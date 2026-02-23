"""
Unit tests for Foundry deployer.

Tests config parsing, validation, env var injection, and deployment interface.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from interoperability.foundry.deploy import (
    AgentDefinition,
    ConfigParseError,
    DeploymentError,
    FoundryConfig,
    FoundryDeployer,
    WorkflowDefinition,
)

# Note: azure-ai-projects SDK calls are mocked in tests.


class TestConfigParsingValidYaml:
    """Tests for valid YAML config parsing."""

    def test_config_parsing_valid_yaml(self) -> None:
        """Verify deployer parses valid config.yaml correctly."""
        deployer = FoundryDeployer()
        config = deployer.config

        assert config.platform == "azure_ai_foundry"
        assert "agents" in dir(config)
        assert len(config.agents) > 0

    def test_config_parses_agent_definitions(self) -> None:
        """Verify agent definitions are parsed correctly."""
        deployer = FoundryDeployer()
        config = deployer.config

        # Check transport agent (native)
        assert "transport" in config.agents
        transport = config.agents["transport"]
        assert transport.agent_type == "native"
        assert "transport" in transport.source

        # Check stay agent (hosted)
        assert "stay" in config.agents
        stay = config.agents["stay"]
        assert stay.agent_type == "hosted"
        assert stay.framework == "agent_framework"

    def test_config_parses_workflow_definitions(self) -> None:
        """Verify workflow definitions are parsed correctly."""
        deployer = FoundryDeployer()
        config = deployer.config

        assert "discovery_procode" in config.workflows
        procode = config.workflows["discovery_procode"]
        assert procode.workflow_type == "hosted_workflow"


class TestConfigParsingMissingRequiredField:
    """Tests for config parsing with missing required fields."""

    def test_config_parsing_missing_platform(self) -> None:
        """Verify error when platform field is missing."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump({"resource_group": "rg", "project": "proj"}, f)
            temp_path = Path(f.name)

        try:
            deployer = FoundryDeployer(config_path=temp_path)
            with pytest.raises(ConfigParseError) as exc_info:
                _ = deployer.config
            assert "platform" in str(exc_info.value)
        finally:
            temp_path.unlink()

    def test_config_parsing_missing_agent_type(self) -> None:
        """Verify error when agent type is missing."""
        config = {
            "platform": "azure_ai_foundry",
            "resource_group": "rg",
            "project": "proj",
            "agents": {
                "test_agent": {
                    "source": "src/agents/test",
                    # Missing type
                }
            },
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(config, f)
            temp_path = Path(f.name)

        try:
            deployer = FoundryDeployer(config_path=temp_path)
            with pytest.raises(ConfigParseError) as exc_info:
                _ = deployer.config
            assert "type" in str(exc_info.value)
        finally:
            temp_path.unlink()


class TestConfigParsingEnvVarsSection:
    """Tests for env_vars parsing in config."""

    def test_config_parsing_env_vars_section(self) -> None:
        """Verify env_vars are parsed from agent definition."""
        deployer = FoundryDeployer()
        config = deployer.config

        # Weather proxy has env_vars
        assert "weather-proxy" in config.agents
        weather_proxy = config.agents["weather-proxy"]
        assert len(weather_proxy.env_vars) > 0
        assert "COPILOTSTUDIOAGENT__DIRECTLINE_SECRET" in weather_proxy.env_vars

    def test_config_expands_agent_model_env_var(self) -> None:
        """Verify agent model expands ${VAR} from environment."""
        config = {
            "platform": "azure_ai_foundry",
            "resource_group": "rg",
            "project": "proj",
            "agents": {
                "test_agent": {
                    "type": "native",
                    "source": "src/agents/test",
                    "model": "${TEST_MODEL_NAME}",
                }
            },
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(config, f)
            temp_path = Path(f.name)

        try:
            with patch.dict(os.environ, {"TEST_MODEL_NAME": "gpt-test"}):
                deployer = FoundryDeployer(config_path=temp_path)
                parsed = deployer.config
                assert parsed.agents["test_agent"].model == "gpt-test"
        finally:
            temp_path.unlink()


class TestDeployerInjectsEnvVars:
    """Tests for environment variable injection."""

    def test_deployer_injects_env_vars(self) -> None:
        """Verify deployer validates and tracks env vars for agents."""
        deployer = FoundryDeployer()
        config = deployer.config

        # Weather proxy requires env vars
        weather_proxy = config.agents["weather-proxy"]
        with patch.dict(os.environ, {}, clear=True):
            missing = deployer._validate_env_vars(weather_proxy)

        # Without env vars set, should report missing
        assert len(missing) > 0


class TestDeployerSupportsKeyvaultReference:
    """Tests for Key Vault reference support."""

    def test_deployer_supports_keyvault_reference(self) -> None:
        """Verify deployer recognizes Key Vault reference syntax."""
        deployer = FoundryDeployer()

        kv_ref = "@Microsoft.KeyVault(SecretUri=https://vault.azure.net/secrets/test)"
        assert deployer._is_keyvault_reference(kv_ref)

        regular_value = "some-secret-value"
        assert not deployer._is_keyvault_reference(regular_value)


class TestDeployerValidatesRequiredEnvVars:
    """Tests for env var validation."""

    def test_deployer_validates_required_env_vars(self) -> None:
        """Verify deployer checks for required env vars."""
        deployer = FoundryDeployer()
        config = deployer.config

        weather_proxy = config.agents["weather-proxy"]

        # Without any env vars set
        with patch.dict(os.environ, {}, clear=True):
            missing = deployer._validate_env_vars(weather_proxy)
            assert len(missing) == len(weather_proxy.env_vars)

    def test_deployer_validates_with_env_vars_set(self) -> None:
        """Verify deployer passes when env vars are set."""
        deployer = FoundryDeployer()
        config = deployer.config

        weather_proxy = config.agents["weather-proxy"]

        # Set all required env vars
        env_vars = {var: "test-value" for var in weather_proxy.env_vars}
        with patch.dict(os.environ, env_vars, clear=False):
            missing = deployer._validate_env_vars(weather_proxy)
            assert len(missing) == 0


class TestDeployerDryRunMode:
    """Tests for dry-run deployment mode."""

    def test_deployer_dry_run_mode(self) -> None:
        """Verify dry-run mode reports what would be deployed."""
        deployer = FoundryDeployer()

        result = deployer.deploy_agent("transport", dry_run=True)

        assert result["success"] is True
        assert "DRY RUN" in result["message"]
        assert "deployment_info" in result

    def test_deployer_dry_run_all(self) -> None:
        """Verify dry-run mode works for deploy_all."""
        deployer = FoundryDeployer()

        results = deployer.deploy_all(dry_run=True)

        assert "agents" in results
        assert "workflows" in results
        assert "summary" in results

        # All should succeed in dry-run
        for agent_result in results["agents"].values():
            assert agent_result.get("success") is True


class TestDeployerAgentSelection:
    """Tests for deploying specific agents."""

    def test_deployer_agent_selection(self) -> None:
        """Verify deployer can deploy specific agent by name."""
        deployer = FoundryDeployer()

        result = deployer.deploy_agent("transport", dry_run=True)
        assert result["deployment_info"]["agent_name"] == "transport"

    def test_deployer_agent_not_found(self) -> None:
        """Verify deployer raises error for unknown agent."""
        deployer = FoundryDeployer()

        with pytest.raises(DeploymentError) as exc_info:
            deployer.deploy_agent("nonexistent_agent", dry_run=True)

        assert "not found" in str(exc_info.value)


class TestDeployerValidatesAgentType:
    """Tests for agent type validation."""

    def test_deployer_validates_agent_type(self) -> None:
        """Verify deployer validates agent type field."""
        config = {
            "platform": "azure_ai_foundry",
            "resource_group": "rg",
            "project": "proj",
            "agents": {
                "bad_agent": {
                    "type": "invalid_type",
                    "source": "src/agents/test",
                }
            },
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(config, f)
            temp_path = Path(f.name)

        try:
            deployer = FoundryDeployer(config_path=temp_path)
            with pytest.raises(ConfigParseError) as exc_info:
                _ = deployer.config
            assert "invalid type" in str(exc_info.value).lower()
        finally:
            temp_path.unlink()

    def test_deployer_validates_hosted_agent_framework(self) -> None:
        """Verify hosted agents require framework field."""
        config = {
            "platform": "azure_ai_foundry",
            "resource_group": "rg",
            "project": "proj",
            "agents": {
                "bad_hosted": {
                    "type": "hosted",
                    "source": "src/agents/test",
                    # Missing framework
                }
            },
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(config, f)
            temp_path = Path(f.name)

        try:
            deployer = FoundryDeployer(config_path=temp_path)
            with pytest.raises(ConfigParseError) as exc_info:
                _ = deployer.config
            assert "framework" in str(exc_info.value).lower()
        finally:
            temp_path.unlink()


class TestConfigValidation:
    """Tests for configuration validation method."""

    def test_validate_returns_agents_and_workflows(self) -> None:
        """Verify validate returns lists of agents and workflows."""
        deployer = FoundryDeployer()
        result = deployer.validate()

        assert "agents" in result
        assert "workflows" in result
        assert len(result["agents"]) > 0
        assert len(result["workflows"]) > 0

    def test_validate_detects_invalid_workflow_agent_refs(self) -> None:
        """Verify validate catches workflows referencing unknown agents."""
        config = {
            "platform": "azure_ai_foundry",
            "resource_group": "rg",
            "project": "proj",
            "agents": {},
            "workflows": {
                "bad_workflow": {
                    "type": "declarative",
                    "source": "path/to/workflow",
                    "agents": ["nonexistent_agent"],
                }
            },
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(config, f)
            temp_path = Path(f.name)

        try:
            deployer = FoundryDeployer(config_path=temp_path)
            result = deployer.validate()

            assert not result["valid"]
            assert any("nonexistent_agent" in issue for issue in result["issues"])
        finally:
            temp_path.unlink()


class TestDeployNativeAgentCallsCreateVersion:
    """Tests for native agent deployment using AIProjectClient."""

    def test_deploy_native_agent_calls_create_version(self) -> None:
        """Verify deploy_agent calls agents.create_version for native agents."""
        deployer = FoundryDeployer()

        # Mock the AIProjectClient and its methods
        mock_agent = type(
            "MockAgent",
            (),
            {"id": "agent-123", "name": "transport", "version": "1.0.0"},
        )()

        with patch(
            "interoperability.foundry.deploy.FoundryDeployer._create_project_client"
        ) as mock_create_client:
            mock_client = type("MockClient", (), {})()
            mock_client.agents = type("MockAgents", (), {})()
            mock_client.agents.create_version = lambda **kwargs: mock_agent
            mock_create_client.return_value = mock_client

            # Set PROJECT_ENDPOINT and Bing connection for deployment
            with patch.dict(
                os.environ,
                {
                    "PROJECT_ENDPOINT": "https://test.endpoint",
                    "BING_PROJECT_CONNECTION_ID": "pc-123",
                },
            ):
                result = deployer.deploy_agent("transport", dry_run=False)

        assert result["success"] is True
        assert result["agent_id"] == "agent-123"
        assert result["agent_version"] == "1.0.0"
        assert "Successfully deployed" in result["message"]

    def test_deploy_native_agent_uses_extracted_instructions(self) -> None:
        """Verify deployment includes extracted instructions in payload."""
        deployer = FoundryDeployer()

        captured_definition = {}

        def capture_create_version(**kwargs):
            captured_definition.update(kwargs)
            return type(
                "MockAgent",
                (),
                {"id": "agent-456", "name": "transport", "version": "1.0.0"},
            )()

        with patch(
            "interoperability.foundry.deploy.FoundryDeployer._create_project_client"
        ) as mock_create_client:
            mock_client = type("MockClient", (), {})()
            mock_client.agents = type("MockAgents", (), {})()
            mock_client.agents.create_version = capture_create_version
            mock_create_client.return_value = mock_client

            with patch.dict(
                os.environ,
                {
                    "PROJECT_ENDPOINT": "https://test.endpoint",
                    "BING_PROJECT_CONNECTION_ID": "pc-123",
                },
            ):
                result = deployer.deploy_agent("transport", dry_run=False)

        assert result["success"] is True
        # Verify agent_name was passed
        assert captured_definition.get("agent_name") == "transport"
        # Verify definition was passed
        definition = captured_definition.get("definition")
        assert definition is not None
        assert getattr(definition, "instructions", None)
        tools = getattr(definition, "tools", [])
        assert tools
        # Bing grounding tool should include required parameters
        first_tool = tools[0]
        assert getattr(first_tool, "type", None) == "bing_grounding"
        assert getattr(first_tool, "bing_grounding", None)

    def test_deploy_native_agent_includes_tools(self) -> None:
        """Verify deployment includes extracted tools (bing_grounding)."""
        deployer = FoundryDeployer()

        # The transport agent should have tools extracted (bing_grounding)
        # This test verifies the deployment info includes tools
        result = deployer.deploy_agent("transport", dry_run=True)

        assert result["success"] is True
        deployment_info = result["deployment_info"]
        assert "extracted_tools" in deployment_info
        # Transport agent uses HostedWebSearchTool which maps to bing_grounding
        tools = deployment_info["extracted_tools"]
        assert len(tools) > 0

    def test_deploy_native_agent_handles_error(self) -> None:
        """Verify deployment errors are caught and reported with actionable messages."""
        deployer = FoundryDeployer()

        with patch(
            "interoperability.foundry.deploy.FoundryDeployer._create_project_client"
        ) as mock_create_client:
            # Simulate an Azure SDK error
            mock_create_client.side_effect = DeploymentError(
                "Failed to create AIProjectClient: Authentication failed"
            )

            with patch.dict(os.environ, {"PROJECT_ENDPOINT": "https://test.endpoint"}):
                with pytest.raises(DeploymentError) as exc_info:
                    deployer.deploy_agent("transport", dry_run=False)

            assert "Authentication failed" in str(exc_info.value)


class TestCreateProjectClient:
    """Tests for _create_project_client method."""

    def test_create_project_client_requires_endpoint(self) -> None:
        """Verify _create_project_client raises error when PROJECT_ENDPOINT not set."""
        deployer = FoundryDeployer()

        # Clear PROJECT_ENDPOINT
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(DeploymentError) as exc_info:
                deployer._create_project_client()

        assert "AZURE_AI_PROJECT_ENDPOINT" in str(exc_info.value)

    def test_create_project_client_with_valid_endpoint(self) -> None:
        """Verify _create_project_client attempts to create client with endpoint."""
        deployer = FoundryDeployer()

        # Mock the Azure SDK at the module level where it gets imported
        import sys

        mock_ai_projects = type(sys)("azure.ai.projects")
        mock_ai_projects.AIProjectClient = lambda **kwargs: type(
            "MockClient", (), {"endpoint": kwargs.get("endpoint")}
        )()

        mock_identity = type(sys)("azure.identity")
        mock_identity.DefaultAzureCredential = lambda: type("MockCred", (), {})()

        with patch.dict(
            os.environ,
            {"PROJECT_ENDPOINT": "https://test.services.ai.azure.com/api/projects/myproject"},
        ):
            with patch.dict(
                sys.modules,
                {
                    "azure.ai.projects": mock_ai_projects,
                    "azure.identity": mock_identity,
                },
            ):
                client = deployer._create_project_client()
                # Just verify we get something back
                assert client is not None


class TestDeployNativeAgentWithMockedSDK:
    """Tests for _deploy_native_agent with fully mocked SDK."""

    def test_deploy_native_agent_success(self) -> None:
        """Verify _deploy_native_agent returns correct result structure."""
        deployer = FoundryDeployer()
        agent = AgentDefinition(
            name="test_agent",
            agent_type="native",
            source="src/agents/test",
            model="gpt-4.1-mini",
        )

        # Create mock agent result
        mock_agent_result = type(
            "MockAgent",
            (),
            {"id": "id-789", "name": "test_agent", "version": "2.0.0"},
        )()

        # Mock at the method level since imports happen inside the method
        with patch.object(deployer, "_create_project_client") as mock_create:
            mock_client = type("MockClient", (), {})()
            mock_client.agents = type("MockAgents", (), {})()
            mock_client.agents.create_version = lambda **kwargs: mock_agent_result
            mock_create.return_value = mock_client
            with patch.dict(os.environ, {"BING_PROJECT_CONNECTION_ID": "pc-123"}):
                result = deployer._deploy_native_agent(
                    agent=agent,
                    instructions="You are a test agent.",
                    tools=[{"kind": "bing_grounding"}],
                )

        assert result["agent_id"] == "id-789"
        assert result["agent_name"] == "test_agent"
        assert result["agent_version"] == "2.0.0"

    def test_deploy_native_agent_sdk_error(self) -> None:
        """Verify _deploy_native_agent wraps SDK errors in DeploymentError."""
        deployer = FoundryDeployer()
        agent = AgentDefinition(
            name="test_agent",
            agent_type="native",
            source="src/agents/test",
            model="gpt-4.1-mini",
        )

        def raise_error(**kwargs):
            raise Exception("Azure SDK error")

        with patch.object(deployer, "_create_project_client") as mock_create:
            mock_client = type("MockClient", (), {})()
            mock_client.agents = type("MockAgents", (), {})()
            mock_client.agents.create_version = raise_error
            mock_create.return_value = mock_client
            with pytest.raises(DeploymentError) as exc_info:
                deployer._deploy_native_agent(
                    agent=agent,
                    instructions="You are a test agent.",
                    tools=[],
                )

        assert "Azure SDK error" in str(exc_info.value)
        assert "test_agent" in str(exc_info.value)


class TestWorkflowEnvVarsValidation:
    """Tests for workflow environment variable validation (INTEROP-011.4)."""

    def test_workflow_env_vars_parsed(self) -> None:
        """Verify env_vars are parsed from workflow definitions."""
        deployer = FoundryDeployer()
        config = deployer.config

        procode = config.workflows["discovery_procode"]
        assert len(procode.env_vars) > 0
        assert "AZURE_AI_PROJECT_ENDPOINT" in procode.env_vars
        assert "COPILOTSTUDIOAGENT__TENANTID" in procode.env_vars

    def test_workflow_env_vars_missing(self) -> None:
        """Verify workflow reports missing env vars."""
        deployer = FoundryDeployer()
        config = deployer.config

        procode = config.workflows["discovery_procode"]

        with patch.dict(os.environ, {}, clear=True):
            missing = deployer._validate_workflow_env_vars(procode)
            assert len(missing) == len(procode.env_vars)
            assert "AZURE_AI_PROJECT_ENDPOINT" in missing

    def test_workflow_env_vars_set(self) -> None:
        """Verify workflow passes when env vars are set."""
        deployer = FoundryDeployer()
        config = deployer.config

        procode = config.workflows["discovery_procode"]

        env_vars = {var: "test-value" for var in procode.env_vars}
        with patch.dict(os.environ, env_vars, clear=False):
            missing = deployer._validate_workflow_env_vars(procode)
            assert len(missing) == 0

    def test_validate_warns_missing_workflow_env_vars(self) -> None:
        """Verify validate() reports missing workflow env vars as warnings."""
        deployer = FoundryDeployer()

        with patch.dict(os.environ, {}, clear=True):
            result = deployer.validate()
            # Should have warnings about missing env vars for workflows
            workflow_warnings = [
                w for w in result["warnings"] if "discovery_procode" in w
            ]
            assert len(workflow_warnings) > 0

    def test_workflow_deploy_fails_missing_env_vars(self) -> None:
        """Verify deploy_workflow fails when required env vars missing."""
        deployer = FoundryDeployer()

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(DeploymentError) as exc_info:
                deployer.deploy_workflow("discovery_procode", dry_run=False)
            assert "missing env vars" in str(exc_info.value).lower()

    def test_workflow_env_vars_empty_list(self) -> None:
        """Verify workflows with no env_vars have empty list."""
        deployer = FoundryDeployer()
        config = deployer.config

        declarative = config.workflows["discovery_declarative"]
        assert declarative.env_vars == []


class TestWorkflowDeploymentFiles:
    """Tests for workflow deployment files (INTEROP-011.4)."""

    def test_dockerfile_exists(self) -> None:
        """Verify Dockerfile exists for discovery_procode workflow."""
        dockerfile_path = (
            Path(__file__).resolve().parents[4]
            / "interoperability"
            / "foundry"
            / "workflows"
            / "discovery_workflow_procode"
            / "Dockerfile"
        )
        assert dockerfile_path.exists(), f"Dockerfile not found at {dockerfile_path}"

    def test_dockerfile_base_image(self) -> None:
        """Verify Dockerfile uses python:3.11-slim base image."""
        dockerfile_path = (
            Path(__file__).resolve().parents[4]
            / "interoperability"
            / "foundry"
            / "workflows"
            / "discovery_workflow_procode"
            / "Dockerfile"
        )
        content = dockerfile_path.read_text()
        assert "FROM python:3.11-slim" in content

    def test_dockerfile_exposes_port(self) -> None:
        """Verify Dockerfile exposes agent server port."""
        dockerfile_path = (
            Path(__file__).resolve().parents[4]
            / "interoperability"
            / "foundry"
            / "workflows"
            / "discovery_workflow_procode"
            / "Dockerfile"
        )
        content = dockerfile_path.read_text()
        assert "EXPOSE 8088" in content

    def test_dockerfile_copies_src(self) -> None:
        """Verify Dockerfile copies src/ for shared models access."""
        dockerfile_path = (
            Path(__file__).resolve().parents[4]
            / "interoperability"
            / "foundry"
            / "workflows"
            / "discovery_workflow_procode"
            / "Dockerfile"
        )
        content = dockerfile_path.read_text()
        assert "COPY src/" in content

    def test_requirements_exists(self) -> None:
        """Verify requirements.txt exists for discovery_procode workflow."""
        req_path = (
            Path(__file__).resolve().parents[4]
            / "interoperability"
            / "foundry"
            / "workflows"
            / "discovery_workflow_procode"
            / "requirements.txt"
        )
        assert req_path.exists(), f"requirements.txt not found at {req_path}"

    def test_requirements_includes_agent_framework(self) -> None:
        """Verify requirements.txt includes azure-ai-agentserver-core."""
        req_path = (
            Path(__file__).resolve().parents[4]
            / "interoperability"
            / "foundry"
            / "workflows"
            / "discovery_workflow_procode"
            / "requirements.txt"
        )
        content = req_path.read_text()
        assert "azure-ai-agentserver-core" in content

    def test_requirements_includes_m365_sdk(self) -> None:
        """Verify requirements.txt includes microsoft-agents-copilotstudio-client."""
        req_path = (
            Path(__file__).resolve().parents[4]
            / "interoperability"
            / "foundry"
            / "workflows"
            / "discovery_workflow_procode"
            / "requirements.txt"
        )
        content = req_path.read_text()
        assert "microsoft-agents-copilotstudio-client" in content

    def test_requirements_includes_azure_identity(self) -> None:
        """Verify requirements.txt includes azure-identity."""
        req_path = (
            Path(__file__).resolve().parents[4]
            / "interoperability"
            / "foundry"
            / "workflows"
            / "discovery_workflow_procode"
            / "requirements.txt"
        )
        content = req_path.read_text()
        assert "azure-identity" in content

    def test_requirements_includes_ai_projects(self) -> None:
        """Verify requirements.txt includes azure-ai-projects."""
        req_path = (
            Path(__file__).resolve().parents[4]
            / "interoperability"
            / "foundry"
            / "workflows"
            / "discovery_workflow_procode"
            / "requirements.txt"
        )
        content = req_path.read_text()
        assert "azure-ai-projects" in content


class TestWorkflowDeployment:
    """Tests for workflow deployment via deploy.py (INTEROP-011.4)."""

    def test_config_includes_procode_workflow(self) -> None:
        """Verify config.yaml includes discovery_procode workflow."""
        deployer = FoundryDeployer()
        config = deployer.config

        assert "discovery_procode" in config.workflows
        procode = config.workflows["discovery_procode"]
        assert procode.workflow_type == "hosted_workflow"

    def test_config_procode_has_env_vars_mapping(self) -> None:
        """Verify discovery_procode workflow has COPILOTSTUDIOAGENT__* env vars."""
        deployer = FoundryDeployer()
        config = deployer.config

        procode = config.workflows["discovery_procode"]
        cs_vars = [v for v in procode.env_vars if v.startswith("COPILOTSTUDIOAGENT__")]
        assert len(cs_vars) >= 4  # At least tenant, env, app, secret

    def test_deploy_workflow_dry_run(self) -> None:
        """Verify deploy_workflow --dry-run shows workflow details."""
        deployer = FoundryDeployer()

        result = deployer.deploy_workflow("discovery_procode", dry_run=True)

        assert result["success"] is True
        assert "DRY RUN" in result["message"]
        assert "deployment_info" in result
        info = result["deployment_info"]
        assert info["type"] == "hosted_workflow"
        assert info["env_vars"]

    def test_deploy_workflow_dry_run_shows_missing_files(self) -> None:
        """Verify dry-run reports file status for hosted workflows."""
        deployer = FoundryDeployer()

        result = deployer.deploy_workflow("discovery_procode", dry_run=True)

        assert "deployment_info" in result
        info = result["deployment_info"]
        assert "workflow_info" in info
        wf_info = info["workflow_info"]
        assert "existing_files" in wf_info
        assert "Dockerfile" in wf_info["existing_files"]
        assert "requirements.txt" in wf_info["existing_files"]

    def test_deploy_workflow_declarative_dry_run(self) -> None:
        """Verify declarative workflow dry-run works."""
        deployer = FoundryDeployer()

        result = deployer.deploy_workflow("discovery_declarative", dry_run=True)

        assert result["success"] is True
        assert "DRY RUN" in result["message"]

    def test_deploy_workflow_not_found(self) -> None:
        """Verify deploy_workflow raises error for unknown workflow."""
        deployer = FoundryDeployer()

        with pytest.raises(DeploymentError) as exc_info:
            deployer.deploy_workflow("nonexistent_workflow", dry_run=True)
        assert "not found" in str(exc_info.value)

    def test_deploy_script_includes_workflow(self) -> None:
        """Verify deploy.py --dry-run includes discovery_procode in output."""
        deployer = FoundryDeployer()

        results = deployer.deploy_all(dry_run=True)

        assert "discovery_procode" in results["workflows"]
        procode_result = results["workflows"]["discovery_procode"]
        assert procode_result["success"] is True

    def test_deploy_workflow_env_var_definition(self) -> None:
        """Verify WorkflowDefinition supports env_vars field."""
        wf = WorkflowDefinition(
            name="test",
            workflow_type="hosted_workflow",
            source="path/to/workflow",
            env_vars=["VAR1", "VAR2"],
        )
        assert wf.env_vars == ["VAR1", "VAR2"]

    def test_deploy_workflow_env_var_default_empty(self) -> None:
        """Verify WorkflowDefinition env_vars defaults to empty list."""
        wf = WorkflowDefinition(
            name="test",
            workflow_type="declarative",
            source="path/to/workflow",
        )
        assert wf.env_vars == []
