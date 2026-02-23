"""
Copilot Studio Agent Verification Script

Validates that all required Copilot Studio agents exist and are configured correctly.

This script checks:
1. Agent configurations in config.yaml
2. Required environment variables
3. Agent reachability (when not in offline mode)
4. Authentication configuration

Usage:
    python verify.py                # Run all checks
    python verify.py --offline      # Run without network checks (for testing)
    python verify.py --verbose      # Show detailed output
    python verify.py --config PATH  # Use custom config file

Design doc references:
    - Appendix A.3 Copilot Studio: lines 1648-1760
    - Cross-Platform Authentication: lines 964-1056
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import yaml


class CheckStatus(Enum):
    """Status of a verification check."""

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


@dataclass
class CheckResult:
    """Result of a single verification check."""

    name: str
    status: CheckStatus
    message: str
    remediation: str = ""
    details: list[str] = field(default_factory=list)


@dataclass
class AgentConfig:
    """Configuration for a single Copilot Studio agent."""

    name: str
    display_name: str
    description: str = ""
    topics: list[str] = field(default_factory=list)
    connected_agents: list[str] = field(default_factory=list)
    schema_name_env_var: str = ""


@dataclass
class VerificationConfig:
    """Configuration for verification, loaded from config files."""

    # Environment settings
    environment_id: str | None = None
    tenant_id: str | None = None
    app_id: str | None = None

    # Agents defined in config
    agents: dict[str, AgentConfig] = field(default_factory=dict)


class CopilotStudioVerifier:
    """Verifies Copilot Studio agent configuration and availability.

    Performs verification checks:
    1. Agent reachability (via mock or actual API)
    2. Authentication configuration
    3. Topics/triggers exist
    4. Environment variables are set
    """

    # Required base environment variables
    BASE_ENV_VARS = [
        "COPILOTSTUDIOAGENT__TENANTID",
        "COPILOTSTUDIOAGENT__AGENTAPPID",
        "COPILOTSTUDIOAGENT__ENVIRONMENTID",
    ]

    # Required env vars for authentication (may be in Key Vault for production)
    AUTH_ENV_VARS = [
        "COPILOTSTUDIOAGENT__AGENTAPPSECRET",
    ]

    # Agent-specific schema name env vars
    AGENT_SCHEMA_VARS = {
        "weather": "COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME",
        "approval": "COPILOTSTUDIOAGENT__APPROVAL__SCHEMANAME",
        "travel_planning_parent": "COPILOTSTUDIOAGENT__TRAVEL_PLANNING_PARENT__SCHEMANAME",
    }

    def __init__(
        self,
        offline: bool = False,
        verbose: bool = False,
        config_path: Path | None = None,
        mock_responses: dict[str, Any] | None = None,
    ):
        """Initialize the verifier.

        Args:
            offline: If True, skip checks that require network access.
            verbose: If True, show detailed output.
            config_path: Path to config.yaml. Defaults to same directory as this file.
            mock_responses: Dict of agent name -> mock response for testing.
        """
        self.offline = offline
        self.verbose = verbose
        self.mock_responses = mock_responses or {}

        # Set default config path relative to this file
        if config_path is None:
            config_path = Path(__file__).parent / "config.yaml"
        self.config_path = config_path

        self._config: VerificationConfig | None = None

    @property
    def config(self) -> VerificationConfig:
        """Get verification configuration, loading from file if needed."""
        if self._config is None:
            self._config = self._load_config()
        return self._config

    def _load_config(self) -> VerificationConfig:
        """Load configuration from config.yaml and environment.

        Returns:
            VerificationConfig with loaded values.
        """
        config = VerificationConfig()

        # Load from environment
        config.tenant_id = os.environ.get("COPILOTSTUDIOAGENT__TENANTID")
        config.app_id = os.environ.get("COPILOTSTUDIOAGENT__AGENTAPPID")
        config.environment_id = os.environ.get("COPILOTSTUDIOAGENT__ENVIRONMENTID")

        # Load from config file
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    yaml_config = yaml.safe_load(f)

                # Override environment_id if in config
                if yaml_config.get("environment_id"):
                    env_id = yaml_config["environment_id"]
                    # Handle ${VAR} syntax
                    if env_id.startswith("${") and env_id.endswith("}"):
                        var_name = env_id[2:-1]
                        config.environment_id = os.environ.get(var_name)
                    else:
                        config.environment_id = env_id

                # Parse agent configurations
                agents_config = yaml_config.get("agents", {})
                for agent_name, agent_data in agents_config.items():
                    agent_config = AgentConfig(
                        name=agent_name,
                        display_name=agent_data.get("name", agent_name),
                        description=agent_data.get("description", ""),
                        topics=agent_data.get("topics", []),
                        connected_agents=agent_data.get("connected_agents", []),
                        schema_name_env_var=self.AGENT_SCHEMA_VARS.get(
                            agent_name, f"COPILOTSTUDIOAGENT__{agent_name.upper()}__SCHEMANAME"
                        ),
                    )
                    config.agents[agent_name] = agent_config

            except yaml.YAMLError as e:
                # Log error but continue with empty config
                if self.verbose:
                    print(f"Warning: Could not parse config.yaml: {e}")

        return config

    def run_all_checks(self) -> list[CheckResult]:
        """Run all verification checks.

        Returns:
            List of check results.
        """
        checks: list[tuple[str, Callable[[], CheckResult]]] = [
            ("Config File", self.check_config_exists),
            ("Agents Defined", self.check_agents_defined),
            ("Environment Variables", self.check_environment_variables),
            ("Authentication Config", self.check_auth_configured),
            ("Agent Reachability", self.check_agents_reachable),
        ]

        results = []
        for name, check_func in checks:
            try:
                result = check_func()
            except Exception as e:
                result = CheckResult(
                    name=name,
                    status=CheckStatus.FAIL,
                    message=f"Check failed with error: {e}",
                    remediation="Review the error and fix the underlying issue.",
                )
            results.append(result)

        return results

    def check_config_exists(self) -> CheckResult:
        """Check that config.yaml exists and is valid.

        Returns:
            CheckResult with pass/fail status.
        """
        if not self.config_path.exists():
            return CheckResult(
                name="Config File",
                status=CheckStatus.FAIL,
                message=f"Config file not found: {self.config_path}",
                remediation=(
                    "Create copilot_studio/config.yaml with agent definitions.\n"
                    "See SETUP.md for required format."
                ),
            )

        try:
            with open(self.config_path) as f:
                yaml_config = yaml.safe_load(f)

            if yaml_config is None:
                return CheckResult(
                    name="Config File",
                    status=CheckStatus.FAIL,
                    message="Config file is empty",
                    remediation="Add agent definitions to config.yaml",
                )

            if "agents" not in yaml_config:
                return CheckResult(
                    name="Config File",
                    status=CheckStatus.WARN,
                    message="No 'agents' section in config",
                    remediation="Add an 'agents' section with agent definitions",
                )

            return CheckResult(
                name="Config File",
                status=CheckStatus.PASS,
                message=f"Config file exists at {self.config_path}",
                details=[f"Contains {len(yaml_config.get('agents', {}))} agent(s)"],
            )

        except yaml.YAMLError as e:
            return CheckResult(
                name="Config File",
                status=CheckStatus.FAIL,
                message=f"Invalid YAML in config file: {e}",
                remediation="Fix the YAML syntax in config.yaml",
            )

    def check_agents_defined(self) -> CheckResult:
        """Check that required agents are defined in config.

        Returns:
            CheckResult with pass/fail status.
        """
        required_agents = ["weather", "approval", "travel_planning_parent"]
        defined_agents = list(self.config.agents.keys())
        missing_agents = [a for a in required_agents if a not in defined_agents]

        details = [f"Defined agents: {', '.join(defined_agents) or 'none'}"]

        if missing_agents:
            return CheckResult(
                name="Agents Defined",
                status=CheckStatus.WARN,
                message=f"Missing agent definitions: {', '.join(missing_agents)}",
                remediation=(
                    "Add missing agents to copilot_studio/config.yaml.\n"
                    "Required agents for demos:\n"
                    "  - weather: Demo A (Foundry -> CS)\n"
                    "  - approval: Demo B (Pro Code -> CS)\n"
                    "  - travel_planning_parent: Demo C (CS -> Foundry)"
                ),
                details=details,
            )

        return CheckResult(
            name="Agents Defined",
            status=CheckStatus.PASS,
            message=f"All {len(required_agents)} required agents defined",
            details=details,
        )

    def check_environment_variables(self) -> CheckResult:
        """Check that required environment variables are set.

        Returns:
            CheckResult with pass/fail status.
        """
        missing_vars = []
        set_vars = []
        details = []

        # Check base env vars
        for var in self.BASE_ENV_VARS:
            if os.environ.get(var):
                set_vars.append(var)
                details.append(f"{var}: Set")
            else:
                missing_vars.append(var)
                details.append(f"{var}: NOT SET")

        # Check agent-specific schema name vars
        for agent_name, agent_config in self.config.agents.items():
            var = agent_config.schema_name_env_var
            if os.environ.get(var):
                set_vars.append(var)
                details.append(f"{var}: Set")
            else:
                missing_vars.append(var)
                details.append(f"{var}: NOT SET (for {agent_config.display_name})")

        if missing_vars:
            return CheckResult(
                name="Environment Variables",
                status=CheckStatus.FAIL,
                message=f"Missing {len(missing_vars)} required environment variables",
                remediation=(
                    "Set the missing environment variables:\n"
                    + "\n".join(f"  export {var}='<value>'" for var in missing_vars)
                    + "\n\nSee SETUP.md Step 5 for details."
                ),
                details=details,
            )

        return CheckResult(
            name="Environment Variables",
            status=CheckStatus.PASS,
            message=f"All {len(set_vars)} required environment variables are set",
            details=details,
        )

    def check_auth_configured(self) -> CheckResult:
        """Check that authentication is configured correctly.

        Returns:
            CheckResult with pass/fail status.
        """
        details = []
        issues = []

        # Check tenant ID
        tenant_id = os.environ.get("COPILOTSTUDIOAGENT__TENANTID")
        if tenant_id:
            details.append(f"Tenant ID: Configured ({tenant_id[:8]}...)")
        else:
            issues.append("Tenant ID not set")

        # Check app ID
        app_id = os.environ.get("COPILOTSTUDIOAGENT__AGENTAPPID")
        if app_id:
            details.append(f"App ID: Configured ({app_id[:8]}...)")
        else:
            issues.append("App ID not set")

        # Check client secret
        secret = os.environ.get("COPILOTSTUDIOAGENT__AGENTAPPSECRET")
        if secret:
            if secret.startswith("@Microsoft.KeyVault"):
                details.append("Client Secret: Key Vault reference configured")
            else:
                details.append("Client Secret: Direct value configured (local dev)")
        else:
            issues.append("Client secret not set")

        # Check environment ID
        env_id = self.config.environment_id
        if env_id:
            details.append(f"Environment ID: Configured ({env_id[:8]}...)")
        else:
            issues.append("Environment ID not set")

        if issues:
            return CheckResult(
                name="Authentication Config",
                status=CheckStatus.FAIL,
                message=f"{len(issues)} authentication issue(s) found",
                remediation=(
                    "Fix authentication configuration:\n"
                    + "\n".join(f"  - {issue}" for issue in issues)
                    + "\n\nSee SETUP.md Step 1 and Step 5 for details."
                ),
                details=details + issues,
            )

        return CheckResult(
            name="Authentication Config",
            status=CheckStatus.PASS,
            message="Authentication is properly configured",
            details=details,
        )

    def check_agents_reachable(self) -> CheckResult:
        """Check that agents are reachable (when not in offline mode).

        Returns:
            CheckResult with pass/fail status.
        """
        if self.offline:
            return CheckResult(
                name="Agent Reachability",
                status=CheckStatus.SKIP,
                message="Skipped in offline mode",
                remediation="Run without --offline to check agent reachability.",
            )

        # If mock responses provided, use those
        if self.mock_responses:
            return self._check_agents_with_mocks()

        # For real checks, we would use the M365 Agents SDK
        # Since we can't import it without the package being installed,
        # we return a warning with manual verification instructions
        agents = list(self.config.agents.keys())
        if not agents:
            return CheckResult(
                name="Agent Reachability",
                status=CheckStatus.WARN,
                message="No agents to check",
                remediation="Add agents to config.yaml first",
            )

        return CheckResult(
            name="Agent Reachability",
            status=CheckStatus.WARN,
            message=f"Manual verification required for {len(agents)} agent(s)",
            remediation=(
                "Verify agents are reachable:\n"
                "1. Open Copilot Studio portal\n"
                "2. For each agent, click 'Test' to verify it responds\n"
                "3. Check the agent is published (not in draft state)\n"
                "\nAgents to verify:\n"
                + "\n".join(
                    f"  - {self.config.agents[a].display_name}"
                    for a in agents
                )
            ),
            details=[f"Agents: {', '.join(agents)}"],
        )

    def _check_agents_with_mocks(self) -> CheckResult:
        """Check agent reachability using mock responses (for testing).

        Returns:
            CheckResult with pass/fail status.
        """
        reachable = []
        unreachable = []
        details = []

        for agent_name, agent_config in self.config.agents.items():
            if agent_name in self.mock_responses:
                response = self.mock_responses[agent_name]
                if response.get("status") == "ok" or response.get("reachable"):
                    reachable.append(agent_name)
                    details.append(f"{agent_config.display_name}: Reachable")
                else:
                    unreachable.append(agent_name)
                    error = response.get("error", "Unknown error")
                    details.append(f"{agent_config.display_name}: NOT REACHABLE ({error})")
            else:
                unreachable.append(agent_name)
                details.append(f"{agent_config.display_name}: No mock response")

        if unreachable:
            return CheckResult(
                name="Agent Reachability",
                status=CheckStatus.FAIL,
                message=f"{len(unreachable)} agent(s) not reachable",
                remediation=(
                    "Check the following agents:\n"
                    + "\n".join(f"  - {a}" for a in unreachable)
                    + "\n\nCommon issues:\n"
                    "  - Agent not published\n"
                    "  - Schema name incorrect\n"
                    "  - Authentication failed"
                ),
                details=details,
            )

        return CheckResult(
            name="Agent Reachability",
            status=CheckStatus.PASS,
            message=f"All {len(reachable)} agent(s) reachable",
            details=details,
        )

    def check_weather_agent(self) -> CheckResult:
        """Check that the Weather agent is defined and configured.

        Verifies:
        1. Weather agent is defined in config
        2. Weather agent has agent_id field (may be placeholder)
        3. Weather agent has required topics

        Returns:
            CheckResult with pass/fail status.
        """
        if "weather" not in self.config.agents:
            return CheckResult(
                name="Weather Agent",
                status=CheckStatus.FAIL,
                message="Weather agent not defined in config",
                remediation=(
                    "Add weather agent to copilot_studio/config.yaml:\n"
                    "  weather:\n"
                    "    name: Weather Agent\n"
                    "    agent_id: ${COPILOTSTUDIOAGENT__WEATHER__AGENTID}\n"
                    "    topics:\n"
                    "      - get_weather_forecast\n"
                    "\nSee interoperability/copilot_studio/agents/weather/README.md for setup."
                ),
            )

        weather_config = self.config.agents["weather"]
        details = [
            f"Display name: {weather_config.display_name}",
            f"Topics: {', '.join(weather_config.topics) or 'none'}",
        ]

        # Check for agent_id env var (placeholder is OK, just needs to be defined)
        agent_id_var = "COPILOTSTUDIOAGENT__WEATHER__AGENTID"
        agent_id = os.environ.get(agent_id_var)
        if agent_id:
            details.append(f"Agent ID: Configured ({agent_id[:8]}...)")
        else:
            details.append(f"Agent ID: NOT SET (set {agent_id_var} after portal deployment)")

        # Check for required topics
        required_topics = ["get_weather_forecast"]
        missing_topics = [t for t in required_topics if t not in weather_config.topics]
        if missing_topics:
            return CheckResult(
                name="Weather Agent",
                status=CheckStatus.WARN,
                message=f"Weather agent missing topics: {', '.join(missing_topics)}",
                remediation=(
                    "Add missing topics to weather agent config:\n"
                    + "\n".join(f"  - {t}" for t in missing_topics)
                ),
                details=details,
            )

        return CheckResult(
            name="Weather Agent",
            status=CheckStatus.PASS,
            message="Weather agent is defined and configured",
            details=details,
        )

    def check_approval_agent(self) -> CheckResult:
        """Check that the Approval agent is defined and configured.

        Verifies:
        1. Approval agent is defined in config
        2. Approval agent has agent_id field (may be placeholder)
        3. Approval agent has required topics

        Returns:
            CheckResult with pass/fail status.
        """
        if "approval" not in self.config.agents:
            return CheckResult(
                name="Approval Agent",
                status=CheckStatus.FAIL,
                message="Approval agent not defined in config",
                remediation=(
                    "Add approval agent to copilot_studio/config.yaml:\n"
                    "  approval:\n"
                    "    name: Approval Agent\n"
                    "    agent_id: ${COPILOTSTUDIOAGENT__APPROVAL__AGENTID}\n"
                    "    topics:\n"
                    "      - request_approval\n"
                    "\nSee interoperability/copilot_studio/agents/approval/README.md for setup."
                ),
            )

        approval_config = self.config.agents["approval"]
        details = [
            f"Display name: {approval_config.display_name}",
            f"Topics: {', '.join(approval_config.topics) or 'none'}",
        ]

        # Check for agent_id env var (placeholder is OK, just needs to be defined)
        agent_id_var = "COPILOTSTUDIOAGENT__APPROVAL__AGENTID"
        agent_id = os.environ.get(agent_id_var)
        if agent_id:
            details.append(f"Agent ID: Configured ({agent_id[:8]}...)")
        else:
            details.append(f"Agent ID: NOT SET (set {agent_id_var} after portal deployment)")

        # Check for required topics
        required_topics = ["request_approval"]
        missing_topics = [t for t in required_topics if t not in approval_config.topics]
        if missing_topics:
            return CheckResult(
                name="Approval Agent",
                status=CheckStatus.WARN,
                message=f"Approval agent missing topics: {', '.join(missing_topics)}",
                remediation=(
                    "Add missing topics to approval agent config:\n"
                    + "\n".join(f"  - {t}" for t in missing_topics)
                ),
                details=details,
            )

        return CheckResult(
            name="Approval Agent",
            status=CheckStatus.PASS,
            message="Approval agent is defined and configured",
            details=details,
        )

    def check_agent_reachable(self, agent_name: str) -> CheckResult:
        """Check if a specific agent is reachable.

        Args:
            agent_name: Name of the agent to check.

        Returns:
            CheckResult with pass/fail status.
        """
        if self.offline:
            return CheckResult(
                name=f"Agent Reachability ({agent_name})",
                status=CheckStatus.SKIP,
                message="Skipped in offline mode",
            )

        if agent_name not in self.config.agents:
            return CheckResult(
                name=f"Agent Reachability ({agent_name})",
                status=CheckStatus.FAIL,
                message=f"Agent '{agent_name}' not defined in config",
            )

        # Use mock if available
        if agent_name in self.mock_responses:
            response = self.mock_responses[agent_name]
            if response.get("status") == "ok" or response.get("reachable"):
                return CheckResult(
                    name=f"Agent Reachability ({agent_name})",
                    status=CheckStatus.PASS,
                    message="Agent is reachable",
                )
            else:
                return CheckResult(
                    name=f"Agent Reachability ({agent_name})",
                    status=CheckStatus.FAIL,
                    message=f"Agent not reachable: {response.get('error', 'Unknown error')}",
                )

        # Without mock, warn about manual verification
        return CheckResult(
            name=f"Agent Reachability ({agent_name})",
            status=CheckStatus.WARN,
            message="Manual verification required",
            remediation=(
                f"Verify '{agent_name}' in Copilot Studio portal:\n"
                "1. Open the agent\n"
                "2. Click 'Test' to verify it responds\n"
                "3. Check the agent is published"
            ),
        )


def print_results(results: list[CheckResult], verbose: bool = False) -> None:
    """Print verification results in a formatted table.

    Args:
        results: List of check results.
        verbose: If True, show detailed output.
    """
    print("\n" + "=" * 60)
    print("Copilot Studio Agent Verification")
    print("=" * 60 + "\n")

    status_symbols = {
        CheckStatus.PASS: "\u2713",  # checkmark
        CheckStatus.FAIL: "\u2717",  # X mark
        CheckStatus.WARN: "!",
        CheckStatus.SKIP: "-",
    }

    for result in results:
        symbol = status_symbols[result.status]
        status_str = result.status.value.upper()
        print(f"[{symbol}] {result.name}: {status_str}")
        print(f"    {result.message}")

        if result.status in (CheckStatus.FAIL, CheckStatus.WARN) and result.remediation:
            print("\n    Remediation:")
            for line in result.remediation.split("\n"):
                print(f"      {line}")

        if verbose and result.details:
            print("\n    Details:")
            for detail in result.details:
                print(f"      - {detail}")

        print()

    # Summary
    passed = sum(1 for r in results if r.status == CheckStatus.PASS)
    failed = sum(1 for r in results if r.status == CheckStatus.FAIL)
    warned = sum(1 for r in results if r.status == CheckStatus.WARN)
    skipped = sum(1 for r in results if r.status == CheckStatus.SKIP)

    print("-" * 60)
    print(f"Summary: {passed} passed, {failed} failed, {warned} warnings, {skipped} skipped")
    print("-" * 60)

    if failed > 0:
        print("\n[!] Fix the failed checks before running demos.")
    elif warned > 0:
        print("\n[!] Review warnings - some checks require manual verification.")
    else:
        print("\n[OK] All checks passed!")


def main() -> int:
    """Run Copilot Studio verification checks.

    Returns:
        Exit code: 0 if all checks pass, 1 if any fail.
    """
    parser = argparse.ArgumentParser(
        description="Verify Copilot Studio agent configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script verifies Copilot Studio agents are configured correctly:

1. Config File - config.yaml exists and is valid
2. Agents Defined - Required agents are defined (weather, approval, travel_planning_parent)
3. Environment Variables - Required env vars are set
4. Authentication Config - Auth settings are complete
5. Agent Reachability - Agents respond to queries

For detailed setup instructions, see SETUP.md.
        """,
    )

    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip checks that require network access",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output for each check",
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to config.yaml (default: same directory as this script)",
    )

    args = parser.parse_args()

    verifier = CopilotStudioVerifier(
        offline=args.offline,
        verbose=args.verbose,
        config_path=Path(args.config) if args.config else None,
    )

    results = verifier.run_all_checks()
    print_results(results, verbose=args.verbose)

    # Exit with error if any checks failed
    has_failures = any(r.status == CheckStatus.FAIL for r in results)
    return 1 if has_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
