"""
Weather Proxy - Hosted Agent that calls Copilot Studio Weather Agent

This agent:
1. Receives requests via the /responses protocol
2. Forwards the user message to CS Weather Agent (LLM handles parameter extraction)
3. Parses the JSON response and returns WeatherResponse

Design doc references:
- INTEROP-011B Implementation Details (lines 2285-2423)
- Reference: https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-direct-line-3-0-concepts
"""

import asyncio
import datetime
import json
import logging
import os
import platform
import re
from typing import Any, AsyncGenerator, Optional

import aiohttp
from dotenv import load_dotenv

# Azure AI Agent Server imports
from azure.ai.agentserver.core import AgentRunContext
from azure.ai.agentserver.core.models import Response as OpenAIResponse, ResponseStreamEvent
from azure.ai.agentserver.core.models.projects import (
    ItemContentOutputText,
    ResponseCompletedEvent,
    ResponseContentPartAddedEvent,
    ResponseContentPartDoneEvent,
    ResponseCreatedEvent,
    ResponseInProgressEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponsesAssistantMessageItemResource,
    ResponseTextDeltaEvent,
    ResponseTextDoneEvent,
)
from azure.ai.agentserver.core.server.base import FoundryCBAgent

# Import shared schema (do NOT duplicate)
from src.shared.models import WeatherResponse

load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)
logger.info(
    "Weather Proxy module loaded (pid=%s, python=%s)",
    os.getpid(),
    platform.python_version(),
)

DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = 1.0


def _require_env(name: str) -> str:
    """Get required environment variable or raise error."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} environment variable must be set.")
    return value


# Environment variable for Direct Line secret
def get_directline_secret() -> str:
    """Get Direct Line secret from Copilot Studio Web channel security."""
    return _require_env("COPILOTSTUDIOAGENT__DIRECTLINE_SECRET")


# Direct Line API base URL
DIRECTLINE_BASE_URL = "https://directline.botframework.com/v3/directline"


def extract_user_message(messages: list[dict[str, Any]]) -> str:
    """Extract user message text from messages list.

    Handles string content and list-based content parts (multi-modal format).
    """
    if not messages:
        return ""

    content = messages[-1].get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            if item.get("type") in {"text", "input_text", "output_text"}:
                text_val = item.get("text")
                if isinstance(text_val, dict):
                    text_val = text_val.get("value")
                if isinstance(text_val, str):
                    text_parts.append(text_val)
                    continue
            text_val = item.get("text")
            if isinstance(text_val, str):
                text_parts.append(text_val)
        return " ".join(part.strip() for part in text_parts if part).strip()
    return ""


async def call_weather_agent(user_message: str) -> str:
    """Call CS Weather Agent via Direct Line API and return raw response.

    The CS Weather Agent LLM handles parameter extraction from the user message.
    It can understand various formats like:
    - "Get weather for Paris from 2025-06-15 to 2025-06-20"
    - "destination_city: Bali, start_date: 2026-06-01, end_date: 2026-06-05"
    - JSON: {"location": "Tokyo", "start_date": "...", "end_date": "..."}

    Args:
        user_message: The raw user message to forward to CS Weather Agent.

    Returns:
        Raw response text from the CS Weather Agent.

    Raises:
        RuntimeError: If the agent call fails.
    """
    secret = get_directline_secret()

    # Add instruction for JSON response format
    prompt = f"{user_message}\n\nPlease provide the weather/climate information as JSON."
    logger.info("Sending message to CS Weather Agent: %s", prompt[:200])

    async with aiohttp.ClientSession() as session:
        # Step 1: Start conversation
        start_url = f"{DIRECTLINE_BASE_URL}/conversations"
        headers = {
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        }

        async with session.post(start_url, headers=headers) as resp:
            if resp.status != 201:
                text = await resp.text()
                raise RuntimeError(f"Failed to start conversation: {resp.status} - {text}")
            conv_data = await resp.json()

        conversation_id = conv_data["conversationId"]
        conv_token = conv_data.get("token", secret)
        logger.info("Started conversation: %s", conversation_id)

        # Step 2: Send message to the bot
        activities_url = f"{DIRECTLINE_BASE_URL}/conversations/{conversation_id}/activities"
        message_headers = {
            "Authorization": f"Bearer {conv_token}",
            "Content-Type": "application/json",
        }
        message_payload = {
            "type": "message",
            "from": {"id": "weather-proxy"},
            "text": prompt,
        }

        async with session.post(activities_url, headers=message_headers, json=message_payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Failed to send message: {resp.status} - {text}")
            send_result = await resp.json()

        logger.info("Message sent, activity ID: %s", send_result.get("id"))

        # Step 3: Poll for bot response
        watermark = None
        response_text = ""
        max_polls = 30  # Max 30 attempts (30 seconds with 1s delay)

        for _ in range(max_polls):
            poll_url = f"{DIRECTLINE_BASE_URL}/conversations/{conversation_id}/activities"
            if watermark:
                poll_url += f"?watermark={watermark}"

            async with session.get(poll_url, headers=message_headers) as resp:
                if resp.status != 200:
                    await asyncio.sleep(1)
                    continue
                activities_data = await resp.json()

            watermark = activities_data.get("watermark")
            activities = activities_data.get("activities", [])

            # Look for bot responses (not from our user)
            for activity in activities:
                if activity.get("type") == "message":
                    from_id = activity.get("from", {}).get("id", "")
                    if from_id != "weather-proxy" and activity.get("text"):
                        response_text = activity.get("text", "")
                        logger.info("Received response from CS Weather Agent (length=%d)", len(response_text))
                        break

            if response_text:
                break

            await asyncio.sleep(1)

        if not response_text:
            raise RuntimeError("No response received from CS Weather Agent")

    return response_text


def extract_json_from_response(response_text: str) -> dict[str, Any]:
    """Extract JSON from response text.

    Handles cases where JSON is:
    - Plain JSON string
    - Embedded in markdown code blocks (```json ... ```)
    - Mixed with natural language text
    """
    # Try direct JSON parsing
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    json_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response_text)
    if json_block_match:
        try:
            return json.loads(json_block_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding JSON object anywhere in text
    json_match = re.search(r"\{[\s\S]*\}", response_text)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract JSON from response: {response_text[:200]}...")


def _extract_messages(request: Any) -> list[dict[str, Any]]:
    """Extract messages array from a Foundry /responses request."""
    if isinstance(request, dict):
        input_data = request.get("input", [])
        if isinstance(input_data, list):
            return input_data
        if isinstance(input_data, dict):
            return input_data.get("messages", []) or []
        return []
    if isinstance(request, list):
        return request
    return []


def _build_created_by(context: AgentRunContext) -> dict[str, Any]:
    agent = context.get_agent_id_object()
    agent_dict = {
        "type": "agent_id",
        "name": getattr(agent, "name", "") if agent else "",
        "version": getattr(agent, "version", "") if agent else "",
    }
    return {
        "agent": agent_dict,
        "response_id": context.response_id,
    }


def _build_openai_response(
    context: AgentRunContext,
    text: str,
    created_at: Optional[int] = None,
    output_items: Optional[list[Any]] = None,
) -> OpenAIResponse:
    if created_at is None:
        created_at = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    agent_id = context.get_agent_id_object()
    content_part = ItemContentOutputText(text=text, annotations=[], logprobs=[])
    item_id = context.id_generator.generate_message_id()
    item = ResponsesAssistantMessageItemResource(
        id=item_id,
        status="completed",
        content=[content_part],
        created_by=_build_created_by(context),
    )
    output = output_items if output_items is not None else [item]
    response_data = {
        "object": "response",
        "metadata": context.request.get("metadata") or {},
        "agent": agent_id,
        "conversation": context.get_conversation_object(),
        "type": "message",
        "role": "assistant",
        "temperature": DEFAULT_TEMPERATURE,
        "top_p": DEFAULT_TOP_P,
        "user": "",
        "id": context.response_id,
        "created_at": created_at,
        "output": output,
        "parallel_tool_calls": True,
        "status": "completed",
    }
    return OpenAIResponse(response_data)


async def _stream_text_response(
    context: AgentRunContext,
    text: str,
) -> AsyncGenerator[ResponseStreamEvent, Any]:
    created_at = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    agent_id = context.get_agent_id_object()
    created_by = _build_created_by(context)
    response_base = OpenAIResponse(
        {
            "object": "response",
            "metadata": context.request.get("metadata") or {},
            "agent": agent_id,
            "conversation": context.get_conversation_object(),
            "type": "message",
            "role": "assistant",
            "temperature": DEFAULT_TEMPERATURE,
            "top_p": DEFAULT_TOP_P,
            "user": "",
            "id": context.response_id,
            "created_at": created_at,
            "status": "in_progress",
        }
    )

    sequence = 0
    output_index = 0
    item_id = context.id_generator.generate_message_id()

    yield ResponseCreatedEvent(sequence_number=sequence, response=response_base)
    sequence += 1
    yield ResponseInProgressEvent(sequence_number=sequence, response=response_base)
    sequence += 1

    in_progress_item = ResponsesAssistantMessageItemResource(
        id=item_id,
        status="in_progress",
        content=[],
        created_by=created_by,
    )
    yield ResponseOutputItemAddedEvent(
        sequence_number=sequence,
        output_index=output_index,
        item=in_progress_item,
    )
    sequence += 1

    empty_part = ItemContentOutputText(text="", annotations=[], logprobs=[])
    yield ResponseContentPartAddedEvent(
        sequence_number=sequence,
        item_id=item_id,
        output_index=output_index,
        content_index=0,
        part=empty_part,
    )
    sequence += 1

    yield ResponseTextDeltaEvent(
        sequence_number=sequence,
        item_id=item_id,
        output_index=output_index,
        content_index=0,
        delta=text,
    )
    sequence += 1

    yield ResponseTextDoneEvent(
        sequence_number=sequence,
        item_id=item_id,
        output_index=output_index,
        content_index=0,
        text=text,
    )
    sequence += 1

    final_part = ItemContentOutputText(text=text, annotations=[], logprobs=[])
    yield ResponseContentPartDoneEvent(
        sequence_number=sequence,
        item_id=item_id,
        output_index=output_index,
        content_index=0,
        part=final_part,
    )
    sequence += 1

    completed_item = ResponsesAssistantMessageItemResource(
        id=item_id,
        status="completed",
        content=[final_part],
        created_by=created_by,
    )
    yield ResponseOutputItemDoneEvent(
        sequence_number=sequence,
        output_index=output_index,
        item=completed_item,
    )
    sequence += 1

    response_completed = OpenAIResponse(
        {
            "object": "response",
            "metadata": context.request.get("metadata") or {},
            "agent": agent_id,
            "conversation": context.get_conversation_object(),
            "type": "message",
            "role": "assistant",
            "temperature": DEFAULT_TEMPERATURE,
            "top_p": DEFAULT_TOP_P,
            "user": "",
            "id": context.response_id,
            "created_at": created_at,
            "output": [completed_item],
            "parallel_tool_calls": True,
            "status": "completed",
        }
    )
    yield ResponseCompletedEvent(sequence_number=sequence, response=response_completed)


class WeatherProxyAgent(FoundryCBAgent):
    """Weather Proxy agent that calls Copilot Studio Weather Agent."""

    async def agent_run(
        self, context: AgentRunContext
    ) -> OpenAIResponse | AsyncGenerator[ResponseStreamEvent, Any]:
        """Handle incoming request from Foundry workflow.

        Args:
            context: The agent run context containing the request.

        Returns:
            Response object for non-streaming, async generator for streaming.
        """
        # Get messages from the request
        request = context.raw_payload if hasattr(context, "raw_payload") else context.request
        messages = _extract_messages(request)

        # Process the request
        if not messages:
            output_text = "Error: No messages in request"
        else:
            user_message = extract_user_message(messages)
            if not user_message:
                output_text = "Error: Empty message content"
            else:
                logger.info("Processing request: %s", user_message[:200])
                try:
                    # Forward message to CS Weather Agent (LLM handles parameter extraction)
                    response_text = await call_weather_agent(user_message)

                    # Extract and validate JSON response
                    weather_data = extract_json_from_response(response_text)
                    weather = WeatherResponse(**weather_data)
                    output_text = json.dumps(weather.model_dump())
                except Exception as e:
                    logger.exception("Weather agent call failed")
                    output_text = f"Error: {str(e)}"

        if getattr(context, "stream", False):
            return _stream_text_response(context, output_text)

        return _build_openai_response(context, output_text)


def main() -> None:
    """Start the hosted agent server."""
    port = int(os.getenv("PORT", os.getenv("DEFAULT_AD_PORT", "8088")))
    logger.info("Starting Weather Proxy on port %s", port)

    try:
        agent = WeatherProxyAgent()
        agent.run(port=port)
    except Exception:
        logger.exception("Weather Proxy server failed to start")
        raise


if __name__ == "__main__":
    main()
