"""
DiscoveryHandler: Phase 2 handler for discovery and planning.

Per design doc Three-Phase Workflow and Long-Running Operations sections:
- Orchestrates parallel calls to discovery agents (POI, Stay, Transport, Events, Dining)
- Creates and manages discovery jobs via DiscoveryJobStore
- Aggregates results from discovery agents
- Runs planning pipeline (Aggregator -> Budget -> Route -> Validator)
- Sets checkpoint="itinerary_approval" when itinerary draft is ready

Per ORCH-088:
- Discovery completion triggers planning pipeline execution
- ItineraryDraft is stored in WorkflowState and DiscoveryJob
- WorkflowState transitions to DISCOVERY_PLANNING with checkpoint itinerary_approval
- Returns itinerary preview when results are ready

Actions handled:
- APPROVE_ITINERARY: Transition to Booking phase
- REQUEST_MODIFICATION: Re-run specific agents or handle change requests
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from src.orchestrator.discovery.job_runner import spawn_discovery_job
from src.orchestrator.discovery.parallel_executor import (
    AGENT_TIMEOUTS,
    DEFAULT_AGENT_TIMEOUT,
    DISCOVERY_AGENTS,
)
from src.orchestrator.handlers.clarification import HandlerResult, PhaseHandler
from src.orchestrator.models.booking import Booking, BookingStatus, CancellationPolicy
from src.orchestrator.models.itinerary import Itinerary, ItineraryDraft
from src.orchestrator.models.responses import ToolResponse, UIAction, UIDirective
from src.orchestrator.models.workflow_state import Phase, WorkflowState
from src.orchestrator.state_gating import Action, WorkflowEvent
from src.orchestrator.storage import WorkflowStateData
from src.orchestrator.storage.booking_store import BookingStoreProtocol, InMemoryBookingStore
from src.orchestrator.storage.consultation_summaries import (
    ConsultationSummary,
    ConsultationSummaryStoreProtocol,
    InMemoryConsultationSummaryStore,
)
from src.orchestrator.storage.discovery_jobs import (
    AgentProgress,
    DiscoveryJob,
    DiscoveryJobStoreProtocol,
    InMemoryDiscoveryJobStore,
    JobStatus,
)
from src.orchestrator.storage.itinerary_store import (
    InMemoryItineraryStore,
    ItineraryStoreProtocol,
)
from src.orchestrator.utils import generate_booking_id, generate_itinerary_id, generate_job_id

if TYPE_CHECKING:
    from src.shared.a2a.client_wrapper import A2AClientWrapper
    from src.shared.a2a.registry import AgentRegistry
    from src.shared.storage.protocols import WorkflowStoreProtocol

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# Discovery Result Types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class AgentDiscoveryResult:
    """Result from a single discovery agent."""

    agent: str
    status: str  # "success", "error", "timeout"
    data: dict[str, Any] | None = None
    message: str | None = None
    retry_possible: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "agent": self.agent,
            "status": self.status,
            "data": self.data,
            "message": self.message,
            "retry_possible": self.retry_possible,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentDiscoveryResult":
        """Create from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        elif timestamp is None:
            timestamp = datetime.now(timezone.utc)

        return cls(
            agent=data.get("agent", ""),
            status=data.get("status", "error"),
            data=data.get("data"),
            message=data.get("message"),
            retry_possible=data.get("retry_possible", False),
            timestamp=timestamp,
        )


@dataclass
class DiscoveryResults:
    """Aggregated results from all discovery agents."""

    transport: AgentDiscoveryResult | None = None
    stay: AgentDiscoveryResult | None = None
    poi: AgentDiscoveryResult | None = None
    events: AgentDiscoveryResult | None = None
    dining: AgentDiscoveryResult | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        result: dict[str, Any] = {}
        for agent in DISCOVERY_AGENTS:
            agent_result = getattr(self, agent, None)
            if agent_result:
                result[agent] = agent_result.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DiscoveryResults":
        """Create from dictionary."""
        results = cls()
        for agent in DISCOVERY_AGENTS:
            agent_data = data.get(agent)
            if agent_data:
                setattr(results, agent, AgentDiscoveryResult.from_dict(agent_data))
        return results

    def get_successful_count(self) -> int:
        """Count successful agent results."""
        return sum(
            1 for agent in DISCOVERY_AGENTS
            if getattr(self, agent, None) and getattr(self, agent).status == "success"
        )

    def get_failed_agents(self) -> list[str]:
        """Get list of agents that failed or timed out."""
        failed = []
        for agent in DISCOVERY_AGENTS:
            result = getattr(self, agent, None)
            if result and result.status in ("error", "timeout"):
                failed.append(agent)
        return failed

    def has_partial_success(self) -> bool:
        """Check if some (but not all) agents succeeded."""
        successful = self.get_successful_count()
        return 0 < successful < len(DISCOVERY_AGENTS)

# ═══════════════════════════════════════════════════════════════════════════════
# Discovery Handler
# ═══════════════════════════════════════════════════════════════════════════════


class DiscoveryHandler(PhaseHandler):
    """
    Handles Phase 2: Discovery & Planning.

    Covers both DISCOVERY_IN_PROGRESS and DISCOVERY_PLANNING phases.

    Per design doc Three-Phase Workflow section:
    - Starts discovery jobs for parallel agent execution
    - Tracks progress via DiscoveryJobStore
    - Aggregates results and runs planning pipeline
    - Sets checkpoint="itinerary_approval" for user approval
    - Transitions to BOOKING on approval
    """

    def __init__(
        self,
        state: WorkflowState,
        state_data: WorkflowStateData,
        a2a_client: "A2AClientWrapper | None" = None,
        agent_registry: "AgentRegistry | None" = None,
        discovery_job_store: DiscoveryJobStoreProtocol | None = None,
        workflow_store: "WorkflowStoreProtocol | None" = None,
        itinerary_store: ItineraryStoreProtocol | None = None,
        booking_store: BookingStoreProtocol | None = None,
        consultation_summary_store: ConsultationSummaryStoreProtocol | None = None,
    ):
        """
        Initialize the discovery handler.

        Args:
            state: Domain model for validation and business logic
            state_data: Storage model for persistence
            a2a_client: A2A client for agent communication (optional for testing)
            agent_registry: Agent registry for URL lookup (optional for testing)
            discovery_job_store: Store for discovery job persistence (optional)
            workflow_store: Store for workflow state (optional for background discovery)
            itinerary_store: Store for itinerary persistence (optional for testing)
            booking_store: Store for booking persistence (optional for testing)
            consultation_summary_store: Store for consultation summary persistence (optional)
        """
        super().__init__(state, state_data)
        self._a2a_client = a2a_client
        self._agent_registry = agent_registry
        self._discovery_job_store = discovery_job_store or InMemoryDiscoveryJobStore()
        self._workflow_store = workflow_store
        self._itinerary_store = itinerary_store or InMemoryItineraryStore()
        self._booking_store = booking_store or InMemoryBookingStore()
        self._consultation_summary_store = (
            consultation_summary_store or InMemoryConsultationSummaryStore()
        )

    async def execute(
        self,
        action: Action,
        message: str,
        event: WorkflowEvent | None = None,
    ) -> HandlerResult:
        """
        Execute the action for discovery/planning phase.

        Per design doc, valid actions in DISCOVERY phases:
        - APPROVE_ITINERARY: Transition to booking
        - REQUEST_MODIFICATION: Handle modification request
        """
        match action:
            case Action.APPROVE_ITINERARY:
                return await self._approve_itinerary()

            case Action.REQUEST_MODIFICATION:
                return await self._handle_modification(message, event)

            case _:
                # For other actions in discovery phase, provide status
                logger.warning(
                    "Action %s received in DISCOVERY phase, returning status",
                    action.value,
                )
                return await self._get_discovery_status()

    async def _run_discovery_agents_parallel(
        self,
        job: DiscoveryJob,
        trip_spec: dict[str, Any] | None,
    ) -> DiscoveryResults:
        """
        Run discovery agents in parallel using the shared executor.

        This is a legacy helper used by unit tests and recovery flows.
        """
        from src.orchestrator.discovery.job_runner import (
            build_discovery_request,
            build_executor_trip_spec,
        )
        from src.orchestrator.discovery.parallel_executor import (
            execute_parallel_discovery,
        )

        trip_spec_dict: dict[str, Any]
        if trip_spec is None:
            trip_spec_dict = {}
        elif isinstance(trip_spec, dict):
            trip_spec_dict = trip_spec
        elif hasattr(trip_spec, "to_dict"):
            trip_spec_dict = trip_spec.to_dict()
        else:
            trip_spec_dict = {}

        executor_trip_spec = build_executor_trip_spec(trip_spec_dict)
        results = await execute_parallel_discovery(
            executor_trip_spec,
            a2a_client=self._a2a_client,
            agent_registry=self._agent_registry,
            request_builder=build_discovery_request,
        )

        discovery_results = DiscoveryResults.from_dict(results.to_dict())
        job.discovery_results = discovery_results.to_dict()

        progress: dict[str, AgentProgress] = {}
        for agent in DISCOVERY_AGENTS:
            agent_result = getattr(discovery_results, agent, None)
            if agent_result is None:
                continue
            status_map = {
                "success": "completed",
                "error": "failed",
                "timeout": "timeout",
            }
            progress[agent] = AgentProgress(
                agent=agent,
                status=status_map.get(agent_result.status, "failed"),
                completed_at=agent_result.timestamp,
                message=agent_result.message,
            )

        job.agent_progress = progress

        failed_count = len(discovery_results.get_failed_agents())
        if failed_count == 0:
            job.status = JobStatus.COMPLETED
        elif failed_count == len(DISCOVERY_AGENTS):
            job.status = JobStatus.FAILED
        else:
            job.status = JobStatus.PARTIAL

        job.completed_at = datetime.now(timezone.utc)
        await self._discovery_job_store.save_job(job)

        return discovery_results

    async def finalize_discovery_with_planning(
        self,
        job: DiscoveryJob,
        workflow_store: "WorkflowStoreProtocol",
    ) -> HandlerResult:
        """
        Finalize a completed discovery job by running planning and syncing to state.

        Per ORCH-088:
        1. Runs the planning pipeline (Aggregator → Budget → Route → Validator)
        2. Stores ItineraryDraft on DiscoveryJob and WorkflowState
        3. Updates WorkflowState phase/checkpoint to DISCOVERY_PLANNING + itinerary_approval
        4. Returns itinerary preview for user approval

        This method should be called when discovery agents complete.

        Args:
            job: The completed discovery job
            workflow_store: Store for loading/saving workflow state

        Returns:
            HandlerResult with itinerary preview or error
        """
        from src.orchestrator.discovery.state_sync import finalize_job_with_planning

        # Run planning and sync to state
        sync_result = await finalize_job_with_planning(
            job=job,
            workflow_store=workflow_store,
            job_store=self._discovery_job_store,
            session_id=self.state.session_id,
            a2a_client=self._a2a_client,
            agent_registry=self._agent_registry,
        )

        if not sync_result.success:
            return HandlerResult(
                response=ToolResponse(
                    success=False,
                    message=f"Failed to finalize discovery: {sync_result.reason}",
                    data={"error": sync_result.reason},
                ),
                state_data=self.state_data,
            )

        # Update local state from synced state
        if sync_result.state:
            self.state.phase = sync_result.state.phase
            self.state.checkpoint = sync_result.state.checkpoint
            self.state.current_step = sync_result.state.current_step
            self.state.discovery_results = sync_result.state.discovery_results
            self.state.itinerary_draft = sync_result.state.itinerary_draft
            self.state.current_job_id = sync_result.state.current_job_id
            self.state.last_synced_job_id = sync_result.state.last_synced_job_id
            self._sync_state_to_data()

        # Return itinerary preview
        return await self._return_itinerary_preview(job)

    async def _call_discovery_agent(
        self,
        agent: str,
        trip_spec: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Call a single discovery agent via A2A.

        Args:
            agent: Agent name (transport, stay, poi, events, dining)
            trip_spec: Trip specification for the discovery request

        Returns:
            Agent response data
        """
        if self._a2a_client is None or self._agent_registry is None:
            # Stub response for testing without real agents
            return self._create_stub_discovery_result(agent, trip_spec)

        try:
            agent_config = self._agent_registry.get(agent)
            if agent_config is None:
                raise ValueError(f"Agent '{agent}' not found in registry")

            # Format discovery request
            request_message = self._format_discovery_request(agent, trip_spec)

            # Call agent
            response = await self._a2a_client.send_message(
                agent_url=agent_config.url,
                message=request_message,
            )

            return {
                "text": response.text,
                "data": response.data,
            }

        except Exception as e:
            logger.error(f"Error calling discovery agent {agent}: {e}")
            raise

    def _format_discovery_request(
        self,
        agent: str,
        trip_spec: dict[str, Any],
    ) -> str:
        """Format a discovery request for a specific agent."""
        destination = trip_spec.get("destination", "unknown")
        start_date = trip_spec.get("start_date", "")
        end_date = trip_spec.get("end_date", "")
        travelers = trip_spec.get("num_travelers", 1)

        # Agent-specific prompts
        prompts = {
            "transport": f"Find flight options to {destination} from {start_date} to {end_date} for {travelers} travelers.",
            "stay": f"Find hotel options in {destination} from {start_date} to {end_date} for {travelers} guests.",
            "poi": f"Find top attractions and points of interest in {destination}.",
            "events": f"Find events happening in {destination} between {start_date} and {end_date}.",
            "dining": f"Find restaurant recommendations in {destination}.",
        }

        return prompts.get(agent, f"Search for {agent} options in {destination}.")

    def _create_stub_discovery_result(
        self,
        agent: str,
        trip_spec: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a stub discovery result for testing."""
        destination = trip_spec.get("destination", "destination")

        stub_results = {
            "transport": {
                "options": [
                    {"type": "flight", "airline": "Sample Airlines", "price": 450},
                ],
                "message": f"Found 3 flight options to {destination}",
            },
            "stay": {
                "options": [
                    {"type": "hotel", "name": "Sample Hotel", "price_per_night": 150},
                ],
                "message": f"Found 5 hotel options in {destination}",
            },
            "poi": {
                "options": [
                    {"name": "Main Attraction", "rating": 4.5},
                ],
                "message": f"Found 10 attractions in {destination}",
            },
            "events": {
                "options": [
                    {"name": "Local Event", "date": "2024-03-15"},
                ],
                "message": f"Found 2 events in {destination}",
            },
            "dining": {
                "options": [
                    {"name": "Popular Restaurant", "cuisine": "Local", "rating": 4.2},
                ],
                "message": f"Found 8 restaurants in {destination}",
            },
        }

        return stub_results.get(agent, {"options": [], "message": "No results found"})

    async def _get_discovery_status(self) -> HandlerResult:
        """
        Get the current discovery job status.

        Returns current progress and any available results.
        Per ORCH-088: Returns itinerary preview when results are ready.
        """
        job_id = getattr(self.state, 'current_job_id', None)

        # Check if we're in DISCOVERY_PLANNING with itinerary draft ready
        if self.state.phase == Phase.DISCOVERY_PLANNING and self.state.itinerary_draft:
            return await self._return_itinerary_preview()

        if not job_id:
            # No active job and no itinerary draft - check state
            if self.state.discovery_results:
                return HandlerResult(
                    response=ToolResponse(
                        success=True,
                        message="Discovery results are ready.",
                        data={
                            "phase": self.state.phase.value,
                            "discovery_results": self.state.discovery_results,
                        },
                    ),
                    state_data=self.state_data,
                )
            return HandlerResult(
                response=ToolResponse(
                    success=True,
                    message="No discovery job is currently running.",
                    data={"phase": self.state.phase.value},
                ),
                state_data=self.state_data,
            )

        # Get job from store
        job = await self._discovery_job_store.get_job(
            job_id,
            self.state.consultation_id or "",
        )

        if not job:
            return HandlerResult(
                response=ToolResponse(
                    success=True,
                    message="Discovery job not found. It may have expired.",
                    data={"job_id": job_id, "status": "not_found"},
                ),
                state_data=self.state_data,
            )

        # Build progress summary
        progress_summary = {}
        for agent, progress in job.agent_progress.items():
            progress_summary[agent] = {
                "status": progress.status,
                "message": progress.message,
            }

        # If job is completed and has itinerary draft, return preview
        if job.is_terminal() and job.itinerary_draft:
            return await self._return_itinerary_preview(job)

        return HandlerResult(
            response=ToolResponse(
                success=True,
                message=f"Discovery job is {job.status.value}.",
                data={
                    "job_id": job_id,
                    "status": job.status.value,
                    "pipeline_stage": job.pipeline_stage,
                    "agent_progress": progress_summary,
                },
            ),
            state_data=self.state_data,
        )

    async def _return_itinerary_preview(
        self,
        job: DiscoveryJob | None = None,
    ) -> HandlerResult:
        """
        Return itinerary preview when discovery + planning is complete.

        Per ORCH-088:
        - Returns itinerary draft for user approval
        - Includes approve/modify actions
        - Sets checkpoint="itinerary_approval" if not already set
        """
        itinerary_draft = job.itinerary_draft if job else self.state.itinerary_draft

        if not itinerary_draft:
            return HandlerResult(
                response=ToolResponse(
                    success=True,
                    message="Itinerary is being prepared...",
                    data={"phase": self.state.phase.value},
                ),
                state_data=self.state_data,
            )

        # Format itinerary preview message
        destination = itinerary_draft.get("destination", "your destination")
        num_days = len(itinerary_draft.get("days", []))
        total_cost = itinerary_draft.get("total_estimated_cost", 0)
        currency = itinerary_draft.get("currency", "USD")

        preview_message = (
            f"I've created a {num_days}-day itinerary for {destination}. "
            f"Estimated total cost: {total_cost:,.0f} {currency}. "
            f"Would you like to approve this plan or make any changes?"
        )

        # Get validation info if available
        validation = itinerary_draft.get("validation", {})
        gaps = itinerary_draft.get("gaps", [])

        # Build response data
        response_data = {
            "itinerary_draft": itinerary_draft,
            "phase": self.state.phase.value,
            "checkpoint": self.state.checkpoint,
        }
        if validation:
            response_data["validation"] = validation
        if gaps:
            response_data["gaps"] = gaps

        return HandlerResult(
            response=ToolResponse(
                success=True,
                message=preview_message,
                data=response_data,
                ui=UIDirective(
                    actions=[
                        UIAction(
                            label="Approve Itinerary",
                            event={"type": "approve_checkpoint", "checkpoint_id": "itinerary_approval"},
                        ),
                        UIAction(
                            label="Request Changes",
                            event={"type": "request_change", "checkpoint_id": "itinerary_approval"},
                        ),
                    ],
                    text_input=True,
                ),
            ),
            state_data=self.state_data,
        )

    async def _approve_itinerary(self) -> HandlerResult:
        """
        User approved itinerary - transition to Booking phase.

        Per design doc and ORCH-102:
        - Convert ItineraryDraft to Itinerary with generated itinerary_id
        - Create Booking records for each bookable item with booking_ids
        - Persist Itinerary and Booking records to their stores
        - Update WorkflowState with itinerary_id and clear itinerary_draft
        - Transition to BOOKING phase and clear checkpoint
        - Upsert ConsultationSummary with itinerary_ids, booking_ids, status
        """
        # Get itinerary draft from state
        draft_data = self.state.itinerary_draft
        if not draft_data:
            return HandlerResult(
                response=ToolResponse(
                    success=False,
                    message="No itinerary draft available to approve.",
                    data={"error": "missing_itinerary_draft"},
                ),
                state_data=self.state_data,
            )

        # Generate IDs
        itinerary_id = generate_itinerary_id()

        # Parse itinerary draft
        itinerary_draft = ItineraryDraft.from_dict(draft_data)

        # Extract bookable items and create Booking records
        bookings: list[Booking] = []
        booking_ids: list[str] = []

        # Get trip end date for TTL calculation
        trip_end_date = itinerary_draft.trip_summary.end_date

        def _normalize_accommodation_field(value: str | None) -> str:
            if not isinstance(value, str):
                return ""
            return value.strip().lower()

        def _accommodation_key(accommodation: Any) -> tuple[str, str, str]:
            return (
                _normalize_accommodation_field(getattr(accommodation, "name", None)),
                _normalize_accommodation_field(getattr(accommodation, "location", None)),
                _normalize_accommodation_field(getattr(accommodation, "room_type", None)),
            )

        current_stay: dict[str, Any] | None = None

        def _flush_current_stay() -> None:
            nonlocal current_stay
            if not current_stay:
                return

            accommodation = current_stay["accommodation"]
            booking_id = generate_booking_id()
            booking_ids.append(booking_id)
            booking = Booking.create_unbooked(
                booking_id=booking_id,
                itinerary_id=itinerary_id,
                item_type="hotel",
                details={
                    "name": accommodation.name,
                    "location": accommodation.location,
                    "room_type": accommodation.room_type,
                    "check_in": current_stay.get("check_in"),
                    "check_out": current_stay.get("check_out"),
                    "nights": current_stay.get("nights", 1),
                },
                price=current_stay.get("total_cost", 0.0),
                cancellation_policy=CancellationPolicy(is_cancellable=True),
            )
            bookings.append(booking)
            current_stay = None

        # Create bookings from itinerary days
        for day in itinerary_draft.days:
            # Transport bookings (flights, trains, etc.)
            for transport in day.transport:
                mode = transport.mode.lower()
                if mode in ("flight", "train", "bus", "ferry"):
                    booking_id = generate_booking_id()
                    booking_ids.append(booking_id)
                    booking = Booking.create_unbooked(
                        booking_id=booking_id,
                        itinerary_id=itinerary_id,
                        item_type="flight" if mode == "flight" else "transport",
                        details={
                            "mode": transport.mode,
                            "from": transport.from_location,
                            "to": transport.to_location,
                            "carrier": transport.carrier,
                            "departure": transport.departure_time,
                            "arrival": transport.arrival_time,
                        },
                        price=transport.estimated_cost,
                        cancellation_policy=CancellationPolicy(is_cancellable=True),
                    )
                    bookings.append(booking)

            # Accommodation bookings (hotels) - dedupe consecutive nights
            if day.accommodation:
                accommodation = day.accommodation
                accommodation_key = _accommodation_key(accommodation)
                day_number = int(getattr(day, "day_number", 0))

                if (
                    current_stay
                    and accommodation_key == current_stay["key"]
                    and day_number == current_stay.get("last_day_number", day_number - 1) + 1
                ):
                    current_stay["last_day_number"] = day_number
                    current_stay["nights"] = current_stay.get("nights", 1) + 1
                    current_stay["total_cost"] = current_stay.get("total_cost", 0.0) + float(
                        accommodation.estimated_cost
                    )
                    if accommodation.check_out:
                        current_stay["check_out"] = accommodation.check_out
                else:
                    _flush_current_stay()
                    current_stay = {
                        "key": accommodation_key,
                        "accommodation": accommodation,
                        "check_in": accommodation.check_in,
                        "check_out": accommodation.check_out,
                        "total_cost": float(accommodation.estimated_cost),
                        "nights": 1,
                        "last_day_number": day_number,
                    }
            else:
                _flush_current_stay()

            # Activity bookings (attractions, tours, etc.)
            for activity in day.activities:
                if activity.booking_required:
                    booking_id = generate_booking_id()
                    booking_ids.append(booking_id)
                    booking = Booking.create_unbooked(
                        booking_id=booking_id,
                        itinerary_id=itinerary_id,
                        item_type="activity",
                        details={
                            "name": activity.name,
                            "location": activity.location,
                            "description": activity.description,
                            "start_time": activity.start_time,
                            "end_time": activity.end_time,
                        },
                        price=activity.estimated_cost,
                        cancellation_policy=CancellationPolicy(is_cancellable=True),
                    )
                    bookings.append(booking)

        _flush_current_stay()

        # Convert draft to approved Itinerary
        itinerary = itinerary_draft.to_itinerary(
            itinerary_id=itinerary_id,
            booking_ids=booking_ids,
        )

        # Persist Itinerary to store
        await self._itinerary_store.save_itinerary(itinerary)

        # Persist all Booking records to store
        for booking in bookings:
            await self._booking_store.save_booking(booking, trip_end_date=trip_end_date)

        # Update state
        self.state.phase = Phase.BOOKING
        self.state.checkpoint = None
        self.state.current_step = "booking"
        self.state.itinerary_id = itinerary_id
        self.state.current_job_id = None  # Clear job reference
        self.state.itinerary_draft = None  # Clear draft after approval

        # Sync to state_data
        self._sync_state_to_data()

        # Upsert ConsultationSummary
        await self._update_consultation_summary(
            itinerary=itinerary,
            booking_ids=booking_ids,
        )

        # Build booking items summary for response
        booking_items = [
            {
                "booking_id": b.booking_id,
                "type": b.item_type,
                "status": b.status.value,
                "price": b.price,
                "details": b.details,
            }
            for b in bookings
        ]

        return HandlerResult(
            response=ToolResponse(
                success=True,
                message=f"Great! Your itinerary ({itinerary_id}) is approved. You can now book each item.",
                data={
                    "itinerary_id": itinerary_id,
                    "phase": "booking",
                    "booking_items": booking_items,
                    "total_bookings": len(bookings),
                },
                ui=UIDirective(
                    actions=[
                        UIAction(
                            label="View All Bookings",
                            event={"type": "view_booking_options"},
                        ),
                    ],
                    text_input=True,
                ),
            ),
            state_data=self.state_data,
        )

    async def _update_consultation_summary(
        self,
        itinerary: Itinerary,
        booking_ids: list[str],
    ) -> None:
        """
        Update ConsultationSummary with itinerary and booking information.

        Per ORCH-102:
        - Creates or updates ConsultationSummary
        - Sets itinerary_ids, booking_ids, trip_spec_summary
        - Sets status="itinerary_approved"
        - Uses dynamic TTL based on trip_end_date
        """
        consultation_id = self.state.consultation_id or ""

        # Try to get existing summary
        existing_summary = await self._consultation_summary_store.get_summary(
            consultation_id
        )

        # Build trip_spec_summary from itinerary
        trip_spec_summary = {
            "destination": itinerary.trip_summary.destination,
            "start_date": itinerary.trip_summary.start_date.isoformat(),
            "end_date": itinerary.trip_summary.end_date.isoformat(),
            "travelers": itinerary.trip_summary.travelers,
            "trip_type": itinerary.trip_summary.trip_type,
        }

        if existing_summary:
            # Update existing summary
            existing_summary.itinerary_ids.append(itinerary.itinerary_id)
            existing_summary.booking_ids.extend(booking_ids)
            existing_summary.trip_spec_summary = trip_spec_summary
            existing_summary.status = "itinerary_approved"
            existing_summary.trip_end_date = itinerary.trip_summary.end_date
            await self._consultation_summary_store.save_summary(existing_summary)
        else:
            # Create new summary
            summary = ConsultationSummary(
                consultation_id=consultation_id,
                session_id=self.state.session_id,
                trip_spec_summary=trip_spec_summary,
                itinerary_ids=[itinerary.itinerary_id],
                booking_ids=booking_ids,
                status="itinerary_approved",
                trip_end_date=itinerary.trip_summary.end_date,
            )
            await self._consultation_summary_store.save_summary(summary)

    async def _handle_modification(
        self,
        message: str,
        event: WorkflowEvent | None,
    ) -> HandlerResult:
        """
        Handle modification request during discovery/planning.

        Per design doc and ORCH-093:
        - For retry_discovery event: Reset all discovery state and restart from scratch
        - For retry_agent/skip_agent events, handle specific agent
        - For change_request, analyze and decide which agents to re-run
        - Re-run affected agents + downstream pipeline
        - Trigger planning pipeline when all agents reach terminal status
        """
        # Handle retry_discovery event - full restart from scratch
        if event and event.type == "retry_discovery":
            return await self._retry_discovery()

        # Handle retry_agent/skip_agent events
        # Per ORCH-093: event.agent is REQUIRED for these events
        if event and event.type in ("retry_agent", "skip_agent"):
            if not event.agent_id:
                return HandlerResult(
                    response=ToolResponse(
                        success=False,
                        message=f"Event '{event.type}' requires event.agent to specify which discovery agent to target.",
                        data={"error": "missing_agent", "event_type": event.type},
                    ),
                    state_data=self.state_data,
                )
            if event.type == "retry_agent":
                return await self._retry_agent(event.agent_id)
            else:  # skip_agent
                return await self._skip_agent(event.agent_id)

        # For general modification, clear checkpoint and handle request
        if self.state.checkpoint == "itinerary_approval":
            self.state.checkpoint = None
            self._sync_state_to_data()

        # Analyze modification and determine which agents to re-run
        # For now, return acknowledgment
        return HandlerResult(
            response=ToolResponse(
                success=True,
                message="I'll update your trip plan. Let me re-check the options based on your changes...",
                data={
                    "modification_requested": True,
                    "original_message": message,
                },
            ),
            state_data=self.state_data,
        )

    async def _retry_discovery(self) -> HandlerResult:
        """
        Restart discovery from scratch - re-run all discovery agents.

        Per ORCH-104 and design doc Modification Handling section:
        1. Cancel any in-flight discovery job (best-effort)
        2. Reset discovery_results, discovery_requests, itinerary_draft, last_synced_job_id
        3. Create fresh discovery job for all agents
        4. Update current_job_id and set phase=DISCOVERY_IN_PROGRESS with checkpoint=None
        5. Return ToolResponse with new job_id and stream_url
        """
        # 1. Cancel any existing in-flight job (best-effort)
        existing_job_id = getattr(self.state, 'current_job_id', None)
        if existing_job_id:
            try:
                existing_job = await self._discovery_job_store.get_job(
                    existing_job_id,
                    self.state.consultation_id or "",
                )
                if existing_job and not existing_job.is_terminal():
                    # Mark as cancelled
                    existing_job.status = JobStatus.CANCELLED
                    existing_job.completed_at = datetime.now(timezone.utc)
                    await self._discovery_job_store.save_job(existing_job)
                    logger.info(
                        "Cancelled in-flight discovery job %s for retry_discovery",
                        existing_job_id,
                    )
            except Exception as e:
                # Best-effort - log but continue
                logger.warning(
                    "Failed to cancel existing job %s: %s",
                    existing_job_id,
                    e,
                )

        # 2. Reset discovery state
        # Note: discovery_results and discovery_requests may be stored on state or state_data
        if hasattr(self.state, 'discovery_results'):
            self.state.discovery_results = None
        if hasattr(self.state, 'discovery_requests'):
            self.state.discovery_requests = None
        if hasattr(self.state, 'itinerary_draft'):
            self.state.itinerary_draft = None
        if hasattr(self.state, 'last_synced_job_id'):
            self.state.last_synced_job_id = None

        # 3. Create fresh discovery job
        job_id = generate_job_id()
        job = DiscoveryJob(
            job_id=job_id,
            consultation_id=self.state.consultation_id or "",
            workflow_version=self.state.workflow_version,
            status=JobStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            agent_progress={
                agent: AgentProgress(agent=agent, status="pending")
                for agent in DISCOVERY_AGENTS
            },
            pipeline_stage="discovery",
        )

        # Save job to store
        await self._discovery_job_store.save_job(job)

        # 4. Update state with job reference and phase
        self.state.current_job_id = job_id
        self.state.phase = Phase.DISCOVERY_IN_PROGRESS
        self.state.checkpoint = None  # Clear checkpoint
        self.state.current_step = "running"

        # Sync to state_data
        self._sync_state_to_data()

        if self._workflow_store is not None:
            spawn_discovery_job(
                job=job,
                trip_spec=self.state.trip_spec,
                session_id=self.state.session_id,
                discovery_job_store=self._discovery_job_store,
                workflow_store=self._workflow_store,
                a2a_client=self._a2a_client,
                agent_registry=self._agent_registry,
            )
        else:
            logger.warning(
                "Discovery job %s created without workflow_store; skipping background run",
                job_id,
            )

        logger.info(
            "Started fresh discovery job %s (retry_discovery) for session %s",
            job_id,
            self.state.session_id,
        )

        # 5. Return response with job_id and stream_url
        return HandlerResult(
            response=ToolResponse(
                success=True,
                message="Restarting discovery from scratch. Let me search for new options...",
                data={
                    "job_id": job_id,
                    "stream_url": f"/sessions/{self.state.session_id}/discovery/stream",
                    "phase": "discovery_in_progress",
                    "action": "retry_discovery",
                    "cancelled_job_id": existing_job_id,
                },
                ui=UIDirective(
                    actions=[
                        UIAction(
                            label="View Progress",
                            event={"type": "status"},
                        ),
                    ],
                    text_input=False,
                ),
            ),
            state_data=self.state_data,
        )

    async def _retry_agent(self, agent_id: str) -> HandlerResult:
        """
        Retry a failed/timed-out discovery agent.

        Per ORCH-093 and design doc Pipeline Execution with Gap Awareness:
        1. Validate agent_id is a known discovery agent
        2. Load current discovery job
        3. Reset agent progress to "pending" and clear previous results
        4. Re-run the single agent
        5. Update job with new results
        6. When all agents have terminal status, trigger planning pipeline
        7. Return itinerary preview when planning completes

        Args:
            agent_id: The agent to retry (transport, stay, poi, events, dining)

        Returns:
            HandlerResult with retry status or itinerary preview
        """
        if agent_id not in DISCOVERY_AGENTS:
            return HandlerResult(
                response=ToolResponse(
                    success=False,
                    message=f"Unknown agent: {agent_id}. Valid agents: {', '.join(DISCOVERY_AGENTS)}",
                    data={"error": "invalid_agent", "valid_agents": list(DISCOVERY_AGENTS)},
                ),
                state_data=self.state_data,
            )

        # Get current job
        job_id = getattr(self.state, 'current_job_id', None)
        if not job_id:
            return HandlerResult(
                response=ToolResponse(
                    success=False,
                    message="No active discovery job to retry agent for.",
                    data={"error": "no_active_job"},
                ),
                state_data=self.state_data,
            )

        job = await self._discovery_job_store.get_job(
            job_id,
            self.state.consultation_id or "",
        )
        if not job:
            return HandlerResult(
                response=ToolResponse(
                    success=False,
                    message="Discovery job not found. It may have expired.",
                    data={"error": "job_not_found", "job_id": job_id},
                ),
                state_data=self.state_data,
            )

        # Reset agent progress to running
        job.agent_progress[agent_id] = AgentProgress(
            agent=agent_id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        job.status = JobStatus.RUNNING  # Job is now running again
        await self._discovery_job_store.save_job(job)

        logger.info(
            "Retrying agent %s for job %s (session %s)",
            agent_id,
            job_id,
            self.state.session_id,
        )

        # Re-run the single agent
        trip_spec = getattr(self.state, 'trip_spec', None)
        if trip_spec:
            trip_spec_dict = trip_spec.to_dict() if hasattr(trip_spec, 'to_dict') else trip_spec
        else:
            trip_spec_dict = {}

        try:
            result_data = await self._call_discovery_agent(agent_id, trip_spec_dict)
            # Update job with successful result
            job.agent_progress[agent_id].status = "completed"
            job.agent_progress[agent_id].completed_at = datetime.now(timezone.utc)

            # Update discovery_results
            if not job.discovery_results:
                job.discovery_results = {}
            job.discovery_results[agent_id] = {
                "agent": agent_id,
                "status": "success",
                "data": result_data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except asyncio.TimeoutError:
            job.agent_progress[agent_id].status = "timeout"
            job.agent_progress[agent_id].completed_at = datetime.now(timezone.utc)
            job.agent_progress[agent_id].message = f"Timeout after {AGENT_TIMEOUTS.get(agent_id, DEFAULT_AGENT_TIMEOUT)}s"

        except Exception as e:
            job.agent_progress[agent_id].status = "failed"
            job.agent_progress[agent_id].completed_at = datetime.now(timezone.utc)
            job.agent_progress[agent_id].message = str(e)
            logger.error("Agent %s retry failed: %s", agent_id, e)

        # Check if all agents are now in terminal status
        all_terminal = self._all_agents_terminal(job)
        if all_terminal:
            # Trigger planning pipeline
            return await self._finalize_after_recovery(job)

        # Not all agents complete yet - save and return status
        await self._discovery_job_store.save_job(job)

        # Build progress summary
        progress_summary = {
            agent: {
                "status": progress.status,
                "message": progress.message,
            }
            for agent, progress in job.agent_progress.items()
        }

        return HandlerResult(
            response=ToolResponse(
                success=True,
                message=f"Retried {agent_id} search. {self._get_completion_message(job)}",
                data={
                    "agent": agent_id,
                    "action": "retry",
                    "agent_status": job.agent_progress[agent_id].status,
                    "agent_progress": progress_summary,
                },
                ui=UIDirective(
                    actions=[
                        UIAction(
                            label="View Progress",
                            event={"type": "status"},
                        ),
                    ],
                    text_input=True,
                ),
            ),
            state_data=self.state_data,
        )

    async def _skip_agent(self, agent_id: str) -> HandlerResult:
        """
        Skip a failed/timed-out discovery agent and continue with partial results.

        Per ORCH-093 and design doc Pipeline Execution with Gap Awareness:
        1. Validate agent_id is a known discovery agent
        2. Load current discovery job
        3. Mark agent as SKIPPED (distinct from completed - creates a gap)
        4. Record skip decision in discovery_results
        5. When all agents have terminal status, trigger planning pipeline
        6. Return itinerary preview (with gaps) when planning completes

        Args:
            agent_id: The agent to skip (transport, stay, poi, events, dining)

        Returns:
            HandlerResult with skip confirmation or itinerary preview
        """
        if agent_id not in DISCOVERY_AGENTS:
            return HandlerResult(
                response=ToolResponse(
                    success=False,
                    message=f"Unknown agent: {agent_id}. Valid agents: {', '.join(DISCOVERY_AGENTS)}",
                    data={"error": "invalid_agent", "valid_agents": list(DISCOVERY_AGENTS)},
                ),
                state_data=self.state_data,
            )

        # Get current job
        job_id = getattr(self.state, 'current_job_id', None)
        if not job_id:
            return HandlerResult(
                response=ToolResponse(
                    success=False,
                    message="No active discovery job to skip agent for.",
                    data={"error": "no_active_job"},
                ),
                state_data=self.state_data,
            )

        job = await self._discovery_job_store.get_job(
            job_id,
            self.state.consultation_id or "",
        )
        if not job:
            return HandlerResult(
                response=ToolResponse(
                    success=False,
                    message="Discovery job not found. It may have expired.",
                    data={"error": "job_not_found", "job_id": job_id},
                ),
                state_data=self.state_data,
            )

        # Mark agent as SKIPPED (distinct status for gap tracking)
        # Note: "skipped" is different from "completed" - skipped creates a known gap
        job.agent_progress[agent_id] = AgentProgress(
            agent=agent_id,
            status="skipped",  # Special status for user-skipped agents
            completed_at=datetime.now(timezone.utc),
            message="Skipped by user",
        )

        # Record skip decision in discovery_results
        if not job.discovery_results:
            job.discovery_results = {}
        job.discovery_results[agent_id] = {
            "agent": agent_id,
            "status": "skipped",  # Per design doc: DiscoveryStatus.SKIPPED
            "data": None,
            "message": "Skipped by user",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            "Skipped agent %s for job %s (session %s)",
            agent_id,
            job_id,
            self.state.session_id,
        )

        # Check if all agents are now in terminal status
        all_terminal = self._all_agents_terminal(job)
        if all_terminal:
            # Trigger planning pipeline
            return await self._finalize_after_recovery(job)

        # Not all agents complete yet - save and return status
        await self._discovery_job_store.save_job(job)

        # Build progress summary
        progress_summary = {
            agent: {
                "status": progress.status,
                "message": progress.message,
            }
            for agent, progress in job.agent_progress.items()
        }

        return HandlerResult(
            response=ToolResponse(
                success=True,
                message=f"Skipped {agent_id} search. {self._get_completion_message(job)}",
                data={
                    "agent": agent_id,
                    "action": "skip",
                    "agent_status": "skipped",
                    "agent_progress": progress_summary,
                },
                ui=UIDirective(
                    actions=[
                        UIAction(
                            label="View Progress",
                            event={"type": "status"},
                        ),
                    ],
                    text_input=True,
                ),
            ),
            state_data=self.state_data,
        )

    def _all_agents_terminal(self, job: DiscoveryJob) -> bool:
        """
        Check if all discovery agents have reached terminal status.

        Terminal statuses: completed, failed, timeout, skipped

        Args:
            job: The discovery job to check

        Returns:
            True if all agents are in terminal status
        """
        terminal_statuses = {"completed", "failed", "timeout", "skipped"}
        for agent in DISCOVERY_AGENTS:
            progress = job.agent_progress.get(agent)
            if not progress or progress.status not in terminal_statuses:
                return False
        return True

    def _get_completion_message(self, job: DiscoveryJob) -> str:
        """
        Get a message about agent completion status.

        Args:
            job: The discovery job

        Returns:
            Human-readable completion status message
        """
        terminal_statuses = {"completed", "failed", "timeout", "skipped"}
        completed = 0
        pending = 0
        for agent in DISCOVERY_AGENTS:
            progress = job.agent_progress.get(agent)
            if progress and progress.status in terminal_statuses:
                completed += 1
            else:
                pending += 1

        if pending == 0:
            return "All agent searches complete. Running planning pipeline..."
        else:
            return f"{completed}/{len(DISCOVERY_AGENTS)} agent searches complete, {pending} still pending."

    async def _finalize_after_recovery(self, job: DiscoveryJob) -> HandlerResult:
        """
        Finalize discovery and run planning after recovery actions complete.

        Per ORCH-093:
        1. Update job status based on results (COMPLETED, PARTIAL, FAILED)
        2. Run planning pipeline with available results + gaps
        3. Store itinerary draft in WorkflowState
        4. Set checkpoint="itinerary_approval"
        5. Return itinerary preview

        Args:
            job: The discovery job with all agents in terminal status

        Returns:
            HandlerResult with itinerary preview or error
        """
        from src.orchestrator.discovery.state_sync import run_planning_after_discovery

        # Determine job status based on agent results
        failed_count = 0
        skipped_count = 0
        success_count = 0
        for agent in DISCOVERY_AGENTS:
            progress = job.agent_progress.get(agent)
            if progress:
                if progress.status in ("failed", "timeout"):
                    failed_count += 1
                elif progress.status == "skipped":
                    skipped_count += 1
                elif progress.status == "completed":
                    success_count += 1

        # Update job status
        if failed_count + skipped_count == len(DISCOVERY_AGENTS):
            # All agents either failed or were skipped - that's a complete failure
            job.status = JobStatus.FAILED
        elif success_count == len(DISCOVERY_AGENTS):
            job.status = JobStatus.COMPLETED
        else:
            job.status = JobStatus.PARTIAL  # Some succeeded, some failed/skipped

        job.completed_at = datetime.now(timezone.utc)
        await self._discovery_job_store.save_job(job)

        logger.info(
            "Discovery job %s finalized after recovery: status=%s, success=%d, failed=%d, skipped=%d",
            job.job_id,
            job.status.value,
            success_count,
            failed_count,
            skipped_count,
        )

        # For FAILED jobs, don't run planning - return error with retry options
        if job.status == JobStatus.FAILED:
            return HandlerResult(
                response=ToolResponse(
                    success=False,
                    message="All discovery searches failed. Please retry or modify your trip requirements.",
                    data={
                        "job_id": job.job_id,
                        "status": job.status.value,
                        "failed_agents": [
                            agent for agent in DISCOVERY_AGENTS
                            if job.agent_progress.get(agent) and job.agent_progress[agent].status in ("failed", "timeout")
                        ],
                        "skipped_agents": [
                            agent for agent in DISCOVERY_AGENTS
                            if job.agent_progress.get(agent) and job.agent_progress[agent].status == "skipped"
                        ],
                    },
                    ui=UIDirective(
                        actions=[
                            UIAction(
                                label="Retry All",
                                event={"type": "retry_discovery", "checkpoint_id": "itinerary_approval"},
                            ),
                            UIAction(
                                label="Modify Trip",
                                event={"type": "request_change", "checkpoint_id": "itinerary_approval"},
                            ),
                        ],
                        text_input=True,
                    ),
                ),
                state_data=self.state_data,
            )

        # Get trip_spec as dict for planning pipeline
        trip_spec = getattr(self.state, 'trip_spec', None)
        if trip_spec and hasattr(trip_spec, 'to_dict'):
            trip_spec_dict = trip_spec.to_dict()
        elif trip_spec:
            trip_spec_dict = trip_spec if isinstance(trip_spec, dict) else {}
        else:
            trip_spec_dict = {}

        # Run planning pipeline
        try:
            planning_result = await run_planning_after_discovery(
                job=job,
                trip_spec=trip_spec_dict,
                a2a_client=self._a2a_client,
                agent_registry=self._agent_registry,
            )

            if not planning_result.success:
                # Planning failed
                job.pipeline_stage = "planning_failed"
                await self._discovery_job_store.save_job(job)

                return HandlerResult(
                    response=ToolResponse(
                        success=False,
                        message=f"Planning pipeline failed: {planning_result.blocker or 'Unknown error'}",
                        data={
                            "job_id": job.job_id,
                            "pipeline_stage": "planning_failed",
                            "blocker": planning_result.blocker,
                        },
                    ),
                    state_data=self.state_data,
                )

            # Planning succeeded - store itinerary draft
            job.pipeline_stage = "completed"
            job.itinerary_draft = planning_result.itinerary
            await self._discovery_job_store.save_job(job)

            # Update WorkflowState
            self.state.phase = Phase.DISCOVERY_PLANNING
            self.state.checkpoint = "itinerary_approval"
            self.state.current_step = "itinerary_approval"
            self.state.discovery_results = job.discovery_results
            self.state.itinerary_draft = planning_result.itinerary
            self.state.last_synced_job_id = job.job_id
            self._sync_state_to_data()

            # Return itinerary preview
            return await self._return_itinerary_preview(job)

        except Exception as e:
            logger.error("Planning pipeline failed: %s", e)
            job.pipeline_stage = "planning_failed"
            await self._discovery_job_store.save_job(job)

            return HandlerResult(
                response=ToolResponse(
                    success=False,
                    message=f"An error occurred while building your itinerary: {e}",
                    data={
                        "job_id": job.job_id,
                        "pipeline_stage": "planning_failed",
                        "error": str(e),
                    },
                ),
                state_data=self.state_data,
            )

    def _sync_state_to_data(self) -> None:
        """
        Sync WorkflowState changes back to WorkflowStateData.
        """
        # Update phase
        self.state_data.phase = self.state.phase.value

        # Update checkpoint and step
        self.state_data.checkpoint = self.state.checkpoint
        self.state_data.current_step = self.state.current_step

        # Update agent context IDs
        self.state_data.agent_context_ids = {
            name: state.to_dict()
            for name, state in self.state.agent_context_ids.items()
        }

        # Update current_job_id if the state_data has this field
        if hasattr(self.state_data, 'current_job_id'):
            self.state_data.current_job_id = self.state.current_job_id

        # Update itinerary_id if available
        if hasattr(self.state_data, 'itinerary_id') and hasattr(self.state, 'itinerary_id'):
            self.state_data.itinerary_id = self.state.itinerary_id

        # Update timestamp
        self.state_data.updated_at = datetime.now(timezone.utc)
