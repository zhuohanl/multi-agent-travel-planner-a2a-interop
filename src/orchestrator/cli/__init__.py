"""Interactive CLI module for end-to-end orchestrator testing.

This module provides a command-line interface for testing the orchestrator
through the A2A protocol, supporting multi-turn conversations, streaming
responses, and session management.

Components:
    InteractiveCLI: Main CLI class with REPL loop
    CLICommand: Command enum for special CLI commands
    SessionState: Tracks current session and conversation state

Usage:
    # Run the CLI
    uv run python src/run_orchestrator_cli.py

    # Or import and use programmatically
    from src.orchestrator.cli import InteractiveCLI
    cli = InteractiveCLI(orchestrator_url="http://localhost:10000")
    await cli.run()
"""

from src.orchestrator.cli.interactive_client import (
    CLICommand,
    InteractiveCLI,
    SessionState,
)

__all__ = [
    "InteractiveCLI",
    "CLICommand",
    "SessionState",
]
