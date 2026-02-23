"""
OrchestratorServer: A2A Protocol server for the orchestrator agent.

This is Entry Point 1 (A2A Protocol) as described in the design doc.
The orchestrator exposes an A2A server interface, allowing other agents
or A2A clients to communicate with it using the same protocol as other agents.

Architecture:
- Extends BaseA2AServer to reuse A2A protocol wiring
- Delegates to OrchestratorExecutor for request processing
- Provides AgentCard declaring orchestrator capabilities
- AgentCard is served at /.well-known/agent.json for A2A discovery
"""

import logging
import os
from contextlib import asynccontextmanager

import httpx
from a2a.types import AgentCard
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from src.orchestrator.agent_card import (
    AGENT_NAME,
    AGENT_VERSION,
    build_orchestrator_agent_card,
)
from src.shared.a2a.base_server import BaseA2AServer
from src.shared.models import HealthResponse, HealthStatus

logger = logging.getLogger(__name__)


async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for monitoring server status."""
    response = HealthResponse(
        status=HealthStatus.HEALTHY,
        agent_name=AGENT_NAME,
        version=AGENT_VERSION,
    )
    return JSONResponse(response.model_dump())


class OrchestratorServer(BaseA2AServer):
    """A2A Server for the Travel Planner Orchestrator.

    This server implements Entry Point 1 (A2A Protocol) from the design doc.
    It receives requests from the frontend or other A2A-compliant clients
    and delegates processing to the OrchestratorExecutor.

    The orchestrator is the central brain of the multi-agent travel planner,
    responsible for:
    1. A2A Client: Establishing connections with downstream agents
    2. LLM-Based Router: Routing user requests to appropriate tools/workflows
    """

    def build_agent_executor(self):
        """Build the orchestrator executor.

        Note: The full OrchestratorExecutor implementation is in ORCH-021.
        This ticket (ORCH-020) establishes the server infrastructure.
        """
        # Import here to avoid circular imports and allow for placeholder
        from src.orchestrator.executor import OrchestratorExecutor

        return OrchestratorExecutor(httpx_client=self.httpx_client)

    def build_agent_card(self) -> AgentCard:
        """Returns the Agent Card for the Orchestrator.

        The AgentCard is served at /.well-known/agent.json and declares the
        orchestrator's capabilities per the A2A protocol. Skills map to the
        7 tools available to the orchestrator (per design doc).

        See src/orchestrator/agent_card.py for full skill definitions.
        """
        return build_orchestrator_agent_card(self.host, self.port)


# Module-level configuration
# Use environment variables with defaults for flexibility
host = os.environ.get("SERVER_URL", "localhost")
port = int(
    os.environ.get("ORCHESTRATOR_AGENT_PORT")
    or os.environ.get("ORCHESTRATOR_PORT", "10000")
)


@asynccontextmanager
async def lifespan(app: Starlette):
    """Manage application lifespan - startup and shutdown."""
    logger.info("Starting Travel Planner Orchestrator with A2A integration...")
    httpx_client = httpx.AsyncClient(timeout=30)
    orchestrator_server = OrchestratorServer(httpx_client, host=host, port=port)

    app.router.routes.extend(list(orchestrator_server.a2a_app.routes()))

    app.state.httpx_client = httpx_client
    app.state.orchestrator_server = orchestrator_server
    logger.info(
        "Orchestrator server initialized on %s:%s",
        host,
        port,
    )

    try:
        yield
    finally:
        logger.info("Shutting down orchestrator server...")
        await httpx_client.aclose()
        logger.info("HTTP client closed")


# Create the Starlette app
app = Starlette(
    routes=[Route(path="/health", methods=["GET"], endpoint=health_check)],
    lifespan=lifespan,
)
