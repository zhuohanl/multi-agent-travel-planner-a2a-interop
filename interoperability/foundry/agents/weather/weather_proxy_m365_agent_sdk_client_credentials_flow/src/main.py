"""
Console test client for CopilotClient with Client Credentials Flow.

This is a standalone script for testing the client credentials flow locally
before deploying as a hosted agent. It connects to the Copilot Studio Weather
Agent using an app-only token (no interactive user sign-in).

Usage:
    python -m src.main
"""

import logging
import sys
from os import environ
import asyncio

from dotenv import load_dotenv
from msal import ConfidentialClientApplication

from microsoft_agents.activity import ActivityTypes
from microsoft_agents.copilotstudio.client import (
    ConnectionSettings,
    CopilotClient,
    PowerPlatformCloud,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

POWER_PLATFORM_SCOPE = "https://api.powerplatform.com/.default"


def acquire_token() -> str:
    """Acquire an app-only token using client credentials flow."""
    tenant_id = environ.get("COPILOTSTUDIOAGENT__TENANTID")
    client_id = environ.get("COPILOTSTUDIOAGENT__AGENTAPPID")
    client_secret = environ.get("COPILOTSTUDIOAGENT__AGENTAPPSECRET")

    if not all([tenant_id, client_id, client_secret]):
        raise RuntimeError(
            "Missing required env vars: COPILOTSTUDIOAGENT__TENANTID, "
            "COPILOTSTUDIOAGENT__AGENTAPPID, COPILOTSTUDIOAGENT__AGENTAPPSECRET"
        )

    cca = ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
    )

    result = cca.acquire_token_for_client(scopes=[POWER_PLATFORM_SCOPE])

    if "access_token" not in result:
        error = result.get("error", "unknown")
        error_description = result.get("error_description", "No description")
        raise RuntimeError(f"Token acquisition failed: {error} - {error_description}")

    logger.info("Token acquired successfully via client credentials flow")
    return result["access_token"]


def create_client() -> CopilotClient:
    """Create CopilotClient with app-only token."""
    settings = ConnectionSettings(
        environment_id=environ.get("COPILOTSTUDIOAGENT__ENVIRONMENTID"),
        agent_identifier=environ.get("COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME"),
        cloud=PowerPlatformCloud.PROD,
        copilot_agent_type=None,
        custom_power_platform_cloud=None,
    )
    token = acquire_token()
    return CopilotClient(settings, token)


async def ainput(string: str) -> str:
    await asyncio.get_event_loop().run_in_executor(
        None, lambda s=string: sys.stdout.write(s + " ")
    )
    return await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)


async def ask_question(copilot_client, conversation_id):
    query = (await ainput("\n>>>: ")).lower().strip()
    if query in ["exit", "quit"]:
        print("Exiting...")
        return
    if query:
        replies = copilot_client.ask_question(query, conversation_id)
        async for reply in replies:
            if reply.type == ActivityTypes.message:
                print(f"\n{reply.text}")
                if reply.suggested_actions:
                    for action in reply.suggested_actions.actions:
                        print(f" - {action.title}")
            elif reply.type == ActivityTypes.end_of_conversation:
                print("\nEnd of conversation.")
                sys.exit(0)
        await ask_question(copilot_client, conversation_id)


async def main():
    copilot_client = create_client()
    act = copilot_client.start_conversation(True)
    print("\nSuggested Actions: ")
    async for action in act:
        if action.text:
            print(action.text)
    await ask_question(copilot_client, action.conversation.id)


asyncio.run(main())
