import json
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from interoperability.foundry_new_format.hosted_agents.weather_proxy.main import (
    call_weather_agent,
    extract_text,
    parse_weather_response,
    require_env,
)
from shared.schemas import WeatherResponse


def valid_weather() -> dict[str, object]:
    return {
        "location": "Paris, France",
        "start_date": "2026-06-15",
        "end_date": "2026-06-20",
        "climate_summary": {
            "average_high_temp_c": 24.0,
            "average_low_temp_c": 14.0,
            "average_precipitation_chance": 25,
            "typical_conditions": "Mostly sunny",
        },
        "summary": "Warm and pleasant.",
    }


def test_extract_text_joins_supported_content_parts() -> None:
    assert extract_text(
        [
            {"type": "input_text", "text": "Weather for"},
            {"type": "image_url", "url": "https://example.test/image.png"},
            {"type": "text", "text": " Paris"},
        ]
    ) == "Weather for Paris"


@pytest.mark.parametrize(
    "response_text",
    [
        json.dumps(valid_weather()),
        f"Here is the weather:\n```json\n{json.dumps(valid_weather())}\n```",
        f"Weather details: {json.dumps(valid_weather())} Have a nice trip.",
    ],
)
def test_parse_weather_response_extracts_json_objects(response_text: str) -> None:
    weather = parse_weather_response(response_text)

    assert isinstance(weather, WeatherResponse)
    assert weather.location == "Paris, France"
    assert weather.climate_summary.average_high_temp_c == 24.0


def test_parse_weather_response_rejects_invalid_contract() -> None:
    invalid = valid_weather()
    invalid.pop("summary")

    with pytest.raises(ValidationError):
        parse_weather_response(json.dumps(invalid))


def test_require_env_rejects_missing_direct_line_secret(monkeypatch) -> None:
    monkeypatch.delenv("COPILOTSTUDIOAGENT__DIRECTLINE_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="COPILOTSTUDIOAGENT__DIRECTLINE_SECRET"):
        require_env("COPILOTSTUDIOAGENT__DIRECTLINE_SECRET")


@pytest.mark.asyncio
async def test_call_weather_agent_uses_direct_line_and_ignores_own_message(
    monkeypatch,
) -> None:
    secret = str(uuid4())
    monkeypatch.setenv("COPILOTSTUDIOAGENT__DIRECTLINE_SECRET", secret)
    requests: list[httpx.Request] = []

    def direct_line(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST" and request.url.path.endswith("/conversations"):
            return httpx.Response(
                201,
                json={"conversationId": "conversation-1", "token": "conversation-token"},
            )
        if request.method == "POST":
            assert json.loads(request.content) == {
                "type": "message",
                "from": {"id": "weather-proxy"},
                "text": "Weather for Paris",
            }
            return httpx.Response(200, json={"id": "activity-1"})
        return httpx.Response(
            200,
            json={
                "watermark": "1",
                "activities": [
                    {
                        "type": "message",
                        "from": {"id": "weather-proxy"},
                        "text": "Weather for Paris",
                    },
                    {
                        "type": "message",
                        "from": {"id": "weather-agent"},
                        "text": json.dumps(valid_weather()),
                    },
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(direct_line)) as client:
        response = await call_weather_agent("Weather for Paris", client=client)

    assert response == json.dumps(valid_weather())
    assert [request.method for request in requests] == ["POST", "POST", "GET"]
    assert requests[0].headers["Authorization"] == f"Bearer {secret}"
    assert requests[1].headers["Authorization"] == "Bearer conversation-token"
