"""Unit tests for shared models and enums."""
from datetime import datetime, timedelta
import json
import pytest
from pydantic import ValidationError

from src.shared.models import (
    # Enums
    ConsultationStatus,
    BookingStatus,
    BookingAction,
    IntentType,
    HealthStatus,
    # Core models
    Source,
    TripSpec,
    Booking,
    Consultation,
    WorkflowState,
    OrchestratorContext,
    HumanApprovalRequest,
    # Discovery models
    DiscoveryResults,
    SearchOutput,
    StayOutput,
    TransportOutput,
    EventsOutput,
    DiningOutput,
    DiningItem,
    POI,
    # Itinerary models
    ItinerarySlot,
    ItineraryDay,
    Itinerary,
    # Planning models
    BudgetProposal,
    BudgetTracking,
    BudgetCategoryAmount,
    ValidationResult,
    # Health check
    HealthResponse,
)


# ======= Enum Tests =======
class TestConsultationStatus:
    """Tests for ConsultationStatus enum."""

    def test_all_values_exist(self):
        """Verify all required status values exist."""
        expected_values = [
            "draft", "planning", "ready_to_book", "partially_booked",
            "fully_booked", "cancelled", "expired", "archived"
        ]
        actual_values = [status.value for status in ConsultationStatus]
        assert set(expected_values) == set(actual_values)

    def test_enum_is_string_subclass(self):
        """Verify enum values can be used as strings."""
        assert ConsultationStatus.DRAFT == "draft"
        assert ConsultationStatus.PLANNING.value == "planning"

    def test_enum_from_string(self):
        """Verify enum can be created from string value."""
        assert ConsultationStatus("draft") == ConsultationStatus.DRAFT
        assert ConsultationStatus("fully_booked") == ConsultationStatus.FULLY_BOOKED


class TestBookingStatus:
    """Tests for BookingStatus enum."""

    def test_all_values_exist(self):
        """Verify all required status values exist."""
        expected_values = ["pending", "confirmed", "modified", "cancelled", "failed"]
        actual_values = [status.value for status in BookingStatus]
        assert set(expected_values) == set(actual_values)

    def test_enum_is_string_subclass(self):
        """Verify enum values can be used as strings."""
        assert BookingStatus.PENDING == "pending"
        assert BookingStatus.CONFIRMED == "confirmed"


class TestBookingAction:
    """Tests for BookingAction enum."""

    def test_all_values_exist(self):
        """Verify all required action values exist."""
        expected_values = ["create", "modify", "cancel"]
        actual_values = [action.value for action in BookingAction]
        assert set(expected_values) == set(actual_values)


class TestIntentType:
    """Tests for IntentType enum."""

    def test_workflow_intents_exist(self):
        """Verify workflow intents exist."""
        workflow_intents = [
            IntentType.START_TRIP_PLANNING,
            IntentType.CONTINUE_CLARIFICATION,
            IntentType.APPROVE_TRIP_SPEC,
            IntentType.APPROVE_ITINERARY,
            IntentType.START_BOOKING,
            IntentType.CONFIRM_BOOKING,
        ]
        assert all(intent in IntentType for intent in workflow_intents)

    def test_adhoc_query_intents_exist(self):
        """Verify ad-hoc query intents exist."""
        adhoc_intents = [
            IntentType.SEARCH_POI,
            IntentType.SEARCH_STAY,
            IntentType.SEARCH_TRANSPORT,
            IntentType.SEARCH_EVENTS,
            IntentType.SEARCH_DINING,
            IntentType.SPECIFY_ITEM,
            IntentType.CHECK_BUDGET,
            IntentType.MODIFY_TRIP,
        ]
        assert all(intent in IntentType for intent in adhoc_intents)

    def test_lifecycle_intents_exist(self):
        """Verify lifecycle intents exist."""
        lifecycle_intents = [
            IntentType.RESUME_SESSION,
            IntentType.EDIT_PENDING,
            IntentType.MODIFY_BOOKING,
            IntentType.CANCEL_BOOKING,
        ]
        assert all(intent in IntentType for intent in lifecycle_intents)

    def test_meta_intents_exist(self):
        """Verify meta intents exist."""
        meta_intents = [
            IntentType.HELP,
            IntentType.STATUS,
            IntentType.CANCEL,
        ]
        assert all(intent in IntentType for intent in meta_intents)


# ======= Booking Model Tests =======
class TestBooking:
    """Tests for Booking model."""

    def test_valid_booking_creation(self):
        """Test creating a valid booking."""
        booking = Booking(
            id="book_123",
            consultation_id="cons_456",
            type="flight",
            provider_ref="AA123",
            status=BookingStatus.CONFIRMED,
            details={"airline": "American Airlines"},
        )
        assert booking.id == "book_123"
        assert booking.consultation_id == "cons_456"
        assert booking.type == "flight"
        assert booking.status == BookingStatus.CONFIRMED
        assert booking.can_modify is True
        assert booking.can_cancel is True

    def test_id_prefix_validation(self):
        """Test that booking id must start with 'book_'."""
        with pytest.raises(ValidationError) as exc_info:
            Booking(
                id="invalid_123",
                consultation_id="cons_456",
                type="hotel",
            )
        assert "book_" in str(exc_info.value)

    def test_consultation_id_prefix_validation(self):
        """Test that consultation_id must start with 'cons_'."""
        with pytest.raises(ValidationError) as exc_info:
            Booking(
                id="book_123",
                consultation_id="invalid_456",
                type="hotel",
            )
        assert "cons_" in str(exc_info.value)

    def test_default_values(self):
        """Test default values are set correctly."""
        booking = Booking(
            id="book_001",
            consultation_id="cons_001",
            type="event",
        )
        assert booking.status == BookingStatus.PENDING
        assert booking.can_modify is True
        assert booking.can_cancel is True
        assert booking.details == {}
        assert booking.provider_ref is None
        assert booking.cancellation_policy is None
        assert booking.modification_fee is None

    def test_json_serialization(self):
        """Test booking can be serialized to JSON."""
        booking = Booking(
            id="book_123",
            consultation_id="cons_456",
            type="flight",
        )
        json_str = booking.model_dump_json()
        data = json.loads(json_str)
        assert data["id"] == "book_123"
        assert data["status"] == "pending"


# ======= Consultation Model Tests =======
class TestConsultation:
    """Tests for Consultation model."""

    def test_valid_consultation_creation(self):
        """Test creating a valid consultation."""
        now = datetime.now()
        expires = now + timedelta(days=7)
        consultation = Consultation(
            id="cons_123",
            session_id="session_abc",
            status=ConsultationStatus.DRAFT,
            created_at=now,
            expires_at=expires,
        )
        assert consultation.id == "cons_123"
        assert consultation.session_id == "session_abc"
        assert consultation.status == ConsultationStatus.DRAFT
        assert consultation.bookings == []

    def test_id_prefix_validation(self):
        """Test that consultation id must start with 'cons_'."""
        now = datetime.now()
        with pytest.raises(ValidationError) as exc_info:
            Consultation(
                id="invalid_123",
                session_id="session_abc",
                created_at=now,
                expires_at=now + timedelta(days=7),
            )
        assert "cons_" in str(exc_info.value)

    def test_with_trip_spec(self):
        """Test consultation with TripSpec."""
        now = datetime.now()
        trip_spec = TripSpec(
            destination_city="Tokyo",
            start_date="2025-11-10",
            end_date="2025-11-17",
            num_travelers=2,
            budget_per_person=3000.0,
            budget_currency="USD",
            origin_city="San Francisco",
            interests=["temples", "food"],
            constraints=["vegetarian"],
        )
        consultation = Consultation(
            id="cons_123",
            session_id="session_abc",
            trip_spec=trip_spec,
            status=ConsultationStatus.PLANNING,
            created_at=now,
            expires_at=now + timedelta(days=7),
        )
        assert consultation.trip_spec.destination_city == "Tokyo"

    def test_json_serialization(self):
        """Test consultation can be serialized to JSON."""
        now = datetime.now()
        consultation = Consultation(
            id="cons_123",
            session_id="session_abc",
            created_at=now,
            expires_at=now + timedelta(days=7),
        )
        json_str = consultation.model_dump_json()
        data = json.loads(json_str)
        assert data["id"] == "cons_123"
        assert data["status"] == "draft"


# ======= WorkflowState Tests =======
class TestWorkflowState:
    """Tests for WorkflowState model."""

    def test_valid_workflow_state(self):
        """Test creating a valid workflow state."""
        state = WorkflowState(
            current_phase="discovery",
            checkpoint="awaiting_tripspec_approval",
            retry_count=0,
        )
        assert state.current_phase == "discovery"
        assert state.checkpoint == "awaiting_tripspec_approval"
        assert state.retry_count == 0

    def test_default_values(self):
        """Test default values."""
        state = WorkflowState(current_phase="clarification")
        assert state.checkpoint is None
        assert state.retry_count == 0
        assert state.failed_agents == []
        assert state.cached_results == {}

    def test_with_cached_results(self):
        """Test workflow state with cached results."""
        state = WorkflowState(
            current_phase="planning",
            cached_results={
                "poi_agent": {"pois": []},
                "stay_agent": {"stays": []},
            },
        )
        assert "poi_agent" in state.cached_results


# ======= OrchestratorContext Tests =======
class TestOrchestratorContext:
    """Tests for OrchestratorContext model."""

    def test_valid_context(self):
        """Test creating a valid orchestrator context."""
        context = OrchestratorContext(
            session_id="session_123",
            consultation_id="cons_456",
            intent=IntentType.START_TRIP_PLANNING,
            intent_confidence=0.95,
        )
        assert context.session_id == "session_123"
        assert context.intent == IntentType.START_TRIP_PLANNING
        assert context.intent_confidence == 0.95

    def test_with_workflow_state(self):
        """Test context with workflow state."""
        state = WorkflowState(current_phase="discovery")
        context = OrchestratorContext(
            session_id="session_123",
            workflow_state=state,
        )
        assert context.workflow_state.current_phase == "discovery"


# ======= HumanApprovalRequest Tests =======
class TestHumanApprovalRequest:
    """Tests for HumanApprovalRequest model."""

    def test_trip_spec_approval(self):
        """Test trip spec approval request."""
        request = HumanApprovalRequest(
            checkpoint_type="trip_spec",
            consultation_id="cons_123",
            summary="7-day trip to Tokyo for 2 travelers",
            details={"budget": 6000, "dates": "Nov 10-17"},
            available_actions=["approve", "modify", "cancel"],
        )
        assert request.checkpoint_type == "trip_spec"
        assert "approve" in request.available_actions

    def test_itinerary_approval(self):
        """Test itinerary approval request."""
        request = HumanApprovalRequest(
            checkpoint_type="itinerary",
            consultation_id="cons_123",
            summary="Complete 7-day itinerary ready for review",
            available_actions=["approve_and_book", "modify_day", "change_hotel", "start_over"],
        )
        assert request.checkpoint_type == "itinerary"

    def test_booking_approval(self):
        """Test booking approval request."""
        request = HumanApprovalRequest(
            checkpoint_type="booking",
            consultation_id="cons_123",
            summary="Flight booking: AA123 SFO -> NRT",
            details={"price": 1200, "airline": "American Airlines"},
            available_actions=["book", "skip", "alternative"],
        )
        assert request.checkpoint_type == "booking"


# ======= DiscoveryResults Tests =======
class TestDiscoveryResults:
    """Tests for DiscoveryResults model."""

    def test_empty_discovery_results(self):
        """Test creating empty discovery results."""
        results = DiscoveryResults()
        assert results.pois is None
        assert results.stays is None
        assert results.transport is None
        assert results.events is None
        assert results.dining is None

    def test_partial_discovery_results(self):
        """Test discovery results with partial data (handles agent failures)."""
        source = Source(title="Test", url="https://example.com")
        poi = POI(name="Temple", source=source)
        search_output = SearchOutput(pois=[poi])

        results = DiscoveryResults(
            pois=search_output,
            # stays is None (agent failed)
            # transport is None (agent failed)
        )
        assert results.pois is not None
        assert len(results.pois.pois) == 1
        assert results.stays is None

    def test_full_discovery_results(self):
        """Test discovery results with all fields populated."""
        source = Source(title="Test", url="https://example.com")

        results = DiscoveryResults(
            pois=SearchOutput(pois=[POI(name="Temple", source=source)]),
            stays=StayOutput(),
            transport=TransportOutput(),
            events=EventsOutput(),
            dining=DiningOutput(),
        )
        assert results.pois is not None
        assert results.stays is not None
        assert results.transport is not None
        assert results.events is not None
        assert results.dining is not None


# ======= Itinerary Models Tests =======
class TestItinerarySlot:
    """Tests for ItinerarySlot model."""

    def test_valid_slot(self):
        """Test creating a valid itinerary slot."""
        slot = ItinerarySlot(
            start_time="09:00",
            end_time="11:00",
            activity="Visit Senso-ji Temple",
            location="Asakusa",
            category="poi",
            estimated_cost=0,
            currency="JPY",
        )
        assert slot.start_time == "09:00"
        assert slot.activity == "Visit Senso-ji Temple"
        assert slot.category == "poi"

    def test_slot_with_item_ref(self):
        """Test slot with reference to specific item."""
        slot = ItinerarySlot(
            start_time="12:00",
            end_time="13:30",
            activity="Lunch at Ramen Shop",
            category="dining",
            item_ref="dining_item_001",
        )
        assert slot.item_ref == "dining_item_001"


class TestItineraryDay:
    """Tests for ItineraryDay model."""

    def test_valid_day(self):
        """Test creating a valid itinerary day."""
        slots = [
            ItinerarySlot(
                start_time="09:00",
                end_time="11:00",
                activity="Morning activity",
                category="poi",
            ),
            ItinerarySlot(
                start_time="12:00",
                end_time="13:00",
                activity="Lunch",
                category="dining",
            ),
        ]
        day = ItineraryDay(
            date="2025-11-10",
            slots=slots,
            day_summary="First day exploring Asakusa area",
        )
        assert day.date == "2025-11-10"
        assert len(day.slots) == 2

    def test_empty_day(self):
        """Test day with no slots."""
        day = ItineraryDay(date="2025-11-10")
        assert day.slots == []
        assert day.day_summary is None


class TestItinerary:
    """Tests for Itinerary model."""

    def test_valid_itinerary(self):
        """Test creating a valid itinerary."""
        days = [
            ItineraryDay(date="2025-11-10"),
            ItineraryDay(date="2025-11-11"),
        ]
        itinerary = Itinerary(
            days=days,
            total_estimated_cost=3000,
            currency="USD",
        )
        assert len(itinerary.days) == 2
        assert itinerary.total_estimated_cost == 3000

    def test_empty_itinerary(self):
        """Test creating empty itinerary."""
        itinerary = Itinerary()
        assert itinerary.days == []
        assert itinerary.total_estimated_cost is None

    def test_json_serialization(self):
        """Test itinerary JSON serialization."""
        itinerary = Itinerary(
            days=[ItineraryDay(date="2025-11-10")],
            total_estimated_cost=1000,
            currency="USD",
        )
        json_str = itinerary.model_dump_json()
        data = json.loads(json_str)
        assert len(data["days"]) == 1
        assert data["total_estimated_cost"] == 1000


# ======= Budget Models Tests =======
class TestBudgetProposal:
    """Tests for BudgetProposal model."""

    def test_valid_proposal(self):
        """Test creating a valid budget proposal."""
        proposal = BudgetProposal(
            total_budget=6000,
            currency="USD",
            allocations=[
                BudgetCategoryAmount(category="accommodation", amount=1800),
                BudgetCategoryAmount(category="flights", amount=1600),
                BudgetCategoryAmount(category="activities", amount=1200),
                BudgetCategoryAmount(category="dining", amount=800),
                BudgetCategoryAmount(category="transport", amount=600),
            ],
            rationale="Based on 7-day trip for 2 travelers",
        )
        assert proposal.total_budget == 6000
        assert sum(a.amount for a in proposal.allocations) == 6000


class TestBudgetTracking:
    """Tests for BudgetTracking model."""

    def test_under_budget(self):
        """Test tracking when under budget."""
        tracking = BudgetTracking(
            total_budget=6000,
            total_spent=4500,
            currency="USD",
            by_category=[
                BudgetCategoryAmount(category="accommodation", amount=1500),
                BudgetCategoryAmount(category="flights", amount=1600),
                BudgetCategoryAmount(category="activities", amount=900),
                BudgetCategoryAmount(category="dining", amount=500),
            ],
            remaining=1500,
            over_budget=False,
        )
        assert tracking.remaining == 1500
        assert tracking.over_budget is False

    def test_over_budget(self):
        """Test tracking when over budget."""
        tracking = BudgetTracking(
            total_budget=6000,
            total_spent=6500,
            currency="USD",
            by_category=[
                BudgetCategoryAmount(category="accommodation", amount=2500),
                BudgetCategoryAmount(category="flights", amount=2000),
                BudgetCategoryAmount(category="other", amount=2000),
            ],
            remaining=-500,
            over_budget=True,
            warnings=["Over budget by $500"],
        )
        assert tracking.over_budget is True
        assert len(tracking.warnings) == 1


# ======= ValidationResult Tests =======
class TestValidationResult:
    """Tests for ValidationResult model."""

    def test_passed_validation(self):
        """Test validation that passed."""
        result = ValidationResult(
            passed=True,
            issues=[],
            warnings=["Consider booking activities in advance"],
        )
        assert result.passed is True
        assert len(result.issues) == 0
        assert len(result.warnings) == 1

    def test_failed_validation(self):
        """Test validation that failed."""
        result = ValidationResult(
            passed=False,
            issues=[
                "Total cost exceeds budget by $500",
                "Nov 13 has no activities scheduled",
            ],
            warnings=[],
        )
        assert result.passed is False
        assert len(result.issues) == 2

    def test_default_values(self):
        """Test default values."""
        result = ValidationResult(passed=True)
        assert result.issues == []
        assert result.warnings == []


# ======= DiningItem Tests =======
class TestDiningItem:
    """Tests for DiningItem model."""

    def test_valid_dining_item(self):
        """Test creating a valid dining item."""
        source = Source(title="TripAdvisor", url="https://tripadvisor.com/restaurant")
        item = DiningItem(
            name="Ichiran Ramen",
            area="Shibuya",
            cuisine="Japanese",
            priceRange="$$",
            dietaryOptions=["vegetarian_options"],
            link="https://ichiran.com",
            notes="Famous tonkotsu ramen chain",
            source=source,
        )
        assert item.name == "Ichiran Ramen"
        assert item.cuisine == "Japanese"
        assert "vegetarian_options" in item.dietaryOptions

    def test_dietary_options(self):
        """Test dining item with dietary options."""
        source = Source(title="Test", url="https://example.com")
        item = DiningItem(
            name="Vegan Restaurant",
            dietaryOptions=["vegan", "gluten_free", "nut_free"],
            link="https://example.com",
            source=source,
        )
        assert len(item.dietaryOptions) == 3


# ======= Model Import Tests =======
class TestModelImports:
    """Test that all models can be imported from the models module."""

    def test_enum_imports(self):
        """Test all enums are importable."""
        from src.shared.models import (
            ConsultationStatus,
            BookingStatus,
            BookingAction,
            IntentType,
        )
        assert ConsultationStatus is not None
        assert BookingStatus is not None
        assert BookingAction is not None
        assert IntentType is not None

    def test_model_imports(self):
        """Test all models are importable."""
        from src.shared.models import (
            Booking,
            Consultation,
            WorkflowState,
            OrchestratorContext,
            HumanApprovalRequest,
            DiscoveryResults,
            BudgetProposal,
            BudgetTracking,
            ItinerarySlot,
            ItineraryDay,
            Itinerary,
            ValidationResult,
            DiningItem,
            DiningOutput,
        )
        assert all([
            Booking, Consultation, WorkflowState, OrchestratorContext,
            HumanApprovalRequest, DiscoveryResults, BudgetProposal,
            BudgetTracking, ItinerarySlot, ItineraryDay, Itinerary,
            ValidationResult, DiningItem, DiningOutput,
        ])


# ======= Health Check Tests =======
class TestHealthStatus:
    """Tests for HealthStatus enum."""

    def test_all_values_exist(self):
        """Verify all health status values exist."""
        expected_values = ["healthy", "degraded", "unhealthy"]
        actual_values = [status.value for status in HealthStatus]
        assert actual_values == expected_values

    def test_is_string_enum(self):
        """Verify HealthStatus is a string enum."""
        assert HealthStatus.HEALTHY == "healthy"
        assert HealthStatus.DEGRADED == "degraded"
        assert HealthStatus.UNHEALTHY == "unhealthy"


class TestHealthResponse:
    """Tests for HealthResponse model."""

    def test_create_valid_health_response(self):
        """Test creating a valid HealthResponse."""
        response = HealthResponse(
            status=HealthStatus.HEALTHY,
            agent_name="Test Agent",
            version="1.0.0",
        )
        assert response.status == HealthStatus.HEALTHY
        assert response.agent_name == "Test Agent"
        assert response.version == "1.0.0"

    def test_default_status_is_healthy(self):
        """Test that default status is HEALTHY."""
        response = HealthResponse(agent_name="Test", version="1.0")
        assert response.status == HealthStatus.HEALTHY

    def test_json_serialization(self):
        """Test that HealthResponse serializes correctly to JSON."""
        response = HealthResponse(
            status=HealthStatus.HEALTHY,
            agent_name="POI Search Agent",
            version="1.0.0",
        )
        data = response.model_dump()
        assert data["status"] == "healthy"
        assert data["agent_name"] == "POI Search Agent"
        assert data["version"] == "1.0.0"

    def test_requires_agent_name(self):
        """Test that agent_name is required."""
        with pytest.raises(ValidationError):
            HealthResponse(version="1.0.0")

    def test_requires_version(self):
        """Test that version is required."""
        with pytest.raises(ValidationError):
            HealthResponse(agent_name="Test")

    def test_forbids_extra_fields(self):
        """Test that extra fields are forbidden."""
        with pytest.raises(ValidationError):
            HealthResponse(
                agent_name="Test",
                version="1.0.0",
                extra_field="not allowed",
            )


# ======= Routing Models Tests =======
class TestRoutingDecision:
    """Tests for RoutingDecision enum."""

    def test_all_values_exist(self):
        """Verify all routing decision values exist."""
        from src.shared.models import RoutingDecision
        expected_values = ["workflow", "agent", "tool", "clarify"]
        actual_values = [decision.value for decision in RoutingDecision]
        assert set(expected_values) == set(actual_values)

    def test_is_string_enum(self):
        """Verify RoutingDecision is a string enum."""
        from src.shared.models import RoutingDecision
        assert RoutingDecision.WORKFLOW == "workflow"
        assert RoutingDecision.AGENT == "agent"
        assert RoutingDecision.TOOL == "tool"
        assert RoutingDecision.CLARIFY == "clarify"

    def test_enum_from_string(self):
        """Verify enum can be created from string value."""
        from src.shared.models import RoutingDecision
        assert RoutingDecision("workflow") == RoutingDecision.WORKFLOW
        assert RoutingDecision("agent") == RoutingDecision.AGENT
        assert RoutingDecision("tool") == RoutingDecision.TOOL
        assert RoutingDecision("clarify") == RoutingDecision.CLARIFY


class TestRoutingResult:
    """Tests for RoutingResult model."""

    def test_workflow_routing(self):
        """Test routing result for workflow decision."""
        from src.shared.models import RoutingResult, RoutingDecision, IntentType
        result = RoutingResult(
            decision=RoutingDecision.WORKFLOW,
            confidence=0.95,
            intent=IntentType.START_TRIP_PLANNING,
        )
        assert result.decision == RoutingDecision.WORKFLOW
        assert result.confidence == 0.95
        assert result.intent == IntentType.START_TRIP_PLANNING
        assert result.target_agent is None
        assert result.target_tool is None
        assert result.clarification_prompt is None

    def test_agent_routing(self):
        """Test routing result for agent decision."""
        from src.shared.models import RoutingResult, RoutingDecision, IntentType
        result = RoutingResult(
            decision=RoutingDecision.AGENT,
            confidence=0.85,
            intent=IntentType.GENERAL_QUESTION,
            target_agent="poi_agent",
        )
        assert result.decision == RoutingDecision.AGENT
        assert result.target_agent == "poi_agent"
        assert result.intent == IntentType.GENERAL_QUESTION

    def test_tool_routing(self):
        """Test routing result for tool decision."""
        from src.shared.models import RoutingResult, RoutingDecision, IntentType
        result = RoutingResult(
            decision=RoutingDecision.TOOL,
            confidence=0.92,
            intent=IntentType.CURRENCY_CONVERT,
            target_tool="currency_convert",
        )
        assert result.decision == RoutingDecision.TOOL
        assert result.target_tool == "currency_convert"
        assert result.intent == IntentType.CURRENCY_CONVERT

    def test_clarify_routing(self):
        """Test routing result for clarify decision."""
        from src.shared.models import RoutingResult, RoutingDecision
        result = RoutingResult(
            decision=RoutingDecision.CLARIFY,
            confidence=0.45,
            clarification_prompt="Are you looking for hotel recommendations or do you want to start planning a trip?",
        )
        assert result.decision == RoutingDecision.CLARIFY
        assert result.confidence == 0.45
        assert "hotel" in result.clarification_prompt

    def test_confidence_bounds(self):
        """Test confidence must be between 0.0 and 1.0."""
        from src.shared.models import RoutingResult, RoutingDecision
        # Valid bounds
        RoutingResult(decision=RoutingDecision.WORKFLOW, confidence=0.0)
        RoutingResult(decision=RoutingDecision.WORKFLOW, confidence=1.0)
        RoutingResult(decision=RoutingDecision.WORKFLOW, confidence=0.5)

    def test_confidence_below_zero_fails(self):
        """Test confidence below 0.0 is rejected."""
        from src.shared.models import RoutingResult, RoutingDecision
        with pytest.raises(ValidationError):
            RoutingResult(decision=RoutingDecision.WORKFLOW, confidence=-0.1)

    def test_confidence_above_one_fails(self):
        """Test confidence above 1.0 is rejected."""
        from src.shared.models import RoutingResult, RoutingDecision
        with pytest.raises(ValidationError):
            RoutingResult(decision=RoutingDecision.WORKFLOW, confidence=1.1)

    def test_json_serialization(self):
        """Test routing result JSON serialization."""
        from src.shared.models import RoutingResult, RoutingDecision, IntentType
        result = RoutingResult(
            decision=RoutingDecision.AGENT,
            confidence=0.88,
            intent=IntentType.SEARCH_POI,
            target_agent="poi_agent",
        )
        data = result.model_dump()
        assert data["decision"] == "agent"
        assert data["confidence"] == 0.88
        assert data["intent"] == "search_poi"
        assert data["target_agent"] == "poi_agent"

    def test_forbids_extra_fields(self):
        """Test that extra fields are forbidden."""
        from src.shared.models import RoutingResult, RoutingDecision
        with pytest.raises(ValidationError):
            RoutingResult(
                decision=RoutingDecision.WORKFLOW,
                confidence=0.9,
                extra_field="not allowed",
            )


class TestIntentTypeExtensions:
    """Tests for new IntentType values added for three-tier routing."""

    def test_general_question_intent_exists(self):
        """Verify GENERAL_QUESTION intent exists."""
        assert IntentType.GENERAL_QUESTION == "general_question"
        assert IntentType("general_question") == IntentType.GENERAL_QUESTION

    def test_tool_intents_exist(self):
        """Verify tool intents exist."""
        tool_intents = [
            IntentType.CURRENCY_CONVERT,
            IntentType.WEATHER_LOOKUP,
            IntentType.TIMEZONE_INFO,
        ]
        assert all(intent in IntentType for intent in tool_intents)

    def test_currency_convert_intent(self):
        """Test CURRENCY_CONVERT intent value."""
        assert IntentType.CURRENCY_CONVERT == "currency_convert"

    def test_weather_lookup_intent(self):
        """Test WEATHER_LOOKUP intent value."""
        assert IntentType.WEATHER_LOOKUP == "weather_lookup"

    def test_timezone_info_intent(self):
        """Test TIMEZONE_INFO intent value."""
        assert IntentType.TIMEZONE_INFO == "timezone_info"

    def test_all_intent_types_count(self):
        """Verify total number of intent types after additions."""
        # 6 workflow + 8 ad-hoc + 4 lifecycle + 3 meta + 1 general question + 3 tool = 25
        assert len(IntentType) == 25


class TestRoutingModelImports:
    """Test that routing models can be imported."""

    def test_routing_decision_import(self):
        """Test RoutingDecision can be imported."""
        from src.shared.models import RoutingDecision
        assert RoutingDecision is not None

    def test_routing_result_import(self):
        """Test RoutingResult can be imported."""
        from src.shared.models import RoutingResult
        assert RoutingResult is not None

    def test_combined_import(self):
        """Test all routing models can be imported together."""
        from src.shared.models import (
            RoutingDecision,
            RoutingResult,
            IntentType,
        )
        assert all([RoutingDecision, RoutingResult, IntentType])
