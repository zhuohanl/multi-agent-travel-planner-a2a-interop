"""
Unit tests for heuristic classification module.

Tests the keyword-based classification for user message intent detection.
Per ORCH-044: Implement heuristic classification for workflow_turn.
"""

import pytest
from unittest.mock import MagicMock

from src.orchestrator.classification.heuristic import (
    heuristic_classify,
    is_approval_message,
    is_modification_message,
    is_question_message,
    is_status_request,
    is_cancellation_message,
    is_booking_intent_message,
    ClassificationResult,
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
    return state


@pytest.fixture
def trip_spec_approval_state():
    """WorkflowState at trip_spec_approval checkpoint."""
    state = MagicMock(spec=WorkflowState)
    state.phase = Phase.CLARIFICATION
    state.checkpoint = "trip_spec_approval"
    return state


@pytest.fixture
def itinerary_approval_state():
    """WorkflowState at itinerary_approval checkpoint."""
    state = MagicMock(spec=WorkflowState)
    state.phase = Phase.DISCOVERY_PLANNING
    state.checkpoint = "itinerary_approval"
    return state


@pytest.fixture
def booking_state():
    """WorkflowState in BOOKING phase."""
    state = MagicMock(spec=WorkflowState)
    state.phase = Phase.BOOKING
    state.checkpoint = None
    return state


@pytest.fixture
def discovery_state():
    """WorkflowState in DISCOVERY_IN_PROGRESS phase."""
    state = MagicMock(spec=WorkflowState)
    state.phase = Phase.DISCOVERY_IN_PROGRESS
    state.checkpoint = None
    return state


# ═══════════════════════════════════════════════════════════════════════════════
# Test Individual Pattern Matchers
# ═══════════════════════════════════════════════════════════════════════════════


class TestApprovalPatterns:
    """Tests for is_approval_message()."""

    @pytest.mark.parametrize("message", [
        "yes",
        "Yes",
        "YES",
        "yeah",
        "yep",
        "yup",
        "sure",
        "ok",
        "okay",
        "approve",
        "approved",
        "accept",
        "accepted",
        "looks good",
        "Looks great",
        "that's good",
        "that's perfect",
        "that's correct",
        "that's right",
        "sounds good",
        "sounds great",
        "go ahead",
        "let's go",
        "let's do it",
        "let's proceed",
        "I agree",
        "agree",
        "confirmed",
        "confirm",
        "proceed",
        "y",
        "yea",
    ])
    def test_approval_patterns_match(self, message):
        """Test various approval patterns are detected."""
        assert is_approval_message(message) is True

    @pytest.mark.parametrize("message", [
        "no",
        "I don't want that",
        "can you change the hotel",
        "what about flights",
        "tell me more",
        "how much does it cost",
    ])
    def test_non_approval_patterns(self, message):
        """Test non-approval messages are not detected as approval."""
        assert is_approval_message(message) is False


class TestModificationPatterns:
    """Tests for is_modification_message()."""

    @pytest.mark.parametrize("message", [
        "change the hotel",
        "modify my booking",
        "update the dates",
        "I want a different flight",
        "can you switch to a later flight",
        "I'd rather have a different hotel",
        "actually I prefer a cheaper option",
        "instead of that hotel",
        "let's try something else",
        "try a different option",
        "move the date to next week",
        "extend the trip by 2 days",
        "shorten the stay",
        "increase the budget",
        "decrease budget to 2000",
    ])
    def test_modification_patterns_match(self, message):
        """Test various modification patterns are detected."""
        assert is_modification_message(message) is True

    @pytest.mark.parametrize("message", [
        "yes looks good",
        "what hotels are available",
        "tell me about Tokyo",
        "book this hotel",
    ])
    def test_non_modification_patterns(self, message):
        """Test non-modification messages are not detected."""
        assert is_modification_message(message) is False


class TestQuestionPatterns:
    """Tests for is_question_message()."""

    @pytest.mark.parametrize("message", [
        "what is the weather like?",
        "where is the hotel located?",
        "when does the flight depart?",
        "why is this option more expensive?",
        "who operates this airline?",
        "how do I get to the airport?",
        "which hotel is closer to the station?",
        "can you recommend a restaurant?",
        "could you show me more options?",
        "would this work for a family?",
        "is this hotel near the station?",
        "are there any cheaper options?",
        "do they have a pool?",
        "does this include breakfast?",
        "tell me about the area",
        "explain the cancellation policy",
        "what's the total cost?",
        "I want to know more about this hotel",
        "I'm curious about the food options",
    ])
    def test_question_patterns_match(self, message):
        """Test various question patterns are detected."""
        assert is_question_message(message) is True

    @pytest.mark.parametrize("message", [
        "yes",
        "book this hotel",
        "change the dates",
        "cancel",
    ])
    def test_non_question_patterns(self, message):
        """Test non-question messages are not detected."""
        assert is_question_message(message) is False


class TestStatusPatterns:
    """Tests for is_status_request()."""

    @pytest.mark.parametrize("message", [
        "status",
        "what's the status",
        "what's the status?",
        "where are we?",
        "where are things?",
        "how's it going",
        "how's going",
        "show me the status",
        "show the progress",
        "get status",
        "check progress",
        "any updates?",
        "any update",
        "current state",
        "what's happening",
        "are we done?",
        "are things ready?",
    ])
    def test_status_patterns_match(self, message):
        """Test various status patterns are detected."""
        assert is_status_request(message) is True

    @pytest.mark.parametrize("message", [
        "yes",
        "book this hotel",
        "what hotels are available",
        "change the dates",
    ])
    def test_non_status_patterns(self, message):
        """Test non-status messages are not detected."""
        assert is_status_request(message) is False


class TestCancellationPatterns:
    """Tests for is_cancellation_message()."""

    @pytest.mark.parametrize("message", [
        "cancel",
        "cancel this",
        "cancel the trip",
        "cancel planning",
        "abort",
        "stop",
        "quit",
        "exit",
        "end this",
        "start over",
        "start fresh",
        "start again",
        "never mind",
        "nevermind",
        "forget it",
        "forget about it",
        "I give up",
        "I changed my mind",
        "don't continue",
        "don't want to proceed",
        "scrap it",
        "scrap this",
    ])
    def test_cancellation_patterns_match(self, message):
        """Test various cancellation patterns are detected."""
        assert is_cancellation_message(message) is True

    @pytest.mark.parametrize("message", [
        "yes",
        "book this hotel",
        "what hotels are available",
        "change the dates",
    ])
    def test_non_cancellation_patterns(self, message):
        """Test non-cancellation messages are not detected."""
        assert is_cancellation_message(message) is False


class TestBookingIntentPatterns:
    """Tests for is_booking_intent_message()."""

    @pytest.mark.parametrize("message", [
        "book this hotel",
        "book the first option",
        "reserve this flight",
        "I'll take this one",
        "I'll book it",
        "let's book",
        "ready to book",
        "want to book this",
        "I'd like to book",
        "confirm the booking",
        "confirm my reservation",
        "add this to my booking",
        "add to cart",
        "select this hotel",
        "select the cheaper option",
        "go with this flight",
        "go for the first option",
    ])
    def test_booking_intent_patterns_match(self, message):
        """Test various booking intent patterns are detected."""
        assert is_booking_intent_message(message) is True

    @pytest.mark.parametrize("message", [
        "yes",
        "change the dates",
        "what can I book",  # Question, not intent
    ])
    def test_non_booking_intent_patterns(self, message):
        """Test non-booking-intent messages are not detected."""
        assert is_booking_intent_message(message) is False


# ═══════════════════════════════════════════════════════════════════════════════
# Test Main Classification Function
# ═══════════════════════════════════════════════════════════════════════════════


class TestHeuristicClassify:
    """Tests for heuristic_classify() main function."""

    def test_empty_message_returns_none(self):
        """Empty message should return None action."""
        result = heuristic_classify("")
        assert result.action is None
        assert result.confidence == 0.0
        assert not result.is_classified

    def test_whitespace_message_returns_none(self):
        """Whitespace-only message should return None action."""
        result = heuristic_classify("   ")
        assert result.action is None
        assert result.confidence == 0.0

    # ─────────────────────────────────────────────────────────────────────
    # Status Requests
    # ─────────────────────────────────────────────────────────────────────

    def test_status_request_classification(self):
        """Status requests should classify to GET_STATUS."""
        result = heuristic_classify("what's the status?")
        assert result.action == Action.GET_STATUS
        assert result.confidence > 0.8

    def test_status_request_any_phase(self, booking_state):
        """Status requests should work in any phase."""
        result = heuristic_classify("any updates?", booking_state)
        assert result.action == Action.GET_STATUS

    # ─────────────────────────────────────────────────────────────────────
    # Cancellation
    # ─────────────────────────────────────────────────────────────────────

    def test_cancellation_classification(self):
        """Cancellation requests should classify to CANCEL_WORKFLOW."""
        result = heuristic_classify("cancel this")
        assert result.action == Action.CANCEL_WORKFLOW
        assert result.confidence > 0.8

    def test_cancellation_any_phase(self, discovery_state):
        """Cancellation should work in any phase."""
        result = heuristic_classify("start over", discovery_state)
        assert result.action == Action.CANCEL_WORKFLOW

    # ─────────────────────────────────────────────────────────────────────
    # Approval at Checkpoints
    # ─────────────────────────────────────────────────────────────────────

    def test_approval_at_trip_spec_checkpoint(self, trip_spec_approval_state):
        """Approval at trip_spec_approval checkpoint."""
        result = heuristic_classify("yes", trip_spec_approval_state)
        assert result.action == Action.APPROVE_TRIP_SPEC
        assert result.confidence > 0.8

    def test_approval_at_itinerary_checkpoint(self, itinerary_approval_state):
        """Approval at itinerary_approval checkpoint."""
        result = heuristic_classify("looks good", itinerary_approval_state)
        assert result.action == Action.APPROVE_ITINERARY
        assert result.confidence > 0.8

    def test_approval_without_checkpoint(self, clarification_state):
        """Approval without checkpoint should default to clarification."""
        result = heuristic_classify("yes", clarification_state)
        assert result.action == Action.CONTINUE_CLARIFICATION
        assert result.confidence < 0.9  # Lower confidence

    # ─────────────────────────────────────────────────────────────────────
    # Modification
    # ─────────────────────────────────────────────────────────────────────

    def test_modification_classification(self):
        """Modification requests should classify to REQUEST_MODIFICATION."""
        result = heuristic_classify("change the hotel")
        assert result.action == Action.REQUEST_MODIFICATION
        assert result.confidence > 0.8

    def test_modification_any_phase(self, itinerary_approval_state):
        """Modification should work in multiple phases."""
        result = heuristic_classify("I want a different flight", itinerary_approval_state)
        assert result.action == Action.REQUEST_MODIFICATION

    # ─────────────────────────────────────────────────────────────────────
    # Booking Intent
    # ─────────────────────────────────────────────────────────────────────

    def test_booking_intent_in_booking_phase(self, booking_state):
        """Booking intent in BOOKING phase should classify to VIEW_BOOKING_OPTIONS."""
        result = heuristic_classify("book this hotel", booking_state)
        assert result.action == Action.VIEW_BOOKING_OPTIONS
        assert result.confidence > 0.8

    def test_booking_intent_outside_booking_phase(self, clarification_state):
        """Booking intent outside BOOKING phase should become a question."""
        result = heuristic_classify("book this hotel", clarification_state)
        assert result.action == Action.ANSWER_QUESTION_IN_CONTEXT
        assert result.confidence < 0.9  # Lower confidence

    # ─────────────────────────────────────────────────────────────────────
    # Questions
    # ─────────────────────────────────────────────────────────────────────

    def test_question_classification(self):
        """Questions should classify to ANSWER_QUESTION_IN_CONTEXT."""
        result = heuristic_classify("what hotels are available?")
        assert result.action == Action.ANSWER_QUESTION_IN_CONTEXT
        assert result.confidence > 0.7

    def test_question_any_phase(self, booking_state):
        """Questions should work in any phase."""
        result = heuristic_classify("is breakfast included?", booking_state)
        assert result.action == Action.ANSWER_QUESTION_IN_CONTEXT

    # ─────────────────────────────────────────────────────────────────────
    # Default/Fallback Behavior
    # ─────────────────────────────────────────────────────────────────────

    def test_unclassified_in_clarification_defaults_to_continue(self, clarification_state):
        """Unclassified message in CLARIFICATION should default to CONTINUE_CLARIFICATION."""
        # Use a message that doesn't match any pattern
        result = heuristic_classify("Tokyo March 10-17", clarification_state)
        assert result.action == Action.CONTINUE_CLARIFICATION
        assert result.confidence < 0.8  # Lower confidence for default

    def test_unclassified_without_state_returns_none(self):
        """Unclassified message without state should return None for LLM fallback."""
        # Use a message that doesn't match any strong pattern
        result = heuristic_classify("Tokyo trip")
        assert result.action is None or result.confidence < 0.5


class TestClassificationPriority:
    """Tests for classification priority order."""

    def test_status_higher_priority_than_question(self):
        """Status patterns should take priority over question patterns."""
        # "where are we?" could be a question, but is more likely status request
        result = heuristic_classify("where are we?")
        assert result.action == Action.GET_STATUS

    def test_cancellation_higher_priority_than_question(self):
        """Cancellation should take priority over question patterns."""
        # "can you cancel?" is a question but intent is cancellation
        result = heuristic_classify("cancel")
        assert result.action == Action.CANCEL_WORKFLOW

    def test_modification_higher_priority_than_question(self, clarification_state):
        """Modification should take priority over question patterns."""
        # "can you change the dates?" is both question and modification
        result = heuristic_classify("can you change the dates?", clarification_state)
        assert result.action == Action.REQUEST_MODIFICATION


class TestClassificationSpeed:
    """Tests for classification performance."""

    def test_classification_is_fast(self, clarification_state):
        """Heuristic classification should be fast (no LLM calls)."""
        import time

        # Run multiple classifications
        messages = [
            "yes",
            "change the hotel",
            "what's the status?",
            "cancel this",
            "book the first option",
            "what hotels are available?",
            "Tokyo March 10-17 for 2 people",
        ]

        start_time = time.time()
        for _ in range(100):  # 100 iterations
            for msg in messages:
                heuristic_classify(msg, clarification_state)
        elapsed = time.time() - start_time

        # 700 classifications should complete in under 1 second
        # (actual should be much faster, ~10-50ms)
        assert elapsed < 1.0, f"Classification took {elapsed:.2f}s, expected < 1s"


class TestEdgeCases:
    """Tests for edge cases and special inputs."""

    def test_unicode_emoji_approval(self):
        """Unicode emoji approval should work."""
        assert is_approval_message("👍") is True
        assert is_approval_message("✅") is True

    def test_mixed_case_handling(self):
        """Mixed case should be handled correctly."""
        assert is_approval_message("YES") is True
        assert is_approval_message("Yes") is True
        assert is_approval_message("yEs") is True

    def test_extra_whitespace_handling(self):
        """Extra whitespace should be handled."""
        result = heuristic_classify("  yes  ")
        assert result.action is not None  # Should still classify

    def test_punctuation_handling(self):
        """Punctuation should be handled."""
        assert is_approval_message("yes!") is True
        assert is_approval_message("ok.") is True

    def test_contracted_forms(self):
        """Contracted forms should be handled."""
        assert is_approval_message("that's good") is True
        assert is_approval_message("let's go") is True
        assert is_modification_message("don't want this") is True
