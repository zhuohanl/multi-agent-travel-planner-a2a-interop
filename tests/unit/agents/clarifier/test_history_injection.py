"""
Unit tests for verifying clarifier agent works with history injection.

Tests ORCH-011: Verify clarifier agent works with history injection.

Per design doc (Agent Communication section):
- Clarifier agent should inherit history support from BaseAgentFrameworkAgent
- History is received from request metadata via BaseA2AAgentExecutor
- No changes needed to clarifier-specific code (inheritance works)
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from collections.abc import AsyncIterable
from typing import Any

from src.agents.intake_clarifier_agent.agent import AgentFrameworkIntakeClarifierAgent
from src.agents.intake_clarifier_agent.agent_executor import (
    AgentFrameworkIntakeClarifierAgentExecutor,
)
from src.shared.agents.base_agent import BaseAgentFrameworkAgent
from src.shared.a2a.base_agent_executor import BaseA2AAgentExecutor


class TestClarifierInheritsHistorySupport:
    """Tests that clarifier agent inherits history support from base classes."""

    def test_clarifier_inherits_from_base_agent_framework_agent(self):
        """Test that AgentFrameworkIntakeClarifierAgent inherits from BaseAgentFrameworkAgent."""
        assert issubclass(
            AgentFrameworkIntakeClarifierAgent, BaseAgentFrameworkAgent
        ), "Clarifier agent must inherit from BaseAgentFrameworkAgent"

    def test_clarifier_executor_inherits_from_base_executor(self):
        """Test that the clarifier executor inherits from BaseA2AAgentExecutor."""
        assert issubclass(
            AgentFrameworkIntakeClarifierAgentExecutor, BaseA2AAgentExecutor
        ), "Clarifier executor must inherit from BaseA2AAgentExecutor"

    def test_clarifier_has_history_parameters_in_stream(self):
        """Test that clarifier's stream() method accepts history parameters via inheritance."""
        import inspect

        # Get the stream() method signature from the clarifier's parent
        stream_sig = inspect.signature(BaseAgentFrameworkAgent.stream)
        stream_params = stream_sig.parameters

        # Verify history parameters exist with correct defaults
        assert "history" in stream_params, "stream() must have history parameter"
        assert (
            stream_params["history"].default is None
        ), "history parameter must default to None"
        assert "history_seq" in stream_params, "stream() must have history_seq parameter"
        assert (
            stream_params["history_seq"].default is None
        ), "history_seq parameter must default to None"

    def test_clarifier_has_history_parameters_in_invoke(self):
        """Test that clarifier's invoke() method accepts history parameters via inheritance."""
        import inspect

        # Get the invoke() method signature from the clarifier's parent
        invoke_sig = inspect.signature(BaseAgentFrameworkAgent.invoke)
        invoke_params = invoke_sig.parameters

        # Verify history parameters exist with correct defaults
        assert "history" in invoke_params, "invoke() must have history parameter"
        assert (
            invoke_params["history"].default is None
        ), "history parameter must default to None"
        assert "history_seq" in invoke_params, "invoke() must have history_seq parameter"
        assert (
            invoke_params["history_seq"].default is None
        ), "history_seq parameter must default to None"


class MockChatAgent:
    """Mock ChatAgent for testing without LLM calls."""

    def __init__(self):
        # Return valid ClarifierResponse JSON format
        self.run_response = MagicMock()
        self.run_response.text = (
            '{"response": "Where would you like to go?", '
            '"trip_spec": null}'
        )
        self.stream_chunks = [
            MagicMock(
                text='{"response": "Where would you like to go?", "trip_spec": null}'
            )
        ]

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


class TestClarifierReceivesHistory:
    """Tests that clarifier receives and processes history correctly."""

    @pytest.fixture
    def mock_clarifier_agent(self):
        """Create a clarifier agent with mocked chat service."""
        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkIntakeClarifierAgent()
            # Replace the agent with a mock
            agent.agent = MockChatAgent()
            return agent

    @pytest.mark.asyncio
    async def test_clarifier_stream_receives_history(self, mock_clarifier_agent):
        """Test that clarifier agent receives history via stream() method."""
        history = [
            {"role": "user", "content": "Plan a trip"},
            {"role": "assistant", "content": "Where would you like to go?"},
        ]

        responses = []
        async for response in mock_clarifier_agent.stream(
            user_input="To Tokyo",
            session_id="test_session",
            history=history,
            history_seq=2,
        ):
            responses.append(response)

        # Verify history was stored
        assert mock_clarifier_agent._current_history == history
        assert mock_clarifier_agent._current_history_seq == 2
        # Verify response was processed
        assert len(responses) == 1

    @pytest.mark.asyncio
    async def test_clarifier_invoke_receives_history(self, mock_clarifier_agent):
        """Test that clarifier agent receives history via invoke() method."""
        history = [
            {"role": "user", "content": "Plan a trip"},
            {"role": "assistant", "content": "Where would you like to go?"},
        ]

        response = await mock_clarifier_agent.invoke(
            user_input="To Tokyo",
            session_id="test_session",
            history=history,
            history_seq=2,
        )

        # Verify history was stored
        assert mock_clarifier_agent._current_history == history
        assert mock_clarifier_agent._current_history_seq == 2
        # Verify response was processed
        assert response is not None

    @pytest.mark.asyncio
    async def test_clarifier_works_without_history_backward_compatible(
        self, mock_clarifier_agent
    ):
        """Test that clarifier still works when history is not provided (backward compatibility)."""
        responses = []
        async for response in mock_clarifier_agent.stream(
            user_input="Plan a trip",
            session_id="test_session",
        ):
            responses.append(response)

        # Verify it works without history
        assert mock_clarifier_agent._current_history is None
        assert mock_clarifier_agent._current_history_seq is None
        assert len(responses) == 1

    @pytest.mark.asyncio
    async def test_clarifier_history_seq_zero_is_valid(self, mock_clarifier_agent):
        """Test that history_seq=0 is a valid value (first message in conversation)."""
        history = []

        responses = []
        async for response in mock_clarifier_agent.stream(
            user_input="First message",
            session_id="test_session",
            history=history,
            history_seq=0,
        ):
            responses.append(response)

        # Zero should be stored, not treated as falsy/None
        assert mock_clarifier_agent._current_history == []
        assert mock_clarifier_agent._current_history_seq == 0
        assert len(responses) == 1


class TestClarifierNoCodeChangesNeeded:
    """
    Tests verifying that no changes to clarifier-specific code were needed.

    The clarifier should work with history injection purely through inheritance.
    """

    def test_clarifier_agent_does_not_override_stream(self):
        """Test that clarifier doesn't override stream() method."""
        # If clarifier overrides stream(), it would appear in the class's __dict__
        assert (
            "stream" not in AgentFrameworkIntakeClarifierAgent.__dict__
        ), "Clarifier should not override stream() - inheritance should work"

    def test_clarifier_agent_does_not_override_invoke(self):
        """Test that clarifier doesn't override invoke() method."""
        assert (
            "invoke" not in AgentFrameworkIntakeClarifierAgent.__dict__
        ), "Clarifier should not override invoke() - inheritance should work"

    def test_clarifier_agent_does_not_override_ensure_thread_exists(self):
        """Test that clarifier doesn't override _ensure_thread_exists() method."""
        assert (
            "_ensure_thread_exists" not in AgentFrameworkIntakeClarifierAgent.__dict__
        ), "Clarifier should not override _ensure_thread_exists()"

    def test_clarifier_only_overrides_expected_methods(self):
        """Test that clarifier only overrides expected abstract methods."""
        # These are the only methods that clarifier should define
        expected_methods = {
            "get_agent_name",
            "get_prompt_name",
            "get_response_format",
            "parse_response",
        }

        # Get methods defined directly on the clarifier class (not inherited)
        clarifier_methods = {
            name
            for name in AgentFrameworkIntakeClarifierAgent.__dict__
            if callable(getattr(AgentFrameworkIntakeClarifierAgent, name))
            and not name.startswith("_")
        }

        # Clarifier should only define the expected abstract method implementations
        assert clarifier_methods == expected_methods, (
            f"Clarifier should only override {expected_methods}, "
            f"but found {clarifier_methods}"
        )
