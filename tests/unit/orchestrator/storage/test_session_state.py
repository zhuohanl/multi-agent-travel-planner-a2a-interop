"""
Unit tests for WorkflowStateStore.

Tests cover:
- Basic CRUD operations (get, save, delete)
- Optimistic locking with etag
- Non-existent session handling
- Serialization/deserialization
"""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator.storage.session_state import (
    ConflictError,
    InMemoryWorkflowStateStore,
    WorkflowStateData,
    WorkflowStateStore,
    WORKFLOW_STATE_TTL,
)


class TestWorkflowStateData:
    """Tests for WorkflowStateData dataclass."""

    def test_default_values(self) -> None:
        """Test that defaults are applied correctly."""
        state = WorkflowStateData(session_id="sess_123")

        assert state.session_id == "sess_123"
        assert state.consultation_id is None
        assert state.phase == "CLARIFICATION"
        assert state.checkpoint is None
        assert state.current_step is None
        assert state.itinerary_id is None
        assert state.workflow_version == 1
        assert state.agent_context_ids == {}
        assert state.etag is None
        assert isinstance(state.created_at, datetime)
        assert isinstance(state.updated_at, datetime)

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        now = datetime.now(timezone.utc)
        state = WorkflowStateData(
            session_id="sess_abc123",
            consultation_id="cons_xyz789",
            phase="DISCOVERY_PLANNING",
            checkpoint="itinerary_approval",
            current_step="approval",
            itinerary_id=None,
            workflow_version=2,
            agent_context_ids={
                "clarifier": {"context_id": "ctx_clar_001", "task_id": None}
            },
            created_at=now,
            updated_at=now,
        )

        doc = state.to_dict()

        assert doc["id"] == "sess_abc123"
        assert doc["session_id"] == "sess_abc123"
        assert doc["consultation_id"] == "cons_xyz789"
        assert doc["phase"] == "DISCOVERY_PLANNING"
        assert doc["checkpoint"] == "itinerary_approval"
        assert doc["current_step"] == "approval"
        assert doc["itinerary_id"] is None
        assert doc["workflow_version"] == 2
        assert doc["agent_context_ids"] == {
            "clarifier": {"context_id": "ctx_clar_001", "task_id": None}
        }
        assert doc["ttl"] == WORKFLOW_STATE_TTL
        assert "created_at" in doc
        assert "updated_at" in doc

    def test_from_dict(self) -> None:
        """Test deserialization from dictionary."""
        now = datetime.now(timezone.utc)
        doc = {
            "id": "sess_abc123",
            "session_id": "sess_abc123",
            "consultation_id": "cons_xyz789",
            "phase": "BOOKING",
            "checkpoint": None,
            "current_step": "booking",
            "itinerary_id": "itn_m1n2o3",
            "workflow_version": 3,
            "agent_context_ids": {
                "stay": {"context_id": "ctx_stay_001", "task_id": "task_stay_001"}
            },
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "_etag": '"0x8D9F..."',
        }

        state = WorkflowStateData.from_dict(doc)

        assert state.session_id == "sess_abc123"
        assert state.consultation_id == "cons_xyz789"
        assert state.phase == "BOOKING"
        assert state.checkpoint is None
        assert state.current_step == "booking"
        assert state.itinerary_id == "itn_m1n2o3"
        assert state.workflow_version == 3
        assert state.agent_context_ids == {
            "stay": {"context_id": "ctx_stay_001", "task_id": "task_stay_001"}
        }
        assert state.etag == '"0x8D9F..."'

    def test_from_dict_with_missing_fields(self) -> None:
        """Test deserialization handles missing fields gracefully."""
        doc = {"id": "sess_minimal"}

        state = WorkflowStateData.from_dict(doc)

        assert state.session_id == "sess_minimal"
        assert state.phase == "CLARIFICATION"
        assert state.workflow_version == 1
        assert state.agent_context_ids == {}

    def test_roundtrip_serialization(self) -> None:
        """Test that to_dict and from_dict are inverses."""
        original = WorkflowStateData(
            session_id="sess_roundtrip",
            consultation_id="cons_rt",
            phase="DISCOVERY_IN_PROGRESS",
            checkpoint=None,
            current_step="searching",
            workflow_version=5,
        )

        doc = original.to_dict()
        restored = WorkflowStateData.from_dict(doc)

        assert restored.session_id == original.session_id
        assert restored.consultation_id == original.consultation_id
        assert restored.phase == original.phase
        assert restored.checkpoint == original.checkpoint
        assert restored.current_step == original.current_step
        assert restored.workflow_version == original.workflow_version


class TestInMemoryWorkflowStateStore:
    """Tests for InMemoryWorkflowStateStore."""

    @pytest.fixture
    def store(self) -> InMemoryWorkflowStateStore:
        """Create a fresh in-memory store for each test."""
        return InMemoryWorkflowStateStore()

    @pytest.mark.asyncio
    async def test_get_state_existing(self, store: InMemoryWorkflowStateStore) -> None:
        """Test retrieving an existing state."""
        state = WorkflowStateData(
            session_id="sess_test",
            consultation_id="cons_test",
            phase="CLARIFICATION",
        )
        await store.save_state(state)

        result = await store.get_state("sess_test")

        assert result is not None
        assert result.session_id == "sess_test"
        assert result.consultation_id == "cons_test"
        assert result.phase == "CLARIFICATION"

    @pytest.mark.asyncio
    async def test_get_state_not_found(
        self, store: InMemoryWorkflowStateStore
    ) -> None:
        """Test retrieving a non-existent state returns None."""
        result = await store.get_state("sess_nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_save_state_creates(
        self, store: InMemoryWorkflowStateStore
    ) -> None:
        """Test saving creates a new state."""
        state = WorkflowStateData(
            session_id="sess_new",
            phase="DISCOVERY_PLANNING",
        )

        result = await store.save_state(state)

        assert result.session_id == "sess_new"
        assert result.etag is not None

        # Verify it's persisted
        retrieved = await store.get_state("sess_new")
        assert retrieved is not None
        assert retrieved.phase == "DISCOVERY_PLANNING"

    @pytest.mark.asyncio
    async def test_save_state_updates(
        self, store: InMemoryWorkflowStateStore
    ) -> None:
        """Test saving updates an existing state."""
        # Create initial state
        state = WorkflowStateData(
            session_id="sess_update",
            phase="CLARIFICATION",
        )
        saved = await store.save_state(state)

        # Update it
        state.phase = "DISCOVERY_PLANNING"
        state.checkpoint = "itinerary_approval"
        updated = await store.save_state(state)

        assert updated.phase == "DISCOVERY_PLANNING"
        assert updated.checkpoint == "itinerary_approval"
        # etag should change
        assert updated.etag != saved.etag

    @pytest.mark.asyncio
    async def test_save_state_with_etag_success(
        self, store: InMemoryWorkflowStateStore
    ) -> None:
        """Test saving with correct etag succeeds."""
        state = WorkflowStateData(session_id="sess_etag")
        saved = await store.save_state(state)

        # Update with correct etag
        state.phase = "BOOKING"
        result = await store.save_state(state, if_match=saved.etag)

        assert result.phase == "BOOKING"

    @pytest.mark.asyncio
    async def test_save_state_with_etag_conflict(
        self, store: InMemoryWorkflowStateStore
    ) -> None:
        """Test saving with stale etag raises ConflictError."""
        state = WorkflowStateData(session_id="sess_conflict")
        await store.save_state(state)

        # Try to update with wrong etag
        state.phase = "BOOKING"
        with pytest.raises(ConflictError) as exc_info:
            await store.save_state(state, if_match="wrong_etag")

        assert exc_info.value.session_id == "sess_conflict"

    @pytest.mark.asyncio
    async def test_delete_state_existing(
        self, store: InMemoryWorkflowStateStore
    ) -> None:
        """Test deleting an existing state."""
        state = WorkflowStateData(session_id="sess_delete")
        await store.save_state(state)

        result = await store.delete_state("sess_delete")

        assert result is True
        assert await store.get_state("sess_delete") is None

    @pytest.mark.asyncio
    async def test_delete_state_not_found(
        self, store: InMemoryWorkflowStateStore
    ) -> None:
        """Test deleting a non-existent state returns False."""
        result = await store.delete_state("sess_nonexistent")

        assert result is False

    def test_clear(self, store: InMemoryWorkflowStateStore) -> None:
        """Test clearing the store."""
        # This is synchronous in the implementation
        store.clear()
        # Just verify it doesn't raise


class TestWorkflowStateStore:
    """Tests for WorkflowStateStore with mocked Cosmos container."""

    @pytest.fixture
    def mock_container(self) -> MagicMock:
        """Create a mock Cosmos container."""
        container = MagicMock()
        container.read_item = AsyncMock()
        container.upsert_item = AsyncMock()
        container.replace_item = AsyncMock()
        container.delete_item = AsyncMock()
        return container

    @pytest.fixture
    def store(self, mock_container: MagicMock) -> WorkflowStateStore:
        """Create a WorkflowStateStore with mocked container."""
        return WorkflowStateStore(mock_container)

    @pytest.mark.asyncio
    async def test_get_state_existing(
        self, store: WorkflowStateStore, mock_container: MagicMock
    ) -> None:
        """Test retrieving an existing state from Cosmos."""
        mock_container.read_item.return_value = {
            "id": "sess_cosmos",
            "session_id": "sess_cosmos",
            "consultation_id": "cons_cosmos",
            "phase": "CLARIFICATION",
            "_etag": '"etag_123"',
        }

        result = await store.get_state("sess_cosmos")

        assert result is not None
        assert result.session_id == "sess_cosmos"
        assert result.consultation_id == "cons_cosmos"
        assert result.etag == '"etag_123"'
        mock_container.read_item.assert_called_once_with(
            item="sess_cosmos",
            partition_key="sess_cosmos",
        )

    @pytest.mark.asyncio
    async def test_get_state_not_found(
        self, store: WorkflowStateStore, mock_container: MagicMock
    ) -> None:
        """Test retrieving a non-existent state returns None."""
        # Simulate 404 error
        error = Exception("Not found")
        error.status_code = 404  # type: ignore[attr-defined]
        mock_container.read_item.side_effect = error

        result = await store.get_state("sess_missing")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_state_error(
        self, store: WorkflowStateStore, mock_container: MagicMock
    ) -> None:
        """Test that non-404 errors are raised."""
        error = Exception("Server error")
        error.status_code = 500  # type: ignore[attr-defined]
        mock_container.read_item.side_effect = error

        with pytest.raises(Exception) as exc_info:
            await store.get_state("sess_error")

        assert "Server error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_save_state_creates(
        self, store: WorkflowStateStore, mock_container: MagicMock
    ) -> None:
        """Test saving creates a new state via upsert."""
        mock_container.upsert_item.return_value = {
            "id": "sess_create",
            "session_id": "sess_create",
            "phase": "CLARIFICATION",
            "_etag": '"new_etag"',
        }

        state = WorkflowStateData(session_id="sess_create")
        result = await store.save_state(state)

        assert result.etag == '"new_etag"'
        mock_container.upsert_item.assert_called_once()
        call_args = mock_container.upsert_item.call_args
        assert call_args.kwargs["body"]["session_id"] == "sess_create"
        assert call_args.kwargs["body"]["ttl"] == WORKFLOW_STATE_TTL

    @pytest.mark.asyncio
    async def test_save_state_updates(
        self, store: WorkflowStateStore, mock_container: MagicMock
    ) -> None:
        """Test saving updates an existing state."""
        mock_container.upsert_item.return_value = {
            "id": "sess_update",
            "session_id": "sess_update",
            "phase": "BOOKING",
            "_etag": '"updated_etag"',
        }

        state = WorkflowStateData(session_id="sess_update", phase="BOOKING")
        result = await store.save_state(state)

        assert result.phase == "BOOKING"
        assert result.etag == '"updated_etag"'

    @pytest.mark.asyncio
    async def test_save_state_with_etag_uses_replace(
        self, store: WorkflowStateStore, mock_container: MagicMock
    ) -> None:
        """Test saving with etag uses replace_item for optimistic locking."""
        mock_container.replace_item.return_value = {
            "id": "sess_replace",
            "session_id": "sess_replace",
            "phase": "BOOKING",
            "_etag": '"new_etag"',
        }

        state = WorkflowStateData(session_id="sess_replace", phase="BOOKING")
        result = await store.save_state(state, if_match='"old_etag"')

        assert result.etag == '"new_etag"'
        mock_container.replace_item.assert_called_once()
        call_args = mock_container.replace_item.call_args
        assert call_args.kwargs["item"] == "sess_replace"
        assert call_args.kwargs["if_match"] == '"old_etag"'

    @pytest.mark.asyncio
    async def test_save_state_conflict(
        self, store: WorkflowStateStore, mock_container: MagicMock
    ) -> None:
        """Test saving with stale etag raises ConflictError."""
        # Simulate 412 Precondition Failed
        error = Exception("Precondition failed")
        error.status_code = 412  # type: ignore[attr-defined]
        mock_container.replace_item.side_effect = error

        state = WorkflowStateData(session_id="sess_conflict")
        with pytest.raises(ConflictError) as exc_info:
            await store.save_state(state, if_match='"stale_etag"')

        assert exc_info.value.session_id == "sess_conflict"

    @pytest.mark.asyncio
    async def test_delete_state_existing(
        self, store: WorkflowStateStore, mock_container: MagicMock
    ) -> None:
        """Test deleting an existing state."""
        mock_container.delete_item.return_value = None

        result = await store.delete_state("sess_delete")

        assert result is True
        mock_container.delete_item.assert_called_once_with(
            item="sess_delete",
            partition_key="sess_delete",
        )

    @pytest.mark.asyncio
    async def test_delete_state_not_found(
        self, store: WorkflowStateStore, mock_container: MagicMock
    ) -> None:
        """Test deleting a non-existent state returns False."""
        error = Exception("Not found")
        error.status_code = 404  # type: ignore[attr-defined]
        mock_container.delete_item.side_effect = error

        result = await store.delete_state("sess_missing")

        assert result is False


class TestConflictError:
    """Tests for ConflictError exception."""

    def test_with_session_id(self) -> None:
        """Test error includes session_id."""
        error = ConflictError("sess_123")
        assert error.session_id == "sess_123"
        assert "sess_123" in str(error)

    def test_with_custom_message(self) -> None:
        """Test error with custom message."""
        error = ConflictError("sess_123", "Custom conflict message")
        assert error.session_id == "sess_123"
        assert "Custom conflict message" in str(error)
