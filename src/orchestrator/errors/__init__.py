"""
Orchestrator error handling module.

Provides custom exception types and error conversion utilities for
consistent error handling across the orchestrator.

Exports:
    Exception Types:
        - OrchestratorError: Base exception for all orchestrator errors
        - InvalidEventError: Event not valid for current checkpoint
        - StaleCheckpointError: Event targets outdated checkpoint
        - MissingCheckpointIdError: Checkpoint-gated event missing checkpoint_id
        - InvalidInputError: Malformed request parameters
        - SessionExpiredError: Session/consultation not found
        - SessionLockedError: Session being modified by another request
        - AgentTimeoutError: Downstream agent didn't respond
        - AgentError: Downstream agent returned error
        - AgentUnavailableError: Downstream agent service is down
        - PartialFailureError: Some agents succeeded, some failed
        - StorageError: Cosmos DB unavailable
        - ConcurrencyConflictError: Optimistic lock failed
        - RateLimitedError: Too many requests
        - BookingError: Base class for booking errors
        - BookingUnknownError: Booking outcome uncertain
        - BookingQuoteMismatchError: Quote ID doesn't match
        - BookingQuoteExpiredError: Quote has expired
        - BookingPriceChangedError: Price changed since quote
        - BookingTermsChangedError: Terms have changed
        - BookingUnavailableError: Item no longer available
        - BookingPendingReconciliationError: Must reconcile first
        - InternalError: Unexpected server error

    Functions:
        - error_to_response: Convert exceptions to ErrorResponse
        - create_error_response: Create ErrorResponse from error code

    Helper Types:
        - AgentResult: Result from a single agent in parallel discovery
"""

from .handler import (
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

__all__ = [
    # Base exception
    "OrchestratorError",
    # Event/input validation errors
    "InvalidEventError",
    "StaleCheckpointError",
    "MissingCheckpointIdError",
    "InvalidInputError",
    # Session errors
    "SessionExpiredError",
    "SessionLockedError",
    # Agent communication errors
    "AgentTimeoutError",
    "AgentError",
    "AgentUnavailableError",
    "AgentResult",
    "PartialFailureError",
    # Storage errors
    "StorageError",
    "ConcurrencyConflictError",
    # Rate limiting
    "RateLimitedError",
    # Booking errors
    "BookingError",
    "BookingUnknownError",
    "BookingQuoteMismatchError",
    "BookingQuoteExpiredError",
    "BookingPriceChangedError",
    "BookingTermsChangedError",
    "BookingUnavailableError",
    "BookingPendingReconciliationError",
    # General errors
    "InternalError",
    # Conversion functions
    "error_to_response",
    "create_error_response",
]
