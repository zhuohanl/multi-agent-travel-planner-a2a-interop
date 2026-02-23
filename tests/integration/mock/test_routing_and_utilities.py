"""
Tier 1: Mock routing layer and utility tool tests.

Tests the three-layer routing system and utility tools as defined
in the orchestrator design document (Routing Flow section).

Run on EVERY ticket to verify protocol correctness.

Run: uv run pytest tests/integration/mock/test_routing_and_utilities.py -v
"""

from unittest.mock import MagicMock

import pytest

from .conftest import MockA2AResponseFactory


class TestRoutingLayerPatterns:
    """
    Test routing layer patterns as defined in design doc.

    Layer 1a: Active session → workflow_turn directly
    Layer 1b: Utility patterns (regex, no LLM)
    Layer 1c: LLM routing via Azure AI Agent
    """

    @pytest.mark.asyncio
    async def test_layer_1b_currency_convert_pattern(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test Layer 1b: currency conversion regex pattern match."""
        # Pattern: r"convert\s+(\d+)\s+(\w+)\s+to\s+(\w+)"
        mock_a2a_client.configure_response(
            "http://localhost:10000",  # Orchestrator URL
            mock_response_factory.currency_convert_result(
                from_amount=100.0,
                from_currency="USD",
                to_currency="EUR",
                result_amount=92.50,
            ),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10000",
            message="convert 100 USD to EUR",  # Matches Layer 1b regex
        )

        assert response.is_complete is True
        assert "92.5" in response.text or "92.50" in response.text

    @pytest.mark.asyncio
    async def test_layer_1b_weather_lookup_pattern(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test Layer 1b: weather lookup regex pattern match."""
        # Pattern: r"weather\s+(?:in|for)\s+(.+)"
        mock_a2a_client.configure_response(
            "http://localhost:10000",
            mock_response_factory.weather_lookup_result(
                location="Tokyo",
                temperature_high=18,
                temperature_low=12,
            ),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10000",
            message="weather in Tokyo",  # Matches Layer 1b regex
        )

        assert response.is_complete is True
        assert "Tokyo" in response.text

    @pytest.mark.asyncio
    async def test_layer_1b_timezone_pattern(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test Layer 1b: timezone info regex pattern match."""
        # Pattern: r"what\s+time\s+(?:in|is\s+it\s+in)\s+(.+)"
        mock_a2a_client.configure_response(
            "http://localhost:10000",
            mock_response_factory.timezone_info_result(
                location="Tokyo",
                timezone="Asia/Tokyo",
                utc_offset="+09:00",
            ),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10000",
            message="what time in Tokyo",  # Matches Layer 1b regex
        )

        assert response.is_complete is True
        assert "Tokyo" in response.text

    @pytest.mark.asyncio
    async def test_layer_1b_get_booking_pattern(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test Layer 1b: get booking lookup regex pattern match."""
        # Pattern: r"show\s+booking\s+(\w+)"
        mock_a2a_client.configure_response(
            "http://localhost:10000",
            mock_response_factory.get_booking_result(
                booking_id="BK-12345",
                status="confirmed",
            ),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10000",
            message="show booking BK-12345",  # Matches Layer 1b regex
        )

        assert response.is_complete is True
        assert "BK-12345" in response.text

    @pytest.mark.asyncio
    async def test_layer_1b_get_consultation_pattern(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test Layer 1b: get consultation lookup regex pattern match."""
        # Pattern: r"show\s+consultation\s+(\w+)"
        mock_a2a_client.configure_response(
            "http://localhost:10000",
            mock_response_factory.get_consultation_result(
                consultation_id="CONS-67890",
            ),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10000",
            message="show consultation CONS-67890",  # Matches Layer 1b regex
        )

        assert response.is_complete is True
        assert "CONS-67890" in response.text


class TestUtilityTools:
    """Test utility tool response formats."""

    @pytest.mark.asyncio
    async def test_currency_convert_response_format(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test currency_convert tool returns properly formatted response."""
        mock_a2a_client.configure_response(
            "http://localhost:10000",
            mock_response_factory.currency_convert_result(
                from_amount=250.0,
                from_currency="USD",
                to_currency="JPY",
                result_amount=37500.0,
            ),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10000",
            message="convert 250 USD to JPY",
        )

        assert response.is_complete is True
        # Response should contain conversion result
        assert "37500" in response.text
        assert "JPY" in response.text

    @pytest.mark.asyncio
    async def test_weather_lookup_response_format(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test weather_lookup tool returns properly formatted response."""
        mock_a2a_client.configure_response(
            "http://localhost:10000",
            mock_response_factory.weather_lookup_result(
                location="Paris",
                temperature_high=22,
                temperature_low=15,
                conditions="sunny",
            ),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10000",
            message="weather in Paris",
        )

        assert response.is_complete is True
        assert "Paris" in response.text
        # Response should contain temperature info
        assert "22" in response.text or "15" in response.text

    @pytest.mark.asyncio
    async def test_timezone_info_response_format(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test timezone_info tool returns properly formatted response."""
        mock_a2a_client.configure_response(
            "http://localhost:10000",
            mock_response_factory.timezone_info_result(
                location="New York",
                timezone="America/New_York",
                utc_offset="-05:00",
                current_time="2026-03-10T09:30:00",
            ),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10000",
            message="what time is it in New York",
        )

        assert response.is_complete is True
        assert "New York" in response.text


class TestAnswerQuestionTool:
    """
    Test answer_question tool (Q&A mode) as defined in design doc.

    The answer_question tool routes domain-specific questions to
    specialized agents in Q&A mode (mode='qa').
    """

    @pytest.mark.asyncio
    async def test_qa_mode_stay_agent(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test Q&A mode routing to stay agent."""
        mock_a2a_client.configure_response(
            "http://localhost:10009",  # Stay agent URL
            mock_response_factory.qa_mode_response(
                agent_name="stay",
                question="Does the Park Hyatt have a pool?",
                answer="Yes, the Park Hyatt Tokyo has an indoor swimming pool on the 47th floor.",
            ),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10009",
            message='{"mode": "qa", "question": "Does the Park Hyatt have a pool?"}',
        )

        assert response.is_complete is True
        assert "pool" in response.text.lower()

    @pytest.mark.asyncio
    async def test_qa_mode_transport_agent(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test Q&A mode routing to transport agent."""
        mock_a2a_client.configure_response(
            "http://localhost:10010",  # Transport agent URL
            mock_response_factory.qa_mode_response(
                agent_name="transport",
                question="How long is the bullet train from Tokyo to Kyoto?",
                answer="The Shinkansen (bullet train) takes approximately 2 hours 15 minutes from Tokyo to Kyoto.",
            ),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10010",
            message='{"mode": "qa", "question": "How long is the bullet train from Tokyo to Kyoto?"}',
        )

        assert response.is_complete is True
        assert "shinkansen" in response.text.lower() or "bullet" in response.text.lower()

    @pytest.mark.asyncio
    async def test_qa_mode_poi_agent(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test Q&A mode routing to POI agent."""
        mock_a2a_client.configure_response(
            "http://localhost:10008",  # POI agent URL
            mock_response_factory.qa_mode_response(
                agent_name="poi",
                question="Is the Senso-ji temple free to enter?",
                answer="Yes, Senso-ji Temple in Asakusa is free to enter. The temple grounds are open 24 hours.",
            ),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10008",
            message='{"mode": "qa", "question": "Is the Senso-ji temple free to enter?"}',
        )

        assert response.is_complete is True
        assert "free" in response.text.lower()

    @pytest.mark.asyncio
    async def test_qa_mode_dining_agent(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test Q&A mode routing to dining agent."""
        mock_a2a_client.configure_response(
            "http://localhost:10017",  # Dining agent URL
            mock_response_factory.qa_mode_response(
                agent_name="dining",
                question="What's the dress code at Sukiyabashi Jiro?",
                answer="Smart casual is recommended at Sukiyabashi Jiro. Reservations are extremely difficult to obtain.",
            ),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10017",
            message='{"mode": "qa", "question": "What\'s the dress code at Sukiyabashi Jiro?"}',
        )

        assert response.is_complete is True
        assert "casual" in response.text.lower() or "dress" in response.text.lower()

    @pytest.mark.asyncio
    async def test_qa_mode_events_agent(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test Q&A mode routing to events agent."""
        mock_a2a_client.configure_response(
            "http://localhost:10011",  # Events agent URL
            mock_response_factory.qa_mode_response(
                agent_name="events",
                question="Are there any festivals in Tokyo in March?",
                answer="Yes! The cherry blossom season typically begins in late March, with Hanami festivals throughout Tokyo parks.",
            ),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10011",
            message='{"mode": "qa", "question": "Are there any festivals in Tokyo in March?"}',
        )

        assert response.is_complete is True
        assert "festival" in response.text.lower() or "cherry" in response.text.lower()


class TestUtilitiesWithContext:
    """
    Test utilities called with active session context.

    Per design doc: When there's an active session, utilities go through
    workflow_turn for context-aware handling (Layer 1a → Layer 2).

    Note: These mock tests verify the PROTOCOL/FORMAT correctness.
    The actual orchestrator implementation is tracked by Phase 2 tickets.
    """

    @pytest.mark.asyncio
    async def test_weather_with_trip_context(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test weather lookup enriched with trip context.

        Implementation: ORCH-024 (workflow_turn tool handler)
        """
        # When user asks "What's the weather during my trip?" with active session,
        # the orchestrator should extract trip dates and location from WorkflowState
        mock_a2a_client.configure_response(
            "http://localhost:10000",
            mock_response_factory.weather_lookup_result(
                location="Tokyo",  # Extracted from trip context
                temperature_high=18,
                temperature_low=12,
            ),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10000",
            message="What's the weather during my trip?",
            context_id="ctx_session_001",  # Indicates active session
        )

        # Should return weather for trip destination
        assert "Tokyo" in response.text

    @pytest.mark.asyncio
    async def test_timezone_with_trip_context(
        self, mock_a2a_client: MagicMock, mock_response_factory: MockA2AResponseFactory
    ) -> None:
        """Test timezone lookup enriched with trip context.

        Implementation: ORCH-024 (workflow_turn tool handler)
        """
        mock_a2a_client.configure_response(
            "http://localhost:10000",
            mock_response_factory.timezone_info_result(
                location="Tokyo",
                timezone="Asia/Tokyo",
                utc_offset="+09:00",
            ),
        )

        response = await mock_a2a_client.send_message(
            agent_url="http://localhost:10000",
            message="What time zone will I be in?",
            context_id="ctx_session_001",  # Indicates active session
        )

        # Should return timezone for trip destination
        assert "Tokyo" in response.text or "Asia/Tokyo" in response.text


class TestCompleteRequestFlow:
    """
    Test complete end-to-end request flow through executor.

    Per ORCH-085: Tests the wiring from A2A request through routing to
    handler dispatch and state persistence.

    These tests verify:
    - Executor routes requests through routing layers
    - workflow_turn dispatches to correct handlers
    - State is persisted after handler execution
    - A2A client and registry are wired through to handlers
    """

    @pytest.mark.asyncio
    async def test_complete_flow_new_session_to_clarification(self) -> None:
        """Test complete flow: new session routes to clarification handler."""
        from datetime import datetime, timezone

        from src.orchestrator.executor import OrchestratorAgent
        from src.orchestrator.models.workflow_state import Phase
        from src.shared.storage import InMemoryWorkflowStore

        # Set up with in-memory store
        store = InMemoryWorkflowStore()
        agent = OrchestratorAgent(workflow_store=store)

        # Make request without existing session
        chunks = []
        async for chunk in agent.stream(
            user_input="I want to plan a trip to Tokyo",
            session_id="new_flow_session",
        ):
            chunks.append(chunk)

        # Should have processed and created state
        assert len(chunks) >= 1

        # Verify state was created and saved
        saved_state = await store.get_by_session("new_flow_session")
        assert saved_state is not None
        assert saved_state.phase == Phase.CLARIFICATION

    @pytest.mark.asyncio
    async def test_complete_flow_existing_session_continues_workflow(self) -> None:
        """Test complete flow: existing session continues in workflow_turn."""
        from datetime import datetime, timezone

        from src.orchestrator.executor import OrchestratorAgent
        from src.orchestrator.models.workflow_state import Phase, WorkflowState
        from src.shared.storage import InMemoryWorkflowStore

        # Pre-create session state
        store = InMemoryWorkflowStore()
        existing_state = WorkflowState(
            session_id="existing_flow_session",
            consultation_id="cons_flow_test",
            phase=Phase.CLARIFICATION,
            workflow_version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await store.save(existing_state)

        agent = OrchestratorAgent(workflow_store=store)

        # Make request with existing session
        chunks = []
        async for chunk in agent.stream(
            user_input="I want to change my destination to Paris",
            session_id="existing_flow_session",
        ):
            chunks.append(chunk)

        # Should have processed
        assert len(chunks) >= 1

        # Verify state was updated
        updated_state = await store.get_by_session("existing_flow_session")
        assert updated_state is not None
        # updated_at should be newer
        assert updated_state.updated_at >= existing_state.updated_at

    @pytest.mark.asyncio
    async def test_complete_flow_utility_without_session(self) -> None:
        """Test complete flow: utility request without session uses Layer 1b."""
        from src.orchestrator.executor import OrchestratorAgent
        from src.shared.storage import InMemoryWorkflowStore

        store = InMemoryWorkflowStore()
        agent = OrchestratorAgent(workflow_store=store)

        # Utility request (Layer 1b pattern) without existing session
        chunks = []
        async for chunk in agent.stream(
            user_input="convert 100 USD to EUR",
            session_id="utility_session",
        ):
            chunks.append(chunk)

        # Should have processed
        assert len(chunks) >= 1
        response_text = chunks[0].get("content", "")
        # Should route to currency utility
        assert "USD" in response_text or "EUR" in response_text

    @pytest.mark.asyncio
    async def test_complete_flow_executor_with_a2a_client(self) -> None:
        """Test complete flow: executor properly wires A2A client."""
        from unittest.mock import MagicMock

        from src.orchestrator.executor import OrchestratorExecutor
        from src.shared.storage import InMemoryWorkflowStore

        # Set up mocks
        mock_a2a_client = MagicMock()
        mock_registry = MagicMock()
        store = InMemoryWorkflowStore()

        executor = OrchestratorExecutor(
            workflow_store=store,
            a2a_client=mock_a2a_client,
            agent_registry=mock_registry,
        )

        # Verify wiring
        assert executor.a2a_client is mock_a2a_client
        assert executor.agent_registry is mock_registry
        assert executor.agent.a2a_client is mock_a2a_client
        assert executor.agent.agent_registry is mock_registry

        # Make a request to verify flow works
        chunks = []
        async for chunk in executor.agent.stream(
            user_input="Plan a trip to Rome",
            session_id="a2a_wiring_session",
        ):
            chunks.append(chunk)

        assert len(chunks) >= 1

    @pytest.mark.asyncio
    async def test_complete_flow_state_persistence_on_phase_change(self) -> None:
        """Test that state changes from handlers are persisted."""
        from datetime import datetime, timezone

        from src.orchestrator.models.workflow_state import Phase, WorkflowState
        from src.orchestrator.tools.workflow_turn import (
            UnifiedWorkflowTurnContext,
            set_unified_workflow_turn_context,
            workflow_turn,
        )
        from src.shared.storage import InMemoryWorkflowStore

        store = InMemoryWorkflowStore()

        # Create initial state
        initial_state = WorkflowState(
            session_id="persist_phase_session",
            consultation_id="cons_persist_phase",
            phase=Phase.CLARIFICATION,
            workflow_version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await store.save(initial_state)

        context = UnifiedWorkflowTurnContext(workflow_store=store)
        set_unified_workflow_turn_context(context)

        try:
            # Call workflow_turn
            result = await workflow_turn(
                session_ref={"session_id": "persist_phase_session"},
                message="Continue planning my trip",
            )

            assert result.success is True

            # Verify state was persisted
            saved_state = await store.get_by_session("persist_phase_session")
            assert saved_state is not None
            assert saved_state.etag is not None  # Should have etag after save

        finally:
            set_unified_workflow_turn_context(None)  # type: ignore
