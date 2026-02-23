"""
OrchestratorExecutor: Bridges A2A protocol with orchestrator processing.

This executor implements the A2A protocol layer for the orchestrator,
translating A2A requests into orchestrator actions and streaming responses
back to clients.

Architecture (per design doc Overview section):
- OrchestratorExecutor extends BaseA2AAgentExecutor for A2A protocol support
- Delegates to OrchestratorAgent for actual request processing
- OrchestratorAgent uses three-layer routing (1a/1b/1c) for request handling

The orchestrator has two entry points that converge here:
1. A2A Protocol: OrchestratorServer → OrchestratorExecutor.execute()
2. Direct API: FastAPI → _process_intelligent_request() (future)

Both paths use the same OrchestratorAgent for request processing.

Routing layers (per design doc "Routing Flow" section):
- Layer 1a: Active session check → workflow_turn (no LLM)
- Layer 1b: Utility pattern match → utility handlers (no LLM)
- Layer 1c: LLM routing → workflow_turn, answer_question, or utilities

Per design doc Compatibility & Migration section:
- WorkflowStoreProtocol is instantiated via create_workflow_store factory
- STORAGE_BACKEND env var controls backend selection (memory/cosmos)
- All orchestrator modules depend on protocols, not implementations
"""

import json
import logging
from typing import TYPE_CHECKING, Any, AsyncGenerator

from src.shared.a2a.base_agent_executor import (
    AgentStreamChunk,
    BaseA2AAgentExecutor,
    StreamableAgent,
)
from src.orchestrator.storage.discovery_jobs import (
    DiscoveryJobStoreProtocol,
    InMemoryDiscoveryJobStore,
)
from src.orchestrator.storage import (
    BookingStoreProtocol,
    ConsultationSummaryStoreProtocol,
    InMemoryBookingStore,
    InMemoryConsultationSummaryStore,
    InMemoryItineraryStore,
    ItineraryStoreProtocol,
)
from src.shared.storage import WorkflowStoreProtocol, create_workflow_store

if TYPE_CHECKING:
    import httpx

    from infrastructure.azure_agent_setup import AzureAgentConfig
    from src.orchestrator.agent import OrchestratorLLM
    from src.orchestrator.models.workflow_state import WorkflowState
    from src.orchestrator.routing.layer1 import RouteResult
    from src.shared.a2a.client_wrapper import A2AClientWrapper
    from src.shared.a2a.registry import AgentRegistry

logger = logging.getLogger(__name__)


class OrchestratorAgent:
    """Orchestrator agent implementing StreamableAgent protocol.

    This agent bridges the A2A protocol with the orchestrator's core logic.
    It processes requests through a three-layer routing system:

    Layer 1a: Active session check (no LLM) - workflow_turn directly
    Layer 1b: Utility pattern match (no LLM) - regex-based utility routing
    Layer 1c: LLM routing (Azure AI Agent) - decides workflow_turn vs answer_question

    The routing logic is implemented in src/orchestrator/routing/layer1.py.

    Per design doc Compatibility & Migration section:
    - Uses WorkflowStoreProtocol for storage-backend agnostic workflow access
    - STORAGE_BACKEND env var controls backend selection at runtime
    """

    def __init__(
        self,
        azure_config: "AzureAgentConfig | None" = None,
        workflow_store: WorkflowStoreProtocol | None = None,
        discovery_job_store: DiscoveryJobStoreProtocol | None = None,
        itinerary_store: ItineraryStoreProtocol | None = None,
        booking_store: BookingStoreProtocol | None = None,
        consultation_summary_store: ConsultationSummaryStoreProtocol | None = None,
        llm: "OrchestratorLLM | None" = None,
        a2a_client: "A2AClientWrapper | None" = None,
        agent_registry: "AgentRegistry | None" = None,
    ) -> None:
        """Initialize the orchestrator agent.

        Args:
            azure_config: Optional Azure AI Agent Service configuration.
                         If None, the agent operates without LLM routing.
            workflow_store: Optional WorkflowStoreProtocol for session lookup and
                           state persistence. If None, Layer 1a (session check) is
                           disabled. Created via create_workflow_store() factory.
            itinerary_store: Optional store for itinerary persistence.
            booking_store: Optional store for booking persistence.
            consultation_summary_store: Optional store for consultation summaries.
            llm: Optional OrchestratorLLM instance for Layer 1c routing.
                If None, Layer 1c defaults to workflow_turn.
            a2a_client: Optional A2A client for downstream agent communication.
                       Required for handlers to call discovery, clarifier, etc.
            agent_registry: Optional agent registry for URL lookup.
                           Required with a2a_client to resolve agent URLs.
            discovery_job_store: Optional store for discovery job tracking.
        """
        self._azure_config = azure_config
        self._workflow_store = workflow_store
        self._discovery_job_store = discovery_job_store or InMemoryDiscoveryJobStore()
        self._itinerary_store = itinerary_store or InMemoryItineraryStore()
        self._booking_store = booking_store or InMemoryBookingStore()
        self._consultation_summary_store = (
            consultation_summary_store or InMemoryConsultationSummaryStore()
        )
        self._llm = llm
        self._a2a_client = a2a_client
        self._agent_registry = agent_registry
        self._session_threads: dict[str, dict[str, str]] = {}

        # Initialize workflow_turn context with stores and A2A client
        self._setup_workflow_turn_context()

        if azure_config and azure_config.has_connection_config:
            logger.info(
                "OrchestratorAgent initialized with Azure AI Agent Service config"
            )
        else:
            logger.info(
                "OrchestratorAgent initialized in placeholder mode "
                "(Azure AI config not provided)"
            )

    def _setup_workflow_turn_context(self) -> None:
        """Set up the global workflow_turn context with dependencies.

        Per design doc Compatibility & Migration section:
        - Uses WorkflowStoreProtocol for storage-backend agnostic access
        - Injects A2A client and registry for handler communication
        - Called once during agent initialization

        The UnifiedWorkflowTurnContext enables workflow_turn to:
        - Load/save workflow state via WorkflowStoreProtocol
        - Call downstream agents via A2A client
        - Resolve agent URLs via registry
        - Access itinerary/booking/summary stores for Phase 2/3 operations
        """
        if self._workflow_store is None:
            logger.debug(
                "No workflow store configured; workflow_turn context not set"
            )
            return

        from src.orchestrator.tools.workflow_turn import (
            UnifiedWorkflowTurnContext,
            set_unified_workflow_turn_context,
        )

        context = UnifiedWorkflowTurnContext(
            workflow_store=self._workflow_store,
            itinerary_store=self._itinerary_store,
            booking_store=self._booking_store,
            consultation_summary_store=self._consultation_summary_store,
            discovery_job_store=self._discovery_job_store,
            a2a_client=self._a2a_client,
            agent_registry=self._agent_registry,
        )
        set_unified_workflow_turn_context(context)
        logger.info(
            "Workflow turn context configured with store=%s, a2a_client=%s",
            type(self._workflow_store).__name__,
            "yes" if self._a2a_client else "no",
        )

    @property
    def is_azure_configured(self) -> bool:
        """Check if Azure AI Agent Service is configured."""
        return (
            self._azure_config is not None
            and self._azure_config.has_connection_config
        )

    @property
    def a2a_client(self) -> "A2AClientWrapper | None":
        """Get the A2A client for downstream agent communication."""
        return self._a2a_client

    @property
    def agent_registry(self) -> "AgentRegistry | None":
        """Get the agent registry for URL lookup."""
        return self._agent_registry

    async def stream(
        self,
        user_input: str,
        session_id: str,
        history: list[dict] | None = None,
        history_seq: int | None = None,
        event: dict[str, Any] | None = None,
    ) -> AsyncGenerator[AgentStreamChunk, None]:
        """Stream orchestrator responses.

        This is the main entry point for A2A protocol requests.
        The method delegates to _process_intelligent_request for core logic.

        Args:
            user_input: The user's message
            session_id: Session identifier for conversation tracking
            history: Optional conversation history for context
            history_seq: Optional sequence number for divergence detection
            event: Optional structured workflow event from UI actions

        Yields:
            AgentStreamChunk with response content and status flags
        """
        logger.info(
            "OrchestratorAgent.stream called with session_id=%s, "
            "history_len=%s, history_seq=%s",
            session_id,
            len(history) if history else 0,
            history_seq,
        )

        # Process the request through the intelligent routing system
        async for chunk in self._process_intelligent_request(
            message=user_input,
            session_id=session_id,
            history=history,
            history_seq=history_seq,
            event=event,
        ):
            yield chunk

    async def _process_intelligent_request(
        self,
        message: str,
        session_id: str,
        history: list[dict] | None = None,
        history_seq: int | None = None,
        event: dict[str, Any] | None = None,
    ) -> AsyncGenerator[AgentStreamChunk, None]:
        """Process a request through the three-layer routing system.

        This implements the design doc "Routing Flow":
        - Layer 1a: Check for active session → workflow_turn
        - Layer 1b: Match utility patterns → utility handlers
        - Layer 1c: LLM routing → workflow_turn, answer_question, or utilities

        Args:
            message: The user's message to process
            session_id: Session identifier for state management
            history: Optional conversation history
            history_seq: Optional sequence number for divergence detection
            event: Optional structured workflow event (bypasses routing)

        Yields:
            AgentStreamChunk with processing results
        """
        from src.orchestrator.routing import RouteResult, RouteTarget, route

        # Log request details for debugging
        logger.debug(
            "Processing request: session_id=%s, message_preview=%s...",
            session_id,
            message[:50] if len(message) > 50 else message,
        )

        # Load state for Layer 1a check (if store is available)
        state = await self._load_workflow_state(session_id)

        if event is not None:
            # Structured events go straight to workflow_turn for validation.
            route_result = RouteResult(
                target=RouteTarget.WORKFLOW_TURN,
                layer="event",
                state=state,
                tool_args={
                    "session_ref": {"session_id": session_id},
                    "message": message,
                    "event": event,
                },
            )
        else:
            # Route through the three-layer system
            route_result = await route(
                message=message,
                session_id=session_id,
                state=state,
                llm=self._llm,
            )

        logger.info(
            "Routing result: target=%s, layer=%s",
            route_result.target.value,
            route_result.layer,
        )

        # Handle the routing result
        async for chunk in self._handle_route_result(
            route_result, message, session_id, history, history_seq
        ):
            yield chunk

    async def _load_workflow_state(
        self, session_id: str
    ) -> "WorkflowState | None":
        """Load workflow state for Layer 1a session check.

        Uses WorkflowStoreProtocol for storage-backend agnostic access.
        Per design doc Session Management section, lookup by session_id is
        the primary (O(1)) path.

        Args:
            session_id: The session identifier

        Returns:
            WorkflowState if found, None otherwise
        """
        if self._workflow_store is None:
            return None

        try:
            return await self._workflow_store.get_by_session(session_id)
        except Exception as e:
            logger.warning(
                "Error loading state for session %s: %s",
                session_id,
                str(e),
            )
            return None

    async def _handle_route_result(
        self,
        route_result: "RouteResult",
        message: str,
        session_id: str,
        history: list[dict] | None = None,
        history_seq: int | None = None,
    ) -> AsyncGenerator[AgentStreamChunk, None]:
        """Handle the routing result by dispatching to appropriate handler.

        Args:
            route_result: The routing decision
            message: Original user message
            session_id: Session identifier
            history: Optional conversation history
            history_seq: Optional sequence number

        Yields:
            AgentStreamChunk with handler results
        """
        from src.orchestrator.routing import RouteTarget

        target = route_result.target
        tool_args = route_result.tool_args or {}

        if target == RouteTarget.WORKFLOW_TURN:
            # Handle workflow operations
            async for chunk in self._handle_workflow_turn(
                tool_args, session_id, history, history_seq
            ):
                yield chunk

        elif target == RouteTarget.ANSWER_QUESTION:
            # Handle stateless Q&A
            async for chunk in self._handle_answer_question(tool_args, session_id):
                yield chunk

        elif target in (
            RouteTarget.CURRENCY_CONVERT,
            RouteTarget.WEATHER_LOOKUP,
            RouteTarget.TIMEZONE_INFO,
            RouteTarget.GET_BOOKING,
            RouteTarget.GET_CONSULTATION,
        ):
            # Handle utility requests
            async for chunk in self._handle_utility(target, tool_args):
                yield chunk

        else:
            # Unknown target - shouldn't happen
            logger.error("Unknown route target: %s", target)
            from src.orchestrator.errors import create_error_response

            error_response = create_error_response(
                "INTERNAL_ERROR",
                message=f"Internal error: unknown route target {target}",
                details={"target": str(target)},
            )
            yield AgentStreamChunk(
                require_user_input=error_response.retryable,
                is_task_complete=not error_response.retryable,
                content=error_response.error_message,
                data={"error": error_response.to_dict()},
            )

    async def _handle_workflow_turn(
        self,
        tool_args: dict[str, Any],
        session_id: str,
        history: list[dict] | None = None,
        history_seq: int | None = None,
    ) -> AsyncGenerator[AgentStreamChunk, None]:
        """Handle workflow_turn requests.

        This delegates to the workflow_turn tool handler.

        Args:
            tool_args: Arguments for workflow_turn
            session_id: Session identifier
            history: Optional conversation history
            history_seq: Optional sequence number

        Yields:
            AgentStreamChunk with workflow results
        """
        from src.orchestrator.tools import workflow_turn

        try:
            # Call workflow_turn with the provided args
            result = await workflow_turn(
                session_ref=tool_args.get("session_ref"),
                message=tool_args.get("message", ""),
                event=tool_args.get("event"),
            )

            # Convert ToolResponse to stream chunk
            response_json = json.dumps(result.to_dict())
            requires_input = False
            if not result.success:
                requires_input = True
            if isinstance(result.data, dict) and result.data.get("requires_input"):
                requires_input = True
            if isinstance(result.ui, dict):
                if result.ui.get("actions"):
                    requires_input = True
                if result.ui.get("text_input") is False:
                    requires_input = True

            yield AgentStreamChunk(
                require_user_input=requires_input,
                is_task_complete=result.success and not requires_input,
                content=result.message,
                data={"response": result.to_dict()},
            )

        except Exception as e:
            logger.error("Error in workflow_turn: %s", str(e), exc_info=True)
            # Convert exception to structured error response
            from src.orchestrator.errors import error_to_response

            error_response = error_to_response(e)
            yield AgentStreamChunk(
                require_user_input=error_response.retryable,
                is_task_complete=not error_response.retryable,
                content=error_response.error_message,
                data={"error": error_response.to_dict()},
            )

    async def _handle_answer_question(
        self,
        tool_args: dict[str, Any],
        session_id: str,
    ) -> AsyncGenerator[AgentStreamChunk, None]:
        """Handle answer_question requests.

        This delegates to the answer_question tool handler.

        Args:
            tool_args: Arguments for answer_question
            session_id: Session identifier

        Yields:
            AgentStreamChunk with Q&A results
        """
        from src.orchestrator.tools import answer_question

        try:
            # Call answer_question with the provided args
            result = await answer_question(
                question=tool_args.get("question", ""),
                domain=tool_args.get("domain", "general"),
                context=tool_args.get("context"),
            )

            yield AgentStreamChunk(
                require_user_input=False,
                is_task_complete=True,
                content=result.message,
                data={"response": result.to_dict()},
            )

        except Exception as e:
            logger.error("Error in answer_question: %s", str(e), exc_info=True)
            # Convert exception to structured error response
            from src.orchestrator.errors import error_to_response

            error_response = error_to_response(e)
            yield AgentStreamChunk(
                require_user_input=error_response.retryable,
                is_task_complete=not error_response.retryable,
                content=error_response.error_message,
                data={"error": error_response.to_dict()},
            )

    async def _handle_utility(
        self,
        target: "RouteTarget",
        tool_args: dict[str, Any],
    ) -> AsyncGenerator[AgentStreamChunk, None]:
        """Handle utility requests (currency, weather, timezone, lookups).

        Args:
            target: The utility target
            tool_args: Arguments for the utility

        Yields:
            AgentStreamChunk with utility results
        """
        from src.orchestrator.routing import RouteTarget

        # Stub implementations for utilities
        # Full implementations will be in ORCH-060, ORCH-061, ORCH-062, ORCH-063, ORCH-064
        try:
            if target == RouteTarget.CURRENCY_CONVERT:
                amount = tool_args.get("amount", 0)
                from_curr = tool_args.get("from_currency", "USD")
                to_curr = tool_args.get("to_currency", "EUR")
                # Stub response - actual implementation in ORCH-060
                result = f"{amount} {from_curr} = [conversion pending] {to_curr}"

            elif target == RouteTarget.WEATHER_LOOKUP:
                location = tool_args.get("location", "Unknown")
                # Stub response - actual implementation in ORCH-061
                result = f"Weather for {location}: [forecast pending]"

            elif target == RouteTarget.TIMEZONE_INFO:
                location = tool_args.get("location", "Unknown")
                # Stub response - actual implementation in ORCH-062
                result = f"Time in {location}: [timezone info pending]"

            elif target == RouteTarget.GET_BOOKING:
                booking_id = tool_args.get("booking_id", "unknown")
                # Stub response - actual implementation in ORCH-063
                result = f"Booking {booking_id}: [lookup pending]"

            elif target == RouteTarget.GET_CONSULTATION:
                consultation_id = tool_args.get("consultation_id", "unknown")
                # Stub response - actual implementation in ORCH-064
                result = f"Consultation {consultation_id}: [lookup pending]"

            else:
                result = f"Unknown utility: {target}"

            yield AgentStreamChunk(
                require_user_input=False,
                is_task_complete=True,
                content=result,
            )

        except Exception as e:
            logger.error("Error in utility handler: %s", str(e), exc_info=True)
            # Convert exception to structured error response
            from src.orchestrator.errors import error_to_response

            error_response = error_to_response(e)
            yield AgentStreamChunk(
                require_user_input=error_response.retryable,
                is_task_complete=not error_response.retryable,
                content=error_response.error_message,
                data={"error": error_response.to_dict()},
            )


class OrchestratorExecutor(BaseA2AAgentExecutor):
    """Executor that bridges A2A protocol with the orchestrator agent.

    This executor extends BaseA2AAgentExecutor to:
    1. Handle A2A protocol requests via execute()
    2. Extract history from request metadata for multi-turn conversations
    3. Stream responses back through the A2A protocol

    The executor delegates actual request processing to OrchestratorAgent,
    which implements the three-layer routing system described in the design doc.

    Architecture (per design doc Overview section):
    - Entry Point 1: A2A Protocol → OrchestratorServer → execute()
    - Entry Point 2: Direct API → _process_intelligent_request() (future)

    Per design doc Compatibility & Migration section:
    - WorkflowStoreProtocol instantiated via create_workflow_store() factory
    - STORAGE_BACKEND env var controls backend selection (memory/cosmos)
    """

    def __init__(
        self,
        agent: StreamableAgent | None = None,
        azure_config: "AzureAgentConfig | None" = None,
        workflow_store: WorkflowStoreProtocol | None = None,
        discovery_job_store: DiscoveryJobStoreProtocol | None = None,
        itinerary_store: ItineraryStoreProtocol | None = None,
        booking_store: BookingStoreProtocol | None = None,
        consultation_summary_store: ConsultationSummaryStoreProtocol | None = None,
        llm: "OrchestratorLLM | None" = None,
        a2a_client: "A2AClientWrapper | None" = None,
        agent_registry: "AgentRegistry | None" = None,
        httpx_client: "httpx.AsyncClient | None" = None,
    ) -> None:
        """Initialize the orchestrator executor.

        Args:
            agent: Optional pre-configured agent (for testing)
            azure_config: Optional Azure AI Agent Service configuration
            workflow_store: Optional WorkflowStoreProtocol for session lookup
                           and state persistence. If None, create_workflow_store()
                           is called to instantiate based on STORAGE_BACKEND env var.
            discovery_job_store: Optional store for discovery job tracking.
            itinerary_store: Optional store for itinerary persistence.
            booking_store: Optional store for booking persistence.
            consultation_summary_store: Optional store for consultation summaries.
            llm: Optional OrchestratorLLM instance for Layer 1c routing.
                If None, attempts to load from environment configuration.
            a2a_client: Optional A2A client for downstream agent communication.
                       Passed to handlers for calling discovery, clarifier, etc.
            agent_registry: Optional agent registry for URL lookup.
                           Required with a2a_client to resolve agent URLs.
            httpx_client: Optional httpx client to build an A2A client when one
                          is not explicitly provided.
        """
        self._azure_config = azure_config
        # Use provided workflow_store or create via factory
        self._workflow_store = workflow_store or create_workflow_store()
        self._discovery_job_store = discovery_job_store or InMemoryDiscoveryJobStore()
        self._itinerary_store = itinerary_store or InMemoryItineraryStore()
        self._booking_store = booking_store or InMemoryBookingStore()
        self._consultation_summary_store = (
            consultation_summary_store or InMemoryConsultationSummaryStore()
        )
        self._llm = self._init_llm(llm)
        self._a2a_client = a2a_client
        if self._a2a_client is None and httpx_client is not None:
            from src.shared.a2a.client_wrapper import A2AClientWrapper

            self._a2a_client = A2AClientWrapper(httpx_client=httpx_client)

        self._agent_registry = agent_registry
        if self._agent_registry is None and self._a2a_client is not None:
            from src.shared.a2a.registry import AgentRegistry

            self._agent_registry = AgentRegistry.load()
        # Call parent init which will call build_agent() if agent is None
        super().__init__(agent=agent)

    def _init_llm(
        self, llm: "OrchestratorLLM | None"
    ) -> "OrchestratorLLM | None":
        """Initialize the LLM wrapper from env config when not provided."""
        if llm is not None:
            return llm

        try:
            from src.orchestrator.agent import OrchestratorLLM
            from src.orchestrator.azure_agent import (
                ConfigurationError,
                load_agent_config,
            )
        except Exception as exc:
            logger.debug("LLM helpers unavailable: %s", exc)
            return None

        try:
            config = load_agent_config()
        except ConfigurationError as exc:
            logger.info("Azure LLM not configured: %s", exc)
            return None

        return OrchestratorLLM(config)

    def build_agent(self) -> StreamableAgent:
        """Build the orchestrator agent instance.

        Creates an OrchestratorAgent with Azure configuration if available.
        The agent handles the actual request processing and routing.
        Uses WorkflowStoreProtocol for storage-backend agnostic workflow access.
        Passes A2A client and registry for downstream agent communication.
        """
        return OrchestratorAgent(
            azure_config=self._azure_config,
            workflow_store=self._workflow_store,
            discovery_job_store=self._discovery_job_store,
            itinerary_store=self._itinerary_store,
            booking_store=self._booking_store,
            consultation_summary_store=self._consultation_summary_store,
            llm=self._llm,
            a2a_client=self._a2a_client,
            agent_registry=self._agent_registry,
        )

    def get_completion_artifact_name(self) -> str:
        """Return the name for completion artifacts.

        This name appears in A2A response artifacts when tasks complete.
        """
        return "orchestrator_response"

    def get_completion_artifact_description(self) -> str:
        """Return the description for completion artifacts.

        This description provides context about the response content.
        """
        return "Response from the travel planner orchestrator"

    @property
    def is_azure_configured(self) -> bool:
        """Check if Azure AI Agent Service is configured."""
        return (
            self._azure_config is not None
            and self._azure_config.has_connection_config
        )

    @property
    def workflow_store(self) -> WorkflowStoreProtocol:
        """Get the workflow store for external access.

        Useful for setting up workflow_turn context or integration tests.
        """
        return self._workflow_store

    @property
    def a2a_client(self) -> "A2AClientWrapper | None":
        """Get the A2A client for downstream agent communication."""
        return self._a2a_client

    @property
    def agent_registry(self) -> "AgentRegistry | None":
        """Get the agent registry for URL lookup."""
        return self._agent_registry
