"""Unit tests for the get_booking lookup tool.

Tests cover:
- Basic booking lookup (found, not found)
- Booking ID validation (format checking)
- Booking details formatting
- Status-specific output formatting
- Quote expiration handling
- Cancellation policy display
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.orchestrator.models.booking import (
    Booking,
    BookingQuote,
    BookingStatus,
    CancellationPolicy,
)
from src.orchestrator.storage.booking_store import InMemoryBookingStore
from src.orchestrator.tools.lookups.get_booking import (
    BookingNotFoundError,
    GetBookingResult,
    format_booking_details,
    format_booking_status,
    format_item_type,
    format_price,
    get_booking,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def booking_store() -> InMemoryBookingStore:
    """Create an in-memory booking store for testing."""
    return InMemoryBookingStore()


@pytest.fixture
def sample_booking() -> Booking:
    """Create a sample booking for testing."""
    return Booking(
        booking_id="book_test123",
        itinerary_id="itin_abc456",
        item_type="hotel",
        details={
            "name": "Test Hotel",
            "location": "Tokyo, Japan",
            "check_in": "2026-03-15",
            "check_out": "2026-03-18",
        },
        status=BookingStatus.UNBOOKED,
        cancellation_policy=CancellationPolicy(
            is_cancellable=True,
            free_cancellation_until=datetime(2026, 3, 10, tzinfo=timezone.utc),
            fee_percentage=0.20,
            notes="20% fee after March 10",
        ),
        price=450.00,
    )


@pytest.fixture
def booked_booking() -> Booking:
    """Create a booked booking with confirmation."""
    return Booking(
        booking_id="book_booked789",
        itinerary_id="itin_abc456",
        item_type="flight",
        details={
            "name": "JAL Flight 123",
            "departure": "2026-03-15 10:00 NRT",
            "arrival": "2026-03-15 12:00 HND",
        },
        status=BookingStatus.BOOKED,
        cancellation_policy=CancellationPolicy.non_refundable(),
        price=350.00,
        booking_reference="JAL-ABC123",
        confirmed_quote_id="quote_xyz",
    )


@pytest.fixture
def failed_booking() -> Booking:
    """Create a failed booking with failure reason."""
    return Booking(
        booking_id="book_failed456",
        itinerary_id="itin_abc456",
        item_type="activity",
        details={
            "name": "Sushi Making Class",
            "date": "2026-03-16",
            "location": "Tokyo, Japan",
        },
        status=BookingStatus.FAILED,
        cancellation_policy=CancellationPolicy(is_cancellable=True),
        price=120.00,
        failure_reason="Payment declined - insufficient funds",
    )


@pytest.fixture
def booking_with_quote() -> Booking:
    """Create a booking with a valid quote."""
    quote = BookingQuote(
        quote_id="quote_valid123",
        booking_id="book_quoted999",
        quoted_price=500.00,
        currency="JPY",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        terms_hash="abc123",
        terms_summary="Free cancellation until check-in",
    )
    return Booking(
        booking_id="book_quoted999",
        itinerary_id="itin_abc456",
        item_type="hotel",
        details={"name": "Luxury Hotel"},
        status=BookingStatus.UNBOOKED,
        cancellation_policy=CancellationPolicy(is_cancellable=True),
        price=500.00,
        current_quote=quote,
    )


@pytest.fixture
def booking_with_expired_quote() -> Booking:
    """Create a booking with an expired quote."""
    quote = BookingQuote(
        quote_id="quote_expired123",
        booking_id="book_expiredquote",
        quoted_price=500.00,
        currency="USD",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),  # Expired
        terms_hash="abc123",
        terms_summary="Free cancellation",
    )
    return Booking(
        booking_id="book_expiredquote",
        itinerary_id="itin_abc456",
        item_type="hotel",
        details={"name": "Test Hotel"},
        status=BookingStatus.UNBOOKED,
        cancellation_policy=CancellationPolicy(is_cancellable=True),
        price=500.00,
        current_quote=quote,
    )


# =============================================================================
# Tests for format_booking_status
# =============================================================================


class TestFormatBookingStatus:
    """Tests for format_booking_status function."""

    def test_unbooked_status(self) -> None:
        """UNBOOKED status should show 'Not yet booked'."""
        assert format_booking_status(BookingStatus.UNBOOKED) == "Not yet booked"

    def test_pending_status(self) -> None:
        """PENDING status should show 'Booking in progress'."""
        assert format_booking_status(BookingStatus.PENDING) == "Booking in progress"

    def test_booked_status(self) -> None:
        """BOOKED status should show 'Confirmed'."""
        assert format_booking_status(BookingStatus.BOOKED) == "Confirmed"

    def test_failed_status(self) -> None:
        """FAILED status should show 'Booking failed'."""
        assert format_booking_status(BookingStatus.FAILED) == "Booking failed"

    def test_unknown_status(self) -> None:
        """UNKNOWN status should show verification message."""
        assert "verification" in format_booking_status(BookingStatus.UNKNOWN).lower()

    def test_cancelled_status(self) -> None:
        """CANCELLED status should show 'Cancelled'."""
        assert format_booking_status(BookingStatus.CANCELLED) == "Cancelled"


# =============================================================================
# Tests for format_item_type
# =============================================================================


class TestFormatItemType:
    """Tests for format_item_type function."""

    def test_flight_formatting(self) -> None:
        """Flight item type should be title-cased."""
        assert format_item_type("flight") == "Flight"

    def test_hotel_formatting(self) -> None:
        """Hotel item type should be title-cased."""
        assert format_item_type("hotel") == "Hotel"

    def test_activity_formatting(self) -> None:
        """Activity item type should be title-cased."""
        assert format_item_type("activity") == "Activity"


# =============================================================================
# Tests for format_price
# =============================================================================


class TestFormatPrice:
    """Tests for format_price function."""

    def test_usd_formatting(self) -> None:
        """USD price should show 2 decimal places."""
        assert format_price(100.50, "USD") == "100.50 USD"
        assert format_price(1000, "USD") == "1,000.00 USD"

    def test_jpy_formatting(self) -> None:
        """JPY price should show no decimal places."""
        assert format_price(15000, "JPY") == "15,000 JPY"
        assert format_price(100.50, "JPY") == "100 JPY"

    def test_eur_formatting(self) -> None:
        """EUR price should show 2 decimal places."""
        assert format_price(99.99, "EUR") == "99.99 EUR"

    def test_large_amount_formatting(self) -> None:
        """Large amounts should have thousand separators."""
        assert format_price(1234567.89, "USD") == "1,234,567.89 USD"


# =============================================================================
# Tests for format_booking_details
# =============================================================================


class TestFormatBookingDetails:
    """Tests for format_booking_details function."""

    def test_basic_details_formatting(self, sample_booking: Booking) -> None:
        """Basic booking should show ID, type, status, and price."""
        formatted = format_booking_details(sample_booking)
        assert "book_test123" in formatted
        assert "Hotel" in formatted
        assert "Not yet booked" in formatted
        assert "450.00" in formatted

    def test_includes_item_details(self, sample_booking: Booking) -> None:
        """Booking details dict should be included."""
        formatted = format_booking_details(sample_booking)
        assert "Test Hotel" in formatted
        assert "Tokyo, Japan" in formatted
        assert "2026-03-15" in formatted

    def test_booked_shows_confirmation(self, booked_booking: Booking) -> None:
        """Booked status should show confirmation reference."""
        formatted = format_booking_details(booked_booking)
        assert "JAL-ABC123" in formatted
        assert "Confirmed" in formatted

    def test_failed_shows_reason(self, failed_booking: Booking) -> None:
        """Failed booking should show failure reason."""
        formatted = format_booking_details(failed_booking)
        assert "Payment declined" in formatted

    def test_non_refundable_policy(self, booked_booking: Booking) -> None:
        """Non-refundable booking should show that."""
        formatted = format_booking_details(booked_booking)
        assert "Non-refundable" in formatted

    def test_free_cancellation_policy(self, sample_booking: Booking) -> None:
        """Policy with free period should show that."""
        # The sample booking has free cancellation until 2026-03-10 (future)
        formatted = format_booking_details(sample_booking)
        # Should show policy notes
        assert "20% fee after March 10" in formatted

    def test_valid_quote_shows_time_remaining(self, booking_with_quote: Booking) -> None:
        """Valid quote should show time remaining."""
        formatted = format_booking_details(booking_with_quote)
        assert "Valid for" in formatted
        assert "minutes" in formatted
        assert "quote_valid123" in formatted

    def test_expired_quote_shows_expired(self, booking_with_expired_quote: Booking) -> None:
        """Expired quote should indicate expiration."""
        formatted = format_booking_details(booking_with_expired_quote)
        assert "Expired" in formatted


# =============================================================================
# Tests for get_booking function
# =============================================================================


class TestGetBooking:
    """Tests for get_booking async function."""

    @pytest.mark.asyncio
    async def test_booking_found(
        self, booking_store: InMemoryBookingStore, sample_booking: Booking
    ) -> None:
        """Found booking should return success with details."""
        await booking_store.save_booking(sample_booking)

        result = await get_booking("book_test123", booking_store)

        assert result.success is True
        assert result.booking is not None
        assert result.booking.booking_id == "book_test123"
        assert result.formatted is not None
        assert "Test Hotel" in result.formatted
        assert result.data is not None
        assert result.data["booking_id"] == "book_test123"

    @pytest.mark.asyncio
    async def test_booking_not_found(self, booking_store: InMemoryBookingStore) -> None:
        """Missing booking should return failure."""
        result = await get_booking("book_nonexistent", booking_store)

        assert result.success is False
        assert result.booking is None
        assert "not found" in result.message.lower()

    @pytest.mark.asyncio
    async def test_empty_booking_id(self, booking_store: InMemoryBookingStore) -> None:
        """Empty booking ID should return failure."""
        result = await get_booking("", booking_store)

        assert result.success is False
        assert "required" in result.message.lower()

    @pytest.mark.asyncio
    async def test_invalid_booking_id_format(
        self, booking_store: InMemoryBookingStore
    ) -> None:
        """Invalid booking ID format should return failure."""
        result = await get_booking("invalid_format", booking_store)

        assert result.success is False
        assert "Invalid booking ID format" in result.message

    @pytest.mark.asyncio
    async def test_result_data_includes_status(
        self, booking_store: InMemoryBookingStore, sample_booking: Booking
    ) -> None:
        """Result data should include booking status."""
        await booking_store.save_booking(sample_booking)

        result = await get_booking("book_test123", booking_store)

        assert result.data is not None
        assert result.data["status"] == "unbooked"

    @pytest.mark.asyncio
    async def test_result_data_includes_details(
        self, booking_store: InMemoryBookingStore, sample_booking: Booking
    ) -> None:
        """Result data should include booking details dict."""
        await booking_store.save_booking(sample_booking)

        result = await get_booking("book_test123", booking_store)

        assert result.data is not None
        assert "details" in result.data
        assert result.data["details"]["name"] == "Test Hotel"

    @pytest.mark.asyncio
    async def test_result_data_includes_quote_when_present(
        self, booking_store: InMemoryBookingStore, booking_with_quote: Booking
    ) -> None:
        """Result data should include quote info when present."""
        await booking_store.save_booking(booking_with_quote)

        result = await get_booking("book_quoted999", booking_store)

        assert result.data is not None
        assert "quote" in result.data
        assert result.data["quote"]["quote_id"] == "quote_valid123"
        assert result.data["quote"]["quoted_price"] == 500.00
        assert result.data["quote"]["currency"] == "JPY"
        assert "is_expired" in result.data["quote"]

    @pytest.mark.asyncio
    async def test_result_data_includes_booking_reference(
        self, booking_store: InMemoryBookingStore, booked_booking: Booking
    ) -> None:
        """Result data should include booking reference when present."""
        await booking_store.save_booking(booked_booking)

        result = await get_booking("book_booked789", booking_store)

        assert result.data is not None
        assert result.data["booking_reference"] == "JAL-ABC123"

    @pytest.mark.asyncio
    async def test_result_data_includes_cancellation_policy(
        self, booking_store: InMemoryBookingStore, sample_booking: Booking
    ) -> None:
        """Result data should include cancellation policy."""
        await booking_store.save_booking(sample_booking)

        result = await get_booking("book_test123", booking_store)

        assert result.data is not None
        assert "cancellation_policy" in result.data
        assert result.data["cancellation_policy"]["is_cancellable"] is True
        assert result.data["cancellation_policy"]["fee_percentage"] == 0.20


class TestGetBookingResult:
    """Tests for GetBookingResult dataclass."""

    def test_to_dict_success(self, sample_booking: Booking) -> None:
        """Successful result should serialize with all fields."""
        result = GetBookingResult(
            success=True,
            message="Found booking",
            booking=sample_booking,
            formatted="Booking details...",
            data={"booking_id": "book_test123"},
        )

        serialized = result.to_dict()

        assert serialized["success"] is True
        assert serialized["message"] == "Found booking"
        assert serialized["formatted"] == "Booking details..."
        assert serialized["data"]["booking_id"] == "book_test123"

    def test_to_dict_failure(self) -> None:
        """Failed result should serialize without optional fields."""
        result = GetBookingResult(
            success=False,
            message="Booking not found",
        )

        serialized = result.to_dict()

        assert serialized["success"] is False
        assert serialized["message"] == "Booking not found"
        assert "formatted" not in serialized
        assert "data" not in serialized


class TestBookingNotFoundError:
    """Tests for BookingNotFoundError exception."""

    def test_error_with_booking_id(self) -> None:
        """Error should include booking ID."""
        error = BookingNotFoundError("book_test123")
        assert error.booking_id == "book_test123"
        assert "book_test123" in str(error)

    def test_error_with_custom_message(self) -> None:
        """Custom message should be used."""
        error = BookingNotFoundError("book_test123", "Custom error message")
        assert error.message == "Custom error message"
        assert str(error) == "Custom error message"
