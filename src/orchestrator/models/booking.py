"""Booking models for the travel planner orchestrator.

Per design doc Booking Safety section:
- Each bookable item in an approved itinerary is booked independently
- No transactional "cart" - each booking succeeds or fails on its own
- User has full control over booking order and retry decisions

Key models:
- BookingStatus: Enum tracking the booking lifecycle
- CancellationPolicy: Policy for cancelling a booking
- BookingQuote: Server-issued quote for exact price/terms
- Booking: Individual bookable item within an itinerary

State machine:
  UNBOOKED -> PENDING -> BOOKED (success)
                      -> FAILED (provider error, can retry)
                      -> UNKNOWN (timeout, needs reconciliation)
  UNKNOWN -> BOOKED (reconciliation found it succeeded)
          -> FAILED (reconciliation found it failed)
  BOOKED -> CANCELLED (if cancellation policy allows)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Literal


class BookingStatus(str, Enum):
    """Status of a booking in its lifecycle.

    Per design doc:
    - UNBOOKED: User hasn't booked yet
    - PENDING: Request sent to provider, awaiting response
    - BOOKED: Successfully booked (confirmed by provider)
    - FAILED: Provider rejected or error occurred (can retry)
    - UNKNOWN: Outcome uncertain (timeout) - needs reconciliation
    - CANCELLED: User cancelled after booking
    """

    UNBOOKED = "unbooked"
    PENDING = "pending"
    BOOKED = "booked"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"

    def can_book(self) -> bool:
        """Check if booking can be initiated from this status."""
        return self == BookingStatus.UNBOOKED

    def can_retry(self) -> bool:
        """Check if booking can be retried from this status."""
        return self == BookingStatus.FAILED

    def can_cancel(self) -> bool:
        """Check if booking can be cancelled from this status."""
        return self == BookingStatus.BOOKED

    def needs_reconciliation(self) -> bool:
        """Check if status needs provider reconciliation."""
        return self in (BookingStatus.UNKNOWN, BookingStatus.PENDING)

    def is_terminal(self) -> bool:
        """Check if this is a terminal status (no more actions possible without manual intervention)."""
        return self in (BookingStatus.CANCELLED,)


@dataclass
class CancellationPolicy:
    """Cancellation policy for a booking.

    Per design doc:
    - is_cancellable: False for non-refundable bookings
    - free_cancellation_until: Free cancellation deadline
    - fee_percentage: Fee after free period (0.0-1.0)
    - fee_fixed: Fixed fee amount
    - notes: Additional policy details

    Attributes:
        is_cancellable: Whether the booking can be cancelled at all
        free_cancellation_until: Deadline for free cancellation (None if no free period)
        fee_percentage: Percentage fee after free period (0.0-1.0, e.g., 0.20 = 20%)
        fee_fixed: Fixed fee amount after free period (overrides percentage if > 0)
        notes: Human-readable policy notes
    """

    is_cancellable: bool
    free_cancellation_until: datetime | None = None
    fee_percentage: float = 0.0
    fee_fixed: float = 0.0
    notes: str | None = None

    def compute_hash(self) -> str:
        """Compute hash for terms matching in BookingQuote.

        Per design doc: Used to detect when cancellation terms have changed
        between when a quote was issued and when booking is attempted.
        """
        # Format free_cancellation_until consistently for hashing
        free_cancel_str = (
            self.free_cancellation_until.isoformat()
            if self.free_cancellation_until
            else "None"
        )
        canonical = (
            f"{self.is_cancellable}|{free_cancel_str}|"
            f"{self.fee_percentage}|{self.fee_fixed}"
        )
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def calculate_fee(self, booking_amount: float, cancel_time: datetime | None = None) -> float:
        """Calculate cancellation fee based on timing and policy.

        Args:
            booking_amount: The total booking amount
            cancel_time: When cancellation is requested (defaults to now)

        Returns:
            The fee amount (0.0 if within free cancellation period)
        """
        if not self.is_cancellable:
            return booking_amount  # Full amount as penalty

        if cancel_time is None:
            cancel_time = datetime.now(timezone.utc)

        # Ensure cancel_time is timezone-aware
        if cancel_time.tzinfo is None:
            cancel_time = cancel_time.replace(tzinfo=timezone.utc)

        # Check free cancellation period
        if self.free_cancellation_until:
            free_until = self.free_cancellation_until
            if free_until.tzinfo is None:
                free_until = free_until.replace(tzinfo=timezone.utc)

            if cancel_time <= free_until:
                return 0.0  # Free cancellation

        # Apply fee (fixed takes precedence if > 0)
        if self.fee_fixed > 0:
            return min(self.fee_fixed, booking_amount)
        return booking_amount * self.fee_percentage

    def is_in_free_period(self, at_time: datetime | None = None) -> bool:
        """Check if within free cancellation period.

        Args:
            at_time: Time to check (defaults to now)

        Returns:
            True if within free cancellation period
        """
        if not self.is_cancellable or not self.free_cancellation_until:
            return False

        if at_time is None:
            at_time = datetime.now(timezone.utc)

        # Ensure at_time is timezone-aware
        if at_time.tzinfo is None:
            at_time = at_time.replace(tzinfo=timezone.utc)

        free_until = self.free_cancellation_until
        if free_until.tzinfo is None:
            free_until = free_until.replace(tzinfo=timezone.utc)

        return at_time <= free_until

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        result: dict[str, Any] = {
            "is_cancellable": self.is_cancellable,
            "fee_percentage": self.fee_percentage,
            "fee_fixed": self.fee_fixed,
        }
        if self.free_cancellation_until is not None:
            result["free_cancellation_until"] = self.free_cancellation_until.isoformat()
        if self.notes is not None:
            result["notes"] = self.notes
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CancellationPolicy:
        """Deserialize from dictionary."""
        # Parse free_cancellation_until
        free_cancel_raw = data.get("free_cancellation_until")
        free_cancel: datetime | None = None
        if free_cancel_raw:
            if isinstance(free_cancel_raw, str):
                try:
                    free_cancel = datetime.fromisoformat(free_cancel_raw)
                    if free_cancel.tzinfo is None:
                        free_cancel = free_cancel.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
            elif isinstance(free_cancel_raw, datetime):
                free_cancel = free_cancel_raw
                if free_cancel.tzinfo is None:
                    free_cancel = free_cancel.replace(tzinfo=timezone.utc)

        return cls(
            is_cancellable=bool(data.get("is_cancellable", True)),
            free_cancellation_until=free_cancel,
            fee_percentage=float(data.get("fee_percentage", 0.0)),
            fee_fixed=float(data.get("fee_fixed", 0.0)),
            notes=data.get("notes"),
        )

    @classmethod
    def non_refundable(cls, notes: str | None = None) -> CancellationPolicy:
        """Create a non-refundable policy."""
        return cls(
            is_cancellable=False,
            notes=notes or "Non-refundable booking",
        )

    @classmethod
    def free_cancellation(
        cls,
        until: datetime,
        fee_after: float = 1.0,
        notes: str | None = None,
    ) -> CancellationPolicy:
        """Create a policy with free cancellation until a date.

        Args:
            until: Free cancellation deadline
            fee_after: Fee percentage after deadline (default 100%)
            notes: Policy notes
        """
        return cls(
            is_cancellable=True,
            free_cancellation_until=until,
            fee_percentage=fee_after,
            notes=notes,
        )


@dataclass
class BookingQuote:
    """Server-issued quote for a specific price/terms.

    Per design doc:
    - Must be echoed back when booking to prove user saw and agreed to exact terms
    - Prevents price drift, stale confirmations, provides audit trail

    Attributes:
        quote_id: Unique identifier for this quote (quote_xxx format)
        booking_id: Which booking item this quote is for
        quoted_price: Exact price user saw
        currency: Currency code (USD, EUR, JPY, etc.)
        expires_at: Quote validity deadline
        terms_hash: SHA256 hash of cancellation terms (for change detection)
        terms_summary: Human-readable terms summary
        created_at: When quote was generated
    """

    quote_id: str
    booking_id: str
    quoted_price: float
    currency: str
    expires_at: datetime
    terms_hash: str
    terms_summary: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_expired(self, at_time: datetime | None = None) -> bool:
        """Check if the quote has expired.

        Args:
            at_time: Time to check against (defaults to now)

        Returns:
            True if quote has expired
        """
        if at_time is None:
            at_time = datetime.now(timezone.utc)

        # Ensure times are timezone-aware for comparison
        if at_time.tzinfo is None:
            at_time = at_time.replace(tzinfo=timezone.utc)

        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        return at_time > expires_at

    def terms_match(self, current_policy: CancellationPolicy) -> bool:
        """Check if terms have changed since quote was issued.

        Args:
            current_policy: Current cancellation policy to compare

        Returns:
            True if terms still match
        """
        return self.terms_hash == current_policy.compute_hash()

    def time_remaining(self, at_time: datetime | None = None) -> timedelta:
        """Get time remaining until quote expires.

        Args:
            at_time: Time to check from (defaults to now)

        Returns:
            Time remaining (negative if expired)
        """
        if at_time is None:
            at_time = datetime.now(timezone.utc)

        if at_time.tzinfo is None:
            at_time = at_time.replace(tzinfo=timezone.utc)

        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        return expires_at - at_time

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "quote_id": self.quote_id,
            "booking_id": self.booking_id,
            "quoted_price": self.quoted_price,
            "currency": self.currency,
            "expires_at": self.expires_at.isoformat(),
            "terms_hash": self.terms_hash,
            "terms_summary": self.terms_summary,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BookingQuote:
        """Deserialize from dictionary."""
        # Parse expires_at
        expires_at_raw = data.get("expires_at")
        if isinstance(expires_at_raw, str):
            try:
                expires_at = datetime.fromisoformat(expires_at_raw)
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
            except ValueError:
                expires_at = datetime.now(timezone.utc)
        elif isinstance(expires_at_raw, datetime):
            expires_at = expires_at_raw
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        else:
            expires_at = datetime.now(timezone.utc)

        # Parse created_at
        created_at_raw = data.get("created_at")
        if isinstance(created_at_raw, str):
            try:
                created_at = datetime.fromisoformat(created_at_raw)
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
            except ValueError:
                created_at = datetime.now(timezone.utc)
        elif isinstance(created_at_raw, datetime):
            created_at = created_at_raw
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
        else:
            created_at = datetime.now(timezone.utc)

        return cls(
            quote_id=data.get("quote_id", ""),
            booking_id=data.get("booking_id", ""),
            quoted_price=float(data.get("quoted_price", 0.0)),
            currency=data.get("currency", "USD"),
            expires_at=expires_at,
            terms_hash=data.get("terms_hash", ""),
            terms_summary=data.get("terms_summary", ""),
            created_at=created_at,
        )


# Type alias for booking item types
BookingItemType = Literal["flight", "hotel", "activity", "transport"]


@dataclass
class Booking:
    """Individual bookable item within an itinerary.

    Per design doc:
    - Each bookable item is booked independently (no cart)
    - Requires server-generated booking_id and user-confirmed quote_id
    - Status tracking prevents double-booking

    Attributes:
        booking_id: Unique identifier (book_xxx format)
        itinerary_id: Parent itinerary ID
        item_type: Type of item (flight, hotel, activity, transport)
        details: Item-specific details (dict for flexibility)
        status: Current booking status
        current_quote: Latest valid quote (refreshed on price/terms change)
        cancellation_policy: Policy for cancelling this booking
        price: Current price (may differ from quote if stale)
        booking_reference: Provider confirmation code (after booking)
        confirmed_quote_id: Which quote_id user confirmed (audit trail)
        failure_reason: Reason if status is FAILED
        etag: Cosmos DB ETag for optimistic locking
        provider_request_id: Idempotency key (booking_id:quote_id)
        status_reason: Context for current status
        updated_at: Last modification timestamp
        cancelled_at: When booking was cancelled
        cancellation_reference: Provider cancellation confirmation ID
        refund_amount: Actual refund amount (after fees)
    """

    booking_id: str
    itinerary_id: str
    item_type: BookingItemType
    details: dict[str, Any]
    status: BookingStatus
    cancellation_policy: CancellationPolicy
    price: float
    current_quote: BookingQuote | None = None
    booking_reference: str | None = None
    confirmed_quote_id: str | None = None
    failure_reason: str | None = None
    etag: str | None = None
    provider_request_id: str | None = None
    status_reason: str | None = None
    updated_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reference: str | None = None
    refund_amount: float | None = None

    def can_book(self) -> bool:
        """Check if booking can be initiated."""
        return self.status.can_book()

    def can_retry(self) -> bool:
        """Check if booking can be retried."""
        return self.status.can_retry()

    def can_cancel(self) -> bool:
        """Check if booking can be cancelled."""
        return self.status.can_cancel()

    def needs_reconciliation(self) -> bool:
        """Check if booking needs provider reconciliation."""
        return self.status.needs_reconciliation()

    def is_quote_valid(self, quote_id: str | None = None) -> bool:
        """Check if the current quote is valid.

        Args:
            quote_id: Optional quote_id to validate against

        Returns:
            True if quote exists, not expired, and matches quote_id if provided
        """
        if self.current_quote is None:
            return False
        if self.current_quote.is_expired():
            return False
        if quote_id is not None and self.current_quote.quote_id != quote_id:
            return False
        return True

    def generate_provider_request_id(self, quote_id: str) -> str:
        """Generate idempotency key for provider requests.

        Per design doc: Format is "{booking_id}:{quote_id}"

        Args:
            quote_id: The quote ID being used for this booking attempt

        Returns:
            Provider request ID for idempotency
        """
        return f"{self.booking_id}:{quote_id}"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for Cosmos DB storage.

        Includes TTL calculation based on trip end date if available.
        """
        result: dict[str, Any] = {
            "booking_id": self.booking_id,
            "id": self.booking_id,  # Cosmos DB document ID
            "itinerary_id": self.itinerary_id,
            "item_type": self.item_type,
            "details": self.details,
            "status": self.status.value,
            "cancellation_policy": self.cancellation_policy.to_dict(),
            "price": self.price,
        }

        if self.current_quote is not None:
            result["current_quote"] = self.current_quote.to_dict()
        if self.booking_reference is not None:
            result["booking_reference"] = self.booking_reference
        if self.confirmed_quote_id is not None:
            result["confirmed_quote_id"] = self.confirmed_quote_id
        if self.failure_reason is not None:
            result["failure_reason"] = self.failure_reason
        if self.etag is not None:
            result["_etag"] = self.etag
        if self.provider_request_id is not None:
            result["provider_request_id"] = self.provider_request_id
        if self.status_reason is not None:
            result["status_reason"] = self.status_reason
        if self.updated_at is not None:
            result["updated_at"] = self.updated_at.isoformat()
        if self.cancelled_at is not None:
            result["cancelled_at"] = self.cancelled_at.isoformat()
        if self.cancellation_reference is not None:
            result["cancellation_reference"] = self.cancellation_reference
        if self.refund_amount is not None:
            result["refund_amount"] = self.refund_amount

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Booking:
        """Deserialize from dictionary."""
        # Parse status
        status_raw = data.get("status", "unbooked")
        try:
            status = BookingStatus(status_raw)
        except ValueError:
            status = BookingStatus.UNBOOKED

        # Parse current_quote
        quote_data = data.get("current_quote")
        current_quote = BookingQuote.from_dict(quote_data) if quote_data else None

        # Parse cancellation_policy
        policy_data = data.get("cancellation_policy", {})
        cancellation_policy = CancellationPolicy.from_dict(policy_data)

        # Parse updated_at
        updated_at: datetime | None = None
        updated_at_raw = data.get("updated_at")
        if updated_at_raw:
            if isinstance(updated_at_raw, str):
                try:
                    updated_at = datetime.fromisoformat(updated_at_raw)
                    if updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
            elif isinstance(updated_at_raw, datetime):
                updated_at = updated_at_raw
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)

        # Parse cancelled_at
        cancelled_at: datetime | None = None
        cancelled_at_raw = data.get("cancelled_at")
        if cancelled_at_raw:
            if isinstance(cancelled_at_raw, str):
                try:
                    cancelled_at = datetime.fromisoformat(cancelled_at_raw)
                    if cancelled_at.tzinfo is None:
                        cancelled_at = cancelled_at.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
            elif isinstance(cancelled_at_raw, datetime):
                cancelled_at = cancelled_at_raw
                if cancelled_at.tzinfo is None:
                    cancelled_at = cancelled_at.replace(tzinfo=timezone.utc)

        # Parse item_type with validation
        item_type_raw = data.get("item_type", "activity")
        valid_types = {"flight", "hotel", "activity", "transport"}
        item_type: BookingItemType = (
            item_type_raw if item_type_raw in valid_types else "activity"
        )

        return cls(
            booking_id=data.get("booking_id", data.get("id", "")),
            itinerary_id=data.get("itinerary_id", ""),
            item_type=item_type,  # type: ignore[arg-type]
            details=dict(data.get("details", {})),
            status=status,
            cancellation_policy=cancellation_policy,
            price=float(data.get("price", 0.0)),
            current_quote=current_quote,
            booking_reference=data.get("booking_reference"),
            confirmed_quote_id=data.get("confirmed_quote_id"),
            failure_reason=data.get("failure_reason"),
            etag=data.get("_etag"),
            provider_request_id=data.get("provider_request_id"),
            status_reason=data.get("status_reason"),
            updated_at=updated_at,
            cancelled_at=cancelled_at,
            cancellation_reference=data.get("cancellation_reference"),
            refund_amount=data.get("refund_amount"),
        )

    @classmethod
    def create_unbooked(
        cls,
        booking_id: str,
        itinerary_id: str,
        item_type: BookingItemType,
        details: dict[str, Any],
        price: float,
        cancellation_policy: CancellationPolicy,
    ) -> Booking:
        """Factory method to create a new unbooked booking.

        Args:
            booking_id: Unique booking ID
            itinerary_id: Parent itinerary ID
            item_type: Type of booking item
            details: Item-specific details
            price: Current price
            cancellation_policy: Cancellation terms

        Returns:
            New Booking instance in UNBOOKED status
        """
        return cls(
            booking_id=booking_id,
            itinerary_id=itinerary_id,
            item_type=item_type,
            details=details,
            status=BookingStatus.UNBOOKED,
            cancellation_policy=cancellation_policy,
            price=price,
            updated_at=datetime.now(timezone.utc),
        )

    def __str__(self) -> str:
        """Human-readable summary."""
        return (
            f"Booking {self.booking_id}: {self.item_type} "
            f"({self.status.value}) - ${self.price:.2f}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Booking Summary Models (for status reporting)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class BookingItemStatus:
    """Status of a single booking item for summary display.

    Per design doc get_booking_summary (Booking Safety section):
    Provides a simplified view of a booking's current state for status display.
    """

    booking_id: str
    item_type: str
    name: str | None
    status: BookingStatus
    booking_reference: str | None = None
    can_cancel: bool | None = None  # Only set if status == BOOKED
    can_retry: bool = False  # True if status == FAILED

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "booking_id": self.booking_id,
            "item_type": self.item_type,
            "name": self.name,
            "status": self.status.value,
        }
        if self.booking_reference:
            result["booking_reference"] = self.booking_reference
        if self.can_cancel is not None:
            result["can_cancel"] = self.can_cancel
        if self.can_retry:
            result["can_retry"] = self.can_retry
        return result


@dataclass
class BookingSummary:
    """Summary of all bookings for an itinerary.

    Per design doc get_booking_summary (Booking Safety section):
    Aggregates booking statuses for the booking phase status response.
    """

    itinerary_id: str
    items: list[BookingItemStatus]
    booked_count: int
    unbooked_count: int
    failed_count: int
    pending_count: int = 0
    unknown_count: int = 0
    cancelled_count: int = 0

    @property
    def total_count(self) -> int:
        """Total number of bookable items."""
        return len(self.items)

    @property
    def all_terminal(self) -> bool:
        """True if all bookings are in a terminal state (BOOKED, FAILED, CANCELLED)."""
        return self.pending_count == 0 and self.unknown_count == 0 and self.unbooked_count == 0

    @property
    def all_booked(self) -> bool:
        """True if all bookings are successfully booked."""
        return self.booked_count == self.total_count

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "itinerary_id": self.itinerary_id,
            "items": [item.to_dict() for item in self.items],
            "counts": {
                "total": self.total_count,
                "booked": self.booked_count,
                "unbooked": self.unbooked_count,
                "pending": self.pending_count,
                "failed": self.failed_count,
                "unknown": self.unknown_count,
                "cancelled": self.cancelled_count,
            },
            "all_terminal": self.all_terminal,
            "all_booked": self.all_booked,
        }
