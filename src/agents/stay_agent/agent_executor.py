from src.shared.a2a.base_agent_executor import BaseA2AAgentExecutor
from .agent import AgentFrameworkStayAgent


class AgentFrameworkStayAgentExecutor(BaseA2AAgentExecutor):
    """AgentFrameworkStayAgent Executor for A2A Protocol."""

    def build_agent(self) -> AgentFrameworkStayAgent:
        return AgentFrameworkStayAgent()
