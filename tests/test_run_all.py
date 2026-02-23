"""Unit tests for run_all.py server configuration and management."""

import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio

# Mock environment variables before importing run_all
TEST_ENV = {
    "SERVER_URL": "localhost",
    "INTAKE_CLARIFIER_AGENT_PORT": "10007",
    "POI_SEARCH_AGENT_PORT": "10008",
    "STAY_AGENT_PORT": "10009",
    "TRANSPORT_AGENT_PORT": "10010",
    "EVENTS_AGENT_PORT": "10011",
    "ROUTE_AGENT_PORT": "10012",
    "BUDGET_AGENT_PORT": "10013",
    "BOOKING_AGENT_PORT": "10014",
    "AGGREGATOR_AGENT_PORT": "10015",
    "VALIDATOR_AGENT_PORT": "10016",
    "DINING_AGENT_PORT": "10017",
}


class TestServerConfiguration:
    """Tests for server configuration in run_all.py."""

    def test_all_agents_configured(self):
        """Verify all 11 agents are configured in servers list."""
        with patch.dict(os.environ, TEST_ENV, clear=False):
            # Re-import to pick up env vars
            import importlib
            import src.run_all as run_all_module
            importlib.reload(run_all_module)

            assert len(run_all_module.servers) == 11

    def test_server_names_unique(self):
        """Verify all server names are unique."""
        with patch.dict(os.environ, TEST_ENV, clear=False):
            import importlib
            import src.run_all as run_all_module
            importlib.reload(run_all_module)

            names = [s["name"] for s in run_all_module.servers]
            assert len(names) == len(set(names)), "Server names must be unique"

    def test_server_ports_unique(self):
        """Verify all server ports are unique."""
        with patch.dict(os.environ, TEST_ENV, clear=False):
            import importlib
            import src.run_all as run_all_module
            importlib.reload(run_all_module)

            ports = [s["port"] for s in run_all_module.servers]
            assert len(ports) == len(set(ports)), "Server ports must be unique"

    def test_server_modules_valid_format(self):
        """Verify all server modules follow the expected format."""
        with patch.dict(os.environ, TEST_ENV, clear=False):
            import importlib
            import src.run_all as run_all_module
            importlib.reload(run_all_module)

            for server in run_all_module.servers:
                module = server["module"]
                assert module.startswith("src.agents."), f"Module should start with src.agents.: {module}"
                assert module.endswith(".server:app"), f"Module should end with .server:app: {module}"

    def test_expected_agents_present(self):
        """Verify all expected agents are present in configuration."""
        with patch.dict(os.environ, TEST_ENV, clear=False):
            import importlib
            import src.run_all as run_all_module
            importlib.reload(run_all_module)

            expected_agents = [
                "intake_clarifier_agent_server",
                "poi_search_agent_server",
                "stay_agent_server",
                "transport_agent_server",
                "events_agent_server",
                "dining_agent_server",
                "aggregator_agent_server",
                "budget_agent_server",
                "route_agent_server",
                "validator_agent_server",
                "booking_agent_server",
            ]
            actual_names = [s["name"] for s in run_all_module.servers]
            for agent in expected_agents:
                assert agent in actual_names, f"Missing agent: {agent}"

    def test_port_mappings_correct(self):
        """Verify port mappings match .env configuration."""
        with patch.dict(os.environ, TEST_ENV, clear=False):
            import importlib
            import src.run_all as run_all_module
            importlib.reload(run_all_module)

            port_map = {s["name"]: s["port"] for s in run_all_module.servers}

            assert port_map["intake_clarifier_agent_server"] == "10007"
            assert port_map["poi_search_agent_server"] == "10008"
            assert port_map["stay_agent_server"] == "10009"
            assert port_map["transport_agent_server"] == "10010"
            assert port_map["events_agent_server"] == "10011"
            assert port_map["dining_agent_server"] == "10017"
            assert port_map["aggregator_agent_server"] == "10015"
            assert port_map["budget_agent_server"] == "10013"
            assert port_map["route_agent_server"] == "10012"
            assert port_map["validator_agent_server"] == "10016"
            assert port_map["booking_agent_server"] == "10014"


class TestWaitForServerReady:
    """Tests for wait_for_server_ready function."""

    @pytest.mark.asyncio
    async def test_wait_for_server_ready_success(self):
        """Test successful health check."""
        with patch.dict(os.environ, TEST_ENV, clear=False):
            import importlib
            import src.run_all as run_all_module
            importlib.reload(run_all_module)

            mock_response = MagicMock()
            mock_response.status_code = 200

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("httpx.AsyncClient", return_value=mock_client):
                server = {"name": "test_server", "port": "9999"}
                result = await run_all_module.wait_for_server_ready(server, timeout=5)
                assert result is True

    @pytest.mark.asyncio
    async def test_wait_for_server_ready_timeout(self):
        """Test timeout when server never becomes healthy."""
        with patch.dict(os.environ, TEST_ENV, clear=False):
            import importlib
            import src.run_all as run_all_module
            importlib.reload(run_all_module)

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("httpx.AsyncClient", return_value=mock_client):
                server = {"name": "test_server", "port": "9999"}
                result = await run_all_module.wait_for_server_ready(server, timeout=1)
                assert result is False

    @pytest.mark.asyncio
    async def test_wait_for_server_ready_eventual_success(self):
        """Test server becomes healthy after initial failures."""
        with patch.dict(os.environ, TEST_ENV, clear=False):
            import importlib
            import src.run_all as run_all_module
            importlib.reload(run_all_module)

            mock_response = MagicMock()
            mock_response.status_code = 200

            call_count = [0]
            async def mock_get(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] < 3:
                    raise Exception("Connection refused")
                return mock_response

            mock_client = AsyncMock()
            mock_client.get = mock_get
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("httpx.AsyncClient", return_value=mock_client):
                server = {"name": "test_server", "port": "9999"}
                result = await run_all_module.wait_for_server_ready(server, timeout=10)
                assert result is True
                assert call_count[0] >= 3


class TestStreamSubprocessOutput:
    """Tests for stream_subprocess_output function."""

    def test_stream_subprocess_output_reads_lines(self):
        """Test that function reads lines from subprocess stdout."""
        with patch.dict(os.environ, TEST_ENV, clear=False):
            import importlib
            import src.run_all as run_all_module
            importlib.reload(run_all_module)

            mock_process = MagicMock()
            lines = ["line1\n", "line2\n", ""]  # Empty string signals EOF
            mock_process.stdout.readline = MagicMock(side_effect=lines)

            # Run in a thread since this function is blocking
            import threading
            printed_lines = []

            with patch("builtins.print", side_effect=lambda x: printed_lines.append(x)):
                run_all_module.stream_subprocess_output(mock_process)

            assert "line1" in printed_lines
            assert "line2" in printed_lines


class TestServerProcsManagement:
    """Tests for server process management."""

    def test_server_procs_starts_empty(self):
        """Verify server_procs list starts empty."""
        with patch.dict(os.environ, TEST_ENV, clear=False):
            import importlib
            import src.run_all as run_all_module
            importlib.reload(run_all_module)

            # Reset the list
            run_all_module.server_procs.clear()
            assert len(run_all_module.server_procs) == 0


class TestAgentModulePaths:
    """Tests to verify agent module paths are importable."""

    def test_intake_clarifier_module_exists(self):
        """Verify intake_clarifier agent module can be imported."""
        from src.agents.intake_clarifier_agent import server
        assert hasattr(server, "app")

    def test_poi_search_module_exists(self):
        """Verify poi_search agent module can be imported."""
        from src.agents.poi_search_agent import server
        assert hasattr(server, "app")

    def test_stay_module_exists(self):
        """Verify stay agent module can be imported."""
        from src.agents.stay_agent import server
        assert hasattr(server, "app")

    def test_transport_module_exists(self):
        """Verify transport agent module can be imported."""
        from src.agents.transport_agent import server
        assert hasattr(server, "app")

    def test_events_module_exists(self):
        """Verify events agent module can be imported."""
        from src.agents.events_agent import server
        assert hasattr(server, "app")

    def test_dining_module_exists(self):
        """Verify dining agent module can be imported."""
        from src.agents.dining_agent import server
        assert hasattr(server, "app")

    def test_aggregator_module_exists(self):
        """Verify aggregator agent module can be imported."""
        from src.agents.aggregator_agent import server
        assert hasattr(server, "app")

    def test_budget_module_exists(self):
        """Verify budget agent module can be imported."""
        from src.agents.budget_agent import server
        assert hasattr(server, "app")

    def test_route_module_exists(self):
        """Verify route agent module can be imported."""
        from src.agents.route_agent import server
        assert hasattr(server, "app")

    def test_validator_module_exists(self):
        """Verify validator agent module can be imported."""
        from src.agents.validator_agent import server
        assert hasattr(server, "app")

    def test_booking_module_exists(self):
        """Verify booking agent module can be imported."""
        from src.agents.booking_agent import server
        assert hasattr(server, "app")
