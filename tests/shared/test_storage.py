"""Unit tests for storage abstractions and implementations."""
from datetime import datetime, timedelta, timezone
import pytest

from src.shared.storage import (
    SessionStore,
    InMemorySessionStore,
    ConsultationStore,
    InMemoryConsultationStore,
    BookingStore,
    InMemoryBookingStore,
)
from src.shared.models import (
    Consultation,
    ConsultationStatus,
    Booking,
    BookingStatus,
)


# ======= SessionStore Tests =======
class TestSessionStoreABC:
    """Tests for SessionStore abstract base class."""

    def test_cannot_instantiate_abc(self):
        """Verify SessionStore cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            SessionStore()


class TestInMemorySessionStore:
    """Tests for InMemorySessionStore implementation."""

    @pytest.fixture
    def store(self) -> InMemorySessionStore:
        """Create a fresh store for each test."""
        return InMemorySessionStore()

    @pytest.mark.asyncio
    async def test_save_and_load(self, store: InMemorySessionStore):
        """Test saving and loading session data."""
        session_id = "sess_123"
        data = {"user_id": "user_1", "context": {"step": 1}}

        await store.save(session_id, data)
        loaded = await store.load(session_id)

        assert loaded == data

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, store: InMemorySessionStore):
        """Test loading non-existent session returns None."""
        loaded = await store.load("nonexistent")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_save_overwrites_existing(self, store: InMemorySessionStore):
        """Test saving to existing session overwrites data."""
        session_id = "sess_123"
        data1 = {"step": 1}
        data2 = {"step": 2, "new_field": "value"}

        await store.save(session_id, data1)
        await store.save(session_id, data2)
        loaded = await store.load(session_id)

        assert loaded == data2

    @pytest.mark.asyncio
    async def test_delete_existing_session(self, store: InMemorySessionStore):
        """Test deleting an existing session."""
        session_id = "sess_123"
        await store.save(session_id, {"data": "value"})

        deleted = await store.delete(session_id)

        assert deleted is True
        assert await store.load(session_id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, store: InMemorySessionStore):
        """Test deleting non-existent session returns False."""
        deleted = await store.delete("nonexistent")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_multiple_sessions_isolated(self, store: InMemorySessionStore):
        """Test multiple sessions are isolated from each other."""
        await store.save("sess_1", {"data": "value_1"})
        await store.save("sess_2", {"data": "value_2"})

        assert await store.load("sess_1") == {"data": "value_1"}
        assert await store.load("sess_2") == {"data": "value_2"}

        await store.delete("sess_1")

        assert await store.load("sess_1") is None
        assert await store.load("sess_2") == {"data": "value_2"}


# ======= ConsultationStore Tests =======
class TestConsultationStoreABC:
    """Tests for ConsultationStore abstract base class."""

    def test_cannot_instantiate_abc(self):
        """Verify ConsultationStore cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            ConsultationStore()


class TestInMemoryConsultationStore:
    """Tests for InMemoryConsultationStore implementation."""

    @pytest.fixture
    def store(self) -> InMemoryConsultationStore:
        """Create a fresh store for each test."""
        return InMemoryConsultationStore()

    @pytest.mark.asyncio
    async def test_create_generates_cons_prefix_id(self, store: InMemoryConsultationStore):
        """Test create generates ID with 'cons_' prefix."""
        consultation = await store.create("sess_123")

        assert consultation.id.startswith("cons_")
        assert len(consultation.id) > 5

    @pytest.mark.asyncio
    async def test_create_sets_session_id(self, store: InMemoryConsultationStore):
        """Test create sets correct session_id."""
        consultation = await store.create("sess_123")
        assert consultation.session_id == "sess_123"

    @pytest.mark.asyncio
    async def test_create_sets_draft_status(self, store: InMemoryConsultationStore):
        """Test create sets DRAFT status."""
        consultation = await store.create("sess_123")
        assert consultation.status == ConsultationStatus.DRAFT

    @pytest.mark.asyncio
    async def test_create_sets_timestamps(self, store: InMemoryConsultationStore):
        """Test create sets created_at and expires_at."""
        now = datetime.now(timezone.utc)
        consultation = await store.create("sess_123", ttl_days=7)

        assert consultation.created_at >= now
        assert consultation.expires_at > consultation.created_at
        expected_expiry = consultation.created_at + timedelta(days=7)
        assert abs((consultation.expires_at - expected_expiry).total_seconds()) < 1

    @pytest.mark.asyncio
    async def test_create_custom_ttl(self, store: InMemoryConsultationStore):
        """Test create with custom TTL."""
        consultation = await store.create("sess_123", ttl_days=14)
        expected_expiry = consultation.created_at + timedelta(days=14)
        assert abs((consultation.expires_at - expected_expiry).total_seconds()) < 1

    @pytest.mark.asyncio
    async def test_get_existing_consultation(self, store: InMemoryConsultationStore):
        """Test getting an existing consultation by ID."""
        created = await store.create("sess_123")
        loaded = await store.get(created.id)

        assert loaded is not None
        assert loaded.id == created.id
        assert loaded.session_id == created.session_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, store: InMemoryConsultationStore):
        """Test getting non-existent consultation returns None."""
        loaded = await store.get("cons_nonexistent")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_get_by_session_active_consultation(self, store: InMemoryConsultationStore):
        """Test getting active consultation by session_id."""
        created = await store.create("sess_123")
        loaded = await store.get_by_session("sess_123")

        assert loaded is not None
        assert loaded.id == created.id

    @pytest.mark.asyncio
    async def test_get_by_session_no_consultation(self, store: InMemoryConsultationStore):
        """Test get_by_session returns None when no consultation exists."""
        loaded = await store.get_by_session("sess_nonexistent")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_get_by_session_excludes_expired(self, store: InMemoryConsultationStore):
        """Test get_by_session excludes expired consultations."""
        created = await store.create("sess_123")
        created.status = ConsultationStatus.EXPIRED
        await store.update(created)

        loaded = await store.get_by_session("sess_123")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_get_by_session_excludes_cancelled(self, store: InMemoryConsultationStore):
        """Test get_by_session excludes cancelled consultations."""
        created = await store.create("sess_123")
        created.status = ConsultationStatus.CANCELLED
        await store.update(created)

        loaded = await store.get_by_session("sess_123")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_get_by_session_excludes_archived(self, store: InMemoryConsultationStore):
        """Test get_by_session excludes archived consultations."""
        created = await store.create("sess_123")
        created.status = ConsultationStatus.ARCHIVED
        await store.update(created)

        loaded = await store.get_by_session("sess_123")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_update_existing_consultation(self, store: InMemoryConsultationStore):
        """Test updating an existing consultation."""
        created = await store.create("sess_123")
        created.status = ConsultationStatus.PLANNING
        updated = await store.update(created)

        assert updated.status == ConsultationStatus.PLANNING
        loaded = await store.get(created.id)
        assert loaded is not None
        assert loaded.status == ConsultationStatus.PLANNING

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises_keyerror(self, store: InMemoryConsultationStore):
        """Test updating non-existent consultation raises KeyError."""
        now = datetime.now(timezone.utc)
        fake_consultation = Consultation(
            id="cons_nonexistent",
            session_id="sess_123",
            status=ConsultationStatus.DRAFT,
            created_at=now,
            expires_at=now + timedelta(days=7),
        )

        with pytest.raises(KeyError, match="Consultation cons_nonexistent not found"):
            await store.update(fake_consultation)

    @pytest.mark.asyncio
    async def test_mark_expired_existing_consultation(self, store: InMemoryConsultationStore):
        """Test marking an existing consultation as expired."""
        created = await store.create("sess_123")
        assert created.status == ConsultationStatus.DRAFT

        result = await store.mark_expired(created.id)

        assert result is not None
        assert result.status == ConsultationStatus.EXPIRED
        # Verify persisted
        loaded = await store.get(created.id)
        assert loaded is not None
        assert loaded.status == ConsultationStatus.EXPIRED

    @pytest.mark.asyncio
    async def test_mark_expired_nonexistent_returns_none(self, store: InMemoryConsultationStore):
        """Test marking non-existent consultation returns None."""
        result = await store.mark_expired("cons_nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_mark_expired_from_any_status(self, store: InMemoryConsultationStore):
        """Test mark_expired works from any active status."""
        statuses_to_test = [
            ConsultationStatus.DRAFT,
            ConsultationStatus.PLANNING,
            ConsultationStatus.READY_TO_BOOK,
            ConsultationStatus.PARTIALLY_BOOKED,
        ]

        for status in statuses_to_test:
            consultation = await store.create(f"sess_{status.value}")
            consultation.status = status
            await store.update(consultation)

            result = await store.mark_expired(consultation.id)

            assert result is not None, f"Failed for status {status}"
            assert result.status == ConsultationStatus.EXPIRED, f"Failed for status {status}"

    @pytest.mark.asyncio
    async def test_mark_expired_already_expired(self, store: InMemoryConsultationStore):
        """Test mark_expired on already expired consultation."""
        created = await store.create("sess_123")
        created.status = ConsultationStatus.EXPIRED
        await store.update(created)

        result = await store.mark_expired(created.id)

        assert result is not None
        assert result.status == ConsultationStatus.EXPIRED


# ======= BookingStore Tests =======
class TestBookingStoreABC:
    """Tests for BookingStore abstract base class."""

    def test_cannot_instantiate_abc(self):
        """Verify BookingStore cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BookingStore()


class TestInMemoryBookingStore:
    """Tests for InMemoryBookingStore implementation."""

    @pytest.fixture
    def store(self) -> InMemoryBookingStore:
        """Create a fresh store for each test."""
        return InMemoryBookingStore()

    @pytest.mark.asyncio
    async def test_create_generates_book_prefix_id(self, store: InMemoryBookingStore):
        """Test create generates ID with 'book_' prefix."""
        booking = await store.create("cons_123", "flight")

        assert booking.id.startswith("book_")
        assert len(booking.id) > 5

    @pytest.mark.asyncio
    async def test_create_sets_consultation_id(self, store: InMemoryBookingStore):
        """Test create sets correct consultation_id."""
        booking = await store.create("cons_123", "flight")
        assert booking.consultation_id == "cons_123"

    @pytest.mark.asyncio
    async def test_create_sets_booking_type(self, store: InMemoryBookingStore):
        """Test create sets correct booking type."""
        booking = await store.create("cons_123", "hotel")
        assert booking.type == "hotel"

    @pytest.mark.asyncio
    async def test_create_sets_pending_status(self, store: InMemoryBookingStore):
        """Test create sets PENDING status."""
        booking = await store.create("cons_123", "flight")
        assert booking.status == BookingStatus.PENDING

    @pytest.mark.asyncio
    async def test_create_with_details(self, store: InMemoryBookingStore):
        """Test create with booking details."""
        details = {"airline": "JAL", "flight_number": "JL123"}
        booking = await store.create("cons_123", "flight", details=details)

        assert booking.details == details

    @pytest.mark.asyncio
    async def test_create_without_details(self, store: InMemoryBookingStore):
        """Test create without details defaults to empty dict."""
        booking = await store.create("cons_123", "flight")
        assert booking.details == {}

    @pytest.mark.asyncio
    async def test_get_existing_booking(self, store: InMemoryBookingStore):
        """Test getting an existing booking by ID."""
        created = await store.create("cons_123", "flight")
        loaded = await store.get(created.id)

        assert loaded is not None
        assert loaded.id == created.id
        assert loaded.type == "flight"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, store: InMemoryBookingStore):
        """Test getting non-existent booking returns None."""
        loaded = await store.get("book_nonexistent")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_get_by_consultation_returns_all_bookings(self, store: InMemoryBookingStore):
        """Test get_by_consultation returns all bookings for a consultation."""
        booking1 = await store.create("cons_123", "flight")
        booking2 = await store.create("cons_123", "hotel")
        booking3 = await store.create("cons_123", "event")

        bookings = await store.get_by_consultation("cons_123")

        assert len(bookings) == 3
        booking_ids = {b.id for b in bookings}
        assert booking_ids == {booking1.id, booking2.id, booking3.id}

    @pytest.mark.asyncio
    async def test_get_by_consultation_no_bookings(self, store: InMemoryBookingStore):
        """Test get_by_consultation returns empty list when no bookings exist."""
        bookings = await store.get_by_consultation("cons_nonexistent")
        assert bookings == []

    @pytest.mark.asyncio
    async def test_get_by_consultation_isolates_consultations(self, store: InMemoryBookingStore):
        """Test get_by_consultation only returns bookings for specified consultation."""
        await store.create("cons_123", "flight")
        await store.create("cons_456", "hotel")

        bookings_123 = await store.get_by_consultation("cons_123")
        bookings_456 = await store.get_by_consultation("cons_456")

        assert len(bookings_123) == 1
        assert bookings_123[0].type == "flight"
        assert len(bookings_456) == 1
        assert bookings_456[0].type == "hotel"

    @pytest.mark.asyncio
    async def test_update_existing_booking(self, store: InMemoryBookingStore):
        """Test updating an existing booking."""
        created = await store.create("cons_123", "flight")
        created.status = BookingStatus.CONFIRMED
        created.provider_ref = "JAL-CONF-123"
        updated = await store.update(created)

        assert updated.status == BookingStatus.CONFIRMED
        assert updated.provider_ref == "JAL-CONF-123"

        loaded = await store.get(created.id)
        assert loaded is not None
        assert loaded.status == BookingStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises_keyerror(self, store: InMemoryBookingStore):
        """Test updating non-existent booking raises KeyError."""
        fake_booking = Booking(
            id="book_nonexistent",
            consultation_id="cons_123",
            type="flight",
            status=BookingStatus.PENDING,
        )

        with pytest.raises(KeyError, match="Booking book_nonexistent not found"):
            await store.update(fake_booking)

    @pytest.mark.asyncio
    async def test_update_can_modify_and_cancel_flags(self, store: InMemoryBookingStore):
        """Test updating can_modify and can_cancel flags."""
        created = await store.create("cons_123", "flight")
        assert created.can_modify is True
        assert created.can_cancel is True

        created.can_modify = False
        created.can_cancel = False
        await store.update(created)

        loaded = await store.get(created.id)
        assert loaded is not None
        assert loaded.can_modify is False
        assert loaded.can_cancel is False


# ======= Module Import Tests =======
class TestStorageModuleExports:
    """Tests for storage module exports."""

    def test_all_stores_importable(self):
        """Verify all store classes are importable from storage module."""
        from src.shared.storage import (
            SessionStore,
            InMemorySessionStore,
            ConsultationStore,
            InMemoryConsultationStore,
            BookingStore,
            InMemoryBookingStore,
        )

        assert SessionStore is not None
        assert InMemorySessionStore is not None
        assert ConsultationStore is not None
        assert InMemoryConsultationStore is not None
        assert BookingStore is not None
        assert InMemoryBookingStore is not None
