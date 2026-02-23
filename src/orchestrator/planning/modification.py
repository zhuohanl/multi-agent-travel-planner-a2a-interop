"""
Modification analysis and selective agent re-runs.

Per design doc Modification Handling section:
- analyze_modification() uses LLM to decide which agents to re-run
- execute_modification() re-runs only affected discovery agents
- Planning pipeline always re-runs after discovery modification
- User returns to CHECKPOINT 2 (itinerary_approval) with updated itinerary

The LLM considers:
- User's modification request
- Current trip_spec and itinerary draft
- Previous discovery request history
- Which agents are affected by the requested change

Example modifications:
- "Change the hotel to something closer to the station" -> re-run stay agent
- "Extend by 2 days" -> re-run transport, stay, events, dining agents
- "Add more outdoor activities" -> re-run poi agent
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.orchestrator.agent.llm import OrchestratorLLM, RunResult
    from src.orchestrator.handlers.discovery import DiscoveryResults
    from src.orchestrator.models.workflow_state import WorkflowState
    from src.orchestrator.planning.pipeline import PlanningResult
    from src.shared.a2a.client_wrapper import A2AClientWrapper
    from src.shared.a2a.registry import AgentRegistry

logger = logging.getLogger(__name__)

# Discovery agents per design doc
DISCOVERY_AGENTS = frozenset(["transport", "stay", "poi", "events", "dining"])

# Planning agents that always re-run after discovery modification
PLANNING_AGENTS = ["aggregator", "budget", "route", "validator"]

# Default modification strategies per agent
AGENT_MODIFICATION_HINTS = {
    "transport": ["flight change", "date change", "departure/arrival time", "airline preference"],
    "stay": ["hotel change", "location preference", "amenity requirement", "room type", "hotel area"],
    "poi": ["activity preference", "attraction type", "outdoor/indoor", "sightseeing"],
    "events": ["event type", "concert", "show", "sports", "festival", "date-specific events"],
    "dining": ["cuisine preference", "dietary requirement", "restaurant type", "budget change for food"],
}


@dataclass
class ModificationPlan:
    """
    Output from analyze_modification.

    Per design doc, ModificationPlan specifies:
    - agents_to_rerun: Which discovery agents need to execute again
    - new_constraints: Updated constraints to pass to the agents
    - exclusions: Items from previous results to exclude
    - reasoning: Why these agents were selected

    Example:
        ModificationPlan(
            agents_to_rerun=["stay"],
            new_constraints={"location": "near Shinjuku", "amenities": ["view"]},
            exclusions={"stay": ["Hotel ABC"]},  # Don't suggest this hotel again
            reasoning="Only hotel preference changed"
        )
    """
    agents_to_rerun: list[str] = field(default_factory=list)
    new_constraints: dict[str, Any] = field(default_factory=dict)
    exclusions: dict[str, list[str]] = field(default_factory=dict)
    reasoning: str = ""

    def __post_init__(self) -> None:
        """Validate agents_to_rerun contains only valid agents."""
        invalid = set(self.agents_to_rerun) - DISCOVERY_AGENTS
        if invalid:
            raise ValueError(f"Invalid agents in modification plan: {invalid}")

    def has_agents_to_rerun(self) -> bool:
        """Check if any agents need to be re-run."""
        return len(self.agents_to_rerun) > 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "agents_to_rerun": self.agents_to_rerun,
            "new_constraints": self.new_constraints,
            "exclusions": self.exclusions,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModificationPlan:
        """Deserialize from dictionary."""
        return cls(
            agents_to_rerun=data.get("agents_to_rerun", []),
            new_constraints=data.get("new_constraints", {}),
            exclusions=data.get("exclusions", {}),
            reasoning=data.get("reasoning", ""),
        )

    @classmethod
    def from_llm_response(cls, response_text: str) -> ModificationPlan:
        """Parse LLM response into ModificationPlan.

        The LLM is expected to return JSON matching the ModificationPlan schema.
        This method handles parsing errors gracefully.

        Args:
            response_text: Raw text response from LLM

        Returns:
            Parsed ModificationPlan or empty plan on error
        """
        try:
            # Find JSON in the response (may have surrounding text)
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1

            if json_start == -1 or json_end == 0:
                logger.warning("No JSON found in LLM response: %s", response_text[:100])
                return cls(reasoning="Failed to parse LLM response - no JSON found")

            json_str = response_text[json_start:json_end]
            data = json.loads(json_str)

            return cls.from_dict(data)

        except json.JSONDecodeError as e:
            logger.error("Failed to parse LLM response as JSON: %s", e)
            return cls(reasoning=f"Failed to parse LLM response: {e}")
        except ValueError as e:
            # Invalid agents in response
            logger.error("Invalid agents in LLM response: %s", e)
            return cls(reasoning=str(e))


@dataclass
class ModificationResult:
    """
    Result of executing a modification.

    Attributes:
        success: Whether the modification was successful
        discovery_results: Updated discovery results after re-running agents
        planning_result: Result from re-running the planning pipeline
        message: Human-readable message about the modification
        plan: The ModificationPlan that was executed
    """
    success: bool
    discovery_results: "DiscoveryResults | None" = None
    planning_result: "PlanningResult | None" = None
    message: str = ""
    plan: ModificationPlan | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        result: dict[str, Any] = {
            "success": self.success,
            "message": self.message,
        }
        if self.discovery_results is not None:
            result["discovery_results"] = self.discovery_results.to_dict()
        if self.planning_result is not None:
            result["planning_result"] = self.planning_result.to_dict()
        if self.plan is not None:
            result["plan"] = self.plan.to_dict()
        return result


def _build_modification_prompt(
    request: str,
    state: "WorkflowState",
) -> str:
    """
    Build the prompt for LLM modification analysis.

    Per design doc, the prompt includes:
    - User's modification request
    - Current trip spec (destination, dates)
    - Current itinerary draft summary
    - Previous discovery request history
    - Available agents and what they handle

    Args:
        request: User's modification request (e.g., "change the hotel")
        state: Current workflow state with trip and itinerary info

    Returns:
        Formatted prompt for the LLM
    """
    # Extract trip info
    trip_spec = getattr(state, "trip_spec", None)
    destination = trip_spec.get("destination", "unknown") if trip_spec else "unknown"
    start_date = trip_spec.get("start_date", "") if trip_spec else ""
    end_date = trip_spec.get("end_date", "") if trip_spec else ""

    # Summarize itinerary draft
    itinerary_draft = getattr(state, "itinerary_draft", None)
    itinerary_summary = "No itinerary yet"
    if itinerary_draft:
        days = itinerary_draft.get("days", [])
        itinerary_summary = f"{len(days)} days planned"
        if days:
            # Include first day highlights
            first_day = days[0]
            activities = first_day.get("activities", [])
            if activities:
                itinerary_summary += f", Day 1: {len(activities)} activities"

    # Get discovery request history if available
    discovery_requests = getattr(state, "discovery_requests", {})
    history_lines = []
    for agent, requests in discovery_requests.items():
        if requests:
            history_lines.append(f"  {agent}: {len(requests)} previous request(s)")
    discovery_history = "\n".join(history_lines) if history_lines else "  No previous discovery requests"

    # Build agent capabilities reference
    agent_capabilities = "\n".join([
        f"  - {agent}: handles {', '.join(hints)}"
        for agent, hints in AGENT_MODIFICATION_HINTS.items()
    ])

    prompt = f"""User's modification request: "{request}"

Current trip:
- Destination: {destination}
- Dates: {start_date} to {end_date}
- Current itinerary: {itinerary_summary}

Previous discovery requests:
{discovery_history}

Available agents and their domains:
{agent_capabilities}

Analyze the modification request and decide:
1. Which agents need to re-run? (transport, stay, poi, events, dining)
2. What new constraints should be passed to these agents?
3. What from previous results should be excluded?

Return your analysis as JSON with this exact structure:
{{
    "agents_to_rerun": ["agent1", "agent2"],
    "new_constraints": {{"key": "value"}},
    "exclusions": {{"agent": ["item to exclude"]}},
    "reasoning": "Brief explanation of your decision"
}}

Only include agents that are actually affected by the modification.
For example, "change the hotel" only affects "stay", not other agents.
If dates change, most agents may need to re-run."""

    return prompt


async def analyze_modification(
    request: str,
    state: "WorkflowState",
    llm: "OrchestratorLLM | None" = None,
) -> ModificationPlan:
    """
    Analyze a modification request and decide which agents to re-run.

    Per design doc Modification Handling section:
    - LLM analyzes the request against current trip context
    - Returns ModificationPlan with agents_to_rerun, new_constraints, exclusions
    - Reasoning is included for transparency

    Args:
        request: User's modification request (e.g., "change the hotel to something closer")
        state: Current workflow state with trip_spec, itinerary_draft, discovery_requests
        llm: OrchestratorLLM for making the analysis (optional for testing)

    Returns:
        ModificationPlan specifying what agents to re-run

    Example:
        plan = await analyze_modification(
            request="hotel closer to Shinjuku station, with a view",
            state=state
        )
        # Returns:
        # ModificationPlan(
        #   agents_to_rerun=["stay"],
        #   new_constraints={"location": "near Shinjuku", "amenities": ["view"]},
        #   reasoning="Only hotel preference changed"
        # )
    """
    if llm is None:
        # Without LLM, use heuristic classification
        return _analyze_modification_heuristic(request, state)

    # Build prompt for LLM
    prompt = _build_modification_prompt(request, state)

    try:
        # Get LLM session and thread
        from src.orchestrator.azure_agent import AgentType

        session_id = state.session_id or "modification_analysis"
        thread_id = llm.ensure_thread_exists(session_id, AgentType.PLANNER)

        # Run LLM analysis
        run_result: RunResult = await llm.create_run(
            thread_id=thread_id,
            agent_type=AgentType.PLANNER,
            message=prompt,
        )

        if run_result.is_completed and run_result.text_response:
            return ModificationPlan.from_llm_response(run_result.text_response)

        if run_result.has_failed:
            logger.error("LLM modification analysis failed: %s", run_result.error_message)
            # Fall back to heuristic
            return _analyze_modification_heuristic(request, state)

        # Unexpected state - fall back to heuristic
        logger.warning("Unexpected LLM run state: %s", run_result.status)
        return _analyze_modification_heuristic(request, state)

    except Exception as e:
        logger.error("Error in LLM modification analysis: %s", e)
        # Fall back to heuristic on any error
        return _analyze_modification_heuristic(request, state)


def _analyze_modification_heuristic(
    request: str,
    state: "WorkflowState",
) -> ModificationPlan:
    """
    Heuristic-based modification analysis (no LLM).

    Used as fallback when LLM is unavailable or fails.
    Uses keyword matching to determine affected agents.

    Args:
        request: User's modification request
        state: Current workflow state

    Returns:
        ModificationPlan based on keyword analysis
    """
    request_lower = request.lower()
    agents_to_rerun: list[str] = []
    new_constraints: dict[str, Any] = {}
    reasoning_parts: list[str] = []

    # Transport keywords
    transport_keywords = ["flight", "airline", "airport", "departure", "arrival", "fly", "travel date"]
    if any(kw in request_lower for kw in transport_keywords):
        agents_to_rerun.append("transport")
        reasoning_parts.append("transport-related terms detected")

    # Stay keywords
    stay_keywords = ["hotel", "room", "accommodation", "stay", "lodging", "hostel", "airbnb", "apartment"]
    if any(kw in request_lower for kw in stay_keywords):
        agents_to_rerun.append("stay")
        reasoning_parts.append("accommodation-related terms detected")

    # POI keywords
    poi_keywords = ["attraction", "sightseeing", "museum", "park", "activity", "activities",
                    "outdoor", "indoor", "landmark", "tour", "visit"]
    if any(kw in request_lower for kw in poi_keywords):
        agents_to_rerun.append("poi")
        reasoning_parts.append("attraction-related terms detected")

    # Events keywords
    events_keywords = ["event", "concert", "show", "festival", "sports", "game", "performance",
                       "theater", "theatre", "exhibition"]
    if any(kw in request_lower for kw in events_keywords):
        agents_to_rerun.append("events")
        reasoning_parts.append("event-related terms detected")

    # Dining keywords
    dining_keywords = ["restaurant", "food", "dining", "cuisine", "eat", "meal", "dinner",
                       "lunch", "breakfast", "cafe", "bar"]
    if any(kw in request_lower for kw in dining_keywords):
        agents_to_rerun.append("dining")
        reasoning_parts.append("dining-related terms detected")

    # Date change affects most agents
    date_keywords = ["extend", "shorten", "date", "day", "longer", "shorter", "more days", "fewer days"]
    if any(kw in request_lower for kw in date_keywords):
        # Date changes affect transport, stay, events (date-sensitive)
        for agent in ["transport", "stay", "events"]:
            if agent not in agents_to_rerun:
                agents_to_rerun.append(agent)
        reasoning_parts.append("date change affects transport, stay, and events")

    # Budget change affects budget-sensitive categories
    budget_keywords = ["budget", "cheaper", "expensive", "price", "cost", "afford", "luxury", "save money"]
    if any(kw in request_lower for kw in budget_keywords):
        # Budget changes affect stay and dining primarily
        for agent in ["stay", "dining"]:
            if agent not in agents_to_rerun:
                agents_to_rerun.append(agent)
        new_constraints["budget_preference"] = "adjusted"
        reasoning_parts.append("budget change affects stay and dining")

    # If no specific keywords found, default to checking context
    if not agents_to_rerun:
        # Generic modification - check for "change" + subject
        if "change" in request_lower:
            # Try to infer from what's being changed
            if "everything" in request_lower or "all" in request_lower:
                agents_to_rerun = list(DISCOVERY_AGENTS)
                reasoning_parts.append("'change all/everything' detected - re-running all agents")
            else:
                # Default to stay (most common modification)
                agents_to_rerun = ["stay"]
                reasoning_parts.append("generic change request - defaulting to stay")
        else:
            # Can't determine - don't re-run anything
            reasoning_parts.append("no modification keywords detected")

    reasoning = "; ".join(reasoning_parts) if reasoning_parts else "Heuristic analysis"

    return ModificationPlan(
        agents_to_rerun=agents_to_rerun,
        new_constraints=new_constraints,
        exclusions={},
        reasoning=reasoning,
    )


async def execute_modification(
    plan: ModificationPlan,
    state: "WorkflowState",
    a2a_client: "A2AClientWrapper | None" = None,
    agent_registry: "AgentRegistry | None" = None,
) -> ModificationResult:
    """
    Execute a modification plan by re-running affected agents.

    Per design doc Downstream Re-run section:
    1. Re-run only the discovery agents specified in the plan
    2. Always re-run the full planning pipeline after discovery
    3. Return to CHECKPOINT 2 (itinerary_approval) with updated itinerary

    Args:
        plan: ModificationPlan from analyze_modification()
        state: Current workflow state
        a2a_client: A2A client for agent communication (optional for testing)
        agent_registry: Agent registry for URL lookup (optional for testing)

    Returns:
        ModificationResult with updated discovery_results and planning_result
    """
    if not plan.has_agents_to_rerun():
        return ModificationResult(
            success=False,
            message="No agents to re-run in the modification plan",
            plan=plan,
        )

    # Import here to avoid circular imports
    from src.orchestrator.handlers.discovery import (
        AgentDiscoveryResult,
        DiscoveryResults,
    )
    from src.orchestrator.planning import pipeline as planning_pipeline

    # Get existing discovery results from state
    existing_results = getattr(state, "discovery_results", None)
    if existing_results is None:
        existing_results = DiscoveryResults()
    elif isinstance(existing_results, dict):
        existing_results = DiscoveryResults.from_dict(existing_results)

    # Get trip spec
    trip_spec = getattr(state, "trip_spec", {})
    if trip_spec is None:
        trip_spec = {}

    # Apply new constraints to trip spec
    modified_trip_spec = dict(trip_spec)
    modified_trip_spec.update(plan.new_constraints)

    # Re-run affected discovery agents
    logger.info("Re-running discovery agents: %s", plan.agents_to_rerun)

    updated_results = await _rerun_discovery_agents(
        agents=plan.agents_to_rerun,
        existing_results=existing_results,
        trip_spec=modified_trip_spec,
        exclusions=plan.exclusions,
        a2a_client=a2a_client,
        agent_registry=agent_registry,
    )

    # Always re-run the planning pipeline per design doc
    logger.info("Re-running planning pipeline (Aggregator -> Budget -> Route -> Validator)")

    planning_result = await planning_pipeline.run_planning_pipeline(
        discovery_results=updated_results,
        trip_spec=modified_trip_spec,
        a2a_client=a2a_client,
        agent_registry=agent_registry,
    )

    # Build result message
    agents_str = ", ".join(plan.agents_to_rerun)
    if planning_result.success:
        message = f"Successfully re-ran {agents_str} and updated the itinerary."
    else:
        message = f"Re-ran {agents_str} but encountered issues: {planning_result.blocker or 'unknown'}"

    return ModificationResult(
        success=planning_result.success,
        discovery_results=updated_results,
        planning_result=planning_result,
        message=message,
        plan=plan,
    )


async def _rerun_discovery_agents(
    agents: list[str],
    existing_results: "DiscoveryResults",
    trip_spec: dict[str, Any],
    exclusions: dict[str, list[str]],
    a2a_client: "A2AClientWrapper | None" = None,
    agent_registry: "AgentRegistry | None" = None,
) -> "DiscoveryResults":
    """
    Re-run specific discovery agents and merge with existing results.

    Only the specified agents are re-run. Results from other agents
    are preserved from existing_results.

    Args:
        agents: List of agent names to re-run
        existing_results: Existing DiscoveryResults to preserve/update
        trip_spec: Trip specification for discovery request
        exclusions: Items to exclude from results per agent
        a2a_client: A2A client for agent communication
        agent_registry: Agent registry for URL lookup

    Returns:
        Updated DiscoveryResults with re-run agents updated
    """
    import asyncio
    from datetime import datetime, timezone

    from src.orchestrator.handlers.discovery import (
        AGENT_TIMEOUTS,
        AgentDiscoveryResult,
        DEFAULT_AGENT_TIMEOUT,
        DiscoveryResults,
    )

    # Create a copy of existing results to update
    updated_results = DiscoveryResults(
        transport=existing_results.transport,
        stay=existing_results.stay,
        poi=existing_results.poi,
        events=existing_results.events,
        dining=existing_results.dining,
    )

    async def run_single_agent(agent: str) -> tuple[str, AgentDiscoveryResult]:
        """Run one agent and return its result."""
        try:
            timeout = AGENT_TIMEOUTS.get(agent, DEFAULT_AGENT_TIMEOUT)

            async with asyncio.timeout(timeout):
                result_data = await _call_discovery_agent(
                    agent=agent,
                    trip_spec=trip_spec,
                    exclusions=exclusions.get(agent, []),
                    a2a_client=a2a_client,
                    agent_registry=agent_registry,
                )

            return agent, AgentDiscoveryResult(
                agent=agent,
                status="success",
                data=result_data,
                timestamp=datetime.now(timezone.utc),
            )

        except asyncio.TimeoutError:
            return agent, AgentDiscoveryResult(
                agent=agent,
                status="timeout",
                message=f"Timeout after {AGENT_TIMEOUTS.get(agent, DEFAULT_AGENT_TIMEOUT)}s",
                retry_possible=True,
                timestamp=datetime.now(timezone.utc),
            )

        except Exception as e:
            logger.error("Error re-running agent %s: %s", agent, e)
            return agent, AgentDiscoveryResult(
                agent=agent,
                status="error",
                message=str(e),
                retry_possible=True,
                timestamp=datetime.now(timezone.utc),
            )

    # Run specified agents in parallel
    results = await asyncio.gather(*[run_single_agent(a) for a in agents])

    # Update the results
    for agent_name, agent_result in results:
        setattr(updated_results, agent_name, agent_result)

    return updated_results


async def _call_discovery_agent(
    agent: str,
    trip_spec: dict[str, Any],
    exclusions: list[str],
    a2a_client: "A2AClientWrapper | None" = None,
    agent_registry: "AgentRegistry | None" = None,
) -> dict[str, Any]:
    """
    Call a single discovery agent with exclusions.

    Args:
        agent: Agent name
        trip_spec: Trip specification
        exclusions: Items to exclude from this agent's results
        a2a_client: A2A client (optional)
        agent_registry: Agent registry (optional)

    Returns:
        Agent response data
    """
    if a2a_client is None or agent_registry is None:
        # Stub response for testing
        return _create_stub_modification_result(agent, trip_spec, exclusions)

    try:
        agent_config = agent_registry.get(agent)
        if agent_config is None:
            raise ValueError(f"Agent '{agent}' not found in registry")

        # Format discovery request with exclusions
        request_message = _format_modification_request(agent, trip_spec, exclusions)

        # Call agent
        response = await a2a_client.send_message(
            agent_url=agent_config.url,
            message=request_message,
        )

        return {
            "text": response.text,
            "data": response.data,
        }

    except Exception as e:
        logger.error("Error calling discovery agent %s: %s", agent, e)
        raise


def _format_modification_request(
    agent: str,
    trip_spec: dict[str, Any],
    exclusions: list[str],
) -> str:
    """Format a modification request for a specific agent."""
    destination = trip_spec.get("destination", "unknown")
    start_date = trip_spec.get("start_date", "")
    end_date = trip_spec.get("end_date", "")

    # Base prompts per agent
    base_prompts = {
        "transport": f"Find alternative flight options to {destination} from {start_date} to {end_date}.",
        "stay": f"Find alternative hotel options in {destination} from {start_date} to {end_date}.",
        "poi": f"Find different attractions and points of interest in {destination}.",
        "events": f"Find different events happening in {destination} between {start_date} and {end_date}.",
        "dining": f"Find different restaurant recommendations in {destination}.",
    }

    prompt = base_prompts.get(agent, f"Search for alternative {agent} options in {destination}.")

    # Add exclusions if any
    if exclusions:
        exclusion_str = ", ".join(exclusions)
        prompt += f" Please exclude the following from results: {exclusion_str}."

    # Add any new constraints from trip_spec
    budget_preference = trip_spec.get("budget_preference")
    if budget_preference:
        prompt += f" Budget preference: {budget_preference}."

    location_preference = trip_spec.get("location")
    if location_preference:
        prompt += f" Location preference: {location_preference}."

    return prompt


def _create_stub_modification_result(
    agent: str,
    trip_spec: dict[str, Any],
    exclusions: list[str],
) -> dict[str, Any]:
    """Create a stub modification result for testing."""
    destination = trip_spec.get("destination", "destination")

    stub_results = {
        "transport": {
            "options": [
                {"type": "flight", "airline": "Alternative Airways", "price": 480},
            ],
            "message": f"Found alternative flight options to {destination}",
            "excluded": exclusions,
        },
        "stay": {
            "options": [
                {"type": "hotel", "name": "Alternative Hotel", "price_per_night": 160},
            ],
            "message": f"Found alternative hotel options in {destination}",
            "excluded": exclusions,
        },
        "poi": {
            "options": [
                {"name": "Alternative Attraction", "rating": 4.3},
            ],
            "message": f"Found alternative attractions in {destination}",
            "excluded": exclusions,
        },
        "events": {
            "options": [
                {"name": "Alternative Event", "date": trip_spec.get("start_date", "")},
            ],
            "message": f"Found alternative events in {destination}",
            "excluded": exclusions,
        },
        "dining": {
            "options": [
                {"name": "Alternative Restaurant", "cuisine": "local"},
            ],
            "message": f"Found alternative restaurants in {destination}",
            "excluded": exclusions,
        },
    }

    return stub_results.get(agent, {"message": f"Stub result for {agent}", "excluded": exclusions})
