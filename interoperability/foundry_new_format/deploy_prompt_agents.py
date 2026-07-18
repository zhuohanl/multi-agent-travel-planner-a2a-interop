from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    BingGroundingTool,
    BingGroundingSearchConfiguration,
    BingGroundingSearchToolParameters,
    PromptAgentDefinition,
)
from azure.identity import DefaultAzureCredential

from interoperability.foundry_new_format.shared.config import (
    ConfigError,
    PromptAgentSpec,
    load_prompt_agent_specs,
)

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "config.yaml"
FOUNDRY_PROJECT_ENDPOINT_PATTERN = re.compile(
    r"https://[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    r"\.services\.ai\.azure\.com/api/projects/[A-Za-z0-9_][A-Za-z0-9_-]*"
)


@dataclass(frozen=True)
class DeploymentSettings:
    project_endpoint: str
    model_deployment: str
    bing_connection_id: str | None


def build_prompt_definition(
    spec: PromptAgentSpec,
    model_deployment: str,
    bing_connection_id: str | None,
) -> PromptAgentDefinition:
    tools: list[Any] = []
    if "bing_grounding" in spec.tools:
        if not bing_connection_id:
            raise ConfigError(f"{spec.name} requires BING_PROJECT_CONNECTION_ID")
        tools.append(
            BingGroundingTool(
                bing_grounding=BingGroundingSearchToolParameters(
                    search_configurations=[
                        BingGroundingSearchConfiguration(
                            project_connection_id=bing_connection_id
                        )
                    ]
                )
            )
        )
    return PromptAgentDefinition(
        model=model_deployment,
        instructions=spec.load_instructions(),
        tools=tools,
    )


def deploy_prompt_agent(
    client: AIProjectClient,
    spec: PromptAgentSpec,
    settings: DeploymentSettings,
) -> Any:
    definition = build_prompt_definition(
        spec,
        settings.model_deployment,
        settings.bing_connection_id,
    )
    return client.agents.create_version(
        agent_name=spec.name,
        description=spec.description,
        definition=definition,
    )


def load_deployment_settings() -> DeploymentSettings:
    project_endpoint = os.getenv("PROJECT_ENDPOINT", "")
    model_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "").strip()
    bing_connection_id = os.getenv("BING_PROJECT_CONNECTION_ID", "").strip() or None
    missing = [
        name
        for name, value in (
            ("PROJECT_ENDPOINT", project_endpoint),
            ("AZURE_OPENAI_DEPLOYMENT_NAME", model_deployment),
        )
        if not value
    ]
    if missing:
        raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")
    if not FOUNDRY_PROJECT_ENDPOINT_PATTERN.fullmatch(project_endpoint):
        raise ConfigError("PROJECT_ENDPOINT must be a Foundry project endpoint")
    return DeploymentSettings(
        project_endpoint=project_endpoint,
        model_deployment=model_deployment,
        bing_connection_id=bing_connection_id,
    )


def create_client(settings: DeploymentSettings) -> AIProjectClient:
    return AIProjectClient(
        endpoint=settings.project_endpoint,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )


def _format_result(agent: Any) -> str:
    identity = getattr(agent, "instance_identity", None)
    endpoint = getattr(agent, "agent_endpoint", None)
    return (
        f"{agent.name} version={agent.version} "
        f"identity={'present' if identity else 'not returned'} "
        f"endpoint={endpoint or 'not returned'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--deploy", action="store_true")
    parser.add_argument("--agent")
    args = parser.parse_args(argv)

    specs = load_prompt_agent_specs(CONFIG_PATH)
    settings = load_deployment_settings()
    if args.agent:
        specs = [spec for spec in specs if spec.name == args.agent]
        if not specs:
            parser.error(f"Unknown agent: {args.agent}")

    for spec in specs:
        build_prompt_definition(
            spec,
            settings.model_deployment,
            settings.bing_connection_id,
        )

    if args.validate:
        print(f"Validated {len(specs)} Prompt agent definitions")
        return 0
    if args.dry_run:
        for spec in specs:
            print(f"Would create {spec.name} with tools={list(spec.tools)}")
        return 0

    client = create_client(settings)
    for spec in specs:
        print(_format_result(deploy_prompt_agent(client, spec, settings)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
