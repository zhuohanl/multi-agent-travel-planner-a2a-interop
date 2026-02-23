"""Approval schemas for cross-platform interoperability.

Re-exports ApprovalRequest, ApprovalDecision, ApprovalDecisionType from src/shared/models.py
for use by interoperability modules (Approval Agent, Pro Code handlers, mock tests, etc.).

These schemas define the contract between:
- Pro Code Orchestrator (caller)
- Copilot Studio Approval Agent (callee)

See docs/interoperability-design.md for schema details.
"""

from src.shared.models import (
    ApprovalDecisionType,
    ApprovalRequest,
    ApprovalDecision,
)

__all__ = ["ApprovalDecisionType", "ApprovalRequest", "ApprovalDecision"]
