"""
Weather Step - Calls Copilot Studio Weather Agent from Foundry Pro-Code Workflow.

This step integrates with the CS Weather agent using the M365 Agents SDK
(microsoft-agents-copilotstudio-client) via CopilotStudioClient wrapper.

The step:
1. Reads COPILOTSTUDIOAGENT__* environment variables for auth config
2. Sends a weather request to the CS Weather agent
3. Parses the JSON response into WeatherResponse schema
4. Returns partial results on timeout or auth failure (graceful degradation)

Design doc references:
- Demo A: Foundry Features - Cross-Platform Call (line 142)
- Cross-Platform Authentication - Foundry -> CS (lines 975-1000)
- Appendix A.3 Copilot Studio (lines 1687-1744)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional

from src.shared.models import WeatherRequest, WeatherResponse

logger = logging.getLogger(__name__)

# Required environment variables for CS Weather agent connection
# These follow M365 Agents SDK naming convention (double underscores)
REQUIRED_ENV_VARS = [
    "COPILOTSTUDIOAGENT__TENANTID",
    "COPILOTSTUDIOAGENT__ENVIRONMENTID",
    "COPILOTSTUDIOAGENT__AGENTAPPID",
    "COPILOTSTUDIOAGENT__AGENTAPPSECRET",
    "COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME",
]

# Default timeout for CS Weather agent call
DEFAULT_TIMEOUT_SECONDS = 30


class WeatherStepError(Exception):
    """Base exception for weather step errors."""


class WeatherAuthError(WeatherStepError):
    """Raised when authentication to CS Weather agent fails."""


class WeatherTimeoutError(WeatherStepError):
    """Raised when CS Weather agent call times out."""


def validate_env_vars() -> list[str]:
    """Check that all required environment variables are set.

    Returns:
        List of missing environment variable names. Empty list if all are set.
    """
    missing = []
    for var in REQUIRED_ENV_VARS:
        if not os.environ.get(var):
            missing.append(var)
    return missing


def get_weather_schema_name() -> str:
    """Get the CS Weather agent schema name from environment.

    Returns:
        The schema name string.

    Raises:
        WeatherStepError: If the schema name env var is not set.
    """
    schema = os.environ.get("COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME")
    if not schema:
        raise WeatherStepError(
            "COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME is not set. "
            "See interoperability/copilot_studio/SETUP.md for configuration."
        )
    return schema


async def call_weather_agent(
    request: WeatherRequest,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> WeatherResponse:
    """Call the CS Weather agent and return a validated WeatherResponse.

    Uses the CopilotStudioClient wrapper from the pro_code module to
    handle M365 SDK authentication and communication.

    Args:
        request: Weather request with location and date range.
        timeout_seconds: Max wait time for CS agent response.

    Returns:
        Validated WeatherResponse from the CS Weather agent.

    Raises:
        WeatherAuthError: If authentication to CS fails.
        WeatherTimeoutError: If the CS agent doesn't respond in time.
        WeatherStepError: For other CS communication failures.
    """
    from interoperability.pro_code.m365_sdk_client import (
        CopilotStudioClient,
        CopilotStudioClientConfig,
    )

    # Build config from env vars (uses WEATHER prefix for schema name)
    try:
        config = CopilotStudioClientConfig.from_env(agent_prefix="WEATHER")
    except ValueError as e:
        raise WeatherAuthError(
            f"CS Weather agent configuration error: {e}. "
            "Check COPILOTSTUDIOAGENT__* environment variables."
        ) from e

    client = CopilotStudioClient(config)

    # Acquire token
    try:
        client.acquire_token()
    except RuntimeError as e:
        raise WeatherAuthError(
            f"Failed to authenticate with CS Weather agent: {e}"
        ) from e

    # Build the question for the weather agent
    question = (
        f"What's the weather forecast for {request.location} "
        f"from {request.start_date} to {request.end_date}? "
        f"Please respond with JSON."
    )

    # Call the CS Weather agent with timeout
    try:
        conversation_id = await asyncio.wait_for(
            client.start_conversation(),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as e:
        raise WeatherTimeoutError(
            f"CS Weather agent conversation start timed out after {timeout_seconds}s"
        ) from e
    except RuntimeError as e:
        raise WeatherStepError(
            f"Failed to start CS Weather agent conversation: {e}"
        ) from e

    # Send message and collect response
    response_text = ""
    try:
        async for activity in client.send_message(question, conversation_id):
            if activity.is_message and activity.text:
                response_text = activity.text
                break  # Take first message response
    except asyncio.TimeoutError as e:
        raise WeatherTimeoutError(
            f"CS Weather agent response timed out after {timeout_seconds}s"
        ) from e
    except Exception as e:
        raise WeatherStepError(
            f"CS Weather agent communication error: {e}"
        ) from e

    if not response_text:
        raise WeatherStepError("CS Weather agent returned empty response")

    # Parse response into WeatherResponse schema
    return _parse_weather_response(response_text, request)


def _parse_weather_response(
    response_text: str, request: WeatherRequest
) -> WeatherResponse:
    """Parse CS Weather agent response text into WeatherResponse.

    Handles JSON responses embedded in plain text or markdown code blocks.

    Args:
        response_text: Raw text from CS Weather agent.
        request: Original request (for fallback field values).

    Returns:
        Validated WeatherResponse.

    Raises:
        WeatherStepError: If response cannot be parsed into valid schema.
    """
    import re

    # Try direct JSON parsing
    json_data: Optional[dict[str, Any]] = None
    try:
        json_data = json.loads(response_text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    if json_data is None:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response_text)
        if match:
            try:
                json_data = json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

    # Try finding JSON object in text
    if json_data is None:
        match = re.search(r"\{[\s\S]*\}", response_text)
        if match:
            try:
                json_data = json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

    if json_data is None:
        raise WeatherStepError(
            f"Could not extract JSON from CS Weather response: "
            f"{response_text[:200]}..."
        )

    try:
        return WeatherResponse(**json_data)
    except Exception as e:
        raise WeatherStepError(
            f"CS Weather response does not match schema: {e}"
        ) from e


async def execute_weather_step(
    destination: str,
    start_date: str,
    end_date: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Execute the weather step in the discovery workflow.

    This is the main entry point called by the workflow orchestrator.
    Returns a dict with either weather data or an error message,
    never raises exceptions (graceful degradation).

    Args:
        destination: Travel destination (e.g., "Paris, France").
        start_date: Trip start date in YYYY-MM-DD format.
        end_date: Trip end date in YYYY-MM-DD format.
        timeout_seconds: Max wait time for CS agent.

    Returns:
        Dict with 'success' bool and either 'data' (WeatherResponse dict)
        or 'error' string.
    """
    # Validate env vars first
    missing = validate_env_vars()
    if missing:
        logger.warning("Missing CS Weather env vars: %s", ", ".join(missing))
        return {
            "success": False,
            "error": f"Weather unavailable: missing env vars ({', '.join(missing)})",
        }

    request = WeatherRequest(
        location=destination,
        start_date=start_date,
        end_date=end_date,
    )

    try:
        response = await call_weather_agent(request, timeout_seconds=timeout_seconds)
        logger.info("Weather data received for %s", destination)
        return {
            "success": True,
            "data": response.model_dump(),
        }
    except WeatherAuthError as e:
        logger.error("CS Weather auth failed: %s", e)
        return {
            "success": False,
            "error": f"Weather unavailable: authentication failed ({e})",
        }
    except WeatherTimeoutError as e:
        logger.warning("CS Weather timed out: %s", e)
        return {
            "success": False,
            "error": f"Weather unavailable: request timed out ({e})",
        }
    except WeatherStepError as e:
        logger.error("CS Weather step error: %s", e)
        return {
            "success": False,
            "error": f"Weather unavailable: {e}",
        }
