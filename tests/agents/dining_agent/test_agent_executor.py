"""Unit tests for Dining Agent agent_executor.py."""

import os
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def mock_environment():
    """Set required environment variables for all tests."""
    env_vars = {
        "SERVER_URL": "localhost",
        "DINING_AGENT_PORT": "10017",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_DEPLOYMENT_NAME": "test-deployment",
        "AZURE_OPENAI_API_VERSION": "2024-02-01",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


class TestAgentFrameworkDiningAgentExecutor:
    """Tests for AgentFrameworkDiningAgentExecutor class."""

    def test_executor_inherits_from_base(self, mock_environment):
        """Test that executor inherits from BaseA2AAgentExecutor."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                from src.agents.dining_agent.agent_executor import (
                    AgentFrameworkDiningAgentExecutor,
                )
                from src.shared.a2a.base_agent_executor import BaseA2AAgentExecutor

                assert issubclass(AgentFrameworkDiningAgentExecutor, BaseA2AAgentExecutor)

    def test_build_agent_returns_dining_agent(self, mock_environment):
        """Test that build_agent returns an AgentFrameworkDiningAgent."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                from src.agents.dining_agent.agent_executor import (
                    AgentFrameworkDiningAgentExecutor,
                )
                from src.agents.dining_agent.agent import AgentFrameworkDiningAgent

                executor = AgentFrameworkDiningAgentExecutor()
                agent = executor.build_agent()

                assert isinstance(agent, AgentFrameworkDiningAgent)

    def test_build_agent_returns_new_instance_each_call(self, mock_environment):
        """Test that build_agent returns a new instance each time."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                from src.agents.dining_agent.agent_executor import (
                    AgentFrameworkDiningAgentExecutor,
                )

                executor = AgentFrameworkDiningAgentExecutor()
                agent1 = executor.build_agent()
                agent2 = executor.build_agent()

                assert agent1 is not agent2

    def test_executor_instantiation(self, mock_environment):
        """Test that executor can be instantiated without arguments."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                from src.agents.dining_agent.agent_executor import (
                    AgentFrameworkDiningAgentExecutor,
                )

                executor = AgentFrameworkDiningAgentExecutor()
                assert executor is not None
