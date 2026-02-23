"""
Unit tests for ClarificationHandler overflow functionality.

Tests for:
- Overflow callback setup
- Overflow persistence to chat_messages store
- Summary injection in handler
- Integration with ClarifierConversation model
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.orchestrator.handlers.clarification import ClarificationHandler
from src.orchestrator.models.clarifier_conversation import (
    ClarifierConversation,
    SUMMARY_THRESHOLD,
    KEEP_RECENT_COUNT,
)
from src.orchestrator.models.workflow_state import Phase, WorkflowState
from src.orchestrator.state_gating import Action
from src.orchestrator.storage import WorkflowStateData
from src.orchestrator.storage.chat_messages import InMemoryChatMessageStore


class TestOverflowCallbackSetup:
    """Test overflow callback setup in handler."""

    def test_handler_without_chat_store_no_callback(self) -> None:
        """Test that handler without chat store doesn't set up callback."""
        state = WorkflowState(
            session_id="test_session",
            consultation_id="test_consultation",
        )
        state_data = WorkflowStateData(
            session_id="test_session",
            consultation_id="test_consultation",
        )

        handler = ClarificationHandler(
            state=state,
            state_data=state_data,
            a2a_client=None,
            agent_registry=None,
            chat_message_store=None,
        )

        # Callback should not be set
        assert state.clarifier_conversation._overflow_callback is None

    def test_handler_with_chat_store_sets_callback(self) -> None:
        """Test that handler with chat store sets up overflow callback."""
        state = WorkflowState(
            session_id="test_session",
            consultation_id="test_consultation",
        )
        state_data = WorkflowStateData(
            session_id="test_session",
            consultation_id="test_consultation",
        )
        chat_store = InMemoryChatMessageStore()

        handler = ClarificationHandler(
            state=state,
            state_data=state_data,
            a2a_client=None,
            agent_registry=None,
            chat_message_store=chat_store,
        )

        # Callback should be set
        assert state.clarifier_conversation._overflow_callback is not None


class TestOverflowPersistence:
    """Test overflow message persistence to chat_messages store."""

    @pytest.mark.asyncio
    async def test_overflow_persists_to_store(self) -> None:
        """Test that overflow messages are persisted to chat_messages store."""
        state = WorkflowState(
            session_id="test_session",
            consultation_id="test_consultation",
        )
        state_data = WorkflowStateData(
            session_id="test_session",
            consultation_id="test_consultation",
        )
        chat_store = InMemoryChatMessageStore()

        handler = ClarificationHandler(
            state=state,
            state_data=state_data,
            a2a_client=None,
            agent_registry=None,
            chat_message_store=chat_store,
        )

        # Add messages to trigger overflow
        for i in range(SUMMARY_THRESHOLD):
            state.clarifier_conversation.append_message(
                role="user" if i % 2 == 0 else "assistant",
                content=f"message {i}",
            )

        # Give async task time to complete
        import asyncio
        await asyncio.sleep(0.1)

        # Check that messages were persisted to overflow store
        messages = await chat_store.get_messages("test_session")
        expected_overflow = SUMMARY_THRESHOLD - KEEP_RECENT_COUNT
        assert len(messages) == expected_overflow


class TestSummaryInHistoryInjection:
    """Test that summary is included in history injection."""

    def test_history_includes_summary_when_present(self) -> None:
        """Test that history list includes summary as system message."""
        state = WorkflowState(
            session_id="test_session",
            consultation_id="test_consultation",
        )

        # Set up summary on conversation
        state.clarifier_conversation.summary = "User wants to visit Paris in spring"
        state.clarifier_conversation.overflow_message_count = 10
        state.clarifier_conversation.append_turn("More info", "Got it")

        history = state.clarifier_conversation.to_history_list()

        # First message should be summary
        assert len(history) >= 1
        assert history[0]["role"] == "system"
        assert "summary" in history[0]["content"].lower()
        assert "Paris" in history[0]["content"]

    def test_history_without_summary(self) -> None:
        """Test that history without summary doesn't have system message."""
        state = WorkflowState(
            session_id="test_session",
            consultation_id="test_consultation",
        )

        state.clarifier_conversation.append_turn("hello", "hi")
        history = state.clarifier_conversation.to_history_list()

        # Should just have user and assistant messages
        assert len(history) == 2
        assert all(msg["role"] in ("user", "assistant") for msg in history)


class TestOverflowCountSync:
    """Test overflow count synchronization between models."""

    @pytest.mark.asyncio
    async def test_sync_state_to_data_updates_overflow_count(self) -> None:
        """Test that _sync_state_to_data updates overflow count."""
        state = WorkflowState(
            session_id="test_session",
            consultation_id="test_consultation",
        )
        state_data = WorkflowStateData(
            session_id="test_session",
            consultation_id="test_consultation",
        )

        handler = ClarificationHandler(
            state=state,
            state_data=state_data,
        )

        # Manually set overflow count on conversation
        state.clarifier_conversation.overflow_message_count = 25

        # Call sync method
        handler._sync_state_to_data()

        # Should be synced to state
        assert state.conversation_overflow_count == 25


class TestClarifierConversationInHandler:
    """Test ClarifierConversation integration in handler."""

    @pytest.mark.asyncio
    async def test_stub_response_uses_clarifier_conversation(self) -> None:
        """Test that stub response uses ClarifierConversation.append_turn."""
        state = WorkflowState(
            session_id="test_session",
            consultation_id="test_consultation",
        )
        state_data = WorkflowStateData(
            session_id="test_session",
            consultation_id="test_consultation",
        )

        handler = ClarificationHandler(
            state=state,
            state_data=state_data,
        )

        # Execute with stub (no A2A client)
        result = await handler.execute(
            action=Action.CONTINUE_CLARIFICATION,
            message="Plan a trip to Tokyo",
        )

        # Conversation should have the turn added
        assert state.clarifier_conversation.message_count == 2
        assert state.clarifier_conversation.messages[0].role == "user"
        assert "Tokyo" in state.clarifier_conversation.messages[0].content

    @pytest.mark.asyncio
    async def test_multiple_turns_accumulate(self) -> None:
        """Test that multiple turns accumulate in conversation."""
        state = WorkflowState(
            session_id="test_session",
            consultation_id="test_consultation",
        )
        state_data = WorkflowStateData(
            session_id="test_session",
            consultation_id="test_consultation",
        )

        handler = ClarificationHandler(
            state=state,
            state_data=state_data,
        )

        # Execute multiple times
        await handler.execute(Action.CONTINUE_CLARIFICATION, "Trip to Paris")
        await handler.execute(Action.CONTINUE_CLARIFICATION, "In March")
        await handler.execute(Action.CONTINUE_CLARIFICATION, "For 5 days")

        # Should have 6 messages (3 turns * 2)
        assert state.clarifier_conversation.message_count == 6


class TestWorkflowStateSerialization:
    """Test WorkflowState serialization with ClarifierConversation."""

    def test_to_dict_includes_conversation_summary(self) -> None:
        """Test that to_dict includes conversation summary."""
        state = WorkflowState(
            session_id="test_session",
            consultation_id="test_consultation",
        )
        state.clarifier_conversation.summary = "Trip planning summary"
        state.clarifier_conversation.overflow_message_count = 15
        state.clarifier_conversation.append_turn("hello", "hi")

        data = state.to_dict()

        # Check conversation data
        conv_data = data["clarifier_conversation"]
        assert conv_data["summary"] == "Trip planning summary"
        assert conv_data["overflow_message_count"] == 15
        assert len(conv_data["messages"]) == 2

    def test_from_dict_restores_conversation(self) -> None:
        """Test that from_dict restores conversation with summary."""
        data = {
            "session_id": "test_session",
            "consultation_id": "test_consultation",
            "workflow_version": 1,
            "phase": "clarification",
            "clarifier_conversation": {
                "agent_name": "clarifier",
                "messages": [
                    {
                        "messageId": "msg_1",
                        "role": "user",
                        "content": "hello",
                        "timestamp": "2025-01-01T12:00:00+00:00",
                    }
                ],
                "current_seq": 1,
                "summary": "Restored summary",
                "overflow_message_count": 20,
            },
        }

        state = WorkflowState.from_dict(data)

        assert state.clarifier_conversation.summary == "Restored summary"
        assert state.clarifier_conversation.overflow_message_count == 20
        assert len(state.clarifier_conversation.messages) == 1

    def test_roundtrip_preserves_all_fields(self) -> None:
        """Test serialization roundtrip preserves all conversation fields."""
        state1 = WorkflowState(
            session_id="test_session",
            consultation_id="test_consultation",
        )
        state1.clarifier_conversation.append_turn("hello", "hi")
        state1.clarifier_conversation.summary = "Summary text"
        state1.clarifier_conversation.overflow_message_count = 10

        data = state1.to_dict()
        state2 = WorkflowState.from_dict(data)

        assert state2.clarifier_conversation.message_count == state1.clarifier_conversation.message_count
        assert state2.clarifier_conversation.summary == state1.clarifier_conversation.summary
        assert state2.clarifier_conversation.overflow_message_count == state1.clarifier_conversation.overflow_message_count
        assert state2.clarifier_conversation.current_seq == state1.clarifier_conversation.current_seq


class TestBackwardCompatibility:
    """Test backward compatibility with old data format."""

    def test_from_dict_handles_legacy_agent_conversation(self) -> None:
        """Test that from_dict handles legacy AgentConversation format."""
        # Old format without summary and overflow_message_count
        data = {
            "session_id": "test_session",
            "consultation_id": "test_consultation",
            "workflow_version": 1,
            "phase": "clarification",
            "clarifier_conversation": {
                "agent_name": "clarifier",
                "messages": [
                    {
                        "messageId": "msg_1",
                        "role": "user",
                        "content": "hello",
                        "timestamp": "2025-01-01T12:00:00+00:00",
                    }
                ],
                "current_seq": 1,
            },
            "conversation_overflow_count": 5,  # Top-level field for backward compat
        }

        state = WorkflowState.from_dict(data)

        # Should handle missing summary gracefully
        assert state.clarifier_conversation.summary is None
        # Should pick up overflow count from top-level field
        assert state.clarifier_conversation.overflow_message_count == 5

    def test_from_dict_prefers_conversation_overflow_count(self) -> None:
        """Test that conversation's overflow count takes precedence."""
        data = {
            "session_id": "test_session",
            "consultation_id": "test_consultation",
            "workflow_version": 1,
            "phase": "clarification",
            "clarifier_conversation": {
                "agent_name": "clarifier",
                "messages": [],
                "current_seq": 0,
                "overflow_message_count": 15,  # In conversation
            },
            "conversation_overflow_count": 10,  # Top-level (should be ignored)
        }

        state = WorkflowState.from_dict(data)

        # Conversation's value should be used
        assert state.clarifier_conversation.overflow_message_count == 15


class TestClarificationHandlerUsesConversation:
    """Test that ClarificationHandler correctly uses the conversation."""

    @pytest.mark.asyncio
    async def test_handler_uses_conversation_history_for_injection(self) -> None:
        """Test that handler uses conversation history for A2A injection."""
        state = WorkflowState(
            session_id="test_session",
            consultation_id="test_consultation",
        )
        # Pre-populate conversation
        state.clarifier_conversation.append_turn("previous user", "previous response")
        state.clarifier_conversation.summary = "Summary from before"

        state_data = WorkflowStateData(
            session_id="test_session",
            consultation_id="test_consultation",
        )

        # Mock A2A client
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.context_id = "ctx_123"
        mock_response.task_id = "task_123"
        mock_response.is_complete = False
        mock_response.text = "agent response"
        mock_client.send_message = AsyncMock(return_value=mock_response)

        # Mock agent registry
        mock_registry = MagicMock()
        mock_agent_config = MagicMock()
        mock_agent_config.url = "http://clarifier:8001"
        mock_registry.get.return_value = mock_agent_config

        handler = ClarificationHandler(
            state=state,
            state_data=state_data,
            a2a_client=mock_client,
            agent_registry=mock_registry,
        )

        await handler.execute(Action.CONTINUE_CLARIFICATION, "new message")

        # Check that send_message was called with history
        mock_client.send_message.assert_called_once()
        call_kwargs = mock_client.send_message.call_args.kwargs

        # History should include summary and previous messages
        assert call_kwargs.get("history") is not None
        history = call_kwargs["history"]
        # First entry should be summary
        assert any("summary" in str(h.get("content", "")).lower() for h in history)
