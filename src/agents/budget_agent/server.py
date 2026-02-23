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
from .agent_executor import AgentFrameworkBudgetAgentExecutor

logger = logging.getLogger(__name__)

AGENT_NAME = 'Budget Agent'
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
    """A2A Server wrapper for the Budget Agent."""

    def build_agent_executor(self) -> AgentFrameworkBudgetAgentExecutor:
        return AgentFrameworkBudgetAgentExecutor()

    def build_agent_card(self) -> AgentCard:
        """Returns the Agent Card for Budget Agent."""
        capabilities = AgentCapabilities(streaming=True)

        skill_ = AgentSkill(
            id='manage_budget',
            name='Manage Travel Budget',
            description=(
                'Manages budget allocation and tracking for travel planning. '
                'Supports four modes: PROPOSE (initial allocation), VALIDATE (check constraints), '
                'TRACK (monitor spending), REALLOCATE (suggest alternatives). '
                'Idempotent: same inputs produce same outputs.'
            ),
            tags=['budget', 'planning', 'finance', 'travel-planning', 'agent-framework'],
            examples=[
                'Propose a budget allocation for a $5000 Tokyo trip.',
                'Validate if selected options fit within budget.',
                'Track spending against allocated budget.',
                'Suggest reallocation to bring trip within budget.',
            ],
        )

        return AgentCard(
            name=AGENT_NAME,
            description=(
                'Manages travel budget allocation and tracking. Supports PROPOSE, VALIDATE, '
                'TRACK, and REALLOCATE modes for comprehensive budget management. '
                'Works with TripSpec and discovery results to ensure trip stays within budget.'
            ),
            url=f'http://{self.host}:{self.port}/',
            version=AGENT_VERSION,
            defaultInputModes=['text'],
            defaultOutputModes=['text'],
            capabilities=capabilities,
            skills=[skill_],
        )


host = os.environ["SERVER_URL"]
port = int(os.environ["BUDGET_AGENT_PORT"])


@asynccontextmanager
async def lifespan(app: Starlette):
    """Manage application lifespan - startup and shutdown"""
    logger.info("Starting Budget Agent with A2A integration...")
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
