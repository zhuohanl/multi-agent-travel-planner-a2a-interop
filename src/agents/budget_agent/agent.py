import logging
from typing import Any
from dotenv import load_dotenv

from src.shared.agents.base_agent import BaseAgentFrameworkAgent
from src.shared.models import BudgetResponse, BudgetMode

logger = logging.getLogger(__name__)
load_dotenv()


class AgentFrameworkBudgetAgent(BaseAgentFrameworkAgent):
    """Wraps Microsoft Agent Framework to manage budget allocation and tracking.

    Supports four idempotent modes:
    - PROPOSE: Create budget allocation proposal from TripSpec
    - VALIDATE: Check if selections fit within budget constraints
    - TRACK: Track spending against allocated budget
    - REALLOCATE: Suggest budget reallocation to bring within budget

    This agent is idempotent: given the same inputs, it produces the same outputs.
    """

    def get_agent_name(self) -> str:
        return "BudgetAgent"

    def get_prompt_name(self) -> str:
        return "budget"

    def get_response_format(self) -> Any:
        return BudgetResponse

    def get_tools(self) -> list[Any]:
        # Budget agent does not need external tools - it performs calculations
        return []

    def parse_response(self, message: Any) -> dict[str, Any]:
        """Extract the structured response from the agent's message content."""
        try:
            budget_response = BudgetResponse.model_validate_json(message)

            # BudgetResponse.response is used when required inputs are missing
            # or when clarification is needed about the mode
            if budget_response.response:
                return {
                    'is_task_complete': False,
                    'require_user_input': True,
                    'content': budget_response.response,
                }

            # Handle each mode's output
            if budget_response.mode == BudgetMode.PROPOSE and budget_response.proposal:
                return {
                    'is_task_complete': True,
                    'require_user_input': False,
                    'content': budget_response.model_dump_json(),
                }

            if budget_response.mode == BudgetMode.VALIDATE and budget_response.validation:
                return {
                    'is_task_complete': True,
                    'require_user_input': False,
                    'content': budget_response.model_dump_json(),
                }

            if budget_response.mode == BudgetMode.TRACK and budget_response.tracking:
                return {
                    'is_task_complete': True,
                    'require_user_input': False,
                    'content': budget_response.model_dump_json(),
                }

            if budget_response.mode == BudgetMode.REALLOCATE and budget_response.reallocation:
                return {
                    'is_task_complete': True,
                    'require_user_input': False,
                    'content': budget_response.model_dump_json(),
                }

            # No valid mode/output combination found
            return {
                'is_task_complete': False,
                'require_user_input': True,
                'content': 'Please specify a mode (PROPOSE, VALIDATE, TRACK, or REALLOCATE) and provide the required inputs.',
            }

        except Exception as e:
            logger.error(f"Failed to parse BudgetResponse: {e}")
            logger.error(f"Raw message: {message}")
            return {
                'is_task_complete': False,
                'require_user_input': True,
                'content': 'We are unable to process your request at the moment. Please try again.',
            }
