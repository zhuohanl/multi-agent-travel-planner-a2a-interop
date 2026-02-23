"""
Weather lookup utility tool.

This module provides weather forecast lookup for a location and date range.
It can be invoked:
1. From Layer 1b via regex pattern match ("weather in Tokyo")
2. From Layer 1c via LLM fallback ("what's the weather like in Paris next week")
3. From Layer 2 via CALL_UTILITY action ("what's the weather for my trip")

Per design doc (Tool Definitions section):
- Parameters: location, date_range
- Returns formatted string like "Tokyo: 12-18°C, partly cloudy, 20% chance of rain"
- Handles date range parsing (ISO or natural language)

In production, this would use a real weather API or MCP tool.
For now, uses mock weather data for deterministic testing.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
import re


# =============================================================================
# MOCK WEATHER DATA
# =============================================================================

# Mock weather patterns by location (for deterministic testing)
# In production, these would come from a weather API (OpenWeatherMap, etc.)
# Each location has seasonal patterns with temp ranges and conditions
LOCATION_WEATHER: dict[str, dict[str, Any]] = {
    # Asia
    "tokyo": {
        "timezone": "JST",
        "country": "Japan",
        "seasonal": {
            "spring": {"temp_low": 10, "temp_high": 18, "condition": "partly cloudy", "rain_chance": 30},
            "summer": {"temp_low": 23, "temp_high": 31, "condition": "humid and sunny", "rain_chance": 40},
            "fall": {"temp_low": 14, "temp_high": 22, "condition": "clear", "rain_chance": 25},
            "winter": {"temp_low": 2, "temp_high": 10, "condition": "cold and clear", "rain_chance": 20},
        },
    },
    "osaka": {
        "timezone": "JST",
        "country": "Japan",
        "seasonal": {
            "spring": {"temp_low": 11, "temp_high": 19, "condition": "partly cloudy", "rain_chance": 30},
            "summer": {"temp_low": 24, "temp_high": 33, "condition": "hot and humid", "rain_chance": 35},
            "fall": {"temp_low": 15, "temp_high": 23, "condition": "clear", "rain_chance": 25},
            "winter": {"temp_low": 3, "temp_high": 10, "condition": "cold and cloudy", "rain_chance": 25},
        },
    },
    "kyoto": {
        "timezone": "JST",
        "country": "Japan",
        "seasonal": {
            "spring": {"temp_low": 9, "temp_high": 18, "condition": "cherry blossom season", "rain_chance": 28},
            "summer": {"temp_low": 23, "temp_high": 34, "condition": "hot and humid", "rain_chance": 38},
            "fall": {"temp_low": 13, "temp_high": 22, "condition": "autumn foliage", "rain_chance": 22},
            "winter": {"temp_low": 1, "temp_high": 9, "condition": "cold", "rain_chance": 30},
        },
    },
    "seoul": {
        "timezone": "KST",
        "country": "South Korea",
        "seasonal": {
            "spring": {"temp_low": 6, "temp_high": 17, "condition": "mild and breezy", "rain_chance": 25},
            "summer": {"temp_low": 22, "temp_high": 30, "condition": "monsoon season", "rain_chance": 60},
            "fall": {"temp_low": 10, "temp_high": 20, "condition": "clear and crisp", "rain_chance": 20},
            "winter": {"temp_low": -6, "temp_high": 3, "condition": "cold and dry", "rain_chance": 15},
        },
    },
    "bangkok": {
        "timezone": "ICT",
        "country": "Thailand",
        "seasonal": {
            "spring": {"temp_low": 26, "temp_high": 35, "condition": "hot", "rain_chance": 20},
            "summer": {"temp_low": 25, "temp_high": 33, "condition": "rainy season", "rain_chance": 70},
            "fall": {"temp_low": 24, "temp_high": 32, "condition": "rainy", "rain_chance": 50},
            "winter": {"temp_low": 22, "temp_high": 32, "condition": "cool and dry", "rain_chance": 10},
        },
    },
    "singapore": {
        "timezone": "SGT",
        "country": "Singapore",
        "seasonal": {
            "spring": {"temp_low": 25, "temp_high": 32, "condition": "tropical", "rain_chance": 45},
            "summer": {"temp_low": 25, "temp_high": 32, "condition": "tropical", "rain_chance": 40},
            "fall": {"temp_low": 24, "temp_high": 31, "condition": "monsoon approaching", "rain_chance": 55},
            "winter": {"temp_low": 24, "temp_high": 31, "condition": "northeast monsoon", "rain_chance": 60},
        },
    },
    "beijing": {
        "timezone": "CST",
        "country": "China",
        "seasonal": {
            "spring": {"temp_low": 8, "temp_high": 22, "condition": "dusty and dry", "rain_chance": 20},
            "summer": {"temp_low": 22, "temp_high": 32, "condition": "hot and humid", "rain_chance": 50},
            "fall": {"temp_low": 10, "temp_high": 20, "condition": "clear and pleasant", "rain_chance": 15},
            "winter": {"temp_low": -8, "temp_high": 3, "condition": "cold and dry", "rain_chance": 10},
        },
    },
    "shanghai": {
        "timezone": "CST",
        "country": "China",
        "seasonal": {
            "spring": {"temp_low": 12, "temp_high": 22, "condition": "mild and rainy", "rain_chance": 45},
            "summer": {"temp_low": 25, "temp_high": 34, "condition": "hot and humid", "rain_chance": 55},
            "fall": {"temp_low": 16, "temp_high": 24, "condition": "pleasant", "rain_chance": 30},
            "winter": {"temp_low": 2, "temp_high": 10, "condition": "cold and damp", "rain_chance": 35},
        },
    },
    "hong kong": {
        "timezone": "HKT",
        "country": "Hong Kong",
        "seasonal": {
            "spring": {"temp_low": 20, "temp_high": 26, "condition": "humid and foggy", "rain_chance": 50},
            "summer": {"temp_low": 26, "temp_high": 32, "condition": "typhoon season", "rain_chance": 60},
            "fall": {"temp_low": 23, "temp_high": 29, "condition": "pleasant", "rain_chance": 30},
            "winter": {"temp_low": 14, "temp_high": 20, "condition": "cool and dry", "rain_chance": 25},
        },
    },
    # Europe
    "paris": {
        "timezone": "CET",
        "country": "France",
        "seasonal": {
            "spring": {"temp_low": 8, "temp_high": 16, "condition": "mild with showers", "rain_chance": 40},
            "summer": {"temp_low": 15, "temp_high": 25, "condition": "warm and pleasant", "rain_chance": 25},
            "fall": {"temp_low": 9, "temp_high": 16, "condition": "cool and rainy", "rain_chance": 45},
            "winter": {"temp_low": 2, "temp_high": 8, "condition": "cold and grey", "rain_chance": 40},
        },
    },
    "london": {
        "timezone": "GMT",
        "country": "United Kingdom",
        "seasonal": {
            "spring": {"temp_low": 7, "temp_high": 14, "condition": "mild with showers", "rain_chance": 45},
            "summer": {"temp_low": 13, "temp_high": 22, "condition": "warm and variable", "rain_chance": 35},
            "fall": {"temp_low": 8, "temp_high": 15, "condition": "cool and rainy", "rain_chance": 50},
            "winter": {"temp_low": 3, "temp_high": 8, "condition": "cold and damp", "rain_chance": 45},
        },
    },
    "rome": {
        "timezone": "CET",
        "country": "Italy",
        "seasonal": {
            "spring": {"temp_low": 11, "temp_high": 20, "condition": "warm and sunny", "rain_chance": 30},
            "summer": {"temp_low": 20, "temp_high": 32, "condition": "hot and sunny", "rain_chance": 15},
            "fall": {"temp_low": 13, "temp_high": 22, "condition": "pleasant", "rain_chance": 40},
            "winter": {"temp_low": 5, "temp_high": 13, "condition": "mild and rainy", "rain_chance": 45},
        },
    },
    "barcelona": {
        "timezone": "CET",
        "country": "Spain",
        "seasonal": {
            "spring": {"temp_low": 12, "temp_high": 20, "condition": "pleasant", "rain_chance": 30},
            "summer": {"temp_low": 22, "temp_high": 30, "condition": "hot and sunny", "rain_chance": 15},
            "fall": {"temp_low": 14, "temp_high": 22, "condition": "mild", "rain_chance": 35},
            "winter": {"temp_low": 7, "temp_high": 14, "condition": "cool", "rain_chance": 30},
        },
    },
    "berlin": {
        "timezone": "CET",
        "country": "Germany",
        "seasonal": {
            "spring": {"temp_low": 5, "temp_high": 15, "condition": "cool and variable", "rain_chance": 35},
            "summer": {"temp_low": 14, "temp_high": 25, "condition": "warm and pleasant", "rain_chance": 40},
            "fall": {"temp_low": 7, "temp_high": 14, "condition": "cool and rainy", "rain_chance": 45},
            "winter": {"temp_low": -2, "temp_high": 4, "condition": "cold and snowy", "rain_chance": 40},
        },
    },
    "amsterdam": {
        "timezone": "CET",
        "country": "Netherlands",
        "seasonal": {
            "spring": {"temp_low": 6, "temp_high": 14, "condition": "mild and windy", "rain_chance": 45},
            "summer": {"temp_low": 13, "temp_high": 22, "condition": "pleasant", "rain_chance": 40},
            "fall": {"temp_low": 8, "temp_high": 14, "condition": "cool and rainy", "rain_chance": 55},
            "winter": {"temp_low": 1, "temp_high": 6, "condition": "cold and wet", "rain_chance": 50},
        },
    },
    # Americas
    "new york": {
        "timezone": "EST",
        "country": "United States",
        "seasonal": {
            "spring": {"temp_low": 8, "temp_high": 18, "condition": "mild and variable", "rain_chance": 40},
            "summer": {"temp_low": 20, "temp_high": 30, "condition": "hot and humid", "rain_chance": 35},
            "fall": {"temp_low": 10, "temp_high": 20, "condition": "cool and crisp", "rain_chance": 30},
            "winter": {"temp_low": -3, "temp_high": 5, "condition": "cold and snowy", "rain_chance": 35},
        },
    },
    "los angeles": {
        "timezone": "PST",
        "country": "United States",
        "seasonal": {
            "spring": {"temp_low": 13, "temp_high": 22, "condition": "sunny and mild", "rain_chance": 15},
            "summer": {"temp_low": 17, "temp_high": 28, "condition": "hot and dry", "rain_chance": 5},
            "fall": {"temp_low": 15, "temp_high": 26, "condition": "warm and sunny", "rain_chance": 10},
            "winter": {"temp_low": 10, "temp_high": 19, "condition": "mild with occasional rain", "rain_chance": 25},
        },
    },
    "san francisco": {
        "timezone": "PST",
        "country": "United States",
        "seasonal": {
            "spring": {"temp_low": 10, "temp_high": 17, "condition": "foggy mornings", "rain_chance": 25},
            "summer": {"temp_low": 13, "temp_high": 20, "condition": "foggy and cool", "rain_chance": 5},
            "fall": {"temp_low": 13, "temp_high": 22, "condition": "Indian summer", "rain_chance": 15},
            "winter": {"temp_low": 8, "temp_high": 14, "condition": "cool and rainy", "rain_chance": 45},
        },
    },
    "toronto": {
        "timezone": "EST",
        "country": "Canada",
        "seasonal": {
            "spring": {"temp_low": 3, "temp_high": 14, "condition": "variable", "rain_chance": 40},
            "summer": {"temp_low": 17, "temp_high": 27, "condition": "warm and humid", "rain_chance": 35},
            "fall": {"temp_low": 6, "temp_high": 15, "condition": "cool and colorful", "rain_chance": 40},
            "winter": {"temp_low": -10, "temp_high": -2, "condition": "cold and snowy", "rain_chance": 35},
        },
    },
    "vancouver": {
        "timezone": "PST",
        "country": "Canada",
        "seasonal": {
            "spring": {"temp_low": 7, "temp_high": 15, "condition": "mild and rainy", "rain_chance": 50},
            "summer": {"temp_low": 14, "temp_high": 23, "condition": "warm and dry", "rain_chance": 20},
            "fall": {"temp_low": 8, "temp_high": 14, "condition": "cool and rainy", "rain_chance": 55},
            "winter": {"temp_low": 2, "temp_high": 8, "condition": "mild and wet", "rain_chance": 60},
        },
    },
    "mexico city": {
        "timezone": "CST",
        "country": "Mexico",
        "seasonal": {
            "spring": {"temp_low": 12, "temp_high": 26, "condition": "dry and warm", "rain_chance": 15},
            "summer": {"temp_low": 14, "temp_high": 24, "condition": "rainy afternoons", "rain_chance": 65},
            "fall": {"temp_low": 12, "temp_high": 23, "condition": "rainy", "rain_chance": 50},
            "winter": {"temp_low": 7, "temp_high": 22, "condition": "dry and mild", "rain_chance": 10},
        },
    },
    # Oceania
    "sydney": {
        "timezone": "AEST",
        "country": "Australia",
        "seasonal": {
            "spring": {"temp_low": 14, "temp_high": 22, "condition": "warm and sunny", "rain_chance": 30},
            "summer": {"temp_low": 20, "temp_high": 28, "condition": "hot and humid", "rain_chance": 35},
            "fall": {"temp_low": 15, "temp_high": 23, "condition": "mild", "rain_chance": 35},
            "winter": {"temp_low": 9, "temp_high": 17, "condition": "cool", "rain_chance": 30},
        },
    },
    "melbourne": {
        "timezone": "AEST",
        "country": "Australia",
        "seasonal": {
            "spring": {"temp_low": 10, "temp_high": 19, "condition": "variable", "rain_chance": 40},
            "summer": {"temp_low": 15, "temp_high": 26, "condition": "hot with cool changes", "rain_chance": 25},
            "fall": {"temp_low": 12, "temp_high": 20, "condition": "mild", "rain_chance": 35},
            "winter": {"temp_low": 7, "temp_high": 14, "condition": "cool and wet", "rain_chance": 45},
        },
    },
    "auckland": {
        "timezone": "NZST",
        "country": "New Zealand",
        "seasonal": {
            "spring": {"temp_low": 11, "temp_high": 17, "condition": "mild and showery", "rain_chance": 45},
            "summer": {"temp_low": 16, "temp_high": 24, "condition": "warm and humid", "rain_chance": 30},
            "fall": {"temp_low": 13, "temp_high": 20, "condition": "mild", "rain_chance": 40},
            "winter": {"temp_low": 8, "temp_high": 14, "condition": "cool and wet", "rain_chance": 50},
        },
    },
}

# Aliases for location lookup
LOCATION_ALIASES: dict[str, str] = {
    "japan": "tokyo",
    "korea": "seoul",
    "south korea": "seoul",
    "thailand": "bangkok",
    "china": "beijing",
    "france": "paris",
    "uk": "london",
    "united kingdom": "london",
    "england": "london",
    "italy": "rome",
    "spain": "barcelona",
    "germany": "berlin",
    "netherlands": "amsterdam",
    "holland": "amsterdam",
    "usa": "new york",
    "us": "new york",
    "united states": "new york",
    "america": "new york",
    "canada": "toronto",
    "mexico": "mexico city",
    "australia": "sydney",
    "new zealand": "auckland",
}


# =============================================================================
# EXCEPTIONS
# =============================================================================


class InvalidLocationError(ValueError):
    """Raised when an invalid or unsupported location is provided."""

    def __init__(self, location: str, message: str | None = None) -> None:
        self.location = location
        self.message = message or f"Unknown location: {location}"
        super().__init__(self.message)


class InvalidDateRangeError(ValueError):
    """Raised when an invalid date range is provided."""

    def __init__(self, date_range: str, message: str | None = None) -> None:
        self.date_range = date_range
        self.message = message or f"Invalid date range: {date_range}"
        super().__init__(self.message)


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass(frozen=True)
class WeatherForecast:
    """Result of a weather lookup operation."""

    location: str
    country: str
    start_date: date
    end_date: date
    temp_low: int
    temp_high: int
    condition: str
    rain_chance: int
    formatted: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "location": self.location,
            "country": self.country,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "temp_low": self.temp_low,
            "temp_high": self.temp_high,
            "condition": self.condition,
            "rain_chance": self.rain_chance,
            "formatted": self.formatted,
        }


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def normalize_location(location: str) -> str:
    """Normalize a location string for lookup.

    Args:
        location: Location name (any case, may include country)

    Returns:
        Normalized location key for LOCATION_WEATHER lookup

    Raises:
        InvalidLocationError: If the location is not recognized
    """
    # Clean and lowercase
    normalized = location.strip().lower()

    # Remove common suffixes like ", Japan" or ", France"
    if "," in normalized:
        normalized = normalized.split(",")[0].strip()

    # Check direct match
    if normalized in LOCATION_WEATHER:
        return normalized

    # Check aliases
    if normalized in LOCATION_ALIASES:
        return LOCATION_ALIASES[normalized]

    # Check for partial matches (e.g., "tokyo japan" -> "tokyo")
    for loc_key in LOCATION_WEATHER:
        if loc_key in normalized or normalized in loc_key:
            return loc_key

    # Check alias partial matches
    for alias, loc_key in LOCATION_ALIASES.items():
        if alias in normalized or normalized in alias:
            return loc_key

    raise InvalidLocationError(location)


def get_season(d: date) -> str:
    """Get the season for a given date (Northern Hemisphere).

    Args:
        d: Date to check

    Returns:
        Season name: "spring", "summer", "fall", or "winter"
    """
    month = d.month
    if month in (3, 4, 5):
        return "spring"
    elif month in (6, 7, 8):
        return "summer"
    elif month in (9, 10, 11):
        return "fall"
    else:
        return "winter"


def parse_date_range(date_range: str) -> tuple[date, date]:
    """Parse a date range string into start and end dates.

    Accepts formats:
    - ISO: "2026-03-10..2026-03-17" or "2026-03-10/2026-03-17" or "2026-03-10 to 2026-03-17"
    - Natural: "March 10-17" or "March 10-17, 2026" or "Mar 10 - Mar 17"
    - Relative: "next week", "this weekend"

    Args:
        date_range: Date range string

    Returns:
        Tuple of (start_date, end_date)

    Raises:
        InvalidDateRangeError: If the date range cannot be parsed
    """
    # Clean the input
    cleaned = date_range.strip()

    # Try ISO format with various separators
    iso_patterns = [
        r"(\d{4}-\d{2}-\d{2})(?:\.\.|/| to | - )(\d{4}-\d{2}-\d{2})",  # Full ISO dates
        r"(\d{4}-\d{2}-\d{2})",  # Single ISO date
    ]

    for pattern in iso_patterns:
        match = re.match(pattern, cleaned)
        if match:
            groups = match.groups()
            try:
                start = datetime.strptime(groups[0], "%Y-%m-%d").date()
                if len(groups) > 1 and groups[1]:
                    end = datetime.strptime(groups[1], "%Y-%m-%d").date()
                else:
                    # Single date - assume 1 day
                    end = start
                return (start, end)
            except ValueError:
                pass

    # Try natural language month formats
    # "March 10-17" or "March 10-17, 2026" or "Mar 10-17"
    month_names = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }

    # Pattern: "Mar 10 - Mar 17" or "March 10 - April 3" or "Mar 28 - Apr 3, 2026"
    # This pattern MUST be checked BEFORE the simpler single-month pattern
    # The year may appear after the start day, or after the end day, or both
    range_pattern = r"([A-Za-z]+)\s+(\d{1,2})(?:,?\s*(\d{4}))?\s*[-–]\s*([A-Za-z]+)\s+(\d{1,2})(?:,?\s*(\d{4}))?"
    match = re.match(range_pattern, cleaned, re.IGNORECASE)
    if match:
        start_month_str, start_day, start_year_str, end_month_str, end_day, end_year_str = match.groups()
        start_month_lower = start_month_str.lower()
        end_month_lower = end_month_str.lower()

        if start_month_lower in month_names and end_month_lower in month_names:
            start_month = month_names[start_month_lower]
            end_month = month_names[end_month_lower]
            current_year = datetime.now().year

            # Year can be on start, end, or both - use whichever is available
            if end_year_str:
                end_year = int(end_year_str)
                start_year = int(start_year_str) if start_year_str else end_year
            elif start_year_str:
                start_year = int(start_year_str)
                end_year = start_year
            else:
                start_year = current_year
                end_year = current_year

            try:
                start = date(start_year, start_month, int(start_day))
                end = date(end_year, end_month, int(end_day))
                return (start, end)
            except ValueError:
                pass

    # Pattern: "March 10-17" or "March 10-17, 2026" (single month, day range)
    natural_pattern = r"([A-Za-z]+)\s+(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?(?:,?\s*(\d{4}))?"
    match = re.match(natural_pattern, cleaned, re.IGNORECASE)
    if match:
        month_str, start_day, end_day, year_str = match.groups()
        month_lower = month_str.lower()

        if month_lower in month_names:
            month = month_names[month_lower]
            year = int(year_str) if year_str else datetime.now().year
            start_day_int = int(start_day)
            end_day_int = int(end_day) if end_day else start_day_int

            try:
                start = date(year, month, start_day_int)
                end = date(year, month, end_day_int)
                # Handle month boundary (e.g., "March 28 - 3" means March 28 to April 3)
                if end < start:
                    # Assume end is in next month
                    next_month = month + 1 if month < 12 else 1
                    next_year = year if month < 12 else year + 1
                    end = date(next_year, next_month, end_day_int)
                return (start, end)
            except ValueError:
                pass

    # Handle relative dates
    today = datetime.now().date()
    cleaned_lower = cleaned.lower()

    if "next week" in cleaned_lower:
        # Next Monday to Sunday
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        start = today + timedelta(days=days_until_monday)
        end = start + timedelta(days=6)
        return (start, end)

    if "this week" in cleaned_lower:
        # This week's Monday to Sunday
        days_since_monday = today.weekday()
        start = today - timedelta(days=days_since_monday)
        end = start + timedelta(days=6)
        return (start, end)

    if "this weekend" in cleaned_lower or "weekend" in cleaned_lower:
        # This Saturday and Sunday
        days_until_saturday = (5 - today.weekday()) % 7
        if days_until_saturday == 0 and today.weekday() > 5:
            days_until_saturday = 7
        start = today + timedelta(days=days_until_saturday)
        end = start + timedelta(days=1)
        return (start, end)

    if "tomorrow" in cleaned_lower:
        tomorrow = today + timedelta(days=1)
        return (tomorrow, tomorrow)

    if "today" in cleaned_lower:
        return (today, today)

    raise InvalidDateRangeError(date_range)


def format_date_range(start: date, end: date) -> str:
    """Format a date range for display.

    Args:
        start: Start date
        end: End date

    Returns:
        Formatted string like "Mar 10-17" or "Mar 10 - Apr 3"
    """
    if start == end:
        return start.strftime("%b %d")

    if start.month == end.month and start.year == end.year:
        return f"{start.strftime('%b %d')}-{end.day}"

    if start.year == end.year:
        return f"{start.strftime('%b %d')} - {end.strftime('%b %d')}"

    return f"{start.strftime('%b %d, %Y')} - {end.strftime('%b %d, %Y')}"


# =============================================================================
# MAIN FUNCTIONS
# =============================================================================


def weather_lookup(location: str, date_range: str) -> WeatherForecast:
    """Look up weather forecast for a location and date range.

    This is the main weather lookup function, used for stateless queries
    from Layer 1b (regex) and Layer 1c (LLM fallback).

    Args:
        location: Location name (city, region, or country)
        date_range: Date range (e.g., '2026-03-10..2026-03-17' or 'March 10-17')

    Returns:
        WeatherForecast with weather details and formatted string

    Raises:
        InvalidLocationError: If the location is not recognized
        InvalidDateRangeError: If the date range cannot be parsed

    Example:
        >>> result = weather_lookup("Tokyo", "2026-03-10..2026-03-17")
        >>> result.formatted
        'Tokyo: 12-18°C, partly cloudy, 30% chance of rain (Mar 10-17)'
    """
    # Normalize location
    loc_key = normalize_location(location)
    loc_data = LOCATION_WEATHER[loc_key]

    # Parse date range
    start_date, end_date = parse_date_range(date_range)

    # Get season for the start date (could be smarter for ranges spanning seasons)
    season = get_season(start_date)
    weather = loc_data["seasonal"][season]

    # Build formatted output
    temp_low = weather["temp_low"]
    temp_high = weather["temp_high"]
    condition = weather["condition"]
    rain_chance = weather["rain_chance"]

    # Capitalize location name for display
    display_location = loc_key.title()
    date_str = format_date_range(start_date, end_date)

    formatted = f"{display_location}: {temp_low}-{temp_high}°C, {condition}, {rain_chance}% chance of rain ({date_str})"

    return WeatherForecast(
        location=display_location,
        country=loc_data["country"],
        start_date=start_date,
        end_date=end_date,
        temp_low=temp_low,
        temp_high=temp_high,
        condition=condition,
        rain_chance=rain_chance,
        formatted=formatted,
    )


async def weather_lookup_with_context(
    message: str,
    destination: str | None = None,
    dates: str | None = None,
) -> str:
    """Look up weather with optional context from workflow.

    This function is called from Layer 2 (inside workflow_turn) when
    the user asks about weather during trip planning. It can use
    the trip destination and dates as defaults.

    Args:
        message: The user's raw message (e.g., "what's the weather like")
        destination: Optional trip destination for default location
        dates: Optional trip dates for default date range

    Returns:
        Formatted weather forecast string

    Example:
        >>> await weather_lookup_with_context("what's the weather", destination="Tokyo, Japan", dates="March 10-17, 2026")
        'Tokyo: 12-18°C, partly cloudy, 30% chance of rain (Mar 10-17)'
    """
    # Try to extract location from message
    location: str | None = None
    date_range: str | None = None

    # Pattern: "weather in/for X"
    loc_patterns = [
        r"weather\s+(?:in|for|at)\s+([^?.,]+)",
        r"what(?:'s| is) the weather (?:like )?(?:in|for|at)\s+([^?.,]+)",
    ]

    for pattern in loc_patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            location = match.group(1).strip()
            break

    # Try to extract date from message
    date_patterns = [
        r"(?:on|for|during)\s+((?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:\s*[-–]\s*\d{1,2})?(?:,?\s*\d{4})?)",
        r"(\d{4}-\d{2}-\d{2}(?:\.\.|/| to | - )\d{4}-\d{2}-\d{2})",
        r"(next week|this week|this weekend|tomorrow|today)",
    ]

    for pattern in date_patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            date_range = match.group(1).strip()
            break

    # Use context as fallbacks
    if not location and destination:
        location = destination
    if not date_range and dates:
        date_range = dates

    # Validate we have enough information
    if not location:
        return "Please specify a location for the weather forecast (e.g., 'weather in Tokyo')."

    if not date_range:
        # Default to next 7 days
        today = datetime.now().date()
        date_range = f"{today.isoformat()}..{(today + timedelta(days=6)).isoformat()}"

    # Perform lookup
    try:
        result = weather_lookup(location, date_range)
        return result.formatted
    except InvalidLocationError as e:
        return f"Weather lookup error: {e.message}. Try a major city like Tokyo, Paris, or New York."
    except InvalidDateRangeError as e:
        return f"Invalid date range: {e.message}. Try formats like 'March 10-17' or '2026-03-10..2026-03-17'."


# =============================================================================
# MODULE EXPORTS
# =============================================================================

# Supported locations for validation
SUPPORTED_LOCATIONS: frozenset[str] = frozenset(LOCATION_WEATHER.keys())

__all__ = [
    "SUPPORTED_LOCATIONS",
    "WeatherForecast",
    "InvalidLocationError",
    "InvalidDateRangeError",
    "weather_lookup",
    "weather_lookup_with_context",
    "normalize_location",
    "parse_date_range",
    "format_date_range",
    "get_season",
]
