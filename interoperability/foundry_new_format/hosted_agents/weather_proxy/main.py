from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Callable
from typing import Any

import httpx
from azure.ai.agentserver.responses import (
    CreateResponse,
    ResponseContext,
    ResponsesAgentServerHost,
    ResponsesServerOptions,
    TextResponse,
)

from shared.schemas import WeatherResponse

_DIRECT_LINE_BASE_URL = "https://directline.botframework.com/v3/directline"
_DIRECT_LINE_SECRET_ENV = "COPILOTSTUDIOAGENT__DIRECTLINE_SECRET"
_SENDER_ID = "weather-proxy"


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} environment variable must be set")
    return value


def extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    text_parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            text_parts.append(part)
        elif isinstance(part, dict) and part.get("type") in {
            "text",
            "input_text",
            "output_text",
        }:
            text = part.get("text")
            if isinstance(text, dict):
                text = text.get("value")
            if isinstance(text, str):
                text_parts.append(text)
    return " ".join(part.strip() for part in text_parts if part.strip())


def _json_object(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Weather agent response must contain a JSON object")
    return parsed


def extract_json_object(response_text: str) -> dict[str, Any]:
    try:
        return _json_object(response_text)
    except (json.JSONDecodeError, ValueError):
        pass

    for match in re.finditer(r"```(?:json)?\s*(.*?)```", response_text, re.IGNORECASE | re.DOTALL):
        try:
            return _json_object(match.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            pass

    decoder = json.JSONDecoder()
    for index, character in enumerate(response_text):
        if character != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(response_text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("Weather agent response did not contain a JSON object")


def parse_weather_response(response_text: str) -> WeatherResponse:
    return WeatherResponse.model_validate(extract_json_object(response_text))


def _raise_if_cancelled(cancellation_signal: asyncio.Event | None) -> None:
    if cancellation_signal is not None and cancellation_signal.is_set():
        raise asyncio.CancelledError()


async def _wait_for_next_poll(
    poll_interval: float,
    cancellation_signal: asyncio.Event | None,
) -> None:
    if cancellation_signal is None:
        await asyncio.sleep(poll_interval)
        return
    try:
        await asyncio.wait_for(cancellation_signal.wait(), timeout=poll_interval)
    except TimeoutError:
        return
    raise asyncio.CancelledError()


async def call_weather_agent(
    user_message: str,
    *,
    client: httpx.AsyncClient | None = None,
    sender_id: str = _SENDER_ID,
    max_polls: int = 30,
    poll_interval: float = 1.0,
    cancellation_signal: asyncio.Event | None = None,
) -> str:
    if max_polls < 1:
        raise ValueError("max_polls must be at least 1")
    if poll_interval < 0:
        raise ValueError("poll_interval must not be negative")

    secret = require_env(_DIRECT_LINE_SECRET_ENV)
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))

    try:
        _raise_if_cancelled(cancellation_signal)
        response = await client.post(
            f"{_DIRECT_LINE_BASE_URL}/conversations",
            headers={"Authorization": f"Bearer {secret}"},
        )
        if response.status_code != 201:
            raise RuntimeError("Direct Line conversation creation failed")
        conversation = response.json()
        conversation_id = conversation.get("conversationId")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise RuntimeError("Direct Line conversation response did not contain an ID")

        conversation_token = conversation.get("token")
        token = conversation_token if isinstance(conversation_token, str) else secret
        headers = {"Authorization": f"Bearer {token}"}
        activities_url = (
            f"{_DIRECT_LINE_BASE_URL}/conversations/{conversation_id}/activities"
        )

        _raise_if_cancelled(cancellation_signal)
        response = await client.post(
            activities_url,
            headers=headers,
            json={"type": "message", "from": {"id": sender_id}, "text": user_message},
        )
        if response.status_code != 200:
            raise RuntimeError("Direct Line message delivery failed")

        watermark: str | None = None
        for _ in range(max_polls):
            _raise_if_cancelled(cancellation_signal)
            response = await client.get(
                activities_url,
                headers=headers,
                params={"watermark": watermark} if watermark else None,
            )
            if response.status_code != 200:
                raise RuntimeError("Direct Line activity polling failed")
            activities_response = response.json()
            watermark_value = activities_response.get("watermark")
            watermark = watermark_value if isinstance(watermark_value, str) else watermark

            for activity in activities_response.get("activities", []):
                if (
                    isinstance(activity, dict)
                    and activity.get("type") == "message"
                    and activity.get("from", {}).get("id") != sender_id
                    and isinstance(activity.get("text"), str)
                    and activity["text"]
                ):
                    return activity["text"]

            await _wait_for_next_poll(poll_interval, cancellation_signal)
    finally:
        if owns_client:
            await client.aclose()

    raise TimeoutError("Direct Line weather agent did not respond before the polling timeout")


def create_app(
    *,
    host_factory: Callable[..., Any] = ResponsesAgentServerHost,
) -> Any:
    return host_factory(
        options=ResponsesServerOptions(default_fetch_history_count=20),
        configure_observability=None,
    )


app = create_app()


@app.response_handler
async def handle(
    request: CreateResponse,
    context: ResponseContext,
    cancellation_signal: asyncio.Event,
) -> TextResponse:
    user_message = extract_text(await context.get_input_text())
    if not user_message:
        raise ValueError("Weather requests require text input")

    raw_response = await call_weather_agent(
        user_message,
        cancellation_signal=cancellation_signal,
    )
    weather = parse_weather_response(raw_response)
    return TextResponse(context, request, text=weather.model_dump_json())


if __name__ == "__main__":
    app.run()
