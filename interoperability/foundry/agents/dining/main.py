"""
Dining Agent - Hosted Agent Entry Point (LangGraph)

This module implements the Dining agent directly with LangGraph, reusing the
shared dining prompt and structured output schema for Azure AI Foundry hosting.

Design doc references:
- Appendix A.2 lines 1527-1646: Hosted Agents patterns (Agent Framework & LangGraph)
- Architecture lines 64-69: "wrap, don't rewrite" principle
"""

import json
import logging
import os
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv

def _find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "src").exists() and (candidate / "interoperability").exists():
            return candidate
    return start.parent


ROOT_DIR = _find_repo_root(Path(__file__).resolve())
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

load_dotenv()

if not os.getenv("AZURE_AI_PROJECT_ENDPOINT") and os.getenv("PROJECT_ENDPOINT"):
    os.environ["AZURE_AI_PROJECT_ENDPOINT"] = os.environ["PROJECT_ENDPOINT"]

from azure.ai.agentserver.langgraph import LangGraphAdapter
from azure.ai.agentserver.langgraph._context import LanggraphRunContext
from azure.ai.agentserver.langgraph.models.human_in_the_loop_json_helper import (
    HumanInTheLoopJsonHelper,
)
from azure.ai.agentserver.langgraph.models.response_api_default_converter import (
    ResponseAPIDefaultConverter,
)
from azure.ai.agentserver.langgraph.models.response_api_non_stream_response_converter import (
    ResponseAPIMessagesNonStreamResponseConverter,
)
from azure.ai.agentserver.langgraph.tools._context import FoundryToolContext
from azure.ai.agentserver.langgraph.tools import FoundryToolLateBindingChatModel
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, MessagesState, StateGraph

from src.shared.models import DiningResponse
from src.shared.utils.load_prompt import load_prompt

def _configure_logging() -> logging.Logger:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    logging.basicConfig(
        level=log_level,
        handlers=handlers,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info("Logging to stdout only")
    for noisy_logger in (
        "azure.core.pipeline.policies.http_logging_policy",
        "azure.identity",
        "azure.monitor.opentelemetry.exporter.export._base",
        "httpx",
        "httpcore",
        "urllib3",
        "openai",
        "langsmith",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    return logger


logger = _configure_logging()

LOG_PREFIX = "[DINING-CONFIG]"

logger.info(
    "Dining agent module loaded (pid=%s, python=%s)",
    os.getpid(),
    platform.python_version(),
)

SYSTEM_PROMPT = load_prompt("dining")


class DiningState(MessagesState):
    pass


def _build_model():
    env_aoai_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
    env_aoai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment_name = env_aoai_deployment or "gpt-4o-mini"
    api_version = os.getenv(
        "AZURE_OPENAI_API_VERSION",
        os.getenv("OPENAI_API_VERSION"),
    )
    logger.info(
        "%s Azure OpenAI config: AZURE_OPENAI_ENDPOINT=%s AZURE_OPENAI_DEPLOYMENT_NAME=%s AZURE_OPENAI_API_VERSION=%s",
        LOG_PREFIX,
        env_aoai_endpoint or "<unset>",
        env_aoai_deployment or "<unset>",
        api_version or "<unset>",
    )
    logger.info("%s Azure OpenAI deployment resolved to %s", LOG_PREFIX, deployment_name)
    if not api_version:
        raise RuntimeError(
            "AZURE_OPENAI_API_VERSION (or OPENAI_API_VERSION) must be set to "
            "initialize the Azure OpenAI chat model."
        )
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )
    return init_chat_model(
        f"azure_openai:{deployment_name}",
        azure_ad_token_provider=token_provider,
        api_version=api_version,
    )


def _build_foundry_tools() -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for env_name in ("BING_PROJECT_CONNECTION_ID", "AZURE_AI_PROJECT_TOOL_CONNECTION_ID"):
        connection_id = os.getenv(env_name)
        if connection_id:
            tools.append(
                {
                    "type": "mcp",
                    "project_connection_id": connection_id,
                }
            )

    if not tools:
        logger.warning(
            "No MCP tool connection configured. Web search tools will be unavailable."
        )
    return tools


_base_model = _build_model()
_foundry_tools = _build_foundry_tools()
if _foundry_tools and not (
    os.getenv("AZURE_AI_PROJECT_ENDPOINT") or os.getenv("PROJECT_ENDPOINT")
):
    raise RuntimeError(
        "AZURE_AI_PROJECT_ENDPOINT (or PROJECT_ENDPOINT) must be set when Foundry tools are enabled."
    )
_tool_model = FoundryToolLateBindingChatModel(
    delegate=_base_model,
    runtime=None,
    foundry_tools=_foundry_tools,
)
_tool_node = _tool_model.tool_node
_structured_model = _base_model.with_structured_output(DiningResponse)


def _system_messages() -> list[BaseMessage]:
    return [SystemMessage(content=SYSTEM_PROMPT)]


def call_model(state: DiningState, config: RunnableConfig) -> dict[str, Any]:
    messages = state.get("messages") or []
    if not messages:
        error_payload = DiningResponse(
            dining_output=None,
            response=(
                "No user message provided. Please provide a query about restaurants "
                "or dining options."
            ),
        )
        return {"messages": [AIMessage(content=error_payload.model_dump_json())]}

    response = _tool_model.invoke(_system_messages() + messages, config=config)
    tool_calls = getattr(response, "tool_calls", None)
    if tool_calls:
        return {"messages": [response]}

    try:
        result = _structured_model.invoke(
            _system_messages() + messages + [response],
            config=config,
        )
        if isinstance(result, DiningResponse):
            content = result.model_dump_json()
        else:
            content = json.dumps(result)
        return {"messages": [AIMessage(content=content)]}
    except Exception:
        logger.exception("Failed to generate structured dining response")
        fallback = DiningResponse(
            dining_output=None,
            response="We were unable to process your request. Please try again.",
        )
        return {"messages": [AIMessage(content=fallback.model_dump_json())]}


def should_continue(state: DiningState) -> Literal["tools", END]:
    last_message = state["messages"][-1]
    tool_calls = getattr(last_message, "tool_calls", None)
    if tool_calls:
        return "tools"
    return END


def build_graph() -> StateGraph:
    workflow = StateGraph(DiningState)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", _tool_node)

    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            END: END,
        },
    )
    workflow.add_edge("tools", "agent")
    return workflow.compile()


app = build_graph()


class DiningLangGraphAdapter(LangGraphAdapter):
    async def setup_lg_run_context(self, agent_run_context):
        if not _foundry_tools:
            return LanggraphRunContext(agent_run_context, FoundryToolContext())
        return await super().setup_lg_run_context(agent_run_context)


class DiningNonStreamResponseConverter(ResponseAPIMessagesNonStreamResponseConverter):
    def convert(self, output):
        if not isinstance(output, list):
            return super().convert(output)

        last_assistant = None
        for step in output:
            for node_output in step.values():
                message_arr = node_output.get("messages")
                if not message_arr:
                    continue
                for message in message_arr:
                    if isinstance(message, AIMessage) and not message.tool_calls:
                        last_assistant = message

        if last_assistant is None:
            return super().convert(output)

        converted = self.convert_output_message(last_assistant)
        return [converted] if converted else []


def _create_non_stream_response_converter(context: LanggraphRunContext):
    hitl_helper = HumanInTheLoopJsonHelper(context)
    return DiningNonStreamResponseConverter(context, hitl_helper)


_response_converter = ResponseAPIDefaultConverter(
    graph=app,
    create_non_stream_response_converter=_create_non_stream_response_converter,
)


def main() -> None:
    port = int(os.getenv("PORT", os.getenv("DEFAULT_AD_PORT", "8088")))
    logger.info("Starting Dining agent server on port %s", port)
    DiningLangGraphAdapter(app, converter=_response_converter).run(port=port)


if __name__ == "__main__":
    main()
