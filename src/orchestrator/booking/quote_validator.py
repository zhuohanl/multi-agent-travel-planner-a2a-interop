"""
Quote validation for booking safety.

This module provides quote validation to ensure users can only book with valid,
unexpired quotes. It prevents price changes between discovery and booking from
causing surprises.

Per design doc (Booking Safety section):
- Quote validation ensures user agreed to exact price/terms
- Non-existent quotes are rejected
- Expired quotes are rejected (user must confirm new price)
- Already-used quotes are rejected
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.orchestrator.models.booking import Booking, BookingQuote


class QuoteValidationStatus(str, Enum):
    """Status of quote validation."""

    VALID = "valid"
    NOT_FOUND = "not_found"  # Quote doesn't exist
    EXPIRED = "expired"  # Quote past its expiry time
    MISMATCH = "mismatch"  # Quote ID doesn't match current quote
    ALREADY_USED = "already_used"  # Quote was already used for a booking


@dataclass
class QuoteValidationResult:
    """
    Result of quote validation.

    Attributes:
        is_valid: True if quote is valid and can be used
        status: Detailed status of validation
        reason: Human-readable description of validation result
        current_quote: The booking's current quote (for mismatch handling)
        suggested_quote_id: Quote ID to use for retry if validation failed
    """

    is_valid: bool
    status: QuoteValidationStatus
    reason: str
    current_quote: BookingQuote | None = None
    suggested_quote_id: str | None = None

    @classmethod
    def valid(cls) -> QuoteValidationResult:
        """Create a valid result."""
        return cls(
            is_valid=True,
            status=QuoteValidationStatus.VALID,
            reason="Quote is valid"
        )

    @classmethod
    def not_found(cls) -> QuoteValidationResult:
        """Create a not found result (no quote exists)."""
        return cls(
            is_valid=False,
            status=QuoteValidationStatus.NOT_FOUND,
            reason="No active quote. Please refresh booking options."
        )

    @classmethod
    def expired(
        cls,
        current_quote: BookingQuote | None = None
    ) -> QuoteValidationResult:
        """Create an expired result."""
        return cls(
            is_valid=False,
            status=QuoteValidationStatus.EXPIRED,
            reason="Quote has expired. Please confirm the current price.",
            current_quote=current_quote,
            suggested_quote_id=current_quote.quote_id if current_quote else None
        )

    @classmethod
    def mismatch(
        cls,
        current_quote: BookingQuote
    ) -> QuoteValidationResult:
        """Create a mismatch result (quote ID doesn't match)."""
        return cls(
            is_valid=False,
            status=QuoteValidationStatus.MISMATCH,
            reason="Quote has changed. Please review the updated price.",
            current_quote=current_quote,
            suggested_quote_id=current_quote.quote_id
        )

    @classmethod
    def already_used(
        cls,
        confirmed_quote_id: str
    ) -> QuoteValidationResult:
        """Create an already used result."""
        return cls(
            is_valid=False,
            status=QuoteValidationStatus.ALREADY_USED,
            reason=f"Quote was already used for this booking (confirmed quote: {confirmed_quote_id})"
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for response."""
        result = {
            "is_valid": self.is_valid,
            "status": self.status.value,
            "reason": self.reason
        }
        if self.current_quote is not None:
            result["current_quote"] = self.current_quote.to_dict()
        if self.suggested_quote_id is not None:
            result["suggested_quote_id"] = self.suggested_quote_id
        return result


def validate_quote(
    booking: Booking,
    quote_id: str,
    check_used: bool = True
) -> QuoteValidationResult:
    """
    Validate a quote for booking.

    Per design doc (Quote Validation section):
    1. Check quote exists
    2. Check quote ID matches
    3. Check quote hasn't expired
    4. Check quote hasn't been used (if check_used=True)

    Args:
        booking: The booking containing the quote to validate
        quote_id: The quote ID provided by the user
        check_used: If True, check if quote was already used (default True)

    Returns:
        QuoteValidationResult with validation outcome

    Example:
        >>> result = validate_quote(booking, "quote_abc123")
        >>> if result.is_valid:
        ...     proceed_with_booking()
        ... else:
        ...     return error_response(result.reason)
    """
    # Check 1: Quote exists
    if booking.current_quote is None:
        return QuoteValidationResult.not_found()

    # Check 2: Quote ID matches (protects against stale quotes)
    if booking.current_quote.quote_id != quote_id:
        return QuoteValidationResult.mismatch(booking.current_quote)

    # Check 3: Quote hasn't expired
    if booking.current_quote.is_expired():
        return QuoteValidationResult.expired(booking.current_quote)

    # Check 4: Quote hasn't been used (for idempotency)
    if check_used and booking.confirmed_quote_id is not None:
        if booking.confirmed_quote_id == quote_id:
            # Same quote used - this is idempotent, handle at call site
            return QuoteValidationResult.already_used(booking.confirmed_quote_id)
        # Different quote was used previously - quote mismatch
        return QuoteValidationResult.mismatch(booking.current_quote)

    return QuoteValidationResult.valid()


def is_quote_expired(quote: BookingQuote) -> bool:
    """
    Check if a quote has expired.

    Args:
        quote: The quote to check

    Returns:
        True if quote is expired, False otherwise
    """
    now = datetime.now(timezone.utc)
    return quote.expires_at <= now


def is_quote_valid_for_booking(
    booking: Booking,
    quote_id: str
) -> bool:
    """
    Quick check if a quote is valid for booking.

    This is a convenience function that returns a simple boolean.
    For detailed validation info, use validate_quote() instead.

    Args:
        booking: The booking to check
        quote_id: The quote ID to validate

    Returns:
        True if quote is valid, False otherwise
    """
    result = validate_quote(booking, quote_id)
    return result.is_valid


def get_error_code_for_status(status: QuoteValidationStatus) -> str:
    """
    Get the appropriate error code for a quote validation status.

    Args:
        status: The validation status

    Returns:
        Error code string for the status
    """
    status_to_error: dict[QuoteValidationStatus, str] = {
        QuoteValidationStatus.VALID: "",
        QuoteValidationStatus.NOT_FOUND: "BOOKING_NO_QUOTE",
        QuoteValidationStatus.EXPIRED: "BOOKING_QUOTE_EXPIRED",
        QuoteValidationStatus.MISMATCH: "BOOKING_QUOTE_MISMATCH",
        QuoteValidationStatus.ALREADY_USED: "BOOKING_ALREADY_COMPLETED",
    }
    return status_to_error.get(status, "BOOKING_VALIDATION_ERROR")
