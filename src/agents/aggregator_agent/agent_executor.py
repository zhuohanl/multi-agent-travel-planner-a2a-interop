from src.shared.a2a.base_agent_executor import BaseA2AAgentExecutor
from .agent import AgentFrameworkAggregatorAgent


class AgentFrameworkAggregatorAgentExecutor(BaseA2AAgentExecutor):
    """AgentFrameworkAggregatorAgent Executor for A2A Protocol."""

    def build_agent(self) -> AgentFrameworkAggregatorAgent:
        return AgentFrameworkAggregatorAgent()
