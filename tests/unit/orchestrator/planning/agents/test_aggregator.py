"""
Unit tests for AggregatorAgent.

Tests the Aggregator agent which combines discovery results from 5 domain agents
into a structured format for downstream planning.

Per ORCH-076 acceptance criteria:
- AggregatorAgent.aggregate() combines discovery results
- Missing agents are included with their status (ERROR, NOT_FOUND, SKIPPED)
- Output is structured for Budget agent consumption
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
    AggregatorAgent,
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
def full_discovery_results() -> DiscoveryResults:
    """Create complete successful discovery results."""
    return DiscoveryResults(
        transport=AgentDiscoveryResult(
            agent="transport",
            status="success",
            data={
                "flights": [
                    {"airline": "JAL", "price": 1200, "departure": "09:00"},
                    {"airline": "ANA", "price": 1100, "departure": "14:00"},
                ],
            },
        ),
        stay=AgentDiscoveryResult(
            agent="stay",
            status="success",
            data={
                "hotels": [
                    {"name": "Park Hyatt Tokyo", "price_per_night": 500, "rating": 4.8},
                    {"name": "Keio Plaza", "price_per_night": 300, "rating": 4.2},
                ],
            },
        ),
        poi=AgentDiscoveryResult(
            agent="poi",
            status="success",
            data={
                "attractions": [
                    {"name": "Tokyo Tower", "category": "landmark"},
                    {"name": "Senso-ji Temple", "category": "temple"},
                ],
            },
        ),
        events=AgentDiscoveryResult(
            agent="events",
            status="success",
            data={
                "events": [
                    {"name": "Cherry Blossom Festival", "date": "2026-03-15"},
                ],
            },
        ),
        dining=AgentDiscoveryResult(
            agent="dining",
            status="success",
            data={
                "restaurants": [
                    {"name": "Sukiyabashi Jiro", "cuisine": "sushi", "rating": 4.9},
                    {"name": "Gonpachi", "cuisine": "izakaya", "rating": 4.5},
                ],
            },
        ),
    )


@pytest.fixture
def partial_discovery_results() -> DiscoveryResults:
    """Create partial discovery results with some failures."""
    return DiscoveryResults(
        transport=AgentDiscoveryResult(
            agent="transport",
            status="timeout",
            message="Timeout after 30s",
        ),
        stay=AgentDiscoveryResult(
            agent="stay",
            status="success",
            data={
                "hotels": [
                    {"name": "Park Hyatt Tokyo", "price_per_night": 500},
                ],
            },
        ),
        poi=AgentDiscoveryResult(
            agent="poi",
            status="success",
            data={
                "attractions": [
                    {"name": "Tokyo Tower"},
                ],
            },
        ),
        events=AgentDiscoveryResult(
            agent="events",
            status="error",
            message="Service unavailable",
        ),
        dining=AgentDiscoveryResult(
            agent="dining",
            status="success",
            data={
                "restaurants": [
                    {"name": "Sukiyabashi Jiro"},
                ],
            },
        ),
    )


@pytest.fixture
def missing_stay_results() -> DiscoveryResults:
    """Create discovery results with missing stay (blocker)."""
    return DiscoveryResults(
        transport=AgentDiscoveryResult(
            agent="transport",
            status="success",
            data={"flights": [{"airline": "JAL", "price": 1200}]},
        ),
        stay=AgentDiscoveryResult(
            agent="stay",
            status="error",
            message="No hotels found",
        ),
        poi=AgentDiscoveryResult(
            agent="poi",
            status="success",
            data={"attractions": [{"name": "Tokyo Tower"}]},
        ),
        events=None,
        dining=None,
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
def discovery_context_no_gaps(full_discovery_results: DiscoveryResults) -> DiscoveryContext:
    """Discovery context with no gaps."""
    return DiscoveryContext(
        results=full_discovery_results,
        gaps=[],
    )


@pytest.fixture
def discovery_context_with_gaps(partial_discovery_results: DiscoveryResults) -> DiscoveryContext:
    """Discovery context with gaps."""
    return DiscoveryContext(
        results=partial_discovery_results,
        gaps=[
            DiscoveryGap(
                agent="transport",
                status=DiscoveryStatus.TIMEOUT,
                impact="Arrival and departure times unknown",
                placeholder_strategy="Itinerary assumes 2pm arrival Day 1, 11am departure final day",
                user_action_required=True,
            ),
            DiscoveryGap(
                agent="events",
                status=DiscoveryStatus.ERROR,
                impact="No local events included",
                placeholder_strategy="Events are optional enhancements",
                user_action_required=False,
            ),
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# AgentResultEntry Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentResultEntry:
    """Tests for AgentResultEntry dataclass."""

    def test_create_success_entry(self) -> None:
        """Test creating a successful result entry."""
        entry = AgentResultEntry(
            status="SUCCESS",
            data={"hotels": [{"name": "Test Hotel"}]},
        )
        assert entry.status == "SUCCESS"
        assert entry.data == {"hotels": [{"name": "Test Hotel"}]}
        assert entry.message is None

    def test_create_error_entry(self) -> None:
        """Test creating an error result entry."""
        entry = AgentResultEntry(
            status="ERROR",
            data=None,
            message="Connection failed",
        )
        assert entry.status == "ERROR"
        assert entry.data is None
        assert entry.message == "Connection failed"

    def test_to_dict_success(self) -> None:
        """Test serialization of success entry."""
        entry = AgentResultEntry(
            status="SUCCESS",
            data={"flights": [{"airline": "JAL"}]},
        )
        result = entry.to_dict()
        assert result == {
            "status": "SUCCESS",
            "data": {"flights": [{"airline": "JAL"}]},
        }

    def test_to_dict_with_message(self) -> None:
        """Test serialization includes message when present."""
        entry = AgentResultEntry(
            status="ERROR",
            data=None,
            message="Timeout occurred",
        )
        result = entry.to_dict()
        assert result == {
            "status": "ERROR",
            "data": None,
            "message": "Timeout occurred",
        }

    def test_from_dict_success(self) -> None:
        """Test deserialization of success entry."""
        data = {
            "status": "SUCCESS",
            "data": {"hotels": [{"name": "Park Hyatt"}]},
        }
        entry = AgentResultEntry.from_dict(data)
        assert entry.status == "SUCCESS"
        assert entry.data == {"hotels": [{"name": "Park Hyatt"}]}
        assert entry.message is None

    def test_from_dict_with_invalid_status(self) -> None:
        """Test deserialization handles invalid status."""
        data = {
            "status": "UNKNOWN_STATUS",
            "data": None,
        }
        entry = AgentResultEntry.from_dict(data)
        assert entry.status == "ERROR"  # Falls back to ERROR

    def test_from_dict_empty(self) -> None:
        """Test deserialization of empty dict."""
        entry = AgentResultEntry.from_dict({})
        assert entry.status == "ERROR"
        assert entry.data is None
        assert entry.message is None


# ═══════════════════════════════════════════════════════════════════════════════
# AggregatedResults Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestAggregatedResults:
    """Tests for AggregatedResults dataclass."""

    def test_create_aggregated_results(self) -> None:
        """Test creating aggregated results."""
        results = AggregatedResults(
            transport=AgentResultEntry(status="SUCCESS", data={"flights": []}),
            stay=AgentResultEntry(status="SUCCESS", data={"hotels": []}),
            poi=AgentResultEntry(status="SUCCESS", data={"attractions": []}),
            events=AgentResultEntry(status="ERROR", data=None),
            dining=AgentResultEntry(status="SUCCESS", data={"restaurants": []}),
            destination="Tokyo",
        )
        assert results.destination == "Tokyo"
        assert results.transport.status == "SUCCESS"
        assert results.events.status == "ERROR"

    def test_has_gaps(self) -> None:
        """Test has_gaps() method."""
        results_no_gaps = AggregatedResults(
            transport=AgentResultEntry(status="SUCCESS", data=None),
            stay=AgentResultEntry(status="SUCCESS", data=None),
            poi=AgentResultEntry(status="SUCCESS", data=None),
            events=AgentResultEntry(status="SUCCESS", data=None),
            dining=AgentResultEntry(status="SUCCESS", data=None),
            gaps=[],
        )
        assert results_no_gaps.has_gaps() is False

        results_with_gaps = AggregatedResults(
            transport=AgentResultEntry(status="SUCCESS", data=None),
            stay=AgentResultEntry(status="SUCCESS", data=None),
            poi=AgentResultEntry(status="SUCCESS", data=None),
            events=AgentResultEntry(status="SUCCESS", data=None),
            dining=AgentResultEntry(status="SUCCESS", data=None),
            gaps=[
                DiscoveryGap(
                    agent="transport",
                    status=DiscoveryStatus.TIMEOUT,
                    impact="Flights unavailable",
                )
            ],
        )
        assert results_with_gaps.has_gaps() is True

    def test_has_critical_gaps(self) -> None:
        """Test has_critical_gaps() method."""
        non_critical_gap = DiscoveryGap(
            agent="events",
            status=DiscoveryStatus.ERROR,
            impact="Events unavailable",
            user_action_required=False,
        )
        critical_gap = DiscoveryGap(
            agent="transport",
            status=DiscoveryStatus.TIMEOUT,
            impact="Flights unavailable",
            user_action_required=True,
        )

        results_non_critical = AggregatedResults(
            transport=AgentResultEntry(status="SUCCESS", data=None),
            stay=AgentResultEntry(status="SUCCESS", data=None),
            poi=AgentResultEntry(status="SUCCESS", data=None),
            events=AgentResultEntry(status="SUCCESS", data=None),
            dining=AgentResultEntry(status="SUCCESS", data=None),
            gaps=[non_critical_gap],
        )
        assert results_non_critical.has_critical_gaps() is False

        results_critical = AggregatedResults(
            transport=AgentResultEntry(status="SUCCESS", data=None),
            stay=AgentResultEntry(status="SUCCESS", data=None),
            poi=AgentResultEntry(status="SUCCESS", data=None),
            events=AgentResultEntry(status="SUCCESS", data=None),
            dining=AgentResultEntry(status="SUCCESS", data=None),
            gaps=[non_critical_gap, critical_gap],
        )
        assert results_critical.has_critical_gaps() is True

    def test_has_transport(self) -> None:
        """Test has_transport() method."""
        with_transport = AggregatedResults(
            transport=AgentResultEntry(status="SUCCESS", data={"flights": [{"airline": "JAL"}]}),
            stay=AgentResultEntry(status="SUCCESS", data=None),
            poi=AgentResultEntry(status="SUCCESS", data=None),
            events=AgentResultEntry(status="SUCCESS", data=None),
            dining=AgentResultEntry(status="SUCCESS", data=None),
        )
        assert with_transport.has_transport() is True

        without_transport = AggregatedResults(
            transport=AgentResultEntry(status="TIMEOUT", data=None),
            stay=AgentResultEntry(status="SUCCESS", data=None),
            poi=AgentResultEntry(status="SUCCESS", data=None),
            events=AgentResultEntry(status="SUCCESS", data=None),
            dining=AgentResultEntry(status="SUCCESS", data=None),
        )
        assert without_transport.has_transport() is False

    def test_has_stay(self) -> None:
        """Test has_stay() method."""
        with_stay = AggregatedResults(
            transport=AgentResultEntry(status="SUCCESS", data=None),
            stay=AgentResultEntry(status="SUCCESS", data={"hotels": [{"name": "Hotel"}]}),
            poi=AgentResultEntry(status="SUCCESS", data=None),
            events=AgentResultEntry(status="SUCCESS", data=None),
            dining=AgentResultEntry(status="SUCCESS", data=None),
        )
        assert with_stay.has_stay() is True

        without_stay = AggregatedResults(
            transport=AgentResultEntry(status="SUCCESS", data=None),
            stay=AgentResultEntry(status="ERROR", data=None),
            poi=AgentResultEntry(status="SUCCESS", data=None),
            events=AgentResultEntry(status="SUCCESS", data=None),
            dining=AgentResultEntry(status="SUCCESS", data=None),
        )
        assert without_stay.has_stay() is False

    def test_to_dict(self) -> None:
        """Test serialization of aggregated results."""
        results = AggregatedResults(
            transport=AgentResultEntry(status="SUCCESS", data={"flights": []}),
            stay=AgentResultEntry(status="SUCCESS", data={"hotels": []}),
            poi=AgentResultEntry(status="SUCCESS", data={}),
            events=AgentResultEntry(status="SUCCESS", data={}),
            dining=AgentResultEntry(status="SUCCESS", data={}),
            destination="Tokyo",
            summary={"transport_options": 2, "stay_options": 3},
        )
        result = results.to_dict()

        assert result["transport"]["status"] == "SUCCESS"
        assert result["stay"]["status"] == "SUCCESS"
        assert result["destination"] == "Tokyo"
        assert result["summary"] == {"transport_options": 2, "stay_options": 3}
        assert "aggregated_at" in result

    def test_from_dict(self) -> None:
        """Test deserialization of aggregated results."""
        data = {
            "transport": {"status": "SUCCESS", "data": {"flights": []}},
            "stay": {"status": "SUCCESS", "data": {"hotels": []}},
            "poi": {"status": "ERROR", "data": None, "message": "Failed"},
            "events": {"status": "SUCCESS", "data": {}},
            "dining": {"status": "SUCCESS", "data": {}},
            "destination": "Paris",
            "summary": {"transport_options": 5},
            "gaps": [
                {
                    "agent": "poi",
                    "status": "error",
                    "impact": "Limited attractions",
                    "user_action_required": False,
                }
            ],
        }
        results = AggregatedResults.from_dict(data)

        assert results.transport.status == "SUCCESS"
        assert results.poi.status == "ERROR"
        assert results.poi.message == "Failed"
        assert results.destination == "Paris"
        assert len(results.gaps) == 1
        assert results.gaps[0].agent == "poi"


# ═══════════════════════════════════════════════════════════════════════════════
# AggregatorAgent Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestAggregatorAgent:
    """Tests for AggregatorAgent class."""

    @pytest.mark.asyncio
    async def test_aggregate_combines_all_results(
        self,
        full_discovery_results: DiscoveryResults,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that aggregator combines results from all agents."""
        aggregator = AggregatorAgent()
        result = await aggregator.aggregate(
            discovery_results=full_discovery_results,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # All agents should have SUCCESS status
        assert result.transport.status == "SUCCESS"
        assert result.stay.status == "SUCCESS"
        assert result.poi.status == "SUCCESS"
        assert result.events.status == "SUCCESS"
        assert result.dining.status == "SUCCESS"

        # Data should be preserved
        assert result.transport.data is not None
        assert "flights" in result.transport.data
        assert len(result.transport.data["flights"]) == 2

        assert result.stay.data is not None
        assert "hotels" in result.stay.data
        assert len(result.stay.data["hotels"]) == 2

    @pytest.mark.asyncio
    async def test_aggregator_handles_missing_transport(
        self,
        partial_discovery_results: DiscoveryResults,
        discovery_context_with_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that aggregator handles missing transport with TIMEOUT status."""
        aggregator = AggregatorAgent()
        result = await aggregator.aggregate(
            discovery_results=partial_discovery_results,
            discovery_context=discovery_context_with_gaps,
            trip_spec=trip_spec,
        )

        # Transport should have TIMEOUT status
        assert result.transport.status == "TIMEOUT"
        assert result.transport.data is None
        assert result.transport.message is not None

        # Stay should still be successful
        assert result.stay.status == "SUCCESS"
        assert result.stay.data is not None

    @pytest.mark.asyncio
    async def test_aggregator_handles_missing_stay(
        self,
        missing_stay_results: DiscoveryResults,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that aggregator handles missing stay with ERROR status."""
        context = DiscoveryContext(
            results=missing_stay_results,
            gaps=[
                DiscoveryGap(
                    agent="stay",
                    status=DiscoveryStatus.ERROR,
                    impact="Cannot plan without accommodation",
                    user_action_required=True,
                )
            ],
        )

        aggregator = AggregatorAgent()
        result = await aggregator.aggregate(
            discovery_results=missing_stay_results,
            discovery_context=context,
            trip_spec=trip_spec,
        )

        # Stay should have ERROR status
        assert result.stay.status == "ERROR"
        assert result.stay.data is None

        # Transport should still be successful
        assert result.transport.status == "SUCCESS"
        assert result.transport.data is not None

    @pytest.mark.asyncio
    async def test_aggregator_preserves_status_for_errors(
        self,
        partial_discovery_results: DiscoveryResults,
        discovery_context_with_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that aggregator preserves error status correctly."""
        aggregator = AggregatorAgent()
        result = await aggregator.aggregate(
            discovery_results=partial_discovery_results,
            discovery_context=discovery_context_with_gaps,
            trip_spec=trip_spec,
        )

        # Verify each agent's status is correctly mapped
        assert result.transport.status == "TIMEOUT"  # from "timeout"
        assert result.stay.status == "SUCCESS"  # from "success"
        assert result.poi.status == "SUCCESS"  # from "success"
        assert result.events.status == "ERROR"  # from "error"
        assert result.dining.status == "SUCCESS"  # from "success"

    @pytest.mark.asyncio
    async def test_aggregator_includes_gaps(
        self,
        partial_discovery_results: DiscoveryResults,
        discovery_context_with_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that aggregator includes gaps in output."""
        aggregator = AggregatorAgent()
        result = await aggregator.aggregate(
            discovery_results=partial_discovery_results,
            discovery_context=discovery_context_with_gaps,
            trip_spec=trip_spec,
        )

        # Should have gaps from context
        assert len(result.gaps) == 2
        gap_agents = [g.agent for g in result.gaps]
        assert "transport" in gap_agents
        assert "events" in gap_agents

    @pytest.mark.asyncio
    async def test_aggregator_sets_destination(
        self,
        full_discovery_results: DiscoveryResults,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that aggregator extracts destination from trip_spec."""
        aggregator = AggregatorAgent()
        result = await aggregator.aggregate(
            discovery_results=full_discovery_results,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        assert result.destination == "Tokyo"

    @pytest.mark.asyncio
    async def test_aggregator_builds_summary(
        self,
        full_discovery_results: DiscoveryResults,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that aggregator builds summary counts."""
        aggregator = AggregatorAgent()
        result = await aggregator.aggregate(
            discovery_results=full_discovery_results,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # Check summary counts
        assert "transport_options" in result.summary
        assert "stay_options" in result.summary
        assert "poi_options" in result.summary
        assert "events_options" in result.summary
        assert "dining_options" in result.summary

        # Verify actual counts
        assert result.summary["transport_options"] == 2  # 2 flights
        assert result.summary["stay_options"] == 2  # 2 hotels
        assert result.summary["poi_options"] == 2  # 2 attractions
        assert result.summary["events_options"] == 1  # 1 event
        assert result.summary["dining_options"] == 2  # 2 restaurants

    @pytest.mark.asyncio
    async def test_aggregator_handles_null_results(
        self,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that aggregator handles null agent results."""
        empty_results = DiscoveryResults()
        context = DiscoveryContext(results=empty_results, gaps=[])

        aggregator = AggregatorAgent()
        result = await aggregator.aggregate(
            discovery_results=empty_results,
            discovery_context=context,
            trip_spec=trip_spec,
        )

        # All agents should have ERROR status for missing results
        assert result.transport.status == "ERROR"
        assert result.stay.status == "ERROR"
        assert result.poi.status == "ERROR"
        assert result.events.status == "ERROR"
        assert result.dining.status == "ERROR"

    @pytest.mark.asyncio
    async def test_aggregator_handles_no_trip_spec(
        self,
        full_discovery_results: DiscoveryResults,
        discovery_context_no_gaps: DiscoveryContext,
    ) -> None:
        """Test that aggregator works without trip_spec."""
        aggregator = AggregatorAgent()
        result = await aggregator.aggregate(
            discovery_results=full_discovery_results,
            discovery_context=discovery_context_no_gaps,
            trip_spec=None,
        )

        # Should still work, just with empty destination
        assert result.destination == ""
        assert result.transport.status == "SUCCESS"

    @pytest.mark.asyncio
    async def test_aggregator_with_skipped_agent(
        self,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that aggregator handles skipped agent status."""
        results = DiscoveryResults(
            transport=AgentDiscoveryResult(
                agent="transport",
                status="skipped",
                message="User arranging own transport",
            ),
            stay=AgentDiscoveryResult(
                agent="stay",
                status="success",
                data={"hotels": [{"name": "Hotel"}]},
            ),
            poi=AgentDiscoveryResult(
                agent="poi",
                status="success",
                data={"attractions": []},
            ),
            events=None,
            dining=None,
        )
        context = DiscoveryContext(results=results, gaps=[])

        aggregator = AggregatorAgent()
        result = await aggregator.aggregate(
            discovery_results=results,
            discovery_context=context,
            trip_spec=trip_spec,
        )

        assert result.transport.status == "SKIPPED"
        assert result.transport.data is None

    @pytest.mark.asyncio
    async def test_aggregator_with_not_found_status(
        self,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that aggregator handles not_found status."""
        results = DiscoveryResults(
            transport=AgentDiscoveryResult(
                agent="transport",
                status="not_found",
                message="No flights for this route",
            ),
            stay=AgentDiscoveryResult(
                agent="stay",
                status="success",
                data={"hotels": [{"name": "Hotel"}]},
            ),
            poi=None,
            events=None,
            dining=None,
        )
        context = DiscoveryContext(results=results, gaps=[])

        aggregator = AggregatorAgent()
        result = await aggregator.aggregate(
            discovery_results=results,
            discovery_context=context,
            trip_spec=trip_spec,
        )

        assert result.transport.status == "NOT_FOUND"
        assert result.transport.message == "No flights for this route"


# ═══════════════════════════════════════════════════════════════════════════════
# A2A Integration Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestAggregatorAgentA2A:
    """Tests for AggregatorAgent A2A integration."""

    @pytest.fixture
    def mock_a2a_client(self) -> AsyncMock:
        """Create mock A2A client."""
        client = AsyncMock()
        return client

    @pytest.fixture
    def mock_agent_registry(self) -> MagicMock:
        """Create mock agent registry."""
        registry = MagicMock()
        aggregator_config = MagicMock()
        aggregator_config.url = "http://localhost:8010"
        aggregator_config.timeout = 60
        registry.get.return_value = aggregator_config
        return registry

    @pytest.mark.asyncio
    async def test_aggregator_calls_a2a_when_available(
        self,
        mock_a2a_client: AsyncMock,
        mock_agent_registry: MagicMock,
        full_discovery_results: DiscoveryResults,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that aggregator calls A2A client when available."""
        # Configure mock response
        mock_response = MagicMock()
        mock_response.is_complete = True
        mock_response.text = '{"transport": {"status": "SUCCESS", "data": {}}, "stay": {"status": "SUCCESS", "data": {}}, "poi": {"status": "SUCCESS", "data": {}}, "events": {"status": "SUCCESS", "data": {}}, "dining": {"status": "SUCCESS", "data": {}}, "destination": "Tokyo", "summary": {}}'
        mock_a2a_client.send_message.return_value = mock_response

        aggregator = AggregatorAgent(
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        result = await aggregator.aggregate(
            discovery_results=full_discovery_results,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # Verify A2A client was called
        mock_a2a_client.send_message.assert_called_once()
        call_kwargs = mock_a2a_client.send_message.call_args.kwargs
        assert call_kwargs["agent_url"] == "http://localhost:8010"
        assert call_kwargs["timeout"] == 60

    @pytest.mark.asyncio
    async def test_aggregator_falls_back_on_a2a_error(
        self,
        mock_a2a_client: AsyncMock,
        mock_agent_registry: MagicMock,
        full_discovery_results: DiscoveryResults,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that aggregator falls back to local on A2A error."""
        # Configure mock to raise exception
        mock_a2a_client.send_message.side_effect = Exception("Connection failed")

        aggregator = AggregatorAgent(
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        result = await aggregator.aggregate(
            discovery_results=full_discovery_results,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # Should still get valid results from local fallback
        assert result.transport.status == "SUCCESS"
        assert result.destination == "Tokyo"

    @pytest.mark.asyncio
    async def test_aggregator_falls_back_on_incomplete_response(
        self,
        mock_a2a_client: AsyncMock,
        mock_agent_registry: MagicMock,
        full_discovery_results: DiscoveryResults,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that aggregator falls back when A2A response is incomplete."""
        # Configure mock to return incomplete response
        mock_response = MagicMock()
        mock_response.is_complete = False
        mock_response.text = ""
        mock_a2a_client.send_message.return_value = mock_response

        aggregator = AggregatorAgent(
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        result = await aggregator.aggregate(
            discovery_results=full_discovery_results,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # Should still get valid results from local fallback
        assert result.transport.status == "SUCCESS"

    @pytest.mark.asyncio
    async def test_aggregator_falls_back_on_missing_registry_entry(
        self,
        mock_a2a_client: AsyncMock,
        full_discovery_results: DiscoveryResults,
        discovery_context_no_gaps: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> None:
        """Test that aggregator falls back when aggregator not in registry."""
        # Configure registry to return None
        mock_registry = MagicMock()
        mock_registry.get.return_value = None

        aggregator = AggregatorAgent(
            a2a_client=mock_a2a_client,
            agent_registry=mock_registry,
        )

        result = await aggregator.aggregate(
            discovery_results=full_discovery_results,
            discovery_context=discovery_context_no_gaps,
            trip_spec=trip_spec,
        )

        # Should still get valid results from local fallback
        assert result.transport.status == "SUCCESS"
        assert result.destination == "Tokyo"

        # A2A client should not be called
        mock_a2a_client.send_message.assert_not_called()
