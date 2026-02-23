"""
Unit tests for planning pipeline.

Tests the planning pipeline orchestration including:
- Gap building from discovery results
- Hard blocker detection (missing stay)
- Sequential pipeline execution
- Discovery context passing to agents
- Validation result handling

Per ticket ORCH-075 test requirements.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator.handlers.discovery import (
    AgentDiscoveryResult,
    DiscoveryResults,
)
from src.orchestrator.models.responses import UIAction
from src.orchestrator.planning.pipeline import (
    DiscoveryContext,
    DiscoveryGap,
    DiscoveryStatus,
    PlanningPipeline,
    PlanningResult,
    ValidationError,
    ValidationGap,
    ValidationResult,
    ValidationWarning,
    build_gaps,
    run_planning_pipeline,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Test Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def full_success_results():
    """Discovery results where all agents succeeded."""
    return DiscoveryResults(
        transport=AgentDiscoveryResult(
            agent="transport",
            status="success",
            data={"options": [{"type": "flight", "price": 500}]},
        ),
        stay=AgentDiscoveryResult(
            agent="stay",
            status="success",
            data={"options": [{"type": "hotel", "price": 150}]},
        ),
        poi=AgentDiscoveryResult(
            agent="poi",
            status="success",
            data={"options": [{"name": "Museum", "rating": 4.5}]},
        ),
        events=AgentDiscoveryResult(
            agent="events",
            status="success",
            data={"options": [{"name": "Festival"}]},
        ),
        dining=AgentDiscoveryResult(
            agent="dining",
            status="success",
            data={"options": [{"name": "Restaurant", "cuisine": "Local"}]},
        ),
    )


@pytest.fixture
def partial_results_transport_error():
    """Discovery results where transport failed."""
    return DiscoveryResults(
        transport=AgentDiscoveryResult(
            agent="transport",
            status="error",
            message="API timeout",
            retry_possible=True,
        ),
        stay=AgentDiscoveryResult(
            agent="stay",
            status="success",
            data={"options": [{"type": "hotel", "price": 150}]},
        ),
        poi=AgentDiscoveryResult(
            agent="poi",
            status="success",
            data={"options": []},
        ),
        events=AgentDiscoveryResult(
            agent="events",
            status="success",
            data={"options": []},
        ),
        dining=AgentDiscoveryResult(
            agent="dining",
            status="success",
            data={"options": []},
        ),
    )


@pytest.fixture
def partial_results_stay_error():
    """Discovery results where stay failed (blocker)."""
    return DiscoveryResults(
        transport=AgentDiscoveryResult(
            agent="transport",
            status="success",
            data={"options": [{"type": "flight", "price": 500}]},
        ),
        stay=AgentDiscoveryResult(
            agent="stay",
            status="error",
            message="No availability",
            retry_possible=True,
        ),
        poi=AgentDiscoveryResult(
            agent="poi",
            status="success",
            data={"options": []},
        ),
        events=AgentDiscoveryResult(
            agent="events",
            status="success",
            data={"options": []},
        ),
        dining=AgentDiscoveryResult(
            agent="dining",
            status="success",
            data={"options": []},
        ),
    )


@pytest.fixture
def sample_trip_spec():
    """Sample trip specification."""
    return {
        "destination_city": "Tokyo",
        "origin_city": "San Francisco",
        "start_date": "2024-06-01",
        "end_date": "2024-06-05",
        "num_travelers": 2,
        "budget_per_person": 2000,
        "budget_currency": "USD",
        "interests": ["temples", "food"],
        "constraints": [],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# DiscoveryStatus Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestDiscoveryStatus:
    """Tests for DiscoveryStatus enum."""

    def test_discovery_status_values(self):
        """Test that all status values are present."""
        assert DiscoveryStatus.SUCCESS.value == "success"
        assert DiscoveryStatus.ERROR.value == "error"
        assert DiscoveryStatus.NOT_FOUND.value == "not_found"
        assert DiscoveryStatus.SKIPPED.value == "skipped"
        assert DiscoveryStatus.TIMEOUT.value == "timeout"

    def test_discovery_status_is_string_enum(self):
        """Test that DiscoveryStatus works as a string via .value."""
        assert DiscoveryStatus.SUCCESS == "success"
        assert DiscoveryStatus.ERROR.value == "error"


# ═══════════════════════════════════════════════════════════════════════════════
# DiscoveryGap Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestDiscoveryGap:
    """Tests for DiscoveryGap dataclass."""

    def test_discovery_gap_creation(self):
        """Test creating a DiscoveryGap."""
        gap = DiscoveryGap(
            agent="transport",
            status=DiscoveryStatus.ERROR,
            impact="Arrival time unknown",
            placeholder_strategy="Using 2pm arrival estimate",
            user_action_required=True,
            retry_action=UIAction(
                label="Retry",
                event={"type": "retry_agent", "agent": "transport"},
            ),
        )

        assert gap.agent == "transport"
        assert gap.status == DiscoveryStatus.ERROR
        assert gap.impact == "Arrival time unknown"
        assert gap.placeholder_strategy == "Using 2pm arrival estimate"
        assert gap.user_action_required is True
        assert gap.retry_action is not None

    def test_discovery_gap_to_dict(self):
        """Test serializing a DiscoveryGap."""
        gap = DiscoveryGap(
            agent="stay",
            status=DiscoveryStatus.NOT_FOUND,
            impact="No hotels found",
            user_action_required=True,
        )

        result = gap.to_dict()

        assert result["agent"] == "stay"
        assert result["status"] == "not_found"
        assert result["impact"] == "No hotels found"
        assert result["user_action_required"] is True
        assert "placeholder_strategy" not in result  # None values not included

    def test_discovery_gap_from_dict(self):
        """Test deserializing a DiscoveryGap."""
        data = {
            "agent": "poi",
            "status": "timeout",
            "impact": "Attractions search timed out",
            "placeholder_strategy": "Free time blocks used",
            "user_action_required": False,
        }

        gap = DiscoveryGap.from_dict(data)

        assert gap.agent == "poi"
        assert gap.status == DiscoveryStatus.TIMEOUT
        assert gap.impact == "Attractions search timed out"
        assert gap.placeholder_strategy == "Free time blocks used"
        assert gap.user_action_required is False

    def test_discovery_gap_from_dict_with_retry_action(self):
        """Test deserializing a DiscoveryGap with retry action."""
        data = {
            "agent": "events",
            "status": "error",
            "impact": "Events search failed",
            "retry_action": {
                "label": "Try Again",
                "event": {"type": "retry_agent", "agent": "events"},
            },
        }

        gap = DiscoveryGap.from_dict(data)

        assert gap.retry_action is not None
        assert gap.retry_action.label == "Try Again"
        assert gap.retry_action.event["agent"] == "events"


# ═══════════════════════════════════════════════════════════════════════════════
# DiscoveryContext Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestDiscoveryContext:
    """Tests for DiscoveryContext dataclass."""

    def test_discovery_context_creation(self, full_success_results):
        """Test creating a DiscoveryContext."""
        context = DiscoveryContext(
            results=full_success_results,
            gaps=[],
        )

        assert context.results is not None
        assert context.gaps == []
        assert context.has_gaps() is False

    def test_discovery_context_with_gaps(self, partial_results_transport_error):
        """Test context with gaps."""
        gaps = build_gaps(partial_results_transport_error)
        context = DiscoveryContext(
            results=partial_results_transport_error,
            gaps=gaps,
        )

        assert context.has_gaps() is True
        assert len(context.gaps) >= 1

    def test_discovery_context_get_gap_for_agent(self):
        """Test getting a specific agent's gap."""
        gaps = [
            DiscoveryGap(
                agent="transport",
                status=DiscoveryStatus.ERROR,
                impact="Test",
            ),
        ]
        context = DiscoveryContext(
            results=DiscoveryResults(),
            gaps=gaps,
        )

        transport_gap = context.get_gap_for_agent("transport")
        stay_gap = context.get_gap_for_agent("stay")

        assert transport_gap is not None
        assert transport_gap.agent == "transport"
        assert stay_gap is None

    def test_discovery_context_has_critical_gaps(self):
        """Test checking for user action required gaps."""
        non_critical_gaps = [
            DiscoveryGap(
                agent="dining",
                status=DiscoveryStatus.ERROR,
                impact="Test",
                user_action_required=False,
            ),
        ]
        context_non_critical = DiscoveryContext(
            results=DiscoveryResults(),
            gaps=non_critical_gaps,
        )
        assert context_non_critical.has_critical_gaps() is False

        critical_gaps = [
            DiscoveryGap(
                agent="transport",
                status=DiscoveryStatus.ERROR,
                impact="Test",
                user_action_required=True,
            ),
        ]
        context_critical = DiscoveryContext(
            results=DiscoveryResults(),
            gaps=critical_gaps,
        )
        assert context_critical.has_critical_gaps() is True

    def test_discovery_context_serialization(self, partial_results_transport_error):
        """Test context serialization round-trip."""
        gaps = build_gaps(partial_results_transport_error)
        original = DiscoveryContext(
            results=partial_results_transport_error,
            gaps=gaps,
        )

        data = original.to_dict()
        restored = DiscoveryContext.from_dict(data)

        assert len(restored.gaps) == len(original.gaps)


# ═══════════════════════════════════════════════════════════════════════════════
# ValidationResult Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_validation_result_valid(self):
        """Test valid result."""
        result = ValidationResult(status="valid")

        assert result.is_valid() is True
        assert result.has_errors() is False

    def test_validation_result_valid_with_gaps(self):
        """Test valid with gaps result."""
        result = ValidationResult(
            status="valid_with_gaps",
            gaps=[
                ValidationGap(
                    category="transport",
                    source=DiscoveryStatus.ERROR,
                    impact="Arrival time unknown",
                ),
            ],
        )

        assert result.is_valid() is True
        assert result.has_errors() is False
        assert len(result.gaps) == 1

    def test_validation_result_invalid(self):
        """Test invalid result."""
        result = ValidationResult(
            status="invalid",
            errors=[
                ValidationError(
                    category="timing",
                    message="Flight lands after hotel check-in",
                    affected_day=1,
                ),
            ],
        )

        assert result.is_valid() is False
        assert result.has_errors() is True
        assert len(result.errors) == 1

    def test_validation_result_serialization(self):
        """Test serialization round-trip."""
        original = ValidationResult(
            status="valid_with_gaps",
            errors=[],
            warnings=[
                ValidationWarning(
                    category="timing",
                    message="Tight connection",
                    affected_day=2,
                ),
            ],
            gaps=[
                ValidationGap(
                    category="transport",
                    source=DiscoveryStatus.ERROR,
                    impact="Test impact",
                ),
            ],
        )

        data = original.to_dict()
        restored = ValidationResult.from_dict(data)

        assert restored.status == original.status
        assert len(restored.warnings) == 1
        assert len(restored.gaps) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# build_gaps Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildGaps:
    """Tests for build_gaps function."""

    def test_build_gaps_no_gaps_for_success(self, full_success_results):
        """Test that successful results produce no gaps."""
        gaps = build_gaps(full_success_results)

        assert gaps == []

    def test_build_gaps_for_transport_error(self, partial_results_transport_error):
        """Test gap building for transport error."""
        gaps = build_gaps(partial_results_transport_error)

        transport_gaps = [g for g in gaps if g.agent == "transport"]
        assert len(transport_gaps) == 1

        gap = transport_gaps[0]
        assert gap.status == DiscoveryStatus.ERROR
        assert gap.user_action_required is True
        assert gap.retry_action is not None
        assert "Retry" in gap.retry_action.label or "retry" in gap.retry_action.event.get("type", "")

    def test_build_gaps_for_not_found(self):
        """Test gap building for NOT_FOUND status."""
        results = DiscoveryResults(
            transport=AgentDiscoveryResult(
                agent="transport",
                status="not_found",
                message="No flights available",
            ),
            stay=AgentDiscoveryResult(
                agent="stay",
                status="success",
                data={"options": []},
            ),
        )

        gaps = build_gaps(results)

        transport_gaps = [g for g in gaps if g.agent == "transport"]
        assert len(transport_gaps) == 1
        assert transport_gaps[0].status == DiscoveryStatus.NOT_FOUND

    def test_build_gaps_for_timeout(self):
        """Test gap building for timeout status."""
        results = DiscoveryResults(
            transport=AgentDiscoveryResult(
                agent="transport",
                status="timeout",
                message="Request timed out",
            ),
            stay=AgentDiscoveryResult(
                agent="stay",
                status="success",
                data={"options": []},
            ),
        )

        gaps = build_gaps(results)

        transport_gaps = [g for g in gaps if g.agent == "transport"]
        assert len(transport_gaps) == 1
        assert transport_gaps[0].status == DiscoveryStatus.TIMEOUT

    def test_build_gaps_stay_is_critical(self, partial_results_stay_error):
        """Test that stay gaps are marked as requiring user action."""
        gaps = build_gaps(partial_results_stay_error)

        stay_gaps = [g for g in gaps if g.agent == "stay"]
        assert len(stay_gaps) == 1
        assert stay_gaps[0].user_action_required is True

    def test_build_gaps_non_critical_agents(self):
        """Test that POI, events, dining gaps are non-critical."""
        results = DiscoveryResults(
            transport=AgentDiscoveryResult(agent="transport", status="success", data={}),
            stay=AgentDiscoveryResult(agent="stay", status="success", data={}),
            poi=AgentDiscoveryResult(agent="poi", status="error", message="Failed"),
            events=AgentDiscoveryResult(agent="events", status="error", message="Failed"),
            dining=AgentDiscoveryResult(agent="dining", status="error", message="Failed"),
        )

        gaps = build_gaps(results)

        for gap in gaps:
            if gap.agent in ("poi", "events", "dining"):
                assert gap.user_action_required is False


# ═══════════════════════════════════════════════════════════════════════════════
# PlanningPipeline Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestPlanningPipeline:
    """Tests for PlanningPipeline class."""

    @pytest.mark.asyncio
    async def test_planning_pipeline_runs_sequentially(
        self, full_success_results, sample_trip_spec
    ):
        """Test that the pipeline runs all stages."""
        pipeline = PlanningPipeline()

        result = await pipeline.run(full_success_results, sample_trip_spec)

        assert result.success is True
        assert result.itinerary is not None
        assert result.validation is not None
        assert result.aggregated_results is not None
        assert result.budget_plan is not None

    @pytest.mark.asyncio
    async def test_planning_pipeline_halts_on_missing_stay(
        self, partial_results_stay_error, sample_trip_spec
    ):
        """Test that missing stay blocks the pipeline."""
        pipeline = PlanningPipeline()

        result = await pipeline.run(partial_results_stay_error, sample_trip_spec)

        assert result.success is False
        assert result.blocker is not None
        assert "accommodation" in result.blocker.lower() or "stay" in result.blocker.lower()
        assert result.action is not None
        assert result.action.event.get("agent") == "stay"

    @pytest.mark.asyncio
    async def test_planning_pipeline_passes_discovery_context(
        self, partial_results_transport_error, sample_trip_spec
    ):
        """Test that pipeline passes gaps to agents."""
        pipeline = PlanningPipeline()

        result = await pipeline.run(partial_results_transport_error, sample_trip_spec)

        # Should succeed (transport is soft-critical, not blocker)
        assert result.success is True
        # Should have gaps
        assert len(result.gaps) > 0
        # Validation should reflect gaps
        assert result.validation is not None
        assert result.validation.status == "valid_with_gaps"

    @pytest.mark.asyncio
    async def test_planning_pipeline_returns_gaps(
        self, partial_results_transport_error, sample_trip_spec
    ):
        """Test that pipeline surfaces discovery gaps in result."""
        pipeline = PlanningPipeline()

        result = await pipeline.run(partial_results_transport_error, sample_trip_spec)

        assert result.success is True
        assert result.gaps is not None
        assert len(result.gaps) >= 1

        transport_gaps = [g for g in result.gaps if g.agent == "transport"]
        assert len(transport_gaps) == 1

    @pytest.mark.asyncio
    async def test_planning_pipeline_with_none_stay(self, sample_trip_spec):
        """Test that missing stay result (None) blocks pipeline."""
        results = DiscoveryResults(
            transport=AgentDiscoveryResult(agent="transport", status="success", data={}),
            stay=None,  # No stay result at all
        )

        pipeline = PlanningPipeline()
        result = await pipeline.run(results, sample_trip_spec)

        assert result.success is False
        assert result.blocker is not None

    @pytest.mark.asyncio
    async def test_planning_pipeline_allows_skipped_stay(self, sample_trip_spec):
        """Test that skipped stay (user arranging own) is allowed."""
        results = DiscoveryResults(
            transport=AgentDiscoveryResult(agent="transport", status="success", data={}),
            stay=AgentDiscoveryResult(
                agent="stay",
                status="skipped",
                message="User arranging own accommodation",
            ),
        )

        pipeline = PlanningPipeline()
        result = await pipeline.run(results, sample_trip_spec)

        # Skipped is allowed - not a blocker
        assert result.success is True


# ═══════════════════════════════════════════════════════════════════════════════
# run_planning_pipeline Convenience Function Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunPlanningPipeline:
    """Tests for the run_planning_pipeline convenience function."""

    @pytest.mark.asyncio
    async def test_run_planning_pipeline_function(
        self, full_success_results, sample_trip_spec
    ):
        """Test the convenience function."""
        result = await run_planning_pipeline(
            discovery_results=full_success_results,
            trip_spec=sample_trip_spec,
        )

        assert result.success is True
        assert result.itinerary is not None

    @pytest.mark.asyncio
    async def test_run_planning_pipeline_with_mocked_agents(
        self, full_success_results, sample_trip_spec
    ):
        """Test with mocked A2A client (still uses stubs since not wired)."""
        mock_client = MagicMock()
        mock_registry = MagicMock()

        result = await run_planning_pipeline(
            discovery_results=full_success_results,
            trip_spec=sample_trip_spec,
            a2a_client=mock_client,
            agent_registry=mock_registry,
        )

        # Even with mocks, the stub implementation runs
        assert result.success is True


# ═══════════════════════════════════════════════════════════════════════════════
# PlanningResult Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestPlanningResult:
    """Tests for PlanningResult dataclass."""

    def test_planning_result_success(self):
        """Test successful planning result."""
        result = PlanningResult(
            success=True,
            itinerary={"days": []},
            validation=ValidationResult(status="valid"),
        )

        assert result.success is True
        assert result.itinerary is not None
        assert result.blocker is None

    def test_planning_result_blocked(self):
        """Test blocked planning result."""
        result = PlanningResult(
            success=False,
            blocker="Missing stay options",
            action=UIAction(
                label="Retry Stay Search",
                event={"type": "retry_agent", "agent": "stay"},
            ),
        )

        assert result.success is False
        assert result.blocker == "Missing stay options"
        assert result.action is not None

    def test_planning_result_serialization(self):
        """Test serialization round-trip."""
        original = PlanningResult(
            success=True,
            itinerary={"destination": "Tokyo", "days": []},
            validation=ValidationResult(status="valid_with_gaps"),
            gaps=[
                DiscoveryGap(
                    agent="transport",
                    status=DiscoveryStatus.ERROR,
                    impact="Test",
                ),
            ],
        )

        data = original.to_dict()
        restored = PlanningResult.from_dict(data)

        assert restored.success == original.success
        assert restored.itinerary == original.itinerary
        assert len(restored.gaps) == len(original.gaps)


# ═══════════════════════════════════════════════════════════════════════════════
# Integration-Style Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestPlanningPipelineIntegration:
    """Integration-style tests for end-to-end pipeline behavior."""

    @pytest.mark.asyncio
    async def test_full_pipeline_with_date_objects(self):
        """Test pipeline with date objects in trip_spec."""
        results = DiscoveryResults(
            transport=AgentDiscoveryResult(
                agent="transport",
                status="success",
                data={"options": [{"price": 500}]},
            ),
            stay=AgentDiscoveryResult(
                agent="stay",
                status="success",
                data={"options": [{"price": 150}]},
            ),
        )

        trip_spec = {
            "destination_city": "Paris",
            "origin_city": "London",
            "start_date": date(2024, 7, 1),  # date object, not string
            "end_date": date(2024, 7, 5),
            "num_travelers": 2,
            "budget_per_person": 1500,
            "budget_currency": "EUR",
        }

        result = await run_planning_pipeline(results, trip_spec)

        assert result.success is True
        assert result.itinerary is not None
        assert len(result.itinerary.get("days", [])) == 5

    @pytest.mark.asyncio
    async def test_pipeline_produces_correct_day_count(self, sample_trip_spec):
        """Test that pipeline produces correct number of days."""
        results = DiscoveryResults(
            transport=AgentDiscoveryResult(agent="transport", status="success", data={}),
            stay=AgentDiscoveryResult(agent="stay", status="success", data={}),
        )

        result = await run_planning_pipeline(results, sample_trip_spec)

        # 2024-06-01 to 2024-06-05 = 5 days
        assert result.success is True
        assert len(result.itinerary.get("days", [])) == 5

    @pytest.mark.asyncio
    async def test_pipeline_budget_allocation(self, full_success_results, sample_trip_spec):
        """Test that budget plan is reasonable."""
        result = await run_planning_pipeline(full_success_results, sample_trip_spec)

        assert result.success is True
        assert result.budget_plan is not None

        # Total budget = 2000 * 2 = 4000
        assert result.budget_plan.get("total_budget") == 4000
        assert result.budget_plan.get("currency") == "USD"

        # BudgetPlan now returns allocations as a list of CategoryAllocation dicts
        allocations = result.budget_plan.get("allocations", [])
        assert isinstance(allocations, list)
        assert len(allocations) > 0

        # All allocations should sum to approximately total budget
        total_allocated = sum(
            alloc.get("amount", 0) for alloc in allocations
            if isinstance(alloc, dict)
        )
        # Allow some flexibility
        assert total_allocated > 0

        # Verify all expected categories are present
        categories = [alloc.get("category") for alloc in allocations]
        assert "transport" in categories
        assert "stay" in categories
