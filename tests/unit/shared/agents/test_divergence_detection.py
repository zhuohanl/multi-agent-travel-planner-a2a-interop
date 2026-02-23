"""
Unit tests for sequence-based divergence detection in BaseAgentFrameworkAgent.

Tests ORCH-009: Implement sequence-based divergence detection logic.

Per design doc (Agent Communication section):
- Compare history_seq (from client) with last_seen_seq (agent's tracked value)
- On mismatch, detect divergence and call _rebuild_thread_from_history()
- Client (orchestrator) history is authoritative
- Echo back last_seen_seq in response metadata for client tracking
"""

import logging
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Any

from src.shared.agents.base_agent import BaseAgentFrameworkAgent


class MockChatAgent:
    """Mock ChatAgent for testing without LLM calls."""

    def __init__(self):
        self.run_response = MagicMock()
        self.run_response.text = '{"is_task_complete": true, "require_user_input": false, "content": "Done"}'
        self.stream_chunks = [MagicMock(text="chunk1"), MagicMock(text="chunk2")]
        self._threads_created: list[str] = []

    def get_new_thread(self, thread_id: str) -> MagicMock:
        thread = MagicMock()
        thread.thread_id = thread_id
        thread.message_store = None
        self._threads_created.append(thread_id)
        return thread

    async def run(self, messages: str, thread: Any) -> MagicMock:
        return self.run_response

    async def run_stream(self, messages: str, thread: Any):
        for chunk in self.stream_chunks:
            yield chunk


class TestableBaseAgent(BaseAgentFrameworkAgent):
    """Testable subclass that provides mock implementations."""

    def __init__(self):
        # Skip the parent __init__ to avoid needing real chat services
        self.agent = MockChatAgent()
        self.session_threads: dict[str, Any] = {}
        self._session_last_seen_seq: dict[str, int] = {}
        self._current_history: list[dict] | None = None
        self._current_history_seq: int | None = None

    def get_agent_name(self) -> str:
        return "TestAgent"

    def get_prompt_name(self) -> str:
        return "test"

    def parse_response(self, message: Any) -> dict[str, Any]:
        return {
            "is_task_complete": True,
            "require_user_input": False,
            "content": message,
        }


class TestNoDivergenceWhenSeqMatch:
    """Tests that no divergence is detected when sequences match."""

    @pytest.mark.asyncio
    async def test_no_divergence_when_seq_match(self):
        """Test that divergence is not detected when history_seq matches last_seen_seq."""
        agent = TestableBaseAgent()
        session_id = "test_session"

        # First request: establishes last_seen_seq=3
        await agent._ensure_thread_exists(session_id, history_seq=3)
        assert agent._session_last_seen_seq.get(session_id) == 3

        # Second request with same seq=3: should NOT trigger divergence
        with patch.object(agent, '_rebuild_thread_from_history', new_callable=AsyncMock) as mock_rebuild:
            await agent._ensure_thread_exists(
                session_id,
                history=[{"role": "user", "content": "Hello"}],
                history_seq=3,
            )
            mock_rebuild.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_divergence_when_no_prior_seq(self):
        """Test that no divergence is detected for new sessions with no prior seq."""
        agent = TestableBaseAgent()
        session_id = "new_session"

        # New session has no prior last_seen_seq, so no divergence
        with patch.object(agent, '_rebuild_thread_from_history', new_callable=AsyncMock) as mock_rebuild:
            await agent._ensure_thread_exists(
                session_id,
                history=[{"role": "user", "content": "Hello"}],
                history_seq=5,
            )
            mock_rebuild.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_divergence_when_history_seq_none(self):
        """Test that no divergence is detected when history_seq is None."""
        agent = TestableBaseAgent()
        session_id = "test_session"

        # Establish a session with known seq
        await agent._ensure_thread_exists(session_id, history_seq=3)

        # Call without history_seq: should NOT trigger divergence
        with patch.object(agent, '_rebuild_thread_from_history', new_callable=AsyncMock) as mock_rebuild:
            await agent._ensure_thread_exists(
                session_id,
                history=[{"role": "user", "content": "Hello"}],
                history_seq=None,
            )
            mock_rebuild.assert_not_called()


class TestDivergenceDetectedWhenSeqMismatch:
    """Tests that divergence is detected when sequences don't match."""

    @pytest.mark.asyncio
    async def test_divergence_detected_when_seq_mismatch(self):
        """Test that divergence is detected when history_seq differs from last_seen_seq."""
        agent = TestableBaseAgent()
        session_id = "test_session"

        # First request: establishes last_seen_seq=5
        await agent._ensure_thread_exists(session_id, history_seq=5)
        assert agent._session_last_seen_seq.get(session_id) == 5

        # Second request with seq=3: divergence! Client has fewer messages
        diverged = agent._check_divergence(session_id, history_seq=3)
        assert diverged is True

    @pytest.mark.asyncio
    async def test_divergence_detected_when_client_ahead(self):
        """Test divergence when client is ahead (history_seq > last_seen_seq)."""
        agent = TestableBaseAgent()
        session_id = "test_session"

        # Establish last_seen_seq=3
        await agent._ensure_thread_exists(session_id, history_seq=3)

        # Client sends seq=7: divergence! Client has more messages
        diverged = agent._check_divergence(session_id, history_seq=7)
        assert diverged is True

    @pytest.mark.asyncio
    async def test_divergence_detected_when_client_behind(self):
        """Test divergence when client is behind (history_seq < last_seen_seq)."""
        agent = TestableBaseAgent()
        session_id = "test_session"

        # Establish last_seen_seq=10
        await agent._ensure_thread_exists(session_id, history_seq=10)

        # Client sends seq=5: divergence! Client has fewer messages (maybe state was rolled back)
        diverged = agent._check_divergence(session_id, history_seq=5)
        assert diverged is True


class TestDivergenceTriggersRebuild:
    """Tests that divergence detection triggers thread rebuild."""

    @pytest.mark.asyncio
    async def test_divergence_triggers_rebuild(self):
        """Test that _rebuild_thread_from_history is called on divergence."""
        agent = TestableBaseAgent()
        session_id = "test_session"

        # Establish session with seq=5
        await agent._ensure_thread_exists(session_id, history_seq=5)

        # Create history for rebuild
        history = [
            {"role": "user", "content": "Plan a trip"},
            {"role": "assistant", "content": "Where to?"},
            {"role": "user", "content": "Tokyo"},
        ]

        # Request with seq=3: divergence should trigger rebuild
        with patch.object(agent, '_rebuild_thread_from_history', new_callable=AsyncMock) as mock_rebuild:
            await agent._ensure_thread_exists(
                session_id,
                history=history,
                history_seq=3,
            )
            mock_rebuild.assert_called_once_with(session_id, history)

    @pytest.mark.asyncio
    async def test_rebuild_creates_new_thread(self):
        """Test that rebuild invalidates old thread and creates new one."""
        agent = TestableBaseAgent()
        session_id = "test_session"

        # Establish session
        await agent._ensure_thread_exists(session_id, history_seq=5)
        old_thread = agent.session_threads[session_id]

        # Trigger divergence and rebuild
        history = [{"role": "user", "content": "Hello"}]
        await agent._ensure_thread_exists(
            session_id,
            history=history,
            history_seq=3,  # Different from 5 -> divergence
        )

        # Thread should be replaced
        new_thread = agent.session_threads[session_id]
        assert new_thread is not old_thread

    @pytest.mark.asyncio
    async def test_last_seen_seq_updated_after_rebuild(self):
        """Test that last_seen_seq is updated to client's seq after rebuild."""
        agent = TestableBaseAgent()
        session_id = "test_session"

        # Establish session with seq=10
        await agent._ensure_thread_exists(session_id, history_seq=10)
        assert agent._session_last_seen_seq.get(session_id) == 10

        # Divergence with seq=3 should update last_seen_seq to 3
        await agent._ensure_thread_exists(
            session_id,
            history=[{"role": "user", "content": "Hello"}],
            history_seq=3,
        )
        assert agent._session_last_seen_seq.get(session_id) == 3


class TestDivergenceLoggedWithContext:
    """Tests that divergence is logged with context information."""

    @pytest.mark.asyncio
    async def test_divergence_logged_with_context(self, caplog):
        """Test that divergence is logged with session_id and both sequence numbers."""
        agent = TestableBaseAgent()
        session_id = "test_session_123"

        # Establish session with seq=5
        await agent._ensure_thread_exists(session_id, history_seq=5)

        # Trigger divergence with seq=2
        with caplog.at_level(logging.WARNING):
            agent._check_divergence(session_id, history_seq=2)

        # Check log message contains all expected context
        assert len(caplog.records) == 1
        log_message = caplog.records[0].message
        assert "divergence" in log_message.lower()
        assert session_id in log_message
        assert "5" in log_message  # cached seq
        assert "2" in log_message  # client seq

    @pytest.mark.asyncio
    async def test_divergence_warning_mentions_client_authoritative(self, caplog):
        """Test that log message indicates client is authoritative."""
        agent = TestableBaseAgent()
        session_id = "test_session"

        # Establish session
        await agent._ensure_thread_exists(session_id, history_seq=5)

        # Trigger divergence
        with caplog.at_level(logging.WARNING):
            agent._check_divergence(session_id, history_seq=2)

        log_message = caplog.records[0].message.lower()
        assert "authoritative" in log_message or "rebuild" in log_message


class TestLastSeenSeqEchoedInResponse:
    """Tests that last_seen_seq is available for echoing in response."""

    def test_last_seen_seq_echoed_in_response(self):
        """Test that get_last_seen_seq returns the tracked sequence number."""
        agent = TestableBaseAgent()
        session_id = "test_session"

        # No seq tracked yet
        assert agent.get_last_seen_seq(session_id) is None

        # After updating
        agent._update_last_seen_seq(session_id, 5)
        assert agent.get_last_seen_seq(session_id) == 5

    @pytest.mark.asyncio
    async def test_last_seen_seq_updated_after_stream(self):
        """Test that last_seen_seq is updated after stream() call."""
        agent = TestableBaseAgent()
        session_id = "test_session"

        # Stream with history_seq=7
        async for _ in agent.stream(
            user_input="Hello",
            session_id=session_id,
            history_seq=7,
        ):
            pass

        assert agent.get_last_seen_seq(session_id) == 7

    @pytest.mark.asyncio
    async def test_last_seen_seq_updated_after_invoke(self):
        """Test that last_seen_seq is updated after invoke() call."""
        agent = TestableBaseAgent()
        session_id = "test_session"

        # Invoke with history_seq=3
        await agent.invoke(
            user_input="Hello",
            session_id=session_id,
            history_seq=3,
        )

        assert agent.get_last_seen_seq(session_id) == 3

    def test_last_seen_seq_zero_is_valid(self):
        """Test that history_seq=0 is a valid value (first message in conversation)."""
        agent = TestableBaseAgent()
        session_id = "test_session"

        # Zero should be stored, not treated as falsy
        agent._update_last_seen_seq(session_id, 0)
        assert agent.get_last_seen_seq(session_id) == 0

    def test_last_seen_seq_per_session(self):
        """Test that last_seen_seq is tracked separately per session."""
        agent = TestableBaseAgent()

        agent._update_last_seen_seq("session_a", 5)
        agent._update_last_seen_seq("session_b", 10)

        assert agent.get_last_seen_seq("session_a") == 5
        assert agent.get_last_seen_seq("session_b") == 10


class TestDivergenceWithEmptyHistory:
    """Tests for edge cases with empty history."""

    @pytest.mark.asyncio
    async def test_divergence_without_history_logs_warning(self, caplog):
        """Test that divergence without history provided logs a warning."""
        agent = TestableBaseAgent()
        session_id = "test_session"

        # Establish session
        await agent._ensure_thread_exists(session_id, history_seq=5)

        # Divergence but no history provided
        with caplog.at_level(logging.WARNING):
            await agent._ensure_thread_exists(
                session_id,
                history=None,  # No history provided
                history_seq=2,  # Different seq -> divergence
            )

        # Should warn about inability to rebuild
        log_messages = [r.message.lower() for r in caplog.records]
        assert any("divergence" in msg for msg in log_messages)
        assert any("cannot rebuild" in msg or "no history provided" in msg for msg in log_messages)

    @pytest.mark.asyncio
    async def test_empty_history_triggers_rebuild(self):
        """Test that empty history list still triggers rebuild on divergence."""
        agent = TestableBaseAgent()
        session_id = "test_session"

        # Establish session with seq=5
        await agent._ensure_thread_exists(session_id, history_seq=5)

        # Divergence with empty history list (valid - means start fresh)
        with patch.object(agent, '_rebuild_thread_from_history', new_callable=AsyncMock) as mock_rebuild:
            await agent._ensure_thread_exists(
                session_id,
                history=[],  # Empty but not None
                history_seq=0,  # Reset to beginning
            )
            mock_rebuild.assert_called_once_with(session_id, [])


# =============================================================================
# ORCH-010: Tests for _rebuild_thread_from_history() method
# =============================================================================


class RealThreadTestableAgent(BaseAgentFrameworkAgent):
    """Testable subclass that uses real ChatAgent to test actual thread rebuilding.

    Unlike TestableBaseAgent which uses mocks, this creates a minimal real ChatAgent
    to test the actual thread and message_store functionality in _rebuild_thread_from_history().
    """

    def __init__(self):
        # Create a minimal mock chat client that satisfies the ChatAgent requirements
        from unittest.mock import MagicMock
        from agent_framework import ChatAgent

        mock_chat_client = MagicMock()
        # The ChatAgent needs certain properties from the chat client
        mock_chat_client.get_thread_store.return_value = None

        self.agent = ChatAgent(
            chat_client=mock_chat_client,
            name="TestAgent",
            instructions="Test agent instructions",
        )
        self.session_threads: dict[str, Any] = {}
        self._session_last_seen_seq: dict[str, int] = {}
        self._current_history: list[dict] | None = None
        self._current_history_seq: int | None = None

    def get_agent_name(self) -> str:
        return "TestAgent"

    def get_prompt_name(self) -> str:
        return "test"

    def parse_response(self, message: Any) -> dict[str, Any]:
        return {
            "is_task_complete": True,
            "require_user_input": False,
            "content": message,
        }


class TestRebuildThreadClearsCache:
    """Tests that _rebuild_thread_from_history clears existing cached thread."""

    @pytest.mark.asyncio
    async def test_rebuild_thread_clears_cache(self):
        """Test that rebuild replaces the old thread with a new one."""
        agent = RealThreadTestableAgent()
        session_id = "test_session"

        # Create an initial thread
        old_thread = agent.agent.get_new_thread(thread_id=session_id)
        agent.session_threads[session_id] = old_thread

        # Rebuild with new history
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        await agent._rebuild_thread_from_history(session_id, history)

        # Verify old thread was replaced
        new_thread = agent.session_threads[session_id]
        assert new_thread is not old_thread

    @pytest.mark.asyncio
    async def test_rebuild_with_empty_history_clears_cache(self):
        """Test that rebuild with empty history still creates a fresh thread."""
        agent = RealThreadTestableAgent()
        session_id = "test_session"

        # Create an initial thread with some state
        old_thread = agent.agent.get_new_thread(thread_id=session_id)
        agent.session_threads[session_id] = old_thread

        # Rebuild with empty history (fresh start)
        await agent._rebuild_thread_from_history(session_id, [])

        # Verify thread was replaced
        new_thread = agent.session_threads[session_id]
        assert new_thread is not old_thread


class TestRebuildThreadFromHistory:
    """Tests that _rebuild_thread_from_history properly populates the message store."""

    @pytest.mark.asyncio
    async def test_rebuild_thread_from_history(self):
        """Test that history messages are added to the thread's message store."""
        agent = RealThreadTestableAgent()
        session_id = "test_session"

        history = [
            {"role": "user", "content": "Plan a trip to Tokyo"},
            {"role": "assistant", "content": "I'd be happy to help! When are you traveling?"},
            {"role": "user", "content": "Next month"},
        ]

        await agent._rebuild_thread_from_history(session_id, history)

        # Verify the thread has a message store with the history
        thread = agent.session_threads[session_id]
        assert thread.message_store is not None

        messages = await thread.message_store.list_messages()
        assert len(messages) == 3

    @pytest.mark.asyncio
    async def test_rebuild_with_empty_history_creates_empty_store(self):
        """Test that empty history creates a thread with no messages."""
        agent = RealThreadTestableAgent()
        session_id = "test_session"

        await agent._rebuild_thread_from_history(session_id, [])

        # Thread should exist but have no message store (or empty store)
        thread = agent.session_threads[session_id]
        # When history is empty, we don't attach a message store
        assert thread.message_store is None


class TestRebuildPreservesMessageOrder:
    """Tests that _rebuild_thread_from_history preserves message order."""

    @pytest.mark.asyncio
    async def test_rebuild_preserves_message_order(self):
        """Test that messages are added in the order they appear in history."""
        agent = RealThreadTestableAgent()
        session_id = "test_session"

        history = [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "Second message"},
            {"role": "user", "content": "Third message"},
            {"role": "assistant", "content": "Fourth message"},
            {"role": "user", "content": "Fifth message"},
        ]

        await agent._rebuild_thread_from_history(session_id, history)

        thread = agent.session_threads[session_id]
        messages = await thread.message_store.list_messages()

        # Verify order matches
        assert len(messages) == 5
        assert messages[0].text == "First message"
        assert messages[1].text == "Second message"
        assert messages[2].text == "Third message"
        assert messages[3].text == "Fourth message"
        assert messages[4].text == "Fifth message"

    @pytest.mark.asyncio
    async def test_rebuild_preserves_alternating_roles(self):
        """Test that alternating user/assistant messages maintain their pattern."""
        agent = RealThreadTestableAgent()
        session_id = "test_session"

        history = [
            {"role": "user", "content": "User 1"},
            {"role": "assistant", "content": "Assistant 1"},
            {"role": "user", "content": "User 2"},
            {"role": "assistant", "content": "Assistant 2"},
        ]

        await agent._rebuild_thread_from_history(session_id, history)

        thread = agent.session_threads[session_id]
        messages = await thread.message_store.list_messages()

        # Verify alternating pattern (role.value gives string representation)
        assert str(messages[0].role) == "user"
        assert str(messages[1].role) == "assistant"
        assert str(messages[2].role) == "user"
        assert str(messages[3].role) == "assistant"


class TestRebuildMapsRolesCorrectly:
    """Tests that _rebuild_thread_from_history maps roles correctly."""

    @pytest.mark.asyncio
    async def test_rebuild_maps_roles_correctly(self):
        """Test that 'user' and 'assistant' roles are mapped correctly."""
        agent = RealThreadTestableAgent()
        session_id = "test_session"

        history = [
            {"role": "user", "content": "I'm the user"},
            {"role": "assistant", "content": "I'm the assistant"},
        ]

        await agent._rebuild_thread_from_history(session_id, history)

        thread = agent.session_threads[session_id]
        messages = await thread.message_store.list_messages()

        assert str(messages[0].role) == "user"
        assert messages[0].text == "I'm the user"
        assert str(messages[1].role) == "assistant"
        assert messages[1].text == "I'm the assistant"

    @pytest.mark.asyncio
    async def test_rebuild_skips_invalid_roles(self, caplog):
        """Test that messages with invalid roles are skipped with a warning."""
        agent = RealThreadTestableAgent()
        session_id = "test_session"

        history = [
            {"role": "user", "content": "Valid user message"},
            {"role": "system", "content": "Invalid system message"},  # system not allowed in conversation
            {"role": "assistant", "content": "Valid assistant message"},
            {"role": "tool", "content": "Invalid tool message"},  # tool not allowed
            {"role": "user", "content": "Another user message"},
        ]

        with caplog.at_level(logging.WARNING):
            await agent._rebuild_thread_from_history(session_id, history)

        thread = agent.session_threads[session_id]
        messages = await thread.message_store.list_messages()

        # Only user and assistant messages should be included
        assert len(messages) == 3
        assert str(messages[0].role) == "user"
        assert messages[0].text == "Valid user message"
        assert str(messages[1].role) == "assistant"
        assert messages[1].text == "Valid assistant message"
        assert str(messages[2].role) == "user"
        assert messages[2].text == "Another user message"

        # Should have logged warnings for invalid roles
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_messages) == 2  # Two invalid roles
        assert any("system" in msg for msg in warning_messages)
        assert any("tool" in msg for msg in warning_messages)

    @pytest.mark.asyncio
    async def test_rebuild_handles_missing_role(self, caplog):
        """Test that messages without a role field are skipped."""
        agent = RealThreadTestableAgent()
        session_id = "test_session"

        history = [
            {"role": "user", "content": "Valid message"},
            {"content": "Missing role"},  # No role field
            {"role": "assistant", "content": "Another valid message"},
        ]

        with caplog.at_level(logging.WARNING):
            await agent._rebuild_thread_from_history(session_id, history)

        thread = agent.session_threads[session_id]
        messages = await thread.message_store.list_messages()

        # Only valid messages should be included
        assert len(messages) == 2

    @pytest.mark.asyncio
    async def test_rebuild_handles_missing_content(self):
        """Test that messages with missing content get empty string."""
        agent = RealThreadTestableAgent()
        session_id = "test_session"

        history = [
            {"role": "user", "content": "Has content"},
            {"role": "assistant"},  # No content field
            {"role": "user", "content": ""},  # Empty content
        ]

        await agent._rebuild_thread_from_history(session_id, history)

        thread = agent.session_threads[session_id]
        messages = await thread.message_store.list_messages()

        assert len(messages) == 3
        assert messages[0].text == "Has content"
        assert messages[1].text == ""  # Should be empty string
        assert messages[2].text == ""  # Empty content preserved
