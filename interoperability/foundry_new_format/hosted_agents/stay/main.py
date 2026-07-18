from __future__ import annotations

import asyncio
import os

from agent_framework import Agent, ChatOptions
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import FoundryToolbox, ResponsesHostServer
from azure.identity import DefaultAzureCredential

from shared.prompt_loader import load_prompt
from shared.schemas import StayResponse


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} environment variable must be set")
    return value


def create_agent(*, credential=None, client=None, toolbox=None) -> Agent:
    credential = credential or DefaultAzureCredential()
    client = client or FoundryChatClient(
        project_endpoint=require_env("FOUNDRY_PROJECT_ENDPOINT"),
        model=require_env("AZURE_AI_MODEL_DEPLOYMENT_NAME"),
        credential=credential,
    )
    toolbox = toolbox or FoundryToolbox(credential)
    return Agent(
        client=client,
        name="TravelPlannerStay",
        instructions=load_prompt("stay"),
        tools=toolbox,
        default_options=ChatOptions(store=False, response_format=StayResponse),
    )


async def main() -> None:
    await ResponsesHostServer(create_agent()).run_async()


if __name__ == "__main__":
    asyncio.run(main())
