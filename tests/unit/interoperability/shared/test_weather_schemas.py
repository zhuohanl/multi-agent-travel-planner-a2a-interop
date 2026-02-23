"""Unit tests for WeatherRequest/WeatherResponse shared schemas.

Tests validate:
- Schema creation with valid inputs
- Schema validation rejects invalid inputs
- Serialization matches the climate summary format from Weather Agent README
- Schemas importable from both src/shared/models.py and interoperability/shared/schemas/weather.py
"""

import pytest
from pydantic import ValidationError


class TestWeatherRequest:
    """Tests for WeatherRequest schema validation."""

    def test_weather_request_valid(self):
        """Test WeatherRequest with valid inputs."""
        from src.shared.models import WeatherRequest

        request = WeatherRequest(
            location="Paris, France",
            start_date="2025-06-15",
            end_date="2025-06-20",
        )

        assert request.location == "Paris, France"
        assert request.start_date == "2025-06-15"
        assert request.end_date == "2025-06-20"

    def test_weather_request_missing_location(self):
        """Test WeatherRequest rejects missing location field."""
        from src.shared.models import WeatherRequest

        with pytest.raises(ValidationError) as exc_info:
            WeatherRequest(
                start_date="2025-06-15",
                end_date="2025-06-20",
            )
        # Verify the error mentions location
        assert "location" in str(exc_info.value)

    def test_weather_request_missing_start_date(self):
        """Test WeatherRequest rejects missing start_date field."""
        from src.shared.models import WeatherRequest

        with pytest.raises(ValidationError) as exc_info:
            WeatherRequest(
                location="Paris, France",
                end_date="2025-06-20",
            )
        assert "start_date" in str(exc_info.value)

    def test_weather_request_missing_end_date(self):
        """Test WeatherRequest rejects missing end_date field."""
        from src.shared.models import WeatherRequest

        with pytest.raises(ValidationError) as exc_info:
            WeatherRequest(
                location="Paris, France",
                start_date="2025-06-15",
            )
        assert "end_date" in str(exc_info.value)

    def test_weather_request_serialization(self):
        """Test WeatherRequest serialization."""
        from src.shared.models import WeatherRequest

        request = WeatherRequest(
            location="Paris, France",
            start_date="2025-06-15",
            end_date="2025-06-20",
        )

        # Serialize and verify format
        data = request.model_dump()
        assert data == {
            "location": "Paris, France",
            "start_date": "2025-06-15",
            "end_date": "2025-06-20",
        }


class TestClimateSummary:
    """Tests for ClimateSummary schema validation."""

    def test_climate_summary_valid(self):
        """Test ClimateSummary with valid inputs."""
        from src.shared.models import ClimateSummary

        summary = ClimateSummary(
            average_high_temp_c=24,
            average_low_temp_c=14,
            average_precipitation_chance=25,
            typical_conditions="Mostly sunny with occasional afternoon clouds",
        )

        assert summary.average_high_temp_c == 24
        assert summary.average_low_temp_c == 14
        assert summary.average_precipitation_chance == 25
        assert summary.typical_conditions == "Mostly sunny with occasional afternoon clouds"

    def test_climate_summary_precipitation_min_boundary(self):
        """Test ClimateSummary accepts 0% precipitation chance."""
        from src.shared.models import ClimateSummary

        summary = ClimateSummary(
            average_high_temp_c=30,
            average_low_temp_c=20,
            average_precipitation_chance=0,
            typical_conditions="Very dry conditions",
        )
        assert summary.average_precipitation_chance == 0

    def test_climate_summary_precipitation_max_boundary(self):
        """Test ClimateSummary accepts 100% precipitation chance."""
        from src.shared.models import ClimateSummary

        summary = ClimateSummary(
            average_high_temp_c=18,
            average_low_temp_c=15,
            average_precipitation_chance=100,
            typical_conditions="Monsoon season with daily rain",
        )
        assert summary.average_precipitation_chance == 100

    def test_climate_summary_precipitation_below_zero(self):
        """Test ClimateSummary rejects negative precipitation chance."""
        from src.shared.models import ClimateSummary

        with pytest.raises(ValidationError) as exc_info:
            ClimateSummary(
                average_high_temp_c=30,
                average_low_temp_c=20,
                average_precipitation_chance=-1,
                typical_conditions="Sunny",
            )
        assert "average_precipitation_chance" in str(exc_info.value)

    def test_climate_summary_precipitation_above_100(self):
        """Test ClimateSummary rejects precipitation chance > 100."""
        from src.shared.models import ClimateSummary

        with pytest.raises(ValidationError) as exc_info:
            ClimateSummary(
                average_high_temp_c=18,
                average_low_temp_c=15,
                average_precipitation_chance=101,
                typical_conditions="Very rainy",
            )
        assert "average_precipitation_chance" in str(exc_info.value)

    def test_climate_summary_missing_required_fields(self):
        """Test ClimateSummary requires all fields."""
        from src.shared.models import ClimateSummary

        with pytest.raises(ValidationError):
            ClimateSummary(
                average_high_temp_c=24,
                average_low_temp_c=14,
                # Missing average_precipitation_chance, typical_conditions
            )


class TestWeatherResponse:
    """Tests for WeatherResponse schema validation."""

    def test_weather_response_valid(self):
        """Test WeatherResponse with valid inputs matching README format."""
        from src.shared.models import ClimateSummary, WeatherResponse

        response = WeatherResponse(
            location="Paris, France",
            start_date="2025-06-15",
            end_date="2025-06-20",
            climate_summary=ClimateSummary(
                average_high_temp_c=24,
                average_low_temp_c=14,
                average_precipitation_chance=25,
                typical_conditions="Mostly sunny with occasional afternoon clouds",
            ),
            summary="June in Paris is typically warm and pleasant with long sunny days.",
        )

        assert response.location == "Paris, France"
        assert response.start_date == "2025-06-15"
        assert response.end_date == "2025-06-20"
        assert response.climate_summary.average_high_temp_c == 24
        assert response.summary == "June in Paris is typically warm and pleasant with long sunny days."

    def test_weather_response_serialization_matches_readme_format(self):
        """Test WeatherResponse serialization matches Weather Agent README format."""
        from src.shared.models import ClimateSummary, WeatherResponse

        response = WeatherResponse(
            location="Paris, France",
            start_date="2025-06-15",
            end_date="2025-06-20",
            climate_summary=ClimateSummary(
                average_high_temp_c=24,
                average_low_temp_c=14,
                average_precipitation_chance=25,
                typical_conditions="Mostly sunny with occasional afternoon clouds",
            ),
            summary="June in Paris is typically warm and pleasant with long sunny days.",
        )

        # Serialize and verify matches README format
        data = response.model_dump()
        expected = {
            "location": "Paris, France",
            "start_date": "2025-06-15",
            "end_date": "2025-06-20",
            "climate_summary": {
                "average_high_temp_c": 24,
                "average_low_temp_c": 14,
                "average_precipitation_chance": 25,
                "typical_conditions": "Mostly sunny with occasional afternoon clouds",
            },
            "summary": "June in Paris is typically warm and pleasant with long sunny days.",
        }
        assert data == expected

    def test_weather_response_missing_location(self):
        """Test WeatherResponse rejects missing location."""
        from src.shared.models import ClimateSummary, WeatherResponse

        with pytest.raises(ValidationError) as exc_info:
            WeatherResponse(
                start_date="2025-06-15",
                end_date="2025-06-20",
                climate_summary=ClimateSummary(
                    average_high_temp_c=24,
                    average_low_temp_c=14,
                    average_precipitation_chance=25,
                    typical_conditions="Sunny",
                ),
                summary="Nice weather.",
            )
        assert "location" in str(exc_info.value)

    def test_weather_response_missing_climate_summary(self):
        """Test WeatherResponse rejects missing climate_summary."""
        from src.shared.models import WeatherResponse

        with pytest.raises(ValidationError) as exc_info:
            WeatherResponse(
                location="Paris, France",
                start_date="2025-06-15",
                end_date="2025-06-20",
                summary="Nice weather.",
            )
        assert "climate_summary" in str(exc_info.value)

    def test_weather_response_missing_summary(self):
        """Test WeatherResponse rejects missing summary."""
        from src.shared.models import ClimateSummary, WeatherResponse

        with pytest.raises(ValidationError) as exc_info:
            WeatherResponse(
                location="Paris, France",
                start_date="2025-06-15",
                end_date="2025-06-20",
                climate_summary=ClimateSummary(
                    average_high_temp_c=24,
                    average_low_temp_c=14,
                    average_precipitation_chance=25,
                    typical_conditions="Sunny",
                ),
            )
        assert "summary" in str(exc_info.value)


class TestWeatherSchemasImportable:
    """Tests for schema importability from both locations."""

    def test_weather_schemas_importable_from_shared_models(self):
        """Test Weather schemas can be imported from src/shared/models.py."""
        from src.shared.models import WeatherRequest, ClimateSummary, WeatherResponse

        # Verify classes exist and are usable
        assert WeatherRequest is not None
        assert ClimateSummary is not None
        assert WeatherResponse is not None

        # Create instances to verify they work
        request = WeatherRequest(
            location="London, UK",
            start_date="2025-07-01",
            end_date="2025-07-05",
        )
        assert request.location == "London, UK"

    def test_weather_schemas_importable_from_interop_schemas(self):
        """Test Weather schemas can be imported from interoperability/shared/schemas/weather.py."""
        from interoperability.shared.schemas.weather import (
            WeatherRequest,
            ClimateSummary,
            WeatherResponse,
        )

        # Verify classes exist and are usable
        assert WeatherRequest is not None
        assert ClimateSummary is not None
        assert WeatherResponse is not None

        # Create instances to verify they work
        request = WeatherRequest(
            location="Berlin, Germany",
            start_date="2025-08-01",
            end_date="2025-08-10",
        )
        assert request.location == "Berlin, Germany"

    def test_weather_schemas_importable_from_schemas_package(self):
        """Test Weather schemas can be imported from interoperability.shared.schemas package."""
        from interoperability.shared.schemas import (
            WeatherRequest,
            ClimateSummary,
            WeatherResponse,
        )

        # Verify classes exist and are usable
        assert WeatherRequest is not None
        assert ClimateSummary is not None
        assert WeatherResponse is not None

    def test_schemas_are_same_class(self):
        """Test that imports from both locations return the same class."""
        from src.shared.models import WeatherRequest as SrcWeatherRequest
        from interoperability.shared.schemas.weather import (
            WeatherRequest as InteropWeatherRequest,
        )

        # Should be the exact same class (re-exported, not copied)
        assert SrcWeatherRequest is InteropWeatherRequest


class TestWeatherSchemaExtraFields:
    """Tests for extra field handling (extra='forbid')."""

    def test_weather_request_rejects_extra_fields(self):
        """Test WeatherRequest rejects unexpected fields."""
        from src.shared.models import WeatherRequest

        with pytest.raises(ValidationError) as exc_info:
            WeatherRequest(
                location="Paris, France",
                start_date="2025-06-15",
                end_date="2025-06-20",
                extra_field="not allowed",
            )
        assert "extra_field" in str(exc_info.value).lower() or "extra" in str(exc_info.value).lower()

    def test_climate_summary_rejects_extra_fields(self):
        """Test ClimateSummary rejects unexpected fields."""
        from src.shared.models import ClimateSummary

        with pytest.raises(ValidationError) as exc_info:
            ClimateSummary(
                average_high_temp_c=25,
                average_low_temp_c=18,
                average_precipitation_chance=10,
                typical_conditions="Sunny",
                humidity=50,  # Extra field not in schema
            )
        assert "humidity" in str(exc_info.value).lower() or "extra" in str(exc_info.value).lower()

    def test_weather_response_rejects_extra_fields(self):
        """Test WeatherResponse rejects unexpected fields."""
        from src.shared.models import ClimateSummary, WeatherResponse

        with pytest.raises(ValidationError) as exc_info:
            WeatherResponse(
                location="Paris, France",
                start_date="2025-06-15",
                end_date="2025-06-20",
                climate_summary=ClimateSummary(
                    average_high_temp_c=25,
                    average_low_temp_c=18,
                    average_precipitation_chance=10,
                    typical_conditions="Sunny",
                ),
                summary="Nice weather.",
                alerts=[],  # Extra field not in schema
            )
        assert "alerts" in str(exc_info.value).lower() or "extra" in str(exc_info.value).lower()
