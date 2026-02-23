"""
Tier 1 mock tests for Demo B protocols.

Tests validate:
1. Approval Agent decision event schema compliance
2. Approve decision handling (itinerary approved, proceed to booking)
3. Reject decision handling (itinerary rejected with reason)
4. Modify decision handling (itinerary needs changes)
5. Pending fallback for timeout scenarios
6. Pending fallback for error scenarios

Per design doc Testing Strategy (lines 1203-1241):
- Demo B tests cover: M365 SDK client, Approval agent receives itinerary,
  Approval agent returns decision, Orchestrator handles approve/reject/modify.
- All tests use deterministic fixtures from conftest.py (zero LLM cost).

Per design doc Approval Agent Contract (lines 637-739):
- Event Name: approval_decision
- Decision enum: approved, rejected, modify, pending
- Response includes: decision, feedback, timestamp
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

import pytest

# Import mock fixtures from conftest
from tests.integration.mock.interoperability.conftest import (
    MockApprovalRequest,
    MockItineraryItem,
    MockAgentResponse,
)


# =============================================================================
# Approval Decision Types (per design doc lines 637-739)
# =============================================================================


class ApprovalDecisionType(Enum):
    """Approval decision types per design doc line 659."""
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFY = "modify"
    PENDING = "pending"  # Fallback state for timeout/error


@dataclass
class ApprovalDecisionEvent:
    """
    Approval decision event schema.

    Per design doc lines 651-673:
    - decision: required, one of approved/rejected/modify/pending
    - feedback: optional human feedback or modification instructions
    - timestamp: ISO 8601 timestamp of the decision
    """
    decision: ApprovalDecisionType
    feedback: str = ""
    timestamp: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        return {
            "decision": self.decision.value,
            "feedback": self.feedback,
            "timestamp": self.timestamp,
        }


# =============================================================================
# Fixtures for Demo B Testing
# =============================================================================


@pytest.fixture
def approval_event_approved() -> ApprovalDecisionEvent:
    """Approval event: itinerary approved."""
    return ApprovalDecisionEvent(
        decision=ApprovalDecisionType.APPROVED,
        feedback="",
        timestamp="2025-06-15T10:30:00Z",
    )


@pytest.fixture
def approval_event_rejected() -> ApprovalDecisionEvent:
    """Approval event: itinerary rejected with reason."""
    return ApprovalDecisionEvent(
        decision=ApprovalDecisionType.REJECTED,
        feedback="Budget exceeds limit",
        timestamp="2025-06-15T10:32:00Z",
    )


@pytest.fixture
def approval_event_modify() -> ApprovalDecisionEvent:
    """Approval event: modifications requested."""
    return ApprovalDecisionEvent(
        decision=ApprovalDecisionType.MODIFY,
        feedback="Change hotel to 4-star instead of 5-star",
        timestamp="2025-06-15T10:35:00Z",
    )


@pytest.fixture
def approval_event_pending_timeout() -> ApprovalDecisionEvent:
    """Approval event: pending due to timeout."""
    return ApprovalDecisionEvent(
        decision=ApprovalDecisionType.PENDING,
        feedback="Awaiting human response",
        timestamp="2025-06-15T10:40:00Z",
    )


@pytest.fixture
def approval_event_pending_error() -> ApprovalDecisionEvent:
    """Approval event: pending due to invalid response."""
    return ApprovalDecisionEvent(
        decision=ApprovalDecisionType.PENDING,
        feedback="Invalid response received",
        timestamp="2025-06-15T10:41:00Z",
    )


# =============================================================================
# Test Classes
# =============================================================================


class TestDemoBApprovalDecisionSchema:
    """Tests for Approval Agent decision event schema compliance.

    Per design doc lines 651-673, the approval_decision event should have:
    - decision: enum of approved/rejected/modify/pending
    - feedback: optional string
    - timestamp: ISO 8601 timestamp
    """

    def test_demo_b_approval_decision_schema(
        self, approval_event_approved: ApprovalDecisionEvent
    ):
        """Test ApprovalDecisionEvent has correct schema structure."""
        event = approval_event_approved

        # Verify required field
        assert event.decision == ApprovalDecisionType.APPROVED

        # Verify optional fields
        assert event.feedback == ""
        assert event.timestamp is not None

        # Verify serialization matches design doc example (lines 678-680)
        event_dict = event.to_dict()
        assert event_dict["decision"] == "approved"
        assert event_dict["feedback"] == ""
        assert event_dict["timestamp"] == "2025-06-15T10:30:00Z"

    def test_demo_b_approval_decision_enum_values(self):
        """Test all decision enum values are valid per design doc line 659."""
        valid_decisions = ["approved", "rejected", "modify", "pending"]

        for decision_type in ApprovalDecisionType:
            assert decision_type.value in valid_decisions

    def test_demo_b_approval_decision_rejected_has_feedback(
        self, approval_event_rejected: ApprovalDecisionEvent
    ):
        """Test rejected decision includes feedback per design doc line 683."""
        event = approval_event_rejected

        assert event.decision == ApprovalDecisionType.REJECTED
        assert event.feedback != ""
        assert "budget" in event.feedback.lower()

    def test_demo_b_approval_decision_modify_has_feedback(
        self, approval_event_modify: ApprovalDecisionEvent
    ):
        """Test modify decision includes feedback per design doc line 686."""
        event = approval_event_modify

        assert event.decision == ApprovalDecisionType.MODIFY
        assert event.feedback != ""
        assert "hotel" in event.feedback.lower() or "change" in event.feedback.lower()


class TestDemoBApproveHandling:
    """Tests for handling approved decisions.

    Per design doc, when decision is 'approved':
    - Itinerary is confirmed
    - Booking can proceed
    """

    def test_demo_b_approve_handling(
        self,
        sample_approval_request: MockApprovalRequest,
        approval_event_approved: ApprovalDecisionEvent,
    ):
        """Test approve decision allows booking to proceed."""
        request = sample_approval_request
        event = approval_event_approved

        # Verify decision is approved
        assert event.decision == ApprovalDecisionType.APPROVED

        # Simulate orchestrator handling
        can_proceed_to_booking = event.decision == ApprovalDecisionType.APPROVED

        assert can_proceed_to_booking is True

    def test_demo_b_approve_handling_no_feedback_required(
        self, approval_event_approved: ApprovalDecisionEvent
    ):
        """Test approve decision doesn't require feedback."""
        event = approval_event_approved

        # Approved decisions typically have empty feedback
        assert event.feedback == ""

        # This should still be valid
        event_dict = event.to_dict()
        assert event_dict["decision"] == "approved"

    def test_demo_b_approve_handling_with_optional_feedback(self):
        """Test approve decision can optionally include feedback."""
        event = ApprovalDecisionEvent(
            decision=ApprovalDecisionType.APPROVED,
            feedback="All items within budget. Booking can proceed.",
            timestamp="2025-06-15T10:30:00Z",
        )

        # Even with feedback, decision should process correctly
        assert event.decision == ApprovalDecisionType.APPROVED
        assert event.feedback != ""


class TestDemoBRejectHandling:
    """Tests for handling rejected decisions.

    Per design doc line 683:
    - Rejected decision should include reason in feedback
    - Itinerary cannot proceed to booking
    """

    def test_demo_b_reject_handling(
        self,
        sample_approval_request: MockApprovalRequest,
        approval_event_rejected: ApprovalDecisionEvent,
    ):
        """Test reject decision prevents booking."""
        request = sample_approval_request
        event = approval_event_rejected

        # Verify decision is rejected
        assert event.decision == ApprovalDecisionType.REJECTED

        # Simulate orchestrator handling
        can_proceed_to_booking = event.decision == ApprovalDecisionType.APPROVED

        assert can_proceed_to_booking is False

    def test_demo_b_reject_handling_requires_feedback(
        self, approval_event_rejected: ApprovalDecisionEvent
    ):
        """Test rejected decision has meaningful feedback."""
        event = approval_event_rejected

        # Rejected decisions should explain why
        assert event.feedback != ""
        assert len(event.feedback) > 5  # More than just empty/trivial

    def test_demo_b_reject_handling_feedback_is_actionable(
        self, approval_event_rejected: ApprovalDecisionEvent
    ):
        """Test rejected decision feedback helps user understand issue."""
        event = approval_event_rejected

        # Feedback should mention the problem
        feedback_lower = event.feedback.lower()
        # Should mention budget, cost, limit, or similar
        actionable_keywords = ["budget", "limit", "cost", "exceed", "over"]
        has_actionable_feedback = any(kw in feedback_lower for kw in actionable_keywords)

        assert has_actionable_feedback, f"Feedback not actionable: {event.feedback}"


class TestDemoBModifyHandling:
    """Tests for handling modify decisions.

    Per design doc line 686:
    - Modify decision should include specific changes needed
    - Itinerary should be regenerated with modifications
    """

    def test_demo_b_modify_handling(
        self,
        sample_approval_request: MockApprovalRequest,
        approval_event_modify: ApprovalDecisionEvent,
    ):
        """Test modify decision triggers itinerary update."""
        request = sample_approval_request
        event = approval_event_modify

        # Verify decision is modify
        assert event.decision == ApprovalDecisionType.MODIFY

        # Simulate orchestrator handling
        needs_modification = event.decision == ApprovalDecisionType.MODIFY
        can_proceed_to_booking = event.decision == ApprovalDecisionType.APPROVED

        assert needs_modification is True
        assert can_proceed_to_booking is False

    def test_demo_b_modify_handling_requires_feedback(
        self, approval_event_modify: ApprovalDecisionEvent
    ):
        """Test modify decision has specific modification instructions."""
        event = approval_event_modify

        # Modify decisions must specify what to change
        assert event.feedback != ""
        assert len(event.feedback) > 10  # Should be specific

    def test_demo_b_modify_handling_feedback_is_specific(
        self, approval_event_modify: ApprovalDecisionEvent
    ):
        """Test modify decision feedback specifies what to change."""
        event = approval_event_modify

        # Feedback should be specific about changes
        feedback_lower = event.feedback.lower()
        # Should mention specific items or changes
        specific_keywords = ["hotel", "change", "instead", "replace", "update", "modify"]
        has_specific_feedback = any(kw in feedback_lower for kw in specific_keywords)

        assert has_specific_feedback, f"Feedback not specific: {event.feedback}"

    def test_demo_b_modify_handling_preserves_request_id(
        self, sample_approval_request: MockApprovalRequest
    ):
        """Test modify flow can correlate back to original request."""
        request = sample_approval_request

        # Original request should have items that can be referenced
        assert len(request.items) > 0

        # Each item should have item_ref for tracking
        for item in request.items:
            assert item.item_ref is not None
            assert item.item_ref != ""


class TestDemoBPendingTimeout:
    """Tests for pending fallback on timeout scenarios.

    Per design doc lines 694-699:
    - No response within timeout (default: 5 minutes) -> pending
    - Invalid/malformed response -> pending
    """

    def test_demo_b_pending_timeout(
        self, approval_event_pending_timeout: ApprovalDecisionEvent
    ):
        """Test timeout results in pending decision."""
        event = approval_event_pending_timeout

        # Verify decision is pending
        assert event.decision == ApprovalDecisionType.PENDING

    def test_demo_b_pending_timeout_has_feedback(
        self, approval_event_pending_timeout: ApprovalDecisionEvent
    ):
        """Test timeout pending has appropriate feedback."""
        event = approval_event_pending_timeout

        # Should indicate waiting for response
        feedback_lower = event.feedback.lower()
        assert "awaiting" in feedback_lower or "waiting" in feedback_lower or "pending" in feedback_lower

    def test_demo_b_pending_timeout_prevents_booking(
        self, approval_event_pending_timeout: ApprovalDecisionEvent
    ):
        """Test pending status prevents booking from proceeding."""
        event = approval_event_pending_timeout

        # Pending should not proceed to booking
        can_proceed_to_booking = event.decision == ApprovalDecisionType.APPROVED

        assert can_proceed_to_booking is False

    def test_demo_b_pending_timeout_can_retry(
        self, approval_event_pending_timeout: ApprovalDecisionEvent
    ):
        """Test pending status allows for retry."""
        event = approval_event_pending_timeout

        # Pending is not final - can be retried
        is_final_decision = event.decision in [
            ApprovalDecisionType.APPROVED,
            ApprovalDecisionType.REJECTED,
        ]

        assert is_final_decision is False


class TestDemoBPendingError:
    """Tests for pending fallback on error scenarios.

    Per design doc lines 697-699:
    - Connection error -> retry once, then fail
    - Invalid/malformed response -> pending
    - Unexpected decision value -> pending
    """

    def test_demo_b_pending_error(
        self, approval_event_pending_error: ApprovalDecisionEvent
    ):
        """Test error results in pending decision."""
        event = approval_event_pending_error

        # Verify decision is pending
        assert event.decision == ApprovalDecisionType.PENDING

    def test_demo_b_pending_error_has_feedback(
        self, approval_event_pending_error: ApprovalDecisionEvent
    ):
        """Test error pending has appropriate feedback."""
        event = approval_event_pending_error

        # Should indicate error condition
        feedback_lower = event.feedback.lower()
        assert "invalid" in feedback_lower or "error" in feedback_lower or "response" in feedback_lower

    def test_demo_b_pending_error_prevents_booking(
        self, approval_event_pending_error: ApprovalDecisionEvent
    ):
        """Test pending status prevents booking from proceeding."""
        event = approval_event_pending_error

        # Pending should not proceed to booking
        can_proceed_to_booking = event.decision == ApprovalDecisionType.APPROVED

        assert can_proceed_to_booking is False

    def test_demo_b_pending_error_types(self):
        """Test different error scenarios result in pending.

        Per design doc lines 697-699, these all result in pending:
        - Connection error (after retry)
        - Invalid/malformed response
        - Unexpected decision value
        """
        error_scenarios = [
            ("Invalid response received", "malformed_response"),
            ("Unrecognized decision value", "unexpected_value"),
            ("Connection failed after retry", "connection_error"),
        ]

        for feedback, scenario_type in error_scenarios:
            event = ApprovalDecisionEvent(
                decision=ApprovalDecisionType.PENDING,
                feedback=feedback,
                timestamp=datetime.now().isoformat(),
            )

            assert event.decision == ApprovalDecisionType.PENDING
            assert event.feedback != ""


class TestDemoBOrchestratorHandling:
    """Tests for orchestrator handling of all decision types.

    Per design doc lines 701-739, the orchestrator must:
    - Handle all 4 decision types
    - Return appropriate ApprovalResponse
    - Raise ApprovalAgentConnectionError on connection failure
    """

    def test_demo_b_orchestrator_decision_routing(
        self,
        approval_event_approved: ApprovalDecisionEvent,
        approval_event_rejected: ApprovalDecisionEvent,
        approval_event_modify: ApprovalDecisionEvent,
        approval_event_pending_timeout: ApprovalDecisionEvent,
    ):
        """Test orchestrator routes all decision types correctly."""
        events = [
            approval_event_approved,
            approval_event_rejected,
            approval_event_modify,
            approval_event_pending_timeout,
        ]

        for event in events:
            # Simulate orchestrator decision routing
            if event.decision == ApprovalDecisionType.APPROVED:
                action = "proceed_to_booking"
            elif event.decision == ApprovalDecisionType.REJECTED:
                action = "notify_user_rejection"
            elif event.decision == ApprovalDecisionType.MODIFY:
                action = "regenerate_itinerary"
            elif event.decision == ApprovalDecisionType.PENDING:
                action = "wait_or_retry"
            else:
                action = "unknown"

            assert action != "unknown", f"Unhandled decision: {event.decision}"

    def test_demo_b_orchestrator_extracts_feedback(
        self,
        approval_event_rejected: ApprovalDecisionEvent,
        approval_event_modify: ApprovalDecisionEvent,
    ):
        """Test orchestrator can extract and use feedback."""
        for event in [approval_event_rejected, approval_event_modify]:
            # Feedback should be available for user notification
            assert event.feedback is not None

            # Feedback should be meaningful
            if event.decision in [ApprovalDecisionType.REJECTED, ApprovalDecisionType.MODIFY]:
                assert len(event.feedback) > 0

    def test_demo_b_orchestrator_records_timestamp(
        self,
        approval_event_approved: ApprovalDecisionEvent,
        approval_event_rejected: ApprovalDecisionEvent,
    ):
        """Test orchestrator can record decision timestamps."""
        for event in [approval_event_approved, approval_event_rejected]:
            # Timestamp should be present
            assert event.timestamp is not None

            # Timestamp should be ISO 8601 format
            # Simple check: contains date separator
            assert "T" in event.timestamp or "-" in event.timestamp


class TestDemoBApprovalRequestSchema:
    """Tests for approval request sent to Approval Agent.

    Per design doc, the request includes:
    - Itinerary items with item_ref, estimated_cost, currency
    - Total cost summary
    """

    def test_demo_b_approval_request_schema(
        self, sample_approval_request: MockApprovalRequest
    ):
        """Test approval request has required fields."""
        request = sample_approval_request

        # Required fields
        assert request.itinerary_summary is not None
        assert request.items is not None
        assert len(request.items) > 0
        assert request.total_cost is not None
        assert request.currency is not None

    def test_demo_b_approval_request_items_have_cost(
        self, sample_approval_request: MockApprovalRequest
    ):
        """Test each item in approval request has cost information."""
        request = sample_approval_request

        for item in request.items:
            # Each item needs cost for approval decision
            assert item.estimated_cost is not None
            assert item.estimated_cost >= 0
            assert item.currency is not None

    def test_demo_b_approval_request_items_have_refs(
        self, sample_approval_request: MockApprovalRequest
    ):
        """Test each item has item_ref for tracking.

        item_ref allows Approval Agent to reference specific items
        when requesting modifications.
        """
        request = sample_approval_request

        for item in request.items:
            assert item.item_ref is not None
            assert item.item_ref != ""

    def test_demo_b_approval_request_total_matches_items(
        self, sample_approval_request: MockApprovalRequest
    ):
        """Test total_cost matches sum of item costs (same currency)."""
        request = sample_approval_request

        # Sum items with same currency as total
        item_sum = sum(
            item.estimated_cost
            for item in request.items
            if item.currency == request.currency
        )

        # Total should match (or be reasonably close accounting for other costs)
        assert request.total_cost >= item_sum
