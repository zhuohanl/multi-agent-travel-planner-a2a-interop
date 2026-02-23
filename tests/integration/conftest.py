"""
Shared fixtures for all integration tests.

This module provides common fixtures used by both:
- Tier 1 mock tests (tests/integration/mock/)
- Tier 2 live tests (tests/integration/live/)
"""

import os

import pytest
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


@pytest.fixture(scope="session")
def agent_ports() -> dict[str, int]:
    """
    Get configured agent ports from environment variables.

    Returns:
        Dict mapping agent names to their port numbers.
    """
    return {
        "orchestrator": int(os.environ.get("ORCHESTRATOR_AGENT_PORT", "10000")),
        "clarifier": int(os.environ.get("INTAKE_CLARIFIER_AGENT_PORT", "10007")),
        "poi": int(os.environ.get("POI_SEARCH_AGENT_PORT", "10008")),
        "stay": int(os.environ.get("STAY_AGENT_PORT", "10009")),
        "transport": int(os.environ.get("TRANSPORT_AGENT_PORT", "10010")),
        "events": int(os.environ.get("EVENTS_AGENT_PORT", "10011")),
        "route": int(os.environ.get("ROUTE_AGENT_PORT", "10012")),
        "budget": int(os.environ.get("BUDGET_AGENT_PORT", "10013")),
        "booking": int(os.environ.get("BOOKING_AGENT_PORT", "10014")),
        "aggregator": int(os.environ.get("AGGREGATOR_AGENT_PORT", "10015")),
        "validator": int(os.environ.get("VALIDATOR_AGENT_PORT", "10016")),
        "dining": int(os.environ.get("DINING_AGENT_PORT", "10017")),
    }


@pytest.fixture(scope="session")
def agent_urls(agent_ports: dict[str, int]) -> dict[str, str]:
    """
    Get full agent URLs from ports.

    Returns:
        Dict mapping agent names to their full URLs.
    """
    server_url = os.environ.get("SERVER_URL", "localhost")
    return {name: f"http://{server_url}:{port}" for name, port in agent_ports.items()}
