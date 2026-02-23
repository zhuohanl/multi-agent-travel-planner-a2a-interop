"""
Booking module for the travel planner orchestrator.

This module contains the BookingService which handles booking actions
invoked via workflow_turn events. The BookingService provides the
integration point for booking safety logic.

Key components:
- BookingService: Main service class for booking operations
- Quote validation: validate_quote, QuoteValidationResult, QuoteValidationStatus
- Reconciliation: reconcile_unknown_bookings for background UNKNOWN cleanup
"""

from src.orchestrator.booking.quote_validator import (
    QuoteValidationResult,
    QuoteValidationStatus,
    get_error_code_for_status,
    is_quote_expired,
    is_quote_valid_for_booking,
    validate_quote,
)
from src.orchestrator.booking.reconciliation import (
    ReconciliationOutcome,
    ReconciliationResult,
    reconcile_unknown_bookings,
    UNKNOWN_ALERT_THRESHOLD_HOURS,
)
from src.orchestrator.booking.service import BookingService

__all__ = [
    "BookingService",
    "QuoteValidationResult",
    "QuoteValidationStatus",
    "ReconciliationOutcome",
    "ReconciliationResult",
    "UNKNOWN_ALERT_THRESHOLD_HOURS",
    "get_error_code_for_status",
    "is_quote_expired",
    "is_quote_valid_for_booking",
    "reconcile_unknown_bookings",
    "validate_quote",
]
