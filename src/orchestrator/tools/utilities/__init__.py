"""
Utility tool handlers for the orchestrator.

These are stateless utility tools that can be called:
1. From Layer 1b (regex pattern match) - no session required
2. From Layer 1c (LLM fallback) - when regex didn't match
3. From Layer 2 (inside workflow_turn) - with trip context

Utility tools:
    - currency_convert: Currency conversion using exchange rates
    - weather_lookup: Weather forecast lookup (ORCH-061)
    - timezone_info: Timezone information (ORCH-062)

Each utility returns a formatted string response for direct display to users.
"""

from src.orchestrator.tools.utilities.currency import (
    SUPPORTED_CURRENCIES,
    CurrencyConvertResult,
    InvalidCurrencyError,
    currency_convert,
    currency_convert_with_context,
    format_currency_amount,
    get_exchange_rate,
)
from src.orchestrator.tools.utilities.timezone import (
    SUPPORTED_TIMEZONE_LOCATIONS,
    InvalidDateError,
    InvalidTimezoneLocationError,
    TimezoneData,
    TimezoneInfo,
    format_utc_offset,
    is_dst_active,
    normalize_timezone_location,
    parse_date_string,
    timezone_info,
    timezone_info_with_context,
)
from src.orchestrator.tools.utilities.weather import (
    SUPPORTED_LOCATIONS,
    InvalidDateRangeError,
    InvalidLocationError,
    WeatherForecast,
    format_date_range,
    get_season,
    normalize_location,
    parse_date_range,
    weather_lookup,
    weather_lookup_with_context,
)

__all__ = [
    # Currency
    "SUPPORTED_CURRENCIES",
    "CurrencyConvertResult",
    "InvalidCurrencyError",
    "currency_convert",
    "currency_convert_with_context",
    "format_currency_amount",
    "get_exchange_rate",
    # Timezone
    "SUPPORTED_TIMEZONE_LOCATIONS",
    "InvalidDateError",
    "InvalidTimezoneLocationError",
    "TimezoneData",
    "TimezoneInfo",
    "format_utc_offset",
    "is_dst_active",
    "normalize_timezone_location",
    "parse_date_string",
    "timezone_info",
    "timezone_info_with_context",
    # Weather
    "SUPPORTED_LOCATIONS",
    "InvalidDateRangeError",
    "InvalidLocationError",
    "WeatherForecast",
    "format_date_range",
    "get_season",
    "normalize_location",
    "parse_date_range",
    "weather_lookup",
    "weather_lookup_with_context",
]
