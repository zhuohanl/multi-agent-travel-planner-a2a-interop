"""
Unit tests for BudgetAgent.

Tests the Budget agent which allocates costs across trip categories based on
aggregated discovery results and trip requirements.

Per ORCH-077 acceptance criteria:
- BudgetAgent.allocate() produces budget allocation
- Missing transport uses placeholder estimate with note
- Missing stay is treated as blocker (raises error)
- Budget breakdown includes per-category allocation
- All unit tests pass
"""

from __future__ import annotations

from datetime import datetime, timezone
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
    BudgetAgent,
    BudgetAllocationError,
    BudgetPlan,
    CategoryAllocation,
    DEFAULT_ALLOCATIONS,
    TRANSPORT_PLACEHOLDER_MAX,
    TRANSPORT_PLACEHOLDER_MIN,
)
from src.orchestrator.planning.pipeline import (
    DiscoveryContext,
    DiscoveryGap,
    DiscoveryStatus,
)


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
                    {"airline": "JAL", "price": 1200, "departure": "09:00"},
                    {"airline": "ANA", "price": 1100, "departure": "14:00"},
                ],
            },
        ),
        stay=AgentResultEntry(
            status="SUCCESS",
            data={
                "hotels": [
                    {"name": "Park Hyatt Tokyo", "price_per_night": 500, "rating": 4.8},
                    {"name": "Keio Plaza", "price_per_night": 300, "rating": 4.2},
                ],
            },
        ),
        poi=AgentResultEntry(
            status="SUCCESS",
            data={
                "attractions": [
                    {"name": "Tokyo Tower", "category": "landmark"},
                    {"name": "Senso-ji Temple", "category": "temple"},
                ],
            },
        ),
        events=AgentResultEntry(
            status="SUCCESS",
            data={
                "events": [
                    {"name": "Cherry Blossom Festival", "date": "2026-03-15"},
                ],
            },
        ),
        dining=AgentResultEntry(
            status="SUCCESS",
            data={
                "restaurants": [
                    {"name": "Sukiyabashi Jiro", "cuisine": "sushi", "rating": 4.9},
                    {"name": "Gonpachi", "cuisine": "izakaya", "rating": 4.5},
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
            status="ERROR",
            data=None,
            message="Service unavailable",
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
            data={"hotels": [{"name": "Park Hyatt"}]},
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
def trip_spec() -> dict[str, Any]:
    """Sample trip specification."""
    return {
        "destination_city": "Tokyo",
        "origin_city": "New York",
        "start_date": "2026-03-10",
        "end_date": "2026-03-15",
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


# ═══════════════════════════════════════════════════════════════════════════════
# CategoryAllocation Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCategoryAllocation:
    """Tests for CategoryAllocation dataclass."""

    def test_create_basic_allocation(self) -> None:
        """Test creating a basic category allocation."""
        allocation = CategoryAllocation(
            category="transport",
            amount=3000.0,
            percentage=30.0,
        )
        assert allocation.category == "transport"
        assert allocation.amount == 3000.0
        assert allocation.percentage == 30.0
        assert allocation.is_placeholder is False
        assert allocation.placeholder_note is None
        assert allocation.item_count is None

    def test_create_placeholder_allocation(self) -> None:
        """Test creating a placeholder allocation."""
        allocation = CategoryAllocation(
            category="transport",
            amount=550.0,
            percentage=5.5,
            is_placeholder=True,
            placeholder_note="Estimated ~$300-$800 based on typical routes",
        )
        assert allocation.is_placeholder is True
        assert allocation.placeholder_note is not None
        assert "$300-$800" in allocation.placeholder_note

    def test_to_dict_basic(self) -> None:
        """Test serialization of basic allocation."""
        allocation = CategoryAllocation(
            category="stay",
            amount=3500.0,
            percentage=35.0,
            item_count=5,
        )
        result = allocation.to_dict()
        assert result == {
            "category": "stay",
            "amount": 3500.0,
            "percentage": 35.0,
            "is_placeholder": False,
            "item_count": 5,
        }

    def test_to_dict_with_placeholder(self) -> None:
        """Test serialization includes placeholder details."""
        allocation = CategoryAllocation(
            category="transport",
            amount=550.0,
            percentage=5.5,
            is_placeholder=True,
            placeholder_note="Estimated transport cost",
        )
        result = allocation.to_dict()
        assert result["is_placeholder"] is True
        assert result["placeholder_note"] == "Estimated transport cost"

    def test_from_dict(self) -> None:
        """Test deserialization of allocation."""
        data = {
            "category": "activities",
            "amount": 2000.0,
            "percentage": 20.0,
            "is_placeholder": True,
            "placeholder_note": "Reduced due to limited options",
            "item_count": 3,
        }
        allocation = CategoryAllocation.from_dict(data)
        assert allocation.category == "activities"
        assert allocation.amount == 2000.0
        assert allocation.percentage == 20.0
        assert allocation.is_placeholder is True
        assert allocation.placeholder_note == "Reduced due to limited options"
        assert allocation.item_count == 3

    def test_from_dict_defaults(self) -> None:
        """Test deserialization with missing fields uses defaults."""
        data = {
            "category": "misc",
            "amount": 500.0,
            "percentage": 5.0,
        }
        allocation = CategoryAllocation.from_dict(data)
        assert allocation.is_placeholder is False
        assert allocation.placeholder_note is None
        assert allocation.item_count is None


# ═══════════════════════════════════════════════════════════════════════════════
# BudgetPlan Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBudgetPlan:
    """Tests for BudgetPlan dataclass."""

    def test_create_budget_plan(self) -> None:
        """Test creating a budget plan."""
        plan = BudgetPlan(
            total_budget=10000.0,
            currency="USD",
            allocations=[
                CategoryAllocation(category="transport", amount=3000.0, percentage=30.0),
                CategoryAllocation(category="stay", amount=3500.0, percentage=35.0),
            ],
        )
        assert plan.total_budget == 10000.0
        assert plan.currency == "USD"
        assert len(plan.allocations) == 2
        assert plan.has_placeholders is False

    def test_get_allocation(self) -> None:
        """Test getting allocation by category."""
        plan = BudgetPlan(
            total_budget=10000.0,
            currency="USD",
            allocations=[
                CategoryAllocation(category="transport", amount=3000.0, percentage=30.0),
                CategoryAllocation(category="stay", amount=3500.0, percentage=35.0),
            ],
        )
        transport = plan.get_allocation("transport")
        assert transport is not None
        assert transport.amount == 3000.0

        missing = plan.get_allocation("nonexistent")
        assert missing is None

    def test_total_allocated(self) -> None:
        """Test total allocated calculation."""
        plan = BudgetPlan(
            total_budget=10000.0,
            currency="USD",
            allocations=[
                CategoryAllocation(category="transport", amount=3000.0, percentage=30.0),
                CategoryAllocation(category="stay", amount=3500.0, percentage=35.0),
                CategoryAllocation(category="activities", amount=2000.0, percentage=20.0),
            ],
        )
        assert plan.total_allocated() == 8500.0

    def test_remaining_budget(self) -> None:
        """Test remaining budget calculation."""
        plan = BudgetPlan(
            total_budget=10000.0,
            currency="USD",
            allocations=[
                CategoryAllocation(category="transport", amount=3000.0, percentage=30.0),
                CategoryAllocation(category="stay", amount=3500.0, percentage=35.0),
            ],
        )
        assert plan.remaining_budget() == 3500.0

    def test_to_dict(self) -> None:
        """Test serialization of budget plan."""
        plan = BudgetPlan(
            total_budget=10000.0,
            currency="USD",
            allocations=[
                CategoryAllocation(category="transport", amount=3000.0, percentage=30.0),
            ],
            has_placeholders=True,
            notes=["Transport estimate pending"],
        )
        result = plan.to_dict()

        assert result["total_budget"] == 10000.0
        assert result["currency"] == "USD"
        assert len(result["allocations"]) == 1
        assert result["has_placeholders"] is True
        assert "Transport estimate pending" in result["notes"]
        assert "budgeted_at" in result

    def test_from_dict(self) -> None:
        """Test deserialization of budget plan."""
        data = {
            "total_budget": 8000.0,
            "currency": "EUR",
            "allocations": [
                {"category": "stay", "amount": 2800.0, "percentage": 35.0, "is_placeholder": False},
            ],
            "has_placeholders": False,
            "notes": [],
            "budgeted_at": "2026-03-10T12:00:00+00:00",
        }
        plan = BudgetPlan.from_dict(data)

        assert plan.total_budget == 8000.0
        assert plan.currency == "EUR"
        assert len(plan.allocations) == 1
        assert plan.allocations[0].category == "stay"


# ═══════════════════════════════════════════════════════════════════════════════
# BudgetAllocationError Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBudgetAllocationError:
    """Tests for BudgetAllocationError exception."""

    def test_create_error(self) -> None:
        """Test creating a budget allocation error."""
        error = BudgetAllocationError(
            "Cannot allocate without stay costs",
            blocker="missing_stay",
        )
        assert "Cannot allocate without stay costs" in str(error)
        assert error.blocker == "missing_stay"

    def test_create_error_without_blocker(self) -> None:
        """Test creating error without blocker specified."""
        error = BudgetAllocationError("Generic error")
        assert "Generic error" in str(error)
        assert error.blocker is None


# ═══════════════════════════════════════════════════════════════════════════════
# BudgetAgent Tests - Core Functionality
# ═══════════════════════════════════════════════════════════════════════════════


class TestBudgetAgent:
    """Tests for BudgetAgent class."""

    @pytest.mark.asyncio
    async def test_allocate_with_full_results(
        self,
        full_aggregated_results: AggregatedResults,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that budget agent allocates correctly with full discovery."""
        agent = BudgetAgent()
        plan = await agent.allocate(
            aggregated=full_aggregated_results,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # Should have allocations for all categories
        assert len(plan.allocations) == 5
        categories = [a.category for a in plan.allocations]
        assert "transport" in categories
        assert "stay" in categories
        assert "activities" in categories
        assert "dining" in categories
        assert "misc" in categories

        # Total budget should be num_travelers * budget_per_person
        assert plan.total_budget == 10000.0  # 2 * 5000
        assert plan.currency == "USD"

        # No placeholders expected
        assert plan.has_placeholders is False

    @pytest.mark.asyncio
    async def test_allocate_respects_user_budget_constraint(
        self,
        full_aggregated_results: AggregatedResults,
        discovery_context_no_gaps: DiscoveryContext,
    ) -> None:
        """Test that budget agent respects user's budget constraint."""
        trip_spec = {
            "num_travelers": 1,
            "budget_per_person": 3000,
            "budget_currency": "EUR",
        }

        agent = BudgetAgent()
        plan = await agent.allocate(
            aggregated=full_aggregated_results,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        assert plan.total_budget == 3000.0
        assert plan.currency == "EUR"

    @pytest.mark.asyncio
    async def test_allocate_uses_placeholder_for_missing_transport(
        self,
        aggregated_missing_transport: AggregatedResults,
        discovery_context_with_transport_gap: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that missing transport results in placeholder estimate."""
        agent = BudgetAgent()
        plan = await agent.allocate(
            aggregated=aggregated_missing_transport,
            discovery_context=discovery_context_with_transport_gap,
            trip_spec=trip_spec,
        )

        # Should have placeholder for transport
        assert plan.has_placeholders is True

        transport = plan.get_allocation("transport")
        assert transport is not None
        assert transport.is_placeholder is True
        assert transport.placeholder_note is not None
        assert str(TRANSPORT_PLACEHOLDER_MIN) in transport.placeholder_note
        assert str(TRANSPORT_PLACEHOLDER_MAX) in transport.placeholder_note

        # Transport amount should be average of min/max
        expected_amount = (TRANSPORT_PLACEHOLDER_MIN + TRANSPORT_PLACEHOLDER_MAX) / 2
        assert transport.amount == expected_amount

        # Should have note about transport estimate
        assert any("Transport" in note for note in plan.notes)

    @pytest.mark.asyncio
    async def test_allocate_blocks_on_missing_stay(
        self,
        aggregated_missing_stay: AggregatedResults,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that missing stay raises BudgetAllocationError."""
        agent = BudgetAgent()

        with pytest.raises(BudgetAllocationError) as exc_info:
            await agent.allocate(
                aggregated=aggregated_missing_stay,
                discovery_context=discovery_context_no_gaps,
                trip_spec=trip_spec,
            )

        assert "stay" in str(exc_info.value).lower()
        assert exc_info.value.blocker == "missing_stay"

    @pytest.mark.asyncio
    async def test_allocate_reduces_activities_when_both_missing(
        self,
        aggregated_missing_all_activities: AggregatedResults,
        discovery_context_with_activity_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that missing POI and events reduces activities budget by 50%."""
        agent = BudgetAgent()
        plan = await agent.allocate(
            aggregated=aggregated_missing_all_activities,
            discovery_context=discovery_context_with_activity_gaps,
            trip_spec=trip_spec,
        )

        activities = plan.get_allocation("activities")
        assert activities is not None
        assert activities.is_placeholder is True

        # Activities should be at 50% of default (10% instead of 20%)
        expected_amount = plan.total_budget * DEFAULT_ALLOCATIONS["activities"] * 0.5
        assert activities.amount == expected_amount

        # Should have note about reduced budget
        assert any("activit" in note.lower() for note in plan.notes)

    @pytest.mark.asyncio
    async def test_allocate_with_partial_activity_gaps(
        self,
        full_aggregated_results: AggregatedResults,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that one missing activity agent reduces budget by 25%."""
        # Create context with only POI gap
        empty_results = DiscoveryResults()
        context = DiscoveryContext(
            results=empty_results,
            gaps=[
                DiscoveryGap(
                    agent="poi",
                    status=DiscoveryStatus.ERROR,
                    impact="Limited attractions",
                    user_action_required=False,
                ),
            ],
        )

        agent = BudgetAgent()
        plan = await agent.allocate(
            aggregated=full_aggregated_results,
            discovery_context=context,
            trip_spec=trip_spec,
        )

        activities = plan.get_allocation("activities")
        assert activities is not None
        assert activities.is_placeholder is True

        # Activities should be at 75% of default (15% instead of 20%)
        expected_amount = plan.total_budget * DEFAULT_ALLOCATIONS["activities"] * 0.75
        assert activities.amount == pytest.approx(expected_amount)

    @pytest.mark.asyncio
    async def test_allocate_includes_item_counts(
        self,
        full_aggregated_results: AggregatedResults,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that allocations include item counts from discovery."""
        agent = BudgetAgent()
        plan = await agent.allocate(
            aggregated=full_aggregated_results,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        transport = plan.get_allocation("transport")
        assert transport is not None
        assert transport.item_count == 2  # 2 flights

        stay = plan.get_allocation("stay")
        assert stay is not None
        assert stay.item_count == 2  # 2 hotels

        dining = plan.get_allocation("dining")
        assert dining is not None
        assert dining.item_count == 2  # 2 restaurants

    @pytest.mark.asyncio
    async def test_allocate_handles_no_trip_spec(
        self,
        full_aggregated_results: AggregatedResults,
        discovery_context_no_gaps: DiscoveryContext,
    ) -> None:
        """Test that budget agent works with missing trip_spec."""
        agent = BudgetAgent()
        plan = await agent.allocate(
            aggregated=full_aggregated_results,
            discovery_context=discovery_context_no_gaps,
            trip_spec=None,
        )

        # Should use defaults: 1 traveler * $1000 = $1000
        assert plan.total_budget == 1000.0
        assert plan.currency == "USD"

    @pytest.mark.asyncio
    async def test_allocate_percentages_follow_defaults(
        self,
        full_aggregated_results: AggregatedResults,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that allocations follow default percentages."""
        agent = BudgetAgent()
        plan = await agent.allocate(
            aggregated=full_aggregated_results,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        transport = plan.get_allocation("transport")
        assert transport is not None
        assert transport.percentage == DEFAULT_ALLOCATIONS["transport"] * 100

        stay = plan.get_allocation("stay")
        assert stay is not None
        assert stay.percentage == DEFAULT_ALLOCATIONS["stay"] * 100

        misc = plan.get_allocation("misc")
        assert misc is not None
        assert misc.percentage == DEFAULT_ALLOCATIONS["misc"] * 100

    @pytest.mark.asyncio
    async def test_allocate_warns_when_over_budget(
        self,
        full_aggregated_results: AggregatedResults,
        discovery_context_with_transport_gap: DiscoveryContext,
    ) -> None:
        """Test warning when allocations exceed budget."""
        # Use a small budget that will be exceeded by transport placeholder
        trip_spec = {
            "num_travelers": 1,
            "budget_per_person": 500,  # Very small
            "budget_currency": "USD",
        }

        agent = BudgetAgent()
        plan = await agent.allocate(
            aggregated=full_aggregated_results,
            discovery_context=discovery_context_with_transport_gap,
            trip_spec=trip_spec,
        )

        # Total allocated will exceed budget due to transport placeholder
        assert plan.total_allocated() > plan.total_budget
        assert any("exceed" in note.lower() for note in plan.notes)


# ═══════════════════════════════════════════════════════════════════════════════
# BudgetAgent A2A Integration Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBudgetAgentA2A:
    """Tests for BudgetAgent A2A integration."""

    @pytest.fixture
    def mock_a2a_client(self) -> AsyncMock:
        """Create mock A2A client."""
        client = AsyncMock()
        return client

    @pytest.fixture
    def mock_agent_registry(self) -> MagicMock:
        """Create mock agent registry."""
        registry = MagicMock()
        budget_config = MagicMock()
        budget_config.url = "http://localhost:8011"
        budget_config.timeout = 60
        registry.get.return_value = budget_config
        return registry

    @pytest.mark.asyncio
    async def test_budget_calls_a2a_when_available(
        self,
        mock_a2a_client: AsyncMock,
        mock_agent_registry: MagicMock,
        full_aggregated_results: AggregatedResults,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that budget agent calls A2A client when available."""
        # Configure mock response
        mock_response = MagicMock()
        mock_response.is_complete = True
        mock_response.text = '''{
            "total_budget": 10000,
            "currency": "USD",
            "allocations": [
                {"category": "transport", "amount": 3000, "percentage": 30, "is_placeholder": false}
            ],
            "has_placeholders": false,
            "notes": []
        }'''
        mock_a2a_client.send_message.return_value = mock_response

        agent = BudgetAgent(
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        plan = await agent.allocate(
            aggregated=full_aggregated_results,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # Verify A2A client was called
        mock_a2a_client.send_message.assert_called_once()
        call_kwargs = mock_a2a_client.send_message.call_args.kwargs
        assert call_kwargs["agent_url"] == "http://localhost:8011"
        assert call_kwargs["timeout"] == 60

    @pytest.mark.asyncio
    async def test_budget_falls_back_on_a2a_error(
        self,
        mock_a2a_client: AsyncMock,
        mock_agent_registry: MagicMock,
        full_aggregated_results: AggregatedResults,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that budget agent falls back to local on A2A error."""
        # Configure mock to raise exception
        mock_a2a_client.send_message.side_effect = Exception("Connection failed")

        agent = BudgetAgent(
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        plan = await agent.allocate(
            aggregated=full_aggregated_results,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # Should still get valid plan from local fallback
        assert plan.total_budget == 10000.0
        assert len(plan.allocations) == 5

    @pytest.mark.asyncio
    async def test_budget_falls_back_on_incomplete_response(
        self,
        mock_a2a_client: AsyncMock,
        mock_agent_registry: MagicMock,
        full_aggregated_results: AggregatedResults,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that budget agent falls back when A2A response is incomplete."""
        # Configure mock to return incomplete response
        mock_response = MagicMock()
        mock_response.is_complete = False
        mock_response.text = ""
        mock_a2a_client.send_message.return_value = mock_response

        agent = BudgetAgent(
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        plan = await agent.allocate(
            aggregated=full_aggregated_results,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # Should still get valid plan from local fallback
        assert plan.total_budget == 10000.0

    @pytest.mark.asyncio
    async def test_budget_falls_back_on_missing_registry_entry(
        self,
        mock_a2a_client: AsyncMock,
        full_aggregated_results: AggregatedResults,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that budget agent falls back when not in registry."""
        # Configure registry to return None
        mock_registry = MagicMock()
        mock_registry.get.return_value = None

        agent = BudgetAgent(
            a2a_client=mock_a2a_client,
            agent_registry=mock_registry,
        )

        plan = await agent.allocate(
            aggregated=full_aggregated_results,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # Should still get valid plan from local fallback
        assert plan.total_budget == 10000.0

        # A2A client should not be called
        mock_a2a_client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_budget_falls_back_on_invalid_json(
        self,
        mock_a2a_client: AsyncMock,
        mock_agent_registry: MagicMock,
        full_aggregated_results: AggregatedResults,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that budget agent falls back on invalid JSON response."""
        # Configure mock to return invalid JSON
        mock_response = MagicMock()
        mock_response.is_complete = True
        mock_response.text = "not valid json"
        mock_a2a_client.send_message.return_value = mock_response

        agent = BudgetAgent(
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        plan = await agent.allocate(
            aggregated=full_aggregated_results,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # Should still get valid plan from local fallback
        assert plan.total_budget == 10000.0

    @pytest.mark.asyncio
    async def test_budget_still_checks_stay_blocker_before_a2a(
        self,
        mock_a2a_client: AsyncMock,
        mock_agent_registry: MagicMock,
        aggregated_missing_stay: AggregatedResults,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that missing stay blocks before even attempting A2A call."""
        agent = BudgetAgent(
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        with pytest.raises(BudgetAllocationError) as exc_info:
            await agent.allocate(
                aggregated=aggregated_missing_stay,
                discovery_context=discovery_context_no_gaps,
                trip_spec=trip_spec,
            )

        # A2A should NOT have been called since stay is a blocker
        mock_a2a_client.send_message.assert_not_called()
        assert exc_info.value.blocker == "missing_stay"
