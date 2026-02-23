"""
Unit tests for Agent Registry.

Tests AgentConfig, AgentRegistry, and agent group constants per design doc
A2A Client Implementation section.
"""

import os
from unittest.mock import patch

import pytest

from src.shared.a2a.registry import (
    AgentConfig,
    AgentRegistry,
    DEFAULT_AGENT_TIMEOUT,
    DISCOVERY_AGENTS,
    PLANNING_AGENTS,
)


class TestAgentConfig:
    """Tests for AgentConfig dataclass."""

    def test_agent_config_creation(self) -> None:
        """Test AgentConfig can be created with required fields."""
        config = AgentConfig(name="transport", url="http://localhost:8002")

        assert config.name == "transport"
        assert config.url == "http://localhost:8002"
        assert config.timeout == DEFAULT_AGENT_TIMEOUT

    def test_agent_config_with_custom_timeout(self) -> None:
        """Test AgentConfig with custom timeout."""
        config = AgentConfig(name="stay", url="http://localhost:8003", timeout=60.0)

        assert config.name == "stay"
        assert config.url == "http://localhost:8003"
        assert config.timeout == 60.0

    def test_agent_config_is_frozen(self) -> None:
        """Test AgentConfig is immutable (frozen dataclass)."""
        config = AgentConfig(name="poi", url="http://localhost:8004")

        with pytest.raises(AttributeError):
            config.name = "new_name"  # type: ignore

    def test_agent_config_equality(self) -> None:
        """Test AgentConfig equality comparison."""
        config1 = AgentConfig(name="events", url="http://localhost:8005")
        config2 = AgentConfig(name="events", url="http://localhost:8005")
        config3 = AgentConfig(name="dining", url="http://localhost:8006")

        assert config1 == config2
        assert config1 != config3

    def test_agent_config_hashable(self) -> None:
        """Test AgentConfig can be used as dict key or in sets."""
        config1 = AgentConfig(name="transport", url="http://localhost:8002")
        config2 = AgentConfig(name="transport", url="http://localhost:8002")

        # Can be used in set
        configs = {config1, config2}
        assert len(configs) == 1

        # Can be used as dict key
        config_dict = {config1: "value"}
        assert config_dict[config2] == "value"


class TestAgentRegistry:
    """Tests for AgentRegistry class."""

    def test_registry_load(self) -> None:
        """Test AgentRegistry.load() returns configured registry."""
        registry = AgentRegistry.load()

        # Should have agents loaded
        assert len(registry) > 0

        # Should have discovery agents
        for agent in DISCOVERY_AGENTS:
            assert agent in registry

        # Should have planning agents
        for agent in PLANNING_AGENTS:
            assert agent in registry

    def test_registry_get_known_agent(self) -> None:
        """Test AgentRegistry.get() returns config for known agent."""
        registry = AgentRegistry.load()

        config = registry.get("transport")

        assert config.name == "transport"
        assert config.url == "http://localhost:8002"
        assert config.timeout == DEFAULT_AGENT_TIMEOUT

    def test_registry_get_unknown_agent_raises(self) -> None:
        """Test AgentRegistry.get() raises ValueError for unknown agent."""
        registry = AgentRegistry.load()

        with pytest.raises(ValueError) as exc_info:
            registry.get("unknown_agent")

        assert "Unknown agent: unknown_agent" in str(exc_info.value)
        assert "Registered agents:" in str(exc_info.value)

    def test_registry_contains(self) -> None:
        """Test AgentRegistry supports 'in' operator."""
        registry = AgentRegistry.load()

        assert "transport" in registry
        assert "stay" in registry
        assert "unknown" not in registry

    def test_registry_len(self) -> None:
        """Test AgentRegistry supports len()."""
        registry = AgentRegistry.load()

        # At minimum, should have discovery + planning + clarifier + booking agents
        expected_min = len(DISCOVERY_AGENTS) + len(PLANNING_AGENTS) + 2
        assert len(registry) >= expected_min

    def test_registry_list_agents(self) -> None:
        """Test AgentRegistry.list_agents() returns sorted list."""
        registry = AgentRegistry.load()

        agents = registry.list_agents()

        assert isinstance(agents, list)
        assert len(agents) == len(registry)
        # Should be sorted
        assert agents == sorted(agents)
        # Should contain known agents
        assert "transport" in agents
        assert "stay" in agents
        assert "clarifier" in agents

    def test_registry_loads_from_environment(self) -> None:
        """Test AgentRegistry.load() uses environment variables when set."""
        custom_url = "http://custom-host:9999"
        custom_timeout = "45.0"

        with patch.dict(os.environ, {
            "TRANSPORT_AGENT_URL": custom_url,
            "TRANSPORT_AGENT_TIMEOUT": custom_timeout,
        }):
            registry = AgentRegistry.load()

            config = registry.get("transport")
            assert config.url == custom_url
            assert config.timeout == 45.0

    def test_registry_loads_from_port_environment(self) -> None:
        """Test AgentRegistry.load() builds URLs from host + port env vars."""
        with patch.dict(
            os.environ,
            {
                "SERVER_URL": "example.com",
                "TRANSPORT_AGENT_PORT": "1234",
                "INTAKE_CLARIFIER_AGENT_PORT": "4321",
                "POI_SEARCH_AGENT_PORT": "5678",
            },
            clear=True,
        ):
            registry = AgentRegistry.load()

            assert registry.get("transport").url == "http://example.com:1234"
            assert registry.get("clarifier").url == "http://example.com:4321"
            assert registry.get("poi").url == "http://example.com:5678"

    def test_registry_uses_defaults_when_env_not_set(self) -> None:
        """Test AgentRegistry.load() uses defaults when env vars not set."""
        # Ensure env vars are not set
        with patch.dict(os.environ, {}, clear=True):
            registry = AgentRegistry.load()

            config = registry.get("stay")
            assert config.url == "http://localhost:8003"
            assert config.timeout == DEFAULT_AGENT_TIMEOUT

    def test_registry_custom_initialization(self) -> None:
        """Test AgentRegistry can be initialized with custom agents."""
        custom_agents = {
            "test_agent": AgentConfig(
                name="test_agent",
                url="http://test:1234",
                timeout=30.0,
            ),
        }

        registry = AgentRegistry(custom_agents)

        assert len(registry) == 1
        assert "test_agent" in registry
        config = registry.get("test_agent")
        assert config.url == "http://test:1234"
        assert config.timeout == 30.0


class TestDiscoveryAgentsConstant:
    """Tests for DISCOVERY_AGENTS constant."""

    def test_discovery_agents_constant(self) -> None:
        """Test DISCOVERY_AGENTS has expected agents."""
        expected = ["transport", "stay", "poi", "events", "dining"]

        assert DISCOVERY_AGENTS == expected

    def test_discovery_agents_count(self) -> None:
        """Test DISCOVERY_AGENTS has 5 agents."""
        assert len(DISCOVERY_AGENTS) == 5

    def test_discovery_agents_all_registered(self) -> None:
        """Test all discovery agents are in the default registry."""
        registry = AgentRegistry.load()

        for agent in DISCOVERY_AGENTS:
            assert agent in registry, f"Discovery agent {agent} not in registry"


class TestPlanningAgentsConstant:
    """Tests for PLANNING_AGENTS constant."""

    def test_planning_agents_constant(self) -> None:
        """Test PLANNING_AGENTS has expected agents."""
        expected = ["aggregator", "budget", "route", "validator"]

        assert PLANNING_AGENTS == expected

    def test_planning_agents_count(self) -> None:
        """Test PLANNING_AGENTS has 4 agents."""
        assert len(PLANNING_AGENTS) == 4

    def test_planning_agents_all_registered(self) -> None:
        """Test all planning agents are in the default registry."""
        registry = AgentRegistry.load()

        for agent in PLANNING_AGENTS:
            assert agent in registry, f"Planning agent {agent} not in registry"


class TestAgentGroupsSeparation:
    """Tests to verify discovery and planning agent groups don't overlap."""

    def test_no_overlap_between_groups(self) -> None:
        """Test discovery and planning agents don't overlap."""
        discovery_set = set(DISCOVERY_AGENTS)
        planning_set = set(PLANNING_AGENTS)

        overlap = discovery_set & planning_set
        assert len(overlap) == 0, f"Overlapping agents: {overlap}"

    def test_clarifier_not_in_groups(self) -> None:
        """Test clarifier agent is not in discovery or planning groups."""
        assert "clarifier" not in DISCOVERY_AGENTS
        assert "clarifier" not in PLANNING_AGENTS

    def test_booking_not_in_groups(self) -> None:
        """Test booking agent is not in discovery or planning groups."""
        assert "booking" not in DISCOVERY_AGENTS
        assert "booking" not in PLANNING_AGENTS
