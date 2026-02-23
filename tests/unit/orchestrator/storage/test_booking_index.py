"""
Unit tests for BookingIndexStore.

Tests cover:
- Basic CRUD operations (get, add, delete)
- Non-existent booking handling
- TTL calculation based on trip_end_date
- Serialization/deserialization
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator.storage.booking_index import (
    BookingIndexEntry,
    BookingIndexStore,
    InMemoryBookingIndexStore,
    calculate_booking_index_ttl,
    DEFAULT_BOOKING_INDEX_TTL,
)


class TestBookingIndexEntry:
    """Tests for BookingIndexEntry dataclass."""

    def test_default_values(self) -> None:
        """Test that defaults are applied correctly."""
        entry = BookingIndexEntry(
            booking_id="book_123",
            consultation_id="cons_456",
            session_id="sess_789",
        )

        assert entry.booking_id == "book_123"
        assert entry.consultation_id == "cons_456"
        assert entry.session_id == "sess_789"
        assert entry.trip_end_date is None

    def test_with_trip_end_date(self) -> None:
        """Test entry with trip_end_date."""
        end_date = date(2026, 3, 20)
        entry = BookingIndexEntry(
            booking_id="book_123",
            consultation_id="cons_456",
            session_id="sess_789",
            trip_end_date=end_date,
        )

        assert entry.trip_end_date == end_date

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        end_date = date(2026, 3, 20)
        entry = BookingIndexEntry(
            booking_id="book_abc123",
            consultation_id="cons_xyz789",
            session_id="sess_qrs456",
            trip_end_date=end_date,
        )

        doc = entry.to_dict()

        assert doc["id"] == "book_abc123"
        assert doc["booking_id"] == "book_abc123"
        assert doc["consultation_id"] == "cons_xyz789"
        assert doc["session_id"] == "sess_qrs456"
        assert doc["trip_end_date"] == "2026-03-20"
        assert "ttl" in doc
        assert doc["ttl"] > 0

    def test_to_dict_without_trip_end_date(self) -> None:
        """Test serialization without trip_end_date."""
        entry = BookingIndexEntry(
            booking_id="book_nodate",
            consultation_id="cons_nodate",
            session_id="sess_nodate",
        )

        doc = entry.to_dict()

        assert doc["id"] == "book_nodate"
        assert doc["booking_id"] == "book_nodate"
        assert "trip_end_date" not in doc
        assert doc["ttl"] == DEFAULT_BOOKING_INDEX_TTL

    def test_from_dict(self) -> None:
        """Test deserialization from dictionary."""
        doc = {
            "id": "book_abc123",
            "booking_id": "book_abc123",
            "consultation_id": "cons_xyz789",
            "session_id": "sess_qrs456",
            "trip_end_date": "2026-03-20",
        }

        entry = BookingIndexEntry.from_dict(doc)

        assert entry.booking_id == "book_abc123"
        assert entry.consultation_id == "cons_xyz789"
        assert entry.session_id == "sess_qrs456"
        assert entry.trip_end_date == date(2026, 3, 20)

    def test_from_dict_without_trip_end_date(self) -> None:
        """Test deserialization without trip_end_date."""
        doc = {
            "id": "book_nodate",
            "booking_id": "book_nodate",
            "consultation_id": "cons_nodate",
            "session_id": "sess_nodate",
        }

        entry = BookingIndexEntry.from_dict(doc)

        assert entry.booking_id == "book_nodate"
        assert entry.trip_end_date is None

    def test_from_dict_with_missing_fields(self) -> None:
        """Test deserialization handles missing fields gracefully."""
        doc = {"id": "book_minimal"}

        entry = BookingIndexEntry.from_dict(doc)

        assert entry.booking_id == "book_minimal"
        assert entry.consultation_id == ""
        assert entry.session_id == ""
        assert entry.trip_end_date is None

    def test_roundtrip_serialization(self) -> None:
        """Test that to_dict and from_dict are inverses."""
        original = BookingIndexEntry(
            booking_id="book_roundtrip",
            consultation_id="cons_rt",
            session_id="sess_rt",
            trip_end_date=date(2026, 4, 15),
        )

        doc = original.to_dict()
        restored = BookingIndexEntry.from_dict(doc)

        assert restored.booking_id == original.booking_id
        assert restored.consultation_id == original.consultation_id
        assert restored.session_id == original.session_id
        assert restored.trip_end_date == original.trip_end_date


class TestCalculateBookingIndexTtl:
    """Tests for calculate_booking_index_ttl function."""

    def test_with_none_returns_default(self) -> None:
        """Test that None trip_end_date returns default TTL."""
        ttl = calculate_booking_index_ttl(None)

        assert ttl == DEFAULT_BOOKING_INDEX_TTL

    def test_with_future_date(self) -> None:
        """Test TTL calculation with a future trip_end_date."""
        # Set trip end date 10 days from now
        future_date = date.today() + timedelta(days=10)
        ttl = calculate_booking_index_ttl(future_date)

        # Should be approximately 40 days (10 + 30) in seconds
        expected_min = 39 * 24 * 60 * 60  # At least 39 days
        expected_max = 41 * 24 * 60 * 60  # At most 41 days

        assert expected_min <= ttl <= expected_max

    def test_with_past_date_returns_minimum(self) -> None:
        """Test that past date returns minimum TTL (1 day)."""
        past_date = date(2020, 1, 1)
        ttl = calculate_booking_index_ttl(past_date)

        # Should return minimum 1 day
        assert ttl == 86400

    def test_with_datetime(self) -> None:
        """Test TTL calculation with datetime input."""
        future_dt = datetime.now(timezone.utc) + timedelta(days=15)
        ttl = calculate_booking_index_ttl(future_dt.date())

        # Should be approximately 45 days in seconds
        expected_min = 44 * 24 * 60 * 60
        expected_max = 46 * 24 * 60 * 60

        assert expected_min <= ttl <= expected_max


class TestInMemoryBookingIndexStore:
    """Tests for InMemoryBookingIndexStore."""

    @pytest.fixture
    def store(self) -> InMemoryBookingIndexStore:
        """Create a fresh in-memory store for each test."""
        return InMemoryBookingIndexStore()

    @pytest.mark.asyncio
    async def test_get_session_for_booking_found(
        self, store: InMemoryBookingIndexStore
    ) -> None:
        """Test retrieving an existing index entry."""
        await store.add_booking_index(
            booking_id="book_test",
            consultation_id="cons_test",
            session_id="sess_test",
            trip_end_date=date(2026, 3, 20),
        )

        result = await store.get_session_for_booking("book_test")

        assert result is not None
        assert result.booking_id == "book_test"
        assert result.consultation_id == "cons_test"
        assert result.session_id == "sess_test"
        assert result.trip_end_date == date(2026, 3, 20)

    @pytest.mark.asyncio
    async def test_get_session_for_booking_not_found(
        self, store: InMemoryBookingIndexStore
    ) -> None:
        """Test retrieving a non-existent entry returns None."""
        result = await store.get_session_for_booking("book_nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_add_booking_index_sets_ttl(
        self, store: InMemoryBookingIndexStore
    ) -> None:
        """Test that add_booking_index sets TTL based on trip_end_date."""
        trip_end = date.today() + timedelta(days=10)
        await store.add_booking_index(
            booking_id="book_ttl",
            consultation_id="cons_ttl",
            session_id="sess_ttl",
            trip_end_date=trip_end,
        )

        # Check internal storage has TTL set
        doc = store._index["book_ttl"]
        assert "ttl" in doc
        # TTL should be approximately 40 days (10 + 30)
        expected_min = 39 * 24 * 60 * 60
        expected_max = 41 * 24 * 60 * 60
        assert expected_min <= doc["ttl"] <= expected_max

    @pytest.mark.asyncio
    async def test_add_booking_index_default_ttl(
        self, store: InMemoryBookingIndexStore
    ) -> None:
        """Test that add_booking_index uses default TTL when no trip_end_date."""
        await store.add_booking_index(
            booking_id="book_default_ttl",
            consultation_id="cons_default",
            session_id="sess_default",
        )

        doc = store._index["book_default_ttl"]
        assert doc["ttl"] == DEFAULT_BOOKING_INDEX_TTL

    @pytest.mark.asyncio
    async def test_add_booking_index_updates_existing(
        self, store: InMemoryBookingIndexStore
    ) -> None:
        """Test that add_booking_index updates an existing entry (upsert)."""
        # Create initial entry
        await store.add_booking_index(
            booking_id="book_update",
            consultation_id="cons_old",
            session_id="sess_old",
        )

        # Update with new values
        await store.add_booking_index(
            booking_id="book_update",
            consultation_id="cons_new",
            session_id="sess_new",
            trip_end_date=date(2026, 5, 1),
        )

        # Verify updated
        result = await store.get_session_for_booking("book_update")
        assert result is not None
        assert result.consultation_id == "cons_new"
        assert result.session_id == "sess_new"
        assert result.trip_end_date == date(2026, 5, 1)

    @pytest.mark.asyncio
    async def test_delete_booking_index(
        self, store: InMemoryBookingIndexStore
    ) -> None:
        """Test deleting an existing entry."""
        await store.add_booking_index(
            booking_id="book_delete",
            consultation_id="cons_delete",
            session_id="sess_delete",
        )

        result = await store.delete_booking_index("book_delete")

        assert result is True
        assert await store.get_session_for_booking("book_delete") is None

    @pytest.mark.asyncio
    async def test_delete_booking_index_not_found(
        self, store: InMemoryBookingIndexStore
    ) -> None:
        """Test deleting a non-existent entry returns False."""
        result = await store.delete_booking_index("book_nonexistent")

        assert result is False

    def test_clear(self, store: InMemoryBookingIndexStore) -> None:
        """Test clearing the store."""
        # Just verify it doesn't raise
        store.clear()


class TestBookingIndexStore:
    """Tests for BookingIndexStore with mocked Cosmos container."""

    @pytest.fixture
    def mock_container(self) -> MagicMock:
        """Create a mock Cosmos container."""
        container = MagicMock()
        container.read_item = AsyncMock()
        container.upsert_item = AsyncMock()
        container.delete_item = AsyncMock()
        return container

    @pytest.fixture
    def store(self, mock_container: MagicMock) -> BookingIndexStore:
        """Create a BookingIndexStore with mocked container."""
        return BookingIndexStore(mock_container)

    @pytest.mark.asyncio
    async def test_get_session_for_booking_found(
        self, store: BookingIndexStore, mock_container: MagicMock
    ) -> None:
        """Test retrieving an existing entry from Cosmos."""
        mock_container.read_item.return_value = {
            "id": "book_cosmos",
            "booking_id": "book_cosmos",
            "consultation_id": "cons_cosmos",
            "session_id": "sess_cosmos",
            "trip_end_date": "2026-03-20",
        }

        result = await store.get_session_for_booking("book_cosmos")

        assert result is not None
        assert result.booking_id == "book_cosmos"
        assert result.consultation_id == "cons_cosmos"
        assert result.session_id == "sess_cosmos"
        assert result.trip_end_date == date(2026, 3, 20)
        mock_container.read_item.assert_called_once_with(
            item="book_cosmos",
            partition_key="book_cosmos",
        )

    @pytest.mark.asyncio
    async def test_get_session_for_booking_not_found(
        self, store: BookingIndexStore, mock_container: MagicMock
    ) -> None:
        """Test retrieving a non-existent entry returns None."""
        # Simulate 404 error
        error = Exception("Not found")
        error.status_code = 404  # type: ignore[attr-defined]
        mock_container.read_item.side_effect = error

        result = await store.get_session_for_booking("book_missing")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_session_error(
        self, store: BookingIndexStore, mock_container: MagicMock
    ) -> None:
        """Test that non-404 errors are raised."""
        error = Exception("Server error")
        error.status_code = 500  # type: ignore[attr-defined]
        mock_container.read_item.side_effect = error

        with pytest.raises(Exception) as exc_info:
            await store.get_session_for_booking("book_error")

        assert "Server error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_add_booking_index_sets_ttl(
        self, store: BookingIndexStore, mock_container: MagicMock
    ) -> None:
        """Test that add_booking_index sets TTL based on trip_end_date."""
        trip_end = date.today() + timedelta(days=10)
        mock_container.upsert_item.return_value = {
            "id": "book_ttl",
            "booking_id": "book_ttl",
            "consultation_id": "cons_ttl",
            "session_id": "sess_ttl",
            "trip_end_date": trip_end.isoformat(),
        }

        await store.add_booking_index(
            booking_id="book_ttl",
            consultation_id="cons_ttl",
            session_id="sess_ttl",
            trip_end_date=trip_end,
        )

        mock_container.upsert_item.assert_called_once()
        call_args = mock_container.upsert_item.call_args
        body = call_args.kwargs["body"]
        assert body["booking_id"] == "book_ttl"
        assert body["consultation_id"] == "cons_ttl"
        assert body["session_id"] == "sess_ttl"
        assert body["trip_end_date"] == trip_end.isoformat()
        assert "ttl" in body
        # TTL should be approximately 40 days
        expected_min = 39 * 24 * 60 * 60
        expected_max = 41 * 24 * 60 * 60
        assert expected_min <= body["ttl"] <= expected_max

    @pytest.mark.asyncio
    async def test_add_booking_index_default_ttl(
        self, store: BookingIndexStore, mock_container: MagicMock
    ) -> None:
        """Test add_booking_index with default TTL (no trip_end_date)."""
        mock_container.upsert_item.return_value = {
            "id": "book_default",
            "booking_id": "book_default",
            "consultation_id": "cons_default",
            "session_id": "sess_default",
        }

        await store.add_booking_index(
            booking_id="book_default",
            consultation_id="cons_default",
            session_id="sess_default",
        )

        call_args = mock_container.upsert_item.call_args
        body = call_args.kwargs["body"]
        assert body["ttl"] == DEFAULT_BOOKING_INDEX_TTL
        assert "trip_end_date" not in body

    @pytest.mark.asyncio
    async def test_add_booking_index_error(
        self, store: BookingIndexStore, mock_container: MagicMock
    ) -> None:
        """Test that errors from Cosmos are raised."""
        error = Exception("Cosmos error")
        mock_container.upsert_item.side_effect = error

        with pytest.raises(Exception) as exc_info:
            await store.add_booking_index(
                booking_id="book_error",
                consultation_id="cons_error",
                session_id="sess_error",
            )

        assert "Cosmos error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_delete_booking_index(
        self, store: BookingIndexStore, mock_container: MagicMock
    ) -> None:
        """Test deleting an existing entry."""
        mock_container.delete_item.return_value = None

        result = await store.delete_booking_index("book_delete")

        assert result is True
        mock_container.delete_item.assert_called_once_with(
            item="book_delete",
            partition_key="book_delete",
        )

    @pytest.mark.asyncio
    async def test_delete_booking_index_not_found(
        self, store: BookingIndexStore, mock_container: MagicMock
    ) -> None:
        """Test deleting a non-existent entry returns False."""
        error = Exception("Not found")
        error.status_code = 404  # type: ignore[attr-defined]
        mock_container.delete_item.side_effect = error

        result = await store.delete_booking_index("book_missing")

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_booking_index_error(
        self, store: BookingIndexStore, mock_container: MagicMock
    ) -> None:
        """Test that non-404 errors on delete are raised."""
        error = Exception("Server error")
        error.status_code = 500  # type: ignore[attr-defined]
        mock_container.delete_item.side_effect = error

        with pytest.raises(Exception) as exc_info:
            await store.delete_booking_index("book_error")

        assert "Server error" in str(exc_info.value)
