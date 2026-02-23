"""
Budget agent for allocating costs across trip categories.

The Budget agent is the second planning agent in the pipeline. It receives
aggregated discovery results from the Aggregator and allocates the user's
budget across categories (transport, stay, activities, dining, misc).

Per design doc "Downstream Pipeline with Partial Results" section:
- Missing transport: Reserve placeholder "Transport: TBD (~$300-800)" using route-based estimates
- Missing stay: **BLOCKER** - cannot allocate without stay costs
- Missing POI: Reduce activities budget, note "fewer planned activities"

The budget plan is consumed by the Route agent.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from src.orchestrator.planning.agents.aggregator import AggregatedResults
from src.orchestrator.planning.pipeline import DiscoveryContext

if TYPE_CHECKING:
    from src.shared.a2a.client_wrapper import A2AClientWrapper
    from src.shared.a2a.registry import AgentRegistry

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Budget Category Allocation Model
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class CategoryAllocation:
    """
    Budget allocation for a single category.

    Per design doc, each category allocation includes:
    - category: Name of the category (transport, stay, activities, dining, misc)
    - amount: Allocated amount in the budget currency
    - percentage: Percentage of total budget
    - is_placeholder: Whether this is an estimate due to missing data
    - placeholder_note: Explanation when is_placeholder is True
    - item_count: Number of items this allocation covers (if known)
    """

    category: str
    amount: float
    percentage: float
    is_placeholder: bool = False
    placeholder_note: str | None = None
    item_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        result: dict[str, Any] = {
            "category": self.category,
            "amount": self.amount,
            "percentage": self.percentage,
            "is_placeholder": self.is_placeholder,
        }
        if self.placeholder_note is not None:
            result["placeholder_note"] = self.placeholder_note
        if self.item_count is not None:
            result["item_count"] = self.item_count
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CategoryAllocation:
        """Deserialize from dictionary."""
        return cls(
            category=data.get("category", ""),
            amount=float(data.get("amount", 0)),
            percentage=float(data.get("percentage", 0)),
            is_placeholder=data.get("is_placeholder", False),
            placeholder_note=data.get("placeholder_note"),
            item_count=data.get("item_count"),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Budget Plan Model
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class BudgetPlan:
    """
    Output from the Budget agent.

    Contains the full budget allocation plan with:
    - total_budget: Total budget for the trip
    - currency: Budget currency (e.g., "USD")
    - allocations: List of CategoryAllocation objects
    - has_placeholders: Whether any allocations are estimates
    - notes: Additional notes/warnings about the budget
    - budgeted_at: Timestamp when budget was calculated
    """

    total_budget: float
    currency: str
    allocations: list[CategoryAllocation] = field(default_factory=list)
    has_placeholders: bool = False
    notes: list[str] = field(default_factory=list)
    budgeted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for storage/transmission."""
        return {
            "total_budget": self.total_budget,
            "currency": self.currency,
            "allocations": [a.to_dict() for a in self.allocations],
            "has_placeholders": self.has_placeholders,
            "notes": self.notes,
            "budgeted_at": self.budgeted_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BudgetPlan:
        """Deserialize from dictionary."""
        def normalize_category(category: Any) -> str:
            if not isinstance(category, str):
                return ""
            return {
                "accommodation": "stay",
                "miscellaneous": "misc",
            }.get(category, category)

        def allocations_from_items(
            items: list[dict[str, Any]] | None,
            total_budget: float,
            amount_key: str = "amount",
        ) -> list[CategoryAllocation]:
            allocations: list[CategoryAllocation] = []
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                amount_raw = item.get(amount_key, item.get("amount", 0))
                amount = float(amount_raw or 0)
                allocations.append(
                    CategoryAllocation(
                        category=normalize_category(item.get("category", "")),
                        amount=amount,
                        percentage=(amount / total_budget) if total_budget else 0.0,
                    )
                )
            return allocations

        budgeted_at = data.get("budgeted_at")
        if isinstance(budgeted_at, str):
            budgeted_at = datetime.fromisoformat(budgeted_at)
        elif budgeted_at is None:
            budgeted_at = datetime.now(timezone.utc)

        if any(key in data for key in ("mode", "proposal", "validation", "tracking", "reallocation")):
            proposal = data.get("proposal") or {}
            if isinstance(proposal, dict) and proposal:
                total_budget = float(proposal.get("total_budget", data.get("total_budget", 0)) or 0)
                currency = proposal.get("currency", data.get("currency", "USD"))
                notes: list[str] = []
                rationale = proposal.get("rationale")
                if isinstance(rationale, str) and rationale:
                    notes.append(rationale)
                return cls(
                    total_budget=total_budget,
                    currency=currency,
                    allocations=allocations_from_items(proposal.get("allocations"), total_budget),
                    has_placeholders=False,
                    notes=notes,
                    budgeted_at=budgeted_at,
                )

            validation = data.get("validation") or {}
            if isinstance(validation, dict) and validation:
                total_budget = float(validation.get("total_budget", data.get("total_budget", 0)) or 0)
                currency = validation.get("currency", data.get("currency", "USD"))
                notes = []
                notes.extend(validation.get("issues", []))
                notes.extend(validation.get("warnings", []))
                return cls(
                    total_budget=total_budget,
                    currency=currency,
                    allocations=allocations_from_items(
                        validation.get("by_category"),
                        total_budget,
                        amount_key="allocated",
                    ),
                    has_placeholders=False,
                    notes=notes,
                    budgeted_at=budgeted_at,
                )

            tracking = data.get("tracking") or {}
            if isinstance(tracking, dict) and tracking:
                total_budget = float(tracking.get("total_budget", data.get("total_budget", 0)) or 0)
                currency = tracking.get("currency", data.get("currency", "USD"))
                notes = tracking.get("warnings", [])
                return cls(
                    total_budget=total_budget,
                    currency=currency,
                    allocations=allocations_from_items(tracking.get("by_category"), total_budget),
                    has_placeholders=False,
                    notes=notes,
                    budgeted_at=budgeted_at,
                )

            reallocation = data.get("reallocation") or {}
            if isinstance(reallocation, dict) and reallocation:
                currency = reallocation.get("currency", data.get("currency", "USD"))
                suggested = reallocation.get("suggested_allocations")
                original = reallocation.get("original_allocations")
                allocations = allocations_from_items(suggested, 0) or allocations_from_items(original, 0)
                total_budget = sum(a.amount for a in allocations)
                if total_budget:
                    for allocation in allocations:
                        allocation.percentage = allocation.amount / total_budget
                return cls(
                    total_budget=total_budget,
                    currency=currency,
                    allocations=allocations,
                    has_placeholders=False,
                    notes=reallocation.get("suggestions", []),
                    budgeted_at=budgeted_at,
                )

        return cls(
            total_budget=float(data.get("total_budget", 0)),
            currency=data.get("currency", "USD"),
            allocations=[CategoryAllocation.from_dict(a) for a in data.get("allocations", [])],
            has_placeholders=data.get("has_placeholders", False),
            notes=data.get("notes", []),
            budgeted_at=budgeted_at,
        )

    def get_allocation(self, category: str) -> CategoryAllocation | None:
        """Get allocation for a specific category."""
        for allocation in self.allocations:
            if allocation.category == category:
                return allocation
        return None

    def total_allocated(self) -> float:
        """Calculate total amount allocated across all categories."""
        return sum(a.amount for a in self.allocations)

    def remaining_budget(self) -> float:
        """Calculate remaining unallocated budget."""
        return self.total_budget - self.total_allocated()


# ═══════════════════════════════════════════════════════════════════════════════
# Budget Allocation Error
# ═══════════════════════════════════════════════════════════════════════════════


class BudgetAllocationError(Exception):
    """Raised when budget allocation cannot proceed.

    Per design doc, missing stay is a blocker that prevents budget allocation.
    """

    def __init__(self, message: str, blocker: str | None = None):
        """
        Initialize the error.

        Args:
            message: Human-readable error message
            blocker: The blocking issue (e.g., "missing_stay")
        """
        super().__init__(message)
        self.blocker = blocker


# ═══════════════════════════════════════════════════════════════════════════════
# Default Allocation Percentages
# ═══════════════════════════════════════════════════════════════════════════════


# Default allocation percentages when all data is available
DEFAULT_ALLOCATIONS = {
    "transport": 0.30,  # 30% for flights/trains
    "stay": 0.35,       # 35% for accommodation
    "activities": 0.20, # 20% for POI/events
    "dining": 0.10,     # 10% for restaurants
    "misc": 0.05,       # 5% for miscellaneous
}

# Transport placeholder range when transport discovery fails
TRANSPORT_PLACEHOLDER_MIN = 300
TRANSPORT_PLACEHOLDER_MAX = 800
TRANSPORT_PLACEHOLDER_NOTE = "Transport: TBD (~${min}-${max})"


# ═══════════════════════════════════════════════════════════════════════════════
# Budget Agent
# ═══════════════════════════════════════════════════════════════════════════════


class BudgetAgent:
    """
    Budget agent for allocating costs across trip categories.

    The Budget agent is the second agent in the planning pipeline. It receives
    aggregated results from the Aggregator and allocates the user's budget
    across categories.

    Per design doc "How Each Agent Handles Partial Discovery":
    - Missing transport: Reserve placeholder (~$300-800) using route-based estimates
    - Missing stay: **BLOCKER** - cannot allocate without stay costs
    - Missing POI: Reduce activities budget, note "fewer planned activities"

    The agent can operate in two modes:
    1. Stub mode (no A2A client): Uses local allocation logic
    2. Live mode (with A2A client): Calls the budget agent via A2A

    Example:
        budget = BudgetAgent(a2a_client, agent_registry)
        plan = await budget.allocate(aggregated, context, trip_spec)
    """

    def __init__(
        self,
        a2a_client: "A2AClientWrapper | None" = None,
        agent_registry: "AgentRegistry | None" = None,
    ):
        """
        Initialize the Budget agent.

        Args:
            a2a_client: A2A client for agent communication (optional for testing)
            agent_registry: Agent registry for URL lookup (optional for testing)
        """
        self._a2a_client = a2a_client
        self._agent_registry = agent_registry

    async def allocate(
        self,
        aggregated: AggregatedResults,
        discovery_context: DiscoveryContext,
        trip_spec: dict[str, Any] | None = None,
    ) -> BudgetPlan:
        """
        Allocate budget across trip categories.

        Per design doc "Downstream Pipeline with Partial Results":
        - Missing transport: Use placeholder estimate (~$300-800)
        - Missing stay: **BLOCKER** - raises BudgetAllocationError
        - Skipped stay: Allowed (user arranging own accommodation)
        - Missing POI: Reduce activities budget

        Args:
            aggregated: Aggregated results from the Aggregator
            discovery_context: Context with explicit gaps
            trip_spec: Trip requirements (budget, travelers, etc.)

        Returns:
            BudgetPlan with allocations for each category

        Raises:
            BudgetAllocationError: If stay data is missing and not skipped (blocker)
        """
        # Check for stay blocker FIRST
        # Note: SKIPPED stay is allowed (user arranging own accommodation)
        stay_is_skipped = aggregated.stay.status == "SKIPPED"
        if not aggregated.has_stay() and not stay_is_skipped:
            raise BudgetAllocationError(
                "Cannot allocate budget without accommodation cost information. "
                "Stay search must succeed before budget planning.",
                blocker="missing_stay",
            )

        if self._a2a_client is not None and self._agent_registry is not None:
            # Live mode: Call budget agent via A2A
            return await self._allocate_via_a2a(aggregated, discovery_context, trip_spec)

        # Stub mode: Use local allocation logic
        return self._allocate_locally(aggregated, discovery_context, trip_spec)

    async def _allocate_via_a2a(
        self,
        aggregated: AggregatedResults,
        discovery_context: DiscoveryContext,
        trip_spec: dict[str, Any] | None,
    ) -> BudgetPlan:
        """
        Call the budget agent via A2A.

        Args:
            aggregated: Aggregated results from Aggregator
            discovery_context: Context with explicit gaps
            trip_spec: Trip requirements

        Returns:
            BudgetPlan from the budget agent
        """
        assert self._a2a_client is not None
        assert self._agent_registry is not None

        # Get budget agent URL
        budget_config = self._agent_registry.get("budget")
        if budget_config is None:
            logger.warning("Budget agent not found in registry, using local allocation")
            return self._allocate_locally(aggregated, discovery_context, trip_spec)

        # Build request payload
        request_payload = {
            "aggregated": aggregated.to_dict(),
            "discovery_context": discovery_context.to_dict(),
            "trip_spec": trip_spec or {},
        }

        try:
            # Call budget agent
            response = await self._a2a_client.send_message(
                agent_url=budget_config.url,
                message=json.dumps(request_payload),
            )

            # Parse response
            if response.is_complete and response.text:
                try:
                    response_data = json.loads(response.text)
                    return BudgetPlan.from_dict(response_data)
                except json.JSONDecodeError:
                    logger.warning("Failed to parse budget response, using local allocation")
                    return self._allocate_locally(aggregated, discovery_context, trip_spec)

            # If not complete, fall back to local allocation
            logger.warning("Budget agent did not complete, using local allocation")
            return self._allocate_locally(aggregated, discovery_context, trip_spec)

        except Exception as e:
            logger.error(f"Budget agent call failed: {e}, using local allocation")
            return self._allocate_locally(aggregated, discovery_context, trip_spec)

    def _allocate_locally(
        self,
        aggregated: AggregatedResults,
        discovery_context: DiscoveryContext,
        trip_spec: dict[str, Any] | None,
    ) -> BudgetPlan:
        """
        Allocate budget using local logic.

        This is the stub implementation used when no A2A client is available.

        Args:
            aggregated: Aggregated results from Aggregator
            discovery_context: Context with explicit gaps
            trip_spec: Trip requirements

        Returns:
            BudgetPlan with allocations
        """
        # Extract budget info from trip_spec
        trip_spec = trip_spec or {}
        num_travelers = trip_spec.get("num_travelers", 1)
        budget_per_person = trip_spec.get("budget_per_person", 1000)
        total_budget = budget_per_person * num_travelers
        currency = trip_spec.get("budget_currency", "USD")

        allocations: list[CategoryAllocation] = []
        notes: list[str] = []
        has_placeholders = False

        # Check transport availability
        transport_gap = discovery_context.get_gap_for_agent("transport")
        if transport_gap or not aggregated.has_transport():
            # Transport missing - use placeholder estimate
            has_placeholders = True
            placeholder_amount = (TRANSPORT_PLACEHOLDER_MIN + TRANSPORT_PLACEHOLDER_MAX) / 2
            allocations.append(
                CategoryAllocation(
                    category="transport",
                    amount=placeholder_amount,
                    percentage=placeholder_amount / total_budget * 100 if total_budget > 0 else 0,
                    is_placeholder=True,
                    placeholder_note=f"Estimated ~${TRANSPORT_PLACEHOLDER_MIN}-${TRANSPORT_PLACEHOLDER_MAX} based on typical routes",
                )
            )
            notes.append(
                f"Transport budget is estimated at ~${TRANSPORT_PLACEHOLDER_MIN}-${TRANSPORT_PLACEHOLDER_MAX}. "
                "Actual costs will depend on booking."
            )
        else:
            # Transport available - allocate based on discovery
            transport_amount = total_budget * DEFAULT_ALLOCATIONS["transport"]
            transport_data = aggregated.transport.data or {}
            item_count = self._count_transport_options(transport_data)
            allocations.append(
                CategoryAllocation(
                    category="transport",
                    amount=transport_amount,
                    percentage=DEFAULT_ALLOCATIONS["transport"] * 100,
                    item_count=item_count,
                )
            )

        # Stay allocation (we already verified stay exists)
        stay_amount = total_budget * DEFAULT_ALLOCATIONS["stay"]
        stay_data = aggregated.stay.data or {}
        stay_item_count = self._count_stay_options(stay_data)
        allocations.append(
            CategoryAllocation(
                category="stay",
                amount=stay_amount,
                percentage=DEFAULT_ALLOCATIONS["stay"] * 100,
                item_count=stay_item_count,
            )
        )

        # Activities (POI + Events) allocation
        poi_gap = discovery_context.get_gap_for_agent("poi")
        events_gap = discovery_context.get_gap_for_agent("events")

        if poi_gap and events_gap:
            # Both missing - reduce activities budget
            activities_percentage = DEFAULT_ALLOCATIONS["activities"] * 0.5  # 50% reduction
            activities_amount = total_budget * activities_percentage
            allocations.append(
                CategoryAllocation(
                    category="activities",
                    amount=activities_amount,
                    percentage=activities_percentage * 100,
                    is_placeholder=True,
                    placeholder_note="Reduced budget due to limited activity recommendations",
                )
            )
            notes.append("Activities budget reduced due to limited attraction and event recommendations.")
        elif poi_gap or events_gap:
            # Partial - slight reduction
            activities_percentage = DEFAULT_ALLOCATIONS["activities"] * 0.75  # 25% reduction
            activities_amount = total_budget * activities_percentage
            allocations.append(
                CategoryAllocation(
                    category="activities",
                    amount=activities_amount,
                    percentage=activities_percentage * 100,
                    is_placeholder=True,
                    placeholder_note="Adjusted budget due to partial activity recommendations",
                )
            )
        else:
            # Both available
            activities_amount = total_budget * DEFAULT_ALLOCATIONS["activities"]
            poi_data = aggregated.poi.data or {}
            events_data = aggregated.events.data or {}
            poi_count = self._count_poi_options(poi_data)
            events_count = self._count_events_options(events_data)
            allocations.append(
                CategoryAllocation(
                    category="activities",
                    amount=activities_amount,
                    percentage=DEFAULT_ALLOCATIONS["activities"] * 100,
                    item_count=poi_count + events_count,
                )
            )

        # Dining allocation
        dining_gap = discovery_context.get_gap_for_agent("dining")
        if dining_gap:
            # Dining missing - slight reduction
            dining_percentage = DEFAULT_ALLOCATIONS["dining"] * 0.75
            dining_amount = total_budget * dining_percentage
            allocations.append(
                CategoryAllocation(
                    category="dining",
                    amount=dining_amount,
                    percentage=dining_percentage * 100,
                    is_placeholder=True,
                    placeholder_note="Estimated based on typical meal costs",
                )
            )
        else:
            dining_amount = total_budget * DEFAULT_ALLOCATIONS["dining"]
            dining_data = aggregated.dining.data or {}
            dining_count = self._count_dining_options(dining_data)
            allocations.append(
                CategoryAllocation(
                    category="dining",
                    amount=dining_amount,
                    percentage=DEFAULT_ALLOCATIONS["dining"] * 100,
                    item_count=dining_count,
                )
            )

        # Misc allocation
        misc_amount = total_budget * DEFAULT_ALLOCATIONS["misc"]
        allocations.append(
            CategoryAllocation(
                category="misc",
                amount=misc_amount,
                percentage=DEFAULT_ALLOCATIONS["misc"] * 100,
            )
        )

        # Add summary note about allocations
        total_allocated = sum(a.amount for a in allocations)
        if total_allocated > total_budget:
            notes.append(
                f"Note: Estimated allocations (${total_allocated:.2f}) exceed budget "
                f"(${total_budget:.2f}). Actual bookings may require adjustments."
            )

        return BudgetPlan(
            total_budget=total_budget,
            currency=currency,
            allocations=allocations,
            has_placeholders=has_placeholders,
            notes=notes,
        )

    def _count_transport_options(self, data: dict[str, Any]) -> int:
        """Count transport options from discovery data."""
        flights = data.get("flights", [])
        trains = data.get("trains", [])
        options = data.get("options", [])
        return len(flights) + len(trains) + len(options)

    def _count_stay_options(self, data: dict[str, Any]) -> int:
        """Count stay options from discovery data."""
        hotels = data.get("hotels", [])
        accommodations = data.get("accommodations", [])
        options = data.get("options", [])
        return len(hotels) + len(accommodations) + len(options)

    def _count_poi_options(self, data: dict[str, Any]) -> int:
        """Count POI options from discovery data."""
        attractions = data.get("attractions", [])
        landmarks = data.get("landmarks", [])
        options = data.get("options", [])
        return len(attractions) + len(landmarks) + len(options)

    def _count_events_options(self, data: dict[str, Any]) -> int:
        """Count events options from discovery data."""
        events = data.get("events", [])
        options = data.get("options", [])
        return len(events) + len(options)

    def _count_dining_options(self, data: dict[str, Any]) -> int:
        """Count dining options from discovery data."""
        restaurants = data.get("restaurants", [])
        options = data.get("options", [])
        return len(restaurants) + len(options)
