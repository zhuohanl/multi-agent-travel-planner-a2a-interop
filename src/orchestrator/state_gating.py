"""
State gating module for workflow event and action validation.

This module is the SINGLE SOURCE OF TRUTH for:
- Phase-based event validation
- Checkpoint-based event validation
- checkpoint_id validation (prevents stale UI approvals)
- Action validation for free-text classification paths

Per design doc State Gating at Checkpoints section:
- Two-layer gating: event-level (validate_event) and action-level (_validate_action_for_phase)
- CHECKPOINT_VALID_EVENTS: Events valid at approval gates
- PHASE_VALID_EVENTS: Events valid when checkpoint=None
- BOOKING_PHASE_EVENTS: Events valid during free-form booking
- ERROR_RECOVERY_EVENTS: Events for discovery error recovery
- PHASE_VALID_ACTIONS: Actions valid per phase (guards free-text classification)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from src.orchestrator.models.workflow_state import Phase, WorkflowState

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Custom Exceptions
# ═══════════════════════════════════════════════════════════════════════════════


class InvalidEventError(Exception):
    """
    Raised when an event is not valid for the current workflow state.

    Attributes:
        message: Human-readable error message
        error_code: Machine-readable code for client handling
        retry_action: Optional UI action to recover from the error
    """

    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        retry_action: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or "INVALID_EVENT"
        self.retry_action = retry_action


# ═══════════════════════════════════════════════════════════════════════════════
# Action Enum
# ═══════════════════════════════════════════════════════════════════════════════


class Action(str, Enum):
    """All possible actions within workflow_turn."""

    # Phase transitions
    START_CLARIFICATION = "start_clarification"
    CONTINUE_CLARIFICATION = "continue_clarification"
    APPROVE_TRIP_SPEC = "approve_trip_spec"
    START_DISCOVERY = "start_discovery"
    APPROVE_ITINERARY = "approve_itinerary"
    REQUEST_MODIFICATION = "request_modification"

    # Booking actions
    VIEW_BOOKING_OPTIONS = "view_booking_options"  # Navigation: show available items
    BOOK_SINGLE_ITEM = "book_single_item"  # Action: execute booking
    RETRY_BOOKING = "retry_booking"
    CANCEL_BOOKING = "cancel_booking"
    CHECK_BOOKING_STATUS = "check_booking_status"  # Reconcile UNKNOWN/PENDING booking
    CANCEL_UNKNOWN_BOOKING = "cancel_unknown_booking"  # Cancel UNKNOWN booking attempt

    # Recovery actions
    START_NEW_WORKFLOW = "start_new_workflow"  # Reset and start fresh

    # Meta actions
    ANSWER_QUESTION_IN_CONTEXT = "answer_question_in_context"
    CALL_UTILITY = "call_utility"  # Context-aware utility call (Layer 2)
    CANCEL_WORKFLOW = "cancel_workflow"
    GET_STATUS = "get_status"


# ═══════════════════════════════════════════════════════════════════════════════
# Event Tables - Canonical Definitions
# ═══════════════════════════════════════════════════════════════════════════════

# Valid event types per checkpoint (approval gates only)
# Note: Booking phase uses BOOKING_PHASE_EVENTS instead (see below)
CHECKPOINT_VALID_EVENTS: dict[str, set[str]] = {
    "trip_spec_approval": {
        "approve_checkpoint",  # -> Proceed to discovery
        "request_change",  # -> Continue clarification
        "cancel_workflow",  # -> Cancel
        "status",  # -> Refresh status at checkpoint
        "free_text",  # -> Classify intent
    },
    "itinerary_approval": {
        "approve_checkpoint",  # -> Proceed to booking (creates itinerary_id + booking_ids)
        "request_change",  # -> Modify specific items
        "retry_discovery",  # -> Re-run all discovery agents from scratch
        "cancel_workflow",  # -> Cancel
        "status",  # -> Refresh status at checkpoint
        "free_text",  # -> Classify intent
    },
}

# Valid events per phase when checkpoint=None (non-gated states)
# Prevents booking events from slipping into clarification/discovery phases
PHASE_VALID_EVENTS: dict[Phase, set[str]] = {
    Phase.CLARIFICATION: {
        "free_text",  # Continue conversation with clarifier
        "cancel_workflow",  # Abandon workflow
    },
    Phase.DISCOVERY_IN_PROGRESS: {
        "free_text",  # Questions while waiting (routed to Q&A)
        "status",  # Check job progress
        "cancel_workflow",  # Abandon workflow
        "request_change",  # Queued for when job completes
    },
    # Note: DISCOVERY_PLANNING always has checkpoint="itinerary_approval"
    # Note: BOOKING uses BOOKING_PHASE_EVENTS (handled separately)
}

# Valid events during booking phase (not a checkpoint - free-form booking)
BOOKING_PHASE_EVENTS: set[str] = {
    "view_booking_options",  # Show booking items (all or single via optional booking_id)
    "book_item",  # Book single item (requires booking.booking_id + quote_id)
    "retry_booking",  # Retry failed booking (requires booking.booking_id + quote_id)
    "cancel_booking",  # Cancel a booked item (if policy allows)
    "check_booking_status",  # Check status of UNKNOWN/PENDING booking (reconciliation)
    "cancel_unknown_booking",  # Cancel UNKNOWN booking attempt before retrying
    "status",  # Get workflow status
    "cancel_workflow",  # Abandon trip
    "free_text",  # Classify intent
}

# Error recovery events (valid during DISCOVERY_IN_PROGRESS or DISCOVERY_PLANNING phases)
# Note: FAILED is terminal - only start_new/status allowed there (see validate_event)
ERROR_RECOVERY_EVENTS: set[str] = {
    "retry_agent",  # Retry a specific agent that failed/timed out
    "skip_agent",  # Skip a failed agent and continue
    "start_new",  # Abandon current workflow and start fresh
}

# Events that require checkpoint_id validation (prevent stale UI approvals)
CHECKPOINT_GATED_EVENTS: set[str] = {
    "approve_checkpoint",
    "request_change",
    "retry_discovery",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Action Tables - Phase-Action Validation
# ═══════════════════════════════════════════════════════════════════════════════

# Meta actions valid in ALL phases (read-only, don't mutate workflow state)
UNIVERSAL_ACTIONS: set[Action] = {
    Action.ANSWER_QUESTION_IN_CONTEXT,
    Action.CALL_UTILITY,
    Action.GET_STATUS,
    Action.CANCEL_WORKFLOW,
}

# Phase-specific valid actions (in addition to UNIVERSAL_ACTIONS)
PHASE_VALID_ACTIONS: dict[Phase, set[Action]] = {
    Phase.CLARIFICATION: {
        Action.START_CLARIFICATION,
        Action.CONTINUE_CLARIFICATION,
        Action.APPROVE_TRIP_SPEC,  # Only at checkpoint
        Action.REQUEST_MODIFICATION,
    },
    Phase.DISCOVERY_IN_PROGRESS: {
        # Limited actions while job is running
        # No approvals, no modifications (job must complete first)
        Action.REQUEST_MODIFICATION,  # Queued for when job completes
    },
    Phase.DISCOVERY_PLANNING: {
        Action.APPROVE_ITINERARY,  # Only at checkpoint
        Action.REQUEST_MODIFICATION,
    },
    Phase.BOOKING: {
        Action.VIEW_BOOKING_OPTIONS,
        Action.BOOK_SINGLE_ITEM,  # Only valid HERE (not in discovery)
        Action.RETRY_BOOKING,
        Action.CANCEL_BOOKING,
        Action.CHECK_BOOKING_STATUS,
        Action.CANCEL_UNKNOWN_BOOKING,
    },
    Phase.COMPLETED: {
        Action.START_NEW_WORKFLOW,  # Can restart from completed
    },
    Phase.FAILED: {
        Action.START_NEW_WORKFLOW,  # Can restart from failed
    },
    Phase.CANCELLED: {
        Action.START_NEW_WORKFLOW,  # Can restart from cancelled
    },
}

# Actions that REQUIRE booking payload (booking_id, quote_id) for consent
BOOKING_ACTIONS_REQUIRING_PAYLOAD: set[Action] = {
    Action.BOOK_SINGLE_ITEM,  # Requires booking_id + quote_id
    Action.RETRY_BOOKING,  # Requires booking_id + quote_id
    Action.CANCEL_BOOKING,  # Requires booking_id
    Action.CHECK_BOOKING_STATUS,  # Requires booking_id
    Action.CANCEL_UNKNOWN_BOOKING,  # Requires booking_id
}


# ═══════════════════════════════════════════════════════════════════════════════
# Event Validation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class WorkflowEvent:
    """
    Represents an event in the workflow.

    Attributes:
        type: The event type (e.g., "approve_checkpoint", "free_text", "book_item")
        checkpoint_id: For checkpoint-gated events, the target checkpoint
        booking: For booking events, the booking payload
        agent_id: For retry_agent/skip_agent, the target agent
    """

    type: str
    checkpoint_id: str | None = None
    booking: dict[str, Any] | None = None
    agent_id: str | None = None


def validate_event(state: WorkflowState, event: WorkflowEvent) -> None:
    """
    Validate that the event is valid for the current state.

    This is the SINGLE SOURCE OF TRUTH for:
    - Phase-based event validation
    - Checkpoint-based event validation
    - checkpoint_id validation (prevents stale UI approvals)

    determine_action() relies on this validation having passed and does NOT
    re-validate checkpoint_id - it only resolves checkpoint type to action.

    Args:
        state: Current workflow state
        event: Event to validate

    Raises:
        InvalidEventError: If event type not allowed in current state
    """
    # ─────────────────────────────────────────────────────────────────────
    # TERMINAL PHASES: Check first to allow start_new in COMPLETED/FAILED/CANCELLED
    # ─────────────────────────────────────────────────────────────────────
    if state.phase in (Phase.COMPLETED, Phase.FAILED, Phase.CANCELLED):
        if event.type not in {"start_new", "status"}:
            raise InvalidEventError(
                f"Workflow is {state.phase.value}. Only 'start_new' or 'status' allowed."
            )
        return  # Valid - start_new allowed in COMPLETED, FAILED, and CANCELLED

    # Error recovery events (retry_agent, skip_agent) valid during discovery phases
    # Note: start_new is handled above for terminal phases, below for discovery phases
    if event.type in ERROR_RECOVERY_EVENTS:
        if state.phase in (Phase.DISCOVERY_IN_PROGRESS, Phase.DISCOVERY_PLANNING):
            return  # Valid
        # For non-terminal, non-discovery phases, error recovery not allowed
        raise InvalidEventError(
            f"Error recovery event '{event.type}' only valid during discovery or terminal phases"
        )

    # Booking phase: validate against BOOKING_PHASE_EVENTS (not a checkpoint)
    if state.phase == Phase.BOOKING:
        if event.type not in BOOKING_PHASE_EVENTS:
            raise InvalidEventError(
                f"Event '{event.type}' not valid in booking phase. "
                f"Valid events: {sorted(BOOKING_PHASE_EVENTS)}"
            )
        return

    # Checkpoint validation (approval gates)
    if state.checkpoint and state.checkpoint in CHECKPOINT_VALID_EVENTS:
        valid_events = CHECKPOINT_VALID_EVENTS[state.checkpoint]
        if event.type not in valid_events:
            raise InvalidEventError(
                f"Event '{event.type}' not valid at checkpoint '{state.checkpoint}'. "
                f"Valid events: {sorted(valid_events)}"
            )

        # ─────────────────────────────────────────────────────────────────────
        # CHECKPOINT_ID VALIDATION: Prevent stale UI actions
        # ─────────────────────────────────────────────────────────────────────
        # For checkpoint-mutating events, REQUIRE checkpoint_id to match current state.
        # This prevents multi-tab race conditions where stale buttons are clicked.
        if event.type in CHECKPOINT_GATED_EVENTS:
            # Require checkpoint_id for checkpoint-gated events
            if event.checkpoint_id is None:
                raise InvalidEventError(
                    f"Event '{event.type}' requires checkpoint_id. "
                    f"Current checkpoint: '{state.checkpoint}'.",
                    error_code="MISSING_CHECKPOINT_ID",
                )

            # Validate checkpoint_id matches current state
            if event.checkpoint_id != state.checkpoint:
                raise InvalidEventError(
                    f"Stale action: state is at checkpoint '{state.checkpoint}', "
                    f"but event targets '{event.checkpoint_id}'. Refresh to see current state.",
                    error_code="STALE_CHECKPOINT",
                    retry_action={"label": "Refresh", "event": {"type": "status"}},
                )
        return

    # Phase-based validation when checkpoint=None (non-gated states)
    # Prevents booking events from slipping into clarification/discovery phases
    # Note: COMPLETED/FAILED/CANCELLED already handled at top of function
    if state.phase in PHASE_VALID_EVENTS:
        valid_events = PHASE_VALID_EVENTS[state.phase]
        if event.type not in valid_events:
            raise InvalidEventError(
                f"Event '{event.type}' not valid in phase '{state.phase.value}'. "
                f"Valid events: {sorted(valid_events)}"
            )
        return

    # ─────────────────────────────────────────────────────────────────────
    # EXPLICIT FALLBACK: Reject unhandled phase+checkpoint combinations
    # ─────────────────────────────────────────────────────────────────────
    # This catch-all ensures the validator is TOTAL - no silent fall-through.
    # If we reach here, we have an unexpected state (e.g., DISCOVERY_PLANNING
    # with checkpoint=None, which should never happen in normal operation).
    raise InvalidEventError(
        f"Unexpected state: phase={state.phase.value}, checkpoint={state.checkpoint}. "
        f"Event '{event.type}' cannot be validated. This indicates a bug in state management."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Action Validation
# ═══════════════════════════════════════════════════════════════════════════════


def validate_action_for_phase(action: Action, state: WorkflowState) -> Action:
    """
    Validate that action is allowed for current phase.

    For free-text classification (Path B/C), this prevents misclassified
    messages from bypassing phase gating. Returns a safe fallback if invalid.

    Note: This does NOT replace validate_event() for explicit events.
    validate_event() handles event-level validation with checkpoint_id checks.
    This function handles action-level validation for free-text paths.

    Args:
        action: The classified action
        state: Current workflow state

    Returns:
        The action if valid, or ANSWER_QUESTION_IN_CONTEXT as safe fallback
    """
    # Universal actions are always allowed
    if action in UNIVERSAL_ACTIONS:
        return action

    # Check phase-specific valid actions
    phase_actions = PHASE_VALID_ACTIONS.get(state.phase, set())
    if action in phase_actions:
        # Additional checkpoint validation for approval actions
        if action == Action.APPROVE_TRIP_SPEC and state.checkpoint != "trip_spec_approval":
            logger.warning(f"APPROVE_TRIP_SPEC requested but checkpoint={state.checkpoint}")
            return Action.ANSWER_QUESTION_IN_CONTEXT
        if action == Action.APPROVE_ITINERARY and state.checkpoint != "itinerary_approval":
            logger.warning(f"APPROVE_ITINERARY requested but checkpoint={state.checkpoint}")
            return Action.ANSWER_QUESTION_IN_CONTEXT
        return action

    # Action not valid for this phase - return safe fallback
    logger.warning(
        f"Action {action.value} not valid in phase {state.phase.value}. "
        f"Falling back to ANSWER_QUESTION_IN_CONTEXT."
    )
    return Action.ANSWER_QUESTION_IN_CONTEXT


# ═══════════════════════════════════════════════════════════════════════════════
# Booking Payload Validation
# ═══════════════════════════════════════════════════════════════════════════════


def has_valid_booking_payload(event: WorkflowEvent, action: Action) -> bool:
    """
    Validate that event has required booking payload for the action.

    This prevents:
    - Booking without explicit user consent (quote_id proves price was seen)
    - LLM-inferred booking targets (must come from structured UI event)
    - Runtime errors from missing payload

    Args:
        event: The workflow event
        action: The intended action

    Returns:
        True if payload is valid for the action, False otherwise
    """
    if event.booking is None:
        return False

    booking = event.booking

    # Actions requiring booking_id only
    if action in {Action.CANCEL_BOOKING, Action.CHECK_BOOKING_STATUS, Action.CANCEL_UNKNOWN_BOOKING}:
        return booking.get("booking_id") is not None

    # Actions requiring booking_id + quote_id (consent proof)
    if action in {Action.BOOK_SINGLE_ITEM, Action.RETRY_BOOKING}:
        return booking.get("booking_id") is not None and booking.get("quote_id") is not None

    return True  # Unknown action - allow (shouldn't happen)
