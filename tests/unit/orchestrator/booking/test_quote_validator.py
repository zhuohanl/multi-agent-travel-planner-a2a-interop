"""Unit tests for quote_validator module.

Tests for ORCH-053: Implement quote validation (quote_id, expiry).
"""

import pytest
from datetime import datetime, timedelta, timezone

from src.orchestrator.booking.quote_validator import (
    QuoteValidationResult,
    QuoteValidationStatus,
    get_error_code_for_status,
    is_quote_expired,
    is_quote_valid_for_booking,
    validate_quote,
)
from src.orchestrator.models.booking import (
    Booking,
    BookingQuote,
    BookingStatus,
    CancellationPolicy,
)


@pytest.fixture
def valid_quote() -> BookingQuote:
    """Create a valid (non-expired) quote."""
    return BookingQuote(
        quote_id="quote_abc123",
        booking_id="book_12345678901234567890123456789012",
        quoted_price=450.00,
        currency="USD",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        terms_hash="hash123",
        terms_summary="Free cancellation until Jun 10, 2025",
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def expired_quote() -> BookingQuote:
    """Create an expired quote."""
    return BookingQuote(
        quote_id="quote_expired123",
        booking_id="book_12345678901234567890123456789012",
        quoted_price=450.00,
        currency="USD",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),  # Expired 5 minutes ago
        terms_hash="hash123",
        terms_summary="Free cancellation until Jun 10, 2025",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=20),
    )


@pytest.fixture
def sample_booking(valid_quote: BookingQuote) -> Booking:
    """Create a sample booking with a valid quote."""
    booking = Booking.create_unbooked(
        booking_id="book_12345678901234567890123456789012",
        itinerary_id="itn_12345678901234567890123456789012",
        item_type="hotel",
        details={
            "name": "Grand Hotel",
            "check_in": "2025-06-15",
            "check_out": "2025-06-18",
            "currency": "USD",
        },
        price=450.00,
        cancellation_policy=CancellationPolicy.free_cancellation(
            until=datetime(2025, 6, 10, tzinfo=timezone.utc),
            fee_after=0.5,
        ),
    )
    booking.current_quote = valid_quote
    return booking


class TestValidateQuote:
    """Tests for validate_quote function."""

    def test_valid_quote_accepted(self, sample_booking: Booking) -> None:
        """Test that a valid quote is accepted."""
        result = validate_quote(sample_booking, sample_booking.current_quote.quote_id)

        assert result.is_valid is True
        assert result.status == QuoteValidationStatus.VALID
        assert result.reason == "Quote is valid"

    def test_nonexistent_quote_rejected(self, sample_booking: Booking) -> None:
        """Test that missing quote is rejected."""
        sample_booking.current_quote = None

        result = validate_quote(sample_booking, "quote_any")

        assert result.is_valid is False
        assert result.status == QuoteValidationStatus.NOT_FOUND
        assert "No active quote" in result.reason

    def test_expired_quote_rejected(
        self, sample_booking: Booking, expired_quote: BookingQuote
    ) -> None:
        """Test that expired quote is rejected."""
        sample_booking.current_quote = expired_quote

        result = validate_quote(sample_booking, expired_quote.quote_id)

        assert result.is_valid is False
        assert result.status == QuoteValidationStatus.EXPIRED
        assert "expired" in result.reason.lower()
        assert result.current_quote is not None

    def test_quote_mismatch_rejected(self, sample_booking: Booking) -> None:
        """Test that mismatched quote ID is rejected."""
        result = validate_quote(sample_booking, "quote_different")

        assert result.is_valid is False
        assert result.status == QuoteValidationStatus.MISMATCH
        assert "changed" in result.reason.lower()
        assert result.current_quote is sample_booking.current_quote
        assert result.suggested_quote_id == sample_booking.current_quote.quote_id

    def test_used_quote_rejected(self, sample_booking: Booking) -> None:
        """Test that already-used quote is rejected."""
        # Mark quote as used
        sample_booking.confirmed_quote_id = sample_booking.current_quote.quote_id

        result = validate_quote(
            sample_booking,
            sample_booking.current_quote.quote_id,
            check_used=True
        )

        assert result.is_valid is False
        assert result.status == QuoteValidationStatus.ALREADY_USED
        assert "already used" in result.reason.lower()

    def test_check_used_false_skips_used_check(self, sample_booking: Booking) -> None:
        """Test that check_used=False skips the used quote check."""
        # Mark quote as used
        sample_booking.confirmed_quote_id = sample_booking.current_quote.quote_id

        result = validate_quote(
            sample_booking,
            sample_booking.current_quote.quote_id,
            check_used=False
        )

        # Should pass because we're not checking if used
        assert result.is_valid is True

    def test_validation_returns_reason(self, sample_booking: Booking) -> None:
        """Test that validation returns a human-readable reason."""
        sample_booking.current_quote = None

        result = validate_quote(sample_booking, "quote_any")

        assert isinstance(result.reason, str)
        assert len(result.reason) > 0


class TestQuoteValidationResult:
    """Tests for QuoteValidationResult class."""

    def test_valid_factory(self) -> None:
        """Test QuoteValidationResult.valid() factory method."""
        result = QuoteValidationResult.valid()

        assert result.is_valid is True
        assert result.status == QuoteValidationStatus.VALID

    def test_not_found_factory(self) -> None:
        """Test QuoteValidationResult.not_found() factory method."""
        result = QuoteValidationResult.not_found()

        assert result.is_valid is False
        assert result.status == QuoteValidationStatus.NOT_FOUND
        assert result.current_quote is None

    def test_expired_factory(self, valid_quote: BookingQuote) -> None:
        """Test QuoteValidationResult.expired() factory method."""
        result = QuoteValidationResult.expired(valid_quote)

        assert result.is_valid is False
        assert result.status == QuoteValidationStatus.EXPIRED
        assert result.current_quote is valid_quote
        assert result.suggested_quote_id == valid_quote.quote_id

    def test_mismatch_factory(self, valid_quote: BookingQuote) -> None:
        """Test QuoteValidationResult.mismatch() factory method."""
        result = QuoteValidationResult.mismatch(valid_quote)

        assert result.is_valid is False
        assert result.status == QuoteValidationStatus.MISMATCH
        assert result.current_quote is valid_quote
        assert result.suggested_quote_id == valid_quote.quote_id

    def test_already_used_factory(self) -> None:
        """Test QuoteValidationResult.already_used() factory method."""
        result = QuoteValidationResult.already_used("quote_used123")

        assert result.is_valid is False
        assert result.status == QuoteValidationStatus.ALREADY_USED
        assert "quote_used123" in result.reason

    def test_to_dict(self, valid_quote: BookingQuote) -> None:
        """Test QuoteValidationResult.to_dict() method."""
        result = QuoteValidationResult.mismatch(valid_quote)
        result_dict = result.to_dict()

        assert result_dict["is_valid"] is False
        assert result_dict["status"] == "mismatch"
        assert "reason" in result_dict
        assert "current_quote" in result_dict
        assert result_dict["suggested_quote_id"] == valid_quote.quote_id

    def test_to_dict_minimal(self) -> None:
        """Test to_dict with minimal result (no current_quote)."""
        result = QuoteValidationResult.valid()
        result_dict = result.to_dict()

        assert result_dict["is_valid"] is True
        assert result_dict["status"] == "valid"
        assert "current_quote" not in result_dict
        assert "suggested_quote_id" not in result_dict


class TestIsQuoteExpired:
    """Tests for is_quote_expired function."""

    def test_valid_quote_not_expired(self, valid_quote: BookingQuote) -> None:
        """Test that a valid quote is not marked as expired."""
        assert is_quote_expired(valid_quote) is False

    def test_expired_quote_is_expired(self, expired_quote: BookingQuote) -> None:
        """Test that an expired quote is marked as expired."""
        assert is_quote_expired(expired_quote) is True

    def test_quote_exactly_at_expiry_is_expired(self) -> None:
        """Test that a quote exactly at expiry time is expired."""
        quote = BookingQuote(
            quote_id="quote_edge",
            booking_id="book_12345678901234567890123456789012",
            quoted_price=100.00,
            currency="USD",
            expires_at=datetime.now(timezone.utc),  # Exactly now
            terms_hash="hash",
            terms_summary="Test",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        assert is_quote_expired(quote) is True


class TestIsQuoteValidForBooking:
    """Tests for is_quote_valid_for_booking convenience function."""

    def test_valid_quote_returns_true(self, sample_booking: Booking) -> None:
        """Test that valid quote returns True."""
        assert is_quote_valid_for_booking(
            sample_booking, sample_booking.current_quote.quote_id
        ) is True

    def test_invalid_quote_returns_false(self, sample_booking: Booking) -> None:
        """Test that invalid quote returns False."""
        assert is_quote_valid_for_booking(sample_booking, "wrong_quote") is False


class TestGetErrorCodeForStatus:
    """Tests for get_error_code_for_status function."""

    def test_valid_status_returns_empty(self) -> None:
        """Test VALID status returns empty string."""
        assert get_error_code_for_status(QuoteValidationStatus.VALID) == ""

    def test_not_found_returns_correct_code(self) -> None:
        """Test NOT_FOUND status returns correct error code."""
        assert get_error_code_for_status(QuoteValidationStatus.NOT_FOUND) == "BOOKING_NO_QUOTE"

    def test_expired_returns_correct_code(self) -> None:
        """Test EXPIRED status returns correct error code."""
        assert get_error_code_for_status(QuoteValidationStatus.EXPIRED) == "BOOKING_QUOTE_EXPIRED"

    def test_mismatch_returns_correct_code(self) -> None:
        """Test MISMATCH status returns correct error code."""
        assert get_error_code_for_status(QuoteValidationStatus.MISMATCH) == "BOOKING_QUOTE_MISMATCH"

    def test_already_used_returns_correct_code(self) -> None:
        """Test ALREADY_USED status returns correct error code."""
        assert get_error_code_for_status(QuoteValidationStatus.ALREADY_USED) == "BOOKING_ALREADY_COMPLETED"


class TestQuoteValidationStatus:
    """Tests for QuoteValidationStatus enum."""

    def test_status_is_string_enum(self) -> None:
        """Test that status values are strings."""
        assert QuoteValidationStatus.VALID.value == "valid"
        assert QuoteValidationStatus.NOT_FOUND.value == "not_found"
        assert QuoteValidationStatus.EXPIRED.value == "expired"
        assert QuoteValidationStatus.MISMATCH.value == "mismatch"
        assert QuoteValidationStatus.ALREADY_USED.value == "already_used"

    def test_all_statuses_defined(self) -> None:
        """Test that all expected statuses are defined."""
        expected = {"VALID", "NOT_FOUND", "EXPIRED", "MISMATCH", "ALREADY_USED"}
        actual = {status.name for status in QuoteValidationStatus}
        assert actual == expected


class TestValidationOrder:
    """Tests to verify validation checks are performed in correct order."""

    def test_not_found_checked_before_mismatch(self, sample_booking: Booking) -> None:
        """Test that NOT_FOUND is returned before MISMATCH when quote is None."""
        sample_booking.current_quote = None

        result = validate_quote(sample_booking, "any_quote")

        # Should get NOT_FOUND, not MISMATCH
        assert result.status == QuoteValidationStatus.NOT_FOUND

    def test_mismatch_checked_before_expiry(
        self, sample_booking: Booking, expired_quote: BookingQuote
    ) -> None:
        """Test that MISMATCH is returned before EXPIRED when quote IDs don't match."""
        sample_booking.current_quote = expired_quote

        result = validate_quote(sample_booking, "different_quote_id")

        # Should get MISMATCH, not EXPIRED
        assert result.status == QuoteValidationStatus.MISMATCH

    def test_expiry_checked_before_used(
        self, sample_booking: Booking, expired_quote: BookingQuote
    ) -> None:
        """Test that EXPIRED is returned before ALREADY_USED when quote is expired."""
        sample_booking.current_quote = expired_quote
        sample_booking.confirmed_quote_id = expired_quote.quote_id

        result = validate_quote(
            sample_booking,
            expired_quote.quote_id,
            check_used=True
        )

        # Should get EXPIRED, not ALREADY_USED
        assert result.status == QuoteValidationStatus.EXPIRED


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_quote_with_different_booking_id(self, sample_booking: Booking) -> None:
        """Test validation when quote has different booking_id (should still work)."""
        # This shouldn't happen in practice, but validator doesn't check booking_id match
        mismatched_quote = BookingQuote(
            quote_id="quote_mismatch",
            booking_id="book_different",  # Different booking ID
            quoted_price=450.00,
            currency="USD",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
            terms_hash="hash",
            terms_summary="Test",
            created_at=datetime.now(timezone.utc),
        )
        sample_booking.current_quote = mismatched_quote

        result = validate_quote(sample_booking, "quote_mismatch")

        # Validator only checks quote_id match, not booking_id
        assert result.is_valid is True

    def test_empty_quote_id_treated_as_mismatch(self, sample_booking: Booking) -> None:
        """Test that empty string quote_id is treated as mismatch."""
        result = validate_quote(sample_booking, "")

        assert result.is_valid is False
        assert result.status == QuoteValidationStatus.MISMATCH

    def test_confirmed_quote_different_from_provided(self, sample_booking: Booking) -> None:
        """Test when confirmed_quote_id exists but is different from provided quote_id."""
        sample_booking.confirmed_quote_id = "quote_old"

        # Providing the current quote (not the confirmed one)
        result = validate_quote(
            sample_booking,
            sample_booking.current_quote.quote_id,
            check_used=True
        )

        # Should detect mismatch because a different quote was already used
        assert result.is_valid is False
        assert result.status == QuoteValidationStatus.MISMATCH
