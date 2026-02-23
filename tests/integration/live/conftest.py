"""
Live test fixtures for real agent integration tests.

These fixtures connect to actual running agents and should only
be used at phase completion milestones to control LLM costs.

Prerequisites:
    - Start all agents: uv run python src/run_all.py
"""

import asyncio
import os

import httpx
import pytest
from dotenv import load_dotenv

load_dotenv()


# Agent URLs (from environment variables)
AGENT_URLS = {
    "orchestrator": f"http://localhost:{os.environ.get('ORCHESTRATOR_AGENT_PORT', '10000')}",
    "clarifier": f"http://localhost:{os.environ.get('INTAKE_CLARIFIER_AGENT_PORT', '10007')}",
    "poi": f"http://localhost:{os.environ.get('POI_SEARCH_AGENT_PORT', '10008')}",
    "stay": f"http://localhost:{os.environ.get('STAY_AGENT_PORT', '10009')}",
    "transport": f"http://localhost:{os.environ.get('TRANSPORT_AGENT_PORT', '10010')}",
    "events": f"http://localhost:{os.environ.get('EVENTS_AGENT_PORT', '10011')}",
    "route": f"http://localhost:{os.environ.get('ROUTE_AGENT_PORT', '10012')}",
    "budget": f"http://localhost:{os.environ.get('BUDGET_AGENT_PORT', '10013')}",
    "booking": f"http://localhost:{os.environ.get('BOOKING_AGENT_PORT', '10014')}",
    "aggregator": f"http://localhost:{os.environ.get('AGGREGATOR_AGENT_PORT', '10015')}",
    "validator": f"http://localhost:{os.environ.get('VALIDATOR_AGENT_PORT', '10016')}",
    "dining": f"http://localhost:{os.environ.get('DINING_AGENT_PORT', '10017')}",
}


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def http_client() -> httpx.AsyncClient:
    """Shared httpx client for all integration tests."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        yield client


async def check_agent_health(client: httpx.AsyncClient, agent_name: str) -> bool:
    """
    Check if an agent is healthy and ready.

    Args:
        client: The httpx client to use for the health check.
        agent_name: Name of the agent to check.

    Returns:
        True if agent is healthy, False otherwise.
    """
    url = AGENT_URLS.get(agent_name)
    if not url:
        return False
    try:
        # Try the standard health endpoint
        response = await client.get(f"{url}/health", timeout=5.0)
        if response.status_code == 200:
            return True

        # Some agents might use root endpoint
        response = await client.get(f"{url}/", timeout=5.0)
        return response.status_code == 200
    except Exception:
        return False


async def get_healthy_agents(client: httpx.AsyncClient, agent_names: list[str]) -> list[str]:
    """
    Get list of agents that are currently healthy.

    Args:
        client: The httpx client to use.
        agent_names: List of agent names to check.

    Returns:
        List of agent names that are healthy.
    """
    healthy = []
    for agent in agent_names:
        if await check_agent_health(client, agent):
            healthy.append(agent)
    return healthy


@pytest.fixture(scope="session")
async def require_clarifier(http_client: httpx.AsyncClient) -> str:
    """
    Fixture that ensures clarifier agent is running.

    Skips the test if clarifier is not available.

    Returns:
        URL of the clarifier agent.
    """
    healthy = await check_agent_health(http_client, "clarifier")
    if not healthy:
        pytest.skip(
            "Clarifier agent is not running. Start with: uv run python src/run_all.py"
        )
    return AGENT_URLS["clarifier"]


@pytest.fixture(scope="session")
async def require_discovery_agents(http_client: httpx.AsyncClient) -> dict[str, str]:
    """
    Fixture that ensures at least one discovery agent is running.

    Returns:
        Dict of available discovery agent URLs.
    """
    discovery_agents = ["stay", "transport", "poi", "events", "dining"]
    healthy = await get_healthy_agents(http_client, discovery_agents)

    if not healthy:
        pytest.skip(
            "No discovery agents running. Start with: uv run python src/run_all.py"
        )

    return {agent: AGENT_URLS[agent] for agent in healthy}


@pytest.fixture(scope="session")
async def require_booking_agent(http_client: httpx.AsyncClient) -> str:
    """
    Fixture that ensures booking agent is running.

    Returns:
        URL of the booking agent.
    """
    healthy = await check_agent_health(http_client, "booking")
    if not healthy:
        pytest.skip(
            "Booking agent is not running. Start with: uv run python src/run_all.py"
        )
    return AGENT_URLS["booking"]


@pytest.fixture(scope="session")
async def require_all_agents(http_client: httpx.AsyncClient) -> dict[str, str]:
    """
    Fixture that ensures all agents are running.

    Returns:
        Dict of all agent URLs.
    """
    required = ["clarifier", "stay", "transport", "booking"]
    healthy = await get_healthy_agents(http_client, required)

    missing = set(required) - set(healthy)
    if missing:
        pytest.skip(
            f"Required agents not running: {missing}. Start with: uv run python src/run_all.py"
        )

    return {agent: AGENT_URLS[agent] for agent in healthy}
