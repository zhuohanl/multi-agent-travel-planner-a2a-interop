"""
Discovery artifacts storage for Cosmos DB.

This module implements the DiscoveryArtifactsStore which persists full
discovery results when WorkflowState's top-10 summaries aren't enough.

Key features:
- Partitioned by consultation_id for efficient lookups
- 7-day TTL matching WorkflowState TTL
- Stores full result sets per agent per job
- Supports retrieval by consultation_id or specific artifact

Per design doc:
- Container: discovery_artifacts
- Partition key: /consultation_id
- TTL: 604800 seconds (7 days)
- Purpose: Full discovery results when top-10 summaries not enough
- Schema: {id, consultation_id, job_id, agent_name, full_results, result_count, created_at, ttl}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

# Import azure.cosmos only at type-checking time or when needed at runtime
if TYPE_CHECKING:
    from azure.cosmos.aio import ContainerProxy

logger = logging.getLogger(__name__)

# TTL for discovery artifacts: 7 days in seconds (matches WorkflowState)
DISCOVERY_ARTIFACTS_TTL = 7 * 24 * 60 * 60  # 604800 seconds


@dataclass
class DiscoveryArtifact:
    """
    Full discovery results for a single agent.

    This represents the complete result set from a discovery agent
    when the top-10 summaries stored in WorkflowState aren't sufficient.

    Attributes:
        consultation_id: The consultation this artifact belongs to (partition key)
        job_id: The discovery job that produced these results
        agent_name: The agent that produced the results (e.g., "stay", "transport")
        full_results: Complete list of discovery results
        result_count: Total number of results in full_results
        created_at: When the artifact was created (UTC)
    """

    consultation_id: str
    job_id: str
    agent_name: str
    full_results: list[dict[str, Any]]
    result_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        """Calculate result_count if not provided."""
        if self.result_count == 0 and self.full_results:
            self.result_count = len(self.full_results)

    @property
    def artifact_id(self) -> str:
        """Generate the artifact document ID from job_id and agent_name."""
        return f"artifact_{self.job_id}_{self.agent_name}"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for Cosmos DB storage."""
        return {
            "id": self.artifact_id,  # Cosmos DB document ID
            "consultation_id": self.consultation_id,  # Partition key
            "job_id": self.job_id,
            "agent_name": self.agent_name,
            "full_results": self.full_results,
            "result_count": self.result_count,
            "created_at": self.created_at.isoformat(),
            "ttl": DISCOVERY_ARTIFACTS_TTL,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiscoveryArtifact:
        """Create from dictionary retrieved from Cosmos DB."""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        else:
            created_at = datetime.now(timezone.utc)

        return cls(
            consultation_id=data.get("consultation_id", ""),
            job_id=data.get("job_id", ""),
            agent_name=data.get("agent_name", ""),
            full_results=data.get("full_results", []),
            result_count=data.get("result_count", 0),
            created_at=created_at,
        )


@runtime_checkable
class DiscoveryArtifactsStoreProtocol(Protocol):
    """
    Protocol defining the interface for discovery artifacts storage.

    This protocol allows swapping between Cosmos DB and in-memory
    implementations for production vs testing.
    """

    async def get_artifacts(
        self, consultation_id: str, job_id: str | None = None
    ) -> list[DiscoveryArtifact]:
        """
        Retrieve artifacts for a consultation.

        Args:
            consultation_id: The consultation identifier (partition key)
            job_id: Optional job_id to filter by specific job

        Returns:
            List of DiscoveryArtifact objects for the consultation
        """
        ...

    async def get_artifact(
        self, consultation_id: str, job_id: str, agent_name: str
    ) -> DiscoveryArtifact | None:
        """
        Retrieve a specific artifact by job_id and agent_name.

        Args:
            consultation_id: The consultation identifier (partition key)
            job_id: The job identifier
            agent_name: The agent name

        Returns:
            The DiscoveryArtifact if found, None otherwise
        """
        ...

    async def save_artifact(self, artifact: DiscoveryArtifact) -> DiscoveryArtifact:
        """
        Save or update an artifact.

        Args:
            artifact: The artifact to save

        Returns:
            The saved DiscoveryArtifact (with any server-generated fields)
        """
        ...

    async def delete_artifacts(
        self, consultation_id: str, job_id: str | None = None
    ) -> int:
        """
        Delete artifacts for a consultation.

        Args:
            consultation_id: The consultation identifier
            job_id: Optional job_id to filter (if None, deletes all for consultation)

        Returns:
            Number of artifacts deleted
        """
        ...


class DiscoveryArtifactsStore:
    """
    Cosmos DB implementation of discovery artifacts storage.

    Uses the discovery_artifacts container partitioned by consultation_id.
    Provides storage for full discovery results that exceed WorkflowState limits.
    """

    def __init__(self, container: ContainerProxy) -> None:
        """
        Initialize the store with a Cosmos container client.

        Args:
            container: Async Cosmos container client for discovery_artifacts
        """
        self._container = container

    async def get_artifacts(
        self, consultation_id: str, job_id: str | None = None
    ) -> list[DiscoveryArtifact]:
        """
        Retrieve artifacts for a consultation.

        Args:
            consultation_id: The consultation identifier (partition key)
            job_id: Optional job_id to filter by specific job

        Returns:
            List of DiscoveryArtifact objects for the consultation
        """
        # Build query with optional job_id filter
        if job_id is not None:
            query = (
                "SELECT * FROM c WHERE c.consultation_id = @consultation_id "
                "AND c.job_id = @job_id ORDER BY c.created_at ASC"
            )
            parameters = [
                {"name": "@consultation_id", "value": consultation_id},
                {"name": "@job_id", "value": job_id},
            ]
        else:
            query = (
                "SELECT * FROM c WHERE c.consultation_id = @consultation_id "
                "ORDER BY c.created_at ASC"
            )
            parameters = [{"name": "@consultation_id", "value": consultation_id}]

        try:
            items = self._container.query_items(
                query=query,
                parameters=parameters,
                partition_key=consultation_id,
            )

            artifacts = []
            async for item in items:
                artifacts.append(DiscoveryArtifact.from_dict(item))

            logger.debug(
                f"Retrieved {len(artifacts)} artifacts for consultation {consultation_id}"
                + (f" (job={job_id})" if job_id else "")
            )
            return artifacts

        except Exception as e:
            logger.error(
                f"Error retrieving artifacts for consultation {consultation_id}: {e}"
            )
            raise

    async def get_artifact(
        self, consultation_id: str, job_id: str, agent_name: str
    ) -> DiscoveryArtifact | None:
        """
        Retrieve a specific artifact by job_id and agent_name.

        Args:
            consultation_id: The consultation identifier (partition key)
            job_id: The job identifier
            agent_name: The agent name

        Returns:
            The DiscoveryArtifact if found, None otherwise
        """
        artifact_id = f"artifact_{job_id}_{agent_name}"

        try:
            item = await self._container.read_item(
                item=artifact_id,
                partition_key=consultation_id,
            )
            logger.debug(
                f"Retrieved artifact {artifact_id} for consultation {consultation_id}"
            )
            return DiscoveryArtifact.from_dict(item)

        except Exception as e:
            # Check if it's a 404 (not found)
            error_code = getattr(e, "status_code", None)
            if error_code == 404:
                logger.debug(
                    f"Artifact {artifact_id} not found for consultation {consultation_id}"
                )
                return None
            logger.error(f"Error retrieving artifact {artifact_id}: {e}")
            raise

    async def save_artifact(self, artifact: DiscoveryArtifact) -> DiscoveryArtifact:
        """
        Save or update an artifact.

        Uses upsert to allow creating or updating artifacts.

        Args:
            artifact: The artifact to save

        Returns:
            The saved DiscoveryArtifact (with any server-generated fields)
        """
        doc = artifact.to_dict()

        try:
            response = await self._container.upsert_item(body=doc)
            logger.debug(
                f"Saved artifact {artifact.artifact_id} for consultation "
                f"{artifact.consultation_id} (agent={artifact.agent_name}, "
                f"results={artifact.result_count})"
            )
            return DiscoveryArtifact.from_dict(response)

        except Exception as e:
            logger.error(
                f"Error saving artifact for consultation {artifact.consultation_id}: {e}"
            )
            raise

    async def delete_artifacts(
        self, consultation_id: str, job_id: str | None = None
    ) -> int:
        """
        Delete artifacts for a consultation.

        Args:
            consultation_id: The consultation identifier
            job_id: Optional job_id to filter (if None, deletes all for consultation)

        Returns:
            Number of artifacts deleted
        """
        # First, query all artifact IDs for this consultation (and optionally job)
        if job_id is not None:
            query = (
                "SELECT c.id FROM c WHERE c.consultation_id = @consultation_id "
                "AND c.job_id = @job_id"
            )
            parameters = [
                {"name": "@consultation_id", "value": consultation_id},
                {"name": "@job_id", "value": job_id},
            ]
        else:
            query = "SELECT c.id FROM c WHERE c.consultation_id = @consultation_id"
            parameters = [{"name": "@consultation_id", "value": consultation_id}]

        try:
            items = self._container.query_items(
                query=query,
                parameters=parameters,
                partition_key=consultation_id,
            )

            deleted_count = 0
            async for item in items:
                doc_id = item["id"]
                try:
                    await self._container.delete_item(
                        item=doc_id,
                        partition_key=consultation_id,
                    )
                    deleted_count += 1
                except Exception as e:
                    # Log but continue - best effort deletion
                    error_code = getattr(e, "status_code", None)
                    if error_code != 404:
                        logger.warning(f"Error deleting artifact {doc_id}: {e}")

            logger.debug(
                f"Deleted {deleted_count} artifacts for consultation {consultation_id}"
                + (f" (job={job_id})" if job_id else "")
            )
            return deleted_count

        except Exception as e:
            logger.error(
                f"Error deleting artifacts for consultation {consultation_id}: {e}"
            )
            raise


class InMemoryDiscoveryArtifactsStore:
    """
    In-memory implementation of discovery artifacts storage for testing.

    Implements the same interface as DiscoveryArtifactsStore but stores
    data in memory. Useful for unit tests and local development.
    """

    def __init__(self) -> None:
        """Initialize empty in-memory store."""
        # Store artifacts per consultation: {consultation_id: {artifact_id: dict}}
        self._artifacts: dict[str, dict[str, dict[str, Any]]] = {}

    async def get_artifacts(
        self, consultation_id: str, job_id: str | None = None
    ) -> list[DiscoveryArtifact]:
        """Retrieve artifacts for a consultation."""
        if consultation_id not in self._artifacts:
            return []

        # Get all artifacts for consultation
        consultation_artifacts = self._artifacts[consultation_id]

        # Filter by job_id if specified
        if job_id is not None:
            filtered = [
                doc
                for doc in consultation_artifacts.values()
                if doc.get("job_id") == job_id
            ]
        else:
            filtered = list(consultation_artifacts.values())

        # Sort by created_at
        filtered.sort(key=lambda x: x.get("created_at", ""))

        return [DiscoveryArtifact.from_dict(doc) for doc in filtered]

    async def get_artifact(
        self, consultation_id: str, job_id: str, agent_name: str
    ) -> DiscoveryArtifact | None:
        """Retrieve a specific artifact by job_id and agent_name."""
        if consultation_id not in self._artifacts:
            return None

        artifact_id = f"artifact_{job_id}_{agent_name}"
        doc = self._artifacts[consultation_id].get(artifact_id)

        if doc is None:
            return None

        return DiscoveryArtifact.from_dict(doc)

    async def save_artifact(self, artifact: DiscoveryArtifact) -> DiscoveryArtifact:
        """Save or update an artifact."""
        doc = artifact.to_dict()
        consultation_id = artifact.consultation_id
        artifact_id = artifact.artifact_id

        if consultation_id not in self._artifacts:
            self._artifacts[consultation_id] = {}

        self._artifacts[consultation_id][artifact_id] = doc
        return artifact

    async def delete_artifacts(
        self, consultation_id: str, job_id: str | None = None
    ) -> int:
        """Delete artifacts for a consultation."""
        if consultation_id not in self._artifacts:
            return 0

        if job_id is not None:
            # Delete only artifacts for specific job
            to_delete = [
                artifact_id
                for artifact_id, doc in self._artifacts[consultation_id].items()
                if doc.get("job_id") == job_id
            ]
            for artifact_id in to_delete:
                del self._artifacts[consultation_id][artifact_id]
            return len(to_delete)
        else:
            # Delete all artifacts for consultation
            count = len(self._artifacts[consultation_id])
            del self._artifacts[consultation_id]
            return count

    def clear(self) -> None:
        """Clear all artifacts (for test cleanup)."""
        self._artifacts.clear()

    def get_artifact_count(self, consultation_id: str) -> int:
        """Get the number of artifacts for a consultation (test helper)."""
        if consultation_id not in self._artifacts:
            return 0
        return len(self._artifacts[consultation_id])

    def get_all_consultation_ids(self) -> list[str]:
        """Get all consultation IDs with artifacts (test helper)."""
        return list(self._artifacts.keys())
