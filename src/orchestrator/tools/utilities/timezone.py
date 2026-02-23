"""
Timezone info utility tool.

This module provides timezone information lookup for a location.
It can be invoked:
1. From Layer 1b via regex pattern match ("what time in Tokyo")
2. From Layer 1c via LLM fallback ("what's the time in Paris right now")
3. From Layer 2 via CALL_UTILITY action ("what time is it at my destination")

Per design doc (Tool Definitions section):
- Parameters: location (required), date (optional for DST-aware results)
- Returns formatted string like "Tokyo: JST (UTC+9), current time 14:30"
- Handles DST-aware results when date is provided

Uses mock timezone data for deterministic testing. In production, this
would use a proper timezone library (pytz, zoneinfo) or MCP tool.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
import re


# =============================================================================
# TIMEZONE DATA
# =============================================================================

# Mock timezone data by location (for deterministic testing)
# In production, these would come from pytz/zoneinfo or a timezone API
# Each location has base UTC offset and optional DST info
@dataclass(frozen=True)
class TimezoneData:
    """Timezone information for a location."""

    timezone_name: str  # Abbreviation (e.g., "JST", "EST")
    utc_offset: float  # Base UTC offset in hours
    dst_name: str | None = None  # DST abbreviation (e.g., "EDT")
    dst_offset: float | None = None  # DST UTC offset in hours
    dst_start_month: int | None = None  # Month DST starts (1-12)
    dst_end_month: int | None = None  # Month DST ends (1-12)


LOCATION_TIMEZONES: dict[str, TimezoneData] = {
    # Asia (generally no DST)
    "tokyo": TimezoneData(
        timezone_name="JST",
        utc_offset=9,
    ),
    "osaka": TimezoneData(
        timezone_name="JST",
        utc_offset=9,
    ),
    "kyoto": TimezoneData(
        timezone_name="JST",
        utc_offset=9,
    ),
    "seoul": TimezoneData(
        timezone_name="KST",
        utc_offset=9,
    ),
    "bangkok": TimezoneData(
        timezone_name="ICT",
        utc_offset=7,
    ),
    "singapore": TimezoneData(
        timezone_name="SGT",
        utc_offset=8,
    ),
    "beijing": TimezoneData(
        timezone_name="CST",
        utc_offset=8,
    ),
    "shanghai": TimezoneData(
        timezone_name="CST",
        utc_offset=8,
    ),
    "hong kong": TimezoneData(
        timezone_name="HKT",
        utc_offset=8,
    ),
    "mumbai": TimezoneData(
        timezone_name="IST",
        utc_offset=5.5,
    ),
    "delhi": TimezoneData(
        timezone_name="IST",
        utc_offset=5.5,
    ),
    "dubai": TimezoneData(
        timezone_name="GST",
        utc_offset=4,
    ),
    # Europe (with DST: March last Sunday to October last Sunday)
    "paris": TimezoneData(
        timezone_name="CET",
        utc_offset=1,
        dst_name="CEST",
        dst_offset=2,
        dst_start_month=3,
        dst_end_month=10,
    ),
    "london": TimezoneData(
        timezone_name="GMT",
        utc_offset=0,
        dst_name="BST",
        dst_offset=1,
        dst_start_month=3,
        dst_end_month=10,
    ),
    "rome": TimezoneData(
        timezone_name="CET",
        utc_offset=1,
        dst_name="CEST",
        dst_offset=2,
        dst_start_month=3,
        dst_end_month=10,
    ),
    "barcelona": TimezoneData(
        timezone_name="CET",
        utc_offset=1,
        dst_name="CEST",
        dst_offset=2,
        dst_start_month=3,
        dst_end_month=10,
    ),
    "berlin": TimezoneData(
        timezone_name="CET",
        utc_offset=1,
        dst_name="CEST",
        dst_offset=2,
        dst_start_month=3,
        dst_end_month=10,
    ),
    "amsterdam": TimezoneData(
        timezone_name="CET",
        utc_offset=1,
        dst_name="CEST",
        dst_offset=2,
        dst_start_month=3,
        dst_end_month=10,
    ),
    "vienna": TimezoneData(
        timezone_name="CET",
        utc_offset=1,
        dst_name="CEST",
        dst_offset=2,
        dst_start_month=3,
        dst_end_month=10,
    ),
    "zurich": TimezoneData(
        timezone_name="CET",
        utc_offset=1,
        dst_name="CEST",
        dst_offset=2,
        dst_start_month=3,
        dst_end_month=10,
    ),
    "moscow": TimezoneData(
        timezone_name="MSK",
        utc_offset=3,
    ),
    # Americas (with DST: March 2nd Sunday to November 1st Sunday)
    "new york": TimezoneData(
        timezone_name="EST",
        utc_offset=-5,
        dst_name="EDT",
        dst_offset=-4,
        dst_start_month=3,
        dst_end_month=11,
    ),
    "los angeles": TimezoneData(
        timezone_name="PST",
        utc_offset=-8,
        dst_name="PDT",
        dst_offset=-7,
        dst_start_month=3,
        dst_end_month=11,
    ),
    "san francisco": TimezoneData(
        timezone_name="PST",
        utc_offset=-8,
        dst_name="PDT",
        dst_offset=-7,
        dst_start_month=3,
        dst_end_month=11,
    ),
    "chicago": TimezoneData(
        timezone_name="CST",
        utc_offset=-6,
        dst_name="CDT",
        dst_offset=-5,
        dst_start_month=3,
        dst_end_month=11,
    ),
    "denver": TimezoneData(
        timezone_name="MST",
        utc_offset=-7,
        dst_name="MDT",
        dst_offset=-6,
        dst_start_month=3,
        dst_end_month=11,
    ),
    "toronto": TimezoneData(
        timezone_name="EST",
        utc_offset=-5,
        dst_name="EDT",
        dst_offset=-4,
        dst_start_month=3,
        dst_end_month=11,
    ),
    "vancouver": TimezoneData(
        timezone_name="PST",
        utc_offset=-8,
        dst_name="PDT",
        dst_offset=-7,
        dst_start_month=3,
        dst_end_month=11,
    ),
    "mexico city": TimezoneData(
        timezone_name="CST",
        utc_offset=-6,
        dst_name="CDT",
        dst_offset=-5,
        dst_start_month=4,
        dst_end_month=10,
    ),
    "sao paulo": TimezoneData(
        timezone_name="BRT",
        utc_offset=-3,
    ),
    "buenos aires": TimezoneData(
        timezone_name="ART",
        utc_offset=-3,
    ),
    # Oceania
    "sydney": TimezoneData(
        timezone_name="AEST",
        utc_offset=10,
        dst_name="AEDT",
        dst_offset=11,
        dst_start_month=10,  # October (Southern hemisphere)
        dst_end_month=4,  # April
    ),
    "melbourne": TimezoneData(
        timezone_name="AEST",
        utc_offset=10,
        dst_name="AEDT",
        dst_offset=11,
        dst_start_month=10,
        dst_end_month=4,
    ),
    "auckland": TimezoneData(
        timezone_name="NZST",
        utc_offset=12,
        dst_name="NZDT",
        dst_offset=13,
        dst_start_month=9,  # September (Southern hemisphere)
        dst_end_month=4,  # April
    ),
    "brisbane": TimezoneData(
        timezone_name="AEST",
        utc_offset=10,
    ),
    "perth": TimezoneData(
        timezone_name="AWST",
        utc_offset=8,
    ),
    # Africa / Middle East
    "cairo": TimezoneData(
        timezone_name="EET",
        utc_offset=2,
    ),
    "johannesburg": TimezoneData(
        timezone_name="SAST",
        utc_offset=2,
    ),
    "lagos": TimezoneData(
        timezone_name="WAT",
        utc_offset=1,
    ),
    # Hawaii
    "honolulu": TimezoneData(
        timezone_name="HST",
        utc_offset=-10,
    ),
}

# Aliases for location lookup (same as weather.py)
TIMEZONE_ALIASES: dict[str, str] = {
    "japan": "tokyo",
    "korea": "seoul",
    "south korea": "seoul",
    "thailand": "bangkok",
    "china": "beijing",
    "india": "mumbai",
    "france": "paris",
    "uk": "london",
    "united kingdom": "london",
    "england": "london",
    "italy": "rome",
    "spain": "barcelona",
    "germany": "berlin",
    "netherlands": "amsterdam",
    "holland": "amsterdam",
    "austria": "vienna",
    "switzerland": "zurich",
    "russia": "moscow",
    "usa": "new york",
    "us": "new york",
    "united states": "new york",
    "america": "new york",
    "canada": "toronto",
    "mexico": "mexico city",
    "brazil": "sao paulo",
    "argentina": "buenos aires",
    "australia": "sydney",
    "new zealand": "auckland",
    "egypt": "cairo",
    "south africa": "johannesburg",
    "nigeria": "lagos",
    "uae": "dubai",
    "hawaii": "honolulu",
}


# =============================================================================
# EXCEPTIONS
# =============================================================================


class InvalidTimezoneLocationError(ValueError):
    """Raised when an invalid or unsupported location is provided."""

    def __init__(self, location: str, message: str | None = None) -> None:
        self.location = location
        self.message = message or f"Unknown location: {location}"
        super().__init__(self.message)


class InvalidDateError(ValueError):
    """Raised when an invalid date is provided."""

    def __init__(self, date_str: str, message: str | None = None) -> None:
        self.date_str = date_str
        self.message = message or f"Invalid date: {date_str}"
        super().__init__(self.message)


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass(frozen=True)
class TimezoneInfo:
    """Result of a timezone lookup operation."""

    location: str  # Normalized location name (title case)
    timezone_name: str  # Current timezone abbreviation (e.g., "JST", "EDT")
    utc_offset: float  # Current UTC offset in hours
    is_dst: bool  # Whether DST is currently in effect
    current_time: datetime  # Current time in that timezone
    formatted: str  # Human-readable formatted string

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "location": self.location,
            "timezone_name": self.timezone_name,
            "utc_offset": self.utc_offset,
            "is_dst": self.is_dst,
            "current_time": self.current_time.isoformat(),
            "formatted": self.formatted,
        }


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def normalize_timezone_location(location: str) -> str:
    """Normalize a location string for timezone lookup.

    Args:
        location: Location name (any case, may include country)

    Returns:
        Normalized location key for LOCATION_TIMEZONES lookup

    Raises:
        InvalidTimezoneLocationError: If the location is not recognized
    """
    # Clean and lowercase
    normalized = location.strip().lower()

    # Remove common suffixes like ", Japan" or ", France"
    if "," in normalized:
        normalized = normalized.split(",")[0].strip()

    # Check direct match
    if normalized in LOCATION_TIMEZONES:
        return normalized

    # Check aliases
    if normalized in TIMEZONE_ALIASES:
        return TIMEZONE_ALIASES[normalized]

    # Check for partial matches (e.g., "tokyo japan" -> "tokyo")
    for loc_key in LOCATION_TIMEZONES:
        if loc_key in normalized or normalized in loc_key:
            return loc_key

    # Check alias partial matches
    for alias, loc_key in TIMEZONE_ALIASES.items():
        if alias in normalized or normalized in alias:
            return loc_key

    raise InvalidTimezoneLocationError(location)


def parse_date_string(date_str: str | None) -> date | None:
    """Parse a date string into a date object.

    Args:
        date_str: Date string (e.g., '2026-03-15') or None

    Returns:
        date object if parseable, None if date_str is None

    Raises:
        InvalidDateError: If the date string cannot be parsed
    """
    if date_str is None:
        return None

    cleaned = date_str.strip()

    # Try ISO format first
    try:
        return datetime.strptime(cleaned, "%Y-%m-%d").date()
    except ValueError:
        pass

    # Try other common formats
    formats = [
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%Y/%m/%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    raise InvalidDateError(date_str)


def is_dst_active(tz_data: TimezoneData, check_date: date) -> bool:
    """Check if DST is active for a given timezone and date.

    Args:
        tz_data: Timezone data with DST info
        check_date: Date to check

    Returns:
        True if DST is active, False otherwise

    Note:
        This is a simplified approximation. Real DST calculation requires
        exact transition rules (e.g., "2nd Sunday of March at 2am").
    """
    if tz_data.dst_offset is None:
        return False

    month = check_date.month
    start = tz_data.dst_start_month
    end = tz_data.dst_end_month

    if start is None or end is None:
        return False

    # Handle Northern vs Southern hemisphere DST
    if start < end:
        # Northern hemisphere: DST is March-November
        return start <= month <= end
    else:
        # Southern hemisphere: DST is October-April (wraps around year)
        return month >= start or month <= end


def format_utc_offset(offset: float) -> str:
    """Format a UTC offset as a string like 'UTC+9' or 'UTC-5:30'.

    Args:
        offset: UTC offset in hours (can be fractional)

    Returns:
        Formatted offset string
    """
    sign = "+" if offset >= 0 else ""

    if offset == int(offset):
        return f"UTC{sign}{int(offset)}"
    else:
        # Handle fractional offsets (e.g., India's +5:30)
        hours = int(offset)
        minutes = int((offset - hours) * 60)
        if offset < 0:
            hours = -(-hours)  # Keep negative sign
            minutes = abs(minutes)
        return f"UTC{sign}{hours}:{abs(minutes):02d}"


# =============================================================================
# MAIN FUNCTIONS
# =============================================================================


def timezone_info(location: str, date_str: str | None = None) -> TimezoneInfo:
    """Look up timezone information for a location.

    This is the main timezone lookup function, used for stateless queries
    from Layer 1b (regex) and Layer 1c (LLM fallback).

    Args:
        location: Location name (city, region, or country)
        date_str: Optional date for DST-aware result (e.g., '2026-03-15')

    Returns:
        TimezoneInfo with timezone details and formatted string

    Raises:
        InvalidTimezoneLocationError: If the location is not recognized
        InvalidDateError: If the date string cannot be parsed

    Example:
        >>> result = timezone_info("Tokyo", "2026-03-15")
        >>> result.formatted
        'Tokyo: JST (UTC+9), current time 14:30'
    """
    # Normalize location
    loc_key = normalize_timezone_location(location)
    tz_data = LOCATION_TIMEZONES[loc_key]

    # Parse date (or use current date)
    check_date = parse_date_string(date_str) if date_str else datetime.utcnow().date()

    # Determine if DST is active
    is_dst = is_dst_active(tz_data, check_date)

    # Get current timezone name and offset
    if is_dst and tz_data.dst_name and tz_data.dst_offset is not None:
        tz_name = tz_data.dst_name
        offset = tz_data.dst_offset
    else:
        tz_name = tz_data.timezone_name
        offset = tz_data.utc_offset

    # Calculate current time in that timezone
    # Use UTC now and add offset (simplified - doesn't handle DST transitions precisely)
    utc_now = datetime.utcnow()
    local_now = utc_now + timedelta(hours=offset)

    # Build formatted output
    display_location = loc_key.title()
    offset_str = format_utc_offset(offset)
    time_str = local_now.strftime("%H:%M")

    formatted = f"{display_location}: {tz_name} ({offset_str}), current time {time_str}"

    return TimezoneInfo(
        location=display_location,
        timezone_name=tz_name,
        utc_offset=offset,
        is_dst=is_dst,
        current_time=local_now,
        formatted=formatted,
    )


async def timezone_info_with_context(
    message: str,
    destination: str | None = None,
    trip_dates: str | None = None,
) -> str:
    """Look up timezone info with optional context from workflow.

    This function is called from Layer 2 (inside workflow_turn) when
    the user asks about time zones during trip planning. It can use
    the trip destination as a default location.

    Args:
        message: The user's raw message (e.g., "what time is it in Tokyo")
        destination: Optional trip destination for default location
        trip_dates: Optional trip dates (used to determine which date for DST check)

    Returns:
        Formatted timezone info string

    Example:
        >>> await timezone_info_with_context("what time is it", destination="Tokyo, Japan")
        'Tokyo: JST (UTC+9), current time 14:30'
    """
    # Try to extract location from message
    location: str | None = None
    date_str: str | None = None

    # Pattern: "what time in X" or "time in X"
    loc_patterns = [
        r"(?:what\s+)?time\s+(?:in|at|is\s+it\s+in)\s+([^?.,]+)",
        r"timezone\s+(?:of|for|in)\s+([^?.,]+)",
        r"(?:local\s+)?time\s+(?:at|for)\s+([^?.,]+)",
    ]

    for pattern in loc_patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            location = match.group(1).strip()
            break

    # Try to extract date from message
    date_patterns = [
        r"(?:on|for|during)\s+(\d{4}-\d{2}-\d{2})",
        r"(?:on|for)\s+((?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:,?\s*\d{4})?)",
    ]

    for pattern in date_patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            date_str = match.group(1).strip()
            break

    # Use context as fallbacks
    if not location and destination:
        location = destination

    # Try to extract date from trip_dates if not in message
    if not date_str and trip_dates:
        # Take the start date from trip dates
        trip_date_match = re.match(r"(\d{4}-\d{2}-\d{2})", trip_dates)
        if trip_date_match:
            date_str = trip_date_match.group(1)

    # Validate we have enough information
    if not location:
        return "Please specify a location for timezone info (e.g., 'what time is it in Tokyo')."

    # Perform lookup
    try:
        result = timezone_info(location, date_str)
        return result.formatted
    except InvalidTimezoneLocationError as e:
        return f"Timezone lookup error: {e.message}. Try a major city like Tokyo, Paris, or New York."
    except InvalidDateError as e:
        return f"Invalid date: {e.message}. Try formats like '2026-03-15' or 'March 15, 2026'."


# =============================================================================
# MODULE EXPORTS
# =============================================================================

# Supported locations for validation
SUPPORTED_TIMEZONE_LOCATIONS: frozenset[str] = frozenset(LOCATION_TIMEZONES.keys())

__all__ = [
    "SUPPORTED_TIMEZONE_LOCATIONS",
    "TimezoneData",
    "TimezoneInfo",
    "InvalidTimezoneLocationError",
    "InvalidDateError",
    "timezone_info",
    "timezone_info_with_context",
    "normalize_timezone_location",
    "parse_date_string",
    "is_dst_active",
    "format_utc_offset",
]
