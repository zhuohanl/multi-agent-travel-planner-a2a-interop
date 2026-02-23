"""Unit tests for copilot_studio/verify.py verification script.

Tests the verification checks:
1. Agent reachability (mocked)
2. Agent not found detection
3. Authentication configuration
4. Status report output
"""

from pathlib import Path

import pytest

from interoperability.copilot_studio.verify import (
    AgentConfig,
    CheckResult,
    CheckStatus,
    CopilotStudioVerifier,
    VerificationConfig,
    print_results,
)


@pytest.fixture
def temp_config_dir(tmp_path: Path) -> Path:
    """Create temporary config directory with test configs."""
    # Create config.yaml
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
platform: copilot_studio
environment_id: test-env-id

agents:
  weather:
    name: Weather Agent
    description: Provides weather forecasts
    topics:
      - get_weather_forecast
  approval:
    name: Approval Agent
    description: Human approval for itineraries
    agent_id: ${COPILOTSTUDIOAGENT__APPROVAL__AGENTID}
    schema_name: ${COPILOTSTUDIOAGENT__APPROVAL__SCHEMANAME}
    topics:
      - request_approval
      - get_approval_status
  travel_planning_parent:
    name: Q&A Parent Agent
    description: Routes questions to discovery agents
    connected_agents:
      - transport
      - poi
      - events
      - stay
      - dining
""")

    return tmp_path


@pytest.fixture
def minimal_config_dir(tmp_path: Path) -> Path:
    """Create config directory with only weather agent."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
platform: copilot_studio

agents:
  weather:
    name: Weather Agent
""")

    return tmp_path


@pytest.fixture
def empty_config_dir(tmp_path: Path) -> Path:
    """Create config directory with empty config."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
platform: copilot_studio
""")

    return tmp_path


class TestAgentReachable:
    """Tests for agent reachability verification."""

    def test_verify_agent_reachable(self, temp_config_dir: Path) -> None:
        """Verify that reachable agents are detected correctly with mock responses."""
        mock_responses = {
            "weather": {"status": "ok", "reachable": True},
            "approval": {"status": "ok", "reachable": True},
            "travel_planning_parent": {"status": "ok", "reachable": True},
        }

        verifier = CopilotStudioVerifier(
            offline=False,
            config_path=temp_config_dir / "config.yaml",
            mock_responses=mock_responses,
        )

        result = verifier.check_agents_reachable()

        assert result.status == CheckStatus.PASS
        assert "3" in result.message
        assert "reachable" in result.message.lower()

    def test_verify_single_agent_reachable(self, temp_config_dir: Path) -> None:
        """Verify that single agent reachability check works with mock."""
        mock_responses = {
            "weather": {"status": "ok", "reachable": True},
        }

        verifier = CopilotStudioVerifier(
            offline=False,
            config_path=temp_config_dir / "config.yaml",
            mock_responses=mock_responses,
        )

        result = verifier.check_agent_reachable("weather")

        assert result.status == CheckStatus.PASS
        assert "reachable" in result.message.lower()


class TestAgentNotFound:
    """Tests for agent not found detection."""

    def test_verify_agent_not_found(self, temp_config_dir: Path) -> None:
        """Verify that unreachable agents are detected correctly."""
        mock_responses = {
            "weather": {"status": "error", "reachable": False, "error": "Agent not found"},
            "approval": {"status": "ok", "reachable": True},
            "travel_planning_parent": {"status": "ok", "reachable": True},
        }

        verifier = CopilotStudioVerifier(
            offline=False,
            config_path=temp_config_dir / "config.yaml",
            mock_responses=mock_responses,
        )

        result = verifier.check_agents_reachable()

        assert result.status == CheckStatus.FAIL
        assert "not reachable" in result.message.lower()

    def test_verify_agent_not_in_config(self, temp_config_dir: Path) -> None:
        """Verify that checking non-existent agent returns error."""
        verifier = CopilotStudioVerifier(
            offline=False,
            config_path=temp_config_dir / "config.yaml",
        )

        result = verifier.check_agent_reachable("nonexistent_agent")

        assert result.status == CheckStatus.FAIL
        assert "not defined" in result.message.lower()

    def test_verify_missing_agent_definitions(self, minimal_config_dir: Path) -> None:
        """Verify that missing required agents are detected."""
        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=minimal_config_dir / "config.yaml",
        )

        result = verifier.check_agents_defined()

        assert result.status == CheckStatus.WARN
        assert "approval" in result.message
        assert "travel_planning_parent" in result.message


class TestAuthConfigured:
    """Tests for authentication configuration verification."""

    def test_verify_auth_configured_passes(
        self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that complete auth config passes."""
        monkeypatch.setenv("COPILOTSTUDIOAGENT__TENANTID", "test-tenant-123")
        monkeypatch.setenv("COPILOTSTUDIOAGENT__AGENTAPPID", "test-app-123")
        monkeypatch.setenv("COPILOTSTUDIOAGENT__AGENTAPPSECRET", "test-secret")
        monkeypatch.setenv("COPILOTSTUDIOAGENT__ENVIRONMENTID", "test-env-123")

        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        result = verifier.check_auth_configured()

        assert result.status == CheckStatus.PASS
        assert "properly configured" in result.message.lower()

    def test_verify_auth_configured_fails_missing_tenant(
        self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that missing tenant ID is detected."""
        monkeypatch.delenv("COPILOTSTUDIOAGENT__TENANTID", raising=False)
        monkeypatch.setenv("COPILOTSTUDIOAGENT__AGENTAPPID", "test-app-123")
        monkeypatch.setenv("COPILOTSTUDIOAGENT__AGENTAPPSECRET", "test-secret")
        monkeypatch.setenv("COPILOTSTUDIOAGENT__ENVIRONMENTID", "test-env-123")

        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        result = verifier.check_auth_configured()

        assert result.status == CheckStatus.FAIL
        assert "tenant" in result.message.lower() or "issue" in result.message.lower()

    def test_verify_auth_configured_keyvault_reference(
        self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that Key Vault references are recognized."""
        monkeypatch.setenv("COPILOTSTUDIOAGENT__TENANTID", "test-tenant-123")
        monkeypatch.setenv("COPILOTSTUDIOAGENT__AGENTAPPID", "test-app-123")
        monkeypatch.setenv(
            "COPILOTSTUDIOAGENT__AGENTAPPSECRET",
            "@Microsoft.KeyVault(SecretUri=https://vault.vault.azure.net/secrets/test)"
        )
        monkeypatch.setenv("COPILOTSTUDIOAGENT__ENVIRONMENTID", "test-env-123")

        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        result = verifier.check_auth_configured()

        assert result.status == CheckStatus.PASS
        assert any("key vault" in d.lower() for d in result.details)


class TestOutputsStatusReport:
    """Tests for status report output."""

    def test_verify_outputs_status_report(self, capsys: pytest.CaptureFixture) -> None:
        """Verify that print_results outputs a status report."""
        results = [
            CheckResult(
                name="Test Check 1",
                status=CheckStatus.PASS,
                message="Check passed",
            ),
            CheckResult(
                name="Test Check 2",
                status=CheckStatus.FAIL,
                message="Check failed",
                remediation="Fix the issue",
            ),
        ]

        print_results(results, verbose=False)
        captured = capsys.readouterr()

        assert "Summary:" in captured.out
        assert "1 passed" in captured.out
        assert "1 failed" in captured.out

    def test_verify_outputs_remediation_on_failure(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """Verify that remediation is shown for failures."""
        results = [
            CheckResult(
                name="Test Check",
                status=CheckStatus.FAIL,
                message="Test failed",
                remediation="Do this to fix the issue",
            ),
        ]

        print_results(results, verbose=False)
        captured = capsys.readouterr()

        assert "Remediation:" in captured.out
        assert "Do this to fix" in captured.out

    def test_verify_outputs_details_in_verbose(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """Verify that details are shown in verbose mode."""
        results = [
            CheckResult(
                name="Test Check",
                status=CheckStatus.PASS,
                message="Test passed",
                details=["Detail 1", "Detail 2"],
            ),
        ]

        print_results(results, verbose=True)
        captured = capsys.readouterr()

        assert "Details:" in captured.out
        assert "Detail 1" in captured.out
        assert "Detail 2" in captured.out


class TestConfigLoading:
    """Tests for configuration loading."""

    def test_load_agents_from_config(self, temp_config_dir: Path) -> None:
        """Verify that agents are loaded from config.yaml."""
        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        config = verifier.config
        assert "weather" in config.agents
        assert "approval" in config.agents
        assert "travel_planning_parent" in config.agents
        assert config.agents["weather"].display_name == "Weather Agent"

    def test_load_topics_from_config(self, temp_config_dir: Path) -> None:
        """Verify that topics are loaded from config.yaml."""
        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        config = verifier.config
        assert "get_weather_forecast" in config.agents["weather"].topics
        assert "request_approval" in config.agents["approval"].topics

    def test_load_connected_agents_from_config(self, temp_config_dir: Path) -> None:
        """Verify that connected agents are loaded for travel_planning_parent."""
        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        config = verifier.config
        travel_planning_parent = config.agents["travel_planning_parent"]
        assert "transport" in travel_planning_parent.connected_agents
        assert "poi" in travel_planning_parent.connected_agents
        assert "dining" in travel_planning_parent.connected_agents

    def test_config_not_found(self, tmp_path: Path) -> None:
        """Verify behavior when config file doesn't exist."""
        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=tmp_path / "nonexistent.yaml",
        )

        result = verifier.check_config_exists()

        assert result.status == CheckStatus.FAIL
        assert "not found" in result.message.lower()

    def test_empty_config(self, empty_config_dir: Path) -> None:
        """Verify behavior when config has no agents section."""
        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=empty_config_dir / "config.yaml",
        )

        result = verifier.check_config_exists()

        assert result.status == CheckStatus.WARN
        assert "agents" in result.message.lower()


class TestEnvironmentVariables:
    """Tests for environment variable checks."""

    def test_verify_env_vars_pass(
        self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that all env vars set results in PASS."""
        env_vars = {
            "COPILOTSTUDIOAGENT__TENANTID": "test-tenant",
            "COPILOTSTUDIOAGENT__AGENTAPPID": "test-app-id",
            "COPILOTSTUDIOAGENT__ENVIRONMENTID": "test-env",
            "COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME": "weather-schema",
            "COPILOTSTUDIOAGENT__APPROVAL__SCHEMANAME": "approval-schema",
            "COPILOTSTUDIOAGENT__TRAVEL_PLANNING_PARENT__SCHEMANAME": "travel-planning-parent-schema",
        }
        for var, value in env_vars.items():
            monkeypatch.setenv(var, value)

        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        result = verifier.check_environment_variables()

        assert result.status == CheckStatus.PASS

    def test_verify_env_vars_missing(
        self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that missing env vars are reported."""
        # Clear all relevant env vars
        for var in [
            "COPILOTSTUDIOAGENT__TENANTID",
            "COPILOTSTUDIOAGENT__AGENTAPPID",
            "COPILOTSTUDIOAGENT__ENVIRONMENTID",
            "COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME",
            "COPILOTSTUDIOAGENT__APPROVAL__SCHEMANAME",
            "COPILOTSTUDIOAGENT__TRAVEL_PLANNING_PARENT__SCHEMANAME",
        ]:
            monkeypatch.delenv(var, raising=False)

        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        result = verifier.check_environment_variables()

        assert result.status == CheckStatus.FAIL
        assert "missing" in result.message.lower()
        assert result.remediation  # Should have remediation instructions


class TestOfflineMode:
    """Tests for offline mode behavior."""

    def test_offline_skips_reachability(self, temp_config_dir: Path) -> None:
        """Verify that offline mode skips reachability checks."""
        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        result = verifier.check_agents_reachable()

        assert result.status == CheckStatus.SKIP
        assert "offline" in result.message.lower()

    def test_offline_does_not_skip_config_checks(
        self, temp_config_dir: Path
    ) -> None:
        """Verify that offline mode does not skip config checks."""
        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        result = verifier.check_config_exists()

        assert result.status != CheckStatus.SKIP


class TestRunAllChecks:
    """Tests for run_all_checks method."""

    def test_run_all_checks_returns_all_results(
        self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that run_all_checks returns results for all checks."""
        # Set env vars to avoid failures
        env_vars = {
            "COPILOTSTUDIOAGENT__TENANTID": "test-tenant",
            "COPILOTSTUDIOAGENT__AGENTAPPID": "test-app-id",
            "COPILOTSTUDIOAGENT__AGENTAPPSECRET": "test-secret",
            "COPILOTSTUDIOAGENT__ENVIRONMENTID": "test-env",
            "COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME": "weather-schema",
            "COPILOTSTUDIOAGENT__APPROVAL__SCHEMANAME": "approval-schema",
            "COPILOTSTUDIOAGENT__TRAVEL_PLANNING_PARENT__SCHEMANAME": "travel-planning-parent-schema",
        }
        for var, value in env_vars.items():
            monkeypatch.setenv(var, value)

        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        results = verifier.run_all_checks()

        # Should have 5 checks
        assert len(results) == 5

        check_names = [r.name for r in results]
        assert "Config File" in check_names
        assert "Agents Defined" in check_names
        assert "Environment Variables" in check_names
        assert "Authentication Config" in check_names
        assert "Agent Reachability" in check_names

    def test_run_all_checks_handles_exceptions(
        self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that run_all_checks handles exceptions gracefully."""
        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        # Monkey-patch a check to raise an exception
        def raise_error():
            raise ValueError("Test error")

        verifier.check_config_exists = raise_error

        results = verifier.run_all_checks()

        # First check should be a failure due to exception
        assert results[0].status == CheckStatus.FAIL
        assert "error" in results[0].message.lower()


class TestAgentConfig:
    """Tests for AgentConfig dataclass."""

    def test_agent_config_defaults(self) -> None:
        """Verify AgentConfig default values."""
        config = AgentConfig(name="test", display_name="Test Agent")

        assert config.description == ""
        assert config.topics == []
        assert config.connected_agents == []
        assert config.schema_name_env_var == ""

    def test_agent_config_with_values(self) -> None:
        """Verify AgentConfig with all values."""
        config = AgentConfig(
            name="test",
            display_name="Test Agent",
            description="A test agent",
            topics=["topic1", "topic2"],
            connected_agents=["agent1"],
            schema_name_env_var="TEST_SCHEMA",
        )

        assert config.name == "test"
        assert config.display_name == "Test Agent"
        assert config.description == "A test agent"
        assert "topic1" in config.topics
        assert "agent1" in config.connected_agents
        assert config.schema_name_env_var == "TEST_SCHEMA"


class TestWeatherAgent:
    """Tests for Weather agent verification (INTEROP-010D)."""

    def test_config_has_weather_agent_entry(self, temp_config_dir: Path) -> None:
        """Verify that config has weather agent entry with agent_id field."""
        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        # Check that weather agent exists in config
        assert "weather" in verifier.config.agents

        # Check the weather agent has expected properties
        weather_config = verifier.config.agents["weather"]
        assert weather_config.display_name == "Weather Agent"
        assert "get_weather_forecast" in weather_config.topics

    def test_verify_weather_agent_function_exists(self, temp_config_dir: Path) -> None:
        """Verify that check_weather_agent method exists and returns CheckResult."""
        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        # Verify the function exists
        assert hasattr(verifier, "check_weather_agent")
        assert callable(verifier.check_weather_agent)

        # Verify it returns a CheckResult
        result = verifier.check_weather_agent()
        assert isinstance(result, CheckResult)

    def test_check_weather_agent_passes_when_defined(
        self, temp_config_dir: Path
    ) -> None:
        """Verify that check_weather_agent passes when weather agent is defined."""
        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        result = verifier.check_weather_agent()

        assert result.status == CheckStatus.PASS
        assert "weather agent" in result.message.lower()
        assert "defined" in result.message.lower() or "configured" in result.message.lower()

    def test_check_weather_agent_fails_when_missing(
        self, tmp_path: Path
    ) -> None:
        """Verify that check_weather_agent fails when weather agent is not defined."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
platform: copilot_studio

agents:
  approval:
    name: Approval Agent
    description: Test approval agent
    topics:
      - request_approval
""")

        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=config_file,
        )

        result = verifier.check_weather_agent()

        assert result.status == CheckStatus.FAIL
        assert "not defined" in result.message.lower()
        assert result.remediation  # Should have remediation instructions

    def test_check_weather_agent_shows_agent_id_status(
        self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that check_weather_agent reports agent_id status."""
        monkeypatch.setenv("COPILOTSTUDIOAGENT__WEATHER__AGENTID", "test-agent-id-123")

        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        result = verifier.check_weather_agent()

        assert result.status == CheckStatus.PASS
        assert any("agent id" in d.lower() for d in result.details)

    def test_check_weather_agent_warns_missing_topics(
        self, tmp_path: Path
    ) -> None:
        """Verify that check_weather_agent warns when required topics are missing."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
platform: copilot_studio

agents:
  weather:
    name: Weather Agent
    description: Test weather agent
    topics: []
""")

        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=config_file,
        )

        result = verifier.check_weather_agent()

        assert result.status == CheckStatus.WARN
        assert "missing topics" in result.message.lower()


class TestApprovalAgent:
    """Tests for Approval agent verification (INTEROP-013B)."""

    def test_config_has_approval_agent_entry(self, temp_config_dir: Path) -> None:
        """Verify that config has approval agent entry with agent_id field."""
        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        # Check that approval agent exists in config
        assert "approval" in verifier.config.agents

        # Check the approval agent has expected properties
        approval_config = verifier.config.agents["approval"]
        assert approval_config.display_name == "Approval Agent"
        assert "request_approval" in approval_config.topics

    def test_verify_approval_agent_function_exists(self, temp_config_dir: Path) -> None:
        """Verify that check_approval_agent method exists and returns CheckResult."""
        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        # Verify the function exists
        assert hasattr(verifier, "check_approval_agent")
        assert callable(verifier.check_approval_agent)

        # Verify it returns a CheckResult
        result = verifier.check_approval_agent()
        assert isinstance(result, CheckResult)

    def test_check_approval_agent_passes_when_defined(
        self, temp_config_dir: Path
    ) -> None:
        """Verify that check_approval_agent passes when approval agent is defined."""
        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        result = verifier.check_approval_agent()

        assert result.status == CheckStatus.PASS
        assert "approval agent" in result.message.lower()
        assert "defined" in result.message.lower() or "configured" in result.message.lower()

    def test_check_approval_agent_fails_when_missing(
        self, minimal_config_dir: Path
    ) -> None:
        """Verify that check_approval_agent fails when approval agent is not defined."""
        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=minimal_config_dir / "config.yaml",
        )

        result = verifier.check_approval_agent()

        assert result.status == CheckStatus.FAIL
        assert "not defined" in result.message.lower()
        assert result.remediation  # Should have remediation instructions

    def test_check_approval_agent_shows_agent_id_status(
        self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that check_approval_agent reports agent_id status."""
        monkeypatch.setenv("COPILOTSTUDIOAGENT__APPROVAL__AGENTID", "test-agent-id-123")

        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=temp_config_dir / "config.yaml",
        )

        result = verifier.check_approval_agent()

        assert result.status == CheckStatus.PASS
        assert any("agent id" in d.lower() for d in result.details)

    def test_check_approval_agent_warns_missing_topics(
        self, tmp_path: Path
    ) -> None:
        """Verify that check_approval_agent warns when required topics are missing."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
platform: copilot_studio

agents:
  approval:
    name: Approval Agent
    description: Test approval agent
    topics: []
""")

        verifier = CopilotStudioVerifier(
            offline=True,
            config_path=config_file,
        )

        result = verifier.check_approval_agent()

        assert result.status == CheckStatus.WARN
        assert "missing topics" in result.message.lower()


class TestCheckResult:
    """Tests for CheckResult dataclass."""

    def test_check_result_defaults(self) -> None:
        """Verify CheckResult default values."""
        result = CheckResult(
            name="Test",
            status=CheckStatus.PASS,
            message="Test passed",
        )

        assert result.remediation == ""
        assert result.details == []

    def test_check_result_with_values(self) -> None:
        """Verify CheckResult with all values."""
        result = CheckResult(
            name="Test",
            status=CheckStatus.FAIL,
            message="Test failed",
            remediation="Fix it",
            details=["Detail 1", "Detail 2"],
        )

        assert result.name == "Test"
        assert result.status == CheckStatus.FAIL
        assert result.message == "Test failed"
        assert result.remediation == "Fix it"
        assert len(result.details) == 2
