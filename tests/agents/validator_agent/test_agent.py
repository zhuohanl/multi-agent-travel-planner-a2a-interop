"""Unit tests for Validator Agent agent.py."""

import json
import os
import pytest
from unittest.mock import patch

from src.shared.models import (
    ValidatorResponse,
    ValidationResult,
)


@pytest.fixture(autouse=True)
def mock_environment():
    """Set required environment variables for all tests."""
    env_vars = {
        "SERVER_URL": "localhost",
        "VALIDATOR_AGENT_PORT": "10016",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_DEPLOYMENT_NAME": "test-deployment",
        "AZURE_OPENAI_API_VERSION": "2024-02-01",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


class TestAgentFrameworkValidatorAgent:
    """Tests for AgentFrameworkValidatorAgent class."""

    @pytest.fixture
    def agent_class(self, mock_environment):
        """Get the agent class with mocked environment."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.validator_agent.agent import AgentFrameworkValidatorAgent
            yield AgentFrameworkValidatorAgent

    def test_get_agent_name_returns_validator_agent(self, agent_class, mock_environment):
        """Test that get_agent_name returns 'ValidatorAgent'."""
        with patch.dict(os.environ, mock_environment):
            agent = agent_class()
            assert agent.get_agent_name() == "ValidatorAgent"

    def test_get_prompt_name_returns_validator(self, agent_class, mock_environment):
        """Test that get_prompt_name returns 'validator'."""
        with patch.dict(os.environ, mock_environment):
            agent = agent_class()
            assert agent.get_prompt_name() == "validator"

    def test_get_response_format_returns_validator_response(self, agent_class, mock_environment):
        """Test that get_response_format returns ValidatorResponse class."""
        with patch.dict(os.environ, mock_environment):
            agent = agent_class()
            assert agent.get_response_format() == ValidatorResponse

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
            from src.agents.validator_agent.agent import AgentFrameworkValidatorAgent
            return AgentFrameworkValidatorAgent()

    def test_parse_response_with_text_response(self, agent, mock_environment):
        """Test parsing when agent needs more user input."""
        with patch.dict(os.environ, mock_environment):
            response_data = ValidatorResponse(
                validation_result=None,
                response="Please provide a TripSpec and Itinerary to validate."
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert "TripSpec" in result['content']

    def test_parse_response_with_passed_validation(self, agent, mock_environment):
        """Test parsing when validation passes."""
        with patch.dict(os.environ, mock_environment):
            validation_result = ValidationResult(
                passed=True,
                issues=[],
                warnings=["Total cost ($4,800) is within 10% of budget ($5,000)"]
            )
            response_data = ValidatorResponse(
                validation_result=validation_result
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            assert result['require_user_input'] is False
            content = json.loads(result['content'])
            assert content['validation_result']['passed'] is True
            assert len(content['validation_result']['warnings']) == 1

    def test_parse_response_with_failed_validation(self, agent, mock_environment):
        """Test parsing when validation fails."""
        with patch.dict(os.environ, mock_environment):
            validation_result = ValidationResult(
                passed=False,
                issues=["Total cost ($6,500) exceeds budget ($5,000) by $1,500"],
                warnings=[]
            )
            response_data = ValidatorResponse(
                validation_result=validation_result
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            assert result['require_user_input'] is False
            content = json.loads(result['content'])
            assert content['validation_result']['passed'] is False
            assert len(content['validation_result']['issues']) == 1

    def test_parse_response_with_multiple_issues(self, agent, mock_environment):
        """Test parsing when validation has multiple issues."""
        with patch.dict(os.environ, mock_environment):
            validation_result = ValidationResult(
                passed=False,
                issues=[
                    "Total cost ($6,500) exceeds budget ($5,000) by $1,500",
                    "Missing activities for 2025-11-15",
                    "Constraint 'vegetarian dining' not addressed"
                ],
                warnings=["Limited coverage of interest 'nightlife'"]
            )
            response_data = ValidatorResponse(
                validation_result=validation_result
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert content['validation_result']['passed'] is False
            assert len(content['validation_result']['issues']) == 3
            assert len(content['validation_result']['warnings']) == 1

    def test_parse_response_with_no_output(self, agent, mock_environment):
        """Test parsing when neither validation_result nor response is provided."""
        with patch.dict(os.environ, mock_environment):
            response_data = ValidatorResponse(
                validation_result=None,
                response=None
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert "TripSpec" in result['content']

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

    def test_parse_response_with_empty_issues_and_warnings(self, agent, mock_environment):
        """Test parsing with passed validation and no issues/warnings."""
        with patch.dict(os.environ, mock_environment):
            validation_result = ValidationResult(
                passed=True,
                issues=[],
                warnings=[]
            )
            response_data = ValidatorResponse(
                validation_result=validation_result
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert content['validation_result']['passed'] is True
            assert len(content['validation_result']['issues']) == 0
            assert len(content['validation_result']['warnings']) == 0


class TestValidatorResponseModel:
    """Tests for ValidatorResponse model validation."""

    def test_validator_response_with_validation_result(self):
        """Test creating ValidatorResponse with validation result."""
        validation_result = ValidationResult(
            passed=True,
            issues=[],
            warnings=[]
        )
        response = ValidatorResponse(validation_result=validation_result)
        assert response.validation_result is not None
        assert response.response is None

    def test_validator_response_with_response_text(self):
        """Test creating ValidatorResponse with response text."""
        response = ValidatorResponse(response="Need TripSpec and Itinerary")
        assert response.validation_result is None
        assert response.response == "Need TripSpec and Itinerary"

    def test_validator_response_rejects_extra_fields(self):
        """Test that ValidatorResponse rejects extra fields."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ValidatorResponse(
                validation_result=None,
                extra_field="not allowed"
            )

    def test_validator_response_json_serialization(self):
        """Test ValidatorResponse can be serialized to JSON."""
        validation_result = ValidationResult(
            passed=False,
            issues=["Over budget"],
            warnings=["Consider alternatives"]
        )
        response = ValidatorResponse(validation_result=validation_result)
        json_str = response.model_dump_json()
        parsed = json.loads(json_str)
        assert 'validation_result' in parsed
        assert parsed['validation_result']['passed'] is False


class TestValidationResultModel:
    """Tests for ValidationResult model."""

    def test_validation_result_passed(self):
        """Test creating passed ValidationResult."""
        result = ValidationResult(
            passed=True,
            issues=[],
            warnings=[]
        )
        assert result.passed is True
        assert len(result.issues) == 0
        assert len(result.warnings) == 0

    def test_validation_result_failed(self):
        """Test creating failed ValidationResult."""
        result = ValidationResult(
            passed=False,
            issues=["Budget exceeded"],
            warnings=[]
        )
        assert result.passed is False
        assert len(result.issues) == 1

    def test_validation_result_with_warnings_only(self):
        """Test ValidationResult with warnings but no issues."""
        result = ValidationResult(
            passed=True,
            issues=[],
            warnings=["Close to budget limit"]
        )
        assert result.passed is True
        assert len(result.warnings) == 1

    def test_validation_result_with_multiple_issues(self):
        """Test ValidationResult with multiple issues."""
        result = ValidationResult(
            passed=False,
            issues=["Budget exceeded", "Missing dates", "Constraint violated"],
            warnings=["Consider alternatives"]
        )
        assert result.passed is False
        assert len(result.issues) == 3
        assert len(result.warnings) == 1

    def test_validation_result_default_lists(self):
        """Test that issues and warnings default to empty lists."""
        result = ValidationResult(passed=True)
        assert result.issues == []
        assert result.warnings == []

    def test_validation_result_rejects_extra_fields(self):
        """Test that ValidationResult rejects extra fields."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ValidationResult(
                passed=True,
                extra_field="not allowed"
            )


class TestAgentNoTools:
    """Tests to verify the agent has no external tools."""

    @pytest.fixture
    def agent(self, mock_environment):
        """Create an agent instance for testing."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.validator_agent.agent import AgentFrameworkValidatorAgent
            return AgentFrameworkValidatorAgent()

    def test_agent_has_no_tools(self, agent, mock_environment):
        """Verify the validator agent does not require external tools."""
        with patch.dict(os.environ, mock_environment):
            tools = agent.get_tools()
            assert len(tools) == 0
            assert tools == []

    def test_agent_inherits_from_base(self, mock_environment):
        """Test that agent inherits from BaseAgentFrameworkAgent."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.validator_agent.agent import AgentFrameworkValidatorAgent
            from src.shared.agents.base_agent import BaseAgentFrameworkAgent

            assert issubclass(AgentFrameworkValidatorAgent, BaseAgentFrameworkAgent)
