"""Unit tests for BookingService.

Tests for ORCH-029: Implement BookingService skeleton for workflow_turn booking actions.
"""

import pytest
from datetime import date, datetime, timedelta, timezone

from src.orchestrator.booking.service import BookingService
from src.orchestrator.models.booking import (
    Booking,
    BookingQuote,
    BookingStatus,
    CancellationPolicy,
)
from src.orchestrator.models.itinerary import Itinerary, ItineraryDay, TripSummary
from src.orchestrator.storage.booking_store import InMemoryBookingStore
from src.orchestrator.storage.itinerary_store import InMemoryItineraryStore


@pytest.fixture
def booking_store() -> InMemoryBookingStore:
    """Create an in-memory booking store for testing."""
    return InMemoryBookingStore()


@pytest.fixture
def itinerary_store() -> InMemoryItineraryStore:
    """Create an in-memory itinerary store for testing."""
    return InMemoryItineraryStore()


@pytest.fixture
def booking_service(
    booking_store: InMemoryBookingStore,
    itinerary_store: InMemoryItineraryStore,
) -> BookingService:
    """Create a BookingService instance for testing."""
    return BookingService(
        booking_store=booking_store,
        itinerary_store=itinerary_store,
    )


@pytest.fixture
def sample_booking() -> Booking:
    """Create a sample booking for testing."""
    return Booking.create_unbooked(
        booking_id="book_12345678901234567890123456789012",
        itinerary_id="itn_12345678901234567890123456789012",
        item_type="hotel",
        details={
            "name": "Grand Hotel Paris",
            "check_in": "2025-06-15",
            "check_out": "2025-06-18",
            "currency": "EUR",
        },
        price=450.00,
        cancellation_policy=CancellationPolicy.free_cancellation(
            until=datetime(2025, 6, 10, tzinfo=timezone.utc),
            fee_after=0.5,
        ),
    )


@pytest.fixture
def sample_itinerary(sample_booking: Booking) -> Itinerary:
    """Create a sample itinerary for testing."""
    return Itinerary(
        itinerary_id="itn_12345678901234567890123456789012",
        consultation_id="cons_12345678901234567890123456789012",
        approved_at=datetime.now(timezone.utc),
        trip_summary=TripSummary(
            destination="Paris, France",
            start_date=date(2025, 6, 15),
            end_date=date(2025, 6, 18),
            travelers=2,
            trip_type="leisure",
        ),
        days=[],
        booking_ids=[sample_booking.booking_id],
        total_estimated_cost=450.00,
    )


class TestViewBookingOptionsForItinerary:
    """Tests for view_booking_options with itinerary_id."""

    @pytest.mark.asyncio
    async def test_view_booking_options_for_itinerary(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        itinerary_store: InMemoryItineraryStore,
        sample_booking: Booking,
        sample_itinerary: Itinerary,
    ) -> None:
        """Test viewing booking options for an itinerary."""
        # Setup
        await booking_store.save_booking(sample_booking)
        await itinerary_store.save_itinerary(sample_itinerary)

        # Execute
        result = await booking_service.view_booking_options(
            itinerary_id=sample_itinerary.itinerary_id
        )

        # Verify
        assert result.success is True
        assert "1 available to book" in result.message
        assert result.data is not None
        assert "bookings" in result.data
        assert len(result.data["bookings"]) == 1
        assert result.data["bookings"][0]["booking_id"] == sample_booking.booking_id

    @pytest.mark.asyncio
    async def test_view_booking_options_itinerary_not_found(
        self,
        booking_service: BookingService,
    ) -> None:
        """Test viewing options for a non-existent itinerary."""
        result = await booking_service.view_booking_options(
            itinerary_id="itn_nonexistent00000000000000000000"
        )

        assert result.success is False
        assert result.data["error_code"] == "ITINERARY_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_view_booking_options_empty_itinerary(
        self,
        booking_service: BookingService,
        itinerary_store: InMemoryItineraryStore,
    ) -> None:
        """Test viewing options for an itinerary with no bookings."""
        itinerary = Itinerary(
            itinerary_id="itn_empty0000000000000000000000000",
            consultation_id="cons_12345678901234567890123456789012",
            approved_at=datetime.now(timezone.utc),
            trip_summary=TripSummary(
                destination="Paris",
                start_date=date(2025, 6, 15),
                end_date=date(2025, 6, 18),
                travelers=1,
            ),
            days=[],
            booking_ids=[],
        )
        await itinerary_store.save_itinerary(itinerary)

        result = await booking_service.view_booking_options(
            itinerary_id=itinerary.itinerary_id
        )

        assert result.success is True
        assert "No bookable items" in result.message
        assert result.data is not None
        assert result.data["bookings"] == []


class TestViewBookingOptionsForBookingId:
    """Tests for view_booking_options with booking_id."""

    @pytest.mark.asyncio
    async def test_view_booking_options_for_booking_id(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test viewing options for a specific booking."""
        await booking_store.save_booking(sample_booking)

        result = await booking_service.view_booking_options(
            booking_id=sample_booking.booking_id
        )

        assert result.success is True
        assert "hotel" in result.message
        assert result.data is not None
        assert "booking" in result.data
        assert result.data["booking"]["booking_id"] == sample_booking.booking_id

    @pytest.mark.asyncio
    async def test_view_booking_options_booking_not_found(
        self,
        booking_service: BookingService,
    ) -> None:
        """Test viewing options for a non-existent booking."""
        result = await booking_service.view_booking_options(
            booking_id="book_nonexistent00000000000000000000"
        )

        assert result.success is False
        assert result.data["error_code"] == "BOOKING_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_view_booking_options_generates_quote(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test that viewing generates a quote if missing."""
        # Booking has no quote initially
        assert sample_booking.current_quote is None
        await booking_store.save_booking(sample_booking)

        result = await booking_service.view_booking_options(
            booking_id=sample_booking.booking_id
        )

        assert result.success is True
        assert result.data is not None
        assert "quote" in result.data["booking"]
        assert result.data["booking"]["quote"]["quote_id"].startswith("quote_")


class TestBookItemReturnsNotFound:
    """Tests for book_item with non-existent booking."""

    @pytest.mark.asyncio
    async def test_book_item_returns_not_found(
        self,
        booking_service: BookingService,
    ) -> None:
        """Test booking returns not found for non-existent booking."""
        result = await booking_service.book_item(
            booking_id="book_nonexistent00000000000000000000",
            quote_id="quote_12345678901234567890123456789012",
        )

        assert result.success is False
        assert result.data["error_code"] == "BOOKING_NOT_FOUND"
        assert "Booking not found" in result.message


class TestBookItemReturnsToolResponse:
    """Tests for book_item returning consistent ToolResponse."""

    @pytest.mark.asyncio
    async def test_book_item_returns_tool_response(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test book_item returns a ToolResponse on success."""
        # Setup: create booking with a valid quote
        now = datetime.now(timezone.utc)
        sample_booking.current_quote = BookingQuote(
            quote_id="quote_12345678901234567890123456789012",
            booking_id=sample_booking.booking_id,
            quoted_price=450.00,
            currency="EUR",
            expires_at=now + timedelta(minutes=15),
            terms_hash=sample_booking.cancellation_policy.compute_hash(),
            terms_summary="Free cancellation until Jun 10, 2025",
            created_at=now,
        )
        await booking_store.save_booking(sample_booking)

        # Execute
        result = await booking_service.book_item(
            booking_id=sample_booking.booking_id,
            quote_id="quote_12345678901234567890123456789012",
        )

        # Verify
        assert result.success is True
        assert "Booked!" in result.message
        assert result.data is not None
        assert "booking_reference" in result.data
        assert result.data["confirmed_price"] == 450.00

    @pytest.mark.asyncio
    async def test_book_item_quote_mismatch(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test book_item returns error on quote mismatch."""
        # Setup: create booking with a valid quote
        now = datetime.now(timezone.utc)
        sample_booking.current_quote = BookingQuote(
            quote_id="quote_currentquote000000000000000000",
            booking_id=sample_booking.booking_id,
            quoted_price=450.00,
            currency="EUR",
            expires_at=now + timedelta(minutes=15),
            terms_hash=sample_booking.cancellation_policy.compute_hash(),
            terms_summary="Free cancellation",
            created_at=now,
        )
        await booking_store.save_booking(sample_booking)

        # Execute with wrong quote_id
        result = await booking_service.book_item(
            booking_id=sample_booking.booking_id,
            quote_id="quote_wrongquote0000000000000000000",
        )

        # Verify
        assert result.success is False
        assert result.data["error_code"] == "BOOKING_QUOTE_MISMATCH"
        assert result.data is not None
        assert "new_quote" in result.data

    @pytest.mark.asyncio
    async def test_book_item_quote_expired(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test book_item returns error on expired quote."""
        # Setup: create booking with an expired quote
        now = datetime.now(timezone.utc)
        sample_booking.current_quote = BookingQuote(
            quote_id="quote_expiredquote00000000000000000",
            booking_id=sample_booking.booking_id,
            quoted_price=450.00,
            currency="EUR",
            expires_at=now - timedelta(hours=1),  # Expired
            terms_hash=sample_booking.cancellation_policy.compute_hash(),
            terms_summary="Free cancellation",
            created_at=now - timedelta(hours=2),
        )
        await booking_store.save_booking(sample_booking)

        # Execute
        result = await booking_service.book_item(
            booking_id=sample_booking.booking_id,
            quote_id="quote_expiredquote00000000000000000",
        )

        # Verify
        assert result.success is False
        assert result.data["error_code"] == "BOOKING_QUOTE_EXPIRED"
        assert result.data is not None
        assert "new_quote" in result.data

    @pytest.mark.asyncio
    async def test_book_item_idempotent_success(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test book_item is idempotent for already-booked items."""
        # Setup: already booked
        sample_booking.status = BookingStatus.BOOKED
        sample_booking.confirmed_quote_id = "quote_12345678901234567890123456789012"
        sample_booking.booking_reference = "REF-12345678"
        await booking_store.save_booking(sample_booking)

        # Execute with same quote_id
        result = await booking_service.book_item(
            booking_id=sample_booking.booking_id,
            quote_id="quote_12345678901234567890123456789012",
        )

        # Verify - idempotent success
        assert result.success is True
        assert "Already booked" in result.message

    @pytest.mark.asyncio
    async def test_book_item_already_booked_different_quote(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test book_item returns error when already booked with different quote."""
        # Setup: already booked with a different quote
        sample_booking.status = BookingStatus.BOOKED
        sample_booking.confirmed_quote_id = "quote_originalquote000000000000000"
        sample_booking.booking_reference = "REF-12345678"
        await booking_store.save_booking(sample_booking)

        # Execute with different quote_id
        result = await booking_service.book_item(
            booking_id=sample_booking.booking_id,
            quote_id="quote_differentquote0000000000000",
        )

        # Verify
        assert result.success is False
        assert result.data["error_code"] == "BOOKING_ALREADY_COMPLETED"


class TestBookItemStatusGuards:
    """Tests for book_item status guards."""

    @pytest.mark.asyncio
    async def test_book_item_unknown_status_blocked(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test book_item blocks when status is UNKNOWN."""
        sample_booking.status = BookingStatus.UNKNOWN
        sample_booking.provider_request_id = "book_xxx:quote_yyy"
        sample_booking.status_reason = "Provider timeout"
        await booking_store.save_booking(sample_booking)

        result = await booking_service.book_item(
            booking_id=sample_booking.booking_id,
            quote_id="quote_anynewquote000000000000000000",
        )

        assert result.success is False
        assert result.data["error_code"] == "BOOKING_PENDING_RECONCILIATION"
        assert result.ui is not None
        assert len(result.ui.actions) == 2  # Check Status, Cancel & Retry

    @pytest.mark.asyncio
    async def test_book_item_pending_status_blocked(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test book_item blocks when status is PENDING."""
        sample_booking.status = BookingStatus.PENDING
        await booking_store.save_booking(sample_booking)

        result = await booking_service.book_item(
            booking_id=sample_booking.booking_id,
            quote_id="quote_anynewquote000000000000000000",
        )

        assert result.success is False
        assert result.data["error_code"] == "BOOKING_IN_PROGRESS"
        assert result.ui is not None
        assert result.ui.actions[0].label == "Check Status"

    @pytest.mark.asyncio
    async def test_book_item_cancelled_status_blocked(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test book_item blocks when status is CANCELLED."""
        sample_booking.status = BookingStatus.CANCELLED
        await booking_store.save_booking(sample_booking)

        result = await booking_service.book_item(
            booking_id=sample_booking.booking_id,
            quote_id="quote_anynewquote000000000000000000",
        )

        assert result.success is False
        assert result.data["error_code"] == "BOOKING_CANCELLED"


class TestBookItemNoQuote:
    """Tests for book_item when booking has no quote."""

    @pytest.mark.asyncio
    async def test_book_item_no_quote_generates_new(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test book_item generates new quote when none exists."""
        # Booking has no quote
        assert sample_booking.current_quote is None
        await booking_store.save_booking(sample_booking)

        result = await booking_service.book_item(
            booking_id=sample_booking.booking_id,
            quote_id="quote_anynewquote000000000000000000",
        )

        assert result.success is False
        assert result.data["error_code"] == "BOOKING_NO_QUOTE"
        assert result.data is not None
        assert "new_quote" in result.data
        assert result.ui is not None
        assert result.ui.actions


class TestViewBookingOptionsMissingIdentifier:
    """Tests for view_booking_options without identifiers."""

    @pytest.mark.asyncio
    async def test_view_booking_options_missing_identifier(
        self,
        booking_service: BookingService,
    ) -> None:
        """Test error when no identifier is provided."""
        result = await booking_service.view_booking_options()

        assert result.success is False
        assert result.data["error_code"] == "BOOKING_MISSING_IDENTIFIER"


class TestBookingUIActions:
    """Tests for UI action generation."""

    @pytest.mark.asyncio
    async def test_unbooked_booking_has_book_action(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test that unbooked items have a 'Book' action."""
        await booking_store.save_booking(sample_booking)

        result = await booking_service.view_booking_options(
            booking_id=sample_booking.booking_id
        )

        assert result.success is True
        assert result.ui is not None
        assert result.ui.actions
        # Find book action
        book_action = next(
            (a for a in result.ui.actions if "Book for" in a.label),
            None,
        )
        assert book_action is not None
        assert book_action.event["type"] == "book_item"

    @pytest.mark.asyncio
    async def test_failed_booking_has_retry_action(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test that failed items have a 'Retry' action."""
        sample_booking.status = BookingStatus.FAILED
        sample_booking.failure_reason = "Provider error"
        await booking_store.save_booking(sample_booking)

        result = await booking_service.view_booking_options(
            booking_id=sample_booking.booking_id
        )

        assert result.success is True
        assert result.ui is not None
        assert result.ui.actions
        retry_action = next(
            (a for a in result.ui.actions if "Retry" in a.label),
            None,
        )
        assert retry_action is not None
        assert retry_action.event["type"] == "retry_booking"

    @pytest.mark.asyncio
    async def test_booked_cancellable_has_cancel_action(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test that booked cancellable items have a 'Cancel' action."""
        sample_booking.status = BookingStatus.BOOKED
        sample_booking.booking_reference = "REF-12345678"
        await booking_store.save_booking(sample_booking)

        result = await booking_service.view_booking_options(
            booking_id=sample_booking.booking_id
        )

        assert result.success is True
        assert result.ui is not None
        assert result.ui.actions
        cancel_action = next(
            (a for a in result.ui.actions if "Cancel" in a.label),
            None,
        )
        assert cancel_action is not None
        assert cancel_action.event["type"] == "cancel_booking"

    @pytest.mark.asyncio
    async def test_pending_booking_has_check_status_action(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test that pending items have a 'Check Status' action."""
        sample_booking.status = BookingStatus.PENDING
        await booking_store.save_booking(sample_booking)

        result = await booking_service.view_booking_options(
            booking_id=sample_booking.booking_id
        )

        assert result.success is True
        assert result.ui is not None
        assert result.ui.actions
        status_action = next(
            (a for a in result.ui.actions if "Check Status" in a.label),
            None,
        )
        assert status_action is not None
        assert status_action.event["type"] == "check_booking_status"


class TestBookItemIdempotency:
    """Tests for ORCH-051: book_item idempotency with booking_id + quote_id."""

    @pytest.mark.asyncio
    async def test_book_item_idempotency_check(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test book_item is idempotent for same booking_id + quote_id pair.

        Per design doc Booking Safety section:
        - booking_id + quote_id pair forms the idempotency key
        - Calling book_item multiple times with same pair returns same result
        """
        # Setup: create booking with a valid quote
        now = datetime.now(timezone.utc)
        quote_id = "quote_idempotency_test0000000000000"
        sample_booking.current_quote = BookingQuote(
            quote_id=quote_id,
            booking_id=sample_booking.booking_id,
            quoted_price=450.00,
            currency="EUR",
            expires_at=now + timedelta(minutes=15),
            terms_hash=sample_booking.cancellation_policy.compute_hash(),
            terms_summary="Free cancellation",
            created_at=now,
        )
        await booking_store.save_booking(sample_booking)

        # First call - should succeed
        result1 = await booking_service.book_item(
            booking_id=sample_booking.booking_id,
            quote_id=quote_id,
        )
        assert result1.success is True
        assert "Booked!" in result1.message
        booking_ref1 = result1.data["booking_reference"]

        # Second call with same booking_id + quote_id - should return cached result
        result2 = await booking_service.book_item(
            booking_id=sample_booking.booking_id,
            quote_id=quote_id,
        )
        assert result2.success is True
        assert "Already booked" in result2.message
        assert result2.data["booking_reference"] == booking_ref1

    @pytest.mark.asyncio
    async def test_book_item_duplicate_returns_cached(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test duplicate booking returns cached result.

        Per design doc: Subsequent duplicates return cached result.
        This verifies idempotency survives across calls.
        """
        # Setup: booking already completed
        confirmed_quote_id = "quote_confirmed000000000000000000"
        sample_booking.status = BookingStatus.BOOKED
        sample_booking.confirmed_quote_id = confirmed_quote_id
        sample_booking.booking_reference = "REF-CACHED123"
        sample_booking.provider_request_id = f"{sample_booking.booking_id}:{confirmed_quote_id}"
        await booking_store.save_booking(sample_booking)

        # Call book_item with same quote_id multiple times
        for _ in range(3):
            result = await booking_service.book_item(
                booking_id=sample_booking.booking_id,
                quote_id=confirmed_quote_id,
            )
            assert result.success is True
            assert "Already booked" in result.message
            assert result.data["booking_reference"] == "REF-CACHED123"

    @pytest.mark.asyncio
    async def test_book_item_sets_provider_request_id(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test provider_request_id is set before provider call.

        Per design doc Booking Safety section:
        - provider_request_id = booking_id:quote_id
        - This ensures retries don't create duplicate charges
        """
        # Setup: create booking with a valid quote
        now = datetime.now(timezone.utc)
        quote_id = "quote_providerrequest0000000000000"
        sample_booking.current_quote = BookingQuote(
            quote_id=quote_id,
            booking_id=sample_booking.booking_id,
            quoted_price=450.00,
            currency="EUR",
            expires_at=now + timedelta(minutes=15),
            terms_hash=sample_booking.cancellation_policy.compute_hash(),
            terms_summary="Free cancellation",
            created_at=now,
        )
        await booking_store.save_booking(sample_booking)

        # Execute booking
        result = await booking_service.book_item(
            booking_id=sample_booking.booking_id,
            quote_id=quote_id,
        )
        assert result.success is True

        # Verify provider_request_id is set and persisted
        persisted_booking = await booking_store.get_booking(sample_booking.booking_id)
        assert persisted_booking is not None
        expected_provider_request_id = f"{sample_booking.booking_id}:{quote_id}"
        assert persisted_booking.provider_request_id == expected_provider_request_id

    @pytest.mark.asyncio
    async def test_book_item_blocks_when_pending_or_unknown(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test book_item blocks when status is PENDING or UNKNOWN.

        Per design doc:
        - UNKNOWN/PENDING guards prevent unsafe new attempts
        - Must resolve status before allowing new booking
        """
        # Test PENDING status
        sample_booking.status = BookingStatus.PENDING
        sample_booking.provider_request_id = "book_xxx:quote_pending000"
        await booking_store.save_booking(sample_booking)

        pending_result = await booking_service.book_item(
            booking_id=sample_booking.booking_id,
            quote_id="quote_newattempt0000000000000000",
        )
        assert pending_result.success is False
        assert pending_result.data["error_code"] == "BOOKING_IN_PROGRESS"

        # Test UNKNOWN status
        sample_booking.status = BookingStatus.UNKNOWN
        sample_booking.status_reason = "Provider timeout"
        await booking_store.save_booking(sample_booking)

        unknown_result = await booking_service.book_item(
            booking_id=sample_booking.booking_id,
            quote_id="quote_newattempt0000000000000000",
        )
        assert unknown_result.success is False
        assert unknown_result.data["error_code"] == "BOOKING_PENDING_RECONCILIATION"
        assert unknown_result.ui is not None
        # Should offer Check Status and Cancel & Retry actions
        action_types = [a.event["type"] for a in unknown_result.ui.actions]
        assert "check_booking_status" in action_types
        assert "cancel_unknown_booking" in action_types

    @pytest.mark.asyncio
    async def test_idempotency_survives_store_reload(
        self,
        booking_store: InMemoryBookingStore,
        itinerary_store: InMemoryItineraryStore,
        sample_booking: Booking,
    ) -> None:
        """Test idempotency survives process restart via store persistence.

        Per design doc: Idempotency survives process restart.
        This simulates creating a new service instance with same store.
        """
        # Setup: booking completed with first service instance
        now = datetime.now(timezone.utc)
        quote_id = "quote_persistence_test0000000000"
        sample_booking.status = BookingStatus.BOOKED
        sample_booking.confirmed_quote_id = quote_id
        sample_booking.booking_reference = "REF-PERSIST123"
        sample_booking.provider_request_id = f"{sample_booking.booking_id}:{quote_id}"
        sample_booking.current_quote = BookingQuote(
            quote_id=quote_id,
            booking_id=sample_booking.booking_id,
            quoted_price=450.00,
            currency="EUR",
            expires_at=now + timedelta(minutes=15),
            terms_hash=sample_booking.cancellation_policy.compute_hash(),
            terms_summary="Free cancellation",
            created_at=now,
        )
        await booking_store.save_booking(sample_booking)

        # Simulate "process restart" by creating a new service instance
        new_service = BookingService(
            booking_store=booking_store,  # Same store (simulating shared persistence)
            itinerary_store=itinerary_store,
        )

        # Call book_item with same quote_id - should return cached result
        result = await new_service.book_item(
            booking_id=sample_booking.booking_id,
            quote_id=quote_id,
        )
        assert result.success is True
        assert "Already booked" in result.message
        assert result.data["booking_reference"] == "REF-PERSIST123"


class TestRetryBooking:
    """Tests for ORCH-052: retry_booking flow for FAILED bookings."""

    @pytest.mark.asyncio
    async def test_retry_booking_requires_failed_status(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test retry_booking only allows status=FAILED.

        Per design doc Booking Safety section:
        - Retry is only allowed when status is FAILED
        - Other statuses should return appropriate error with guidance
        """
        # Test each non-FAILED status
        non_failed_statuses = [
            (BookingStatus.UNBOOKED, "book_item"),
            (BookingStatus.PENDING, "already in progress"),
            (BookingStatus.BOOKED, "already booked"),
            (BookingStatus.UNKNOWN, "check status first"),
            (BookingStatus.CANCELLED, "cancelled"),
        ]

        for status, expected_guidance in non_failed_statuses:
            sample_booking.status = status
            await booking_store.save_booking(sample_booking)

            result = await booking_service.retry_booking(
                booking_id=sample_booking.booking_id,
                quote_id="quote_anyquote00000000000000000000",
            )

            assert result.success is False, f"Should fail for status {status.value}"
            assert result.data["error_code"] == "INVALID_BOOKING_STATUS"
            assert expected_guidance in result.message.lower(), \
                f"Expected guidance for {status.value}: {expected_guidance}"
            assert result.data is not None
            assert result.data["current_status"] == status.value

    @pytest.mark.asyncio
    async def test_retry_booking_requires_fresh_quote(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test retry_booking requires a valid quote.

        Per design doc:
        - Fresh quote_id is required for retry (new idempotency key)
        - Quote validation same as book_item
        """
        # Setup: FAILED booking with no quote
        sample_booking.status = BookingStatus.FAILED
        sample_booking.failure_reason = "Provider error"
        sample_booking.current_quote = None
        await booking_store.save_booking(sample_booking)

        result = await booking_service.retry_booking(
            booking_id=sample_booking.booking_id,
            quote_id="quote_nonexistent000000000000000000",
        )

        assert result.success is False
        assert result.data["error_code"] == "BOOKING_NO_QUOTE"
        assert result.data is not None
        assert "new_quote" in result.data

    @pytest.mark.asyncio
    async def test_retry_booking_quote_mismatch(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test retry_booking with quote_id mismatch.

        Per design doc:
        - Quote ID must match current quote
        - Mismatch returns error with new quote for confirmation
        """
        # Setup: FAILED booking with a valid quote
        now = datetime.now(timezone.utc)
        sample_booking.status = BookingStatus.FAILED
        sample_booking.failure_reason = "Provider error"
        sample_booking.current_quote = BookingQuote(
            quote_id="quote_currentquote000000000000000000",
            booking_id=sample_booking.booking_id,
            quoted_price=450.00,
            currency="EUR",
            expires_at=now + timedelta(minutes=15),
            terms_hash=sample_booking.cancellation_policy.compute_hash(),
            terms_summary="Free cancellation",
            created_at=now,
        )
        await booking_store.save_booking(sample_booking)

        result = await booking_service.retry_booking(
            booking_id=sample_booking.booking_id,
            quote_id="quote_wrongquote0000000000000000000",
        )

        assert result.success is False
        assert result.data["error_code"] == "BOOKING_QUOTE_MISMATCH"
        assert result.ui is not None
        # Should have retry action with correct quote_id
        retry_action = result.ui.actions[0]
        assert retry_action.event["type"] == "retry_booking"
        assert retry_action.event["booking"]["quote_id"] == "quote_currentquote000000000000000000"

    @pytest.mark.asyncio
    async def test_retry_booking_quote_expired(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test retry_booking with expired quote.

        Per design doc:
        - Expired quotes return error with new quote for confirmation
        """
        # Setup: FAILED booking with an expired quote
        now = datetime.now(timezone.utc)
        sample_booking.status = BookingStatus.FAILED
        sample_booking.failure_reason = "Provider error"
        sample_booking.current_quote = BookingQuote(
            quote_id="quote_expiredquote00000000000000000",
            booking_id=sample_booking.booking_id,
            quoted_price=450.00,
            currency="EUR",
            expires_at=now - timedelta(hours=1),  # Expired
            terms_hash=sample_booking.cancellation_policy.compute_hash(),
            terms_summary="Free cancellation",
            created_at=now - timedelta(hours=2),
        )
        await booking_store.save_booking(sample_booking)

        result = await booking_service.retry_booking(
            booking_id=sample_booking.booking_id,
            quote_id="quote_expiredquote00000000000000000",
        )

        assert result.success is False
        assert result.data["error_code"] == "BOOKING_QUOTE_EXPIRED"
        assert result.data is not None
        assert "new_quote" in result.data

    @pytest.mark.asyncio
    async def test_retry_booking_updates_status(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test retry_booking updates status correctly.

        Per design doc:
        - Status transitions: FAILED → PENDING → BOOKED/FAILED
        - failure_reason is cleared on retry
        """
        # Setup: FAILED booking with a valid quote
        now = datetime.now(timezone.utc)
        quote_id = "quote_retryupdate0000000000000000"
        sample_booking.status = BookingStatus.FAILED
        sample_booking.failure_reason = "Previous provider error"
        sample_booking.current_quote = BookingQuote(
            quote_id=quote_id,
            booking_id=sample_booking.booking_id,
            quoted_price=450.00,
            currency="EUR",
            expires_at=now + timedelta(minutes=15),
            terms_hash=sample_booking.cancellation_policy.compute_hash(),
            terms_summary="Free cancellation",
            created_at=now,
        )
        await booking_store.save_booking(sample_booking)

        # Execute retry
        result = await booking_service.retry_booking(
            booking_id=sample_booking.booking_id,
            quote_id=quote_id,
        )

        # Verify success
        assert result.success is True
        assert "Booked!" in result.message

        # Verify status was updated
        updated_booking = await booking_store.get_booking(sample_booking.booking_id)
        assert updated_booking is not None
        assert updated_booking.status == BookingStatus.BOOKED
        assert updated_booking.failure_reason is None  # Cleared
        assert updated_booking.confirmed_quote_id == quote_id

    @pytest.mark.asyncio
    async def test_retry_booking_sets_new_provider_request_id(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test retry_booking sets new provider_request_id with fresh quote.

        Per design doc:
        - Use NEW quote_id in idempotency key to differentiate from failed attempt
        - provider_request_id = booking_id:quote_id
        - This ensures provider treats it as a new request
        """
        # Setup: FAILED booking with old provider_request_id
        now = datetime.now(timezone.utc)
        old_quote_id = "quote_failedquote00000000000000000"
        new_quote_id = "quote_freshquote000000000000000000"

        sample_booking.status = BookingStatus.FAILED
        sample_booking.failure_reason = "Previous provider error"
        sample_booking.provider_request_id = f"{sample_booking.booking_id}:{old_quote_id}"
        sample_booking.current_quote = BookingQuote(
            quote_id=new_quote_id,
            booking_id=sample_booking.booking_id,
            quoted_price=450.00,
            currency="EUR",
            expires_at=now + timedelta(minutes=15),
            terms_hash=sample_booking.cancellation_policy.compute_hash(),
            terms_summary="Free cancellation",
            created_at=now,
        )
        await booking_store.save_booking(sample_booking)

        # Execute retry
        result = await booking_service.retry_booking(
            booking_id=sample_booking.booking_id,
            quote_id=new_quote_id,
        )

        assert result.success is True

        # Verify provider_request_id was updated with new quote_id
        updated_booking = await booking_store.get_booking(sample_booking.booking_id)
        assert updated_booking is not None
        expected_provider_request_id = f"{sample_booking.booking_id}:{new_quote_id}"
        assert updated_booking.provider_request_id == expected_provider_request_id
        assert updated_booking.provider_request_id != f"{sample_booking.booking_id}:{old_quote_id}"

    @pytest.mark.asyncio
    async def test_retry_booking_not_found(
        self,
        booking_service: BookingService,
    ) -> None:
        """Test retry_booking returns not found for non-existent booking."""
        result = await booking_service.retry_booking(
            booking_id="book_nonexistent00000000000000000000",
            quote_id="quote_anyquote00000000000000000000",
        )

        assert result.success is False
        assert result.data["error_code"] == "BOOKING_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_retry_booking_clears_failure_reason(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test retry_booking clears the previous failure reason.

        Per design doc:
        - failure_reason is cleared before retrying to avoid confusion
        """
        # Setup: FAILED booking with failure reason
        now = datetime.now(timezone.utc)
        quote_id = "quote_clearfailure000000000000000"
        sample_booking.status = BookingStatus.FAILED
        sample_booking.failure_reason = "Card declined by bank"
        sample_booking.current_quote = BookingQuote(
            quote_id=quote_id,
            booking_id=sample_booking.booking_id,
            quoted_price=450.00,
            currency="EUR",
            expires_at=now + timedelta(minutes=15),
            terms_hash=sample_booking.cancellation_policy.compute_hash(),
            terms_summary="Free cancellation",
            created_at=now,
        )
        await booking_store.save_booking(sample_booking)

        # Execute retry
        result = await booking_service.retry_booking(
            booking_id=sample_booking.booking_id,
            quote_id=quote_id,
        )

        assert result.success is True

        # Verify failure_reason is cleared
        updated_booking = await booking_store.get_booking(sample_booking.booking_id)
        assert updated_booking is not None
        assert updated_booking.failure_reason is None


class TestCheckBookingStatus:
    """Tests for ORCH-089: check_booking_status reconciliation flow."""

    @pytest.mark.asyncio
    async def test_check_booking_status_confirms_booking(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test check_booking_status confirms UNKNOWN booking when provider confirms.

        Per design doc Unknown Outcome Reconciliation:
        - ProviderStatus.CONFIRMED → BOOKED (with booking_reference)
        """
        # Setup: UNKNOWN booking with provider_request_id
        sample_booking.status = BookingStatus.UNKNOWN
        sample_booking.provider_request_id = f"{sample_booking.booking_id}:quote_xxx"
        sample_booking.status_reason = "Provider timeout"
        await booking_store.save_booking(sample_booking)

        # Execute
        result = await booking_service.check_booking_status(
            booking_id=sample_booking.booking_id,
        )

        # Verify - booking was confirmed
        assert result.success is True
        assert "Good news" in result.message
        assert "confirmed" in result.message.lower()
        assert result.data is not None
        assert result.data["status"] == BookingStatus.BOOKED.value
        assert result.data["booking_reference"] is not None

        # Verify status was updated in store
        updated_booking = await booking_store.get_booking(sample_booking.booking_id)
        assert updated_booking is not None
        assert updated_booking.status == BookingStatus.BOOKED

    @pytest.mark.asyncio
    async def test_check_booking_status_marks_failed(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test check_booking_status marks UNKNOWN as FAILED when provider has no record.

        Per design doc Unknown Outcome Reconciliation:
        - ProviderStatus.NOT_FOUND → FAILED (safe to retry)
        """
        # Setup: UNKNOWN booking WITHOUT provider_request_id (simulates NOT_FOUND)
        sample_booking.status = BookingStatus.UNKNOWN
        sample_booking.provider_request_id = None  # No request ID = provider has no record
        sample_booking.status_reason = "Provider timeout"
        await booking_store.save_booking(sample_booking)

        # Execute
        result = await booking_service.check_booking_status(
            booking_id=sample_booking.booking_id,
        )

        # Verify - booking was not found at provider
        assert result.success is False
        assert "not processed" in result.message.lower() or "retry" in result.message.lower()
        assert result.data["error_code"] == "BOOKING_NOT_FOUND_AT_PROVIDER"
        assert result.data is not None
        assert result.data["status"] == BookingStatus.FAILED.value
        assert result.data["retry_possible"] is True

        # Verify retry action is provided
        assert result.ui is not None
        assert result.ui.actions
        retry_action = next(
            (a for a in result.ui.actions if "retry" in a.label.lower()),
            None,
        )
        assert retry_action is not None
        assert retry_action.event["type"] == "retry_booking"

        # Verify status was updated in store
        updated_booking = await booking_store.get_booking(sample_booking.booking_id)
        assert updated_booking is not None
        assert updated_booking.status == BookingStatus.FAILED
        assert updated_booking.failure_reason == "Provider has no record of booking"

    @pytest.mark.asyncio
    async def test_check_booking_status_pending(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test check_booking_status returns pending when provider still processing.

        Per design doc Unknown Outcome Reconciliation:
        - ProviderStatus.PENDING → Stay PENDING (check again later)

        Note: This test uses a mock to force the "pending" status path.
        """
        # Setup: PENDING booking
        sample_booking.status = BookingStatus.PENDING
        sample_booking.provider_request_id = f"{sample_booking.booking_id}:quote_xxx"
        await booking_store.save_booking(sample_booking)

        # For skeleton, we need to override the _query_provider_status method
        # to return "pending" since the default skeleton returns "confirmed"
        original_query = booking_service._query_provider_status

        async def mock_pending_status(booking):
            return "pending"

        booking_service._query_provider_status = mock_pending_status

        try:
            # Execute
            result = await booking_service.check_booking_status(
                booking_id=sample_booking.booking_id,
            )

            # Verify - still pending
            assert result.success is False
            assert "still being processed" in result.message.lower()
            assert result.data["error_code"] == "BOOKING_STILL_PENDING"
            assert result.data is not None
            assert result.data["status"] == BookingStatus.PENDING.value

            # Verify "Check Again" action is provided
            assert result.ui is not None
            assert result.ui.actions
            check_action = next(
                (a for a in result.ui.actions if "check" in a.label.lower()),
                None,
            )
            assert check_action is not None
            assert check_action.event["type"] == "check_booking_status"
        finally:
            # Restore original method
            booking_service._query_provider_status = original_query

    @pytest.mark.asyncio
    async def test_check_booking_status_not_found(
        self,
        booking_service: BookingService,
    ) -> None:
        """Test check_booking_status returns error for non-existent booking."""
        result = await booking_service.check_booking_status(
            booking_id="book_nonexistent00000000000000000000",
        )

        assert result.success is False
        assert result.data["error_code"] == "BOOKING_NOT_FOUND"
        assert "Booking not found" in result.message

    @pytest.mark.asyncio
    async def test_check_booking_status_already_booked(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test check_booking_status returns success for already-booked items.

        Per design doc: check_booking_status only runs for UNKNOWN or PENDING.
        For BOOKED status, it should return the current status without querying provider.
        """
        # Setup: already BOOKED
        sample_booking.status = BookingStatus.BOOKED
        sample_booking.booking_reference = "REF-ALREADYBOOKED"
        await booking_store.save_booking(sample_booking)

        # Execute
        result = await booking_service.check_booking_status(
            booking_id=sample_booking.booking_id,
        )

        # Verify - returns current status
        assert result.success is True
        assert "confirmed" in result.message.lower()
        assert "REF-ALREADYBOOKED" in result.message
        assert result.data is not None
        assert result.data["status"] == BookingStatus.BOOKED.value
        assert result.data["booking_reference"] == "REF-ALREADYBOOKED"

    @pytest.mark.asyncio
    async def test_check_booking_status_unbooked(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test check_booking_status returns status for UNBOOKED items.

        Per design doc: check_booking_status only runs for UNKNOWN or PENDING.
        For UNBOOKED status, it should return the current status without querying provider.
        """
        # Setup: UNBOOKED
        sample_booking.status = BookingStatus.UNBOOKED
        await booking_store.save_booking(sample_booking)

        # Execute
        result = await booking_service.check_booking_status(
            booking_id=sample_booking.booking_id,
        )

        # Verify - returns current status
        assert result.success is True
        assert "not been booked yet" in result.message.lower()
        assert result.data is not None
        assert result.data["status"] == BookingStatus.UNBOOKED.value

    @pytest.mark.asyncio
    async def test_check_booking_status_failed_offers_retry(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test check_booking_status for FAILED items offers retry action.

        Per design doc: FAILED status returns guidance to retry.
        """
        # Setup: FAILED with current quote
        now = datetime.now(timezone.utc)
        sample_booking.status = BookingStatus.FAILED
        sample_booking.failure_reason = "Previous error"
        sample_booking.current_quote = BookingQuote(
            quote_id="quote_failed_retry_test0000000000",
            booking_id=sample_booking.booking_id,
            quoted_price=450.00,
            currency="EUR",
            expires_at=now + timedelta(minutes=15),
            terms_hash=sample_booking.cancellation_policy.compute_hash(),
            terms_summary="Free cancellation",
            created_at=now,
        )
        await booking_store.save_booking(sample_booking)

        # Execute
        result = await booking_service.check_booking_status(
            booking_id=sample_booking.booking_id,
        )

        # Verify - returns current status with retry action
        assert result.success is True
        assert "failed" in result.message.lower()
        assert result.data is not None
        assert result.data["status"] == BookingStatus.FAILED.value

        # Verify retry action is provided
        assert result.ui is not None
        assert result.ui.actions
        retry_action = next(
            (a for a in result.ui.actions if "retry" in a.label.lower()),
            None,
        )
        assert retry_action is not None
        assert retry_action.event["type"] == "retry_booking"

    @pytest.mark.asyncio
    async def test_check_booking_status_updates_store(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test check_booking_status properly updates booking store.

        Per design doc: Provider status updates BookingStore records.
        """
        # Setup: UNKNOWN booking
        original_updated_at = sample_booking.updated_at
        sample_booking.status = BookingStatus.UNKNOWN
        sample_booking.provider_request_id = f"{sample_booking.booking_id}:quote_zzz"
        await booking_store.save_booking(sample_booking)

        # Execute
        result = await booking_service.check_booking_status(
            booking_id=sample_booking.booking_id,
        )

        # Verify store was updated
        assert result.success is True
        updated_booking = await booking_store.get_booking(sample_booking.booking_id)
        assert updated_booking is not None
        assert updated_booking.status == BookingStatus.BOOKED
        assert updated_booking.booking_reference is not None
        # updated_at should have changed
        assert updated_booking.updated_at >= original_updated_at


# ═══════════════════════════════════════════════════════════════════════════════
# Tests for get_booking_summary (ORCH-103)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetBookingSummary:
    """Tests for BookingService.get_booking_summary per ORCH-103."""

    @pytest.mark.asyncio
    async def test_get_booking_summary_itinerary_not_found(
        self,
        booking_service: BookingService,
    ) -> None:
        """Test get_booking_summary returns None for non-existent itinerary."""
        result = await booking_service.get_booking_summary("nonexistent_itinerary")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_booking_summary_no_bookings(
        self,
        booking_service: BookingService,
        itinerary_store: InMemoryItineraryStore,
    ) -> None:
        """Test get_booking_summary for itinerary with no bookings."""
        # Create itinerary with no booking_ids
        itinerary = Itinerary(
            itinerary_id="itin_empty",
            consultation_id="cons_123",
            approved_at=datetime.now(timezone.utc),
            trip_summary=TripSummary(
                destination="Paris",
                start_date=date(2026, 6, 15),
                end_date=date(2026, 6, 20),
                travelers=2,
            ),
            days=[],
            booking_ids=[],
        )
        await itinerary_store.save_itinerary(itinerary)

        result = await booking_service.get_booking_summary("itin_empty")

        assert result is not None
        assert result.itinerary_id == "itin_empty"
        assert result.total_count == 0
        assert result.booked_count == 0
        assert result.unbooked_count == 0

    @pytest.mark.asyncio
    async def test_get_booking_summary_mixed_statuses(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        itinerary_store: InMemoryItineraryStore,
    ) -> None:
        """Test get_booking_summary with mixed booking statuses."""
        # Create bookings with different statuses
        bookings = [
            Booking.create_unbooked(
                booking_id="book_1",
                itinerary_id="itin_mix",
                item_type="flight",
                details={"name": "Flight to Paris"},
                price=500.00,
                cancellation_policy=CancellationPolicy(is_cancellable=True),
            ),
            Booking.create_unbooked(
                booking_id="book_2",
                itinerary_id="itin_mix",
                item_type="hotel",
                details={"name": "Paris Hotel"},
                price=800.00,
                cancellation_policy=CancellationPolicy(is_cancellable=True),
            ),
            Booking.create_unbooked(
                booking_id="book_3",
                itinerary_id="itin_mix",
                item_type="activity",
                details={"name": "Eiffel Tower Tour"},
                price=100.00,
                cancellation_policy=CancellationPolicy(is_cancellable=False),
            ),
        ]

        # Set different statuses
        bookings[0].status = BookingStatus.BOOKED
        bookings[0].booking_reference = "CONF123"
        bookings[1].status = BookingStatus.PENDING
        bookings[2].status = BookingStatus.FAILED
        bookings[2].failure_reason = "Payment declined"

        for b in bookings:
            await booking_store.save_booking(b)

        # Create itinerary
        itinerary = Itinerary(
            itinerary_id="itin_mix",
            consultation_id="cons_123",
            approved_at=datetime.now(timezone.utc),
            trip_summary=TripSummary(
                destination="Paris",
                start_date=date(2026, 6, 15),
                end_date=date(2026, 6, 20),
                travelers=2,
            ),
            days=[],
            booking_ids=["book_1", "book_2", "book_3"],
        )
        await itinerary_store.save_itinerary(itinerary)

        result = await booking_service.get_booking_summary("itin_mix")

        assert result is not None
        assert result.itinerary_id == "itin_mix"
        assert result.total_count == 3
        assert result.booked_count == 1
        assert result.unbooked_count == 0  # No unbooked, all have different statuses
        assert result.pending_count == 1
        assert result.failed_count == 1
        assert result.all_terminal is False  # Has pending
        assert result.all_booked is False

    @pytest.mark.asyncio
    async def test_get_booking_summary_all_booked(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        itinerary_store: InMemoryItineraryStore,
    ) -> None:
        """Test get_booking_summary when all bookings are booked."""
        # Create all booked
        bookings = [
            Booking.create_unbooked(
                booking_id=f"book_{i}",
                itinerary_id="itin_all",
                item_type="hotel",
                details={"name": f"Hotel {i}"},
                price=200.00 * i,
                cancellation_policy=CancellationPolicy(is_cancellable=True),
            )
            for i in range(1, 4)
        ]

        for b in bookings:
            b.status = BookingStatus.BOOKED
            b.booking_reference = f"CONF_{b.booking_id}"
            await booking_store.save_booking(b)

        # Create itinerary
        itinerary = Itinerary(
            itinerary_id="itin_all",
            consultation_id="cons_123",
            approved_at=datetime.now(timezone.utc),
            trip_summary=TripSummary(
                destination="Paris",
                start_date=date(2026, 6, 15),
                end_date=date(2026, 6, 20),
                travelers=2,
            ),
            days=[],
            booking_ids=["book_1", "book_2", "book_3"],
        )
        await itinerary_store.save_itinerary(itinerary)

        result = await booking_service.get_booking_summary("itin_all")

        assert result is not None
        assert result.total_count == 3
        assert result.booked_count == 3
        assert result.all_booked is True
        assert result.all_terminal is True

    @pytest.mark.asyncio
    async def test_get_booking_summary_item_details(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        itinerary_store: InMemoryItineraryStore,
    ) -> None:
        """Test get_booking_summary includes correct item details."""
        # Create a booked item with reference
        booking = Booking.create_unbooked(
            booking_id="book_detail",
            itinerary_id="itin_detail",
            item_type="flight",
            details={"name": "Direct Flight to Paris"},
            price=650.00,
            cancellation_policy=CancellationPolicy(is_cancellable=True),
        )
        booking.status = BookingStatus.BOOKED
        booking.booking_reference = "FLT-12345"
        await booking_store.save_booking(booking)

        # Create itinerary
        itinerary = Itinerary(
            itinerary_id="itin_detail",
            consultation_id="cons_123",
            approved_at=datetime.now(timezone.utc),
            trip_summary=TripSummary(
                destination="Paris",
                start_date=date(2026, 6, 15),
                end_date=date(2026, 6, 20),
                travelers=2,
            ),
            days=[],
            booking_ids=["book_detail"],
        )
        await itinerary_store.save_itinerary(itinerary)

        result = await booking_service.get_booking_summary("itin_detail")

        assert result is not None
        assert len(result.items) == 1

        item = result.items[0]
        assert item.booking_id == "book_detail"
        assert item.item_type == "flight"
        assert item.name == "Direct Flight to Paris"
        assert item.status == BookingStatus.BOOKED
        assert item.booking_reference == "FLT-12345"
        assert item.can_cancel is True  # BOOKED with is_cancellable=True

    @pytest.mark.asyncio
    async def test_get_booking_summary_failed_can_retry(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        itinerary_store: InMemoryItineraryStore,
    ) -> None:
        """Test get_booking_summary sets can_retry for failed bookings."""
        # Create failed booking
        booking = Booking.create_unbooked(
            booking_id="book_fail",
            itinerary_id="itin_fail",
            item_type="hotel",
            details={"name": "Paris Hotel"},
            price=500.00,
            cancellation_policy=CancellationPolicy(is_cancellable=False),
        )
        booking.status = BookingStatus.FAILED
        booking.failure_reason = "Card declined"
        await booking_store.save_booking(booking)

        # Create itinerary
        itinerary = Itinerary(
            itinerary_id="itin_fail",
            consultation_id="cons_123",
            approved_at=datetime.now(timezone.utc),
            trip_summary=TripSummary(
                destination="Paris",
                start_date=date(2026, 6, 15),
                end_date=date(2026, 6, 20),
                travelers=2,
            ),
            days=[],
            booking_ids=["book_fail"],
        )
        await itinerary_store.save_itinerary(itinerary)

        result = await booking_service.get_booking_summary("itin_fail")

        assert result is not None
        assert len(result.items) == 1

        item = result.items[0]
        assert item.status == BookingStatus.FAILED
        assert item.can_retry is True
        assert item.can_cancel is None  # Not set for non-BOOKED


# ═══════════════════════════════════════════════════════════════════════════════
# Tests for cancel_unknown_booking (ORCH-090)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCancelUnknownBooking:
    """Tests for ORCH-090: cancel_unknown_booking flow."""

    @pytest.mark.asyncio
    async def test_cancel_unknown_booking_confirms_booking(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test cancel_unknown_booking confirms when provider confirms booking.

        Per design doc Booking Safety section:
        - If provider confirms booking, convert to BOOKED (don't cancel!)
        - Return success message with booking reference
        """
        # Setup: UNKNOWN booking with provider_request_id (simulates CONFIRMED)
        sample_booking.status = BookingStatus.UNKNOWN
        sample_booking.provider_request_id = f"{sample_booking.booking_id}:quote_xxx"
        sample_booking.status_reason = "Provider timeout"
        await booking_store.save_booking(sample_booking)

        # Execute
        result = await booking_service.cancel_unknown_booking(
            booking_id=sample_booking.booking_id,
        )

        # Verify - booking was actually confirmed
        assert result.success is True
        assert "Good news" in result.message
        assert "confirmed" in result.message.lower()
        assert result.data is not None
        assert result.data["status"] == BookingStatus.BOOKED.value
        assert result.data["booking_reference"] is not None

        # Verify status was updated in store
        updated_booking = await booking_store.get_booking(sample_booking.booking_id)
        assert updated_booking is not None
        assert updated_booking.status == BookingStatus.BOOKED

    @pytest.mark.asyncio
    async def test_cancel_unknown_booking_resets_failed(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test cancel_unknown_booking resets to FAILED when provider has no record.

        Per design doc Booking Safety section:
        - Provider NOT_FOUND resets status to FAILED
        - Clears provider_request_id (idempotency key)
        - Returns success with retry guidance
        """
        # Setup: UNKNOWN booking WITHOUT provider_request_id (simulates NOT_FOUND)
        sample_booking.status = BookingStatus.UNKNOWN
        sample_booking.provider_request_id = None  # No request ID = provider has no record
        sample_booking.status_reason = "Provider timeout"
        await booking_store.save_booking(sample_booking)

        # Execute
        result = await booking_service.cancel_unknown_booking(
            booking_id=sample_booking.booking_id,
        )

        # Verify - booking was reset to FAILED
        assert result.success is True
        assert "cancelled" in result.message.lower() or "previous attempt" in result.message.lower()
        assert "fresh quote" in result.message.lower()
        assert result.data is not None
        assert result.data["status"] == BookingStatus.FAILED.value
        assert "new_quote" in result.data

        # Verify UI actions for retry
        assert result.ui is not None
        assert result.ui.actions
        # Should have view options and/or retry action
        action_types = [a.event.get("type") for a in result.ui.actions]
        assert "view_booking_options" in action_types or "retry_booking" in action_types

        # Verify status was updated in store
        updated_booking = await booking_store.get_booking(sample_booking.booking_id)
        assert updated_booking is not None
        assert updated_booking.status == BookingStatus.FAILED
        assert updated_booking.provider_request_id is None  # Cleared
        assert "UNKNOWN" in updated_booking.failure_reason

    @pytest.mark.asyncio
    async def test_cancel_unknown_booking_rejects_non_unknown(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test cancel_unknown_booking only runs when status=UNKNOWN.

        Per design doc:
        - cancel_unknown_booking only runs for UNKNOWN status
        - Other statuses return appropriate error with guidance
        """
        # Test each non-UNKNOWN status
        non_unknown_statuses = [
            (BookingStatus.UNBOOKED, "book_item"),
            (BookingStatus.PENDING, "wait"),
            (BookingStatus.BOOKED, "cancel_booking"),
            (BookingStatus.FAILED, "retry"),
            (BookingStatus.CANCELLED, "cancelled"),
        ]

        for status, expected_guidance in non_unknown_statuses:
            sample_booking.status = status
            await booking_store.save_booking(sample_booking)

            result = await booking_service.cancel_unknown_booking(
                booking_id=sample_booking.booking_id,
            )

            assert result.success is False, f"Should fail for status {status.value}"
            assert result.data["error_code"] == "INVALID_BOOKING_STATUS"
            assert expected_guidance in result.message.lower(), \
                f"Expected guidance for {status.value}: {expected_guidance}"
            assert result.data is not None
            assert result.data["current_status"] == status.value

    @pytest.mark.asyncio
    async def test_cancel_unknown_booking_not_found(
        self,
        booking_service: BookingService,
    ) -> None:
        """Test cancel_unknown_booking returns error for non-existent booking."""
        result = await booking_service.cancel_unknown_booking(
            booking_id="book_nonexistent00000000000000000000",
        )

        assert result.success is False
        assert result.data["error_code"] == "BOOKING_NOT_FOUND"
        assert "Booking not found" in result.message

    @pytest.mark.asyncio
    async def test_cancel_unknown_booking_pending_at_provider(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test cancel_unknown_booking blocks when provider still processing.

        Per design doc Booking Safety section:
        - If provider still PENDING, cannot cancel yet
        - Return error with "Check Again" action
        """
        # Setup: UNKNOWN booking
        sample_booking.status = BookingStatus.UNKNOWN
        sample_booking.provider_request_id = f"{sample_booking.booking_id}:quote_xxx"
        await booking_store.save_booking(sample_booking)

        # Mock provider to return "pending"
        async def mock_pending_status(booking):
            return "pending"

        original_query = booking_service._query_provider_status
        booking_service._query_provider_status = mock_pending_status

        try:
            # Execute
            result = await booking_service.cancel_unknown_booking(
                booking_id=sample_booking.booking_id,
            )

            # Verify - cannot cancel yet
            assert result.success is False
            assert "still processing" in result.message.lower()
            assert result.data["error_code"] == "BOOKING_STILL_PENDING"

            # Verify "Check Again" action is provided
            assert result.ui is not None
            assert result.ui.actions
            check_action = next(
                (a for a in result.ui.actions if "check" in a.label.lower()),
                None,
            )
            assert check_action is not None
            assert check_action.event["type"] == "check_booking_status"

            # Verify status was NOT changed (still UNKNOWN)
            updated_booking = await booking_store.get_booking(sample_booking.booking_id)
            assert updated_booking is not None
            assert updated_booking.status == BookingStatus.UNKNOWN
        finally:
            # Restore original method
            booking_service._query_provider_status = original_query

    @pytest.mark.asyncio
    async def test_cancel_unknown_booking_clears_idempotency_key(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test cancel_unknown_booking clears provider_request_id on NOT_FOUND.

        Per design doc Booking Safety section:
        - Clear provider_request_id so next attempt gets fresh key
        - This allows retry with new idempotency key
        """
        # Setup: UNKNOWN booking WITHOUT provider_request_id (simulates NOT_FOUND)
        # But first give it one to verify it gets cleared
        sample_booking.status = BookingStatus.UNKNOWN
        sample_booking.provider_request_id = None  # Will simulate NOT_FOUND
        await booking_store.save_booking(sample_booking)

        # Execute
        result = await booking_service.cancel_unknown_booking(
            booking_id=sample_booking.booking_id,
        )

        # Verify - provider_request_id is None in updated booking
        assert result.success is True
        updated_booking = await booking_store.get_booking(sample_booking.booking_id)
        assert updated_booking is not None
        assert updated_booking.provider_request_id is None

    @pytest.mark.asyncio
    async def test_cancel_unknown_booking_generates_fresh_quote(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test cancel_unknown_booking generates a fresh quote for retry.

        Per design doc Booking Safety section:
        - On NOT_FOUND, generate fresh quote for retry
        - Include quote in response for immediate retry
        """
        # Setup: UNKNOWN booking WITHOUT provider_request_id (simulates NOT_FOUND)
        sample_booking.status = BookingStatus.UNKNOWN
        sample_booking.provider_request_id = None
        sample_booking.current_quote = None
        await booking_store.save_booking(sample_booking)

        # Execute
        result = await booking_service.cancel_unknown_booking(
            booking_id=sample_booking.booking_id,
        )

        # Verify - fresh quote is generated
        assert result.success is True
        assert result.data is not None
        assert "new_quote" in result.data
        assert result.data["new_quote"]["quote_id"].startswith("quote_")
        assert result.data["new_quote"]["quoted_price"] == sample_booking.price

        # Verify quote is saved in store
        updated_booking = await booking_store.get_booking(sample_booking.booking_id)
        assert updated_booking is not None
        assert updated_booking.current_quote is not None
        assert updated_booking.current_quote.quote_id == result.data["new_quote"]["quote_id"]


class TestCancelBooking:
    """Tests for ORCH-091: cancel_booking flow for BOOKED items."""

    @pytest.mark.asyncio
    async def test_cancel_booking_rejects_non_booked(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test cancel_booking only allows status=BOOKED.

        Per design doc Booking Safety section:
        - Only BOOKED items can be cancelled
        - Other statuses return appropriate guidance
        """
        # Test UNBOOKED status
        sample_booking.status = BookingStatus.UNBOOKED
        await booking_store.save_booking(sample_booking)

        result = await booking_service.cancel_booking(
            booking_id=sample_booking.booking_id,
        )
        assert result.success is False
        assert result.data["error_code"] == "INVALID_BOOKING_STATUS"
        assert "hasn't been booked yet" in result.message

        # Test PENDING status
        sample_booking.status = BookingStatus.PENDING
        await booking_store.save_booking(sample_booking)

        result = await booking_service.cancel_booking(
            booking_id=sample_booking.booking_id,
        )
        assert result.success is False
        assert "in progress" in result.message

        # Test FAILED status
        sample_booking.status = BookingStatus.FAILED
        await booking_store.save_booking(sample_booking)

        result = await booking_service.cancel_booking(
            booking_id=sample_booking.booking_id,
        )
        assert result.success is False
        assert "failed" in result.message

        # Test UNKNOWN status
        sample_booking.status = BookingStatus.UNKNOWN
        await booking_store.save_booking(sample_booking)

        result = await booking_service.cancel_booking(
            booking_id=sample_booking.booking_id,
        )
        assert result.success is False
        assert "uncertain" in result.message

        # Test CANCELLED status
        sample_booking.status = BookingStatus.CANCELLED
        await booking_store.save_booking(sample_booking)

        result = await booking_service.cancel_booking(
            booking_id=sample_booking.booking_id,
        )
        assert result.success is False
        assert "already cancelled" in result.message

    @pytest.mark.asyncio
    async def test_cancel_booking_enforces_policy_non_refundable(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test cancel_booking rejects non-refundable bookings.

        Per design doc Booking Safety section:
        - Non-refundable bookings cannot be cancelled
        """
        sample_booking.status = BookingStatus.BOOKED
        sample_booking.booking_reference = "REF-12345678"
        sample_booking.cancellation_policy = CancellationPolicy.non_refundable(
            notes="Non-refundable rate"
        )
        await booking_store.save_booking(sample_booking)

        result = await booking_service.cancel_booking(
            booking_id=sample_booking.booking_id,
        )

        assert result.success is False
        assert result.data["error_code"] == "CANCELLATION_NOT_ALLOWED"
        assert "non-refundable" in result.message

    @pytest.mark.asyncio
    async def test_cancel_booking_free_cancellation(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test cancel_booking with free cancellation window.

        Per design doc Booking Safety section:
        - Free cancellation within the policy window
        - Full refund when cancelling before deadline
        """
        # Set up booking within free cancellation period
        now = datetime.now(timezone.utc)
        sample_booking.status = BookingStatus.BOOKED
        sample_booking.booking_reference = "REF-12345678"
        sample_booking.price = 450.00
        sample_booking.cancellation_policy = CancellationPolicy.free_cancellation(
            until=now + timedelta(days=7),  # 7 days in the future
            fee_after=0.5,
        )
        # Add a current quote
        sample_booking.current_quote = BookingQuote(
            quote_id="quote_cancel_test00000000000000",
            booking_id=sample_booking.booking_id,
            quoted_price=450.00,
            currency="EUR",
            expires_at=now + timedelta(minutes=15),
            terms_hash=sample_booking.cancellation_policy.compute_hash(),
            terms_summary="Free cancellation",
            created_at=now,
        )
        await booking_store.save_booking(sample_booking)

        result = await booking_service.cancel_booking(
            booking_id=sample_booking.booking_id,
        )

        # Should succeed with full refund
        assert result.success is True
        assert "cancelled successfully" in result.message
        assert result.data is not None
        assert result.data["refund_amount"] == 450.00
        assert result.data["cancellation_fee"] == 0.0
        assert result.data["cancellation_reference"].startswith("CANCEL-")

        # Verify booking is updated in store
        updated_booking = await booking_store.get_booking(sample_booking.booking_id)
        assert updated_booking is not None
        assert updated_booking.status == BookingStatus.CANCELLED
        assert updated_booking.cancelled_at is not None
        assert updated_booking.refund_amount == 450.00

    @pytest.mark.asyncio
    async def test_cancel_booking_requires_fee_confirmation(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test cancel_booking requires confirmation when fee applies.

        Per design doc Booking Safety section:
        - After free cancellation period, fee may apply
        - User must confirm the fee before cancellation proceeds
        """
        # Set up booking past free cancellation period
        now = datetime.now(timezone.utc)
        sample_booking.status = BookingStatus.BOOKED
        sample_booking.booking_reference = "REF-12345678"
        sample_booking.price = 450.00
        sample_booking.cancellation_policy = CancellationPolicy.free_cancellation(
            until=now - timedelta(days=1),  # 1 day in the past
            fee_after=0.5,  # 50% fee
        )
        sample_booking.current_quote = BookingQuote(
            quote_id="quote_fee_test00000000000000000",
            booking_id=sample_booking.booking_id,
            quoted_price=450.00,
            currency="EUR",
            expires_at=now + timedelta(minutes=15),
            terms_hash=sample_booking.cancellation_policy.compute_hash(),
            terms_summary="Free cancellation",
            created_at=now,
        )
        await booking_store.save_booking(sample_booking)

        # First call without fee confirmation
        result = await booking_service.cancel_booking(
            booking_id=sample_booking.booking_id,
            confirm_fee=False,
        )

        # Should return fee confirmation request
        assert result.success is False
        assert result.data["error_code"] == "CANCELLATION_FEE_REQUIRED"
        assert "$225.00" in result.message  # 50% of 450
        assert result.data is not None
        assert result.data["cancellation_fee"] == 225.00
        assert result.data["refund_amount"] == 225.00

        # Should have UI actions
        assert result.ui is not None
        assert result.ui.actions
        # Find confirm cancel action
        confirm_action = next(
            (a for a in result.ui.actions if "Cancel" in a.label),
            None,
        )
        assert confirm_action is not None
        assert confirm_action.event["type"] == "cancel_booking"
        assert confirm_action.event["booking"]["confirm_fee"] is True

        # Booking should NOT be cancelled yet
        booking_check = await booking_store.get_booking(sample_booking.booking_id)
        assert booking_check is not None
        assert booking_check.status == BookingStatus.BOOKED

    @pytest.mark.asyncio
    async def test_cancel_booking_with_confirmed_fee(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test cancel_booking proceeds when fee is confirmed.

        Per design doc Booking Safety section:
        - Once user confirms fee, cancellation proceeds
        - Refund amount is original price minus fee
        """
        # Set up booking past free cancellation period
        now = datetime.now(timezone.utc)
        sample_booking.status = BookingStatus.BOOKED
        sample_booking.booking_reference = "REF-12345678"
        sample_booking.price = 450.00
        sample_booking.cancellation_policy = CancellationPolicy.free_cancellation(
            until=now - timedelta(days=1),  # 1 day in the past
            fee_after=0.5,  # 50% fee
        )
        sample_booking.current_quote = BookingQuote(
            quote_id="quote_confirmed_fee_test0000000000",
            booking_id=sample_booking.booking_id,
            quoted_price=450.00,
            currency="EUR",
            expires_at=now + timedelta(minutes=15),
            terms_hash=sample_booking.cancellation_policy.compute_hash(),
            terms_summary="Free cancellation",
            created_at=now,
        )
        await booking_store.save_booking(sample_booking)

        # Call with fee confirmation
        result = await booking_service.cancel_booking(
            booking_id=sample_booking.booking_id,
            confirm_fee=True,
        )

        # Should succeed with partial refund
        assert result.success is True
        assert "cancelled successfully" in result.message
        assert result.data is not None
        assert result.data["refund_amount"] == 225.00  # 50% of 450
        assert result.data["cancellation_fee"] == 225.00

        # Verify booking is updated in store
        updated_booking = await booking_store.get_booking(sample_booking.booking_id)
        assert updated_booking is not None
        assert updated_booking.status == BookingStatus.CANCELLED
        assert updated_booking.cancelled_at is not None
        assert updated_booking.refund_amount == 225.00

    @pytest.mark.asyncio
    async def test_cancel_booking_updates_fields(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test cancel_booking updates all required booking fields.

        Per design doc Booking Safety section:
        - Booking records store cancellation_reference and refund_amount
        - cancelled_at timestamp is recorded
        """
        now = datetime.now(timezone.utc)
        sample_booking.status = BookingStatus.BOOKED
        sample_booking.booking_reference = "REF-12345678"
        sample_booking.price = 450.00
        sample_booking.cancellation_policy = CancellationPolicy.free_cancellation(
            until=now + timedelta(days=7),
            fee_after=0.5,
        )
        sample_booking.current_quote = BookingQuote(
            quote_id="quote_fields_test00000000000000",
            booking_id=sample_booking.booking_id,
            quoted_price=450.00,
            currency="EUR",
            expires_at=now + timedelta(minutes=15),
            terms_hash=sample_booking.cancellation_policy.compute_hash(),
            terms_summary="Free cancellation",
            created_at=now,
        )
        await booking_store.save_booking(sample_booking)

        result = await booking_service.cancel_booking(
            booking_id=sample_booking.booking_id,
        )

        assert result.success is True

        # Verify all fields are updated
        updated_booking = await booking_store.get_booking(sample_booking.booking_id)
        assert updated_booking is not None
        assert updated_booking.status == BookingStatus.CANCELLED
        assert updated_booking.cancelled_at is not None
        assert updated_booking.cancellation_reference is not None
        assert updated_booking.cancellation_reference.startswith("CANCEL-")
        assert updated_booking.refund_amount == 450.00
        assert updated_booking.updated_at is not None

    @pytest.mark.asyncio
    async def test_cancel_booking_not_found(
        self,
        booking_service: BookingService,
    ) -> None:
        """Test cancel_booking returns error for unknown booking_id."""
        result = await booking_service.cancel_booking(
            booking_id="book_nonexistent00000000000000000000",
        )

        assert result.success is False
        assert result.data["error_code"] == "BOOKING_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_cancel_booking_fixed_fee_policy(
        self,
        booking_service: BookingService,
        booking_store: InMemoryBookingStore,
        sample_booking: Booking,
    ) -> None:
        """Test cancel_booking with fixed fee policy.

        Per design doc Booking Safety section:
        - Fixed fee takes precedence over percentage if > 0
        """
        now = datetime.now(timezone.utc)
        sample_booking.status = BookingStatus.BOOKED
        sample_booking.booking_reference = "REF-12345678"
        sample_booking.price = 450.00
        sample_booking.cancellation_policy = CancellationPolicy(
            is_cancellable=True,
            free_cancellation_until=now - timedelta(days=1),
            fee_fixed=50.00,  # Fixed $50 fee
        )
        sample_booking.current_quote = BookingQuote(
            quote_id="quote_fixed_fee_test00000000000",
            booking_id=sample_booking.booking_id,
            quoted_price=450.00,
            currency="EUR",
            expires_at=now + timedelta(minutes=15),
            terms_hash=sample_booking.cancellation_policy.compute_hash(),
            terms_summary="Fixed fee cancellation",
            created_at=now,
        )
        await booking_store.save_booking(sample_booking)

        # Call with fee confirmation
        result = await booking_service.cancel_booking(
            booking_id=sample_booking.booking_id,
            confirm_fee=True,
        )

        assert result.success is True
        assert result.data is not None
        assert result.data["cancellation_fee"] == 50.00
        assert result.data["refund_amount"] == 400.00  # 450 - 50


