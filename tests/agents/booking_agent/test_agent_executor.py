"""Unit tests for Booking Agent agent_executor.py."""

import os
import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def mock_environment():
    """Set required environment variables for all tests."""
    env_vars = {
        "SERVER_URL": "localhost",
        "BOOKING_AGENT_PORT": "10014",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_DEPLOYMENT_NAME": "test-deployment",
        "AZURE_OPENAI_API_VERSION": "2024-02-01",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


class TestAgentFrameworkBookingAgentExecutor:
    """Tests for AgentFrameworkBookingAgentExecutor class."""

    def test_build_agent_returns_booking_agent(self, mock_environment):
        """Test that build_agent returns a BookingAgent instance."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.booking_agent.agent_executor import (
                AgentFrameworkBookingAgentExecutor,
            )
            from src.agents.booking_agent.agent import AgentFrameworkBookingAgent

            executor = AgentFrameworkBookingAgentExecutor()
            agent = executor.build_agent()

            assert isinstance(agent, AgentFrameworkBookingAgent)

    def test_executor_inherits_from_base(self, mock_environment):
        """Test that executor inherits from BaseA2AAgentExecutor."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.booking_agent.agent_executor import (
                AgentFrameworkBookingAgentExecutor,
            )
            from src.shared.a2a.base_agent_executor import BaseA2AAgentExecutor

            assert issubclass(AgentFrameworkBookingAgentExecutor, BaseA2AAgentExecutor)

    def test_executor_instantiation(self, mock_environment):
        """Test that executor can be instantiated."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.booking_agent.agent_executor import (
                AgentFrameworkBookingAgentExecutor,
            )

            executor = AgentFrameworkBookingAgentExecutor()
            assert executor is not None

    def test_build_agent_called_multiple_times(self, mock_environment):
        """Test that build_agent returns new instances each time."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.booking_agent.agent_executor import (
                AgentFrameworkBookingAgentExecutor,
            )

            executor = AgentFrameworkBookingAgentExecutor()
            agent1 = executor.build_agent()
            agent2 = executor.build_agent()

            # Should be different instances
            assert agent1 is not agent2
