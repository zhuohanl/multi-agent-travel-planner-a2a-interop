"""
Unit tests for BookingStore.

Tests cover:
- Basic CRUD operations (get, save, delete)
- Optimistic locking with etag
- Non-existent booking handling
- Batch retrieval
- Status updates
- TTL calculation
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator.models.booking import (
    Booking,
    BookingStatus,
    CancellationPolicy,
)
from src.orchestrator.storage.booking_store import (
    BookingConflictError,
    BookingStore,
    BookingStoreProtocol,
    InMemoryBookingStore,
    calculate_booking_ttl,
    DEFAULT_BOOKING_TTL,
)


class TestCalculateBookingTtl:
    """Tests for TTL calculation function."""

    def test_with_none_returns_default(self) -> None:
        """Test that None trip_end_date returns default TTL."""
        result = calculate_booking_ttl(None)
        assert result == DEFAULT_BOOKING_TTL

    def test_with_future_date(self) -> None:
        """Test TTL calculation with future trip_end_date."""
        future_date = date.today() + timedelta(days=10)
        result = calculate_booking_ttl(future_date)

        # Should be approximately (10 + 30) days in seconds
        expected_min = 39 * 24 * 60 * 60  # 39 days (accounting for time of day)
        expected_max = 41 * 24 * 60 * 60  # 41 days

        assert expected_min <= result <= expected_max

    def test_with_past_date_returns_minimum(self) -> None:
        """Test that past trip_end_date returns minimum TTL (1 day)."""
        past_date = date.today() - timedelta(days=60)
        result = calculate_booking_ttl(past_date)

        # Should be minimum of 1 day (86400 seconds)
        assert result == 86400

    def test_with_datetime(self) -> None:
        """Test TTL calculation with datetime input."""
        future_dt = datetime.now(timezone.utc) + timedelta(days=10)
        result = calculate_booking_ttl(future_dt)

        # Should be approximately (10 + 30) days in seconds
        expected_min = 39 * 24 * 60 * 60
        expected_max = 41 * 24 * 60 * 60

        assert expected_min <= result <= expected_max


class TestBookingConflictError:
    """Tests for BookingConflictError exception."""

    def test_with_booking_id(self) -> None:
        """Test error includes booking_id."""
        error = BookingConflictError("book_123")
        assert error.booking_id == "book_123"
        assert "book_123" in str(error)

    def test_with_custom_message(self) -> None:
        """Test error with custom message."""
        error = BookingConflictError("book_123", "Custom conflict message")
        assert error.booking_id == "book_123"
        assert "Custom conflict message" in str(error)


class TestInMemoryBookingStore:
    """Tests for InMemoryBookingStore."""

    @pytest.fixture
    def store(self) -> InMemoryBookingStore:
        """Create a fresh in-memory store for each test."""
        return InMemoryBookingStore()

    @pytest.fixture
    def sample_booking(self) -> Booking:
        """Create a sample booking for testing."""
        return Booking.create_unbooked(
            booking_id="book_test123",
            itinerary_id="itn_abc",
            item_type="hotel",
            details={"name": "Grand Hotel", "nights": 3},
            price=450.00,
            cancellation_policy=CancellationPolicy(
                is_cancellable=True,
                fee_percentage=0.10,
            ),
        )

    @pytest.mark.asyncio
    async def test_get_booking_found(
        self, store: InMemoryBookingStore, sample_booking: Booking
    ) -> None:
        """Test retrieving an existing booking."""
        await store.save_booking(sample_booking)

        result = await store.get_booking("book_test123")

        assert result is not None
        assert result.booking_id == "book_test123"
        assert result.itinerary_id == "itn_abc"
        assert result.item_type == "hotel"
        assert result.price == 450.00

    @pytest.mark.asyncio
    async def test_get_booking_not_found(
        self, store: InMemoryBookingStore
    ) -> None:
        """Test retrieving a non-existent booking returns None."""
        result = await store.get_booking("book_nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_save_booking(
        self, store: InMemoryBookingStore, sample_booking: Booking
    ) -> None:
        """Test saving creates a new booking."""
        result = await store.save_booking(sample_booking)

        assert result.booking_id == "book_test123"
        assert result.etag is not None

        # Verify it's persisted
        retrieved = await store.get_booking("book_test123")
        assert retrieved is not None
        assert retrieved.item_type == "hotel"

    @pytest.mark.asyncio
    async def test_save_booking_updates(
        self, store: InMemoryBookingStore, sample_booking: Booking
    ) -> None:
        """Test saving updates an existing booking."""
        saved = await store.save_booking(sample_booking)

        # Update it
        sample_booking.status = BookingStatus.PENDING
        sample_booking.status_reason = "Awaiting provider"
        updated = await store.save_booking(sample_booking)

        assert updated.status == BookingStatus.PENDING
        assert updated.status_reason == "Awaiting provider"
        # etag should change
        assert updated.etag != saved.etag

    @pytest.mark.asyncio
    async def test_save_booking_with_trip_end_date(
        self, store: InMemoryBookingStore, sample_booking: Booking
    ) -> None:
        """Test saving with trip_end_date sets TTL."""
        trip_end = date.today() + timedelta(days=10)
        result = await store.save_booking(sample_booking, trip_end_date=trip_end)

        # Check the stored doc has TTL
        stored = store._bookings["book_test123"]
        assert "ttl" in stored
        assert stored["trip_end_date"] == trip_end.isoformat()

    @pytest.mark.asyncio
    async def test_save_booking_with_etag_success(
        self, store: InMemoryBookingStore, sample_booking: Booking
    ) -> None:
        """Test saving with correct etag succeeds."""
        saved = await store.save_booking(sample_booking)

        # Update with correct etag
        sample_booking.status = BookingStatus.BOOKED
        result = await store.save_booking(sample_booking, if_match=saved.etag)

        assert result.status == BookingStatus.BOOKED

    @pytest.mark.asyncio
    async def test_save_booking_with_etag_conflict(
        self, store: InMemoryBookingStore, sample_booking: Booking
    ) -> None:
        """Test saving with stale etag raises BookingConflictError."""
        await store.save_booking(sample_booking)

        # Try to update with wrong etag
        sample_booking.status = BookingStatus.BOOKED
        with pytest.raises(BookingConflictError) as exc_info:
            await store.save_booking(sample_booking, if_match="wrong_etag")

        assert exc_info.value.booking_id == "book_test123"

    @pytest.mark.asyncio
    async def test_delete_booking_existing(
        self, store: InMemoryBookingStore, sample_booking: Booking
    ) -> None:
        """Test deleting an existing booking."""
        await store.save_booking(sample_booking)

        result = await store.delete_booking("book_test123")

        assert result is True
        assert await store.get_booking("book_test123") is None

    @pytest.mark.asyncio
    async def test_delete_booking_not_found(
        self, store: InMemoryBookingStore
    ) -> None:
        """Test deleting a non-existent booking returns False."""
        result = await store.delete_booking("book_nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_bookings_by_ids(
        self, store: InMemoryBookingStore
    ) -> None:
        """Test retrieving multiple bookings by IDs."""
        # Create multiple bookings
        for i in range(3):
            booking = Booking.create_unbooked(
                booking_id=f"book_{i}",
                itinerary_id="itn_abc",
                item_type="activity",
                details={"name": f"Activity {i}"},
                price=100.0 + i * 50,
                cancellation_policy=CancellationPolicy(is_cancellable=True),
            )
            await store.save_booking(booking)

        # Retrieve subset
        results = await store.get_bookings_by_ids(["book_0", "book_2", "book_nonexistent"])

        assert len(results) == 2
        booking_ids = [b.booking_id for b in results]
        assert "book_0" in booking_ids
        assert "book_2" in booking_ids
        assert "book_nonexistent" not in booking_ids

    @pytest.mark.asyncio
    async def test_get_bookings_by_ids_empty(
        self, store: InMemoryBookingStore
    ) -> None:
        """Test retrieving with empty list returns empty list."""
        results = await store.get_bookings_by_ids([])

        assert results == []

    @pytest.mark.asyncio
    async def test_update_booking_status(
        self, store: InMemoryBookingStore, sample_booking: Booking
    ) -> None:
        """Test updating booking status."""
        await store.save_booking(sample_booking)

        result = await store.update_booking_status(
            booking_id="book_test123",
            status=BookingStatus.PENDING,
            status_reason="Processing payment",
        )

        assert result is not None
        assert result.status == BookingStatus.PENDING
        assert result.status_reason == "Processing payment"

    @pytest.mark.asyncio
    async def test_update_booking_status_not_found(
        self, store: InMemoryBookingStore
    ) -> None:
        """Test updating status of non-existent booking returns None."""
        result = await store.update_booking_status(
            booking_id="book_nonexistent",
            status=BookingStatus.BOOKED,
        )

        assert result is None

    def test_clear(self, store: InMemoryBookingStore) -> None:
        """Test clearing the store."""
        store.clear()
        # Verify it doesn't raise and counter is reset
        assert store._etag_counter == 0


class TestBookingStore:
    """Tests for BookingStore with mocked Cosmos container."""

    @pytest.fixture
    def mock_container(self) -> MagicMock:
        """Create a mock Cosmos container."""
        container = MagicMock()
        container.read_item = AsyncMock()
        container.upsert_item = AsyncMock()
        container.replace_item = AsyncMock()
        container.delete_item = AsyncMock()
        return container

    @pytest.fixture
    def store(self, mock_container: MagicMock) -> BookingStore:
        """Create a BookingStore with mocked container."""
        return BookingStore(mock_container)

    @pytest.fixture
    def sample_booking_dict(self) -> dict[str, Any]:
        """Create a sample booking dict as returned by Cosmos."""
        return {
            "id": "book_cosmos",
            "booking_id": "book_cosmos",
            "itinerary_id": "itn_cosmos",
            "item_type": "flight",
            "details": {"airline": "Test Air", "flight": "TA123"},
            "status": "unbooked",
            "cancellation_policy": {
                "is_cancellable": True,
                "fee_percentage": 0.0,
                "fee_fixed": 0.0,
            },
            "price": 250.00,
            "_etag": '"etag_123"',
        }

    @pytest.mark.asyncio
    async def test_get_booking_found(
        self,
        store: BookingStore,
        mock_container: MagicMock,
        sample_booking_dict: dict[str, Any],
    ) -> None:
        """Test retrieving an existing booking from Cosmos."""
        mock_container.read_item.return_value = sample_booking_dict

        result = await store.get_booking("book_cosmos")

        assert result is not None
        assert result.booking_id == "book_cosmos"
        assert result.itinerary_id == "itn_cosmos"
        assert result.item_type == "flight"
        assert result.etag == '"etag_123"'
        mock_container.read_item.assert_called_once_with(
            item="book_cosmos",
            partition_key="book_cosmos",
        )

    @pytest.mark.asyncio
    async def test_get_booking_not_found(
        self, store: BookingStore, mock_container: MagicMock
    ) -> None:
        """Test retrieving a non-existent booking returns None."""
        error = Exception("Not found")
        error.status_code = 404  # type: ignore[attr-defined]
        mock_container.read_item.side_effect = error

        result = await store.get_booking("book_missing")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_booking_error(
        self, store: BookingStore, mock_container: MagicMock
    ) -> None:
        """Test that non-404 errors are raised."""
        error = Exception("Server error")
        error.status_code = 500  # type: ignore[attr-defined]
        mock_container.read_item.side_effect = error

        with pytest.raises(Exception) as exc_info:
            await store.get_booking("book_error")

        assert "Server error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_save_booking(
        self, store: BookingStore, mock_container: MagicMock
    ) -> None:
        """Test saving creates a new booking via upsert."""
        mock_container.upsert_item.return_value = {
            "id": "book_create",
            "booking_id": "book_create",
            "itinerary_id": "itn_create",
            "item_type": "hotel",
            "details": {},
            "status": "unbooked",
            "cancellation_policy": {"is_cancellable": True},
            "price": 100.0,
            "_etag": '"new_etag"',
        }

        booking = Booking.create_unbooked(
            booking_id="book_create",
            itinerary_id="itn_create",
            item_type="hotel",
            details={},
            price=100.0,
            cancellation_policy=CancellationPolicy(is_cancellable=True),
        )
        result = await store.save_booking(booking)

        assert result.etag == '"new_etag"'
        mock_container.upsert_item.assert_called_once()
        call_args = mock_container.upsert_item.call_args
        assert call_args.kwargs["body"]["booking_id"] == "book_create"
        assert "ttl" in call_args.kwargs["body"]

    @pytest.mark.asyncio
    async def test_save_booking_with_trip_end_date(
        self, store: BookingStore, mock_container: MagicMock
    ) -> None:
        """Test saving with trip_end_date sets correct TTL."""
        mock_container.upsert_item.return_value = {
            "id": "book_ttl",
            "booking_id": "book_ttl",
            "itinerary_id": "itn_ttl",
            "item_type": "activity",
            "details": {},
            "status": "unbooked",
            "cancellation_policy": {"is_cancellable": True},
            "price": 50.0,
            "_etag": '"etag"',
        }

        booking = Booking.create_unbooked(
            booking_id="book_ttl",
            itinerary_id="itn_ttl",
            item_type="activity",
            details={},
            price=50.0,
            cancellation_policy=CancellationPolicy(is_cancellable=True),
        )
        trip_end = date.today() + timedelta(days=10)
        await store.save_booking(booking, trip_end_date=trip_end)

        call_args = mock_container.upsert_item.call_args
        body = call_args.kwargs["body"]
        assert "trip_end_date" in body
        assert body["trip_end_date"] == trip_end.isoformat()

    @pytest.mark.asyncio
    async def test_save_booking_with_etag_uses_replace(
        self, store: BookingStore, mock_container: MagicMock
    ) -> None:
        """Test saving with etag uses replace_item for optimistic locking."""
        mock_container.replace_item.return_value = {
            "id": "book_replace",
            "booking_id": "book_replace",
            "itinerary_id": "itn_replace",
            "item_type": "hotel",
            "details": {},
            "status": "booked",
            "cancellation_policy": {"is_cancellable": True},
            "price": 200.0,
            "_etag": '"new_etag"',
        }

        booking = Booking.create_unbooked(
            booking_id="book_replace",
            itinerary_id="itn_replace",
            item_type="hotel",
            details={},
            price=200.0,
            cancellation_policy=CancellationPolicy(is_cancellable=True),
        )
        booking.status = BookingStatus.BOOKED
        result = await store.save_booking(booking, if_match='"old_etag"')

        assert result.etag == '"new_etag"'
        mock_container.replace_item.assert_called_once()
        call_args = mock_container.replace_item.call_args
        assert call_args.kwargs["item"] == "book_replace"
        assert call_args.kwargs["if_match"] == '"old_etag"'

    @pytest.mark.asyncio
    async def test_save_booking_conflict(
        self, store: BookingStore, mock_container: MagicMock
    ) -> None:
        """Test saving with stale etag raises BookingConflictError."""
        error = Exception("Precondition failed")
        error.status_code = 412  # type: ignore[attr-defined]
        mock_container.replace_item.side_effect = error

        booking = Booking.create_unbooked(
            booking_id="book_conflict",
            itinerary_id="itn_conflict",
            item_type="hotel",
            details={},
            price=100.0,
            cancellation_policy=CancellationPolicy(is_cancellable=True),
        )
        with pytest.raises(BookingConflictError) as exc_info:
            await store.save_booking(booking, if_match='"stale_etag"')

        assert exc_info.value.booking_id == "book_conflict"

    @pytest.mark.asyncio
    async def test_delete_booking_existing(
        self, store: BookingStore, mock_container: MagicMock
    ) -> None:
        """Test deleting an existing booking."""
        mock_container.delete_item.return_value = None

        result = await store.delete_booking("book_delete")

        assert result is True
        mock_container.delete_item.assert_called_once_with(
            item="book_delete",
            partition_key="book_delete",
        )

    @pytest.mark.asyncio
    async def test_delete_booking_not_found(
        self, store: BookingStore, mock_container: MagicMock
    ) -> None:
        """Test deleting a non-existent booking returns False."""
        error = Exception("Not found")
        error.status_code = 404  # type: ignore[attr-defined]
        mock_container.delete_item.side_effect = error

        result = await store.delete_booking("book_missing")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_bookings_by_ids(
        self,
        store: BookingStore,
        mock_container: MagicMock,
        sample_booking_dict: dict[str, Any],
    ) -> None:
        """Test retrieving multiple bookings."""
        # First call returns booking, second returns 404
        error = Exception("Not found")
        error.status_code = 404  # type: ignore[attr-defined]
        mock_container.read_item.side_effect = [sample_booking_dict, error]

        results = await store.get_bookings_by_ids(["book_cosmos", "book_missing"])

        assert len(results) == 1
        assert results[0].booking_id == "book_cosmos"

    @pytest.mark.asyncio
    async def test_update_booking_status(
        self,
        store: BookingStore,
        mock_container: MagicMock,
        sample_booking_dict: dict[str, Any],
    ) -> None:
        """Test updating booking status."""
        # First read returns original
        mock_container.read_item.return_value = sample_booking_dict
        # Save returns updated
        updated_dict = sample_booking_dict.copy()
        updated_dict["status"] = "booked"
        updated_dict["status_reason"] = "Confirmed"
        updated_dict["_etag"] = '"new_etag"'
        mock_container.replace_item.return_value = updated_dict

        result = await store.update_booking_status(
            booking_id="book_cosmos",
            status=BookingStatus.BOOKED,
            status_reason="Confirmed",
        )

        assert result is not None
        assert result.status == BookingStatus.BOOKED

    @pytest.mark.asyncio
    async def test_update_booking_status_not_found(
        self, store: BookingStore, mock_container: MagicMock
    ) -> None:
        """Test updating status of non-existent booking returns None."""
        error = Exception("Not found")
        error.status_code = 404  # type: ignore[attr-defined]
        mock_container.read_item.side_effect = error

        result = await store.update_booking_status(
            booking_id="book_missing",
            status=BookingStatus.BOOKED,
        )

        assert result is None


class TestBookingStoreProtocol:
    """Tests for BookingStoreProtocol compliance."""

    def test_inmemory_store_is_protocol_compliant(self) -> None:
        """Test that InMemoryBookingStore implements the protocol."""
        store = InMemoryBookingStore()
        assert isinstance(store, BookingStoreProtocol)

    def test_booking_store_is_protocol_compliant(self) -> None:
        """Test that BookingStore implements the protocol."""
        mock_container = MagicMock()
        store = BookingStore(mock_container)
        assert isinstance(store, BookingStoreProtocol)
