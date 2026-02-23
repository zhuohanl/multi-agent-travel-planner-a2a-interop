"""Unit tests for Aggregator Agent agent.py."""

import json
import os
import pytest
from unittest.mock import patch, MagicMock

from src.shared.models import (
    AggregatorResponse,
    DiscoveryResults,
    SearchOutput,
    StayOutput,
    TransportOutput,
    EventsOutput,
    DiningOutput,
    POI,
    StayItem,
    Neighborhood,
    TransportOption,
    EventItem,
    DiningItem,
    Source,
)


@pytest.fixture(autouse=True)
def mock_environment():
    """Set required environment variables for all tests."""
    env_vars = {
        "SERVER_URL": "localhost",
        "AGGREGATOR_AGENT_PORT": "10015",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_DEPLOYMENT_NAME": "test-deployment",
        "AZURE_OPENAI_API_VERSION": "2024-02-01",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


class TestAgentFrameworkAggregatorAgent:
    """Tests for AgentFrameworkAggregatorAgent class."""

    @pytest.fixture
    def agent_class(self, mock_environment):
        """Get the agent class with mocked environment."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.aggregator_agent.agent import AgentFrameworkAggregatorAgent
            yield AgentFrameworkAggregatorAgent

    def test_get_agent_name_returns_aggregator_agent(self, agent_class, mock_environment):
        """Test that get_agent_name returns 'AggregatorAgent'."""
        with patch.dict(os.environ, mock_environment):
            agent = agent_class()
            assert agent.get_agent_name() == "AggregatorAgent"

    def test_get_prompt_name_returns_aggregator(self, agent_class, mock_environment):
        """Test that get_prompt_name returns 'aggregator'."""
        with patch.dict(os.environ, mock_environment):
            agent = agent_class()
            assert agent.get_prompt_name() == "aggregator"

    def test_get_response_format_returns_aggregator_response(self, agent_class, mock_environment):
        """Test that get_response_format returns AggregatorResponse class."""
        with patch.dict(os.environ, mock_environment):
            agent = agent_class()
            assert agent.get_response_format() == AggregatorResponse

    def test_get_tools_returns_empty_list(self, agent_class, mock_environment):
        """Test that get_tools returns an empty list (no external tools needed)."""
        with patch.dict(os.environ, mock_environment):
            agent = agent_class()
            tools = agent.get_tools()
            assert tools == []


class TestParseResponse:
    """Tests for parse_response method."""

    @pytest.fixture
    def agent(self, mock_environment):
        """Create an agent instance for testing."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.aggregator_agent.agent import AgentFrameworkAggregatorAgent
            return AgentFrameworkAggregatorAgent()

    def test_parse_response_with_text_response(self, agent, mock_environment):
        """Test parsing when agent needs more user input."""
        with patch.dict(os.environ, mock_environment):
            response_data = AggregatorResponse(
                aggregated_results=None,
                response="Please provide discovery results to aggregate."
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert result['content'] == "Please provide discovery results to aggregate."

    def test_parse_response_with_successful_output(self, agent, mock_environment):
        """Test parsing when agent returns aggregated results."""
        with patch.dict(os.environ, mock_environment):
            discovery_results = DiscoveryResults(
                pois=SearchOutput(
                    pois=[
                        POI(
                            name="Tokyo Tower",
                            area="Minato",
                            tags=["landmark", "observation"],
                            estCost=15.0,
                            currency="USD",
                            source=Source(title="Tokyo Tower", url="https://example.com/tower")
                        )
                    ],
                    notes=["Popular landmark"]
                ),
                stays=None,
                transport=None,
                events=None,
                dining=None
            )
            response_data = AggregatorResponse(aggregated_results=discovery_results, response=None)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            assert result['require_user_input'] is False
            content = json.loads(result['content'])
            assert 'pois' in content
            assert content['pois']['pois'][0]['name'] == "Tokyo Tower"

    def test_parse_response_with_empty_output(self, agent, mock_environment):
        """Test parsing when both output and response are empty."""
        with patch.dict(os.environ, mock_environment):
            response_data = AggregatorResponse(aggregated_results=None, response=None)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert "discovery results" in result['content'].lower()

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

    def test_parse_response_with_full_discovery_results(self, agent, mock_environment):
        """Test parsing with all discovery categories populated."""
        with patch.dict(os.environ, mock_environment):
            discovery_results = DiscoveryResults(
                pois=SearchOutput(
                    pois=[
                        POI(
                            name="Senso-ji Temple",
                            area="Asakusa",
                            tags=["temple", "historic"],
                            estCost=0.0,
                            currency="USD",
                            source=Source(title="Senso-ji", url="https://example.com/sensoji")
                        )
                    ],
                    notes=["Free entry"]
                ),
                stays=StayOutput(
                    neighborhoods=[
                        Neighborhood(
                            name="Shinjuku",
                            reasons=["Central", "Good transport"],
                            source=Source(title="Tokyo Guide", url="https://example.com/guide")
                        )
                    ],
                    stays=[
                        StayItem(
                            name="Park Hyatt Tokyo",
                            area="Shinjuku",
                            pricePerNight=500.0,
                            currency="USD",
                            link="https://example.com/parkhyatt",
                            source=Source(title="Park Hyatt", url="https://example.com/parkhyatt")
                        )
                    ],
                    notes=["Luxury option"]
                ),
                transport=TransportOutput(
                    transportOptions=[
                        TransportOption(
                            mode="flight",
                            route="SFO-NRT",
                            provider="ANA",
                            date="2025-11-10",
                            durationMins=660,
                            price=1200.0,
                            currency="USD",
                            link="https://example.com/flight",
                            source=Source(title="ANA", url="https://example.com/ana")
                        )
                    ],
                    localTransfers=[],
                    localPasses=[],
                    notes=["Direct flight"]
                ),
                events=EventsOutput(
                    events=[
                        EventItem(
                            name="Tokyo Game Show",
                            date="2025-11-12",
                            area="Chiba",
                            link="https://example.com/tgs",
                            source=Source(title="TGS", url="https://example.com/tgs")
                        )
                    ],
                    notes=["Popular gaming event"]
                ),
                dining=DiningOutput(
                    restaurants=[
                        DiningItem(
                            name="Sukiyabashi Jiro",
                            area="Ginza",
                            cuisine="Sushi",
                            priceRange="$$$$",
                            dietaryOptions=["pescatarian"],
                            link="https://example.com/jiro",
                            source=Source(title="Jiro", url="https://example.com/jiro")
                        )
                    ],
                    notes=["Reservation required"]
                )
            )
            response_data = AggregatorResponse(aggregated_results=discovery_results)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert content['pois'] is not None
            assert content['stays'] is not None
            assert content['transport'] is not None
            assert content['events'] is not None
            assert content['dining'] is not None

    def test_parse_response_with_partial_results(self, agent, mock_environment):
        """Test parsing when some discovery categories are null."""
        with patch.dict(os.environ, mock_environment):
            discovery_results = DiscoveryResults(
                pois=SearchOutput(pois=[], notes=[]),
                stays=None,
                transport=TransportOutput(
                    transportOptions=[],
                    localTransfers=[],
                    localPasses=[],
                    notes=[]
                ),
                events=None,
                dining=None
            )
            response_data = AggregatorResponse(aggregated_results=discovery_results)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert content['pois'] is not None
            assert content['stays'] is None
            assert content['transport'] is not None
            assert content['events'] is None
            assert content['dining'] is None


class TestAggregatorResponseModel:
    """Tests for AggregatorResponse model validation."""

    def test_aggregator_response_with_only_results(self):
        """Test creating AggregatorResponse with only aggregated_results."""
        discovery_results = DiscoveryResults(
            pois=None,
            stays=None,
            transport=None,
            events=None,
            dining=None
        )
        response = AggregatorResponse(aggregated_results=discovery_results)
        assert response.aggregated_results is not None
        assert response.response is None

    def test_aggregator_response_with_only_response(self):
        """Test creating AggregatorResponse with only response text."""
        response = AggregatorResponse(response="Need discovery inputs")
        assert response.aggregated_results is None
        assert response.response == "Need discovery inputs"

    def test_aggregator_response_with_both(self):
        """Test creating AggregatorResponse with both fields."""
        discovery_results = DiscoveryResults()
        response = AggregatorResponse(
            aggregated_results=discovery_results,
            response="Here are your aggregated results"
        )
        assert response.aggregated_results is not None
        assert response.response is not None

    def test_aggregator_response_rejects_extra_fields(self):
        """Test that AggregatorResponse rejects extra fields."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AggregatorResponse(
                aggregated_results=None,
                response=None,
                extra_field="not allowed"
            )

    def test_aggregator_response_json_serialization(self):
        """Test AggregatorResponse can be serialized to JSON."""
        discovery_results = DiscoveryResults(
            pois=SearchOutput(
                pois=[
                    POI(
                        name="Test POI",
                        area="Test Area",
                        tags=["test"],
                        source=Source(title="Test", url="https://test.com")
                    )
                ],
                notes=[]
            )
        )
        response = AggregatorResponse(aggregated_results=discovery_results)
        json_str = response.model_dump_json()
        parsed = json.loads(json_str)
        assert 'aggregated_results' in parsed
        assert 'response' in parsed

    def test_discovery_results_all_fields_optional(self):
        """Test that all DiscoveryResults fields are optional."""
        # Empty DiscoveryResults should be valid
        results = DiscoveryResults()
        assert results.pois is None
        assert results.stays is None
        assert results.transport is None
        assert results.events is None
        assert results.dining is None

    def test_discovery_results_partial_population(self):
        """Test DiscoveryResults with some fields populated."""
        results = DiscoveryResults(
            pois=SearchOutput(pois=[], notes=["No POIs found"]),
            dining=DiningOutput(restaurants=[], notes=["No restaurants found"])
        )
        assert results.pois is not None
        assert results.stays is None
        assert results.transport is None
        assert results.events is None
        assert results.dining is not None


class TestAgentNoTools:
    """Tests to verify the agent has no external tools."""

    @pytest.fixture
    def agent(self, mock_environment):
        """Create an agent instance for testing."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.aggregator_agent.agent import AgentFrameworkAggregatorAgent
            return AgentFrameworkAggregatorAgent()

    def test_agent_has_no_tools(self, agent, mock_environment):
        """Verify the aggregator agent does not require external tools."""
        with patch.dict(os.environ, mock_environment):
            tools = agent.get_tools()
            assert len(tools) == 0
            assert tools == []

    def test_agent_inherits_from_base(self, mock_environment):
        """Test that agent inherits from BaseAgentFrameworkAgent."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.aggregator_agent.agent import AgentFrameworkAggregatorAgent
            from src.shared.agents.base_agent import BaseAgentFrameworkAgent

            assert issubclass(AgentFrameworkAggregatorAgent, BaseAgentFrameworkAgent)
