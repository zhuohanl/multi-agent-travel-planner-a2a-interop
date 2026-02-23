import logging
from typing import Any
from dotenv import load_dotenv

from src.shared.agents.base_agent import BaseAgentFrameworkAgent
from src.shared.models import ValidatorResponse

logger = logging.getLogger(__name__)
load_dotenv()


class AgentFrameworkValidatorAgent(BaseAgentFrameworkAgent):
    """Wraps Microsoft Agent Framework to validate itineraries against TripSpec.

    Validates:
    - Budget: Total cost within budget constraints
    - Date coverage: All travel dates have activities
    - Interests: User interests are addressed
    - Constraints: User constraints are respected

    Returns ValidationResult with passed, issues[], and warnings[].
    """

    def get_agent_name(self) -> str:
        return "ValidatorAgent"

    def get_prompt_name(self) -> str:
        return "validator"

    def get_response_format(self) -> Any:
        return ValidatorResponse

    def get_tools(self) -> list[Any]:
        # Validator agent does not need external tools - it performs validation logic
        return []

    def parse_response(self, message: Any) -> dict[str, Any]:
        """Extract the structured response from the agent's message content."""
        try:
            validator_response = ValidatorResponse.model_validate_json(message)

            # ValidatorResponse.response is used when required inputs are missing
            if validator_response.response:
                return {
                    'is_task_complete': False,
                    'require_user_input': True,
                    'content': validator_response.response,
                }

            # Handle validation result output
            if validator_response.validation_result:
                return {
                    'is_task_complete': True,
                    'require_user_input': False,
                    'content': validator_response.model_dump_json(),
                }

            # No valid output found
            return {
                'is_task_complete': False,
                'require_user_input': True,
                'content': 'Please provide a TripSpec and Itinerary to validate.',
            }

        except Exception as e:
            logger.error(f"Failed to parse ValidatorResponse: {e}")
            logger.error(f"Raw message: {message}")
            return {
                'is_task_complete': False,
                'require_user_input': True,
                'content': 'We are unable to process your request at the moment. Please try again.',
            }
