"""
M365 SDK Client Wrapper for calling Copilot Studio agents.

This module provides a clean interface for interacting with Copilot Studio agents
using the microsoft-agents-copilotstudio-client library with MSAL authentication.

Design doc references:
- Demo B Components table (lines 624-629)
- Appendix A.3 Copilot Studio (lines 1648-1760)
- Cross-Platform Authentication: Pro Code -> CS (lines 1001-1014)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional

logger = logging.getLogger(__name__)

# Token scope for Power Platform API
POWER_PLATFORM_SCOPE = "https://api.powerplatform.com/.default"


@dataclass
class Activity:
    """Represents an activity received from a Copilot Studio agent.

    Activities can be messages (text responses) or events (structured data
    like approval_decision).
    """

    type: str
    text: Optional[str] = None
    name: Optional[str] = None
    value: Optional[Any] = None

    @property
    def is_message(self) -> bool:
        return self.type == "message"

    @property
    def is_event(self) -> bool:
        return self.type == "event"


@dataclass
class CopilotStudioClientConfig:
    """Configuration for connecting to a Copilot Studio agent.

    All values are loaded from COPILOTSTUDIOAGENT__* environment variables
    as documented in the design doc (lines 1679-1685).
    """

    tenant_id: str
    environment_id: str
    agent_app_id: str
    agent_app_secret: str
    schema_name: str

    @classmethod
    def from_env(cls, agent_prefix: str = "") -> "CopilotStudioClientConfig":
        """Load configuration from environment variables.

        Args:
            agent_prefix: Optional agent-specific prefix for SCHEMANAME.
                If provided, looks for COPILOTSTUDIOAGENT__<PREFIX>__SCHEMANAME.
                Common env vars (TENANTID, AGENTAPPID, etc.) are shared.

        Returns:
            CopilotStudioClientConfig with values from environment.

        Raises:
            ValueError: If required environment variables are missing.
        """
        missing = []

        tenant_id = os.environ.get("COPILOTSTUDIOAGENT__TENANTID", "")
        if not tenant_id:
            missing.append("COPILOTSTUDIOAGENT__TENANTID")

        environment_id = os.environ.get("COPILOTSTUDIOAGENT__ENVIRONMENTID", "")
        if not environment_id:
            missing.append("COPILOTSTUDIOAGENT__ENVIRONMENTID")

        agent_app_id = os.environ.get("COPILOTSTUDIOAGENT__AGENTAPPID", "")
        if not agent_app_id:
            missing.append("COPILOTSTUDIOAGENT__AGENTAPPID")

        agent_app_secret = os.environ.get("COPILOTSTUDIOAGENT__AGENTAPPSECRET", "")
        if not agent_app_secret:
            missing.append("COPILOTSTUDIOAGENT__AGENTAPPSECRET")

        # Schema name can be agent-specific
        if agent_prefix:
            schema_key = f"COPILOTSTUDIOAGENT__{agent_prefix.upper()}__SCHEMANAME"
        else:
            schema_key = "COPILOTSTUDIOAGENT__SCHEMANAME"
        schema_name = os.environ.get(schema_key, "")
        if not schema_name:
            missing.append(schema_key)

        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

        return cls(
            tenant_id=tenant_id,
            environment_id=environment_id,
            agent_app_id=agent_app_id,
            agent_app_secret=agent_app_secret,
            schema_name=schema_name,
        )


class CopilotStudioClient:
    """Wrapper around microsoft-agents-copilotstudio-client for calling CS agents.

    Handles authentication via MSAL and provides a clean async interface
    for sending messages and receiving activities (messages and events).

    Usage:
        config = CopilotStudioClientConfig.from_env(agent_prefix="APPROVAL")
        client = CopilotStudioClient(config)
        conversation_id = await client.start_conversation()
        async for activity in client.send_message("Review this itinerary", conversation_id):
            if activity.is_event and activity.name == "approval_decision":
                decision = activity.value
    """

    def __init__(self, config: CopilotStudioClientConfig) -> None:
        self._config = config
        self._token: Optional[str] = None
        self._copilot_client: Any = None

    @property
    def config(self) -> CopilotStudioClientConfig:
        return self._config

    def acquire_token(self) -> str:
        """Acquire an access token using MSAL client credentials flow.

        Uses scope: https://api.powerplatform.com/.default

        Returns:
            Access token string.

        Raises:
            RuntimeError: If token acquisition fails.
        """
        try:
            from msal import ConfidentialClientApplication
        except ImportError as e:
            raise RuntimeError(
                "msal package is required. Install with: uv add msal"
            ) from e

        app = ConfidentialClientApplication(
            client_id=self._config.agent_app_id,
            authority=f"https://login.microsoftonline.com/{self._config.tenant_id}",
            client_credential=self._config.agent_app_secret,
        )

        result = app.acquire_token_for_client(scopes=[POWER_PLATFORM_SCOPE])

        if "access_token" not in result:
            error = result.get("error", "unknown")
            error_desc = result.get("error_description", "No description")
            raise RuntimeError(
                f"Token acquisition failed: {error} - {error_desc}"
            )

        self._token = result["access_token"]
        logger.info("Token acquired successfully for tenant %s", self._config.tenant_id)
        return self._token

    def _get_copilot_client(self) -> Any:
        """Create or return the CopilotClient instance.

        Returns:
            CopilotClient instance configured for the target agent.

        Raises:
            RuntimeError: If CopilotClient cannot be created.
        """
        if self._copilot_client is not None:
            return self._copilot_client

        try:
            from microsoft_agents_copilotstudio_client import (
                ConnectionSettings,
                CopilotClient,
            )
        except ImportError as e:
            raise RuntimeError(
                "microsoft-agents-copilotstudio-client package is required. "
                "Install with: uv add microsoft-agents-copilotstudio-client"
            ) from e

        if self._token is None:
            self.acquire_token()

        settings = ConnectionSettings(
            environment_id=self._config.environment_id,
            agent_identifier=self._config.schema_name,
        )

        self._copilot_client = CopilotClient(settings, self._token)
        return self._copilot_client

    async def start_conversation(self) -> str:
        """Start a new conversation with the Copilot Studio agent.

        Returns:
            Conversation ID string.

        Raises:
            RuntimeError: If conversation cannot be started.
        """
        client = self._get_copilot_client()
        conversation_id = await client.start_conversation(emit_start_event=True)
        logger.info("Started conversation: %s", conversation_id)
        return conversation_id

    async def send_message(
        self, message: str, conversation_id: str
    ) -> AsyncGenerator[Activity, None]:
        """Send a message to the agent and yield response activities.

        Args:
            message: The message text to send.
            conversation_id: The conversation ID from start_conversation().

        Yields:
            Activity objects representing messages and events from the agent.
        """
        client = self._get_copilot_client()

        async for reply in client.ask_question(message, conversation_id):
            activity = _parse_activity(reply)
            if activity is not None:
                yield activity

    async def request_approval(
        self, itinerary_json: str, timeout_seconds: int = 300
    ) -> dict[str, Any]:
        """Send an itinerary for approval and wait for the decision event.

        This is a convenience method specifically for the Demo B approval flow.
        It starts a conversation, sends the itinerary, and waits for the
        approval_decision event.

        Args:
            itinerary_json: Serialized itinerary JSON to approve.
            timeout_seconds: Max wait time (used in prompt, not enforced here).

        Returns:
            Dictionary with 'decision' and optional 'feedback' fields.
        """
        conversation_id = await self.start_conversation()

        prompt = f"Please review and approve this itinerary:\n{itinerary_json}"

        async for activity in self.send_message(prompt, conversation_id):
            if activity.is_event and activity.name == "approval_decision":
                value = activity.value
                if isinstance(value, str):
                    try:
                        return json.loads(value)
                    except json.JSONDecodeError:
                        return {"decision": "pending", "feedback": f"Invalid response: {value}"}
                if isinstance(value, dict):
                    return value
                return {"decision": "pending", "feedback": f"Unexpected value type: {type(value).__name__}"}

            if activity.is_message:
                logger.info("Agent message: %s", activity.text)

        return {"decision": "pending", "feedback": "No response received"}


def _parse_activity(reply: Any) -> Optional[Activity]:
    """Parse a raw SDK reply into an Activity object.

    Args:
        reply: Raw activity from CopilotClient.ask_question().

    Returns:
        Activity object, or None if the reply cannot be parsed.
    """
    activity_type = getattr(reply, "type", None)
    if activity_type is None:
        return None

    # Normalize activity type to string
    activity_type_str = str(activity_type)
    # Handle enum values like ActivityTypes.message -> "message"
    if "." in activity_type_str:
        activity_type_str = activity_type_str.rsplit(".", 1)[-1]

    if activity_type_str == "message":
        return Activity(
            type="message",
            text=getattr(reply, "text", None),
        )
    elif activity_type_str == "event":
        return Activity(
            type="event",
            name=getattr(reply, "name", None),
            value=getattr(reply, "value", None),
        )
    else:
        return Activity(type=activity_type_str)
