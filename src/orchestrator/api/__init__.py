"""
FastAPI Direct API entry point for the orchestrator.

This is Entry Point 2 (Direct API) as described in the design doc.
It provides a simpler interface than the A2A protocol for frontend integration.

Both entry points converge to the same _process_intelligent_request() logic
in OrchestratorAgent.

Endpoints:
    - POST /chat: Synchronous chat endpoint
    - GET /chat/stream: SSE streaming endpoint for chat
    - GET /sessions/{session_id}/discovery/stream: SSE for discovery progress
    - GET /sessions/{session_id}/discovery/status: Polling for discovery status
    - GET /sessions/{session_id}/discovery/reconnect: Reconnection endpoint

Exports:
    - app: The FastAPI application instance
    - ChatRequest: Request model for POST /chat
    - ChatResponse: Response model for POST /chat
    - ChatStreamChunk: Response model for GET /chat/stream SSE events
    - create_discovery_router: Factory for discovery router
    - JobStatusResponse: Response model for discovery status
    - ReconnectionResponse: Response model for reconnection
"""

from src.orchestrator.api.app import (
    ChatRequest,
    ChatResponse,
    ChatStreamChunk,
    app,
)
from src.orchestrator.api.discovery import (
    JobStatusResponse,
    ReconnectionResponse,
    create_discovery_router,
    discovery_router,
)

__all__ = [
    "app",
    "ChatRequest",
    "ChatResponse",
    "ChatStreamChunk",
    "create_discovery_router",
    "discovery_router",
    "JobStatusResponse",
    "ReconnectionResponse",
]
