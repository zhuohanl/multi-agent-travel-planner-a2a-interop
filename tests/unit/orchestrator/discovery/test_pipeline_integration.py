"""
Unit tests for discovery → planning pipeline integration.

Per ORCH-088, tests cover:
- finalize_job_runs_planning_pipeline: Planning pipeline execution after discovery
- finalize_job_sets_itinerary_draft: ItineraryDraft storage on job and state
- finalize_job_sets_checkpoint: Phase/checkpoint transition
- discovery_handler_returns_itinerary_when_ready: Itinerary preview response
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from src.orchestrator.discovery.state_sync import (
    SyncResult,
    finalize_job_with_planning,
    run_planning_after_discovery,
)
from src.orchestrator.handlers.discovery import DiscoveryHandler, DiscoveryResults
from src.orchestrator.models.workflow_state import Phase, WorkflowState
from src.orchestrator.storage import WorkflowStateData
from src.orchestrator.storage.discovery_jobs import (
    AgentProgress,
    DiscoveryJob,
    InMemoryDiscoveryJobStore,
    JobStatus,
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
        trip_spec={
            "destination": "Tokyo",
            "start_date": "2026-03-10",
            "end_date": "2026-03-15",
            "num_travelers": 2,
            "budget": "$5000",
        },
    )


@pytest.fixture
def sample_planning_state() -> WorkflowState:
    """Create a sample workflow state in DISCOVERY_PLANNING phase with itinerary draft."""
    return WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_test456",
        workflow_version=1,
        phase=Phase.DISCOVERY_PLANNING,
        checkpoint="itinerary_approval",
        current_step="approval",
        current_job_id=None,
        last_synced_job_id="job_abc123",
        trip_spec={
            "destination": "Tokyo",
            "start_date": "2026-03-10",
            "end_date": "2026-03-15",
        },
        discovery_results={
            "transport": {"status": "success", "data": {"flights": [{"id": "fl1"}]}},
            "stay": {"status": "success", "data": {"hotels": [{"id": "h1"}]}},
            "poi": {"status": "success", "data": {"pois": [{"id": "p1"}]}},
            "events": {"status": "success", "data": {"events": []}},
            "dining": {"status": "success", "data": {"restaurants": []}},
        },
        itinerary_draft={
            "destination": "Tokyo",
            "start_date": "2026-03-10",
            "end_date": "2026-03-15",
            "days": [
                {"day_number": 1, "date": "2026-03-10", "title": "Day 1 in Tokyo"},
                {"day_number": 2, "date": "2026-03-11", "title": "Day 2 in Tokyo"},
            ],
            "total_estimated_cost": 3500,
            "currency": "USD",
        },
    )


@pytest.fixture
def sample_completed_job() -> DiscoveryJob:
    """Create a sample completed discovery job with results."""
    return DiscoveryJob(
        job_id="job_abc123",
        consultation_id="cons_test456",
        workflow_version=1,
        status=JobStatus.COMPLETED,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        agent_progress={
            "transport": AgentProgress(agent="transport", status="completed"),
            "stay": AgentProgress(agent="stay", status="completed"),
            "poi": AgentProgress(agent="poi", status="completed"),
            "events": AgentProgress(agent="events", status="completed"),
            "dining": AgentProgress(agent="dining", status="completed"),
        },
        pipeline_stage="discovery",
        discovery_results={
            "transport": {"status": "success", "data": {"flights": [{"id": "fl1", "price": 500}]}},
            "stay": {"status": "success", "data": {"hotels": [{"id": "h1", "price": 200}]}},
            "poi": {"status": "success", "data": {"pois": [{"id": "p1"}]}},
            "events": {"status": "success", "data": {"events": []}},
            "dining": {"status": "success", "data": {"restaurants": []}},
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
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        agent_progress={
            "transport": AgentProgress(agent="transport", status="timeout"),
            "stay": AgentProgress(agent="stay", status="completed"),
            "poi": AgentProgress(agent="poi", status="completed"),
            "events": AgentProgress(agent="events", status="failed"),
            "dining": AgentProgress(agent="dining", status="completed"),
        },
        pipeline_stage="discovery",
        discovery_results={
            "transport": {"status": "timeout", "message": "Timeout after 30s"},
            "stay": {"status": "success", "data": {"hotels": [{"id": "h1"}]}},
            "poi": {"status": "success", "data": {"pois": []}},
            "events": {"status": "error", "message": "Service unavailable"},
            "dining": {"status": "success", "data": {"restaurants": []}},
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
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        error="All agents failed",
    )


@pytest.fixture
def mock_workflow_store() -> AsyncMock:
    """Create a mock workflow store."""
    store = AsyncMock()
    return store


@pytest.fixture
def mock_job_store() -> InMemoryDiscoveryJobStore:
    """Create an in-memory job store."""
    return InMemoryDiscoveryJobStore()


@pytest.fixture
def mock_planning_result() -> dict[str, Any]:
    """Create a mock planning result."""
    return {
        "success": True,
        "itinerary": {
            "destination": "Tokyo",
            "start_date": "2026-03-10",
            "end_date": "2026-03-15",
            "days": [
                {"day_number": 1, "date": "2026-03-10", "title": "Day 1 in Tokyo", "activities": []},
                {"day_number": 2, "date": "2026-03-11", "title": "Day 2 in Tokyo", "activities": []},
                {"day_number": 3, "date": "2026-03-12", "title": "Day 3 in Tokyo", "activities": []},
            ],
            "total_estimated_cost": 3500,
            "currency": "USD",
        },
        "validation": {
            "status": "valid",
            "errors": [],
            "warnings": [],
            "gaps": [],
        },
        "gaps": [],
    }


# ============================================================================
# Tests for run_planning_after_discovery()
# ============================================================================


class TestRunPlanningAfterDiscovery:
    """Tests for the run_planning_after_discovery function."""

    @pytest.mark.asyncio
    async def test_runs_planning_pipeline(
        self, sample_completed_job: DiscoveryJob
    ):
        """Test that planning pipeline is invoked with discovery results."""
        trip_spec = {
            "destination": "Tokyo",
            "start_date": "2026-03-10",
            "end_date": "2026-03-15",
        }

        # Run planning (stub mode - no A2A client)
        result = await run_planning_after_discovery(
            job=sample_completed_job,
            trip_spec=trip_spec,
        )

        # Verify result structure
        assert hasattr(result, "success")
        assert hasattr(result, "itinerary")

    @pytest.mark.asyncio
    async def test_converts_discovery_results(
        self, sample_completed_job: DiscoveryJob
    ):
        """Test that discovery results dict is converted to DiscoveryResults."""
        trip_spec = {"destination": "Tokyo"}

        with patch(
            "src.orchestrator.planning.pipeline.run_planning_pipeline"
        ) as mock_pipeline:
            mock_pipeline.return_value = MagicMock(
                success=True,
                itinerary={"days": []},
            )

            await run_planning_after_discovery(
                job=sample_completed_job,
                trip_spec=trip_spec,
            )

            # Verify pipeline was called with DiscoveryResults object
            mock_pipeline.assert_called_once()
            call_args = mock_pipeline.call_args
            discovery_results = call_args.kwargs.get("discovery_results")
            assert discovery_results is not None
            assert isinstance(discovery_results, DiscoveryResults)


# ============================================================================
# Tests for finalize_job_with_planning()
# ============================================================================


class TestFinalizeJobWithPlanning:
    """Tests for the finalize_job_with_planning function."""

    @pytest.mark.asyncio
    async def test_finalize_job_runs_planning_pipeline(
        self,
        sample_workflow_state: WorkflowState,
        sample_completed_job: DiscoveryJob,
        mock_workflow_store: AsyncMock,
        mock_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that finalize_job runs the planning pipeline."""
        mock_workflow_store.get_by_session.return_value = sample_workflow_state
        mock_workflow_store.save_state.return_value = sample_workflow_state

        await mock_job_store.save_job(sample_completed_job)

        with patch(
            "src.orchestrator.discovery.state_sync.run_planning_after_discovery"
        ) as mock_planning:
            mock_planning.return_value = MagicMock(
                success=True,
                itinerary={"destination": "Tokyo", "days": []},
            )

            result = await finalize_job_with_planning(
                job=sample_completed_job,
                workflow_store=mock_workflow_store,
                job_store=mock_job_store,
                session_id="sess_test123",
            )

            # Verify planning was called
            mock_planning.assert_called_once()
            assert result.success is True

    @pytest.mark.asyncio
    async def test_finalize_job_sets_itinerary_draft(
        self,
        sample_workflow_state: WorkflowState,
        sample_completed_job: DiscoveryJob,
        mock_workflow_store: AsyncMock,
        mock_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that finalize_job stores itinerary draft on job and state."""
        mock_workflow_store.get_by_session.return_value = sample_workflow_state
        mock_workflow_store.save_state.return_value = sample_workflow_state

        await mock_job_store.save_job(sample_completed_job)

        mock_itinerary = {
            "destination": "Tokyo",
            "days": [{"day_number": 1}],
            "total_estimated_cost": 3000,
        }

        with patch(
            "src.orchestrator.discovery.state_sync.run_planning_after_discovery"
        ) as mock_planning:
            mock_planning.return_value = MagicMock(
                success=True,
                itinerary=mock_itinerary,
            )

            await finalize_job_with_planning(
                job=sample_completed_job,
                workflow_store=mock_workflow_store,
                job_store=mock_job_store,
                session_id="sess_test123",
            )

            # Verify job was updated with itinerary draft
            updated_job = await mock_job_store.get_job(
                sample_completed_job.job_id,
                sample_completed_job.consultation_id,
            )
            assert updated_job is not None
            assert updated_job.itinerary_draft == mock_itinerary
            assert updated_job.pipeline_stage == "validator"

    @pytest.mark.asyncio
    async def test_finalize_job_sets_checkpoint(
        self,
        sample_workflow_state: WorkflowState,
        sample_completed_job: DiscoveryJob,
        mock_workflow_store: AsyncMock,
        mock_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that finalize_job sets checkpoint to itinerary_approval."""
        mock_workflow_store.get_by_session.return_value = sample_workflow_state
        mock_workflow_store.save_state.return_value = sample_workflow_state

        await mock_job_store.save_job(sample_completed_job)

        with patch(
            "src.orchestrator.discovery.state_sync.run_planning_after_discovery"
        ) as mock_planning:
            mock_planning.return_value = MagicMock(
                success=True,
                itinerary={"days": []},
            )

            await finalize_job_with_planning(
                job=sample_completed_job,
                workflow_store=mock_workflow_store,
                job_store=mock_job_store,
                session_id="sess_test123",
            )

            # Verify state was saved with correct phase/checkpoint
            mock_workflow_store.save_state.assert_called()
            saved_state = mock_workflow_store.save_state.call_args[0][0]
            assert saved_state.phase == Phase.DISCOVERY_PLANNING
            assert saved_state.checkpoint == "itinerary_approval"

    @pytest.mark.asyncio
    async def test_finalize_job_skips_planning_for_failed_job(
        self,
        sample_workflow_state: WorkflowState,
        sample_failed_job: DiscoveryJob,
        mock_workflow_store: AsyncMock,
        mock_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that finalize_job skips planning for FAILED jobs."""
        sample_workflow_state.current_job_id = sample_failed_job.job_id
        mock_workflow_store.get_by_session.return_value = sample_workflow_state
        mock_workflow_store.save_state.return_value = sample_workflow_state

        await mock_job_store.save_job(sample_failed_job)

        with patch(
            "src.orchestrator.discovery.state_sync.run_planning_after_discovery"
        ) as mock_planning:
            await finalize_job_with_planning(
                job=sample_failed_job,
                workflow_store=mock_workflow_store,
                job_store=mock_job_store,
                session_id="sess_test123",
            )

            # Planning should not be called for failed jobs
            mock_planning.assert_not_called()

    @pytest.mark.asyncio
    async def test_finalize_job_handles_planning_failure(
        self,
        sample_workflow_state: WorkflowState,
        sample_completed_job: DiscoveryJob,
        mock_workflow_store: AsyncMock,
        mock_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that finalize_job handles planning pipeline failures gracefully."""
        mock_workflow_store.get_by_session.return_value = sample_workflow_state
        mock_workflow_store.save_state.return_value = sample_workflow_state

        await mock_job_store.save_job(sample_completed_job)

        with patch(
            "src.orchestrator.discovery.state_sync.run_planning_after_discovery"
        ) as mock_planning:
            mock_planning.side_effect = Exception("Planning pipeline error")

            result = await finalize_job_with_planning(
                job=sample_completed_job,
                workflow_store=mock_workflow_store,
                job_store=mock_job_store,
                session_id="sess_test123",
            )

            # Should still sync the job (with planning_failed stage)
            assert result.success is True or result.synced is True or "synced" in result.reason.lower()

            # Verify job was updated with error
            updated_job = await mock_job_store.get_job(
                sample_completed_job.job_id,
                sample_completed_job.consultation_id,
            )
            assert updated_job is not None
            assert updated_job.pipeline_stage == "planning_failed"
            assert updated_job.error is not None


# ============================================================================
# Tests for DiscoveryHandler itinerary preview
# ============================================================================


class TestDiscoveryHandlerItineraryPreview:
    """Tests for DiscoveryHandler returning itinerary when ready."""

    @pytest.fixture
    def sample_state_data(self) -> WorkflowStateData:
        """Create sample state data."""
        return WorkflowStateData(
            session_id="sess_test123",
            consultation_id="cons_test456",
            phase="discovery_planning",
            checkpoint="itinerary_approval",
            current_step="approval",
        )

    @pytest.mark.asyncio
    async def test_discovery_handler_returns_itinerary_when_ready(
        self,
        sample_planning_state: WorkflowState,
        sample_state_data: WorkflowStateData,
    ):
        """Test that DiscoveryHandler returns itinerary preview when results are ready."""
        handler = DiscoveryHandler(
            state=sample_planning_state,
            state_data=sample_state_data,
        )

        # Get status should return itinerary preview
        result = await handler._get_discovery_status()

        assert result.response.success is True
        assert "itinerary" in result.response.message.lower() or "day" in result.response.message.lower()
        assert result.response.data is not None
        assert "itinerary_draft" in result.response.data

        # Verify UI actions include approve and modify
        assert result.response.ui is not None
        action_labels = [a.label for a in result.response.ui.actions]
        assert any("approve" in label.lower() for label in action_labels)
        assert any("change" in label.lower() for label in action_labels)

    @pytest.mark.asyncio
    async def test_discovery_handler_includes_checkpoint_in_response(
        self,
        sample_planning_state: WorkflowState,
        sample_state_data: WorkflowStateData,
    ):
        """Test that response includes checkpoint information."""
        handler = DiscoveryHandler(
            state=sample_planning_state,
            state_data=sample_state_data,
        )

        result = await handler._get_discovery_status()

        assert result.response.data["checkpoint"] == "itinerary_approval"
        assert result.response.data["phase"] == "discovery_planning"

    @pytest.mark.asyncio
    async def test_return_itinerary_preview_formats_message(
        self,
        sample_planning_state: WorkflowState,
        sample_state_data: WorkflowStateData,
    ):
        """Test that itinerary preview message includes key details."""
        handler = DiscoveryHandler(
            state=sample_planning_state,
            state_data=sample_state_data,
        )

        result = await handler._return_itinerary_preview()

        # Message should include destination, days, and cost
        message = result.response.message.lower()
        assert "tokyo" in message or "destination" in message
        assert "day" in message
        assert "cost" in message or "usd" in message or "3,500" in message or "3500" in message

    @pytest.mark.asyncio
    async def test_return_itinerary_preview_with_job(
        self,
        sample_planning_state: WorkflowState,
        sample_state_data: WorkflowStateData,
        sample_completed_job: DiscoveryJob,
    ):
        """Test that itinerary preview can use job's itinerary draft."""
        sample_completed_job.itinerary_draft = {
            "destination": "Kyoto",
            "days": [{"day_number": 1}],
            "total_estimated_cost": 2000,
            "currency": "JPY",
        }

        handler = DiscoveryHandler(
            state=sample_planning_state,
            state_data=sample_state_data,
        )

        result = await handler._return_itinerary_preview(job=sample_completed_job)

        # Should use job's itinerary draft
        assert result.response.data["itinerary_draft"]["destination"] == "Kyoto"
        assert "kyoto" in result.response.message.lower()

    @pytest.mark.asyncio
    async def test_discovery_status_returns_progress_when_job_running(
        self,
        sample_workflow_state: WorkflowState,
        sample_state_data: WorkflowStateData,
    ):
        """Test that status returns progress when job is still running."""
        sample_state_data.phase = "discovery_in_progress"
        sample_workflow_state.phase = Phase.DISCOVERY_IN_PROGRESS

        job_store = InMemoryDiscoveryJobStore()
        running_job = DiscoveryJob(
            job_id="job_abc123",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.RUNNING,
            agent_progress={
                "transport": AgentProgress(agent="transport", status="running"),
                "stay": AgentProgress(agent="stay", status="pending"),
                "poi": AgentProgress(agent="poi", status="pending"),
                "events": AgentProgress(agent="events", status="pending"),
                "dining": AgentProgress(agent="dining", status="pending"),
            },
        )
        await job_store.save_job(running_job)

        handler = DiscoveryHandler(
            state=sample_workflow_state,
            state_data=sample_state_data,
            discovery_job_store=job_store,
        )

        result = await handler._get_discovery_status()

        # Should return job status, not itinerary preview
        assert result.response.data["status"] == "running"
        assert "agent_progress" in result.response.data


# ============================================================================
# Tests for finalize_discovery_with_planning()
# ============================================================================


class TestFinalizeDiscoveryWithPlanning:
    """Tests for DiscoveryHandler.finalize_discovery_with_planning method."""

    @pytest.fixture
    def sample_state_data(self) -> WorkflowStateData:
        """Create sample state data."""
        return WorkflowStateData(
            session_id="sess_test123",
            consultation_id="cons_test456",
            phase="discovery_in_progress",
            checkpoint=None,
            current_step="discovering",
        )

    @pytest.mark.asyncio
    async def test_finalize_updates_handler_state(
        self,
        sample_workflow_state: WorkflowState,
        sample_state_data: WorkflowStateData,
        sample_completed_job: DiscoveryJob,
        mock_workflow_store: AsyncMock,
    ):
        """Test that finalize_discovery_with_planning updates handler state."""
        # Create updated state that would be returned after sync
        updated_state = WorkflowState(
            session_id="sess_test123",
            consultation_id="cons_test456",
            workflow_version=1,
            phase=Phase.DISCOVERY_PLANNING,
            checkpoint="itinerary_approval",
            current_step="approval",
            discovery_results=sample_completed_job.discovery_results,
            itinerary_draft={"days": [], "destination": "Tokyo"},
            current_job_id=None,
            last_synced_job_id=sample_completed_job.job_id,
        )

        mock_workflow_store.get_by_session.return_value = sample_workflow_state
        mock_workflow_store.save_state.return_value = updated_state

        job_store = InMemoryDiscoveryJobStore()
        await job_store.save_job(sample_completed_job)

        handler = DiscoveryHandler(
            state=sample_workflow_state,
            state_data=sample_state_data,
            discovery_job_store=job_store,
        )

        with patch(
            "src.orchestrator.discovery.state_sync.run_planning_after_discovery"
        ) as mock_planning:
            mock_planning.return_value = MagicMock(
                success=True,
                itinerary={"days": [], "destination": "Tokyo"},
            )

            result = await handler.finalize_discovery_with_planning(
                job=sample_completed_job,
                workflow_store=mock_workflow_store,
            )

            # Handler's state should be updated
            assert handler.state.phase == Phase.DISCOVERY_PLANNING
            assert handler.state.checkpoint == "itinerary_approval"

    @pytest.mark.asyncio
    async def test_finalize_returns_itinerary_preview(
        self,
        sample_workflow_state: WorkflowState,
        sample_state_data: WorkflowStateData,
        sample_completed_job: DiscoveryJob,
        mock_workflow_store: AsyncMock,
    ):
        """Test that finalize_discovery_with_planning returns itinerary preview."""
        updated_state = WorkflowState(
            session_id="sess_test123",
            consultation_id="cons_test456",
            workflow_version=1,
            phase=Phase.DISCOVERY_PLANNING,
            checkpoint="itinerary_approval",
            current_step="approval",
            itinerary_draft={"days": [{"day_number": 1}], "destination": "Tokyo", "total_estimated_cost": 3000, "currency": "USD"},
        )

        mock_workflow_store.get_by_session.return_value = sample_workflow_state
        mock_workflow_store.save_state.return_value = updated_state

        job_store = InMemoryDiscoveryJobStore()
        await job_store.save_job(sample_completed_job)

        handler = DiscoveryHandler(
            state=sample_workflow_state,
            state_data=sample_state_data,
            discovery_job_store=job_store,
        )

        with patch(
            "src.orchestrator.discovery.state_sync.run_planning_after_discovery"
        ) as mock_planning:
            mock_planning.return_value = MagicMock(
                success=True,
                itinerary={"days": [{"day_number": 1}], "destination": "Tokyo", "total_estimated_cost": 3000, "currency": "USD"},
            )

            result = await handler.finalize_discovery_with_planning(
                job=sample_completed_job,
                workflow_store=mock_workflow_store,
            )

            # Should return success with itinerary preview
            assert result.response.success is True
            assert result.response.ui is not None
