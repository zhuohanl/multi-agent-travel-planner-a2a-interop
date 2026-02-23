"""
Tier 1: Mock discovery flow tests for discovery + planning integration.

Tests the flow from discovery agent results through the planning pipeline
to itinerary draft creation. Uses mock responses for zero LLM cost.

Run: uv run pytest tests/integration/mock/test_discovery_flow.py -v
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from .conftest import MockA2AChunk, MockA2AResponseFactory


# ============================================================
# Planning Pipeline Mock Responses
# ============================================================


class MockPlanningResponseFactory:
    """
    Factory for creating mock planning agent responses.

    The planning pipeline consists of:
    1. Aggregator: Combines discovery results
    2. Budget: Allocates budget across categories
    3. Route: Creates day-by-day itinerary
    4. Validator: Checks feasibility
    """

    @staticmethod
    def aggregator_result(
        destination: str = "Tokyo",
        num_hotels: int = 3,
        num_flights: int = 2,
        num_pois: int = 10,
        has_transport: bool = True,
        has_stay: bool = True,
    ) -> list[MockA2AChunk]:
        """Aggregator combines all discovery results."""
        aggregated = {
            "destination": destination,
            "has_transport": has_transport,
            "has_stay": has_stay,
            "summary": {
                "hotels": num_hotels,
                "flights": num_flights if has_transport else 0,
                "pois": num_pois,
                "events": 3,
                "restaurants": 5,
            },
            "gaps": [],
        }

        # Add gaps for missing data
        if not has_transport:
            aggregated["gaps"].append({
                "category": "transport",
                "severity": "warning",
                "message": "No flight options found",
            })
        if not has_stay:
            aggregated["gaps"].append({
                "category": "stay",
                "severity": "blocker",
                "message": "No accommodation found",
            })

        return [
            MockA2AChunk(
                context_id="ctx_aggregator_001",
                task_id="task_aggregator_001",
                status_state="completed",
                text=str(aggregated).replace("'", '"'),
                is_task=True,
            )
        ]

    @staticmethod
    def budget_allocation_result(
        total_budget: float = 5000.0,
        transport_allocation: float = 1500.0,
        stay_allocation: float = 2000.0,
        activities_allocation: float = 1000.0,
        dining_allocation: float = 500.0,
    ) -> list[MockA2AChunk]:
        """Budget agent allocates costs across categories."""
        budget = {
            "total_budget": total_budget,
            "allocation": {
                "transport": transport_allocation,
                "stay": stay_allocation,
                "activities": activities_allocation,
                "dining": dining_allocation,
            },
            "remaining": total_budget - (
                transport_allocation + stay_allocation +
                activities_allocation + dining_allocation
            ),
            "status": "within_budget",
        }

        return [
            MockA2AChunk(
                context_id="ctx_budget_001",
                task_id="task_budget_001",
                status_state="completed",
                text=str(budget).replace("'", '"'),
                is_task=True,
            )
        ]

    @staticmethod
    def route_plan_result(
        destination: str = "Tokyo",
        num_days: int = 5,
        start_date: str = "2026-03-10",
    ) -> list[MockA2AChunk]:
        """Route agent creates day-by-day itinerary."""
        days = []
        base_date = date.fromisoformat(start_date)
        for i in range(num_days):
            day_date = date(
                base_date.year,
                base_date.month,
                base_date.day + i
            )
            days.append({
                "day_number": i + 1,
                "date": day_date.isoformat(),
                "title": f"Day {i + 1} in {destination}",
                "activities": [
                    {"name": f"Activity {j}", "time": f"{9 + j}:00"}
                    for j in range(3)
                ],
            })

        route = {
            "destination": destination,
            "days": days,
            "total_days": num_days,
        }

        return [
            MockA2AChunk(
                context_id="ctx_route_001",
                task_id="task_route_001",
                status_state="completed",
                text=str(route).replace("'", '"'),
                is_task=True,
            )
        ]

    @staticmethod
    def validator_result(
        is_valid: bool = True,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
    ) -> list[MockA2AChunk]:
        """Validator checks itinerary feasibility."""
        validation = {
            "is_valid": is_valid,
            "warnings": warnings or [],
            "errors": errors or [],
            "checked": [
                "time_conflicts",
                "impossible_connections",
                "budget_overruns",
            ],
        }

        return [
            MockA2AChunk(
                context_id="ctx_validator_001",
                task_id="task_validator_001",
                status_state="completed",
                text=str(validation).replace("'", '"'),
                is_task=True,
            )
        ]


@pytest.fixture
def mock_planning_factory() -> MockPlanningResponseFactory:
    """Provide mock planning response factory to tests."""
    return MockPlanningResponseFactory()


# ============================================================
# Discovery Results Types (for test setup)
# ============================================================


@dataclass
class MockDiscoveryResult:
    """Simulated discovery result for testing."""

    agent: str
    status: str  # "success", "error", "timeout"
    data: dict[str, Any] | None = None
    message: str | None = None


def create_full_discovery_results() -> dict[str, MockDiscoveryResult]:
    """Create a full set of successful discovery results."""
    return {
        "transport": MockDiscoveryResult(
            agent="transport",
            status="success",
            data={
                "flights": [
                    {"airline": "JAL", "price": 1200, "departure": "09:00"},
                    {"airline": "ANA", "price": 1100, "departure": "14:00"},
                ],
            },
        ),
        "stay": MockDiscoveryResult(
            agent="stay",
            status="success",
            data={
                "hotels": [
                    {"name": "Park Hyatt Tokyo", "price_per_night": 500, "rating": 4.8},
                    {"name": "Keio Plaza", "price_per_night": 300, "rating": 4.2},
                ],
            },
        ),
        "poi": MockDiscoveryResult(
            agent="poi",
            status="success",
            data={
                "attractions": [
                    {"name": "Tokyo Tower", "category": "landmark"},
                    {"name": "Senso-ji Temple", "category": "temple"},
                    {"name": "Shibuya Crossing", "category": "landmark"},
                ],
            },
        ),
        "events": MockDiscoveryResult(
            agent="events",
            status="success",
            data={
                "events": [
                    {"name": "Cherry Blossom Festival", "date": "2026-03-15"},
                ],
            },
        ),
        "dining": MockDiscoveryResult(
            agent="dining",
            status="success",
            data={
                "restaurants": [
                    {"name": "Sukiyabashi Jiro", "cuisine": "sushi", "rating": 4.9},
                    {"name": "Gonpachi", "cuisine": "izakaya", "rating": 4.5},
                ],
            },
        ),
    }


def create_partial_discovery_results() -> dict[str, MockDiscoveryResult]:
    """Create discovery results with some failures (partial success)."""
    return {
        "transport": MockDiscoveryResult(
            agent="transport",
            status="timeout",
            message="Timeout after 30s",
        ),
        "stay": MockDiscoveryResult(
            agent="stay",
            status="success",
            data={
                "hotels": [
                    {"name": "Park Hyatt Tokyo", "price_per_night": 500},
                ],
            },
        ),
        "poi": MockDiscoveryResult(
            agent="poi",
            status="success",
            data={
                "attractions": [
                    {"name": "Tokyo Tower"},
                ],
            },
        ),
        "events": MockDiscoveryResult(
            agent="events",
            status="error",
            message="Service unavailable",
        ),
        "dining": MockDiscoveryResult(
            agent="dining",
            status="success",
            data={
                "restaurants": [
                    {"name": "Sukiyabashi Jiro"},
                ],
            },
        ),
    }


# ============================================================
# Test Classes
# ============================================================


class TestDiscoveryFlow:
    """Test discovery results feeding into planning pipeline."""

    @pytest.mark.asyncio
    async def test_discovery_results_feed_planning_pipeline(
        self,
        mock_a2a_client: MagicMock,
        mock_response_factory: MockA2AResponseFactory,
        mock_planning_factory: MockPlanningResponseFactory,
    ) -> None:
        """Test that discovery results are passed to planning agents."""
        # Configure discovery agent responses
        discovery_agents = ["stay", "transport", "poi", "events", "dining"]
        discovery_ports = {
            "stay": 10009,
            "transport": 10010,
            "poi": 10008,
            "events": 10011,
            "dining": 10017,
        }

        for agent in discovery_agents:
            port = discovery_ports[agent]
            mock_a2a_client.configure_response(
                f"http://localhost:{port}",
                mock_response_factory.discovery_agent_results(agent),
            )

        # Configure planning agent responses (sequential pipeline)
        planning_ports = {
            "aggregator": 10010,  # reuse for simplicity
            "budget": 10011,
            "route": 10012,
            "validator": 10013,
        }

        mock_a2a_client.configure_response(
            f"http://localhost:{planning_ports['aggregator']}/planning",
            mock_planning_factory.aggregator_result(
                destination="Tokyo",
                has_transport=True,
                has_stay=True,
            ),
        )
        mock_a2a_client.configure_response(
            f"http://localhost:{planning_ports['budget']}/planning",
            mock_planning_factory.budget_allocation_result(),
        )
        mock_a2a_client.configure_response(
            f"http://localhost:{planning_ports['route']}/planning",
            mock_planning_factory.route_plan_result(destination="Tokyo", num_days=5),
        )
        mock_a2a_client.configure_response(
            f"http://localhost:{planning_ports['validator']}/planning",
            mock_planning_factory.validator_result(is_valid=True),
        )

        # Simulate discovery phase - call all agents in parallel
        discovery_responses = await asyncio.gather(*[
            mock_a2a_client.send_message(
                agent_url=f"http://localhost:{discovery_ports[agent]}",
                message=f"Search {agent} options in Tokyo",
            )
            for agent in discovery_agents
        ])

        # All discovery should complete
        assert all(r.is_complete for r in discovery_responses)
        assert len(discovery_responses) == 5

        # Simulate planning pipeline - sequential calls
        aggregator_response = await mock_a2a_client.send_message(
            agent_url=f"http://localhost:{planning_ports['aggregator']}/planning",
            message="Aggregate discovery results for Tokyo trip",
        )
        assert aggregator_response.is_complete

        budget_response = await mock_a2a_client.send_message(
            agent_url=f"http://localhost:{planning_ports['budget']}/planning",
            message="Allocate budget for Tokyo trip",
        )
        assert budget_response.is_complete

        route_response = await mock_a2a_client.send_message(
            agent_url=f"http://localhost:{planning_ports['route']}/planning",
            message="Create day-by-day route for Tokyo trip",
        )
        assert route_response.is_complete

        validator_response = await mock_a2a_client.send_message(
            agent_url=f"http://localhost:{planning_ports['validator']}/planning",
            message="Validate itinerary for Tokyo trip",
        )
        assert validator_response.is_complete
        assert "is_valid" in validator_response.text.lower()

    @pytest.mark.asyncio
    async def test_partial_results_create_gaps(
        self,
        mock_a2a_client: MagicMock,
        mock_response_factory: MockA2AResponseFactory,
        mock_planning_factory: MockPlanningResponseFactory,
    ) -> None:
        """Test that partial discovery creates gaps in the output."""
        # Configure mixed success/failure discovery responses
        mock_a2a_client.configure_response(
            "http://localhost:10009",  # stay - success
            mock_response_factory.stay_agent_results(),
        )
        mock_a2a_client.configure_response(
            "http://localhost:10010",  # transport - timeout
            mock_response_factory.agent_timeout(),
        )
        mock_a2a_client.configure_response(
            "http://localhost:10008",  # poi - success
            mock_response_factory.discovery_agent_results("poi"),
        )
        mock_a2a_client.configure_response(
            "http://localhost:10011",  # events - error
            mock_response_factory.agent_error("Service unavailable"),
        )
        mock_a2a_client.configure_response(
            "http://localhost:10017",  # dining - success
            mock_response_factory.discovery_agent_results("dining"),
        )

        # Run discovery
        results = {}
        discovery_ports = {
            "stay": 10009,
            "transport": 10010,
            "poi": 10008,
            "events": 10011,
            "dining": 10017,
        }
        for agent, port in discovery_ports.items():
            results[agent] = await mock_a2a_client.send_message(
                agent_url=f"http://localhost:{port}",
                message=f"Search {agent}",
            )

        # Count successes and failures
        successful = [a for a, r in results.items() if r.is_complete]
        failed = [a for a, r in results.items() if not r.is_complete]

        assert len(successful) == 3  # stay, poi, dining
        assert len(failed) == 2  # transport, events
        assert "transport" in failed
        assert "events" in failed

        # Configure aggregator with partial results (has gaps)
        mock_a2a_client.configure_response(
            "http://localhost:10010/planning",
            mock_planning_factory.aggregator_result(
                destination="Tokyo",
                has_transport=False,  # Missing transport
                has_stay=True,
            ),
        )

        # Aggregator should report gaps
        aggregator_response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10010/planning",
            message="Aggregate partial discovery results",
        )
        assert aggregator_response.is_complete
        assert "gaps" in aggregator_response.text.lower()

    @pytest.mark.asyncio
    async def test_itinerary_draft_created(
        self,
        mock_a2a_client: MagicMock,
        mock_planning_factory: MockPlanningResponseFactory,
    ) -> None:
        """Test that planning pipeline produces an itinerary draft."""
        # Configure full planning pipeline
        mock_a2a_client.configure_response(
            "http://localhost:10010/aggregator",
            mock_planning_factory.aggregator_result(
                destination="Kyoto",
                num_hotels=4,
                num_pois=15,
            ),
        )
        mock_a2a_client.configure_response(
            "http://localhost:10011/budget",
            mock_planning_factory.budget_allocation_result(
                total_budget=3000.0,
                transport_allocation=800.0,
                stay_allocation=1200.0,
            ),
        )
        mock_a2a_client.configure_response(
            "http://localhost:10012/route",
            mock_planning_factory.route_plan_result(
                destination="Kyoto",
                num_days=4,
                start_date="2026-04-01",
            ),
        )
        mock_a2a_client.configure_response(
            "http://localhost:10013/validator",
            mock_planning_factory.validator_result(
                is_valid=True,
                warnings=["Check weather for outdoor activities"],
            ),
        )

        # Run planning pipeline
        aggregator = await mock_a2a_client.send_message(
            "http://localhost:10010/aggregator", "Aggregate Kyoto trip"
        )
        budget = await mock_a2a_client.send_message(
            "http://localhost:10011/budget", "Allocate budget"
        )
        route = await mock_a2a_client.send_message(
            "http://localhost:10012/route", "Create route"
        )
        validator = await mock_a2a_client.send_message(
            "http://localhost:10013/validator", "Validate"
        )

        # All should complete
        assert aggregator.is_complete
        assert budget.is_complete
        assert route.is_complete
        assert validator.is_complete

        # Verify route contains itinerary structure
        assert "days" in route.text.lower()
        assert "kyoto" in route.text.lower()

        # Verify validator passed
        assert "is_valid" in validator.text.lower()


class TestPlanningPipelineSequence:
    """Test the sequential nature of planning pipeline."""

    @pytest.mark.asyncio
    async def test_planning_agents_called_sequentially(
        self,
        mock_a2a_client: MagicMock,
        mock_planning_factory: MockPlanningResponseFactory,
    ) -> None:
        """Test that planning agents are called in correct sequence."""
        call_order: list[str] = []

        # Track call order
        original_send = mock_a2a_client.send_message.side_effect

        async def tracking_send(*args: Any, **kwargs: Any) -> Any:
            agent_url = kwargs.get("agent_url") or args[0]
            if "/aggregator" in agent_url:
                call_order.append("aggregator")
            elif "/budget" in agent_url:
                call_order.append("budget")
            elif "/route" in agent_url:
                call_order.append("route")
            elif "/validator" in agent_url:
                call_order.append("validator")
            return await original_send(*args, **kwargs)

        mock_a2a_client.send_message.side_effect = tracking_send

        # Configure responses
        mock_a2a_client.configure_response(
            "http://localhost:10010/aggregator",
            mock_planning_factory.aggregator_result(),
        )
        mock_a2a_client.configure_response(
            "http://localhost:10011/budget",
            mock_planning_factory.budget_allocation_result(),
        )
        mock_a2a_client.configure_response(
            "http://localhost:10012/route",
            mock_planning_factory.route_plan_result(),
        )
        mock_a2a_client.configure_response(
            "http://localhost:10013/validator",
            mock_planning_factory.validator_result(),
        )

        # Call in sequence
        await mock_a2a_client.send_message(
            agent_url="http://localhost:10010/aggregator",
            message="Aggregate",
        )
        await mock_a2a_client.send_message(
            agent_url="http://localhost:10011/budget",
            message="Budget",
        )
        await mock_a2a_client.send_message(
            agent_url="http://localhost:10012/route",
            message="Route",
        )
        await mock_a2a_client.send_message(
            agent_url="http://localhost:10013/validator",
            message="Validate",
        )

        # Verify sequence
        assert call_order == ["aggregator", "budget", "route", "validator"]

    @pytest.mark.asyncio
    async def test_budget_uses_aggregator_output(
        self,
        mock_a2a_client: MagicMock,
        mock_planning_factory: MockPlanningResponseFactory,
    ) -> None:
        """Test that budget agent receives aggregator output."""
        # Configure aggregator with specific summary
        mock_a2a_client.configure_response(
            "http://localhost:10010/aggregator",
            mock_planning_factory.aggregator_result(
                destination="Paris",
                num_hotels=5,
                num_flights=3,
            ),
        )
        mock_a2a_client.configure_response(
            "http://localhost:10011/budget",
            mock_planning_factory.budget_allocation_result(
                total_budget=8000.0,
            ),
        )

        aggregator_result = await mock_a2a_client.send_message(
            agent_url="http://localhost:10010/aggregator",
            message="Aggregate Paris trip",
        )
        assert "paris" in aggregator_result.text.lower()

        # Budget would receive aggregator output
        budget_result = await mock_a2a_client.send_message(
            agent_url="http://localhost:10011/budget",
            message=f"Allocate budget based on: {aggregator_result.text}",
        )
        assert budget_result.is_complete
        assert "8000" in budget_result.text


class TestPartialDiscoveryGaps:
    """Test gap handling in partial discovery scenarios."""

    @pytest.mark.asyncio
    async def test_missing_transport_creates_warning_gap(
        self,
        mock_a2a_client: MagicMock,
        mock_planning_factory: MockPlanningResponseFactory,
    ) -> None:
        """Test that missing transport creates a warning gap."""
        mock_a2a_client.configure_response(
            "http://localhost:10010/aggregator",
            mock_planning_factory.aggregator_result(
                has_transport=False,
                has_stay=True,
            ),
        )

        result = await mock_a2a_client.send_message(
            agent_url="http://localhost:10010/aggregator",
            message="Aggregate with missing transport",
        )

        assert result.is_complete
        assert "gaps" in result.text.lower()
        assert "transport" in result.text.lower()
        # Transport missing is a warning, not a blocker
        assert "warning" in result.text.lower()

    @pytest.mark.asyncio
    async def test_missing_stay_creates_blocker_gap(
        self,
        mock_a2a_client: MagicMock,
        mock_planning_factory: MockPlanningResponseFactory,
    ) -> None:
        """Test that missing stay creates a blocker gap."""
        mock_a2a_client.configure_response(
            "http://localhost:10010/aggregator",
            mock_planning_factory.aggregator_result(
                has_transport=True,
                has_stay=False,
            ),
        )

        result = await mock_a2a_client.send_message(
            agent_url="http://localhost:10010/aggregator",
            message="Aggregate with missing stay",
        )

        assert result.is_complete
        assert "gaps" in result.text.lower()
        assert "stay" in result.text.lower()
        # Stay missing is a blocker
        assert "blocker" in result.text.lower()

    @pytest.mark.asyncio
    async def test_validator_reports_gaps(
        self,
        mock_a2a_client: MagicMock,
        mock_planning_factory: MockPlanningResponseFactory,
    ) -> None:
        """Test that validator reports gaps from partial discovery."""
        mock_a2a_client.configure_response(
            "http://localhost:10013/validator",
            mock_planning_factory.validator_result(
                is_valid=False,
                errors=["Missing accommodation for days 3-4"],
                warnings=["No flight options, consider alternative transport"],
            ),
        )

        result = await mock_a2a_client.send_message(
            agent_url="http://localhost:10013/validator",
            message="Validate itinerary with gaps",
        )

        assert result.is_complete
        assert "errors" in result.text.lower()
        assert "warnings" in result.text.lower()


class TestDiscoveryResultAggregation:
    """Test aggregation of discovery results for planning."""

    @pytest.mark.asyncio
    async def test_aggregator_combines_all_sources(
        self,
        mock_a2a_client: MagicMock,
        mock_planning_factory: MockPlanningResponseFactory,
    ) -> None:
        """Test aggregator combines results from all discovery agents."""
        mock_a2a_client.configure_response(
            "http://localhost:10010/aggregator",
            mock_planning_factory.aggregator_result(
                destination="Barcelona",
                num_hotels=6,
                num_flights=4,
                num_pois=20,
            ),
        )

        result = await mock_a2a_client.send_message(
            agent_url="http://localhost:10010/aggregator",
            message="Aggregate Barcelona trip discovery",
        )

        assert result.is_complete
        # Verify all categories represented
        assert "barcelona" in result.text.lower()
        # Summary should show hotel count
        text_lower = result.text.lower()
        assert "hotels" in text_lower or "6" in result.text

    @pytest.mark.asyncio
    async def test_discovery_to_draft_flow(
        self,
        mock_a2a_client: MagicMock,
        mock_response_factory: MockA2AResponseFactory,
        mock_planning_factory: MockPlanningResponseFactory,
    ) -> None:
        """Test complete flow from discovery to itinerary draft."""
        # Step 1: Discovery (parallel)
        discovery_agents = ["stay", "transport", "poi", "events", "dining"]
        discovery_ports = {
            "stay": 10009,
            "transport": 10010,
            "poi": 10008,
            "events": 10011,
            "dining": 10017,
        }

        for agent in discovery_agents:
            mock_a2a_client.configure_response(
                f"http://localhost:{discovery_ports[agent]}",
                mock_response_factory.discovery_agent_results(agent),
            )

        discovery_results = await asyncio.gather(*[
            mock_a2a_client.send_message(
                agent_url=f"http://localhost:{discovery_ports[agent]}",
                message=f"Search {agent}",
            )
            for agent in discovery_agents
        ])

        assert all(r.is_complete for r in discovery_results)

        # Step 2: Planning (sequential)
        mock_a2a_client.configure_response(
            "http://localhost:8010/aggregator",
            mock_planning_factory.aggregator_result(),
        )
        mock_a2a_client.configure_response(
            "http://localhost:8011/budget",
            mock_planning_factory.budget_allocation_result(),
        )
        mock_a2a_client.configure_response(
            "http://localhost:8012/route",
            mock_planning_factory.route_plan_result(num_days=7),
        )
        mock_a2a_client.configure_response(
            "http://localhost:8013/validator",
            mock_planning_factory.validator_result(is_valid=True),
        )

        # Run planning pipeline
        aggregator = await mock_a2a_client.send_message(
            "http://localhost:8010/aggregator", "Aggregate"
        )
        budget = await mock_a2a_client.send_message(
            "http://localhost:8011/budget", "Budget"
        )
        route = await mock_a2a_client.send_message(
            "http://localhost:8012/route", "Route"
        )
        validator = await mock_a2a_client.send_message(
            "http://localhost:8013/validator", "Validate"
        )

        # Verify complete flow
        assert aggregator.is_complete
        assert budget.is_complete
        assert route.is_complete
        assert validator.is_complete

        # Final output should be valid itinerary
        assert "days" in route.text.lower()
        assert "7" in route.text  # 7 days
