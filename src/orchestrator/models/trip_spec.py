"""TripSpec: User travel requirements from the clarification phase.

Per design doc Three-Phase Workflow section:
- TripSpec captures the user's travel requirements from Phase 1 (Clarification)
- It's the output of clarification and input to Phase 2 (Discovery)
- The is_complete() method determines when to transition from clarification to discovery

The clarifier agent gathers this information through multi-turn conversation
and returns it when all required fields are collected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class TripSpec:
    """
    User travel requirements gathered during clarification.

    This dataclass captures all requirements needed to plan a trip:
    - Core trip details (where, when, who)
    - Budget constraints
    - Personal preferences (interests, constraints)

    Per design doc:
    - All core fields are required for a valid TripSpec
    - is_complete() checks if ready to transition to Discovery phase
    - Serialization supports Cosmos DB storage

    Attributes:
        destination_city: The city the user wants to visit (e.g., "Tokyo")
        origin_city: The city the user is traveling from (e.g., "San Francisco")
        start_date: Trip start date
        end_date: Trip end date
        num_travelers: Total number of travelers (must be >= 1)
        budget_per_person: Budget amount per person
        budget_currency: Currency code (e.g., "USD", "EUR", "JPY")
        interests: List of activities/things the user wants to do
        constraints: List of constraints/preferences (dietary, accessibility, etc.)
        special_requests: Optional additional requests or notes
    """

    destination_city: str
    origin_city: str
    start_date: date
    end_date: date
    num_travelers: int
    budget_per_person: float
    budget_currency: str
    interests: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    special_requests: str | None = None

    def is_complete(self) -> bool:
        """
        Check if TripSpec has all required fields for discovery.

        Per design doc: TripSpec is complete when it has:
        - Valid destination and origin cities (non-empty strings)
        - Valid date range (start_date <= end_date, not sentinel values)
        - At least 1 traveler
        - Positive budget with valid currency

        Returns:
            True if all required fields are set and valid, False otherwise
        """
        # Check required string fields are non-empty
        if not self.destination_city or not self.destination_city.strip():
            return False
        if not self.origin_city or not self.origin_city.strip():
            return False
        if not self.budget_currency or not self.budget_currency.strip():
            return False

        # Check dates are valid (not None and not sentinel values like date.min)
        if self.start_date is None or self.end_date is None:
            return False
        if self.start_date == date.min or self.end_date == date.min:
            return False
        if self.start_date > self.end_date:
            return False

        # Check travelers and budget
        if self.num_travelers < 1:
            return False
        if self.budget_per_person <= 0:
            return False

        return True

    def validate(self) -> list[str]:
        """
        Validate TripSpec and return list of issues.

        Unlike is_complete() which returns a boolean, this method
        returns detailed validation messages for each issue found.

        Returns:
            List of validation error messages. Empty list means valid.
        """
        errors: list[str] = []

        if not self.destination_city or not self.destination_city.strip():
            errors.append("Destination city is required")
        if not self.origin_city or not self.origin_city.strip():
            errors.append("Origin city is required")
        if not self.budget_currency or not self.budget_currency.strip():
            errors.append("Budget currency is required")

        if self.start_date is None:
            errors.append("Start date is required")
        if self.end_date is None:
            errors.append("End date is required")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            errors.append("Start date must be before or equal to end date")

        if self.num_travelers < 1:
            errors.append("Number of travelers must be at least 1")
        if self.budget_per_person <= 0:
            errors.append("Budget per person must be positive")

        return errors

    @property
    def total_budget(self) -> float:
        """Calculate total trip budget (budget_per_person * num_travelers)."""
        return self.budget_per_person * self.num_travelers

    @property
    def trip_duration_days(self) -> int:
        """Calculate trip duration in days (inclusive of start and end)."""
        if self.start_date is None or self.end_date is None:
            return 0
        return (self.end_date - self.start_date).days + 1

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to dictionary for Cosmos DB storage.

        Uses snake_case keys for internal storage consistency.
        Dates are serialized as ISO format strings.

        Returns:
            Dictionary representation suitable for Cosmos DB storage
        """
        return {
            "destination_city": self.destination_city,
            "origin_city": self.origin_city,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "num_travelers": self.num_travelers,
            "budget_per_person": self.budget_per_person,
            "budget_currency": self.budget_currency,
            "interests": self.interests,
            "constraints": self.constraints,
            "special_requests": self.special_requests,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TripSpec:
        """
        Deserialize from dictionary (e.g., from Cosmos DB or clarifier response).

        Handles missing fields gracefully with sensible defaults.
        Parses date strings in ISO format.

        Args:
            data: Dictionary with TripSpec fields

        Returns:
            TripSpec instance
        """
        return cls(
            destination_city=data.get("destination_city", ""),
            origin_city=data.get("origin_city", ""),
            start_date=cls._parse_date(data.get("start_date")),
            end_date=cls._parse_date(data.get("end_date")),
            num_travelers=int(data.get("num_travelers", 0)),
            budget_per_person=float(data.get("budget_per_person", 0.0)),
            budget_currency=data.get("budget_currency", ""),
            interests=list(data.get("interests", [])),
            constraints=list(data.get("constraints", [])),
            special_requests=data.get("special_requests"),
        )

    @staticmethod
    def _parse_date(value: str | date | datetime | None) -> date:
        """
        Parse date from various input formats.

        Args:
            value: Date as string (ISO format), date, datetime, or None

        Returns:
            date object, or date.min if parsing fails
        """
        if value is None:
            return date.min
        # Check datetime before date since datetime is a subclass of date
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                # Handle ISO format (YYYY-MM-DD)
                return date.fromisoformat(value)
            except ValueError:
                pass
            try:
                # Handle datetime ISO format
                return datetime.fromisoformat(value).date()
            except ValueError:
                pass
        return date.min

    def __str__(self) -> str:
        """Human-readable summary of the trip spec."""
        return (
            f"Trip to {self.destination_city} from {self.origin_city} "
            f"({self.start_date} to {self.end_date}), "
            f"{self.num_travelers} travelers, "
            f"{self.budget_per_person} {self.budget_currency}/person"
        )
