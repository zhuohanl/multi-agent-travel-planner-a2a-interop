"""
Session manager for workflow state lookup and creation.

This module implements the load_or_create_state function which centralizes
session resumption. It resolves WorkflowState through the session_ref lookup
chain, validates workflow_version for identity integrity, and creates new
sessions when no match exists.

Lookup chain (per design doc):
- session_id: Direct lookup via workflow_states[session_id]
- consultation_id: Via consultation_index + workflow_version validation
- itinerary_id: Itinerary -> consultation_id -> session_id
- booking_id: Booking -> itinerary_id -> consultation_id -> session_id

Key behaviors:
- All lookups validate workflow_version to ensure identity integrity
- Stale consultation_ids return None (not found) after start_new
- New workflows generate consultation_id and index entries
- Cross-session resumption returns original session_id state

Per design doc Compatibility & Migration section:
- Uses WorkflowStoreProtocol for storage-backend agnostic access
- All lookup methods (get_by_session, get_by_consultation, get_by_booking)
  are provided by the unified protocol interface
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.orchestrator.models.session_ref import SessionRef
from src.orchestrator.models.workflow_state import Phase, WorkflowState
from src.orchestrator.utils import generate_consultation_id
from src.shared.storage import WorkflowStoreProtocol

# Legacy imports for backward compatibility
from src.orchestrator.storage import (
    BookingIndexStoreProtocol,
    BookingStoreProtocol,
    ConsultationIndexStoreProtocol,
    ItineraryStoreProtocol,
    WorkflowStateData,
    WorkflowStateStoreProtocol,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class SessionManagerResult:
    """Result of load_or_create_state operation.

    Attributes:
        state: The loaded or created WorkflowState
        is_new: True if a new state was created, False if loaded from storage
        original_session_id: The session_id of the state (may differ from requested
                            session_id if resuming via consultation_id/itinerary_id/booking_id)
    """

    state: WorkflowStateData
    is_new: bool
    original_session_id: str


class SessionManager:
    """Manages workflow state lookup and creation.

    This class encapsulates the lookup chain for resolving WorkflowState
    from various identifiers (session_id, consultation_id, itinerary_id,
    booking_id) and handles new state creation.
    """

    def __init__(
        self,
        workflow_state_store: WorkflowStateStoreProtocol,
        consultation_index_store: ConsultationIndexStoreProtocol,
        itinerary_store: ItineraryStoreProtocol,
        booking_store: BookingStoreProtocol,
        booking_index_store: BookingIndexStoreProtocol,
    ) -> None:
        """Initialize the session manager with required stores.

        Args:
            workflow_state_store: Store for WorkflowState persistence
            consultation_index_store: Store for consultation_id -> session_id lookup
            itinerary_store: Store for Itinerary persistence
            booking_store: Store for Booking persistence
            booking_index_store: Store for booking_id -> session_id lookup
        """
        self._workflow_state_store = workflow_state_store
        self._consultation_index_store = consultation_index_store
        self._itinerary_store = itinerary_store
        self._booking_store = booking_store
        self._booking_index_store = booking_index_store

    async def load_or_create_state(
        self,
        session_ref: SessionRef,
        new_session_id: str,
    ) -> SessionManagerResult:
        """Load existing workflow state or create a new one.

        This is the primary entry point for session management. It follows
        the lookup chain to resolve a WorkflowState:

        1. session_id: Direct lookup
        2. consultation_id: Via index with version validation
        3. itinerary_id: Itinerary -> consultation_id -> session_id
        4. booking_id: Booking -> itinerary_id -> consultation_id -> session_id

        If no state is found via any lookup path, a new state is created
        with the new_session_id.

        Args:
            session_ref: Reference containing one or more IDs to lookup
            new_session_id: Session ID to use when creating new state

        Returns:
            SessionManagerResult with state, is_new flag, and original_session_id
        """
        # Try lookup via each ID in the hierarchy
        state = await self._lookup_state(session_ref)

        if state is not None:
            logger.info(
                f"Loaded existing workflow state for session {state.session_id} "
                f"(via {self._describe_lookup_path(session_ref)})"
            )
            return SessionManagerResult(
                state=state,
                is_new=False,
                original_session_id=state.session_id,
            )

        # No existing state found - create new one
        logger.info(f"Creating new workflow state with session_id={new_session_id}")
        new_state = await self._create_new_state(new_session_id)

        return SessionManagerResult(
            state=new_state,
            is_new=True,
            original_session_id=new_session_id,
        )

    async def _lookup_state(self, session_ref: SessionRef) -> WorkflowStateData | None:
        """Attempt to find existing state via the lookup chain.

        The lookup chain tries IDs in priority order:
        1. session_id - Direct lookup
        2. consultation_id - Via index with version validation
        3. itinerary_id - Via itinerary -> consultation_id -> session_id
        4. booking_id - Via booking -> itinerary_id -> consultation_id -> session_id

        Args:
            session_ref: Reference containing one or more IDs

        Returns:
            WorkflowStateData if found and valid, None otherwise
        """
        # 1. Try session_id (direct lookup)
        if session_ref.session_id:
            state = await self._lookup_by_session_id(session_ref.session_id)
            if state is not None:
                return state

        # 2. Try consultation_id (via index with version validation)
        if session_ref.consultation_id:
            state = await self._lookup_by_consultation_id(session_ref.consultation_id)
            if state is not None:
                return state

        # 3. Try itinerary_id (via itinerary -> consultation_id -> session_id)
        if session_ref.itinerary_id:
            state = await self._lookup_by_itinerary_id(session_ref.itinerary_id)
            if state is not None:
                return state

        # 4. Try booking_id (via booking -> itinerary_id -> consultation_id -> session_id)
        if session_ref.booking_id:
            state = await self._lookup_by_booking_id(session_ref.booking_id)
            if state is not None:
                return state

        return None

    async def _lookup_by_session_id(self, session_id: str) -> WorkflowStateData | None:
        """Direct lookup by session_id.

        Args:
            session_id: The session identifier

        Returns:
            WorkflowStateData if found, None otherwise
        """
        logger.debug(f"Looking up state by session_id: {session_id}")
        return await self._workflow_state_store.get_state(session_id)

    async def _lookup_by_consultation_id(
        self, consultation_id: str
    ) -> WorkflowStateData | None:
        """Lookup by consultation_id via index with version validation.

        Per design doc, the lookup includes version validation to ensure
        identity integrity. If a user calls start_new, the old consultation_id's
        index entry is deleted, so lookups return None rather than the new
        workflow state.

        Args:
            consultation_id: The consultation identifier

        Returns:
            WorkflowStateData if found and version matches, None otherwise
        """
        logger.debug(f"Looking up state by consultation_id: {consultation_id}")

        # Get index entry
        index_entry = await self._consultation_index_store.get_session_for_consultation(
            consultation_id
        )
        if index_entry is None:
            logger.debug(f"No index entry found for consultation_id: {consultation_id}")
            return None

        # Get state by session_id from index
        state = await self._workflow_state_store.get_state(index_entry.session_id)
        if state is None:
            logger.debug(
                f"State not found for session_id {index_entry.session_id} "
                f"(from consultation_id {consultation_id})"
            )
            return None

        # Validate workflow_version matches (identity integrity check)
        if state.workflow_version != index_entry.workflow_version:
            logger.warning(
                f"Workflow version mismatch for consultation_id {consultation_id}: "
                f"index has version {index_entry.workflow_version}, "
                f"state has version {state.workflow_version}. "
                "Returning None (stale consultation_id)."
            )
            return None

        return state

    async def _lookup_by_itinerary_id(
        self, itinerary_id: str
    ) -> WorkflowStateData | None:
        """Lookup by itinerary_id via itinerary -> consultation_id -> session_id.

        Args:
            itinerary_id: The itinerary identifier

        Returns:
            WorkflowStateData if found and valid, None otherwise
        """
        logger.debug(f"Looking up state by itinerary_id: {itinerary_id}")

        # Get itinerary
        itinerary = await self._itinerary_store.get_itinerary(itinerary_id)
        if itinerary is None:
            logger.debug(f"Itinerary not found: {itinerary_id}")
            return None

        # Continue lookup via consultation_id
        return await self._lookup_by_consultation_id(itinerary.consultation_id)

    async def _lookup_by_booking_id(self, booking_id: str) -> WorkflowStateData | None:
        """Lookup by booking_id via booking -> itinerary_id -> consultation_id -> session_id.

        For efficiency, we first try the booking_index (direct lookup).
        If that fails or returns stale data, we fall back to the full chain.

        Args:
            booking_id: The booking identifier

        Returns:
            WorkflowStateData if found and valid, None otherwise
        """
        logger.debug(f"Looking up state by booking_id: {booking_id}")

        # First try booking_index (O(1) lookup)
        booking_index_entry = await self._booking_index_store.get_session_for_booking(
            booking_id
        )
        if booking_index_entry is not None:
            # Try to get state via the indexed session_id
            # Still need to validate via consultation_index for version integrity
            state = await self._lookup_by_consultation_id(
                booking_index_entry.consultation_id
            )
            if state is not None:
                return state
            # Index entry exists but state lookup failed - fall through to full chain

        # Fall back to full chain: booking -> itinerary -> consultation -> session
        booking = await self._booking_store.get_booking(booking_id)
        if booking is None:
            logger.debug(f"Booking not found: {booking_id}")
            return None

        # Continue lookup via itinerary_id
        return await self._lookup_by_itinerary_id(booking.itinerary_id)

    async def _create_new_state(self, session_id: str) -> WorkflowStateData:
        """Create a new workflow state with consultation_id and index entry.

        Per design doc:
        - Generate consultation_id when Phase 1 (planning) starts
        - Create index entry for cross-session resumption
        - Initialize state in CLARIFICATION phase

        Args:
            session_id: The session identifier for the new state

        Returns:
            The newly created and persisted WorkflowStateData
        """
        # Generate consultation_id
        consultation_id = generate_consultation_id()

        # Create new state
        new_state = WorkflowStateData(
            session_id=session_id,
            consultation_id=consultation_id,
            phase="CLARIFICATION",
            workflow_version=1,
        )

        # Save state to workflow_state_store
        saved_state = await self._workflow_state_store.save_state(new_state)

        # Create consultation_index entry for cross-session resumption
        await self._consultation_index_store.add_session(
            session_id=session_id,
            consultation_id=consultation_id,
            workflow_version=1,
        )

        logger.info(
            f"Created new workflow state: session_id={session_id}, "
            f"consultation_id={consultation_id}"
        )

        return saved_state

    def _describe_lookup_path(self, session_ref: SessionRef) -> str:
        """Describe which lookup path was used for logging.

        Args:
            session_ref: The session reference used for lookup

        Returns:
            Human-readable description of the lookup path
        """
        if session_ref.session_id:
            return f"session_id={session_ref.session_id}"
        if session_ref.consultation_id:
            return f"consultation_id={session_ref.consultation_id}"
        if session_ref.itinerary_id:
            return f"itinerary_id={session_ref.itinerary_id}"
        if session_ref.booking_id:
            return f"booking_id={session_ref.booking_id}"
        return "no identifier"


async def load_or_create_state(
    session_ref: SessionRef,
    new_session_id: str,
    workflow_state_store: WorkflowStateStoreProtocol,
    consultation_index_store: ConsultationIndexStoreProtocol,
    itinerary_store: ItineraryStoreProtocol,
    booking_store: BookingStoreProtocol,
    booking_index_store: BookingIndexStoreProtocol,
) -> SessionManagerResult:
    """Convenience function for load_or_create_state.

    Creates a SessionManager instance and calls load_or_create_state.
    For repeated operations, prefer creating a SessionManager directly.

    Args:
        session_ref: Reference containing one or more IDs to lookup
        new_session_id: Session ID to use when creating new state
        workflow_state_store: Store for WorkflowState persistence
        consultation_index_store: Store for consultation_id -> session_id lookup
        itinerary_store: Store for Itinerary persistence
        booking_store: Store for Booking persistence
        booking_index_store: Store for booking_id -> session_id lookup

    Returns:
        SessionManagerResult with state, is_new flag, and original_session_id
    """
    manager = SessionManager(
        workflow_state_store=workflow_state_store,
        consultation_index_store=consultation_index_store,
        itinerary_store=itinerary_store,
        booking_store=booking_store,
        booking_index_store=booking_index_store,
    )
    return await manager.load_or_create_state(session_ref, new_session_id)


# =============================================================================
# Unified Session Manager (using WorkflowStoreProtocol)
# =============================================================================


@dataclass
class UnifiedSessionManagerResult:
    """Result of unified load_or_create_state operation.

    Uses WorkflowState (rich domain model) instead of WorkflowStateData.

    Attributes:
        state: The loaded or created WorkflowState (rich domain model)
        is_new: True if a new state was created, False if loaded from storage
        original_session_id: The session_id of the state (may differ from requested
                            session_id if resuming via consultation_id/booking_id)
        etag: The etag for optimistic locking (if loaded from storage)
    """

    state: WorkflowState
    is_new: bool
    original_session_id: str
    etag: str | None = None


class UnifiedSessionManager:
    """Manages workflow state lookup and creation using WorkflowStoreProtocol.

    This class uses the unified WorkflowStoreProtocol interface which provides
    all lookup methods (get_by_session, get_by_consultation, get_by_booking)
    and index operations in a single interface.

    Per design doc Compatibility & Migration section:
    - Uses WorkflowStoreProtocol for storage-backend agnostic access
    - STORAGE_BACKEND env var controls backend selection at runtime
    - All orchestrator code depends only on protocols, not implementations
    """

    def __init__(self, workflow_store: WorkflowStoreProtocol) -> None:
        """Initialize the unified session manager.

        Args:
            workflow_store: WorkflowStoreProtocol instance (created via
                           create_workflow_store() factory)
        """
        self._workflow_store = workflow_store

    async def load_or_create_state(
        self,
        session_ref: SessionRef,
        new_session_id: str,
    ) -> UnifiedSessionManagerResult:
        """Load existing workflow state or create a new one.

        Uses WorkflowStoreProtocol's unified lookup methods:
        - get_by_session: Primary lookup (O(1))
        - get_by_consultation: Cross-session resumption with version validation
        - get_by_booking: Booking resumption lookup

        If no state is found via any lookup path, a new state is created
        with the new_session_id.

        Args:
            session_ref: Reference containing one or more IDs to lookup
            new_session_id: Session ID to use when creating new state

        Returns:
            UnifiedSessionManagerResult with state, is_new flag, and original_session_id
        """
        # Try lookup via each ID in the hierarchy
        state = await self._lookup_state(session_ref)

        if state is not None:
            logger.info(
                f"Loaded existing workflow state for session {state.session_id} "
                f"(via {self._describe_lookup_path(session_ref)})"
            )
            return UnifiedSessionManagerResult(
                state=state,
                is_new=False,
                original_session_id=state.session_id,
                etag=state.etag,
            )

        # No existing state found - create new one
        logger.info(f"Creating new workflow state with session_id={new_session_id}")
        new_state, etag = await self._create_new_state(new_session_id)

        return UnifiedSessionManagerResult(
            state=new_state,
            is_new=True,
            original_session_id=new_session_id,
            etag=etag,
        )

    async def _lookup_state(self, session_ref: SessionRef) -> WorkflowState | None:
        """Attempt to find existing state via the lookup chain.

        Uses WorkflowStoreProtocol's unified methods:
        1. get_by_session - Direct lookup (primary path)
        2. get_by_consultation - Cross-session resumption with version validation
        3. get_by_booking - Booking resumption lookup

        Note: itinerary_id lookup is handled internally by get_by_consultation
        via the consultation_id extracted from the itinerary.

        Args:
            session_ref: Reference containing one or more IDs

        Returns:
            WorkflowState if found and valid, None otherwise
        """
        # 1. Try session_id (direct lookup, O(1))
        if session_ref.session_id:
            state = await self._workflow_store.get_by_session(session_ref.session_id)
            if state is not None:
                return state

        # 2. Try consultation_id (includes version validation)
        if session_ref.consultation_id:
            state = await self._workflow_store.get_by_consultation(
                session_ref.consultation_id
            )
            if state is not None:
                return state

        # 3. Try booking_id (booking resumption)
        if session_ref.booking_id:
            state = await self._workflow_store.get_by_booking(session_ref.booking_id)
            if state is not None:
                return state

        # 4. itinerary_id lookup would require itinerary_store
        # For now, this is handled separately if needed
        # The unified protocol could be extended to include itinerary lookup

        return None

    async def _create_new_state(
        self, session_id: str
    ) -> tuple[WorkflowState, str]:
        """Create a new workflow state with consultation_id and index entry.

        Per design doc:
        - Generate consultation_id when Phase 1 (planning) starts
        - Create index entry for cross-session resumption
        - Initialize state in CLARIFICATION phase

        Args:
            session_id: The session identifier for the new state

        Returns:
            Tuple of (newly created WorkflowState, etag)
        """
        # Generate consultation_id
        consultation_id = generate_consultation_id()

        # Create new state
        now = datetime.now(timezone.utc)
        new_state = WorkflowState(
            session_id=session_id,
            consultation_id=consultation_id,
            workflow_version=1,
            phase=Phase.CLARIFICATION,
            checkpoint=None,
            current_step="gathering",
            created_at=now,
            updated_at=now,
        )

        # Save state to workflow_store and get etag
        etag = await self._workflow_store.save(new_state)
        new_state.etag = etag

        # Create consultation_index entry for cross-session resumption
        await self._workflow_store.create_consultation_index(
            consultation_id=consultation_id,
            session_id=session_id,
            workflow_version=1,
        )

        logger.info(
            f"Created new workflow state: session_id={session_id}, "
            f"consultation_id={consultation_id}"
        )

        return new_state, etag

    def _describe_lookup_path(self, session_ref: SessionRef) -> str:
        """Describe which lookup path was used for logging.

        Args:
            session_ref: The session reference used for lookup

        Returns:
            Human-readable description of the lookup path
        """
        if session_ref.session_id:
            return f"session_id={session_ref.session_id}"
        if session_ref.consultation_id:
            return f"consultation_id={session_ref.consultation_id}"
        if session_ref.itinerary_id:
            return f"itinerary_id={session_ref.itinerary_id}"
        if session_ref.booking_id:
            return f"booking_id={session_ref.booking_id}"
        return "no identifier"


async def unified_load_or_create_state(
    session_ref: SessionRef,
    new_session_id: str,
    workflow_store: WorkflowStoreProtocol,
) -> UnifiedSessionManagerResult:
    """Convenience function for unified load_or_create_state.

    Creates a UnifiedSessionManager instance and calls load_or_create_state.
    For repeated operations, prefer creating a UnifiedSessionManager directly.

    Args:
        session_ref: Reference containing one or more IDs to lookup
        new_session_id: Session ID to use when creating new state
        workflow_store: WorkflowStoreProtocol instance (from create_workflow_store())

    Returns:
        UnifiedSessionManagerResult with state, is_new flag, original_session_id, and etag
    """
    manager = UnifiedSessionManager(workflow_store=workflow_store)
    return await manager.load_or_create_state(session_ref, new_session_id)
