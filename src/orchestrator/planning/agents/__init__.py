"""
Planning agents for the orchestrator planning pipeline.

This module contains the planning agents that transform discovery results
into a validated itinerary:

    Discovery (parallel) -> Aggregator -> Budget -> Route -> Validator

Per design doc, the planning pipeline is sequential:
1. Aggregator: Combines discovery results from 5 domain agents
2. Budget: Allocates costs across categories (transport, stay, activities, dining)
3. Route: Creates day-by-day itinerary with timing and logistics
4. Validator: Checks feasibility, flags errors/warnings/gaps
"""

from src.orchestrator.planning.agents.aggregator import (
    AggregatedResults,
    AgentResultEntry,
    AggregatorAgent,
)
from src.orchestrator.planning.agents.budget import (
    BudgetAgent,
    BudgetAllocationError,
    BudgetPlan,
    CategoryAllocation,
)
from src.orchestrator.planning.agents.route import (
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
from src.orchestrator.planning.agents.validator import (
    ValidatorAgent,
)

__all__ = [
    "AggregatedResults",
    "AgentResultEntry",
    "AggregatorAgent",
    "BudgetAgent",
    "BudgetAllocationError",
    "BudgetPlan",
    "CategoryAllocation",
    "ItineraryAccommodation",
    "ItineraryActivity",
    "ItineraryDay",
    "ItineraryMeal",
    "ItineraryTransport",
    "RouteAgent",
    "RoutePlan",
    "RoutePlanningError",
    "TimeSlot",
    "ValidatorAgent",
]
