from src.shared.a2a.base_agent_executor import BaseA2AAgentExecutor
from .agent import AgentFrameworkBookingAgent


class AgentFrameworkBookingAgentExecutor(BaseA2AAgentExecutor):
    """AgentFrameworkBookingAgent Executor for A2A Protocol."""

    def build_agent(self) -> AgentFrameworkBookingAgent:
        return AgentFrameworkBookingAgent()
