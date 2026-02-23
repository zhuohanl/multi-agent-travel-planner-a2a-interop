"""Unit tests for Events Agent agent.py."""

import json
import os
import pytest
from unittest.mock import patch, MagicMock

from src.shared.models import (
    EventsResponse,
    EventsOutput,
    EventItem,
    Source,
)


@pytest.fixture(autouse=True)
def mock_environment():
    """Set required environment variables for all tests."""
    env_vars = {
        "SERVER_URL": "localhost",
        "EVENTS_AGENT_PORT": "10011",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_DEPLOYMENT_NAME": "test-deployment",
        "AZURE_OPENAI_API_VERSION": "2024-02-01",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


class TestAgentFrameworkEventsAgent:
    """Tests for AgentFrameworkEventsAgent class."""

    @pytest.fixture
    def agent_class(self, mock_environment):
        """Get the agent class with mocked environment."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                from src.agents.events_agent.agent import AgentFrameworkEventsAgent
                yield AgentFrameworkEventsAgent

    def test_get_agent_name_returns_events_agent(self, agent_class, mock_environment):
        """Test that get_agent_name returns 'EventsAgent'."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                agent = agent_class()
                assert agent.get_agent_name() == "EventsAgent"

    def test_get_prompt_name_returns_events(self, agent_class, mock_environment):
        """Test that get_prompt_name returns 'events'."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                agent = agent_class()
                assert agent.get_prompt_name() == "events"

    def test_get_response_format_returns_events_response(self, agent_class, mock_environment):
        """Test that get_response_format returns EventsResponse class."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                agent = agent_class()
                assert agent.get_response_format() == EventsResponse

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
                from src.agents.events_agent.agent import AgentFrameworkEventsAgent
                return AgentFrameworkEventsAgent()

    def test_parse_response_with_text_response(self, agent, mock_environment):
        """Test parsing when agent needs more user input."""
        with patch.dict(os.environ, mock_environment):
            response_data = EventsResponse(
                events_output=None,
                response="What dates are you traveling?"
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert result['content'] == "What dates are you traveling?"

    def test_parse_response_with_successful_output(self, agent, mock_environment):
        """Test parsing when agent returns complete event results."""
        with patch.dict(os.environ, mock_environment):
            events_output = EventsOutput(
                events=[
                    EventItem(
                        name="Tokyo Game Show",
                        date="2025-09-25",
                        area="Makuhari Messe",
                        link="https://tgs.cesa.or.jp",
                        note="Annual gaming convention",
                        source=Source(title="TGS Official", url="https://tgs.cesa.or.jp")
                    )
                ],
                notes=["Major gaming event in Japan"]
            )
            response_data = EventsResponse(events_output=events_output, response=None)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            assert result['require_user_input'] is False
            # Content should be the EventsOutput JSON
            content = json.loads(result['content'])
            assert len(content['events']) == 1
            assert content['events'][0]['name'] == "Tokyo Game Show"

    def test_parse_response_with_empty_output(self, agent, mock_environment):
        """Test parsing when both output and response are empty."""
        with patch.dict(os.environ, mock_environment):
            response_data = EventsResponse(events_output=None, response=None)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert "destination" in result['content'].lower() or "dates" in result['content'].lower()

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

    def test_parse_response_with_multiple_events(self, agent, mock_environment):
        """Test parsing with multiple events."""
        with patch.dict(os.environ, mock_environment):
            events_output = EventsOutput(
                events=[
                    EventItem(
                        name="Tokyo Game Show",
                        date="2025-09-25",
                        area="Makuhari Messe",
                        link="https://tgs.cesa.or.jp",
                        source=Source(title="TGS Official", url="https://tgs.cesa.or.jp")
                    ),
                    EventItem(
                        name="Comiket",
                        date="2025-08-15",
                        area="Tokyo Big Sight",
                        link="https://comiket.co.jp",
                        source=Source(title="Comiket", url="https://comiket.co.jp")
                    ),
                    EventItem(
                        name="Fuji Rock Festival",
                        date="2025-07-25",
                        area="Naeba",
                        link="https://fujirockfestival.com",
                        source=Source(title="Fuji Rock", url="https://fujirockfestival.com")
                    ),
                ],
                notes=["Mix of gaming, anime, and music events"]
            )
            response_data = EventsResponse(events_output=events_output)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert len(content['events']) == 3

    def test_parse_response_with_optional_fields_null(self, agent, mock_environment):
        """Test parsing with optional fields as null."""
        with patch.dict(os.environ, mock_environment):
            events_output = EventsOutput(
                events=[
                    EventItem(
                        name="Local Festival",
                        date="2025-11-10",
                        area=None,
                        link="https://example.com",
                        note=None,
                        source=Source(title="Site", url="https://example.com")
                    )
                ],
                notes=[]
            )
            response_data = EventsResponse(events_output=events_output)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert content['events'][0]['area'] is None
            assert content['events'][0]['note'] is None

    def test_parse_response_with_empty_events_list(self, agent, mock_environment):
        """Test parsing when no events found."""
        with patch.dict(os.environ, mock_environment):
            events_output = EventsOutput(
                events=[],
                notes=["No events found for the specified dates"]
            )
            response_data = EventsResponse(events_output=events_output)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert len(content['events']) == 0
            assert len(content['notes']) == 1


class TestEventsResponseModel:
    """Tests for EventsResponse model validation."""

    def test_events_response_with_only_output(self):
        """Test creating EventsResponse with only events_output."""
        events_output = EventsOutput(
            events=[],
            notes=[]
        )
        response = EventsResponse(events_output=events_output)
        assert response.events_output is not None
        assert response.response is None

    def test_events_response_with_only_response(self):
        """Test creating EventsResponse with only response text."""
        response = EventsResponse(response="Need more information")
        assert response.events_output is None
        assert response.response == "Need more information"

    def test_events_response_with_both(self):
        """Test creating EventsResponse with both fields."""
        events_output = EventsOutput(events=[], notes=[])
        response = EventsResponse(events_output=events_output, response="Here are your events")
        assert response.events_output is not None
        assert response.response is not None

    def test_events_response_rejects_extra_fields(self):
        """Test that EventsResponse rejects extra fields."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            EventsResponse(
                events_output=None,
                response=None,
                extra_field="not allowed"
            )

    def test_events_response_json_serialization(self):
        """Test EventsResponse can be serialized to JSON."""
        events_output = EventsOutput(
            events=[
                EventItem(
                    name="Test Event",
                    date="2025-11-15",
                    area="Test Area",
                    link="https://test.com",
                    source=Source(title="Test", url="https://test.com")
                )
            ],
            notes=[]
        )
        response = EventsResponse(events_output=events_output)
        json_str = response.model_dump_json()
        parsed = json.loads(json_str)
        assert 'events_output' in parsed
        assert 'response' in parsed

    def test_event_item_requires_name_date_link_source(self):
        """Test EventItem requires all mandatory fields."""
        from pydantic import ValidationError
        # Missing source
        with pytest.raises(ValidationError):
            EventItem(
                name="Test",
                date="2025-11-15",
                link="https://test.com"
            )
