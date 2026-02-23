"""
ID Generation utilities for the orchestrator.

ID Format conventions (from design doc):
- session_id: sess_{uuid4} - Browser session tracking
- consultation_id: cons_{uuid4} - Planning conversation (returned to client)
- itinerary_id: itn_{uuid4} - Approved travel plan (user-facing, shareable)
- booking_id: book_{uuid4} - Individual bookable item

All IDs use UUID v4 to ensure:
- Non-guessable (256-bit entropy)
- Globally unique
- URL-safe (base32 encoding optional for shorter URLs)
"""

import uuid

# Standard prefixes per design doc
PREFIX_SESSION = "sess"
PREFIX_CONSULTATION = "cons"
PREFIX_ITINERARY = "itn"
PREFIX_BOOKING = "book"
PREFIX_QUOTE = "quote"
PREFIX_JOB = "job"


def generate_id(prefix: str) -> str:
    """Generate a prefixed UUID v4 identifier.

    Args:
        prefix: The prefix to use (e.g., "sess", "cons", "itn", "book")

    Returns:
        String in format "{prefix}_{uuid4}" where uuid4 is hex without dashes

    Example:
        >>> generate_id("cons")
        'cons_a1b2c3d4e5f6789012345678901234ab'
    """
    # Use hex format without dashes for compactness
    # Full UUID4 provides 122 bits of randomness (sufficient for non-guessable)
    unique_part = uuid.uuid4().hex
    return f"{prefix}_{unique_part}"


def generate_session_id() -> str:
    """Generate a new session ID.

    Format: sess_{uuid4_hex}

    Used for browser session tracking. Ephemeral, not user-facing.
    """
    return generate_id(PREFIX_SESSION)


def generate_consultation_id() -> str:
    """Generate a new consultation ID.

    Format: cons_{uuid4_hex}

    Generated when Phase 1 (planning) starts. Returned to client
    for resuming the planning session. Non-guessable but user-facing.
    """
    return generate_id(PREFIX_CONSULTATION)


def generate_itinerary_id() -> str:
    """Generate a new itinerary ID.

    Format: itn_{uuid4_hex}

    Generated when the itinerary checkpoint is approved. User-facing
    and shareable - can be used for trip links, support calls, etc.
    """
    return generate_id(PREFIX_ITINERARY)


def generate_booking_id() -> str:
    """Generate a new booking ID.

    Format: book_{uuid4_hex}

    Generated when an itinerary is approved (one per bookable item).
    Used for individual booking management and confirmation emails.
    """
    return generate_id(PREFIX_BOOKING)


def generate_quote_id() -> str:
    """Generate a new quote ID.

    Format: quote_{uuid4_hex}

    Generated when creating a booking quote for user confirmation.
    Must be echoed back when booking to prove user saw exact terms.
    """
    return generate_id(PREFIX_QUOTE)


def generate_job_id() -> str:
    """Generate a new job ID.

    Format: job_{uuid4_hex}

    Generated when starting a discovery job. Used to track background
    job progress during long-running discovery operations.
    """
    return generate_id(PREFIX_JOB)


def validate_id_format(id_value: str, expected_prefix: str | None = None) -> bool:
    """Validate that an ID matches the expected format.

    Args:
        id_value: The ID string to validate
        expected_prefix: Optional prefix to check (e.g., "sess", "cons")
                        If None, accepts any valid prefix

    Returns:
        True if the ID is valid, False otherwise
    """
    if not id_value or not isinstance(id_value, str):
        return False

    parts = id_value.split("_", 1)
    if len(parts) != 2:
        return False

    prefix, uuid_part = parts

    # Check prefix if specified
    if expected_prefix is not None and prefix != expected_prefix:
        return False

    # Validate known prefixes if no specific prefix required
    if expected_prefix is None:
        known_prefixes = {PREFIX_SESSION, PREFIX_CONSULTATION, PREFIX_ITINERARY, PREFIX_BOOKING, PREFIX_QUOTE, PREFIX_JOB}
        if prefix not in known_prefixes:
            return False

    # UUID hex should be 32 characters (128 bits = 32 hex chars)
    if len(uuid_part) != 32:
        return False

    # Validate hex characters
    try:
        int(uuid_part, 16)
        return True
    except ValueError:
        return False


def extract_prefix(id_value: str) -> str | None:
    """Extract the prefix from an ID.

    Args:
        id_value: The ID string (e.g., "cons_abc123...")

    Returns:
        The prefix (e.g., "cons") or None if invalid format
    """
    if not id_value or not isinstance(id_value, str):
        return None

    parts = id_value.split("_", 1)
    if len(parts) != 2:
        return None

    return parts[0]
