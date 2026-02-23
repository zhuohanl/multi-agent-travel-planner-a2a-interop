"""Unit tests for src/run_frontend.py entry point script."""

import os
from unittest.mock import patch

import pytest


class TestGetConfig:
    """Tests for get_config() in run_frontend.py."""

    def test_uses_defaults(self):
        from src.run_frontend import get_config

        env_overrides = {
            "SERVER_URL": "",
            "ORCHESTRATOR_AGENT_PORT": "",
            "ORCHESTRATOR_PORT": "",
            "LOG_LEVEL": "",
        }
        with patch.dict(os.environ, env_overrides, clear=False):
            for key in env_overrides:
                os.environ.pop(key, None)

            config = get_config()
            assert config["host"] == "localhost"
            assert config["port"] == 10000
            assert config["log_level"] == "info"

    def test_normalizes_server_url_host(self):
        from src.run_frontend import get_config

        with patch.dict(os.environ, {"SERVER_URL": "http://0.0.0.0"}, clear=False):
            config = get_config()
            assert config["host"] == "0.0.0.0"


class TestHealthProbe:
    """Tests for health-check logic."""

    def test_detects_running_api(self):
        from src.run_frontend import is_api_running

        with patch("src.run_frontend.httpx.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"service": "orchestrator-api"}
            assert is_api_running("localhost", 10000) is True

    def test_detects_not_running_api(self):
        from src.run_frontend import is_api_running

        with patch("src.run_frontend.httpx.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"agent_name": "orchestrator"}
            assert is_api_running("localhost", 10000) is False


class TestMain:
    """Tests for main() startup orchestration."""

    def test_skips_uvicorn_when_api_is_running(self):
        with patch("src.run_frontend.is_api_running", return_value=True):
            with patch("src.run_frontend.uvicorn.run") as mock_run:
                from src.run_frontend import main

                main()
                mock_run.assert_not_called()

    def test_starts_uvicorn_when_api_not_running(self):
        with patch("src.run_frontend.is_api_running", return_value=False):
            with patch("src.run_frontend.uvicorn.run") as mock_run:
                from src.run_frontend import main

                main()
                mock_run.assert_called_once_with(
                    "src.orchestrator.api.app:app",
                    host="localhost",
                    port=10000,
                    log_level="info",
                    reload=False,
                )

    def test_handles_keyboard_interrupt(self):
        with patch("src.run_frontend.is_api_running", return_value=False):
            with patch("src.run_frontend.uvicorn.run", side_effect=KeyboardInterrupt()):
                with pytest.raises(SystemExit) as exc_info:
                    from src.run_frontend import main

                    main()
                assert exc_info.value.code == 0
