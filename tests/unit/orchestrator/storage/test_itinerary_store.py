"""
Unit tests for ItineraryStore.

Tests cover:
- Basic CRUD operations (get, save, delete)
- Non-existent itinerary handling
- Query by consultation_id
- TTL calculation
- Protocol compliance
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator.models.itinerary import (
    Itinerary,
    ItineraryDay,
    TripSummary,
)
from src.orchestrator.storage.itinerary_store import (
    DEFAULT_ITINERARY_TTL,
    InMemoryItineraryStore,
    ItineraryStore,
    ItineraryStoreProtocol,
    calculate_itinerary_ttl,
)


class TestCalculateItineraryTtl:
    """Tests for TTL calculation function."""

    def test_with_none_returns_default(self) -> None:
        """Test that None trip_end_date returns default TTL."""
        result = calculate_itinerary_ttl(None)
        assert result == DEFAULT_ITINERARY_TTL

    def test_with_future_date(self) -> None:
        """Test TTL calculation with future trip_end_date."""
        future_date = date.today() + timedelta(days=10)
        result = calculate_itinerary_ttl(future_date)

        # Should be approximately (10 + 30) days in seconds
        expected_min = 39 * 24 * 60 * 60  # 39 days (accounting for time of day)
        expected_max = 41 * 24 * 60 * 60  # 41 days

        assert expected_min <= result <= expected_max

    def test_with_past_date_returns_minimum(self) -> None:
        """Test that past trip_end_date returns minimum TTL (1 day)."""
        past_date = date.today() - timedelta(days=60)
        result = calculate_itinerary_ttl(past_date)

        # Should be minimum of 1 day (86400 seconds)
        assert result == 86400

    def test_with_datetime(self) -> None:
        """Test TTL calculation with datetime input."""
        future_dt = datetime.now(timezone.utc) + timedelta(days=10)
        result = calculate_itinerary_ttl(future_dt)

        # Should be approximately (10 + 30) days in seconds
        expected_min = 39 * 24 * 60 * 60
        expected_max = 41 * 24 * 60 * 60

        assert expected_min <= result <= expected_max


class TestInMemoryItineraryStore:
    """Tests for InMemoryItineraryStore."""

    @pytest.fixture
    def store(self) -> InMemoryItineraryStore:
        """Create a fresh in-memory store for each test."""
        return InMemoryItineraryStore()

    @pytest.fixture
    def sample_itinerary(self) -> Itinerary:
        """Create a sample itinerary for testing."""
        trip_summary = TripSummary(
            destination="Tokyo, Japan",
            start_date=date.today() + timedelta(days=30),
            end_date=date.today() + timedelta(days=37),
            travelers=2,
            trip_type="leisure",
        )
        return Itinerary(
            itinerary_id="itn_test123",
            consultation_id="cons_abc",
            approved_at=datetime.now(timezone.utc),
            trip_summary=trip_summary,
            days=[
                ItineraryDay(
                    day_number=1,
                    date=date.today() + timedelta(days=30),
                    title="Arrival Day",
                )
            ],
            booking_ids=["book_1", "book_2"],
            total_estimated_cost=3000.00,
        )

    @pytest.mark.asyncio
    async def test_get_itinerary_found(
        self, store: InMemoryItineraryStore, sample_itinerary: Itinerary
    ) -> None:
        """Test retrieving an existing itinerary."""
        await store.save_itinerary(sample_itinerary)

        result = await store.get_itinerary("itn_test123")

        assert result is not None
        assert result.itinerary_id == "itn_test123"
        assert result.consultation_id == "cons_abc"
        assert result.trip_summary.destination == "Tokyo, Japan"
        assert result.total_estimated_cost == 3000.00

    @pytest.mark.asyncio
    async def test_get_itinerary_not_found(
        self, store: InMemoryItineraryStore
    ) -> None:
        """Test retrieving a non-existent itinerary returns None."""
        result = await store.get_itinerary("itn_nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_save_itinerary(
        self, store: InMemoryItineraryStore, sample_itinerary: Itinerary
    ) -> None:
        """Test saving creates a new itinerary."""
        result = await store.save_itinerary(sample_itinerary)

        assert result.itinerary_id == "itn_test123"

        # Verify it's persisted
        retrieved = await store.get_itinerary("itn_test123")
        assert retrieved is not None
        assert retrieved.consultation_id == "cons_abc"

    @pytest.mark.asyncio
    async def test_save_itinerary_sets_ttl(
        self, store: InMemoryItineraryStore, sample_itinerary: Itinerary
    ) -> None:
        """Test saving sets TTL based on trip_end_date."""
        await store.save_itinerary(sample_itinerary)

        # Check the stored doc has TTL
        stored = store._itineraries["itn_test123"]
        assert "ttl" in stored
        # TTL should be roughly trip_end_date + 30 days from now
        # sample_itinerary has end_date = today + 37 days
        # So TTL = (37 + 30) days = 67 days
        expected_min = 66 * 24 * 60 * 60  # 66 days (accounting for time of day)
        expected_max = 68 * 24 * 60 * 60  # 68 days
        assert expected_min <= stored["ttl"] <= expected_max

    @pytest.mark.asyncio
    async def test_delete_itinerary_existing(
        self, store: InMemoryItineraryStore, sample_itinerary: Itinerary
    ) -> None:
        """Test deleting an existing itinerary."""
        await store.save_itinerary(sample_itinerary)

        result = await store.delete_itinerary("itn_test123")

        assert result is True
        assert await store.get_itinerary("itn_test123") is None

    @pytest.mark.asyncio
    async def test_delete_itinerary_not_found(
        self, store: InMemoryItineraryStore
    ) -> None:
        """Test deleting a non-existent itinerary returns False."""
        result = await store.delete_itinerary("itn_nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_itineraries_by_consultation(
        self, store: InMemoryItineraryStore
    ) -> None:
        """Test retrieving itineraries by consultation_id."""
        # Create multiple itineraries for the same consultation
        # (as can happen with request_change -> approve -> new itinerary)
        for i in range(3):
            trip_summary = TripSummary(
                destination="Tokyo, Japan",
                start_date=date.today() + timedelta(days=30),
                end_date=date.today() + timedelta(days=37),
                travelers=2,
            )
            itinerary = Itinerary(
                itinerary_id=f"itn_{i}",
                consultation_id="cons_shared",
                approved_at=datetime.now(timezone.utc),
                trip_summary=trip_summary,
                days=[],
                booking_ids=[],
            )
            await store.save_itinerary(itinerary)

        # Add one for a different consultation
        trip_summary2 = TripSummary(
            destination="Paris, France",
            start_date=date.today() + timedelta(days=30),
            end_date=date.today() + timedelta(days=37),
            travelers=1,
        )
        other_itinerary = Itinerary(
            itinerary_id="itn_other",
            consultation_id="cons_other",
            approved_at=datetime.now(timezone.utc),
            trip_summary=trip_summary2,
            days=[],
            booking_ids=[],
        )
        await store.save_itinerary(other_itinerary)

        # Query by consultation
        results = await store.get_itineraries_by_consultation("cons_shared")

        assert len(results) == 3
        itinerary_ids = [itn.itinerary_id for itn in results]
        assert "itn_0" in itinerary_ids
        assert "itn_1" in itinerary_ids
        assert "itn_2" in itinerary_ids
        assert "itn_other" not in itinerary_ids

    @pytest.mark.asyncio
    async def test_get_itineraries_by_consultation_empty(
        self, store: InMemoryItineraryStore
    ) -> None:
        """Test querying with no matching itineraries returns empty list."""
        results = await store.get_itineraries_by_consultation("cons_nonexistent")

        assert results == []

    def test_clear(self, store: InMemoryItineraryStore) -> None:
        """Test clearing the store."""
        store.clear()
        # Verify it doesn't raise
        assert store._itineraries == {}


class TestItineraryStore:
    """Tests for ItineraryStore with mocked Cosmos container."""

    @pytest.fixture
    def mock_container(self) -> MagicMock:
        """Create a mock Cosmos container."""
        container = MagicMock()
        container.read_item = AsyncMock()
        container.upsert_item = AsyncMock()
        container.delete_item = AsyncMock()
        container.query_items = MagicMock()
        return container

    @pytest.fixture
    def store(self, mock_container: MagicMock) -> ItineraryStore:
        """Create an ItineraryStore with mocked container."""
        return ItineraryStore(mock_container)

    @pytest.fixture
    def sample_itinerary_dict(self) -> dict[str, Any]:
        """Create a sample itinerary dict as returned by Cosmos."""
        return {
            "id": "itn_cosmos",
            "itinerary_id": "itn_cosmos",
            "consultation_id": "cons_cosmos",
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "trip_summary": {
                "destination": "Paris, France",
                "start_date": (date.today() + timedelta(days=30)).isoformat(),
                "end_date": (date.today() + timedelta(days=35)).isoformat(),
                "travelers": 2,
                "trip_type": "leisure",
            },
            "days": [],
            "booking_ids": ["book_a", "book_b"],
            "total_estimated_cost": 2500.00,
            "ttl": 3024000,  # ~35 days
        }

    @pytest.mark.asyncio
    async def test_get_itinerary_found(
        self,
        store: ItineraryStore,
        mock_container: MagicMock,
        sample_itinerary_dict: dict[str, Any],
    ) -> None:
        """Test retrieving an existing itinerary from Cosmos."""
        mock_container.read_item.return_value = sample_itinerary_dict

        result = await store.get_itinerary("itn_cosmos")

        assert result is not None
        assert result.itinerary_id == "itn_cosmos"
        assert result.consultation_id == "cons_cosmos"
        assert result.trip_summary.destination == "Paris, France"
        mock_container.read_item.assert_called_once_with(
            item="itn_cosmos",
            partition_key="itn_cosmos",
        )

    @pytest.mark.asyncio
    async def test_get_itinerary_not_found(
        self, store: ItineraryStore, mock_container: MagicMock
    ) -> None:
        """Test retrieving a non-existent itinerary returns None."""
        error = Exception("Not found")
        error.status_code = 404  # type: ignore[attr-defined]
        mock_container.read_item.side_effect = error

        result = await store.get_itinerary("itn_missing")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_itinerary_error(
        self, store: ItineraryStore, mock_container: MagicMock
    ) -> None:
        """Test that non-404 errors are raised."""
        error = Exception("Server error")
        error.status_code = 500  # type: ignore[attr-defined]
        mock_container.read_item.side_effect = error

        with pytest.raises(Exception) as exc_info:
            await store.get_itinerary("itn_error")

        assert "Server error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_save_itinerary(
        self, store: ItineraryStore, mock_container: MagicMock
    ) -> None:
        """Test saving creates a new itinerary via upsert."""
        trip_summary = TripSummary(
            destination="London, UK",
            start_date=date.today() + timedelta(days=14),
            end_date=date.today() + timedelta(days=21),
            travelers=3,
        )
        itinerary = Itinerary(
            itinerary_id="itn_create",
            consultation_id="cons_create",
            approved_at=datetime.now(timezone.utc),
            trip_summary=trip_summary,
            days=[],
            booking_ids=[],
            total_estimated_cost=1500.00,
        )

        mock_container.upsert_item.return_value = {
            "id": "itn_create",
            "itinerary_id": "itn_create",
            "consultation_id": "cons_create",
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "trip_summary": trip_summary.to_dict(),
            "days": [],
            "booking_ids": [],
            "total_estimated_cost": 1500.00,
            "ttl": 3888000,
        }

        result = await store.save_itinerary(itinerary)

        assert result.itinerary_id == "itn_create"
        mock_container.upsert_item.assert_called_once()
        call_args = mock_container.upsert_item.call_args
        assert call_args.kwargs["body"]["itinerary_id"] == "itn_create"
        assert "ttl" in call_args.kwargs["body"]

    @pytest.mark.asyncio
    async def test_delete_itinerary_existing(
        self, store: ItineraryStore, mock_container: MagicMock
    ) -> None:
        """Test deleting an existing itinerary."""
        mock_container.delete_item.return_value = None

        result = await store.delete_itinerary("itn_delete")

        assert result is True
        mock_container.delete_item.assert_called_once_with(
            item="itn_delete",
            partition_key="itn_delete",
        )

    @pytest.mark.asyncio
    async def test_delete_itinerary_not_found(
        self, store: ItineraryStore, mock_container: MagicMock
    ) -> None:
        """Test deleting a non-existent itinerary returns False."""
        error = Exception("Not found")
        error.status_code = 404  # type: ignore[attr-defined]
        mock_container.delete_item.side_effect = error

        result = await store.delete_itinerary("itn_missing")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_itineraries_by_consultation(
        self,
        store: ItineraryStore,
        mock_container: MagicMock,
        sample_itinerary_dict: dict[str, Any],
    ) -> None:
        """Test querying itineraries by consultation_id."""
        # Set up async generator mock
        async def mock_query_items(*args: Any, **kwargs: Any) -> Any:
            yield sample_itinerary_dict

        mock_container.query_items.return_value = mock_query_items()

        results = await store.get_itineraries_by_consultation("cons_cosmos")

        assert len(results) == 1
        assert results[0].itinerary_id == "itn_cosmos"
        mock_container.query_items.assert_called_once()
        call_args = mock_container.query_items.call_args
        assert "consultation_id" in call_args.kwargs["query"]
        assert call_args.kwargs["enable_cross_partition_query"] is True


class TestItineraryStoreProtocol:
    """Tests for ItineraryStoreProtocol compliance."""

    def test_inmemory_store_is_protocol_compliant(self) -> None:
        """Test that InMemoryItineraryStore implements the protocol."""
        store = InMemoryItineraryStore()
        assert isinstance(store, ItineraryStoreProtocol)

    def test_itinerary_store_is_protocol_compliant(self) -> None:
        """Test that ItineraryStore implements the protocol."""
        mock_container = MagicMock()
        store = ItineraryStore(mock_container)
        assert isinstance(store, ItineraryStoreProtocol)
