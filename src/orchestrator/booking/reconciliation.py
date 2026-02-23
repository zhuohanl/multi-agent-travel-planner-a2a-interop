"""
Periodic reconciliation job for UNKNOWN bookings.

This module implements the background reconciliation process for bookings
that have an UNKNOWN status (typically due to provider timeouts).

Per design doc (Booking Safety - Unknown Outcome Reconciliation):
- Periodically scan for UNKNOWN bookings
- Reconcile each with the provider using check_booking_status
- Log failures and alert ops team for bookings stuck too long
- Skip bookings that have been reconciled since scan started

Key functions:
- reconcile_unknown_bookings(): Main reconciliation job
- ReconciliationResult: Tracks reconciliation outcomes
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable, Awaitable

from src.orchestrator.models.booking import BookingStatus

if TYPE_CHECKING:
    from src.orchestrator.booking.service import BookingService
    from src.orchestrator.storage.booking_store import BookingStoreProtocol

logger = logging.getLogger(__name__)

# Alert threshold: bookings stuck in UNKNOWN for longer than this should alert ops
UNKNOWN_ALERT_THRESHOLD_HOURS = 1


@dataclass
class ReconciliationOutcome:
    """
    Tracks the outcome of reconciling a single booking.
    """

    booking_id: str
    success: bool
    previous_status: str = "UNKNOWN"
    new_status: str | None = None
    error: str | None = None
    needs_alert: bool = False
    alert_reason: str | None = None


@dataclass
class ReconciliationResult:
    """
    Aggregated result of a reconciliation run.

    Tracks successes, failures, and alerts for monitoring and logging.
    """

    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    total_processed: int = 0
    confirmed_count: int = 0
    not_found_count: int = 0
    still_pending_count: int = 0
    already_resolved_count: int = 0
    error_count: int = 0
    alerts_generated: int = 0
    outcomes: list[ReconciliationOutcome] = field(default_factory=list)

    def add_outcome(self, outcome: ReconciliationOutcome) -> None:
        """Add an outcome and update counts."""
        self.outcomes.append(outcome)
        self.total_processed += 1

        if outcome.success:
            if outcome.new_status == BookingStatus.BOOKED.value:
                self.confirmed_count += 1
            elif outcome.new_status == BookingStatus.FAILED.value:
                self.not_found_count += 1
            elif outcome.new_status == BookingStatus.PENDING.value or outcome.new_status == BookingStatus.UNKNOWN.value:
                self.still_pending_count += 1
            elif outcome.new_status is None:
                # Already resolved
                self.already_resolved_count += 1
        else:
            self.error_count += 1

        if outcome.needs_alert:
            self.alerts_generated += 1

    def complete(self) -> None:
        """Mark the reconciliation run as complete."""
        self.completed_at = datetime.now(timezone.utc)

    @property
    def duration_seconds(self) -> float | None:
        """Get the duration of the reconciliation run in seconds."""
        if self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/metrics."""
        return {
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "total_processed": self.total_processed,
            "confirmed_count": self.confirmed_count,
            "not_found_count": self.not_found_count,
            "still_pending_count": self.still_pending_count,
            "already_resolved_count": self.already_resolved_count,
            "error_count": self.error_count,
            "alerts_generated": self.alerts_generated,
        }


async def reconcile_unknown_bookings(
    booking_store: BookingStoreProtocol,
    booking_service: BookingService,
    alert_callback: Callable[[str, str, str], Awaitable[None]] | None = None,
    max_bookings: int | None = None,
) -> ReconciliationResult:
    """
    Background job to reconcile all UNKNOWN bookings.

    Per design doc (Booking Safety - Unknown Outcome Reconciliation):
    - Scans for all bookings with status=UNKNOWN
    - Calls check_booking_status for each
    - Logs failures and alerts for bookings older than 1 hour
    - Skips bookings that have been reconciled since scan started

    Args:
        booking_store: Store for retrieving bookings by status
        booking_service: Service for reconciliation via check_booking_status
        alert_callback: Optional async callback for alerting ops team.
                       Called with (booking_id, message, reason).
        max_bookings: Optional limit on number of bookings to process (for batching)

    Returns:
        ReconciliationResult with detailed outcomes
    """
    result = ReconciliationResult()

    logger.info("Starting UNKNOWN booking reconciliation job")

    # Get all UNKNOWN bookings
    try:
        unknown_bookings = await booking_store.get_bookings_by_status(BookingStatus.UNKNOWN)
    except Exception as e:
        logger.error(f"Failed to query UNKNOWN bookings: {e}")
        # Return empty result on query failure
        result.complete()
        return result

    logger.info(f"Found {len(unknown_bookings)} UNKNOWN bookings to reconcile")

    # Apply max_bookings limit if specified
    if max_bookings is not None and len(unknown_bookings) > max_bookings:
        logger.info(f"Limiting to {max_bookings} bookings")
        unknown_bookings = unknown_bookings[:max_bookings]

    # Process each booking
    for booking in unknown_bookings:
        outcome = await _reconcile_single_booking(
            booking.booking_id,
            booking.updated_at,
            booking_service,
            alert_callback,
        )
        result.add_outcome(outcome)

    result.complete()

    logger.info(
        f"Reconciliation complete: processed={result.total_processed}, "
        f"confirmed={result.confirmed_count}, not_found={result.not_found_count}, "
        f"pending={result.still_pending_count}, errors={result.error_count}, "
        f"alerts={result.alerts_generated}"
    )

    return result


async def _reconcile_single_booking(
    booking_id: str,
    updated_at: datetime | None,
    booking_service: BookingService,
    alert_callback: Callable[[str, str, str], Awaitable[None]] | None,
) -> ReconciliationOutcome:
    """
    Reconcile a single UNKNOWN booking.

    Args:
        booking_id: The booking to reconcile
        updated_at: When the booking was last updated (for age check)
        booking_service: Service for reconciliation
        alert_callback: Optional callback for alerts

    Returns:
        ReconciliationOutcome with details
    """
    outcome = ReconciliationOutcome(booking_id=booking_id, success=False)

    try:
        # Call check_booking_status which handles the reconciliation logic
        response = await booking_service.check_booking_status(booking_id)

        outcome.success = True

        # Extract the resulting status from the response
        if response.data:
            outcome.new_status = response.data.get("status")

        # Check if we need to alert for bookings stuck too long
        if _should_alert(updated_at, outcome.new_status):
            outcome.needs_alert = True
            outcome.alert_reason = f"Booking stuck in reconciliation for over {UNKNOWN_ALERT_THRESHOLD_HOURS} hour(s)"

            if alert_callback:
                try:
                    await alert_callback(
                        booking_id,
                        f"UNKNOWN booking reconciliation: {outcome.new_status}",
                        outcome.alert_reason,
                    )
                except Exception as alert_error:
                    logger.warning(
                        f"Failed to send alert for {booking_id}: {alert_error}"
                    )

        logger.debug(
            f"Reconciled booking {booking_id}: {outcome.previous_status} -> {outcome.new_status}"
        )

    except Exception as e:
        outcome.success = False
        outcome.error = str(e)

        logger.error(f"Reconciliation failed for {booking_id}: {e}")

        # Alert for repeated failures
        if _should_alert(updated_at, BookingStatus.UNKNOWN.value):
            outcome.needs_alert = True
            outcome.alert_reason = f"Reconciliation failed repeatedly: {e}"

            if alert_callback:
                try:
                    await alert_callback(
                        booking_id,
                        "UNKNOWN booking reconciliation failed",
                        outcome.alert_reason,
                    )
                except Exception as alert_error:
                    logger.warning(
                        f"Failed to send alert for {booking_id}: {alert_error}"
                    )

    return outcome


def _should_alert(
    updated_at: datetime | None,
    current_status: str | None,
) -> bool:
    """
    Determine if we should alert ops team for this booking.

    Per design doc: Alert for bookings stuck in UNKNOWN for over 1 hour.

    Args:
        updated_at: When the booking was last updated
        current_status: The current/resulting status after reconciliation

    Returns:
        True if an alert should be generated
    """
    # Only alert if still UNKNOWN or PENDING after reconciliation
    if current_status not in (BookingStatus.UNKNOWN.value, BookingStatus.PENDING.value):
        return False

    # Check age
    if updated_at is None:
        # No timestamp - be conservative and don't alert
        return False

    threshold = datetime.now(timezone.utc) - timedelta(hours=UNKNOWN_ALERT_THRESHOLD_HOURS)
    return updated_at < threshold
