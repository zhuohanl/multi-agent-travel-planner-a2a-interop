"""
Unit tests for terminal action handling in workflow_turn.

Tests the cancel_workflow and start_new action handling per ORCH-030.

Per design doc (State Gating at Checkpoints section):
- cancel_workflow: Sets phase=CANCELLED, clears checkpoint, cancels in-flight jobs
- start_new: Increments workflow_version, generates new consultation_id, invalidates old
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.orchestrator.models.workflow_state import Phase, WorkflowState
from src.orchestrator.models.conversation import AgentConversation
from src.orchestrator.storage import (
    ConsultationIndexEntry,
    InMemoryConsultationIndexStore,
    InMemoryDiscoveryJobStore,
    InMemoryWorkflowStateStore,
    WorkflowStateData,
    JobStatus,
)
from src.orchestrator.storage.discovery_jobs import DiscoveryJob
from src.orchestrator.tools.workflow_turn import (
    handle_cancel_workflow,
    handle_start_new_workflow,
    _cancel_discovery_job,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Test Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def workflow_state() -> WorkflowState:
    """Create a test workflow state in CLARIFICATION phase."""
    return WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_old123",
        workflow_version=1,
        phase=Phase.CLARIFICATION,
        checkpoint=None,
        current_step="gathering",
        trip_spec={"destination": "Tokyo", "dates": "2026-03-10..2026-03-17"},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def workflow_state_data() -> WorkflowStateData:
    """Create a test workflow state data."""
    return WorkflowStateData(
        session_id="sess_test123",
        consultation_id="cons_old123",
        workflow_version=1,
        phase="clarification",
        checkpoint=None,
        current_step="gathering",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        etag="test_etag_123",
    )


@pytest.fixture
def discovery_job_store() -> InMemoryDiscoveryJobStore:
    """Create an in-memory discovery job store."""
    return InMemoryDiscoveryJobStore()


@pytest.fixture
def consultation_index_store() -> InMemoryConsultationIndexStore:
    """Create an in-memory consultation index store."""
    return InMemoryConsultationIndexStore()


# ═══════════════════════════════════════════════════════════════════════════════
# cancel_workflow Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCancelWorkflow:
    """Tests for handle_cancel_workflow function."""

    @pytest.mark.asyncio
    async def test_cancel_workflow_sets_cancelled_phase(
        self, workflow_state: WorkflowState, workflow_state_data: WorkflowStateData
    ):
        """Cancel workflow should transition to CANCELLED phase."""
        response, updated_state_data = await handle_cancel_workflow(
            state=workflow_state,
            state_data=workflow_state_data,
        )

        assert response.success is True
        assert workflow_state.phase == Phase.CANCELLED
        assert updated_state_data.phase == "cancelled"
        assert "cancelled" in response.message.lower()

    @pytest.mark.asyncio
    async def test_cancel_workflow_clears_checkpoint(
        self, workflow_state_data: WorkflowStateData
    ):
        """Cancel workflow should clear any active checkpoint."""
        # Set up state at a checkpoint
        state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_test",
            workflow_version=1,
            phase=Phase.CLARIFICATION,
            checkpoint="trip_spec_approval",
        )
        workflow_state_data.checkpoint = "trip_spec_approval"

        response, updated_state_data = await handle_cancel_workflow(
            state=state,
            state_data=workflow_state_data,
        )

        assert response.success is True
        assert state.checkpoint is None
        assert updated_state_data.checkpoint is None

    @pytest.mark.asyncio
    async def test_cancel_workflow_sets_cancelled_at(
        self, workflow_state: WorkflowState, workflow_state_data: WorkflowStateData
    ):
        """Cancel workflow should set cancelled_at timestamp."""
        before = datetime.now(timezone.utc)

        response, _ = await handle_cancel_workflow(
            state=workflow_state,
            state_data=workflow_state_data,
        )

        after = datetime.now(timezone.utc)

        assert response.success is True
        assert workflow_state.cancelled_at is not None
        assert before <= workflow_state.cancelled_at <= after

    @pytest.mark.asyncio
    async def test_cancel_workflow_idempotent_already_cancelled(
        self, workflow_state_data: WorkflowStateData
    ):
        """Cancel workflow should be idempotent for already-cancelled state."""
        state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_test",
            workflow_version=1,
            phase=Phase.CANCELLED,
        )

        response, _ = await handle_cancel_workflow(
            state=state,
            state_data=workflow_state_data,
        )

        assert response.success is True
        assert "already cancelled" in response.message.lower()

    @pytest.mark.asyncio
    async def test_cancel_workflow_rejects_completed_phase(
        self, workflow_state_data: WorkflowStateData
    ):
        """Cancel workflow should reject if already COMPLETED."""
        state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_test",
            workflow_version=1,
            phase=Phase.COMPLETED,
        )

        response, _ = await handle_cancel_workflow(
            state=state,
            state_data=workflow_state_data,
        )

        assert response.success is False
        assert response.error_code == "INVALID_STATE_TRANSITION"
        assert "completed" in response.message.lower()

    @pytest.mark.asyncio
    async def test_cancel_workflow_rejects_failed_phase(
        self, workflow_state_data: WorkflowStateData
    ):
        """Cancel workflow should reject if already FAILED."""
        state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_test",
            workflow_version=1,
            phase=Phase.FAILED,
        )

        response, _ = await handle_cancel_workflow(
            state=state,
            state_data=workflow_state_data,
        )

        assert response.success is False
        assert response.error_code == "INVALID_STATE_TRANSITION"
        assert "failed" in response.message.lower()

    @pytest.mark.asyncio
    async def test_cancel_workflow_clears_current_job_id(
        self, workflow_state_data: WorkflowStateData
    ):
        """Cancel workflow should clear current_job_id."""
        state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_test",
            workflow_version=1,
            phase=Phase.DISCOVERY_IN_PROGRESS,
            current_job_id="job_test123",
        )

        response, _ = await handle_cancel_workflow(
            state=state,
            state_data=workflow_state_data,
        )

        assert response.success is True
        assert state.current_job_id is None

    @pytest.mark.asyncio
    async def test_cancel_workflow_cancels_discovery_job(
        self,
        workflow_state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Cancel workflow should cancel in-flight discovery job."""
        # Create a running job
        job = DiscoveryJob(
            job_id="job_test123",
            consultation_id="cons_test",
            workflow_version=1,
            status=JobStatus.RUNNING,
        )
        await discovery_job_store.save_job(job)

        state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_test",
            workflow_version=1,
            phase=Phase.DISCOVERY_IN_PROGRESS,
            current_job_id="job_test123",
        )

        response, _ = await handle_cancel_workflow(
            state=state,
            state_data=workflow_state_data,
            discovery_job_store=discovery_job_store,
        )

        # Verify job was cancelled
        cancelled_job = await discovery_job_store.get_job("job_test123", "cons_test")
        assert cancelled_job.status == JobStatus.CANCELLED
        assert cancelled_job.cancelled_at is not None

    @pytest.mark.asyncio
    async def test_cancel_workflow_includes_start_new_action(
        self, workflow_state: WorkflowState, workflow_state_data: WorkflowStateData
    ):
        """Cancel workflow response should include start_new UI action."""
        response, _ = await handle_cancel_workflow(
            state=workflow_state,
            state_data=workflow_state_data,
        )

        assert response.ui is not None
        assert "actions" in response.ui
        actions = response.ui["actions"]
        assert len(actions) > 0
        assert actions[0]["event"]["type"] == "start_new"

    @pytest.mark.asyncio
    async def test_cancel_workflow_retains_consultation_id(
        self, workflow_state: WorkflowState, workflow_state_data: WorkflowStateData
    ):
        """Cancel workflow should retain consultation_id for analytics/audit."""
        original_consultation_id = workflow_state.consultation_id

        response, _ = await handle_cancel_workflow(
            state=workflow_state,
            state_data=workflow_state_data,
        )

        assert response.success is True
        assert workflow_state.consultation_id == original_consultation_id
        assert response.data["consultation_id"] == original_consultation_id


# ═══════════════════════════════════════════════════════════════════════════════
# start_new Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestStartNewWorkflow:
    """Tests for handle_start_new_workflow function."""

    @pytest.mark.asyncio
    async def test_start_new_increments_workflow_version(
        self,
        workflow_state_data: WorkflowStateData,
        consultation_index_store: InMemoryConsultationIndexStore,
    ):
        """Start new should increment workflow_version."""
        state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_old",
            workflow_version=1,
            phase=Phase.CANCELLED,
        )

        response, updated_state_data = await handle_start_new_workflow(
            state=state,
            state_data=workflow_state_data,
            consultation_index_store=consultation_index_store,
        )

        assert response.success is True
        assert state.workflow_version == 2
        assert updated_state_data.workflow_version == 2

    @pytest.mark.asyncio
    async def test_start_new_generates_new_consultation_id(
        self,
        workflow_state_data: WorkflowStateData,
        consultation_index_store: InMemoryConsultationIndexStore,
    ):
        """Start new should generate a new consultation_id."""
        old_consultation_id = "cons_old123"
        state = WorkflowState(
            session_id="sess_test",
            consultation_id=old_consultation_id,
            workflow_version=1,
            phase=Phase.CANCELLED,
        )

        response, updated_state_data = await handle_start_new_workflow(
            state=state,
            state_data=workflow_state_data,
            consultation_index_store=consultation_index_store,
        )

        assert response.success is True
        assert state.consultation_id != old_consultation_id
        assert state.consultation_id.startswith("cons_")
        assert updated_state_data.consultation_id == state.consultation_id

    @pytest.mark.asyncio
    async def test_start_new_transitions_to_clarification(
        self,
        workflow_state_data: WorkflowStateData,
        consultation_index_store: InMemoryConsultationIndexStore,
    ):
        """Start new should transition to CLARIFICATION phase."""
        state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_old",
            workflow_version=1,
            phase=Phase.COMPLETED,
        )

        response, updated_state_data = await handle_start_new_workflow(
            state=state,
            state_data=workflow_state_data,
            consultation_index_store=consultation_index_store,
        )

        assert response.success is True
        assert state.phase == Phase.CLARIFICATION
        assert updated_state_data.phase == "clarification"

    @pytest.mark.asyncio
    async def test_start_new_clears_workflow_data(
        self,
        workflow_state_data: WorkflowStateData,
        consultation_index_store: InMemoryConsultationIndexStore,
    ):
        """Start new should clear trip_spec, discovery_results, etc."""
        state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_old",
            workflow_version=1,
            phase=Phase.CANCELLED,
            trip_spec={"destination": "Tokyo"},
            discovery_results={"flights": [{"id": "f1"}]},
            itinerary_draft={"days": []},
            current_job_id="job_123",
        )

        response, _ = await handle_start_new_workflow(
            state=state,
            state_data=workflow_state_data,
            consultation_index_store=consultation_index_store,
        )

        assert response.success is True
        assert state.trip_spec is None
        assert state.discovery_results is None
        assert state.itinerary_draft is None
        assert state.current_job_id is None

    @pytest.mark.asyncio
    async def test_start_new_retains_session_id(
        self,
        workflow_state_data: WorkflowStateData,
        consultation_index_store: InMemoryConsultationIndexStore,
    ):
        """Start new should retain session_id for session continuity."""
        original_session_id = "sess_test123"
        state = WorkflowState(
            session_id=original_session_id,
            consultation_id="cons_old",
            workflow_version=1,
            phase=Phase.CANCELLED,
        )

        response, _ = await handle_start_new_workflow(
            state=state,
            state_data=workflow_state_data,
            consultation_index_store=consultation_index_store,
        )

        assert response.success is True
        assert state.session_id == original_session_id

    @pytest.mark.asyncio
    async def test_start_new_invalidates_old_consultation_id(
        self,
        workflow_state_data: WorkflowStateData,
        consultation_index_store: InMemoryConsultationIndexStore,
    ):
        """Start new should delete old consultation_index entry."""
        old_consultation_id = "cons_old123"

        # Create old consultation index entry
        await consultation_index_store.add_session(
            session_id="sess_test",
            consultation_id=old_consultation_id,
            workflow_version=1,
        )

        state = WorkflowState(
            session_id="sess_test",
            consultation_id=old_consultation_id,
            workflow_version=1,
            phase=Phase.CANCELLED,
        )

        response, _ = await handle_start_new_workflow(
            state=state,
            state_data=workflow_state_data,
            consultation_index_store=consultation_index_store,
        )

        # Old consultation should be deleted
        old_lookup = await consultation_index_store.get_session_for_consultation(old_consultation_id)
        assert old_lookup is None

    @pytest.mark.asyncio
    async def test_start_new_creates_new_consultation_index(
        self,
        workflow_state_data: WorkflowStateData,
        consultation_index_store: InMemoryConsultationIndexStore,
    ):
        """Start new should create new consultation_index entry."""
        state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_old",
            workflow_version=1,
            phase=Phase.CANCELLED,
        )

        response, _ = await handle_start_new_workflow(
            state=state,
            state_data=workflow_state_data,
            consultation_index_store=consultation_index_store,
        )

        # New consultation should be created
        new_consultation_id = state.consultation_id
        new_lookup = await consultation_index_store.get_session_for_consultation(new_consultation_id)

        assert new_lookup is not None
        assert new_lookup.consultation_id == new_consultation_id
        assert new_lookup.session_id == "sess_test"
        assert new_lookup.workflow_version == 2

    @pytest.mark.asyncio
    async def test_start_new_clears_agent_context_ids(
        self,
        workflow_state_data: WorkflowStateData,
        consultation_index_store: InMemoryConsultationIndexStore,
    ):
        """Start new should clear agent_context_ids."""
        from src.orchestrator.models.workflow_state import AgentA2AState

        state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_old",
            workflow_version=1,
            phase=Phase.CANCELLED,
            agent_context_ids={
                "clarifier": AgentA2AState(context_id="ctx_123", task_id="task_456"),
                "stay": AgentA2AState(context_id="ctx_789"),
            },
        )

        response, updated_state_data = await handle_start_new_workflow(
            state=state,
            state_data=workflow_state_data,
            consultation_index_store=consultation_index_store,
        )

        assert response.success is True
        assert state.agent_context_ids == {}
        assert updated_state_data.agent_context_ids == {}

    @pytest.mark.asyncio
    async def test_start_new_response_includes_new_consultation_id(
        self,
        workflow_state_data: WorkflowStateData,
        consultation_index_store: InMemoryConsultationIndexStore,
    ):
        """Start new response should include new consultation_id."""
        state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_old",
            workflow_version=1,
            phase=Phase.CANCELLED,
        )

        response, _ = await handle_start_new_workflow(
            state=state,
            state_data=workflow_state_data,
            consultation_index_store=consultation_index_store,
        )

        assert response.success is True
        assert response.data["consultation_id"] == state.consultation_id
        assert response.data["is_new_workflow"] is True

    @pytest.mark.asyncio
    async def test_start_new_from_completed_phase(
        self,
        workflow_state_data: WorkflowStateData,
        consultation_index_store: InMemoryConsultationIndexStore,
    ):
        """Start new should work from COMPLETED phase."""
        state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_old",
            workflow_version=1,
            phase=Phase.COMPLETED,
            itinerary_id="itn_123",
        )

        response, _ = await handle_start_new_workflow(
            state=state,
            state_data=workflow_state_data,
            consultation_index_store=consultation_index_store,
        )

        assert response.success is True
        assert state.phase == Phase.CLARIFICATION
        assert state.itinerary_id is None  # Cleared

    @pytest.mark.asyncio
    async def test_start_new_from_failed_phase(
        self,
        workflow_state_data: WorkflowStateData,
        consultation_index_store: InMemoryConsultationIndexStore,
    ):
        """Start new should work from FAILED phase."""
        state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_old",
            workflow_version=1,
            phase=Phase.FAILED,
        )

        response, _ = await handle_start_new_workflow(
            state=state,
            state_data=workflow_state_data,
            consultation_index_store=consultation_index_store,
        )

        assert response.success is True
        assert state.phase == Phase.CLARIFICATION

    @pytest.mark.asyncio
    async def test_start_new_includes_welcome_message(
        self,
        workflow_state_data: WorkflowStateData,
        consultation_index_store: InMemoryConsultationIndexStore,
    ):
        """Start new response should include welcoming message."""
        state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_old",
            workflow_version=1,
            phase=Phase.CANCELLED,
        )

        response, _ = await handle_start_new_workflow(
            state=state,
            state_data=workflow_state_data,
            consultation_index_store=consultation_index_store,
        )

        assert response.success is True
        # Should have a message about starting new trip
        assert "new" in response.message.lower() or "travel" in response.message.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# _cancel_discovery_job Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCancelDiscoveryJob:
    """Tests for _cancel_discovery_job helper function."""

    @pytest.mark.asyncio
    async def test_cancel_running_job(
        self, discovery_job_store: InMemoryDiscoveryJobStore
    ):
        """Should cancel a running job."""
        job = DiscoveryJob(
            job_id="job_test",
            consultation_id="cons_test",
            workflow_version=1,
            status=JobStatus.RUNNING,
        )
        await discovery_job_store.save_job(job)

        await _cancel_discovery_job(
            job_id="job_test",
            consultation_id="cons_test",
            discovery_job_store=discovery_job_store,
        )

        updated_job = await discovery_job_store.get_job("job_test", "cons_test")
        assert updated_job.status == JobStatus.CANCELLED
        assert updated_job.cancelled_at is not None

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_job(
        self, discovery_job_store: InMemoryDiscoveryJobStore
    ):
        """Should handle nonexistent job gracefully."""
        # Should not raise
        await _cancel_discovery_job(
            job_id="job_nonexistent",
            consultation_id="cons_test",
            discovery_job_store=discovery_job_store,
        )

    @pytest.mark.asyncio
    async def test_cancel_already_completed_job(
        self, discovery_job_store: InMemoryDiscoveryJobStore
    ):
        """Should not change status of already-completed job."""
        job = DiscoveryJob(
            job_id="job_test",
            consultation_id="cons_test",
            workflow_version=1,
            status=JobStatus.COMPLETED,
        )
        await discovery_job_store.save_job(job)

        await _cancel_discovery_job(
            job_id="job_test",
            consultation_id="cons_test",
            discovery_job_store=discovery_job_store,
        )

        updated_job = await discovery_job_store.get_job("job_test", "cons_test")
        # Status should remain COMPLETED
        assert updated_job.status == JobStatus.COMPLETED
