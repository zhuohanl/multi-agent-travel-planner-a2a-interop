"""
Unit tests for Transport agent Q&A mode.

Tests ORCH-013: Add Q&A mode to Transport agent prompt and response parsing.

Per design doc (Tool Definitions section):
- Q&A mode is signaled by "mode": "qa" in the request JSON
- In Q&A mode, agent answers questions and returns text response
- Q&A mode sets is_task_complete=True (single-turn)
- Planning mode (mode="plan" or no mode) returns structured TransportOutput
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from collections.abc import AsyncIterable
from typing import Any

from src.agents.transport_agent.agent import AgentFrameworkTransportAgent
from src.shared.models import TransportResponse, TransportOutput, TransportOption, Source


class MockChatAgent:
    """Mock ChatAgent for testing without LLM calls."""

    def __init__(self, response_json: str):
        self.response_json = response_json
        self.run_response = MagicMock()
        self.run_response.text = response_json

    def get_new_thread(self, thread_id: str) -> MagicMock:
        thread = MagicMock()
        thread.thread_id = thread_id
        thread.message_store = None
        return thread

    async def run(self, messages: str, thread: Any) -> MagicMock:
        return self.run_response

    async def run_stream(self, messages: str, thread: Any) -> AsyncIterable:
        yield MagicMock(text=self.response_json)


class TestTransportAgentDetectsQAMode:
    """Tests that Transport agent correctly detects Q&A mode from request."""

    @pytest.fixture
    def transport_agent(self):
        """Create a Transport agent with mocked chat service."""
        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkTransportAgent()
            return agent

    def test_transport_agent_detects_qa_mode_from_json(self, transport_agent):
        """Test that _detect_qa_mode returns True for Q&A mode requests."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "How long is the bullet train from Tokyo to Kyoto?",
            "context": {"destination": "Kyoto"}
        })

        assert transport_agent._detect_qa_mode(qa_request) is True

    def test_transport_agent_detects_planning_mode_explicit(self, transport_agent):
        """Test that _detect_qa_mode returns False for explicit planning mode."""
        plan_request = json.dumps({
            "mode": "plan",
            "origin_city": "Tokyo",
            "destination_city": "Kyoto"
        })

        assert transport_agent._detect_qa_mode(plan_request) is False

    def test_transport_agent_detects_planning_mode_no_mode_field(self, transport_agent):
        """Test that _detect_qa_mode returns False when no mode field (defaults to plan)."""
        request_without_mode = json.dumps({
            "origin_city": "Tokyo",
            "destination_city": "Kyoto"
        })

        assert transport_agent._detect_qa_mode(request_without_mode) is False

    def test_transport_agent_detects_planning_mode_plain_text(self, transport_agent):
        """Test that _detect_qa_mode returns False for plain text requests."""
        plain_text = "Find trains from Tokyo to Kyoto"

        assert transport_agent._detect_qa_mode(plain_text) is False

    def test_transport_agent_detects_planning_mode_invalid_json(self, transport_agent):
        """Test that _detect_qa_mode returns False for invalid JSON."""
        invalid_json = '{"mode": "qa", broken'

        assert transport_agent._detect_qa_mode(invalid_json) is False


class TestTransportAgentQAReturnsTextResponse:
    """Tests that Transport agent returns text response in Q&A mode."""

    @pytest.fixture
    def mock_transport_agent_qa(self):
        """Create a Transport agent with mocked chat service configured for Q&A response."""
        qa_response = json.dumps({
            "transport_output": None,
            "response": "The bullet train from Tokyo to Kyoto takes about 2 hours and 15 minutes."
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkTransportAgent()
            agent.agent = MockChatAgent(qa_response)
            return agent

    @pytest.mark.asyncio
    async def test_transport_agent_qa_returns_text_response_via_stream(
        self, mock_transport_agent_qa
    ):
        """Test that Q&A mode returns text response via stream()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "How long is the bullet train from Tokyo to Kyoto?"
        })

        responses = []
        async for response in mock_transport_agent_qa.stream(
            user_input=qa_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["content"] == "The bullet train from Tokyo to Kyoto takes about 2 hours and 15 minutes."

    @pytest.mark.asyncio
    async def test_transport_agent_qa_returns_text_response_via_invoke(
        self, mock_transport_agent_qa
    ):
        """Test that Q&A mode returns text response via invoke()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "How long is the bullet train from Tokyo to Kyoto?"
        })

        response = await mock_transport_agent_qa.invoke(
            user_input=qa_request,
            session_id="test_session",
        )

        assert response["content"] == "The bullet train from Tokyo to Kyoto takes about 2 hours and 15 minutes."


class TestTransportAgentQASetsTaskComplete:
    """Tests that Transport agent sets is_task_complete=True in Q&A mode."""

    @pytest.fixture
    def mock_transport_agent_qa(self):
        """Create a Transport agent with mocked chat service configured for Q&A response."""
        qa_response = json.dumps({
            "transport_output": None,
            "response": "The JR Pass costs about 50,000 yen for 7 days."
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkTransportAgent()
            agent.agent = MockChatAgent(qa_response)
            return agent

    @pytest.mark.asyncio
    async def test_transport_agent_qa_sets_task_complete_via_stream(
        self, mock_transport_agent_qa
    ):
        """Test that Q&A mode sets is_task_complete=True via stream()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "How much does the JR Pass cost?"
        })

        responses = []
        async for response in mock_transport_agent_qa.stream(
            user_input=qa_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["is_task_complete"] is True
        assert responses[0]["require_user_input"] is False

    @pytest.mark.asyncio
    async def test_transport_agent_qa_sets_task_complete_via_invoke(
        self, mock_transport_agent_qa
    ):
        """Test that Q&A mode sets is_task_complete=True via invoke()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "How much does the JR Pass cost?"
        })

        response = await mock_transport_agent_qa.invoke(
            user_input=qa_request,
            session_id="test_session",
        )

        assert response["is_task_complete"] is True
        assert response["require_user_input"] is False


class TestTransportAgentPlanningModeUnchanged:
    """Tests that Transport agent planning mode behavior is unchanged."""

    @pytest.fixture
    def mock_transport_agent_planning(self):
        """Create a Transport agent with mocked chat service for planning response."""
        planning_response = json.dumps({
            "transport_output": {
                "transportOptions": [
                    {
                        "mode": "train",
                        "route": "Tokyo to Kyoto",
                        "provider": "JR Central",
                        "date": "2025-03-15",
                        "durationMins": 135,
                        "price": 14000,
                        "currency": "JPY",
                        "link": "https://jr-central.co.jp",
                        "source": {"title": "JR Central", "url": "https://jr-central.co.jp"}
                    }
                ],
                "localTransfers": [],
                "localPasses": [],
                "notes": ["Nozomi is the fastest option"]
            },
            "response": None
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkTransportAgent()
            agent.agent = MockChatAgent(planning_response)
            return agent

    @pytest.fixture
    def mock_transport_agent_followup(self):
        """Create a Transport agent that returns a follow-up question in planning mode."""
        followup_response = json.dumps({
            "transport_output": None,
            "response": "Please provide the destination city for transport search."
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkTransportAgent()
            agent.agent = MockChatAgent(followup_response)
            return agent

    @pytest.mark.asyncio
    async def test_transport_agent_planning_mode_returns_structured_output(
        self, mock_transport_agent_planning
    ):
        """Test that planning mode returns structured TransportOutput."""
        plan_request = json.dumps({
            "mode": "plan",
            "origin_city": "Tokyo",
            "destination_city": "Kyoto"
        })

        responses = []
        async for response in mock_transport_agent_planning.stream(
            user_input=plan_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["is_task_complete"] is True
        assert responses[0]["require_user_input"] is False

        # Verify content is valid TransportOutput JSON
        content = json.loads(responses[0]["content"])
        assert "transportOptions" in content

    @pytest.mark.asyncio
    async def test_transport_agent_planning_mode_no_mode_field(
        self, mock_transport_agent_planning
    ):
        """Test that requests without mode field default to planning mode."""
        request_no_mode = "Find trains from Tokyo to Kyoto"

        responses = []
        async for response in mock_transport_agent_planning.stream(
            user_input=request_no_mode,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["is_task_complete"] is True
        # Verify content is valid TransportOutput JSON (planning mode)
        content = json.loads(responses[0]["content"])
        assert "transportOptions" in content

    @pytest.mark.asyncio
    async def test_transport_agent_planning_mode_followup_is_incomplete(
        self, mock_transport_agent_followup
    ):
        """Test that planning mode follow-up questions are marked incomplete."""
        # Request in planning mode (no mode = plan)
        plan_request = "Help me find transport"

        responses = []
        async for response in mock_transport_agent_followup.stream(
            user_input=plan_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        # In planning mode, response field means incomplete (needs more info)
        assert responses[0]["is_task_complete"] is False
        assert responses[0]["require_user_input"] is True
        assert "destination" in responses[0]["content"].lower()


class TestTransportAgentParseResponseQAMode:
    """Tests for parse_response() Q&A mode handling."""

    @pytest.fixture
    def transport_agent(self):
        """Create a Transport agent with mocked chat service."""
        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkTransportAgent()
            return agent

    def test_parse_response_qa_mode_returns_complete(self, transport_agent):
        """Test that parse_response returns complete task for Q&A mode response."""
        # Set agent to Q&A mode
        transport_agent._is_qa_mode = True

        response_json = json.dumps({
            "transport_output": None,
            "response": "The Nozomi train is the fastest option."
        })

        result = transport_agent.parse_response(response_json)

        assert result["is_task_complete"] is True
        assert result["require_user_input"] is False
        assert result["content"] == "The Nozomi train is the fastest option."

    def test_parse_response_planning_mode_response_returns_incomplete(self, transport_agent):
        """Test that parse_response returns incomplete task for planning mode follow-up."""
        # Ensure planning mode (not Q&A)
        transport_agent._is_qa_mode = False

        response_json = json.dumps({
            "transport_output": None,
            "response": "What cities are you traveling between?"
        })

        result = transport_agent.parse_response(response_json)

        assert result["is_task_complete"] is False
        assert result["require_user_input"] is True
        assert result["content"] == "What cities are you traveling between?"

    def test_parse_response_planning_mode_transport_output_returns_complete(self, transport_agent):
        """Test that parse_response returns complete task for planning mode structured output."""
        transport_agent._is_qa_mode = False

        response_json = json.dumps({
            "transport_output": {
                "transportOptions": [
                    {
                        "mode": "train",
                        "route": "Tokyo to Osaka",
                        "provider": "JR Central",
                        "date": None,
                        "durationMins": 150,
                        "price": 15000,
                        "currency": "JPY",
                        "link": "https://jr-central.co.jp",
                        "source": {"title": "JR", "url": "https://jr-central.co.jp"}
                    }
                ],
                "localTransfers": [],
                "localPasses": [],
                "notes": []
            },
            "response": None
        })

        result = transport_agent.parse_response(response_json)

        assert result["is_task_complete"] is True
        assert result["require_user_input"] is False
        # Content should be the serialized transport_output
        content = json.loads(result["content"])
        assert "transportOptions" in content
