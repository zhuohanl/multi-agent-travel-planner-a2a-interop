"""FastAPI entry point for the orchestrator direct API."""

from __future__ import annotations

import logging
import os
import uuid
import inspect
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.orchestrator.api.agent_registry import AgentRegistryApi
from src.orchestrator.api.discovery import create_discovery_router
from src.orchestrator.storage.session_state import WorkflowStateData

logger = logging.getLogger(__name__)


# =============================================================================
# Request/Response Models
# =============================================================================


class ChatRequest(BaseModel):
    """Request model for POST /chat endpoint."""

    message: str = Field(..., description="The user's message to process")
    session_id: str | None = Field(
        default=None,
        description="Session identifier. If not provided, a new session is created.",
    )


class ChatResponse(BaseModel):
    """Response model for POST /chat endpoint."""

    message: str = Field(..., description="The orchestrator's response message")
    session_id: str = Field(..., description="Session identifier for conversation tracking")
    consultation_id: str | None = Field(
        default=None,
        description="Consultation ID if a trip planning session was started or resumed",
    )
    data: dict[str, Any] | None = Field(
        default=None,
        description="Additional structured data from the response",
    )


class ChatStreamChunk(BaseModel):
    """Model for SSE stream chunks from GET /chat/stream."""

    message: str = Field(..., description="Partial message content")
    session_id: str = Field(..., description="Session identifier")
    consultation_id: str | None = Field(
        default=None,
        description="Consultation ID if available",
    )
    is_complete: bool = Field(
        default=False,
        description="True if this is the final chunk",
    )
    require_user_input: bool = Field(
        default=False,
        description="True if the orchestrator is waiting for user input",
    )
    data: dict[str, Any] | None = Field(
        default=None,
        description="Additional structured data",
    )


class SessionEventRequest(BaseModel):
    """Request payload for structured workflow events."""

    type: str = Field(..., description="Workflow event type")
    checkpoint_id: str | None = Field(default=None)
    booking: dict[str, Any] | None = Field(default=None)
    agent_id: str | None = Field(default=None)
    agent: str | None = Field(default=None)
    message: str | None = Field(
        default=None,
        description="Optional free-text message for type=free_text",
    )


class AddAgentRequest(BaseModel):
    """Request payload for adding a custom agent."""

    name: str
    url: str


class SessionMessage(BaseModel):
    """Chat message item returned in session state."""

    id: str
    role: str
    sender: str
    content: str
    created_at: str


class PendingAction(BaseModel):
    """Action surfaced by workflow_turn UI metadata."""

    event: dict[str, Any]
    label: str
    description: str | None = None


class SessionStateResponse(BaseModel):
    """Session snapshot returned by GET /sessions/{session_id}."""

    session_id: str
    phase: str | None = None
    checkpoint: str | None = None
    messages: list[SessionMessage] = Field(default_factory=list)
    pending_actions: list[PendingAction] = Field(default_factory=list)
    agent_statuses: list[dict[str, Any]] = Field(default_factory=list)
    itinerary: dict[str, Any] | None = None
    text_input_enabled: bool = True


# =============================================================================
# In-memory Session View Tracking
# =============================================================================


@dataclass
class SessionViewState:
    """Session UI view state assembled from orchestrator responses."""

    session_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    pending_actions: list[dict[str, Any]] = field(default_factory=list)
    text_input_enabled: bool = True
    phase: str | None = None
    checkpoint: str | None = None


class _WorkflowStateStoreAdapter:
    """Adapter that exposes WorkflowStoreProtocol via get_state()."""

    def __init__(self, workflow_store: Any):
        self._workflow_store = workflow_store

    async def get_state(self, session_id: str) -> WorkflowStateData | None:
        state = await self._workflow_store.get_by_session(session_id)
        if state is None:
            return None
        return WorkflowStateData(
            session_id=state.session_id,
            consultation_id=state.consultation_id,
            phase=state.phase.value,
            checkpoint=state.checkpoint,
            current_step=state.current_step,
            itinerary_id=state.itinerary_id,
            current_job_id=state.current_job_id,
            workflow_version=state.workflow_version,
            agent_context_ids={name: value.to_dict() for name, value in state.agent_context_ids.items()},
            created_at=state.created_at,
            updated_at=state.updated_at,
            etag=state.etag,
        )


def _append_session_message(view: SessionViewState, role: str, sender: str, content: str) -> None:
    if not content:
        return
    view.messages.append(
        {
            "id": str(uuid.uuid4()),
            "role": role,
            "sender": sender,
            "content": content,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def _parse_ui_state(payload: dict[str, Any] | None) -> tuple[list[dict[str, Any]], bool]:
    if not isinstance(payload, dict):
        return [], True

    actions: list[dict[str, Any]] = []
    text_input_enabled = True

    def _collect(raw_actions: Any) -> None:
        if not isinstance(raw_actions, list):
            return
        for action in raw_actions:
            if not isinstance(action, dict):
                continue
            event = action.get("event")
            label = action.get("label")
            if isinstance(event, dict) and isinstance(label, str):
                action_payload = {"label": label, "event": event}
                if isinstance(action.get("description"), str):
                    action_payload["description"] = action["description"]
                actions.append(action_payload)

    response = payload.get("response")
    if isinstance(response, dict):
        ui = response.get("ui")
        if isinstance(ui, dict):
            _collect(ui.get("actions"))
            text_input_enabled = bool(ui.get("text_input", True))

    error = payload.get("error")
    if isinstance(error, dict):
        retry_action = error.get("retry_action")
        if isinstance(retry_action, dict):
            _collect([retry_action])
        _collect(error.get("fallback_actions"))

    ui_payload = payload.get("ui")
    if isinstance(ui_payload, dict):
        _collect(ui_payload.get("actions"))
        text_input_enabled = bool(ui_payload.get("text_input", text_input_enabled))

    return actions, text_input_enabled


def _parse_phase_status(payload: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if not isinstance(payload, dict):
        return None, None

    phase: str | None = None
    checkpoint: str | None = None

    response = payload.get("response")
    if isinstance(response, dict):
        status = response.get("status")
        if isinstance(status, dict):
            if isinstance(status.get("phase"), str):
                phase = status["phase"]
            if "checkpoint" in status:
                checkpoint = status.get("checkpoint") if isinstance(status.get("checkpoint"), str) else None
            elif phase is not None:
                checkpoint = None

        response_data = response.get("data")
        if phase is None and isinstance(response_data, dict) and isinstance(response_data.get("phase"), str):
            phase = response_data["phase"]

    status_payload = payload.get("status")
    if isinstance(status_payload, dict):
        if phase is None and isinstance(status_payload.get("phase"), str):
            phase = status_payload["phase"]
        if "checkpoint" in status_payload:
            checkpoint = (
                status_payload.get("checkpoint")
                if isinstance(status_payload.get("checkpoint"), str)
                else None
            )
        elif phase is not None and checkpoint is None:
            checkpoint = None

    return phase, checkpoint


def _extract_consultation_id(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    response = payload.get("response")
    if not isinstance(response, dict):
        return None
    consultation_id = response.get("consultation_id")
    return consultation_id if isinstance(consultation_id, str) else None


def _safe_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        try:
            data = value.to_dict()
            if isinstance(data, dict):
                return data
        except Exception:
            return None
    return None


def _get_or_create_session_view(session_id: str) -> SessionViewState:
    views: dict[str, SessionViewState] = app.state.session_views
    view = views.get(session_id)
    if view is None:
        view = SessionViewState(session_id=session_id)
        views[session_id] = view
    return view


def _update_view_from_payload(view: SessionViewState, payload: dict[str, Any] | None) -> None:
    actions, text_input_enabled = _parse_ui_state(payload)
    view.pending_actions = actions
    view.text_input_enabled = text_input_enabled

    phase, checkpoint = _parse_phase_status(payload)
    if phase is not None:
        view.phase = phase
    if checkpoint is not None:
        view.checkpoint = checkpoint


async def _run_agent_interaction(
    *,
    session_id: str,
    message: str,
    event_payload: dict[str, Any] | None = None,
    record_user_message: bool = True,
) -> tuple[str, dict[str, Any] | None, str | None]:
    from src.orchestrator.executor import OrchestratorAgent

    agent: OrchestratorAgent = app.state.agent
    view = _get_or_create_session_view(session_id)

    if record_user_message:
        _append_session_message(view, role="user", sender="You", content=message)

    final_message = ""
    final_data: dict[str, Any] | None = None
    consultation_id: str | None = None

    if event_payload is None:
        stream = agent._process_intelligent_request(
            message=message,
            session_id=session_id,
        )
    else:
        stream = agent._process_intelligent_request(
            message=message,
            session_id=session_id,
            event=event_payload,
        )

    async for chunk in stream:
        content = chunk.get("content")
        if isinstance(content, str) and content:
            final_message = content

        data = chunk.get("data")
        if isinstance(data, dict):
            final_data = data
            consultation_id = _extract_consultation_id(data) or consultation_id

    _append_session_message(
        view,
        role="assistant",
        sender="Orchestrator",
        content=final_message,
    )
    _update_view_from_payload(view, final_data)

    return final_message, final_data, consultation_id


async def _build_agent_statuses(session_id: str) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []

    workflow_store = getattr(app.state, "workflow_store", None)
    if workflow_store is not None:
        state = await workflow_store.get_by_session(session_id)
        if state is not None and state.current_job_id:
            discovery_store = getattr(app.state, "discovery_job_store", None)
            if discovery_store is not None:
                job = await discovery_store.get_job(
                    state.current_job_id, state.consultation_id or ""
                )
                if job is not None and job.agent_progress:
                    for agent_name, progress in job.agent_progress.items():
                        statuses.append(
                            {
                                "agent_id": agent_name,
                                "status": progress.status,
                                "message": progress.message,
                            }
                        )

    if statuses:
        return statuses

    registry_api = getattr(app.state, "agent_registry_api", None)
    if registry_api is not None:
        for agent in await registry_api.list_agents():
            statuses.append(
                {
                    "agent_id": agent.get("agentId"),
                    "status": agent.get("status"),
                    "type": agent.get("type"),
                }
            )
    return statuses


async def _build_session_response(session_id: str) -> SessionStateResponse:
    workflow_store = getattr(app.state, "workflow_store", None)
    state = None
    if workflow_store is not None:
        state = await workflow_store.get_by_session(session_id)

    view = app.state.session_views.get(session_id)
    if state is None and view is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    phase = state.phase.value if state is not None else (view.phase if view else None)
    checkpoint = state.checkpoint if state is not None else (view.checkpoint if view else None)
    itinerary = _safe_dict(state.itinerary_draft if state is not None else None)

    messages = view.messages if view else []
    pending_actions = view.pending_actions if view else []
    text_input_enabled = view.text_input_enabled if view is not None else True

    return SessionStateResponse(
        session_id=session_id,
        phase=phase,
        checkpoint=checkpoint,
        messages=[SessionMessage(**message) for message in messages],
        pending_actions=[PendingAction(**action) for action in pending_actions],
        agent_statuses=await _build_agent_statuses(session_id),
        itinerary=itinerary,
        text_input_enabled=text_input_enabled,
    )


def _build_orchestrator_url() -> str:
    host = os.environ.get("SERVER_URL", "localhost")
    if host.startswith("http://") or host.startswith("https://"):
        base = host.rstrip("/")
    else:
        base = f"http://{host}"
    port = os.environ.get("ORCHESTRATOR_AGENT_PORT") or os.environ.get(
        "ORCHESTRATOR_PORT", "10000"
    )
    return f"{base}:{port}"


# =============================================================================
# FastAPI Application
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - startup and shutdown."""
    logger.info("Starting FastAPI Direct API for orchestrator...")

    from src.orchestrator.executor import OrchestratorExecutor
    from src.orchestrator.storage.discovery_jobs import InMemoryDiscoveryJobStore

    app.state.discovery_job_store = InMemoryDiscoveryJobStore()
    app.state.session_views = {}

    httpx_client = httpx.AsyncClient(timeout=30)
    executor = OrchestratorExecutor(
        httpx_client=httpx_client,
        discovery_job_store=app.state.discovery_job_store,
    )

    app.state.executor = executor
    app.state.agent = executor.agent
    app.state.httpx_client = httpx_client
    app.state.workflow_store = executor.workflow_store
    app.state.workflow_state_store = _WorkflowStateStoreAdapter(executor.workflow_store)

    app.state.agent_registry_api = AgentRegistryApi(
        http_client=httpx_client,
        orchestrator_url=_build_orchestrator_url(),
        builtin_registry=executor.agent_registry,
    )
    await app.state.agent_registry_api.start_health_checks(interval_seconds=10)

    discovery_router = create_discovery_router(
        workflow_state_store=app.state.workflow_state_store,
        discovery_job_store=app.state.discovery_job_store,
    )
    app.include_router(discovery_router)

    logger.info("FastAPI Direct API initialized")

    try:
        yield
    finally:
        logger.info("Shutting down FastAPI Direct API...")
        if getattr(app.state, "agent_registry_api", None) is not None:
            stop_health_checks = getattr(app.state.agent_registry_api, "stop_health_checks", None)
            if callable(stop_health_checks):
                maybe_awaitable = stop_health_checks()
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable
        await app.state.httpx_client.aclose()


app = FastAPI(
    title="Travel Planner Orchestrator API",
    description="Direct API for the travel planner orchestrator (Entry Point 2)",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Health Check
# =============================================================================


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "orchestrator-api"}


# =============================================================================
# Chat Endpoints
# =============================================================================


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Synchronous chat endpoint."""
    session_id = request.session_id or str(uuid.uuid4())
    logger.info(
        "POST /chat: session_id=%s, message_preview=%s...",
        session_id,
        request.message[:50] if len(request.message) > 50 else request.message,
    )

    final_message, final_data, consultation_id = await _run_agent_interaction(
        session_id=session_id,
        message=request.message,
    )

    return ChatResponse(
        message=final_message,
        session_id=session_id,
        consultation_id=consultation_id,
        data=final_data,
    )


@app.get("/chat/stream")
async def chat_stream(
    message: str = Query(..., description="The user's message to process"),
    session_id: str = Query(
        default=None,
        description="Session identifier. If not provided, a new session is created.",
    ),
) -> StreamingResponse:
    """SSE streaming endpoint for real-time updates."""
    from src.orchestrator.executor import OrchestratorAgent

    actual_session_id = session_id or str(uuid.uuid4())
    logger.info(
        "GET /chat/stream: session_id=%s, message_preview=%s...",
        actual_session_id,
        message[:50] if len(message) > 50 else message,
    )

    view = _get_or_create_session_view(actual_session_id)
    _append_session_message(view, role="user", sender="You", content=message)

    async def event_generator() -> AsyncGenerator[str, None]:
        agent: OrchestratorAgent = app.state.agent
        consultation_id: str | None = None
        final_message = ""
        final_data: dict[str, Any] | None = None

        try:
            async for chunk in agent._process_intelligent_request(
                message=message,
                session_id=actual_session_id,
            ):
                content = chunk.get("content")
                if isinstance(content, str) and content:
                    final_message = content

                data = chunk.get("data")
                if isinstance(data, dict):
                    final_data = data
                    consultation_id = _extract_consultation_id(data) or consultation_id

                stream_chunk = ChatStreamChunk(
                    message=chunk.get("content", ""),
                    session_id=actual_session_id,
                    consultation_id=consultation_id,
                    is_complete=chunk.get("is_task_complete", False),
                    require_user_input=chunk.get("require_user_input", False),
                    data=data if isinstance(data, dict) else None,
                )
                yield f"data: {stream_chunk.model_dump_json()}\n\n"
        except Exception as exc:
            logger.error(
                "Stream processing failed for session_id=%s: %s",
                actual_session_id,
                exc,
                exc_info=True,
            )
            final_message = (
                "I'm having trouble connecting to the trip planner. Please try again."
            )
            final_data = {
                "error": {
                    "code": "STREAM_ERROR",
                    "message": str(exc),
                }
            }
            stream_chunk = ChatStreamChunk(
                message=final_message,
                session_id=actual_session_id,
                consultation_id=consultation_id,
                is_complete=True,
                require_user_input=True,
                data=final_data,
            )
            yield f"data: {stream_chunk.model_dump_json()}\n\n"
        finally:
            _append_session_message(
                view,
                role="assistant",
                sender="Orchestrator",
                content=final_message,
            )
            _update_view_from_payload(view, final_data)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =============================================================================
# Session Endpoints
# =============================================================================


@app.get("/sessions/{session_id}", response_model=SessionStateResponse)
async def get_session_state(session_id: str) -> SessionStateResponse:
    """Return full session state for frontend polling."""
    return await _build_session_response(session_id)


@app.post("/sessions/{session_id}/event", response_model=SessionStateResponse)
async def send_workflow_event(
    session_id: str,
    request: SessionEventRequest,
) -> SessionStateResponse:
    """Send a structured workflow event to the orchestrator."""
    if request.type == "free_text" and not request.message:
        raise HTTPException(
            status_code=400,
            detail="message is required when type=free_text",
        )

    event_payload: dict[str, Any] = {
        "type": request.type,
    }
    if request.checkpoint_id is not None:
        event_payload["checkpoint_id"] = request.checkpoint_id
    if request.booking is not None:
        event_payload["booking"] = request.booking
    if request.agent_id is not None:
        event_payload["agent_id"] = request.agent_id
        event_payload["agent"] = request.agent_id
    elif request.agent is not None:
        event_payload["agent"] = request.agent

    interaction_message = request.message or request.type.replace("_", " ")
    record_user_message = bool(request.message) or request.type == "free_text"

    await _run_agent_interaction(
        session_id=session_id,
        message=interaction_message,
        event_payload=event_payload,
        record_user_message=record_user_message,
    )
    return await _build_session_response(session_id)


# =============================================================================
# Agent Registry Endpoints
# =============================================================================


@app.get("/agents")
async def list_agents() -> list[dict[str, Any]]:
    """List all agents known to the orchestrator API."""
    return await app.state.agent_registry_api.list_agents()


@app.get("/agents/{agent_id}/card")
async def get_agent_card(agent_id: str) -> dict[str, Any]:
    """Fetch full agent card details."""
    try:
        return await app.state.agent_registry_api.get_agent_card(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/agents")
async def add_agent(request: AddAgentRequest) -> dict[str, Any]:
    """Register a custom agent after validating its agent card."""
    try:
        return await app.state.agent_registry_api.add_custom_agent(
            name=request.name,
            url=request.url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/agents/{agent_id}")
async def remove_agent(agent_id: str) -> dict[str, Any]:
    """Remove a custom agent."""
    try:
        deleted = await app.state.agent_registry_api.remove_custom_agent(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": deleted, "agent_id": agent_id}
