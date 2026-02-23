"""
Shared pytest fixtures for Tier 1 mock tests (cross-platform interoperability).

Per design doc Testing Strategy (lines 1203-1241), these fixtures provide:
- Deterministic test data (no randomness)
- Consistent data across Demo A/B/C tests
- Zero LLM cost testing

Fixture Categories:
1. TripSpec fixtures - Sample trip specifications
2. Weather fixtures - WeatherRequest/WeatherResponse samples (stub until INTEROP-010A)
3. Agent response fixtures - Mock responses from Foundry and Copilot Studio agents
4. Workflow fixtures - Declarative workflow inputs/outputs
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pytest


# =============================================================================
# TripSpec Fixtures
# =============================================================================


@dataclass
class MockTripSpec:
    """
    Deterministic TripSpec for testing.

    Matches the TripSpec dataclass from src/orchestrator/models/trip_spec.py:
    - destination_city, origin_city, start_date, end_date
    - num_travelers, budget_per_person, budget_currency
    - interests, constraints, special_requests
    """
    destination_city: str
    origin_city: str
    start_date: date
    end_date: date
    num_travelers: int
    budget_per_person: float
    budget_currency: str
    interests: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    special_requests: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary (matches TripSpec.to_dict())."""
        return {
            "destination_city": self.destination_city,
            "origin_city": self.origin_city,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "num_travelers": self.num_travelers,
            "budget_per_person": self.budget_per_person,
            "budget_currency": self.budget_currency,
            "interests": self.interests,
            "constraints": self.constraints,
            "special_requests": self.special_requests,
        }


@pytest.fixture
def sample_trip_spec_paris() -> MockTripSpec:
    """
    Sample TripSpec for Paris trip.

    Deterministic fixture for Demo A workflow testing.
    """
    return MockTripSpec(
        destination_city="Paris",
        origin_city="San Francisco",
        start_date=date(2025, 6, 15),
        end_date=date(2025, 6, 20),
        num_travelers=2,
        budget_per_person=2500.0,
        budget_currency="USD",
        interests=["art", "history", "food"],
        constraints=["vegetarian"],
        special_requests=None,
    )


@pytest.fixture
def sample_trip_spec_tokyo() -> MockTripSpec:
    """
    Sample TripSpec for Tokyo trip.

    Deterministic fixture with different values for variety.
    """
    return MockTripSpec(
        destination_city="Tokyo",
        origin_city="Seattle",
        start_date=date(2025, 7, 1),
        end_date=date(2025, 7, 10),
        num_travelers=1,
        budget_per_person=3000.0,
        budget_currency="USD",
        interests=["technology", "anime", "sushi"],
        constraints=["wheelchair accessible"],
        special_requests="Would like to visit Akihabara",
    )


@pytest.fixture
def sample_trip_spec_london() -> MockTripSpec:
    """
    Sample TripSpec for London trip.

    Used for Demo C testing (concerts/events).
    """
    return MockTripSpec(
        destination_city="London",
        origin_city="New York",
        start_date=date(2025, 8, 5),
        end_date=date(2025, 8, 12),
        num_travelers=4,
        budget_per_person=2000.0,
        budget_currency="GBP",
        interests=["music", "theater", "history"],
        constraints=[],
        special_requests=None,
    )


# =============================================================================
# Weather Fixtures (Stub - will be updated by INTEROP-010A)
# =============================================================================


@dataclass
class MockWeatherForecast:
    """
    Single day weather forecast.

    Matches WeatherForecast from design doc lines 567-580:
    - date: YYYY-MM-DD
    - condition: e.g., "Partly Cloudy"
    - high_temp_c, low_temp_c: temperatures
    - precipitation_chance: 0-100
    """
    date: str
    condition: str
    high_temp_c: float
    low_temp_c: float
    precipitation_chance: int


@dataclass
class MockWeatherRequest:
    """
    Weather request schema.

    Matches design doc lines 558-565:
    - location: "Paris, France"
    - start_date: "2025-06-15"
    - end_date: "2025-06-20"
    """
    location: str
    start_date: str
    end_date: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "location": self.location,
            "start_date": self.start_date,
            "end_date": self.end_date,
        }


@dataclass
class MockWeatherResponse:
    """
    Weather response schema.

    Matches design doc lines 567-582:
    - location: echo of request location
    - forecasts: list of daily forecasts
    - summary: human-readable summary
    """
    location: str
    forecasts: list[MockWeatherForecast]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "location": self.location,
            "forecasts": [
                {
                    "date": f.date,
                    "condition": f.condition,
                    "high_temp_c": f.high_temp_c,
                    "low_temp_c": f.low_temp_c,
                    "precipitation_chance": f.precipitation_chance,
                }
                for f in self.forecasts
            ],
            "summary": self.summary,
        }


@pytest.fixture
def sample_weather_request_paris() -> MockWeatherRequest:
    """
    Weather request for Paris trip dates.

    Matches sample_trip_spec_paris dates.
    """
    return MockWeatherRequest(
        location="Paris, France",
        start_date="2025-06-15",
        end_date="2025-06-20",
    )


@pytest.fixture
def sample_weather_response_paris() -> MockWeatherResponse:
    """
    Weather response for Paris.

    Deterministic forecast data matching design doc example.
    """
    return MockWeatherResponse(
        location="Paris, France",
        forecasts=[
            MockWeatherForecast(
                date="2025-06-15",
                condition="Partly Cloudy",
                high_temp_c=24.0,
                low_temp_c=16.0,
                precipitation_chance=20,
            ),
            MockWeatherForecast(
                date="2025-06-16",
                condition="Sunny",
                high_temp_c=26.0,
                low_temp_c=17.0,
                precipitation_chance=10,
            ),
            MockWeatherForecast(
                date="2025-06-17",
                condition="Partly Cloudy",
                high_temp_c=25.0,
                low_temp_c=16.0,
                precipitation_chance=15,
            ),
            MockWeatherForecast(
                date="2025-06-18",
                condition="Light Rain",
                high_temp_c=22.0,
                low_temp_c=15.0,
                precipitation_chance=60,
            ),
            MockWeatherForecast(
                date="2025-06-19",
                condition="Cloudy",
                high_temp_c=21.0,
                low_temp_c=14.0,
                precipitation_chance=40,
            ),
            MockWeatherForecast(
                date="2025-06-20",
                condition="Sunny",
                high_temp_c=27.0,
                low_temp_c=18.0,
                precipitation_chance=5,
            ),
        ],
        summary="Generally pleasant weather with mild temperatures. Brief rain expected mid-week.",
    )


@pytest.fixture
def sample_weather_request_tokyo() -> MockWeatherRequest:
    """Weather request for Tokyo trip dates."""
    return MockWeatherRequest(
        location="Tokyo, Japan",
        start_date="2025-07-01",
        end_date="2025-07-10",
    )


@pytest.fixture
def sample_weather_response_tokyo() -> MockWeatherResponse:
    """Weather response for Tokyo (summer, rainy season)."""
    return MockWeatherResponse(
        location="Tokyo, Japan",
        forecasts=[
            MockWeatherForecast(
                date="2025-07-01",
                condition="Rainy",
                high_temp_c=28.0,
                low_temp_c=23.0,
                precipitation_chance=80,
            ),
            MockWeatherForecast(
                date="2025-07-02",
                condition="Thunderstorm",
                high_temp_c=27.0,
                low_temp_c=22.0,
                precipitation_chance=90,
            ),
            MockWeatherForecast(
                date="2025-07-03",
                condition="Cloudy",
                high_temp_c=29.0,
                low_temp_c=24.0,
                precipitation_chance=50,
            ),
        ],
        summary="Rainy season in Tokyo. Expect frequent showers and high humidity.",
    )


# =============================================================================
# Mock Agent Responses - Foundry Agents
# =============================================================================


@dataclass
class MockAgentResponse:
    """
    Generic mock response from a Foundry or Copilot Studio agent.

    Used for testing agent invocation patterns.
    """
    agent_name: str
    response_text: str
    success: bool = True
    error_message: str | None = None


@pytest.fixture
def mock_transport_response() -> MockAgentResponse:
    """
    Mock Transport agent response.

    Sample response for Demo A workflow testing.
    """
    return MockAgentResponse(
        agent_name="transport",
        response_text=(
            "Found several flight options from San Francisco to Paris:\n"
            "1. Air France AF83 - $850 direct (11h 20m)\n"
            "2. United UA990 via London - $720 (14h 30m)\n"
            "3. Delta DL8551 via Atlanta - $680 (16h 45m)\n"
            "Local transport: Paris Metro day pass recommended (~15 EUR/day)"
        ),
        success=True,
    )


@pytest.fixture
def mock_poi_response() -> MockAgentResponse:
    """Mock POI agent response."""
    return MockAgentResponse(
        agent_name="poi",
        response_text=(
            "Top attractions in Paris for art and history enthusiasts:\n"
            "1. Louvre Museum - World's largest art museum\n"
            "2. Musee d'Orsay - Impressionist masterpieces\n"
            "3. Palace of Versailles - Historic royal residence\n"
            "4. Eiffel Tower - Iconic landmark with city views\n"
            "5. Notre-Dame Cathedral - Gothic architecture (exterior view during reconstruction)"
        ),
        success=True,
    )


@pytest.fixture
def mock_events_response() -> MockAgentResponse:
    """Mock Events agent response."""
    return MockAgentResponse(
        agent_name="events",
        response_text=(
            "Events in Paris June 15-20, 2025:\n"
            "1. Paris Jazz Festival - Parc Floral (June 15-16)\n"
            "2. Fete de la Musique - Citywide free concerts (June 21, but festivities start early)\n"
            "3. Bastille Day preparations - Various exhibitions\n"
            "4. Opera Garnier - Carmen performance (June 18)"
        ),
        success=True,
    )


@pytest.fixture
def mock_stay_response() -> MockAgentResponse:
    """Mock Stay agent response."""
    return MockAgentResponse(
        agent_name="stay",
        response_text=(
            "Recommended neighborhoods and hotels in Paris:\n"
            "Neighborhoods: Le Marais (trendy, central), Saint-Germain (historic, artistic)\n"
            "Hotels:\n"
            "1. Hotel Le Marais - $180/night, 4-star, central location\n"
            "2. Hotel Saint-Germain - $220/night, boutique, near museums\n"
            "3. Ibis Styles Republique - $120/night, budget-friendly"
        ),
        success=True,
    )


@pytest.fixture
def mock_dining_response() -> MockAgentResponse:
    """Mock Dining agent response."""
    return MockAgentResponse(
        agent_name="dining",
        response_text=(
            "Vegetarian-friendly restaurants in Paris:\n"
            "1. Le Grenier de Notre-Dame - Vegetarian French cuisine\n"
            "2. Wild & The Moon - Organic plant-based\n"
            "3. Cafe Pinson - Vegan brunch spot\n"
            "4. L'Arpege - Michelin 3-star, famous vegetable menu"
        ),
        success=True,
    )


@pytest.fixture
def mock_aggregator_response() -> MockAgentResponse:
    """Mock Aggregator agent response."""
    return MockAgentResponse(
        agent_name="aggregator",
        response_text=(
            "Aggregated discovery results for Paris trip:\n"
            "- Transport: 3 flight options, local metro recommended\n"
            "- Accommodation: 3 hotels in recommended areas\n"
            "- Attractions: 5 POIs matching art/history interests\n"
            "- Events: 4 relevant events during trip dates\n"
            "- Dining: 4 vegetarian-friendly options\n"
            "Weather: Generally pleasant, pack for one rainy day."
        ),
        success=True,
    )


@pytest.fixture
def mock_route_response() -> MockAgentResponse:
    """Mock Route agent response with itinerary."""
    return MockAgentResponse(
        agent_name="route",
        response_text=(
            "Proposed 6-day Paris itinerary:\n"
            "Day 1 (Jun 15): Arrive, check in Le Marais, evening walk\n"
            "Day 2 (Jun 16): Louvre Museum, lunch at Wild & The Moon\n"
            "Day 3 (Jun 17): Musee d'Orsay, Saint-Germain exploration\n"
            "Day 4 (Jun 18): Day trip to Versailles\n"
            "Day 5 (Jun 19): Eiffel Tower, Seine cruise, Opera Carmen\n"
            "Day 6 (Jun 20): Notre-Dame, Le Marais shopping, departure"
        ),
        success=True,
    )


# =============================================================================
# Mock Agent Responses - Copilot Studio Agents
# =============================================================================


@pytest.fixture
def mock_weather_agent_response() -> MockAgentResponse:
    """Mock Weather agent response (Copilot Studio)."""
    return MockAgentResponse(
        agent_name="weather",
        response_text=(
            "Weather forecast for Paris, June 15-20:\n"
            "Generally pleasant with temperatures 21-27C.\n"
            "Expect some rain on June 18.\n"
            "Pack layers and a light rain jacket."
        ),
        success=True,
    )


@pytest.fixture
def mock_approval_approve_response() -> MockAgentResponse:
    """Mock Approval agent response - itinerary approved."""
    return MockAgentResponse(
        agent_name="approval",
        response_text=(
            "The itinerary has been reviewed and APPROVED.\n"
            "All items within budget. Booking can proceed."
        ),
        success=True,
    )


@pytest.fixture
def mock_approval_reject_response() -> MockAgentResponse:
    """Mock Approval agent response - itinerary rejected."""
    return MockAgentResponse(
        agent_name="approval",
        response_text=(
            "The itinerary has been REJECTED.\n"
            "Reason: Day 4 Versailles day trip exceeds daily budget allocation.\n"
            "Suggestion: Consider a half-day trip or alternative activity."
        ),
        success=True,
    )


@pytest.fixture
def mock_approval_modify_response() -> MockAgentResponse:
    """Mock Approval agent response - modifications requested."""
    return MockAgentResponse(
        agent_name="approval",
        response_text=(
            "The itinerary requires MODIFICATIONS:\n"
            "1. Day 2: Replace 3-star restaurant with more affordable option\n"
            "2. Day 5: Opera tickets ($150) need approval for special event budget\n"
            "Please update and resubmit."
        ),
        success=True,
    )


@pytest.fixture
def mock_travel_planning_parent_response() -> MockAgentResponse:
    """Mock Q&A Parent agent response (Demo C)."""
    return MockAgentResponse(
        agent_name="travel_planning_parent",
        response_text=(
            "Based on your question about London concerts:\n"
            "I found several upcoming events via the Events agent:\n"
            "1. Coldplay at Wembley Stadium - Aug 8\n"
            "2. Ed Sheeran at The O2 - Aug 10\n"
            "3. London Symphony Orchestra - Aug 7\n"
            "Would you like more details on any of these?"
        ),
        success=True,
    )


# =============================================================================
# Error Response Fixtures
# =============================================================================


@pytest.fixture
def mock_agent_error_response() -> MockAgentResponse:
    """Mock agent error response for failure testing."""
    return MockAgentResponse(
        agent_name="transport",
        response_text="",
        success=False,
        error_message="Failed to connect to Bing search. Please try again later.",
    )


@pytest.fixture
def mock_agent_timeout_response() -> MockAgentResponse:
    """Mock agent timeout response."""
    return MockAgentResponse(
        agent_name="poi",
        response_text="",
        success=False,
        error_message="Request timed out after 30 seconds.",
    )


# =============================================================================
# Workflow Fixtures
# =============================================================================


@dataclass
class MockWorkflowContext:
    """
    Context for declarative workflow testing.

    Represents the Local.* variables in Foundry declarative workflows.
    """
    trip_request_msg: str
    transport_results: str | None = None
    poi_results: str | None = None
    events_results: str | None = None
    stay_results: str | None = None
    dining_results: str | None = None
    weather_results: str | None = None
    aggregated_result: str | None = None
    final_itinerary: str | None = None


@pytest.fixture
def sample_workflow_context_initial(sample_trip_spec_paris: MockTripSpec) -> MockWorkflowContext:
    """Initial workflow context with only trip request."""
    trip_spec = sample_trip_spec_paris.to_dict()
    return MockWorkflowContext(
        trip_request_msg=(
            f"Plan a trip to {trip_spec['destination_city']} "
            f"from {trip_spec['origin_city']}, "
            f"{trip_spec['start_date']} to {trip_spec['end_date']}, "
            f"{trip_spec['num_travelers']} travelers, "
            f"budget {trip_spec['budget_per_person']} {trip_spec['budget_currency']}/person. "
            f"Interests: {', '.join(trip_spec['interests'])}. "
            f"Constraints: {', '.join(trip_spec['constraints'])}."
        )
    )


@pytest.fixture
def sample_workflow_context_completed(
    sample_trip_spec_paris: MockTripSpec,
    mock_transport_response: MockAgentResponse,
    mock_poi_response: MockAgentResponse,
    mock_events_response: MockAgentResponse,
    mock_stay_response: MockAgentResponse,
    mock_dining_response: MockAgentResponse,
    mock_weather_agent_response: MockAgentResponse,
    mock_aggregator_response: MockAgentResponse,
    mock_route_response: MockAgentResponse,
) -> MockWorkflowContext:
    """Completed workflow context with all agent results."""
    trip_spec = sample_trip_spec_paris.to_dict()
    return MockWorkflowContext(
        trip_request_msg=(
            f"Plan a trip to {trip_spec['destination_city']} "
            f"from {trip_spec['origin_city']}, "
            f"{trip_spec['start_date']} to {trip_spec['end_date']}, "
            f"{trip_spec['num_travelers']} travelers, "
            f"budget {trip_spec['budget_per_person']} {trip_spec['budget_currency']}/person. "
            f"Interests: {', '.join(trip_spec['interests'])}. "
            f"Constraints: {', '.join(trip_spec['constraints'])}."
        ),
        transport_results=mock_transport_response.response_text,
        poi_results=mock_poi_response.response_text,
        events_results=mock_events_response.response_text,
        stay_results=mock_stay_response.response_text,
        dining_results=mock_dining_response.response_text,
        weather_results=mock_weather_agent_response.response_text,
        aggregated_result=mock_aggregator_response.response_text,
        final_itinerary=mock_route_response.response_text,
    )


# =============================================================================
# Demo B - Approval Workflow Fixtures
# =============================================================================


@dataclass
class MockItineraryItem:
    """Single item in an itinerary for approval."""
    item_ref: str
    activity: str
    estimated_cost: float
    currency: str
    day_summary: str


@dataclass
class MockApprovalRequest:
    """Request to Approval agent."""
    itinerary_summary: str
    items: list[MockItineraryItem]
    total_cost: float
    currency: str


@pytest.fixture
def sample_approval_request() -> MockApprovalRequest:
    """Sample approval request for Demo B testing."""
    return MockApprovalRequest(
        itinerary_summary="6-day Paris trip for 2 travelers",
        items=[
            MockItineraryItem(
                item_ref="transport_1",
                activity="Air France flight SFO-CDG",
                estimated_cost=1700.0,
                currency="USD",
                day_summary="Day 1: Arrival",
            ),
            MockItineraryItem(
                item_ref="stay_1",
                activity="Hotel Le Marais (5 nights)",
                estimated_cost=900.0,
                currency="USD",
                day_summary="Days 1-6: Accommodation",
            ),
            MockItineraryItem(
                item_ref="event_1",
                activity="Opera Carmen tickets x2",
                estimated_cost=300.0,
                currency="USD",
                day_summary="Day 5: Evening event",
            ),
        ],
        total_cost=2900.0,
        currency="USD",
    )


# =============================================================================
# Demo C - Q&A Routing Fixtures
# =============================================================================


@dataclass
class MockQAQuery:
    """Q&A query for routing tests."""
    query: str
    expected_agents: list[str]
    expected_response_type: str  # "single_agent", "multi_agent", "internal"


@pytest.fixture
def sample_qa_queries() -> list[MockQAQuery]:
    """Sample Q&A queries for Demo C routing tests."""
    return [
        MockQAQuery(
            query="What concerts are happening in London next week?",
            expected_agents=["events"],
            expected_response_type="single_agent",
        ),
        MockQAQuery(
            query="What's the weather like in Paris and what are the top attractions?",
            expected_agents=["weather", "poi"],
            expected_response_type="multi_agent",
        ),
        MockQAQuery(
            query="What's the weather forecast for Tokyo?",
            expected_agents=["weather"],
            expected_response_type="internal",  # Weather is a CS agent
        ),
        MockQAQuery(
            query="Find me a flight from Seattle to Tokyo",
            expected_agents=["transport"],
            expected_response_type="single_agent",
        ),
        MockQAQuery(
            query="I need a hotel and restaurant recommendations for London",
            expected_agents=["stay", "dining"],
            expected_response_type="multi_agent",
        ),
    ]


# =============================================================================
# Utility Fixtures
# =============================================================================


@pytest.fixture
def deterministic_date_2025_06_15() -> date:
    """Fixed date for deterministic testing."""
    return date(2025, 6, 15)


@pytest.fixture
def deterministic_date_2025_07_01() -> date:
    """Fixed date for deterministic testing."""
    return date(2025, 7, 1)


@pytest.fixture
def deterministic_date_2025_08_05() -> date:
    """Fixed date for deterministic testing."""
    return date(2025, 8, 5)
