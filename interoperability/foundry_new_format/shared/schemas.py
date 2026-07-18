# models.py (primitives only for structured output)
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import List, Optional, Literal, Union, Any
from pydantic import BaseModel, Field, ConfigDict


# ======= Enums =======
class ConsultationStatus(str, Enum):
    """Status of a travel consultation."""
    DRAFT = "draft"
    PLANNING = "planning"
    READY_TO_BOOK = "ready_to_book"
    PARTIALLY_BOOKED = "partially_booked"
    FULLY_BOOKED = "fully_booked"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    ARCHIVED = "archived"


class BookingStatus(str, Enum):
    """Status of an individual booking."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    MODIFIED = "modified"
    CANCELLED = "cancelled"
    FAILED = "failed"


class BookingAction(str, Enum):
    """Action to perform on a booking."""
    CREATE = "create"
    MODIFY = "modify"
    CANCEL = "cancel"


class BudgetMode(str, Enum):
    """Operating mode for the Budget Agent."""
    PROPOSE = "propose"
    VALIDATE = "validate"
    TRACK = "track"
    REALLOCATE = "reallocate"


class IntentType(str, Enum):
    """User intent types for orchestrator routing."""
    # Workflow intents
    START_TRIP_PLANNING = "start_trip_planning"
    CONTINUE_CLARIFICATION = "continue_clarification"
    APPROVE_TRIP_SPEC = "approve_trip_spec"
    APPROVE_ITINERARY = "approve_itinerary"
    START_BOOKING = "start_booking"
    CONFIRM_BOOKING = "confirm_booking"
    # Ad-hoc query intents
    SEARCH_POI = "search_poi"
    SEARCH_STAY = "search_stay"
    SEARCH_TRANSPORT = "search_transport"
    SEARCH_EVENTS = "search_events"
    SEARCH_DINING = "search_dining"
    SPECIFY_ITEM = "specify_item"
    CHECK_BUDGET = "check_budget"
    MODIFY_TRIP = "modify_trip"
    # Lifecycle intents
    RESUME_SESSION = "resume_session"
    EDIT_PENDING = "edit_pending"
    MODIFY_BOOKING = "modify_booking"
    CANCEL_BOOKING = "cancel_booking"
    # Meta intents
    HELP = "help"
    STATUS = "status"
    CANCEL = "cancel"
    # General question intents
    GENERAL_QUESTION = "general_question"
    # Tool intents
    CURRENCY_CONVERT = "currency_convert"
    WEATHER_LOOKUP = "weather_lookup"
    TIMEZONE_INFO = "timezone_info"


class RoutingDecision(str, Enum):
    """Routing decision for three-tier orchestrator routing."""
    WORKFLOW = "workflow"  # Route to workflow state machine
    AGENT = "agent"  # Route directly to a specialist agent
    TOOL = "tool"  # Route to a utility tool
    CLARIFY = "clarify"  # Ask user for clarification


# Common primitives
class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    url: str  # plain string


# Clarifier Agent
class TripSpec(BaseModel):
    """A model for the trip spec."""
    destination_city: str
    start_date: str  # YYYY-MM-DD
    end_date: str  # YYYY-MM-DD
    num_travelers: int
    budget_per_person: float
    budget_currency: str
    origin_city: str
    interests: List[str]
    constraints: List[str]

class ClarifierResponse(BaseModel):
    """A model for the clarifier response."""
    trip_spec: TripSpec
    response: str | None = None  # Optional response message to the user


# ======= Phase B - Option Discovery Concurrent =======
# Search Agent
class POI(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    area: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    estCost: Optional[float] = None
    currency: Optional[str] = None
    openHint: Optional[str] = None
    source: Source

class SearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pois: List[POI] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class POISearchResponse(BaseModel):
    """Structured response for the POI search agent."""
    model_config = ConfigDict(extra="forbid")
    search_output: Optional[SearchOutput] = None
    response: Optional[str] = None


# Stay Agent
class Neighborhood(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    reasons: List[str] = Field(default_factory=list)
    source: Source

class StayItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    area: str
    pricePerNight: Optional[float] = None
    currency: Optional[str] = None
    link: str
    notes: Optional[str] = None
    source: Source

class StayOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    neighborhoods: List[Neighborhood] = Field(default_factory=list)
    stays: List[StayItem] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class StayResponse(BaseModel):
    """Structured response for the Stay Agent."""
    model_config = ConfigDict(extra="forbid")
    stay_output: Optional[StayOutput] = None
    response: Optional[str] = None


# Transport Agent
TransportMode = Literal["flight", "train", "bus"]

class TransportOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: TransportMode
    route: str
    provider: Optional[str] = None
    date: Optional[str] = None   # YYYY-MM-DD
    durationMins: Optional[int] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    link: str
    source: Source

class LocalTransfer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    durationMins: Optional[int] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    link: str
    source: Source

class LocalPass(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    duration: str
    price: Optional[float] = None
    currency: Optional[str] = None
    link: str
    source: Source

class TransportOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transportOptions: List[TransportOption] = Field(default_factory=list)
    localTransfers: List[LocalTransfer] = Field(default_factory=list)
    localPasses: List[LocalPass] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class TransportResponse(BaseModel):
    """Structured response for the Transport Agent."""
    model_config = ConfigDict(extra="forbid")
    transport_output: Optional[TransportOutput] = None
    response: Optional[str] = None


# Events Agent
class EventItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    date: str  # YYYY-MM-DD
    area: Optional[str] = None
    link: str
    note: Optional[str] = None
    source: Source

class EventsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: List[EventItem] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class EventsResponse(BaseModel):
    """Structured response for the Events Agent."""
    model_config = ConfigDict(extra="forbid")
    events_output: Optional[EventsOutput] = None
    response: Optional[str] = None


# Dining Agent
class DiningItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    area: Optional[str] = None
    cuisine: Optional[str] = None
    priceRange: Optional[str] = None
    dietaryOptions: List[str] = Field(default_factory=list)
    link: str
    notes: Optional[str] = None
    source: Source


class DiningOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    restaurants: List[DiningItem] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class DiningResponse(BaseModel):
    """Structured response for the Dining Agent."""
    model_config = ConfigDict(extra="forbid")
    dining_output: Optional[DiningOutput] = None
    response: Optional[str] = None


# ======= Phase C - Orchestrator & Workflow Models =======
class Booking(BaseModel):
    """An individual booking within a consultation."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., pattern=r"^book_")
    consultation_id: str = Field(..., pattern=r"^cons_")
    type: str  # e.g., "flight", "hotel", "event", "transport_pass"
    provider_ref: Optional[str] = None
    status: BookingStatus = BookingStatus.PENDING
    details: dict[str, Any] = Field(default_factory=dict)
    can_modify: bool = True
    can_cancel: bool = True
    cancellation_policy: Optional[str] = None
    modification_fee: Optional[float] = None


class DiscoveryResults(BaseModel):
    """Aggregated discovery results from all discovery agents."""
    model_config = ConfigDict(extra="forbid")
    pois: Optional[SearchOutput] = None
    stays: Optional[StayOutput] = None
    transport: Optional[TransportOutput] = None
    events: Optional[EventsOutput] = None
    dining: Optional[DiningOutput] = None


class ItinerarySlot(BaseModel):
    """A single time slot in an itinerary day."""
    model_config = ConfigDict(extra="forbid")
    start_time: str  # HH:MM format
    end_time: str  # HH:MM format
    activity: str
    location: Optional[str] = None
    category: str  # e.g., "poi", "dining", "transport", "event"
    mode: Optional[str] = None  # Required when category == "transport"
    item_ref: Optional[str] = None  # reference to specific item
    estimated_cost: Optional[float] = None
    currency: Optional[str] = None
    notes: Optional[str] = None


class ItineraryDay(BaseModel):
    """A single day in an itinerary."""
    model_config = ConfigDict(extra="forbid")
    date: str  # YYYY-MM-DD format
    slots: List[ItinerarySlot] = Field(default_factory=list)
    day_summary: Optional[str] = None


class Itinerary(BaseModel):
    """Complete day-by-day itinerary."""
    model_config = ConfigDict(extra="forbid")
    days: List[ItineraryDay] = Field(default_factory=list)
    total_estimated_cost: Optional[float] = None
    currency: Optional[str] = None


class Consultation(BaseModel):
    """A travel consultation session."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., pattern=r"^cons_")
    session_id: str
    trip_spec: Optional[TripSpec] = None
    discovery_results: Optional[DiscoveryResults] = None
    itinerary: Optional[Itinerary] = None
    status: ConsultationStatus = ConsultationStatus.DRAFT
    bookings: List[str] = Field(default_factory=list)  # booking IDs
    created_at: datetime
    expires_at: datetime


class WorkflowState(BaseModel):
    """State tracking for orchestrator workflow."""
    model_config = ConfigDict(extra="forbid")
    current_phase: str  # e.g., "clarification", "discovery", "planning", "booking"
    checkpoint: Optional[str] = None  # e.g., "awaiting_tripspec_approval"
    retry_count: int = 0
    failed_agents: List[str] = Field(default_factory=list)
    cached_results: dict[str, Any] = Field(default_factory=dict)


class OrchestratorContext(BaseModel):
    """Context for orchestrator decision-making."""
    model_config = ConfigDict(extra="forbid")
    session_id: str
    consultation_id: Optional[str] = None
    intent: Optional[IntentType] = None
    intent_confidence: float = 0.0
    workflow_state: Optional[WorkflowState] = None
    last_user_message: Optional[str] = None


class HumanApprovalRequest(BaseModel):
    """Request for human approval at checkpoints."""
    model_config = ConfigDict(extra="forbid")
    checkpoint_type: str  # "trip_spec", "itinerary", "booking"
    consultation_id: str
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    available_actions: List[str]  # e.g., ["approve", "modify", "cancel"]


class BudgetCategoryAmount(BaseModel):
    """Budget amount for a single category - replaces dict[str, float] for OpenAI structured output."""
    model_config = ConfigDict(extra="forbid")
    category: str
    amount: float


class BudgetProposal(BaseModel):
    """Budget allocation proposal from budget agent."""
    model_config = ConfigDict(extra="forbid")
    total_budget: float
    currency: str
    allocations: List[BudgetCategoryAmount]  # category -> amount
    rationale: Optional[str] = None


class BudgetTracking(BaseModel):
    """Budget tracking for spending against allocations."""
    model_config = ConfigDict(extra="forbid")
    total_budget: float
    total_spent: float
    currency: str
    by_category: List[BudgetCategoryAmount]  # category -> spent amount
    remaining: float
    over_budget: bool = False
    warnings: List[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    """Result of itinerary validation against TripSpec."""
    model_config = ConfigDict(extra="forbid")
    passed: bool
    issues: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


# Aggregator Agent
class AggregatorResponse(BaseModel):
    """Structured response for the Aggregator Agent."""
    model_config = ConfigDict(extra="forbid")
    aggregated_results: Optional[DiscoveryResults] = None
    response: Optional[str] = None


# Budget Agent
class BudgetCategoryValidation(BaseModel):
    """Validation result for a single budget category."""
    model_config = ConfigDict(extra="forbid")
    category: str  # Added category field for List usage
    allocated: float
    cost: float
    over: bool


class BudgetValidation(BaseModel):
    """Budget validation result."""
    model_config = ConfigDict(extra="forbid")
    valid: bool
    total_budget: float
    total_cost: float
    currency: str
    by_category: List[BudgetCategoryValidation]  # Changed from dict to List
    issues: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class BudgetReallocation(BaseModel):
    """Budget reallocation suggestion."""
    model_config = ConfigDict(extra="forbid")
    original_allocations: List[BudgetCategoryAmount]  # Changed from dict to List
    suggested_allocations: List[BudgetCategoryAmount]  # Changed from dict to List
    currency: str
    suggestions: List[str] = Field(default_factory=list)
    potential_savings: float


class BudgetResponse(BaseModel):
    """Structured response for the Budget Agent."""
    model_config = ConfigDict(extra="forbid")
    mode: Optional[BudgetMode] = None
    proposal: Optional[BudgetProposal] = None
    validation: Optional[BudgetValidation] = None
    tracking: Optional[BudgetTracking] = None
    reallocation: Optional[BudgetReallocation] = None
    response: Optional[str] = None


# Route Agent
class RouteResponse(BaseModel):
    """Structured response for the Route Agent."""
    model_config = ConfigDict(extra="forbid")
    itinerary: Optional[Itinerary] = None
    response: Optional[str] = None


# Validator Agent
class ValidatorResponse(BaseModel):
    """Structured response for the Validator Agent."""
    model_config = ConfigDict(extra="forbid")
    validation_result: Optional[ValidationResult] = None
    response: Optional[str] = None


# Booking Agent
class BookingItemState(BaseModel):
    """State of a booking item (used for previous/updated in modify operations)."""
    model_config = ConfigDict(extra="forbid")
    type: Optional[str] = None
    name: Optional[str] = None
    confirmation_number: Optional[str] = None
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None


class BookingDetails(BaseModel):
    """Details for booking operations (CREATE, MODIFY, CANCEL).

    This is a flat model with all possible fields from all action types.
    Only populate the fields relevant to the action being performed.
    """
    model_config = ConfigDict(extra="forbid")
    # For CREATE action (and general booking info)
    type: Optional[str] = None
    name: Optional[str] = None
    confirmation_number: Optional[str] = None
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    # Additional booking details (commonly used in storage/modifications)
    nights: Optional[int] = None
    valid_from: Optional[str] = None
    date: Optional[str] = None
    new_dates: Optional[List[str]] = None
    # Hotel-specific fields
    room_type: Optional[str] = None
    # Flight-specific fields
    airline: Optional[str] = None
    flight_number: Optional[str] = None
    departure: Optional[str] = None
    arrival: Optional[str] = None
    # For MODIFY action
    previous: Optional[BookingItemState] = None
    updated: Optional[BookingItemState] = None
    modification_fee: Optional[float] = None
    # For CANCEL action
    cancelled: Optional[bool] = None
    refund_initiated: Optional[bool] = None
    refund_amount: Optional[float] = None
    cancellation_fee: Optional[float] = None
    cancellation_reference: Optional[str] = None


class BookingResult(BaseModel):
    """Result of a booking operation."""
    model_config = ConfigDict(extra="forbid")
    success: bool
    booking_id: Optional[str] = Field(default=None, pattern=r"^book_")
    provider_ref: Optional[str] = None
    status: BookingStatus = BookingStatus.PENDING
    error_message: Optional[str] = None
    details: Optional[BookingDetails] = None


class BookingResponse(BaseModel):
    """Structured response for the Booking Agent."""
    model_config = ConfigDict(extra="forbid")
    action: Optional[BookingAction] = None
    result: Optional[BookingResult] = None
    response: Optional[str] = None


# Orchestrator Agent
class OrchestratorAction(str, Enum):
    """Actions the orchestrator can take."""
    CALL_AGENTS = "call_agents"
    REQUEST_APPROVAL = "request_approval"
    UPDATE_STATE = "update_state"
    RESPOND_TO_USER = "respond_to_user"


class OrchestratorKeyValue(BaseModel):
    """Key-value pair for orchestrator output - replaces dict[str, Any] for OpenAI structured output."""
    model_config = ConfigDict(extra="forbid")
    key: str
    value: str  # Values stored as strings; parse JSON if needed


class OrchestratorOutput(BaseModel):
    """Structured output for orchestrator internal operations."""
    model_config = ConfigDict(extra="forbid")
    action: OrchestratorAction
    agents: List[str] = Field(default_factory=list)  # Agent types to call
    message: Optional[str] = None  # Message to send to agents
    checkpoint_type: Optional[str] = None  # For REQUEST_APPROVAL
    summary: Optional[str] = None  # For REQUEST_APPROVAL
    details: List[OrchestratorKeyValue] = Field(default_factory=list)
    available_actions: List[str] = Field(default_factory=list)
    context: List[OrchestratorKeyValue] = Field(default_factory=list)


class OrchestratorResponse(BaseModel):
    """Structured response for the Orchestrator Agent."""
    model_config = ConfigDict(extra="forbid")
    orchestrator_output: Optional[OrchestratorOutput] = None
    response: Optional[str] = None


# Health Check
class HealthStatus(str, Enum):
    """Health status of an agent."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthResponse(BaseModel):
    """Health check response for all agents."""
    model_config = ConfigDict(extra="forbid")
    status: HealthStatus = HealthStatus.HEALTHY
    agent_name: str
    version: str


# Three-Tier Routing
class RoutingResult(BaseModel):
    """Result of routing classification for three-tier orchestrator routing."""
    model_config = ConfigDict(extra="forbid")
    decision: RoutingDecision
    confidence: float = Field(..., ge=0.0, le=1.0)
    intent: Optional[IntentType] = None
    target_agent: Optional[str] = None  # For AGENT routing
    target_tool: Optional[str] = None  # For TOOL routing
    clarification_prompt: Optional[str] = None  # For CLARIFY routing


# ======= Cross-Platform Weather Schemas (Interoperability) =======
# Used by Foundry workflows and Copilot Studio Weather agent
# See interoperability/copilot_studio/agents/weather/README.md for schema details

class WeatherRequest(BaseModel):
    """Request schema for weather data from Copilot Studio Weather agent.

    Used in cross-platform calls between Foundry workflows and CS Weather agent.
    """
    model_config = ConfigDict(extra="forbid")
    location: str = Field(..., description="Location for weather forecast (e.g., 'Paris, France')")
    start_date: str = Field(..., description="Start date in YYYY-MM-DD format")
    end_date: str = Field(..., description="End date in YYYY-MM-DD format")


class ClimateSummary(BaseModel):
    """Climate summary based on historical weather patterns.

    Used instead of daily forecasts since trip planning typically involves
    dates months in advance where real forecasts aren't available.
    """
    model_config = ConfigDict(extra="forbid")
    average_high_temp_c: float = Field(..., description="Average high temperature in Celsius")
    average_low_temp_c: float = Field(..., description="Average low temperature in Celsius")
    average_precipitation_chance: int = Field(..., ge=0, le=100, description="Typical precipitation probability 0-100%")
    typical_conditions: str = Field(..., description="Description of typical weather conditions (e.g., 'Mostly sunny with occasional afternoon clouds')")


class WeatherResponse(BaseModel):
    """Response schema for weather data from Copilot Studio Weather agent.

    Returns climate summaries based on historical patterns rather than
    daily forecasts, since trip planning involves dates months in advance.
    """
    model_config = ConfigDict(extra="forbid")
    location: str = Field(..., description="Location for which climate data was retrieved")
    start_date: str = Field(..., description="Start date in YYYY-MM-DD format")
    end_date: str = Field(..., description="End date in YYYY-MM-DD format")
    climate_summary: ClimateSummary = Field(..., description="Climate summary based on historical patterns")
    summary: str = Field(..., description="Brief 1-2 sentence overall climate outlook for the trip")


# ======= Cross-Platform Approval Schemas (Interoperability) =======
# Used by Pro Code Orchestrator and Copilot Studio Approval agent
# See docs/interoperability-design.md

class ApprovalDecisionType(str, Enum):
    """Decision type from the Approval Agent.

    The Approval Agent in Copilot Studio emits one of these decision values
    via the 'approval_decision' event.
    """
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFY = "modify"
    PENDING = "pending"  # Fallback state for timeout/error scenarios


class ApprovalRequest(BaseModel):
    """Request schema for sending an itinerary to Copilot Studio Approval agent.

    Used by the Approval Proxy (Foundry hosted agent) to send draft itinerary
    for human approval via the M365 Agents SDK.
    """
    model_config = ConfigDict(extra="forbid")
    itinerary: Itinerary = Field(..., description="Draft itinerary requiring approval")
    request_id: str = Field(..., description="Unique identifier for this approval request")
    timeout_seconds: Optional[int] = Field(
        default=300,
        description="Max wait time for human response (default: 5 minutes)"
    )


class ApprovalDecision(BaseModel):
    """Response schema for approval decisions from Copilot Studio Approval agent.

    Emitted via the 'approval_decision' event from CS Approval agent.
    """
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(..., description="Request ID matching the original ApprovalRequest")
    decision: ApprovalDecisionType = Field(..., description="The approval decision")
    feedback: Optional[str] = Field(
        default=None,
        description="Optional human feedback or modification instructions"
    )
    timestamp: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp of the decision"
    )
