"""
Azure AI Agent Service configuration for the orchestrator.

This module defines and validates the configuration required to connect
to Azure AI Agent Service, which the orchestrator uses for LLM-driven
routing decisions (routing, classification, planning, Q&A).

The orchestrator uses 4 pre-provisioned Azure AI agents:
  - Router: Decides workflow_turn vs answer_question
  - Classifier: Classifies user actions (APPROVE, MODIFY, etc.)
  - Planner: Plans which agents to re-run for modifications
  - QA: Answers general/budget questions

Usage:
    # From command line - verify configuration:
    uv run python -m infrastructure.azure_agent_setup

    # From code:
    from infrastructure.azure_agent_setup import get_azure_config, verify_connection
    config = get_azure_config()  # Raises if missing required env vars
    await verify_connection(config)  # Tests connectivity

Environment Variables:
    Required:
        PROJECT_ENDPOINT: Azure AI Agent Service endpoint URL
            Format: https://<resource-name>.services.ai.azure.com/api/projects/<project-name>
        AZURE_OPENAI_DEPLOYMENT_NAME: LLM model deployment name (e.g., gpt-4.1)

    Required for orchestrator runtime:
        ORCHESTRATOR_ROUTING_AGENT_ID: Pre-provisioned routing agent ID
        ORCHESTRATOR_CLASSIFIER_AGENT_ID: Pre-provisioned classifier agent ID
        ORCHESTRATOR_PLANNER_AGENT_ID: Pre-provisioned planner agent ID
        ORCHESTRATOR_QA_AGENT_ID: Pre-provisioned Q&A agent ID

Dependencies:
    Requires azure-ai-agents and azure-identity packages for actual Azure operations.
    Install with: uv add azure-ai-agents azure-identity
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Import azure packages only at type-checking time or when needed at runtime
# This allows the module to be imported for testing without the SDKs installed
if TYPE_CHECKING:
    from azure.ai.agents import AgentsClient

logger = logging.getLogger(__name__)


# Required environment variables for Azure AI Agent Service connection
REQUIRED_CONNECTION_VARS = [
    "PROJECT_ENDPOINT",
    "AZURE_OPENAI_DEPLOYMENT_NAME",
]

# Required environment variables for pre-provisioned orchestrator agents
REQUIRED_AGENT_ID_VARS = [
    "ORCHESTRATOR_ROUTING_AGENT_ID",
    "ORCHESTRATOR_CLASSIFIER_AGENT_ID",
    "ORCHESTRATOR_PLANNER_AGENT_ID",
    "ORCHESTRATOR_QA_AGENT_ID",
]

# All environment variables documented in this module
ALL_DOCUMENTED_VARS = REQUIRED_CONNECTION_VARS + REQUIRED_AGENT_ID_VARS


@dataclass(frozen=True)
class AzureAgentConfig:
    """Configuration for Azure AI Agent Service connection."""

    endpoint: str
    deployment_name: str
    routing_agent_id: str | None = None
    classifier_agent_id: str | None = None
    planner_agent_id: str | None = None
    qa_agent_id: str | None = None

    @property
    def has_connection_config(self) -> bool:
        """Check if connection configuration is present."""
        return bool(self.endpoint and self.deployment_name)

    @property
    def has_agent_ids(self) -> bool:
        """Check if all agent IDs are configured."""
        return all([
            self.routing_agent_id,
            self.classifier_agent_id,
            self.planner_agent_id,
            self.qa_agent_id,
        ])

    @property
    def agent_id_dict(self) -> dict[str, str | None]:
        """Return agent IDs as a dictionary."""
        return {
            "router": self.routing_agent_id,
            "classifier": self.classifier_agent_id,
            "planner": self.planner_agent_id,
            "qa": self.qa_agent_id,
        }


def get_missing_env_vars(var_names: list[str]) -> list[str]:
    """Return list of environment variable names that are not set."""
    return [var for var in var_names if not os.environ.get(var)]


def get_azure_config(require_agent_ids: bool = False) -> AzureAgentConfig:
    """
    Load Azure AI Agent Service configuration from environment variables.

    Args:
        require_agent_ids: If True, also require agent ID environment variables

    Returns:
        AzureAgentConfig with values from environment

    Raises:
        ValueError: If required environment variables are not set
    """
    # Check required connection vars
    missing = get_missing_env_vars(REQUIRED_CONNECTION_VARS)
    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "See .env.example for required configuration."
        )

    # Check agent IDs if required
    if require_agent_ids:
        missing_agents = get_missing_env_vars(REQUIRED_AGENT_ID_VARS)
        if missing_agents:
            raise ValueError(
                f"Missing required agent ID environment variables: {', '.join(missing_agents)}. "
                "Run 'uv run python scripts/provision_azure_agents.py' to create agents "
                "and get their IDs."
            )

    return AzureAgentConfig(
        endpoint=os.environ["PROJECT_ENDPOINT"],
        deployment_name=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
        routing_agent_id=os.environ.get("ORCHESTRATOR_ROUTING_AGENT_ID"),
        classifier_agent_id=os.environ.get("ORCHESTRATOR_CLASSIFIER_AGENT_ID"),
        planner_agent_id=os.environ.get("ORCHESTRATOR_PLANNER_AGENT_ID"),
        qa_agent_id=os.environ.get("ORCHESTRATOR_QA_AGENT_ID"),
    )


def _get_azure_agents_imports() -> tuple[Any, Any]:
    """
    Lazily import Azure AI Agents dependencies.

    Returns:
        Tuple of (AgentsClient, DefaultAzureCredential)

    Raises:
        ImportError: If azure-ai-agents or azure-identity packages are not installed
    """
    try:
        from azure.ai.agents import AgentsClient
        from azure.identity import DefaultAzureCredential

        return AgentsClient, DefaultAzureCredential
    except ImportError as e:
        raise ImportError(
            "azure-ai-agents and azure-identity packages are required for Azure AI operations. "
            "Install with: uv add azure-ai-agents azure-identity"
        ) from e


def parse_endpoint(endpoint: str) -> dict[str, str]:
    """
    Parse Azure AI Agent Service endpoint URL into components.

    Endpoint URL format:
        https://<resource-name>.services.ai.azure.com/api/projects/<project-name>

    Args:
        endpoint: Azure AI Agent Service endpoint URL

    Returns:
        Dictionary with 'resource_name' and 'project_name'

    Raises:
        ValueError: If endpoint format is invalid
    """
    import re

    pattern = r"https://([^.]+)\.services\.ai\.azure\.com/api/projects/([^/]+)"
    match = re.match(pattern, endpoint)

    if not match:
        raise ValueError(
            "Invalid endpoint format. Expected: "
            "https://<resource-name>.services.ai.azure.com/api/projects/<project-name>"
        )

    return {
        "resource_name": match.group(1),
        "project_name": match.group(2),
    }


def create_agents_client(config: AzureAgentConfig) -> "AgentsClient":
    """
    Create an AgentsClient from configuration.

    Args:
        config: Azure agent configuration

    Returns:
        Configured AgentsClient instance

    Raises:
        ImportError: If required packages are not installed
    """
    AgentsClient, DefaultAzureCredential = _get_azure_agents_imports()

    return AgentsClient(
        endpoint=config.endpoint,
        credential=DefaultAzureCredential(),
    )


async def verify_connection(config: AzureAgentConfig) -> dict[str, Any]:
    """
    Verify connection to Azure AI Agent Service.

    Args:
        config: Azure agent configuration

    Returns:
        Dictionary with connection status and details

    Raises:
        ImportError: If required packages are not installed
        Exception: If connection verification fails
    """
    client = create_agents_client(config)

    # Parse endpoint to extract project info
    endpoint_info = parse_endpoint(config.endpoint)

    result = {
        "connected": False,
        "project_name": endpoint_info["project_name"],
        "resource_name": endpoint_info["resource_name"],
        "endpoint": config.endpoint,
        "deployment_name": config.deployment_name,
        "agents_configured": config.has_agent_ids,
        "agent_ids": config.agent_id_dict if config.has_agent_ids else None,
    }

    # Try to list agents to verify connection
    try:
        # This is a lightweight operation to test connectivity
        agents = client.list_agents(limit=1)
        _ = list(agents)
        result["connected"] = True
    except Exception as e:
        result["error"] = str(e)

    return result


async def verify_agent_ids(config: AzureAgentConfig) -> dict[str, dict[str, Any]]:
    """
    Verify that configured agent IDs exist in Azure.

    Args:
        config: Azure agent configuration with agent IDs

    Returns:
        Dictionary mapping agent type to verification result

    Raises:
        ImportError: If required packages are not installed
    """
    if not config.has_agent_ids:
        raise ValueError("Agent IDs are not configured")

    client = create_agents_client(config)
    results: dict[str, dict[str, Any]] = {}

    for agent_type, agent_id in config.agent_id_dict.items():
        if not agent_id:
            results[agent_type] = {"exists": False, "error": "Not configured"}
            continue

        try:
            agent = client.get_agent(agent_id)
            results[agent_type] = {
                "exists": True,
                "id": agent.get("id"),
                "name": agent.get("name"),
            }
        except Exception as e:
            results[agent_type] = {"exists": False, "error": str(e)}

    return results


def print_env_template() -> str:
    """
    Return a template for environment variables.

    Returns:
        String containing .env template content
    """
    return """# Azure AI Agent Service Configuration
# Required for orchestrator LLM routing decisions

# Azure AI Agent Service endpoint URL
# Format: https://<resource-name>.services.ai.azure.com/api/projects/<project-name>
# Get this from your Azure project settings in the portal
PROJECT_ENDPOINT="https://your-resource.services.ai.azure.com/api/projects/your-project"

# LLM model deployment name (from Azure OpenAI)
AZURE_OPENAI_DEPLOYMENT_NAME="gpt-4.1"

# Pre-provisioned orchestrator agent IDs
# Create these by running: uv run python scripts/provision_azure_agents.py
# The script will output the agent IDs to set here
ORCHESTRATOR_ROUTING_AGENT_ID=""
ORCHESTRATOR_CLASSIFIER_AGENT_ID=""
ORCHESTRATOR_PLANNER_AGENT_ID=""
ORCHESTRATOR_QA_AGENT_ID=""
"""


async def main() -> None:
    """
    Main entry point for configuration verification.

    Verifies Azure AI Agent Service configuration and connectivity.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("Azure AI Agent Service Configuration Verification")
    logger.info("=" * 60)

    # Check environment variables
    logger.info("\n1. Checking environment variables...")

    missing_conn = get_missing_env_vars(REQUIRED_CONNECTION_VARS)
    missing_agents = get_missing_env_vars(REQUIRED_AGENT_ID_VARS)

    if missing_conn:
        logger.warning(f"   Missing connection variables: {', '.join(missing_conn)}")
        logger.info("\n   To set up Azure AI Agent Service:")
        logger.info("   1. Create an Azure AI project")
        logger.info("   2. Deploy an LLM model (e.g., gpt-4.1)")
        logger.info("   3. Get the project connection string from portal")
        logger.info("   4. Add to your .env file:")
        logger.info("")
        logger.info(print_env_template())
        return

    logger.info("   Connection variables: OK")

    if missing_agents:
        logger.warning(f"   Missing agent ID variables: {', '.join(missing_agents)}")
        logger.info("   Agent IDs will be set after running provision_azure_agents.py")
    else:
        logger.info("   Agent ID variables: OK")

    # Load configuration
    try:
        config = get_azure_config(require_agent_ids=False)
        logger.info(f"   Deployment name: {config.deployment_name}")
    except ValueError as e:
        logger.error(f"   Configuration error: {e}")
        return

    # Parse endpoint
    logger.info("\n2. Parsing endpoint...")
    try:
        endpoint_info = parse_endpoint(config.endpoint)
        logger.info(f"   Resource: {endpoint_info['resource_name']}")
        logger.info(f"   Project: {endpoint_info['project_name']}")
    except ValueError as e:
        logger.error(f"   Invalid endpoint: {e}")
        return

    # Verify connection
    logger.info("\n3. Verifying connection to Azure AI Agent Service...")
    try:
        result = await verify_connection(config)
        if result["connected"]:
            logger.info("   Connection: SUCCESS")
        else:
            logger.error(f"   Connection: FAILED - {result.get('error', 'Unknown error')}")
    except ImportError as e:
        logger.warning(f"   Cannot verify connection: {e}")
        logger.info("   Install packages with: uv add azure-ai-agents azure-identity")
    except Exception as e:
        logger.error(f"   Connection failed: {e}")

    # Verify agent IDs if configured
    if config.has_agent_ids:
        logger.info("\n4. Verifying pre-provisioned agent IDs...")
        try:
            agent_results = await verify_agent_ids(config)
            for agent_type, status in agent_results.items():
                if status["exists"]:
                    logger.info(f"   {agent_type}: OK (name={status.get('name', 'N/A')})")
                else:
                    logger.error(f"   {agent_type}: NOT FOUND - {status.get('error', 'Unknown')}")
        except Exception as e:
            logger.error(f"   Agent verification failed: {e}")
    else:
        logger.info("\n4. Agent IDs not yet configured")
        logger.info("   Run: uv run python scripts/provision_azure_agents.py")

    logger.info("\n" + "=" * 60)
    logger.info("Configuration verification complete.")


if __name__ == "__main__":
    asyncio.run(main())
