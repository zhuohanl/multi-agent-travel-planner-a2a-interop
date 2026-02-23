"""Booking agent for handling booking operations.

Processes CREATE, MODIFY, and CANCEL actions for travel bookings.
"""
import logging
from typing import Any
from dotenv import load_dotenv

from src.shared.agents.base_agent import BaseAgentFrameworkAgent
from src.shared.models import BookingResponse, BookingAction, BookingStatus

logger = logging.getLogger(__name__)
load_dotenv()


class AgentFrameworkBookingAgent(BaseAgentFrameworkAgent):
    """Wraps Microsoft Agent Framework to handle booking operations.

    Supports three actions:
    - CREATE: Create a new booking with a provider
    - MODIFY: Modify an existing booking
    - CANCEL: Cancel an existing booking
    """

    def get_agent_name(self) -> str:
        return "BookingAgent"

    def get_prompt_name(self) -> str:
        return "booking"

    def get_response_format(self) -> Any:
        return BookingResponse

    def get_tools(self) -> list[Any]:
        # Booking agent does not need external tools - it processes booking requests
        return []

    def parse_response(self, message: Any) -> dict[str, Any]:
        """Extract the structured response from the agent's message content.

        Args:
            message: Raw message from the agent

        Returns:
            Parsed response dict with is_task_complete, require_user_input, content
        """
        try:
            booking_response = BookingResponse.model_validate_json(message)

            # BookingResponse.response is used when required inputs are missing
            # or when clarification is needed about the action
            if booking_response.response:
                return {
                    'is_task_complete': False,
                    'require_user_input': True,
                    'content': booking_response.response,
                }

            # Handle each action's result
            if booking_response.action and booking_response.result:
                # Check if the operation succeeded
                if booking_response.result.success:
                    return {
                        'is_task_complete': True,
                        'require_user_input': False,
                        'content': booking_response.model_dump_json(),
                    }
                else:
                    # Operation failed - return error but task is complete
                    return {
                        'is_task_complete': True,
                        'require_user_input': False,
                        'content': booking_response.model_dump_json(),
                    }

            # No valid action/result combination found
            return {
                'is_task_complete': False,
                'require_user_input': True,
                'content': (
                    'Please specify an action (CREATE, MODIFY, or CANCEL) '
                    'and provide the required booking details.'
                ),
            }

        except Exception as e:
            logger.error(f"Failed to parse BookingResponse: {e}")
            logger.error(f"Raw message: {message}")
            return {
                'is_task_complete': False,
                'require_user_input': True,
                'content': (
                    'We are unable to process your booking request at the moment. '
                    'Please try again.'
                ),
            }
