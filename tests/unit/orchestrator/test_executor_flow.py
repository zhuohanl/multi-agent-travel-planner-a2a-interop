"""
Unit tests for OrchestratorExecutor request flow wiring.

Tests the complete flow from A2A request through routing to handler dispatch
and state persistence, as specified in ORCH-085.

Tests cover:
- Executor routes active session to workflow_turn
- Executor routes no session to LLM (or workflow_turn fallback)
- workflow_turn dispatches to correct handler based on phase
- State is persisted after handler execution
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.orchestrator.executor import OrchestratorAgent, OrchestratorExecutor
from src.orchestrator.models.workflow_state import Phase, WorkflowState
from src.orchestrator.routing.layer1 import RouteResult, RouteTarget
from src.shared.a2a.base_agent_executor import AgentStreamChunk


# ═══════════════════════════════════════════════════════════════════════════════
# Test Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_workflow_store() -> MagicMock:
    """Create a mock WorkflowStoreProtocol."""
    store = MagicMock()
    store.get_by_session = AsyncMock(return_value=None)
    store.save = AsyncMock(return_value="new_etag_123")
    return store


@pytest.fixture
def mock_a2a_client() -> MagicMock:
    """Create a mock A2AClientWrapper."""
    client = MagicMock()
    client.send_message = AsyncMock(return_value=MagicMock(
        text="Mock response",
        is_complete=True,
        context_id="ctx_123",
    ))
    return client


@pytest.fixture
def mock_agent_registry() -> MagicMock:
    """Create a mock AgentRegistry."""
    registry = MagicMock()
    registry.get = MagicMock(return_value=MagicMock(
        url="http://localhost:8001",
        timeout=30.0,
    ))
    return registry


@pytest.fixture
def sample_workflow_state() -> WorkflowState:
    """Create a sample WorkflowState for testing."""
    return WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_test456",
        phase=Phase.CLARIFICATION,
        checkpoint=None,
        workflow_version=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test: Executor Routes Active Session to workflow_turn
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecutorRoutesActiveSession:
    """Test that executor routes active sessions to workflow_turn (Layer 1a)."""

    @pytest.mark.asyncio
    async def test_executor_routes_active_session_to_workflow_turn(
        self,
        mock_workflow_store: MagicMock,
        sample_workflow_state: WorkflowState,
    ) -> None:
        """Test that messages with active session are routed to workflow_turn."""
        # Configure store to return existing state
        mock_workflow_store.get_by_session = AsyncMock(return_value=sample_workflow_state)

        agent = OrchestratorAgent(workflow_store=mock_workflow_store)

        chunks = []
        async for chunk in agent.stream(
            user_input="I want to change my destination",
            session_id=sample_workflow_state.session_id,
        ):
            chunks.append(chunk)

        # Should have processed the request
        assert len(chunks) >= 1
        # State should have been loaded (may be called multiple times for routing+load)
        assert mock_workflow_store.get_by_session.call_count >= 1
        mock_workflow_store.get_by_session.assert_called_with(
            sample_workflow_state.session_id
        )

    @pytest.mark.asyncio
    async def test_active_session_always_routes_to_workflow_turn(
        self,
        mock_workflow_store: MagicMock,
        sample_workflow_state: WorkflowState,
    ) -> None:
        """Test Layer 1a: active session means workflow_turn regardless of message."""
        mock_workflow_store.get_by_session = AsyncMock(return_value=sample_workflow_state)

        agent = OrchestratorAgent(workflow_store=mock_workflow_store)

        # Even utility-like messages should go to workflow_turn with active session
        messages = [
            "convert 100 USD to EUR",  # Would be Layer 1b without session
            "What's the weather in Tokyo?",  # Would be Layer 1b without session
            "Plan my trip",  # Normal workflow message
        ]

        for message in messages:
            chunks = []
            async for chunk in agent.stream(
                user_input=message,
                session_id=sample_workflow_state.session_id,
            ):
                chunks.append(chunk)

            # Each should result in at least one chunk
            assert len(chunks) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# Test: Executor Routes No Session to LLM
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecutorRoutesNoSession:
    """Test that executor routes messages without session through Layer 1b/1c."""

    @pytest.mark.asyncio
    async def test_executor_routes_no_session_to_llm(
        self,
        mock_workflow_store: MagicMock,
    ) -> None:
        """Test that messages without session go through routing layers."""
        # No existing state
        mock_workflow_store.get_by_session = AsyncMock(return_value=None)

        agent = OrchestratorAgent(workflow_store=mock_workflow_store)

        chunks = []
        async for chunk in agent.stream(
            user_input="Plan a trip to Paris",
            session_id="new_session_123",
        ):
            chunks.append(chunk)

        # Should have processed the request (defaults to workflow_turn without LLM)
        assert len(chunks) >= 1

    @pytest.mark.asyncio
    async def test_utility_pattern_routes_to_utility_layer_1b(
        self,
        mock_workflow_store: MagicMock,
    ) -> None:
        """Test Layer 1b: utility patterns route to utility handlers."""
        mock_workflow_store.get_by_session = AsyncMock(return_value=None)

        agent = OrchestratorAgent(workflow_store=mock_workflow_store)

        # Test currency pattern
        chunks = []
        async for chunk in agent.stream(
            user_input="convert 100 USD to EUR",
            session_id="new_session_123",
        ):
            chunks.append(chunk)

        assert len(chunks) >= 1
        # Response should mention currencies
        response_text = chunks[0].get("content", "")
        assert "USD" in response_text or "EUR" in response_text

    @pytest.mark.asyncio
    async def test_weather_pattern_routes_to_utility_layer_1b(
        self,
        mock_workflow_store: MagicMock,
    ) -> None:
        """Test Layer 1b: weather patterns route to weather utility."""
        mock_workflow_store.get_by_session = AsyncMock(return_value=None)

        agent = OrchestratorAgent(workflow_store=mock_workflow_store)

        chunks = []
        async for chunk in agent.stream(
            user_input="weather in Tokyo",
            session_id="new_session_123",
        ):
            chunks.append(chunk)

        assert len(chunks) >= 1
        response_text = chunks[0].get("content", "")
        assert "Tokyo" in response_text or "weather" in response_text.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# Test: workflow_turn Dispatches Correct Handler
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkflowTurnDispatchesHandler:
    """Test that workflow_turn dispatches to the correct handler based on phase."""

    @pytest.mark.asyncio
    async def test_workflow_turn_dispatches_correct_handler(
        self,
        mock_workflow_store: MagicMock,
        sample_workflow_state: WorkflowState,
    ) -> None:
        """Test that workflow_turn uses ClarificationHandler in CLARIFICATION phase."""
        from src.orchestrator.tools.workflow_turn import (
            UnifiedWorkflowTurnContext,
            set_unified_workflow_turn_context,
            workflow_turn,
        )
        from src.shared.storage import InMemoryWorkflowStore

        # Use in-memory store
        store = InMemoryWorkflowStore()
        await store.save(sample_workflow_state)

        # Set up context
        context = UnifiedWorkflowTurnContext(workflow_store=store)
        set_unified_workflow_turn_context(context)

        try:
            result = await workflow_turn(
                session_ref={"session_id": sample_workflow_state.session_id},
                message="I want to go to Tokyo",
            )

            # Should succeed and mention clarification phase
            assert result.success is True
            assert result.status is not None
            assert result.status.get("phase") == "clarification"
        finally:
            # Clean up global context
            set_unified_workflow_turn_context(None)  # type: ignore

    @pytest.mark.asyncio
    async def test_discovery_phase_uses_discovery_handler(
        self,
    ) -> None:
        """Test that DISCOVERY phases use DiscoveryHandler."""
        from src.orchestrator.tools.workflow_turn import (
            UnifiedWorkflowTurnContext,
            set_unified_workflow_turn_context,
            workflow_turn,
        )
        from src.shared.storage import InMemoryWorkflowStore

        # Create state in discovery phase
        state = WorkflowState(
            session_id="sess_discovery",
            consultation_id="cons_discovery",
            phase=Phase.DISCOVERY_IN_PROGRESS,
            checkpoint=None,
            workflow_version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        store = InMemoryWorkflowStore()
        await store.save(state)

        context = UnifiedWorkflowTurnContext(workflow_store=store)
        set_unified_workflow_turn_context(context)

        try:
            result = await workflow_turn(
                session_ref={"session_id": state.session_id},
                message="Check progress",
            )

            # Should succeed with discovery phase
            assert result.success is True
            assert result.status is not None
            # Phase could be discovery_in_progress or discovery_planning
            phase = result.status.get("phase", "").lower()
            assert "discovery" in phase
        finally:
            set_unified_workflow_turn_context(None)  # type: ignore


# ═══════════════════════════════════════════════════════════════════════════════
# Test: State Persisted After Handler Execution
# ═══════════════════════════════════════════════════════════════════════════════


class TestStatePersistence:
    """Test that state is persisted correctly after handler execution."""

    @pytest.mark.asyncio
    async def test_state_persisted_after_handler_execution(
        self,
    ) -> None:
        """Test that state changes are saved after workflow_turn completes."""
        from src.orchestrator.tools.workflow_turn import (
            UnifiedWorkflowTurnContext,
            set_unified_workflow_turn_context,
            workflow_turn,
        )
        from src.shared.storage import InMemoryWorkflowStore

        store = InMemoryWorkflowStore()

        # Create initial state
        initial_state = WorkflowState(
            session_id="sess_persist_test",
            consultation_id="cons_persist_test",
            phase=Phase.CLARIFICATION,
            checkpoint=None,
            workflow_version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await store.save(initial_state)

        context = UnifiedWorkflowTurnContext(workflow_store=store)
        set_unified_workflow_turn_context(context)

        try:
            # Make a workflow_turn call
            result = await workflow_turn(
                session_ref={"session_id": initial_state.session_id},
                message="I want to visit Paris",
            )

            assert result.success is True

            # Verify state was saved (updated_at should change)
            saved_state = await store.get_by_session(initial_state.session_id)
            assert saved_state is not None
            # State should have been updated
            assert saved_state.updated_at >= initial_state.updated_at

        finally:
            set_unified_workflow_turn_context(None)  # type: ignore

    @pytest.mark.asyncio
    async def test_new_state_created_for_new_session(
        self,
    ) -> None:
        """Test that new state is created for sessions without existing state."""
        from src.orchestrator.tools.workflow_turn import (
            UnifiedWorkflowTurnContext,
            set_unified_workflow_turn_context,
            workflow_turn,
        )
        from src.shared.storage import InMemoryWorkflowStore

        store = InMemoryWorkflowStore()

        context = UnifiedWorkflowTurnContext(workflow_store=store)
        set_unified_workflow_turn_context(context)

        try:
            # Call with a new session_id
            new_session_id = "brand_new_session"
            result = await workflow_turn(
                session_ref={"session_id": new_session_id},
                message="Plan a trip to Tokyo",
            )

            assert result.success is True

            # Verify new state was created
            saved_state = await store.get_by_session(new_session_id)
            assert saved_state is not None
            assert saved_state.session_id == new_session_id
            assert saved_state.phase == Phase.CLARIFICATION

        finally:
            set_unified_workflow_turn_context(None)  # type: ignore


# ═══════════════════════════════════════════════════════════════════════════════
# Test: A2A Client and Registry Wiring
# ═══════════════════════════════════════════════════════════════════════════════


class TestA2AClientWiring:
    """Test that A2A client and registry are properly wired through executor."""

    def test_executor_accepts_a2a_client(
        self,
        mock_a2a_client: MagicMock,
        mock_agent_registry: MagicMock,
    ) -> None:
        """Test that executor accepts and stores A2A client."""
        executor = OrchestratorExecutor(
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        assert executor.a2a_client is mock_a2a_client
        assert executor.agent_registry is mock_agent_registry

    def test_executor_passes_a2a_client_to_agent(
        self,
        mock_a2a_client: MagicMock,
        mock_agent_registry: MagicMock,
    ) -> None:
        """Test that executor passes A2A client to agent."""
        executor = OrchestratorExecutor(
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        # Agent should have the A2A client
        assert executor.agent.a2a_client is mock_a2a_client
        assert executor.agent.agent_registry is mock_agent_registry

    def test_agent_accepts_a2a_client(
        self,
        mock_a2a_client: MagicMock,
        mock_agent_registry: MagicMock,
        mock_workflow_store: MagicMock,
    ) -> None:
        """Test that agent accepts and stores A2A client."""
        agent = OrchestratorAgent(
            workflow_store=mock_workflow_store,
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        assert agent.a2a_client is mock_a2a_client
        assert agent.agent_registry is mock_agent_registry


# ═══════════════════════════════════════════════════════════════════════════════
# Test: Workflow Turn Context Setup
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkflowTurnContextSetup:
    """Test that workflow_turn context is properly set up."""

    def test_agent_sets_up_workflow_turn_context(
        self,
        mock_workflow_store: MagicMock,
    ) -> None:
        """Test that OrchestratorAgent sets up workflow_turn context."""
        from src.orchestrator.tools.workflow_turn import (
            get_unified_workflow_turn_context,
        )

        # Clear any existing context first
        from src.orchestrator.tools.workflow_turn import (
            set_unified_workflow_turn_context,
        )
        set_unified_workflow_turn_context(None)  # type: ignore

        agent = OrchestratorAgent(workflow_store=mock_workflow_store)

        # Context should be set
        context = get_unified_workflow_turn_context()
        assert context is not None
        assert context.workflow_store is mock_workflow_store

    def test_agent_context_includes_a2a_client(
        self,
        mock_workflow_store: MagicMock,
        mock_a2a_client: MagicMock,
        mock_agent_registry: MagicMock,
    ) -> None:
        """Test that context includes A2A client and registry."""
        from src.orchestrator.tools.workflow_turn import (
            get_unified_workflow_turn_context,
            set_unified_workflow_turn_context,
        )

        # Clear context
        set_unified_workflow_turn_context(None)  # type: ignore

        agent = OrchestratorAgent(
            workflow_store=mock_workflow_store,
            a2a_client=mock_a2a_client,
            agent_registry=mock_agent_registry,
        )

        context = get_unified_workflow_turn_context()
        assert context is not None
        assert context.a2a_client is mock_a2a_client
        assert context.agent_registry is mock_agent_registry
