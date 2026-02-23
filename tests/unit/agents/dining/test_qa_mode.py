"""
Unit tests for Dining agent Q&A mode.

Tests ORCH-015: Add Q&A mode to Dining agent prompt and response parsing.

Per design doc (Tool Definitions section):
- Q&A mode is signaled by "mode": "qa" in the request JSON
- In Q&A mode, agent answers questions and returns text response
- Q&A mode sets is_task_complete=True (single-turn)
- Planning mode (mode="plan" or no mode) returns structured DiningOutput
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from collections.abc import AsyncIterable
from typing import Any

from src.agents.dining_agent.agent import AgentFrameworkDiningAgent
from src.shared.models import DiningResponse, DiningOutput, DiningItem, Source


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


class TestDiningAgentDetectsQAMode:
    """Tests that Dining agent correctly detects Q&A mode from request."""

    @pytest.fixture
    def dining_agent(self):
        """Create a Dining agent with mocked chat service."""
        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkDiningAgent()
            return agent

    def test_dining_agent_detects_qa_mode_from_json(self, dining_agent):
        """Test that _detect_qa_mode returns True for Q&A mode requests."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "What's the dress code at Sukiyabashi Jiro?",
            "context": {"destination": "Tokyo"}
        })

        assert dining_agent._detect_qa_mode(qa_request) is True

    def test_dining_agent_detects_planning_mode_explicit(self, dining_agent):
        """Test that _detect_qa_mode returns False for explicit planning mode."""
        plan_request = json.dumps({
            "mode": "plan",
            "destination_city": "Tokyo"
        })

        assert dining_agent._detect_qa_mode(plan_request) is False

    def test_dining_agent_detects_planning_mode_no_mode_field(self, dining_agent):
        """Test that _detect_qa_mode returns False when no mode field (defaults to plan)."""
        request_without_mode = json.dumps({
            "destination_city": "Tokyo"
        })

        assert dining_agent._detect_qa_mode(request_without_mode) is False

    def test_dining_agent_detects_planning_mode_plain_text(self, dining_agent):
        """Test that _detect_qa_mode returns False for plain text requests."""
        plain_text = "Find restaurants in Tokyo"

        assert dining_agent._detect_qa_mode(plain_text) is False

    def test_dining_agent_detects_planning_mode_invalid_json(self, dining_agent):
        """Test that _detect_qa_mode returns False for invalid JSON."""
        invalid_json = '{"mode": "qa", broken'

        assert dining_agent._detect_qa_mode(invalid_json) is False


class TestDiningAgentQAReturnsTextResponse:
    """Tests that Dining agent returns text response in Q&A mode."""

    @pytest.fixture
    def mock_dining_agent_qa(self):
        """Create a Dining agent with mocked chat service configured for Q&A response."""
        qa_response = json.dumps({
            "dining_output": None,
            "response": "Sukiyabashi Jiro has a smart casual dress code."
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkDiningAgent()
            agent.agent = MockChatAgent(qa_response)
            return agent

    @pytest.mark.asyncio
    async def test_dining_agent_qa_returns_text_response_via_stream(
        self, mock_dining_agent_qa
    ):
        """Test that Q&A mode returns text response via stream()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "What's the dress code at Sukiyabashi Jiro?"
        })

        responses = []
        async for response in mock_dining_agent_qa.stream(
            user_input=qa_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["content"] == "Sukiyabashi Jiro has a smart casual dress code."

    @pytest.mark.asyncio
    async def test_dining_agent_qa_returns_text_response_via_invoke(
        self, mock_dining_agent_qa
    ):
        """Test that Q&A mode returns text response via invoke()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "What's the dress code at Sukiyabashi Jiro?"
        })

        response = await mock_dining_agent_qa.invoke(
            user_input=qa_request,
            session_id="test_session",
        )

        assert response["content"] == "Sukiyabashi Jiro has a smart casual dress code."


class TestDiningAgentQASetsTaskComplete:
    """Tests that Dining agent sets is_task_complete=True in Q&A mode."""

    @pytest.fixture
    def mock_dining_agent_qa(self):
        """Create a Dining agent with mocked chat service configured for Q&A response."""
        qa_response = json.dumps({
            "dining_output": None,
            "response": "The restaurant accepts reservations up to 3 months in advance."
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkDiningAgent()
            agent.agent = MockChatAgent(qa_response)
            return agent

    @pytest.mark.asyncio
    async def test_dining_agent_qa_sets_task_complete_via_stream(
        self, mock_dining_agent_qa
    ):
        """Test that Q&A mode sets is_task_complete=True via stream()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "How far in advance can I make a reservation?"
        })

        responses = []
        async for response in mock_dining_agent_qa.stream(
            user_input=qa_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["is_task_complete"] is True
        assert responses[0]["require_user_input"] is False

    @pytest.mark.asyncio
    async def test_dining_agent_qa_sets_task_complete_via_invoke(
        self, mock_dining_agent_qa
    ):
        """Test that Q&A mode sets is_task_complete=True via invoke()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "How far in advance can I make a reservation?"
        })

        response = await mock_dining_agent_qa.invoke(
            user_input=qa_request,
            session_id="test_session",
        )

        assert response["is_task_complete"] is True
        assert response["require_user_input"] is False


class TestDiningAgentPlanningModeUnchanged:
    """Tests that Dining agent planning mode behavior is unchanged."""

    @pytest.fixture
    def mock_dining_agent_planning(self):
        """Create a Dining agent with mocked chat service for planning response."""
        planning_response = json.dumps({
            "dining_output": {
                "restaurants": [
                    {
                        "name": "Sukiyabashi Jiro",
                        "area": "Ginza",
                        "cuisine": "Sushi",
                        "priceRange": "$$$",
                        "dietaryOptions": [],
                        "link": "https://example.com/jiro",
                        "notes": "Reservation required",
                        "source": {"title": "Tokyo Dining", "url": "https://example.com"}
                    }
                ],
                "notes": ["Book well in advance"]
            },
            "response": None
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkDiningAgent()
            agent.agent = MockChatAgent(planning_response)
            return agent

    @pytest.fixture
    def mock_dining_agent_followup(self):
        """Create a Dining agent that returns a follow-up question in planning mode."""
        followup_response = json.dumps({
            "dining_output": None,
            "response": "Please provide the destination to search for restaurants and dining options."
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkDiningAgent()
            agent.agent = MockChatAgent(followup_response)
            return agent

    @pytest.mark.asyncio
    async def test_dining_agent_planning_mode_returns_structured_output(
        self, mock_dining_agent_planning
    ):
        """Test that planning mode returns structured DiningOutput."""
        plan_request = json.dumps({
            "mode": "plan",
            "destination_city": "Tokyo"
        })

        responses = []
        async for response in mock_dining_agent_planning.stream(
            user_input=plan_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["is_task_complete"] is True
        assert responses[0]["require_user_input"] is False

        # Verify content is valid DiningOutput JSON
        content = json.loads(responses[0]["content"])
        assert "restaurants" in content

    @pytest.mark.asyncio
    async def test_dining_agent_planning_mode_no_mode_field(
        self, mock_dining_agent_planning
    ):
        """Test that requests without mode field default to planning mode."""
        request_no_mode = "Find restaurants in Tokyo"

        responses = []
        async for response in mock_dining_agent_planning.stream(
            user_input=request_no_mode,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["is_task_complete"] is True
        # Verify content is valid DiningOutput JSON (planning mode)
        content = json.loads(responses[0]["content"])
        assert "restaurants" in content

    @pytest.mark.asyncio
    async def test_dining_agent_planning_mode_followup_is_incomplete(
        self, mock_dining_agent_followup
    ):
        """Test that planning mode follow-up questions are marked incomplete."""
        # Request in planning mode (no mode = plan)
        plan_request = "Help me find restaurants"

        responses = []
        async for response in mock_dining_agent_followup.stream(
            user_input=plan_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        # In planning mode, response field means incomplete (needs more info)
        assert responses[0]["is_task_complete"] is False
        assert responses[0]["require_user_input"] is True
        assert "destination" in responses[0]["content"].lower()


class TestDiningAgentParseResponseQAMode:
    """Tests for parse_response() Q&A mode handling."""

    @pytest.fixture
    def dining_agent(self):
        """Create a Dining agent with mocked chat service."""
        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkDiningAgent()
            return agent

    def test_parse_response_qa_mode_returns_complete(self, dining_agent):
        """Test that parse_response returns complete task for Q&A mode response."""
        # Set agent to Q&A mode
        dining_agent._is_qa_mode = True

        response_json = json.dumps({
            "dining_output": None,
            "response": "The restaurant is open from 6 PM to 10 PM."
        })

        result = dining_agent.parse_response(response_json)

        assert result["is_task_complete"] is True
        assert result["require_user_input"] is False
        assert result["content"] == "The restaurant is open from 6 PM to 10 PM."

    def test_parse_response_planning_mode_response_returns_incomplete(self, dining_agent):
        """Test that parse_response returns incomplete task for planning mode follow-up."""
        # Ensure planning mode (not Q&A)
        dining_agent._is_qa_mode = False

        response_json = json.dumps({
            "dining_output": None,
            "response": "What cuisine are you looking for?"
        })

        result = dining_agent.parse_response(response_json)

        assert result["is_task_complete"] is False
        assert result["require_user_input"] is True
        assert result["content"] == "What cuisine are you looking for?"

    def test_parse_response_planning_mode_dining_output_returns_complete(self, dining_agent):
        """Test that parse_response returns complete task for planning mode structured output."""
        dining_agent._is_qa_mode = False

        response_json = json.dumps({
            "dining_output": {
                "restaurants": [
                    {
                        "name": "Test Restaurant",
                        "area": "Downtown",
                        "cuisine": "Italian",
                        "priceRange": "$$",
                        "dietaryOptions": ["vegetarian"],
                        "link": "https://example.com",
                        "notes": None,
                        "source": {"title": "Test", "url": "https://example.com"}
                    }
                ],
                "notes": []
            },
            "response": None
        })

        result = dining_agent.parse_response(response_json)

        assert result["is_task_complete"] is True
        assert result["require_user_input"] is False
        # Content should be the serialized dining_output
        content = json.loads(result["content"])
        assert "restaurants" in content
