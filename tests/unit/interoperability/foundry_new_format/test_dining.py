import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from interoperability.foundry_new_format.hosted_agents.dining.main import (
    AzureTokenAuth,
    build_graph,
    create_app,
    extract_final_text,
    load_toolbox_tools,
    require_env,
    to_langchain_messages,
)


def test_converts_platform_history_to_langchain_messages() -> None:
    history = [
        {"role": "user", "text": "Find dinner"},
        {"role": "assistant", "text": "Which city?"},
    ]

    assert to_langchain_messages(history, "Paris") == [
        HumanMessage(content="Find dinner"),
        AIMessage(content="Which city?"),
        HumanMessage(content="Paris"),
    ]


def test_extracts_string_and_block_content() -> None:
    assert extract_final_text(AIMessage(content="done")) == "done"
    assert (
        extract_final_text(
            AIMessage(content=[{"type": "text", "text": "first"}, {"text": " second"}])
        )
        == "first second"
    )


def test_requires_versioned_toolbox_endpoint(monkeypatch) -> None:
    monkeypatch.delenv("TOOLBOX_ENDPOINT", raising=False)

    with pytest.raises(RuntimeError, match="TOOLBOX_ENDPOINT"):
        require_env("TOOLBOX_ENDPOINT")


def test_azure_token_auth_uses_injected_bearer_token_provider() -> None:
    request = httpx.Request("GET", "https://example.test/mcp")
    auth = AzureTokenAuth(token_provider=lambda: "issued-token")

    prepared = next(auth.auth_flow(request))

    assert prepared.headers["Authorization"] == "Bearer issued-token"


@pytest.mark.asyncio
async def test_build_graph_uses_structured_response_without_contacting_foundry(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://project.example")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4.1")
    captured = {}

    def chat_model_factory(**kwargs):
        captured["chat"] = kwargs
        return "chat-model"

    def graph_factory(model, *, tools, prompt, response_format):
        captured["graph"] = {
            "model": model,
            "tools": tools,
            "prompt": prompt,
            "response_format": response_format,
        }
        return "graph"

    async with build_graph(
        ["search-tool"],
        chat_model_factory=chat_model_factory,
        graph_factory=graph_factory,
    ) as graph:
        assert graph == "graph"
    assert captured["chat"]["base_url"] == "https://project.example/openai/v1"
    assert captured["chat"]["model"] == "gpt-4.1"
    assert captured["graph"]["tools"] == ["search-tool"]
    assert captured["graph"]["response_format"].__name__ == "DiningResponse"


@pytest.mark.asyncio
async def test_build_graph_closes_http_clients_when_context_exits(monkeypatch) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://project.example")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4.1")
    captured = {}

    def chat_model_factory(**kwargs):
        captured["chat"] = kwargs
        return "chat-model"

    def graph_factory(*args, **kwargs):
        return "graph"

    async with build_graph(
        ["search-tool"],
        chat_model_factory=chat_model_factory,
        graph_factory=graph_factory,
    ) as graph:
        assert graph == "graph"
        sync_client = captured["chat"]["http_client"]
        async_client = captured["chat"]["http_async_client"]
        assert not sync_client.is_closed
        assert not async_client.is_closed

    assert sync_client.is_closed
    assert async_client.is_closed


@pytest.mark.asyncio
async def test_build_graph_closes_its_azure_credential_when_context_exits(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://project.example")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4.1")

    class Credential:
        closed = False

        def close(self) -> None:
            self.closed = True

    credential = Credential()
    monkeypatch.setattr(
        "interoperability.foundry_new_format.hosted_agents.dining.main.DefaultAzureCredential",
        lambda: credential,
    )
    monkeypatch.setattr(
        "interoperability.foundry_new_format.hosted_agents.dining.main.get_bearer_token_provider",
        lambda *_: lambda: "issued-token",
    )

    async with build_graph(
        [],
        chat_model_factory=lambda **_: "chat-model",
        graph_factory=lambda *_args, **_kwargs: "graph",
    ):
        assert not credential.closed

    assert credential.closed


@pytest.mark.asyncio
async def test_load_toolbox_tools_uses_injected_client_and_bearer_token(monkeypatch) -> None:
    monkeypatch.setenv("TOOLBOX_ENDPOINT", "https://toolbox.example/mcp")
    captured = {}

    class ToolboxClient:
        def __init__(self, connections) -> None:
            captured["connections"] = connections

        async def get_tools(self):
            return ["search-tool"]

    assert await load_toolbox_tools(
        token_provider=lambda: "issued-token",
        client_factory=ToolboxClient,
    ) == ["search-tool"]
    assert captured["connections"] == {
        "travel-search": {
            "transport": "streamable_http",
            "url": "https://toolbox.example/mcp",
            "headers": {"Authorization": "Bearer issued-token"},
        }
    }


@pytest.mark.asyncio
async def test_load_toolbox_tools_closes_its_azure_credential(monkeypatch) -> None:
    monkeypatch.setenv("TOOLBOX_ENDPOINT", "https://toolbox.example/mcp")

    class Credential:
        closed = False

        def close(self) -> None:
            self.closed = True

    class ToolboxClient:
        def __init__(self, connections) -> None:
            self.connections = connections

        async def get_tools(self):
            return []

    credential = Credential()
    monkeypatch.setattr(
        "interoperability.foundry_new_format.hosted_agents.dining.main.DefaultAzureCredential",
        lambda: credential,
    )
    monkeypatch.setattr(
        "interoperability.foundry_new_format.hosted_agents.dining.main.get_bearer_token_provider",
        lambda *_: lambda: "issued-token",
    )

    assert await load_toolbox_tools(client_factory=ToolboxClient) == []
    assert credential.closed


def test_create_app_disables_sdk_observability_for_source_safe_import() -> None:
    captured = {}

    def host_factory(*, options, configure_observability):
        captured["options"] = options
        captured["configure_observability"] = configure_observability
        return "app"

    assert create_app(host_factory=host_factory) == "app"
    assert captured["options"].default_fetch_history_count == 20
    assert captured["configure_observability"] is None
