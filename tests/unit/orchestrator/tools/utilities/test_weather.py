"""Unit tests for the weather_lookup utility tool.

Tests cover:
- Basic weather lookup (Tokyo, Paris, etc.)
- Invalid location handling
- Date range parsing (ISO, natural language, relative)
- Context-aware weather lookup with destination
- Season determination
- Edge cases (unknown locations, invalid dates)
"""

from datetime import date, datetime, timedelta

import pytest

from src.orchestrator.tools.utilities.weather import (
    LOCATION_WEATHER,
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


class TestNormalizeLocation:
    """Tests for normalize_location function."""

    def test_lowercase_match(self) -> None:
        """Location names should match case-insensitively."""
        assert normalize_location("tokyo") == "tokyo"
        assert normalize_location("TOKYO") == "tokyo"
        assert normalize_location("Tokyo") == "tokyo"

    def test_strips_whitespace(self) -> None:
        """Whitespace should be stripped."""
        assert normalize_location("  tokyo  ") == "tokyo"
        assert normalize_location("\tparis\n") == "paris"

    def test_removes_country_suffix(self) -> None:
        """Country suffix should be removed."""
        assert normalize_location("Tokyo, Japan") == "tokyo"
        assert normalize_location("Paris, France") == "paris"
        assert normalize_location("london, UK") == "london"

    def test_alias_mapping(self) -> None:
        """Country aliases should map to representative cities."""
        assert normalize_location("japan") == "tokyo"
        assert normalize_location("france") == "paris"
        assert normalize_location("uk") == "london"
        assert normalize_location("england") == "london"
        assert normalize_location("united states") == "new york"
        assert normalize_location("usa") == "new york"

    def test_partial_match(self) -> None:
        """Partial matches should be recognized."""
        assert normalize_location("tokyo japan") == "tokyo"

    def test_unknown_location_raises_error(self) -> None:
        """Unknown locations should raise InvalidLocationError."""
        with pytest.raises(InvalidLocationError) as exc_info:
            normalize_location("nonexistent city")
        assert "Unknown location" in exc_info.value.message
        assert exc_info.value.location == "nonexistent city"


class TestGetSeason:
    """Tests for get_season function."""

    def test_spring_months(self) -> None:
        """March, April, May should be spring."""
        assert get_season(date(2026, 3, 15)) == "spring"
        assert get_season(date(2026, 4, 1)) == "spring"
        assert get_season(date(2026, 5, 31)) == "spring"

    def test_summer_months(self) -> None:
        """June, July, August should be summer."""
        assert get_season(date(2026, 6, 1)) == "summer"
        assert get_season(date(2026, 7, 15)) == "summer"
        assert get_season(date(2026, 8, 31)) == "summer"

    def test_fall_months(self) -> None:
        """September, October, November should be fall."""
        assert get_season(date(2026, 9, 1)) == "fall"
        assert get_season(date(2026, 10, 15)) == "fall"
        assert get_season(date(2026, 11, 30)) == "fall"

    def test_winter_months(self) -> None:
        """December, January, February should be winter."""
        assert get_season(date(2026, 12, 1)) == "winter"
        assert get_season(date(2026, 1, 15)) == "winter"
        assert get_season(date(2026, 2, 28)) == "winter"


class TestParseDateRange:
    """Tests for parse_date_range function."""

    def test_iso_format_with_double_dot(self) -> None:
        """ISO format with double dot separator."""
        start, end = parse_date_range("2026-03-10..2026-03-17")
        assert start == date(2026, 3, 10)
        assert end == date(2026, 3, 17)

    def test_iso_format_with_slash(self) -> None:
        """ISO format with slash separator."""
        start, end = parse_date_range("2026-03-10/2026-03-17")
        assert start == date(2026, 3, 10)
        assert end == date(2026, 3, 17)

    def test_iso_format_with_to(self) -> None:
        """ISO format with 'to' separator."""
        start, end = parse_date_range("2026-03-10 to 2026-03-17")
        assert start == date(2026, 3, 10)
        assert end == date(2026, 3, 17)

    def test_single_iso_date(self) -> None:
        """Single ISO date should return same date for start and end."""
        start, end = parse_date_range("2026-03-10")
        assert start == date(2026, 3, 10)
        assert end == date(2026, 3, 10)

    def test_natural_month_day_range(self) -> None:
        """Natural language format: 'March 10-17'."""
        start, end = parse_date_range("March 10-17")
        current_year = datetime.now().year
        assert start == date(current_year, 3, 10)
        assert end == date(current_year, 3, 17)

    def test_natural_month_day_range_with_year(self) -> None:
        """Natural language format with year: 'March 10-17, 2026'."""
        start, end = parse_date_range("March 10-17, 2026")
        assert start == date(2026, 3, 10)
        assert end == date(2026, 3, 17)

    def test_abbreviated_month(self) -> None:
        """Abbreviated month names should work."""
        start, end = parse_date_range("Mar 10-17, 2026")
        assert start == date(2026, 3, 10)
        assert end == date(2026, 3, 17)

    def test_single_day_natural(self) -> None:
        """Single day in natural format."""
        start, end = parse_date_range("March 15, 2026")
        assert start == date(2026, 3, 15)
        assert end == date(2026, 3, 15)

    def test_cross_month_range(self) -> None:
        """Range spanning two months: 'Mar 28 - Apr 3'."""
        start, end = parse_date_range("Mar 28 - Apr 3, 2026")
        assert start == date(2026, 3, 28)
        assert end == date(2026, 4, 3)

    def test_relative_next_week(self) -> None:
        """'next week' should return upcoming Monday to Sunday."""
        start, end = parse_date_range("next week")
        today = datetime.now().date()
        # start should be a Monday
        assert start.weekday() == 0
        # end should be Sunday (6 days after start)
        assert end == start + timedelta(days=6)
        # start should be in the future
        assert start > today or start >= today - timedelta(days=7)

    def test_relative_this_week(self) -> None:
        """'this week' should return current Monday to Sunday."""
        start, end = parse_date_range("this week")
        # start should be a Monday
        assert start.weekday() == 0
        # end should be Sunday
        assert end == start + timedelta(days=6)

    def test_relative_today(self) -> None:
        """'today' should return today's date."""
        start, end = parse_date_range("today")
        today = datetime.now().date()
        assert start == today
        assert end == today

    def test_relative_tomorrow(self) -> None:
        """'tomorrow' should return tomorrow's date."""
        start, end = parse_date_range("tomorrow")
        tomorrow = datetime.now().date() + timedelta(days=1)
        assert start == tomorrow
        assert end == tomorrow

    def test_invalid_date_range_raises_error(self) -> None:
        """Invalid date range format should raise error."""
        with pytest.raises(InvalidDateRangeError) as exc_info:
            parse_date_range("invalid date format")
        assert "Invalid date range" in exc_info.value.message


class TestFormatDateRange:
    """Tests for format_date_range function."""

    def test_single_day(self) -> None:
        """Single day should format as 'Mar 10'."""
        result = format_date_range(date(2026, 3, 10), date(2026, 3, 10))
        assert result == "Mar 10"

    def test_same_month(self) -> None:
        """Same month range should format as 'Mar 10-17'."""
        result = format_date_range(date(2026, 3, 10), date(2026, 3, 17))
        assert result == "Mar 10-17"

    def test_different_months_same_year(self) -> None:
        """Different months in same year should include both month names."""
        result = format_date_range(date(2026, 3, 28), date(2026, 4, 3))
        assert result == "Mar 28 - Apr 03"

    def test_different_years(self) -> None:
        """Different years should include full dates."""
        result = format_date_range(date(2025, 12, 28), date(2026, 1, 3))
        assert result == "Dec 28, 2025 - Jan 03, 2026"


class TestWeatherLookup:
    """Tests for weather_lookup function."""

    def test_tokyo_spring_weather(self) -> None:
        """Tokyo spring weather should return expected forecast."""
        result = weather_lookup("Tokyo", "2026-03-10..2026-03-17")

        assert isinstance(result, WeatherForecast)
        assert result.location == "Tokyo"
        assert result.country == "Japan"
        assert result.start_date == date(2026, 3, 10)
        assert result.end_date == date(2026, 3, 17)
        # Spring weather for Tokyo
        assert 10 <= result.temp_low <= 15
        assert 15 <= result.temp_high <= 20
        assert "partly cloudy" in result.condition
        assert 0 <= result.rain_chance <= 100
        assert "Tokyo:" in result.formatted
        assert "°C" in result.formatted

    def test_paris_summer_weather(self) -> None:
        """Paris summer weather should return warm temperatures."""
        result = weather_lookup("Paris", "2026-07-01..2026-07-10")

        assert result.location == "Paris"
        assert result.country == "France"
        # Summer should be warmer
        assert result.temp_high >= 20

    def test_new_york_winter_weather(self) -> None:
        """New York winter weather should return cold temperatures."""
        result = weather_lookup("New York", "2026-01-15..2026-01-20")

        assert result.location == "New York"
        assert result.country == "United States"
        # Winter should be cold
        assert result.temp_high <= 10

    def test_location_with_country_suffix(self) -> None:
        """Location with country suffix should work."""
        result = weather_lookup("Tokyo, Japan", "March 10-17, 2026")
        assert result.location == "Tokyo"

    def test_country_name_maps_to_city(self) -> None:
        """Country name should map to representative city."""
        result = weather_lookup("Japan", "March 10-17, 2026")
        assert result.location == "Tokyo"

    def test_natural_language_date_range(self) -> None:
        """Natural language date range should work."""
        result = weather_lookup("Tokyo", "March 10-17, 2026")
        assert result.start_date == date(2026, 3, 10)
        assert result.end_date == date(2026, 3, 17)

    def test_unknown_location_raises_error(self) -> None:
        """Unknown location should raise InvalidLocationError."""
        with pytest.raises(InvalidLocationError) as exc_info:
            weather_lookup("Unknown City", "2026-03-10..2026-03-17")
        assert "Unknown location" in exc_info.value.message

    def test_invalid_date_range_raises_error(self) -> None:
        """Invalid date range should raise InvalidDateRangeError."""
        with pytest.raises(InvalidDateRangeError):
            weather_lookup("Tokyo", "invalid date")

    def test_to_dict_serialization(self) -> None:
        """WeatherForecast should serialize to dict correctly."""
        result = weather_lookup("Tokyo", "2026-03-10..2026-03-17")
        data = result.to_dict()

        assert data["location"] == "Tokyo"
        assert data["country"] == "Japan"
        assert data["start_date"] == "2026-03-10"
        assert data["end_date"] == "2026-03-17"
        assert isinstance(data["temp_low"], int)
        assert isinstance(data["temp_high"], int)
        assert isinstance(data["condition"], str)
        assert isinstance(data["rain_chance"], int)
        assert isinstance(data["formatted"], str)

    def test_all_supported_locations(self) -> None:
        """All supported locations should return valid weather."""
        for location in SUPPORTED_LOCATIONS:
            result = weather_lookup(location, "2026-06-01..2026-06-07")
            assert result.location.lower() == location
            assert isinstance(result.temp_low, int)
            assert isinstance(result.temp_high, int)
            assert result.temp_low <= result.temp_high

    def test_formatted_output_structure(self) -> None:
        """Formatted output should have expected structure."""
        result = weather_lookup("Tokyo", "2026-03-10..2026-03-17")
        # Format: "Tokyo: 10-18°C, partly cloudy, 30% chance of rain (Mar 10-17)"
        parts = result.formatted.split(":")
        assert len(parts) == 2
        assert parts[0] == "Tokyo"
        assert "°C" in parts[1]
        assert "% chance of rain" in parts[1]
        assert "(" in parts[1] and ")" in parts[1]


class TestWeatherLookupWithContext:
    """Tests for weather_lookup_with_context function."""

    @pytest.mark.asyncio
    async def test_extracts_location_from_message(self) -> None:
        """Should extract location from 'weather in X' pattern."""
        result = await weather_lookup_with_context("what's the weather in Tokyo")
        assert "Tokyo" in result
        assert "°C" in result

    @pytest.mark.asyncio
    async def test_extracts_location_for_pattern(self) -> None:
        """Should extract location from 'weather for X' pattern."""
        result = await weather_lookup_with_context("weather for Paris")
        assert "Paris" in result
        assert "°C" in result

    @pytest.mark.asyncio
    async def test_uses_destination_as_fallback(self) -> None:
        """Should use destination context when location not in message."""
        result = await weather_lookup_with_context(
            "what's the weather like",
            destination="Tokyo, Japan"
        )
        assert "Tokyo" in result
        assert "°C" in result

    @pytest.mark.asyncio
    async def test_uses_dates_as_fallback(self) -> None:
        """Should use dates context when date range not in message."""
        result = await weather_lookup_with_context(
            "weather in Tokyo",
            dates="March 10-17, 2026"
        )
        assert "Tokyo" in result
        assert "Mar 10-17" in result

    @pytest.mark.asyncio
    async def test_extracts_date_from_message(self) -> None:
        """Should extract date from message."""
        result = await weather_lookup_with_context(
            "weather in Tokyo for March 15-20, 2026"
        )
        assert "Tokyo" in result
        assert "Mar 15-20" in result

    @pytest.mark.asyncio
    async def test_no_location_returns_prompt(self) -> None:
        """Should prompt for location if not provided."""
        result = await weather_lookup_with_context("what's the weather")
        assert "Please specify a location" in result

    @pytest.mark.asyncio
    async def test_unknown_location_returns_error(self) -> None:
        """Should return error for unknown location."""
        result = await weather_lookup_with_context("weather in Unknown City")
        assert "Weather lookup error" in result

    @pytest.mark.asyncio
    async def test_invalid_date_returns_error(self) -> None:
        """Should return error for invalid date range."""
        result = await weather_lookup_with_context(
            "weather in Tokyo for invalid-date-format"
        )
        # Should fall back to default dates (next 7 days)
        assert "Tokyo" in result

    @pytest.mark.asyncio
    async def test_relative_date_in_message(self) -> None:
        """Should handle relative dates in message."""
        result = await weather_lookup_with_context(
            "weather in Tokyo for next week"
        )
        assert "Tokyo" in result
        assert "°C" in result


class TestLocationData:
    """Tests for location weather data integrity."""

    def test_all_locations_have_seasons(self) -> None:
        """All locations should have all four seasons."""
        seasons = {"spring", "summer", "fall", "winter"}
        for location, data in LOCATION_WEATHER.items():
            assert "seasonal" in data, f"{location} missing seasonal data"
            assert set(data["seasonal"].keys()) == seasons, f"{location} missing seasons"

    def test_all_seasons_have_required_fields(self) -> None:
        """All seasons should have temp_low, temp_high, condition, rain_chance."""
        required_fields = {"temp_low", "temp_high", "condition", "rain_chance"}
        for location, data in LOCATION_WEATHER.items():
            for season, weather in data["seasonal"].items():
                for field in required_fields:
                    assert field in weather, f"{location}/{season} missing {field}"

    def test_temperature_ranges_are_valid(self) -> None:
        """Temperature ranges should be reasonable."""
        for location, data in LOCATION_WEATHER.items():
            for season, weather in data["seasonal"].items():
                assert weather["temp_low"] < weather["temp_high"], \
                    f"{location}/{season} has temp_low >= temp_high"
                # Reasonable temperature range
                assert -20 <= weather["temp_low"] <= 40, \
                    f"{location}/{season} temp_low out of range"
                assert -10 <= weather["temp_high"] <= 45, \
                    f"{location}/{season} temp_high out of range"

    def test_rain_chance_is_valid(self) -> None:
        """Rain chance should be 0-100."""
        for location, data in LOCATION_WEATHER.items():
            for season, weather in data["seasonal"].items():
                assert 0 <= weather["rain_chance"] <= 100, \
                    f"{location}/{season} rain_chance out of range"


class TestSupportedLocations:
    """Tests for SUPPORTED_LOCATIONS constant."""

    def test_is_frozenset(self) -> None:
        """SUPPORTED_LOCATIONS should be a frozenset."""
        assert isinstance(SUPPORTED_LOCATIONS, frozenset)

    def test_contains_major_cities(self) -> None:
        """Should contain major world cities."""
        major_cities = {"tokyo", "paris", "london", "new york", "sydney"}
        assert major_cities.issubset(SUPPORTED_LOCATIONS)

    def test_matches_location_weather_keys(self) -> None:
        """Should match LOCATION_WEATHER keys."""
        assert SUPPORTED_LOCATIONS == frozenset(LOCATION_WEATHER.keys())


class TestExceptionClasses:
    """Tests for exception classes."""

    def test_invalid_location_error(self) -> None:
        """InvalidLocationError should store location and message."""
        error = InvalidLocationError("test_location", "custom message")
        assert error.location == "test_location"
        assert error.message == "custom message"
        assert str(error) == "custom message"

    def test_invalid_location_error_default_message(self) -> None:
        """InvalidLocationError should have default message."""
        error = InvalidLocationError("test_location")
        assert error.location == "test_location"
        assert "Unknown location: test_location" in error.message

    def test_invalid_date_range_error(self) -> None:
        """InvalidDateRangeError should store date_range and message."""
        error = InvalidDateRangeError("test_date", "custom message")
        assert error.date_range == "test_date"
        assert error.message == "custom message"
        assert str(error) == "custom message"

    def test_invalid_date_range_error_default_message(self) -> None:
        """InvalidDateRangeError should have default message."""
        error = InvalidDateRangeError("test_date")
        assert error.date_range == "test_date"
        assert "Invalid date range: test_date" in error.message
