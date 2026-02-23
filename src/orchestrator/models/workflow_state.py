"""
WorkflowState: Central data structure for trip planning progress.

Per design doc Data Stores section:
- WorkflowState tracks the current phase, checkpoint, agent context IDs,
  conversation history, and discovery results
- Persisted in Cosmos DB with optimistic locking via etag
- TTL of 7 days for automatic cleanup

The workflow progresses through phases:
1. CLARIFICATION: Gathering trip requirements
2. DISCOVERY_IN_PROGRESS: Agents searching in parallel
3. DISCOVERY_PLANNING: Results ready, awaiting itinerary approval
4. BOOKING: Itinerary approved, booking items
5. COMPLETED/FAILED/CANCELLED: Terminal states
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

from src.orchestrator.models.clarifier_conversation import ClarifierConversation
from src.orchestrator.models.conversation import AgentConversation

# Avoid circular imports for type hints
if TYPE_CHECKING:
    pass


class Phase(str, Enum):
    """
    Workflow phases - mutually exclusive states.

    Per design doc Three-Phase Workflow section:
    - Phase determines which handlers and events are valid
    - Transitions are controlled by checkpoints and events
    """

    CLARIFICATION = "clarification"  # Phase 1: Gathering trip requirements
    DISCOVERY_IN_PROGRESS = "discovery_in_progress"  # Phase 2a: Agents searching
    DISCOVERY_PLANNING = "discovery_planning"  # Phase 2b: Results ready, awaiting approval
    BOOKING = "booking"  # Phase 3: User booking items
    COMPLETED = "completed"  # Workflow finished successfully
    FAILED = "failed"  # Workflow failed (recoverable via start_new)
    CANCELLED = "cancelled"  # User cancelled workflow


@dataclass
class AgentA2AState:
    """
    Per-agent A2A protocol state for multi-turn conversations.

    Per design doc Agent Communication section:
    - context_id: Persistent across the entire session with this agent
    - task_id: Current task within the context (cleared when task completes)

    Used in WorkflowState.agent_context_ids to track A2A state per downstream agent.
    """

    context_id: str | None = None  # A2A context for multi-turn (persistent)
    task_id: str | None = None  # Current task within context (transient)

    def to_dict(self) -> dict[str, str | None]:
        """Serialize to dictionary for storage."""
        return {
            "context_id": self.context_id,
            "task_id": self.task_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentA2AState:
        """Deserialize from dictionary."""
        return cls(
            context_id=data.get("context_id"),
            task_id=data.get("task_id"),
        )


@dataclass
class WorkflowState:
    """
    Canonical workflow state schema.

    Per design doc Data Stores section:
    - Checkpoint model: Single `checkpoint` field (str | None)
    - checkpoint indicates which approval gate we're waiting at (if any)
    - When checkpoint is set, only events valid for that checkpoint are allowed
    - When checkpoint is None, we're in a non-gated phase or transitioning

    Phase-Checkpoint Relationships:
    | Phase | Valid Checkpoints | Description |
    |-------|-------------------|-------------|
    | CLARIFICATION | "trip_spec_approval", None | Gathering info → approval |
    | DISCOVERY_IN_PROGRESS | None | Agents running |
    | DISCOVERY_PLANNING | "itinerary_approval" | Results ready, awaiting approval |
    | BOOKING | None | Free-form booking |
    | COMPLETED/FAILED/CANCELLED | None | Terminal states |
    """

    # Identity
    session_id: str  # Primary key, partition key
    consultation_id: str  # Business workflow ID (returned to client, non-guessable)
    workflow_version: int = 1  # Increments on start_new; invalidates old consultation_ids

    # Workflow position
    phase: Phase = Phase.CLARIFICATION  # Current phase (see enum above)
    checkpoint: str | None = None  # Current approval gate or None
    current_step: str = "gathering"  # Sub-step within phase (for UI display)

    # Business data - these will be typed properly when their models are created
    trip_spec: dict[str, Any] | None = None  # TripSpec when ORCH-066 is done
    discovery_results: dict[str, Any] | None = None  # DiscoveryResults (typed)
    itinerary_draft: dict[str, Any] | None = None  # ItineraryDraft before approval
    itinerary_id: str | None = None  # Approved itinerary ID (after approval)

    # Job coordination
    current_job_id: str | None = None  # Active discovery job ID
    last_synced_job_id: str | None = None  # For idempotency in finalize_job

    # Agent coordination
    agent_context_ids: dict[str, AgentA2AState] = field(default_factory=dict)
    clarifier_conversation: ClarifierConversation = field(
        default_factory=lambda: ClarifierConversation(agent_name="clarifier", messages=[])
    )
    discovery_requests: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    # Sharding support (for large data)
    discovery_artifact_id: str | None = None  # Pointer to full results
    conversation_overflow_count: int = 0  # Messages moved to chat_messages

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    cancelled_at: datetime | None = None  # Set when user cancels workflow
    etag: str | None = None  # Cosmos DB optimistic concurrency token

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to dictionary for Cosmos DB storage.

        Uses camelCase for A2A protocol compatibility where appropriate,
        but maintains snake_case for internal fields per design doc.
        """
        return {
            # Cosmos DB document ID and partition key
            "id": self.session_id,
            "session_id": self.session_id,
            "consultation_id": self.consultation_id,
            "workflow_version": self.workflow_version,
            # Workflow position
            "phase": self.phase.value,
            "checkpoint": self.checkpoint,
            "current_step": self.current_step,
            # Business data
            "trip_spec": self.trip_spec,
            "discovery_results": self.discovery_results,
            "itinerary_draft": self.itinerary_draft,
            "itinerary_id": self.itinerary_id,
            # Job coordination
            "current_job_id": self.current_job_id,
            "last_synced_job_id": self.last_synced_job_id,
            # Agent coordination
            "agent_context_ids": {
                name: state.to_dict() for name, state in self.agent_context_ids.items()
            },
            "clarifier_conversation": self.clarifier_conversation.to_dict(),
            "discovery_requests": self.discovery_requests,
            # Sharding support
            "discovery_artifact_id": self.discovery_artifact_id,
            "conversation_overflow_count": self.clarifier_conversation.overflow_message_count,
            # Metadata
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            # TTL for automatic cleanup (7 days)
            "ttl": 7 * 24 * 60 * 60,  # 604800 seconds
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowState:
        """
        Deserialize from dictionary retrieved from Cosmos DB.

        Handles missing fields gracefully with sensible defaults.
        """
        # Parse phase
        phase_str = data.get("phase", "clarification")
        try:
            phase = Phase(phase_str)
        except ValueError:
            phase = Phase.CLARIFICATION

        # Parse agent_context_ids
        agent_context_ids_raw = data.get("agent_context_ids", {})
        agent_context_ids = {
            name: AgentA2AState.from_dict(state_data)
            for name, state_data in agent_context_ids_raw.items()
        }

        # Parse clarifier_conversation using ClarifierConversation.from_dict
        conv_data = data.get("clarifier_conversation", {})
        clarifier_conversation = ClarifierConversation.from_dict(conv_data)

        # Parse timestamps
        created_at = cls._parse_datetime(data.get("created_at"), default_now=True)
        updated_at = cls._parse_datetime(data.get("updated_at"), default_now=True)
        cancelled_at = cls._parse_datetime(data.get("cancelled_at"), default_now=False)

        # Use overflow count from clarifier_conversation (authoritative source)
        # Fall back to top-level field for backward compatibility with old data
        overflow_count = clarifier_conversation.overflow_message_count
        if overflow_count == 0:
            overflow_count = data.get("conversation_overflow_count", 0)
            clarifier_conversation.overflow_message_count = overflow_count

        return cls(
            session_id=data.get("session_id", data.get("id", "")),
            consultation_id=data.get("consultation_id", ""),
            workflow_version=data.get("workflow_version", 1),
            phase=phase,
            checkpoint=data.get("checkpoint"),
            current_step=data.get("current_step", "gathering"),
            trip_spec=data.get("trip_spec"),
            discovery_results=data.get("discovery_results"),
            itinerary_draft=data.get("itinerary_draft"),
            itinerary_id=data.get("itinerary_id"),
            current_job_id=data.get("current_job_id"),
            last_synced_job_id=data.get("last_synced_job_id"),
            agent_context_ids=agent_context_ids,
            clarifier_conversation=clarifier_conversation,
            discovery_requests=data.get("discovery_requests", {}),
            discovery_artifact_id=data.get("discovery_artifact_id"),
            conversation_overflow_count=overflow_count,
            created_at=created_at,
            updated_at=updated_at,
            cancelled_at=cancelled_at,
            etag=data.get("_etag"),
        )

    @staticmethod
    def _parse_datetime(value: str | datetime | None, default_now: bool = True) -> datetime | None:
        """Parse datetime from ISO string or return default.

        Args:
            value: ISO string, datetime, or None
            default_now: If True, return current time for None/invalid.
                        If False, return None for None/invalid.
        """
        if value is None:
            return datetime.now(timezone.utc) if default_now else None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return datetime.now(timezone.utc) if default_now else None

    def is_terminal(self) -> bool:
        """Check if workflow is in a terminal state."""
        return self.phase in (Phase.COMPLETED, Phase.FAILED, Phase.CANCELLED)

    def is_at_checkpoint(self) -> bool:
        """Check if workflow is waiting at an approval checkpoint."""
        return self.checkpoint is not None

    def get_agent_a2a_state(self, agent_name: str) -> AgentA2AState:
        """
        Get A2A state for an agent, creating if not exists.

        Args:
            agent_name: The agent identifier (e.g., "clarifier", "stay")

        Returns:
            AgentA2AState for the agent
        """
        if agent_name not in self.agent_context_ids:
            self.agent_context_ids[agent_name] = AgentA2AState()
        return self.agent_context_ids[agent_name]

    def update_agent_a2a_state(
        self,
        agent_name: str,
        context_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        """
        Update A2A state for an agent.

        Args:
            agent_name: The agent identifier
            context_id: New context ID (if provided)
            task_id: New task ID (if provided)
        """
        state = self.get_agent_a2a_state(agent_name)
        if context_id is not None:
            state.context_id = context_id
        if task_id is not None:
            state.task_id = task_id
        self.updated_at = datetime.now(timezone.utc)
