"""
Unit tests for job-to-state synchronization.

Tests cover:
- sync_job_to_state(): 4 guards, idempotency, result transfer
- finalize_job(): Terminal state validation
- resume_session_with_recovery(): Crash recovery scenarios
- check_sync_needed(): Lightweight sync check
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from src.orchestrator.discovery.state_sync import (
    SyncResult,
    check_sync_needed,
    finalize_job,
    resume_session_with_recovery,
    sync_job_to_state,
)
from src.orchestrator.models.workflow_state import Phase, WorkflowState
from src.orchestrator.storage.discovery_jobs import (
    DiscoveryJob,
    JobStatus,
    InMemoryDiscoveryJobStore,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def sample_workflow_state() -> WorkflowState:
    """Create a sample workflow state in DISCOVERY_IN_PROGRESS phase."""
    return WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_test456",
        workflow_version=1,
        phase=Phase.DISCOVERY_IN_PROGRESS,
        checkpoint=None,
        current_step="discovering",
        current_job_id="job_abc123",
        last_synced_job_id=None,
    )


@pytest.fixture
def sample_completed_job() -> DiscoveryJob:
    """Create a sample completed discovery job."""
    return DiscoveryJob(
        job_id="job_abc123",
        consultation_id="cons_test456",
        workflow_version=1,
        status=JobStatus.COMPLETED,
        discovery_results={
            "transport": {"flights": [{"id": "fl1", "price": 500}]},
            "stay": {"hotels": [{"id": "h1", "price": 200}]},
        },
        itinerary_draft={
            "days": [{"date": "2026-03-10", "activities": []}],
            "total_cost": 700,
        },
    )


@pytest.fixture
def sample_partial_job() -> DiscoveryJob:
    """Create a sample partial discovery job (some agents failed)."""
    return DiscoveryJob(
        job_id="job_abc123",
        consultation_id="cons_test456",
        workflow_version=1,
        status=JobStatus.PARTIAL,
        discovery_results={
            "transport": {"flights": [{"id": "fl1", "price": 500}]},
            "stay": {"error": "Agent timeout"},
        },
        itinerary_draft={
            "days": [{"date": "2026-03-10", "activities": []}],
            "gaps": ["stay"],
        },
    )


@pytest.fixture
def sample_failed_job() -> DiscoveryJob:
    """Create a sample failed discovery job."""
    return DiscoveryJob(
        job_id="job_abc123",
        consultation_id="cons_test456",
        workflow_version=1,
        status=JobStatus.FAILED,
        error="All agents failed",
    )


@pytest.fixture
def mock_workflow_store() -> AsyncMock:
    """Create a mock workflow store."""
    store = AsyncMock()
    return store


# ============================================================================
# Tests for sync_job_to_state()
# ============================================================================


class TestSyncJobToState:
    """Tests for the sync_job_to_state function."""

    @pytest.mark.asyncio
    async def test_successful_sync_completed_job(
        self, sample_workflow_state: WorkflowState, sample_completed_job: DiscoveryJob, mock_workflow_store: AsyncMock
    ):
        """Test successful sync of a completed job."""
        mock_workflow_store.get_by_session.return_value = sample_workflow_state
        mock_workflow_store.save_state.return_value = sample_workflow_state

        result = await sync_job_to_state(
            sample_completed_job, mock_workflow_store, session_id="sess_test123"
        )

        assert result.success is True
        assert result.synced is True
        assert "synced successfully" in result.reason
        mock_workflow_store.save_state.assert_called_once()

        # Verify state was updated correctly
        saved_state = mock_workflow_store.save_state.call_args[0][0]
        assert saved_state.phase == Phase.DISCOVERY_PLANNING
        assert saved_state.checkpoint == "itinerary_approval"
        assert saved_state.current_step == "approval"
        assert saved_state.discovery_results == sample_completed_job.discovery_results
        assert saved_state.itinerary_draft == sample_completed_job.itinerary_draft
        assert saved_state.last_synced_job_id == sample_completed_job.job_id
        assert saved_state.current_job_id is None

    @pytest.mark.asyncio
    async def test_successful_sync_partial_job(
        self, sample_workflow_state: WorkflowState, sample_partial_job: DiscoveryJob, mock_workflow_store: AsyncMock
    ):
        """Test successful sync of a partial job."""
        mock_workflow_store.get_by_session.return_value = sample_workflow_state
        mock_workflow_store.save_state.return_value = sample_workflow_state

        result = await sync_job_to_state(
            sample_partial_job, mock_workflow_store, session_id="sess_test123"
        )

        assert result.success is True
        assert result.synced is True

        # Verify state transitions to DISCOVERY_PLANNING even with gaps
        saved_state = mock_workflow_store.save_state.call_args[0][0]
        assert saved_state.phase == Phase.DISCOVERY_PLANNING
        assert saved_state.checkpoint == "itinerary_approval"

    @pytest.mark.asyncio
    async def test_successful_sync_failed_job(
        self, sample_workflow_state: WorkflowState, sample_failed_job: DiscoveryJob, mock_workflow_store: AsyncMock
    ):
        """Test successful sync of a failed job."""
        mock_workflow_store.get_by_session.return_value = sample_workflow_state
        mock_workflow_store.save_state.return_value = sample_workflow_state

        result = await sync_job_to_state(
            sample_failed_job, mock_workflow_store, session_id="sess_test123"
        )

        assert result.success is True
        assert result.synced is True

        # Verify state transitions to FAILED phase
        saved_state = mock_workflow_store.save_state.call_args[0][0]
        assert saved_state.phase == Phase.FAILED
        assert saved_state.checkpoint is None
        assert saved_state.current_step == "failed"

    @pytest.mark.asyncio
    async def test_guard1_workflow_not_found(
        self, sample_completed_job: DiscoveryJob, mock_workflow_store: AsyncMock
    ):
        """Test Guard 1: Workflow state not found."""
        mock_workflow_store.get_by_session.return_value = None

        result = await sync_job_to_state(
            sample_completed_job, mock_workflow_store, session_id="sess_test123"
        )

        assert result.success is False
        assert result.synced is False
        assert "not found" in result.reason
        mock_workflow_store.save_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_guard2_version_mismatch(
        self, sample_workflow_state: WorkflowState, sample_completed_job: DiscoveryJob, mock_workflow_store: AsyncMock
    ):
        """Test Guard 2: Workflow version mismatch."""
        # Simulate workflow was reset via start_new
        sample_workflow_state.workflow_version = 2
        mock_workflow_store.get_by_session.return_value = sample_workflow_state

        result = await sync_job_to_state(
            sample_completed_job, mock_workflow_store, session_id="sess_test123"
        )

        assert result.success is False
        assert result.synced is False
        assert "version mismatch" in result.reason.lower()
        mock_workflow_store.save_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_guard3_not_active_job(
        self, sample_workflow_state: WorkflowState, sample_completed_job: DiscoveryJob, mock_workflow_store: AsyncMock
    ):
        """Test Guard 3: Job is not the active job."""
        # Simulate a different job is active
        sample_workflow_state.current_job_id = "job_different456"
        mock_workflow_store.get_by_session.return_value = sample_workflow_state

        result = await sync_job_to_state(
            sample_completed_job, mock_workflow_store, session_id="sess_test123"
        )

        assert result.success is False
        assert result.synced is False
        assert "not the active job" in result.reason
        mock_workflow_store.save_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_guard4_wrong_phase(
        self, sample_workflow_state: WorkflowState, sample_completed_job: DiscoveryJob, mock_workflow_store: AsyncMock
    ):
        """Test Guard 4: Workflow in wrong phase."""
        # Simulate workflow moved to a different phase
        sample_workflow_state.phase = Phase.BOOKING
        mock_workflow_store.get_by_session.return_value = sample_workflow_state

        result = await sync_job_to_state(
            sample_completed_job, mock_workflow_store, session_id="sess_test123"
        )

        assert result.success is False
        assert result.synced is False
        assert "phase" in result.reason.lower()
        mock_workflow_store.save_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_idempotency_already_synced(
        self, sample_workflow_state: WorkflowState, sample_completed_job: DiscoveryJob, mock_workflow_store: AsyncMock
    ):
        """Test idempotency: Job already synced."""
        # Simulate job was already synced
        sample_workflow_state.last_synced_job_id = "job_abc123"
        mock_workflow_store.get_by_session.return_value = sample_workflow_state

        result = await sync_job_to_state(
            sample_completed_job, mock_workflow_store, session_id="sess_test123"
        )

        assert result.success is True  # Success because idempotent
        assert result.synced is False  # But no data was actually synced
        assert "idempotent" in result.reason.lower()
        assert result.state is not None
        mock_workflow_store.save_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_consultation_lookup_when_no_session_id(
        self, sample_workflow_state: WorkflowState, sample_completed_job: DiscoveryJob
    ):
        """Test fallback to consultation lookup when session_id not provided."""
        mock_store = AsyncMock()
        mock_store.get_by_consultation = AsyncMock(return_value=sample_workflow_state)
        mock_store.save_state.return_value = sample_workflow_state

        result = await sync_job_to_state(sample_completed_job, mock_store)

        assert result.success is True
        mock_store.get_by_consultation.assert_called_once_with("cons_test456")

    @pytest.mark.asyncio
    async def test_fails_without_session_id_or_consultation_lookup(
        self, sample_completed_job: DiscoveryJob
    ):
        """Test failure when no session_id and store lacks get_by_consultation."""
        mock_store = AsyncMock()
        # Remove get_by_consultation to simulate store without it
        del mock_store.get_by_consultation

        result = await sync_job_to_state(sample_completed_job, mock_store)

        assert result.success is False
        assert "no session_id provided" in result.reason


# ============================================================================
# Tests for finalize_job()
# ============================================================================


class TestFinalizeJob:
    """Tests for the finalize_job function."""

    @pytest.mark.asyncio
    async def test_finalize_completed_job(
        self, sample_workflow_state: WorkflowState, sample_completed_job: DiscoveryJob, mock_workflow_store: AsyncMock
    ):
        """Test finalize_job with completed job."""
        mock_workflow_store.get_by_session.return_value = sample_workflow_state
        mock_workflow_store.save_state.return_value = sample_workflow_state

        result = await finalize_job(
            sample_completed_job, mock_workflow_store, session_id="sess_test123"
        )

        assert result.success is True
        assert result.synced is True

    @pytest.mark.asyncio
    async def test_finalize_non_terminal_job_fails(
        self, mock_workflow_store: AsyncMock
    ):
        """Test finalize_job rejects non-terminal jobs."""
        running_job = DiscoveryJob(
            job_id="job_abc123",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.RUNNING,
        )

        result = await finalize_job(
            running_job, mock_workflow_store, session_id="sess_test123"
        )

        assert result.success is False
        assert "not in terminal state" in result.reason
        mock_workflow_store.save_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_finalize_pending_job_fails(
        self, mock_workflow_store: AsyncMock
    ):
        """Test finalize_job rejects pending jobs."""
        pending_job = DiscoveryJob(
            job_id="job_abc123",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.PENDING,
        )

        result = await finalize_job(
            pending_job, mock_workflow_store, session_id="sess_test123"
        )

        assert result.success is False
        assert "not in terminal state" in result.reason


# ============================================================================
# Tests for resume_session_with_recovery()
# ============================================================================


class TestResumeSessionWithRecovery:
    """Tests for crash recovery on session resume."""

    @pytest.mark.asyncio
    async def test_normal_resume_no_job(self, mock_workflow_store: AsyncMock):
        """Test normal resume when no job is active."""
        state = WorkflowState(
            session_id="sess_test123",
            consultation_id="cons_test456",
            workflow_version=1,
            phase=Phase.CLARIFICATION,
            current_job_id=None,
        )
        mock_workflow_store.get_by_session.return_value = state
        job_store = InMemoryDiscoveryJobStore()

        result = await resume_session_with_recovery(
            "sess_test123", mock_workflow_store, job_store
        )

        assert result is not None
        assert result.session_id == "sess_test123"
        mock_workflow_store.save_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_with_job_still_running(self, mock_workflow_store: AsyncMock):
        """Test resume when job is still running (no recovery needed)."""
        state = WorkflowState(
            session_id="sess_test123",
            consultation_id="cons_test456",
            workflow_version=1,
            phase=Phase.DISCOVERY_IN_PROGRESS,
            current_job_id="job_abc123",
            discovery_results=None,
        )
        mock_workflow_store.get_by_session.return_value = state

        job_store = InMemoryDiscoveryJobStore()
        running_job = DiscoveryJob(
            job_id="job_abc123",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.RUNNING,
        )
        await job_store.save_job(running_job)

        result = await resume_session_with_recovery(
            "sess_test123", mock_workflow_store, job_store
        )

        assert result is not None
        # No save should happen - job is still running
        mock_workflow_store.save_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_crash_recovery_completed_job(self, mock_workflow_store: AsyncMock):
        """Test crash recovery when job completed but sync failed."""
        state = WorkflowState(
            session_id="sess_test123",
            consultation_id="cons_test456",
            workflow_version=1,
            phase=Phase.DISCOVERY_IN_PROGRESS,
            current_job_id="job_abc123",
            discovery_results=None,  # Results not synced
        )
        mock_workflow_store.get_by_session.return_value = state
        mock_workflow_store.save_state.return_value = state

        job_store = InMemoryDiscoveryJobStore()
        completed_job = DiscoveryJob(
            job_id="job_abc123",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.COMPLETED,
            discovery_results={"transport": {"flights": []}},
            itinerary_draft={"days": []},
        )
        await job_store.save_job(completed_job)

        result = await resume_session_with_recovery(
            "sess_test123", mock_workflow_store, job_store
        )

        assert result is not None
        # Verify lazy sync was triggered
        mock_workflow_store.save_state.assert_called()

    @pytest.mark.asyncio
    async def test_crash_recovery_partial_job(self, mock_workflow_store: AsyncMock):
        """Test crash recovery with partial job."""
        state = WorkflowState(
            session_id="sess_test123",
            consultation_id="cons_test456",
            workflow_version=1,
            phase=Phase.DISCOVERY_IN_PROGRESS,
            current_job_id="job_abc123",
            discovery_results=None,
        )
        mock_workflow_store.get_by_session.return_value = state
        mock_workflow_store.save_state.return_value = state

        job_store = InMemoryDiscoveryJobStore()
        partial_job = DiscoveryJob(
            job_id="job_abc123",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.PARTIAL,
            discovery_results={"transport": {"flights": []}},
        )
        await job_store.save_job(partial_job)

        result = await resume_session_with_recovery(
            "sess_test123", mock_workflow_store, job_store
        )

        assert result is not None
        mock_workflow_store.save_state.assert_called()

    @pytest.mark.asyncio
    async def test_cancelled_job_clears_reference(self, mock_workflow_store: AsyncMock):
        """Test that cancelled jobs just clear the job reference."""
        state = WorkflowState(
            session_id="sess_test123",
            consultation_id="cons_test456",
            workflow_version=1,
            phase=Phase.DISCOVERY_IN_PROGRESS,
            current_job_id="job_abc123",
            discovery_results=None,
        )
        mock_workflow_store.get_by_session.return_value = state
        mock_workflow_store.save_state.return_value = state

        job_store = InMemoryDiscoveryJobStore()
        cancelled_job = DiscoveryJob(
            job_id="job_abc123",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.CANCELLED,
        )
        await job_store.save_job(cancelled_job)

        result = await resume_session_with_recovery(
            "sess_test123", mock_workflow_store, job_store
        )

        assert result is not None
        # Verify job reference was cleared
        saved_state = mock_workflow_store.save_state.call_args[0][0]
        assert saved_state.current_job_id is None

    @pytest.mark.asyncio
    async def test_stale_job_reference_cleared(self, mock_workflow_store: AsyncMock):
        """Test that stale job references (job not found) are cleared."""
        state = WorkflowState(
            session_id="sess_test123",
            consultation_id="cons_test456",
            workflow_version=1,
            phase=Phase.DISCOVERY_IN_PROGRESS,
            current_job_id="job_abc123",
            discovery_results=None,
        )
        mock_workflow_store.get_by_session.return_value = state
        mock_workflow_store.save_state.return_value = state

        # Empty job store - job was deleted/expired
        job_store = InMemoryDiscoveryJobStore()

        result = await resume_session_with_recovery(
            "sess_test123", mock_workflow_store, job_store
        )

        assert result is not None
        # Verify stale reference was cleared
        saved_state = mock_workflow_store.save_state.call_args[0][0]
        assert saved_state.current_job_id is None

    @pytest.mark.asyncio
    async def test_session_not_found(self, mock_workflow_store: AsyncMock):
        """Test resume when session doesn't exist."""
        mock_workflow_store.get_by_session.return_value = None
        job_store = InMemoryDiscoveryJobStore()

        result = await resume_session_with_recovery(
            "sess_nonexistent", mock_workflow_store, job_store
        )

        assert result is None


# ============================================================================
# Tests for check_sync_needed()
# ============================================================================


class TestCheckSyncNeeded:
    """Tests for the lightweight sync check function."""

    def test_sync_needed_all_conditions_met(
        self, sample_workflow_state: WorkflowState, sample_completed_job: DiscoveryJob
    ):
        """Test sync needed when all conditions are met."""
        needs_sync, reason = check_sync_needed(sample_workflow_state, sample_completed_job)
        assert needs_sync is True
        assert "Sync needed" in reason

    def test_version_mismatch(
        self, sample_workflow_state: WorkflowState, sample_completed_job: DiscoveryJob
    ):
        """Test version mismatch detection."""
        sample_workflow_state.workflow_version = 2
        needs_sync, reason = check_sync_needed(sample_workflow_state, sample_completed_job)
        assert needs_sync is False
        assert "Version mismatch" in reason

    def test_not_active_job(
        self, sample_workflow_state: WorkflowState, sample_completed_job: DiscoveryJob
    ):
        """Test not active job detection."""
        sample_workflow_state.current_job_id = "job_different"
        needs_sync, reason = check_sync_needed(sample_workflow_state, sample_completed_job)
        assert needs_sync is False
        assert "Not the active job" in reason

    def test_wrong_phase(
        self, sample_workflow_state: WorkflowState, sample_completed_job: DiscoveryJob
    ):
        """Test wrong phase detection."""
        sample_workflow_state.phase = Phase.CLARIFICATION
        needs_sync, reason = check_sync_needed(sample_workflow_state, sample_completed_job)
        assert needs_sync is False
        assert "Wrong phase" in reason

    def test_already_synced(
        self, sample_workflow_state: WorkflowState, sample_completed_job: DiscoveryJob
    ):
        """Test idempotency detection."""
        sample_workflow_state.last_synced_job_id = "job_abc123"
        needs_sync, reason = check_sync_needed(sample_workflow_state, sample_completed_job)
        assert needs_sync is False
        assert "Already synced" in reason

    def test_job_not_terminal(self, sample_workflow_state: WorkflowState):
        """Test non-terminal job detection."""
        running_job = DiscoveryJob(
            job_id="job_abc123",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.RUNNING,
        )
        needs_sync, reason = check_sync_needed(sample_workflow_state, running_job)
        assert needs_sync is False
        assert "not terminal" in reason


# ============================================================================
# Integration-style tests
# ============================================================================


class TestStateSyncIntegration:
    """Integration tests for state sync scenarios."""

    @pytest.mark.asyncio
    async def test_full_sync_flow(self, mock_workflow_store: AsyncMock):
        """Test complete sync flow from job completion to state update."""
        # Setup initial state
        state = WorkflowState(
            session_id="sess_test123",
            consultation_id="cons_test456",
            workflow_version=1,
            phase=Phase.DISCOVERY_IN_PROGRESS,
            current_job_id="job_abc123",
        )
        mock_workflow_store.get_by_session.return_value = state
        mock_workflow_store.save_state.side_effect = lambda s: s

        # Create completed job
        job = DiscoveryJob(
            job_id="job_abc123",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.COMPLETED,
            discovery_results={
                "transport": {"flights": [{"id": "fl1"}]},
                "stay": {"hotels": [{"id": "h1"}]},
            },
            itinerary_draft={
                "days": [{"date": "2026-03-10"}],
            },
        )

        # Execute sync
        result = await finalize_job(job, mock_workflow_store, session_id="sess_test123")

        # Verify result
        assert result.success is True
        assert result.synced is True
        assert result.state is not None
        assert result.state.phase == Phase.DISCOVERY_PLANNING
        assert result.state.checkpoint == "itinerary_approval"
        assert result.state.discovery_results is not None
        assert result.state.itinerary_draft is not None
        assert result.state.last_synced_job_id == "job_abc123"
        assert result.state.current_job_id is None

    @pytest.mark.asyncio
    async def test_idempotent_retry(self, mock_workflow_store: AsyncMock):
        """Test that retrying sync is idempotent."""
        # Setup state that has been synced but still references the job
        # This simulates a race condition where sync happens twice
        state = WorkflowState(
            session_id="sess_test123",
            consultation_id="cons_test456",
            workflow_version=1,
            phase=Phase.DISCOVERY_IN_PROGRESS,  # Still in progress phase
            checkpoint=None,
            current_job_id="job_abc123",  # Job still referenced
            last_synced_job_id="job_abc123",  # But already synced
            discovery_results={"old": "data"},
        )
        mock_workflow_store.get_by_session.return_value = state

        # Try to sync same job again
        job = DiscoveryJob(
            job_id="job_abc123",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.COMPLETED,
            discovery_results={"new": "data"},  # Different data
        )

        result = await finalize_job(job, mock_workflow_store, session_id="sess_test123")

        # Should succeed but not actually sync (idempotent)
        assert result.success is True
        assert result.synced is False
        # State should not be modified
        mock_workflow_store.save_state.assert_not_called()
