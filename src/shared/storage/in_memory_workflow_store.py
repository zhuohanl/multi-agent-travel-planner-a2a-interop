"""
In-memory implementation of WorkflowStoreProtocol for development and testing.

This module provides an InMemoryWorkflowStore that implements the full
WorkflowStoreProtocol interface using in-memory dictionaries.

Per design doc Compatibility & Migration section:
- Enables local development without Cosmos DB
- Enables unit tests to run without external dependencies
- Interface-compatible with CosmosWorkflowStore for production

Usage:
    from src.shared.storage.in_memory_workflow_store import InMemoryWorkflowStore

    store = InMemoryWorkflowStore()
    await store.save(workflow_state)
    state = await store.get_by_session("sess_abc123")
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.orchestrator.models.workflow_state import WorkflowState

logger = logging.getLogger(__name__)


class ConflictError(Exception):
    """
    Raised when optimistic locking fails due to concurrent modification.

    This mirrors the ConflictError from session_state.py for consistency.
    """

    def __init__(self, session_id: str, message: str | None = None):
        self.session_id = session_id
        super().__init__(
            message or f"Concurrent modification detected for session {session_id}"
        )


class InMemoryWorkflowStore:
    """
    In-memory implementation of WorkflowStoreProtocol.

    Stores workflow state, consultation index, booking index, and
    consultation summaries in dictionaries. Supports optimistic locking
    via etag simulation.

    This implementation is designed for:
    - Unit tests (no external dependencies)
    - Local development (no Cosmos DB required)
    - Integration tests with mocked data

    Thread Safety:
        This implementation is NOT thread-safe. For concurrent access,
        use proper synchronization or the CosmosWorkflowStore.
    """

    def __init__(self) -> None:
        """Initialize empty in-memory stores."""
        # Primary state storage: session_id -> WorkflowState dict
        self._states: dict[str, dict[str, Any]] = {}

        # Consultation index: consultation_id -> {session_id, workflow_version}
        self._consultation_index: dict[str, dict[str, Any]] = {}

        # Booking index: booking_id -> {session_id, consultation_id}
        self._booking_index: dict[str, dict[str, Any]] = {}

        # Consultation summaries: consultation_id -> summary dict
        self._consultation_summaries: dict[str, dict[str, Any]] = {}

        # Etag counter for optimistic locking simulation
        self._etag_counter = 0

    # =========================================================================
    # Primary state operations
    # =========================================================================

    async def get_by_session(self, session_id: str) -> WorkflowState | None:
        """
        Retrieve workflow state by session_id (primary lookup).

        Args:
            session_id: The session identifier

        Returns:
            WorkflowState if found, None if not found
        """
        from src.orchestrator.models.workflow_state import WorkflowState

        if session_id not in self._states:
            logger.debug(f"Workflow state not found for session {session_id}")
            return None

        state_dict = self._states[session_id]
        logger.debug(f"Retrieved workflow state for session {session_id}")
        return WorkflowState.from_dict(state_dict)

    async def get_by_consultation(
        self, consultation_id: str
    ) -> WorkflowState | None:
        """
        Retrieve workflow state by consultation_id (cross-session lookup).

        Uses consultation_index for reverse lookup and validates
        workflow_version for identity integrity.

        Args:
            consultation_id: The consultation identifier

        Returns:
            WorkflowState if found and valid, None otherwise
        """
        # Look up session_id via consultation index
        index_entry = self._consultation_index.get(consultation_id)
        if not index_entry:
            logger.debug(f"Consultation index not found for {consultation_id}")
            return None

        session_id = index_entry.get("session_id")
        if not session_id:
            logger.debug(f"No session_id in consultation index for {consultation_id}")
            return None

        # Get the workflow state
        state = await self.get_by_session(session_id)
        if not state:
            logger.debug(
                f"Workflow state not found for session {session_id} "
                f"(consultation {consultation_id})"
            )
            return None

        # Validate workflow_version for identity integrity
        expected_version = index_entry.get("workflow_version", 1)
        if state.workflow_version != expected_version:
            logger.debug(
                f"Workflow version mismatch for {consultation_id}: "
                f"expected {expected_version}, got {state.workflow_version}"
            )
            return None

        return state

    async def get_by_booking(self, booking_id: str) -> WorkflowState | None:
        """
        Retrieve workflow state by booking_id (booking resumption lookup).

        Uses booking_index for reverse lookup.

        Args:
            booking_id: The booking identifier

        Returns:
            WorkflowState if found, None otherwise
        """
        # Look up session_id via booking index
        index_entry = self._booking_index.get(booking_id)
        if not index_entry:
            logger.debug(f"Booking index not found for {booking_id}")
            return None

        session_id = index_entry.get("session_id")
        if not session_id:
            logger.debug(f"No session_id in booking index for {booking_id}")
            return None

        return await self.get_by_session(session_id)

    async def save(
        self, state: WorkflowState, etag: str | None = None
    ) -> str:
        """
        Persist workflow state with optional optimistic locking.

        Args:
            state: The WorkflowState to save
            etag: Optional etag for optimistic locking

        Returns:
            Updated etag value for subsequent saves

        Raises:
            ConflictError: If etag is provided and doesn't match
        """
        session_id = state.session_id
        existing = self._states.get(session_id)

        # Check etag for optimistic locking
        if etag and existing:
            existing_etag = existing.get("_etag")
            if existing_etag != etag:
                logger.warning(
                    f"Conflict detected saving workflow state for session {session_id}"
                )
                raise ConflictError(session_id)

        # Update timestamp
        state.updated_at = datetime.now(timezone.utc)

        # Generate new etag
        self._etag_counter += 1
        new_etag = f"etag_{self._etag_counter}_{uuid.uuid4().hex[:8]}"

        # Serialize and store
        state_dict = state.to_dict()
        state_dict["_etag"] = new_etag
        self._states[session_id] = state_dict

        logger.debug(f"Saved workflow state for session {session_id} with etag {new_etag}")
        return new_etag

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

        Args:
            consultation_id: The consultation identifier
            session_id: The session identifier to map to
            workflow_version: Workflow version for identity integrity
        """
        self._consultation_index[consultation_id] = {
            "consultation_id": consultation_id,
            "session_id": session_id,
            "workflow_version": workflow_version,
        }
        logger.debug(
            f"Created consultation index: {consultation_id} -> {session_id} "
            f"(version={workflow_version})"
        )

    async def delete_consultation_index(self, consultation_id: str) -> None:
        """
        Delete consultation index entry on start_new.

        Args:
            consultation_id: The consultation identifier to invalidate
        """
        if consultation_id in self._consultation_index:
            del self._consultation_index[consultation_id]
            logger.debug(f"Deleted consultation index for {consultation_id}")
        else:
            logger.debug(f"Consultation index not found for deletion: {consultation_id}")

    # =========================================================================
    # Consultation summary operations
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
        Create or update consultation summary.

        Args:
            consultation_id: The consultation identifier
            session_id: The session identifier
            trip_spec_summary: Minimal snapshot (destination, dates, travelers)
            itinerary_ids: List of itinerary IDs
            booking_ids: List of booking IDs
            status: Current status
        """
        now = datetime.now(timezone.utc).isoformat()
        existing = self._consultation_summaries.get(consultation_id)

        self._consultation_summaries[consultation_id] = {
            "consultation_id": consultation_id,
            "session_id": session_id,
            "trip_spec_summary": trip_spec_summary,
            "itinerary_ids": itinerary_ids or [],
            "booking_ids": booking_ids or [],
            "status": status,
            "created_at": existing.get("created_at", now) if existing else now,
            "updated_at": now,
        }
        logger.debug(f"Upserted consultation summary for {consultation_id}")

    async def get_consultation_summary(
        self, consultation_id: str
    ) -> dict[str, Any] | None:
        """
        Retrieve consultation summary by consultation_id.

        Args:
            consultation_id: The consultation identifier

        Returns:
            Summary dict if found, None otherwise
        """
        summary = self._consultation_summaries.get(consultation_id)
        if summary:
            logger.debug(f"Retrieved consultation summary for {consultation_id}")
        else:
            logger.debug(f"Consultation summary not found for {consultation_id}")
        return summary

    # =========================================================================
    # Booking index operations
    # =========================================================================

    async def create_booking_index(
        self,
        booking_id: str,
        session_id: str,
        consultation_id: str,
    ) -> None:
        """
        Create a booking index entry for workflow lookup via booking_id.

        Args:
            booking_id: The booking identifier
            session_id: The session identifier to map to
            consultation_id: The consultation identifier
        """
        self._booking_index[booking_id] = {
            "booking_id": booking_id,
            "session_id": session_id,
            "consultation_id": consultation_id,
        }
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
        if booking_id in self._booking_index:
            del self._booking_index[booking_id]
            logger.debug(f"Deleted booking index for {booking_id}")
        else:
            logger.debug(f"Booking index not found for deletion: {booking_id}")

    # =========================================================================
    # Testing utilities
    # =========================================================================

    def clear(self) -> None:
        """Clear all stored data (for test cleanup)."""
        self._states.clear()
        self._consultation_index.clear()
        self._booking_index.clear()
        self._consultation_summaries.clear()
        self._etag_counter = 0
        logger.debug("Cleared all in-memory workflow store data")

    def get_state_count(self) -> int:
        """Get the number of workflow states stored (for testing)."""
        return len(self._states)

    def get_consultation_index_count(self) -> int:
        """Get the number of consultation index entries (for testing)."""
        return len(self._consultation_index)

    def get_booking_index_count(self) -> int:
        """Get the number of booking index entries (for testing)."""
        return len(self._booking_index)

    def get_summary_count(self) -> int:
        """Get the number of consultation summaries (for testing)."""
        return len(self._consultation_summaries)
