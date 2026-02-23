"""
Classification module for workflow_turn message intent detection.

This module provides heuristic (keyword-based) and LLM-based classification
for determining user intent when no explicit event is provided.

Per design doc Routing Flow section:
- Heuristic classification provides a fast path for common patterns (no LLM cost)
- LLM fallback handles ambiguous cases (ORCH-045)

Classification flow (in workflow_turn._determine_action):
1. If structured event provided → direct mapping (Path A)
2. Try heuristic classification (Path B) - fast, no LLM cost
3. If heuristics return None → LLM fallback (Path C)
"""

from src.orchestrator.classification.heuristic import (
    heuristic_classify,
    is_approval_message,
    is_modification_message,
    is_question_message,
    is_status_request,
    is_cancellation_message,
    is_booking_intent_message,
    ClassificationResult,
)

from src.orchestrator.classification.llm_classify import (
    llm_classify,
    LLMClassificationResult,
    LLM_ACTION_TO_INTERNAL,
    DEFAULT_ACTION,
)

__all__ = [
    # Main classification functions
    "heuristic_classify",
    "llm_classify",
    # Individual pattern matchers (for testing and extension)
    "is_approval_message",
    "is_modification_message",
    "is_question_message",
    "is_status_request",
    "is_cancellation_message",
    "is_booking_intent_message",
    # Result types
    "ClassificationResult",
    "LLMClassificationResult",
    # LLM classification helpers
    "LLM_ACTION_TO_INTERNAL",
    "DEFAULT_ACTION",
]
