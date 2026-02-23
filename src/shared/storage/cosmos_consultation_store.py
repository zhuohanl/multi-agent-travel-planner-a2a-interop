"""
CosmosConsultationStore adapter for the shared ConsultationStore interface.

This module implements the ConsultationStore interface by delegating to
the orchestrator's Cosmos DB containers:
- consultation_index: Maps consultation_id → session_id
- consultation_summaries: Stores post-expiry access data
- booking_index: Maps booking_id → consultation_id (for get_by_booking)

Per design doc Compatibility & Migration section:
- Extends shared ConsultationStore interface with Cosmos-backed implementation
- Uses orchestrator containers for persistence
- Respects canonical id/consultation_id naming conventions
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from ..models import Consultation, ConsultationStatus
from .consultation_store import ConsultationStore

if TYPE_CHECKING:
    from src.orchestrator.storage.booking_index import (
        BookingIndexStore,
        BookingIndexStoreProtocol,
    )
    from src.orchestrator.storage.consultation_index import (
        ConsultationIndexStore,
        ConsultationIndexStoreProtocol,
    )
    from src.orchestrator.storage.consultation_summaries import (
        ConsultationSummary,
        ConsultationSummaryStore,
        ConsultationSummaryStoreProtocol,
    )

logger = logging.getLogger(__name__)


class CosmosConsultationStore(ConsultationStore):
    """
    Cosmos DB implementation of ConsultationStore.

    Implements the shared ConsultationStore interface by composing
    orchestrator Cosmos containers:
    - consultation_index: For session/consultation lookups
    - consultation_summaries: For consultation data persistence
    - booking_index: For booking → consultation lookups

    This adapter bridges the legacy ConsultationStore interface with
    the new orchestrator Cosmos DB architecture.
    """

    def __init__(
        self,
        consultation_index_store: ConsultationIndexStoreProtocol | ConsultationIndexStore,
        consultation_summary_store: ConsultationSummaryStoreProtocol | ConsultationSummaryStore,
        booking_index_store: BookingIndexStoreProtocol | BookingIndexStore | None = None,
    ) -> None:
        """
        Initialize with orchestrator storage dependencies.

        Args:
            consultation_index_store: Store for consultation_id → session_id mapping
            consultation_summary_store: Store for consultation summary data
            booking_index_store: Optional store for booking_id → consultation_id mapping
                                (required for get_by_booking support)
        """
        self._index_store = consultation_index_store
        self._summary_store = consultation_summary_store
        self._booking_index_store = booking_index_store

        # In-memory consultation objects (ephemeral, not persisted)
        # The actual persistence is via index and summary stores
        self._consultations: dict[str, Consultation] = {}
        self._session_to_consultation: dict[str, str] = {}

    async def create(self, session_id: str, ttl_days: int = 7) -> Consultation:
        """
        Create a new consultation for a session.

        Creates both the in-memory Consultation object and the
        consultation_index entry for lookup.

        Args:
            session_id: Session ID to associate with the consultation.
            ttl_days: Time-to-live in days for the consultation.

        Returns:
            Newly created Consultation with generated ID.
        """
        import uuid

        now = datetime.now(timezone.utc)
        consultation_id = f"cons_{uuid.uuid4().hex[:12]}"

        consultation = Consultation(
            id=consultation_id,
            session_id=session_id,
            status=ConsultationStatus.DRAFT,
            created_at=now,
            expires_at=now + timedelta(days=ttl_days),
        )

        # Store locally
        self._consultations[consultation_id] = consultation
        self._session_to_consultation[session_id] = consultation_id

        # Create index entry for lookup
        await self._index_store.add_session(
            session_id=session_id,
            consultation_id=consultation_id,
            workflow_version=1,
        )

        logger.debug(f"Created consultation {consultation_id} for session {session_id}")
        return consultation

    async def get(self, consultation_id: str) -> Consultation | None:
        """
        Get a consultation by ID.

        First checks local cache, then falls back to summary store
        for post-expiry access.

        Args:
            consultation_id: Unique identifier for the consultation.

        Returns:
            Consultation if found, None otherwise.
        """
        # Check local cache first
        if consultation_id in self._consultations:
            return self._consultations[consultation_id]

        # Fall back to summary store for post-expiry access
        summary = await self._summary_store.get_summary(consultation_id)
        if summary is None:
            return None

        # Reconstruct Consultation from summary
        consultation = self._consultation_from_summary(summary)
        self._consultations[consultation_id] = consultation
        return consultation

    async def get_by_session(self, session_id: str) -> Consultation | None:
        """
        Get the active consultation for a session.

        Uses consultation_index for lookup:
        session_id → consultation_index → consultation_id → Consultation

        Args:
            session_id: Session ID to look up.

        Returns:
            Active consultation if found, None otherwise.
        """
        # Check local cache first
        if session_id in self._session_to_consultation:
            consultation_id = self._session_to_consultation[session_id]
            consultation = self._consultations.get(consultation_id)
            if consultation and consultation.status not in (
                ConsultationStatus.EXPIRED,
                ConsultationStatus.CANCELLED,
                ConsultationStatus.ARCHIVED,
            ):
                return consultation

        # Look up in index store
        index_entry = await self._index_store.get_session_for_consultation(session_id)
        if index_entry is None:
            # Try reverse lookup: iterate through index to find by session
            # This is a limitation of the current index design
            # For now, return None if not in cache
            return None

        # Get consultation using the mapped consultation_id
        return await self.get(index_entry.consultation_id)

    async def update(self, consultation: Consultation) -> Consultation:
        """
        Update an existing consultation.

        Args:
            consultation: Consultation with updated fields.

        Returns:
            Updated consultation.

        Raises:
            KeyError: If consultation does not exist.
        """
        if consultation.id not in self._consultations:
            # Check if it exists in storage
            existing = await self.get(consultation.id)
            if existing is None:
                raise KeyError(f"Consultation {consultation.id} not found")

        # Update local cache
        self._consultations[consultation.id] = consultation

        logger.debug(f"Updated consultation {consultation.id}")
        return consultation

    async def mark_expired(self, consultation_id: str) -> Consultation | None:
        """
        Mark a consultation as expired.

        Args:
            consultation_id: ID of the consultation to mark expired.

        Returns:
            Updated consultation if found, None otherwise.
        """
        consultation = await self.get(consultation_id)
        if not consultation:
            return None

        consultation.status = ConsultationStatus.EXPIRED
        self._consultations[consultation_id] = consultation

        logger.debug(f"Marked consultation {consultation_id} as expired")
        return consultation

    async def get_by_booking(self, booking_id: str) -> Consultation | None:
        """
        Get the consultation associated with a booking.

        Uses booking_index for lookup:
        booking_id → booking_index → consultation_id → Consultation

        Args:
            booking_id: Booking ID to look up.

        Returns:
            Consultation if found, None otherwise.
        """
        if self._booking_index_store is None:
            logger.warning("get_by_booking called but booking_index_store not configured")
            return None

        # Look up booking in index to get consultation_id
        index_entry = await self._booking_index_store.get_session_for_booking(booking_id)
        if index_entry is None:
            logger.debug(f"No booking index entry for booking_id={booking_id}")
            return None

        # Get consultation using the mapped consultation_id
        return await self.get(index_entry.consultation_id)

    def _consultation_from_summary(
        self, summary: ConsultationSummary | Any
    ) -> Consultation:
        """
        Reconstruct a Consultation object from a ConsultationSummary.

        This is used for post-expiry read access.

        Args:
            summary: ConsultationSummary from the summary store

        Returns:
            Consultation object (may have limited data)
        """
        # Handle both ConsultationSummary dataclass and dict
        if hasattr(summary, "consultation_id"):
            consultation_id = summary.consultation_id
            session_id = summary.session_id
            status_str = summary.status
            created_at = summary.created_at
        else:
            consultation_id = summary.get("consultation_id", summary.get("id", ""))
            session_id = summary.get("session_id", "")
            status_str = summary.get("status", "active")
            created_at_str = summary.get("created_at")
            if isinstance(created_at_str, str):
                created_at = datetime.fromisoformat(created_at_str)
            else:
                created_at = created_at_str or datetime.now(timezone.utc)

        # Map status string to enum
        # Note: Summary status strings may differ from ConsultationStatus values
        status_map = {
            "active": ConsultationStatus.PLANNING,
            "draft": ConsultationStatus.DRAFT,
            "completed": ConsultationStatus.FULLY_BOOKED,
            "fully_booked": ConsultationStatus.FULLY_BOOKED,
            "cancelled": ConsultationStatus.CANCELLED,
            "expired": ConsultationStatus.EXPIRED,
            "archived": ConsultationStatus.ARCHIVED,
        }
        status = status_map.get(status_str, ConsultationStatus.DRAFT)

        return Consultation(
            id=consultation_id,
            session_id=session_id,
            status=status,
            created_at=created_at,
            expires_at=created_at + timedelta(days=7),  # Default expiry
        )
