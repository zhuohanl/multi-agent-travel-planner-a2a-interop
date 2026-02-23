"""
BookingService for handling workflow_turn booking actions.

This module encapsulates booking actions invoked via workflow_turn events.
It provides a single integration point for booking safety logic, keeping
BookingHandler thin.

Per design doc Booking Safety section:
- Each bookable item is booked independently (no cart)
- Requires server-generated booking_id and user-confirmed quote_id
- Status tracking prevents double-booking

Key methods:
- view_booking_options(): Returns bookable items with current quotes
- book_item(): Executes booking with quote validation
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from src.orchestrator.models.booking import (
    Booking,
    BookingItemStatus,
    BookingQuote,
    BookingStatus,
    BookingSummary,
)
from src.orchestrator.booking.quote_validator import (
    QuoteValidationResult,
    QuoteValidationStatus,
    get_error_code_for_status,
    validate_quote,
)
from src.orchestrator.models.responses import ToolResponse, UIAction, UIDirective
from src.orchestrator.utils.id_generator import generate_quote_id

if TYPE_CHECKING:
    from src.orchestrator.storage.booking_store import BookingStoreProtocol
    from src.orchestrator.storage.itinerary_store import ItineraryStoreProtocol

logger = logging.getLogger(__name__)

# Default quote validity period: 15 minutes
QUOTE_VALIDITY_MINUTES = 15


def _error_response(
    message: str,
    error_code: str | None = None,
    ui: UIDirective | None = None,
    data: dict[str, Any] | None = None,
) -> ToolResponse:
    """Create an error ToolResponse aligned with Response Formats."""
    response_data = data.copy() if data else {}
    if error_code:
        response_data["error_code"] = error_code
    return ToolResponse(
        success=False,
        message=message,
        data=response_data if response_data else None,
        ui=ui,
    )


class BookingService:
    """
    Service for handling booking operations in workflow_turn.

    This class encapsulates all booking-related business logic,
    providing a clean interface for the workflow handler.

    Per design doc:
    - Each booking is independent (no cart to confirm)
    - Users may interleave questions between bookings
    - Quote validation ensures user agreed to exact price/terms
    """

    def __init__(
        self,
        booking_store: BookingStoreProtocol,
        itinerary_store: ItineraryStoreProtocol,
    ) -> None:
        """
        Initialize BookingService with required stores.

        Args:
            booking_store: Store for booking data
            itinerary_store: Store for itinerary data
        """
        self._booking_store = booking_store
        self._itinerary_store = itinerary_store

    async def get_booking_summary(
        self,
        itinerary_id: str,
    ) -> BookingSummary | None:
        """
        Get current booking status for all items in an itinerary.

        Per design doc get_booking_summary (Booking Safety section):
        Returns a summary of booking statuses for the itinerary, used by
        the GET_STATUS action in the BOOKING phase.

        Args:
            itinerary_id: The itinerary to get booking summary for

        Returns:
            BookingSummary with all booking statuses, or None if itinerary not found
        """
        logger.debug(f"get_booking_summary called: itinerary_id={itinerary_id}")

        # Load the itinerary
        itinerary = await self._itinerary_store.get_itinerary(itinerary_id)
        if itinerary is None:
            logger.warning(f"Itinerary not found: {itinerary_id}")
            return None

        if not itinerary.booking_ids:
            # No bookings - return empty summary
            return BookingSummary(
                itinerary_id=itinerary_id,
                items=[],
                booked_count=0,
                unbooked_count=0,
                failed_count=0,
                pending_count=0,
                unknown_count=0,
                cancelled_count=0,
            )

        # Load all bookings
        bookings = await self._booking_store.get_bookings_by_ids(itinerary.booking_ids)

        # Build item status list
        items: list[BookingItemStatus] = []
        status_counts: dict[BookingStatus, int] = {status: 0 for status in BookingStatus}

        for booking in bookings:
            # Count statuses
            status_counts[booking.status] += 1

            # Build item status
            item = BookingItemStatus(
                booking_id=booking.booking_id,
                item_type=booking.item_type.value if hasattr(booking.item_type, 'value') else str(booking.item_type),
                name=booking.details.get("name"),
                status=booking.status,
                booking_reference=booking.booking_reference,
                can_cancel=(
                    booking.cancellation_policy.is_cancellable
                    if booking.status == BookingStatus.BOOKED
                    else None
                ),
                can_retry=booking.status == BookingStatus.FAILED,
            )
            items.append(item)

        return BookingSummary(
            itinerary_id=itinerary_id,
            items=items,
            booked_count=status_counts[BookingStatus.BOOKED],
            unbooked_count=status_counts[BookingStatus.UNBOOKED],
            failed_count=status_counts[BookingStatus.FAILED],
            pending_count=status_counts[BookingStatus.PENDING],
            unknown_count=status_counts[BookingStatus.UNKNOWN],
            cancelled_count=status_counts[BookingStatus.CANCELLED],
        )

    async def view_booking_options(
        self,
        itinerary_id: str | None = None,
        booking_id: str | None = None,
    ) -> ToolResponse:
        """
        View bookable items with current quotes.

        Per design doc (Navigation vs Action Events):
        - No payload: returns all bookable items for the itinerary
        - Optional booking_id: returns single item quote card (for drill-down)

        Args:
            itinerary_id: Optional itinerary to view options for
            booking_id: Optional specific booking to view

        Returns:
            ToolResponse with booking options and quotes
        """
        logger.debug(
            f"view_booking_options called: itinerary_id={itinerary_id}, "
            f"booking_id={booking_id}"
        )

        # Case 1: Single booking drill-down
        if booking_id:
            return await self._view_single_booking(booking_id)

        # Case 2: View all bookings for itinerary
        if itinerary_id:
            return await self._view_itinerary_bookings(itinerary_id)

        # No identifier provided
        return _error_response(
            message="Please provide an itinerary_id or booking_id to view booking options.",
            error_code="BOOKING_MISSING_IDENTIFIER",
        )

    async def _view_single_booking(self, booking_id: str) -> ToolResponse:
        """
        View a single booking with its current quote.

        Args:
            booking_id: The booking to view

        Returns:
            ToolResponse with booking details and quote
        """
        booking = await self._booking_store.get_booking(booking_id)

        if booking is None:
            return _error_response(
                message=f"Booking not found: {booking_id}",
                error_code="BOOKING_NOT_FOUND",
            )

        # Generate fresh quote if needed
        booking_with_quote = await self._ensure_valid_quote(booking)

        return ToolResponse(
            success=True,
            message=f"Viewing {booking_with_quote.item_type} booking",
            data={
                "booking": self._booking_to_view_dict(booking_with_quote),
            },
            ui=self._build_booking_ui(booking_with_quote),
        )

    async def _view_itinerary_bookings(self, itinerary_id: str) -> ToolResponse:
        """
        View all bookings for an itinerary.

        Args:
            itinerary_id: The itinerary to view bookings for

        Returns:
            ToolResponse with all booking details and quotes
        """
        # Load the itinerary to get booking IDs
        itinerary = await self._itinerary_store.get_itinerary(itinerary_id)

        if itinerary is None:
            return _error_response(
                message=f"Itinerary not found: {itinerary_id}",
                error_code="ITINERARY_NOT_FOUND",
            )

        if not itinerary.booking_ids:
            return ToolResponse(
                success=True,
                message="No bookable items in this itinerary",
                data={"bookings": []},
            )

        # Load all bookings
        bookings = await self._booking_store.get_bookings_by_ids(itinerary.booking_ids)

        # Ensure valid quotes for all bookings
        bookings_with_quotes = []
        for booking in bookings:
            booking_with_quote = await self._ensure_valid_quote(booking)
            bookings_with_quotes.append(booking_with_quote)

        # Build response
        booking_dicts = [
            self._booking_to_view_dict(b) for b in bookings_with_quotes
        ]

        # Categorize by status
        unbooked = [b for b in bookings_with_quotes if b.status == BookingStatus.UNBOOKED]
        booked = [b for b in bookings_with_quotes if b.status == BookingStatus.BOOKED]
        pending = [b for b in bookings_with_quotes if b.status == BookingStatus.PENDING]
        failed = [b for b in bookings_with_quotes if b.status == BookingStatus.FAILED]

        summary = (
            f"{len(unbooked)} available to book, "
            f"{len(booked)} booked, "
            f"{len(pending)} pending"
        )
        if failed:
            summary += f", {len(failed)} failed"

        return ToolResponse(
            success=True,
            message=summary,
            data={
                "bookings": booking_dicts,
                "itinerary_id": itinerary_id,
            },
            ui=self._build_bookings_list_ui(bookings_with_quotes),
        )

    async def book_item(
        self,
        booking_id: str,
        quote_id: str,
    ) -> ToolResponse:
        """
        Book a single item with quote validation.

        Per design doc (Server-Side Implementation):
        - Idempotent - safe to call multiple times with same quote_id
        - Quote validation ensures user agreed to exact price/terms

        This is a skeleton implementation that validates the quote and
        status but does NOT actually call the provider. Full provider
        integration will be added in Phase 3.

        Args:
            booking_id: The booking to execute
            quote_id: Server-issued quote ID confirming user saw exact price/terms

        Returns:
            ToolResponse with booking result
        """
        logger.info(f"book_item called: booking_id={booking_id}, quote_id={quote_id}")

        # Load the booking
        booking = await self._booking_store.get_booking(booking_id)

        if booking is None:
            return _error_response(
                message=f"Booking not found: {booking_id}",
                error_code="BOOKING_NOT_FOUND",
            )

        # ═══════════════════════════════════════════════════════════════════
        # STATUS GUARDS - Check booking status before proceeding
        # ═══════════════════════════════════════════════════════════════════

        # UNKNOWN STATUS GUARD - Block new attempts until reconciliation
        if booking.status == BookingStatus.UNKNOWN:
            return _error_response(
                message="Previous booking attempt is still being verified. Please check status first.",
                error_code="BOOKING_PENDING_RECONCILIATION",
                data={
                    "booking_id": booking_id,
                    "provider_request_id": booking.provider_request_id,
                    "reason": booking.status_reason,
                },
                ui=UIDirective(
                    actions=[
                        UIAction(
                            label=self._format_action_label("Check Status", booking),
                            event={
                                "type": "check_booking_status",
                                "booking": {"booking_id": booking_id},
                            },
                        ),
                        UIAction(
                            label=self._format_action_label("Cancel & Retry", booking),
                            event={
                                "type": "cancel_unknown_booking",
                                "booking": {"booking_id": booking_id},
                            },
                        ),
                    ],
                    display_type="booking_options",
                ),
            )

        # PENDING STATUS GUARD - Booking already in progress
        if booking.status == BookingStatus.PENDING:
            return _error_response(
                message="Booking is already in progress. Please wait.",
                error_code="BOOKING_IN_PROGRESS",
                ui=UIDirective(
                    actions=[
                        UIAction(
                            label=self._format_action_label("Check Status", booking),
                            event={
                                "type": "check_booking_status",
                                "booking": {"booking_id": booking_id},
                            },
                        ),
                    ],
                    display_type="booking_options",
                ),
            )

        # ALREADY BOOKED - Idempotent check
        if booking.status == BookingStatus.BOOKED:
            if booking.confirmed_quote_id == quote_id:
                return ToolResponse(
                    success=True,
                    message="Already booked!",
                    data={
                        "booking_id": booking_id,
                        "booking_reference": booking.booking_reference,
                        "status": booking.status.value,
                    },
                )
            # Different quote_id for already-booked item
            return _error_response(
                message="Booking already completed with different quote",
                error_code="BOOKING_ALREADY_COMPLETED",
            )

        # CANCELLED - Cannot book
        if booking.status == BookingStatus.CANCELLED:
            return _error_response(
                message="This booking has been cancelled and cannot be booked",
                error_code="BOOKING_CANCELLED",
            )

        # ═══════════════════════════════════════════════════════════════════
        # QUOTE VALIDATION - Critical for booking safety
        # Uses quote_validator module for centralized validation logic
        # ═══════════════════════════════════════════════════════════════════

        validation_result = validate_quote(booking, quote_id, check_used=False)
        if not validation_result.is_valid:
            return await self._handle_quote_validation_failure(
                booking, booking_id, quote_id, validation_result, event_type="book_item"
            )

        # ═══════════════════════════════════════════════════════════════════
        # QUOTE VALID - Skeleton: Mark as booked without provider call
        # Full provider integration will be added in Phase 3
        # ═══════════════════════════════════════════════════════════════════

        # Generate provider request ID for idempotency
        provider_request_id = booking.generate_provider_request_id(quote_id)
        booking.provider_request_id = provider_request_id

        # For skeleton: immediately mark as booked
        # In Phase 3, this will be PENDING -> provider call -> BOOKED/FAILED/UNKNOWN
        booking.status = BookingStatus.BOOKED
        booking.confirmed_quote_id = quote_id
        booking.booking_reference = f"REF-{booking_id[-8:].upper()}"  # Placeholder reference
        booking.updated_at = datetime.now(timezone.utc)

        await self._booking_store.save_booking(booking)

        logger.info(
            f"Booking completed (skeleton): booking_id={booking_id}, "
            f"reference={booking.booking_reference}"
        )

        return ToolResponse(
            success=True,
            message=f"Booked! Confirmation: {booking.booking_reference}",
            data={
                "booking_id": booking_id,
                "booking_reference": booking.booking_reference,
                "confirmed_price": booking.current_quote.quoted_price,
                "confirmed_terms": booking.current_quote.terms_summary,
            },
        )

    async def _ensure_valid_quote(self, booking: Booking) -> Booking:
        """
        Ensure booking has a valid (non-expired) quote.

        Generates a new quote if needed and saves the booking.

        Args:
            booking: The booking to check

        Returns:
            Booking with valid quote
        """
        if booking.current_quote is None or booking.current_quote.is_expired():
            booking.current_quote = self._generate_quote(booking)
            await self._booking_store.save_booking(booking)
        return booking

    def _generate_quote(self, booking: Booking) -> BookingQuote:
        """
        Generate a fresh quote for a booking.

        Args:
            booking: The booking to generate a quote for

        Returns:
            New BookingQuote with current price/terms
        """
        now = datetime.now(timezone.utc)
        return BookingQuote(
            quote_id=generate_quote_id(),
            booking_id=booking.booking_id,
            quoted_price=booking.price,
            currency=booking.details.get("currency", "USD"),
            expires_at=now + timedelta(minutes=QUOTE_VALIDITY_MINUTES),
            terms_hash=booking.cancellation_policy.compute_hash(),
            terms_summary=self._format_terms_summary(booking.cancellation_policy),
            created_at=now,
        )

    def _format_terms_summary(self, policy: Any) -> str:
        """
        Format cancellation policy as human-readable summary.

        Args:
            policy: CancellationPolicy to format

        Returns:
            Human-readable terms summary
        """
        if not policy.is_cancellable:
            return "Non-refundable"

        if policy.free_cancellation_until:
            free_until = policy.free_cancellation_until
            if hasattr(free_until, "strftime"):
                date_str = free_until.strftime("%b %d, %Y")
            else:
                date_str = str(free_until)
            return f"Free cancellation until {date_str}"

        if policy.fee_percentage > 0:
            return f"Cancellation fee: {int(policy.fee_percentage * 100)}%"

        if policy.fee_fixed > 0:
            return f"Cancellation fee: ${policy.fee_fixed:.2f}"

        return "Cancellable"

    async def _handle_quote_validation_failure(
        self,
        booking: Booking,
        booking_id: str,
        quote_id: str,
        validation_result: QuoteValidationResult,
        event_type: str = "book_item",
    ) -> ToolResponse:
        """
        Handle quote validation failure by generating appropriate response.

        This method converts QuoteValidationResult failures into ToolResponse
        with appropriate error codes, messages, and UI actions.

        Args:
            booking: The booking being validated
            booking_id: ID of the booking
            quote_id: The quote ID that failed validation
            validation_result: The validation result from validate_quote()
            event_type: Event type for retry action (book_item or retry_booking)

        Returns:
            ToolResponse with error information and retry action
        """
        error_code = get_error_code_for_status(validation_result.status)

        match validation_result.status:
            case QuoteValidationStatus.NOT_FOUND:
                # Generate fresh quote
                new_quote = self._generate_quote(booking)
                booking.current_quote = new_quote
                await self._booking_store.save_booking(booking)

                return _error_response(
                    message=validation_result.reason,
                    error_code=error_code,
                    data={"new_quote": new_quote.to_dict()},
                    ui=UIDirective(
                        actions=[
                            UIAction(
                                label=self._format_action_label(
                                    "Confirm",
                                    booking,
                                    price=new_quote.quoted_price,
                                    currency=new_quote.currency,
                                ),
                                event={
                                    "type": event_type,
                                    "booking": {
                                        "booking_id": booking_id,
                                        "quote_id": new_quote.quote_id,
                                    },
                                },
                            ),
                        ],
                        display_type="booking_options",
                    ),
                )

            case QuoteValidationStatus.MISMATCH:
                # Quote ID doesn't match - user needs to confirm new quote
                return _error_response(
                    message=validation_result.reason,
                    error_code=error_code,
                    data={
                        "new_quote": validation_result.current_quote.to_dict()
                        if validation_result.current_quote
                        else None
                    },
                    ui=UIDirective(
                        actions=[
                            UIAction(
                                label=self._format_action_label(
                                    "Confirm",
                                    booking,
                                    price=validation_result.current_quote.quoted_price
                                    if validation_result.current_quote
                                    else None,
                                    currency=validation_result.current_quote.currency
                                    if validation_result.current_quote
                                    else None,
                                ),
                                event={
                                    "type": event_type,
                                    "booking": {
                                        "booking_id": booking_id,
                                        "quote_id": validation_result.suggested_quote_id,
                                    },
                                },
                            ),
                        ],
                        display_type="booking_options",
                    ),
                )

            case QuoteValidationStatus.EXPIRED:
                # Quote expired - generate fresh quote
                new_quote = self._generate_quote(booking)
                booking.current_quote = new_quote
                await self._booking_store.save_booking(booking)

                return _error_response(
                    message=validation_result.reason,
                    error_code=error_code,
                    data={"new_quote": new_quote.to_dict()},
                    ui=UIDirective(
                        actions=[
                            UIAction(
                                label=self._format_action_label(
                                    "Confirm",
                                    booking,
                                    price=new_quote.quoted_price,
                                    currency=new_quote.currency,
                                ),
                                event={
                                    "type": event_type,
                                    "booking": {
                                        "booking_id": booking_id,
                                        "quote_id": new_quote.quote_id,
                                    },
                                },
                            ),
                        ],
                        display_type="booking_options",
                    ),
                )

            case QuoteValidationStatus.ALREADY_USED:
                # Quote already used - this is a duplicate booking attempt
                return _error_response(
                    message=validation_result.reason,
                    error_code=error_code,
                )

            case _:
                # Unknown status - shouldn't happen, but handle gracefully
                return _error_response(
                    message="Quote validation failed",
                    error_code="BOOKING_VALIDATION_ERROR",
                )

    def _booking_to_view_dict(self, booking: Booking) -> dict[str, Any]:
        """
        Convert booking to dictionary for view response.

        Args:
            booking: The booking to convert

        Returns:
            Dictionary with booking details
        """
        result: dict[str, Any] = {
            "booking_id": booking.booking_id,
            "item_type": booking.item_type,
            "status": booking.status.value,
            "price": booking.price,
            "details": booking.details,
        }

        if booking.current_quote:
            result["quote"] = {
                "quote_id": booking.current_quote.quote_id,
                "quoted_price": booking.current_quote.quoted_price,
                "currency": booking.current_quote.currency,
                "expires_at": booking.current_quote.expires_at.isoformat(),
                "terms_summary": booking.current_quote.terms_summary,
            }

        if booking.booking_reference:
            result["booking_reference"] = booking.booking_reference

        if booking.failure_reason:
            result["failure_reason"] = booking.failure_reason

        return result

    def _detail_str(self, value: Any) -> str | None:
        """Normalize a detail value into a readable string."""
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return str(value)

    def _describe_transport(self, booking: Booking) -> str:
        """Build a short descriptor for transport bookings."""
        details = booking.details or {}
        mode = self._detail_str(details.get("mode"))
        mode_label = (mode or str(booking.item_type or "transport")).title()

        from_loc = self._detail_str(details.get("from") or details.get("origin"))
        to_loc = self._detail_str(details.get("to") or details.get("destination"))
        route = None
        if from_loc and to_loc:
            route = f"{from_loc} -> {to_loc}"
        elif from_loc:
            route = f"from {from_loc}"
        elif to_loc:
            route = f"to {to_loc}"

        carrier = self._detail_str(details.get("carrier"))
        descriptor = mode_label
        if route:
            descriptor = f"{descriptor} {route}"
        if carrier:
            descriptor = f"{descriptor} ({carrier})"
        return descriptor

    def _describe_hotel(self, booking: Booking) -> str:
        """Build a short descriptor for hotel bookings."""
        details = booking.details or {}
        name = self._detail_str(details.get("name"))
        location = self._detail_str(details.get("location"))
        descriptor = "Hotel"
        if name:
            descriptor = f"{descriptor} {name}"
        if location:
            if name:
                descriptor = f"{descriptor} ({location})"
            else:
                descriptor = f"{descriptor} in {location}"
        return descriptor

    def _describe_activity(self, booking: Booking) -> str:
        """Build a short descriptor for activity bookings."""
        details = booking.details or {}
        name = self._detail_str(details.get("name"))
        location = self._detail_str(details.get("location"))
        descriptor = "Activity"
        if name:
            descriptor = f"{descriptor} {name}"
        if location:
            descriptor = f"{descriptor} ({location})"
        return descriptor

    def _describe_booking(self, booking: Booking) -> str:
        """Create a concise, user-facing booking descriptor."""
        details = booking.details or {}
        mode = self._detail_str(details.get("mode"))
        if booking.item_type in {"flight", "transport"} or (
            mode and mode.lower() in {"flight", "train", "bus", "ferry", "shuttle", "taxi", "transfer"}
        ):
            return self._describe_transport(booking)
        if booking.item_type == "hotel":
            return self._describe_hotel(booking)
        if booking.item_type == "activity":
            return self._describe_activity(booking)
        return str(booking.item_type or "item").title()

    def _format_price_label(self, price: float, currency: str | None = None) -> str:
        """Format price for UI labels."""
        if currency and currency.upper() != "USD":
            return f"{price:.2f} {currency.upper()}"
        return f"${price:.2f}"

    def _format_action_label(
        self,
        action: str,
        booking: Booking,
        *,
        price: float | None = None,
        currency: str | None = None,
    ) -> str:
        """Build a descriptive action label for a booking."""
        descriptor = self._describe_booking(booking)
        if price is None:
            return f"{action} {descriptor}".strip()
        price_label = self._format_price_label(price, currency)
        return f"{action} {descriptor} ({price_label})".strip()

    def _build_booking_ui(self, booking: Booking) -> UIDirective | None:
        """
        Build UI actions for a single booking.

        Args:
            booking: The booking to build UI for

        Returns:
            UIDirective with actions, or None if no actions
        """
        actions: list[UIAction] = []

        # Bookable items get a "Book" action
        if booking.status == BookingStatus.UNBOOKED and booking.current_quote:
            actions.append(
                UIAction(
                    label=self._format_action_label(
                        "Book",
                        booking,
                        price=booking.current_quote.quoted_price,
                        currency=booking.current_quote.currency,
                    ),
                    event={
                        "type": "book_item",
                        "booking": {
                            "booking_id": booking.booking_id,
                            "quote_id": booking.current_quote.quote_id,
                        },
                    },
                )
            )

        # Failed items can be retried
        if booking.status == BookingStatus.FAILED and booking.current_quote:
            actions.append(
                UIAction(
                    label=self._format_action_label(
                        "Retry",
                        booking,
                        price=booking.current_quote.quoted_price,
                        currency=booking.current_quote.currency,
                    ),
                    event={
                        "type": "retry_booking",
                        "booking": {
                            "booking_id": booking.booking_id,
                            "quote_id": booking.current_quote.quote_id,
                        },
                    },
                )
            )

        # Booked items can be cancelled (if policy allows)
        if booking.status == BookingStatus.BOOKED and booking.cancellation_policy.is_cancellable:
            actions.append(
                UIAction(
                    label=self._format_action_label("Cancel", booking),
                    event={
                        "type": "cancel_booking",
                        "booking": {"booking_id": booking.booking_id},
                    },
                )
            )

        # Pending/Unknown items need status check
        if booking.status in (BookingStatus.PENDING, BookingStatus.UNKNOWN):
            actions.append(
                UIAction(
                    label=self._format_action_label("Check Status", booking),
                    event={
                        "type": "check_booking_status",
                        "booking": {"booking_id": booking.booking_id},
                    },
                )
            )

        return (
            UIDirective(actions=actions, display_type="booking_options")
            if actions
            else None
        )

    def _build_bookings_list_ui(
        self, bookings: list[Booking]
    ) -> UIDirective | None:
        """
        Build UI for a list of bookings.

        Args:
            bookings: List of bookings to build UI for

        Returns:
            UIDirective with actions, or None if no actions
        """
        actions: list[UIAction] = []

        for booking in bookings:
            booking_ui = self._build_booking_ui(booking)
            if booking_ui and booking_ui.actions:
                actions.extend(booking_ui.actions)

        return (
            UIDirective(actions=actions, display_type="booking_options")
            if actions
            else None
        )

    async def retry_booking(
        self,
        booking_id: str,
        quote_id: str,
    ) -> ToolResponse:
        """
        Retry a failed booking with a fresh quote.

        Per design doc (Booking Safety - Retry Booking Flow):
        - Allowed source status: FAILED only
        - Required payload: booking_id + quote_id (fresh quote)
        - Generates NEW idempotency key (different from failed attempt)
        - State transition: FAILED → PENDING → BOOKED/FAILED/UNKNOWN

        The fresh quote_id ensures the retry is treated as a new provider request,
        avoiding any ambiguity from the previous failed attempt.

        Args:
            booking_id: The booking to retry
            quote_id: Server-issued quote ID (must be fresh, not the failed quote)

        Returns:
            ToolResponse with retry result
        """
        logger.info(f"retry_booking called: booking_id={booking_id}, quote_id={quote_id}")

        # Load the booking
        booking = await self._booking_store.get_booking(booking_id)

        if booking is None:
            return _error_response(
                message=f"Booking not found: {booking_id}",
                error_code="BOOKING_NOT_FOUND",
            )

        # ═══════════════════════════════════════════════════════════════════
        # STATUS GUARD: Only FAILED bookings can be retried
        # ═══════════════════════════════════════════════════════════════════

        if booking.status != BookingStatus.FAILED:
            status_guidance = {
                BookingStatus.UNBOOKED: "Use 'book_item' to book this item.",
                BookingStatus.PENDING: "Booking is already in progress.",
                BookingStatus.BOOKED: "This item is already booked.",
                BookingStatus.UNKNOWN: "Please check status first to resolve the unknown state.",
                BookingStatus.CANCELLED: "This booking was cancelled. Use 'book_item' with a fresh quote.",
            }
            return _error_response(
                message=f"Cannot retry - booking status is {booking.status.value}. "
                        f"{status_guidance.get(booking.status, '')}",
                error_code="INVALID_BOOKING_STATUS",
                data={"current_status": booking.status.value},
            )

        # ═══════════════════════════════════════════════════════════════════
        # QUOTE VALIDATION: Same as book_item
        # ═══════════════════════════════════════════════════════════════════

        validation_result = validate_quote(booking, quote_id, check_used=False)
        if not validation_result.is_valid:
            return await self._handle_quote_validation_failure(
                booking, booking_id, quote_id, validation_result, event_type="retry_booking"
            )

        # ═══════════════════════════════════════════════════════════════════
        # EXECUTE RETRY: New idempotency key for fresh attempt
        # IMPORTANT: Use NEW quote_id in idempotency key to differentiate from
        # the failed attempt. This ensures provider treats it as a new request.
        # ═══════════════════════════════════════════════════════════════════

        # Generate provider request ID for idempotency (new key with fresh quote)
        provider_request_id = booking.generate_provider_request_id(quote_id)
        booking.provider_request_id = provider_request_id

        # Update status to PENDING and clear previous failure
        booking.status = BookingStatus.PENDING
        booking.failure_reason = None  # Clear previous failure
        booking.updated_at = datetime.now(timezone.utc)

        await self._booking_store.save_booking(booking)

        # ═══════════════════════════════════════════════════════════════════
        # SKELETON: Mark as booked without provider call
        # In production, this would call the provider and handle:
        # - Success → BOOKED
        # - Timeout → UNKNOWN (with check_booking_status action)
        # - Error → FAILED (with retry action)
        # ═══════════════════════════════════════════════════════════════════

        # For skeleton: immediately mark as booked
        booking.status = BookingStatus.BOOKED
        booking.confirmed_quote_id = quote_id
        booking.booking_reference = f"REF-{booking_id[-8:].upper()}"  # Placeholder reference
        booking.updated_at = datetime.now(timezone.utc)

        await self._booking_store.save_booking(booking)

        logger.info(
            f"Booking retry completed (skeleton): booking_id={booking_id}, "
            f"reference={booking.booking_reference}"
        )

        return ToolResponse(
            success=True,
            message=f"Booked! Confirmation: {booking.booking_reference}",
            data={
                "booking_id": booking_id,
                "booking_reference": booking.booking_reference,
                "confirmed_price": booking.current_quote.quoted_price,
                "confirmed_terms": booking.current_quote.terms_summary,
            },
        )

    async def check_booking_status(
        self,
        booking_id: str,
    ) -> ToolResponse:
        """
        Check and reconcile booking status with the provider.

        Per design doc (Unknown Outcome Reconciliation):
        - Used to reconcile UNKNOWN/PENDING bookings
        - Queries provider using idempotency key (provider_request_id)
        - Updates booking status based on provider response:
          - CONFIRMED → BOOKED (with booking_reference)
          - NOT_FOUND → FAILED (safe to retry)
          - PENDING → Stay PENDING (check again later)

        This is a skeleton implementation. Full provider integration
        will be added in Phase 3.

        Args:
            booking_id: The booking to check status for

        Returns:
            ToolResponse with status and next steps
        """
        logger.info(f"check_booking_status called: booking_id={booking_id}")

        # Load the booking
        booking = await self._booking_store.get_booking(booking_id)

        if booking is None:
            return _error_response(
                message=f"Booking not found: {booking_id}",
                error_code="BOOKING_NOT_FOUND",
            )

        # ═══════════════════════════════════════════════════════════════════
        # STATUS GUARD: Only run for UNKNOWN or PENDING statuses
        # Per design doc: check_booking_status only runs for UNKNOWN or PENDING
        # ═══════════════════════════════════════════════════════════════════

        if not booking.status.needs_reconciliation():
            # Status is already known - return current status
            status_messages = {
                BookingStatus.UNBOOKED: "This item has not been booked yet.",
                BookingStatus.BOOKED: f"Booking confirmed! Reference: {booking.booking_reference or 'N/A'}",
                BookingStatus.FAILED: "Booking failed. You can retry with a fresh quote.",
                BookingStatus.CANCELLED: "This booking was cancelled.",
            }
            return ToolResponse(
                success=True,
                message=status_messages.get(
                    booking.status,
                    f"Current status: {booking.status.value}"
                ),
                data={
                    "booking_id": booking_id,
                    "status": booking.status.value,
                    "booking_reference": booking.booking_reference,
                },
                ui=self._build_status_check_ui(booking),
            )

        # ═══════════════════════════════════════════════════════════════════
        # QUERY PROVIDER: Use idempotency key to check status
        # Skeleton: Simulate provider check - will be replaced with real call
        # ═══════════════════════════════════════════════════════════════════

        # In Phase 3, this will call:
        # provider_status = await provider_client.check_booking_status(
        #     idempotency_key=booking.provider_request_id
        # )

        # Skeleton implementation: Determine outcome based on presence of provider_request_id
        # This allows testing of all reconciliation paths
        provider_status = await self._query_provider_status(booking)

        # ═══════════════════════════════════════════════════════════════════
        # HANDLE PROVIDER RESPONSE: Update booking based on result
        # ═══════════════════════════════════════════════════════════════════

        return await self._handle_provider_status(booking, provider_status)

    async def _query_provider_status(self, booking: Booking) -> str:
        """
        Query provider for booking status.

        Skeleton implementation returns simulated statuses based on booking state.
        In production, this will call the actual provider API.

        Args:
            booking: The booking to check

        Returns:
            Provider status string: "confirmed", "not_found", or "pending"
        """
        # Skeleton: if provider_request_id exists, assume confirmed
        # This allows testing the success path
        # Full implementation will make actual provider calls

        if booking.provider_request_id:
            # Has a request ID - assume provider has a record
            # For skeleton, always return "confirmed" to test success path
            return "confirmed"

        # No request ID - provider has no record
        return "not_found"

    async def _handle_provider_status(
        self,
        booking: Booking,
        provider_status: str,
    ) -> ToolResponse:
        """
        Handle provider status response and update booking.

        Args:
            booking: The booking being reconciled
            provider_status: Status from provider ("confirmed", "not_found", "pending")

        Returns:
            ToolResponse with result and next steps
        """
        booking_id = booking.booking_id

        if provider_status == "confirmed":
            # Provider confirmed booking
            booking.status = BookingStatus.BOOKED
            # Generate booking reference if not already set
            if not booking.booking_reference:
                booking.booking_reference = f"REF-{booking_id[-8:].upper()}"
            booking.updated_at = datetime.now(timezone.utc)

            await self._booking_store.save_booking(booking)

            logger.info(
                f"Booking reconciled as CONFIRMED: booking_id={booking_id}, "
                f"reference={booking.booking_reference}"
            )

            return ToolResponse(
                success=True,
                message=f"Good news! Your booking was confirmed. Reference: {booking.booking_reference}",
                data={
                    "booking_id": booking_id,
                    "status": BookingStatus.BOOKED.value,
                    "booking_reference": booking.booking_reference,
                },
            )

        elif provider_status == "not_found":
            # Provider has no record - safe to retry
            booking.status = BookingStatus.FAILED
            booking.failure_reason = "Provider has no record of booking"
            booking.updated_at = datetime.now(timezone.utc)

            await self._booking_store.save_booking(booking)

            logger.info(
                f"Booking reconciled as NOT_FOUND: booking_id={booking_id}"
            )

            # Generate fresh quote for retry
            new_quote = self._generate_quote(booking)
            booking.current_quote = new_quote
            await self._booking_store.save_booking(booking)

            return _error_response(
                message="Booking was not processed. You can safely retry.",
                error_code="BOOKING_NOT_FOUND_AT_PROVIDER",
                data={
                    "booking_id": booking_id,
                    "status": BookingStatus.FAILED.value,
                    "retry_possible": True,
                },
                ui=UIDirective(
                    actions=[
                        UIAction(
                            label=self._format_action_label(
                                "Retry",
                                booking,
                                price=new_quote.quoted_price,
                                currency=new_quote.currency,
                            ),
                            event={
                                "type": "retry_booking",
                                "booking": {
                                    "booking_id": booking_id,
                                    "quote_id": new_quote.quote_id,
                                },
                            },
                        ),
                    ],
                    display_type="booking_options",
                ),
            )

        else:  # provider_status == "pending"
            # Provider is still processing
            logger.info(
                f"Booking still pending at provider: booking_id={booking_id}"
            )

            return _error_response(
                message="Booking is still being processed. Please check again shortly.",
                error_code="BOOKING_STILL_PENDING",
                data={
                    "booking_id": booking_id,
                    "status": BookingStatus.PENDING.value,
                },
                ui=UIDirective(
                    actions=[
                        UIAction(
                            label=self._format_action_label("Check Again", booking),
                            event={
                                "type": "check_booking_status",
                                "booking": {"booking_id": booking_id},
                            },
                        ),
                    ],
                    display_type="booking_options",
                ),
            )

    async def cancel_unknown_booking(
        self,
        booking_id: str,
    ) -> ToolResponse:
        """
        Cancel an UNKNOWN booking attempt and allow retry with fresh quote.

        Per design doc (Booking Safety - cancel_unknown_booking):
        - Only allowed for status=UNKNOWN
        - First, attempts reconciliation with provider
        - If provider confirms booking, converts to BOOKED (don't cancel!)
        - If provider has no record (NOT_FOUND), resets to FAILED and clears idempotency key
        - If provider still processing (PENDING), blocks cancellation

        This method ensures users can safely abandon an uncertain booking attempt
        only after confirming the provider has no record of it.

        Args:
            booking_id: The booking to cancel

        Returns:
            ToolResponse with result and next steps
        """
        logger.info(f"cancel_unknown_booking called: booking_id={booking_id}")

        # Load the booking
        booking = await self._booking_store.get_booking(booking_id)

        if booking is None:
            return _error_response(
                message=f"Booking not found: {booking_id}",
                error_code="BOOKING_NOT_FOUND",
            )

        # ═══════════════════════════════════════════════════════════════════
        # STATUS GUARD: Only UNKNOWN bookings can be cancelled this way
        # ═══════════════════════════════════════════════════════════════════

        if booking.status != BookingStatus.UNKNOWN:
            status_guidance = {
                BookingStatus.UNBOOKED: "This item is not booked. Use 'book_item' to book it.",
                BookingStatus.PENDING: "Booking is in progress. Wait for completion or check status.",
                BookingStatus.BOOKED: "This item is already booked. Use 'cancel_booking' to cancel it.",
                BookingStatus.FAILED: "Booking already failed. Use 'retry_booking' to try again.",
                BookingStatus.CANCELLED: "This booking was already cancelled.",
            }
            return _error_response(
                message=f"Cannot cancel: status is {booking.status.value}. "
                        f"{status_guidance.get(booking.status, '')}",
                error_code="INVALID_BOOKING_STATUS",
                data={"current_status": booking.status.value},
            )

        # ═══════════════════════════════════════════════════════════════════
        # RECONCILIATION FIRST: Check with provider before allowing cancel
        # Per design doc: Only cancel after confirming provider has no record
        # ═══════════════════════════════════════════════════════════════════

        provider_status = await self._query_provider_status(booking)

        # ─────────────────────────────────────────────────────────────────────
        # CASE 1: Provider CONFIRMS booking - Don't cancel! Convert to BOOKED
        # ─────────────────────────────────────────────────────────────────────
        if provider_status == "confirmed":
            booking.status = BookingStatus.BOOKED
            if not booking.booking_reference:
                booking.booking_reference = f"REF-{booking_id[-8:].upper()}"
            booking.updated_at = datetime.now(timezone.utc)

            await self._booking_store.save_booking(booking)

            logger.info(
                f"cancel_unknown_booking: Booking was actually confirmed! "
                f"booking_id={booking_id}, reference={booking.booking_reference}"
            )

            return ToolResponse(
                success=True,
                message=f"Good news! Your booking was actually confirmed. "
                        f"Reference: {booking.booking_reference}",
                data={
                    "booking_id": booking_id,
                    "status": BookingStatus.BOOKED.value,
                    "booking_reference": booking.booking_reference,
                },
            )

        # ─────────────────────────────────────────────────────────────────────
        # CASE 2: Provider still PENDING - Can't cancel yet
        # ─────────────────────────────────────────────────────────────────────
        if provider_status == "pending":
            logger.info(
                f"cancel_unknown_booking: Provider still processing, cannot cancel yet. "
                f"booking_id={booking_id}"
            )

            return _error_response(
                message="Provider is still processing. Cannot cancel yet.",
                error_code="BOOKING_STILL_PENDING",
                data={
                    "booking_id": booking_id,
                    "status": BookingStatus.UNKNOWN.value,
                },
                ui=UIDirective(
                    actions=[
                        UIAction(
                            label=self._format_action_label("Check Again", booking),
                            event={
                                "type": "check_booking_status",
                                "booking": {"booking_id": booking_id},
                            },
                        ),
                    ],
                    display_type="booking_options",
                ),
            )

        # ─────────────────────────────────────────────────────────────────────
        # CASE 3: Provider has NO RECORD - Safe to reset and allow retry
        # ─────────────────────────────────────────────────────────────────────
        # This is the expected path for cancelling an unknown booking

        booking.status = BookingStatus.FAILED
        booking.failure_reason = "Cancelled after UNKNOWN status - provider had no record"
        booking.provider_request_id = None  # Clear so next attempt gets fresh key
        booking.updated_at = datetime.now(timezone.utc)

        await self._booking_store.save_booking(booking)

        logger.info(
            f"cancel_unknown_booking: Reset to FAILED after NOT_FOUND at provider. "
            f"booking_id={booking_id}"
        )

        # Generate fresh quote for retry
        new_quote = self._generate_quote(booking)
        booking.current_quote = new_quote
        await self._booking_store.save_booking(booking)

        return ToolResponse(
            success=True,
            message="Previous attempt cancelled. You can now book with a fresh quote.",
            data={
                "booking_id": booking_id,
                "status": BookingStatus.FAILED.value,
                "new_quote": new_quote.to_dict(),
            },
                ui=UIDirective(
                    actions=[
                        UIAction(
                            label=self._format_action_label(
                                "Get Fresh Quote",
                                booking,
                                price=new_quote.quoted_price,
                                currency=new_quote.currency,
                            ),
                            event={"type": "view_booking_options"},
                        ),
                        UIAction(
                            label=self._format_action_label(
                                "Book Now",
                                booking,
                                price=new_quote.quoted_price,
                                currency=new_quote.currency,
                            ),
                            event={
                                "type": "retry_booking",
                                "booking": {
                                "booking_id": booking_id,
                                "quote_id": new_quote.quote_id,
                            },
                        },
                    ),
                ],
                display_type="booking_options",
            ),
        )

    def _build_status_check_ui(self, booking: Booking) -> UIDirective | None:
        """
        Build UI actions for status check response.

        Args:
            booking: The booking to build UI for

        Returns:
            UIDirective with actions based on current status, or None
        """
        actions: list[UIAction] = []

        if booking.status == BookingStatus.UNBOOKED and booking.current_quote:
            actions.append(
                UIAction(
                    label=self._format_action_label(
                        "Book",
                        booking,
                        price=booking.current_quote.quoted_price,
                        currency=booking.current_quote.currency,
                    ),
                    event={
                        "type": "book_item",
                        "booking": {
                            "booking_id": booking.booking_id,
                            "quote_id": booking.current_quote.quote_id,
                        },
                    },
                )
            )
        elif booking.status == BookingStatus.FAILED and booking.current_quote:
            actions.append(
                UIAction(
                    label=self._format_action_label(
                        "Retry",
                        booking,
                        price=booking.current_quote.quoted_price,
                        currency=booking.current_quote.currency,
                    ),
                    event={
                        "type": "retry_booking",
                        "booking": {
                            "booking_id": booking.booking_id,
                            "quote_id": booking.current_quote.quote_id,
                        },
                    },
                )
            )
        elif booking.status == BookingStatus.BOOKED and booking.cancellation_policy.is_cancellable:
            actions.append(
                UIAction(
                    label=self._format_action_label("Cancel", booking),
                    event={
                        "type": "cancel_booking",
                        "booking": {"booking_id": booking.booking_id},
                    },
                )
            )

        return (
            UIDirective(actions=actions, display_type="booking_options")
            if actions
            else None
        )

    async def cancel_booking(
        self,
        booking_id: str,
        confirm_fee: bool = False,
    ) -> ToolResponse:
        """
        Cancel a booked item with cancellation policy enforcement.

        Per design doc (Booking Safety - cancel_booking):
        - Only allowed for status=BOOKED
        - Checks cancellation policy (is_cancellable)
        - Calculates fee if past free cancellation window
        - Requires fee confirmation if cancellation incurs a fee
        - Updates booking status to CANCELLED with metadata

        This is a skeleton implementation. Full provider integration
        will be added in Phase 3.

        Args:
            booking_id: The booking to cancel
            confirm_fee: True if user has confirmed the cancellation fee

        Returns:
            ToolResponse with cancellation result
        """
        logger.info(f"cancel_booking called: booking_id={booking_id}, confirm_fee={confirm_fee}")

        # Load the booking
        booking = await self._booking_store.get_booking(booking_id)

        if booking is None:
            return _error_response(
                message=f"Booking not found: {booking_id}",
                error_code="BOOKING_NOT_FOUND",
            )

        # ═══════════════════════════════════════════════════════════════════
        # STATUS GUARD: Only BOOKED items can be cancelled
        # ═══════════════════════════════════════════════════════════════════

        if booking.status != BookingStatus.BOOKED:
            status_guidance = {
                BookingStatus.UNBOOKED: "This item hasn't been booked yet.",
                BookingStatus.PENDING: "Booking is in progress. Please wait for it to complete.",
                BookingStatus.FAILED: "This booking failed. Nothing to cancel.",
                BookingStatus.UNKNOWN: "Booking status is uncertain. Please check status first.",
                BookingStatus.CANCELLED: "This booking is already cancelled.",
            }
            return _error_response(
                message=f"Cannot cancel - booking status is {booking.status.value}. "
                        f"{status_guidance.get(booking.status, '')}",
                error_code="INVALID_BOOKING_STATUS",
                data={"current_status": booking.status.value},
            )

        # ═══════════════════════════════════════════════════════════════════
        # CANCELLATION POLICY CHECK
        # ═══════════════════════════════════════════════════════════════════

        policy = booking.cancellation_policy

        if not policy.is_cancellable:
            return _error_response(
                message="This booking is non-refundable and cannot be cancelled.",
                error_code="CANCELLATION_NOT_ALLOWED",
                data={
                    "policy": policy.to_dict(),
                    "booking_reference": booking.booking_reference,
                },
            )

        # Check if we're past the free cancellation window
        now = datetime.now(timezone.utc)
        cancellation_fee = policy.calculate_fee(booking.price, now)
        booking_price = booking.current_quote.quoted_price if booking.current_quote else booking.price

        # If there's a fee and user hasn't confirmed, ask for confirmation
        if cancellation_fee > 0 and not confirm_fee:
            refund_amount = booking_price - cancellation_fee

            # Format free cancellation deadline if available
            deadline_str = ""
            if policy.free_cancellation_until:
                deadline_str = f" Free cancellation ended on {policy.free_cancellation_until.strftime('%b %d, %Y at %H:%M UTC')}."

            return _error_response(
                message=f"Cancellation will incur a fee of ${cancellation_fee:.2f}.{deadline_str}",
                error_code="CANCELLATION_FEE_REQUIRED",
                data={
                    "cancellation_fee": cancellation_fee,
                    "original_price": booking_price,
                    "refund_amount": refund_amount,
                    "policy": policy.to_dict(),
                },
                ui=UIDirective(
                    actions=[
                        UIAction(
                            label=(
                                f"{self._format_action_label('Cancel', booking)} "
                                f"({self._format_price_label(cancellation_fee, booking.current_quote.currency if booking.current_quote else None)} fee)"
                            ),
                            event={
                                "type": "cancel_booking",
                                "booking": {
                                    "booking_id": booking_id,
                                    "confirm_fee": True,
                                },
                            },
                        ),
                        UIAction(
                            label=self._format_action_label("Keep", booking),
                            event={"type": "view_booking_options"},
                        ),
                    ],
                    display_type="booking_options",
                ),
            )

        # ═══════════════════════════════════════════════════════════════════
        # EXECUTE CANCELLATION
        # Skeleton: Mark as cancelled without actual provider call
        # In Phase 3, this will call provider cancellation API
        # ═══════════════════════════════════════════════════════════════════

        # Calculate refund amount
        refund_amount = booking_price - cancellation_fee

        # Update booking status
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = now
        booking.cancellation_reference = f"CANCEL-{booking_id[-8:].upper()}"  # Placeholder
        booking.refund_amount = refund_amount
        booking.updated_at = now

        await self._booking_store.save_booking(booking)

        logger.info(
            f"Booking cancelled (skeleton): booking_id={booking_id}, "
            f"cancellation_reference={booking.cancellation_reference}, "
            f"refund_amount=${refund_amount:.2f}"
        )

        # Build success message
        refund_message = ""
        if refund_amount > 0:
            refund_message = f" Refund of ${refund_amount:.2f} will be processed."
        elif cancellation_fee > 0:
            refund_message = f" A cancellation fee of ${cancellation_fee:.2f} was applied."

        return ToolResponse(
            success=True,
            message=f"Booking cancelled successfully.{refund_message}",
            data={
                "booking_id": booking_id,
                "cancellation_reference": booking.cancellation_reference,
                "refund_amount": refund_amount,
                "cancellation_fee": cancellation_fee,
            },
        )
