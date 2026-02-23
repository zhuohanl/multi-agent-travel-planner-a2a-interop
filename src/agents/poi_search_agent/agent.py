import json
import logging
from typing import Any
from dotenv import load_dotenv

from agent_framework import HostedWebSearchTool

from src.shared.agents.base_agent import BaseAgentFrameworkAgent
from src.shared.models import POISearchResponse

logger = logging.getLogger(__name__)
load_dotenv()


class AgentFrameworkPOISearchAgent(BaseAgentFrameworkAgent):
    """Wraps Microsoft Agent Framework-based agents to search for POIs at travel destinations.

    Supports two modes:
    - Q&A mode (mode="qa"): Answers questions about POIs, returns text response
    - Planning mode (mode="plan" or no mode): Returns structured SearchOutput
    """

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        # Track whether current request is Q&A mode (per-request state)
        self._is_qa_mode: bool = False

    def get_agent_name(self) -> str:
        return "POISearchAgent"

    def get_prompt_name(self) -> str:
        return "search"

    def get_response_format(self) -> Any:
        return POISearchResponse

    def get_tools(self) -> list[Any]:
        return [HostedWebSearchTool()]

    def _detect_qa_mode(self, user_input: str) -> bool:
        """Detect if the request is Q&A mode by parsing the input JSON.

        Per design doc (Tool Definitions section):
        - Q&A mode is signaled by "mode": "qa" in the request JSON
        - Planning mode is "mode": "plan" or no mode field

        Args:
            user_input: The raw user input string.

        Returns:
            True if Q&A mode is detected, False otherwise.
        """
        try:
            request = json.loads(user_input)
            if isinstance(request, dict):
                mode = request.get("mode", "plan")
                return mode == "qa"
        except (json.JSONDecodeError, TypeError):
            # Not valid JSON, assume planning mode (plain text request)
            pass
        return False

    async def stream(
        self,
        user_input: str,
        session_id: str,
        history: list[dict] | None = None,
        history_seq: int | None = None,
    ):
        """Yield a final structured response after streaming completes.

        Overrides base class to detect Q&A mode before processing.

        Args:
            user_input: The user's message to process.
            session_id: Unique identifier for the conversation session.
            history: Optional conversation history from orchestrator.
            history_seq: Optional sequence number for divergence detection.
        """
        # Detect Q&A mode from the input before processing
        self._is_qa_mode = self._detect_qa_mode(user_input)
        if self._is_qa_mode:
            logger.debug("Q&A mode detected for session_id=%s", session_id)

        # Call parent stream implementation
        async for result in super().stream(user_input, session_id, history, history_seq):
            yield result

    async def invoke(
        self,
        user_input: str,
        session_id: str,
        history: list[dict] | None = None,
        history_seq: int | None = None,
    ) -> dict[str, Any]:
        """Handle synchronous tasks (like tasks/send).

        Overrides base class to detect Q&A mode before processing.

        Args:
            user_input: The user's message to process.
            session_id: Unique identifier for the conversation session.
            history: Optional conversation history from orchestrator.
            history_seq: Optional sequence number for divergence detection.
        """
        # Detect Q&A mode from the input before processing
        self._is_qa_mode = self._detect_qa_mode(user_input)
        if self._is_qa_mode:
            logger.debug("Q&A mode detected for session_id=%s", session_id)

        return await super().invoke(user_input, session_id, history, history_seq)

    def parse_response(self, message: Any) -> dict[str, Any]:
        """Extract the structured response from the agent's message content.

        Handles both Q&A mode and planning mode responses:
        - Q&A mode: text response in 'response' field, is_task_complete=True
        - Planning mode: structured output in 'search_output' field
        """
        try:
            # Parse as POISearchResponse (structured output)
            search_response = POISearchResponse.model_validate_json(message)

            # Q&A mode: return text response (single-turn, always complete)
            # Per design doc: Q&A mode sets is_task_complete=True
            if self._is_qa_mode and search_response.response:
                logger.debug("Returning Q&A mode response")
                return {
                    'is_task_complete': True,
                    'require_user_input': False,
                    'content': search_response.response,
                }

            # Planning mode: POISearchResponse.response is used when required inputs are missing.
            # This lets the agent ask follow-up questions while keeping output structured.
            if search_response.response:
                return {
                    'is_task_complete': False,
                    'require_user_input': True,
                    'content': search_response.response,
                }

            # POISearchResponse.search_output is the successful result payload.
            if search_response.search_output:
                return {
                    'is_task_complete': True,
                    'require_user_input': False,
                    'content': search_response.search_output.model_dump_json(),
                }

            return {
                'is_task_complete': False,
                'require_user_input': True,
                'content': 'Please provide the destination city to continue.',
            }

        except Exception as e:
            logger.error(f"Failed to parse POISearchResponse: {e}")
            logger.error(f"Raw message: {message}")
            return {
                'is_task_complete': False,
                'require_user_input': True,
                'content': 'We are unable to process your request at the moment. Please try again.',
            }
