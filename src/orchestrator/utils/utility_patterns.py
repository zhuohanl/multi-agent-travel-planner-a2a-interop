"""
Shared utility regex patterns used across routing (Layer 1b) and workflow_turn (Layer 2).

Layer 1b patterns are intentionally simplistic for fast-path routing.
Layer 2 uses a superset for context-aware utility detection.
"""

from __future__ import annotations

# Canonical Layer 1b patterns (intentionally simplistic)
CURRENCY_CONVERT_PATTERN = r"convert\s+(\d+(?:\.\d+)?)\s+(\w+)\s+to\s+(\w+)"
WEATHER_LOOKUP_PATTERN = r"weather\s+(?:in|for)\s+(.+)"
TIMEZONE_INFO_PATTERN = r"what\s+time\s+(?:in|is\s+it\s+in)\s+(.+)"
BOOKING_LOOKUP_PATTERN = r"show\s+booking\s+(book_\w+)"
CONSULTATION_LOOKUP_PATTERN = r"show\s+consultation\s+(cons_\w+)"
LIST_QUALIFIER_PATTERN = (
    r"(?:all|any|current|existing|previous|past|recent|open|active|available|saved|prior|older|the)"
)
LIST_QUALIFIER_PREFIX = rf"(?:{LIST_QUALIFIER_PATTERN}\s+)?(?:of\s+)?"
BOOKING_LIST_PATTERN = (
    rf"\b(list|what|which)\s+(?:out\s+)?{LIST_QUALIFIER_PREFIX}(?:the\s+)?(?:my\s+)?bookings?"
    rf"(?:\s+sessions?)?(?:\s+(?:do\s+)?(?:i|we)\s+have)?(?:\s+that\s+i\s+created\s+before)?\b"
)
CONSULTATION_LIST_PATTERN = (
    rf"\b(list|what|which)\s+(?:out\s+)?{LIST_QUALIFIER_PREFIX}(?:the\s+)?(?:my\s+)?consultations?"
    rf"(?:\s+sessions?)?(?:\s+(?:do\s+)?(?:i|we)\s+have)?\b"
)

# Layer 1b pattern map (name -> regex)
LAYER1_UTILITY_PATTERNS: dict[str, str] = {
    "currency": CURRENCY_CONVERT_PATTERN,
    "weather": WEATHER_LOOKUP_PATTERN,
    "timezone": TIMEZONE_INFO_PATTERN,
    "booking_lookup": BOOKING_LOOKUP_PATTERN,
    "consultation_lookup": CONSULTATION_LOOKUP_PATTERN,
}

# Layer 2 extra patterns (beyond canonical) for context-aware detection
LAYER2_EXTRA_UTILITY_PATTERNS: list[str] = [
    # Currency patterns
    r"convert\s+\d+",
    r"exchange\s+rate",
    r"(how\s+much|what).*?(in|to)\s+[a-z]+",
    r"\d+\s+[a-z]{3}\s+(to|in)\s+[a-z]{3}",
    r"currency",
    r"local\s+currency",
    # Weather patterns
    r"weather\s+(in|for|during)",
    r"(what'?s?|how'?s?)\s+(the\s+)?weather",
    r"temperature\s+(in|for|during)",
    r"(rain|sunny|cloudy|forecast)",
    r"weather\s+(?:at|during)\s+(my|the)\s+",
    # Timezone patterns
    r"(what\s+)?time\s+(in|is\s+it\s+in)",
    r"timezone",
    r"time\s+difference",
    r"what\s+time\s+(zone|is\s+it)",
    r"local\s+time",
    # Booking/consultation listing queries (no IDs)
    BOOKING_LIST_PATTERN,
    CONSULTATION_LIST_PATTERN,
]

# Layer 2 patterns include Layer 1b patterns plus extra context-aware variants
LAYER2_UTILITY_PATTERNS: list[str] = [
    CURRENCY_CONVERT_PATTERN,
    WEATHER_LOOKUP_PATTERN,
    TIMEZONE_INFO_PATTERN,
    BOOKING_LOOKUP_PATTERN,
    CONSULTATION_LOOKUP_PATTERN,
    *LAYER2_EXTRA_UTILITY_PATTERNS,
]
