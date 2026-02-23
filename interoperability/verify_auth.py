"""
Authentication verification script for cross-platform interoperability.

Validates that all required Azure AD apps, Key Vault secrets, and environment
variables are configured correctly before running demos.

This script performs the verification checks from the design doc
Cross-Platform Authentication section (lines 1046-1057):

1. Azure AD app (interop-foundry-to-cs) registered with correct API permissions
2. Admin consent granted for API permissions
3. Client secrets created and stored in Key Vault
4. Foundry agent connectivity (user RBAC access via Entra ID User Login)
5. Copilot Studio added agents configured correctly
6. Environment variables set (or Key Vault references configured)

Usage:
    python verify_auth.py                # Run all checks
    python verify_auth.py --offline      # Run without Azure CLI commands (for testing)
    python verify_auth.py --verbose      # Show detailed output

Design doc references:
    - Cross-Platform Authentication: lines 964-1056
    - Verification Checklist: lines 1046-1057
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
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
class VerificationConfig:
    """Configuration for verification, loaded from config files."""

    # Required Azure AD apps
    foundry_to_cs_app_id: str | None = None
    tenant_id: str | None = None

    # Environment IDs
    copilot_studio_env_id: str | None = None

    # Agent names from configs
    foundry_agents: list[str] = field(default_factory=list)
    copilot_studio_agents: list[str] = field(default_factory=list)

    # Required environment variables per platform
    foundry_env_vars: list[str] = field(default_factory=list)
    copilot_studio_env_vars: list[str] = field(default_factory=list)


class CommandRunner:
    """Abstraction for running shell commands (enables mocking in tests)."""

    def run(self, command: list[str]) -> tuple[int, str, str]:
        """Run a command and return (returncode, stdout, stderr).

        Args:
            command: Command to run as list of strings.

        Returns:
            Tuple of (return code, stdout, stderr).
        """
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return 1, "", "Command timed out"
        except FileNotFoundError:
            return 1, "", f"Command not found: {command[0]}"


class AuthVerifier:
    """Verifies cross-platform authentication configuration.

    Performs the 6 verification checks from the design doc:
    1. Azure AD app registration (interop-foundry-to-cs)
    2. Admin consent for API permissions
    3. Key Vault secrets
    4. Foundry agent connectivity (user RBAC access)
    5. Copilot Studio added agents
    6. Environment variables
    """

    # Required environment variables for Foundry -> CS communication
    FOUNDRY_TO_CS_ENV_VARS = [
        "COPILOTSTUDIOAGENT__TENANTID",
        "COPILOTSTUDIOAGENT__AGENTAPPID",
        "COPILOTSTUDIOAGENT__AGENTAPPSECRET",
        "COPILOTSTUDIOAGENT__ENVIRONMENTID",
        "COPILOTSTUDIOAGENT__SCHEMANAME",
    ]

    # Required base environment variables
    BASE_ENV_VARS = [
        "AZURE_TENANT_ID",
    ]

    # API permissions required for each app
    APP_PERMISSIONS = {
        "interop-foundry-to-cs": "https://api.powerplatform.com/.default",
    }

    def __init__(
        self,
        command_runner: CommandRunner | None = None,
        offline: bool = False,
        verbose: bool = False,
        foundry_config_path: Path | None = None,
        copilot_config_path: Path | None = None,
    ):
        """Initialize the verifier.

        Args:
            command_runner: Command runner for shell commands. Defaults to real runner.
            offline: If True, skip checks that require Azure CLI or network access.
            verbose: If True, show detailed output.
            foundry_config_path: Path to Foundry config.yaml.
            copilot_config_path: Path to Copilot Studio config.yaml.
        """
        self.command_runner = command_runner or CommandRunner()
        self.offline = offline
        self.verbose = verbose

        # Set default config paths relative to this file
        interop_root = Path(__file__).parent
        self.foundry_config_path = foundry_config_path or (
            interop_root / "foundry" / "config.yaml"
        )
        self.copilot_config_path = copilot_config_path or (
            interop_root / "copilot_studio" / "config.yaml"
        )

        self._config: VerificationConfig | None = None

    @property
    def config(self) -> VerificationConfig:
        """Get verification configuration, loading from files if needed."""
        if self._config is None:
            self._config = self._load_config()
        return self._config

    def _load_config(self) -> VerificationConfig:
        """Load configuration from config files and environment.

        Returns:
            VerificationConfig with loaded values.
        """
        config = VerificationConfig()

        # Load from environment
        config.tenant_id = os.environ.get("AZURE_TENANT_ID")
        config.foundry_to_cs_app_id = os.environ.get(
            "INTEROP_FOUNDRY_TO_CS_APP_ID"
        ) or os.environ.get("COPILOTSTUDIOAGENT__AGENTAPPID")
        config.copilot_studio_env_id = os.environ.get(
            "COPILOTSTUDIO_ENVIRONMENT_ID"
        ) or os.environ.get("COPILOTSTUDIOAGENT__ENVIRONMENTID")

        # Load Foundry config
        if self.foundry_config_path.exists():
            try:
                with open(self.foundry_config_path) as f:
                    foundry_config = yaml.safe_load(f)

                # Extract agent names
                agents = foundry_config.get("agents", {})
                config.foundry_agents = list(agents.keys())

                # Collect env vars required by agents
                for agent in agents.values():
                    env_vars = agent.get("env_vars", [])
                    config.foundry_env_vars.extend(env_vars)
            except yaml.YAMLError:
                pass

        # Load Copilot Studio config
        if self.copilot_config_path.exists():
            try:
                with open(self.copilot_config_path) as f:
                    cs_config = yaml.safe_load(f)

                # Extract agent names
                agents = cs_config.get("agents", {})
                config.copilot_studio_agents = list(agents.keys())
            except yaml.YAMLError:
                pass

        return config

    def run_all_checks(self) -> list[CheckResult]:
        """Run all verification checks.

        Returns:
            List of check results.
        """
        checks: list[tuple[str, Callable[[], CheckResult]]] = [
            ("Azure AD App Registrations", self.check_app_registrations),
            ("Admin Consent", self.check_admin_consent),
            ("Key Vault Secrets", self.check_keyvault_secrets),
            ("Foundry Agent Permissions", self.check_foundry_permissions),
            ("Copilot Studio Added Agents", self.check_connected_agents),
            ("Environment Variables", self.check_environment_variables),
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

    def check_app_registrations(self) -> CheckResult:
        """Check 1: Verify Azure AD app registrations exist.

        Returns:
            CheckResult with pass/fail status.
        """
        if self.offline:
            return CheckResult(
                name="Azure AD App Registrations",
                status=CheckStatus.SKIP,
                message="Skipped in offline mode",
                remediation="Run without --offline to check app registrations.",
            )

        # Check if az CLI is available
        returncode, _, stderr = self.command_runner.run(["az", "--version"])
        if returncode != 0:
            return CheckResult(
                name="Azure AD App Registrations",
                status=CheckStatus.FAIL,
                message="Azure CLI not available or not logged in",
                remediation="Install Azure CLI and run 'az login' to authenticate.",
            )

        missing_apps = []
        found_apps = []
        details = []

        # Check interop-foundry-to-cs app
        app_id = self.config.foundry_to_cs_app_id
        if app_id:
            returncode, stdout, _ = self.command_runner.run(
                ["az", "ad", "app", "show", "--id", app_id, "--output", "json"]
            )
            if returncode == 0:
                found_apps.append("interop-foundry-to-cs")
                details.append(f"interop-foundry-to-cs: Found (ID: {app_id})")
            else:
                missing_apps.append("interop-foundry-to-cs")
                details.append(f"interop-foundry-to-cs: Not found (ID: {app_id})")
        else:
            missing_apps.append("interop-foundry-to-cs")
            details.append(
                "interop-foundry-to-cs: App ID not configured "
                "(set INTEROP_FOUNDRY_TO_CS_APP_ID or COPILOTSTUDIOAGENT__AGENTAPPID)"
            )

        # Note: interop-cs-to-foundry app is no longer required.
        # Copilot Studio -> Foundry uses Microsoft Entra ID User Login (delegated auth).

        if missing_apps:
            return CheckResult(
                name="Azure AD App Registrations",
                status=CheckStatus.FAIL,
                message=f"Missing app registrations: {', '.join(missing_apps)}",
                remediation=(
                    "Register the missing Azure AD app in the Azure portal:\n"
                    "1. Go to Azure Portal > App registrations > New registration\n"
                    "2. Create 'interop-foundry-to-cs' with API permission: "
                    f"{self.APP_PERMISSIONS['interop-foundry-to-cs']}"
                ),
                details=details,
            )

        return CheckResult(
            name="Azure AD App Registrations",
            status=CheckStatus.PASS,
            message=f"All required apps found: {', '.join(found_apps)}",
            details=details,
        )

    def check_admin_consent(self) -> CheckResult:
        """Check 2: Verify admin consent granted for API permissions.

        Returns:
            CheckResult with pass/fail status.
        """
        if self.offline:
            return CheckResult(
                name="Admin Consent",
                status=CheckStatus.SKIP,
                message="Skipped in offline mode",
                remediation="Run without --offline to check admin consent.",
            )

        # This check requires Graph API access which is beyond basic az CLI
        # We'll check if service principals exist as a proxy for consent
        details = []
        issues = []

        for app_name, app_id_getter in [
            ("interop-foundry-to-cs", lambda: self.config.foundry_to_cs_app_id),
        ]:
            app_id = app_id_getter()
            if not app_id:
                issues.append(f"{app_name}: App ID not configured")
                continue

            # Check if service principal exists (created after consent)
            returncode, _, _ = self.command_runner.run(
                ["az", "ad", "sp", "show", "--id", app_id, "--output", "json"]
            )
            if returncode == 0:
                details.append(f"{app_name}: Service principal exists")
            else:
                issues.append(f"{app_name}: Service principal not found (consent may not be granted)")

        if issues:
            return CheckResult(
                name="Admin Consent",
                status=CheckStatus.WARN,
                message="Could not verify admin consent for all apps",
                remediation=(
                    "Grant admin consent in Azure Portal:\n"
                    "1. Go to App registrations > [app name] > API permissions\n"
                    "2. Click 'Grant admin consent for [tenant]'\n"
                    "3. Verify the Status shows 'Granted'"
                ),
                details=details + issues,
            )

        return CheckResult(
            name="Admin Consent",
            status=CheckStatus.PASS,
            message="Service principals exist for all apps (consent likely granted)",
            details=details,
        )

    def check_keyvault_secrets(self) -> CheckResult:
        """Check 3: Verify client secrets exist in Key Vault.

        Returns:
            CheckResult with pass/fail status.
        """
        if self.offline:
            return CheckResult(
                name="Key Vault Secrets",
                status=CheckStatus.SKIP,
                message="Skipped in offline mode",
                remediation="Run without --offline to check Key Vault secrets.",
            )

        details = []

        # Check if the secret is configured as a Key Vault reference or env var
        secret_value = os.environ.get("COPILOTSTUDIOAGENT__AGENTAPPSECRET", "")

        if secret_value.startswith("@Microsoft.KeyVault"):
            # It's a Key Vault reference - try to validate it
            # Extract the vault URL from the reference
            # Format: @Microsoft.KeyVault(SecretUri=https://vault.vault.azure.net/secrets/name)
            import re

            match = re.search(r"SecretUri=([^)]+)", secret_value)
            if match:
                secret_uri = match.group(1)
                details.append(f"Key Vault reference found: {secret_uri}")

                # Try to access the secret (requires az login with appropriate permissions)
                returncode, _, stderr = self.command_runner.run(
                    ["az", "keyvault", "secret", "show", "--id", secret_uri, "--query", "id"]
                )
                if returncode == 0:
                    return CheckResult(
                        name="Key Vault Secrets",
                        status=CheckStatus.PASS,
                        message="Key Vault secret accessible",
                        details=details,
                    )
                else:
                    return CheckResult(
                        name="Key Vault Secrets",
                        status=CheckStatus.WARN,
                        message="Key Vault secret configured but not accessible",
                        remediation=(
                            "Verify Key Vault access:\n"
                            "1. Ensure you have 'Key Vault Secrets User' role on the vault\n"
                            "2. Check the secret URI is correct\n"
                            "3. Run 'az login' with an account that has access"
                        ),
                        details=details + [f"Error: {stderr}"],
                    )
            else:
                return CheckResult(
                    name="Key Vault Secrets",
                    status=CheckStatus.FAIL,
                    message="Invalid Key Vault reference format",
                    remediation=(
                        "Use correct Key Vault reference format:\n"
                        "@Microsoft.KeyVault(SecretUri=https://your-vault.vault.azure.net/secrets/secret-name)"
                    ),
                    details=details,
                )
        elif secret_value:
            # Secret is in environment variable directly (ok for local dev)
            return CheckResult(
                name="Key Vault Secrets",
                status=CheckStatus.PASS,
                message="Client secret configured via environment variable (local dev mode)",
                details=["COPILOTSTUDIOAGENT__AGENTAPPSECRET is set directly"],
            )
        else:
            return CheckResult(
                name="Key Vault Secrets",
                status=CheckStatus.FAIL,
                message="Client secret not configured",
                remediation=(
                    "Configure the client secret:\n"
                    "For local dev: Set COPILOTSTUDIOAGENT__AGENTAPPSECRET environment variable\n"
                    "For production: Use Key Vault reference:\n"
                    "  COPILOTSTUDIOAGENT__AGENTAPPSECRET="
                    "@Microsoft.KeyVault(SecretUri=https://your-vault.vault.azure.net/secrets/cs-client-secret)"
                ),
                details=["COPILOTSTUDIOAGENT__AGENTAPPSECRET not set"],
            )

    def check_foundry_permissions(self) -> CheckResult:
        """Check 4: Verify Foundry agent connectivity.

        Copilot Studio connects to Foundry agents via Microsoft Entra ID User Login
        (delegated auth). No separate app registration is required — the signed-in
        user's RBAC permissions on the Foundry project grant access.

        Returns:
            CheckResult with pass/fail status.
        """
        if self.offline:
            return CheckResult(
                name="Foundry Agent Permissions",
                status=CheckStatus.SKIP,
                message="Skipped in offline mode",
                remediation="Run without --offline to check Foundry permissions.",
            )

        agents = self.config.foundry_agents
        if not agents:
            return CheckResult(
                name="Foundry Agent Permissions",
                status=CheckStatus.WARN,
                message="No Foundry agents found in config",
                remediation="Configure agents in interoperability/foundry/config.yaml",
                details=["foundry/config.yaml has no agents defined"],
            )

        # Copilot Studio -> Foundry uses Microsoft Entra ID User Login (delegated auth).
        # No app registration check needed. Manual verification of user RBAC is required.
        return CheckResult(
            name="Foundry Agent Permissions",
            status=CheckStatus.WARN,
            message=f"Manual verification required for {len(agents)} agents",
            remediation=(
                "Copilot Studio connects to Foundry via Microsoft Entra ID User Login.\n"
                "Verify the signed-in user has RBAC access to the Foundry project:\n"
                "  - Required role: Contributor or Cognitive Services User\n"
                "  - Verify in Azure Portal > Foundry project > Access Control (IAM)"
            ),
            details=[f"Agents to verify: {', '.join(agents)}"],
        )

    def check_connected_agents(self) -> CheckResult:
        """Check 5: Verify Copilot Studio added agents are configured.

        Returns:
            CheckResult with pass/fail status.
        """
        if self.offline:
            return CheckResult(
                name="Copilot Studio Added Agents",
                status=CheckStatus.SKIP,
                message="Skipped in offline mode",
                remediation="Run without --offline to check added agents.",
            )

        # This requires Copilot Studio API access which isn't available via az CLI
        # We can only verify the configuration references
        details = []

        cs_agents = self.config.copilot_studio_agents
        if not cs_agents:
            return CheckResult(
                name="Copilot Studio Added Agents",
                status=CheckStatus.WARN,
                message="No Copilot Studio agents found in config",
                remediation="Configure agents in interoperability/copilot_studio/config.yaml",
                details=["copilot_studio/config.yaml has no agents defined"],
            )

        # Check if travel_planning_parent agent (which uses added agents) is defined
        if "travel_planning_parent" not in cs_agents:
            return CheckResult(
                name="Copilot Studio Added Agents",
                status=CheckStatus.WARN,
                message="Travel Planning Parent agent not defined in config",
                remediation=(
                    "Add travel_planning_parent agent to copilot_studio/config.yaml with agents list"
                ),
                details=["travel_planning_parent agent required for Demo C"],
            )

        foundry_agents = self.config.foundry_agents
        details.append(f"Copilot Studio agents: {', '.join(cs_agents)}")
        details.append(f"Foundry agents (added agents): {', '.join(foundry_agents)}")

        # Manual verification required
        return CheckResult(
            name="Copilot Studio Added Agents",
            status=CheckStatus.WARN,
            message="Manual verification required in Copilot Studio portal",
            remediation=(
                "Add agents in Copilot Studio portal:\n"
                "1. Go to Travel Planning Parent Agent > Agents section > + Add agent\n"
                "2. Connect to external agent > Microsoft Foundry\n"
                "3. Add each Foundry agent with its Name, Description, and Agent Id"
            ),
            details=details,
        )

    def check_environment_variables(self) -> CheckResult:
        """Check 6: Verify required environment variables are set.

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

        # Check Foundry -> CS env vars (needed for Demo A and B)
        for var in self.FOUNDRY_TO_CS_ENV_VARS:
            if os.environ.get(var):
                set_vars.append(var)
                details.append(f"{var}: Set")
            else:
                missing_vars.append(var)
                details.append(f"{var}: NOT SET")

        # Check agent-specific env vars from config
        for var in self.config.foundry_env_vars:
            if var not in self.FOUNDRY_TO_CS_ENV_VARS:  # Don't duplicate
                if os.environ.get(var):
                    set_vars.append(var)
                    details.append(f"{var}: Set")
                else:
                    missing_vars.append(var)
                    details.append(f"{var}: NOT SET")

        if missing_vars:
            return CheckResult(
                name="Environment Variables",
                status=CheckStatus.FAIL,
                message=f"Missing {len(missing_vars)} required environment variables",
                remediation=(
                    "Set the missing environment variables:\n"
                    + "\n".join(f"  export {var}='<value>'" for var in missing_vars)
                    + "\n\nSee docs/interoperability-design.md for details."
                ),
                details=details,
            )

        return CheckResult(
            name="Environment Variables",
            status=CheckStatus.PASS,
            message=f"All {len(set_vars)} required environment variables are set",
            details=details,
        )


def print_results(results: list[CheckResult], verbose: bool = False) -> None:
    """Print verification results in a formatted table.

    Args:
        results: List of check results.
        verbose: If True, show detailed output.
    """
    print("\n" + "=" * 60)
    print("Cross-Platform Authentication Verification")
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
    """Run authentication verification checks.

    Returns:
        Exit code: 0 if all checks pass, 1 if any fail.
    """
    parser = argparse.ArgumentParser(
        description="Verify cross-platform authentication configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script verifies the 6 authentication checks from the design doc:

1. Azure AD App Registrations - Required app (interop-foundry-to-cs) exists
2. Admin Consent - API permissions are consented
3. Key Vault Secrets - Client secrets are accessible
4. Foundry Agent Permissions - User RBAC access to Foundry project
5. Copilot Studio Added Agents - Agents are configured
6. Environment Variables - Required vars are set

For more details, see docs/interoperability-design.md.
        """,
    )

    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip checks that require Azure CLI or network access",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output for each check",
    )
    parser.add_argument(
        "--foundry-config",
        type=str,
        help="Path to Foundry config.yaml",
    )
    parser.add_argument(
        "--copilot-config",
        type=str,
        help="Path to Copilot Studio config.yaml",
    )
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Also run agent name consistency validation (from validate_config.py)",
    )

    args = parser.parse_args()

    verifier = AuthVerifier(
        offline=args.offline,
        verbose=args.verbose,
        foundry_config_path=Path(args.foundry_config) if args.foundry_config else None,
        copilot_config_path=Path(args.copilot_config) if args.copilot_config else None,
    )

    results = verifier.run_all_checks()
    print_results(results, verbose=args.verbose)

    # Run config validation if requested
    config_failed = False
    if args.validate_config:
        from interoperability.validate_config import validate_all, print_results as print_config_results

        interop_root = Path(__file__).parent
        config_results = validate_all(interop_root)
        print_config_results(config_results)

        from interoperability.validate_config import ValidationStatus
        config_failed = any(r.status == ValidationStatus.FAIL for r in config_results)

    # Exit with error if any checks failed
    has_failures = any(r.status == CheckStatus.FAIL for r in results)
    return 1 if has_failures or config_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
