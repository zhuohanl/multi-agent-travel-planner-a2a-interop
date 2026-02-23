"""
ClarificationHandler: Phase 1 handler for gathering trip requirements.

Per design doc Three-Phase Workflow and workflow_turn Internal Implementation sections:
- Orchestrates multi-turn dialog with the clarifier agent
- Builds up TripSpec through iterative questioning
- Detects when clarification is complete (ready_to_plan)
- Sets checkpoint="trip_spec_approval" when TripSpec is ready

Actions handled:
- START_CLARIFICATION / CONTINUE_CLARIFICATION: Send message to clarifier
- APPROVE_TRIP_SPEC: Transition to Discovery phase
- REQUEST_MODIFICATION: Handle modification requests during clarification
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from src.orchestrator.discovery import DISCOVERY_AGENTS, spawn_discovery_job
from src.orchestrator.models.responses import ToolResponse, UIAction, UIDirective
from src.orchestrator.models.workflow_state import (
    AgentA2AState,
    Phase,
    WorkflowState,
)
from src.orchestrator.state_gating import Action, WorkflowEvent
from src.orchestrator.storage import WorkflowStateData
from src.orchestrator.storage.discovery_jobs import (
    AgentProgress,
    DiscoveryJob,
    DiscoveryJobStoreProtocol,
    InMemoryDiscoveryJobStore,
    JobStatus,
)
from src.orchestrator.utils import generate_job_id

if TYPE_CHECKING:
    from src.orchestrator.storage.chat_messages import ChatMessageStoreProtocol
    from src.shared.a2a.client_wrapper import A2AClientWrapper, A2AResponse
    from src.shared.a2a.registry import AgentRegistry
    from src.shared.storage.protocols import WorkflowStoreProtocol

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Handler Response
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class HandlerResult:
    """
    Result from a phase handler execution.

    Contains the tool response to return and updated state data.
    """

    response: ToolResponse
    state_data: WorkflowStateData


# ═══════════════════════════════════════════════════════════════════════════════
# Base Handler Protocol
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class PhaseHandlerProtocol(Protocol):
    """Protocol for phase handlers."""

    async def execute(
        self,
        action: Action,
        message: str,
        event: WorkflowEvent | None = None,
    ) -> HandlerResult:
        """Execute an action for this phase."""
        ...


class PhaseHandler(ABC):
    """
    Base class for phase-specific handlers.

    Per design doc workflow_turn Internal Implementation:
    - Each handler receives the current state and can modify it
    - Handlers return HandlerResult with response and updated state
    """

    def __init__(
        self,
        state: WorkflowState,
        state_data: WorkflowStateData,
    ):
        """
        Initialize the handler.

        Args:
            state: Domain model for validation and business logic
            state_data: Storage model for persistence
        """
        self.state = state
        self.state_data = state_data

    @abstractmethod
    async def execute(
        self,
        action: Action,
        message: str,
        event: WorkflowEvent | None = None,
    ) -> HandlerResult:
        """
        Execute the action for this phase.

        Args:
            action: The determined action to execute
            message: The user's message text
            event: The original event with payload (optional)

        Returns:
            HandlerResult with response and updated state
        """
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# Clarification Handler
# ═══════════════════════════════════════════════════════════════════════════════


class ClarificationHandler(PhaseHandler):
    """
    Handles Phase 1: Clarification.

    Orchestrates multi-turn dialog with the clarifier agent to build up the TripSpec.

    Per design doc Three-Phase Workflow section:
    - Sends user messages to clarifier agent with history injection
    - Updates TripSpec from clarifier response when ready
    - Sets checkpoint="trip_spec_approval" for user approval
    - Transitions to DISCOVERY_IN_PROGRESS on approval
    """

    def __init__(
        self,
        state: WorkflowState,
        state_data: WorkflowStateData,
        a2a_client: "A2AClientWrapper | None" = None,
        agent_registry: "AgentRegistry | None" = None,
        chat_message_store: "ChatMessageStoreProtocol | None" = None,
        discovery_job_store: DiscoveryJobStoreProtocol | None = None,
        workflow_store: "WorkflowStoreProtocol | None" = None,
    ):
        """
        Initialize the clarification handler.

        Args:
            state: Domain model for validation and business logic
            state_data: Storage model for persistence
            a2a_client: A2A client for agent communication (optional for testing)
            agent_registry: Agent registry for URL lookup (optional for testing)
            chat_message_store: Chat message store for overflow persistence (optional)
            discovery_job_store: Store for discovery job persistence (optional for testing)
            workflow_store: Store for workflow state (optional for background discovery)
        """
        super().__init__(state, state_data)
        self._a2a_client = a2a_client
        self._agent_registry = agent_registry
        self._chat_message_store = chat_message_store
        self._discovery_job_store = discovery_job_store or InMemoryDiscoveryJobStore()
        self._workflow_store = workflow_store

        # Set up overflow callback if chat message store is provided
        if chat_message_store is not None:
            self._setup_overflow_callback()

    async def execute(
        self,
        action: Action,
        message: str,
        event: WorkflowEvent | None = None,
    ) -> HandlerResult:
        """
        Execute the action for clarification phase.

        Per design doc, valid actions in CLARIFICATION:
        - START_CLARIFICATION / CONTINUE_CLARIFICATION: Send to clarifier
        - APPROVE_TRIP_SPEC: Transition to discovery
        - REQUEST_MODIFICATION: Handle modification request
        """
        match action:
            case Action.START_CLARIFICATION | Action.CONTINUE_CLARIFICATION:
                return await self._continue_clarification(message)

            case Action.APPROVE_TRIP_SPEC:
                return await self._approve_trip_spec()

            case Action.REQUEST_MODIFICATION:
                return await self._handle_modification(message)

            case _:
                # Invalid action for this phase - should not reach here
                # due to validate_action_for_phase in workflow_turn
                logger.warning(
                    "Invalid action %s for CLARIFICATION phase, treating as continue",
                    action.value,
                )
                return await self._continue_clarification(message)

    async def _continue_clarification(self, message: str) -> HandlerResult:
        """
        Send message to Clarifier agent.

        Per design doc:
        - Gets existing A2A state or starts fresh
        - Calls clarifier with history injection
        - Updates agent_context_ids with new context/task IDs
        - Appends turn to clarifier_conversation
        - Checks if clarification is complete (is_task_complete)
        """
        # Check if we have A2A client available
        if self._a2a_client is None or self._agent_registry is None:
            # Return stub response when no A2A client is configured
            # This allows testing without real agents
            return self._create_stub_clarification_response(message)

        try:
            # Get clarifier agent URL
            clarifier_config = self._agent_registry.get("clarifier")
            agent_url = clarifier_config.url

            # Get existing A2A state or start fresh
            agent_state = self.state.get_agent_a2a_state("clarifier")

            # Build history for injection
            history = self.state.clarifier_conversation.to_history_list()
            history_seq = self.state.clarifier_conversation.current_seq

            # Call clarifier agent
            response = await self._a2a_client.send_message(
                agent_url=agent_url,
                message=message,
                context_id=agent_state.context_id,
                task_id=agent_state.task_id,
                history=history if history else None,
                history_seq=history_seq,
            )

            # Store updated A2A state
            # Note: We need to explicitly clear task_id when complete
            clarifier_state = self.state.get_agent_a2a_state("clarifier")
            if response.context_id is not None:
                clarifier_state.context_id = response.context_id
            # Clear task_id when task is complete, otherwise update from response
            if response.is_complete:
                clarifier_state.task_id = None
            elif response.task_id is not None:
                clarifier_state.task_id = response.task_id

            # Append to conversation history
            self.state.clarifier_conversation.append_turn(
                user_content=message,
                assistant_content=response.text,
            )

            # Sync state changes back to state_data
            self._sync_state_to_data()

            # Check if clarification is complete
            if response.is_complete:
                return self._handle_clarification_complete(response)

            # Clarification continues - return response with input required
            return HandlerResult(
                response=ToolResponse(
                    success=True,
                    message=response.text,
                    data={"requires_input": True},
                ),
                state_data=self.state_data,
            )

        except Exception as e:
            logger.error(f"Error calling clarifier agent: {e}")
            return HandlerResult(
                response=ToolResponse(
                    success=False,
                    message="I'm having trouble connecting to the trip planner. Please try again.",
                    data={"error": str(e)},
                ),
                state_data=self.state_data,
            )

    def _handle_clarification_complete(
        self, response: "A2AResponse"
    ) -> HandlerResult:
        """
        Handle completed clarification - set checkpoint for approval.

        Per design doc:
        - Parse trip_spec from response data
        - Set checkpoint="trip_spec_approval"
        - Set current_step="approval"
        - Return UI with Approve/Request Changes buttons
        """
        # Try to extract trip_spec from response
        # The clarifier agent should return structured data when complete
        trip_spec = self._extract_trip_spec_from_response(response)

        # Update state
        self.state.trip_spec = trip_spec
        self.state.checkpoint = "trip_spec_approval"
        self.state.current_step = "approval"

        # Sync to state_data
        self._sync_state_to_data()

        # Generate checkpoint_id for approval events
        checkpoint_id = "trip_spec_approval"

        return HandlerResult(
            response=ToolResponse(
                success=True,
                message=response.text,
                data={
                    "trip_spec": trip_spec,
                    "checkpoint": checkpoint_id,
                },
                ui=UIDirective(
                    actions=[
                        UIAction(
                            label="Approve",
                            event={
                                "type": "approve_checkpoint",
                                "checkpoint_id": checkpoint_id,
                            },
                        ),
                        UIAction(
                            label="Request Changes",
                            event={
                                "type": "request_change",
                                "checkpoint_id": checkpoint_id,
                            },
                        ),
                    ],
                    text_input=False,  # Approval checkpoint - buttons only
                ),
            ),
            state_data=self.state_data,
        )

    def _extract_trip_spec_from_response(
        self, response: "A2AResponse"
    ) -> dict[str, Any] | None:
        """
        Extract TripSpec from clarifier response.

        The clarifier agent returns structured data when clarification is complete.
        We look for trip_spec in various response locations.
        """
        def _parse_json_payload(text: str) -> Any | None:
            if not text:
                return None
            raw = text.strip()
            if not raw:
                return None
            # Strip fenced code blocks if present.
            if raw.startswith("```"):
                fence_end = raw.rfind("```")
                if fence_end > 0:
                    raw = raw[3:fence_end].strip()
                    if raw.lower().startswith("json"):
                        raw = raw[4:].strip()
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
            # Fall back to the first JSON object embedded in text.
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                snippet = raw[start : end + 1]
                try:
                    return json.loads(snippet)
                except json.JSONDecodeError:
                    return None
            return None

        def _looks_like_trip_spec(payload: dict[str, Any]) -> bool:
            expected_keys = {
                "destination_city",
                "origin_city",
                "start_date",
                "end_date",
                "num_travelers",
                "budget_per_person",
                "budget_currency",
            }
            return any(key in payload for key in expected_keys)

        def _extract_trip_spec(data: Any) -> dict[str, Any] | None:
            if isinstance(data, dict):
                trip_spec = None
                from_wrapper = False
                if isinstance(data.get("trip_spec"), dict):
                    trip_spec = data.get("trip_spec")
                    from_wrapper = True
                elif isinstance(data.get("tripSpec"), dict):
                    trip_spec = data.get("tripSpec")
                    from_wrapper = True
                else:
                    trip_spec = data
                if trip_spec and isinstance(trip_spec, dict):
                    if from_wrapper or _looks_like_trip_spec(trip_spec):
                        return trip_spec
            if isinstance(data, str):
                nested = _parse_json_payload(data)
                if nested is not None:
                    return _extract_trip_spec(nested)
            return None

        candidates: list[str] = []
        if response.text:
            candidates.append(response.text)
        for chunk in response.raw_chunks:
            result = chunk.get("result", {})
            for container_key in ("artifact", "message", "status"):
                container = result.get(container_key, {})
                parts = container.get("parts")
                if isinstance(parts, list):
                    for part in parts:
                        text = part.get("text")
                        if isinstance(text, str):
                            candidates.append(text)

        for candidate in candidates:
            parsed = _parse_json_payload(candidate)
            trip_spec = _extract_trip_spec(parsed)
            if trip_spec is not None:
                return trip_spec

        logger.warning("Unable to parse trip_spec from clarifier response text.")
        return None

    async def _approve_trip_spec(self) -> HandlerResult:
        """
        User approved TripSpec - transition to Discovery phase.

        Per design doc:
        - Transition to DISCOVERY_IN_PROGRESS phase
        - Clear checkpoint
        - Set current_step="running"
        - Start discovery job and set current_job_id

        Per ORCH-102:
        - Creates DiscoveryJob and saves to store
        - Initializes agent progress for all discovery agents
        - Returns job_id and stream_url for client
        """
        # Create discovery job
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

        # Update state for phase transition
        self.state.phase = Phase.DISCOVERY_IN_PROGRESS
        self.state.checkpoint = None
        self.state.current_step = "running"
        self.state.current_job_id = job_id

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

        return HandlerResult(
            response=ToolResponse(
                success=True,
                message="Great! Starting to search for your trip options...",
                data={
                    "job_id": job_id,
                    "stream_url": f"/sessions/{self.state.session_id}/discovery/stream",
                    "phase": "discovery_in_progress",
                },
                ui=UIDirective(
                    actions=[
                        UIAction(
                            label="Continue in Background",
                            event={"type": "status"},
                        ),
                    ],
                    text_input=False,
                ),
            ),
            state_data=self.state_data,
        )

    async def _handle_modification(self, message: str) -> HandlerResult:
        """
        Handle modification request during clarification.

        User wants to change something about the trip spec.
        Continue clarification dialog with the modification request.
        """
        # Clear checkpoint since we're going back to gathering
        if self.state.checkpoint == "trip_spec_approval":
            self.state.checkpoint = None
            self.state.current_step = "gathering"
            self._sync_state_to_data()

        # Continue clarification with the modification message
        return await self._continue_clarification(message)

    def _create_stub_clarification_response(self, message: str) -> HandlerResult:
        """
        Create a stub response when no A2A client is configured.

        Used for testing without real agents.
        """
        # Add a stub message to conversation history
        stub_response = (
            f"I received your message: '{message[:50]}...' "
            "I'm here to help plan your trip. What are your travel dates and destination?"
        )

        self.state.clarifier_conversation.append_turn(
            user_content=message,
            assistant_content=stub_response,
        )

        # Sync to state_data
        self._sync_state_to_data()

        return HandlerResult(
            response=ToolResponse(
                success=True,
                message=stub_response,
                data={"requires_input": True, "stub": True},
            ),
            state_data=self.state_data,
        )

    def _setup_overflow_callback(self) -> None:
        """
        Set up the overflow callback for conversation history persistence.

        When clarifier_conversation exceeds SUMMARY_THRESHOLD messages,
        older messages are persisted to chat_messages and summarized.
        """
        if self._chat_message_store is None:
            return

        from src.orchestrator.models.conversation import ConversationMessage

        session_id = self.state.session_id

        def persist_overflow(messages: list[ConversationMessage]) -> None:
            """Persist overflow messages to chat_messages store."""
            import asyncio

            async def _persist() -> None:
                for msg in messages:
                    await self._chat_message_store.append_message(  # type: ignore
                        session_id=session_id,
                        message_id=msg.message_id,
                        role=msg.role,
                        content=msg.content,
                    )

            # Run async persistence
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_persist())
            except RuntimeError:
                # No running loop - run synchronously
                asyncio.run(_persist())

        self.state.clarifier_conversation.set_overflow_callback(persist_overflow)

    def _sync_state_to_data(self) -> None:
        """
        Sync WorkflowState changes back to WorkflowStateData.

        WorkflowStateData is the storage model; this updates it with
        changes made to the domain model.

        Note: WorkflowStateData has specific fields for core state,
        and agent_context_ids dict for agent-specific state.
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

        # Sync overflow count from conversation to state_data
        # This ensures overflow count is persisted with the workflow state
        self.state.conversation_overflow_count = (
            self.state.clarifier_conversation.overflow_message_count
        )

        # Note: clarifier_conversation and trip_spec are stored in
        # WorkflowState.to_dict() which is the full serialization.
        # WorkflowStateData is a simplified storage model that tracks
        # session identity and phase - the full state is in WorkflowState.
        # For now, we rely on the domain model holding conversation state.

        # Update timestamp
        self.state_data.updated_at = datetime.now(timezone.utc)
