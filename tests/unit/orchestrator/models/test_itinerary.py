"""Unit tests for Itinerary models.

Tests cover:
- TripSummary creation and serialization
- ItineraryDay with activities, meals, transport, accommodation
- ItineraryGap for partial discovery failures
- ItineraryDraft creation and conversion to Itinerary
- Itinerary as approved, immutable plan
- Serialization roundtrips for Cosmos DB storage
- create_itinerary_draft factory function
- format_for_display method for user-facing output

ORCH-080 acceptance criteria:
- ItineraryDraft contains day-by-day structure with time slots
- Each activity has location, time, duration, and bookable flag
- Gaps from planning are included in ItineraryDraft
- format_for_display() produces user-friendly preview text
- ItineraryDraft can be stored in WorkflowState
"""

from datetime import date, datetime, timezone

import pytest

from src.orchestrator.models.itinerary import (
    Itinerary,
    ItineraryAccommodation,
    ItineraryActivity,
    ItineraryDay,
    ItineraryDraft,
    ItineraryGap,
    ItineraryMeal,
    ItineraryTransport,
    TripSummary,
)


class TestTripSummaryCreation:
    """Tests for TripSummary creation and basic operations."""

    def test_trip_summary_creation(self):
        """Test creating TripSummary with all fields."""
        summary = TripSummary(
            destination="Tokyo",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 17),
            travelers=2,
            trip_type="leisure",
        )

        assert summary.destination == "Tokyo"
        assert summary.start_date == date(2025, 3, 10)
        assert summary.end_date == date(2025, 3, 17)
        assert summary.travelers == 2
        assert summary.trip_type == "leisure"

    def test_trip_summary_duration_days(self):
        """Test duration_days property calculation."""
        summary = TripSummary(
            destination="Paris",
            start_date=date(2025, 6, 1),
            end_date=date(2025, 6, 5),
            travelers=1,
        )

        # June 1-5 = 5 days inclusive
        assert summary.duration_days == 5

    def test_trip_summary_duration_days_same_day(self):
        """Test duration_days for same-day trip."""
        summary = TripSummary(
            destination="Tokyo",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 10),
            travelers=1,
        )

        assert summary.duration_days == 1

    def test_trip_summary_serialization_roundtrip(self):
        """Test serialization/deserialization roundtrip."""
        original = TripSummary(
            destination="Tokyo",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 17),
            travelers=2,
            trip_type="business",
        )

        data = original.to_dict()
        restored = TripSummary.from_dict(data)

        assert restored.destination == original.destination
        assert restored.start_date == original.start_date
        assert restored.end_date == original.end_date
        assert restored.travelers == original.travelers
        assert restored.trip_type == original.trip_type

    def test_trip_summary_from_dict_defaults(self):
        """Test from_dict handles missing fields with defaults."""
        summary = TripSummary.from_dict({})

        assert summary.destination == ""
        assert summary.start_date == date.min
        assert summary.travelers == 1
        assert summary.trip_type == "leisure"


class TestItineraryActivity:
    """Tests for ItineraryActivity."""

    def test_activity_creation(self):
        """Test creating an activity."""
        activity = ItineraryActivity(
            name="Visit Senso-ji Temple",
            location="Asakusa",
            description="Historic Buddhist temple",
            start_time="09:00",
            end_time="11:00",
            estimated_cost=0.0,
            currency="JPY",
            booking_required=False,
            notes="Arrive early to avoid crowds",
        )

        assert activity.name == "Visit Senso-ji Temple"
        assert activity.location == "Asakusa"
        assert activity.start_time == "09:00"
        assert activity.booking_required is False

    def test_activity_serialization_roundtrip(self):
        """Test activity serialization roundtrip."""
        original = ItineraryActivity(
            name="Cooking Class",
            location="Shibuya",
            description="Learn to make sushi",
            start_time="14:00",
            end_time="17:00",
            estimated_cost=100.0,
            currency="USD",
            booking_required=True,
            notes="Bring an apron",
        )

        data = original.to_dict()
        restored = ItineraryActivity.from_dict(data)

        assert restored.name == original.name
        assert restored.start_time == original.start_time
        assert restored.booking_required == original.booking_required
        assert restored.notes == original.notes


class TestItineraryMeal:
    """Tests for ItineraryMeal."""

    def test_meal_creation(self):
        """Test creating a meal recommendation."""
        meal = ItineraryMeal(
            meal_type="dinner",
            restaurant_name="Ichiran Ramen",
            cuisine="Japanese",
            location="Shibuya",
            estimated_cost=15.0,
            currency="USD",
            reservation_required=False,
        )

        assert meal.meal_type == "dinner"
        assert meal.restaurant_name == "Ichiran Ramen"
        assert meal.cuisine == "Japanese"

    def test_meal_serialization_roundtrip(self):
        """Test meal serialization roundtrip."""
        original = ItineraryMeal(
            meal_type="lunch",
            restaurant_name="Sukiyabashi Jiro",
            cuisine="Sushi",
            location="Ginza",
            estimated_cost=300.0,
            currency="USD",
            reservation_required=True,
            notes="Book 3 months in advance",
        )

        data = original.to_dict()
        restored = ItineraryMeal.from_dict(data)

        assert restored.meal_type == original.meal_type
        assert restored.restaurant_name == original.restaurant_name
        assert restored.reservation_required == original.reservation_required
        assert restored.notes == original.notes

    def test_meal_from_dict_invalid_meal_type(self):
        """Test from_dict handles invalid meal type."""
        data = {
            "meal_type": "brunch",  # Invalid
            "restaurant_name": "Test",
        }

        meal = ItineraryMeal.from_dict(data)
        assert meal.meal_type == "lunch"  # Defaults to lunch


class TestItineraryTransport:
    """Tests for ItineraryTransport."""

    def test_transport_creation(self):
        """Test creating a transport segment."""
        transport = ItineraryTransport(
            mode="flight",
            from_location="San Francisco (SFO)",
            to_location="Tokyo (NRT)",
            departure_time="2025-03-10T10:00:00",
            arrival_time="2025-03-11T14:00:00",
            carrier="Japan Airlines",
            estimated_cost=1200.0,
            currency="USD",
        )

        assert transport.mode == "flight"
        assert transport.from_location == "San Francisco (SFO)"
        assert transport.carrier == "Japan Airlines"

    def test_transport_serialization_roundtrip(self):
        """Test transport serialization roundtrip."""
        original = ItineraryTransport(
            mode="train",
            from_location="Tokyo Station",
            to_location="Kyoto Station",
            departure_time="2025-03-12T08:30:00",
            arrival_time="2025-03-12T10:45:00",
            carrier="JR Shinkansen",
            booking_reference="ABC123",
            estimated_cost=130.0,
            currency="USD",
            notes="Reserve window seat",
        )

        data = original.to_dict()
        restored = ItineraryTransport.from_dict(data)

        assert restored.mode == original.mode
        assert restored.carrier == original.carrier
        assert restored.booking_reference == original.booking_reference
        assert restored.notes == original.notes


class TestItineraryAccommodation:
    """Tests for ItineraryAccommodation."""

    def test_accommodation_creation(self):
        """Test creating accommodation details."""
        accommodation = ItineraryAccommodation(
            name="Park Hyatt Tokyo",
            location="Shinjuku",
            check_in="2025-03-10T15:00:00",
            check_out="2025-03-14T11:00:00",
            room_type="Deluxe King",
            estimated_cost=1500.0,
            currency="USD",
        )

        assert accommodation.name == "Park Hyatt Tokyo"
        assert accommodation.location == "Shinjuku"
        assert accommodation.room_type == "Deluxe King"

    def test_accommodation_serialization_roundtrip(self):
        """Test accommodation serialization roundtrip."""
        original = ItineraryAccommodation(
            name="Hoshinoya Tokyo",
            location="Otemachi",
            check_in="2025-03-14T15:00:00",
            check_out="2025-03-17T11:00:00",
            room_type="Yagura Suite",
            estimated_cost=2000.0,
            currency="USD",
            booking_reference="HT12345",
            notes="Request high floor",
        )

        data = original.to_dict()
        restored = ItineraryAccommodation.from_dict(data)

        assert restored.name == original.name
        assert restored.booking_reference == original.booking_reference
        assert restored.notes == original.notes


class TestItineraryDay:
    """Tests for ItineraryDay."""

    def test_itinerary_day_creation(self):
        """Test creating an itinerary day."""
        day = ItineraryDay(
            day_number=1,
            date=date(2025, 3, 10),
            title="Arrival & Exploring Shibuya",
            activities=[
                ItineraryActivity(name="Visit Shibuya Crossing", location="Shibuya")
            ],
            meals=[
                ItineraryMeal(meal_type="dinner", restaurant_name="Ichiran Ramen")
            ],
            transport=[
                ItineraryTransport(
                    mode="taxi", from_location="NRT Airport", to_location="Hotel"
                )
            ],
            accommodation=ItineraryAccommodation(name="Park Hyatt", location="Shinjuku"),
            estimated_daily_cost=500.0,
            currency="USD",
        )

        assert day.day_number == 1
        assert day.title == "Arrival & Exploring Shibuya"
        assert len(day.activities) == 1
        assert len(day.meals) == 1
        assert len(day.transport) == 1
        assert day.accommodation is not None

    def test_itinerary_day_serialization_roundtrip(self):
        """Test day serialization roundtrip."""
        original = ItineraryDay(
            day_number=2,
            date=date(2025, 3, 11),
            title="Temple Day",
            activities=[
                ItineraryActivity(
                    name="Senso-ji Temple",
                    location="Asakusa",
                    estimated_cost=0.0,
                )
            ],
            meals=[
                ItineraryMeal(
                    meal_type="breakfast",
                    restaurant_name="Hotel Breakfast",
                ),
                ItineraryMeal(
                    meal_type="lunch",
                    restaurant_name="Local Ramen Shop",
                ),
            ],
            notes="Wear comfortable shoes",
            estimated_daily_cost=150.0,
        )

        data = original.to_dict()
        restored = ItineraryDay.from_dict(data)

        assert restored.day_number == original.day_number
        assert restored.date == original.date
        assert restored.title == original.title
        assert len(restored.activities) == 1
        assert len(restored.meals) == 2
        assert restored.notes == original.notes

    def test_itinerary_day_from_dict_minimal(self):
        """Test day from_dict with minimal data."""
        day = ItineraryDay.from_dict({
            "day_number": 1,
            "date": "2025-03-10",
        })

        assert day.day_number == 1
        assert day.date == date(2025, 3, 10)
        assert day.activities == []
        assert day.meals == []
        assert day.transport == []
        assert day.accommodation is None


class TestItineraryGapCreation:
    """Tests for ItineraryGap creation."""

    def test_itinerary_gap_creation(self):
        """Test creating an itinerary gap."""
        gap = ItineraryGap(
            category="transport",
            description="No flights found for this route",
            severity="blocker",
            suggestions=["Consider nearby airports", "Try different dates"],
        )

        assert gap.category == "transport"
        assert gap.description == "No flights found for this route"
        assert gap.severity == "blocker"
        assert len(gap.suggestions) == 2

    def test_itinerary_gap_is_blocker(self):
        """Test is_blocker method."""
        blocker = ItineraryGap(
            category="stay",
            description="No hotels available",
            severity="blocker",
        )
        warning = ItineraryGap(
            category="poi",
            description="Limited attractions found",
            severity="warning",
        )

        assert blocker.is_blocker() is True
        assert warning.is_blocker() is False

    def test_itinerary_gap_serialization_roundtrip(self):
        """Test gap serialization roundtrip."""
        original = ItineraryGap(
            category="dining",
            description="Few vegetarian options found",
            severity="warning",
            suggestions=["Consider flexible dietary preferences"],
        )

        data = original.to_dict()
        restored = ItineraryGap.from_dict(data)

        assert restored.category == original.category
        assert restored.description == original.description
        assert restored.severity == original.severity
        assert restored.suggestions == original.suggestions

    def test_itinerary_gap_from_dict_invalid_severity(self):
        """Test from_dict handles invalid severity."""
        data = {
            "category": "events",
            "description": "No events found",
            "severity": "critical",  # Invalid
        }

        gap = ItineraryGap.from_dict(data)
        assert gap.severity == "warning"  # Defaults to warning


class TestItineraryDraftCreation:
    """Tests for ItineraryDraft creation."""

    def test_itinerary_draft_creation(self):
        """Test creating an itinerary draft."""
        draft = ItineraryDraft(
            consultation_id="cons_abc123def456",
            trip_summary=TripSummary(
                destination="Tokyo",
                start_date=date(2025, 3, 10),
                end_date=date(2025, 3, 17),
                travelers=2,
            ),
            days=[
                ItineraryDay(day_number=1, date=date(2025, 3, 10)),
                ItineraryDay(day_number=2, date=date(2025, 3, 11)),
            ],
            total_estimated_cost=5000.0,
        )

        assert draft.consultation_id == "cons_abc123def456"
        assert draft.trip_summary.destination == "Tokyo"
        assert len(draft.days) == 2
        assert draft.total_estimated_cost == 5000.0
        assert draft.gaps is None

    def test_itinerary_draft_with_gaps(self):
        """Test creating draft with gaps from partial discovery."""
        draft = ItineraryDraft(
            consultation_id="cons_xyz789",
            trip_summary=TripSummary(
                destination="Kyoto",
                start_date=date(2025, 4, 1),
                end_date=date(2025, 4, 5),
                travelers=1,
            ),
            days=[ItineraryDay(day_number=1, date=date(2025, 4, 1))],
            total_estimated_cost=2000.0,
            gaps=[
                ItineraryGap(
                    category="transport",
                    description="No direct flights",
                    severity="warning",
                ),
                ItineraryGap(
                    category="stay",
                    description="Limited availability",
                    severity="blocker",
                ),
            ],
        )

        assert draft.has_blockers() is True
        assert len(draft.get_blockers()) == 1
        assert len(draft.get_warnings()) == 1

    def test_itinerary_draft_no_blockers(self):
        """Test has_blockers returns False when no blockers."""
        draft = ItineraryDraft(
            consultation_id="cons_test",
            trip_summary=TripSummary(
                destination="Paris",
                start_date=date(2025, 5, 1),
                end_date=date(2025, 5, 7),
                travelers=2,
            ),
            days=[],
            total_estimated_cost=3000.0,
            gaps=[
                ItineraryGap(
                    category="dining",
                    description="Limited options",
                    severity="warning",
                )
            ],
        )

        assert draft.has_blockers() is False
        assert len(draft.get_blockers()) == 0
        assert len(draft.get_warnings()) == 1


class TestDraftToItineraryConversion:
    """Tests for ItineraryDraft.to_itinerary() conversion."""

    def test_draft_to_itinerary_conversion(self):
        """Test converting draft to approved itinerary."""
        draft = ItineraryDraft(
            consultation_id="cons_abc123",
            trip_summary=TripSummary(
                destination="Tokyo",
                start_date=date(2025, 3, 10),
                end_date=date(2025, 3, 17),
                travelers=2,
            ),
            days=[
                ItineraryDay(day_number=1, date=date(2025, 3, 10), title="Day 1"),
                ItineraryDay(day_number=2, date=date(2025, 3, 11), title="Day 2"),
            ],
            total_estimated_cost=5000.0,
        )

        itinerary = draft.to_itinerary(
            itinerary_id="itn_xyz789",
            booking_ids=["book_001", "book_002"],
        )

        assert itinerary.itinerary_id == "itn_xyz789"
        assert itinerary.consultation_id == "cons_abc123"
        assert itinerary.trip_summary.destination == "Tokyo"
        assert len(itinerary.days) == 2
        assert itinerary.booking_ids == ["book_001", "book_002"]
        assert itinerary.total_estimated_cost == 5000.0
        assert itinerary.approved_at is not None

    def test_draft_to_itinerary_generates_id(self):
        """Test to_itinerary generates ID if not provided."""
        draft = ItineraryDraft(
            consultation_id="cons_test",
            trip_summary=TripSummary(
                destination="Paris",
                start_date=date(2025, 5, 1),
                end_date=date(2025, 5, 7),
                travelers=1,
            ),
            days=[],
            total_estimated_cost=2000.0,
        )

        itinerary = draft.to_itinerary()

        assert itinerary.itinerary_id.startswith("itn_")
        assert len(itinerary.itinerary_id) == 36  # itn_ + 32 hex chars
        assert itinerary.booking_ids == []


class TestItineraryCreation:
    """Tests for Itinerary creation."""

    def test_itinerary_creation(self):
        """Test creating an approved itinerary."""
        itinerary = Itinerary(
            itinerary_id="itn_abc123def456789012345678901234",
            consultation_id="cons_xyz789",
            approved_at=datetime(2025, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
            trip_summary=TripSummary(
                destination="Tokyo",
                start_date=date(2025, 3, 10),
                end_date=date(2025, 3, 17),
                travelers=2,
            ),
            days=[
                ItineraryDay(day_number=1, date=date(2025, 3, 10)),
            ],
            booking_ids=["book_001", "book_002", "book_003"],
            total_estimated_cost=5000.0,
        )

        assert itinerary.itinerary_id == "itn_abc123def456789012345678901234"
        assert itinerary.consultation_id == "cons_xyz789"
        assert len(itinerary.booking_ids) == 3
        assert itinerary.duration_days == 8

    def test_itinerary_str_representation(self):
        """Test string representation."""
        itinerary = Itinerary(
            itinerary_id="itn_test123",
            consultation_id="cons_test",
            approved_at=datetime.now(timezone.utc),
            trip_summary=TripSummary(
                destination="Tokyo",
                start_date=date(2025, 3, 10),
                end_date=date(2025, 3, 17),
                travelers=2,
            ),
            days=[
                ItineraryDay(day_number=1, date=date(2025, 3, 10)),
                ItineraryDay(day_number=2, date=date(2025, 3, 11)),
            ],
            booking_ids=["book_1"],
        )

        result = str(itinerary)
        assert "itn_test123" in result
        assert "Tokyo" in result
        assert "2 days" in result
        assert "1 bookings" in result


class TestItinerarySerialization:
    """Tests for Itinerary serialization."""

    def test_itinerary_serialization_roundtrip(self):
        """Test itinerary serialization/deserialization roundtrip."""
        original = Itinerary(
            itinerary_id="itn_roundtrip123",
            consultation_id="cons_roundtrip",
            approved_at=datetime(2025, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
            trip_summary=TripSummary(
                destination="Kyoto",
                start_date=date(2025, 4, 1),
                end_date=date(2025, 4, 5),
                travelers=2,
                trip_type="cultural",
            ),
            days=[
                ItineraryDay(
                    day_number=1,
                    date=date(2025, 4, 1),
                    title="Arrival",
                    activities=[
                        ItineraryActivity(name="Temple Visit", location="Kinkaku-ji")
                    ],
                )
            ],
            booking_ids=["book_a", "book_b"],
            share_token="share_xyz",
            total_estimated_cost=3000.0,
        )

        data = original.to_dict()
        restored = Itinerary.from_dict(data)

        assert restored.itinerary_id == original.itinerary_id
        assert restored.consultation_id == original.consultation_id
        assert restored.trip_summary.destination == original.trip_summary.destination
        assert len(restored.days) == len(original.days)
        assert restored.days[0].title == "Arrival"
        assert len(restored.days[0].activities) == 1
        assert restored.booking_ids == original.booking_ids
        assert restored.share_token == original.share_token

    def test_itinerary_to_dict_includes_cosmos_fields(self):
        """Test to_dict includes Cosmos DB required fields."""
        itinerary = Itinerary(
            itinerary_id="itn_cosmos123",
            consultation_id="cons_cosmos",
            approved_at=datetime.now(timezone.utc),
            trip_summary=TripSummary(
                destination="Tokyo",
                start_date=date(2025, 3, 10),
                end_date=date(2025, 3, 17),
                travelers=1,
            ),
            days=[],
            booking_ids=[],
        )

        data = itinerary.to_dict()

        assert "id" in data  # Cosmos document ID
        assert data["id"] == "itn_cosmos123"
        assert "ttl" in data  # TTL for auto-cleanup
        assert data["ttl"] > 0

    def test_itinerary_from_dict_uses_id_field(self):
        """Test from_dict can use 'id' field as fallback for itinerary_id."""
        data = {
            "id": "itn_from_id_field",
            "consultation_id": "cons_test",
            "approved_at": "2025-03-01T12:00:00+00:00",
            "trip_summary": {
                "destination": "Paris",
                "start_date": "2025-05-01",
                "end_date": "2025-05-05",
                "travelers": 1,
            },
            "days": [],
            "booking_ids": [],
        }

        itinerary = Itinerary.from_dict(data)
        assert itinerary.itinerary_id == "itn_from_id_field"


class TestItineraryDraftSerialization:
    """Tests for ItineraryDraft serialization."""

    def test_draft_serialization_roundtrip(self):
        """Test draft serialization/deserialization roundtrip."""
        original = ItineraryDraft(
            consultation_id="cons_draft123",
            trip_summary=TripSummary(
                destination="Rome",
                start_date=date(2025, 6, 1),
                end_date=date(2025, 6, 7),
                travelers=4,
            ),
            days=[
                ItineraryDay(
                    day_number=1,
                    date=date(2025, 6, 1),
                    title="Colosseum Day",
                )
            ],
            total_estimated_cost=8000.0,
            gaps=[
                ItineraryGap(
                    category="transport",
                    description="Consider local transport",
                    severity="warning",
                )
            ],
            created_at=datetime(2025, 2, 15, 10, 0, 0, tzinfo=timezone.utc),
        )

        data = original.to_dict()
        restored = ItineraryDraft.from_dict(data)

        assert restored.consultation_id == original.consultation_id
        assert restored.trip_summary.destination == original.trip_summary.destination
        assert len(restored.days) == 1
        assert restored.total_estimated_cost == original.total_estimated_cost
        assert len(restored.gaps) == 1
        assert restored.gaps[0].category == "transport"

    def test_draft_from_dict_handles_missing_gaps(self):
        """Test from_dict handles missing gaps field."""
        data = {
            "consultation_id": "cons_no_gaps",
            "trip_summary": {
                "destination": "London",
                "start_date": "2025-07-01",
                "end_date": "2025-07-05",
                "travelers": 2,
            },
            "days": [],
            "total_estimated_cost": 2500.0,
        }

        draft = ItineraryDraft.from_dict(data)
        assert draft.gaps is None
        assert draft.has_blockers() is False


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_itinerary_day_list(self):
        """Test itinerary with no days."""
        draft = ItineraryDraft(
            consultation_id="cons_empty",
            trip_summary=TripSummary(
                destination="Nowhere",
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 1),
                travelers=1,
            ),
            days=[],
            total_estimated_cost=0.0,
        )

        assert len(draft.days) == 0
        itinerary = draft.to_itinerary()
        assert len(itinerary.days) == 0

    def test_unicode_content_in_itinerary(self):
        """Test handling of unicode content."""
        draft = ItineraryDraft(
            consultation_id="cons_unicode",
            trip_summary=TripSummary(
                destination="東京",
                start_date=date(2025, 3, 10),
                end_date=date(2025, 3, 17),
                travelers=2,
            ),
            days=[
                ItineraryDay(
                    day_number=1,
                    date=date(2025, 3, 10),
                    title="浅草寺を訪問",
                    activities=[
                        ItineraryActivity(
                            name="浅草寺",
                            location="浅草",
                            description="有名な寺院",
                        )
                    ],
                )
            ],
            total_estimated_cost=500000.0,
        )

        data = draft.to_dict()
        restored = ItineraryDraft.from_dict(data)

        assert restored.trip_summary.destination == "東京"
        assert restored.days[0].title == "浅草寺を訪問"
        assert restored.days[0].activities[0].name == "浅草寺"

    def test_large_itinerary(self):
        """Test handling of large itinerary with many days."""
        days = [
            ItineraryDay(
                day_number=i,
                date=date(2025, 1, 1) + __import__("datetime").timedelta(days=i - 1),
                title=f"Day {i}",
                activities=[
                    ItineraryActivity(name=f"Activity {j}", location=f"Location {j}")
                    for j in range(5)
                ],
                meals=[
                    ItineraryMeal(meal_type="breakfast", restaurant_name=f"Breakfast {i}"),
                    ItineraryMeal(meal_type="lunch", restaurant_name=f"Lunch {i}"),
                    ItineraryMeal(meal_type="dinner", restaurant_name=f"Dinner {i}"),
                ],
            )
            for i in range(1, 31)  # 30 days
        ]

        draft = ItineraryDraft(
            consultation_id="cons_large",
            trip_summary=TripSummary(
                destination="World Tour",
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 30),
                travelers=1,
            ),
            days=days,
            total_estimated_cost=50000.0,
        )

        assert len(draft.days) == 30

        data = draft.to_dict()
        restored = ItineraryDraft.from_dict(data)

        assert len(restored.days) == 30
        assert len(restored.days[0].activities) == 5
        assert len(restored.days[0].meals) == 3

    def test_itinerary_with_share_token(self):
        """Test itinerary with share token."""
        itinerary = Itinerary(
            itinerary_id="itn_shared",
            consultation_id="cons_shared",
            approved_at=datetime.now(timezone.utc),
            trip_summary=TripSummary(
                destination="Barcelona",
                start_date=date(2025, 8, 1),
                end_date=date(2025, 8, 5),
                travelers=2,
            ),
            days=[],
            booking_ids=[],
            share_token="share_token_abc123",
        )

        assert itinerary.share_token == "share_token_abc123"

        data = itinerary.to_dict()
        assert data["share_token"] == "share_token_abc123"

        restored = Itinerary.from_dict(data)
        assert restored.share_token == "share_token_abc123"

    def test_draft_created_at_timezone_handling(self):
        """Test created_at timezone handling."""
        # Without timezone
        data_no_tz = {
            "consultation_id": "cons_tz",
            "trip_summary": {
                "destination": "Test",
                "start_date": "2025-01-01",
                "end_date": "2025-01-02",
                "travelers": 1,
            },
            "days": [],
            "total_estimated_cost": 0.0,
            "created_at": "2025-02-15T10:00:00",  # No timezone
        }

        draft = ItineraryDraft.from_dict(data_no_tz)
        assert draft.created_at.tzinfo is not None  # Should have UTC timezone

        # With timezone
        data_with_tz = {
            "consultation_id": "cons_tz2",
            "trip_summary": {
                "destination": "Test",
                "start_date": "2025-01-01",
                "end_date": "2025-01-02",
                "travelers": 1,
            },
            "days": [],
            "total_estimated_cost": 0.0,
            "created_at": "2025-02-15T10:00:00+00:00",
        }

        draft2 = ItineraryDraft.from_dict(data_with_tz)
        assert draft2.created_at.tzinfo is not None


class TestItineraryDraftIncludesGaps:
    """Tests for ItineraryDraft gap handling - ORCH-080 acceptance criteria."""

    def test_itinerary_draft_includes_gaps(self):
        """Test that ItineraryDraft properly includes gaps from partial discovery."""
        draft = ItineraryDraft(
            consultation_id="cons_gaps_test",
            trip_summary=TripSummary(
                destination="Tokyo",
                start_date=date(2025, 3, 10),
                end_date=date(2025, 3, 17),
                travelers=2,
            ),
            days=[
                ItineraryDay(
                    day_number=1,
                    date=date(2025, 3, 10),
                    title="Arrival Day",
                )
            ],
            total_estimated_cost=3000.0,
            gaps=[
                ItineraryGap(
                    category="transport",
                    description="No direct flights found - connection required",
                    severity="warning",
                    suggestions=["Consider nearby airports", "Try flexible dates"],
                ),
                ItineraryGap(
                    category="stay",
                    description="Limited hotel availability for these dates",
                    severity="blocker",
                    suggestions=["Adjust dates", "Consider alternative areas"],
                ),
            ],
        )

        # Verify gaps are included
        assert draft.gaps is not None
        assert len(draft.gaps) == 2

        # Verify gap categories
        categories = [gap.category for gap in draft.gaps]
        assert "transport" in categories
        assert "stay" in categories

        # Verify severity classification
        assert draft.has_blockers() is True
        blockers = draft.get_blockers()
        warnings = draft.get_warnings()
        assert len(blockers) == 1
        assert len(warnings) == 1
        assert blockers[0].category == "stay"
        assert warnings[0].category == "transport"

        # Verify suggestions are preserved
        transport_gap = next(g for g in draft.gaps if g.category == "transport")
        assert transport_gap.suggestions is not None
        assert len(transport_gap.suggestions) == 2


class TestItineraryDayStructure:
    """Tests for ItineraryDay structure - ORCH-080 acceptance criteria."""

    def test_itinerary_day_structure(self):
        """Test that ItineraryDay contains proper day-by-day structure with time slots."""
        day = ItineraryDay(
            day_number=1,
            date=date(2025, 3, 10),
            title="Tokyo Exploration",
            activities=[
                ItineraryActivity(
                    name="Visit Senso-ji Temple",
                    location="Asakusa",
                    description="Ancient Buddhist temple",
                    start_time="09:00",
                    end_time="11:00",
                    estimated_cost=0.0,
                ),
                ItineraryActivity(
                    name="TeamLab Borderless",
                    location="Odaiba",
                    description="Digital art museum",
                    start_time="14:00",
                    end_time="17:00",
                    estimated_cost=35.0,
                    booking_required=True,
                ),
            ],
            meals=[
                ItineraryMeal(
                    meal_type="breakfast",
                    restaurant_name="Hotel Breakfast",
                ),
                ItineraryMeal(
                    meal_type="lunch",
                    restaurant_name="Ramen Shop",
                    location="Shibuya",
                ),
                ItineraryMeal(
                    meal_type="dinner",
                    restaurant_name="Izakaya",
                    location="Shinjuku",
                ),
            ],
            transport=[
                ItineraryTransport(
                    mode="taxi",
                    from_location="NRT Airport",
                    to_location="Hotel",
                    departure_time="2025-03-10T10:00:00",
                    arrival_time="2025-03-10T11:30:00",
                    estimated_cost=200.0,
                ),
            ],
            accommodation=ItineraryAccommodation(
                name="Park Hyatt Tokyo",
                location="Shinjuku",
                check_in="2025-03-10T15:00:00",
                room_type="Deluxe King",
                estimated_cost=500.0,
            ),
            estimated_daily_cost=735.0,
        )

        # Verify day structure
        assert day.day_number == 1
        assert day.date == date(2025, 3, 10)
        assert day.title == "Tokyo Exploration"

        # Verify activities with time slots
        assert len(day.activities) == 2
        assert day.activities[0].start_time == "09:00"
        assert day.activities[0].end_time == "11:00"
        assert day.activities[1].start_time == "14:00"

        # Verify meals structure
        assert len(day.meals) == 3
        meal_types = [m.meal_type for m in day.meals]
        assert "breakfast" in meal_types
        assert "lunch" in meal_types
        assert "dinner" in meal_types

        # Verify transport
        assert len(day.transport) == 1
        assert day.transport[0].mode == "taxi"
        assert day.transport[0].departure_time is not None

        # Verify accommodation
        assert day.accommodation is not None
        assert day.accommodation.name == "Park Hyatt Tokyo"
        assert day.accommodation.check_in is not None

        # Verify daily cost
        assert day.estimated_daily_cost == 735.0


class TestTimeSlotBookingFlag:
    """Tests for time slot booking flag - ORCH-080 acceptance criteria."""

    def test_time_slot_booking_flag(self):
        """Test that activities have location, time, duration, and bookable flag."""
        # Bookable activity
        bookable_activity = ItineraryActivity(
            name="TeamLab Borderless",
            location="Odaiba",
            description="Digital art museum",
            start_time="14:00",
            end_time="17:00",
            estimated_cost=35.0,
            currency="USD",
            booking_required=True,
            notes="Tickets required",
        )

        # Non-bookable activity
        free_activity = ItineraryActivity(
            name="Walk through Shibuya",
            location="Shibuya",
            description="Explore the famous crossing",
            start_time="18:00",
            end_time="19:00",
            estimated_cost=0.0,
            booking_required=False,
        )

        # Verify bookable activity
        assert bookable_activity.location == "Odaiba"
        assert bookable_activity.start_time == "14:00"
        assert bookable_activity.end_time == "17:00"
        assert bookable_activity.booking_required is True

        # Verify free activity
        assert free_activity.location == "Shibuya"
        assert free_activity.start_time == "18:00"
        assert free_activity.end_time == "19:00"
        assert free_activity.booking_required is False

        # Verify serialization preserves booking flag
        bookable_data = bookable_activity.to_dict()
        assert bookable_data["booking_required"] is True

        free_data = free_activity.to_dict()
        assert free_data["booking_required"] is False

        # Verify deserialization preserves booking flag
        restored_bookable = ItineraryActivity.from_dict(bookable_data)
        assert restored_bookable.booking_required is True

        restored_free = ItineraryActivity.from_dict(free_data)
        assert restored_free.booking_required is False


class TestFormatForDisplayShowsPlaceholders:
    """Tests for format_for_display method - ORCH-080 acceptance criteria."""

    def test_format_for_display_shows_placeholders(self):
        """Test that format_for_display produces user-friendly preview with placeholders."""
        draft = ItineraryDraft(
            consultation_id="cons_display_test",
            trip_summary=TripSummary(
                destination="Tokyo",
                start_date=date(2025, 3, 10),
                end_date=date(2025, 3, 17),
                travelers=2,
                trip_type="leisure",
            ),
            days=[
                ItineraryDay(
                    day_number=1,
                    date=date(2025, 3, 10),
                    title="Arrival Day",
                    transport=[
                        ItineraryTransport(
                            mode="flight",
                            from_location="SFO",
                            to_location="NRT",
                            departure_time="2025-03-10T10:00:00",
                            arrival_time="2025-03-11T14:00:00",
                            booking_reference="placeholder",  # Indicates placeholder
                            estimated_cost=1200.0,
                        ),
                    ],
                    activities=[
                        ItineraryActivity(
                            name="Hotel Check-in",
                            location="Shinjuku",
                            start_time="15:00",
                        ),
                    ],
                    accommodation=ItineraryAccommodation(
                        name="Park Hyatt Tokyo",
                        location="Shinjuku",
                        check_in="2025-03-10T15:00:00",
                        estimated_cost=500.0,
                    ),
                    estimated_daily_cost=1700.0,
                ),
            ],
            total_estimated_cost=5000.0,
            gaps=[
                ItineraryGap(
                    category="transport",
                    description="Flight times are estimated",
                    severity="warning",
                    suggestions=["Confirm flight times"],
                ),
            ],
        )

        # Get formatted display
        display_text = draft.format_for_display()

        # Verify header
        assert "ITINERARY DRAFT" in display_text
        assert "Tokyo" in display_text

        # Verify trip summary
        assert "Destination: Tokyo" in display_text
        assert "Travelers: 2" in display_text
        assert "Trip Type: leisure" in display_text
        assert "$5,000.00" in display_text  # Total cost formatted

        # Verify day-by-day content
        assert "DAY 1" in display_text
        assert "Arrival Day" in display_text
        assert "Transport:" in display_text
        assert "FLIGHT" in display_text
        assert "SFO" in display_text
        assert "NRT" in display_text
        assert "[PLACEHOLDER]" in display_text  # Placeholder marker

        # Verify gaps section
        assert "WARNING" in display_text
        assert "TRANSPORT" in display_text
        assert "Flight times are estimated" in display_text

        # Verify accommodation section
        assert "Accommodation:" in display_text
        assert "Park Hyatt Tokyo" in display_text

    def test_format_for_display_with_blockers(self):
        """Test format_for_display highlights blocking gaps."""
        draft = ItineraryDraft(
            consultation_id="cons_blocker_test",
            trip_summary=TripSummary(
                destination="Kyoto",
                start_date=date(2025, 4, 1),
                end_date=date(2025, 4, 5),
                travelers=1,
            ),
            days=[],
            total_estimated_cost=2000.0,
            gaps=[
                ItineraryGap(
                    category="stay",
                    description="No hotels available for these dates",
                    severity="blocker",
                    suggestions=["Try different dates", "Consider nearby cities"],
                ),
            ],
        )

        display_text = draft.format_for_display()

        # Verify blocker is prominently displayed
        assert "BLOCKING ISSUES" in display_text
        assert "[BLOCKER]" in display_text
        assert "STAY" in display_text
        assert "No hotels available" in display_text
        assert "Try different dates" in display_text

    def test_format_for_display_no_gaps(self):
        """Test format_for_display works when there are no gaps."""
        draft = ItineraryDraft(
            consultation_id="cons_no_gaps",
            trip_summary=TripSummary(
                destination="Paris",
                start_date=date(2025, 5, 1),
                end_date=date(2025, 5, 5),
                travelers=2,
            ),
            days=[
                ItineraryDay(
                    day_number=1,
                    date=date(2025, 5, 1),
                    title="Arrival",
                ),
            ],
            total_estimated_cost=3000.0,
            gaps=None,
        )

        display_text = draft.format_for_display()

        # Verify no gap warnings
        assert "BLOCKING ISSUES" not in display_text
        assert "[BLOCKER]" not in display_text
        assert "WARNINGS" not in display_text

        # Verify basic content is present
        assert "Paris" in display_text
        assert "DAY 1" in display_text
        assert "Arrival" in display_text
