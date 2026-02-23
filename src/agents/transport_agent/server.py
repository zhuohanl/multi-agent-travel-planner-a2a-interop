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
from .agent_executor import AgentFrameworkTransportAgentExecutor

logger = logging.getLogger(__name__)

AGENT_NAME = 'Transport Agent'
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
    """A2A Server wrapper for the Transport Agent."""

    def build_agent_executor(self) -> AgentFrameworkTransportAgentExecutor:
        return AgentFrameworkTransportAgentExecutor()

    def build_agent_card(self) -> AgentCard:
        """Returns the Agent Card for Transport Search."""
        capabilities = AgentCapabilities(streaming=True)

        skill_ = AgentSkill(
            id='search_transport',
            name='Search Transport Options',
            description=(
                'Finds flights, trains, buses, and local transit options between cities. '
                'Returns intercity transport, airport/station transfers, and local passes '
                'with pricing and booking links.'
            ),
            tags=['transport-search', 'flights', 'trains', 'transit', 'travel-planning', 'agent-framework'],
            examples=[
                'Find flights from NYC to Tokyo for November 10.',
                'What are the train options from Tokyo to Kyoto?',
                'How do I get from Narita Airport to Shinjuku?',
                'What local transit passes are available in Tokyo?',
            ],
        )

        return AgentCard(
            name=AGENT_NAME,
            description=(
                'Searches for transport options including flights, trains, buses, '
                'airport transfers, and local transit passes. Returns structured results '
                'with pricing and booking information.'
            ),
            url=f'http://{self.host}:{self.port}/',
            version=AGENT_VERSION,
            defaultInputModes=['text'],
            defaultOutputModes=['text'],
            capabilities=capabilities,
            skills=[skill_],
        )


host = os.environ["SERVER_URL"]
port = int(os.environ["TRANSPORT_AGENT_PORT"])


@asynccontextmanager
async def lifespan(app: Starlette):
    """Manage application lifespan - startup and shutdown"""
    logger.info("Starting Transport Agent with A2A integration...")
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
