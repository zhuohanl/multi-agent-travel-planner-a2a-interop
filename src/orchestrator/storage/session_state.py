"""
Workflow state storage for Cosmos DB.

This module implements the WorkflowStateStore which persists WorkflowState
documents to the `workflow_states` Cosmos DB container.

Key features:
- Partitioned by session_id for efficient lookups
- Optimistic locking via etag for concurrency control
- 7-day TTL for automatic cleanup

Per design doc:
- Container: workflow_states
- Partition key: /session_id
- TTL: 604800 seconds (7 days)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

# Import azure.cosmos only at type-checking time or when needed at runtime
if TYPE_CHECKING:
    from azure.cosmos.aio import ContainerProxy

logger = logging.getLogger(__name__)

# TTL for workflow states: 7 days in seconds
WORKFLOW_STATE_TTL = 7 * 24 * 60 * 60  # 604800 seconds


@dataclass
class WorkflowStateData:
    """
    Serializable workflow state data for storage.

    This is a simplified dataclass representing the essential fields
    stored in Cosmos DB. The full WorkflowState model (with methods
    and computed properties) will be defined in ORCH-065.

    Fields match the design doc container schema for workflow_states.
    """

    session_id: str
    consultation_id: str | None = None
    phase: str = "CLARIFICATION"
    checkpoint: str | None = None
    current_step: str | None = None
    itinerary_id: str | None = None
    current_job_id: str | None = None  # Active discovery job ID
    workflow_version: int = 1
    agent_context_ids: dict[str, dict[str, str | None]] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # etag is managed by Cosmos DB
    etag: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for Cosmos DB storage."""
        return {
            "id": self.session_id,  # Cosmos DB document ID
            "session_id": self.session_id,  # Partition key
            "consultation_id": self.consultation_id,
            "phase": self.phase,
            "checkpoint": self.checkpoint,
            "current_step": self.current_step,
            "itinerary_id": self.itinerary_id,
            "current_job_id": self.current_job_id,
            "workflow_version": self.workflow_version,
            "agent_context_ids": self.agent_context_ids,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "ttl": WORKFLOW_STATE_TTL,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowStateData:
        """Create from dictionary retrieved from Cosmos DB."""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        else:
            created_at = datetime.now(timezone.utc)

        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        else:
            updated_at = datetime.now(timezone.utc)

        return cls(
            session_id=data.get("session_id", data.get("id", "")),
            consultation_id=data.get("consultation_id"),
            phase=data.get("phase", "CLARIFICATION"),
            checkpoint=data.get("checkpoint"),
            current_step=data.get("current_step"),
            itinerary_id=data.get("itinerary_id"),
            current_job_id=data.get("current_job_id"),
            workflow_version=data.get("workflow_version", 1),
            agent_context_ids=data.get("agent_context_ids", {}),
            created_at=created_at,
            updated_at=updated_at,
            etag=data.get("_etag"),
        )


class ConflictError(Exception):
    """Raised when optimistic locking fails due to concurrent modification."""

    def __init__(self, session_id: str, message: str | None = None):
        self.session_id = session_id
        super().__init__(
            message or f"Concurrent modification detected for session {session_id}"
        )


@runtime_checkable
class WorkflowStateStoreProtocol(Protocol):
    """
    Protocol defining the interface for workflow state storage.

    This protocol allows swapping between Cosmos DB and in-memory
    implementations for production vs testing.
    """

    async def get_state(self, session_id: str) -> WorkflowStateData | None:
        """
        Retrieve workflow state by session_id.

        Args:
            session_id: The session identifier (partition key)

        Returns:
            WorkflowStateData if found, None if not found
        """
        ...

    async def save_state(
        self, state: WorkflowStateData, if_match: str | None = None
    ) -> WorkflowStateData:
        """
        Save workflow state.

        Args:
            state: The workflow state to save
            if_match: Optional etag for optimistic locking. If provided,
                     the save will fail with ConflictError if the document
                     has been modified since the etag was retrieved.

        Returns:
            The saved state with updated etag

        Raises:
            ConflictError: If if_match is provided and doesn't match
        """
        ...

    async def delete_state(self, session_id: str) -> bool:
        """
        Delete workflow state by session_id.

        Args:
            session_id: The session identifier

        Returns:
            True if deleted, False if not found
        """
        ...


class WorkflowStateStore:
    """
    Cosmos DB implementation of workflow state storage.

    Uses the workflow_states container partitioned by session_id.
    Supports optimistic locking via etag for concurrent updates.
    """

    def __init__(self, container: ContainerProxy) -> None:
        """
        Initialize the store with a Cosmos container client.

        Args:
            container: Async Cosmos container client for workflow_states
        """
        self._container = container

    async def get_state(self, session_id: str) -> WorkflowStateData | None:
        """
        Retrieve workflow state by session_id.

        Args:
            session_id: The session identifier (partition key)

        Returns:
            WorkflowStateData if found, None if not found
        """
        try:
            response = await self._container.read_item(
                item=session_id,
                partition_key=session_id,
            )
            logger.debug(f"Retrieved workflow state for session {session_id}")
            return WorkflowStateData.from_dict(response)
        except Exception as e:
            # Handle CosmosResourceNotFoundError
            error_code = getattr(e, "status_code", None)
            if error_code == 404:
                logger.debug(f"Workflow state not found for session {session_id}")
                return None
            # Re-raise other errors
            logger.error(f"Error retrieving workflow state: {e}")
            raise

    async def save_state(
        self, state: WorkflowStateData, if_match: str | None = None
    ) -> WorkflowStateData:
        """
        Save workflow state with optional optimistic locking.

        Uses upsert for create/update semantics. When if_match is provided,
        uses conditional write to detect concurrent modifications.

        Args:
            state: The workflow state to save
            if_match: Optional etag for optimistic locking

        Returns:
            The saved state with updated etag

        Raises:
            ConflictError: If if_match is provided and doesn't match
        """
        # Update timestamp
        state.updated_at = datetime.now(timezone.utc)
        doc = state.to_dict()

        try:
            if if_match:
                # Conditional write with etag
                response = await self._container.replace_item(
                    item=state.session_id,
                    body=doc,
                    if_match=if_match,
                )
                logger.debug(
                    f"Replaced workflow state for session {state.session_id} with etag check"
                )
            else:
                # Upsert without etag check
                response = await self._container.upsert_item(body=doc)
                logger.debug(f"Upserted workflow state for session {state.session_id}")

            return WorkflowStateData.from_dict(response)

        except Exception as e:
            # Handle CosmosResourceExistsError (412 Precondition Failed)
            error_code = getattr(e, "status_code", None)
            if error_code == 412:
                logger.warning(
                    f"Conflict detected saving workflow state for session {state.session_id}"
                )
                raise ConflictError(state.session_id) from e
            # Re-raise other errors
            logger.error(f"Error saving workflow state: {e}")
            raise

    async def delete_state(self, session_id: str) -> bool:
        """
        Delete workflow state by session_id.

        Args:
            session_id: The session identifier

        Returns:
            True if deleted, False if not found
        """
        try:
            await self._container.delete_item(
                item=session_id,
                partition_key=session_id,
            )
            logger.debug(f"Deleted workflow state for session {session_id}")
            return True
        except Exception as e:
            error_code = getattr(e, "status_code", None)
            if error_code == 404:
                logger.debug(f"Workflow state not found for deletion: {session_id}")
                return False
            logger.error(f"Error deleting workflow state: {e}")
            raise


class InMemoryWorkflowStateStore:
    """
    In-memory implementation of workflow state storage for testing.

    Implements the same interface as WorkflowStateStore but stores
    data in memory. Useful for unit tests and local development.
    """

    def __init__(self) -> None:
        """Initialize empty in-memory store."""
        self._states: dict[str, dict[str, Any]] = {}
        self._etag_counter = 0

    async def get_state(self, session_id: str) -> WorkflowStateData | None:
        """Retrieve workflow state by session_id."""
        if session_id not in self._states:
            return None
        return WorkflowStateData.from_dict(self._states[session_id])

    async def save_state(
        self, state: WorkflowStateData, if_match: str | None = None
    ) -> WorkflowStateData:
        """Save workflow state with optional optimistic locking."""
        existing = self._states.get(state.session_id)

        if if_match and existing:
            existing_etag = existing.get("_etag")
            if existing_etag != if_match:
                raise ConflictError(state.session_id)

        # Update timestamp and generate new etag
        state.updated_at = datetime.now(timezone.utc)
        self._etag_counter += 1
        new_etag = f"etag_{self._etag_counter}"

        doc = state.to_dict()
        doc["_etag"] = new_etag
        self._states[state.session_id] = doc

        return WorkflowStateData.from_dict(doc)

    async def delete_state(self, session_id: str) -> bool:
        """Delete workflow state by session_id."""
        if session_id in self._states:
            del self._states[session_id]
            return True
        return False

    def clear(self) -> None:
        """Clear all states (for test cleanup)."""
        self._states.clear()
        self._etag_counter = 0
