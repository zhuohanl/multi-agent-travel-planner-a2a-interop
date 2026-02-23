"""
Azure AI Agent wrapper for orchestrator LLM decisions.

This module provides the OrchestratorLLM class that wraps Azure AI Agent Service
for all orchestrator LLM decision points. It extends the configuration from
azure_agent.py with actual LLM interaction methods.

The orchestrator uses 4 pre-provisioned Azure AI agents:
  - Router: Decides workflow_turn vs answer_question (has 5 tools)
  - Classifier: Classifies user actions (has 1 tool)
  - Planner: Plans which agents to re-run for modifications (has 1 tool)
  - QA: Answers general/budget questions (no tools - text generation only)

Usage:
    from src.orchestrator.agent import OrchestratorLLM

    # Create LLM wrapper from configuration
    from src.orchestrator.azure_agent import load_agent_config
    config = load_agent_config()
    llm = OrchestratorLLM(config)

    # Create a run and process it
    run = await llm.create_run(thread_id, agent_type, message)
    if run.status == "requires_action":
        run = await llm.submit_tool_outputs(run.id, tool_outputs)
"""

from src.orchestrator.agent.llm import (
    OrchestratorLLM,
    RunResult,
    ToolCall,
    ToolOutput,
)

__all__ = [
    "OrchestratorLLM",
    "RunResult",
    "ToolCall",
    "ToolOutput",
]
