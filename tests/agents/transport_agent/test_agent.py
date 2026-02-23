"""Unit tests for Transport Agent agent.py."""

import json
import os
import pytest
from unittest.mock import patch, MagicMock

from src.shared.models import (
    TransportResponse,
    TransportOutput,
    TransportOption,
    LocalTransfer,
    LocalPass,
    Source,
)


@pytest.fixture(autouse=True)
def mock_environment():
    """Set required environment variables for all tests."""
    env_vars = {
        "SERVER_URL": "localhost",
        "TRANSPORT_AGENT_PORT": "10010",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_DEPLOYMENT_NAME": "test-deployment",
        "AZURE_OPENAI_API_VERSION": "2024-02-01",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


class TestAgentFrameworkTransportAgent:
    """Tests for AgentFrameworkTransportAgent class."""

    @pytest.fixture
    def agent_class(self, mock_environment):
        """Get the agent class with mocked environment."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                from src.agents.transport_agent.agent import AgentFrameworkTransportAgent
                yield AgentFrameworkTransportAgent

    def test_get_agent_name_returns_transport_agent(self, agent_class, mock_environment):
        """Test that get_agent_name returns 'TransportAgent'."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                agent = agent_class()
                assert agent.get_agent_name() == "TransportAgent"

    def test_get_prompt_name_returns_transport(self, agent_class, mock_environment):
        """Test that get_prompt_name returns 'transport'."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                agent = agent_class()
                assert agent.get_prompt_name() == "transport"

    def test_get_response_format_returns_transport_response(self, agent_class, mock_environment):
        """Test that get_response_format returns TransportResponse class."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                agent = agent_class()
                assert agent.get_response_format() == TransportResponse

    def test_get_tools_returns_web_search_tool(self, agent_class, mock_environment):
        """Test that get_tools returns a list with HostedWebSearchTool."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool") as mock_tool:
                mock_tool.return_value = MagicMock()
                agent = agent_class()
                tools = agent.get_tools()
                assert len(tools) == 1


class TestParseResponse:
    """Tests for parse_response method."""

    @pytest.fixture
    def agent(self, mock_environment):
        """Create an agent instance for testing."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                from src.agents.transport_agent.agent import AgentFrameworkTransportAgent
                return AgentFrameworkTransportAgent()

    def test_parse_response_with_text_response(self, agent, mock_environment):
        """Test parsing when agent needs more user input."""
        with patch.dict(os.environ, mock_environment):
            response_data = TransportResponse(
                transport_output=None,
                response="What is your travel date?"
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert result['content'] == "What is your travel date?"

    def test_parse_response_with_successful_output(self, agent, mock_environment):
        """Test parsing when agent returns complete transport results."""
        with patch.dict(os.environ, mock_environment):
            transport_output = TransportOutput(
                transportOptions=[
                    TransportOption(
                        mode="train",
                        route="Tokyo -> Kyoto",
                        provider="JR Central",
                        date="2024-11-15",
                        durationMins=135,
                        price=14000,
                        currency="JPY",
                        link="https://jr-central.co.jp",
                        source=Source(title="JR Central", url="https://jr-central.co.jp")
                    )
                ],
                localTransfers=[
                    LocalTransfer(
                        name="Narita Express",
                        durationMins=60,
                        price=3250,
                        currency="JPY",
                        link="https://jreast.co.jp",
                        source=Source(title="JR East", url="https://jreast.co.jp")
                    )
                ],
                localPasses=[
                    LocalPass(
                        name="JR Pass 7-Day",
                        duration="7 days",
                        price=50000,
                        currency="JPY",
                        link="https://japanrailpass.net",
                        source=Source(title="JR Pass", url="https://japanrailpass.net")
                    )
                ],
                notes=["Shinkansen is the fastest option"]
            )
            response_data = TransportResponse(transport_output=transport_output, response=None)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            assert result['require_user_input'] is False
            content = json.loads(result['content'])
            assert len(content['transportOptions']) == 1
            assert len(content['localTransfers']) == 1
            assert len(content['localPasses']) == 1
            assert content['transportOptions'][0]['route'] == "Tokyo -> Kyoto"

    def test_parse_response_with_empty_output(self, agent, mock_environment):
        """Test parsing when both output and response are empty."""
        with patch.dict(os.environ, mock_environment):
            response_data = TransportResponse(transport_output=None, response=None)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert "origin" in result['content'].lower() or "destination" in result['content'].lower()

    def test_parse_response_with_invalid_json(self, agent, mock_environment):
        """Test parsing handles invalid JSON gracefully."""
        with patch.dict(os.environ, mock_environment):
            message = "not valid json {{"

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert "unable to process" in result['content'].lower()

    def test_parse_response_with_malformed_structure(self, agent, mock_environment):
        """Test parsing handles structurally invalid response."""
        with patch.dict(os.environ, mock_environment):
            message = '{"unexpected_field": "value"}'

            result = agent.parse_response(message)

            # Pydantic should reject extra fields due to extra="forbid"
            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True

    def test_parse_response_with_multiple_transport_options(self, agent, mock_environment):
        """Test parsing with multiple transport options."""
        with patch.dict(os.environ, mock_environment):
            transport_output = TransportOutput(
                transportOptions=[
                    TransportOption(
                        mode="train",
                        route="Tokyo -> Kyoto",
                        provider="JR Central",
                        durationMins=135,
                        price=14000,
                        currency="JPY",
                        link="https://jr-central.co.jp",
                        source=Source(title="JR Central", url="https://jr-central.co.jp")
                    ),
                    TransportOption(
                        mode="bus",
                        route="Tokyo -> Kyoto",
                        provider="Willer Express",
                        durationMins=480,
                        price=4000,
                        currency="JPY",
                        link="https://willer.co.jp",
                        source=Source(title="Willer", url="https://willer.co.jp")
                    ),
                    TransportOption(
                        mode="flight",
                        route="HND -> ITM",
                        provider="ANA",
                        durationMins=65,
                        price=20000,
                        currency="JPY",
                        link="https://ana.co.jp",
                        source=Source(title="ANA", url="https://ana.co.jp")
                    ),
                ],
                localTransfers=[],
                localPasses=[],
                notes=["Multiple options for different budgets"]
            )
            response_data = TransportResponse(transport_output=transport_output)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert len(content['transportOptions']) == 3

    def test_parse_response_with_flight_mode(self, agent, mock_environment):
        """Test parsing with flight transport option."""
        with patch.dict(os.environ, mock_environment):
            transport_output = TransportOutput(
                transportOptions=[
                    TransportOption(
                        mode="flight",
                        route="NYC -> NRT",
                        provider="JAL",
                        date="2024-11-10",
                        durationMins=840,
                        price=1200,
                        currency="USD",
                        link="https://jal.com",
                        source=Source(title="JAL", url="https://jal.com")
                    )
                ],
                localTransfers=[],
                localPasses=[],
                notes=[]
            )
            response_data = TransportResponse(transport_output=transport_output)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert content['transportOptions'][0]['mode'] == "flight"

    def test_parse_response_with_optional_fields_null(self, agent, mock_environment):
        """Test parsing with optional fields as null."""
        with patch.dict(os.environ, mock_environment):
            transport_output = TransportOutput(
                transportOptions=[
                    TransportOption(
                        mode="train",
                        route="A -> B",
                        provider=None,
                        date=None,
                        durationMins=None,
                        price=None,
                        currency=None,
                        link="https://example.com",
                        source=Source(title="Example", url="https://example.com")
                    )
                ],
                localTransfers=[],
                localPasses=[],
                notes=[]
            )
            response_data = TransportResponse(transport_output=transport_output)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert content['transportOptions'][0]['provider'] is None
            assert content['transportOptions'][0]['date'] is None
            assert content['transportOptions'][0]['durationMins'] is None

    def test_parse_response_with_multiple_local_passes(self, agent, mock_environment):
        """Test parsing with multiple local passes."""
        with patch.dict(os.environ, mock_environment):
            transport_output = TransportOutput(
                transportOptions=[],
                localTransfers=[],
                localPasses=[
                    LocalPass(
                        name="JR Pass 7-Day",
                        duration="7 days",
                        price=50000,
                        currency="JPY",
                        link="https://japanrailpass.net",
                        source=Source(title="JR Pass", url="https://japanrailpass.net")
                    ),
                    LocalPass(
                        name="Suica Card",
                        duration="Rechargeable",
                        price=2000,
                        currency="JPY",
                        link="https://jreast.co.jp/suica",
                        source=Source(title="Suica", url="https://jreast.co.jp/suica")
                    ),
                ],
                notes=["Both passes are useful for tourists"]
            )
            response_data = TransportResponse(transport_output=transport_output)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert len(content['localPasses']) == 2


class TestTransportResponseModel:
    """Tests for TransportResponse model validation."""

    def test_transport_response_with_only_output(self):
        """Test creating TransportResponse with only transport_output."""
        transport_output = TransportOutput(
            transportOptions=[],
            localTransfers=[],
            localPasses=[],
            notes=[]
        )
        response = TransportResponse(transport_output=transport_output)
        assert response.transport_output is not None
        assert response.response is None

    def test_transport_response_with_only_response(self):
        """Test creating TransportResponse with only response text."""
        response = TransportResponse(response="Need more information")
        assert response.transport_output is None
        assert response.response == "Need more information"

    def test_transport_response_with_both(self):
        """Test creating TransportResponse with both fields."""
        transport_output = TransportOutput(
            transportOptions=[], localTransfers=[], localPasses=[], notes=[]
        )
        response = TransportResponse(
            transport_output=transport_output, response="Here are your options"
        )
        assert response.transport_output is not None
        assert response.response is not None

    def test_transport_response_rejects_extra_fields(self):
        """Test that TransportResponse rejects extra fields."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TransportResponse(
                transport_output=None,
                response=None,
                extra_field="not allowed"
            )

    def test_transport_response_json_serialization(self):
        """Test TransportResponse can be serialized to JSON."""
        transport_output = TransportOutput(
            transportOptions=[
                TransportOption(
                    mode="train",
                    route="A -> B",
                    link="https://test.com",
                    source=Source(title="Test", url="https://test.com")
                )
            ],
            localTransfers=[],
            localPasses=[],
            notes=[]
        )
        response = TransportResponse(transport_output=transport_output)
        json_str = response.model_dump_json()
        parsed = json.loads(json_str)
        assert 'transport_output' in parsed
        assert 'response' in parsed


class TestTransportModeValidation:
    """Tests for TransportMode literal type validation."""

    def test_valid_flight_mode(self):
        """Test that 'flight' is a valid transport mode."""
        option = TransportOption(
            mode="flight",
            route="A -> B",
            link="https://test.com",
            source=Source(title="Test", url="https://test.com")
        )
        assert option.mode == "flight"

    def test_valid_train_mode(self):
        """Test that 'train' is a valid transport mode."""
        option = TransportOption(
            mode="train",
            route="A -> B",
            link="https://test.com",
            source=Source(title="Test", url="https://test.com")
        )
        assert option.mode == "train"

    def test_valid_bus_mode(self):
        """Test that 'bus' is a valid transport mode."""
        option = TransportOption(
            mode="bus",
            route="A -> B",
            link="https://test.com",
            source=Source(title="Test", url="https://test.com")
        )
        assert option.mode == "bus"

    def test_invalid_mode_rejected(self):
        """Test that invalid transport modes are rejected."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TransportOption(
                mode="bicycle",
                route="A -> B",
                link="https://test.com",
                source=Source(title="Test", url="https://test.com")
            )
