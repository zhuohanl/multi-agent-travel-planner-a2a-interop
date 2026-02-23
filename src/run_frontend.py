"""Entry point to run the orchestrator FastAPI app used by the frontend."""

from __future__ import annotations

import logging
import os
import sys
from urllib.parse import urlparse

import httpx
import uvicorn
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def normalize_host(value: str) -> str:
    """Normalize SERVER_URL into a host value suitable for uvicorn."""
    candidate = value.strip()
    if not candidate:
        return "localhost"
    if candidate.startswith("http://") or candidate.startswith("https://"):
        parsed = urlparse(candidate)
        return parsed.hostname or "localhost"
    return candidate


def get_config() -> dict[str, str | int]:
    """Load host/port/log-level from environment variables."""
    server_host = normalize_host(os.environ.get("SERVER_URL", "localhost"))
    bind_host_raw = os.environ.get("ORCHESTRATOR_BIND_HOST", "").strip()
    bind_host = normalize_host(bind_host_raw) if bind_host_raw else server_host
    health_host = "localhost" if bind_host in {"0.0.0.0", "::"} else bind_host
    port = int(
        os.environ.get("ORCHESTRATOR_AGENT_PORT")
        or os.environ.get("ORCHESTRATOR_PORT", "10000")
    )
    log_level = os.environ.get("LOG_LEVEL", "info")
    return {
        "host": bind_host,
        "health_host": health_host,
        "port": port,
        "log_level": log_level,
    }


def is_api_running(host: str, port: int) -> bool:
    """Return True when orchestrator API health endpoint responds with 200."""
    health_url = f"http://{host}:{port}/health"
    try:
        response = httpx.get(health_url, timeout=2.0)
        if response.status_code != 200:
            return False
        payload = response.json()
        return isinstance(payload, dict) and payload.get("service") == "orchestrator-api"
    except Exception:
        return False


def main() -> None:
    """Start the orchestrator API server for frontend development."""
    config = get_config()
    host = str(config["host"])
    health_host = str(config["health_host"])
    port = int(config["port"])
    log_level = str(config["log_level"])

    logger.info(
        "Frontend API bind target: http://%s:%s (health check via %s)",
        host,
        port,
        health_host,
    )

    if is_api_running(health_host, port):
        logger.info("Orchestrator API is already running on http://%s:%s", health_host, port)
        return

    logger.info("Starting orchestrator API for frontend...")
    try:
        uvicorn.run(
            "src.orchestrator.api.app:app",
            host=host,
            port=port,
            log_level=log_level,
            reload=False,
        )
    except KeyboardInterrupt:
        logger.info("Shutting down frontend API launcher...")
        sys.exit(0)
    except Exception as exc:
        logger.error("Failed to start orchestrator API: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
