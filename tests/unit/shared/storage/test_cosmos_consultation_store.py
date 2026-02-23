"""
Unit tests for CosmosConsultationStore adapter.

Tests the CosmosConsultationStore which implements the shared ConsultationStore
interface using orchestrator Cosmos DB containers.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from src.shared.models import Consultation, ConsultationStatus
from src.shared.storage.cosmos_consultation_store import CosmosConsultationStore


class MockConsultationIndexEntry:
    """Mock for ConsultationIndexEntry."""
    def __init__(self, consultation_id: str, session_id: str, workflow_version: int = 1):
        self.consultation_id = consultation_id
        self.session_id = session_id
        self.workflow_version = workflow_version


class MockConsultationSummary:
    """Mock for ConsultationSummary."""
    def __init__(
        self,
        consultation_id: str,
        session_id: str,
        status: str = "active",
    ):
        self.consultation_id = consultation_id
        self.session_id = session_id
        self.status = status
        self.trip_spec_summary = {}
        self.itinerary_ids = []
        self.booking_ids = []
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)


class MockBookingIndexEntry:
    """Mock for BookingIndexEntry."""
    def __init__(self, booking_id: str, consultation_id: str, session_id: str):
        self.booking_id = booking_id
        self.consultation_id = consultation_id
        self.session_id = session_id


@pytest.fixture
def mock_index_store():
    """Create a mock consultation index store."""
    store = AsyncMock()
    store.add_session = AsyncMock()
    store.get_session_for_consultation = AsyncMock(return_value=None)
    store.delete_consultation = AsyncMock(return_value=True)
    return store


@pytest.fixture
def mock_summary_store():
    """Create a mock consultation summary store."""
    store = AsyncMock()
    store.get_summary = AsyncMock(return_value=None)
    store.save_summary = AsyncMock()
    return store


@pytest.fixture
def mock_booking_index_store():
    """Create a mock booking index store."""
    store = AsyncMock()
    store.get_session_for_booking = AsyncMock(return_value=None)
    store.add_booking_index = AsyncMock()
    store.delete_booking_index = AsyncMock(return_value=True)
    return store


@pytest.fixture
def cosmos_consultation_store(mock_index_store, mock_summary_store, mock_booking_index_store):
    """Create a CosmosConsultationStore with mocked dependencies."""
    return CosmosConsultationStore(
        consultation_index_store=mock_index_store,
        consultation_summary_store=mock_summary_store,
        booking_index_store=mock_booking_index_store,
    )


class TestCosmosConsultationStoreCreate:
    """Tests for creating consultations."""

    @pytest.mark.asyncio
    async def test_create_generates_consultation_id(
        self, cosmos_consultation_store, mock_index_store
    ):
        """Test that create generates a consultation ID with cons_ prefix."""
        result = await cosmos_consultation_store.create(session_id="sess_test123")

        assert result.id.startswith("cons_")
        assert len(result.id) > 5

    @pytest.mark.asyncio
    async def test_create_sets_session_id(
        self, cosmos_consultation_store
    ):
        """Test that create sets the session_id correctly."""
        session_id = "sess_test456"
        result = await cosmos_consultation_store.create(session_id=session_id)

        assert result.session_id == session_id

    @pytest.mark.asyncio
    async def test_create_sets_draft_status(
        self, cosmos_consultation_store
    ):
        """Test that create sets status to DRAFT."""
        result = await cosmos_consultation_store.create(session_id="sess_test")

        assert result.status == ConsultationStatus.DRAFT

    @pytest.mark.asyncio
    async def test_create_adds_index_entry(
        self, cosmos_consultation_store, mock_index_store
    ):
        """Test that create adds an entry to the consultation index."""
        session_id = "sess_test789"
        result = await cosmos_consultation_store.create(session_id=session_id)

        mock_index_store.add_session.assert_called_once_with(
            session_id=session_id,
            consultation_id=result.id,
            workflow_version=1,
        )

    @pytest.mark.asyncio
    async def test_create_with_custom_ttl(
        self, cosmos_consultation_store
    ):
        """Test that create respects custom TTL."""
        result = await cosmos_consultation_store.create(
            session_id="sess_test",
            ttl_days=14,
        )

        # Check expires_at is approximately 14 days from now
        expected_expiry = datetime.now(timezone.utc) + timedelta(days=14)
        assert (result.expires_at - expected_expiry).total_seconds() < 10


class TestCosmosConsultationStoreGet:
    """Tests for getting consultations."""

    @pytest.mark.asyncio
    async def test_get_returns_cached_consultation(
        self, cosmos_consultation_store
    ):
        """Test that get returns a cached consultation."""
        # Create a consultation first
        created = await cosmos_consultation_store.create(session_id="sess_cache")

        # Get should return from cache
        result = await cosmos_consultation_store.get(created.id)

        assert result is not None
        assert result.id == created.id

    @pytest.mark.asyncio
    async def test_get_returns_none_for_unknown_id(
        self, cosmos_consultation_store, mock_summary_store
    ):
        """Test that get returns None for unknown consultation ID."""
        mock_summary_store.get_summary.return_value = None

        result = await cosmos_consultation_store.get("cons_unknown")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_falls_back_to_summary_store(
        self, cosmos_consultation_store, mock_summary_store
    ):
        """Test that get falls back to summary store for non-cached IDs."""
        summary = MockConsultationSummary(
            consultation_id="cons_summary",
            session_id="sess_summary",
            status="completed",
        )
        mock_summary_store.get_summary.return_value = summary

        result = await cosmos_consultation_store.get("cons_summary")

        assert result is not None
        assert result.id == "cons_summary"
        mock_summary_store.get_summary.assert_called_with("cons_summary")


class TestCosmosConsultationStoreGetBySession:
    """Tests for getting consultations by session."""

    @pytest.mark.asyncio
    async def test_get_by_session_returns_cached(
        self, cosmos_consultation_store
    ):
        """Test that get_by_session returns from cache."""
        # Create a consultation
        created = await cosmos_consultation_store.create(session_id="sess_bylookup")

        # Should return from cache
        result = await cosmos_consultation_store.get_by_session("sess_bylookup")

        assert result is not None
        assert result.id == created.id

    @pytest.mark.asyncio
    async def test_get_by_session_excludes_expired(
        self, cosmos_consultation_store
    ):
        """Test that get_by_session excludes expired consultations."""
        # Create and expire a consultation
        created = await cosmos_consultation_store.create(session_id="sess_expired")
        await cosmos_consultation_store.mark_expired(created.id)

        # Should not return expired consultation
        result = await cosmos_consultation_store.get_by_session("sess_expired")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_session_returns_none_for_unknown(
        self, cosmos_consultation_store, mock_index_store
    ):
        """Test that get_by_session returns None for unknown session."""
        mock_index_store.get_session_for_consultation.return_value = None

        result = await cosmos_consultation_store.get_by_session("sess_unknown")

        assert result is None


class TestCosmosConsultationStoreUpdate:
    """Tests for updating consultations."""

    @pytest.mark.asyncio
    async def test_update_modifies_consultation(
        self, cosmos_consultation_store
    ):
        """Test that update modifies a consultation."""
        created = await cosmos_consultation_store.create(session_id="sess_update")
        created.status = ConsultationStatus.PLANNING

        result = await cosmos_consultation_store.update(created)

        assert result.status == ConsultationStatus.PLANNING

    @pytest.mark.asyncio
    async def test_update_raises_for_unknown(
        self, cosmos_consultation_store, mock_summary_store
    ):
        """Test that update raises KeyError for unknown consultation."""
        mock_summary_store.get_summary.return_value = None
        unknown = Consultation(
            id="cons_unknown",
            session_id="sess_test",
            status=ConsultationStatus.DRAFT,
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )

        with pytest.raises(KeyError):
            await cosmos_consultation_store.update(unknown)


class TestCosmosConsultationStoreMarkExpired:
    """Tests for marking consultations as expired."""

    @pytest.mark.asyncio
    async def test_mark_expired_changes_status(
        self, cosmos_consultation_store
    ):
        """Test that mark_expired changes status to EXPIRED."""
        created = await cosmos_consultation_store.create(session_id="sess_expire")

        result = await cosmos_consultation_store.mark_expired(created.id)

        assert result is not None
        assert result.status == ConsultationStatus.EXPIRED

    @pytest.mark.asyncio
    async def test_mark_expired_returns_none_for_unknown(
        self, cosmos_consultation_store, mock_summary_store
    ):
        """Test that mark_expired returns None for unknown ID."""
        mock_summary_store.get_summary.return_value = None

        result = await cosmos_consultation_store.mark_expired("cons_unknown")

        assert result is None


class TestCosmosConsultationStoreGetByBooking:
    """Tests for getting consultations by booking ID."""

    @pytest.mark.asyncio
    async def test_get_by_booking_uses_booking_index(
        self, cosmos_consultation_store, mock_booking_index_store
    ):
        """Test that get_by_booking uses the booking index store."""
        # Set up the booking index to return a consultation_id
        index_entry = MockBookingIndexEntry(
            booking_id="book_test",
            consultation_id="cons_frombook",
            session_id="sess_frombook",
        )
        mock_booking_index_store.get_session_for_booking.return_value = index_entry

        # Create a consultation with that ID
        cosmos_consultation_store._consultations["cons_frombook"] = Consultation(
            id="cons_frombook",
            session_id="sess_frombook",
            status=ConsultationStatus.PLANNING,
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )

        result = await cosmos_consultation_store.get_by_booking("book_test")

        assert result is not None
        assert result.id == "cons_frombook"
        mock_booking_index_store.get_session_for_booking.assert_called_with("book_test")

    @pytest.mark.asyncio
    async def test_get_by_booking_returns_none_for_unknown(
        self, cosmos_consultation_store, mock_booking_index_store
    ):
        """Test that get_by_booking returns None for unknown booking."""
        mock_booking_index_store.get_session_for_booking.return_value = None

        result = await cosmos_consultation_store.get_by_booking("book_unknown")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_booking_returns_none_without_booking_store(
        self, mock_index_store, mock_summary_store
    ):
        """Test that get_by_booking returns None when no booking store configured."""
        store = CosmosConsultationStore(
            consultation_index_store=mock_index_store,
            consultation_summary_store=mock_summary_store,
            booking_index_store=None,  # No booking store
        )

        result = await store.get_by_booking("book_test")

        assert result is None


class TestCosmosConsultationStoreConsultationFromSummary:
    """Tests for converting summary to consultation."""

    def test_consultation_from_summary_with_dataclass(
        self, cosmos_consultation_store
    ):
        """Test conversion from ConsultationSummary dataclass."""
        summary = MockConsultationSummary(
            consultation_id="cons_dc",
            session_id="sess_dc",
            status="completed",
        )

        result = cosmos_consultation_store._consultation_from_summary(summary)

        assert result.id == "cons_dc"
        assert result.session_id == "sess_dc"
        assert result.status == ConsultationStatus.FULLY_BOOKED  # completed maps to FULLY_BOOKED

    def test_consultation_from_summary_with_dict(
        self, cosmos_consultation_store
    ):
        """Test conversion from dict."""
        summary = {
            "consultation_id": "cons_dict",
            "session_id": "sess_dict",
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        result = cosmos_consultation_store._consultation_from_summary(summary)

        assert result.id == "cons_dict"
        assert result.session_id == "sess_dict"
        assert result.status == ConsultationStatus.PLANNING  # active maps to PLANNING

    def test_consultation_from_summary_status_mapping(
        self, cosmos_consultation_store
    ):
        """Test that status strings are mapped correctly."""
        status_cases = [
            ("active", ConsultationStatus.PLANNING),
            ("draft", ConsultationStatus.DRAFT),
            ("completed", ConsultationStatus.FULLY_BOOKED),
            ("fully_booked", ConsultationStatus.FULLY_BOOKED),
            ("cancelled", ConsultationStatus.CANCELLED),
            ("expired", ConsultationStatus.EXPIRED),
            ("unknown", ConsultationStatus.DRAFT),  # Default
        ]

        for status_str, expected_status in status_cases:
            summary = MockConsultationSummary(
                consultation_id="cons_status",
                session_id="sess_status",
                status=status_str,
            )
            result = cosmos_consultation_store._consultation_from_summary(summary)
            assert result.status == expected_status, f"Failed for status: {status_str}"
