"""Booking provider interface and mock implementation.

Defines the abstract interface for booking providers and provides
a mock implementation for testing.
"""
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ProviderBookingResult:
    """Result from a booking provider operation."""
    success: bool
    provider_ref: Optional[str] = None
    confirmation_number: Optional[str] = None
    error_message: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)


class BookingProvider(ABC):
    """Abstract base class for booking providers.

    Implementations handle actual booking operations with external systems
    (hotels, airlines, tour operators, etc.).
    """

    @abstractmethod
    async def create(
        self,
        booking_type: str,
        item_details: dict[str, Any],
    ) -> ProviderBookingResult:
        """Create a new booking.

        Args:
            booking_type: Type of booking (hotel, flight, activity, etc.)
            item_details: Details of the item to book

        Returns:
            ProviderBookingResult with booking confirmation
        """
        pass

    @abstractmethod
    async def modify(
        self,
        provider_ref: str,
        modifications: dict[str, Any],
    ) -> ProviderBookingResult:
        """Modify an existing booking.

        Args:
            provider_ref: Provider's reference for the booking
            modifications: Changes to make to the booking

        Returns:
            ProviderBookingResult with modification confirmation
        """
        pass

    @abstractmethod
    async def cancel(
        self,
        provider_ref: str,
    ) -> ProviderBookingResult:
        """Cancel an existing booking.

        Args:
            provider_ref: Provider's reference for the booking

        Returns:
            ProviderBookingResult with cancellation confirmation
        """
        pass


class MockBookingProvider(BookingProvider):
    """Mock booking provider for testing.

    By default succeeds for create, modify, and cancel operations
    unless failure injection is configured or the booking is explicitly
    marked as non-modifiable or non-cancellable.

    Supports failure injection for testing error handling:
    - inject_failure(): Configure next operation to fail
    - inject_failure_for_type(): Configure failures for specific booking types
    - inject_transient_failure(): Configure failure that resolves after N attempts
    """

    def __init__(self):
        """Initialize the mock provider with an in-memory booking store."""
        self._bookings: dict[str, dict[str, Any]] = {}
        # Failure injection state
        self._next_failure: Optional[str] = None
        self._type_failures: dict[str, str] = {}  # booking_type -> error_message
        self._transient_failures: dict[str, int] = {}  # booking_type -> remaining_failures
        self._failure_count: int = 0  # Track total failures for testing

    def inject_failure(self, error_message: str) -> None:
        """Inject a failure for the next create operation.

        Args:
            error_message: Error message to return
        """
        self._next_failure = error_message

    def inject_failure_for_type(
        self,
        booking_type: str,
        error_message: str,
    ) -> None:
        """Inject persistent failure for a specific booking type.

        Args:
            booking_type: Type of booking to fail (e.g., "hotel", "flight")
            error_message: Error message to return
        """
        self._type_failures[booking_type.lower()] = error_message

    def inject_transient_failure(
        self,
        booking_type: str,
        error_message: str,
        failure_count: int = 1,
    ) -> None:
        """Inject a transient failure that resolves after N attempts.

        Args:
            booking_type: Type of booking to fail
            error_message: Error message to return
            failure_count: Number of times to fail before succeeding
        """
        self._type_failures[booking_type.lower()] = error_message
        self._transient_failures[booking_type.lower()] = failure_count

    def clear_failures(self) -> None:
        """Clear all injected failures."""
        self._next_failure = None
        self._type_failures.clear()
        self._transient_failures.clear()

    def get_failure_count(self) -> int:
        """Get the total number of failures that occurred."""
        return self._failure_count

    def _check_injected_failure(
        self,
        booking_type: str,
    ) -> Optional[ProviderBookingResult]:
        """Check if a failure should be injected.

        Args:
            booking_type: Type of booking being created

        Returns:
            ProviderBookingResult with failure if injection configured, else None
        """
        # Check one-time failure
        if self._next_failure:
            error = self._next_failure
            self._next_failure = None
            self._failure_count += 1
            return ProviderBookingResult(
                success=False,
                error_message=error,
            )

        # Check type-specific failure
        type_lower = booking_type.lower()
        if type_lower in self._type_failures:
            # Check if transient failure
            if type_lower in self._transient_failures:
                remaining = self._transient_failures[type_lower]
                if remaining > 0:
                    self._transient_failures[type_lower] = remaining - 1
                    self._failure_count += 1
                    return ProviderBookingResult(
                        success=False,
                        error_message=self._type_failures[type_lower],
                    )
                else:
                    # Transient failure resolved
                    del self._type_failures[type_lower]
                    del self._transient_failures[type_lower]
                    return None
            else:
                # Persistent failure
                self._failure_count += 1
                return ProviderBookingResult(
                    success=False,
                    error_message=self._type_failures[type_lower],
                )

        return None

    def _generate_ref(self, booking_type: str) -> str:
        """Generate a realistic-looking provider reference.

        Args:
            booking_type: Type of booking for prefix

        Returns:
            Provider reference string
        """
        prefix_map = {
            "hotel": "HTL",
            "stay": "HTL",
            "flight": "FLT",
            "transport_pass": "TRP",
            "activity": "ACT",
            "event": "EVT",
            "restaurant": "RST",
        }
        prefix = prefix_map.get(booking_type.lower(), "BKG")
        unique_id = uuid.uuid4().hex[:8].upper()
        return f"{prefix}-{unique_id}"

    def _generate_confirmation(self) -> str:
        """Generate a confirmation number.

        Returns:
            Confirmation number string
        """
        return uuid.uuid4().hex[:10].upper()

    async def create(
        self,
        booking_type: str,
        item_details: dict[str, Any],
    ) -> ProviderBookingResult:
        """Create a mock booking.

        Args:
            booking_type: Type of booking
            item_details: Details of the item

        Returns:
            ProviderBookingResult with booking result (success or failure)
        """
        # Check for injected failures first
        failure_result = self._check_injected_failure(booking_type)
        if failure_result:
            return failure_result

        provider_ref = self._generate_ref(booking_type)
        confirmation = self._generate_confirmation()

        # Store the booking
        self._bookings[provider_ref] = {
            "type": booking_type,
            "details": item_details,
            "status": "confirmed",
            "confirmation": confirmation,
        }

        return ProviderBookingResult(
            success=True,
            provider_ref=provider_ref,
            confirmation_number=confirmation,
            details={
                "type": booking_type,
                **item_details,
                "confirmation_number": confirmation,
            },
        )

    async def modify(
        self,
        provider_ref: str,
        modifications: dict[str, Any],
    ) -> ProviderBookingResult:
        """Modify a mock booking.

        Args:
            provider_ref: Provider reference
            modifications: Changes to apply

        Returns:
            ProviderBookingResult with modification result
        """
        if provider_ref not in self._bookings:
            return ProviderBookingResult(
                success=False,
                provider_ref=provider_ref,
                error_message=f"Booking {provider_ref} not found",
            )

        booking = self._bookings[provider_ref]

        # Store previous state
        previous_details = dict(booking["details"])

        # Apply modifications
        booking["details"].update(modifications)
        booking["status"] = "modified"

        return ProviderBookingResult(
            success=True,
            provider_ref=provider_ref,
            confirmation_number=booking["confirmation"],
            details={
                "previous": previous_details,
                "updated": booking["details"],
                "modification_fee": None,
            },
        )

    async def cancel(
        self,
        provider_ref: str,
    ) -> ProviderBookingResult:
        """Cancel a mock booking.

        Args:
            provider_ref: Provider reference

        Returns:
            ProviderBookingResult with cancellation result
        """
        if provider_ref not in self._bookings:
            return ProviderBookingResult(
                success=False,
                provider_ref=provider_ref,
                error_message=f"Booking {provider_ref} not found",
            )

        booking = self._bookings[provider_ref]
        booking["status"] = "cancelled"
        cancellation_ref = f"CXL-{uuid.uuid4().hex[:8].upper()}"

        return ProviderBookingResult(
            success=True,
            provider_ref=provider_ref,
            details={
                "refund_amount": None,
                "cancellation_fee": None,
                "cancellation_reference": cancellation_ref,
            },
        )

    def get_booking(self, provider_ref: str) -> Optional[dict[str, Any]]:
        """Get a booking by provider reference (for testing).

        Args:
            provider_ref: Provider reference

        Returns:
            Booking data or None if not found
        """
        return self._bookings.get(provider_ref)

    def clear(self) -> None:
        """Clear all bookings and failures (for testing)."""
        self._bookings.clear()
        self.clear_failures()
        self._failure_count = 0
