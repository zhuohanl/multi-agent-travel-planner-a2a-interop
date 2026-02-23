"""
Heuristic (keyword-based) classification for workflow_turn message intent detection.

This module provides fast, deterministic classification of user messages using
regex patterns and keyword matching. No LLM calls are made.

Per design doc Routing Flow section (Layer 2a):
- Approvals: "yes", "looks good", "approve" → YES (workflow action)
- Modifications: "change X", "different X" → YES (workflow action)
- Selections: "book the X", "select X" → YES (workflow action)
- Cancellations: "cancel", "start over" → YES (workflow action)
- Questions: "is this hotel...?", "what about?" → NO (answer_question)
- Utilities: "how much in dollars?" → NO (call_utility - handled separately)

The heuristic classifier returns None when it cannot confidently classify,
signaling that LLM fallback (ORCH-045) should be used.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.orchestrator.state_gating import Action

if TYPE_CHECKING:
    from src.orchestrator.models.workflow_state import WorkflowState, Phase

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Classification Result
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ClassificationResult:
    """Result of heuristic classification.

    Attributes:
        action: The classified action, or None if heuristics couldn't classify
        confidence: Confidence score 0.0-1.0 (for logging/debugging)
        reason: Brief explanation of why this classification was made
    """
    action: Action | None
    confidence: float = 1.0
    reason: str = ""

    @property
    def is_classified(self) -> bool:
        """Returns True if the message was successfully classified."""
        return self.action is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Pattern Definitions
# ═══════════════════════════════════════════════════════════════════════════════

# Approval patterns - user agrees with current state/proposal
APPROVAL_PATTERNS = [
    # Explicit approval
    r"\b(yes|yeah|yep|yup|sure|ok|okay|approve|approved|accept|accepted)\b",
    r"\blooks?\s+(good|great|fine|perfect|correct)\b",
    r"\bthat['']?s?\s+(good|great|fine|perfect|correct|right)\b",
    r"\b(sounds?\s+(good|great|fine|perfect))\b",
    r"\b(go\s+ahead|let['']?s?\s+(go|do\s+it|proceed))\b",
    r"\b(i\s+)?agree\b",
    r"\b(confirm|confirmed|confirming)\b",
    r"\bproceed\b",
    # Thumbs up / positive shorthand
    r"^\s*(👍|✅|✓|y|yea)\s*$",
]

# Modification patterns - user wants to change something
MODIFICATION_PATTERNS = [
    # Explicit change requests
    r"\b(change|modify|update|alter|revise|adjust|edit)\s+(the|my|this)?\s*\w*",
    r"\b(different|another|alternative)\s+\w+",
    r"\b(switch|swap)\s+(to|the)?\s*\w*",
    r"\b(want|need|prefer)\s+(a\s+)?different\b",
    r"\b(can\s+(you|we)|could\s+(you|we))\s+(change|modify|update)\b",
    r"\binstead\s+of\b",
    r"\brather\s+(have|than)\b",
    r"\b(not\s+this|not\s+that)\b",
    r"\b(let['']?s?\s+)?try\s+(something\s+)?(else|different)\b",
    r"\bactually[,]?\s+(i\s+)?(want|prefer|need)\b",
    # Negation patterns - user doesn't want something
    r"\bdon['']?t\s+(want|like|need)\b",
    # Date/time changes
    r"\b(move|shift)\s+(the\s+)?(date|time|trip)\b",
    r"\b(extend|shorten)\s+(the\s+)?(trip|stay)\b",
    # Budget changes
    r"\b(increase|decrease|raise|lower)\s+(the\s+)?budget\b",
]

# Question patterns - user is asking for information
QUESTION_PATTERNS = [
    # Question words at start
    r"^(what|where|when|why|who|how|which|can|could|would|will|is|are|do|does|did|have|has|should)\b",
    # Questions ending with ?
    r"\?\s*$",
    # Information requests
    r"\b(tell\s+me|explain|describe|show\s+me)\s+(about|more|the)?\b",
    r"\bwhat['']?s?\s+(the|this|that)\b",
    r"\bi\s+(want\s+to\s+)?know\b",
    r"\b(curious|wondering)\s+about\b",
    # Clarification requests
    r"\b(can\s+you\s+)?(clarify|explain)\b",
    r"\bwhat\s+(do\s+you\s+)?mean\b",
    r"\bi\s+don['']?t\s+understand\b",
]

# Status request patterns - user wants to know current state
STATUS_PATTERNS = [
    r"\b(what['']?s?\s+the\s+)?status\b",
    r"\bwhere\s+(are\s+)?(we|things)\b",
    r"\bhow['']?s?\s+(it\s+)?going\b",
    r"\b(show|get|check)\s+(me\s+)?(the\s+)?(status|progress)\b",
    r"\bany\s+(updates?|progress)\b",
    r"\bcurrent\s+state\b",
    r"\bwhat['']?s?\s+happening\b",
    r"\bare\s+(we|things)\s+(done|ready)\b",
]

# Cancellation patterns - user wants to stop/cancel
CANCELLATION_PATTERNS = [
    r"\b(cancel|abort|stop|quit|exit|end)\s*(this|the)?\s*(trip|workflow|session|planning)?\b",
    r"\bstart\s+(over|fresh|again)\b",
    r"\bnever\s*mind\b",
    r"\bforget\s+(it|about\s+it)\b",
    r"\bi\s+(give\s+up|changed\s+my\s+mind)\b",
    r"\bdon['']?t\s+(want\s+to\s+)?(continue|proceed)\b",
    r"\bscrap\s+(it|this)\b",
]

# Booking intent patterns - user wants to book something
BOOKING_INTENT_PATTERNS = [
    r"\b(book|reserve|purchase|buy)\s+(this|that|the|it|them|a)\b",
    r"\bi['']?ll\s+(take|book|get)\s+(it|this|that|them)\b",
    r"\b(let['']?s?\s+)?(book|reserve)\b",
    r"\b(ready\s+to|want\s+to|like\s+to)\s+(book|reserve|purchase)\b",
    r"\bconfirm\s+(the\s+)?(booking|reservation)\b",
    r"\bconfirm\s+my\s+(booking|reservation)\b",
    r"\badd\s+(this\s+)?to\s+(my\s+)?(cart|booking)\b",
    r"\bselect\s+(this|that|the)\s+\w+\b",
    r"\bgo\s+(with|for)\s+(this|that|the)\s+\w+\b",
    r"\bbook\s+(the\s+)?\w+\s*(option|choice)?\b",
]


# ═══════════════════════════════════════════════════════════════════════════════
# Pattern Matchers
# ═══════════════════════════════════════════════════════════════════════════════


def _matches_any_pattern(text: str, patterns: list[str]) -> bool:
    """Check if text matches any of the given regex patterns.

    Args:
        text: The text to check (case-insensitive)
        patterns: List of regex patterns to try

    Returns:
        True if any pattern matches
    """
    text_lower = text.lower().strip()
    for pattern in patterns:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    return False


def is_approval_message(message: str) -> bool:
    """Check if message expresses approval/agreement.

    Examples:
        "yes" → True
        "looks good" → True
        "let's proceed" → True
        "I have a question" → False
    """
    return _matches_any_pattern(message, APPROVAL_PATTERNS)


def is_modification_message(message: str) -> bool:
    """Check if message requests a modification/change.

    Examples:
        "change the hotel" → True
        "I want a different flight" → True
        "can we switch to a later date" → True
        "what hotels are available" → False
    """
    return _matches_any_pattern(message, MODIFICATION_PATTERNS)


def is_question_message(message: str) -> bool:
    """Check if message is asking a question.

    Examples:
        "what is the weather like?" → True
        "is this hotel near the station?" → True
        "tell me about the area" → True
        "yes, let's book it" → False
    """
    return _matches_any_pattern(message, QUESTION_PATTERNS)


def is_status_request(message: str) -> bool:
    """Check if message is asking for status/progress.

    Examples:
        "what's the status" → True
        "any updates?" → True
        "where are we?" → True
        "what hotels are available" → False
    """
    return _matches_any_pattern(message, STATUS_PATTERNS)


def is_cancellation_message(message: str) -> bool:
    """Check if message requests cancellation/stop.

    Examples:
        "cancel this" → True
        "start over" → True
        "never mind" → True
        "cancel the flight option" → True (but context matters)
    """
    return _matches_any_pattern(message, CANCELLATION_PATTERNS)


def is_booking_intent_message(message: str) -> bool:
    """Check if message expresses intent to book.

    Examples:
        "book this hotel" → True
        "I'll take the first flight" → True
        "let's book" → True
        "what can I book" → False (question, not intent)
    """
    # First check if it's primarily a question (starts with question word or ends with ?)
    # Questions ABOUT booking are not the same as intent TO book
    message_lower = message.lower().strip()
    if message_lower.endswith("?"):
        return False
    # Check for question words at start that indicate inquiry, not action
    question_starters = ("what", "where", "when", "why", "who", "how", "which", "can i", "could i")
    if any(message_lower.startswith(q) for q in question_starters):
        return False
    return _matches_any_pattern(message, BOOKING_INTENT_PATTERNS)


# ═══════════════════════════════════════════════════════════════════════════════
# Main Classification Function
# ═══════════════════════════════════════════════════════════════════════════════


def heuristic_classify(
    message: str,
    state: "WorkflowState | None" = None,
) -> ClassificationResult:
    """
    Classify user message intent using keyword-based heuristics.

    This is the fast path for common message patterns. Returns None for
    the action when the message cannot be confidently classified, signaling
    that LLM fallback should be used.

    Per design doc Routing Flow (Layer 2a):
    - Priority order prevents misclassification
    - Questions are lower priority (many patterns overlap with actions)
    - Returns ClassificationResult with action=None if uncertain

    Classification priority:
    1. Status requests (always safe, non-mutating)
    2. Cancellation (explicit user intent to stop)
    3. Approval (at checkpoints)
    4. Modification (change requests)
    5. Booking intent (in BOOKING phase)
    6. Questions (catch-all for interrogative patterns)
    7. None (LLM fallback needed)

    Args:
        message: The user's raw message text
        state: Current workflow state (optional, for phase-aware classification)

    Returns:
        ClassificationResult with action and confidence
    """
    if not message or not message.strip():
        return ClassificationResult(
            action=None,
            confidence=0.0,
            reason="Empty message",
        )

    message = message.strip()

    # ─────────────────────────────────────────────────────────────────────
    # 1. Status requests - always safe, non-mutating
    # ─────────────────────────────────────────────────────────────────────
    if is_status_request(message):
        logger.debug(f"Heuristic: classified as GET_STATUS: {message[:50]}")
        return ClassificationResult(
            action=Action.GET_STATUS,
            confidence=0.9,
            reason="Status request pattern matched",
        )

    # ─────────────────────────────────────────────────────────────────────
    # 2. Cancellation - explicit user intent to stop
    # ─────────────────────────────────────────────────────────────────────
    if is_cancellation_message(message):
        logger.debug(f"Heuristic: classified as CANCEL_WORKFLOW: {message[:50]}")
        return ClassificationResult(
            action=Action.CANCEL_WORKFLOW,
            confidence=0.85,
            reason="Cancellation pattern matched",
        )

    # ─────────────────────────────────────────────────────────────────────
    # 3. Approval - user agreeing with current state
    # ─────────────────────────────────────────────────────────────────────
    # Note: The specific approval action (APPROVE_TRIP_SPEC vs APPROVE_ITINERARY)
    # depends on the current checkpoint. workflow_turn handles this resolution.
    if is_approval_message(message):
        # Check if we're at a checkpoint where approval makes sense
        if state and state.checkpoint:
            if state.checkpoint == "trip_spec_approval":
                logger.debug(f"Heuristic: classified as APPROVE_TRIP_SPEC: {message[:50]}")
                return ClassificationResult(
                    action=Action.APPROVE_TRIP_SPEC,
                    confidence=0.9,
                    reason="Approval at trip_spec_approval checkpoint",
                )
            elif state.checkpoint == "itinerary_approval":
                logger.debug(f"Heuristic: classified as APPROVE_ITINERARY: {message[:50]}")
                return ClassificationResult(
                    action=Action.APPROVE_ITINERARY,
                    confidence=0.9,
                    reason="Approval at itinerary_approval checkpoint",
                )

        # Approval without checkpoint - might be confirming info during clarification
        # Let it fall through to clarification or LLM fallback
        logger.debug(f"Heuristic: approval pattern but no checkpoint, treating as clarification: {message[:50]}")
        return ClassificationResult(
            action=Action.CONTINUE_CLARIFICATION,
            confidence=0.7,
            reason="Approval pattern without checkpoint - treating as clarification",
        )

    # ─────────────────────────────────────────────────────────────────────
    # 4. Modification - user wants to change something
    # ─────────────────────────────────────────────────────────────────────
    if is_modification_message(message):
        logger.debug(f"Heuristic: classified as REQUEST_MODIFICATION: {message[:50]}")
        return ClassificationResult(
            action=Action.REQUEST_MODIFICATION,
            confidence=0.85,
            reason="Modification pattern matched",
        )

    # ─────────────────────────────────────────────────────────────────────
    # 5. Booking intent - user wants to book (only in BOOKING phase)
    # ─────────────────────────────────────────────────────────────────────
    if is_booking_intent_message(message):
        from src.orchestrator.models.workflow_state import Phase

        # Only treat as booking intent if we're in BOOKING phase
        if state and state.phase == Phase.BOOKING:
            logger.debug(f"Heuristic: classified as VIEW_BOOKING_OPTIONS: {message[:50]}")
            return ClassificationResult(
                action=Action.VIEW_BOOKING_OPTIONS,
                confidence=0.85,
                reason="Booking intent in BOOKING phase",
            )
        else:
            # Booking intent outside BOOKING phase - treat as question
            # User might be asking about booking options, not actually booking
            logger.debug(f"Heuristic: booking intent outside BOOKING phase, treating as question: {message[:50]}")
            return ClassificationResult(
                action=Action.ANSWER_QUESTION_IN_CONTEXT,
                confidence=0.7,
                reason="Booking intent outside BOOKING phase",
            )

    # ─────────────────────────────────────────────────────────────────────
    # 6. Questions - catch-all for interrogative patterns
    # ─────────────────────────────────────────────────────────────────────
    if is_question_message(message):
        logger.debug(f"Heuristic: classified as ANSWER_QUESTION_IN_CONTEXT: {message[:50]}")
        return ClassificationResult(
            action=Action.ANSWER_QUESTION_IN_CONTEXT,
            confidence=0.8,
            reason="Question pattern matched",
        )

    # ─────────────────────────────────────────────────────────────────────
    # 7. No confident match - fall through to LLM or default
    # ─────────────────────────────────────────────────────────────────────
    # Return None action to signal LLM fallback needed
    # However, if we're in CLARIFICATION phase, default to CONTINUE_CLARIFICATION
    # since that's the most common case
    if state:
        from src.orchestrator.models.workflow_state import Phase
        if state.phase == Phase.CLARIFICATION:
            logger.debug(f"Heuristic: no match, defaulting to CONTINUE_CLARIFICATION: {message[:50]}")
            return ClassificationResult(
                action=Action.CONTINUE_CLARIFICATION,
                confidence=0.5,
                reason="No heuristic match, defaulting to clarification in CLARIFICATION phase",
            )

    logger.debug(f"Heuristic: no confident match, returning None for LLM fallback: {message[:50]}")
    return ClassificationResult(
        action=None,
        confidence=0.0,
        reason="No heuristic pattern matched",
    )
