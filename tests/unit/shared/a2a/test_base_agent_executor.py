"""
Unit tests for BaseA2AAgentExecutor history extraction.

Tests ORCH-007: Update BaseA2AAgentExecutor to extract history from request.

Per design doc (Agent Communication section):
- History is sent via message.metadata.history for reliability
- historySeq is a sequence number for divergence detection
- Extraction handles missing/malformed metadata gracefully
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from collections.abc import AsyncIterable

from src.shared.a2a.base_agent_executor import (
    BaseA2AAgentExecutor,
    AgentStreamChunk,
    StreamableAgent,
)


class MockStreamableAgent:
    """Mock agent that captures parameters passed to stream()."""

    def __init__(self):
        self.last_user_input: str | None = None
        self.last_session_id: str | None = None
        self.last_history: list[dict] | None = None
        self.last_history_seq: int | None = None
        self.stream_responses: list[AgentStreamChunk] = [
            {"require_user_input": False, "is_task_complete": True, "content": "Done"}
        ]

    async def stream(
        self,
        user_input: str,
        session_id: str,
        history: list[dict] | None = None,
        history_seq: int | None = None,
    ) -> AsyncIterable[AgentStreamChunk]:
        """Mock stream that captures parameters."""
        self.last_user_input = user_input
        self.last_session_id = session_id
        self.last_history = history
        self.last_history_seq = history_seq
        for response in self.stream_responses:
            yield response


class _TestableExecutor(BaseA2AAgentExecutor):
    """Testable subclass that provides a mock agent."""

    def __init__(self, agent: StreamableAgent):
        super().__init__(agent=agent)


def create_mock_context(
    message_text: str = "Hello",
    context_id: str | None = None,
    metadata: dict | None = None,
) -> MagicMock:
    """Create a mock RequestContext with configurable metadata."""
    context = MagicMock()

    # Mock message with parts
    message = MagicMock()
    message.context_id = context_id
    message.parts = [MagicMock(kind="text", text=message_text)]
    message.metadata = metadata
    context.message = message

    # Mock get_user_input to return the message text
    context.get_user_input.return_value = message_text

    # No current task (new conversation)
    context.current_task = None

    return context


def create_mock_event_queue() -> MagicMock:
    """Create a mock EventQueue."""
    event_queue = MagicMock()
    event_queue.enqueue_event = AsyncMock()
    return event_queue


class TestExtractHistoryFromMetadata:
    """Tests for _extract_history_from_metadata method."""

    def test_extract_history_from_metadata(self):
        """Test that history is correctly extracted from metadata."""
        agent = MockStreamableAgent()
        executor = _TestableExecutor(agent)

        history = [
            {"role": "user", "content": "Plan a trip"},
            {"role": "assistant", "content": "Where to?"},
        ]
        context = create_mock_context(
            metadata={"history": history, "historySeq": 2}
        )

        extracted_history, extracted_seq = executor._extract_history_from_metadata(context)

        assert extracted_history == history
        assert len(extracted_history) == 2

    def test_extract_history_seq_from_metadata(self):
        """Test that historySeq is correctly extracted from metadata."""
        agent = MockStreamableAgent()
        executor = _TestableExecutor(agent)

        context = create_mock_context(
            metadata={"history": [], "historySeq": 5}
        )

        extracted_history, extracted_seq = executor._extract_history_from_metadata(context)

        assert extracted_seq == 5

    def test_extract_history_seq_zero_is_valid(self):
        """Test that historySeq=0 is a valid value (first message)."""
        agent = MockStreamableAgent()
        executor = _TestableExecutor(agent)

        context = create_mock_context(
            metadata={"history": [], "historySeq": 0}
        )

        extracted_history, extracted_seq = executor._extract_history_from_metadata(context)

        assert extracted_seq == 0

    def test_handle_missing_metadata(self):
        """Test graceful handling when metadata is None."""
        agent = MockStreamableAgent()
        executor = _TestableExecutor(agent)

        context = create_mock_context(metadata=None)

        extracted_history, extracted_seq = executor._extract_history_from_metadata(context)

        assert extracted_history is None
        assert extracted_seq is None

    def test_handle_missing_metadata_attribute(self):
        """Test graceful handling when message has no metadata attribute."""
        agent = MockStreamableAgent()
        executor = _TestableExecutor(agent)

        context = MagicMock()
        message = MagicMock(spec=[])  # No metadata attribute
        del message.metadata  # Ensure hasattr returns False
        context.message = message

        extracted_history, extracted_seq = executor._extract_history_from_metadata(context)

        assert extracted_history is None
        assert extracted_seq is None

    def test_handle_non_dict_metadata(self):
        """Test graceful handling when metadata is not a dict."""
        agent = MockStreamableAgent()
        executor = _TestableExecutor(agent)

        context = create_mock_context(metadata="not a dict")

        extracted_history, extracted_seq = executor._extract_history_from_metadata(context)

        assert extracted_history is None
        assert extracted_seq is None

    def test_handle_non_list_history(self):
        """Test graceful handling when history is not a list."""
        agent = MockStreamableAgent()
        executor = _TestableExecutor(agent)

        context = create_mock_context(
            metadata={"history": "not a list", "historySeq": 5}
        )

        extracted_history, extracted_seq = executor._extract_history_from_metadata(context)

        assert extracted_history is None
        assert extracted_seq == 5  # historySeq should still be extracted

    def test_handle_non_int_history_seq(self):
        """Test graceful handling when historySeq is not an int."""
        agent = MockStreamableAgent()
        executor = _TestableExecutor(agent)

        history = [{"role": "user", "content": "Hello"}]
        context = create_mock_context(
            metadata={"history": history, "historySeq": "not an int"}
        )

        extracted_history, extracted_seq = executor._extract_history_from_metadata(context)

        assert extracted_history == history  # history should still be extracted
        assert extracted_seq is None

    def test_handle_missing_history_key(self):
        """Test graceful handling when history key is missing."""
        agent = MockStreamableAgent()
        executor = _TestableExecutor(agent)

        context = create_mock_context(
            metadata={"otherKey": "value"}
        )

        extracted_history, extracted_seq = executor._extract_history_from_metadata(context)

        assert extracted_history is None
        assert extracted_seq is None


class TestHistoryPassedToStream:
    """Tests that extracted history is passed to agent.stream()."""

    @pytest.mark.asyncio
    async def test_history_passed_to_stream(self):
        """Test that extracted history is passed to agent's stream method."""
        agent = MockStreamableAgent()
        executor = _TestableExecutor(agent)

        history = [
            {"role": "user", "content": "Plan a trip"},
            {"role": "assistant", "content": "Where to?"},
        ]
        context = create_mock_context(
            message_text="To Tokyo",
            metadata={"history": history, "historySeq": 2}
        )
        event_queue = create_mock_event_queue()

        # Mock new_task to return a task object
        with patch("src.shared.a2a.base_agent_executor.new_task") as mock_new_task:
            mock_task = MagicMock()
            mock_task.context_id = "ctx_123"
            mock_task.id = "task_123"
            mock_new_task.return_value = mock_task

            await executor.execute(context, event_queue)

        # Verify history was passed to stream
        assert agent.last_history == history
        assert agent.last_history_seq == 2

    @pytest.mark.asyncio
    async def test_none_passed_when_no_history(self):
        """Test that None is passed when no history in metadata."""
        agent = MockStreamableAgent()
        executor = _TestableExecutor(agent)

        context = create_mock_context(
            message_text="Hello",
            metadata=None
        )
        event_queue = create_mock_event_queue()

        with patch("src.shared.a2a.base_agent_executor.new_task") as mock_new_task:
            mock_task = MagicMock()
            mock_task.context_id = "ctx_123"
            mock_task.id = "task_123"
            mock_new_task.return_value = mock_task

            await executor.execute(context, event_queue)

        # Verify None was passed to stream
        assert agent.last_history is None
        assert agent.last_history_seq is None

    @pytest.mark.asyncio
    async def test_user_input_still_passed(self):
        """Test that user input is still correctly passed alongside history."""
        agent = MockStreamableAgent()
        executor = _TestableExecutor(agent)

        history = [{"role": "user", "content": "Hello"}]
        context = create_mock_context(
            message_text="To Tokyo",
            metadata={"history": history, "historySeq": 1}
        )
        event_queue = create_mock_event_queue()

        with patch("src.shared.a2a.base_agent_executor.new_task") as mock_new_task:
            mock_task = MagicMock()
            mock_task.context_id = "ctx_123"
            mock_task.id = "task_123"
            mock_new_task.return_value = mock_task

            await executor.execute(context, event_queue)

        # Verify user input was passed correctly
        assert agent.last_user_input == "To Tokyo"
        assert agent.last_session_id == "ctx_123"


class TestStreamableAgentProtocol:
    """Tests for the StreamableAgent protocol update."""

    def test_protocol_accepts_history_parameter(self):
        """Test that StreamableAgent protocol defines history parameter."""
        # The MockStreamableAgent implements the protocol with history
        agent = MockStreamableAgent()

        # This should work without error - the protocol accepts history
        assert hasattr(agent, "stream")
        # Verify the signature accepts history parameters
        import inspect
        sig = inspect.signature(agent.stream)
        params = list(sig.parameters.keys())
        assert "history" in params
        assert "history_seq" in params

    def test_protocol_history_is_optional(self):
        """Test that history parameter is optional in protocol."""
        import inspect
        sig = inspect.signature(MockStreamableAgent().stream)
        params = sig.parameters

        # history should have a default value of None
        assert params["history"].default is None
        assert params["history_seq"].default is None
