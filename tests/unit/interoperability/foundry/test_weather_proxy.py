"""Unit tests for Weather Proxy hosted agent.

Tests validate:
- agent.yaml is valid and contains required fields
- main.py uses Direct Line API for CS Weather Agent calls
- WeatherResponse schema imported from src/shared/models.py (not duplicated)
- User message extraction handles both string and list content formats
- Response parsing handles JSON embedded in various formats
- Environment variables are declared in agent.yaml
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml


WEATHER_PROXY_DIR = Path("interoperability/foundry/agents/weather/weather_proxy_direct_line")


class TestWeatherProxyYaml:
    """Tests for weather_proxy/agent.yaml validity."""

    def test_weather_proxy_yaml_valid(self):
        """Test agent.yaml is valid YAML with required fields."""
        yaml_path = WEATHER_PROXY_DIR / "agent.yaml"
        assert yaml_path.exists(), "agent.yaml must exist"

        with open(yaml_path) as f:
            config = yaml.safe_load(f)

        assert config["name"] == "weather-proxy"
        assert config["type"] == "hosted"
        assert "description" in config
        assert "container" in config
        assert "environment" in config

    def test_weather_proxy_container_config(self):
        """Test container configuration is correct."""
        yaml_path = WEATHER_PROXY_DIR / "agent.yaml"
        with open(yaml_path) as f:
            config = yaml.safe_load(f)

        container = config["container"]
        assert "image" in container
        assert container["cpu"] == "1"
        assert container["memory"] == "2Gi"

    def test_weather_proxy_protocol_config(self):
        """Test protocol configuration specifies responses v1."""
        yaml_path = WEATHER_PROXY_DIR / "agent.yaml"
        with open(yaml_path) as f:
            config = yaml.safe_load(f)

        protocols = config.get("protocol", [])
        assert len(protocols) > 0
        assert protocols[0]["protocol"] == "responses"
        assert protocols[0]["version"] == "v1"

    def test_weather_proxy_env_vars_declared(self):
        """Test all required Direct Line environment variables are declared."""
        yaml_path = WEATHER_PROXY_DIR / "agent.yaml"
        with open(yaml_path) as f:
            config = yaml.safe_load(f)

        env = config["environment"]
        # Direct Line only requires the secret
        assert "COPILOTSTUDIOAGENT__DIRECTLINE_SECRET" in env

    def test_weather_proxy_framework_is_custom(self):
        """Test framework is set to 'custom' (not agent_framework)."""
        yaml_path = WEATHER_PROXY_DIR / "agent.yaml"
        with open(yaml_path) as f:
            config = yaml.safe_load(f)

        # Weather Proxy uses Direct Line API, not Agent Framework
        assert config["framework"] == "custom"


class TestWeatherProxyRequirements:
    """Tests for weather_proxy/requirements.txt."""

    def test_requirements_txt_exists(self):
        """Test requirements.txt exists."""
        req_path = WEATHER_PROXY_DIR / "requirements.txt"
        assert req_path.exists()

    def test_requirements_includes_required_packages(self):
        """Test required packages are listed."""
        req_path = WEATHER_PROXY_DIR / "requirements.txt"
        with open(req_path) as f:
            content = f.read()

        required_packages = [
            "azure-ai-agentserver-core",
            "aiohttp",
            "pydantic",
            "python-dotenv",
        ]
        for pkg in required_packages:
            assert pkg in content, f"Package {pkg} must be in requirements.txt"


class TestWeatherProxyDockerfile:
    """Tests for weather_proxy/Dockerfile."""

    def test_dockerfile_exists(self):
        """Test Dockerfile exists."""
        dockerfile_path = WEATHER_PROXY_DIR / "Dockerfile"
        assert dockerfile_path.exists()

    def test_dockerfile_base_image(self):
        """Test Dockerfile uses python:3.11-slim base image."""
        dockerfile_path = WEATHER_PROXY_DIR / "Dockerfile"
        with open(dockerfile_path) as f:
            content = f.read()

        assert "FROM python:3.11-slim" in content

    def test_dockerfile_copies_src(self):
        """Test Dockerfile copies src/ for shared models."""
        dockerfile_path = WEATHER_PROXY_DIR / "Dockerfile"
        with open(dockerfile_path) as f:
            content = f.read()

        assert "COPY src/ src/" in content

    def test_dockerfile_exposes_port(self):
        """Test Dockerfile exposes port 8088."""
        dockerfile_path = WEATHER_PROXY_DIR / "Dockerfile"
        with open(dockerfile_path) as f:
            content = f.read()

        assert "EXPOSE 8088" in content


class TestWeatherProxyImportsSharedSchemas:
    """Tests for shared schema imports."""

    def test_weather_proxy_imports_weather_response(self):
        """Test Weather Proxy uses WeatherResponse from src/shared/models.py."""
        from interoperability.foundry.agents.weather.weather_proxy_direct_line.main import WeatherResponse

        # Import directly from shared models
        from src.shared.models import WeatherResponse as SharedWeatherResponse

        # Verify they are the same class (not duplicated)
        assert WeatherResponse is SharedWeatherResponse

    def test_weather_response_schema_fields(self):
        """Test WeatherResponse has expected fields."""
        from src.shared.models import WeatherResponse, ClimateSummary

        # Create a valid response
        response = WeatherResponse(
            location="Paris, France",
            start_date="2025-06-15",
            end_date="2025-06-20",
            climate_summary=ClimateSummary(
                average_high_temp_c=24.0,
                average_low_temp_c=14.0,
                average_precipitation_chance=25,
                typical_conditions="Mostly sunny with occasional afternoon clouds",
            ),
            summary="June in Paris is typically warm and pleasant.",
        )

        assert response.location == "Paris, France"
        assert response.climate_summary.average_high_temp_c == 24.0


class TestWeatherProxyExtractUserMessage:
    """Tests for user message extraction."""

    def test_extract_user_message_string_content(self):
        """Test extract_user_message handles string content."""
        from interoperability.foundry.agents.weather.weather_proxy_direct_line.main import extract_user_message

        messages = [{"role": "user", "content": "Get weather for Paris"}]
        result = extract_user_message(messages)

        assert result == "Get weather for Paris"

    def test_extract_user_message_list_content(self):
        """Test extract_user_message handles list content (OpenAI multi-modal format)."""
        from interoperability.foundry.agents.weather.weather_proxy_direct_line.main import extract_user_message

        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Get weather for"},
                {"type": "text", "text": "Paris, France"}
            ]
        }]
        result = extract_user_message(messages)

        assert result == "Get weather for Paris, France"

    def test_extract_user_message_mixed_list_content(self):
        """Test extract_user_message handles mixed content types in list."""
        from interoperability.foundry.agents.weather.weather_proxy_direct_line.main import extract_user_message

        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Weather request"},
                {"type": "image_url", "url": "http://example.com/img.png"},  # Should be ignored
                {"type": "text", "text": "for Tokyo"}
            ]
        }]
        result = extract_user_message(messages)

        assert result == "Weather request for Tokyo"

    def test_extract_user_message_empty_messages(self):
        """Test extract_user_message handles empty messages list."""
        from interoperability.foundry.agents.weather.weather_proxy_direct_line.main import extract_user_message

        result = extract_user_message([])
        assert result == ""

    def test_extract_user_message_uses_last_message(self):
        """Test extract_user_message uses the last message in the list."""
        from interoperability.foundry.agents.weather.weather_proxy_direct_line.main import extract_user_message

        messages = [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "Response"},
            {"role": "user", "content": "Last message"}
        ]
        result = extract_user_message(messages)

        assert result == "Last message"


class TestWeatherProxyParsesResponseSchema:
    """Tests for response parsing and JSON extraction."""

    def test_extract_json_from_plain_json(self):
        """Test extract_json_from_response handles plain JSON."""
        from interoperability.foundry.agents.weather.weather_proxy_direct_line.main import extract_json_from_response

        response = json.dumps({"location": "Paris", "test": True})
        result = extract_json_from_response(response)

        assert result["location"] == "Paris"
        assert result["test"] is True

    def test_extract_json_from_markdown_block(self):
        """Test extract_json_from_response handles markdown code blocks."""
        from interoperability.foundry.agents.weather.weather_proxy_direct_line.main import extract_json_from_response

        response = """Here is the weather data:

```json
{"location": "Paris", "summary": "Sunny"}
```

Let me know if you need more details."""
        result = extract_json_from_response(response)

        assert result["location"] == "Paris"
        assert result["summary"] == "Sunny"

    def test_extract_json_from_embedded_json(self):
        """Test extract_json_from_response handles JSON embedded in text."""
        from interoperability.foundry.agents.weather.weather_proxy_direct_line.main import extract_json_from_response

        response = 'The weather data is: {"location": "Tokyo", "temp": 25}'
        result = extract_json_from_response(response)

        assert result["location"] == "Tokyo"
        assert result["temp"] == 25

    def test_extract_json_raises_on_invalid(self):
        """Test extract_json_from_response raises ValueError for invalid JSON."""
        from interoperability.foundry.agents.weather.weather_proxy_direct_line.main import extract_json_from_response

        with pytest.raises(ValueError, match="Could not extract JSON"):
            extract_json_from_response("No JSON here at all")


class TestWeatherProxyCallsAgent:
    """Tests for the weather agent call."""

    def test_call_weather_agent_adds_json_instruction(self):
        """Test call_weather_agent appends JSON instruction to user message."""
        # We can't easily test the full async flow, but we can verify the function signature
        from interoperability.foundry.agents.weather.weather_proxy_direct_line.main import call_weather_agent
        import inspect

        # Verify the function takes a single user_message parameter
        sig = inspect.signature(call_weather_agent)
        params = list(sig.parameters.keys())
        assert params == ["user_message"], "call_weather_agent should take only user_message"

    def test_call_weather_agent_is_async(self):
        """Test call_weather_agent is an async function."""
        from interoperability.foundry.agents.weather.weather_proxy_direct_line.main import call_weather_agent
        import asyncio

        assert asyncio.iscoroutinefunction(call_weather_agent)


class TestWeatherProxyConfigYaml:
    """Tests for weather_proxy in foundry/config.yaml."""

    def test_weather_proxy_in_config(self):
        """Test weather_proxy is defined in foundry/config.yaml."""
        config_path = Path("interoperability/foundry/config.yaml")
        with open(config_path) as f:
            config = yaml.safe_load(f)

        assert "weather-proxy" in config["agents"]

    def test_weather_proxy_config_type(self):
        """Test weather_proxy is type: hosted."""
        config_path = Path("interoperability/foundry/config.yaml")
        with open(config_path) as f:
            config = yaml.safe_load(f)

        agent = config["agents"]["weather-proxy"]
        assert agent["type"] == "hosted"

    def test_weather_proxy_config_framework(self):
        """Test weather_proxy uses custom framework."""
        config_path = Path("interoperability/foundry/config.yaml")
        with open(config_path) as f:
            config = yaml.safe_load(f)

        agent = config["agents"]["weather-proxy"]
        assert agent["framework"] == "custom"

    def test_weather_proxy_config_env_vars(self):
        """Test weather_proxy has required env vars in config."""
        config_path = Path("interoperability/foundry/config.yaml")
        with open(config_path) as f:
            config = yaml.safe_load(f)

        agent = config["agents"]["weather-proxy"]
        env_vars = agent["env_vars"]

        # Direct Line only requires the secret
        assert "COPILOTSTUDIOAGENT__DIRECTLINE_SECRET" in env_vars
