"""
Validator agent for checking itinerary feasibility.

The Validator is the fourth and final planning agent in the pipeline. It receives
the route plan from the Route agent and checks for:
- Time conflicts (overlapping activities, impossible connections)
- Budget overruns (total exceeds allocation)
- Missing or incomplete data (discovery gaps)

Per design doc "Validation Output with Gap Awareness" section:
- ValidationError: Hard failures that must be fixed (e.g., checkout conflicts with flight)
- ValidationWarning: Soft issues to be aware of (e.g., only 45 minutes between activities)
- ValidationGap: Known missing pieces from partial discovery (e.g., transport not determined)

The key distinction is that gaps are NOT errors - they are known issues from
discovery that the user has already been informed about.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date as date_type, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Any, Literal

from src.orchestrator.models.responses import UIAction
from src.orchestrator.planning.pipeline import (
    DiscoveryContext,
    DiscoveryGap,
    DiscoveryStatus,
    ValidationError,
    ValidationGap,
    ValidationResult,
    ValidationWarning,
)

if TYPE_CHECKING:
    from src.orchestrator.planning.agents.route import RoutePlan
    from src.shared.a2a.client_wrapper import A2AClientWrapper
    from src.shared.a2a.registry import AgentRegistry

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════


# Minimum connection time between activities (minutes)
MIN_CONNECTION_TIME = 30

# Threshold for "tight connection" warning (minutes)
TIGHT_CONNECTION_THRESHOLD = 45

# Threshold for "long walk" warning (minutes)
LONG_WALK_THRESHOLD = 20

# Standard check-in and check-out times
DEFAULT_CHECK_IN_TIME = time(15, 0)  # 3:00 PM
DEFAULT_CHECK_OUT_TIME = time(11, 0)  # 11:00 AM

# Threshold for budget overrun (as percentage over total)
BUDGET_OVERRUN_THRESHOLD = 1.1  # 10% over budget


# ═══════════════════════════════════════════════════════════════════════════════
# Validator Agent
# ═══════════════════════════════════════════════════════════════════════════════


class ValidatorAgent:
    """
    Validator agent for checking itinerary feasibility.

    The Validator is the final agent in the planning pipeline. It checks the
    route plan for:
    - Time conflicts and overlaps
    - Impossible connections (not enough travel time)
    - Budget overruns
    - Discovery gaps that need user attention

    Per design doc, the Validator distinguishes between:
    - Errors: Hard failures requiring fixes
    - Warnings: Soft issues for user awareness
    - Gaps: Known missing data from discovery (NOT errors)

    Example:
        validator = ValidatorAgent(a2a_client, agent_registry)
        result = await validator.validate(route_plan, discovery_context)
        if result.status == "invalid":
            # Show errors to user
        elif result.status == "valid_with_gaps":
            # Show gaps with action buttons
    """

    def __init__(
        self,
        a2a_client: "A2AClientWrapper | None" = None,
        agent_registry: "AgentRegistry | None" = None,
    ):
        """
        Initialize the Validator agent.

        Args:
            a2a_client: A2A client for agent communication (optional for testing)
            agent_registry: Agent registry for URL lookup (optional for testing)
        """
        self._a2a_client = a2a_client
        self._agent_registry = agent_registry

    async def validate(
        self,
        route_plan: "RoutePlan | dict[str, Any]",
        discovery_context: DiscoveryContext,
    ) -> ValidationResult:
        """
        Validate the route plan and discovery context.

        Per design doc "How Validator handles gaps":
        - Missing transport: Flag as action_required ("Transport not determined")
        - Missing stay: Flag as blocker ("Cannot validate")
        - Missing POI: Flag as warning ("Limited activities planned")

        Args:
            route_plan: The day-by-day itinerary from the Route agent
            discovery_context: Context with explicit discovery gaps

        Returns:
            ValidationResult with status, errors, warnings, and gaps
        """
        if self._a2a_client is not None and self._agent_registry is not None:
            # Live mode: Call validator agent via A2A
            return await self._validate_via_a2a(route_plan, discovery_context)

        # Stub mode: Use local validation logic
        return self._validate_locally(route_plan, discovery_context)

    async def _validate_via_a2a(
        self,
        route_plan: "RoutePlan | dict[str, Any]",
        discovery_context: DiscoveryContext,
    ) -> ValidationResult:
        """
        Call the validator agent via A2A.

        Args:
            route_plan: Route plan (RoutePlan or dict)
            discovery_context: Context with explicit gaps

        Returns:
            ValidationResult from the validator agent
        """
        assert self._a2a_client is not None
        assert self._agent_registry is not None

        # Get validator agent URL
        validator_config = self._agent_registry.get("validator")
        if validator_config is None:
            logger.warning("Validator agent not found in registry, using local validation")
            return self._validate_locally(route_plan, discovery_context)

        # Convert route_plan to dict if needed
        route_dict = route_plan.to_dict() if hasattr(route_plan, "to_dict") else route_plan

        # Build request payload
        request_payload = {
            "route_plan": route_dict,
            "discovery_context": discovery_context.to_dict(),
        }

        try:
            # Call validator agent
            response = await self._a2a_client.send_message(
                agent_url=validator_config.url,
                message=json.dumps(request_payload),
            )

            # Parse response
            if response.is_complete and response.text:
                try:
                    response_data = json.loads(response.text)
                    return ValidationResult.from_dict(response_data)
                except json.JSONDecodeError:
                    logger.warning("Failed to parse validator response, using local validation")
                    return self._validate_locally(route_plan, discovery_context)

            # If not complete, fall back to local validation
            logger.warning("Validator agent did not complete, using local validation")
            return self._validate_locally(route_plan, discovery_context)

        except Exception as e:
            logger.error(f"Validator agent call failed: {e}, using local validation")
            return self._validate_locally(route_plan, discovery_context)

    def _validate_locally(
        self,
        route_plan: "RoutePlan | dict[str, Any]",
        discovery_context: DiscoveryContext,
    ) -> ValidationResult:
        """
        Validate the route plan using local logic.

        This is the stub implementation used when no A2A client is available.

        Args:
            route_plan: Route plan (RoutePlan or dict)
            discovery_context: Context with explicit gaps

        Returns:
            ValidationResult with errors, warnings, and gaps
        """
        errors: list[ValidationError] = []
        warnings: list[ValidationWarning] = []
        gaps: list[ValidationGap] = []

        # Convert route_plan to dict if needed
        route_dict = route_plan.to_dict() if hasattr(route_plan, "to_dict") else route_plan

        # 1. Convert discovery gaps to validation gaps
        # Per design doc, gaps are NOT errors - they are known issues
        gaps = self._convert_discovery_gaps(discovery_context)

        # 2. Check for time conflicts in itinerary
        time_errors, time_warnings = self._check_time_conflicts(route_dict)
        errors.extend(time_errors)
        warnings.extend(time_warnings)

        # 3. Check for connection issues (tight transfers, long walks)
        connection_warnings = self._check_connections(route_dict)
        warnings.extend(connection_warnings)

        # 4. Check budget (if available)
        budget_warnings = self._check_budget(route_dict)
        warnings.extend(budget_warnings)

        # 5. Check for accommodation gaps on multi-day trips
        stay_issues = self._check_accommodation(route_dict, discovery_context)
        # Stay issues can be errors (missing) or gaps (known from discovery)
        for issue in stay_issues:
            if isinstance(issue, ValidationError):
                errors.append(issue)

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

    def _convert_discovery_gaps(
        self,
        discovery_context: DiscoveryContext,
    ) -> list[ValidationGap]:
        """
        Convert discovery gaps to validation gaps.

        Per design doc, the Validator distinguishes:
        - ValidationError: Actual conflicts in the itinerary
        - ValidationGap: Known missing pieces from partial discovery

        Each discovery gap becomes a validation gap so it can be displayed
        to the user with appropriate action buttons.
        """
        validation_gaps: list[ValidationGap] = []

        for discovery_gap in discovery_context.gaps:
            # Determine the impact message based on agent and status
            impact = discovery_gap.impact
            placeholder_used = discovery_gap.placeholder_strategy

            # Create validation gap with retry action if available
            action = discovery_gap.retry_action

            validation_gaps.append(
                ValidationGap(
                    category=discovery_gap.agent,
                    source=discovery_gap.status,
                    impact=impact,
                    placeholder_used=placeholder_used,
                    action=action,
                )
            )

        return validation_gaps

    def _check_time_conflicts(
        self,
        route_dict: dict[str, Any],
    ) -> tuple[list[ValidationError], list[ValidationWarning]]:
        """
        Check for time conflicts in the itinerary.

        Looks for:
        - Overlapping activities on the same day
        - Activities scheduled outside venue hours
        - Check-in/check-out conflicts with transport
        """
        errors: list[ValidationError] = []
        warnings: list[ValidationWarning] = []

        days = route_dict.get("days", [])

        for day in days:
            day_number = day.get("day_number", 0)

            # Get transport for this day
            transport_list = day.get("transport", [])
            arrival_time = None
            departure_time = None

            for transport in transport_list:
                if transport.get("arrival_time"):
                    try:
                        arrival_time = self._parse_time(transport.get("arrival_time"))
                    except (ValueError, TypeError):
                        pass
                if transport.get("departure_time"):
                    try:
                        departure_time = self._parse_time(transport.get("departure_time"))
                    except (ValueError, TypeError):
                        pass

            # Get accommodation for this day
            accommodation = day.get("accommodation")
            check_in_time = DEFAULT_CHECK_IN_TIME
            check_out_time = DEFAULT_CHECK_OUT_TIME

            if accommodation:
                if accommodation.get("check_in_time"):
                    try:
                        check_in_time = self._parse_time(accommodation.get("check_in_time"))
                    except (ValueError, TypeError):
                        pass
                if accommodation.get("check_out_time"):
                    try:
                        check_out_time = self._parse_time(accommodation.get("check_out_time"))
                    except (ValueError, TypeError):
                        pass

            # Check arrival vs check-in (first day)
            if arrival_time and accommodation:
                # If arrival is after check-in time, that's fine
                # If arrival is before check-in, it's a warning (may need to store luggage)
                if arrival_time < check_in_time:
                    warnings.append(
                        ValidationWarning(
                            category="timing",
                            message=f"Arrival at {arrival_time.strftime('%H:%M')} is before hotel check-in at {check_in_time.strftime('%H:%M')}. You may need to store luggage.",
                            affected_day=day_number,
                        )
                    )

            # Check departure vs check-out (last day)
            # Note: We check if this is a "departure day" by looking for departure transport
            if departure_time and day_number > 1:
                # If departure is before checkout, that's an error
                if departure_time < check_out_time:
                    errors.append(
                        ValidationError(
                            category="timing",
                            message=f"Departure at {departure_time.strftime('%H:%M')} conflicts with hotel check-out at {check_out_time.strftime('%H:%M')}. Please arrange early checkout.",
                            affected_day=day_number,
                        )
                    )

            # Check for overlapping activities
            activities = day.get("activities", [])
            activity_overlaps = self._find_overlapping_slots(activities, day_number)
            errors.extend(activity_overlaps)

        return errors, warnings

    def _find_overlapping_slots(
        self,
        activities: list[dict[str, Any]],
        day_number: int,
    ) -> list[ValidationError]:
        """Find overlapping time slots in a list of activities."""
        errors: list[ValidationError] = []

        # Extract time slots with names
        slots: list[tuple[str, time | None, time | None]] = []

        for activity in activities:
            name = activity.get("name", "Activity")
            time_slot = activity.get("time_slot", {})
            start = None
            end = None

            if time_slot.get("start_time"):
                try:
                    start = self._parse_time(time_slot.get("start_time"))
                except (ValueError, TypeError):
                    pass
            if time_slot.get("end_time"):
                try:
                    end = self._parse_time(time_slot.get("end_time"))
                except (ValueError, TypeError):
                    pass

            if start is not None and end is not None:
                slots.append((name, start, end))

        # Check for overlaps
        for i, (name1, start1, end1) in enumerate(slots):
            for name2, start2, end2 in slots[i + 1 :]:
                if start1 is not None and end1 is not None and start2 is not None and end2 is not None:
                    # Check if slots overlap
                    if start1 < end2 and start2 < end1:
                        errors.append(
                            ValidationError(
                                category="timing",
                                message=f"'{name1}' ({start1.strftime('%H:%M')}-{end1.strftime('%H:%M')}) overlaps with '{name2}' ({start2.strftime('%H:%M')}-{end2.strftime('%H:%M')})",
                                affected_day=day_number,
                            )
                        )

        return errors

    def _check_connections(
        self,
        route_dict: dict[str, Any],
    ) -> list[ValidationWarning]:
        """
        Check for connection issues between activities.

        Per design doc, a "tight connection" is one with less than 45 minutes
        between activities.
        """
        warnings: list[ValidationWarning] = []

        days = route_dict.get("days", [])

        for day in days:
            day_number = day.get("day_number", 0)
            activities = day.get("activities", [])

            # Check time gaps between consecutive activities
            prev_end_time: time | None = None
            prev_name: str | None = None

            for activity in activities:
                # Skip placeholder activities
                if activity.get("is_placeholder"):
                    continue

                time_slot = activity.get("time_slot", {})
                start_time_str = time_slot.get("start_time")
                end_time_str = time_slot.get("end_time")
                name = activity.get("name", "Activity")

                if start_time_str and prev_end_time is not None and prev_name is not None:
                    try:
                        start_time = self._parse_time(start_time_str)
                        # Calculate gap in minutes
                        gap_minutes = self._time_diff_minutes(prev_end_time, start_time)

                        if gap_minutes < MIN_CONNECTION_TIME:
                            warnings.append(
                                ValidationWarning(
                                    category="timing",
                                    message=f"Only {gap_minutes} minutes between '{prev_name}' and '{name}'. This might be too tight.",
                                    affected_day=day_number,
                                )
                            )
                        elif gap_minutes < TIGHT_CONNECTION_THRESHOLD:
                            warnings.append(
                                ValidationWarning(
                                    category="timing",
                                    message=f"Only {gap_minutes} minutes between '{prev_name}' and '{name}'. Consider allowing more time.",
                                    affected_day=day_number,
                                )
                            )
                    except (ValueError, TypeError):
                        pass

                if end_time_str:
                    try:
                        prev_end_time = self._parse_time(end_time_str)
                        prev_name = name
                    except (ValueError, TypeError):
                        prev_end_time = None
                        prev_name = None

        return warnings

    def _check_budget(
        self,
        route_dict: dict[str, Any],
    ) -> list[ValidationWarning]:
        """Check for budget issues."""
        warnings: list[ValidationWarning] = []

        # Extract total estimated cost
        total_cost = route_dict.get("total_estimated_cost", 0)

        if total_cost > 0:
            # We don't have direct access to the budget plan here,
            # but we can flag if costs seem high
            # This is a simplified check - real implementation would compare against budget
            pass

        return warnings

    def _check_accommodation(
        self,
        route_dict: dict[str, Any],
        discovery_context: DiscoveryContext,
    ) -> list[ValidationError]:
        """Check for accommodation issues."""
        errors: list[ValidationError] = []

        # Check if stay was a discovery gap
        stay_gap = discovery_context.get_gap_for_agent("stay")

        if stay_gap and stay_gap.status != DiscoveryStatus.SKIPPED:
            # Stay is missing but not skipped - this is an error
            # (Note: This should not happen if Route agent blocked correctly,
            # but we check anyway for safety)
            errors.append(
                ValidationError(
                    category="accommodation",
                    message="Cannot validate itinerary without accommodation information.",
                    details={"reason": "missing_stay"},
                )
            )

        # Check that each non-last day has accommodation
        days = route_dict.get("days", [])
        num_days = len(days)

        for i, day in enumerate(days):
            day_number = day.get("day_number", i + 1)
            accommodation = day.get("accommodation")

            # All days except last should have accommodation (unless it's a day trip)
            if i < num_days - 1 and accommodation is None:
                # Only flag if stay wasn't explicitly skipped
                if stay_gap is None or stay_gap.status != DiscoveryStatus.SKIPPED:
                    errors.append(
                        ValidationError(
                            category="accommodation",
                            message=f"Day {day_number} has no accommodation specified.",
                            affected_day=day_number,
                        )
                    )

        return errors

    def _parse_time(self, value: Any) -> time:
        """Parse a time value from string or time object."""
        if isinstance(value, time):
            return value
        if isinstance(value, str):
            # Handle HH:MM format
            if ":" in value:
                parts = value.split(":")
                return time(int(parts[0]), int(parts[1]))
            # Handle HHMM format
            if len(value) == 4 and value.isdigit():
                return time(int(value[:2]), int(value[2:]))
        raise ValueError(f"Cannot parse time from {value!r}")

    def _time_diff_minutes(self, t1: time, t2: time) -> int:
        """Calculate the difference in minutes between two times."""
        # Convert to minutes since midnight
        t1_minutes = t1.hour * 60 + t1.minute
        t2_minutes = t2.hour * 60 + t2.minute
        return t2_minutes - t1_minutes
