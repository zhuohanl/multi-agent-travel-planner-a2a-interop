"""
Unit tests for ConsultationIndexStore.

Tests cover:
- Basic CRUD operations (get, add, delete)
- Non-existent consultation handling
- Workflow version tracking
- Serialization/deserialization
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator.storage.consultation_index import (
    ConsultationIndexEntry,
    ConsultationIndexStore,
    InMemoryConsultationIndexStore,
    CONSULTATION_INDEX_TTL,
)


class TestConsultationIndexEntry:
    """Tests for ConsultationIndexEntry dataclass."""

    def test_default_values(self) -> None:
        """Test that defaults are applied correctly."""
        entry = ConsultationIndexEntry(
            consultation_id="cons_123",
            session_id="sess_456",
        )

        assert entry.consultation_id == "cons_123"
        assert entry.session_id == "sess_456"
        assert entry.workflow_version == 1  # Default

    def test_custom_workflow_version(self) -> None:
        """Test custom workflow version."""
        entry = ConsultationIndexEntry(
            consultation_id="cons_123",
            session_id="sess_456",
            workflow_version=5,
        )

        assert entry.workflow_version == 5

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        entry = ConsultationIndexEntry(
            consultation_id="cons_abc123",
            session_id="sess_xyz789",
            workflow_version=3,
        )

        doc = entry.to_dict()

        assert doc["id"] == "cons_abc123"
        assert doc["consultation_id"] == "cons_abc123"
        assert doc["session_id"] == "sess_xyz789"
        assert doc["workflow_version"] == 3
        assert doc["ttl"] == CONSULTATION_INDEX_TTL

    def test_from_dict(self) -> None:
        """Test deserialization from dictionary."""
        doc = {
            "id": "cons_abc123",
            "consultation_id": "cons_abc123",
            "session_id": "sess_xyz789",
            "workflow_version": 2,
        }

        entry = ConsultationIndexEntry.from_dict(doc)

        assert entry.consultation_id == "cons_abc123"
        assert entry.session_id == "sess_xyz789"
        assert entry.workflow_version == 2

    def test_from_dict_with_missing_fields(self) -> None:
        """Test deserialization handles missing fields gracefully."""
        doc = {"id": "cons_minimal"}

        entry = ConsultationIndexEntry.from_dict(doc)

        assert entry.consultation_id == "cons_minimal"
        assert entry.session_id == ""
        assert entry.workflow_version == 1

    def test_roundtrip_serialization(self) -> None:
        """Test that to_dict and from_dict are inverses."""
        original = ConsultationIndexEntry(
            consultation_id="cons_roundtrip",
            session_id="sess_rt",
            workflow_version=7,
        )

        doc = original.to_dict()
        restored = ConsultationIndexEntry.from_dict(doc)

        assert restored.consultation_id == original.consultation_id
        assert restored.session_id == original.session_id
        assert restored.workflow_version == original.workflow_version


class TestInMemoryConsultationIndexStore:
    """Tests for InMemoryConsultationIndexStore."""

    @pytest.fixture
    def store(self) -> InMemoryConsultationIndexStore:
        """Create a fresh in-memory store for each test."""
        return InMemoryConsultationIndexStore()

    @pytest.mark.asyncio
    async def test_get_session_for_consultation(
        self, store: InMemoryConsultationIndexStore
    ) -> None:
        """Test retrieving an existing index entry."""
        await store.add_session(
            session_id="sess_test",
            consultation_id="cons_test",
            workflow_version=1,
        )

        result = await store.get_session_for_consultation("cons_test")

        assert result is not None
        assert result.consultation_id == "cons_test"
        assert result.session_id == "sess_test"
        assert result.workflow_version == 1

    @pytest.mark.asyncio
    async def test_get_session_not_found(
        self, store: InMemoryConsultationIndexStore
    ) -> None:
        """Test retrieving a non-existent entry returns None."""
        result = await store.get_session_for_consultation("cons_nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_add_session_includes_workflow_version(
        self, store: InMemoryConsultationIndexStore
    ) -> None:
        """Test adding an entry includes workflow_version."""
        result = await store.add_session(
            session_id="sess_new",
            consultation_id="cons_new",
            workflow_version=3,
        )

        assert result.session_id == "sess_new"
        assert result.consultation_id == "cons_new"
        assert result.workflow_version == 3

        # Verify it's persisted
        retrieved = await store.get_session_for_consultation("cons_new")
        assert retrieved is not None
        assert retrieved.workflow_version == 3

    @pytest.mark.asyncio
    async def test_add_session_updates_existing(
        self, store: InMemoryConsultationIndexStore
    ) -> None:
        """Test that add_session updates an existing entry (upsert)."""
        # Create initial entry
        await store.add_session(
            session_id="sess_old",
            consultation_id="cons_update",
            workflow_version=1,
        )

        # Update with new session and version
        await store.add_session(
            session_id="sess_new",
            consultation_id="cons_update",
            workflow_version=2,
        )

        # Verify updated
        result = await store.get_session_for_consultation("cons_update")
        assert result is not None
        assert result.session_id == "sess_new"
        assert result.workflow_version == 2

    @pytest.mark.asyncio
    async def test_delete_consultation(
        self, store: InMemoryConsultationIndexStore
    ) -> None:
        """Test deleting an existing entry."""
        await store.add_session(
            session_id="sess_delete",
            consultation_id="cons_delete",
        )

        result = await store.delete_consultation("cons_delete")

        assert result is True
        assert await store.get_session_for_consultation("cons_delete") is None

    @pytest.mark.asyncio
    async def test_delete_consultation_not_found(
        self, store: InMemoryConsultationIndexStore
    ) -> None:
        """Test deleting a non-existent entry returns False."""
        result = await store.delete_consultation("cons_nonexistent")

        assert result is False

    def test_clear(self, store: InMemoryConsultationIndexStore) -> None:
        """Test clearing the store."""
        # Just verify it doesn't raise
        store.clear()


class TestConsultationIndexStore:
    """Tests for ConsultationIndexStore with mocked Cosmos container."""

    @pytest.fixture
    def mock_container(self) -> MagicMock:
        """Create a mock Cosmos container."""
        container = MagicMock()
        container.read_item = AsyncMock()
        container.upsert_item = AsyncMock()
        container.delete_item = AsyncMock()
        return container

    @pytest.fixture
    def store(self, mock_container: MagicMock) -> ConsultationIndexStore:
        """Create a ConsultationIndexStore with mocked container."""
        return ConsultationIndexStore(mock_container)

    @pytest.mark.asyncio
    async def test_get_session_for_consultation(
        self, store: ConsultationIndexStore, mock_container: MagicMock
    ) -> None:
        """Test retrieving an existing entry from Cosmos."""
        mock_container.read_item.return_value = {
            "id": "cons_cosmos",
            "consultation_id": "cons_cosmos",
            "session_id": "sess_cosmos",
            "workflow_version": 2,
        }

        result = await store.get_session_for_consultation("cons_cosmos")

        assert result is not None
        assert result.consultation_id == "cons_cosmos"
        assert result.session_id == "sess_cosmos"
        assert result.workflow_version == 2
        mock_container.read_item.assert_called_once_with(
            item="cons_cosmos",
            partition_key="cons_cosmos",
        )

    @pytest.mark.asyncio
    async def test_get_session_not_found(
        self, store: ConsultationIndexStore, mock_container: MagicMock
    ) -> None:
        """Test retrieving a non-existent entry returns None."""
        # Simulate 404 error
        error = Exception("Not found")
        error.status_code = 404  # type: ignore[attr-defined]
        mock_container.read_item.side_effect = error

        result = await store.get_session_for_consultation("cons_missing")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_session_error(
        self, store: ConsultationIndexStore, mock_container: MagicMock
    ) -> None:
        """Test that non-404 errors are raised."""
        error = Exception("Server error")
        error.status_code = 500  # type: ignore[attr-defined]
        mock_container.read_item.side_effect = error

        with pytest.raises(Exception) as exc_info:
            await store.get_session_for_consultation("cons_error")

        assert "Server error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_add_session_includes_workflow_version(
        self, store: ConsultationIndexStore, mock_container: MagicMock
    ) -> None:
        """Test adding an entry includes workflow_version."""
        mock_container.upsert_item.return_value = {
            "id": "cons_new",
            "consultation_id": "cons_new",
            "session_id": "sess_new",
            "workflow_version": 4,
        }

        result = await store.add_session(
            session_id="sess_new",
            consultation_id="cons_new",
            workflow_version=4,
        )

        assert result.session_id == "sess_new"
        assert result.workflow_version == 4
        mock_container.upsert_item.assert_called_once()
        call_args = mock_container.upsert_item.call_args
        body = call_args.kwargs["body"]
        assert body["session_id"] == "sess_new"
        assert body["consultation_id"] == "cons_new"
        assert body["workflow_version"] == 4
        assert body["ttl"] == CONSULTATION_INDEX_TTL

    @pytest.mark.asyncio
    async def test_add_session_default_workflow_version(
        self, store: ConsultationIndexStore, mock_container: MagicMock
    ) -> None:
        """Test adding an entry with default workflow_version."""
        mock_container.upsert_item.return_value = {
            "id": "cons_default",
            "consultation_id": "cons_default",
            "session_id": "sess_default",
            "workflow_version": 1,
        }

        await store.add_session(
            session_id="sess_default",
            consultation_id="cons_default",
        )

        call_args = mock_container.upsert_item.call_args
        body = call_args.kwargs["body"]
        assert body["workflow_version"] == 1

    @pytest.mark.asyncio
    async def test_delete_consultation(
        self, store: ConsultationIndexStore, mock_container: MagicMock
    ) -> None:
        """Test deleting an existing entry."""
        mock_container.delete_item.return_value = None

        result = await store.delete_consultation("cons_delete")

        assert result is True
        mock_container.delete_item.assert_called_once_with(
            item="cons_delete",
            partition_key="cons_delete",
        )

    @pytest.mark.asyncio
    async def test_delete_consultation_not_found(
        self, store: ConsultationIndexStore, mock_container: MagicMock
    ) -> None:
        """Test deleting a non-existent entry returns False."""
        error = Exception("Not found")
        error.status_code = 404  # type: ignore[attr-defined]
        mock_container.delete_item.side_effect = error

        result = await store.delete_consultation("cons_missing")

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_consultation_error(
        self, store: ConsultationIndexStore, mock_container: MagicMock
    ) -> None:
        """Test that non-404 errors on delete are raised."""
        error = Exception("Server error")
        error.status_code = 500  # type: ignore[attr-defined]
        mock_container.delete_item.side_effect = error

        with pytest.raises(Exception) as exc_info:
            await store.delete_consultation("cons_error")

        assert "Server error" in str(exc_info.value)
