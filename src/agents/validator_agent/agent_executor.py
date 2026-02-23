from src.shared.a2a.base_agent_executor import BaseA2AAgentExecutor
from .agent import AgentFrameworkValidatorAgent


class AgentFrameworkValidatorAgentExecutor(BaseA2AAgentExecutor):
    """AgentFrameworkValidatorAgent Executor for A2A Protocol."""

    def build_agent(self) -> AgentFrameworkValidatorAgent:
        return AgentFrameworkValidatorAgent()
