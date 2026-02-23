"""
Get consultation lookup tool.

This module provides the get_consultation tool for retrieving consultation details
by consultation ID. It is a stateless lookup tool that doesn't mutate workflow state.

Per design doc (Tool 7: get_consultation):
- Parameters: consultation_id (required)
- Returns: Consultation details including TripSpec summary, itinerary IDs, booking IDs, current phase
- Works after WorkflowState TTL expires via consultation_summaries

Lookup Strategy:
1. First, try consultation_summaries container (O(1) by consultation_id partition key)
2. If summary exists and WorkflowState is still active, enrich with live workflow data
3. If summary exists but WorkflowState expired, return summary with itinerary/booking references
4. Returns: trip spec summary, itinerary IDs, booking IDs, consultation status

Invocation paths:
1. Layer 1b regex: "show consultation cons_xxx" -> get_consultation(consultation_id)
2. Layer 1c LLM fallback: "what's the status of my trip" -> LLM decides
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.orchestrator.auth import (
    AuthenticatedUser,
    authorize_itinerary_read,
)
from src.orchestrator.storage.consultation_index import ConsultationIndexStoreProtocol
from src.orchestrator.storage.consultation_summaries import (
    ConsultationSummary,
    ConsultationSummaryStoreProtocol,
)
from src.orchestrator.storage.session_state import (
    WorkflowStateData,
    WorkflowStateStoreProtocol,
)


# =============================================================================
# EXCEPTIONS
# =============================================================================


class ConsultationNotFoundError(ValueError):
    """Raised when a consultation ID is not found in any store."""

    def __init__(self, consultation_id: str, message: str | None = None) -> None:
        self.consultation_id = consultation_id
        self.message = message or f"Consultation not found: {consultation_id}"
        super().__init__(self.message)


# =============================================================================
# FORMATTING
# =============================================================================


def format_phase(phase: str) -> str:
    """Format workflow phase for display.

    Args:
        phase: The phase string (e.g., "CLARIFICATION", "BOOKING")

    Returns:
        Human-readable phase string
    """
    phase_descriptions = {
        "CLARIFICATION": "Gathering trip details",
        "clarification": "Gathering trip details",
        "DISCOVERY_IN_PROGRESS": "Searching for options",
        "discovery_in_progress": "Searching for options",
        "DISCOVERY_COMPLETE": "Options found",
        "discovery_complete": "Options found",
        "BOOKING": "Ready for booking",
        "booking": "Ready for booking",
        "COMPLETED": "Trip completed",
        "completed": "Trip completed",
        "CANCELLED": "Consultation cancelled",
        "cancelled": "Consultation cancelled",
        "FAILED": "Planning failed",
        "failed": "Planning failed",
    }
    return phase_descriptions.get(phase, phase.replace("_", " ").title())


def format_status(status: str) -> str:
    """Format consultation status for display.

    Args:
        status: The status string

    Returns:
        Human-readable status string
    """
    status_descriptions = {
        "active": "Active",
        "itinerary_approved": "Itinerary approved",
        "completed": "Completed",
        "cancelled": "Cancelled",
    }
    return status_descriptions.get(status, status.replace("_", " ").title())


def format_trip_spec_summary(trip_spec_summary: dict[str, Any]) -> str:
    """Format trip spec summary for display.

    Args:
        trip_spec_summary: Dict containing destination, dates, travelers

    Returns:
        Formatted trip summary string
    """
    lines: list[str] = []

    destination = trip_spec_summary.get("destination")
    if destination:
        lines.append(f"Destination: {destination}")

    dates = trip_spec_summary.get("dates", {})
    if dates:
        start = dates.get("start", "")
        end = dates.get("end", "")
        if start and end:
            lines.append(f"Dates: {start} to {end}")
        elif start:
            lines.append(f"Start date: {start}")

    travelers = trip_spec_summary.get("travelers")
    if travelers:
        lines.append(f"Travelers: {travelers}")

    return "\n".join(lines) if lines else "No trip details available"


def format_consultation_details(
    consultation_id: str,
    summary: ConsultationSummary | None = None,
    workflow_state: WorkflowStateData | None = None,
) -> str:
    """Format consultation details for display.

    Produces a human-readable summary of the consultation including:
    - Consultation ID
    - Current status/phase
    - Trip details (destination, dates, travelers)
    - Itinerary IDs (if any)
    - Booking IDs (if any)

    Args:
        consultation_id: The consultation identifier
        summary: Optional consultation summary (for post-expiry access)
        workflow_state: Optional live workflow state (for active consultations)

    Returns:
        Formatted consultation details string
    """
    lines: list[str] = []

    # Header
    lines.append(f"Consultation: {consultation_id}")

    # Status/Phase
    if workflow_state:
        lines.append(f"Status: {format_phase(workflow_state.phase)}")
        if workflow_state.checkpoint:
            lines.append(f"Checkpoint: {workflow_state.checkpoint}")
    elif summary:
        lines.append(f"Status: {format_status(summary.status)}")

    # Trip details
    if summary and summary.trip_spec_summary:
        lines.append("")
        lines.append("Trip Details:")
        lines.append(format_trip_spec_summary(summary.trip_spec_summary))

    # Itinerary references
    itinerary_ids = summary.itinerary_ids if summary else []
    if workflow_state and workflow_state.itinerary_id:
        # Add current itinerary if not already in list
        if workflow_state.itinerary_id not in itinerary_ids:
            itinerary_ids = [workflow_state.itinerary_id] + itinerary_ids

    if itinerary_ids:
        lines.append("")
        lines.append(f"Itineraries: {len(itinerary_ids)}")
        for itin_id in itinerary_ids:
            lines.append(f"  - {itin_id}")

    # Booking references
    booking_ids = summary.booking_ids if summary else []
    if booking_ids:
        lines.append("")
        lines.append(f"Bookings: {len(booking_ids)}")
        for booking_id in booking_ids:
            lines.append(f"  - {booking_id}")

    # Timestamps
    if summary:
        lines.append("")
        lines.append(f"Created: {summary.created_at.isoformat()}")
        lines.append(f"Updated: {summary.updated_at.isoformat()}")
        if summary.trip_end_date:
            lines.append(f"Trip ends: {summary.trip_end_date}")

    return "\n".join(lines)


# =============================================================================
# LOOKUP RESULT
# =============================================================================


@dataclass
class GetConsultationResult:
    """Result of get_consultation lookup.

    Attributes:
        success: Whether the lookup succeeded
        message: Human-readable message
        consultation_id: The consultation identifier
        summary: The consultation summary (if found)
        workflow_state: The live workflow state (if still active)
        formatted: Formatted consultation details string
        data: Raw consultation data dict (for API responses)
    """

    success: bool
    message: str
    consultation_id: str | None = None
    summary: ConsultationSummary | None = None
    workflow_state: WorkflowStateData | None = None
    formatted: str | None = None
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for API responses."""
        result: dict[str, Any] = {
            "success": self.success,
            "message": self.message,
        }
        if self.consultation_id:
            result["consultation_id"] = self.consultation_id
        if self.formatted:
            result["formatted"] = self.formatted
        if self.data:
            result["data"] = self.data
        return result


# =============================================================================
# MAIN LOOKUP FUNCTION
# =============================================================================


async def get_consultation(
    consultation_id: str,
    summary_store: ConsultationSummaryStoreProtocol,
    consultation_index_store: ConsultationIndexStoreProtocol | None = None,
    workflow_state_store: WorkflowStateStoreProtocol | None = None,
) -> GetConsultationResult:
    """
    Retrieve consultation details by consultation ID.

    This is a stateless lookup tool (Tool 7 in design doc) that returns
    consultation information without modifying any state.

    Per design doc Lookup Strategy:
    1. First, try consultation_summaries container (O(1) by consultation_id)
    2. If summary exists and WorkflowState is still active, enrich with live data
    3. If summary exists but WorkflowState expired, return summary alone
    4. If no summary, try consultation_index → WorkflowState (for pre-approval state)

    Args:
        consultation_id: The consultation identifier (e.g., "cons_xyz789")
        summary_store: The consultation summary store to query
        consultation_index_store: Optional consultation index for active lookup
        workflow_state_store: Optional workflow state store for live data

    Returns:
        GetConsultationResult with consultation details

    Example:
        >>> result = await get_consultation("cons_xyz789", summary_store)
        >>> if result.success:
        ...     print(result.formatted)
        Consultation: cons_xyz789
        Status: Itinerary approved
        ...
    """
    # Validate consultation_id format (should start with "cons_")
    if not consultation_id:
        return GetConsultationResult(
            success=False,
            message="Consultation ID is required",
        )

    if not consultation_id.startswith("cons_"):
        return GetConsultationResult(
            success=False,
            message=f"Invalid consultation ID format: {consultation_id}. Expected format: cons_<id>",
        )

    # Step 1: Try consultation_summaries first (works post-expiry)
    summary = await summary_store.get_summary(consultation_id)

    # Step 2: Try to get live WorkflowState if stores are provided
    workflow_state: WorkflowStateData | None = None

    if summary and workflow_state_store and consultation_index_store:
        # Summary exists - try to enrich with live data
        index_entry = await consultation_index_store.get_session_for_consultation(
            consultation_id
        )
        if index_entry:
            # Check workflow version matches (identity integrity)
            state = await workflow_state_store.get_state(index_entry.session_id)
            if state and state.workflow_version == index_entry.workflow_version:
                workflow_state = state

    elif not summary and consultation_index_store and workflow_state_store:
        # No summary yet (pre-approval) - try consultation_index → WorkflowState
        index_entry = await consultation_index_store.get_session_for_consultation(
            consultation_id
        )
        if index_entry:
            state = await workflow_state_store.get_state(index_entry.session_id)
            if state and state.workflow_version == index_entry.workflow_version:
                workflow_state = state

    # Check if we found anything
    if summary is None and workflow_state is None:
        return GetConsultationResult(
            success=False,
            message=f"Consultation not found: {consultation_id}",
            consultation_id=consultation_id,
        )

    # Authorization check (MVP mode allows all when user=None)
    # Per design doc Authorization Model section:
    # - MVP mode: No auth required, IDs as bearer tokens
    # - Production mode: Would pass AuthenticatedUser from OAuth/Azure AD
    # For consultations, we use itinerary authorization since consultations
    # may contain itinerary references. In MVP mode this always allows.
    user: AuthenticatedUser | None = None  # MVP mode: no auth required
    # Use authorize_itinerary_read with the available authorization subject.
    # Either summary or workflow_state must exist at this point.
    # In MVP mode (user=None, share_token=None), this always returns allowed=True.
    auth_subject = summary if summary is not None else workflow_state
    auth_result = authorize_itinerary_read(
        itinerary=auth_subject,  # Use summary or workflow_state as subject
        user=user,
        share_token=None,
    )
    if not auth_result.allowed:
        return GetConsultationResult(
            success=False,
            message="You don't have permission to view this consultation.",
            consultation_id=consultation_id,
        )

    # Format the consultation details
    formatted = format_consultation_details(
        consultation_id=consultation_id,
        summary=summary,
        workflow_state=workflow_state,
    )

    # Build data dict for API responses
    data: dict[str, Any] = {
        "consultation_id": consultation_id,
    }

    if summary:
        data["trip_spec_summary"] = summary.trip_spec_summary
        data["itinerary_ids"] = summary.itinerary_ids
        data["booking_ids"] = summary.booking_ids
        data["status"] = summary.status
        data["created_at"] = summary.created_at.isoformat()
        data["updated_at"] = summary.updated_at.isoformat()
        if summary.trip_end_date:
            data["trip_end_date"] = str(summary.trip_end_date)

    if workflow_state:
        data["phase"] = workflow_state.phase
        data["checkpoint"] = workflow_state.checkpoint
        data["current_step"] = workflow_state.current_step
        data["session_id"] = workflow_state.session_id
        if workflow_state.itinerary_id:
            # Include current itinerary in data
            current_itinerary = workflow_state.itinerary_id
            if "itinerary_ids" not in data:
                data["itinerary_ids"] = []
            if current_itinerary not in data["itinerary_ids"]:
                data["itinerary_ids"] = [current_itinerary] + data.get(
                    "itinerary_ids", []
                )

    # Set flags for client convenience
    data["is_active"] = workflow_state is not None
    data["has_itinerary"] = bool(data.get("itinerary_ids"))
    data["has_bookings"] = bool(data.get("booking_ids"))

    return GetConsultationResult(
        success=True,
        message=f"Found consultation: {consultation_id}",
        consultation_id=consultation_id,
        summary=summary,
        workflow_state=workflow_state,
        formatted=formatted,
        data=data,
    )
