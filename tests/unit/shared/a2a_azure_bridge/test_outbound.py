"""Unit tests for A2A-Azure bridge outbound module."""

import json
import pytest

from src.shared.a2a_azure_bridge.outbound import (
    A2AOutboundRequest,
    A2AToolResponse,
    ToolOutput,
    translate_tool_args_to_a2a,
    translate_a2a_to_tool_output,
    translate_a2a_response_to_tool_response,
    create_tool_output,
    create_error_tool_output,
    WORKFLOW_TOOLS,
    UTILITY_TOOLS,
    ALL_TOOLS,
    _translate_workflow_turn_args,
    _translate_answer_question_args,
    _translate_currency_convert_args,
    _translate_weather_lookup_args,
    _translate_timezone_info_args,
    _translate_get_booking_args,
    _translate_get_consultation_args,
    _a2a_tool_response_to_dict,
    _extract_response_dict,
)


# =============================================================================
# TEST: A2AOutboundRequest DATACLASS
# =============================================================================


class TestA2AOutboundRequest:
    """Tests for A2AOutboundRequest dataclass."""

    def test_create_with_message_only(self):
        """Test creating request with message only."""
        request = A2AOutboundRequest(message="Hello")
        assert request.message == "Hello"
        assert request.context_id is None
        assert request.task_id is None
        assert request.history is None
        assert request.history_seq == 0
        assert request.metadata is None

    def test_create_with_all_fields(self):
        """Test creating request with all fields."""
        history = [{"role": "user", "content": "Hello"}]
        metadata = {"session_ref": {"session_id": "sess_123"}}

        request = A2AOutboundRequest(
            message="Plan a trip",
            context_id="ctx_123",
            task_id="task_456",
            history=history,
            history_seq=5,
            metadata=metadata,
        )

        assert request.message == "Plan a trip"
        assert request.context_id == "ctx_123"
        assert request.task_id == "task_456"
        assert request.history == history
        assert request.history_seq == 5
        assert request.metadata == metadata


# =============================================================================
# TEST: A2AToolResponse DATACLASS
# =============================================================================


class TestA2AToolResponse:
    """Tests for A2AToolResponse dataclass."""

    def test_create_with_defaults(self):
        """Test creating response with default values."""
        response = A2AToolResponse()
        assert response.success is True
        assert response.message == ""
        assert response.context_id is None
        assert response.task_id is None
        assert response.is_complete is False
        assert response.requires_input is False
        assert response.data == {}
        assert response.error_code is None

    def test_create_success_response(self):
        """Test creating a successful response."""
        response = A2AToolResponse(
            success=True,
            message="Trip planned successfully!",
            context_id="ctx_123",
            task_id="task_456",
            is_complete=True,
            data={"itinerary_id": "itn_789"},
        )

        assert response.success is True
        assert response.message == "Trip planned successfully!"
        assert response.context_id == "ctx_123"
        assert response.task_id == "task_456"
        assert response.is_complete is True
        assert response.data == {"itinerary_id": "itn_789"}

    def test_create_error_response(self):
        """Test creating an error response."""
        response = A2AToolResponse(
            success=False,
            message="Connection failed",
            error_code="AGENT_CONNECTION_ERROR",
        )

        assert response.success is False
        assert response.message == "Connection failed"
        assert response.error_code == "AGENT_CONNECTION_ERROR"


# =============================================================================
# TEST: ToolOutput DATACLASS
# =============================================================================


class TestToolOutput:
    """Tests for ToolOutput dataclass."""

    def test_create_tool_output(self):
        """Test creating a tool output."""
        output = ToolOutput(
            tool_call_id="call_123",
            output='{"success": true, "message": "Done"}',
        )

        assert output.tool_call_id == "call_123"
        assert output.output == '{"success": true, "message": "Done"}'

    def test_to_dict(self):
        """Test converting tool output to dictionary."""
        output = ToolOutput(
            tool_call_id="call_456",
            output='{"result": "success"}',
        )

        result = output.to_dict()

        assert result == {
            "tool_call_id": "call_456",
            "output": '{"result": "success"}',
        }


# =============================================================================
# TEST: TOOL CONSTANTS
# =============================================================================


class TestToolConstants:
    """Tests for tool type constants."""

    def test_workflow_tools(self):
        """Test WORKFLOW_TOOLS contains expected tools."""
        assert "workflow_turn" in WORKFLOW_TOOLS
        assert len(WORKFLOW_TOOLS) == 1

    def test_utility_tools(self):
        """Test UTILITY_TOOLS contains expected tools."""
        expected = {
            "answer_question",
            "currency_convert",
            "weather_lookup",
            "timezone_info",
            "get_booking",
            "get_consultation",
        }
        assert UTILITY_TOOLS == expected

    def test_all_tools(self):
        """Test ALL_TOOLS is union of workflow and utility tools."""
        assert ALL_TOOLS == WORKFLOW_TOOLS | UTILITY_TOOLS
        assert len(ALL_TOOLS) == 7


# =============================================================================
# TEST: translate_tool_args_to_a2a (BOUNDARY #2)
# =============================================================================


class TestTranslateToolArgsToA2A:
    """Tests for translate_tool_args_to_a2a function."""

    def test_unknown_tool_raises_error(self):
        """Test that unknown tool names raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            translate_tool_args_to_a2a("unknown_tool", {})

        assert "Unknown tool" in str(exc_info.value)
        assert "unknown_tool" in str(exc_info.value)

    def test_workflow_turn_basic(self):
        """Test translating basic workflow_turn args."""
        args = {
            "message": "Plan a trip to Tokyo",
        }

        request = translate_tool_args_to_a2a("workflow_turn", args)

        assert request.message == "Plan a trip to Tokyo"
        assert request.context_id is None
        assert request.history is None

    def test_workflow_turn_with_session_ref(self):
        """Test translating workflow_turn with session_ref."""
        args = {
            "message": "Continue planning",
            "session_ref": {
                "session_id": "sess_123",
                "agent_context_ids": {"clarifier": "ctx_456"},
            },
        }

        request = translate_tool_args_to_a2a("workflow_turn", args)

        assert request.message == "Continue planning"
        assert request.context_id == "ctx_456"  # From clarifier context
        assert request.metadata is not None
        assert request.metadata["session_ref"]["session_id"] == "sess_123"

    def test_workflow_turn_with_event(self):
        """Test translating workflow_turn with event."""
        args = {
            "message": "Approve it",
            "event": {"type": "approve_checkpoint", "checkpoint_id": "cp_123"},
        }

        request = translate_tool_args_to_a2a("workflow_turn", args)

        assert request.message == "Approve it"
        assert request.metadata is not None
        assert request.metadata["event"]["type"] == "approve_checkpoint"

    def test_workflow_turn_missing_message_raises_error(self):
        """Test that missing message raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            translate_tool_args_to_a2a("workflow_turn", {})

        assert "message" in str(exc_info.value).lower()

    def test_answer_question_basic(self):
        """Test translating basic answer_question args."""
        args = {
            "question": "What's Tokyo like in spring?",
        }

        request = translate_tool_args_to_a2a("answer_question", args)

        # Message should be JSON with Q&A mode
        message_data = json.loads(request.message)
        assert message_data["mode"] == "qa"
        assert message_data["question"] == "What's Tokyo like in spring?"
        assert message_data.get("domain") == "general"

    def test_answer_question_with_domain_and_context(self):
        """Test translating answer_question with domain and context."""
        args = {
            "question": "Does my hotel have a pool?",
            "domain": "stay",
            "context": {"destination": "Tokyo", "hotel": "Grand Hyatt"},
        }

        request = translate_tool_args_to_a2a("answer_question", args)

        message_data = json.loads(request.message)
        assert message_data["domain"] == "stay"
        assert message_data["context"]["destination"] == "Tokyo"
        # Q&A is stateless
        assert request.context_id is None

    def test_answer_question_missing_question_raises_error(self):
        """Test that missing question raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            translate_tool_args_to_a2a("answer_question", {})

        assert "question" in str(exc_info.value).lower()

    def test_currency_convert(self):
        """Test translating currency_convert args."""
        args = {
            "amount": 100.50,
            "from_currency": "usd",
            "to_currency": "jpy",
        }

        request = translate_tool_args_to_a2a("currency_convert", args)

        message_data = json.loads(request.message)
        assert message_data["tool"] == "currency_convert"
        assert message_data["amount"] == 100.50
        assert message_data["from_currency"] == "USD"  # Uppercased
        assert message_data["to_currency"] == "JPY"  # Uppercased

    def test_currency_convert_missing_fields(self):
        """Test currency_convert validation."""
        # Missing amount
        with pytest.raises(ValueError):
            translate_tool_args_to_a2a("currency_convert", {
                "from_currency": "USD",
                "to_currency": "JPY",
            })

        # Missing from_currency
        with pytest.raises(ValueError):
            translate_tool_args_to_a2a("currency_convert", {
                "amount": 100,
                "to_currency": "JPY",
            })

        # Missing to_currency
        with pytest.raises(ValueError):
            translate_tool_args_to_a2a("currency_convert", {
                "amount": 100,
                "from_currency": "USD",
            })

    def test_weather_lookup(self):
        """Test translating weather_lookup args."""
        args = {
            "location": "Tokyo, Japan",
            "date": "2026-03-15",
        }

        request = translate_tool_args_to_a2a("weather_lookup", args)

        message_data = json.loads(request.message)
        assert message_data["tool"] == "weather_lookup"
        assert message_data["location"] == "Tokyo, Japan"
        assert message_data["date"] == "2026-03-15"

    def test_weather_lookup_without_date(self):
        """Test weather_lookup without optional date."""
        args = {"location": "Paris"}

        request = translate_tool_args_to_a2a("weather_lookup", args)

        message_data = json.loads(request.message)
        assert message_data["location"] == "Paris"
        assert "date" not in message_data

    def test_weather_lookup_missing_location(self):
        """Test weather_lookup validation."""
        with pytest.raises(ValueError) as exc_info:
            translate_tool_args_to_a2a("weather_lookup", {})

        assert "location" in str(exc_info.value).lower()

    def test_timezone_info(self):
        """Test translating timezone_info args."""
        args = {
            "location": "Los Angeles",
            "date": "2026-06-15",
        }

        request = translate_tool_args_to_a2a("timezone_info", args)

        message_data = json.loads(request.message)
        assert message_data["tool"] == "timezone_info"
        assert message_data["location"] == "Los Angeles"
        assert message_data["date"] == "2026-06-15"

    def test_timezone_info_missing_location(self):
        """Test timezone_info validation."""
        with pytest.raises(ValueError) as exc_info:
            translate_tool_args_to_a2a("timezone_info", {})

        assert "location" in str(exc_info.value).lower()

    def test_get_booking(self):
        """Test translating get_booking args."""
        args = {"booking_id": "book_abc123"}

        request = translate_tool_args_to_a2a("get_booking", args)

        message_data = json.loads(request.message)
        assert message_data["tool"] == "get_booking"
        assert message_data["booking_id"] == "book_abc123"

    def test_get_booking_missing_id(self):
        """Test get_booking validation."""
        with pytest.raises(ValueError) as exc_info:
            translate_tool_args_to_a2a("get_booking", {})

        assert "booking_id" in str(exc_info.value).lower()

    def test_get_consultation(self):
        """Test translating get_consultation args."""
        args = {"consultation_id": "cons_xyz789"}

        request = translate_tool_args_to_a2a("get_consultation", args)

        message_data = json.loads(request.message)
        assert message_data["tool"] == "get_consultation"
        assert message_data["consultation_id"] == "cons_xyz789"

    def test_get_consultation_missing_id(self):
        """Test get_consultation validation."""
        with pytest.raises(ValueError) as exc_info:
            translate_tool_args_to_a2a("get_consultation", {})

        assert "consultation_id" in str(exc_info.value).lower()


# =============================================================================
# TEST: translate_a2a_to_tool_output (BOUNDARY #3)
# =============================================================================


class TestTranslateA2AToToolOutput:
    """Tests for translate_a2a_to_tool_output function."""

    def test_from_a2a_tool_response(self):
        """Test translating A2AToolResponse to tool output."""
        response = A2AToolResponse(
            success=True,
            message="Trip planned!",
            context_id="ctx_123",
        )

        output = translate_a2a_to_tool_output(response)

        output_data = json.loads(output)
        assert output_data["success"] is True
        assert output_data["message"] == "Trip planned!"
        assert output_data["context_id"] == "ctx_123"

    def test_from_dict_response(self):
        """Test translating dict response to tool output."""
        response = {
            "success": True,
            "message": "Done",
            "data": {"result": "ok"},
        }

        output = translate_a2a_to_tool_output(response)

        output_data = json.loads(output)
        assert output_data["success"] is True
        assert output_data["message"] == "Done"
        assert output_data["data"]["result"] == "ok"

    def test_error_response(self):
        """Test translating error response."""
        response = A2AToolResponse(
            success=False,
            message="Agent unavailable",
            error_code="AGENT_CONNECTION_ERROR",
        )

        output = translate_a2a_to_tool_output(response)

        output_data = json.loads(output)
        assert output_data["success"] is False
        assert output_data["message"] == "Agent unavailable"
        assert output_data["error_code"] == "AGENT_CONNECTION_ERROR"

    def test_omits_none_values(self):
        """Test that None values are omitted from output."""
        response = A2AToolResponse(
            success=True,
            message="Hello",
        )

        output = translate_a2a_to_tool_output(response)

        output_data = json.loads(output)
        assert "context_id" not in output_data
        assert "task_id" not in output_data
        assert "error_code" not in output_data


# =============================================================================
# TEST: translate_a2a_response_to_tool_response
# =============================================================================


class TestTranslateA2AResponseToToolResponse:
    """Tests for translate_a2a_response_to_tool_response function."""

    def test_from_dict(self):
        """Test converting dict to A2AToolResponse."""
        response_dict = {
            "success": True,
            "message": "Response text",
            "context_id": "ctx_123",
            "is_complete": True,
        }

        result = translate_a2a_response_to_tool_response(response_dict)

        assert result.success is True
        assert result.message == "Response text"
        assert result.context_id == "ctx_123"
        assert result.is_complete is True

    def test_from_dict_with_text_key(self):
        """Test converting dict with 'text' key instead of 'message'."""
        response_dict = {
            "text": "Agent response",
            "context_id": "ctx_456",
        }

        result = translate_a2a_response_to_tool_response(response_dict)

        assert result.message == "Agent response"

    def test_from_object(self):
        """Test converting object with attributes."""
        class MockA2AResponse:
            text = "Hello world"
            context_id = "ctx_789"
            task_id = "task_012"
            is_complete = True
            requires_input = False

        result = translate_a2a_response_to_tool_response(MockA2AResponse())

        assert result.success is True
        assert result.message == "Hello world"
        assert result.context_id == "ctx_789"
        assert result.task_id == "task_012"
        assert result.is_complete is True


# =============================================================================
# TEST: create_tool_output
# =============================================================================


class TestCreateToolOutput:
    """Tests for create_tool_output function."""

    def test_from_a2a_tool_response(self):
        """Test creating ToolOutput from A2AToolResponse."""
        response = A2AToolResponse(
            success=True,
            message="Done",
        )

        output = create_tool_output("call_123", response)

        assert output.tool_call_id == "call_123"
        assert '"success": true' in output.output.lower()

    def test_from_dict(self):
        """Test creating ToolOutput from dict."""
        response = {"success": True, "message": "OK"}

        output = create_tool_output("call_456", response)

        assert output.tool_call_id == "call_456"
        output_data = json.loads(output.output)
        assert output_data["success"] is True

    def test_from_string(self):
        """Test creating ToolOutput from raw string."""
        output = create_tool_output("call_789", "Raw string output")

        assert output.tool_call_id == "call_789"
        assert output.output == "Raw string output"


# =============================================================================
# TEST: create_error_tool_output
# =============================================================================


class TestCreateErrorToolOutput:
    """Tests for create_error_tool_output function."""

    def test_basic_error(self):
        """Test creating basic error output."""
        output = create_error_tool_output("call_123", "Something went wrong")

        assert output.tool_call_id == "call_123"
        output_data = json.loads(output.output)
        assert output_data["success"] is False
        assert output_data["message"] == "Something went wrong"

    def test_error_with_code(self):
        """Test creating error output with error code."""
        output = create_error_tool_output(
            "call_456",
            "Connection failed",
            error_code="AGENT_CONNECTION_ERROR",
        )

        output_data = json.loads(output.output)
        assert output_data["success"] is False
        assert output_data["error_code"] == "AGENT_CONNECTION_ERROR"


# =============================================================================
# TEST: Helper Functions
# =============================================================================


class TestHelperFunctions:
    """Tests for internal helper functions."""

    def test_a2a_tool_response_to_dict_complete(self):
        """Test full response conversion to dict."""
        response = A2AToolResponse(
            success=True,
            message="Complete response",
            context_id="ctx_123",
            task_id="task_456",
            is_complete=True,
            requires_input=False,
            data={"key": "value"},
            error_code=None,
        )

        result = _a2a_tool_response_to_dict(response)

        assert result["success"] is True
        assert result["message"] == "Complete response"
        assert result["context_id"] == "ctx_123"
        assert result["task_id"] == "task_456"
        assert result["is_complete"] is True
        assert result["data"]["key"] == "value"
        assert "error_code" not in result  # None values omitted
        assert "requires_input" not in result  # False omitted

    def test_extract_response_dict_from_object(self):
        """Test extracting dict from object with text attribute."""
        class MockResponse:
            text = "Hello"
            context_id = "ctx_abc"
            task_id = None
            is_complete = True
            requires_input = False

        result = _extract_response_dict(MockResponse())

        assert result["success"] is True
        assert result["message"] == "Hello"
        assert result["context_id"] == "ctx_abc"

    def test_extract_response_dict_fallback(self):
        """Test fallback to string representation."""
        result = _extract_response_dict("Just a string")

        assert result["success"] is True
        assert "Just a string" in result["message"]


# =============================================================================
# TEST: Individual Tool Translators
# =============================================================================


class TestIndividualToolTranslators:
    """Tests for internal tool-specific translator functions."""

    def test_translate_workflow_turn_with_history(self):
        """Test workflow_turn with history injection."""
        args = {
            "message": "Continue",
            "history": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ],
            "history_seq": 3,
        }

        request = _translate_workflow_turn_args(args)

        assert request.history is not None
        assert len(request.history) == 2
        assert request.history_seq == 3

    def test_translate_answer_question_qa_mode(self):
        """Test answer_question creates proper Q&A request."""
        args = {
            "question": "Best time to visit?",
            "domain": "poi",
        }

        request = _translate_answer_question_args(args)

        message_data = json.loads(request.message)
        assert message_data["mode"] == "qa"
        assert message_data["question"] == "Best time to visit?"
        assert message_data["domain"] == "poi"

    def test_translate_currency_convert_uppercases(self):
        """Test currency codes are uppercased."""
        args = {
            "amount": 50,
            "from_currency": "eur",
            "to_currency": "gbp",
        }

        request = _translate_currency_convert_args(args)

        message_data = json.loads(request.message)
        assert message_data["from_currency"] == "EUR"
        assert message_data["to_currency"] == "GBP"
