"""
Unit tests for ConsultationSummaryStore.

Tests cover:
- Basic CRUD operations (get, save, delete)
- TTL calculation based on trip_end_date
- ConsultationSummary dataclass serialization/deserialization
- InMemoryConsultationSummaryStore behavior
- ConsultationSummaryStore with mocked Cosmos container
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator.storage.consultation_summaries import (
    ConsultationSummary,
    ConsultationSummaryStore,
    InMemoryConsultationSummaryStore,
    calculate_consultation_summary_ttl,
)


class TestCalculateConsultationSummaryTTL:
    """Tests for TTL calculation function."""

    def test_ttl_with_future_date(self) -> None:
        """Test TTL calculation with a future trip end date."""
        # Trip ends 10 days from now
        future_date = date.today() + timedelta(days=10)
        ttl = calculate_consultation_summary_ttl(future_date)

        # Should be approximately (10 + 30) days = 40 days in seconds
        # The calculation uses midnight UTC of the date, so variance depends on current time
        # Allow a full day margin to account for timezone differences
        expected_min = (39 * 24 * 60 * 60)  # 39 days minimum
        expected_max = (41 * 24 * 60 * 60)  # 41 days maximum
        assert expected_min <= ttl <= expected_max

    def test_ttl_with_past_date_uses_minimum(self) -> None:
        """Test TTL with past trip end date uses minimum 1 day."""
        # Trip ended 60 days ago (trip_end + 30 = 30 days ago)
        past_date = date.today() - timedelta(days=60)
        ttl = calculate_consultation_summary_ttl(past_date)

        # Should be minimum 1 day (86400 seconds)
        assert ttl == 86400

    def test_ttl_with_none_uses_default(self) -> None:
        """Test TTL with None uses default 30 days."""
        ttl = calculate_consultation_summary_ttl(None)
        # Default is 30 days in seconds
        assert ttl == 30 * 24 * 60 * 60

    def test_ttl_with_datetime_instead_of_date(self) -> None:
        """Test TTL calculation handles datetime input."""
        future_datetime = datetime.now(timezone.utc) + timedelta(days=10)
        ttl = calculate_consultation_summary_ttl(future_datetime)  # type: ignore

        expected_min = (40 * 24 * 60 * 60) - 3600
        expected_max = (40 * 24 * 60 * 60) + 3600
        assert expected_min <= ttl <= expected_max


class TestConsultationSummary:
    """Tests for ConsultationSummary dataclass."""

    def test_default_values(self) -> None:
        """Test that defaults are applied correctly."""
        summary = ConsultationSummary(
            consultation_id="cons_123",
            session_id="sess_abc",
            trip_spec_summary={"destination": "Tokyo"},
        )

        assert summary.consultation_id == "cons_123"
        assert summary.session_id == "sess_abc"
        assert summary.trip_spec_summary == {"destination": "Tokyo"}
        assert summary.itinerary_ids == []
        assert summary.booking_ids == []
        assert summary.status == "active"
        assert summary.trip_end_date is None
        assert isinstance(summary.created_at, datetime)
        assert isinstance(summary.updated_at, datetime)

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        now = datetime.now(timezone.utc)
        trip_end = date(2025, 4, 15)
        summary = ConsultationSummary(
            consultation_id="cons_xyz789",
            session_id="sess_abc123",
            trip_spec_summary={
                "destination": "Tokyo",
                "dates": {"start": "2025-04-10", "end": "2025-04-15"},
            },
            itinerary_ids=["itn_m1n2o3"],
            booking_ids=["book_p4q5r6", "book_q5r6s7"],
            status="completed",
            trip_end_date=trip_end,
            created_at=now,
            updated_at=now,
        )

        doc = summary.to_dict()

        assert doc["id"] == "cons_xyz789"
        assert doc["consultation_id"] == "cons_xyz789"
        assert doc["session_id"] == "sess_abc123"
        assert doc["trip_spec_summary"] == {
            "destination": "Tokyo",
            "dates": {"start": "2025-04-10", "end": "2025-04-15"},
        }
        assert doc["itinerary_ids"] == ["itn_m1n2o3"]
        assert doc["booking_ids"] == ["book_p4q5r6", "book_q5r6s7"]
        assert doc["status"] == "completed"
        assert doc["trip_end_date"] == "2025-04-15"
        assert "ttl" in doc
        assert isinstance(doc["ttl"], int)
        assert doc["ttl"] > 0

    def test_from_dict(self) -> None:
        """Test deserialization from dictionary."""
        now = datetime.now(timezone.utc)
        doc = {
            "id": "cons_xyz789",
            "consultation_id": "cons_xyz789",
            "session_id": "sess_abc123",
            "trip_spec_summary": {"destination": "Kyoto"},
            "itinerary_ids": ["itn_001", "itn_002"],
            "booking_ids": ["book_001"],
            "status": "active",
            "trip_end_date": "2025-06-20",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

        summary = ConsultationSummary.from_dict(doc)

        assert summary.consultation_id == "cons_xyz789"
        assert summary.session_id == "sess_abc123"
        assert summary.trip_spec_summary == {"destination": "Kyoto"}
        assert summary.itinerary_ids == ["itn_001", "itn_002"]
        assert summary.booking_ids == ["book_001"]
        assert summary.status == "active"
        assert summary.trip_end_date == date(2025, 6, 20)

    def test_from_dict_with_missing_fields(self) -> None:
        """Test deserialization handles missing fields gracefully."""
        doc = {"id": "cons_minimal"}

        summary = ConsultationSummary.from_dict(doc)

        assert summary.consultation_id == "cons_minimal"
        assert summary.session_id == ""
        assert summary.trip_spec_summary == {}
        assert summary.itinerary_ids == []
        assert summary.booking_ids == []
        assert summary.status == "active"
        assert summary.trip_end_date is None

    def test_from_dict_with_datetime_trip_end(self) -> None:
        """Test deserialization handles datetime trip_end_date."""
        doc = {
            "consultation_id": "cons_123",
            "session_id": "sess_abc",
            "trip_spec_summary": {},
            "trip_end_date": "2025-06-20T23:59:59",
        }

        summary = ConsultationSummary.from_dict(doc)

        assert summary.trip_end_date == date(2025, 6, 20)

    def test_roundtrip_serialization(self) -> None:
        """Test that to_dict and from_dict are inverses."""
        original = ConsultationSummary(
            consultation_id="cons_roundtrip",
            session_id="sess_rt",
            trip_spec_summary={"destination": "Osaka", "travelers": 2},
            itinerary_ids=["itn_001"],
            booking_ids=["book_001", "book_002"],
            status="completed",
            trip_end_date=date(2025, 8, 15),
        )

        doc = original.to_dict()
        restored = ConsultationSummary.from_dict(doc)

        assert restored.consultation_id == original.consultation_id
        assert restored.session_id == original.session_id
        assert restored.trip_spec_summary == original.trip_spec_summary
        assert restored.itinerary_ids == original.itinerary_ids
        assert restored.booking_ids == original.booking_ids
        assert restored.status == original.status
        assert restored.trip_end_date == original.trip_end_date


class TestInMemoryConsultationSummaryStore:
    """Tests for InMemoryConsultationSummaryStore."""

    @pytest.fixture
    def store(self) -> InMemoryConsultationSummaryStore:
        """Create a fresh in-memory store for each test."""
        return InMemoryConsultationSummaryStore()

    @pytest.mark.asyncio
    async def test_get_summary_found(
        self, store: InMemoryConsultationSummaryStore
    ) -> None:
        """Test retrieving an existing summary."""
        summary = ConsultationSummary(
            consultation_id="cons_test",
            session_id="sess_test",
            trip_spec_summary={"destination": "Tokyo"},
            itinerary_ids=["itn_001"],
        )
        await store.save_summary(summary)

        result = await store.get_summary("cons_test")

        assert result is not None
        assert result.consultation_id == "cons_test"
        assert result.session_id == "sess_test"
        assert result.trip_spec_summary == {"destination": "Tokyo"}
        assert result.itinerary_ids == ["itn_001"]

    @pytest.mark.asyncio
    async def test_get_summary_not_found(
        self, store: InMemoryConsultationSummaryStore
    ) -> None:
        """Test retrieving a non-existent summary returns None."""
        result = await store.get_summary("cons_nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_save_summary_sets_ttl(
        self, store: InMemoryConsultationSummaryStore
    ) -> None:
        """Test that save_summary sets TTL based on trip_end_date."""
        summary = ConsultationSummary(
            consultation_id="cons_ttl",
            session_id="sess_ttl",
            trip_spec_summary={"destination": "Tokyo"},
            trip_end_date=date.today() + timedelta(days=10),
        )

        result = await store.save_summary(summary)

        # Check that the stored document has TTL
        stored_doc = store._summaries["cons_ttl"]
        assert "ttl" in stored_doc
        assert stored_doc["ttl"] > 0

    @pytest.mark.asyncio
    async def test_save_summary_creates(
        self, store: InMemoryConsultationSummaryStore
    ) -> None:
        """Test saving creates a new summary."""
        summary = ConsultationSummary(
            consultation_id="cons_new",
            session_id="sess_new",
            trip_spec_summary={"destination": "Kyoto"},
            status="active",
        )

        result = await store.save_summary(summary)

        assert result.consultation_id == "cons_new"
        assert store.get_count() == 1

    @pytest.mark.asyncio
    async def test_save_summary_updates(
        self, store: InMemoryConsultationSummaryStore
    ) -> None:
        """Test saving updates an existing summary."""
        # Create initial summary
        summary = ConsultationSummary(
            consultation_id="cons_update",
            session_id="sess_update",
            trip_spec_summary={"destination": "Tokyo"},
            status="active",
        )
        await store.save_summary(summary)
        original_updated_at = summary.updated_at

        # Update it
        import asyncio

        await asyncio.sleep(0.01)  # Ensure timestamp changes
        summary.status = "completed"
        summary.booking_ids = ["book_001"]
        result = await store.save_summary(summary)

        assert result.status == "completed"
        assert result.booking_ids == ["book_001"]
        assert result.updated_at >= original_updated_at
        assert store.get_count() == 1  # Still only one summary

    @pytest.mark.asyncio
    async def test_delete_summary_existing(
        self, store: InMemoryConsultationSummaryStore
    ) -> None:
        """Test deleting an existing summary."""
        summary = ConsultationSummary(
            consultation_id="cons_delete",
            session_id="sess_delete",
            trip_spec_summary={"destination": "Tokyo"},
        )
        await store.save_summary(summary)

        result = await store.delete_summary("cons_delete")

        assert result is True
        assert await store.get_summary("cons_delete") is None

    @pytest.mark.asyncio
    async def test_delete_summary_not_found(
        self, store: InMemoryConsultationSummaryStore
    ) -> None:
        """Test deleting a non-existent summary returns False."""
        result = await store.delete_summary("cons_nonexistent")

        assert result is False

    def test_clear(self, store: InMemoryConsultationSummaryStore) -> None:
        """Test clearing the store."""
        store._summaries["cons_1"] = {"id": "cons_1"}
        store._summaries["cons_2"] = {"id": "cons_2"}

        store.clear()

        assert store.get_count() == 0

    def test_get_count(self, store: InMemoryConsultationSummaryStore) -> None:
        """Test get_count returns correct count."""
        assert store.get_count() == 0

        store._summaries["cons_1"] = {"id": "cons_1"}
        assert store.get_count() == 1

        store._summaries["cons_2"] = {"id": "cons_2"}
        assert store.get_count() == 2


class TestConsultationSummaryStore:
    """Tests for ConsultationSummaryStore with mocked Cosmos container."""

    @pytest.fixture
    def mock_container(self) -> MagicMock:
        """Create a mock Cosmos container."""
        container = MagicMock()
        container.read_item = AsyncMock()
        container.upsert_item = AsyncMock()
        container.delete_item = AsyncMock()
        return container

    @pytest.fixture
    def store(self, mock_container: MagicMock) -> ConsultationSummaryStore:
        """Create a ConsultationSummaryStore with mocked container."""
        return ConsultationSummaryStore(mock_container)

    @pytest.mark.asyncio
    async def test_get_summary_found(
        self, store: ConsultationSummaryStore, mock_container: MagicMock
    ) -> None:
        """Test retrieving an existing summary from Cosmos."""
        mock_container.read_item.return_value = {
            "id": "cons_cosmos",
            "consultation_id": "cons_cosmos",
            "session_id": "sess_cosmos",
            "trip_spec_summary": {"destination": "Osaka"},
            "itinerary_ids": ["itn_001"],
            "booking_ids": ["book_001"],
            "status": "completed",
        }

        result = await store.get_summary("cons_cosmos")

        assert result is not None
        assert result.consultation_id == "cons_cosmos"
        assert result.session_id == "sess_cosmos"
        assert result.trip_spec_summary == {"destination": "Osaka"}
        mock_container.read_item.assert_called_once_with(
            item="cons_cosmos",
            partition_key="cons_cosmos",
        )

    @pytest.mark.asyncio
    async def test_get_summary_not_found(
        self, store: ConsultationSummaryStore, mock_container: MagicMock
    ) -> None:
        """Test retrieving a non-existent summary returns None."""
        # Simulate 404 error
        error = Exception("Not found")
        error.status_code = 404  # type: ignore[attr-defined]
        mock_container.read_item.side_effect = error

        result = await store.get_summary("cons_missing")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_summary_error(
        self, store: ConsultationSummaryStore, mock_container: MagicMock
    ) -> None:
        """Test that non-404 errors are raised."""
        error = Exception("Server error")
        error.status_code = 500  # type: ignore[attr-defined]
        mock_container.read_item.side_effect = error

        with pytest.raises(Exception) as exc_info:
            await store.get_summary("cons_error")

        assert "Server error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_save_summary_sets_ttl(
        self, store: ConsultationSummaryStore, mock_container: MagicMock
    ) -> None:
        """Test saving summary sets TTL correctly."""
        mock_container.upsert_item.return_value = {
            "id": "cons_create",
            "consultation_id": "cons_create",
            "session_id": "sess_create",
            "trip_spec_summary": {"destination": "Tokyo"},
            "trip_end_date": "2025-04-15",
        }

        summary = ConsultationSummary(
            consultation_id="cons_create",
            session_id="sess_create",
            trip_spec_summary={"destination": "Tokyo"},
            trip_end_date=date(2025, 4, 15),
        )
        await store.save_summary(summary)

        mock_container.upsert_item.assert_called_once()
        call_args = mock_container.upsert_item.call_args
        body = call_args.kwargs["body"]
        assert body["consultation_id"] == "cons_create"
        assert "ttl" in body
        assert body["ttl"] > 0

    @pytest.mark.asyncio
    async def test_save_summary_updates(
        self, store: ConsultationSummaryStore, mock_container: MagicMock
    ) -> None:
        """Test saving updates an existing summary."""
        mock_container.upsert_item.return_value = {
            "id": "cons_update",
            "consultation_id": "cons_update",
            "session_id": "sess_update",
            "trip_spec_summary": {"destination": "Kyoto"},
            "status": "completed",
        }

        summary = ConsultationSummary(
            consultation_id="cons_update",
            session_id="sess_update",
            trip_spec_summary={"destination": "Kyoto"},
            status="completed",
        )
        result = await store.save_summary(summary)

        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_delete_summary_existing(
        self, store: ConsultationSummaryStore, mock_container: MagicMock
    ) -> None:
        """Test deleting an existing summary."""
        mock_container.delete_item.return_value = None

        result = await store.delete_summary("cons_delete")

        assert result is True
        mock_container.delete_item.assert_called_once_with(
            item="cons_delete",
            partition_key="cons_delete",
        )

    @pytest.mark.asyncio
    async def test_delete_summary_not_found(
        self, store: ConsultationSummaryStore, mock_container: MagicMock
    ) -> None:
        """Test deleting a non-existent summary returns False."""
        error = Exception("Not found")
        error.status_code = 404  # type: ignore[attr-defined]
        mock_container.delete_item.side_effect = error

        result = await store.delete_summary("cons_missing")

        assert result is False
