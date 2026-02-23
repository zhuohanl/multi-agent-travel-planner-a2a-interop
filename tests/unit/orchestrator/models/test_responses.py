"""
Unit tests for response models.

Tests cover:
- UIAction creation and serialization
- UIDirective with actions and display types
- ToolResponse success responses
- ErrorResponse with retryable/non-retryable errors
- Error code validation
"""

import pytest

from src.orchestrator.models.responses import (
    ERROR_CODES,
    VALID_ERROR_CODES,
    ErrorResponse,
    ToolResponse,
    UIAction,
    UIDirective,
    get_error_code_info,
    is_valid_error_code,
)


# ═══════════════════════════════════════════════════════════════════════════════
# UIAction Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestUIAction:
    """Tests for UIAction dataclass."""

    def test_ui_action_creation(self):
        """Test basic UIAction creation."""
        action = UIAction(
            label="Approve",
            event={"type": "approve_checkpoint", "checkpoint_id": "itinerary_approval"}
        )

        assert action.label == "Approve"
        assert action.event["type"] == "approve_checkpoint"
        assert action.event["checkpoint_id"] == "itinerary_approval"

    def test_ui_action_to_dict(self):
        """Test UIAction serialization."""
        action = UIAction(
            label="Retry",
            event={"type": "retry_agent", "agent": "transport"}
        )

        result = action.to_dict()

        assert result == {
            "label": "Retry",
            "event": {"type": "retry_agent", "agent": "transport"},
        }

    def test_ui_action_from_dict(self):
        """Test UIAction deserialization."""
        data = {
            "label": "Start New",
            "event": {"type": "start_new"},
        }

        action = UIAction.from_dict(data)

        assert action.label == "Start New"
        assert action.event == {"type": "start_new"}

    def test_ui_action_from_dict_with_missing_fields(self):
        """Test UIAction deserialization handles missing fields."""
        action = UIAction.from_dict({})

        assert action.label == ""
        assert action.event == {}


# ═══════════════════════════════════════════════════════════════════════════════
# UIDirective Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestUIDirective:
    """Tests for UIDirective dataclass."""

    def test_ui_directive_default_values(self):
        """Test UIDirective defaults."""
        directive = UIDirective()

        assert directive.actions == []
        assert directive.display_type == "text"
        assert directive.text_input is True

    def test_ui_directive_with_actions(self):
        """Test UIDirective with actions list."""
        actions = [
            UIAction(label="Approve", event={"type": "approve_checkpoint"}),
            UIAction(label="Cancel", event={"type": "cancel_workflow"}),
        ]

        directive = UIDirective(actions=actions, display_type="itinerary")

        assert len(directive.actions) == 2
        assert directive.display_type == "itinerary"

    def test_ui_directive_to_dict(self):
        """Test UIDirective serialization."""
        directive = UIDirective(
            actions=[
                UIAction(label="Book", event={"type": "book_item", "booking_id": "123"}),
            ],
            display_type="booking_options",
            text_input=False,
        )

        result = directive.to_dict()

        assert result["actions"] == [
            {"label": "Book", "event": {"type": "book_item", "booking_id": "123"}}
        ]
        assert result["display_type"] == "booking_options"
        assert result["text_input"] is False

    def test_ui_directive_to_dict_minimal(self):
        """Test UIDirective serialization omits defaults."""
        directive = UIDirective()  # All defaults

        result = directive.to_dict()

        # Empty dict when all defaults
        assert result == {}

    def test_ui_directive_to_dict_with_default_display_type(self):
        """Test UIDirective doesn't include display_type if 'text'."""
        directive = UIDirective(
            actions=[UIAction(label="OK", event={"type": "ok"})],
            display_type="text",
        )

        result = directive.to_dict()

        assert "display_type" not in result
        assert "actions" in result

    def test_ui_directive_from_dict(self):
        """Test UIDirective deserialization."""
        data = {
            "actions": [
                {"label": "Retry", "event": {"type": "retry"}},
            ],
            "display_type": "error",
            "text_input": False,
        }

        directive = UIDirective.from_dict(data)

        assert len(directive.actions) == 1
        assert directive.actions[0].label == "Retry"
        assert directive.display_type == "error"
        assert directive.text_input is False

    def test_ui_directive_from_dict_with_defaults(self):
        """Test UIDirective deserialization with missing fields uses defaults."""
        directive = UIDirective.from_dict({})

        assert directive.actions == []
        assert directive.display_type == "text"
        assert directive.text_input is True


# ═══════════════════════════════════════════════════════════════════════════════
# ToolResponse Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolResponse:
    """Tests for ToolResponse dataclass."""

    def test_tool_response_creation(self):
        """Test basic ToolResponse creation."""
        response = ToolResponse(
            success=True,
            message="Operation completed successfully",
            data={"booking_id": "book_123"},
        )

        assert response.success is True
        assert response.message == "Operation completed successfully"
        assert response.data == {"booking_id": "book_123"}
        assert response.ui is None

    def test_tool_response_with_ui_directive(self):
        """Test ToolResponse with UI directive."""
        ui = UIDirective(
            display_type="itinerary",
            actions=[UIAction(label="Approve", event={"type": "approve"})],
        )

        response = ToolResponse(
            success=True,
            message="Here's your itinerary",
            data={"itinerary": {"days": 7}},
            ui=ui,
        )

        assert response.ui is not None
        assert response.ui.display_type == "itinerary"
        assert len(response.ui.actions) == 1

    def test_tool_response_to_dict(self):
        """Test ToolResponse serialization."""
        response = ToolResponse(
            success=True,
            message="Booking confirmed",
            data={"booking_id": "book_xyz", "status": "BOOKED"},
            ui=UIDirective(actions=[
                UIAction(label="View All", event={"type": "view_booking_options"})
            ]),
        )

        result = response.to_dict()

        assert result["success"] is True
        assert result["message"] == "Booking confirmed"
        assert result["data"]["booking_id"] == "book_xyz"
        assert "ui" in result
        assert len(result["ui"]["actions"]) == 1

    def test_tool_response_to_dict_minimal(self):
        """Test ToolResponse serialization without optional fields."""
        response = ToolResponse(
            success=True,
            message="OK",
        )

        result = response.to_dict()

        assert result == {"success": True, "message": "OK"}
        assert "data" not in result
        assert "ui" not in result

    def test_tool_response_to_dict_excludes_empty_ui(self):
        """Test ToolResponse doesn't include empty UI dict."""
        response = ToolResponse(
            success=True,
            message="OK",
            ui=UIDirective(),  # Empty directive
        )

        result = response.to_dict()

        # Empty UIDirective.to_dict() returns {} which is excluded
        assert "ui" not in result

    def test_tool_response_from_dict(self):
        """Test ToolResponse deserialization."""
        data = {
            "success": True,
            "message": "Success",
            "data": {"key": "value"},
            "ui": {
                "display_type": "text",
                "actions": [{"label": "OK", "event": {"type": "ok"}}],
            },
        }

        response = ToolResponse.from_dict(data)

        assert response.success is True
        assert response.message == "Success"
        assert response.data == {"key": "value"}
        assert response.ui is not None
        assert len(response.ui.actions) == 1

    def test_tool_response_from_dict_minimal(self):
        """Test ToolResponse deserialization with minimal data."""
        response = ToolResponse.from_dict({})

        assert response.success is True  # Default
        assert response.message == ""
        assert response.data is None
        assert response.ui is None


# ═══════════════════════════════════════════════════════════════════════════════
# ErrorResponse Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestErrorResponse:
    """Tests for ErrorResponse dataclass."""

    def test_error_response_retryable(self):
        """Test ErrorResponse for retryable errors."""
        retry_action = UIAction(
            label="Retry Flight Search",
            event={"type": "retry_agent", "agent": "transport"}
        )

        response = ErrorResponse(
            error_code="AGENT_TIMEOUT",
            error_message="The flight search is taking longer than expected.",
            error_details={"agent": "transport", "timeout_ms": 30000},
            retryable=True,
            retry_action=retry_action,
        )

        assert response.success is False
        assert response.error_code == "AGENT_TIMEOUT"
        assert response.retryable is True
        assert response.retry_action is not None
        assert response.retry_action.label == "Retry Flight Search"

    def test_error_response_not_retryable(self):
        """Test ErrorResponse for non-retryable errors."""
        response = ErrorResponse(
            error_code="SESSION_EXPIRED",
            error_message="Your planning session has expired.",
            retryable=False,
            fallback_actions=[
                UIAction(label="Start New Plan", event={"type": "start_new"})
            ],
        )

        assert response.success is False
        assert response.error_code == "SESSION_EXPIRED"
        assert response.retryable is False
        assert response.retry_action is None
        assert len(response.fallback_actions) == 1

    def test_error_response_success_always_false(self):
        """Test that ErrorResponse.success is always False."""
        response = ErrorResponse(
            error_code="INTERNAL_ERROR",
            error_message="Something went wrong",
        )

        # Even though success isn't specified, it should be False
        assert response.success is False

    def test_error_response_to_dict(self):
        """Test ErrorResponse serialization."""
        response = ErrorResponse(
            error_code="BOOKING_PRICE_CHANGED",
            error_message="Price changed from ¥15,000 to ¥17,500/night.",
            error_details={
                "booking_id": "book_xyz",
                "original_price": 15000,
                "new_price": 17500,
            },
            retryable=True,
            retry_action=UIAction(
                label="Book at New Price",
                event={"type": "book_item", "booking_id": "book_xyz"}
            ),
            fallback_actions=[
                UIAction(label="View Other Options", event={"type": "view_booking_options"}),
            ],
        )

        result = response.to_dict()

        assert result["success"] is False
        assert result["error_code"] == "BOOKING_PRICE_CHANGED"
        assert result["error_message"] == "Price changed from ¥15,000 to ¥17,500/night."
        assert result["error_details"]["booking_id"] == "book_xyz"
        assert result["retryable"] is True
        assert result["retry_action"]["label"] == "Book at New Price"
        assert len(result["fallback_actions"]) == 1

    def test_error_response_to_dict_minimal(self):
        """Test ErrorResponse serialization without optional fields."""
        response = ErrorResponse(
            error_code="INTERNAL_ERROR",
            error_message="Error occurred",
        )

        result = response.to_dict()

        assert result["success"] is False
        assert result["error_code"] == "INTERNAL_ERROR"
        assert result["error_message"] == "Error occurred"
        assert result["retryable"] is True  # Default
        assert "error_details" not in result
        assert "retry_action" not in result
        assert "fallback_actions" not in result

    def test_error_response_from_dict(self):
        """Test ErrorResponse deserialization."""
        data = {
            "success": False,
            "error_code": "STORAGE_ERROR",
            "error_message": "Database unavailable",
            "error_details": {"service": "cosmos_db"},
            "retryable": True,
            "retry_action": {"label": "Try Again", "event": {"type": "retry"}},
            "fallback_actions": [],
        }

        response = ErrorResponse.from_dict(data)

        assert response.success is False
        assert response.error_code == "STORAGE_ERROR"
        assert response.error_message == "Database unavailable"
        assert response.error_details == {"service": "cosmos_db"}
        assert response.retryable is True
        assert response.retry_action is not None
        assert response.retry_action.label == "Try Again"

    def test_error_response_from_dict_minimal(self):
        """Test ErrorResponse deserialization with minimal data."""
        response = ErrorResponse.from_dict({})

        assert response.success is False
        assert response.error_code == ""
        assert response.error_message == ""
        assert response.retryable is True  # Default
        assert response.retry_action is None
        assert response.fallback_actions == []

    def test_error_response_from_error_code(self):
        """Test ErrorResponse factory method from error code."""
        response = ErrorResponse.from_error_code(
            "AGENT_TIMEOUT",
            details={"agent": "transport"},
            retry_action=UIAction(label="Retry", event={"type": "retry"}),
        )

        # Should use default description from ERROR_CODES
        assert response.error_code == "AGENT_TIMEOUT"
        assert "didn't respond" in response.error_message.lower()
        assert response.retryable is True  # From ERROR_CODES
        assert response.retry_action is not None

    def test_error_response_from_error_code_custom_message(self):
        """Test ErrorResponse factory with custom message."""
        response = ErrorResponse.from_error_code(
            "SESSION_EXPIRED",
            message="Your session has timed out. Please start over.",
        )

        # Should use custom message
        assert response.error_message == "Your session has timed out. Please start over."
        assert response.retryable is False  # From ERROR_CODES

    def test_error_response_from_error_code_unknown(self):
        """Test ErrorResponse factory with unknown error code."""
        response = ErrorResponse.from_error_code("UNKNOWN_CODE")

        assert response.error_code == "UNKNOWN_CODE"
        assert response.error_message == "An error occurred"  # Fallback
        assert response.retryable is True  # Default


# ═══════════════════════════════════════════════════════════════════════════════
# Error Code Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestErrorCodes:
    """Tests for error code utilities."""

    def test_all_error_codes_defined(self):
        """Test that all expected error codes from design doc are defined."""
        expected_codes = [
            "INVALID_EVENT",
            "STALE_CHECKPOINT",
            "MISSING_CHECKPOINT_ID",
            "INVALID_INPUT",
            "SESSION_EXPIRED",
            "SESSION_LOCKED",
            "AGENT_TIMEOUT",
            "AGENT_ERROR",
            "AGENT_UNAVAILABLE",
            "PARTIAL_FAILURE",
            "STORAGE_ERROR",
            "CONCURRENCY_CONFLICT",
            "RATE_LIMITED",
            "BOOKING_FAILED",
            "BOOKING_UNKNOWN",
            "BOOKING_QUOTE_MISMATCH",
            "BOOKING_QUOTE_EXPIRED",
            "BOOKING_PRICE_CHANGED",
            "BOOKING_TERMS_CHANGED",
            "BOOKING_UNAVAILABLE",
            "INTERNAL_ERROR",
        ]

        for code in expected_codes:
            assert code in ERROR_CODES, f"Missing error code: {code}"

    def test_error_codes_have_required_fields(self):
        """Test that all error codes have required metadata."""
        for code, info in ERROR_CODES.items():
            assert "description" in info, f"{code} missing description"
            assert "retryable" in info, f"{code} missing retryable"
            assert "frontend_behavior" in info, f"{code} missing frontend_behavior"

    def test_is_valid_error_code_true(self):
        """Test is_valid_error_code returns True for valid codes."""
        assert is_valid_error_code("INVALID_EVENT") is True
        assert is_valid_error_code("SESSION_EXPIRED") is True
        assert is_valid_error_code("BOOKING_FAILED") is True

    def test_is_valid_error_code_false(self):
        """Test is_valid_error_code returns False for invalid codes."""
        assert is_valid_error_code("FAKE_ERROR") is False
        assert is_valid_error_code("") is False
        assert is_valid_error_code("invalid_event") is False  # Case-sensitive

    def test_get_error_code_info_valid(self):
        """Test get_error_code_info returns info for valid codes."""
        info = get_error_code_info("AGENT_TIMEOUT")

        assert info is not None
        assert info["description"] == "Downstream agent didn't respond"
        assert info["retryable"] is True

    def test_get_error_code_info_invalid(self):
        """Test get_error_code_info returns None for invalid codes."""
        info = get_error_code_info("NOT_A_REAL_CODE")
        assert info is None

    def test_valid_error_codes_set(self):
        """Test VALID_ERROR_CODES is a proper set of all codes."""
        assert isinstance(VALID_ERROR_CODES, set)
        assert len(VALID_ERROR_CODES) == len(ERROR_CODES)
        assert VALID_ERROR_CODES == set(ERROR_CODES.keys())


# ═══════════════════════════════════════════════════════════════════════════════
# Integration / Edge Case Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestResponseIntegration:
    """Integration tests for response models."""

    def test_complex_itinerary_response(self):
        """Test a complex itinerary approval response structure."""
        response = ToolResponse(
            success=True,
            message="Here's your 7-day Tokyo itinerary...",
            data={"itinerary": {"days": 7, "total_budget": 2500}},
            ui=UIDirective(
                display_type="itinerary",
                actions=[
                    UIAction(
                        label="Approve & Book",
                        event={"type": "approve_checkpoint", "checkpoint_id": "itinerary_approval"}
                    ),
                    UIAction(
                        label="Change Hotel",
                        event={"type": "request_change", "change_request": "hotel"}
                    ),
                    UIAction(
                        label="Start Over",
                        event={"type": "cancel_workflow"}
                    ),
                ],
            ),
        )

        result = response.to_dict()

        assert result["success"] is True
        assert result["ui"]["display_type"] == "itinerary"
        assert len(result["ui"]["actions"]) == 3
        assert result["ui"]["actions"][0]["event"]["type"] == "approve_checkpoint"

    def test_partial_failure_error_response(self):
        """Test partial failure error response structure."""
        response = ErrorResponse(
            error_code="PARTIAL_FAILURE",
            error_message="We found hotels and attractions, but couldn't search for flights.",
            error_details={
                "succeeded": ["stay", "poi", "events", "dining"],
                "failed": ["transport"],
                "failure_reason": {"transport": "timeout"},
            },
            retryable=True,
            retry_action=UIAction(
                label="Retry Flight Search",
                event={"type": "retry_agent", "agent": "transport"}
            ),
            fallback_actions=[
                UIAction(
                    label="Continue Without Flights",
                    event={"type": "skip_agent", "agent": "transport"}
                ),
                UIAction(
                    label="Retry All",
                    event={"type": "retry_discovery"}
                ),
            ],
        )

        result = response.to_dict()

        assert result["error_code"] == "PARTIAL_FAILURE"
        assert result["error_details"]["succeeded"] == ["stay", "poi", "events", "dining"]
        assert result["error_details"]["failed"] == ["transport"]
        assert result["retry_action"]["label"] == "Retry Flight Search"
        assert len(result["fallback_actions"]) == 2

    def test_roundtrip_serialization_tool_response(self):
        """Test ToolResponse can be serialized and deserialized."""
        original = ToolResponse(
            success=True,
            message="Test message",
            data={"key": "value", "nested": {"a": 1}},
            ui=UIDirective(
                display_type="custom",
                actions=[UIAction(label="Action", event={"type": "action"})],
                text_input=False,
            ),
        )

        serialized = original.to_dict()
        restored = ToolResponse.from_dict(serialized)

        assert restored.success == original.success
        assert restored.message == original.message
        assert restored.data == original.data
        assert restored.ui.display_type == original.ui.display_type
        assert len(restored.ui.actions) == len(original.ui.actions)
        assert restored.ui.text_input == original.ui.text_input

    def test_roundtrip_serialization_error_response(self):
        """Test ErrorResponse can be serialized and deserialized."""
        original = ErrorResponse(
            error_code="BOOKING_QUOTE_EXPIRED",
            error_message="Quote has expired",
            error_details={"quote_id": "quote_123", "expired_at": "2024-01-01T00:00:00Z"},
            retryable=True,
            retry_action=UIAction(label="Refresh Quote", event={"type": "refresh_quote"}),
            fallback_actions=[
                UIAction(label="Cancel", event={"type": "cancel"}),
            ],
        )

        serialized = original.to_dict()
        restored = ErrorResponse.from_dict(serialized)

        assert restored.success is False  # Always false
        assert restored.error_code == original.error_code
        assert restored.error_message == original.error_message
        assert restored.error_details == original.error_details
        assert restored.retryable == original.retryable
        assert restored.retry_action.label == original.retry_action.label
        assert len(restored.fallback_actions) == len(original.fallback_actions)
