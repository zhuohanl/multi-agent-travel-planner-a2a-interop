"""
Unit tests for modification analysis and selective agent re-runs.

Per ORCH-081 acceptance criteria:
- analyze_modification() uses LLM to decide which agents to re-run
- ModificationPlan specifies: agents_to_rerun, new_constraints, exclusions
- execute_modification() re-runs only affected discovery agents
- Planning pipeline always runs after discovery modification
- User returns to CHECKPOINT 2 with updated itinerary
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.orchestrator.planning.modification import (
    AGENT_MODIFICATION_HINTS,
    DISCOVERY_AGENTS,
    PLANNING_AGENTS,
    ModificationPlan,
    ModificationResult,
    _analyze_modification_heuristic,
    _build_modification_prompt,
    analyze_modification,
    execute_modification,
)


# ═══════════════════════════════════════════════════════════════════════════════
# ModificationPlan Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestModificationPlan:
    """Tests for ModificationPlan dataclass."""

    def test_create_valid_plan(self):
        """Test creating a valid modification plan."""
        plan = ModificationPlan(
            agents_to_rerun=["stay", "poi"],
            new_constraints={"location": "near station"},
            exclusions={"stay": ["Hotel ABC"]},
            reasoning="User wants different hotel near station",
        )

        assert plan.agents_to_rerun == ["stay", "poi"]
        assert plan.new_constraints == {"location": "near station"}
        assert plan.exclusions == {"stay": ["Hotel ABC"]}
        assert plan.reasoning == "User wants different hotel near station"

    def test_create_empty_plan(self):
        """Test creating an empty modification plan."""
        plan = ModificationPlan()

        assert plan.agents_to_rerun == []
        assert plan.new_constraints == {}
        assert plan.exclusions == {}
        assert plan.reasoning == ""

    def test_invalid_agents_raises_error(self):
        """Test that invalid agent names raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            ModificationPlan(agents_to_rerun=["invalid_agent"])

        assert "Invalid agents" in str(exc_info.value)
        assert "invalid_agent" in str(exc_info.value)

    def test_has_agents_to_rerun_true(self):
        """Test has_agents_to_rerun returns True when agents present."""
        plan = ModificationPlan(agents_to_rerun=["stay"])
        assert plan.has_agents_to_rerun() is True

    def test_has_agents_to_rerun_false(self):
        """Test has_agents_to_rerun returns False when no agents."""
        plan = ModificationPlan()
        assert plan.has_agents_to_rerun() is False

    def test_to_dict(self):
        """Test serialization to dictionary."""
        plan = ModificationPlan(
            agents_to_rerun=["transport"],
            new_constraints={"airline": "preferred"},
            exclusions={"transport": ["Slow Airlines"]},
            reasoning="User prefers different airline",
        )

        result = plan.to_dict()

        assert result["agents_to_rerun"] == ["transport"]
        assert result["new_constraints"] == {"airline": "preferred"}
        assert result["exclusions"] == {"transport": ["Slow Airlines"]}
        assert result["reasoning"] == "User prefers different airline"

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "agents_to_rerun": ["dining", "events"],
            "new_constraints": {"cuisine": "local"},
            "exclusions": {},
            "reasoning": "User wants local food",
        }

        plan = ModificationPlan.from_dict(data)

        assert plan.agents_to_rerun == ["dining", "events"]
        assert plan.new_constraints == {"cuisine": "local"}
        assert plan.exclusions == {}
        assert plan.reasoning == "User wants local food"

    def test_from_dict_defaults(self):
        """Test from_dict with missing fields uses defaults."""
        plan = ModificationPlan.from_dict({})

        assert plan.agents_to_rerun == []
        assert plan.new_constraints == {}
        assert plan.exclusions == {}
        assert plan.reasoning == ""

    def test_from_llm_response_valid_json(self):
        """Test parsing valid JSON from LLM response."""
        response = """
        Based on your request, here's my analysis:
        {
            "agents_to_rerun": ["stay"],
            "new_constraints": {"location": "near Shinjuku"},
            "exclusions": {"stay": ["Hotel ABC"]},
            "reasoning": "Only hotel preference changed"
        }
        """

        plan = ModificationPlan.from_llm_response(response)

        assert plan.agents_to_rerun == ["stay"]
        assert plan.new_constraints == {"location": "near Shinjuku"}
        assert plan.exclusions == {"stay": ["Hotel ABC"]}
        assert "hotel preference" in plan.reasoning

    def test_from_llm_response_no_json(self):
        """Test parsing response without JSON returns empty plan."""
        response = "I couldn't understand your request"

        plan = ModificationPlan.from_llm_response(response)

        assert plan.agents_to_rerun == []
        assert "no JSON found" in plan.reasoning

    def test_from_llm_response_invalid_json(self):
        """Test parsing invalid JSON returns empty plan with error."""
        response = "{invalid json content}"

        plan = ModificationPlan.from_llm_response(response)

        assert plan.agents_to_rerun == []
        assert "Failed to parse" in plan.reasoning

    def test_from_llm_response_invalid_agents(self):
        """Test parsing response with invalid agents returns error."""
        response = """
        {
            "agents_to_rerun": ["invalid_agent"],
            "new_constraints": {},
            "exclusions": {},
            "reasoning": "test"
        }
        """

        plan = ModificationPlan.from_llm_response(response)

        assert plan.agents_to_rerun == []
        assert "Invalid agents" in plan.reasoning


# ═══════════════════════════════════════════════════════════════════════════════
# Heuristic Analysis Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestHeuristicAnalysis:
    """Tests for heuristic-based modification analysis."""

    def create_mock_state(
        self,
        destination: str = "Tokyo",
        start_date: str = "2026-03-15",
        end_date: str = "2026-03-20",
    ) -> MagicMock:
        """Create a mock workflow state."""
        state = MagicMock()
        state.session_id = "sess_123"
        state.trip_spec = {
            "destination": destination,
            "start_date": start_date,
            "end_date": end_date,
        }
        state.itinerary_draft = {"days": [{"day_number": 1}]}
        state.discovery_requests = {}
        return state

    def test_analyze_modification_hotel_change(self):
        """Test that hotel-related modifications target stay agent."""
        state = self.create_mock_state()
        plan = _analyze_modification_heuristic("change the hotel to something nicer", state)

        assert "stay" in plan.agents_to_rerun
        assert "accommodation" in plan.reasoning.lower() or "stay" in plan.reasoning.lower()

    def test_analyze_modification_flight_change(self):
        """Test that flight-related modifications target transport agent."""
        state = self.create_mock_state()
        plan = _analyze_modification_heuristic("find a different flight", state)

        assert "transport" in plan.agents_to_rerun
        assert "transport" in plan.reasoning.lower()

    def test_analyze_modification_activities(self):
        """Test that activity-related modifications target poi agent."""
        state = self.create_mock_state()
        plan = _analyze_modification_heuristic("add more outdoor activities", state)

        assert "poi" in plan.agents_to_rerun
        assert "attraction" in plan.reasoning.lower()

    def test_analyze_modification_events(self):
        """Test that event-related modifications target events agent."""
        state = self.create_mock_state()
        plan = _analyze_modification_heuristic("find concerts happening during my trip", state)

        assert "events" in plan.agents_to_rerun

    def test_analyze_modification_dining(self):
        """Test that dining-related modifications target dining agent."""
        state = self.create_mock_state()
        plan = _analyze_modification_heuristic("find restaurants with local cuisine", state)

        assert "dining" in plan.agents_to_rerun

    def test_analyze_modification_date_change(self):
        """Test that date changes affect multiple agents."""
        state = self.create_mock_state()
        plan = _analyze_modification_heuristic("extend the trip by 2 more days", state)

        # Date changes should affect transport, stay, and events
        assert "transport" in plan.agents_to_rerun
        assert "stay" in plan.agents_to_rerun
        assert "events" in plan.agents_to_rerun

    def test_analyze_modification_budget_change(self):
        """Test that budget changes affect stay and dining."""
        state = self.create_mock_state()
        plan = _analyze_modification_heuristic("find cheaper options to save money", state)

        assert "stay" in plan.agents_to_rerun
        assert "dining" in plan.agents_to_rerun
        assert "budget_preference" in plan.new_constraints

    def test_analyze_modification_multiple_keywords(self):
        """Test that multiple keywords affect multiple agents."""
        state = self.create_mock_state()
        plan = _analyze_modification_heuristic(
            "change the hotel and find different restaurants",
            state,
        )

        assert "stay" in plan.agents_to_rerun
        assert "dining" in plan.agents_to_rerun

    def test_analyze_modification_generic_change_defaults_to_stay(self):
        """Test that generic 'change' request defaults to stay."""
        state = self.create_mock_state()
        plan = _analyze_modification_heuristic("just change something", state)

        assert "stay" in plan.agents_to_rerun

    def test_analyze_modification_change_everything(self):
        """Test that 'change everything' re-runs all agents."""
        state = self.create_mock_state()
        plan = _analyze_modification_heuristic("change everything", state)

        assert set(plan.agents_to_rerun) == DISCOVERY_AGENTS

    def test_analyze_modification_no_keywords(self):
        """Test handling requests with no modification keywords."""
        state = self.create_mock_state()
        plan = _analyze_modification_heuristic("hello, how are you?", state)

        # Should not modify any agents
        assert plan.agents_to_rerun == []
        assert "no modification keywords" in plan.reasoning.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# LLM Analysis Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestLLMAnalysis:
    """Tests for LLM-based modification analysis."""

    def create_mock_state(self) -> MagicMock:
        """Create a mock workflow state."""
        state = MagicMock()
        state.session_id = "sess_123"
        state.trip_spec = {
            "destination": "Tokyo",
            "start_date": "2026-03-15",
            "end_date": "2026-03-20",
        }
        state.itinerary_draft = {"days": [{"day_number": 1}]}
        state.discovery_requests = {"stay": ["request1"]}
        return state

    def test_build_modification_prompt(self):
        """Test building the modification prompt."""
        state = self.create_mock_state()
        prompt = _build_modification_prompt("change the hotel", state)

        assert "change the hotel" in prompt
        assert "Tokyo" in prompt
        assert "2026-03-15" in prompt
        assert "agents_to_rerun" in prompt
        assert "stay" in prompt

    def test_build_prompt_with_discovery_history(self):
        """Test prompt includes discovery history when available."""
        state = self.create_mock_state()
        state.discovery_requests = {
            "stay": ["request1", "request2"],
            "transport": ["request3"],
        }

        prompt = _build_modification_prompt("change hotel", state)

        assert "stay: 2" in prompt
        assert "transport: 1" in prompt

    @pytest.mark.asyncio
    async def test_analyze_modification_without_llm_uses_heuristic(self):
        """Test that analysis without LLM falls back to heuristics."""
        state = self.create_mock_state()

        plan = await analyze_modification(
            request="change the hotel",
            state=state,
            llm=None,
        )

        assert "stay" in plan.agents_to_rerun

    @pytest.mark.asyncio
    async def test_analyze_modification_with_llm_success(self):
        """Test successful LLM analysis."""
        state = self.create_mock_state()

        # Mock LLM
        mock_llm = MagicMock()
        mock_llm.ensure_thread_exists = MagicMock(return_value="thread_123")

        # Mock run result with valid JSON response
        mock_run_result = MagicMock()
        mock_run_result.is_completed = True
        mock_run_result.has_failed = False
        mock_run_result.text_response = """
        {
            "agents_to_rerun": ["stay"],
            "new_constraints": {"location": "near station"},
            "exclusions": {},
            "reasoning": "Hotel preference changed"
        }
        """
        mock_llm.create_run = AsyncMock(return_value=mock_run_result)

        plan = await analyze_modification(
            request="change hotel to one near the station",
            state=state,
            llm=mock_llm,
        )

        assert plan.agents_to_rerun == ["stay"]
        assert plan.new_constraints == {"location": "near station"}

    @pytest.mark.asyncio
    async def test_analyze_modification_with_llm_failure_falls_back(self):
        """Test that LLM failure falls back to heuristics."""
        state = self.create_mock_state()

        # Mock LLM that fails
        mock_llm = MagicMock()
        mock_llm.ensure_thread_exists = MagicMock(return_value="thread_123")

        mock_run_result = MagicMock()
        mock_run_result.is_completed = False
        mock_run_result.has_failed = True
        mock_run_result.error_message = "LLM error"
        mock_llm.create_run = AsyncMock(return_value=mock_run_result)

        plan = await analyze_modification(
            request="change the hotel",
            state=state,
            llm=mock_llm,
        )

        # Should fall back to heuristic and still find stay
        assert "stay" in plan.agents_to_rerun

    @pytest.mark.asyncio
    async def test_analyze_modification_with_llm_exception_falls_back(self):
        """Test that LLM exception falls back to heuristics."""
        state = self.create_mock_state()

        # Mock LLM that throws exception
        mock_llm = MagicMock()
        mock_llm.ensure_thread_exists = MagicMock(side_effect=Exception("Connection error"))

        plan = await analyze_modification(
            request="change the hotel",
            state=state,
            llm=mock_llm,
        )

        # Should fall back to heuristic
        assert "stay" in plan.agents_to_rerun


# ═══════════════════════════════════════════════════════════════════════════════
# Execute Modification Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteModification:
    """Tests for execute_modification function."""

    def create_mock_state(self) -> MagicMock:
        """Create a mock workflow state."""
        state = MagicMock()
        state.session_id = "sess_123"
        state.trip_spec = {
            "destination": "Tokyo",
            "start_date": "2026-03-15",
            "end_date": "2026-03-20",
        }
        state.itinerary_draft = {"days": []}
        state.discovery_results = None
        return state

    @pytest.mark.asyncio
    async def test_execute_modification_no_agents(self):
        """Test execution with no agents to re-run."""
        state = self.create_mock_state()
        plan = ModificationPlan()  # Empty plan

        result = await execute_modification(plan, state)

        assert result.success is False
        assert "No agents to re-run" in result.message

    @pytest.mark.asyncio
    async def test_execute_modification_reruns_affected_agents(self):
        """Test that only affected agents are re-run.

        Uses stub responses (no real agents) to verify the modification
        flow correctly:
        1. Re-runs specified discovery agents
        2. Calls planning pipeline with updated results
        3. Returns success with appropriate message
        """
        state = self.create_mock_state()
        # Add stay discovery results so pipeline doesn't block on missing stay
        from src.orchestrator.handlers.discovery import (
            AgentDiscoveryResult,
            DiscoveryResults,
        )
        state.discovery_results = DiscoveryResults(
            stay=AgentDiscoveryResult(agent="stay", status="success", data={"hotel": "Test Hotel"}),
        )

        plan = ModificationPlan(
            agents_to_rerun=["stay"],
            new_constraints={"location": "near station"},
        )

        # Execute modification with stub responses
        result = await execute_modification(plan, state)

        # With stub responses, execution should succeed
        assert result.plan == plan
        # Discovery results should be updated
        assert result.discovery_results is not None
        # Stay agent should have been re-run (stub data)
        assert result.discovery_results.stay is not None

    @pytest.mark.asyncio
    async def test_execute_modification_always_reruns_planning_pipeline(self):
        """Test that planning pipeline always runs after discovery re-run.

        Verifies that the planning_result is populated, which means
        the pipeline ran after discovery re-run.
        """
        state = self.create_mock_state()
        from src.orchestrator.handlers.discovery import (
            AgentDiscoveryResult,
            DiscoveryResults,
        )
        state.discovery_results = DiscoveryResults(
            stay=AgentDiscoveryResult(agent="stay", status="success", data={"hotel": "Test"}),
        )

        plan = ModificationPlan(agents_to_rerun=["poi"])

        result = await execute_modification(plan, state)

        # Planning result should be populated (pipeline ran)
        assert result.planning_result is not None

    @pytest.mark.asyncio
    async def test_execute_modification_handles_pipeline_failure(self):
        """Test handling of planning pipeline failure.

        When stay discovery fails (not skipped), the pipeline should fail
        with a blocker about missing accommodation.
        """
        state = self.create_mock_state()
        # Create discovery results where stay is an error (not success or skipped)
        from src.orchestrator.handlers.discovery import (
            AgentDiscoveryResult,
            DiscoveryResults,
        )
        state.discovery_results = DiscoveryResults(
            stay=AgentDiscoveryResult(agent="stay", status="error", data=None),
        )

        plan = ModificationPlan(agents_to_rerun=["poi"])  # Re-run POI, not stay

        result = await execute_modification(plan, state)

        # Pipeline should fail due to missing stay
        assert result.success is False
        # The blocker message should indicate accommodation issue
        assert result.planning_result is not None
        assert "accommodation" in (result.planning_result.blocker or "").lower()

    @pytest.mark.asyncio
    async def test_execute_modification_preserves_existing_results(self):
        """Test that non-modified agents preserve their results.

        When only stay is re-run, transport should keep its original data.
        """
        state = self.create_mock_state()

        from src.orchestrator.handlers.discovery import (
            AgentDiscoveryResult,
            DiscoveryResults,
        )

        existing_transport = AgentDiscoveryResult(
            agent="transport",
            status="success",
            data={"airline": "Original Airlines"},
        )
        existing_stay = AgentDiscoveryResult(
            agent="stay",
            status="success",
            data={"hotel": "Original Hotel"},
        )
        state.discovery_results = DiscoveryResults(
            transport=existing_transport,
            stay=existing_stay,
        )

        plan = ModificationPlan(agents_to_rerun=["stay"])  # Only re-run stay

        result = await execute_modification(plan, state)

        # Transport should still have original data (not re-run)
        assert result.discovery_results is not None
        assert result.discovery_results.transport is not None
        assert result.discovery_results.transport.data == {"airline": "Original Airlines"}

        # Stay should have new data (was re-run with stubs)
        assert result.discovery_results.stay is not None
        # The stub data should be different from original
        assert result.discovery_results.stay.data != {"hotel": "Original Hotel"}


# ═══════════════════════════════════════════════════════════════════════════════
# ModificationResult Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestModificationResult:
    """Tests for ModificationResult dataclass."""

    def test_create_success_result(self):
        """Test creating a successful modification result."""
        result = ModificationResult(
            success=True,
            message="Successfully re-ran stay and updated itinerary",
        )

        assert result.success is True
        assert "stay" in result.message

    def test_to_dict(self):
        """Test serialization to dictionary."""
        plan = ModificationPlan(agents_to_rerun=["stay"])
        result = ModificationResult(
            success=True,
            message="Done",
            plan=plan,
        )

        data = result.to_dict()

        assert data["success"] is True
        assert data["message"] == "Done"
        assert "plan" in data
        assert data["plan"]["agents_to_rerun"] == ["stay"]

    def test_to_dict_without_optional_fields(self):
        """Test serialization omits None fields."""
        result = ModificationResult(
            success=False,
            message="Failed",
        )

        data = result.to_dict()

        assert "discovery_results" not in data
        assert "planning_result" not in data
        assert "plan" not in data


# ═══════════════════════════════════════════════════════════════════════════════
# Constants Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestConstants:
    """Tests for module constants."""

    def test_discovery_agents_matches_handler(self):
        """Test DISCOVERY_AGENTS matches the handler module."""
        from src.orchestrator.handlers.discovery import (
            DISCOVERY_AGENTS as HANDLER_AGENTS,
        )

        assert DISCOVERY_AGENTS == frozenset(HANDLER_AGENTS)

    def test_planning_agents_are_complete(self):
        """Test PLANNING_AGENTS includes all pipeline stages."""
        assert "aggregator" in PLANNING_AGENTS
        assert "budget" in PLANNING_AGENTS
        assert "route" in PLANNING_AGENTS
        assert "validator" in PLANNING_AGENTS

    def test_agent_modification_hints_covers_all_agents(self):
        """Test all discovery agents have modification hints."""
        for agent in DISCOVERY_AGENTS:
            assert agent in AGENT_MODIFICATION_HINTS
            assert len(AGENT_MODIFICATION_HINTS[agent]) > 0
