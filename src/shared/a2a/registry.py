"""Agent Registry for downstream agent URL management.

Provides centralized configuration for downstream agents, supporting both
discovery agents (parallel execution) and planning agents (sequential pipeline).
"""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Default timeout for agent calls (2 minutes)
DEFAULT_AGENT_TIMEOUT = 120.0


@dataclass(frozen=True)
class AgentConfig:
    """Configuration for a downstream agent.

    Attributes:
        name: Unique identifier for the agent (e.g., "transport", "stay")
        url: Base URL of the agent endpoint (e.g., "http://localhost:8002")
        timeout: Request timeout in seconds. Defaults to 120.0 (2 minutes)
    """

    name: str
    url: str
    timeout: float = DEFAULT_AGENT_TIMEOUT


class AgentRegistry:
    """Registry of downstream agents and their endpoints.

    Centralizes agent configuration for the orchestrator. Supports loading
    from environment variables for production deployment while providing
    sensible defaults for local development.

    Usage:
        registry = AgentRegistry.load()
        transport_config = registry.get("transport")
        # transport_config.url -> "http://localhost:8002"
        # transport_config.timeout -> 120.0
    """

    def __init__(self, agents: dict[str, AgentConfig]):
        """Initialize the registry with agent configurations.

        Args:
            agents: Dictionary mapping agent names to their configurations
        """
        self._agents = agents

    @classmethod
    def load(cls) -> "AgentRegistry":
        """Load registry from environment variables or defaults.

        Environment variables follow the pattern:
            {AGENT_NAME}_AGENT_URL (e.g., TRANSPORT_AGENT_URL)
            {AGENT_NAME}_AGENT_TIMEOUT (e.g., TRANSPORT_AGENT_TIMEOUT)
            {AGENT_NAME}_AGENT_PORT (e.g., TRANSPORT_AGENT_PORT)
            SERVER_URL (host used with *_AGENT_PORT)

        Returns:
            AgentRegistry with all configured agents
        """
        agents: dict[str, AgentConfig] = {}

        # Phase 1: Clarification agent
        agents["clarifier"] = cls._load_agent_config(
            name="clarifier",
            default_url="http://localhost:8001",
            env_port_var="INTAKE_CLARIFIER_AGENT_PORT",
        )

        # Phase 2a: Discovery agents (parallel execution)
        agents["transport"] = cls._load_agent_config(
            name="transport",
            default_url="http://localhost:8002",
        )
        agents["stay"] = cls._load_agent_config(
            name="stay",
            default_url="http://localhost:8003",
        )
        agents["poi"] = cls._load_agent_config(
            name="poi",
            default_url="http://localhost:8004",
            env_port_var="POI_SEARCH_AGENT_PORT",
        )
        agents["events"] = cls._load_agent_config(
            name="events",
            default_url="http://localhost:8005",
        )
        agents["dining"] = cls._load_agent_config(
            name="dining",
            default_url="http://localhost:8006",
        )

        # Phase 2b: Planning agents (sequential pipeline)
        agents["aggregator"] = cls._load_agent_config(
            name="aggregator",
            default_url="http://localhost:8010",
        )
        agents["budget"] = cls._load_agent_config(
            name="budget",
            default_url="http://localhost:8011",
        )
        agents["route"] = cls._load_agent_config(
            name="route",
            default_url="http://localhost:8012",
        )
        agents["validator"] = cls._load_agent_config(
            name="validator",
            default_url="http://localhost:8013",
        )

        # Booking agent (Phase 3)
        agents["booking"] = cls._load_agent_config(
            name="booking",
            default_url="http://localhost:8020",
        )

        logger.debug("Loaded %d agent configurations", len(agents))
        return cls(agents)

    @classmethod
    def _load_agent_config(
        cls,
        name: str,
        default_url: str,
        default_timeout: float = DEFAULT_AGENT_TIMEOUT,
        env_url_var: str | None = None,
        env_port_var: str | None = None,
        host_env_var: str = "SERVER_URL",
        default_host: str = "localhost",
    ) -> AgentConfig:
        """Load configuration for a single agent from environment.

        Args:
            name: Agent name (used to construct env var names)
            default_url: Default URL if env var not set
            default_timeout: Default timeout if env var not set
            env_url_var: Explicit env var name for agent URL override
            env_port_var: Explicit env var name for agent port override
            host_env_var: Env var name for host used with agent ports
            default_host: Default host if host env var not set

        Returns:
            AgentConfig with loaded or default values
        """
        env_prefix = name.upper()
        url_var = env_url_var or f"{env_prefix}_AGENT_URL"
        port_var = env_port_var or f"{env_prefix}_AGENT_PORT"
        url = os.environ.get(url_var)
        if not url:
            port = os.environ.get(port_var)
            if port:
                host = os.environ.get(host_env_var, default_host)
                url = cls._build_url(host, port)
            else:
                url = default_url
        timeout_str = os.environ.get(f"{env_prefix}_AGENT_TIMEOUT")
        timeout = float(timeout_str) if timeout_str else default_timeout

        return AgentConfig(name=name, url=url, timeout=timeout)

    @staticmethod
    def _build_url(host: str, port: str) -> str:
        """Build a base URL from host and port."""
        if host.startswith("http://") or host.startswith("https://"):
            base = host.rstrip("/")
        else:
            base = f"http://{host}"
        return f"{base}:{port}"

    def get(self, agent_name: str) -> AgentConfig:
        """Get configuration for a specific agent.

        Args:
            agent_name: Name of the agent (e.g., "transport", "stay")

        Returns:
            AgentConfig for the requested agent

        Raises:
            ValueError: If agent_name is not registered
        """
        if agent_name not in self._agents:
            registered = ", ".join(sorted(self._agents.keys()))
            raise ValueError(
                f"Unknown agent: {agent_name}. Registered agents: {registered}"
            )
        return self._agents[agent_name]

    def list_agents(self) -> list[str]:
        """List all registered agent names.

        Returns:
            Sorted list of registered agent names
        """
        return sorted(self._agents.keys())

    def __contains__(self, agent_name: str) -> bool:
        """Check if an agent is registered."""
        return agent_name in self._agents

    def __len__(self) -> int:
        """Return number of registered agents."""
        return len(self._agents)


# Agent group constants (used throughout the codebase)
# Per design doc A2A Client Implementation section

DISCOVERY_AGENTS: list[str] = ["transport", "stay", "poi", "events", "dining"]
"""Discovery agents for Phase 2a parallel search.

These agents are called in parallel during the discovery phase to find
flights, hotels, points of interest, events, and restaurants.
"""

PLANNING_AGENTS: list[str] = ["aggregator", "budget", "route", "validator"]
"""Planning agents for Phase 2b sequential pipeline.

These agents process discovery results in order:
1. Aggregator: Combine results from discovery agents
2. Budget: Allocate budget across categories
3. Route: Build day-by-day itinerary
4. Validator: Check feasibility and flag issues
"""
