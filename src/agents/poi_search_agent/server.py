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
from .agent_executor import AgentFrameworkPOISearchAgentExecutor

logger = logging.getLogger(__name__)

AGENT_NAME = 'POI Search Agent'
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
    """A2A Server wrapper for the POI Search Agent."""

    def build_agent_executor(self) -> AgentFrameworkPOISearchAgentExecutor:
        return AgentFrameworkPOISearchAgentExecutor()

    def build_agent_card(self) -> AgentCard:
        """Returns the Agent Card for the POI Search."""
        capabilities = AgentCapabilities(streaming=True)
        
        skill_ = AgentSkill(
            id='search_pois',
            name='Search Points of Interest',
            description=(
                'Finds 6-10 high-quality points of interest or activities for a destination '
                'based on traveler interests and seasonality. Returns concise POI details, '
                'estimated costs, and source links.'
            ),
            tags=['poi-search', 'activities', 'travel-planning', 'agent-framework'],
            examples=[
                'Find top attractions in Tokyo for art and food lovers.',
                'What are the best activities in Paris in spring?',
                'Suggest cultural sites in Rome with estimated ticket prices.',
                'Provide family-friendly things to do in Singapore.',
            ],
        )

        return AgentCard(
            name=AGENT_NAME,
            description=(
                'Searches for points of interest and activities that match the destination, '
                'interests, and season. Returns structured POI results with costs, tags, and sources.'
            ),
            url=f'http://{self.host}:{self.port}/',
            version=AGENT_VERSION,
            defaultInputModes=['text'],
            defaultOutputModes=['text'],
            capabilities=capabilities,
            skills=[skill_],
        )


# Module-level configuration
host = os.environ["SERVER_URL"]
port = int(os.environ["POI_SEARCH_AGENT_PORT"])


@asynccontextmanager
async def lifespan(app: Starlette):
    """Manage application lifespan - startup and shutdown"""
    logger.info("Starting POI Search Agent with A2A integration...")
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


# Create the Starlette app
app = Starlette(
    routes=[Route(path='/health', methods=['GET'], endpoint=health_check)],
    lifespan=lifespan,
)
