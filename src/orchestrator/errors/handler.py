"""
Comprehensive error handling for the orchestrator.

This module provides:
- Custom exception types for each error scenario
- error_to_response() function to convert exceptions to ErrorResponse
- create_error_response() factory for creating ErrorResponse from error codes

Per design doc "Error Handling Within workflow_turn" and "Error Response Format" sections.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.orchestrator.models.responses import (
    ERROR_CODES,
    ErrorResponse,
    UIAction,
)

if TYPE_CHECKING:
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Custom Exception Types
# ═══════════════════════════════════════════════════════════════════════════════


class OrchestratorError(Exception):
    """Base exception for all orchestrator errors.

    Attributes:
        error_code: Machine-readable error code from ERROR_CODES
        message: Human-readable error message
        details: Additional context for debugging
        retry_action: Suggested retry action
        fallback_actions: Alternative actions
    """

    error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str = "",
        details: dict[str, Any] | None = None,
        retry_action: UIAction | None = None,
        fallback_actions: list[UIAction] | None = None,
    ):
        super().__init__(message)
        self.message = message or self._default_message()
        self.details = details
        self.retry_action = retry_action
        self.fallback_actions = fallback_actions or []

    def _default_message(self) -> str:
        """Get default message from ERROR_CODES."""
        code_info = ERROR_CODES.get(self.error_code, {})
        return code_info.get("description", "An unexpected error occurred")


# ─────────────────────────────────────────────────────────────────────────────
# Event/Input Validation Errors
# ─────────────────────────────────────────────────────────────────────────────


class InvalidEventError(OrchestratorError):
    """Event not valid for current checkpoint.

    Raised when user sends an event type that is not allowed in the
    current workflow phase or checkpoint state.
    """

    error_code = "INVALID_EVENT"


class StaleCheckpointError(OrchestratorError):
    """Event targets outdated checkpoint (multi-tab race).

    Raised when the checkpoint_id in the event doesn't match the current
    checkpoint, typically due to concurrent modifications from another tab.
    """

    error_code = "STALE_CHECKPOINT"


class MissingCheckpointIdError(OrchestratorError):
    """Checkpoint-gated event missing required checkpoint_id.

    Raised when an event that requires checkpoint_id (like approve_checkpoint)
    is received without the checkpoint_id field.
    """

    error_code = "MISSING_CHECKPOINT_ID"


class InvalidInputError(OrchestratorError):
    """Malformed request parameters.

    Raised when request parameters are invalid or malformed.
    """

    error_code = "INVALID_INPUT"


# ─────────────────────────────────────────────────────────────────────────────
# Session Errors
# ─────────────────────────────────────────────────────────────────────────────


class SessionExpiredError(OrchestratorError):
    """Session or consultation not found.

    Raised when the session has expired (TTL) or was never created.
    Not retryable - user must start a new session.
    """

    error_code = "SESSION_EXPIRED"


class SessionLockedError(OrchestratorError):
    """Session being modified by another request.

    Raised when optimistic locking detects concurrent modification,
    typically from another tab or device. Frontend should auto-retry.
    """

    error_code = "SESSION_LOCKED"


# ─────────────────────────────────────────────────────────────────────────────
# Agent Communication Errors
# ─────────────────────────────────────────────────────────────────────────────


class AgentTimeoutError(OrchestratorError):
    """Downstream agent didn't respond within timeout.

    Attributes:
        agent_name: Name of the agent that timed out
        timeout_ms: Timeout duration in milliseconds
    """

    error_code = "AGENT_TIMEOUT"

    def __init__(
        self,
        agent_name: str,
        timeout_ms: int = 30000,
        message: str = "",
        retry_action: UIAction | None = None,
        fallback_actions: list[UIAction] | None = None,
    ):
        self.agent_name = agent_name
        self.timeout_ms = timeout_ms
        super().__init__(
            message=message
            or f"The {agent_name} service is taking too long. Please try again.",
            details={"agent": agent_name, "timeout_ms": timeout_ms},
            retry_action=retry_action,
            fallback_actions=fallback_actions,
        )


class AgentError(OrchestratorError):
    """Downstream agent returned an error.

    Retryability depends on the specific error from the agent.

    Attributes:
        agent_name: Name of the agent that errored
        agent_error: The error message from the agent
    """

    error_code = "AGENT_ERROR"

    def __init__(
        self,
        agent_name: str,
        agent_error: str,
        message: str = "",
        retryable: bool | None = None,
        details: dict[str, Any] | None = None,
        retry_action: UIAction | None = None,
        fallback_actions: list[UIAction] | None = None,
    ):
        self.agent_name = agent_name
        self.agent_error = agent_error
        self.retryable = retryable  # Caller can override
        full_details = {"agent": agent_name, "agent_error": agent_error}
        if details:
            full_details.update(details)
        super().__init__(
            message=message or f"Error from {agent_name}: {agent_error}",
            details=full_details,
            retry_action=retry_action,
            fallback_actions=fallback_actions,
        )


class AgentUnavailableError(OrchestratorError):
    """Downstream agent service is down.

    Raised when connection to an agent fails entirely.

    Attributes:
        agent_name: Name of the unavailable agent
    """

    error_code = "AGENT_UNAVAILABLE"

    def __init__(
        self,
        agent_name: str,
        message: str = "",
        details: dict[str, Any] | None = None,
        retry_action: UIAction | None = None,
        fallback_actions: list[UIAction] | None = None,
    ):
        self.agent_name = agent_name
        full_details = {"agent": agent_name}
        if details:
            full_details.update(details)
        super().__init__(
            message=message or f"The {agent_name} service is currently unavailable.",
            details=full_details,
            retry_action=retry_action,
            fallback_actions=fallback_actions,
        )


@dataclass
class AgentResult:
    """Result from a single agent in parallel discovery."""

    agent_name: str
    success: bool
    error: str | None = None
    data: dict[str, Any] | None = None


class PartialFailureError(OrchestratorError):
    """Some agents succeeded, some failed.

    Raised during parallel discovery when some agents return results
    but others fail. Contains partial results and failure details.

    Attributes:
        succeeded: List of agents that succeeded
        failed: Dict mapping failed agent names to failure reasons
        partial_results: Results from successful agents
    """

    error_code = "PARTIAL_FAILURE"

    def __init__(
        self,
        succeeded: list[str],
        failed: dict[str, str],
        partial_results: dict[str, Any] | None = None,
        message: str = "",
        retry_action: UIAction | None = None,
        fallback_actions: list[UIAction] | None = None,
    ):
        self.succeeded = succeeded
        self.failed = failed
        self.partial_results = partial_results

        if not message:
            succeeded_str = ", ".join(succeeded) if succeeded else "none"
            failed_names = ", ".join(failed.keys()) if failed else "none"
            message = (
                f"Partial results available. Succeeded: {succeeded_str}. "
                f"Failed: {failed_names}."
            )

        super().__init__(
            message=message,
            details={
                "succeeded": succeeded,
                "failed": failed,
                "failure_reasons": failed,
            },
            retry_action=retry_action,
            fallback_actions=fallback_actions,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Storage Errors
# ─────────────────────────────────────────────────────────────────────────────


class StorageError(OrchestratorError):
    """Cosmos DB or storage layer unavailable.

    Raised when storage operations fail due to infrastructure issues.
    """

    error_code = "STORAGE_ERROR"

    def __init__(
        self,
        message: str = "Service temporarily unavailable. Please try again.",
        details: dict[str, Any] | None = None,
        retry_action: UIAction | None = None,
        fallback_actions: list[UIAction] | None = None,
    ):
        super().__init__(
            message=message,
            details=details,
            retry_action=retry_action,
            fallback_actions=fallback_actions,
        )


class ConcurrencyConflictError(OrchestratorError):
    """Optimistic lock failed.

    Raised when etag mismatch occurs during save operation.
    Frontend should refresh and retry.
    """

    error_code = "CONCURRENCY_CONFLICT"

    def __init__(
        self,
        session_id: str | None = None,
        message: str = "Your session was updated elsewhere. Please refresh.",
        details: dict[str, Any] | None = None,
        retry_action: UIAction | None = None,
        fallback_actions: list[UIAction] | None = None,
    ):
        full_details = {}
        if session_id:
            full_details["session_id"] = session_id
        if details:
            full_details.update(details)
        super().__init__(
            message=message,
            details=full_details if full_details else None,
            retry_action=retry_action,
            fallback_actions=fallback_actions,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Rate Limiting
# ─────────────────────────────────────────────────────────────────────────────


class RateLimitedError(OrchestratorError):
    """Too many requests.

    Raised when rate limit is exceeded. Frontend should show wait
    message and auto-retry after delay.

    Attributes:
        retry_after_seconds: Suggested wait time before retry
    """

    error_code = "RATE_LIMITED"

    def __init__(
        self,
        retry_after_seconds: int = 60,
        message: str = "",
        details: dict[str, Any] | None = None,
        retry_action: UIAction | None = None,
        fallback_actions: list[UIAction] | None = None,
    ):
        self.retry_after_seconds = retry_after_seconds
        full_details = {"retry_after_seconds": retry_after_seconds}
        if details:
            full_details.update(details)
        super().__init__(
            message=message or f"Too many requests. Please wait {retry_after_seconds} seconds.",
            details=full_details,
            retry_action=retry_action,
            fallback_actions=fallback_actions,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Booking Errors
# ─────────────────────────────────────────────────────────────────────────────


class BookingError(OrchestratorError):
    """Base class for booking-related errors."""

    error_code = "BOOKING_FAILED"

    def __init__(
        self,
        booking_id: str | None = None,
        message: str = "",
        details: dict[str, Any] | None = None,
        retry_action: UIAction | None = None,
        fallback_actions: list[UIAction] | None = None,
    ):
        self.booking_id = booking_id
        full_details = {}
        if booking_id:
            full_details["booking_id"] = booking_id
        if details:
            full_details.update(details)
        super().__init__(
            message=message or "Booking couldn't be completed",
            details=full_details if full_details else None,
            retry_action=retry_action,
            fallback_actions=fallback_actions,
        )


class BookingUnknownError(BookingError):
    """Booking outcome uncertain (timeout).

    Raised when booking request timed out and we don't know if it succeeded.
    User must check status before proceeding.
    """

    error_code = "BOOKING_UNKNOWN"


class BookingQuoteMismatchError(BookingError):
    """Quote ID doesn't match current quote.

    Raised when the quote_id in the booking request doesn't match
    the quote currently associated with the booking.
    """

    error_code = "BOOKING_QUOTE_MISMATCH"


class BookingQuoteExpiredError(BookingError):
    """Quote has expired, needs refresh.

    Raised when the quote's expiry time has passed.
    """

    error_code = "BOOKING_QUOTE_EXPIRED"

    def __init__(
        self,
        booking_id: str | None = None,
        quote_id: str | None = None,
        expired_at: str | None = None,
        message: str = "Quote has expired. Please get a fresh quote.",
        details: dict[str, Any] | None = None,
        retry_action: UIAction | None = None,
        fallback_actions: list[UIAction] | None = None,
    ):
        full_details = {}
        if quote_id:
            full_details["quote_id"] = quote_id
        if expired_at:
            full_details["expired_at"] = expired_at
        if details:
            full_details.update(details)
        super().__init__(
            booking_id=booking_id,
            message=message,
            details=full_details if full_details else None,
            retry_action=retry_action,
            fallback_actions=fallback_actions,
        )


class BookingPriceChangedError(BookingError):
    """Price changed since quote.

    Raised when the current price differs from the quoted price.
    """

    error_code = "BOOKING_PRICE_CHANGED"

    def __init__(
        self,
        booking_id: str | None = None,
        original_price: dict[str, Any] | None = None,
        new_price: dict[str, Any] | None = None,
        message: str = "",
        details: dict[str, Any] | None = None,
        retry_action: UIAction | None = None,
        fallback_actions: list[UIAction] | None = None,
    ):
        self.original_price = original_price
        self.new_price = new_price
        full_details = {}
        if original_price:
            full_details["original_price"] = original_price
        if new_price:
            full_details["new_price"] = new_price
        if details:
            full_details.update(details)

        if not message and original_price and new_price:
            orig_amt = original_price.get("amount", "?")
            new_amt = new_price.get("amount", "?")
            currency = new_price.get("currency", "")
            message = f"Price changed from {orig_amt} to {new_amt} {currency}"

        super().__init__(
            booking_id=booking_id,
            message=message or "Price has changed since your quote.",
            details=full_details if full_details else None,
            retry_action=retry_action,
            fallback_actions=fallback_actions,
        )


class BookingTermsChangedError(BookingError):
    """Cancellation terms have changed.

    Raised when the terms hash from the quote doesn't match current terms.
    """

    error_code = "BOOKING_TERMS_CHANGED"


class BookingUnavailableError(BookingError):
    """Item no longer available.

    Raised when the item cannot be booked because it's sold out or
    no longer available. Not retryable - user must find alternatives.
    """

    error_code = "BOOKING_UNAVAILABLE"


class BookingPendingReconciliationError(BookingError):
    """Booking has UNKNOWN status, must reconcile first.

    Raised when attempting to book/retry while status is UNKNOWN.
    User must use check_booking_status first.
    """

    error_code = "BOOKING_PENDING_RECONCILIATION"


# ─────────────────────────────────────────────────────────────────────────────
# General Errors
# ─────────────────────────────────────────────────────────────────────────────


class InternalError(OrchestratorError):
    """Unexpected server error.

    Catch-all for unexpected exceptions that don't fit other categories.
    """

    error_code = "INTERNAL_ERROR"


# ═══════════════════════════════════════════════════════════════════════════════
# Error Conversion Functions
# ═══════════════════════════════════════════════════════════════════════════════


def error_to_response(exception: Exception) -> ErrorResponse:
    """Convert an exception to an ErrorResponse.

    This is the main function for converting caught exceptions into
    structured ErrorResponse objects for the frontend.

    Maps exception types to appropriate error codes and populates
    retry_action and fallback_actions based on the error type.

    Args:
        exception: The caught exception to convert

    Returns:
        ErrorResponse with appropriate error code and actions
    """
    # Handle OrchestratorError subclasses
    if isinstance(exception, OrchestratorError):
        return _orchestrator_error_to_response(exception)

    # Handle storage ConflictError from storage modules
    from src.orchestrator.storage import ConflictError, BookingConflictError

    if isinstance(exception, ConflictError):
        return ErrorResponse.from_error_code(
            "CONCURRENCY_CONFLICT",
            message="Your session was updated elsewhere. Please refresh.",
            details={"session_id": str(exception)},
            retry_action=UIAction(
                label="Refresh", event={"type": "status"}
            ),
        )

    if isinstance(exception, BookingConflictError):
        return ErrorResponse.from_error_code(
            "CONCURRENCY_CONFLICT",
            message="Booking was updated elsewhere. Please refresh.",
            details={"booking_id": str(exception)},
            retry_action=UIAction(
                label="Refresh", event={"type": "status"}
            ),
        )

    # Handle A2A client errors
    from src.shared.a2a.client_wrapper import (
        A2AClientError,
        A2AConnectionError,
        A2ATimeoutError,
    )

    if isinstance(exception, A2ATimeoutError):
        return ErrorResponse.from_error_code(
            "AGENT_TIMEOUT",
            message="A service is taking too long. Please try again.",
            retry_action=UIAction(label="Retry", event={"type": "free_text"}),
        )

    if isinstance(exception, A2AConnectionError):
        return ErrorResponse.from_error_code(
            "AGENT_UNAVAILABLE",
            message="A service is currently unavailable.",
            retry_action=UIAction(label="Retry", event={"type": "free_text"}),
        )

    if isinstance(exception, A2AClientError):
        return ErrorResponse.from_error_code(
            "AGENT_ERROR",
            message=str(exception) or "Agent communication error",
            retry_action=UIAction(label="Retry", event={"type": "free_text"}),
        )

    # Handle state_gating InvalidEventError (the one in state_gating module)
    from src.orchestrator.state_gating import (
        InvalidEventError as StateGatingInvalidEventError,
    )

    if isinstance(exception, StateGatingInvalidEventError):
        return ErrorResponse.from_error_code(
            "INVALID_EVENT",
            message=str(exception),
            details={"error_code": exception.error_code} if hasattr(exception, "error_code") else None,
            retry_action=exception.retry_action if hasattr(exception, "retry_action") else UIAction(
                label="Try Again", event={"type": "free_text"}
            ),
        )

    # Handle StateNotFoundError from workflow_turn
    from src.orchestrator.tools.workflow_turn import StateNotFoundError

    if isinstance(exception, StateNotFoundError):
        return ErrorResponse.from_error_code(
            "SESSION_EXPIRED",
            message="Session not found. Please start a new trip plan.",
            fallback_actions=[
                UIAction(label="Start New Plan", event={"type": "start_new"}),
            ],
        )

    # Fallback for unknown exceptions
    return ErrorResponse.from_error_code(
        "INTERNAL_ERROR",
        message="An unexpected error occurred. Please try again.",
        details={"exception_type": type(exception).__name__, "error": str(exception)},
        retry_action=UIAction(label="Try Again", event={"type": "free_text"}),
    )


def _orchestrator_error_to_response(error: OrchestratorError) -> ErrorResponse:
    """Convert an OrchestratorError subclass to ErrorResponse.

    Internal helper that handles the common conversion logic for
    all OrchestratorError subclasses.

    Args:
        error: The OrchestratorError to convert

    Returns:
        ErrorResponse with appropriate error code and actions
    """
    # Get retryable from ERROR_CODES
    code_info = ERROR_CODES.get(error.error_code, {})
    retryable = code_info.get("retryable")

    # Special handling for AgentError which can override retryable
    if isinstance(error, AgentError) and error.retryable is not None:
        retryable = error.retryable

    if retryable is None:
        retryable = True  # Default to retryable

    return ErrorResponse(
        error_code=error.error_code,
        error_message=error.message,
        error_details=error.details,
        retryable=retryable,
        retry_action=error.retry_action,
        fallback_actions=error.fallback_actions,
    )


def create_error_response(
    error_code: str,
    message: str | None = None,
    details: dict[str, Any] | None = None,
    retry_action: UIAction | None = None,
    fallback_actions: list[UIAction] | None = None,
) -> ErrorResponse:
    """Factory function for creating ErrorResponse from error code.

    This is a convenience wrapper around ErrorResponse.from_error_code()
    for cases where you don't have an exception but need to create
    an error response directly.

    Args:
        error_code: Error code from ERROR_CODES
        message: Custom message (overrides default description)
        details: Additional error context
        retry_action: Suggested retry action
        fallback_actions: Alternative actions

    Returns:
        ErrorResponse with appropriate settings
    """
    return ErrorResponse.from_error_code(
        error_code=error_code,
        message=message,
        details=details,
        retry_action=retry_action,
        fallback_actions=fallback_actions,
    )
