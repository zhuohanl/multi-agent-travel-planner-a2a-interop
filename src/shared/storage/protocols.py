"""
Storage protocols for backend-agnostic workflow persistence.

This module defines the WorkflowStoreProtocol that establishes a clean
interface boundary for workflow state storage. Implementations can be:
- InMemoryWorkflowStore: For development and testing
- CosmosWorkflowStore: For production (Azure Cosmos DB)

Per design doc Compatibility & Migration section:
- All orchestrator code depends only on protocols, not implementations
- Factory function enables environment-based backend selection
- Protocol-first design enables unit testing without Cosmos

Key protocol methods:
- get_by_session: Primary lookup by session_id
- get_by_consultation: Cross-session resumption via consultation_id
- get_by_booking: Lookup workflow via booking_id
- save: Persist state with optimistic locking support
- Index/summary management for cross-entity lookups

Factory function:
- create_workflow_store(): Create store based on STORAGE_BACKEND env var
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.orchestrator.models.workflow_state import WorkflowState

logger = logging.getLogger(__name__)


@runtime_checkable
class WorkflowStoreProtocol(Protocol):
    """
    Protocol for workflow state persistence.

    This protocol abstracts the storage backend, allowing the orchestrator
    to work with either in-memory storage (for testing) or Cosmos DB
    (for production).

    Per design doc Interface Boundary Definition:
    - All methods are async for compatibility with Cosmos DB SDK
    - get_by_* methods return None when entity not found
    - save returns updated etag for optimistic locking
    - Index methods manage cross-entity lookups
    """

    # =========================================================================
    # Primary state operations
    # =========================================================================

    async def get_by_session(self, session_id: str) -> WorkflowState | None:
        """
        Retrieve workflow state by session_id (primary lookup).

        This is the most direct lookup - session_id is the partition key
        in Cosmos DB.

        Args:
            session_id: The session identifier (e.g., "sess_abc123...")

        Returns:
            WorkflowState if found, None if not found
        """
        ...

    async def get_by_consultation(self, consultation_id: str) -> WorkflowState | None:
        """
        Retrieve workflow state by consultation_id (cross-session lookup).

        Uses consultation_index for reverse lookup:
        consultation_id -> session_id -> WorkflowState

        Also validates workflow_version to ensure identity integrity
        (old consultation_ids return None after start_new).

        Args:
            consultation_id: The consultation identifier (e.g., "cons_abc123...")

        Returns:
            WorkflowState if found and valid, None otherwise
        """
        ...

    async def get_by_booking(self, booking_id: str) -> WorkflowState | None:
        """
        Retrieve workflow state by booking_id (booking resumption lookup).

        Uses booking_index for reverse lookup:
        booking_id -> session_id -> WorkflowState

        Args:
            booking_id: The booking identifier (e.g., "book_abc123...")

        Returns:
            WorkflowState if found, None otherwise
        """
        ...

    async def save(
        self, state: WorkflowState, etag: str | None = None
    ) -> str:
        """
        Persist workflow state with optional optimistic locking.

        Args:
            state: The WorkflowState to save
            etag: Optional etag for optimistic locking. If provided,
                  the save will fail if the document has been modified
                  since the etag was retrieved.

        Returns:
            Updated etag value for subsequent saves

        Raises:
            ConflictError: If etag is provided and doesn't match
        """
        ...

    # =========================================================================
    # Consultation index operations
    # =========================================================================

    async def create_consultation_index(
        self,
        consultation_id: str,
        session_id: str,
        workflow_version: int,
    ) -> None:
        """
        Create a consultation index entry for cross-session lookup.

        Called when a new consultation is created (new workflow).

        Args:
            consultation_id: The consultation identifier
            session_id: The session identifier to map to
            workflow_version: Workflow version for identity integrity
        """
        ...

    async def delete_consultation_index(self, consultation_id: str) -> None:
        """
        Delete consultation index entry on start_new.

        This ensures the old consultation_id returns None rather than
        pointing to the new workflow state.

        Args:
            consultation_id: The consultation identifier to invalidate
        """
        ...

    # =========================================================================
    # Consultation summary operations (post-expiry read access)
    # =========================================================================

    async def upsert_consultation_summary(
        self,
        consultation_id: str,
        session_id: str,
        trip_spec_summary: dict[str, Any],
        itinerary_ids: list[str] | None = None,
        booking_ids: list[str] | None = None,
        status: str = "active",
    ) -> None:
        """
        Create or update consultation summary for post-WorkflowState-expiry access.

        Called when:
        1. Itinerary is approved (initial creation)
        2. Bookings complete (status update)

        Args:
            consultation_id: The consultation identifier
            session_id: The session identifier
            trip_spec_summary: Minimal snapshot (destination, dates, travelers)
            itinerary_ids: List of itinerary IDs
            booking_ids: List of booking IDs
            status: Current status (active, completed, cancelled)
        """
        ...

    async def get_consultation_summary(
        self, consultation_id: str
    ) -> dict[str, Any] | None:
        """
        Retrieve consultation summary by consultation_id.

        Used by get_consultation tool for post-WorkflowState-expiry access.

        Args:
            consultation_id: The consultation identifier

        Returns:
            Summary dict if found, None otherwise
        """
        ...

    # =========================================================================
    # Booking index operations (for booking resumption)
    # =========================================================================

    async def create_booking_index(
        self,
        booking_id: str,
        session_id: str,
        consultation_id: str,
    ) -> None:
        """
        Create a booking index entry for workflow lookup via booking_id.

        Called when bookings are created.

        Args:
            booking_id: The booking identifier
            session_id: The session identifier to map to
            consultation_id: The consultation identifier
        """
        ...

    async def delete_booking_index(self, booking_id: str) -> None:
        """
        Delete booking index entry.

        Args:
            booking_id: The booking identifier to remove
        """
        ...


# =============================================================================
# Factory function for backend selection
# =============================================================================


def create_workflow_store(backend: str | None = None) -> WorkflowStoreProtocol:
    """
    Create workflow store based on configuration.

    Factory function that returns the appropriate WorkflowStoreProtocol
    implementation based on the STORAGE_BACKEND environment variable or
    the explicit backend parameter.

    Per design doc Compatibility & Migration section:
    - STORAGE_BACKEND=memory → InMemoryWorkflowStore (default for dev/testing)
    - STORAGE_BACKEND=cosmos → CosmosWorkflowStore (production)

    Args:
        backend: Explicit backend selection. If None, uses STORAGE_BACKEND
                 environment variable. Defaults to "memory" if unset.

    Returns:
        WorkflowStoreProtocol implementation (InMemoryWorkflowStore or
        CosmosWorkflowStore)

    Raises:
        ValueError: If STORAGE_BACKEND=cosmos but required Cosmos
                    configuration is missing
        ImportError: If cosmos backend requested but azure-cosmos not installed

    Example:
        # Use environment variable
        store = create_workflow_store()

        # Explicit backend for testing
        store = create_workflow_store("memory")

        # Explicit backend for production
        store = create_workflow_store("cosmos")
    """
    # Determine backend from parameter or environment
    if backend is None:
        backend = os.environ.get("STORAGE_BACKEND", "memory")

    backend = backend.lower()

    if backend == "cosmos":
        return _create_cosmos_workflow_store()
    else:
        # Default to in-memory for development/testing
        return _create_in_memory_workflow_store()


def _create_in_memory_workflow_store() -> WorkflowStoreProtocol:
    """Create InMemoryWorkflowStore instance."""
    from src.shared.storage.in_memory_workflow_store import InMemoryWorkflowStore

    logger.debug("Creating InMemoryWorkflowStore")
    return InMemoryWorkflowStore()


def _create_cosmos_workflow_store() -> WorkflowStoreProtocol:
    """
    Create CosmosWorkflowStore instance from environment configuration.

    Requires the following environment variables:
    - COSMOS_ENDPOINT: Cosmos DB endpoint URL
    - COSMOS_KEY: Cosmos DB access key (or use managed identity)
    - COSMOS_DATABASE_NAME: Database name (default: "travel_planner")

    Returns:
        Configured CosmosWorkflowStore

    Raises:
        ValueError: If required environment variables are missing
        ImportError: If azure-cosmos package is not installed
    """
    # Import Cosmos SDK and store
    try:
        from azure.cosmos.aio import CosmosClient
    except ImportError as e:
        raise ImportError(
            "azure-cosmos package required for Cosmos backend. "
            "Install with: pip install azure-cosmos"
        ) from e

    from src.shared.storage.cosmos_workflow_store import CosmosWorkflowStore

    # Get configuration from environment
    endpoint = os.environ.get("COSMOS_ENDPOINT")
    key = os.environ.get("COSMOS_KEY")
    database_name = os.environ.get("COSMOS_DATABASE_NAME", "travel_planner")

    if not endpoint:
        raise ValueError(
            "COSMOS_ENDPOINT environment variable required for Cosmos backend"
        )

    # Create Cosmos client
    # Note: In production, consider using DefaultAzureCredential for managed identity
    if key:
        client = CosmosClient(endpoint, credential=key)
    else:
        # Try managed identity
        try:
            from azure.identity.aio import DefaultAzureCredential

            credential = DefaultAzureCredential()
            client = CosmosClient(endpoint, credential=credential)
        except ImportError:
            raise ValueError(
                "COSMOS_KEY environment variable required, or install "
                "azure-identity for managed identity authentication"
            )

    # Get database and containers
    database = client.get_database_client(database_name)
    workflow_states_container = database.get_container_client("workflow_states")
    consultation_index_container = database.get_container_client("consultation_index")
    booking_index_container = database.get_container_client("booking_index")
    consultation_summaries_container = database.get_container_client(
        "consultation_summaries"
    )

    logger.info(
        f"Creating CosmosWorkflowStore with endpoint={endpoint}, "
        f"database={database_name}"
    )

    return CosmosWorkflowStore.from_containers(
        workflow_states_container=workflow_states_container,
        consultation_index_container=consultation_index_container,
        booking_index_container=booking_index_container,
        consultation_summaries_container=consultation_summaries_container,
    )
