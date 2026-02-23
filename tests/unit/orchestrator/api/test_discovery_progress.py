"""Unit tests for the discovery progress API endpoints.

Tests cover:
- GET /sessions/{session_id}/discovery/stream - SSE streaming
- GET /sessions/{session_id}/discovery/status - Polling endpoint
- GET /sessions/{session_id}/discovery/reconnect - Reconnection handling

Per ORCH-101 acceptance criteria:
- Discovery start returns stream_url and job_id and persists current_job_id
- GET stream returns 404 when no active job
- GET status returns coarse status while running and detailed results after completion
- Reconnection returns stream_url for RUNNING jobs and itinerary/gaps for COMPLETED/PARTIAL jobs
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from src.orchestrator.api.discovery import (
    JobStatusResponse,
    ReconnectionResponse,
    _build_state_event,
    _build_result_event,
    _build_status_message,
    create_discovery_router,
)
from src.orchestrator.storage.discovery_jobs import (
    AgentProgress,
    DiscoveryJob,
    InMemoryDiscoveryJobStore,
    JobStatus,
)
from src.orchestrator.storage.session_state import (
    InMemoryWorkflowStateStore,
    WorkflowStateData,
)
from src.orchestrator.streaming.progress import ProgressEventType


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def workflow_store():
    """Create an in-memory workflow state store."""
    return InMemoryWorkflowStateStore()


@pytest.fixture
def job_store():
    """Create an in-memory discovery job store."""
    return InMemoryDiscoveryJobStore()


@pytest.fixture
def test_app(workflow_store, job_store):
    """Create a test FastAPI app with discovery router."""
    app = FastAPI()
    router = create_discovery_router(
        workflow_state_store=workflow_store,
        discovery_job_store=job_store,
    )
    app.include_router(router)
    return app


@pytest.fixture
def client(test_app):
    """Create a test client."""
    return TestClient(test_app)


@pytest.fixture
def sample_state():
    """Create a sample workflow state with an active job."""
    return WorkflowStateData(
        session_id="test-session-123",
        consultation_id="test-consultation-456",
        phase="DISCOVERY_IN_PROGRESS",
        current_job_id="job-789",
    )


@pytest.fixture
def sample_running_job():
    """Create a sample running discovery job."""
    return DiscoveryJob(
        job_id="job-789",
        consultation_id="test-consultation-456",
        workflow_version=1,
        status=JobStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
        agent_progress={
            "transport": AgentProgress(agent="transport", status="completed"),
            "stay": AgentProgress(agent="stay", status="running"),
            "poi": AgentProgress(agent="poi", status="pending"),
            "events": AgentProgress(agent="events", status="pending"),
            "dining": AgentProgress(agent="dining", status="pending"),
        },
        pipeline_stage="discovery",
    )


@pytest.fixture
def sample_completed_job():
    """Create a sample completed discovery job."""
    return DiscoveryJob(
        job_id="job-789",
        consultation_id="test-consultation-456",
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
        pipeline_stage="validator",
        itinerary_draft={
            "destination": "Tokyo",
            "days": [{"day": 1, "activities": []}],
            "total_estimated_cost": 2500,
        },
    )


@pytest.fixture
def sample_partial_job():
    """Create a sample partial discovery job (some agents failed)."""
    return DiscoveryJob(
        job_id="job-789",
        consultation_id="test-consultation-456",
        workflow_version=1,
        status=JobStatus.PARTIAL,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        agent_progress={
            "transport": AgentProgress(agent="transport", status="completed"),
            "stay": AgentProgress(agent="stay", status="timeout"),
            "poi": AgentProgress(agent="poi", status="completed"),
            "events": AgentProgress(agent="events", status="failed"),
            "dining": AgentProgress(agent="dining", status="completed"),
        },
        pipeline_stage="validator",
        itinerary_draft={
            "destination": "Tokyo",
            "days": [{"day": 1, "activities": []}],
        },
        discovery_results={
            "gaps": [
                {"agent": "stay", "reason": "timeout"},
                {"agent": "events", "reason": "failed"},
            ]
        },
    )


# =============================================================================
# Response Model Tests
# =============================================================================


class TestJobStatusResponse:
    """Tests for JobStatusResponse model validation."""

    def test_valid_response_running(self):
        """Test valid response for running job."""
        response = JobStatusResponse(
            status="running",
            job_id="job-123",
            pipeline_stage="discovery",
            message="Job in progress...",
        )
        assert response.status == "running"
        assert response.job_id == "job-123"
        assert response.agent_progress is None  # Not available while running

    def test_valid_response_completed(self):
        """Test valid response for completed job."""
        response = JobStatusResponse(
            status="completed",
            job_id="job-123",
            pipeline_stage="validator",
            agent_progress={
                "transport": {"status": "completed"},
                "stay": {"status": "completed"},
            },
            message="Your itinerary is ready!",
            itinerary_draft={"destination": "Tokyo"},
        )
        assert response.status == "completed"
        assert response.itinerary_draft is not None

    def test_response_serialization(self):
        """Test that response serializes correctly to JSON."""
        response = JobStatusResponse(
            status="partial",
            job_id="job-123",
            gaps=[{"agent": "stay", "reason": "timeout"}],
        )
        json_dict = response.model_dump()
        assert json_dict["status"] == "partial"
        assert len(json_dict["gaps"]) == 1


class TestReconnectionResponse:
    """Tests for ReconnectionResponse model validation."""

    def test_valid_response_running(self):
        """Test valid response for running job reconnection."""
        response = ReconnectionResponse(
            status="running",
            stream_url="/sessions/sess-123/discovery/stream",
            message="Your trip planning is in progress...",
            current_progress={"status": "running"},
        )
        assert response.status == "running"
        assert response.stream_url is not None
        assert response.itinerary_draft is None

    def test_valid_response_completed(self):
        """Test valid response for completed job reconnection."""
        response = ReconnectionResponse(
            status="completed",
            message="Your itinerary is ready!",
            itinerary_draft={"destination": "Tokyo"},
            checkpoint="itinerary_approval",
        )
        assert response.status == "completed"
        assert response.stream_url is None
        assert response.checkpoint == "itinerary_approval"


# =============================================================================
# Discovery Stream Endpoint Tests
# =============================================================================


class TestDiscoveryStreamEndpoint:
    """Tests for GET /sessions/{session_id}/discovery/stream endpoint."""

    def test_discovery_stream_404_without_session(self, client):
        """Test that stream returns 404 when session not found."""
        response = client.get("/sessions/nonexistent-session/discovery/stream")
        assert response.status_code == 404
        assert "Session not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_discovery_stream_404_without_job(
        self, test_app, workflow_store
    ):
        """Test that stream returns 404 when no active discovery job."""
        # Create state without job
        state = WorkflowStateData(
            session_id="test-session",
            consultation_id="test-consultation",
            phase="CLARIFICATION",
            current_job_id=None,  # No active job
        )
        await workflow_store.save_state(state)

        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test"
        ) as ac:
            response = await ac.get("/sessions/test-session/discovery/stream")

        assert response.status_code == 404
        assert "No active discovery job" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_discovery_stream_404_job_not_found(
        self, test_app, workflow_store
    ):
        """Test that stream returns 404 when job doesn't exist in store."""
        # Create state with job_id but don't add job to store
        state = WorkflowStateData(
            session_id="test-session",
            consultation_id="test-consultation",
            phase="DISCOVERY_IN_PROGRESS",
            current_job_id="nonexistent-job",
        )
        await workflow_store.save_state(state)

        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test"
        ) as ac:
            response = await ac.get("/sessions/test-session/discovery/stream")

        assert response.status_code == 404
        assert "Discovery job not found" in response.json()["detail"]


# =============================================================================
# Discovery Status Endpoint Tests
# =============================================================================


class TestDiscoveryStatusEndpoint:
    """Tests for GET /sessions/{session_id}/discovery/status endpoint."""

    @pytest.mark.asyncio
    async def test_discovery_status_running_is_coarse(
        self, test_app, workflow_store, job_store, sample_state, sample_running_job
    ):
        """Test that status returns coarse info while job is running (no mid-job DB writes)."""
        await workflow_store.save_state(sample_state)
        await job_store.save_job(sample_running_job)

        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test"
        ) as ac:
            response = await ac.get("/sessions/test-session-123/discovery/status")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert data["job_id"] == "job-789"
        assert data["pipeline_stage"] == "discovery"
        # Per design doc: agent_progress is NOT available via polling mid-job
        assert data["agent_progress"] is None
        assert "SSE stream" in data["message"]

    @pytest.mark.asyncio
    async def test_discovery_status_completed_includes_results(
        self, test_app, workflow_store, job_store, sample_state, sample_completed_job
    ):
        """Test that status includes full details after job completion."""
        await workflow_store.save_state(sample_state)
        await job_store.save_job(sample_completed_job)

        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test"
        ) as ac:
            response = await ac.get("/sessions/test-session-123/discovery/status")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["job_id"] == "job-789"
        # Agent progress IS available after completion
        assert data["agent_progress"] is not None
        assert len(data["agent_progress"]) == 5
        # Itinerary draft available
        assert data["itinerary_draft"] is not None
        assert data["itinerary_draft"]["destination"] == "Tokyo"

    @pytest.mark.asyncio
    async def test_discovery_status_partial_includes_gaps(
        self, test_app, workflow_store, job_store, sample_state, sample_partial_job
    ):
        """Test that status includes gaps for partial completion."""
        await workflow_store.save_state(sample_state)
        await job_store.save_job(sample_partial_job)

        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test"
        ) as ac:
            response = await ac.get("/sessions/test-session-123/discovery/status")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "partial"
        assert data["gaps"] is not None
        assert len(data["gaps"]) == 2

    def test_discovery_status_404_without_session(self, client):
        """Test that status returns 404 when session not found."""
        response = client.get("/sessions/nonexistent-session/discovery/status")
        assert response.status_code == 404


# =============================================================================
# Discovery Reconnect Endpoint Tests
# =============================================================================


class TestDiscoveryReconnectEndpoint:
    """Tests for GET /sessions/{session_id}/discovery/reconnect endpoint."""

    @pytest.mark.asyncio
    async def test_discovery_reconnect_running_returns_stream_url(
        self, test_app, workflow_store, job_store, sample_state, sample_running_job
    ):
        """Test that reconnect returns stream_url for RUNNING jobs."""
        await workflow_store.save_state(sample_state)
        await job_store.save_job(sample_running_job)

        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test"
        ) as ac:
            response = await ac.get("/sessions/test-session-123/discovery/reconnect")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert data["stream_url"] == "/sessions/test-session-123/discovery/stream"
        assert "in progress" in data["message"]
        assert data["current_progress"] is not None

    @pytest.mark.asyncio
    async def test_discovery_reconnect_completed_returns_itinerary(
        self, test_app, workflow_store, job_store, sample_state, sample_completed_job
    ):
        """Test that reconnect returns itinerary for COMPLETED jobs."""
        await workflow_store.save_state(sample_state)
        await job_store.save_job(sample_completed_job)

        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test"
        ) as ac:
            response = await ac.get("/sessions/test-session-123/discovery/reconnect")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["stream_url"] is None
        assert data["itinerary_draft"] is not None
        assert data["checkpoint"] == "itinerary_approval"
        assert "itinerary is ready" in data["message"]

    @pytest.mark.asyncio
    async def test_discovery_reconnect_partial_returns_itinerary_with_gaps(
        self, test_app, workflow_store, job_store, sample_state, sample_partial_job
    ):
        """Test that reconnect returns itinerary with gaps for PARTIAL jobs."""
        await workflow_store.save_state(sample_state)
        await job_store.save_job(sample_partial_job)

        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test"
        ) as ac:
            response = await ac.get("/sessions/test-session-123/discovery/reconnect")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "partial"
        assert data["itinerary_draft"] is not None
        assert data["gaps"] is not None
        assert len(data["gaps"]) == 2
        assert data["checkpoint"] == "itinerary_approval"

    @pytest.mark.asyncio
    async def test_discovery_reconnect_no_job_returns_guidance(
        self, test_app, workflow_store
    ):
        """Test that reconnect returns guidance when no active job."""
        state = WorkflowStateData(
            session_id="test-session",
            consultation_id="test-consultation",
            phase="CLARIFICATION",
            current_job_id=None,
        )
        await workflow_store.save_state(state)

        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test"
        ) as ac:
            response = await ac.get("/sessions/test-session/discovery/reconnect")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "no_job"
        assert "No active discovery job" in data["message"]

    @pytest.mark.asyncio
    async def test_discovery_reconnect_failed_job(
        self, test_app, workflow_store, job_store
    ):
        """Test reconnect response for FAILED jobs."""
        state = WorkflowStateData(
            session_id="test-session",
            consultation_id="test-consultation",
            phase="DISCOVERY_IN_PROGRESS",
            current_job_id="job-failed",
        )
        await workflow_store.save_state(state)

        failed_job = DiscoveryJob(
            job_id="job-failed",
            consultation_id="test-consultation",
            workflow_version=1,
            status=JobStatus.FAILED,
            error="All agents timed out",
        )
        await job_store.save_job(failed_job)

        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test"
        ) as ac:
            response = await ac.get("/sessions/test-session/discovery/reconnect")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert "failed" in data["message"].lower()

    def test_discovery_reconnect_404_without_session(self, client):
        """Test that reconnect returns 404 when session not found."""
        response = client.get("/sessions/nonexistent-session/discovery/reconnect")
        assert response.status_code == 404


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestHelperFunctions:
    """Tests for helper functions in discovery module."""

    def test_build_status_message_pending(self):
        """Test status message for pending job."""
        job = DiscoveryJob(
            job_id="job-1",
            consultation_id="con-1",
            workflow_version=1,
            status=JobStatus.PENDING,
        )
        message = _build_status_message(job)
        assert "pending" in message.lower()

    def test_build_status_message_running_discovery(self):
        """Test status message for running job in discovery stage."""
        job = DiscoveryJob(
            job_id="job-1",
            consultation_id="con-1",
            workflow_version=1,
            status=JobStatus.RUNNING,
            pipeline_stage="discovery",
        )
        message = _build_status_message(job)
        assert "Searching" in message

    def test_build_status_message_running_planning(self):
        """Test status message for running job in planning stage."""
        job = DiscoveryJob(
            job_id="job-1",
            consultation_id="con-1",
            workflow_version=1,
            status=JobStatus.RUNNING,
            pipeline_stage="aggregator",
        )
        message = _build_status_message(job)
        assert "Building itinerary" in message

    def test_build_status_message_completed(self):
        """Test status message for completed job."""
        job = DiscoveryJob(
            job_id="job-1",
            consultation_id="con-1",
            workflow_version=1,
            status=JobStatus.COMPLETED,
        )
        message = _build_status_message(job)
        assert "ready" in message.lower()

    def test_build_state_event_includes_completion_percentage(self):
        """Test that state event includes completion percentage."""
        job = DiscoveryJob(
            job_id="job-1",
            consultation_id="con-1",
            workflow_version=1,
            status=JobStatus.RUNNING,
            agent_progress={
                "transport": AgentProgress(agent="transport", status="completed"),
                "stay": AgentProgress(agent="stay", status="completed"),
                "poi": AgentProgress(agent="poi", status="running"),
                "events": AgentProgress(agent="events", status="pending"),
                "dining": AgentProgress(agent="dining", status="pending"),
            },
        )
        event = _build_state_event(job)
        assert event.type == ProgressEventType.STATE
        assert event.data["completion_percentage"] == 40  # 2/5 = 40%

    def test_build_result_event_completed(self):
        """Test result event for completed job."""
        job = DiscoveryJob(
            job_id="job-1",
            consultation_id="con-1",
            workflow_version=1,
            status=JobStatus.COMPLETED,
            itinerary_draft={"destination": "Tokyo"},
        )
        event = _build_result_event(job)
        assert event.type == ProgressEventType.JOB_COMPLETED
        assert event.data["itinerary_draft"]["destination"] == "Tokyo"

    def test_build_result_event_failed(self):
        """Test result event for failed job."""
        job = DiscoveryJob(
            job_id="job-1",
            consultation_id="con-1",
            workflow_version=1,
            status=JobStatus.FAILED,
            error="All agents timed out",
        )
        event = _build_result_event(job)
        assert event.type == ProgressEventType.JOB_FAILED
        assert event.data["error"] == "All agents timed out"


# =============================================================================
# Router Factory Tests
# =============================================================================


class TestDiscoveryRouterFactory:
    """Tests for create_discovery_router factory function."""

    def test_create_router_with_defaults(self):
        """Test that router can be created with default stores."""
        router = create_discovery_router()
        assert router is not None
        assert router.prefix == "/sessions"

    def test_create_router_with_custom_stores(self, workflow_store, job_store):
        """Test that router can be created with custom stores."""
        router = create_discovery_router(
            workflow_state_store=workflow_store,
            discovery_job_store=job_store,
        )
        assert router is not None

    def test_router_has_correct_routes(self):
        """Test that router has all expected routes."""
        router = create_discovery_router()
        route_paths = [route.path for route in router.routes]
        # Routes include the prefix "/sessions"
        assert "/sessions/{session_id}/discovery/stream" in route_paths
        assert "/sessions/{session_id}/discovery/status" in route_paths
        assert "/sessions/{session_id}/discovery/reconnect" in route_paths
