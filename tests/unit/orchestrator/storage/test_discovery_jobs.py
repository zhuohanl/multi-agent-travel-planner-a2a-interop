"""
Unit tests for discovery_jobs storage module.

Tests the DiscoveryJob dataclass, AgentProgress, JobStatus enum,
DiscoveryJobStore (Cosmos DB), and InMemoryDiscoveryJobStore.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator.storage.discovery_jobs import (
    DISCOVERY_JOBS_TTL,
    AgentProgress,
    DiscoveryJob,
    DiscoveryJobStore,
    InMemoryDiscoveryJobStore,
    JobStatus,
)


class TestJobStatus:
    """Tests for JobStatus enum."""

    def test_job_status_values(self) -> None:
        """Test that all status values are correct."""
        assert JobStatus.PENDING.value == "pending"
        assert JobStatus.RUNNING.value == "running"
        assert JobStatus.COMPLETED.value == "completed"
        assert JobStatus.FAILED.value == "failed"
        assert JobStatus.PARTIAL.value == "partial"
        assert JobStatus.CANCELLED.value == "cancelled"

    def test_job_status_from_string(self) -> None:
        """Test creating JobStatus from string."""
        assert JobStatus("pending") == JobStatus.PENDING
        assert JobStatus("running") == JobStatus.RUNNING
        assert JobStatus("completed") == JobStatus.COMPLETED

    def test_job_status_is_string_enum(self) -> None:
        """Test that JobStatus is a string enum."""
        assert isinstance(JobStatus.PENDING, str)
        assert JobStatus.PENDING == "pending"


class TestAgentProgress:
    """Tests for AgentProgress dataclass."""

    def test_agent_progress_defaults(self) -> None:
        """Test AgentProgress default values."""
        progress = AgentProgress(agent="transport")
        assert progress.agent == "transport"
        assert progress.status == "pending"
        assert progress.started_at is None
        assert progress.completed_at is None
        assert progress.message is None
        assert progress.result_summary is None

    def test_agent_progress_with_all_fields(self) -> None:
        """Test AgentProgress with all fields set."""
        now = datetime.now(timezone.utc)
        progress = AgentProgress(
            agent="stay",
            status="completed",
            started_at=now,
            completed_at=now,
            message="Found 12 hotels",
            result_summary="Park Hyatt, Four Seasons, ...",
        )
        assert progress.agent == "stay"
        assert progress.status == "completed"
        assert progress.started_at == now
        assert progress.completed_at == now
        assert progress.message == "Found 12 hotels"
        assert progress.result_summary == "Park Hyatt, Four Seasons, ..."

    def test_agent_progress_to_dict(self) -> None:
        """Test AgentProgress serialization."""
        now = datetime.now(timezone.utc)
        progress = AgentProgress(
            agent="poi",
            status="running",
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
        """Test AgentProgress deserialization."""
        now = datetime.now(timezone.utc)
        data = {
            "agent": "dining",
            "status": "completed",
            "started_at": now.isoformat(),
            "completed_at": now.isoformat(),
            "message": "Found 15 restaurants",
            "result_summary": "Top picks found",
        }
        progress = AgentProgress.from_dict(data)

        assert progress.agent == "dining"
        assert progress.status == "completed"
        assert progress.started_at == now
        assert progress.completed_at == now
        assert progress.message == "Found 15 restaurants"
        assert progress.result_summary == "Top picks found"

    def test_agent_progress_from_dict_missing_fields(self) -> None:
        """Test AgentProgress deserialization with missing fields."""
        data = {"agent": "events"}
        progress = AgentProgress.from_dict(data)

        assert progress.agent == "events"
        assert progress.status == "pending"
        assert progress.started_at is None
        assert progress.completed_at is None

    def test_agent_progress_round_trip(self) -> None:
        """Test AgentProgress serialization round-trip."""
        now = datetime.now(timezone.utc)
        original = AgentProgress(
            agent="transport",
            status="timeout",
            started_at=now,
            message="Request timed out",
        )
        data = original.to_dict()
        restored = AgentProgress.from_dict(data)

        assert restored.agent == original.agent
        assert restored.status == original.status
        assert restored.started_at == original.started_at
        assert restored.message == original.message


class TestDiscoveryJob:
    """Tests for DiscoveryJob dataclass."""

    def test_discovery_job_defaults(self) -> None:
        """Test DiscoveryJob default values."""
        job = DiscoveryJob(
            job_id="job_abc123",
            consultation_id="cons_xyz789",
            workflow_version=1,
        )
        assert job.job_id == "job_abc123"
        assert job.consultation_id == "cons_xyz789"
        assert job.workflow_version == 1
        assert job.status == JobStatus.PENDING
        assert job.started_at is not None
        assert job.completed_at is None
        assert job.cancelled_at is None
        assert job.agent_progress == {}
        assert job.pipeline_stage is None
        assert job.discovery_results is None
        assert job.itinerary_draft is None
        assert job.error is None

    def test_discovery_job_to_dict(self) -> None:
        """Test DiscoveryJob serialization."""
        now = datetime.now(timezone.utc)
        job = DiscoveryJob(
            job_id="job_test123",
            consultation_id="cons_test456",
            workflow_version=2,
            status=JobStatus.RUNNING,
            started_at=now,
            pipeline_stage="discovery",
            agent_progress={
                "transport": AgentProgress(agent="transport", status="running"),
            },
        )
        data = job.to_dict()

        assert data["id"] == "job_test123"  # Cosmos document ID
        assert data["job_id"] == "job_test123"
        assert data["consultation_id"] == "cons_test456"
        assert data["workflow_version"] == 2
        assert data["status"] == "running"
        assert data["started_at"] == now.isoformat()
        assert data["completed_at"] is None
        assert data["pipeline_stage"] == "discovery"
        assert "transport" in data["agent_progress"]
        assert data["ttl"] == DISCOVERY_JOBS_TTL

    def test_discovery_job_from_dict(self) -> None:
        """Test DiscoveryJob deserialization."""
        now = datetime.now(timezone.utc)
        data = {
            "id": "job_from_dict",
            "job_id": "job_from_dict",
            "consultation_id": "cons_from_dict",
            "workflow_version": 3,
            "status": "completed",
            "started_at": now.isoformat(),
            "completed_at": now.isoformat(),
            "agent_progress": {
                "stay": {"agent": "stay", "status": "completed"},
            },
            "discovery_results": {"stay": {"hotels": []}},
            "itinerary_draft": {"days": []},
        }
        job = DiscoveryJob.from_dict(data)

        assert job.job_id == "job_from_dict"
        assert job.consultation_id == "cons_from_dict"
        assert job.workflow_version == 3
        assert job.status == JobStatus.COMPLETED
        assert job.started_at == now
        assert job.completed_at == now
        assert "stay" in job.agent_progress
        assert job.agent_progress["stay"].status == "completed"
        assert job.discovery_results == {"stay": {"hotels": []}}
        assert job.itinerary_draft == {"days": []}

    def test_discovery_job_from_dict_missing_fields(self) -> None:
        """Test DiscoveryJob deserialization with missing fields."""
        data = {"job_id": "job_minimal"}
        job = DiscoveryJob.from_dict(data)

        assert job.job_id == "job_minimal"
        assert job.consultation_id == ""
        assert job.workflow_version == 1
        assert job.status == JobStatus.PENDING

    def test_discovery_job_from_dict_invalid_status(self) -> None:
        """Test DiscoveryJob deserialization with invalid status."""
        data = {"job_id": "job_bad_status", "status": "invalid_status"}
        job = DiscoveryJob.from_dict(data)

        # Should default to PENDING for invalid status
        assert job.status == JobStatus.PENDING

    def test_discovery_job_is_terminal(self) -> None:
        """Test is_terminal method."""
        job = DiscoveryJob(job_id="job_1", consultation_id="cons_1", workflow_version=1)

        job.status = JobStatus.PENDING
        assert job.is_terminal() is False

        job.status = JobStatus.RUNNING
        assert job.is_terminal() is False

        job.status = JobStatus.COMPLETED
        assert job.is_terminal() is True

        job.status = JobStatus.FAILED
        assert job.is_terminal() is True

        job.status = JobStatus.PARTIAL
        assert job.is_terminal() is True

        job.status = JobStatus.CANCELLED
        assert job.is_terminal() is True

    def test_discovery_job_update_agent_progress(self) -> None:
        """Test update_agent_progress method."""
        job = DiscoveryJob(job_id="job_1", consultation_id="cons_1", workflow_version=1)

        # Update new agent
        job.update_agent_progress("transport", "running", message="Searching...")
        assert "transport" in job.agent_progress
        assert job.agent_progress["transport"].status == "running"
        assert job.agent_progress["transport"].message == "Searching..."
        assert job.agent_progress["transport"].started_at is not None

        # Update same agent to completed
        job.update_agent_progress(
            "transport", "completed", message="Found flights", result_summary="12 options"
        )
        assert job.agent_progress["transport"].status == "completed"
        assert job.agent_progress["transport"].completed_at is not None
        assert job.agent_progress["transport"].result_summary == "12 options"

    def test_discovery_job_round_trip(self) -> None:
        """Test DiscoveryJob serialization round-trip."""
        original = DiscoveryJob(
            job_id="job_round_trip",
            consultation_id="cons_round_trip",
            workflow_version=5,
            status=JobStatus.PARTIAL,
        )
        original.update_agent_progress("stay", "completed", message="Done")
        original.update_agent_progress("transport", "failed", message="Error")

        data = original.to_dict()
        restored = DiscoveryJob.from_dict(data)

        assert restored.job_id == original.job_id
        assert restored.consultation_id == original.consultation_id
        assert restored.workflow_version == original.workflow_version
        assert restored.status == original.status
        assert len(restored.agent_progress) == 2
        assert restored.agent_progress["stay"].status == "completed"
        assert restored.agent_progress["transport"].status == "failed"


class TestDiscoveryJobStore:
    """Tests for DiscoveryJobStore (Cosmos DB implementation)."""

    @pytest.fixture
    def mock_container(self) -> MagicMock:
        """Create a mock Cosmos container."""
        return MagicMock()

    @pytest.fixture
    def store(self, mock_container: MagicMock) -> DiscoveryJobStore:
        """Create a DiscoveryJobStore with mock container."""
        return DiscoveryJobStore(mock_container)

    @pytest.mark.asyncio
    async def test_get_job_found(self, store: DiscoveryJobStore, mock_container: MagicMock) -> None:
        """Test retrieving an existing job."""
        now = datetime.now(timezone.utc)
        mock_container.read_item = AsyncMock(
            return_value={
                "id": "job_found",
                "job_id": "job_found",
                "consultation_id": "cons_found",
                "workflow_version": 1,
                "status": "running",
                "started_at": now.isoformat(),
            }
        )

        job = await store.get_job("job_found", "cons_found")

        assert job is not None
        assert job.job_id == "job_found"
        assert job.consultation_id == "cons_found"
        assert job.status == JobStatus.RUNNING
        mock_container.read_item.assert_called_once_with(
            item="job_found",
            partition_key="cons_found",
        )

    @pytest.mark.asyncio
    async def test_get_job_not_found(self, store: DiscoveryJobStore, mock_container: MagicMock) -> None:
        """Test retrieving a non-existent job."""
        error = Exception("Not found")
        error.status_code = 404  # type: ignore[attr-defined]
        mock_container.read_item = AsyncMock(side_effect=error)

        job = await store.get_job("job_missing", "cons_missing")

        assert job is None

    @pytest.mark.asyncio
    async def test_get_job_other_error(self, store: DiscoveryJobStore, mock_container: MagicMock) -> None:
        """Test get_job with unexpected error."""
        error = Exception("Server error")
        error.status_code = 500  # type: ignore[attr-defined]
        mock_container.read_item = AsyncMock(side_effect=error)

        with pytest.raises(Exception) as exc_info:
            await store.get_job("job_error", "cons_error")

        assert "Server error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_save_job_creates(self, store: DiscoveryJobStore, mock_container: MagicMock) -> None:
        """Test saving a new job."""
        job = DiscoveryJob(
            job_id="job_new",
            consultation_id="cons_new",
            workflow_version=1,
            status=JobStatus.PENDING,
        )
        mock_container.upsert_item = AsyncMock(return_value=job.to_dict())

        saved = await store.save_job(job)

        assert saved.job_id == "job_new"
        mock_container.upsert_item.assert_called_once()
        call_args = mock_container.upsert_item.call_args
        body = call_args.kwargs["body"]
        assert body["id"] == "job_new"
        assert body["ttl"] == DISCOVERY_JOBS_TTL

    @pytest.mark.asyncio
    async def test_update_job_status(self, store: DiscoveryJobStore, mock_container: MagicMock) -> None:
        """Test updating job status."""
        now = datetime.now(timezone.utc)
        mock_container.read_item = AsyncMock(
            return_value={
                "id": "job_update",
                "job_id": "job_update",
                "consultation_id": "cons_update",
                "workflow_version": 1,
                "status": "running",
                "started_at": now.isoformat(),
            }
        )
        mock_container.upsert_item = AsyncMock(
            return_value={
                "id": "job_update",
                "job_id": "job_update",
                "consultation_id": "cons_update",
                "workflow_version": 1,
                "status": "completed",
                "started_at": now.isoformat(),
                "completed_at": now.isoformat(),
            }
        )

        updated = await store.update_job_status("job_update", "cons_update", JobStatus.COMPLETED)

        assert updated is not None
        assert updated.status == JobStatus.COMPLETED
        # completed_at should be set by update_job_status

    @pytest.mark.asyncio
    async def test_update_job_status_not_found(
        self, store: DiscoveryJobStore, mock_container: MagicMock
    ) -> None:
        """Test updating status of non-existent job."""
        error = Exception("Not found")
        error.status_code = 404  # type: ignore[attr-defined]
        mock_container.read_item = AsyncMock(side_effect=error)

        result = await store.update_job_status("job_missing", "cons_missing", JobStatus.COMPLETED)

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_job_found(self, store: DiscoveryJobStore, mock_container: MagicMock) -> None:
        """Test deleting an existing job."""
        mock_container.delete_item = AsyncMock()

        result = await store.delete_job("job_del", "cons_del")

        assert result is True
        mock_container.delete_item.assert_called_once_with(
            item="job_del",
            partition_key="cons_del",
        )

    @pytest.mark.asyncio
    async def test_delete_job_not_found(
        self, store: DiscoveryJobStore, mock_container: MagicMock
    ) -> None:
        """Test deleting a non-existent job."""
        error = Exception("Not found")
        error.status_code = 404  # type: ignore[attr-defined]
        mock_container.delete_item = AsyncMock(side_effect=error)

        result = await store.delete_job("job_missing", "cons_missing")

        assert result is False


class TestInMemoryDiscoveryJobStore:
    """Tests for InMemoryDiscoveryJobStore."""

    @pytest.fixture
    def store(self) -> InMemoryDiscoveryJobStore:
        """Create an InMemoryDiscoveryJobStore."""
        return InMemoryDiscoveryJobStore()

    @pytest.mark.asyncio
    async def test_save_and_get_job(self, store: InMemoryDiscoveryJobStore) -> None:
        """Test saving and retrieving a job."""
        job = DiscoveryJob(
            job_id="job_mem_1",
            consultation_id="cons_mem_1",
            workflow_version=1,
        )
        await store.save_job(job)

        retrieved = await store.get_job("job_mem_1", "cons_mem_1")

        assert retrieved is not None
        assert retrieved.job_id == "job_mem_1"
        assert retrieved.consultation_id == "cons_mem_1"

    @pytest.mark.asyncio
    async def test_get_job_not_found(self, store: InMemoryDiscoveryJobStore) -> None:
        """Test retrieving a non-existent job."""
        job = await store.get_job("job_missing", "cons_missing")
        assert job is None

    @pytest.mark.asyncio
    async def test_get_job_wrong_consultation(self, store: InMemoryDiscoveryJobStore) -> None:
        """Test retrieving a job with wrong consultation_id."""
        job = DiscoveryJob(
            job_id="job_1",
            consultation_id="cons_1",
            workflow_version=1,
        )
        await store.save_job(job)

        # Should not find job with different consultation_id
        retrieved = await store.get_job("job_1", "cons_wrong")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_update_job(self, store: InMemoryDiscoveryJobStore) -> None:
        """Test updating an existing job."""
        job = DiscoveryJob(
            job_id="job_update",
            consultation_id="cons_update",
            workflow_version=1,
            status=JobStatus.PENDING,
        )
        await store.save_job(job)

        job.status = JobStatus.RUNNING
        job.pipeline_stage = "discovery"
        await store.save_job(job)

        retrieved = await store.get_job("job_update", "cons_update")
        assert retrieved is not None
        assert retrieved.status == JobStatus.RUNNING
        assert retrieved.pipeline_stage == "discovery"

    @pytest.mark.asyncio
    async def test_update_job_status(self, store: InMemoryDiscoveryJobStore) -> None:
        """Test update_job_status helper."""
        job = DiscoveryJob(
            job_id="job_status",
            consultation_id="cons_status",
            workflow_version=1,
            status=JobStatus.RUNNING,
        )
        await store.save_job(job)

        updated = await store.update_job_status("job_status", "cons_status", JobStatus.COMPLETED)

        assert updated is not None
        assert updated.status == JobStatus.COMPLETED
        assert updated.completed_at is not None

    @pytest.mark.asyncio
    async def test_update_job_status_cancelled(self, store: InMemoryDiscoveryJobStore) -> None:
        """Test update_job_status with CANCELLED status."""
        job = DiscoveryJob(
            job_id="job_cancel",
            consultation_id="cons_cancel",
            workflow_version=1,
            status=JobStatus.RUNNING,
        )
        await store.save_job(job)

        updated = await store.update_job_status("job_cancel", "cons_cancel", JobStatus.CANCELLED)

        assert updated is not None
        assert updated.status == JobStatus.CANCELLED
        assert updated.cancelled_at is not None

    @pytest.mark.asyncio
    async def test_update_job_status_not_found(self, store: InMemoryDiscoveryJobStore) -> None:
        """Test update_job_status for non-existent job."""
        result = await store.update_job_status("job_missing", "cons_missing", JobStatus.COMPLETED)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_job(self, store: InMemoryDiscoveryJobStore) -> None:
        """Test deleting a job."""
        job = DiscoveryJob(
            job_id="job_del",
            consultation_id="cons_del",
            workflow_version=1,
        )
        await store.save_job(job)

        result = await store.delete_job("job_del", "cons_del")
        assert result is True

        retrieved = await store.get_job("job_del", "cons_del")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_job_not_found(self, store: InMemoryDiscoveryJobStore) -> None:
        """Test deleting a non-existent job."""
        result = await store.delete_job("job_missing", "cons_missing")
        assert result is False

    @pytest.mark.asyncio
    async def test_clear(self, store: InMemoryDiscoveryJobStore) -> None:
        """Test clearing all jobs."""
        job1 = DiscoveryJob(job_id="job_1", consultation_id="cons_1", workflow_version=1)
        job2 = DiscoveryJob(job_id="job_2", consultation_id="cons_2", workflow_version=1)
        await store.save_job(job1)
        await store.save_job(job2)

        assert store.get_job_count() == 2

        store.clear()

        assert store.get_job_count() == 0

    @pytest.mark.asyncio
    async def test_get_job_count(self, store: InMemoryDiscoveryJobStore) -> None:
        """Test get_job_count helper."""
        assert store.get_job_count() == 0

        job1 = DiscoveryJob(job_id="job_1", consultation_id="cons_1", workflow_version=1)
        await store.save_job(job1)
        assert store.get_job_count() == 1

        job2 = DiscoveryJob(job_id="job_2", consultation_id="cons_1", workflow_version=1)
        await store.save_job(job2)
        assert store.get_job_count() == 2

    @pytest.mark.asyncio
    async def test_get_jobs_for_consultation(self, store: InMemoryDiscoveryJobStore) -> None:
        """Test get_jobs_for_consultation helper."""
        job1 = DiscoveryJob(job_id="job_1", consultation_id="cons_a", workflow_version=1)
        job2 = DiscoveryJob(job_id="job_2", consultation_id="cons_a", workflow_version=1)
        job3 = DiscoveryJob(job_id="job_3", consultation_id="cons_b", workflow_version=1)
        await store.save_job(job1)
        await store.save_job(job2)
        await store.save_job(job3)

        cons_a_jobs = store.get_jobs_for_consultation("cons_a")
        assert len(cons_a_jobs) == 2

        cons_b_jobs = store.get_jobs_for_consultation("cons_b")
        assert len(cons_b_jobs) == 1

        cons_c_jobs = store.get_jobs_for_consultation("cons_c")
        assert len(cons_c_jobs) == 0

    @pytest.mark.asyncio
    async def test_multiple_consultations(self, store: InMemoryDiscoveryJobStore) -> None:
        """Test storing jobs for multiple consultations."""
        job1 = DiscoveryJob(job_id="job_1", consultation_id="cons_1", workflow_version=1)
        job2 = DiscoveryJob(job_id="job_2", consultation_id="cons_2", workflow_version=1)
        await store.save_job(job1)
        await store.save_job(job2)

        retrieved1 = await store.get_job("job_1", "cons_1")
        retrieved2 = await store.get_job("job_2", "cons_2")

        assert retrieved1 is not None
        assert retrieved2 is not None
        assert retrieved1.consultation_id == "cons_1"
        assert retrieved2.consultation_id == "cons_2"


class TestDiscoveryJobsTTL:
    """Tests for discovery_jobs TTL constant."""

    def test_discovery_jobs_ttl_is_24_hours(self) -> None:
        """Test that TTL is 24 hours (86400 seconds)."""
        assert DISCOVERY_JOBS_TTL == 86400
        assert DISCOVERY_JOBS_TTL == 24 * 60 * 60

    def test_ttl_included_in_to_dict(self) -> None:
        """Test that TTL is included in serialized job."""
        job = DiscoveryJob(
            job_id="job_ttl",
            consultation_id="cons_ttl",
            workflow_version=1,
        )
        data = job.to_dict()

        assert "ttl" in data
        assert data["ttl"] == DISCOVERY_JOBS_TTL
