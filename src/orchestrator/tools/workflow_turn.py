"""
workflow_turn tool handler for Azure AI Agent Service.

This is the ONLY tool that mutates WorkflowState. It implements the 5-step process:
1. Load state from Cosmos DB (or create new)
2. Validate event against current checkpoint
3. Classify the message (if no event provided)
4. Execute the appropriate phase handler
5. Save state and return response

Per design doc Tool Definitions and workflow_turn Internal Implementation sections.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from src.orchestrator.models.conversation import AgentConversation
from src.orchestrator.models.session_ref import SessionRef
from src.orchestrator.models.workflow_state import Phase, WorkflowState
from src.orchestrator.session_manager import SessionManager, SessionManagerResult
from src.orchestrator.state_gating import (
    Action,
    InvalidEventError,
    WorkflowEvent,
    validate_action_for_phase,
    validate_event,
)
from src.orchestrator.storage import (
    BookingIndexStoreProtocol,
    BookingStoreProtocol,
    ConflictError,
    ConsultationIndexStoreProtocol,
    ConsultationSummaryStoreProtocol,
    ItineraryStoreProtocol,
    WorkflowStateData,
    WorkflowStateStoreProtocol,
)
from src.orchestrator.utils import generate_consultation_id, generate_session_id

# Handler imports
from src.orchestrator.handlers.booking import BookingHandler
from src.orchestrator.handlers.clarification import ClarificationHandler
from src.orchestrator.handlers.discovery import DiscoveryHandler

# Storage imports for discovery job cancellation
from src.orchestrator.storage import (
    DiscoveryJobStoreProtocol,
    JobStatus,
)

# Utility intent detection
from src.orchestrator.tools.utility_intent import (
    is_utility_message,
    extract_utility_intent,
    UtilityMatch,
)

# Heuristic and LLM classification for free-text messages
from src.orchestrator.classification import heuristic_classify, llm_classify

# Authorization helpers (MVP mode allows all when user=None)
from src.orchestrator.auth import (
    AuthenticatedUser,
    authorize_workflow_mutation,
)

if TYPE_CHECKING:
    from src.orchestrator.booking.service import BookingService
    from src.shared.a2a.client_wrapper import A2AClientWrapper
    from src.shared.a2a.registry import AgentRegistry
    from src.shared.storage import WorkflowStoreProtocol

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Tool Response Envelope
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ToolResponse:
    """
    Standard response envelope for all orchestrator tools.

    Per design doc, all tools return this envelope for consistent client handling.
    The UI uses the status, message, and ui fields to render appropriate feedback.

    Attributes:
        success: Whether the operation succeeded
        message: Human-readable message for the user
        status: Current workflow status (for UI state tracking)
        data: Additional response data (tool-specific)
        ui: UI components to render (actions, cards, etc.)
        error_code: Machine-readable error code (if success=False)
    """

    success: bool = True
    message: str = ""
    status: dict[str, Any] | None = None
    data: dict[str, Any] | None = None
    ui: dict[str, Any] | None = None
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "success": self.success,
            "message": self.message,
        }
        if self.status is not None:
            result["status"] = self.status
        if self.data is not None:
            result["data"] = self.data
        if self.ui is not None:
            result["ui"] = self.ui
        if self.error_code is not None:
            result["error_code"] = self.error_code
        return result

    @classmethod
    def error(
        cls,
        message: str,
        error_code: str | None = None,
        retry_action: dict[str, Any] | None = None,
    ) -> "ToolResponse":
        """Create an error response."""
        ui = None
        if retry_action:
            ui = {"actions": [retry_action]}
        return cls(
            success=False,
            message=message,
            error_code=error_code,
            ui=ui,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Input Parsing Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def parse_session_ref(session_ref_data: dict[str, Any] | None) -> SessionRef:
    """Parse session_ref from tool arguments.

    Args:
        session_ref_data: Optional dict with session_id, consultation_id, etc.

    Returns:
        SessionRef instance (may have all None fields if no data provided)
    """
    if session_ref_data is None:
        return SessionRef()

    return SessionRef(
        session_id=session_ref_data.get("session_id"),
        consultation_id=session_ref_data.get("consultation_id"),
        itinerary_id=session_ref_data.get("itinerary_id"),
        booking_id=session_ref_data.get("booking_id"),
    )


def parse_event(event_data: dict[str, Any] | None) -> WorkflowEvent | None:
    """Parse event from tool arguments.

    Args:
        event_data: Optional dict with event type and optional fields

    Returns:
        WorkflowEvent instance or None if no event provided
    """
    if event_data is None:
        return None

    event_type = event_data.get("type")
    if not event_type:
        return None

    return WorkflowEvent(
        type=event_type,
        checkpoint_id=event_data.get("checkpoint_id"),
        booking=event_data.get("booking"),
        agent_id=event_data.get("agent"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Workflow Turn Context
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class WorkflowTurnContext:
    """
    Context object holding dependencies for workflow_turn execution.

    This allows workflow_turn to be called with different storage backends
    (Cosmos DB for production, in-memory for testing) via dependency injection.

    Note: This is the legacy context using individual store protocols.
    For new code, prefer UnifiedWorkflowTurnContext which uses WorkflowStoreProtocol.
    """

    workflow_state_store: WorkflowStateStoreProtocol
    consultation_index_store: ConsultationIndexStoreProtocol
    itinerary_store: ItineraryStoreProtocol
    booking_store: BookingStoreProtocol
    booking_index_store: BookingIndexStoreProtocol
    consultation_summary_store: ConsultationSummaryStoreProtocol | None = None

    # Discovery jobs store for progress tracking (optional)
    discovery_job_store: DiscoveryJobStoreProtocol | None = None

    # A2A client and registry for agent communication (optional)
    a2a_client: "A2AClientWrapper | None" = None
    agent_registry: "AgentRegistry | None" = None

    def create_session_manager(self) -> SessionManager:
        """Create a SessionManager with the configured stores."""
        return SessionManager(
            workflow_state_store=self.workflow_state_store,
            consultation_index_store=self.consultation_index_store,
            itinerary_store=self.itinerary_store,
            booking_store=self.booking_store,
            booking_index_store=self.booking_index_store,
        )


@dataclass
class UnifiedWorkflowTurnContext:
    """
    Context object for workflow_turn using unified WorkflowStoreProtocol.

    Per design doc Compatibility & Migration section:
    - Uses WorkflowStoreProtocol for storage-backend agnostic access
    - STORAGE_BACKEND env var controls backend selection at runtime
    - All orchestrator code depends only on protocols, not implementations

    This is the recommended context for new code. It uses a single protocol
    interface instead of multiple individual store protocols.
    """

    workflow_store: "WorkflowStoreProtocol"

    # Optional stores for booking/itinerary operations (Phase 2/3)
    itinerary_store: ItineraryStoreProtocol | None = None
    booking_store: BookingStoreProtocol | None = None
    consultation_summary_store: ConsultationSummaryStoreProtocol | None = None

    # Discovery jobs store for progress tracking (optional)
    discovery_job_store: DiscoveryJobStoreProtocol | None = None

    # A2A client and registry for agent communication (optional)
    a2a_client: "A2AClientWrapper | None" = None
    agent_registry: "AgentRegistry | None" = None


# Global context for workflow_turn (set during orchestrator initialization)
_workflow_turn_context: WorkflowTurnContext | None = None
_unified_workflow_turn_context: UnifiedWorkflowTurnContext | None = None


def set_workflow_turn_context(context: WorkflowTurnContext) -> None:
    """Set the global workflow turn context.

    This should be called during orchestrator initialization to configure
    the storage backends for workflow_turn.
    """
    global _workflow_turn_context
    _workflow_turn_context = context


def set_unified_workflow_turn_context(context: UnifiedWorkflowTurnContext) -> None:
    """Set the unified global workflow turn context.

    This should be called during orchestrator initialization to configure
    the WorkflowStoreProtocol for workflow_turn.

    Per design doc Compatibility & Migration section, this context uses
    the unified WorkflowStoreProtocol which provides all storage operations
    through a single interface.
    """
    global _unified_workflow_turn_context
    _unified_workflow_turn_context = context


def get_workflow_turn_context() -> WorkflowTurnContext | None:
    """Get the current workflow turn context."""
    return _workflow_turn_context


def get_unified_workflow_turn_context() -> UnifiedWorkflowTurnContext | None:
    """Get the unified workflow turn context."""
    return _unified_workflow_turn_context


# ═══════════════════════════════════════════════════════════════════════════════
# Workflow Turn Handler
# ═══════════════════════════════════════════════════════════════════════════════


async def workflow_turn(
    session_ref: dict[str, Any] | SessionRef | None = None,
    message: str = "",
    event: dict[str, Any] | WorkflowEvent | None = None,
) -> ToolResponse:
    """
    The core workflow handler. All stateful workflow operations flow through here.

    This is the ONLY tool that mutates WorkflowState. It implements the 5-step process:
    1. Load state from Cosmos DB (or create new)
    2. Validate event against current checkpoint
    3. Classify the message (if no event provided)
    4. Execute the appropriate phase handler
    5. Save state and return response

    This convenience function uses the global workflow turn context set via
    set_workflow_turn_context(). For explicit dependency injection, use
    workflow_turn_with_stores() instead.

    Args:
        session_ref: Identifies which workflow to load/resume
            - session_id: Frontend conversation/session id
            - consultation_id: Business workflow id (non-guessable)
            - itinerary_id: Approved itinerary id (user-facing)
            - booking_id: Individual booking id
        message: Raw user text (always required)
        event: Structured event from frontend (optional, preferred when available)
            - type: Event type (approve_checkpoint, book_item, etc.)
            - checkpoint_id: For approval events, must match current checkpoint
            - booking: For booking events, contains booking_id and quote_id

    Returns:
        ToolResponse envelope with status, message, and optional UI components

    Per design doc:
    - If no session exists and trip intent detected → start new workflow
    - If session exists → route based on current phase and checkpoint
    - For non-action messages (questions, utilities) → call other tools WITH context
    - State mutations only happen for workflow actions
    """
    # First check for unified context (preferred per design doc Compatibility section)
    unified_context = get_unified_workflow_turn_context()
    if unified_context is not None:
        return await workflow_turn_with_unified_store(
            session_ref=session_ref,
            message=message,
            event=event,
            workflow_store=unified_context.workflow_store,
            itinerary_store=unified_context.itinerary_store,
            booking_store=unified_context.booking_store,
            consultation_summary_store=unified_context.consultation_summary_store,
            discovery_job_store=unified_context.discovery_job_store,
            a2a_client=unified_context.a2a_client,
            agent_registry=unified_context.agent_registry,
        )

    # Fall back to legacy context (individual stores)
    context = get_workflow_turn_context()
    if context is not None:
        return await workflow_turn_with_stores(
            session_ref=session_ref,
            message=message,
            event=event,
            workflow_state_store=context.workflow_state_store,
            consultation_index_store=context.consultation_index_store,
            itinerary_store=context.itinerary_store,
            booking_store=context.booking_store,
            booking_index_store=context.booking_index_store,
            consultation_summary_store=context.consultation_summary_store,
            discovery_job_store=context.discovery_job_store,
            a2a_client=context.a2a_client,
            agent_registry=context.agent_registry,
        )

    # Fall back to stub implementation when no context is configured
    # This allows backward compatibility with existing tests
    return await _workflow_turn_stub(session_ref, message, event)


async def workflow_turn_with_stores(
    session_ref: dict[str, Any] | SessionRef | None = None,
    message: str = "",
    event: dict[str, Any] | WorkflowEvent | None = None,
    *,
    workflow_state_store: WorkflowStateStoreProtocol,
    consultation_index_store: ConsultationIndexStoreProtocol,
    itinerary_store: ItineraryStoreProtocol,
    booking_store: BookingStoreProtocol,
    booking_index_store: BookingIndexStoreProtocol,
    consultation_summary_store: ConsultationSummaryStoreProtocol | None = None,
    discovery_job_store: DiscoveryJobStoreProtocol | None = None,
    a2a_client: "A2AClientWrapper | None" = None,
    agent_registry: "AgentRegistry | None" = None,
) -> ToolResponse:
    """
    The core workflow handler with explicit store dependencies.

    This implements the 5-step process:
    1. Load state from store (or create new)
    2. Validate event against current checkpoint
    3. Classify the message (if no event provided)
    4. Execute the appropriate phase handler
    5. Save state and return response

    Args:
        session_ref: Identifies which workflow to load/resume
        message: Raw user text (always required)
        event: Structured event from frontend (optional)
        workflow_state_store: Store for WorkflowState persistence
        consultation_index_store: Store for consultation_id -> session_id lookup
        itinerary_store: Store for Itinerary persistence
        booking_store: Store for Booking persistence
        booking_index_store: Store for booking_id -> session_id lookup
        consultation_summary_store: Optional store for consultation summaries
        discovery_job_store: Optional store for discovery job tracking
        a2a_client: A2A client for agent communication (optional)
        agent_registry: Agent registry for URL lookup (optional)

    Returns:
        ToolResponse envelope with status, message, and optional UI components
    """
    # Normalize inputs
    if isinstance(session_ref, dict):
        session_ref = parse_session_ref(session_ref)
    elif session_ref is None:
        session_ref = SessionRef()

    if isinstance(event, dict):
        event = parse_event(event)

    # Validate message is provided
    if not message:
        return ToolResponse.error(
            message="Message is required for workflow_turn",
            error_code="MISSING_MESSAGE",
        )

    logger.info(
        "workflow_turn called with session_ref=%s, message=%s, event=%s",
        session_ref.to_dict() if session_ref.has_any_id() else "None",
        message[:50] + "..." if len(message) > 50 else message,
        event.type if event else "None",
    )

    # Create session manager with injected stores
    session_manager = SessionManager(
        workflow_state_store=workflow_state_store,
        consultation_index_store=consultation_index_store,
        itinerary_store=itinerary_store,
        booking_store=booking_store,
        booking_index_store=booking_index_store,
    )

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 1: LOAD STATE
    # ═══════════════════════════════════════════════════════════════════════
    try:
        # Generate a new session_id if none provided
        new_session_id = session_ref.session_id or generate_session_id()

        manager_result: SessionManagerResult = await session_manager.load_or_create_state(
            session_ref=session_ref,
            new_session_id=new_session_id,
        )

        state_data = manager_result.state
        is_new_state = manager_result.is_new

        # Convert WorkflowStateData to WorkflowState for validation
        state = _state_data_to_workflow_state(state_data)

        logger.info(
            "State loaded: session_id=%s, is_new=%s, phase=%s",
            state.session_id,
            is_new_state,
            state.phase.value,
        )

    except Exception as e:
        logger.error(f"Error loading state: {e}")
        return ToolResponse.error(
            message="Failed to load workflow state. The session may have expired.",
            error_code="SESSION_EXPIRED",
            retry_action={"label": "Start New", "event": {"type": "start_new"}},
        )

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 1b: AUTHORIZE MUTATION (MVP mode allows all when user=None)
    # ═══════════════════════════════════════════════════════════════════════
    # Per design doc Authorization Model section:
    # - MVP mode: No auth required, IDs as bearer tokens
    # - Production mode: Would pass AuthenticatedUser from OAuth/Azure AD
    user: AuthenticatedUser | None = None  # MVP mode: no auth required
    auth_result = authorize_workflow_mutation(state, user)
    if not auth_result.allowed:
        logger.warning(
            "Authorization denied: session_id=%s, reason=%s",
            state.session_id,
            auth_result.reason,
        )
        return ToolResponse.error(
            message="You don't have permission to modify this workflow.",
            error_code="UNAUTHORIZED",
        )

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 2: VALIDATE EVENT (phase-appropriate events only)
    # ═══════════════════════════════════════════════════════════════════════
    if event:
        try:
            validate_event(state, event)
        except InvalidEventError as e:
            return ToolResponse.error(
                message=e.message,
                error_code=e.error_code,
                retry_action=e.retry_action,
            )

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 3: DETERMINE ACTION (event-based or classify message)
    # ═══════════════════════════════════════════════════════════════════════
    action = await _determine_action(event, message, state)

    # Validate action is allowed for current phase
    action = validate_action_for_phase(action, state)

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 4: EXECUTE PHASE HANDLER
    # ═══════════════════════════════════════════════════════════════════════
    result, state_data = await _execute_action(
        action, state, state_data, message, event,
        a2a_client=a2a_client,
        agent_registry=agent_registry,
        discovery_job_store=discovery_job_store,
        booking_store=booking_store,
        itinerary_store=itinerary_store,
        consultation_summary_store=consultation_summary_store,
        workflow_store=None,
    )

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 5: SAVE STATE AND RETURN
    # ═══════════════════════════════════════════════════════════════════════
    try:
        # Save state with etag for optimistic locking
        saved_state = await workflow_state_store.save_state(
            state_data,
            if_match=state_data.etag,  # Use etag for concurrency control
        )

        # Update state_data with new etag for potential future operations
        state_data.etag = saved_state.etag

        logger.info(
            "State saved: session_id=%s, new_etag=%s",
            state_data.session_id,
            saved_state.etag,
        )

    except ConflictError as e:
        # Concurrent modification detected - return error for client to retry
        logger.warning(f"Concurrent modification detected: {e}")
        return ToolResponse.error(
            message="Another request modified this workflow. Please refresh and try again.",
            error_code="CONCURRENCY_CONFLICT",
            retry_action={"label": "Refresh", "event": {"type": "status"}},
        )
    except Exception as e:
        logger.error(f"Error saving state: {e}")
        return ToolResponse.error(
            message="Failed to save workflow state. Please try again.",
            error_code="SAVE_FAILED",
        )

    return result


async def workflow_turn_with_unified_store(
    session_ref: dict[str, Any] | SessionRef | None = None,
    message: str = "",
    event: dict[str, Any] | WorkflowEvent | None = None,
    *,
    workflow_store: "WorkflowStoreProtocol",
    itinerary_store: ItineraryStoreProtocol | None = None,
    booking_store: BookingStoreProtocol | None = None,
    consultation_summary_store: ConsultationSummaryStoreProtocol | None = None,
    discovery_job_store: DiscoveryJobStoreProtocol | None = None,
    a2a_client: "A2AClientWrapper | None" = None,
    agent_registry: "AgentRegistry | None" = None,
) -> ToolResponse:
    """
    The core workflow handler using unified WorkflowStoreProtocol.

    Per design doc Compatibility & Migration section:
    - Uses WorkflowStoreProtocol for storage-backend agnostic access
    - All lookup/save operations go through the unified protocol
    - Etag handling for optimistic locking

    This implements the 5-step process:
    1. Load state via WorkflowStoreProtocol
    2. Validate event against current checkpoint
    3. Classify the message (if no event provided)
    4. Execute the appropriate phase handler
    5. Save state via WorkflowStoreProtocol and return response

    Args:
        session_ref: Identifies which workflow to load/resume
        message: Raw user text (always required)
        event: Structured event from frontend (optional)
        workflow_store: WorkflowStoreProtocol instance for state management
        itinerary_store: Optional itinerary store for booking/discovery persistence
        booking_store: Optional booking store for booking operations
        consultation_summary_store: Optional consultation summary store for completion updates
        discovery_job_store: Optional store for discovery job tracking
        a2a_client: A2A client for agent communication (optional)
        agent_registry: Agent registry for URL lookup (optional)

    Returns:
        ToolResponse envelope with status, message, and optional UI components
    """
    from src.orchestrator.session_manager import (
        UnifiedSessionManager,
        UnifiedSessionManagerResult,
    )
    from src.shared.storage import WorkflowStoreProtocol, ConflictError as UnifiedConflictError

    # Normalize inputs
    if isinstance(session_ref, dict):
        session_ref = parse_session_ref(session_ref)
    elif session_ref is None:
        session_ref = SessionRef()

    if isinstance(event, dict):
        event = parse_event(event)

    # Validate message is provided
    if not message:
        return ToolResponse.error(
            message="Message is required for workflow_turn",
            error_code="MISSING_MESSAGE",
        )

    logger.info(
        "workflow_turn (unified) called with session_ref=%s, message=%s, event=%s",
        session_ref.to_dict() if session_ref.has_any_id() else "None",
        message[:50] + "..." if len(message) > 50 else message,
        event.type if event else "None",
    )

    # Create unified session manager
    session_manager = UnifiedSessionManager(workflow_store=workflow_store)

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 1: LOAD STATE
    # ═══════════════════════════════════════════════════════════════════════
    try:
        # Generate a new session_id if none provided
        new_session_id = session_ref.session_id or generate_session_id()

        manager_result: UnifiedSessionManagerResult = (
            await session_manager.load_or_create_state(
                session_ref=session_ref,
                new_session_id=new_session_id,
            )
        )

        state = manager_result.state
        is_new_state = manager_result.is_new
        current_etag = manager_result.etag

        logger.info(
            "State loaded (unified): session_id=%s, is_new=%s, phase=%s",
            state.session_id,
            is_new_state,
            state.phase.value,
        )

    except Exception as e:
        logger.error(f"Error loading state: {e}")
        return ToolResponse.error(
            message="Failed to load workflow state. The session may have expired.",
            error_code="SESSION_EXPIRED",
            retry_action={"label": "Start New", "event": {"type": "start_new"}},
        )

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 1b: AUTHORIZE MUTATION (MVP mode allows all when user=None)
    # ═══════════════════════════════════════════════════════════════════════
    # Per design doc Authorization Model section:
    # - MVP mode: No auth required, IDs as bearer tokens
    # - Production mode: Would pass AuthenticatedUser from OAuth/Azure AD
    user: AuthenticatedUser | None = None  # MVP mode: no auth required
    auth_result = authorize_workflow_mutation(state, user)
    if not auth_result.allowed:
        logger.warning(
            "Authorization denied (unified): session_id=%s, reason=%s",
            state.session_id,
            auth_result.reason,
        )
        return ToolResponse.error(
            message="You don't have permission to modify this workflow.",
            error_code="UNAUTHORIZED",
        )

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 2: VALIDATE EVENT (phase-appropriate events only)
    # ═══════════════════════════════════════════════════════════════════════
    if event:
        try:
            validate_event(state, event)
        except InvalidEventError as e:
            return ToolResponse.error(
                message=e.message,
                error_code=e.error_code,
                retry_action=e.retry_action,
            )

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 3: DETERMINE ACTION (event-based or classify message)
    # ═══════════════════════════════════════════════════════════════════════
    action = await _determine_action(event, message, state)

    # Validate action is allowed for current phase
    action = validate_action_for_phase(action, state)

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 4: EXECUTE PHASE HANDLER
    # ═══════════════════════════════════════════════════════════════════════
    # For unified store, we work directly with WorkflowState (domain model)
    # Convert to state_data for handlers that still expect it
    state_data = _workflow_state_to_state_data_for_unified(state)

    result, updated_state_data = await _execute_action(
        action, state, state_data, message, event,
        a2a_client=a2a_client,
        agent_registry=agent_registry,
        discovery_job_store=discovery_job_store,
        booking_store=booking_store,
        itinerary_store=itinerary_store,
        consultation_summary_store=consultation_summary_store,
        workflow_store=workflow_store,
    )

    # Sync state_data changes back to state
    state = _sync_state_data_to_workflow_state(state, updated_state_data)

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 5: SAVE STATE AND RETURN
    # ═══════════════════════════════════════════════════════════════════════
    try:
        # Save state with etag for optimistic locking
        new_etag = await workflow_store.save(state, etag=current_etag)

        # Update state with new etag for potential future operations
        state.etag = new_etag

        logger.info(
            "State saved (unified): session_id=%s, new_etag=%s",
            state.session_id,
            new_etag,
        )

    except UnifiedConflictError as e:
        # Concurrent modification detected - return error for client to retry
        logger.warning(f"Concurrent modification detected (unified): {e}")
        return ToolResponse.error(
            message="Another request modified this workflow. Please refresh and try again.",
            error_code="CONCURRENCY_CONFLICT",
            retry_action={"label": "Refresh", "event": {"type": "status"}},
        )
    except Exception as e:
        logger.error(f"Error saving state (unified): {e}")
        return ToolResponse.error(
            message="Failed to save workflow state. Please try again.",
            error_code="SAVE_FAILED",
        )

    return result


def _workflow_state_to_state_data_for_unified(
    state: WorkflowState,
) -> WorkflowStateData:
    """Convert WorkflowState to WorkflowStateData for handler compatibility.

    Handlers still expect WorkflowStateData for now. This creates a compatible
    WorkflowStateData from the WorkflowState domain model.

    Args:
        state: WorkflowState domain model

    Returns:
        WorkflowStateData compatible with handlers
    """
    return WorkflowStateData(
        session_id=state.session_id,
        consultation_id=state.consultation_id,
        phase=state.phase.value if isinstance(state.phase, Phase) else str(state.phase),
        checkpoint=state.checkpoint,
        current_step=state.current_step,
        itinerary_id=state.itinerary_id,
        workflow_version=state.workflow_version,
        agent_context_ids={
            name: agent_state.to_dict()
            for name, agent_state in state.agent_context_ids.items()
        },
        created_at=state.created_at,
        updated_at=state.updated_at,
        etag=state.etag,
    )


def _sync_state_data_to_workflow_state(
    state: WorkflowState,
    state_data: WorkflowStateData,
) -> WorkflowState:
    """Sync WorkflowStateData changes back to WorkflowState.

    After handler execution, state_data may have been modified. This syncs
    those changes back to the WorkflowState domain model.

    Args:
        state: Original WorkflowState
        state_data: Modified WorkflowStateData from handler

    Returns:
        Updated WorkflowState with changes from state_data
    """
    from src.orchestrator.models.workflow_state import AgentA2AState

    # Update phase
    phase_str = state_data.phase.upper() if state_data.phase else "CLARIFICATION"
    try:
        state.phase = Phase[phase_str]
    except KeyError:
        state.phase = Phase.CLARIFICATION

    # Update checkpoint and current_step
    state.checkpoint = state_data.checkpoint
    state.current_step = state_data.current_step or "gathering"

    # Update itinerary_id
    state.itinerary_id = state_data.itinerary_id

    # Update agent_context_ids
    state.agent_context_ids = {
        name: AgentA2AState.from_dict(data)
        for name, data in state_data.agent_context_ids.items()
    }

    # Update timestamp
    state.updated_at = state_data.updated_at

    return state


async def _workflow_turn_stub(
    session_ref: dict[str, Any] | SessionRef | None = None,
    message: str = "",
    event: dict[str, Any] | WorkflowEvent | None = None,
) -> ToolResponse:
    """
    Stub implementation for workflow_turn when no context is configured.

    This maintains backward compatibility with tests that don't configure
    the workflow turn context.
    """
    # Normalize inputs
    if isinstance(session_ref, dict):
        session_ref = parse_session_ref(session_ref)
    elif session_ref is None:
        session_ref = SessionRef()

    if isinstance(event, dict):
        event = parse_event(event)

    # Validate message is provided
    if not message:
        return ToolResponse.error(
            message="Message is required for workflow_turn",
            error_code="MISSING_MESSAGE",
        )

    logger.info(
        "workflow_turn (stub) called with session_ref=%s, message=%s, event=%s",
        session_ref.to_dict() if session_ref.has_any_id() else "None",
        message[:50] + "..." if len(message) > 50 else message,
        event.type if event else "None",
    )

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 1: LOAD STATE (stub)
    # ═══════════════════════════════════════════════════════════════════════
    try:
        state = await _load_or_create_state_stub(session_ref)
    except StateNotFoundError as e:
        return ToolResponse.error(
            message=str(e),
            error_code="SESSION_EXPIRED",
            retry_action={"label": "Start New", "event": {"type": "start_new"}},
        )

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 2: VALIDATE EVENT (phase-appropriate events only)
    # ═══════════════════════════════════════════════════════════════════════
    if event:
        try:
            validate_event(state, event)
        except InvalidEventError as e:
            return ToolResponse.error(
                message=e.message,
                error_code=e.error_code,
                retry_action=e.retry_action,
            )

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 3: DETERMINE ACTION (event-based or classify message)
    # ═══════════════════════════════════════════════════════════════════════
    action = await _determine_action(event, message, state)

    # Validate action is allowed for current phase
    action = validate_action_for_phase(action, state)

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 4: EXECUTE PHASE HANDLER (stub)
    # ═══════════════════════════════════════════════════════════════════════
    result = await _execute_action_stub(action, state, message, event)

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 5: SAVE STATE (stub - no actual saving)
    # ═══════════════════════════════════════════════════════════════════════

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# State Conversion Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _state_data_to_workflow_state(state_data: WorkflowStateData) -> WorkflowState:
    """Convert WorkflowStateData to WorkflowState for validation.

    WorkflowStateData is the storage representation, while WorkflowState
    is the domain model used for validation and business logic.

    Args:
        state_data: Storage data class

    Returns:
        WorkflowState domain model
    """
    # Parse phase from string
    phase_str = state_data.phase.upper() if state_data.phase else "CLARIFICATION"
    try:
        phase = Phase[phase_str]
    except KeyError:
        logger.warning(f"Unknown phase '{state_data.phase}', defaulting to CLARIFICATION")
        phase = Phase.CLARIFICATION

    return WorkflowState(
        session_id=state_data.session_id,
        consultation_id=state_data.consultation_id,
        phase=phase,
        checkpoint=state_data.checkpoint,
        workflow_version=state_data.workflow_version,
    )


def _workflow_state_to_state_data(
    state: WorkflowState,
    state_data: WorkflowStateData,
) -> WorkflowStateData:
    """Update WorkflowStateData from WorkflowState changes.

    Args:
        state: Domain model with potential changes
        state_data: Storage data to update

    Returns:
        Updated storage data
    """
    state_data.phase = state.phase.value if isinstance(state.phase, Phase) else str(state.phase)
    state_data.checkpoint = state.checkpoint
    state_data.workflow_version = state.workflow_version
    state_data.updated_at = datetime.now(timezone.utc)
    return state_data


# ═══════════════════════════════════════════════════════════════════════════════
# Stub Implementations (backward compatibility for tests without stores)
# ═══════════════════════════════════════════════════════════════════════════════


class StateNotFoundError(Exception):
    """Raised when workflow state cannot be found for provided identifiers."""

    pass


@dataclass
class StubWorkflowState:
    """Minimal stub for WorkflowState for backward compatibility.

    This stub is used when workflow_turn is called without configured stores.
    It provides just enough structure for validate_event and validate_action_for_phase.
    """

    session_id: str | None = None
    consultation_id: str | None = None
    phase: Any = None
    checkpoint: str | None = None
    workflow_version: int = 1


async def _load_or_create_state_stub(session_ref: SessionRef) -> StubWorkflowState:
    """Stub for load_or_create_state when no stores are configured.

    For now, creates a minimal stub state for validation testing.
    """
    # If session_ref has identifiers, we would look up state
    # For now, return a stub new state in CLARIFICATION phase
    return StubWorkflowState(
        session_id=session_ref.session_id or "stub_session",
        consultation_id=session_ref.consultation_id,
        phase=Phase.CLARIFICATION,
        checkpoint=None,
    )


async def _execute_action(
    action: Action,
    state: WorkflowState,
    state_data: WorkflowStateData,
    message: str,
    event: WorkflowEvent | None,
    a2a_client: "A2AClientWrapper | None" = None,
    agent_registry: "AgentRegistry | None" = None,
    discovery_job_store: DiscoveryJobStoreProtocol | None = None,
    booking_store: BookingStoreProtocol | None = None,
    itinerary_store: ItineraryStoreProtocol | None = None,
    consultation_summary_store: ConsultationSummaryStoreProtocol | None = None,
    workflow_store: "WorkflowStoreProtocol | None" = None,
) -> tuple[ToolResponse, WorkflowStateData]:
    """Execute action and return response with updated state.

    This is the main action dispatcher. Routes actions to phase-specific
    handlers based on current workflow phase.

    Args:
        action: The action to execute
        state: Current workflow state (domain model)
        state_data: Current workflow state data (storage model)
        message: Raw user message
        event: Optional structured event
        a2a_client: A2A client for agent communication (optional)
        agent_registry: Agent registry for URL lookup (optional)
        discovery_job_store: Optional store for discovery job tracking
        booking_store: Optional store for booking persistence
        itinerary_store: Optional store for itinerary persistence
        consultation_summary_store: Optional store for consultation summaries
        workflow_store: Optional workflow store for background discovery

    Returns:
        Tuple of (ToolResponse, updated WorkflowStateData)
    """
    # Build status dict for response
    status: dict[str, Any] = {
        "phase": state.phase.value,
        "session_id": state.session_id,
    }
    if state.consultation_id:
        status["consultation_id"] = state.consultation_id
    if state.checkpoint:
        status["checkpoint"] = state.checkpoint

    # Update state_data timestamp for any action
    state_data.updated_at = datetime.now(timezone.utc)

    # Track if this is a new session (before any state modifications)
    is_new_session = state_data.etag is None

    # ─────────────────────────────────────────────────────────────────────
    # UNIVERSAL ACTIONS: Handle CALL_UTILITY before phase-specific routing
    # ─────────────────────────────────────────────────────────────────────
    # Per design doc: CALL_UTILITY is a universal action that doesn't mutate
    # state. It should be handled here regardless of the current phase.
    if action == Action.CALL_UTILITY:
        utility_response = await handle_utility_with_context(
            state,
            message,
            booking_store=booking_store,
            consultation_summary_store=consultation_summary_store,
        )
        response = ToolResponse(
            success=True,
            message=utility_response,
            status=status,
            data={
                "action": action.value,
                "is_new_session": is_new_session,
                "utility_result": utility_response,
            },
        )
        # State unchanged for utility calls - return as-is
        return response, state_data

    # ─────────────────────────────────────────────────────────────────────
    # ANSWER_QUESTION_IN_CONTEXT: Answer question with workflow context
    # ─────────────────────────────────────────────────────────────────────
    # Per design doc (workflow_turn Internal Implementation, Example 2):
    # - Questions are answered using answer_question tool WITH context
    # - WorkflowState remains unchanged (read-only action)
    # - Response includes checkpoint re-prompt when at a checkpoint
    if action == Action.ANSWER_QUESTION_IN_CONTEXT:
        return await handle_question_with_context(
            state=state,
            state_data=state_data,
            message=message,
            status=status,
            is_new_session=is_new_session,
            a2a_client=a2a_client,
            agent_registry=agent_registry,
        )

    # ─────────────────────────────────────────────────────────────────────
    # GET_STATUS: Universal action, read-only, returns phase-specific status
    # ─────────────────────────────────────────────────────────────────────
    # Per design doc: GET_STATUS is a universal action that doesn't mutate state.
    # Returns phase-specific status payloads for CLI /status and UI refresh.
    if action == Action.GET_STATUS:
        # Get optional dependencies for status enrichment
        context = get_workflow_turn_context()
        booking_service = None  # Will be None if not configured

        # Prefer explicitly provided stores (workflow_turn_with_* parameters)
        if booking_store and itinerary_store:
            try:
                from src.orchestrator.booking.service import BookingService
                booking_service = BookingService(
                    booking_store=booking_store,
                    itinerary_store=itinerary_store,
                )
            except Exception as e:
                logger.warning(
                    f"Could not create BookingService for status (explicit stores): {e}"
                )
        # Fall back to global context if available
        elif context:
            try:
                from src.orchestrator.booking.service import BookingService
                booking_service = BookingService(
                    booking_store=context.booking_store,
                    itinerary_store=context.itinerary_store,
                )
            except Exception as e:
                logger.warning(f"Could not create BookingService for status: {e}")

        return await handle_get_status(
            state=state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
            booking_service=booking_service,
        )

    # ─────────────────────────────────────────────────────────────────────
    # TERMINAL ACTIONS: CANCEL_WORKFLOW and START_NEW_WORKFLOW
    # ─────────────────────────────────────────────────────────────────────
    # Per design doc: cancel_workflow sets phase=CANCELLED, start_new resets
    # and starts fresh workflow. These are handled here before phase routing
    # as they apply universally (cancel from any non-terminal, start_new from terminal).

    if action == Action.CANCEL_WORKFLOW:
        # Get context for consultation index store (needed only if we have it)
        context = get_workflow_turn_context()
        # Note: discovery_job_store may be None; cancellation is best-effort.
        return await handle_cancel_workflow(
            state=state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

    if action == Action.START_NEW_WORKFLOW:
        # Get context for consultation index store
        context = get_workflow_turn_context()
        if context is None:
            return ToolResponse.error(
                message="Cannot start new workflow: context not configured.",
                error_code="CONFIGURATION_ERROR",
            ), state_data

        return await handle_start_new_workflow(
            state=state,
            state_data=state_data,
            consultation_index_store=context.consultation_index_store,
        )

    # Route to phase-specific handler
    if state.phase == Phase.CLARIFICATION:
        # Use ClarificationHandler for CLARIFICATION phase
        handler = ClarificationHandler(
            state=state,
            state_data=state_data,
            a2a_client=a2a_client,
            agent_registry=agent_registry,
            discovery_job_store=discovery_job_store,
            workflow_store=workflow_store,
        )
        result = await handler.execute(action, message, event)

        # Convert handler response to ToolResponse with status and is_new_session
        tool_response = _convert_handler_response(
            result.response, status, is_new_session=is_new_session
        )
        return tool_response, result.state_data

    # Use DiscoveryHandler for DISCOVERY phases
    if state.phase in (Phase.DISCOVERY_IN_PROGRESS, Phase.DISCOVERY_PLANNING):
        handler = DiscoveryHandler(
            state=state,
            state_data=state_data,
            a2a_client=a2a_client,
            agent_registry=agent_registry,
            discovery_job_store=discovery_job_store,
            workflow_store=workflow_store,
            itinerary_store=itinerary_store,
            booking_store=booking_store,
            consultation_summary_store=consultation_summary_store,
        )
        result = await handler.execute(action, message, event)

        # Convert handler response to ToolResponse with status and is_new_session
        tool_response = _convert_handler_response(
            result.response, status, is_new_session=is_new_session
        )
        return tool_response, result.state_data

    # Use BookingHandler for BOOKING phase
    if state.phase == Phase.BOOKING:
        handler = BookingHandler(
            state=state,
            state_data=state_data,
            booking_store=booking_store,
            itinerary_store=itinerary_store,
            consultation_summary_store=consultation_summary_store,
        )
        result = await handler.execute(action, message, event)

        tool_response = _convert_handler_response(
            result.response, status, is_new_session=is_new_session
        )
        return tool_response, result.state_data

    # For terminal phases (COMPLETED, FAILED, CANCELLED), return acknowledgment
    response = ToolResponse(
        success=True,
        message=f"Received message in {status['phase']} phase. Action: {action.value}",
        status=status,
        data={
            "action": action.value,
            "event_type": event.type if event else None,
            "is_new_session": state_data.etag is None,  # No etag = newly created
        },
    )

    return response, state_data


def _convert_handler_response(
    handler_response: "ToolResponse",
    status: dict[str, Any],
    is_new_session: bool = False,
) -> ToolResponse:
    """
    Convert handler response to workflow_turn ToolResponse format.

    Merges status information into the response.

    Args:
        handler_response: Response from the phase handler
        status: Status dict with phase, session_id, etc.
        is_new_session: Whether this is a newly created session
    """
    from src.orchestrator.models.responses import ToolResponse as ResponseModelToolResponse

    # If the handler returned a ToolResponse from models.responses, convert it
    if isinstance(handler_response, ResponseModelToolResponse):
        # Convert UIDirective to dict for workflow_turn's ToolResponse
        ui_dict = handler_response.ui.to_dict() if handler_response.ui else None

        # Merge is_new_session into data
        data = handler_response.data.copy() if handler_response.data else {}
        data["is_new_session"] = is_new_session

        return ToolResponse(
            success=handler_response.success,
            message=handler_response.message,
            status=status,
            data=data,
            ui=ui_dict,
        )

    # If it's already workflow_turn's ToolResponse, add status and is_new_session
    if handler_response.status is None:
        handler_response.status = status

    # Add is_new_session to data
    if handler_response.data is None:
        handler_response.data = {}
    handler_response.data["is_new_session"] = is_new_session

    return handler_response


async def _determine_action(
    event: WorkflowEvent | None,
    message: str,
    state: WorkflowState | StubWorkflowState,
) -> Action:
    """Determine action from event or classify message.

    Per design doc (workflow_turn Internal Implementation, Step 3):
    - Path A: Explicit event → direct mapping
    - Path B: Heuristic classification (fast, no LLM cost)
    - Path C: LLM fallback (for ambiguous messages)

    Args:
        event: Structured event (preferred path - no classification needed)
        message: Raw user message (needs classification if no event)
        state: Current workflow state

    Returns:
        Action enum value
    """
    # Path A: Structured event → map to action
    if event:
        return _event_to_action(event, state)

    # ─────────────────────────────────────────────────────────────────────
    # UTILITY DETECTION: Context-aware utility calls (Layer 2)
    # ─────────────────────────────────────────────────────────────────────
    # Check for utility patterns FIRST. When matched, CALL_UTILITY is returned
    # and the handler will execute the utility with trip context.
    # Example: "What's the weather during my trip?" → uses trip_spec.dates
    if is_utility_message(message):
        return Action.CALL_UTILITY  # Universal, no validation needed

    # ─────────────────────────────────────────────────────────────────────
    # Path B: HEURISTIC CLASSIFICATION (fast path, no LLM cost)
    # ─────────────────────────────────────────────────────────────────────
    # Per design doc Routing Flow (Layer 2a):
    # - Status requests, cancellations, approvals, modifications, questions
    # - Returns None if no confident match (fall through to LLM)
    heuristic_result = heuristic_classify(message, state)
    if heuristic_result.is_classified:
        logger.debug(
            f"Heuristic classification: {heuristic_result.action.value} "
            f"(confidence={heuristic_result.confidence:.2f}, reason={heuristic_result.reason})"
        )
        return heuristic_result.action

    # ─────────────────────────────────────────────────────────────────────
    # Path C: LLM FALLBACK (for ambiguous messages)
    # ─────────────────────────────────────────────────────────────────────
    # Per design doc Routing Flow (Layer 2a): When heuristics return None,
    # use LLM-based classification via Azure AI Agent (Classifier).
    # This handles complex or ambiguous messages that don't match patterns.
    logger.debug(f"No heuristic match, using LLM fallback: {message[:50]}")

    # Convert StubWorkflowState to WorkflowState if needed for LLM classification
    workflow_state = state if isinstance(state, WorkflowState) else None

    # Call LLM classifier
    llm_result = await llm_classify(
        message=message,
        state=workflow_state,
        session_id=getattr(state, 'session_id', None),
    )

    logger.debug(
        f"LLM classification: {llm_result.action.value} "
        f"(confidence={llm_result.confidence:.2f}, reason={llm_result.reason})"
    )

    return llm_result.action


def _event_to_action(
    event: WorkflowEvent,
    state: WorkflowState | StubWorkflowState | None = None,
) -> Action:
    """Map event type to action.

    This is the structured path - events from UI have explicit type.
    For "approve_checkpoint", the specific action depends on the current checkpoint.

    Args:
        event: The workflow event
        state: Current workflow state (used for checkpoint-based resolution)

    Returns:
        Action enum value
    """
    # Handle approve_checkpoint specially - resolve based on current checkpoint
    if event.type == "approve_checkpoint":
        if state and hasattr(state, 'checkpoint') and state.checkpoint:
            if state.checkpoint == "trip_spec_approval":
                return Action.APPROVE_TRIP_SPEC
            elif state.checkpoint == "itinerary_approval":
                return Action.APPROVE_ITINERARY
        # Default to APPROVE_TRIP_SPEC if no checkpoint context
        return Action.APPROVE_TRIP_SPEC

    # Handle free_text - use heuristics (will be called separately)
    if event.type == "free_text":
        # free_text events should fall through to message classification
        # Return CONTINUE_CLARIFICATION as default, but heuristics should handle
        return Action.CONTINUE_CLARIFICATION

    event_action_map: dict[str, Action] = {
        "request_change": Action.REQUEST_MODIFICATION,
        "view_booking_options": Action.VIEW_BOOKING_OPTIONS,
        "book_item": Action.BOOK_SINGLE_ITEM,
        "retry_booking": Action.RETRY_BOOKING,
        "cancel_booking": Action.CANCEL_BOOKING,
        "check_booking_status": Action.CHECK_BOOKING_STATUS,
        "cancel_unknown_booking": Action.CANCEL_UNKNOWN_BOOKING,
        "cancel_workflow": Action.CANCEL_WORKFLOW,
        "status": Action.GET_STATUS,
        "retry_agent": Action.REQUEST_MODIFICATION,      # Re-run specific agent
        "skip_agent": Action.REQUEST_MODIFICATION,       # Skip agent and continue
        "retry_discovery": Action.REQUEST_MODIFICATION,  # Re-run all discovery agents
        "start_new": Action.START_NEW_WORKFLOW,
    }

    return event_action_map.get(event.type, Action.CONTINUE_CLARIFICATION)


async def _execute_action_stub(
    action: Action,
    state: StubWorkflowState | WorkflowState,
    message: str,
    event: WorkflowEvent | None,
) -> ToolResponse:
    """Stub for action execution when no stores are configured.

    This returns a simple acknowledgment. Full handlers will:
    - Call downstream agents via A2A
    - Update workflow state
    - Return appropriate UI components
    """
    # Build status dict for response
    phase_value = state.phase.value if isinstance(state.phase, Phase) else str(state.phase)
    status: dict[str, Any] = {
        "phase": phase_value,
        "session_id": state.session_id,
    }
    if state.consultation_id:
        status["consultation_id"] = state.consultation_id
    if state.checkpoint:
        status["checkpoint"] = state.checkpoint

    return ToolResponse(
        success=True,
        message=f"Received message in {status['phase']} phase. Action: {action.value}",
        status=status,
        data={
            "action": action.value,
            "event_type": event.type if event else None,
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Context-Aware Utility Handler
# ═══════════════════════════════════════════════════════════════════════════════


async def handle_utility_with_context(
    state: WorkflowState | StubWorkflowState,
    message: str,
    *,
    booking_store: BookingStoreProtocol | None = None,
    consultation_summary_store: ConsultationSummaryStoreProtocol | None = None,
) -> str:
    """
    Handle a utility call with trip context (Layer 2).

    Unlike Layer 1b stateless utilities, this enriches utility calls with
    context from WorkflowState. Examples:
    - "What's the weather during my trip?" → uses trip_spec.dates
    - "How much is 100 USD in local currency?" → uses trip_spec.destination
    - "What time is it at my destination?" → uses trip_spec.destination
    - "Show booking book_abc123" → uses booking store lookup
    - "Show consultation cons_xyz789" → uses consultation summary lookup

    Per design doc (workflow_turn Internal Implementation section):
    - Extracts utility intent using extract_utility_intent()
    - Enriches with trip context from WorkflowState
    - Dispatches to appropriate utility tool
    - Returns formatted result string (state unchanged)

    Args:
        state: Current workflow state (contains trip_spec for context)
        message: The user's raw message
        booking_store: Optional booking store for get_booking lookups
        consultation_summary_store: Optional summary store for get_consultation lookups

    Returns:
        Formatted utility result string
    """
    # Import utility tools
    from src.orchestrator.tools.utilities.currency import currency_convert_with_context
    from src.orchestrator.tools.utilities.weather import weather_lookup_with_context
    from src.orchestrator.tools.utilities.timezone import timezone_info_with_context
    from src.orchestrator.tools.lookups import get_booking
    from src.orchestrator.tools.lookups.get_consultation import (
        format_consultation_details,
    )

    # Extract utility intent
    utility_match = extract_utility_intent(message)
    if not utility_match:
        # Shouldn't happen if is_utility_message() returned True, but handle gracefully
        return "I couldn't understand that utility request. Please try rephrasing."

    # ─────────────────────────────────────────────────────────────────────
    # Build context from WorkflowState
    # ─────────────────────────────────────────────────────────────────────
    # Extract trip context from state's trip_spec if available
    destination: str | None = None
    dates: str | None = None

    # WorkflowState has trip_spec as an optional attribute
    if hasattr(state, "trip_spec") and state.trip_spec:
        trip_spec = state.trip_spec
        # Get destination
        if hasattr(trip_spec, "destination"):
            destination = trip_spec.destination
        # Get dates (format as string range)
        if hasattr(trip_spec, "start_date") and hasattr(trip_spec, "end_date"):
            if trip_spec.start_date and trip_spec.end_date:
                dates = f"{trip_spec.start_date}..{trip_spec.end_date}"

    # ─────────────────────────────────────────────────────────────────────
    # Dispatch to appropriate utility tool with context
    # ─────────────────────────────────────────────────────────────────────
    match utility_match.tool:
        case "currency_convert":
            # Extract amounts from message, use destination for target currency
            return await currency_convert_with_context(
                message=message,
                destination=destination,
            )

        case "weather_lookup":
            # Use trip destination and dates if not specified in message
            return await weather_lookup_with_context(
                message=message,
                destination=destination,
                dates=dates,
            )

        case "timezone_info":
            # Use trip destination if not specified
            return await timezone_info_with_context(
                message=message,
                destination=destination,
                trip_dates=dates,
            )

        case "get_booking":
            booking_id = utility_match.args.get("booking_id")
            if not booking_id:
                return "Please provide a booking ID (e.g., 'show booking book_abc123')."
            if booking_store is None:
                return "Booking lookup is unavailable right now. Please try again later."

            result = await get_booking(str(booking_id), booking_store)
            return result.formatted or result.message

        case "get_consultation":
            consultation_id = utility_match.args.get("consultation_id")
            if not consultation_id and hasattr(state, "consultation_id"):
                consultation_id = getattr(state, "consultation_id")
            if not consultation_id:
                return "Please provide a consultation ID (e.g., 'show consultation cons_abc123')."

            # Prefer summary store when available; fall back to current state if it matches.
            summary = None
            if consultation_summary_store is not None:
                summary = await consultation_summary_store.get_summary(str(consultation_id))

            workflow_state_data = None
            if isinstance(state, WorkflowState) and state.consultation_id == str(consultation_id):
                workflow_state_data = _workflow_state_to_state_data_for_unified(state)

            if summary is None and workflow_state_data is None:
                return f"Consultation not found: {consultation_id}"

            return format_consultation_details(
                consultation_id=str(consultation_id),
                summary=summary,
                workflow_state=workflow_state_data,
            )

        case _:
            # Unknown utility - return helpful message
            return (
                "Unknown utility: "
                f"{utility_match.tool}. Supported utilities: "
                "currency_convert, weather_lookup, timezone_info, "
                "get_booking, get_consultation."
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Context-Aware Question Handler
# ═══════════════════════════════════════════════════════════════════════════════


async def handle_question_with_context(
    state: WorkflowState | StubWorkflowState,
    state_data: WorkflowStateData,
    message: str,
    status: dict[str, Any],
    is_new_session: bool = False,
    a2a_client: "A2AClientWrapper | None" = None,
    agent_registry: "AgentRegistry | None" = None,
) -> tuple[ToolResponse, WorkflowStateData]:
    """
    Handle a question inside an active workflow WITHOUT mutating state.

    Per design doc (workflow_turn Internal Implementation, Example 2):
    - Questions are answered using answer_question tool WITH workflow context
    - WorkflowState remains UNCHANGED (this is a read-only action)
    - Response includes the answer plus checkpoint re-prompt when at a checkpoint
    - Only chat history is updated (handled separately by the caller)

    Context building:
    - Extracts trip_spec destination and dates
    - Includes itinerary_draft or approved itinerary when available
    - Determines question domain from message content

    Response format:
    - Answer text from answer_question tool
    - Checkpoint re-prompt actions when state.checkpoint is set
    - UI actions appropriate to current phase

    Args:
        state: Current workflow state (read-only)
        state_data: Current workflow state data (unchanged)
        message: The user's question
        status: Status dict with phase, session_id, etc.
        is_new_session: Whether this is a newly created session
        a2a_client: Optional A2A client for agent communication
        agent_registry: Optional agent registry for URL lookup

    Returns:
        Tuple of (ToolResponse with answer + re-prompt, unchanged WorkflowStateData)
    """
    from src.orchestrator.tools.answer_question import answer_question

    # ─────────────────────────────────────────────────────────────────────
    # Build context payload from WorkflowState
    # ─────────────────────────────────────────────────────────────────────
    context = _build_question_context(state)

    # ─────────────────────────────────────────────────────────────────────
    # Determine question domain from message content
    # ─────────────────────────────────────────────────────────────────────
    domain = _infer_question_domain(message)

    # ─────────────────────────────────────────────────────────────────────
    # Call answer_question with context
    # ─────────────────────────────────────────────────────────────────────
    answer_response = await answer_question(
        question=message,
        domain=domain,
        context=context,
        a2a_client=a2a_client,
        agent_registry=agent_registry,
    )

    # ─────────────────────────────────────────────────────────────────────
    # Build response with checkpoint re-prompt
    # ─────────────────────────────────────────────────────────────────────
    answer_text = answer_response.message

    # Add checkpoint re-prompt if at a checkpoint
    checkpoint_prompt = _get_checkpoint_reprompt(state)
    if checkpoint_prompt:
        answer_text = f"{answer_text}\n\n{checkpoint_prompt}"

    # Build UI actions for current checkpoint
    ui_actions = _build_checkpoint_actions(state)

    # Build response data
    data: dict[str, Any] = {
        "action": "answer_question_in_context",
        "is_new_session": is_new_session,
        "domain": domain,
    }
    if answer_response.data:
        data.update(answer_response.data)

    response = ToolResponse(
        success=answer_response.success,
        message=answer_text,
        status=status,
        data=data,
        ui={"actions": ui_actions} if ui_actions else None,
    )

    # State is UNCHANGED for question-only turns - return as-is
    return response, state_data


def _build_question_context(state: WorkflowState | StubWorkflowState) -> dict[str, Any]:
    """
    Build context payload from WorkflowState for answer_question.

    Per design doc (Tool 2: answer_question):
    - context.destination: Trip destination (e.g., "Tokyo")
    - context.dates: Trip dates (e.g., "March 10-17, 2026")
    - context.trip_spec: Full TripSpec object with all requirements
    - context.itinerary: Current itinerary for context-aware answers

    Args:
        state: Current workflow state

    Returns:
        Context dict for answer_question
    """
    context: dict[str, Any] = {}

    # Extract from trip_spec if available
    if hasattr(state, "trip_spec") and state.trip_spec:
        trip_spec = state.trip_spec

        # Get destination (check multiple field names for compatibility)
        if hasattr(trip_spec, "destination_city") and trip_spec.destination_city:
            context["destination"] = trip_spec.destination_city
        elif hasattr(trip_spec, "destination") and trip_spec.destination:
            context["destination"] = trip_spec.destination

        # Get dates
        if hasattr(trip_spec, "start_date") and hasattr(trip_spec, "end_date"):
            if trip_spec.start_date and trip_spec.end_date:
                context["dates"] = f"{trip_spec.start_date} to {trip_spec.end_date}"

        # Include full trip_spec (serialize if it has to_dict method)
        if hasattr(trip_spec, "to_dict"):
            context["trip_spec"] = trip_spec.to_dict()
        elif hasattr(trip_spec, "__dict__"):
            context["trip_spec"] = {k: str(v) for k, v in trip_spec.__dict__.items() if v is not None}

    # Include itinerary_draft if available (discovery phase)
    if hasattr(state, "itinerary_draft") and state.itinerary_draft:
        itinerary_draft = state.itinerary_draft
        if hasattr(itinerary_draft, "to_dict"):
            context["itinerary"] = itinerary_draft.to_dict()
        elif hasattr(itinerary_draft, "__dict__"):
            context["itinerary"] = {k: str(v) for k, v in itinerary_draft.__dict__.items() if v is not None}

    # Include approved itinerary if available (booking phase)
    if hasattr(state, "itinerary") and state.itinerary:
        itinerary = state.itinerary
        if hasattr(itinerary, "to_dict"):
            context["itinerary"] = itinerary.to_dict()
        elif hasattr(itinerary, "__dict__"):
            context["itinerary"] = {k: str(v) for k, v in itinerary.__dict__.items() if v is not None}

    return context


def _infer_question_domain(message: str) -> str:
    """
    Infer the question domain from message content.

    Per design doc (Tool 2: answer_question):
    - Domain determines which agent handles the question
    - Valid domains: general, poi, stay, transport, events, dining, budget

    Simple keyword-based inference using word boundaries to avoid false matches:
    - Hotel/accommodation keywords → "stay"
    - Flight/train/transport keywords → "transport"
    - Attraction/sight keywords → "poi"
    - Restaurant/food keywords → "dining"
    - Event/show keywords → "events"
    - Cost/price/budget keywords → "budget"
    - Default → "general"

    Args:
        message: The user's question

    Returns:
        Domain string for answer_question
    """
    import re

    def has_keyword(message_text: str, keywords: list[str]) -> bool:
        """Check if message contains any keyword as a whole word."""
        message_lower = message_text.lower()
        for keyword in keywords:
            # Use word boundary for short keywords to avoid false matches
            # e.g., "eat" shouldn't match "weather"
            if len(keyword) <= 4:
                if re.search(rf"\b{re.escape(keyword)}\b", message_lower):
                    return True
            else:
                # For longer keywords, simple substring match is fine
                if keyword in message_lower:
                    return True
        return False

    # Stay/Accommodation patterns
    stay_keywords = [
        "hotel", "hostel", "motel", "inn", "resort", "accommodation",
        "room", "suite", "check-in", "checkout", "amenity", "amenities",
        "pool", "gym", "fitness", "spa", "wifi", "concierge",
        "lobby", "floor", "bed", "pillow", "towel", "housekeeping",
    ]
    if has_keyword(message, stay_keywords):
        return "stay"

    # Transport patterns
    transport_keywords = [
        "flight", "plane", "airline", "airport", "terminal", "boarding",
        "train", "rail", "station", "shinkansen", "bullet train",
        "bus", "coach", "shuttle", "taxi", "uber", "lyft",
        "car", "rental", "drive", "parking",
        "ferry", "boat", "cruise",
        "departure", "arrival", "layover", "connection",
    ]
    if has_keyword(message, transport_keywords):
        return "transport"

    # POI/Attraction patterns
    poi_keywords = [
        "attraction", "sight", "landmark", "museum", "gallery", "temple",
        "shrine", "park", "garden", "tower", "castle", "palace",
        "monument", "statue", "bridge", "view", "viewpoint",
        "tour", "visit", "explore", "neighborhood", "district",
        "market", "shopping", "mall", "shop", "store",
    ]
    if has_keyword(message, poi_keywords):
        return "poi"

    # Dining patterns (note: "breakfast" removed as it overlaps with stay)
    dining_keywords = [
        "restaurant", "cafe", "coffee", "bar", "pub", "bistro",
        "food", "eat", "meal", "dinner", "lunch", "brunch",
        "cuisine", "dish", "menu", "ramen", "sushi",
        "izakaya", "michelin", "vegetarian", "vegan", "halal", "kosher",
    ]
    if has_keyword(message, dining_keywords):
        return "dining"

    # Events patterns
    event_keywords = [
        "event", "show", "concert", "performance", "festival", "exhibit",
        "exhibition", "game", "match", "theater", "theatre", "opera",
        "ballet", "musical", "ticket", "tickets", "happening", "going on",
    ]
    if has_keyword(message, event_keywords):
        return "events"

    # Budget patterns
    budget_keywords = [
        "budget", "cost", "price", "expensive", "cheap", "afford",
        "spend", "spending", "money", "total", "estimate", "average",
        "per day", "per person", "how much", "worth",
    ]
    if has_keyword(message, budget_keywords):
        return "budget"

    # Default to general
    return "general"


def _get_checkpoint_reprompt(state: WorkflowState | StubWorkflowState) -> str | None:
    """
    Get a checkpoint re-prompt message based on current checkpoint.

    Per design doc (Example 2):
    - After answering a question at a checkpoint, re-prompt the checkpoint action
    - Reminds user they can approve or make changes

    Args:
        state: Current workflow state

    Returns:
        Re-prompt message or None if not at a checkpoint
    """
    if not hasattr(state, "checkpoint") or not state.checkpoint:
        return None

    if state.checkpoint == "trip_spec_approval":
        return "Would you like to approve these trip details and start searching, or make any changes?"

    if state.checkpoint == "itinerary_approval":
        return "Would you like to approve this itinerary, or make any changes?"

    return None


def _build_checkpoint_actions(state: WorkflowState | StubWorkflowState) -> list[dict[str, Any]]:
    """
    Build UI actions for the current checkpoint.

    Per design doc (Example 2):
    - Checkpoint actions: Approve, Request Changes, possibly Start Over/Cancel
    - Actions depend on which checkpoint we're at

    Args:
        state: Current workflow state

    Returns:
        List of UI action dicts
    """
    actions: list[dict[str, Any]] = []

    if not hasattr(state, "checkpoint") or not state.checkpoint:
        return actions

    if state.checkpoint == "trip_spec_approval":
        actions.append({
            "label": "Approve & Search",
            "event": {"type": "approve_checkpoint", "checkpoint_id": "trip_spec_approval"},
        })
        actions.append({
            "label": "Make Changes",
            "event": {"type": "request_change", "checkpoint_id": "trip_spec_approval"},
        })
        actions.append({
            "label": "Start Over",
            "event": {"type": "cancel_workflow"},
        })

    elif state.checkpoint == "itinerary_approval":
        actions.append({
            "label": "Approve & Book",
            "event": {"type": "approve_checkpoint", "checkpoint_id": "itinerary_approval"},
        })
        actions.append({
            "label": "Request Changes",
            "event": {"type": "request_change", "checkpoint_id": "itinerary_approval"},
        })
        actions.append({
            "label": "Start Over",
            "event": {"type": "cancel_workflow"},
        })

    return actions


# ═══════════════════════════════════════════════════════════════════════════════
# Terminal Action Handlers (cancel_workflow, start_new)
# ═══════════════════════════════════════════════════════════════════════════════


async def handle_cancel_workflow(
    state: WorkflowState,
    state_data: WorkflowStateData,
    discovery_job_store: DiscoveryJobStoreProtocol | None = None,
) -> tuple[ToolResponse, WorkflowStateData]:
    """
    Cancel the current workflow - user-initiated abandonment.

    Per design doc (workflow_turn Internal Implementation, cancel_workflow semantics):

    **State Transition:**
    - Any non-terminal phase → Phase.CANCELLED

    **Field Updates:**
    - CLEARS: checkpoint (no longer at a gate)
    - SETS: cancelled_at (timestamp), phase=CANCELLED
    - RETAINS: consultation_id, session_id, trip_spec, discovery_results,
               itinerary_draft (for analytics and potential future "undo")

    **Active Job Handling:**
    If a discovery job is in progress (current_job_id is set):
    1. Send cancel signal to job (best-effort, non-blocking)
    2. Clear current_job_id from state
    3. Job will be orphaned when it completes (version mismatch on finalize)

    **Resumability:**
    - Consultation remains in storage but is non-resumable
    - User can only start_new from CANCELLED state
    - consultation_id remains valid for analytics/audit purposes

    **Idempotency:**
    - Safe to call multiple times - already-cancelled workflow stays cancelled

    Args:
        state: Current workflow state (domain model)
        state_data: Current workflow state data (storage model)
        discovery_job_store: Optional discovery job store for job cancellation

    Returns:
        Tuple of (ToolResponse, updated WorkflowStateData)
    """
    # Build UI action for start_new
    start_new_action = {"label": "Start New Plan", "event": {"type": "start_new"}}

    # Idempotent: already cancelled
    if state.phase == Phase.CANCELLED:
        return ToolResponse(
            success=True,
            message="Trip planning was already cancelled.",
            status={"phase": Phase.CANCELLED.value, "session_id": state.session_id},
            data={"phase": Phase.CANCELLED.value},
            ui={"actions": [start_new_action]},
        ), state_data

    # Cannot cancel terminal states (COMPLETED, FAILED)
    if state.phase in (Phase.COMPLETED, Phase.FAILED):
        return ToolResponse(
            success=False,
            message=f"Cannot cancel - workflow is already {state.phase.value}.",
            error_code="INVALID_STATE_TRANSITION",
            status={"phase": state.phase.value, "session_id": state.session_id},
            data={"phase": state.phase.value},
            ui={"actions": [start_new_action]},
        ), state_data

    # Handle in-flight discovery job (best-effort cancel)
    if state.current_job_id and discovery_job_store:
        try:
            await _cancel_discovery_job(
                job_id=state.current_job_id,
                consultation_id=state.consultation_id,
                discovery_job_store=discovery_job_store,
            )
        except Exception as e:
            # Log but don't fail - job will be orphaned on finalize anyway
            logger.warning(f"Failed to cancel job {state.current_job_id}: {e}")

    # Update state to CANCELLED
    now = datetime.now(timezone.utc)
    state.phase = Phase.CANCELLED
    state.checkpoint = None  # Clear checkpoint gate
    state.cancelled_at = now
    state.current_job_id = None  # Clear job reference
    state.updated_at = now

    # Sync changes to state_data for storage
    state_data.phase = Phase.CANCELLED.value
    state_data.checkpoint = None
    state_data.updated_at = now

    return ToolResponse(
        success=True,
        message="Trip planning cancelled. You can start a new trip plan whenever you're ready.",
        status={"phase": Phase.CANCELLED.value, "session_id": state.session_id},
        data={
            "phase": Phase.CANCELLED.value,
            "consultation_id": state.consultation_id,
        },
        ui={"actions": [start_new_action]},
    ), state_data


async def handle_start_new_workflow(
    state: WorkflowState,
    state_data: WorkflowStateData,
    consultation_index_store: ConsultationIndexStoreProtocol,
) -> tuple[ToolResponse, WorkflowStateData]:
    """
    Reset workflow and start fresh - canonical start_new semantics.

    Per design doc (workflow_turn Internal Implementation, start_new semantics):

    **start_new Semantics:**
    - CLEARS: trip_spec, discovery_results, itinerary_draft, current_job_id,
              last_synced_job_id, checkpoint, agent_context_ids, clarifier_conversation
    - GENERATES: New consultation_id (fresh business reference, non-guessable)
    - INCREMENTS: workflow_version (invalidates old consultation_id lookups)
    - RETAINS: session_id (user session continuity)
    - TRANSITIONS TO: Phase.CLARIFICATION with checkpoint=None
    - DELETES: Old consultation_index entry (prevents stale lookups)
    - CREATES: New consultation_index entry with new workflow_version

    **Identity Integrity:** The old consultation_id is explicitly invalidated by:
    1. Deleting its consultation_index entry
    2. Incrementing workflow_version in WorkflowState
    This ensures old consultation_ids return "not found" rather than new workflow state.

    **Job Orphaning:** If a discovery job is in progress when start_new is called:
    1. current_job_id is set to None in new state
    2. workflow_version is incremented
    3. When the old job completes, finalize_job() checks workflow_version
    4. Version mismatch → job is orphaned (results discarded, logged as warning)
    This prevents old job results from corrupting new workflow state.

    Args:
        state: Current workflow state (domain model)
        state_data: Current workflow state data (storage model)
        consultation_index_store: Store for consultation_id → session_id lookups

    Returns:
        Tuple of (ToolResponse, updated WorkflowStateData)
    """
    # Generate new consultation_id and increment workflow_version
    old_consultation_id = state.consultation_id
    new_consultation_id = generate_consultation_id()
    new_version = state.workflow_version + 1
    now = datetime.now(timezone.utc)

    # Delete old consultation_index entry to prevent stale lookups
    # This ensures the old consultation_id returns "not found" rather than new state
    try:
        await consultation_index_store.delete_consultation(old_consultation_id)
        logger.info(
            f"Deleted consultation index for old consultation_id={old_consultation_id}"
        )
    except Exception as e:
        # Log but continue - the version check in lookup will still prevent stale access
        logger.warning(
            f"Failed to delete old consultation index for {old_consultation_id}: {e}"
        )

    # Create new consultation_index entry with new version
    try:
        await consultation_index_store.add_session(
            session_id=state.session_id,
            consultation_id=new_consultation_id,
            workflow_version=new_version,
        )
        logger.info(
            f"Created new consultation index: consultation_id={new_consultation_id}, "
            f"session_id={state.session_id}, version={new_version}"
        )
    except Exception as e:
        logger.error(
            f"Failed to create consultation index for {new_consultation_id}: {e}"
        )
        # This is a critical error - return error response
        return ToolResponse.error(
            message="Failed to start new workflow. Please try again.",
            error_code="INTERNAL_ERROR",
        ), state_data

    # Update state to fresh CLARIFICATION state
    # CLEARS fields, INCREMENTS version, GENERATES new consultation_id
    state.consultation_id = new_consultation_id
    state.workflow_version = new_version
    state.phase = Phase.CLARIFICATION
    state.checkpoint = None
    state.current_step = "gathering"
    state.trip_spec = None
    state.discovery_results = None
    state.itinerary_draft = None
    state.itinerary_id = None
    state.current_job_id = None
    state.last_synced_job_id = None
    state.agent_context_ids = {}
    state.clarifier_conversation = AgentConversation(agent_name="clarifier", messages=[])
    state.discovery_requests = {}
    state.discovery_artifact_id = None
    state.conversation_overflow_count = 0
    state.cancelled_at = None  # Clear cancelled_at since we're starting fresh
    state.updated_at = now

    # Sync changes to state_data for storage
    state_data.consultation_id = new_consultation_id
    state_data.workflow_version = new_version
    state_data.phase = Phase.CLARIFICATION.value
    state_data.checkpoint = None
    state_data.current_step = "gathering"
    state_data.itinerary_id = None
    state_data.agent_context_ids = {}
    state_data.updated_at = now

    return ToolResponse(
        success=True,
        message="Starting a new trip plan. Where would you like to travel?",
        status={
            "phase": Phase.CLARIFICATION.value,
            "session_id": state.session_id,
            "consultation_id": new_consultation_id,
        },
        data={
            "phase": Phase.CLARIFICATION.value,
            "consultation_id": new_consultation_id,
            "workflow_version": new_version,
            "is_new_workflow": True,
        },
    ), state_data


async def _cancel_discovery_job(
    job_id: str,
    consultation_id: str,
    discovery_job_store: DiscoveryJobStoreProtocol,
) -> None:
    """
    Send cancel signal to a running discovery job.

    Best-effort cancellation:
    - Updates job status to CANCELLED in storage
    - Running agents may continue briefly but results will be discarded
    - Job finalization will detect version mismatch and orphan results

    Args:
        job_id: The job ID to cancel
        consultation_id: The consultation ID (partition key)
        discovery_job_store: Store for discovery jobs
    """
    try:
        job = await discovery_job_store.get_job(job_id, consultation_id)
        if job and job.status == JobStatus.RUNNING:
            job.status = JobStatus.CANCELLED
            job.cancelled_at = datetime.now(timezone.utc)
            await discovery_job_store.save_job(job)
            logger.info(f"Cancelled discovery job {job_id}")
        else:
            logger.debug(
                f"Job {job_id} not found or not running "
                f"(status={job.status if job else 'not found'})"
            )
    except Exception as e:
        logger.warning(f"Error cancelling discovery job {job_id}: {e}")
        raise


# ═══════════════════════════════════════════════════════════════════════════════
# Status Handler (universal action, no state mutation)
# ═══════════════════════════════════════════════════════════════════════════════


async def handle_get_status(
    state: WorkflowState,
    state_data: WorkflowStateData,
    discovery_job_store: DiscoveryJobStoreProtocol | None = None,
    booking_service: "BookingService | None" = None,
) -> tuple[ToolResponse, WorkflowStateData]:
    """
    Return phase-specific status without mutating WorkflowState.

    Per design doc (Long-Running Operations and Booking Safety sections):
    - GET_STATUS is a universal action valid in ALL phases
    - Returns phase-specific status payloads
    - Powers CLI /status and UI refresh actions
    - Does NOT mutate WorkflowState

    Phase-specific responses:
    - CLARIFICATION: TripSpec summary (destination, dates, travelers, preferences)
    - DISCOVERY_IN_PROGRESS: Job progress (agent statuses, completion percentage)
    - DISCOVERY_PLANNING: Itinerary draft summary, gaps if any
    - BOOKING: Booking summary (per-item statuses, counts)
    - Terminal phases (COMPLETED/FAILED/CANCELLED): Final state guidance

    Args:
        state: Current workflow state (domain model)
        state_data: Current workflow state data (storage model)
        discovery_job_store: Optional store for discovery job lookup
        booking_service: Optional service for booking summary

    Returns:
        Tuple of (ToolResponse with status, unchanged WorkflowStateData)
    """
    # Build base status dict
    status: dict[str, Any] = {
        "phase": state.phase.value,
        "session_id": state.session_id,
    }
    if state.consultation_id:
        status["consultation_id"] = state.consultation_id
    if state.checkpoint:
        status["checkpoint"] = state.checkpoint

    # ─────────────────────────────────────────────────────────────────────
    # CLARIFICATION Phase Status
    # ─────────────────────────────────────────────────────────────────────
    if state.phase == Phase.CLARIFICATION:
        return _build_clarification_status(state, status), state_data

    # ─────────────────────────────────────────────────────────────────────
    # DISCOVERY_IN_PROGRESS Phase Status
    # ─────────────────────────────────────────────────────────────────────
    if state.phase == Phase.DISCOVERY_IN_PROGRESS:
        return await _build_discovery_in_progress_status(
            state, status, discovery_job_store
        ), state_data

    # ─────────────────────────────────────────────────────────────────────
    # DISCOVERY_PLANNING Phase Status
    # ─────────────────────────────────────────────────────────────────────
    if state.phase == Phase.DISCOVERY_PLANNING:
        return _build_discovery_planning_status(state, status), state_data

    # ─────────────────────────────────────────────────────────────────────
    # BOOKING Phase Status
    # ─────────────────────────────────────────────────────────────────────
    if state.phase == Phase.BOOKING:
        return await _build_booking_status(state, status, booking_service), state_data

    # ─────────────────────────────────────────────────────────────────────
    # Terminal Phases (COMPLETED, FAILED, CANCELLED)
    # ─────────────────────────────────────────────────────────────────────
    return _build_terminal_status(state, status), state_data


def _build_clarification_status(
    state: WorkflowState,
    status: dict[str, Any],
) -> ToolResponse:
    """Build status response for CLARIFICATION phase."""
    # Extract trip_spec summary if available
    data: dict[str, Any] = {"phase": state.phase.value}

    if state.trip_spec:
        trip_spec = state.trip_spec
        spec_summary: dict[str, Any] = {}

        # Check for both destination_city (TripSpec model) and destination (legacy/TripSummary)
        if hasattr(trip_spec, "destination_city") and trip_spec.destination_city:
            spec_summary["destination"] = trip_spec.destination_city
        elif hasattr(trip_spec, "destination") and trip_spec.destination:
            spec_summary["destination"] = trip_spec.destination
        if hasattr(trip_spec, "start_date") and trip_spec.start_date:
            spec_summary["start_date"] = str(trip_spec.start_date)
        if hasattr(trip_spec, "end_date") and trip_spec.end_date:
            spec_summary["end_date"] = str(trip_spec.end_date)
        # Check for both num_travelers (TripSpec) and travelers (legacy)
        if hasattr(trip_spec, "num_travelers") and trip_spec.num_travelers:
            spec_summary["travelers"] = trip_spec.num_travelers
        elif hasattr(trip_spec, "travelers") and trip_spec.travelers:
            spec_summary["travelers"] = trip_spec.travelers
        # Check for budget fields
        if hasattr(trip_spec, "budget_per_person") and trip_spec.budget_per_person:
            spec_summary["budget"] = trip_spec.budget_per_person
        elif hasattr(trip_spec, "budget") and trip_spec.budget:
            spec_summary["budget"] = trip_spec.budget

        data["trip_spec"] = spec_summary
        message = f"Planning trip to {spec_summary.get('destination', 'TBD')}"
    else:
        message = "Gathering trip details..."

    # Check if at approval checkpoint
    if state.checkpoint == "trip_spec_approval":
        message = "Trip details ready for approval"
        data["awaiting_approval"] = True

    # Build UI actions
    ui_actions = []
    if state.checkpoint == "trip_spec_approval":
        ui_actions.append({
            "label": "Approve & Continue",
            "event": {"type": "approve_checkpoint", "checkpoint_id": "trip_spec_approval"},
        })
        ui_actions.append({
            "label": "Make Changes",
            "event": {"type": "request_change", "checkpoint_id": "trip_spec_approval"},
        })

    return ToolResponse(
        success=True,
        message=message,
        status=status,
        data=data,
        ui={"actions": ui_actions} if ui_actions else None,
    )


async def _build_discovery_in_progress_status(
    state: WorkflowState,
    status: dict[str, Any],
    discovery_job_store: DiscoveryJobStoreProtocol | None,
) -> ToolResponse:
    """Build status response for DISCOVERY_IN_PROGRESS phase."""
    stage_labels = {
        "discovery": "discovery search",
        "aggregator": "aggregating results",
        "budget": "budget planning",
        "route": "route planning",
        "validator": "final itinerary validation",
        "planning_blocked": "planning review",
        "planning_failed": "planning recovery",
    }

    data: dict[str, Any] = {"phase": state.phase.value}

    # Per design doc: Real-time progress only available via SSE
    # Polling endpoint returns coarse status
    if not state.current_job_id:
        return ToolResponse(
            success=True,
            message="Discovery job not started yet.",
            status=status,
            data=data,
        )

    data["job_id"] = state.current_job_id

    # Try to load job details if store available
    if discovery_job_store and state.consultation_id:
        try:
            job = await discovery_job_store.get_job(
                state.current_job_id, state.consultation_id
            )
            if job:
                # Build agent progress summary
                agent_progress: dict[str, str] = {}
                completed = 0
                total = 0
                for agent_name, progress in job.agent_progress.items():
                    agent_progress[agent_name] = progress.status
                    total += 1
                    if progress.status in ("completed", "failed", "timeout"):
                        completed += 1

                data["agent_progress"] = agent_progress
                data["completion_percentage"] = (
                    int((completed / total) * 100) if total > 0 else 0
                )
                data["job_status"] = job.status.value
                if job.pipeline_stage:
                    data["pipeline_stage"] = job.pipeline_stage

                # Keep users informed through discovery and planning stages.
                stage = job.pipeline_stage or "discovery"
                if stage == "discovery" and job.status == JobStatus.RUNNING:
                    message = f"Searching... {completed}/{total} agents complete"
                elif stage in {"aggregator", "budget", "route", "validator"}:
                    message = (
                        f"Discovery completed. Now {stage_labels[stage]}..."
                    )
                elif stage in {"planning_blocked", "planning_failed"}:
                    message = (
                        f"Discovery completed. {stage_labels[stage].capitalize()}..."
                    )
                elif job.status != JobStatus.RUNNING:
                    message = "Discovery completed. Starting itinerary planning..."
                else:
                    message = "Discovery in progress..."

        except Exception as e:
            logger.warning(f"Error loading discovery job {state.current_job_id}: {e}")
            message = "Discovery in progress..."
    else:
        message = "Discovery in progress..."

    # Build UI with refresh action
    ui_actions = [
        {
            "label": "Refresh",
            "event": {"type": "status"},
        },
        {
            "label": "Cancel",
            "event": {"type": "cancel_workflow"},
        },
    ]

    # Add stream URL for SSE connection
    data["stream_url"] = f"/sessions/{state.session_id}/discovery/stream"

    return ToolResponse(
        success=True,
        message=message,
        status=status,
        data=data,
        ui={"actions": ui_actions},
    )


def _build_discovery_planning_status(
    state: WorkflowState,
    status: dict[str, Any],
) -> ToolResponse:
    """Build status response for DISCOVERY_PLANNING phase."""
    data: dict[str, Any] = {"phase": state.phase.value}

    # Check for itinerary draft
    if state.itinerary_draft:
        itinerary_draft = state.itinerary_draft
        draft_summary: dict[str, Any] = {}

        if isinstance(itinerary_draft, dict):
            destination = itinerary_draft.get("destination")
            days = itinerary_draft.get("days", [])
            total_cost = itinerary_draft.get("total_estimated_cost")
            currency = itinerary_draft.get("currency")
            if destination:
                draft_summary["destination"] = destination
            if isinstance(days, list) and days:
                draft_summary["day_count"] = len(days)
            if total_cost is not None:
                draft_summary["estimated_cost"] = total_cost
            if currency:
                draft_summary["currency"] = currency
            gaps = itinerary_draft.get("gaps", [])
            data["has_gaps"] = bool(gaps)
            data["itinerary_draft"] = itinerary_draft
            data["itinerary_summary"] = draft_summary
        else:
            # Extract summary from draft object
            if hasattr(itinerary_draft, "trip_summary") and itinerary_draft.trip_summary:
                summary = itinerary_draft.trip_summary
                if hasattr(summary, "destination"):
                    draft_summary["destination"] = summary.destination
                # Compute day_count from dates if not directly available
                if hasattr(summary, "day_count"):
                    draft_summary["day_count"] = summary.day_count
                elif hasattr(summary, "start_date") and hasattr(summary, "end_date"):
                    if summary.start_date and summary.end_date:
                        delta = summary.end_date - summary.start_date
                        draft_summary["day_count"] = delta.days + 1
                if hasattr(summary, "estimated_cost"):
                    draft_summary["estimated_cost"] = summary.estimated_cost

            # Check for gaps
            if hasattr(itinerary_draft, "gaps") and itinerary_draft.gaps:
                draft_summary["gap_count"] = len(itinerary_draft.gaps)
                data["has_gaps"] = True
            else:
                data["has_gaps"] = False

            data["itinerary_draft"] = draft_summary
            data["itinerary_summary"] = draft_summary

        destination = draft_summary.get("destination", "your trip")
        day_count = draft_summary.get("day_count")
        estimated_cost = draft_summary.get("estimated_cost")
        currency = draft_summary.get("currency")
        preview_block = ""
        if isinstance(itinerary_draft, dict):
            days = itinerary_draft.get("days", [])
            if isinstance(days, list) and days:
                def _format_time_slot(time_slot: Any) -> str | None:
                    if isinstance(time_slot, str) and time_slot:
                        return time_slot
                    if not isinstance(time_slot, dict):
                        return None
                    start_time = time_slot.get("start_time") or time_slot.get("startTime")
                    end_time = time_slot.get("end_time") or time_slot.get("endTime")
                    duration = time_slot.get("duration_minutes") or time_slot.get(
                        "durationMinutes"
                    )
                    if isinstance(start_time, str) and isinstance(end_time, str):
                        return f"{start_time}-{end_time}"
                    if isinstance(start_time, str):
                        return start_time
                    if isinstance(end_time, str):
                        return f"Until {end_time}"
                    if isinstance(duration, int):
                        return f"{duration}m"
                    return None

                def _format_activity(activity: dict[str, Any]) -> str | None:
                    name = activity.get("name") or activity.get("title")
                    if not isinstance(name, str) or not name:
                        return None
                    time_label = _format_time_slot(
                        activity.get("time_slot")
                        or {
                            "start_time": activity.get("start_time"),
                            "end_time": activity.get("end_time"),
                        }
                    )
                    location = activity.get("location")
                    notes = activity.get("notes")
                    is_placeholder = activity.get("is_placeholder")
                    parts = []
                    if time_label:
                        parts.append(time_label)
                    parts.append(name)
                    if isinstance(location, str) and location:
                        parts.append(f"@ {location}")
                    if is_placeholder:
                        parts.append("(placeholder)")
                    if isinstance(notes, str) and notes:
                        parts.append(f"- {notes}")
                    return " ".join(parts)

                def _format_meal(meal: dict[str, Any]) -> str | None:
                    meal_type = meal.get("meal_type")
                    name = meal.get("name")
                    if isinstance(meal_type, str) and meal_type:
                        label = meal_type.title()
                    else:
                        label = "Meal"
                    if isinstance(name, str) and name:
                        label = f"{label}: {name}"
                    time_label = _format_time_slot(
                        meal.get("time_slot")
                        or {"start_time": meal.get("start_time"), "end_time": meal.get("end_time")}
                    )
                    location = meal.get("location")
                    cuisine = meal.get("cuisine")
                    notes = meal.get("notes")
                    is_placeholder = meal.get("is_placeholder")
                    parts = []
                    if time_label:
                        parts.append(time_label)
                    parts.append(label)
                    if isinstance(location, str) and location:
                        parts.append(f"@ {location}")
                    if isinstance(cuisine, str) and cuisine:
                        parts.append(f"({cuisine})")
                    if is_placeholder:
                        parts.append("(placeholder)")
                    if isinstance(notes, str) and notes:
                        parts.append(f"- {notes}")
                    return " ".join(parts)

                def _format_transport(segment: dict[str, Any]) -> str | None:
                    mode = segment.get("mode")
                    from_loc = segment.get("from_location")
                    to_loc = segment.get("to_location")
                    if not (isinstance(mode, str) and isinstance(from_loc, str) and isinstance(to_loc, str)):
                        return None
                    carrier = segment.get("carrier")
                    depart = segment.get("departure_time")
                    arrive = segment.get("arrival_time")
                    time_label = None
                    if isinstance(depart, str) and isinstance(arrive, str):
                        time_label = f"{depart}-{arrive}"
                    elif isinstance(depart, str):
                        time_label = depart
                    else:
                        time_label = _format_time_slot(
                            segment.get("time_slot")
                            or {
                                "start_time": segment.get("start_time"),
                                "end_time": segment.get("end_time"),
                            }
                        )
                    notes = segment.get("notes")
                    is_placeholder = segment.get("is_placeholder")
                    parts = []
                    if time_label:
                        parts.append(time_label)
                    parts.append(f"{mode.title()} {from_loc} -> {to_loc}")
                    if isinstance(carrier, str) and carrier:
                        parts.append(f"({carrier})")
                    if is_placeholder:
                        parts.append("(placeholder)")
                    if isinstance(notes, str) and notes:
                        parts.append(f"- {notes}")
                    return " ".join(parts)

                def _format_day_block(day: dict[str, Any], index: int) -> list[str]:
                    day_number = index + 1
                    date_value = day.get("date")
                    date_str = date_value if isinstance(date_value, str) else None
                    title = day.get("title")
                    title_str = title.strip() if isinstance(title, str) else ""
                    if title_str.lower().startswith("day "):
                        title_str = ""

                    header = f"Day {day_number}"
                    if date_str:
                        header += f" ({date_str})"
                    if title_str:
                        header += f": {title_str}"
                    lines = [f"- {header}"]

                    activities = day.get("activities", [])
                    activity_lines: list[str] = []
                    if isinstance(activities, list):
                        for activity in activities:
                            if not isinstance(activity, dict):
                                continue
                            formatted = _format_activity(activity)
                            if formatted:
                                activity_lines.append(formatted)
                    if activity_lines:
                        lines.append("  Activities:")
                        for item in activity_lines:
                            lines.append(f"    - {item}")
                    else:
                        lines.append("  Activities: (not listed)")

                    meals = day.get("meals", [])
                    meal_lines: list[str] = []
                    if isinstance(meals, list):
                        for meal in meals:
                            if not isinstance(meal, dict):
                                continue
                            formatted = _format_meal(meal)
                            if formatted:
                                meal_lines.append(formatted)
                    if meal_lines:
                        lines.append("  Meals:")
                        for item in meal_lines:
                            lines.append(f"    - {item}")
                    else:
                        lines.append("  Meals: (not listed)")

                    accommodation = day.get("accommodation")
                    if isinstance(accommodation, dict):
                        acc_name = accommodation.get("name")
                        if isinstance(acc_name, str) and acc_name:
                            location = accommodation.get("location")
                            if isinstance(location, str) and location:
                                lines.append(f"  Stay: {acc_name} @ {location}")
                            else:
                                lines.append(f"  Stay: {acc_name}")
                        else:
                            lines.append("  Stay: (not specified)")
                    else:
                        lines.append("  Stay: (not specified)")

                    transport = day.get("transport", [])
                    transport_lines: list[str] = []
                    if isinstance(transport, list):
                        for segment in transport:
                            if not isinstance(segment, dict):
                                continue
                            formatted = _format_transport(segment)
                            if formatted:
                                transport_lines.append(formatted)
                    if transport_lines:
                        lines.append("  Transport:")
                        for item in transport_lines:
                            lines.append(f"    - {item}")
                    else:
                        lines.append("  Transport: (not listed)")

                    notes = day.get("notes", [])
                    if isinstance(notes, list):
                        note_lines = [n for n in notes if isinstance(n, str) and n]
                        if note_lines:
                            lines.append("  Notes:")
                            for item in note_lines:
                                lines.append(f"    - {item}")

                    return lines

                preview_lines: list[str] = []
                for idx, day in enumerate(days):
                    if not isinstance(day, dict):
                        continue
                    preview_lines.extend(_format_day_block(day, idx))
                if preview_lines:
                    preview_block = "\nItinerary:\n" + "\n".join(preview_lines)
        preview_suffix = f"{preview_block}\n" if preview_block else " "
        if isinstance(day_count, int) and isinstance(estimated_cost, (int, float)) and currency:
            message = (
                f"I've created a {day_count}-day itinerary for {destination}. "
                f"Estimated total cost: {estimated_cost:,.0f} {currency}."
                f"{preview_suffix}"
                "Would you like to approve this plan or make changes?"
            )
        else:
            message = (
                f"Itinerary for {destination} ready for review."
                f"{preview_suffix}"
                "Would you like to approve this plan or make changes?"
            )
    else:
        message = "Planning pipeline in progress..."
        data["awaiting_results"] = True

    # Check if at approval checkpoint
    if state.checkpoint == "itinerary_approval":
        data["awaiting_approval"] = True

    # Build UI actions
    ui_actions = []
    if state.checkpoint == "itinerary_approval":
        ui_actions.append({
            "label": "Approve Itinerary",
            "event": {"type": "approve_checkpoint", "checkpoint_id": "itinerary_approval"},
        })
        ui_actions.append({
            "label": "Request Changes",
            "event": {"type": "request_change", "checkpoint_id": "itinerary_approval"},
        })
        ui_actions.append({
            "label": "Restart Discovery",
            "event": {"type": "retry_discovery", "checkpoint_id": "itinerary_approval"},
        })

    return ToolResponse(
        success=True,
        message=message,
        status=status,
        data=data,
        ui={"actions": ui_actions} if ui_actions else None,
    )


async def _build_booking_status(
    state: WorkflowState,
    status: dict[str, Any],
    booking_service: "BookingService | None",
) -> ToolResponse:
    """Build status response for BOOKING phase."""
    from src.orchestrator.booking.service import BookingService

    data: dict[str, Any] = {"phase": state.phase.value}

    if not state.itinerary_id:
        return ToolResponse(
            success=True,
            message="No itinerary approved yet.",
            status=status,
            data=data,
        )

    data["itinerary_id"] = state.itinerary_id

    # Get booking summary if service available
    if booking_service:
        try:
            summary = await booking_service.get_booking_summary(state.itinerary_id)
            if summary:
                data["booking_summary"] = summary.to_dict()

                # Build message from summary
                if summary.all_booked:
                    message = f"All {summary.total_count} items booked successfully!"
                elif summary.pending_count > 0 or summary.unknown_count > 0:
                    message = (
                        f"Bookings in progress: "
                        f"{summary.booked_count} booked, "
                        f"{summary.pending_count + summary.unknown_count} pending"
                    )
                else:
                    message = (
                        f"{summary.booked_count}/{summary.total_count} items booked, "
                        f"{summary.unbooked_count} remaining"
                    )
                    if summary.failed_count > 0:
                        message += f", {summary.failed_count} failed"
            else:
                message = "Loading booking details..."
        except Exception as e:
            logger.warning(f"Error getting booking summary: {e}")
            message = "Error loading booking status"
    else:
        message = "View booking options to see available items"

    # Build UI actions
    ui_actions = [
        {
            "label": "View Booking Options",
            "event": {"type": "view_booking_options"},
        },
        {
            "label": "Refresh",
            "event": {"type": "status"},
        },
    ]

    return ToolResponse(
        success=True,
        message=message,
        status=status,
        data=data,
        ui={"actions": ui_actions},
    )


def _build_terminal_status(
    state: WorkflowState,
    status: dict[str, Any],
) -> ToolResponse:
    """Build status response for terminal phases (COMPLETED, FAILED, CANCELLED)."""
    data: dict[str, Any] = {"phase": state.phase.value}

    # Phase-specific messages and data
    if state.phase == Phase.COMPLETED:
        message = "Trip planning completed successfully!"
        data["completed"] = True
        if state.itinerary_id:
            data["itinerary_id"] = state.itinerary_id

    elif state.phase == Phase.FAILED:
        message = "Trip planning encountered an error."
        data["failed"] = True
        if hasattr(state, "failure_reason") and state.failure_reason:
            data["failure_reason"] = state.failure_reason

    elif state.phase == Phase.CANCELLED:
        message = "Trip planning was cancelled."
        data["cancelled"] = True
        if hasattr(state, "cancelled_at") and state.cancelled_at:
            data["cancelled_at"] = state.cancelled_at.isoformat()

    else:
        # Shouldn't happen, but handle gracefully
        message = f"Workflow in {state.phase.value} state"

    # All terminal phases offer start_new
    ui_actions = [
        {
            "label": "Start New Trip",
            "event": {"type": "start_new"},
        },
    ]

    return ToolResponse(
        success=True,
        message=message,
        status=status,
        data=data,
        ui={"actions": ui_actions},
    )
