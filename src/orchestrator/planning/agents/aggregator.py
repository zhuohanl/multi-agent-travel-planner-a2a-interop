"""
Aggregator agent for combining discovery results.

The Aggregator is the first planning agent in the pipeline. It takes raw
discovery results from 5 domain agents (POI, Stay, Transport, Events, Dining)
and combines them into a structured format for downstream planning.

Per design doc "Downstream Pipeline with Partial Results" section:
- Include status for missing agents: ERROR, NOT_FOUND, SKIPPED, TIMEOUT
- Missing transport: Include `transport: {status: ERROR, data: null}` in output
- Missing stay: Include `stay: {status: ERROR, data: null}` in output
- Missing POI: Include `poi: {status: ERROR, data: null}` in output

The aggregated output is consumed by the Budget agent.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from src.orchestrator.handlers.discovery import (
    AgentDiscoveryResult,
    DISCOVERY_AGENTS,
    DiscoveryResults,
)
from src.orchestrator.planning.pipeline import DiscoveryContext, DiscoveryGap

if TYPE_CHECKING:
    from src.shared.a2a.client_wrapper import A2AClientWrapper
    from src.shared.a2a.registry import AgentRegistry

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Result Entry for Aggregated Output
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class AgentResultEntry:
    """
    Entry for a single agent's results in the aggregated output.

    Per design doc, each agent entry contains:
    - status: SUCCESS, ERROR, NOT_FOUND, SKIPPED, TIMEOUT
    - data: The actual discovery data (null if status != SUCCESS)
    - message: Error/status message (optional)

    Examples:
        AgentResultEntry(status="SUCCESS", data={"hotels": [...]})
        AgentResultEntry(status="ERROR", data=None, message="Connection timeout")
    """

    status: Literal["SUCCESS", "ERROR", "NOT_FOUND", "SKIPPED", "TIMEOUT"]
    data: dict[str, Any] | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        result: dict[str, Any] = {
            "status": self.status,
            "data": self.data,
        }
        if self.message:
            result["message"] = self.message
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentResultEntry:
        """Deserialize from dictionary."""
        status_raw = data.get("status", "ERROR")
        if status_raw not in ("SUCCESS", "ERROR", "NOT_FOUND", "SKIPPED", "TIMEOUT"):
            status_raw = "ERROR"
        return cls(
            status=status_raw,  # type: ignore[arg-type]
            data=data.get("data"),
            message=data.get("message"),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Aggregated Results Model
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class AggregatedResults:
    """
    Output from the Aggregator agent.

    Contains structured results from all discovery agents, with explicit
    status for each agent (including failures). This is the input to the
    Budget agent.

    Per design doc, the aggregated output structure is:
    - transport: {status: ..., data: ...}
    - stay: {status: ..., data: ...}
    - poi: {status: ..., data: ...}
    - events: {status: ..., data: ...}
    - dining: {status: ..., data: ...}
    - gaps: List of DiscoveryGap objects for non-success agents
    - destination: Trip destination (from trip_spec)
    - summary: Count of options per category
    """

    transport: AgentResultEntry
    stay: AgentResultEntry
    poi: AgentResultEntry
    events: AgentResultEntry
    dining: AgentResultEntry
    gaps: list[DiscoveryGap] = field(default_factory=list)
    destination: str = ""
    summary: dict[str, int] = field(default_factory=dict)
    aggregated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for storage/transmission."""
        return {
            "transport": self.transport.to_dict(),
            "stay": self.stay.to_dict(),
            "poi": self.poi.to_dict(),
            "events": self.events.to_dict(),
            "dining": self.dining.to_dict(),
            "gaps": [gap.to_dict() for gap in self.gaps],
            "destination": self.destination,
            "summary": self.summary,
            "aggregated_at": self.aggregated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AggregatedResults:
        """Deserialize from dictionary."""
        aggregated_at = data.get("aggregated_at")
        if isinstance(aggregated_at, str):
            aggregated_at = datetime.fromisoformat(aggregated_at)
        elif aggregated_at is None:
            aggregated_at = datetime.now(timezone.utc)

        return cls(
            transport=AgentResultEntry.from_dict(data.get("transport", {})),
            stay=AgentResultEntry.from_dict(data.get("stay", {})),
            poi=AgentResultEntry.from_dict(data.get("poi", {})),
            events=AgentResultEntry.from_dict(data.get("events", {})),
            dining=AgentResultEntry.from_dict(data.get("dining", {})),
            gaps=[DiscoveryGap.from_dict(g) for g in data.get("gaps", [])],
            destination=data.get("destination", ""),
            summary=data.get("summary", {}),
            aggregated_at=aggregated_at,
        )

    def has_gaps(self) -> bool:
        """Check if there are any gaps in the aggregated results."""
        return len(self.gaps) > 0

    def has_critical_gaps(self) -> bool:
        """Check if there are gaps that require user action (e.g., missing stay)."""
        return any(gap.user_action_required for gap in self.gaps)

    def has_transport(self) -> bool:
        """Check if transport data is available."""
        return self.transport.status == "SUCCESS" and self.transport.data is not None

    def has_stay(self) -> bool:
        """Check if stay data is available."""
        return self.stay.status == "SUCCESS" and self.stay.data is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Aggregator Agent
# ═══════════════════════════════════════════════════════════════════════════════


class AggregatorAgent:
    """
    Aggregator agent for combining discovery results.

    The Aggregator is the first agent in the planning pipeline. It takes
    raw discovery results from 5 domain agents and combines them into
    a structured format for downstream planning.

    Per design doc:
    - Includes status for missing agents: ERROR, NOT_FOUND, SKIPPED, TIMEOUT
    - Preserves all discovery data for successful agents
    - Creates gap entries for failed agents
    - Output is structured for Budget agent consumption

    The agent can operate in two modes:
    1. Stub mode (no A2A client): Uses local aggregation logic
    2. Live mode (with A2A client): Calls the aggregator agent via A2A

    Example:
        aggregator = AggregatorAgent(a2a_client, agent_registry)
        result = await aggregator.aggregate(discovery_results, context)
    """

    def __init__(
        self,
        a2a_client: "A2AClientWrapper | None" = None,
        agent_registry: "AgentRegistry | None" = None,
    ):
        """
        Initialize the Aggregator agent.

        Args:
            a2a_client: A2A client for agent communication (optional for testing)
            agent_registry: Agent registry for URL lookup (optional for testing)
        """
        self._a2a_client = a2a_client
        self._agent_registry = agent_registry

    async def aggregate(
        self,
        discovery_results: DiscoveryResults,
        discovery_context: DiscoveryContext,
        trip_spec: dict[str, Any] | None = None,
    ) -> AggregatedResults:
        """
        Aggregate discovery results into a structured format.

        Per design doc "Downstream Pipeline with Partial Results":
        - Include status for missing agents (ERROR, NOT_FOUND, SKIPPED, TIMEOUT)
        - Preserve all discovery data for successful agents
        - Create gap entries for failed agents
        - Output is structured for Budget agent consumption

        Args:
            discovery_results: Raw results from parallel discovery
            discovery_context: Context with explicit gaps
            trip_spec: Trip requirements (optional, for destination info)

        Returns:
            AggregatedResults with structured data for Budget agent
        """
        if self._a2a_client is not None and self._agent_registry is not None:
            # Live mode: Call aggregator agent via A2A
            return await self._aggregate_via_a2a(
                discovery_results, discovery_context, trip_spec
            )

        # Stub mode: Use local aggregation logic
        return self._aggregate_locally(discovery_results, discovery_context, trip_spec)

    async def _aggregate_via_a2a(
        self,
        discovery_results: DiscoveryResults,
        discovery_context: DiscoveryContext,
        trip_spec: dict[str, Any] | None,
    ) -> AggregatedResults:
        """
        Call the aggregator agent via A2A.

        Args:
            discovery_results: Raw results from parallel discovery
            discovery_context: Context with explicit gaps
            trip_spec: Trip requirements

        Returns:
            AggregatedResults from the aggregator agent
        """
        assert self._a2a_client is not None
        assert self._agent_registry is not None

        # Get aggregator agent URL
        aggregator_config = self._agent_registry.get("aggregator")
        if aggregator_config is None:
            logger.warning("Aggregator agent not found in registry, using local aggregation")
            return self._aggregate_locally(discovery_results, discovery_context, trip_spec)

        # Build request payload
        request_payload = {
            "discovery_results": discovery_results.to_dict(),
            "discovery_context": discovery_context.to_dict(),
            "trip_spec": trip_spec or {},
        }

        try:
            # Call aggregator agent
            response = await self._a2a_client.send_message(
                agent_url=aggregator_config.url,
                message=json.dumps(request_payload),
            )

            # Parse response
            if response.is_complete and response.text:
                try:
                    response_data = json.loads(response.text)
                    
                    # detects the internal AggregatedResults schema
                    if self._looks_like_aggregated_results(response_data):
                        return AggregatedResults.from_dict(response_data)
                    
                    # detects the A2A Aggregator output schema
                    if self._looks_like_agent_outputs(response_data):
                        return self._aggregate_from_agent_outputs(
                            response_data,
                            discovery_context,
                            trip_spec,
                        )
                    logger.warning(
                        "Aggregator response did not match expected schema, using local aggregation"
                    )
                    return self._aggregate_locally(discovery_results, discovery_context, trip_spec)
                except json.JSONDecodeError:
                    logger.warning("Failed to parse aggregator response, using local aggregation")
                    return self._aggregate_locally(discovery_results, discovery_context, trip_spec)

            # If not complete, fall back to local aggregation
            logger.warning("Aggregator agent did not complete, using local aggregation")
            return self._aggregate_locally(discovery_results, discovery_context, trip_spec)

        except Exception as e:
            logger.error(f"Aggregator agent call failed: {e}, using local aggregation")
            return self._aggregate_locally(discovery_results, discovery_context, trip_spec)

    def _aggregate_locally(
        self,
        discovery_results: DiscoveryResults,
        discovery_context: DiscoveryContext,
        trip_spec: dict[str, Any] | None,
    ) -> AggregatedResults:
        """
        Aggregate discovery results using local logic.

        This is the stub implementation used when no A2A client is available.

        Args:
            discovery_results: Raw results from parallel discovery
            discovery_context: Context with explicit gaps
            trip_spec: Trip requirements

        Returns:
            AggregatedResults with structured data
        """
        # Get destination from trip_spec
        destination = ""
        if trip_spec:
            destination = trip_spec.get("destination_city", trip_spec.get("destination", ""))

        # Build result entries for each agent
        transport_entry = self._build_result_entry(discovery_results.transport, "transport")
        stay_entry = self._build_result_entry(discovery_results.stay, "stay")
        poi_entry = self._build_result_entry(discovery_results.poi, "poi")
        events_entry = self._build_result_entry(discovery_results.events, "events")
        dining_entry = self._build_result_entry(discovery_results.dining, "dining")

        # Build summary counts
        summary = self._build_summary(
            transport_entry, stay_entry, poi_entry, events_entry, dining_entry
        )

        return AggregatedResults(
            transport=transport_entry,
            stay=stay_entry,
            poi=poi_entry,
            events=events_entry,
            dining=dining_entry,
            gaps=discovery_context.gaps.copy(),
            destination=destination,
            summary=summary,
        )

    def _looks_like_aggregated_results(self, data: Any) -> bool:
        """Check if payload matches AggregatedResults schema."""
        if not isinstance(data, dict):
            return False
        for key in ("transport", "stay", "poi", "events", "dining"):
            value = data.get(key)
            if isinstance(value, dict) and "status" in value:
                return True
        return False

    def _looks_like_agent_outputs(self, data: Any) -> bool:
        """Check if payload matches A2A Aggregator output schema."""
        if not isinstance(data, dict):
            return False
        return any(key in data for key in ("pois", "stays", "transport", "events", "dining"))

    def _aggregate_from_agent_outputs(
        self,
        outputs: dict[str, Any],
        discovery_context: DiscoveryContext,
        trip_spec: dict[str, Any] | None,
    ) -> AggregatedResults:
        """Convert A2A Aggregator outputs into AggregatedResults."""
        destination = ""
        if trip_spec:
            destination = trip_spec.get("destination_city", trip_spec.get("destination", ""))

        transport_entry = self._build_entry_from_output(outputs.get("transport"), "transport")
        stay_entry = self._build_entry_from_output(outputs.get("stays") or outputs.get("stay"), "stay")
        poi_entry = self._build_entry_from_output(outputs.get("pois") or outputs.get("poi"), "poi")
        events_entry = self._build_entry_from_output(outputs.get("events"), "events")
        dining_entry = self._build_entry_from_output(outputs.get("dining"), "dining")

        summary = self._build_summary(
            transport_entry, stay_entry, poi_entry, events_entry, dining_entry
        )

        return AggregatedResults(
            transport=transport_entry,
            stay=stay_entry,
            poi=poi_entry,
            events=events_entry,
            dining=dining_entry,
            gaps=discovery_context.gaps.copy(),
            destination=destination,
            summary=summary,
        )

    def _build_entry_from_output(
        self,
        output: Any,
        agent_name: str,
    ) -> AgentResultEntry:
        """Build AgentResultEntry from Aggregator agent output."""
        if not isinstance(output, dict):
            return AgentResultEntry(
                status="ERROR",
                data=None,
                message=f"{agent_name} output missing or invalid",
            )

        normalized = self._normalize_agent_output(agent_name, output)
        return AgentResultEntry(
            status="SUCCESS",
            data=normalized,
        )

    def _normalize_agent_output(
        self,
        agent_name: str,
        output: dict[str, Any],
    ) -> dict[str, Any]:
        """Normalize output keys to align with downstream expectations."""
        normalized = dict(output)
        if agent_name == "transport":
            if "options" not in normalized and "transportOptions" in normalized:
                normalized["options"] = normalized["transportOptions"]
        elif agent_name == "stay":
            if "hotels" not in normalized and "stays" in normalized:
                normalized["hotels"] = normalized["stays"]
        elif agent_name == "poi":
            if "attractions" not in normalized and "pois" in normalized:
                normalized["attractions"] = normalized["pois"]
        return normalized

    def _build_result_entry(
        self,
        agent_result: AgentDiscoveryResult | None,
        agent_name: str,
    ) -> AgentResultEntry:
        """
        Build AgentResultEntry from AgentDiscoveryResult.

        Maps the discovery result status to aggregated status and includes data.

        Args:
            agent_result: Discovery result for the agent (may be None)
            agent_name: Name of the agent (for logging)

        Returns:
            AgentResultEntry with appropriate status and data
        """
        if agent_result is None:
            return AgentResultEntry(
                status="ERROR",
                data=None,
                message=f"{agent_name} agent did not return results",
            )

        # Map status strings to aggregated status
        status_map: dict[str, Literal["SUCCESS", "ERROR", "NOT_FOUND", "SKIPPED", "TIMEOUT"]] = {
            "success": "SUCCESS",
            "error": "ERROR",
            "not_found": "NOT_FOUND",
            "skipped": "SKIPPED",
            "timeout": "TIMEOUT",
        }

        status_value = agent_result.status
        if hasattr(status_value, "value"):
            status_value = status_value.value
        mapped_status = status_map.get(str(status_value).lower(), "ERROR")

        return AgentResultEntry(
            status=mapped_status,
            data=agent_result.data if mapped_status == "SUCCESS" else None,
            message=agent_result.message if mapped_status != "SUCCESS" else None,
        )

    def _build_summary(
        self,
        transport: AgentResultEntry,
        stay: AgentResultEntry,
        poi: AgentResultEntry,
        events: AgentResultEntry,
        dining: AgentResultEntry,
    ) -> dict[str, int]:
        """
        Build summary counts for each category.

        Counts the number of options available in each category from the
        discovery data.

        Args:
            transport: Transport result entry
            stay: Stay result entry
            poi: POI result entry
            events: Events result entry
            dining: Dining result entry

        Returns:
            Dictionary with counts per category
        """
        summary: dict[str, int] = {
            "transport_options": 0,
            "stay_options": 0,
            "poi_options": 0,
            "events_options": 0,
            "dining_options": 0,
        }

        def _count_first_list(data: dict[str, Any], keys: tuple[str, ...]) -> int:
            for key in keys:
                items = data.get(key)
                if isinstance(items, list) and items:
                    return len(items)
            return 0

        # Count transport options (flights, trains, etc.)
        if transport.status == "SUCCESS" and transport.data:
            flights = transport.data.get("flights", [])
            trains = transport.data.get("trains", [])
            local_transfers = transport.data.get("localTransfers", [])
            local_passes = transport.data.get("localPasses", [])
            base_options = _count_first_list(
                transport.data, ("options", "transportOptions")
            )
            if base_options == 0:
                base_options = len(flights) + len(trains)
            summary["transport_options"] = (
                base_options + len(local_transfers) + len(local_passes)
            )

        # Count stay options (hotels, accommodations)
        if stay.status == "SUCCESS" and stay.data:
            hotels = stay.data.get("hotels", [])
            stays = stay.data.get("stays", [])
            accommodations = stay.data.get("accommodations", [])
            options = stay.data.get("options", [])
            base_options = len(hotels) if hotels else len(stays)
            if base_options == 0:
                base_options = len(accommodations) + len(options)
            summary["stay_options"] = base_options

        # Count POI options (attractions, landmarks)
        if poi.status == "SUCCESS" and poi.data:
            attractions = poi.data.get("attractions", [])
            pois = poi.data.get("pois", [])
            landmarks = poi.data.get("landmarks", [])
            options = poi.data.get("options", [])
            base_options = len(attractions) if attractions else len(pois)
            if base_options == 0:
                base_options = len(landmarks) + len(options)
            summary["poi_options"] = base_options

        # Count events options
        if events.status == "SUCCESS" and events.data:
            event_list = events.data.get("events", [])
            options = events.data.get("options", [])
            summary["events_options"] = len(event_list) + len(options)

        # Count dining options (restaurants)
        if dining.status == "SUCCESS" and dining.data:
            restaurants = dining.data.get("restaurants", [])
            options = dining.data.get("options", [])
            base_options = len(restaurants) if restaurants else len(options)
            summary["dining_options"] = base_options

        return summary
