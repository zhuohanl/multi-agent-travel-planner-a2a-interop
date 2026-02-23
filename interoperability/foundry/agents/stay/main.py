"""
Stay Agent - Hosted Agent Entry Point (Microsoft Agent Framework)

This module wraps Stay agent behavior for deployment as a hosted agent on
Azure AI Foundry, aligning with the Agent Framework hosted agent sample.
"""

import logging
import os
import platform

from dotenv import load_dotenv
from agent_framework import ChatAgent, HostedWebSearchTool
from agent_framework_azure_ai import AzureAIAgentClient
from azure.ai.agentserver.agentframework import from_agent_framework
from azure.identity.aio import DefaultAzureCredential

from src.shared.models import StayResponse
from src.shared.utils.load_prompt import load_prompt

load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)
logger.info(
    "Stay agent module loaded (pid=%s, python=%s)",
    os.getpid(),
    platform.python_version(),
)


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} environment variable must be set.")
    return value


def create_agent() -> ChatAgent:
    logger.info("Creating StayAgent")
    project_endpoint = _require_env("PROJECT_ENDPOINT")
    azure_openai_deployment_name = _require_env("AZURE_OPENAI_DEPLOYMENT_NAME")
    bing_project_connection_id = _require_env("BING_PROJECT_CONNECTION_ID")

    logger.info("Using project endpoint: %s", project_endpoint)
    logger.info("Using model deployment name: %s", azure_openai_deployment_name)
    logger.info("Using Bing grounding connection id: %s", bing_project_connection_id)

    chat_client = AzureAIAgentClient(
        project_endpoint=project_endpoint,
        model_deployment_name=azure_openai_deployment_name,
        credential=DefaultAzureCredential(),
    )

    search_tool = HostedWebSearchTool(
        description="Search the web for current accommodation information.",
        connection_id=bing_project_connection_id,
    )

    return ChatAgent(
        chat_client=chat_client,
        name="StayAgent",
        instructions=load_prompt("stay"),
        response_format=StayResponse,
        # TODO: fix this
        # Getting "something is wrong" error when enabling tools. response_format + tool call incompatibility issue? 
        # tools=[search_tool],
    )


def main() -> None:
    port = int(os.getenv("PORT", os.getenv("DEFAULT_AD_PORT", "8088")))
    logger.info("Starting Stay agent server on port %s", port)
    try:
        from_agent_framework(create_agent()).run(port=port)
    except Exception:
        logger.exception("Stay agent server failed to start")
        raise


if __name__ == "__main__":
    main()
