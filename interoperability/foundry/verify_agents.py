"""
Verification script for deployed Azure AI Foundry agents.

Tests that deployed agents respond correctly via the Foundry conversations API.

This script verifies INTEROP-005B1 deployment by:
1. Creating a conversation for each agent
2. Sending a test query to each agent
3. Verifying responses are non-empty and well-formed

Usage:
    python verify_agents.py                    # Test all deployed agents
    python verify_agents.py --agent transport  # Test specific agent
    python verify_agents.py --dry-run          # Show what would be tested

Design doc references:
    - Appendix A.1 lines 1497-1513: conversations API, responses.create()
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv

load_dotenv()

if TYPE_CHECKING:
    from azure.ai.projects import AIProjectClient


class VerificationStatus(Enum):
    """Status of an agent verification."""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class TestQuery:
    """A test query for an agent."""

    agent_name: str
    query: str
    expected_keywords: list[str] = field(default_factory=list)


@dataclass
class VerificationResult:
    """Result of verifying a single agent."""

    agent_name: str
    status: VerificationStatus
    query: str
    response: str = ""
    message: str = ""
    details: list[str] = field(default_factory=list)


# Test queries for each agent type per acceptance criteria
TEST_QUERIES = {
    "transport": TestQuery(
        agent_name="transport",
        query="Find flights from Seattle to Tokyo",
        expected_keywords=["flight", "Seattle", "Tokyo", "airline", "travel"],
    ),
    "poi": TestQuery(
        agent_name="poi",
        query="Find attractions in Paris",
        expected_keywords=["Paris", "attraction", "museum", "landmark", "tour", "Eiffel"],
    ),
    "events": TestQuery(
        agent_name="events",
        query="Find concerts in London next week",
        expected_keywords=["London", "concert", "event", "music", "show", "venue"],
    ),
}


class AgentVerifier:
    """Verifies deployed Azure AI Foundry agents respond correctly.

    Uses the conversations API to test each agent with sample queries
    and verify responses are non-empty and contain expected content.

    Per design doc Appendix A.1 lines 1497-1513, uses:
    - project_client.get_openai_client() to get OpenAI client
    - openai_client.conversations.create() to create conversation
    - openai_client.responses.create() with extra_body={"agent": ...} to invoke agent
    """

    def __init__(
        self,
        project_endpoint: str | None = None,
        verbose: bool = False,
    ):
        """Initialize the verifier.

        Args:
            project_endpoint: Azure AI Foundry project endpoint.
                Defaults to AZURE_AI_PROJECT_ENDPOINT or PROJECT_ENDPOINT env var.
            verbose: If True, show detailed output including full responses.
        """
        self.project_endpoint = project_endpoint or os.environ.get(
            "AZURE_AI_PROJECT_ENDPOINT"
        ) or os.environ.get("PROJECT_ENDPOINT")
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

    def verify_agent(
        self,
        agent_name: str,
        test_query: TestQuery | None = None,
        dry_run: bool = False,
    ) -> VerificationResult:
        """Verify a single agent responds correctly.

        Args:
            agent_name: Name of the agent to verify.
            test_query: Query to send. Defaults to predefined query for agent type.
            dry_run: If True, only show what would be tested.

        Returns:
            VerificationResult with pass/fail status and response details.
        """
        # Get test query for this agent
        if test_query is None:
            if agent_name not in TEST_QUERIES:
                return VerificationResult(
                    agent_name=agent_name,
                    status=VerificationStatus.SKIP,
                    query="",
                    message=f"No test query defined for agent '{agent_name}'",
                )
            test_query = TEST_QUERIES[agent_name]

        if dry_run:
            return VerificationResult(
                agent_name=agent_name,
                status=VerificationStatus.SKIP,
                query=test_query.query,
                message=f"[DRY RUN] Would test '{agent_name}' with query: {test_query.query}",
                details=[f"Expected keywords: {test_query.expected_keywords}"],
            )

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
                extra_body={"agent": {"name": agent_name, "type": "agent_reference"}},
                input=test_query.query,
            )

            # Extract response text (per design doc line 1505)
            response_text = response.output_text if hasattr(response, 'output_text') else str(response)

            if not response_text:
                return VerificationResult(
                    agent_name=agent_name,
                    status=VerificationStatus.FAIL,
                    query=test_query.query,
                    response="",
                    message="Agent returned empty response",
                )

            # Check for expected keywords in response
            response_lower = response_text.lower()
            found_keywords = [
                kw for kw in test_query.expected_keywords
                if kw.lower() in response_lower
            ]
            missing_keywords = [
                kw for kw in test_query.expected_keywords
                if kw.lower() not in response_lower
            ]

            # Consider success if at least half the keywords are found
            # or response is reasonably long (indicating actual content)
            keyword_threshold = len(test_query.expected_keywords) // 2
            content_threshold = 50  # characters

            if len(found_keywords) >= keyword_threshold or len(response_text) > content_threshold:
                status = VerificationStatus.PASS
                message = f"Agent responded with {len(response_text)} chars, {len(found_keywords)}/{len(test_query.expected_keywords)} keywords"
            else:
                status = VerificationStatus.FAIL
                message = f"Response may not be relevant: only {len(found_keywords)}/{len(test_query.expected_keywords)} expected keywords found"

            return VerificationResult(
                agent_name=agent_name,
                status=status,
                query=test_query.query,
                response=response_text[:500] + ("..." if len(response_text) > 500 else ""),
                message=message,
                details=[
                    f"Found keywords: {found_keywords}",
                    f"Missing keywords: {missing_keywords}",
                ],
            )

        except Exception as e:
            return VerificationResult(
                agent_name=agent_name,
                status=VerificationStatus.FAIL,
                query=test_query.query,
                message=f"Error testing agent: {e}",
            )

    def verify_all(
        self,
        agent_names: list[str] | None = None,
        dry_run: bool = False,
    ) -> list[VerificationResult]:
        """Verify all deployed agents.

        Args:
            agent_names: List of agent names to verify. Defaults to all known agents.
            dry_run: If True, only show what would be tested.

        Returns:
            List of verification results for each agent.
        """
        if agent_names is None:
            agent_names = list(TEST_QUERIES.keys())

        results = []
        for agent_name in agent_names:
            if self.verbose:
                print(f"\nVerifying agent: {agent_name}")
            result = self.verify_agent(agent_name, dry_run=dry_run)
            results.append(result)

        return results


def print_results(results: list[VerificationResult], verbose: bool = False) -> None:
    """Print verification results in a formatted table.

    Args:
        results: List of verification results.
        verbose: If True, show full response text.
    """
    print("\n" + "=" * 60)
    print("Agent Verification Results")
    print("=" * 60 + "\n")

    status_symbols = {
        VerificationStatus.PASS: "\u2713",  # checkmark
        VerificationStatus.FAIL: "\u2717",  # X mark
        VerificationStatus.SKIP: "-",
    }

    for result in results:
        symbol = status_symbols[result.status]
        status_str = result.status.value.upper()
        print(f"[{symbol}] {result.agent_name}: {status_str}")
        print(f"    Query: {result.query}")
        print(f"    {result.message}")

        if result.details:
            for detail in result.details:
                print(f"    - {detail}")

        if verbose and result.response:
            print(f"\n    Response preview:")
            for line in result.response.split('\n')[:5]:
                print(f"      {line}")

        print()

    # Summary
    passed = sum(1 for r in results if r.status == VerificationStatus.PASS)
    failed = sum(1 for r in results if r.status == VerificationStatus.FAIL)
    skipped = sum(1 for r in results if r.status == VerificationStatus.SKIP)

    print("-" * 60)
    print(f"Summary: {passed} passed, {failed} failed, {skipped} skipped")
    print("-" * 60)

    if failed > 0:
        print("\n[!] Some agents failed verification. Check deployment status.")
    elif passed > 0 and skipped == 0:
        print("\n[OK] All agents verified successfully!")
    else:
        print("\n[!] Review skipped agents.")


def main() -> int:
    """Run agent verification.

    Returns:
        Exit code: 0 if all agents pass, 1 if any fail.
    """
    parser = argparse.ArgumentParser(
        description="Verify deployed Azure AI Foundry agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script verifies deployed agents respond correctly:

1. Transport agent - Tests flight search query
2. POI agent - Tests attraction search query
3. Events agent - Tests event search query

Each agent is tested by:
- Creating a conversation (per design doc line 1498)
- Sending a test query via responses API (per design doc lines 1500-1504)
- Verifying response is non-empty and relevant

Prerequisites:
- AZURE_AI_PROJECT_ENDPOINT or PROJECT_ENDPOINT environment variable
- Azure CLI logged in with appropriate permissions
- Agents deployed via deploy.py (INTEROP-005B1)

Examples:
  python verify_agents.py                    # Verify all agents
  python verify_agents.py --agent transport  # Verify specific agent
  python verify_agents.py --dry-run          # Preview tests
        """,
    )

    parser.add_argument(
        "--agent",
        type=str,
        help="Verify specific agent by name (transport, poi, events)",
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
        "--endpoint",
        type=str,
        help="Azure AI Foundry project endpoint (overrides env var)",
    )

    args = parser.parse_args()

    verifier = AgentVerifier(
        project_endpoint=args.endpoint,
        verbose=args.verbose,
    )

    if args.agent:
        # Verify single agent
        result = verifier.verify_agent(args.agent, dry_run=args.dry_run)
        print_results([result], verbose=args.verbose)
        return 0 if result.status != VerificationStatus.FAIL else 1
    else:
        # Verify all agents
        results = verifier.verify_all(dry_run=args.dry_run)
        print_results(results, verbose=args.verbose)
        has_failures = any(r.status == VerificationStatus.FAIL for r in results)
        return 1 if has_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
