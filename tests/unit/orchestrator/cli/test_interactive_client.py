"""Unit tests for the interactive CLI client.

These tests verify:
1. CLI command parsing (/new, /status, /help, /quit)
2. Session state management (new session, context preservation)
3. Response handling and state updates
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.orchestrator.cli.interactive_client import (
    CLICommand,
    Colors,
    ConversationMessage,
    InteractiveCLI,
    SessionState,
)
from src.shared.a2a.client_wrapper import A2AResponse


# =============================================================================
# CLICommand Tests
# =============================================================================


class TestCLICommand:
    """Tests for CLICommand parsing."""

    def test_parse_new_command(self):
        """Test parsing /new command."""
        assert CLICommand.parse("/new") == CLICommand.NEW
        assert CLICommand.parse("/NEW") == CLICommand.NEW
        assert CLICommand.parse("  /new  ") == CLICommand.NEW

    def test_parse_status_command(self):
        """Test parsing /status command."""
        assert CLICommand.parse("/status") == CLICommand.STATUS
        assert CLICommand.parse("/STATUS") == CLICommand.STATUS

    def test_parse_help_command(self):
        """Test parsing /help command."""
        assert CLICommand.parse("/help") == CLICommand.HELP

    def test_parse_quit_command(self):
        """Test parsing /quit command."""
        assert CLICommand.parse("/quit") == CLICommand.QUIT

    def test_parse_history_command(self):
        """Test parsing /history command."""
        assert CLICommand.parse("/history") == CLICommand.HISTORY

    def test_parse_invalid_command(self):
        """Test that non-commands return None."""
        assert CLICommand.parse("hello") is None
        assert CLICommand.parse("/unknown") is None
        assert CLICommand.parse("") is None

    def test_is_command(self):
        """Test is_command helper."""
        assert CLICommand.is_command("/new") is True
        assert CLICommand.is_command("/status") is True
        assert CLICommand.is_command("hello world") is False
        assert CLICommand.is_command("/notacommand") is False


# =============================================================================
# SessionState Tests
# =============================================================================


class TestSessionState:
    """Tests for SessionState management."""

    def test_initial_state(self):
        """Test initial session state values."""
        state = SessionState()
        assert state.session_id is None
        assert state.context_id is None
        assert state.task_id is None
        assert state.consultation_id is None
        assert state.messages == []
        assert state.is_complete is False
        assert state.requires_input is True

    def test_reset_clears_state(self):
        """Test that reset clears all state."""
        state = SessionState(
            session_id="sess_123",
            context_id="ctx_456",
            task_id="task_789",
            consultation_id="cons_abc",
            messages=[ConversationMessage(role="user", content="hello")],
            is_complete=True,
            requires_input=False,
        )

        state.reset()

        assert state.session_id is None
        assert state.context_id is None
        assert state.task_id is None
        assert state.consultation_id is None
        assert state.messages == []
        assert state.is_complete is False
        assert state.requires_input is True

    def test_add_user_message(self):
        """Test adding user messages to history."""
        state = SessionState()
        state.add_user_message("Hello, I want to plan a trip")

        assert len(state.messages) == 1
        assert state.messages[0].role == "user"
        assert state.messages[0].content == "Hello, I want to plan a trip"
        assert isinstance(state.messages[0].timestamp, datetime)

    def test_add_assistant_message(self):
        """Test adding assistant messages to history."""
        state = SessionState()
        state.add_assistant_message("I can help you with that!")

        assert len(state.messages) == 1
        assert state.messages[0].role == "assistant"
        assert state.messages[0].content == "I can help you with that!"

    def test_update_from_response(self):
        """Test updating state from A2A response."""
        state = SessionState()
        response = A2AResponse(
            text="Welcome!",
            context_id="ctx_new_123",
            task_id="task_new_456",
            is_complete=False,
            requires_input=True,
        )

        state.update_from_response(response)

        assert state.context_id == "ctx_new_123"
        assert state.task_id == "task_new_456"
        assert state.is_complete is False
        assert state.requires_input is True

    def test_update_from_response_preserves_context_id(self):
        """Test that response without context_id preserves existing."""
        state = SessionState(context_id="ctx_existing")
        response = A2AResponse(
            text="Hello",
            context_id=None,  # No new context_id
            task_id="task_123",
        )

        state.update_from_response(response)

        assert state.context_id == "ctx_existing"  # Preserved
        assert state.task_id == "task_123"  # Updated

    def test_to_status_dict(self):
        """Test converting state to status dictionary."""
        state = SessionState(
            session_id="sess_123",
            context_id="ctx_456",
            task_id="task_789",
            consultation_id="cons_abc",
            is_complete=False,
            requires_input=True,
        )
        state.add_user_message("Hello")
        state.add_assistant_message("Hi there!")

        status = state.to_status_dict()

        assert status["session_id"] == "sess_123"
        assert status["context_id"] == "ctx_456"
        assert status["task_id"] == "task_789"
        assert status["consultation_id"] == "cons_abc"
        assert status["message_count"] == 2
        assert status["is_complete"] is False
        assert status["requires_input"] is True


# =============================================================================
# InteractiveCLI Tests
# =============================================================================


class TestInteractiveCLI:
    """Tests for InteractiveCLI functionality."""

    def test_default_url(self):
        """Test default orchestrator URL."""
        cli = InteractiveCLI()
        assert cli.orchestrator_url == "http://localhost:10000"

    def test_custom_url(self):
        """Test custom orchestrator URL."""
        cli = InteractiveCLI(orchestrator_url="http://custom:8000")
        assert cli.orchestrator_url == "http://custom:8000"

    def test_custom_timeout(self):
        """Test custom timeout setting."""
        cli = InteractiveCLI(timeout=60.0)
        assert cli.timeout == 60.0

    def test_handle_new_command(self):
        """Test /new command resets session."""
        cli = InteractiveCLI()
        cli.state.context_id = "ctx_existing"
        cli.state.add_user_message("old message")

        result = cli._handle_command(CLICommand.NEW)

        assert result is True  # Continue running
        assert cli.state.context_id is None
        assert cli.state.messages == []

    def test_handle_status_command(self):
        """Test /status command returns True (continue)."""
        cli = InteractiveCLI(use_colors=False)
        cli.state.context_id = "ctx_123"

        result = cli._handle_command(CLICommand.STATUS)

        assert result is True  # Continue running

    def test_handle_help_command(self):
        """Test /help command returns True (continue)."""
        cli = InteractiveCLI(use_colors=False)

        result = cli._handle_command(CLICommand.HELP)

        assert result is True  # Continue running

    def test_handle_quit_command(self):
        """Test /quit command returns False (stop)."""
        cli = InteractiveCLI(use_colors=False)

        result = cli._handle_command(CLICommand.QUIT)

        assert result is False  # Stop running

    def test_handle_history_command(self):
        """Test /history command returns True (continue)."""
        cli = InteractiveCLI(use_colors=False)
        cli.state.add_user_message("Hello")
        cli.state.add_assistant_message("Hi!")

        result = cli._handle_command(CLICommand.HISTORY)

        assert result is True  # Continue running

    def test_get_prompt_without_context(self):
        """Test prompt without context_id."""
        cli = InteractiveCLI()

        prompt = cli._get_prompt()

        assert prompt == "You: "

    def test_get_prompt_with_context(self):
        """Test prompt with context_id shows abbreviated ID."""
        cli = InteractiveCLI()
        cli.state.context_id = "ctx_1234567890abcdef"

        prompt = cli._get_prompt()

        assert prompt == "[ctx_1234...] You: "

    @pytest.mark.asyncio
    async def test_send_message_updates_state(self):
        """Test that send_message updates session state."""
        cli = InteractiveCLI()

        mock_response = A2AResponse(
            text="Hello! How can I help?",
            context_id="ctx_new_123",
            task_id="task_new_456",
            is_complete=False,
            requires_input=True,
        )

        with patch.object(cli, "_print"):  # Suppress output
            with patch(
                "src.orchestrator.cli.interactive_client.A2AClientWrapper"
            ) as MockWrapper:
                mock_instance = AsyncMock()
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                mock_instance.health_check = AsyncMock(return_value=True)
                mock_instance.send_message = AsyncMock(return_value=mock_response)
                MockWrapper.return_value = mock_instance

                result = await cli.send_message("Plan a trip to Tokyo")

        assert result == "Hello! How can I help?"
        assert cli.state.context_id == "ctx_new_123"
        assert cli.state.task_id == "task_new_456"
        assert len(cli.state.messages) == 2  # User + Assistant

    @pytest.mark.asyncio
    async def test_send_message_preserves_context_id(self):
        """Test that context_id is preserved across calls."""
        cli = InteractiveCLI()
        cli.state.context_id = "ctx_existing_123"

        mock_response = A2AResponse(
            text="Following up...",
            context_id="ctx_existing_123",  # Same context
            task_id=None,
        )

        with patch.object(cli, "_print"):
            with patch(
                "src.orchestrator.cli.interactive_client.A2AClientWrapper"
            ) as MockWrapper:
                mock_instance = AsyncMock()
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                mock_instance.health_check = AsyncMock(return_value=True)
                mock_instance.send_message = AsyncMock(return_value=mock_response)
                MockWrapper.return_value = mock_instance

                await cli.send_message("Continue from before")

                # Verify context_id was passed to send_message
                call_args = mock_instance.send_message.call_args
                assert call_args.kwargs["context_id"] == "ctx_existing_123"

    @pytest.mark.asyncio
    async def test_send_message_handles_connection_error(self):
        """Test graceful handling of connection errors."""
        cli = InteractiveCLI()

        with patch.object(cli, "_print") as mock_print:
            with patch(
                "src.orchestrator.cli.interactive_client.A2AClientWrapper"
            ) as MockWrapper:
                mock_instance = AsyncMock()
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                mock_instance.health_check = AsyncMock(return_value=False)
                MockWrapper.return_value = mock_instance

                result = await cli.send_message("Hello")

        assert result is None
        # Verify error message was printed
        assert any("Cannot connect" in str(call) for call in mock_print.call_args_list)

    def test_stop_sets_running_false(self):
        """Test that stop() sets _running to False."""
        cli = InteractiveCLI()
        cli._running = True

        cli.stop()

        assert cli._running is False


# =============================================================================
# Colors Tests
# =============================================================================


class TestColors:
    """Tests for color formatting."""

    def test_colorize(self):
        """Test basic colorization."""
        result = Colors.colorize("hello", Colors.RED)
        assert Colors.RED in result
        assert Colors.RESET in result
        assert "hello" in result

    def test_user_color(self):
        """Test user message coloring."""
        result = Colors.user("my input")
        assert Colors.GREEN in result
        assert "my input" in result

    def test_assistant_color(self):
        """Test assistant message coloring."""
        result = Colors.assistant("response")
        assert Colors.CYAN in result
        assert "response" in result

    def test_system_color(self):
        """Test system message coloring."""
        result = Colors.system("info")
        assert Colors.YELLOW in result
        assert "info" in result

    def test_error_color(self):
        """Test error message coloring."""
        result = Colors.error("something went wrong")
        assert Colors.RED in result
        assert "something went wrong" in result

    def test_dim_color(self):
        """Test dimmed text formatting."""
        result = Colors.dim("secondary")
        assert Colors.DIM in result
        assert "secondary" in result


# =============================================================================
# ConversationMessage Tests
# =============================================================================


class TestConversationMessage:
    """Tests for ConversationMessage."""

    def test_default_timestamp(self):
        """Test that timestamp is auto-generated."""
        msg = ConversationMessage(role="user", content="hello")

        assert isinstance(msg.timestamp, datetime)

    def test_explicit_timestamp(self):
        """Test explicit timestamp."""
        ts = datetime(2024, 1, 15, 12, 0, 0)
        msg = ConversationMessage(role="assistant", content="hi", timestamp=ts)

        assert msg.timestamp == ts
