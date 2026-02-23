"""
Unit tests for LLM fallback classification module.

Tests the Azure AI Agent-based classification for ambiguous messages
that heuristics cannot confidently classify.

Per ORCH-045: Implement LLM fallback classification.
"""

import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.orchestrator.classification.llm_classify import (
    llm_classify,
    LLMClassificationResult,
    LLM_ACTION_TO_INTERNAL,
    DEFAULT_ACTION,
    _build_classification_prompt,
    _parse_classify_action_response,
    _create_fallback_result,
)
from src.orchestrator.state_gating import Action
from src.orchestrator.models.workflow_state import Phase, WorkflowState


# ═══════════════════════════════════════════════════════════════════════════════
# Test Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def clarification_state():
    """WorkflowState in CLARIFICATION phase."""
    state = MagicMock(spec=WorkflowState)
    state.phase = Phase.CLARIFICATION
    state.checkpoint = None
    state.session_id = "test_session_123"
    state.trip_spec = None
    return state


@pytest.fixture
def trip_spec_approval_state():
    """WorkflowState at trip_spec_approval checkpoint."""
    state = MagicMock(spec=WorkflowState)
    state.phase = Phase.CLARIFICATION
    state.checkpoint = "trip_spec_approval"
    state.session_id = "test_session_123"
    # Add trip spec for context
    state.trip_spec = MagicMock()
    state.trip_spec.destination = "Tokyo"
    state.trip_spec.start_date = "2026-03-10"
    state.trip_spec.end_date = "2026-03-17"
    state.trip_spec.budget = "$3000"
    return state


@pytest.fixture
def discovery_state():
    """WorkflowState in DISCOVERY_IN_PROGRESS phase."""
    state = MagicMock(spec=WorkflowState)
    state.phase = Phase.DISCOVERY_IN_PROGRESS
    state.checkpoint = None
    state.session_id = "test_session_123"
    state.trip_spec = None
    return state


@pytest.fixture
def booking_state():
    """WorkflowState in BOOKING phase."""
    state = MagicMock(spec=WorkflowState)
    state.phase = Phase.BOOKING
    state.checkpoint = None
    state.session_id = "test_session_123"
    state.trip_spec = None
    return state


@pytest.fixture
def mock_orchestrator_llm():
    """Mock OrchestratorLLM instance."""
    mock_llm = MagicMock()
    mock_llm.get_agent_id = MagicMock(return_value="classifier_agent_123")
    mock_llm._ensure_thread_exists = MagicMock(return_value="thread_123")
    mock_llm.client = MagicMock()
    return mock_llm


# ═══════════════════════════════════════════════════════════════════════════════
# Test LLMClassificationResult
# ═══════════════════════════════════════════════════════════════════════════════


class TestLLMClassificationResult:
    """Tests for LLMClassificationResult dataclass."""

    def test_result_to_dict(self):
        """Test serialization of classification result."""
        result = LLMClassificationResult(
            action=Action.APPROVE_TRIP_SPEC,
            confidence=0.95,
            reason="LLM classified as approval",
            raw_response={"action": "APPROVE_TRIP_SPEC", "confidence": 0.95},
        )

        result_dict = result.to_dict()

        assert result_dict["action"] == "approve_trip_spec"
        assert result_dict["confidence"] == 0.95
        assert result_dict["reason"] == "LLM classified as approval"
        assert "raw_response" in result_dict

    def test_result_default_confidence(self):
        """Test default confidence value."""
        result = LLMClassificationResult(action=Action.CONTINUE_CLARIFICATION)

        assert result.confidence == 0.8  # Default LLM confidence
        assert result.reason == ""


# ═══════════════════════════════════════════════════════════════════════════════
# Test Action Mapping
# ═══════════════════════════════════════════════════════════════════════════════


class TestActionMapping:
    """Tests for LLM action to internal action mapping."""

    def test_all_expected_mappings_exist(self):
        """Verify all expected LLM actions have mappings."""
        expected_llm_actions = [
            "APPROVE_TRIP_SPEC",
            "MODIFY_TRIP_SPEC",
            "START_DISCOVERY",
            "APPROVE_ITINERARY",
            "MODIFY_ITINERARY",
            "START_BOOKING",
            "CONFIRM_BOOKING",
            "CANCEL_BOOKING",
        ]

        for llm_action in expected_llm_actions:
            assert llm_action in LLM_ACTION_TO_INTERNAL, f"Missing mapping for {llm_action}"

    def test_modify_actions_map_to_request_modification(self):
        """Verify MODIFY_* actions map to REQUEST_MODIFICATION."""
        assert LLM_ACTION_TO_INTERNAL["MODIFY_TRIP_SPEC"] == Action.REQUEST_MODIFICATION
        assert LLM_ACTION_TO_INTERNAL["MODIFY_ITINERARY"] == Action.REQUEST_MODIFICATION

    def test_booking_actions_map_correctly(self):
        """Verify booking-related action mappings."""
        assert LLM_ACTION_TO_INTERNAL["START_BOOKING"] == Action.VIEW_BOOKING_OPTIONS
        assert LLM_ACTION_TO_INTERNAL["CONFIRM_BOOKING"] == Action.BOOK_SINGLE_ITEM
        assert LLM_ACTION_TO_INTERNAL["CANCEL_BOOKING"] == Action.CANCEL_BOOKING

    def test_default_action_is_safe(self):
        """Verify default action is a safe, non-mutating action."""
        assert DEFAULT_ACTION == Action.CONTINUE_CLARIFICATION


# ═══════════════════════════════════════════════════════════════════════════════
# Test Prompt Building
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildClassificationPrompt:
    """Tests for _build_classification_prompt()."""

    def test_prompt_includes_message(self):
        """Test that the prompt includes the user message."""
        message = "I want to change my travel dates"
        prompt = _build_classification_prompt(message)

        assert message in prompt

    def test_prompt_includes_phase_context(self, clarification_state):
        """Test that prompt includes current phase."""
        prompt = _build_classification_prompt("test message", clarification_state)

        assert "clarification" in prompt.lower()

    def test_prompt_includes_checkpoint(self, trip_spec_approval_state):
        """Test that prompt includes checkpoint when present."""
        prompt = _build_classification_prompt("looks good", trip_spec_approval_state)

        assert "trip_spec_approval" in prompt

    def test_prompt_includes_trip_spec(self, trip_spec_approval_state):
        """Test that prompt includes trip spec details when present."""
        prompt = _build_classification_prompt("approve it", trip_spec_approval_state)

        assert "Tokyo" in prompt
        assert "2026-03-10" in prompt
        assert "$3000" in prompt

    def test_prompt_without_state(self):
        """Test prompt building without workflow state."""
        prompt = _build_classification_prompt("plan a trip to Paris")

        assert "No active workflow context" in prompt
        assert "Paris" in prompt

    def test_prompt_includes_action_options(self):
        """Test that prompt includes available action options."""
        prompt = _build_classification_prompt("some message")

        assert "APPROVE_TRIP_SPEC" in prompt
        assert "MODIFY_TRIP_SPEC" in prompt
        assert "CONTINUE_CLARIFICATION" in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# Test Response Parsing
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseClassifyActionResponse:
    """Tests for _parse_classify_action_response()."""

    def test_parse_json_string(self):
        """Test parsing JSON string response."""
        args = json.dumps({"action": "APPROVE_TRIP_SPEC", "confidence": 0.9})

        result = _parse_classify_action_response(args)

        assert result.action == Action.APPROVE_TRIP_SPEC
        assert result.confidence == 0.9

    def test_parse_dict_response(self):
        """Test parsing dict response directly."""
        args = {"action": "MODIFY_TRIP_SPEC", "confidence": 0.85}

        result = _parse_classify_action_response(args)

        assert result.action == Action.REQUEST_MODIFICATION
        assert result.confidence == 0.85

    def test_parse_missing_confidence(self):
        """Test parsing when confidence is missing."""
        args = {"action": "START_DISCOVERY"}

        result = _parse_classify_action_response(args)

        assert result.action == Action.START_DISCOVERY
        assert result.confidence == 0.8  # Default

    def test_parse_unknown_action_uses_default(self):
        """Test that unknown LLM action maps to default."""
        args = {"action": "UNKNOWN_ACTION", "confidence": 0.7}

        result = _parse_classify_action_response(args)

        assert result.action == DEFAULT_ACTION

    def test_parse_invalid_json_returns_default(self):
        """Test that invalid JSON returns default action."""
        args = "not valid json {{"

        result = _parse_classify_action_response(args)

        assert result.action == DEFAULT_ACTION
        assert result.confidence == 0.5  # Low confidence for parse failure

    def test_parse_normalizes_confidence_range(self):
        """Test that confidence is normalized to 0-1 range."""
        # Test above 1
        args = {"action": "APPROVE_TRIP_SPEC", "confidence": 1.5}
        result = _parse_classify_action_response(args)
        assert result.confidence == 1.0

        # Test below 0
        args = {"action": "APPROVE_TRIP_SPEC", "confidence": -0.5}
        result = _parse_classify_action_response(args)
        assert result.confidence == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Test Fallback Result Creation
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateFallbackResult:
    """Tests for _create_fallback_result()."""

    def test_fallback_in_clarification_phase(self, clarification_state):
        """Test fallback defaults to CONTINUE_CLARIFICATION in clarification."""
        result = _create_fallback_result("some message", clarification_state)

        assert result.action == Action.CONTINUE_CLARIFICATION
        assert result.confidence == 0.5  # Lower confidence for fallback
        assert "fallback" in result.raw_response

    def test_fallback_in_discovery_phase(self, discovery_state):
        """Test fallback defaults to ANSWER_QUESTION in discovery."""
        result = _create_fallback_result("some message", discovery_state)

        assert result.action == Action.ANSWER_QUESTION_IN_CONTEXT
        assert result.confidence == 0.5

    def test_fallback_in_booking_phase(self, booking_state):
        """Test fallback defaults to ANSWER_QUESTION in booking."""
        result = _create_fallback_result("some message", booking_state)

        assert result.action == Action.ANSWER_QUESTION_IN_CONTEXT
        assert result.confidence == 0.5

    def test_fallback_without_state(self):
        """Test fallback without state context."""
        result = _create_fallback_result("some message", None)

        assert result.action == Action.ANSWER_QUESTION_IN_CONTEXT
        assert "no state context" in result.reason.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# Test Main llm_classify Function
# ═══════════════════════════════════════════════════════════════════════════════


class TestLLMClassify:
    """Tests for the main llm_classify() function."""

    @pytest.mark.asyncio
    async def test_llm_classify_ambiguous_message(self, clarification_state):
        """Test LLM classification of ambiguous message."""
        # When Azure is not configured, should use fallback
        with patch(
            "src.orchestrator.classification.llm_classify._call_classifier_agent",
            new_callable=AsyncMock,
            return_value=None,  # Simulate Azure not available
        ):
            result = await llm_classify(
                message="I'm not sure about this",
                state=clarification_state,
            )

            # Should use fallback
            assert result.action == Action.CONTINUE_CLARIFICATION
            assert result.confidence == 0.5

    @pytest.mark.asyncio
    async def test_llm_classify_parses_response(self, clarification_state):
        """Test that LLM classify correctly parses LLM response."""
        mock_result = LLMClassificationResult(
            action=Action.APPROVE_TRIP_SPEC,
            confidence=0.92,
            reason="LLM classified as APPROVE_TRIP_SPEC",
        )

        with patch(
            "src.orchestrator.classification.llm_classify._call_classifier_agent",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await llm_classify(
                message="yeah that works for me",
                state=clarification_state,
            )

            assert result.action == Action.APPROVE_TRIP_SPEC
            assert result.confidence == 0.92

    @pytest.mark.asyncio
    async def test_llm_classify_confidence_score(self, clarification_state):
        """Test that LLM classification includes confidence score."""
        mock_result = LLMClassificationResult(
            action=Action.REQUEST_MODIFICATION,
            confidence=0.78,
            reason="User wants changes",
        )

        with patch(
            "src.orchestrator.classification.llm_classify._call_classifier_agent",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await llm_classify(
                message="hmm maybe we could adjust things",
                state=clarification_state,
            )

            assert 0.0 <= result.confidence <= 1.0
            assert result.confidence == 0.78

    @pytest.mark.asyncio
    async def test_llm_classify_uses_agent(self, trip_spec_approval_state, mock_orchestrator_llm):
        """Test that LLM classify uses the classifier agent when available."""
        mock_result = LLMClassificationResult(
            action=Action.APPROVE_TRIP_SPEC,
            confidence=0.95,
            reason="Clear approval intent",
        )

        with patch(
            "src.orchestrator.classification.llm_classify._call_classifier_agent",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_call:
            result = await llm_classify(
                message="that looks perfect",
                state=trip_spec_approval_state,
                llm=mock_orchestrator_llm,
                session_id="test_session",
            )

            # Verify _call_classifier_agent was called
            mock_call.assert_called_once()
            # Verify the prompt was built with context
            call_args = mock_call.call_args
            prompt = call_args[0][0]  # First positional arg is prompt
            assert "Tokyo" in prompt or "trip_spec_approval" in prompt

    @pytest.mark.asyncio
    async def test_llm_classify_handles_exception(self, clarification_state):
        """Test that LLM classify gracefully handles exceptions."""
        with patch(
            "src.orchestrator.classification.llm_classify._call_classifier_agent",
            new_callable=AsyncMock,
            side_effect=Exception("Azure connection failed"),
        ):
            # Should not raise, should return fallback
            result = await llm_classify(
                message="some ambiguous message",
                state=clarification_state,
            )

            assert result is not None
            assert result.action == Action.CONTINUE_CLARIFICATION
            assert result.confidence == 0.5

    @pytest.mark.asyncio
    async def test_llm_classify_without_state(self):
        """Test LLM classification without workflow state."""
        with patch(
            "src.orchestrator.classification.llm_classify._call_classifier_agent",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await llm_classify(
                message="help me plan a trip",
                state=None,
            )

            # Should use fallback with default action
            assert result.action == Action.ANSWER_QUESTION_IN_CONTEXT


# ═══════════════════════════════════════════════════════════════════════════════
# Integration Tests (Mock Azure)
# ═══════════════════════════════════════════════════════════════════════════════


class TestLLMClassifyIntegration:
    """Integration-style tests with mocked Azure agent."""

    @pytest.mark.asyncio
    async def test_classify_approval_in_context(self, trip_spec_approval_state):
        """Test classifying an approval message in trip spec approval context."""
        mock_result = LLMClassificationResult(
            action=Action.APPROVE_TRIP_SPEC,
            confidence=0.95,
            reason="User expressed approval at trip spec checkpoint",
        )

        with patch(
            "src.orchestrator.classification.llm_classify._call_classifier_agent",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await llm_classify(
                message="alright, that works for me I suppose",
                state=trip_spec_approval_state,
            )

            assert result.action == Action.APPROVE_TRIP_SPEC
            assert result.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_classify_modification_request(self, trip_spec_approval_state):
        """Test classifying a modification request."""
        mock_result = LLMClassificationResult(
            action=Action.REQUEST_MODIFICATION,
            confidence=0.88,
            reason="User wants to change trip details",
        )

        with patch(
            "src.orchestrator.classification.llm_classify._call_classifier_agent",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await llm_classify(
                message="actually, on second thought, can we make some adjustments",
                state=trip_spec_approval_state,
            )

            assert result.action == Action.REQUEST_MODIFICATION

    @pytest.mark.asyncio
    async def test_classify_question_during_discovery(self, discovery_state):
        """Test classifying a question during discovery phase."""
        mock_result = LLMClassificationResult(
            action=Action.ANSWER_QUESTION_IN_CONTEXT,
            confidence=0.9,
            reason="User is asking a question",
        )

        with patch(
            "src.orchestrator.classification.llm_classify._call_classifier_agent",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await llm_classify(
                message="I'm curious about the hotel options",
                state=discovery_state,
            )

            assert result.action == Action.ANSWER_QUESTION_IN_CONTEXT


# ═══════════════════════════════════════════════════════════════════════════════
# Module Exports Test
# ═══════════════════════════════════════════════════════════════════════════════


class TestModuleExports:
    """Test that module exports are correct."""

    def test_classification_module_exports_llm_classify(self):
        """Test that classification module exports llm_classify."""
        from src.orchestrator.classification import (
            llm_classify,
            LLMClassificationResult,
            LLM_ACTION_TO_INTERNAL,
            DEFAULT_ACTION,
        )

        assert callable(llm_classify)
        assert LLMClassificationResult is not None
        assert isinstance(LLM_ACTION_TO_INTERNAL, dict)
        assert DEFAULT_ACTION == Action.CONTINUE_CLARIFICATION
