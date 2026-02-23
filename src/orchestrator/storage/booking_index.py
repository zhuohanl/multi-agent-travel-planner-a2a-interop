"""
Booking index storage for Cosmos DB.

This module implements the BookingIndexStore which provides a reverse
lookup from booking_id to session_id for workflow resumption.

Key features:
- Partitioned by booking_id for O(1) lookups
- Maps booking_id to session_id and consultation_id
- Dynamic TTL based on trip_end_date + 30 days
- Enables cross-session resumption via booking_id

Per design doc:
- Container: booking_index
- Partition key: /booking_id
- TTL: Dynamic (trip_end_date + 30 days)
- Purpose: Maps booking_id -> session_id for workflow lookup
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

# Import azure.cosmos only at type-checking time or when needed at runtime
if TYPE_CHECKING:
    from azure.cosmos.aio import ContainerProxy

logger = logging.getLogger(__name__)

# Default TTL fallback: 30 days in seconds (when trip_end_date not available)
DEFAULT_BOOKING_INDEX_TTL = 30 * 24 * 60 * 60  # 2592000 seconds


@dataclass
class BookingIndexEntry:
    """
    Entry in the booking_index container.

    Maps booking_id to session_id and consultation_id for workflow
    lookup and resumption. Includes trip_end_date for TTL calculation.
    """

    booking_id: str
    consultation_id: str
    session_id: str
    trip_end_date: date | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for Cosmos DB storage."""
        doc = {
            "id": self.booking_id,  # Cosmos DB document ID
            "booking_id": self.booking_id,  # Partition key
            "consultation_id": self.consultation_id,
            "session_id": self.session_id,
            "ttl": calculate_booking_index_ttl(self.trip_end_date),
        }
        if self.trip_end_date:
            doc["trip_end_date"] = self.trip_end_date.isoformat()
        return doc

    @classmethod
    def from_dict(cls, data: dict) -> BookingIndexEntry:
        """Create from dictionary retrieved from Cosmos DB."""
        trip_end_date = None
        if "trip_end_date" in data and data["trip_end_date"]:
            trip_end_date = date.fromisoformat(data["trip_end_date"])

        return cls(
            booking_id=data.get("booking_id", data.get("id", "")),
            consultation_id=data.get("consultation_id", ""),
            session_id=data.get("session_id", ""),
            trip_end_date=trip_end_date,
        )


def calculate_booking_index_ttl(trip_end_date: date | None) -> int:
    """
    Calculate TTL based on trip_end_date + 30 days.

    Per design doc: booking_index TTL is trip_end_date + 30 days.

    Args:
        trip_end_date: The trip end date (None uses default TTL)

    Returns:
        TTL in seconds (minimum 1 day)
    """
    if trip_end_date is None:
        return DEFAULT_BOOKING_INDEX_TTL

    # Calculate expiry: trip_end_date + 30 days
    if isinstance(trip_end_date, datetime):
        expiry = trip_end_date + timedelta(days=30)
    else:
        # Convert date to datetime at midnight UTC
        expiry = datetime.combine(trip_end_date, datetime.min.time(), tzinfo=timezone.utc)
        expiry = expiry + timedelta(days=30)

    now = datetime.now(timezone.utc)
    ttl_seconds = int((expiry - now).total_seconds())

    # Minimum 1 day TTL (86400 seconds)
    return max(ttl_seconds, 86400)


@runtime_checkable
class BookingIndexStoreProtocol(Protocol):
    """
    Protocol defining the interface for booking index storage.

    This protocol allows swapping between Cosmos DB and in-memory
    implementations for production vs testing.
    """

    async def get_session_for_booking(
        self, booking_id: str
    ) -> BookingIndexEntry | None:
        """
        Retrieve index entry by booking_id.

        Args:
            booking_id: The booking identifier (partition key)

        Returns:
            BookingIndexEntry with session_id and consultation_id if found,
            None if not found
        """
        ...

    async def add_booking_index(
        self,
        booking_id: str,
        consultation_id: str,
        session_id: str,
        trip_end_date: date | None = None,
    ) -> BookingIndexEntry:
        """
        Create or update a booking index entry.

        Args:
            booking_id: The booking identifier (partition key)
            consultation_id: The consultation identifier
            session_id: The session identifier
            trip_end_date: Trip end date for TTL calculation (None uses default)

        Returns:
            The created/updated index entry
        """
        ...

    async def delete_booking_index(self, booking_id: str) -> bool:
        """
        Delete booking index entry.

        Args:
            booking_id: The booking identifier to delete

        Returns:
            True if deleted, False if not found
        """
        ...


class BookingIndexStore:
    """
    Cosmos DB implementation of booking index storage.

    Uses the booking_index container partitioned by booking_id.
    Provides O(1) lookup for workflow resumption via booking_id.
    """

    def __init__(self, container: ContainerProxy) -> None:
        """
        Initialize the store with a Cosmos container client.

        Args:
            container: Async Cosmos container client for booking_index
        """
        self._container = container

    async def get_session_for_booking(
        self, booking_id: str
    ) -> BookingIndexEntry | None:
        """
        Retrieve index entry by booking_id.

        Args:
            booking_id: The booking identifier (partition key)

        Returns:
            BookingIndexEntry if found, None if not found
        """
        try:
            response = await self._container.read_item(
                item=booking_id,
                partition_key=booking_id,
            )
            logger.debug(f"Retrieved booking index for {booking_id}")
            return BookingIndexEntry.from_dict(response)
        except Exception as e:
            # Handle CosmosResourceNotFoundError
            error_code = getattr(e, "status_code", None)
            if error_code == 404:
                logger.debug(f"Booking index not found for {booking_id}")
                return None
            # Re-raise other errors
            logger.error(f"Error retrieving booking index: {e}")
            raise

    async def add_booking_index(
        self,
        booking_id: str,
        consultation_id: str,
        session_id: str,
        trip_end_date: date | None = None,
    ) -> BookingIndexEntry:
        """
        Create or update a booking index entry.

        Uses upsert for create/update semantics.

        Args:
            booking_id: The booking identifier (partition key)
            consultation_id: The consultation identifier
            session_id: The session identifier
            trip_end_date: Trip end date for TTL calculation (None uses default)

        Returns:
            The created/updated index entry
        """
        entry = BookingIndexEntry(
            booking_id=booking_id,
            consultation_id=consultation_id,
            session_id=session_id,
            trip_end_date=trip_end_date,
        )
        doc = entry.to_dict()

        try:
            response = await self._container.upsert_item(body=doc)
            logger.debug(
                f"Upserted booking index: {booking_id} -> session={session_id}, "
                f"consultation={consultation_id}"
            )
            return BookingIndexEntry.from_dict(response)
        except Exception as e:
            logger.error(f"Error adding booking index: {e}")
            raise

    async def delete_booking_index(self, booking_id: str) -> bool:
        """
        Delete booking index entry.

        Args:
            booking_id: The booking identifier to delete

        Returns:
            True if deleted, False if not found
        """
        try:
            await self._container.delete_item(
                item=booking_id,
                partition_key=booking_id,
            )
            logger.debug(f"Deleted booking index for {booking_id}")
            return True
        except Exception as e:
            error_code = getattr(e, "status_code", None)
            if error_code == 404:
                logger.debug(
                    f"Booking index not found for deletion: {booking_id}"
                )
                return False
            logger.error(f"Error deleting booking index: {e}")
            raise


class InMemoryBookingIndexStore:
    """
    In-memory implementation of booking index storage for testing.

    Implements the same interface as BookingIndexStore but stores
    data in memory. Useful for unit tests and local development.
    """

    def __init__(self) -> None:
        """Initialize empty in-memory store."""
        self._index: dict[str, dict[str, Any]] = {}

    async def get_session_for_booking(
        self, booking_id: str
    ) -> BookingIndexEntry | None:
        """Retrieve index entry by booking_id."""
        if booking_id not in self._index:
            return None
        return BookingIndexEntry.from_dict(self._index[booking_id])

    async def add_booking_index(
        self,
        booking_id: str,
        consultation_id: str,
        session_id: str,
        trip_end_date: date | None = None,
    ) -> BookingIndexEntry:
        """Create or update a booking index entry."""
        entry = BookingIndexEntry(
            booking_id=booking_id,
            consultation_id=consultation_id,
            session_id=session_id,
            trip_end_date=trip_end_date,
        )
        self._index[booking_id] = entry.to_dict()
        return entry

    async def delete_booking_index(self, booking_id: str) -> bool:
        """Delete booking index entry."""
        if booking_id in self._index:
            del self._index[booking_id]
            return True
        return False

    def clear(self) -> None:
        """Clear all index entries (for test cleanup)."""
        self._index.clear()
