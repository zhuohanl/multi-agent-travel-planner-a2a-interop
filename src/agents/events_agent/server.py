import logging
import os
import httpx
from contextlib import asynccontextmanager
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from src.shared.a2a.base_server import BaseA2AServer
from src.shared.models import HealthResponse, HealthStatus
from .agent_executor import AgentFrameworkEventsAgentExecutor

logger = logging.getLogger(__name__)

AGENT_NAME = 'Events Agent'
AGENT_VERSION = '1.0.0'


async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for monitoring server status."""
    response = HealthResponse(
        status=HealthStatus.HEALTHY,
        agent_name=AGENT_NAME,
        version=AGENT_VERSION,
    )
    return JSONResponse(response.model_dump())


class A2AServer(BaseA2AServer):
    """A2A Server wrapper for the Events Agent."""

    def build_agent_executor(self) -> AgentFrameworkEventsAgentExecutor:
        return AgentFrameworkEventsAgentExecutor()

    def build_agent_card(self) -> AgentCard:
        """Returns the Agent Card for Events Search."""
        capabilities = AgentCapabilities(streaming=True)

        skill_ = AgentSkill(
            id='search_events',
            name='Search Events',
            description=(
                'Finds events, festivals, exhibitions, concerts, and local happenings '
                'at a destination during the travel dates. Returns event details with '
                'dates, venues, and source links.'
            ),
            tags=['events', 'festivals', 'concerts', 'exhibitions', 'travel-planning', 'agent-framework'],
            examples=[
                'Find events in Tokyo November 10-17.',
                'What festivals are happening in Kyoto this week?',
                'Search for concerts in Paris next weekend.',
                'Are there any art exhibitions in London in December?',
            ],
        )

        return AgentCard(
            name=AGENT_NAME,
            description=(
                'Searches for events, festivals, and happenings at travel destinations '
                'during specified dates. Returns structured event results with dates, '
                'venues, and source information.'
            ),
            url=f'http://{self.host}:{self.port}/',
            version=AGENT_VERSION,
            defaultInputModes=['text'],
            defaultOutputModes=['text'],
            capabilities=capabilities,
            skills=[skill_],
        )


host = os.environ["SERVER_URL"]
port = int(os.environ["EVENTS_AGENT_PORT"])


@asynccontextmanager
async def lifespan(app: Starlette):
    """Manage application lifespan - startup and shutdown"""
    logger.info("Starting Events Agent with A2A integration...")
    httpx_client = httpx.AsyncClient(timeout=30)
    a2a_server = A2AServer(httpx_client, host=host, port=port)

    app.router.routes.extend(list(a2a_server.a2a_app.routes()))

    app.state.httpx_client = httpx_client
    app.state.a2a_server = a2a_server
    logger.info("Server initialized")

    try:
        yield
    finally:
        logger.info("Shutting down server...")
        await httpx_client.aclose()
        logger.info("HTTP client closed")


app = Starlette(
    routes=[Route(path='/health', methods=['GET'], endpoint=health_check)],
    lifespan=lifespan,
)
