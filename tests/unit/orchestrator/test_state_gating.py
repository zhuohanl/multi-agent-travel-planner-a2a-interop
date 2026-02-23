"""
Unit tests for the state gating module.

Tests the core event and action validation logic as specified in the design doc:
- validate_event: Event validation against phase/checkpoint
- validate_action_for_phase: Action validation for free-text classification
- has_valid_booking_payload: Booking payload validation
"""

import pytest

from src.orchestrator.models.workflow_state import Phase, WorkflowState
from src.orchestrator.state_gating import (
    Action,
    BOOKING_ACTIONS_REQUIRING_PAYLOAD,
    BOOKING_PHASE_EVENTS,
    CHECKPOINT_GATED_EVENTS,
    CHECKPOINT_VALID_EVENTS,
    ERROR_RECOVERY_EVENTS,
    InvalidEventError,
    PHASE_VALID_ACTIONS,
    PHASE_VALID_EVENTS,
    UNIVERSAL_ACTIONS,
    WorkflowEvent,
    has_valid_booking_payload,
    validate_action_for_phase,
    validate_event,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def clarification_state() -> WorkflowState:
    """WorkflowState in CLARIFICATION phase with no checkpoint."""
    return WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_test123",
        phase=Phase.CLARIFICATION,
        checkpoint=None,
    )


@pytest.fixture
def clarification_at_checkpoint() -> WorkflowState:
    """WorkflowState in CLARIFICATION phase at trip_spec_approval checkpoint."""
    return WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_test123",
        phase=Phase.CLARIFICATION,
        checkpoint="trip_spec_approval",
    )


@pytest.fixture
def discovery_in_progress_state() -> WorkflowState:
    """WorkflowState in DISCOVERY_IN_PROGRESS phase."""
    return WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_test123",
        phase=Phase.DISCOVERY_IN_PROGRESS,
        checkpoint=None,
    )


@pytest.fixture
def discovery_planning_state() -> WorkflowState:
    """WorkflowState in DISCOVERY_PLANNING phase at itinerary_approval checkpoint."""
    return WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_test123",
        phase=Phase.DISCOVERY_PLANNING,
        checkpoint="itinerary_approval",
    )


@pytest.fixture
def booking_state() -> WorkflowState:
    """WorkflowState in BOOKING phase."""
    return WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_test123",
        phase=Phase.BOOKING,
        checkpoint=None,
    )


@pytest.fixture
def completed_state() -> WorkflowState:
    """WorkflowState in COMPLETED phase (terminal)."""
    return WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_test123",
        phase=Phase.COMPLETED,
        checkpoint=None,
    )


@pytest.fixture
def failed_state() -> WorkflowState:
    """WorkflowState in FAILED phase (terminal)."""
    return WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_test123",
        phase=Phase.FAILED,
        checkpoint=None,
    )


@pytest.fixture
def cancelled_state() -> WorkflowState:
    """WorkflowState in CANCELLED phase (terminal)."""
    return WorkflowState(
        session_id="sess_test123",
        consultation_id="cons_test123",
        phase=Phase.CANCELLED,
        checkpoint=None,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test Event Tables
# ═══════════════════════════════════════════════════════════════════════════════


class TestEventTables:
    """Test that event tables are correctly defined."""

    def test_checkpoint_valid_events_trip_spec(self):
        """Test trip_spec_approval checkpoint events."""
        events = CHECKPOINT_VALID_EVENTS["trip_spec_approval"]
        assert "approve_checkpoint" in events
        assert "request_change" in events
        assert "cancel_workflow" in events
        assert "free_text" in events
        assert len(events) == 4

    def test_checkpoint_valid_events_itinerary(self):
        """Test itinerary_approval checkpoint events."""
        events = CHECKPOINT_VALID_EVENTS["itinerary_approval"]
        assert "approve_checkpoint" in events
        assert "request_change" in events
        assert "retry_discovery" in events
        assert "cancel_workflow" in events
        assert "free_text" in events
        assert len(events) == 5

    def test_phase_valid_events_clarification(self):
        """Test CLARIFICATION phase valid events."""
        events = PHASE_VALID_EVENTS[Phase.CLARIFICATION]
        assert "free_text" in events
        assert "cancel_workflow" in events
        assert len(events) == 2

    def test_phase_valid_events_discovery(self):
        """Test DISCOVERY_IN_PROGRESS phase valid events."""
        events = PHASE_VALID_EVENTS[Phase.DISCOVERY_IN_PROGRESS]
        assert "free_text" in events
        assert "status" in events
        assert "cancel_workflow" in events
        assert "request_change" in events
        assert len(events) == 4

    def test_booking_phase_events(self):
        """Test BOOKING phase valid events."""
        assert "view_booking_options" in BOOKING_PHASE_EVENTS
        assert "book_item" in BOOKING_PHASE_EVENTS
        assert "retry_booking" in BOOKING_PHASE_EVENTS
        assert "cancel_booking" in BOOKING_PHASE_EVENTS
        assert "check_booking_status" in BOOKING_PHASE_EVENTS
        assert "cancel_unknown_booking" in BOOKING_PHASE_EVENTS
        assert "status" in BOOKING_PHASE_EVENTS
        assert "cancel_workflow" in BOOKING_PHASE_EVENTS
        assert "free_text" in BOOKING_PHASE_EVENTS
        assert len(BOOKING_PHASE_EVENTS) == 9

    def test_error_recovery_events(self):
        """Test error recovery events."""
        assert "retry_agent" in ERROR_RECOVERY_EVENTS
        assert "skip_agent" in ERROR_RECOVERY_EVENTS
        assert "start_new" in ERROR_RECOVERY_EVENTS
        assert len(ERROR_RECOVERY_EVENTS) == 3

    def test_checkpoint_gated_events(self):
        """Test checkpoint-gated events requiring checkpoint_id."""
        assert "approve_checkpoint" in CHECKPOINT_GATED_EVENTS
        assert "request_change" in CHECKPOINT_GATED_EVENTS
        assert "retry_discovery" in CHECKPOINT_GATED_EVENTS
        assert len(CHECKPOINT_GATED_EVENTS) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Test validate_event - Event Validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidateEvent:
    """Test the validate_event function."""

    # --- Terminal States ---

    def test_terminal_allows_start_new(self, completed_state):
        """Terminal phases allow start_new event."""
        event = WorkflowEvent(type="start_new")
        # Should not raise
        validate_event(completed_state, event)

    def test_terminal_allows_status(self, failed_state):
        """Terminal phases allow status event."""
        event = WorkflowEvent(type="status")
        # Should not raise
        validate_event(failed_state, event)

    def test_terminal_rejects_other_events(self, cancelled_state):
        """Terminal phases reject events other than start_new/status."""
        event = WorkflowEvent(type="free_text")
        with pytest.raises(InvalidEventError) as exc_info:
            validate_event(cancelled_state, event)
        assert "cancelled" in str(exc_info.value).lower()
        assert "'start_new' or 'status'" in str(exc_info.value)

    def test_all_terminal_states_reject_booking(self, completed_state, failed_state, cancelled_state):
        """All terminal states reject booking events."""
        event = WorkflowEvent(type="book_item")
        for state in [completed_state, failed_state, cancelled_state]:
            with pytest.raises(InvalidEventError):
                validate_event(state, event)

    # --- Error Recovery Events ---

    def test_error_recovery_valid_in_discovery_in_progress(self, discovery_in_progress_state):
        """Error recovery events are valid during DISCOVERY_IN_PROGRESS."""
        for event_type in ERROR_RECOVERY_EVENTS:
            event = WorkflowEvent(type=event_type)
            # Should not raise
            validate_event(discovery_in_progress_state, event)

    def test_error_recovery_valid_in_discovery_planning(self, discovery_planning_state):
        """Error recovery events are valid during DISCOVERY_PLANNING."""
        for event_type in ERROR_RECOVERY_EVENTS:
            event = WorkflowEvent(type=event_type)
            # Should not raise
            validate_event(discovery_planning_state, event)

    def test_error_recovery_invalid_in_clarification(self, clarification_state):
        """Error recovery events are invalid during CLARIFICATION."""
        event = WorkflowEvent(type="retry_agent")
        with pytest.raises(InvalidEventError) as exc_info:
            validate_event(clarification_state, event)
        assert "only valid during discovery or terminal phases" in str(exc_info.value)

    def test_error_recovery_invalid_in_booking(self, booking_state):
        """Error recovery events are invalid during BOOKING."""
        event = WorkflowEvent(type="skip_agent")
        with pytest.raises(InvalidEventError) as exc_info:
            validate_event(booking_state, event)
        assert "only valid during discovery or terminal phases" in str(exc_info.value)

    # --- Booking Phase ---

    def test_booking_phase_allows_booking_events(self, booking_state):
        """BOOKING phase allows all booking events."""
        for event_type in BOOKING_PHASE_EVENTS:
            event = WorkflowEvent(type=event_type)
            # Should not raise
            validate_event(booking_state, event)

    def test_booking_phase_rejects_invalid_events(self, booking_state):
        """BOOKING phase rejects events not in BOOKING_PHASE_EVENTS."""
        event = WorkflowEvent(type="approve_checkpoint")
        with pytest.raises(InvalidEventError) as exc_info:
            validate_event(booking_state, event)
        assert "not valid in booking phase" in str(exc_info.value)

    # --- Checkpoint Validation ---

    def test_checkpoint_allows_valid_events(self, clarification_at_checkpoint):
        """Checkpoint allows events in CHECKPOINT_VALID_EVENTS."""
        event = WorkflowEvent(type="approve_checkpoint", checkpoint_id="trip_spec_approval")
        # Should not raise
        validate_event(clarification_at_checkpoint, event)

    def test_checkpoint_rejects_invalid_events(self, clarification_at_checkpoint):
        """Checkpoint rejects events not in CHECKPOINT_VALID_EVENTS."""
        event = WorkflowEvent(type="book_item")
        with pytest.raises(InvalidEventError) as exc_info:
            validate_event(clarification_at_checkpoint, event)
        assert "not valid at checkpoint" in str(exc_info.value)

    def test_validate_event_rejects_stale_checkpoint_id(self, clarification_at_checkpoint):
        """Checkpoint-gated events with wrong checkpoint_id are rejected."""
        event = WorkflowEvent(type="approve_checkpoint", checkpoint_id="wrong_checkpoint")
        with pytest.raises(InvalidEventError) as exc_info:
            validate_event(clarification_at_checkpoint, event)
        assert exc_info.value.error_code == "STALE_CHECKPOINT"
        assert "Stale action" in str(exc_info.value)

    def test_validate_event_rejects_missing_checkpoint_id(self, clarification_at_checkpoint):
        """Checkpoint-gated events without checkpoint_id are rejected."""
        event = WorkflowEvent(type="approve_checkpoint", checkpoint_id=None)
        with pytest.raises(InvalidEventError) as exc_info:
            validate_event(clarification_at_checkpoint, event)
        assert exc_info.value.error_code == "MISSING_CHECKPOINT_ID"

    def test_validate_event_rejects_invalid_checkpoint_event(self, clarification_at_checkpoint):
        """Events not valid at the current checkpoint are rejected."""
        # retry_discovery is only valid at itinerary_approval, not trip_spec_approval
        event = WorkflowEvent(type="retry_discovery", checkpoint_id="trip_spec_approval")
        with pytest.raises(InvalidEventError) as exc_info:
            validate_event(clarification_at_checkpoint, event)
        assert "not valid at checkpoint" in str(exc_info.value)

    def test_itinerary_checkpoint_allows_retry_discovery(self, discovery_planning_state):
        """itinerary_approval checkpoint allows retry_discovery."""
        event = WorkflowEvent(type="retry_discovery", checkpoint_id="itinerary_approval")
        # Should not raise
        validate_event(discovery_planning_state, event)

    # --- Phase Validation (No Checkpoint) ---

    def test_clarification_allows_free_text(self, clarification_state):
        """CLARIFICATION phase allows free_text without checkpoint."""
        event = WorkflowEvent(type="free_text")
        # Should not raise
        validate_event(clarification_state, event)

    def test_clarification_rejects_booking_events(self, clarification_state):
        """CLARIFICATION phase rejects booking events."""
        event = WorkflowEvent(type="book_item")
        with pytest.raises(InvalidEventError) as exc_info:
            validate_event(clarification_state, event)
        assert "not valid in phase" in str(exc_info.value)

    def test_discovery_in_progress_allows_status(self, discovery_in_progress_state):
        """DISCOVERY_IN_PROGRESS allows status event."""
        event = WorkflowEvent(type="status")
        # Should not raise
        validate_event(discovery_in_progress_state, event)

    def test_discovery_in_progress_allows_request_change(self, discovery_in_progress_state):
        """DISCOVERY_IN_PROGRESS allows request_change (queued)."""
        event = WorkflowEvent(type="request_change")
        # Should not raise
        validate_event(discovery_in_progress_state, event)

    # --- Edge Cases ---

    def test_unexpected_state_raises_error(self):
        """Unexpected state combinations raise InvalidEventError."""
        # DISCOVERY_PLANNING with checkpoint=None is unexpected
        state = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_test",
            phase=Phase.DISCOVERY_PLANNING,
            checkpoint=None,  # Unexpected - should have itinerary_approval
        )
        event = WorkflowEvent(type="free_text")
        with pytest.raises(InvalidEventError) as exc_info:
            validate_event(state, event)
        assert "Unexpected state" in str(exc_info.value)


# ═══════════════════════════════════════════════════════════════════════════════
# Test validate_action_for_phase - Action Validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidateActionForPhase:
    """Test the validate_action_for_phase function."""

    def test_universal_actions_always_allowed(self, clarification_state, booking_state, completed_state):
        """Universal actions are allowed in all phases."""
        for state in [clarification_state, booking_state, completed_state]:
            for action in UNIVERSAL_ACTIONS:
                result = validate_action_for_phase(action, state)
                assert result == action

    def test_validate_action_for_phase_blocks_booking_outside_booking(self, clarification_state):
        """Booking actions are blocked outside BOOKING phase."""
        for action in [
            Action.BOOK_SINGLE_ITEM,
            Action.RETRY_BOOKING,
            Action.CANCEL_BOOKING,
            Action.CHECK_BOOKING_STATUS,
            Action.CANCEL_UNKNOWN_BOOKING,
        ]:
            result = validate_action_for_phase(action, clarification_state)
            assert result == Action.ANSWER_QUESTION_IN_CONTEXT

    def test_booking_actions_allowed_in_booking_phase(self, booking_state):
        """Booking actions are allowed in BOOKING phase."""
        booking_actions = PHASE_VALID_ACTIONS[Phase.BOOKING]
        for action in booking_actions:
            result = validate_action_for_phase(action, booking_state)
            assert result == action

    def test_approve_trip_spec_requires_checkpoint(self, clarification_state, clarification_at_checkpoint):
        """APPROVE_TRIP_SPEC requires trip_spec_approval checkpoint."""
        # Without checkpoint - should fallback
        result = validate_action_for_phase(Action.APPROVE_TRIP_SPEC, clarification_state)
        assert result == Action.ANSWER_QUESTION_IN_CONTEXT

        # With checkpoint - should be allowed
        result = validate_action_for_phase(Action.APPROVE_TRIP_SPEC, clarification_at_checkpoint)
        assert result == Action.APPROVE_TRIP_SPEC

    def test_approve_itinerary_requires_checkpoint(self, discovery_planning_state):
        """APPROVE_ITINERARY requires itinerary_approval checkpoint."""
        # With correct checkpoint - should be allowed
        result = validate_action_for_phase(Action.APPROVE_ITINERARY, discovery_planning_state)
        assert result == Action.APPROVE_ITINERARY

        # Wrong checkpoint
        state_wrong_checkpoint = WorkflowState(
            session_id="sess_test",
            consultation_id="cons_test",
            phase=Phase.DISCOVERY_PLANNING,
            checkpoint="trip_spec_approval",  # Wrong checkpoint
        )
        result = validate_action_for_phase(Action.APPROVE_ITINERARY, state_wrong_checkpoint)
        assert result == Action.ANSWER_QUESTION_IN_CONTEXT

    def test_start_new_allowed_in_terminal_states(self, completed_state, failed_state, cancelled_state):
        """START_NEW_WORKFLOW is allowed in terminal states."""
        for state in [completed_state, failed_state, cancelled_state]:
            result = validate_action_for_phase(Action.START_NEW_WORKFLOW, state)
            assert result == Action.START_NEW_WORKFLOW

    def test_start_new_blocked_in_clarification(self, clarification_state):
        """START_NEW_WORKFLOW is blocked in CLARIFICATION."""
        result = validate_action_for_phase(Action.START_NEW_WORKFLOW, clarification_state)
        assert result == Action.ANSWER_QUESTION_IN_CONTEXT

    def test_request_modification_allowed_in_clarification(self, clarification_state):
        """REQUEST_MODIFICATION is allowed in CLARIFICATION."""
        result = validate_action_for_phase(Action.REQUEST_MODIFICATION, clarification_state)
        assert result == Action.REQUEST_MODIFICATION

    def test_request_modification_allowed_in_discovery_in_progress(self, discovery_in_progress_state):
        """REQUEST_MODIFICATION is allowed in DISCOVERY_IN_PROGRESS (queued)."""
        result = validate_action_for_phase(Action.REQUEST_MODIFICATION, discovery_in_progress_state)
        assert result == Action.REQUEST_MODIFICATION


# ═══════════════════════════════════════════════════════════════════════════════
# Test Booking Payload Validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestBookingPayloadValidation:
    """Test the has_valid_booking_payload function."""

    def test_missing_booking_payload(self):
        """Missing booking payload returns False."""
        event = WorkflowEvent(type="book_item", booking=None)
        assert not has_valid_booking_payload(event, Action.BOOK_SINGLE_ITEM)

    def test_booking_id_only_actions(self):
        """Actions requiring only booking_id."""
        actions_requiring_only_id = [
            Action.CANCEL_BOOKING,
            Action.CHECK_BOOKING_STATUS,
            Action.CANCEL_UNKNOWN_BOOKING,
        ]
        for action in actions_requiring_only_id:
            # Valid: has booking_id
            event = WorkflowEvent(type="test", booking={"booking_id": "book_123"})
            assert has_valid_booking_payload(event, action)

            # Invalid: missing booking_id
            event = WorkflowEvent(type="test", booking={})
            assert not has_valid_booking_payload(event, action)

    def test_booking_id_and_quote_id_actions(self):
        """Actions requiring both booking_id and quote_id."""
        actions_requiring_both = [
            Action.BOOK_SINGLE_ITEM,
            Action.RETRY_BOOKING,
        ]
        for action in actions_requiring_both:
            # Valid: has both
            event = WorkflowEvent(
                type="test",
                booking={"booking_id": "book_123", "quote_id": "quote_456"},
            )
            assert has_valid_booking_payload(event, action)

            # Invalid: missing quote_id
            event = WorkflowEvent(type="test", booking={"booking_id": "book_123"})
            assert not has_valid_booking_payload(event, action)

            # Invalid: missing booking_id
            event = WorkflowEvent(type="test", booking={"quote_id": "quote_456"})
            assert not has_valid_booking_payload(event, action)

    def test_booking_actions_requiring_payload_constant(self):
        """Verify BOOKING_ACTIONS_REQUIRING_PAYLOAD contains expected actions."""
        assert Action.BOOK_SINGLE_ITEM in BOOKING_ACTIONS_REQUIRING_PAYLOAD
        assert Action.RETRY_BOOKING in BOOKING_ACTIONS_REQUIRING_PAYLOAD
        assert Action.CANCEL_BOOKING in BOOKING_ACTIONS_REQUIRING_PAYLOAD
        assert Action.CHECK_BOOKING_STATUS in BOOKING_ACTIONS_REQUIRING_PAYLOAD
        assert Action.CANCEL_UNKNOWN_BOOKING in BOOKING_ACTIONS_REQUIRING_PAYLOAD
        # Ensure VIEW_BOOKING_OPTIONS doesn't require payload
        assert Action.VIEW_BOOKING_OPTIONS not in BOOKING_ACTIONS_REQUIRING_PAYLOAD


# ═══════════════════════════════════════════════════════════════════════════════
# Test InvalidEventError
# ═══════════════════════════════════════════════════════════════════════════════


class TestInvalidEventError:
    """Test the InvalidEventError exception."""

    def test_basic_error(self):
        """Test basic error creation."""
        error = InvalidEventError("Test message")
        assert str(error) == "Test message"
        assert error.message == "Test message"
        assert error.error_code == "INVALID_EVENT"
        assert error.retry_action is None

    def test_error_with_code(self):
        """Test error with custom error code."""
        error = InvalidEventError("Test", error_code="CUSTOM_CODE")
        assert error.error_code == "CUSTOM_CODE"

    def test_error_with_retry_action(self):
        """Test error with retry action."""
        retry = {"label": "Refresh", "event": {"type": "status"}}
        error = InvalidEventError("Test", retry_action=retry)
        assert error.retry_action == retry


# ═══════════════════════════════════════════════════════════════════════════════
# Test Action Enum
# ═══════════════════════════════════════════════════════════════════════════════


class TestActionEnum:
    """Test the Action enum."""

    def test_action_values(self):
        """Test that all expected actions exist."""
        expected_actions = [
            "start_clarification",
            "continue_clarification",
            "approve_trip_spec",
            "start_discovery",
            "approve_itinerary",
            "request_modification",
            "view_booking_options",
            "book_single_item",
            "retry_booking",
            "cancel_booking",
            "check_booking_status",
            "cancel_unknown_booking",
            "start_new_workflow",
            "answer_question_in_context",
            "call_utility",
            "cancel_workflow",
            "get_status",
        ]
        actual_values = [a.value for a in Action]
        for expected in expected_actions:
            assert expected in actual_values, f"Missing action: {expected}"

    def test_action_is_str_enum(self):
        """Test that Action inherits from str."""
        assert isinstance(Action.GET_STATUS.value, str)
        # Can be used as string
        assert Action.GET_STATUS == "get_status"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration Tests - End-to-End Scenarios
# ═══════════════════════════════════════════════════════════════════════════════


class TestEndToEndScenarios:
    """Test complete workflow scenarios."""

    def test_happy_path_clarification_to_discovery(self, clarification_at_checkpoint):
        """Test approval flow from clarification to discovery."""
        # User approves trip spec
        event = WorkflowEvent(type="approve_checkpoint", checkpoint_id="trip_spec_approval")
        validate_event(clarification_at_checkpoint, event)
        # Would then proceed to discovery...

    def test_happy_path_discovery_to_booking(self, discovery_planning_state):
        """Test approval flow from discovery planning to booking."""
        # User approves itinerary
        event = WorkflowEvent(type="approve_checkpoint", checkpoint_id="itinerary_approval")
        validate_event(discovery_planning_state, event)
        # Would then proceed to booking...

    def test_booking_flow(self, booking_state):
        """Test complete booking flow."""
        # View options
        validate_event(booking_state, WorkflowEvent(type="view_booking_options"))

        # Book item
        validate_event(
            booking_state,
            WorkflowEvent(
                type="book_item",
                booking={"booking_id": "book_123", "quote_id": "quote_456"},
            ),
        )

        # Check status
        validate_event(
            booking_state,
            WorkflowEvent(type="check_booking_status", booking={"booking_id": "book_123"}),
        )

    def test_error_recovery_flow(self, discovery_in_progress_state):
        """Test error recovery during discovery."""
        # Retry failed agent
        validate_event(discovery_in_progress_state, WorkflowEvent(type="retry_agent", agent_id="stay"))

        # Skip failed agent
        validate_event(discovery_in_progress_state, WorkflowEvent(type="skip_agent", agent_id="events"))

        # Start over
        validate_event(discovery_in_progress_state, WorkflowEvent(type="start_new"))

    def test_multi_tab_stale_approval_blocked(self, clarification_at_checkpoint):
        """Test that stale approvals from multiple tabs are blocked."""
        # Tab 1: User is at trip_spec_approval
        # Tab 2: User was at trip_spec_approval, but state has changed

        # Simulate Tab 2 sending stale approval (wrong checkpoint_id)
        event = WorkflowEvent(type="approve_checkpoint", checkpoint_id="wrong_checkpoint")
        with pytest.raises(InvalidEventError) as exc_info:
            validate_event(clarification_at_checkpoint, event)
        assert exc_info.value.error_code == "STALE_CHECKPOINT"
        assert exc_info.value.retry_action is not None  # Should suggest refresh

    def test_validate_event_allows_booking_phase_events(self, booking_state):
        """Test that all booking phase events are accepted."""
        for event_type in BOOKING_PHASE_EVENTS:
            event = WorkflowEvent(type=event_type)
            # All should pass without raising
            validate_event(booking_state, event)
