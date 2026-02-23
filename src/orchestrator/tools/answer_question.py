"""
answer_question tool handler for Azure AI Agent Service.

This is a STATELESS tool that answers travel questions by routing to specialized
domain agents or using the QA LLM directly. It can optionally receive workflow
context for grounded, relevant answers.

Per design doc Tool Definitions section (Tool 2: answer_question).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.orchestrator.tools.workflow_turn import ToolResponse
from src.shared.a2a.client_wrapper import (
    A2AClientError,
    A2AClientWrapper,
    A2AConnectionError,
    A2ATimeoutError,
)
from src.shared.a2a.registry import AgentRegistry

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Domain Classification Constants
# ═══════════════════════════════════════════════════════════════════════════════

# Domain agents that support Q&A mode (per design doc)
DOMAIN_AGENTS: frozenset[str] = frozenset({"poi", "stay", "transport", "events", "dining"})

# Valid domain values (all domains including non-agent ones)
VALID_DOMAINS: frozenset[str] = frozenset(
    {"general", "poi", "stay", "transport", "events", "dining", "budget"}
)

# Default domain when not specified
DEFAULT_DOMAIN = "general"


# ═══════════════════════════════════════════════════════════════════════════════
# Q&A Request Building
# ═══════════════════════════════════════════════════════════════════════════════


def build_qa_request(
    question: str,
    context: dict[str, Any] | None = None,
) -> str:
    """Build a Q&A mode request for domain agents.

    Per design doc Tool 2 implementation, this creates a JSON request
    that domain agents can parse to detect Q&A mode.

    Args:
        question: The user's question
        context: Optional workflow context for grounded answers

    Returns:
        JSON string with mode="qa" and the question
    """
    request: dict[str, Any] = {
        "mode": "qa",  # Signals Q&A mode (not planning mode)
        "question": question,
    }
    if context:
        request["context"] = context
    return json.dumps(request)


# ═══════════════════════════════════════════════════════════════════════════════
# Answer Question Handler
# ═══════════════════════════════════════════════════════════════════════════════


async def answer_question(
    question: str,
    domain: str | None = None,
    context: dict[str, Any] | None = None,
    *,
    a2a_client: A2AClientWrapper | None = None,
    agent_registry: AgentRegistry | None = None,
) -> ToolResponse:
    """
    Answer a travel question, optionally routing to specialized agents.

    This is a STATELESS tool - it does not modify workflow state.

    Per design doc Tool Definitions section (Tool 2: answer_question):
    - Routes to specialized agents (poi, stay, transport, events, dining) in Q&A mode
    - General/budget questions use the QA LLM directly
    - Returns ToolResponse envelope for consistency with other tools

    Args:
        question: The user's question (required)
        domain: Knowledge domain to ground the answer. One of:
            general, poi, stay, transport, events, dining, budget.
            If omitted, defaults to "general".
        context: Optional workflow context for grounded answers:
            - destination: Trip destination (e.g., "Tokyo")
            - dates: Trip dates (e.g., "March 10-17, 2026")
            - trip_spec: Full TripSpec object
            - itinerary: Current itinerary for context-aware answers
        a2a_client: Optional A2AClientWrapper for testing (creates new if not provided)
        agent_registry: Optional AgentRegistry for testing (loads from env if not provided)

    Returns:
        ToolResponse envelope with:
            - success: True if question was answered
            - message: The answer text
            - data: {"domain": domain} if domain was specified

    Usage:
        # Outside workflow - called directly with no context
        response = await answer_question("What's the weather like in Tokyo in March?")

        # Inside workflow - workflow_turn calls it WITH context
        response = await answer_question(
            "Does my hotel have a gym?",
            domain="stay",
            context={"trip_spec": trip_spec, "itinerary": itinerary}
        )
    """
    # Validate question
    if not question or not question.strip():
        return ToolResponse.error(
            message="Question is required for answer_question",
            error_code="MISSING_QUESTION",
        )

    # Normalize domain
    effective_domain = (domain or DEFAULT_DOMAIN).lower()
    if effective_domain not in VALID_DOMAINS:
        logger.warning(
            "Invalid domain '%s', falling back to '%s'",
            domain,
            DEFAULT_DOMAIN,
        )
        effective_domain = DEFAULT_DOMAIN

    logger.info(
        "answer_question called: domain=%s, question=%s, has_context=%s",
        effective_domain,
        question[:50] + "..." if len(question) > 50 else question,
        context is not None,
    )

    # Route based on domain
    if effective_domain in DOMAIN_AGENTS:
        # Route to specialized domain agent in Q&A mode
        return await _route_to_domain_agent(
            question=question,
            domain=effective_domain,
            context=context,
            a2a_client=a2a_client,
            agent_registry=agent_registry,
        )
    else:
        # General/budget questions → LLM call (stub for now)
        return await _answer_with_llm(
            question=question,
            domain=effective_domain,
            context=context,
        )


async def _route_to_domain_agent(
    question: str,
    domain: str,
    context: dict[str, Any] | None,
    a2a_client: A2AClientWrapper | None = None,
    agent_registry: AgentRegistry | None = None,
) -> ToolResponse:
    """Route question to specialized domain agent in Q&A mode.

    Args:
        question: The user's question
        domain: One of: poi, stay, transport, events, dining
        context: Optional workflow context
        a2a_client: Optional pre-configured client
        agent_registry: Optional registry for agent URLs

    Returns:
        ToolResponse with answer from domain agent
    """
    # Get or create registry
    if agent_registry is None:
        agent_registry = AgentRegistry.load()

    # Get agent configuration
    try:
        agent_config = agent_registry.get(domain)
    except ValueError as e:
        logger.error("Unknown domain agent: %s", domain)
        return ToolResponse.error(
            message=f"Unknown domain: {domain}",
            error_code="UNKNOWN_DOMAIN",
        )

    # Build Q&A request
    qa_request = build_qa_request(question, context)

    # Send to domain agent
    try:
        if a2a_client is not None:
            # Use provided client (for testing)
            response = await a2a_client.send_message(
                agent_url=agent_config.url,
                message=qa_request,
                context_id=None,  # Stateless question
                history=[],  # No history needed
            )
        else:
            # Create new client for this request
            async with A2AClientWrapper(timeout_seconds=agent_config.timeout) as client:
                response = await client.send_message(
                    agent_url=agent_config.url,
                    message=qa_request,
                    context_id=None,  # Stateless question
                    history=[],  # No history needed
                )

        logger.info(
            "Received answer from %s agent: %s chars",
            domain,
            len(response.text) if response.text else 0,
        )

        # Return answer in ToolResponse envelope
        return ToolResponse(
            success=True,
            message=response.text,
            data={"domain": domain},
        )

    except A2AConnectionError as e:
        logger.error("Connection error to %s agent: %s", domain, e)
        return ToolResponse.error(
            message=f"Could not connect to {domain} agent. Please try again later.",
            error_code="AGENT_CONNECTION_ERROR",
        )

    except A2ATimeoutError as e:
        logger.error("Timeout calling %s agent: %s", domain, e)
        return ToolResponse.error(
            message=f"The {domain} agent took too long to respond. Please try again.",
            error_code="AGENT_TIMEOUT",
        )

    except A2AClientError as e:
        logger.error("A2A error from %s agent: %s", domain, e)
        return ToolResponse.error(
            message=f"Error communicating with {domain} agent: {e}",
            error_code="AGENT_ERROR",
        )


async def _answer_with_llm(
    question: str,
    domain: str,
    context: dict[str, Any] | None,
) -> ToolResponse:
    """Answer general/budget questions using LLM directly.

    Uses the OrchestratorLLM's QA agent for text generation.

    Args:
        question: The user's question
        domain: Either "general" or "budget"
        context: Optional workflow context

    Returns:
        ToolResponse with answer
    """
    logger.info(
        "Answering %s question via LLM: %s",
        domain,
        question[:50] + "..." if len(question) > 50 else question,
    )

    chit_chat_response = _maybe_handle_chitchat(question, context)
    if chit_chat_response:
        return ToolResponse(
            success=True,
            message=chit_chat_response,
            data={"domain": domain},
        )

    prompt = _build_qa_prompt(question=question, domain=domain, context=context)
    llm = _get_llm()
    if llm is None:
        fallback = _build_fallback_answer(question=question, domain=domain, context=context)
        return ToolResponse(
            success=True,
            message=fallback,
            data={"domain": domain},
        )

    try:
        from src.orchestrator.azure_agent import AgentType

        session_id = _resolve_qa_session_id(context)
        thread_id = llm.ensure_thread_exists(session_id, AgentType.QA)
        run_result = await llm.create_run(
            thread_id=thread_id,
            agent_type=AgentType.QA,
            message=prompt,
        )

        if run_result.is_completed and run_result.text_response:
            answer = run_result.text_response
        elif run_result.has_failed:
            logger.error("QA LLM failed: %s", run_result.error_message)
            answer = _build_fallback_answer(
                question=question,
                domain=domain,
                context=context,
            )
        else:
            logger.warning("QA LLM returned unexpected state: %s", run_result.status)
            answer = _build_fallback_answer(
                question=question,
                domain=domain,
                context=context,
            )

        return ToolResponse(
            success=True,
            message=answer,
            data={"domain": domain},
        )
    except Exception as e:
        logger.error("Error calling QA LLM: %s", e)
        fallback = _build_fallback_answer(question=question, domain=domain, context=context)
        return ToolResponse(
            success=True,
            message=fallback,
            data={"domain": domain},
        )


def _normalize_question(text: str) -> str:
    """Normalize user text for simple intent checks."""
    normalized = " ".join(text.lower().strip().split())
    return normalized.strip("!?.,:;")


def _maybe_handle_chitchat(
    question: str,
    context: dict[str, Any] | None,
) -> str | None:
    """Return a canned response for greetings or capability questions."""
    normalized = _normalize_question(question)
    if not normalized:
        return None

    greetings = (
        "hi",
        "hello",
        "hey",
        "hiya",
        "yo",
        "sup",
        "good morning",
        "good afternoon",
        "good evening",
    )
    if normalized in greetings or any(
        normalized.startswith(f"{greeting} ") for greeting in greetings
    ):
        return _build_greeting_response(context)

    capability_phrases = (
        "what can you do",
        "what can you help with",
        "what can you help me with",
        "what do you do",
        "who are you",
        "what are you",
        "what kind of agent are you",
        "what kind of assistant are you",
        "what kind of agent",
        "what kind of assistant",
        "how can you help",
        "how can you assist",
        "what do you help with",
        "can you help",
        "can you help me",
        "what is this",
        "what is this agent",
        "what is this assistant",
    )
    if normalized in capability_phrases or any(
        normalized.startswith(f"{phrase} ") for phrase in capability_phrases
    ):
        return _build_capabilities_response(context)

    return None


def _build_greeting_response(context: dict[str, Any] | None) -> str:
    """Return a friendly greeting with optional context hint."""
    context_hint = _build_context_hint(context)
    if context_hint:
        return (
            "Hi! I'm your travel planning assistant. "
            f"{context_hint} How can I help?"
        )
    return (
        "Hi! I'm your travel planning assistant. "
        "I can plan trips, answer travel questions, and help with bookings. "
        "How can I help?"
    )


def _build_capabilities_response(context: dict[str, Any] | None) -> str:
    """Return a short capabilities blurb with an invitation to proceed."""
    context_hint = _build_context_hint(context)
    if context_hint:
        return (
            "I'm the travel planning orchestrator. I can help plan trips end-to-end, "
            "answer travel questions, and coordinate options for flights, stays, "
            "activities, and dining. "
            f"{context_hint}"
        )
    return (
        "I'm the travel planning orchestrator. I can help plan trips end-to-end, "
        "answer travel questions, and coordinate options for flights, stays, "
        "activities, and dining. Share a destination and dates to get started."
    )


def _build_context_hint(context: dict[str, Any] | None) -> str:
    """Create a short context hint for greetings/capabilities."""
    if not context:
        return ""
    destination = context.get("destination")
    dates = context.get("dates")
    if destination and dates:
        return (
            f"If you'd like to continue planning your trip to {destination} "
            f"({dates}), just tell me what you need."
        )
    if destination:
        return f"If you'd like to continue planning your trip to {destination}, just tell me what you need."
    return ""


def _build_qa_prompt(
    question: str,
    domain: str,
    context: dict[str, Any] | None,
) -> str:
    """Build the prompt sent to the QA agent."""
    parts: list[str] = []
    if domain == "budget":
        parts.append(
            "This is a budget-focused travel question. Provide ranges, assumptions, and key cost drivers."
        )
    parts.append(f"Question: {question}")
    if context:
        context_json = json.dumps(context, ensure_ascii=True, sort_keys=True, default=str)
        parts.append(f"Context: {context_json}")
    return "\n\n".join(parts)


def _build_fallback_answer(
    question: str,
    domain: str,
    context: dict[str, Any] | None,
) -> str:
    """Fallback response when QA LLM is unavailable."""
    context_info = ""
    if context:
        if "destination" in context:
            context_info += f" for {context['destination']}"
        if "dates" in context:
            context_info += f" during {context['dates']}"

    if domain == "budget":
        return (
            f"Budget guidance{context_info}: I can help estimate costs, but I need "
            "a bit more detail on your preferences and trip style. "
            "Share your destination, dates, and budget range."
        )
    return (
        f"Happy to help{context_info}. Ask me about destinations, flights, stays, "
        "activities, or timing, and I can provide travel guidance."
    )


def _get_llm() -> "OrchestratorLLM | None":
    """Create an OrchestratorLLM instance from env config if available."""
    try:
        from src.orchestrator.agent import OrchestratorLLM
        from src.orchestrator.azure_agent import ConfigurationError, load_agent_config
    except Exception as exc:
        logger.debug("LLM helpers unavailable: %s", exc)
        return None

    try:
        config = load_agent_config()
    except ConfigurationError as exc:
        logger.info("Azure LLM not configured: %s", exc)
        return None

    return OrchestratorLLM(config)


def _resolve_qa_session_id(context: dict[str, Any] | None) -> str:
    """Resolve a QA session ID for thread management."""
    if context and isinstance(context, dict):
        session_id = context.get("session_id")
        if isinstance(session_id, str) and session_id.strip():
            return session_id
    return "qa_stateless"
