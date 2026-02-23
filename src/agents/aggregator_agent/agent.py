import logging
from typing import Any
from dotenv import load_dotenv

from src.shared.agents.base_agent import BaseAgentFrameworkAgent
from src.shared.models import AggregatorResponse

logger = logging.getLogger(__name__)
load_dotenv()


class AgentFrameworkAggregatorAgent(BaseAgentFrameworkAgent):
    """Wraps Microsoft Agent Framework to aggregate discovery results.

    Combines raw discovery outputs from multiple discovery agents:
    - POI Agent: Points of interest
    - Stay Agent: Accommodations
    - Transport Agent: Flights, trains, buses, local transfers
    - Events Agent: Festivals, concerts, exhibitions
    - Dining Agent: Restaurants and food experiences

    This agent does NOT validate against TripSpec - that is the Validator Agent's job.
    """

    def get_agent_name(self) -> str:
        return "AggregatorAgent"

    def get_prompt_name(self) -> str:
        return "aggregator"

    def get_response_format(self) -> Any:
        return AggregatorResponse

    def get_tools(self) -> list[Any]:
        # Aggregator does not need external tools - it combines data from other agents
        return []

    def parse_response(self, message: Any) -> dict[str, Any]:
        """Extract the structured response from the agent's message content."""
        try:
            aggregator_response = AggregatorResponse.model_validate_json(message)

            # AggregatorResponse.response is used when required inputs are missing.
            # This lets the agent ask follow-up questions while keeping output structured.
            if aggregator_response.response:
                return {
                    'is_task_complete': False,
                    'require_user_input': True,
                    'content': aggregator_response.response,
                }

            # AggregatorResponse.aggregated_results is the successful result payload.
            if aggregator_response.aggregated_results:
                return {
                    'is_task_complete': True,
                    'require_user_input': False,
                    'content': aggregator_response.aggregated_results.model_dump_json(),
                }

            return {
                'is_task_complete': False,
                'require_user_input': True,
                'content': 'Please provide discovery results from at least one agent to aggregate.',
            }

        except Exception as e:
            logger.error(f"Failed to parse AggregatorResponse: {e}")
            logger.error(f"Raw message: {message}")
            return {
                'is_task_complete': False,
                'require_user_input': True,
                'content': 'We are unable to process your request at the moment. Please try again.',
            }
