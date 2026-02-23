"""
Response models for orchestrator tool outputs.

All orchestrator tools return responses using these standard envelopes:
- ToolResponse: For successful operations
- ErrorResponse: For failures with structured error information

Per design doc Response Formats section.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════════
# Error Code Catalog
# ═══════════════════════════════════════════════════════════════════════════════

# All error codes defined per design doc Response Formats section
ERROR_CODES: dict[str, dict[str, Any]] = {
    # Event and input validation errors
    "INVALID_EVENT": {
        "description": "Event not valid for current checkpoint",
        "retryable": True,
        "frontend_behavior": "Show error, offer valid actions",
    },
    "STALE_CHECKPOINT": {
        "description": "Event targets outdated checkpoint (multi-tab race)",
        "retryable": True,
        "frontend_behavior": "Show 'Refresh' button to get current state",
    },
    "MISSING_CHECKPOINT_ID": {
        "description": "Checkpoint-gated event missing required checkpoint_id",
        "retryable": True,
        "frontend_behavior": "Re-fetch UI with proper checkpoint_id",
    },
    "INVALID_INPUT": {
        "description": "Malformed request parameters",
        "retryable": True,
        "frontend_behavior": "Show error, let user correct",
    },
    # Session errors
    "SESSION_EXPIRED": {
        "description": "Session/consultation not found",
        "retryable": False,
        "frontend_behavior": "Prompt to start new session",
    },
    "SESSION_LOCKED": {
        "description": "Session being modified by another request",
        "retryable": True,
        "frontend_behavior": "Auto-retry after delay",
    },
    # Agent errors
    "AGENT_TIMEOUT": {
        "description": "Downstream agent didn't respond",
        "retryable": True,
        "frontend_behavior": "Show retry button",
    },
    "AGENT_ERROR": {
        "description": "Downstream agent returned error",
        "retryable": None,  # "Maybe" - depends on specific error
        "frontend_behavior": "Show error with agent-specific guidance",
    },
    "AGENT_UNAVAILABLE": {
        "description": "Downstream agent service is down",
        "retryable": True,
        "frontend_behavior": "Retry with backoff",
    },
    "PARTIAL_FAILURE": {
        "description": "Some agents succeeded, some failed",
        "retryable": None,  # N/A - partial results available
        "frontend_behavior": "Show partial results with retry options",
    },
    # Storage errors
    "STORAGE_ERROR": {
        "description": "Cosmos DB unavailable",
        "retryable": True,
        "frontend_behavior": "Generic retry message",
    },
    "CONCURRENCY_CONFLICT": {
        "description": "Optimistic lock failed",
        "retryable": True,
        "frontend_behavior": "Refresh and retry",
    },
    # Rate limiting
    "RATE_LIMITED": {
        "description": "Too many requests",
        "retryable": True,
        "frontend_behavior": "Show wait message, auto-retry",
    },
    # Booking-specific errors
    "BOOKING_FAILED": {
        "description": "Booking couldn't be completed",
        "retryable": None,  # Depends on specific failure
        "frontend_behavior": "Show reason and options",
    },
    "BOOKING_UNKNOWN": {
        "description": "Booking outcome uncertain (timeout)",
        "retryable": True,
        "frontend_behavior": "Show 'Check Status' button, trigger reconciliation",
    },
    "BOOKING_QUOTE_MISMATCH": {
        "description": "Quote ID doesn't match current quote",
        "retryable": True,
        "frontend_behavior": "Show current quote, ask to confirm",
    },
    "BOOKING_QUOTE_EXPIRED": {
        "description": "Quote has expired, needs refresh",
        "retryable": True,
        "frontend_behavior": "Show refreshed quote, ask to confirm",
    },
    "BOOKING_PRICE_CHANGED": {
        "description": "Price changed since quote",
        "retryable": True,
        "frontend_behavior": "Show new price, ask to confirm",
    },
    "BOOKING_TERMS_CHANGED": {
        "description": "Cancellation terms have changed",
        "retryable": True,
        "frontend_behavior": "Show new terms, ask to confirm",
    },
    "BOOKING_UNAVAILABLE": {
        "description": "Item no longer available",
        "retryable": False,
        "frontend_behavior": "Offer alternatives",
    },
    "BOOKING_PENDING_RECONCILIATION": {
        "description": "Booking has UNKNOWN status, must reconcile first",
        "retryable": True,
        "frontend_behavior": "Show 'Check Status' button only",
    },
    # General errors
    "INTERNAL_ERROR": {
        "description": "Unexpected server error",
        "retryable": True,
        "frontend_behavior": "Generic error message",
    },
}

# Export just the error code names for easy validation
VALID_ERROR_CODES: set[str] = set(ERROR_CODES.keys())


# ═══════════════════════════════════════════════════════════════════════════════
# UI Components
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class UIAction:
    """
    Represents a single action button for the frontend.

    Per design doc, UIAction contains:
    - label: Button text shown to user
    - event: Structured event dict to send back when clicked

    Example:
        UIAction(
            label="Approve & Book",
            event={"type": "approve_checkpoint", "checkpoint_id": "itinerary_approval"}
        )
    """

    label: str
    event: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "label": self.label,
            "event": self.event,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UIAction":
        """Create UIAction from dictionary."""
        return cls(
            label=data.get("label", ""),
            event=data.get("event", {}),
        )


@dataclass
class UIDirective:
    """
    Contains UI hints for the frontend to render appropriate components.

    Per design doc, UIDirective contains:
    - actions: List of UIAction buttons to display
    - display_type: Hint for how to render content ("text", "itinerary", "booking_options", etc.)
    - text_input: Whether to show a text input field (default True)

    Example:
        UIDirective(
            display_type="itinerary",
            actions=[
                UIAction(label="Approve", event={"type": "approve_checkpoint", ...}),
                UIAction(label="Start Over", event={"type": "cancel_workflow"}),
            ]
        )
    """

    actions: list[UIAction] = field(default_factory=list)
    display_type: str = "text"
    text_input: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {}

        if self.actions:
            result["actions"] = [action.to_dict() for action in self.actions]

        if self.display_type != "text":
            result["display_type"] = self.display_type

        if not self.text_input:
            result["text_input"] = False

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UIDirective":
        """Create UIDirective from dictionary."""
        actions = [
            UIAction.from_dict(a) for a in data.get("actions", [])
        ]
        return cls(
            actions=actions,
            display_type=data.get("display_type", "text"),
            text_input=data.get("text_input", True),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Response Envelopes
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ToolResponse:
    """
    Standard response envelope for all successful orchestrator tool operations.

    Per design doc Response Formats section, all tools return a consistent structure:
    - success: Always True for ToolResponse
    - message: Human-readable message for the user (always present)
    - data: Tool-specific result data (optional)
    - ui: UI hints for frontend (optional)

    Common data fields by tool type:
    - Clarification: {"trip_spec": TripSpec, "checkpoint": "trip_spec_approval"}
    - Discovery: {"job_id": str, "stream_url": str}
    - Booking: {"booking_id": str, "status": str, "confirmation": dict}
    - Question: {"domain": str | None}

    Example:
        ToolResponse(
            success=True,
            message="Here's your 7-day Tokyo itinerary...",
            data={"itinerary": {...}},
            ui=UIDirective(
                display_type="itinerary",
                actions=[UIAction(label="Approve & Book", event={...})]
            )
        )
    """

    success: bool = True
    message: str = ""
    data: dict[str, Any] | None = None
    ui: UIDirective | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "success": self.success,
            "message": self.message,
        }

        if self.data is not None:
            result["data"] = self.data

        if self.ui is not None:
            ui_dict = self.ui.to_dict()
            if ui_dict:  # Only include if not empty
                result["ui"] = ui_dict

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolResponse":
        """Create ToolResponse from dictionary."""
        ui = None
        if "ui" in data and data["ui"]:
            ui = UIDirective.from_dict(data["ui"])

        return cls(
            success=data.get("success", True),
            message=data.get("message", ""),
            data=data.get("data"),
            ui=ui,
        )


@dataclass
class ErrorResponse:
    """
    Standardized error response for all failure scenarios.

    Per design doc Response Formats section, ErrorResponse distinguishes between:
    - Retryable failures (show retry button)
    - User errors (show correction guidance)
    - Fatal errors (redirect to start)

    Attributes:
        success: Always False for errors
        error_code: Machine-readable error code (from ERROR_CODES)
        error_message: Human-readable message for display
        error_details: Additional context for debugging/logging
        retryable: Whether the user can retry this action
        retry_action: Suggested retry action (button to show)
        fallback_actions: Alternative actions if retry won't help

    Example:
        ErrorResponse(
            error_code="AGENT_TIMEOUT",
            error_message="The flight search is taking longer than expected.",
            retryable=True,
            retry_action=UIAction(label="Retry", event={"type": "retry_agent", "agent": "transport"}),
            fallback_actions=[
                UIAction(label="Skip Flights", event={"type": "skip_agent", "agent": "transport"}),
            ]
        )
    """

    success: bool = field(default=False, init=False)  # Always False for errors
    error_code: str = ""
    error_message: str = ""
    error_details: dict[str, Any] | None = None
    retryable: bool = True
    retry_action: UIAction | None = None
    fallback_actions: list[UIAction] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Ensure success is always False."""
        object.__setattr__(self, "success", False)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "success": False,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "retryable": self.retryable,
        }

        if self.error_details is not None:
            result["error_details"] = self.error_details

        if self.retry_action is not None:
            result["retry_action"] = self.retry_action.to_dict()

        if self.fallback_actions:
            result["fallback_actions"] = [
                action.to_dict() for action in self.fallback_actions
            ]

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ErrorResponse":
        """Create ErrorResponse from dictionary."""
        retry_action = None
        if "retry_action" in data and data["retry_action"]:
            retry_action = UIAction.from_dict(data["retry_action"])

        fallback_actions = [
            UIAction.from_dict(a) for a in data.get("fallback_actions", [])
        ]

        return cls(
            error_code=data.get("error_code", ""),
            error_message=data.get("error_message", ""),
            error_details=data.get("error_details"),
            retryable=data.get("retryable", True),
            retry_action=retry_action,
            fallback_actions=fallback_actions,
        )

    @classmethod
    def from_error_code(
        cls,
        error_code: str,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        retry_action: UIAction | None = None,
        fallback_actions: list[UIAction] | None = None,
    ) -> "ErrorResponse":
        """
        Create ErrorResponse from a known error code.

        Uses ERROR_CODES to determine retryable status and default message.

        Args:
            error_code: Error code from ERROR_CODES
            message: Custom message (overrides default description)
            details: Additional error context
            retry_action: Suggested retry action
            fallback_actions: Alternative actions

        Returns:
            ErrorResponse with appropriate settings
        """
        code_info = ERROR_CODES.get(error_code, {})
        retryable = code_info.get("retryable")
        if retryable is None:
            retryable = True  # Default to retryable if not specified

        return cls(
            error_code=error_code,
            error_message=message or code_info.get("description", "An error occurred"),
            error_details=details,
            retryable=retryable,
            retry_action=retry_action,
            fallback_actions=fallback_actions or [],
        )


def is_valid_error_code(code: str) -> bool:
    """Check if the given string is a valid error code."""
    return code in VALID_ERROR_CODES


def get_error_code_info(code: str) -> dict[str, Any] | None:
    """Get information about an error code, or None if invalid."""
    return ERROR_CODES.get(code)
