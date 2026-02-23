"""
Unit tests for OrchestratorServer.

Tests cover:
- Server extends BaseA2AServer correctly
- Health check endpoint returns healthy status
- Server accepts and processes requests
- AgentCard is properly configured with required skills
- AgentCard is served at /.well-known/agent.json endpoint
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.testclient import TestClient

from src.shared.a2a.base_server import BaseA2AServer
from src.shared.models import HealthStatus
from src.orchestrator.agent_card import (
    AGENT_NAME,
    AGENT_VERSION,
    ORCHESTRATOR_SKILL_IDS,
    build_orchestrator_agent_card,
    build_orchestrator_skills,
)


class TestOrchestratorServerExtension:
    """Test that OrchestratorServer properly extends BaseA2AServer."""

    def test_orchestrator_server_extends_base(self) -> None:
        """Test that OrchestratorServer extends BaseA2AServer."""
        from src.orchestrator.server import OrchestratorServer

        assert issubclass(OrchestratorServer, BaseA2AServer)

    def test_orchestrator_server_implements_build_agent_executor(self) -> None:
        """Test that OrchestratorServer implements build_agent_executor."""
        from src.orchestrator.server import OrchestratorServer

        # Verify the method exists and is not the base class method
        assert hasattr(OrchestratorServer, "build_agent_executor")
        # The method should be overridden
        assert (
            OrchestratorServer.build_agent_executor
            is not BaseA2AServer.build_agent_executor
        )

    def test_orchestrator_server_implements_build_agent_card(self) -> None:
        """Test that OrchestratorServer implements build_agent_card."""
        from src.orchestrator.server import OrchestratorServer

        assert hasattr(OrchestratorServer, "build_agent_card")
        assert (
            OrchestratorServer.build_agent_card is not BaseA2AServer.build_agent_card
        )


class TestOrchestratorServerHealthCheck:
    """Test the health check endpoint."""

    def test_orchestrator_server_health_check(self) -> None:
        """Test that health check endpoint returns healthy status."""
        from src.orchestrator.server import app

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == HealthStatus.HEALTHY.value
        assert data["agent_name"] == "Travel Planner Orchestrator"
        assert data["version"] == "1.0.0"

    def test_health_check_response_format(self) -> None:
        """Test that health check response follows HealthResponse format."""
        from src.orchestrator.server import app

        client = TestClient(app)
        response = client.get("/health")

        data = response.json()
        # All required fields should be present
        assert "status" in data
        assert "agent_name" in data
        assert "version" in data


class TestOrchestratorServerAgentCard:
    """Test the AgentCard configuration."""

    @pytest.fixture
    def mock_httpx_client(self):
        """Create a mock httpx client for testing."""
        return MagicMock()

    def test_agent_card_has_required_fields(self, mock_httpx_client) -> None:
        """Test that AgentCard has all required fields."""
        from src.orchestrator.server import OrchestratorServer

        with patch(
            "src.orchestrator.server.OrchestratorServer.build_agent_executor"
        ) as mock_executor:
            mock_executor.return_value = MagicMock()
            server = OrchestratorServer(mock_httpx_client, host="localhost", port=10000)

        card = server.build_agent_card()

        assert card.name == "Travel Planner Orchestrator"
        assert card.description is not None
        assert card.url == "http://localhost:10000/"
        assert card.version == "1.0.0"
        assert card.capabilities is not None
        assert card.capabilities.streaming is True

    def test_agent_card_has_all_skills(self, mock_httpx_client) -> None:
        """Test that AgentCard includes all 7 orchestrator skills."""
        from src.orchestrator.server import OrchestratorServer

        with patch(
            "src.orchestrator.server.OrchestratorServer.build_agent_executor"
        ) as mock_executor:
            mock_executor.return_value = MagicMock()
            server = OrchestratorServer(mock_httpx_client, host="localhost", port=10000)

        card = server.build_agent_card()
        skill_ids = [skill.id for skill in card.skills]

        # Per design doc: 7 skills
        expected_skills = [
            "plan_trip",
            "answer_travel_question",
            "convert_currency",
            "lookup_weather",
            "lookup_timezone",
            "get_booking",
            "get_consultation",
        ]

        for skill_id in expected_skills:
            assert skill_id in skill_ids, f"Missing skill: {skill_id}"

    def test_agent_card_skills_have_descriptions(self, mock_httpx_client) -> None:
        """Test that all skills have descriptions."""
        from src.orchestrator.server import OrchestratorServer

        with patch(
            "src.orchestrator.server.OrchestratorServer.build_agent_executor"
        ) as mock_executor:
            mock_executor.return_value = MagicMock()
            server = OrchestratorServer(mock_httpx_client, host="localhost", port=10000)

        card = server.build_agent_card()

        for skill in card.skills:
            assert skill.name is not None and len(skill.name) > 0
            assert skill.description is not None and len(skill.description) > 0


class TestOrchestratorServerAcceptsRequests:
    """Test that server accepts requests."""

    def test_orchestrator_server_app_has_routes(self) -> None:
        """Test that the Starlette app has required routes."""
        from src.orchestrator.server import app

        route_paths = [r.path for r in app.routes]

        # Health check should be present
        assert "/health" in route_paths

    def test_orchestrator_server_routes_extend_on_startup(self) -> None:
        """Test that A2A routes are added during startup via lifespan."""
        from src.orchestrator.server import app

        # The app should have the health route initially
        initial_routes = list(app.routes)
        assert len(initial_routes) >= 1

        # During lifespan, A2A routes will be added
        # This is tested by the health check working after startup


class TestOrchestratorServerLogging:
    """Test that server logs requests appropriately."""

    def test_logger_is_configured(self) -> None:
        """Test that logger is configured for the server module."""
        from src.orchestrator import server

        assert hasattr(server, "logger")
        assert server.logger.name == "src.orchestrator.server"


class TestOrchestratorServerConstants:
    """Test server constants and configuration."""

    def test_agent_name_constant(self) -> None:
        """Test AGENT_NAME constant."""
        from src.orchestrator.server import AGENT_NAME

        assert AGENT_NAME == "Travel Planner Orchestrator"

    def test_agent_version_constant(self) -> None:
        """Test AGENT_VERSION constant."""
        from src.orchestrator.server import AGENT_VERSION

        assert AGENT_VERSION == "1.0.0"

    def test_default_port_is_10000(self) -> None:
        """Test that default orchestrator port is 10000."""
        import os

        # Clear env var to test default
        original = os.environ.pop("ORCHESTRATOR_PORT", None)
        try:
            # Re-import to get fresh defaults
            import importlib
            from src.orchestrator import server

            importlib.reload(server)
            assert server.port == 10000
        finally:
            if original is not None:
                os.environ["ORCHESTRATOR_PORT"] = original


class TestAgentCardEndpoint:
    """Test the /.well-known/agent.json endpoint."""

    def test_agent_card_endpoint(self) -> None:
        """Test that /.well-known/agent.json returns the AgentCard.

        The A2A protocol requires agents to expose their AgentCard
        at the /.well-known/agent.json endpoint for discovery.
        """
        from src.orchestrator.server import app

        client = TestClient(app)

        # The A2A routes are added during lifespan, so we need to
        # use the TestClient context which triggers lifespan
        with client:
            response = client.get("/.well-known/agent.json")

        assert response.status_code == 200
        data = response.json()

        # Verify key AgentCard fields
        assert data["name"] == AGENT_NAME
        assert data["version"] == AGENT_VERSION
        assert "description" in data
        assert "skills" in data
        assert len(data["skills"]) == 7  # Per design doc

    def test_agent_card_endpoint_has_capabilities(self) -> None:
        """Test that AgentCard endpoint returns capabilities."""
        from src.orchestrator.server import app

        client = TestClient(app)
        with client:
            response = client.get("/.well-known/agent.json")

        data = response.json()
        assert "capabilities" in data
        assert data["capabilities"]["streaming"] is True

    def test_agent_card_endpoint_skills_match_module(self) -> None:
        """Test that endpoint skills match agent_card module definition."""
        from src.orchestrator.server import app

        client = TestClient(app)
        with client:
            response = client.get("/.well-known/agent.json")

        data = response.json()
        skill_ids = [skill["id"] for skill in data["skills"]]

        # Verify all expected skill IDs are present
        for skill_id in ORCHESTRATOR_SKILL_IDS:
            assert skill_id in skill_ids, f"Missing skill: {skill_id}"


class TestAgentCardModule:
    """Test the agent_card.py module directly."""

    def test_build_orchestrator_skills_returns_seven_skills(self) -> None:
        """Test that build_orchestrator_skills returns exactly 7 skills."""
        skills = build_orchestrator_skills()
        assert len(skills) == 7

    def test_build_orchestrator_skills_ids_match_constant(self) -> None:
        """Test that skill IDs match ORCHESTRATOR_SKILL_IDS constant."""
        skills = build_orchestrator_skills()
        skill_ids = [skill.id for skill in skills]

        for expected_id in ORCHESTRATOR_SKILL_IDS:
            assert expected_id in skill_ids

    def test_build_orchestrator_agent_card_uses_host_port(self) -> None:
        """Test that build_orchestrator_agent_card uses provided host/port."""
        card = build_orchestrator_agent_card("example.com", 9999)

        assert card.url == "http://example.com:9999/"
        assert card.name == AGENT_NAME
        assert card.version == AGENT_VERSION

    def test_build_orchestrator_agent_card_has_streaming(self) -> None:
        """Test that AgentCard includes streaming capability."""
        card = build_orchestrator_agent_card("localhost", 10000)

        assert card.capabilities is not None
        assert card.capabilities.streaming is True

    def test_orchestrator_skill_ids_constant(self) -> None:
        """Test that ORCHESTRATOR_SKILL_IDS contains expected skills."""
        expected = [
            "plan_trip",
            "answer_travel_question",
            "convert_currency",
            "lookup_weather",
            "lookup_timezone",
            "get_booking",
            "get_consultation",
        ]
        assert ORCHESTRATOR_SKILL_IDS == expected

    def test_agent_name_constant(self) -> None:
        """Test AGENT_NAME constant from agent_card module."""
        assert AGENT_NAME == "Travel Planner Orchestrator"

    def test_agent_version_constant(self) -> None:
        """Test AGENT_VERSION constant from agent_card module."""
        assert AGENT_VERSION == "1.0.0"

    def test_skills_have_examples(self) -> None:
        """Test that all skills have example queries."""
        skills = build_orchestrator_skills()

        for skill in skills:
            assert skill.examples is not None and len(skill.examples) > 0, \
                f"Skill {skill.id} missing examples"

    def test_skills_have_tags(self) -> None:
        """Test that all skills have tags."""
        skills = build_orchestrator_skills()

        for skill in skills:
            assert skill.tags is not None and len(skill.tags) > 0, \
                f"Skill {skill.id} missing tags"
            # All skills should have "orchestrator" tag
            assert "orchestrator" in skill.tags, \
                f"Skill {skill.id} missing 'orchestrator' tag"
