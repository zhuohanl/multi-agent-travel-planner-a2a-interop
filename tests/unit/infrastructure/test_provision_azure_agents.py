"""
Unit tests for scripts/provision_azure_agents.py

Tests the agent provisioning script with mocked Azure AI client.
"""

import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

# Import the module under test
sys.path.insert(0, "scripts")
from scripts.provision_azure_agents import (
    AGENT_CONFIGS,
    AGENT_TYPES,
    CLASSIFICATION_TOOLS,
    CLASSIFIER_SYSTEM_PROMPT,
    PLAN_MODIFICATION_TOOL,
    PLANNER_SYSTEM_PROMPT,
    QA_SYSTEM_PROMPT,
    QA_TOOLS,
    ROUTER_SYSTEM_PROMPT,
    ROUTING_TOOLS,
    AgentConfig,
    main,
    parse_args,
    print_env_exports,
    provision_agent,
    provision_all_agents,
    validate_endpoint,
)


class TestAgentConfigurations:
    """Tests for agent configuration definitions."""

    def test_agent_types_has_four_agents(self) -> None:
        """Verify we have exactly 4 agent types defined."""
        assert len(AGENT_TYPES) == 4
        assert "router" in AGENT_TYPES
        assert "classifier" in AGENT_TYPES
        assert "planner" in AGENT_TYPES
        assert "qa" in AGENT_TYPES

    def test_agent_configs_match_agent_types(self) -> None:
        """Verify AGENT_CONFIGS matches AGENT_TYPES."""
        assert set(AGENT_CONFIGS.keys()) == set(AGENT_TYPES.keys())

    def test_router_has_five_tools(self) -> None:
        """Router agent should have 5 tools for routing decisions."""
        assert len(ROUTING_TOOLS) == 5
        tool_names = [t["function"]["name"] for t in ROUTING_TOOLS]
        assert "workflow_turn" in tool_names
        assert "answer_question" in tool_names
        assert "currency_convert" in tool_names
        assert "weather_lookup" in tool_names
        assert "timezone_info" in tool_names

    def test_classifier_has_one_tool(self) -> None:
        """Classifier agent should have 1 tool for action classification."""
        assert len(CLASSIFICATION_TOOLS) == 1
        assert CLASSIFICATION_TOOLS[0]["function"]["name"] == "classify_action"

    def test_planner_has_one_tool(self) -> None:
        """Planner agent should have 1 tool for modification planning."""
        assert PLAN_MODIFICATION_TOOL["function"]["name"] == "plan_modification"

    def test_qa_has_no_tools(self) -> None:
        """QA agent should have no tools (text generation only)."""
        assert QA_TOOLS == []

    def test_all_agents_have_system_prompts(self) -> None:
        """All agents should have non-empty system prompts."""
        assert len(ROUTER_SYSTEM_PROMPT) > 100
        assert len(CLASSIFIER_SYSTEM_PROMPT) > 100
        assert len(PLANNER_SYSTEM_PROMPT) > 100
        assert len(QA_SYSTEM_PROMPT) > 100

    def test_agent_config_has_env_var(self) -> None:
        """Each agent config should have the correct env var name."""
        assert AGENT_CONFIGS["router"].env_var == "ORCHESTRATOR_ROUTING_AGENT_ID"
        assert AGENT_CONFIGS["classifier"].env_var == "ORCHESTRATOR_CLASSIFIER_AGENT_ID"
        assert AGENT_CONFIGS["planner"].env_var == "ORCHESTRATOR_PLANNER_AGENT_ID"
        assert AGENT_CONFIGS["qa"].env_var == "ORCHESTRATOR_QA_AGENT_ID"


class TestValidateEndpoint:
    """Tests for endpoint URL validation."""

    def test_valid_endpoint(self) -> None:
        """Valid endpoint URL should parse correctly."""
        endpoint = "https://my-resource.services.ai.azure.com/api/projects/my-project"
        result = validate_endpoint(endpoint)

        assert result["resource_name"] == "my-resource"
        assert result["project_name"] == "my-project"

    def test_invalid_endpoint_wrong_format(self) -> None:
        """Invalid endpoint format should raise."""
        with pytest.raises(ValueError, match="Invalid endpoint format"):
            validate_endpoint("invalid-endpoint")

    def test_invalid_endpoint_wrong_domain(self) -> None:
        """Invalid endpoint with wrong domain should raise."""
        with pytest.raises(ValueError, match="Invalid endpoint format"):
            validate_endpoint("https://my-resource.azure.com/api/projects/my-project")

    def test_empty_endpoint(self) -> None:
        """Empty endpoint should raise."""
        with pytest.raises(ValueError, match="Invalid endpoint format"):
            validate_endpoint("")


class TestProvisionAgent:
    """Tests for single agent provisioning."""

    def test_provision_agent_dry_run(self) -> None:
        """Dry-run should return None without calling client."""
        config = AgentConfig(
            name="test-agent",
            instructions="Test instructions",
            tools=[],
            env_var="TEST_AGENT_ID",
        )

        result = provision_agent(
            client=None,  # type: ignore
            config=config,
            deployment_name="gpt-4.1",
            dry_run=True,
        )

        assert result is None

    @patch("scripts.provision_azure_agents._get_azure_agents_imports")
    def test_provision_agent_with_tools(self, mock_imports: MagicMock) -> None:
        """Agent with tools should pass tools to create."""
        # Mock Azure imports
        mock_function_tool_def = MagicMock()
        mock_function_def = MagicMock()
        mock_imports.return_value = (None, None, mock_function_tool_def, mock_function_def)

        mock_client = MagicMock()
        mock_agent = MagicMock()
        mock_agent.id = "asst_test123"
        mock_client.create_agent.return_value = mock_agent

        config = AgentConfig(
            name="test-agent",
            instructions="Test instructions",
            tools=[{"type": "function", "function": {"name": "test_tool", "description": "A test tool", "parameters": {}}}],
            env_var="TEST_AGENT_ID",
        )

        result = provision_agent(
            client=mock_client,
            config=config,
            deployment_name="gpt-4.1",
            dry_run=False,
        )

        assert result == "asst_test123"
        mock_client.create_agent.assert_called_once()
        call_kwargs = mock_client.create_agent.call_args[1]
        assert call_kwargs["name"] == "test-agent"
        assert call_kwargs["model"] == "gpt-4.1"
        assert call_kwargs["instructions"] == "Test instructions"

    @patch("scripts.provision_azure_agents._get_azure_agents_imports")
    def test_provision_agent_without_tools(self, mock_imports: MagicMock) -> None:
        """Agent without tools (QA) should pass None for tools."""
        # Mock Azure imports
        mock_function_tool_def = MagicMock()
        mock_function_def = MagicMock()
        mock_imports.return_value = (None, None, mock_function_tool_def, mock_function_def)

        mock_client = MagicMock()
        mock_agent = MagicMock()
        mock_agent.id = "asst_qa123"
        mock_client.create_agent.return_value = mock_agent

        config = AgentConfig(
            name="qa-agent",
            instructions="QA instructions",
            tools=[],  # No tools
            env_var="QA_AGENT_ID",
        )

        result = provision_agent(
            client=mock_client,
            config=config,
            deployment_name="gpt-4.1",
            dry_run=False,
        )

        assert result == "asst_qa123"
        mock_client.create_agent.assert_called_once()
        call_kwargs = mock_client.create_agent.call_args[1]
        assert call_kwargs["tools"] is None


class TestProvisionAllAgents:
    """Tests for provisioning all agents."""

    @patch("scripts.provision_azure_agents._get_azure_agents_imports")
    @patch("scripts.provision_azure_agents.create_agents_client")
    def test_provision_all_agents_creates_four_agents(
        self, mock_create_client: MagicMock, mock_imports: MagicMock
    ) -> None:
        """Should create all 4 agents and return their IDs."""
        # Mock Azure imports
        mock_function_tool_def = MagicMock()
        mock_function_def = MagicMock()
        mock_imports.return_value = (None, None, mock_function_tool_def, mock_function_def)

        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        # Each call returns a unique agent ID
        agent_ids = ["asst_router", "asst_classifier", "asst_planner", "asst_qa"]
        mock_agents = [MagicMock(id=aid) for aid in agent_ids]
        mock_client.create_agent.side_effect = mock_agents

        results = provision_all_agents(
            endpoint="https://my-resource.services.ai.azure.com/api/projects/my-project",
            deployment_name="gpt-4.1",
            dry_run=False,
        )

        # Should have 4 results
        assert len(results) == 4
        assert "router" in results
        assert "classifier" in results
        assert "planner" in results
        assert "qa" in results

        # Should have called create 4 times
        assert mock_client.create_agent.call_count == 4

    def test_provision_all_agents_dry_run(self) -> None:
        """Dry-run should validate without creating agents."""
        results = provision_all_agents(
            endpoint="https://my-resource.services.ai.azure.com/api/projects/my-project",
            deployment_name="gpt-4.1",
            dry_run=True,
        )

        # All results should be None (no agents created)
        assert len(results) == 4
        assert all(v is None for v in results.values())

    def test_provision_all_agents_invalid_endpoint(self) -> None:
        """Invalid endpoint should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid endpoint format"):
            provision_all_agents(
                endpoint="invalid",
                deployment_name="gpt-4.1",
                dry_run=False,
            )


class TestPrintEnvExports:
    """Tests for environment variable output."""

    def test_print_env_exports_with_ids(self, capsys: pytest.CaptureFixture) -> None:
        """Should print env var export lines with agent IDs."""
        results = {
            "router": "asst_router123",
            "classifier": "asst_classifier456",
            "planner": "asst_planner789",
            "qa": "asst_qa012",
        }

        print_env_exports(results)

        captured = capsys.readouterr()
        assert 'ORCHESTRATOR_ROUTING_AGENT_ID="asst_router123"' in captured.out
        assert 'ORCHESTRATOR_CLASSIFIER_AGENT_ID="asst_classifier456"' in captured.out
        assert 'ORCHESTRATOR_PLANNER_AGENT_ID="asst_planner789"' in captured.out
        assert 'ORCHESTRATOR_QA_AGENT_ID="asst_qa012"' in captured.out

    def test_print_env_exports_dry_run(self, capsys: pytest.CaptureFixture) -> None:
        """Dry-run should print empty values with comment."""
        results = {
            "router": None,
            "classifier": None,
            "planner": None,
            "qa": None,
        }

        print_env_exports(results)

        captured = capsys.readouterr()
        assert "dry-run" in captured.out.lower()


class TestParseArgs:
    """Tests for command-line argument parsing."""

    def test_parse_args_defaults(self) -> None:
        """Default args should have no endpoint or deployment."""
        with patch("sys.argv", ["provision_azure_agents.py"]):
            args = parse_args()

        assert args.endpoint is None
        assert args.deployment_name is None
        assert args.dry_run is False
        assert args.verbose is False

    def test_parse_args_with_options(self) -> None:
        """Should parse all command-line options."""
        with patch(
            "sys.argv",
            [
                "provision_azure_agents.py",
                "--endpoint",
                "https://test.services.ai.azure.com/api/projects/test",
                "--deployment-name",
                "gpt-4.1",
                "--dry-run",
                "-v",
            ],
        ):
            args = parse_args()

        assert args.endpoint == "https://test.services.ai.azure.com/api/projects/test"
        assert args.deployment_name == "gpt-4.1"
        assert args.dry_run is True
        assert args.verbose is True


class TestMain:
    """Tests for main entry point."""

    def test_main_missing_endpoint(self) -> None:
        """Should return 1 if endpoint is missing."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("sys.argv", ["provision_azure_agents.py"]):
                result = main()

        assert result == 1

    def test_main_missing_deployment_name(self) -> None:
        """Should return 1 if deployment name is missing."""
        with patch.dict(
            "os.environ",
            {"PROJECT_ENDPOINT": "https://test.services.ai.azure.com/api/projects/test"},
            clear=True,
        ):
            with patch("sys.argv", ["provision_azure_agents.py"]):
                result = main()

        assert result == 1

    @patch("scripts.provision_azure_agents.provision_all_agents")
    def test_main_dry_run_success(
        self, mock_provision: MagicMock
    ) -> None:
        """Dry-run should succeed with valid config."""
        mock_provision.return_value = {
            "router": None,
            "classifier": None,
            "planner": None,
            "qa": None,
        }

        with patch.dict(
            "os.environ",
            {
                "PROJECT_ENDPOINT": "https://test.services.ai.azure.com/api/projects/test",
                "AZURE_OPENAI_DEPLOYMENT_NAME": "gpt-4.1",
            },
            clear=True,
        ):
            with patch("sys.argv", ["provision_azure_agents.py", "--dry-run"]):
                result = main()

        assert result == 0
        mock_provision.assert_called_once()
        assert mock_provision.call_args[1]["dry_run"] is True

    @patch("scripts.provision_azure_agents.provision_all_agents")
    def test_main_outputs_env_vars(
        self, mock_provision: MagicMock, capsys: pytest.CaptureFixture
    ) -> None:
        """Should output environment variable lines on success."""
        mock_provision.return_value = {
            "router": "asst_router",
            "classifier": "asst_classifier",
            "planner": "asst_planner",
            "qa": "asst_qa",
        }

        with patch.dict(
            "os.environ",
            {
                "PROJECT_ENDPOINT": "https://test.services.ai.azure.com/api/projects/test",
                "AZURE_OPENAI_DEPLOYMENT_NAME": "gpt-4.1",
            },
            clear=True,
        ):
            with patch("sys.argv", ["provision_azure_agents.py"]):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "ORCHESTRATOR_ROUTING_AGENT_ID" in captured.out

    @patch("scripts.provision_azure_agents.provision_all_agents")
    def test_main_requires_endpoint_arg(
        self, mock_provision: MagicMock
    ) -> None:
        """Should use --endpoint arg over env var."""
        mock_provision.return_value = {
            "router": None,
            "classifier": None,
            "planner": None,
            "qa": None,
        }

        with patch.dict(
            "os.environ",
            {"AZURE_OPENAI_DEPLOYMENT_NAME": "gpt-4.1"},
            clear=True,
        ):
            with patch(
                "sys.argv",
                [
                    "provision_azure_agents.py",
                    "--endpoint",
                    "https://test.services.ai.azure.com/api/projects/test",
                    "--dry-run",
                ],
            ):
                result = main()

        assert result == 0
        assert mock_provision.call_args[1]["endpoint"] == "https://test.services.ai.azure.com/api/projects/test"


class TestToolDefinitions:
    """Tests for tool definitions match design doc requirements."""

    def test_workflow_turn_tool_has_message_param(self) -> None:
        """workflow_turn tool should have message parameter."""
        wt_tool = next(t for t in ROUTING_TOOLS if t["function"]["name"] == "workflow_turn")
        params = wt_tool["function"]["parameters"]["properties"]
        assert "message" in params
        assert params["message"]["type"] == "string"

    def test_answer_question_tool_has_domain_enum(self) -> None:
        """answer_question tool should have domain enum with 7 values."""
        aq_tool = next(t for t in ROUTING_TOOLS if t["function"]["name"] == "answer_question")
        params = aq_tool["function"]["parameters"]["properties"]
        assert "domain" in params
        domain_enum = params["domain"]["enum"]
        assert "general" in domain_enum
        assert "budget" in domain_enum
        assert len(domain_enum) == 7

    def test_classify_action_tool_has_action_enum(self) -> None:
        """classify_action tool should have action enum with 8 values."""
        ca_tool = CLASSIFICATION_TOOLS[0]
        params = ca_tool["function"]["parameters"]["properties"]
        action_enum = params["action"]["enum"]
        assert "APPROVE_TRIP_SPEC" in action_enum
        assert "MODIFY_ITINERARY" in action_enum
        assert "START_BOOKING" in action_enum
        assert len(action_enum) == 8

    def test_plan_modification_tool_has_agents_enum(self) -> None:
        """plan_modification tool should have agents enum with 5 values."""
        pm_tool = PLAN_MODIFICATION_TOOL
        params = pm_tool["function"]["parameters"]["properties"]
        agents_items = params["agents"]["items"]
        agents_enum = agents_items["enum"]
        assert "transport" in agents_enum
        assert "stay" in agents_enum
        assert "poi" in agents_enum
        assert "events" in agents_enum
        assert "dining" in agents_enum
        assert len(agents_enum) == 5

    def test_plan_modification_tool_has_strategy_enum(self) -> None:
        """plan_modification tool should have strategy enum."""
        pm_tool = PLAN_MODIFICATION_TOOL
        params = pm_tool["function"]["parameters"]["properties"]
        strategy_enum = params["strategy"]["enum"]
        assert "replace" in strategy_enum
        assert "add" in strategy_enum
        assert "remove" in strategy_enum
