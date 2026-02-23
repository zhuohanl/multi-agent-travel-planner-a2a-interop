"""Tests for M365 SDK Client wrapper (INTEROP-014).

Tests verify:
- Client initialization from environment variables
- Token acquisition scope
- Conversation start
- Message sending and activity yielding
- Activity type parsing (message and event)
- Approval decision event handling
"""

import json
from dataclasses import dataclass
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from interoperability.pro_code.m365_sdk_client import (
    Activity,
    CopilotStudioClient,
    CopilotStudioClientConfig,
    POWER_PLATFORM_SCOPE,
    _parse_activity,
)


# --- Fixtures ---


@pytest.fixture
def env_vars(monkeypatch):
    """Set up required COPILOTSTUDIOAGENT__* environment variables."""
    monkeypatch.setenv("COPILOTSTUDIOAGENT__TENANTID", "test-tenant-id")
    monkeypatch.setenv("COPILOTSTUDIOAGENT__ENVIRONMENTID", "test-env-id")
    monkeypatch.setenv("COPILOTSTUDIOAGENT__AGENTAPPID", "test-app-id")
    monkeypatch.setenv("COPILOTSTUDIOAGENT__AGENTAPPSECRET", "test-secret")
    monkeypatch.setenv("COPILOTSTUDIOAGENT__SCHEMANAME", "test-schema")


@pytest.fixture
def approval_env_vars(monkeypatch):
    """Set up env vars with agent-specific schema name for approval agent."""
    monkeypatch.setenv("COPILOTSTUDIOAGENT__TENANTID", "test-tenant-id")
    monkeypatch.setenv("COPILOTSTUDIOAGENT__ENVIRONMENTID", "test-env-id")
    monkeypatch.setenv("COPILOTSTUDIOAGENT__AGENTAPPID", "test-app-id")
    monkeypatch.setenv("COPILOTSTUDIOAGENT__AGENTAPPSECRET", "test-secret")
    monkeypatch.setenv("COPILOTSTUDIOAGENT__APPROVAL__SCHEMANAME", "approval-schema")


@pytest.fixture
def config(env_vars):
    """Create a CopilotStudioClientConfig from env vars."""
    return CopilotStudioClientConfig.from_env()


@pytest.fixture
def client(config):
    """Create a CopilotStudioClient with test config."""
    return CopilotStudioClient(config)


# --- Mock SDK types ---


@dataclass
class MockReply:
    """Mock for SDK activity reply."""

    type: Any
    text: Optional[str] = None
    name: Optional[str] = None
    value: Optional[Any] = None


class MockActivityType:
    """Mock for ActivityTypes enum values."""

    def __init__(self, value: str):
        self._value = value

    def __str__(self) -> str:
        return f"ActivityTypes.{self._value}"


# --- Test: Client Initialization ---


class TestClientInitializationFromEnv:
    """Test CopilotStudioClientConfig.from_env()."""

    def test_client_initialization_from_env(self, env_vars):
        """Config loads all required env vars correctly."""
        config = CopilotStudioClientConfig.from_env()
        assert config.tenant_id == "test-tenant-id"
        assert config.environment_id == "test-env-id"
        assert config.agent_app_id == "test-app-id"
        assert config.agent_app_secret == "test-secret"
        assert config.schema_name == "test-schema"

    def test_client_initialization_with_agent_prefix(self, approval_env_vars):
        """Config loads agent-specific schema name with prefix."""
        config = CopilotStudioClientConfig.from_env(agent_prefix="APPROVAL")
        assert config.schema_name == "approval-schema"

    def test_client_initialization_missing_tenant_id(self, monkeypatch):
        """Raises ValueError when TENANTID is missing."""
        monkeypatch.delenv("COPILOTSTUDIOAGENT__TENANTID", raising=False)
        monkeypatch.setenv("COPILOTSTUDIOAGENT__ENVIRONMENTID", "env-id")
        monkeypatch.setenv("COPILOTSTUDIOAGENT__AGENTAPPID", "app-id")
        monkeypatch.setenv("COPILOTSTUDIOAGENT__AGENTAPPSECRET", "secret")
        monkeypatch.setenv("COPILOTSTUDIOAGENT__SCHEMANAME", "schema")
        with pytest.raises(ValueError, match="COPILOTSTUDIOAGENT__TENANTID"):
            CopilotStudioClientConfig.from_env()

    def test_client_initialization_missing_multiple(self, monkeypatch):
        """Raises ValueError listing all missing env vars."""
        monkeypatch.setenv("COPILOTSTUDIOAGENT__TENANTID", "tenant")
        monkeypatch.delenv("COPILOTSTUDIOAGENT__ENVIRONMENTID", raising=False)
        monkeypatch.delenv("COPILOTSTUDIOAGENT__AGENTAPPID", raising=False)
        monkeypatch.delenv("COPILOTSTUDIOAGENT__AGENTAPPSECRET", raising=False)
        monkeypatch.delenv("COPILOTSTUDIOAGENT__SCHEMANAME", raising=False)
        with pytest.raises(ValueError) as exc_info:
            CopilotStudioClientConfig.from_env()
        error_msg = str(exc_info.value)
        assert "COPILOTSTUDIOAGENT__ENVIRONMENTID" in error_msg
        assert "COPILOTSTUDIOAGENT__AGENTAPPID" in error_msg
        assert "COPILOTSTUDIOAGENT__AGENTAPPSECRET" in error_msg
        assert "COPILOTSTUDIOAGENT__SCHEMANAME" in error_msg

    def test_client_initialization_empty_value_treated_as_missing(self, monkeypatch):
        """Empty string env vars are treated as missing."""
        monkeypatch.setenv("COPILOTSTUDIOAGENT__TENANTID", "")
        monkeypatch.setenv("COPILOTSTUDIOAGENT__ENVIRONMENTID", "env-id")
        monkeypatch.setenv("COPILOTSTUDIOAGENT__AGENTAPPID", "app-id")
        monkeypatch.setenv("COPILOTSTUDIOAGENT__AGENTAPPSECRET", "secret")
        monkeypatch.setenv("COPILOTSTUDIOAGENT__SCHEMANAME", "schema")
        with pytest.raises(ValueError, match="COPILOTSTUDIOAGENT__TENANTID"):
            CopilotStudioClientConfig.from_env()

    def test_copilot_studio_client_stores_config(self, config):
        """CopilotStudioClient stores the config."""
        client = CopilotStudioClient(config)
        assert client.config == config


# --- Test: Token Acquisition ---


class TestTokenAcquisitionScope:
    """Test token acquisition uses correct scope."""

    def test_token_acquisition_scope(self, client):
        """Token acquisition uses https://api.powerplatform.com/.default scope."""
        assert POWER_PLATFORM_SCOPE == "https://api.powerplatform.com/.default"

    @patch("interoperability.pro_code.m365_sdk_client.CopilotStudioClient.acquire_token")
    def test_acquire_token_returns_token(self, mock_acquire, client):
        """acquire_token returns the access token string."""
        mock_acquire.return_value = "mock-access-token"
        token = client.acquire_token()
        assert token == "mock-access-token"

    def test_acquire_token_uses_msal(self, client):
        """acquire_token calls MSAL ConfidentialClientApplication."""
        mock_msal_app = MagicMock()
        mock_msal_app.acquire_token_for_client.return_value = {
            "access_token": "test-token-123"
        }

        with patch(
            "interoperability.pro_code.m365_sdk_client.CopilotStudioClient.acquire_token"
        ) as mock_method:
            mock_method.return_value = "test-token-123"
            token = client.acquire_token()
            assert token == "test-token-123"

    def test_acquire_token_failure_raises_error(self, client):
        """acquire_token raises RuntimeError on MSAL failure."""
        mock_msal_module = MagicMock()
        mock_msal_app = MagicMock()
        mock_msal_app.acquire_token_for_client.return_value = {
            "error": "invalid_client",
            "error_description": "Bad credentials",
        }
        mock_msal_module.ConfidentialClientApplication.return_value = mock_msal_app

        with patch.dict("sys.modules", {"msal": mock_msal_module}):
            with pytest.raises(RuntimeError, match="Token acquisition failed"):
                client.acquire_token()

    def test_acquire_token_correct_authority(self, client):
        """acquire_token uses correct tenant-specific authority URL."""
        mock_msal_module = MagicMock()
        mock_msal_app = MagicMock()
        mock_msal_app.acquire_token_for_client.return_value = {
            "access_token": "token"
        }
        mock_msal_module.ConfidentialClientApplication.return_value = mock_msal_app

        with patch.dict("sys.modules", {"msal": mock_msal_module}):
            client.acquire_token()
            mock_msal_module.ConfidentialClientApplication.assert_called_once_with(
                client_id="test-app-id",
                authority="https://login.microsoftonline.com/test-tenant-id",
                client_credential="test-secret",
            )

    def test_acquire_token_correct_scope(self, client):
        """acquire_token passes correct Power Platform scope."""
        mock_msal_module = MagicMock()
        mock_msal_app = MagicMock()
        mock_msal_app.acquire_token_for_client.return_value = {
            "access_token": "token"
        }
        mock_msal_module.ConfidentialClientApplication.return_value = mock_msal_app

        with patch.dict("sys.modules", {"msal": mock_msal_module}):
            client.acquire_token()
            mock_msal_app.acquire_token_for_client.assert_called_once_with(
                scopes=[POWER_PLATFORM_SCOPE]
            )


# --- Test: Start Conversation ---


class TestStartConversation:
    """Test starting a conversation with the agent."""

    @pytest.mark.asyncio
    async def test_start_conversation_returns_id(self, client):
        """start_conversation returns a conversation ID string."""
        mock_copilot_client = AsyncMock()
        mock_copilot_client.start_conversation = AsyncMock(
            return_value="conv-12345"
        )
        client._copilot_client = mock_copilot_client
        client._token = "mock-token"

        conversation_id = await client.start_conversation()
        assert conversation_id == "conv-12345"

    @pytest.mark.asyncio
    async def test_start_conversation_calls_emit_start_event(self, client):
        """start_conversation calls SDK with emit_start_event=True."""
        mock_copilot_client = AsyncMock()
        mock_copilot_client.start_conversation = AsyncMock(
            return_value="conv-id"
        )
        client._copilot_client = mock_copilot_client
        client._token = "mock-token"

        await client.start_conversation()
        mock_copilot_client.start_conversation.assert_called_once_with(
            emit_start_event=True
        )


# --- Test: Send Message ---


class TestSendMessageYieldsActivities:
    """Test sending messages and receiving activities."""

    @pytest.mark.asyncio
    async def test_send_message_yields_activities(self, client):
        """send_message yields Activity objects from SDK replies."""
        mock_reply = MockReply(type="message", text="Hello from agent")

        async def mock_ask_question(message, conv_id):
            yield mock_reply

        mock_copilot_client = MagicMock()
        mock_copilot_client.ask_question = mock_ask_question
        client._copilot_client = mock_copilot_client
        client._token = "mock-token"

        activities = []
        async for activity in client.send_message("test", "conv-1"):
            activities.append(activity)

        assert len(activities) == 1
        assert activities[0].type == "message"
        assert activities[0].text == "Hello from agent"

    @pytest.mark.asyncio
    async def test_send_message_yields_multiple_activities(self, client):
        """send_message yields multiple activities in order."""
        replies = [
            MockReply(type="message", text="Processing..."),
            MockReply(type="message", text="Here is the result"),
            MockReply(
                type="event",
                name="approval_decision",
                value={"decision": "approved"},
            ),
        ]

        async def mock_ask_question(message, conv_id):
            for r in replies:
                yield r

        mock_copilot_client = MagicMock()
        mock_copilot_client.ask_question = mock_ask_question
        client._copilot_client = mock_copilot_client
        client._token = "mock-token"

        activities = []
        async for activity in client.send_message("approve this", "conv-1"):
            activities.append(activity)

        assert len(activities) == 3
        assert activities[0].is_message
        assert activities[1].is_message
        assert activities[2].is_event

    @pytest.mark.asyncio
    async def test_send_message_skips_unparseable_replies(self, client):
        """send_message skips replies without a type attribute."""

        async def mock_ask_question(message, conv_id):
            yield "not-an-activity-object"
            yield MockReply(type="message", text="valid")

        mock_copilot_client = MagicMock()
        mock_copilot_client.ask_question = mock_ask_question
        client._copilot_client = mock_copilot_client
        client._token = "mock-token"

        activities = []
        async for activity in client.send_message("test", "conv-1"):
            activities.append(activity)

        assert len(activities) == 1
        assert activities[0].text == "valid"


# --- Test: Message Activity ---


class TestMessageActivityHasText:
    """Test message activity properties."""

    def test_message_activity_has_text(self):
        """Message activity has text field."""
        activity = Activity(type="message", text="Hello")
        assert activity.text == "Hello"
        assert activity.is_message is True
        assert activity.is_event is False

    def test_message_activity_none_text(self):
        """Message activity can have None text."""
        activity = Activity(type="message", text=None)
        assert activity.text is None
        assert activity.is_message is True


# --- Test: Event Activity Parsed ---


class TestEventActivityParsed:
    """Test event activity parsing."""

    def test_event_activity_parsed(self):
        """Event activity has name and value fields."""
        activity = Activity(
            type="event",
            name="approval_decision",
            value={"decision": "approved", "feedback": "Looks good"},
        )
        assert activity.is_event is True
        assert activity.is_message is False
        assert activity.name == "approval_decision"
        assert activity.value == {"decision": "approved", "feedback": "Looks good"}

    def test_event_activity_no_value(self):
        """Event activity can have no value."""
        activity = Activity(type="event", name="some_event")
        assert activity.is_event is True
        assert activity.value is None


# --- Test: Approval Decision Event Handling ---


class TestApprovalDecisionEventHandling:
    """Test approval decision event parsing via request_approval()."""

    @pytest.mark.asyncio
    async def test_approval_decision_event_handling(self, client):
        """request_approval returns decision dict from approval_decision event."""
        replies = [
            MockReply(type="message", text="Reviewing your itinerary..."),
            MockReply(
                type="event",
                name="approval_decision",
                value={"decision": "approved", "feedback": ""},
            ),
        ]

        async def mock_ask_question(message, conv_id):
            for r in replies:
                yield r

        mock_copilot_client = MagicMock()
        mock_copilot_client.ask_question = mock_ask_question
        mock_copilot_client.start_conversation = AsyncMock(return_value="conv-1")
        client._copilot_client = mock_copilot_client
        client._token = "mock-token"

        result = await client.request_approval('{"itinerary": "test"}')
        assert result["decision"] == "approved"

    @pytest.mark.asyncio
    async def test_approval_decision_rejected_with_feedback(self, client):
        """request_approval handles rejected decision with feedback."""
        replies = [
            MockReply(
                type="event",
                name="approval_decision",
                value={"decision": "rejected", "feedback": "Budget too high"},
            ),
        ]

        async def mock_ask_question(message, conv_id):
            for r in replies:
                yield r

        mock_copilot_client = MagicMock()
        mock_copilot_client.ask_question = mock_ask_question
        mock_copilot_client.start_conversation = AsyncMock(return_value="conv-1")
        client._copilot_client = mock_copilot_client
        client._token = "mock-token"

        result = await client.request_approval('{"itinerary": "test"}')
        assert result["decision"] == "rejected"
        assert result["feedback"] == "Budget too high"

    @pytest.mark.asyncio
    async def test_approval_decision_modify(self, client):
        """request_approval handles modify decision."""
        replies = [
            MockReply(
                type="event",
                name="approval_decision",
                value={"decision": "modify", "feedback": "Change hotel"},
            ),
        ]

        async def mock_ask_question(message, conv_id):
            for r in replies:
                yield r

        mock_copilot_client = MagicMock()
        mock_copilot_client.ask_question = mock_ask_question
        mock_copilot_client.start_conversation = AsyncMock(return_value="conv-1")
        client._copilot_client = mock_copilot_client
        client._token = "mock-token"

        result = await client.request_approval('{"itinerary": "test"}')
        assert result["decision"] == "modify"
        assert result["feedback"] == "Change hotel"

    @pytest.mark.asyncio
    async def test_approval_no_response_returns_pending(self, client):
        """request_approval returns pending when no decision event received."""

        async def mock_ask_question(message, conv_id):
            yield MockReply(type="message", text="Processing...")
            # No event activity follows

        mock_copilot_client = MagicMock()
        mock_copilot_client.ask_question = mock_ask_question
        mock_copilot_client.start_conversation = AsyncMock(return_value="conv-1")
        client._copilot_client = mock_copilot_client
        client._token = "mock-token"

        result = await client.request_approval('{"itinerary": "test"}')
        assert result["decision"] == "pending"
        assert "No response" in result["feedback"]

    @pytest.mark.asyncio
    async def test_approval_decision_json_string_value(self, client):
        """request_approval handles JSON string value in event."""
        replies = [
            MockReply(
                type="event",
                name="approval_decision",
                value=json.dumps({"decision": "approved", "feedback": "OK"}),
            ),
        ]

        async def mock_ask_question(message, conv_id):
            for r in replies:
                yield r

        mock_copilot_client = MagicMock()
        mock_copilot_client.ask_question = mock_ask_question
        mock_copilot_client.start_conversation = AsyncMock(return_value="conv-1")
        client._copilot_client = mock_copilot_client
        client._token = "mock-token"

        result = await client.request_approval('{"itinerary": "test"}')
        assert result["decision"] == "approved"


# --- Test: Activity Parsing ---


class TestParseActivity:
    """Test _parse_activity helper."""

    def test_parse_message_activity(self):
        """Parses message type reply."""
        reply = MockReply(type="message", text="Hello")
        activity = _parse_activity(reply)
        assert activity is not None
        assert activity.type == "message"
        assert activity.text == "Hello"

    def test_parse_event_activity(self):
        """Parses event type reply."""
        reply = MockReply(
            type="event", name="test_event", value={"key": "val"}
        )
        activity = _parse_activity(reply)
        assert activity is not None
        assert activity.type == "event"
        assert activity.name == "test_event"

    def test_parse_enum_type(self):
        """Handles ActivityTypes.message enum-style type."""
        reply = MockReply(type=MockActivityType("message"), text="Hi")
        activity = _parse_activity(reply)
        assert activity is not None
        assert activity.type == "message"
        assert activity.text == "Hi"

    def test_parse_enum_event_type(self):
        """Handles ActivityTypes.event enum-style type."""
        reply = MockReply(
            type=MockActivityType("event"),
            name="approval_decision",
            value={"decision": "approved"},
        )
        activity = _parse_activity(reply)
        assert activity is not None
        assert activity.type == "event"
        assert activity.name == "approval_decision"

    def test_parse_no_type_returns_none(self):
        """Returns None for objects without type attribute."""
        activity = _parse_activity("not-an-activity")
        assert activity is None

    def test_parse_unknown_type(self):
        """Handles unknown activity types gracefully."""
        reply = MockReply(type="typing")
        activity = _parse_activity(reply)
        assert activity is not None
        assert activity.type == "typing"
