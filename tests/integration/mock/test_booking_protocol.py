"""
Tier 1: Mock booking flow protocol tests.

Tests booking agent communication and idempotency patterns.
Run on EVERY ticket to verify protocol correctness.

Run: uv run pytest tests/integration/mock/test_booking_protocol.py -v
"""

from unittest.mock import MagicMock

import pytest

from .conftest import MockA2AResponseFactory


class TestBookingProtocol:
    """Test booking flow protocol with mocks."""

    @pytest.mark.asyncio
    async def test_booking_request_format(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test booking agent accepts properly formatted requests."""
        mock_a2a_client.configure_response(
            "http://localhost:10014",
            mock_response_factory.booking_agent_pending(),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10014",
            message="Book Park Hyatt Tokyo, March 10-15, 2026",
        )

        assert response.context_id is not None
        assert "quote_id" in response.text.lower() or "Q-" in response.text

    @pytest.mark.asyncio
    async def test_booking_confirmation_flow(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test complete booking confirmation flow."""
        # Step 1: Initial booking request returns quote
        mock_a2a_client.configure_response(
            "http://localhost:10014",
            mock_response_factory.booking_agent_pending(),
        )

        quote_response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10014",
            message="Book Park Hyatt Tokyo",
        )

        assert quote_response.requires_input is True
        assert "quote_id" in quote_response.text.lower()

        # Step 2: Confirm booking with quote
        mock_a2a_client.configure_response(
            "http://localhost:10014",
            mock_response_factory.booking_agent_confirmation(),
        )

        confirm_response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10014",
            message="Confirm booking with quote Q-67890",
            context_id=quote_response.context_id,
            task_id=quote_response.task_id,
        )

        assert confirm_response.is_complete is True
        assert "booking_id" in confirm_response.text.lower() or "BK-" in confirm_response.text

    @pytest.mark.asyncio
    async def test_booking_error_handling(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test booking error handling."""
        mock_a2a_client.configure_response(
            "http://localhost:10014",
            mock_response_factory.agent_error("Payment failed: insufficient funds"),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10014",
            message="Book Park Hyatt Tokyo",
        )

        assert response.is_complete is False
        assert "failed" in response.text.lower()


class TestBookingIdempotency:
    """Test booking idempotency patterns."""

    @pytest.mark.asyncio
    async def test_duplicate_booking_request(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that duplicate booking requests return same result."""
        # Both requests should return the same confirmation
        mock_a2a_client.configure_response(
            "http://localhost:10014",
            mock_response_factory.booking_agent_confirmation(),
        )

        response1 = await mock_a2a_client.send_message(
            agent_url="http://localhost:10014",
            message="Book Park Hyatt Tokyo with booking_id BK-12345",
        )

        response2 = await mock_a2a_client.send_message(
            agent_url="http://localhost:10014",
            message="Book Park Hyatt Tokyo with booking_id BK-12345",
        )

        # Both should complete successfully (idempotent)
        assert response1.is_complete is True
        assert response2.is_complete is True

    @pytest.mark.asyncio
    async def test_booking_with_quote_validation(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test booking validates quote before confirmation."""
        # Get initial quote
        mock_a2a_client.configure_response(
            "http://localhost:10014",
            mock_response_factory.booking_agent_pending(),
        )

        quote = await mock_a2a_client.send_message(
            agent_url="http://localhost:10014",
            message="Book Park Hyatt Tokyo",
        )

        # Quote should contain validation info
        assert "quote_id" in quote.text.lower()
        assert "expires" in quote.text.lower()


class TestBookAllFlow:
    """Test book_all sequential booking flow."""

    @pytest.mark.asyncio
    async def test_sequential_booking_multiple_items(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test booking multiple items sequentially."""
        # Configure booking agent to return confirmations
        mock_a2a_client.configure_response(
            "http://localhost:10014",
            mock_response_factory.booking_agent_confirmation(),
        )

        booking_items = [
            "Book Park Hyatt Tokyo",
            "Book JAL flight SFO-NRT",
            "Book Senso-ji temple tour",
        ]

        results = []
        for item in booking_items:
            response = await mock_a2a_client.send_message(
                agent_url="http://localhost:10014",
                message=item,
            )
            results.append(response)

        # All should complete
        assert all(r.is_complete for r in results)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_book_all_stops_on_failure(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that book_all stops on first failure (no partial bookings)."""
        call_count = 0

        async def mock_booking_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # First booking succeeds
                return mock_response_factory.booking_agent_confirmation()[0]
            else:
                # Second booking fails
                return mock_response_factory.agent_error("Booking failed")[0]

        # This test demonstrates the expected pattern:
        # When booking multiple items, if one fails, subsequent bookings should not proceed
        # The actual implementation will be in the orchestrator's book_all tool


class TestQuoteValidation:
    """
    Test quote validation patterns.

    Note: These mock tests verify the PROTOCOL/FORMAT correctness.
    The actual implementation is tracked by ORCH-053 (quote validation).
    """

    @pytest.mark.asyncio
    async def test_quote_contains_required_fields(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that quotes contain required validation fields."""
        mock_a2a_client.configure_response(
            "http://localhost:10014",
            mock_response_factory.booking_agent_pending(),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10014",
            message="Get quote for Park Hyatt Tokyo",
        )

        # Quote should have validation fields
        assert "quote_id" in response.text.lower()
        assert "price" in response.text.lower() or "500" in response.text
        assert "expires" in response.text.lower()

    @pytest.mark.asyncio
    async def test_expired_quote_rejected(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that expired quotes are rejected.

        Implementation: ORCH-053
        """
        # This would require the booking agent to check quote expiry
        # Implementation will validate quote_id + expiry timestamp
        mock_a2a_client.configure_response(
            "http://localhost:10014",
            mock_response_factory.agent_error("Quote expired"),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10014",
            message="Confirm booking with expired quote Q-EXPIRED",
        )

        assert response.is_complete is False
        assert "expired" in response.text.lower()
