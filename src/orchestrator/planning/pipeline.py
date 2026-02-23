"""
Planning pipeline for transforming discovery results into validated itineraries.

Per design doc Pipeline Execution with Gap Awareness section:
- Checks for hard blockers (missing stay) before starting pipeline
- Builds explicit gaps for partial discovery results
- Runs sequential planning: Aggregator -> Budget -> Route -> Validator
- Each agent receives DiscoveryContext with explicit gaps
- Returns PlanningResult with itinerary, validation, and gaps

The planning pipeline is invoked after parallel discovery completes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal

from src.orchestrator.handlers.discovery import (
    AgentDiscoveryResult,
    DiscoveryResults,
)
from src.orchestrator.models.responses import UIAction

if TYPE_CHECKING:
    from src.orchestrator.planning.agents.aggregator import (
        AggregatedResults,
        AggregatorAgent,
    )
    from src.shared.a2a.client_wrapper import A2AClientWrapper
    from src.shared.a2a.registry import AgentRegistry

logger = logging.getLogger(__name__)

StageProgressCallback = Callable[[str, Literal["started", "completed"]], Awaitable[None]]


# ═══════════════════════════════════════════════════════════════════════════════
# Discovery Status Enum
# ═══════════════════════════════════════════════════════════════════════════════


class DiscoveryStatus(str, Enum):
    """Status of discovery for a single agent.

    Per design doc Partial Discovery Context section:
    - SUCCESS: Agent returned valid results
    - ERROR: Agent failed with an error (retryable)
    - NOT_FOUND: Agent returned no results for the query
    - SKIPPED: User explicitly skipped this agent
    - TIMEOUT: Agent did not respond in time
    """

    SUCCESS = "success"
    ERROR = "error"
    NOT_FOUND = "not_found"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


# ═══════════════════════════════════════════════════════════════════════════════
# Discovery Gap and Context Models
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class DiscoveryGap:
    """
    Represents a gap in discovery results that the planning pipeline must handle.

    Per design doc Partial Discovery Context section, DiscoveryGap contains:
    - agent: Which agent has missing/failed results
    - status: Why it's missing (ERROR, NOT_FOUND, TIMEOUT, SKIPPED)
    - impact: Human-readable description of how this affects the itinerary
    - placeholder_strategy: What placeholder/estimate is being used
    - user_action_required: Whether the user should be prompted to take action
    - retry_action: UIAction for retrying (if applicable)

    Example:
        DiscoveryGap(
            agent="transport",
            status=DiscoveryStatus.ERROR,
            impact="Arrival and departure times unknown",
            placeholder_strategy="Itinerary assumes 2pm arrival Day 1, 11am departure final day",
            user_action_required=True,
            retry_action=UIAction(label="Retry Flight Search", event={"type": "retry_agent", "agent": "transport"})
        )
    """

    agent: str
    status: DiscoveryStatus
    impact: str
    placeholder_strategy: str | None = None
    user_action_required: bool = False
    retry_action: UIAction | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for storage/transmission."""
        result: dict[str, Any] = {
            "agent": self.agent,
            "status": self.status.value,
            "impact": self.impact,
            "user_action_required": self.user_action_required,
        }
        if self.placeholder_strategy is not None:
            result["placeholder_strategy"] = self.placeholder_strategy
        if self.retry_action is not None:
            result["retry_action"] = self.retry_action.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiscoveryGap:
        """Deserialize from dictionary."""
        status_str = data.get("status", "error")
        try:
            status = DiscoveryStatus(status_str)
        except ValueError:
            status = DiscoveryStatus.ERROR

        retry_action = None
        if data.get("retry_action"):
            retry_action = UIAction.from_dict(data["retry_action"])

        return cls(
            agent=data.get("agent", ""),
            status=status,
            impact=data.get("impact", ""),
            placeholder_strategy=data.get("placeholder_strategy"),
            user_action_required=data.get("user_action_required", False),
            retry_action=retry_action,
        )


@dataclass
class DiscoveryContext:
    """
    Context passed to all planning agents to communicate discovery state.

    Per design doc, DiscoveryContext bundles:
    - results: The raw discovery results from all agents
    - gaps: Explicit list of gaps/failures for planning agents to handle

    This context is passed to each planning agent (Aggregator, Budget, Route, Validator)
    so they can explicitly handle partial results and create appropriate placeholders.
    """

    results: DiscoveryResults
    gaps: list[DiscoveryGap] = field(default_factory=list)

    def has_gaps(self) -> bool:
        """Check if there are any gaps in discovery."""
        return len(self.gaps) > 0

    def has_critical_gaps(self) -> bool:
        """Check if there are gaps that require user action."""
        return any(gap.user_action_required for gap in self.gaps)

    def get_gap_for_agent(self, agent: str) -> DiscoveryGap | None:
        """Get the gap for a specific agent, if any."""
        for gap in self.gaps:
            if gap.agent == agent:
                return gap
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "results": self.results.to_dict(),
            "gaps": [gap.to_dict() for gap in self.gaps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiscoveryContext:
        """Deserialize from dictionary."""
        return cls(
            results=DiscoveryResults.from_dict(data.get("results", {})),
            gaps=[DiscoveryGap.from_dict(g) for g in data.get("gaps", [])],
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Validation Result Models
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ValidationError:
    """A hard validation error that must be fixed.

    Per design doc, validation errors are conflicts or impossibilities:
    - "Hotel checkout conflicts with flight"
    - "Activity scheduled before museum opens"
    """

    category: str  # "timing", "location", "budget", etc.
    message: str
    affected_day: int | None = None  # Which day has the issue
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "category": self.category,
            "message": self.message,
        }
        if self.affected_day is not None:
            result["affected_day"] = self.affected_day
        if self.details is not None:
            result["details"] = self.details
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidationError:
        return cls(
            category=data.get("category", ""),
            message=data.get("message", ""),
            affected_day=data.get("affected_day"),
            details=data.get("details"),
        )


@dataclass
class ValidationWarning:
    """A soft validation warning the user should be aware of.

    Per design doc, warnings are issues that can proceed but need attention:
    - "Only 45 minutes between activities"
    - "Long walk between locations"
    """

    category: str
    message: str
    affected_day: int | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "category": self.category,
            "message": self.message,
        }
        if self.affected_day is not None:
            result["affected_day"] = self.affected_day
        if self.details is not None:
            result["details"] = self.details
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidationWarning:
        return cls(
            category=data.get("category", ""),
            message=data.get("message", ""),
            affected_day=data.get("affected_day"),
            details=data.get("details"),
        )


@dataclass
class ValidationGap:
    """
    A known gap from partial discovery - NOT a validation error.

    Per design doc, the Validator distinguishes between:
    - ValidationError: Actual conflicts in the itinerary
    - ValidationWarning: Potential issues to be aware of
    - ValidationGap: Known missing pieces from partial discovery

    Example:
        ValidationGap(
            category="transport",
            source=DiscoveryStatus.ERROR,
            impact="Arrival time unknown",
            placeholder_used="Assumed 2pm arrival",
            action=UIAction(label="Search for flights", ...)
        )
    """

    category: str  # "transport", "stay", etc.
    source: DiscoveryStatus
    impact: str
    placeholder_used: str | None = None
    action: UIAction | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "category": self.category,
            "source": self.source.value,
            "impact": self.impact,
        }
        if self.placeholder_used is not None:
            result["placeholder_used"] = self.placeholder_used
        if self.action is not None:
            result["action"] = self.action.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidationGap:
        source_str = data.get("source", "error")
        try:
            source = DiscoveryStatus(source_str)
        except ValueError:
            source = DiscoveryStatus.ERROR

        action = None
        if data.get("action"):
            action = UIAction.from_dict(data["action"])

        return cls(
            category=data.get("category", ""),
            source=source,
            impact=data.get("impact", ""),
            placeholder_used=data.get("placeholder_used"),
            action=action,
        )


@dataclass
class ValidationResult:
    """
    Output from the Validator agent.

    Per design doc, ValidationResult contains:
    - status: "valid", "valid_with_gaps", or "invalid"
    - errors: Hard failures that must be fixed
    - warnings: Soft issues to be aware of
    - gaps: Known gaps from partial discovery
    """

    status: Literal["valid", "valid_with_gaps", "invalid"]
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationWarning] = field(default_factory=list)
    gaps: list[ValidationGap] = field(default_factory=list)

    def is_valid(self) -> bool:
        """Check if the itinerary passed validation (no errors)."""
        return self.status in ("valid", "valid_with_gaps")

    def has_errors(self) -> bool:
        """Check if there are validation errors."""
        return len(self.errors) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "gaps": [g.to_dict() for g in self.gaps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidationResult:
        status_raw = data.get("status", "valid")
        if status_raw not in ("valid", "valid_with_gaps", "invalid"):
            status_raw = "valid"

        return cls(
            status=status_raw,  # type: ignore[arg-type]
            errors=[ValidationError.from_dict(e) for e in data.get("errors", [])],
            warnings=[ValidationWarning.from_dict(w) for w in data.get("warnings", [])],
            gaps=[ValidationGap.from_dict(g) for g in data.get("gaps", [])],
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Planning Result Model
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class PlanningResult:
    """
    Output from the planning pipeline.

    Per design doc, PlanningResult is either:
    - success=True with itinerary, validation, and gaps
    - success=False with blocker reason and action

    Attributes:
        success: Whether the pipeline completed (even with gaps)
        itinerary: The day-by-day route plan (dict until ORCH-078)
        validation: Validation results from the Validator agent
        gaps: Discovery gaps surfaced to user
        blocker: Reason pipeline was blocked (if success=False)
        action: Suggested action for user to unblock (if success=False)
        aggregated_results: Output from Aggregator (intermediate)
        budget_plan: Output from Budget agent (intermediate)
    """

    success: bool
    itinerary: dict[str, Any] | None = None
    validation: ValidationResult | None = None
    gaps: list[DiscoveryGap] = field(default_factory=list)
    blocker: str | None = None
    action: UIAction | None = None
    # Intermediate pipeline outputs (for debugging/inspection)
    aggregated_results: dict[str, Any] | None = None
    budget_plan: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "success": self.success,
        }
        if self.itinerary is not None:
            result["itinerary"] = self.itinerary
        if self.validation is not None:
            result["validation"] = self.validation.to_dict()
        if self.gaps:
            result["gaps"] = [g.to_dict() for g in self.gaps]
        if self.blocker is not None:
            result["blocker"] = self.blocker
        if self.action is not None:
            result["action"] = self.action.to_dict()
        if self.aggregated_results is not None:
            result["aggregated_results"] = self.aggregated_results
        if self.budget_plan is not None:
            result["budget_plan"] = self.budget_plan
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanningResult:
        validation = None
        if data.get("validation"):
            validation = ValidationResult.from_dict(data["validation"])

        action = None
        if data.get("action"):
            action = UIAction.from_dict(data["action"])

        return cls(
            success=data.get("success", False),
            itinerary=data.get("itinerary"),
            validation=validation,
            gaps=[DiscoveryGap.from_dict(g) for g in data.get("gaps", [])],
            blocker=data.get("blocker"),
            action=action,
            aggregated_results=data.get("aggregated_results"),
            budget_plan=data.get("budget_plan"),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Gap Building
# ═══════════════════════════════════════════════════════════════════════════════


def build_gaps(results: DiscoveryResults) -> list[DiscoveryGap]:
    """
    Generate gap descriptions for non-success discovery results.

    Per design doc, this function analyzes discovery results and creates
    explicit DiscoveryGap objects for any agent that didn't succeed.

    Args:
        results: Discovery results from all agents

    Returns:
        List of DiscoveryGap objects for agents with issues
    """
    gaps: list[DiscoveryGap] = []

    # Check transport
    transport_result = results.transport
    if transport_result:
        transport_gap = _build_transport_gap(transport_result)
        if transport_gap:
            gaps.append(transport_gap)

    # Check stay
    stay_result = results.stay
    if stay_result:
        stay_gap = _build_stay_gap(stay_result)
        if stay_gap:
            gaps.append(stay_gap)

    # Check POI
    poi_result = results.poi
    if poi_result:
        poi_gap = _build_poi_gap(poi_result)
        if poi_gap:
            gaps.append(poi_gap)

    # Check events
    events_result = results.events
    if events_result:
        events_gap = _build_events_gap(events_result)
        if events_gap:
            gaps.append(events_gap)

    # Check dining
    dining_result = results.dining
    if dining_result:
        dining_gap = _build_dining_gap(dining_result)
        if dining_gap:
            gaps.append(dining_gap)

    return gaps


def _build_transport_gap(result: AgentDiscoveryResult) -> DiscoveryGap | None:
    """Build gap for transport agent failures."""
    if result.status == "success":
        return None

    status = _map_status(result.status)

    if status == DiscoveryStatus.ERROR:
        return DiscoveryGap(
            agent="transport",
            status=status,
            impact="Arrival and departure times unknown",
            placeholder_strategy="Itinerary assumes 2pm arrival Day 1, 11am departure final day",
            user_action_required=True,
            retry_action=UIAction(
                label="Retry Flight Search",
                event={"type": "retry_agent", "agent": "transport"},
            ),
        )
    elif status == DiscoveryStatus.NOT_FOUND:
        return DiscoveryGap(
            agent="transport",
            status=status,
            impact="No flights found for your dates/route",
            placeholder_strategy="Consider alternative dates or nearby airports",
            user_action_required=True,
            retry_action=UIAction(
                label="Modify Search",
                event={
                    "type": "request_change",
                    "checkpoint_id": "itinerary_approval",
                    "agent": "transport",
                },
            ),
        )
    elif status == DiscoveryStatus.TIMEOUT:
        return DiscoveryGap(
            agent="transport",
            status=status,
            impact="Flight search timed out",
            placeholder_strategy="Itinerary uses estimated arrival times",
            user_action_required=True,
            retry_action=UIAction(
                label="Retry Flight Search",
                event={"type": "retry_agent", "agent": "transport"},
            ),
        )
    elif status == DiscoveryStatus.SKIPPED:
        return DiscoveryGap(
            agent="transport",
            status=status,
            impact="User arranging own transport",
            placeholder_strategy=None,
            user_action_required=False,
            retry_action=None,
        )

    return None


def _build_stay_gap(result: AgentDiscoveryResult) -> DiscoveryGap | None:
    """Build gap for stay agent failures.

    Note: Stay failures are critical - they block the planning pipeline.
    """
    if result.status == "success":
        return None

    status = _map_status(result.status)

    if status == DiscoveryStatus.ERROR:
        return DiscoveryGap(
            agent="stay",
            status=status,
            impact="Cannot plan itinerary without accommodation options",
            placeholder_strategy=None,  # No placeholder - this is a blocker
            user_action_required=True,
            retry_action=UIAction(
                label="Retry Stay Search",
                event={"type": "retry_agent", "agent": "stay"},
            ),
        )
    elif status == DiscoveryStatus.NOT_FOUND:
        return DiscoveryGap(
            agent="stay",
            status=status,
            impact="No accommodations found for your criteria",
            placeholder_strategy=None,
            user_action_required=True,
            retry_action=UIAction(
                label="Modify Stay Search",
                event={
                    "type": "request_change",
                    "checkpoint_id": "itinerary_approval",
                    "agent": "stay",
                },
            ),
        )
    elif status == DiscoveryStatus.TIMEOUT:
        return DiscoveryGap(
            agent="stay",
            status=status,
            impact="Hotel search timed out",
            placeholder_strategy=None,
            user_action_required=True,
            retry_action=UIAction(
                label="Retry Stay Search",
                event={"type": "retry_agent", "agent": "stay"},
            ),
        )
    elif status == DiscoveryStatus.SKIPPED:
        # Skipped stay is valid (e.g., staying with friends)
        return DiscoveryGap(
            agent="stay",
            status=status,
            impact="User arranging own accommodation",
            placeholder_strategy=None,
            user_action_required=False,
            retry_action=None,
        )

    return None


def _build_poi_gap(result: AgentDiscoveryResult) -> DiscoveryGap | None:
    """Build gap for POI agent failures."""
    if result.status == "success":
        return None

    status = _map_status(result.status)

    return DiscoveryGap(
        agent="poi",
        status=status,
        impact="Limited attraction recommendations",
        placeholder_strategy="Itinerary includes 'free time' blocks instead of specific attractions",
        user_action_required=False,  # POI is non-critical
        retry_action=UIAction(
            label="Retry Attractions Search",
            event={"type": "retry_agent", "agent": "poi"},
        ),
    )


def _build_events_gap(result: AgentDiscoveryResult) -> DiscoveryGap | None:
    """Build gap for events agent failures."""
    if result.status == "success":
        return None

    status = _map_status(result.status)

    return DiscoveryGap(
        agent="events",
        status=status,
        impact="No local events included in itinerary",
        placeholder_strategy="Events are optional enhancements",
        user_action_required=False,  # Events are optional
        retry_action=UIAction(
            label="Retry Events Search",
            event={"type": "retry_agent", "agent": "events"},
        ),
    )


def _build_dining_gap(result: AgentDiscoveryResult) -> DiscoveryGap | None:
    """Build gap for dining agent failures."""
    if result.status == "success":
        return None

    status = _map_status(result.status)

    return DiscoveryGap(
        agent="dining",
        status=status,
        impact="Restaurant recommendations not available",
        placeholder_strategy="Generic meal breaks included in itinerary",
        user_action_required=False,  # Dining is non-critical
        retry_action=UIAction(
            label="Retry Dining Search",
            event={"type": "retry_agent", "agent": "dining"},
        ),
    )


def _map_status(status_str: str) -> DiscoveryStatus:
    """Map agent result status string to DiscoveryStatus enum."""
    status_map = {
        "success": DiscoveryStatus.SUCCESS,
        "error": DiscoveryStatus.ERROR,
        "not_found": DiscoveryStatus.NOT_FOUND,
        "skipped": DiscoveryStatus.SKIPPED,
        "timeout": DiscoveryStatus.TIMEOUT,
    }
    return status_map.get(status_str, DiscoveryStatus.ERROR)


# ═══════════════════════════════════════════════════════════════════════════════
# Planning Pipeline
# ═══════════════════════════════════════════════════════════════════════════════


class PlanningPipeline:
    """
    Orchestrates the sequential planning pipeline.

    Per design doc, the pipeline runs:
        Aggregator -> Budget -> Route -> Validator

    Each agent receives the DiscoveryContext with explicit gaps so they
    can handle partial results appropriately.
    """

    def __init__(
        self,
        a2a_client: "A2AClientWrapper | None" = None,
        agent_registry: "AgentRegistry | None" = None,
        stage_progress_callback: StageProgressCallback | None = None,
    ):
        """
        Initialize the planning pipeline.

        Args:
            a2a_client: A2A client for agent communication (optional for testing)
            agent_registry: Agent registry for URL lookup (optional for testing)
            stage_progress_callback: Optional callback for stage progress updates.
        """
        self._a2a_client = a2a_client
        self._agent_registry = agent_registry
        self._stage_progress_callback = stage_progress_callback

    async def _emit_stage_progress(
        self,
        stage: str,
        event: Literal["started", "completed"],
    ) -> None:
        if self._stage_progress_callback is None:
            return
        await self._stage_progress_callback(stage, event)

    async def run(
        self,
        discovery_results: DiscoveryResults,
        trip_spec: dict[str, Any],
    ) -> PlanningResult:
        """
        Run the planning pipeline on discovery results.

        Per design doc Pipeline Execution with Gap Awareness:
        1. Check for hard blockers (missing stay)
        2. Build discovery context with explicit gaps
        3. Run sequential pipeline: Aggregator -> Budget -> Route -> Validator
        4. Return PlanningResult with itinerary and validation

        Args:
            discovery_results: Results from parallel discovery
            trip_spec: Trip requirements from clarification

        Returns:
            PlanningResult with itinerary or blocker reason
        """
        # 1. Check for hard blockers before starting pipeline
        stay_result = discovery_results.stay
        if stay_result is None or stay_result.status not in ("success", "skipped"):
            # Stay is required - cannot proceed without accommodation
            return PlanningResult(
                success=False,
                blocker="Cannot plan itinerary without accommodation options",
                action=UIAction(
                    label="Retry Stay Search",
                    event={"type": "retry_agent", "agent": "stay"},
                ),
            )

        # 2. Build discovery context with explicit gaps
        gaps = build_gaps(discovery_results)
        discovery_context = DiscoveryContext(
            results=discovery_results,
            gaps=gaps,
        )

        # 3. Run sequential pipeline
        try:
            # Aggregator: Combine discovery results
            await self._emit_stage_progress("aggregator", "started")
            aggregated = await self._run_aggregator(
                discovery_results=discovery_results,
                discovery_context=discovery_context,
                trip_spec=trip_spec,
            )
            await self._emit_stage_progress("aggregator", "completed")

            # Budget: Allocate costs across categories
            await self._emit_stage_progress("budget", "started")
            budget_plan = await self._run_budget(
                aggregated=aggregated,
                discovery_context=discovery_context,
                trip_spec=trip_spec,
            )
            await self._emit_stage_progress("budget", "completed")

            # Route: Build day-by-day itinerary
            await self._emit_stage_progress("route", "started")
            route_plan = await self._run_route(
                aggregated=aggregated,
                budget_plan=budget_plan,
                discovery_context=discovery_context,
                trip_spec=trip_spec,
            )
            await self._emit_stage_progress("route", "completed")

            # Validator: Check itinerary feasibility
            await self._emit_stage_progress("validator", "started")
            validation = await self._run_validator(
                route_plan=route_plan,
                discovery_context=discovery_context,
            )
            await self._emit_stage_progress("validator", "completed")

            # 4. Return result with itinerary and validation
            return PlanningResult(
                success=True,
                itinerary=route_plan,
                validation=validation,
                gaps=discovery_context.gaps,
                aggregated_results=aggregated,
                budget_plan=budget_plan,
            )

        except Exception as e:
            logger.error(f"Planning pipeline failed: {e}")
            return PlanningResult(
                success=False,
                blocker=f"Planning pipeline error: {str(e)}",
                gaps=discovery_context.gaps,
                action=UIAction(
                    label="Retry Planning",
                    event={"type": "retry_planning"},
                ),
            )

    async def _run_aggregator(
        self,
        discovery_results: DiscoveryResults,
        discovery_context: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Run the Aggregator agent.

        The Aggregator combines raw discovery results from 5 domain agents
        into a structured format for downstream planning.

        Args:
            discovery_results: Raw results from discovery agents
            discovery_context: Context with explicit gaps
            trip_spec: Trip requirements

        Returns:
            Aggregated results dict
        """
        # Import at runtime to avoid circular import
        from src.orchestrator.planning.agents.aggregator import AggregatorAgent

        # Use AggregatorAgent to combine discovery results
        aggregator = AggregatorAgent(
            a2a_client=self._a2a_client,
            agent_registry=self._agent_registry,
        )
        aggregated_result = await aggregator.aggregate(
            discovery_results=discovery_results,
            discovery_context=discovery_context,
            trip_spec=trip_spec,
        )
        return aggregated_result.to_dict()

    async def _run_budget(
        self,
        aggregated: dict[str, Any],
        discovery_context: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Run the Budget agent.

        The Budget agent allocates budget across categories (transport, stay,
        activities, dining) based on aggregated results and trip requirements.

        Args:
            aggregated: Output from Aggregator (dict representation of AggregatedResults)
            discovery_context: Context with explicit gaps
            trip_spec: Trip requirements with budget info

        Returns:
            Budget allocation plan (dict representation of BudgetPlan)
        """
        # Import at runtime to avoid circular import
        from src.orchestrator.planning.agents.aggregator import AggregatedResults
        from src.orchestrator.planning.agents.budget import BudgetAgent

        # Convert aggregated dict back to AggregatedResults
        aggregated_results = AggregatedResults.from_dict(aggregated)

        # Use BudgetAgent to allocate budget
        budget_agent = BudgetAgent(
            a2a_client=self._a2a_client,
            agent_registry=self._agent_registry,
        )
        budget_plan = await budget_agent.allocate(
            aggregated=aggregated_results,
            discovery_context=discovery_context,
            trip_spec=trip_spec,
        )
        return budget_plan.to_dict()

    async def _run_route(
        self,
        aggregated: dict[str, Any],
        budget_plan: dict[str, Any],
        discovery_context: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Run the Route agent.

        The Route agent transforms aggregated results and budget plan into
        a day-by-day itinerary with timing and logistics.

        Args:
            aggregated: Output from Aggregator
            budget_plan: Output from Budget agent
            discovery_context: Context with explicit gaps
            trip_spec: Trip requirements

        Returns:
            Day-by-day route plan
        """
        # Import at runtime to avoid circular import
        from src.orchestrator.planning.agents.aggregator import AggregatedResults
        from src.orchestrator.planning.agents.budget import BudgetPlan
        from src.orchestrator.planning.agents.route import RouteAgent

        # Convert dicts back to dataclass objects
        aggregated_results = AggregatedResults.from_dict(aggregated)
        budget_plan_obj = BudgetPlan.from_dict(budget_plan)

        # Use RouteAgent to build day-by-day itinerary
        route_agent = RouteAgent(
            a2a_client=self._a2a_client,
            agent_registry=self._agent_registry,
        )
        route_plan = await route_agent.plan(
            aggregated=aggregated_results,
            budget_plan=budget_plan_obj,
            discovery_context=discovery_context,
            trip_spec=trip_spec,
        )
        _run_route_result = route_plan.to_dict()
        return _run_route_result

    async def _run_validator(
        self,
        route_plan: dict[str, Any],
        discovery_context: DiscoveryContext,
    ) -> ValidationResult:
        """
        Run the Validator agent.

        The Validator checks the route plan for feasibility: time conflicts,
        impossible connections, budget overruns.

        Args:
            route_plan: Output from Route agent
            discovery_context: Context with explicit gaps

        Returns:
            Validation result with errors, warnings, and gap acknowledgments
        """
        # Import at runtime to avoid circular import
        from src.orchestrator.planning.agents.validator import ValidatorAgent

        # Use ValidatorAgent to check itinerary feasibility
        validator = ValidatorAgent(
            a2a_client=self._a2a_client,
            agent_registry=self._agent_registry,
        )
        return await validator.validate(
            route_plan=route_plan,
            discovery_context=discovery_context,
        )

    def _stub_route(
        self,
        aggregated: dict[str, Any],
        budget_plan: dict[str, Any],
        context: DiscoveryContext,
        trip_spec: dict[str, Any],
    ) -> dict[str, Any]:
        """Stub route planning for testing."""
        from datetime import date as date_type, timedelta

        # Parse dates
        start_date_raw = trip_spec.get("start_date")
        end_date_raw = trip_spec.get("end_date")

        if isinstance(start_date_raw, str):
            start_date = date_type.fromisoformat(start_date_raw)
        elif isinstance(start_date_raw, date_type):
            start_date = start_date_raw
        else:
            start_date = date_type.today()

        if isinstance(end_date_raw, str):
            end_date = date_type.fromisoformat(end_date_raw)
        elif isinstance(end_date_raw, date_type):
            end_date = end_date_raw
        else:
            end_date = start_date + timedelta(days=3)

        num_days = (end_date - start_date).days + 1
        destination = trip_spec.get("destination_city", "Unknown")

        # Check for transport gap to use placeholders
        transport_gap = context.get_gap_for_agent("transport")

        days = []
        for i in range(num_days):
            day_date = start_date + timedelta(days=i)
            day: dict[str, Any] = {
                "day_number": i + 1,
                "date": day_date.isoformat(),
                "title": f"Day {i + 1} in {destination}",
                "activities": [],
                "meals": [],
                "transport": [],
            }

            # Add transport placeholders for first/last day
            if i == 0:
                if transport_gap:
                    day["transport"].append({
                        "mode": "flight",
                        "from_location": trip_spec.get("origin_city", "Origin"),
                        "to_location": destination,
                        "departure_time": None,
                        "arrival_time": "14:00",  # Placeholder: 2pm arrival
                        "notes": "User to arrange transport",
                    })
                else:
                    day["transport"].append({
                        "mode": "flight",
                        "from_location": trip_spec.get("origin_city", "Origin"),
                        "to_location": destination,
                        "departure_time": "09:00",
                        "arrival_time": "14:00",
                    })

            if i == num_days - 1:
                if transport_gap:
                    day["transport"].append({
                        "mode": "flight",
                        "from_location": destination,
                        "to_location": trip_spec.get("origin_city", "Origin"),
                        "departure_time": "11:00",  # Placeholder: 11am departure
                        "arrival_time": None,
                        "notes": "User to arrange transport",
                    })

            days.append(day)

        return {
            "destination": destination,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days": days,
            "total_estimated_cost": budget_plan.get("total_budget", 0),
            "currency": budget_plan.get("currency", "USD"),
        }

    def _stub_validate(
        self,
        route_plan: dict[str, Any],
        context: DiscoveryContext,
    ) -> ValidationResult:
        """Stub validation for testing."""
        errors: list[ValidationError] = []
        warnings: list[ValidationWarning] = []
        gaps: list[ValidationGap] = []

        # Convert discovery gaps to validation gaps
        for discovery_gap in context.gaps:
            gaps.append(
                ValidationGap(
                    category=discovery_gap.agent,
                    source=discovery_gap.status,
                    impact=discovery_gap.impact,
                    placeholder_used=discovery_gap.placeholder_strategy,
                    action=discovery_gap.retry_action,
                )
            )

        # Determine overall status
        if errors:
            status: Literal["valid", "valid_with_gaps", "invalid"] = "invalid"
        elif gaps:
            status = "valid_with_gaps"
        else:
            status = "valid"

        return ValidationResult(
            status=status,
            errors=errors,
            warnings=warnings,
            gaps=gaps,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Convenience Function
# ═══════════════════════════════════════════════════════════════════════════════


async def run_planning_pipeline(
    discovery_results: DiscoveryResults,
    trip_spec: dict[str, Any],
    a2a_client: "A2AClientWrapper | None" = None,
    agent_registry: "AgentRegistry | None" = None,
    stage_progress_callback: StageProgressCallback | None = None,
) -> PlanningResult:
    """
    Run the planning pipeline on discovery results.

    Convenience function that creates a PlanningPipeline instance and runs it.

    Per design doc, this is the main entry point for planning after discovery:
    1. Check for hard blockers (missing stay)
    2. Build discovery context with explicit gaps
    3. Run sequential pipeline: Aggregator -> Budget -> Route -> Validator
    4. Return PlanningResult with itinerary and validation

    Args:
        discovery_results: Results from parallel discovery
        trip_spec: Trip requirements from clarification (dict format)
        a2a_client: A2A client for agent communication (optional)
        agent_registry: Agent registry for URL lookup (optional)
        stage_progress_callback: Optional callback for stage progress updates.

    Returns:
        PlanningResult with itinerary or blocker reason
    """
    pipeline = PlanningPipeline(
        a2a_client=a2a_client,
        agent_registry=agent_registry,
        stage_progress_callback=stage_progress_callback,
    )
    return await pipeline.run(discovery_results, trip_spec)
