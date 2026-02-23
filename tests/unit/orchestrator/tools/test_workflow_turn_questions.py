"""
Unit tests for context-aware question handling in workflow_turn.

Tests for ORCH-105: Handle context-aware questions inside workflow_turn and re-prompt checkpoints.

Per design doc (workflow_turn Internal Implementation, Example 2):
- Questions inside an active workflow invoke answer_question with workflow context
- WorkflowState remains unchanged for question-only turns
- Checkpoint re-prompts are returned when a checkpoint is active
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.orchestrator.models.workflow_state import Phase, WorkflowState
from src.orchestrator.storage import WorkflowStateData
from src.orchestrator.tools.workflow_turn import (
    ToolResponse,
    handle_question_with_context,
    _build_question_context,
    _infer_question_domain,
    _get_checkpoint_reprompt,
    _build_checkpoint_actions,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Test Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def clarification_state() -> WorkflowState:
    """Create a WorkflowState in clarification phase."""
    return WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_test456",
        phase=Phase.CLARIFICATION,
        checkpoint=None,
        workflow_version=1,
    )


@pytest.fixture
def trip_spec_approval_state() -> WorkflowState:
    """Create a WorkflowState at trip_spec_approval checkpoint."""
    state = WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_test456",
        phase=Phase.CLARIFICATION,
        checkpoint="trip_spec_approval",
        workflow_version=1,
    )
    # Add trip_spec
    state.trip_spec = MagicMock()
    state.trip_spec.destination_city = "Tokyo"
    state.trip_spec.destination = "Tokyo"
    state.trip_spec.start_date = "2026-03-10"
    state.trip_spec.end_date = "2026-03-17"
    state.trip_spec.to_dict = MagicMock(return_value={
        "destination_city": "Tokyo",
        "start_date": "2026-03-10",
        "end_date": "2026-03-17",
    })
    return state


@pytest.fixture
def itinerary_approval_state() -> WorkflowState:
    """Create a WorkflowState at itinerary_approval checkpoint."""
    state = WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_test456",
        phase=Phase.DISCOVERY_PLANNING,
        checkpoint="itinerary_approval",
        workflow_version=1,
    )
    # Add trip_spec and itinerary_draft
    state.trip_spec = MagicMock()
    state.trip_spec.destination_city = "Tokyo"
    state.trip_spec.start_date = "2026-03-10"
    state.trip_spec.end_date = "2026-03-17"
    state.trip_spec.to_dict = MagicMock(return_value={
        "destination_city": "Tokyo",
        "start_date": "2026-03-10",
        "end_date": "2026-03-17",
    })
    state.itinerary_draft = MagicMock()
    state.itinerary_draft.to_dict = MagicMock(return_value={
        "destination": "Tokyo",
        "days": 7,
        "accommodation": {"name": "Keio Plaza Hotel", "location": "Shinjuku"},
    })
    return state


@pytest.fixture
def state_data() -> WorkflowStateData:
    """Create a WorkflowStateData for testing."""
    return WorkflowStateData(
        session_id="sess_test123",
        consultation_id="cons_test456",
        phase="CLARIFICATION",
        checkpoint=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test handle_question_with_context
# ═══════════════════════════════════════════════════════════════════════════════


class TestHandleQuestionWithContext:
    """Tests for handle_question_with_context function."""

    @pytest.mark.asyncio
    async def test_question_calls_answer_question_with_context(
        self,
        trip_spec_approval_state: WorkflowState,
        state_data: WorkflowStateData,
    ):
        """Question should call answer_question with workflow context."""
        message = "Does the hotel have a gym?"
        status = {"phase": "CLARIFICATION", "session_id": "sess_test123"}

        with patch(
            "src.orchestrator.tools.answer_question.answer_question"
        ) as mock_answer:
            mock_answer.return_value = ToolResponse(
                success=True,
                message="Yes, the hotel has a fitness center on the 7th floor.",
                data={"domain": "stay"},
            )

            response, returned_state_data = await handle_question_with_context(
                state=trip_spec_approval_state,
                state_data=state_data,
                message=message,
                status=status,
                is_new_session=False,
            )

            # Verify answer_question was called with context
            mock_answer.assert_called_once()
            call_kwargs = mock_answer.call_args.kwargs
            assert call_kwargs["question"] == message
            assert call_kwargs["domain"] == "stay"  # Inferred from message
            assert call_kwargs["context"] is not None
            assert "destination" in call_kwargs["context"]
            assert call_kwargs["context"]["destination"] == "Tokyo"

    @pytest.mark.asyncio
    async def test_question_does_not_mutate_state(
        self,
        trip_spec_approval_state: WorkflowState,
        state_data: WorkflowStateData,
    ):
        """WorkflowState should remain unchanged for question-only turns."""
        message = "What attractions are near the hotel?"
        status = {"phase": "CLARIFICATION", "session_id": "sess_test123"}

        # Capture original state values
        original_phase = trip_spec_approval_state.phase
        original_checkpoint = trip_spec_approval_state.checkpoint
        original_workflow_version = trip_spec_approval_state.workflow_version

        with patch(
            "src.orchestrator.tools.answer_question.answer_question"
        ) as mock_answer:
            mock_answer.return_value = ToolResponse(
                success=True,
                message="There are many attractions nearby.",
                data={"domain": "poi"},
            )

            response, returned_state_data = await handle_question_with_context(
                state=trip_spec_approval_state,
                state_data=state_data,
                message=message,
                status=status,
                is_new_session=False,
            )

            # Verify state is unchanged
            assert trip_spec_approval_state.phase == original_phase
            assert trip_spec_approval_state.checkpoint == original_checkpoint
            assert trip_spec_approval_state.workflow_version == original_workflow_version

            # Verify returned state_data is the same object
            assert returned_state_data is state_data

    @pytest.mark.asyncio
    async def test_question_reprompts_checkpoint(
        self,
        trip_spec_approval_state: WorkflowState,
        state_data: WorkflowStateData,
    ):
        """Response should include checkpoint re-prompt when at a checkpoint."""
        message = "What's the weather like in March?"
        status = {"phase": "CLARIFICATION", "session_id": "sess_test123"}

        with patch(
            "src.orchestrator.tools.answer_question.answer_question"
        ) as mock_answer:
            mock_answer.return_value = ToolResponse(
                success=True,
                message="March weather in Tokyo is mild with occasional rain.",
                data={"domain": "general"},
            )

            response, _ = await handle_question_with_context(
                state=trip_spec_approval_state,
                state_data=state_data,
                message=message,
                status=status,
                is_new_session=False,
            )

            # Verify response includes checkpoint re-prompt
            assert response.success is True
            assert "March weather in Tokyo" in response.message
            assert "approve" in response.message.lower() or "changes" in response.message.lower()

            # Verify UI actions include approval button
            assert response.ui is not None
            assert "actions" in response.ui
            action_labels = [a["label"] for a in response.ui["actions"]]
            assert "Approve & Search" in action_labels or "Make Changes" in action_labels

    @pytest.mark.asyncio
    async def test_question_at_itinerary_approval_checkpoint(
        self,
        itinerary_approval_state: WorkflowState,
        state_data: WorkflowStateData,
    ):
        """Question at itinerary_approval should include itinerary approval actions."""
        message = "Does the Keio Plaza have a pool?"
        status = {"phase": "DISCOVERY_PLANNING", "session_id": "sess_test123"}
        state_data.phase = "DISCOVERY_PLANNING"
        state_data.checkpoint = "itinerary_approval"

        with patch(
            "src.orchestrator.tools.answer_question.answer_question"
        ) as mock_answer:
            mock_answer.return_value = ToolResponse(
                success=True,
                message="The Keio Plaza has a fitness center but no pool.",
                data={"domain": "stay"},
            )

            response, _ = await handle_question_with_context(
                state=itinerary_approval_state,
                state_data=state_data,
                message=message,
                status=status,
                is_new_session=False,
            )

            # Verify response has itinerary approval actions
            assert response.ui is not None
            assert "actions" in response.ui
            action_labels = [a["label"] for a in response.ui["actions"]]
            assert "Approve & Book" in action_labels
            assert "Request Changes" in action_labels

    @pytest.mark.asyncio
    async def test_question_without_checkpoint_no_reprompt(
        self,
        clarification_state: WorkflowState,
        state_data: WorkflowStateData,
    ):
        """Question without checkpoint should not include re-prompt."""
        message = "What's the best time to visit Tokyo?"
        status = {"phase": "CLARIFICATION", "session_id": "sess_test123"}

        with patch(
            "src.orchestrator.tools.answer_question.answer_question"
        ) as mock_answer:
            mock_answer.return_value = ToolResponse(
                success=True,
                message="The best time to visit Tokyo is spring or fall.",
                data={"domain": "general"},
            )

            response, _ = await handle_question_with_context(
                state=clarification_state,
                state_data=state_data,
                message=message,
                status=status,
                is_new_session=False,
            )

            # Verify response does not have approval actions
            # (ui may be None or have empty actions)
            if response.ui and "actions" in response.ui:
                action_labels = [a["label"] for a in response.ui["actions"]]
                assert "Approve & Search" not in action_labels
                assert "Approve & Book" not in action_labels


# ═══════════════════════════════════════════════════════════════════════════════
# Test _build_question_context
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildQuestionContext:
    """Tests for _build_question_context helper function."""

    def test_context_includes_destination(self, trip_spec_approval_state: WorkflowState):
        """Context should include destination from trip_spec."""
        context = _build_question_context(trip_spec_approval_state)
        assert "destination" in context
        assert context["destination"] == "Tokyo"

    def test_context_includes_dates(self, trip_spec_approval_state: WorkflowState):
        """Context should include dates from trip_spec."""
        context = _build_question_context(trip_spec_approval_state)
        assert "dates" in context
        assert "2026-03-10" in context["dates"]
        assert "2026-03-17" in context["dates"]

    def test_context_includes_trip_spec(self, trip_spec_approval_state: WorkflowState):
        """Context should include full trip_spec."""
        context = _build_question_context(trip_spec_approval_state)
        assert "trip_spec" in context
        assert context["trip_spec"]["destination_city"] == "Tokyo"

    def test_context_includes_itinerary_draft(self, itinerary_approval_state: WorkflowState):
        """Context should include itinerary_draft when available."""
        context = _build_question_context(itinerary_approval_state)
        assert "itinerary" in context
        assert context["itinerary"]["destination"] == "Tokyo"
        assert "accommodation" in context["itinerary"]

    def test_context_empty_when_no_trip_spec(self, clarification_state: WorkflowState):
        """Context should be empty when no trip_spec available."""
        context = _build_question_context(clarification_state)
        # May have some keys but destination and dates should be missing
        assert context.get("destination") is None
        assert context.get("dates") is None


# ═══════════════════════════════════════════════════════════════════════════════
# Test _infer_question_domain
# ═══════════════════════════════════════════════════════════════════════════════


class TestInferQuestionDomain:
    """Tests for _infer_question_domain helper function."""

    def test_stay_domain_for_hotel_questions(self):
        """Hotel/accommodation questions should map to stay domain."""
        assert _infer_question_domain("Does the hotel have a gym?") == "stay"
        assert _infer_question_domain("What time is check-in?") == "stay"
        assert _infer_question_domain("Is wifi included in the room?") == "stay"
        assert _infer_question_domain("What amenities are available?") == "stay"

    def test_transport_domain_for_travel_questions(self):
        """Flight/train/transport questions should map to transport domain."""
        assert _infer_question_domain("What time is the flight?") == "transport"
        assert _infer_question_domain("How long is the train ride?") == "transport"
        assert _infer_question_domain("Is there a shuttle to the airport?") == "transport"
        assert _infer_question_domain("Can I rent a car?") == "transport"

    def test_poi_domain_for_attraction_questions(self):
        """Attraction/sightseeing questions should map to poi domain."""
        assert _infer_question_domain("What museums should I visit?") == "poi"
        assert _infer_question_domain("Is the temple worth visiting?") == "poi"
        assert _infer_question_domain("What's the best viewpoint?") == "poi"
        assert _infer_question_domain("Is the park worth exploring?") == "poi"

    def test_dining_domain_for_food_questions(self):
        """Food/restaurant questions should map to dining domain."""
        assert _infer_question_domain("Where can I find good ramen?") == "dining"
        assert _infer_question_domain("Is there a vegetarian restaurant?") == "dining"
        assert _infer_question_domain("What's a good place for sushi?") == "dining"
        assert _infer_question_domain("I want to eat traditional Japanese food") == "dining"

    def test_events_domain_for_event_questions(self):
        """Event/show questions should map to events domain."""
        assert _infer_question_domain("Are there any concerts happening?") == "events"
        assert _infer_question_domain("Can I get tickets for a performance?") == "events"
        assert _infer_question_domain("Is there a festival during my trip?") == "events"
        assert _infer_question_domain("Any exhibitions I should check out?") == "events"

    def test_budget_domain_for_cost_questions(self):
        """Cost/budget questions should map to budget domain."""
        assert _infer_question_domain("How much will this trip cost?") == "budget"
        assert _infer_question_domain("Is Tokyo expensive?") == "budget"
        assert _infer_question_domain("What's the average spending per day?") == "budget"
        assert _infer_question_domain("Can I afford this on my budget?") == "budget"

    def test_general_domain_for_other_questions(self):
        """General questions should map to general domain."""
        assert _infer_question_domain("What's the weather like?") == "general"
        assert _infer_question_domain("Do I need a visa?") == "general"
        assert _infer_question_domain("Is it safe to travel there?") == "general"
        assert _infer_question_domain("What should I pack?") == "general"


# ═══════════════════════════════════════════════════════════════════════════════
# Test _get_checkpoint_reprompt
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetCheckpointReprompt:
    """Tests for _get_checkpoint_reprompt helper function."""

    def test_reprompt_for_trip_spec_approval(self, trip_spec_approval_state: WorkflowState):
        """Should return trip spec approval reprompt."""
        reprompt = _get_checkpoint_reprompt(trip_spec_approval_state)
        assert reprompt is not None
        assert "approve" in reprompt.lower()
        assert "changes" in reprompt.lower()

    def test_reprompt_for_itinerary_approval(self, itinerary_approval_state: WorkflowState):
        """Should return itinerary approval reprompt."""
        reprompt = _get_checkpoint_reprompt(itinerary_approval_state)
        assert reprompt is not None
        assert "approve" in reprompt.lower()
        assert "itinerary" in reprompt.lower()

    def test_no_reprompt_without_checkpoint(self, clarification_state: WorkflowState):
        """Should return None when no checkpoint."""
        reprompt = _get_checkpoint_reprompt(clarification_state)
        assert reprompt is None


# ═══════════════════════════════════════════════════════════════════════════════
# Test _build_checkpoint_actions
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildCheckpointActions:
    """Tests for _build_checkpoint_actions helper function."""

    def test_actions_for_trip_spec_approval(self, trip_spec_approval_state: WorkflowState):
        """Should return trip spec approval actions."""
        actions = _build_checkpoint_actions(trip_spec_approval_state)
        assert len(actions) >= 2
        labels = [a["label"] for a in actions]
        assert "Approve & Search" in labels
        assert "Make Changes" in labels

        # Verify event types
        for action in actions:
            if action["label"] == "Approve & Search":
                assert action["event"]["type"] == "approve_checkpoint"
                assert action["event"]["checkpoint_id"] == "trip_spec_approval"

    def test_actions_for_itinerary_approval(self, itinerary_approval_state: WorkflowState):
        """Should return itinerary approval actions."""
        actions = _build_checkpoint_actions(itinerary_approval_state)
        assert len(actions) >= 2
        labels = [a["label"] for a in actions]
        assert "Approve & Book" in labels
        assert "Request Changes" in labels

        # Verify event types
        for action in actions:
            if action["label"] == "Approve & Book":
                assert action["event"]["type"] == "approve_checkpoint"
                assert action["event"]["checkpoint_id"] == "itinerary_approval"

    def test_empty_actions_without_checkpoint(self, clarification_state: WorkflowState):
        """Should return empty list when no checkpoint."""
        actions = _build_checkpoint_actions(clarification_state)
        assert actions == []


# ═══════════════════════════════════════════════════════════════════════════════
# Test Integration with workflow_turn
# ═══════════════════════════════════════════════════════════════════════════════


class TestQuestionIntegrationWithWorkflowTurn:
    """Integration tests for question handling via workflow_turn."""

    @pytest.mark.asyncio
    async def test_question_message_routes_to_answer_question(
        self,
        trip_spec_approval_state: WorkflowState,
    ):
        """Question message should be classified as ANSWER_QUESTION_IN_CONTEXT."""
        from src.orchestrator.classification import heuristic_classify
        from src.orchestrator.state_gating import Action

        # Test various question patterns
        questions = [
            "Does the hotel have a gym?",
            "What is the weather like?",
            "Is the temple worth visiting?",
            "How much does the train cost?",
        ]

        for question in questions:
            result = heuristic_classify(question, trip_spec_approval_state)
            assert result.action == Action.ANSWER_QUESTION_IN_CONTEXT, \
                f"Expected ANSWER_QUESTION_IN_CONTEXT for '{question}', got {result.action}"

    @pytest.mark.asyncio
    async def test_answer_question_includes_data_fields(
        self,
        trip_spec_approval_state: WorkflowState,
        state_data: WorkflowStateData,
    ):
        """Response should include expected data fields."""
        message = "How far is the hotel from the station?"
        status = {"phase": "CLARIFICATION", "session_id": "sess_test123"}

        with patch(
            "src.orchestrator.tools.answer_question.answer_question"
        ) as mock_answer:
            mock_answer.return_value = ToolResponse(
                success=True,
                message="The hotel is a 5-minute walk from Shinjuku Station.",
                data={"domain": "stay"},
            )

            response, _ = await handle_question_with_context(
                state=trip_spec_approval_state,
                state_data=state_data,
                message=message,
                status=status,
                is_new_session=False,
            )

            # Verify data fields
            assert response.data is not None
            assert response.data["action"] == "answer_question_in_context"
            assert response.data["domain"] == "stay"
            assert response.data["is_new_session"] is False
