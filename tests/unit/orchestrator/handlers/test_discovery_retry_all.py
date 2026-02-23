"""Unit tests for retry_discovery handling in DiscoveryHandler.

Per ORCH-104 and design doc Modification Handling section:
- retry_discovery event resets all discovery state
- Cancels in-flight discovery job (best-effort)
- Creates fresh discovery job for all agents
- Updates current_job_id and transitions to DISCOVERY_IN_PROGRESS

Tests cover:
- State reset (discovery_results, itinerary_draft, last_synced_job_id)
- Job creation for fresh discovery
- In-flight job cancellation
- Phase and checkpoint transitions
- Response format with job_id and stream_url
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
def workflow_state_at_approval() -> WorkflowState:
    """Create a workflow state at itinerary approval checkpoint with existing discovery results."""
    state = WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_test456",
        phase=Phase.DISCOVERY_PLANNING,
        checkpoint="itinerary_approval",
        workflow_version=1,
        trip_spec={
            "destination": "Tokyo",
            "start_date": "2024-03-10",
            "end_date": "2024-03-17",
            "num_travelers": 2,
        },
    )
    # Add discovery results and itinerary draft
    state.discovery_results = {
        "transport": {"status": "success", "data": {"flights": []}},
        "stay": {"status": "success", "data": {"hotels": []}},
    }
    state.itinerary_draft = {
        "destination": "Tokyo",
        "days": [{"day_number": 1}],
    }
    state.last_synced_job_id = "old_job_123"
    state.current_job_id = "old_job_123"
    return state


@pytest.fixture
def workflow_state_in_progress() -> WorkflowState:
    """Create a workflow state in DISCOVERY_IN_PROGRESS phase."""
    state = WorkflowState(
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
    state.current_job_id = "running_job_123"
    return state


@pytest.fixture
def state_data_at_approval(workflow_state_at_approval: WorkflowState) -> WorkflowStateData:
    """Create WorkflowStateData matching the state at approval."""
    return WorkflowStateData(
        session_id=workflow_state_at_approval.session_id,
        consultation_id=workflow_state_at_approval.consultation_id,
        phase=workflow_state_at_approval.phase.value,
        checkpoint=workflow_state_at_approval.checkpoint,
        current_step="planning",
        workflow_version=workflow_state_at_approval.workflow_version,
    )


@pytest.fixture
def state_data_in_progress(workflow_state_in_progress: WorkflowState) -> WorkflowStateData:
    """Create WorkflowStateData matching the state in progress."""
    return WorkflowStateData(
        session_id=workflow_state_in_progress.session_id,
        consultation_id=workflow_state_in_progress.consultation_id,
        phase=workflow_state_in_progress.phase.value,
        checkpoint=workflow_state_in_progress.checkpoint,
        current_step="running",
        workflow_version=workflow_state_in_progress.workflow_version,
    )


@pytest.fixture
def running_job() -> DiscoveryJob:
    """Create a running discovery job."""
    return DiscoveryJob(
        job_id="running_job_123",
        consultation_id="cons_test456",
        workflow_version=1,
        status=JobStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
        agent_progress={
            agent: AgentProgress(agent=agent, status="running")
            for agent in DISCOVERY_AGENTS
        },
        pipeline_stage="discovery",
    )


@pytest.fixture
def completed_job() -> DiscoveryJob:
    """Create a completed discovery job."""
    return DiscoveryJob(
        job_id="old_job_123",
        consultation_id="cons_test456",
        workflow_version=1,
        status=JobStatus.COMPLETED,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        agent_progress={
            agent: AgentProgress(agent=agent, status="completed")
            for agent in DISCOVERY_AGENTS
        },
        pipeline_stage="completed",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test: retry_discovery resets state
# ═══════════════════════════════════════════════════════════════════════════════


class TestRetryDiscoveryResetsState:
    """Tests that retry_discovery properly resets discovery state."""

    @pytest.mark.asyncio
    async def test_retry_discovery_clears_discovery_results(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data_at_approval: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that retry_discovery clears discovery_results."""
        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data_at_approval,
            discovery_job_store=discovery_job_store,
        )

        # Verify state has discovery_results
        assert handler.state.discovery_results is not None

        # Execute retry_discovery
        event = WorkflowEvent(type="retry_discovery")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Start over",
            event=event,
        )

        # Verify discovery_results was cleared
        assert handler.state.discovery_results is None

    @pytest.mark.asyncio
    async def test_retry_discovery_clears_itinerary_draft(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data_at_approval: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that retry_discovery clears itinerary_draft."""
        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data_at_approval,
            discovery_job_store=discovery_job_store,
        )

        # Verify state has itinerary_draft
        assert handler.state.itinerary_draft is not None

        # Execute retry_discovery
        event = WorkflowEvent(type="retry_discovery")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Start over",
            event=event,
        )

        # Verify itinerary_draft was cleared
        assert handler.state.itinerary_draft is None

    @pytest.mark.asyncio
    async def test_retry_discovery_clears_last_synced_job_id(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data_at_approval: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that retry_discovery clears last_synced_job_id."""
        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data_at_approval,
            discovery_job_store=discovery_job_store,
        )

        # Verify state has last_synced_job_id
        assert handler.state.last_synced_job_id is not None

        # Execute retry_discovery
        event = WorkflowEvent(type="retry_discovery")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Start over",
            event=event,
        )

        # Verify last_synced_job_id was cleared
        assert handler.state.last_synced_job_id is None


# ═══════════════════════════════════════════════════════════════════════════════
# Test: retry_discovery starts new job
# ═══════════════════════════════════════════════════════════════════════════════


class TestRetryDiscoveryStartsNewJob:
    """Tests that retry_discovery creates a fresh discovery job."""

    @pytest.mark.asyncio
    async def test_retry_discovery_creates_new_job(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data_at_approval: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that retry_discovery creates a new discovery job."""
        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data_at_approval,
            discovery_job_store=discovery_job_store,
        )

        # Execute retry_discovery
        event = WorkflowEvent(type="retry_discovery")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Start over",
            event=event,
        )

        # Verify a new job was created
        assert result.response.success is True
        assert "job_id" in result.response.data

        # Verify job in store
        job_id = result.response.data["job_id"]
        job = await discovery_job_store.get_job(job_id, "cons_test456")
        assert job is not None
        assert job.status == JobStatus.RUNNING

    @pytest.mark.asyncio
    async def test_retry_discovery_job_has_all_agents_pending(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data_at_approval: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that new job has all agents in pending status."""
        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data_at_approval,
            discovery_job_store=discovery_job_store,
        )

        # Execute retry_discovery
        event = WorkflowEvent(type="retry_discovery")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Start over",
            event=event,
        )

        # Verify all agents are pending
        job_id = result.response.data["job_id"]
        job = await discovery_job_store.get_job(job_id, "cons_test456")

        for agent in DISCOVERY_AGENTS:
            assert agent in job.agent_progress
            assert job.agent_progress[agent].status == "pending"

    @pytest.mark.asyncio
    async def test_retry_discovery_updates_current_job_id(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data_at_approval: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that retry_discovery updates state.current_job_id."""
        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data_at_approval,
            discovery_job_store=discovery_job_store,
        )

        old_job_id = handler.state.current_job_id

        # Execute retry_discovery
        event = WorkflowEvent(type="retry_discovery")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Start over",
            event=event,
        )

        # Verify current_job_id was updated
        assert handler.state.current_job_id is not None
        assert handler.state.current_job_id != old_job_id
        assert handler.state.current_job_id == result.response.data["job_id"]

    @pytest.mark.asyncio
    async def test_retry_discovery_returns_stream_url(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data_at_approval: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that retry_discovery returns stream_url for progress tracking."""
        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data_at_approval,
            discovery_job_store=discovery_job_store,
        )

        # Execute retry_discovery
        event = WorkflowEvent(type="retry_discovery")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Start over",
            event=event,
        )

        # Verify stream_url is returned
        assert "stream_url" in result.response.data
        assert "/discovery/stream" in result.response.data["stream_url"]
        assert handler.state.session_id in result.response.data["stream_url"]


# ═══════════════════════════════════════════════════════════════════════════════
# Test: retry_discovery cancels existing job
# ═══════════════════════════════════════════════════════════════════════════════


class TestRetryDiscoveryCancelsExistingJob:
    """Tests that retry_discovery cancels in-flight discovery job."""

    @pytest.mark.asyncio
    async def test_retry_discovery_cancels_running_job(
        self,
        workflow_state_in_progress: WorkflowState,
        state_data_in_progress: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
        running_job: DiscoveryJob,
    ):
        """Test that retry_discovery cancels a running discovery job."""
        # Save running job to store
        await discovery_job_store.save_job(running_job)

        handler = DiscoveryHandler(
            state=workflow_state_in_progress,
            state_data=state_data_in_progress,
            discovery_job_store=discovery_job_store,
        )

        # Execute retry_discovery
        event = WorkflowEvent(type="retry_discovery")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Start over",
            event=event,
        )

        # Verify old job was cancelled
        old_job = await discovery_job_store.get_job("running_job_123", "cons_test456")
        assert old_job.status == JobStatus.CANCELLED
        assert old_job.completed_at is not None

    @pytest.mark.asyncio
    async def test_retry_discovery_returns_cancelled_job_id(
        self,
        workflow_state_in_progress: WorkflowState,
        state_data_in_progress: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
        running_job: DiscoveryJob,
    ):
        """Test that retry_discovery response includes cancelled_job_id."""
        # Save running job to store
        await discovery_job_store.save_job(running_job)

        handler = DiscoveryHandler(
            state=workflow_state_in_progress,
            state_data=state_data_in_progress,
            discovery_job_store=discovery_job_store,
        )

        # Execute retry_discovery
        event = WorkflowEvent(type="retry_discovery")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Start over",
            event=event,
        )

        # Verify response includes cancelled_job_id
        assert "cancelled_job_id" in result.response.data
        assert result.response.data["cancelled_job_id"] == "running_job_123"

    @pytest.mark.asyncio
    async def test_retry_discovery_skips_cancel_for_completed_job(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data_at_approval: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
        completed_job: DiscoveryJob,
    ):
        """Test that retry_discovery doesn't cancel already completed job."""
        # Save completed job to store
        await discovery_job_store.save_job(completed_job)

        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data_at_approval,
            discovery_job_store=discovery_job_store,
        )

        # Execute retry_discovery
        event = WorkflowEvent(type="retry_discovery")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Start over",
            event=event,
        )

        # Verify old job is still completed (not cancelled)
        old_job = await discovery_job_store.get_job("old_job_123", "cons_test456")
        assert old_job.status == JobStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_retry_discovery_handles_missing_job_gracefully(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data_at_approval: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that retry_discovery handles missing job gracefully."""
        # State has job_id but job not in store (e.g., expired)
        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data_at_approval,
            discovery_job_store=discovery_job_store,
        )

        # Execute retry_discovery - should not fail
        event = WorkflowEvent(type="retry_discovery")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Start over",
            event=event,
        )

        # Should still succeed
        assert result.response.success is True
        assert "job_id" in result.response.data


# ═══════════════════════════════════════════════════════════════════════════════
# Test: retry_discovery phase transitions
# ═══════════════════════════════════════════════════════════════════════════════


class TestRetryDiscoveryPhaseTransitions:
    """Tests that retry_discovery properly transitions phase and checkpoint."""

    @pytest.mark.asyncio
    async def test_retry_discovery_sets_phase_to_discovery_in_progress(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data_at_approval: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that retry_discovery transitions phase to DISCOVERY_IN_PROGRESS."""
        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data_at_approval,
            discovery_job_store=discovery_job_store,
        )

        # Verify initial phase
        assert handler.state.phase == Phase.DISCOVERY_PLANNING

        # Execute retry_discovery
        event = WorkflowEvent(type="retry_discovery")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Start over",
            event=event,
        )

        # Verify phase transition
        assert handler.state.phase == Phase.DISCOVERY_IN_PROGRESS

    @pytest.mark.asyncio
    async def test_retry_discovery_clears_checkpoint(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data_at_approval: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that retry_discovery clears the checkpoint."""
        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data_at_approval,
            discovery_job_store=discovery_job_store,
        )

        # Verify initial checkpoint
        assert handler.state.checkpoint == "itinerary_approval"

        # Execute retry_discovery
        event = WorkflowEvent(type="retry_discovery")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Start over",
            event=event,
        )

        # Verify checkpoint is cleared
        assert handler.state.checkpoint is None

    @pytest.mark.asyncio
    async def test_retry_discovery_sets_current_step_to_running(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data_at_approval: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that retry_discovery sets current_step to running."""
        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data_at_approval,
            discovery_job_store=discovery_job_store,
        )

        # Execute retry_discovery
        event = WorkflowEvent(type="retry_discovery")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Start over",
            event=event,
        )

        # Verify current_step
        assert handler.state.current_step == "running"

    @pytest.mark.asyncio
    async def test_retry_discovery_syncs_to_state_data(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data_at_approval: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that retry_discovery syncs changes to state_data."""
        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data_at_approval,
            discovery_job_store=discovery_job_store,
        )

        # Execute retry_discovery
        event = WorkflowEvent(type="retry_discovery")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Start over",
            event=event,
        )

        # Verify state_data was synced
        assert result.state_data.phase == "discovery_in_progress"
        assert result.state_data.checkpoint is None
        assert result.state_data.current_step == "running"


# ═══════════════════════════════════════════════════════════════════════════════
# Test: Response format
# ═══════════════════════════════════════════════════════════════════════════════


class TestRetryDiscoveryResponseFormat:
    """Tests for retry_discovery response format."""

    @pytest.mark.asyncio
    async def test_retry_discovery_response_success(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data_at_approval: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that retry_discovery returns success response."""
        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data_at_approval,
            discovery_job_store=discovery_job_store,
        )

        # Execute retry_discovery
        event = WorkflowEvent(type="retry_discovery")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Start over",
            event=event,
        )

        # Verify response
        assert result.response.success is True
        assert "Restarting" in result.response.message

    @pytest.mark.asyncio
    async def test_retry_discovery_response_data_includes_action(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data_at_approval: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that response data includes action=retry_discovery."""
        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data_at_approval,
            discovery_job_store=discovery_job_store,
        )

        # Execute retry_discovery
        event = WorkflowEvent(type="retry_discovery")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Start over",
            event=event,
        )

        # Verify action in data
        assert result.response.data.get("action") == "retry_discovery"

    @pytest.mark.asyncio
    async def test_retry_discovery_response_includes_ui_directive(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data_at_approval: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that response includes UI directive with status action."""
        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data_at_approval,
            discovery_job_store=discovery_job_store,
        )

        # Execute retry_discovery
        event = WorkflowEvent(type="retry_discovery")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Start over",
            event=event,
        )

        # Verify UI directive
        assert result.response.ui is not None
        assert len(result.response.ui.actions) > 0
        # Should have a "View Progress" or similar action
        action_labels = [a.label for a in result.response.ui.actions]
        assert any("Progress" in label or "Status" in label for label in action_labels)
