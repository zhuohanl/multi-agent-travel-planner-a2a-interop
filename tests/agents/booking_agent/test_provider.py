"""Unit tests for Booking Agent provider.py."""

import pytest
from src.agents.booking_agent.provider import (
    BookingProvider,
    MockBookingProvider,
    ProviderBookingResult,
)


class TestProviderBookingResult:
    """Tests for ProviderBookingResult dataclass."""

    def test_provider_result_success(self):
        """Test creating successful result."""
        result = ProviderBookingResult(
            success=True,
            provider_ref="HTL-ABC123",
            confirmation_number="CONF123"
        )
        assert result.success is True
        assert result.provider_ref == "HTL-ABC123"
        assert result.error_message is None

    def test_provider_result_failure(self):
        """Test creating failure result."""
        result = ProviderBookingResult(
            success=False,
            error_message="Booking not found"
        )
        assert result.success is False
        assert result.error_message == "Booking not found"

    def test_provider_result_with_details(self):
        """Test result with details dict."""
        result = ProviderBookingResult(
            success=True,
            provider_ref="HTL-ABC123",
            details={"type": "hotel", "price": 500}
        )
        assert result.details["type"] == "hotel"
        assert result.details["price"] == 500

    def test_provider_result_default_details(self):
        """Test default empty details dict."""
        result = ProviderBookingResult(success=True)
        assert result.details == {}


class TestBookingProviderABC:
    """Tests for BookingProvider abstract base class."""

    def test_booking_provider_is_abstract(self):
        """Test that BookingProvider cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BookingProvider()  # type: ignore

    def test_mock_provider_is_booking_provider(self):
        """Test that MockBookingProvider implements BookingProvider."""
        provider = MockBookingProvider()
        assert isinstance(provider, BookingProvider)


class TestMockBookingProviderCreate:
    """Tests for MockBookingProvider.create method."""

    @pytest.fixture
    def provider(self):
        """Create a fresh provider for each test."""
        return MockBookingProvider()

    @pytest.mark.asyncio
    async def test_create_hotel_booking(self, provider):
        """Test creating a hotel booking."""
        result = await provider.create(
            booking_type="hotel",
            item_details={
                "name": "Park Hyatt Tokyo",
                "check_in": "2024-11-10",
                "check_out": "2024-11-17",
                "room_type": "Deluxe King"
            }
        )

        assert result.success is True
        assert result.provider_ref is not None
        assert result.provider_ref.startswith("HTL-")
        assert result.confirmation_number is not None
        assert "name" in result.details
        assert result.details["name"] == "Park Hyatt Tokyo"

    @pytest.mark.asyncio
    async def test_create_flight_booking(self, provider):
        """Test creating a flight booking."""
        result = await provider.create(
            booking_type="flight",
            item_details={
                "airline": "ANA",
                "flight_number": "NH123",
                "departure": "2024-11-10T09:00:00",
                "arrival": "2024-11-10T18:00:00"
            }
        )

        assert result.success is True
        assert result.provider_ref.startswith("FLT-")

    @pytest.mark.asyncio
    async def test_create_transport_pass_booking(self, provider):
        """Test creating a transport pass booking."""
        result = await provider.create(
            booking_type="transport_pass",
            item_details={
                "type": "JR Pass",
                "duration": "7 days"
            }
        )

        assert result.success is True
        assert result.provider_ref.startswith("TRP-")

    @pytest.mark.asyncio
    async def test_create_activity_booking(self, provider):
        """Test creating an activity booking."""
        result = await provider.create(
            booking_type="activity",
            item_details={
                "name": "Tokyo Food Tour",
                "date": "2024-11-12"
            }
        )

        assert result.success is True
        assert result.provider_ref.startswith("ACT-")

    @pytest.mark.asyncio
    async def test_create_event_booking(self, provider):
        """Test creating an event booking."""
        result = await provider.create(
            booking_type="event",
            item_details={
                "name": "Sumo Tournament",
                "date": "2024-11-15"
            }
        )

        assert result.success is True
        assert result.provider_ref.startswith("EVT-")

    @pytest.mark.asyncio
    async def test_create_restaurant_booking(self, provider):
        """Test creating a restaurant booking."""
        result = await provider.create(
            booking_type="restaurant",
            item_details={
                "name": "Sukiyabashi Jiro",
                "date": "2024-11-14",
                "time": "19:00",
                "party_size": 2
            }
        )

        assert result.success is True
        assert result.provider_ref.startswith("RST-")

    @pytest.mark.asyncio
    async def test_create_unknown_type_booking(self, provider):
        """Test creating booking with unknown type falls back to BKG prefix."""
        result = await provider.create(
            booking_type="unknown_type",
            item_details={"some": "data"}
        )

        assert result.success is True
        assert result.provider_ref.startswith("BKG-")

    @pytest.mark.asyncio
    async def test_create_stay_alias(self, provider):
        """Test 'stay' alias maps to HTL prefix."""
        result = await provider.create(
            booking_type="stay",
            item_details={"name": "Some Hotel"}
        )

        assert result.success is True
        assert result.provider_ref.startswith("HTL-")


class TestMockBookingProviderModify:
    """Tests for MockBookingProvider.modify method."""

    @pytest.fixture
    def provider(self):
        """Create a fresh provider for each test."""
        return MockBookingProvider()

    @pytest.mark.asyncio
    async def test_modify_existing_booking(self, provider):
        """Test modifying an existing booking."""
        # First create a booking
        create_result = await provider.create(
            booking_type="hotel",
            item_details={
                "name": "Park Hyatt Tokyo",
                "check_in": "2024-11-10"
            }
        )
        provider_ref = create_result.provider_ref

        # Now modify it
        modify_result = await provider.modify(
            provider_ref=provider_ref,
            modifications={"check_in": "2024-11-12"}
        )

        assert modify_result.success is True
        assert modify_result.provider_ref == provider_ref
        assert "previous" in modify_result.details
        assert "updated" in modify_result.details
        assert modify_result.details["previous"]["check_in"] == "2024-11-10"
        assert modify_result.details["updated"]["check_in"] == "2024-11-12"

    @pytest.mark.asyncio
    async def test_modify_nonexistent_booking(self, provider):
        """Test modifying a booking that doesn't exist."""
        result = await provider.modify(
            provider_ref="NONEXISTENT-123",
            modifications={"check_in": "2024-11-12"}
        )

        assert result.success is False
        assert "not found" in result.error_message


class TestMockBookingProviderCancel:
    """Tests for MockBookingProvider.cancel method."""

    @pytest.fixture
    def provider(self):
        """Create a fresh provider for each test."""
        return MockBookingProvider()

    @pytest.mark.asyncio
    async def test_cancel_existing_booking(self, provider):
        """Test cancelling an existing booking."""
        # First create a booking
        create_result = await provider.create(
            booking_type="hotel",
            item_details={"name": "Park Hyatt Tokyo"}
        )
        provider_ref = create_result.provider_ref

        # Now cancel it
        cancel_result = await provider.cancel(provider_ref=provider_ref)

        assert cancel_result.success is True
        assert cancel_result.provider_ref == provider_ref
        assert "cancellation_reference" in cancel_result.details
        assert cancel_result.details["cancellation_reference"].startswith("CXL-")

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_booking(self, provider):
        """Test cancelling a booking that doesn't exist."""
        result = await provider.cancel(provider_ref="NONEXISTENT-123")

        assert result.success is False
        assert "not found" in result.error_message


class TestMockBookingProviderHelpers:
    """Tests for MockBookingProvider helper methods."""

    @pytest.fixture
    def provider(self):
        """Create a fresh provider for each test."""
        return MockBookingProvider()

    @pytest.mark.asyncio
    async def test_get_booking_existing(self, provider):
        """Test getting an existing booking."""
        create_result = await provider.create(
            booking_type="hotel",
            item_details={"name": "Test Hotel"}
        )

        booking = provider.get_booking(create_result.provider_ref)

        assert booking is not None
        assert booking["type"] == "hotel"
        assert booking["status"] == "confirmed"

    def test_get_booking_nonexistent(self, provider):
        """Test getting a nonexistent booking returns None."""
        booking = provider.get_booking("NONEXISTENT")
        assert booking is None

    @pytest.mark.asyncio
    async def test_clear_bookings(self, provider):
        """Test clearing all bookings."""
        # Create some bookings
        result1 = await provider.create("hotel", {"name": "Hotel 1"})
        result2 = await provider.create("flight", {"name": "Flight 1"})

        # Verify they exist
        assert provider.get_booking(result1.provider_ref) is not None
        assert provider.get_booking(result2.provider_ref) is not None

        # Clear all
        provider.clear()

        # Verify they're gone
        assert provider.get_booking(result1.provider_ref) is None
        assert provider.get_booking(result2.provider_ref) is None

    @pytest.mark.asyncio
    async def test_booking_status_changes(self, provider):
        """Test that booking status changes correctly through operations."""
        # Create - should be confirmed
        create_result = await provider.create("hotel", {"name": "Test"})
        ref = create_result.provider_ref
        assert provider.get_booking(ref)["status"] == "confirmed"

        # Modify - should be modified
        await provider.modify(ref, {"room": "upgraded"})
        assert provider.get_booking(ref)["status"] == "modified"

        # Cancel - should be cancelled
        await provider.cancel(ref)
        assert provider.get_booking(ref)["status"] == "cancelled"


class TestMockBookingProviderReferenceGeneration:
    """Tests for reference number generation."""

    @pytest.fixture
    def provider(self):
        """Create a fresh provider for each test."""
        return MockBookingProvider()

    @pytest.mark.asyncio
    async def test_unique_provider_refs(self, provider):
        """Test that each booking gets a unique provider reference."""
        refs = set()
        for _ in range(10):
            result = await provider.create("hotel", {"name": "Test"})
            refs.add(result.provider_ref)

        # All 10 should be unique
        assert len(refs) == 10

    @pytest.mark.asyncio
    async def test_unique_confirmation_numbers(self, provider):
        """Test that each booking gets a unique confirmation number."""
        confs = set()
        for _ in range(10):
            result = await provider.create("hotel", {"name": "Test"})
            confs.add(result.confirmation_number)

        # All 10 should be unique
        assert len(confs) == 10

    @pytest.mark.asyncio
    async def test_provider_ref_format(self, provider):
        """Test that provider refs have correct format."""
        result = await provider.create("hotel", {"name": "Test"})

        # Format should be PREFIX-8CHARS
        parts = result.provider_ref.split("-")
        assert len(parts) == 2
        assert len(parts[1]) == 8
        # Should be all uppercase (hex digits are uppercase, numbers unchanged)
        assert parts[1] == parts[1].upper()


class TestMockBookingProviderFailureInjection:
    """Tests for MockBookingProvider failure injection capabilities."""

    @pytest.fixture
    def provider(self):
        """Create a fresh provider for each test."""
        return MockBookingProvider()

    @pytest.mark.asyncio
    async def test_inject_single_failure(self, provider):
        """Test injecting a one-time failure."""
        provider.inject_failure("Payment processing error")

        result = await provider.create("hotel", {"name": "Test Hotel"})

        assert result.success is False
        assert result.error_message == "Payment processing error"
        assert provider.get_failure_count() == 1

    @pytest.mark.asyncio
    async def test_inject_failure_clears_after_use(self, provider):
        """Test that single failure injection clears after one use."""
        provider.inject_failure("One-time error")

        # First call fails
        result1 = await provider.create("hotel", {"name": "Test 1"})
        assert result1.success is False

        # Second call succeeds
        result2 = await provider.create("hotel", {"name": "Test 2"})
        assert result2.success is True

    @pytest.mark.asyncio
    async def test_inject_failure_for_type(self, provider):
        """Test injecting persistent failure for specific booking type."""
        provider.inject_failure_for_type("flight", "Flights unavailable")

        # Flight fails
        flight_result = await provider.create("flight", {"number": "AA123"})
        assert flight_result.success is False
        assert flight_result.error_message == "Flights unavailable"

        # Hotel succeeds
        hotel_result = await provider.create("hotel", {"name": "Test Hotel"})
        assert hotel_result.success is True

    @pytest.mark.asyncio
    async def test_inject_failure_for_type_persistent(self, provider):
        """Test that type failures persist across multiple calls."""
        provider.inject_failure_for_type("hotel", "Hotels fully booked")

        # Multiple hotel bookings fail
        for i in range(3):
            result = await provider.create("hotel", {"name": f"Hotel {i}"})
            assert result.success is False

        assert provider.get_failure_count() == 3

    @pytest.mark.asyncio
    async def test_inject_transient_failure(self, provider):
        """Test transient failure that resolves after N attempts."""
        provider.inject_transient_failure(
            "hotel",
            "Temporary network error",
            failure_count=2
        )

        # First two calls fail
        result1 = await provider.create("hotel", {"name": "Test 1"})
        assert result1.success is False
        assert result1.error_message == "Temporary network error"

        result2 = await provider.create("hotel", {"name": "Test 2"})
        assert result2.success is False

        # Third call succeeds
        result3 = await provider.create("hotel", {"name": "Test 3"})
        assert result3.success is True
        assert result3.provider_ref is not None

    @pytest.mark.asyncio
    async def test_transient_failure_count_tracking(self, provider):
        """Test that transient failures decrement correctly."""
        provider.inject_transient_failure("hotel", "Temp error", failure_count=3)

        for _ in range(3):
            result = await provider.create("hotel", {"name": "Test"})
            assert result.success is False

        # 4th call should succeed
        result = await provider.create("hotel", {"name": "Test"})
        assert result.success is True
        assert provider.get_failure_count() == 3

    @pytest.mark.asyncio
    async def test_clear_failures(self, provider):
        """Test clearing all injected failures."""
        provider.inject_failure("Single error")
        provider.inject_failure_for_type("hotel", "Hotel error")
        provider.inject_transient_failure("flight", "Flight error", 2)

        provider.clear_failures()

        # All booking types should succeed
        hotel_result = await provider.create("hotel", {"name": "Test Hotel"})
        flight_result = await provider.create("flight", {"number": "AA123"})

        assert hotel_result.success is True
        assert flight_result.success is True

    @pytest.mark.asyncio
    async def test_clear_method_resets_failures(self, provider):
        """Test that clear() also resets failure state."""
        provider.inject_failure_for_type("hotel", "Error")
        await provider.create("hotel", {"name": "Test"})

        # Clear all (including bookings and failures)
        provider.clear()

        # Should succeed now
        result = await provider.create("hotel", {"name": "Test 2"})
        assert result.success is True
        assert provider.get_failure_count() == 0

    @pytest.mark.asyncio
    async def test_multiple_type_failures(self, provider):
        """Test setting failures for multiple types."""
        provider.inject_failure_for_type("hotel", "No hotels")
        provider.inject_failure_for_type("flight", "No flights")

        hotel_result = await provider.create("hotel", {"name": "Test"})
        flight_result = await provider.create("flight", {"number": "123"})
        activity_result = await provider.create("activity", {"name": "Tour"})

        assert hotel_result.success is False
        assert flight_result.success is False
        assert activity_result.success is True  # Not configured to fail

    @pytest.mark.asyncio
    async def test_case_insensitive_type_matching(self, provider):
        """Test that type matching is case-insensitive."""
        provider.inject_failure_for_type("HOTEL", "Error")

        result = await provider.create("hotel", {"name": "Test"})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_single_failure_takes_priority(self, provider):
        """Test that single failure injection takes priority over type failure."""
        provider.inject_failure_for_type("hotel", "Type error")
        provider.inject_failure("Priority error")

        result = await provider.create("hotel", {"name": "Test"})

        # Should use single failure first
        assert result.success is False
        assert result.error_message == "Priority error"

        # Second call uses type failure
        result2 = await provider.create("hotel", {"name": "Test 2"})
        assert result2.success is False
        assert result2.error_message == "Type error"

    @pytest.mark.asyncio
    async def test_failure_count_accumulates(self, provider):
        """Test that failure count accumulates across all failure types."""
        provider.inject_failure("Single error")
        provider.inject_failure_for_type("flight", "Flight error")

        await provider.create("hotel", {"name": "Test 1"})  # Single failure
        await provider.create("flight", {"number": "123"})  # Type failure
        await provider.create("flight", {"number": "456"})  # Type failure

        assert provider.get_failure_count() == 3
