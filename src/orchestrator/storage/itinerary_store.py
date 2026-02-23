"""
Itinerary storage for Cosmos DB.

This module implements the ItineraryStore which persists Itinerary
documents to the `itineraries` Cosmos DB container.

Key features:
- Partitioned by itinerary_id for efficient lookups
- Immutable after creation (approved itineraries don't change)
- Dynamic TTL based on trip_end_date + 30 days

Per design doc:
- Container: itineraries
- Partition key: /itinerary_id
- TTL: Dynamic (trip_end_date + 30 days)
- Itineraries are created ONLY when user approves the ItineraryDraft
- Immutable after creation (modifications create new itinerary)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from src.orchestrator.models.itinerary import Itinerary

# Import azure.cosmos only at type-checking time or when needed at runtime
if TYPE_CHECKING:
    from azure.cosmos.aio import ContainerProxy

logger = logging.getLogger(__name__)

# Default TTL fallback: 30 days in seconds (when trip_end_date not available)
DEFAULT_ITINERARY_TTL = 30 * 24 * 60 * 60  # 2592000 seconds


def calculate_itinerary_ttl(trip_end_date: date | None) -> int:
    """
    Calculate TTL based on trip_end_date + 30 days.

    Per design doc: Itinerary TTL is trip_end_date + 30 days.

    Args:
        trip_end_date: The trip end date (None uses default TTL)

    Returns:
        TTL in seconds (minimum 1 day)
    """
    if trip_end_date is None:
        return DEFAULT_ITINERARY_TTL

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
class ItineraryStoreProtocol(Protocol):
    """
    Protocol defining the interface for itinerary storage.

    This protocol allows swapping between Cosmos DB and in-memory
    implementations for production vs testing.
    """

    async def get_itinerary(self, itinerary_id: str) -> Itinerary | None:
        """
        Retrieve itinerary by itinerary_id.

        Args:
            itinerary_id: The itinerary identifier (partition key)

        Returns:
            Itinerary if found, None if not found
        """
        ...

    async def save_itinerary(
        self,
        itinerary: Itinerary,
    ) -> Itinerary:
        """
        Save itinerary.

        Per design doc, itineraries are immutable after creation.
        This method is primarily for initial creation at approval time.

        Args:
            itinerary: The itinerary to save

        Returns:
            The saved itinerary

        Note:
            TTL is calculated from the itinerary's trip_summary.end_date
        """
        ...

    async def delete_itinerary(self, itinerary_id: str) -> bool:
        """
        Delete itinerary by itinerary_id.

        Args:
            itinerary_id: The itinerary identifier

        Returns:
            True if deleted, False if not found

        Note:
            Deletion should be rare - itineraries are immutable and
            expire via TTL. This is mainly for cleanup/testing.
        """
        ...

    async def get_itineraries_by_consultation(
        self, consultation_id: str
    ) -> list[Itinerary]:
        """
        Retrieve itineraries for a consultation.

        Per design doc, a user can have multiple itineraries if they
        request_change and approve again (creates new itinerary_id).

        Args:
            consultation_id: The consultation identifier

        Returns:
            List of itineraries for the consultation (may be empty)
        """
        ...


class ItineraryStore:
    """
    Cosmos DB implementation of itinerary storage.

    Uses the itineraries container partitioned by itinerary_id.
    Itineraries are immutable after creation (per design doc).
    """

    def __init__(self, container: ContainerProxy) -> None:
        """
        Initialize the store with a Cosmos container client.

        Args:
            container: Async Cosmos container client for itineraries
        """
        self._container = container

    async def get_itinerary(self, itinerary_id: str) -> Itinerary | None:
        """
        Retrieve itinerary by itinerary_id.

        Args:
            itinerary_id: The itinerary identifier (partition key)

        Returns:
            Itinerary if found, None if not found
        """
        try:
            response = await self._container.read_item(
                item=itinerary_id,
                partition_key=itinerary_id,
            )
            logger.debug(f"Retrieved itinerary {itinerary_id}")
            return Itinerary.from_dict(response)
        except Exception as e:
            # Handle CosmosResourceNotFoundError
            error_code = getattr(e, "status_code", None)
            if error_code == 404:
                logger.debug(f"Itinerary not found: {itinerary_id}")
                return None
            # Re-raise other errors
            logger.error(f"Error retrieving itinerary: {e}")
            raise

    async def save_itinerary(
        self,
        itinerary: Itinerary,
    ) -> Itinerary:
        """
        Save itinerary.

        Uses upsert for idempotent creation. Per design doc, itineraries
        are immutable after approval, so updates should be rare.

        Args:
            itinerary: The itinerary to save

        Returns:
            The saved itinerary
        """
        # Serialize to dict (includes TTL calculation via Itinerary.to_dict())
        doc = itinerary.to_dict()

        # Ensure TTL is set correctly based on trip_end_date
        trip_end = itinerary.trip_summary.end_date
        doc["ttl"] = calculate_itinerary_ttl(trip_end)

        try:
            response = await self._container.upsert_item(body=doc)
            logger.debug(f"Saved itinerary {itinerary.itinerary_id}")
            return Itinerary.from_dict(response)
        except Exception as e:
            logger.error(f"Error saving itinerary: {e}")
            raise

    async def delete_itinerary(self, itinerary_id: str) -> bool:
        """
        Delete itinerary by itinerary_id.

        Args:
            itinerary_id: The itinerary identifier

        Returns:
            True if deleted, False if not found
        """
        try:
            await self._container.delete_item(
                item=itinerary_id,
                partition_key=itinerary_id,
            )
            logger.debug(f"Deleted itinerary {itinerary_id}")
            return True
        except Exception as e:
            error_code = getattr(e, "status_code", None)
            if error_code == 404:
                logger.debug(f"Itinerary not found for deletion: {itinerary_id}")
                return False
            logger.error(f"Error deleting itinerary: {e}")
            raise

    async def get_itineraries_by_consultation(
        self, consultation_id: str
    ) -> list[Itinerary]:
        """
        Retrieve itineraries for a consultation.

        Uses a cross-partition query since itineraries are partitioned by
        itinerary_id but we need to find by consultation_id.

        Args:
            consultation_id: The consultation identifier

        Returns:
            List of itineraries for the consultation
        """
        try:
            query = "SELECT * FROM c WHERE c.consultation_id = @consultation_id"
            parameters = [{"name": "@consultation_id", "value": consultation_id}]

            items = []
            async for item in self._container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True,
            ):
                items.append(Itinerary.from_dict(item))

            logger.debug(
                f"Found {len(items)} itineraries for consultation {consultation_id}"
            )
            return items
        except Exception as e:
            logger.error(f"Error querying itineraries by consultation: {e}")
            raise


class InMemoryItineraryStore:
    """
    In-memory implementation of itinerary storage for testing.

    Implements the same interface as ItineraryStore but stores
    data in memory. Useful for unit tests and local development.
    """

    def __init__(self) -> None:
        """Initialize empty in-memory store."""
        self._itineraries: dict[str, dict[str, Any]] = {}

    async def get_itinerary(self, itinerary_id: str) -> Itinerary | None:
        """Retrieve itinerary by itinerary_id."""
        if itinerary_id not in self._itineraries:
            return None
        return Itinerary.from_dict(self._itineraries[itinerary_id])

    async def save_itinerary(
        self,
        itinerary: Itinerary,
    ) -> Itinerary:
        """Save itinerary."""
        doc = itinerary.to_dict()

        # Calculate and store TTL
        trip_end = itinerary.trip_summary.end_date
        doc["ttl"] = calculate_itinerary_ttl(trip_end)

        self._itineraries[itinerary.itinerary_id] = doc

        return Itinerary.from_dict(doc)

    async def delete_itinerary(self, itinerary_id: str) -> bool:
        """Delete itinerary by itinerary_id."""
        if itinerary_id in self._itineraries:
            del self._itineraries[itinerary_id]
            return True
        return False

    async def get_itineraries_by_consultation(
        self, consultation_id: str
    ) -> list[Itinerary]:
        """Retrieve itineraries for a consultation."""
        results = []
        for doc in self._itineraries.values():
            if doc.get("consultation_id") == consultation_id:
                results.append(Itinerary.from_dict(doc))
        return results

    def clear(self) -> None:
        """Clear all itineraries (for test cleanup)."""
        self._itineraries.clear()
