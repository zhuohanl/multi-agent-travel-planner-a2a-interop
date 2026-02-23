"""
Consultation index storage for Cosmos DB.

This module implements the ConsultationIndexStore which provides a reverse
lookup from consultation_id to session_id for cross-session resumption.

Key features:
- Partitioned by consultation_id for O(1) lookups
- Includes workflow_version for identity integrity validation
- 7-day TTL matching WorkflowState TTL
- delete_consultation() for start_new invalidation

Per design doc:
- Container: consultation_index
- Partition key: /consultation_id
- TTL: 604800 seconds (7 days)
- Purpose: Maps consultation_id → session_id for active workflows
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

# Import azure.cosmos only at type-checking time or when needed at runtime
if TYPE_CHECKING:
    from azure.cosmos.aio import ContainerProxy

logger = logging.getLogger(__name__)

# TTL for consultation index: 7 days in seconds (matches WorkflowState)
CONSULTATION_INDEX_TTL = 7 * 24 * 60 * 60  # 604800 seconds


@dataclass
class ConsultationIndexEntry:
    """
    Entry in the consultation_index container.

    Maps consultation_id to session_id with workflow_version for
    identity integrity validation during cross-session resumption.
    """

    consultation_id: str
    session_id: str
    workflow_version: int = 1

    def to_dict(self) -> dict:
        """Convert to dictionary for Cosmos DB storage."""
        return {
            "id": self.consultation_id,  # Cosmos DB document ID
            "consultation_id": self.consultation_id,  # Partition key
            "session_id": self.session_id,
            "workflow_version": self.workflow_version,
            "ttl": CONSULTATION_INDEX_TTL,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConsultationIndexEntry:
        """Create from dictionary retrieved from Cosmos DB."""
        return cls(
            consultation_id=data.get("consultation_id", data.get("id", "")),
            session_id=data.get("session_id", ""),
            workflow_version=data.get("workflow_version", 1),
        )


@runtime_checkable
class ConsultationIndexStoreProtocol(Protocol):
    """
    Protocol defining the interface for consultation index storage.

    This protocol allows swapping between Cosmos DB and in-memory
    implementations for production vs testing.
    """

    async def get_session_for_consultation(
        self, consultation_id: str
    ) -> ConsultationIndexEntry | None:
        """
        Retrieve index entry by consultation_id.

        Args:
            consultation_id: The consultation identifier (partition key)

        Returns:
            ConsultationIndexEntry with session_id and workflow_version if found,
            None if not found
        """
        ...

    async def add_session(
        self, session_id: str, consultation_id: str, workflow_version: int = 1
    ) -> ConsultationIndexEntry:
        """
        Create or update an index entry.

        Args:
            session_id: The session identifier to store
            consultation_id: The consultation identifier (partition key)
            workflow_version: The workflow version for identity integrity

        Returns:
            The created/updated index entry
        """
        ...

    async def delete_consultation(self, consultation_id: str) -> bool:
        """
        Delete index entry to invalidate old consultation_id on start_new.

        This ensures the old consultation_id returns "not found" rather
        than pointing to the new workflow state.

        Args:
            consultation_id: The consultation identifier to delete

        Returns:
            True if deleted, False if not found
        """
        ...


class ConsultationIndexStore:
    """
    Cosmos DB implementation of consultation index storage.

    Uses the consultation_index container partitioned by consultation_id.
    Provides O(1) lookup for cross-session resumption.
    """

    def __init__(self, container: ContainerProxy) -> None:
        """
        Initialize the store with a Cosmos container client.

        Args:
            container: Async Cosmos container client for consultation_index
        """
        self._container = container

    async def get_session_for_consultation(
        self, consultation_id: str
    ) -> ConsultationIndexEntry | None:
        """
        Retrieve index entry by consultation_id.

        Args:
            consultation_id: The consultation identifier (partition key)

        Returns:
            ConsultationIndexEntry if found, None if not found
        """
        try:
            response = await self._container.read_item(
                item=consultation_id,
                partition_key=consultation_id,
            )
            logger.debug(f"Retrieved consultation index for {consultation_id}")
            return ConsultationIndexEntry.from_dict(response)
        except Exception as e:
            # Handle CosmosResourceNotFoundError
            error_code = getattr(e, "status_code", None)
            if error_code == 404:
                logger.debug(f"Consultation index not found for {consultation_id}")
                return None
            # Re-raise other errors
            logger.error(f"Error retrieving consultation index: {e}")
            raise

    async def add_session(
        self, session_id: str, consultation_id: str, workflow_version: int = 1
    ) -> ConsultationIndexEntry:
        """
        Create or update an index entry.

        Uses upsert for create/update semantics.

        Args:
            session_id: The session identifier to store
            consultation_id: The consultation identifier (partition key)
            workflow_version: The workflow version for identity integrity

        Returns:
            The created/updated index entry
        """
        entry = ConsultationIndexEntry(
            consultation_id=consultation_id,
            session_id=session_id,
            workflow_version=workflow_version,
        )
        doc = entry.to_dict()

        try:
            response = await self._container.upsert_item(body=doc)
            logger.debug(
                f"Upserted consultation index: {consultation_id} -> {session_id} "
                f"(version={workflow_version})"
            )
            return ConsultationIndexEntry.from_dict(response)
        except Exception as e:
            logger.error(f"Error adding consultation index: {e}")
            raise

    async def delete_consultation(self, consultation_id: str) -> bool:
        """
        Delete index entry to invalidate old consultation_id on start_new.

        Args:
            consultation_id: The consultation identifier to delete

        Returns:
            True if deleted, False if not found
        """
        try:
            await self._container.delete_item(
                item=consultation_id,
                partition_key=consultation_id,
            )
            logger.debug(f"Deleted consultation index for {consultation_id}")
            return True
        except Exception as e:
            error_code = getattr(e, "status_code", None)
            if error_code == 404:
                logger.debug(
                    f"Consultation index not found for deletion: {consultation_id}"
                )
                return False
            logger.error(f"Error deleting consultation index: {e}")
            raise


class InMemoryConsultationIndexStore:
    """
    In-memory implementation of consultation index storage for testing.

    Implements the same interface as ConsultationIndexStore but stores
    data in memory. Useful for unit tests and local development.
    """

    def __init__(self) -> None:
        """Initialize empty in-memory store."""
        self._index: dict[str, dict] = {}

    async def get_session_for_consultation(
        self, consultation_id: str
    ) -> ConsultationIndexEntry | None:
        """Retrieve index entry by consultation_id."""
        if consultation_id not in self._index:
            return None
        return ConsultationIndexEntry.from_dict(self._index[consultation_id])

    async def add_session(
        self, session_id: str, consultation_id: str, workflow_version: int = 1
    ) -> ConsultationIndexEntry:
        """Create or update an index entry."""
        entry = ConsultationIndexEntry(
            consultation_id=consultation_id,
            session_id=session_id,
            workflow_version=workflow_version,
        )
        self._index[consultation_id] = entry.to_dict()
        return entry

    async def delete_consultation(self, consultation_id: str) -> bool:
        """Delete index entry."""
        if consultation_id in self._index:
            del self._index[consultation_id]
            return True
        return False

    def clear(self) -> None:
        """Clear all index entries (for test cleanup)."""
        self._index.clear()
