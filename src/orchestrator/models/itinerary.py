"""Itinerary models for the travel planner orchestrator.

Per design doc Itinerary and Booking Data Models section:
- ItineraryDraft: Proposed travel plan, NOT yet approved
  - Stored in DiscoveryJob and WorkflowState during planning
  - Can be modified via user feedback before approval
  - Does NOT have itinerary_id (created only at approval)
- Itinerary: Approved travel plan, user-facing, shareable, immutable
  - Created ONLY when user approves the ItineraryDraft
  - Stored in itinerary_store with itinerary_id as key

Lifecycle:
1. Discovery job completes -> creates ItineraryDraft (temporary, modifiable)
2. User reviews draft at itinerary_approval checkpoint
3. User approves -> creates Itinerary with itinerary_id + booking_ids (persisted)
4. Transition to BOOKING phase
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Literal

from src.orchestrator.utils.id_generator import generate_itinerary_id


@dataclass
class TripSummary:
    """Summary of the trip destination and dates.

    A condensed view of the core trip details used in both
    ItineraryDraft and Itinerary for display purposes.

    Attributes:
        destination: The main destination city/region
        start_date: Trip start date
        end_date: Trip end date
        travelers: Number of travelers
        trip_type: Type of trip (e.g., "leisure", "business", "adventure")
    """

    destination: str
    start_date: date
    end_date: date
    travelers: int
    trip_type: str = "leisure"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for Cosmos DB storage."""
        return {
            "destination": self.destination,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "travelers": self.travelers,
            "trip_type": self.trip_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TripSummary:
        """Deserialize from dictionary."""
        return cls(
            destination=data.get("destination", ""),
            start_date=cls._parse_date(data.get("start_date")),
            end_date=cls._parse_date(data.get("end_date")),
            travelers=int(data.get("travelers", 1)),
            trip_type=data.get("trip_type", "leisure"),
        )

    @staticmethod
    def _parse_date(value: str | date | datetime | None) -> date:
        """Parse date from various input formats."""
        if value is None:
            return date.min
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                pass
            try:
                return datetime.fromisoformat(value).date()
            except ValueError:
                pass
        return date.min

    @property
    def duration_days(self) -> int:
        """Calculate trip duration in days (inclusive)."""
        if self.start_date == date.min or self.end_date == date.min:
            return 0
        return (self.end_date - self.start_date).days + 1


@dataclass
class ItineraryActivity:
    """An activity or point of interest in the itinerary.

    Represents a scheduled activity like visiting a museum,
    a guided tour, or other planned events.

    Attributes:
        name: Name of the activity
        location: Location or venue name
        description: Brief description of the activity
        start_time: Scheduled start time (optional)
        end_time: Scheduled end time (optional)
        estimated_cost: Estimated cost for the activity
        currency: Currency for the cost
        booking_required: Whether booking is needed
        notes: Additional notes or tips
    """

    name: str
    location: str
    description: str = ""
    start_time: str | None = None  # HH:MM format
    end_time: str | None = None  # HH:MM format
    estimated_cost: float = 0.0
    currency: str = "USD"
    booking_required: bool = False
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        result: dict[str, Any] = {
            "name": self.name,
            "location": self.location,
            "description": self.description,
            "estimated_cost": self.estimated_cost,
            "currency": self.currency,
            "booking_required": self.booking_required,
        }
        if self.start_time is not None:
            result["start_time"] = self.start_time
        if self.end_time is not None:
            result["end_time"] = self.end_time
        if self.notes is not None:
            result["notes"] = self.notes
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ItineraryActivity:
        """Deserialize from dictionary."""
        return cls(
            name=data.get("name", ""),
            location=data.get("location", ""),
            description=data.get("description", ""),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            estimated_cost=float(data.get("estimated_cost", 0.0)),
            currency=data.get("currency", "USD"),
            booking_required=bool(data.get("booking_required", False)),
            notes=data.get("notes"),
        )


@dataclass
class ItineraryMeal:
    """A meal recommendation in the itinerary.

    Represents a dining recommendation for a specific meal.

    Attributes:
        meal_type: Type of meal (breakfast, lunch, dinner, snack)
        restaurant_name: Name of the recommended restaurant
        cuisine: Type of cuisine
        location: Restaurant location/address
        estimated_cost: Estimated cost per person
        currency: Currency for the cost
        reservation_required: Whether reservation is recommended
        notes: Additional notes or dietary info
    """

    meal_type: Literal["breakfast", "lunch", "dinner", "snack"]
    restaurant_name: str
    cuisine: str = ""
    location: str = ""
    estimated_cost: float = 0.0
    currency: str = "USD"
    reservation_required: bool = False
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        result: dict[str, Any] = {
            "meal_type": self.meal_type,
            "restaurant_name": self.restaurant_name,
            "cuisine": self.cuisine,
            "location": self.location,
            "estimated_cost": self.estimated_cost,
            "currency": self.currency,
            "reservation_required": self.reservation_required,
        }
        if self.notes is not None:
            result["notes"] = self.notes
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ItineraryMeal:
        """Deserialize from dictionary."""
        meal_type_raw = data.get("meal_type", "lunch")
        # Validate meal_type
        valid_meal_types = {"breakfast", "lunch", "dinner", "snack"}
        meal_type = meal_type_raw if meal_type_raw in valid_meal_types else "lunch"

        return cls(
            meal_type=meal_type,  # type: ignore[arg-type]
            restaurant_name=data.get("restaurant_name", ""),
            cuisine=data.get("cuisine", ""),
            location=data.get("location", ""),
            estimated_cost=float(data.get("estimated_cost", 0.0)),
            currency=data.get("currency", "USD"),
            reservation_required=bool(data.get("reservation_required", False)),
            notes=data.get("notes"),
        )


@dataclass
class ItineraryTransport:
    """A transport segment in the itinerary.

    Represents travel between locations.

    Attributes:
        mode: Mode of transport (flight, train, bus, taxi, walking, etc.)
        from_location: Starting point
        to_location: Destination
        departure_time: Scheduled departure time
        arrival_time: Scheduled arrival time
        carrier: Carrier/operator name (airline, train company, etc.)
        booking_reference: Booking reference if booked
        estimated_cost: Estimated cost
        currency: Currency for the cost
        notes: Additional notes
    """

    mode: str  # flight, train, bus, taxi, car, walking, ferry, etc.
    from_location: str
    to_location: str
    departure_time: str | None = None  # ISO datetime string
    arrival_time: str | None = None  # ISO datetime string
    carrier: str | None = None
    booking_reference: str | None = None
    estimated_cost: float = 0.0
    currency: str = "USD"
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        result: dict[str, Any] = {
            "mode": self.mode,
            "from_location": self.from_location,
            "to_location": self.to_location,
            "estimated_cost": self.estimated_cost,
            "currency": self.currency,
        }
        if self.departure_time is not None:
            result["departure_time"] = self.departure_time
        if self.arrival_time is not None:
            result["arrival_time"] = self.arrival_time
        if self.carrier is not None:
            result["carrier"] = self.carrier
        if self.booking_reference is not None:
            result["booking_reference"] = self.booking_reference
        if self.notes is not None:
            result["notes"] = self.notes
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ItineraryTransport:
        """Deserialize from dictionary."""
        return cls(
            mode=data.get("mode", ""),
            from_location=data.get("from_location", ""),
            to_location=data.get("to_location", ""),
            departure_time=data.get("departure_time"),
            arrival_time=data.get("arrival_time"),
            carrier=data.get("carrier"),
            booking_reference=data.get("booking_reference"),
            estimated_cost=float(data.get("estimated_cost", 0.0)),
            currency=data.get("currency", "USD"),
            notes=data.get("notes"),
        )


@dataclass
class ItineraryAccommodation:
    """Accommodation details for a day or period.

    Represents where the traveler is staying.

    Attributes:
        name: Hotel/accommodation name
        location: Address or area
        check_in: Check-in date/time
        check_out: Check-out date/time
        room_type: Type of room
        estimated_cost: Total cost for the stay
        currency: Currency for the cost
        booking_reference: Booking reference if booked
        notes: Additional notes
    """

    name: str
    location: str
    check_in: str | None = None  # ISO datetime string
    check_out: str | None = None  # ISO datetime string
    room_type: str | None = None
    estimated_cost: float = 0.0
    currency: str = "USD"
    booking_reference: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        result: dict[str, Any] = {
            "name": self.name,
            "location": self.location,
            "estimated_cost": self.estimated_cost,
            "currency": self.currency,
        }
        if self.check_in is not None:
            result["check_in"] = self.check_in
        if self.check_out is not None:
            result["check_out"] = self.check_out
        if self.room_type is not None:
            result["room_type"] = self.room_type
        if self.booking_reference is not None:
            result["booking_reference"] = self.booking_reference
        if self.notes is not None:
            result["notes"] = self.notes
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ItineraryAccommodation:
        """Deserialize from dictionary."""
        return cls(
            name=data.get("name", ""),
            location=data.get("location", ""),
            check_in=data.get("check_in"),
            check_out=data.get("check_out"),
            room_type=data.get("room_type"),
            estimated_cost=float(data.get("estimated_cost", 0.0)),
            currency=data.get("currency", "USD"),
            booking_reference=data.get("booking_reference"),
            notes=data.get("notes"),
        )


@dataclass
class ItineraryDay:
    """A single day in the itinerary.

    Contains all activities, meals, transport, and accommodation
    for one day of the trip.

    Attributes:
        day_number: Day number in the trip (1-indexed)
        date: The actual date
        title: A descriptive title for the day (e.g., "Arrival & Exploring Shibuya")
        activities: List of planned activities
        meals: List of meal recommendations
        transport: List of transport segments
        accommodation: Accommodation for this day (if applicable)
        notes: Day-level notes
        estimated_daily_cost: Total estimated cost for this day
        currency: Currency for costs
    """

    day_number: int
    date: date
    title: str = ""
    activities: list[ItineraryActivity] = field(default_factory=list)
    meals: list[ItineraryMeal] = field(default_factory=list)
    transport: list[ItineraryTransport] = field(default_factory=list)
    accommodation: ItineraryAccommodation | None = None
    notes: str | None = None
    estimated_daily_cost: float = 0.0
    currency: str = "USD"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        result: dict[str, Any] = {
            "day_number": self.day_number,
            "date": self.date.isoformat(),
            "title": self.title,
            "activities": [a.to_dict() for a in self.activities],
            "meals": [m.to_dict() for m in self.meals],
            "transport": [t.to_dict() for t in self.transport],
            "estimated_daily_cost": self.estimated_daily_cost,
            "currency": self.currency,
        }
        if self.accommodation is not None:
            result["accommodation"] = self.accommodation.to_dict()
        if self.notes is not None:
            result["notes"] = self.notes
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ItineraryDay:
        """Deserialize from dictionary."""
        # Parse date
        date_value = data.get("date")
        if isinstance(date_value, str):
            try:
                parsed_date = date.fromisoformat(date_value)
            except ValueError:
                parsed_date = date.min
        elif isinstance(date_value, datetime):
            parsed_date = date_value.date()
        elif isinstance(date_value, date):
            parsed_date = date_value
        else:
            parsed_date = date.min

        # Parse accommodation
        accommodation_data = data.get("accommodation")
        accommodation = (
            ItineraryAccommodation.from_dict(accommodation_data)
            if accommodation_data
            else None
        )

        return cls(
            day_number=int(data.get("day_number", 1)),
            date=parsed_date,
            title=data.get("title", ""),
            activities=[
                ItineraryActivity.from_dict(a) for a in data.get("activities", [])
            ],
            meals=[ItineraryMeal.from_dict(m) for m in data.get("meals", [])],
            transport=[
                ItineraryTransport.from_dict(t) for t in data.get("transport", [])
            ],
            accommodation=accommodation,
            notes=data.get("notes"),
            estimated_daily_cost=float(data.get("estimated_daily_cost", 0.0)),
            currency=data.get("currency", "USD"),
        )


@dataclass
class ItineraryGap:
    """A gap in the itinerary due to partial discovery failure.

    When discovery agents fail or cannot provide results for certain
    categories, gaps are recorded to inform the user and suggest
    alternatives.

    Per design doc:
    - category: Which type of discovery failed (transport, stay, poi, etc.)
    - severity: "blocker" = can't proceed, "warning" = can proceed with gaps
    - suggestions: Alternative actions or manual options

    Attributes:
        category: The category with missing data (transport, stay, poi, events, dining)
        description: Human-readable description of what's missing
        severity: "blocker" if trip can't proceed, "warning" if can continue
        suggestions: List of suggestions to address the gap
    """

    category: str  # transport, stay, poi, events, dining
    description: str
    severity: Literal["blocker", "warning"]
    suggestions: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        result: dict[str, Any] = {
            "category": self.category,
            "description": self.description,
            "severity": self.severity,
        }
        if self.suggestions is not None:
            result["suggestions"] = self.suggestions
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ItineraryGap:
        """Deserialize from dictionary."""
        severity_raw = data.get("severity", "warning")
        # Validate severity
        severity = severity_raw if severity_raw in ("blocker", "warning") else "warning"

        return cls(
            category=data.get("category", ""),
            description=data.get("description", ""),
            severity=severity,  # type: ignore[arg-type]
            suggestions=data.get("suggestions"),
        )

    def is_blocker(self) -> bool:
        """Check if this gap prevents the trip from proceeding."""
        return self.severity == "blocker"


@dataclass
class ItineraryDraft:
    """Proposed travel plan - NOT yet approved.

    Per design doc:
    - Stored in DiscoveryJob and WorkflowState during planning
    - Can be modified via user feedback before approval
    - Does NOT have itinerary_id (created only at approval)

    When the user approves the draft, to_itinerary() creates the
    immutable Itinerary with a new itinerary_id.

    Attributes:
        consultation_id: Back-reference to planning session
        trip_summary: Destination, dates, travelers
        days: Day-by-day plan
        total_estimated_cost: Budget estimate
        gaps: Gaps from partial discovery (if any)
        created_at: When draft was created
    """

    consultation_id: str
    trip_summary: TripSummary
    days: list[ItineraryDay]
    total_estimated_cost: float
    gaps: list[ItineraryGap] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_itinerary(
        self, itinerary_id: str | None = None, booking_ids: list[str] | None = None
    ) -> Itinerary:
        """Convert draft to approved Itinerary at approval time.

        Per design doc: Creates immutable Itinerary with new IDs.

        Args:
            itinerary_id: The itinerary ID to use. If None, generates a new one.
            booking_ids: List of booking IDs. If None, uses empty list.

        Returns:
            Approved Itinerary instance
        """
        return Itinerary(
            itinerary_id=itinerary_id or generate_itinerary_id(),
            consultation_id=self.consultation_id,
            approved_at=datetime.now(timezone.utc),
            trip_summary=self.trip_summary,
            days=self.days,
            booking_ids=booking_ids or [],
            share_token=None,  # Generated on-demand
            total_estimated_cost=self.total_estimated_cost,
        )

    def has_blockers(self) -> bool:
        """Check if the draft has any blocking gaps."""
        if not self.gaps:
            return False
        return any(gap.is_blocker() for gap in self.gaps)

    def get_blockers(self) -> list[ItineraryGap]:
        """Get all blocking gaps."""
        if not self.gaps:
            return []
        return [gap for gap in self.gaps if gap.is_blocker()]

    def get_warnings(self) -> list[ItineraryGap]:
        """Get all warning gaps (non-blocking)."""
        if not self.gaps:
            return []
        return [gap for gap in self.gaps if not gap.is_blocker()]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for Cosmos DB storage."""
        result: dict[str, Any] = {
            "consultation_id": self.consultation_id,
            "trip_summary": self.trip_summary.to_dict(),
            "days": [day.to_dict() for day in self.days],
            "total_estimated_cost": self.total_estimated_cost,
            "created_at": self.created_at.isoformat(),
        }
        if self.gaps is not None:
            result["gaps"] = [gap.to_dict() for gap in self.gaps]
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ItineraryDraft:
        """Deserialize from dictionary."""
        # Parse created_at
        created_at_raw = data.get("created_at")
        if isinstance(created_at_raw, str):
            try:
                created_at = datetime.fromisoformat(created_at_raw)
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
            except ValueError:
                created_at = datetime.now(timezone.utc)
        elif isinstance(created_at_raw, datetime):
            created_at = created_at_raw
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
        else:
            created_at = datetime.now(timezone.utc)

        # Parse gaps
        gaps_data = data.get("gaps")
        gaps = [ItineraryGap.from_dict(g) for g in gaps_data] if gaps_data else None

        return cls(
            consultation_id=data.get("consultation_id", ""),
            trip_summary=TripSummary.from_dict(data.get("trip_summary", {})),
            days=[ItineraryDay.from_dict(d) for d in data.get("days", [])],
            total_estimated_cost=float(data.get("total_estimated_cost", 0.0)),
            gaps=gaps,
            created_at=created_at,
        )

    def format_for_display(self) -> str:
        """
        Format the itinerary draft for user-facing display.

        Per design doc "User-Facing Partial Results" section:
        - Shows day-by-day plan with timing
        - Highlights placeholders for missing data with [PLACEHOLDER] markers
        - Includes gaps with suggested actions
        - Shows estimated costs

        Returns:
            User-friendly text representation of the draft itinerary
        """
        lines: list[str] = []

        # Header
        lines.append("=" * 60)
        lines.append(f"ITINERARY DRAFT: {self.trip_summary.destination}")
        lines.append("=" * 60)
        lines.append("")

        # Trip summary
        lines.append(f"Destination: {self.trip_summary.destination}")
        lines.append(
            f"Dates: {self.trip_summary.start_date} to {self.trip_summary.end_date} "
            f"({self.trip_summary.duration_days} days)"
        )
        lines.append(f"Travelers: {self.trip_summary.travelers}")
        lines.append(f"Trip Type: {self.trip_summary.trip_type}")
        lines.append(f"Estimated Total Cost: ${self.total_estimated_cost:,.2f}")
        lines.append("")

        # Gaps warning
        if self.gaps:
            blockers = self.get_blockers()
            warnings = self.get_warnings()

            if blockers:
                lines.append("-" * 60)
                lines.append("BLOCKING ISSUES (must be resolved):")
                for gap in blockers:
                    lines.append(f"  [BLOCKER] {gap.category.upper()}: {gap.description}")
                    if gap.suggestions:
                        for suggestion in gap.suggestions:
                            lines.append(f"            -> {suggestion}")
                lines.append("")

            if warnings:
                lines.append("-" * 60)
                lines.append("WARNINGS (can proceed, but review recommended):")
                for gap in warnings:
                    lines.append(f"  [WARNING] {gap.category.upper()}: {gap.description}")
                    if gap.suggestions:
                        for suggestion in gap.suggestions:
                            lines.append(f"            -> {suggestion}")
                lines.append("")

        # Day-by-day plan
        lines.append("-" * 60)
        lines.append("DAY-BY-DAY ITINERARY")
        lines.append("-" * 60)

        for day in self.days:
            lines.append("")
            lines.append(f"DAY {day.day_number}: {day.title}")
            lines.append(f"Date: {day.date}")

            # Transport
            if day.transport:
                lines.append("  Transport:")
                for transport in day.transport:
                    placeholder = " [PLACEHOLDER]" if getattr(transport, "booking_reference", None) == "placeholder" else ""
                    lines.append(
                        f"    - {transport.mode.upper()}: {transport.from_location} -> {transport.to_location}{placeholder}"
                    )
                    if transport.departure_time and transport.arrival_time:
                        lines.append(f"      Departure: {transport.departure_time}, Arrival: {transport.arrival_time}")
                    elif transport.notes:
                        lines.append(f"      Note: {transport.notes}")
                    if transport.estimated_cost:
                        lines.append(f"      Cost: ${transport.estimated_cost:,.2f}")

            # Activities
            if day.activities:
                lines.append("  Activities:")
                for activity in day.activities:
                    placeholder = " [PLACEHOLDER]" if getattr(activity, "booking_required", False) and not getattr(activity, "booking_reference", None) else ""
                    lines.append(f"    - {activity.name}{placeholder}")
                    if activity.location:
                        lines.append(f"      Location: {activity.location}")
                    time_str = ""
                    if activity.start_time:
                        time_str = f"{activity.start_time}"
                        if activity.end_time:
                            time_str += f" - {activity.end_time}"
                    if time_str:
                        lines.append(f"      Time: {time_str}")
                    if activity.estimated_cost:
                        lines.append(f"      Cost: ${activity.estimated_cost:,.2f}")
                    if activity.notes:
                        lines.append(f"      Note: {activity.notes}")

            # Meals
            if day.meals:
                lines.append("  Meals:")
                for meal in day.meals:
                    lines.append(f"    - {meal.meal_type.upper()}: {meal.restaurant_name}")
                    if meal.location:
                        lines.append(f"      Location: {meal.location}")
                    if meal.cuisine:
                        lines.append(f"      Cuisine: {meal.cuisine}")
                    if meal.estimated_cost:
                        lines.append(f"      Cost: ${meal.estimated_cost:,.2f}")

            # Accommodation
            if day.accommodation:
                lines.append("  Accommodation:")
                lines.append(f"    {day.accommodation.name}")
                if day.accommodation.location:
                    lines.append(f"    Location: {day.accommodation.location}")
                if day.accommodation.check_in:
                    lines.append(f"    Check-in: {day.accommodation.check_in}")
                if day.accommodation.estimated_cost:
                    lines.append(f"    Cost: ${day.accommodation.estimated_cost:,.2f}")

            # Day notes
            if day.notes:
                lines.append(f"  Note: {day.notes}")

            # Daily cost
            if day.estimated_daily_cost:
                lines.append(f"  Daily Estimated Cost: ${day.estimated_daily_cost:,.2f}")

        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)


@dataclass
class Itinerary:
    """Approved travel plan - user-facing, shareable, immutable.

    Per design doc:
    - Created ONLY when user approves the ItineraryDraft
    - Stored in itinerary_store with itinerary_id as key
    - Immutable after creation (modifications create new itinerary)

    If a user wants to change their plans after approval, they use
    request_change to return to the ItineraryDraft stage, make
    modifications, and approve again - creating a NEW Itinerary
    with a new itinerary_id.

    Attributes:
        itinerary_id: Unique identifier (itn_xxx format)
        consultation_id: Back-reference to planning session
        approved_at: When user approved
        trip_summary: Destination, dates, travelers
        days: Day-by-day plan
        booking_ids: List of booking IDs created at approval
        share_token: For shareable links (optional)
        total_estimated_cost: Budget estimate
    """

    itinerary_id: str
    consultation_id: str
    approved_at: datetime
    trip_summary: TripSummary
    days: list[ItineraryDay]
    booking_ids: list[str]
    share_token: str | None = None
    total_estimated_cost: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for Cosmos DB storage.

        Includes TTL calculation for automatic cleanup.
        """
        # Calculate TTL: trip end + 30 days
        trip_end = self.trip_summary.end_date
        if trip_end and trip_end != date.min:
            # Convert to datetime for TTL calculation
            trip_end_dt = datetime.combine(trip_end, datetime.min.time())
            trip_end_dt = trip_end_dt.replace(tzinfo=timezone.utc)
            expiry = trip_end_dt + __import__("datetime").timedelta(days=30)
            ttl_seconds = int((expiry - datetime.now(timezone.utc)).total_seconds())
            ttl = max(ttl_seconds, 86400)  # At least 1 day
        else:
            ttl = 30 * 86400  # 30 days default

        result: dict[str, Any] = {
            "itinerary_id": self.itinerary_id,
            "id": self.itinerary_id,  # Cosmos DB document ID
            "consultation_id": self.consultation_id,
            "approved_at": self.approved_at.isoformat(),
            "trip_summary": self.trip_summary.to_dict(),
            "days": [day.to_dict() for day in self.days],
            "booking_ids": self.booking_ids,
            "total_estimated_cost": self.total_estimated_cost,
            "ttl": ttl,
        }
        if self.share_token is not None:
            result["share_token"] = self.share_token
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Itinerary:
        """Deserialize from dictionary."""
        # Parse approved_at
        approved_at_raw = data.get("approved_at")
        if isinstance(approved_at_raw, str):
            try:
                approved_at = datetime.fromisoformat(approved_at_raw)
                if approved_at.tzinfo is None:
                    approved_at = approved_at.replace(tzinfo=timezone.utc)
            except ValueError:
                approved_at = datetime.now(timezone.utc)
        elif isinstance(approved_at_raw, datetime):
            approved_at = approved_at_raw
            if approved_at.tzinfo is None:
                approved_at = approved_at.replace(tzinfo=timezone.utc)
        else:
            approved_at = datetime.now(timezone.utc)

        return cls(
            itinerary_id=data.get("itinerary_id", data.get("id", "")),
            consultation_id=data.get("consultation_id", ""),
            approved_at=approved_at,
            trip_summary=TripSummary.from_dict(data.get("trip_summary", {})),
            days=[ItineraryDay.from_dict(d) for d in data.get("days", [])],
            booking_ids=list(data.get("booking_ids", [])),
            share_token=data.get("share_token"),
            total_estimated_cost=float(data.get("total_estimated_cost", 0.0)),
        )

    @property
    def duration_days(self) -> int:
        """Get trip duration in days."""
        return self.trip_summary.duration_days

    def __str__(self) -> str:
        """Human-readable summary."""
        return (
            f"Itinerary {self.itinerary_id}: "
            f"{self.trip_summary.destination} "
            f"({self.trip_summary.start_date} to {self.trip_summary.end_date}), "
            f"{len(self.days)} days, {len(self.booking_ids)} bookings"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Factory Function: Create ItineraryDraft from Planning Pipeline Output
# ═══════════════════════════════════════════════════════════════════════════════


def create_itinerary_draft(
    planning_result: dict[str, Any],
    consultation_id: str,
    trip_spec: dict[str, Any] | None = None,
) -> ItineraryDraft:
    """
    Create an ItineraryDraft from planning pipeline output.

    Per design doc "User-Facing Partial Results" section, this function:
    - Converts the PlanningResult's itinerary dict to ItineraryDraft
    - Extracts trip summary from itinerary or trip_spec
    - Converts discovery gaps to itinerary gaps
    - Preserves validation information for display

    This is the bridge between the internal planning representation
    (PlanningResult with dict-based itinerary) and the user-facing
    ItineraryDraft model that's serializable and displayable.

    Args:
        planning_result: Output from run_planning_pipeline(), containing:
            - success: bool
            - itinerary: dict with destination, days, costs
            - validation: ValidationResult dict
            - gaps: list of DiscoveryGap dicts
        consultation_id: The consultation ID for this draft
        trip_spec: Optional trip specification with dates/destination/etc

    Returns:
        ItineraryDraft ready for user review

    Example:
        result = await run_planning_pipeline(discovery_results, trip_spec)
        if result.success:
            draft = create_itinerary_draft(
                result.to_dict(),
                consultation_id="cons_abc123",
                trip_spec=trip_spec,
            )
            display_text = draft.format_for_display()
    """
    itinerary_data = planning_result.get("itinerary") or {}
    validation_data = planning_result.get("validation") or {}
    gaps_data = planning_result.get("gaps") or []
    trip_spec = trip_spec or {}

    # Extract trip summary - prefer itinerary data, fall back to trip_spec
    destination = itinerary_data.get(
        "destination",
        trip_spec.get("destination_city", trip_spec.get("destination", "")),
    )

    start_date = _parse_date_from_any(
        itinerary_data.get("start_date", trip_spec.get("start_date"))
    )
    end_date = _parse_date_from_any(
        itinerary_data.get("end_date", trip_spec.get("end_date"))
    )

    travelers = trip_spec.get("travelers", trip_spec.get("num_travelers", 1))
    trip_type = trip_spec.get("trip_type", "leisure")

    trip_summary = TripSummary(
        destination=destination,
        start_date=start_date,
        end_date=end_date,
        travelers=travelers,
        trip_type=trip_type,
    )

    # Convert days from itinerary
    days: list[ItineraryDay] = []
    raw_days = itinerary_data.get("days", [])

    for raw_day in raw_days:
        day = _convert_day_from_pipeline(raw_day)
        days.append(day)

    # Extract total cost
    total_cost = itinerary_data.get(
        "total_estimated_cost",
        itinerary_data.get("total_cost", 0.0),
    )

    # Convert gaps from discovery gaps to itinerary gaps
    itinerary_gaps: list[ItineraryGap] | None = None
    if gaps_data:
        itinerary_gaps = []
        for gap_dict in gaps_data:
            itinerary_gap = _convert_gap_from_pipeline(gap_dict)
            itinerary_gaps.append(itinerary_gap)

    # Also convert validation gaps if present
    validation_gaps = validation_data.get("gaps", [])
    for val_gap in validation_gaps:
        itinerary_gap = _convert_validation_gap(val_gap)
        if itinerary_gaps is None:
            itinerary_gaps = []
        itinerary_gaps.append(itinerary_gap)

    return ItineraryDraft(
        consultation_id=consultation_id,
        trip_summary=trip_summary,
        days=days,
        total_estimated_cost=total_cost,
        gaps=itinerary_gaps,
    )


def _parse_date_from_any(value: Any) -> date:
    """Parse date from various formats."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return date.min


def _convert_day_from_pipeline(raw_day: dict[str, Any]) -> ItineraryDay:
    """Convert a day dict from pipeline format to ItineraryDay."""
    day_date = _parse_date_from_any(raw_day.get("date"))
    day_number = raw_day.get("day_number", 1)
    title = raw_day.get("title", f"Day {day_number}")

    # Convert activities
    activities: list[ItineraryActivity] = []
    for raw_activity in raw_day.get("activities", []):
        activity = _convert_activity_from_pipeline(raw_activity)
        activities.append(activity)

    # Convert meals
    meals: list[ItineraryMeal] = []
    for raw_meal in raw_day.get("meals", []):
        meal = _convert_meal_from_pipeline(raw_meal)
        meals.append(meal)

    # Convert transport
    transport: list[ItineraryTransport] = []
    for raw_transport in raw_day.get("transport", []):
        transport_item = _convert_transport_from_pipeline(raw_transport)
        transport.append(transport_item)

    # Convert accommodation
    accommodation = None
    raw_accommodation = raw_day.get("accommodation")
    if raw_accommodation:
        accommodation = _convert_accommodation_from_pipeline(raw_accommodation)

    # Get notes and daily cost
    notes = raw_day.get("notes", "")
    if isinstance(notes, list):
        notes = "; ".join(notes) if notes else ""
    daily_cost = raw_day.get("estimated_daily_cost", 0.0)

    return ItineraryDay(
        day_number=day_number,
        date=day_date,
        title=title,
        activities=activities,
        meals=meals,
        transport=transport,
        accommodation=accommodation,
        notes=notes,
        estimated_daily_cost=daily_cost,
    )


def _convert_activity_from_pipeline(raw: dict[str, Any]) -> ItineraryActivity:
    """Convert activity dict from pipeline format."""
    # Extract time slot info
    time_slot = raw.get("time_slot", {})
    start_time = time_slot.get("start_time", raw.get("start_time"))
    end_time = time_slot.get("end_time", raw.get("end_time"))

    is_placeholder = raw.get("is_placeholder", False)
    notes = raw.get("notes")
    if is_placeholder and not notes:
        notes = "Placeholder - booking details pending"

    return ItineraryActivity(
        name=raw.get("name", ""),
        location=raw.get("location"),
        description=raw.get("description"),
        start_time=start_time,
        end_time=end_time,
        estimated_cost=raw.get("estimated_cost"),
        currency=raw.get("currency", "USD"),
        booking_required=raw.get("booking_required", False),
        notes=notes,
    )


def _convert_meal_from_pipeline(raw: dict[str, Any]) -> ItineraryMeal:
    """Convert meal dict from pipeline format."""
    # Extract time slot info
    time_slot = raw.get("time_slot", {})
    # Not used in ItineraryMeal but extracted for potential future use

    meal_type = raw.get("meal_type", "lunch")
    if meal_type not in ("breakfast", "lunch", "dinner"):
        meal_type = "lunch"

    is_placeholder = raw.get("is_placeholder", False)
    notes = raw.get("notes")
    if is_placeholder and not notes:
        notes = "Placeholder - restaurant details pending"

    return ItineraryMeal(
        meal_type=meal_type,  # type: ignore[arg-type]
        restaurant_name=raw.get("name", raw.get("restaurant_name", "")),
        cuisine=raw.get("cuisine"),
        location=raw.get("location"),
        estimated_cost=raw.get("estimated_cost"),
        currency=raw.get("currency", "USD"),
        reservation_required=raw.get("reservation_required", False),
        notes=notes,
    )


def _convert_transport_from_pipeline(raw: dict[str, Any]) -> ItineraryTransport:
    """Convert transport dict from pipeline format."""
    # Extract time slot info
    time_slot = raw.get("time_slot", {})

    is_placeholder = raw.get("is_placeholder", False)
    notes = raw.get("notes")
    if is_placeholder and not notes:
        notes = "Placeholder - transport details to be arranged"

    # For placeholder transport, set booking_reference to "placeholder"
    booking_ref = raw.get("booking_reference")
    if is_placeholder and not booking_ref:
        booking_ref = "placeholder"

    return ItineraryTransport(
        mode=raw.get("mode", ""),
        from_location=raw.get("from_location", ""),
        to_location=raw.get("to_location", ""),
        departure_time=raw.get("departure_time", time_slot.get("start_time")),
        arrival_time=raw.get("arrival_time", time_slot.get("end_time")),
        carrier=raw.get("carrier"),
        booking_reference=booking_ref,
        estimated_cost=raw.get("estimated_cost"),
        currency=raw.get("currency", "USD"),
        notes=notes,
    )


def _convert_accommodation_from_pipeline(raw: dict[str, Any]) -> ItineraryAccommodation:
    """Convert accommodation dict from pipeline format."""
    return ItineraryAccommodation(
        name=raw.get("name", ""),
        location=raw.get("location"),
        check_in=raw.get("check_in_time", raw.get("check_in")),
        check_out=raw.get("check_out_time", raw.get("check_out")),
        room_type=raw.get("room_type"),
        booking_reference=raw.get("booking_reference"),
        estimated_cost=raw.get("price_per_night", raw.get("estimated_cost")),
        currency=raw.get("currency", "USD"),
        notes=raw.get("notes"),
    )


def _convert_gap_from_pipeline(gap_dict: dict[str, Any]) -> ItineraryGap:
    """Convert a discovery gap dict to an ItineraryGap."""
    # Map discovery status to severity
    status = gap_dict.get("status", "error")
    user_action_required = gap_dict.get("user_action_required", False)

    # Determine severity based on status and user_action_required
    if user_action_required and status in ("error", "not_found", "timeout"):
        severity: Literal["blocker", "warning", "info"] = "blocker"
    elif status in ("error", "timeout"):
        severity = "warning"
    else:
        severity = "info"

    # Extract suggestions from retry_action if available
    suggestions: list[str] = []
    retry_action = gap_dict.get("retry_action")
    if retry_action:
        label = retry_action.get("label", "")
        if label:
            suggestions.append(label)

    placeholder_strategy = gap_dict.get("placeholder_strategy")
    if placeholder_strategy:
        suggestions.append(f"Using placeholder: {placeholder_strategy}")

    return ItineraryGap(
        category=gap_dict.get("agent", gap_dict.get("category", "unknown")),
        description=gap_dict.get("impact", gap_dict.get("description", "")),
        severity=severity,
        suggestions=suggestions if suggestions else None,
    )


def _convert_validation_gap(val_gap: dict[str, Any]) -> ItineraryGap:
    """Convert a validation gap dict to an ItineraryGap."""
    # Validation gaps are usually softer - they're known issues, not blockers
    category = val_gap.get("category", "validation")

    suggestions: list[str] = []
    placeholder_used = val_gap.get("placeholder_used")
    if placeholder_used:
        suggestions.append(f"Current assumption: {placeholder_used}")

    action = val_gap.get("action")
    if action:
        label = action.get("label", "")
        if label:
            suggestions.append(label)

    return ItineraryGap(
        category=category,
        description=val_gap.get("impact", ""),
        severity="warning",
        suggestions=suggestions if suggestions else None,
    )
