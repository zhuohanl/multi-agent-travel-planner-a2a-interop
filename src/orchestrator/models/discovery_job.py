"""
Discovery job models for tracking parallel discovery operations.

This module defines the DiscoveryJobModel which tracks the status of
parallel discovery operations. It enables progress reporting and
partial failure handling.

Key features:
- Per-agent status tracking via AgentJobStatus enum
- Completion percentage calculation
- Pipeline stage tracking for post-discovery planning steps
- Serialization/deserialization for Cosmos DB storage
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal


class AgentJobStatus(str, Enum):
    """
    Status of an individual discovery agent within a job.

    This enum tracks the lifecycle of each agent's discovery task.
    Used by AgentJobProgress to track per-agent status.
    """

    PENDING = "pending"  # Agent task created, not yet started
    RUNNING = "running"  # Agent task is in progress
    COMPLETED = "completed"  # Agent task finished successfully
    FAILED = "failed"  # Agent task failed with error
    TIMEOUT = "timeout"  # Agent task exceeded timeout limit


class DiscoveryJobStatus(str, Enum):
    """
    Overall status of a discovery job.

    A job can have multiple agents running in parallel.
    The job status reflects the aggregate state.
    """

    PENDING = "pending"  # Job created, not yet started
    RUNNING = "running"  # Job is in progress (at least one agent running)
    COMPLETED = "completed"  # Job finished successfully (all agents succeeded)
    FAILED = "failed"  # Job failed completely (all agents failed)
    PARTIAL = "partial"  # Some agents succeeded, some failed/timed out
    CANCELLED = "cancelled"  # User cancelled workflow while job was running


# Define discovery agents
DISCOVERY_AGENTS: tuple[str, ...] = ("transport", "stay", "poi", "events", "dining")


@dataclass
class AgentJobProgress:
    """
    Progress tracking for an individual discovery agent within a job.

    Tracks the lifecycle of each agent's discovery task including
    timing information and result summaries for UI display.
    """

    agent: str
    status: AgentJobStatus = AgentJobStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    message: str | None = None  # "Found 12 flights", "Searching..."
    result_summary: str | None = None  # Brief summary for progress display

    def is_terminal(self) -> bool:
        """Check if agent is in a terminal state."""
        return self.status in (
            AgentJobStatus.COMPLETED,
            AgentJobStatus.FAILED,
            AgentJobStatus.TIMEOUT,
        )

    def is_successful(self) -> bool:
        """Check if agent completed successfully."""
        return self.status == AgentJobStatus.COMPLETED

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for Cosmos DB storage."""
        return {
            "agent": self.agent,
            "status": self.status.value if isinstance(self.status, AgentJobStatus) else self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "message": self.message,
            "result_summary": self.result_summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentJobProgress:
        """Create from dictionary retrieved from Cosmos DB."""
        started_at = data.get("started_at")
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)

        completed_at = data.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at)

        # Parse status
        status_str = data.get("status", "pending")
        try:
            status = AgentJobStatus(status_str)
        except ValueError:
            status = AgentJobStatus.PENDING

        return cls(
            agent=data.get("agent", ""),
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            message=data.get("message"),
            result_summary=data.get("result_summary"),
        )


@dataclass
class DiscoveryJobModel:
    """
    Model for tracking background discovery + planning pipeline execution.

    A DiscoveryJob is created when the user approves their trip specification
    and discovery begins. It tracks:
    - Overall job status (pending, running, completed, failed, partial, cancelled)
    - Per-agent progress for parallel discovery agents
    - Pipeline stage for post-discovery planning steps
    - Discovery results and itinerary draft

    The job is ephemeral (24h TTL) - results are transferred to WorkflowState
    when the job completes via finalize_job().
    """

    job_id: str  # "job_abc123"
    consultation_id: str  # Links to workflow (partition key)
    workflow_version: int  # Must match state.workflow_version at finalize time
    status: DiscoveryJobStatus = DiscoveryJobStatus.PENDING
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None  # Set when user cancels workflow

    # Per-agent progress tracking
    agent_progress: dict[str, AgentJobProgress] = field(default_factory=dict)

    # Pipeline progress (stages after discovery agents)
    pipeline_stage: str | None = None  # "discovery", "aggregator", "budget", "route", "validator"

    # Results (persisted even if client disconnects)
    discovery_results: dict[str, Any] | None = None
    itinerary_draft: dict[str, Any] | None = None  # Draft plan (NOT approved yet)
    error: str | None = None

    def is_terminal(self) -> bool:
        """Check if job is in a terminal state."""
        return self.status in (
            DiscoveryJobStatus.COMPLETED,
            DiscoveryJobStatus.FAILED,
            DiscoveryJobStatus.PARTIAL,
            DiscoveryJobStatus.CANCELLED,
        )

    def is_successful(self) -> bool:
        """Check if job completed successfully."""
        return self.status == DiscoveryJobStatus.COMPLETED

    @property
    def completion_percentage(self) -> float:
        """
        Calculate the completion percentage of the discovery job.

        Returns a value between 0.0 and 100.0 representing the percentage
        of agents that have reached a terminal state (completed, failed, timeout).

        Returns 100.0 if there are no agents being tracked.
        """
        if not self.agent_progress:
            # No agents means we consider it complete (0/0 = 100%)
            return 100.0

        total_agents = len(self.agent_progress)
        terminal_agents = sum(
            1 for progress in self.agent_progress.values()
            if progress.is_terminal()
        )

        return (terminal_agents / total_agents) * 100.0

    @property
    def completed_agents(self) -> list[str]:
        """Get list of successfully completed agent names."""
        return [
            agent
            for agent, progress in self.agent_progress.items()
            if progress.is_successful()
        ]

    @property
    def failed_agents(self) -> list[str]:
        """Get list of failed or timed out agent names."""
        return [
            agent
            for agent, progress in self.agent_progress.items()
            if progress.status in (AgentJobStatus.FAILED, AgentJobStatus.TIMEOUT)
        ]

    @property
    def pending_agents(self) -> list[str]:
        """Get list of agents still pending or running."""
        return [
            agent
            for agent, progress in self.agent_progress.items()
            if progress.status in (AgentJobStatus.PENDING, AgentJobStatus.RUNNING)
        ]

    def update_agent_progress(
        self,
        agent: str,
        status: AgentJobStatus | Literal["pending", "running", "completed", "failed", "timeout"],
        message: str | None = None,
        result_summary: str | None = None,
    ) -> None:
        """
        Update progress for a specific agent.

        Automatically sets timestamps when status transitions to running or terminal.

        Args:
            agent: Name of the discovery agent
            status: New status (AgentJobStatus enum or string literal)
            message: Optional progress message for UI display
            result_summary: Optional brief summary of results
        """
        # Convert string to enum if needed
        if isinstance(status, str):
            status = AgentJobStatus(status)

        if agent not in self.agent_progress:
            self.agent_progress[agent] = AgentJobProgress(agent=agent)

        progress = self.agent_progress[agent]
        progress.status = status

        now = datetime.now(timezone.utc)
        if status == AgentJobStatus.RUNNING and progress.started_at is None:
            progress.started_at = now
        if status in (AgentJobStatus.COMPLETED, AgentJobStatus.FAILED, AgentJobStatus.TIMEOUT):
            progress.completed_at = now

        if message is not None:
            progress.message = message
        if result_summary is not None:
            progress.result_summary = result_summary

    def initialize_agents(self, agents: tuple[str, ...] | list[str] | None = None) -> None:
        """
        Initialize agent progress tracking for all discovery agents.

        Args:
            agents: Optional list of agent names. Defaults to DISCOVERY_AGENTS.
        """
        if agents is None:
            agents = DISCOVERY_AGENTS

        for agent in agents:
            if agent not in self.agent_progress:
                self.agent_progress[agent] = AgentJobProgress(agent=agent)

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
            "status": self.status.value if isinstance(self.status, DiscoveryJobStatus) else self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "agent_progress": agent_progress_dict,
            "pipeline_stage": self.pipeline_stage,
            "discovery_results": self.discovery_results,
            "itinerary_draft": self.itinerary_draft,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiscoveryJobModel:
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
            status = DiscoveryJobStatus(status_str)
        except ValueError:
            status = DiscoveryJobStatus.PENDING

        # Parse agent progress
        agent_progress_data = data.get("agent_progress", {})
        agent_progress = {
            agent: AgentJobProgress.from_dict(progress)
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

    @classmethod
    def create(
        cls,
        job_id: str,
        consultation_id: str,
        workflow_version: int,
        agents: tuple[str, ...] | list[str] | None = None,
    ) -> DiscoveryJobModel:
        """
        Factory method to create a new discovery job with initialized agents.

        Args:
            job_id: Unique job identifier (e.g., "job_abc123")
            consultation_id: Consultation ID for partition key
            workflow_version: Workflow version for finalize_job validation
            agents: Optional list of agents. Defaults to DISCOVERY_AGENTS.

        Returns:
            A new DiscoveryJobModel with agents initialized to PENDING status.
        """
        job = cls(
            job_id=job_id,
            consultation_id=consultation_id,
            workflow_version=workflow_version,
            status=DiscoveryJobStatus.PENDING,
        )
        job.initialize_agents(agents)
        return job
