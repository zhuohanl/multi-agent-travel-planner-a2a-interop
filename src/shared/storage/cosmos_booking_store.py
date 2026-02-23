"""
CosmosBookingStore adapter for the shared BookingStore interface.

This module implements the shared BookingStore interface using Cosmos DB
for persistence. It stores shared Booking models directly, maintaining
a local cache and optional Cosmos DB persistence.

Note: This is separate from the orchestrator's BookingStore which handles
the orchestrator Booking model (tied to itineraries with different fields).
This adapter handles the simpler shared Booking model (tied to consultations).

Per design doc Compatibility & Migration section:
- Extends shared BookingStore interface with Cosmos-backed implementation
- Uses booking_index for booking lookups
- Respects canonical id/booking_id naming conventions
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
import uuid

from ..models import Booking, BookingStatus
from .booking_store import BookingStore

if TYPE_CHECKING:
    from azure.cosmos.aio import ContainerProxy
    from src.orchestrator.storage.booking_index import (
        BookingIndexStore,
        BookingIndexStoreProtocol,
    )

logger = logging.getLogger(__name__)


class CosmosBookingStore(BookingStore):
    """
    Cosmos DB implementation of the shared BookingStore interface.

    This adapter stores shared Booking models directly with optional
    Cosmos DB persistence. It uses:
    - A local cache for fast lookups
    - Optional Cosmos container for persistence
    - Optional booking_index for cross-session lookups
    """

    def __init__(
        self,
        container: ContainerProxy | None = None,
        booking_index_store: BookingIndexStoreProtocol | BookingIndexStore | None = None,
    ) -> None:
        """
        Initialize with optional Cosmos DB container.

        Args:
            container: Optional Cosmos container for shared Booking documents.
                      If None, operates in cache-only mode.
            booking_index_store: Optional store for booking_id → consultation mapping
        """
        self._container = container
        self._booking_index_store = booking_index_store
        # In-memory cache for bookings
        self._bookings: dict[str, Booking] = {}
        self._consultation_index: dict[str, list[str]] = {}

    def _generate_id(self) -> str:
        """Generate a booking ID with 'book_' prefix."""
        return f"book_{uuid.uuid4().hex[:12]}"

    async def create(
        self,
        consultation_id: str,
        booking_type: str,
        details: dict[str, Any] | None = None,
    ) -> Booking:
        """
        Create a new booking for a consultation.

        Args:
            consultation_id: Consultation ID to associate with the booking.
            booking_type: Type of booking (e.g., "flight", "hotel").
            details: Additional booking details.

        Returns:
            Newly created Booking with generated ID.
        """
        booking_id = self._generate_id()

        booking = Booking(
            id=booking_id,
            consultation_id=consultation_id,
            type=booking_type,
            status=BookingStatus.PENDING,
            details=details or {},
        )

        # Store in cache
        self._bookings[booking_id] = booking

        # Update consultation index
        if consultation_id not in self._consultation_index:
            self._consultation_index[consultation_id] = []
        self._consultation_index[consultation_id].append(booking_id)

        # Persist to Cosmos if container available
        if self._container is not None:
            doc = self._booking_to_doc(booking)
            try:
                await self._container.upsert_item(body=doc)
                logger.debug(f"Created booking {booking_id} in Cosmos")
            except Exception as e:
                logger.error(f"Error persisting booking to Cosmos: {e}")
                # Keep in cache even if Cosmos write fails

        # Update booking index if available
        if self._booking_index_store is not None:
            try:
                await self._booking_index_store.add_booking_index(
                    booking_id=booking_id,
                    consultation_id=consultation_id,
                    session_id="",  # Session ID not available at this level
                )
            except Exception as e:
                logger.error(f"Error updating booking index: {e}")

        logger.debug(f"Created booking {booking_id} for consultation {consultation_id}")
        return booking

    async def get(self, booking_id: str) -> Booking | None:
        """
        Get a booking by ID.

        Args:
            booking_id: Unique identifier for the booking.

        Returns:
            Booking if found, None otherwise.
        """
        # Check cache first
        if booking_id in self._bookings:
            return self._bookings[booking_id]

        # Try to load from Cosmos
        if self._container is not None:
            try:
                response = await self._container.read_item(
                    item=booking_id,
                    partition_key=booking_id,
                )
                booking = self._doc_to_booking(response)
                self._bookings[booking_id] = booking
                return booking
            except Exception as e:
                error_code = getattr(e, "status_code", None)
                if error_code == 404:
                    return None
                logger.error(f"Error reading booking from Cosmos: {e}")
                raise

        return None

    async def get_by_consultation(self, consultation_id: str) -> list[Booking]:
        """
        Get all bookings for a consultation.

        Args:
            consultation_id: Consultation ID to look up.

        Returns:
            List of bookings for the consultation.
        """
        # Check local index first
        booking_ids = self._consultation_index.get(consultation_id, [])
        bookings = []
        for bid in booking_ids:
            booking = await self.get(bid)
            if booking:
                bookings.append(booking)

        # If we have Cosmos container and no local results, query Cosmos
        if not bookings and self._container is not None:
            try:
                query = "SELECT * FROM c WHERE c.consultation_id = @consultation_id"
                parameters = [{"name": "@consultation_id", "value": consultation_id}]
                items = self._container.query_items(
                    query=query,
                    parameters=parameters,
                    enable_cross_partition_query=True,
                )
                async for item in items:
                    booking = self._doc_to_booking(item)
                    self._bookings[booking.id] = booking
                    bookings.append(booking)
                    # Update local index
                    if consultation_id not in self._consultation_index:
                        self._consultation_index[consultation_id] = []
                    if booking.id not in self._consultation_index[consultation_id]:
                        self._consultation_index[consultation_id].append(booking.id)
            except Exception as e:
                logger.error(f"Error querying bookings from Cosmos: {e}")

        return bookings

    async def update(self, booking: Booking) -> Booking:
        """
        Update an existing booking.

        Args:
            booking: Booking with updated fields.

        Returns:
            Updated booking.

        Raises:
            KeyError: If booking does not exist.
        """
        # Check if booking exists
        existing = await self.get(booking.id)
        if existing is None:
            raise KeyError(f"Booking {booking.id} not found")

        # Update cache
        self._bookings[booking.id] = booking

        # Persist to Cosmos if container available
        if self._container is not None:
            doc = self._booking_to_doc(booking)
            try:
                await self._container.upsert_item(body=doc)
                logger.debug(f"Updated booking {booking.id} in Cosmos")
            except Exception as e:
                logger.error(f"Error updating booking in Cosmos: {e}")
                raise

        return booking

    def _booking_to_doc(self, booking: Booking) -> dict[str, Any]:
        """
        Convert Booking to Cosmos document.

        Args:
            booking: The Booking to convert

        Returns:
            Dict suitable for Cosmos DB storage
        """
        return {
            "id": booking.id,
            "booking_id": booking.id,  # Redundant but matches convention
            "consultation_id": booking.consultation_id,
            "type": booking.type,
            "provider_ref": booking.provider_ref,
            "status": booking.status.value,
            "details": booking.details,
            "can_modify": booking.can_modify,
            "can_cancel": booking.can_cancel,
            "cancellation_policy": booking.cancellation_policy,
            "modification_fee": booking.modification_fee,
        }

    def _doc_to_booking(self, doc: dict[str, Any]) -> Booking:
        """
        Convert Cosmos document to Booking.

        Args:
            doc: Dict from Cosmos DB

        Returns:
            Booking instance
        """
        status_str = doc.get("status", "pending")
        try:
            status = BookingStatus(status_str)
        except ValueError:
            status = BookingStatus.PENDING

        return Booking(
            id=doc.get("booking_id", doc.get("id", "")),
            consultation_id=doc.get("consultation_id", ""),
            type=doc.get("type", ""),
            provider_ref=doc.get("provider_ref"),
            status=status,
            details=doc.get("details", {}),
            can_modify=doc.get("can_modify", True),
            can_cancel=doc.get("can_cancel", True),
            cancellation_policy=doc.get("cancellation_policy"),
            modification_fee=doc.get("modification_fee"),
        )
