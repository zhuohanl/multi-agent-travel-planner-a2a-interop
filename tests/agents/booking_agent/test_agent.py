"""Unit tests for Booking Agent agent.py."""

import json
import os
import pytest
from unittest.mock import patch

from src.shared.models import (
    BookingResponse,
    BookingAction,
    BookingResult,
    BookingStatus,
)


@pytest.fixture(autouse=True)
def mock_environment():
    """Set required environment variables for all tests."""
    env_vars = {
        "SERVER_URL": "localhost",
        "BOOKING_AGENT_PORT": "10014",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_DEPLOYMENT_NAME": "test-deployment",
        "AZURE_OPENAI_API_VERSION": "2024-02-01",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


class TestAgentFrameworkBookingAgent:
    """Tests for AgentFrameworkBookingAgent class."""

    @pytest.fixture
    def agent_class(self, mock_environment):
        """Get the agent class with mocked environment."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.booking_agent.agent import AgentFrameworkBookingAgent
            yield AgentFrameworkBookingAgent

    def test_get_agent_name_returns_booking_agent(self, agent_class, mock_environment):
        """Test that get_agent_name returns 'BookingAgent'."""
        with patch.dict(os.environ, mock_environment):
            agent = agent_class()
            assert agent.get_agent_name() == "BookingAgent"

    def test_get_prompt_name_returns_booking(self, agent_class, mock_environment):
        """Test that get_prompt_name returns 'booking'."""
        with patch.dict(os.environ, mock_environment):
            agent = agent_class()
            assert agent.get_prompt_name() == "booking"

    def test_get_response_format_returns_booking_response(self, agent_class, mock_environment):
        """Test that get_response_format returns BookingResponse class."""
        with patch.dict(os.environ, mock_environment):
            agent = agent_class()
            assert agent.get_response_format() == BookingResponse

    def test_get_tools_returns_empty_list(self, agent_class, mock_environment):
        """Test that get_tools returns an empty list (no external tools needed)."""
        with patch.dict(os.environ, mock_environment):
            agent = agent_class()
            tools = agent.get_tools()
            assert tools == []


class TestParseResponse:
    """Tests for parse_response method."""

    @pytest.fixture
    def agent(self, mock_environment):
        """Create an agent instance for testing."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.booking_agent.agent import AgentFrameworkBookingAgent
            return AgentFrameworkBookingAgent()

    def test_parse_response_with_text_response(self, agent, mock_environment):
        """Test parsing when agent needs more user input."""
        with patch.dict(os.environ, mock_environment):
            response_data = BookingResponse(
                action=None,
                response="Please provide the booking details."
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert result['content'] == "Please provide the booking details."

    def test_parse_response_with_create_success(self, agent, mock_environment):
        """Test parsing CREATE action success."""
        with patch.dict(os.environ, mock_environment):
            booking_result = BookingResult(
                success=True,
                booking_id="book_abc123xyz",
                provider_ref="HTL-12345678",
                status=BookingStatus.CONFIRMED,
                details={
                    "type": "hotel",
                    "name": "Park Hyatt Tokyo",
                    "confirmation_number": "ABC12345",
                    "check_in": "2024-11-10",
                    "check_out": "2024-11-17",
                    "price": 3500.00,
                    "currency": "USD"
                }
            )
            response_data = BookingResponse(
                action=BookingAction.CREATE,
                result=booking_result
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            assert result['require_user_input'] is False
            content = json.loads(result['content'])
            assert content['action'] == "create"
            assert content['result']['success'] is True
            assert content['result']['booking_id'] == "book_abc123xyz"
            assert content['result']['status'] == "confirmed"

    def test_parse_response_with_create_failure(self, agent, mock_environment):
        """Test parsing CREATE action failure."""
        with patch.dict(os.environ, mock_environment):
            booking_result = BookingResult(
                success=False,
                status=BookingStatus.FAILED,
                error_message="Hotel is fully booked for selected dates"
            )
            response_data = BookingResponse(
                action=BookingAction.CREATE,
                result=booking_result
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            assert result['require_user_input'] is False
            content = json.loads(result['content'])
            assert content['result']['success'] is False
            assert "fully booked" in content['result']['error_message']

    def test_parse_response_with_modify_success(self, agent, mock_environment):
        """Test parsing MODIFY action success."""
        with patch.dict(os.environ, mock_environment):
            booking_result = BookingResult(
                success=True,
                booking_id="book_abc123xyz",
                provider_ref="HTL-12345678",
                status=BookingStatus.MODIFIED,
                details={
                    "previous": {"check_in": "2024-11-10"},
                    "updated": {"check_in": "2024-11-12"},
                    "modification_fee": None
                }
            )
            response_data = BookingResponse(
                action=BookingAction.MODIFY,
                result=booking_result
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            assert result['require_user_input'] is False
            content = json.loads(result['content'])
            assert content['action'] == "modify"
            assert content['result']['success'] is True
            assert content['result']['status'] == "modified"

    def test_parse_response_with_modify_not_allowed(self, agent, mock_environment):
        """Test parsing MODIFY action when not allowed."""
        with patch.dict(os.environ, mock_environment):
            booking_result = BookingResult(
                success=False,
                booking_id="book_abc123xyz",
                status=BookingStatus.PENDING,
                error_message="Modification not allowed for this booking"
            )
            response_data = BookingResponse(
                action=BookingAction.MODIFY,
                result=booking_result
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert content['result']['success'] is False
            assert "not allowed" in content['result']['error_message']

    def test_parse_response_with_cancel_success(self, agent, mock_environment):
        """Test parsing CANCEL action success."""
        with patch.dict(os.environ, mock_environment):
            booking_result = BookingResult(
                success=True,
                booking_id="book_abc123xyz",
                provider_ref="HTL-12345678",
                status=BookingStatus.CANCELLED,
                details={
                    "refund_amount": 500.00,
                    "cancellation_fee": 50.00,
                    "cancellation_reference": "CXL-ABC123"
                }
            )
            response_data = BookingResponse(
                action=BookingAction.CANCEL,
                result=booking_result
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            assert result['require_user_input'] is False
            content = json.loads(result['content'])
            assert content['action'] == "cancel"
            assert content['result']['success'] is True
            assert content['result']['status'] == "cancelled"

    def test_parse_response_with_cancel_not_allowed(self, agent, mock_environment):
        """Test parsing CANCEL action when not allowed."""
        with patch.dict(os.environ, mock_environment):
            booking_result = BookingResult(
                success=False,
                booking_id="book_abc123xyz",
                status=BookingStatus.CONFIRMED,
                error_message="Cancellation not allowed for this booking"
            )
            response_data = BookingResponse(
                action=BookingAction.CANCEL,
                result=booking_result
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert content['result']['success'] is False
            assert "not allowed" in content['result']['error_message']

    def test_parse_response_with_empty_output(self, agent, mock_environment):
        """Test parsing when action is set but result is missing."""
        with patch.dict(os.environ, mock_environment):
            response_data = BookingResponse(
                action=BookingAction.CREATE,
                result=None
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert "action" in result['content'].lower()

    def test_parse_response_with_no_action_no_result(self, agent, mock_environment):
        """Test parsing when both action and result are None."""
        with patch.dict(os.environ, mock_environment):
            response_data = BookingResponse(action=None, result=None, response=None)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True

    def test_parse_response_with_invalid_json(self, agent, mock_environment):
        """Test parsing handles invalid JSON gracefully."""
        with patch.dict(os.environ, mock_environment):
            message = "not valid json {{"

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert "unable to process" in result['content'].lower()

    def test_parse_response_with_malformed_structure(self, agent, mock_environment):
        """Test parsing handles structurally invalid response."""
        with patch.dict(os.environ, mock_environment):
            message = '{"unexpected_field": "value"}'

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True


class TestBookingResponseModel:
    """Tests for BookingResponse model validation."""

    def test_booking_response_with_create_result(self):
        """Test creating BookingResponse with CREATE result."""
        result = BookingResult(
            success=True,
            booking_id="book_abc123def",
            status=BookingStatus.CONFIRMED
        )
        response = BookingResponse(action=BookingAction.CREATE, result=result)
        assert response.action == BookingAction.CREATE
        assert response.result is not None
        assert response.response is None

    def test_booking_response_with_modify_result(self):
        """Test creating BookingResponse with MODIFY result."""
        result = BookingResult(
            success=True,
            booking_id="book_abc123def",
            status=BookingStatus.MODIFIED
        )
        response = BookingResponse(action=BookingAction.MODIFY, result=result)
        assert response.action == BookingAction.MODIFY
        assert response.result.status == BookingStatus.MODIFIED

    def test_booking_response_with_cancel_result(self):
        """Test creating BookingResponse with CANCEL result."""
        result = BookingResult(
            success=True,
            booking_id="book_abc123def",
            status=BookingStatus.CANCELLED
        )
        response = BookingResponse(action=BookingAction.CANCEL, result=result)
        assert response.action == BookingAction.CANCEL
        assert response.result.status == BookingStatus.CANCELLED

    def test_booking_response_with_response_text(self):
        """Test creating BookingResponse with response text."""
        response = BookingResponse(response="Please provide booking details")
        assert response.action is None
        assert response.result is None
        assert response.response == "Please provide booking details"

    def test_booking_response_rejects_extra_fields(self):
        """Test that BookingResponse rejects extra fields."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            BookingResponse(
                action=BookingAction.CREATE,
                extra_field="not allowed"
            )

    def test_booking_response_json_serialization(self):
        """Test BookingResponse can be serialized to JSON."""
        result = BookingResult(
            success=True,
            booking_id="book_abc123def",
            status=BookingStatus.CONFIRMED,
            details={"type": "hotel"}
        )
        response = BookingResponse(action=BookingAction.CREATE, result=result)
        json_str = response.model_dump_json()
        parsed = json.loads(json_str)
        assert 'action' in parsed
        assert 'result' in parsed


class TestBookingResultModel:
    """Tests for BookingResult model validation."""

    def test_booking_result_success(self):
        """Test successful BookingResult."""
        result = BookingResult(
            success=True,
            booking_id="book_abc123def",
            provider_ref="HTL-12345",
            status=BookingStatus.CONFIRMED
        )
        assert result.success is True
        assert result.booking_id.startswith("book_")
        assert result.error_message is None

    def test_booking_result_failure(self):
        """Test failed BookingResult."""
        result = BookingResult(
            success=False,
            status=BookingStatus.FAILED,
            error_message="Operation failed"
        )
        assert result.success is False
        assert result.booking_id is None
        assert result.error_message == "Operation failed"

    def test_booking_result_with_details(self):
        """Test BookingResult with details."""
        result = BookingResult(
            success=True,
            booking_id="book_abc123def",
            status=BookingStatus.CONFIRMED,
            details={
                "type": "hotel",
                "name": "Park Hyatt",
                "price": 500.00
            }
        )
        assert result.details.type == "hotel"
        assert result.details.price == 500.00

    def test_booking_result_invalid_booking_id_format(self):
        """Test that invalid booking_id format is rejected."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            BookingResult(
                success=True,
                booking_id="invalid_id",  # Missing "book_" prefix
                status=BookingStatus.CONFIRMED
            )

    def test_booking_result_valid_booking_id_formats(self):
        """Test various valid booking_id formats."""
        valid_ids = ["book_abc123", "book_a", "book_123456789012"]
        for booking_id in valid_ids:
            result = BookingResult(
                success=True,
                booking_id=booking_id,
                status=BookingStatus.CONFIRMED
            )
            assert result.booking_id == booking_id

    def test_booking_result_default_status(self):
        """Test that default status is PENDING."""
        result = BookingResult(success=True)
        assert result.status == BookingStatus.PENDING


class TestBookingActionEnum:
    """Tests for BookingAction enum."""

    def test_booking_action_create(self):
        """Test CREATE action value."""
        assert BookingAction.CREATE.value == "create"

    def test_booking_action_modify(self):
        """Test MODIFY action value."""
        assert BookingAction.MODIFY.value == "modify"

    def test_booking_action_cancel(self):
        """Test CANCEL action value."""
        assert BookingAction.CANCEL.value == "cancel"

    def test_booking_action_is_string_enum(self):
        """Test that BookingAction is a string enum."""
        assert isinstance(BookingAction.CREATE, str)
        assert BookingAction.CREATE == "create"


class TestBookingStatusEnum:
    """Tests for BookingStatus enum."""

    def test_booking_status_pending(self):
        """Test PENDING status value."""
        assert BookingStatus.PENDING.value == "pending"

    def test_booking_status_confirmed(self):
        """Test CONFIRMED status value."""
        assert BookingStatus.CONFIRMED.value == "confirmed"

    def test_booking_status_modified(self):
        """Test MODIFIED status value."""
        assert BookingStatus.MODIFIED.value == "modified"

    def test_booking_status_cancelled(self):
        """Test CANCELLED status value."""
        assert BookingStatus.CANCELLED.value == "cancelled"

    def test_booking_status_failed(self):
        """Test FAILED status value."""
        assert BookingStatus.FAILED.value == "failed"

    def test_booking_status_is_string_enum(self):
        """Test that BookingStatus is a string enum."""
        assert isinstance(BookingStatus.PENDING, str)


class TestAgentNoTools:
    """Tests to verify the agent has no external tools."""

    @pytest.fixture
    def agent(self, mock_environment):
        """Create an agent instance for testing."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.booking_agent.agent import AgentFrameworkBookingAgent
            return AgentFrameworkBookingAgent()

    def test_agent_has_no_tools(self, agent, mock_environment):
        """Verify the booking agent does not require external tools."""
        with patch.dict(os.environ, mock_environment):
            tools = agent.get_tools()
            assert len(tools) == 0
            assert tools == []

    def test_agent_inherits_from_base(self, mock_environment):
        """Test that agent inherits from BaseAgentFrameworkAgent."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.booking_agent.agent import AgentFrameworkBookingAgent
            from src.shared.agents.base_agent import BaseAgentFrameworkAgent

            assert issubclass(AgentFrameworkBookingAgent, BaseAgentFrameworkAgent)
