"""Unit tests for Discovery Workflow Pro-Code weather step.

Tests validate:
- Weather step uses correct COPILOTSTUDIOAGENT__* environment variables
- Weather step handles timeout gracefully (returns partial results)
- Weather step handles auth failure gracefully (returns error, continues)
- Weather request/response format matches shared schema
- Environment variable validation detects missing vars
- Response parsing handles various JSON formats

Design doc references:
- Cross-Platform Authentication - Foundry -> CS (lines 975-1000)
- Appendix A.3 Copilot Studio (lines 1687-1744)
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.shared.models import ClimateSummary, WeatherRequest, WeatherResponse

# Patch target: the source module where CopilotStudioClient lives.
# Since weather_step.py imports lazily inside functions with
# `from interoperability.pro_code.m365_sdk_client import ...`,
# we must patch at the source module.
M365_MODULE = "interoperability.pro_code.m365_sdk_client"


# Sample valid weather response JSON
SAMPLE_WEATHER_JSON = json.dumps(
    {
        "location": "Paris, France",
        "start_date": "2025-06-15",
        "end_date": "2025-06-20",
        "climate_summary": {
            "average_high_temp_c": 24,
            "average_low_temp_c": 14,
            "average_precipitation_chance": 25,
            "typical_conditions": "Mostly sunny with occasional afternoon clouds",
        },
        "summary": "June in Paris is typically warm and pleasant with long sunny days.",
    }
)


class TestWeatherStepEnvVars:
    """Test weather step uses correct environment variables."""

    def test_required_env_vars_list(self):
        """Test REQUIRED_ENV_VARS includes all COPILOTSTUDIOAGENT__ vars."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            REQUIRED_ENV_VARS,
        )

        assert "COPILOTSTUDIOAGENT__TENANTID" in REQUIRED_ENV_VARS
        assert "COPILOTSTUDIOAGENT__ENVIRONMENTID" in REQUIRED_ENV_VARS
        assert "COPILOTSTUDIOAGENT__AGENTAPPID" in REQUIRED_ENV_VARS
        assert "COPILOTSTUDIOAGENT__AGENTAPPSECRET" in REQUIRED_ENV_VARS
        assert "COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME" in REQUIRED_ENV_VARS

    def test_validate_env_vars_all_set(self):
        """Test validate_env_vars returns empty list when all vars are set."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            validate_env_vars,
        )

        env = {
            "COPILOTSTUDIOAGENT__TENANTID": "test-tenant",
            "COPILOTSTUDIOAGENT__ENVIRONMENTID": "test-env",
            "COPILOTSTUDIOAGENT__AGENTAPPID": "test-app-id",
            "COPILOTSTUDIOAGENT__AGENTAPPSECRET": "test-secret",
            "COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME": "test-schema",
        }
        with patch.dict("os.environ", env, clear=False):
            missing = validate_env_vars()
        assert missing == []

    def test_validate_env_vars_missing(self):
        """Test validate_env_vars detects missing variables."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            validate_env_vars,
        )

        env = {
            "COPILOTSTUDIOAGENT__TENANTID": "test-tenant",
            # Missing the rest
        }
        with patch.dict("os.environ", env, clear=True):
            missing = validate_env_vars()
        assert "COPILOTSTUDIOAGENT__ENVIRONMENTID" in missing
        assert "COPILOTSTUDIOAGENT__AGENTAPPID" in missing
        assert "COPILOTSTUDIOAGENT__AGENTAPPSECRET" in missing
        assert "COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME" in missing

    def test_validate_env_vars_all_missing(self):
        """Test validate_env_vars returns all vars when none are set."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            REQUIRED_ENV_VARS,
            validate_env_vars,
        )

        with patch.dict("os.environ", {}, clear=True):
            missing = validate_env_vars()
        assert len(missing) == len(REQUIRED_ENV_VARS)

    def test_get_weather_schema_name_set(self):
        """Test get_weather_schema_name returns value when set."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            get_weather_schema_name,
        )

        with patch.dict(
            "os.environ",
            {"COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME": "my-weather"},
        ):
            assert get_weather_schema_name() == "my-weather"

    def test_get_weather_schema_name_missing(self):
        """Test get_weather_schema_name raises when not set."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            WeatherStepError,
            get_weather_schema_name,
        )

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(WeatherStepError, match="SCHEMANAME"):
                get_weather_schema_name()

    def test_weather_step_uses_weather_prefix(self):
        """Test that CopilotStudioClientConfig.from_env is called with WEATHER prefix."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            call_weather_agent,
        )

        request = WeatherRequest(
            location="Tokyo", start_date="2025-07-01", end_date="2025-07-05"
        )

        with patch(
            f"{M365_MODULE}.CopilotStudioClientConfig"
        ) as mock_config_cls, patch(
            f"{M365_MODULE}.CopilotStudioClient"
        ):
            mock_config_cls.from_env.side_effect = ValueError("test: missing vars")

            with pytest.raises(Exception):
                asyncio.get_event_loop().run_until_complete(call_weather_agent(request))

            # Verify from_env was called with agent_prefix="WEATHER"
            mock_config_cls.from_env.assert_called_once_with(agent_prefix="WEATHER")


class TestWeatherStepTimeout:
    """Test weather step handles timeout gracefully."""

    def test_execute_weather_step_timeout(self):
        """Test execute_weather_step returns error on timeout."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            execute_weather_step,
        )

        env = {
            "COPILOTSTUDIOAGENT__TENANTID": "t",
            "COPILOTSTUDIOAGENT__ENVIRONMENTID": "e",
            "COPILOTSTUDIOAGENT__AGENTAPPID": "a",
            "COPILOTSTUDIOAGENT__AGENTAPPSECRET": "s",
            "COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME": "w",
        }

        with patch.dict("os.environ", env, clear=False), patch(
            f"{M365_MODULE}.CopilotStudioClientConfig"
        ), patch(f"{M365_MODULE}.CopilotStudioClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.acquire_token.return_value = "fake-token"

            # Simulate timeout on start_conversation
            async def slow_start():
                raise asyncio.TimeoutError()

            mock_client.start_conversation = slow_start

            result = asyncio.get_event_loop().run_until_complete(
                execute_weather_step("Paris", "2025-06-15", "2025-06-20")
            )

        assert result["success"] is False
        assert "timed out" in result["error"]

    def test_call_weather_agent_timeout_raises(self):
        """Test call_weather_agent raises WeatherTimeoutError on timeout."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            WeatherTimeoutError,
            call_weather_agent,
        )

        request = WeatherRequest(
            location="Paris", start_date="2025-06-15", end_date="2025-06-20"
        )

        with patch(
            f"{M365_MODULE}.CopilotStudioClientConfig"
        ), patch(f"{M365_MODULE}.CopilotStudioClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.acquire_token.return_value = "fake-token"

            async def slow_start():
                raise asyncio.TimeoutError()

            mock_client.start_conversation = slow_start

            with pytest.raises(WeatherTimeoutError):
                asyncio.get_event_loop().run_until_complete(
                    call_weather_agent(request, timeout_seconds=1)
                )


class TestWeatherStepAuthFailure:
    """Test weather step handles auth failure gracefully."""

    def test_execute_weather_step_auth_failure(self):
        """Test execute_weather_step returns error on auth failure."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            execute_weather_step,
        )

        env = {
            "COPILOTSTUDIOAGENT__TENANTID": "t",
            "COPILOTSTUDIOAGENT__ENVIRONMENTID": "e",
            "COPILOTSTUDIOAGENT__AGENTAPPID": "a",
            "COPILOTSTUDIOAGENT__AGENTAPPSECRET": "bad-secret",
            "COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME": "w",
        }

        with patch.dict("os.environ", env, clear=False), patch(
            f"{M365_MODULE}.CopilotStudioClientConfig"
        ), patch(f"{M365_MODULE}.CopilotStudioClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.acquire_token.side_effect = RuntimeError(
                "Token acquisition failed: invalid_client"
            )

            result = asyncio.get_event_loop().run_until_complete(
                execute_weather_step("Paris", "2025-06-15", "2025-06-20")
            )

        assert result["success"] is False
        assert "authentication failed" in result["error"]

    def test_call_weather_agent_auth_failure_raises(self):
        """Test call_weather_agent raises WeatherAuthError on auth failure."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            WeatherAuthError,
            call_weather_agent,
        )

        request = WeatherRequest(
            location="Paris", start_date="2025-06-15", end_date="2025-06-20"
        )

        with patch(
            f"{M365_MODULE}.CopilotStudioClientConfig"
        ), patch(f"{M365_MODULE}.CopilotStudioClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.acquire_token.side_effect = RuntimeError("invalid_client")

            with pytest.raises(WeatherAuthError, match="Failed to authenticate"):
                asyncio.get_event_loop().run_until_complete(
                    call_weather_agent(request)
                )

    def test_call_weather_agent_config_error_raises(self):
        """Test call_weather_agent raises WeatherAuthError on config error."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            WeatherAuthError,
            call_weather_agent,
        )

        request = WeatherRequest(
            location="Paris", start_date="2025-06-15", end_date="2025-06-20"
        )

        with patch(
            f"{M365_MODULE}.CopilotStudioClientConfig"
        ) as mock_config_cls:
            mock_config_cls.from_env.side_effect = ValueError("Missing env vars")

            with pytest.raises(WeatherAuthError, match="configuration error"):
                asyncio.get_event_loop().run_until_complete(
                    call_weather_agent(request)
                )

    def test_execute_weather_step_missing_env_vars(self):
        """Test execute_weather_step returns error when env vars missing."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            execute_weather_step,
        )

        with patch.dict("os.environ", {}, clear=True):
            result = asyncio.get_event_loop().run_until_complete(
                execute_weather_step("Paris", "2025-06-15", "2025-06-20")
            )

        assert result["success"] is False
        assert "missing env vars" in result["error"]


class TestWeatherResponseParsing:
    """Test weather response parsing and schema validation."""

    def test_parse_direct_json(self):
        """Test parsing direct JSON response."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            _parse_weather_response,
        )

        request = WeatherRequest(
            location="Paris, France",
            start_date="2025-06-15",
            end_date="2025-06-20",
        )

        response = _parse_weather_response(SAMPLE_WEATHER_JSON, request)
        assert isinstance(response, WeatherResponse)
        assert response.location == "Paris, France"
        assert response.climate_summary.average_high_temp_c == 24

    def test_parse_markdown_json(self):
        """Test parsing JSON embedded in markdown code block."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            _parse_weather_response,
        )

        request = WeatherRequest(
            location="Paris, France",
            start_date="2025-06-15",
            end_date="2025-06-20",
        )

        markdown_response = f"Here is the weather data:\n```json\n{SAMPLE_WEATHER_JSON}\n```"
        response = _parse_weather_response(markdown_response, request)
        assert isinstance(response, WeatherResponse)
        assert response.location == "Paris, France"

    def test_parse_json_in_text(self):
        """Test parsing JSON embedded in plain text."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            _parse_weather_response,
        )

        request = WeatherRequest(
            location="Paris, France",
            start_date="2025-06-15",
            end_date="2025-06-20",
        )

        text_response = f"The weather forecast is: {SAMPLE_WEATHER_JSON} Hope this helps!"
        response = _parse_weather_response(text_response, request)
        assert isinstance(response, WeatherResponse)

    def test_parse_invalid_json_raises(self):
        """Test parsing invalid JSON raises WeatherStepError."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            WeatherStepError,
            _parse_weather_response,
        )

        request = WeatherRequest(
            location="Paris", start_date="2025-06-15", end_date="2025-06-20"
        )

        with pytest.raises(WeatherStepError, match="Could not extract JSON"):
            _parse_weather_response("No JSON here at all", request)

    def test_parse_invalid_schema_raises(self):
        """Test parsing valid JSON that doesn't match WeatherResponse raises."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            WeatherStepError,
            _parse_weather_response,
        )

        request = WeatherRequest(
            location="Paris", start_date="2025-06-15", end_date="2025-06-20"
        )

        bad_json = json.dumps({"not": "a weather response"})
        with pytest.raises(WeatherStepError, match="does not match schema"):
            _parse_weather_response(bad_json, request)

    def test_weather_request_schema_fields(self):
        """Test WeatherRequest schema has expected fields."""
        request = WeatherRequest(
            location="Tokyo, Japan",
            start_date="2025-07-01",
            end_date="2025-07-05",
        )
        assert request.location == "Tokyo, Japan"
        assert request.start_date == "2025-07-01"
        assert request.end_date == "2025-07-05"

    def test_weather_response_schema_fields(self):
        """Test WeatherResponse schema has expected fields."""
        data = json.loads(SAMPLE_WEATHER_JSON)
        response = WeatherResponse(**data)
        assert response.location == "Paris, France"
        assert response.start_date == "2025-06-15"
        assert response.end_date == "2025-06-20"
        assert isinstance(response.climate_summary, ClimateSummary)
        assert response.climate_summary.average_high_temp_c == 24
        assert response.climate_summary.average_low_temp_c == 14
        assert response.climate_summary.average_precipitation_chance == 25
        assert response.summary.startswith("June in Paris")


class TestWeatherStepExecute:
    """Test execute_weather_step end-to-end behavior."""

    def test_execute_success(self):
        """Test successful weather step execution."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            execute_weather_step,
        )

        env = {
            "COPILOTSTUDIOAGENT__TENANTID": "t",
            "COPILOTSTUDIOAGENT__ENVIRONMENTID": "e",
            "COPILOTSTUDIOAGENT__AGENTAPPID": "a",
            "COPILOTSTUDIOAGENT__AGENTAPPSECRET": "s",
            "COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME": "w",
        }

        mock_activity = MagicMock()
        mock_activity.is_message = True
        mock_activity.text = SAMPLE_WEATHER_JSON

        with patch.dict("os.environ", env, clear=False), patch(
            f"{M365_MODULE}.CopilotStudioClientConfig"
        ), patch(f"{M365_MODULE}.CopilotStudioClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.acquire_token.return_value = "token"

            async def mock_start():
                return "conv-123"

            mock_client.start_conversation = mock_start

            async def mock_send(msg, conv_id):
                yield mock_activity

            mock_client.send_message = mock_send

            result = asyncio.get_event_loop().run_until_complete(
                execute_weather_step("Paris, France", "2025-06-15", "2025-06-20")
            )

        assert result["success"] is True
        assert result["data"]["location"] == "Paris, France"
        assert result["data"]["climate_summary"]["average_high_temp_c"] == 24

    def test_execute_never_raises(self):
        """Test execute_weather_step never raises, always returns dict."""
        from interoperability.foundry.workflows.discovery_workflow_procode.steps.weather_step import (
            execute_weather_step,
        )

        env = {
            "COPILOTSTUDIOAGENT__TENANTID": "t",
            "COPILOTSTUDIOAGENT__ENVIRONMENTID": "e",
            "COPILOTSTUDIOAGENT__AGENTAPPID": "a",
            "COPILOTSTUDIOAGENT__AGENTAPPSECRET": "s",
            "COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME": "w",
        }

        with patch.dict("os.environ", env, clear=False), patch(
            f"{M365_MODULE}.CopilotStudioClientConfig"
        ) as mock_config_cls:
            mock_config_cls.from_env.side_effect = ValueError("kaboom")

            # Should not raise
            result = asyncio.get_event_loop().run_until_complete(
                execute_weather_step("Paris", "2025-06-15", "2025-06-20")
            )

        assert result["success"] is False
        assert "error" in result
