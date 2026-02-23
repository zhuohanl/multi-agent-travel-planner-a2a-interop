"""
Tier 1: Mock A2A client protocol tests.

Run on EVERY ticket to verify protocol correctness.
These tests use mock responses and have zero LLM cost.

Run: uv run pytest tests/integration/mock/test_a2a_client_protocol.py -v
"""

from unittest.mock import MagicMock

import pytest

from .conftest import MockA2AResponseFactory


class TestA2AClientProtocol:
    """Test A2A client protocol handling with mock responses."""

    @pytest.mark.asyncio
    async def test_context_id_extracted_from_response(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that context_id is correctly extracted from response."""
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.clarifier_asking_destination(),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="I want to plan a trip",
        )

        assert response.context_id == "ctx_clarifier_001"

    @pytest.mark.asyncio
    async def test_task_id_extracted_from_task_kind(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that task_id is extracted when kind=task."""
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.clarifier_asking_destination(),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="Plan a trip",
        )

        assert response.task_id == "task_clarifier_001"

    @pytest.mark.asyncio
    async def test_input_required_status_detected(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that input_required status is correctly detected."""
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.clarifier_asking_destination(),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="Help me travel",
        )

        assert response.requires_input is True
        assert response.is_complete is False

    @pytest.mark.asyncio
    async def test_completed_status_detected(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that completed status is correctly detected."""
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.clarifier_complete_tripspec(),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="Tokyo, March 10-17, 2 adults",
        )

        assert response.is_complete is True
        assert response.requires_input is False

    @pytest.mark.asyncio
    async def test_context_id_passed_to_subsequent_calls(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that context_id from first response is passed to second call."""
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.clarifier_asking_destination(),
        )

        # First call
        response1 = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="Plan a trip",
        )

        # Second call with context from first
        response2 = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="To Tokyo",
            context_id=response1.context_id,
            task_id=response1.task_id,
        )

        # Verify the call was made with context
        calls = mock_a2a_client.send_message.call_args_list
        assert len(calls) == 2
        assert calls[1].kwargs.get("context_id") == "ctx_clarifier_001"
        assert calls[1].kwargs.get("task_id") == "task_clarifier_001"

    @pytest.mark.asyncio
    async def test_text_extracted_from_message_parts(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that text content is extracted from message parts."""
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.clarifier_asking_destination(),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="Plan a trip",
        )

        assert "Where would you like to travel to?" in response.text

    @pytest.mark.asyncio
    async def test_failed_status_handling(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test handling of failed status responses."""
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.agent_error("Connection failed"),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="Plan a trip",
        )

        assert response.is_complete is False
        assert response.requires_input is False
        assert "Connection failed" in response.text


class TestA2AClientContextManagement:
    """Test A2A client context management patterns."""

    @pytest.mark.asyncio
    async def test_new_conversation_gets_new_context(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that new conversations without context_id get new context."""
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.clarifier_asking_destination(),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="Plan a trip",
            # No context_id provided - new conversation
        )

        # Should receive a new context_id from agent
        assert response.context_id is not None
        assert response.context_id.startswith("ctx_")

    @pytest.mark.asyncio
    async def test_context_preserved_in_multi_turn(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that context is preserved across multiple turns."""
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.clarifier_asking_destination(),
        )

        # Turn 1
        r1 = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="Plan a trip",
        )

        # Turn 2 - should use context from Turn 1
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.clarifier_asking_dates(),
        )

        r2 = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="To Tokyo",
            context_id=r1.context_id,
            task_id=r1.task_id,
        )

        # Context should be maintained (same conversation)
        assert r2.context_id == r1.context_id


class TestHistoryInjection:
    """
    Test history injection via message.metadata.

    Per design doc (Agent Communication section):
    - History is always sent (not just on context_id miss) for reliability
    - Uses historySeq (sequence number) for divergence detection
    - Agent echoes back lastSeenSeq; if != historySeq, divergence detected

    Note: These mock tests verify the PROTOCOL/FORMAT correctness.
    The actual implementation is tracked by:
    - ORCH-001: history parameter in A2AClientWrapper.send_message()
    - ORCH-002: history_seq parameter for divergence detection
    """

    @pytest.mark.asyncio
    async def test_history_injected_in_metadata(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that history is injected via message.metadata.

        Implementation: ORCH-001
        """
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.clarifier_asking_dates(),
        )

        history = [
            {"role": "user", "content": "Plan a trip"},
            {"role": "assistant", "content": "Where would you like to go?"},
        ]

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="To Tokyo",
            context_id="ctx_clarifier_001",
            task_id="task_clarifier_001",
            history=history,  # Per design doc: always sent for reliability
        )

        # Verify history was passed
        call_kwargs = mock_a2a_client.send_message.call_args.kwargs
        assert "history" in call_kwargs
        assert len(call_kwargs["history"]) == 2

    @pytest.mark.asyncio
    async def test_history_seq_passed_for_divergence_detection(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that history_seq is passed for divergence detection.

        Implementation: ORCH-002

        Per design doc (Agent Communication section):
        - We control the sequence numbers (not message IDs which differ across systems)
        - Agent echoes back lastSeenSeq; if != history_seq, divergence detected
        """
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.response_with_history_ack(
                context_id="ctx_clarifier_001",
                last_seen_seq=5,  # Agent acknowledges receiving sequence 5
            ),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="To Tokyo",
            context_id="ctx_clarifier_001",
            history_seq=5,  # Per design doc: sequence number for divergence detection
        )

        call_kwargs = mock_a2a_client.send_message.call_args.kwargs
        assert call_kwargs.get("history_seq") == 5

    @pytest.mark.asyncio
    async def test_history_and_seq_sent_together(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that history and history_seq are sent together per design doc.

        Implementation: ORCH-001, ORCH-002
        """
        mock_a2a_client.configure_response(
            "http://localhost:10007",
            mock_response_factory.response_with_history_ack(last_seen_seq=3),
        )

        history = [
            {"role": "user", "content": "Plan a trip"},
            {"role": "assistant", "content": "Where would you like to go?"},
            {"role": "user", "content": "Tokyo"},
        ]

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10007",
            message="For next week",
            context_id="ctx_clarifier_001",
            task_id="task_clarifier_001",
            history=history,
            history_seq=3,  # len(history) for divergence detection
        )

        call_kwargs = mock_a2a_client.send_message.call_args.kwargs
        assert "history" in call_kwargs
        assert call_kwargs.get("history_seq") == 3
