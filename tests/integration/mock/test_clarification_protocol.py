"""
Tier 1: Mock clarification flow protocol tests.

Tests the multi-turn clarification flow using mock responses.
Run on EVERY ticket to verify protocol correctness.

Run: uv run pytest tests/integration/mock/test_clarification_protocol.py -v
"""

from unittest.mock import MagicMock

import pytest

from .conftest import MockA2AResponseFactory


class TestClarificationProtocol:
    """Test clarification flow protocol with mocks."""

    @pytest.mark.asyncio
    async def test_multi_turn_context_chain(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that multi-turn conversation maintains context chain."""
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.clarifier_asking_destination(),
        )

        context_id: str | None = None
        task_id: str | None = None

        # Simulate 3 turns
        for i, message in enumerate(["Plan trip", "To Paris", "Next week"]):
            response = await mock_a2a_client.send_message(
                agent_url="http://localhost:10007",
                message=message,
                context_id=context_id,
                task_id=task_id,
            )
            context_id = response.context_id or context_id
            task_id = response.task_id or task_id

        # Verify context was maintained
        assert context_id is not None
        assert task_id is not None

    @pytest.mark.asyncio
    async def test_clarifier_transitions_from_input_required_to_completed(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test clarifier transitions from input_required to completed."""
        # First turn: asking for destination
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.clarifier_asking_destination(),
        )

        r1 = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="I want to plan a trip",
        )

        assert r1.requires_input is True
        assert r1.is_complete is False

        # Final turn: complete with TripSpec
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.clarifier_complete_tripspec(),
        )

        r2 = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="Tokyo, March 10-17, 2 people",
            context_id=r1.context_id,
            task_id=r1.task_id,
        )

        assert r2.is_complete is True
        assert r2.requires_input is False
        assert "Tokyo" in r2.text

    @pytest.mark.asyncio
    async def test_clarifier_full_conversation_flow(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test complete clarification flow: destination → dates → travelers → complete."""
        context_id: str | None = None
        task_id: str | None = None

        # Turn 1: Initial request, clarifier asks for destination
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.clarifier_asking_destination(),
        )
        r1 = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="Help me plan a vacation",
            context_id=context_id,
            task_id=task_id,
        )
        context_id, task_id = r1.context_id, r1.task_id
        assert r1.requires_input is True
        assert "where" in r1.text.lower()

        # Turn 2: User provides destination, clarifier asks for dates
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.clarifier_asking_dates(),
        )
        r2 = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="Tokyo, Japan",
            context_id=context_id,
            task_id=task_id,
        )
        assert r2.requires_input is True
        assert "when" in r2.text.lower() or "date" in r2.text.lower()

        # Turn 3: User provides dates, clarifier asks for travelers
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.clarifier_asking_travelers(),
        )
        r3 = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="March 10-17, 2026",
            context_id=context_id,
            task_id=task_id,
        )
        assert r3.requires_input is True
        assert "people" in r3.text.lower() or "traveler" in r3.text.lower()

        # Turn 4: User provides travelers, clarifier completes
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.clarifier_complete_tripspec(),
        )
        r4 = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="2 adults",
            context_id=context_id,
            task_id=task_id,
        )
        assert r4.is_complete is True
        assert "Tokyo" in r4.text


class TestClarificationErrorHandling:
    """Test error handling in clarification flow."""

    @pytest.mark.asyncio
    async def test_clarifier_handles_error_gracefully(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that clarifier errors are handled gracefully."""
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.agent_error("Internal server error"),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="Plan a trip",
        )

        assert response.is_complete is False
        assert "error" in response.text.lower()

    @pytest.mark.asyncio
    async def test_clarifier_timeout_handling(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test timeout handling for clarifier."""
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.agent_timeout(),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="Plan a trip",
        )

        assert response.is_complete is False
        assert "timed out" in response.text.lower()


class TestDivergenceRecovery:
    """
    Test divergence detection and recovery flows.

    Per design doc (Agent Communication section):
    - Count-based divergence detection using historySeq
    - Compare len(history) vs len(cached_thread.messages)
    - On mismatch: invalidate cache and rebuild from client-provided history

    Note: These mock tests verify the PROTOCOL/FORMAT correctness.
    The actual implementation is tracked by ORCH-009 (divergence detection).
    """

    @pytest.mark.asyncio
    async def test_divergence_recovery_flow(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that divergence triggers history rebuild.

        Implementation: ORCH-009
        """
        # Simulate a scenario where client history differs from server
        history = [
            {"role": "user", "content": "Plan a trip"},
            {"role": "assistant", "content": "Where to?"},
            {"role": "user", "content": "Tokyo"},
        ]

        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.response_with_history_ack(last_seen_seq=3),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="For next week",
            context_id="ctx_clarifier_001",
            task_id="task_clarifier_001",
            history=history,
            history_seq=3,  # Per design doc: sequence number for divergence detection
        )

        # Verify history was sent for potential rebuild
        call_kwargs = mock_a2a_client.send_message.call_args.kwargs
        assert call_kwargs.get("history_seq") == 3

    @pytest.mark.asyncio
    async def test_divergence_detected_when_seq_mismatch(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that divergence is detected when sequence numbers don't match.

        Implementation: ORCH-009
        """
        # Client has 3 messages, but server cached 5 (divergence!)
        history = [
            {"role": "user", "content": "Plan a trip"},
            {"role": "assistant", "content": "Where to?"},
            {"role": "user", "content": "Tokyo"},
        ]

        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.divergence_detected_response(
                expected_seq=5,  # Server expected 5
                received_seq=3,  # Client sent 3
            ),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="For next week",
            context_id="ctx_clarifier_001",
            task_id="task_clarifier_001",
            history=history,
            history_seq=3,
        )

        # Response should indicate divergence was detected and handled
        assert "divergence" in response.text.lower() or "rebuilt" in response.text.lower()

    @pytest.mark.asyncio
    async def test_history_always_sent_for_reliability(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that history is always sent (not just on context_id miss).

        Implementation: ORCH-001, ORCH-002

        Per design doc: History is always sent (not just on context_id miss) for reliability.
        This handles agent restarts, context cache expiry, and orchestrator failover.
        """
        history = [
            {"role": "user", "content": "Plan a trip"},
            {"role": "assistant", "content": "Where to?"},
        ]

        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.response_with_history_ack(last_seen_seq=2),
        )

        # Even with valid context_id, history should still be sent
        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="Tokyo",
            context_id="ctx_clarifier_001",  # Valid context_id
            task_id="task_clarifier_001",
            history=history,
            history_seq=2,
        )

        # Verify history was sent even with valid context
        call_kwargs = mock_a2a_client.send_message.call_args.kwargs
        assert "history" in call_kwargs
        assert call_kwargs.get("history_seq") == 2
