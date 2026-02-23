import logging
from typing import Any
from dotenv import load_dotenv

from src.shared.agents.base_agent import BaseAgentFrameworkAgent
from src.shared.models import ClarifierResponse

logger = logging.getLogger(__name__)
load_dotenv()

class AgentFrameworkIntakeClarifierAgent(BaseAgentFrameworkAgent):
    """Wraps Microsoft Agent Framework-based agents to handle traveller's intake messages."""

    def get_agent_name(self) -> str:
        return "IntakeClarifierAgent"

    def get_prompt_name(self) -> str:
        return "clarifier"

    def get_response_format(self) -> Any:
        return ClarifierResponse

    def parse_response(self, message: Any) -> dict[str, Any]:
        """Extract the structured response from the agent's message content."""
        try:
            # Parse as ClarifierResponse (structured output)
            clarifier_response = ClarifierResponse.model_validate_json(message)
            
            # If response is None, the task is complete
            if clarifier_response.response is None:
                return {
                    'is_task_complete': True,
                    'require_user_input': False,
                    'content': str(clarifier_response.trip_spec.model_dump_json()),  # Return the trip spec
                }
            else:
                # If response has text, we need more user input
                return {
                    'is_task_complete': False,
                    'require_user_input': True,
                    'content': clarifier_response.response,
                }
                
        except Exception as e:
            logger.error(f"Failed to parse ClarifierResponse: {e}")
            logger.error(f"Raw message: {message}")
            return {
                'is_task_complete': False,
                'require_user_input': True,
                'content': 'We are unable to process your request at the moment. Please try again.',
            }
