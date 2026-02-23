"""Unit tests for ConversationMessage and AgentConversation dataclasses.

Per design doc Agent Communication section:
- ConversationMessage is the building block for history injection
- AgentConversation tracks full conversation with a downstream agent
- Represents a single turn in the conversation with rich metadata
- to_dict() produces camelCase keys per A2A spec
- from_dict() correctly parses camelCase input
- Round-trip serialization preserves all data
"""

from datetime import datetime, timezone

import pytest

from src.orchestrator.models.conversation import AgentConversation, ConversationMessage


class TestConversationMessageToDict:
    """Tests for ConversationMessage.to_dict() serialization."""

    def test_conversation_message_to_dict_user_message(self) -> None:
        """Test to_dict() for a user message."""
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        msg = ConversationMessage(
            message_id="msg_abc123",
            role="user",
            content="Plan a trip to Tokyo",
            timestamp=timestamp,
        )

        result = msg.to_dict()

        assert result["messageId"] == "msg_abc123"
        assert result["role"] == "user"
        assert result["content"] == "Plan a trip to Tokyo"
        assert result["timestamp"] == "2024-01-15T10:30:00+00:00"
        assert result["metadata"] is None

    def test_conversation_message_to_dict_assistant_message(self) -> None:
        """Test to_dict() for an assistant message."""
        timestamp = datetime(2024, 1, 15, 10, 31, 0, tzinfo=timezone.utc)
        msg = ConversationMessage(
            message_id="msg_xyz789",
            role="assistant",
            content="What dates are you traveling?",
            timestamp=timestamp,
        )

        result = msg.to_dict()

        assert result["messageId"] == "msg_xyz789"
        assert result["role"] == "assistant"
        assert result["content"] == "What dates are you traveling?"
        assert result["timestamp"] == "2024-01-15T10:31:00+00:00"

    def test_conversation_message_to_dict_with_metadata(self) -> None:
        """Test to_dict() preserves metadata."""
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        metadata = {"seq": 3, "agent": "clarifier"}
        msg = ConversationMessage(
            message_id="msg_meta001",
            role="user",
            content="5 days",
            timestamp=timestamp,
            metadata=metadata,
        )

        result = msg.to_dict()

        assert result["metadata"] == {"seq": 3, "agent": "clarifier"}

    def test_conversation_message_to_dict_camel_case_keys(self) -> None:
        """Test to_dict() produces camelCase keys per A2A spec."""
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        msg = ConversationMessage(
            message_id="msg_test",
            role="user",
            content="Test",
            timestamp=timestamp,
        )

        result = msg.to_dict()

        # Must use camelCase for A2A compatibility
        assert "messageId" in result
        assert "message_id" not in result
        # Other keys are single words so same in both cases
        assert "role" in result
        assert "content" in result
        assert "timestamp" in result
        assert "metadata" in result


class TestConversationMessageFromDict:
    """Tests for ConversationMessage.from_dict() deserialization."""

    def test_conversation_message_from_dict_user_message(self) -> None:
        """Test from_dict() for a user message."""
        data = {
            "messageId": "msg_abc123",
            "role": "user",
            "content": "Plan a trip to Tokyo",
            "timestamp": "2024-01-15T10:30:00+00:00",
        }

        msg = ConversationMessage.from_dict(data)

        assert msg.message_id == "msg_abc123"
        assert msg.role == "user"
        assert msg.content == "Plan a trip to Tokyo"
        assert msg.timestamp == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert msg.metadata is None

    def test_conversation_message_from_dict_assistant_message(self) -> None:
        """Test from_dict() for an assistant message."""
        data = {
            "messageId": "msg_xyz789",
            "role": "assistant",
            "content": "What dates are you traveling?",
            "timestamp": "2024-01-15T10:31:00+00:00",
        }

        msg = ConversationMessage.from_dict(data)

        assert msg.message_id == "msg_xyz789"
        assert msg.role == "assistant"
        assert msg.content == "What dates are you traveling?"

    def test_conversation_message_from_dict_with_metadata(self) -> None:
        """Test from_dict() parses metadata correctly."""
        data = {
            "messageId": "msg_meta001",
            "role": "user",
            "content": "5 days",
            "timestamp": "2024-01-15T10:30:00+00:00",
            "metadata": {"seq": 3, "agent": "clarifier"},
        }

        msg = ConversationMessage.from_dict(data)

        assert msg.metadata == {"seq": 3, "agent": "clarifier"}

    def test_conversation_message_from_dict_without_metadata(self) -> None:
        """Test from_dict() handles missing metadata (optional field)."""
        data = {
            "messageId": "msg_test",
            "role": "user",
            "content": "Test",
            "timestamp": "2024-01-15T10:30:00+00:00",
        }

        msg = ConversationMessage.from_dict(data)

        assert msg.metadata is None

    def test_conversation_message_from_dict_naive_timestamp(self) -> None:
        """Test from_dict() handles naive timestamps (no timezone)."""
        data = {
            "messageId": "msg_naive",
            "role": "user",
            "content": "Test",
            "timestamp": "2024-01-15T10:30:00",  # No timezone
        }

        msg = ConversationMessage.from_dict(data)

        # Should parse as naive datetime
        assert msg.timestamp == datetime(2024, 1, 15, 10, 30, 0)
        assert msg.timestamp.tzinfo is None


class TestConversationMessageRoundTrip:
    """Tests for round-trip serialization (to_dict -> from_dict)."""

    def test_conversation_message_round_trip_basic(self) -> None:
        """Test round-trip preserves all fields for basic message."""
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        original = ConversationMessage(
            message_id="msg_roundtrip",
            role="user",
            content="Plan a trip to Tokyo",
            timestamp=timestamp,
        )

        serialized = original.to_dict()
        restored = ConversationMessage.from_dict(serialized)

        assert restored.message_id == original.message_id
        assert restored.role == original.role
        assert restored.content == original.content
        assert restored.timestamp == original.timestamp
        assert restored.metadata == original.metadata

    def test_conversation_message_round_trip_with_metadata(self) -> None:
        """Test round-trip preserves metadata."""
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        metadata = {"seq": 5, "agent": "clarifier", "nested": {"key": "value"}}
        original = ConversationMessage(
            message_id="msg_meta_roundtrip",
            role="assistant",
            content="What's your budget?",
            timestamp=timestamp,
            metadata=metadata,
        )

        serialized = original.to_dict()
        restored = ConversationMessage.from_dict(serialized)

        assert restored.metadata == original.metadata
        assert restored.metadata["nested"]["key"] == "value"

    def test_conversation_message_round_trip_multiple_messages(self) -> None:
        """Test round-trip for a sequence of messages (conversation)."""
        timestamp1 = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        timestamp2 = datetime(2024, 1, 15, 10, 31, 0, tzinfo=timezone.utc)

        messages = [
            ConversationMessage(
                message_id="msg_001",
                role="user",
                content="Plan a trip to Tokyo",
                timestamp=timestamp1,
                metadata={"seq": 1},
            ),
            ConversationMessage(
                message_id="msg_002",
                role="assistant",
                content="What dates?",
                timestamp=timestamp2,
                metadata={"seq": 2},
            ),
        ]

        # Serialize and deserialize all
        serialized = [msg.to_dict() for msg in messages]
        restored = [ConversationMessage.from_dict(d) for d in serialized]

        for original, restored_msg in zip(messages, restored):
            assert restored_msg.message_id == original.message_id
            assert restored_msg.role == original.role
            assert restored_msg.content == original.content
            assert restored_msg.timestamp == original.timestamp
            assert restored_msg.metadata == original.metadata

    def test_conversation_message_round_trip_empty_content(self) -> None:
        """Test round-trip with empty content (edge case)."""
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        original = ConversationMessage(
            message_id="msg_empty",
            role="user",
            content="",
            timestamp=timestamp,
        )

        serialized = original.to_dict()
        restored = ConversationMessage.from_dict(serialized)

        assert restored.content == ""

    def test_conversation_message_round_trip_unicode_content(self) -> None:
        """Test round-trip preserves unicode characters."""
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        original = ConversationMessage(
            message_id="msg_unicode",
            role="user",
            content="Plan a trip to Tokyo",
            timestamp=timestamp,
        )

        serialized = original.to_dict()
        restored = ConversationMessage.from_dict(serialized)

        assert restored.content == "Plan a trip to Tokyo"


class TestAgentConversationAppendTurn:
    """Tests for AgentConversation.append_turn() method."""

    def test_agent_conversation_append_turn_creates_two_messages(self) -> None:
        """Test append_turn() creates both user and assistant messages."""
        conversation = AgentConversation(agent_name="clarifier")

        conversation.append_turn(
            user_content="Plan a trip to Tokyo",
            assistant_content="What dates are you traveling?",
        )

        assert len(conversation.messages) == 2
        assert conversation.messages[0].role == "user"
        assert conversation.messages[0].content == "Plan a trip to Tokyo"
        assert conversation.messages[1].role == "assistant"
        assert conversation.messages[1].content == "What dates are you traveling?"

    def test_agent_conversation_append_turn_increments_seq(self) -> None:
        """Test append_turn() increments sequence numbers correctly."""
        conversation = AgentConversation(agent_name="clarifier")
        assert conversation.current_seq == 0

        conversation.append_turn(
            user_content="Plan a trip",
            assistant_content="Where to?",
        )

        # After one turn, seq should be 2 (one for user, one for assistant)
        assert conversation.current_seq == 2
        assert conversation.messages[0].metadata["seq"] == 1
        assert conversation.messages[1].metadata["seq"] == 2

    def test_agent_conversation_append_turn_multiple_turns(self) -> None:
        """Test append_turn() with multiple turns."""
        conversation = AgentConversation(agent_name="clarifier")

        conversation.append_turn(
            user_content="Plan a trip to Tokyo",
            assistant_content="What dates?",
        )
        conversation.append_turn(
            user_content="March 15-20",
            assistant_content="What's your budget?",
        )

        assert len(conversation.messages) == 4
        assert conversation.current_seq == 4
        assert conversation.messages[2].content == "March 15-20"
        assert conversation.messages[3].content == "What's your budget?"

    def test_agent_conversation_append_turn_generates_message_ids(self) -> None:
        """Test append_turn() generates unique message IDs."""
        conversation = AgentConversation(agent_name="clarifier")

        conversation.append_turn(
            user_content="Hello",
            assistant_content="Hi there!",
        )

        # Both messages should have unique IDs
        assert conversation.messages[0].message_id.startswith("msg_")
        assert conversation.messages[1].message_id.startswith("msg_")
        assert conversation.messages[0].message_id != conversation.messages[1].message_id

    def test_agent_conversation_append_turn_sets_timestamps(self) -> None:
        """Test append_turn() sets timestamps on messages."""
        conversation = AgentConversation(agent_name="clarifier")

        conversation.append_turn(
            user_content="Hello",
            assistant_content="Hi!",
        )

        # Both messages should have timestamps
        assert conversation.messages[0].timestamp is not None
        assert conversation.messages[1].timestamp is not None
        # Timestamps should be timezone-aware (UTC)
        assert conversation.messages[0].timestamp.tzinfo is not None


class TestAgentConversationToHistoryList:
    """Tests for AgentConversation.to_history_list() method."""

    def test_agent_conversation_to_history_list_empty(self) -> None:
        """Test to_history_list() returns empty list for new conversation."""
        conversation = AgentConversation(agent_name="clarifier")

        result = conversation.to_history_list()

        assert result == []

    def test_agent_conversation_to_history_list_single_turn(self) -> None:
        """Test to_history_list() serializes single turn correctly."""
        conversation = AgentConversation(agent_name="clarifier")
        conversation.append_turn(
            user_content="Plan a trip",
            assistant_content="Where to?",
        )

        result = conversation.to_history_list()

        assert len(result) == 2
        # Should use camelCase keys per A2A spec
        assert "messageId" in result[0]
        assert "role" in result[0]
        assert "content" in result[0]
        assert "timestamp" in result[0]
        assert "metadata" in result[0]

    def test_agent_conversation_to_history_list_multiple_turns(self) -> None:
        """Test to_history_list() serializes multiple turns correctly."""
        conversation = AgentConversation(agent_name="clarifier")
        conversation.append_turn("Hello", "Hi!")
        conversation.append_turn("How are you?", "I'm good!")

        result = conversation.to_history_list()

        assert len(result) == 4
        assert result[0]["content"] == "Hello"
        assert result[1]["content"] == "Hi!"
        assert result[2]["content"] == "How are you?"
        assert result[3]["content"] == "I'm good!"

    def test_agent_conversation_to_history_list_preserves_metadata(self) -> None:
        """Test to_history_list() preserves seq metadata."""
        conversation = AgentConversation(agent_name="clarifier")
        conversation.append_turn("Hello", "Hi!")

        result = conversation.to_history_list()

        assert result[0]["metadata"]["seq"] == 1
        assert result[1]["metadata"]["seq"] == 2


class TestAgentConversationMessageCount:
    """Tests for AgentConversation.message_count property."""

    def test_agent_conversation_message_count_empty(self) -> None:
        """Test message_count is 0 for new conversation."""
        conversation = AgentConversation(agent_name="clarifier")

        assert conversation.message_count == 0

    def test_agent_conversation_message_count_after_turn(self) -> None:
        """Test message_count increases after append_turn()."""
        conversation = AgentConversation(agent_name="clarifier")
        conversation.append_turn("Hello", "Hi!")

        assert conversation.message_count == 2

    def test_agent_conversation_message_count_multiple_turns(self) -> None:
        """Test message_count tracks multiple turns correctly."""
        conversation = AgentConversation(agent_name="clarifier")
        conversation.append_turn("Hello", "Hi!")
        conversation.append_turn("How are you?", "Good!")
        conversation.append_turn("What's the weather?", "Sunny!")

        assert conversation.message_count == 6


class TestAgentConversationNextSeq:
    """Tests for AgentConversation.next_seq property."""

    def test_agent_conversation_next_seq_initial(self) -> None:
        """Test next_seq is 1 for new conversation."""
        conversation = AgentConversation(agent_name="clarifier")

        assert conversation.next_seq == 1

    def test_agent_conversation_next_seq_after_turn(self) -> None:
        """Test next_seq increases after append_turn()."""
        conversation = AgentConversation(agent_name="clarifier")
        conversation.append_turn("Hello", "Hi!")

        # After a turn (2 messages), current_seq is 2, so next_seq is 3
        assert conversation.next_seq == 3


class TestAgentConversationInit:
    """Tests for AgentConversation initialization."""

    def test_agent_conversation_init_with_name(self) -> None:
        """Test AgentConversation initializes with agent name."""
        conversation = AgentConversation(agent_name="clarifier")

        assert conversation.agent_name == "clarifier"
        assert conversation.messages == []
        assert conversation.current_seq == 0

    def test_agent_conversation_init_with_messages(self) -> None:
        """Test AgentConversation can be initialized with messages."""
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        messages = [
            ConversationMessage(
                message_id="msg_001",
                role="user",
                content="Hello",
                timestamp=timestamp,
            )
        ]

        conversation = AgentConversation(
            agent_name="clarifier",
            messages=messages,
            current_seq=1,
        )

        assert conversation.agent_name == "clarifier"
        assert len(conversation.messages) == 1
        assert conversation.current_seq == 1
