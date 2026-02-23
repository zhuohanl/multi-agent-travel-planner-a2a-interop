"""
Booking storage for Cosmos DB.

This module implements the BookingStore which persists Booking
documents to the `bookings` Cosmos DB container.

Key features:
- Partitioned by booking_id for efficient lookups
- Optimistic locking via etag for concurrency control
- Dynamic TTL based on trip_end_date + 30 days

Per design doc:
- Container: bookings
- Partition key: /booking_id
- TTL: Dynamic (trip_end_date + 30 days)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from src.orchestrator.models.booking import Booking, BookingStatus

# Import azure.cosmos only at type-checking time or when needed at runtime
if TYPE_CHECKING:
    from azure.cosmos.aio import ContainerProxy

logger = logging.getLogger(__name__)

# Default TTL fallback: 30 days in seconds (when trip_end_date not available)
DEFAULT_BOOKING_TTL = 30 * 24 * 60 * 60  # 2592000 seconds


class BookingConflictError(Exception):
    """Raised when optimistic locking fails due to concurrent modification."""

    def __init__(self, booking_id: str, message: str | None = None):
        self.booking_id = booking_id
        super().__init__(
            message or f"Concurrent modification detected for booking {booking_id}"
        )


def calculate_booking_ttl(trip_end_date: date | None) -> int:
    """
    Calculate TTL based on trip_end_date + 30 days.

    Per design doc: Booking TTL is trip_end_date + 30 days.

    Args:
        trip_end_date: The trip end date (None uses default TTL)

    Returns:
        TTL in seconds (minimum 1 day)
    """
    if trip_end_date is None:
        return DEFAULT_BOOKING_TTL

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
class BookingStoreProtocol(Protocol):
    """
    Protocol defining the interface for booking storage.

    This protocol allows swapping between Cosmos DB and in-memory
    implementations for production vs testing.
    """

    async def get_booking(self, booking_id: str) -> Booking | None:
        """
        Retrieve booking by booking_id.

        Args:
            booking_id: The booking identifier (partition key)

        Returns:
            Booking if found, None if not found
        """
        ...

    async def save_booking(
        self,
        booking: Booking,
        trip_end_date: date | None = None,
        if_match: str | None = None,
    ) -> Booking:
        """
        Save booking.

        Args:
            booking: The booking to save
            trip_end_date: Trip end date for TTL calculation (None uses default)
            if_match: Optional etag for optimistic locking. If provided,
                     the save will fail with BookingConflictError if the document
                     has been modified since the etag was retrieved.

        Returns:
            The saved booking with updated etag

        Raises:
            BookingConflictError: If if_match is provided and doesn't match
        """
        ...

    async def delete_booking(self, booking_id: str) -> bool:
        """
        Delete booking by booking_id.

        Args:
            booking_id: The booking identifier

        Returns:
            True if deleted, False if not found
        """
        ...

    async def get_bookings_by_ids(self, booking_ids: list[str]) -> list[Booking]:
        """
        Retrieve multiple bookings by their IDs.

        Args:
            booking_ids: List of booking identifiers

        Returns:
            List of found bookings (may be shorter than input if some not found)
        """
        ...

    async def update_booking_status(
        self,
        booking_id: str,
        status: BookingStatus,
        status_reason: str | None = None,
        if_match: str | None = None,
    ) -> Booking | None:
        """
        Update booking status.

        Args:
            booking_id: The booking identifier
            status: New booking status
            status_reason: Optional reason for status change
            if_match: Optional etag for optimistic locking

        Returns:
            Updated booking if found, None if not found

        Raises:
            BookingConflictError: If if_match is provided and doesn't match
        """
        ...

    async def get_bookings_by_status(self, status: BookingStatus) -> list[Booking]:
        """
        Retrieve all bookings with the given status.

        This is a cross-partition query used for background reconciliation.
        Use sparingly as it scans all partitions.

        Args:
            status: The booking status to filter by

        Returns:
            List of bookings with the given status
        """
        ...


class BookingStore:
    """
    Cosmos DB implementation of booking storage.

    Uses the bookings container partitioned by booking_id.
    Supports optimistic locking via etag for concurrent updates.
    """

    def __init__(self, container: ContainerProxy) -> None:
        """
        Initialize the store with a Cosmos container client.

        Args:
            container: Async Cosmos container client for bookings
        """
        self._container = container

    async def get_booking(self, booking_id: str) -> Booking | None:
        """
        Retrieve booking by booking_id.

        Args:
            booking_id: The booking identifier (partition key)

        Returns:
            Booking if found, None if not found
        """
        try:
            response = await self._container.read_item(
                item=booking_id,
                partition_key=booking_id,
            )
            logger.debug(f"Retrieved booking {booking_id}")
            return Booking.from_dict(response)
        except Exception as e:
            # Handle CosmosResourceNotFoundError
            error_code = getattr(e, "status_code", None)
            if error_code == 404:
                logger.debug(f"Booking not found: {booking_id}")
                return None
            # Re-raise other errors
            logger.error(f"Error retrieving booking: {e}")
            raise

    async def save_booking(
        self,
        booking: Booking,
        trip_end_date: date | None = None,
        if_match: str | None = None,
    ) -> Booking:
        """
        Save booking with optional optimistic locking.

        Uses upsert for create/update semantics. When if_match is provided,
        uses conditional write to detect concurrent modifications.

        Args:
            booking: The booking to save
            trip_end_date: Trip end date for TTL calculation (None uses default)
            if_match: Optional etag for optimistic locking

        Returns:
            The saved booking with updated etag

        Raises:
            BookingConflictError: If if_match is provided and doesn't match
        """
        # Update timestamp
        booking.updated_at = datetime.now(timezone.utc)

        # Serialize to dict and add TTL
        doc = booking.to_dict()
        doc["ttl"] = calculate_booking_ttl(trip_end_date)
        if trip_end_date:
            # Store trip_end_date for reference
            if isinstance(trip_end_date, datetime):
                doc["trip_end_date"] = trip_end_date.date().isoformat()
            else:
                doc["trip_end_date"] = trip_end_date.isoformat()

        try:
            if if_match:
                # Conditional write with etag
                response = await self._container.replace_item(
                    item=booking.booking_id,
                    body=doc,
                    if_match=if_match,
                )
                logger.debug(
                    f"Replaced booking {booking.booking_id} with etag check"
                )
            else:
                # Upsert without etag check
                response = await self._container.upsert_item(body=doc)
                logger.debug(f"Upserted booking {booking.booking_id}")

            return Booking.from_dict(response)

        except Exception as e:
            # Handle CosmosResourceExistsError (412 Precondition Failed)
            error_code = getattr(e, "status_code", None)
            if error_code == 412:
                logger.warning(
                    f"Conflict detected saving booking {booking.booking_id}"
                )
                raise BookingConflictError(booking.booking_id) from e
            # Re-raise other errors
            logger.error(f"Error saving booking: {e}")
            raise

    async def delete_booking(self, booking_id: str) -> bool:
        """
        Delete booking by booking_id.

        Args:
            booking_id: The booking identifier

        Returns:
            True if deleted, False if not found
        """
        try:
            await self._container.delete_item(
                item=booking_id,
                partition_key=booking_id,
            )
            logger.debug(f"Deleted booking {booking_id}")
            return True
        except Exception as e:
            error_code = getattr(e, "status_code", None)
            if error_code == 404:
                logger.debug(f"Booking not found for deletion: {booking_id}")
                return False
            logger.error(f"Error deleting booking: {e}")
            raise

    async def get_bookings_by_ids(self, booking_ids: list[str]) -> list[Booking]:
        """
        Retrieve multiple bookings by their IDs.

        Uses point reads for each ID (cross-partition query not efficient).
        For large numbers of IDs, consider batching.

        Args:
            booking_ids: List of booking identifiers

        Returns:
            List of found bookings (may be shorter than input if some not found)
        """
        bookings = []
        for booking_id in booking_ids:
            booking = await self.get_booking(booking_id)
            if booking:
                bookings.append(booking)
        return bookings

    async def update_booking_status(
        self,
        booking_id: str,
        status: BookingStatus,
        status_reason: str | None = None,
        if_match: str | None = None,
    ) -> Booking | None:
        """
        Update booking status.

        Performs read-modify-write with optional optimistic locking.

        Args:
            booking_id: The booking identifier
            status: New booking status
            status_reason: Optional reason for status change
            if_match: Optional etag for optimistic locking

        Returns:
            Updated booking if found, None if not found

        Raises:
            BookingConflictError: If if_match is provided and doesn't match
        """
        # Get existing booking
        booking = await self.get_booking(booking_id)
        if booking is None:
            return None

        # Update status
        booking.status = status
        booking.status_reason = status_reason

        # If no explicit if_match provided, use the etag from the read
        etag = if_match or booking.etag

        # Save with etag check
        return await self.save_booking(booking, if_match=etag)

    async def get_bookings_by_status(self, status: BookingStatus) -> list[Booking]:
        """
        Retrieve all bookings with the given status.

        This is a cross-partition query used for background reconciliation.
        Use sparingly as it scans all partitions.

        Args:
            status: The booking status to filter by

        Returns:
            List of bookings with the given status
        """
        query = "SELECT * FROM c WHERE c.status = @status"
        parameters = [{"name": "@status", "value": status.value}]

        bookings = []
        try:
            async for item in self._container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True,
            ):
                bookings.append(Booking.from_dict(item))
            logger.debug(f"Found {len(bookings)} bookings with status {status.value}")
        except Exception as e:
            logger.error(f"Error querying bookings by status: {e}")
            raise

        return bookings


class InMemoryBookingStore:
    """
    In-memory implementation of booking storage for testing.

    Implements the same interface as BookingStore but stores
    data in memory. Useful for unit tests and local development.
    """

    def __init__(self) -> None:
        """Initialize empty in-memory store."""
        self._bookings: dict[str, dict[str, Any]] = {}
        self._etag_counter = 0

    async def get_booking(self, booking_id: str) -> Booking | None:
        """Retrieve booking by booking_id."""
        if booking_id not in self._bookings:
            return None
        return Booking.from_dict(self._bookings[booking_id])

    async def save_booking(
        self,
        booking: Booking,
        trip_end_date: date | None = None,
        if_match: str | None = None,
    ) -> Booking:
        """Save booking with optional optimistic locking."""
        existing = self._bookings.get(booking.booking_id)

        if if_match and existing:
            existing_etag = existing.get("_etag")
            if existing_etag != if_match:
                raise BookingConflictError(booking.booking_id)

        # Update timestamp and generate new etag
        booking.updated_at = datetime.now(timezone.utc)
        self._etag_counter += 1
        new_etag = f"etag_{self._etag_counter}"

        doc = booking.to_dict()
        doc["_etag"] = new_etag
        doc["ttl"] = calculate_booking_ttl(trip_end_date)
        if trip_end_date:
            if isinstance(trip_end_date, datetime):
                doc["trip_end_date"] = trip_end_date.date().isoformat()
            else:
                doc["trip_end_date"] = trip_end_date.isoformat()

        self._bookings[booking.booking_id] = doc

        return Booking.from_dict(doc)

    async def delete_booking(self, booking_id: str) -> bool:
        """Delete booking by booking_id."""
        if booking_id in self._bookings:
            del self._bookings[booking_id]
            return True
        return False

    async def get_bookings_by_ids(self, booking_ids: list[str]) -> list[Booking]:
        """Retrieve multiple bookings by their IDs."""
        bookings = []
        for booking_id in booking_ids:
            booking = await self.get_booking(booking_id)
            if booking:
                bookings.append(booking)
        return bookings

    async def update_booking_status(
        self,
        booking_id: str,
        status: BookingStatus,
        status_reason: str | None = None,
        if_match: str | None = None,
    ) -> Booking | None:
        """Update booking status."""
        booking = await self.get_booking(booking_id)
        if booking is None:
            return None

        # Update status
        booking.status = status
        booking.status_reason = status_reason

        # If no explicit if_match provided, use the etag from the read
        etag = if_match or booking.etag

        return await self.save_booking(booking, if_match=etag)

    async def get_bookings_by_status(self, status: BookingStatus) -> list[Booking]:
        """Retrieve all bookings with the given status."""
        bookings = []
        for doc in self._bookings.values():
            booking = Booking.from_dict(doc)
            if booking.status == status:
                bookings.append(booking)
        return bookings

    def clear(self) -> None:
        """Clear all bookings (for test cleanup)."""
        self._bookings.clear()
        self._etag_counter = 0
