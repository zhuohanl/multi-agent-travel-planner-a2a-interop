"""
Unit tests for OrchestratorLLM in src/orchestrator/agent/llm.py.

Tests cover:
- Thread management (ensure_thread_exists, get_thread_id, clear_session_threads)
- Run creation (create_run)
- Tool output submission (submit_tool_outputs)
- RunResult parsing
- Graceful handling of expired threads
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from src.orchestrator.azure_agent import OrchestratorAgentConfig


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_config() -> OrchestratorAgentConfig:
    """Create a mock configuration for testing."""
    from src.orchestrator.azure_agent import OrchestratorAgentConfig

    return OrchestratorAgentConfig(
        endpoint="https://test.services.ai.azure.com/api/projects/test",
        deployment_name="gpt-4.1",
        routing_agent_id="asst_router_123",
        classifier_agent_id="asst_classifier_456",
        planner_agent_id="asst_planner_789",
        qa_agent_id="asst_qa_012",
    )


@pytest.fixture
def mock_azure_client() -> MagicMock:
    """Create a mock Azure AI Agents client."""
    client = MagicMock()
    client.threads = MagicMock()
    client.messages = MagicMock()
    client.runs = MagicMock()
    return client


@pytest.fixture
def mock_thread() -> MagicMock:
    """Create a mock Azure thread."""
    thread = MagicMock()
    thread.id = "thread_test_123"
    return thread


@pytest.fixture
def mock_run_completed() -> MagicMock:
    """Create a mock completed run."""
    run = MagicMock()
    run.id = "run_abc123"
    run.status = "completed"
    run.required_action = None
    return run


@pytest.fixture
def mock_run_requires_action() -> MagicMock:
    """Create a mock run that requires action (tool calls)."""
    # Create the tool call
    tool_call = MagicMock()
    tool_call.id = "call_xyz789"
    tool_call.function = MagicMock()
    tool_call.function.name = "workflow_turn"
    tool_call.function.arguments = '{"message": "Plan a trip to Tokyo"}'

    # Create the submit_tool_outputs
    submit_outputs = MagicMock()
    submit_outputs.tool_calls = [tool_call]

    # Create the required action
    required_action = MagicMock()
    required_action.submit_tool_outputs = submit_outputs

    # Create the run
    run = MagicMock()
    run.id = "run_needs_action"
    run.status = "requires_action"
    run.required_action = required_action

    return run


@pytest.fixture
def mock_run_failed() -> MagicMock:
    """Create a mock failed run."""
    run = MagicMock()
    run.id = "run_failed"
    run.status = "failed"
    run.required_action = None
    run.last_error = "Rate limit exceeded"
    return run


# =============================================================================
# DATA CLASS TESTS
# =============================================================================


class TestToolCall:
    """Tests for ToolCall dataclass."""

    def test_tool_call_creation(self) -> None:
        """Test creating a ToolCall."""
        from src.orchestrator.agent.llm import ToolCall

        tc = ToolCall(
            id="call_123",
            name="workflow_turn",
            arguments={"message": "Plan a trip"},
            raw_arguments='{"message": "Plan a trip"}',
        )

        assert tc.id == "call_123"
        assert tc.name == "workflow_turn"
        assert tc.arguments == {"message": "Plan a trip"}
        assert tc.raw_arguments == '{"message": "Plan a trip"}'

    def test_tool_call_default_raw_arguments(self) -> None:
        """Test that raw_arguments defaults to empty string."""
        from src.orchestrator.agent.llm import ToolCall

        tc = ToolCall(
            id="call_123",
            name="workflow_turn",
            arguments={"message": "Plan a trip"},
        )

        assert tc.raw_arguments == ""


class TestToolOutput:
    """Tests for ToolOutput dataclass."""

    def test_tool_output_creation(self) -> None:
        """Test creating a ToolOutput."""
        from src.orchestrator.agent.llm import ToolOutput

        output = ToolOutput(
            tool_call_id="call_123",
            output='{"success": true, "message": "Trip planned"}',
        )

        assert output.tool_call_id == "call_123"
        assert output.output == '{"success": true, "message": "Trip planned"}'


class TestRunResult:
    """Tests for RunResult dataclass."""

    def test_run_result_completed(self) -> None:
        """Test RunResult for a completed run."""
        from src.orchestrator.agent.llm import RunResult

        result = RunResult(
            id="run_123",
            thread_id="thread_456",
            status="completed",
            text_response="Here is your trip plan.",
        )

        assert result.is_completed
        assert not result.requires_action
        assert not result.has_failed
        assert result.text_response == "Here is your trip plan."

    def test_run_result_requires_action(self) -> None:
        """Test RunResult for a run requiring action."""
        from src.orchestrator.agent.llm import RunResult, ToolCall

        result = RunResult(
            id="run_123",
            thread_id="thread_456",
            status="requires_action",
            tool_calls=[
                ToolCall(
                    id="call_789",
                    name="workflow_turn",
                    arguments={"message": "Plan trip"},
                )
            ],
        )

        assert result.requires_action
        assert not result.is_completed
        assert not result.has_failed
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "workflow_turn"

    def test_run_result_failed(self) -> None:
        """Test RunResult for a failed run."""
        from src.orchestrator.agent.llm import RunResult

        result = RunResult(
            id="run_123",
            thread_id="thread_456",
            status="failed",
            error_message="Rate limit exceeded",
        )

        assert result.has_failed
        assert not result.is_completed
        assert not result.requires_action
        assert result.error_message == "Rate limit exceeded"

    def test_run_result_cancelled_is_failed(self) -> None:
        """Test that cancelled runs are considered failed."""
        from src.orchestrator.agent.llm import RunResult

        result = RunResult(
            id="run_123",
            thread_id="thread_456",
            status="cancelled",
        )

        assert result.has_failed

    def test_run_result_expired_is_failed(self) -> None:
        """Test that expired runs are considered failed."""
        from src.orchestrator.agent.llm import RunResult

        result = RunResult(
            id="run_123",
            thread_id="thread_456",
            status="expired",
        )

        assert result.has_failed


# =============================================================================
# THREAD MANAGEMENT TESTS
# =============================================================================


class TestEnsureThreadExists:
    """Tests for ensure_thread_exists method."""

    def test_ensure_thread_exists_creates_new(
        self,
        mock_config: OrchestratorAgentConfig,
        mock_azure_client: MagicMock,
        mock_thread: MagicMock,
    ) -> None:
        """Test that ensure_thread_exists creates a new thread for new session."""
        from src.orchestrator.agent.llm import OrchestratorLLM
        from src.orchestrator.azure_agent import AgentType

        # Setup mock
        mock_azure_client.threads.create.return_value = mock_thread

        with patch(
            "src.orchestrator.agent.llm.create_agents_client",
            return_value=mock_azure_client,
        ):
            llm = OrchestratorLLM(mock_config)
            thread_id = llm.ensure_thread_exists("sess_new", AgentType.ROUTER)

        assert thread_id == "thread_test_123"
        mock_azure_client.threads.create.assert_called_once()
        # Verify metadata was passed
        call_kwargs = mock_azure_client.threads.create.call_args[1]
        assert call_kwargs["metadata"]["session_id"] == "sess_new"
        assert call_kwargs["metadata"]["agent_type"] == "router"

    def test_ensure_thread_exists_returns_cached_per_agent(
        self,
        mock_config: OrchestratorAgentConfig,
        mock_azure_client: MagicMock,
        mock_thread: MagicMock,
    ) -> None:
        """Test that ensure_thread_exists returns cached thread on second call."""
        from src.orchestrator.agent.llm import OrchestratorLLM
        from src.orchestrator.azure_agent import AgentType

        mock_azure_client.threads.create.return_value = mock_thread
        mock_azure_client.threads.get.return_value = mock_thread

        with patch(
            "src.orchestrator.agent.llm.create_agents_client",
            return_value=mock_azure_client,
        ):
            llm = OrchestratorLLM(mock_config)

            # First call creates thread
            thread_id1 = llm.ensure_thread_exists("sess_123", AgentType.ROUTER)

            # Second call should return cached
            thread_id2 = llm.ensure_thread_exists("sess_123", AgentType.ROUTER)

        assert thread_id1 == thread_id2
        # Should only create once, then verify on second call
        assert mock_azure_client.threads.create.call_count == 1
        assert mock_azure_client.threads.get.call_count == 1

    def test_ensure_thread_exists_separates_agent_types(
        self,
        mock_config: OrchestratorAgentConfig,
        mock_azure_client: MagicMock,
    ) -> None:
        """Test that different agent types get different threads."""
        from src.orchestrator.agent.llm import OrchestratorLLM
        from src.orchestrator.azure_agent import AgentType

        # Create different threads for different agent types
        router_thread = MagicMock()
        router_thread.id = "thread_router_001"
        classifier_thread = MagicMock()
        classifier_thread.id = "thread_classifier_001"

        mock_azure_client.threads.create.side_effect = [
            router_thread,
            classifier_thread,
        ]

        with patch(
            "src.orchestrator.agent.llm.create_agents_client",
            return_value=mock_azure_client,
        ):
            llm = OrchestratorLLM(mock_config)

            router_id = llm.ensure_thread_exists("sess_123", AgentType.ROUTER)
            classifier_id = llm.ensure_thread_exists("sess_123", AgentType.CLASSIFIER)

        assert router_id == "thread_router_001"
        assert classifier_id == "thread_classifier_001"
        assert router_id != classifier_id
        assert mock_azure_client.threads.create.call_count == 2

    def test_ensure_thread_handles_expired(
        self,
        mock_config: OrchestratorAgentConfig,
        mock_azure_client: MagicMock,
        mock_thread: MagicMock,
    ) -> None:
        """Test that ensure_thread_exists handles expired threads gracefully."""
        from src.orchestrator.agent.llm import OrchestratorLLM
        from src.orchestrator.azure_agent import AgentType

        # First call creates thread
        old_thread = MagicMock()
        old_thread.id = "thread_old_expired"

        new_thread = MagicMock()
        new_thread.id = "thread_new_fresh"

        mock_azure_client.threads.create.side_effect = [old_thread, new_thread]

        # Simulate NotFoundError on get_thread (thread expired)
        mock_azure_client.threads.get.side_effect = Exception("NotFound: Thread does not exist")

        with patch(
            "src.orchestrator.agent.llm.create_agents_client",
            return_value=mock_azure_client,
        ):
            llm = OrchestratorLLM(mock_config)

            # First call creates thread
            thread_id1 = llm.ensure_thread_exists("sess_123", AgentType.ROUTER)
            assert thread_id1 == "thread_old_expired"

            # Second call: get_thread fails (expired), should create new
            thread_id2 = llm.ensure_thread_exists("sess_123", AgentType.ROUTER)
            assert thread_id2 == "thread_new_fresh"

        # Should have created two threads (initial + replacement after expiry)
        assert mock_azure_client.threads.create.call_count == 2

    def test_ensure_thread_works_with_string_agent_type(
        self,
        mock_config: OrchestratorAgentConfig,
        mock_azure_client: MagicMock,
        mock_thread: MagicMock,
    ) -> None:
        """Test that ensure_thread_exists works with string agent type."""
        from src.orchestrator.agent.llm import OrchestratorLLM

        mock_azure_client.threads.create.return_value = mock_thread

        with patch(
            "src.orchestrator.agent.llm.create_agents_client",
            return_value=mock_azure_client,
        ):
            llm = OrchestratorLLM(mock_config)
            thread_id = llm.ensure_thread_exists("sess_123", "classifier")

        assert thread_id == "thread_test_123"


class TestGetThreadId:
    """Tests for get_thread_id method."""

    def test_get_thread_id_returns_none_for_new_session(
        self,
        mock_config: OrchestratorAgentConfig,
    ) -> None:
        """Test that get_thread_id returns None for new sessions."""
        from src.orchestrator.agent.llm import OrchestratorLLM
        from src.orchestrator.azure_agent import AgentType

        llm = OrchestratorLLM(mock_config)

        assert llm.get_thread_id("sess_new", AgentType.ROUTER) is None
        assert llm.get_thread_id("sess_new", "classifier") is None

    def test_get_thread_id_returns_cached(
        self,
        mock_config: OrchestratorAgentConfig,
        mock_azure_client: MagicMock,
        mock_thread: MagicMock,
    ) -> None:
        """Test that get_thread_id returns cached thread after creation."""
        from src.orchestrator.agent.llm import OrchestratorLLM
        from src.orchestrator.azure_agent import AgentType

        mock_azure_client.threads.create.return_value = mock_thread

        with patch(
            "src.orchestrator.agent.llm.create_agents_client",
            return_value=mock_azure_client,
        ):
            llm = OrchestratorLLM(mock_config)

            # Create thread first
            llm.ensure_thread_exists("sess_123", AgentType.ROUTER)

            # Now get_thread_id should return it
            thread_id = llm.get_thread_id("sess_123", AgentType.ROUTER)

        assert thread_id == "thread_test_123"


class TestClearSessionThreads:
    """Tests for clear_session_threads method."""

    def test_clear_session_threads(
        self,
        mock_config: OrchestratorAgentConfig,
        mock_azure_client: MagicMock,
        mock_thread: MagicMock,
    ) -> None:
        """Test that clear_session_threads removes session data."""
        from src.orchestrator.agent.llm import OrchestratorLLM
        from src.orchestrator.azure_agent import AgentType

        mock_azure_client.threads.create.return_value = mock_thread

        with patch(
            "src.orchestrator.agent.llm.create_agents_client",
            return_value=mock_azure_client,
        ):
            llm = OrchestratorLLM(mock_config)

            # Create thread
            llm.ensure_thread_exists("sess_123", AgentType.ROUTER)
            assert llm.get_thread_id("sess_123", AgentType.ROUTER) is not None

            # Clear session
            llm.clear_session_threads("sess_123")
            assert llm.get_thread_id("sess_123", AgentType.ROUTER) is None

    def test_clear_nonexistent_session_is_safe(
        self,
        mock_config: OrchestratorAgentConfig,
    ) -> None:
        """Test that clearing non-existent session doesn't raise."""
        from src.orchestrator.agent.llm import OrchestratorLLM

        llm = OrchestratorLLM(mock_config)

        # Should not raise
        llm.clear_session_threads("nonexistent_session")


# =============================================================================
# RUN MANAGEMENT TESTS
# =============================================================================


class TestCreateRun:
    """Tests for create_run method."""

    @pytest.mark.asyncio
    async def test_create_run_processes_message(
        self,
        mock_config: OrchestratorAgentConfig,
        mock_azure_client: MagicMock,
        mock_thread: MagicMock,
        mock_run_completed: MagicMock,
    ) -> None:
        """Test that create_run processes a message through the agent."""
        from src.orchestrator.agent.llm import OrchestratorLLM
        from src.orchestrator.azure_agent import AgentType

        # Setup mocks
        mock_azure_client.threads.create.return_value = mock_thread
        mock_azure_client.messages.create.return_value = MagicMock()
        mock_azure_client.runs.create.return_value = mock_run_completed
        mock_azure_client.runs.get.return_value = mock_run_completed

        # Mock messages for text extraction
        mock_message = MagicMock()
        mock_message.role = "assistant"
        mock_content = MagicMock()
        mock_content.text = MagicMock()
        mock_content.text.value = "Here is your response."
        mock_message.content = [mock_content]

        mock_azure_client.messages.list.return_value = iter([mock_message])

        with patch(
            "src.orchestrator.agent.llm.create_agents_client",
            return_value=mock_azure_client,
        ):
            llm = OrchestratorLLM(mock_config)
            thread_id = llm.ensure_thread_exists("sess_123", AgentType.ROUTER)

            result = await llm.create_run(
                thread_id=thread_id,
                agent_type=AgentType.ROUTER,
                message="Plan a trip to Tokyo",
            )

        assert result.is_completed
        assert result.thread_id == thread_id
        assert result.id == "run_abc123"
        mock_azure_client.runs.create.assert_called()

    @pytest.mark.asyncio
    async def test_create_run_handles_tool_calls(
        self,
        mock_config: OrchestratorAgentConfig,
        mock_azure_client: MagicMock,
        mock_thread: MagicMock,
        mock_run_requires_action: MagicMock,
    ) -> None:
        """Test that create_run properly parses tool calls."""
        from src.orchestrator.agent.llm import OrchestratorLLM
        from src.orchestrator.azure_agent import AgentType

        mock_azure_client.threads.create.return_value = mock_thread
        mock_azure_client.messages.create.return_value = MagicMock()
        mock_azure_client.runs.create.return_value = mock_run_requires_action
        mock_azure_client.runs.get.return_value = mock_run_requires_action

        with patch(
            "src.orchestrator.agent.llm.create_agents_client",
            return_value=mock_azure_client,
        ):
            llm = OrchestratorLLM(mock_config)
            thread_id = llm.ensure_thread_exists("sess_123", AgentType.ROUTER)

            result = await llm.create_run(
                thread_id=thread_id,
                agent_type=AgentType.ROUTER,
                message="Plan a trip to Tokyo",
            )

        assert result.requires_action
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "workflow_turn"
        assert result.tool_calls[0].arguments == {"message": "Plan a trip to Tokyo"}
        assert result.tool_calls[0].id == "call_xyz789"

    @pytest.mark.asyncio
    async def test_create_run_handles_errors(
        self,
        mock_config: OrchestratorAgentConfig,
        mock_azure_client: MagicMock,
        mock_thread: MagicMock,
    ) -> None:
        """Test that create_run handles errors gracefully."""
        from src.orchestrator.agent.llm import OrchestratorLLM
        from src.orchestrator.azure_agent import AgentType

        mock_azure_client.threads.create.return_value = mock_thread
        mock_azure_client.messages.create.return_value = MagicMock()
        mock_azure_client.runs.create.side_effect = Exception(
            "Rate limit exceeded"
        )

        with patch(
            "src.orchestrator.agent.llm.create_agents_client",
            return_value=mock_azure_client,
        ):
            llm = OrchestratorLLM(mock_config)
            thread_id = llm.ensure_thread_exists("sess_123", AgentType.ROUTER)

            result = await llm.create_run(
                thread_id=thread_id,
                agent_type=AgentType.ROUTER,
                message="Plan a trip to Tokyo",
            )

        assert result.has_failed
        assert "Rate limit exceeded" in result.error_message

    @pytest.mark.asyncio
    async def test_create_run_with_string_agent_type(
        self,
        mock_config: OrchestratorAgentConfig,
        mock_azure_client: MagicMock,
        mock_thread: MagicMock,
        mock_run_completed: MagicMock,
    ) -> None:
        """Test that create_run works with string agent type."""
        from src.orchestrator.agent.llm import OrchestratorLLM

        mock_azure_client.threads.create.return_value = mock_thread
        mock_azure_client.messages.create.return_value = MagicMock()
        mock_azure_client.runs.create.return_value = mock_run_completed
        mock_azure_client.runs.get.return_value = mock_run_completed
        mock_azure_client.messages.list.return_value = iter([])

        with patch(
            "src.orchestrator.agent.llm.create_agents_client",
            return_value=mock_azure_client,
        ):
            llm = OrchestratorLLM(mock_config)
            thread_id = llm.ensure_thread_exists("sess_123", "router")

            result = await llm.create_run(
                thread_id=thread_id,
                agent_type="router",
                message="Hello",
            )

        assert result.is_completed


class TestSubmitToolOutputs:
    """Tests for submit_tool_outputs method."""

    @pytest.mark.asyncio
    async def test_submit_tool_outputs(
        self,
        mock_config: OrchestratorAgentConfig,
        mock_azure_client: MagicMock,
        mock_thread: MagicMock,
        mock_run_completed: MagicMock,
    ) -> None:
        """Test that submit_tool_outputs submits outputs and continues the run."""
        from src.orchestrator.agent.llm import OrchestratorLLM, ToolOutput

        mock_azure_client.threads.create.return_value = mock_thread
        mock_azure_client.runs.submit_tool_outputs.return_value = mock_run_completed
        mock_azure_client.runs.get.return_value = mock_run_completed
        mock_azure_client.messages.list.return_value = iter([])

        with patch(
            "src.orchestrator.agent.llm.create_agents_client",
            return_value=mock_azure_client,
        ):
            llm = OrchestratorLLM(mock_config)

            outputs = [
                ToolOutput(
                    tool_call_id="call_xyz789",
                    output='{"success": true, "message": "Trip planned"}',
                )
            ]

            result = await llm.submit_tool_outputs(
                run_id="run_needs_action",
                thread_id="thread_test_123",
                tool_outputs=outputs,
            )

        assert result.is_completed
        mock_azure_client.runs.submit_tool_outputs.assert_called_once()

        # Verify the tool outputs format
        call_kwargs = mock_azure_client.runs.submit_tool_outputs.call_args[1]
        assert call_kwargs["thread_id"] == "thread_test_123"
        assert call_kwargs["run_id"] == "run_needs_action"
        assert len(call_kwargs["tool_outputs"]) == 1
        assert call_kwargs["tool_outputs"][0]["tool_call_id"] == "call_xyz789"

    @pytest.mark.asyncio
    async def test_submit_tool_outputs_handles_errors(
        self,
        mock_config: OrchestratorAgentConfig,
        mock_azure_client: MagicMock,
    ) -> None:
        """Test that submit_tool_outputs handles errors gracefully."""
        from src.orchestrator.agent.llm import OrchestratorLLM, ToolOutput

        mock_azure_client.runs.submit_tool_outputs.side_effect = Exception(
            "Connection timeout"
        )

        with patch(
            "src.orchestrator.agent.llm.create_agents_client",
            return_value=mock_azure_client,
        ):
            llm = OrchestratorLLM(mock_config)

            outputs = [
                ToolOutput(
                    tool_call_id="call_xyz789",
                    output="result",
                )
            ]

            result = await llm.submit_tool_outputs(
                run_id="run_needs_action",
                thread_id="thread_test_123",
                tool_outputs=outputs,
            )

        assert result.has_failed
        assert "Connection timeout" in result.error_message


# =============================================================================
# CONFIGURATION TESTS
# =============================================================================


class TestOrchestratorLLMConfiguration:
    """Tests for OrchestratorLLM configuration loading."""

    def test_loads_agent_ids_from_env(
        self,
        mock_config: OrchestratorAgentConfig,
    ) -> None:
        """Test that OrchestratorLLM loads agent IDs from configuration."""
        from src.orchestrator.agent.llm import OrchestratorLLM
        from src.orchestrator.azure_agent import AgentType

        llm = OrchestratorLLM(mock_config)

        assert llm.get_agent_id(AgentType.ROUTER) == "asst_router_123"
        assert llm.get_agent_id(AgentType.CLASSIFIER) == "asst_classifier_456"
        assert llm.get_agent_id(AgentType.PLANNER) == "asst_planner_789"
        assert llm.get_agent_id(AgentType.QA) == "asst_qa_012"

    def test_config_property(
        self,
        mock_config: OrchestratorAgentConfig,
    ) -> None:
        """Test that config property returns the configuration."""
        from src.orchestrator.agent.llm import OrchestratorLLM

        llm = OrchestratorLLM(mock_config)

        assert llm.config == mock_config

    def test_client_is_lazy_loaded(
        self,
        mock_config: OrchestratorAgentConfig,
    ) -> None:
        """Test that the Azure client is lazily loaded."""
        from src.orchestrator.agent.llm import OrchestratorLLM

        llm = OrchestratorLLM(mock_config)

        # Client should not be loaded yet
        assert llm._client is None


# =============================================================================
# MODULE EXPORTS TESTS
# =============================================================================


class TestModuleExports:
    """Tests for module exports."""

    def test_module_exports_orchestrator_llm(self) -> None:
        """Test that OrchestratorLLM is exported from the module."""
        from src.orchestrator.agent import OrchestratorLLM

        assert OrchestratorLLM is not None

    def test_module_exports_run_result(self) -> None:
        """Test that RunResult is exported from the module."""
        from src.orchestrator.agent import RunResult

        assert RunResult is not None

    def test_module_exports_tool_call(self) -> None:
        """Test that ToolCall is exported from the module."""
        from src.orchestrator.agent import ToolCall

        assert ToolCall is not None

    def test_module_exports_tool_output(self) -> None:
        """Test that ToolOutput is exported from the module."""
        from src.orchestrator.agent import ToolOutput

        assert ToolOutput is not None
