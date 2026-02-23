from src.shared.a2a.base_agent_executor import BaseA2AAgentExecutor
from .agent import AgentFrameworkBudgetAgent


class AgentFrameworkBudgetAgentExecutor(BaseA2AAgentExecutor):
    """AgentFrameworkBudgetAgent Executor for A2A Protocol."""

    def build_agent(self) -> AgentFrameworkBudgetAgent:
        return AgentFrameworkBudgetAgent()
