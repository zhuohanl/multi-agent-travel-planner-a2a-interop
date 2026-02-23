"""Unit tests for booking models.

Tests for ORCH-068: Booking models (Booking, BookingQuote, BookingStatus, CancellationPolicy)
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.orchestrator.models.booking import (
    Booking,
    BookingQuote,
    BookingStatus,
    CancellationPolicy,
)


class TestBookingStatus:
    """Tests for BookingStatus enum."""

    def test_booking_status_enum_values(self):
        """Test all status values are defined."""
        assert BookingStatus.UNBOOKED.value == "unbooked"
        assert BookingStatus.PENDING.value == "pending"
        assert BookingStatus.BOOKED.value == "booked"
        assert BookingStatus.FAILED.value == "failed"
        assert BookingStatus.UNKNOWN.value == "unknown"
        assert BookingStatus.CANCELLED.value == "cancelled"

    def test_booking_status_str_enum(self):
        """Test BookingStatus inherits from str."""
        assert isinstance(BookingStatus.UNBOOKED, str)
        assert BookingStatus.UNBOOKED == "unbooked"

    def test_can_book_only_unbooked(self):
        """Test can_book returns True only for UNBOOKED."""
        assert BookingStatus.UNBOOKED.can_book() is True
        assert BookingStatus.PENDING.can_book() is False
        assert BookingStatus.BOOKED.can_book() is False
        assert BookingStatus.FAILED.can_book() is False
        assert BookingStatus.UNKNOWN.can_book() is False
        assert BookingStatus.CANCELLED.can_book() is False

    def test_can_retry_only_failed(self):
        """Test can_retry returns True only for FAILED."""
        assert BookingStatus.UNBOOKED.can_retry() is False
        assert BookingStatus.PENDING.can_retry() is False
        assert BookingStatus.BOOKED.can_retry() is False
        assert BookingStatus.FAILED.can_retry() is True
        assert BookingStatus.UNKNOWN.can_retry() is False
        assert BookingStatus.CANCELLED.can_retry() is False

    def test_can_cancel_only_booked(self):
        """Test can_cancel returns True only for BOOKED."""
        assert BookingStatus.UNBOOKED.can_cancel() is False
        assert BookingStatus.PENDING.can_cancel() is False
        assert BookingStatus.BOOKED.can_cancel() is True
        assert BookingStatus.FAILED.can_cancel() is False
        assert BookingStatus.UNKNOWN.can_cancel() is False
        assert BookingStatus.CANCELLED.can_cancel() is False

    def test_needs_reconciliation(self):
        """Test needs_reconciliation for UNKNOWN and PENDING."""
        assert BookingStatus.UNBOOKED.needs_reconciliation() is False
        assert BookingStatus.PENDING.needs_reconciliation() is True
        assert BookingStatus.BOOKED.needs_reconciliation() is False
        assert BookingStatus.FAILED.needs_reconciliation() is False
        assert BookingStatus.UNKNOWN.needs_reconciliation() is True
        assert BookingStatus.CANCELLED.needs_reconciliation() is False

    def test_is_terminal(self):
        """Test is_terminal for CANCELLED."""
        assert BookingStatus.UNBOOKED.is_terminal() is False
        assert BookingStatus.PENDING.is_terminal() is False
        assert BookingStatus.BOOKED.is_terminal() is False
        assert BookingStatus.FAILED.is_terminal() is False
        assert BookingStatus.UNKNOWN.is_terminal() is False
        assert BookingStatus.CANCELLED.is_terminal() is True


class TestCancellationPolicy:
    """Tests for CancellationPolicy dataclass."""

    def test_cancellation_policy_creation(self):
        """Test basic policy creation."""
        policy = CancellationPolicy(
            is_cancellable=True,
            free_cancellation_until=datetime(2026, 3, 15, tzinfo=timezone.utc),
            fee_percentage=0.2,
            fee_fixed=0.0,
            notes="Free cancellation until Mar 15",
        )
        assert policy.is_cancellable is True
        assert policy.free_cancellation_until == datetime(2026, 3, 15, tzinfo=timezone.utc)
        assert policy.fee_percentage == 0.2
        assert policy.notes == "Free cancellation until Mar 15"

    def test_non_refundable_factory(self):
        """Test non_refundable factory method."""
        policy = CancellationPolicy.non_refundable("No refunds allowed")
        assert policy.is_cancellable is False
        assert policy.free_cancellation_until is None
        assert policy.notes == "No refunds allowed"

    def test_non_refundable_factory_default_notes(self):
        """Test non_refundable factory with default notes."""
        policy = CancellationPolicy.non_refundable()
        assert policy.is_cancellable is False
        assert policy.notes == "Non-refundable booking"

    def test_free_cancellation_factory(self):
        """Test free_cancellation factory method."""
        deadline = datetime(2026, 3, 15, tzinfo=timezone.utc)
        policy = CancellationPolicy.free_cancellation(until=deadline, fee_after=0.5)
        assert policy.is_cancellable is True
        assert policy.free_cancellation_until == deadline
        assert policy.fee_percentage == 0.5

    def test_compute_hash_consistent(self):
        """Test compute_hash returns consistent value."""
        policy = CancellationPolicy(
            is_cancellable=True,
            free_cancellation_until=datetime(2026, 3, 15, tzinfo=timezone.utc),
            fee_percentage=0.2,
        )
        hash1 = policy.compute_hash()
        hash2 = policy.compute_hash()
        assert hash1 == hash2
        assert len(hash1) == 16  # SHA256 truncated to 16 chars

    def test_compute_hash_different_for_different_policies(self):
        """Test compute_hash differs for different policies."""
        policy1 = CancellationPolicy(is_cancellable=True, fee_percentage=0.2)
        policy2 = CancellationPolicy(is_cancellable=True, fee_percentage=0.3)
        assert policy1.compute_hash() != policy2.compute_hash()

    def test_calculate_fee_non_cancellable(self):
        """Test calculate_fee for non-refundable booking."""
        policy = CancellationPolicy.non_refundable()
        assert policy.calculate_fee(100.0) == 100.0  # Full amount

    def test_calculate_fee_within_free_period(self):
        """Test calculate_fee within free cancellation period."""
        future = datetime.now(timezone.utc) + timedelta(days=7)
        policy = CancellationPolicy.free_cancellation(until=future, fee_after=0.5)
        assert policy.calculate_fee(100.0) == 0.0

    def test_calculate_fee_after_free_period(self):
        """Test calculate_fee after free cancellation period."""
        past = datetime.now(timezone.utc) - timedelta(days=7)
        policy = CancellationPolicy.free_cancellation(until=past, fee_after=0.5)
        assert policy.calculate_fee(100.0) == 50.0

    def test_calculate_fee_fixed_takes_precedence(self):
        """Test calculate_fee with fixed fee (takes precedence)."""
        past = datetime.now(timezone.utc) - timedelta(days=7)
        policy = CancellationPolicy(
            is_cancellable=True,
            free_cancellation_until=past,
            fee_percentage=0.5,
            fee_fixed=25.0,
        )
        assert policy.calculate_fee(100.0) == 25.0

    def test_calculate_fee_fixed_capped_at_amount(self):
        """Test calculate_fee fixed fee doesn't exceed booking amount."""
        past = datetime.now(timezone.utc) - timedelta(days=7)
        policy = CancellationPolicy(
            is_cancellable=True,
            free_cancellation_until=past,
            fee_fixed=150.0,
        )
        assert policy.calculate_fee(100.0) == 100.0  # Capped

    def test_is_in_free_period_true(self):
        """Test is_in_free_period when within period."""
        future = datetime.now(timezone.utc) + timedelta(days=7)
        policy = CancellationPolicy.free_cancellation(until=future)
        assert policy.is_in_free_period() is True

    def test_is_in_free_period_false_past(self):
        """Test is_in_free_period when period expired."""
        past = datetime.now(timezone.utc) - timedelta(days=7)
        policy = CancellationPolicy.free_cancellation(until=past)
        assert policy.is_in_free_period() is False

    def test_is_in_free_period_false_non_cancellable(self):
        """Test is_in_free_period for non-cancellable."""
        policy = CancellationPolicy.non_refundable()
        assert policy.is_in_free_period() is False

    def test_to_dict(self):
        """Test serialization to dictionary."""
        policy = CancellationPolicy(
            is_cancellable=True,
            free_cancellation_until=datetime(2026, 3, 15, tzinfo=timezone.utc),
            fee_percentage=0.2,
            fee_fixed=10.0,
            notes="Test notes",
        )
        data = policy.to_dict()
        assert data["is_cancellable"] is True
        assert data["fee_percentage"] == 0.2
        assert data["fee_fixed"] == 10.0
        assert data["notes"] == "Test notes"
        assert "free_cancellation_until" in data

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "is_cancellable": True,
            "free_cancellation_until": "2026-03-15T00:00:00+00:00",
            "fee_percentage": 0.2,
            "fee_fixed": 10.0,
            "notes": "Test notes",
        }
        policy = CancellationPolicy.from_dict(data)
        assert policy.is_cancellable is True
        assert policy.free_cancellation_until is not None
        assert policy.fee_percentage == 0.2
        assert policy.fee_fixed == 10.0
        assert policy.notes == "Test notes"

    def test_from_dict_defaults(self):
        """Test from_dict with minimal data."""
        data = {}
        policy = CancellationPolicy.from_dict(data)
        assert policy.is_cancellable is True  # Default
        assert policy.free_cancellation_until is None
        assert policy.fee_percentage == 0.0
        assert policy.fee_fixed == 0.0


class TestBookingQuote:
    """Tests for BookingQuote dataclass."""

    def test_booking_quote_creation(self):
        """Test basic quote creation."""
        quote = BookingQuote(
            quote_id="quote_abc123",
            booking_id="book_xyz789",
            quoted_price=1240.00,
            currency="USD",
            expires_at=datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc),
            terms_hash="abc123def456",
            terms_summary="Free cancellation until Mar 8",
        )
        assert quote.quote_id == "quote_abc123"
        assert quote.booking_id == "book_xyz789"
        assert quote.quoted_price == 1240.00
        assert quote.currency == "USD"

    def test_is_expired_not_expired(self):
        """Test is_expired returns False for valid quote."""
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        quote = BookingQuote(
            quote_id="q1",
            booking_id="b1",
            quoted_price=100.0,
            currency="USD",
            expires_at=future,
            terms_hash="hash",
            terms_summary="Terms",
        )
        assert quote.is_expired() is False

    def test_is_expired_expired(self):
        """Test is_expired returns True for expired quote."""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        quote = BookingQuote(
            quote_id="q1",
            booking_id="b1",
            quoted_price=100.0,
            currency="USD",
            expires_at=past,
            terms_hash="hash",
            terms_summary="Terms",
        )
        assert quote.is_expired() is True

    def test_terms_match_true(self):
        """Test terms_match returns True when hashes match."""
        policy = CancellationPolicy(is_cancellable=True, fee_percentage=0.2)
        quote = BookingQuote(
            quote_id="q1",
            booking_id="b1",
            quoted_price=100.0,
            currency="USD",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            terms_hash=policy.compute_hash(),
            terms_summary="Terms",
        )
        assert quote.terms_match(policy) is True

    def test_terms_match_false(self):
        """Test terms_match returns False when hashes differ."""
        policy1 = CancellationPolicy(is_cancellable=True, fee_percentage=0.2)
        policy2 = CancellationPolicy(is_cancellable=True, fee_percentage=0.5)
        quote = BookingQuote(
            quote_id="q1",
            booking_id="b1",
            quoted_price=100.0,
            currency="USD",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            terms_hash=policy1.compute_hash(),
            terms_summary="Terms",
        )
        assert quote.terms_match(policy2) is False

    def test_time_remaining_positive(self):
        """Test time_remaining for unexpired quote."""
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        quote = BookingQuote(
            quote_id="q1",
            booking_id="b1",
            quoted_price=100.0,
            currency="USD",
            expires_at=future,
            terms_hash="hash",
            terms_summary="Terms",
        )
        remaining = quote.time_remaining()
        assert remaining.total_seconds() > 0
        assert remaining.total_seconds() < 2 * 3600 + 1  # Less than ~2 hours

    def test_time_remaining_negative(self):
        """Test time_remaining for expired quote."""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        quote = BookingQuote(
            quote_id="q1",
            booking_id="b1",
            quoted_price=100.0,
            currency="USD",
            expires_at=past,
            terms_hash="hash",
            terms_summary="Terms",
        )
        remaining = quote.time_remaining()
        assert remaining.total_seconds() < 0

    def test_to_dict(self):
        """Test serialization to dictionary."""
        quote = BookingQuote(
            quote_id="quote_abc123",
            booking_id="book_xyz789",
            quoted_price=1240.00,
            currency="USD",
            expires_at=datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc),
            terms_hash="abc123def456",
            terms_summary="Free cancellation",
            created_at=datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
        )
        data = quote.to_dict()
        assert data["quote_id"] == "quote_abc123"
        assert data["booking_id"] == "book_xyz789"
        assert data["quoted_price"] == 1240.00
        assert data["currency"] == "USD"
        assert data["terms_hash"] == "abc123def456"
        assert "expires_at" in data
        assert "created_at" in data

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "quote_id": "quote_abc123",
            "booking_id": "book_xyz789",
            "quoted_price": 1240.00,
            "currency": "USD",
            "expires_at": "2026-03-15T12:00:00+00:00",
            "terms_hash": "abc123def456",
            "terms_summary": "Free cancellation",
            "created_at": "2026-03-15T10:00:00+00:00",
        }
        quote = BookingQuote.from_dict(data)
        assert quote.quote_id == "quote_abc123"
        assert quote.booking_id == "book_xyz789"
        assert quote.quoted_price == 1240.00
        assert quote.currency == "USD"
        assert quote.terms_summary == "Free cancellation"


class TestBooking:
    """Tests for Booking dataclass."""

    @pytest.fixture
    def sample_policy(self):
        """Create a sample cancellation policy."""
        return CancellationPolicy(
            is_cancellable=True,
            free_cancellation_until=datetime.now(timezone.utc) + timedelta(days=7),
            fee_percentage=0.2,
        )

    @pytest.fixture
    def sample_quote(self):
        """Create a sample booking quote."""
        return BookingQuote(
            quote_id="quote_abc123",
            booking_id="book_xyz789",
            quoted_price=1240.00,
            currency="USD",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            terms_hash="abc123",
            terms_summary="Free cancellation",
        )

    def test_booking_creation(self, sample_policy):
        """Test basic booking creation."""
        booking = Booking(
            booking_id="book_xyz789",
            itinerary_id="itn_abc123",
            item_type="flight",
            details={"airline": "JAL", "flight": "JL123"},
            status=BookingStatus.UNBOOKED,
            cancellation_policy=sample_policy,
            price=1240.00,
        )
        assert booking.booking_id == "book_xyz789"
        assert booking.item_type == "flight"
        assert booking.status == BookingStatus.UNBOOKED
        assert booking.price == 1240.00

    def test_create_unbooked_factory(self, sample_policy):
        """Test create_unbooked factory method."""
        booking = Booking.create_unbooked(
            booking_id="book_xyz789",
            itinerary_id="itn_abc123",
            item_type="hotel",
            details={"hotel": "Park Hyatt"},
            price=2100.00,
            cancellation_policy=sample_policy,
        )
        assert booking.booking_id == "book_xyz789"
        assert booking.status == BookingStatus.UNBOOKED
        assert booking.item_type == "hotel"
        assert booking.updated_at is not None

    def test_can_book_delegates_to_status(self, sample_policy):
        """Test can_book delegates to status."""
        booking = Booking.create_unbooked(
            booking_id="book_1",
            itinerary_id="itn_1",
            item_type="activity",
            details={},
            price=100.0,
            cancellation_policy=sample_policy,
        )
        assert booking.can_book() is True

        booking.status = BookingStatus.BOOKED
        assert booking.can_book() is False

    def test_can_retry_delegates_to_status(self, sample_policy):
        """Test can_retry delegates to status."""
        booking = Booking.create_unbooked(
            booking_id="book_1",
            itinerary_id="itn_1",
            item_type="activity",
            details={},
            price=100.0,
            cancellation_policy=sample_policy,
        )
        assert booking.can_retry() is False

        booking.status = BookingStatus.FAILED
        assert booking.can_retry() is True

    def test_can_cancel_delegates_to_status(self, sample_policy):
        """Test can_cancel delegates to status."""
        booking = Booking.create_unbooked(
            booking_id="book_1",
            itinerary_id="itn_1",
            item_type="activity",
            details={},
            price=100.0,
            cancellation_policy=sample_policy,
        )
        assert booking.can_cancel() is False

        booking.status = BookingStatus.BOOKED
        assert booking.can_cancel() is True

    def test_is_quote_valid_no_quote(self, sample_policy):
        """Test is_quote_valid returns False with no quote."""
        booking = Booking.create_unbooked(
            booking_id="book_1",
            itinerary_id="itn_1",
            item_type="activity",
            details={},
            price=100.0,
            cancellation_policy=sample_policy,
        )
        assert booking.is_quote_valid() is False

    def test_is_quote_valid_with_valid_quote(self, sample_policy, sample_quote):
        """Test is_quote_valid returns True with valid quote."""
        booking = Booking.create_unbooked(
            booking_id="book_xyz789",
            itinerary_id="itn_1",
            item_type="activity",
            details={},
            price=100.0,
            cancellation_policy=sample_policy,
        )
        booking.current_quote = sample_quote
        assert booking.is_quote_valid() is True

    def test_is_quote_valid_with_expired_quote(self, sample_policy):
        """Test is_quote_valid returns False with expired quote."""
        expired_quote = BookingQuote(
            quote_id="quote_old",
            booking_id="book_1",
            quoted_price=100.0,
            currency="USD",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            terms_hash="hash",
            terms_summary="Terms",
        )
        booking = Booking.create_unbooked(
            booking_id="book_1",
            itinerary_id="itn_1",
            item_type="activity",
            details={},
            price=100.0,
            cancellation_policy=sample_policy,
        )
        booking.current_quote = expired_quote
        assert booking.is_quote_valid() is False

    def test_is_quote_valid_with_quote_id_mismatch(self, sample_policy, sample_quote):
        """Test is_quote_valid returns False when quote_id doesn't match."""
        booking = Booking.create_unbooked(
            booking_id="book_xyz789",
            itinerary_id="itn_1",
            item_type="activity",
            details={},
            price=100.0,
            cancellation_policy=sample_policy,
        )
        booking.current_quote = sample_quote
        assert booking.is_quote_valid(quote_id="quote_different") is False

    def test_is_quote_valid_with_quote_id_match(self, sample_policy, sample_quote):
        """Test is_quote_valid returns True when quote_id matches."""
        booking = Booking.create_unbooked(
            booking_id="book_xyz789",
            itinerary_id="itn_1",
            item_type="activity",
            details={},
            price=100.0,
            cancellation_policy=sample_policy,
        )
        booking.current_quote = sample_quote
        assert booking.is_quote_valid(quote_id="quote_abc123") is True

    def test_generate_provider_request_id(self, sample_policy):
        """Test generate_provider_request_id creates correct format."""
        booking = Booking.create_unbooked(
            booking_id="book_xyz789",
            itinerary_id="itn_1",
            item_type="activity",
            details={},
            price=100.0,
            cancellation_policy=sample_policy,
        )
        request_id = booking.generate_provider_request_id("quote_abc123")
        assert request_id == "book_xyz789:quote_abc123"

    def test_to_dict(self, sample_policy, sample_quote):
        """Test serialization to dictionary."""
        booking = Booking(
            booking_id="book_xyz789",
            itinerary_id="itn_abc123",
            item_type="flight",
            details={"airline": "JAL"},
            status=BookingStatus.BOOKED,
            cancellation_policy=sample_policy,
            price=1240.00,
            current_quote=sample_quote,
            booking_reference="JAL-12345",
            confirmed_quote_id="quote_abc123",
            etag="etag123",
            provider_request_id="book_xyz789:quote_abc123",
            updated_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
        )
        data = booking.to_dict()
        assert data["booking_id"] == "book_xyz789"
        assert data["id"] == "book_xyz789"  # Cosmos DB ID
        assert data["itinerary_id"] == "itn_abc123"
        assert data["item_type"] == "flight"
        assert data["status"] == "booked"
        assert data["price"] == 1240.00
        assert data["booking_reference"] == "JAL-12345"
        assert data["confirmed_quote_id"] == "quote_abc123"
        assert data["_etag"] == "etag123"
        assert "current_quote" in data
        assert "cancellation_policy" in data

    def test_to_dict_minimal(self, sample_policy):
        """Test serialization with minimal fields."""
        booking = Booking.create_unbooked(
            booking_id="book_1",
            itinerary_id="itn_1",
            item_type="activity",
            details={},
            price=100.0,
            cancellation_policy=sample_policy,
        )
        data = booking.to_dict()
        assert data["booking_id"] == "book_1"
        assert data["status"] == "unbooked"
        # Optional fields should not be present
        assert "booking_reference" not in data
        assert "confirmed_quote_id" not in data
        assert "_etag" not in data

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "booking_id": "book_xyz789",
            "itinerary_id": "itn_abc123",
            "item_type": "flight",
            "details": {"airline": "JAL"},
            "status": "booked",
            "cancellation_policy": {
                "is_cancellable": True,
                "fee_percentage": 0.2,
            },
            "price": 1240.00,
            "booking_reference": "JAL-12345",
            "confirmed_quote_id": "quote_abc123",
            "_etag": "etag123",
            "updated_at": "2026-03-15T00:00:00+00:00",
        }
        booking = Booking.from_dict(data)
        assert booking.booking_id == "book_xyz789"
        assert booking.item_type == "flight"
        assert booking.status == BookingStatus.BOOKED
        assert booking.price == 1240.00
        assert booking.booking_reference == "JAL-12345"
        assert booking.etag == "etag123"

    def test_from_dict_with_quote(self):
        """Test deserialization with quote data."""
        data = {
            "booking_id": "book_xyz789",
            "itinerary_id": "itn_abc123",
            "item_type": "hotel",
            "details": {},
            "status": "unbooked",
            "cancellation_policy": {"is_cancellable": True},
            "price": 2100.00,
            "current_quote": {
                "quote_id": "quote_abc123",
                "booking_id": "book_xyz789",
                "quoted_price": 2100.00,
                "currency": "USD",
                "expires_at": "2026-03-15T12:00:00+00:00",
                "terms_hash": "hash123",
                "terms_summary": "Free cancellation",
            },
        }
        booking = Booking.from_dict(data)
        assert booking.current_quote is not None
        assert booking.current_quote.quote_id == "quote_abc123"
        assert booking.current_quote.quoted_price == 2100.00

    def test_from_dict_invalid_status(self):
        """Test from_dict with invalid status defaults to UNBOOKED."""
        data = {
            "booking_id": "book_1",
            "itinerary_id": "itn_1",
            "item_type": "activity",
            "details": {},
            "status": "invalid_status",
            "price": 100.0,
        }
        booking = Booking.from_dict(data)
        assert booking.status == BookingStatus.UNBOOKED

    def test_from_dict_invalid_item_type(self):
        """Test from_dict with invalid item_type defaults to activity."""
        data = {
            "booking_id": "book_1",
            "itinerary_id": "itn_1",
            "item_type": "invalid_type",
            "details": {},
            "status": "unbooked",
            "price": 100.0,
        }
        booking = Booking.from_dict(data)
        assert booking.item_type == "activity"

    def test_from_dict_with_id_fallback(self):
        """Test from_dict uses 'id' if 'booking_id' is missing."""
        data = {
            "id": "book_from_id",
            "itinerary_id": "itn_1",
            "item_type": "flight",
            "details": {},
            "status": "unbooked",
            "price": 100.0,
        }
        booking = Booking.from_dict(data)
        assert booking.booking_id == "book_from_id"

    def test_str_representation(self, sample_policy):
        """Test string representation."""
        booking = Booking.create_unbooked(
            booking_id="book_xyz789",
            itinerary_id="itn_1",
            item_type="flight",
            details={},
            price=1240.00,
            cancellation_policy=sample_policy,
        )
        str_repr = str(booking)
        assert "book_xyz789" in str_repr
        assert "flight" in str_repr
        assert "unbooked" in str_repr
        assert "1240.00" in str_repr

    def test_booking_with_cancellation_fields(self, sample_policy):
        """Test booking with cancellation fields."""
        booking = Booking.create_unbooked(
            booking_id="book_1",
            itinerary_id="itn_1",
            item_type="hotel",
            details={},
            price=500.0,
            cancellation_policy=sample_policy,
        )
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = datetime(2026, 3, 20, tzinfo=timezone.utc)
        booking.cancellation_reference = "CANCEL-12345"
        booking.refund_amount = 400.0

        data = booking.to_dict()
        assert data["status"] == "cancelled"
        assert "cancelled_at" in data
        assert data["cancellation_reference"] == "CANCEL-12345"
        assert data["refund_amount"] == 400.0

    def test_from_dict_with_cancellation_fields(self):
        """Test from_dict with cancellation fields."""
        data = {
            "booking_id": "book_1",
            "itinerary_id": "itn_1",
            "item_type": "hotel",
            "details": {},
            "status": "cancelled",
            "price": 500.0,
            "cancellation_policy": {"is_cancellable": True},
            "cancelled_at": "2026-03-20T00:00:00+00:00",
            "cancellation_reference": "CANCEL-12345",
            "refund_amount": 400.0,
        }
        booking = Booking.from_dict(data)
        assert booking.status == BookingStatus.CANCELLED
        assert booking.cancelled_at is not None
        assert booking.cancellation_reference == "CANCEL-12345"
        assert booking.refund_amount == 400.0


class TestBookingRoundTrip:
    """Test serialization round-trip for all models."""

    def test_cancellation_policy_roundtrip(self):
        """Test CancellationPolicy survives serialization round-trip."""
        original = CancellationPolicy(
            is_cancellable=True,
            free_cancellation_until=datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc),
            fee_percentage=0.25,
            fee_fixed=50.0,
            notes="Test policy",
        )
        data = original.to_dict()
        restored = CancellationPolicy.from_dict(data)

        assert restored.is_cancellable == original.is_cancellable
        assert restored.fee_percentage == original.fee_percentage
        assert restored.fee_fixed == original.fee_fixed
        assert restored.notes == original.notes

    def test_booking_quote_roundtrip(self):
        """Test BookingQuote survives serialization round-trip."""
        original = BookingQuote(
            quote_id="quote_abc123",
            booking_id="book_xyz789",
            quoted_price=1240.50,
            currency="EUR",
            expires_at=datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc),
            terms_hash="abc123def456",
            terms_summary="Free cancellation until Mar 8",
            created_at=datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
        )
        data = original.to_dict()
        restored = BookingQuote.from_dict(data)

        assert restored.quote_id == original.quote_id
        assert restored.booking_id == original.booking_id
        assert restored.quoted_price == original.quoted_price
        assert restored.currency == original.currency
        assert restored.terms_hash == original.terms_hash
        assert restored.terms_summary == original.terms_summary

    def test_booking_roundtrip(self):
        """Test full Booking survives serialization round-trip."""
        policy = CancellationPolicy(
            is_cancellable=True,
            fee_percentage=0.2,
        )
        quote = BookingQuote(
            quote_id="quote_abc123",
            booking_id="book_xyz789",
            quoted_price=1240.00,
            currency="USD",
            expires_at=datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc),
            terms_hash="abc123",
            terms_summary="Terms",
        )
        original = Booking(
            booking_id="book_xyz789",
            itinerary_id="itn_abc123",
            item_type="flight",
            details={"airline": "JAL", "flight": "JL123"},
            status=BookingStatus.BOOKED,
            cancellation_policy=policy,
            price=1240.00,
            current_quote=quote,
            booking_reference="JAL-12345",
            confirmed_quote_id="quote_abc123",
            etag="etag123",
            provider_request_id="book_xyz789:quote_abc123",
            status_reason="Successfully booked",
            updated_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
        )
        data = original.to_dict()
        restored = Booking.from_dict(data)

        assert restored.booking_id == original.booking_id
        assert restored.itinerary_id == original.itinerary_id
        assert restored.item_type == original.item_type
        assert restored.status == original.status
        assert restored.price == original.price
        assert restored.booking_reference == original.booking_reference
        assert restored.confirmed_quote_id == original.confirmed_quote_id
        assert restored.etag == original.etag
        assert restored.provider_request_id == original.provider_request_id
        assert restored.status_reason == original.status_reason
        assert restored.current_quote is not None
        assert restored.current_quote.quote_id == original.current_quote.quote_id
