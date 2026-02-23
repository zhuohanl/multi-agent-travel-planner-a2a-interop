from src.shared.a2a.base_agent_executor import BaseA2AAgentExecutor
from .agent import AgentFrameworkPOISearchAgent


class AgentFrameworkPOISearchAgentExecutor(BaseA2AAgentExecutor):
    """AgentFrameworkPOISearchAgent Executor for A2A Protocol."""

    def build_agent(self) -> AgentFrameworkPOISearchAgent:
        return AgentFrameworkPOISearchAgent()

