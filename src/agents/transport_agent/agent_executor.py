from src.shared.a2a.base_agent_executor import BaseA2AAgentExecutor
from .agent import AgentFrameworkTransportAgent


class AgentFrameworkTransportAgentExecutor(BaseA2AAgentExecutor):
    """AgentFrameworkTransportAgent Executor for A2A Protocol."""

    def build_agent(self) -> AgentFrameworkTransportAgent:
        return AgentFrameworkTransportAgent()
