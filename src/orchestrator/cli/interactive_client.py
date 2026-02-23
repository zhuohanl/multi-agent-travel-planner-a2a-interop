"""Interactive CLI client for end-to-end orchestrator testing.

This module provides a command-line interface for testing the orchestrator
via the A2A protocol. It supports multi-turn conversations, streaming responses,
session management, and special commands for controlling the session.

Architecture:
    - Uses A2AClientWrapper for A2A protocol communication
    - Maintains session state (session_id, context_id, conversation history)
    - REPL loop with readline support for better input handling
    - Colored output for readability using ANSI escape codes

Commands:
    /new     - Start a new session (clears current state)
    /status  - Show current session state
    /help    - Show available commands
    /quit    - Exit the CLI

Example:
    cli = InteractiveCLI(orchestrator_url="http://localhost:10000")
    await cli.run()
"""

from __future__ import annotations

import os
import asyncio
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from src.shared.a2a.client_wrapper import (
    A2AClientError,
    A2AClientWrapper,
    A2AConnectionError,
    A2AResponse,
    A2ATimeoutError,
)

logger = logging.getLogger(__name__)

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# =============================================================================
# ANSI Color Codes for Terminal Output
# =============================================================================


class Colors:
    """ANSI escape codes for colored terminal output."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Foreground colors
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright foreground colors
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_CYAN = "\033[96m"

    @classmethod
    def colorize(cls, text: str, color: str) -> str:
        """Wrap text with color codes."""
        return f"{color}{text}{cls.RESET}"

    @classmethod
    def user(cls, text: str) -> str:
        """Format user input."""
        return cls.colorize(text, cls.GREEN)

    @classmethod
    def assistant(cls, text: str) -> str:
        """Format assistant response."""
        return cls.colorize(text, cls.CYAN)

    @classmethod
    def system(cls, text: str) -> str:
        """Format system messages."""
        return cls.colorize(text, cls.YELLOW)

    @classmethod
    def error(cls, text: str) -> str:
        """Format error messages."""
        return cls.colorize(text, cls.RED)

    @classmethod
    def dim(cls, text: str) -> str:
        """Format dimmed/secondary text."""
        return cls.colorize(text, cls.DIM)


# =============================================================================
# CLI Commands
# =============================================================================


class CLICommand(Enum):
    """Special CLI commands."""

    NEW = "/new"
    STATUS = "/status"
    HELP = "/help"
    QUIT = "/quit"
    HISTORY = "/history"
    ACTION = "/action"

    @classmethod
    def parse(cls, text: str) -> CLICommand | None:
        """Parse text into a CLI command if it matches."""
        text_lower = text.strip().lower()
        for cmd in cls:
            if text_lower == cmd.value:
                return cmd
        return None

    @classmethod
    def is_command(cls, text: str) -> bool:
        """Check if text is a CLI command."""
        return cls.parse(text) is not None


# =============================================================================
# Session State
# =============================================================================


@dataclass
class ConversationMessage:
    """A message in the conversation history."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SessionState:
    """Tracks the current CLI session state."""

    session_id: str | None = None
    context_id: str | None = None
    task_id: str | None = None
    consultation_id: str | None = None
    messages: list[ConversationMessage] = field(default_factory=list)
    is_complete: bool = False
    requires_input: bool = True
    pending_actions: list[dict[str, Any]] = field(default_factory=list)
    text_input_enabled: bool = True
    phase: str | None = None
    checkpoint: str | None = None

    def reset(self) -> None:
        """Reset session state for a new conversation."""
        self.session_id = None
        self.context_id = None
        self.task_id = None
        self.consultation_id = None
        self.messages = []
        self.is_complete = False
        self.requires_input = True
        self.pending_actions = []
        self.text_input_enabled = True
        self.phase = None
        self.checkpoint = None

    def add_user_message(self, content: str) -> None:
        """Add a user message to history."""
        self.messages.append(ConversationMessage(role="user", content=content))

    def add_assistant_message(self, content: str) -> None:
        """Add an assistant message to history."""
        self.messages.append(ConversationMessage(role="assistant", content=content))

    def update_from_response(self, response: A2AResponse) -> None:
        """Update state from an A2A response."""
        if response.context_id:
            self.context_id = response.context_id
        if response.is_complete:
            self.task_id = None
        elif response.task_id:
            self.task_id = response.task_id
        self.is_complete = response.is_complete
        self.requires_input = response.requires_input

        # Extract consultation_id from response if present
        for chunk in response.raw_chunks:
            if "result" in chunk:
                result = chunk["result"]
                if "metadata" in result and isinstance(result["metadata"], dict):
                    consultation_id = result["metadata"].get("consultation_id")
                    if consultation_id:
                        self.consultation_id = consultation_id

    def to_status_dict(self) -> dict:
        """Convert state to a dictionary for status display."""
        return {
            "session_id": self.session_id,
            "context_id": self.context_id,
            "task_id": self.task_id,
            "consultation_id": self.consultation_id,
            "message_count": len(self.messages),
            "is_complete": self.is_complete,
            "requires_input": self.requires_input,
            "pending_actions": len(self.pending_actions),
            "text_input_enabled": self.text_input_enabled,
            "phase": self.phase,
            "checkpoint": self.checkpoint,
        }


# =============================================================================
# Interactive CLI
# =============================================================================


class InteractiveCLI:
    """Interactive CLI for testing the orchestrator via A2A protocol.

    This CLI provides a REPL (Read-Eval-Print Loop) interface for:
    - Sending messages to the orchestrator
    - Receiving and displaying streamed responses
    - Managing multi-turn conversations with context_id
    - Starting new sessions and checking status

    Usage:
        cli = InteractiveCLI(orchestrator_url="http://localhost:10000")
        await cli.run()
    """

    # Default orchestrator URL (Entry Point 1: A2A Protocol)
    host = os.environ.get("SERVER_URL", "localhost")
    port = os.environ.get("ORCHESTRATOR_AGENT_PORT", "10000")
    DEFAULT_URL = f"http://{host}:{port}"

    # Timeout for A2A calls (seconds)
    DEFAULT_TIMEOUT = 120.0

    def __init__(
        self,
        orchestrator_url: str = DEFAULT_URL,
        timeout: float = DEFAULT_TIMEOUT,
        use_colors: bool = True,
        wait_for_background: bool = True,
        wait_interval: float = 2.0,
        max_wait_seconds: float | None = 300.0,
    ):
        """Initialize the CLI.

        Args:
            orchestrator_url: Base URL of the orchestrator A2A server.
            timeout: Timeout for A2A calls in seconds.
            use_colors: Whether to use colored output (can be disabled for non-TTY).
            wait_for_background: Whether to auto-wait on long-running phases.
            wait_interval: Seconds between status polls while waiting.
            max_wait_seconds: Optional cap on wait time (None waits indefinitely).
        """
        self.orchestrator_url = orchestrator_url
        self.timeout = timeout
        self.use_colors = use_colors and sys.stdout.isatty()
        self.wait_for_background = wait_for_background
        self.wait_interval = wait_interval
        self.max_wait_seconds = max_wait_seconds
        self.state = SessionState()
        self._running = False

    def _print(self, text: str, style: str = "normal") -> None:
        """Print text with optional styling.

        Args:
            text: The text to print.
            style: One of "normal", "user", "assistant", "system", "error", "dim".
        """
        if not self.use_colors:
            print(text)
            return

        styled_text = text
        if style == "user":
            styled_text = Colors.user(text)
        elif style == "assistant":
            styled_text = Colors.assistant(text)
        elif style == "system":
            styled_text = Colors.system(text)
        elif style == "error":
            styled_text = Colors.error(text)
        elif style == "dim":
            styled_text = Colors.dim(text)

        print(styled_text)

    def _print_banner(self) -> None:
        """Print the welcome banner."""
        banner = """
================================================================================
              Travel Planner Orchestrator - Interactive CLI
================================================================================
Connected to: {url}
Type your message and press Enter to send.
Special commands: /new, /status, /history, /action, /help, /quit
================================================================================
""".format(
            url=self.orchestrator_url
        )
        self._print(banner, "system")

    def _print_help(self) -> None:
        """Print help text for available commands."""
        help_text = """
Available Commands:
  /new      - Start a new session (clears current conversation)
  /status   - Fetch workflow status from orchestrator
  /history  - Show conversation history
  /action   - Show or select available UI actions (e.g., /action 1)
  /help     - Show this help message
  /quit     - Exit the CLI

Tips:
  - Context is preserved across turns (multi-turn conversations)
  - Use /new to start fresh when testing different scenarios
  - Use /status to check workflow progress and approval checkpoints
  - When actions appear, type the number or /action <number>
"""
        self._print(help_text, "system")

    def _print_status(self) -> None:
        """Print current session status."""
        status = self.state.to_status_dict()
        self._print("\n--- Session Status ---", "system")
        for key, value in status.items():
            self._print(f"  {key}: {value}", "dim")
        self._print("----------------------\n", "system")

    def _print_history(self) -> None:
        """Print conversation history."""
        if not self.state.messages:
            self._print("No messages in conversation history.", "system")
            return

        self._print("\n--- Conversation History ---", "system")
        for i, msg in enumerate(self.state.messages, 1):
            timestamp = msg.timestamp.strftime("%H:%M:%S")
            prefix = f"[{timestamp}] "
            if msg.role == "user":
                self._print(f"{prefix}You: {msg.content}", "user")
            else:
                # Truncate long assistant messages for display
                content = msg.content
                if len(content) > 200:
                    content = content[:200] + "..."
                self._print(f"{prefix}Assistant: {content}", "assistant")
        self._print("----------------------------\n", "system")

    def _print_actions(self) -> None:
        """Print available UI actions, if any."""
        if not self.state.pending_actions:
            return

        self._print("\n--- Available Actions ---", "system")
        for idx, action in enumerate(self.state.pending_actions, 1):
            label = action.get("label", "")
            event = action.get("event", {})
            event_type = ""
            if isinstance(event, dict):
                event_type = event.get("type", "")
            if event_type:
                self._print(f"  [{idx}] {label} ({event_type})", "system")
            else:
                self._print(f"  [{idx}] {label}", "system")
        if not self.state.text_input_enabled:
            self._print("Text input is disabled for this step.", "dim")
        self._print("Select an action with /action <number> or type the label.", "dim")
        self._print("--------------------------\n", "system")

    def _resolve_action(
        self, user_input: str
    ) -> tuple[str, dict[str, Any] | None] | None:
        """Resolve user input to a UI action when available."""
        if not self.state.pending_actions:
            if user_input.strip().lower().startswith(CLICommand.ACTION.value):
                self._print("No actions available.", "dim")
            return None

        stripped = user_input.strip()
        if not stripped:
            return None

        token = stripped
        if stripped.lower().startswith(CLICommand.ACTION.value):
            token = stripped[len(CLICommand.ACTION.value) :].strip()
            if not token:
                self._print_actions()
                return None

        action = self._get_action_by_token(token)
        if action is None:
            return None

        event = action.get("event")
        if isinstance(event, dict) and event.get("type") == "free_text":
            self._print("Selected action expects text input; enter your message.", "dim")
            return None

        label = action.get("label", "")
        if not label and isinstance(event, dict):
            label = event.get("type", "")
        return label, event if isinstance(event, dict) else None

    def _get_action_by_token(self, token: str) -> dict[str, Any] | None:
        """Find action by index or label."""
        if token.isdigit():
            index = int(token) - 1
            if 0 <= index < len(self.state.pending_actions):
                return self.state.pending_actions[index]
            self._print("Invalid action number.", "error")
            return None

        for action in self.state.pending_actions:
            label = action.get("label", "")
            if label and label.lower() == token.lower():
                return action

        return None

    def _extract_metadata_payloads(
        self, raw_chunks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Extract metadata payloads from raw A2A chunks."""
        payloads: list[dict[str, Any]] = []
        for chunk in raw_chunks:
            result = chunk.get("result")
            if not isinstance(result, dict):
                continue

            candidates: list[dict[str, Any]] = []

            metadata = result.get("metadata")
            if isinstance(metadata, dict):
                candidates.append(metadata)

            status = result.get("status")
            if isinstance(status, dict):
                message = status.get("message")
                if isinstance(message, dict):
                    message_meta = message.get("metadata")
                    if isinstance(message_meta, dict):
                        candidates.append(message_meta)

            message = result.get("message")
            if isinstance(message, dict):
                message_meta = message.get("metadata")
                if isinstance(message_meta, dict):
                    candidates.append(message_meta)

            artifact = result.get("artifact")
            if isinstance(artifact, dict):
                artifact_meta = artifact.get("metadata")
                if isinstance(artifact_meta, dict):
                    candidates.append(artifact_meta)

            payloads.extend(candidates)

        return payloads

    def _update_ui_state(self, response: A2AResponse) -> None:
        """Update pending UI actions from response metadata."""
        payloads = self._extract_metadata_payloads(response.raw_chunks)
        if not payloads:
            self.state.pending_actions = []
            self.state.text_input_enabled = True
            return

        actions: list[dict[str, Any]] = []
        text_input_enabled = True
        for payload in payloads:
            actions, text_input_enabled = self._extract_actions(payload)

        self.state.pending_actions = actions
        self.state.text_input_enabled = text_input_enabled

    def _update_status_state(self, response: A2AResponse) -> None:
        """Update phase/checkpoint state from response metadata."""
        payloads = self._extract_metadata_payloads(response.raw_chunks)
        if not payloads:
            return

        phase: str | None = None
        checkpoint: str | None = None

        for payload in payloads:
            response_payload = payload.get("response")
            if isinstance(response_payload, dict):
                status = response_payload.get("status")
                if isinstance(status, dict):
                    if "phase" in status:
                        phase = status.get("phase")
                    if "checkpoint" in status:
                        checkpoint = status.get("checkpoint")
                    elif "phase" in status:
                        checkpoint = None
                data = response_payload.get("data")
                if phase is None and isinstance(data, dict) and "phase" in data:
                    phase = data.get("phase")

            status = payload.get("status")
            if isinstance(status, dict):
                if phase is None and "phase" in status:
                    phase = status.get("phase")
                if "checkpoint" in status:
                    checkpoint = status.get("checkpoint")
                elif "phase" in status and checkpoint is None:
                    checkpoint = None

        if phase is not None:
            self.state.phase = phase
        if checkpoint is not None:
            self.state.checkpoint = checkpoint

    def _extract_actions(
        self, payload: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], bool]:
        """Extract UI actions and text input flag from a payload."""
        actions: list[dict[str, Any]] = []
        text_input_enabled = True

        def _add_actions(raw_actions: Any) -> None:
            if not isinstance(raw_actions, list):
                return
            for action in raw_actions:
                if not isinstance(action, dict):
                    continue
                label = action.get("label")
                event = action.get("event")
                if isinstance(label, str) and isinstance(event, dict):
                    actions.append({"label": label, "event": event})

        response = payload.get("response")
        if isinstance(response, dict):
            ui = response.get("ui")
            if isinstance(ui, dict):
                _add_actions(ui.get("actions"))
                text_input_enabled = ui.get("text_input", True)

        error = payload.get("error")
        if isinstance(error, dict):
            retry_action = error.get("retry_action")
            if isinstance(retry_action, dict):
                _add_actions([retry_action])
            _add_actions(error.get("fallback_actions"))

        ui_payload = payload.get("ui")
        if isinstance(ui_payload, dict):
            _add_actions(ui_payload.get("actions"))
            text_input_enabled = ui_payload.get("text_input", text_input_enabled)

        return actions, text_input_enabled

    def _handle_command(self, command: CLICommand) -> bool:
        """Handle a CLI command.

        Args:
            command: The command to handle.

        Returns:
            True if the CLI should continue running, False if it should exit.
        """
        if command == CLICommand.NEW:
            self.state.reset()
            self._print("Session reset. Starting fresh conversation.", "system")
            return True

        elif command == CLICommand.HISTORY:
            self._print_history()
            return True

        elif command == CLICommand.HELP:
            self._print_help()
            return True

        elif command == CLICommand.ACTION:
            self._print_actions()
            return True

        elif command == CLICommand.QUIT:
            self._print("Goodbye!", "system")
            return False

        return True

    async def _handle_status_command(self) -> None:
        """Fetch and print workflow status from the orchestrator."""
        self._print("", "normal")
        self._print("Checking status...", "dim")
        response = await self.send_message(
            "status",
            event={"type": "status"},
            record_history=False,
        )
        if response is None:
            return
        self._print("", "normal")
        self._print("Assistant:", "assistant")
        for line in response.split("\n"):
            self._print(f"  {line}", "assistant")
        self._print("", "normal")
        self._print_actions()

    async def send_message(
        self,
        message: str,
        event: dict[str, Any] | None = None,
        *,
        record_history: bool = True,
    ) -> str | None:
        """Send a message to the orchestrator and return the response.

        Args:
            message: The user's message to send.
            event: Optional structured event for UI actions.

        Returns:
            The assistant's response text, or None if there was an error.
        """
        if record_history:
            self.state.add_user_message(message)

        async with A2AClientWrapper(timeout_seconds=self.timeout) as client:
            try:
                # Check health first
                if not await client.health_check(self.orchestrator_url):
                    self._print(
                        f"Cannot connect to orchestrator at {self.orchestrator_url}",
                        "error",
                    )
                    self._print("Make sure the orchestrator is running:", "error")
                    self._print("  uv run python src/run_orchestrator.py", "dim")
                    return None

                # Send the message
                response = await client.send_message(
                    agent_url=self.orchestrator_url,
                    message=message,
                    context_id=self.state.context_id,
                    task_id=self.state.task_id,
                    collect_raw_chunks=True,  # For extracting metadata
                    event=event,
                )

                # Update state from response
                self.state.update_from_response(response)
                if record_history:
                    self.state.add_assistant_message(response.text)
                self._update_ui_state(response)
                self._update_status_state(response)

                return response.text

            except A2AConnectionError as e:
                self._print(f"Connection error: {e}", "error")
                self._print("Is the orchestrator running?", "dim")
                return None

            except A2ATimeoutError as e:
                self._print(f"Timeout: {e}", "error")
                self._print("The request took too long. Try a simpler query.", "dim")
                return None

            except A2AClientError as e:
                self._print(f"A2A error: {e}", "error")
                return None

    def _get_prompt(self) -> str:
        """Get the input prompt string."""
        if self.state.context_id:
            # Show abbreviated context_id in prompt
            short_ctx = self.state.context_id[:8] + "..."
            return f"[{short_ctx}] You: "
        return "You: "

    def _should_wait_for_background(self) -> bool:
        """Check if we should auto-wait for background processing."""
        if not self.wait_for_background:
            return False
        phase = (self.state.phase or "").lower()
        if phase == "discovery_in_progress":
            return True
        if phase == "discovery_planning" and self.state.checkpoint != "itinerary_approval":
            return True
        if not self.state.text_input_enabled and self._has_status_action():
            return True
        return False

    def _has_status_action(self) -> bool:
        """Return True when a pending action is a status refresh."""
        for action in self.state.pending_actions:
            event = action.get("event")
            if isinstance(event, dict) and event.get("type") == "status":
                return True
        return False

    async def _wait_for_background(self) -> None:
        """Poll status until background work completes or timeout hits."""
        if not self._should_wait_for_background():
            return

        self._print("Waiting for background processing...", "dim")
        loop = asyncio.get_running_loop()
        start_time = loop.time()
        last_status: str | None = None

        while self._running and self._should_wait_for_background():
            await asyncio.sleep(self.wait_interval)
            response = await self.send_message(
                "status",
                event={"type": "status"},
                record_history=False,
            )
            if response is None:
                return

            status_line = response.strip()
            if status_line and status_line != last_status:
                self._print(f"Status: {status_line}", "dim")
                last_status = status_line

            if (
                self.max_wait_seconds is not None
                and loop.time() - start_time > self.max_wait_seconds
            ):
                self._print(
                    "Still running. Use /status to check progress or /action to continue.",
                    "dim",
                )
                return

    async def _read_input(self) -> str | None:
        """Read user input from stdin.

        Returns:
            The user's input, or None if EOF/interrupt.
        """
        try:
            # Use asyncio to allow for potential async input in the future
            loop = asyncio.get_event_loop()
            prompt = self._get_prompt()

            # Print prompt with color if enabled
            if self.use_colors:
                sys.stdout.write(Colors.GREEN + prompt + Colors.RESET)
            else:
                sys.stdout.write(prompt)
            sys.stdout.flush()

            # Read line from stdin
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:  # EOF
                return None
            return line.strip()

        except (KeyboardInterrupt, EOFError):
            return None

    async def run(self) -> None:
        """Run the interactive CLI REPL loop."""
        self._running = True
        self._print_banner()

        while self._running:
            # Read user input
            user_input = await self._read_input()

            if user_input is None:
                # EOF or interrupt
                self._print("\nGoodbye!", "system")
                break

            if not user_input:
                # Empty input, skip
                continue

            # Check for action selection
            action = self._resolve_action(user_input)
            if action:
                user_input, action_event = action
            else:
                action_event = None
                if user_input.strip().lower().startswith(CLICommand.ACTION.value):
                    continue

            # Check for CLI commands (exact matches)
            command = CLICommand.parse(user_input)
            if command and action is None:
                if command == CLICommand.STATUS:
                    await self._handle_status_command()
                    continue
                if not self._handle_command(command):
                    break
                continue

            # Send message to orchestrator
            self._print("", "normal")  # Blank line for readability
            self._print("Thinking...", "dim")

            response = await self.send_message(user_input, event=action_event)

            if response is not None:
                # Clear "Thinking..." and print response
                self._print("", "normal")
                self._print("Assistant:", "assistant")
                # Print response with proper indentation
                for line in response.split("\n"):
                    self._print(f"  {line}", "assistant")
                self._print("", "normal")
                await self._wait_for_background()
                self._print_actions()

        self._running = False

    def stop(self) -> None:
        """Stop the CLI REPL loop."""
        self._running = False


# =============================================================================
# Main Entry Point (for direct module execution)
# =============================================================================


async def main(orchestrator_url: str | None = None) -> None:
    """Main entry point for running the CLI.

    Args:
        orchestrator_url: Optional URL override for the orchestrator.
    """
    url = orchestrator_url or InteractiveCLI.DEFAULT_URL
    cli = InteractiveCLI(orchestrator_url=url)

    try:
        await cli.run()
    except KeyboardInterrupt:
        print("\nInterrupted. Goodbye!")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Interactive CLI for the Travel Planner Orchestrator"
    )
    parser.add_argument(
        "--url",
        default=None,
        help=f"Orchestrator URL (default: {InteractiveCLI.DEFAULT_URL})",
    )
    args = parser.parse_args()

    asyncio.run(main(orchestrator_url=args.url))
