"""
Unit tests for the booking reconciliation module.

Tests cover:
- reconcile_unknown_bookings only processes UNKNOWN status
- Error handling for individual booking reconciliation failures
- Alert generation for bookings stuck too long
- ReconciliationResult tracking and metrics
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.orchestrator.booking.reconciliation import (
    UNKNOWN_ALERT_THRESHOLD_HOURS,
    ReconciliationOutcome,
    ReconciliationResult,
    reconcile_unknown_bookings,
    _reconcile_single_booking,
    _should_alert,
)
from src.orchestrator.models.booking import (
    Booking,
    BookingQuote,
    BookingStatus,
    CancellationPolicy,
)
from src.orchestrator.storage.booking_store import InMemoryBookingStore
from src.orchestrator.tools.workflow_turn import ToolResponse


@pytest.fixture
def mock_booking_store():
    """Create an in-memory booking store for testing."""
    return InMemoryBookingStore()


@pytest.fixture
def mock_booking_service():
    """Create a mock booking service."""
    return MagicMock()


def create_test_booking(
    booking_id: str,
    status: BookingStatus = BookingStatus.UNKNOWN,
    updated_at: datetime | None = None,
) -> Booking:
    """Helper to create test bookings."""
    now = datetime.now(timezone.utc)
    booking = Booking.create_unbooked(
        booking_id=booking_id,
        itinerary_id="itn_test123",
        item_type="flight",
        price=500.0,
        details={"name": "Test Flight"},
        cancellation_policy=CancellationPolicy.non_refundable(),
    )
    # Override status and updated_at for testing
    booking.status = status
    booking.updated_at = updated_at or now
    return booking


class TestReconcileUnknownBookings:
    """Tests for the main reconcile_unknown_bookings function."""

    @pytest.mark.asyncio
    async def test_reconcile_unknown_bookings_only_unknown(
        self, mock_booking_store, mock_booking_service
    ):
        """Test that only UNKNOWN bookings are processed."""
        # Create bookings with various statuses
        unknown_booking = create_test_booking("book_unknown", BookingStatus.UNKNOWN)
        booked_booking = create_test_booking("book_booked", BookingStatus.BOOKED)
        failed_booking = create_test_booking("book_failed", BookingStatus.FAILED)
        pending_booking = create_test_booking("book_pending", BookingStatus.PENDING)

        # Save to store
        await mock_booking_store.save_booking(unknown_booking)
        await mock_booking_store.save_booking(booked_booking)
        await mock_booking_store.save_booking(failed_booking)
        await mock_booking_store.save_booking(pending_booking)

        # Mock the check_booking_status to return success
        mock_booking_service.check_booking_status = AsyncMock(
            return_value=ToolResponse(
                success=True,
                message="Confirmed",
                data={"status": BookingStatus.BOOKED.value},
            )
        )

        result = await reconcile_unknown_bookings(
            mock_booking_store, mock_booking_service
        )

        # Only the UNKNOWN booking should be processed
        assert result.total_processed == 1
        assert mock_booking_service.check_booking_status.call_count == 1
        mock_booking_service.check_booking_status.assert_called_with("book_unknown")

    @pytest.mark.asyncio
    async def test_reconcile_unknown_bookings_handles_errors(
        self, mock_booking_store, mock_booking_service
    ):
        """Test that errors for individual bookings don't stop the job."""
        # Create multiple UNKNOWN bookings
        booking1 = create_test_booking("book_001", BookingStatus.UNKNOWN)
        booking2 = create_test_booking("book_002", BookingStatus.UNKNOWN)
        booking3 = create_test_booking("book_003", BookingStatus.UNKNOWN)

        await mock_booking_store.save_booking(booking1)
        await mock_booking_store.save_booking(booking2)
        await mock_booking_store.save_booking(booking3)

        # First call succeeds, second fails, third succeeds
        mock_booking_service.check_booking_status = AsyncMock(
            side_effect=[
                ToolResponse(
                    success=True,
                    message="Confirmed",
                    data={"status": BookingStatus.BOOKED.value},
                ),
                Exception("Provider timeout"),
                ToolResponse(
                    success=True,
                    message="Not found",
                    data={"status": BookingStatus.FAILED.value},
                ),
            ]
        )

        result = await reconcile_unknown_bookings(
            mock_booking_store, mock_booking_service
        )

        # All 3 should be processed despite the error
        assert result.total_processed == 3
        assert result.confirmed_count == 1
        assert result.not_found_count == 1
        assert result.error_count == 1
        assert mock_booking_service.check_booking_status.call_count == 3

    @pytest.mark.asyncio
    async def test_reconcile_unknown_bookings_empty(
        self, mock_booking_store, mock_booking_service
    ):
        """Test behavior when no UNKNOWN bookings exist."""
        # Add a booked booking (not UNKNOWN)
        booked_booking = create_test_booking("book_test", BookingStatus.BOOKED)
        await mock_booking_store.save_booking(booked_booking)

        result = await reconcile_unknown_bookings(
            mock_booking_store, mock_booking_service
        )

        assert result.total_processed == 0
        mock_booking_service.check_booking_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_reconcile_unknown_bookings_max_bookings_limit(
        self, mock_booking_store, mock_booking_service
    ):
        """Test that max_bookings parameter limits processing."""
        # Create 5 UNKNOWN bookings
        for i in range(5):
            booking = create_test_booking(f"book_{i:03d}", BookingStatus.UNKNOWN)
            await mock_booking_store.save_booking(booking)

        mock_booking_service.check_booking_status = AsyncMock(
            return_value=ToolResponse(
                success=True,
                message="Confirmed",
                data={"status": BookingStatus.BOOKED.value},
            )
        )

        # Limit to 2 bookings
        result = await reconcile_unknown_bookings(
            mock_booking_store, mock_booking_service, max_bookings=2
        )

        assert result.total_processed == 2
        assert mock_booking_service.check_booking_status.call_count == 2

    @pytest.mark.asyncio
    async def test_reconcile_unknown_bookings_confirmed_outcome(
        self, mock_booking_store, mock_booking_service
    ):
        """Test confirmed booking outcome tracking."""
        booking = create_test_booking("book_confirmed", BookingStatus.UNKNOWN)
        await mock_booking_store.save_booking(booking)

        mock_booking_service.check_booking_status = AsyncMock(
            return_value=ToolResponse(
                success=True,
                message="Booking confirmed",
                data={"status": BookingStatus.BOOKED.value},
            )
        )

        result = await reconcile_unknown_bookings(
            mock_booking_store, mock_booking_service
        )

        assert result.confirmed_count == 1
        assert result.not_found_count == 0
        assert result.still_pending_count == 0

    @pytest.mark.asyncio
    async def test_reconcile_unknown_bookings_not_found_outcome(
        self, mock_booking_store, mock_booking_service
    ):
        """Test not found booking outcome tracking."""
        booking = create_test_booking("book_notfound", BookingStatus.UNKNOWN)
        await mock_booking_store.save_booking(booking)

        mock_booking_service.check_booking_status = AsyncMock(
            return_value=ToolResponse(
                success=False,
                message="Not found",
                data={"status": BookingStatus.FAILED.value},
            )
        )

        result = await reconcile_unknown_bookings(
            mock_booking_store, mock_booking_service
        )

        assert result.not_found_count == 1
        assert result.confirmed_count == 0

    @pytest.mark.asyncio
    async def test_reconcile_unknown_bookings_still_pending(
        self, mock_booking_store, mock_booking_service
    ):
        """Test still pending booking outcome tracking."""
        booking = create_test_booking("book_pending", BookingStatus.UNKNOWN)
        await mock_booking_store.save_booking(booking)

        mock_booking_service.check_booking_status = AsyncMock(
            return_value=ToolResponse(
                success=False,
                message="Still pending",
                data={"status": BookingStatus.PENDING.value},
            )
        )

        result = await reconcile_unknown_bookings(
            mock_booking_store, mock_booking_service
        )

        assert result.still_pending_count == 1

    @pytest.mark.asyncio
    async def test_reconcile_unknown_bookings_query_failure(
        self, mock_booking_service
    ):
        """Test handling of store query failures."""
        mock_store = MagicMock()
        mock_store.get_bookings_by_status = AsyncMock(
            side_effect=Exception("Database connection failed")
        )

        result = await reconcile_unknown_bookings(mock_store, mock_booking_service)

        # Should return empty result, not raise
        assert result.total_processed == 0
        assert result.completed_at is not None


class TestAlertGeneration:
    """Tests for alert generation on stuck bookings."""

    @pytest.mark.asyncio
    async def test_alert_generated_for_old_unknown_booking(
        self, mock_booking_store, mock_booking_service
    ):
        """Test that alerts are generated for bookings stuck too long."""
        # Create a booking that's been UNKNOWN for over an hour
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        old_booking = create_test_booking(
            "book_old", BookingStatus.UNKNOWN, updated_at=old_time
        )
        # Save booking then manually override the updated_at in the store
        # to preserve the old timestamp (since save_booking updates it)
        await mock_booking_store.save_booking(old_booking)
        mock_booking_store._bookings["book_old"]["updated_at"] = old_time.isoformat()

        # Reconciliation returns still UNKNOWN
        mock_booking_service.check_booking_status = AsyncMock(
            return_value=ToolResponse(
                success=False,
                message="Still processing",
                data={"status": BookingStatus.UNKNOWN.value},
            )
        )

        alert_callback = AsyncMock()

        result = await reconcile_unknown_bookings(
            mock_booking_store, mock_booking_service, alert_callback=alert_callback
        )

        assert result.alerts_generated == 1
        alert_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_alert_for_recent_unknown_booking(
        self, mock_booking_store, mock_booking_service
    ):
        """Test that no alert is generated for recently created bookings."""
        # Create a booking that's only been UNKNOWN for 10 minutes
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        recent_booking = create_test_booking(
            "book_recent", BookingStatus.UNKNOWN, updated_at=recent_time
        )
        await mock_booking_store.save_booking(recent_booking)

        mock_booking_service.check_booking_status = AsyncMock(
            return_value=ToolResponse(
                success=False,
                message="Still processing",
                data={"status": BookingStatus.UNKNOWN.value},
            )
        )

        alert_callback = AsyncMock()

        result = await reconcile_unknown_bookings(
            mock_booking_store, mock_booking_service, alert_callback=alert_callback
        )

        assert result.alerts_generated == 0
        alert_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_alert_for_resolved_booking(
        self, mock_booking_store, mock_booking_service
    ):
        """Test that no alert is generated when booking is resolved."""
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        old_booking = create_test_booking(
            "book_old", BookingStatus.UNKNOWN, updated_at=old_time
        )
        await mock_booking_store.save_booking(old_booking)

        # Reconciliation successfully resolves to BOOKED
        mock_booking_service.check_booking_status = AsyncMock(
            return_value=ToolResponse(
                success=True,
                message="Confirmed!",
                data={"status": BookingStatus.BOOKED.value},
            )
        )

        alert_callback = AsyncMock()

        result = await reconcile_unknown_bookings(
            mock_booking_store, mock_booking_service, alert_callback=alert_callback
        )

        assert result.alerts_generated == 0
        alert_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_alert_callback_failure_does_not_stop_job(
        self, mock_booking_store, mock_booking_service
    ):
        """Test that alert callback failure doesn't stop reconciliation."""
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        booking1 = create_test_booking(
            "book_001", BookingStatus.UNKNOWN, updated_at=old_time
        )
        booking2 = create_test_booking(
            "book_002", BookingStatus.UNKNOWN, updated_at=old_time
        )
        await mock_booking_store.save_booking(booking1)
        await mock_booking_store.save_booking(booking2)

        mock_booking_service.check_booking_status = AsyncMock(
            return_value=ToolResponse(
                success=False,
                message="Still processing",
                data={"status": BookingStatus.UNKNOWN.value},
            )
        )

        # Alert callback raises an error
        alert_callback = AsyncMock(side_effect=Exception("Alert service unavailable"))

        result = await reconcile_unknown_bookings(
            mock_booking_store, mock_booking_service, alert_callback=alert_callback
        )

        # Both bookings should still be processed
        assert result.total_processed == 2


class TestReconciliationResult:
    """Tests for ReconciliationResult tracking."""

    def test_result_to_dict(self):
        """Test result serialization."""
        result = ReconciliationResult()
        result.add_outcome(
            ReconciliationOutcome(
                booking_id="book_001",
                success=True,
                new_status=BookingStatus.BOOKED.value,
            )
        )
        result.complete()

        data = result.to_dict()

        assert data["total_processed"] == 1
        assert data["confirmed_count"] == 1
        assert "started_at" in data
        assert "completed_at" in data
        assert data["duration_seconds"] is not None

    def test_result_counts_multiple_outcomes(self):
        """Test that result correctly tracks multiple outcomes."""
        result = ReconciliationResult()

        # Add confirmed
        result.add_outcome(
            ReconciliationOutcome(
                booking_id="book_001",
                success=True,
                new_status=BookingStatus.BOOKED.value,
            )
        )

        # Add not found
        result.add_outcome(
            ReconciliationOutcome(
                booking_id="book_002",
                success=True,
                new_status=BookingStatus.FAILED.value,
            )
        )

        # Add error
        result.add_outcome(
            ReconciliationOutcome(
                booking_id="book_003",
                success=False,
                error="Provider timeout",
            )
        )

        # Add alert
        result.add_outcome(
            ReconciliationOutcome(
                booking_id="book_004",
                success=True,
                new_status=BookingStatus.UNKNOWN.value,
                needs_alert=True,
            )
        )

        assert result.total_processed == 4
        assert result.confirmed_count == 1
        assert result.not_found_count == 1
        assert result.error_count == 1
        assert result.still_pending_count == 1
        assert result.alerts_generated == 1


class TestShouldAlert:
    """Tests for the _should_alert helper."""

    def test_should_alert_for_old_unknown(self):
        """Test alert for old UNKNOWN bookings."""
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        assert _should_alert(old_time, BookingStatus.UNKNOWN.value) is True

    def test_should_not_alert_for_recent_unknown(self):
        """Test no alert for recent UNKNOWN bookings."""
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        assert _should_alert(recent_time, BookingStatus.UNKNOWN.value) is False

    def test_should_not_alert_for_resolved_status(self):
        """Test no alert for resolved statuses."""
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        assert _should_alert(old_time, BookingStatus.BOOKED.value) is False
        assert _should_alert(old_time, BookingStatus.FAILED.value) is False

    def test_should_not_alert_for_none_timestamp(self):
        """Test no alert when timestamp is None."""
        assert _should_alert(None, BookingStatus.UNKNOWN.value) is False

    def test_should_alert_for_old_pending(self):
        """Test alert for old PENDING bookings."""
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        assert _should_alert(old_time, BookingStatus.PENDING.value) is True
