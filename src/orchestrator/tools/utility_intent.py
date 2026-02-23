"""
Utility intent detection and extraction module.

This module provides helpers for detecting utility messages and extracting
utility intent from free-text messages in Layer 2 (inside workflow_turn).

Per design doc (workflow_turn Internal Implementation section):
- is_utility_message(): Detect if message is a utility query
- extract_utility_intent(): Extract utility tool and arguments from message
- UtilityMatch: Result of utility pattern matching

Utility tools covered:
- currency_convert: Currency conversion queries
- weather_lookup: Weather forecast queries
- timezone_info: Timezone information queries
- get_booking: Booking lookup queries
- get_consultation: Consultation lookup queries
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.orchestrator.utils.utility_patterns import (
    BOOKING_LIST_PATTERN,
    BOOKING_LOOKUP_PATTERN,
    CONSULTATION_LIST_PATTERN,
    CONSULTATION_LOOKUP_PATTERN,
    LAYER2_UTILITY_PATTERNS,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Utility Pattern Definitions
# ═══════════════════════════════════════════════════════════════════════════════

# Regex patterns for utility detection
# These patterns match common ways users ask about utilities
UTILITY_PATTERNS: list[str] = LAYER2_UTILITY_PATTERNS


# ═══════════════════════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class UtilityMatch:
    """
    Result of utility pattern matching with extracted tool and arguments.

    Attributes:
        tool: The utility tool name (currency_convert, weather_lookup, timezone_info,
            get_booking, or get_consultation)
        args: Extracted arguments (may be partial - handler will enrich with context)
        raw_message: Original message for context enrichment
    """

    tool: str
    args: dict[str, str | float | None]
    raw_message: str

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary for serialization."""
        return {
            "tool": self.tool,
            "args": self.args,
            "raw_message": self.raw_message,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Detection Functions
# ═══════════════════════════════════════════════════════════════════════════════


def is_utility_message(message: str) -> bool:
    """
    Detect if message is a utility query (Layer 2).

    This function checks if the message matches any utility pattern.
    When matched, the message should be routed to Action.CALL_UTILITY
    instead of going through LLM classification.

    Args:
        message: The user's raw message text

    Returns:
        True if the message matches a utility pattern, False otherwise

    Examples:
        >>> is_utility_message("convert 100 USD to JPY")
        True
        >>> is_utility_message("what's the weather in Tokyo?")
        True
        >>> is_utility_message("I want to plan a trip")
        False
    """
    if not message:
        return False

    lower_message = message.lower()

    for pattern in UTILITY_PATTERNS:
        if re.search(pattern, lower_message):
            return True

    return False


def extract_utility_intent(message: str) -> UtilityMatch | None:
    """
    Extract utility tool and arguments from message.

    Returns None if no utility pattern matches.

    Note: Arguments may be partial - the utility handler will enrich
    with context from WorkflowState (e.g., trip dates for weather).

    Args:
        message: The user's raw message text

    Returns:
        UtilityMatch with tool name and extracted args, or None if no match

    Examples:
        >>> match = extract_utility_intent("convert 100 USD to JPY")
        >>> match.tool
        'currency_convert'
        >>> extract_utility_intent("I want to plan a trip")
        None
    """
    if not message:
        return None

    lower = message.lower()

    # ─────────────────────────────────────────────────────────────────────
    # Lookup patterns (booking / consultation)
    # ─────────────────────────────────────────────────────────────────────
    booking_match = re.search(BOOKING_LOOKUP_PATTERN, message, re.IGNORECASE)
    if booking_match:
        return UtilityMatch(
            tool="get_booking",
            args={"booking_id": booking_match.group(1)},
            raw_message=message,
        )

    if re.search(BOOKING_LIST_PATTERN, lower):
        return UtilityMatch(tool="get_booking", args={}, raw_message=message)

    consultation_match = re.search(
        CONSULTATION_LOOKUP_PATTERN, message, re.IGNORECASE
    )
    if consultation_match:
        return UtilityMatch(
            tool="get_consultation",
            args={"consultation_id": consultation_match.group(1)},
            raw_message=message,
        )

    if re.search(CONSULTATION_LIST_PATTERN, lower):
        return UtilityMatch(tool="get_consultation", args={}, raw_message=message)

    # ─────────────────────────────────────────────────────────────────────
    # Timezone patterns (check first - "what time" overlaps with "what...in")
    # ─────────────────────────────────────────────────────────────────────
    if re.search(r"(what\s+)?time\s+(in|is\s+it|zone)|timezone|time\s+difference|local\s+time", lower):
        args: dict[str, str | float | None] = {}

        # Try to extract location
        loc_match = re.search(
            r"time\s+(?:in|at|is\s+it\s+in)\s+([^?.,]+)",
            message,
            re.IGNORECASE,
        )
        if loc_match:
            args["location"] = loc_match.group(1).strip()

        return UtilityMatch(tool="timezone_info", args=args, raw_message=message)

    # ─────────────────────────────────────────────────────────────────────
    # Weather patterns
    # ─────────────────────────────────────────────────────────────────────
    if re.search(r"weather|temperature|rain|sunny|cloudy|forecast", lower):
        args = {}

        # Try to extract location
        loc_match = re.search(
            r"weather\s+(?:in|for|at)\s+([^?.,]+)",
            message,
            re.IGNORECASE,
        )
        if loc_match:
            args["location"] = loc_match.group(1).strip()

        return UtilityMatch(tool="weather_lookup", args=args, raw_message=message)

    # ─────────────────────────────────────────────────────────────────────
    # Currency patterns (check last to avoid overlapping with timezone)
    # ─────────────────────────────────────────────────────────────────────
    if re.search(r"convert|exchange|currency|(how much|what).*(in|to)", lower):
        # Try to extract amount and currencies
        args = {}

        # Pattern: "100 USD to JPY" or "convert 100 USD to JPY"
        amount_match = re.search(r"(\d+(?:\.\d+)?)\s*([A-Za-z]{3})", message)
        if amount_match:
            args["amount"] = float(amount_match.group(1))
            args["from_currency"] = amount_match.group(2).upper()

        # Find target currency
        to_match = re.search(r"(?:to|in|into)\s+([A-Za-z]{3})", message, re.IGNORECASE)
        if to_match:
            args["to_currency"] = to_match.group(1).upper()

        return UtilityMatch(tool="currency_convert", args=args, raw_message=message)

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Module Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "UTILITY_PATTERNS",
    "UtilityMatch",
    "is_utility_message",
    "extract_utility_intent",
]
