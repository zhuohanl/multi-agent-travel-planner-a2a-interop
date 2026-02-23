"""
Tier 1: Mock discovery flow protocol tests.

Tests parallel discovery agent communication using mock responses.
Run on EVERY ticket to verify protocol correctness.

Run: uv run pytest tests/integration/mock/test_discovery_protocol.py -v
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from .conftest import MockA2AResponseFactory


DISCOVERY_AGENTS = ["stay", "transport", "poi", "events", "dining"]
DISCOVERY_AGENT_PORTS = {
    "stay": 10009,
    "transport": 10010,
    "poi": 10008,
    "events": 10011,
    "dining": 10017,
}


class TestDiscoveryProtocol:
    """Test discovery flow protocol with mocks."""

    @pytest.mark.asyncio
    async def test_parallel_discovery_responses(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test handling responses from multiple discovery agents."""
        # Configure responses for each discovery agent
        for agent in DISCOVERY_AGENTS:
            port = DISCOVERY_AGENT_PORTS[agent]
            mock_a2a_client.configure_response(
                f"http://localhost:{port}",
                mock_response_factory.discovery_agent_results(agent),
            )

        # Simulate parallel calls
        responses = []
        for agent in DISCOVERY_AGENTS:
            port = DISCOVERY_AGENT_PORTS[agent]
            response = await mock_a2a_client.send_message(
                agent_url=f"http://localhost:{port}",
                message=f"Search {agent} options in Tokyo",
            )
            responses.append((agent, response))

        # All should complete successfully
        assert all(r.is_complete for _, r in responses)
        assert len(responses) == 5

    @pytest.mark.asyncio
    async def test_partial_discovery_failure(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test handling when some discovery agents fail."""
        # Stay succeeds
        mock_a2a_client.configure_response(
            "http://localhost:10009",
            mock_response_factory.stay_agent_results(),
        )

        # Transport fails
        mock_a2a_client.configure_response(
            "http://localhost:10010",
            mock_response_factory.agent_error("Search timeout"),
        )

        # Stay succeeds
        stay_response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10009",
            message="Find hotels in Tokyo",
        )
        assert stay_response.is_complete is True
        assert "hotels" in stay_response.text.lower()

        # Transport fails
        transport_response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10010",
            message="Find flights to Tokyo",
        )
        assert transport_response.is_complete is False
        assert "timeout" in transport_response.text.lower()

    @pytest.mark.asyncio
    async def test_discovery_agent_context_isolation(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that each discovery agent gets its own context."""
        # Configure different responses for each agent
        mock_a2a_client.configure_response(
            "http://localhost:10009",
            mock_response_factory.stay_agent_results(),
        )
        mock_a2a_client.configure_response(
            "http://localhost:10010",
            mock_response_factory.transport_agent_results(),
        )

        stay_response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10009",
            message="Find hotels",
        )
        transport_response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10010",
            message="Find flights",
        )

        # Each agent should have its own context_id
        assert stay_response.context_id != transport_response.context_id
        assert stay_response.context_id == "ctx_stay_001"
        assert transport_response.context_id == "ctx_transport_001"


class TestParallelDiscovery:
    """Test parallel execution patterns for discovery."""

    @pytest.mark.asyncio
    async def test_concurrent_agent_calls(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test that multiple agents can be called concurrently."""
        # Configure all agents
        for agent in DISCOVERY_AGENTS:
            port = DISCOVERY_AGENT_PORTS[agent]
            mock_a2a_client.configure_response(
                f"http://localhost:{port}",
                mock_response_factory.discovery_agent_results(agent),
            )

        # Create concurrent tasks
        async def call_agent(agent: str) -> tuple[str, object]:
            port = DISCOVERY_AGENT_PORTS[agent]
            response = await mock_a2a_client.send_message(
                agent_url=f"http://localhost:{port}",
                message=f"Search {agent}",
            )
            return agent, response

        # Execute all calls concurrently
        tasks = [call_agent(agent) for agent in DISCOVERY_AGENTS]
        results = await asyncio.gather(*tasks)

        # All should complete
        assert len(results) == 5
        for agent, response in results:
            assert response.is_complete is True
            assert response.context_id is not None

    @pytest.mark.asyncio
    async def test_partial_timeout_handling(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test handling when some agents timeout in parallel execution."""
        # Most agents succeed
        for agent in ["stay", "poi", "dining"]:
            port = DISCOVERY_AGENT_PORTS[agent]
            mock_a2a_client.configure_response(
                f"http://localhost:{port}",
                mock_response_factory.discovery_agent_results(agent),
            )

        # Some agents timeout
        for agent in ["transport", "events"]:
            port = DISCOVERY_AGENT_PORTS[agent]
            mock_a2a_client.configure_response(
                f"http://localhost:{port}",
                mock_response_factory.agent_timeout(),
            )

        results = {}
        for agent in DISCOVERY_AGENTS:
            port = DISCOVERY_AGENT_PORTS[agent]
            response = await mock_a2a_client.send_message(
                agent_url=f"http://localhost:{port}",
                message=f"Search {agent}",
            )
            results[agent] = response

        # Check successful agents
        assert results["stay"].is_complete is True
        assert results["poi"].is_complete is True
        assert results["dining"].is_complete is True

        # Check failed agents
        assert results["transport"].is_complete is False
        assert results["events"].is_complete is False


class TestDiscoveryResultAggregation:
    """Test aggregation of discovery results."""

    @pytest.mark.asyncio
    async def test_aggregate_successful_results(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test aggregating results from successful discovery agents."""
        mock_a2a_client.configure_response(
            "http://localhost:10009",
            mock_response_factory.stay_agent_results(),
        )
        mock_a2a_client.configure_response(
            "http://localhost:10010",
            mock_response_factory.transport_agent_results(),
        )

        stay = await mock_a2a_client.send_message(
            agent_url="http://localhost:10009",
            message="Find hotels",
        )
        transport = await mock_a2a_client.send_message(
            agent_url="http://localhost:10010",
            message="Find flights",
        )

        # Verify results contain expected data
        assert "hotels" in stay.text.lower() or "Park Hyatt" in stay.text
        assert "flights" in transport.text.lower() or "JAL" in transport.text

    @pytest.mark.asyncio
    async def test_handle_mixed_success_failure(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test handling mix of successful and failed discovery results."""
        # Configure mixed results
        mock_a2a_client.configure_response(
            "http://localhost:10009",  # stay - success
            mock_response_factory.stay_agent_results(),
        )
        mock_a2a_client.configure_response(
            "http://localhost:10010",  # transport - error
            mock_response_factory.agent_error("Service unavailable"),
        )
        mock_a2a_client.configure_response(
            "http://localhost:10008",  # poi - success
            mock_response_factory.discovery_agent_results("poi"),
        )

        results = {
            "stay": await mock_a2a_client.send_message(
                "http://localhost:10009", "Find hotels"
            ),
            "transport": await mock_a2a_client.send_message(
                "http://localhost:10010", "Find flights"
            ),
            "poi": await mock_a2a_client.send_message(
                "http://localhost:10008", "Find attractions"
            ),
        }

        # Count successes and failures
        successes = sum(1 for r in results.values() if r.is_complete)
        failures = sum(1 for r in results.values() if not r.is_complete)

        assert successes == 2
        assert failures == 1
        assert results["transport"].is_complete is False
