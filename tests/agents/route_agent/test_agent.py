"""Unit tests for Route Agent agent.py."""

import json
import os
import pytest
from unittest.mock import patch, MagicMock

from src.shared.models import (
    RouteResponse,
    Itinerary,
    ItineraryDay,
    ItinerarySlot,
)


@pytest.fixture(autouse=True)
def mock_environment():
    """Set required environment variables for all tests."""
    env_vars = {
        "SERVER_URL": "localhost",
        "ROUTE_AGENT_PORT": "10012",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_DEPLOYMENT_NAME": "test-deployment",
        "AZURE_OPENAI_API_VERSION": "2024-02-01",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


class TestAgentFrameworkRouteAgent:
    """Tests for AgentFrameworkRouteAgent class."""

    @pytest.fixture
    def agent_class(self, mock_environment):
        """Get the agent class with mocked environment."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.route_agent.agent import AgentFrameworkRouteAgent
            yield AgentFrameworkRouteAgent

    def test_get_agent_name_returns_route_agent(self, agent_class, mock_environment):
        """Test that get_agent_name returns 'RouteAgent'."""
        with patch.dict(os.environ, mock_environment):
            agent = agent_class()
            assert agent.get_agent_name() == "RouteAgent"

    def test_get_prompt_name_returns_route(self, agent_class, mock_environment):
        """Test that get_prompt_name returns 'route'."""
        with patch.dict(os.environ, mock_environment):
            agent = agent_class()
            assert agent.get_prompt_name() == "route"

    def test_get_response_format_returns_route_response(self, agent_class, mock_environment):
        """Test that get_response_format returns RouteResponse class."""
        with patch.dict(os.environ, mock_environment):
            agent = agent_class()
            assert agent.get_response_format() == RouteResponse

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
            from src.agents.route_agent.agent import AgentFrameworkRouteAgent
            return AgentFrameworkRouteAgent()

    def test_parse_response_with_text_response(self, agent, mock_environment):
        """Test parsing when agent needs more user input."""
        with patch.dict(os.environ, mock_environment):
            response_data = RouteResponse(
                itinerary=None,
                response="Please provide TripSpec and discovery results."
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert result['content'] == "Please provide TripSpec and discovery results."

    def test_parse_response_with_successful_itinerary(self, agent, mock_environment):
        """Test parsing when agent returns a complete itinerary."""
        with patch.dict(os.environ, mock_environment):
            itinerary = Itinerary(
                days=[
                    ItineraryDay(
                        date="2025-11-10",
                        slots=[
                            ItinerarySlot(
                                start_time="09:00",
                                end_time="12:00",
                                activity="Visit Tokyo Tower",
                                location="Minato",
                                category="poi",
                                item_ref="Tokyo Tower",
                                estimated_cost=15.0,
                                currency="USD",
                                notes="Great views of the city"
                            )
                        ],
                        day_summary="Arrival day - Tokyo Tower visit"
                    )
                ],
                total_estimated_cost=15.0,
                currency="USD"
            )
            response_data = RouteResponse(itinerary=itinerary, response=None)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            assert result['require_user_input'] is False
            content = json.loads(result['content'])
            assert 'days' in content
            assert len(content['days']) == 1
            assert content['days'][0]['date'] == "2025-11-10"

    def test_parse_response_with_empty_output(self, agent, mock_environment):
        """Test parsing when both output and response are empty."""
        with patch.dict(os.environ, mock_environment):
            response_data = RouteResponse(itinerary=None, response=None)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert "tripspec" in result['content'].lower() or "discovery" in result['content'].lower()

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

    def test_parse_response_with_multi_day_itinerary(self, agent, mock_environment):
        """Test parsing a multi-day itinerary."""
        with patch.dict(os.environ, mock_environment):
            itinerary = Itinerary(
                days=[
                    ItineraryDay(
                        date="2025-11-10",
                        slots=[
                            ItinerarySlot(
                                start_time="09:00",
                                end_time="12:00",
                                activity="Visit Senso-ji Temple",
                                location="Asakusa",
                                category="poi",
                                item_ref="Senso-ji Temple"
                            ),
                            ItinerarySlot(
                                start_time="12:30",
                                end_time="14:00",
                                activity="Lunch at Ramen Shop",
                                location="Asakusa",
                                category="dining",
                                item_ref="Ramen Shop"
                            )
                        ],
                        day_summary="Asakusa exploration day"
                    ),
                    ItineraryDay(
                        date="2025-11-11",
                        slots=[
                            ItinerarySlot(
                                start_time="10:00",
                                end_time="15:00",
                                activity="Shibuya shopping",
                                location="Shibuya",
                                category="poi",
                                item_ref="Shibuya Crossing"
                            )
                        ],
                        day_summary="Shopping day in Shibuya"
                    )
                ],
                total_estimated_cost=100.0,
                currency="USD"
            )
            response_data = RouteResponse(itinerary=itinerary)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert len(content['days']) == 2
            assert content['days'][0]['date'] == "2025-11-10"
            assert content['days'][1]['date'] == "2025-11-11"
            assert len(content['days'][0]['slots']) == 2
            assert len(content['days'][1]['slots']) == 1

    def test_parse_response_with_various_categories(self, agent, mock_environment):
        """Test parsing itinerary with different activity categories."""
        with patch.dict(os.environ, mock_environment):
            itinerary = Itinerary(
                days=[
                    ItineraryDay(
                        date="2025-11-10",
                        slots=[
                            ItinerarySlot(
                                start_time="06:00",
                                end_time="08:00",
                                activity="Flight arrival",
                                location="Narita Airport",
                                category="transport",
                                item_ref="ANA 101"
                            ),
                            ItinerarySlot(
                                start_time="10:00",
                                end_time="12:00",
                                activity="Hotel check-in",
                                location="Park Hyatt Tokyo",
                                category="stay",
                                item_ref="Park Hyatt Tokyo"
                            ),
                            ItinerarySlot(
                                start_time="14:00",
                                end_time="16:00",
                                activity="Visit Tokyo Tower",
                                location="Minato",
                                category="poi",
                                item_ref="Tokyo Tower"
                            ),
                            ItinerarySlot(
                                start_time="19:00",
                                end_time="21:00",
                                activity="Dinner at Sukiyabashi Jiro",
                                location="Ginza",
                                category="dining",
                                item_ref="Sukiyabashi Jiro"
                            )
                        ],
                        day_summary="Arrival day with dinner"
                    )
                ],
                total_estimated_cost=800.0,
                currency="USD"
            )
            response_data = RouteResponse(itinerary=itinerary)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            categories = [slot['category'] for slot in content['days'][0]['slots']]
            assert "transport" in categories
            assert "stay" in categories
            assert "poi" in categories
            assert "dining" in categories

    def test_parse_response_preserves_cost_information(self, agent, mock_environment):
        """Test that cost information is preserved in parsed response."""
        with patch.dict(os.environ, mock_environment):
            itinerary = Itinerary(
                days=[
                    ItineraryDay(
                        date="2025-11-10",
                        slots=[
                            ItinerarySlot(
                                start_time="09:00",
                                end_time="12:00",
                                activity="Visit Museum",
                                location="Ueno",
                                category="poi",
                                estimated_cost=20.0,
                                currency="USD"
                            )
                        ]
                    )
                ],
                total_estimated_cost=20.0,
                currency="USD"
            )
            response_data = RouteResponse(itinerary=itinerary)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            content = json.loads(result['content'])
            assert content['total_estimated_cost'] == 20.0
            assert content['currency'] == "USD"
            assert content['days'][0]['slots'][0]['estimated_cost'] == 20.0


class TestRouteResponseModel:
    """Tests for RouteResponse model validation."""

    def test_route_response_with_only_itinerary(self):
        """Test creating RouteResponse with only itinerary."""
        itinerary = Itinerary(days=[])
        response = RouteResponse(itinerary=itinerary)
        assert response.itinerary is not None
        assert response.response is None

    def test_route_response_with_only_response(self):
        """Test creating RouteResponse with only response text."""
        response = RouteResponse(response="Need TripSpec to create itinerary")
        assert response.itinerary is None
        assert response.response == "Need TripSpec to create itinerary"

    def test_route_response_with_both(self):
        """Test creating RouteResponse with both fields."""
        itinerary = Itinerary(days=[])
        response = RouteResponse(
            itinerary=itinerary,
            response="Here is your itinerary"
        )
        assert response.itinerary is not None
        assert response.response is not None

    def test_route_response_rejects_extra_fields(self):
        """Test that RouteResponse rejects extra fields."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RouteResponse(
                itinerary=None,
                response=None,
                extra_field="not allowed"
            )

    def test_route_response_json_serialization(self):
        """Test RouteResponse can be serialized to JSON."""
        itinerary = Itinerary(
            days=[
                ItineraryDay(
                    date="2025-11-10",
                    slots=[
                        ItinerarySlot(
                            start_time="09:00",
                            end_time="12:00",
                            activity="Test Activity",
                            category="poi"
                        )
                    ]
                )
            ],
            total_estimated_cost=50.0,
            currency="USD"
        )
        response = RouteResponse(itinerary=itinerary)
        json_str = response.model_dump_json()
        parsed = json.loads(json_str)
        assert 'itinerary' in parsed
        assert 'response' in parsed


class TestItineraryModel:
    """Tests for Itinerary model validation."""

    def test_itinerary_empty_days(self):
        """Test creating Itinerary with empty days list."""
        itinerary = Itinerary(days=[])
        assert itinerary.days == []
        assert itinerary.total_estimated_cost is None

    def test_itinerary_with_multiple_days(self):
        """Test creating Itinerary with multiple days."""
        itinerary = Itinerary(
            days=[
                ItineraryDay(date="2025-11-10", slots=[]),
                ItineraryDay(date="2025-11-11", slots=[]),
                ItineraryDay(date="2025-11-12", slots=[])
            ],
            total_estimated_cost=500.0,
            currency="USD"
        )
        assert len(itinerary.days) == 3
        assert itinerary.total_estimated_cost == 500.0

    def test_itinerary_day_with_summary(self):
        """Test ItineraryDay with day_summary."""
        day = ItineraryDay(
            date="2025-11-10",
            slots=[],
            day_summary="Relaxing day at the hotel"
        )
        assert day.day_summary == "Relaxing day at the hotel"

    def test_itinerary_slot_minimal_fields(self):
        """Test ItinerarySlot with minimal required fields."""
        slot = ItinerarySlot(
            start_time="09:00",
            end_time="12:00",
            activity="Free exploration",
            category="poi"
        )
        assert slot.location is None
        assert slot.item_ref is None
        assert slot.estimated_cost is None
        assert slot.notes is None

    def test_itinerary_slot_all_fields(self):
        """Test ItinerarySlot with all fields populated."""
        slot = ItinerarySlot(
            start_time="09:00",
            end_time="12:00",
            activity="Visit Tokyo Tower",
            location="Minato",
            category="poi",
            item_ref="Tokyo Tower",
            estimated_cost=15.0,
            currency="USD",
            notes="Get there early to avoid crowds"
        )
        assert slot.start_time == "09:00"
        assert slot.end_time == "12:00"
        assert slot.activity == "Visit Tokyo Tower"
        assert slot.location == "Minato"
        assert slot.category == "poi"
        assert slot.item_ref == "Tokyo Tower"
        assert slot.estimated_cost == 15.0
        assert slot.currency == "USD"
        assert slot.notes == "Get there early to avoid crowds"


class TestAgentNoTools:
    """Tests to verify the agent has no external tools."""

    @pytest.fixture
    def agent(self, mock_environment):
        """Create an agent instance for testing."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.route_agent.agent import AgentFrameworkRouteAgent
            return AgentFrameworkRouteAgent()

    def test_agent_has_no_tools(self, agent, mock_environment):
        """Verify the route agent does not require external tools."""
        with patch.dict(os.environ, mock_environment):
            tools = agent.get_tools()
            assert len(tools) == 0
            assert tools == []

    def test_agent_inherits_from_base(self, mock_environment):
        """Test that agent inherits from BaseAgentFrameworkAgent."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.route_agent.agent import AgentFrameworkRouteAgent
            from src.shared.agents.base_agent import BaseAgentFrameworkAgent

            assert issubclass(AgentFrameworkRouteAgent, BaseAgentFrameworkAgent)
