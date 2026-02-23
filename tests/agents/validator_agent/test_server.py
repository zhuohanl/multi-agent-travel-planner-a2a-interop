"""Unit tests for Validator Agent server."""

import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.testclient import TestClient
from a2a.types import AgentCard


@pytest.fixture(autouse=True)
def mock_environment():
    """Set required environment variables for all tests."""
    env_vars = {
        "SERVER_URL": "localhost",
        "VALIDATOR_AGENT_PORT": "10016",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_DEPLOYMENT_NAME": "test-deployment",
        "AZURE_OPENAI_API_VERSION": "2024-02-01",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


class TestHealthCheck:
    """Tests for the health_check endpoint function."""

    async def test_health_check_returns_json_response(self, mock_environment):
        """Test that health_check returns a JSONResponse."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.validator_agent.server import health_check

        mock_request = MagicMock(spec=Request)

        response = await health_check(mock_request)

        assert isinstance(response, JSONResponse)

    async def test_health_check_returns_correct_structure(self, mock_environment):
        """Test that health_check returns correct JSON structure."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.validator_agent.server import health_check

        mock_request = MagicMock(spec=Request)

        response = await health_check(mock_request)
        data = json.loads(response.body)

        assert data["status"] == "healthy"
        assert data["agent_name"] == "Validator Agent"
        assert data["version"] == "1.0.0"

    async def test_health_check_status_code(self, mock_environment):
        """Test that health_check returns 200 status code."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.validator_agent.server import health_check

        mock_request = MagicMock(spec=Request)

        response = await health_check(mock_request)

        assert response.status_code == 200


class TestModuleLevelConfig:
    """Tests for module-level configuration."""

    def test_host_from_environment(self, mock_environment):
        """Test that host is read from SERVER_URL environment variable."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.validator_agent.server import host
        assert host == "localhost"

    def test_port_from_environment(self, mock_environment):
        """Test that port is read from VALIDATOR_AGENT_PORT environment variable."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.validator_agent.server import port
        assert port == 10016

    def test_port_is_integer(self, mock_environment):
        """Test that port is converted to integer."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.validator_agent.server import port
        assert isinstance(port, int)


class TestA2AServer:
    """Tests for the A2AServer class."""

    @pytest.fixture
    def mock_httpx_client(self):
        """Create a mock httpx AsyncClient."""
        client = AsyncMock()
        client.aclose = AsyncMock()
        return client

    @pytest.fixture
    def a2a_server_class(self, mock_environment):
        """Get the A2AServer class with mocked environment."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.validator_agent.server import A2AServer
            A2AServer._task_store = None
            A2AServer._config_store = None
            A2AServer._agent_executor = None
            yield A2AServer
            A2AServer._task_store = None
            A2AServer._config_store = None
            A2AServer._agent_executor = None

    def test_build_agent_executor_returns_executor(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that build_agent_executor returns an AgentFrameworkValidatorAgentExecutor."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.validator_agent.agent_executor import (
                AgentFrameworkValidatorAgentExecutor,
            )

            server = a2a_server_class(mock_httpx_client, host="localhost", port=10016)
            executor = server.build_agent_executor()

            assert isinstance(executor, AgentFrameworkValidatorAgentExecutor)

    def test_build_agent_card_returns_agent_card(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that build_agent_card returns an AgentCard."""
        with patch.dict(os.environ, mock_environment):
            server = a2a_server_class(mock_httpx_client, host="localhost", port=10016)
            card = server.build_agent_card()

            assert isinstance(card, AgentCard)

    def test_build_agent_card_has_correct_name(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that agent card has the correct name."""
        with patch.dict(os.environ, mock_environment):
            server = a2a_server_class(mock_httpx_client, host="localhost", port=10016)
            card = server.build_agent_card()

            assert card.name == "Validator Agent"

    def test_build_agent_card_has_correct_version(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that agent card has the correct version."""
        with patch.dict(os.environ, mock_environment):
            server = a2a_server_class(mock_httpx_client, host="localhost", port=10016)
            card = server.build_agent_card()

            assert card.version == "1.0.0"

    def test_build_agent_card_has_correct_url(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that agent card has the correct URL based on host and port."""
        with patch.dict(os.environ, mock_environment):
            a2a_server_class._task_store = None
            a2a_server_class._config_store = None
            a2a_server_class._agent_executor = None

            server = a2a_server_class(mock_httpx_client, host="testhost", port=9999)
            card = server.build_agent_card()

            assert card.url == "http://testhost:9999/"

    def test_build_agent_card_has_streaming_capability(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that agent card has streaming capability enabled."""
        with patch.dict(os.environ, mock_environment):
            server = a2a_server_class(mock_httpx_client, host="localhost", port=10016)
            card = server.build_agent_card()

            assert card.capabilities is not None
            assert card.capabilities.streaming is True

    def test_build_agent_card_has_skill(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that agent card has at least one skill."""
        with patch.dict(os.environ, mock_environment):
            server = a2a_server_class(mock_httpx_client, host="localhost", port=10016)
            card = server.build_agent_card()

            assert card.skills is not None
            assert len(card.skills) >= 1

    def test_build_agent_card_skill_has_correct_id(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that the skill has the correct ID."""
        with patch.dict(os.environ, mock_environment):
            server = a2a_server_class(mock_httpx_client, host="localhost", port=10016)
            card = server.build_agent_card()
            skill = card.skills[0]

            assert skill.id == "validate_itinerary"

    def test_build_agent_card_skill_has_correct_name(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that the skill has the correct name."""
        with patch.dict(os.environ, mock_environment):
            server = a2a_server_class(mock_httpx_client, host="localhost", port=10016)
            card = server.build_agent_card()
            skill = card.skills[0]

            assert skill.name == "Validate Itinerary"

    def test_build_agent_card_skill_has_tags(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that the skill has appropriate tags."""
        with patch.dict(os.environ, mock_environment):
            server = a2a_server_class(mock_httpx_client, host="localhost", port=10016)
            card = server.build_agent_card()
            skill = card.skills[0]

            assert "validation" in skill.tags
            assert "planning" in skill.tags

    def test_build_agent_card_skill_has_examples(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that the skill has usage examples."""
        with patch.dict(os.environ, mock_environment):
            server = a2a_server_class(mock_httpx_client, host="localhost", port=10016)
            card = server.build_agent_card()
            skill = card.skills[0]

            assert skill.examples is not None
            assert len(skill.examples) > 0

    def test_build_agent_card_default_input_modes(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that agent card has correct default input modes."""
        with patch.dict(os.environ, mock_environment):
            server = a2a_server_class(mock_httpx_client, host="localhost", port=10016)
            card = server.build_agent_card()

            assert "text" in card.default_input_modes

    def test_build_agent_card_default_output_modes(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that agent card has correct default output modes."""
        with patch.dict(os.environ, mock_environment):
            server = a2a_server_class(mock_httpx_client, host="localhost", port=10016)
            card = server.build_agent_card()

            assert "text" in card.default_output_modes

    def test_server_initializes_shared_state(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that server initializes shared state on first instantiation."""
        with patch.dict(os.environ, mock_environment):
            server = a2a_server_class(mock_httpx_client, host="localhost", port=10016)

            assert a2a_server_class._task_store is not None
            assert a2a_server_class._config_store is not None
            assert a2a_server_class._agent_executor is not None

    def test_server_reuses_shared_state(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that second server instance reuses shared state."""
        with patch.dict(os.environ, mock_environment):
            server1 = a2a_server_class(mock_httpx_client, host="localhost", port=10016)
            task_store_1 = a2a_server_class._task_store

            server2 = a2a_server_class(mock_httpx_client, host="localhost", port=10016)
            task_store_2 = a2a_server_class._task_store

            assert task_store_1 is task_store_2


class TestLifespan:
    """Tests for the lifespan context manager."""

    @pytest.fixture
    def a2a_server_class(self, mock_environment):
        """Get the A2AServer class with mocked environment."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.validator_agent.server import A2AServer
            A2AServer._task_store = None
            A2AServer._config_store = None
            A2AServer._agent_executor = None
            yield A2AServer
            A2AServer._task_store = None
            A2AServer._config_store = None
            A2AServer._agent_executor = None

    async def test_lifespan_sets_app_state(self, mock_environment, a2a_server_class):
        """Test that lifespan context manager sets app state correctly."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.validator_agent.server import lifespan

            mock_app = MagicMock()
            mock_app.router = MagicMock()
            mock_app.router.routes = []
            mock_app.state = MagicMock()

            async with lifespan(mock_app):
                assert hasattr(mock_app.state, "httpx_client")
                assert hasattr(mock_app.state, "a2a_server")

    async def test_lifespan_closes_httpx_client_on_exit(self, mock_environment, a2a_server_class):
        """Test that lifespan closes httpx client on context exit."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.validator_agent.server import lifespan

            mock_app = MagicMock()
            mock_app.router = MagicMock()
            mock_app.router.routes = []
            mock_app.state = MagicMock()

            async with lifespan(mock_app):
                pass

            assert True


class TestStarletteApp:
    """Tests for the Starlette application."""

    def test_app_has_health_route(self, mock_environment):
        """Test that the app has a health check route."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.validator_agent.server import app

        routes = [route.path for route in app.routes]
        assert "/health" in routes

    def test_health_endpoint_with_test_client(self, mock_environment):
        """Test health endpoint using Starlette TestClient."""
        with patch.dict(os.environ, mock_environment):
            import src.agents.validator_agent.server as server_module

            server_module.A2AServer._task_store = None
            server_module.A2AServer._config_store = None
            server_module.A2AServer._agent_executor = None

            with TestClient(server_module.app) as client:
                response = client.get("/health")

                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "healthy"
                assert data["agent_name"] == "Validator Agent"
                assert data["version"] == "1.0.0"

    def test_app_has_lifespan_handler(self, mock_environment):
        """Test that the app has a lifespan handler configured."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.validator_agent.server import app

        assert app is not None


class TestAgentCardDescription:
    """Tests for agent card description content."""

    @pytest.fixture
    def mock_httpx_client(self):
        """Create a mock httpx AsyncClient."""
        return AsyncMock()

    @pytest.fixture
    def a2a_server_class(self, mock_environment):
        """Get the A2AServer class with mocked environment."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.validator_agent.server import A2AServer
            A2AServer._task_store = None
            A2AServer._config_store = None
            A2AServer._agent_executor = None
            yield A2AServer
            A2AServer._task_store = None
            A2AServer._config_store = None
            A2AServer._agent_executor = None

    def test_agent_card_description_mentions_validation(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that agent card description mentions validation."""
        with patch.dict(os.environ, mock_environment):
            server = a2a_server_class(mock_httpx_client, host="localhost", port=10016)
            card = server.build_agent_card()

            assert "validat" in card.description.lower()

    def test_agent_card_description_mentions_tripspec(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that agent card description mentions TripSpec."""
        with patch.dict(os.environ, mock_environment):
            server = a2a_server_class(mock_httpx_client, host="localhost", port=10016)
            card = server.build_agent_card()

            assert "tripspec" in card.description.lower()

    def test_agent_card_description_mentions_budget(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that agent card description mentions budget."""
        with patch.dict(os.environ, mock_environment):
            server = a2a_server_class(mock_httpx_client, host="localhost", port=10016)
            card = server.build_agent_card()

            assert "budget" in card.description.lower()

    def test_skill_description_mentions_checks(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that skill description mentions validation checks."""
        with patch.dict(os.environ, mock_environment):
            server = a2a_server_class(mock_httpx_client, host="localhost", port=10016)
            card = server.build_agent_card()
            skill = card.skills[0]

            description_lower = skill.description.lower()
            checks_mentioned = sum(1 for check in ["budget", "date", "constraint"]
                                  if check in description_lower)
            assert checks_mentioned >= 2

    def test_skill_examples_mention_validation(
        self, mock_httpx_client, a2a_server_class, mock_environment
    ):
        """Test that skill examples mention validation concepts."""
        with patch.dict(os.environ, mock_environment):
            server = a2a_server_class(mock_httpx_client, host="localhost", port=10016)
            card = server.build_agent_card()
            skill = card.skills[0]
            examples_text = " ".join(skill.examples).lower()

            assert "validat" in examples_text or "check" in examples_text or "verify" in examples_text
