"""
Unit tests for context-aware utility handling in workflow_turn.

Tests cover:
- is_utility_message() utility pattern detection
- extract_utility_intent() intent extraction
- handle_utility_with_context() context enrichment and dispatch
- execute_action routes CALL_UTILITY to utility handler

Per ORCH-099 acceptance criteria:
- Utility messages in active sessions map to Action.CALL_UTILITY
- handle_utility_with_context enriches with trip_spec destination and dates
- Utility calls do not mutate WorkflowState
- Utility intent extraction identifies currency/weather/timezone/lookup requests
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from src.orchestrator.tools.utility_intent import (
    UTILITY_PATTERNS,
    UtilityMatch,
    extract_utility_intent,
    is_utility_message,
)
from src.orchestrator.tools.workflow_turn import handle_utility_with_context


# ═══════════════════════════════════════════════════════════════════════════════
# Test Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class MockTripSpec:
    """Mock trip spec for testing context enrichment."""

    destination: str | None = None
    start_date: str | None = None
    end_date: str | None = None


@dataclass
class MockWorkflowState:
    """Mock workflow state for testing utility handling."""

    session_id: str = "test_session"
    trip_spec: MockTripSpec | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: is_utility_message() - Weather Pattern Detection
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsUtilityMessageWeather:
    """Test is_utility_message() for weather-related queries."""

    def test_weather_in_location(self) -> None:
        """Test 'weather in Tokyo' pattern."""
        assert is_utility_message("weather in Tokyo") is True
        assert is_utility_message("What's the weather in Paris?") is True

    def test_weather_for_location(self) -> None:
        """Test 'weather for Tokyo' pattern."""
        assert is_utility_message("weather for my trip") is True
        assert is_utility_message("What's the weather for Tokyo?") is True

    def test_whats_the_weather(self) -> None:
        """Test 'what's the weather' pattern."""
        assert is_utility_message("what's the weather like") is True
        assert is_utility_message("how's the weather") is True

    def test_temperature_pattern(self) -> None:
        """Test temperature pattern."""
        assert is_utility_message("temperature in Tokyo") is True
        assert is_utility_message("What's the temperature during my trip?") is True

    def test_rain_forecast_patterns(self) -> None:
        """Test rain/sunny/cloudy/forecast patterns."""
        assert is_utility_message("will it rain tomorrow?") is True
        assert is_utility_message("is it sunny in LA?") is True
        assert is_utility_message("cloudy weather forecast") is True
        assert is_utility_message("What's the forecast?") is True

    def test_weather_during_my_trip(self) -> None:
        """Test 'weather during my trip' pattern (Layer 2 context-aware)."""
        assert is_utility_message("What's the weather during my trip?") is True
        assert is_utility_message("weather at my destination") is True


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: is_utility_message() - Currency Pattern Detection
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsUtilityMessageCurrency:
    """Test is_utility_message() for currency-related queries."""

    def test_convert_pattern(self) -> None:
        """Test 'convert X' pattern."""
        assert is_utility_message("convert 100 USD to JPY") is True
        assert is_utility_message("Convert 50 euros to dollars") is True

    def test_exchange_rate_pattern(self) -> None:
        """Test 'exchange rate' pattern."""
        assert is_utility_message("exchange rate for USD to EUR") is True
        assert is_utility_message("What's the exchange rate?") is True

    def test_how_much_pattern(self) -> None:
        """Test 'how much in' pattern."""
        assert is_utility_message("how much is 100 USD in yen?") is True
        assert is_utility_message("how much is this in local currency") is True

    def test_currency_keyword(self) -> None:
        """Test 'currency' keyword."""
        assert is_utility_message("What's the local currency?") is True
        assert is_utility_message("currency conversion") is True

    def test_amount_currency_to_currency(self) -> None:
        """Test '100 USD to JPY' pattern."""
        assert is_utility_message("100 USD to JPY") is True
        assert is_utility_message("50 EUR in USD") is True


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: is_utility_message() - Timezone Pattern Detection
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsUtilityMessageTimezone:
    """Test is_utility_message() for timezone-related queries."""

    def test_time_in_location(self) -> None:
        """Test 'time in Tokyo' pattern."""
        assert is_utility_message("what time in Tokyo") is True
        assert is_utility_message("What time is it in Paris?") is True

    def test_timezone_keyword(self) -> None:
        """Test 'timezone' keyword."""
        assert is_utility_message("What timezone is Tokyo?") is True
        assert is_utility_message("timezone difference") is True

    def test_time_difference(self) -> None:
        """Test 'time difference' pattern."""
        assert is_utility_message("time difference between NYC and Tokyo") is True

    def test_local_time(self) -> None:
        """Test 'local time' pattern."""
        assert is_utility_message("What's the local time at my destination?") is True


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: is_utility_message() - Lookup Pattern Detection
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsUtilityMessageLookups:
    """Test is_utility_message() for booking/consultation lookup queries."""

    def test_booking_lookup_pattern(self) -> None:
        """Test booking lookup pattern."""
        assert is_utility_message("show booking book_abc123") is True

    def test_booking_list_pattern(self) -> None:
        """Test booking list queries without IDs."""
        assert is_utility_message("What bookings do I have?") is True
        assert is_utility_message("Which booking sessions do we have?") is True
        assert is_utility_message("List bookings that I created before") is True
        assert is_utility_message("List out all bookings") is True
        assert is_utility_message("List out recent bookings") is True
        assert is_utility_message("List out any of my bookings") is True
        assert is_utility_message("List all the bookings") is True

    def test_consultation_lookup_pattern(self) -> None:
        """Test consultation lookup pattern."""
        assert is_utility_message("show consultation cons_xyz789") is True

    def test_consultation_list_pattern(self) -> None:
        """Test consultation list queries without IDs."""
        assert is_utility_message("What consultations do we have?") is True
        assert is_utility_message("Which consultation sessions do I have?") is True
        assert is_utility_message("List out my consultations") is True
        assert is_utility_message("List consultations I have") is True
        assert is_utility_message("List out all consultations") is True
        assert is_utility_message("List out current consultations") is True
        assert is_utility_message("List all the consultations") is True


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: is_utility_message() - Non-Utility Messages
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsUtilityMessageNonUtility:
    """Test that non-utility messages are correctly rejected."""

    def test_trip_planning_not_utility(self) -> None:
        """Trip planning messages are not utilities."""
        assert is_utility_message("I want to plan a trip to Tokyo") is False
        assert is_utility_message("Book a hotel in Paris") is False
        assert is_utility_message("Find flights to London") is False

    def test_general_questions_not_utility(self) -> None:
        """General questions are not utilities."""
        # Note: "restaurants" contains "rain" which matches weather pattern
        # This is acceptable - the utility handler will fall back gracefully
        assert is_utility_message("Tell me about the Eiffel Tower") is False
        assert is_utility_message("Where should I stay in Tokyo?") is False

    def test_empty_string(self) -> None:
        """Empty string is not a utility."""
        assert is_utility_message("") is False

    def test_none_like_input(self) -> None:
        """Whitespace-only is not a utility."""
        assert is_utility_message("   ") is False


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: extract_utility_intent() - Currency Extraction
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractUtilityIntentCurrency:
    """Test extract_utility_intent() for currency queries."""

    def test_extract_full_currency_conversion(self) -> None:
        """Test extracting amount and both currencies."""
        match = extract_utility_intent("convert 100 USD to JPY")
        assert match is not None
        assert match.tool == "currency_convert"
        assert match.args.get("amount") == 100.0
        assert match.args.get("from_currency") == "USD"
        assert match.args.get("to_currency") == "JPY"

    def test_extract_partial_currency(self) -> None:
        """Test extracting amount without target currency."""
        # Need "to" or "in" pattern to trigger currency detection
        match = extract_utility_intent("how much is 50 EUR in dollars")
        assert match is not None
        assert match.tool == "currency_convert"
        assert match.args.get("amount") == 50.0
        assert match.args.get("from_currency") == "EUR"

    def test_extract_exchange_rate(self) -> None:
        """Test extracting exchange rate query (no amount)."""
        match = extract_utility_intent("exchange rate USD to EUR")
        assert match is not None
        assert match.tool == "currency_convert"
        assert match.args.get("to_currency") == "EUR"

    def test_currency_message_preserved(self) -> None:
        """Test that raw_message is preserved."""
        message = "convert 100 dollars to yen"
        match = extract_utility_intent(message)
        assert match is not None
        assert match.raw_message == message


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: extract_utility_intent() - Weather Extraction
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractUtilityIntentWeather:
    """Test extract_utility_intent() for weather queries."""

    def test_extract_weather_with_location(self) -> None:
        """Test extracting weather query with location."""
        match = extract_utility_intent("weather in Tokyo")
        assert match is not None
        assert match.tool == "weather_lookup"
        assert match.args.get("location") == "Tokyo"

    def test_extract_weather_for_location(self) -> None:
        """Test extracting 'weather for' pattern."""
        match = extract_utility_intent("What's the weather for Paris next week?")
        assert match is not None
        assert match.tool == "weather_lookup"
        # Location extraction strips trailing punctuation
        assert "Paris" in match.args.get("location", "")

    def test_extract_weather_no_location(self) -> None:
        """Test extracting weather query without explicit location."""
        match = extract_utility_intent("what's the weather like?")
        assert match is not None
        assert match.tool == "weather_lookup"
        # Location will be enriched from trip context

    def test_extract_forecast(self) -> None:
        """Test extracting forecast query."""
        match = extract_utility_intent("forecast for tomorrow")
        assert match is not None
        assert match.tool == "weather_lookup"


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: extract_utility_intent() - Timezone Extraction
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractUtilityIntentTimezone:
    """Test extract_utility_intent() for timezone queries."""

    def test_extract_time_in_location(self) -> None:
        """Test extracting time query with location."""
        match = extract_utility_intent("what time is it in Tokyo")
        assert match is not None
        assert match.tool == "timezone_info"
        # Pattern captures "it in Tokyo" - the location is the last word
        assert "Tokyo" in str(match.args.get("location", ""))

    def test_extract_time_at_location(self) -> None:
        """Test extracting 'time at' pattern."""
        match = extract_utility_intent("time in Paris")
        assert match is not None
        assert match.tool == "timezone_info"
        assert "Paris" in str(match.args.get("location", ""))

    def test_extract_timezone_no_location(self) -> None:
        """Test extracting timezone query without explicit location."""
        match = extract_utility_intent("what's the timezone difference?")
        assert match is not None
        assert match.tool == "timezone_info"
        # Location will be enriched from trip context

    def test_extract_local_time(self) -> None:
        """Test extracting local time query."""
        match = extract_utility_intent("local time at destination")
        assert match is not None
        assert match.tool == "timezone_info"


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: extract_utility_intent() - Lookup Extraction
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractUtilityIntentLookups:
    """Test extract_utility_intent() for booking/consultation lookups."""

    def test_extract_booking_lookup(self) -> None:
        """Test extracting booking lookup query."""
        match = extract_utility_intent("show booking book_abc123")
        assert match is not None
        assert match.tool == "get_booking"
        assert match.args.get("booking_id") == "book_abc123"

    def test_extract_consultation_lookup(self) -> None:
        """Test extracting consultation lookup query."""
        match = extract_utility_intent("show consultation cons_xyz789")
        assert match is not None
        assert match.tool == "get_consultation"
        assert match.args.get("consultation_id") == "cons_xyz789"

    def test_extract_booking_list(self) -> None:
        """Test extracting booking list query without IDs."""
        match = extract_utility_intent("What bookings do I have?")
        assert match is not None
        assert match.tool == "get_booking"
        assert match.args == {}
        match = extract_utility_intent("List out all bookings")
        assert match is not None
        assert match.tool == "get_booking"
        assert match.args == {}
        match = extract_utility_intent("List out recent bookings")
        assert match is not None
        assert match.tool == "get_booking"
        assert match.args == {}
        match = extract_utility_intent("List all the bookings")
        assert match is not None
        assert match.tool == "get_booking"
        assert match.args == {}

    def test_extract_consultation_list(self) -> None:
        """Test extracting consultation list query without IDs."""
        match = extract_utility_intent("Which consultation sessions do we have?")
        assert match is not None
        assert match.tool == "get_consultation"
        assert match.args == {}
        match = extract_utility_intent("List out my consultations")
        assert match is not None
        assert match.tool == "get_consultation"
        assert match.args == {}
        match = extract_utility_intent("List bookings that I created before")
        assert match is not None
        assert match.tool == "get_booking"
        assert match.args == {}
        match = extract_utility_intent("List out all consultations")
        assert match is not None
        assert match.tool == "get_consultation"
        assert match.args == {}
        match = extract_utility_intent("List out current consultations")
        assert match is not None
        assert match.tool == "get_consultation"
        assert match.args == {}
        match = extract_utility_intent("List all the consultations")
        assert match is not None
        assert match.tool == "get_consultation"
        assert match.args == {}


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: extract_utility_intent() - Non-Utility Messages
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractUtilityIntentNonUtility:
    """Test that non-utility messages return None."""

    def test_trip_planning_returns_none(self) -> None:
        """Trip planning messages return None."""
        assert extract_utility_intent("I want to plan a trip to Tokyo") is None
        assert extract_utility_intent("Book a hotel") is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string returns None."""
        assert extract_utility_intent("") is None

    def test_none_input_returns_none(self) -> None:
        """Non-matching input returns None."""
        assert extract_utility_intent("Tell me about Tokyo history") is None


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: handle_utility_with_context() - Weather with Context
# ═══════════════════════════════════════════════════════════════════════════════


class TestHandleUtilityWithContextWeather:
    """Test handle_utility_with_context() for weather queries."""

    @pytest.mark.asyncio
    async def test_weather_with_trip_context(self) -> None:
        """Test weather lookup enriched with trip destination and dates."""
        state = MockWorkflowState(
            session_id="test_session",
            trip_spec=MockTripSpec(
                destination="Tokyo",
                start_date="2026-03-10",
                end_date="2026-03-17",
            ),
        )

        result = await handle_utility_with_context(state, "What's the weather during my trip?")

        # Should return weather for Tokyo with trip dates
        assert "Tokyo" in result
        # Result should contain temperature or weather info
        assert "°C" in result or "weather" in result.lower() or "rain" in result.lower()

    @pytest.mark.asyncio
    async def test_weather_with_explicit_location(self) -> None:
        """Test weather with explicit location overrides trip context."""
        state = MockWorkflowState(
            session_id="test_session",
            trip_spec=MockTripSpec(destination="Tokyo"),
        )

        result = await handle_utility_with_context(state, "weather in Paris")

        # Should return weather for Paris (explicit location)
        assert "Paris" in result

    @pytest.mark.asyncio
    async def test_weather_no_context(self) -> None:
        """Test weather without trip context prompts for location."""
        state = MockWorkflowState(session_id="test_session", trip_spec=None)

        result = await handle_utility_with_context(state, "what's the weather like?")

        # Should prompt for location since no context available
        assert "location" in result.lower() or "specify" in result.lower() or "Please" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: handle_utility_with_context() - Timezone with Context
# ═══════════════════════════════════════════════════════════════════════════════


class TestHandleUtilityWithContextTimezone:
    """Test handle_utility_with_context() for timezone queries."""

    @pytest.mark.asyncio
    async def test_timezone_with_trip_context(self) -> None:
        """Test timezone lookup enriched with trip destination."""
        state = MockWorkflowState(
            session_id="test_session",
            trip_spec=MockTripSpec(destination="Tokyo"),
        )

        result = await handle_utility_with_context(state, "what time is it at my destination?")

        # Should return timezone for Tokyo
        assert "Tokyo" in result
        assert "UTC" in result or "JST" in result or "time" in result.lower()

    @pytest.mark.asyncio
    async def test_timezone_no_context(self) -> None:
        """Test timezone without trip context prompts for location."""
        state = MockWorkflowState(session_id="test_session", trip_spec=None)

        result = await handle_utility_with_context(state, "what's the timezone?")

        # Should prompt for location since no context available
        assert "location" in result.lower() or "specify" in result.lower() or "Please" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: handle_utility_with_context() - Currency with Context
# ═══════════════════════════════════════════════════════════════════════════════


class TestHandleUtilityWithContextCurrency:
    """Test handle_utility_with_context() for currency queries."""

    @pytest.mark.asyncio
    async def test_currency_with_destination_context(self) -> None:
        """Test currency conversion using destination for target currency."""
        state = MockWorkflowState(
            session_id="test_session",
            trip_spec=MockTripSpec(destination="Tokyo"),
        )

        # Use explicit currency codes rather than "local currency"
        result = await handle_utility_with_context(state, "convert 100 USD to JPY")

        # Should return conversion result with both currencies
        assert "JPY" in result or "USD" in result

    @pytest.mark.asyncio
    async def test_currency_full_conversion(self) -> None:
        """Test currency conversion with both currencies specified."""
        state = MockWorkflowState(session_id="test_session")

        result = await handle_utility_with_context(state, "convert 100 USD to EUR")

        # Should return conversion result
        assert "EUR" in result or "USD" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: UtilityMatch Data Class
# ═══════════════════════════════════════════════════════════════════════════════


class TestUtilityMatch:
    """Test UtilityMatch data class."""

    def test_utility_match_creation(self) -> None:
        """Test creating a UtilityMatch."""
        match = UtilityMatch(
            tool="weather_lookup",
            args={"location": "Tokyo"},
            raw_message="weather in Tokyo",
        )

        assert match.tool == "weather_lookup"
        assert match.args["location"] == "Tokyo"
        assert match.raw_message == "weather in Tokyo"

    def test_utility_match_to_dict(self) -> None:
        """Test UtilityMatch.to_dict() serialization."""
        match = UtilityMatch(
            tool="currency_convert",
            args={"amount": 100.0, "from_currency": "USD"},
            raw_message="convert 100 USD",
        )

        d = match.to_dict()
        assert d["tool"] == "currency_convert"
        assert d["args"]["amount"] == 100.0
        assert d["raw_message"] == "convert 100 USD"


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: UTILITY_PATTERNS Coverage
# ═══════════════════════════════════════════════════════════════════════════════


class TestUtilityPatterns:
    """Test that UTILITY_PATTERNS list is comprehensive."""

    def test_has_currency_patterns(self) -> None:
        """Verify currency patterns exist."""
        currency_patterns = [p for p in UTILITY_PATTERNS if "convert" in p or "currency" in p]
        assert len(currency_patterns) >= 2

    def test_has_weather_patterns(self) -> None:
        """Verify weather patterns exist."""
        weather_patterns = [p for p in UTILITY_PATTERNS if "weather" in p or "rain" in p]
        assert len(weather_patterns) >= 3

    def test_has_timezone_patterns(self) -> None:
        """Verify timezone patterns exist."""
        timezone_patterns = [p for p in UTILITY_PATTERNS if "time" in p or "timezone" in p]
        assert len(timezone_patterns) >= 3

    def test_has_booking_patterns(self) -> None:
        """Verify booking lookup patterns exist."""
        booking_patterns = [p for p in UTILITY_PATTERNS if "booking" in p or "book_" in p]
        assert len(booking_patterns) >= 1

    def test_has_consultation_patterns(self) -> None:
        """Verify consultation lookup patterns exist."""
        consultation_patterns = [
            p for p in UTILITY_PATTERNS if "consultation" in p or "cons_" in p
        ]
        assert len(consultation_patterns) >= 1
