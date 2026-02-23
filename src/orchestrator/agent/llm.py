"""
OrchestratorLLM - Azure AI Agent Service wrapper for orchestrator LLM decisions.

This module provides the core interface for the orchestrator to interact with
Azure AI Agent Service. It manages thread lifecycle, run creation, and tool
output submission.

Key design principles:
1. Each LLM decision must be correct with zero thread history - business context
   comes from WorkflowState, not thread history.
2. Per-agent threads avoid cross-contamination between different decision types.
3. Thread expiry is handled gracefully - threads exist for debugging only.

The 4 decision points:
- LLM #1 (Router): Decides workflow_turn vs answer_question (5 tools)
- LLM #2 (Classifier): Classifies user actions (1 tool)
- LLM #3 (Planner): Plans modification re-runs (1 tool)
- LLM #4 (QA): Answers questions (no tools, pure text)

Usage:
    from src.orchestrator.agent import OrchestratorLLM
    from src.orchestrator.azure_agent import load_agent_config

    config = load_agent_config()
    llm = OrchestratorLLM(config)

    # Create a run with a message
    thread_id = llm.ensure_thread_exists(session_id, AgentType.ROUTER)
    run = await llm.create_run(thread_id, AgentType.ROUTER, message)

    # Handle tool calls
    if run.status == "requires_action" and run.tool_calls:
        # Process tool calls...
        outputs = [ToolOutput(tool_call_id="...", output="...")]
        run = await llm.submit_tool_outputs(run.id, thread_id, outputs)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.orchestrator.azure_agent import (
    AgentType,
    OrchestratorAgentConfig,
    create_agents_client,
)

if TYPE_CHECKING:
    from azure.ai.agents import AgentsClient
    from azure.ai.agents.models import AgentThread, ThreadRun

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES FOR RUN RESULTS
# =============================================================================


@dataclass
class ToolCall:
    """Represents a tool call from the Azure AI Agent.

    Attributes:
        id: Unique identifier for this tool call
        name: Name of the tool (e.g., "workflow_turn", "answer_question")
        arguments: Parsed arguments dict from the tool call
        raw_arguments: Raw JSON string of arguments (for debugging)
    """

    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""


@dataclass
class ToolOutput:
    """Output to submit back to the Azure AI Agent.

    Attributes:
        tool_call_id: The ID of the tool call this output responds to
        output: The string output to return to the agent
    """

    tool_call_id: str
    output: str


@dataclass
class RunResult:
    """Result of an Azure AI Agent run.

    Attributes:
        id: The run ID
        thread_id: The thread this run belongs to
        status: Run status (e.g., "completed", "requires_action", "failed")
        tool_calls: List of tool calls if status is "requires_action"
        text_response: The final text response if status is "completed"
        error_message: Error message if status is "failed"
        raw_run: The raw Azure run object (for advanced use cases)
    """

    id: str
    thread_id: str
    status: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    text_response: str | None = None
    error_message: str | None = None
    raw_run: Any = None

    @property
    def requires_action(self) -> bool:
        """Check if this run requires tool output submission."""
        return self.status == "requires_action"

    @property
    def is_completed(self) -> bool:
        """Check if this run is completed successfully."""
        return self.status == "completed"

    @property
    def has_failed(self) -> bool:
        """Check if this run has failed."""
        return self.status in ("failed", "cancelled", "expired")


# =============================================================================
# ORCHESTRATOR LLM CLASS
# =============================================================================


class OrchestratorLLM:
    """Azure AI Agent Service wrapper for orchestrator LLM decisions.

    Uses pre-provisioned agent IDs (set during deployment) and
    per-agent threads to avoid cross-contamination.

    The orchestrator uses 4 LLM decision points:
    - LLM #1 (Router): Decides workflow_turn vs answer_question (5 tools)
    - LLM #2 (Classifier): Classifies user actions (1 tool)
    - LLM #3 (Planner): Plans modification re-runs (1 tool)
    - LLM #4 (QA): Answers questions (no tools, pure text)

    Key principle: Each LLM decision must be correct with zero thread history.
    Business context is injected via WorkflowState summaries in the prompt,
    not retrieved from thread history. Threads exist for debugging only.
    """

    # Agent types for thread management
    AGENT_TYPES = list(AgentType)

    def __init__(self, config: OrchestratorAgentConfig) -> None:
        """Initialize the orchestrator LLM wrapper.

        Args:
            config: Orchestrator agent configuration with all agent IDs

        Note:
            This constructor does NOT create agents in Azure. It only
            loads the pre-provisioned agent IDs from configuration.
            Agents are created once during deployment via
            scripts/provision_azure_agents.py.
        """
        self._config = config
        self._client: AgentsClient | None = None

        # Per-agent threads to avoid cross-contamination
        # Structure: session_id -> {agent_type -> thread_id}
        self._session_threads: dict[str, dict[AgentType, str]] = {}

        logger.info(
            "OrchestratorLLM initialized with pre-provisioned agents: %s",
            ", ".join(
                f"{t.value}={config.get_agent_id(t)[:20]}..." for t in AgentType
            ),
        )

    @property
    def config(self) -> OrchestratorAgentConfig:
        """Return the agent configuration."""
        return self._config

    @property
    def client(self) -> "AgentsClient":
        """Lazily initialize and return the Azure AI Agents client.

        Returns:
            AgentsClient instance

        Raises:
            ImportError: If Azure packages are not installed
        """
        if self._client is None:
            self._client = create_agents_client(self._config)
        return self._client

    def get_agent_id(self, agent_type: AgentType | str) -> str:
        """Get the agent ID for a given agent type.

        Args:
            agent_type: The agent type (AgentType enum or string)

        Returns:
            The agent ID for the specified type
        """
        return self._config.get_agent_id(agent_type)

    # =========================================================================
    # THREAD MANAGEMENT
    # =========================================================================

    def ensure_thread_exists(self, session_id: str, agent_type: AgentType | str) -> str:
        """Get existing thread_id or create new thread for this session/agent_type.

        Each agent type gets its own thread to avoid cross-contamination:
        - Router thread only sees routing decisions
        - Classifier thread only sees classification decisions
        - Planner thread only sees planning decisions
        - QA thread only sees Q&A pairs

        Args:
            session_id: The session identifier
            agent_type: The agent type (enum or string)

        Returns:
            thread_id for this session/agent_type combination

        Note:
            Handles expired threads (Azure TTL) gracefully by creating new ones.
        """
        if isinstance(agent_type, str):
            agent_type = AgentType(agent_type)

        if session_id not in self._session_threads:
            self._session_threads[session_id] = {}

        agent_threads = self._session_threads[session_id]

        if agent_type in agent_threads:
            try:
                # Verify thread still exists in Azure
                self.client.threads.get(agent_threads[agent_type])
                return agent_threads[agent_type]
            except Exception as e:
                # Thread expired or error - create new one
                # Catch all exceptions since the specific exception type
                # depends on Azure SDK version
                logger.info(
                    "Thread expired or error for %s/%s: %s, creating new",
                    session_id,
                    agent_type.value,
                    str(e),
                )

        # Create thread with metadata for debugging/querying
        thread = self.client.threads.create(
            metadata={
                "session_id": session_id,
                "agent_type": agent_type.value,
            }
        )
        agent_threads[agent_type] = thread.id
        logger.debug(
            "Created thread %s for %s/%s",
            thread.id,
            session_id,
            agent_type.value,
        )
        return thread.id

    def get_thread_id(
        self, session_id: str, agent_type: AgentType | str
    ) -> str | None:
        """Get existing thread ID without creating a new one.

        Args:
            session_id: The session identifier
            agent_type: The agent type

        Returns:
            thread_id if it exists, None otherwise
        """
        if isinstance(agent_type, str):
            agent_type = AgentType(agent_type)

        if session_id not in self._session_threads:
            return None
        return self._session_threads[session_id].get(agent_type)

    def clear_session_threads(self, session_id: str) -> None:
        """Clear all threads for a session.

        Use this when a session is terminated or when threads need to be reset.

        Args:
            session_id: The session identifier to clear
        """
        if session_id in self._session_threads:
            del self._session_threads[session_id]
            logger.debug("Cleared threads for session %s", session_id)

    # =========================================================================
    # RUN MANAGEMENT
    # =========================================================================

    async def create_run(
        self,
        thread_id: str,
        agent_type: AgentType | str,
        message: str,
    ) -> RunResult:
        """Create a run to process a message through the specified agent.

        This is the primary method for sending a message to an Azure AI Agent
        and getting a response. The agent may return tool calls that need to
        be processed with submit_tool_outputs().

        Args:
            thread_id: The thread ID to use (from ensure_thread_exists)
            agent_type: The type of agent to use (determines which agent_id)
            message: The message to process

        Returns:
            RunResult with the run status and any tool calls or text response

        Example:
            thread_id = llm.ensure_thread_exists(session_id, AgentType.ROUTER)
            run = await llm.create_run(thread_id, AgentType.ROUTER, "Plan a trip to Tokyo")
            if run.requires_action:
                # Process tool calls...
                outputs = [ToolOutput(tool_call_id=tc.id, output="...") for tc in run.tool_calls]
                run = await llm.submit_tool_outputs(run.id, thread_id, outputs)
        """
        if isinstance(agent_type, str):
            agent_type = AgentType(agent_type)

        agent_id = self.get_agent_id(agent_type)

        logger.debug(
            "Creating run for thread=%s, agent=%s, message=%s...",
            thread_id,
            agent_type.value,
            message[:50],
        )

        try:
            # First, add the user message to the thread
            self.client.messages.create(
                thread_id=thread_id,
                role="user",
                content=message,
            )

            # Create a run and poll until it reaches a terminal status
            run = self.client.runs.create(
                thread_id=thread_id,
                agent_id=agent_id,
            )
            run = self._poll_run_until_terminal(thread_id, run.id)

            return self._parse_run_result(run, thread_id)

        except Exception as e:
            logger.error(
                "Error creating run for thread=%s, agent=%s: %s",
                thread_id,
                agent_type.value,
                str(e),
            )
            return RunResult(
                id="error",
                thread_id=thread_id,
                status="failed",
                error_message=str(e),
            )

    async def submit_tool_outputs(
        self,
        run_id: str,
        thread_id: str,
        tool_outputs: list[ToolOutput],
    ) -> RunResult:
        """Submit tool outputs to continue a run that requires action.

        After processing tool calls from create_run(), use this method to
        submit the outputs and continue processing.

        Args:
            run_id: The run ID from the RunResult
            thread_id: The thread ID
            tool_outputs: List of ToolOutput with results for each tool call

        Returns:
            RunResult with the updated run status

        Example:
            if run.requires_action:
                outputs = []
                for tc in run.tool_calls:
                    result = await handle_tool_call(tc)
                    outputs.append(ToolOutput(tool_call_id=tc.id, output=result))
                run = await llm.submit_tool_outputs(run.id, run.thread_id, outputs)
        """
        logger.debug(
            "Submitting %d tool outputs for run=%s, thread=%s",
            len(tool_outputs),
            run_id,
            thread_id,
        )

        try:
            # Convert ToolOutput objects to the format expected by Azure SDK
            azure_tool_outputs = [
                {"tool_call_id": to.tool_call_id, "output": to.output}
                for to in tool_outputs
            ]

            # Submit outputs and continue the run
            run = self.client.runs.submit_tool_outputs(
                thread_id=thread_id,
                run_id=run_id,
                tool_outputs=azure_tool_outputs,
            )
            run = self._poll_run_until_terminal(thread_id, run.id)

            return self._parse_run_result(run, thread_id)

        except Exception as e:
            logger.error(
                "Error submitting tool outputs for run=%s: %s",
                run_id,
                str(e),
            )
            return RunResult(
                id=run_id,
                thread_id=thread_id,
                status="failed",
                error_message=str(e),
            )

    def _poll_run_until_terminal(
        self,
        thread_id: str,
        run_id: str,
        poll_interval_seconds: float = 0.5,
        timeout_seconds: float = 120.0,
    ) -> ThreadRun:
        """Poll a run until it reaches a terminal status."""
        terminal_statuses = {
            "requires_action",
            "completed",
            "failed",
            "cancelled",
            "expired",
            "incomplete",
        }
        start_time = time.monotonic()

        while True:
            run = self.client.runs.get(thread_id=thread_id, run_id=run_id)
            if run.status in terminal_statuses:
                return run
            if timeout_seconds is not None and time.monotonic() - start_time > timeout_seconds:
                raise TimeoutError(
                    f"Run {run_id} did not complete within {timeout_seconds} seconds"
                )
            time.sleep(poll_interval_seconds)

    def _parse_run_result(self, run: ThreadRun, thread_id: str) -> RunResult:
        """Parse an Azure ThreadRun into our RunResult dataclass.

        Args:
            run: The Azure ThreadRun object
            thread_id: The thread ID

        Returns:
            Parsed RunResult
        """
        tool_calls: list[ToolCall] = []
        text_response: str | None = None
        error_message: str | None = None

        # Extract tool calls if the run requires action
        if run.status == "requires_action" and run.required_action:
            submit_outputs = getattr(run.required_action, "submit_tool_outputs", None)
            if submit_outputs and hasattr(submit_outputs, "tool_calls"):
                for tc in submit_outputs.tool_calls:
                    # Parse the arguments JSON
                    try:
                        arguments = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, AttributeError):
                        arguments = {}

                    tool_calls.append(
                        ToolCall(
                            id=tc.id,
                            name=tc.function.name,
                            arguments=arguments,
                            raw_arguments=tc.function.arguments,
                        )
                    )

        # Extract text response if completed
        if run.status == "completed":
            text_response = self._extract_text_from_run(run, thread_id)

        # Extract error if failed
        if run.status in ("failed", "cancelled", "expired"):
            error_message = getattr(run, "last_error", None)
            if error_message:
                error_message = str(error_message)
            else:
                error_message = f"Run {run.status}"

        return RunResult(
            id=run.id,
            thread_id=thread_id,
            status=run.status,
            tool_calls=tool_calls,
            text_response=text_response,
            error_message=error_message,
            raw_run=run,
        )

    def _extract_text_from_run(self, run: ThreadRun, thread_id: str) -> str | None:
        """Extract the assistant's text response from a completed run.

        Args:
            run: The completed Azure ThreadRun
            thread_id: The thread ID to query messages

        Returns:
            The text response or None
        """
        try:
            # Get the messages from the thread
            messages = self.client.messages.list(thread_id=thread_id, order="desc")

            # Find the most recent assistant message
            for msg in messages:
                if msg.role == "assistant":
                    # Extract text from the message content
                    for content_block in msg.content:
                        if hasattr(content_block, "text") and content_block.text:
                            return content_block.text.value
            return None

        except Exception as e:
            logger.warning("Error extracting text from run: %s", str(e))
            return None
