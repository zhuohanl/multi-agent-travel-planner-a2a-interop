"""
Unit tests for answer_question tool handler.

Tests cover:
- Tool registration and callable interface
- Domain validation and routing
- Q&A mode request building
- Domain agent routing
- ToolResponse envelope format
- Error handling for connection/timeout issues
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.orchestrator.tools.answer_question import (
    DEFAULT_DOMAIN,
    DOMAIN_AGENTS,
    VALID_DOMAINS,
    _answer_with_llm,
    _route_to_domain_agent,
    answer_question,
    build_qa_request,
)
from src.orchestrator.tools.workflow_turn import ToolResponse
from src.shared.a2a.client_wrapper import (
    A2AClientError,
    A2AClientWrapper,
    A2AConnectionError,
    A2AResponse,
    A2ATimeoutError,
)
from src.shared.a2a.registry import AgentConfig, AgentRegistry


# ═══════════════════════════════════════════════════════════════════════════════
# Constants Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestDomainConstants:
    """Tests for domain constants."""

    def test_domain_agents_is_frozenset(self):
        """Test DOMAIN_AGENTS is immutable."""
        assert isinstance(DOMAIN_AGENTS, frozenset)

    def test_domain_agents_contains_expected(self):
        """Test DOMAIN_AGENTS has all domain agents."""
        expected = {"poi", "stay", "transport", "events", "dining"}
        assert DOMAIN_AGENTS == expected

    def test_valid_domains_is_frozenset(self):
        """Test VALID_DOMAINS is immutable."""
        assert isinstance(VALID_DOMAINS, frozenset)

    def test_valid_domains_contains_all(self):
        """Test VALID_DOMAINS has all domains."""
        expected = {"general", "poi", "stay", "transport", "events", "dining", "budget"}
        assert VALID_DOMAINS == expected

    def test_domain_agents_is_subset_of_valid(self):
        """Test all domain agents are in valid domains."""
        assert DOMAIN_AGENTS.issubset(VALID_DOMAINS)

    def test_default_domain_is_general(self):
        """Test default domain is 'general'."""
        assert DEFAULT_DOMAIN == "general"


# ═══════════════════════════════════════════════════════════════════════════════
# build_qa_request Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildQaRequest:
    """Tests for Q&A request building."""

    def test_build_qa_request_basic(self):
        """Test basic Q&A request without context."""
        result = build_qa_request("What's the weather like?")
        parsed = json.loads(result)

        assert parsed["mode"] == "qa"
        assert parsed["question"] == "What's the weather like?"
        assert "context" not in parsed

    def test_build_qa_request_with_context(self):
        """Test Q&A request with context."""
        context = {
            "destination": "Tokyo",
            "dates": "March 10-17, 2026",
        }
        result = build_qa_request("Does my hotel have a pool?", context)
        parsed = json.loads(result)

        assert parsed["mode"] == "qa"
        assert parsed["question"] == "Does my hotel have a pool?"
        assert parsed["context"] == context

    def test_build_qa_request_with_full_context(self):
        """Test Q&A request with full workflow context."""
        context = {
            "destination": "Paris",
            "dates": "April 1-10, 2026",
            "trip_spec": {"num_travelers": 2, "budget_per_person": 3000},
            "itinerary": {"days": [{"activities": []}]},
        }
        result = build_qa_request("What are the best restaurants?", context)
        parsed = json.loads(result)

        assert parsed["context"]["trip_spec"]["num_travelers"] == 2
        assert parsed["context"]["itinerary"]["days"] == [{"activities": []}]

    def test_build_qa_request_is_valid_json(self):
        """Test output is always valid JSON."""
        result = build_qa_request("Test question with 'quotes' and \"double quotes\"")
        # Should not raise
        parsed = json.loads(result)
        assert "question" in parsed


# ═══════════════════════════════════════════════════════════════════════════════
# answer_question Tests - Basic Interface
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnswerQuestionInterface:
    """Tests for answer_question basic interface."""

    @pytest.mark.asyncio
    async def test_answer_question_is_async_callable(self):
        """Test that answer_question is an async callable."""
        assert callable(answer_question)
        # Can call it (will use LLM stub)
        result = await answer_question("What's the weather?")
        assert isinstance(result, ToolResponse)

    @pytest.mark.asyncio
    async def test_answer_question_missing_question(self):
        """Test error when question is missing."""
        result = await answer_question("")
        assert result.success is False
        assert result.error_code == "MISSING_QUESTION"

    @pytest.mark.asyncio
    async def test_answer_question_whitespace_question(self):
        """Test error when question is only whitespace."""
        result = await answer_question("   ")
        assert result.success is False
        assert result.error_code == "MISSING_QUESTION"

    @pytest.mark.asyncio
    async def test_answer_question_returns_tool_response(self):
        """Test that answer_question returns ToolResponse."""
        result = await answer_question("Test question")
        assert isinstance(result, ToolResponse)
        assert result.success is True
        assert result.message  # Has some content

    @pytest.mark.asyncio
    async def test_answer_question_includes_domain_in_data(self):
        """Test response includes domain in data."""
        result = await answer_question("Test question", domain="general")
        assert result.data is not None
        assert result.data["domain"] == "general"


# ═══════════════════════════════════════════════════════════════════════════════
# answer_question Tests - Domain Routing
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnswerQuestionDomainRouting:
    """Tests for domain-based routing."""

    @pytest.mark.asyncio
    async def test_answer_question_default_domain(self):
        """Test default domain is 'general'."""
        result = await answer_question("Test question")
        assert result.data["domain"] == "general"

    @pytest.mark.asyncio
    async def test_answer_question_explicit_general_domain(self):
        """Test explicit 'general' domain."""
        result = await answer_question("Test question", domain="general")
        assert result.data["domain"] == "general"

    @pytest.mark.asyncio
    async def test_answer_question_budget_domain(self):
        """Test 'budget' domain uses LLM."""
        result = await answer_question("How much will this trip cost?", domain="budget")
        assert result.success is True
        assert result.data["domain"] == "budget"

    @pytest.mark.asyncio
    async def test_answer_question_invalid_domain_fallback(self):
        """Test invalid domain falls back to 'general'."""
        result = await answer_question("Test question", domain="invalid_domain")
        assert result.success is True
        assert result.data["domain"] == "general"

    @pytest.mark.asyncio
    async def test_answer_question_domain_case_insensitive(self):
        """Test domain matching is case-insensitive."""
        result = await answer_question("Test question", domain="GENERAL")
        assert result.data["domain"] == "general"


# ═══════════════════════════════════════════════════════════════════════════════
# answer_question Tests - Routes to Stay Agent
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnswerQuestionRoutesToStayAgent:
    """Tests for routing to stay agent."""

    @pytest.fixture
    def mock_registry(self):
        """Create mock registry with stay agent configured."""
        registry = MagicMock(spec=AgentRegistry)
        registry.get.return_value = AgentConfig(
            name="stay",
            url="http://localhost:8003",
            timeout=120.0,
        )
        return registry

    @pytest.fixture
    def mock_a2a_client(self):
        """Create mock A2A client."""
        client = AsyncMock(spec=A2AClientWrapper)
        client.send_message = AsyncMock(
            return_value=A2AResponse(
                text="The hotel has a gym, pool, and spa.",
                is_complete=True,
            )
        )
        return client

    @pytest.mark.asyncio
    async def test_routes_to_stay_agent(self, mock_registry, mock_a2a_client):
        """Test stay questions route to stay agent."""
        result = await answer_question(
            question="Does my hotel have a gym?",
            domain="stay",
            a2a_client=mock_a2a_client,
            agent_registry=mock_registry,
        )

        assert result.success is True
        assert result.message == "The hotel has a gym, pool, and spa."
        assert result.data["domain"] == "stay"

    @pytest.mark.asyncio
    async def test_stay_agent_receives_qa_mode(self, mock_registry, mock_a2a_client):
        """Test stay agent receives mode='qa' in request."""
        await answer_question(
            question="Does my hotel have a pool?",
            domain="stay",
            a2a_client=mock_a2a_client,
            agent_registry=mock_registry,
        )

        # Check the message sent
        call_args = mock_a2a_client.send_message.call_args
        message = call_args.kwargs.get("message") or call_args[1].get("message") or call_args[0][1]
        parsed = json.loads(message)
        assert parsed["mode"] == "qa"
        assert parsed["question"] == "Does my hotel have a pool?"


# ═══════════════════════════════════════════════════════════════════════════════
# answer_question Tests - Routes to Transport Agent
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnswerQuestionRoutesToTransportAgent:
    """Tests for routing to transport agent."""

    @pytest.fixture
    def mock_registry(self):
        """Create mock registry with transport agent configured."""
        registry = MagicMock(spec=AgentRegistry)
        registry.get.return_value = AgentConfig(
            name="transport",
            url="http://localhost:8002",
            timeout=120.0,
        )
        return registry

    @pytest.fixture
    def mock_a2a_client(self):
        """Create mock A2A client."""
        client = AsyncMock(spec=A2AClientWrapper)
        client.send_message = AsyncMock(
            return_value=A2AResponse(
                text="Flights from Tokyo to Osaka take about 1 hour.",
                is_complete=True,
            )
        )
        return client

    @pytest.mark.asyncio
    async def test_routes_to_transport_agent(self, mock_registry, mock_a2a_client):
        """Test transport questions route to transport agent."""
        result = await answer_question(
            question="How long is the flight from Tokyo to Osaka?",
            domain="transport",
            a2a_client=mock_a2a_client,
            agent_registry=mock_registry,
        )

        assert result.success is True
        assert "1 hour" in result.message
        assert result.data["domain"] == "transport"

    @pytest.mark.asyncio
    async def test_transport_agent_receives_context(self, mock_registry, mock_a2a_client):
        """Test transport agent receives context in Q&A request."""
        context = {"destination": "Tokyo", "dates": "March 10-17"}
        await answer_question(
            question="What's the best way to get from the airport?",
            domain="transport",
            context=context,
            a2a_client=mock_a2a_client,
            agent_registry=mock_registry,
        )

        # Check the message sent includes context
        call_args = mock_a2a_client.send_message.call_args
        message = call_args.kwargs.get("message") or call_args[1].get("message") or call_args[0][1]
        parsed = json.loads(message)
        assert parsed["context"] == context


# ═══════════════════════════════════════════════════════════════════════════════
# answer_question Tests - Sends Q&A Mode
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnswerQuestionSendsQaMode:
    """Tests for Q&A mode signaling."""

    @pytest.fixture
    def mock_registry(self):
        """Create mock registry."""
        registry = MagicMock(spec=AgentRegistry)
        registry.get.return_value = AgentConfig(
            name="poi",
            url="http://localhost:8004",
            timeout=120.0,
        )
        return registry

    @pytest.fixture
    def mock_a2a_client(self):
        """Create mock A2A client."""
        client = AsyncMock(spec=A2AClientWrapper)
        client.send_message = AsyncMock(
            return_value=A2AResponse(text="Test response", is_complete=True)
        )
        return client

    @pytest.mark.asyncio
    async def test_qa_mode_in_message(self, mock_registry, mock_a2a_client):
        """Test mode='qa' is included in message."""
        await answer_question(
            question="What are the top attractions?",
            domain="poi",
            a2a_client=mock_a2a_client,
            agent_registry=mock_registry,
        )

        call_args = mock_a2a_client.send_message.call_args
        message = call_args.kwargs.get("message") or call_args[1].get("message") or call_args[0][1]
        parsed = json.loads(message)
        assert parsed["mode"] == "qa"

    @pytest.mark.asyncio
    async def test_stateless_call_no_context_id(self, mock_registry, mock_a2a_client):
        """Test calls are stateless (no context_id)."""
        await answer_question(
            question="What are the best restaurants?",
            domain="dining",
            a2a_client=mock_a2a_client,
            agent_registry=mock_registry,
        )

        call_args = mock_a2a_client.send_message.call_args
        assert call_args.kwargs.get("context_id") is None

    @pytest.mark.asyncio
    async def test_stateless_call_empty_history(self, mock_registry, mock_a2a_client):
        """Test calls have empty history (stateless)."""
        await answer_question(
            question="What events are happening?",
            domain="events",
            a2a_client=mock_a2a_client,
            agent_registry=mock_registry,
        )

        call_args = mock_a2a_client.send_message.call_args
        assert call_args.kwargs.get("history") == []


# ═══════════════════════════════════════════════════════════════════════════════
# answer_question Tests - Returns Text
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnswerQuestionReturnsText:
    """Tests for text response handling."""

    @pytest.fixture
    def mock_registry(self):
        """Create mock registry."""
        registry = MagicMock(spec=AgentRegistry)
        registry.get.return_value = AgentConfig(
            name="poi",
            url="http://localhost:8004",
            timeout=120.0,
        )
        return registry

    @pytest.fixture
    def mock_a2a_client(self):
        """Create mock A2A client."""
        client = AsyncMock(spec=A2AClientWrapper)
        return client

    @pytest.mark.asyncio
    async def test_returns_agent_text_response(self, mock_registry, mock_a2a_client):
        """Test agent's text response is returned."""
        mock_a2a_client.send_message = AsyncMock(
            return_value=A2AResponse(
                text="The Louvre is a must-see attraction in Paris.",
                is_complete=True,
            )
        )

        result = await answer_question(
            question="What should I see in Paris?",
            domain="poi",
            a2a_client=mock_a2a_client,
            agent_registry=mock_registry,
        )

        assert result.success is True
        assert result.message == "The Louvre is a must-see attraction in Paris."

    @pytest.mark.asyncio
    async def test_returns_empty_text_if_no_response(self, mock_registry, mock_a2a_client):
        """Test handling of empty agent response."""
        mock_a2a_client.send_message = AsyncMock(
            return_value=A2AResponse(text="", is_complete=True)
        )

        result = await answer_question(
            question="Test question",
            domain="poi",
            a2a_client=mock_a2a_client,
            agent_registry=mock_registry,
        )

        assert result.success is True
        assert result.message == ""


# ═══════════════════════════════════════════════════════════════════════════════
# answer_question Tests - Error Handling
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnswerQuestionErrorHandling:
    """Tests for error handling."""

    @pytest.fixture
    def mock_registry(self):
        """Create mock registry."""
        registry = MagicMock(spec=AgentRegistry)
        registry.get.return_value = AgentConfig(
            name="stay",
            url="http://localhost:8003",
            timeout=120.0,
        )
        return registry

    @pytest.fixture
    def mock_a2a_client(self):
        """Create mock A2A client."""
        return AsyncMock(spec=A2AClientWrapper)

    @pytest.mark.asyncio
    async def test_handles_connection_error(self, mock_registry, mock_a2a_client):
        """Test handling of connection errors."""
        mock_a2a_client.send_message = AsyncMock(
            side_effect=A2AConnectionError("Connection refused")
        )

        result = await answer_question(
            question="Does my hotel have WiFi?",
            domain="stay",
            a2a_client=mock_a2a_client,
            agent_registry=mock_registry,
        )

        assert result.success is False
        assert result.error_code == "AGENT_CONNECTION_ERROR"
        assert "stay agent" in result.message.lower()

    @pytest.mark.asyncio
    async def test_handles_timeout_error(self, mock_registry, mock_a2a_client):
        """Test handling of timeout errors."""
        mock_a2a_client.send_message = AsyncMock(
            side_effect=A2ATimeoutError("Request timed out")
        )

        result = await answer_question(
            question="What's the check-in time?",
            domain="stay",
            a2a_client=mock_a2a_client,
            agent_registry=mock_registry,
        )

        assert result.success is False
        assert result.error_code == "AGENT_TIMEOUT"
        assert "stay agent" in result.message.lower()

    @pytest.mark.asyncio
    async def test_handles_generic_a2a_error(self, mock_registry, mock_a2a_client):
        """Test handling of generic A2A errors."""
        mock_a2a_client.send_message = AsyncMock(
            side_effect=A2AClientError("Something went wrong")
        )

        result = await answer_question(
            question="What amenities are available?",
            domain="stay",
            a2a_client=mock_a2a_client,
            agent_registry=mock_registry,
        )

        assert result.success is False
        assert result.error_code == "AGENT_ERROR"


# ═══════════════════════════════════════════════════════════════════════════════
# _answer_with_llm Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnswerWithLlm:
    """Tests for LLM-based answering (stub implementation)."""

    @pytest.mark.asyncio
    async def test_general_question_stub(self):
        """Test general question returns stub response."""
        result = await _answer_with_llm(
            question="Is March good for cherry blossoms in Japan?",
            domain="general",
            context=None,
        )

        assert result.success is True
        assert "general travel question" in result.message.lower()
        assert result.data["domain"] == "general"

    @pytest.mark.asyncio
    async def test_budget_question_stub(self):
        """Test budget question returns stub response."""
        result = await _answer_with_llm(
            question="How much will my trip cost?",
            domain="budget",
            context=None,
        )

        assert result.success is True
        assert "budget" in result.message.lower()
        assert result.data["domain"] == "budget"

    @pytest.mark.asyncio
    async def test_includes_context_info(self):
        """Test context info is included in stub response."""
        context = {
            "destination": "Tokyo",
            "dates": "March 2026",
        }
        result = await _answer_with_llm(
            question="What should I pack?",
            domain="general",
            context=context,
        )

        assert "Tokyo" in result.message
        assert "March 2026" in result.message


# ═══════════════════════════════════════════════════════════════════════════════
# _route_to_domain_agent Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestRouteToDomainAgent:
    """Tests for domain agent routing helper."""

    @pytest.fixture
    def mock_registry(self):
        """Create mock registry."""
        registry = MagicMock(spec=AgentRegistry)
        return registry

    @pytest.fixture
    def mock_a2a_client(self):
        """Create mock A2A client."""
        client = AsyncMock(spec=A2AClientWrapper)
        client.send_message = AsyncMock(
            return_value=A2AResponse(text="Test answer", is_complete=True)
        )
        return client

    @pytest.mark.asyncio
    async def test_calls_correct_agent_url(self, mock_registry, mock_a2a_client):
        """Test correct agent URL is called."""
        mock_registry.get.return_value = AgentConfig(
            name="dining",
            url="http://localhost:8006",
            timeout=120.0,
        )

        await _route_to_domain_agent(
            question="Best sushi in Tokyo?",
            domain="dining",
            context=None,
            a2a_client=mock_a2a_client,
            agent_registry=mock_registry,
        )

        call_args = mock_a2a_client.send_message.call_args
        assert call_args.kwargs.get("agent_url") == "http://localhost:8006"

    @pytest.mark.asyncio
    async def test_handles_unknown_agent(self, mock_registry, mock_a2a_client):
        """Test handling of unknown agent in registry."""
        mock_registry.get.side_effect = ValueError("Unknown agent: foo")

        result = await _route_to_domain_agent(
            question="Test question",
            domain="foo",
            context=None,
            a2a_client=mock_a2a_client,
            agent_registry=mock_registry,
        )

        assert result.success is False
        assert result.error_code == "UNKNOWN_DOMAIN"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration with ToolResponse Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolResponseIntegration:
    """Tests for ToolResponse integration."""

    @pytest.mark.asyncio
    async def test_response_serializes_to_dict(self):
        """Test response can be serialized to dict."""
        result = await answer_question("Test question", domain="general")
        serialized = result.to_dict()

        assert isinstance(serialized, dict)
        assert "success" in serialized
        assert "message" in serialized

    @pytest.mark.asyncio
    async def test_error_response_has_proper_format(self):
        """Test error responses have proper format."""
        result = await answer_question("")
        serialized = result.to_dict()

        assert serialized["success"] is False
        assert "error_code" in serialized
        assert serialized["error_code"] == "MISSING_QUESTION"
