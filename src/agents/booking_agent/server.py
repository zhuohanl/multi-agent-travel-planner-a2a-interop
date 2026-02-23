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
from .agent_executor import AgentFrameworkBookingAgentExecutor

logger = logging.getLogger(__name__)

AGENT_NAME = 'Booking Agent'
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
    """A2A Server wrapper for the Booking Agent."""

    def build_agent_executor(self) -> AgentFrameworkBookingAgentExecutor:
        return AgentFrameworkBookingAgentExecutor()

    def build_agent_card(self) -> AgentCard:
        """Returns the Agent Card for Booking Agent."""
        capabilities = AgentCapabilities(streaming=True)

        skill_ = AgentSkill(
            id='manage_bookings',
            name='Manage Travel Bookings',
            description=(
                'Handles booking operations for travel items. '
                'Supports three actions: CREATE (new booking), MODIFY (change existing), '
                'CANCEL (cancel booking). Works with hotels, flights, activities, and more.'
            ),
            tags=['booking', 'travel', 'hotel', 'flight', 'activity', 'agent-framework'],
            examples=[
                'Create a hotel booking for Park Hyatt Tokyo.',
                'Modify booking book_abc123 to change check-in date.',
                'Cancel booking book_xyz789.',
            ],
        )

        return AgentCard(
            name=AGENT_NAME,
            description=(
                'Manages travel booking operations including creation, modification, '
                'and cancellation. Interfaces with booking providers to handle '
                'hotels, flights, transport passes, activities, and events.'
            ),
            url=f'http://{self.host}:{self.port}/',
            version=AGENT_VERSION,
            defaultInputModes=['text'],
            defaultOutputModes=['text'],
            capabilities=capabilities,
            skills=[skill_],
        )


host = os.environ["SERVER_URL"]
port = int(os.environ["BOOKING_AGENT_PORT"])


@asynccontextmanager
async def lifespan(app: Starlette):
    """Manage application lifespan - startup and shutdown"""
    logger.info("Starting Booking Agent with A2A integration...")
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
