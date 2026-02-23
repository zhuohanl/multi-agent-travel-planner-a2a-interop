"""
Unit tests for POI Search agent Q&A mode.

Tests ORCH-014: Add Q&A mode to POI agent prompt and response parsing.

Per design doc (Tool Definitions section):
- Q&A mode is signaled by "mode": "qa" in the request JSON
- In Q&A mode, agent answers questions and returns text response
- Q&A mode sets is_task_complete=True (single-turn)
- Planning mode (mode="plan" or no mode) returns structured SearchOutput
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from collections.abc import AsyncIterable
from typing import Any

from src.agents.poi_search_agent.agent import AgentFrameworkPOISearchAgent
from src.shared.models import POISearchResponse, SearchOutput, POI, Source


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


class TestPOIAgentDetectsQAMode:
    """Tests that POI agent correctly detects Q&A mode from request."""

    @pytest.fixture
    def poi_agent(self):
        """Create a POI agent with mocked chat service."""
        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkPOISearchAgent()
            return agent

    def test_poi_agent_detects_qa_mode_from_json(self, poi_agent):
        """Test that _detect_qa_mode returns True for Q&A mode requests."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "Is the Senso-ji temple free to enter?",
            "context": {"destination": "Tokyo"}
        })

        assert poi_agent._detect_qa_mode(qa_request) is True

    def test_poi_agent_detects_planning_mode_explicit(self, poi_agent):
        """Test that _detect_qa_mode returns False for explicit planning mode."""
        plan_request = json.dumps({
            "mode": "plan",
            "destination_city": "Tokyo"
        })

        assert poi_agent._detect_qa_mode(plan_request) is False

    def test_poi_agent_detects_planning_mode_no_mode_field(self, poi_agent):
        """Test that _detect_qa_mode returns False when no mode field (defaults to plan)."""
        request_without_mode = json.dumps({
            "destination_city": "Tokyo"
        })

        assert poi_agent._detect_qa_mode(request_without_mode) is False

    def test_poi_agent_detects_planning_mode_plain_text(self, poi_agent):
        """Test that _detect_qa_mode returns False for plain text requests."""
        plain_text = "Find attractions in Tokyo"

        assert poi_agent._detect_qa_mode(plain_text) is False

    def test_poi_agent_detects_planning_mode_invalid_json(self, poi_agent):
        """Test that _detect_qa_mode returns False for invalid JSON."""
        invalid_json = '{"mode": "qa", broken'

        assert poi_agent._detect_qa_mode(invalid_json) is False


class TestPOIAgentQAReturnsTextResponse:
    """Tests that POI agent returns text response in Q&A mode."""

    @pytest.fixture
    def mock_poi_agent_qa(self):
        """Create a POI agent with mocked chat service configured for Q&A response."""
        qa_response = json.dumps({
            "search_output": None,
            "response": "Yes, Senso-ji Temple is free to enter."
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkPOISearchAgent()
            agent.agent = MockChatAgent(qa_response)
            return agent

    @pytest.mark.asyncio
    async def test_poi_agent_qa_returns_text_response_via_stream(
        self, mock_poi_agent_qa
    ):
        """Test that Q&A mode returns text response via stream()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "Is the Senso-ji temple free to enter?"
        })

        responses = []
        async for response in mock_poi_agent_qa.stream(
            user_input=qa_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["content"] == "Yes, Senso-ji Temple is free to enter."

    @pytest.mark.asyncio
    async def test_poi_agent_qa_returns_text_response_via_invoke(
        self, mock_poi_agent_qa
    ):
        """Test that Q&A mode returns text response via invoke()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "Is the Senso-ji temple free to enter?"
        })

        response = await mock_poi_agent_qa.invoke(
            user_input=qa_request,
            session_id="test_session",
        )

        assert response["content"] == "Yes, Senso-ji Temple is free to enter."


class TestPOIAgentQASetsTaskComplete:
    """Tests that POI agent sets is_task_complete=True in Q&A mode."""

    @pytest.fixture
    def mock_poi_agent_qa(self):
        """Create a POI agent with mocked chat service configured for Q&A response."""
        qa_response = json.dumps({
            "search_output": None,
            "response": "The museum is open from 9 AM to 5 PM."
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkPOISearchAgent()
            agent.agent = MockChatAgent(qa_response)
            return agent

    @pytest.mark.asyncio
    async def test_poi_agent_qa_sets_task_complete_via_stream(
        self, mock_poi_agent_qa
    ):
        """Test that Q&A mode sets is_task_complete=True via stream()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "What are the museum hours?"
        })

        responses = []
        async for response in mock_poi_agent_qa.stream(
            user_input=qa_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["is_task_complete"] is True
        assert responses[0]["require_user_input"] is False

    @pytest.mark.asyncio
    async def test_poi_agent_qa_sets_task_complete_via_invoke(
        self, mock_poi_agent_qa
    ):
        """Test that Q&A mode sets is_task_complete=True via invoke()."""
        qa_request = json.dumps({
            "mode": "qa",
            "question": "What are the museum hours?"
        })

        response = await mock_poi_agent_qa.invoke(
            user_input=qa_request,
            session_id="test_session",
        )

        assert response["is_task_complete"] is True
        assert response["require_user_input"] is False


class TestPOIAgentPlanningModeUnchanged:
    """Tests that POI agent planning mode behavior is unchanged."""

    @pytest.fixture
    def mock_poi_agent_planning(self):
        """Create a POI agent with mocked chat service for planning response."""
        planning_response = json.dumps({
            "search_output": {
                "pois": [
                    {
                        "name": "Senso-ji Temple",
                        "area": "Asakusa",
                        "tags": ["temple", "historic", "free"],
                        "estCost": 0,
                        "currency": "JPY",
                        "openHint": "6 AM - 5 PM",
                        "source": {"title": "Tokyo Guide", "url": "https://example.com"}
                    }
                ],
                "notes": ["Great options for sightseeing"]
            },
            "response": None
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkPOISearchAgent()
            agent.agent = MockChatAgent(planning_response)
            return agent

    @pytest.fixture
    def mock_poi_agent_followup(self):
        """Create a POI agent that returns a follow-up question in planning mode."""
        followup_response = json.dumps({
            "search_output": None,
            "response": "Please provide the destination city to continue."
        })

        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkPOISearchAgent()
            agent.agent = MockChatAgent(followup_response)
            return agent

    @pytest.mark.asyncio
    async def test_poi_agent_planning_mode_returns_structured_output(
        self, mock_poi_agent_planning
    ):
        """Test that planning mode returns structured SearchOutput."""
        plan_request = json.dumps({
            "mode": "plan",
            "destination_city": "Tokyo"
        })

        responses = []
        async for response in mock_poi_agent_planning.stream(
            user_input=plan_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["is_task_complete"] is True
        assert responses[0]["require_user_input"] is False

        # Verify content is valid SearchOutput JSON
        content = json.loads(responses[0]["content"])
        assert "pois" in content
        assert "notes" in content

    @pytest.mark.asyncio
    async def test_poi_agent_planning_mode_no_mode_field(
        self, mock_poi_agent_planning
    ):
        """Test that requests without mode field default to planning mode."""
        request_no_mode = "Find attractions in Tokyo"

        responses = []
        async for response in mock_poi_agent_planning.stream(
            user_input=request_no_mode,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        assert responses[0]["is_task_complete"] is True
        # Verify content is valid SearchOutput JSON (planning mode)
        content = json.loads(responses[0]["content"])
        assert "pois" in content

    @pytest.mark.asyncio
    async def test_poi_agent_planning_mode_followup_is_incomplete(
        self, mock_poi_agent_followup
    ):
        """Test that planning mode follow-up questions are marked incomplete."""
        # Request in planning mode (no mode = plan)
        plan_request = "Help me find attractions"

        responses = []
        async for response in mock_poi_agent_followup.stream(
            user_input=plan_request,
            session_id="test_session",
        ):
            responses.append(response)

        assert len(responses) == 1
        # In planning mode, response field means incomplete (needs more info)
        assert responses[0]["is_task_complete"] is False
        assert responses[0]["require_user_input"] is True
        assert "destination city" in responses[0]["content"].lower()


class TestPOIAgentParseResponseQAMode:
    """Tests for parse_response() Q&A mode handling."""

    @pytest.fixture
    def poi_agent(self):
        """Create a POI agent with mocked chat service."""
        with patch(
            "src.shared.agents.base_agent.get_chat_completion_service"
        ) as mock_service:
            mock_service.return_value = MagicMock()
            agent = AgentFrameworkPOISearchAgent()
            return agent

    def test_parse_response_qa_mode_returns_complete(self, poi_agent):
        """Test that parse_response returns complete task for Q&A mode response."""
        # Set agent to Q&A mode
        poi_agent._is_qa_mode = True

        response_json = json.dumps({
            "search_output": None,
            "response": "The temple is open 24 hours."
        })

        result = poi_agent.parse_response(response_json)

        assert result["is_task_complete"] is True
        assert result["require_user_input"] is False
        assert result["content"] == "The temple is open 24 hours."

    def test_parse_response_planning_mode_response_returns_incomplete(self, poi_agent):
        """Test that parse_response returns incomplete task for planning mode follow-up."""
        # Ensure planning mode (not Q&A)
        poi_agent._is_qa_mode = False

        response_json = json.dumps({
            "search_output": None,
            "response": "What city would you like to visit?"
        })

        result = poi_agent.parse_response(response_json)

        assert result["is_task_complete"] is False
        assert result["require_user_input"] is True
        assert result["content"] == "What city would you like to visit?"

    def test_parse_response_planning_mode_search_output_returns_complete(self, poi_agent):
        """Test that parse_response returns complete task for planning mode structured output."""
        poi_agent._is_qa_mode = False

        response_json = json.dumps({
            "search_output": {
                "pois": [
                    {
                        "name": "Test Attraction",
                        "area": "Downtown",
                        "tags": ["museum"],
                        "estCost": 20,
                        "currency": "USD",
                        "openHint": "9 AM - 5 PM",
                        "source": {"title": "Test", "url": "https://example.com"}
                    }
                ],
                "notes": []
            },
            "response": None
        })

        result = poi_agent.parse_response(response_json)

        assert result["is_task_complete"] is True
        assert result["require_user_input"] is False
        # Content should be the serialized search_output
        content = json.loads(result["content"])
        assert "pois" in content
