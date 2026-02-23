from src.shared.a2a.base_agent_executor import BaseA2AAgentExecutor
from .agent import AgentFrameworkEventsAgent


class AgentFrameworkEventsAgentExecutor(BaseA2AAgentExecutor):
    """AgentFrameworkEventsAgent Executor for A2A Protocol."""

    def build_agent(self) -> AgentFrameworkEventsAgent:
        return AgentFrameworkEventsAgent()
