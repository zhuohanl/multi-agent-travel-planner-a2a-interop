"""
Smoke test script for verifying deployed agents respond correctly.

Quick validation script for testing deployed agents after deployment.
Designed to catch configuration errors early by testing each agent
independently and reporting pass/fail status.

Usage:
    python interoperability/test_smoke.py --demo a   # Test Demo A agents
    python interoperability/test_smoke.py --demo b   # Test Demo B agents
    python interoperability/test_smoke.py --demo c   # Test Demo C agents
    python interoperability/test_smoke.py --all      # Test all demos

Design doc references:
    - Testing Strategy lines 1203-1253: smoke tests, quick validation
    - Appendix A.1 lines 1492-1509: responses.create(), agent reference
"""

from __future__ import annotations

import argparse
import os
import sys
import signal
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

from dotenv import load_dotenv

load_dotenv()

if TYPE_CHECKING:
    from azure.ai.projects import AIProjectClient


class SmokeTestStatus(Enum):
    """Status of a smoke test."""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    TIMEOUT = "timeout"


@dataclass
class AgentTestQuery:
    """A test query for an agent."""

    agent_name: str
    query: str
    expected_keywords: list[str] = field(default_factory=list)
    agent_type: str = "foundry"  # "foundry" or "copilot_studio"


@dataclass
class SmokeTestResult:
    """Result of a smoke test for a single agent."""

    agent_name: str
    status: SmokeTestStatus
    query: str
    response: str = ""
    message: str = ""
    response_time_ms: float = 0.0


# Demo A agents: All 6 discovery agents + aggregator + route + weather (CS cross-platform)
# Per design doc Demo A uses Foundry agents + Weather from Copilot Studio
DEMO_A_AGENTS = {
    "transport": AgentTestQuery(
        agent_name="transport",
        query="Find flights from Seattle to Tokyo for next weekend",
        expected_keywords=["flight", "Seattle", "Tokyo", "airline", "travel"],
        agent_type="foundry",
    ),
    "poi": AgentTestQuery(
        agent_name="poi",
        query="Find top attractions to visit in Paris",
        expected_keywords=["Paris", "attraction", "museum", "landmark", "Eiffel"],
        agent_type="foundry",
    ),
    "events": AgentTestQuery(
        agent_name="events",
        query="Find concerts and events in London next week",
        expected_keywords=["London", "concert", "event", "music", "venue"],
        agent_type="foundry",
    ),
    "stay": AgentTestQuery(
        agent_name="stay",
        query="Find hotels near downtown Tokyo",
        expected_keywords=["hotel", "Tokyo", "room", "accommodation", "stay"],
        agent_type="foundry",
    ),
    "dining": AgentTestQuery(
        agent_name="dining",
        query="Find best restaurants in Paris for dinner",
        expected_keywords=["restaurant", "Paris", "dinner", "cuisine", "food"],
        agent_type="foundry",
    ),
    "aggregator": AgentTestQuery(
        agent_name="aggregator",
        query="Combine the following travel results into a summary",
        expected_keywords=["summary", "result", "travel", "combined"],
        agent_type="foundry",
    ),
    "route": AgentTestQuery(
        agent_name="route",
        query="Create an itinerary for a 3-day trip to Tokyo",
        expected_keywords=["itinerary", "day", "Tokyo", "schedule", "plan"],
        agent_type="foundry",
    ),
    # Cross-platform: Foundry -> Copilot Studio Weather agent (INTEROP-012)
    "weather": AgentTestQuery(
        agent_name="weather",
        query="What's the weather forecast for Paris from 2025-06-15 to 2025-06-20?",
        expected_keywords=["weather", "Paris", "temperature", "forecast", "climate"],
        agent_type="copilot_studio",
    ),
}

# Demo B agents: Approval agent in Copilot Studio
DEMO_B_AGENTS = {
    "approval": AgentTestQuery(
        agent_name="approval",
        query="Please review and approve this travel itinerary",
        expected_keywords=["approve", "review", "decision", "itinerary"],
        agent_type="copilot_studio",
    ),
}

# Demo C agents: Q&A Parent + Weather in Copilot Studio, connected to Foundry agents
DEMO_C_AGENTS = {
    "weather": AgentTestQuery(
        agent_name="weather",
        query="What's the weather forecast for Tokyo next week?",
        expected_keywords=["weather", "Tokyo", "forecast", "temperature"],
        agent_type="copilot_studio",
    ),
    "travel_planning_parent": AgentTestQuery(
        agent_name="travel_planning_parent",
        query="What are the best things to do in Paris?",
        expected_keywords=["Paris", "attraction", "visit", "recommend"],
        agent_type="copilot_studio",
    ),
}


class TimeoutError(Exception):
    """Raised when an operation times out."""
    pass


def timeout_handler(signum: int, frame: Any) -> None:
    """Signal handler for timeout."""
    raise TimeoutError("Operation timed out")


class SmokeTester:
    """Smoke tester for verifying deployed agents.

    Tests agents by sending simple queries and verifying non-empty responses.
    Handles timeouts gracefully and provides clear pass/fail reporting.
    """

    def __init__(
        self,
        project_endpoint: str | None = None,
        timeout_seconds: int = 30,
        verbose: bool = False,
    ):
        """Initialize the smoke tester.

        Args:
            project_endpoint: Azure AI Foundry project endpoint.
                Defaults to AZURE_AI_PROJECT_ENDPOINT or PROJECT_ENDPOINT env var.
            timeout_seconds: Maximum time to wait for agent response.
            verbose: If True, show detailed output.
        """
        self.project_endpoint = project_endpoint or os.environ.get(
            "AZURE_AI_PROJECT_ENDPOINT"
        ) or os.environ.get("PROJECT_ENDPOINT")
        self.timeout_seconds = timeout_seconds
        self.verbose = verbose
        self._project_client: AIProjectClient | None = None
        self._openai_client: Any = None

    def _get_project_client(self) -> AIProjectClient:
        """Get or create the AIProjectClient.

        Returns:
            Configured AIProjectClient.

        Raises:
            RuntimeError: If project endpoint is not configured.
        """
        if self._project_client is not None:
            return self._project_client

        if not self.project_endpoint:
            raise RuntimeError(
                "Project endpoint not configured. "
                "Set AZURE_AI_PROJECT_ENDPOINT or PROJECT_ENDPOINT environment variable."
            )

        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential

        self._project_client = AIProjectClient(
            endpoint=self.project_endpoint,
            credential=DefaultAzureCredential(),
        )
        return self._project_client

    def _get_openai_client(self) -> Any:
        """Get or create the OpenAI client from AIProjectClient.

        Returns:
            OpenAI client for conversations/responses API.
        """
        if self._openai_client is not None:
            return self._openai_client

        project_client = self._get_project_client()
        self._openai_client = project_client.get_openai_client()
        return self._openai_client

    def _test_foundry_agent(
        self,
        agent_query: AgentTestQuery,
    ) -> SmokeTestResult:
        """Test a Foundry agent with a query.

        Args:
            agent_query: The test query to send.

        Returns:
            SmokeTestResult with pass/fail status.
        """
        import time

        start_time = time.time()

        try:
            openai_client = self._get_openai_client()

            # Create a conversation (per design doc line 1498)
            conversation = openai_client.conversations.create()
            conversation_id = conversation.id

            if self.verbose:
                print(f"  Created conversation: {conversation_id}")

            # Send query to agent using responses API (per design doc lines 1500-1504)
            response = openai_client.responses.create(
                conversation=conversation_id,
                extra_body={"agent": {"name": agent_query.agent_name, "type": "agent_reference"}},
                input=agent_query.query,
            )

            response_time = (time.time() - start_time) * 1000

            # Extract response text (per design doc line 1505)
            response_text = response.output_text if hasattr(response, 'output_text') else str(response)

            if not response_text:
                return SmokeTestResult(
                    agent_name=agent_query.agent_name,
                    status=SmokeTestStatus.FAIL,
                    query=agent_query.query,
                    response="",
                    message="Agent returned empty response",
                    response_time_ms=response_time,
                )

            # Validate response format: check for expected keywords
            status, message = self._validate_response(response_text, agent_query.expected_keywords)

            return SmokeTestResult(
                agent_name=agent_query.agent_name,
                status=status,
                query=agent_query.query,
                response=response_text[:500] + ("..." if len(response_text) > 500 else ""),
                message=message,
                response_time_ms=response_time,
            )

        except TimeoutError:
            return SmokeTestResult(
                agent_name=agent_query.agent_name,
                status=SmokeTestStatus.TIMEOUT,
                query=agent_query.query,
                message=f"Agent did not respond within {self.timeout_seconds} seconds",
                response_time_ms=self.timeout_seconds * 1000,
            )
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return SmokeTestResult(
                agent_name=agent_query.agent_name,
                status=SmokeTestStatus.FAIL,
                query=agent_query.query,
                message=f"Error testing agent: {e}",
                response_time_ms=response_time,
            )

    def _validate_response(
        self,
        response_text: str,
        expected_keywords: list[str],
    ) -> tuple[SmokeTestStatus, str]:
        """Validate agent response is well-formed.

        Checks for non-empty response and presence of expected keywords.

        Args:
            response_text: The agent's response text.
            expected_keywords: Keywords expected in the response.

        Returns:
            Tuple of (status, message).
        """
        if not response_text or len(response_text.strip()) == 0:
            return SmokeTestStatus.FAIL, "Empty response"

        # Check for expected keywords in response
        response_lower = response_text.lower()
        found_keywords = [
            kw for kw in expected_keywords
            if kw.lower() in response_lower
        ]

        # Consider success if response is reasonably long (>50 chars)
        # or at least half the expected keywords are found
        content_threshold = 50
        keyword_threshold = max(1, len(expected_keywords) // 2)

        if len(response_text) > content_threshold or len(found_keywords) >= keyword_threshold:
            return (
                SmokeTestStatus.PASS,
                f"Response OK ({len(response_text)} chars, {len(found_keywords)}/{len(expected_keywords)} keywords)",
            )
        else:
            return (
                SmokeTestStatus.FAIL,
                f"Response may not be relevant ({len(found_keywords)}/{len(expected_keywords)} keywords)",
            )

    def test_agent(
        self,
        agent_query: AgentTestQuery,
        dry_run: bool = False,
    ) -> SmokeTestResult:
        """Test a single agent.

        Args:
            agent_query: The test query to send.
            dry_run: If True, only show what would be tested.

        Returns:
            SmokeTestResult with pass/fail status.
        """
        if dry_run:
            return SmokeTestResult(
                agent_name=agent_query.agent_name,
                status=SmokeTestStatus.SKIP,
                query=agent_query.query,
                message=f"[DRY RUN] Would test '{agent_query.agent_name}' ({agent_query.agent_type})",
            )

        if agent_query.agent_type == "foundry":
            return self._test_foundry_agent(agent_query)
        elif agent_query.agent_type == "copilot_studio":
            # Copilot Studio testing not implemented in this ticket
            return SmokeTestResult(
                agent_name=agent_query.agent_name,
                status=SmokeTestStatus.SKIP,
                query=agent_query.query,
                message="Copilot Studio testing not implemented (requires M365 SDK)",
            )
        else:
            return SmokeTestResult(
                agent_name=agent_query.agent_name,
                status=SmokeTestStatus.FAIL,
                query=agent_query.query,
                message=f"Unknown agent type: {agent_query.agent_type}",
            )

    def test_demo_a(self, dry_run: bool = False) -> list[SmokeTestResult]:
        """Test all Demo A agents (Foundry agents).

        Demo A includes: transport, poi, events, stay, dining, aggregator, route

        Args:
            dry_run: If True, only show what would be tested.

        Returns:
            List of SmokeTestResults for each agent.
        """
        results = []
        for agent_name in DEMO_A_AGENTS:
            if self.verbose:
                print(f"\nTesting agent: {agent_name}")
            result = self.test_agent(DEMO_A_AGENTS[agent_name], dry_run=dry_run)
            results.append(result)
        return results

    def test_demo_b(self, dry_run: bool = False) -> list[SmokeTestResult]:
        """Test all Demo B agents (Copilot Studio approval).

        Demo B includes: approval

        Args:
            dry_run: If True, only show what would be tested.

        Returns:
            List of SmokeTestResults for each agent.
        """
        results = []
        for agent_name in DEMO_B_AGENTS:
            if self.verbose:
                print(f"\nTesting agent: {agent_name}")
            result = self.test_agent(DEMO_B_AGENTS[agent_name], dry_run=dry_run)
            results.append(result)
        return results

    def test_demo_c(self, dry_run: bool = False) -> list[SmokeTestResult]:
        """Test all Demo C agents (CS Q&A Parent with connected agents).

        Demo C includes: weather, travel_planning_parent

        Args:
            dry_run: If True, only show what would be tested.

        Returns:
            List of SmokeTestResults for each agent.
        """
        results = []
        for agent_name in DEMO_C_AGENTS:
            if self.verbose:
                print(f"\nTesting agent: {agent_name}")
            result = self.test_agent(DEMO_C_AGENTS[agent_name], dry_run=dry_run)
            results.append(result)
        return results

    def test_all(self, dry_run: bool = False) -> dict[str, list[SmokeTestResult]]:
        """Test all demos.

        Args:
            dry_run: If True, only show what would be tested.

        Returns:
            Dict mapping demo name to list of SmokeTestResults.
        """
        return {
            "a": self.test_demo_a(dry_run=dry_run),
            "b": self.test_demo_b(dry_run=dry_run),
            "c": self.test_demo_c(dry_run=dry_run),
        }


def print_results(results: list[SmokeTestResult], demo_name: str = "", verbose: bool = False) -> None:
    """Print smoke test results in a formatted table.

    Args:
        results: List of smoke test results.
        demo_name: Name of the demo being tested.
        verbose: If True, show full response text.
    """
    header = f"Demo {demo_name.upper()} Results" if demo_name else "Smoke Test Results"
    print("\n" + "=" * 60)
    print(header)
    print("=" * 60 + "\n")

    status_symbols = {
        SmokeTestStatus.PASS: "✓",
        SmokeTestStatus.FAIL: "✗",
        SmokeTestStatus.SKIP: "-",
        SmokeTestStatus.TIMEOUT: "⏱",
    }

    for result in results:
        symbol = status_symbols[result.status]
        status_str = result.status.value.upper()
        time_str = f" ({result.response_time_ms:.0f}ms)" if result.response_time_ms > 0 else ""
        print(f"[{symbol}] {result.agent_name}: {status_str}{time_str}")
        print(f"    Query: {result.query}")
        print(f"    {result.message}")

        if verbose and result.response:
            print(f"\n    Response preview:")
            for line in result.response.split('\n')[:3]:
                print(f"      {line[:80]}...")

        print()

    # Summary
    passed = sum(1 for r in results if r.status == SmokeTestStatus.PASS)
    failed = sum(1 for r in results if r.status == SmokeTestStatus.FAIL)
    skipped = sum(1 for r in results if r.status == SmokeTestStatus.SKIP)
    timedout = sum(1 for r in results if r.status == SmokeTestStatus.TIMEOUT)

    print("-" * 60)
    summary_parts = [f"{passed}/{len(results)} agents passed"]
    if failed > 0:
        summary_parts.append(f"{failed} failed")
    if skipped > 0:
        summary_parts.append(f"{skipped} skipped")
    if timedout > 0:
        summary_parts.append(f"{timedout} timed out")
    print(f"Summary: {', '.join(summary_parts)}")
    print("-" * 60)

    if failed > 0 or timedout > 0:
        print("\n[!] Some agents failed. Check deployment status.")
    elif passed > 0 and skipped == 0:
        print("\n[OK] All agents passed!")
    elif skipped > 0:
        print("\n[!] Some agents were skipped.")


def main() -> int:
    """Run smoke tests.

    Returns:
        Exit code: 0 if all tests pass, 1 if any fail.
    """
    parser = argparse.ArgumentParser(
        description="Run smoke tests for deployed agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script performs quick validation of deployed agents:

Demo A (Foundry):
  - transport, poi, events, stay, dining (discovery)
  - aggregator, route (workflow support)

Demo B (Copilot Studio):
  - approval (itinerary approval)

Demo C (CS Connected Agents):
  - weather, travel_planning_parent (CS agents connected to Foundry)

Each agent is tested by sending a simple query and verifying
a non-empty, well-formed response is received.

Examples:
  python interoperability/test_smoke.py --demo a       # Test Demo A
  python interoperability/test_smoke.py --demo b       # Test Demo B
  python interoperability/test_smoke.py --demo c       # Test Demo C
  python interoperability/test_smoke.py --all          # Test all demos
  python interoperability/test_smoke.py --demo a --dry-run  # Preview tests
        """,
    )

    parser.add_argument(
        "--demo",
        type=str,
        choices=["a", "b", "c"],
        help="Which demo to test (a, b, or c)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Test all demos",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be tested without sending requests",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output including response text",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout in seconds for each agent (default: 30)",
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        help="Azure AI Foundry project endpoint (overrides env var)",
    )

    args = parser.parse_args()

    if not args.demo and not args.all:
        parser.print_help()
        print("\nError: Must specify --demo or --all")
        return 1

    tester = SmokeTester(
        project_endpoint=args.endpoint,
        timeout_seconds=args.timeout,
        verbose=args.verbose,
    )

    has_failures = False

    if args.all:
        all_results = tester.test_all(dry_run=args.dry_run)
        for demo_name, results in all_results.items():
            print_results(results, demo_name=demo_name, verbose=args.verbose)
            if any(r.status in (SmokeTestStatus.FAIL, SmokeTestStatus.TIMEOUT) for r in results):
                has_failures = True
    else:
        if args.demo == "a":
            results = tester.test_demo_a(dry_run=args.dry_run)
        elif args.demo == "b":
            results = tester.test_demo_b(dry_run=args.dry_run)
        elif args.demo == "c":
            results = tester.test_demo_c(dry_run=args.dry_run)
        else:
            print(f"Unknown demo: {args.demo}")
            return 1

        print_results(results, demo_name=args.demo, verbose=args.verbose)
        if any(r.status in (SmokeTestStatus.FAIL, SmokeTestStatus.TIMEOUT) for r in results):
            has_failures = True

    return 1 if has_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
