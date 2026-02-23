"""Unit tests for Budget Agent agent.py."""

import json
import os
import pytest
from unittest.mock import patch

from src.shared.models import (
    BudgetResponse,
    BudgetMode,
    BudgetProposal,
    BudgetValidation,
    BudgetTracking,
    BudgetReallocation,
    BudgetCategoryValidation,
    BudgetCategoryAmount,
)


@pytest.fixture(autouse=True)
def mock_environment():
    """Set required environment variables for all tests."""
    env_vars = {
        "SERVER_URL": "localhost",
        "BUDGET_AGENT_PORT": "10013",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_DEPLOYMENT_NAME": "test-deployment",
        "AZURE_OPENAI_API_VERSION": "2024-02-01",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


class TestAgentFrameworkBudgetAgent:
    """Tests for AgentFrameworkBudgetAgent class."""

    @pytest.fixture
    def agent_class(self, mock_environment):
        """Get the agent class with mocked environment."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.budget_agent.agent import AgentFrameworkBudgetAgent
            yield AgentFrameworkBudgetAgent

    def test_get_agent_name_returns_budget_agent(self, agent_class, mock_environment):
        """Test that get_agent_name returns 'BudgetAgent'."""
        with patch.dict(os.environ, mock_environment):
            agent = agent_class()
            assert agent.get_agent_name() == "BudgetAgent"

    def test_get_prompt_name_returns_budget(self, agent_class, mock_environment):
        """Test that get_prompt_name returns 'budget'."""
        with patch.dict(os.environ, mock_environment):
            agent = agent_class()
            assert agent.get_prompt_name() == "budget"

    def test_get_response_format_returns_budget_response(self, agent_class, mock_environment):
        """Test that get_response_format returns BudgetResponse class."""
        with patch.dict(os.environ, mock_environment):
            agent = agent_class()
            assert agent.get_response_format() == BudgetResponse

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
            from src.agents.budget_agent.agent import AgentFrameworkBudgetAgent
            return AgentFrameworkBudgetAgent()

    def test_parse_response_with_text_response(self, agent, mock_environment):
        """Test parsing when agent needs more user input."""
        with patch.dict(os.environ, mock_environment):
            response_data = BudgetResponse(
                mode=None,
                response="Please specify a mode and provide trip details."
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert result['content'] == "Please specify a mode and provide trip details."

    def test_parse_response_with_propose_mode(self, agent, mock_environment):
        """Test parsing PROPOSE mode response."""
        with patch.dict(os.environ, mock_environment):
            proposal = BudgetProposal(
                total_budget=5000.0,
                currency="USD",
                allocations=[
                    BudgetCategoryAmount(category="transport", amount=1500.0),
                    BudgetCategoryAmount(category="accommodation", amount=1750.0),
                    BudgetCategoryAmount(category="activities", amount=750.0),
                    BudgetCategoryAmount(category="dining", amount=750.0),
                    BudgetCategoryAmount(category="miscellaneous", amount=250.0),
                ],
                rationale="Standard allocation for Tokyo trip"
            )
            response_data = BudgetResponse(
                mode=BudgetMode.PROPOSE,
                proposal=proposal
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            assert result['require_user_input'] is False
            content = json.loads(result['content'])
            assert content['mode'] == "propose"
            assert content['proposal']['total_budget'] == 5000.0

    def test_parse_response_with_validate_mode(self, agent, mock_environment):
        """Test parsing VALIDATE mode response."""
        with patch.dict(os.environ, mock_environment):
            validation = BudgetValidation(
                valid=True,
                total_budget=5000.0,
                total_cost=4500.0,
                currency="USD",
                by_category=[
                    BudgetCategoryValidation(
                        category="transport",
                        allocated=1500.0,
                        cost=1200.0,
                        over=False
                    ),
                    BudgetCategoryValidation(
                        category="accommodation",
                        allocated=1750.0,
                        cost=1600.0,
                        over=False
                    )
                ],
                issues=[],
                warnings=["Consider booking transport early"]
            )
            response_data = BudgetResponse(
                mode=BudgetMode.VALIDATE,
                validation=validation
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            assert result['require_user_input'] is False
            content = json.loads(result['content'])
            assert content['mode'] == "validate"
            assert content['validation']['valid'] is True

    def test_parse_response_with_track_mode(self, agent, mock_environment):
        """Test parsing TRACK mode response."""
        with patch.dict(os.environ, mock_environment):
            tracking = BudgetTracking(
                total_budget=5000.0,
                total_spent=2500.0,
                currency="USD",
                by_category=[
                    BudgetCategoryAmount(category="transport", amount=1200.0),
                    BudgetCategoryAmount(category="accommodation", amount=800.0),
                    BudgetCategoryAmount(category="activities", amount=300.0),
                    BudgetCategoryAmount(category="dining", amount=200.0),
                ],
                remaining=2500.0,
                over_budget=False,
                warnings=[]
            )
            response_data = BudgetResponse(
                mode=BudgetMode.TRACK,
                tracking=tracking
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            assert result['require_user_input'] is False
            content = json.loads(result['content'])
            assert content['mode'] == "track"
            assert content['tracking']['remaining'] == 2500.0

    def test_parse_response_with_reallocate_mode(self, agent, mock_environment):
        """Test parsing REALLOCATE mode response."""
        with patch.dict(os.environ, mock_environment):
            reallocation = BudgetReallocation(
                original_allocations=[
                    BudgetCategoryAmount(category="transport", amount=1500.0),
                    BudgetCategoryAmount(category="accommodation", amount=2000.0),
                ],
                suggested_allocations=[
                    BudgetCategoryAmount(category="transport", amount=1200.0),
                    BudgetCategoryAmount(category="accommodation", amount=1800.0),
                ],
                currency="USD",
                suggestions=[
                    "Consider budget airlines for transport",
                    "Look at 3-star hotels instead of 4-star"
                ],
                potential_savings=500.0
            )
            response_data = BudgetResponse(
                mode=BudgetMode.REALLOCATE,
                reallocation=reallocation
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            assert result['require_user_input'] is False
            content = json.loads(result['content'])
            assert content['mode'] == "reallocate"
            assert content['reallocation']['potential_savings'] == 500.0

    def test_parse_response_with_empty_output(self, agent, mock_environment):
        """Test parsing when mode is set but output is missing."""
        with patch.dict(os.environ, mock_environment):
            response_data = BudgetResponse(
                mode=BudgetMode.PROPOSE,
                proposal=None
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True
            assert "mode" in result['content'].lower()

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

    def test_parse_response_with_no_mode(self, agent, mock_environment):
        """Test parsing when mode is None and no response text."""
        with patch.dict(os.environ, mock_environment):
            response_data = BudgetResponse(mode=None, response=None)
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is False
            assert result['require_user_input'] is True

    def test_parse_response_validate_over_budget(self, agent, mock_environment):
        """Test parsing VALIDATE mode when over budget."""
        with patch.dict(os.environ, mock_environment):
            validation = BudgetValidation(
                valid=False,
                total_budget=5000.0,
                total_cost=6500.0,
                currency="USD",
                by_category=[
                    BudgetCategoryValidation(
                        category="transport",
                        allocated=1500.0,
                        cost=2000.0,
                        over=True
                    ),
                    BudgetCategoryValidation(
                        category="accommodation",
                        allocated=1750.0,
                        cost=2500.0,
                        over=True
                    )
                ],
                issues=["Total cost exceeds budget by $1500"],
                warnings=[]
            )
            response_data = BudgetResponse(
                mode=BudgetMode.VALIDATE,
                validation=validation
            )
            message = response_data.model_dump_json()

            result = agent.parse_response(message)

            assert result['is_task_complete'] is True
            content = json.loads(result['content'])
            assert content['validation']['valid'] is False
            assert len(content['validation']['issues']) > 0


class TestBudgetResponseModel:
    """Tests for BudgetResponse model validation."""

    def test_budget_response_with_only_proposal(self):
        """Test creating BudgetResponse with only proposal."""
        proposal = BudgetProposal(
            total_budget=5000.0,
            currency="USD",
            allocations=[BudgetCategoryAmount(category="transport", amount=1500.0)]
        )
        response = BudgetResponse(mode=BudgetMode.PROPOSE, proposal=proposal)
        assert response.mode == BudgetMode.PROPOSE
        assert response.proposal is not None
        assert response.validation is None

    def test_budget_response_with_only_validation(self):
        """Test creating BudgetResponse with only validation."""
        validation = BudgetValidation(
            valid=True,
            total_budget=5000.0,
            total_cost=4000.0,
            currency="USD",
            by_category=[]
        )
        response = BudgetResponse(mode=BudgetMode.VALIDATE, validation=validation)
        assert response.mode == BudgetMode.VALIDATE
        assert response.validation is not None

    def test_budget_response_with_only_tracking(self):
        """Test creating BudgetResponse with only tracking."""
        tracking = BudgetTracking(
            total_budget=5000.0,
            total_spent=2000.0,
            currency="USD",
            by_category=[],
            remaining=3000.0
        )
        response = BudgetResponse(mode=BudgetMode.TRACK, tracking=tracking)
        assert response.mode == BudgetMode.TRACK
        assert response.tracking is not None

    def test_budget_response_with_only_reallocation(self):
        """Test creating BudgetResponse with only reallocation."""
        reallocation = BudgetReallocation(
            original_allocations=[BudgetCategoryAmount(category="transport", amount=1500.0)],
            suggested_allocations=[BudgetCategoryAmount(category="transport", amount=1200.0)],
            currency="USD",
            suggestions=[],
            potential_savings=300.0
        )
        response = BudgetResponse(mode=BudgetMode.REALLOCATE, reallocation=reallocation)
        assert response.mode == BudgetMode.REALLOCATE
        assert response.reallocation is not None

    def test_budget_response_with_response_text(self):
        """Test creating BudgetResponse with response text."""
        response = BudgetResponse(response="Need more details")
        assert response.mode is None
        assert response.response == "Need more details"

    def test_budget_response_rejects_extra_fields(self):
        """Test that BudgetResponse rejects extra fields."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            BudgetResponse(
                mode=BudgetMode.PROPOSE,
                extra_field="not allowed"
            )

    def test_budget_response_json_serialization(self):
        """Test BudgetResponse can be serialized to JSON."""
        proposal = BudgetProposal(
            total_budget=5000.0,
            currency="USD",
            allocations=[BudgetCategoryAmount(category="transport", amount=1500.0)],
            rationale="Test"
        )
        response = BudgetResponse(mode=BudgetMode.PROPOSE, proposal=proposal)
        json_str = response.model_dump_json()
        parsed = json.loads(json_str)
        assert 'mode' in parsed
        assert 'proposal' in parsed


class TestBudgetModeEnum:
    """Tests for BudgetMode enum."""

    def test_budget_mode_propose(self):
        """Test PROPOSE mode value."""
        assert BudgetMode.PROPOSE.value == "propose"

    def test_budget_mode_validate(self):
        """Test VALIDATE mode value."""
        assert BudgetMode.VALIDATE.value == "validate"

    def test_budget_mode_track(self):
        """Test TRACK mode value."""
        assert BudgetMode.TRACK.value == "track"

    def test_budget_mode_reallocate(self):
        """Test REALLOCATE mode value."""
        assert BudgetMode.REALLOCATE.value == "reallocate"

    def test_budget_mode_is_string_enum(self):
        """Test that BudgetMode is a string enum."""
        assert isinstance(BudgetMode.PROPOSE, str)
        assert BudgetMode.PROPOSE == "propose"


class TestBudgetProposalModel:
    """Tests for BudgetProposal model."""

    def test_budget_proposal_required_fields(self):
        """Test BudgetProposal with required fields only."""
        proposal = BudgetProposal(
            total_budget=5000.0,
            currency="USD",
            allocations=[BudgetCategoryAmount(category="transport", amount=1500.0)]
        )
        assert proposal.total_budget == 5000.0
        assert proposal.currency == "USD"
        assert proposal.rationale is None

    def test_budget_proposal_all_fields(self):
        """Test BudgetProposal with all fields."""
        proposal = BudgetProposal(
            total_budget=5000.0,
            currency="USD",
            allocations=[
                BudgetCategoryAmount(category="transport", amount=1500.0),
                BudgetCategoryAmount(category="accommodation", amount=1750.0),
                BudgetCategoryAmount(category="activities", amount=750.0),
            ],
            rationale="Standard allocation"
        )
        assert proposal.rationale == "Standard allocation"
        assert len(proposal.allocations) == 3


class TestBudgetValidationModel:
    """Tests for BudgetValidation model."""

    def test_budget_validation_valid(self):
        """Test valid BudgetValidation."""
        validation = BudgetValidation(
            valid=True,
            total_budget=5000.0,
            total_cost=4000.0,
            currency="USD",
            by_category=[]
        )
        assert validation.valid is True
        assert len(validation.issues) == 0

    def test_budget_validation_with_issues(self):
        """Test BudgetValidation with issues."""
        validation = BudgetValidation(
            valid=False,
            total_budget=5000.0,
            total_cost=6000.0,
            currency="USD",
            by_category=[],
            issues=["Over budget by $1000"],
            warnings=["Consider cheaper alternatives"]
        )
        assert validation.valid is False
        assert len(validation.issues) == 1
        assert len(validation.warnings) == 1


class TestBudgetCategoryValidation:
    """Tests for BudgetCategoryValidation model."""

    def test_category_validation_under_budget(self):
        """Test category validation when under budget."""
        cat_val = BudgetCategoryValidation(
            category="transport",
            allocated=1500.0,
            cost=1200.0,
            over=False
        )
        assert cat_val.over is False
        assert cat_val.category == "transport"

    def test_category_validation_over_budget(self):
        """Test category validation when over budget."""
        cat_val = BudgetCategoryValidation(
            category="accommodation",
            allocated=1500.0,
            cost=2000.0,
            over=True
        )
        assert cat_val.over is True
        assert cat_val.category == "accommodation"


class TestAgentNoTools:
    """Tests to verify the agent has no external tools."""

    @pytest.fixture
    def agent(self, mock_environment):
        """Create an agent instance for testing."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.budget_agent.agent import AgentFrameworkBudgetAgent
            return AgentFrameworkBudgetAgent()

    def test_agent_has_no_tools(self, agent, mock_environment):
        """Verify the budget agent does not require external tools."""
        with patch.dict(os.environ, mock_environment):
            tools = agent.get_tools()
            assert len(tools) == 0
            assert tools == []

    def test_agent_inherits_from_base(self, mock_environment):
        """Test that agent inherits from BaseAgentFrameworkAgent."""
        with patch.dict(os.environ, mock_environment):
            from src.agents.budget_agent.agent import AgentFrameworkBudgetAgent
            from src.shared.agents.base_agent import BaseAgentFrameworkAgent

            assert issubclass(AgentFrameworkBudgetAgent, BaseAgentFrameworkAgent)
