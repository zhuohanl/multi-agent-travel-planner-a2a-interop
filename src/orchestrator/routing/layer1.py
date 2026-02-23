"""
Layer 1 routing implementation for the orchestrator.

This module implements the three-layer routing system:
- Layer 1a: Active session check (no LLM) - workflow_turn directly
- Layer 1b: Utility pattern match (no LLM) - regex-based utility routing
- Layer 1c: LLM routing (Azure AI Agent) - decides workflow_turn vs answer_question

The routing follows the design doc "Routing Flow" section:
1. If session exists → workflow_turn (Layer 1a)
2. If utility pattern matches → utility handler (Layer 1b)
3. Otherwise → LLM decides (Layer 1c)

Key design decisions:
- Layer 1b patterns are INTENTIONALLY SIMPLISTIC - they only match obvious,
  canonical phrasings. Natural language variations fall through to Layer 1c.
- With active session, all messages (including utilities) go to workflow_turn
  for context-aware handling at Layer 2.
- Layer 1c LLM sees 7 tools: workflow_turn, answer_question, + 5 utilities
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from src.orchestrator.utils.utility_patterns import (
    BOOKING_LOOKUP_PATTERN,
    CONSULTATION_LOOKUP_PATTERN,
    CURRENCY_CONVERT_PATTERN,
    TIMEZONE_INFO_PATTERN,
    WEATHER_LOOKUP_PATTERN,
)

if TYPE_CHECKING:
    from src.orchestrator.agent import OrchestratorLLM, RunResult
    from src.orchestrator.storage import WorkflowStateData

logger = logging.getLogger(__name__)


# =============================================================================
# ROUTE TARGET ENUM
# =============================================================================


class RouteTarget(str, Enum):
    """Target tool/handler for routing decisions.

    These represent the possible routing destinations:
    - WORKFLOW_TURN: Stateful workflow operations (creates/loads WorkflowState)
    - ANSWER_QUESTION: Stateless Q&A (no workflow context)
    - CURRENCY_CONVERT: Stateless currency conversion
    - WEATHER_LOOKUP: Stateless weather lookup
    - TIMEZONE_INFO: Stateless timezone lookup
    - GET_BOOKING: Stateless booking lookup
    - GET_CONSULTATION: Stateless consultation lookup
    """

    WORKFLOW_TURN = "workflow_turn"
    ANSWER_QUESTION = "answer_question"
    CURRENCY_CONVERT = "currency_convert"
    WEATHER_LOOKUP = "weather_lookup"
    TIMEZONE_INFO = "timezone_info"
    GET_BOOKING = "get_booking"
    GET_CONSULTATION = "get_consultation"


# =============================================================================
# UTILITY PATTERNS (LAYER 1B)
# =============================================================================

# Pattern definitions for Layer 1b regex matching
# These patterns are INTENTIONALLY SIMPLISTIC per design doc
UTILITY_PATTERNS: dict[str, tuple[str, RouteTarget]] = {
    # Currency conversion: "convert 100 USD to EUR"
    "currency": (
        CURRENCY_CONVERT_PATTERN,
        RouteTarget.CURRENCY_CONVERT,
    ),
    # Weather lookup: "weather in Tokyo" or "weather for Paris"
    "weather": (
        WEATHER_LOOKUP_PATTERN,
        RouteTarget.WEATHER_LOOKUP,
    ),
    # Timezone: "what time in Tokyo" or "what time is it in London"
    "timezone": (
        TIMEZONE_INFO_PATTERN,
        RouteTarget.TIMEZONE_INFO,
    ),
    # Booking lookup: "show booking book_xxx"
    "booking_lookup": (
        BOOKING_LOOKUP_PATTERN,
        RouteTarget.GET_BOOKING,
    ),
    # Consultation lookup: "show consultation cons_xxx"
    "consultation_lookup": (
        CONSULTATION_LOOKUP_PATTERN,
        RouteTarget.GET_CONSULTATION,
    ),
}


@dataclass
class UtilityMatch:
    """Result of a successful utility pattern match.

    Attributes:
        target: The routing target (utility tool)
        args: Tuple of captured groups from the regex match
        pattern_name: Name of the matched pattern (for logging)
    """

    target: RouteTarget
    args: tuple[str, ...]
    pattern_name: str


def match_utility_pattern(message: str) -> UtilityMatch | None:
    """Match message against Layer 1b utility patterns.

    This implements Layer 1b regex matching for stateless utilities.
    Only reached when there is no active session.

    Per design doc:
    - Patterns are INTENTIONALLY SIMPLISTIC
    - They only match obvious, canonical phrasings
    - Natural language variations fall through to Layer 1c

    Args:
        message: The user message to match

    Returns:
        UtilityMatch if a pattern matched, None otherwise

    Examples:
        >>> match_utility_pattern("convert 100 USD to EUR")
        UtilityMatch(target=CURRENCY_CONVERT, args=('100', 'USD', 'EUR'), ...)

        >>> match_utility_pattern("how much is 100 dollars in euros?")
        None  # Falls through to Layer 1c
    """
    for pattern_name, (pattern, target) in UTILITY_PATTERNS.items():
        if match := re.search(pattern, message, re.IGNORECASE):
            logger.debug(
                "Layer 1b match: pattern=%s, groups=%s",
                pattern_name,
                match.groups(),
            )
            return UtilityMatch(
                target=target,
                args=match.groups(),
                pattern_name=pattern_name,
            )
    return None


# =============================================================================
# ROUTE RESULT
# =============================================================================


@dataclass
class RouteResult:
    """Result of the routing decision.

    Attributes:
        target: The routing target (tool/handler to invoke)
        layer: Which routing layer made the decision (1a, 1b, or 1c)
        state: WorkflowState if loaded (Layer 1a), None otherwise
        utility_match: Utility pattern match details (Layer 1b), None otherwise
        llm_run: LLM run result (Layer 1c), None otherwise
        tool_args: Arguments for the target tool (varies by layer)
    """

    target: RouteTarget
    layer: str
    state: "WorkflowStateData | None" = None
    utility_match: UtilityMatch | None = None
    llm_run: "RunResult | None" = None
    tool_args: dict[str, Any] | None = None


# =============================================================================
# MAIN ROUTING FUNCTION
# =============================================================================


async def route(
    message: str,
    session_id: str,
    *,
    state: "WorkflowStateData | None" = None,
    llm: "OrchestratorLLM | None" = None,
) -> RouteResult:
    """Route an incoming request through the three-layer system.

    This is the main routing entry point. It implements:
    1. Layer 1a: Check for active session (state is not None)
    2. Layer 1b: Check for utility pattern match
    3. Layer 1c: Use LLM for routing decision

    Per design doc "Routing Flow" section:
    - Active session → workflow_turn (context-aware handling at Layer 2)
    - Utility pattern match → utility handler (stateless)
    - LLM decides → workflow_turn, answer_question, or utility (fallback)

    Args:
        message: The user message to route
        session_id: The session identifier
        state: Pre-loaded WorkflowState if available (from session lookup)
        llm: OrchestratorLLM instance for Layer 1c routing

    Returns:
        RouteResult with routing decision and context

    Note:
        The caller (OrchestratorExecutor) is responsible for loading state
        before calling route(). If state is provided, Layer 1a applies.
    """
    logger.info(
        "Routing message: session_id=%s, has_state=%s, message_preview=%s...",
        session_id,
        state is not None,
        message[:50] if len(message) > 50 else message,
    )

    # =========================================================================
    # LAYER 1a: ACTIVE SESSION CHECK
    # =========================================================================
    # If we have an active session, ALL messages go to workflow_turn
    # (including utilities, which get context-aware handling at Layer 2)
    if state is not None:
        logger.debug(
            "Layer 1a: Active session detected, routing to workflow_turn"
        )
        return RouteResult(
            target=RouteTarget.WORKFLOW_TURN,
            layer="1a",
            state=state,
            tool_args={
                "session_ref": {"session_id": session_id},
                "message": message,
            },
        )

    # =========================================================================
    # LAYER 1b: UTILITY PATTERN MATCHING
    # =========================================================================
    # No active session - check if this is a simple utility request
    utility_match = match_utility_pattern(message)
    if utility_match is not None:
        logger.debug(
            "Layer 1b: Utility pattern match, routing to %s",
            utility_match.target.value,
        )
        return RouteResult(
            target=utility_match.target,
            layer="1b",
            utility_match=utility_match,
            tool_args=_build_utility_args(utility_match),
        )

    # =========================================================================
    # LAYER 1c: LLM ROUTING
    # =========================================================================
    # No session, no utility pattern - let LLM decide
    logger.debug("Layer 1c: No session/pattern match, using LLM routing")

    if llm is None:
        # No LLM configured - default to workflow_turn (start new session)
        logger.warning(
            "Layer 1c: No LLM configured, defaulting to workflow_turn"
        )
        return RouteResult(
            target=RouteTarget.WORKFLOW_TURN,
            layer="1c",
            tool_args={
                "session_ref": {"session_id": session_id},
                "message": message,
            },
        )

    # Use LLM for routing decision.
    # Guard against auth/network/runtime failures so streaming endpoints
    # can degrade gracefully instead of crashing the request.
    try:
        run_result = await _route_with_llm(message, session_id, llm)
    except Exception as exc:
        logger.exception(
            "Layer 1c LLM routing failed, falling back to workflow_turn: %s",
            exc,
        )
        return RouteResult(
            target=RouteTarget.WORKFLOW_TURN,
            layer="1c",
            tool_args={
                "session_ref": {"session_id": session_id},
                "message": message,
            },
        )

    # Parse LLM's routing decision
    target, tool_args = _parse_llm_routing_decision(run_result, session_id, message)

    return RouteResult(
        target=target,
        layer="1c",
        llm_run=run_result,
        tool_args=tool_args,
    )


def _build_utility_args(utility_match: UtilityMatch) -> dict[str, Any]:
    """Build tool arguments from utility pattern match.

    Args:
        utility_match: The utility match with captured groups

    Returns:
        Dict of tool arguments
    """
    match utility_match.target:
        case RouteTarget.CURRENCY_CONVERT:
            # Args: (amount, from_currency, to_currency)
            return {
                "amount": float(utility_match.args[0]),
                "from_currency": utility_match.args[1].upper(),
                "to_currency": utility_match.args[2].upper(),
            }
        case RouteTarget.WEATHER_LOOKUP:
            # Args: (location,)
            return {
                "location": utility_match.args[0].strip(),
            }
        case RouteTarget.TIMEZONE_INFO:
            # Args: (location,)
            return {
                "location": utility_match.args[0].strip(),
            }
        case RouteTarget.GET_BOOKING:
            # Args: (booking_id,)
            return {
                "booking_id": utility_match.args[0],
            }
        case RouteTarget.GET_CONSULTATION:
            # Args: (consultation_id,)
            return {
                "consultation_id": utility_match.args[0],
            }
        case _:
            return {}


async def _route_with_llm(
    message: str,
    session_id: str,
    llm: "OrchestratorLLM",
) -> "RunResult":
    """Use LLM to make routing decision (Layer 1c).

    Per design doc, the LLM sees 7 tools at Layer 1c:
    - workflow_turn: Start new trip planning session
    - answer_question: General travel question (no context)
    - currency_convert: Currency conversion (LLM fallback for regex miss)
    - weather_lookup: Weather query (LLM fallback for regex miss)
    - timezone_info: Timezone query (LLM fallback for regex miss)
    - get_booking: Booking lookup (LLM fallback for regex miss)
    - get_consultation: Consultation lookup (LLM fallback for regex miss)

    Args:
        message: The user message
        session_id: The session identifier
        llm: The OrchestratorLLM instance

    Returns:
        RunResult with the LLM's routing decision
    """
    from src.orchestrator.azure_agent import AgentType

    # Get/create thread for routing decisions
    thread_id = llm.ensure_thread_exists(session_id, AgentType.ROUTER)

    # Create run with the routing agent
    run_result = await llm.create_run(thread_id, AgentType.ROUTER, message)

    logger.debug(
        "Layer 1c LLM result: status=%s, tool_calls=%d",
        run_result.status,
        len(run_result.tool_calls),
    )

    return run_result


def _parse_llm_routing_decision(
    run_result: "RunResult",
    session_id: str,
    message: str,
) -> tuple[RouteTarget, dict[str, Any]]:
    """Parse the LLM's routing decision from run result.

    Args:
        run_result: The RunResult from LLM
        session_id: The session identifier
        message: The original user message

    Returns:
        Tuple of (RouteTarget, tool_args)
    """
    # Handle run failures
    if run_result.has_failed:
        logger.error("LLM routing failed: %s", run_result.error_message)
        # Default to workflow_turn on failure (start new session)
        return RouteTarget.WORKFLOW_TURN, {
            "session_ref": {"session_id": session_id},
            "message": message,
        }

    # Handle completed run (no tool calls - pure text response)
    if run_result.is_completed and not run_result.tool_calls:
        # LLM generated text without calling a tool
        # This shouldn't happen with proper prompting, but handle gracefully
        logger.warning("LLM completed without tool call, defaulting to answer_question")
        return RouteTarget.ANSWER_QUESTION, {
            "question": message,
            "domain": "general",
        }

    # Handle tool calls
    if run_result.tool_calls:
        tool_call = run_result.tool_calls[0]  # Take first tool call
        tool_name = tool_call.name
        tool_args = tool_call.arguments

        logger.debug("LLM routing decision: tool=%s, args=%s", tool_name, tool_args)

        # Map tool name to RouteTarget
        target_map = {
            "workflow_turn": RouteTarget.WORKFLOW_TURN,
            "answer_question": RouteTarget.ANSWER_QUESTION,
            "currency_convert": RouteTarget.CURRENCY_CONVERT,
            "weather_lookup": RouteTarget.WEATHER_LOOKUP,
            "timezone_info": RouteTarget.TIMEZONE_INFO,
        }

        target = target_map.get(tool_name, RouteTarget.WORKFLOW_TURN)

        # Ensure session_ref is set for workflow_turn
        if target == RouteTarget.WORKFLOW_TURN:
            if "session_ref" not in tool_args or tool_args["session_ref"] is None:
                tool_args["session_ref"] = {"session_id": session_id}
            if "message" not in tool_args or not tool_args["message"]:
                tool_args["message"] = message

        return target, tool_args

    # Fallback: requires_action but no tool_calls (shouldn't happen)
    logger.warning("LLM routing in unexpected state, defaulting to workflow_turn")
    return RouteTarget.WORKFLOW_TURN, {
        "session_ref": {"session_id": session_id},
        "message": message,
    }
