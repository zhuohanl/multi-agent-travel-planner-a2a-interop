"""
Orchestrator tool handlers for Azure AI Agent Service.

This module contains tool handlers that are called by the Azure AI Agent Service
when the LLM decides to invoke a tool. The tools are registered with pre-provisioned
Azure AI agents during deployment.

Tools:
    - workflow_turn: Stateful trip-planning workflow handler (ONLY tool that mutates state)
    - answer_question: Answers travel questions (stateless, optional context)
    - currency_convert: Currency conversion utility (stateless)
    - weather_lookup: Weather forecast utility (stateless)
    - timezone_info: Timezone information utility (stateless)
    - get_booking: Lookup tool for booking details (stateless)
    - get_consultation: Lookup tool for consultation details (stateless)

Architecture:
    - workflow_turn is the SINGLE source of state mutations
    - All other tools are stateless and read-only
    - Tools return ToolResponse envelopes for consistent client handling
"""

from src.orchestrator.tools.answer_question import (
    DOMAIN_AGENTS,
    VALID_DOMAINS,
    answer_question,
    build_qa_request,
)
from src.orchestrator.tools.lookups import (
    BookingNotFoundError,
    ConsultationNotFoundError,
    format_booking_details,
    format_consultation_details,
    get_booking,
    get_consultation,
)
from src.orchestrator.tools.utilities import (
    SUPPORTED_CURRENCIES,
    SUPPORTED_LOCATIONS,
    SUPPORTED_TIMEZONE_LOCATIONS,
    CurrencyConvertResult,
    InvalidCurrencyError,
    InvalidDateError,
    InvalidDateRangeError,
    InvalidLocationError,
    InvalidTimezoneLocationError,
    TimezoneData,
    TimezoneInfo,
    WeatherForecast,
    currency_convert,
    currency_convert_with_context,
    format_currency_amount,
    format_utc_offset,
    get_exchange_rate,
    is_dst_active,
    normalize_timezone_location,
    parse_date_string,
    timezone_info,
    timezone_info_with_context,
    weather_lookup,
    weather_lookup_with_context,
)
from src.orchestrator.tools.utility_intent import (
    UTILITY_PATTERNS,
    UtilityMatch,
    extract_utility_intent,
    is_utility_message,
)
from src.orchestrator.tools.workflow_turn import (
    ToolResponse,
    WorkflowTurnContext,
    get_workflow_turn_context,
    handle_utility_with_context,
    set_workflow_turn_context,
    workflow_turn,
    workflow_turn_with_stores,
)

__all__ = [
    # answer_question exports
    "DOMAIN_AGENTS",
    "VALID_DOMAINS",
    "answer_question",
    "build_qa_request",
    # get_booking exports
    "BookingNotFoundError",
    "format_booking_details",
    "get_booking",
    # get_consultation exports
    "ConsultationNotFoundError",
    "format_consultation_details",
    "get_consultation",
    # currency_convert exports
    "SUPPORTED_CURRENCIES",
    "CurrencyConvertResult",
    "InvalidCurrencyError",
    "currency_convert",
    "currency_convert_with_context",
    "format_currency_amount",
    "get_exchange_rate",
    # timezone_info exports
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
    # weather_lookup exports
    "SUPPORTED_LOCATIONS",
    "InvalidDateRangeError",
    "InvalidLocationError",
    "WeatherForecast",
    "weather_lookup",
    "weather_lookup_with_context",
    # utility_intent exports
    "UTILITY_PATTERNS",
    "UtilityMatch",
    "extract_utility_intent",
    "is_utility_message",
    # workflow_turn exports
    "ToolResponse",
    "WorkflowTurnContext",
    "get_workflow_turn_context",
    "handle_utility_with_context",
    "set_workflow_turn_context",
    "workflow_turn",
    "workflow_turn_with_stores",
]
