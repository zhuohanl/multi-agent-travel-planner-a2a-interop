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
from .agent_executor import AgentFrameworkIntakeClarifierAgentExecutor

logger = logging.getLogger(__name__)

AGENT_NAME = 'Intake Clarifier Agent'
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
    """A2A Server wrapper for the Intake Clarifier Agent."""

    def build_agent_executor(self) -> AgentFrameworkIntakeClarifierAgentExecutor:
        return AgentFrameworkIntakeClarifierAgentExecutor()

    def build_agent_card(self) -> AgentCard:
        """Returns the Agent Card for the Intake Clarifier."""
        capabilities = AgentCapabilities(streaming=True)
        
        skill_ = AgentSkill(
            id='generate_trip_spec',
            name='Generate Trip Spec',
            description=(
                'Gathers complete trip information through friendly, conversational questions. '
                'Collects destination, origin city, travel dates, number of travelers, budget, '
                'interests, and constraints to generate a comprehensive trip specification.'
            ),
            tags=['intake-clarifier', 'trip-spec-generation', 'travel-planning', 'agent-framework'],
            examples=[
                'I want to plan a trip to Tokyo',
                'Help me plan a vacation to Paris for 2 people',
                'I need to travel from Melbourne to Fiji next month',
                'Plan a budget trip to Japan for a week',
            ],
        )

        return AgentCard(
            name=AGENT_NAME,
            description=(
                'A conversational travel planning assistant that gathers trip requirements '
                'through friendly dialogue. Collects destination, origin, dates, travelers, '
                'budget, interests, and constraints to produce a complete trip specification.'
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
port = int(os.environ["INTAKE_CLARIFIER_AGENT_PORT"])


@asynccontextmanager
async def lifespan(app: Starlette):
    """Manage application lifespan - startup and shutdown"""
    logger.info("Starting Intake Clarifier Agent with A2A integration...")
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
