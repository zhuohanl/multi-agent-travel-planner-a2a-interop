"""
Tests for orchestrator error handling module.

Tests cover:
- Custom exception types and their attributes
- error_to_response() conversion for all exception types
- create_error_response() factory function
- Retryable/non-retryable classification
- retry_action and fallback_actions population
"""

import pytest

from src.orchestrator.errors import (
    # Base exception
    OrchestratorError,
    # Event/input validation errors
    InvalidEventError,
    StaleCheckpointError,
    MissingCheckpointIdError,
    InvalidInputError,
    # Session errors
    SessionExpiredError,
    SessionLockedError,
    # Agent communication errors
    AgentTimeoutError,
    AgentError,
    AgentUnavailableError,
    AgentResult,
    PartialFailureError,
    # Storage errors
    StorageError,
    ConcurrencyConflictError,
    # Rate limiting
    RateLimitedError,
    # Booking errors
    BookingError,
    BookingUnknownError,
    BookingQuoteMismatchError,
    BookingQuoteExpiredError,
    BookingPriceChangedError,
    BookingTermsChangedError,
    BookingUnavailableError,
    BookingPendingReconciliationError,
    # General errors
    InternalError,
    # Conversion functions
    error_to_response,
    create_error_response,
)
from src.orchestrator.models.responses import ErrorResponse, UIAction


# ═══════════════════════════════════════════════════════════════════════════════
# Exception Type Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestExceptionTypes:
    """Test that exception types have correct error codes and attributes."""

    def test_orchestrator_error_base(self):
        """Test base OrchestratorError."""
        error = OrchestratorError("Test error")
        assert error.message == "Test error"
        assert error.error_code == "INTERNAL_ERROR"
        assert error.details is None
        assert error.retry_action is None
        assert error.fallback_actions == []

    def test_orchestrator_error_with_details(self):
        """Test OrchestratorError with all attributes."""
        retry = UIAction(label="Retry", event={"type": "retry"})
        fallback = UIAction(label="Cancel", event={"type": "cancel"})
        error = OrchestratorError(
            message="Custom message",
            details={"key": "value"},
            retry_action=retry,
            fallback_actions=[fallback],
        )
        assert error.message == "Custom message"
        assert error.details == {"key": "value"}
        assert error.retry_action == retry
        assert error.fallback_actions == [fallback]

    def test_invalid_event_error(self):
        """Test InvalidEventError has correct error code."""
        error = InvalidEventError("Event not valid")
        assert error.error_code == "INVALID_EVENT"
        assert "Event not valid" in str(error)

    def test_stale_checkpoint_error(self):
        """Test StaleCheckpointError has correct error code."""
        error = StaleCheckpointError()
        assert error.error_code == "STALE_CHECKPOINT"

    def test_missing_checkpoint_id_error(self):
        """Test MissingCheckpointIdError has correct error code."""
        error = MissingCheckpointIdError()
        assert error.error_code == "MISSING_CHECKPOINT_ID"

    def test_invalid_input_error(self):
        """Test InvalidInputError has correct error code."""
        error = InvalidInputError("Bad input")
        assert error.error_code == "INVALID_INPUT"

    def test_session_expired_error(self):
        """Test SessionExpiredError has correct error code."""
        error = SessionExpiredError("Session not found")
        assert error.error_code == "SESSION_EXPIRED"

    def test_session_locked_error(self):
        """Test SessionLockedError has correct error code."""
        error = SessionLockedError()
        assert error.error_code == "SESSION_LOCKED"

    def test_agent_timeout_error(self):
        """Test AgentTimeoutError with agent info."""
        error = AgentTimeoutError(agent_name="transport", timeout_ms=30000)
        assert error.error_code == "AGENT_TIMEOUT"
        assert error.agent_name == "transport"
        assert error.timeout_ms == 30000
        assert "transport" in error.message
        assert error.details == {"agent": "transport", "timeout_ms": 30000}

    def test_agent_error(self):
        """Test AgentError with agent info."""
        error = AgentError(
            agent_name="stay",
            agent_error="Connection refused",
            retryable=True,
        )
        assert error.error_code == "AGENT_ERROR"
        assert error.agent_name == "stay"
        assert error.agent_error == "Connection refused"
        assert error.retryable is True
        assert "stay" in error.message

    def test_agent_unavailable_error(self):
        """Test AgentUnavailableError with agent info."""
        error = AgentUnavailableError(agent_name="poi")
        assert error.error_code == "AGENT_UNAVAILABLE"
        assert error.agent_name == "poi"
        assert "poi" in error.message

    def test_partial_failure_error(self):
        """Test PartialFailureError with succeeded/failed lists."""
        error = PartialFailureError(
            succeeded=["stay", "poi"],
            failed={"transport": "timeout", "events": "error"},
            partial_results={"stay": {"hotels": []}},
        )
        assert error.error_code == "PARTIAL_FAILURE"
        assert error.succeeded == ["stay", "poi"]
        assert error.failed == {"transport": "timeout", "events": "error"}
        assert error.partial_results == {"stay": {"hotels": []}}
        assert "stay" in error.message
        assert "transport" in error.message

    def test_storage_error(self):
        """Test StorageError with custom message."""
        error = StorageError(
            message="Database unavailable",
            details={"service": "cosmos_db"},
        )
        assert error.error_code == "STORAGE_ERROR"
        assert "Database unavailable" in error.message
        assert error.details == {"service": "cosmos_db"}

    def test_concurrency_conflict_error(self):
        """Test ConcurrencyConflictError with session_id."""
        error = ConcurrencyConflictError(session_id="sess_123")
        assert error.error_code == "CONCURRENCY_CONFLICT"
        assert error.details == {"session_id": "sess_123"}

    def test_rate_limited_error(self):
        """Test RateLimitedError with retry_after."""
        error = RateLimitedError(retry_after_seconds=60)
        assert error.error_code == "RATE_LIMITED"
        assert error.retry_after_seconds == 60
        assert "60" in error.message

    def test_booking_error(self):
        """Test base BookingError with booking_id."""
        error = BookingError(booking_id="book_123")
        assert error.error_code == "BOOKING_FAILED"
        assert error.booking_id == "book_123"
        assert error.details == {"booking_id": "book_123"}

    def test_booking_unknown_error(self):
        """Test BookingUnknownError has correct code."""
        error = BookingUnknownError(booking_id="book_456")
        assert error.error_code == "BOOKING_UNKNOWN"
        assert error.booking_id == "book_456"

    def test_booking_quote_mismatch_error(self):
        """Test BookingQuoteMismatchError has correct code."""
        error = BookingQuoteMismatchError()
        assert error.error_code == "BOOKING_QUOTE_MISMATCH"

    def test_booking_quote_expired_error(self):
        """Test BookingQuoteExpiredError with quote info."""
        error = BookingQuoteExpiredError(
            booking_id="book_789",
            quote_id="quote_abc",
            expired_at="2025-01-01T12:00:00Z",
        )
        assert error.error_code == "BOOKING_QUOTE_EXPIRED"
        assert error.details["quote_id"] == "quote_abc"
        assert error.details["expired_at"] == "2025-01-01T12:00:00Z"

    def test_booking_price_changed_error(self):
        """Test BookingPriceChangedError with price info."""
        error = BookingPriceChangedError(
            booking_id="book_def",
            original_price={"amount": 100, "currency": "USD"},
            new_price={"amount": 120, "currency": "USD"},
        )
        assert error.error_code == "BOOKING_PRICE_CHANGED"
        assert error.original_price == {"amount": 100, "currency": "USD"}
        assert error.new_price == {"amount": 120, "currency": "USD"}
        assert "100" in error.message
        assert "120" in error.message

    def test_booking_terms_changed_error(self):
        """Test BookingTermsChangedError has correct code."""
        error = BookingTermsChangedError()
        assert error.error_code == "BOOKING_TERMS_CHANGED"

    def test_booking_unavailable_error(self):
        """Test BookingUnavailableError has correct code."""
        error = BookingUnavailableError()
        assert error.error_code == "BOOKING_UNAVAILABLE"

    def test_booking_pending_reconciliation_error(self):
        """Test BookingPendingReconciliationError has correct code."""
        error = BookingPendingReconciliationError(booking_id="book_ghi")
        assert error.error_code == "BOOKING_PENDING_RECONCILIATION"

    def test_internal_error(self):
        """Test InternalError has correct code."""
        error = InternalError("Something broke")
        assert error.error_code == "INTERNAL_ERROR"


# ═══════════════════════════════════════════════════════════════════════════════
# error_to_response() Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestErrorToResponse:
    """Test error_to_response() conversion function."""

    def test_session_expired_error(self):
        """Test SessionExpiredError conversion."""
        error = SessionExpiredError("Session not found")
        response = error_to_response(error)

        assert isinstance(response, ErrorResponse)
        assert response.success is False
        assert response.error_code == "SESSION_EXPIRED"
        assert response.retryable is False
        assert "not found" in response.error_message.lower()

    def test_agent_timeout_error(self):
        """Test AgentTimeoutError conversion."""
        retry = UIAction(label="Retry Flight", event={"type": "retry_agent", "agent": "transport"})
        error = AgentTimeoutError(
            agent_name="transport",
            timeout_ms=30000,
            retry_action=retry,
        )
        response = error_to_response(error)

        assert response.error_code == "AGENT_TIMEOUT"
        assert response.retryable is True
        assert "transport" in response.error_message
        assert response.retry_action is not None
        assert response.retry_action.label == "Retry Flight"
        assert response.error_details["agent"] == "transport"
        assert response.error_details["timeout_ms"] == 30000

    def test_booking_price_changed_error(self):
        """Test BookingPriceChangedError conversion."""
        retry = UIAction(
            label="Book at New Price",
            event={"type": "book_item", "booking": {"booking_id": "book_123"}},
        )
        fallback = UIAction(label="View Options", event={"type": "view_booking_options"})

        error = BookingPriceChangedError(
            booking_id="book_123",
            original_price={"amount": 15000, "currency": "JPY"},
            new_price={"amount": 17500, "currency": "JPY"},
            retry_action=retry,
            fallback_actions=[fallback],
        )
        response = error_to_response(error)

        assert response.error_code == "BOOKING_PRICE_CHANGED"
        assert response.retryable is True
        assert response.error_details["original_price"]["amount"] == 15000
        assert response.error_details["new_price"]["amount"] == 17500
        assert response.retry_action.label == "Book at New Price"
        assert len(response.fallback_actions) == 1

    def test_partial_failure_error(self):
        """Test PartialFailureError conversion."""
        retry = UIAction(label="Retry Transport", event={"type": "retry_agent", "agent": "transport"})
        fallback = UIAction(label="Skip Transport", event={"type": "skip_agent", "agent": "transport"})

        error = PartialFailureError(
            succeeded=["stay", "poi", "events", "dining"],
            failed={"transport": "timeout"},
            retry_action=retry,
            fallback_actions=[fallback],
        )
        response = error_to_response(error)

        assert response.error_code == "PARTIAL_FAILURE"
        # PARTIAL_FAILURE has retryable=None in ERROR_CODES, defaults to True
        assert response.retryable is True
        assert "transport" in str(response.error_details["failed"])
        assert response.retry_action is not None

    def test_retryable_errors_have_retry_action(self):
        """Test that retryable errors can have retry_action."""
        retry = UIAction(label="Try Again", event={"type": "free_text"})
        error = StorageError(
            message="Database temporarily unavailable",
            retry_action=retry,
        )
        response = error_to_response(error)

        assert response.retryable is True
        assert response.retry_action is not None
        assert response.retry_action.label == "Try Again"

    def test_non_retryable_errors_have_fallback_actions(self):
        """Test that non-retryable errors can have fallback_actions."""
        fallback = UIAction(label="Start New Plan", event={"type": "start_new"})
        error = SessionExpiredError(
            message="Your session has expired",
            fallback_actions=[fallback],
        )
        response = error_to_response(error)

        assert response.retryable is False
        assert len(response.fallback_actions) == 1
        assert response.fallback_actions[0].label == "Start New Plan"

    def test_storage_conflict_error_conversion(self):
        """Test storage ConflictError is converted properly."""
        from src.orchestrator.storage import ConflictError

        error = ConflictError("sess_123")
        response = error_to_response(error)

        assert response.error_code == "CONCURRENCY_CONFLICT"
        assert response.retryable is True
        assert "sess_123" in str(response.error_details)

    def test_booking_conflict_error_conversion(self):
        """Test BookingConflictError is converted properly."""
        from src.orchestrator.storage import BookingConflictError

        error = BookingConflictError("book_123")
        response = error_to_response(error)

        assert response.error_code == "CONCURRENCY_CONFLICT"
        assert response.retryable is True
        assert "book_123" in str(response.error_details)

    def test_a2a_timeout_error_conversion(self):
        """Test A2ATimeoutError is converted properly."""
        from src.shared.a2a.client_wrapper import A2ATimeoutError

        error = A2ATimeoutError("Connection timed out")
        response = error_to_response(error)

        assert response.error_code == "AGENT_TIMEOUT"
        assert response.retryable is True
        assert response.retry_action is not None

    def test_a2a_connection_error_conversion(self):
        """Test A2AConnectionError is converted properly."""
        from src.shared.a2a.client_wrapper import A2AConnectionError

        error = A2AConnectionError("Failed to connect")
        response = error_to_response(error)

        assert response.error_code == "AGENT_UNAVAILABLE"
        assert response.retryable is True

    def test_a2a_client_error_conversion(self):
        """Test generic A2AClientError is converted properly."""
        from src.shared.a2a.client_wrapper import A2AClientError

        error = A2AClientError("Unknown A2A error")
        response = error_to_response(error)

        assert response.error_code == "AGENT_ERROR"
        assert response.retryable is True

    def test_state_gating_invalid_event_error_conversion(self):
        """Test state_gating InvalidEventError is converted properly."""
        from src.orchestrator.state_gating import InvalidEventError as StateGatingInvalidEventError

        error = StateGatingInvalidEventError("Event not valid for current phase")
        response = error_to_response(error)

        assert response.error_code == "INVALID_EVENT"
        assert response.retryable is True

    def test_state_not_found_error_conversion(self):
        """Test StateNotFoundError is converted properly."""
        from src.orchestrator.tools.workflow_turn import StateNotFoundError

        error = StateNotFoundError("Session not found")
        response = error_to_response(error)

        assert response.error_code == "SESSION_EXPIRED"
        assert response.retryable is False
        assert len(response.fallback_actions) == 1

    def test_unknown_exception_fallback(self):
        """Test unknown exceptions fall back to INTERNAL_ERROR."""
        error = ValueError("Some unexpected error")
        response = error_to_response(error)

        assert response.error_code == "INTERNAL_ERROR"
        assert response.retryable is True
        assert "ValueError" in str(response.error_details)
        assert response.retry_action is not None

    def test_agent_error_with_overridden_retryable(self):
        """Test AgentError can override retryable status."""
        # Mark as not retryable even though default is retryable
        error = AgentError(
            agent_name="booking",
            agent_error="Payment declined",
            retryable=False,
        )
        response = error_to_response(error)

        assert response.error_code == "AGENT_ERROR"
        assert response.retryable is False


# ═══════════════════════════════════════════════════════════════════════════════
# create_error_response() Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateErrorResponse:
    """Test create_error_response() factory function."""

    def test_create_with_code_only(self):
        """Test creating error response with just error code."""
        response = create_error_response("SESSION_EXPIRED")

        assert isinstance(response, ErrorResponse)
        assert response.success is False
        assert response.error_code == "SESSION_EXPIRED"
        assert response.retryable is False
        # Uses description from ERROR_CODES as message
        assert "Session" in response.error_message or "not found" in response.error_message

    def test_create_with_custom_message(self):
        """Test creating error response with custom message."""
        response = create_error_response(
            "AGENT_TIMEOUT",
            message="The hotel search is taking longer than expected.",
        )

        assert response.error_code == "AGENT_TIMEOUT"
        assert response.error_message == "The hotel search is taking longer than expected."
        assert response.retryable is True

    def test_create_with_details(self):
        """Test creating error response with details."""
        response = create_error_response(
            "STORAGE_ERROR",
            message="Database unavailable",
            details={"service": "cosmos_db", "operation": "upsert"},
        )

        assert response.error_details is not None
        assert response.error_details["service"] == "cosmos_db"
        assert response.error_details["operation"] == "upsert"

    def test_create_with_retry_action(self):
        """Test creating error response with retry_action."""
        retry = UIAction(label="Retry", event={"type": "free_text"})
        response = create_error_response(
            "STORAGE_ERROR",
            retry_action=retry,
        )

        assert response.retry_action is not None
        assert response.retry_action.label == "Retry"

    def test_create_with_fallback_actions(self):
        """Test creating error response with fallback_actions."""
        fallbacks = [
            UIAction(label="Start Over", event={"type": "start_new"}),
            UIAction(label="Cancel", event={"type": "cancel_workflow"}),
        ]
        response = create_error_response(
            "SESSION_EXPIRED",
            fallback_actions=fallbacks,
        )

        assert len(response.fallback_actions) == 2
        assert response.fallback_actions[0].label == "Start Over"

    def test_create_unknown_code_defaults_to_retryable(self):
        """Test unknown error codes default to retryable."""
        response = create_error_response("UNKNOWN_CODE")

        # Unknown codes should default to retryable=True
        assert response.retryable is True
        assert response.error_code == "UNKNOWN_CODE"


# ═══════════════════════════════════════════════════════════════════════════════
# Helper Type Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentResult:
    """Test AgentResult helper dataclass."""

    def test_successful_result(self):
        """Test creating a successful agent result."""
        result = AgentResult(
            agent_name="stay",
            success=True,
            data={"hotels": [{"name": "Hotel A"}]},
        )

        assert result.agent_name == "stay"
        assert result.success is True
        assert result.error is None
        assert result.data == {"hotels": [{"name": "Hotel A"}]}

    def test_failed_result(self):
        """Test creating a failed agent result."""
        result = AgentResult(
            agent_name="transport",
            success=False,
            error="Connection timeout",
        )

        assert result.agent_name == "transport"
        assert result.success is False
        assert result.error == "Connection timeout"
        assert result.data is None


# ═══════════════════════════════════════════════════════════════════════════════
# Serialization Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestErrorResponseSerialization:
    """Test that error responses serialize correctly."""

    def test_error_response_to_dict(self):
        """Test ErrorResponse.to_dict() includes all fields."""
        retry = UIAction(label="Retry", event={"type": "retry"})
        fallback = UIAction(label="Cancel", event={"type": "cancel"})

        error = AgentTimeoutError(
            agent_name="transport",
            timeout_ms=30000,
            retry_action=retry,
            fallback_actions=[fallback],
        )
        response = error_to_response(error)
        data = response.to_dict()

        assert data["success"] is False
        assert data["error_code"] == "AGENT_TIMEOUT"
        assert data["retryable"] is True
        assert "error_message" in data
        assert "error_details" in data
        assert data["retry_action"]["label"] == "Retry"
        assert len(data["fallback_actions"]) == 1

    def test_minimal_error_response_to_dict(self):
        """Test minimal ErrorResponse.to_dict() omits None values."""
        response = create_error_response("INTERNAL_ERROR", message="Error")
        data = response.to_dict()

        assert "success" in data
        assert "error_code" in data
        assert "error_message" in data
        assert "retryable" in data
        # These should NOT be in the dict since they're None/empty
        assert "error_details" not in data or data["error_details"] is None
        assert "retry_action" not in data or data["retry_action"] is None
        assert "fallback_actions" not in data or data["fallback_actions"] == []
