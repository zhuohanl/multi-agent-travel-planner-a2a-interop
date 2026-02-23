"""Unit tests for Budget Agent agent_executor.py."""

import os
import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def mock_environment():
    """Set required environment variables for all tests."""
    env_vars = {
        "SERVER_URL": "localhost",
        "BUDGET_AGENT_PORT": "10013",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_DEPLOYMENT_NAME": "test-deployment",
        "AZURE_OPENAI_API_VERSION": "2024-02-01",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


class TestAgentFrameworkBudgetAgentExecutor:
    """Tests for AgentFrameworkBudgetAgentExecutor class."""

    @pytest.fixture
    def executor_class(self, mock_environment):
        """Get the executor class with mocked environment."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.budget_agent.agent_executor import (
                AgentFrameworkBudgetAgentExecutor,
            )
            yield AgentFrameworkBudgetAgentExecutor

    def test_build_agent_returns_budget_agent(self, executor_class, mock_environment):
        """Test that build_agent returns an AgentFrameworkBudgetAgent instance."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.budget_agent.agent import AgentFrameworkBudgetAgent

            executor = executor_class()
            agent = executor.build_agent()

            assert isinstance(agent, AgentFrameworkBudgetAgent)

    def test_executor_inherits_from_base(self, mock_environment):
        """Test that executor inherits from BaseA2AAgentExecutor."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.budget_agent.agent_executor import (
                AgentFrameworkBudgetAgentExecutor,
            )
            from src.shared.a2a.base_agent_executor import BaseA2AAgentExecutor

            assert issubclass(AgentFrameworkBudgetAgentExecutor, BaseA2AAgentExecutor)

    def test_executor_can_be_instantiated(self, executor_class, mock_environment):
        """Test that executor can be instantiated without errors."""
        with patch.dict(os.environ, mock_environment):
            executor = executor_class()
            assert executor is not None

    def test_built_agent_has_correct_name(self, executor_class, mock_environment):
        """Test that built agent has the correct agent name."""
        with patch.dict(os.environ, mock_environment):
            executor = executor_class()
            agent = executor.build_agent()

            assert agent.get_agent_name() == "BudgetAgent"
