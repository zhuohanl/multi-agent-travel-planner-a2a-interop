"""
Tier 2: Live integration tests for Phase 2 (Discovery).

Prerequisites:
    - At least one discovery agent running (stay, transport, poi, events, dining)

Run (only at phase milestones):
    uv run python src/run_all.py  # Terminal 1
    uv run pytest tests/integration/live/test_phase2_discovery.py -v  # Terminal 2

WARNING: These tests make real LLM calls and consume Azure OpenAI quota.
Only run at phase completion milestones, not on every ticket.
"""

import asyncio

import pytest

from src.shared.a2a.client_wrapper import A2AClientWrapper

from .conftest import AGENT_URLS, check_agent_health


DISCOVERY_AGENTS = ["stay", "transport", "poi", "events", "dining"]


class TestDiscoveryAgentCommunication:
    """Test communication with individual discovery agents."""

    @pytest.fixture
    async def a2a_client(self) -> A2AClientWrapper:
        async with A2AClientWrapper(timeout_seconds=120.0) as client:
            yield client

    @pytest.fixture
    async def available_discovery_agents(self, http_client) -> list[str]:
        """Find which discovery agents are currently running."""
        available = []
        for agent in DISCOVERY_AGENTS:
            if await check_agent_health(http_client, agent):
                available.append(agent)

        if not available:
            pytest.skip("No discovery agents running")

        return available

    @pytest.mark.asyncio
    async def test_discovery_agent_health(
        self, http_client, available_discovery_agents: list[str]
    ) -> None:
        """Test that available discovery agents are healthy."""
        assert len(available_discovery_agents) > 0
        for agent in available_discovery_agents:
            healthy = await check_agent_health(http_client, agent)
            assert healthy, f"Agent {agent} should be healthy"

    @pytest.mark.asyncio
    async def test_discovery_agent_responds(
        self, a2a_client: A2AClientWrapper, available_discovery_agents: list[str]
    ) -> None:
        """Test that available discovery agents respond to requests."""
        test_messages = {
            "stay": "Find hotels in Tokyo for March 10-17, 2026, 2 guests",
            "transport": "Find flights from San Francisco to Tokyo on March 10, 2026",
            "poi": "Find popular tourist attractions in Tokyo",
            "events": "Find events happening in Tokyo in March 2026",
            "dining": "Find highly-rated restaurants in Tokyo",
        }

        for agent_name in available_discovery_agents:
            agent_url = AGENT_URLS[agent_name]
            message = test_messages.get(agent_name, f"Search for options in Tokyo")

            response = await a2a_client.send_message(
                agent_url=agent_url,
                message=message,
            )

            assert response.text is not None, f"{agent_name} should return text"
            assert len(response.text) > 0, f"{agent_name} response should not be empty"


class TestParallelDiscovery:
    """Test parallel execution of discovery agents."""

    @pytest.fixture
    async def a2a_client(self) -> A2AClientWrapper:
        async with A2AClientWrapper(timeout_seconds=180.0) as client:
            yield client

    @pytest.mark.asyncio
    async def test_parallel_discovery_execution(
        self, a2a_client: A2AClientWrapper, http_client
    ) -> None:
        """Test parallel execution of multiple discovery agents."""
        # Find available agents
        available = []
        for agent in DISCOVERY_AGENTS:
            if await check_agent_health(http_client, agent):
                available.append(agent)

        if len(available) < 2:
            pytest.skip("Need at least 2 discovery agents for parallel test")

        test_messages = {
            "stay": "Find 3 hotel options in Tokyo",
            "transport": "Find flight options from LAX to Tokyo",
            "poi": "List top 5 attractions in Tokyo",
            "events": "Find cultural events in Tokyo",
            "dining": "Find sushi restaurants in Tokyo",
        }

        async def call_agent(agent: str):
            url = AGENT_URLS[agent]
            message = test_messages.get(agent, "Search Tokyo")
            return agent, await a2a_client.send_message(agent_url=url, message=message)

        # Execute in parallel
        tasks = [call_agent(agent) for agent in available[:3]]  # Limit to 3 for cost
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Check results
        successes = 0
        for result in results:
            if isinstance(result, Exception):
                continue
            agent, response = result
            if response.text and len(response.text) > 0:
                successes += 1

        assert successes >= 1, "At least one discovery agent should succeed"


class TestDiscoveryWithTripSpec:
    """Test discovery agents with complete TripSpec context."""

    @pytest.fixture
    async def a2a_client(self) -> A2AClientWrapper:
        async with A2AClientWrapper(timeout_seconds=120.0) as client:
            yield client

    @pytest.mark.asyncio
    async def test_stay_agent_with_full_context(
        self, a2a_client: A2AClientWrapper, http_client
    ) -> None:
        """Test stay agent with complete trip specification."""
        if not await check_agent_health(http_client, "stay"):
            pytest.skip("Stay agent not running")

        response = await a2a_client.send_message(
            agent_url=AGENT_URLS["stay"],
            message=(
                "Find hotel options for a trip to Tokyo, Japan. "
                "Check-in: March 10, 2026. Check-out: March 17, 2026. "
                "2 adults. Budget: mid-range to luxury. "
                "Prefer central location near public transit."
            ),
        )

        assert response.text is not None
        assert len(response.text) > 50  # Should have substantial response

    @pytest.mark.asyncio
    async def test_transport_agent_with_full_context(
        self, a2a_client: A2AClientWrapper, http_client
    ) -> None:
        """Test transport agent with complete trip specification."""
        if not await check_agent_health(http_client, "transport"):
            pytest.skip("Transport agent not running")

        response = await a2a_client.send_message(
            agent_url=AGENT_URLS["transport"],
            message=(
                "Find flight options from San Francisco (SFO) to Tokyo. "
                "Departure: March 10, 2026. Return: March 17, 2026. "
                "2 passengers. Economy or premium economy class."
            ),
        )

        assert response.text is not None
        assert len(response.text) > 50  # Should have substantial response


class TestQAMode:
    """
    Test Q&A mode for discovery agents.

    Per design doc (Tool Definitions section, answer_question tool):
    - Domain agents support mode='qa' for answering questions
    - Q&A mode returns text response, not structured planning output
    - Q&A mode sets is_task_complete=True

    Note: These tests are marked as expected failures until
    Q&A mode tickets (ORCH-012 to ORCH-016) are implemented.
    """

    @pytest.fixture
    async def a2a_client(self) -> A2AClientWrapper:
        async with A2AClientWrapper(timeout_seconds=120.0) as client:
            yield client

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="ORCH-012: Q&A mode for Stay agent not yet implemented")
    async def test_stay_agent_qa_mode(
        self, a2a_client: A2AClientWrapper, http_client
    ) -> None:
        """Test stay agent in Q&A mode."""
        if not await check_agent_health(http_client, "stay"):
            pytest.skip("Stay agent not running")

        # Q&A mode request format per design doc
        response = await a2a_client.send_message(
            agent_url=AGENT_URLS["stay"],
            message='{"mode": "qa", "question": "Does the Park Hyatt Tokyo have a pool?"}',
        )

        assert response.text is not None
        # Q&A mode should return direct answer, not structured output
        assert "pool" in response.text.lower() or "swimming" in response.text.lower()

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="ORCH-013: Q&A mode for Transport agent not yet implemented")
    async def test_transport_agent_qa_mode(
        self, a2a_client: A2AClientWrapper, http_client
    ) -> None:
        """Test transport agent in Q&A mode."""
        if not await check_agent_health(http_client, "transport"):
            pytest.skip("Transport agent not running")

        response = await a2a_client.send_message(
            agent_url=AGENT_URLS["transport"],
            message='{"mode": "qa", "question": "How long is the bullet train from Tokyo to Kyoto?"}',
        )

        assert response.text is not None
        # Should mention duration or Shinkansen
        assert any(
            term in response.text.lower()
            for term in ["hour", "minute", "shinkansen", "bullet"]
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="ORCH-014: Q&A mode for POI agent not yet implemented")
    async def test_poi_agent_qa_mode(
        self, a2a_client: A2AClientWrapper, http_client
    ) -> None:
        """Test POI agent in Q&A mode."""
        if not await check_agent_health(http_client, "poi"):
            pytest.skip("POI agent not running")

        response = await a2a_client.send_message(
            agent_url=AGENT_URLS["poi"],
            message='{"mode": "qa", "question": "Is the Senso-ji temple free to enter?"}',
        )

        assert response.text is not None
        assert "free" in response.text.lower() or "entrance" in response.text.lower()

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="ORCH-015: Q&A mode for Dining agent not yet implemented")
    async def test_dining_agent_qa_mode(
        self, a2a_client: A2AClientWrapper, http_client
    ) -> None:
        """Test dining agent in Q&A mode."""
        if not await check_agent_health(http_client, "dining"):
            pytest.skip("Dining agent not running")

        response = await a2a_client.send_message(
            agent_url=AGENT_URLS["dining"],
            message='{"mode": "qa", "question": "What is the dress code at fine dining restaurants in Tokyo?"}',
        )

        assert response.text is not None
        # Should mention dress code related terms
        assert any(
            term in response.text.lower()
            for term in ["dress", "casual", "formal", "attire"]
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="ORCH-016: Q&A mode for Events agent not yet implemented")
    async def test_events_agent_qa_mode(
        self, a2a_client: A2AClientWrapper, http_client
    ) -> None:
        """Test events agent in Q&A mode."""
        if not await check_agent_health(http_client, "events"):
            pytest.skip("Events agent not running")

        response = await a2a_client.send_message(
            agent_url=AGENT_URLS["events"],
            message='{"mode": "qa", "question": "Are there cherry blossom festivals in Tokyo in late March?"}',
        )

        assert response.text is not None
        # Should mention cherry blossoms or festivals
        assert any(
            term in response.text.lower()
            for term in ["cherry", "blossom", "festival", "hanami", "sakura"]
        )
