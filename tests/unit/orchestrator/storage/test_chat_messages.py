"""Unit tests for chat_messages storage."""

import pytest
from datetime import datetime, timezone

from src.orchestrator.storage.chat_messages import (
    CHAT_MESSAGES_TTL,
    ChatMessage,
    ChatMessageStoreProtocol,
    InMemoryChatMessageStore,
)


class TestChatMessage:
    """Tests for the ChatMessage dataclass."""

    def test_chat_message_creation(self):
        """Test creating a ChatMessage with all fields."""
        timestamp = datetime(2026, 1, 21, 9, 0, 0, tzinfo=timezone.utc)
        msg = ChatMessage(
            session_id="sess_abc123",
            message_id="msg_001",
            role="user",
            content="Plan a trip to Tokyo",
            timestamp=timestamp,
        )

        assert msg.session_id == "sess_abc123"
        assert msg.message_id == "msg_001"
        assert msg.role == "user"
        assert msg.content == "Plan a trip to Tokyo"
        assert msg.timestamp == timestamp

    def test_chat_message_default_timestamp(self):
        """Test that ChatMessage has a default timestamp."""
        msg = ChatMessage(
            session_id="sess_abc123",
            message_id="msg_001",
            role="user",
            content="Hello",
        )

        assert msg.timestamp is not None
        assert isinstance(msg.timestamp, datetime)
        # Should be recent (within last few seconds)
        now = datetime.now(timezone.utc)
        diff = abs((now - msg.timestamp).total_seconds())
        assert diff < 5

    def test_chat_message_to_dict(self):
        """Test serialization to dictionary."""
        timestamp = datetime(2026, 1, 21, 9, 0, 0, tzinfo=timezone.utc)
        msg = ChatMessage(
            session_id="sess_abc123",
            message_id="msg_001",
            role="user",
            content="Plan a trip to Tokyo",
            timestamp=timestamp,
        )

        result = msg.to_dict()

        # Document ID combines message_id and session_id
        assert result["id"] == "msg_001_sess_abc123"
        assert result["session_id"] == "sess_abc123"
        assert result["message_id"] == "msg_001"
        assert result["role"] == "user"
        assert result["content"] == "Plan a trip to Tokyo"
        assert result["timestamp"] == "2026-01-21T09:00:00+00:00"
        assert result["ttl"] == CHAT_MESSAGES_TTL

    def test_chat_message_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "id": "msg_001_sess_abc123",
            "session_id": "sess_abc123",
            "message_id": "msg_001",
            "role": "assistant",
            "content": "I can help you plan that trip!",
            "timestamp": "2026-01-21T09:01:00+00:00",
        }

        msg = ChatMessage.from_dict(data)

        assert msg.session_id == "sess_abc123"
        assert msg.message_id == "msg_001"
        assert msg.role == "assistant"
        assert msg.content == "I can help you plan that trip!"
        assert msg.timestamp == datetime(2026, 1, 21, 9, 1, 0, tzinfo=timezone.utc)

    def test_chat_message_from_dict_with_defaults(self):
        """Test deserialization with missing fields uses defaults."""
        data = {"session_id": "sess_abc123"}

        msg = ChatMessage.from_dict(data)

        assert msg.session_id == "sess_abc123"
        assert msg.message_id == ""
        assert msg.role == "user"  # Default
        assert msg.content == ""
        assert msg.timestamp is not None  # Default to now

    def test_chat_message_from_dict_empty(self):
        """Test deserialization from empty dictionary."""
        msg = ChatMessage.from_dict({})

        assert msg.session_id == ""
        assert msg.message_id == ""
        assert msg.role == "user"
        assert msg.content == ""


class TestChatMessagesTTL:
    """Tests for TTL constant."""

    def test_ttl_is_7_days(self):
        """Test that TTL is 7 days in seconds."""
        # 7 days * 24 hours * 60 minutes * 60 seconds
        expected_ttl = 7 * 24 * 60 * 60
        assert CHAT_MESSAGES_TTL == expected_ttl
        assert CHAT_MESSAGES_TTL == 604800


class TestInMemoryChatMessageStore:
    """Tests for InMemoryChatMessageStore."""

    @pytest.fixture
    def store(self):
        """Create a fresh in-memory store for each test."""
        return InMemoryChatMessageStore()

    @pytest.mark.asyncio
    async def test_get_messages_empty_session(self, store):
        """Test retrieving messages for a session that has no messages."""
        messages = await store.get_messages("sess_nonexistent")
        assert messages == []

    @pytest.mark.asyncio
    async def test_append_message(self, store):
        """Test adding a new message."""
        msg = await store.append_message(
            session_id="sess_abc123",
            message_id="msg_001",
            role="user",
            content="Hello, world!",
        )

        assert msg.session_id == "sess_abc123"
        assert msg.message_id == "msg_001"
        assert msg.role == "user"
        assert msg.content == "Hello, world!"
        assert msg.timestamp is not None

    @pytest.mark.asyncio
    async def test_append_and_get_messages(self, store):
        """Test adding messages and retrieving them."""
        await store.append_message(
            session_id="sess_abc123",
            message_id="msg_001",
            role="user",
            content="Plan a trip to Tokyo",
        )
        await store.append_message(
            session_id="sess_abc123",
            message_id="msg_002",
            role="assistant",
            content="I'd be happy to help!",
        )

        messages = await store.get_messages("sess_abc123")

        assert len(messages) == 2
        assert messages[0].message_id == "msg_001"
        assert messages[0].role == "user"
        assert messages[1].message_id == "msg_002"
        assert messages[1].role == "assistant"

    @pytest.mark.asyncio
    async def test_get_messages_ordered_by_timestamp(self, store):
        """Test that messages are returned ordered by timestamp."""
        # Add messages (they should be ordered by timestamp)
        await store.append_message("sess_abc", "msg_001", "user", "First")
        await store.append_message("sess_abc", "msg_002", "assistant", "Second")
        await store.append_message("sess_abc", "msg_003", "user", "Third")

        messages = await store.get_messages("sess_abc")

        assert len(messages) == 3
        # Messages should be in order
        assert messages[0].content == "First"
        assert messages[1].content == "Second"
        assert messages[2].content == "Third"

    @pytest.mark.asyncio
    async def test_get_messages_with_limit(self, store):
        """Test retrieving messages with a limit."""
        for i in range(10):
            await store.append_message(
                "sess_abc", f"msg_{i:03d}", "user", f"Message {i}"
            )

        messages = await store.get_messages("sess_abc", limit=3)

        assert len(messages) == 3
        assert messages[0].content == "Message 0"
        assert messages[2].content == "Message 2"

    @pytest.mark.asyncio
    async def test_get_messages_with_offset(self, store):
        """Test retrieving messages with an offset."""
        for i in range(10):
            await store.append_message(
                "sess_abc", f"msg_{i:03d}", "user", f"Message {i}"
            )

        messages = await store.get_messages("sess_abc", offset=5)

        assert len(messages) == 5
        assert messages[0].content == "Message 5"
        assert messages[4].content == "Message 9"

    @pytest.mark.asyncio
    async def test_get_messages_with_limit_and_offset(self, store):
        """Test retrieving messages with both limit and offset."""
        for i in range(10):
            await store.append_message(
                "sess_abc", f"msg_{i:03d}", "user", f"Message {i}"
            )

        messages = await store.get_messages("sess_abc", limit=3, offset=2)

        assert len(messages) == 3
        assert messages[0].content == "Message 2"
        assert messages[1].content == "Message 3"
        assert messages[2].content == "Message 4"

    @pytest.mark.asyncio
    async def test_purge_messages(self, store):
        """Test deleting all messages for a session."""
        await store.append_message("sess_abc", "msg_001", "user", "Hello")
        await store.append_message("sess_abc", "msg_002", "assistant", "Hi")
        await store.append_message("sess_def", "msg_003", "user", "Different session")

        # Purge sess_abc
        count = await store.purge_messages("sess_abc")

        assert count == 2
        messages = await store.get_messages("sess_abc")
        assert messages == []

        # sess_def should be unaffected
        messages_def = await store.get_messages("sess_def")
        assert len(messages_def) == 1

    @pytest.mark.asyncio
    async def test_purge_messages_nonexistent_session(self, store):
        """Test purging messages for a non-existent session."""
        count = await store.purge_messages("sess_nonexistent")
        assert count == 0

    @pytest.mark.asyncio
    async def test_multiple_sessions(self, store):
        """Test that different sessions have independent message stores."""
        await store.append_message("sess_1", "msg_001", "user", "Session 1 message")
        await store.append_message("sess_2", "msg_001", "user", "Session 2 message")

        messages_1 = await store.get_messages("sess_1")
        messages_2 = await store.get_messages("sess_2")

        assert len(messages_1) == 1
        assert len(messages_2) == 1
        assert messages_1[0].content == "Session 1 message"
        assert messages_2[0].content == "Session 2 message"

    def test_clear(self, store):
        """Test clearing all messages from the store."""
        # Note: Using sync test since clear() is not async
        import asyncio

        async def setup():
            await store.append_message("sess_1", "msg_001", "user", "Message 1")
            await store.append_message("sess_2", "msg_002", "user", "Message 2")

        asyncio.get_event_loop().run_until_complete(setup())

        store.clear()

        async def verify():
            assert await store.get_messages("sess_1") == []
            assert await store.get_messages("sess_2") == []

        asyncio.get_event_loop().run_until_complete(verify())

    def test_get_message_count(self, store):
        """Test the helper method to get message count."""
        import asyncio

        async def setup():
            await store.append_message("sess_abc", "msg_001", "user", "Hello")
            await store.append_message("sess_abc", "msg_002", "assistant", "Hi")

        asyncio.get_event_loop().run_until_complete(setup())

        assert store.get_message_count("sess_abc") == 2
        assert store.get_message_count("sess_nonexistent") == 0


class TestChatMessageStoreProtocol:
    """Tests for the ChatMessageStoreProtocol."""

    def test_inmemory_implements_protocol(self):
        """Test that InMemoryChatMessageStore implements the protocol."""
        store = InMemoryChatMessageStore()
        assert isinstance(store, ChatMessageStoreProtocol)

    def test_protocol_methods_exist(self):
        """Test that the protocol has the expected method signatures."""
        # This is a compile-time check that the protocol is properly defined
        assert hasattr(ChatMessageStoreProtocol, "get_messages")
        assert hasattr(ChatMessageStoreProtocol, "append_message")
        assert hasattr(ChatMessageStoreProtocol, "purge_messages")


class TestChatMessageRoles:
    """Tests for message role handling."""

    @pytest.fixture
    def store(self):
        return InMemoryChatMessageStore()

    @pytest.mark.asyncio
    async def test_user_role(self, store):
        """Test creating a user message."""
        msg = await store.append_message("sess_abc", "msg_001", "user", "Hello")
        assert msg.role == "user"

    @pytest.mark.asyncio
    async def test_assistant_role(self, store):
        """Test creating an assistant message."""
        msg = await store.append_message("sess_abc", "msg_001", "assistant", "Hi there")
        assert msg.role == "assistant"

    @pytest.mark.asyncio
    async def test_conversation_alternating_roles(self, store):
        """Test a conversation with alternating user and assistant messages."""
        await store.append_message("sess_abc", "msg_001", "user", "Hello")
        await store.append_message("sess_abc", "msg_002", "assistant", "Hi! How can I help?")
        await store.append_message("sess_abc", "msg_003", "user", "Plan a trip")
        await store.append_message("sess_abc", "msg_004", "assistant", "Sure, where to?")

        messages = await store.get_messages("sess_abc")

        assert len(messages) == 4
        assert messages[0].role == "user"
        assert messages[1].role == "assistant"
        assert messages[2].role == "user"
        assert messages[3].role == "assistant"
