"""
Base wrapper class for deploying existing agent logic across platforms.

This module provides the abstract base class that all platform-specific wrappers
inherit from. The wrapper pattern allows reusing existing agent logic from
src/agents/ without rewriting it for each deployment target.

Architecture Principle (from design doc lines 64-69):
    - "Reuse existing agent logic" - wrap, don't rewrite
    - Output models from src/shared/models.py
    - Consistent behavior across all deployment platforms
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AgentConfig:
    """Configuration for an agent wrapper.

    Attributes:
        name: Agent name (e.g., "transport", "poi")
        source_path: Path to the source agent code in src/agents/
        agent_type: Type of agent ("native" or "hosted")
        framework: Framework for hosted agents ("agent_framework" or "langgraph")
        model: Model deployment name (e.g., "gpt-4.1-mini")
        tools: List of tools the agent uses
        env_vars: Environment variables required by the agent
    """

    name: str
    source_path: Path
    agent_type: str = "native"  # "native" or "hosted"
    framework: str | None = None  # "agent_framework" or "langgraph" for hosted
    model: str = "gpt-4.1-mini"
    tools: list[str] = field(default_factory=list)
    env_vars: list[str] = field(default_factory=list)


class BaseAgentWrapper(ABC):
    """Abstract base class for agent wrappers.

    All platform-specific wrappers (Foundry, MAF Hosted, LangGraph Hosted)
    inherit from this class. It defines the common interface for wrapping
    existing agent logic and deploying it to different platforms.

    The wrapper provides three core operations:
        - wrap(): Configure the wrapper with agent source code
        - get_config(): Get deployment configuration for the platform
        - deploy(): Deploy the wrapped agent to the target platform

    Subclasses must implement these methods according to their platform's
    requirements.
    """

    def __init__(self, config: AgentConfig):
        """Initialize the wrapper with agent configuration.

        Args:
            config: Configuration specifying the agent to wrap.
        """
        self._config = config
        self._wrapped = False
        self._instructions: str | None = None
        self._tools: list[dict[str, Any]] = []

    @property
    def config(self) -> AgentConfig:
        """Get the agent configuration."""
        return self._config

    @property
    def name(self) -> str:
        """Get the agent name."""
        return self._config.name

    @property
    def source_path(self) -> Path:
        """Get the source path."""
        return self._config.source_path

    @property
    def is_wrapped(self) -> bool:
        """Check if the agent has been wrapped."""
        return self._wrapped

    @property
    def instructions(self) -> str | None:
        """Get the extracted instructions (after wrap() is called)."""
        return self._instructions

    @property
    def tools(self) -> list[dict[str, Any]]:
        """Get the extracted tools (after wrap() is called)."""
        return self._tools

    @abstractmethod
    def wrap(self) -> None:
        """Extract agent logic from the source code.

        This method reads the source agent code and extracts:
        - Instructions (SYSTEM_PROMPT or instructions attribute)
        - Tools (get_tools() return value)
        - Any other configuration needed for deployment

        After calling wrap(), the wrapper is ready for get_config() and deploy().

        Raises:
            FileNotFoundError: If the source agent code is not found.
            ValueError: If the source code is invalid or missing required elements.
        """
        pass

    @abstractmethod
    def get_config(self) -> dict[str, Any]:
        """Get the deployment configuration for the platform.

        Returns a dictionary containing all configuration needed to deploy
        the agent to the target platform. The format depends on the platform:
        - Foundry: YAML-compatible dict for agent.yaml
        - MAF Hosted: Dockerfile + requirements + main.py configuration
        - LangGraph: Graph definition configuration

        Returns:
            Dictionary containing deployment configuration.

        Raises:
            RuntimeError: If wrap() has not been called.
        """
        pass

    @abstractmethod
    def deploy(self, dry_run: bool = False) -> dict[str, Any]:
        """Deploy the wrapped agent to the target platform.

        Args:
            dry_run: If True, only print what would be deployed without
                     actually deploying.

        Returns:
            Dictionary containing deployment result:
            - success: bool indicating if deployment succeeded
            - agent_id: ID of the deployed agent (if successful)
            - message: Human-readable status message

        Raises:
            RuntimeError: If wrap() has not been called.
            DeploymentError: If deployment fails.
        """
        pass

    def _ensure_wrapped(self) -> None:
        """Ensure wrap() has been called before operations that require it.

        Raises:
            RuntimeError: If wrap() has not been called.
        """
        if not self._wrapped:
            raise RuntimeError(
                f"Agent '{self.name}' has not been wrapped. "
                "Call wrap() before get_config() or deploy()."
            )
