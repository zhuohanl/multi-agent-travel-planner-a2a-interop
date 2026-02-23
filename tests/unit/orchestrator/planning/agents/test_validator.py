"""
Unit tests for ValidatorAgent.

Tests the Validator agent which checks itinerary feasibility including:
- Time conflicts between activities
- Tight connections and timing warnings
- Discovery gaps surfacing as validation gaps
- Accommodation validation

Per ORCH-079 acceptance criteria:
- ValidatorAgent.validate() returns ValidationResult
- ValidationResult has status: valid | valid_with_gaps | invalid
- Hard conflicts (time overlap) are ValidationError
- Soft issues (tight connections) are ValidationWarning
- Known gaps from discovery are ValidationGap with action buttons
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
from src.orchestrator.models.responses import UIAction
from src.orchestrator.planning.agents.route import (
    ItineraryAccommodation,
    ItineraryActivity,
    ItineraryDay,
    ItineraryMeal,
    ItineraryTransport,
    RoutePlan,
    TimeSlot,
)
from src.orchestrator.planning.agents.validator import (
    DEFAULT_CHECK_IN_TIME,
    DEFAULT_CHECK_OUT_TIME,
    MIN_CONNECTION_TIME,
    TIGHT_CONNECTION_THRESHOLD,
    ValidatorAgent,
)
from src.orchestrator.planning.pipeline import (
    DiscoveryContext,
    DiscoveryGap,
    DiscoveryStatus,
    ValidationError,
    ValidationGap,
    ValidationResult,
    ValidationWarning,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def valid_route_plan() -> dict[str, Any]:
    """Create a valid route plan with no conflicts."""
    return {
        "destination": "Tokyo",
        "start_date": "2026-03-15",
        "end_date": "2026-03-17",
        "days": [
            {
                "day_number": 1,
                "date": "2026-03-15",
                "title": "Day 1 in Tokyo",
                "transport": [
                    {
                        "mode": "flight",
                        "from_location": "Los Angeles",
                        "to_location": "Tokyo",
                        "departure_time": "09:00",
                        "arrival_time": "14:00",
                        "is_placeholder": False,
                    }
                ],
                "activities": [
                    {
                        "name": "Check-in at hotel",
                        "category": "logistics",
                        "time_slot": {
                            "start_time": "15:00",
                            "end_time": "15:30",
                        },
                        "is_placeholder": False,
                    },
                    {
                        "name": "Explore Shinjuku",
                        "category": "attraction",
                        "time_slot": {
                            "start_time": "16:00",
                            "end_time": "18:00",
                        },
                        "is_placeholder": False,
                    },
                ],
                "meals": [
                    {
                        "meal_type": "dinner",
                        "name": "Ichiran Ramen",
                        "time_slot": {
                            "start_time": "19:00",
                            "end_time": "20:30",
                        },
                    }
                ],
                "accommodation": {
                    "name": "Park Hyatt Tokyo",
                    "check_in_time": "15:00",
                    "check_out_time": "11:00",
                },
            },
            {
                "day_number": 2,
                "date": "2026-03-16",
                "title": "Day 2 in Tokyo",
                "activities": [
                    {
                        "name": "Tokyo Tower",
                        "category": "attraction",
                        "time_slot": {
                            "start_time": "10:00",
                            "end_time": "12:00",
                        },
                        "is_placeholder": False,
                    },
                    {
                        "name": "Senso-ji Temple",
                        "category": "attraction",
                        "time_slot": {
                            "start_time": "14:30",
                            "end_time": "16:00",
                        },
                        "is_placeholder": False,
                    },
                ],
                "meals": [],
                "accommodation": {
                    "name": "Park Hyatt Tokyo",
                    "check_in_time": "15:00",
                    "check_out_time": "11:00",
                },
            },
            {
                "day_number": 3,
                "date": "2026-03-17",
                "title": "Day 3 in Tokyo - Departure",
                "transport": [
                    {
                        "mode": "flight",
                        "from_location": "Tokyo",
                        "to_location": "Los Angeles",
                        "departure_time": "13:00",
                        "arrival_time": "08:00",
                        "is_placeholder": False,
                    }
                ],
                "activities": [
                    {
                        "name": "Last-minute shopping",
                        "category": "shopping",
                        "time_slot": {
                            "start_time": "09:00",
                            "end_time": "10:30",
                        },
                        "is_placeholder": False,
                    },
                ],
                "meals": [],
            },
        ],
        "total_estimated_cost": 2500.0,
        "currency": "USD",
        "has_placeholders": False,
    }


@pytest.fixture
def route_plan_with_time_conflict() -> dict[str, Any]:
    """Create a route plan with overlapping activities."""
    return {
        "destination": "Tokyo",
        "start_date": "2026-03-15",
        "end_date": "2026-03-15",
        "days": [
            {
                "day_number": 1,
                "date": "2026-03-15",
                "title": "Day 1 in Tokyo",
                "activities": [
                    {
                        "name": "Tokyo Tower",
                        "category": "attraction",
                        "time_slot": {
                            "start_time": "10:00",
                            "end_time": "12:30",  # Overlaps with next activity
                        },
                        "is_placeholder": False,
                    },
                    {
                        "name": "Senso-ji Temple",
                        "category": "attraction",
                        "time_slot": {
                            "start_time": "12:00",  # Starts before Tokyo Tower ends
                            "end_time": "14:00",
                        },
                        "is_placeholder": False,
                    },
                ],
                "meals": [],
                "accommodation": {
                    "name": "Park Hyatt Tokyo",
                },
            },
        ],
        "total_estimated_cost": 1000.0,
        "currency": "USD",
    }


@pytest.fixture
def route_plan_with_tight_connection() -> dict[str, Any]:
    """Create a route plan with tight connections between activities."""
    return {
        "destination": "Tokyo",
        "start_date": "2026-03-15",
        "end_date": "2026-03-15",
        "days": [
            {
                "day_number": 1,
                "date": "2026-03-15",
                "title": "Day 1 in Tokyo",
                "activities": [
                    {
                        "name": "Tokyo Tower",
                        "category": "attraction",
                        "time_slot": {
                            "start_time": "10:00",
                            "end_time": "12:00",
                        },
                        "is_placeholder": False,
                    },
                    {
                        "name": "Senso-ji Temple",
                        "category": "attraction",
                        "time_slot": {
                            "start_time": "12:20",  # Only 20 minutes gap (tight)
                            "end_time": "14:00",
                        },
                        "is_placeholder": False,
                    },
                ],
                "meals": [],
                "accommodation": {
                    "name": "Park Hyatt Tokyo",
                },
            },
        ],
        "total_estimated_cost": 1000.0,
        "currency": "USD",
    }


@pytest.fixture
def route_plan_with_departure_conflict() -> dict[str, Any]:
    """Create a route plan with departure before checkout."""
    return {
        "destination": "Tokyo",
        "start_date": "2026-03-15",
        "end_date": "2026-03-16",
        "days": [
            {
                "day_number": 1,
                "date": "2026-03-15",
                "title": "Day 1 in Tokyo",
                "activities": [],
                "meals": [],
                "accommodation": {
                    "name": "Park Hyatt Tokyo",
                    "check_in_time": "15:00",
                    "check_out_time": "11:00",
                },
            },
            {
                "day_number": 2,
                "date": "2026-03-16",
                "title": "Day 2 - Departure",
                "transport": [
                    {
                        "mode": "flight",
                        "from_location": "Tokyo",
                        "to_location": "Los Angeles",
                        "departure_time": "08:00",  # Before 11:00 checkout
                        "is_placeholder": False,
                    }
                ],
                "activities": [],
                "meals": [],
            },
        ],
        "total_estimated_cost": 1000.0,
        "currency": "USD",
    }


@pytest.fixture
def full_discovery_results() -> DiscoveryResults:
    """Create complete successful discovery results."""
    return DiscoveryResults(
        transport=AgentDiscoveryResult(
            agent="transport",
            status="success",
            data={"flights": [{"airline": "JAL", "price": 1200}]},
        ),
        stay=AgentDiscoveryResult(
            agent="stay",
            status="success",
            data={"hotels": [{"name": "Park Hyatt", "price_per_night": 500}]},
        ),
        poi=AgentDiscoveryResult(
            agent="poi",
            status="success",
            data={"attractions": [{"name": "Tokyo Tower"}]},
        ),
        events=AgentDiscoveryResult(
            agent="events",
            status="success",
            data={"events": []},
        ),
        dining=AgentDiscoveryResult(
            agent="dining",
            status="success",
            data={"restaurants": [{"name": "Ichiran"}]},
        ),
    )


@pytest.fixture
def discovery_context_no_gaps(full_discovery_results: DiscoveryResults) -> DiscoveryContext:
    """Create discovery context with no gaps."""
    return DiscoveryContext(
        results=full_discovery_results,
        gaps=[],
    )


@pytest.fixture
def discovery_context_with_transport_gap() -> DiscoveryContext:
    """Create discovery context with transport gap."""
    return DiscoveryContext(
        results=DiscoveryResults(
            transport=AgentDiscoveryResult(
                agent="transport",
                status="error",
                data=None,
                message="API timeout",
            ),
            stay=AgentDiscoveryResult(
                agent="stay",
                status="success",
                data={"hotels": [{"name": "Park Hyatt"}]},
            ),
            poi=AgentDiscoveryResult(
                agent="poi",
                status="success",
                data={"attractions": []},
            ),
            events=AgentDiscoveryResult(agent="events", status="success", data={}),
            dining=AgentDiscoveryResult(agent="dining", status="success", data={}),
        ),
        gaps=[
            DiscoveryGap(
                agent="transport",
                status=DiscoveryStatus.ERROR,
                impact="Arrival and departure times unknown",
                placeholder_strategy="Itinerary assumes 2pm arrival Day 1, 11am departure final day",
                user_action_required=True,
                retry_action=UIAction(
                    label="Retry Flight Search",
                    event={"type": "retry_agent", "agent": "transport"},
                ),
            ),
        ],
    )


@pytest.fixture
def discovery_context_with_poi_gap() -> DiscoveryContext:
    """Create discovery context with POI gap (non-critical)."""
    return DiscoveryContext(
        results=DiscoveryResults(
            transport=AgentDiscoveryResult(
                agent="transport",
                status="success",
                data={"flights": [{"airline": "JAL"}]},
            ),
            stay=AgentDiscoveryResult(
                agent="stay",
                status="success",
                data={"hotels": [{"name": "Park Hyatt"}]},
            ),
            poi=AgentDiscoveryResult(
                agent="poi",
                status="error",
                data=None,
                message="No attractions found",
            ),
            events=AgentDiscoveryResult(agent="events", status="success", data={}),
            dining=AgentDiscoveryResult(agent="dining", status="success", data={}),
        ),
        gaps=[
            DiscoveryGap(
                agent="poi",
                status=DiscoveryStatus.ERROR,
                impact="Limited attraction recommendations",
                placeholder_strategy="Itinerary includes 'free time' blocks",
                user_action_required=False,
                retry_action=UIAction(
                    label="Retry Attractions Search",
                    event={"type": "retry_agent", "agent": "poi"},
                ),
            ),
        ],
    )


@pytest.fixture
def discovery_context_with_multiple_gaps() -> DiscoveryContext:
    """Create discovery context with multiple gaps."""
    return DiscoveryContext(
        results=DiscoveryResults(
            transport=AgentDiscoveryResult(
                agent="transport",
                status="timeout",
                data=None,
                message="Timeout",
            ),
            stay=AgentDiscoveryResult(
                agent="stay",
                status="success",
                data={"hotels": [{"name": "Park Hyatt"}]},
            ),
            poi=AgentDiscoveryResult(
                agent="poi",
                status="not_found",
                data=None,
                message="No attractions found",
            ),
            events=AgentDiscoveryResult(
                agent="events",
                status="error",
                data=None,
                message="API error",
            ),
            dining=AgentDiscoveryResult(agent="dining", status="success", data={}),
        ),
        gaps=[
            DiscoveryGap(
                agent="transport",
                status=DiscoveryStatus.TIMEOUT,
                impact="Flight search timed out",
                placeholder_strategy="Itinerary uses estimated arrival times",
                user_action_required=True,
            ),
            DiscoveryGap(
                agent="poi",
                status=DiscoveryStatus.NOT_FOUND,
                impact="No attractions found for destination",
                user_action_required=False,
            ),
            DiscoveryGap(
                agent="events",
                status=DiscoveryStatus.ERROR,
                impact="No local events available",
                user_action_required=False,
            ),
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test ValidatorAgent.validate() basic behavior
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidatorBasic:
    """Test basic ValidatorAgent behavior."""

    @pytest.mark.asyncio
    async def test_validator_returns_valid_for_good_itinerary(
        self,
        valid_route_plan: dict[str, Any],
        discovery_context_no_gaps: DiscoveryContext,
    ) -> None:
        """Test that a well-formed itinerary with no gaps returns valid status."""
        validator = ValidatorAgent()

        result = await validator.validate(valid_route_plan, discovery_context_no_gaps)

        assert result.status == "valid"
        assert len(result.errors) == 0
        assert len(result.gaps) == 0
        assert result.is_valid() is True
        assert result.has_errors() is False

    @pytest.mark.asyncio
    async def test_validator_returns_validation_result_type(
        self,
        valid_route_plan: dict[str, Any],
        discovery_context_no_gaps: DiscoveryContext,
    ) -> None:
        """Test that validate() returns a ValidationResult."""
        validator = ValidatorAgent()

        result = await validator.validate(valid_route_plan, discovery_context_no_gaps)

        assert isinstance(result, ValidationResult)

    @pytest.mark.asyncio
    async def test_validator_accepts_route_plan_object(
        self,
        discovery_context_no_gaps: DiscoveryContext,
    ) -> None:
        """Test that validate() accepts RoutePlan objects, not just dicts."""
        route_plan = RoutePlan(
            destination="Tokyo",
            start_date=date_type(2026, 3, 15),
            end_date=date_type(2026, 3, 16),
            days=[
                ItineraryDay(
                    day_number=1,
                    date=date_type(2026, 3, 15),
                    title="Day 1 in Tokyo",
                    accommodation=ItineraryAccommodation(name="Park Hyatt Tokyo"),
                ),
                ItineraryDay(
                    day_number=2,
                    date=date_type(2026, 3, 16),
                    title="Day 2 in Tokyo",
                ),
            ],
        )
        validator = ValidatorAgent()

        result = await validator.validate(route_plan, discovery_context_no_gaps)

        assert isinstance(result, ValidationResult)
        # Should be valid with no gaps
        assert result.status == "valid"


# ═══════════════════════════════════════════════════════════════════════════════
# Test time conflict detection
# ═══════════════════════════════════════════════════════════════════════════════


class TestTimeConflictDetection:
    """Test detection of time conflicts in itinerary."""

    @pytest.mark.asyncio
    async def test_validator_returns_invalid_for_time_conflict(
        self,
        route_plan_with_time_conflict: dict[str, Any],
        discovery_context_no_gaps: DiscoveryContext,
    ) -> None:
        """Test that overlapping activities produce ValidationError."""
        validator = ValidatorAgent()

        result = await validator.validate(
            route_plan_with_time_conflict,
            discovery_context_no_gaps,
        )

        assert result.status == "invalid"
        assert len(result.errors) > 0
        assert result.has_errors() is True
        assert result.is_valid() is False

        # Check that the error mentions the overlap
        error = result.errors[0]
        assert isinstance(error, ValidationError)
        assert error.category == "timing"
        assert "Tokyo Tower" in error.message or "Senso-ji" in error.message
        assert "overlap" in error.message.lower()

    @pytest.mark.asyncio
    async def test_validator_returns_warning_for_tight_connection(
        self,
        route_plan_with_tight_connection: dict[str, Any],
        discovery_context_no_gaps: DiscoveryContext,
    ) -> None:
        """Test that tight connections produce ValidationWarning."""
        validator = ValidatorAgent()

        result = await validator.validate(
            route_plan_with_tight_connection,
            discovery_context_no_gaps,
        )

        # Should be valid but with warnings
        assert result.status == "valid"
        assert len(result.warnings) > 0

        # Check the warning content
        warning = result.warnings[0]
        assert isinstance(warning, ValidationWarning)
        assert warning.category == "timing"
        assert "minutes" in warning.message.lower()

    @pytest.mark.asyncio
    async def test_validator_returns_error_for_departure_checkout_conflict(
        self,
        route_plan_with_departure_conflict: dict[str, Any],
        discovery_context_no_gaps: DiscoveryContext,
    ) -> None:
        """Test that departure before checkout produces ValidationError."""
        validator = ValidatorAgent()

        result = await validator.validate(
            route_plan_with_departure_conflict,
            discovery_context_no_gaps,
        )

        assert result.status == "invalid"
        assert len(result.errors) > 0

        # Find the checkout conflict error
        checkout_errors = [e for e in result.errors if "check" in e.message.lower()]
        assert len(checkout_errors) > 0
        assert checkout_errors[0].category == "timing"


# ═══════════════════════════════════════════════════════════════════════════════
# Test gap handling
# ═══════════════════════════════════════════════════════════════════════════════


class TestGapHandling:
    """Test handling of discovery gaps."""

    @pytest.mark.asyncio
    async def test_validator_returns_gaps_for_missing_transport(
        self,
        valid_route_plan: dict[str, Any],
        discovery_context_with_transport_gap: DiscoveryContext,
    ) -> None:
        """Test that transport gaps are converted to ValidationGaps."""
        validator = ValidatorAgent()

        result = await validator.validate(
            valid_route_plan,
            discovery_context_with_transport_gap,
        )

        # Should be valid_with_gaps, not invalid
        assert result.status == "valid_with_gaps"
        assert len(result.gaps) > 0
        assert result.is_valid() is True  # Gaps don't make it invalid

        # Check the gap
        gap = result.gaps[0]
        assert isinstance(gap, ValidationGap)
        assert gap.category == "transport"
        assert gap.source == DiscoveryStatus.ERROR
        assert gap.impact == "Arrival and departure times unknown"
        assert gap.action is not None
        assert gap.action.label == "Retry Flight Search"

    @pytest.mark.asyncio
    async def test_validator_returns_gaps_for_missing_poi(
        self,
        valid_route_plan: dict[str, Any],
        discovery_context_with_poi_gap: DiscoveryContext,
    ) -> None:
        """Test that POI gaps are converted to ValidationGaps."""
        validator = ValidatorAgent()

        result = await validator.validate(
            valid_route_plan,
            discovery_context_with_poi_gap,
        )

        assert result.status == "valid_with_gaps"
        assert len(result.gaps) == 1

        gap = result.gaps[0]
        assert gap.category == "poi"
        assert gap.impact == "Limited attraction recommendations"

    @pytest.mark.asyncio
    async def test_validator_handles_multiple_gaps(
        self,
        valid_route_plan: dict[str, Any],
        discovery_context_with_multiple_gaps: DiscoveryContext,
    ) -> None:
        """Test that multiple discovery gaps are all converted."""
        validator = ValidatorAgent()

        result = await validator.validate(
            valid_route_plan,
            discovery_context_with_multiple_gaps,
        )

        assert result.status == "valid_with_gaps"
        assert len(result.gaps) == 3

        # Check all gap categories are present
        gap_categories = {gap.category for gap in result.gaps}
        assert "transport" in gap_categories
        assert "poi" in gap_categories
        assert "events" in gap_categories


# ═══════════════════════════════════════════════════════════════════════════════
# Test distinguishing error vs warning vs gap
# ═══════════════════════════════════════════════════════════════════════════════


class TestErrorWarningGapDistinction:
    """Test that Validator correctly distinguishes errors, warnings, and gaps."""

    @pytest.mark.asyncio
    async def test_validator_distinguishes_error_vs_warning_vs_gap(
        self,
        route_plan_with_tight_connection: dict[str, Any],
        discovery_context_with_transport_gap: DiscoveryContext,
    ) -> None:
        """Test that different issue types are categorized correctly."""
        validator = ValidatorAgent()

        result = await validator.validate(
            route_plan_with_tight_connection,
            discovery_context_with_transport_gap,
        )

        # Should have:
        # - No errors (tight connection is warning, not error)
        # - Warning for tight connection
        # - Gap for missing transport
        assert result.status == "valid_with_gaps"
        assert len(result.errors) == 0
        assert len(result.warnings) > 0
        assert len(result.gaps) > 0

        # Check types
        for error in result.errors:
            assert isinstance(error, ValidationError)
        for warning in result.warnings:
            assert isinstance(warning, ValidationWarning)
        for gap in result.gaps:
            assert isinstance(gap, ValidationGap)

    @pytest.mark.asyncio
    async def test_gaps_have_action_buttons(
        self,
        valid_route_plan: dict[str, Any],
        discovery_context_with_transport_gap: DiscoveryContext,
    ) -> None:
        """Test that gaps include UI action buttons for retry."""
        validator = ValidatorAgent()

        result = await validator.validate(
            valid_route_plan,
            discovery_context_with_transport_gap,
        )

        assert len(result.gaps) > 0
        gap = result.gaps[0]
        assert gap.action is not None
        assert isinstance(gap.action, UIAction)
        assert gap.action.event is not None
        assert gap.action.event.get("type") == "retry_agent"

    @pytest.mark.asyncio
    async def test_validation_result_status_priority(self) -> None:
        """Test that invalid > valid_with_gaps > valid in status determination."""
        validator = ValidatorAgent()

        # Create a route plan with both time conflict AND gaps
        conflicting_route = {
            "destination": "Tokyo",
            "start_date": "2026-03-15",
            "end_date": "2026-03-15",
            "days": [
                {
                    "day_number": 1,
                    "date": "2026-03-15",
                    "activities": [
                        {
                            "name": "Activity 1",
                            "time_slot": {"start_time": "10:00", "end_time": "12:00"},
                            "is_placeholder": False,
                        },
                        {
                            "name": "Activity 2",
                            "time_slot": {"start_time": "11:00", "end_time": "13:00"},
                            "is_placeholder": False,
                        },
                    ],
                    "accommodation": {"name": "Hotel"},
                }
            ],
        }

        context_with_gap = DiscoveryContext(
            results=DiscoveryResults(
                transport=AgentDiscoveryResult(agent="transport", status="error", data=None),
                stay=AgentDiscoveryResult(agent="stay", status="success", data={}),
                poi=AgentDiscoveryResult(agent="poi", status="success", data={}),
                events=AgentDiscoveryResult(agent="events", status="success", data={}),
                dining=AgentDiscoveryResult(agent="dining", status="success", data={}),
            ),
            gaps=[
                DiscoveryGap(
                    agent="transport",
                    status=DiscoveryStatus.ERROR,
                    impact="Missing transport",
                ),
            ],
        )

        result = await validator.validate(conflicting_route, context_with_gap)

        # Should be "invalid" because errors take priority over gaps
        assert result.status == "invalid"
        assert len(result.errors) > 0
        assert len(result.gaps) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Test serialization
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidationResultSerialization:
    """Test ValidationResult serialization."""

    @pytest.mark.asyncio
    async def test_validation_result_to_dict(
        self,
        valid_route_plan: dict[str, Any],
        discovery_context_with_transport_gap: DiscoveryContext,
    ) -> None:
        """Test that ValidationResult can be serialized to dict."""
        validator = ValidatorAgent()
        result = await validator.validate(valid_route_plan, discovery_context_with_transport_gap)

        result_dict = result.to_dict()

        assert isinstance(result_dict, dict)
        assert result_dict["status"] == "valid_with_gaps"
        assert isinstance(result_dict["errors"], list)
        assert isinstance(result_dict["warnings"], list)
        assert isinstance(result_dict["gaps"], list)
        assert len(result_dict["gaps"]) > 0

        # Check gap serialization
        gap_dict = result_dict["gaps"][0]
        assert gap_dict["category"] == "transport"
        assert gap_dict["source"] == "error"

    @pytest.mark.asyncio
    async def test_validation_result_from_dict(self) -> None:
        """Test that ValidationResult can be deserialized from dict."""
        data = {
            "status": "valid_with_gaps",
            "errors": [
                {
                    "category": "timing",
                    "message": "Overlapping activities",
                    "affected_day": 1,
                }
            ],
            "warnings": [
                {
                    "category": "timing",
                    "message": "Tight connection",
                    "affected_day": 2,
                }
            ],
            "gaps": [
                {
                    "category": "transport",
                    "source": "error",
                    "impact": "Missing transport",
                    "placeholder_used": "Assumed 2pm arrival",
                    "action": {
                        "label": "Retry",
                        "event": {"type": "retry_agent", "agent": "transport"},
                    },
                }
            ],
        }

        result = ValidationResult.from_dict(data)

        assert result.status == "valid_with_gaps"
        assert len(result.errors) == 1
        assert len(result.warnings) == 1
        assert len(result.gaps) == 1
        assert result.gaps[0].action is not None
        assert result.gaps[0].action.label == "Retry"


# ═══════════════════════════════════════════════════════════════════════════════
# Test A2A integration (mocked)
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidatorA2AIntegration:
    """Test ValidatorAgent A2A integration."""

    @pytest.mark.asyncio
    async def test_validator_falls_back_to_local_when_no_client(
        self,
        valid_route_plan: dict[str, Any],
        discovery_context_no_gaps: DiscoveryContext,
    ) -> None:
        """Test that validator uses local logic when no A2A client is provided."""
        validator = ValidatorAgent(a2a_client=None, agent_registry=None)

        result = await validator.validate(valid_route_plan, discovery_context_no_gaps)

        assert isinstance(result, ValidationResult)
        assert result.status == "valid"

    @pytest.mark.asyncio
    async def test_validator_falls_back_on_a2a_error(
        self,
        valid_route_plan: dict[str, Any],
        discovery_context_no_gaps: DiscoveryContext,
    ) -> None:
        """Test that validator falls back to local on A2A error."""
        # Mock A2A client that raises an error
        mock_client = AsyncMock()
        mock_client.send_message.side_effect = Exception("Connection failed")

        mock_registry = MagicMock()
        mock_registry.get.return_value = MagicMock(
            url="http://localhost:8013",
            timeout=30,
        )

        validator = ValidatorAgent(a2a_client=mock_client, agent_registry=mock_registry)

        result = await validator.validate(valid_route_plan, discovery_context_no_gaps)

        # Should fall back to local validation
        assert isinstance(result, ValidationResult)
        assert result.status == "valid"

    @pytest.mark.asyncio
    async def test_validator_falls_back_when_agent_not_in_registry(
        self,
        valid_route_plan: dict[str, Any],
        discovery_context_no_gaps: DiscoveryContext,
    ) -> None:
        """Test that validator falls back when validator agent not in registry."""
        mock_client = AsyncMock()
        mock_registry = MagicMock()
        mock_registry.get.return_value = None  # Validator not found

        validator = ValidatorAgent(a2a_client=mock_client, agent_registry=mock_registry)

        result = await validator.validate(valid_route_plan, discovery_context_no_gaps)

        assert isinstance(result, ValidationResult)
        assert result.status == "valid"


# ═══════════════════════════════════════════════════════════════════════════════
# Test edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidatorEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_validator_handles_empty_itinerary(
        self,
        discovery_context_no_gaps: DiscoveryContext,
    ) -> None:
        """Test validation of empty itinerary."""
        empty_route = {
            "destination": "Tokyo",
            "start_date": "2026-03-15",
            "end_date": "2026-03-15",
            "days": [],
        }
        validator = ValidatorAgent()

        result = await validator.validate(empty_route, discovery_context_no_gaps)

        assert isinstance(result, ValidationResult)
        # Should be valid (empty is not invalid, just empty)
        assert result.status == "valid"

    @pytest.mark.asyncio
    async def test_validator_handles_missing_time_slots(
        self,
        discovery_context_no_gaps: DiscoveryContext,
    ) -> None:
        """Test validation when activities have no time slots."""
        route_no_times = {
            "destination": "Tokyo",
            "start_date": "2026-03-15",
            "end_date": "2026-03-15",
            "days": [
                {
                    "day_number": 1,
                    "activities": [
                        {
                            "name": "Activity 1",
                            "time_slot": {},  # No times
                        },
                        {
                            "name": "Activity 2",
                            # No time_slot at all
                        },
                    ],
                    "accommodation": {"name": "Hotel"},
                }
            ],
        }
        validator = ValidatorAgent()

        result = await validator.validate(route_no_times, discovery_context_no_gaps)

        # Should not crash, should be valid (can't detect conflicts without times)
        assert isinstance(result, ValidationResult)

    @pytest.mark.asyncio
    async def test_validator_handles_placeholder_activities(
        self,
        discovery_context_no_gaps: DiscoveryContext,
    ) -> None:
        """Test that placeholder activities are skipped in connection checks."""
        route_with_placeholders = {
            "destination": "Tokyo",
            "start_date": "2026-03-15",
            "end_date": "2026-03-15",
            "days": [
                {
                    "day_number": 1,
                    "activities": [
                        {
                            "name": "Activity 1",
                            "time_slot": {"start_time": "10:00", "end_time": "12:00"},
                            "is_placeholder": False,
                        },
                        {
                            "name": "Free time",
                            "time_slot": {"start_time": "12:00", "end_time": "12:15"},
                            "is_placeholder": True,  # Should be skipped in timing checks
                        },
                        {
                            "name": "Activity 2",
                            "time_slot": {"start_time": "12:15", "end_time": "14:00"},
                            "is_placeholder": False,
                        },
                    ],
                    "accommodation": {"name": "Hotel"},
                }
            ],
        }
        validator = ValidatorAgent()

        result = await validator.validate(route_with_placeholders, discovery_context_no_gaps)

        # The warning should be about the gap between Activity 1 and Activity 2
        # (15 minutes is very tight), but placeholders are skipped
        assert isinstance(result, ValidationResult)

    @pytest.mark.asyncio
    async def test_validator_handles_skipped_stay(self) -> None:
        """Test that skipped stay (user arranging own) is not flagged as error."""
        route_plan = {
            "destination": "Tokyo",
            "start_date": "2026-03-15",
            "end_date": "2026-03-16",
            "days": [
                {"day_number": 1, "activities": []},  # No accommodation
                {"day_number": 2, "activities": []},
            ],
        }

        context_skipped_stay = DiscoveryContext(
            results=DiscoveryResults(
                transport=AgentDiscoveryResult(agent="transport", status="success", data={}),
                stay=AgentDiscoveryResult(agent="stay", status="skipped", data=None),
                poi=AgentDiscoveryResult(agent="poi", status="success", data={}),
                events=AgentDiscoveryResult(agent="events", status="success", data={}),
                dining=AgentDiscoveryResult(agent="dining", status="success", data={}),
            ),
            gaps=[
                DiscoveryGap(
                    agent="stay",
                    status=DiscoveryStatus.SKIPPED,
                    impact="User arranging own accommodation",
                    user_action_required=False,
                ),
            ],
        )

        validator = ValidatorAgent()
        result = await validator.validate(route_plan, context_skipped_stay)

        # Skipped stay should not produce errors
        stay_errors = [e for e in result.errors if e.category == "accommodation"]
        assert len(stay_errors) == 0
