"""Unit tests for ApprovalRequest/ApprovalDecision shared schemas.

Tests validate:
- Schema creation with valid inputs
- Schema validation rejects invalid inputs
- ApprovalDecisionType enum has correct values
- Serialization matches design doc JSON format (lines 651-690)
- Schemas importable from both src/shared/models.py and interoperability/shared/schemas/approval.py
"""

import pytest
from pydantic import ValidationError


class TestApprovalDecisionType:
    """Tests for ApprovalDecisionType enum."""

    def test_approval_decision_enum_values(self):
        """Test ApprovalDecisionType has all required enum values per design doc."""
        from src.shared.models import ApprovalDecisionType

        # Verify all enum values exist
        assert ApprovalDecisionType.APPROVED.value == "approved"
        assert ApprovalDecisionType.REJECTED.value == "rejected"
        assert ApprovalDecisionType.MODIFY.value == "modify"
        assert ApprovalDecisionType.PENDING.value == "pending"

    def test_approval_decision_enum_is_string_enum(self):
        """Test ApprovalDecisionType is a string enum."""
        from src.shared.models import ApprovalDecisionType

        # Verify enum values can be used as strings
        assert str(ApprovalDecisionType.APPROVED) == "ApprovalDecisionType.APPROVED"
        assert ApprovalDecisionType.APPROVED.value == "approved"

    def test_approval_decision_all_values(self):
        """Test ApprovalDecisionType has exactly 4 values."""
        from src.shared.models import ApprovalDecisionType

        values = list(ApprovalDecisionType)
        assert len(values) == 4
        assert set(v.value for v in values) == {"approved", "rejected", "modify", "pending"}


class TestApprovalRequest:
    """Tests for ApprovalRequest schema validation."""

    def test_approval_request_valid(self):
        """Test ApprovalRequest with valid inputs per design doc."""
        from src.shared.models import ApprovalRequest, Itinerary

        # Create a minimal valid itinerary
        itinerary = Itinerary(days=[], total_estimated_cost=1500.0, currency="USD")

        request = ApprovalRequest(
            itinerary=itinerary,
            request_id="req_abc123",
        )

        assert request.request_id == "req_abc123"
        assert request.itinerary.currency == "USD"
        assert request.timeout_seconds == 300  # Default value

    def test_approval_request_with_custom_timeout(self):
        """Test ApprovalRequest with custom timeout value."""
        from src.shared.models import ApprovalRequest, Itinerary

        itinerary = Itinerary(days=[])
        request = ApprovalRequest(
            itinerary=itinerary,
            request_id="req_xyz789",
            timeout_seconds=600,
        )

        assert request.timeout_seconds == 600

    def test_approval_request_missing_itinerary(self):
        """Test ApprovalRequest rejects missing itinerary field."""
        from src.shared.models import ApprovalRequest

        with pytest.raises(ValidationError) as exc_info:
            ApprovalRequest(request_id="req_abc123")
        assert "itinerary" in str(exc_info.value)

    def test_approval_request_missing_request_id(self):
        """Test ApprovalRequest rejects missing request_id field."""
        from src.shared.models import ApprovalRequest, Itinerary

        itinerary = Itinerary(days=[])
        with pytest.raises(ValidationError) as exc_info:
            ApprovalRequest(itinerary=itinerary)
        assert "request_id" in str(exc_info.value)

    def test_approval_request_with_full_itinerary(self):
        """Test ApprovalRequest with a complete itinerary."""
        from src.shared.models import ApprovalRequest, Itinerary, ItineraryDay, ItinerarySlot

        slot = ItinerarySlot(
            start_time="09:00",
            end_time="12:00",
            activity="Visit Eiffel Tower",
            location="Paris, France",
            category="poi",
            estimated_cost=25.0,
            currency="EUR",
        )
        day = ItineraryDay(
            date="2025-06-15",
            slots=[slot],
            day_summary="Morning at Eiffel Tower",
        )
        itinerary = Itinerary(
            days=[day],
            total_estimated_cost=500.0,
            currency="EUR",
        )

        request = ApprovalRequest(
            itinerary=itinerary,
            request_id="req_full123",
        )

        assert len(request.itinerary.days) == 1
        assert request.itinerary.days[0].slots[0].activity == "Visit Eiffel Tower"


class TestApprovalDecision:
    """Tests for ApprovalDecision schema validation."""

    def test_approval_decision_approved(self):
        """Test ApprovalDecision with approved decision."""
        from src.shared.models import ApprovalDecision, ApprovalDecisionType

        decision = ApprovalDecision(
            request_id="req_abc123",
            decision=ApprovalDecisionType.APPROVED,
        )

        assert decision.request_id == "req_abc123"
        assert decision.decision == ApprovalDecisionType.APPROVED
        assert decision.feedback is None
        assert decision.timestamp is None

    def test_approval_decision_rejected_with_feedback(self):
        """Test ApprovalDecision with rejected decision and feedback."""
        from src.shared.models import ApprovalDecision, ApprovalDecisionType

        decision = ApprovalDecision(
            request_id="req_abc123",
            decision=ApprovalDecisionType.REJECTED,
            feedback="Budget exceeds limit",
            timestamp="2025-06-15T10:32:00Z",
        )

        assert decision.decision == ApprovalDecisionType.REJECTED
        assert decision.feedback == "Budget exceeds limit"
        assert decision.timestamp == "2025-06-15T10:32:00Z"

    def test_approval_decision_modify_with_feedback(self):
        """Test ApprovalDecision with modify decision and feedback."""
        from src.shared.models import ApprovalDecision, ApprovalDecisionType

        decision = ApprovalDecision(
            request_id="req_abc123",
            decision=ApprovalDecisionType.MODIFY,
            feedback="Change hotel to 4-star instead of 5-star",
            timestamp="2025-06-15T10:35:00Z",
        )

        assert decision.decision == ApprovalDecisionType.MODIFY
        assert decision.feedback == "Change hotel to 4-star instead of 5-star"

    def test_approval_decision_pending(self):
        """Test ApprovalDecision with pending decision (timeout/error fallback)."""
        from src.shared.models import ApprovalDecision, ApprovalDecisionType

        decision = ApprovalDecision(
            request_id="req_abc123",
            decision=ApprovalDecisionType.PENDING,
            feedback="Awaiting human response",
            timestamp="2025-06-15T10:40:00Z",
        )

        assert decision.decision == ApprovalDecisionType.PENDING
        assert decision.feedback == "Awaiting human response"

    def test_approval_decision_missing_request_id(self):
        """Test ApprovalDecision rejects missing request_id."""
        from src.shared.models import ApprovalDecision, ApprovalDecisionType

        with pytest.raises(ValidationError) as exc_info:
            ApprovalDecision(decision=ApprovalDecisionType.APPROVED)
        assert "request_id" in str(exc_info.value)

    def test_approval_decision_missing_decision(self):
        """Test ApprovalDecision rejects missing decision field."""
        from src.shared.models import ApprovalDecision

        with pytest.raises(ValidationError) as exc_info:
            ApprovalDecision(request_id="req_abc123")
        assert "decision" in str(exc_info.value)

    def test_approval_decision_invalid_decision_value(self):
        """Test ApprovalDecision rejects invalid decision values."""
        from src.shared.models import ApprovalDecision

        with pytest.raises(ValidationError) as exc_info:
            ApprovalDecision(
                request_id="req_abc123",
                decision="invalid_decision",
            )
        # Error should mention the invalid value or enum type
        error_str = str(exc_info.value).lower()
        assert "decision" in error_str or "invalid" in error_str

    def test_approval_decision_serialization_approved(self):
        """Test ApprovalDecision serialization matches design doc line 679-680."""
        from src.shared.models import ApprovalDecision, ApprovalDecisionType

        decision = ApprovalDecision(
            request_id="req_abc123",
            decision=ApprovalDecisionType.APPROVED,
            feedback=None,
            timestamp="2025-06-15T10:30:00Z",
        )

        data = decision.model_dump()
        assert data == {
            "request_id": "req_abc123",
            "decision": "approved",
            "feedback": None,
            "timestamp": "2025-06-15T10:30:00Z",
        }

    def test_approval_decision_serialization_rejected(self):
        """Test ApprovalDecision serialization matches design doc line 682-683."""
        from src.shared.models import ApprovalDecision, ApprovalDecisionType

        decision = ApprovalDecision(
            request_id="req_abc123",
            decision=ApprovalDecisionType.REJECTED,
            feedback="Budget exceeds limit",
            timestamp="2025-06-15T10:32:00Z",
        )

        data = decision.model_dump()
        assert data == {
            "request_id": "req_abc123",
            "decision": "rejected",
            "feedback": "Budget exceeds limit",
            "timestamp": "2025-06-15T10:32:00Z",
        }


class TestApprovalSchemasImportable:
    """Tests for schema importability from both locations."""

    def test_approval_schemas_importable_from_shared_models(self):
        """Test Approval schemas can be imported from src/shared/models.py."""
        from src.shared.models import ApprovalDecisionType, ApprovalRequest, ApprovalDecision

        # Verify classes exist and are usable
        assert ApprovalDecisionType is not None
        assert ApprovalRequest is not None
        assert ApprovalDecision is not None

    def test_approval_schemas_importable_from_interop_schemas(self):
        """Test Approval schemas can be imported from interoperability/shared/schemas/approval.py."""
        from interoperability.shared.schemas.approval import (
            ApprovalDecisionType,
            ApprovalRequest,
            ApprovalDecision,
        )

        # Verify classes exist and are usable
        assert ApprovalDecisionType is not None
        assert ApprovalRequest is not None
        assert ApprovalDecision is not None

    def test_approval_schemas_importable_from_schemas_package(self):
        """Test Approval schemas can be imported from interoperability.shared.schemas package."""
        from interoperability.shared.schemas import (
            ApprovalDecisionType,
            ApprovalRequest,
            ApprovalDecision,
        )

        # Verify classes exist and are usable
        assert ApprovalDecisionType is not None
        assert ApprovalRequest is not None
        assert ApprovalDecision is not None

    def test_schemas_are_same_class(self):
        """Test that imports from both locations return the same class."""
        from src.shared.models import ApprovalDecisionType as SrcType
        from src.shared.models import ApprovalRequest as SrcRequest
        from src.shared.models import ApprovalDecision as SrcDecision
        from interoperability.shared.schemas.approval import (
            ApprovalDecisionType as InteropType,
            ApprovalRequest as InteropRequest,
            ApprovalDecision as InteropDecision,
        )

        # Should be the exact same class (re-exported, not copied)
        assert SrcType is InteropType
        assert SrcRequest is InteropRequest
        assert SrcDecision is InteropDecision


class TestApprovalSchemaExtraFields:
    """Tests for extra field handling (extra='forbid')."""

    def test_approval_request_rejects_extra_fields(self):
        """Test ApprovalRequest rejects unexpected fields."""
        from src.shared.models import ApprovalRequest, Itinerary

        itinerary = Itinerary(days=[])
        with pytest.raises(ValidationError) as exc_info:
            ApprovalRequest(
                itinerary=itinerary,
                request_id="req_abc123",
                extra_field="not allowed",
            )
        error_str = str(exc_info.value).lower()
        assert "extra_field" in error_str or "extra" in error_str

    def test_approval_decision_rejects_extra_fields(self):
        """Test ApprovalDecision rejects unexpected fields."""
        from src.shared.models import ApprovalDecision, ApprovalDecisionType

        with pytest.raises(ValidationError) as exc_info:
            ApprovalDecision(
                request_id="req_abc123",
                decision=ApprovalDecisionType.APPROVED,
                extra_field="not allowed",
            )
        error_str = str(exc_info.value).lower()
        assert "extra_field" in error_str or "extra" in error_str
