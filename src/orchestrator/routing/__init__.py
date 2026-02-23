"""
Routing layer for the orchestrator.

This module implements the three-layer routing system for the orchestrator:
- Layer 1a: Active session check (no LLM) - workflow_turn directly
- Layer 1b: Utility pattern match (no LLM) - regex-based utility routing
- Layer 1c: LLM routing (Azure AI Agent) - decides workflow_turn vs answer_question

Per design doc "Routing Flow" and "Orchestrator Initialization and Request Flow" sections.
"""

from src.orchestrator.routing.layer1 import (
    UTILITY_PATTERNS,
    RouteResult,
    RouteTarget,
    UtilityMatch,
    match_utility_pattern,
    route,
)

__all__ = [
    "UTILITY_PATTERNS",
    "RouteResult",
    "RouteTarget",
    "UtilityMatch",
    "match_utility_pattern",
    "route",
]
