"""
Lookup tools for the orchestrator.

This module contains stateless lookup tools that retrieve data by ID:
- get_booking: Retrieve booking details by booking_id
- get_consultation: Retrieve consultation details by consultation_id

These tools are invoked:
1. From Layer 1b via regex pattern match ("show booking book_xxx", "show consultation cons_xxx")
2. From Layer 1c via LLM fallback (if no pattern match)

Per design doc:
- These are stateless tools that don't mutate workflow state
- They provide read-only access to booking/consultation data
- After WorkflowState TTL expires, they still work via consultation_summaries
"""

from src.orchestrator.tools.lookups.get_booking import (
    BookingNotFoundError,
    format_booking_details,
    get_booking,
)
from src.orchestrator.tools.lookups.get_consultation import (
    ConsultationNotFoundError,
    format_consultation_details,
    get_consultation,
)

__all__ = [
    # get_booking exports
    "BookingNotFoundError",
    "format_booking_details",
    "get_booking",
    # get_consultation exports
    "ConsultationNotFoundError",
    "format_consultation_details",
    "get_consultation",
]
