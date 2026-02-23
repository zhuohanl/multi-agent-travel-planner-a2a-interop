"""Unit tests for Azure AI Agent Service setup."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infrastructure.azure_agent_setup import (
    ALL_DOCUMENTED_VARS,
    REQUIRED_AGENT_ID_VARS,
    REQUIRED_CONNECTION_VARS,
    AzureAgentConfig,
    get_azure_config,
    get_missing_env_vars,
    parse_endpoint,
    print_env_template,
)


# Mock azure packages for tests
@pytest.fixture(autouse=True)
def mock_azure_packages():
    """Mock azure.ai.agents and azure.identity modules for tests."""
    mock_ai_agents = MagicMock()
    mock_identity = MagicMock()

    # Create mock client
    mock_client_instance = MagicMock()
    mock_ai_agents.AgentsClient = MagicMock(return_value=mock_client_instance)

    # Create mock credential
    mock_identity.DefaultAzureCredential = MagicMock()

    with patch.dict(
        sys.modules,
        {
            "azure": MagicMock(),
            "azure.ai": MagicMock(),
            "azure.ai.agents": mock_ai_agents,
            "azure.identity": mock_identity,
        },
    ):
        yield mock_ai_agents, mock_identity


class TestRequiredEnvVarsDocumented:
    """Tests for environment variable documentation."""

    def test_required_env_vars_documented(self) -> None:
        """All required connection variables are documented."""
        assert len(REQUIRED_CONNECTION_VARS) == 2
        assert "PROJECT_ENDPOINT" in REQUIRED_CONNECTION_VARS
        assert "AZURE_OPENAI_DEPLOYMENT_NAME" in REQUIRED_CONNECTION_VARS

    def test_agent_ids_documented(self) -> None:
        """All required agent ID variables are documented."""
        assert len(REQUIRED_AGENT_ID_VARS) == 4
        assert "ORCHESTRATOR_ROUTING_AGENT_ID" in REQUIRED_AGENT_ID_VARS
        assert "ORCHESTRATOR_CLASSIFIER_AGENT_ID" in REQUIRED_AGENT_ID_VARS
        assert "ORCHESTRATOR_PLANNER_AGENT_ID" in REQUIRED_AGENT_ID_VARS
        assert "ORCHESTRATOR_QA_AGENT_ID" in REQUIRED_AGENT_ID_VARS

    def test_all_documented_vars_includes_both(self) -> None:
        """ALL_DOCUMENTED_VARS includes both connection and agent ID vars."""
        assert set(ALL_DOCUMENTED_VARS) == set(REQUIRED_CONNECTION_VARS + REQUIRED_AGENT_ID_VARS)


class TestEndpointParsing:
    """Tests for endpoint URL parsing."""

    def test_endpoint_parsing_valid(self) -> None:
        """Parses valid endpoint URL correctly."""
        endpoint = "https://my-resource.services.ai.azure.com/api/projects/my-project"
        result = parse_endpoint(endpoint)

        assert result["resource_name"] == "my-resource"
        assert result["project_name"] == "my-project"

    def test_endpoint_parsing_invalid_format(self) -> None:
        """Raises ValueError for invalid endpoint format."""
        with pytest.raises(ValueError) as exc_info:
            parse_endpoint("invalid-endpoint")
        assert "Invalid endpoint format" in str(exc_info.value)

    def test_endpoint_parsing_missing_https(self) -> None:
        """Raises ValueError when endpoint is missing https."""
        with pytest.raises(ValueError):
            parse_endpoint("http://my-resource.services.ai.azure.com/api/projects/my-project")

    def test_endpoint_parsing_wrong_domain(self) -> None:
        """Raises ValueError when endpoint has wrong domain."""
        with pytest.raises(ValueError):
            parse_endpoint("https://my-resource.azure.com/api/projects/my-project")


class TestAzureAgentConfig:
    """Tests for AzureAgentConfig dataclass."""

    def test_config_has_connection_config_true(self) -> None:
        """has_connection_config is True when both values present."""
        config = AzureAgentConfig(
            endpoint="https://test.services.ai.azure.com/api/projects/test",
            deployment_name="gpt-4",
        )
        assert config.has_connection_config is True

    def test_config_has_connection_config_false_missing_endpoint(self) -> None:
        """has_connection_config is False when endpoint missing."""
        config = AzureAgentConfig(
            endpoint="",
            deployment_name="gpt-4",
        )
        assert config.has_connection_config is False

    def test_config_has_connection_config_false_missing_deployment(self) -> None:
        """has_connection_config is False when deployment name missing."""
        config = AzureAgentConfig(
            endpoint="https://test.services.ai.azure.com/api/projects/test",
            deployment_name="",
        )
        assert config.has_connection_config is False

    def test_config_has_agent_ids_true(self) -> None:
        """has_agent_ids is True when all agent IDs present."""
        config = AzureAgentConfig(
            endpoint="https://test.services.ai.azure.com/api/projects/test",
            deployment_name="gpt-4",
            routing_agent_id="agent-1",
            classifier_agent_id="agent-2",
            planner_agent_id="agent-3",
            qa_agent_id="agent-4",
        )
        assert config.has_agent_ids is True

    def test_config_has_agent_ids_false_missing_one(self) -> None:
        """has_agent_ids is False when any agent ID missing."""
        config = AzureAgentConfig(
            endpoint="https://test.services.ai.azure.com/api/projects/test",
            deployment_name="gpt-4",
            routing_agent_id="agent-1",
            classifier_agent_id="agent-2",
            planner_agent_id="agent-3",
            qa_agent_id=None,  # Missing
        )
        assert config.has_agent_ids is False

    def test_config_agent_id_dict(self) -> None:
        """agent_id_dict returns correct dictionary."""
        config = AzureAgentConfig(
            endpoint="https://test.services.ai.azure.com/api/projects/test",
            deployment_name="gpt-4",
            routing_agent_id="router-123",
            classifier_agent_id="class-456",
            planner_agent_id="plan-789",
            qa_agent_id="qa-012",
        )
        expected = {
            "router": "router-123",
            "classifier": "class-456",
            "planner": "plan-789",
            "qa": "qa-012",
        }
        assert config.agent_id_dict == expected

    def test_config_is_frozen(self) -> None:
        """AzureAgentConfig is immutable."""
        config = AzureAgentConfig(
            endpoint="https://test.services.ai.azure.com/api/projects/test",
            deployment_name="gpt-4",
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            config.deployment_name = "new-value"  # type: ignore


class TestGetMissingEnvVars:
    """Tests for get_missing_env_vars function."""

    def test_returns_missing_vars(self) -> None:
        """Returns list of missing environment variables."""
        with patch.dict("os.environ", {}, clear=True):
            missing = get_missing_env_vars(["VAR_A", "VAR_B"])
            assert missing == ["VAR_A", "VAR_B"]

    def test_returns_empty_when_all_present(self) -> None:
        """Returns empty list when all variables present."""
        with patch.dict("os.environ", {"VAR_A": "value", "VAR_B": "value"}, clear=True):
            missing = get_missing_env_vars(["VAR_A", "VAR_B"])
            assert missing == []

    def test_returns_only_missing(self) -> None:
        """Returns only the missing variables."""
        with patch.dict("os.environ", {"VAR_A": "value"}, clear=True):
            missing = get_missing_env_vars(["VAR_A", "VAR_B", "VAR_C"])
            assert missing == ["VAR_B", "VAR_C"]


class TestGetAzureConfig:
    """Tests for get_azure_config function."""

    def test_raises_when_connection_vars_missing(self) -> None:
        """Raises ValueError when connection variables are missing."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError) as exc_info:
                get_azure_config()
            assert "PROJECT_ENDPOINT" in str(exc_info.value)

    def test_loads_config_without_agent_ids(self) -> None:
        """Loads config successfully without agent IDs."""
        env = {
            "PROJECT_ENDPOINT": "https://test.services.ai.azure.com/api/projects/test",
            "AZURE_OPENAI_DEPLOYMENT_NAME": "gpt-4",
        }
        with patch.dict("os.environ", env, clear=True):
            config = get_azure_config(require_agent_ids=False)
            assert config.endpoint == "https://test.services.ai.azure.com/api/projects/test"
            assert config.deployment_name == "gpt-4"
            assert config.routing_agent_id is None

    def test_raises_when_agent_ids_required_but_missing(self) -> None:
        """Raises ValueError when agent IDs required but missing."""
        env = {
            "PROJECT_ENDPOINT": "https://test.services.ai.azure.com/api/projects/test",
            "AZURE_OPENAI_DEPLOYMENT_NAME": "gpt-4",
        }
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(ValueError) as exc_info:
                get_azure_config(require_agent_ids=True)
            assert "ORCHESTRATOR_ROUTING_AGENT_ID" in str(exc_info.value)

    def test_loads_full_config_with_agent_ids(self) -> None:
        """Loads complete config including agent IDs."""
        env = {
            "PROJECT_ENDPOINT": "https://test.services.ai.azure.com/api/projects/test",
            "AZURE_OPENAI_DEPLOYMENT_NAME": "gpt-4",
            "ORCHESTRATOR_ROUTING_AGENT_ID": "router-123",
            "ORCHESTRATOR_CLASSIFIER_AGENT_ID": "class-456",
            "ORCHESTRATOR_PLANNER_AGENT_ID": "plan-789",
            "ORCHESTRATOR_QA_AGENT_ID": "qa-012",
        }
        with patch.dict("os.environ", env, clear=True):
            config = get_azure_config(require_agent_ids=True)
            assert config.endpoint == "https://test.services.ai.azure.com/api/projects/test"
            assert config.deployment_name == "gpt-4"
            assert config.routing_agent_id == "router-123"
            assert config.classifier_agent_id == "class-456"
            assert config.planner_agent_id == "plan-789"
            assert config.qa_agent_id == "qa-012"


class TestPrintEnvTemplate:
    """Tests for print_env_template function."""

    def test_template_contains_all_vars(self) -> None:
        """Template contains all required environment variables."""
        template = print_env_template()

        assert "PROJECT_ENDPOINT" in template
        assert "AZURE_OPENAI_DEPLOYMENT_NAME" in template
        assert "ORCHESTRATOR_ROUTING_AGENT_ID" in template
        assert "ORCHESTRATOR_CLASSIFIER_AGENT_ID" in template
        assert "ORCHESTRATOR_PLANNER_AGENT_ID" in template
        assert "ORCHESTRATOR_QA_AGENT_ID" in template

    def test_template_contains_instructions(self) -> None:
        """Template contains setup instructions."""
        template = print_env_template()

        assert "Azure AI Agent Service" in template
        assert "provision_azure_agents.py" in template


class TestCreateAgentsClient:
    """Tests for create_agents_client function."""

    def test_creates_client_from_config(self, mock_azure_packages) -> None:
        """Creates AgentsClient from configuration."""
        mock_ai_agents, mock_identity = mock_azure_packages

        from infrastructure.azure_agent_setup import create_agents_client

        config = AzureAgentConfig(
            endpoint="https://test.services.ai.azure.com/api/projects/test",
            deployment_name="gpt-4",
        )

        client = create_agents_client(config)

        mock_ai_agents.AgentsClient.assert_called_once()
        call_kwargs = mock_ai_agents.AgentsClient.call_args.kwargs
        assert call_kwargs["endpoint"] == "https://test.services.ai.azure.com/api/projects/test"


class TestVerifyConnection:
    """Tests for verify_connection function."""

    @pytest.mark.asyncio
    async def test_verify_connection_success(self, mock_azure_packages) -> None:
        """Returns connected=True when connection succeeds."""
        mock_ai_agents, _ = mock_azure_packages

        # Set up mock client that returns agents
        # SDK 2.0.0b3: list() instead of list_agents()
        mock_client = MagicMock()
        mock_client.list_agents.return_value = iter([MagicMock()])
        mock_ai_agents.AgentsClient.return_value = mock_client

        from infrastructure.azure_agent_setup import verify_connection

        config = AzureAgentConfig(
            endpoint="https://my-resource.services.ai.azure.com/api/projects/my-project",
            deployment_name="gpt-4",
        )

        result = await verify_connection(config)

        assert result["connected"] is True
        assert result["project_name"] == "my-project"
        assert result["resource_name"] == "my-resource"
        assert result["deployment_name"] == "gpt-4"

    @pytest.mark.asyncio
    async def test_verify_connection_failure(self, mock_azure_packages) -> None:
        """Returns connected=False when connection fails."""
        mock_ai_agents, _ = mock_azure_packages

        # Set up mock client that raises exception
        # SDK 2.0.0b3: list() instead of list_agents()
        mock_client = MagicMock()
        mock_client.list_agents.side_effect = Exception("Connection refused")
        mock_ai_agents.AgentsClient.return_value = mock_client

        from infrastructure.azure_agent_setup import verify_connection

        config = AzureAgentConfig(
            endpoint="https://my-resource.services.ai.azure.com/api/projects/my-project",
            deployment_name="gpt-4",
        )

        result = await verify_connection(config)

        assert result["connected"] is False
        assert "error" in result


class TestVerifyAgentIds:
    """Tests for verify_agent_ids function."""

    @pytest.mark.asyncio
    async def test_raises_when_no_agent_ids(self, mock_azure_packages) -> None:
        """Raises ValueError when agent IDs not configured."""
        from infrastructure.azure_agent_setup import verify_agent_ids

        config = AzureAgentConfig(
            endpoint="https://test.services.ai.azure.com/api/projects/test",
            deployment_name="gpt-4",
        )

        with pytest.raises(ValueError) as exc_info:
            await verify_agent_ids(config)
        assert "not configured" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_verifies_all_agents(self, mock_azure_packages) -> None:
        """Verifies all configured agent IDs."""
        mock_ai_agents, _ = mock_azure_packages

        # Set up mock client that returns agent info
        # SDK 2.0.0b3: get() instead of get_agent(), returns dict-like object
        mock_agent = {"id": "router-123", "name": "test-router"}

        mock_client = MagicMock()
        mock_client.get_agent.return_value = mock_agent
        mock_ai_agents.AgentsClient.return_value = mock_client

        from infrastructure.azure_agent_setup import verify_agent_ids

        config = AzureAgentConfig(
            endpoint="https://test.services.ai.azure.com/api/projects/test",
            deployment_name="gpt-4",
            routing_agent_id="router-123",
            classifier_agent_id="class-456",
            planner_agent_id="plan-789",
            qa_agent_id="qa-012",
        )

        results = await verify_agent_ids(config)

        assert len(results) == 4
        assert results["router"]["exists"] is True
        assert results["classifier"]["exists"] is True
        assert results["planner"]["exists"] is True
        assert results["qa"]["exists"] is True

    @pytest.mark.asyncio
    async def test_handles_agent_not_found(self, mock_azure_packages) -> None:
        """Returns exists=False for agents that don't exist."""
        mock_ai_agents, _ = mock_azure_packages

        # Set up mock client that raises exception for missing agent
        # SDK 2.0.0b3: get() instead of get_agent()
        mock_client = MagicMock()
        mock_client.get_agent.side_effect = Exception("Agent not found")
        mock_ai_agents.AgentsClient.return_value = mock_client

        from infrastructure.azure_agent_setup import verify_agent_ids

        config = AzureAgentConfig(
            endpoint="https://test.services.ai.azure.com/api/projects/test",
            deployment_name="gpt-4",
            routing_agent_id="missing-agent",
            classifier_agent_id="class-456",
            planner_agent_id="plan-789",
            qa_agent_id="qa-012",
        )

        results = await verify_agent_ids(config)

        assert results["router"]["exists"] is False
        assert "error" in results["router"]
