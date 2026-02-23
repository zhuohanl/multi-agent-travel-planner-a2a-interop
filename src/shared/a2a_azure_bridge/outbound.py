"""
A2A-Azure Bridge outbound module.

This module handles boundaries #2 and #3 from the design doc:
  - Boundary #2: Tool handler → A2A Client (convert tool args to A2A request)
  - Boundary #3: A2A Response → Tool output (convert AgentResponse to string for Azure AI)

The outbound bridge converts tool call arguments from Azure AI Agent Service into
the format needed by downstream A2A agents, and converts A2A responses back into
tool output strings that Azure AI Agent can consume.

Key concepts:
  - Tool args contain: tool name, session_ref, message, event (for workflow_turn)
  - A2A request needs: message text, context_id, task_id, history
  - A2A response contains: text, context_id, task_id, is_complete
  - Tool output is: JSON string with response data

Usage:
    from src.shared.a2a_azure_bridge.outbound import (
        translate_tool_args_to_a2a,
        translate_a2a_to_tool_output,
    )

    # Boundary #2: Tool args → A2A request
    a2a_request = translate_tool_args_to_a2a("workflow_turn", tool_args)
    # Use a2a_request with A2AClientWrapper.send_message()

    # Boundary #3: A2A response → Tool output
    tool_output = translate_a2a_to_tool_output(a2a_response)
    # Return tool_output to Azure AI Agent's submit_tool_outputs()
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class A2AOutboundRequest:
    """Request format for A2A client send_message().

    This dataclass captures the data extracted from Azure AI tool arguments
    that needs to be sent to a downstream A2A agent.

    Attributes:
        message: The message text to send to the agent
        context_id: Optional A2A context ID for multi-turn conversations
        task_id: Optional A2A task ID for task continuation
        history: Optional conversation history for reliability
        history_seq: Sequence number for divergence detection
        metadata: Optional additional metadata for the agent
    """

    message: str
    context_id: str | None = None
    task_id: str | None = None
    history: list[dict[str, Any]] | None = None
    history_seq: int = 0
    metadata: dict[str, Any] | None = None


@dataclass
class ToolOutput:
    """Tool output format for Azure AI Agent's submit_tool_outputs().

    This dataclass represents the response format that Azure AI Agent
    expects when a tool call completes.

    Attributes:
        tool_call_id: The ID of the tool call this output corresponds to
        output: The string output to return to Azure AI Agent
    """

    tool_call_id: str
    output: str

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary for API submission."""
        return {
            "tool_call_id": self.tool_call_id,
            "output": self.output,
        }


@dataclass
class A2AToolResponse:
    """Parsed A2A response ready for tool output conversion.

    Attributes:
        success: Whether the agent call succeeded
        message: The response text from the agent
        context_id: A2A context ID from the response
        task_id: A2A task ID from the response
        is_complete: Whether the agent task is complete
        requires_input: Whether the agent requires user input
        data: Additional structured data from the response
        error_code: Error code if success is False
    """

    success: bool = True
    message: str = ""
    context_id: str | None = None
    task_id: str | None = None
    is_complete: bool = False
    requires_input: bool = False
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None


# =============================================================================
# TOOL TYPE CONSTANTS
# =============================================================================

# Tools that operate on workflow state (require session_ref)
WORKFLOW_TOOLS: frozenset[str] = frozenset({
    "workflow_turn",
})

# Utility tools that can be stateless
UTILITY_TOOLS: frozenset[str] = frozenset({
    "answer_question",
    "currency_convert",
    "weather_lookup",
    "timezone_info",
    "get_booking",
    "get_consultation",
})

# All recognized tool names
ALL_TOOLS: frozenset[str] = WORKFLOW_TOOLS | UTILITY_TOOLS


# =============================================================================
# BOUNDARY #2: TOOL ARGS → A2A REQUEST
# =============================================================================


def translate_tool_args_to_a2a(
    tool_name: str,
    args: dict[str, Any],
) -> A2AOutboundRequest:
    """Translate Azure AI tool arguments to A2A request format.

    This function implements Boundary #2: converting tool call arguments
    from Azure AI Agent Service into the format needed by downstream A2A
    agents via A2AClientWrapper.send_message().

    Args:
        tool_name: The name of the tool being called. Must be one of:
            - workflow_turn: Main workflow handler
            - answer_question: Q&A tool
            - currency_convert, weather_lookup, timezone_info: Utility tools
            - get_booking, get_consultation: Lookup tools
        args: Tool arguments from Azure AI. Structure depends on tool:
            workflow_turn: {session_ref, message, event}
            answer_question: {question, domain, context}
            currency_convert: {amount, from_currency, to_currency}
            weather_lookup: {location, date}
            timezone_info: {location, date}
            get_booking: {booking_id}
            get_consultation: {consultation_id}

    Returns:
        A2AOutboundRequest ready for A2AClientWrapper.send_message()

    Raises:
        ValueError: If tool_name is not recognized or args are invalid

    Example:
        >>> args = {
        ...     "message": "Plan a trip to Tokyo",
        ...     "session_ref": {"session_id": "sess_123"},
        ...     "event": {"type": "free_text"},
        ... }
        >>> request = translate_tool_args_to_a2a("workflow_turn", args)
        >>> request.message
        'Plan a trip to Tokyo'
    """
    # Validate tool name
    if tool_name not in ALL_TOOLS:
        raise ValueError(f"Unknown tool: {tool_name}. Expected one of: {sorted(ALL_TOOLS)}")

    logger.debug(
        "Translating tool args to A2A: tool=%s, arg_keys=%s",
        tool_name,
        list(args.keys()),
    )

    # Route to tool-specific translator
    if tool_name == "workflow_turn":
        return _translate_workflow_turn_args(args)
    elif tool_name == "answer_question":
        return _translate_answer_question_args(args)
    elif tool_name == "currency_convert":
        return _translate_currency_convert_args(args)
    elif tool_name == "weather_lookup":
        return _translate_weather_lookup_args(args)
    elif tool_name == "timezone_info":
        return _translate_timezone_info_args(args)
    elif tool_name == "get_booking":
        return _translate_get_booking_args(args)
    elif tool_name == "get_consultation":
        return _translate_get_consultation_args(args)
    else:
        # Should not reach here due to validation above
        raise ValueError(f"Unhandled tool: {tool_name}")


def _translate_workflow_turn_args(args: dict[str, Any]) -> A2AOutboundRequest:
    """Translate workflow_turn tool arguments to A2A request.

    workflow_turn is the main workflow handler that routes messages through
    the clarification, discovery, and booking phases.

    Expected args:
        message: str - The user's message
        session_ref: dict - Optional session identifiers
        event: dict - Optional structured event
    """
    message = args.get("message", "")
    if not message:
        raise ValueError("workflow_turn requires 'message' argument")

    session_ref = args.get("session_ref", {}) or {}
    event = args.get("event")

    # Build message with event info if present
    # The downstream agent will parse this from the message or metadata
    full_message = message

    # Extract context_id and task_id from session_ref if present
    # These map to A2A's multi-turn conversation tracking
    context_id = None
    task_id = None

    # session_ref may contain agent_context_ids which track per-agent contexts
    agent_context_ids = session_ref.get("agent_context_ids", {})
    if agent_context_ids:
        # Use clarifier context_id for workflow_turn (primary multi-turn agent)
        context_id = agent_context_ids.get("clarifier")

    # Extract history from args if provided
    history = args.get("history")
    history_seq = args.get("history_seq", 0)

    # Build metadata with session_ref and event for downstream processing
    metadata: dict[str, Any] = {}
    if session_ref:
        metadata["session_ref"] = session_ref
    if event:
        metadata["event"] = event

    logger.debug(
        "Translated workflow_turn: message_len=%d, context_id=%s, has_event=%s",
        len(full_message),
        context_id,
        event is not None,
    )

    return A2AOutboundRequest(
        message=full_message,
        context_id=context_id,
        task_id=task_id,
        history=history,
        history_seq=history_seq,
        metadata=metadata if metadata else None,
    )


def _translate_answer_question_args(args: dict[str, Any]) -> A2AOutboundRequest:
    """Translate answer_question tool arguments to A2A request.

    answer_question routes questions to domain agents in Q&A mode.

    Expected args:
        question: str - The user's question
        domain: str - Optional domain (poi, stay, transport, events, dining, general, budget)
        context: dict - Optional workflow context for grounded answers
    """
    question = args.get("question", "")
    if not question:
        raise ValueError("answer_question requires 'question' argument")

    domain = args.get("domain", "general")
    context = args.get("context")

    # Build Q&A request as JSON for domain agent
    qa_request: dict[str, Any] = {
        "mode": "qa",
        "question": question,
    }
    if domain:
        qa_request["domain"] = domain
    if context:
        qa_request["context"] = context

    message = json.dumps(qa_request)

    logger.debug(
        "Translated answer_question: domain=%s, question_len=%d",
        domain,
        len(question),
    )

    return A2AOutboundRequest(
        message=message,
        context_id=None,  # Q&A is typically stateless
        task_id=None,
        history=None,
        history_seq=0,
        metadata=None,
    )


def _translate_currency_convert_args(args: dict[str, Any]) -> A2AOutboundRequest:
    """Translate currency_convert tool arguments to A2A request.

    Expected args:
        amount: float - Amount to convert
        from_currency: str - Source currency code (e.g., "USD")
        to_currency: str - Target currency code (e.g., "JPY")
    """
    amount = args.get("amount")
    from_currency = args.get("from_currency", "")
    to_currency = args.get("to_currency", "")

    if amount is None:
        raise ValueError("currency_convert requires 'amount' argument")
    if not from_currency:
        raise ValueError("currency_convert requires 'from_currency' argument")
    if not to_currency:
        raise ValueError("currency_convert requires 'to_currency' argument")

    # Build request message
    request = {
        "tool": "currency_convert",
        "amount": amount,
        "from_currency": from_currency.upper(),
        "to_currency": to_currency.upper(),
    }
    message = json.dumps(request)

    logger.debug(
        "Translated currency_convert: %s %s -> %s",
        amount,
        from_currency,
        to_currency,
    )

    return A2AOutboundRequest(message=message)


def _translate_weather_lookup_args(args: dict[str, Any]) -> A2AOutboundRequest:
    """Translate weather_lookup tool arguments to A2A request.

    Expected args:
        location: str - Location to get weather for
        date: str - Optional date for forecast
    """
    location = args.get("location", "")
    if not location:
        raise ValueError("weather_lookup requires 'location' argument")

    date = args.get("date")

    request: dict[str, Any] = {
        "tool": "weather_lookup",
        "location": location,
    }
    if date:
        request["date"] = date

    message = json.dumps(request)

    logger.debug("Translated weather_lookup: location=%s, date=%s", location, date)

    return A2AOutboundRequest(message=message)


def _translate_timezone_info_args(args: dict[str, Any]) -> A2AOutboundRequest:
    """Translate timezone_info tool arguments to A2A request.

    Expected args:
        location: str - Location to get timezone for
        date: str - Optional date for DST-aware results
    """
    location = args.get("location", "")
    if not location:
        raise ValueError("timezone_info requires 'location' argument")

    date = args.get("date")

    request: dict[str, Any] = {
        "tool": "timezone_info",
        "location": location,
    }
    if date:
        request["date"] = date

    message = json.dumps(request)

    logger.debug("Translated timezone_info: location=%s, date=%s", location, date)

    return A2AOutboundRequest(message=message)


def _translate_get_booking_args(args: dict[str, Any]) -> A2AOutboundRequest:
    """Translate get_booking tool arguments to A2A request.

    Expected args:
        booking_id: str - Booking ID to retrieve
    """
    booking_id = args.get("booking_id", "")
    if not booking_id:
        raise ValueError("get_booking requires 'booking_id' argument")

    request = {
        "tool": "get_booking",
        "booking_id": booking_id,
    }
    message = json.dumps(request)

    logger.debug("Translated get_booking: booking_id=%s", booking_id)

    return A2AOutboundRequest(message=message)


def _translate_get_consultation_args(args: dict[str, Any]) -> A2AOutboundRequest:
    """Translate get_consultation tool arguments to A2A request.

    Expected args:
        consultation_id: str - Consultation ID to retrieve
    """
    consultation_id = args.get("consultation_id", "")
    if not consultation_id:
        raise ValueError("get_consultation requires 'consultation_id' argument")

    request = {
        "tool": "get_consultation",
        "consultation_id": consultation_id,
    }
    message = json.dumps(request)

    logger.debug("Translated get_consultation: consultation_id=%s", consultation_id)

    return A2AOutboundRequest(message=message)


# =============================================================================
# BOUNDARY #3: A2A RESPONSE → TOOL OUTPUT
# =============================================================================


def translate_a2a_to_tool_output(
    response: "A2AToolResponse | dict[str, Any]",
    tool_call_id: str | None = None,
) -> str:
    """Translate A2A response to tool output string for Azure AI.

    This function implements Boundary #3: converting the A2A response
    from a downstream agent into a string format that Azure AI Agent
    Service can consume as tool output.

    Args:
        response: A2A response. Can be:
            - A2AToolResponse dataclass
            - dict with 'success', 'message', and optional 'data', 'context_id', etc.
        tool_call_id: Optional tool call ID for creating ToolOutput

    Returns:
        JSON string representation of the response for Azure AI

    Example:
        >>> response = A2AToolResponse(
        ...     success=True,
        ...     message="Tokyo trip planned!",
        ...     context_id="ctx_123",
        ... )
        >>> output = translate_a2a_to_tool_output(response)
        >>> print(output)
        '{"success": true, "message": "Tokyo trip planned!", ...}'
    """
    # Convert to dict if needed
    if isinstance(response, A2AToolResponse):
        response_dict = _a2a_tool_response_to_dict(response)
    elif isinstance(response, dict):
        response_dict = response
    else:
        # Try to extract from unknown type
        response_dict = _extract_response_dict(response)

    # Serialize to JSON string
    output = json.dumps(response_dict, ensure_ascii=False, default=str)

    logger.debug(
        "Translated A2A response to tool output: success=%s, output_len=%d",
        response_dict.get("success", True),
        len(output),
    )

    return output


def translate_a2a_response_to_tool_response(
    a2a_response: "A2AResponseLike",
) -> A2AToolResponse:
    """Convert an A2A response object to A2AToolResponse.

    This function handles various A2A response formats and normalizes
    them into the A2AToolResponse structure.

    Args:
        a2a_response: Response from A2AClientWrapper.send_message() or similar.
            Expected to have attributes: text, context_id, task_id, is_complete

    Returns:
        A2AToolResponse with normalized fields
    """
    # Handle dict responses
    if isinstance(a2a_response, dict):
        return A2AToolResponse(
            success=a2a_response.get("success", True),
            message=a2a_response.get("message", a2a_response.get("text", "")),
            context_id=a2a_response.get("context_id"),
            task_id=a2a_response.get("task_id"),
            is_complete=a2a_response.get("is_complete", False),
            requires_input=a2a_response.get("requires_input", False),
            data=a2a_response.get("data", {}),
            error_code=a2a_response.get("error_code"),
        )

    # Handle object responses (like A2AResponse from client_wrapper)
    text = getattr(a2a_response, "text", "") or ""
    context_id = getattr(a2a_response, "context_id", None)
    task_id = getattr(a2a_response, "task_id", None)
    is_complete = getattr(a2a_response, "is_complete", False)
    requires_input = getattr(a2a_response, "requires_input", False)

    return A2AToolResponse(
        success=True,
        message=text,
        context_id=context_id,
        task_id=task_id,
        is_complete=is_complete,
        requires_input=requires_input,
        data={},
        error_code=None,
    )


def create_tool_output(
    tool_call_id: str,
    response: "A2AToolResponse | dict[str, Any] | str",
) -> ToolOutput:
    """Create a ToolOutput for Azure AI submit_tool_outputs().

    Args:
        tool_call_id: The ID of the tool call this output corresponds to
        response: The response to convert to output string

    Returns:
        ToolOutput ready for Azure AI Agent Service
    """
    if isinstance(response, str):
        output = response
    else:
        output = translate_a2a_to_tool_output(response)

    return ToolOutput(tool_call_id=tool_call_id, output=output)


def create_error_tool_output(
    tool_call_id: str,
    error_message: str,
    error_code: str | None = None,
) -> ToolOutput:
    """Create a ToolOutput for an error condition.

    Args:
        tool_call_id: The ID of the tool call this output corresponds to
        error_message: Human-readable error message
        error_code: Optional machine-readable error code

    Returns:
        ToolOutput with error information
    """
    response = A2AToolResponse(
        success=False,
        message=error_message,
        error_code=error_code,
    )
    return create_tool_output(tool_call_id, response)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _a2a_tool_response_to_dict(response: A2AToolResponse) -> dict[str, Any]:
    """Convert A2AToolResponse to dictionary for serialization.

    Omits None values for cleaner output.
    """
    result: dict[str, Any] = {
        "success": response.success,
        "message": response.message,
    }

    if response.context_id:
        result["context_id"] = response.context_id
    if response.task_id:
        result["task_id"] = response.task_id
    if response.is_complete:
        result["is_complete"] = response.is_complete
    if response.requires_input:
        result["requires_input"] = response.requires_input
    if response.data:
        result["data"] = response.data
    if response.error_code:
        result["error_code"] = response.error_code

    return result


def _extract_response_dict(response: Any) -> dict[str, Any]:
    """Extract response dictionary from unknown type.

    Handles various response formats by checking for common attributes.
    """
    # Try to get attributes that A2AResponse or similar objects have
    if hasattr(response, "text"):
        return {
            "success": True,
            "message": getattr(response, "text", ""),
            "context_id": getattr(response, "context_id", None),
            "task_id": getattr(response, "task_id", None),
            "is_complete": getattr(response, "is_complete", False),
            "requires_input": getattr(response, "requires_input", False),
        }

    # Try to convert to dict
    if hasattr(response, "__dict__"):
        return {"success": True, "message": str(response), "data": response.__dict__}

    # Fall back to string representation
    return {"success": True, "message": str(response)}


# Type alias for response-like objects
A2AResponseLike = Any  # Could be A2AResponse, dict, or similar
