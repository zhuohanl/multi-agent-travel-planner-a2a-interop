"""
Unit tests for BaseAgentFrameworkAgent history parameter support.

Tests ORCH-008: Update BaseAgentFrameworkAgent.stream() to accept history parameter.

Per design doc (Agent Communication section):
- stream() and invoke() accept optional history parameter
- stream() and invoke() accept optional history_seq parameter
- Parameters are optional for backward compatibility
- History is accessible for divergence detection (ORCH-009)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from collections.abc import AsyncIterable
from typing import Any

from src.shared.agents.base_agent import BaseAgentFrameworkAgent


class MockChatAgent:
    """Mock ChatAgent for testing without LLM calls."""

    def __init__(self):
        self.run_response = MagicMock()
        self.run_response.text = '{"is_task_complete": true, "require_user_input": false, "content": "Done"}'
        self.stream_chunks = [MagicMock(text="chunk1"), MagicMock(text="chunk2")]

    def get_new_thread(self, thread_id: str) -> MagicMock:
        thread = MagicMock()
        thread.thread_id = thread_id
        thread.message_store = None
        return thread

    async def run(self, messages: str, thread: Any) -> MagicMock:
        return self.run_response

    async def run_stream(self, messages: str, thread: Any) -> AsyncIterable:
        for chunk in self.stream_chunks:
            yield chunk


class FailingChatAgent(MockChatAgent):
    """Mock ChatAgent that raises at runtime."""

    async def run(self, messages: str, thread: Any) -> MagicMock:
        raise RuntimeError("chat service unavailable")

    async def run_stream(self, messages: str, thread: Any) -> AsyncIterable:
        raise RuntimeError("stream service unavailable")
        yield  # pragma: no cover


class TestableBaseAgent(BaseAgentFrameworkAgent):
    """Testable subclass that provides mock implementations."""

    def __init__(self):
        # Skip the parent __init__ to avoid needing real chat services
        self.agent = MockChatAgent()
        self.session_threads: dict[str, Any] = {}
        # Track last_seen_seq per session for divergence detection (ORCH-009)
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


class FailingBaseAgent(TestableBaseAgent):
    """Agent wrapper with a failing chat backend."""

    def __init__(self):
        self.agent = FailingChatAgent()
        self.session_threads: dict[str, Any] = {}
        self._session_last_seen_seq: dict[str, int] = {}
        self._current_history: list[dict] | None = None
        self._current_history_seq: int | None = None


class TestStreamAcceptsHistoryParameter:
    """Tests for stream() method accepting history parameter."""

    @pytest.mark.asyncio
    async def test_stream_accepts_history_parameter(self):
        """Test that stream() accepts optional history parameter."""
        agent = TestableBaseAgent()
        history = [
            {"role": "user", "content": "Plan a trip"},
            {"role": "assistant", "content": "Where to?"},
        ]

        responses = []
        async for response in agent.stream(
            user_input="To Tokyo",
            session_id="test_session",
            history=history,
        ):
            responses.append(response)

        # Should complete without error
        assert len(responses) == 1
        assert responses[0]["is_task_complete"] is True

    @pytest.mark.asyncio
    async def test_stream_accepts_history_seq_parameter(self):
        """Test that stream() accepts optional history_seq parameter."""
        agent = TestableBaseAgent()

        responses = []
        async for response in agent.stream(
            user_input="Hello",
            session_id="test_session",
            history_seq=5,
        ):
            responses.append(response)

        # Should complete without error
        assert len(responses) == 1

    @pytest.mark.asyncio
    async def test_stream_accepts_both_parameters(self):
        """Test that stream() accepts both history and history_seq."""
        agent = TestableBaseAgent()
        history = [{"role": "user", "content": "Hello"}]

        responses = []
        async for response in agent.stream(
            user_input="World",
            session_id="test_session",
            history=history,
            history_seq=1,
        ):
            responses.append(response)

        assert len(responses) == 1

    @pytest.mark.asyncio
    async def test_stream_works_without_history(self):
        """Test that stream() works without history parameter (backward compatibility)."""
        agent = TestableBaseAgent()

        responses = []
        async for response in agent.stream(
            user_input="Hello",
            session_id="test_session",
        ):
            responses.append(response)

        # Should complete without error - backward compatible
        assert len(responses) == 1


class TestInvokeAcceptsHistoryParameter:
    """Tests for invoke() method accepting history parameter."""

    @pytest.mark.asyncio
    async def test_invoke_accepts_history_parameter(self):
        """Test that invoke() accepts optional history parameter."""
        agent = TestableBaseAgent()
        history = [
            {"role": "user", "content": "Plan a trip"},
            {"role": "assistant", "content": "Where to?"},
        ]

        response = await agent.invoke(
            user_input="To Tokyo",
            session_id="test_session",
            history=history,
        )

        # Should complete without error
        assert response["is_task_complete"] is True

    @pytest.mark.asyncio
    async def test_invoke_accepts_history_seq_parameter(self):
        """Test that invoke() accepts optional history_seq parameter."""
        agent = TestableBaseAgent()

        response = await agent.invoke(
            user_input="Hello",
            session_id="test_session",
            history_seq=5,
        )

        # Should complete without error
        assert "is_task_complete" in response

    @pytest.mark.asyncio
    async def test_invoke_accepts_both_parameters(self):
        """Test that invoke() accepts both history and history_seq."""
        agent = TestableBaseAgent()
        history = [{"role": "user", "content": "Hello"}]

        response = await agent.invoke(
            user_input="World",
            session_id="test_session",
            history=history,
            history_seq=1,
        )

        assert response["is_task_complete"] is True

    @pytest.mark.asyncio
    async def test_invoke_works_without_history(self):
        """Test that invoke() works without history parameter (backward compatibility)."""
        agent = TestableBaseAgent()

        response = await agent.invoke(
            user_input="Hello",
            session_id="test_session",
        )

        # Should complete without error - backward compatible
        assert response["is_task_complete"] is True


class TestHistoryAccessibility:
    """Tests that history is accessible for divergence detection."""

    @pytest.mark.asyncio
    async def test_history_stored_after_stream(self):
        """Test that history is stored and accessible after stream() call."""
        agent = TestableBaseAgent()
        history = [
            {"role": "user", "content": "Plan a trip"},
            {"role": "assistant", "content": "Where to?"},
        ]

        async for _ in agent.stream(
            user_input="To Tokyo",
            session_id="test_session",
            history=history,
            history_seq=2,
        ):
            pass

        # History should be accessible on the agent instance
        assert agent._current_history == history
        assert agent._current_history_seq == 2

    @pytest.mark.asyncio
    async def test_history_stored_after_invoke(self):
        """Test that history is stored and accessible after invoke() call."""
        agent = TestableBaseAgent()
        history = [{"role": "user", "content": "Hello"}]

        await agent.invoke(
            user_input="World",
            session_id="test_session",
            history=history,
            history_seq=1,
        )

        # History should be accessible on the agent instance
        assert agent._current_history == history
        assert agent._current_history_seq == 1

    @pytest.mark.asyncio
    async def test_none_history_stored_when_not_provided(self):
        """Test that None is stored when history is not provided."""
        agent = TestableBaseAgent()

        await agent.invoke(
            user_input="Hello",
            session_id="test_session",
        )

        # History should be None when not provided
        assert agent._current_history is None
        assert agent._current_history_seq is None

    @pytest.mark.asyncio
    async def test_history_seq_zero_is_valid(self):
        """Test that history_seq=0 is a valid value (first message in conversation)."""
        agent = TestableBaseAgent()
        history = []

        await agent.invoke(
            user_input="First message",
            session_id="test_session",
            history=history,
            history_seq=0,
        )

        # Zero should be stored, not treated as falsy/None
        assert agent._current_history == []
        assert agent._current_history_seq == 0


class TestBackwardCompatibility:
    """Tests ensuring existing agent implementations continue working."""

    @pytest.mark.asyncio
    async def test_existing_callers_without_history_still_work(self):
        """Test that existing callers can use stream() without providing history."""
        agent = TestableBaseAgent()

        # This is how existing code calls stream() - without history parameters
        responses = []
        async for response in agent.stream("Hello", "session_123"):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["is_task_complete"] is True

    @pytest.mark.asyncio
    async def test_existing_callers_invoke_without_history_still_work(self):
        """Test that existing callers can use invoke() without providing history."""
        agent = TestableBaseAgent()

        # This is how existing code calls invoke() - without history parameters
        response = await agent.invoke("Hello", "session_123")

        assert response["is_task_complete"] is True

    def test_method_signature_has_optional_defaults(self):
        """Test that history parameters have default values of None."""
        import inspect

        # Check stream() signature
        stream_sig = inspect.signature(BaseAgentFrameworkAgent.stream)
        stream_params = stream_sig.parameters
        assert "history" in stream_params
        assert stream_params["history"].default is None
        assert "history_seq" in stream_params
        assert stream_params["history_seq"].default is None

        # Check invoke() signature
        invoke_sig = inspect.signature(BaseAgentFrameworkAgent.invoke)
        invoke_params = invoke_sig.parameters
        assert "history" in invoke_params
        assert invoke_params["history"].default is None
        assert "history_seq" in invoke_params
        assert invoke_params["history_seq"].default is None


class TestExecutionErrorFallback:
    """Tests for fallback behavior when the underlying chat service fails."""

    @pytest.mark.asyncio
    async def test_invoke_returns_error_payload_on_backend_failure(self):
        agent = FailingBaseAgent()

        response = await agent.invoke(
            user_input="Hello",
            session_id="session_error_invoke",
        )

        assert response["is_task_complete"] is False
        assert response["require_user_input"] is True
        assert "unable to process" in response["content"].lower()

    @pytest.mark.asyncio
    async def test_stream_yields_error_payload_on_backend_failure(self):
        agent = FailingBaseAgent()

        responses = []
        async for response in agent.stream(
            user_input="Hello",
            session_id="session_error_stream",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["is_task_complete"] is False
        assert responses[0]["require_user_input"] is True
        assert "unable to process" in responses[0]["content"].lower()
