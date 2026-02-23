"""Unit tests for the FastAPI Direct API entry point.

Tests cover:
- ChatRequest and ChatResponse model validation
- POST /chat endpoint functionality
- GET /chat/stream SSE endpoint functionality
- Request validation and error handling
- Health check endpoint
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from src.orchestrator.models.workflow_state import Phase, WorkflowState
from src.orchestrator.api.app import (
    ChatRequest,
    ChatResponse,
    ChatStreamChunk,
    app,
)


# =============================================================================
# Model Tests
# =============================================================================


class TestChatRequest:
    """Tests for ChatRequest model validation."""

    def test_valid_request_with_session_id(self):
        """Test valid request with both message and session_id."""
        request = ChatRequest(message="Hello", session_id="session-123")
        assert request.message == "Hello"
        assert request.session_id == "session-123"

    def test_valid_request_without_session_id(self):
        """Test valid request with only message (session_id optional)."""
        request = ChatRequest(message="Hello")
        assert request.message == "Hello"
        assert request.session_id is None

    def test_empty_message_allowed(self):
        """Test that empty message string is allowed (routing will handle)."""
        request = ChatRequest(message="")
        assert request.message == ""

    def test_message_required(self):
        """Test that message field is required."""
        with pytest.raises(ValueError):
            ChatRequest()

    def test_long_message(self):
        """Test that long messages are accepted."""
        long_message = "x" * 10000
        request = ChatRequest(message=long_message)
        assert request.message == long_message


class TestChatResponse:
    """Tests for ChatResponse model validation."""

    def test_valid_response_all_fields(self):
        """Test valid response with all fields."""
        response = ChatResponse(
            message="Hello back!",
            session_id="session-123",
            consultation_id="consult-456",
            data={"key": "value"},
        )
        assert response.message == "Hello back!"
        assert response.session_id == "session-123"
        assert response.consultation_id == "consult-456"
        assert response.data == {"key": "value"}

    def test_valid_response_minimal(self):
        """Test valid response with only required fields."""
        response = ChatResponse(message="Hello", session_id="session-123")
        assert response.message == "Hello"
        assert response.session_id == "session-123"
        assert response.consultation_id is None
        assert response.data is None

    def test_response_serialization(self):
        """Test that response serializes correctly to JSON."""
        response = ChatResponse(
            message="Test",
            session_id="sess-1",
            consultation_id="con-1",
        )
        json_dict = response.model_dump()
        assert json_dict["message"] == "Test"
        assert json_dict["session_id"] == "sess-1"
        assert json_dict["consultation_id"] == "con-1"


class TestChatStreamChunk:
    """Tests for ChatStreamChunk model validation."""

    def test_valid_chunk_all_fields(self):
        """Test valid chunk with all fields."""
        chunk = ChatStreamChunk(
            message="Processing...",
            session_id="session-123",
            consultation_id="consult-456",
            is_complete=False,
            require_user_input=False,
            data={"progress": 50},
        )
        assert chunk.message == "Processing..."
        assert chunk.session_id == "session-123"
        assert chunk.consultation_id == "consult-456"
        assert chunk.is_complete is False
        assert chunk.require_user_input is False
        assert chunk.data == {"progress": 50}

    def test_valid_chunk_minimal(self):
        """Test valid chunk with only required fields."""
        chunk = ChatStreamChunk(message="Hello", session_id="sess-1")
        assert chunk.message == "Hello"
        assert chunk.session_id == "sess-1"
        assert chunk.is_complete is False
        assert chunk.require_user_input is False

    def test_chunk_complete_state(self):
        """Test chunk representing complete state."""
        chunk = ChatStreamChunk(
            message="Done!",
            session_id="sess-1",
            is_complete=True,
        )
        assert chunk.is_complete is True

    def test_chunk_input_required_state(self):
        """Test chunk representing input required state."""
        chunk = ChatStreamChunk(
            message="Please provide more details",
            session_id="sess-1",
            require_user_input=True,
        )
        assert chunk.require_user_input is True

    def test_chunk_json_serialization(self):
        """Test that chunk serializes correctly for SSE."""
        chunk = ChatStreamChunk(
            message="Test",
            session_id="sess-1",
            is_complete=True,
        )
        json_str = chunk.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["message"] == "Test"
        assert parsed["session_id"] == "sess-1"
        assert parsed["is_complete"] is True


# =============================================================================
# Helper for creating mock agent
# =============================================================================


def create_mock_agent():
    """Create a mock OrchestratorAgent for testing."""
    mock_agent = MagicMock()

    async def mock_process_request(message, session_id, history=None, history_seq=None):
        """Mock _process_intelligent_request that yields test chunks."""
        yield {
            "content": f"Response to: {message}",
            "is_task_complete": True,
            "require_user_input": False,
            "data": {
                "response": {
                    "message": f"Response to: {message}",
                    "session_id": session_id,
                    "consultation_id": "test-consultation-123",
                }
            },
        }

    mock_agent._process_intelligent_request = mock_process_request
    return mock_agent


# =============================================================================
# Endpoint Tests with TestClient
# =============================================================================


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_check(self):
        """Test health check returns healthy status."""
        # Health check doesn't need the full lifespan, use override
        with patch.object(app, "state", MagicMock()):
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "healthy"
                assert data["service"] == "orchestrator-api"


class TestChatEndpoint:
    """Tests for the POST /chat endpoint."""

    def test_chat_endpoint_with_session_id(self):
        """Test chat endpoint with provided session_id."""
        mock_agent = create_mock_agent()

        with TestClient(app, raise_server_exceptions=False) as client:
            # Override app state
            app.state.agent = mock_agent
            app.state.executor = MagicMock()

            response = client.post(
                "/chat",
                json={"message": "Plan a trip to Tokyo", "session_id": "test-session"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["message"] == "Response to: Plan a trip to Tokyo"
            assert data["session_id"] == "test-session"
            assert data["consultation_id"] == "test-consultation-123"

    def test_chat_endpoint_without_session_id(self):
        """Test chat endpoint generates session_id when not provided."""
        mock_agent = create_mock_agent()

        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.agent = mock_agent
            app.state.executor = MagicMock()

            response = client.post(
                "/chat",
                json={"message": "Hello"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["message"] == "Response to: Hello"
            # Session ID should be generated (UUID format)
            assert len(data["session_id"]) == 36  # UUID length

    def test_chat_endpoint_missing_message(self):
        """Test chat endpoint rejects request without message."""
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post("/chat", json={})
            assert response.status_code == 422  # Validation error

    def test_chat_endpoint_invalid_json(self):
        """Test chat endpoint rejects invalid JSON."""
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/chat",
                content="not json",
                headers={"Content-Type": "application/json"},
            )
            assert response.status_code == 422

    def test_chat_endpoint_long_message(self):
        """Test chat endpoint handles long messages."""
        mock_agent = create_mock_agent()
        long_message = "Plan a detailed trip " * 500

        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.agent = mock_agent
            app.state.executor = MagicMock()

            response = client.post(
                "/chat",
                json={"message": long_message, "session_id": "test-session"},
            )

            assert response.status_code == 200
            data = response.json()
            assert "Response to: " in data["message"]


class TestChatStreamEndpoint:
    """Tests for the GET /chat/stream SSE endpoint."""

    def test_chat_stream_endpoint(self):
        """Test chat stream endpoint returns SSE format."""
        mock_agent = create_mock_agent()

        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.agent = mock_agent
            app.state.executor = MagicMock()

            response = client.get(
                "/chat/stream",
                params={"message": "Hello", "session_id": "test-session"},
            )

            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

            # Parse SSE events
            content = response.content.decode()
            assert "data:" in content

            # Extract JSON from SSE format
            lines = content.strip().split("\n")
            for line in lines:
                if line.startswith("data: "):
                    json_data = json.loads(line[6:])
                    assert "message" in json_data
                    assert "session_id" in json_data
                    assert json_data["session_id"] == "test-session"

    def test_chat_stream_generates_session_id(self):
        """Test chat stream generates session_id when not provided."""
        mock_agent = create_mock_agent()

        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.agent = mock_agent
            app.state.executor = MagicMock()

            response = client.get(
                "/chat/stream",
                params={"message": "Hello"},
            )

            assert response.status_code == 200
            content = response.content.decode()

            # Extract and verify session_id was generated
            for line in content.strip().split("\n"):
                if line.startswith("data: "):
                    json_data = json.loads(line[6:])
                    assert len(json_data["session_id"]) == 36  # UUID length

    def test_chat_stream_missing_message(self):
        """Test chat stream rejects request without message."""
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/chat/stream")
            assert response.status_code == 422  # Validation error

    def test_chat_stream_headers(self):
        """Test chat stream returns correct headers for SSE."""
        mock_agent = create_mock_agent()

        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.agent = mock_agent
            app.state.executor = MagicMock()

            response = client.get(
                "/chat/stream",
                params={"message": "Hello", "session_id": "test"},
            )

            # Check SSE-specific headers
            assert "text/event-stream" in response.headers["content-type"]


class TestMultipleChunks:
    """Tests for handling multiple chunks from the agent."""

    def test_chat_collects_final_chunk(self):
        """Test POST /chat returns the final chunk's content."""
        mock_agent = MagicMock()

        async def multi_chunk_response(message, session_id, history=None, history_seq=None):
            """Mock that yields multiple chunks."""
            yield {
                "content": "Processing...",
                "is_task_complete": False,
                "require_user_input": False,
                "data": None,
            }
            yield {
                "content": "Final answer",
                "is_task_complete": True,
                "require_user_input": False,
                "data": {"response": {"consultation_id": "final-consult"}},
            }

        mock_agent._process_intelligent_request = multi_chunk_response

        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.agent = mock_agent
            app.state.executor = MagicMock()

            response = client.post(
                "/chat",
                json={"message": "Test", "session_id": "test-session"},
            )

            assert response.status_code == 200
            data = response.json()
            # Should have final chunk's content
            assert data["message"] == "Final answer"
            assert data["consultation_id"] == "final-consult"

    def test_stream_yields_all_chunks(self):
        """Test GET /chat/stream yields all chunks as SSE events."""
        mock_agent = MagicMock()

        async def multi_chunk_response(message, session_id, history=None, history_seq=None):
            """Mock that yields multiple chunks."""
            yield {
                "content": "Chunk 1",
                "is_task_complete": False,
                "require_user_input": False,
                "data": None,
            }
            yield {
                "content": "Chunk 2",
                "is_task_complete": False,
                "require_user_input": False,
                "data": None,
            }
            yield {
                "content": "Final",
                "is_task_complete": True,
                "require_user_input": False,
                "data": {"response": {"consultation_id": "test-con"}},
            }

        mock_agent._process_intelligent_request = multi_chunk_response

        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.agent = mock_agent
            app.state.executor = MagicMock()

            response = client.get(
                "/chat/stream",
                params={"message": "Test", "session_id": "test"},
            )

            content = response.content.decode()
            events = [
                line[6:]
                for line in content.strip().split("\n")
                if line.startswith("data: ")
            ]

            # Should have 3 events
            assert len(events) == 3

            # Parse and verify chunks
            chunks = [json.loads(e) for e in events]
            assert chunks[0]["message"] == "Chunk 1"
            assert chunks[0]["is_complete"] is False
            assert chunks[1]["message"] == "Chunk 2"
            assert chunks[2]["message"] == "Final"
            assert chunks[2]["is_complete"] is True


class TestErrorHandling:
    """Tests for error handling in the API."""

    def test_chat_handles_agent_error(self):
        """Test POST /chat handles agent errors gracefully."""
        mock_agent = MagicMock()

        async def error_response(message, session_id, history=None, history_seq=None):
            """Mock that yields an error response."""
            yield {
                "content": "Error occurred",
                "is_task_complete": False,
                "require_user_input": True,
                "data": {"error": {"code": "INTERNAL_ERROR"}},
            }

        mock_agent._process_intelligent_request = error_response

        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.agent = mock_agent
            app.state.executor = MagicMock()

            response = client.post(
                "/chat",
                json={"message": "Test", "session_id": "test"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["message"] == "Error occurred"
            assert "error" in data["data"]

    def test_stream_handles_agent_error(self):
        """Test GET /chat/stream handles agent errors gracefully."""
        mock_agent = MagicMock()

        async def error_response(message, session_id, history=None, history_seq=None):
            """Mock that yields an error response."""
            yield {
                "content": "Error occurred",
                "is_task_complete": False,
                "require_user_input": True,
                "data": {"error": {"code": "AGENT_TIMEOUT"}},
            }

        mock_agent._process_intelligent_request = error_response

        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.agent = mock_agent
            app.state.executor = MagicMock()

            response = client.get(
                "/chat/stream",
                params={"message": "Test", "session_id": "test"},
            )

            content = response.content.decode()
            for line in content.strip().split("\n"):
                if line.startswith("data: "):
                    chunk = json.loads(line[6:])
                    assert chunk["require_user_input"] is True

    def test_stream_handles_unexpected_generator_exception(self):
        """Test GET /chat/stream emits an error chunk when generator raises."""
        mock_agent = MagicMock()

        async def broken_response(message, session_id, history=None, history_seq=None):
            raise RuntimeError("downstream stream crashed")
            yield  # pragma: no cover

        mock_agent._process_intelligent_request = broken_response

        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.agent = mock_agent
            app.state.executor = MagicMock()

            response = client.get(
                "/chat/stream",
                params={"message": "Test", "session_id": "test"},
            )

            assert response.status_code == 200
            content = response.content.decode()
            events = [
                json.loads(line[6:])
                for line in content.strip().split("\n")
                if line.startswith("data: ")
            ]
            assert len(events) == 1
            assert events[0]["require_user_input"] is True
            assert events[0]["is_complete"] is True


class TestConsultationIdExtraction:
    """Tests for consultation_id extraction from response data."""

    def test_extracts_consultation_id_from_nested_response(self):
        """Test consultation_id extraction from nested response data."""
        mock_agent = MagicMock()

        async def response_with_consultation(message, session_id, history=None, history_seq=None):
            yield {
                "content": "Trip planned!",
                "is_task_complete": True,
                "require_user_input": False,
                "data": {
                    "response": {
                        "message": "Trip planned!",
                        "consultation_id": "nested-consult-id",
                        "session_id": session_id,
                    }
                },
            }

        mock_agent._process_intelligent_request = response_with_consultation

        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.agent = mock_agent
            app.state.executor = MagicMock()

            response = client.post(
                "/chat",
                json={"message": "Plan trip", "session_id": "test"},
            )

            data = response.json()
            assert data["consultation_id"] == "nested-consult-id"

    def test_handles_missing_consultation_id(self):
        """Test handling when consultation_id is not present."""
        mock_agent = MagicMock()

        async def response_without_consultation(message, session_id, history=None, history_seq=None):
            yield {
                "content": "Just a question answer",
                "is_task_complete": True,
                "require_user_input": False,
                "data": {"response": {"message": "Just a question answer"}},
            }

        mock_agent._process_intelligent_request = response_without_consultation

        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.agent = mock_agent
            app.state.executor = MagicMock()

            response = client.post(
                "/chat",
                json={"message": "What's Tokyo like?", "session_id": "test"},
            )

            data = response.json()
            assert data["consultation_id"] is None

    def test_stream_tracks_consultation_id_across_chunks(self):
        """Test stream endpoint tracks consultation_id across multiple chunks."""
        mock_agent = MagicMock()

        async def multi_chunk_with_consultation(message, session_id, history=None, history_seq=None):
            yield {
                "content": "Starting...",
                "is_task_complete": False,
                "data": None,
            }
            yield {
                "content": "Planning...",
                "is_task_complete": False,
                "data": {"response": {"consultation_id": "mid-chunk-consult"}},
            }
            yield {
                "content": "Done!",
                "is_task_complete": True,
                "data": None,  # No consultation_id in final chunk
            }

        mock_agent._process_intelligent_request = multi_chunk_with_consultation

        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.agent = mock_agent
            app.state.executor = MagicMock()

            response = client.get(
                "/chat/stream",
                params={"message": "Plan trip", "session_id": "test"},
            )

            content = response.content.decode()
            events = [
                json.loads(line[6:])
                for line in content.strip().split("\n")
                if line.startswith("data: ")
            ]

            # Chunk 1 should have no consultation_id
            assert events[0]["consultation_id"] is None

            # Chunk 2 should have the consultation_id
            assert events[1]["consultation_id"] == "mid-chunk-consult"

            # Chunk 3 should preserve the consultation_id from previous chunk
            assert events[2]["consultation_id"] == "mid-chunk-consult"


class TestSessionEndpoints:
    """Tests for session state and workflow event endpoints."""

    def test_get_session_state_after_chat(self):
        """GET /sessions/{id} returns session snapshot fields."""
        mock_agent = MagicMock()

        async def chat_response(message, session_id, history=None, history_seq=None, event=None):
            yield {
                "content": "I can help you plan this trip.",
                "is_task_complete": True,
                "require_user_input": True,
                "data": {
                    "response": {
                        "status": {"phase": "clarification", "checkpoint": "trip_spec_approval"},
                        "ui": {
                            "actions": [
                                {
                                    "label": "Approve Trip Spec",
                                    "event": {
                                        "type": "approve_checkpoint",
                                        "checkpoint_id": "trip_spec_approval",
                                    },
                                }
                            ],
                            "text_input": False,
                        },
                    }
                },
            }

        mock_agent._process_intelligent_request = chat_response

        state = WorkflowState(
            session_id="test-session",
            consultation_id="cons-123",
            phase=Phase.CLARIFICATION,
            checkpoint="trip_spec_approval",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.agent = mock_agent
            app.state.executor = MagicMock()
            app.state.workflow_store = MagicMock()
            app.state.workflow_store.get_by_session = AsyncMock(return_value=state)
            app.state.discovery_job_store = MagicMock()
            app.state.discovery_job_store.get_job = AsyncMock(return_value=None)

            chat_response_obj = client.post(
                "/chat",
                json={"message": "Plan a weekend in Seattle", "session_id": "test-session"},
            )
            assert chat_response_obj.status_code == 200

            response = client.get("/sessions/test-session")
            assert response.status_code == 200
            data = response.json()
            assert data["session_id"] == "test-session"
            assert data["phase"] == "clarification"
            assert data["checkpoint"] == "trip_spec_approval"
            assert data["text_input_enabled"] is False
            assert len(data["messages"]) >= 2
            assert data["pending_actions"][0]["event"]["type"] == "approve_checkpoint"

    def test_post_session_event_forwards_structured_event(self):
        """POST /sessions/{id}/event forwards WorkflowEvent payload to orchestrator."""
        mock_agent = MagicMock()
        received_event: dict[str, object] = {}

        async def event_response(message, session_id, history=None, history_seq=None, event=None):
            nonlocal received_event
            received_event = event or {}
            yield {
                "content": "Checkpoint approved. Starting discovery.",
                "is_task_complete": True,
                "require_user_input": False,
                "data": {"response": {"status": {"phase": "discovery_in_progress"}}},
            }

        mock_agent._process_intelligent_request = event_response

        state = WorkflowState(
            session_id="test-session",
            consultation_id="cons-123",
            phase=Phase.DISCOVERY_IN_PROGRESS,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.agent = mock_agent
            app.state.executor = MagicMock()
            app.state.workflow_store = MagicMock()
            app.state.workflow_store.get_by_session = AsyncMock(return_value=state)
            app.state.discovery_job_store = MagicMock()
            app.state.discovery_job_store.get_job = AsyncMock(return_value=None)

            response = client.post(
                "/sessions/test-session/event",
                json={
                    "type": "approve_checkpoint",
                    "checkpoint_id": "trip_spec_approval",
                },
            )

            assert response.status_code == 200
            assert received_event["type"] == "approve_checkpoint"
            assert received_event["checkpoint_id"] == "trip_spec_approval"

    def test_post_session_event_requires_message_for_free_text(self):
        """POST /sessions/{id}/event rejects free_text when message is missing."""
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/sessions/test-session/event",
                json={"type": "free_text"},
            )
            assert response.status_code == 400

    def test_session_endpoint_returns_404_for_unknown_session(self):
        """GET /sessions/{id} returns 404 when no workflow state exists."""
        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.workflow_store = MagicMock()
            app.state.workflow_store.get_by_session = AsyncMock(return_value=None)
            response = client.get("/sessions/missing-session")
            assert response.status_code == 404


class TestAgentRegistryEndpoints:
    """Tests for agent registry API endpoints."""

    def test_get_agents_returns_registry_list(self):
        """GET /agents returns registered agents."""
        mock_registry_api = MagicMock()
        mock_registry_api.list_agents = AsyncMock(
            return_value=[
                {
                    "agentId": "clarifier",
                    "name": "Clarifier Agent",
                    "type": "discovery",
                    "status": "online",
                    "url": "http://localhost:8001",
                    "capabilities": ["collect requirements"],
                }
            ]
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.agent_registry_api = mock_registry_api
            response = client.get("/agents")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["agentId"] == "clarifier"

    def test_get_agent_card_returns_details(self):
        """GET /agents/{id}/card returns well-known agent card."""
        mock_registry_api = MagicMock()
        mock_registry_api.get_agent_card = AsyncMock(
            return_value={
                "name": "Clarifier Agent",
                "description": "Collects trip requirements",
                "version": "1.0.0",
                "url": "http://localhost:8001",
                "protocolVersion": "1.0",
                "skills": [],
                "capabilities": {"streaming": True},
                "defaultInputModes": ["text"],
                "defaultOutputModes": ["text"],
            }
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.agent_registry_api = mock_registry_api
            response = client.get("/agents/clarifier/card")
            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "Clarifier Agent"

    def test_post_and_delete_custom_agent(self):
        """POST /agents adds a custom agent and DELETE removes it."""
        mock_registry_api = MagicMock()
        mock_registry_api.add_custom_agent = AsyncMock(
            return_value={
                "agentId": "custom-weather",
                "name": "Weather Agent",
                "type": "custom",
                "status": "online",
                "url": "http://localhost:8999",
                "capabilities": ["weather"],
            }
        )
        mock_registry_api.remove_custom_agent = AsyncMock(return_value=True)

        with TestClient(app, raise_server_exceptions=False) as client:
            app.state.agent_registry_api = mock_registry_api

            create_response = client.post(
                "/agents",
                json={"name": "Weather Agent", "url": "http://localhost:8999"},
            )
            assert create_response.status_code == 200
            assert create_response.json()["type"] == "custom"

            delete_response = client.delete("/agents/custom-weather")
            assert delete_response.status_code == 200
            assert delete_response.json()["deleted"] is True


class TestCorsConfiguration:
    """Tests for CORS behavior."""

    def test_cors_preflight_allows_vite_origin(self):
        """CORS preflight for localhost:5173 is allowed."""
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.options(
                "/chat",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "POST",
                },
            )
            assert response.status_code == 200
            assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
