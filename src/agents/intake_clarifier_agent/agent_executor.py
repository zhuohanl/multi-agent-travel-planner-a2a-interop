from src.shared.a2a.base_agent_executor import BaseA2AAgentExecutor
from .agent import AgentFrameworkIntakeClarifierAgent


class AgentFrameworkIntakeClarifierAgentExecutor(BaseA2AAgentExecutor):
    """AgentFrameworkIntakeClarifierAgent Executor for A2A Protocol."""

    def build_agent(self) -> AgentFrameworkIntakeClarifierAgent:
        return AgentFrameworkIntakeClarifierAgent()

