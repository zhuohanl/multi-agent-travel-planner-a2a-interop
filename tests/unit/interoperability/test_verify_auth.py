"""Unit tests for verify_auth.py authentication verification script.

Tests the 6 verification checks:
1. Azure AD App Registrations (interop-foundry-to-cs)
2. Admin Consent
3. Key Vault Secrets
4. Foundry Agent Permissions (user RBAC access)
5. Copilot Studio Added Agents
6. Environment Variables
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from interoperability.verify_auth import (
    AuthVerifier,
    CheckResult,
    CheckStatus,
    CommandRunner,
    VerificationConfig,
    print_results,
)


class MockCommandRunner(CommandRunner):
    """Mock command runner for testing."""

    def __init__(self, responses: dict[tuple[str, ...], tuple[int, str, str]] | None = None):
        """Initialize with predefined responses.

        Args:
            responses: Dict mapping command tuples to (returncode, stdout, stderr).
        """
        self.responses = responses or {}
        self.calls: list[list[str]] = []

    def run(self, command: list[str]) -> tuple[int, str, str]:
        """Return predefined response for command."""
        self.calls.append(command)
        key = tuple(command)
        if key in self.responses:
            return self.responses[key]
        # Default: command not found
        return 1, "", f"Command not found: {command[0]}"


@pytest.fixture
def temp_config_dir(tmp_path: Path) -> Path:
    """Create temporary config directory with test configs."""
    foundry_dir = tmp_path / "foundry"
    foundry_dir.mkdir()

    cs_dir = tmp_path / "copilot_studio"
    cs_dir.mkdir()

    # Create Foundry config
    foundry_config = foundry_dir / "config.yaml"
    foundry_config.write_text("""
platform: azure_ai_foundry
resource_group: test-rg
project: test-project

agents:
  transport:
    type: native
    source: src/agents/transport_agent
  poi:
    type: native
    source: src/agents/poi_search_agent
  weather_proxy:
    type: hosted
    framework: agent_framework
    source: interoperability/foundry/agents/weather_proxy
    env_vars:
      - COPILOTSTUDIOAGENT__ENVIRONMENTID
      - COPILOTSTUDIOAGENT__SCHEMANAME
""")

    # Create Copilot Studio config
    cs_config = cs_dir / "config.yaml"
    cs_config.write_text("""
platform: copilot_studio
environment_id: test-env

agents:
  weather:
    name: Weather Agent
  approval:
    name: Approval Agent
  travel_planning_parent:
    name: Q&A Parent Agent
    connected_agents:
      - transport
      - poi
""")

    return tmp_path


class TestCheckAllItems:
    """Tests for verifying all 6 checklist items are checked."""

    def test_verify_auth_checks_all_items(self, temp_config_dir: Path) -> None:
        """Verify that run_all_checks runs all 6 verification checks."""
        mock_runner = MockCommandRunner({
            ("az", "--version"): (0, "az 2.0", ""),
        })

        verifier = AuthVerifier(
            command_runner=mock_runner,
            offline=False,
            foundry_config_path=temp_config_dir / "foundry" / "config.yaml",
            copilot_config_path=temp_config_dir / "copilot_studio" / "config.yaml",
        )

        results = verifier.run_all_checks()

        # Should have exactly 6 checks
        assert len(results) == 6

        # Verify all check names
        check_names = [r.name for r in results]
        assert "Azure AD App Registrations" in check_names
        assert "Admin Consent" in check_names
        assert "Key Vault Secrets" in check_names
        assert "Foundry Agent Permissions" in check_names
        assert "Copilot Studio Added Agents" in check_names
        assert "Environment Variables" in check_names

    def test_verify_auth_offline_skips_network_checks(
        self, temp_config_dir: Path
    ) -> None:
        """Verify that offline mode skips checks requiring network access."""
        verifier = AuthVerifier(
            offline=True,
            foundry_config_path=temp_config_dir / "foundry" / "config.yaml",
            copilot_config_path=temp_config_dir / "copilot_studio" / "config.yaml",
        )

        results = verifier.run_all_checks()

        # Network-dependent checks should be skipped
        skipped_checks = [r for r in results if r.status == CheckStatus.SKIP]
        assert len(skipped_checks) >= 4  # App registrations, consent, keyvault, permissions, connected agents

        # Environment variables check should NOT be skipped
        env_check = next(r for r in results if r.name == "Environment Variables")
        assert env_check.status != CheckStatus.SKIP


class TestMissingEnvVars:
    """Tests for environment variable detection."""

    def test_verify_auth_reports_missing_env_vars(
        self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that missing environment variables are reported."""
        # Clear all relevant env vars
        for var in [
            "AZURE_TENANT_ID",
            "COPILOTSTUDIOAGENT__TENANTID",
            "COPILOTSTUDIOAGENT__AGENTAPPID",
            "COPILOTSTUDIOAGENT__AGENTAPPSECRET",
            "COPILOTSTUDIOAGENT__ENVIRONMENTID",
            "COPILOTSTUDIOAGENT__SCHEMANAME",
        ]:
            monkeypatch.delenv(var, raising=False)

        verifier = AuthVerifier(
            offline=True,
            foundry_config_path=temp_config_dir / "foundry" / "config.yaml",
            copilot_config_path=temp_config_dir / "copilot_studio" / "config.yaml",
        )

        result = verifier.check_environment_variables()

        assert result.status == CheckStatus.FAIL
        assert "Missing" in result.message
        assert result.remediation  # Should have remediation instructions
        assert "AZURE_TENANT_ID" in result.remediation

    def test_verify_auth_passes_with_all_env_vars(
        self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that all env vars set results in PASS."""
        # Set all required env vars
        env_vars = {
            "AZURE_TENANT_ID": "test-tenant",
            "COPILOTSTUDIOAGENT__TENANTID": "test-tenant",
            "COPILOTSTUDIOAGENT__AGENTAPPID": "test-app-id",
            "COPILOTSTUDIOAGENT__AGENTAPPSECRET": "test-secret",
            "COPILOTSTUDIOAGENT__ENVIRONMENTID": "test-env",
            "COPILOTSTUDIOAGENT__SCHEMANAME": "test-schema",
        }
        for var, value in env_vars.items():
            monkeypatch.setenv(var, value)

        verifier = AuthVerifier(
            offline=True,
            foundry_config_path=temp_config_dir / "foundry" / "config.yaml",
            copilot_config_path=temp_config_dir / "copilot_studio" / "config.yaml",
        )

        result = verifier.check_environment_variables()

        assert result.status == CheckStatus.PASS


class TestAppRegistration:
    """Tests for Azure AD app registration detection."""

    def test_verify_auth_detects_missing_app_registration(
        self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that missing app registrations are detected."""
        monkeypatch.setenv("INTEROP_FOUNDRY_TO_CS_APP_ID", "test-app-id")

        mock_runner = MockCommandRunner({
            ("az", "--version"): (0, "az 2.0", ""),
            # App not found
            ("az", "ad", "app", "show", "--id", "test-app-id", "--output", "json"): (
                1,
                "",
                "Resource not found",
            ),
        })

        verifier = AuthVerifier(
            command_runner=mock_runner,
            foundry_config_path=temp_config_dir / "foundry" / "config.yaml",
            copilot_config_path=temp_config_dir / "copilot_studio" / "config.yaml",
        )

        result = verifier.check_app_registrations()

        assert result.status == CheckStatus.FAIL
        assert "Missing app registrations" in result.message

    def test_verify_auth_passes_with_app_registrations(
        self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that found app registrations result in PASS."""
        monkeypatch.setenv("INTEROP_FOUNDRY_TO_CS_APP_ID", "test-app-id")

        mock_runner = MockCommandRunner({
            ("az", "--version"): (0, "az 2.0", ""),
            # App found
            ("az", "ad", "app", "show", "--id", "test-app-id", "--output", "json"): (
                0,
                '{"id": "test-app-id"}',
                "",
            ),
        })

        verifier = AuthVerifier(
            command_runner=mock_runner,
            foundry_config_path=temp_config_dir / "foundry" / "config.yaml",
            copilot_config_path=temp_config_dir / "copilot_studio" / "config.yaml",
        )

        result = verifier.check_app_registrations()

        assert result.status == CheckStatus.PASS
        assert "interop-foundry-to-cs" in result.message


class TestKeyVaultSecrets:
    """Tests for Key Vault secret detection."""

    def test_verify_auth_detects_missing_keyvault_secret(
        self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that missing Key Vault secrets are detected."""
        # Remove the secret env var
        monkeypatch.delenv("COPILOTSTUDIOAGENT__AGENTAPPSECRET", raising=False)

        verifier = AuthVerifier(
            offline=False,  # But won't actually call az since secret not configured
            foundry_config_path=temp_config_dir / "foundry" / "config.yaml",
            copilot_config_path=temp_config_dir / "copilot_studio" / "config.yaml",
        )

        result = verifier.check_keyvault_secrets()

        assert result.status == CheckStatus.FAIL
        assert "not configured" in result.message

    def test_verify_auth_passes_with_env_var_secret(
        self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that direct env var secret results in PASS."""
        monkeypatch.setenv("COPILOTSTUDIOAGENT__AGENTAPPSECRET", "direct-secret-value")

        verifier = AuthVerifier(
            offline=False,
            foundry_config_path=temp_config_dir / "foundry" / "config.yaml",
            copilot_config_path=temp_config_dir / "copilot_studio" / "config.yaml",
        )

        result = verifier.check_keyvault_secrets()

        assert result.status == CheckStatus.PASS
        assert "local dev mode" in result.message

    def test_verify_auth_validates_keyvault_reference_format(
        self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that Key Vault reference format is validated."""
        # Invalid Key Vault reference format
        monkeypatch.setenv(
            "COPILOTSTUDIOAGENT__AGENTAPPSECRET", "@Microsoft.KeyVault(invalid)"
        )

        verifier = AuthVerifier(
            offline=False,
            foundry_config_path=temp_config_dir / "foundry" / "config.yaml",
            copilot_config_path=temp_config_dir / "copilot_studio" / "config.yaml",
        )

        result = verifier.check_keyvault_secrets()

        assert result.status == CheckStatus.FAIL
        assert "Invalid" in result.message

    def test_verify_auth_checks_keyvault_access(
        self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that Key Vault access is checked when reference is valid."""
        monkeypatch.setenv(
            "COPILOTSTUDIOAGENT__AGENTAPPSECRET",
            "@Microsoft.KeyVault(SecretUri=https://test-vault.vault.azure.net/secrets/test-secret)",
        )

        mock_runner = MockCommandRunner({
            (
                "az",
                "keyvault",
                "secret",
                "show",
                "--id",
                "https://test-vault.vault.azure.net/secrets/test-secret",
                "--query",
                "id",
            ): (0, '"secret-id"', ""),
        })

        verifier = AuthVerifier(
            command_runner=mock_runner,
            foundry_config_path=temp_config_dir / "foundry" / "config.yaml",
            copilot_config_path=temp_config_dir / "copilot_studio" / "config.yaml",
        )

        result = verifier.check_keyvault_secrets()

        assert result.status == CheckStatus.PASS
        assert "accessible" in result.message


class TestExitCode:
    """Tests for exit code behavior."""

    def test_verify_auth_exit_code_nonzero_on_failure(
        self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that exit code is non-zero when checks fail."""
        # Clear env vars to cause failure
        for var in [
            "AZURE_TENANT_ID",
            "COPILOTSTUDIOAGENT__TENANTID",
            "COPILOTSTUDIOAGENT__AGENTAPPID",
            "COPILOTSTUDIOAGENT__AGENTAPPSECRET",
            "COPILOTSTUDIOAGENT__ENVIRONMENTID",
            "COPILOTSTUDIOAGENT__SCHEMANAME",
        ]:
            monkeypatch.delenv(var, raising=False)

        verifier = AuthVerifier(
            offline=True,
            foundry_config_path=temp_config_dir / "foundry" / "config.yaml",
            copilot_config_path=temp_config_dir / "copilot_studio" / "config.yaml",
        )

        results = verifier.run_all_checks()

        # Environment Variables check should fail
        has_failure = any(r.status == CheckStatus.FAIL for r in results)
        assert has_failure

    def test_verify_auth_exit_code_zero_on_success(
        self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that exit code is zero when all checks pass (offline mode)."""
        # Set all required env vars
        env_vars = {
            "AZURE_TENANT_ID": "test-tenant",
            "COPILOTSTUDIOAGENT__TENANTID": "test-tenant",
            "COPILOTSTUDIOAGENT__AGENTAPPID": "test-app-id",
            "COPILOTSTUDIOAGENT__AGENTAPPSECRET": "test-secret",
            "COPILOTSTUDIOAGENT__ENVIRONMENTID": "test-env",
            "COPILOTSTUDIOAGENT__SCHEMANAME": "test-schema",
        }
        for var, value in env_vars.items():
            monkeypatch.setenv(var, value)

        verifier = AuthVerifier(
            offline=True,  # Skip network checks
            foundry_config_path=temp_config_dir / "foundry" / "config.yaml",
            copilot_config_path=temp_config_dir / "copilot_studio" / "config.yaml",
        )

        results = verifier.run_all_checks()

        # No failures (only skips and passes)
        has_failure = any(r.status == CheckStatus.FAIL for r in results)
        assert not has_failure


class TestConfigLoading:
    """Tests for configuration loading."""

    def test_load_foundry_agents_from_config(self, temp_config_dir: Path) -> None:
        """Verify that Foundry agent names are loaded from config."""
        verifier = AuthVerifier(
            offline=True,
            foundry_config_path=temp_config_dir / "foundry" / "config.yaml",
            copilot_config_path=temp_config_dir / "copilot_studio" / "config.yaml",
        )

        config = verifier.config
        assert "transport" in config.foundry_agents
        assert "poi" in config.foundry_agents
        assert "weather_proxy" in config.foundry_agents

    def test_load_copilot_studio_agents_from_config(
        self, temp_config_dir: Path
    ) -> None:
        """Verify that Copilot Studio agent names are loaded from config."""
        verifier = AuthVerifier(
            offline=True,
            foundry_config_path=temp_config_dir / "foundry" / "config.yaml",
            copilot_config_path=temp_config_dir / "copilot_studio" / "config.yaml",
        )

        config = verifier.config
        assert "weather" in config.copilot_studio_agents
        assert "approval" in config.copilot_studio_agents
        assert "travel_planning_parent" in config.copilot_studio_agents

    def test_load_env_vars_from_agent_config(self, temp_config_dir: Path) -> None:
        """Verify that agent-specific env vars are loaded from config."""
        verifier = AuthVerifier(
            offline=True,
            foundry_config_path=temp_config_dir / "foundry" / "config.yaml",
            copilot_config_path=temp_config_dir / "copilot_studio" / "config.yaml",
        )

        config = verifier.config
        # weather_proxy has env_vars in config
        assert "COPILOTSTUDIOAGENT__ENVIRONMENTID" in config.foundry_env_vars
        assert "COPILOTSTUDIOAGENT__SCHEMANAME" in config.foundry_env_vars


class TestFoundryPermissions:
    """Tests for Foundry agent permissions check (user RBAC access)."""

    def test_check_foundry_permissions_requires_manual_verification(
        self, temp_config_dir: Path
    ) -> None:
        """Verify that manual verification is required for Foundry permissions."""
        verifier = AuthVerifier(
            offline=False,
            foundry_config_path=temp_config_dir / "foundry" / "config.yaml",
            copilot_config_path=temp_config_dir / "copilot_studio" / "config.yaml",
        )

        result = verifier.check_foundry_permissions()

        assert result.status == CheckStatus.WARN
        assert "Manual verification required" in result.message
        assert "RBAC" in result.remediation


class TestConnectedAgents:
    """Tests for Copilot Studio added agents check."""

    def test_check_connected_agents_finds_travel_planning_parent(
        self, temp_config_dir: Path
    ) -> None:
        """Verify that Travel Planning Parent agent is found in config."""
        verifier = AuthVerifier(
            offline=False,
            foundry_config_path=temp_config_dir / "foundry" / "config.yaml",
            copilot_config_path=temp_config_dir / "copilot_studio" / "config.yaml",
        )

        result = verifier.check_connected_agents()

        # Should warn for manual verification, not fail
        assert result.status == CheckStatus.WARN
        assert "Manual verification required" in result.message

    def test_check_connected_agents_warns_missing_travel_planning_parent(
        self, tmp_path: Path
    ) -> None:
        """Verify warning when Travel Planning Parent is not defined."""
        # Create config without travel_planning_parent
        cs_dir = tmp_path / "copilot_studio"
        cs_dir.mkdir()
        cs_config = cs_dir / "config.yaml"
        cs_config.write_text("""
platform: copilot_studio
agents:
  weather:
    name: Weather Agent
""")

        foundry_dir = tmp_path / "foundry"
        foundry_dir.mkdir()
        foundry_config = foundry_dir / "config.yaml"
        foundry_config.write_text("""
platform: azure_ai_foundry
resource_group: test
project: test
agents: {}
""")

        verifier = AuthVerifier(
            offline=False,
            foundry_config_path=foundry_config,
            copilot_config_path=cs_config,
        )

        result = verifier.check_connected_agents()

        assert result.status == CheckStatus.WARN
        assert "Travel Planning Parent" in result.message


class TestPrintResults:
    """Tests for result printing."""

    def test_print_results_shows_summary(self, capsys: pytest.CaptureFixture) -> None:
        """Verify that print_results shows summary."""
        results = [
            CheckResult(
                name="Test Check 1",
                status=CheckStatus.PASS,
                message="Test passed",
            ),
            CheckResult(
                name="Test Check 2",
                status=CheckStatus.FAIL,
                message="Test failed",
                remediation="Fix the issue",
            ),
        ]

        print_results(results, verbose=False)
        captured = capsys.readouterr()

        assert "Summary:" in captured.out
        assert "1 passed" in captured.out
        assert "1 failed" in captured.out

    def test_print_results_shows_remediation_on_failure(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """Verify that remediation is shown for failures."""
        results = [
            CheckResult(
                name="Test Check",
                status=CheckStatus.FAIL,
                message="Test failed",
                remediation="Do this to fix",
            ),
        ]

        print_results(results, verbose=False)
        captured = capsys.readouterr()

        assert "Remediation:" in captured.out
        assert "Do this to fix" in captured.out

    def test_print_results_shows_details_in_verbose(
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


class TestCommandRunner:
    """Tests for CommandRunner class."""

    def test_command_runner_handles_timeout(self) -> None:
        """Verify that command runner handles timeout."""
        runner = CommandRunner()

        # This should timeout or fail (sleep doesn't exist with timeout)
        with patch("subprocess.run") as mock_run:
            from subprocess import TimeoutExpired

            mock_run.side_effect = TimeoutExpired("cmd", 30)
            returncode, stdout, stderr = runner.run(["sleep", "100"])

            assert returncode == 1
            assert "timed out" in stderr

    def test_command_runner_handles_missing_command(self) -> None:
        """Verify that command runner handles missing commands."""
        runner = CommandRunner()

        # Non-existent command
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            returncode, stdout, stderr = runner.run(["nonexistent_command"])

            assert returncode == 1
            assert "not found" in stderr
