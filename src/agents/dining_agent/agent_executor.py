from src.shared.a2a.base_agent_executor import BaseA2AAgentExecutor
from .agent import AgentFrameworkDiningAgent


class AgentFrameworkDiningAgentExecutor(BaseA2AAgentExecutor):
    """AgentFrameworkDiningAgent Executor for A2A Protocol."""

    def build_agent(self) -> AgentFrameworkDiningAgent:
        return AgentFrameworkDiningAgent()
