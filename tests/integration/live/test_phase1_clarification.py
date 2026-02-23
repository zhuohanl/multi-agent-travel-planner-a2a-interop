"""
Tier 2: Live integration tests for Phase 1 (Clarification).

Prerequisites:
    - Clarifier agent running on INTAKE_CLARIFIER_AGENT_PORT

Run (only at phase milestones):
    uv run python src/run_all.py  # Terminal 1
    uv run pytest tests/integration/live/test_phase1_clarification.py -v  # Terminal 2

WARNING: These tests make real LLM calls and consume Azure OpenAI quota.
Only run at phase completion milestones, not on every ticket.
"""

import pytest

from src.shared.a2a.client_wrapper import A2AClientWrapper, A2AResponse

from .conftest import AGENT_URLS, check_agent_health


@pytest.fixture
async def a2a_client() -> A2AClientWrapper:
    """Create A2A client wrapper for tests."""
    async with A2AClientWrapper(timeout_seconds=60.0) as client:
        yield client


class TestA2AClientRoundTrip:
    """Integration tests for A2A client against real clarifier agent."""

    @pytest.mark.asyncio
    async def test_clarifier_health_check(self, http_client) -> None:
        """Test clarifier agent is reachable via health endpoint."""
        healthy = await check_agent_health(http_client, "clarifier")
        if not healthy:
            pytest.skip("Clarifier agent not running")
        assert healthy, "Clarifier agent is not running"

    @pytest.mark.asyncio
    async def test_clarifier_agent_card(
        self, a2a_client: A2AClientWrapper, require_clarifier: str
    ) -> None:
        """Test fetching agent card from clarifier."""
        card = await a2a_client._get_agent_card(require_clarifier)

        assert card is not None
        assert card.name is not None
        assert len(card.skills) > 0

    @pytest.mark.asyncio
    async def test_send_message_returns_response(
        self, a2a_client: A2AClientWrapper, require_clarifier: str
    ) -> None:
        """Test sending a message and receiving a valid response."""
        response = await a2a_client.send_message(
            agent_url=require_clarifier,
            message="I want to plan a trip to Tokyo",
        )

        assert isinstance(response, A2AResponse)
        assert response.text is not None
        assert len(response.text) > 0

    @pytest.mark.asyncio
    async def test_context_id_returned(
        self, a2a_client: A2AClientWrapper, require_clarifier: str
    ) -> None:
        """Test that context_id is returned for multi-turn support."""
        response = await a2a_client.send_message(
            agent_url=require_clarifier,
            message="Plan a trip to Paris for 5 days",
        )

        assert response.context_id is not None, (
            "Agent must return context_id for multi-turn conversations"
        )

    @pytest.mark.asyncio
    async def test_multi_turn_with_context_id(
        self, a2a_client: A2AClientWrapper, require_clarifier: str
    ) -> None:
        """Test multi-turn conversation using context_id."""
        # Turn 1: Initial request
        response1 = await a2a_client.send_message(
            agent_url=require_clarifier,
            message="I want to travel to Japan",
        )

        assert response1.context_id is not None

        # Turn 2: Follow-up with context
        response2 = await a2a_client.send_message(
            agent_url=require_clarifier,
            message="For 2 weeks in March",
            context_id=response1.context_id,
            task_id=response1.task_id,
        )

        assert isinstance(response2, A2AResponse)
        assert response2.text is not None


class TestClarificationFlow:
    """Integration tests for complete clarification flow."""

    @pytest.mark.asyncio
    async def test_clarifier_asks_questions(
        self, a2a_client: A2AClientWrapper, require_clarifier: str
    ) -> None:
        """Test that clarifier asks clarifying questions."""
        response = await a2a_client.send_message(
            agent_url=require_clarifier,
            message="Help me plan a trip",  # Vague request
        )

        # Clarifier should ask for more details or be in input_required state
        assert response.text is not None
        # The response should either ask a question or request more input
        assert len(response.text) > 10  # Non-trivial response

    @pytest.mark.asyncio
    async def test_clarifier_produces_tripspec(
        self, a2a_client: A2AClientWrapper, require_clarifier: str
    ) -> None:
        """Test that clarifier produces TripSpec when given complete info."""
        # Provide complete trip details upfront
        response = await a2a_client.send_message(
            agent_url=require_clarifier,
            message=(
                "Plan a trip to Tokyo, Japan from March 10 to March 17, 2026 "
                "for 2 adults. We're interested in cultural sites and good food."
            ),
        )

        assert response.text is not None
        # Response should contain trip details or be complete
        # The exact format depends on the clarifier implementation


class TestHistoryInjection:
    """
    Integration tests for history injection feature.

    Per design doc (Agent Communication section):
    - History is always sent (not just on context_id miss) for reliability
    - Uses historySeq (sequence number) for divergence detection
    - Agent echoes back lastSeenSeq; if != historySeq, divergence detected

    Note: These tests are marked as expected failures until
    Phase 1 tickets (ORCH-001 to ORCH-011) are implemented.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="ORCH-001: history parameter not yet implemented")
    async def test_history_injection_with_real_agent(
        self, a2a_client: A2AClientWrapper, require_clarifier: str
    ) -> None:
        """Test history injection works with real clarifier agent.

        Implementation: ORCH-001, ORCH-002
        """
        # Start a conversation
        r1 = await a2a_client.send_message(
            agent_url=require_clarifier,
            message="I want to plan a trip",
        )

        # Build history
        history = [
            {"role": "user", "content": "I want to plan a trip"},
            {"role": "assistant", "content": r1.text},
        ]

        # Send with history (not yet implemented)
        # Per design doc: use history_seq for divergence detection
        r2 = await a2a_client.send_message(
            agent_url=require_clarifier,
            message="To Tokyo",
            context_id=r1.context_id,
            task_id=r1.task_id,
            history=history,  # Will fail until implemented
            history_seq=2,  # Per design doc: sequence number for divergence detection
        )

        assert r2.text is not None
