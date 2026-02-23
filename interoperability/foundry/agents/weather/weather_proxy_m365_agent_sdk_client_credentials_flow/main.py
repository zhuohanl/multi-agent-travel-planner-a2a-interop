"""
Weather Proxy - Hosted Agent that calls Copilot Studio Weather Agent
via M365 Agents SDK using Client Credentials Flow (no interactive user auth).

This agent:
1. Receives requests via the /responses protocol
2. Acquires an app-only token using MSAL ConfidentialClientApplication
3. Forwards the user message to CS Weather Agent via CopilotClient
4. Parses the response and returns WeatherResponse

Prerequisites:
- Azure AD App Registration with:
  - CopilotStudio.Copilots.Invoke as Application permission (not Delegated)
  - Admin consent granted
  - Client secret or certificate configured
"""

import asyncio
import datetime
import json
import logging
import os
import platform
import re
from typing import Any, AsyncGenerator, Optional

from dotenv import load_dotenv
from msal import ConfidentialClientApplication

from microsoft_agents.activity import ActivityTypes
from microsoft_agents.copilotstudio.client import (
    ConnectionSettings,
    CopilotClient,
    PowerPlatformCloud,
)

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

# Import shared schema
from src.shared.models import WeatherResponse

load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)
logger.info(
    "Weather Proxy (M365 SDK Client Credentials) module loaded (pid=%s, python=%s)",
    os.getpid(),
    platform.python_version(),
)

DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = 1.0

# Token scope for Power Platform API
POWER_PLATFORM_SCOPE = "https://api.powerplatform.com/.default"


def _require_env(name: str) -> str:
    """Get required environment variable or raise error."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} environment variable must be set.")
    return value


def acquire_token_client_credentials() -> str:
    """Acquire an app-only token using MSAL client credentials flow.

    Uses ConfidentialClientApplication with client_id + client_secret
    to get a token with CopilotStudio.Copilots.Invoke application permission.

    Returns:
        Access token string.

    Raises:
        RuntimeError: If token acquisition fails.
    """
    tenant_id = _require_env("COPILOTSTUDIOAGENT__TENANTID")
    client_id = _require_env("COPILOTSTUDIOAGENT__AGENTAPPID")
    client_secret = _require_env("COPILOTSTUDIOAGENT__AGENTAPPSECRET")

    cca = ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
    )

    result = cca.acquire_token_for_client(scopes=[POWER_PLATFORM_SCOPE])

    if "access_token" not in result:
        error = result.get("error", "unknown")
        error_description = result.get("error_description", "No description")
        raise RuntimeError(
            f"Failed to acquire token: {error} - {error_description}"
        )

    logger.info("Successfully acquired app-only token via client credentials flow")
    return result["access_token"]


def create_copilot_client() -> CopilotClient:
    """Create a CopilotClient with app-only token.

    Returns:
        Configured CopilotClient instance.
    """
    settings = ConnectionSettings(
        environment_id=_require_env("COPILOTSTUDIOAGENT__ENVIRONMENTID"),
        agent_identifier=_require_env("COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME"),
        cloud=PowerPlatformCloud.PROD,
        copilot_agent_type=None,
        custom_power_platform_cloud=None,
    )

    token = acquire_token_client_credentials()
    return CopilotClient(settings, token)


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
    """Call CS Weather Agent via M365 Agents SDK CopilotClient.

    Args:
        user_message: The raw user message to forward to CS Weather Agent.

    Returns:
        Raw response text from the CS Weather Agent.

    Raises:
        RuntimeError: If the agent call fails.
    """
    prompt = f"{user_message}\n\nPlease provide the weather/climate information as JSON."
    logger.info("Sending message to CS Weather Agent via CopilotClient: %s", prompt[:200])

    copilot_client = create_copilot_client()

    # Start conversation and collect initial greeting
    start_activities = copilot_client.start_conversation(emit_start_event=True)
    conversation_id = None
    async for activity in start_activities:
        if activity.text:
            logger.info("Start conversation response: %s", activity.text[:100])
        if activity.conversation:
            conversation_id = activity.conversation.id

    if not conversation_id:
        raise RuntimeError("Failed to start conversation with Copilot Studio agent")

    logger.info("Started conversation: %s", conversation_id)

    # Ask the weather question
    response_text = ""
    replies = copilot_client.ask_question(prompt, conversation_id)
    async for reply in replies:
        if reply.type == ActivityTypes.message and reply.text:
            response_text = reply.text
            logger.info("Received response from CS Weather Agent (length=%d)", len(response_text))
        elif reply.type == ActivityTypes.end_of_conversation:
            logger.info("End of conversation")

    if not response_text:
        raise RuntimeError("No response received from CS Weather Agent")

    return response_text


def extract_json_from_response(response_text: str) -> dict[str, Any]:
    """Extract JSON from response text.

    Handles cases where JSON is:
    - Plain JSON string
    - Embedded in markdown code blocks
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
    """Weather Proxy agent that calls Copilot Studio Weather Agent
    via M365 Agents SDK using client credentials flow."""

    async def agent_run(
        self, context: AgentRunContext
    ) -> OpenAIResponse | AsyncGenerator[ResponseStreamEvent, Any]:
        """Handle incoming request from Foundry workflow."""
        request = context.raw_payload if hasattr(context, "raw_payload") else context.request
        messages = _extract_messages(request)

        if not messages:
            output_text = "Error: No messages in request"
        else:
            user_message = extract_user_message(messages)
            if not user_message:
                output_text = "Error: Empty message content"
            else:
                logger.info("Processing request: %s", user_message[:200])
                try:
                    response_text = await call_weather_agent(user_message)
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
    logger.info("Starting Weather Proxy (M365 SDK Client Credentials) on port %s", port)

    try:
        agent = WeatherProxyAgent()
        agent.run(port=port)
    except Exception:
        logger.exception("Weather Proxy server failed to start")
        raise


if __name__ == "__main__":
    main()
