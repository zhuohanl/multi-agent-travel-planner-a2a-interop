"""
Unit tests for WorkflowStoreProtocol integration.

Per ORCH-098: Tests validate that:
1. Executor uses workflow store factory
2. Session manager uses workflow store lookup chain
3. workflow_turn saves state via protocol

These tests use InMemoryWorkflowStore to validate integration without Cosmos DB.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.orchestrator.executor import OrchestratorAgent, OrchestratorExecutor
from src.orchestrator.models.session_ref import SessionRef
from src.orchestrator.models.workflow_state import Phase, WorkflowState
from src.orchestrator.session_manager import (
    UnifiedSessionManager,
    UnifiedSessionManagerResult,
    unified_load_or_create_state,
)
from src.orchestrator.tools.workflow_turn import (
    UnifiedWorkflowTurnContext,
    set_unified_workflow_turn_context,
    get_unified_workflow_turn_context,
    workflow_turn_with_unified_store,
)
from src.shared.storage import (
    InMemoryWorkflowStore,
    WorkflowStoreProtocol,
    create_workflow_store,
)


class TestExecutorUsesWorkflowStoreFactory:
    """Tests for ORCH-098: Executor instantiation with WorkflowStoreProtocol."""

    def test_executor_creates_workflow_store_by_default(self):
        """Executor should create workflow store via factory when none provided."""
        executor = OrchestratorExecutor()

        # Executor should have a workflow_store attribute
        assert hasattr(executor, "workflow_store")
        assert executor.workflow_store is not None
        # Should be an InMemoryWorkflowStore by default (STORAGE_BACKEND defaults to memory)
        assert isinstance(executor.workflow_store, InMemoryWorkflowStore)

    def test_executor_accepts_custom_workflow_store(self):
        """Executor should accept a custom WorkflowStoreProtocol."""
        custom_store = InMemoryWorkflowStore()
        executor = OrchestratorExecutor(workflow_store=custom_store)

        assert executor.workflow_store is custom_store

    def test_executor_passes_workflow_store_to_agent(self):
        """Executor should pass workflow_store to OrchestratorAgent."""
        custom_store = InMemoryWorkflowStore()
        executor = OrchestratorExecutor(workflow_store=custom_store)

        # Build agent should use the workflow store
        agent = executor.build_agent()
        assert isinstance(agent, OrchestratorAgent)
        assert agent._workflow_store is custom_store

    def test_orchestrator_agent_with_workflow_store(self):
        """OrchestratorAgent should accept WorkflowStoreProtocol."""
        workflow_store = InMemoryWorkflowStore()
        agent = OrchestratorAgent(workflow_store=workflow_store)

        assert agent._workflow_store is workflow_store

    def test_create_workflow_store_returns_protocol(self):
        """create_workflow_store should return WorkflowStoreProtocol implementation."""
        store = create_workflow_store()

        # Should return InMemoryWorkflowStore by default
        assert isinstance(store, InMemoryWorkflowStore)
        # Should implement the protocol
        assert isinstance(store, WorkflowStoreProtocol)

    def test_create_workflow_store_explicit_memory_backend(self):
        """create_workflow_store with explicit 'memory' backend."""
        store = create_workflow_store("memory")

        assert isinstance(store, InMemoryWorkflowStore)


class TestSessionManagerUsesWorkflowStoreLookupChain:
    """Tests for ORCH-098: Session manager uses WorkflowStoreProtocol lookup chain."""

    @pytest.fixture
    def workflow_store(self):
        """Create an InMemoryWorkflowStore for testing."""
        return InMemoryWorkflowStore()

    @pytest.fixture
    def session_manager(self, workflow_store):
        """Create a UnifiedSessionManager with test store."""
        return UnifiedSessionManager(workflow_store=workflow_store)

    @pytest.mark.asyncio
    async def test_load_or_create_creates_new_state(self, session_manager, workflow_store):
        """Should create new state when no existing state found."""
        session_ref = SessionRef()  # Empty - no identifiers
        new_session_id = "sess_test_new"

        result = await session_manager.load_or_create_state(
            session_ref=session_ref,
            new_session_id=new_session_id,
        )

        assert isinstance(result, UnifiedSessionManagerResult)
        assert result.is_new is True
        assert result.original_session_id == new_session_id
        assert result.state.session_id == new_session_id
        assert result.state.phase == Phase.CLARIFICATION
        assert result.state.consultation_id is not None
        assert result.etag is not None

    @pytest.mark.asyncio
    async def test_load_or_create_loads_existing_by_session_id(
        self, session_manager, workflow_store
    ):
        """Should load existing state when session_id matches."""
        # First create a state
        new_session_id = "sess_existing"
        first_result = await session_manager.load_or_create_state(
            session_ref=SessionRef(),
            new_session_id=new_session_id,
        )
        assert first_result.is_new is True

        # Now load by session_id
        session_ref = SessionRef(session_id=new_session_id)
        second_result = await session_manager.load_or_create_state(
            session_ref=session_ref,
            new_session_id="sess_should_not_be_used",
        )

        assert second_result.is_new is False
        assert second_result.original_session_id == new_session_id
        assert second_result.state.session_id == new_session_id

    @pytest.mark.asyncio
    async def test_load_or_create_loads_existing_by_consultation_id(
        self, session_manager, workflow_store
    ):
        """Should load existing state when consultation_id matches."""
        # First create a state
        new_session_id = "sess_for_consultation"
        first_result = await session_manager.load_or_create_state(
            session_ref=SessionRef(),
            new_session_id=new_session_id,
        )
        consultation_id = first_result.state.consultation_id

        # Now load by consultation_id (cross-session resumption)
        session_ref = SessionRef(consultation_id=consultation_id)
        second_result = await session_manager.load_or_create_state(
            session_ref=session_ref,
            new_session_id="sess_new_browser",  # Different session_id (new browser)
        )

        assert second_result.is_new is False
        assert second_result.original_session_id == new_session_id
        assert second_result.state.session_id == new_session_id
        assert second_result.state.consultation_id == consultation_id

    @pytest.mark.asyncio
    async def test_convenience_function_unified_load_or_create_state(self, workflow_store):
        """Test unified_load_or_create_state convenience function."""
        result = await unified_load_or_create_state(
            session_ref=SessionRef(),
            new_session_id="sess_convenience_test",
            workflow_store=workflow_store,
        )

        assert isinstance(result, UnifiedSessionManagerResult)
        assert result.is_new is True
        assert result.state.session_id == "sess_convenience_test"


class TestWorkflowTurnSavesStateViaProtocol:
    """Tests for ORCH-098: workflow_turn saves state via WorkflowStoreProtocol."""

    @pytest.fixture
    def workflow_store(self):
        """Create an InMemoryWorkflowStore for testing."""
        return InMemoryWorkflowStore()

    @pytest.mark.asyncio
    async def test_workflow_turn_with_unified_store_creates_new_state(self, workflow_store):
        """workflow_turn should create new state and save via protocol."""
        result = await workflow_turn_with_unified_store(
            session_ref=None,
            message="I want to plan a trip to Tokyo",
            event=None,
            workflow_store=workflow_store,
        )

        assert result.success is True
        # Should have saved state
        assert workflow_store.get_state_count() == 1

    @pytest.mark.asyncio
    async def test_workflow_turn_with_unified_store_loads_existing_state(self, workflow_store):
        """workflow_turn should load existing state and save changes."""
        # First call creates state
        first_result = await workflow_turn_with_unified_store(
            session_ref=None,
            message="I want to plan a trip to Tokyo",
            event=None,
            workflow_store=workflow_store,
        )
        session_id = first_result.status.get("session_id")

        # Second call loads existing state
        second_result = await workflow_turn_with_unified_store(
            session_ref={"session_id": session_id},
            message="For 5 days in March",
            event=None,
            workflow_store=workflow_store,
        )

        assert second_result.success is True
        # Still only one state (loaded, not created)
        assert workflow_store.get_state_count() == 1

    @pytest.mark.asyncio
    async def test_workflow_turn_with_unified_store_handles_etag(self, workflow_store):
        """workflow_turn should handle etag for optimistic locking."""
        # Create a state
        result = await workflow_turn_with_unified_store(
            session_ref=None,
            message="Test etag handling",
            event=None,
            workflow_store=workflow_store,
        )

        # Get the state and verify etag was set
        session_id = result.status.get("session_id")
        state = await workflow_store.get_by_session(session_id)

        assert state is not None
        assert state.etag is not None

    @pytest.mark.asyncio
    async def test_workflow_turn_with_unified_store_requires_message(self, workflow_store):
        """workflow_turn should return error when message is empty."""
        result = await workflow_turn_with_unified_store(
            session_ref=None,
            message="",
            event=None,
            workflow_store=workflow_store,
        )

        assert result.success is False
        assert result.error_code == "MISSING_MESSAGE"

    @pytest.mark.asyncio
    async def test_unified_workflow_turn_context(self, workflow_store):
        """Test UnifiedWorkflowTurnContext setup and retrieval."""
        context = UnifiedWorkflowTurnContext(
            workflow_store=workflow_store,
            a2a_client=None,
            agent_registry=None,
        )

        set_unified_workflow_turn_context(context)
        retrieved = get_unified_workflow_turn_context()

        assert retrieved is context
        assert retrieved.workflow_store is workflow_store


class TestWorkflowStoreProtocolCompliance:
    """Tests verifying InMemoryWorkflowStore implements WorkflowStoreProtocol correctly."""

    @pytest.fixture
    def workflow_store(self):
        """Create an InMemoryWorkflowStore for testing."""
        return InMemoryWorkflowStore()

    @pytest.mark.asyncio
    async def test_get_by_session(self, workflow_store):
        """Test get_by_session method."""
        # Non-existent session returns None
        state = await workflow_store.get_by_session("nonexistent")
        assert state is None

        # Save a state
        test_state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_test",
            phase=Phase.CLARIFICATION,
        )
        await workflow_store.save(test_state)

        # Now should find it
        loaded = await workflow_store.get_by_session("sess_test")
        assert loaded is not None
        assert loaded.session_id == "sess_test"

    @pytest.mark.asyncio
    async def test_get_by_consultation(self, workflow_store):
        """Test get_by_consultation method."""
        # Save state and create consultation index
        test_state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_test",
            workflow_version=1,
            phase=Phase.CLARIFICATION,
        )
        await workflow_store.save(test_state)
        await workflow_store.create_consultation_index(
            consultation_id="cons_test",
            session_id="sess_test",
            workflow_version=1,
        )

        # Lookup by consultation_id
        loaded = await workflow_store.get_by_consultation("cons_test")
        assert loaded is not None
        assert loaded.consultation_id == "cons_test"

    @pytest.mark.asyncio
    async def test_get_by_booking(self, workflow_store):
        """Test get_by_booking method."""
        # Save state and create booking index
        test_state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_test",
            phase=Phase.CLARIFICATION,
        )
        await workflow_store.save(test_state)
        await workflow_store.create_booking_index(
            booking_id="book_test",
            session_id="sess_test",
            consultation_id="cons_test",
        )

        # Lookup by booking_id
        loaded = await workflow_store.get_by_booking("book_test")
        assert loaded is not None
        assert loaded.session_id == "sess_test"

    @pytest.mark.asyncio
    async def test_save_with_etag(self, workflow_store):
        """Test save method with optimistic locking."""
        from src.shared.storage import ConflictError

        # Save initial state
        test_state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_test",
            phase=Phase.CLARIFICATION,
        )
        etag1 = await workflow_store.save(test_state)
        assert etag1 is not None

        # Update with correct etag should succeed
        test_state.current_step = "updated"
        etag2 = await workflow_store.save(test_state, etag=etag1)
        assert etag2 != etag1

        # Update with stale etag should fail
        with pytest.raises(ConflictError):
            await workflow_store.save(test_state, etag=etag1)  # Stale etag

    @pytest.mark.asyncio
    async def test_consultation_index_operations(self, workflow_store):
        """Test consultation index create and delete."""
        # Create index
        await workflow_store.create_consultation_index(
            consultation_id="cons_test",
            session_id="sess_test",
            workflow_version=1,
        )

        # Verify index exists (internal check)
        assert workflow_store.get_consultation_index_count() == 1

        # Delete index
        await workflow_store.delete_consultation_index("cons_test")
        assert workflow_store.get_consultation_index_count() == 0

    @pytest.mark.asyncio
    async def test_booking_index_operations(self, workflow_store):
        """Test booking index create and delete."""
        # Create index
        await workflow_store.create_booking_index(
            booking_id="book_test",
            session_id="sess_test",
            consultation_id="cons_test",
        )

        # Verify index exists
        assert workflow_store.get_booking_index_count() == 1

        # Delete index
        await workflow_store.delete_booking_index("book_test")
        assert workflow_store.get_booking_index_count() == 0

    @pytest.mark.asyncio
    async def test_consultation_summary_operations(self, workflow_store):
        """Test consultation summary upsert and get."""
        # Upsert summary
        await workflow_store.upsert_consultation_summary(
            consultation_id="cons_test",
            session_id="sess_test",
            trip_spec_summary={"destination": "Tokyo", "dates": "March 2026"},
            itinerary_ids=["itin_1"],
            booking_ids=["book_1"],
            status="active",
        )

        # Get summary
        summary = await workflow_store.get_consultation_summary("cons_test")
        assert summary is not None
        assert summary["consultation_id"] == "cons_test"
        assert summary["trip_spec_summary"]["destination"] == "Tokyo"
