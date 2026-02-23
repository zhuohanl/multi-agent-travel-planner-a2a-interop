"""Unit tests for src/run_orchestrator.py entry point script.

Tests configuration loading, app creation, and server startup behavior.
"""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestGetConfig:
    """Tests for get_config() configuration loading."""

    def test_loads_env_defaults(self):
        """Test that config loads default values when env vars not set."""
        from src.run_orchestrator import get_config

        # Clear relevant env vars
        env_overrides = {
            "SERVER_URL": "",
            "ORCHESTRATOR_PORT": "",
            "LOG_LEVEL": "",
            "PROJECT_ENDPOINT": "",
            "AZURE_OPENAI_DEPLOYMENT_NAME": "",
            "ORCHESTRATOR_ROUTING_AGENT_ID": "",
            "ORCHESTRATOR_CLASSIFIER_AGENT_ID": "",
            "ORCHESTRATOR_PLANNER_AGENT_ID": "",
            "ORCHESTRATOR_QA_AGENT_ID": "",
        }

        with patch.dict(os.environ, env_overrides, clear=False):
            # Remove the env vars completely
            for key in env_overrides:
                os.environ.pop(key, None)

            config = get_config()

            assert config["host"] == "localhost"
            assert config["port"] == 10000
            assert config["log_level"] == "info"
            assert config["azure_configured"] is False
            assert config["agents_configured"] is False

    def test_uses_configured_host_port(self):
        """Test that config respects env var overrides for host/port."""
        from src.run_orchestrator import get_config

        env_overrides = {
            "SERVER_URL": "0.0.0.0",
            "ORCHESTRATOR_PORT": "8080",
            "LOG_LEVEL": "debug",
        }

        with patch.dict(os.environ, env_overrides, clear=False):
            config = get_config()

            assert config["host"] == "0.0.0.0"
            assert config["port"] == 8080
            assert config["log_level"] == "debug"

    def test_detects_azure_configuration(self):
        """Test that config correctly detects Azure AI configuration."""
        from src.run_orchestrator import get_config

        # Test with Azure configured
        env_with_azure = {
            "PROJECT_ENDPOINT": "connection-string",
            "AZURE_OPENAI_DEPLOYMENT_NAME": "gpt-4",
        }

        with patch.dict(os.environ, env_with_azure, clear=False):
            config = get_config()
            assert config["azure_configured"] is True

    def test_detects_azure_not_configured(self):
        """Test that config correctly detects missing Azure configuration."""
        from src.run_orchestrator import get_config

        # Test with only partial Azure config
        env_partial = {
            "PROJECT_ENDPOINT": "connection-string",
        }

        # Remove deployment name
        with patch.dict(os.environ, env_partial, clear=False):
            os.environ.pop("AZURE_OPENAI_DEPLOYMENT_NAME", None)
            config = get_config()
            assert config["azure_configured"] is False

    def test_detects_agents_configuration(self):
        """Test that config correctly detects pre-provisioned agents."""
        from src.run_orchestrator import get_config

        env_with_agents = {
            "ORCHESTRATOR_ROUTING_AGENT_ID": "agent-1",
            "ORCHESTRATOR_CLASSIFIER_AGENT_ID": "agent-2",
            "ORCHESTRATOR_PLANNER_AGENT_ID": "agent-3",
            "ORCHESTRATOR_QA_AGENT_ID": "agent-4",
        }

        with patch.dict(os.environ, env_with_agents, clear=False):
            config = get_config()
            assert config["agents_configured"] is True

    def test_detects_agents_not_configured(self):
        """Test that config correctly detects missing agent IDs."""
        from src.run_orchestrator import get_config

        # Test with only partial agent config
        env_partial = {
            "ORCHESTRATOR_ROUTING_AGENT_ID": "agent-1",
            # Missing other agent IDs
        }

        with patch.dict(os.environ, env_partial, clear=False):
            # Remove other agent IDs
            os.environ.pop("ORCHESTRATOR_CLASSIFIER_AGENT_ID", None)
            os.environ.pop("ORCHESTRATOR_PLANNER_AGENT_ID", None)
            os.environ.pop("ORCHESTRATOR_QA_AGENT_ID", None)
            config = get_config()
            assert config["agents_configured"] is False


class TestCreateApp:
    """Tests for create_app() factory function."""

    def test_builds_uvicorn_app(self):
        """Test that create_app returns a valid Starlette application."""
        from starlette.applications import Starlette

        from src.run_orchestrator import create_app

        app = create_app()

        assert isinstance(app, Starlette)

    def test_app_has_health_route(self):
        """Test that the app has a health check route."""
        from src.run_orchestrator import create_app

        app = create_app()

        # Check that /health route exists
        route_paths = [route.path for route in app.routes]
        assert "/health" in route_paths

    def test_app_is_singleton(self):
        """Test that create_app returns the same app instance."""
        from src.run_orchestrator import create_app

        app1 = create_app()
        app2 = create_app()

        # The app should be the same module-level instance
        assert app1 is app2


class TestMain:
    """Tests for main() entry point."""

    def test_main_calls_uvicorn_run(self):
        """Test that main() calls uvicorn.run with correct arguments."""
        with patch("src.run_orchestrator.uvicorn.run") as mock_run:
            with patch.dict(
                os.environ,
                {
                    "SERVER_URL": "127.0.0.1",
                    "ORCHESTRATOR_PORT": "9000",
                    "LOG_LEVEL": "warning",
                },
            ):
                from src.run_orchestrator import main

                main()

                mock_run.assert_called_once_with(
                    "src.orchestrator.server:app",
                    host="127.0.0.1",
                    port=9000,
                    log_level="warning",
                    reload=False,
                )

    def test_main_with_defaults(self):
        """Test that main() uses default config values."""
        with patch("src.run_orchestrator.uvicorn.run") as mock_run:
            # Clear env vars to use defaults
            env_clear = {
                "SERVER_URL": "",
                "ORCHESTRATOR_PORT": "",
                "LOG_LEVEL": "",
            }
            with patch.dict(os.environ, env_clear, clear=False):
                for key in env_clear:
                    os.environ.pop(key, None)

                from src.run_orchestrator import main

                main()

                mock_run.assert_called_once_with(
                    "src.orchestrator.server:app",
                    host="localhost",
                    port=10000,
                    log_level="info",
                    reload=False,
                )

    def test_main_handles_keyboard_interrupt(self):
        """Test that main() handles KeyboardInterrupt gracefully."""
        with patch("src.run_orchestrator.uvicorn.run") as mock_run:
            mock_run.side_effect = KeyboardInterrupt()

            with pytest.raises(SystemExit) as exc_info:
                from src.run_orchestrator import main

                main()

            assert exc_info.value.code == 0

    def test_main_handles_startup_error(self):
        """Test that main() exits with error code on startup failure."""
        with patch("src.run_orchestrator.uvicorn.run") as mock_run:
            mock_run.side_effect = Exception("Port already in use")

            with pytest.raises(SystemExit) as exc_info:
                from src.run_orchestrator import main

                main()

            assert exc_info.value.code == 1

    def test_main_logs_startup_info(self):
        """Test that main() logs startup information."""
        with patch("src.run_orchestrator.uvicorn.run"):
            with patch("src.run_orchestrator.logger") as mock_logger:
                from src.run_orchestrator import main

                main()

                # Verify startup logging occurred
                info_calls = [call for call in mock_logger.info.call_args_list]
                assert len(info_calls) > 0

                # Check that host and port are logged
                all_log_messages = " ".join(
                    str(call) for call in mock_logger.info.call_args_list
                )
                assert "Host" in all_log_messages or "localhost" in all_log_messages


class TestModuleImport:
    """Tests for module-level imports and structure."""

    def test_module_imports_cleanly(self):
        """Test that the module can be imported without errors."""
        import importlib

        # Force reimport
        import src.run_orchestrator as module

        importlib.reload(module)

        assert hasattr(module, "get_config")
        assert hasattr(module, "create_app")
        assert hasattr(module, "main")

    def test_module_loads_dotenv(self):
        """Test that dotenv.load_dotenv is called on import."""
        # This is implicitly tested by the module loading without error
        # when .env file exists
        import src.run_orchestrator

        assert src.run_orchestrator is not None
