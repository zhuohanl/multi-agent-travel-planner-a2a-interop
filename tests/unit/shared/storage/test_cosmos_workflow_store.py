"""
Unit tests for CosmosWorkflowStore.

Tests cover:
- Protocol compliance verification
- Delegation to underlying stores
- get_by_session, get_by_consultation, get_by_booking lookups
- save with optimistic locking
- Consultation index operations
- Booking index operations
- Consultation summary operations

Per ticket ORCH-097 acceptance criteria:
- CosmosWorkflowStore implements all WorkflowStoreProtocol methods
- CosmosWorkflowStore delegates session/consultation/booking lookups to the correct containers
"""

from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.orchestrator.models.workflow_state import Phase, WorkflowState
from src.orchestrator.storage.session_state import WorkflowStateData
from src.shared.storage.cosmos_workflow_store import CosmosWorkflowStore
from src.shared.storage.protocols import WorkflowStoreProtocol


@pytest.fixture
def mock_state_store() -> MagicMock:
    """Mock WorkflowStateStore for testing."""
    mock = MagicMock()
    mock.get_state = AsyncMock(return_value=None)
    mock.save_state = AsyncMock()
    return mock


@pytest.fixture
def mock_consultation_index_store() -> MagicMock:
    """Mock ConsultationIndexStore for testing."""
    mock = MagicMock()
    mock.get_session_for_consultation = AsyncMock(return_value=None)
    mock.add_session = AsyncMock()
    mock.delete_consultation = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def mock_booking_index_store() -> MagicMock:
    """Mock BookingIndexStore for testing."""
    mock = MagicMock()
    mock.get_session_for_booking = AsyncMock(return_value=None)
    mock.add_booking_index = AsyncMock()
    mock.delete_booking_index = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def mock_consultation_summary_store() -> MagicMock:
    """Mock ConsultationSummaryStore for testing."""
    mock = MagicMock()
    mock.get_summary = AsyncMock(return_value=None)
    mock.save_summary = AsyncMock()
    return mock


@pytest.fixture
def store(
    mock_state_store: MagicMock,
    mock_consultation_index_store: MagicMock,
    mock_booking_index_store: MagicMock,
    mock_consultation_summary_store: MagicMock,
) -> CosmosWorkflowStore:
    """Create CosmosWorkflowStore with mocked dependencies."""
    return CosmosWorkflowStore(
        state_store=mock_state_store,
        consultation_index_store=mock_consultation_index_store,
        booking_index_store=mock_booking_index_store,
        consultation_summary_store=mock_consultation_summary_store,
    )


@pytest.fixture
def sample_state() -> WorkflowState:
    """Provide a sample WorkflowState for testing."""
    return WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_test456",
        workflow_version=1,
        phase=Phase.CLARIFICATION,
        checkpoint=None,
        current_step="gathering",
    )


@pytest.fixture
def sample_state_data() -> WorkflowStateData:
    """Provide sample WorkflowStateData returned from underlying store."""
    return WorkflowStateData(
        session_id="sess_test123",
        consultation_id="cons_test456",
        phase="clarification",
        checkpoint=None,
        current_step="gathering",
        workflow_version=1,
        agent_context_ids={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        etag="etag_123",
    )


class TestProtocolCompliance:
    """Verify CosmosWorkflowStore implements WorkflowStoreProtocol."""

    def test_implements_protocol(self, store: CosmosWorkflowStore) -> None:
        """Store should implement the WorkflowStoreProtocol."""
        assert isinstance(store, WorkflowStoreProtocol)

    def test_has_required_methods(self, store: CosmosWorkflowStore) -> None:
        """Store should have all required protocol methods."""
        # Primary state operations
        assert hasattr(store, "get_by_session")
        assert hasattr(store, "get_by_consultation")
        assert hasattr(store, "get_by_booking")
        assert hasattr(store, "save")

        # Consultation index operations
        assert hasattr(store, "create_consultation_index")
        assert hasattr(store, "delete_consultation_index")

        # Consultation summary operations
        assert hasattr(store, "upsert_consultation_summary")
        assert hasattr(store, "get_consultation_summary")

        # Booking index operations
        assert hasattr(store, "create_booking_index")
        assert hasattr(store, "delete_booking_index")


class TestGetBySession:
    """Test get_by_session delegation."""

    @pytest.mark.asyncio
    async def test_get_by_session_delegates_to_state_store(
        self,
        store: CosmosWorkflowStore,
        mock_state_store: MagicMock,
        sample_state_data: WorkflowStateData,
    ) -> None:
        """Should delegate to state_store.get_state."""
        mock_state_store.get_state.return_value = sample_state_data

        result = await store.get_by_session("sess_test123")

        mock_state_store.get_state.assert_called_once_with("sess_test123")
        assert result is not None
        assert result.session_id == "sess_test123"

    @pytest.mark.asyncio
    async def test_get_by_session_returns_none_when_not_found(
        self,
        store: CosmosWorkflowStore,
        mock_state_store: MagicMock,
    ) -> None:
        """Should return None when state not found."""
        mock_state_store.get_state.return_value = None

        result = await store.get_by_session("sess_nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_session_converts_state_data_to_workflow_state(
        self,
        store: CosmosWorkflowStore,
        mock_state_store: MagicMock,
        sample_state_data: WorkflowStateData,
    ) -> None:
        """Should convert WorkflowStateData to WorkflowState."""
        mock_state_store.get_state.return_value = sample_state_data

        result = await store.get_by_session("sess_test123")

        assert result is not None
        assert isinstance(result, WorkflowState)
        assert result.phase == Phase.CLARIFICATION


class TestGetByConsultation:
    """Test get_by_consultation cross-session lookup."""

    @pytest.mark.asyncio
    async def test_get_by_consultation_uses_index(
        self,
        store: CosmosWorkflowStore,
        mock_consultation_index_store: MagicMock,
        mock_state_store: MagicMock,
        sample_state_data: WorkflowStateData,
    ) -> None:
        """Should lookup via consultation index then state store."""
        # Mock index entry
        index_entry = MagicMock()
        index_entry.session_id = "sess_test123"
        index_entry.workflow_version = 1
        mock_consultation_index_store.get_session_for_consultation.return_value = (
            index_entry
        )
        mock_state_store.get_state.return_value = sample_state_data

        result = await store.get_by_consultation("cons_test456")

        mock_consultation_index_store.get_session_for_consultation.assert_called_once_with(
            "cons_test456"
        )
        mock_state_store.get_state.assert_called_once_with("sess_test123")
        assert result is not None
        assert result.consultation_id == "cons_test456"

    @pytest.mark.asyncio
    async def test_get_by_consultation_returns_none_when_index_not_found(
        self,
        store: CosmosWorkflowStore,
        mock_consultation_index_store: MagicMock,
    ) -> None:
        """Should return None when index not found."""
        mock_consultation_index_store.get_session_for_consultation.return_value = None

        result = await store.get_by_consultation("cons_nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_consultation_validates_workflow_version(
        self,
        store: CosmosWorkflowStore,
        mock_consultation_index_store: MagicMock,
        mock_state_store: MagicMock,
        sample_state_data: WorkflowStateData,
    ) -> None:
        """Should return None on workflow_version mismatch."""
        # Index has version 1, state has version 2
        index_entry = MagicMock()
        index_entry.session_id = "sess_test123"
        index_entry.workflow_version = 1  # Version in index
        mock_consultation_index_store.get_session_for_consultation.return_value = (
            index_entry
        )

        # State has version 2 (mismatched)
        sample_state_data.workflow_version = 2
        mock_state_store.get_state.return_value = sample_state_data

        result = await store.get_by_consultation("cons_test456")

        # Should return None due to version mismatch
        assert result is None


class TestGetByBooking:
    """Test get_by_booking booking resumption lookup."""

    @pytest.mark.asyncio
    async def test_get_by_booking_uses_index(
        self,
        store: CosmosWorkflowStore,
        mock_booking_index_store: MagicMock,
        mock_state_store: MagicMock,
        sample_state_data: WorkflowStateData,
    ) -> None:
        """Should lookup via booking index then state store."""
        # Mock index entry
        index_entry = MagicMock()
        index_entry.session_id = "sess_test123"
        mock_booking_index_store.get_session_for_booking.return_value = index_entry
        mock_state_store.get_state.return_value = sample_state_data

        result = await store.get_by_booking("book_test789")

        mock_booking_index_store.get_session_for_booking.assert_called_once_with(
            "book_test789"
        )
        mock_state_store.get_state.assert_called_once_with("sess_test123")
        assert result is not None

    @pytest.mark.asyncio
    async def test_get_by_booking_returns_none_when_index_not_found(
        self,
        store: CosmosWorkflowStore,
        mock_booking_index_store: MagicMock,
    ) -> None:
        """Should return None when index not found."""
        mock_booking_index_store.get_session_for_booking.return_value = None

        result = await store.get_by_booking("book_nonexistent")

        assert result is None


class TestSave:
    """Test save operation with optimistic locking."""

    @pytest.mark.asyncio
    async def test_save_delegates_to_state_store(
        self,
        store: CosmosWorkflowStore,
        mock_state_store: MagicMock,
        sample_state: WorkflowState,
    ) -> None:
        """Should delegate to state_store.save_state."""
        saved_data = WorkflowStateData(
            session_id="sess_test123",
            consultation_id="cons_test456",
            phase="clarification",
            checkpoint=None,
            current_step="gathering",
            workflow_version=1,
            etag="etag_new",
        )
        mock_state_store.save_state.return_value = saved_data

        etag = await store.save(sample_state)

        assert mock_state_store.save_state.called
        assert etag == "etag_new"

    @pytest.mark.asyncio
    async def test_save_passes_etag_for_optimistic_locking(
        self,
        store: CosmosWorkflowStore,
        mock_state_store: MagicMock,
        sample_state: WorkflowState,
    ) -> None:
        """Should pass etag parameter for optimistic locking."""
        saved_data = WorkflowStateData(
            session_id="sess_test123",
            consultation_id="cons_test456",
            phase="clarification",
            workflow_version=1,
            etag="etag_new",
        )
        mock_state_store.save_state.return_value = saved_data

        await store.save(sample_state, etag="etag_old")

        # Verify if_match was passed
        call_args = mock_state_store.save_state.call_args
        assert call_args.kwargs.get("if_match") == "etag_old"

    @pytest.mark.asyncio
    async def test_save_converts_workflow_state_to_state_data(
        self,
        store: CosmosWorkflowStore,
        mock_state_store: MagicMock,
        sample_state: WorkflowState,
    ) -> None:
        """Should convert WorkflowState to WorkflowStateData."""
        saved_data = WorkflowStateData(
            session_id="sess_test123",
            consultation_id="cons_test456",
            phase="clarification",
            workflow_version=1,
            etag="etag_new",
        )
        mock_state_store.save_state.return_value = saved_data

        await store.save(sample_state)

        # Verify WorkflowStateData was passed
        call_args = mock_state_store.save_state.call_args
        state_data = call_args.args[0]
        assert isinstance(state_data, WorkflowStateData)
        assert state_data.session_id == "sess_test123"


class TestConsultationIndexOperations:
    """Test consultation index create and delete."""

    @pytest.mark.asyncio
    async def test_create_consultation_index_delegates(
        self,
        store: CosmosWorkflowStore,
        mock_consultation_index_store: MagicMock,
    ) -> None:
        """Should delegate to consultation_index_store.add_session."""
        await store.create_consultation_index(
            consultation_id="cons_test",
            session_id="sess_test",
            workflow_version=2,
        )

        mock_consultation_index_store.add_session.assert_called_once_with(
            session_id="sess_test",
            consultation_id="cons_test",
            workflow_version=2,
        )

    @pytest.mark.asyncio
    async def test_delete_consultation_index_delegates(
        self,
        store: CosmosWorkflowStore,
        mock_consultation_index_store: MagicMock,
    ) -> None:
        """Should delegate to consultation_index_store.delete_consultation."""
        await store.delete_consultation_index("cons_test")

        mock_consultation_index_store.delete_consultation.assert_called_once_with(
            "cons_test"
        )


class TestBookingIndexOperations:
    """Test booking index create and delete."""

    @pytest.mark.asyncio
    async def test_create_booking_index_delegates(
        self,
        store: CosmosWorkflowStore,
        mock_booking_index_store: MagicMock,
    ) -> None:
        """Should delegate to booking_index_store.add_booking_index."""
        await store.create_booking_index(
            booking_id="book_test",
            session_id="sess_test",
            consultation_id="cons_test",
            trip_end_date=date(2024, 6, 15),
        )

        mock_booking_index_store.add_booking_index.assert_called_once_with(
            booking_id="book_test",
            consultation_id="cons_test",
            session_id="sess_test",
            trip_end_date=date(2024, 6, 15),
        )

    @pytest.mark.asyncio
    async def test_delete_booking_index_delegates(
        self,
        store: CosmosWorkflowStore,
        mock_booking_index_store: MagicMock,
    ) -> None:
        """Should delegate to booking_index_store.delete_booking_index."""
        await store.delete_booking_index("book_test")

        mock_booking_index_store.delete_booking_index.assert_called_once_with(
            "book_test"
        )


class TestConsultationSummaryOperations:
    """Test consultation summary operations."""

    @pytest.mark.asyncio
    async def test_upsert_consultation_summary_delegates(
        self,
        store: CosmosWorkflowStore,
        mock_consultation_summary_store: MagicMock,
    ) -> None:
        """Should delegate to consultation_summary_store.save_summary."""
        await store.upsert_consultation_summary(
            consultation_id="cons_test",
            session_id="sess_test",
            trip_spec_summary={"destination": "Tokyo"},
            itinerary_ids=["itn_001"],
            booking_ids=["book_001"],
            status="active",
            trip_end_date=date(2024, 6, 15),
        )

        mock_consultation_summary_store.save_summary.assert_called_once()
        summary = mock_consultation_summary_store.save_summary.call_args.args[0]
        assert summary.consultation_id == "cons_test"
        assert summary.session_id == "sess_test"
        assert summary.trip_spec_summary == {"destination": "Tokyo"}

    @pytest.mark.asyncio
    async def test_get_consultation_summary_delegates(
        self,
        store: CosmosWorkflowStore,
        mock_consultation_summary_store: MagicMock,
    ) -> None:
        """Should delegate to consultation_summary_store.get_summary."""
        # Mock summary with to_dict method
        mock_summary = MagicMock()
        mock_summary.to_dict.return_value = {
            "consultation_id": "cons_test",
            "trip_spec_summary": {"destination": "Tokyo"},
        }
        mock_consultation_summary_store.get_summary.return_value = mock_summary

        result = await store.get_consultation_summary("cons_test")

        mock_consultation_summary_store.get_summary.assert_called_once_with("cons_test")
        assert result is not None
        assert result["consultation_id"] == "cons_test"

    @pytest.mark.asyncio
    async def test_get_consultation_summary_returns_none_when_not_found(
        self,
        store: CosmosWorkflowStore,
        mock_consultation_summary_store: MagicMock,
    ) -> None:
        """Should return None when summary not found."""
        mock_consultation_summary_store.get_summary.return_value = None

        result = await store.get_consultation_summary("cons_nonexistent")

        assert result is None


class TestFromContainers:
    """Test the from_containers factory method."""

    def test_from_containers_creates_stores(self) -> None:
        """Should create CosmosWorkflowStore from container clients."""
        # Patch at the source modules where the classes are defined
        with patch(
            "src.orchestrator.storage.session_state.WorkflowStateStore"
        ) as mock_state_store_class, patch(
            "src.orchestrator.storage.consultation_index.ConsultationIndexStore"
        ) as mock_consultation_index_class, patch(
            "src.orchestrator.storage.booking_index.BookingIndexStore"
        ) as mock_booking_index_class, patch(
            "src.orchestrator.storage.consultation_summaries.ConsultationSummaryStore"
        ) as mock_summary_class:
            mock_containers = {
                "workflow_states": MagicMock(),
                "consultation_index": MagicMock(),
                "booking_index": MagicMock(),
                "consultation_summaries": MagicMock(),
            }

            store = CosmosWorkflowStore.from_containers(
                workflow_states_container=mock_containers["workflow_states"],
                consultation_index_container=mock_containers["consultation_index"],
                booking_index_container=mock_containers["booking_index"],
                consultation_summaries_container=mock_containers[
                    "consultation_summaries"
                ],
            )

            assert isinstance(store, CosmosWorkflowStore)
            mock_state_store_class.assert_called_once_with(
                mock_containers["workflow_states"]
            )
            mock_consultation_index_class.assert_called_once_with(
                mock_containers["consultation_index"]
            )
            mock_booking_index_class.assert_called_once_with(
                mock_containers["booking_index"]
            )
            mock_summary_class.assert_called_once_with(
                mock_containers["consultation_summaries"]
            )
