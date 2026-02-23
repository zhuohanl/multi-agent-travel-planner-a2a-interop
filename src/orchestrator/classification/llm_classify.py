"""
LLM fallback classification for workflow_turn message intent detection.

This module provides LLM-based classification for messages that heuristics
cannot confidently classify. It uses the Azure AI Agent (Classifier) to
determine user intent for ambiguous or complex inputs.

Per design doc Routing Flow section (Layer 2a heuristics + LLM fallback):
- Path B: Heuristic classification (fast, no LLM cost) - see heuristic.py
- Path C: LLM fallback (for ambiguous messages) - THIS MODULE

The LLM classifier is only called when:
1. No structured event is provided
2. Heuristic classification returns action=None (no confident match)

Key principles:
- Each LLM decision must be correct with zero thread history
- Business context is injected via WorkflowState summary in the prompt
- Threads exist for debugging and observability only
- LLM returns structured output via classify_action tool call
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.orchestrator.state_gating import Action

if TYPE_CHECKING:
    from azure.ai.agents import AgentsClient
    from src.orchestrator.azure_agent import OrchestratorLLM
    from src.orchestrator.models.workflow_state import WorkflowState, Phase

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Classification Result
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class LLMClassificationResult:
    """Result of LLM-based classification.

    Attributes:
        action: The classified action
        confidence: Confidence score 0.0-1.0 (from LLM's own assessment)
        reason: Brief explanation of why this classification was made
        raw_response: Raw LLM response for debugging
    """

    action: Action
    confidence: float = 0.8  # Default confidence for LLM-based classification
    reason: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "action": self.action.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "raw_response": self.raw_response,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# LLM Action Mapping
# ═══════════════════════════════════════════════════════════════════════════════

# Mapping from LLM classify_action tool output to internal Action enum
# The LLM tool uses a simplified action vocabulary; we map to internal actions
LLM_ACTION_TO_INTERNAL: dict[str, Action] = {
    # Trip spec actions
    "APPROVE_TRIP_SPEC": Action.APPROVE_TRIP_SPEC,
    "MODIFY_TRIP_SPEC": Action.REQUEST_MODIFICATION,
    "START_DISCOVERY": Action.START_DISCOVERY,
    # Itinerary actions
    "APPROVE_ITINERARY": Action.APPROVE_ITINERARY,
    "MODIFY_ITINERARY": Action.REQUEST_MODIFICATION,
    # Booking actions
    "START_BOOKING": Action.VIEW_BOOKING_OPTIONS,
    "CONFIRM_BOOKING": Action.BOOK_SINGLE_ITEM,
    "CANCEL_BOOKING": Action.CANCEL_BOOKING,
    # Additional action mappings for completeness
    "CONTINUE_CLARIFICATION": Action.CONTINUE_CLARIFICATION,
    "ANSWER_QUESTION": Action.ANSWER_QUESTION_IN_CONTEXT,
    "GET_STATUS": Action.GET_STATUS,
    "CANCEL_WORKFLOW": Action.CANCEL_WORKFLOW,
    "CALL_UTILITY": Action.CALL_UTILITY,
}

# Default action when LLM classification fails or is ambiguous
DEFAULT_ACTION = Action.CONTINUE_CLARIFICATION


# ═══════════════════════════════════════════════════════════════════════════════
# Classification Functions
# ═══════════════════════════════════════════════════════════════════════════════


def _build_classification_prompt(
    message: str,
    state: "WorkflowState | None" = None,
) -> str:
    """Build the classification prompt with workflow context.

    Per design doc:
    - Business context is injected via WorkflowState summary in the prompt
    - Not retrieved from thread history (each decision is self-contained)

    Args:
        message: The user's raw message to classify
        state: Current workflow state (optional, for context-aware classification)

    Returns:
        Formatted prompt for the LLM classifier
    """
    # Build context section from WorkflowState
    context_parts = []

    if state:
        # Add phase context
        phase_str = state.phase.value if hasattr(state.phase, "value") else str(state.phase)
        context_parts.append(f"Current phase: {phase_str}")

        # Add checkpoint context
        if state.checkpoint:
            context_parts.append(f"Current checkpoint: {state.checkpoint}")

        # Add trip spec context if available
        if hasattr(state, "trip_spec") and state.trip_spec:
            trip = state.trip_spec
            trip_info = []
            if hasattr(trip, "destination") and trip.destination:
                trip_info.append(f"destination: {trip.destination}")
            if hasattr(trip, "start_date") and trip.start_date:
                trip_info.append(f"dates: {trip.start_date} to {getattr(trip, 'end_date', 'TBD')}")
            if hasattr(trip, "budget") and trip.budget:
                trip_info.append(f"budget: {trip.budget}")
            if trip_info:
                context_parts.append(f"Trip: {', '.join(trip_info)}")

    context_section = "\n".join(context_parts) if context_parts else "No active workflow context."

    # Build the full prompt
    prompt = f"""Classify the following user message as a workflow action.

## Workflow Context
{context_section}

## User Message
"{message}"

## Instructions
Analyze the user message and classify it as one of the following actions:

For CLARIFICATION phase:
- APPROVE_TRIP_SPEC: User approves the trip specification ("yes", "looks good", "that's correct")
- MODIFY_TRIP_SPEC: User wants to change trip details ("change the dates", "different budget")
- CONTINUE_CLARIFICATION: User is providing more trip details or answering questions

For DISCOVERY phase:
- START_DISCOVERY: User wants to start finding options (usually after trip spec approval)
- APPROVE_ITINERARY: User approves the proposed itinerary
- MODIFY_ITINERARY: User wants changes to the itinerary

For BOOKING phase:
- START_BOOKING: User wants to see booking options
- CONFIRM_BOOKING: User confirms a specific booking
- CANCEL_BOOKING: User wants to cancel a booking

Universal actions (any phase):
- ANSWER_QUESTION: User is asking a question (not taking an action)
- GET_STATUS: User is asking about current status or progress
- CANCEL_WORKFLOW: User wants to cancel the entire trip planning
- CALL_UTILITY: User is asking about weather, currency, timezone, or booking/consultation lookups

Call the classify_action function with your classification and confidence score (0-1).
Higher confidence (>0.8) for clear intent, lower (<0.6) for ambiguous messages.
"""

    return prompt


async def llm_classify(
    message: str,
    state: "WorkflowState | None" = None,
    llm: "OrchestratorLLM | None" = None,
    session_id: str | None = None,
) -> LLMClassificationResult:
    """
    Classify user message intent using Azure AI Agent (Classifier).

    This is the LLM fallback path (Path C) when heuristics cannot confidently
    classify the message. It uses the pre-provisioned Classifier agent to
    determine user intent via the classify_action tool.

    Per design doc Routing Flow section:
    - Called only when heuristics return action=None
    - Uses Azure AI Agent with classify_action tool
    - Returns structured result with action and confidence

    Args:
        message: The user's raw message to classify
        state: Current workflow state (provides context for classification)
        llm: OrchestratorLLM instance (optional, will create if not provided)
        session_id: Session ID for thread management (optional)

    Returns:
        LLMClassificationResult with action, confidence, and reason

    Note:
        If Azure AI Agent is unavailable or returns an error, falls back to
        a default action based on current phase (graceful degradation).
    """
    # Build the classification prompt with context
    prompt = _build_classification_prompt(message, state)

    # Try LLM classification
    try:
        result = await _call_classifier_agent(prompt, llm, session_id)
        if result:
            return result
    except Exception as e:
        logger.warning(f"LLM classification failed: {e}, using fallback")

    # Fallback: use phase-based defaults
    return _create_fallback_result(message, state)


async def _call_classifier_agent(
    prompt: str,
    llm: "OrchestratorLLM | None" = None,
    session_id: str | None = None,
) -> LLMClassificationResult | None:
    """
    Call the Azure AI Classifier agent to classify the message.

    Args:
        prompt: The classification prompt to send
        llm: OrchestratorLLM instance (optional)
        session_id: Session ID for thread management

    Returns:
        LLMClassificationResult if successful, None on failure
    """
    # Import here to avoid circular dependencies and allow mocking
    from src.orchestrator.azure_agent import (
        AgentType,
        OrchestratorLLM,
        get_orchestrator_llm,
        ConfigurationError,
    )

    # Get or create LLM instance
    if llm is None:
        try:
            llm = get_orchestrator_llm()
        except ConfigurationError as e:
            logger.debug(f"Azure AI not configured: {e}")
            return None

    # Use a default session_id if not provided
    if session_id is None:
        session_id = "classification_session"

    try:
        # Get classifier agent ID and ensure thread exists
        classifier_agent_id = llm.get_agent_id(AgentType.CLASSIFIER)
        thread_id = llm._ensure_thread_exists(session_id, AgentType.CLASSIFIER)

        # Create message in the thread
        llm.client.messages.create(
            thread_id=thread_id,
            role="user",
            content=prompt,
        )

        # Run the classifier agent
        run = llm.client.runs.create(
            thread_id=thread_id,
            agent_id=classifier_agent_id,
        )
        run = _poll_run_until_terminal(llm.client, thread_id, run.id)

        # Process the run result
        if run.status == "completed":
            # Get tool calls from the run
            if hasattr(run, "required_action") and run.required_action:
                tool_calls = run.required_action.submit_tool_outputs.tool_calls
                for tool_call in tool_calls:
                    if tool_call.function.name == "classify_action":
                        return _parse_classify_action_response(
                            tool_call.function.arguments
                        )

            # Check thread messages for tool call results
            messages = llm.client.messages.list(thread_id=thread_id, order="desc")
            for msg in messages:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tool_call in msg.tool_calls:
                        if tool_call.function.name == "classify_action":
                            return _parse_classify_action_response(
                                tool_call.function.arguments
                            )

        elif run.status == "requires_action":
            # Handle tool calls
            if run.required_action:
                tool_calls = run.required_action.submit_tool_outputs.tool_calls
                for tool_call in tool_calls:
                    if tool_call.function.name == "classify_action":
                        return _parse_classify_action_response(
                            tool_call.function.arguments
                        )

        logger.warning(f"Classifier run completed without tool call, status: {run.status}")
        return None

    except Exception as e:
        logger.error(f"Error calling classifier agent: {e}")
        return None


def _poll_run_until_terminal(
    client: "AgentsClient",
    thread_id: str,
    run_id: str,
    poll_interval_seconds: float = 0.5,
    timeout_seconds: float = 60.0,
):
    """Poll a run until it reaches a terminal status."""
    terminal_statuses = {
        "requires_action",
        "completed",
        "failed",
        "cancelled",
        "expired",
        "incomplete",
    }
    start_time = time.monotonic()

    while True:
        run = client.runs.get(thread_id=thread_id, run_id=run_id)
        if run.status in terminal_statuses:
            return run
        if timeout_seconds is not None and time.monotonic() - start_time > timeout_seconds:
            raise TimeoutError(
                f"Run {run_id} did not complete within {timeout_seconds} seconds"
            )
        time.sleep(poll_interval_seconds)


def _parse_classify_action_response(
    arguments: str | dict[str, Any],
) -> LLMClassificationResult:
    """
    Parse the classify_action tool response from the LLM.

    Args:
        arguments: Tool call arguments (JSON string or dict)

    Returns:
        LLMClassificationResult with parsed action and confidence
    """
    # Parse arguments if string
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse classify_action arguments: {arguments}")
            return LLMClassificationResult(
                action=DEFAULT_ACTION,
                confidence=0.5,
                reason="Failed to parse LLM response",
                raw_response={"raw": arguments},
            )
    else:
        args = arguments

    # Extract action from response
    llm_action = args.get("action", "CONTINUE_CLARIFICATION")
    confidence = args.get("confidence", 0.8)

    # Normalize confidence to 0-1 range
    if isinstance(confidence, (int, float)):
        confidence = max(0.0, min(1.0, float(confidence)))
    else:
        confidence = 0.8

    # Map LLM action to internal Action enum
    internal_action = LLM_ACTION_TO_INTERNAL.get(llm_action, DEFAULT_ACTION)

    logger.debug(
        f"LLM classified message as {llm_action} -> {internal_action.value} "
        f"(confidence={confidence:.2f})"
    )

    return LLMClassificationResult(
        action=internal_action,
        confidence=confidence,
        reason=f"LLM classified as {llm_action}",
        raw_response=args,
    )


def _create_fallback_result(
    message: str,
    state: "WorkflowState | None" = None,
) -> LLMClassificationResult:
    """
    Create a fallback classification result when LLM is unavailable.

    Uses phase-based defaults to provide reasonable behavior:
    - CLARIFICATION phase: CONTINUE_CLARIFICATION (gather more info)
    - DISCOVERY phases: ANSWER_QUESTION_IN_CONTEXT (safe, non-mutating)
    - BOOKING phase: ANSWER_QUESTION_IN_CONTEXT (safe, non-mutating)
    - Other phases: ANSWER_QUESTION_IN_CONTEXT (safest default)

    Args:
        message: The original message (for logging)
        state: Current workflow state

    Returns:
        LLMClassificationResult with fallback action
    """
    from src.orchestrator.models.workflow_state import Phase

    fallback_action = Action.ANSWER_QUESTION_IN_CONTEXT  # Safest default

    if state and hasattr(state, "phase"):
        if state.phase == Phase.CLARIFICATION:
            fallback_action = Action.CONTINUE_CLARIFICATION
            reason = "LLM unavailable, defaulting to clarification in CLARIFICATION phase"
        elif state.phase in (Phase.DISCOVERY_IN_PROGRESS, Phase.DISCOVERY_PLANNING):
            fallback_action = Action.ANSWER_QUESTION_IN_CONTEXT
            reason = "LLM unavailable, defaulting to question handling in discovery"
        elif state.phase == Phase.BOOKING:
            fallback_action = Action.ANSWER_QUESTION_IN_CONTEXT
            reason = "LLM unavailable, defaulting to question handling in booking"
        else:
            fallback_action = Action.ANSWER_QUESTION_IN_CONTEXT
            reason = f"LLM unavailable, defaulting to question handling in {state.phase.value}"
    else:
        reason = "LLM unavailable, no state context - defaulting to question handling"

    logger.info(f"Using fallback classification: {fallback_action.value} - {reason}")

    return LLMClassificationResult(
        action=fallback_action,
        confidence=0.5,  # Lower confidence for fallback
        reason=reason,
        raw_response={"fallback": True, "original_message": message[:100]},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Module Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "llm_classify",
    "LLMClassificationResult",
    "LLM_ACTION_TO_INTERNAL",
    "DEFAULT_ACTION",
]
