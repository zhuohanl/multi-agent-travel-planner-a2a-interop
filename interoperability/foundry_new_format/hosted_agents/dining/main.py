from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Generator
from contextlib import asynccontextmanager, closing
from typing import Any

import httpx
from azure.ai.agentserver.responses import (
    CreateResponse,
    ResponseContext,
    ResponsesAgentServerHost,
    ResponsesServerOptions,
    TextResponse,
)
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from shared.prompt_loader import load_prompt
from shared.schemas import DiningResponse

_AZURE_AI_SCOPE = "https://ai.azure.com/.default"


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} environment variable must be set")
    return value


class AzureTokenAuth(httpx.Auth):
    def __init__(
        self,
        *,
        credential: DefaultAzureCredential | None = None,
        token_provider: Callable[[], str] | None = None,
    ) -> None:
        self._provider = token_provider or get_bearer_token_provider(
            credential or DefaultAzureCredential(),
            _AZURE_AI_SCOPE,
        )

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, None, None]:
        request.headers["Authorization"] = f"Bearer {self._provider()}"
        yield request


@asynccontextmanager
async def build_graph(
    tools: list[Any],
    *,
    chat_model_factory: Callable[..., Any] = ChatOpenAI,
    graph_factory: Callable[..., Any] = create_react_agent,
) -> AsyncIterator[Any]:
    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(credential, _AZURE_AI_SCOPE)
    with closing(credential), httpx.Client(
        auth=AzureTokenAuth(token_provider=token_provider)
    ) as http_client:
        async with httpx.AsyncClient(
            auth=AzureTokenAuth(token_provider=token_provider)
        ) as http_async_client:
            llm = chat_model_factory(
                base_url=f"{require_env('FOUNDRY_PROJECT_ENDPOINT')}/openai/v1",
                api_key=token_provider,
                model=require_env("AZURE_AI_MODEL_DEPLOYMENT_NAME"),
                use_responses_api=True,
                http_client=http_client,
                http_async_client=http_async_client,
            )
            yield graph_factory(
                llm,
                tools=tools,
                prompt=load_prompt("dining"),
                response_format=DiningResponse,
            )


async def load_toolbox_tools(
    *,
    token_provider: Callable[[], str] | None = None,
    client_factory: Callable[..., Any] = MultiServerMCPClient,
) -> list[Any]:
    credential = None
    if token_provider is None:
        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(credential, _AZURE_AI_SCOPE)
    client = client_factory(
        {
            "travel-search": {
                "transport": "streamable_http",
                "url": require_env("TOOLBOX_ENDPOINT"),
                "headers": {"Authorization": f"Bearer {token_provider()}"},
            }
        }
    )
    return await close_after(client.get_tools(), credential)


async def close_after(awaitable: Any, credential: DefaultAzureCredential | None) -> Any:
    try:
        return await awaitable
    finally:
        if credential is not None:
            credential.close()


def to_langchain_messages(
    history: list[dict[str, str]],
    user_input: str,
) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for item in history:
        message_type = HumanMessage if item["role"] == "user" else AIMessage
        messages.append(message_type(content=item["text"]))
    messages.append(HumanMessage(content=user_input))
    return messages


def extract_final_text(message: AIMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return "".join(
        block.get("text", "") if isinstance(block, dict) else str(block)
        for block in message.content
    ).strip()


def create_app(
    *,
    host_factory: Callable[..., Any] = ResponsesAgentServerHost,
) -> Any:
    return host_factory(
        options=ResponsesServerOptions(default_fetch_history_count=20),
        configure_observability=None,
    )


app = create_app()


@app.response_handler
async def handle(
    request: CreateResponse,
    context: ResponseContext,
    cancellation_signal: asyncio.Event,
) -> TextResponse:
    del cancellation_signal
    platform_history = await context.get_history()
    history = [
        {"role": item.role, "text": content.text}
        for item in platform_history
        for content in getattr(item, "content", [])
        if getattr(content, "text", None)
    ]
    tools = await load_toolbox_tools()
    async with build_graph(tools) as graph:
        result = await graph.ainvoke(
            {
                "messages": to_langchain_messages(
                    history,
                    await context.get_input_text() or "",
                )
            }
        )
    structured_response = result.get("structured_response")
    if isinstance(structured_response, DiningResponse):
        text = structured_response.model_dump_json()
    else:
        text = extract_final_text(result["messages"][-1])
    return TextResponse(context, request, text=text)


if __name__ == "__main__":
    app.run()
