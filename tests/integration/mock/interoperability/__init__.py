"""
Tier 1 mock tests for cross-platform interoperability.

These tests validate request/response formats and protocols without
incurring LLM costs. Per design doc Testing Strategy (lines 1203-1241):

- Test Levels:
  - Unit: Wrapper logic, config parsing (tests/unit/interoperability/)
  - Integration (Mock): Mock platform APIs, verify request/response formats
  - Integration (Live): Actual deployed agents, end-to-end verification

Fixtures in conftest.py provide deterministic test data for:
- Demo A (Foundry): Intake form, workflow execution, weather integration
- Demo B (Pro Code -> Copilot Studio): Approval decisions, pending items
- Demo C (Copilot Studio -> Foundry): Q&A routing, connected agents
"""
