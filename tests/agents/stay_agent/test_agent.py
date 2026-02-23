"""Unit tests for Stay Agent agent.py."""

import json
import os
import pytest
from unittest.mock import patch, MagicMock

from src.shared.models import (
    StayResponse,
    StayOutput,
    StayItem,
    Neighborhood,
    Source,
)


@pytest.fixture(autouse=True)
def mock_environment():
    """Set required environment variables for all tests."""
    env_vars = {
        "SERVER_URL": "localhost",
        "STAY_AGENT_PORT": "10009",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_DEPLOYMENT_NAME": "test-deployment",
        "AZURE_OPENAI_API_VERSION": "2024-02-01",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


class TestAgentFrameworkStayAgent:
    """Tests for AgentFrameworkStayAgent class."""

    @pytest.fixture
    def agent_class(self, mock_environment):
        """Get the agent class with mocked environment."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                from src.agents.stay_agent.agent import AgentFrameworkStayAgent
                yield AgentFrameworkStayAgent

    def test_get_agent_name_returns_stay_agent(self, agent_class, mock_environment):
        """Test that get_agent_name returns 'StayAgent'."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                agent = agent_class()
                assert agent.get_agent_name() == "StayAgent"

    def test_get_prompt_name_returns_stay(self, agent_class, mock_environment):
        """Test that get_prompt_name returns 'stay'."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                agent = agent_class()
                assert agent.get_prompt_name() == "stay"

    def test_get_response_format_returns_stay_response(self, agent_class, mock_environment):
        """Test that get_response_format returns StayResponse class."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                agent = agent_class()
                assert agent.get_response_format() == StayResponse

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
                from src.agents.stay_agent.agent import AgentFrameworkStayAgent
                return AgentFrameworkStayAgent()

    def test_parse_response_with_text_response(self, agent, mock_environment):
        """Test parsing when agent needs more user input."""
        with patch.dict(os.environ, mock_environment):
            response_data = StayResponse(
                stay_output=None,
                response="What is your budget for accommodations?"
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert result['content'] == "What is your budget for accommodations?"

    def test_parse_response_with_successful_output(self, agent, mock_environment):
        """Test parsing when agent returns complete stay results."""
        with patch.dict(os.environ, mock_environment):
            stay_output = StayOutput(
                neighborhoods=[
                    Neighborhood(
                        name="Shinjuku",
                        reasons=["Convenient transport", "Nightlife"],
                        source=Source(title="Tokyo Guide", url="https://example.com")
                    )
                ],
                stays=[
                    StayItem(
                        name="Park Hyatt Tokyo",
                        area="Shinjuku",
                        pricePerNight=400,
                        currency="USD",
                        link="https://parkhyatt.com",
                        notes="Famous from Lost in Translation",
                        source=Source(title="Hotel Site", url="https://parkhyatt.com")
                    )
                ],
                notes=["Luxury option in Shinjuku"]
            )
            response_data = StayResponse(stay_output=stay_output, response=None)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            assert result['require_user_input'] is False
            # Content should be the StayOutput JSON
            content = json.loads(result['content'])
            assert len(content['neighborhoods']) == 1
            assert len(content['stays']) == 1
            assert content['neighborhoods'][0]['name'] == "Shinjuku"
            assert content['stays'][0]['name'] == "Park Hyatt Tokyo"

    def test_parse_response_with_empty_output(self, agent, mock_environment):
        """Test parsing when both output and response are empty."""
        with patch.dict(os.environ, mock_environment):
            response_data = StayResponse(stay_output=None, response=None)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert "destination city" in result['content'].lower()

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

    def test_parse_response_with_multiple_neighborhoods(self, agent, mock_environment):
        """Test parsing with multiple neighborhoods."""
        with patch.dict(os.environ, mock_environment):
            stay_output = StayOutput(
                neighborhoods=[
                    Neighborhood(
                        name="Shinjuku",
                        reasons=["Transport hub"],
                        source=Source(title="Guide", url="https://example.com")
                    ),
                    Neighborhood(
                        name="Shibuya",
                        reasons=["Shopping", "Youth culture"],
                        source=Source(title="Guide", url="https://example.com")
                    ),
                ],
                stays=[],
                notes=[]
            )
            response_data = StayResponse(stay_output=stay_output)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert len(content['neighborhoods']) == 2

    def test_parse_response_with_multiple_stays(self, agent, mock_environment):
        """Test parsing with multiple stay options."""
        with patch.dict(os.environ, mock_environment):
            stay_output = StayOutput(
                neighborhoods=[],
                stays=[
                    StayItem(
                        name="Budget Hotel",
                        area="Ueno",
                        pricePerNight=80,
                        currency="USD",
                        link="https://budget.com",
                        source=Source(title="Site", url="https://budget.com")
                    ),
                    StayItem(
                        name="Mid-range Hotel",
                        area="Shinjuku",
                        pricePerNight=150,
                        currency="USD",
                        link="https://midrange.com",
                        source=Source(title="Site", url="https://midrange.com")
                    ),
                    StayItem(
                        name="Luxury Hotel",
                        area="Ginza",
                        pricePerNight=400,
                        currency="USD",
                        link="https://luxury.com",
                        source=Source(title="Site", url="https://luxury.com")
                    ),
                ],
                notes=["Range of options for different budgets"]
            )
            response_data = StayResponse(stay_output=stay_output)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert len(content['stays']) == 3

    def test_parse_response_with_optional_fields_null(self, agent, mock_environment):
        """Test parsing with optional fields as null."""
        with patch.dict(os.environ, mock_environment):
            stay_output = StayOutput(
                neighborhoods=[],
                stays=[
                    StayItem(
                        name="Basic Hotel",
                        area="Downtown",
                        pricePerNight=None,
                        currency=None,
                        link="https://basic.com",
                        notes=None,
                        source=Source(title="Site", url="https://basic.com")
                    )
                ],
                notes=[]
            )
            response_data = StayResponse(stay_output=stay_output)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert content['stays'][0]['pricePerNight'] is None
            assert content['stays'][0]['currency'] is None
            assert content['stays'][0]['notes'] is None


class TestStayResponseModel:
    """Tests for StayResponse model validation."""

    def test_stay_response_with_only_output(self):
        """Test creating StayResponse with only stay_output."""
        stay_output = StayOutput(
            neighborhoods=[],
            stays=[],
            notes=[]
        )
        response = StayResponse(stay_output=stay_output)
        assert response.stay_output is not None
        assert response.response is None

    def test_stay_response_with_only_response(self):
        """Test creating StayResponse with only response text."""
        response = StayResponse(response="Need more information")
        assert response.stay_output is None
        assert response.response == "Need more information"

    def test_stay_response_with_both(self):
        """Test creating StayResponse with both fields."""
        stay_output = StayOutput(neighborhoods=[], stays=[], notes=[])
        response = StayResponse(stay_output=stay_output, response="Here are your options")
        assert response.stay_output is not None
        assert response.response is not None

    def test_stay_response_rejects_extra_fields(self):
        """Test that StayResponse rejects extra fields."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            StayResponse(
                stay_output=None,
                response=None,
                extra_field="not allowed"
            )

    def test_stay_response_json_serialization(self):
        """Test StayResponse can be serialized to JSON."""
        stay_output = StayOutput(
            neighborhoods=[
                Neighborhood(
                    name="Test Area",
                    reasons=["Reason 1"],
                    source=Source(title="Test", url="https://test.com")
                )
            ],
            stays=[],
            notes=[]
        )
        response = StayResponse(stay_output=stay_output)
        json_str = response.model_dump_json()
        parsed = json.loads(json_str)
        assert 'stay_output' in parsed
        assert 'response' in parsed
