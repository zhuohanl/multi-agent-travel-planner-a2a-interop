from pathlib import Path
from unittest.mock import Mock

import pytest

from interoperability.foundry_new_format.deploy_prompt_agents import (
    DeploymentSettings,
    build_prompt_definition,
    deploy_prompt_agent,
    load_deployment_settings,
    main,
)
from interoperability.foundry_new_format.shared.config import (
    ConfigError,
    PromptAgentSpec,
)


def make_spec(tmp_path: Path, *tools: str) -> PromptAgentSpec:
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("Be helpful.", encoding="utf-8")
    return PromptAgentSpec(
        name="travel-planner-test",
        description="Test travel agent",
        prompt_path=prompt_path,
        tools=tools,
    )


def test_builds_prompt_definition_without_tools(tmp_path: Path) -> None:
    definition = build_prompt_definition(make_spec(tmp_path), "gpt-4.1", None)

    assert definition.model == "gpt-4.1"
    assert definition.instructions == "Be helpful."
    assert definition.tools == []


def test_builds_bing_grounding_tool(tmp_path: Path) -> None:
    definition = build_prompt_definition(
        make_spec(tmp_path, "bing_grounding"),
        "gpt-4.1",
        "bing-connection-id",
    )

    assert len(definition.tools) == 1
    assert definition.tools[0].type == "bing_grounding"
    assert definition.as_dict() == {
        "model": "gpt-4.1",
        "instructions": "Be helpful.",
        "tools": [
            {
                "bing_grounding": {
                    "search_configurations": [
                        {"project_connection_id": "bing-connection-id"}
                    ]
                },
                "type": "bing_grounding",
            }
        ],
        "kind": "prompt",
    }


def test_rejects_bing_grounding_without_connection(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="BING_PROJECT_CONNECTION_ID"):
        build_prompt_definition(
            make_spec(tmp_path, "bing_grounding"),
            "gpt-4.1",
            None,
        )


def test_deploys_under_new_name(tmp_path: Path) -> None:
    spec = make_spec(tmp_path)
    client = Mock()
    client.agents.create_version.return_value = Mock()
    result_model = client.agents.create_version.return_value
    result_model.id = "agent-id"
    result_model.name = spec.name
    result_model.version = "1"
    result_model.instance_identity = {"principal_id": "principal-id"}
    result_model.agent_endpoint = "https://example/agents/travel-planner-test/endpoint"

    result = deploy_prompt_agent(
        client,
        spec,
        DeploymentSettings(
            project_endpoint="https://account.services.ai.azure.com/api/projects/project",
            model_deployment="gpt-4.1",
            bing_connection_id=None,
        ),
    )

    client.agents.create_version.assert_called_once_with(
        agent_name="travel-planner-test",
        description="Test travel agent",
        definition=client.agents.create_version.call_args.kwargs["definition"],
    )
    definition = client.agents.create_version.call_args.kwargs["definition"]
    assert definition.as_dict() == {
        "model": "gpt-4.1",
        "instructions": "Be helpful.",
        "tools": [],
        "kind": "prompt",
    }
    assert result.name == "travel-planner-test"
    assert result.version == "1"


def test_settings_require_project_endpoint(monkeypatch) -> None:
    monkeypatch.delenv("PROJECT_ENDPOINT", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4.1")

    with pytest.raises(ConfigError, match="PROJECT_ENDPOINT"):
        load_deployment_settings()


def test_settings_reject_non_foundry_project_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("PROJECT_ENDPOINT", "not-a-url/api/projects/project")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4.1")

    with pytest.raises(ConfigError, match="Foundry project endpoint"):
        load_deployment_settings()


def test_settings_reject_project_endpoint_with_extra_path(monkeypatch) -> None:
    monkeypatch.setenv(
        "PROJECT_ENDPOINT",
        "https://account.services.ai.azure.com/api/projects/project/extra",
    )
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4.1")

    with pytest.raises(ConfigError, match="Foundry project endpoint"):
        load_deployment_settings()


def test_settings_accepts_default_foundry_project_endpoint(monkeypatch) -> None:
    endpoint = "https://account.services.ai.azure.com/api/projects/_project"
    monkeypatch.setenv("PROJECT_ENDPOINT", endpoint)
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4.1")

    assert load_deployment_settings().project_endpoint == endpoint


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://account.services.ai.azure.com/api/projects/project/",
        "https://account.services.ai.azure.com/api/projects//project",
        "https://account.services.ai.azure.com/api/projects/project?x=1",
        "https://account.services.ai.azure.com/api/projects/project#part",
        "https://.services.ai.azure.com/api/projects/project",
        "https://user@account.services.ai.azure.com/api/projects/project",
        "https://account.services.ai.azure.com:443/api/projects/project",
        "https://account.services.ai.azure.com/api/projects/project%2Fextra",
        "https://account.services.ai.azure.com/api/projects/project name",
        "https://account.services.ai.azure.com\t/api/projects/project",
        "https://[account.services.ai.azure.com/api/projects/project",
        "\thttps://account.services.ai.azure.com/api/projects/project",
        "https://account.services.ai.azure.com/api/projects/project\n",
    ],
)
def test_settings_reject_noncanonical_project_endpoint(
    monkeypatch, endpoint: str
) -> None:
    monkeypatch.setenv("PROJECT_ENDPOINT", endpoint)
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4.1")

    with pytest.raises(ConfigError, match="Foundry project endpoint"):
        load_deployment_settings()


def test_validate_does_not_create_client(monkeypatch) -> None:
    monkeypatch.setenv(
        "PROJECT_ENDPOINT",
        "https://account.services.ai.azure.com/api/projects/project",
    )
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4.1")
    monkeypatch.setenv("BING_PROJECT_CONNECTION_ID", "bing-id")
    monkeypatch.setattr(
        "interoperability.foundry_new_format.deploy_prompt_agents.create_client",
        lambda settings: (_ for _ in ()).throw(
            AssertionError("client should not be created")
        ),
    )

    assert main(["--validate"]) == 0
