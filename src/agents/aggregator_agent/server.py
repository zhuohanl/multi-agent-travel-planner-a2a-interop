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
from .agent_executor import AgentFrameworkAggregatorAgentExecutor

logger = logging.getLogger(__name__)

AGENT_NAME = 'Aggregator Agent'
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
    """A2A Server wrapper for the Aggregator Agent."""

    def build_agent_executor(self) -> AgentFrameworkAggregatorAgentExecutor:
        return AgentFrameworkAggregatorAgentExecutor()

    def build_agent_card(self) -> AgentCard:
        """Returns the Agent Card for Aggregator."""
        capabilities = AgentCapabilities(streaming=True)

        skill_ = AgentSkill(
            id='aggregate_discovery',
            name='Aggregate Discovery Results',
            description=(
                'Combines raw discovery outputs from multiple agents (POI, Stay, Transport, '
                'Events, Dining) into a unified structure. Calculates totals and merges results '
                'without validating against TripSpec.'
            ),
            tags=['aggregation', 'discovery', 'planning', 'travel-planning', 'agent-framework'],
            examples=[
                'Combine POI and Stay discovery results.',
                'Aggregate all discovery outputs for Tokyo trip.',
                'Merge transport and events findings.',
            ],
        )

        return AgentCard(
            name=AGENT_NAME,
            description=(
                'Combines discovery results from multiple agents into a unified DiscoveryResults '
                'structure. Does not validate against TripSpec - that is the Validator Agent\'s role.'
            ),
            url=f'http://{self.host}:{self.port}/',
            version=AGENT_VERSION,
            defaultInputModes=['text'],
            defaultOutputModes=['text'],
            capabilities=capabilities,
            skills=[skill_],
        )


host = os.environ["SERVER_URL"]
port = int(os.environ["AGGREGATOR_AGENT_PORT"])


@asynccontextmanager
async def lifespan(app: Starlette):
    """Manage application lifespan - startup and shutdown"""
    logger.info("Starting Aggregator Agent with A2A integration...")
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
