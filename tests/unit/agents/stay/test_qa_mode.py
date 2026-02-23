"""
Unit tests for Stay agent Q&A mode.

Tests ORCH-012: Add Q&A mode to Stay agent prompt and response parsing.

Per design doc (Tool Definitions section):
- Q&A mode is signaled by "mode": "qa" in the request JSON
- In Q&A mode, agent answers questions and returns text response
- Q&A mode sets is_task_complete=True (single-turn)
- Planning mode (mode="plan" or no mode) returns structured StayOutput
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from collections.abc import AsyncIterable
from typing import Any

from src.agents.stay_agent.agent import AgentFrameworkStayAgent
from src.shared.models import StayResponse, StayOutput, Neighborhood, StayItem, Source


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


class TestStayAgentDetectsQAMode:
    """Tests that Stay agent correctly detects Q&A mode from request."""

    @pytest.fixture
    def stay_agent(self):
        """Create a Stay agent with mocked chat service."""
        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkStayAgent()
            return agent

    def test_stay_agent_detects_qa_mode_from_json(self, stay_agent):
        """Test that _detect_qa_mode returns True for Q&A mode requests."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "Does the Park Hyatt have a pool?",
            "context": {"destination": "Tokyo"}
        })

        assert stay_agent._detect_qa_mode(qa_request) is True

    def test_stay_agent_detects_planning_mode_explicit(self, stay_agent):
        """Test that _detect_qa_mode returns False for explicit planning mode."""
        plan_request = json.dumps({
            "mode": "plan",
            "destination_city": "Tokyo"
        })

        assert stay_agent._detect_qa_mode(plan_request) is False

    def test_stay_agent_detects_planning_mode_no_mode_field(self, stay_agent):
        """Test that _detect_qa_mode returns False when no mode field (defaults to plan)."""
        request_without_mode = json.dumps({
            "destination_city": "Tokyo"
        })

        assert stay_agent._detect_qa_mode(request_without_mode) is False

    def test_stay_agent_detects_planning_mode_plain_text(self, stay_agent):
        """Test that _detect_qa_mode returns False for plain text requests."""
        plain_text = "Find hotels in Tokyo"

        assert stay_agent._detect_qa_mode(plain_text) is False

    def test_stay_agent_detects_planning_mode_invalid_json(self, stay_agent):
        """Test that _detect_qa_mode returns False for invalid JSON."""
        invalid_json = '{"mode": "qa", broken'

        assert stay_agent._detect_qa_mode(invalid_json) is False


class TestStayAgentQAReturnsTextResponse:
    """Tests that Stay agent returns text response in Q&A mode."""

    @pytest.fixture
    def mock_stay_agent_qa(self):
        """Create a Stay agent with mocked chat service configured for Q&A response."""
        qa_response = json.dumps({
            "stay_output": None,
            "response": "Yes, the Park Hyatt Tokyo has an indoor swimming pool."
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkStayAgent()
            agent.agent = MockChatAgent(qa_response)
            return agent

    @pytest.mark.asyncio
    async def test_stay_agent_qa_returns_text_response_via_stream(
        self, mock_stay_agent_qa
    ):
        """Test that Q&A mode returns text response via stream()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "Does the Park Hyatt Tokyo have a pool?"
        })

        responses = []
        async for response in mock_stay_agent_qa.stream(
            user_input=qa_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["content"] == "Yes, the Park Hyatt Tokyo has an indoor swimming pool."

    @pytest.mark.asyncio
    async def test_stay_agent_qa_returns_text_response_via_invoke(
        self, mock_stay_agent_qa
    ):
        """Test that Q&A mode returns text response via invoke()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "Does the Park Hyatt Tokyo have a pool?"
        })

        response = await mock_stay_agent_qa.invoke(
            user_input=qa_request,
            session_id="test_session",
        )

        assert response["content"] == "Yes, the Park Hyatt Tokyo has an indoor swimming pool."


class TestStayAgentQASetsTaskComplete:
    """Tests that Stay agent sets is_task_complete=True in Q&A mode."""

    @pytest.fixture
    def mock_stay_agent_qa(self):
        """Create a Stay agent with mocked chat service configured for Q&A response."""
        qa_response = json.dumps({
            "stay_output": None,
            "response": "The hotel has free WiFi throughout the property."
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkStayAgent()
            agent.agent = MockChatAgent(qa_response)
            return agent

    @pytest.mark.asyncio
    async def test_stay_agent_qa_sets_task_complete_via_stream(
        self, mock_stay_agent_qa
    ):
        """Test that Q&A mode sets is_task_complete=True via stream()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "Does the hotel have WiFi?"
        })

        responses = []
        async for response in mock_stay_agent_qa.stream(
            user_input=qa_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["is_task_complete"] is True
        assert responses[0]["require_user_input"] is False

    @pytest.mark.asyncio
    async def test_stay_agent_qa_sets_task_complete_via_invoke(
        self, mock_stay_agent_qa
    ):
        """Test that Q&A mode sets is_task_complete=True via invoke()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "Does the hotel have WiFi?"
        })

        response = await mock_stay_agent_qa.invoke(
            user_input=qa_request,
            session_id="test_session",
        )

        assert response["is_task_complete"] is True
        assert response["require_user_input"] is False


class TestStayAgentPlanningModeUnchanged:
    """Tests that Stay agent planning mode behavior is unchanged."""

    @pytest.fixture
    def mock_stay_agent_planning(self):
        """Create a Stay agent with mocked chat service for planning response."""
        planning_response = json.dumps({
            "stay_output": {
                "neighborhoods": [
                    {
                        "name": "Shinjuku",
                        "reasons": ["Central location", "Great transport"],
                        "source": {"title": "Tokyo Guide", "url": "https://example.com"}
                    }
                ],
                "stays": [
                    {
                        "name": "Park Hyatt Tokyo",
                        "area": "Shinjuku",
                        "pricePerNight": 500,
                        "currency": "USD",
                        "link": "https://parkhyatt.com",
                        "notes": "Luxury hotel",
                        "source": {"title": "Park Hyatt", "url": "https://parkhyatt.com"}
                    }
                ],
                "notes": ["Great options for luxury travelers"]
            },
            "response": None
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkStayAgent()
            agent.agent = MockChatAgent(planning_response)
            return agent

    @pytest.fixture
    def mock_stay_agent_followup(self):
        """Create a Stay agent that returns a follow-up question in planning mode."""
        followup_response = json.dumps({
            "stay_output": None,
            "response": "Please provide the destination city to search for stays."
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkStayAgent()
            agent.agent = MockChatAgent(followup_response)
            return agent

    @pytest.mark.asyncio
    async def test_stay_agent_planning_mode_returns_structured_output(
        self, mock_stay_agent_planning
    ):
        """Test that planning mode returns structured StayOutput."""
        plan_request = json.dumps({
            "mode": "plan",
            "destination_city": "Tokyo"
        })

        responses = []
        async for response in mock_stay_agent_planning.stream(
            user_input=plan_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["is_task_complete"] is True
        assert responses[0]["require_user_input"] is False

        # Verify content is valid StayOutput JSON
        content = json.loads(responses[0]["content"])
        assert "neighborhoods" in content
        assert "stays" in content

    @pytest.mark.asyncio
    async def test_stay_agent_planning_mode_no_mode_field(
        self, mock_stay_agent_planning
    ):
        """Test that requests without mode field default to planning mode."""
        request_no_mode = "Find hotels in Tokyo"

        responses = []
        async for response in mock_stay_agent_planning.stream(
            user_input=request_no_mode,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["is_task_complete"] is True
        # Verify content is valid StayOutput JSON (planning mode)
        content = json.loads(responses[0]["content"])
        assert "neighborhoods" in content

    @pytest.mark.asyncio
    async def test_stay_agent_planning_mode_followup_is_incomplete(
        self, mock_stay_agent_followup
    ):
        """Test that planning mode follow-up questions are marked incomplete."""
        # Request in planning mode (no mode = plan)
        plan_request = "Help me find hotels"

        responses = []
        async for response in mock_stay_agent_followup.stream(
            user_input=plan_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        # In planning mode, response field means incomplete (needs more info)
        assert responses[0]["is_task_complete"] is False
        assert responses[0]["require_user_input"] is True
        assert "destination city" in responses[0]["content"].lower()


class TestStayAgentParseResponseQAMode:
    """Tests for parse_response() Q&A mode handling."""

    @pytest.fixture
    def stay_agent(self):
        """Create a Stay agent with mocked chat service."""
        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkStayAgent()
            return agent

    def test_parse_response_qa_mode_returns_complete(self, stay_agent):
        """Test that parse_response returns complete task for Q&A mode response."""
        # Set agent to Q&A mode
        stay_agent._is_qa_mode = True

        response_json = json.dumps({
            "stay_output": None,
            "response": "The pool is open 24 hours."
        })

        result = stay_agent.parse_response(response_json)

        assert result["is_task_complete"] is True
        assert result["require_user_input"] is False
        assert result["content"] == "The pool is open 24 hours."

    def test_parse_response_planning_mode_response_returns_incomplete(self, stay_agent):
        """Test that parse_response returns incomplete task for planning mode follow-up."""
        # Ensure planning mode (not Q&A)
        stay_agent._is_qa_mode = False

        response_json = json.dumps({
            "stay_output": None,
            "response": "What city would you like to visit?"
        })

        result = stay_agent.parse_response(response_json)

        assert result["is_task_complete"] is False
        assert result["require_user_input"] is True
        assert result["content"] == "What city would you like to visit?"

    def test_parse_response_planning_mode_stay_output_returns_complete(self, stay_agent):
        """Test that parse_response returns complete task for planning mode structured output."""
        stay_agent._is_qa_mode = False

        response_json = json.dumps({
            "stay_output": {
                "neighborhoods": [],
                "stays": [
                    {
                        "name": "Test Hotel",
                        "area": "Downtown",
                        "pricePerNight": 100,
                        "currency": "USD",
                        "link": "https://example.com",
                        "notes": None,
                        "source": {"title": "Test", "url": "https://example.com"}
                    }
                ],
                "notes": []
            },
            "response": None
        })

        result = stay_agent.parse_response(response_json)

        assert result["is_task_complete"] is True
        assert result["require_user_input"] is False
        # Content should be the serialized stay_output
        content = json.loads(result["content"])
        assert "stays" in content
