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
from .agent_executor import AgentFrameworkRouteAgentExecutor

logger = logging.getLogger(__name__)

AGENT_NAME = 'Route Agent'
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
    """A2A Server wrapper for the Route Agent."""

    def build_agent_executor(self) -> AgentFrameworkRouteAgentExecutor:
        return AgentFrameworkRouteAgentExecutor()

    def build_agent_card(self) -> AgentCard:
        """Returns the Agent Card for Route."""
        capabilities = AgentCapabilities(streaming=True)

        skill_ = AgentSkill(
            id='create_itinerary',
            name='Create Day-by-Day Itinerary',
            description=(
                'Creates a day-by-day walkable itinerary from aggregated discovery results. '
                'Organizes activities into logical time slots, groups nearby attractions, '
                'and includes meals, transport, and events. Covers all dates in the trip range.'
            ),
            tags=['itinerary', 'planning', 'route', 'travel-planning', 'agent-framework'],
            examples=[
                'Create a 7-day itinerary for Tokyo.',
                'Plan daily activities from discovery results.',
                'Build a walkable schedule for the trip.',
            ],
        )

        return AgentCard(
            name=AGENT_NAME,
            description=(
                'Creates day-by-day itineraries from aggregated discovery results. '
                'Optimizes for geographic proximity and logical time slots. '
                'Does not validate against TripSpec - that is the Validator Agent\'s role.'
            ),
            url=f'http://{self.host}:{self.port}/',
            version=AGENT_VERSION,
            defaultInputModes=['text'],
            defaultOutputModes=['text'],
            capabilities=capabilities,
            skills=[skill_],
        )


host = os.environ["SERVER_URL"]
port = int(os.environ["ROUTE_AGENT_PORT"])


@asynccontextmanager
async def lifespan(app: Starlette):
    """Manage application lifespan - startup and shutdown"""
    logger.info("Starting Route Agent with A2A integration...")
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
