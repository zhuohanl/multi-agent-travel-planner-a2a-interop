"""
Route agent for creating day-by-day itineraries.

The Route agent is the third planning agent in the pipeline. It receives
aggregated discovery results and a budget plan, then transforms them into
a day-by-day itinerary with timing and logistics.

Per design doc "Downstream Pipeline with Partial Results" section:
- Missing transport: Use placeholder "Arrival: User to arrange" slots
- Missing stay: **BLOCKER** - cannot build day-by-day without accommodation
- Missing POI: Build itinerary with "Free time" blocks instead of activities

The route plan (itinerary) is consumed by the Validator agent.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date as date_type, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Any

from src.orchestrator.planning.agents.aggregator import AggregatedResults
from src.orchestrator.planning.agents.budget import BudgetPlan
from src.orchestrator.planning.pipeline import DiscoveryContext

if TYPE_CHECKING:
    from src.shared.a2a.client_wrapper import A2AClientWrapper
    from src.shared.a2a.registry import AgentRegistry

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Itinerary Models
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class TimeSlot:
    """
    A time slot in the itinerary.

    Per design doc, each activity/transport/meal has:
    - start_time: When the slot begins
    - end_time: When the slot ends
    - duration_minutes: Duration in minutes (for display)
    """

    start_time: time | None = None
    end_time: time | None = None
    duration_minutes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        result: dict[str, Any] = {}
        if self.start_time is not None:
            result["start_time"] = self.start_time.strftime("%H:%M")
        if self.end_time is not None:
            result["end_time"] = self.end_time.strftime("%H:%M")
        if self.duration_minutes is not None:
            result["duration_minutes"] = self.duration_minutes
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TimeSlot:
        """Deserialize from dictionary."""
        start_time = None
        end_time = None

        start_str = data.get("start_time")
        if start_str:
            try:
                start_time = time.fromisoformat(start_str)
            except ValueError:
                pass

        end_str = data.get("end_time")
        if end_str:
            try:
                end_time = time.fromisoformat(end_str)
            except ValueError:
                pass

        return cls(
            start_time=start_time,
            end_time=end_time,
            duration_minutes=data.get("duration_minutes"),
        )


@dataclass
class ItineraryActivity:
    """
    An activity slot in the day's schedule.

    Per design doc, activities can be:
    - Attractions/POIs from discovery
    - Events from discovery
    - "Free time" placeholders when POI/events are missing
    """

    name: str
    category: str  # "attraction", "event", "free_time"
    time_slot: TimeSlot
    location: str | None = None
    notes: str | None = None
    estimated_cost: float | None = None
    is_placeholder: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        result: dict[str, Any] = {
            "name": self.name,
            "category": self.category,
            "time_slot": self.time_slot.to_dict(),
            "is_placeholder": self.is_placeholder,
        }
        if self.location is not None:
            result["location"] = self.location
        if self.notes is not None:
            result["notes"] = self.notes
        if self.estimated_cost is not None:
            result["estimated_cost"] = self.estimated_cost
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ItineraryActivity:
        """Deserialize from dictionary."""
        return cls(
            name=data.get("name", ""),
            category=data.get("category", "activity"),
            time_slot=TimeSlot.from_dict(data.get("time_slot", {})),
            location=data.get("location"),
            notes=data.get("notes"),
            estimated_cost=data.get("estimated_cost"),
            is_placeholder=data.get("is_placeholder", False),
        )


@dataclass
class ItineraryMeal:
    """
    A meal slot in the day's schedule.

    Per design doc, meals can be:
    - Restaurant recommendations from discovery
    - Generic "Lunch break" / "Dinner" placeholders when dining is missing
    """

    meal_type: str  # "breakfast", "lunch", "dinner"
    name: str
    time_slot: TimeSlot
    location: str | None = None
    cuisine: str | None = None
    estimated_cost: float | None = None
    notes: str | None = None
    is_placeholder: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        result: dict[str, Any] = {
            "meal_type": self.meal_type,
            "name": self.name,
            "time_slot": self.time_slot.to_dict(),
            "is_placeholder": self.is_placeholder,
        }
        if self.location is not None:
            result["location"] = self.location
        if self.cuisine is not None:
            result["cuisine"] = self.cuisine
        if self.estimated_cost is not None:
            result["estimated_cost"] = self.estimated_cost
        if self.notes is not None:
            result["notes"] = self.notes
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ItineraryMeal:
        """Deserialize from dictionary."""
        return cls(
            meal_type=data.get("meal_type", "meal"),
            name=data.get("name", ""),
            time_slot=TimeSlot.from_dict(data.get("time_slot", {})),
            location=data.get("location"),
            cuisine=data.get("cuisine"),
            estimated_cost=data.get("estimated_cost"),
            notes=data.get("notes"),
            is_placeholder=data.get("is_placeholder", False),
        )


@dataclass
class ItineraryTransport:
    """
    A transport segment in the itinerary.

    Per design doc, transport can be:
    - Flights/trains from discovery
    - "User to arrange" placeholders when transport is missing
    """

    mode: str  # "flight", "train", "taxi", "walk"
    from_location: str
    to_location: str
    time_slot: TimeSlot
    departure_time: str | None = None
    arrival_time: str | None = None
    carrier: str | None = None
    estimated_cost: float | None = None
    notes: str | None = None
    is_placeholder: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        result: dict[str, Any] = {
            "mode": self.mode,
            "from_location": self.from_location,
            "to_location": self.to_location,
            "time_slot": self.time_slot.to_dict(),
            "is_placeholder": self.is_placeholder,
        }
        if self.departure_time is not None:
            result["departure_time"] = self.departure_time
        if self.arrival_time is not None:
            result["arrival_time"] = self.arrival_time
        if self.carrier is not None:
            result["carrier"] = self.carrier
        if self.estimated_cost is not None:
            result["estimated_cost"] = self.estimated_cost
        if self.notes is not None:
            result["notes"] = self.notes
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ItineraryTransport:
        """Deserialize from dictionary."""
        return cls(
            mode=data.get("mode", "transport"),
            from_location=data.get("from_location", ""),
            to_location=data.get("to_location", ""),
            time_slot=TimeSlot.from_dict(data.get("time_slot", {})),
            departure_time=data.get("departure_time"),
            arrival_time=data.get("arrival_time"),
            carrier=data.get("carrier"),
            estimated_cost=data.get("estimated_cost"),
            notes=data.get("notes"),
            is_placeholder=data.get("is_placeholder", False),
        )


@dataclass
class ItineraryAccommodation:
    """
    Accommodation for the night.

    Per design doc, stay is required for building day-by-day itinerary.
    """

    name: str
    location: str | None = None
    check_in_time: str | None = None
    check_out_time: str | None = None
    price_per_night: float | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        result: dict[str, Any] = {
            "name": self.name,
        }
        if self.location is not None:
            result["location"] = self.location
        if self.check_in_time is not None:
            result["check_in_time"] = self.check_in_time
        if self.check_out_time is not None:
            result["check_out_time"] = self.check_out_time
        if self.price_per_night is not None:
            result["price_per_night"] = self.price_per_night
        if self.notes is not None:
            result["notes"] = self.notes
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ItineraryAccommodation:
        """Deserialize from dictionary."""
        return cls(
            name=data.get("name", ""),
            location=data.get("location"),
            check_in_time=data.get("check_in_time"),
            check_out_time=data.get("check_out_time"),
            price_per_night=data.get("price_per_night"),
            notes=data.get("notes"),
        )


@dataclass
class ItineraryDay:
    """
    A single day in the itinerary.

    Per design doc, each day contains:
    - date: The calendar date
    - title: Human-readable title (e.g., "Day 1 in Tokyo")
    - activities: List of activities/attractions
    - meals: List of meals
    - transport: List of transport segments
    - accommodation: Where you're staying (if not last day)
    """

    day_number: int
    date: date_type
    title: str
    activities: list[ItineraryActivity] = field(default_factory=list)
    meals: list[ItineraryMeal] = field(default_factory=list)
    transport: list[ItineraryTransport] = field(default_factory=list)
    accommodation: ItineraryAccommodation | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        result: dict[str, Any] = {
            "day_number": self.day_number,
            "date": self.date.isoformat(),
            "title": self.title,
            "activities": [a.to_dict() for a in self.activities],
            "meals": [m.to_dict() for m in self.meals],
            "transport": [t.to_dict() for t in self.transport],
        }
        if self.accommodation is not None:
            result["accommodation"] = self.accommodation.to_dict()
        if self.notes:
            result["notes"] = self.notes
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ItineraryDay:
        """Deserialize from dictionary."""
        date_raw = data.get("date")
        if isinstance(date_raw, str):
            day_date = date_type.fromisoformat(date_raw)
        elif isinstance(date_raw, date_type):
            day_date = date_raw
        else:
            day_date = date_type.today()

        accommodation = None
        if data.get("accommodation"):
            accommodation = ItineraryAccommodation.from_dict(data["accommodation"])

        return cls(
            day_number=data.get("day_number", 1),
            date=day_date,
            title=data.get("title", ""),
            activities=[ItineraryActivity.from_dict(a) for a in data.get("activities", [])],
            meals=[ItineraryMeal.from_dict(m) for m in data.get("meals", [])],
            transport=[ItineraryTransport.from_dict(t) for t in data.get("transport", [])],
            accommodation=accommodation,
            notes=data.get("notes", []),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# A2A Itinerary Compatibility
# ═══════════════════════════════════════════════════════════════════════════════


def _looks_like_slot_days(raw_days: list[Any]) -> bool:
    for day in raw_days:
        if isinstance(day, dict) and isinstance(day.get("slots"), list):
            return True
    return False


def _parse_date_value(value: Any) -> date_type:
    if isinstance(value, str):
        try:
            return date_type.fromisoformat(value)
        except ValueError:
            return date_type.today()
    if isinstance(value, date_type):
        return value
    return date_type.today()


def _parse_time_value(value: Any) -> time | None:
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        try:
            return time.fromisoformat(value)
        except ValueError:
            return None
    return None


def _time_slot_from_slot(slot: dict[str, Any]) -> TimeSlot:
    start = _parse_time_value(slot.get("start_time"))
    end = _parse_time_value(slot.get("end_time"))
    duration: int | None = None
    if start and end:
        delta = datetime.combine(date_type.min, end) - datetime.combine(date_type.min, start)
        if delta.total_seconds() >= 0:
            duration = int(delta.total_seconds() // 60)
    return TimeSlot(start_time=start, end_time=end, duration_minutes=duration)


def _infer_meal_type(name: str | None, start_time: time | None) -> str:
    lower = (name or "").lower()
    if "breakfast" in lower:
        return "breakfast"
    if "brunch" in lower:
        return "brunch"
    if "lunch" in lower:
        return "lunch"
    if "dinner" in lower or "supper" in lower:
        return "dinner"
    if start_time:
        if start_time < time(10, 0):
            return "breakfast"
        if start_time < time(15, 0):
            return "lunch"
        return "dinner"
    return "meal"


def _infer_transport_mode(*parts: str | None) -> str:
    lower = " ".join(
        part.strip()
        for part in parts
        if isinstance(part, str) and part.strip()
    ).lower()
    if "shuttle" in lower:
        return "shuttle"
    if "transfer" in lower:
        return "transfer"
    if "taxi" in lower or "uber" in lower or "cab" in lower:
        return "taxi"
    if "train" in lower:
        return "train"
    if "bus" in lower:
        return "bus"
    if "ferry" in lower or "boat" in lower:
        return "ferry"
    if "walk" in lower:
        return "walk"
    if re.search(
        r"\bflight\b|\bair\b|\bairline\b|\bairlines\b|\bairways\b|"
        r"\bairfare\b|\bair\s+ticket\b|\bair\s+travel\b|\bplane\b|\baircraft\b",
        lower,
    ):
        return "flight"
    return "transport"


def _split_route_location(location: str | None, activity: str | None) -> tuple[str, str]:
    for source in (activity, location):
        if not isinstance(source, str) or not source.strip():
            continue
        match = re.search(r"\bfrom\s+(.+?)\s+to\s+(.+?)(?:[.,()]+|$)", source, re.IGNORECASE)
        if match:
            return match.group(1).strip(), match.group(2).strip()
        if " -> " in source:
            left, right = source.split(" -> ", 1)
            return left.strip(), right.strip()
        if " to " in source:
            left, right = source.split(" to ", 1)
            return left.strip(), right.strip()
    if isinstance(location, str) and location.strip():
        cleaned = location.strip()
        return cleaned, cleaned
    return ("", "")


def _merge_notes(*parts: Any) -> str | None:
    merged: list[str] = []
    for part in parts:
        if isinstance(part, str):
            text = part.strip()
            if text and text not in merged:
                merged.append(text)
    if not merged:
        return None
    return " ".join(merged)


def _convert_slot_day(day_data: dict[str, Any], day_number: int) -> ItineraryDay:
    day_date = _parse_date_value(day_data.get("date"))
    title = day_data.get("title", "")
    day_summary = day_data.get("day_summary")
    notes: list[str] = []
    if isinstance(day_summary, str) and day_summary:
        if not title:
            title = day_summary
        else:
            notes.append(day_summary)

    activities: list[ItineraryActivity] = []
    meals: list[ItineraryMeal] = []
    transport: list[ItineraryTransport] = []
    accommodation: ItineraryAccommodation | None = None

    for slot in day_data.get("slots", []):
        if not isinstance(slot, dict):
            continue

        category = str(slot.get("category", "")).lower()
        name = slot.get("activity") or slot.get("name") or slot.get("title") or ""
        location = slot.get("location")
        item_ref = slot.get("item_ref")
        est_cost = slot.get("estimated_cost")
        slot_notes = slot.get("notes")
        time_slot = _time_slot_from_slot(slot)

        if category == "dining":
            meal_type = _infer_meal_type(name, time_slot.start_time)
            meals.append(
                ItineraryMeal(
                    meal_type=meal_type,
                    name=name or item_ref or meal_type.capitalize(),
                    time_slot=time_slot,
                    location=location,
                    estimated_cost=est_cost if isinstance(est_cost, (int, float)) else None,
                    notes=_merge_notes(slot_notes, item_ref),
                    is_placeholder=False,
                )
            )
            continue

        if category == "transport":
            from_loc, to_loc = _split_route_location(location, name)
            if not from_loc:
                from_loc = location or name or "Origin"
            if not to_loc:
                to_loc = location or name or from_loc
            raw_mode = slot.get("mode")
            mode = (
                raw_mode.strip()
                if isinstance(raw_mode, str) and raw_mode.strip()
                else _infer_transport_mode(name, item_ref, location)
            )
            transport.append(
                ItineraryTransport(
                    mode=mode,
                    from_location=from_loc,
                    to_location=to_loc,
                    time_slot=time_slot,
                    departure_time=slot.get("start_time"),
                    arrival_time=slot.get("end_time"),
                    estimated_cost=est_cost if isinstance(est_cost, (int, float)) else None,
                    notes=_merge_notes(slot_notes, name, item_ref),
                    is_placeholder=False,
                )
            )
            continue

        if category == "stay":
            accommodation_name = item_ref or location or name or "Accommodation"
            if accommodation is None:
                accommodation = ItineraryAccommodation(
                    name=accommodation_name,
                    location=location if location and location != accommodation_name else None,
                    check_in_time=slot.get("start_time")
                    if "check-in" in (name or "").lower()
                    else None,
                    check_out_time=slot.get("start_time")
                    if "check-out" in (name or "").lower()
                    else None,
                    price_per_night=est_cost if isinstance(est_cost, (int, float)) else None,
                    notes=_merge_notes(slot_notes, item_ref),
                )
            else:
                if "check-in" in (name or "").lower() and accommodation.check_in_time is None:
                    accommodation.check_in_time = slot.get("start_time")
                if "check-out" in (name or "").lower() and accommodation.check_out_time is None:
                    accommodation.check_out_time = slot.get("start_time")

            activities.append(
                ItineraryActivity(
                    name=name or accommodation_name,
                    category="stay",
                    time_slot=time_slot,
                    location=location,
                    notes=_merge_notes(slot_notes, item_ref),
                    estimated_cost=est_cost if isinstance(est_cost, (int, float)) else None,
                    is_placeholder=False,
                )
            )
            continue

        activity_category = category or "activity"
        is_placeholder = False
        if "free time" in (name or "").lower():
            activity_category = "free_time"
            is_placeholder = True
        elif category == "poi":
            activity_category = "attraction"
        elif category == "event":
            activity_category = "event"

        activities.append(
            ItineraryActivity(
                name=name or item_ref or "Activity",
                category=activity_category,
                time_slot=time_slot,
                location=location,
                notes=_merge_notes(slot_notes, item_ref),
                estimated_cost=est_cost if isinstance(est_cost, (int, float)) else None,
                is_placeholder=is_placeholder,
            )
        )

    return ItineraryDay(
        day_number=day_number,
        date=day_date,
        title=title,
        activities=activities,
        meals=meals,
        transport=transport,
        accommodation=accommodation,
        notes=notes,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Route Plan Model
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class RoutePlan:
    """
    Output from the Route agent.

    Contains the complete day-by-day itinerary with:
    - destination: Trip destination city
    - start_date: First day of trip
    - end_date: Last day of trip
    - days: List of ItineraryDay objects
    - total_estimated_cost: Sum of all estimated costs
    - currency: Currency for costs
    - has_placeholders: Whether any items are placeholders (missing data)
    - notes: General notes about the itinerary
    - routed_at: Timestamp when route was created
    """

    destination: str
    start_date: date_type
    end_date: date_type
    days: list[ItineraryDay] = field(default_factory=list)
    total_estimated_cost: float = 0.0
    currency: str = "USD"
    has_placeholders: bool = False
    notes: list[str] = field(default_factory=list)
    routed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for storage/transmission."""
        return {
            "destination": self.destination,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "days": [day.to_dict() for day in self.days],
            "total_estimated_cost": self.total_estimated_cost,
            "currency": self.currency,
            "has_placeholders": self.has_placeholders,
            "notes": self.notes,
            "routed_at": self.routed_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoutePlan:
        """Deserialize from dictionary."""
        start_date_raw = data.get("start_date")
        start_date_provided = False
        if isinstance(start_date_raw, str):
            try:
                start_date = date_type.fromisoformat(start_date_raw)
                start_date_provided = True
            except ValueError:
                start_date = date_type.today()
        elif isinstance(start_date_raw, date_type):
            start_date = start_date_raw
            start_date_provided = True
        else:
            start_date = date_type.today()

        end_date_raw = data.get("end_date")
        end_date_provided = False
        if isinstance(end_date_raw, str):
            try:
                end_date = date_type.fromisoformat(end_date_raw)
                end_date_provided = True
            except ValueError:
                end_date = start_date
        elif isinstance(end_date_raw, date_type):
            end_date = end_date_raw
            end_date_provided = True
        else:
            end_date = start_date

        routed_at = data.get("routed_at")
        if isinstance(routed_at, str):
            routed_at = datetime.fromisoformat(routed_at)
        elif routed_at is None:
            routed_at = datetime.now(timezone.utc)

        raw_days = data.get("days", [])
        if _looks_like_slot_days(raw_days):
            days = [
                _convert_slot_day(day, index + 1)
                for index, day in enumerate(raw_days)
                if isinstance(day, dict)
            ]
        else:
            days = [ItineraryDay.from_dict(d) for d in raw_days]

        if days:
            if not start_date_provided:
                start_date = days[0].date
            if not end_date_provided:
                end_date = days[-1].date

        from_dict_result = cls(
            destination=data.get("destination", ""),
            start_date=start_date,
            end_date=end_date,
            days=days,
            total_estimated_cost=float(data.get("total_estimated_cost", 0)),
            currency=data.get("currency", "USD"),
            has_placeholders=data.get("has_placeholders", False),
            notes=data.get("notes", []),
            routed_at=routed_at,
        )

        return from_dict_result

    def get_day(self, day_number: int) -> ItineraryDay | None:
        """Get a specific day by number."""
        for day in self.days:
            if day.day_number == day_number:
                return day
        return None

    def num_days(self) -> int:
        """Return the number of days in the itinerary."""
        return len(self.days)


# ═══════════════════════════════════════════════════════════════════════════════
# Route Planning Error
# ═══════════════════════════════════════════════════════════════════════════════


class RoutePlanningError(Exception):
    """Raised when route planning cannot proceed.

    Per design doc, missing stay is a blocker that prevents route planning.
    """

    def __init__(self, message: str, blocker: str | None = None):
        """
        Initialize the error.

        Args:
            message: Human-readable error message
            blocker: The blocking issue (e.g., "missing_stay")
        """
        super().__init__(message)
        self.blocker = blocker


# ═══════════════════════════════════════════════════════════════════════════════
# Default Time Slots
# ═══════════════════════════════════════════════════════════════════════════════


# Default arrival time placeholder for first day when transport missing
DEFAULT_ARRIVAL_TIME = time(14, 0)  # 2:00 PM
DEFAULT_ARRIVAL_PLACEHOLDER = "Arrival: User to arrange (assume ~2pm)"

# Default departure time placeholder for last day when transport missing
DEFAULT_DEPARTURE_TIME = time(11, 0)  # 11:00 AM
DEFAULT_DEPARTURE_PLACEHOLDER = "Departure: User to arrange (assume ~11am)"

# Meal time defaults
BREAKFAST_TIME = time(8, 0)
LUNCH_TIME = time(12, 30)
DINNER_TIME = time(19, 0)

# Activity time defaults
MORNING_ACTIVITY_START = time(10, 0)
AFTERNOON_ACTIVITY_START = time(14, 30)
EVENING_ACTIVITY_START = time(16, 30)

# Free time placeholder
FREE_TIME_NOTE = "Free time to explore at your own pace"


# ═══════════════════════════════════════════════════════════════════════════════
# Route Agent
# ═══════════════════════════════════════════════════════════════════════════════


class RouteAgent:
    """
    Route agent for creating day-by-day itineraries.

    The Route agent is the third agent in the planning pipeline. It receives
    aggregated results and budget plan, then builds a day-by-day itinerary
    with timing and logistics.

    Per design doc "How Each Agent Handles Partial Discovery":
    - Missing transport: Use placeholder arrival/departure slots
    - Missing stay: **BLOCKER** - cannot build day-by-day without accommodation
    - Missing POI: Build itinerary with "Free time" blocks

    The agent can operate in two modes:
    1. Stub mode (no A2A client): Uses local routing logic
    2. Live mode (with A2A client): Calls the route agent via A2A

    Example:
        route = RouteAgent(a2a_client, agent_registry)
        plan = await route.plan(aggregated, budget_plan, context, trip_spec)
    """

    def __init__(
        self,
        a2a_client: "A2AClientWrapper | None" = None,
        agent_registry: "AgentRegistry | None" = None,
    ):
        """
        Initialize the Route agent.

        Args:
            a2a_client: A2A client for agent communication (optional for testing)
            agent_registry: Agent registry for URL lookup (optional for testing)
        """
        self._a2a_client = a2a_client
        self._agent_registry = agent_registry

    async def plan(
        self,
        aggregated: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context: DiscoveryContext,
        trip_spec: dict[str, Any] | None = None,
    ) -> RoutePlan:
        """
        Create a day-by-day itinerary from aggregated results and budget plan.

        Per design doc "Downstream Pipeline with Partial Results":
        - Missing transport: Use placeholder arrival/departure slots
        - Missing stay: **BLOCKER** - raises RoutePlanningError
        - Skipped stay: Allowed (user arranging own accommodation)
        - Missing POI: Use "Free time" blocks

        Args:
            aggregated: Aggregated results from the Aggregator
            budget_plan: Budget allocation from the Budget agent
            discovery_context: Context with explicit gaps
            trip_spec: Trip requirements (destination, dates, etc.)

        Returns:
            RoutePlan with day-by-day itinerary

        Raises:
            RoutePlanningError: If stay data is missing and not skipped (blocker)
        """
        # Check for stay blocker FIRST
        # Note: SKIPPED stay is allowed (user arranging own accommodation)
        stay_is_skipped = aggregated.stay.status == "SKIPPED"
        if not aggregated.has_stay() and not stay_is_skipped:
            raise RoutePlanningError(
                "Cannot build day-by-day itinerary without accommodation information. "
                "Stay search must succeed before route planning.",
                blocker="missing_stay",
            )

        if self._a2a_client is not None and self._agent_registry is not None:
            # Live mode: Call route agent via A2A
            plan = await self._plan_via_a2a(
                aggregated, budget_plan, discovery_context, trip_spec
            )
            self._normalize_route_plan(plan)
            return plan

        # Stub mode: Use local routing logic
        plan = self._plan_locally(aggregated, budget_plan, discovery_context, trip_spec)
        self._normalize_route_plan(plan)
        return plan

    async def _plan_via_a2a(
        self,
        aggregated: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context: DiscoveryContext,
        trip_spec: dict[str, Any] | None,
    ) -> RoutePlan:
        """
        Call the route agent via A2A.

        Args:
            aggregated: Aggregated results from Aggregator
            budget_plan: Budget allocation plan
            discovery_context: Context with explicit gaps
            trip_spec: Trip requirements

        Returns:
            RoutePlan from the route agent
        """
        assert self._a2a_client is not None
        assert self._agent_registry is not None

        # Get route agent URL
        route_config = self._agent_registry.get("route")
        if route_config is None:
            logger.warning("Route agent not found in registry, using local planning")
            return self._plan_locally(aggregated, budget_plan, discovery_context, trip_spec)

        # Build request payload
        request_payload = {
            "aggregated": aggregated.to_dict(),
            "budget_plan": budget_plan.to_dict(),
            "discovery_context": discovery_context.to_dict(),
            "trip_spec": trip_spec or {},
        }

        try:
            # Call route agent
            timeout = getattr(route_config, "timeout", 60)
            response = await self._a2a_client.send_message(
                agent_url=route_config.url,
                message=json.dumps(request_payload),
                timeout=timeout,
            )

            # Parse response
            if response.is_complete and response.text:
                try:
                    response_data = json.loads(response.text)
                    to_return = RoutePlan.from_dict(response_data)
                    return to_return
                except json.JSONDecodeError:
                    logger.warning("Failed to parse route response, using local planning")
                    return self._plan_locally(
                        aggregated, budget_plan, discovery_context, trip_spec
                    )

            # If not complete, fall back to local planning
            logger.warning("Route agent did not complete, using local planning")
            return self._plan_locally(aggregated, budget_plan, discovery_context, trip_spec)

        except Exception as e:
            logger.error(f"Route agent call failed: {e}, using local planning")
            return self._plan_locally(aggregated, budget_plan, discovery_context, trip_spec)

    def _plan_locally(
        self,
        aggregated: AggregatedResults,
        budget_plan: BudgetPlan,
        discovery_context: DiscoveryContext,
        trip_spec: dict[str, Any] | None,
    ) -> RoutePlan:
        """
        Create itinerary using local logic.

        This is the stub implementation used when no A2A client is available.

        Args:
            aggregated: Aggregated results from Aggregator
            budget_plan: Budget allocation plan
            discovery_context: Context with explicit gaps
            trip_spec: Trip requirements

        Returns:
            RoutePlan with day-by-day itinerary
        """
        trip_spec = trip_spec or {}

        # Parse dates
        start_date = self._parse_date(trip_spec.get("start_date"), date_type.today())
        end_date = self._parse_date(
            trip_spec.get("end_date"), start_date + timedelta(days=3)
        )

        # Get destination
        destination = trip_spec.get(
            "destination_city", trip_spec.get("destination", aggregated.destination or "Unknown")
        )
        origin = trip_spec.get("origin_city", "Origin")

        # Check for gaps
        transport_gap = discovery_context.get_gap_for_agent("transport")
        poi_gap = discovery_context.get_gap_for_agent("poi")
        events_gap = discovery_context.get_gap_for_agent("events")
        dining_gap = discovery_context.get_gap_for_agent("dining")

        # Determine if we have placeholders
        has_placeholders = bool(transport_gap or poi_gap or events_gap or dining_gap)

        # Get data from aggregated results
        stay_data = aggregated.stay.data or {}
        poi_data = aggregated.poi.data or {} if not poi_gap else {}
        events_data = aggregated.events.data or {} if not events_gap else {}
        dining_data = aggregated.dining.data or {} if not dining_gap else {}

        # Build days
        num_days = (end_date - start_date).days + 1
        days: list[ItineraryDay] = []
        notes: list[str] = []
        total_cost = 0.0

        # Extract options from data
        hotels = stay_data.get("hotels", stay_data.get("accommodations", stay_data.get("options", [])))
        attractions = poi_data.get("attractions", poi_data.get("landmarks", poi_data.get("options", [])))
        events = events_data.get("events", events_data.get("options", []))
        restaurants = dining_data.get("restaurants", dining_data.get("options", []))

        # Pick first hotel if available
        hotel = hotels[0] if hotels else None
        hotel_name = hotel.get("name", "Accommodation") if hotel else "User's accommodation"
        hotel_price = hotel.get("price_per_night", 0) if hotel else 0

        for i in range(num_days):
            day_date = start_date + timedelta(days=i)
            day_number = i + 1
            is_first_day = i == 0
            is_last_day = i == num_days - 1

            day = ItineraryDay(
                day_number=day_number,
                date=day_date,
                title=f"Day {day_number} in {destination}",
            )

            # Add arrival transport on first day
            if is_first_day:
                arrival = self._create_arrival_transport(
                    origin=origin,
                    destination=destination,
                    has_gap=bool(transport_gap),
                )
                day.transport.append(arrival)
                if arrival.is_placeholder:
                    notes.append(
                        "Arrival transport not specified. "
                        "Itinerary assumes ~2pm arrival on Day 1."
                    )

            # Add departure transport on last day
            if is_last_day:
                departure = self._create_departure_transport(
                    origin=destination,
                    destination=origin,
                    has_gap=bool(transport_gap),
                )
                day.transport.append(departure)
                if departure.is_placeholder:
                    notes.append(
                        "Departure transport not specified. "
                        "Itinerary assumes ~11am departure on final day."
                    )

            # Add activities or free time
            if poi_gap and events_gap:
                # Both missing - add free time blocks
                day.activities.append(self._create_free_time_activity("morning"))
                day.activities.append(self._create_free_time_activity("afternoon"))
                if not is_last_day:
                    day.activities.append(self._create_free_time_activity("evening"))
            else:
                # Add attractions and events as activities
                morning_activity = self._create_activity_from_data(
                    attractions, events, day_number, "morning", poi_gap, events_gap
                )
                afternoon_activity = self._create_activity_from_data(
                    attractions, events, day_number, "afternoon", poi_gap, events_gap
                )

                if morning_activity:
                    day.activities.append(morning_activity)
                else:
                    day.activities.append(self._create_free_time_activity("morning"))

                if afternoon_activity:
                    day.activities.append(afternoon_activity)
                else:
                    day.activities.append(self._create_free_time_activity("afternoon"))

                # Evening activity only if not last day
                if not is_last_day:
                    evening_activity = self._create_activity_from_data(
                        attractions, events, day_number, "evening", poi_gap, events_gap
                    )
                    if evening_activity:
                        day.activities.append(evening_activity)
                    else:
                        day.activities.append(self._create_free_time_activity("evening"))

            # Add meals
            if not is_first_day:  # Skip breakfast on arrival day (assuming late arrival)
                day.meals.append(
                    self._create_meal("breakfast", restaurants, dining_gap)
                )

            day.meals.append(self._create_meal("lunch", restaurants, dining_gap))

            if not is_last_day:  # Skip dinner on departure day (assuming early departure)
                day.meals.append(self._create_meal("dinner", restaurants, dining_gap))

            # Add accommodation (except last day)
            if not is_last_day:
                day.accommodation = ItineraryAccommodation(
                    name=hotel_name,
                    location=hotel.get("location") if hotel else None,
                    check_in_time="15:00",
                    check_out_time="11:00",
                    price_per_night=hotel_price,
                )
                total_cost += hotel_price

            days.append(day)

        # Add notes about gaps
        if poi_gap:
            notes.append(
                "Limited attraction recommendations. "
                "Itinerary includes 'Free time' blocks for self-exploration."
            )
        if dining_gap:
            notes.append(
                "Restaurant recommendations not available. "
                "Generic meal breaks included."
            )

        return RoutePlan(
            destination=destination,
            start_date=start_date,
            end_date=end_date,
            days=days,
            total_estimated_cost=budget_plan.total_budget,
            currency=budget_plan.currency,
            has_placeholders=has_placeholders,
            notes=notes,
        )

    def _normalize_day_schedule(self, day: ItineraryDay) -> None:
        """
        Normalize one day schedule to keep it chronological and conflict-safe.

        Rules:
        - Remove activities/meals that overlap transport windows
        - Remove internal activity/meal overlaps within the same day
        - Keep remaining items sorted by start time
        """
        transport_windows = self._extract_transport_windows(day.transport)
        if transport_windows:
            day.activities = [
                activity
                for activity in day.activities
                if not self._overlaps_any_transport_window(activity.time_slot, transport_windows)
            ]
            day.meals = [
                meal
                for meal in day.meals
                if not self._overlaps_any_transport_window(meal.time_slot, transport_windows)
            ]

        day.activities, day.meals = self._remove_internal_overlaps(day.activities, day.meals)
        day.transport.sort(key=lambda transport: self._slot_sort_key(transport.time_slot))
        day.activities.sort(key=lambda activity: self._slot_sort_key(activity.time_slot))
        day.meals.sort(key=lambda meal: self._slot_sort_key(meal.time_slot))

    def _remove_internal_overlaps(
        self,
        activities: list[ItineraryActivity],
        meals: list[ItineraryMeal],
    ) -> tuple[list[ItineraryActivity], list[ItineraryMeal]]:
        """
        Remove overlaps between activity and meal items for one day.

        Meals are treated as anchors and evaluated before activities so lunch/dinner
        windows remain stable when there is a conflict.
        """
        kept_activities: list[ItineraryActivity] = []
        kept_meals: list[ItineraryMeal] = []
        timed_windows: list[tuple[time | None, time | None]] = []

        untimed_activities = [
            activity
            for activity in activities
            if activity.time_slot.start_time is None and activity.time_slot.end_time is None
        ]
        untimed_meals = [
            meal
            for meal in meals
            if meal.time_slot.start_time is None and meal.time_slot.end_time is None
        ]

        timed_candidates: list[tuple[str, int, int]] = []
        for meal_index, meal in enumerate(meals):
            if meal.time_slot.start_time is None and meal.time_slot.end_time is None:
                continue
            timed_candidates.append(("meal", meal_index, 0))
        for activity_index, activity in enumerate(activities):
            if activity.time_slot.start_time is None and activity.time_slot.end_time is None:
                continue
            timed_candidates.append(("activity", activity_index, 1))

        timed_candidates.sort(
            key=lambda candidate: (
                candidate[2],
                self._slot_sort_key(
                    meals[candidate[1]].time_slot
                    if candidate[0] == "meal"
                    else activities[candidate[1]].time_slot
                ),
                candidate[1],
            )
        )

        for kind, index, _priority in timed_candidates:
            slot = meals[index].time_slot if kind == "meal" else activities[index].time_slot
            has_conflict = any(
                self._slots_overlap(
                    slot.start_time,
                    slot.end_time,
                    existing_start,
                    existing_end,
                )
                for existing_start, existing_end in timed_windows
            )
            if has_conflict:
                continue

            timed_windows.append((slot.start_time, slot.end_time))
            if kind == "meal":
                kept_meals.append(meals[index])
            else:
                kept_activities.append(activities[index])

        kept_activities.extend(untimed_activities)
        kept_meals.extend(untimed_meals)
        return kept_activities, kept_meals

    def _normalize_route_plan(self, plan: RoutePlan) -> None:
        for day in plan.days:
            self._normalize_day_schedule(day)

    def _extract_transport_windows(
        self,
        transports: list[ItineraryTransport],
    ) -> list[tuple[time | None, time | None]]:
        windows: list[tuple[time | None, time | None]] = []
        for transport in transports:
            start = transport.time_slot.start_time
            end = transport.time_slot.end_time

            if start is None:
                start = self._parse_time_optional(transport.departure_time)
            if end is None:
                end = self._parse_time_optional(transport.arrival_time)

            if start is None and end is None:
                continue
            windows.append((start, end))
        return windows

    def _parse_time_optional(self, value: str | None) -> time | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            return time.fromisoformat(value)
        except ValueError:
            return None

    def _overlaps_any_transport_window(
        self,
        slot: TimeSlot,
        transport_windows: list[tuple[time | None, time | None]],
    ) -> bool:
        for transport_start, transport_end in transport_windows:
            if self._slots_overlap(
                slot.start_time,
                slot.end_time,
                transport_start,
                transport_end,
            ):
                return True
        return False

    def _slots_overlap(
        self,
        start_a: time | None,
        end_a: time | None,
        start_b: time | None,
        end_b: time | None,
    ) -> bool:
        # Convert partial intervals into bounded ranges.
        a_start = start_a or time.min
        a_end = end_a or time.max
        b_start = start_b or time.min
        b_end = end_b or time.max
        return a_start < b_end and b_start < a_end

    def _slot_sort_key(self, slot: TimeSlot) -> tuple[int, int]:
        if slot.start_time is not None:
            return (slot.start_time.hour, slot.start_time.minute)
        if slot.end_time is not None:
            return (slot.end_time.hour, slot.end_time.minute)
        return (23, 59)

    def _parse_date(self, value: Any, default: date_type) -> date_type:
        """Parse a date from various formats."""
        if isinstance(value, str):
            try:
                return date_type.fromisoformat(value)
            except ValueError:
                return default
        elif isinstance(value, date_type):
            return value
        return default

    def _create_arrival_transport(
        self,
        origin: str,
        destination: str,
        has_gap: bool,
    ) -> ItineraryTransport:
        """Create arrival transport (first day)."""
        if has_gap:
            return ItineraryTransport(
                mode="flight",
                from_location=origin,
                to_location=destination,
                time_slot=TimeSlot(
                    start_time=None,
                    end_time=DEFAULT_ARRIVAL_TIME,
                    duration_minutes=None,
                ),
                departure_time=None,
                arrival_time=DEFAULT_ARRIVAL_TIME.strftime("%H:%M"),
                notes=DEFAULT_ARRIVAL_PLACEHOLDER,
                is_placeholder=True,
            )
        else:
            return ItineraryTransport(
                mode="flight",
                from_location=origin,
                to_location=destination,
                time_slot=TimeSlot(
                    start_time=time(9, 0),
                    end_time=DEFAULT_ARRIVAL_TIME,
                    duration_minutes=300,  # 5 hours
                ),
                departure_time="09:00",
                arrival_time="14:00",
                is_placeholder=False,
            )

    def _create_departure_transport(
        self,
        origin: str,
        destination: str,
        has_gap: bool,
    ) -> ItineraryTransport:
        """Create departure transport (last day)."""
        if has_gap:
            return ItineraryTransport(
                mode="flight",
                from_location=origin,
                to_location=destination,
                time_slot=TimeSlot(
                    start_time=DEFAULT_DEPARTURE_TIME,
                    end_time=None,
                    duration_minutes=None,
                ),
                departure_time=DEFAULT_DEPARTURE_TIME.strftime("%H:%M"),
                arrival_time=None,
                notes=DEFAULT_DEPARTURE_PLACEHOLDER,
                is_placeholder=True,
            )
        else:
            return ItineraryTransport(
                mode="flight",
                from_location=origin,
                to_location=destination,
                time_slot=TimeSlot(
                    start_time=DEFAULT_DEPARTURE_TIME,
                    end_time=time(16, 0),
                    duration_minutes=300,
                ),
                departure_time="11:00",
                arrival_time="16:00",
                is_placeholder=False,
            )

    def _create_free_time_activity(self, period: str) -> ItineraryActivity:
        """Create a free time placeholder activity."""
        time_slots = {
            "morning": TimeSlot(
                start_time=MORNING_ACTIVITY_START,
                end_time=time(12, 0),
                duration_minutes=120,
            ),
            "afternoon": TimeSlot(
                start_time=AFTERNOON_ACTIVITY_START,
                end_time=time(16, 0),
                duration_minutes=90,
            ),
            "evening": TimeSlot(
                start_time=EVENING_ACTIVITY_START,
                end_time=time(18, 30),
                duration_minutes=120,
            ),
        }
        return ItineraryActivity(
            name=f"Free time ({period})",
            category="free_time",
            time_slot=time_slots.get(
                period, TimeSlot(start_time=time(10, 0), end_time=time(12, 0))
            ),
            notes=FREE_TIME_NOTE,
            is_placeholder=True,
        )

    def _create_activity_from_data(
        self,
        attractions: list[dict[str, Any]],
        events: list[dict[str, Any]],
        day_number: int,
        period: str,
        poi_gap: Any,
        events_gap: Any,
    ) -> ItineraryActivity | None:
        """Create an activity from discovery data or return None."""
        time_slots = {
            "morning": TimeSlot(
                start_time=MORNING_ACTIVITY_START,
                end_time=time(12, 0),
                duration_minutes=120,
            ),
            "afternoon": TimeSlot(
                start_time=AFTERNOON_ACTIVITY_START,
                end_time=time(16, 0),
                duration_minutes=90,
            ),
            "evening": TimeSlot(
                start_time=EVENING_ACTIVITY_START,
                end_time=time(18, 30),
                duration_minutes=120,
            ),
        }

        # Rotate through attractions and events based on day and period
        period_index = {"morning": 0, "afternoon": 1, "evening": 2}.get(period, 0)
        index = (day_number - 1) * 3 + period_index

        # Try attractions first
        if attractions and not poi_gap and index < len(attractions) * 2:
            attraction = attractions[index % len(attractions)]
            return ItineraryActivity(
                name=attraction.get("name", "Attraction"),
                category="attraction",
                time_slot=time_slots.get(
                    period, TimeSlot(start_time=time(10, 0), end_time=time(12, 0))
                ),
                location=attraction.get("location"),
                notes=attraction.get("description"),
                estimated_cost=attraction.get("price", attraction.get("estimated_cost")),
                is_placeholder=False,
            )

        # Try events
        if events and not events_gap:
            event_index = index % len(events) if events else 0
            if event_index < len(events):
                event = events[event_index]
                return ItineraryActivity(
                    name=event.get("name", "Event"),
                    category="event",
                    time_slot=time_slots.get(
                        period, TimeSlot(start_time=time(10, 0), end_time=time(12, 0))
                    ),
                    location=event.get("location", event.get("venue")),
                    notes=event.get("description"),
                    estimated_cost=event.get("price", event.get("ticket_price")),
                    is_placeholder=False,
                )

        return None

    def _create_meal(
        self,
        meal_type: str,
        restaurants: list[dict[str, Any]],
        dining_gap: Any,
    ) -> ItineraryMeal:
        """Create a meal entry."""
        meal_times = {
            "breakfast": TimeSlot(
                start_time=BREAKFAST_TIME,
                end_time=time(9, 0),
                duration_minutes=60,
            ),
            "lunch": TimeSlot(
                start_time=LUNCH_TIME,
                end_time=time(13, 30),
                duration_minutes=60,
            ),
            "dinner": TimeSlot(
                start_time=DINNER_TIME,
                end_time=time(20, 30),
                duration_minutes=90,
            ),
        }

        if dining_gap or not restaurants:
            # Placeholder meal
            return ItineraryMeal(
                meal_type=meal_type,
                name=f"{meal_type.capitalize()} break",
                time_slot=meal_times.get(
                    meal_type, TimeSlot(start_time=time(12, 0), end_time=time(13, 0))
                ),
                notes="Restaurant recommendation not available",
                is_placeholder=True,
            )
        else:
            # Pick a restaurant (rotate through available options)
            restaurant = restaurants[0]  # Simple: just use first
            return ItineraryMeal(
                meal_type=meal_type,
                name=restaurant.get("name", "Restaurant"),
                time_slot=meal_times.get(
                    meal_type, TimeSlot(start_time=time(12, 0), end_time=time(13, 0))
                ),
                location=restaurant.get("location"),
                cuisine=restaurant.get("cuisine"),
                estimated_cost=restaurant.get("price", restaurant.get("average_cost")),
                is_placeholder=False,
            )
