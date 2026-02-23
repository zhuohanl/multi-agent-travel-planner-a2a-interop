"""Unit tests for Dining Agent agent.py."""

import json
import os
import pytest
from unittest.mock import patch, MagicMock

from src.shared.models import (
    DiningResponse,
    DiningOutput,
    DiningItem,
    Source,
)


@pytest.fixture(autouse=True)
def mock_environment():
    """Set required environment variables for all tests."""
    env_vars = {
        "SERVER_URL": "localhost",
        "DINING_AGENT_PORT": "10017",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_DEPLOYMENT_NAME": "test-deployment",
        "AZURE_OPENAI_API_VERSION": "2024-02-01",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


class TestAgentFrameworkDiningAgent:
    """Tests for AgentFrameworkDiningAgent class."""

    @pytest.fixture
    def agent_class(self, mock_environment):
        """Get the agent class with mocked environment."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                from src.agents.dining_agent.agent import AgentFrameworkDiningAgent
                yield AgentFrameworkDiningAgent

    def test_get_agent_name_returns_dining_agent(self, agent_class, mock_environment):
        """Test that get_agent_name returns 'DiningAgent'."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                agent = agent_class()
                assert agent.get_agent_name() == "DiningAgent"

    def test_get_prompt_name_returns_dining(self, agent_class, mock_environment):
        """Test that get_prompt_name returns 'dining'."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                agent = agent_class()
                assert agent.get_prompt_name() == "dining"

    def test_get_response_format_returns_dining_response(self, agent_class, mock_environment):
        """Test that get_response_format returns DiningResponse class."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                agent = agent_class()
                assert agent.get_response_format() == DiningResponse

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
                from src.agents.dining_agent.agent import AgentFrameworkDiningAgent
                return AgentFrameworkDiningAgent()

    def test_parse_response_with_text_response(self, agent, mock_environment):
        """Test parsing when agent needs more user input."""
        with patch.dict(os.environ, mock_environment):
            response_data = DiningResponse(
                dining_output=None,
                response="What cuisine are you interested in?"
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert result['content'] == "What cuisine are you interested in?"

    def test_parse_response_with_successful_output(self, agent, mock_environment):
        """Test parsing when agent returns complete dining results."""
        with patch.dict(os.environ, mock_environment):
            dining_output = DiningOutput(
                restaurants=[
                    DiningItem(
                        name="Sukiyabashi Jiro",
                        area="Ginza",
                        cuisine="Sushi",
                        priceRange="$$$$",
                        dietaryOptions=["pescatarian"],
                        link="https://example.com/jiro",
                        notes="Reservations required months in advance",
                        source=Source(title="Jiro Official", url="https://example.com/jiro")
                    )
                ],
                notes=["Top sushi restaurant in Tokyo"]
            )
            response_data = DiningResponse(dining_output=dining_output, response=None)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            assert result['require_user_input'] is False
            content = json.loads(result['content'])
            assert len(content['restaurants']) == 1
            assert content['restaurants'][0]['name'] == "Sukiyabashi Jiro"

    def test_parse_response_with_empty_output(self, agent, mock_environment):
        """Test parsing when both output and response are empty."""
        with patch.dict(os.environ, mock_environment):
            response_data = DiningResponse(dining_output=None, response=None)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert "destination" in result['content'].lower()

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

    def test_parse_response_with_multiple_restaurants(self, agent, mock_environment):
        """Test parsing with multiple restaurants."""
        with patch.dict(os.environ, mock_environment):
            dining_output = DiningOutput(
                restaurants=[
                    DiningItem(
                        name="Afuri Ramen",
                        area="Ebisu",
                        cuisine="Ramen",
                        priceRange="$$",
                        dietaryOptions=[],
                        link="https://example.com/afuri",
                        source=Source(title="Afuri", url="https://example.com/afuri")
                    ),
                    DiningItem(
                        name="T's TanTan",
                        area="Tokyo Station",
                        cuisine="Vegan Ramen",
                        priceRange="$",
                        dietaryOptions=["vegan", "vegetarian"],
                        link="https://example.com/tstan",
                        source=Source(title="T's TanTan", url="https://example.com/tstan")
                    ),
                    DiningItem(
                        name="Narisawa",
                        area="Minato",
                        cuisine="Innovative",
                        priceRange="$$$$",
                        dietaryOptions=["vegetarian-options"],
                        link="https://example.com/narisawa",
                        source=Source(title="Narisawa", url="https://example.com/narisawa")
                    ),
                ],
                notes=["Mix of casual and fine dining options"]
            )
            response_data = DiningResponse(dining_output=dining_output)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert len(content['restaurants']) == 3

    def test_parse_response_with_dietary_options(self, agent, mock_environment):
        """Test parsing with dietary constraint handling."""
        with patch.dict(os.environ, mock_environment):
            dining_output = DiningOutput(
                restaurants=[
                    DiningItem(
                        name="Ain Soph",
                        area="Ginza",
                        cuisine="Vegan",
                        priceRange="$$",
                        dietaryOptions=["vegan", "vegetarian", "gluten-free-options"],
                        link="https://example.com/ainsoph",
                        notes="Fully vegan restaurant",
                        source=Source(title="Ain Soph", url="https://example.com/ainsoph")
                    )
                ],
                notes=["Great option for vegan travelers"]
            )
            response_data = DiningResponse(dining_output=dining_output)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert "vegan" in content['restaurants'][0]['dietaryOptions']
            assert "vegetarian" in content['restaurants'][0]['dietaryOptions']

    def test_parse_response_with_optional_fields_null(self, agent, mock_environment):
        """Test parsing with optional fields as null."""
        with patch.dict(os.environ, mock_environment):
            dining_output = DiningOutput(
                restaurants=[
                    DiningItem(
                        name="Local Spot",
                        area=None,
                        cuisine=None,
                        priceRange=None,
                        dietaryOptions=[],
                        link="https://example.com",
                        notes=None,
                        source=Source(title="Site", url="https://example.com")
                    )
                ],
                notes=[]
            )
            response_data = DiningResponse(dining_output=dining_output)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert content['restaurants'][0]['area'] is None
            assert content['restaurants'][0]['cuisine'] is None
            assert content['restaurants'][0]['priceRange'] is None

    def test_parse_response_with_empty_restaurants_list(self, agent, mock_environment):
        """Test parsing when no restaurants found."""
        with patch.dict(os.environ, mock_environment):
            dining_output = DiningOutput(
                restaurants=[],
                notes=["No restaurants found matching dietary constraints"]
            )
            response_data = DiningResponse(dining_output=dining_output)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert len(content['restaurants']) == 0
            assert len(content['notes']) == 1


class TestDiningResponseModel:
    """Tests for DiningResponse model validation."""

    def test_dining_response_with_only_output(self):
        """Test creating DiningResponse with only dining_output."""
        dining_output = DiningOutput(
            restaurants=[],
            notes=[]
        )
        response = DiningResponse(dining_output=dining_output)
        assert response.dining_output is not None
        assert response.response is None

    def test_dining_response_with_only_response(self):
        """Test creating DiningResponse with only response text."""
        response = DiningResponse(response="Need more information")
        assert response.dining_output is None
        assert response.response == "Need more information"

    def test_dining_response_with_both(self):
        """Test creating DiningResponse with both fields."""
        dining_output = DiningOutput(restaurants=[], notes=[])
        response = DiningResponse(dining_output=dining_output, response="Here are your restaurants")
        assert response.dining_output is not None
        assert response.response is not None

    def test_dining_response_rejects_extra_fields(self):
        """Test that DiningResponse rejects extra fields."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            DiningResponse(
                dining_output=None,
                response=None,
                extra_field="not allowed"
            )

    def test_dining_response_json_serialization(self):
        """Test DiningResponse can be serialized to JSON."""
        dining_output = DiningOutput(
            restaurants=[
                DiningItem(
                    name="Test Restaurant",
                    area="Test Area",
                    cuisine="Test Cuisine",
                    priceRange="$$",
                    dietaryOptions=["vegetarian"],
                    link="https://test.com",
                    source=Source(title="Test", url="https://test.com")
                )
            ],
            notes=[]
        )
        response = DiningResponse(dining_output=dining_output)
        json_str = response.model_dump_json()
        parsed = json.loads(json_str)
        assert 'dining_output' in parsed
        assert 'response' in parsed

    def test_dining_item_requires_name_link_source(self):
        """Test DiningItem requires all mandatory fields."""
        from pydantic import ValidationError
        # Missing source
        with pytest.raises(ValidationError):
            DiningItem(
                name="Test",
                link="https://test.com"
            )

    def test_dining_item_dietary_options_defaults_to_empty(self):
        """Test DiningItem dietaryOptions defaults to empty list."""
        item = DiningItem(
            name="Test",
            link="https://test.com",
            source=Source(title="Test", url="https://test.com")
        )
        assert item.dietaryOptions == []
