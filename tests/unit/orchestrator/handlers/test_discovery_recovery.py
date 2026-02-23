"""Unit tests for discovery error recovery (retry_agent, skip_agent).

Per ORCH-093 and design doc Pipeline Execution with Gap Awareness:
- retry_agent re-runs a failed agent and triggers planning when all complete
- skip_agent marks agent as SKIPPED (creates a gap) and triggers planning when all complete
- Both actions require event.agent to be specified
- Both actions trigger planning pipeline when all agents reach terminal status

Tests cover:
- Validation of event.agent requirement
- Agent re-run on retry
- SKIPPED status on skip
- Planning pipeline trigger after all agents complete
- Error handling for missing jobs, unknown agents
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.orchestrator.handlers.discovery import (
    DISCOVERY_AGENTS,
    DiscoveryHandler,
)
from src.orchestrator.models.workflow_state import Phase, WorkflowState
from src.orchestrator.state_gating import Action, WorkflowEvent
from src.orchestrator.storage import WorkflowStateData
from src.orchestrator.storage.discovery_jobs import (
    AgentProgress,
    DiscoveryJob,
    InMemoryDiscoveryJobStore,
    JobStatus,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def discovery_job_store():
    """Create an in-memory discovery job store for testing."""
    return InMemoryDiscoveryJobStore()


@pytest.fixture
def workflow_state() -> WorkflowState:
    """Create a workflow state in DISCOVERY_IN_PROGRESS phase."""
    return WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_test456",
        phase=Phase.DISCOVERY_IN_PROGRESS,
        checkpoint=None,
        workflow_version=1,
        trip_spec={
            "destination": "Tokyo",
            "start_date": "2024-03-10",
            "end_date": "2024-03-17",
            "num_travelers": 2,
        },
    )


@pytest.fixture
def state_data() -> WorkflowStateData:
    """Create workflow state data for testing."""
    return WorkflowStateData(
        session_id="sess_test123",
        consultation_id="cons_test456",
        phase="discovery_in_progress",
        checkpoint=None,
        workflow_version=1,
    )


@pytest.fixture
def job_with_failures(discovery_job_store: InMemoryDiscoveryJobStore) -> DiscoveryJob:
    """Create a job with some failed agents for testing recovery."""
    job = DiscoveryJob(
        job_id="job_test123",
        consultation_id="cons_test456",
        workflow_version=1,
        status=JobStatus.PARTIAL,
        agent_progress={
            "transport": AgentProgress(agent="transport", status="completed"),
            "stay": AgentProgress(agent="stay", status="failed", message="Connection timeout"),
            "poi": AgentProgress(agent="poi", status="completed"),
            "events": AgentProgress(agent="events", status="timeout", message="Timeout after 20s"),
            "dining": AgentProgress(agent="dining", status="completed"),
        },
        discovery_results={
            "transport": {"agent": "transport", "status": "success", "data": {"options": []}},
            "poi": {"agent": "poi", "status": "success", "data": {"attractions": []}},
            "dining": {"agent": "dining", "status": "success", "data": {"restaurants": []}},
        },
    )
    return job


# ═══════════════════════════════════════════════════════════════════════════════
# Event Validation Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestEventAgentValidation:
    """Tests for event.agent requirement validation."""

    @pytest.mark.asyncio
    async def test_retry_agent_requires_agent_id(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that retry_agent event requires event.agent to be specified."""
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        # Event without agent_id
        event = WorkflowEvent(type="retry_agent", agent_id=None)
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Retry",
            event=event,
        )

        assert result.response.success is False
        assert "requires event.agent" in result.response.message
        assert result.response.data.get("error") == "missing_agent"

    @pytest.mark.asyncio
    async def test_skip_agent_requires_agent_id(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that skip_agent event requires event.agent to be specified."""
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        # Event without agent_id
        event = WorkflowEvent(type="skip_agent", agent_id=None)
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Skip",
            event=event,
        )

        assert result.response.success is False
        assert "requires event.agent" in result.response.message
        assert result.response.data.get("error") == "missing_agent"

    @pytest.mark.asyncio
    async def test_retry_agent_rejects_unknown_agent(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that retry_agent rejects unknown agent names."""
        workflow_state.current_job_id = "job_test123"
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        result = await handler._retry_agent("invalid_agent")

        assert result.response.success is False
        assert "Unknown agent" in result.response.message
        assert result.response.data.get("error") == "invalid_agent"
        assert "valid_agents" in result.response.data

    @pytest.mark.asyncio
    async def test_skip_agent_rejects_unknown_agent(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that skip_agent rejects unknown agent names."""
        workflow_state.current_job_id = "job_test123"
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        result = await handler._skip_agent("invalid_agent")

        assert result.response.success is False
        assert "Unknown agent" in result.response.message
        assert result.response.data.get("error") == "invalid_agent"


# ═══════════════════════════════════════════════════════════════════════════════
# Retry Agent Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestRetryAgent:
    """Tests for retry_agent functionality."""

    @pytest.mark.asyncio
    async def test_retry_agent_no_active_job(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test retry_agent fails when no active discovery job exists."""
        workflow_state.current_job_id = None
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        result = await handler._retry_agent("stay")

        assert result.response.success is False
        assert "No active discovery job" in result.response.message
        assert result.response.data.get("error") == "no_active_job"

    @pytest.mark.asyncio
    async def test_retry_agent_job_not_found(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test retry_agent fails when job is not found (expired)."""
        workflow_state.current_job_id = "job_nonexistent"
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        result = await handler._retry_agent("stay")

        assert result.response.success is False
        assert "not found" in result.response.message.lower()
        assert result.response.data.get("error") == "job_not_found"

    @pytest.mark.asyncio
    async def test_retry_agent_reruns_agent(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
        job_with_failures: DiscoveryJob,
    ):
        """Test that retry_agent actually re-runs the agent."""
        await discovery_job_store.save_job(job_with_failures)
        workflow_state.current_job_id = job_with_failures.job_id

        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        # Patch the _call_discovery_agent to track if it's called
        called_agents = []

        async def mock_call_agent(agent, trip_spec):
            called_agents.append(agent)
            return {"options": [], "message": "Retry succeeded"}

        with patch.object(handler, "_call_discovery_agent", mock_call_agent):
            result = await handler._retry_agent("stay")

        assert result.response.success is True
        assert "stay" in called_agents  # Agent was actually called

    @pytest.mark.asyncio
    async def test_retry_agent_updates_progress_to_running(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
        job_with_failures: DiscoveryJob,
    ):
        """Test that retry_agent sets agent progress to running before re-run."""
        await discovery_job_store.save_job(job_with_failures)
        workflow_state.current_job_id = job_with_failures.job_id

        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        # Check that progress was initially failed
        initial_job = await discovery_job_store.get_job(
            job_with_failures.job_id, job_with_failures.consultation_id
        )
        assert initial_job.agent_progress["stay"].status == "failed"

        # Mock to avoid actual agent call and return quickly
        async def mock_call_agent(agent, trip_spec):
            # At this point the progress should have been set to running
            job = await discovery_job_store.get_job(
                job_with_failures.job_id, job_with_failures.consultation_id
            )
            assert job.agent_progress[agent].status == "running"
            return {"options": []}

        with patch.object(handler, "_call_discovery_agent", mock_call_agent):
            await handler._retry_agent("stay")


# ═══════════════════════════════════════════════════════════════════════════════
# Skip Agent Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestSkipAgent:
    """Tests for skip_agent functionality."""

    @pytest.mark.asyncio
    async def test_skip_agent_no_active_job(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test skip_agent fails when no active discovery job exists."""
        workflow_state.current_job_id = None
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        result = await handler._skip_agent("stay")

        assert result.response.success is False
        assert "No active discovery job" in result.response.message

    @pytest.mark.asyncio
    async def test_skip_agent_job_not_found(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test skip_agent fails when job is not found (expired)."""
        workflow_state.current_job_id = "job_nonexistent"
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        result = await handler._skip_agent("stay")

        assert result.response.success is False
        assert "not found" in result.response.message.lower()

    @pytest.mark.asyncio
    async def test_skip_agent_sets_skipped_status(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
        job_with_failures: DiscoveryJob,
    ):
        """Test that skip_agent sets agent progress to SKIPPED (not completed)."""
        await discovery_job_store.save_job(job_with_failures)
        workflow_state.current_job_id = job_with_failures.job_id

        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        # Skip all remaining non-completed agents so we don't trigger planning
        # (we'll test planning trigger separately)
        result = await handler._skip_agent("stay")

        assert result.response.success is True

        # Check the progress was set to "skipped" (not "completed")
        updated_job = await discovery_job_store.get_job(
            job_with_failures.job_id, job_with_failures.consultation_id
        )
        assert updated_job.agent_progress["stay"].status == "skipped"
        assert "Skipped by user" in updated_job.agent_progress["stay"].message

    @pytest.mark.asyncio
    async def test_skip_agent_records_in_discovery_results(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
        job_with_failures: DiscoveryJob,
    ):
        """Test that skip_agent records the skip in discovery_results."""
        await discovery_job_store.save_job(job_with_failures)
        workflow_state.current_job_id = job_with_failures.job_id

        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        await handler._skip_agent("stay")

        updated_job = await discovery_job_store.get_job(
            job_with_failures.job_id, job_with_failures.consultation_id
        )

        # Check discovery_results has the skip recorded
        assert "stay" in updated_job.discovery_results
        assert updated_job.discovery_results["stay"]["status"] == "skipped"
        assert updated_job.discovery_results["stay"]["data"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# Planning Pipeline Trigger Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestPlanningPipelineTrigger:
    """Tests for planning pipeline trigger after recovery actions."""

    @pytest.mark.asyncio
    async def test_all_agents_terminal_detection(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that _all_agents_terminal correctly detects terminal states."""
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        # Job with all agents completed
        job_complete = DiscoveryJob(
            job_id="job_complete",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.COMPLETED,
            agent_progress={
                "transport": AgentProgress(agent="transport", status="completed"),
                "stay": AgentProgress(agent="stay", status="completed"),
                "poi": AgentProgress(agent="poi", status="completed"),
                "events": AgentProgress(agent="events", status="completed"),
                "dining": AgentProgress(agent="dining", status="completed"),
            },
        )
        assert handler._all_agents_terminal(job_complete) is True

        # Job with one agent pending
        job_pending = DiscoveryJob(
            job_id="job_pending",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.RUNNING,
            agent_progress={
                "transport": AgentProgress(agent="transport", status="completed"),
                "stay": AgentProgress(agent="stay", status="pending"),
                "poi": AgentProgress(agent="poi", status="completed"),
                "events": AgentProgress(agent="events", status="completed"),
                "dining": AgentProgress(agent="dining", status="completed"),
            },
        )
        assert handler._all_agents_terminal(job_pending) is False

        # Job with mixed terminal states (skipped, failed, completed)
        job_mixed = DiscoveryJob(
            job_id="job_mixed",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.PARTIAL,
            agent_progress={
                "transport": AgentProgress(agent="transport", status="completed"),
                "stay": AgentProgress(agent="stay", status="skipped"),
                "poi": AgentProgress(agent="poi", status="failed"),
                "events": AgentProgress(agent="events", status="timeout"),
                "dining": AgentProgress(agent="dining", status="completed"),
            },
        )
        assert handler._all_agents_terminal(job_mixed) is True

    @pytest.mark.asyncio
    async def test_skip_triggers_planning_when_all_complete(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that skip_agent triggers planning when all agents are terminal."""
        # Create a job where only one agent is not terminal
        job = DiscoveryJob(
            job_id="job_test123",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.RUNNING,
            agent_progress={
                "transport": AgentProgress(agent="transport", status="completed"),
                "stay": AgentProgress(agent="stay", status="failed"),  # Will be skipped
                "poi": AgentProgress(agent="poi", status="completed"),
                "events": AgentProgress(agent="events", status="completed"),
                "dining": AgentProgress(agent="dining", status="completed"),
            },
            discovery_results={
                "transport": {"agent": "transport", "status": "success", "data": {}},
                "poi": {"agent": "poi", "status": "success", "data": {}},
                "events": {"agent": "events", "status": "success", "data": {}},
                "dining": {"agent": "dining", "status": "success", "data": {}},
            },
        )
        await discovery_job_store.save_job(job)
        workflow_state.current_job_id = job.job_id

        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        # Mock the planning pipeline
        planning_called = []

        async def mock_finalize(job):
            planning_called.append(job.job_id)
            # Return mock itinerary preview
            from src.orchestrator.handlers.clarification import HandlerResult
            from src.orchestrator.models.responses import ToolResponse

            return HandlerResult(
                response=ToolResponse(
                    success=True,
                    message="Itinerary ready for approval",
                    data={"phase": "discovery_planning"},
                ),
                state_data=state_data,
            )

        with patch.object(handler, "_finalize_after_recovery", mock_finalize):
            result = await handler._skip_agent("stay")

        # Planning should have been triggered
        assert len(planning_called) > 0

    @pytest.mark.asyncio
    async def test_skip_does_not_trigger_planning_when_pending_agents(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that skip_agent doesn't trigger planning when other agents are pending."""
        # Create a job with multiple non-terminal agents
        job = DiscoveryJob(
            job_id="job_test123",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.RUNNING,
            agent_progress={
                "transport": AgentProgress(agent="transport", status="completed"),
                "stay": AgentProgress(agent="stay", status="failed"),  # Will be skipped
                "poi": AgentProgress(agent="poi", status="running"),  # Still running
                "events": AgentProgress(agent="events", status="pending"),  # Still pending
                "dining": AgentProgress(agent="dining", status="completed"),
            },
        )
        await discovery_job_store.save_job(job)
        workflow_state.current_job_id = job.job_id

        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        # Mock the planning pipeline - should not be called
        planning_called = []

        async def mock_finalize(job):
            planning_called.append(job.job_id)
            from src.orchestrator.handlers.clarification import HandlerResult
            from src.orchestrator.models.responses import ToolResponse

            return HandlerResult(
                response=ToolResponse(success=True, message="Planning done"),
                state_data=state_data,
            )

        with patch.object(handler, "_finalize_after_recovery", mock_finalize):
            result = await handler._skip_agent("stay")

        # Planning should NOT have been triggered
        assert len(planning_called) == 0
        assert result.response.success is True


# ═══════════════════════════════════════════════════════════════════════════════
# Helper Method Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestHelperMethods:
    """Tests for helper methods."""

    @pytest.mark.asyncio
    async def test_get_completion_message(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test completion message generation."""
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        # Job with 3 complete, 2 pending
        job = DiscoveryJob(
            job_id="job_test",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.RUNNING,
            agent_progress={
                "transport": AgentProgress(agent="transport", status="completed"),
                "stay": AgentProgress(agent="stay", status="completed"),
                "poi": AgentProgress(agent="poi", status="completed"),
                "events": AgentProgress(agent="events", status="pending"),
                "dining": AgentProgress(agent="dining", status="running"),
            },
        )

        message = handler._get_completion_message(job)
        assert "3/5" in message
        assert "2 still pending" in message

        # Job with all complete
        job.agent_progress["events"].status = "completed"
        job.agent_progress["dining"].status = "completed"

        message = handler._get_completion_message(job)
        assert "All agent searches complete" in message
