import pytest

from interoperability.foundry_new_format.hosted_agents.stay.main import (
    create_agent,
    require_env,
)


def test_require_env_rejects_missing_value(monkeypatch) -> None:
    monkeypatch.delenv("FOUNDRY_PROJECT_ENDPOINT", raising=False)

    with pytest.raises(RuntimeError, match="FOUNDRY_PROJECT_ENDPOINT"):
        require_env("FOUNDRY_PROJECT_ENDPOINT")


def test_create_agent_uses_foundry_client_and_structured_output(monkeypatch) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example/project")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4.1")
    monkeypatch.setenv("TOOLBOX_NAME", "travel-search")

    agent = create_agent(credential=object(), client=object(), toolbox=object())

    assert agent.name == "TravelPlannerStay"
    assert agent.default_options["store"] is False
    assert agent.default_options["response_format"] is not None
    assert agent.default_options["tools"] is not None
