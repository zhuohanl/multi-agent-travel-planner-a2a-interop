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
from .agent_executor import AgentFrameworkStayAgentExecutor

logger = logging.getLogger(__name__)

AGENT_NAME = 'Stay Agent'
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
    """A2A Server wrapper for the Stay Agent."""

    def build_agent_executor(self) -> AgentFrameworkStayAgentExecutor:
        return AgentFrameworkStayAgentExecutor()

    def build_agent_card(self) -> AgentCard:
        """Returns the Agent Card for Stay Search."""
        capabilities = AgentCapabilities(streaming=True)

        skill_ = AgentSkill(
            id='search_stays',
            name='Search Accommodations',
            description=(
                'Finds recommended neighborhoods and 4-6 accommodation options at a destination '
                'based on traveler budget, interests, and seasonality. Returns neighborhood details '
                'with reasons, and stay options with pricing and source links.'
            ),
            tags=['stay-search', 'accommodations', 'hotels', 'travel-planning', 'agent-framework'],
            examples=[
                'Find budget hotels in Tokyo for art lovers.',
                'What are the best neighborhoods in Paris for families?',
                'Suggest mid-range stays in Rome near cultural sites.',
                'Find accommodations in Singapore for food enthusiasts.',
            ],
        )

        return AgentCard(
            name=AGENT_NAME,
            description=(
                'Searches for recommended neighborhoods and accommodations that match the destination, '
                'budget, and traveler interests. Returns structured stay results with neighborhoods, '
                'pricing, and source information.'
            ),
            url=f'http://{self.host}:{self.port}/',
            version=AGENT_VERSION,
            defaultInputModes=['text'],
            defaultOutputModes=['text'],
            capabilities=capabilities,
            skills=[skill_],
        )


host = os.environ["SERVER_URL"]
port = int(os.environ["STAY_AGENT_PORT"])


@asynccontextmanager
async def lifespan(app: Starlette):
    """Manage application lifespan - startup and shutdown"""
    logger.info("Starting Stay Agent with A2A integration...")
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
