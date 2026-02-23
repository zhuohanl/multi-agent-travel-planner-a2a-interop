"""
Unit tests for ClarifierConversation model.

Tests for the overflow-aware conversation model that:
- Tracks conversation with Clarifier agent
- Summarizes when message count reaches threshold
- Persists overflow messages to external store
- Maintains rolling summary of older messages
"""

import pytest
from datetime import datetime, timezone

from src.orchestrator.models.clarifier_conversation import (
    ClarifierConversation,
    MAX_MESSAGES_IN_STATE,
    SUMMARY_THRESHOLD,
    KEEP_RECENT_COUNT,
    summarize_messages,
)
from src.orchestrator.models.conversation import ConversationMessage


class TestClarifierConversationBasics:
    """Test basic conversation functionality."""

    def test_create_empty_conversation(self) -> None:
        """Test creating an empty conversation."""
        conv = ClarifierConversation()
        assert conv.agent_name == "clarifier"
        assert conv.messages == []
        assert conv.current_seq == 0
        assert conv.summary is None
        assert conv.overflow_message_count == 0

    def test_create_with_agent_name(self) -> None:
        """Test creating conversation with custom agent name."""
        conv = ClarifierConversation(agent_name="test_agent")
        assert conv.agent_name == "test_agent"

    def test_message_count_property(self) -> None:
        """Test message_count property."""
        conv = ClarifierConversation()
        assert conv.message_count == 0

        conv.append_turn("hello", "world")
        assert conv.message_count == 2  # user + assistant

    def test_total_message_count_property(self) -> None:
        """Test total_message_count includes overflow."""
        conv = ClarifierConversation()
        conv.append_turn("hello", "world")
        assert conv.total_message_count == 2

        conv.overflow_message_count = 10
        assert conv.total_message_count == 12

    def test_next_seq_property(self) -> None:
        """Test next_seq property."""
        conv = ClarifierConversation()
        assert conv.next_seq == 1

        conv.current_seq = 5
        assert conv.next_seq == 6


class TestAppendTurn:
    """Test append_turn functionality."""

    def test_append_turn_adds_two_messages(self) -> None:
        """Test that append_turn adds user and assistant messages."""
        conv = ClarifierConversation()
        conv.append_turn("user message", "assistant response")

        assert len(conv.messages) == 2
        assert conv.messages[0].role == "user"
        assert conv.messages[0].content == "user message"
        assert conv.messages[1].role == "assistant"
        assert conv.messages[1].content == "assistant response"

    def test_append_turn_increments_seq(self) -> None:
        """Test that append_turn increments sequence number twice."""
        conv = ClarifierConversation()
        assert conv.current_seq == 0

        conv.append_turn("hello", "hi")
        assert conv.current_seq == 2  # Two increments

        conv.append_turn("how are you", "good")
        assert conv.current_seq == 4

    def test_append_turn_sets_message_metadata(self) -> None:
        """Test that append_turn sets metadata with sequence numbers."""
        conv = ClarifierConversation()
        conv.append_turn("hello", "hi")

        assert conv.messages[0].metadata is not None
        assert conv.messages[0].metadata.get("seq") == 1
        assert conv.messages[1].metadata is not None
        assert conv.messages[1].metadata.get("seq") == 2

    def test_append_turn_sets_timestamps(self) -> None:
        """Test that append_turn sets timestamps."""
        conv = ClarifierConversation()
        conv.append_turn("hello", "hi")

        assert conv.messages[0].timestamp is not None
        assert conv.messages[1].timestamp is not None
        # Both should be close to now
        now = datetime.now(timezone.utc)
        assert (now - conv.messages[0].timestamp).total_seconds() < 1
        assert (now - conv.messages[1].timestamp).total_seconds() < 1


class TestAppendMessage:
    """Test append_message functionality."""

    def test_append_single_message(self) -> None:
        """Test appending a single message."""
        conv = ClarifierConversation()
        conv.append_message("user", "hello")

        assert len(conv.messages) == 1
        assert conv.messages[0].role == "user"
        assert conv.messages[0].content == "hello"
        assert conv.current_seq == 1

    def test_append_message_with_custom_id(self) -> None:
        """Test appending message with custom message_id."""
        conv = ClarifierConversation()
        conv.append_message("user", "hello", message_id="custom_id")

        assert conv.messages[0].message_id == "custom_id"

    def test_append_message_with_custom_timestamp(self) -> None:
        """Test appending message with custom timestamp."""
        conv = ClarifierConversation()
        custom_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        conv.append_message("user", "hello", timestamp=custom_time)

        assert conv.messages[0].timestamp == custom_time


class TestSummarizeAndTrim:
    """Test summarize and trim functionality."""

    def test_no_trim_below_threshold(self) -> None:
        """Test that no trimming occurs below threshold."""
        conv = ClarifierConversation()
        # Add messages below threshold
        for i in range(SUMMARY_THRESHOLD - 2):
            conv.append_message("user" if i % 2 == 0 else "assistant", f"msg {i}")

        assert len(conv.messages) == SUMMARY_THRESHOLD - 2
        assert conv.summary is None
        assert conv.overflow_message_count == 0

    def test_trim_at_threshold(self) -> None:
        """Test that trimming occurs at threshold."""
        conv = ClarifierConversation()
        # Add messages to reach threshold
        for i in range(SUMMARY_THRESHOLD):
            conv.append_message("user" if i % 2 == 0 else "assistant", f"msg {i}")

        # Should now be trimmed to KEEP_RECENT_COUNT
        assert len(conv.messages) == KEEP_RECENT_COUNT
        assert conv.summary is not None
        assert conv.overflow_message_count == SUMMARY_THRESHOLD - KEEP_RECENT_COUNT

    def test_keeps_most_recent_messages(self) -> None:
        """Test that trim keeps the most recent messages."""
        conv = ClarifierConversation()
        # Add messages to trigger trim
        for i in range(SUMMARY_THRESHOLD):
            conv.append_message("user" if i % 2 == 0 else "assistant", f"msg {i}")

        # Check that the last KEEP_RECENT_COUNT messages are kept
        # Messages were numbered 0 to SUMMARY_THRESHOLD-1
        # After trim, we should have messages from (SUMMARY_THRESHOLD - KEEP_RECENT_COUNT) onwards
        expected_start = SUMMARY_THRESHOLD - KEEP_RECENT_COUNT
        assert conv.messages[0].content == f"msg {expected_start}"
        assert conv.messages[-1].content == f"msg {SUMMARY_THRESHOLD - 1}"

    def test_overflow_callback_is_called(self) -> None:
        """Test that overflow callback is called with trimmed messages."""
        conv = ClarifierConversation()
        overflow_messages: list[ConversationMessage] = []

        def capture_overflow(messages: list[ConversationMessage]) -> None:
            overflow_messages.extend(messages)

        conv.set_overflow_callback(capture_overflow)

        # Add messages to trigger trim
        for i in range(SUMMARY_THRESHOLD):
            conv.append_message("user" if i % 2 == 0 else "assistant", f"msg {i}")

        # Check overflow callback received the trimmed messages
        expected_overflow_count = SUMMARY_THRESHOLD - KEEP_RECENT_COUNT
        assert len(overflow_messages) == expected_overflow_count
        assert overflow_messages[0].content == "msg 0"

    def test_summary_callback_is_called(self) -> None:
        """Test that summarize callback is called."""
        conv = ClarifierConversation()
        callback_called = {"count": 0, "messages": None, "existing": None}

        def custom_summarize(
            messages: list[ConversationMessage], existing: str | None
        ) -> str:
            callback_called["count"] += 1
            callback_called["messages"] = messages
            callback_called["existing"] = existing
            return "custom summary"

        conv.set_summarize_callback(custom_summarize)

        # Add messages to trigger trim
        for i in range(SUMMARY_THRESHOLD):
            conv.append_message("user" if i % 2 == 0 else "assistant", f"msg {i}")

        assert callback_called["count"] == 1
        assert conv.summary == "custom summary"


class TestToHistoryList:
    """Test to_history_list functionality."""

    def test_empty_conversation_returns_empty_list(self) -> None:
        """Test empty conversation returns empty list."""
        conv = ClarifierConversation()
        result = conv.to_history_list()
        assert result == []

    def test_returns_messages_as_dicts(self) -> None:
        """Test that messages are serialized to dicts."""
        conv = ClarifierConversation()
        conv.append_turn("hello", "hi")

        result = conv.to_history_list()
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "hello"
        assert result[1]["role"] == "assistant"
        assert result[1]["content"] == "hi"

    def test_includes_summary_as_system_message(self) -> None:
        """Test that summary is included as a system message."""
        conv = ClarifierConversation()
        conv.summary = "This is a summary"
        conv.append_turn("hello", "hi")

        result = conv.to_history_list()
        assert len(result) == 3
        assert result[0]["role"] == "system"
        assert "summary" in result[0]["content"].lower()
        assert "This is a summary" in result[0]["content"]
        assert result[0]["metadata"]["type"] == "summary"

    def test_includes_overflow_count_in_summary_metadata(self) -> None:
        """Test that overflow count is in summary metadata."""
        conv = ClarifierConversation()
        conv.summary = "Summary"
        conv.overflow_message_count = 25

        result = conv.to_history_list()
        assert result[0]["metadata"]["overflowCount"] == 25


class TestSerialization:
    """Test to_dict and from_dict serialization."""

    def test_to_dict_empty_conversation(self) -> None:
        """Test serializing empty conversation."""
        conv = ClarifierConversation()
        data = conv.to_dict()

        assert data["agent_name"] == "clarifier"
        assert data["messages"] == []
        assert data["current_seq"] == 0
        assert data["summary"] is None
        assert data["overflow_message_count"] == 0

    def test_to_dict_with_messages(self) -> None:
        """Test serializing conversation with messages."""
        conv = ClarifierConversation()
        conv.append_turn("hello", "hi")

        data = conv.to_dict()
        assert len(data["messages"]) == 2
        assert data["current_seq"] == 2

    def test_to_dict_with_summary(self) -> None:
        """Test serializing conversation with summary."""
        conv = ClarifierConversation()
        conv.summary = "A summary of previous messages"
        conv.overflow_message_count = 10

        data = conv.to_dict()
        assert data["summary"] == "A summary of previous messages"
        assert data["overflow_message_count"] == 10

    def test_from_dict_empty(self) -> None:
        """Test deserializing empty conversation."""
        data = {"agent_name": "clarifier", "messages": []}
        conv = ClarifierConversation.from_dict(data)

        assert conv.agent_name == "clarifier"
        assert conv.messages == []
        assert conv.current_seq == 0
        assert conv.summary is None
        assert conv.overflow_message_count == 0

    def test_from_dict_with_messages(self) -> None:
        """Test deserializing conversation with messages."""
        data = {
            "agent_name": "clarifier",
            "messages": [
                {
                    "messageId": "msg_1",
                    "role": "user",
                    "content": "hello",
                    "timestamp": "2025-01-01T12:00:00+00:00",
                },
                {
                    "messageId": "msg_2",
                    "role": "assistant",
                    "content": "hi",
                    "timestamp": "2025-01-01T12:00:01+00:00",
                },
            ],
            "current_seq": 2,
        }
        conv = ClarifierConversation.from_dict(data)

        assert len(conv.messages) == 2
        assert conv.messages[0].content == "hello"
        assert conv.messages[1].content == "hi"
        assert conv.current_seq == 2

    def test_from_dict_with_summary(self) -> None:
        """Test deserializing conversation with summary."""
        data = {
            "agent_name": "clarifier",
            "messages": [],
            "summary": "Previous conversation summary",
            "overflow_message_count": 15,
        }
        conv = ClarifierConversation.from_dict(data)

        assert conv.summary == "Previous conversation summary"
        assert conv.overflow_message_count == 15

    def test_roundtrip_serialization(self) -> None:
        """Test serialization roundtrip."""
        conv1 = ClarifierConversation()
        conv1.append_turn("hello", "hi")
        conv1.summary = "Summary text"
        conv1.overflow_message_count = 5

        data = conv1.to_dict()
        conv2 = ClarifierConversation.from_dict(data)

        assert conv2.agent_name == conv1.agent_name
        assert len(conv2.messages) == len(conv1.messages)
        assert conv2.current_seq == conv1.current_seq
        assert conv2.summary == conv1.summary
        assert conv2.overflow_message_count == conv1.overflow_message_count

    def test_from_dict_handles_malformed_messages(self) -> None:
        """Test that from_dict skips malformed messages."""
        data = {
            "agent_name": "clarifier",
            "messages": [
                {"invalid": "message"},  # Missing required fields
                {
                    "messageId": "msg_1",
                    "role": "user",
                    "content": "valid",
                    "timestamp": "2025-01-01T12:00:00+00:00",
                },
            ],
        }
        conv = ClarifierConversation.from_dict(data)

        # Should only have the valid message
        assert len(conv.messages) == 1
        assert conv.messages[0].content == "valid"


class TestFromAgentConversation:
    """Test migration from AgentConversation."""

    def test_from_agent_conversation_basic(self) -> None:
        """Test creating from AgentConversation."""
        from src.orchestrator.models.conversation import AgentConversation

        agent_conv = AgentConversation(agent_name="clarifier")
        agent_conv.append_turn("hello", "hi")

        clarifier_conv = ClarifierConversation.from_agent_conversation(agent_conv)

        assert clarifier_conv.agent_name == "clarifier"
        assert len(clarifier_conv.messages) == 2
        assert clarifier_conv.current_seq == agent_conv.current_seq

    def test_from_agent_conversation_with_summary(self) -> None:
        """Test creating from AgentConversation with existing summary."""
        from src.orchestrator.models.conversation import AgentConversation

        agent_conv = AgentConversation(agent_name="clarifier")
        agent_conv.append_turn("hello", "hi")

        clarifier_conv = ClarifierConversation.from_agent_conversation(
            agent_conv,
            summary="Existing summary",
            overflow_message_count=10,
        )

        assert clarifier_conv.summary == "Existing summary"
        assert clarifier_conv.overflow_message_count == 10


class TestClear:
    """Test clear functionality."""

    def test_clear_resets_all_fields(self) -> None:
        """Test that clear resets all fields."""
        conv = ClarifierConversation()
        conv.append_turn("hello", "hi")
        conv.summary = "Summary"
        conv.overflow_message_count = 10

        conv.clear()

        assert conv.messages == []
        assert conv.summary is None
        assert conv.overflow_message_count == 0
        assert conv.current_seq == 0


class TestGetContextForAgent:
    """Test get_context_for_agent functionality."""

    def test_returns_context_dict(self) -> None:
        """Test that context dict is returned."""
        conv = ClarifierConversation()
        conv.append_turn("hello", "hi")
        conv.summary = "Summary"
        conv.overflow_message_count = 5

        context = conv.get_context_for_agent()

        assert "summary" in context
        assert "recent_messages" in context
        assert "total_messages" in context
        assert "overflow_count" in context
        assert "current_seq" in context

        assert context["summary"] == "Summary"
        assert context["overflow_count"] == 5
        assert context["total_messages"] == 7  # 2 messages + 5 overflow


class TestSummarizeMessagesFunction:
    """Test the standalone summarize_messages function."""

    def test_summarize_empty_list(self) -> None:
        """Test summarizing empty list returns empty string or short summary."""
        result = summarize_messages([])
        # Result should be empty or minimal
        assert len(result) < 100

    def test_summarize_with_messages(self) -> None:
        """Test summarizing list of messages."""
        messages = [
            ConversationMessage(
                message_id="msg_1",
                role="user",
                content="Plan a trip to Paris",
                timestamp=datetime.now(timezone.utc),
            ),
            ConversationMessage(
                message_id="msg_2",
                role="assistant",
                content="When would you like to travel?",
                timestamp=datetime.now(timezone.utc),
            ),
        ]
        result = summarize_messages(messages)

        assert len(result) > 0
        # Should contain some reference to the content
        assert "Paris" in result or "travel" in result.lower()

    def test_summarize_with_existing_summary(self) -> None:
        """Test summarizing with existing summary."""
        messages = [
            ConversationMessage(
                message_id="msg_1",
                role="user",
                content="March dates",
                timestamp=datetime.now(timezone.utc),
            ),
        ]
        result = summarize_messages(messages, existing_summary="Trip to Paris")

        assert "Previous" in result or "Trip to Paris" in result

    def test_summarize_truncates_long_content(self) -> None:
        """Test that long messages are truncated in summary."""
        messages = [
            ConversationMessage(
                message_id="msg_1",
                role="user",
                content="x" * 500,  # Very long message
                timestamp=datetime.now(timezone.utc),
            ),
        ]
        result = summarize_messages(messages)

        # Summary should be capped at 800 chars per the implementation
        assert len(result) <= 800


class TestConstants:
    """Test that constants are correctly defined."""

    def test_max_messages_constant(self) -> None:
        """Test MAX_MESSAGES_IN_STATE is defined."""
        assert MAX_MESSAGES_IN_STATE == 50

    def test_summary_threshold_constant(self) -> None:
        """Test SUMMARY_THRESHOLD is defined."""
        assert SUMMARY_THRESHOLD == 40

    def test_keep_recent_count_constant(self) -> None:
        """Test KEEP_RECENT_COUNT is defined."""
        assert KEEP_RECENT_COUNT == 20

    def test_threshold_less_than_max(self) -> None:
        """Test that threshold is less than max for proper trimming."""
        assert SUMMARY_THRESHOLD < MAX_MESSAGES_IN_STATE

    def test_keep_recent_less_than_threshold(self) -> None:
        """Test that keep count is less than threshold."""
        assert KEEP_RECENT_COUNT < SUMMARY_THRESHOLD
