"""
Cosmos DB implementation of WorkflowStoreProtocol.

This module provides CosmosWorkflowStore which implements the full
WorkflowStoreProtocol interface by composing the existing Cosmos DB stores:
- WorkflowStateStore: Primary workflow state storage
- ConsultationIndexStore: Consultation ID to session ID mapping
- BookingIndexStore: Booking ID to session ID mapping
- ConsultationSummaryStore: Post-expiry consultation access

Per design doc Compatibility & Migration section:
- CosmosWorkflowStore enables production deployment with Cosmos DB
- Interface-compatible with InMemoryWorkflowStore for testing
- Factory function provides environment-based backend selection

Usage:
    from src.shared.storage import create_workflow_store

    # Production (STORAGE_BACKEND=cosmos)
    store = create_workflow_store()

    # Testing (STORAGE_BACKEND=memory or default)
    store = create_workflow_store("memory")
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any

# Lazy imports for Cosmos DB stores to avoid circular imports
if TYPE_CHECKING:
    from azure.cosmos.aio import ContainerProxy
    from src.orchestrator.models.workflow_state import WorkflowState
    from src.orchestrator.storage.booking_index import BookingIndexStore
    from src.orchestrator.storage.consultation_index import ConsultationIndexStore
    from src.orchestrator.storage.consultation_summaries import (
        ConsultationSummary,
        ConsultationSummaryStore,
    )
    from src.orchestrator.storage.session_state import (
        WorkflowStateStore,
    )

logger = logging.getLogger(__name__)


class CosmosWorkflowStore:
    """
    Cosmos DB implementation of WorkflowStoreProtocol.

    This class composes existing Cosmos DB stores to provide a unified
    interface for workflow persistence. It delegates to:
    - WorkflowStateStore: For session-based state storage
    - ConsultationIndexStore: For consultation ID lookups
    - BookingIndexStore: For booking ID lookups
    - ConsultationSummaryStore: For post-expiry consultation access

    The composition pattern enables:
    - Code reuse of existing, tested Cosmos DB implementations
    - Consistent interface with InMemoryWorkflowStore
    - Gradual migration from direct store usage to protocol-based

    Thread Safety:
        This implementation delegates to underlying Cosmos stores which
        use async operations. Cosmos SDK handles connection pooling.
    """

    def __init__(
        self,
        state_store: WorkflowStateStore,
        consultation_index_store: ConsultationIndexStore,
        booking_index_store: BookingIndexStore,
        consultation_summary_store: ConsultationSummaryStore,
    ) -> None:
        """
        Initialize with required Cosmos DB stores.

        Args:
            state_store: WorkflowStateStore for primary state persistence
            consultation_index_store: ConsultationIndexStore for consultation lookups
            booking_index_store: BookingIndexStore for booking lookups
            consultation_summary_store: ConsultationSummaryStore for post-expiry access
        """
        self._state_store = state_store
        self._consultation_index_store = consultation_index_store
        self._booking_index_store = booking_index_store
        self._consultation_summary_store = consultation_summary_store

    @classmethod
    def from_containers(
        cls,
        workflow_states_container: ContainerProxy,
        consultation_index_container: ContainerProxy,
        booking_index_container: ContainerProxy,
        consultation_summaries_container: ContainerProxy,
    ) -> CosmosWorkflowStore:
        """
        Create CosmosWorkflowStore from Cosmos container clients.

        This factory method creates all required stores from containers,
        useful when initializing from a Cosmos database connection.

        Args:
            workflow_states_container: Container for workflow states
            consultation_index_container: Container for consultation index
            booking_index_container: Container for booking index
            consultation_summaries_container: Container for consultation summaries

        Returns:
            Configured CosmosWorkflowStore instance
        """
        from src.orchestrator.storage.booking_index import BookingIndexStore
        from src.orchestrator.storage.consultation_index import ConsultationIndexStore
        from src.orchestrator.storage.consultation_summaries import (
            ConsultationSummaryStore,
        )
        from src.orchestrator.storage.session_state import WorkflowStateStore

        return cls(
            state_store=WorkflowStateStore(workflow_states_container),
            consultation_index_store=ConsultationIndexStore(consultation_index_container),
            booking_index_store=BookingIndexStore(booking_index_container),
            consultation_summary_store=ConsultationSummaryStore(
                consultation_summaries_container
            ),
        )

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
        from src.orchestrator.models.workflow_state import WorkflowState

        state_data = await self._state_store.get_state(session_id)
        if state_data is None:
            logger.debug(f"Workflow state not found for session {session_id}")
            return None

        # Convert WorkflowStateData to WorkflowState
        # WorkflowStateData stores simplified fields, we need to rebuild full WorkflowState
        state_dict = state_data.to_dict()
        state_dict["_etag"] = state_data.etag
        logger.debug(f"Retrieved workflow state for session {session_id}")
        return WorkflowState.from_dict(state_dict)

    async def get_by_consultation(
        self, consultation_id: str
    ) -> WorkflowState | None:
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
        # Look up session_id via consultation index
        index_entry = await self._consultation_index_store.get_session_for_consultation(
            consultation_id
        )
        if index_entry is None:
            logger.debug(f"Consultation index not found for {consultation_id}")
            return None

        # Get the workflow state
        state = await self.get_by_session(index_entry.session_id)
        if state is None:
            logger.debug(
                f"Workflow state not found for session {index_entry.session_id} "
                f"(consultation {consultation_id})"
            )
            return None

        # Validate workflow_version for identity integrity
        if state.workflow_version != index_entry.workflow_version:
            logger.debug(
                f"Workflow version mismatch for {consultation_id}: "
                f"expected {index_entry.workflow_version}, got {state.workflow_version}"
            )
            return None

        return state

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
        # Look up session_id via booking index
        index_entry = await self._booking_index_store.get_session_for_booking(
            booking_id
        )
        if index_entry is None:
            logger.debug(f"Booking index not found for {booking_id}")
            return None

        return await self.get_by_session(index_entry.session_id)

    async def save(
        self, state: WorkflowState, etag: str | None = None
    ) -> str:
        """
        Persist workflow state with optional optimistic locking.

        Converts WorkflowState to WorkflowStateData for storage and handles
        etag-based optimistic concurrency control.

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
        from src.orchestrator.storage.session_state import WorkflowStateData

        # Convert WorkflowState to WorkflowStateData for storage
        state_data = WorkflowStateData(
            session_id=state.session_id,
            consultation_id=state.consultation_id,
            phase=state.phase.value,
            checkpoint=state.checkpoint,
            current_step=state.current_step,
            itinerary_id=state.itinerary_id,
            workflow_version=state.workflow_version,
            agent_context_ids={
                name: agent_state.to_dict()
                for name, agent_state in state.agent_context_ids.items()
            },
            created_at=state.created_at,
            updated_at=datetime.now(timezone.utc),
            etag=etag,
        )

        # Save via underlying store with optimistic locking
        saved_data = await self._state_store.save_state(state_data, if_match=etag)

        logger.debug(
            f"Saved workflow state for session {state.session_id} "
            f"with etag {saved_data.etag}"
        )
        return saved_data.etag or ""

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
        await self._consultation_index_store.add_session(
            session_id=session_id,
            consultation_id=consultation_id,
            workflow_version=workflow_version,
        )
        logger.debug(
            f"Created consultation index: {consultation_id} -> {session_id} "
            f"(version={workflow_version})"
        )

    async def delete_consultation_index(self, consultation_id: str) -> None:
        """
        Delete consultation index entry on start_new.

        This ensures the old consultation_id returns None rather than
        pointing to the new workflow state.

        Args:
            consultation_id: The consultation identifier to invalidate
        """
        deleted = await self._consultation_index_store.delete_consultation(
            consultation_id
        )
        if deleted:
            logger.debug(f"Deleted consultation index for {consultation_id}")
        else:
            logger.debug(f"Consultation index not found for deletion: {consultation_id}")

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
        trip_end_date: date | None = None,
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
            trip_end_date: Trip end date for TTL calculation
        """
        from src.orchestrator.storage.consultation_summaries import ConsultationSummary

        summary = ConsultationSummary(
            consultation_id=consultation_id,
            session_id=session_id,
            trip_spec_summary=trip_spec_summary,
            itinerary_ids=itinerary_ids or [],
            booking_ids=booking_ids or [],
            status=status,
            trip_end_date=trip_end_date,
        )
        await self._consultation_summary_store.save_summary(summary)
        logger.debug(f"Upserted consultation summary for {consultation_id}")

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
        summary = await self._consultation_summary_store.get_summary(consultation_id)
        if summary is None:
            logger.debug(f"Consultation summary not found for {consultation_id}")
            return None

        logger.debug(f"Retrieved consultation summary for {consultation_id}")
        return summary.to_dict()

    # =========================================================================
    # Booking index operations (for booking resumption)
    # =========================================================================

    async def create_booking_index(
        self,
        booking_id: str,
        session_id: str,
        consultation_id: str,
        trip_end_date: date | None = None,
    ) -> None:
        """
        Create a booking index entry for workflow lookup via booking_id.

        Called when bookings are created.

        Args:
            booking_id: The booking identifier
            session_id: The session identifier to map to
            consultation_id: The consultation identifier
            trip_end_date: Trip end date for TTL calculation
        """
        await self._booking_index_store.add_booking_index(
            booking_id=booking_id,
            consultation_id=consultation_id,
            session_id=session_id,
            trip_end_date=trip_end_date,
        )
        logger.debug(
            f"Created booking index: {booking_id} -> session {session_id}, "
            f"consultation {consultation_id}"
        )

    async def delete_booking_index(self, booking_id: str) -> None:
        """
        Delete booking index entry.

        Args:
            booking_id: The booking identifier to remove
        """
        deleted = await self._booking_index_store.delete_booking_index(booking_id)
        if deleted:
            logger.debug(f"Deleted booking index for {booking_id}")
        else:
            logger.debug(f"Booking index not found for deletion: {booking_id}")
