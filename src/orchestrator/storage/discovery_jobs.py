"""
Discovery jobs storage for Cosmos DB.

This module implements the DiscoveryJobStore which persists DiscoveryJob
documents to the `discovery_jobs` Cosmos DB container.

Key features:
- Partitioned by consultation_id for efficient lookups
- 24-hour TTL (jobs are ephemeral)
- Tracks job status, progress, and results

Per design doc:
- Container: discovery_jobs
- Partition key: /consultation_id
- TTL: 86400 seconds (24 hours)
- Purpose: Track background discovery job progress
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

# Import azure.cosmos only at type-checking time or when needed at runtime
if TYPE_CHECKING:
    from azure.cosmos.aio import ContainerProxy

logger = logging.getLogger(__name__)

# TTL for discovery jobs: 24 hours in seconds
DISCOVERY_JOBS_TTL = 24 * 60 * 60  # 86400 seconds


class JobStatus(str, Enum):
    """Status of a discovery job."""

    PENDING = "pending"  # Job created, not yet started
    RUNNING = "running"  # Job is in progress
    COMPLETED = "completed"  # Job finished successfully
    FAILED = "failed"  # Job failed completely
    PARTIAL = "partial"  # Some agents succeeded, some failed/timed out
    CANCELLED = "cancelled"  # User cancelled workflow while job was running


@dataclass
class AgentProgress:
    """Progress tracking for an individual discovery agent."""

    agent: str
    status: Literal["pending", "running", "completed", "failed", "timeout"] = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    message: str | None = None  # "Found 12 flights", "Searching..."
    result_summary: str | None = None  # Brief summary for progress display

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for Cosmos DB storage."""
        return {
            "agent": self.agent,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "message": self.message,
            "result_summary": self.result_summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentProgress:
        """Create from dictionary retrieved from Cosmos DB."""
        started_at = data.get("started_at")
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)

        completed_at = data.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at)

        return cls(
            agent=data.get("agent", ""),
            status=data.get("status", "pending"),
            started_at=started_at,
            completed_at=completed_at,
            message=data.get("message"),
            result_summary=data.get("result_summary"),
        )


@dataclass
class DiscoveryJob:
    """
    Background job for discovery + planning pipeline.

    Stored in the discovery_jobs container, partitioned by consultation_id.
    Used to track progress during long-running discovery operations.
    """

    job_id: str  # "job_abc123"
    consultation_id: str  # Links to workflow (partition key)
    workflow_version: int  # Must match state.workflow_version at finalize time
    status: JobStatus = JobStatus.PENDING
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None  # Set when user cancels workflow

    # Per-agent progress tracking
    agent_progress: dict[str, AgentProgress] = field(default_factory=dict)

    # Pipeline progress (stages after discovery agents)
    pipeline_stage: str | None = None  # "discovery", "aggregator", "budget", "route", "validator"

    # Results (persisted even if client disconnects)
    # Note: These are stored as dicts for simplicity; full typed models in later tickets
    discovery_results: dict[str, Any] | None = None
    itinerary_draft: dict[str, Any] | None = None  # Draft plan (NOT approved yet)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for Cosmos DB storage."""
        agent_progress_dict = {
            agent: progress.to_dict() for agent, progress in self.agent_progress.items()
        }

        return {
            "id": self.job_id,  # Cosmos DB document ID
            "job_id": self.job_id,
            "consultation_id": self.consultation_id,  # Partition key
            "workflow_version": self.workflow_version,
            "status": self.status.value if isinstance(self.status, JobStatus) else self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "agent_progress": agent_progress_dict,
            "pipeline_stage": self.pipeline_stage,
            "discovery_results": self.discovery_results,
            "itinerary_draft": self.itinerary_draft,
            "error": self.error,
            "ttl": DISCOVERY_JOBS_TTL,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiscoveryJob:
        """Create from dictionary retrieved from Cosmos DB."""
        started_at = data.get("started_at")
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)
        elif started_at is None:
            started_at = datetime.now(timezone.utc)

        completed_at = data.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at)

        cancelled_at = data.get("cancelled_at")
        if isinstance(cancelled_at, str):
            cancelled_at = datetime.fromisoformat(cancelled_at)

        # Parse status
        status_str = data.get("status", "pending")
        try:
            status = JobStatus(status_str)
        except ValueError:
            status = JobStatus.PENDING

        # Parse agent progress
        agent_progress_data = data.get("agent_progress", {})
        agent_progress = {
            agent: AgentProgress.from_dict(progress)
            for agent, progress in agent_progress_data.items()
        }

        return cls(
            job_id=data.get("job_id", data.get("id", "")),
            consultation_id=data.get("consultation_id", ""),
            workflow_version=data.get("workflow_version", 1),
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            cancelled_at=cancelled_at,
            agent_progress=agent_progress,
            pipeline_stage=data.get("pipeline_stage"),
            discovery_results=data.get("discovery_results"),
            itinerary_draft=data.get("itinerary_draft"),
            error=data.get("error"),
        )

    def is_terminal(self) -> bool:
        """Check if job is in a terminal state."""
        return self.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.PARTIAL, JobStatus.CANCELLED)

    def update_agent_progress(
        self,
        agent: str,
        status: Literal["pending", "running", "completed", "failed", "timeout"],
        message: str | None = None,
        result_summary: str | None = None,
    ) -> None:
        """Update progress for a specific agent."""
        if agent not in self.agent_progress:
            self.agent_progress[agent] = AgentProgress(agent=agent)

        progress = self.agent_progress[agent]
        progress.status = status

        now = datetime.now(timezone.utc)
        if status == "running" and progress.started_at is None:
            progress.started_at = now
        if status in ("completed", "failed", "timeout"):
            progress.completed_at = now

        if message is not None:
            progress.message = message
        if result_summary is not None:
            progress.result_summary = result_summary


@runtime_checkable
class DiscoveryJobStoreProtocol(Protocol):
    """
    Protocol defining the interface for discovery job storage.

    This protocol allows swapping between Cosmos DB and in-memory
    implementations for production vs testing.
    """

    async def get_job(self, job_id: str, consultation_id: str) -> DiscoveryJob | None:
        """
        Retrieve discovery job by job_id.

        Args:
            job_id: The job identifier (document ID)
            consultation_id: The consultation identifier (partition key)

        Returns:
            DiscoveryJob if found, None if not found
        """
        ...

    async def save_job(self, job: DiscoveryJob) -> DiscoveryJob:
        """
        Save discovery job (create or update).

        Args:
            job: The discovery job to save

        Returns:
            The saved job
        """
        ...

    async def update_job_status(
        self, job_id: str, consultation_id: str, status: JobStatus
    ) -> DiscoveryJob | None:
        """
        Update job status.

        Args:
            job_id: The job identifier
            consultation_id: The consultation identifier (partition key)
            status: The new status

        Returns:
            The updated job, or None if not found
        """
        ...

    async def delete_job(self, job_id: str, consultation_id: str) -> bool:
        """
        Delete a discovery job.

        Args:
            job_id: The job identifier
            consultation_id: The consultation identifier (partition key)

        Returns:
            True if deleted, False if not found
        """
        ...


class DiscoveryJobStore:
    """
    Cosmos DB implementation of discovery job storage.

    Uses the discovery_jobs container partitioned by consultation_id.
    Jobs have a 24-hour TTL and are used for ephemeral progress tracking.
    """

    def __init__(self, container: ContainerProxy) -> None:
        """
        Initialize the store with a Cosmos container client.

        Args:
            container: Async Cosmos container client for discovery_jobs
        """
        self._container = container

    async def get_job(self, job_id: str, consultation_id: str) -> DiscoveryJob | None:
        """
        Retrieve discovery job by job_id.

        Args:
            job_id: The job identifier (document ID)
            consultation_id: The consultation identifier (partition key)

        Returns:
            DiscoveryJob if found, None if not found
        """
        try:
            response = await self._container.read_item(
                item=job_id,
                partition_key=consultation_id,
            )
            logger.debug(f"Retrieved discovery job {job_id} for consultation {consultation_id}")
            return DiscoveryJob.from_dict(response)
        except Exception as e:
            # Handle CosmosResourceNotFoundError
            error_code = getattr(e, "status_code", None)
            if error_code == 404:
                logger.debug(f"Discovery job not found: {job_id} in consultation {consultation_id}")
                return None
            # Re-raise other errors
            logger.error(f"Error retrieving discovery job: {e}")
            raise

    async def save_job(self, job: DiscoveryJob) -> DiscoveryJob:
        """
        Save discovery job (create or update).

        Uses upsert for create/update semantics.

        Args:
            job: The discovery job to save

        Returns:
            The saved job
        """
        doc = job.to_dict()

        try:
            response = await self._container.upsert_item(body=doc)
            logger.debug(
                f"Upserted discovery job {job.job_id} for consultation {job.consultation_id}"
            )
            return DiscoveryJob.from_dict(response)
        except Exception as e:
            logger.error(f"Error saving discovery job: {e}")
            raise

    async def update_job_status(
        self, job_id: str, consultation_id: str, status: JobStatus
    ) -> DiscoveryJob | None:
        """
        Update job status.

        Args:
            job_id: The job identifier
            consultation_id: The consultation identifier (partition key)
            status: The new status

        Returns:
            The updated job, or None if not found
        """
        job = await self.get_job(job_id, consultation_id)
        if job is None:
            return None

        job.status = status

        # Set completion/cancellation timestamps
        now = datetime.now(timezone.utc)
        if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.PARTIAL):
            job.completed_at = now
        elif status == JobStatus.CANCELLED:
            job.cancelled_at = now

        return await self.save_job(job)

    async def delete_job(self, job_id: str, consultation_id: str) -> bool:
        """
        Delete a discovery job.

        Args:
            job_id: The job identifier
            consultation_id: The consultation identifier (partition key)

        Returns:
            True if deleted, False if not found
        """
        try:
            await self._container.delete_item(
                item=job_id,
                partition_key=consultation_id,
            )
            logger.debug(f"Deleted discovery job {job_id}")
            return True
        except Exception as e:
            error_code = getattr(e, "status_code", None)
            if error_code == 404:
                logger.debug(f"Discovery job not found for deletion: {job_id}")
                return False
            logger.error(f"Error deleting discovery job: {e}")
            raise


class InMemoryDiscoveryJobStore:
    """
    In-memory implementation of discovery job storage for testing.

    Implements the same interface as DiscoveryJobStore but stores
    data in memory. Useful for unit tests and local development.
    """

    def __init__(self) -> None:
        """Initialize empty in-memory store."""
        # Store jobs by consultation_id -> job_id -> job_data
        self._jobs: dict[str, dict[str, dict[str, Any]]] = {}

    async def get_job(self, job_id: str, consultation_id: str) -> DiscoveryJob | None:
        """Retrieve discovery job by job_id."""
        consultation_jobs = self._jobs.get(consultation_id, {})
        if job_id not in consultation_jobs:
            return None
        return DiscoveryJob.from_dict(consultation_jobs[job_id])

    async def save_job(self, job: DiscoveryJob) -> DiscoveryJob:
        """Save discovery job (create or update)."""
        if job.consultation_id not in self._jobs:
            self._jobs[job.consultation_id] = {}

        self._jobs[job.consultation_id][job.job_id] = job.to_dict()
        return job

    async def update_job_status(
        self, job_id: str, consultation_id: str, status: JobStatus
    ) -> DiscoveryJob | None:
        """Update job status."""
        job = await self.get_job(job_id, consultation_id)
        if job is None:
            return None

        job.status = status

        # Set completion/cancellation timestamps
        now = datetime.now(timezone.utc)
        if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.PARTIAL):
            job.completed_at = now
        elif status == JobStatus.CANCELLED:
            job.cancelled_at = now

        return await self.save_job(job)

    async def delete_job(self, job_id: str, consultation_id: str) -> bool:
        """Delete a discovery job."""
        consultation_jobs = self._jobs.get(consultation_id, {})
        if job_id in consultation_jobs:
            del consultation_jobs[job_id]
            return True
        return False

    def clear(self) -> None:
        """Clear all jobs (for test cleanup)."""
        self._jobs.clear()

    def get_job_count(self) -> int:
        """Get total number of jobs (for testing)."""
        return sum(len(jobs) for jobs in self._jobs.values())

    def get_jobs_for_consultation(self, consultation_id: str) -> list[DiscoveryJob]:
        """Get all jobs for a consultation (for testing)."""
        consultation_jobs = self._jobs.get(consultation_id, {})
        return [DiscoveryJob.from_dict(data) for data in consultation_jobs.values()]
