"""Unit tests for the get_consultation lookup tool.

Tests cover:
- Basic consultation lookup (found via summary, found via workflow state)
- Consultation ID validation (format checking)
- Consultation details formatting
- Post-expiry lookup (summary exists, workflow state expired)
- Pre-approval lookup (workflow state exists, no summary yet)
- Enrichment with live workflow data
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from src.orchestrator.storage.consultation_index import (
    ConsultationIndexEntry,
    InMemoryConsultationIndexStore,
)
from src.orchestrator.storage.consultation_summaries import (
    ConsultationSummary,
    InMemoryConsultationSummaryStore,
)
from src.orchestrator.storage.session_state import (
    InMemoryWorkflowStateStore,
    WorkflowStateData,
)
from src.orchestrator.tools.lookups.get_consultation import (
    ConsultationNotFoundError,
    GetConsultationResult,
    format_consultation_details,
    format_phase,
    format_status,
    format_trip_spec_summary,
    get_consultation,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def summary_store() -> InMemoryConsultationSummaryStore:
    """Create an in-memory consultation summary store for testing."""
    return InMemoryConsultationSummaryStore()


@pytest.fixture
def index_store() -> InMemoryConsultationIndexStore:
    """Create an in-memory consultation index store for testing."""
    return InMemoryConsultationIndexStore()


@pytest.fixture
def state_store() -> InMemoryWorkflowStateStore:
    """Create an in-memory workflow state store for testing."""
    return InMemoryWorkflowStateStore()


@pytest.fixture
def sample_summary() -> ConsultationSummary:
    """Create a sample consultation summary for testing."""
    return ConsultationSummary(
        consultation_id="cons_test123",
        session_id="session_abc",
        trip_spec_summary={
            "destination": "Tokyo, Japan",
            "dates": {"start": "2026-03-15", "end": "2026-03-22"},
            "travelers": 2,
        },
        itinerary_ids=["itin_xyz789"],
        booking_ids=["book_001", "book_002"],
        status="itinerary_approved",
        trip_end_date=date(2026, 3, 22),
        created_at=datetime(2026, 1, 10, 10, 0, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 15, 14, 30, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def active_summary() -> ConsultationSummary:
    """Create an active consultation summary (workflow still running)."""
    return ConsultationSummary(
        consultation_id="cons_active456",
        session_id="session_def",
        trip_spec_summary={
            "destination": "Paris, France",
            "dates": {"start": "2026-04-01", "end": "2026-04-10"},
            "travelers": 4,
        },
        itinerary_ids=[],  # Not yet approved
        booking_ids=[],
        status="active",
        trip_end_date=date(2026, 4, 10),
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )


@pytest.fixture
def sample_workflow_state() -> WorkflowStateData:
    """Create a sample workflow state for testing."""
    return WorkflowStateData(
        session_id="session_def",
        consultation_id="cons_active456",
        phase="DISCOVERY_IN_PROGRESS",
        checkpoint="checkpoint_2",
        current_step="searching_hotels",
        itinerary_id=None,
        workflow_version=1,
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )


@pytest.fixture
def sample_index_entry() -> ConsultationIndexEntry:
    """Create a sample consultation index entry for testing."""
    return ConsultationIndexEntry(
        consultation_id="cons_active456",
        session_id="session_def",
        workflow_version=1,
    )


# =============================================================================
# Tests for format_phase
# =============================================================================


class TestFormatPhase:
    """Tests for format_phase function."""

    def test_clarification_phase(self) -> None:
        """CLARIFICATION phase should show gathering details."""
        assert format_phase("CLARIFICATION") == "Gathering trip details"
        assert format_phase("clarification") == "Gathering trip details"

    def test_discovery_in_progress_phase(self) -> None:
        """DISCOVERY_IN_PROGRESS phase should show searching."""
        assert format_phase("DISCOVERY_IN_PROGRESS") == "Searching for options"
        assert format_phase("discovery_in_progress") == "Searching for options"

    def test_discovery_complete_phase(self) -> None:
        """DISCOVERY_COMPLETE phase should show options found."""
        assert format_phase("DISCOVERY_COMPLETE") == "Options found"

    def test_booking_phase(self) -> None:
        """BOOKING phase should show ready for booking."""
        assert format_phase("BOOKING") == "Ready for booking"
        assert format_phase("booking") == "Ready for booking"

    def test_completed_phase(self) -> None:
        """COMPLETED phase should show trip completed."""
        assert format_phase("COMPLETED") == "Trip completed"

    def test_cancelled_phase(self) -> None:
        """CANCELLED phase should show cancelled."""
        assert format_phase("CANCELLED") == "Consultation cancelled"

    def test_unknown_phase(self) -> None:
        """Unknown phase should be title-cased."""
        assert format_phase("SOME_NEW_PHASE") == "Some New Phase"


# =============================================================================
# Tests for format_status
# =============================================================================


class TestFormatStatus:
    """Tests for format_status function."""

    def test_active_status(self) -> None:
        """Active status should show Active."""
        assert format_status("active") == "Active"

    def test_itinerary_approved_status(self) -> None:
        """Itinerary approved status should be formatted."""
        assert format_status("itinerary_approved") == "Itinerary approved"

    def test_completed_status(self) -> None:
        """Completed status should show Completed."""
        assert format_status("completed") == "Completed"

    def test_cancelled_status(self) -> None:
        """Cancelled status should show Cancelled."""
        assert format_status("cancelled") == "Cancelled"

    def test_unknown_status(self) -> None:
        """Unknown status should be title-cased."""
        assert format_status("some_custom_status") == "Some Custom Status"


# =============================================================================
# Tests for format_trip_spec_summary
# =============================================================================


class TestFormatTripSpecSummary:
    """Tests for format_trip_spec_summary function."""

    def test_full_trip_spec(self) -> None:
        """Full trip spec should show all details."""
        trip_spec = {
            "destination": "Tokyo, Japan",
            "dates": {"start": "2026-03-15", "end": "2026-03-22"},
            "travelers": 2,
        }
        formatted = format_trip_spec_summary(trip_spec)
        assert "Tokyo, Japan" in formatted
        assert "2026-03-15 to 2026-03-22" in formatted
        assert "2" in formatted

    def test_partial_trip_spec(self) -> None:
        """Partial trip spec should show available details."""
        trip_spec = {"destination": "Paris"}
        formatted = format_trip_spec_summary(trip_spec)
        assert "Paris" in formatted

    def test_dates_only_start(self) -> None:
        """Dates with only start should show start date."""
        trip_spec = {"dates": {"start": "2026-03-15"}}
        formatted = format_trip_spec_summary(trip_spec)
        assert "2026-03-15" in formatted

    def test_empty_trip_spec(self) -> None:
        """Empty trip spec should show default message."""
        formatted = format_trip_spec_summary({})
        assert "No trip details available" in formatted


# =============================================================================
# Tests for format_consultation_details
# =============================================================================


class TestFormatConsultationDetails:
    """Tests for format_consultation_details function."""

    def test_with_summary_only(self, sample_summary: ConsultationSummary) -> None:
        """Formatting with summary only should include all summary details."""
        formatted = format_consultation_details(
            consultation_id="cons_test123",
            summary=sample_summary,
            workflow_state=None,
        )
        assert "cons_test123" in formatted
        assert "Itinerary approved" in formatted
        assert "Tokyo, Japan" in formatted
        assert "itin_xyz789" in formatted
        assert "book_001" in formatted

    def test_with_workflow_state_only(
        self, sample_workflow_state: WorkflowStateData
    ) -> None:
        """Formatting with workflow state only should include phase info."""
        formatted = format_consultation_details(
            consultation_id="cons_active456",
            summary=None,
            workflow_state=sample_workflow_state,
        )
        assert "cons_active456" in formatted
        assert "Searching for options" in formatted
        assert "checkpoint_2" in formatted

    def test_with_both_summary_and_state(
        self,
        active_summary: ConsultationSummary,
        sample_workflow_state: WorkflowStateData,
    ) -> None:
        """Formatting with both should show phase from state and details from summary."""
        formatted = format_consultation_details(
            consultation_id="cons_active456",
            summary=active_summary,
            workflow_state=sample_workflow_state,
        )
        assert "cons_active456" in formatted
        # Phase from workflow state
        assert "Searching for options" in formatted
        # Details from summary
        assert "Paris, France" in formatted

    def test_includes_timestamps(self, sample_summary: ConsultationSummary) -> None:
        """Formatting should include timestamps from summary."""
        formatted = format_consultation_details(
            consultation_id="cons_test123",
            summary=sample_summary,
        )
        assert "Created:" in formatted
        assert "Updated:" in formatted


# =============================================================================
# Tests for get_consultation function
# =============================================================================


class TestGetConsultation:
    """Tests for get_consultation async function."""

    @pytest.mark.asyncio
    async def test_consultation_found_via_summary(
        self,
        summary_store: InMemoryConsultationSummaryStore,
        sample_summary: ConsultationSummary,
    ) -> None:
        """Consultation found via summary should return success."""
        await summary_store.save_summary(sample_summary)

        result = await get_consultation(
            "cons_test123",
            summary_store=summary_store,
        )

        assert result.success is True
        assert result.consultation_id == "cons_test123"
        assert result.summary is not None
        assert result.summary.consultation_id == "cons_test123"
        assert result.formatted is not None
        assert "Tokyo, Japan" in result.formatted
        assert result.data is not None
        assert result.data["consultation_id"] == "cons_test123"

    @pytest.mark.asyncio
    async def test_consultation_not_found(
        self, summary_store: InMemoryConsultationSummaryStore
    ) -> None:
        """Missing consultation should return failure."""
        result = await get_consultation(
            "cons_nonexistent",
            summary_store=summary_store,
        )

        assert result.success is False
        assert result.summary is None
        assert "not found" in result.message.lower()

    @pytest.mark.asyncio
    async def test_empty_consultation_id(
        self, summary_store: InMemoryConsultationSummaryStore
    ) -> None:
        """Empty consultation ID should return failure."""
        result = await get_consultation("", summary_store=summary_store)

        assert result.success is False
        assert "required" in result.message.lower()

    @pytest.mark.asyncio
    async def test_invalid_consultation_id_format(
        self, summary_store: InMemoryConsultationSummaryStore
    ) -> None:
        """Invalid consultation ID format should return failure."""
        result = await get_consultation("invalid_format", summary_store=summary_store)

        assert result.success is False
        assert "Invalid consultation ID format" in result.message

    @pytest.mark.asyncio
    async def test_enrichment_with_live_workflow_data(
        self,
        summary_store: InMemoryConsultationSummaryStore,
        index_store: InMemoryConsultationIndexStore,
        state_store: InMemoryWorkflowStateStore,
        active_summary: ConsultationSummary,
        sample_workflow_state: WorkflowStateData,
        sample_index_entry: ConsultationIndexEntry,
    ) -> None:
        """Should enrich summary with live workflow state when available."""
        await summary_store.save_summary(active_summary)
        await index_store.add_session(
            session_id=sample_index_entry.session_id,
            consultation_id=sample_index_entry.consultation_id,
            workflow_version=sample_index_entry.workflow_version,
        )
        await state_store.save_state(sample_workflow_state)

        result = await get_consultation(
            "cons_active456",
            summary_store=summary_store,
            consultation_index_store=index_store,
            workflow_state_store=state_store,
        )

        assert result.success is True
        assert result.summary is not None
        assert result.workflow_state is not None
        assert result.data is not None
        assert result.data["phase"] == "DISCOVERY_IN_PROGRESS"
        assert result.data["is_active"] is True

    @pytest.mark.asyncio
    async def test_pre_approval_lookup_via_index(
        self,
        summary_store: InMemoryConsultationSummaryStore,
        index_store: InMemoryConsultationIndexStore,
        state_store: InMemoryWorkflowStateStore,
        sample_workflow_state: WorkflowStateData,
        sample_index_entry: ConsultationIndexEntry,
    ) -> None:
        """Should find consultation via index when no summary exists yet."""
        # No summary saved (pre-approval state)
        await index_store.add_session(
            session_id=sample_index_entry.session_id,
            consultation_id=sample_index_entry.consultation_id,
            workflow_version=sample_index_entry.workflow_version,
        )
        await state_store.save_state(sample_workflow_state)

        result = await get_consultation(
            "cons_active456",
            summary_store=summary_store,
            consultation_index_store=index_store,
            workflow_state_store=state_store,
        )

        assert result.success is True
        assert result.summary is None  # No summary yet
        assert result.workflow_state is not None
        assert result.data is not None
        assert result.data["phase"] == "DISCOVERY_IN_PROGRESS"

    @pytest.mark.asyncio
    async def test_post_expiry_lookup_summary_only(
        self,
        summary_store: InMemoryConsultationSummaryStore,
        index_store: InMemoryConsultationIndexStore,
        state_store: InMemoryWorkflowStateStore,
        sample_summary: ConsultationSummary,
    ) -> None:
        """Should return summary alone when workflow state has expired."""
        await summary_store.save_summary(sample_summary)
        # No index entry or workflow state (expired)

        result = await get_consultation(
            "cons_test123",
            summary_store=summary_store,
            consultation_index_store=index_store,
            workflow_state_store=state_store,
        )

        assert result.success is True
        assert result.summary is not None
        assert result.workflow_state is None  # Expired
        assert result.data is not None
        assert result.data["is_active"] is False

    @pytest.mark.asyncio
    async def test_version_mismatch_skips_stale_state(
        self,
        summary_store: InMemoryConsultationSummaryStore,
        index_store: InMemoryConsultationIndexStore,
        state_store: InMemoryWorkflowStateStore,
        sample_summary: ConsultationSummary,
    ) -> None:
        """Should skip workflow state when version doesn't match index."""
        await summary_store.save_summary(sample_summary)

        # Index entry with version 2
        await index_store.add_session(
            session_id="session_abc",
            consultation_id="cons_test123",
            workflow_version=2,
        )

        # Workflow state with version 1 (stale)
        stale_state = WorkflowStateData(
            session_id="session_abc",
            consultation_id="cons_test123",
            phase="BOOKING",
            workflow_version=1,  # Doesn't match index version
        )
        await state_store.save_state(stale_state)

        result = await get_consultation(
            "cons_test123",
            summary_store=summary_store,
            consultation_index_store=index_store,
            workflow_state_store=state_store,
        )

        assert result.success is True
        assert result.summary is not None
        assert result.workflow_state is None  # Skipped due to version mismatch
        assert result.data["is_active"] is False

    @pytest.mark.asyncio
    async def test_result_data_includes_trip_spec(
        self,
        summary_store: InMemoryConsultationSummaryStore,
        sample_summary: ConsultationSummary,
    ) -> None:
        """Result data should include trip spec summary."""
        await summary_store.save_summary(sample_summary)

        result = await get_consultation("cons_test123", summary_store=summary_store)

        assert result.data is not None
        assert "trip_spec_summary" in result.data
        assert result.data["trip_spec_summary"]["destination"] == "Tokyo, Japan"

    @pytest.mark.asyncio
    async def test_result_data_includes_booking_ids(
        self,
        summary_store: InMemoryConsultationSummaryStore,
        sample_summary: ConsultationSummary,
    ) -> None:
        """Result data should include booking IDs."""
        await summary_store.save_summary(sample_summary)

        result = await get_consultation("cons_test123", summary_store=summary_store)

        assert result.data is not None
        assert "booking_ids" in result.data
        assert result.data["booking_ids"] == ["book_001", "book_002"]
        assert result.data["has_bookings"] is True

    @pytest.mark.asyncio
    async def test_result_data_includes_itinerary_ids(
        self,
        summary_store: InMemoryConsultationSummaryStore,
        sample_summary: ConsultationSummary,
    ) -> None:
        """Result data should include itinerary IDs."""
        await summary_store.save_summary(sample_summary)

        result = await get_consultation("cons_test123", summary_store=summary_store)

        assert result.data is not None
        assert "itinerary_ids" in result.data
        assert result.data["itinerary_ids"] == ["itin_xyz789"]
        assert result.data["has_itinerary"] is True

    @pytest.mark.asyncio
    async def test_workflow_itinerary_added_to_data(
        self,
        summary_store: InMemoryConsultationSummaryStore,
        index_store: InMemoryConsultationIndexStore,
        state_store: InMemoryWorkflowStateStore,
    ) -> None:
        """Workflow state itinerary should be included in data."""
        # Summary without itinerary
        summary = ConsultationSummary(
            consultation_id="cons_itin_test",
            session_id="session_itin",
            trip_spec_summary={"destination": "London"},
            itinerary_ids=[],
        )
        await summary_store.save_summary(summary)

        await index_store.add_session(
            session_id="session_itin",
            consultation_id="cons_itin_test",
            workflow_version=1,
        )

        state = WorkflowStateData(
            session_id="session_itin",
            consultation_id="cons_itin_test",
            phase="BOOKING",
            itinerary_id="itin_new_abc",
            workflow_version=1,
        )
        await state_store.save_state(state)

        result = await get_consultation(
            "cons_itin_test",
            summary_store=summary_store,
            consultation_index_store=index_store,
            workflow_state_store=state_store,
        )

        assert result.data is not None
        assert result.data["itinerary_ids"] == ["itin_new_abc"]
        assert result.data["has_itinerary"] is True


class TestGetConsultationResult:
    """Tests for GetConsultationResult dataclass."""

    def test_to_dict_success(self, sample_summary: ConsultationSummary) -> None:
        """Successful result should serialize with all fields."""
        result = GetConsultationResult(
            success=True,
            message="Found consultation",
            consultation_id="cons_test123",
            summary=sample_summary,
            formatted="Consultation details...",
            data={"consultation_id": "cons_test123"},
        )

        serialized = result.to_dict()

        assert serialized["success"] is True
        assert serialized["message"] == "Found consultation"
        assert serialized["consultation_id"] == "cons_test123"
        assert serialized["formatted"] == "Consultation details..."
        assert serialized["data"]["consultation_id"] == "cons_test123"

    def test_to_dict_failure(self) -> None:
        """Failed result should serialize without optional fields."""
        result = GetConsultationResult(
            success=False,
            message="Consultation not found",
        )

        serialized = result.to_dict()

        assert serialized["success"] is False
        assert serialized["message"] == "Consultation not found"
        assert "consultation_id" not in serialized
        assert "formatted" not in serialized
        assert "data" not in serialized


class TestConsultationNotFoundError:
    """Tests for ConsultationNotFoundError exception."""

    def test_error_with_consultation_id(self) -> None:
        """Error should include consultation ID."""
        error = ConsultationNotFoundError("cons_test123")
        assert error.consultation_id == "cons_test123"
        assert "cons_test123" in str(error)

    def test_error_with_custom_message(self) -> None:
        """Custom message should be used."""
        error = ConsultationNotFoundError("cons_test123", "Custom error message")
        assert error.message == "Custom error message"
        assert str(error) == "Custom error message"
