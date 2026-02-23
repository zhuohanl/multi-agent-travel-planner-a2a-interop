"""Unit tests for ClarificationHandler.

Tests for:
- Handler calls clarifier agent with history injection
- Handler updates TripSpec from response
- Handler detects when clarification is complete
- Handler returns appropriate UI for approval checkpoint
- Stub mode works without A2A client
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.orchestrator.handlers.clarification import (
    ClarificationHandler,
    HandlerResult,
    PhaseHandler,
)
from src.orchestrator.models.conversation import AgentConversation
from src.orchestrator.models.workflow_state import (
    AgentA2AState,
    Phase,
    WorkflowState,
)
from src.orchestrator.state_gating import Action, WorkflowEvent
from src.orchestrator.storage import WorkflowStateData


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def workflow_state() -> WorkflowState:
    """Create a WorkflowState for testing."""
    return WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_test456",
        workflow_version=1,
        phase=Phase.CLARIFICATION,
        checkpoint=None,
        current_step="gathering",
    )


@pytest.fixture
def workflow_state_data() -> WorkflowStateData:
    """Create a WorkflowStateData for testing."""
    return WorkflowStateData(
        session_id="sess_test123",
        consultation_id="cons_test456",
        workflow_version=1,
        phase="clarification",
        checkpoint=None,
        current_step="gathering",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        etag="etag_123",
    )


@pytest.fixture
def mock_a2a_client() -> MagicMock:
    """Create a mock A2A client."""
    mock = MagicMock()
    mock.send_message = AsyncMock()
    return mock


@pytest.fixture
def mock_agent_registry() -> MagicMock:
    """Create a mock agent registry."""
    mock = MagicMock()
    mock.get.return_value = MagicMock(url="http://localhost:8001", timeout=120.0)
    return mock


@pytest.fixture
def mock_a2a_response() -> MagicMock:
    """Create a mock A2A response."""
    mock = MagicMock()
    mock.text = "Where would you like to go for your trip?"
    mock.context_id = "ctx_123"
    mock.task_id = "task_456"
    mock.is_complete = False
    mock.requires_input = True
    return mock


@pytest.fixture
def mock_complete_a2a_response() -> MagicMock:
    """Create a mock A2A response for completed clarification."""
    mock = MagicMock()
    mock.text = "Great! Here's your trip summary: Tokyo, March 10-17, 2 travelers."
    mock.context_id = "ctx_123"
    mock.task_id = None  # Task completed
    mock.is_complete = True
    mock.requires_input = False
    return mock


# ═══════════════════════════════════════════════════════════════════════════════
# Handler Creation Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestClarificationHandlerCreation:
    """Tests for ClarificationHandler initialization."""

    def test_handler_inherits_from_phase_handler(self) -> None:
        """ClarificationHandler should inherit from PhaseHandler."""
        assert issubclass(ClarificationHandler, PhaseHandler)

    def test_handler_creation_without_a2a_client(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
    ) -> None:
        """Handler can be created without A2A client (stub mode)."""
        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
        )
        assert handler is not None
        assert handler._a2a_client is None
        assert handler._agent_registry is None

    def test_handler_creation_with_a2a_client(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
        mock_a2a_client: MagicMock,
        mock_agent_registry: MagicMock,
    ) -> None:
        """Handler can be created with A2A client for agent communication."""
        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )
        assert handler._a2a_client is mock_a2a_client
        assert handler._agent_registry is mock_agent_registry


# ═══════════════════════════════════════════════════════════════════════════════
# Stub Mode Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestClarificationHandlerStubMode:
    """Tests for ClarificationHandler in stub mode (no A2A client)."""

    @pytest.mark.asyncio
    async def test_continue_clarification_stub_mode(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
    ) -> None:
        """Handler returns stub response when no A2A client configured."""
        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
        )

        result = await handler.execute(
            action=Action.CONTINUE_CLARIFICATION,
            message="I want to plan a trip to Tokyo",
        )

        assert isinstance(result, HandlerResult)
        assert result.response.success is True
        assert "trip" in result.response.message.lower()
        assert result.response.data.get("stub") is True
        assert result.response.data.get("requires_input") is True

    @pytest.mark.asyncio
    async def test_stub_mode_appends_to_conversation(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
    ) -> None:
        """Handler appends messages to conversation history in stub mode."""
        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
        )

        initial_count = workflow_state.clarifier_conversation.message_count

        await handler.execute(
            action=Action.CONTINUE_CLARIFICATION,
            message="I want to plan a trip",
        )

        # Should have added user + assistant messages
        assert workflow_state.clarifier_conversation.message_count == initial_count + 2

    @pytest.mark.asyncio
    async def test_start_clarification_works_like_continue(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
    ) -> None:
        """START_CLARIFICATION action works the same as CONTINUE_CLARIFICATION."""
        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
        )

        result = await handler.execute(
            action=Action.START_CLARIFICATION,
            message="I want to plan a trip",
        )

        assert result.response.success is True
        assert result.response.data.get("requires_input") is True


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Call Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestClarificationHandlerAgentCall:
    """Tests for ClarificationHandler calling clarifier agent."""

    @pytest.mark.asyncio
    async def test_handler_calls_agent_with_message(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
        mock_a2a_client: MagicMock,
        mock_agent_registry: MagicMock,
        mock_a2a_response: MagicMock,
    ) -> None:
        """Handler calls clarifier agent with user message."""
        mock_a2a_client.send_message.return_value = mock_a2a_response

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        await handler.execute(
            action=Action.CONTINUE_CLARIFICATION,
            message="I want to plan a trip to Tokyo",
        )

        mock_a2a_client.send_message.assert_called_once()
        call_kwargs = mock_a2a_client.send_message.call_args.kwargs
        assert call_kwargs["message"] == "I want to plan a trip to Tokyo"
        assert call_kwargs["agent_url"] == "http://localhost:8001"

    @pytest.mark.asyncio
    async def test_handler_injects_history(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
        mock_a2a_client: MagicMock,
        mock_agent_registry: MagicMock,
        mock_a2a_response: MagicMock,
    ) -> None:
        """Handler injects conversation history in A2A call."""
        mock_a2a_client.send_message.return_value = mock_a2a_response

        # Add some conversation history
        workflow_state.clarifier_conversation.append_turn(
            user_content="Hello",
            assistant_content="Hi there!",
        )

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        await handler.execute(
            action=Action.CONTINUE_CLARIFICATION,
            message="I want to plan a trip",
        )

        call_kwargs = mock_a2a_client.send_message.call_args.kwargs
        assert call_kwargs["history"] is not None
        assert len(call_kwargs["history"]) == 2  # user + assistant from append_turn
        assert call_kwargs["history_seq"] == 2

    @pytest.mark.asyncio
    async def test_handler_updates_agent_context(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
        mock_a2a_client: MagicMock,
        mock_agent_registry: MagicMock,
        mock_a2a_response: MagicMock,
    ) -> None:
        """Handler updates agent_context_ids with new context/task IDs."""
        mock_a2a_client.send_message.return_value = mock_a2a_response

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        await handler.execute(
            action=Action.CONTINUE_CLARIFICATION,
            message="I want to plan a trip",
        )

        clarifier_state = workflow_state.agent_context_ids.get("clarifier")
        assert clarifier_state is not None
        assert clarifier_state.context_id == "ctx_123"
        assert clarifier_state.task_id == "task_456"

    @pytest.mark.asyncio
    async def test_handler_appends_conversation_turn(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
        mock_a2a_client: MagicMock,
        mock_agent_registry: MagicMock,
        mock_a2a_response: MagicMock,
    ) -> None:
        """Handler appends conversation turn after agent call."""
        mock_a2a_client.send_message.return_value = mock_a2a_response

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        initial_count = workflow_state.clarifier_conversation.message_count

        await handler.execute(
            action=Action.CONTINUE_CLARIFICATION,
            message="I want to plan a trip to Tokyo",
        )

        # Should have added user + assistant messages
        assert workflow_state.clarifier_conversation.message_count == initial_count + 2

    @pytest.mark.asyncio
    async def test_handler_returns_agent_response(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
        mock_a2a_client: MagicMock,
        mock_agent_registry: MagicMock,
        mock_a2a_response: MagicMock,
    ) -> None:
        """Handler returns agent's response message."""
        mock_a2a_client.send_message.return_value = mock_a2a_response

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        result = await handler.execute(
            action=Action.CONTINUE_CLARIFICATION,
            message="I want to plan a trip",
        )

        assert result.response.success is True
        assert result.response.message == mock_a2a_response.text


# ═══════════════════════════════════════════════════════════════════════════════
# Clarification Complete Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestClarificationHandlerCompletion:
    """Tests for ClarificationHandler detecting completion."""

    @pytest.mark.asyncio
    async def test_handler_detects_completion(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
        mock_a2a_client: MagicMock,
        mock_agent_registry: MagicMock,
        mock_complete_a2a_response: MagicMock,
    ) -> None:
        """Handler detects when clarification is complete."""
        mock_a2a_client.send_message.return_value = mock_complete_a2a_response

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        result = await handler.execute(
            action=Action.CONTINUE_CLARIFICATION,
            message="That looks great, let's proceed",
        )

        assert result.response.success is True
        assert result.response.data.get("checkpoint") == "trip_spec_approval"

    @pytest.mark.asyncio
    async def test_handler_sets_checkpoint_on_completion(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
        mock_a2a_client: MagicMock,
        mock_agent_registry: MagicMock,
        mock_complete_a2a_response: MagicMock,
    ) -> None:
        """Handler sets checkpoint when clarification is complete."""
        mock_a2a_client.send_message.return_value = mock_complete_a2a_response

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        await handler.execute(
            action=Action.CONTINUE_CLARIFICATION,
            message="That looks great",
        )

        assert workflow_state.checkpoint == "trip_spec_approval"
        assert workflow_state.current_step == "approval"

    @pytest.mark.asyncio
    async def test_handler_returns_ui_actions_on_completion(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
        mock_a2a_client: MagicMock,
        mock_agent_registry: MagicMock,
        mock_complete_a2a_response: MagicMock,
    ) -> None:
        """Handler returns UI actions for approval on completion."""
        mock_a2a_client.send_message.return_value = mock_complete_a2a_response

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        result = await handler.execute(
            action=Action.CONTINUE_CLARIFICATION,
            message="That looks great",
        )

        assert result.response.ui is not None
        assert len(result.response.ui.actions) == 2

        action_labels = [a.label for a in result.response.ui.actions]
        assert "Approve" in action_labels
        assert "Request Changes" in action_labels

    @pytest.mark.asyncio
    async def test_completion_clears_task_id(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
        mock_a2a_client: MagicMock,
        mock_agent_registry: MagicMock,
        mock_complete_a2a_response: MagicMock,
    ) -> None:
        """Handler clears task_id when task is complete."""
        mock_a2a_client.send_message.return_value = mock_complete_a2a_response

        # Set initial task_id
        workflow_state.agent_context_ids["clarifier"] = AgentA2AState(
            context_id="ctx_old",
            task_id="task_old",
        )

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        await handler.execute(
            action=Action.CONTINUE_CLARIFICATION,
            message="That looks great",
        )

        clarifier_state = workflow_state.agent_context_ids["clarifier"]
        assert clarifier_state.context_id == "ctx_123"
        assert clarifier_state.task_id is None  # Cleared because task complete


# ═══════════════════════════════════════════════════════════════════════════════
# Approve Trip Spec Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestClarificationHandlerApproval:
    """Tests for ClarificationHandler handling trip spec approval."""

    @pytest.mark.asyncio
    async def test_approve_transitions_to_discovery(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
    ) -> None:
        """APPROVE_TRIP_SPEC transitions to DISCOVERY_IN_PROGRESS phase."""
        # Set up state as if clarification just completed
        workflow_state.checkpoint = "trip_spec_approval"
        workflow_state.current_step = "approval"

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
        )

        result = await handler.execute(
            action=Action.APPROVE_TRIP_SPEC,
            message="Looks good, let's go!",
        )

        assert result.response.success is True
        assert workflow_state.phase == Phase.DISCOVERY_IN_PROGRESS
        assert workflow_state.checkpoint is None
        assert workflow_state.current_step == "running"

    @pytest.mark.asyncio
    async def test_approve_syncs_state_data(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
    ) -> None:
        """APPROVE_TRIP_SPEC syncs changes to state_data."""
        workflow_state.checkpoint = "trip_spec_approval"

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
        )

        result = await handler.execute(
            action=Action.APPROVE_TRIP_SPEC,
            message="Approved!",
        )

        assert result.state_data.phase == "discovery_in_progress"
        assert result.state_data.checkpoint is None

    @pytest.mark.asyncio
    async def test_approve_creates_discovery_job(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
    ) -> None:
        """APPROVE_TRIP_SPEC creates a discovery job and sets current_job_id."""
        from src.orchestrator.storage.discovery_jobs import InMemoryDiscoveryJobStore

        workflow_state.checkpoint = "trip_spec_approval"
        discovery_job_store = InMemoryDiscoveryJobStore()

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
            discovery_job_store=discovery_job_store,
        )

        result = await handler.execute(
            action=Action.APPROVE_TRIP_SPEC,
            message="Approved!",
        )

        # Check job was created
        assert result.response.success is True
        assert "job_id" in result.response.data
        assert "stream_url" in result.response.data

        # Check state has job reference
        assert workflow_state.current_job_id is not None
        assert workflow_state.current_job_id.startswith("job_")

        # Check job was saved to store
        job = await discovery_job_store.get_job(
            workflow_state.current_job_id, workflow_state.consultation_id
        )
        assert job is not None
        assert job.status.value == "running"
        assert len(job.agent_progress) == 5  # 5 discovery agents

    @pytest.mark.asyncio
    async def test_approve_returns_stream_url(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
    ) -> None:
        """APPROVE_TRIP_SPEC returns stream_url for client polling."""
        workflow_state.checkpoint = "trip_spec_approval"

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
        )

        result = await handler.execute(
            action=Action.APPROVE_TRIP_SPEC,
            message="Approved!",
        )

        assert "stream_url" in result.response.data
        assert workflow_state.session_id in result.response.data["stream_url"]
        assert "/discovery/stream" in result.response.data["stream_url"]

    @pytest.mark.asyncio
    async def test_approve_returns_ui_directive(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
    ) -> None:
        """APPROVE_TRIP_SPEC returns UI directive for background polling."""
        workflow_state.checkpoint = "trip_spec_approval"

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
        )

        result = await handler.execute(
            action=Action.APPROVE_TRIP_SPEC,
            message="Approved!",
        )

        assert result.response.ui is not None
        assert len(result.response.ui.actions) > 0
        assert result.response.ui.text_input is False


# ═══════════════════════════════════════════════════════════════════════════════
# Modification Request Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestClarificationHandlerModification:
    """Tests for ClarificationHandler handling modification requests."""

    @pytest.mark.asyncio
    async def test_modification_clears_checkpoint(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
    ) -> None:
        """REQUEST_MODIFICATION clears the approval checkpoint."""
        workflow_state.checkpoint = "trip_spec_approval"
        workflow_state.current_step = "approval"

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
        )

        await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="I want to change the dates",
        )

        assert workflow_state.checkpoint is None
        assert workflow_state.current_step == "gathering"

    @pytest.mark.asyncio
    async def test_modification_continues_clarification(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
    ) -> None:
        """REQUEST_MODIFICATION continues clarification dialog."""
        workflow_state.checkpoint = "trip_spec_approval"
        initial_count = workflow_state.clarifier_conversation.message_count

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
        )

        result = await handler.execute(
            action=Action.REQUEST_MODIFICATION,
            message="I want to change the dates",
        )

        assert result.response.success is True
        # Should have continued clarification (stub adds 2 messages)
        assert workflow_state.clarifier_conversation.message_count == initial_count + 2


# ═══════════════════════════════════════════════════════════════════════════════
# Error Handling Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestClarificationHandlerErrors:
    """Tests for ClarificationHandler error handling."""

    @pytest.mark.asyncio
    async def test_handler_catches_agent_errors(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
        mock_a2a_client: MagicMock,
        mock_agent_registry: MagicMock,
    ) -> None:
        """Handler catches and reports agent communication errors."""
        mock_a2a_client.send_message.side_effect = Exception("Connection failed")

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        result = await handler.execute(
            action=Action.CONTINUE_CLARIFICATION,
            message="Plan a trip",
        )

        assert result.response.success is False
        assert "trouble" in result.response.message.lower()

    @pytest.mark.asyncio
    async def test_invalid_action_falls_back_to_continue(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
    ) -> None:
        """Invalid action for phase falls back to continue_clarification."""
        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
        )

        # BOOK_SINGLE_ITEM is not valid in CLARIFICATION phase
        result = await handler.execute(
            action=Action.BOOK_SINGLE_ITEM,
            message="Book something",
        )

        # Should have treated it as continue_clarification (stub mode)
        assert result.response.success is True


# ═══════════════════════════════════════════════════════════════════════════════
# State Sync Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestClarificationHandlerStateSync:
    """Tests for ClarificationHandler state synchronization."""

    @pytest.mark.asyncio
    async def test_syncs_phase_to_state_data(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
    ) -> None:
        """Handler syncs phase changes to state_data."""
        # Set up state for approval
        workflow_state.checkpoint = "trip_spec_approval"

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
        )

        await handler.execute(
            action=Action.APPROVE_TRIP_SPEC,
            message="Approved!",
        )

        assert workflow_state_data.phase == "discovery_in_progress"

    @pytest.mark.asyncio
    async def test_syncs_agent_context_to_state_data(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
        mock_a2a_client: MagicMock,
        mock_agent_registry: MagicMock,
        mock_a2a_response: MagicMock,
    ) -> None:
        """Handler syncs agent context IDs to state_data."""
        mock_a2a_client.send_message.return_value = mock_a2a_response

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        await handler.execute(
            action=Action.CONTINUE_CLARIFICATION,
            message="Plan a trip",
        )

        contexts = workflow_state_data.agent_context_ids
        assert "clarifier" in contexts
        assert contexts["clarifier"]["context_id"] == "ctx_123"

    @pytest.mark.asyncio
    async def test_updates_timestamp_on_action(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
    ) -> None:
        """Handler updates updated_at timestamp."""
        original_time = workflow_state_data.updated_at

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
        )

        await handler.execute(
            action=Action.CONTINUE_CLARIFICATION,
            message="Plan a trip",
        )

        assert workflow_state_data.updated_at >= original_time

    @pytest.mark.asyncio
    async def test_syncs_checkpoint_to_state_data(
        self,
        workflow_state: WorkflowState,
        workflow_state_data: WorkflowStateData,
        mock_a2a_client: MagicMock,
        mock_agent_registry: MagicMock,
        mock_complete_a2a_response: MagicMock,
    ) -> None:
        """Handler syncs checkpoint to state_data when clarification completes."""
        mock_a2a_client.send_message.return_value = mock_complete_a2a_response

        handler = ClarificationHandler(
            state=workflow_state,
            state_data=workflow_state_data,
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        await handler.execute(
            action=Action.CONTINUE_CLARIFICATION,
            message="Looks good!",
        )

        assert workflow_state_data.checkpoint == "trip_spec_approval"
        assert workflow_state_data.current_step == "approval"
