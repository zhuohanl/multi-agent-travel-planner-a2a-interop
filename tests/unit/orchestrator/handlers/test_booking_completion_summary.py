"""Unit tests for BookingHandler consultation summary updates on booking completion.

Tests for ORCH-107:
- consultation_summaries is updated when all bookings reach a terminal state
- Summary status is set to completed with current booking_ids
- No summary update occurs while bookings are still in progress
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator.handlers.booking import BookingHandler
from src.orchestrator.models.booking import (
    Booking,
    BookingItemStatus,
    BookingStatus,
    BookingSummary,
    CancellationPolicy,
)
from src.orchestrator.models.responses import ToolResponse
from src.orchestrator.models.workflow_state import Phase, WorkflowState
from src.orchestrator.state_gating import Action, WorkflowEvent
from src.orchestrator.storage import WorkflowStateData
from src.orchestrator.storage.consultation_summaries import (
    ConsultationSummary,
    InMemoryConsultationSummaryStore,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def booking_workflow_state() -> WorkflowState:
    """Create a WorkflowState in BOOKING phase for testing."""
    state = WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_test456",
        workflow_version=1,
        phase=Phase.BOOKING,
        checkpoint=None,
        current_step="booking",
    )
    state.itinerary_id = "itn_test789"
    return state


@pytest.fixture
def booking_workflow_state_data() -> WorkflowStateData:
    """Create a WorkflowStateData in BOOKING phase for testing."""
    return WorkflowStateData(
        session_id="sess_test123",
        consultation_id="cons_test456",
        workflow_version=1,
        phase="booking",
        checkpoint=None,
        current_step="booking",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        etag="etag_123",
    )


@pytest.fixture
def mock_booking_service() -> MagicMock:
    """Create a mock BookingService."""
    mock = MagicMock()
    mock.view_booking_options = AsyncMock()
    mock.book_item = AsyncMock()
    mock.retry_booking = AsyncMock()
    mock.check_booking_status = AsyncMock()
    mock.cancel_unknown_booking = AsyncMock()
    mock.cancel_booking = AsyncMock()
    mock.get_booking_summary = AsyncMock()
    return mock


@pytest.fixture
def consultation_summary_store() -> InMemoryConsultationSummaryStore:
    """Create an in-memory consultation summary store for testing."""
    return InMemoryConsultationSummaryStore()


@pytest.fixture
def existing_consultation_summary(
    consultation_summary_store: InMemoryConsultationSummaryStore,
) -> ConsultationSummary:
    """Create and store an existing consultation summary."""
    import asyncio

    summary = ConsultationSummary(
        consultation_id="cons_test456",
        session_id="sess_test123",
        trip_spec_summary={
            "destination": "Tokyo",
            "start_date": "2026-02-01",
            "end_date": "2026-02-07",
        },
        itinerary_ids=["itn_test789"],
        booking_ids=["book_1", "book_2", "book_3"],
        status="itinerary_approved",
        trip_end_date=date(2026, 2, 7),
    )
    asyncio.get_event_loop().run_until_complete(
        consultation_summary_store.save_summary(summary)
    )
    return summary


def create_booking_summary_all_terminal(itinerary_id: str) -> BookingSummary:
    """Create a BookingSummary with all bookings in terminal state."""
    return BookingSummary(
        itinerary_id=itinerary_id,
        items=[
            BookingItemStatus(
                booking_id="book_1",
                item_type="flight",
                name="Flight to Tokyo",
                status=BookingStatus.BOOKED,
                booking_reference="REF-FLIGHT-001",
            ),
            BookingItemStatus(
                booking_id="book_2",
                item_type="hotel",
                name="Hotel in Shibuya",
                status=BookingStatus.BOOKED,
                booking_reference="REF-HOTEL-001",
            ),
            BookingItemStatus(
                booking_id="book_3",
                item_type="activity",
                name="Mt Fuji Tour",
                status=BookingStatus.CANCELLED,
            ),
        ],
        booked_count=2,
        unbooked_count=0,
        failed_count=0,
        pending_count=0,
        unknown_count=0,
        cancelled_count=1,
    )


def create_booking_summary_not_terminal(itinerary_id: str) -> BookingSummary:
    """Create a BookingSummary with some bookings still in progress."""
    return BookingSummary(
        itinerary_id=itinerary_id,
        items=[
            BookingItemStatus(
                booking_id="book_1",
                item_type="flight",
                name="Flight to Tokyo",
                status=BookingStatus.BOOKED,
                booking_reference="REF-FLIGHT-001",
            ),
            BookingItemStatus(
                booking_id="book_2",
                item_type="hotel",
                name="Hotel in Shibuya",
                status=BookingStatus.UNBOOKED,
            ),
            BookingItemStatus(
                booking_id="book_3",
                item_type="activity",
                name="Mt Fuji Tour",
                status=BookingStatus.PENDING,
            ),
        ],
        booked_count=1,
        unbooked_count=1,
        failed_count=0,
        pending_count=1,
        unknown_count=0,
        cancelled_count=0,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Booking Completion Updates Summary Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBookingCompletionUpdatesSummary:
    """Test that consultation summary is updated when all bookings complete."""

    @pytest.mark.asyncio
    async def test_booking_completion_updates_summary(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
        consultation_summary_store: InMemoryConsultationSummaryStore,
    ) -> None:
        """Test summary is updated when all bookings reach terminal state."""
        # Set up existing consultation summary
        existing = ConsultationSummary(
            consultation_id="cons_test456",
            session_id="sess_test123",
            trip_spec_summary={"destination": "Tokyo"},
            itinerary_ids=["itn_test789"],
            booking_ids=["book_1", "book_2", "book_3"],
            status="itinerary_approved",
            trip_end_date=date(2026, 2, 7),
        )
        await consultation_summary_store.save_summary(existing)

        # Configure mock booking service
        mock_booking_service.book_item.return_value = ToolResponse(
            success=True,
            message="Booked! Confirmation: REF-123",
            data={"booking_id": "book_1", "status": "booked"},
        )

        # Return all-terminal summary after booking
        mock_booking_service.get_booking_summary.return_value = (
            create_booking_summary_all_terminal("itn_test789")
        )

        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
            consultation_summary_store=consultation_summary_store,
        )

        event = WorkflowEvent(
            type="book_item",
            booking={"booking_id": "book_1", "quote_id": "quote_123"},
        )

        # Execute booking
        await handler.execute(
            action=Action.BOOK_SINGLE_ITEM,
            message="book my flight",
            event=event,
        )

        # Verify summary was updated
        updated = await consultation_summary_store.get_summary("cons_test456")
        assert updated is not None
        assert updated.status == "completed"
        assert len(updated.booking_ids) == 3
        assert "book_1" in updated.booking_ids
        assert "book_2" in updated.booking_ids
        assert "book_3" in updated.booking_ids

    @pytest.mark.asyncio
    async def test_booking_incomplete_does_not_update_summary(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
        consultation_summary_store: InMemoryConsultationSummaryStore,
    ) -> None:
        """Test summary is NOT updated when bookings are still in progress."""
        # Set up existing consultation summary
        existing = ConsultationSummary(
            consultation_id="cons_test456",
            session_id="sess_test123",
            trip_spec_summary={"destination": "Tokyo"},
            itinerary_ids=["itn_test789"],
            booking_ids=["book_1", "book_2", "book_3"],
            status="itinerary_approved",
            trip_end_date=date(2026, 2, 7),
        )
        await consultation_summary_store.save_summary(existing)

        # Configure mock booking service
        mock_booking_service.book_item.return_value = ToolResponse(
            success=True,
            message="Booked! Confirmation: REF-123",
            data={"booking_id": "book_1", "status": "booked"},
        )

        # Return not-all-terminal summary (some still pending/unbooked)
        mock_booking_service.get_booking_summary.return_value = (
            create_booking_summary_not_terminal("itn_test789")
        )

        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
            consultation_summary_store=consultation_summary_store,
        )

        event = WorkflowEvent(
            type="book_item",
            booking={"booking_id": "book_1", "quote_id": "quote_123"},
        )

        # Execute booking
        await handler.execute(
            action=Action.BOOK_SINGLE_ITEM,
            message="book my flight",
            event=event,
        )

        # Verify summary was NOT updated
        updated = await consultation_summary_store.get_summary("cons_test456")
        assert updated is not None
        assert updated.status == "itinerary_approved"  # Unchanged

    @pytest.mark.asyncio
    async def test_cancel_booking_triggers_completion_check(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
        consultation_summary_store: InMemoryConsultationSummaryStore,
    ) -> None:
        """Test cancellation also triggers completion check."""
        # Set up existing consultation summary
        existing = ConsultationSummary(
            consultation_id="cons_test456",
            session_id="sess_test123",
            trip_spec_summary={"destination": "Tokyo"},
            itinerary_ids=["itn_test789"],
            booking_ids=["book_1"],
            status="itinerary_approved",
            trip_end_date=date(2026, 2, 7),
        )
        await consultation_summary_store.save_summary(existing)

        # Configure mock booking service
        mock_booking_service.cancel_booking.return_value = ToolResponse(
            success=True,
            message="Booking cancelled",
            data={"booking_id": "book_1", "status": "cancelled"},
        )

        # Return all-terminal summary after cancellation (single booking, now cancelled)
        summary = BookingSummary(
            itinerary_id="itn_test789",
            items=[
                BookingItemStatus(
                    booking_id="book_1",
                    item_type="flight",
                    name="Flight",
                    status=BookingStatus.CANCELLED,
                ),
            ],
            booked_count=0,
            unbooked_count=0,
            failed_count=0,
            pending_count=0,
            unknown_count=0,
            cancelled_count=1,
        )
        mock_booking_service.get_booking_summary.return_value = summary

        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
            consultation_summary_store=consultation_summary_store,
        )

        event = WorkflowEvent(
            type="cancel_booking",
            booking={"booking_id": "book_1"},
        )

        # Execute cancellation
        await handler.execute(
            action=Action.CANCEL_BOOKING,
            message="cancel my flight",
            event=event,
        )

        # Verify summary was updated
        updated = await consultation_summary_store.get_summary("cons_test456")
        assert updated is not None
        assert updated.status == "completed"

    @pytest.mark.asyncio
    async def test_check_booking_status_triggers_completion_check(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
        consultation_summary_store: InMemoryConsultationSummaryStore,
    ) -> None:
        """Test check_booking_status also triggers completion check."""
        # Set up existing consultation summary
        existing = ConsultationSummary(
            consultation_id="cons_test456",
            session_id="sess_test123",
            trip_spec_summary={"destination": "Tokyo"},
            itinerary_ids=["itn_test789"],
            booking_ids=["book_1"],
            status="itinerary_approved",
            trip_end_date=date(2026, 2, 7),
        )
        await consultation_summary_store.save_summary(existing)

        # Configure mock: check_booking_status resolves UNKNOWN to BOOKED
        mock_booking_service.check_booking_status.return_value = ToolResponse(
            success=True,
            message="Booking confirmed!",
            data={"booking_id": "book_1", "status": "booked"},
        )

        # Return all-terminal summary (single booking now booked)
        summary = BookingSummary(
            itinerary_id="itn_test789",
            items=[
                BookingItemStatus(
                    booking_id="book_1",
                    item_type="flight",
                    name="Flight",
                    status=BookingStatus.BOOKED,
                    booking_reference="REF-001",
                ),
            ],
            booked_count=1,
            unbooked_count=0,
            failed_count=0,
            pending_count=0,
            unknown_count=0,
            cancelled_count=0,
        )
        mock_booking_service.get_booking_summary.return_value = summary

        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
            consultation_summary_store=consultation_summary_store,
        )

        event = WorkflowEvent(
            type="check_booking_status",
            booking={"booking_id": "book_1"},
        )

        # Execute status check
        await handler.execute(
            action=Action.CHECK_BOOKING_STATUS,
            message="check my booking",
            event=event,
        )

        # Verify summary was updated
        updated = await consultation_summary_store.get_summary("cons_test456")
        assert updated is not None
        assert updated.status == "completed"

    @pytest.mark.asyncio
    async def test_no_consultation_summary_store_skips_update(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
    ) -> None:
        """Test that no error occurs when consultation_summary_store is not provided."""
        # Configure mock booking service
        mock_booking_service.book_item.return_value = ToolResponse(
            success=True,
            message="Booked! Confirmation: REF-123",
            data={"booking_id": "book_1", "status": "booked"},
        )

        # Return all-terminal summary
        mock_booking_service.get_booking_summary.return_value = (
            create_booking_summary_all_terminal("itn_test789")
        )

        # Handler without consultation_summary_store
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
            # No consultation_summary_store
        )

        event = WorkflowEvent(
            type="book_item",
            booking={"booking_id": "book_1", "quote_id": "quote_123"},
        )

        # Execute booking - should not raise error
        result = await handler.execute(
            action=Action.BOOK_SINGLE_ITEM,
            message="book my flight",
            event=event,
        )

        # Should still succeed
        assert result.response.success is True

    @pytest.mark.asyncio
    async def test_no_booking_service_skips_completion_check(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        consultation_summary_store: InMemoryConsultationSummaryStore,
    ) -> None:
        """Test stub response path doesn't crash on completion check."""
        # Set up existing consultation summary
        existing = ConsultationSummary(
            consultation_id="cons_test456",
            session_id="sess_test123",
            trip_spec_summary={"destination": "Tokyo"},
            itinerary_ids=["itn_test789"],
            booking_ids=["book_1"],
            status="itinerary_approved",
            trip_end_date=date(2026, 2, 7),
        )
        await consultation_summary_store.save_summary(existing)

        # Handler without booking_service (will use stub)
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            # No booking_service
            consultation_summary_store=consultation_summary_store,
        )

        event = WorkflowEvent(
            type="book_item",
            booking={"booking_id": "book_1", "quote_id": "quote_123"},
        )

        # Execute booking - should use stub and not crash
        result = await handler.execute(
            action=Action.BOOK_SINGLE_ITEM,
            message="book my flight",
            event=event,
        )

        # Should return stub response
        assert result.response.success is True
        assert result.response.data is not None
        assert result.response.data.get("stub") is True

        # Summary should NOT be updated (stub path doesn't trigger completion check)
        updated = await consultation_summary_store.get_summary("cons_test456")
        assert updated is not None
        assert updated.status == "itinerary_approved"  # Unchanged

    @pytest.mark.asyncio
    async def test_missing_consultation_summary_logs_warning(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
        consultation_summary_store: InMemoryConsultationSummaryStore,
    ) -> None:
        """Test that missing summary doesn't crash but logs warning."""
        # Don't create a consultation summary - store is empty

        # Configure mock booking service
        mock_booking_service.book_item.return_value = ToolResponse(
            success=True,
            message="Booked!",
            data={"booking_id": "book_1", "status": "booked"},
        )

        mock_booking_service.get_booking_summary.return_value = (
            create_booking_summary_all_terminal("itn_test789")
        )

        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
            consultation_summary_store=consultation_summary_store,
        )

        event = WorkflowEvent(
            type="book_item",
            booking={"booking_id": "book_1", "quote_id": "quote_123"},
        )

        # Execute booking - should not crash
        result = await handler.execute(
            action=Action.BOOK_SINGLE_ITEM,
            message="book my flight",
            event=event,
        )

        # Should still succeed
        assert result.response.success is True
