"""
Unit tests for CosmosBookingStore adapter.

Tests the CosmosBookingStore which implements the shared BookingStore
interface using local caching with optional Cosmos DB persistence.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.shared.models import Booking, BookingStatus
from src.shared.storage.cosmos_booking_store import CosmosBookingStore


@pytest.fixture
def mock_container():
    """Create a mock Cosmos container."""
    container = AsyncMock()
    container.upsert_item = AsyncMock()
    container.read_item = AsyncMock()
    container.query_items = MagicMock()
    return container


@pytest.fixture
def mock_booking_index_store():
    """Create a mock booking index store."""
    store = AsyncMock()
    store.get_session_for_booking = AsyncMock(return_value=None)
    store.add_booking_index = AsyncMock()
    store.delete_booking_index = AsyncMock(return_value=True)
    return store


@pytest.fixture
def cosmos_booking_store():
    """Create a CosmosBookingStore with no Cosmos container (cache-only mode)."""
    return CosmosBookingStore()


@pytest.fixture
def cosmos_booking_store_with_container(mock_container):
    """Create a CosmosBookingStore with a mocked Cosmos container."""
    return CosmosBookingStore(container=mock_container)


@pytest.fixture
def cosmos_booking_store_full(mock_container, mock_booking_index_store):
    """Create a CosmosBookingStore with all dependencies."""
    return CosmosBookingStore(
        container=mock_container,
        booking_index_store=mock_booking_index_store,
    )


class TestCosmosBookingStoreCreate:
    """Tests for creating bookings."""

    @pytest.mark.asyncio
    async def test_create_generates_booking_id(
        self, cosmos_booking_store
    ):
        """Test that create generates a booking ID with book_ prefix."""
        result = await cosmos_booking_store.create(
            consultation_id="cons_test",
            booking_type="hotel",
        )

        assert result.id.startswith("book_")
        assert len(result.id) > 5

    @pytest.mark.asyncio
    async def test_create_sets_consultation_id(
        self, cosmos_booking_store
    ):
        """Test that create sets the consultation_id correctly."""
        consultation_id = "cons_test123"
        result = await cosmos_booking_store.create(
            consultation_id=consultation_id,
            booking_type="flight",
        )

        assert result.consultation_id == consultation_id

    @pytest.mark.asyncio
    async def test_create_sets_booking_type(
        self, cosmos_booking_store
    ):
        """Test that create sets the booking type correctly."""
        result = await cosmos_booking_store.create(
            consultation_id="cons_test",
            booking_type="activity",
        )

        assert result.type == "activity"

    @pytest.mark.asyncio
    async def test_create_sets_pending_status(
        self, cosmos_booking_store
    ):
        """Test that create sets status to PENDING."""
        result = await cosmos_booking_store.create(
            consultation_id="cons_test",
            booking_type="hotel",
        )

        assert result.status == BookingStatus.PENDING

    @pytest.mark.asyncio
    async def test_create_stores_details(
        self, cosmos_booking_store
    ):
        """Test that create stores the details dict."""
        details = {"room_type": "deluxe", "nights": 3}
        result = await cosmos_booking_store.create(
            consultation_id="cons_test",
            booking_type="hotel",
            details=details,
        )

        assert result.details == details

    @pytest.mark.asyncio
    async def test_create_persists_to_cosmos(
        self, cosmos_booking_store_with_container, mock_container
    ):
        """Test that create persists to Cosmos when container is available."""
        result = await cosmos_booking_store_with_container.create(
            consultation_id="cons_test",
            booking_type="hotel",
        )

        mock_container.upsert_item.assert_called_once()
        call_args = mock_container.upsert_item.call_args
        assert call_args.kwargs["body"]["booking_id"] == result.id

    @pytest.mark.asyncio
    async def test_create_updates_booking_index(
        self, cosmos_booking_store_full, mock_booking_index_store
    ):
        """Test that create updates the booking index when available."""
        result = await cosmos_booking_store_full.create(
            consultation_id="cons_test",
            booking_type="hotel",
        )

        mock_booking_index_store.add_booking_index.assert_called_once_with(
            booking_id=result.id,
            consultation_id="cons_test",
            session_id="",
        )


class TestCosmosBookingStoreGet:
    """Tests for getting bookings."""

    @pytest.mark.asyncio
    async def test_get_returns_cached_booking(
        self, cosmos_booking_store
    ):
        """Test that get returns a cached booking."""
        created = await cosmos_booking_store.create(
            consultation_id="cons_test",
            booking_type="hotel",
        )

        result = await cosmos_booking_store.get(created.id)

        assert result is not None
        assert result.id == created.id

    @pytest.mark.asyncio
    async def test_get_returns_none_for_unknown_id(
        self, cosmos_booking_store
    ):
        """Test that get returns None for unknown booking ID."""
        result = await cosmos_booking_store.get("book_unknown")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_fetches_from_cosmos(
        self, cosmos_booking_store_with_container, mock_container
    ):
        """Test that get fetches from Cosmos for non-cached bookings."""
        mock_container.read_item.return_value = {
            "id": "book_cosmos123",
            "booking_id": "book_cosmos123",
            "consultation_id": "cons_cosmos",
            "type": "flight",
            "status": "pending",
            "details": {},
        }

        result = await cosmos_booking_store_with_container.get("book_cosmos123")

        assert result is not None
        assert result.id == "book_cosmos123"
        mock_container.read_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_returns_none_for_cosmos_404(
        self, cosmos_booking_store_with_container, mock_container
    ):
        """Test that get returns None when Cosmos returns 404."""
        error = Exception("Not found")
        error.status_code = 404
        mock_container.read_item.side_effect = error

        result = await cosmos_booking_store_with_container.get("book_notfound")

        assert result is None


class TestCosmosBookingStoreGetByConsultation:
    """Tests for getting bookings by consultation."""

    @pytest.mark.asyncio
    async def test_get_by_consultation_returns_bookings(
        self, cosmos_booking_store
    ):
        """Test that get_by_consultation returns bookings for a consultation."""
        # Create multiple bookings for the same consultation
        await cosmos_booking_store.create(
            consultation_id="cons_multi",
            booking_type="hotel",
        )
        await cosmos_booking_store.create(
            consultation_id="cons_multi",
            booking_type="flight",
        )

        result = await cosmos_booking_store.get_by_consultation("cons_multi")

        assert len(result) == 2
        assert all(b.consultation_id == "cons_multi" for b in result)

    @pytest.mark.asyncio
    async def test_get_by_consultation_returns_empty_for_unknown(
        self, cosmos_booking_store
    ):
        """Test that get_by_consultation returns empty list for unknown consultation."""
        result = await cosmos_booking_store.get_by_consultation("cons_unknown")

        assert result == []


class TestCosmosBookingStoreUpdate:
    """Tests for updating bookings."""

    @pytest.mark.asyncio
    async def test_update_modifies_booking(
        self, cosmos_booking_store
    ):
        """Test that update modifies a booking."""
        created = await cosmos_booking_store.create(
            consultation_id="cons_update",
            booking_type="hotel",
        )
        created.status = BookingStatus.CONFIRMED

        result = await cosmos_booking_store.update(created)

        assert result.status == BookingStatus.CONFIRMED

        # Verify the cache was updated
        fetched = await cosmos_booking_store.get(created.id)
        assert fetched is not None
        assert fetched.status == BookingStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_update_raises_for_unknown(
        self, cosmos_booking_store
    ):
        """Test that update raises KeyError for unknown booking."""
        booking = Booking(
            id="book_unknown",
            consultation_id="cons_test",
            type="hotel",
            status=BookingStatus.PENDING,
            details={},
        )

        with pytest.raises(KeyError):
            await cosmos_booking_store.update(booking)

    @pytest.mark.asyncio
    async def test_update_persists_to_cosmos(
        self, cosmos_booking_store_with_container, mock_container
    ):
        """Test that update persists to Cosmos when container is available."""
        created = await cosmos_booking_store_with_container.create(
            consultation_id="cons_update",
            booking_type="hotel",
        )
        # Reset mock to verify update call
        mock_container.upsert_item.reset_mock()

        created.status = BookingStatus.CONFIRMED
        await cosmos_booking_store_with_container.update(created)

        mock_container.upsert_item.assert_called_once()


class TestCosmosBookingStoreDocConversion:
    """Tests for document conversion."""

    def test_booking_to_doc(self, cosmos_booking_store):
        """Test converting Booking to Cosmos document."""
        booking = Booking(
            id="book_test123",
            consultation_id="cons_test456",
            type="flight",
            status=BookingStatus.CONFIRMED,
            details={"flight": "AA123"},
            can_modify=False,
            can_cancel=True,
        )

        doc = cosmos_booking_store._booking_to_doc(booking)

        assert doc["id"] == "book_test123"
        assert doc["booking_id"] == "book_test123"
        assert doc["consultation_id"] == "cons_test456"
        assert doc["type"] == "flight"
        assert doc["status"] == "confirmed"
        assert doc["details"] == {"flight": "AA123"}
        assert doc["can_modify"] is False
        assert doc["can_cancel"] is True

    def test_doc_to_booking(self, cosmos_booking_store):
        """Test converting Cosmos document to Booking."""
        doc = {
            "id": "book_doc123",
            "booking_id": "book_doc123",
            "consultation_id": "cons_doc456",
            "type": "hotel",
            "status": "confirmed",
            "details": {"room": "suite"},
            "can_modify": True,
            "can_cancel": False,
        }

        booking = cosmos_booking_store._doc_to_booking(doc)

        assert booking.id == "book_doc123"
        assert booking.consultation_id == "cons_doc456"
        assert booking.type == "hotel"
        assert booking.status == BookingStatus.CONFIRMED
        assert booking.details == {"room": "suite"}
        assert booking.can_modify is True
        assert booking.can_cancel is False

    def test_doc_to_booking_handles_invalid_status(self, cosmos_booking_store):
        """Test that invalid status defaults to PENDING."""
        doc = {
            "id": "book_invalid",
            "booking_id": "book_invalid",
            "consultation_id": "cons_test",
            "type": "hotel",
            "status": "invalid_status",
            "details": {},
        }

        booking = cosmos_booking_store._doc_to_booking(doc)

        assert booking.status == BookingStatus.PENDING


class TestCosmosBookingStoreWithoutContainer:
    """Tests for cache-only mode (no Cosmos container)."""

    @pytest.mark.asyncio
    async def test_works_in_cache_only_mode(self):
        """Test that store works without Cosmos container."""
        store = CosmosBookingStore()

        created = await store.create(
            consultation_id="cons_cache",
            booking_type="hotel",
        )

        result = await store.get(created.id)
        assert result is not None
        assert result.id == created.id

    @pytest.mark.asyncio
    async def test_get_returns_none_without_cosmos(self):
        """Test that get returns None for unknown ID without Cosmos."""
        store = CosmosBookingStore()

        result = await store.get("book_notincache")

        assert result is None
