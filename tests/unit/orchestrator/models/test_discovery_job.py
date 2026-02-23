"""
Unit tests for discovery_job models.

Tests the DiscoveryJobModel, AgentJobProgress, AgentJobStatus,
DiscoveryJobStatus, and completion percentage calculation.
"""

from datetime import datetime, timezone

import pytest

from src.orchestrator.models.discovery_job import (
    DISCOVERY_AGENTS,
    AgentJobProgress,
    AgentJobStatus,
    DiscoveryJobModel,
    DiscoveryJobStatus,
)


class TestAgentJobStatus:
    """Tests for AgentJobStatus enum."""

    def test_agent_job_status_values(self) -> None:
        """Test that all status values are correct."""
        assert AgentJobStatus.PENDING.value == "pending"
        assert AgentJobStatus.RUNNING.value == "running"
        assert AgentJobStatus.COMPLETED.value == "completed"
        assert AgentJobStatus.FAILED.value == "failed"
        assert AgentJobStatus.TIMEOUT.value == "timeout"

    def test_agent_job_status_from_string(self) -> None:
        """Test creating AgentJobStatus from string."""
        assert AgentJobStatus("pending") == AgentJobStatus.PENDING
        assert AgentJobStatus("running") == AgentJobStatus.RUNNING
        assert AgentJobStatus("completed") == AgentJobStatus.COMPLETED
        assert AgentJobStatus("failed") == AgentJobStatus.FAILED
        assert AgentJobStatus("timeout") == AgentJobStatus.TIMEOUT

    def test_agent_job_status_is_string_enum(self) -> None:
        """Test that AgentJobStatus is a string enum."""
        assert isinstance(AgentJobStatus.PENDING, str)
        assert AgentJobStatus.PENDING == "pending"


class TestDiscoveryJobStatus:
    """Tests for DiscoveryJobStatus enum."""

    def test_discovery_job_status_values(self) -> None:
        """Test that all status values are correct."""
        assert DiscoveryJobStatus.PENDING.value == "pending"
        assert DiscoveryJobStatus.RUNNING.value == "running"
        assert DiscoveryJobStatus.COMPLETED.value == "completed"
        assert DiscoveryJobStatus.FAILED.value == "failed"
        assert DiscoveryJobStatus.PARTIAL.value == "partial"
        assert DiscoveryJobStatus.CANCELLED.value == "cancelled"

    def test_discovery_job_status_from_string(self) -> None:
        """Test creating DiscoveryJobStatus from string."""
        assert DiscoveryJobStatus("pending") == DiscoveryJobStatus.PENDING
        assert DiscoveryJobStatus("completed") == DiscoveryJobStatus.COMPLETED

    def test_discovery_job_status_is_string_enum(self) -> None:
        """Test that DiscoveryJobStatus is a string enum."""
        assert isinstance(DiscoveryJobStatus.PENDING, str)
        assert DiscoveryJobStatus.RUNNING == "running"


class TestAgentJobProgress:
    """Tests for AgentJobProgress dataclass."""

    def test_agent_progress_defaults(self) -> None:
        """Test AgentJobProgress default values."""
        progress = AgentJobProgress(agent="transport")
        assert progress.agent == "transport"
        assert progress.status == AgentJobStatus.PENDING
        assert progress.started_at is None
        assert progress.completed_at is None
        assert progress.message is None
        assert progress.result_summary is None

    def test_agent_progress_with_all_fields(self) -> None:
        """Test AgentJobProgress with all fields set."""
        now = datetime.now(timezone.utc)
        progress = AgentJobProgress(
            agent="stay",
            status=AgentJobStatus.COMPLETED,
            started_at=now,
            completed_at=now,
            message="Found 12 hotels",
            result_summary="Park Hyatt, Four Seasons, ...",
        )
        assert progress.agent == "stay"
        assert progress.status == AgentJobStatus.COMPLETED
        assert progress.started_at == now
        assert progress.completed_at == now
        assert progress.message == "Found 12 hotels"
        assert progress.result_summary == "Park Hyatt, Four Seasons, ..."

    def test_agent_progress_is_terminal(self) -> None:
        """Test is_terminal method."""
        # Non-terminal states
        assert not AgentJobProgress(agent="test", status=AgentJobStatus.PENDING).is_terminal()
        assert not AgentJobProgress(agent="test", status=AgentJobStatus.RUNNING).is_terminal()

        # Terminal states
        assert AgentJobProgress(agent="test", status=AgentJobStatus.COMPLETED).is_terminal()
        assert AgentJobProgress(agent="test", status=AgentJobStatus.FAILED).is_terminal()
        assert AgentJobProgress(agent="test", status=AgentJobStatus.TIMEOUT).is_terminal()

    def test_agent_progress_is_successful(self) -> None:
        """Test is_successful method."""
        assert AgentJobProgress(agent="test", status=AgentJobStatus.COMPLETED).is_successful()
        assert not AgentJobProgress(agent="test", status=AgentJobStatus.FAILED).is_successful()
        assert not AgentJobProgress(agent="test", status=AgentJobStatus.TIMEOUT).is_successful()
        assert not AgentJobProgress(agent="test", status=AgentJobStatus.PENDING).is_successful()

    def test_agent_progress_to_dict(self) -> None:
        """Test AgentJobProgress serialization."""
        now = datetime.now(timezone.utc)
        progress = AgentJobProgress(
            agent="poi",
            status=AgentJobStatus.RUNNING,
            started_at=now,
            message="Searching attractions...",
        )
        data = progress.to_dict()

        assert data["agent"] == "poi"
        assert data["status"] == "running"
        assert data["started_at"] == now.isoformat()
        assert data["completed_at"] is None
        assert data["message"] == "Searching attractions..."
        assert data["result_summary"] is None

    def test_agent_progress_from_dict(self) -> None:
        """Test AgentJobProgress deserialization."""
        now = datetime.now(timezone.utc)
        data = {
            "agent": "dining",
            "status": "completed",
            "started_at": now.isoformat(),
            "completed_at": now.isoformat(),
            "message": "Found 15 restaurants",
            "result_summary": "Italian, Japanese, French",
        }
        progress = AgentJobProgress.from_dict(data)

        assert progress.agent == "dining"
        assert progress.status == AgentJobStatus.COMPLETED
        assert progress.started_at == now
        assert progress.completed_at == now
        assert progress.message == "Found 15 restaurants"
        assert progress.result_summary == "Italian, Japanese, French"

    def test_agent_progress_from_dict_with_defaults(self) -> None:
        """Test deserialization with missing fields uses defaults."""
        data = {"agent": "events"}
        progress = AgentJobProgress.from_dict(data)

        assert progress.agent == "events"
        assert progress.status == AgentJobStatus.PENDING
        assert progress.started_at is None
        assert progress.completed_at is None

    def test_agent_progress_from_dict_invalid_status(self) -> None:
        """Test deserialization with invalid status defaults to PENDING."""
        data = {"agent": "test", "status": "invalid_status"}
        progress = AgentJobProgress.from_dict(data)
        assert progress.status == AgentJobStatus.PENDING


class TestDiscoveryJobModel:
    """Tests for DiscoveryJobModel dataclass."""

    def test_discovery_job_creation(self) -> None:
        """Test basic DiscoveryJobModel creation."""
        job = DiscoveryJobModel(
            job_id="job_abc123",
            consultation_id="cons_xyz789",
            workflow_version=1,
        )
        assert job.job_id == "job_abc123"
        assert job.consultation_id == "cons_xyz789"
        assert job.workflow_version == 1
        assert job.status == DiscoveryJobStatus.PENDING
        assert job.completed_at is None
        assert job.cancelled_at is None
        assert job.agent_progress == {}
        assert job.pipeline_stage is None
        assert job.discovery_results is None
        assert job.itinerary_draft is None
        assert job.error is None

    def test_discovery_job_create_factory(self) -> None:
        """Test create factory method with initialized agents."""
        job = DiscoveryJobModel.create(
            job_id="job_test",
            consultation_id="cons_test",
            workflow_version=2,
        )

        assert job.job_id == "job_test"
        assert job.status == DiscoveryJobStatus.PENDING
        assert len(job.agent_progress) == len(DISCOVERY_AGENTS)

        for agent in DISCOVERY_AGENTS:
            assert agent in job.agent_progress
            assert job.agent_progress[agent].status == AgentJobStatus.PENDING

    def test_discovery_job_create_with_custom_agents(self) -> None:
        """Test create factory with custom agent list."""
        custom_agents = ("transport", "stay")
        job = DiscoveryJobModel.create(
            job_id="job_custom",
            consultation_id="cons_custom",
            workflow_version=1,
            agents=custom_agents,
        )

        assert len(job.agent_progress) == 2
        assert "transport" in job.agent_progress
        assert "stay" in job.agent_progress
        assert "poi" not in job.agent_progress

    def test_discovery_job_is_terminal(self) -> None:
        """Test is_terminal method."""
        job = DiscoveryJobModel(
            job_id="job_test",
            consultation_id="cons_test",
            workflow_version=1,
        )

        # Non-terminal states
        job.status = DiscoveryJobStatus.PENDING
        assert not job.is_terminal()

        job.status = DiscoveryJobStatus.RUNNING
        assert not job.is_terminal()

        # Terminal states
        job.status = DiscoveryJobStatus.COMPLETED
        assert job.is_terminal()

        job.status = DiscoveryJobStatus.FAILED
        assert job.is_terminal()

        job.status = DiscoveryJobStatus.PARTIAL
        assert job.is_terminal()

        job.status = DiscoveryJobStatus.CANCELLED
        assert job.is_terminal()

    def test_discovery_job_is_successful(self) -> None:
        """Test is_successful method."""
        job = DiscoveryJobModel(
            job_id="job_test",
            consultation_id="cons_test",
            workflow_version=1,
        )

        job.status = DiscoveryJobStatus.COMPLETED
        assert job.is_successful()

        job.status = DiscoveryJobStatus.PARTIAL
        assert not job.is_successful()

        job.status = DiscoveryJobStatus.FAILED
        assert not job.is_successful()

    def test_discovery_job_completion_percentage_no_agents(self) -> None:
        """Test completion percentage with no agents."""
        job = DiscoveryJobModel(
            job_id="job_test",
            consultation_id="cons_test",
            workflow_version=1,
        )
        # No agents means 100% complete
        assert job.completion_percentage == 100.0

    def test_discovery_job_completion_percentage_all_pending(self) -> None:
        """Test completion percentage with all agents pending."""
        job = DiscoveryJobModel.create(
            job_id="job_test",
            consultation_id="cons_test",
            workflow_version=1,
        )
        # All 5 agents pending = 0%
        assert job.completion_percentage == 0.0

    def test_discovery_job_completion_percentage_partial(self) -> None:
        """Test completion percentage with partial completion."""
        job = DiscoveryJobModel.create(
            job_id="job_test",
            consultation_id="cons_test",
            workflow_version=1,
        )

        # Complete 2 out of 5 agents
        job.update_agent_progress("transport", AgentJobStatus.COMPLETED)
        job.update_agent_progress("stay", AgentJobStatus.COMPLETED)

        assert job.completion_percentage == 40.0  # 2/5 = 40%

    def test_discovery_job_completion_percentage_all_complete(self) -> None:
        """Test completion percentage with all agents complete."""
        job = DiscoveryJobModel.create(
            job_id="job_test",
            consultation_id="cons_test",
            workflow_version=1,
        )

        for agent in DISCOVERY_AGENTS:
            job.update_agent_progress(agent, AgentJobStatus.COMPLETED)

        assert job.completion_percentage == 100.0

    def test_discovery_job_completion_percentage_mixed_terminal(self) -> None:
        """Test completion percentage counts all terminal states."""
        job = DiscoveryJobModel.create(
            job_id="job_test",
            consultation_id="cons_test",
            workflow_version=1,
        )

        # Mix of terminal states
        job.update_agent_progress("transport", AgentJobStatus.COMPLETED)
        job.update_agent_progress("stay", AgentJobStatus.FAILED)
        job.update_agent_progress("poi", AgentJobStatus.TIMEOUT)
        # events and dining still pending

        assert job.completion_percentage == 60.0  # 3/5 = 60%

    def test_discovery_job_completed_agents(self) -> None:
        """Test completed_agents property."""
        job = DiscoveryJobModel.create(
            job_id="job_test",
            consultation_id="cons_test",
            workflow_version=1,
        )

        job.update_agent_progress("transport", AgentJobStatus.COMPLETED)
        job.update_agent_progress("stay", AgentJobStatus.COMPLETED)
        job.update_agent_progress("poi", AgentJobStatus.FAILED)

        completed = job.completed_agents
        assert len(completed) == 2
        assert "transport" in completed
        assert "stay" in completed
        assert "poi" not in completed

    def test_discovery_job_failed_agents(self) -> None:
        """Test failed_agents property."""
        job = DiscoveryJobModel.create(
            job_id="job_test",
            consultation_id="cons_test",
            workflow_version=1,
        )

        job.update_agent_progress("transport", AgentJobStatus.COMPLETED)
        job.update_agent_progress("stay", AgentJobStatus.FAILED)
        job.update_agent_progress("poi", AgentJobStatus.TIMEOUT)

        failed = job.failed_agents
        assert len(failed) == 2
        assert "stay" in failed
        assert "poi" in failed
        assert "transport" not in failed

    def test_discovery_job_pending_agents(self) -> None:
        """Test pending_agents property."""
        job = DiscoveryJobModel.create(
            job_id="job_test",
            consultation_id="cons_test",
            workflow_version=1,
        )

        job.update_agent_progress("transport", AgentJobStatus.COMPLETED)
        job.update_agent_progress("stay", AgentJobStatus.RUNNING)

        pending = job.pending_agents
        assert len(pending) == 4  # poi, events, dining are pending; stay is running
        assert "stay" in pending
        assert "poi" in pending
        assert "transport" not in pending

    def test_discovery_job_update_agent_progress(self) -> None:
        """Test update_agent_progress method."""
        job = DiscoveryJobModel(
            job_id="job_test",
            consultation_id="cons_test",
            workflow_version=1,
        )

        # Update a new agent
        job.update_agent_progress(
            "transport",
            AgentJobStatus.RUNNING,
            message="Searching flights...",
        )

        assert "transport" in job.agent_progress
        assert job.agent_progress["transport"].status == AgentJobStatus.RUNNING
        assert job.agent_progress["transport"].message == "Searching flights..."
        assert job.agent_progress["transport"].started_at is not None
        assert job.agent_progress["transport"].completed_at is None

    def test_discovery_job_update_agent_progress_with_string(self) -> None:
        """Test update_agent_progress with string status."""
        job = DiscoveryJobModel(
            job_id="job_test",
            consultation_id="cons_test",
            workflow_version=1,
        )

        job.update_agent_progress("transport", "completed", result_summary="12 flights")

        assert job.agent_progress["transport"].status == AgentJobStatus.COMPLETED
        assert job.agent_progress["transport"].result_summary == "12 flights"

    def test_discovery_job_update_sets_completed_at(self) -> None:
        """Test that completing an agent sets completed_at."""
        job = DiscoveryJobModel.create(
            job_id="job_test",
            consultation_id="cons_test",
            workflow_version=1,
        )

        job.update_agent_progress("transport", AgentJobStatus.RUNNING)
        assert job.agent_progress["transport"].started_at is not None
        assert job.agent_progress["transport"].completed_at is None

        job.update_agent_progress("transport", AgentJobStatus.COMPLETED)
        assert job.agent_progress["transport"].completed_at is not None

    def test_discovery_job_serialization(self) -> None:
        """Test DiscoveryJobModel serialization."""
        job = DiscoveryJobModel.create(
            job_id="job_serialize",
            consultation_id="cons_serialize",
            workflow_version=3,
        )
        job.status = DiscoveryJobStatus.RUNNING
        job.pipeline_stage = "discovery"
        job.update_agent_progress("transport", AgentJobStatus.COMPLETED, message="Found 12 flights")

        data = job.to_dict()

        assert data["id"] == "job_serialize"
        assert data["job_id"] == "job_serialize"
        assert data["consultation_id"] == "cons_serialize"
        assert data["workflow_version"] == 3
        assert data["status"] == "running"
        assert data["pipeline_stage"] == "discovery"
        assert "started_at" in data
        assert data["completed_at"] is None
        assert "agent_progress" in data
        assert "transport" in data["agent_progress"]
        assert data["agent_progress"]["transport"]["status"] == "completed"

    def test_discovery_job_deserialization(self) -> None:
        """Test DiscoveryJobModel deserialization."""
        now = datetime.now(timezone.utc)
        data = {
            "id": "job_deserialize",
            "job_id": "job_deserialize",
            "consultation_id": "cons_deserialize",
            "workflow_version": 2,
            "status": "partial",
            "started_at": now.isoformat(),
            "completed_at": now.isoformat(),
            "pipeline_stage": "validator",
            "agent_progress": {
                "transport": {"agent": "transport", "status": "completed"},
                "stay": {"agent": "stay", "status": "failed"},
            },
            "discovery_results": {"flights": []},
            "itinerary_draft": {"days": []},
            "error": None,
        }

        job = DiscoveryJobModel.from_dict(data)

        assert job.job_id == "job_deserialize"
        assert job.consultation_id == "cons_deserialize"
        assert job.workflow_version == 2
        assert job.status == DiscoveryJobStatus.PARTIAL
        assert job.started_at == now
        assert job.completed_at == now
        assert job.pipeline_stage == "validator"
        assert len(job.agent_progress) == 2
        assert job.agent_progress["transport"].status == AgentJobStatus.COMPLETED
        assert job.agent_progress["stay"].status == AgentJobStatus.FAILED
        assert job.discovery_results == {"flights": []}
        assert job.itinerary_draft == {"days": []}

    def test_discovery_job_roundtrip_serialization(self) -> None:
        """Test serialization/deserialization roundtrip."""
        original = DiscoveryJobModel.create(
            job_id="job_roundtrip",
            consultation_id="cons_roundtrip",
            workflow_version=5,
        )
        original.status = DiscoveryJobStatus.COMPLETED
        original.pipeline_stage = "validator"
        original.discovery_results = {"flights": [{"id": 1}], "hotels": [{"id": 2}]}
        original.update_agent_progress("transport", AgentJobStatus.COMPLETED, message="Done")

        data = original.to_dict()
        restored = DiscoveryJobModel.from_dict(data)

        assert restored.job_id == original.job_id
        assert restored.consultation_id == original.consultation_id
        assert restored.workflow_version == original.workflow_version
        assert restored.status == original.status
        assert restored.pipeline_stage == original.pipeline_stage
        assert restored.discovery_results == original.discovery_results
        assert len(restored.agent_progress) == len(original.agent_progress)

    def test_discovery_job_deserialization_defaults(self) -> None:
        """Test deserialization with minimal fields."""
        data = {"id": "job_minimal"}
        job = DiscoveryJobModel.from_dict(data)

        assert job.job_id == "job_minimal"
        assert job.consultation_id == ""
        assert job.workflow_version == 1
        assert job.status == DiscoveryJobStatus.PENDING
        assert job.started_at is not None  # Default is generated
        assert job.agent_progress == {}

    def test_discovery_job_deserialization_invalid_status(self) -> None:
        """Test deserialization with invalid status defaults to PENDING."""
        data = {"job_id": "job_invalid", "status": "not_a_real_status"}
        job = DiscoveryJobModel.from_dict(data)
        assert job.status == DiscoveryJobStatus.PENDING


class TestDiscoveryAgents:
    """Tests for DISCOVERY_AGENTS constant."""

    def test_discovery_agents_contains_expected(self) -> None:
        """Test that DISCOVERY_AGENTS contains expected agents."""
        assert "transport" in DISCOVERY_AGENTS
        assert "stay" in DISCOVERY_AGENTS
        assert "poi" in DISCOVERY_AGENTS
        assert "events" in DISCOVERY_AGENTS
        assert "dining" in DISCOVERY_AGENTS

    def test_discovery_agents_count(self) -> None:
        """Test DISCOVERY_AGENTS has expected count."""
        assert len(DISCOVERY_AGENTS) == 5
