#!/usr/bin/env python
"""Entry point script for the Orchestrator Interactive CLI.

This script starts an interactive command-line interface for testing
the orchestrator via the A2A protocol. It provides a REPL loop for
multi-turn conversations with full context preservation.

Architecture (per design doc):
- Connects to Entry Point 1 (A2A Protocol) at the orchestrator server
- Uses A2AClientWrapper for protocol handling
- Maintains session state (context_id, task_id) across turns
- Supports special commands: /new, /status, /history, /help, /quit

Prerequisites:
    The orchestrator server must be running:
        uv run python src/run_orchestrator.py

Configuration (environment variables):
    SERVER_URL: Server host (default: localhost)
    ORCHESTRATOR_PORT: Server port (default: 10000)
    CLI_TIMEOUT: Request timeout in seconds (default: 120)

Usage:
    # Start with default configuration
    uv run python src/run_orchestrator_cli.py

    # With custom URL
    uv run python src/run_orchestrator_cli.py --url http://localhost:8000

    # With verbose logging
    uv run python src/run_orchestrator_cli.py --verbose

Example session:
    $ uv run python src/run_orchestrator_cli.py

    ================================================================================
                  Travel Planner Orchestrator - Interactive CLI
    ================================================================================
    Connected to: http://localhost:10000

    You: Plan a trip to Tokyo for 5 days

    Thinking...

    Assistant:
      I'd be happy to help you plan a trip to Tokyo! Let me ask a few questions
      to create the perfect itinerary for you...
      ...

    You: /status
    --- Session Status ---
      session_id: None
      context_id: ctx_abc123...
      ...

    You: /quit
    Goodbye!
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def get_default_url() -> str:
    """Get the default orchestrator URL from environment variables."""
    host = os.environ.get("SERVER_URL", "localhost")
    port = os.environ.get("ORCHESTRATOR_AGENT_PORT", "10000")
    return f"http://{host}:{port}"


def get_default_timeout() -> float:
    """Get the default timeout from environment variables."""
    return float(os.environ.get("CLI_TIMEOUT", "120"))


def configure_logging(verbose: bool = False) -> None:
    """Configure logging for the CLI.

    Args:
        verbose: If True, enable DEBUG level logging.
    """
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


async def run_cli(url: str, timeout: float) -> None:
    """Run the interactive CLI.

    Args:
        url: The orchestrator URL to connect to.
        timeout: Request timeout in seconds.
    """
    # Import here to avoid import errors if dependencies are missing
    from src.orchestrator.cli import InteractiveCLI

    cli = InteractiveCLI(orchestrator_url=url, timeout=timeout)

    try:
        await cli.run()
    except KeyboardInterrupt:
        print("\nInterrupted. Goodbye!")


def main() -> None:
    """Main entry point for the CLI script."""
    parser = argparse.ArgumentParser(
        description="Interactive CLI for the Travel Planner Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Start with default settings
    uv run python src/run_orchestrator_cli.py

    # Connect to custom URL
    uv run python src/run_orchestrator_cli.py --url http://localhost:8000

    # Enable verbose logging
    uv run python src/run_orchestrator_cli.py --verbose

Special Commands:
    /new      - Start a new session
    /status   - Show current session state
    /history  - Show conversation history
    /action   - Show or select available UI actions
    /help     - Show help
    /quit     - Exit the CLI
""",
    )

    parser.add_argument(
        "--url",
        default=None,
        help=f"Orchestrator URL (default: {get_default_url()})",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help=f"Request timeout in seconds (default: {get_default_timeout()})",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging (DEBUG level)",
    )

    args = parser.parse_args()

    # Configure logging
    configure_logging(verbose=args.verbose)

    # Get configuration
    url = args.url or get_default_url()
    timeout = args.timeout or get_default_timeout()

    # Check if orchestrator might be running
    logger = logging.getLogger(__name__)
    logger.info("Connecting to orchestrator at %s", url)
    logger.info("Request timeout: %s seconds", timeout)

    # Run the CLI
    try:
        asyncio.run(run_cli(url=url, timeout=timeout))
    except KeyboardInterrupt:
        print("\nInterrupted. Goodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
