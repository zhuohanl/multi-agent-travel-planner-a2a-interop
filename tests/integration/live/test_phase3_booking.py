"""
Tier 2: Live integration tests for Phase 3 (Booking).

Prerequisites:
    - Booking agent running

Run (only at phase milestones):
    uv run python src/run_all.py  # Terminal 1
    uv run pytest tests/integration/live/test_phase3_booking.py -v  # Terminal 2

WARNING: These tests make real LLM calls and consume Azure OpenAI quota.
Only run at phase completion milestones, not on every ticket.

NOTE: Booking tests should use test/sandbox booking APIs to avoid real charges.
"""

import pytest

from src.shared.a2a.client_wrapper import A2AClientWrapper

from .conftest import AGENT_URLS, check_agent_health


class TestBookingFlow:
    """Integration tests for booking operations."""

    @pytest.fixture
    async def a2a_client(self) -> A2AClientWrapper:
        async with A2AClientWrapper(timeout_seconds=120.0) as client:
            yield client

    @pytest.fixture
    async def require_booking_agent(self, http_client) -> str:
        """Ensure booking agent is running."""
        healthy = await check_agent_health(http_client, "booking")
        if not healthy:
            pytest.skip("Booking agent not running")
        return AGENT_URLS["booking"]

    @pytest.mark.asyncio
    async def test_booking_agent_health(
        self, http_client, require_booking_agent: str
    ) -> None:
        """Test booking agent is healthy."""
        healthy = await check_agent_health(http_client, "booking")
        assert healthy

    @pytest.mark.asyncio
    async def test_booking_availability_check(
        self, a2a_client: A2AClientWrapper, require_booking_agent: str
    ) -> None:
        """Test booking agent can check availability."""
        response = await a2a_client.send_message(
            agent_url=require_booking_agent,
            message="Check availability for a hotel in Tokyo, March 10-15, 2026",
        )

        assert response.text is not None
        assert len(response.text) > 0

    @pytest.mark.asyncio
    async def test_booking_request_format(
        self, a2a_client: A2AClientWrapper, require_booking_agent: str
    ) -> None:
        """Test booking agent accepts properly formatted requests."""
        response = await a2a_client.send_message(
            agent_url=require_booking_agent,
            message=(
                "I would like to book a hotel room. "
                "Hotel: Park Hyatt Tokyo. "
                "Check-in: March 10, 2026. "
                "Check-out: March 15, 2026. "
                "Guests: 2 adults."
            ),
        )

        assert response.text is not None


class TestBookingIdempotency:
    """
    Integration tests for booking idempotency.

    Note: These tests are marked as expected failures until
    Phase 3 tickets (ORCH-051 to ORCH-053) are implemented.
    """

    @pytest.fixture
    async def a2a_client(self) -> A2AClientWrapper:
        async with A2AClientWrapper(timeout_seconds=120.0) as client:
            yield client

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="ORCH-051: booking idempotency not yet implemented")
    async def test_duplicate_booking_returns_same_result(
        self, a2a_client: A2AClientWrapper, http_client
    ) -> None:
        """Test that duplicate booking requests are idempotent."""
        if not await check_agent_health(http_client, "booking"):
            pytest.skip("Booking agent not running")

        booking_url = AGENT_URLS["booking"]
        booking_request = (
            "Book hotel with booking_id: TEST-IDEM-001. "
            "Hotel: Test Hotel. Dates: March 10-15, 2026."
        )

        # First request
        r1 = await a2a_client.send_message(
            agent_url=booking_url,
            message=booking_request,
        )

        # Second request with same booking_id
        r2 = await a2a_client.send_message(
            agent_url=booking_url,
            message=booking_request,
        )

        # Both should return consistent results (idempotent)
        # Implementation details will determine exact matching


class TestQuoteValidation:
    """
    Integration tests for quote validation.

    Note: These tests are marked as expected failures until
    ORCH-053 (quote validation) is implemented.
    """

    @pytest.fixture
    async def a2a_client(self) -> A2AClientWrapper:
        async with A2AClientWrapper(timeout_seconds=120.0) as client:
            yield client

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="ORCH-053: quote validation not yet implemented")
    async def test_booking_with_valid_quote(
        self, a2a_client: A2AClientWrapper, http_client
    ) -> None:
        """Test booking with valid quote is accepted."""
        if not await check_agent_health(http_client, "booking"):
            pytest.skip("Booking agent not running")

        booking_url = AGENT_URLS["booking"]

        # Step 1: Get a quote
        quote_response = await a2a_client.send_message(
            agent_url=booking_url,
            message="Get a quote for Park Hyatt Tokyo, March 10-15, 2026",
        )

        # Step 2: Confirm with quote_id
        # This requires extracting quote_id from the response
        # and sending a confirmation - implementation specific

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="ORCH-053: quote validation not yet implemented")
    async def test_booking_with_expired_quote_rejected(
        self, a2a_client: A2AClientWrapper, http_client
    ) -> None:
        """Test that expired quotes are rejected."""
        if not await check_agent_health(http_client, "booking"):
            pytest.skip("Booking agent not running")

        booking_url = AGENT_URLS["booking"]

        response = await a2a_client.send_message(
            agent_url=booking_url,
            message="Confirm booking with quote_id: EXPIRED-QUOTE-001",
        )

        # Should indicate quote is expired or invalid
        assert "expired" in response.text.lower() or "invalid" in response.text.lower()
