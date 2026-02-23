"""Unit tests for DiscoveryHandler.

Per design doc Three-Phase Workflow and Long-Running Operations sections.

Tests cover:
- Starting discovery jobs
- Aggregating results from discovery agents
- Handling partial failures
- Transitioning to planning when ready
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.orchestrator.discovery.parallel_executor import (
    DiscoveryResults as ParallelDiscoveryResults,
)
from src.orchestrator.handlers.discovery import (
    AGENT_TIMEOUTS,
    DISCOVERY_AGENTS,
    AgentDiscoveryResult,
    DiscoveryHandler,
    DiscoveryResults,
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
def workflow_state_at_approval() -> WorkflowState:
    """Create a workflow state at itinerary approval checkpoint."""
    return WorkflowState(
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
        itinerary_draft={
            "consultation_id": "cons_test456",
            "trip_summary": {
                "destination": "Tokyo",
                "start_date": "2024-03-10",
                "end_date": "2024-03-17",
                "travelers": 2,
                "trip_type": "leisure",
            },
            "days": [
                {
                    "day_number": 1,
                    "date": "2024-03-10",
                    "title": "Arrival Day",
                    "activities": [
                        {
                            "name": "Visit Senso-ji Temple",
                            "location": "Asakusa",
                            "description": "Historic Buddhist temple",
                            "start_time": "10:00",
                            "end_time": "12:00",
                            "estimated_cost": 0,
                            "currency": "USD",
                            "booking_required": False,
                        },
                    ],
                    "meals": [],
                    "transport": [
                        {
                            "mode": "flight",
                            "from_location": "Los Angeles",
                            "to_location": "Tokyo Narita",
                            "departure_time": "2024-03-10T08:00:00",
                            "arrival_time": "2024-03-10T14:00:00",
                            "carrier": "ANA",
                            "estimated_cost": 800,
                            "currency": "USD",
                        },
                    ],
                    "accommodation": {
                        "name": "Tokyo Grand Hotel",
                        "location": "Shinjuku",
                        "check_in": "2024-03-10T15:00:00",
                        "check_out": "2024-03-11T11:00:00",
                        "room_type": "Deluxe",
                        "estimated_cost": 200,
                        "currency": "USD",
                    },
                    "estimated_daily_cost": 1000,
                    "currency": "USD",
                },
                {
                    "day_number": 2,
                    "date": "2024-03-11",
                    "title": "Exploration Day",
                    "activities": [
                        {
                            "name": "Tokyo Skytree Observation Deck",
                            "location": "Tokyo Skytree",
                            "description": "Observation deck with city views",
                            "start_time": "09:00",
                            "end_time": "11:00",
                            "estimated_cost": 30,
                            "currency": "USD",
                            "booking_required": True,
                        },
                    ],
                    "meals": [],
                    "transport": [],
                    "estimated_daily_cost": 230,
                    "currency": "USD",
                },
            ],
            "total_estimated_cost": 1230,
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
def discovery_handler(
    workflow_state: WorkflowState,
    state_data: WorkflowStateData,
    discovery_job_store: InMemoryDiscoveryJobStore,
) -> DiscoveryHandler:
    """Create a discovery handler with mock dependencies."""
    return DiscoveryHandler(
        state=workflow_state,
        state_data=state_data,
        discovery_job_store=discovery_job_store,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Discovery Result Model Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentDiscoveryResult:
    """Tests for AgentDiscoveryResult dataclass."""

    def test_create_success_result(self):
        """Test creating a successful result."""
        result = AgentDiscoveryResult(
            agent="transport",
            status="success",
            data={"options": [{"flight": "AA123"}]},
        )
        assert result.agent == "transport"
        assert result.status == "success"
        assert result.data == {"options": [{"flight": "AA123"}]}
        assert result.retry_possible is False

    def test_create_error_result(self):
        """Test creating an error result."""
        result = AgentDiscoveryResult(
            agent="stay",
            status="error",
            message="Connection timeout",
            retry_possible=True,
        )
        assert result.agent == "stay"
        assert result.status == "error"
        assert result.message == "Connection timeout"
        assert result.retry_possible is True

    def test_to_dict(self):
        """Test serialization to dictionary."""
        result = AgentDiscoveryResult(
            agent="poi",
            status="success",
            data={"attractions": []},
            message="Found 10 attractions",
        )
        result_dict = result.to_dict()
        assert result_dict["agent"] == "poi"
        assert result_dict["status"] == "success"
        assert result_dict["data"] == {"attractions": []}
        assert "timestamp" in result_dict

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "agent": "events",
            "status": "timeout",
            "message": "Timeout after 20s",
            "retry_possible": True,
            "timestamp": "2024-03-10T10:00:00+00:00",
        }
        result = AgentDiscoveryResult.from_dict(data)
        assert result.agent == "events"
        assert result.status == "timeout"
        assert result.retry_possible is True


class TestDiscoveryResults:
    """Tests for DiscoveryResults dataclass."""

    def test_empty_results(self):
        """Test empty results."""
        results = DiscoveryResults()
        assert results.get_successful_count() == 0
        assert results.get_failed_agents() == []
        assert results.has_partial_success() is False

    def test_all_successful(self):
        """Test all agents successful."""
        results = DiscoveryResults(
            transport=AgentDiscoveryResult(agent="transport", status="success"),
            stay=AgentDiscoveryResult(agent="stay", status="success"),
            poi=AgentDiscoveryResult(agent="poi", status="success"),
            events=AgentDiscoveryResult(agent="events", status="success"),
            dining=AgentDiscoveryResult(agent="dining", status="success"),
        )
        assert results.get_successful_count() == 5
        assert results.get_failed_agents() == []
        assert results.has_partial_success() is False

    def test_partial_success(self):
        """Test partial success with some failures."""
        results = DiscoveryResults(
            transport=AgentDiscoveryResult(agent="transport", status="success"),
            stay=AgentDiscoveryResult(agent="stay", status="success"),
            poi=AgentDiscoveryResult(agent="poi", status="error"),
            events=AgentDiscoveryResult(agent="events", status="timeout"),
            dining=AgentDiscoveryResult(agent="dining", status="success"),
        )
        assert results.get_successful_count() == 3
        assert set(results.get_failed_agents()) == {"poi", "events"}
        assert results.has_partial_success() is True

    def test_to_dict(self):
        """Test serialization."""
        results = DiscoveryResults(
            transport=AgentDiscoveryResult(agent="transport", status="success"),
        )
        results_dict = results.to_dict()
        assert "transport" in results_dict
        assert results_dict["transport"]["status"] == "success"

    def test_from_dict(self):
        """Test deserialization."""
        data = {
            "transport": {"agent": "transport", "status": "success"},
            "stay": {"agent": "stay", "status": "error", "message": "Failed"},
        }
        results = DiscoveryResults.from_dict(data)
        assert results.transport is not None
        assert results.transport.status == "success"
        assert results.stay is not None
        assert results.stay.status == "error"


# ═══════════════════════════════════════════════════════════════════════════════
# DiscoveryHandler Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestDiscoveryHandlerStartsJob:
    """Tests for starting discovery jobs via retry_discovery."""

    @pytest.mark.asyncio
    async def test_discovery_handler_starts_job(
        self, discovery_handler: DiscoveryHandler, discovery_job_store: InMemoryDiscoveryJobStore
    ):
        """Test that retry_discovery creates a job."""
        result = await discovery_handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Find me options",
            event=WorkflowEvent(type="retry_discovery"),
        )

        # Check response
        assert result.response.success is True
        assert "job_id" in result.response.data
        assert "stream_url" in result.response.data

        # Check job was created in store
        job_id = result.response.data["job_id"]
        job = await discovery_job_store.get_job(job_id, "cons_test456")
        assert job is not None
        assert job.status == JobStatus.RUNNING
        assert len(job.agent_progress) == len(DISCOVERY_AGENTS)

    @pytest.mark.asyncio
    async def test_discovery_handler_starts_job_with_correct_progress(
        self, discovery_handler: DiscoveryHandler, discovery_job_store: InMemoryDiscoveryJobStore
    ):
        """Test that job has correct initial progress."""
        result = await discovery_handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Find me options",
            event=WorkflowEvent(type="retry_discovery"),
        )

        job_id = result.response.data["job_id"]
        job = await discovery_job_store.get_job(job_id, "cons_test456")

        # All agents should be pending
        for agent in DISCOVERY_AGENTS:
            assert agent in job.agent_progress
            assert job.agent_progress[agent].status == "pending"

    @pytest.mark.asyncio
    async def test_discovery_handler_starts_job_updates_state(
        self, discovery_handler: DiscoveryHandler
    ):
        """Test that retry_discovery updates workflow state."""
        result = await discovery_handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Find me options",
            event=WorkflowEvent(type="retry_discovery"),
        )

        # Check state was updated
        assert discovery_handler.state.current_job_id is not None
        assert discovery_handler.state.phase == Phase.DISCOVERY_IN_PROGRESS

    @pytest.mark.asyncio
    async def test_discovery_handler_starts_job_returns_stream_url(
        self, discovery_handler: DiscoveryHandler
    ):
        """Test that retry_discovery returns stream URL."""
        result = await discovery_handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Find me options",
            event=WorkflowEvent(type="retry_discovery"),
        )

        stream_url = result.response.data.get("stream_url")
        assert stream_url is not None
        assert "/discovery/stream" in stream_url

    @pytest.mark.asyncio
    async def test_discovery_handler_start_discovery_is_status_only(
        self, state_data: WorkflowStateData
    ):
        """Test that START_DISCOVERY is treated as a status request."""
        state_without_trip_spec = WorkflowState(
            session_id="sess_test123",
            consultation_id="cons_test456",
            phase=Phase.DISCOVERY_IN_PROGRESS,
            trip_spec=None,  # No trip spec
        )
        handler = DiscoveryHandler(
            state=state_without_trip_spec,
            state_data=state_data,
        )

        result = await handler.execute(
            action=Action.START_DISCOVERY,
            message="Find me options",
        )

        assert result.response.success is True
        assert "no discovery job" in result.response.message.lower()


class TestDiscoveryHandlerAggregatesResults:
    """Tests for result aggregation."""

    @pytest.mark.asyncio
    async def test_discovery_handler_aggregates_results_success(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test aggregating successful results."""
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        # Create a job
        job = DiscoveryJob(
            job_id="job_test123",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.RUNNING,
        )
        await discovery_job_store.save_job(job)

        # Run parallel agents (stub mode - no real agents)
        results = await handler._run_discovery_agents_parallel(
            job, workflow_state.trip_spec
        )

        # All should succeed in stub mode
        assert results.get_successful_count() == len(DISCOVERY_AGENTS)
        assert results.get_failed_agents() == []

    @pytest.mark.asyncio
    async def test_discovery_handler_aggregates_results_updates_job(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that aggregation updates job in store."""
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        job = DiscoveryJob(
            job_id="job_test123",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.RUNNING,
        )
        await discovery_job_store.save_job(job)

        await handler._run_discovery_agents_parallel(job, workflow_state.trip_spec)

        # Reload job and check it was updated
        updated_job = await discovery_job_store.get_job("job_test123", "cons_test456")
        assert updated_job.status == JobStatus.COMPLETED
        assert updated_job.completed_at is not None
        assert updated_job.discovery_results is not None


class TestDiscoveryHandlerHandlesPartialFailure:
    """Tests for partial failure handling."""

    @pytest.mark.asyncio
    async def test_discovery_handler_handles_partial_failure(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test handling partial agent failures."""
        # Mock A2A client to fail for some agents
        mock_a2a_client = MagicMock()
        mock_registry = MagicMock()

        # Configure registry to return agent configs
        def get_agent(name):
            config = MagicMock()
            config.url = f"http://{name}:8000"
            return config

        mock_registry.get.side_effect = get_agent

        # Configure client to fail for some agents
        async def mock_send_message(agent_url, message, **kwargs):
            if "poi" in agent_url or "events" in agent_url:
                raise Exception("Connection refused")
            response = MagicMock()
            response.text = f"Found results"
            response.data = {"options": []}
            return response

        mock_a2a_client.send_message = mock_send_message

        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            a2a_client=mock_a2a_client,
            agent_registry=mock_registry,
            discovery_job_store=discovery_job_store,
        )

        job = DiscoveryJob(
            job_id="job_test123",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.RUNNING,
        )
        await discovery_job_store.save_job(job)

        results = await handler._run_discovery_agents_parallel(job, workflow_state.trip_spec)

        # Should have partial results
        failed_agents = results.get_failed_agents()
        assert len(failed_agents) > 0
        assert results.has_partial_success() is True

    @pytest.mark.asyncio
    async def test_discovery_handler_sets_partial_status(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test that partial failure sets PARTIAL status."""
        # Create handler and manually set up a partial failure scenario
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        job = DiscoveryJob(
            job_id="job_test123",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.RUNNING,
        )
        await discovery_job_store.save_job(job)

        partial_results = ParallelDiscoveryResults.from_dict(
            {
                "transport": {"status": "success", "data": {}},
                "stay": {"status": "success", "data": {}},
                "poi": {"status": "success", "data": {}},
                "events": {"status": "error", "message": "Simulated failure"},
                "dining": {"status": "success", "data": {}},
            }
        )

        with patch(
            "src.orchestrator.discovery.parallel_executor.execute_parallel_discovery",
            new=AsyncMock(return_value=partial_results),
        ):
            await handler._run_discovery_agents_parallel(job, workflow_state.trip_spec)

        # Check job status - should be PARTIAL (4 success, 1 failure)
        updated_job = await discovery_job_store.get_job("job_test123", "cons_test456")
        assert updated_job.status == JobStatus.PARTIAL


class TestDiscoveryHandlerTransitionsToPlanning:
    """Tests for transitioning to planning phase."""

    @pytest.mark.asyncio
    async def test_discovery_handler_transitions_to_planning(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data: WorkflowStateData,
    ):
        """Test transitioning from discovery to booking on approval."""
        state_data.phase = "discovery_planning"
        state_data.checkpoint = "itinerary_approval"

        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data,
        )

        result = await handler.execute(
            action=Action.APPROVE_ITINERARY,
            message="Looks good!",
        )

        assert result.response.success is True
        assert handler.state.phase == Phase.BOOKING
        assert handler.state.checkpoint is None
        assert handler.state.itinerary_id is not None
        assert "itinerary_id" in result.response.data

    @pytest.mark.asyncio
    async def test_discovery_handler_transitions_creates_itinerary_id(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data: WorkflowStateData,
    ):
        """Test that approval creates an itinerary ID."""
        state_data.phase = "discovery_planning"
        state_data.checkpoint = "itinerary_approval"

        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data,
        )

        result = await handler.execute(
            action=Action.APPROVE_ITINERARY,
            message="Approve",
        )

        itinerary_id = result.response.data.get("itinerary_id")
        assert itinerary_id is not None
        assert itinerary_id.startswith("itn_")

    @pytest.mark.asyncio
    async def test_discovery_handler_transitions_provides_booking_items(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data: WorkflowStateData,
    ):
        """Test that approval provides booking items for next phase."""
        state_data.phase = "discovery_planning"
        state_data.checkpoint = "itinerary_approval"

        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data,
        )

        result = await handler.execute(
            action=Action.APPROVE_ITINERARY,
            message="Approve",
        )

        booking_items = result.response.data.get("booking_items")
        assert booking_items is not None
        assert len(booking_items) > 0
        for item in booking_items:
            assert "booking_id" in item
            assert item["booking_id"].startswith("book_")

    @pytest.mark.asyncio
    async def test_discovery_handler_creates_itinerary_in_store(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data: WorkflowStateData,
    ):
        """Test that approval persists Itinerary to itinerary store."""
        from src.orchestrator.storage.itinerary_store import InMemoryItineraryStore

        state_data.phase = "discovery_planning"
        state_data.checkpoint = "itinerary_approval"

        itinerary_store = InMemoryItineraryStore()

        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data,
            itinerary_store=itinerary_store,
        )

        result = await handler.execute(
            action=Action.APPROVE_ITINERARY,
            message="Approve",
        )

        assert result.response.success is True
        itinerary_id = result.response.data.get("itinerary_id")

        # Check itinerary was saved to store
        itinerary = await itinerary_store.get_itinerary(itinerary_id)
        assert itinerary is not None
        assert itinerary.itinerary_id == itinerary_id
        assert itinerary.consultation_id == "cons_test456"
        assert len(itinerary.booking_ids) > 0

    @pytest.mark.asyncio
    async def test_discovery_handler_creates_bookings_in_store(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data: WorkflowStateData,
    ):
        """Test that approval creates Booking records in booking store."""
        from src.orchestrator.storage.booking_store import InMemoryBookingStore

        state_data.phase = "discovery_planning"
        state_data.checkpoint = "itinerary_approval"

        booking_store = InMemoryBookingStore()

        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data,
            booking_store=booking_store,
        )

        result = await handler.execute(
            action=Action.APPROVE_ITINERARY,
            message="Approve",
        )

        assert result.response.success is True
        booking_items = result.response.data.get("booking_items", [])

        # Check each booking was saved to store
        for item in booking_items:
            booking_id = item["booking_id"]
            booking = await booking_store.get_booking(booking_id)
            assert booking is not None
            assert booking.status.value == "unbooked"

    @pytest.mark.asyncio
    async def test_discovery_handler_updates_consultation_summary(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data: WorkflowStateData,
    ):
        """Test that approval upserts ConsultationSummary."""
        from src.orchestrator.storage.consultation_summaries import (
            InMemoryConsultationSummaryStore,
        )

        state_data.phase = "discovery_planning"
        state_data.checkpoint = "itinerary_approval"

        summary_store = InMemoryConsultationSummaryStore()

        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data,
            consultation_summary_store=summary_store,
        )

        result = await handler.execute(
            action=Action.APPROVE_ITINERARY,
            message="Approve",
        )

        assert result.response.success is True

        # Check consultation summary was created
        summary = await summary_store.get_summary("cons_test456")
        assert summary is not None
        assert summary.status == "itinerary_approved"
        assert len(summary.itinerary_ids) > 0
        assert len(summary.booking_ids) > 0
        assert summary.trip_spec_summary["destination"] == "Tokyo"

    @pytest.mark.asyncio
    async def test_discovery_handler_clears_itinerary_draft_on_approval(
        self,
        workflow_state_at_approval: WorkflowState,
        state_data: WorkflowStateData,
    ):
        """Test that approval clears itinerary_draft from state."""
        state_data.phase = "discovery_planning"
        state_data.checkpoint = "itinerary_approval"

        handler = DiscoveryHandler(
            state=workflow_state_at_approval,
            state_data=state_data,
        )

        # Verify draft exists before
        assert workflow_state_at_approval.itinerary_draft is not None

        result = await handler.execute(
            action=Action.APPROVE_ITINERARY,
            message="Approve",
        )

        assert result.response.success is True
        # Draft should be cleared after approval
        assert handler.state.itinerary_draft is None

    @pytest.mark.asyncio
    async def test_discovery_handler_fails_without_draft(
        self,
        state_data: WorkflowStateData,
    ):
        """Test that approval fails when no itinerary_draft exists."""
        state_without_draft = WorkflowState(
            session_id="sess_test123",
            consultation_id="cons_test456",
            phase=Phase.DISCOVERY_PLANNING,
            checkpoint="itinerary_approval",
            workflow_version=1,
            itinerary_draft=None,  # No draft
        )

        state_data.phase = "discovery_planning"
        state_data.checkpoint = "itinerary_approval"

        handler = DiscoveryHandler(
            state=state_without_draft,
            state_data=state_data,
        )

        result = await handler.execute(
            action=Action.APPROVE_ITINERARY,
            message="Approve",
        )

        assert result.response.success is False
        assert "missing" in result.response.message.lower() or "no" in result.response.message.lower()


class TestDiscoveryHandlerStatus:
    """Tests for discovery status retrieval."""

    @pytest.mark.asyncio
    async def test_get_status_no_job(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
    ):
        """Test getting status when no job exists."""
        workflow_state.current_job_id = None
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
        )

        result = await handler._get_discovery_status()

        assert result.response.success is True
        assert "no discovery job" in result.response.message.lower()

    @pytest.mark.asyncio
    async def test_get_status_job_running(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test getting status of a running job."""
        # Create a running job
        job = DiscoveryJob(
            job_id="job_test123",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.RUNNING,
            agent_progress={
                "transport": AgentProgress(agent="transport", status="completed"),
                "stay": AgentProgress(agent="stay", status="running"),
                "poi": AgentProgress(agent="poi", status="pending"),
                "events": AgentProgress(agent="events", status="pending"),
                "dining": AgentProgress(agent="dining", status="pending"),
            },
        )
        await discovery_job_store.save_job(job)

        workflow_state.current_job_id = "job_test123"
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        result = await handler._get_discovery_status()

        assert result.response.success is True
        assert result.response.data["status"] == "running"
        assert "agent_progress" in result.response.data


class TestDiscoveryHandlerModification:
    """Tests for modification handling."""

    @pytest.mark.asyncio
    async def test_retry_agent(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test retrying a failed agent re-runs it and returns updated progress."""
        # Create a job with a failed agent
        # Include all agents so we don't trigger planning pipeline
        job = DiscoveryJob(
            job_id="job_test123",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.PARTIAL,
            agent_progress={
                "transport": AgentProgress(agent="transport", status="completed"),
                "stay": AgentProgress(agent="stay", status="failed"),
                "poi": AgentProgress(agent="poi", status="running"),  # Still running
                "events": AgentProgress(agent="events", status="pending"),
                "dining": AgentProgress(agent="dining", status="pending"),
            },
        )
        await discovery_job_store.save_job(job)

        workflow_state.current_job_id = "job_test123"
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        event = WorkflowEvent(type="retry_agent", agent_id="stay")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Retry",
            event=event,
        )

        assert result.response.success is True
        assert result.response.data["agent"] == "stay"
        assert result.response.data["action"] == "retry"

        # With the new implementation, the agent is re-run (in stub mode, completes)
        # and progress is updated to completed (since stub always succeeds)
        updated_job = await discovery_job_store.get_job("job_test123", "cons_test456")
        assert updated_job.agent_progress["stay"].status == "completed"

    @pytest.mark.asyncio
    async def test_skip_agent(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test skipping a failed agent marks it as SKIPPED (not completed)."""
        # Include all agents - some non-terminal to avoid triggering planning
        job = DiscoveryJob(
            job_id="job_test123",
            consultation_id="cons_test456",
            workflow_version=1,
            status=JobStatus.PARTIAL,
            agent_progress={
                "transport": AgentProgress(agent="transport", status="completed"),
                "stay": AgentProgress(agent="stay", status="failed"),
                "poi": AgentProgress(agent="poi", status="running"),  # Still running
                "events": AgentProgress(agent="events", status="pending"),
                "dining": AgentProgress(agent="dining", status="pending"),
            },
        )
        await discovery_job_store.save_job(job)

        workflow_state.current_job_id = "job_test123"
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        event = WorkflowEvent(type="skip_agent", agent_id="stay")
        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="Skip",
            event=event,
        )

        assert result.response.success is True
        assert result.response.data["action"] == "skip"

        # Check progress was updated - now uses "skipped" status per ORCH-093
        updated_job = await discovery_job_store.get_job("job_test123", "cons_test456")
        assert updated_job.agent_progress["stay"].status == "skipped"
        assert "Skipped" in updated_job.agent_progress["stay"].message

    @pytest.mark.asyncio
    async def test_invalid_agent_retry(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
        discovery_job_store: InMemoryDiscoveryJobStore,
    ):
        """Test retrying an invalid agent returns error with valid agents list."""
        # Need a job reference for the error handling to work
        workflow_state.current_job_id = "job_test123"
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
            discovery_job_store=discovery_job_store,
        )

        result = await handler._retry_agent("invalid_agent")

        assert result.response.success is False
        assert result.response.data.get("error") == "invalid_agent"
        assert "valid_agents" in result.response.data


class TestDiscoveryHandlerConstants:
    """Tests for handler constants."""

    def test_discovery_agents_list(self):
        """Test that DISCOVERY_AGENTS has the expected agents."""
        expected = {"transport", "stay", "poi", "events", "dining"}
        assert set(DISCOVERY_AGENTS) == expected

    def test_agent_timeouts(self):
        """Test that all discovery agents have timeouts."""
        for agent in DISCOVERY_AGENTS:
            assert agent in AGENT_TIMEOUTS
            assert AGENT_TIMEOUTS[agent] > 0


class TestDiscoveryHandlerStubResults:
    """Tests for stub result generation."""

    def test_create_stub_discovery_result(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
    ):
        """Test stub result generation for testing."""
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
        )

        for agent in DISCOVERY_AGENTS:
            result = handler._create_stub_discovery_result(agent, workflow_state.trip_spec)
            assert "options" in result
            assert "message" in result


class TestDiscoveryHandlerFormatRequest:
    """Tests for request formatting."""

    def test_format_discovery_request_transport(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
    ):
        """Test formatting transport request."""
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
        )

        request = handler._format_discovery_request("transport", workflow_state.trip_spec)

        assert "Tokyo" in request
        assert "2024-03-10" in request
        assert "2024-03-17" in request
        assert "2" in request  # travelers

    def test_format_discovery_request_all_agents(
        self,
        workflow_state: WorkflowState,
        state_data: WorkflowStateData,
    ):
        """Test formatting requests for all agents."""
        handler = DiscoveryHandler(
            state=workflow_state,
            state_data=state_data,
        )

        for agent in DISCOVERY_AGENTS:
            request = handler._format_discovery_request(agent, workflow_state.trip_spec)
            assert len(request) > 0
            assert "Tokyo" in request  # All should mention destination
