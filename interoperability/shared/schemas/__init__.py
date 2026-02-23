"""Shared schemas for cross-platform interoperability.

Schemas in this package define contracts between platforms:
- weather.py: WeatherRequest/WeatherResponse for Foundry <-> CS Weather agent
- approval.py: ApprovalRequest/ApprovalDecision for Pro Code <-> CS Approval agent
"""

from interoperability.shared.schemas.weather import (
    WeatherRequest,
    ClimateSummary,
    WeatherResponse,
)

from interoperability.shared.schemas.approval import (
    ApprovalDecisionType,
    ApprovalRequest,
    ApprovalDecision,
)

__all__ = [
    "WeatherRequest",
    "ClimateSummary",
    "WeatherResponse",
    "ApprovalDecisionType",
    "ApprovalRequest",
    "ApprovalDecision",
]
