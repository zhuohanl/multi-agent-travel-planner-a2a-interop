from src.shared.a2a.base_agent_executor import BaseA2AAgentExecutor
from .agent import AgentFrameworkRouteAgent


class AgentFrameworkRouteAgentExecutor(BaseA2AAgentExecutor):
    """AgentFrameworkRouteAgent Executor for A2A Protocol."""

    def build_agent(self) -> AgentFrameworkRouteAgent:
        return AgentFrameworkRouteAgent()
