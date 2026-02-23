"""Unit tests for A2A-Azure bridge inbound module."""

import pytest
from uuid import UUID

from src.shared.a2a_azure_bridge.inbound import (
    AzureAIInput,
    A2AResponseEnvelope,
    AzureStreamingChunk,
    translate_a2a_to_azure,
    translate_azure_to_a2a,
    translate_azure_streaming_chunk,
    _extract_azure_response_text,
    _extract_text_from_content_array,
    _parse_azure_streaming_chunk,
)


# =============================================================================
# TEST: AzureAIInput DATACLASS
# =============================================================================


class TestAzureAIInput:
    """Tests for AzureAIInput dataclass."""

    def test_create_with_required_fields(self):
        """Test creating AzureAIInput with required fields."""
        input_data = AzureAIInput(
            message="Hello",
            session_id="sess_123",
        )
        assert input_data.message == "Hello"
        assert input_data.session_id == "sess_123"
        assert input_data.context_id is None
        assert input_data.task_id is None
        assert input_data.metadata is None

    def test_create_with_all_fields(self):
        """Test creating AzureAIInput with all fields."""
        metadata = {"history": [], "historySeq": 0}
        input_data = AzureAIInput(
            message="Plan a trip",
            session_id="sess_456",
            context_id="ctx_789",
            task_id="task_012",
            metadata=metadata,
        )
        assert input_data.message == "Plan a trip"
        assert input_data.session_id == "sess_456"
        assert input_data.context_id == "ctx_789"
        assert input_data.task_id == "task_012"
        assert input_data.metadata == metadata


# =============================================================================
# TEST: A2AResponseEnvelope DATACLASS
# =============================================================================


class TestA2AResponseEnvelope:
    """Tests for A2AResponseEnvelope dataclass."""

    def test_create_with_text_only(self):
        """Test creating response envelope with text only."""
        envelope = A2AResponseEnvelope(text="Hello world")
        assert envelope.text == "Hello world"
        assert envelope.context_id is None
        assert envelope.task_id is None
        assert envelope.is_complete is False
        assert envelope.requires_input is False
        assert envelope.status == "working"
        assert envelope.metadata == {}

    def test_create_with_all_fields(self):
        """Test creating response envelope with all fields."""
        envelope = A2AResponseEnvelope(
            text="Trip planned",
            context_id="ctx_123",
            task_id="task_456",
            is_complete=True,
            requires_input=False,
            status="completed",
            metadata={"key": "value"},
        )
        assert envelope.text == "Trip planned"
        assert envelope.context_id == "ctx_123"
        assert envelope.task_id == "task_456"
        assert envelope.is_complete is True
        assert envelope.requires_input is False
        assert envelope.status == "completed"
        assert envelope.metadata == {"key": "value"}

    def test_to_dict_basic(self):
        """Test to_dict with basic response."""
        envelope = A2AResponseEnvelope(text="Hello")
        result = envelope.to_dict()

        assert "message" in result
        assert result["message"]["role"] == "assistant"
        assert result["message"]["parts"][0]["kind"] == "text"
        assert result["message"]["parts"][0]["text"] == "Hello"
        assert "messageId" in result["message"]

        assert "status" in result
        assert result["status"]["state"] == "working"

        # No context_id or task_id when None
        assert "contextId" not in result
        assert "taskId" not in result

    def test_to_dict_with_context_and_task(self):
        """Test to_dict includes context_id and task_id when set."""
        envelope = A2AResponseEnvelope(
            text="Response",
            context_id="ctx_123",
            task_id="task_456",
        )
        result = envelope.to_dict()

        assert result["contextId"] == "ctx_123"
        assert result["taskId"] == "task_456"

    def test_to_dict_with_metadata(self):
        """Test to_dict includes metadata when set."""
        envelope = A2AResponseEnvelope(
            text="Response",
            metadata={"lastSeenSeq": 5},
        )
        result = envelope.to_dict()

        assert result["metadata"] == {"lastSeenSeq": 5}

    def test_to_dict_message_id_is_uuid(self):
        """Test that messageId is a valid UUID hex."""
        envelope = A2AResponseEnvelope(text="Test")
        result = envelope.to_dict()
        message_id = result["message"]["messageId"]

        # Should be a 32-character hex string (UUID without dashes)
        assert len(message_id) == 32
        UUID(message_id)  # Should not raise


# =============================================================================
# TEST: translate_a2a_to_azure (BOUNDARY #1)
# =============================================================================


class TestTranslateA2AToAzure:
    """Tests for translate_a2a_to_azure function."""

    def test_basic_request(self):
        """Test translating a basic A2A request."""
        request = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "Plan a trip to Tokyo"}],
            },
            "sessionId": "sess_abc123",
        }

        result = translate_a2a_to_azure(request)

        assert isinstance(result, AzureAIInput)
        assert result.message == "Plan a trip to Tokyo"
        assert result.session_id == "sess_abc123"
        assert result.context_id is None
        assert result.task_id is None

    def test_request_with_context_id(self):
        """Test request with contextId is preserved."""
        request = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "Yes, those dates work"}],
                "contextId": "ctx_multi_turn",
            },
            "sessionId": "sess_xyz",
        }

        result = translate_a2a_to_azure(request)

        assert result.message == "Yes, those dates work"
        assert result.context_id == "ctx_multi_turn"

    def test_request_with_task_id(self):
        """Test request with taskId is preserved."""
        request = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "Continue"}],
                "contextId": "ctx_123",
                "taskId": "task_456",
            },
            "sessionId": "sess_789",
        }

        result = translate_a2a_to_azure(request)

        assert result.task_id == "task_456"
        assert result.context_id == "ctx_123"

    def test_request_with_metadata(self):
        """Test request with metadata is preserved."""
        request = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "Message with history"}],
                "metadata": {
                    "history": [{"role": "user", "content": "Previous"}],
                    "historySeq": 1,
                },
            },
            "sessionId": "sess_001",
        }

        result = translate_a2a_to_azure(request)

        assert result.metadata is not None
        assert result.metadata["historySeq"] == 1
        assert len(result.metadata["history"]) == 1

    def test_multiple_text_parts_concatenated(self):
        """Test that multiple text parts are concatenated."""
        request = {
            "message": {
                "role": "user",
                "parts": [
                    {"kind": "text", "text": "Hello"},
                    {"kind": "text", "text": "World"},
                ],
            },
            "sessionId": "sess_multi",
        }

        result = translate_a2a_to_azure(request)

        assert result.message == "Hello World"

    def test_string_parts_handled(self):
        """Test that string parts (not dicts) are handled."""
        request = {
            "message": {
                "role": "user",
                "parts": ["Just a string"],
            },
            "sessionId": "sess_string",
        }

        result = translate_a2a_to_azure(request)

        assert result.message == "Just a string"

    def test_session_id_from_snake_case(self):
        """Test session_id can be extracted from snake_case key."""
        request = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "Test"}],
            },
            "session_id": "sess_snake",
        }

        result = translate_a2a_to_azure(request)

        assert result.session_id == "sess_snake"

    def test_session_id_from_message(self):
        """Test session_id can be extracted from message object."""
        request = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "Test"}],
                "sessionId": "sess_in_message",
            },
        }

        result = translate_a2a_to_azure(request)

        assert result.session_id == "sess_in_message"

    def test_generates_session_id_when_missing(self):
        """Test that a session_id is generated when not provided."""
        request = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "New conversation"}],
            },
        }

        result = translate_a2a_to_azure(request)

        assert result.session_id is not None
        assert result.session_id.startswith("sess_")
        # Should be sess_ + 32 hex chars
        assert len(result.session_id) == 37

    def test_raises_on_missing_message(self):
        """Test that ValueError is raised when message is missing."""
        request = {"sessionId": "sess_123"}

        with pytest.raises(ValueError, match="missing 'message'"):
            translate_a2a_to_azure(request)

    def test_raises_on_empty_message(self):
        """Test that ValueError is raised when message has no text."""
        request = {
            "message": {
                "role": "user",
                "parts": [],
            },
            "sessionId": "sess_123",
        }

        with pytest.raises(ValueError, match="no text content"):
            translate_a2a_to_azure(request)

    def test_raises_on_whitespace_only_message(self):
        """Test that ValueError is raised when message is whitespace only."""
        request = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "   "}],
            },
            "sessionId": "sess_123",
        }

        with pytest.raises(ValueError, match="no text content"):
            translate_a2a_to_azure(request)

    def test_context_id_snake_case(self):
        """Test context_id can be extracted from snake_case key."""
        request = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "Test"}],
                "context_id": "ctx_snake_case",
            },
            "sessionId": "sess_123",
        }

        result = translate_a2a_to_azure(request)

        assert result.context_id == "ctx_snake_case"


# =============================================================================
# TEST: translate_azure_to_a2a (BOUNDARY #4)
# =============================================================================


class TestTranslateAzureToA2A:
    """Tests for translate_azure_to_a2a function."""

    def test_string_response(self):
        """Test translating a simple string response."""
        result = translate_azure_to_a2a("Here's your trip plan...")

        assert isinstance(result, A2AResponseEnvelope)
        assert result.text == "Here's your trip plan..."
        assert result.is_complete is True
        assert result.status == "completed"

    def test_dict_with_content(self):
        """Test translating dict response with 'content' field."""
        azure_response = {"content": "Response content"}

        result = translate_azure_to_a2a(azure_response)

        assert result.text == "Response content"

    def test_dict_with_text(self):
        """Test translating dict response with 'text' field."""
        azure_response = {"text": "Response text"}

        result = translate_azure_to_a2a(azure_response)

        assert result.text == "Response text"

    def test_preserves_context_id(self):
        """Test that context_id is preserved in response."""
        result = translate_azure_to_a2a(
            "Response",
            context_id="ctx_preserved",
        )

        assert result.context_id == "ctx_preserved"

    def test_preserves_task_id(self):
        """Test that task_id is preserved in response."""
        result = translate_azure_to_a2a(
            "Response",
            context_id="ctx_123",
            task_id="task_456",
        )

        assert result.task_id == "task_456"

    def test_incomplete_response(self):
        """Test response marked as incomplete."""
        result = translate_azure_to_a2a(
            "Partial response...",
            is_complete=False,
        )

        assert result.is_complete is False
        assert result.status == "working"

    def test_requires_input_response(self):
        """Test response that requires user input."""
        result = translate_azure_to_a2a(
            "Please provide more details",
            is_complete=False,
            requires_input=True,
        )

        assert result.requires_input is True
        assert result.status == "input_required"

    def test_includes_metadata(self):
        """Test that metadata is included in response."""
        result = translate_azure_to_a2a(
            "Response",
            metadata={"lastSeenSeq": 3},
        )

        assert result.metadata == {"lastSeenSeq": 3}

    def test_messages_array_format(self):
        """Test extracting text from messages array format."""
        azure_response = {
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ]
        }

        result = translate_azure_to_a2a(azure_response)

        assert result.text == "Hi there!"

    def test_nested_message_format(self):
        """Test extracting text from nested message format."""
        azure_response = {
            "message": {
                "content": "Nested content"
            }
        }

        result = translate_azure_to_a2a(azure_response)

        assert result.text == "Nested content"


# =============================================================================
# TEST: translate_azure_streaming_chunk
# =============================================================================


class TestTranslateAzureStreamingChunk:
    """Tests for translate_azure_streaming_chunk function."""

    def test_string_chunk(self):
        """Test translating a string chunk."""
        result = translate_azure_streaming_chunk("Partial text")

        assert result.text == "Partial text"
        assert result.status == "working"
        assert result.is_complete is False

    def test_delta_format(self):
        """Test translating delta format chunk."""
        chunk = {"delta": {"content": "Streaming..."}}

        result = translate_azure_streaming_chunk(chunk)

        assert result.text == "Streaming..."
        assert result.is_complete is False

    def test_choices_format(self):
        """Test translating choices format (OpenAI-style)."""
        chunk = {
            "choices": [
                {"delta": {"content": "Choice content"}}
            ]
        }

        result = translate_azure_streaming_chunk(chunk)

        assert result.text == "Choice content"

    def test_final_chunk(self):
        """Test recognizing final chunk."""
        chunk = {
            "choices": [
                {
                    "delta": {"content": "Final"},
                    "finish_reason": "stop",
                }
            ]
        }

        result = translate_azure_streaming_chunk(chunk)

        assert result.is_complete is True
        assert result.status == "completed"

    def test_status_completed(self):
        """Test recognizing completed status."""
        chunk = {"status": "completed", "content": "Done"}

        result = translate_azure_streaming_chunk(chunk)

        assert result.is_complete is True
        assert result.status == "completed"

    def test_requires_action_status(self):
        """Test recognizing requires_action status."""
        chunk = {"status": "requires_action"}

        result = translate_azure_streaming_chunk(chunk)

        assert result.requires_input is True
        assert result.status == "input_required"

    def test_preserves_context_id(self):
        """Test context_id is preserved in streaming chunk."""
        result = translate_azure_streaming_chunk(
            "Chunk",
            context_id="ctx_streaming",
        )

        assert result.context_id == "ctx_streaming"

    def test_preserves_task_id(self):
        """Test task_id is preserved in streaming chunk."""
        result = translate_azure_streaming_chunk(
            "Chunk",
            context_id="ctx_123",
            task_id="task_456",
        )

        assert result.task_id == "task_456"


# =============================================================================
# TEST: HELPER FUNCTIONS
# =============================================================================


class TestExtractAzureResponseText:
    """Tests for _extract_azure_response_text helper."""

    def test_string_input(self):
        """Test extracting text from string input."""
        assert _extract_azure_response_text("Hello") == "Hello"

    def test_dict_with_content_string(self):
        """Test extracting from dict with string content."""
        assert _extract_azure_response_text({"content": "Content"}) == "Content"

    def test_dict_with_content_array(self):
        """Test extracting from dict with content array."""
        response = {
            "content": [
                {"type": "text", "text": "First"},
                {"type": "text", "text": "Second"},
            ]
        }
        assert _extract_azure_response_text(response) == "First Second"

    def test_dict_with_output(self):
        """Test extracting from tool output format."""
        assert _extract_azure_response_text({"output": "Tool output"}) == "Tool output"

    def test_dict_with_result(self):
        """Test extracting from result format."""
        assert _extract_azure_response_text({"result": "Result text"}) == "Result text"

    def test_dict_with_value(self):
        """Test extracting from value format."""
        assert _extract_azure_response_text({"value": "Value text"}) == "Value text"

    def test_fallback_to_str(self):
        """Test fallback to string representation."""
        # Non-dict, non-string input
        result = _extract_azure_response_text(12345)
        assert result == "12345"


class TestExtractTextFromContentArray:
    """Tests for _extract_text_from_content_array helper."""

    def test_string_items(self):
        """Test extracting from array of strings."""
        content = ["Hello", "World"]
        assert _extract_text_from_content_array(content) == "Hello World"

    def test_dict_items_with_type(self):
        """Test extracting from array of dicts with type field."""
        content = [
            {"type": "text", "text": "First"},
            {"type": "text", "text": "Second"},
        ]
        assert _extract_text_from_content_array(content) == "First Second"

    def test_dict_items_with_text_only(self):
        """Test extracting from array of dicts with text field only."""
        content = [
            {"text": "Only text"},
        ]
        assert _extract_text_from_content_array(content) == "Only text"

    def test_mixed_content(self):
        """Test extracting from mixed content array."""
        content = [
            "String item",
            {"type": "text", "text": "Dict item"},
        ]
        assert _extract_text_from_content_array(content) == "String item Dict item"

    def test_empty_array(self):
        """Test extracting from empty array."""
        assert _extract_text_from_content_array([]) == ""


class TestParseAzureStreamingChunk:
    """Tests for _parse_azure_streaming_chunk helper."""

    def test_string_chunk(self):
        """Test parsing string chunk."""
        result = _parse_azure_streaming_chunk("Text")

        assert isinstance(result, AzureStreamingChunk)
        assert result.text == "Text"
        assert result.is_final is False
        assert result.tool_calls == []

    def test_delta_with_tool_calls(self):
        """Test parsing delta with tool calls."""
        chunk = {
            "delta": {
                "content": "Thinking...",
                "tool_calls": [{"id": "call_1", "function": {"name": "test"}}],
            }
        }

        result = _parse_azure_streaming_chunk(chunk)

        assert result.text == "Thinking..."
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["id"] == "call_1"

    def test_required_action(self):
        """Test parsing required_action indicator."""
        chunk = {"required_action": {"type": "tool_calls"}}

        result = _parse_azure_streaming_chunk(chunk)

        assert result.run_status == "requires_action"

    def test_failed_status(self):
        """Test parsing failed status."""
        chunk = {"status": "failed"}

        result = _parse_azure_streaming_chunk(chunk)

        assert result.is_final is True
        assert result.run_status == "failed"

    def test_cancelled_status(self):
        """Test parsing cancelled status."""
        chunk = {"status": "cancelled"}

        result = _parse_azure_streaming_chunk(chunk)

        assert result.is_final is True
        assert result.run_status == "cancelled"


# =============================================================================
# TEST: INTEGRATION SCENARIOS
# =============================================================================


class TestIntegrationScenarios:
    """Integration tests for end-to-end translation scenarios."""

    def test_full_round_trip(self):
        """Test full A2A → Azure → A2A round trip."""
        # Incoming A2A request
        a2a_request = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "Plan a trip to Tokyo"}],
                "contextId": "ctx_new",
            },
            "sessionId": "sess_trip_123",
        }

        # Translate to Azure input
        azure_input = translate_a2a_to_azure(a2a_request)

        assert azure_input.message == "Plan a trip to Tokyo"
        assert azure_input.session_id == "sess_trip_123"
        assert azure_input.context_id == "ctx_new"

        # Simulate Azure response
        azure_response = "Great! When would you like to travel to Tokyo?"

        # Translate back to A2A
        a2a_response = translate_azure_to_a2a(
            azure_response,
            context_id=azure_input.context_id,
            is_complete=False,
            requires_input=True,
        )

        assert a2a_response.text == azure_response
        assert a2a_response.context_id == "ctx_new"
        assert a2a_response.status == "input_required"

    def test_streaming_conversation(self):
        """Test streaming response scenario."""
        chunks = [
            {"delta": {"content": "Here's "}},
            {"delta": {"content": "your trip "}},
            {"delta": {"content": "plan!"}},
            {"status": "completed"},
        ]

        responses = []
        for chunk in chunks:
            response = translate_azure_streaming_chunk(
                chunk,
                context_id="ctx_stream",
            )
            responses.append(response)

        # Check progression
        assert responses[0].text == "Here's "
        assert responses[0].status == "working"

        assert responses[1].text == "your trip "
        assert responses[1].status == "working"

        assert responses[2].text == "plan!"
        assert responses[2].status == "working"

        assert responses[3].is_complete is True
        assert responses[3].status == "completed"

    def test_multi_turn_context_preservation(self):
        """Test that context is preserved across multiple turns."""
        # First turn
        turn1_request = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "Plan a trip"}],
            },
            "sessionId": "sess_multi",
        }

        turn1_input = translate_a2a_to_azure(turn1_request)
        assert turn1_input.context_id is None

        # Simulate response with new context
        turn1_response = translate_azure_to_a2a(
            "Where to?",
            context_id="ctx_turn1",
            is_complete=False,
            requires_input=True,
        )

        # Second turn with context
        turn2_request = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "Tokyo"}],
                "contextId": turn1_response.context_id,
            },
            "sessionId": "sess_multi",
        }

        turn2_input = translate_a2a_to_azure(turn2_request)
        assert turn2_input.context_id == "ctx_turn1"
        assert turn2_input.session_id == "sess_multi"
