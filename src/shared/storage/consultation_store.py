"""Consultation storage abstraction and implementations."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
import uuid

from ..models import Consultation, ConsultationStatus

if TYPE_CHECKING:
    from .booking_store import BookingStore


class ConsultationStore(ABC):
    """Abstract base class for consultation storage."""

    @abstractmethod
    async def create(self, session_id: str, ttl_days: int = 7) -> Consultation:
        """Create a new consultation for a session.

        Args:
            session_id: Session ID to associate with the consultation.
            ttl_days: Time-to-live in days for the consultation.

        Returns:
            Newly created Consultation with generated ID.
        """
        pass

    @abstractmethod
    async def get(self, consultation_id: str) -> Consultation | None:
        """Get a consultation by ID.

        Args:
            consultation_id: Unique identifier for the consultation.

        Returns:
            Consultation if found, None otherwise.
        """
        pass

    @abstractmethod
    async def get_by_session(self, session_id: str) -> Consultation | None:
        """Get the active consultation for a session.

        Args:
            session_id: Session ID to look up.

        Returns:
            Active consultation if found, None otherwise.
        """
        pass

    @abstractmethod
    async def update(self, consultation: Consultation) -> Consultation:
        """Update an existing consultation.

        Args:
            consultation: Consultation with updated fields.

        Returns:
            Updated consultation.

        Raises:
            KeyError: If consultation does not exist.
        """
        pass

    @abstractmethod
    async def mark_expired(self, consultation_id: str) -> Consultation | None:
        """Mark a consultation as expired.

        Args:
            consultation_id: ID of the consultation to mark expired.

        Returns:
            Updated consultation if found, None otherwise.
        """
        pass

    @abstractmethod
    async def get_by_booking(self, booking_id: str) -> Consultation | None:
        """Get the consultation associated with a booking.

        This enables workflow resumption via booking_id by:
        booking_id -> consultation_id -> session_id -> WorkflowState

        Args:
            booking_id: Booking ID to look up.

        Returns:
            Consultation if found, None otherwise.
        """
        pass


class InMemoryConsultationStore(ConsultationStore):
    """In-memory implementation of ConsultationStore for development/testing."""

    def __init__(self, booking_store: BookingStore | None = None) -> None:
        self._consultations: dict[str, Consultation] = {}
        self._session_index: dict[str, str] = {}  # session_id -> consultation_id
        self._booking_store = booking_store

    def _generate_id(self) -> str:
        """Generate a consultation ID with 'cons_' prefix."""
        return f"cons_{uuid.uuid4().hex[:12]}"

    async def create(self, session_id: str, ttl_days: int = 7) -> Consultation:
        """Create a new consultation for a session."""
        now = datetime.now(timezone.utc)
        consultation = Consultation(
            id=self._generate_id(),
            session_id=session_id,
            status=ConsultationStatus.DRAFT,
            created_at=now,
            expires_at=now + timedelta(days=ttl_days),
        )
        self._consultations[consultation.id] = consultation
        self._session_index[session_id] = consultation.id
        return consultation

    async def get(self, consultation_id: str) -> Consultation | None:
        """Get a consultation by ID."""
        return self._consultations.get(consultation_id)

    async def get_by_session(self, session_id: str) -> Consultation | None:
        """Get the active consultation for a session."""
        consultation_id = self._session_index.get(session_id)
        if consultation_id:
            consultation = self._consultations.get(consultation_id)
            if consultation and consultation.status not in (
                ConsultationStatus.EXPIRED,
                ConsultationStatus.CANCELLED,
                ConsultationStatus.ARCHIVED,
            ):
                return consultation
        return None

    async def update(self, consultation: Consultation) -> Consultation:
        """Update an existing consultation."""
        if consultation.id not in self._consultations:
            raise KeyError(f"Consultation {consultation.id} not found")
        self._consultations[consultation.id] = consultation
        return consultation

    async def mark_expired(self, consultation_id: str) -> Consultation | None:
        """Mark a consultation as expired."""
        consultation = self._consultations.get(consultation_id)
        if not consultation:
            return None
        consultation.status = ConsultationStatus.EXPIRED
        self._consultations[consultation_id] = consultation
        return consultation

    async def get_by_booking(self, booking_id: str) -> Consultation | None:
        """Get the consultation associated with a booking.

        Requires booking_store to be set during construction for the lookup.
        If booking_store is None, returns None.
        """
        if self._booking_store is None:
            return None

        # Look up booking to get consultation_id
        booking = await self._booking_store.get(booking_id)
        if booking is None:
            return None

        # Look up consultation by the booking's consultation_id
        return await self.get(booking.consultation_id)
