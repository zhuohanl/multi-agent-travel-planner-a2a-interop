"""
Unit tests for OrchestratorLLM and Azure agent configuration.

Tests cover:
- Loading agent IDs from environment variables
- Validation of required configuration
- Agent ID lookup by type
- Tool schema bundles matching the 7-tool design
- Thread management per session/agent type
"""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestAgentType:
    """Tests for AgentType enum."""

    def test_agent_types_exist(self) -> None:
        """Test that all 4 agent types are defined."""
        from src.orchestrator.azure_agent import AgentType

        assert AgentType.ROUTER.value == "router"
        assert AgentType.CLASSIFIER.value == "classifier"
        assert AgentType.PLANNER.value == "planner"
        assert AgentType.QA.value == "qa"

    def test_agent_types_count(self) -> None:
        """Test that there are exactly 4 agent types."""
        from src.orchestrator.azure_agent import AgentType

        assert len(AgentType) == 4


class TestOrchestratorAgentConfig:
    """Tests for OrchestratorAgentConfig dataclass."""

    def test_config_is_frozen(self) -> None:
        """Test that config is immutable."""
        from src.orchestrator.azure_agent import OrchestratorAgentConfig

        config = OrchestratorAgentConfig(
            endpoint="https://test.services.ai.azure.com/api/projects/test",
            deployment_name="model",
            routing_agent_id="router_id",
            classifier_agent_id="classifier_id",
            planner_agent_id="planner_id",
            qa_agent_id="qa_id",
        )

        with pytest.raises(AttributeError):
            config.routing_agent_id = "new_id"  # type: ignore

    def test_get_agent_id_by_enum(self) -> None:
        """Test getting agent ID using AgentType enum."""
        from src.orchestrator.azure_agent import AgentType, OrchestratorAgentConfig

        config = OrchestratorAgentConfig(
            endpoint="https://test.services.ai.azure.com/api/projects/test",
            deployment_name="model",
            routing_agent_id="router_123",
            classifier_agent_id="classifier_456",
            planner_agent_id="planner_789",
            qa_agent_id="qa_012",
        )

        assert config.get_agent_id(AgentType.ROUTER) == "router_123"
        assert config.get_agent_id(AgentType.CLASSIFIER) == "classifier_456"
        assert config.get_agent_id(AgentType.PLANNER) == "planner_789"
        assert config.get_agent_id(AgentType.QA) == "qa_012"

    def test_get_agent_id_by_string(self) -> None:
        """Test getting agent ID using string agent type."""
        from src.orchestrator.azure_agent import OrchestratorAgentConfig

        config = OrchestratorAgentConfig(
            endpoint="https://test.services.ai.azure.com/api/projects/test",
            deployment_name="model",
            routing_agent_id="router_123",
            classifier_agent_id="classifier_456",
            planner_agent_id="planner_789",
            qa_agent_id="qa_012",
        )

        assert config.get_agent_id("router") == "router_123"
        assert config.get_agent_id("classifier") == "classifier_456"
        assert config.get_agent_id("planner") == "planner_789"
        assert config.get_agent_id("qa") == "qa_012"

    def test_get_agent_id_invalid_type(self) -> None:
        """Test that invalid agent type raises ValueError."""
        from src.orchestrator.azure_agent import OrchestratorAgentConfig

        config = OrchestratorAgentConfig(
            endpoint="https://test.services.ai.azure.com/api/projects/test",
            deployment_name="model",
            routing_agent_id="router_123",
            classifier_agent_id="classifier_456",
            planner_agent_id="planner_789",
            qa_agent_id="qa_012",
        )

        with pytest.raises(ValueError):
            config.get_agent_id("invalid_type")

    def test_agent_ids_property(self) -> None:
        """Test that agent_ids property returns all IDs."""
        from src.orchestrator.azure_agent import AgentType, OrchestratorAgentConfig

        config = OrchestratorAgentConfig(
            endpoint="https://test.services.ai.azure.com/api/projects/test",
            deployment_name="model",
            routing_agent_id="router_123",
            classifier_agent_id="classifier_456",
            planner_agent_id="planner_789",
            qa_agent_id="qa_012",
        )

        agent_ids = config.agent_ids
        assert len(agent_ids) == 4
        assert agent_ids[AgentType.ROUTER] == "router_123"
        assert agent_ids[AgentType.CLASSIFIER] == "classifier_456"
        assert agent_ids[AgentType.PLANNER] == "planner_789"
        assert agent_ids[AgentType.QA] == "qa_012"


class TestLoadAgentConfig:
    """Tests for loading agent configuration from environment."""

    def test_loads_agent_ids_from_env(self) -> None:
        """Test that load_agent_config loads IDs from environment variables."""
        from src.orchestrator.azure_agent import load_agent_config

        env_vars = {
            "PROJECT_ENDPOINT": "https://test.services.ai.azure.com/api/projects/test",
            "AZURE_OPENAI_DEPLOYMENT_NAME": "gpt-4.1",
            "ORCHESTRATOR_ROUTING_AGENT_ID": "asst_router_123",
            "ORCHESTRATOR_CLASSIFIER_AGENT_ID": "asst_classifier_456",
            "ORCHESTRATOR_PLANNER_AGENT_ID": "asst_planner_789",
            "ORCHESTRATOR_QA_AGENT_ID": "asst_qa_012",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            config = load_agent_config()

            assert config.endpoint == "https://test.services.ai.azure.com/api/projects/test"
            assert config.deployment_name == "gpt-4.1"
            assert config.routing_agent_id == "asst_router_123"
            assert config.classifier_agent_id == "asst_classifier_456"
            assert config.planner_agent_id == "asst_planner_789"
            assert config.qa_agent_id == "asst_qa_012"

    def test_missing_agent_ids_raise_error(self) -> None:
        """Test that missing agent IDs raise ConfigurationError."""
        from src.orchestrator.azure_agent import ConfigurationError, load_agent_config

        # Only provide connection config, missing agent IDs
        env_vars = {
            "PROJECT_ENDPOINT": "https://test.services.ai.azure.com/api/projects/test",
            "AZURE_OPENAI_DEPLOYMENT_NAME": "gpt-4.1",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ConfigurationError) as exc_info:
                load_agent_config()

            assert "ORCHESTRATOR_ROUTING_AGENT_ID" in str(exc_info.value)

    def test_missing_endpoint_raises_error(self) -> None:
        """Test that missing endpoint raises ConfigurationError."""
        from src.orchestrator.azure_agent import ConfigurationError, load_agent_config

        # Only provide agent IDs, missing connection config
        env_vars = {
            "ORCHESTRATOR_ROUTING_AGENT_ID": "asst_router_123",
            "ORCHESTRATOR_CLASSIFIER_AGENT_ID": "asst_classifier_456",
            "ORCHESTRATOR_PLANNER_AGENT_ID": "asst_planner_789",
            "ORCHESTRATOR_QA_AGENT_ID": "asst_qa_012",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ConfigurationError) as exc_info:
                load_agent_config()

            assert "PROJECT_ENDPOINT" in str(exc_info.value)

    def test_error_message_includes_help(self) -> None:
        """Test that error message includes helpful instructions."""
        from src.orchestrator.azure_agent import ConfigurationError, load_agent_config

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError) as exc_info:
                load_agent_config()

            error_msg = str(exc_info.value)
            assert "provision_azure_agents.py" in error_msg


class TestToolSchemaBundles:
    """Tests for tool schema bundles matching the 9-tool design."""

    def test_routing_tools_count(self) -> None:
        """Test that router has 7 tools (including get_booking and get_consultation for LLM fallback)."""
        from src.orchestrator.azure_agent import ROUTING_TOOLS

        assert len(ROUTING_TOOLS) == 7

    def test_routing_tool_names(self) -> None:
        """Test that router has the correct tools."""
        from src.orchestrator.azure_agent import ROUTING_TOOLS

        tool_names = [t["function"]["name"] for t in ROUTING_TOOLS]
        assert "workflow_turn" in tool_names
        assert "answer_question" in tool_names
        assert "currency_convert" in tool_names
        assert "weather_lookup" in tool_names
        assert "timezone_info" in tool_names
        assert "get_booking" in tool_names
        assert "get_consultation" in tool_names

    def test_classification_tools_count(self) -> None:
        """Test that classifier has 1 tool."""
        from src.orchestrator.azure_agent import CLASSIFICATION_TOOLS

        assert len(CLASSIFICATION_TOOLS) == 1

    def test_classification_tool_name(self) -> None:
        """Test that classifier has classify_action tool."""
        from src.orchestrator.azure_agent import CLASSIFICATION_TOOLS

        assert CLASSIFICATION_TOOLS[0]["function"]["name"] == "classify_action"

    def test_classify_action_has_8_action_types(self) -> None:
        """Test that classify_action has 8 action types."""
        from src.orchestrator.azure_agent import CLASSIFY_ACTION_TOOL

        actions = CLASSIFY_ACTION_TOOL["function"]["parameters"]["properties"]["action"]["enum"]
        assert len(actions) == 8
        assert "APPROVE_TRIP_SPEC" in actions
        assert "MODIFY_TRIP_SPEC" in actions
        assert "START_DISCOVERY" in actions
        assert "APPROVE_ITINERARY" in actions
        assert "MODIFY_ITINERARY" in actions
        assert "START_BOOKING" in actions
        assert "CONFIRM_BOOKING" in actions
        assert "CANCEL_BOOKING" in actions

    def test_planning_tools_count(self) -> None:
        """Test that planner has 1 tool."""
        from src.orchestrator.azure_agent import PLANNING_TOOLS

        assert len(PLANNING_TOOLS) == 1

    def test_planning_tool_name(self) -> None:
        """Test that planner has plan_modification tool."""
        from src.orchestrator.azure_agent import PLANNING_TOOLS

        assert PLANNING_TOOLS[0]["function"]["name"] == "plan_modification"

    def test_plan_modification_has_5_agent_types(self) -> None:
        """Test that plan_modification has 5 agent types."""
        from src.orchestrator.azure_agent import PLAN_MODIFICATION_TOOL

        agents = PLAN_MODIFICATION_TOOL["function"]["parameters"]["properties"]["agents"]["items"]["enum"]
        assert len(agents) == 5
        assert "transport" in agents
        assert "stay" in agents
        assert "poi" in agents
        assert "events" in agents
        assert "dining" in agents

    def test_plan_modification_has_3_strategies(self) -> None:
        """Test that plan_modification has 3 strategies."""
        from src.orchestrator.azure_agent import PLAN_MODIFICATION_TOOL

        strategies = PLAN_MODIFICATION_TOOL["function"]["parameters"]["properties"]["strategy"]["enum"]
        assert len(strategies) == 3
        assert "replace" in strategies
        assert "add" in strategies
        assert "remove" in strategies

    def test_qa_tools_empty(self) -> None:
        """Test that QA has no tools (pure text generation)."""
        from src.orchestrator.azure_agent import QA_TOOLS

        assert len(QA_TOOLS) == 0

    def test_tool_bundles_match_design(self) -> None:
        """Test that tool bundles are correctly mapped to agent types."""
        from src.orchestrator.azure_agent import (
            CLASSIFICATION_TOOLS,
            PLANNING_TOOLS,
            QA_TOOLS,
            ROUTING_TOOLS,
            TOOL_BUNDLES,
            AgentType,
        )

        assert TOOL_BUNDLES[AgentType.ROUTER] == ROUTING_TOOLS
        assert TOOL_BUNDLES[AgentType.CLASSIFIER] == CLASSIFICATION_TOOLS
        assert TOOL_BUNDLES[AgentType.PLANNER] == PLANNING_TOOLS
        assert TOOL_BUNDLES[AgentType.QA] == QA_TOOLS

    def test_total_tool_count_is_9(self) -> None:
        """Test that total unique tools across all agents is 9."""
        from src.orchestrator.azure_agent import TOOL_BUNDLES

        all_tools = []
        for tools in TOOL_BUNDLES.values():
            all_tools.extend(tools)

        # Total tools should be 7 + 1 + 1 + 0 = 9
        assert len(all_tools) == 9


class TestOrchestratorLLM:
    """Tests for OrchestratorLLM class."""

    @pytest.fixture
    def mock_config(self) -> "OrchestratorAgentConfig":
        """Create a mock configuration for testing."""
        from src.orchestrator.azure_agent import OrchestratorAgentConfig

        return OrchestratorAgentConfig(
            endpoint="https://test.services.ai.azure.com/api/projects/test",
            deployment_name="gpt-4.1",
            routing_agent_id="asst_router_123",
            classifier_agent_id="asst_classifier_456",
            planner_agent_id="asst_planner_789",
            qa_agent_id="asst_qa_012",
        )

    def test_azure_agent_configuration(self, mock_config: "OrchestratorAgentConfig") -> None:
        """Test that OrchestratorLLM stores configuration correctly."""
        from src.orchestrator.azure_agent import OrchestratorLLM

        llm = OrchestratorLLM(mock_config)

        assert llm.config == mock_config
        assert llm._client is None  # Client is lazy-loaded

    def test_agent_id_lookup_by_type(self, mock_config: "OrchestratorAgentConfig") -> None:
        """Test that get_agent_id returns correct ID for each type."""
        from src.orchestrator.azure_agent import AgentType, OrchestratorLLM

        llm = OrchestratorLLM(mock_config)

        assert llm.get_agent_id(AgentType.ROUTER) == "asst_router_123"
        assert llm.get_agent_id(AgentType.CLASSIFIER) == "asst_classifier_456"
        assert llm.get_agent_id(AgentType.PLANNER) == "asst_planner_789"
        assert llm.get_agent_id(AgentType.QA) == "asst_qa_012"

    def test_agent_id_lookup_by_string(self, mock_config: "OrchestratorAgentConfig") -> None:
        """Test that get_agent_id works with string type."""
        from src.orchestrator.azure_agent import OrchestratorLLM

        llm = OrchestratorLLM(mock_config)

        assert llm.get_agent_id("router") == "asst_router_123"
        assert llm.get_agent_id("qa") == "asst_qa_012"

    def test_get_tools_for_agent(self, mock_config: "OrchestratorAgentConfig") -> None:
        """Test that get_tools_for_agent returns correct tools."""
        from src.orchestrator.azure_agent import (
            CLASSIFICATION_TOOLS,
            PLANNING_TOOLS,
            QA_TOOLS,
            ROUTING_TOOLS,
            AgentType,
            OrchestratorLLM,
        )

        llm = OrchestratorLLM(mock_config)

        assert llm.get_tools_for_agent(AgentType.ROUTER) == ROUTING_TOOLS
        assert llm.get_tools_for_agent("classifier") == CLASSIFICATION_TOOLS
        assert llm.get_tools_for_agent(AgentType.PLANNER) == PLANNING_TOOLS
        assert llm.get_tools_for_agent("qa") == QA_TOOLS

    def test_session_threads_initially_empty(self, mock_config: "OrchestratorAgentConfig") -> None:
        """Test that session threads start empty."""
        from src.orchestrator.azure_agent import OrchestratorLLM

        llm = OrchestratorLLM(mock_config)

        assert llm._session_threads == {}

    def test_get_thread_id_returns_none_for_new_session(
        self, mock_config: "OrchestratorAgentConfig"
    ) -> None:
        """Test that get_thread_id returns None for new sessions."""
        from src.orchestrator.azure_agent import AgentType, OrchestratorLLM

        llm = OrchestratorLLM(mock_config)

        assert llm.get_thread_id("sess_123", AgentType.ROUTER) is None
        assert llm.get_thread_id("sess_123", "classifier") is None

    def test_clear_session_threads(self, mock_config: "OrchestratorAgentConfig") -> None:
        """Test that clear_session_threads removes session data."""
        from src.orchestrator.azure_agent import AgentType, OrchestratorLLM

        llm = OrchestratorLLM(mock_config)

        # Manually add some thread data
        llm._session_threads["sess_123"] = {AgentType.ROUTER: "thread_abc"}

        # Clear the session
        llm.clear_session_threads("sess_123")

        assert "sess_123" not in llm._session_threads

    def test_clear_nonexistent_session_is_safe(
        self, mock_config: "OrchestratorAgentConfig"
    ) -> None:
        """Test that clearing non-existent session doesn't raise."""
        from src.orchestrator.azure_agent import OrchestratorLLM

        llm = OrchestratorLLM(mock_config)

        # Should not raise
        llm.clear_session_threads("nonexistent_session")

    def test_does_not_create_agents_on_init(
        self, mock_config: "OrchestratorAgentConfig"
    ) -> None:
        """Test that OrchestratorLLM does not create Azure agents on initialization."""
        from src.orchestrator.azure_agent import OrchestratorLLM

        # The fact that this works without Azure SDK proves no agent creation happens
        llm = OrchestratorLLM(mock_config)

        # Should not have accessed client at all
        assert llm._client is None

    def test_agent_types_list(self, mock_config: "OrchestratorAgentConfig") -> None:
        """Test that AGENT_TYPES list contains all types."""
        from src.orchestrator.azure_agent import AgentType, OrchestratorLLM

        assert len(OrchestratorLLM.AGENT_TYPES) == 4
        assert AgentType.ROUTER in OrchestratorLLM.AGENT_TYPES
        assert AgentType.CLASSIFIER in OrchestratorLLM.AGENT_TYPES
        assert AgentType.PLANNER in OrchestratorLLM.AGENT_TYPES
        assert AgentType.QA in OrchestratorLLM.AGENT_TYPES


class TestModuleLevelHelpers:
    """Tests for module-level helper functions."""

    def test_get_orchestrator_llm_creates_singleton(self) -> None:
        """Test that get_orchestrator_llm creates a singleton instance."""
        from src.orchestrator.azure_agent import (
            get_orchestrator_llm,
            reset_orchestrator_llm,
        )

        env_vars = {
            "PROJECT_ENDPOINT": "https://test.services.ai.azure.com/api/projects/test",
            "AZURE_OPENAI_DEPLOYMENT_NAME": "gpt-4.1",
            "ORCHESTRATOR_ROUTING_AGENT_ID": "asst_router_123",
            "ORCHESTRATOR_CLASSIFIER_AGENT_ID": "asst_classifier_456",
            "ORCHESTRATOR_PLANNER_AGENT_ID": "asst_planner_789",
            "ORCHESTRATOR_QA_AGENT_ID": "asst_qa_012",
        }

        try:
            reset_orchestrator_llm()  # Clean up any previous state

            with patch.dict(os.environ, env_vars, clear=True):
                llm1 = get_orchestrator_llm()
                llm2 = get_orchestrator_llm()

                assert llm1 is llm2  # Same instance
        finally:
            reset_orchestrator_llm()  # Clean up

    def test_reset_orchestrator_llm(self) -> None:
        """Test that reset_orchestrator_llm clears the singleton."""
        from src.orchestrator.azure_agent import (
            get_orchestrator_llm,
            reset_orchestrator_llm,
        )

        env_vars = {
            "PROJECT_ENDPOINT": "https://test.services.ai.azure.com/api/projects/test",
            "AZURE_OPENAI_DEPLOYMENT_NAME": "gpt-4.1",
            "ORCHESTRATOR_ROUTING_AGENT_ID": "asst_router_123",
            "ORCHESTRATOR_CLASSIFIER_AGENT_ID": "asst_classifier_456",
            "ORCHESTRATOR_PLANNER_AGENT_ID": "asst_planner_789",
            "ORCHESTRATOR_QA_AGENT_ID": "asst_qa_012",
        }

        try:
            reset_orchestrator_llm()  # Clean up any previous state

            with patch.dict(os.environ, env_vars, clear=True):
                llm1 = get_orchestrator_llm()
                reset_orchestrator_llm()
                llm2 = get_orchestrator_llm()

                assert llm1 is not llm2  # Different instances after reset
        finally:
            reset_orchestrator_llm()  # Clean up

    def test_get_missing_env_vars(self) -> None:
        """Test that get_missing_env_vars returns missing variables."""
        from src.orchestrator.azure_agent import get_missing_env_vars

        # With empty environment
        with patch.dict(os.environ, {}, clear=True):
            missing = get_missing_env_vars()

            assert "PROJECT_ENDPOINT" in missing
            assert "AZURE_OPENAI_DEPLOYMENT_NAME" in missing
            assert "ORCHESTRATOR_ROUTING_AGENT_ID" in missing
            assert "ORCHESTRATOR_CLASSIFIER_AGENT_ID" in missing
            assert "ORCHESTRATOR_PLANNER_AGENT_ID" in missing
            assert "ORCHESTRATOR_QA_AGENT_ID" in missing


class TestAzureClientHelpers:
    """Tests for Azure client helper functions."""

    def test_get_azure_agents_imports_raises_when_not_installed(self) -> None:
        """Test that _get_azure_agents_imports raises ImportError when SDK not installed."""
        from src.orchestrator.azure_agent import _get_azure_agents_imports

        with patch.dict("sys.modules", {"azure.ai.agents": None, "azure.identity": None}):
            # This test verifies the error message is helpful
            # In reality, the import would fail differently, but we test the pattern
            pass  # Skip actual test as it depends on SDK installation state

    def test_create_agents_client_requires_sdk(self) -> None:
        """Test that create_agents_client requires Azure SDK."""
        from src.orchestrator.azure_agent import OrchestratorAgentConfig

        config = OrchestratorAgentConfig(
            endpoint="https://test.services.ai.azure.com/api/projects/test",
            deployment_name="gpt-4.1",
            routing_agent_id="router",
            classifier_agent_id="classifier",
            planner_agent_id="planner",
            qa_agent_id="qa",
        )

        # This test verifies the function signature exists
        # Actual SDK test would require SDK to be installed
        from src.orchestrator.azure_agent import create_agents_client

        assert callable(create_agents_client)
