"""Unit tests for the timezone_info utility tool.

Tests cover:
- Basic timezone lookup (Tokyo, Paris, New York, etc.)
- Invalid location handling
- Date string parsing
- DST-aware timezone lookup
- Context-aware timezone lookup with destination
- UTC offset formatting
- Edge cases (unknown locations, invalid dates)
"""

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from src.orchestrator.tools.utilities.timezone import (
    LOCATION_TIMEZONES,
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


class TestNormalizeTimezoneLocation:
    """Tests for normalize_timezone_location function."""

    def test_lowercase_match(self) -> None:
        """Location names should match case-insensitively."""
        assert normalize_timezone_location("tokyo") == "tokyo"
        assert normalize_timezone_location("TOKYO") == "tokyo"
        assert normalize_timezone_location("Tokyo") == "tokyo"

    def test_strips_whitespace(self) -> None:
        """Whitespace should be stripped."""
        assert normalize_timezone_location("  tokyo  ") == "tokyo"
        assert normalize_timezone_location("\tparis\n") == "paris"

    def test_removes_country_suffix(self) -> None:
        """Country suffix should be removed."""
        assert normalize_timezone_location("Tokyo, Japan") == "tokyo"
        assert normalize_timezone_location("Paris, France") == "paris"
        assert normalize_timezone_location("london, UK") == "london"

    def test_alias_mapping(self) -> None:
        """Country aliases should map to representative cities."""
        assert normalize_timezone_location("japan") == "tokyo"
        assert normalize_timezone_location("france") == "paris"
        assert normalize_timezone_location("uk") == "london"
        assert normalize_timezone_location("england") == "london"
        assert normalize_timezone_location("united states") == "new york"
        assert normalize_timezone_location("usa") == "new york"
        assert normalize_timezone_location("india") == "mumbai"

    def test_partial_match(self) -> None:
        """Partial matches should be recognized."""
        assert normalize_timezone_location("tokyo japan") == "tokyo"

    def test_unknown_location_raises_error(self) -> None:
        """Unknown locations should raise InvalidTimezoneLocationError."""
        with pytest.raises(InvalidTimezoneLocationError) as exc_info:
            normalize_timezone_location("nonexistent city")
        assert "Unknown location" in exc_info.value.message
        assert exc_info.value.location == "nonexistent city"


class TestParseDateString:
    """Tests for parse_date_string function."""

    def test_none_returns_none(self) -> None:
        """None input should return None."""
        assert parse_date_string(None) is None

    def test_iso_format(self) -> None:
        """ISO format dates should parse correctly."""
        result = parse_date_string("2026-03-15")
        assert result == date(2026, 3, 15)

    def test_iso_format_with_whitespace(self) -> None:
        """Whitespace should be stripped from date strings."""
        result = parse_date_string("  2026-03-15  ")
        assert result == date(2026, 3, 15)

    def test_us_format(self) -> None:
        """US format (MM/DD/YYYY) should parse correctly."""
        result = parse_date_string("03/15/2026")
        assert result == date(2026, 3, 15)

    def test_full_month_name(self) -> None:
        """Full month name format should parse correctly."""
        result = parse_date_string("March 15, 2026")
        assert result == date(2026, 3, 15)

    def test_abbreviated_month_name(self) -> None:
        """Abbreviated month name format should parse correctly."""
        result = parse_date_string("Mar 15, 2026")
        assert result == date(2026, 3, 15)

    def test_invalid_date_raises_error(self) -> None:
        """Invalid date strings should raise InvalidDateError."""
        with pytest.raises(InvalidDateError) as exc_info:
            parse_date_string("invalid date")
        assert "Invalid date" in exc_info.value.message


class TestIsDstActive:
    """Tests for is_dst_active function."""

    def test_no_dst_location(self) -> None:
        """Locations without DST should always return False."""
        tokyo = LOCATION_TIMEZONES["tokyo"]
        assert is_dst_active(tokyo, date(2026, 1, 15)) is False
        assert is_dst_active(tokyo, date(2026, 7, 15)) is False

    def test_northern_hemisphere_dst(self) -> None:
        """Northern hemisphere DST (March-November) should work correctly."""
        new_york = LOCATION_TIMEZONES["new york"]
        # Winter (January) - no DST
        assert is_dst_active(new_york, date(2026, 1, 15)) is False
        # Summer (July) - DST active
        assert is_dst_active(new_york, date(2026, 7, 15)) is True
        # Fall (December) - no DST
        assert is_dst_active(new_york, date(2026, 12, 15)) is False

    def test_european_dst(self) -> None:
        """European DST (March-October) should work correctly."""
        paris = LOCATION_TIMEZONES["paris"]
        # Winter (February) - no DST
        assert is_dst_active(paris, date(2026, 2, 15)) is False
        # Summer (June) - DST active
        assert is_dst_active(paris, date(2026, 6, 15)) is True
        # Summer (October) - DST active
        assert is_dst_active(paris, date(2026, 10, 15)) is True
        # Winter (November) - no DST
        assert is_dst_active(paris, date(2026, 11, 15)) is False

    def test_southern_hemisphere_dst(self) -> None:
        """Southern hemisphere DST (wraps year) should work correctly."""
        sydney = LOCATION_TIMEZONES["sydney"]
        # Southern summer (January) - DST active
        assert is_dst_active(sydney, date(2026, 1, 15)) is True
        # Southern winter (July) - no DST
        assert is_dst_active(sydney, date(2026, 7, 15)) is False
        # Southern summer (November) - DST active
        assert is_dst_active(sydney, date(2026, 11, 15)) is True


class TestFormatUtcOffset:
    """Tests for format_utc_offset function."""

    def test_positive_whole_hour(self) -> None:
        """Positive whole hour offsets should format correctly."""
        assert format_utc_offset(9) == "UTC+9"
        assert format_utc_offset(1) == "UTC+1"

    def test_negative_whole_hour(self) -> None:
        """Negative whole hour offsets should format correctly."""
        assert format_utc_offset(-5) == "UTC-5"
        assert format_utc_offset(-8) == "UTC-8"

    def test_zero_offset(self) -> None:
        """Zero offset should format as UTC+0."""
        assert format_utc_offset(0) == "UTC+0"

    def test_fractional_offset(self) -> None:
        """Fractional offsets (e.g., India's +5:30) should format correctly."""
        assert format_utc_offset(5.5) == "UTC+5:30"

    def test_negative_fractional_offset(self) -> None:
        """Negative fractional offsets should format correctly."""
        # Newfoundland, Canada is UTC-3:30
        assert format_utc_offset(-3.5) == "UTC-3:30"


class TestTimezoneInfo:
    """Tests for timezone_info function."""

    @patch("src.orchestrator.tools.utilities.timezone.datetime")
    def test_tokyo_timezone(self, mock_datetime: any) -> None:
        """Tokyo should return JST (UTC+9) with no DST."""
        mock_datetime.utcnow.return_value = datetime(2026, 3, 15, 5, 30, 0)
        mock_datetime.strptime = datetime.strptime

        result = timezone_info("Tokyo")
        assert result.location == "Tokyo"
        assert result.timezone_name == "JST"
        assert result.utc_offset == 9
        assert result.is_dst is False
        assert "JST" in result.formatted
        assert "UTC+9" in result.formatted

    @patch("src.orchestrator.tools.utilities.timezone.datetime")
    def test_new_york_winter(self, mock_datetime: any) -> None:
        """New York in winter should return EST (UTC-5)."""
        mock_datetime.utcnow.return_value = datetime(2026, 1, 15, 18, 0, 0)
        mock_datetime.strptime = datetime.strptime

        result = timezone_info("New York", "2026-01-15")
        assert result.location == "New York"
        assert result.timezone_name == "EST"
        assert result.utc_offset == -5
        assert result.is_dst is False

    @patch("src.orchestrator.tools.utilities.timezone.datetime")
    def test_new_york_summer(self, mock_datetime: any) -> None:
        """New York in summer should return EDT (UTC-4) due to DST."""
        mock_datetime.utcnow.return_value = datetime(2026, 7, 15, 18, 0, 0)
        mock_datetime.strptime = datetime.strptime

        result = timezone_info("New York", "2026-07-15")
        assert result.location == "New York"
        assert result.timezone_name == "EDT"
        assert result.utc_offset == -4
        assert result.is_dst is True

    @patch("src.orchestrator.tools.utilities.timezone.datetime")
    def test_paris_dst(self, mock_datetime: any) -> None:
        """Paris in summer should return CEST (UTC+2) due to DST."""
        mock_datetime.utcnow.return_value = datetime(2026, 6, 15, 12, 0, 0)
        mock_datetime.strptime = datetime.strptime

        result = timezone_info("Paris", "2026-06-15")
        assert result.location == "Paris"
        assert result.timezone_name == "CEST"
        assert result.utc_offset == 2
        assert result.is_dst is True

    @patch("src.orchestrator.tools.utilities.timezone.datetime")
    def test_london_summer(self, mock_datetime: any) -> None:
        """London in summer should return BST (UTC+1) due to DST."""
        mock_datetime.utcnow.return_value = datetime(2026, 7, 1, 12, 0, 0)
        mock_datetime.strptime = datetime.strptime

        result = timezone_info("London", "2026-07-01")
        assert result.location == "London"
        assert result.timezone_name == "BST"
        assert result.utc_offset == 1
        assert result.is_dst is True

    @patch("src.orchestrator.tools.utilities.timezone.datetime")
    def test_sydney_southern_summer(self, mock_datetime: any) -> None:
        """Sydney in January should return AEDT (UTC+11) due to DST."""
        mock_datetime.utcnow.return_value = datetime(2026, 1, 15, 3, 0, 0)
        mock_datetime.strptime = datetime.strptime

        result = timezone_info("Sydney", "2026-01-15")
        assert result.location == "Sydney"
        assert result.timezone_name == "AEDT"
        assert result.utc_offset == 11
        assert result.is_dst is True

    @patch("src.orchestrator.tools.utilities.timezone.datetime")
    def test_country_alias(self, mock_datetime: any) -> None:
        """Country aliases should work for timezone lookup."""
        mock_datetime.utcnow.return_value = datetime(2026, 3, 15, 5, 30, 0)
        mock_datetime.strptime = datetime.strptime

        result = timezone_info("Japan")
        assert result.location == "Tokyo"
        assert result.timezone_name == "JST"

    @patch("src.orchestrator.tools.utilities.timezone.datetime")
    def test_india_half_hour_offset(self, mock_datetime: any) -> None:
        """India should return IST (UTC+5:30)."""
        mock_datetime.utcnow.return_value = datetime(2026, 3, 15, 5, 30, 0)
        mock_datetime.strptime = datetime.strptime

        result = timezone_info("Mumbai")
        assert result.location == "Mumbai"
        assert result.timezone_name == "IST"
        assert result.utc_offset == 5.5
        assert "UTC+5:30" in result.formatted

    def test_invalid_location_raises_error(self) -> None:
        """Invalid location should raise InvalidTimezoneLocationError."""
        with pytest.raises(InvalidTimezoneLocationError):
            timezone_info("Nonexistent City")

    def test_invalid_date_raises_error(self) -> None:
        """Invalid date should raise InvalidDateError."""
        with pytest.raises(InvalidDateError):
            timezone_info("Tokyo", "invalid-date")

    @patch("src.orchestrator.tools.utilities.timezone.datetime")
    def test_formatted_output_includes_current_time(self, mock_datetime: any) -> None:
        """Formatted output should include current time."""
        mock_datetime.utcnow.return_value = datetime(2026, 3, 15, 5, 30, 0)
        mock_datetime.strptime = datetime.strptime

        result = timezone_info("Tokyo")
        # Tokyo is UTC+9, so 05:30 UTC = 14:30 JST
        assert "14:30" in result.formatted
        assert "Tokyo" in result.formatted


class TestTimezoneInfoWithContext:
    """Tests for timezone_info_with_context function."""

    @pytest.mark.asyncio
    @patch("src.orchestrator.tools.utilities.timezone.datetime")
    async def test_extracts_location_from_message(self, mock_datetime: any) -> None:
        """Should extract location from message."""
        mock_datetime.utcnow.return_value = datetime(2026, 3, 15, 5, 30, 0)
        mock_datetime.strptime = datetime.strptime

        result = await timezone_info_with_context("what time is it in Tokyo")
        assert "Tokyo" in result
        assert "JST" in result

    @pytest.mark.asyncio
    @patch("src.orchestrator.tools.utilities.timezone.datetime")
    async def test_uses_destination_as_fallback(self, mock_datetime: any) -> None:
        """Should use destination when location not in message."""
        mock_datetime.utcnow.return_value = datetime(2026, 3, 15, 5, 30, 0)
        mock_datetime.strptime = datetime.strptime

        result = await timezone_info_with_context(
            "what time is it there", destination="Paris, France"
        )
        assert "Paris" in result

    @pytest.mark.asyncio
    async def test_returns_error_when_no_location(self) -> None:
        """Should return error message when no location is available."""
        result = await timezone_info_with_context("what time is it")
        assert "Please specify a location" in result

    @pytest.mark.asyncio
    @patch("src.orchestrator.tools.utilities.timezone.datetime")
    async def test_extracts_date_from_message(self, mock_datetime: any) -> None:
        """Should extract date from message for DST calculation."""
        mock_datetime.utcnow.return_value = datetime(2026, 7, 15, 12, 0, 0)
        mock_datetime.strptime = datetime.strptime

        result = await timezone_info_with_context(
            "what time in New York on 2026-07-15"
        )
        # Should show EDT (DST) not EST
        assert "EDT" in result

    @pytest.mark.asyncio
    @patch("src.orchestrator.tools.utilities.timezone.datetime")
    async def test_uses_trip_dates_for_dst(self, mock_datetime: any) -> None:
        """Should use trip dates for DST calculation when available."""
        mock_datetime.utcnow.return_value = datetime(2026, 7, 15, 12, 0, 0)
        mock_datetime.strptime = datetime.strptime

        result = await timezone_info_with_context(
            "what time is it there",
            destination="New York",
            trip_dates="2026-07-15..2026-07-20",
        )
        # Should show EDT (DST) not EST
        assert "EDT" in result

    @pytest.mark.asyncio
    async def test_handles_invalid_location_gracefully(self) -> None:
        """Should return error message for invalid location."""
        result = await timezone_info_with_context(
            "what time is it in Narnia"
        )
        assert "Timezone lookup error" in result

    @pytest.mark.asyncio
    @patch("src.orchestrator.tools.utilities.timezone.datetime")
    async def test_timezone_pattern_variations(self, mock_datetime: any) -> None:
        """Should handle various timezone question patterns."""
        mock_datetime.utcnow.return_value = datetime(2026, 3, 15, 5, 30, 0)
        mock_datetime.strptime = datetime.strptime

        patterns = [
            "what time in Tokyo",
            "time in Tokyo",
            "what time is it in Tokyo",
            "timezone of Tokyo",
            "local time at Tokyo",
        ]

        for pattern in patterns:
            result = await timezone_info_with_context(pattern)
            assert "Tokyo" in result, f"Pattern failed: {pattern}"


class TestTimezoneDataConsistency:
    """Tests for timezone data consistency."""

    def test_all_locations_have_required_fields(self) -> None:
        """All locations should have required timezone fields."""
        for loc_key, tz_data in LOCATION_TIMEZONES.items():
            assert isinstance(tz_data.timezone_name, str), f"{loc_key}: missing timezone_name"
            assert isinstance(tz_data.utc_offset, (int, float)), f"{loc_key}: missing utc_offset"

    def test_dst_locations_have_complete_dst_info(self) -> None:
        """Locations with DST should have complete DST information."""
        for loc_key, tz_data in LOCATION_TIMEZONES.items():
            if tz_data.dst_offset is not None:
                assert tz_data.dst_name is not None, f"{loc_key}: has dst_offset but no dst_name"
                assert tz_data.dst_start_month is not None, f"{loc_key}: has dst_offset but no dst_start_month"
                assert tz_data.dst_end_month is not None, f"{loc_key}: has dst_offset but no dst_end_month"

    def test_supported_locations_matches_data(self) -> None:
        """SUPPORTED_TIMEZONE_LOCATIONS should match LOCATION_TIMEZONES keys."""
        assert SUPPORTED_TIMEZONE_LOCATIONS == frozenset(LOCATION_TIMEZONES.keys())

    def test_utc_offsets_are_valid(self) -> None:
        """UTC offsets should be in valid range (-12 to +14)."""
        for loc_key, tz_data in LOCATION_TIMEZONES.items():
            assert -12 <= tz_data.utc_offset <= 14, f"{loc_key}: invalid UTC offset {tz_data.utc_offset}"
            if tz_data.dst_offset is not None:
                assert -12 <= tz_data.dst_offset <= 14, f"{loc_key}: invalid DST offset {tz_data.dst_offset}"


class TestTimezoneInfoDataclass:
    """Tests for TimezoneInfo dataclass."""

    def test_to_dict_includes_all_fields(self) -> None:
        """to_dict should include all fields."""
        info = TimezoneInfo(
            location="Tokyo",
            timezone_name="JST",
            utc_offset=9,
            is_dst=False,
            current_time=datetime(2026, 3, 15, 14, 30, 0),
            formatted="Tokyo: JST (UTC+9), current time 14:30",
        )
        d = info.to_dict()
        assert d["location"] == "Tokyo"
        assert d["timezone_name"] == "JST"
        assert d["utc_offset"] == 9
        assert d["is_dst"] is False
        assert d["current_time"] == "2026-03-15T14:30:00"
        assert d["formatted"] == "Tokyo: JST (UTC+9), current time 14:30"

    def test_dataclass_is_frozen(self) -> None:
        """TimezoneInfo should be immutable."""
        info = TimezoneInfo(
            location="Tokyo",
            timezone_name="JST",
            utc_offset=9,
            is_dst=False,
            current_time=datetime(2026, 3, 15, 14, 30, 0),
            formatted="Tokyo: JST (UTC+9), current time 14:30",
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            info.location = "Paris"  # type: ignore


class TestEdgeCases:
    """Edge case tests."""

    @patch("src.orchestrator.tools.utilities.timezone.datetime")
    def test_dst_boundary_month_start(self, mock_datetime: any) -> None:
        """DST boundary at start month should be handled."""
        mock_datetime.utcnow.return_value = datetime(2026, 3, 1, 12, 0, 0)
        mock_datetime.strptime = datetime.strptime

        # March 1 is within DST range for US (March-November)
        result = timezone_info("New York", "2026-03-15")
        assert result.is_dst is True

    @patch("src.orchestrator.tools.utilities.timezone.datetime")
    def test_dst_boundary_month_end(self, mock_datetime: any) -> None:
        """DST boundary at end month should be handled."""
        mock_datetime.utcnow.return_value = datetime(2026, 11, 1, 12, 0, 0)
        mock_datetime.strptime = datetime.strptime

        # November is within DST range for US (March-November)
        result = timezone_info("New York", "2026-11-01")
        assert result.is_dst is True

    @patch("src.orchestrator.tools.utilities.timezone.datetime")
    def test_honolulu_no_dst(self, mock_datetime: any) -> None:
        """Hawaii does not observe DST."""
        mock_datetime.utcnow.return_value = datetime(2026, 7, 15, 12, 0, 0)
        mock_datetime.strptime = datetime.strptime

        result = timezone_info("Honolulu", "2026-07-15")
        assert result.timezone_name == "HST"
        assert result.utc_offset == -10
        assert result.is_dst is False

    @patch("src.orchestrator.tools.utilities.timezone.datetime")
    def test_moscow_no_dst(self, mock_datetime: any) -> None:
        """Russia does not observe DST."""
        mock_datetime.utcnow.return_value = datetime(2026, 7, 15, 12, 0, 0)
        mock_datetime.strptime = datetime.strptime

        result = timezone_info("Moscow", "2026-07-15")
        assert result.timezone_name == "MSK"
        assert result.utc_offset == 3
        assert result.is_dst is False
