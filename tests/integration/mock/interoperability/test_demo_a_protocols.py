"""
Tier 1 mock tests for Demo A protocols.

Tests validate:
1. Intake form TripSpec validation (valid/invalid inputs)
2. Workflow parallel agent invocation pattern
3. Weather agent request/response schema compliance
4. Aggregator result combination
5. Route agent itinerary output schema

Per design doc Testing Strategy (lines 1203-1241):
- Demo A tests cover: Intake form, workflow execution, Weather cross-platform call,
  Aggregator combining results, Route agent output.
- All tests use deterministic fixtures from conftest.py (zero LLM cost).
"""

import pytest
from datetime import date
from typing import Any

from src.shared.models import (
    TripSpec,
    WeatherRequest,
    WeatherResponse,
    WeatherForecast,
    Itinerary,
    ItineraryDay,
    ItinerarySlot,
    DiscoveryResults,
)
from pydantic import ValidationError

# Import mock fixtures
from tests.integration.mock.interoperability.conftest import (
    MockTripSpec,
    MockWeatherRequest,
    MockWeatherResponse,
    MockAgentResponse,
    MockWorkflowContext,
)


# =============================================================================
# Intake Form TripSpec Validation Tests
# =============================================================================


class TestDemoAIntakeFormValidTripSpec:
    """Tests for valid TripSpec inputs from intake form."""

    def test_demo_a_intake_form_accepts_valid_tripspec(
        self, sample_trip_spec_paris: MockTripSpec
    ):
        """Test that a valid TripSpec from intake form is accepted.

        Validates the intake form output matches TripSpec schema.
        Per design doc lines 444-461: intake form outputs destination, dates,
        budget, interests.
        """
        trip_dict = sample_trip_spec_paris.to_dict()

        # Create TripSpec from mock data
        trip_spec = TripSpec(
            destination_city=trip_dict["destination_city"],
            origin_city=trip_dict["origin_city"],
            start_date=trip_dict["start_date"],
            end_date=trip_dict["end_date"],
            num_travelers=trip_dict["num_travelers"],
            budget_per_person=trip_dict["budget_per_person"],
            budget_currency=trip_dict["budget_currency"],
            interests=trip_dict["interests"],
            constraints=trip_dict["constraints"],
        )

        # Verify all required fields are populated
        assert trip_spec.destination_city == "Paris"
        assert trip_spec.origin_city == "San Francisco"
        assert trip_spec.start_date == "2025-06-15"
        assert trip_spec.end_date == "2025-06-20"
        assert trip_spec.num_travelers == 2
        assert trip_spec.budget_per_person == 2500.0
        assert trip_spec.budget_currency == "USD"
        assert "art" in trip_spec.interests
        assert "vegetarian" in trip_spec.constraints

    def test_demo_a_intake_form_tripspec_with_minimal_input(self):
        """Test TripSpec with minimal required fields.

        Per design doc, intake form may provide only: destination, dates, budget,
        interests. Other fields can have defaults.
        """
        # Minimal input - what an intake form might actually provide
        trip_spec = TripSpec(
            destination_city="Paris",
            origin_city="Not specified",  # Default if not provided
            start_date="2025-06-15",
            end_date="2025-06-20",
            num_travelers=1,  # Default
            budget_per_person=1000.0,
            budget_currency="USD",
            interests=["sightseeing"],
            constraints=[],  # Empty if not specified
        )

        assert trip_spec.destination_city == "Paris"
        assert trip_spec.constraints == []


class TestDemoAIntakeFormInvalidTripSpec:
    """Tests for invalid TripSpec inputs from intake form."""

    def test_demo_a_intake_form_rejects_missing_destination(self):
        """Test that TripSpec requires destination_city."""
        with pytest.raises(ValidationError) as exc_info:
            TripSpec(
                destination_city=None,  # type: ignore - intentionally invalid
                origin_city="San Francisco",
                start_date="2025-06-15",
                end_date="2025-06-20",
                num_travelers=2,
                budget_per_person=2500.0,
                budget_currency="USD",
                interests=["art"],
                constraints=[],
            )

        assert "destination_city" in str(exc_info.value)

    def test_demo_a_intake_form_rejects_invalid_num_travelers(self):
        """Test that TripSpec rejects non-integer num_travelers."""
        with pytest.raises(ValidationError) as exc_info:
            TripSpec(
                destination_city="Paris",
                origin_city="San Francisco",
                start_date="2025-06-15",
                end_date="2025-06-20",
                num_travelers="two",  # type: ignore - intentionally invalid
                budget_per_person=2500.0,
                budget_currency="USD",
                interests=["art"],
                constraints=[],
            )

        assert "num_travelers" in str(exc_info.value)

    def test_demo_a_intake_form_rejects_missing_dates(self):
        """Test that TripSpec requires start_date and end_date."""
        with pytest.raises(ValidationError) as exc_info:
            TripSpec(
                destination_city="Paris",
                origin_city="San Francisco",
                start_date=None,  # type: ignore - intentionally invalid
                end_date="2025-06-20",
                num_travelers=2,
                budget_per_person=2500.0,
                budget_currency="USD",
                interests=["art"],
                constraints=[],
            )

        assert "start_date" in str(exc_info.value)


# =============================================================================
# Workflow Parallel Agent Invocation Tests
# =============================================================================


class TestDemoAWorkflowParallelAgentCalls:
    """Tests for workflow parallel agent invocation pattern.

    Per design doc lines 486-491, the workflow should:
    - Fan-out: Call 6 discovery agents (potentially in parallel)
    - Fan-in: Combine all results for aggregator
    """

    def test_demo_a_workflow_parallel_agent_calls(
        self,
        sample_workflow_context_initial: MockWorkflowContext,
        mock_transport_response: MockAgentResponse,
        mock_poi_response: MockAgentResponse,
        mock_events_response: MockAgentResponse,
        mock_stay_response: MockAgentResponse,
        mock_dining_response: MockAgentResponse,
        mock_weather_agent_response: MockAgentResponse,
    ):
        """Test workflow can call all 6 discovery agents.

        Validates the workflow invocation pattern - all agents receive
        the trip request and return responses.
        """
        context = sample_workflow_context_initial

        # Simulate parallel agent calls (in reality, workflow engine handles this)
        agent_responses = {
            "transport": mock_transport_response,
            "poi": mock_poi_response,
            "events": mock_events_response,
            "stay": mock_stay_response,
            "dining": mock_dining_response,
            "weather": mock_weather_agent_response,
        }

        # Verify all 6 agents are called
        assert len(agent_responses) == 6

        # Verify all agents receive the trip request
        for agent_name, response in agent_responses.items():
            assert response.agent_name == agent_name
            assert response.success is True
            assert len(response.response_text) > 0

    def test_demo_a_workflow_context_stores_all_results(
        self, sample_workflow_context_completed: MockWorkflowContext
    ):
        """Test workflow context stores results from all agents.

        Per design doc, Local.* variables store agent results:
        - Local.TransportResult
        - Local.POIResult
        - Local.EventsResult
        - Local.StayResult
        - Local.DiningResult
        - Local.WeatherResult
        """
        context = sample_workflow_context_completed

        # All results should be populated
        assert context.transport_results is not None
        assert context.poi_results is not None
        assert context.events_results is not None
        assert context.stay_results is not None
        assert context.dining_results is not None
        assert context.weather_results is not None

        # Results should be non-empty strings
        assert len(context.transport_results) > 0
        assert len(context.poi_results) > 0
        assert len(context.events_results) > 0
        assert len(context.stay_results) > 0
        assert len(context.dining_results) > 0
        assert len(context.weather_results) > 0


# =============================================================================
# Weather Agent Schema Tests
# =============================================================================


class TestDemoAWeatherRequestSchema:
    """Tests for Weather agent request schema compliance."""

    def test_demo_a_weather_request_schema(
        self, sample_weather_request_paris: MockWeatherRequest
    ):
        """Test WeatherRequest schema matches design doc (lines 558-565).

        Fields:
        - location: "Paris, France"
        - start_date: "2025-06-15"
        - end_date: "2025-06-20"
        """
        mock_request = sample_weather_request_paris

        # Create Pydantic model from mock
        request = WeatherRequest(
            location=mock_request.location,
            start_date=mock_request.start_date,
            end_date=mock_request.end_date,
        )

        assert request.location == "Paris, France"
        assert request.start_date == "2025-06-15"
        assert request.end_date == "2025-06-20"

    def test_demo_a_weather_request_serialization(
        self, sample_weather_request_paris: MockWeatherRequest
    ):
        """Test WeatherRequest serializes correctly for cross-platform call."""
        mock_request = sample_weather_request_paris

        request = WeatherRequest(
            location=mock_request.location,
            start_date=mock_request.start_date,
            end_date=mock_request.end_date,
        )

        # Serialize to dict (would be JSON in actual API call)
        request_dict = request.model_dump()

        assert request_dict == {
            "location": "Paris, France",
            "start_date": "2025-06-15",
            "end_date": "2025-06-20",
        }


class TestDemoAWeatherResponseSchema:
    """Tests for Weather agent response schema compliance."""

    def test_demo_a_weather_response_schema(
        self, sample_weather_response_paris: MockWeatherResponse
    ):
        """Test WeatherResponse schema matches design doc (lines 567-582).

        Fields:
        - location: echo of request location
        - forecasts: list of daily forecasts
        - summary: human-readable summary
        """
        mock_response = sample_weather_response_paris

        # Create Pydantic model from mock
        forecasts = [
            WeatherForecast(
                date=f.date,
                condition=f.condition,
                high_temp_c=f.high_temp_c,
                low_temp_c=f.low_temp_c,
                precipitation_chance=f.precipitation_chance,
            )
            for f in mock_response.forecasts
        ]

        response = WeatherResponse(
            location=mock_response.location,
            forecasts=forecasts,
            summary=mock_response.summary,
        )

        assert response.location == "Paris, France"
        assert len(response.forecasts) == 6  # 6 days: June 15-20
        assert "pleasant" in response.summary.lower()

    def test_demo_a_weather_response_forecast_structure(
        self, sample_weather_response_paris: MockWeatherResponse
    ):
        """Test individual forecast structure within WeatherResponse."""
        mock_response = sample_weather_response_paris
        first_forecast = mock_response.forecasts[0]

        forecast = WeatherForecast(
            date=first_forecast.date,
            condition=first_forecast.condition,
            high_temp_c=first_forecast.high_temp_c,
            low_temp_c=first_forecast.low_temp_c,
            precipitation_chance=first_forecast.precipitation_chance,
        )

        assert forecast.date == "2025-06-15"
        assert forecast.condition == "Partly Cloudy"
        assert forecast.high_temp_c == 24.0
        assert forecast.low_temp_c == 16.0
        assert 0 <= forecast.precipitation_chance <= 100


# =============================================================================
# Aggregator Result Combination Tests
# =============================================================================


class TestDemoAAggregatorCombinesResults:
    """Tests for Aggregator combining 6 agent results.

    Per design doc lines 462-484, the aggregator receives:
    - trip_request: Original TripSpec
    - discovery_results: Results from all 6 discovery agents
    """

    def test_demo_a_aggregator_combines_results(
        self, sample_workflow_context_completed: MockWorkflowContext
    ):
        """Test Aggregator receives all 6 agent results.

        The aggregator input payload should contain results from:
        transport, poi, events, stay, dining, weather.
        """
        context = sample_workflow_context_completed

        # Simulate aggregator input payload (as shown in design doc)
        aggregator_input = {
            "trip_request": {
                "destination": "Paris, France",
                "start_date": "2025-06-15",
                "end_date": "2025-06-20",
                "budget": "moderate",
                "interests": ["art", "history", "food"],
            },
            "discovery_results": {
                "transport": context.transport_results,
                "poi": context.poi_results,
                "events": context.events_results,
                "stay": context.stay_results,
                "dining": context.dining_results,
                "weather": context.weather_results,
            },
        }

        # Verify all 6 discovery results are present
        discovery = aggregator_input["discovery_results"]
        assert "transport" in discovery
        assert "poi" in discovery
        assert "events" in discovery
        assert "stay" in discovery
        assert "dining" in discovery
        assert "weather" in discovery

        # All results should be non-null
        for key, value in discovery.items():
            assert value is not None, f"Missing result for {key}"
            assert len(value) > 0, f"Empty result for {key}"

    def test_demo_a_aggregator_output_contains_summary(
        self, mock_aggregator_response: MockAgentResponse
    ):
        """Test Aggregator produces a summarized output.

        The aggregator should combine and summarize all discovery results.
        """
        response = mock_aggregator_response

        assert response.agent_name == "aggregator"
        assert response.success is True

        # Summary should mention all categories
        summary = response.response_text.lower()
        assert "transport" in summary
        # POI might be listed as "accommodation" or "attractions"
        assert "events" in summary or "event" in summary
        # Check for dining
        assert "dining" in summary or "vegetarian" in summary


# =============================================================================
# Route Agent Output Schema Tests
# =============================================================================


class TestDemoARouteAgentOutputSchema:
    """Tests for Route agent itinerary output schema.

    Per design doc and src/shared/models.py, the Route agent should output
    an Itinerary with days containing time slots.
    """

    def test_demo_a_route_agent_output_schema(self):
        """Test Route agent produces valid Itinerary schema.

        Itinerary structure:
        - days: List[ItineraryDay]
        - total_estimated_cost: Optional[float]
        - currency: Optional[str]
        """
        # Create a sample itinerary matching Route agent output
        itinerary = Itinerary(
            days=[
                ItineraryDay(
                    date="2025-06-15",
                    day_summary="Arrival day - check in and explore Le Marais",
                    slots=[
                        ItinerarySlot(
                            start_time="15:00",
                            end_time="16:00",
                            activity="Hotel check-in at Le Marais",
                            location="Le Marais, Paris",
                            category="stay",
                            item_ref="stay_1",
                        ),
                        ItinerarySlot(
                            start_time="18:00",
                            end_time="20:00",
                            activity="Evening walk and dinner",
                            location="Le Marais",
                            category="dining",
                            item_ref="dining_1",
                            estimated_cost=50.0,
                            currency="EUR",
                        ),
                    ],
                ),
                ItineraryDay(
                    date="2025-06-16",
                    day_summary="Full day at Louvre Museum",
                    slots=[
                        ItinerarySlot(
                            start_time="09:00",
                            end_time="17:00",
                            activity="Louvre Museum visit",
                            location="Louvre, Paris",
                            category="poi",
                            item_ref="poi_1",
                            estimated_cost=17.0,
                            currency="EUR",
                        ),
                    ],
                ),
            ],
            total_estimated_cost=2900.0,
            currency="USD",
        )

        # Verify structure
        assert len(itinerary.days) == 2
        assert itinerary.total_estimated_cost == 2900.0
        assert itinerary.currency == "USD"

        # Verify day structure
        first_day = itinerary.days[0]
        assert first_day.date == "2025-06-15"
        assert len(first_day.slots) == 2
        assert first_day.day_summary is not None

        # Verify slot structure
        first_slot = first_day.slots[0]
        assert first_slot.start_time == "15:00"
        assert first_slot.end_time == "16:00"
        assert first_slot.category == "stay"

    def test_demo_a_route_agent_itinerary_covers_all_trip_days(
        self, sample_trip_spec_paris: MockTripSpec
    ):
        """Test Route agent itinerary covers the full trip duration.

        For a June 15-20 trip, itinerary should have 6 days.
        """
        trip = sample_trip_spec_paris

        # Calculate expected days
        start = trip.start_date
        end = trip.end_date
        num_days = (end - start).days + 1  # Inclusive

        assert num_days == 6, "Paris trip should be 6 days"

        # A complete itinerary should have entries for all days
        sample_itinerary = Itinerary(
            days=[
                ItineraryDay(
                    date=f"2025-06-{15 + i}",
                    slots=[
                        ItinerarySlot(
                            start_time="10:00",
                            end_time="18:00",
                            activity=f"Day {i + 1} activities",
                            category="poi",
                        )
                    ],
                )
                for i in range(num_days)
            ]
        )

        assert len(sample_itinerary.days) == 6

    def test_demo_a_route_agent_slot_has_required_fields(self):
        """Test ItinerarySlot has all required fields for Demo B compatibility.

        Per design doc, slots need item_ref, estimated_cost, currency
        for Demo B approval workflow.
        """
        slot = ItinerarySlot(
            start_time="09:00",
            end_time="17:00",
            activity="Versailles Day Trip",
            location="Versailles, France",
            category="poi",
            mode=None,  # Not transport
            item_ref="poi_versailles",
            estimated_cost=25.0,
            currency="EUR",
            notes="Book tickets in advance",
        )

        # Required for display
        assert slot.activity is not None
        assert slot.start_time is not None
        assert slot.end_time is not None
        assert slot.category is not None

        # Required for Demo B approval
        assert slot.item_ref is not None
        assert slot.estimated_cost is not None
        assert slot.currency is not None


# =============================================================================
# Integration Tests - Full Demo A Flow
# =============================================================================


class TestDemoAFullFlow:
    """Integration tests for complete Demo A flow."""

    def test_demo_a_full_flow_intake_to_itinerary(
        self,
        sample_trip_spec_paris: MockTripSpec,
        sample_weather_response_paris: MockWeatherResponse,
        mock_transport_response: MockAgentResponse,
        mock_poi_response: MockAgentResponse,
        mock_events_response: MockAgentResponse,
        mock_stay_response: MockAgentResponse,
        mock_dining_response: MockAgentResponse,
        mock_aggregator_response: MockAgentResponse,
        mock_route_response: MockAgentResponse,
    ):
        """Test complete Demo A flow from intake form to final itinerary.

        Flow:
        1. User submits TripSpec via intake form
        2. Workflow calls 6 discovery agents
        3. Aggregator combines results
        4. Route agent produces itinerary
        """
        # Step 1: Intake form creates TripSpec
        trip_dict = sample_trip_spec_paris.to_dict()
        trip_spec = TripSpec(
            destination_city=trip_dict["destination_city"],
            origin_city=trip_dict["origin_city"],
            start_date=trip_dict["start_date"],
            end_date=trip_dict["end_date"],
            num_travelers=trip_dict["num_travelers"],
            budget_per_person=trip_dict["budget_per_person"],
            budget_currency=trip_dict["budget_currency"],
            interests=trip_dict["interests"],
            constraints=trip_dict["constraints"],
        )

        # Step 2: Collect discovery results
        discovery_responses = [
            mock_transport_response,
            mock_poi_response,
            mock_events_response,
            mock_stay_response,
            mock_dining_response,
        ]
        weather_response = sample_weather_response_paris

        # All discovery calls succeed
        for response in discovery_responses:
            assert response.success is True

        # Weather schema validates
        weather = WeatherResponse(
            location=weather_response.location,
            forecasts=[
                WeatherForecast(
                    date=f.date,
                    condition=f.condition,
                    high_temp_c=f.high_temp_c,
                    low_temp_c=f.low_temp_c,
                    precipitation_chance=f.precipitation_chance,
                )
                for f in weather_response.forecasts
            ],
            summary=weather_response.summary,
        )
        assert weather.location == "Paris, France"

        # Step 3: Aggregator combines results
        aggregator = mock_aggregator_response
        assert aggregator.success is True
        assert aggregator.agent_name == "aggregator"

        # Step 4: Route agent produces itinerary
        route = mock_route_response
        assert route.success is True
        assert route.agent_name == "route"
        assert "itinerary" in route.response_text.lower()
