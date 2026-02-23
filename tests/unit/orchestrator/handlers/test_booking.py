"""Unit tests for BookingHandler.

Tests for:
- Handler coordinates booking operations through BookingService
- Handler tracks booking status in state
- Handler isolates booking failures (one failure doesn't affect others)
- Handler validates quotes before booking
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator.handlers.booking import BookingHandler
from src.orchestrator.handlers.clarification import HandlerResult
from src.orchestrator.models.responses import ToolResponse, UIDirective
from src.orchestrator.models.workflow_state import Phase, WorkflowState
from src.orchestrator.state_gating import Action, WorkflowEvent
from src.orchestrator.storage import WorkflowStateData


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
    return mock


@pytest.fixture
def mock_booking_store() -> MagicMock:
    """Create a mock BookingStore."""
    mock = MagicMock()
    mock.get_booking = AsyncMock()
    mock.save_booking = AsyncMock()
    mock.get_bookings_by_ids = AsyncMock()
    return mock


@pytest.fixture
def mock_itinerary_store() -> MagicMock:
    """Create a mock ItineraryStore."""
    mock = MagicMock()
    mock.get_itinerary = AsyncMock()
    return mock


# ═══════════════════════════════════════════════════════════════════════════════
# Handler Initialization Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBookingHandlerInit:
    """Test BookingHandler initialization."""

    def test_handler_initializes_with_state(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
    ) -> None:
        """Test handler initializes with workflow state."""
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
        )

        assert handler.state == booking_workflow_state
        assert handler.state_data == booking_workflow_state_data

    def test_handler_accepts_booking_service(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
    ) -> None:
        """Test handler accepts BookingService for dependency injection."""
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
        )

        assert handler._booking_service == mock_booking_service

    def test_handler_accepts_stores_for_lazy_service_creation(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_store: MagicMock,
        mock_itinerary_store: MagicMock,
    ) -> None:
        """Test handler accepts stores and creates BookingService lazily."""
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_store=mock_booking_store,
            itinerary_store=mock_itinerary_store,
        )

        assert handler._booking_store == mock_booking_store
        assert handler._itinerary_store == mock_itinerary_store


# ═══════════════════════════════════════════════════════════════════════════════
# View Booking Options Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestViewBookingOptions:
    """Test VIEW_BOOKING_OPTIONS action."""

    @pytest.mark.asyncio
    async def test_view_all_bookings_with_service(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
    ) -> None:
        """Test viewing all bookings calls BookingService."""
        mock_booking_service.view_booking_options.return_value = ToolResponse(
            success=True,
            message="3 available to book, 0 booked, 0 pending",
            data={"bookings": []},
        )

        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
        )

        result = await handler.execute(
            action=Action.VIEW_BOOKING_OPTIONS,
            message="show my booking options",
        )

        assert isinstance(result, HandlerResult)
        assert result.response.success is True
        mock_booking_service.view_booking_options.assert_called_once()

    @pytest.mark.asyncio
    async def test_view_single_booking_with_booking_id(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
    ) -> None:
        """Test viewing single booking passes booking_id to service."""
        mock_booking_service.view_booking_options.return_value = ToolResponse(
            success=True,
            message="Viewing flight booking",
            data={"booking": {"booking_id": "book_123"}},
        )

        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
        )

        event = WorkflowEvent(
            type="view_booking_options",
            booking={"booking_id": "book_123"},
        )

        result = await handler.execute(
            action=Action.VIEW_BOOKING_OPTIONS,
            message="show booking details",
            event=event,
        )

        assert result.response.success is True
        mock_booking_service.view_booking_options.assert_called_once_with(
            booking_id="book_123",
        )

    @pytest.mark.asyncio
    async def test_view_bookings_stub_mode(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
    ) -> None:
        """Test viewing bookings in stub mode (no BookingService)."""
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
        )

        result = await handler.execute(
            action=Action.VIEW_BOOKING_OPTIONS,
            message="show my booking options",
        )

        assert result.response.success is True
        assert "bookings" in result.response.data
        assert result.response.data.get("stub") is True


# ═══════════════════════════════════════════════════════════════════════════════
# Book Single Item Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBookSingleItem:
    """Test BOOK_SINGLE_ITEM action."""

    @pytest.mark.asyncio
    async def test_book_item_requires_booking_payload(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
    ) -> None:
        """Test booking requires booking_id and quote_id."""
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
        )

        # No event provided
        result = await handler.execute(
            action=Action.BOOK_SINGLE_ITEM,
            message="book this",
        )

        assert result.response.success is False
        assert result.response.data.get("error_code") == "MISSING_BOOKING_PAYLOAD"

    @pytest.mark.asyncio
    async def test_book_item_requires_both_ids(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
    ) -> None:
        """Test booking requires both booking_id and quote_id."""
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
        )

        # Only booking_id provided
        event = WorkflowEvent(
            type="book_item",
            booking={"booking_id": "book_123"},
        )

        result = await handler.execute(
            action=Action.BOOK_SINGLE_ITEM,
            message="book this",
            event=event,
        )

        assert result.response.success is False
        assert result.response.data.get("error_code") == "MISSING_BOOKING_PAYLOAD"

    @pytest.mark.asyncio
    async def test_book_item_calls_service(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
    ) -> None:
        """Test booking calls BookingService with correct parameters."""
        mock_booking_service.book_item.return_value = ToolResponse(
            success=True,
            message="Booked! Confirmation: REF-12345678",
            data={
                "booking_id": "book_123",
                "booking_reference": "REF-12345678",
            },
        )

        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
        )

        event = WorkflowEvent(
            type="book_item",
            booking={"booking_id": "book_123", "quote_id": "quote_456"},
        )

        result = await handler.execute(
            action=Action.BOOK_SINGLE_ITEM,
            message="book it",
            event=event,
        )

        assert result.response.success is True
        assert "REF-" in result.response.data.get("booking_reference", "")
        mock_booking_service.book_item.assert_called_once_with(
            booking_id="book_123",
            quote_id="quote_456",
        )

    @pytest.mark.asyncio
    async def test_book_item_stub_mode(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
    ) -> None:
        """Test booking in stub mode (no BookingService)."""
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
        )

        event = WorkflowEvent(
            type="book_item",
            booking={"booking_id": "book_123", "quote_id": "quote_456"},
        )

        result = await handler.execute(
            action=Action.BOOK_SINGLE_ITEM,
            message="book it",
            event=event,
        )

        assert result.response.success is True
        assert "booking_reference" in result.response.data
        assert result.response.data.get("stub") is True


# ═══════════════════════════════════════════════════════════════════════════════
# Booking Status Tracking Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBookingStatusTracking:
    """Test handler tracks booking status in state."""

    @pytest.mark.asyncio
    async def test_successful_booking_tracked(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
    ) -> None:
        """Test successful booking updates status tracking."""
        mock_booking_service.book_item.return_value = ToolResponse(
            success=True,
            message="Booked!",
            data={"booking_id": "book_123"},
        )

        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
        )

        event = WorkflowEvent(
            type="book_item",
            booking={"booking_id": "book_123", "quote_id": "quote_456"},
        )

        await handler.execute(
            action=Action.BOOK_SINGLE_ITEM,
            message="book it",
            event=event,
        )

        # Check status was tracked
        assert hasattr(booking_workflow_state, 'booking_status')
        assert "book_123" in booking_workflow_state.booking_status
        assert booking_workflow_state.booking_status["book_123"]["status"] == "booked"

    @pytest.mark.asyncio
    async def test_pending_booking_tracked(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
    ) -> None:
        """Test pending booking updates status tracking."""
        mock_booking_service.book_item.return_value = ToolResponse(
            success=False,
            message="Booking in progress",
            data={"error_code": "BOOKING_IN_PROGRESS"},
        )

        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
        )

        event = WorkflowEvent(
            type="book_item",
            booking={"booking_id": "book_123", "quote_id": "quote_456"},
        )

        await handler.execute(
            action=Action.BOOK_SINGLE_ITEM,
            message="book it",
            event=event,
        )

        assert booking_workflow_state.booking_status["book_123"]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_unknown_booking_tracked(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
    ) -> None:
        """Test unknown booking status is tracked."""
        mock_booking_service.book_item.return_value = ToolResponse(
            success=False,
            message="Previous booking attempt is still being verified",
            data={"error_code": "BOOKING_PENDING_RECONCILIATION"},
        )

        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
        )

        event = WorkflowEvent(
            type="book_item",
            booking={"booking_id": "book_123", "quote_id": "quote_456"},
        )

        await handler.execute(
            action=Action.BOOK_SINGLE_ITEM,
            message="book it",
            event=event,
        )

        assert booking_workflow_state.booking_status["book_123"]["status"] == "unknown"


# ═══════════════════════════════════════════════════════════════════════════════
# Booking Failure Isolation Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBookingFailureIsolation:
    """Test that booking failures don't affect other bookings."""

    @pytest.mark.asyncio
    async def test_failure_isolated_to_single_booking(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
    ) -> None:
        """Test that one booking failure doesn't affect another."""
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
        )

        # First booking succeeds
        mock_booking_service.book_item.return_value = ToolResponse(
            success=True,
            message="Booked!",
            data={"booking_id": "book_1"},
        )

        event1 = WorkflowEvent(
            type="book_item",
            booking={"booking_id": "book_1", "quote_id": "quote_1"},
        )

        await handler.execute(
            action=Action.BOOK_SINGLE_ITEM,
            message="book first",
            event=event1,
        )

        # Second booking fails
        mock_booking_service.book_item.return_value = ToolResponse(
            success=False,
            message="Booking failed",
            data={"error_code": "BOOKING_FAILED"},
        )

        event2 = WorkflowEvent(
            type="book_item",
            booking={"booking_id": "book_2", "quote_id": "quote_2"},
        )

        await handler.execute(
            action=Action.BOOK_SINGLE_ITEM,
            message="book second",
            event=event2,
        )

        # Verify first booking is still tracked as successful
        assert booking_workflow_state.booking_status["book_1"]["status"] == "booked"
        # Second booking tracked as failed
        assert booking_workflow_state.booking_status["book_2"]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_handler_continues_after_failure(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
    ) -> None:
        """Test handler can continue processing after a booking failure."""
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
        )

        # Booking fails
        mock_booking_service.book_item.return_value = ToolResponse(
            success=False,
            message="Payment failed",
            data={"error_code": "BOOKING_FAILED"},
        )

        event1 = WorkflowEvent(
            type="book_item",
            booking={"booking_id": "book_1", "quote_id": "quote_1"},
        )

        result1 = await handler.execute(
            action=Action.BOOK_SINGLE_ITEM,
            message="book",
            event=event1,
        )

        assert result1.response.success is False

        # Can still view options
        mock_booking_service.view_booking_options.return_value = ToolResponse(
            success=True,
            message="1 available, 0 booked, 0 pending, 1 failed",
            data={"bookings": []},
        )

        result2 = await handler.execute(
            action=Action.VIEW_BOOKING_OPTIONS,
            message="show options",
        )

        assert result2.response.success is True


# ═══════════════════════════════════════════════════════════════════════════════
# Quote Validation Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestQuoteValidation:
    """Test handler validates quotes before booking."""

    @pytest.mark.asyncio
    async def test_quote_mismatch_returns_error(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
    ) -> None:
        """Test quote mismatch is handled properly."""
        mock_booking_service.book_item.return_value = ToolResponse(
            success=False,
            message="Quote has changed. Please review the updated price.",
            data={"error_code": "BOOKING_QUOTE_MISMATCH", "new_quote": {"quote_id": "quote_new"}},
        )

        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
        )

        event = WorkflowEvent(
            type="book_item",
            booking={"booking_id": "book_123", "quote_id": "quote_old"},
        )

        result = await handler.execute(
            action=Action.BOOK_SINGLE_ITEM,
            message="book it",
            event=event,
        )

        assert result.response.success is False
        assert result.response.data.get("error_code") == "BOOKING_QUOTE_MISMATCH"
        assert "new_quote" in result.response.data

    @pytest.mark.asyncio
    async def test_expired_quote_returns_error(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
    ) -> None:
        """Test expired quote is handled properly."""
        mock_booking_service.book_item.return_value = ToolResponse(
            success=False,
            message="Quote expired. Please confirm the current price.",
            data={"error_code": "BOOKING_QUOTE_EXPIRED", "new_quote": {"quote_id": "quote_fresh"}},
        )

        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
        )

        event = WorkflowEvent(
            type="book_item",
            booking={"booking_id": "book_123", "quote_id": "quote_expired"},
        )

        result = await handler.execute(
            action=Action.BOOK_SINGLE_ITEM,
            message="book it",
            event=event,
        )

        assert result.response.success is False
        assert result.response.data.get("error_code") == "BOOKING_QUOTE_EXPIRED"


# ═══════════════════════════════════════════════════════════════════════════════
# Retry Booking Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestRetryBooking:
    """Test RETRY_BOOKING action."""

    @pytest.mark.asyncio
    async def test_retry_requires_payload(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
    ) -> None:
        """Test retry requires booking payload."""
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
        )

        result = await handler.execute(
            action=Action.RETRY_BOOKING,
            message="retry",
        )

        assert result.response.success is False
        assert result.response.data.get("error_code") == "MISSING_BOOKING_PAYLOAD"

    @pytest.mark.asyncio
    async def test_retry_stub_mode(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
    ) -> None:
        """Test retry in stub mode."""
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
        )

        event = WorkflowEvent(
            type="retry_booking",
            booking={"booking_id": "book_123", "quote_id": "quote_456"},
        )

        result = await handler.execute(
            action=Action.RETRY_BOOKING,
            message="retry",
            event=event,
        )

        assert result.response.success is True


# ═══════════════════════════════════════════════════════════════════════════════
# Cancel Booking Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCancelBooking:
    """Test CANCEL_BOOKING action."""

    @pytest.mark.asyncio
    async def test_cancel_requires_booking_id(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
    ) -> None:
        """Test cancel requires booking_id."""
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
        )

        result = await handler.execute(
            action=Action.CANCEL_BOOKING,
            message="cancel",
        )

        assert result.response.success is False
        assert result.response.data.get("error_code") == "MISSING_BOOKING_PAYLOAD"

    @pytest.mark.asyncio
    async def test_cancel_returns_stub_when_no_service(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
    ) -> None:
        """Test cancel returns stub response when no BookingService is available."""
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
        )

        event = WorkflowEvent(
            type="cancel_booking",
            booking={"booking_id": "book_123"},
        )

        result = await handler.execute(
            action=Action.CANCEL_BOOKING,
            message="cancel",
            event=event,
        )

        assert result.response.success is True
        assert "cancel" in result.response.message.lower()

    @pytest.mark.asyncio
    async def test_cancel_routes_to_service(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
    ) -> None:
        """Test cancel_booking routes to BookingService.cancel_booking."""
        mock_booking_service.cancel_booking.return_value = ToolResponse(
            success=True,
            message="Booking cancelled successfully.",
            data={
                "booking_id": "book_123",
                "cancellation_reference": "CANCEL-12345678",
                "refund_amount": 450.00,
            },
        )

        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
        )

        event = WorkflowEvent(
            type="cancel_booking",
            booking={"booking_id": "book_123"},
        )

        result = await handler.execute(
            action=Action.CANCEL_BOOKING,
            message="cancel",
            event=event,
        )

        assert result.response.success is True
        assert "cancelled" in result.response.message.lower()
        mock_booking_service.cancel_booking.assert_called_once_with(
            booking_id="book_123",
            confirm_fee=False,
        )

    @pytest.mark.asyncio
    async def test_cancel_passes_confirm_fee(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
    ) -> None:
        """Test cancel_booking passes confirm_fee to BookingService."""
        mock_booking_service.cancel_booking.return_value = ToolResponse(
            success=True,
            message="Booking cancelled successfully.",
            data={
                "booking_id": "book_123",
                "cancellation_reference": "CANCEL-12345678",
                "refund_amount": 225.00,
                "cancellation_fee": 225.00,
            },
        )

        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
        )

        event = WorkflowEvent(
            type="cancel_booking",
            booking={"booking_id": "book_123", "confirm_fee": True},
        )

        result = await handler.execute(
            action=Action.CANCEL_BOOKING,
            message="cancel with fee",
            event=event,
        )

        assert result.response.success is True
        mock_booking_service.cancel_booking.assert_called_once_with(
            booking_id="book_123",
            confirm_fee=True,
        )

    @pytest.mark.asyncio
    async def test_cancel_tracks_cancelled_status(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
    ) -> None:
        """Test cancel_booking tracks cancelled status in state."""
        mock_booking_service.cancel_booking.return_value = ToolResponse(
            success=True,
            message="Booking cancelled successfully.",
            data={
                "booking_id": "book_123",
                "cancellation_reference": "CANCEL-12345678",
                "refund_amount": 450.00,
            },
        )

        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
        )

        event = WorkflowEvent(
            type="cancel_booking",
            booking={"booking_id": "book_123"},
        )

        result = await handler.execute(
            action=Action.CANCEL_BOOKING,
            message="cancel",
            event=event,
        )

        assert result.response.success is True
        # Verify booking status is tracked
        assert hasattr(booking_workflow_state, 'booking_status')
        assert "book_123" in booking_workflow_state.booking_status
        assert booking_workflow_state.booking_status["book_123"]["status"] == "cancelled"


# ═══════════════════════════════════════════════════════════════════════════════
# Check Booking Status Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckBookingStatus:
    """Test CHECK_BOOKING_STATUS action."""

    @pytest.mark.asyncio
    async def test_check_status_requires_booking_id(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
    ) -> None:
        """Test check status requires booking_id."""
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
        )

        result = await handler.execute(
            action=Action.CHECK_BOOKING_STATUS,
            message="check status",
        )

        assert result.response.success is False
        assert result.response.data.get("error_code") == "MISSING_BOOKING_PAYLOAD"

    @pytest.mark.asyncio
    async def test_check_status_returns_stub(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
    ) -> None:
        """Test check status returns stub (full impl in ORCH-089)."""
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
        )

        event = WorkflowEvent(
            type="check_booking_status",
            booking={"booking_id": "book_123"},
        )

        result = await handler.execute(
            action=Action.CHECK_BOOKING_STATUS,
            message="check",
            event=event,
        )

        assert result.response.success is True
        assert "checking" in result.response.message.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# Cancel Unknown Booking Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCancelUnknownBooking:
    """Test CANCEL_UNKNOWN_BOOKING action (ORCH-090)."""

    @pytest.mark.asyncio
    async def test_cancel_unknown_requires_booking_id(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
    ) -> None:
        """Test cancel unknown requires booking_id."""
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
        )

        result = await handler.execute(
            action=Action.CANCEL_UNKNOWN_BOOKING,
            message="cancel unknown",
        )

        assert result.response.success is False
        assert result.response.data.get("error_code") == "MISSING_BOOKING_PAYLOAD"

    @pytest.mark.asyncio
    async def test_cancel_unknown_returns_stub(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
    ) -> None:
        """Test cancel unknown returns stub when no BookingService."""
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
        )

        event = WorkflowEvent(
            type="cancel_unknown_booking",
            booking={"booking_id": "book_123"},
        )

        result = await handler.execute(
            action=Action.CANCEL_UNKNOWN_BOOKING,
            message="cancel unknown",
            event=event,
        )

        assert result.response.success is True
        assert "cancel" in result.response.message.lower() or "fresh quote" in result.response.message.lower()
        assert result.response.data.get("stub") is True

    @pytest.mark.asyncio
    async def test_booking_handler_routes_cancel_unknown_booking(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
    ) -> None:
        """Test BookingHandler routes cancel_unknown_booking events to BookingService.

        Per design doc Booking Safety section (ORCH-090):
        - Handler routes cancel_unknown_booking events to BookingService.cancel_unknown_booking
        """
        # Setup mock to return success
        mock_booking_service.cancel_unknown_booking = AsyncMock(
            return_value=ToolResponse(
                success=True,
                message="Previous attempt cancelled. You can now book with a fresh quote.",
                data={
                    "booking_id": "book_123",
                    "status": "failed",
                    "new_quote": {"quote_id": "quote_fresh123"},
                },
            )
        )

        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
        )

        event = WorkflowEvent(
            type="cancel_unknown_booking",
            booking={"booking_id": "book_123"},
        )

        result = await handler.execute(
            action=Action.CANCEL_UNKNOWN_BOOKING,
            message="cancel unknown",
            event=event,
        )

        # Verify BookingService was called with correct booking_id
        mock_booking_service.cancel_unknown_booking.assert_called_once_with(
            booking_id="book_123",
        )
        assert result.response.success is True
        assert "fresh quote" in result.response.message.lower()

    @pytest.mark.asyncio
    async def test_cancel_unknown_updates_booking_status_tracking(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
    ) -> None:
        """Test cancel_unknown_booking updates status tracking in state."""
        mock_booking_service.cancel_unknown_booking = AsyncMock(
            return_value=ToolResponse(
                success=True,
                message="Previous attempt cancelled.",
                data={"booking_id": "book_123", "status": "failed"},
            )
        )

        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
        )

        event = WorkflowEvent(
            type="cancel_unknown_booking",
            booking={"booking_id": "book_123"},
        )

        await handler.execute(
            action=Action.CANCEL_UNKNOWN_BOOKING,
            message="cancel unknown",
            event=event,
        )

        # Verify status tracking was updated
        assert hasattr(booking_workflow_state, 'booking_status')
        assert "book_123" in booking_workflow_state.booking_status


# ═══════════════════════════════════════════════════════════════════════════════
# Invalid Action Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestInvalidActions:
    """Test invalid actions for booking phase."""

    @pytest.mark.asyncio
    async def test_clarification_action_rejected(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
    ) -> None:
        """Test clarification actions are rejected in booking phase."""
        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
        )

        result = await handler.execute(
            action=Action.CONTINUE_CLARIFICATION,
            message="continue",
        )

        assert result.response.success is False
        assert result.response.data.get("error_code") == "INVALID_ACTION_FOR_PHASE"


# ═══════════════════════════════════════════════════════════════════════════════
# State Sync Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestStateSync:
    """Test state synchronization to state_data."""

    @pytest.mark.asyncio
    async def test_state_synced_after_booking(
        self,
        booking_workflow_state: WorkflowState,
        booking_workflow_state_data: WorkflowStateData,
        mock_booking_service: MagicMock,
    ) -> None:
        """Test state_data is updated after booking action."""
        mock_booking_service.book_item.return_value = ToolResponse(
            success=True,
            message="Booked!",
            data={"booking_id": "book_123"},
        )

        handler = BookingHandler(
            state=booking_workflow_state,
            state_data=booking_workflow_state_data,
            booking_service=mock_booking_service,
        )

        original_updated_at = booking_workflow_state_data.updated_at

        event = WorkflowEvent(
            type="book_item",
            booking={"booking_id": "book_123", "quote_id": "quote_456"},
        )

        result = await handler.execute(
            action=Action.BOOK_SINGLE_ITEM,
            message="book",
            event=event,
        )

        # State data should be updated
        assert result.state_data.updated_at > original_updated_at
        assert result.state_data.phase == "booking"
