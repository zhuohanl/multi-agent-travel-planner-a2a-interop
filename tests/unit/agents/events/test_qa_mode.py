"""
Unit tests for Events agent Q&A mode.

Tests ORCH-016: Add Q&A mode to Events agent prompt and response parsing.

Per design doc (Tool Definitions section):
- Q&A mode is signaled by "mode": "qa" in the request JSON
- In Q&A mode, agent answers questions and returns text response
- Q&A mode sets is_task_complete=True (single-turn)
- Planning mode (mode="plan" or no mode) returns structured EventsOutput
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from collections.abc import AsyncIterable
from typing import Any

from src.agents.events_agent.agent import AgentFrameworkEventsAgent
from src.shared.models import EventsResponse, EventsOutput, EventItem, Source


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


class TestEventsAgentDetectsQAMode:
    """Tests that Events agent correctly detects Q&A mode from request."""

    @pytest.fixture
    def events_agent(self):
        """Create an Events agent with mocked chat service."""
        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkEventsAgent()
            return agent

    def test_events_agent_detects_qa_mode_from_json(self, events_agent):
        """Test that _detect_qa_mode returns True for Q&A mode requests."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "Are there any festivals in Tokyo in March?",
            "context": {"destination": "Tokyo"}
        })

        assert events_agent._detect_qa_mode(qa_request) is True

    def test_events_agent_detects_planning_mode_explicit(self, events_agent):
        """Test that _detect_qa_mode returns False for explicit planning mode."""
        plan_request = json.dumps({
            "mode": "plan",
            "destination_city": "Tokyo"
        })

        assert events_agent._detect_qa_mode(plan_request) is False

    def test_events_agent_detects_planning_mode_no_mode_field(self, events_agent):
        """Test that _detect_qa_mode returns False when no mode field (defaults to plan)."""
        request_without_mode = json.dumps({
            "destination_city": "Tokyo"
        })

        assert events_agent._detect_qa_mode(request_without_mode) is False

    def test_events_agent_detects_planning_mode_plain_text(self, events_agent):
        """Test that _detect_qa_mode returns False for plain text requests."""
        plain_text = "Find events in Tokyo"

        assert events_agent._detect_qa_mode(plain_text) is False

    def test_events_agent_detects_planning_mode_invalid_json(self, events_agent):
        """Test that _detect_qa_mode returns False for invalid JSON."""
        invalid_json = '{"mode": "qa", broken'

        assert events_agent._detect_qa_mode(invalid_json) is False


class TestEventsAgentQAReturnsTextResponse:
    """Tests that Events agent returns text response in Q&A mode."""

    @pytest.fixture
    def mock_events_agent_qa(self):
        """Create an Events agent with mocked chat service configured for Q&A response."""
        qa_response = json.dumps({
            "events_output": None,
            "response": "Yes, Tokyo has several festivals in March including the Tokyo Marathon."
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkEventsAgent()
            agent.agent = MockChatAgent(qa_response)
            return agent

    @pytest.mark.asyncio
    async def test_events_agent_qa_returns_text_response_via_stream(
        self, mock_events_agent_qa
    ):
        """Test that Q&A mode returns text response via stream()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "Are there any festivals in Tokyo in March?"
        })

        responses = []
        async for response in mock_events_agent_qa.stream(
            user_input=qa_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["content"] == "Yes, Tokyo has several festivals in March including the Tokyo Marathon."

    @pytest.mark.asyncio
    async def test_events_agent_qa_returns_text_response_via_invoke(
        self, mock_events_agent_qa
    ):
        """Test that Q&A mode returns text response via invoke()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "Are there any festivals in Tokyo in March?"
        })

        response = await mock_events_agent_qa.invoke(
            user_input=qa_request,
            session_id="test_session",
        )

        assert response["content"] == "Yes, Tokyo has several festivals in March including the Tokyo Marathon."


class TestEventsAgentQASetsTaskComplete:
    """Tests that Events agent sets is_task_complete=True in Q&A mode."""

    @pytest.fixture
    def mock_events_agent_qa(self):
        """Create an Events agent with mocked chat service configured for Q&A response."""
        qa_response = json.dumps({
            "events_output": None,
            "response": "The cherry blossom festival typically starts in late March."
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkEventsAgent()
            agent.agent = MockChatAgent(qa_response)
            return agent

    @pytest.mark.asyncio
    async def test_events_agent_qa_sets_task_complete_via_stream(
        self, mock_events_agent_qa
    ):
        """Test that Q&A mode sets is_task_complete=True via stream()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "When is the cherry blossom festival?"
        })

        responses = []
        async for response in mock_events_agent_qa.stream(
            user_input=qa_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["is_task_complete"] is True
        assert responses[0]["require_user_input"] is False

    @pytest.mark.asyncio
    async def test_events_agent_qa_sets_task_complete_via_invoke(
        self, mock_events_agent_qa
    ):
        """Test that Q&A mode sets is_task_complete=True via invoke()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "When is the cherry blossom festival?"
        })

        response = await mock_events_agent_qa.invoke(
            user_input=qa_request,
            session_id="test_session",
        )

        assert response["is_task_complete"] is True
        assert response["require_user_input"] is False


class TestEventsAgentPlanningModeUnchanged:
    """Tests that Events agent planning mode behavior is unchanged."""

    @pytest.fixture
    def mock_events_agent_planning(self):
        """Create an Events agent with mocked chat service for planning response."""
        planning_response = json.dumps({
            "events_output": {
                "events": [
                    {
                        "name": "Tokyo Marathon",
                        "date": "2025-03-02",
                        "area": "Shinjuku",
                        "link": "https://tokyo42195.org",
                        "note": "Major marathon event",
                        "source": {"title": "Tokyo Marathon Official", "url": "https://tokyo42195.org"}
                    }
                ],
                "notes": ["Great time to visit for sports events"]
            },
            "response": None
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkEventsAgent()
            agent.agent = MockChatAgent(planning_response)
            return agent

    @pytest.fixture
    def mock_events_agent_followup(self):
        """Create an Events agent that returns a follow-up question in planning mode."""
        followup_response = json.dumps({
            "events_output": None,
            "response": "Please provide the destination and travel dates to search for events."
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkEventsAgent()
            agent.agent = MockChatAgent(followup_response)
            return agent

    @pytest.mark.asyncio
    async def test_events_agent_planning_mode_returns_structured_output(
        self, mock_events_agent_planning
    ):
        """Test that planning mode returns structured EventsOutput."""
        plan_request = json.dumps({
            "mode": "plan",
            "destination_city": "Tokyo"
        })

        responses = []
        async for response in mock_events_agent_planning.stream(
            user_input=plan_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["is_task_complete"] is True
        assert responses[0]["require_user_input"] is False

        # Verify content is valid EventsOutput JSON
        content = json.loads(responses[0]["content"])
        assert "events" in content
        assert "notes" in content

    @pytest.mark.asyncio
    async def test_events_agent_planning_mode_no_mode_field(
        self, mock_events_agent_planning
    ):
        """Test that requests without mode field default to planning mode."""
        request_no_mode = "Find events in Tokyo"

        responses = []
        async for response in mock_events_agent_planning.stream(
            user_input=request_no_mode,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["is_task_complete"] is True
        # Verify content is valid EventsOutput JSON (planning mode)
        content = json.loads(responses[0]["content"])
        assert "events" in content

    @pytest.mark.asyncio
    async def test_events_agent_planning_mode_followup_is_incomplete(
        self, mock_events_agent_followup
    ):
        """Test that planning mode follow-up questions are marked incomplete."""
        # Request in planning mode (no mode = plan)
        plan_request = "Help me find events"

        responses = []
        async for response in mock_events_agent_followup.stream(
            user_input=plan_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        # In planning mode, response field means incomplete (needs more info)
        assert responses[0]["is_task_complete"] is False
        assert responses[0]["require_user_input"] is True
        assert "destination" in responses[0]["content"].lower()


class TestEventsAgentParseResponseQAMode:
    """Tests for parse_response() Q&A mode handling."""

    @pytest.fixture
    def events_agent(self):
        """Create an Events agent with mocked chat service."""
        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkEventsAgent()
            return agent

    def test_parse_response_qa_mode_returns_complete(self, events_agent):
        """Test that parse_response returns complete task for Q&A mode response."""
        # Set agent to Q&A mode
        events_agent._is_qa_mode = True

        response_json = json.dumps({
            "events_output": None,
            "response": "The festival runs from March 1-5."
        })

        result = events_agent.parse_response(response_json)

        assert result["is_task_complete"] is True
        assert result["require_user_input"] is False
        assert result["content"] == "The festival runs from March 1-5."

    def test_parse_response_planning_mode_response_returns_incomplete(self, events_agent):
        """Test that parse_response returns incomplete task for planning mode follow-up."""
        # Ensure planning mode (not Q&A)
        events_agent._is_qa_mode = False

        response_json = json.dumps({
            "events_output": None,
            "response": "What city would you like to find events in?"
        })

        result = events_agent.parse_response(response_json)

        assert result["is_task_complete"] is False
        assert result["require_user_input"] is True
        assert result["content"] == "What city would you like to find events in?"

    def test_parse_response_planning_mode_events_output_returns_complete(self, events_agent):
        """Test that parse_response returns complete task for planning mode structured output."""
        events_agent._is_qa_mode = False

        response_json = json.dumps({
            "events_output": {
                "events": [
                    {
                        "name": "Test Festival",
                        "date": "2025-03-01",
                        "area": "Downtown",
                        "link": "https://example.com",
                        "note": None,
                        "source": {"title": "Test", "url": "https://example.com"}
                    }
                ],
                "notes": []
            },
            "response": None
        })

        result = events_agent.parse_response(response_json)

        assert result["is_task_complete"] is True
        assert result["require_user_input"] is False
        # Content should be the serialized events_output
        content = json.loads(result["content"])
        assert "events" in content
