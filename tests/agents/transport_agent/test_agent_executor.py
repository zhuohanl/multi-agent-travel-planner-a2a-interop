"""Unit tests for Transport Agent agent_executor.py."""

import os
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def mock_environment():
    """Set required environment variables for all tests."""
    env_vars = {
        "SERVER_URL": "localhost",
        "TRANSPORT_AGENT_PORT": "10010",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_DEPLOYMENT_NAME": "test-deployment",
        "AZURE_OPENAI_API_VERSION": "2024-02-01",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


class TestAgentFrameworkTransportAgentExecutor:
    """Tests for AgentFrameworkTransportAgentExecutor class."""

    def test_build_agent_returns_transport_agent(self, mock_environment):
        """Test that build_agent returns an AgentFrameworkTransportAgent."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                from src.agents.transport_agent.agent_executor import (
                    AgentFrameworkTransportAgentExecutor,
                )
                from src.agents.transport_agent.agent import (
                    AgentFrameworkTransportAgent,
                )

                executor = AgentFrameworkTransportAgentExecutor()
                agent = executor.build_agent()

                assert isinstance(agent, AgentFrameworkTransportAgent)

    def test_executor_inherits_from_base(self, mock_environment):
        """Test that executor inherits from BaseA2AAgentExecutor."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                from src.agents.transport_agent.agent_executor import (
                    AgentFrameworkTransportAgentExecutor,
                )
                from src.shared.a2a.base_agent_executor import BaseA2AAgentExecutor

                executor = AgentFrameworkTransportAgentExecutor()

                assert isinstance(executor, BaseA2AAgentExecutor)

    def test_executor_can_be_instantiated(self, mock_environment):
        """Test that executor can be instantiated without errors."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                from src.agents.transport_agent.agent_executor import (
                    AgentFrameworkTransportAgentExecutor,
                )

                executor = AgentFrameworkTransportAgentExecutor()

                assert executor is not None

    def test_executor_build_agent_is_callable(self, mock_environment):
        """Test that build_agent method is callable."""
        with patch.dict(os.environ, mock_environment):
            with patch("agent_framework.HostedWebSearchTool"):
                from src.agents.transport_agent.agent_executor import (
                    AgentFrameworkTransportAgentExecutor,
                )

                executor = AgentFrameworkTransportAgentExecutor()

                assert callable(executor.build_agent)
