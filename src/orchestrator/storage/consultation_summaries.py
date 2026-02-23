"""
Consultation summaries storage for Cosmos DB.

This module implements the ConsultationSummaryStore which persists
ConsultationSummary documents to the `consultation_summaries` Cosmos DB container.

Key features:
- Partitioned by consultation_id for O(1) lookups
- Enables post-WorkflowState-expiry read-only access via get_consultation
- Dynamic TTL based on trip_end_date + 30 days
- Created when itinerary is approved, updated when bookings complete

Per design doc:
- Container: consultation_summaries
- Partition key: /consultation_id
- TTL: Dynamic (trip_end_date + 30 days)
- Purpose: Durable summary for post-expiry read-only access

Lookup patterns:
- Consultation (post-expiry) -> Summary: consultation_summaries[consultation_id] (O(1))
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

# Import azure.cosmos only at type-checking time or when needed at runtime
if TYPE_CHECKING:
    from azure.cosmos.aio import ContainerProxy

logger = logging.getLogger(__name__)

# Default TTL fallback: 30 days in seconds (when trip_end_date not available)
DEFAULT_CONSULTATION_SUMMARY_TTL = 30 * 24 * 60 * 60  # 2592000 seconds


def calculate_consultation_summary_ttl(trip_end_date: date | None) -> int:
    """
    Calculate TTL based on trip_end_date + 30 days.

    Per design doc: ConsultationSummary TTL is trip_end_date + 30 days.

    Args:
        trip_end_date: The trip end date (None uses default TTL)

    Returns:
        TTL in seconds (minimum 1 day)
    """
    if trip_end_date is None:
        return DEFAULT_CONSULTATION_SUMMARY_TTL

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


@dataclass
class ConsultationSummary:
    """
    Durable summary of a consultation for post-WorkflowState-expiry access.

    Created when an itinerary is approved and updated when bookings complete.
    This enables get_consultation to work after WorkflowState TTL expires.

    Per design doc:
    - trip_spec_summary: Contains destination, dates, travelers (not full TripSpec)
    - itinerary_ids: List of itinerary IDs (may have multiple if user modified)
    - booking_ids: List of booking IDs for all bookable items
    - status: Current status (e.g., "active", "completed", "cancelled")
    """

    consultation_id: str
    session_id: str
    trip_spec_summary: dict[str, Any]
    itinerary_ids: list[str] = field(default_factory=list)
    booking_ids: list[str] = field(default_factory=list)
    status: str = "active"
    trip_end_date: date | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for Cosmos DB storage."""
        doc = {
            "id": self.consultation_id,  # Cosmos DB document ID
            "consultation_id": self.consultation_id,  # Partition key
            "session_id": self.session_id,
            "trip_spec_summary": self.trip_spec_summary,
            "itinerary_ids": self.itinerary_ids,
            "booking_ids": self.booking_ids,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "ttl": calculate_consultation_summary_ttl(self.trip_end_date),
        }
        if self.trip_end_date is not None:
            doc["trip_end_date"] = (
                self.trip_end_date.isoformat()
                if isinstance(self.trip_end_date, date)
                else self.trip_end_date
            )
        return doc

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConsultationSummary:
        """Create from dictionary retrieved from Cosmos DB."""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        else:
            created_at = datetime.now(timezone.utc)

        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        else:
            updated_at = datetime.now(timezone.utc)

        trip_end_date = data.get("trip_end_date")
        if isinstance(trip_end_date, str):
            # Parse ISO date string
            if "T" in trip_end_date:
                trip_end_date = datetime.fromisoformat(trip_end_date).date()
            else:
                trip_end_date = date.fromisoformat(trip_end_date)
        elif isinstance(trip_end_date, datetime):
            trip_end_date = trip_end_date.date()

        return cls(
            consultation_id=data.get("consultation_id", data.get("id", "")),
            session_id=data.get("session_id", ""),
            trip_spec_summary=data.get("trip_spec_summary", {}),
            itinerary_ids=data.get("itinerary_ids", []),
            booking_ids=data.get("booking_ids", []),
            status=data.get("status", "active"),
            trip_end_date=trip_end_date,
            created_at=created_at,
            updated_at=updated_at,
        )


@runtime_checkable
class ConsultationSummaryStoreProtocol(Protocol):
    """
    Protocol defining the interface for consultation summary storage.

    This protocol allows swapping between Cosmos DB and in-memory
    implementations for production vs testing.
    """

    async def get_summary(self, consultation_id: str) -> ConsultationSummary | None:
        """
        Retrieve consultation summary by consultation_id.

        Args:
            consultation_id: The consultation identifier (partition key)

        Returns:
            ConsultationSummary if found, None if not found
        """
        ...

    async def save_summary(
        self,
        summary: ConsultationSummary,
    ) -> ConsultationSummary:
        """
        Save or update consultation summary.

        Called when:
        1. Itinerary is approved (initial creation)
        2. Bookings complete (status update)

        Args:
            summary: The consultation summary to save

        Returns:
            The saved summary with updated timestamp
        """
        ...

    async def delete_summary(self, consultation_id: str) -> bool:
        """
        Delete consultation summary by consultation_id.

        Args:
            consultation_id: The consultation identifier

        Returns:
            True if deleted, False if not found

        Note:
            Deletion should be rare - summaries expire via TTL.
            This is mainly for cleanup/testing.
        """
        ...


class ConsultationSummaryStore:
    """
    Cosmos DB implementation of consultation summary storage.

    Uses the consultation_summaries container partitioned by consultation_id.
    Provides O(1) lookups for post-WorkflowState-expiry access.
    """

    def __init__(self, container: ContainerProxy) -> None:
        """
        Initialize the store with a Cosmos container client.

        Args:
            container: Async Cosmos container client for consultation_summaries
        """
        self._container = container

    async def get_summary(self, consultation_id: str) -> ConsultationSummary | None:
        """
        Retrieve consultation summary by consultation_id.

        Args:
            consultation_id: The consultation identifier (partition key)

        Returns:
            ConsultationSummary if found, None if not found
        """
        try:
            response = await self._container.read_item(
                item=consultation_id,
                partition_key=consultation_id,
            )
            logger.debug(f"Retrieved consultation summary {consultation_id}")
            return ConsultationSummary.from_dict(response)
        except Exception as e:
            # Handle CosmosResourceNotFoundError
            error_code = getattr(e, "status_code", None)
            if error_code == 404:
                logger.debug(f"Consultation summary not found: {consultation_id}")
                return None
            # Re-raise other errors
            logger.error(f"Error retrieving consultation summary: {e}")
            raise

    async def save_summary(
        self,
        summary: ConsultationSummary,
    ) -> ConsultationSummary:
        """
        Save or update consultation summary.

        Uses upsert for create/update semantics:
        - Initial creation when itinerary is approved
        - Update when bookings complete or status changes

        Args:
            summary: The consultation summary to save

        Returns:
            The saved summary with updated timestamp
        """
        # Update timestamp
        summary.updated_at = datetime.now(timezone.utc)

        # Serialize to dict (includes TTL calculation)
        doc = summary.to_dict()

        try:
            response = await self._container.upsert_item(body=doc)
            logger.debug(f"Saved consultation summary {summary.consultation_id}")
            return ConsultationSummary.from_dict(response)
        except Exception as e:
            logger.error(f"Error saving consultation summary: {e}")
            raise

    async def delete_summary(self, consultation_id: str) -> bool:
        """
        Delete consultation summary by consultation_id.

        Args:
            consultation_id: The consultation identifier

        Returns:
            True if deleted, False if not found
        """
        try:
            await self._container.delete_item(
                item=consultation_id,
                partition_key=consultation_id,
            )
            logger.debug(f"Deleted consultation summary {consultation_id}")
            return True
        except Exception as e:
            error_code = getattr(e, "status_code", None)
            if error_code == 404:
                logger.debug(
                    f"Consultation summary not found for deletion: {consultation_id}"
                )
                return False
            logger.error(f"Error deleting consultation summary: {e}")
            raise


class InMemoryConsultationSummaryStore:
    """
    In-memory implementation of consultation summary storage for testing.

    Implements the same interface as ConsultationSummaryStore but stores
    data in memory. Useful for unit tests and local development.
    """

    def __init__(self) -> None:
        """Initialize empty in-memory store."""
        self._summaries: dict[str, dict[str, Any]] = {}

    async def get_summary(self, consultation_id: str) -> ConsultationSummary | None:
        """Retrieve consultation summary by consultation_id."""
        if consultation_id not in self._summaries:
            return None
        return ConsultationSummary.from_dict(self._summaries[consultation_id])

    async def save_summary(
        self,
        summary: ConsultationSummary,
    ) -> ConsultationSummary:
        """Save or update consultation summary."""
        # Update timestamp
        summary.updated_at = datetime.now(timezone.utc)

        doc = summary.to_dict()
        self._summaries[summary.consultation_id] = doc

        return ConsultationSummary.from_dict(doc)

    async def delete_summary(self, consultation_id: str) -> bool:
        """Delete consultation summary by consultation_id."""
        if consultation_id in self._summaries:
            del self._summaries[consultation_id]
            return True
        return False

    def clear(self) -> None:
        """Clear all summaries (for test cleanup)."""
        self._summaries.clear()

    def get_count(self) -> int:
        """Get the number of summaries stored (for testing)."""
        return len(self._summaries)
