"""Entry point script for the Orchestrator A2A server.

This script starts the orchestrator server with configuration loaded from
environment variables. It provides the canonical way to launch the orchestrator
for development and production use.

Architecture (per design doc Overview section):
- Entry Point 1: A2A Protocol via OrchestratorServer → OrchestratorExecutor
- The orchestrator serves the A2A protocol at the configured host:port
- AgentCard is available at /.well-known/agent.json
- Health check is available at /health

Configuration (environment variables):
    SERVER_URL: Server host (default: localhost)
    ORCHESTRATOR_AGENT_PORT: Server port (default: 10000)
    ORCHESTRATOR_PORT: Legacy server port (default: 10000)
    PROJECT_ENDPOINT: Azure AI Agent Service endpoint URL (optional)
        Format: https://<resource-name>.services.ai.azure.com/api/projects/<project-name>
    AZURE_OPENAI_DEPLOYMENT_NAME: Azure OpenAI deployment (optional)
    ORCHESTRATOR_ROUTING_AGENT_ID: Pre-provisioned routing agent ID (optional)
    ORCHESTRATOR_CLASSIFIER_AGENT_ID: Pre-provisioned classifier agent ID (optional)
    ORCHESTRATOR_PLANNER_AGENT_ID: Pre-provisioned planner agent ID (optional)
    ORCHESTRATOR_QA_AGENT_ID: Pre-provisioned Q&A agent ID (optional)

Usage:
    # Start with default configuration
    uv run python src/run_orchestrator.py

    # Or with custom port
    ORCHESTRATOR_AGENT_PORT=8000 uv run python src/run_orchestrator.py

    # Or via uvicorn directly
    uv run uvicorn src.orchestrator.server:app --host localhost --port 10000
"""

from __future__ import annotations

import logging
import os
import sys

import uvicorn
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_config() -> dict[str, str | int]:
    """Load orchestrator configuration from environment variables.

    Returns:
        Dictionary with host, port, and other configuration values.
    """
    config = {
        "host": os.environ.get("SERVER_URL", "localhost"),
        "port": int(
            os.environ.get("ORCHESTRATOR_AGENT_PORT")
            or os.environ.get("ORCHESTRATOR_PORT", "10000")
        ),
        "log_level": os.environ.get("LOG_LEVEL", "info"),
    }

    # Log Azure AI configuration status (not the actual values for security)
    azure_configured = all(
        os.environ.get(var)
        for var in [
            "PROJECT_ENDPOINT",
            "AZURE_OPENAI_DEPLOYMENT_NAME",
        ]
    )

    agents_configured = all(
        os.environ.get(var)
        for var in [
            "ORCHESTRATOR_ROUTING_AGENT_ID",
            "ORCHESTRATOR_CLASSIFIER_AGENT_ID",
            "ORCHESTRATOR_PLANNER_AGENT_ID",
            "ORCHESTRATOR_QA_AGENT_ID",
        ]
    )

    config["azure_configured"] = azure_configured
    config["agents_configured"] = agents_configured

    return config


def create_app():
    """Create and return the orchestrator Starlette application.

    This function is useful for programmatic access and testing.

    Returns:
        The Starlette application instance from orchestrator.server
    """
    from src.orchestrator.server import app

    return app


def main() -> None:
    """Start the orchestrator server."""
    config = get_config()

    logger.info("=" * 60)
    logger.info("Starting Travel Planner Orchestrator")
    logger.info("=" * 60)
    logger.info("Host: %s", config["host"])
    logger.info("Port: %s", config["port"])
    logger.info("Azure AI configured: %s", config["azure_configured"])
    logger.info("Pre-provisioned agents: %s", config["agents_configured"])
    logger.info("=" * 60)

    if not config["azure_configured"]:
        logger.warning(
            "Azure AI not configured. Running in placeholder mode. "
            "Set PROJECT_ENDPOINT and AZURE_OPENAI_DEPLOYMENT_NAME "
            "for full functionality."
        )

    if not config["agents_configured"]:
        logger.warning(
            "Pre-provisioned agents not configured. "
            "Run scripts/provision_azure_agents.py to create agents."
        )

    # Start the server using uvicorn
    logger.info(
        "Starting uvicorn server at http://%s:%s",
        config["host"],
        config["port"],
    )
    logger.info("Health check available at http://%s:%s/health", config["host"], config["port"])
    logger.info(
        "AgentCard available at http://%s:%s/.well-known/agent.json",
        config["host"],
        config["port"],
    )

    try:
        uvicorn.run(
            "src.orchestrator.server:app",
            host=str(config["host"]),
            port=int(config["port"]),
            log_level=str(config["log_level"]),
            reload=False,  # Disable reload for production stability
        )
    except KeyboardInterrupt:
        logger.info("Shutting down orchestrator server...")
        sys.exit(0)
    except Exception as e:
        logger.error("Failed to start server: %s", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
