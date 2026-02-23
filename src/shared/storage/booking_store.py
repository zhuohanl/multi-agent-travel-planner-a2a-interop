"""Booking storage abstraction and implementations."""
from abc import ABC, abstractmethod
from typing import Any
import uuid

from ..models import Booking, BookingStatus


class BookingStore(ABC):
    """Abstract base class for booking storage."""

    @abstractmethod
    async def create(
        self,
        consultation_id: str,
        booking_type: str,
        details: dict[str, Any] | None = None,
    ) -> Booking:
        """Create a new booking for a consultation.

        Args:
            consultation_id: Consultation ID to associate with the booking.
            booking_type: Type of booking (e.g., "flight", "hotel").
            details: Additional booking details.

        Returns:
            Newly created Booking with generated ID.
        """
        pass

    @abstractmethod
    async def get(self, booking_id: str) -> Booking | None:
        """Get a booking by ID.

        Args:
            booking_id: Unique identifier for the booking.

        Returns:
            Booking if found, None otherwise.
        """
        pass

    @abstractmethod
    async def get_by_consultation(self, consultation_id: str) -> list[Booking]:
        """Get all bookings for a consultation.

        Args:
            consultation_id: Consultation ID to look up.

        Returns:
            List of bookings for the consultation.
        """
        pass

    @abstractmethod
    async def update(self, booking: Booking) -> Booking:
        """Update an existing booking.

        Args:
            booking: Booking with updated fields.

        Returns:
            Updated booking.

        Raises:
            KeyError: If booking does not exist.
        """
        pass


class InMemoryBookingStore(BookingStore):
    """In-memory implementation of BookingStore for development/testing."""

    def __init__(self) -> None:
        self._bookings: dict[str, Booking] = {}
        self._consultation_index: dict[str, list[str]] = {}  # consultation_id -> [booking_ids]

    def _generate_id(self) -> str:
        """Generate a booking ID with 'book_' prefix."""
        return f"book_{uuid.uuid4().hex[:12]}"

    async def create(
        self,
        consultation_id: str,
        booking_type: str,
        details: dict[str, Any] | None = None,
    ) -> Booking:
        """Create a new booking for a consultation."""
        booking = Booking(
            id=self._generate_id(),
            consultation_id=consultation_id,
            type=booking_type,
            status=BookingStatus.PENDING,
            details=details or {},
        )
        self._bookings[booking.id] = booking

        if consultation_id not in self._consultation_index:
            self._consultation_index[consultation_id] = []
        self._consultation_index[consultation_id].append(booking.id)

        return booking

    async def get(self, booking_id: str) -> Booking | None:
        """Get a booking by ID."""
        return self._bookings.get(booking_id)

    async def get_by_consultation(self, consultation_id: str) -> list[Booking]:
        """Get all bookings for a consultation."""
        booking_ids = self._consultation_index.get(consultation_id, [])
        return [self._bookings[bid] for bid in booking_ids if bid in self._bookings]

    async def update(self, booking: Booking) -> Booking:
        """Update an existing booking."""
        if booking.id not in self._bookings:
            raise KeyError(f"Booking {booking.id} not found")
        self._bookings[booking.id] = booking
        return booking
