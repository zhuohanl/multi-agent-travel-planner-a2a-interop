"""
Unit tests for RouteAgent.

Tests the Route agent which creates day-by-day itineraries based on
aggregated discovery results, budget plan, and trip requirements.

Per ORCH-078 acceptance criteria:
- RouteAgent.plan() produces day-by-day itinerary
- Missing transport uses 'Arrival: User to arrange' placeholders
- Missing stay is treated as blocker (raises error)
- Missing POI results in 'Free time' blocks
- Itinerary includes time slots for each activity
- All unit tests pass
"""

from __future__ import annotations

from datetime import date as date_type, datetime, time, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator.handlers.discovery import (
    AgentDiscoveryResult,
    DiscoveryResults,
)
from src.orchestrator.planning.agents.aggregator import (
    AggregatedResults,
    AgentResultEntry,
)
from src.orchestrator.planning.agents.budget import (
    BudgetPlan,
    CategoryAllocation,
)
from src.orchestrator.planning.agents.route import (
    DEFAULT_ARRIVAL_TIME,
    DEFAULT_DEPARTURE_TIME,
    ItineraryAccommodation,
    ItineraryActivity,
    ItineraryDay,
    ItineraryMeal,
    ItineraryTransport,
    RouteAgent,
    RoutePlan,
    RoutePlanningError,
    TimeSlot,
)
from src.orchestrator.planning.pipeline import (
    DiscoveryContext,
    DiscoveryGap,
    DiscoveryStatus,
)


def _slots_overlap(
    start_a: time | None,
    end_a: time | None,
    start_b: time | None,
    end_b: time | None,
) -> bool:
    a_start = start_a or time.min
    a_end = end_a or time.max
    b_start = start_b or time.min
    b_end = end_b or time.max
    return a_start < b_end and b_start < a_end


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def full_aggregated_results() -> AggregatedResults:
    """Create complete successful aggregated results."""
    return AggregatedResults(
        transport=AgentResultEntry(
            status="SUCCESS",
            data={
                "flights": [
                    {"airline": "JAL", "price": 1200, "departure": "09:00", "arrival": "14:00"},
                    {"airline": "ANA", "price": 1100, "departure": "14:00", "arrival": "19:00"},
                ],
            },
        ),
        stay=AgentResultEntry(
            status="SUCCESS",
            data={
                "hotels": [
                    {
                        "name": "Park Hyatt Tokyo",
                        "price_per_night": 500,
                        "rating": 4.8,
                        "location": "Shinjuku",
                    },
                    {
                        "name": "Keio Plaza",
                        "price_per_night": 300,
                        "rating": 4.2,
                        "location": "Shinjuku",
                    },
                ],
            },
        ),
        poi=AgentResultEntry(
            status="SUCCESS",
            data={
                "attractions": [
                    {"name": "Tokyo Tower", "category": "landmark", "location": "Minato"},
                    {"name": "Senso-ji Temple", "category": "temple", "location": "Asakusa"},
                    {"name": "Meiji Shrine", "category": "shrine", "location": "Shibuya"},
                ],
            },
        ),
        events=AgentResultEntry(
            status="SUCCESS",
            data={
                "events": [
                    {"name": "Cherry Blossom Festival", "date": "2026-03-15", "venue": "Ueno Park"},
                ],
            },
        ),
        dining=AgentResultEntry(
            status="SUCCESS",
            data={
                "restaurants": [
                    {"name": "Sukiyabashi Jiro", "cuisine": "sushi", "rating": 4.9, "location": "Ginza"},
                    {"name": "Gonpachi", "cuisine": "izakaya", "rating": 4.5, "location": "Shibuya"},
                ],
            },
        ),
        destination="Tokyo",
    )


@pytest.fixture
def aggregated_missing_transport() -> AggregatedResults:
    """Create aggregated results with missing transport."""
    return AggregatedResults(
        transport=AgentResultEntry(
            status="TIMEOUT",
            data=None,
            message="Timeout after 30s",
        ),
        stay=AgentResultEntry(
            status="SUCCESS",
            data={
                "hotels": [
                    {"name": "Park Hyatt Tokyo", "price_per_night": 500},
                ],
            },
        ),
        poi=AgentResultEntry(
            status="SUCCESS",
            data={
                "attractions": [
                    {"name": "Tokyo Tower"},
                ],
            },
        ),
        events=AgentResultEntry(
            status="SUCCESS",
            data={
                "events": [],
            },
        ),
        dining=AgentResultEntry(
            status="SUCCESS",
            data={
                "restaurants": [
                    {"name": "Sukiyabashi Jiro"},
                ],
            },
        ),
        destination="Tokyo",
    )


@pytest.fixture
def aggregated_missing_stay() -> AggregatedResults:
    """Create aggregated results with missing stay (blocker)."""
    return AggregatedResults(
        transport=AgentResultEntry(
            status="SUCCESS",
            data={"flights": [{"airline": "JAL", "price": 1200}]},
        ),
        stay=AgentResultEntry(
            status="ERROR",
            data=None,
            message="No hotels found",
        ),
        poi=AgentResultEntry(
            status="SUCCESS",
            data={"attractions": [{"name": "Tokyo Tower"}]},
        ),
        events=AgentResultEntry(status="SUCCESS", data={}),
        dining=AgentResultEntry(status="SUCCESS", data={}),
        destination="Tokyo",
    )


@pytest.fixture
def aggregated_missing_all_activities() -> AggregatedResults:
    """Create aggregated results with missing POI and events."""
    return AggregatedResults(
        transport=AgentResultEntry(
            status="SUCCESS",
            data={"flights": [{"airline": "JAL", "price": 1200}]},
        ),
        stay=AgentResultEntry(
            status="SUCCESS",
            data={"hotels": [{"name": "Park Hyatt", "price_per_night": 500}]},
        ),
        poi=AgentResultEntry(
            status="ERROR",
            data=None,
            message="POI service down",
        ),
        events=AgentResultEntry(
            status="TIMEOUT",
            data=None,
            message="Events timeout",
        ),
        dining=AgentResultEntry(
            status="SUCCESS",
            data={"restaurants": [{"name": "Sushi Place"}]},
        ),
        destination="Tokyo",
    )


@pytest.fixture
def aggregated_missing_dining() -> AggregatedResults:
    """Create aggregated results with missing dining."""
    return AggregatedResults(
        transport=AgentResultEntry(
            status="SUCCESS",
            data={"flights": [{"airline": "JAL", "price": 1200}]},
        ),
        stay=AgentResultEntry(
            status="SUCCESS",
            data={"hotels": [{"name": "Park Hyatt", "price_per_night": 500}]},
        ),
        poi=AgentResultEntry(
            status="SUCCESS",
            data={"attractions": [{"name": "Tokyo Tower"}]},
        ),
        events=AgentResultEntry(
            status="SUCCESS",
            data={"events": []},
        ),
        dining=AgentResultEntry(
            status="ERROR",
            data=None,
            message="Dining service unavailable",
        ),
        destination="Tokyo",
    )


@pytest.fixture
def budget_plan() -> BudgetPlan:
    """Sample budget plan from Budget agent."""
    return BudgetPlan(
        total_budget=10000.0,
        currency="USD",
        allocations=[
            CategoryAllocation(category="transport", amount=3000.0, percentage=30.0),
            CategoryAllocation(category="stay", amount=3500.0, percentage=35.0),
            CategoryAllocation(category="activities", amount=2000.0, percentage=20.0),
            CategoryAllocation(category="dining", amount=1000.0, percentage=10.0),
            CategoryAllocation(category="misc", amount=500.0, percentage=5.0),
        ],
    )


@pytest.fixture
def trip_spec() -> dict[str, Any]:
    """Sample trip specification."""
    return {
        "destination_city": "Tokyo",
        "origin_city": "New York",
        "start_date": "2026-03-10",
        "end_date": "2026-03-14",
        "num_travelers": 2,
        "budget_per_person": 5000,
        "budget_currency": "USD",
    }


@pytest.fixture
def discovery_context_no_gaps() -> DiscoveryContext:
    """Discovery context with no gaps."""
    empty_results = DiscoveryResults()
    return DiscoveryContext(
        results=empty_results,
        gaps=[],
    )


@pytest.fixture
def discovery_context_with_transport_gap() -> DiscoveryContext:
    """Discovery context with transport gap."""
    empty_results = DiscoveryResults()
    return DiscoveryContext(
        results=empty_results,
        gaps=[
            DiscoveryGap(
                agent="transport",
                status=DiscoveryStatus.TIMEOUT,
                impact="Arrival and departure times unknown",
                placeholder_strategy="Itinerary assumes 2pm arrival Day 1, 11am departure final day",
                user_action_required=True,
            ),
        ],
    )


@pytest.fixture
def discovery_context_with_activity_gaps() -> DiscoveryContext:
    """Discovery context with POI and events gaps."""
    empty_results = DiscoveryResults()
    return DiscoveryContext(
        results=empty_results,
        gaps=[
            DiscoveryGap(
                agent="poi",
                status=DiscoveryStatus.ERROR,
                impact="Limited attractions",
                user_action_required=False,
            ),
            DiscoveryGap(
                agent="events",
                status=DiscoveryStatus.TIMEOUT,
                impact="No events available",
                user_action_required=False,
            ),
        ],
    )


@pytest.fixture
def discovery_context_with_dining_gap() -> DiscoveryContext:
    """Discovery context with dining gap."""
    empty_results = DiscoveryResults()
    return DiscoveryContext(
        results=empty_results,
        gaps=[
            DiscoveryGap(
                agent="dining",
                status=DiscoveryStatus.ERROR,
                impact="Restaurant recommendations not available",
                user_action_required=False,
            ),
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TimeSlot Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestTimeSlot:
    """Tests for TimeSlot dataclass."""

    def test_create_time_slot(self) -> None:
        """Test creating a time slot."""
        slot = TimeSlot(
            start_time=time(9, 0),
            end_time=time(12, 0),
            duration_minutes=180,
        )
        assert slot.start_time == time(9, 0)
        assert slot.end_time == time(12, 0)
        assert slot.duration_minutes == 180

    def test_create_empty_time_slot(self) -> None:
        """Test creating an empty time slot (for placeholders)."""
        slot = TimeSlot()
        assert slot.start_time is None
        assert slot.end_time is None
        assert slot.duration_minutes is None

    def test_to_dict(self) -> None:
        """Test serialization of time slot."""
        slot = TimeSlot(
            start_time=time(10, 30),
            end_time=time(12, 45),
            duration_minutes=135,
        )
        result = slot.to_dict()
        assert result["start_time"] == "10:30"
        assert result["end_time"] == "12:45"
        assert result["duration_minutes"] == 135

    def test_to_dict_empty(self) -> None:
        """Test serialization of empty time slot."""
        slot = TimeSlot()
        result = slot.to_dict()
        assert "start_time" not in result
        assert "end_time" not in result

    def test_from_dict(self) -> None:
        """Test deserialization of time slot."""
        data = {
            "start_time": "14:30",
            "end_time": "16:00",
            "duration_minutes": 90,
        }
        slot = TimeSlot.from_dict(data)
        assert slot.start_time == time(14, 30)
        assert slot.end_time == time(16, 0)
        assert slot.duration_minutes == 90

    def test_from_dict_empty(self) -> None:
        """Test deserialization of empty data."""
        slot = TimeSlot.from_dict({})
        assert slot.start_time is None
        assert slot.end_time is None


# ═══════════════════════════════════════════════════════════════════════════════
# ItineraryActivity Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestItineraryActivity:
    """Tests for ItineraryActivity dataclass."""

    def test_create_activity(self) -> None:
        """Test creating an activity."""
        activity = ItineraryActivity(
            name="Tokyo Tower",
            category="attraction",
            time_slot=TimeSlot(start_time=time(10, 0), end_time=time(12, 0)),
            location="Minato",
            estimated_cost=20.0,
        )
        assert activity.name == "Tokyo Tower"
        assert activity.category == "attraction"
        assert activity.location == "Minato"
        assert activity.is_placeholder is False

    def test_create_free_time_placeholder(self) -> None:
        """Test creating a free time placeholder activity."""
        activity = ItineraryActivity(
            name="Free time (morning)",
            category="free_time",
            time_slot=TimeSlot(start_time=time(10, 0), end_time=time(12, 0)),
            notes="Free time to explore",
            is_placeholder=True,
        )
        assert activity.is_placeholder is True
        assert activity.category == "free_time"

    def test_to_dict(self) -> None:
        """Test serialization of activity."""
        activity = ItineraryActivity(
            name="Senso-ji Temple",
            category="temple",
            time_slot=TimeSlot(start_time=time(14, 0)),
            location="Asakusa",
        )
        result = activity.to_dict()
        assert result["name"] == "Senso-ji Temple"
        assert result["category"] == "temple"
        assert result["location"] == "Asakusa"
        assert "time_slot" in result

    def test_from_dict(self) -> None:
        """Test deserialization of activity."""
        data = {
            "name": "Cherry Blossom Festival",
            "category": "event",
            "time_slot": {"start_time": "15:00", "end_time": "18:00"},
            "location": "Ueno Park",
            "is_placeholder": False,
        }
        activity = ItineraryActivity.from_dict(data)
        assert activity.name == "Cherry Blossom Festival"
        assert activity.category == "event"
        assert activity.location == "Ueno Park"


# ═══════════════════════════════════════════════════════════════════════════════
# ItineraryMeal Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestItineraryMeal:
    """Tests for ItineraryMeal dataclass."""

    def test_create_meal(self) -> None:
        """Test creating a meal."""
        meal = ItineraryMeal(
            meal_type="dinner",
            name="Sukiyabashi Jiro",
            time_slot=TimeSlot(start_time=time(19, 0), end_time=time(20, 30)),
            location="Ginza",
            cuisine="sushi",
        )
        assert meal.meal_type == "dinner"
        assert meal.name == "Sukiyabashi Jiro"
        assert meal.cuisine == "sushi"
        assert meal.is_placeholder is False

    def test_create_placeholder_meal(self) -> None:
        """Test creating a placeholder meal."""
        meal = ItineraryMeal(
            meal_type="lunch",
            name="Lunch break",
            time_slot=TimeSlot(start_time=time(12, 30)),
            notes="Restaurant recommendation not available",
            is_placeholder=True,
        )
        assert meal.is_placeholder is True
        assert meal.name == "Lunch break"

    def test_to_dict(self) -> None:
        """Test serialization of meal."""
        meal = ItineraryMeal(
            meal_type="breakfast",
            name="Hotel Restaurant",
            time_slot=TimeSlot(start_time=time(8, 0)),
        )
        result = meal.to_dict()
        assert result["meal_type"] == "breakfast"
        assert result["name"] == "Hotel Restaurant"

    def test_from_dict(self) -> None:
        """Test deserialization of meal."""
        data = {
            "meal_type": "lunch",
            "name": "Ramen Shop",
            "time_slot": {"start_time": "12:30"},
            "cuisine": "ramen",
        }
        meal = ItineraryMeal.from_dict(data)
        assert meal.meal_type == "lunch"
        assert meal.name == "Ramen Shop"


# ═══════════════════════════════════════════════════════════════════════════════
# ItineraryTransport Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestItineraryTransport:
    """Tests for ItineraryTransport dataclass."""

    def test_create_transport(self) -> None:
        """Test creating a transport segment."""
        transport = ItineraryTransport(
            mode="flight",
            from_location="New York",
            to_location="Tokyo",
            time_slot=TimeSlot(start_time=time(9, 0), end_time=time(14, 0)),
            departure_time="09:00",
            arrival_time="14:00",
            carrier="JAL",
        )
        assert transport.mode == "flight"
        assert transport.from_location == "New York"
        assert transport.carrier == "JAL"
        assert transport.is_placeholder is False

    def test_create_placeholder_transport(self) -> None:
        """Test creating a placeholder transport."""
        transport = ItineraryTransport(
            mode="flight",
            from_location="New York",
            to_location="Tokyo",
            time_slot=TimeSlot(end_time=time(14, 0)),
            arrival_time="14:00",
            notes="Arrival: User to arrange",
            is_placeholder=True,
        )
        assert transport.is_placeholder is True
        assert "User to arrange" in (transport.notes or "")

    def test_to_dict(self) -> None:
        """Test serialization of transport."""
        transport = ItineraryTransport(
            mode="train",
            from_location="Tokyo",
            to_location="Kyoto",
            time_slot=TimeSlot(start_time=time(8, 0)),
            estimated_cost=150.0,
        )
        result = transport.to_dict()
        assert result["mode"] == "train"
        assert result["estimated_cost"] == 150.0

    def test_from_dict(self) -> None:
        """Test deserialization of transport."""
        data = {
            "mode": "taxi",
            "from_location": "Airport",
            "to_location": "Hotel",
            "time_slot": {"start_time": "14:00", "duration_minutes": 60},
        }
        transport = ItineraryTransport.from_dict(data)
        assert transport.mode == "taxi"


# ═══════════════════════════════════════════════════════════════════════════════
# ItineraryDay Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestItineraryDay:
    """Tests for ItineraryDay dataclass."""

    def test_create_day(self) -> None:
        """Test creating an itinerary day."""
        day = ItineraryDay(
            day_number=1,
            date=date_type(2026, 3, 10),
            title="Day 1 in Tokyo",
        )
        assert day.day_number == 1
        assert day.date == date_type(2026, 3, 10)
        assert day.title == "Day 1 in Tokyo"
        assert len(day.activities) == 0
        assert len(day.meals) == 0

    def test_to_dict(self) -> None:
        """Test serialization of day."""
        day = ItineraryDay(
            day_number=2,
            date=date_type(2026, 3, 11),
            title="Day 2 in Tokyo",
            activities=[
                ItineraryActivity(
                    name="Tokyo Tower",
                    category="attraction",
                    time_slot=TimeSlot(start_time=time(10, 0)),
                ),
            ],
        )
        result = day.to_dict()
        assert result["day_number"] == 2
        assert result["date"] == "2026-03-11"
        assert len(result["activities"]) == 1

    def test_from_dict(self) -> None:
        """Test deserialization of day."""
        data = {
            "day_number": 3,
            "date": "2026-03-12",
            "title": "Day 3",
            "activities": [],
            "meals": [],
            "transport": [],
        }
        day = ItineraryDay.from_dict(data)
        assert day.day_number == 3
        assert day.date == date_type(2026, 3, 12)


# ═══════════════════════════════════════════════════════════════════════════════
# RoutePlan Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestRoutePlan:
    """Tests for RoutePlan dataclass."""

    def test_create_route_plan(self) -> None:
        """Test creating a route plan."""
        plan = RoutePlan(
            destination="Tokyo",
            start_date=date_type(2026, 3, 10),
            end_date=date_type(2026, 3, 14),
            days=[
                ItineraryDay(day_number=1, date=date_type(2026, 3, 10), title="Day 1"),
                ItineraryDay(day_number=2, date=date_type(2026, 3, 11), title="Day 2"),
            ],
            total_estimated_cost=10000.0,
            currency="USD",
        )
        assert plan.destination == "Tokyo"
        assert plan.num_days() == 2
        assert plan.has_placeholders is False

    def test_get_day(self) -> None:
        """Test getting a specific day."""
        plan = RoutePlan(
            destination="Tokyo",
            start_date=date_type(2026, 3, 10),
            end_date=date_type(2026, 3, 12),
            days=[
                ItineraryDay(day_number=1, date=date_type(2026, 3, 10), title="Day 1"),
                ItineraryDay(day_number=2, date=date_type(2026, 3, 11), title="Day 2"),
            ],
        )
        day1 = plan.get_day(1)
        assert day1 is not None
        assert day1.title == "Day 1"

        day3 = plan.get_day(3)
        assert day3 is None

    def test_to_dict(self) -> None:
        """Test serialization of route plan."""
        plan = RoutePlan(
            destination="Tokyo",
            start_date=date_type(2026, 3, 10),
            end_date=date_type(2026, 3, 14),
            total_estimated_cost=10000.0,
            has_placeholders=True,
            notes=["Transport to be arranged"],
        )
        result = plan.to_dict()
        assert result["destination"] == "Tokyo"
        assert result["start_date"] == "2026-03-10"
        assert result["has_placeholders"] is True
        assert "Transport to be arranged" in result["notes"]

    def test_from_dict(self) -> None:
        """Test deserialization of route plan."""
        data = {
            "destination": "Kyoto",
            "start_date": "2026-04-01",
            "end_date": "2026-04-05",
            "days": [],
            "total_estimated_cost": 5000.0,
            "currency": "JPY",
        }
        plan = RoutePlan.from_dict(data)
        assert plan.destination == "Kyoto"
        assert plan.currency == "JPY"


# ═══════════════════════════════════════════════════════════════════════════════
# RoutePlanningError Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestRoutePlanningError:
    """Tests for RoutePlanningError exception."""

    def test_create_error(self) -> None:
        """Test creating a route planning error."""
        error = RoutePlanningError(
            "Cannot build itinerary without accommodation",
            blocker="missing_stay",
        )
        assert "accommodation" in str(error).lower()
        assert error.blocker == "missing_stay"

    def test_create_error_without_blocker(self) -> None:
        """Test creating error without blocker specified."""
        error = RoutePlanningError("Generic error")
        assert "Generic error" in str(error)
        assert error.blocker is None


# ═══════════════════════════════════════════════════════════════════════════════
# RouteAgent Tests - Core Functionality
# ═══════════════════════════════════════════════════════════════════════════════


class TestRouteAgent:
    """Tests for RouteAgent class."""

    @pytest.mark.asyncio
    async def test_plan_with_full_results(
        self,
        full_aggregated_results: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that route agent creates itinerary with full discovery."""
        agent = RouteAgent()
        plan = await agent.plan(
            aggregated=full_aggregated_results,
            budget_plan=budget_plan,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # Should have correct number of days (Mar 10-14 = 5 days)
        assert plan.num_days() == 5
        assert plan.destination == "Tokyo"
        assert plan.start_date == date_type(2026, 3, 10)
        assert plan.end_date == date_type(2026, 3, 14)

        # No placeholders expected with full results
        assert plan.has_placeholders is False

        # Check first day has arrival transport
        day1 = plan.get_day(1)
        assert day1 is not None
        assert len(day1.transport) > 0
        arrival = day1.transport[0]
        assert arrival.to_location == "Tokyo"

        # Check last day has departure transport
        day5 = plan.get_day(5)
        assert day5 is not None
        assert len(day5.transport) > 0

    @pytest.mark.asyncio
    async def test_plan_blocks_on_missing_stay(
        self,
        aggregated_missing_stay: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that missing stay raises RoutePlanningError."""
        agent = RouteAgent()

        with pytest.raises(RoutePlanningError) as exc_info:
            await agent.plan(
                aggregated=aggregated_missing_stay,
                budget_plan=budget_plan,
                discovery_context=discovery_context_no_gaps,
                trip_spec=trip_spec,
            )

        assert "accommodation" in str(exc_info.value).lower()
        assert exc_info.value.blocker == "missing_stay"

    @pytest.mark.asyncio
    async def test_plan_uses_placeholder_for_missing_transport(
        self,
        aggregated_missing_transport: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context_with_transport_gap: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that missing transport results in placeholder arrival/departure."""
        agent = RouteAgent()
        plan = await agent.plan(
            aggregated=aggregated_missing_transport,
            budget_plan=budget_plan,
            discovery_context=discovery_context_with_transport_gap,
            trip_spec=trip_spec,
        )

        # Should have placeholder flag set
        assert plan.has_placeholders is True

        # Check first day has placeholder arrival
        day1 = plan.get_day(1)
        assert day1 is not None
        assert len(day1.transport) > 0
        arrival = day1.transport[0]
        assert arrival.is_placeholder is True
        assert "User to arrange" in (arrival.notes or "")
        assert arrival.arrival_time == DEFAULT_ARRIVAL_TIME.strftime("%H:%M")

        # Check last day has placeholder departure
        last_day = plan.get_day(plan.num_days())
        assert last_day is not None
        departure = [t for t in last_day.transport if t.departure_time]
        assert len(departure) > 0
        assert departure[0].is_placeholder is True
        assert departure[0].departure_time == DEFAULT_DEPARTURE_TIME.strftime("%H:%M")

        # Should have notes about transport
        assert any("arrival" in note.lower() or "transport" in note.lower() for note in plan.notes)

    @pytest.mark.asyncio
    async def test_plan_uses_free_time_for_missing_poi_and_events(
        self,
        aggregated_missing_all_activities: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context_with_activity_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that missing POI and events results in 'Free time' blocks."""
        agent = RouteAgent()
        plan = await agent.plan(
            aggregated=aggregated_missing_all_activities,
            budget_plan=budget_plan,
            discovery_context=discovery_context_with_activity_gaps,
            trip_spec=trip_spec,
        )

        # Should have placeholder flag set
        assert plan.has_placeholders is True

        # Check that days have free time activities
        day2 = plan.get_day(2)
        assert day2 is not None
        assert len(day2.activities) > 0

        # All activities should be free time placeholders
        for activity in day2.activities:
            assert activity.is_placeholder is True
            assert activity.category == "free_time"
            assert "Free time" in activity.name

        # Should have note about limited attractions
        assert any("free time" in note.lower() or "attraction" in note.lower() for note in plan.notes)

    @pytest.mark.asyncio
    async def test_plan_uses_placeholder_meals_for_missing_dining(
        self,
        aggregated_missing_dining: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context_with_dining_gap: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that missing dining results in placeholder meals."""
        agent = RouteAgent()
        plan = await agent.plan(
            aggregated=aggregated_missing_dining,
            budget_plan=budget_plan,
            discovery_context=discovery_context_with_dining_gap,
            trip_spec=trip_spec,
        )

        # Check that days have placeholder meals
        day2 = plan.get_day(2)
        assert day2 is not None
        assert len(day2.meals) > 0

        # All meals should be placeholders
        for meal in day2.meals:
            assert meal.is_placeholder is True
            assert "break" in meal.name.lower()

        # Should have note about restaurant recommendations
        assert any("restaurant" in note.lower() or "dining" in note.lower() for note in plan.notes)

    @pytest.mark.asyncio
    async def test_plan_includes_accommodation(
        self,
        full_aggregated_results: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that days include accommodation (except last day)."""
        agent = RouteAgent()
        plan = await agent.plan(
            aggregated=full_aggregated_results,
            budget_plan=budget_plan,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # All days except last should have accommodation
        for i in range(1, plan.num_days()):
            day = plan.get_day(i)
            assert day is not None
            assert day.accommodation is not None
            assert day.accommodation.name == "Park Hyatt Tokyo"

        # Last day should not have accommodation
        last_day = plan.get_day(plan.num_days())
        assert last_day is not None
        assert last_day.accommodation is None

    @pytest.mark.asyncio
    async def test_plan_activities_have_time_slots(
        self,
        full_aggregated_results: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that all activities have time slots."""
        agent = RouteAgent()
        plan = await agent.plan(
            aggregated=full_aggregated_results,
            budget_plan=budget_plan,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # Check all activities have time slots
        for day in plan.days:
            for activity in day.activities:
                assert activity.time_slot is not None
                assert activity.time_slot.start_time is not None

    @pytest.mark.asyncio
    async def test_plan_first_day_items_do_not_overlap_arrival_transport(
        self,
        full_aggregated_results: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """First day activities/meals should not overlap the arrival transport window."""
        agent = RouteAgent()
        plan = await agent.plan(
            aggregated=full_aggregated_results,
            budget_plan=budget_plan,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        day1 = plan.get_day(1)
        assert day1 is not None
        assert day1.transport

        arrival = day1.transport[0]
        arrival_start = arrival.time_slot.start_time
        arrival_end = arrival.time_slot.end_time

        for activity in day1.activities:
            assert not _slots_overlap(
                activity.time_slot.start_time,
                activity.time_slot.end_time,
                arrival_start,
                arrival_end,
            )

        for meal in day1.meals:
            assert not _slots_overlap(
                meal.time_slot.start_time,
                meal.time_slot.end_time,
                arrival_start,
                arrival_end,
            )

    @pytest.mark.asyncio
    async def test_plan_last_day_items_do_not_overlap_departure_transport(
        self,
        full_aggregated_results: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Final day activities/meals should not overlap the departure transport window."""
        agent = RouteAgent()
        plan = await agent.plan(
            aggregated=full_aggregated_results,
            budget_plan=budget_plan,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        last_day = plan.get_day(plan.num_days())
        assert last_day is not None
        assert last_day.transport

        departure = last_day.transport[0]
        departure_start = departure.time_slot.start_time
        departure_end = departure.time_slot.end_time

        for activity in last_day.activities:
            assert not _slots_overlap(
                activity.time_slot.start_time,
                activity.time_slot.end_time,
                departure_start,
                departure_end,
            )

        for meal in last_day.meals:
            assert not _slots_overlap(
                meal.time_slot.start_time,
                meal.time_slot.end_time,
                departure_start,
                departure_end,
            )

    @pytest.mark.asyncio
    async def test_plan_meals_have_time_slots(
        self,
        full_aggregated_results: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that all meals have time slots."""
        agent = RouteAgent()
        plan = await agent.plan(
            aggregated=full_aggregated_results,
            budget_plan=budget_plan,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # Check all meals have time slots
        for day in plan.days:
            for meal in day.meals:
                assert meal.time_slot is not None
                assert meal.time_slot.start_time is not None

    @pytest.mark.asyncio
    async def test_plan_handles_no_trip_spec(
        self,
        full_aggregated_results: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context_no_gaps: DiscoveryContext,
    ) -> None:
        """Test that route agent works with missing trip_spec."""
        agent = RouteAgent()
        plan = await agent.plan(
            aggregated=full_aggregated_results,
            budget_plan=budget_plan,
            discovery_context=discovery_context_no_gaps,
            trip_spec=None,
        )

        # Should still produce valid plan with defaults
        assert plan is not None
        assert plan.num_days() > 0
        assert plan.destination == "Tokyo"  # From aggregated results

    @pytest.mark.asyncio
    async def test_plan_uses_budget_info(
        self,
        full_aggregated_results: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that route plan includes budget info."""
        agent = RouteAgent()
        plan = await agent.plan(
            aggregated=full_aggregated_results,
            budget_plan=budget_plan,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        assert plan.total_estimated_cost == budget_plan.total_budget
        assert plan.currency == budget_plan.currency


# ═══════════════════════════════════════════════════════════════════════════════
# RouteAgent A2A Integration Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestRouteAgentA2A:
    """Tests for RouteAgent A2A integration."""

    @pytest.fixture
    def mock_a2a_client(self) -> AsyncMock:
        """Create mock A2A client."""
        client = AsyncMock()
        return client

    @pytest.fixture
    def mock_agent_registry(self) -> MagicMock:
        """Create mock agent registry."""
        registry = MagicMock()
        route_config = MagicMock()
        route_config.url = "http://localhost:8012"
        route_config.timeout = 60
        registry.get.return_value = route_config
        return registry

    @pytest.mark.asyncio
    async def test_route_calls_a2a_when_available(
        self,
        mock_a2a_client: AsyncMock,
        mock_agent_registry: MagicMock,
        full_aggregated_results: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that route agent calls A2A client when available."""
        # Configure mock response
        mock_response = MagicMock()
        mock_response.is_complete = True
        mock_response.text = '''{
            "destination": "Tokyo",
            "start_date": "2026-03-10",
            "end_date": "2026-03-14",
            "days": [],
            "total_estimated_cost": 10000,
            "currency": "USD",
            "has_placeholders": false,
            "notes": []
        }'''
        mock_a2a_client.send_message.return_value = mock_response

        agent = RouteAgent(
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        plan = await agent.plan(
            aggregated=full_aggregated_results,
            budget_plan=budget_plan,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # Verify A2A client was called
        mock_a2a_client.send_message.assert_called_once()
        call_kwargs = mock_a2a_client.send_message.call_args.kwargs
        assert call_kwargs["agent_url"] == "http://localhost:8012"
        assert call_kwargs["timeout"] == 60

    @pytest.mark.asyncio
    async def test_route_falls_back_on_a2a_error(
        self,
        mock_a2a_client: AsyncMock,
        mock_agent_registry: MagicMock,
        full_aggregated_results: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that route agent falls back to local on A2A error."""
        # Configure mock to raise exception
        mock_a2a_client.send_message.side_effect = Exception("Connection failed")

        agent = RouteAgent(
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        plan = await agent.plan(
            aggregated=full_aggregated_results,
            budget_plan=budget_plan,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # Should still get valid plan from local fallback
        assert plan is not None
        assert plan.destination == "Tokyo"
        assert plan.num_days() == 5

    @pytest.mark.asyncio
    async def test_route_falls_back_on_incomplete_response(
        self,
        mock_a2a_client: AsyncMock,
        mock_agent_registry: MagicMock,
        full_aggregated_results: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that route agent falls back when A2A response is incomplete."""
        # Configure mock to return incomplete response
        mock_response = MagicMock()
        mock_response.is_complete = False
        mock_response.text = ""
        mock_a2a_client.send_message.return_value = mock_response

        agent = RouteAgent(
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        plan = await agent.plan(
            aggregated=full_aggregated_results,
            budget_plan=budget_plan,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # Should still get valid plan from local fallback
        assert plan is not None
        assert plan.destination == "Tokyo"

    @pytest.mark.asyncio
    async def test_route_falls_back_on_missing_registry_entry(
        self,
        mock_a2a_client: AsyncMock,
        full_aggregated_results: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that route agent falls back when not in registry."""
        # Configure registry to return None
        mock_registry = MagicMock()
        mock_registry.get.return_value = None

        agent = RouteAgent(
            a2a_client=mock_a2a_client,
            agent_registry=mock_registry,
        )

        plan = await agent.plan(
            aggregated=full_aggregated_results,
            budget_plan=budget_plan,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # Should still get valid plan from local fallback
        assert plan is not None
        assert plan.destination == "Tokyo"

        # A2A client should not be called
        mock_a2a_client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_route_falls_back_on_invalid_json(
        self,
        mock_a2a_client: AsyncMock,
        mock_agent_registry: MagicMock,
        full_aggregated_results: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that route agent falls back on invalid JSON response."""
        # Configure mock to return invalid JSON
        mock_response = MagicMock()
        mock_response.is_complete = True
        mock_response.text = "not valid json"
        mock_a2a_client.send_message.return_value = mock_response

        agent = RouteAgent(
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        plan = await agent.plan(
            aggregated=full_aggregated_results,
            budget_plan=budget_plan,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # Should still get valid plan from local fallback
        assert plan is not None
        assert plan.destination == "Tokyo"

    @pytest.mark.asyncio
    async def test_route_normalizes_overlapping_a2a_slots(
        self,
        mock_a2a_client: AsyncMock,
        mock_agent_registry: MagicMock,
        full_aggregated_results: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """A2A route responses should be normalized to a conflict-free day schedule."""
        mock_response = MagicMock()
        mock_response.is_complete = True
        mock_response.text = """{
            "destination": "Tokyo",
            "start_date": "2026-03-10",
            "end_date": "2026-03-10",
            "days": [
                {
                    "day_number": 1,
                    "date": "2026-03-10",
                    "title": "Day 1 in Tokyo",
                    "activities": [
                        {
                            "name": "Late attraction",
                            "category": "attraction",
                            "time_slot": {"start_time": "16:30", "end_time": "18:30"}
                        },
                        {
                            "name": "Morning attraction",
                            "category": "attraction",
                            "time_slot": {"start_time": "10:00", "end_time": "12:00"}
                        },
                        {
                            "name": "Overlapping attraction",
                            "category": "attraction",
                            "time_slot": {"start_time": "11:30", "end_time": "13:00"}
                        }
                    ],
                    "meals": [
                        {
                            "meal_type": "lunch",
                            "name": "Lunch",
                            "time_slot": {"start_time": "12:30", "end_time": "13:30"}
                        },
                        {
                            "meal_type": "dinner",
                            "name": "Dinner",
                            "time_slot": {"start_time": "19:00", "end_time": "20:30"}
                        }
                    ],
                    "transport": []
                }
            ],
            "total_estimated_cost": 10000,
            "currency": "USD",
            "has_placeholders": false,
            "notes": []
        }"""
        mock_a2a_client.send_message.return_value = mock_response

        agent = RouteAgent(
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )
        plan = await agent.plan(
            aggregated=full_aggregated_results,
            budget_plan=budget_plan,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        day1 = plan.get_day(1)
        assert day1 is not None

        timed_slots: list[tuple[time | None, time | None]] = []
        for activity in day1.activities:
            timed_slots.append((activity.time_slot.start_time, activity.time_slot.end_time))
        for meal in day1.meals:
            timed_slots.append((meal.time_slot.start_time, meal.time_slot.end_time))

        for i in range(len(timed_slots)):
            for j in range(i + 1, len(timed_slots)):
                assert not _slots_overlap(
                    timed_slots[i][0],
                    timed_slots[i][1],
                    timed_slots[j][0],
                    timed_slots[j][1],
                )

    @pytest.mark.asyncio
    async def test_route_still_checks_stay_blocker_before_a2a(
        self,
        mock_a2a_client: AsyncMock,
        mock_agent_registry: MagicMock,
        aggregated_missing_stay: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that missing stay blocks before even attempting A2A call."""
        agent = RouteAgent(
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        with pytest.raises(RoutePlanningError) as exc_info:
            await agent.plan(
                aggregated=aggregated_missing_stay,
                budget_plan=budget_plan,
                discovery_context=discovery_context_no_gaps,
                trip_spec=trip_spec,
            )

        # A2A should NOT have been called since stay is a blocker
        mock_a2a_client.send_message.assert_not_called()
        assert exc_info.value.blocker == "missing_stay"
