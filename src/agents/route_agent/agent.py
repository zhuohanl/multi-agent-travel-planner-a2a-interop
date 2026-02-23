import logging
from typing import Any
from dotenv import load_dotenv

from src.shared.agents.base_agent import BaseAgentFrameworkAgent
from src.shared.models import RouteResponse

logger = logging.getLogger(__name__)
load_dotenv()


class AgentFrameworkRouteAgent(BaseAgentFrameworkAgent):
    """Wraps Microsoft Agent Framework to create day-by-day itineraries.

    Takes aggregated discovery results from the Aggregator Agent and creates
    a day-by-day walkable itinerary that:
    - Covers all dates in the TripSpec range
    - Groups nearby attractions to minimize transit
    - Includes meals, transport, and events in logical time slots
    - Estimates costs based on discovery results

    This agent does NOT validate against TripSpec - that is the Validator Agent's job.
    """

    def get_agent_name(self) -> str:
        return "RouteAgent"

    def get_prompt_name(self) -> str:
        return "route"

    def get_response_format(self) -> Any:
        return RouteResponse

    def get_tools(self) -> list[Any]:
        # Route Agent does not need external tools - it plans from existing discovery data
        return []

    def parse_response(self, message: Any) -> dict[str, Any]:
        """Extract the structured response from the agent's message content."""
        try:
            route_response = RouteResponse.model_validate_json(message)

            # RouteResponse.response is used when required inputs are missing.
            # This lets the agent ask follow-up questions while keeping output structured.
            if route_response.response:
                return {
                    'is_task_complete': False,
                    'require_user_input': True,
                    'content': route_response.response,
                }

            # RouteResponse.itinerary is the successful result payload.
            if route_response.itinerary:
                return {
                    'is_task_complete': True,
                    'require_user_input': False,
                    'content': route_response.itinerary.model_dump_json(),
                }

            return {
                'is_task_complete': False,
                'require_user_input': True,
                'content': 'Please provide TripSpec and discovery results to create an itinerary.',
            }

        except Exception as e:
            logger.error(f"Failed to parse RouteResponse: {e}")
            logger.error(f"Raw message: {message}")
            return {
                'is_task_complete': False,
                'require_user_input': True,
                'content': 'We are unable to process your request at the moment. Please try again.',
            }
