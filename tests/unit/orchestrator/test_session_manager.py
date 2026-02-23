"""Unit tests for SessionManager and load_or_create_state."""

from datetime import date, datetime, timezone

import pytest

from src.orchestrator.models.booking import Booking, BookingStatus, CancellationPolicy
from src.orchestrator.models.itinerary import Itinerary, ItineraryDay, TripSummary
from src.orchestrator.models.session_ref import SessionRef
from src.orchestrator.session_manager import (
    SessionManager,
    SessionManagerResult,
    load_or_create_state,
)
from src.orchestrator.storage import (
    InMemoryBookingIndexStore,
    InMemoryBookingStore,
    InMemoryConsultationIndexStore,
    InMemoryItineraryStore,
    InMemoryWorkflowStateStore,
    WorkflowStateData,
)
from src.orchestrator.utils import (
    generate_booking_id,
    generate_consultation_id,
    generate_itinerary_id,
    generate_session_id,
)


@pytest.fixture
def workflow_state_store() -> InMemoryWorkflowStateStore:
    """Create an in-memory workflow state store."""
    return InMemoryWorkflowStateStore()


@pytest.fixture
def consultation_index_store() -> InMemoryConsultationIndexStore:
    """Create an in-memory consultation index store."""
    return InMemoryConsultationIndexStore()


@pytest.fixture
def itinerary_store() -> InMemoryItineraryStore:
    """Create an in-memory itinerary store."""
    return InMemoryItineraryStore()


@pytest.fixture
def booking_store() -> InMemoryBookingStore:
    """Create an in-memory booking store."""
    return InMemoryBookingStore()


@pytest.fixture
def booking_index_store() -> InMemoryBookingIndexStore:
    """Create an in-memory booking index store."""
    return InMemoryBookingIndexStore()


@pytest.fixture
def session_manager(
    workflow_state_store: InMemoryWorkflowStateStore,
    consultation_index_store: InMemoryConsultationIndexStore,
    itinerary_store: InMemoryItineraryStore,
    booking_store: InMemoryBookingStore,
    booking_index_store: InMemoryBookingIndexStore,
) -> SessionManager:
    """Create a session manager with in-memory stores."""
    return SessionManager(
        workflow_state_store=workflow_state_store,
        consultation_index_store=consultation_index_store,
        itinerary_store=itinerary_store,
        booking_store=booking_store,
        booking_index_store=booking_index_store,
    )


def create_test_itinerary(
    itinerary_id: str, consultation_id: str, trip_end_date: date | None = None
) -> Itinerary:
    """Create a test itinerary."""
    if trip_end_date is None:
        trip_end_date = date(2025, 3, 20)

    return Itinerary(
        itinerary_id=itinerary_id,
        consultation_id=consultation_id,
        approved_at=datetime.now(timezone.utc),
        trip_summary=TripSummary(
            destination="Tokyo",
            start_date=date(2025, 3, 15),
            end_date=trip_end_date,
            travelers=2,
            trip_type="leisure",
        ),
        days=[
            ItineraryDay(
                day_number=1,
                date=date(2025, 3, 15),
                title="Arrival Day",
            )
        ],
        booking_ids=[],
        total_estimated_cost=2000.0,
    )


def create_test_booking(booking_id: str, itinerary_id: str) -> Booking:
    """Create a test booking."""
    return Booking.create_unbooked(
        booking_id=booking_id,
        itinerary_id=itinerary_id,
        item_type="hotel",
        details={"hotel_name": "Test Hotel", "room_type": "Standard"},
        price=150.0,
        cancellation_policy=CancellationPolicy.free_cancellation(
            until=datetime(2025, 3, 10, tzinfo=timezone.utc)
        ),
    )


class TestLoadOrCreateStateSessionId:
    """Tests for load_or_create_state with session_id lookup."""

    @pytest.mark.asyncio
    async def test_load_or_create_state_session_id_found(
        self,
        session_manager: SessionManager,
        workflow_state_store: InMemoryWorkflowStateStore,
    ) -> None:
        """Existing state is returned when session_id exists."""
        # Setup: Create existing state
        session_id = generate_session_id()
        consultation_id = generate_consultation_id()
        existing_state = WorkflowStateData(
            session_id=session_id,
            consultation_id=consultation_id,
            phase="DISCOVERY_IN_PROGRESS",
            workflow_version=1,
        )
        await workflow_state_store.save_state(existing_state)

        # Act
        result = await session_manager.load_or_create_state(
            SessionRef(session_id=session_id),
            new_session_id=generate_session_id(),
        )

        # Assert
        assert result.is_new is False
        assert result.state.session_id == session_id
        assert result.state.consultation_id == consultation_id
        assert result.state.phase == "DISCOVERY_IN_PROGRESS"
        assert result.original_session_id == session_id

    @pytest.mark.asyncio
    async def test_load_or_create_state_session_id_not_found(
        self,
        session_manager: SessionManager,
        consultation_index_store: InMemoryConsultationIndexStore,
    ) -> None:
        """New state is created when session_id doesn't exist."""
        new_session_id = generate_session_id()

        # Act
        result = await session_manager.load_or_create_state(
            SessionRef(session_id=generate_session_id()),  # Non-existent
            new_session_id=new_session_id,
        )

        # Assert
        assert result.is_new is True
        assert result.state.session_id == new_session_id
        assert result.state.consultation_id is not None
        assert result.state.consultation_id.startswith("cons_")
        assert result.state.phase == "CLARIFICATION"
        assert result.original_session_id == new_session_id

        # Verify consultation_index was created
        entry = await consultation_index_store.get_session_for_consultation(
            result.state.consultation_id
        )
        assert entry is not None
        assert entry.session_id == new_session_id


class TestLoadOrCreateStateConsultationId:
    """Tests for load_or_create_state with consultation_id lookup."""

    @pytest.mark.asyncio
    async def test_load_or_create_state_consultation_id_found(
        self,
        session_manager: SessionManager,
        workflow_state_store: InMemoryWorkflowStateStore,
        consultation_index_store: InMemoryConsultationIndexStore,
    ) -> None:
        """State is returned via consultation_id -> session_id lookup."""
        # Setup: Create existing state with index
        session_id = generate_session_id()
        consultation_id = generate_consultation_id()
        existing_state = WorkflowStateData(
            session_id=session_id,
            consultation_id=consultation_id,
            phase="DISCOVERY_PLANNING",
            workflow_version=1,
        )
        await workflow_state_store.save_state(existing_state)
        await consultation_index_store.add_session(
            session_id=session_id,
            consultation_id=consultation_id,
            workflow_version=1,
        )

        # Act: Lookup via consultation_id (simulating cross-session resumption)
        result = await session_manager.load_or_create_state(
            SessionRef(consultation_id=consultation_id),
            new_session_id=generate_session_id(),  # New browser session
        )

        # Assert
        assert result.is_new is False
        assert result.state.session_id == session_id  # Original session_id
        assert result.state.consultation_id == consultation_id
        assert result.state.phase == "DISCOVERY_PLANNING"
        assert result.original_session_id == session_id  # Original, not new

    @pytest.mark.asyncio
    async def test_load_or_create_state_rejects_stale_version(
        self,
        session_manager: SessionManager,
        workflow_state_store: InMemoryWorkflowStateStore,
        consultation_index_store: InMemoryConsultationIndexStore,
    ) -> None:
        """workflow_version mismatch causes lookup to return None."""
        # Setup: Create state with version 2
        session_id = generate_session_id()
        consultation_id = generate_consultation_id()
        existing_state = WorkflowStateData(
            session_id=session_id,
            consultation_id=consultation_id,
            phase="CLARIFICATION",
            workflow_version=2,  # Version 2
        )
        await workflow_state_store.save_state(existing_state)

        # Index entry has stale version (1)
        await consultation_index_store.add_session(
            session_id=session_id,
            consultation_id=consultation_id,
            workflow_version=1,  # Stale version
        )

        new_session_id = generate_session_id()

        # Act: Lookup should fail due to version mismatch
        result = await session_manager.load_or_create_state(
            SessionRef(consultation_id=consultation_id),
            new_session_id=new_session_id,
        )

        # Assert: New state created because version mismatch
        assert result.is_new is True
        assert result.state.session_id == new_session_id

    @pytest.mark.asyncio
    async def test_load_or_create_state_consultation_id_not_in_index(
        self,
        session_manager: SessionManager,
    ) -> None:
        """New state is created when consultation_id is not in index."""
        new_session_id = generate_session_id()

        # Act
        result = await session_manager.load_or_create_state(
            SessionRef(consultation_id=generate_consultation_id()),  # Not indexed
            new_session_id=new_session_id,
        )

        # Assert
        assert result.is_new is True
        assert result.state.session_id == new_session_id


class TestLoadOrCreateStateItineraryId:
    """Tests for load_or_create_state with itinerary_id lookup."""

    @pytest.mark.asyncio
    async def test_load_or_create_state_itinerary_id_found(
        self,
        session_manager: SessionManager,
        workflow_state_store: InMemoryWorkflowStateStore,
        consultation_index_store: InMemoryConsultationIndexStore,
        itinerary_store: InMemoryItineraryStore,
    ) -> None:
        """State is returned via itinerary_id -> consultation_id -> session_id."""
        # Setup: Create full chain
        session_id = generate_session_id()
        consultation_id = generate_consultation_id()
        itinerary_id = generate_itinerary_id()

        # Create state
        existing_state = WorkflowStateData(
            session_id=session_id,
            consultation_id=consultation_id,
            phase="BOOKING",
            workflow_version=1,
        )
        await workflow_state_store.save_state(existing_state)

        # Create index
        await consultation_index_store.add_session(
            session_id=session_id,
            consultation_id=consultation_id,
            workflow_version=1,
        )

        # Create itinerary
        itinerary = create_test_itinerary(itinerary_id, consultation_id)
        await itinerary_store.save_itinerary(itinerary)

        # Act: Lookup via itinerary_id
        result = await session_manager.load_or_create_state(
            SessionRef(itinerary_id=itinerary_id),
            new_session_id=generate_session_id(),
        )

        # Assert
        assert result.is_new is False
        assert result.state.session_id == session_id
        assert result.state.consultation_id == consultation_id
        assert result.original_session_id == session_id

    @pytest.mark.asyncio
    async def test_load_or_create_state_itinerary_id_not_found(
        self,
        session_manager: SessionManager,
    ) -> None:
        """New state is created when itinerary_id doesn't exist."""
        new_session_id = generate_session_id()

        # Act
        result = await session_manager.load_or_create_state(
            SessionRef(itinerary_id=generate_itinerary_id()),  # Not in store
            new_session_id=new_session_id,
        )

        # Assert
        assert result.is_new is True
        assert result.state.session_id == new_session_id


class TestLoadOrCreateStateBookingId:
    """Tests for load_or_create_state with booking_id lookup."""

    @pytest.mark.asyncio
    async def test_load_or_create_state_booking_id_found(
        self,
        session_manager: SessionManager,
        workflow_state_store: InMemoryWorkflowStateStore,
        consultation_index_store: InMemoryConsultationIndexStore,
        itinerary_store: InMemoryItineraryStore,
        booking_store: InMemoryBookingStore,
        booking_index_store: InMemoryBookingIndexStore,
    ) -> None:
        """State is returned via booking_id -> itinerary_id -> consultation_id."""
        # Setup: Create full chain
        session_id = generate_session_id()
        consultation_id = generate_consultation_id()
        itinerary_id = generate_itinerary_id()
        booking_id = generate_booking_id()

        # Create state
        existing_state = WorkflowStateData(
            session_id=session_id,
            consultation_id=consultation_id,
            phase="BOOKING",
            workflow_version=1,
        )
        await workflow_state_store.save_state(existing_state)

        # Create index
        await consultation_index_store.add_session(
            session_id=session_id,
            consultation_id=consultation_id,
            workflow_version=1,
        )

        # Create booking_index for faster lookup
        await booking_index_store.add_booking_index(
            booking_id=booking_id,
            consultation_id=consultation_id,
            session_id=session_id,
            trip_end_date=date(2025, 3, 20),
        )

        # Create itinerary (used as fallback if index lookup fails)
        itinerary = create_test_itinerary(itinerary_id, consultation_id)
        await itinerary_store.save_itinerary(itinerary)

        # Create booking
        booking = create_test_booking(booking_id, itinerary_id)
        await booking_store.save_booking(booking)

        # Act: Lookup via booking_id
        result = await session_manager.load_or_create_state(
            SessionRef(booking_id=booking_id),
            new_session_id=generate_session_id(),
        )

        # Assert
        assert result.is_new is False
        assert result.state.session_id == session_id
        assert result.state.consultation_id == consultation_id
        assert result.original_session_id == session_id

    @pytest.mark.asyncio
    async def test_load_or_create_state_booking_id_fallback_to_full_chain(
        self,
        session_manager: SessionManager,
        workflow_state_store: InMemoryWorkflowStateStore,
        consultation_index_store: InMemoryConsultationIndexStore,
        itinerary_store: InMemoryItineraryStore,
        booking_store: InMemoryBookingStore,
    ) -> None:
        """Booking lookup falls back to full chain when index is missing."""
        # Setup: Create chain WITHOUT booking_index
        session_id = generate_session_id()
        consultation_id = generate_consultation_id()
        itinerary_id = generate_itinerary_id()
        booking_id = generate_booking_id()

        # Create state
        existing_state = WorkflowStateData(
            session_id=session_id,
            consultation_id=consultation_id,
            phase="BOOKING",
            workflow_version=1,
        )
        await workflow_state_store.save_state(existing_state)

        # Create consultation_index
        await consultation_index_store.add_session(
            session_id=session_id,
            consultation_id=consultation_id,
            workflow_version=1,
        )

        # Create itinerary
        itinerary = create_test_itinerary(itinerary_id, consultation_id)
        await itinerary_store.save_itinerary(itinerary)

        # Create booking (NO booking_index)
        booking = create_test_booking(booking_id, itinerary_id)
        await booking_store.save_booking(booking)

        # Act: Lookup via booking_id should use fallback chain
        result = await session_manager.load_or_create_state(
            SessionRef(booking_id=booking_id),
            new_session_id=generate_session_id(),
        )

        # Assert
        assert result.is_new is False
        assert result.state.session_id == session_id

    @pytest.mark.asyncio
    async def test_load_or_create_state_booking_id_not_found(
        self,
        session_manager: SessionManager,
    ) -> None:
        """New state is created when booking_id doesn't exist."""
        new_session_id = generate_session_id()

        # Act
        result = await session_manager.load_or_create_state(
            SessionRef(booking_id=generate_booking_id()),  # Not in store
            new_session_id=new_session_id,
        )

        # Assert
        assert result.is_new is True
        assert result.state.session_id == new_session_id


class TestLoadOrCreateStateCreation:
    """Tests for new state creation behavior."""

    @pytest.mark.asyncio
    async def test_new_state_has_consultation_id(
        self,
        session_manager: SessionManager,
    ) -> None:
        """New state is created with a generated consultation_id."""
        new_session_id = generate_session_id()

        result = await session_manager.load_or_create_state(
            SessionRef(),  # No IDs
            new_session_id=new_session_id,
        )

        assert result.is_new is True
        assert result.state.consultation_id is not None
        assert result.state.consultation_id.startswith("cons_")
        assert len(result.state.consultation_id) == 37  # "cons_" + 32 hex chars

    @pytest.mark.asyncio
    async def test_new_state_starts_in_clarification_phase(
        self,
        session_manager: SessionManager,
    ) -> None:
        """New state starts in CLARIFICATION phase."""
        result = await session_manager.load_or_create_state(
            SessionRef(),
            new_session_id=generate_session_id(),
        )

        assert result.state.phase == "CLARIFICATION"

    @pytest.mark.asyncio
    async def test_new_state_creates_consultation_index(
        self,
        session_manager: SessionManager,
        consultation_index_store: InMemoryConsultationIndexStore,
    ) -> None:
        """New state creates an entry in consultation_index."""
        new_session_id = generate_session_id()

        result = await session_manager.load_or_create_state(
            SessionRef(),
            new_session_id=new_session_id,
        )

        # Verify index entry was created
        entry = await consultation_index_store.get_session_for_consultation(
            result.state.consultation_id
        )
        assert entry is not None
        assert entry.session_id == new_session_id
        assert entry.workflow_version == 1

    @pytest.mark.asyncio
    async def test_new_state_has_workflow_version_1(
        self,
        session_manager: SessionManager,
    ) -> None:
        """New state has workflow_version=1."""
        result = await session_manager.load_or_create_state(
            SessionRef(),
            new_session_id=generate_session_id(),
        )

        assert result.state.workflow_version == 1


class TestSessionManagerResult:
    """Tests for SessionManagerResult dataclass."""

    def test_result_dataclass_fields(self) -> None:
        """SessionManagerResult has expected fields."""
        state = WorkflowStateData(session_id="test")
        result = SessionManagerResult(
            state=state,
            is_new=True,
            original_session_id="test",
        )

        assert result.state == state
        assert result.is_new is True
        assert result.original_session_id == "test"

    def test_result_with_existing_state(self) -> None:
        """Result correctly represents loaded existing state."""
        original_id = "sess_original"
        state = WorkflowStateData(
            session_id=original_id,
            consultation_id="cons_test",
            phase="BOOKING",
        )
        result = SessionManagerResult(
            state=state,
            is_new=False,
            original_session_id=original_id,
        )

        assert result.is_new is False
        assert result.original_session_id == original_id


class TestConvenienceFunction:
    """Tests for the load_or_create_state convenience function."""

    @pytest.mark.asyncio
    async def test_convenience_function_creates_manager(
        self,
        workflow_state_store: InMemoryWorkflowStateStore,
        consultation_index_store: InMemoryConsultationIndexStore,
        itinerary_store: InMemoryItineraryStore,
        booking_store: InMemoryBookingStore,
        booking_index_store: InMemoryBookingIndexStore,
    ) -> None:
        """Convenience function works same as creating SessionManager."""
        new_session_id = generate_session_id()

        result = await load_or_create_state(
            session_ref=SessionRef(),
            new_session_id=new_session_id,
            workflow_state_store=workflow_state_store,
            consultation_index_store=consultation_index_store,
            itinerary_store=itinerary_store,
            booking_store=booking_store,
            booking_index_store=booking_index_store,
        )

        assert result.is_new is True
        assert result.state.session_id == new_session_id

    @pytest.mark.asyncio
    async def test_convenience_function_finds_existing(
        self,
        workflow_state_store: InMemoryWorkflowStateStore,
        consultation_index_store: InMemoryConsultationIndexStore,
        itinerary_store: InMemoryItineraryStore,
        booking_store: InMemoryBookingStore,
        booking_index_store: InMemoryBookingIndexStore,
    ) -> None:
        """Convenience function finds existing state."""
        # Setup: Create existing state
        session_id = generate_session_id()
        consultation_id = generate_consultation_id()
        existing_state = WorkflowStateData(
            session_id=session_id,
            consultation_id=consultation_id,
            phase="DISCOVERY_IN_PROGRESS",
        )
        await workflow_state_store.save_state(existing_state)
        await consultation_index_store.add_session(
            session_id=session_id,
            consultation_id=consultation_id,
            workflow_version=1,
        )

        # Act
        result = await load_or_create_state(
            session_ref=SessionRef(consultation_id=consultation_id),
            new_session_id=generate_session_id(),
            workflow_state_store=workflow_state_store,
            consultation_index_store=consultation_index_store,
            itinerary_store=itinerary_store,
            booking_store=booking_store,
            booking_index_store=booking_index_store,
        )

        assert result.is_new is False
        assert result.state.session_id == session_id


class TestLookupChainPriority:
    """Tests for lookup chain priority (session_id > consultation_id > itinerary_id > booking_id)."""

    @pytest.mark.asyncio
    async def test_session_id_takes_priority_over_consultation_id(
        self,
        session_manager: SessionManager,
        workflow_state_store: InMemoryWorkflowStateStore,
        consultation_index_store: InMemoryConsultationIndexStore,
    ) -> None:
        """session_id lookup takes priority over consultation_id."""
        # Setup: Two different states
        session_id_1 = generate_session_id()
        session_id_2 = generate_session_id()
        consultation_id = generate_consultation_id()

        # State 1: Has session_id_1
        state_1 = WorkflowStateData(
            session_id=session_id_1,
            consultation_id=consultation_id,
            phase="CLARIFICATION",
        )
        await workflow_state_store.save_state(state_1)

        # State 2: Has session_id_2, same consultation_id in index
        state_2 = WorkflowStateData(
            session_id=session_id_2,
            consultation_id=consultation_id,
            phase="BOOKING",
        )
        await workflow_state_store.save_state(state_2)
        await consultation_index_store.add_session(
            session_id=session_id_2,
            consultation_id=consultation_id,
            workflow_version=1,
        )

        # Act: Provide both, session_id should win
        result = await session_manager.load_or_create_state(
            SessionRef(session_id=session_id_1, consultation_id=consultation_id),
            new_session_id=generate_session_id(),
        )

        # Assert: session_id lookup returns state_1
        assert result.state.session_id == session_id_1
        assert result.state.phase == "CLARIFICATION"

    @pytest.mark.asyncio
    async def test_consultation_id_used_when_session_id_not_found(
        self,
        session_manager: SessionManager,
        workflow_state_store: InMemoryWorkflowStateStore,
        consultation_index_store: InMemoryConsultationIndexStore,
    ) -> None:
        """consultation_id is used when session_id doesn't find state."""
        session_id = generate_session_id()
        consultation_id = generate_consultation_id()

        # Only create state accessible via consultation_id
        state = WorkflowStateData(
            session_id=session_id,
            consultation_id=consultation_id,
            phase="DISCOVERY_PLANNING",
        )
        await workflow_state_store.save_state(state)
        await consultation_index_store.add_session(
            session_id=session_id,
            consultation_id=consultation_id,
            workflow_version=1,
        )

        # Act: Provide non-existent session_id and valid consultation_id
        result = await session_manager.load_or_create_state(
            SessionRef(
                session_id=generate_session_id(),  # Non-existent
                consultation_id=consultation_id,
            ),
            new_session_id=generate_session_id(),
        )

        # Assert: Falls back to consultation_id lookup
        assert result.is_new is False
        assert result.state.session_id == session_id
        assert result.state.phase == "DISCOVERY_PLANNING"
