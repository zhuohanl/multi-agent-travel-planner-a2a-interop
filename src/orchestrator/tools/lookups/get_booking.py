"""
Get booking lookup tool.

This module provides the get_booking tool for retrieving booking details
by booking ID. It is a stateless lookup tool that doesn't mutate workflow state.

Per design doc (Tool 6: get_booking):
- Parameters: booking_id (required)
- Returns: Booking details including status, items, confirmation numbers
- Works after WorkflowState TTL expires (booking data has longer TTL)

Invocation paths:
1. Layer 1b regex: "show booking book_xxx" -> get_booking(booking_id)
2. Layer 1c LLM fallback: "what's the status of my hotel booking" -> LLM decides
"""

from dataclasses import dataclass
from typing import Any

from src.orchestrator.auth import (
    AuthenticatedUser,
    authorize_booking_read,
)
from src.orchestrator.models.booking import Booking, BookingStatus
from src.orchestrator.storage.booking_store import BookingStoreProtocol


# =============================================================================
# EXCEPTIONS
# =============================================================================


class BookingNotFoundError(ValueError):
    """Raised when a booking ID is not found in the store."""

    def __init__(self, booking_id: str, message: str | None = None) -> None:
        self.booking_id = booking_id
        self.message = message or f"Booking not found: {booking_id}"
        super().__init__(self.message)


# =============================================================================
# FORMATTING
# =============================================================================


def format_booking_status(status: BookingStatus) -> str:
    """Format booking status with description.

    Args:
        status: The booking status enum

    Returns:
        Human-readable status string
    """
    status_descriptions = {
        BookingStatus.UNBOOKED: "Not yet booked",
        BookingStatus.PENDING: "Booking in progress",
        BookingStatus.BOOKED: "Confirmed",
        BookingStatus.FAILED: "Booking failed",
        BookingStatus.UNKNOWN: "Status uncertain - verification needed",
        BookingStatus.CANCELLED: "Cancelled",
    }
    return status_descriptions.get(status, status.value.title())


def format_item_type(item_type: str) -> str:
    """Format item type for display.

    Args:
        item_type: The item type (flight, hotel, activity, transport)

    Returns:
        Formatted item type string
    """
    return item_type.title()


def format_price(price: float, currency: str = "USD") -> str:
    """Format price with currency.

    Args:
        price: The price amount
        currency: Currency code (default: USD)

    Returns:
        Formatted price string
    """
    # Use appropriate decimal places based on currency
    if currency in ("JPY", "KRW", "VND", "IDR"):
        return f"{price:,.0f} {currency}"
    return f"{price:,.2f} {currency}"


def format_booking_details(booking: Booking) -> str:
    """Format booking details for display.

    Produces a human-readable summary of the booking including:
    - Item type and details
    - Current status
    - Price and quote information
    - Confirmation reference (if booked)
    - Cancellation policy summary

    Args:
        booking: The booking to format

    Returns:
        Formatted booking details string
    """
    lines: list[str] = []

    # Header
    lines.append(f"Booking: {booking.booking_id}")
    lines.append(f"Type: {format_item_type(booking.item_type)}")
    lines.append(f"Status: {format_booking_status(booking.status)}")

    # Item details (extract key info from details dict)
    if booking.details:
        if "name" in booking.details:
            lines.append(f"Name: {booking.details['name']}")
        if "description" in booking.details:
            lines.append(f"Description: {booking.details['description']}")
        if "location" in booking.details:
            lines.append(f"Location: {booking.details['location']}")
        if "date" in booking.details:
            lines.append(f"Date: {booking.details['date']}")
        if "check_in" in booking.details:
            lines.append(f"Check-in: {booking.details['check_in']}")
        if "check_out" in booking.details:
            lines.append(f"Check-out: {booking.details['check_out']}")
        if "departure" in booking.details:
            lines.append(f"Departure: {booking.details['departure']}")
        if "arrival" in booking.details:
            lines.append(f"Arrival: {booking.details['arrival']}")

    # Price
    currency = "USD"
    if booking.current_quote:
        currency = booking.current_quote.currency
    lines.append(f"Price: {format_price(booking.price, currency)}")

    # Quote status
    if booking.current_quote:
        if booking.current_quote.is_expired():
            lines.append("Quote: Expired - new quote needed for booking")
        else:
            remaining = booking.current_quote.time_remaining()
            minutes = int(remaining.total_seconds() / 60)
            lines.append(f"Quote: Valid for {minutes} minutes")
            lines.append(f"Quote ID: {booking.current_quote.quote_id}")

    # Booking confirmation
    if booking.booking_reference:
        lines.append(f"Confirmation: {booking.booking_reference}")

    # Failure reason (if applicable)
    if booking.status == BookingStatus.FAILED and booking.failure_reason:
        lines.append(f"Failure reason: {booking.failure_reason}")

    # Status reason (if applicable)
    if booking.status_reason:
        lines.append(f"Note: {booking.status_reason}")

    # Cancellation policy summary
    if booking.cancellation_policy:
        policy = booking.cancellation_policy
        if not policy.is_cancellable:
            lines.append("Cancellation: Non-refundable")
        elif policy.is_in_free_period():
            lines.append("Cancellation: Free cancellation available")
        elif policy.free_cancellation_until:
            lines.append("Cancellation: Fee applies")
        if policy.notes:
            lines.append(f"Policy: {policy.notes}")

    # Cancellation info (if cancelled)
    if booking.cancelled_at:
        lines.append(f"Cancelled at: {booking.cancelled_at.isoformat()}")
    if booking.cancellation_reference:
        lines.append(f"Cancellation ref: {booking.cancellation_reference}")
    if booking.refund_amount is not None:
        lines.append(f"Refund: {format_price(booking.refund_amount, currency)}")

    return "\n".join(lines)


# =============================================================================
# LOOKUP RESULT
# =============================================================================


@dataclass
class GetBookingResult:
    """Result of get_booking lookup.

    Attributes:
        success: Whether the lookup succeeded
        message: Human-readable message
        booking: The booking data (if found)
        formatted: Formatted booking details string
        data: Raw booking data dict (for API responses)
    """

    success: bool
    message: str
    booking: Booking | None = None
    formatted: str | None = None
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for API responses."""
        result: dict[str, Any] = {
            "success": self.success,
            "message": self.message,
        }
        if self.formatted:
            result["formatted"] = self.formatted
        if self.data:
            result["data"] = self.data
        return result


# =============================================================================
# MAIN LOOKUP FUNCTION
# =============================================================================


async def get_booking(
    booking_id: str,
    booking_store: BookingStoreProtocol,
) -> GetBookingResult:
    """
    Retrieve booking details by booking ID.

    This is a stateless lookup tool (Tool 6 in design doc) that returns
    booking information without modifying any state.

    Per design doc:
    - Retrieves booking details by booking_id
    - Returns status, items, confirmation numbers
    - Works after WorkflowState TTL expires (booking TTL is trip_end + 30 days)
    - Pattern: "show booking book_xxx" (Layer 1b regex)

    Args:
        booking_id: The booking identifier (e.g., "book_abc123")
        booking_store: The booking store to query

    Returns:
        GetBookingResult with booking details

    Example:
        >>> result = await get_booking("book_abc123", store)
        >>> if result.success:
        ...     print(result.formatted)
        Booking: book_abc123
        Type: Hotel
        Status: Confirmed
        ...
    """
    # Validate booking_id format (should start with "book_")
    if not booking_id:
        return GetBookingResult(
            success=False,
            message="Booking ID is required",
        )

    if not booking_id.startswith("book_"):
        return GetBookingResult(
            success=False,
            message=f"Invalid booking ID format: {booking_id}. Expected format: book_<id>",
        )

    # Look up booking from store
    booking = await booking_store.get_booking(booking_id)

    if booking is None:
        return GetBookingResult(
            success=False,
            message=f"Booking not found: {booking_id}",
        )

    # Authorization check (MVP mode allows all when user=None)
    # Per design doc Authorization Model section:
    # - MVP mode: No auth required, IDs as bearer tokens
    # - Production mode: Would pass AuthenticatedUser from OAuth/Azure AD
    user: AuthenticatedUser | None = None  # MVP mode: no auth required
    auth_result = authorize_booking_read(booking, user)
    if not auth_result.allowed:
        return GetBookingResult(
            success=False,
            message="You don't have permission to view this booking.",
        )

    # Format booking details
    formatted = format_booking_details(booking)

    # Prepare data dict (exclude sensitive info like etag)
    data = {
        "booking_id": booking.booking_id,
        "itinerary_id": booking.itinerary_id,
        "item_type": booking.item_type,
        "status": booking.status.value,
        "price": booking.price,
        "details": booking.details,
    }

    if booking.booking_reference:
        data["booking_reference"] = booking.booking_reference
    if booking.current_quote:
        data["quote"] = {
            "quote_id": booking.current_quote.quote_id,
            "quoted_price": booking.current_quote.quoted_price,
            "currency": booking.current_quote.currency,
            "expires_at": booking.current_quote.expires_at.isoformat(),
            "is_expired": booking.current_quote.is_expired(),
        }
    if booking.cancellation_policy:
        data["cancellation_policy"] = booking.cancellation_policy.to_dict()

    return GetBookingResult(
        success=True,
        message=f"Found booking: {booking_id}",
        booking=booking,
        formatted=formatted,
        data=data,
    )
