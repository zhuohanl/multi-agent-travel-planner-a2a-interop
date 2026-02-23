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
from .agent_executor import AgentFrameworkDiningAgentExecutor

logger = logging.getLogger(__name__)

AGENT_NAME = 'Dining Agent'
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
    """A2A Server wrapper for the Dining Agent."""

    def build_agent_executor(self) -> AgentFrameworkDiningAgentExecutor:
        return AgentFrameworkDiningAgentExecutor()

    def build_agent_card(self) -> AgentCard:
        """Returns the Agent Card for Dining Search."""
        capabilities = AgentCapabilities(streaming=True)

        skill_ = AgentSkill(
            id='search_dining',
            name='Search Dining Options',
            description=(
                'Finds restaurants, food experiences, and dining options at a destination. '
                'Supports dietary constraints (vegetarian, vegan, halal, gluten-free, etc.) '
                'and returns details including cuisine type, price range, and reservations.'
            ),
            tags=['dining', 'restaurants', 'food', 'dietary', 'travel-planning', 'agent-framework'],
            examples=[
                'Find vegetarian restaurants in Shinjuku.',
                'Search for Michelin-starred restaurants in Paris.',
                'Where can I find halal food in Singapore?',
                'Best ramen shops in Tokyo under $20.',
            ],
        )

        return AgentCard(
            name=AGENT_NAME,
            description=(
                'Searches for restaurants and food experiences at travel destinations. '
                'Handles dietary constraints and preferences, returning structured results '
                'with cuisine type, price range, and dietary accommodation information.'
            ),
            url=f'http://{self.host}:{self.port}/',
            version=AGENT_VERSION,
            defaultInputModes=['text'],
            defaultOutputModes=['text'],
            capabilities=capabilities,
            skills=[skill_],
        )


host = os.environ["SERVER_URL"]
port = int(os.environ["DINING_AGENT_PORT"])


@asynccontextmanager
async def lifespan(app: Starlette):
    """Manage application lifespan - startup and shutdown"""
    logger.info("Starting Dining Agent with A2A integration...")
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
