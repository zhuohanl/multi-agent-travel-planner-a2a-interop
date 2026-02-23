"""
A2A-Azure Bridge inbound module.

This module handles boundaries #1 and #4 from the design doc:
  - Boundary #1: A2A Request → Azure AI (extract message/session for create_run())
  - Boundary #4: Azure AI response → A2A Response (wrap final response in A2A envelope)

The inbound bridge converts incoming A2A protocol requests into the format needed
by Azure AI Agent Service, and converts Azure AI responses back into A2A protocol
format for the client.

Key concepts:
  - A2A Request contains: message, session_id, context_id, task_id, metadata
  - Azure AI needs: message text, thread_id (managed separately)
  - A2A Response contains: text, context_id, task_id, status, metadata
  - Azure AI returns: text content, tool_calls, run status

Usage:
    from src.shared.a2a_azure_bridge.inbound import (
        translate_a2a_to_azure,
        translate_azure_to_a2a,
    )

    # Boundary #1: A2A Request → Azure AI
    azure_input = translate_a2a_to_azure(a2a_request)
    # Use azure_input.message and azure_input.session_id with Azure AI Agent

    # Boundary #4: Azure AI response → A2A Response
    a2a_response = translate_azure_to_a2a(azure_response, context_id="...")
    # Return a2a_response to the A2A client
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class AzureAIInput:
    """Input format for Azure AI Agent Service create_run().

    This dataclass captures the essential data extracted from an A2A request
    that Azure AI Agent needs to process the request.

    Attributes:
        message: The user's message text
        session_id: Session identifier for thread management
        context_id: Optional A2A context ID (preserved for response)
        task_id: Optional A2A task ID (preserved for response)
        metadata: Optional metadata from the A2A request
    """

    message: str
    session_id: str
    context_id: str | None = None
    task_id: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class A2AResponseEnvelope:
    """A2A protocol response envelope.

    This dataclass represents the response format expected by A2A clients.
    It wraps the Azure AI response in the standard A2A protocol format.

    Attributes:
        text: The response text content
        context_id: A2A context ID for multi-turn conversations
        task_id: Optional task ID within the context
        is_complete: Whether the task is complete
        requires_input: Whether the agent requires user input
        status: Response status (completed, input_required, working)
        metadata: Optional response metadata
    """

    text: str
    context_id: str | None = None
    task_id: str | None = None
    is_complete: bool = False
    requires_input: bool = False
    status: str = "working"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to A2A protocol response format.

        Returns:
            Dictionary in A2A protocol format
        """
        result: dict[str, Any] = {
            "message": {
                "role": "assistant",
                "parts": [{"kind": "text", "text": self.text}],
                "messageId": uuid4().hex,
            },
            "status": {
                "state": self.status,
                "message": {
                    "role": "assistant",
                    "parts": [{"kind": "text", "text": self.text}],
                },
            },
        }

        if self.context_id:
            result["contextId"] = self.context_id

        if self.task_id:
            result["taskId"] = self.task_id

        if self.metadata:
            result["metadata"] = self.metadata

        return result


@dataclass
class AzureStreamingChunk:
    """A chunk from Azure AI streaming response.

    Attributes:
        text: Text content in this chunk (may be partial)
        is_final: Whether this is the final chunk
        tool_calls: Any tool calls in this chunk
        run_status: Status of the run (e.g., 'completed', 'requires_action')
    """

    text: str = ""
    is_final: bool = False
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    run_status: str | None = None


# =============================================================================
# BOUNDARY #1: A2A REQUEST → AZURE AI INPUT
# =============================================================================


def translate_a2a_to_azure(a2a_request: dict[str, Any]) -> AzureAIInput:
    """Translate A2A protocol request to Azure AI Agent input format.

    This function implements Boundary #1: extracting the message and session
    information from an A2A request for use with Azure AI Agent Service's
    create_run() method.

    Args:
        a2a_request: A2A protocol request dictionary. Expected structure:
            {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "..."}],
                    "contextId": "...",  # optional
                    "taskId": "...",  # optional
                    "metadata": {...},  # optional
                },
                "sessionId": "...",  # optional, from params
            }

    Returns:
        AzureAIInput with extracted message and session information

    Raises:
        ValueError: If the request is missing required fields

    Example:
        >>> request = {
        ...     "message": {
        ...         "role": "user",
        ...         "parts": [{"kind": "text", "text": "Plan a trip to Tokyo"}],
        ...         "contextId": "ctx_123",
        ...     },
        ...     "sessionId": "sess_abc",
        ... }
        >>> result = translate_a2a_to_azure(request)
        >>> result.message
        'Plan a trip to Tokyo'
        >>> result.session_id
        'sess_abc'
        >>> result.context_id
        'ctx_123'
    """
    # Extract message object
    message_obj = a2a_request.get("message", {})
    if not message_obj:
        raise ValueError("A2A request missing 'message' field")

    # Extract text from message parts
    parts = message_obj.get("parts", [])
    text_parts = []
    for part in parts:
        if isinstance(part, dict) and part.get("kind") == "text":
            text_parts.append(part.get("text", ""))
        elif isinstance(part, str):
            text_parts.append(part)

    message_text = " ".join(text_parts).strip()
    if not message_text:
        raise ValueError("A2A request message has no text content")

    # Extract session_id from multiple possible locations
    session_id = (
        a2a_request.get("sessionId")
        or a2a_request.get("session_id")
        or message_obj.get("sessionId")
        or message_obj.get("session_id")
    )

    # Generate session_id if not provided (new session)
    if not session_id:
        session_id = f"sess_{uuid4().hex}"
        logger.debug("Generated new session_id: %s", session_id)

    # Extract context_id and task_id (for multi-turn)
    context_id = message_obj.get("contextId") or message_obj.get("context_id")
    task_id = message_obj.get("taskId") or message_obj.get("task_id")

    # Extract metadata
    metadata = message_obj.get("metadata")

    logger.debug(
        "Translated A2A request: session=%s, context=%s, task=%s, message_len=%d",
        session_id,
        context_id,
        task_id,
        len(message_text),
    )

    return AzureAIInput(
        message=message_text,
        session_id=session_id,
        context_id=context_id,
        task_id=task_id,
        metadata=metadata,
    )


# =============================================================================
# BOUNDARY #4: AZURE AI RESPONSE → A2A RESPONSE
# =============================================================================


def translate_azure_to_a2a(
    azure_response: dict[str, Any] | str,
    context_id: str | None = None,
    task_id: str | None = None,
    is_complete: bool = True,
    requires_input: bool = False,
    metadata: dict[str, Any] | None = None,
) -> A2AResponseEnvelope:
    """Translate Azure AI Agent response to A2A protocol format.

    This function implements Boundary #4: wrapping the Azure AI response
    in an A2A protocol envelope for return to the A2A client.

    Args:
        azure_response: Azure AI response. Can be:
            - A string (final text response)
            - A dict with 'content' or 'text' field
            - A dict with 'messages' array (conversation format)
        context_id: A2A context ID to include in response
        task_id: A2A task ID to include in response
        is_complete: Whether the task is complete
        requires_input: Whether agent requires user input
        metadata: Additional metadata for the response

    Returns:
        A2AResponseEnvelope wrapping the response

    Example:
        >>> response = translate_azure_to_a2a(
        ...     "Here's your trip plan...",
        ...     context_id="ctx_123",
        ...     is_complete=True,
        ... )
        >>> response.text
        "Here's your trip plan..."
        >>> response.status
        'completed'
    """
    # Extract text from various Azure response formats
    text = _extract_azure_response_text(azure_response)

    # Determine status
    if is_complete:
        status = "completed"
    elif requires_input:
        status = "input_required"
    else:
        status = "working"

    return A2AResponseEnvelope(
        text=text,
        context_id=context_id,
        task_id=task_id,
        is_complete=is_complete,
        requires_input=requires_input,
        status=status,
        metadata=metadata or {},
    )


def translate_azure_streaming_chunk(
    chunk: dict[str, Any] | str,
    context_id: str | None = None,
    task_id: str | None = None,
) -> A2AResponseEnvelope:
    """Translate a streaming chunk from Azure AI to A2A format.

    This function handles individual streaming chunks, which may contain
    partial text or status updates.

    Args:
        chunk: A streaming chunk from Azure AI. Can be:
            - A string (text content)
            - A dict with 'delta', 'content', or 'text' field
            - A dict with run status information
        context_id: A2A context ID to include
        task_id: A2A task ID to include

    Returns:
        A2AResponseEnvelope for this chunk

    Example:
        >>> chunk = {"delta": {"content": "Planning..."}}
        >>> response = translate_azure_streaming_chunk(chunk, context_id="ctx_123")
        >>> response.text
        'Planning...'
        >>> response.status
        'working'
    """
    # Parse the streaming chunk
    parsed = _parse_azure_streaming_chunk(chunk)

    # Determine status from chunk
    if parsed.is_final:
        status = "completed"
    elif parsed.run_status == "requires_action":
        status = "input_required"
    else:
        status = "working"

    return A2AResponseEnvelope(
        text=parsed.text,
        context_id=context_id,
        task_id=task_id,
        is_complete=parsed.is_final,
        requires_input=parsed.run_status == "requires_action",
        status=status,
    )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _extract_azure_response_text(response: dict[str, Any] | str) -> str:
    """Extract text content from various Azure response formats.

    Args:
        response: Azure AI response in various formats

    Returns:
        Extracted text content
    """
    if isinstance(response, str):
        return response

    if not isinstance(response, dict):
        return str(response)

    # Try various keys Azure might use
    # Direct text content
    if "content" in response:
        content = response["content"]
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            # Content array format
            return _extract_text_from_content_array(content)

    if "text" in response:
        return response["text"]

    # Message format (assistant message)
    if "message" in response:
        return _extract_azure_response_text(response["message"])

    # Messages array format (conversation)
    if "messages" in response:
        messages = response["messages"]
        if isinstance(messages, list) and messages:
            # Get the last assistant message
            for msg in reversed(messages):
                if isinstance(msg, dict) and msg.get("role") == "assistant":
                    return _extract_azure_response_text(msg)
            # Fallback to last message regardless of role
            return _extract_azure_response_text(messages[-1])

    # Tool output format
    if "output" in response:
        return str(response["output"])

    # Run result format
    if "result" in response:
        return _extract_azure_response_text(response["result"])

    # Value format (from run)
    if "value" in response:
        return _extract_azure_response_text(response["value"])

    # Fallback: stringify the response
    logger.warning("Could not extract text from Azure response: %s", response)
    return str(response)


def _extract_text_from_content_array(content: list[Any]) -> str:
    """Extract text from a content array (OpenAI message format).

    Args:
        content: Array of content items

    Returns:
        Concatenated text content
    """
    text_parts = []
    for item in content:
        if isinstance(item, str):
            text_parts.append(item)
        elif isinstance(item, dict):
            if item.get("type") == "text":
                text_parts.append(item.get("text", ""))
            elif "text" in item:
                text_parts.append(item["text"])
    return " ".join(text_parts).strip()


def _parse_azure_streaming_chunk(chunk: dict[str, Any] | str) -> AzureStreamingChunk:
    """Parse a streaming chunk from Azure AI.

    Args:
        chunk: Streaming chunk in various formats

    Returns:
        Parsed AzureStreamingChunk
    """
    if isinstance(chunk, str):
        return AzureStreamingChunk(text=chunk)

    if not isinstance(chunk, dict):
        return AzureStreamingChunk(text=str(chunk))

    text = ""
    is_final = False
    tool_calls: list[dict[str, Any]] = []
    run_status = None

    # Delta format (streaming completions)
    if "delta" in chunk:
        delta = chunk["delta"]
        if isinstance(delta, dict):
            text = delta.get("content", "") or ""
            if "tool_calls" in delta:
                tool_calls = delta["tool_calls"]

    # Choices format (completions API)
    elif "choices" in chunk:
        choices = chunk["choices"]
        if isinstance(choices, list) and choices:
            choice = choices[0]
            if isinstance(choice, dict):
                if "delta" in choice:
                    delta = choice["delta"]
                    text = delta.get("content", "") or ""
                elif "message" in choice:
                    text = _extract_azure_response_text(choice["message"])
                # Check finish_reason
                if choice.get("finish_reason"):
                    is_final = True

    # Direct content
    elif "content" in chunk:
        text = chunk["content"] if isinstance(chunk["content"], str) else ""

    elif "text" in chunk:
        text = chunk["text"]

    # Run status
    if "status" in chunk:
        run_status = chunk["status"]
        if run_status in ("completed", "failed", "cancelled"):
            is_final = True

    # Tool calls
    if "tool_calls" in chunk and not tool_calls:
        tool_calls = chunk["tool_calls"]

    # Requires action indicator
    if "required_action" in chunk or run_status == "requires_action":
        run_status = "requires_action"

    return AzureStreamingChunk(
        text=text,
        is_final=is_final,
        tool_calls=tool_calls,
        run_status=run_status,
    )
