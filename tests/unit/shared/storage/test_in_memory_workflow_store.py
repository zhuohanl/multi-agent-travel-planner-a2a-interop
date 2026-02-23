"""
Unit tests for InMemoryWorkflowStore.

Tests cover:
- Save and get by session (primary lookup)
- Get by consultation (cross-session lookup)
- Get by booking (booking resumption lookup)
- Consultation index operations
- Booking index operations
- Consultation summary operations
- Optimistic locking (etag validation)
- Testing utilities (clear, counts)

Per ticket ORCH-095 acceptance criteria:
- InMemoryWorkflowStore returns WorkflowState for session/consultation/booking lookups
- InMemoryWorkflowStore supports consultation summary upsert/get
- save returns updated etag value for WorkflowState
"""

import pytest

from src.orchestrator.models.workflow_state import Phase, WorkflowState
from src.shared.storage.in_memory_workflow_store import (
    ConflictError,
    InMemoryWorkflowStore,
)
from src.shared.storage.protocols import WorkflowStoreProtocol


@pytest.fixture
def store() -> InMemoryWorkflowStore:
    """Provide a fresh in-memory store for each test."""
    return InMemoryWorkflowStore()


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


class TestProtocolCompliance:
    """Verify InMemoryWorkflowStore implements WorkflowStoreProtocol."""

    def test_implements_protocol(self, store: InMemoryWorkflowStore) -> None:
        """Store should implement the WorkflowStoreProtocol."""
        # Check that store is an instance of the protocol
        assert isinstance(store, WorkflowStoreProtocol)

    def test_has_required_methods(self, store: InMemoryWorkflowStore) -> None:
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


class TestSaveAndGetBySession:
    """Test primary save and get_by_session operations."""

    @pytest.mark.asyncio
    async def test_save_and_get_by_session(
        self, store: InMemoryWorkflowStore, sample_state: WorkflowState
    ) -> None:
        """Should save and retrieve workflow state by session_id."""
        # Save state
        etag = await store.save(sample_state)
        assert etag is not None
        assert etag.startswith("etag_")

        # Retrieve state
        retrieved = await store.get_by_session(sample_state.session_id)
        assert retrieved is not None
        assert retrieved.session_id == sample_state.session_id
        assert retrieved.consultation_id == sample_state.consultation_id
        assert retrieved.phase == sample_state.phase

    @pytest.mark.asyncio
    async def test_get_by_session_not_found(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should return None when session not found."""
        result = await store.get_by_session("sess_nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_updates_existing(
        self, store: InMemoryWorkflowStore, sample_state: WorkflowState
    ) -> None:
        """Should update existing state when saving again."""
        # Save initial state
        await store.save(sample_state)

        # Modify and save again
        sample_state.phase = Phase.DISCOVERY_IN_PROGRESS
        sample_state.current_step = "discovering"
        await store.save(sample_state)

        # Verify update
        retrieved = await store.get_by_session(sample_state.session_id)
        assert retrieved is not None
        assert retrieved.phase == Phase.DISCOVERY_IN_PROGRESS
        assert retrieved.current_step == "discovering"

    @pytest.mark.asyncio
    async def test_save_returns_new_etag(
        self, store: InMemoryWorkflowStore, sample_state: WorkflowState
    ) -> None:
        """Each save should return a unique etag."""
        etag1 = await store.save(sample_state)
        etag2 = await store.save(sample_state)

        assert etag1 != etag2

    @pytest.mark.asyncio
    async def test_save_with_etag_success(
        self, store: InMemoryWorkflowStore, sample_state: WorkflowState
    ) -> None:
        """Should succeed with correct etag."""
        # Save and get etag
        etag = await store.save(sample_state)

        # Save again with correct etag
        sample_state.current_step = "updated"
        new_etag = await store.save(sample_state, etag=etag)

        assert new_etag != etag

        # Verify update
        retrieved = await store.get_by_session(sample_state.session_id)
        assert retrieved is not None
        assert retrieved.current_step == "updated"

    @pytest.mark.asyncio
    async def test_save_with_etag_conflict(
        self, store: InMemoryWorkflowStore, sample_state: WorkflowState
    ) -> None:
        """Should raise ConflictError with incorrect etag."""
        # Save initial state
        await store.save(sample_state)

        # Try to save with wrong etag
        with pytest.raises(ConflictError) as exc_info:
            await store.save(sample_state, etag="wrong_etag")

        assert exc_info.value.session_id == sample_state.session_id


class TestGetByConsultation:
    """Test cross-session lookup via consultation_id."""

    @pytest.mark.asyncio
    async def test_get_by_consultation(
        self, store: InMemoryWorkflowStore, sample_state: WorkflowState
    ) -> None:
        """Should retrieve state via consultation index."""
        # Save state
        await store.save(sample_state)

        # Create consultation index
        await store.create_consultation_index(
            consultation_id=sample_state.consultation_id,
            session_id=sample_state.session_id,
            workflow_version=sample_state.workflow_version,
        )

        # Retrieve via consultation_id
        retrieved = await store.get_by_consultation(sample_state.consultation_id)
        assert retrieved is not None
        assert retrieved.session_id == sample_state.session_id
        assert retrieved.consultation_id == sample_state.consultation_id

    @pytest.mark.asyncio
    async def test_get_by_consultation_not_found(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should return None when consultation not found."""
        result = await store.get_by_consultation("cons_nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_consultation_version_mismatch(
        self, store: InMemoryWorkflowStore, sample_state: WorkflowState
    ) -> None:
        """Should return None when workflow_version doesn't match."""
        # Save state with version 2
        sample_state.workflow_version = 2
        await store.save(sample_state)

        # Create consultation index with version 1 (simulating stale index)
        await store.create_consultation_index(
            consultation_id=sample_state.consultation_id,
            session_id=sample_state.session_id,
            workflow_version=1,  # Different from state's version 2
        )

        # Should return None due to version mismatch
        retrieved = await store.get_by_consultation(sample_state.consultation_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_get_by_consultation_no_state(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should return None when index exists but state doesn't."""
        # Create consultation index without saving state
        await store.create_consultation_index(
            consultation_id="cons_orphan",
            session_id="sess_ghost",
            workflow_version=1,
        )

        # Should return None because state doesn't exist
        retrieved = await store.get_by_consultation("cons_orphan")
        assert retrieved is None


class TestGetByBooking:
    """Test booking resumption lookup via booking_id."""

    @pytest.mark.asyncio
    async def test_get_by_booking(
        self, store: InMemoryWorkflowStore, sample_state: WorkflowState
    ) -> None:
        """Should retrieve state via booking index."""
        # Save state
        await store.save(sample_state)

        # Create booking index
        await store.create_booking_index(
            booking_id="book_test789",
            session_id=sample_state.session_id,
            consultation_id=sample_state.consultation_id,
        )

        # Retrieve via booking_id
        retrieved = await store.get_by_booking("book_test789")
        assert retrieved is not None
        assert retrieved.session_id == sample_state.session_id

    @pytest.mark.asyncio
    async def test_get_by_booking_not_found(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should return None when booking not found."""
        result = await store.get_by_booking("book_nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_booking_no_state(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should return None when index exists but state doesn't."""
        # Create booking index without saving state
        await store.create_booking_index(
            booking_id="book_orphan",
            session_id="sess_ghost",
            consultation_id="cons_ghost",
        )

        # Should return None because state doesn't exist
        retrieved = await store.get_by_booking("book_orphan")
        assert retrieved is None


class TestConsultationIndexOperations:
    """Test consultation index create and delete."""

    @pytest.mark.asyncio
    async def test_create_consultation_index(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should create consultation index entry."""
        await store.create_consultation_index(
            consultation_id="cons_idx_test",
            session_id="sess_idx_test",
            workflow_version=3,
        )

        assert store.get_consultation_index_count() == 1

    @pytest.mark.asyncio
    async def test_delete_consultation_index(
        self, store: InMemoryWorkflowStore, sample_state: WorkflowState
    ) -> None:
        """Should delete consultation index entry."""
        # Save state and create index
        await store.save(sample_state)
        await store.create_consultation_index(
            consultation_id=sample_state.consultation_id,
            session_id=sample_state.session_id,
            workflow_version=sample_state.workflow_version,
        )

        # Verify index exists
        retrieved = await store.get_by_consultation(sample_state.consultation_id)
        assert retrieved is not None

        # Delete index
        await store.delete_consultation_index(sample_state.consultation_id)

        # Verify index is gone
        retrieved = await store.get_by_consultation(sample_state.consultation_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_consultation_index(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should handle deleting non-existent index gracefully."""
        # Should not raise
        await store.delete_consultation_index("cons_nonexistent")


class TestBookingIndexOperations:
    """Test booking index create and delete."""

    @pytest.mark.asyncio
    async def test_create_booking_index(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should create booking index entry."""
        await store.create_booking_index(
            booking_id="book_idx_test",
            session_id="sess_idx_test",
            consultation_id="cons_idx_test",
        )

        assert store.get_booking_index_count() == 1

    @pytest.mark.asyncio
    async def test_delete_booking_index(
        self, store: InMemoryWorkflowStore, sample_state: WorkflowState
    ) -> None:
        """Should delete booking index entry."""
        # Save state and create booking index
        await store.save(sample_state)
        await store.create_booking_index(
            booking_id="book_del_test",
            session_id=sample_state.session_id,
            consultation_id=sample_state.consultation_id,
        )

        # Verify index exists
        retrieved = await store.get_by_booking("book_del_test")
        assert retrieved is not None

        # Delete index
        await store.delete_booking_index("book_del_test")

        # Verify index is gone
        retrieved = await store.get_by_booking("book_del_test")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_booking_index(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should handle deleting non-existent index gracefully."""
        # Should not raise
        await store.delete_booking_index("book_nonexistent")


class TestConsultationSummary:
    """Test consultation summary operations."""

    @pytest.mark.asyncio
    async def test_upsert_and_get_summary(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should create and retrieve consultation summary."""
        # Create summary
        await store.upsert_consultation_summary(
            consultation_id="cons_summary_test",
            session_id="sess_summary_test",
            trip_spec_summary={
                "destination": "Tokyo",
                "start_date": "2024-04-01",
                "end_date": "2024-04-07",
                "travelers": 2,
            },
            itinerary_ids=["itn_001"],
            booking_ids=["book_001", "book_002"],
            status="active",
        )

        # Retrieve summary
        summary = await store.get_consultation_summary("cons_summary_test")
        assert summary is not None
        assert summary["consultation_id"] == "cons_summary_test"
        assert summary["session_id"] == "sess_summary_test"
        assert summary["trip_spec_summary"]["destination"] == "Tokyo"
        assert summary["itinerary_ids"] == ["itn_001"]
        assert summary["booking_ids"] == ["book_001", "book_002"]
        assert summary["status"] == "active"

    @pytest.mark.asyncio
    async def test_get_summary_not_found(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should return None when summary not found."""
        result = await store.get_consultation_summary("cons_nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_summary(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should update existing summary on upsert."""
        # Create initial summary
        await store.upsert_consultation_summary(
            consultation_id="cons_upsert_test",
            session_id="sess_upsert_test",
            trip_spec_summary={"destination": "Tokyo"},
            status="active",
        )

        # Update summary
        await store.upsert_consultation_summary(
            consultation_id="cons_upsert_test",
            session_id="sess_upsert_test",
            trip_spec_summary={"destination": "Tokyo"},
            booking_ids=["book_new"],
            status="completed",
        )

        # Verify update
        summary = await store.get_consultation_summary("cons_upsert_test")
        assert summary is not None
        assert summary["status"] == "completed"
        assert summary["booking_ids"] == ["book_new"]

    @pytest.mark.asyncio
    async def test_upsert_preserves_created_at(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should preserve created_at timestamp on update."""
        # Create initial summary
        await store.upsert_consultation_summary(
            consultation_id="cons_timestamp_test",
            session_id="sess_timestamp_test",
            trip_spec_summary={"destination": "Tokyo"},
        )

        # Get initial created_at
        summary1 = await store.get_consultation_summary("cons_timestamp_test")
        assert summary1 is not None
        created_at = summary1["created_at"]

        # Update summary
        await store.upsert_consultation_summary(
            consultation_id="cons_timestamp_test",
            session_id="sess_timestamp_test",
            trip_spec_summary={"destination": "Osaka"},
        )

        # Verify created_at preserved
        summary2 = await store.get_consultation_summary("cons_timestamp_test")
        assert summary2 is not None
        assert summary2["created_at"] == created_at

    @pytest.mark.asyncio
    async def test_consultation_summary_round_trip(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Test complete round-trip of consultation summary."""
        # Full workflow: create, update, retrieve
        trip_spec = {
            "destination": "Paris",
            "start_date": "2024-06-15",
            "end_date": "2024-06-22",
            "travelers": 4,
            "budget": 5000,
        }

        # Initial creation (when itinerary approved)
        await store.upsert_consultation_summary(
            consultation_id="cons_round_trip",
            session_id="sess_round_trip",
            trip_spec_summary=trip_spec,
            itinerary_ids=["itn_paris_001"],
            status="active",
        )

        # Update when booking completes
        await store.upsert_consultation_summary(
            consultation_id="cons_round_trip",
            session_id="sess_round_trip",
            trip_spec_summary=trip_spec,
            itinerary_ids=["itn_paris_001"],
            booking_ids=["book_hotel_001", "book_flight_001"],
            status="completed",
        )

        # Final retrieval
        summary = await store.get_consultation_summary("cons_round_trip")
        assert summary is not None
        assert summary["trip_spec_summary"]["destination"] == "Paris"
        assert len(summary["itinerary_ids"]) == 1
        assert len(summary["booking_ids"]) == 2
        assert summary["status"] == "completed"


class TestTestingUtilities:
    """Test utilities for testing convenience."""

    @pytest.mark.asyncio
    async def test_clear(
        self, store: InMemoryWorkflowStore, sample_state: WorkflowState
    ) -> None:
        """Should clear all stored data."""
        # Add some data
        await store.save(sample_state)
        await store.create_consultation_index("cons_1", "sess_1", 1)
        await store.create_booking_index("book_1", "sess_1", "cons_1")
        await store.upsert_consultation_summary("cons_1", "sess_1", {})

        # Clear
        store.clear()

        # Verify all cleared
        assert store.get_state_count() == 0
        assert store.get_consultation_index_count() == 0
        assert store.get_booking_index_count() == 0
        assert store.get_summary_count() == 0

    @pytest.mark.asyncio
    async def test_get_state_count(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should return accurate state count."""
        assert store.get_state_count() == 0

        # Add states
        state1 = WorkflowState(session_id="sess_1", consultation_id="cons_1")
        state2 = WorkflowState(session_id="sess_2", consultation_id="cons_2")

        await store.save(state1)
        assert store.get_state_count() == 1

        await store.save(state2)
        assert store.get_state_count() == 2

    @pytest.mark.asyncio
    async def test_get_consultation_index_count(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should return accurate consultation index count."""
        assert store.get_consultation_index_count() == 0

        await store.create_consultation_index("cons_1", "sess_1", 1)
        assert store.get_consultation_index_count() == 1

        await store.create_consultation_index("cons_2", "sess_2", 1)
        assert store.get_consultation_index_count() == 2

    @pytest.mark.asyncio
    async def test_get_booking_index_count(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should return accurate booking index count."""
        assert store.get_booking_index_count() == 0

        await store.create_booking_index("book_1", "sess_1", "cons_1")
        assert store.get_booking_index_count() == 1

    @pytest.mark.asyncio
    async def test_get_summary_count(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should return accurate summary count."""
        assert store.get_summary_count() == 0

        await store.upsert_consultation_summary("cons_1", "sess_1", {})
        assert store.get_summary_count() == 1


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_save_new_state_without_etag(
        self, store: InMemoryWorkflowStore, sample_state: WorkflowState
    ) -> None:
        """Should create new state without requiring etag."""
        # First save should work without etag
        etag = await store.save(sample_state)
        assert etag is not None

    @pytest.mark.asyncio
    async def test_save_multiple_states(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should handle multiple independent states."""
        state1 = WorkflowState(
            session_id="sess_multi_1",
            consultation_id="cons_multi_1",
            phase=Phase.CLARIFICATION,
        )
        state2 = WorkflowState(
            session_id="sess_multi_2",
            consultation_id="cons_multi_2",
            phase=Phase.BOOKING,
        )

        await store.save(state1)
        await store.save(state2)

        retrieved1 = await store.get_by_session("sess_multi_1")
        retrieved2 = await store.get_by_session("sess_multi_2")

        assert retrieved1 is not None
        assert retrieved1.phase == Phase.CLARIFICATION

        assert retrieved2 is not None
        assert retrieved2.phase == Phase.BOOKING

    @pytest.mark.asyncio
    async def test_overwrite_consultation_index(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should overwrite existing consultation index entry."""
        # Create initial index
        await store.create_consultation_index("cons_overwrite", "sess_old", 1)

        # Overwrite with new session
        await store.create_consultation_index("cons_overwrite", "sess_new", 2)

        # Save state with new session
        state = WorkflowState(
            session_id="sess_new",
            consultation_id="cons_overwrite",
            workflow_version=2,
        )
        await store.save(state)

        # Should find the new session
        retrieved = await store.get_by_consultation("cons_overwrite")
        assert retrieved is not None
        assert retrieved.session_id == "sess_new"
        assert retrieved.workflow_version == 2

    @pytest.mark.asyncio
    async def test_empty_trip_spec_summary(
        self, store: InMemoryWorkflowStore
    ) -> None:
        """Should handle empty trip_spec_summary."""
        await store.upsert_consultation_summary(
            consultation_id="cons_empty",
            session_id="sess_empty",
            trip_spec_summary={},
        )

        summary = await store.get_consultation_summary("cons_empty")
        assert summary is not None
        assert summary["trip_spec_summary"] == {}
        assert summary["itinerary_ids"] == []
        assert summary["booking_ids"] == []
