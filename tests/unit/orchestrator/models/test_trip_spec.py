"""Unit tests for TripSpec model.

Tests cover:
- TripSpec creation and field access
- is_complete() validation logic
- validate() method returning detailed errors
- Serialization (to_dict, from_dict)
- Helper properties (total_budget, trip_duration_days)
- Edge cases and boundary conditions
"""

from datetime import date, datetime

import pytest

from src.orchestrator.models.trip_spec import TripSpec


class TestTripSpecCreation:
    """Tests for TripSpec creation and basic field access."""

    def test_trip_spec_creation_with_all_fields(self):
        """Test creating TripSpec with all fields populated."""
        trip_spec = TripSpec(
            destination_city="Tokyo",
            origin_city="San Francisco",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 17),
            num_travelers=2,
            budget_per_person=2000.0,
            budget_currency="USD",
            interests=["temples", "food", "anime"],
            constraints=["vegetarian", "no early mornings"],
            special_requests="Would like to see cherry blossoms",
        )

        assert trip_spec.destination_city == "Tokyo"
        assert trip_spec.origin_city == "San Francisco"
        assert trip_spec.start_date == date(2025, 3, 10)
        assert trip_spec.end_date == date(2025, 3, 17)
        assert trip_spec.num_travelers == 2
        assert trip_spec.budget_per_person == 2000.0
        assert trip_spec.budget_currency == "USD"
        assert trip_spec.interests == ["temples", "food", "anime"]
        assert trip_spec.constraints == ["vegetarian", "no early mornings"]
        assert trip_spec.special_requests == "Would like to see cherry blossoms"

    def test_trip_spec_creation_with_defaults(self):
        """Test creating TripSpec with minimal required fields."""
        trip_spec = TripSpec(
            destination_city="Paris",
            origin_city="London",
            start_date=date(2025, 6, 1),
            end_date=date(2025, 6, 5),
            num_travelers=1,
            budget_per_person=1500.0,
            budget_currency="EUR",
        )

        assert trip_spec.destination_city == "Paris"
        assert trip_spec.interests == []
        assert trip_spec.constraints == []
        assert trip_spec.special_requests is None


class TestIsComplete:
    """Tests for is_complete() validation method."""

    def test_trip_spec_is_complete_true(self):
        """Test is_complete returns True when all required fields are valid."""
        trip_spec = TripSpec(
            destination_city="Tokyo",
            origin_city="San Francisco",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 17),
            num_travelers=2,
            budget_per_person=2000.0,
            budget_currency="USD",
        )

        assert trip_spec.is_complete() is True

    def test_trip_spec_is_complete_false_empty_destination(self):
        """Test is_complete returns False when destination is empty."""
        trip_spec = TripSpec(
            destination_city="",
            origin_city="San Francisco",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 17),
            num_travelers=2,
            budget_per_person=2000.0,
            budget_currency="USD",
        )

        assert trip_spec.is_complete() is False

    def test_trip_spec_is_complete_false_whitespace_destination(self):
        """Test is_complete returns False when destination is whitespace."""
        trip_spec = TripSpec(
            destination_city="   ",
            origin_city="San Francisco",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 17),
            num_travelers=2,
            budget_per_person=2000.0,
            budget_currency="USD",
        )

        assert trip_spec.is_complete() is False

    def test_trip_spec_is_complete_false_empty_origin(self):
        """Test is_complete returns False when origin is empty."""
        trip_spec = TripSpec(
            destination_city="Tokyo",
            origin_city="",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 17),
            num_travelers=2,
            budget_per_person=2000.0,
            budget_currency="USD",
        )

        assert trip_spec.is_complete() is False

    def test_trip_spec_is_complete_false_invalid_date_range(self):
        """Test is_complete returns False when start_date > end_date."""
        trip_spec = TripSpec(
            destination_city="Tokyo",
            origin_city="San Francisco",
            start_date=date(2025, 3, 17),  # After end date
            end_date=date(2025, 3, 10),
            num_travelers=2,
            budget_per_person=2000.0,
            budget_currency="USD",
        )

        assert trip_spec.is_complete() is False

    def test_trip_spec_is_complete_true_same_day_trip(self):
        """Test is_complete returns True for same-day trip (start == end)."""
        trip_spec = TripSpec(
            destination_city="Tokyo",
            origin_city="San Francisco",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 10),  # Same day
            num_travelers=1,
            budget_per_person=500.0,
            budget_currency="USD",
        )

        assert trip_spec.is_complete() is True

    def test_trip_spec_is_complete_false_zero_travelers(self):
        """Test is_complete returns False when num_travelers is 0."""
        trip_spec = TripSpec(
            destination_city="Tokyo",
            origin_city="San Francisco",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 17),
            num_travelers=0,
            budget_per_person=2000.0,
            budget_currency="USD",
        )

        assert trip_spec.is_complete() is False

    def test_trip_spec_is_complete_false_negative_budget(self):
        """Test is_complete returns False when budget is negative."""
        trip_spec = TripSpec(
            destination_city="Tokyo",
            origin_city="San Francisco",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 17),
            num_travelers=2,
            budget_per_person=-100.0,
            budget_currency="USD",
        )

        assert trip_spec.is_complete() is False

    def test_trip_spec_is_complete_false_zero_budget(self):
        """Test is_complete returns False when budget is zero."""
        trip_spec = TripSpec(
            destination_city="Tokyo",
            origin_city="San Francisco",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 17),
            num_travelers=2,
            budget_per_person=0.0,
            budget_currency="USD",
        )

        assert trip_spec.is_complete() is False

    def test_trip_spec_is_complete_false_empty_currency(self):
        """Test is_complete returns False when currency is empty."""
        trip_spec = TripSpec(
            destination_city="Tokyo",
            origin_city="San Francisco",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 17),
            num_travelers=2,
            budget_per_person=2000.0,
            budget_currency="",
        )

        assert trip_spec.is_complete() is False


class TestValidate:
    """Tests for validate() method returning detailed error messages."""

    def test_validate_returns_empty_list_when_valid(self):
        """Test validate returns empty list for valid TripSpec."""
        trip_spec = TripSpec(
            destination_city="Tokyo",
            origin_city="San Francisco",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 17),
            num_travelers=2,
            budget_per_person=2000.0,
            budget_currency="USD",
        )

        errors = trip_spec.validate()
        assert errors == []

    def test_validate_returns_multiple_errors(self):
        """Test validate returns all errors when multiple fields are invalid."""
        trip_spec = TripSpec(
            destination_city="",
            origin_city="",
            start_date=date(2025, 3, 17),  # After end date
            end_date=date(2025, 3, 10),
            num_travelers=0,
            budget_per_person=-100.0,
            budget_currency="",
        )

        errors = trip_spec.validate()
        assert len(errors) >= 5
        assert "Destination city is required" in errors
        assert "Origin city is required" in errors
        assert "Start date must be before or equal to end date" in errors
        assert "Number of travelers must be at least 1" in errors
        assert "Budget per person must be positive" in errors
        assert "Budget currency is required" in errors


class TestSerialization:
    """Tests for to_dict() and from_dict() serialization methods."""

    def test_trip_spec_serialization_roundtrip(self):
        """Test serialization/deserialization roundtrip preserves data."""
        original = TripSpec(
            destination_city="Tokyo",
            origin_city="San Francisco",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 17),
            num_travelers=2,
            budget_per_person=2000.0,
            budget_currency="USD",
            interests=["temples", "food"],
            constraints=["vegetarian"],
            special_requests="Cherry blossoms please",
        )

        data = original.to_dict()
        restored = TripSpec.from_dict(data)

        assert restored.destination_city == original.destination_city
        assert restored.origin_city == original.origin_city
        assert restored.start_date == original.start_date
        assert restored.end_date == original.end_date
        assert restored.num_travelers == original.num_travelers
        assert restored.budget_per_person == original.budget_per_person
        assert restored.budget_currency == original.budget_currency
        assert restored.interests == original.interests
        assert restored.constraints == original.constraints
        assert restored.special_requests == original.special_requests

    def test_to_dict_contains_all_fields(self):
        """Test to_dict includes all fields with correct keys."""
        trip_spec = TripSpec(
            destination_city="Paris",
            origin_city="London",
            start_date=date(2025, 6, 1),
            end_date=date(2025, 6, 5),
            num_travelers=1,
            budget_per_person=1500.0,
            budget_currency="EUR",
        )

        data = trip_spec.to_dict()

        assert "destination_city" in data
        assert "origin_city" in data
        assert "start_date" in data
        assert "end_date" in data
        assert "num_travelers" in data
        assert "budget_per_person" in data
        assert "budget_currency" in data
        assert "interests" in data
        assert "constraints" in data
        assert "special_requests" in data

    def test_to_dict_dates_are_iso_strings(self):
        """Test to_dict converts dates to ISO format strings."""
        trip_spec = TripSpec(
            destination_city="Tokyo",
            origin_city="San Francisco",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 17),
            num_travelers=1,
            budget_per_person=1000.0,
            budget_currency="USD",
        )

        data = trip_spec.to_dict()

        assert data["start_date"] == "2025-03-10"
        assert data["end_date"] == "2025-03-17"

    def test_from_dict_handles_missing_fields(self):
        """Test from_dict handles missing optional fields gracefully."""
        data = {
            "destination_city": "Tokyo",
            "origin_city": "San Francisco",
            "start_date": "2025-03-10",
            "end_date": "2025-03-17",
            "num_travelers": 2,
            "budget_per_person": 2000.0,
            "budget_currency": "USD",
            # interests, constraints, special_requests missing
        }

        trip_spec = TripSpec.from_dict(data)

        assert trip_spec.destination_city == "Tokyo"
        assert trip_spec.interests == []
        assert trip_spec.constraints == []
        assert trip_spec.special_requests is None

    def test_from_dict_handles_empty_dict(self):
        """Test from_dict handles empty dictionary with defaults."""
        data = {}

        trip_spec = TripSpec.from_dict(data)

        assert trip_spec.destination_city == ""
        assert trip_spec.origin_city == ""
        assert trip_spec.start_date == date.min
        assert trip_spec.end_date == date.min
        assert trip_spec.num_travelers == 0
        assert trip_spec.budget_per_person == 0.0
        assert trip_spec.budget_currency == ""
        assert trip_spec.is_complete() is False

    def test_from_dict_parses_datetime_string(self):
        """Test from_dict parses datetime ISO strings correctly."""
        data = {
            "destination_city": "Tokyo",
            "origin_city": "San Francisco",
            "start_date": "2025-03-10T00:00:00",
            "end_date": "2025-03-17T23:59:59",
            "num_travelers": 1,
            "budget_per_person": 1000.0,
            "budget_currency": "USD",
        }

        trip_spec = TripSpec.from_dict(data)

        assert trip_spec.start_date == date(2025, 3, 10)
        assert trip_spec.end_date == date(2025, 3, 17)


class TestHelperProperties:
    """Tests for helper properties and methods."""

    def test_total_budget(self):
        """Test total_budget calculation."""
        trip_spec = TripSpec(
            destination_city="Tokyo",
            origin_city="San Francisco",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 17),
            num_travelers=3,
            budget_per_person=2000.0,
            budget_currency="USD",
        )

        assert trip_spec.total_budget == 6000.0

    def test_trip_duration_days(self):
        """Test trip_duration_days calculation (inclusive of both dates)."""
        trip_spec = TripSpec(
            destination_city="Tokyo",
            origin_city="San Francisco",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 17),
            num_travelers=1,
            budget_per_person=1000.0,
            budget_currency="USD",
        )

        # March 10 to March 17 = 8 days inclusive
        assert trip_spec.trip_duration_days == 8

    def test_trip_duration_days_same_day(self):
        """Test trip_duration_days for same-day trip."""
        trip_spec = TripSpec(
            destination_city="Tokyo",
            origin_city="San Francisco",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 10),
            num_travelers=1,
            budget_per_person=500.0,
            budget_currency="USD",
        )

        assert trip_spec.trip_duration_days == 1

    def test_str_representation(self):
        """Test string representation of TripSpec."""
        trip_spec = TripSpec(
            destination_city="Tokyo",
            origin_city="San Francisco",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 17),
            num_travelers=2,
            budget_per_person=2000.0,
            budget_currency="USD",
        )

        result = str(trip_spec)

        assert "Tokyo" in result
        assert "San Francisco" in result
        assert "2025-03-10" in result
        assert "2025-03-17" in result
        assert "2 travelers" in result
        assert "2000" in result
        assert "USD" in result


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_trip_spec_with_date_objects(self):
        """Test TripSpec handles date objects directly in from_dict."""
        data = {
            "destination_city": "Tokyo",
            "origin_city": "San Francisco",
            "start_date": date(2025, 3, 10),
            "end_date": date(2025, 3, 17),
            "num_travelers": 1,
            "budget_per_person": 1000.0,
            "budget_currency": "USD",
        }

        trip_spec = TripSpec.from_dict(data)

        assert trip_spec.start_date == date(2025, 3, 10)
        assert trip_spec.end_date == date(2025, 3, 17)

    def test_trip_spec_with_datetime_objects(self):
        """Test TripSpec handles datetime objects in from_dict."""
        data = {
            "destination_city": "Tokyo",
            "origin_city": "San Francisco",
            "start_date": datetime(2025, 3, 10, 14, 30),
            "end_date": datetime(2025, 3, 17, 18, 0),
            "num_travelers": 1,
            "budget_per_person": 1000.0,
            "budget_currency": "USD",
        }

        trip_spec = TripSpec.from_dict(data)

        assert trip_spec.start_date == date(2025, 3, 10)
        assert trip_spec.end_date == date(2025, 3, 17)

    def test_trip_spec_with_invalid_date_string(self):
        """Test TripSpec handles invalid date strings by using date.min."""
        data = {
            "destination_city": "Tokyo",
            "origin_city": "San Francisco",
            "start_date": "not-a-date",
            "end_date": "also-invalid",
            "num_travelers": 1,
            "budget_per_person": 1000.0,
            "budget_currency": "USD",
        }

        trip_spec = TripSpec.from_dict(data)

        assert trip_spec.start_date == date.min
        assert trip_spec.end_date == date.min
        assert trip_spec.is_complete() is False

    def test_trip_spec_with_very_long_interests_list(self):
        """Test TripSpec handles long lists of interests."""
        interests = [f"interest_{i}" for i in range(100)]
        trip_spec = TripSpec(
            destination_city="Tokyo",
            origin_city="San Francisco",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 17),
            num_travelers=1,
            budget_per_person=1000.0,
            budget_currency="USD",
            interests=interests,
        )

        assert len(trip_spec.interests) == 100
        data = trip_spec.to_dict()
        restored = TripSpec.from_dict(data)
        assert len(restored.interests) == 100

    def test_trip_spec_with_unicode_content(self):
        """Test TripSpec handles unicode characters in fields."""
        trip_spec = TripSpec(
            destination_city="東京",
            origin_city="サンフランシスコ",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 17),
            num_travelers=2,
            budget_per_person=200000.0,
            budget_currency="JPY",
            interests=["寺院", "日本料理", "アニメ"],
            constraints=["ベジタリアン"],
            special_requests="桜が見たいです",
        )

        assert trip_spec.destination_city == "東京"
        assert trip_spec.is_complete() is True

        data = trip_spec.to_dict()
        restored = TripSpec.from_dict(data)
        assert restored.destination_city == "東京"
        assert restored.interests == ["寺院", "日本料理", "アニメ"]
