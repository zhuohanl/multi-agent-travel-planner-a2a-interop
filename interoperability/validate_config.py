"""
Agent name consistency validator for cross-platform interoperability.

Validates that agent names are consistent across:
- foundry/config.yaml (agent definitions)
- workflow YAML files (InvokeAzureAgent references)
- copilot_studio/config.yaml (connected_agents references)

This ensures that agent names match exactly to avoid runtime errors when
agents are invoked across platforms.

Usage:
    python validate_config.py                # Validate all configs
    python validate_config.py --all          # Same as above
    python validate_config.py --foundry-only # Only validate Foundry configs
    python validate_config.py --cs-only      # Only validate Copilot Studio configs

Design doc references:
    - Directory Structure - Example config.yaml: lines 1120-1200
    - Demo C: Connected Agents Config: lines 880-920
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class ValidationStatus(Enum):
    """Status of a validation check."""

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


@dataclass
class ValidationResult:
    """Result of a validation check."""

    status: ValidationStatus
    message: str
    details: list[str] = field(default_factory=list)
    file_locations: list[str] = field(default_factory=list)
    suggested_fixes: list[str] = field(default_factory=list)


@dataclass
class AgentReference:
    """Reference to an agent in a config file."""

    name: str
    file_path: str
    line_number: int | None = None
    context: str = ""  # e.g., "foundry_config", "workflow", "connected_agents"


@dataclass
class ConfigValidationContext:
    """Context for config validation."""

    # Agents defined in foundry/config.yaml
    foundry_agents: list[AgentReference] = field(default_factory=list)

    # Agents referenced in workflow YAML files
    workflow_agent_refs: list[AgentReference] = field(default_factory=list)

    # Agents listed in copilot_studio/config.yaml connected_agents
    connected_agents: list[AgentReference] = field(default_factory=list)

    # Agents defined in copilot_studio/config.yaml
    cs_agents: list[AgentReference] = field(default_factory=list)


def parse_foundry_config(config_path: Path) -> list[AgentReference]:
    """Parse foundry/config.yaml to extract agent names.

    Args:
        config_path: Path to foundry/config.yaml.

    Returns:
        List of AgentReference objects for each defined agent.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        yaml.YAMLError: If YAML parsing fails.
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        content = f.read()
        config = yaml.safe_load(content)

    agents = []
    agents_section = config.get("agents", {})

    # Find line numbers for each agent
    lines = content.split("\n")
    for agent_name in agents_section:
        line_number = None
        # Search for the agent name in the YAML
        for i, line in enumerate(lines, 1):
            # Match agent name at start of line (allowing for indentation)
            if re.match(rf"^\s+{re.escape(agent_name)}:\s*$", line) or re.match(
                rf"^\s+{re.escape(agent_name)}:\s+", line
            ):
                line_number = i
                break

        agents.append(
            AgentReference(
                name=agent_name,
                file_path=str(config_path),
                line_number=line_number,
                context="foundry_config",
            )
        )

    return agents


def parse_workflow_yaml(workflow_dir: Path) -> list[AgentReference]:
    """Parse workflow YAML files to extract InvokeAzureAgent references.

    Args:
        workflow_dir: Path to workflow directory containing YAML files.

    Returns:
        List of AgentReference objects for each agent referenced in workflows.
    """
    agent_refs = []

    if not workflow_dir.exists():
        return agent_refs

    # Find all YAML files in workflow directories
    yaml_files = list(workflow_dir.glob("**/*.yaml")) + list(
        workflow_dir.glob("**/*.yml")
    )

    for yaml_file in yaml_files:
        try:
            with open(yaml_file) as f:
                content = f.read()

            # Parse YAML to find InvokeAzureAgent references
            # The format is:
            # - kind: InvokeAzureAgent
            #   agent:
            #     name: <agent_name>

            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                # Look for agent name references in InvokeAzureAgent blocks
                # Format: name: <agent_name> (within agent: block)
                match = re.match(r"^\s+name:\s*(\S+)\s*$", line)
                if match:
                    agent_name = match.group(1)
                    # Verify this is within an InvokeAzureAgent context
                    # by checking previous lines for "kind: InvokeAzureAgent"
                    context_lines = lines[max(0, i - 10) : i]
                    is_invoke_agent = any(
                        "kind: InvokeAzureAgent" in cl or "kind:InvokeAzureAgent" in cl
                        for cl in context_lines
                    )
                    if is_invoke_agent:
                        agent_refs.append(
                            AgentReference(
                                name=agent_name,
                                file_path=str(yaml_file),
                                line_number=i,
                                context="workflow",
                            )
                        )
        except yaml.YAMLError:
            # Skip files that can't be parsed
            continue
        except Exception:
            continue

    return agent_refs


def parse_connected_agents(config_path: Path) -> tuple[list[AgentReference], list[AgentReference]]:
    """Parse copilot_studio/config.yaml to extract agent definitions and connected_agents.

    Args:
        config_path: Path to copilot_studio/config.yaml.

    Returns:
        Tuple of (cs_agents, connected_agents) lists.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        yaml.YAMLError: If YAML parsing fails.
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        content = f.read()

    config = yaml.safe_load(content)
    if config is None:
        config = {}

    lines = content.split("\n")
    cs_agents = []
    connected_agents = []

    agents_section = config.get("agents", {})

    for agent_name, agent_config in agents_section.items():
        # Find line number for agent definition
        line_number = None
        for i, line in enumerate(lines, 1):
            if re.match(rf"^\s+{re.escape(agent_name)}:\s*$", line) or re.match(
                rf"^\s+{re.escape(agent_name)}:\s+", line
            ):
                line_number = i
                break

        cs_agents.append(
            AgentReference(
                name=agent_name,
                file_path=str(config_path),
                line_number=line_number,
                context="cs_config",
            )
        )

        # Extract connected_agents list if present
        connected = agent_config.get("connected_agents", [])
        if connected:
            # Find line numbers for connected agents
            in_connected_section = False
            for i, line in enumerate(lines, 1):
                if "connected_agents:" in line:
                    in_connected_section = True
                    continue
                if in_connected_section:
                    # Check if we've left the connected_agents section
                    if re.match(r"^\s+\w+:", line) and "- " not in line:
                        in_connected_section = False
                        continue
                    # Look for agent references (- agent_name or - agent_name  # comment)
                    match = re.match(r"^\s+-\s+(\S+)", line)
                    if match:
                        ref_name = match.group(1)
                        if ref_name in connected:
                            connected_agents.append(
                                AgentReference(
                                    name=ref_name,
                                    file_path=str(config_path),
                                    line_number=i,
                                    context="connected_agents",
                                )
                            )

    return cs_agents, connected_agents


def parse_workflow_config_agents(config_path: Path) -> list[AgentReference]:
    """Parse foundry/config.yaml workflows section to extract agent lists.

    Args:
        config_path: Path to foundry/config.yaml.

    Returns:
        List of AgentReference objects for agents listed in workflow definitions.
    """
    if not config_path.exists():
        return []

    with open(config_path) as f:
        content = f.read()
        config = yaml.safe_load(content)

    agent_refs = []
    workflows = config.get("workflows", {})
    lines = content.split("\n")

    for workflow_name, workflow_config in workflows.items():
        agents_list = workflow_config.get("agents", [])
        if agents_list:
            # Find line numbers
            for agent_name in agents_list:
                for i, line in enumerate(lines, 1):
                    if agent_name in line and "agents:" in lines[i - 2 : i + 1][0] if i > 1 else False:
                        agent_refs.append(
                            AgentReference(
                                name=agent_name,
                                file_path=str(config_path),
                                line_number=i,
                                context=f"workflow_config:{workflow_name}",
                            )
                        )
                        break
                else:
                    # Add without line number if not found
                    agent_refs.append(
                        AgentReference(
                            name=agent_name,
                            file_path=str(config_path),
                            line_number=None,
                            context=f"workflow_config:{workflow_name}",
                        )
                    )

    return agent_refs


def validate_agent_name_consistency(context: ConfigValidationContext) -> list[ValidationResult]:
    """Validate that agent names are consistent across all config sources.

    Args:
        context: ConfigValidationContext with parsed agent references.

    Returns:
        List of ValidationResult objects.
    """
    results = []

    # Get sets of agent names from each source
    foundry_names = {ref.name for ref in context.foundry_agents}
    workflow_names = {ref.name for ref in context.workflow_agent_refs}
    connected_names = {ref.name for ref in context.connected_agents}
    cs_names = {ref.name for ref in context.cs_agents}

    # Check 1: Workflow agent references should match Foundry definitions
    if workflow_names:
        missing_in_foundry = workflow_names - foundry_names
        if missing_in_foundry:
            # Find specific references for error reporting
            file_locations = []
            for ref in context.workflow_agent_refs:
                if ref.name in missing_in_foundry:
                    loc = f"{ref.file_path}"
                    if ref.line_number:
                        loc += f":{ref.line_number}"
                    file_locations.append(f"{loc} - agent '{ref.name}'")

            results.append(
                ValidationResult(
                    status=ValidationStatus.FAIL,
                    message=f"Workflow references agents not defined in Foundry config: {', '.join(sorted(missing_in_foundry))}",
                    details=[
                        "These agents are referenced in workflow YAML but not defined in foundry/config.yaml",
                        "This will cause runtime errors when the workflow tries to invoke these agents",
                    ],
                    file_locations=file_locations,
                    suggested_fixes=[
                        f"Add agent '{name}' to foundry/config.yaml agents section"
                        for name in sorted(missing_in_foundry)
                    ],
                )
            )
        else:
            results.append(
                ValidationResult(
                    status=ValidationStatus.PASS,
                    message="All workflow agent references match Foundry definitions",
                    details=[f"Verified {len(workflow_names)} agent references"],
                )
            )

    # Check 2: Connected agents should match Foundry definitions (except internal CS agents)
    if connected_names:
        # Filter out internal CS agents (like 'weather' which is a CS agent, not Foundry)
        external_connected = connected_names - cs_names
        missing_in_foundry = external_connected - foundry_names

        if missing_in_foundry:
            file_locations = []
            for ref in context.connected_agents:
                if ref.name in missing_in_foundry:
                    loc = f"{ref.file_path}"
                    if ref.line_number:
                        loc += f":{ref.line_number}"
                    file_locations.append(f"{loc} - connected agent '{ref.name}'")

            results.append(
                ValidationResult(
                    status=ValidationStatus.FAIL,
                    message=f"Connected agents reference Foundry agents not defined: {', '.join(sorted(missing_in_foundry))}",
                    details=[
                        "These connected agents in Copilot Studio config reference Foundry agents that don't exist",
                        "Copilot Studio will fail to route to these agents",
                    ],
                    file_locations=file_locations,
                    suggested_fixes=[
                        f"Add agent '{name}' to foundry/config.yaml or remove from connected_agents"
                        for name in sorted(missing_in_foundry)
                    ],
                )
            )
        else:
            results.append(
                ValidationResult(
                    status=ValidationStatus.PASS,
                    message="All connected agent references match Foundry definitions",
                    details=[
                        f"Verified {len(external_connected)} external connected agents",
                        f"Skipped {len(connected_names - external_connected)} internal CS agents",
                    ],
                )
            )

    # Check 3: Foundry agents with type:native should have corresponding agent.yaml files
    for ref in context.foundry_agents:
        # This check is informational - agent.yaml validation is handled by deploy.py
        pass

    # Check 4: Warn about unused Foundry agents (not referenced anywhere)
    all_refs = workflow_names | connected_names
    unused_agents = foundry_names - all_refs
    # Exclude workflow-support agents that might only be used internally
    internal_agents = {"aggregator", "route", "weather-proxy"}
    truly_unused = unused_agents - internal_agents

    if truly_unused:
        results.append(
            ValidationResult(
                status=ValidationStatus.WARN,
                message=f"Foundry agents not referenced in workflows or connected_agents: {', '.join(sorted(truly_unused))}",
                details=[
                    "These agents are defined but not used in any workflow or connected_agents config",
                    "This may be intentional (e.g., agents used only via direct API calls)",
                ],
            )
        )

    return results


def validate_foundry_only(interop_root: Path) -> list[ValidationResult]:
    """Validate only Foundry-related configs.

    Args:
        interop_root: Path to interoperability/ directory.

    Returns:
        List of ValidationResult objects.
    """
    results = []
    context = ConfigValidationContext()

    # Parse Foundry config
    foundry_config = interop_root / "foundry" / "config.yaml"
    try:
        context.foundry_agents = parse_foundry_config(foundry_config)
        results.append(
            ValidationResult(
                status=ValidationStatus.PASS,
                message=f"Parsed {len(context.foundry_agents)} agents from foundry/config.yaml",
            )
        )
    except FileNotFoundError as e:
        results.append(
            ValidationResult(
                status=ValidationStatus.FAIL,
                message=f"Foundry config not found: {e}",
            )
        )
        return results
    except yaml.YAMLError as e:
        results.append(
            ValidationResult(
                status=ValidationStatus.FAIL,
                message=f"Foundry config YAML parse error: {e}",
            )
        )
        return results

    # Parse workflow configs from foundry/config.yaml
    workflow_config_refs = parse_workflow_config_agents(foundry_config)
    context.workflow_agent_refs.extend(workflow_config_refs)

    # Parse workflow YAML files
    workflow_dirs = [
        interop_root / "foundry" / "workflows" / "discovery_workflow_procode",
        interop_root / "foundry" / "workflows" / "discovery_workflow_declarative",
    ]

    for workflow_dir in workflow_dirs:
        refs = parse_workflow_yaml(workflow_dir)
        context.workflow_agent_refs.extend(refs)

    # Validate consistency
    consistency_results = validate_agent_name_consistency(context)
    results.extend(consistency_results)

    return results


def validate_cs_only(interop_root: Path) -> list[ValidationResult]:
    """Validate only Copilot Studio-related configs.

    Args:
        interop_root: Path to interoperability/ directory.

    Returns:
        List of ValidationResult objects.
    """
    results = []
    context = ConfigValidationContext()

    # Parse Foundry config (needed for cross-reference checking)
    foundry_config = interop_root / "foundry" / "config.yaml"
    try:
        context.foundry_agents = parse_foundry_config(foundry_config)
    except (FileNotFoundError, yaml.YAMLError):
        # Continue without Foundry agents - will show warnings
        pass

    # Parse Copilot Studio config
    cs_config = interop_root / "copilot_studio" / "config.yaml"
    try:
        context.cs_agents, context.connected_agents = parse_connected_agents(cs_config)
        results.append(
            ValidationResult(
                status=ValidationStatus.PASS,
                message=f"Parsed {len(context.cs_agents)} CS agents and {len(context.connected_agents)} connected agent references",
            )
        )
    except FileNotFoundError as e:
        results.append(
            ValidationResult(
                status=ValidationStatus.FAIL,
                message=f"Copilot Studio config not found: {e}",
            )
        )
        return results
    except yaml.YAMLError as e:
        results.append(
            ValidationResult(
                status=ValidationStatus.FAIL,
                message=f"Copilot Studio config YAML parse error: {e}",
            )
        )
        return results

    # Validate consistency
    consistency_results = validate_agent_name_consistency(context)
    results.extend(consistency_results)

    return results


def validate_all(interop_root: Path) -> list[ValidationResult]:
    """Validate all configs for cross-platform consistency.

    Args:
        interop_root: Path to interoperability/ directory.

    Returns:
        List of ValidationResult objects.
    """
    results = []
    context = ConfigValidationContext()

    # Parse Foundry config
    foundry_config = interop_root / "foundry" / "config.yaml"
    try:
        context.foundry_agents = parse_foundry_config(foundry_config)
        results.append(
            ValidationResult(
                status=ValidationStatus.PASS,
                message=f"Parsed {len(context.foundry_agents)} agents from foundry/config.yaml",
                details=[f"Agents: {', '.join(ref.name for ref in context.foundry_agents)}"],
            )
        )
    except FileNotFoundError as e:
        results.append(
            ValidationResult(
                status=ValidationStatus.FAIL,
                message=f"Foundry config not found: {e}",
            )
        )
    except yaml.YAMLError as e:
        results.append(
            ValidationResult(
                status=ValidationStatus.FAIL,
                message=f"Foundry config YAML parse error: {e}",
            )
        )

    # Parse workflow configs from foundry/config.yaml
    workflow_config_refs = parse_workflow_config_agents(foundry_config)
    context.workflow_agent_refs.extend(workflow_config_refs)

    # Parse workflow YAML files
    workflow_dirs = [
        interop_root / "foundry" / "workflows" / "discovery_workflow_procode",
        interop_root / "foundry" / "workflows" / "discovery_workflow_declarative",
    ]

    for workflow_dir in workflow_dirs:
        refs = parse_workflow_yaml(workflow_dir)
        context.workflow_agent_refs.extend(refs)

    if context.workflow_agent_refs:
        results.append(
            ValidationResult(
                status=ValidationStatus.PASS,
                message=f"Parsed {len(context.workflow_agent_refs)} workflow agent references",
            )
        )

    # Parse Copilot Studio config
    cs_config = interop_root / "copilot_studio" / "config.yaml"
    try:
        context.cs_agents, context.connected_agents = parse_connected_agents(cs_config)
        results.append(
            ValidationResult(
                status=ValidationStatus.PASS,
                message=f"Parsed {len(context.cs_agents)} CS agents and {len(context.connected_agents)} connected agent references",
                details=[
                    f"CS agents: {', '.join(ref.name for ref in context.cs_agents)}",
                    f"Connected agents: {', '.join(ref.name for ref in context.connected_agents)}",
                ],
            )
        )
    except FileNotFoundError as e:
        results.append(
            ValidationResult(
                status=ValidationStatus.FAIL,
                message=f"Copilot Studio config not found: {e}",
            )
        )
    except yaml.YAMLError as e:
        results.append(
            ValidationResult(
                status=ValidationStatus.FAIL,
                message=f"Copilot Studio config YAML parse error: {e}",
            )
        )

    # Validate consistency
    consistency_results = validate_agent_name_consistency(context)
    results.extend(consistency_results)

    return results


def print_results(results: list[ValidationResult]) -> None:
    """Print validation results in a formatted output.

    Args:
        results: List of ValidationResult objects.
    """
    print("\n" + "=" * 60)
    print("Agent Name Consistency Validation")
    print("=" * 60 + "\n")

    status_symbols = {
        ValidationStatus.PASS: "\u2713",  # checkmark
        ValidationStatus.FAIL: "\u2717",  # X mark
        ValidationStatus.WARN: "!",
    }

    for result in results:
        symbol = status_symbols[result.status]
        status_str = result.status.value.upper()
        print(f"[{symbol}] {status_str}: {result.message}")

        if result.details:
            for detail in result.details:
                print(f"    {detail}")

        if result.file_locations:
            print("\n    File locations:")
            for loc in result.file_locations:
                print(f"      - {loc}")

        if result.suggested_fixes:
            print("\n    Suggested fixes:")
            for fix in result.suggested_fixes:
                print(f"      - {fix}")

        print()

    # Summary
    passed = sum(1 for r in results if r.status == ValidationStatus.PASS)
    failed = sum(1 for r in results if r.status == ValidationStatus.FAIL)
    warned = sum(1 for r in results if r.status == ValidationStatus.WARN)

    print("-" * 60)
    print(f"Summary: {passed} passed, {failed} failed, {warned} warnings")
    print("-" * 60)

    if failed > 0:
        print("\n[!] Fix the failed checks before deployment.")
    elif warned > 0:
        print("\n[!] Review warnings for potential issues.")
    else:
        print("\n[OK] All checks passed!")


def main() -> int:
    """Run agent name consistency validation.

    Returns:
        Exit code: 0 if all checks pass, 1 if any fail.
    """
    parser = argparse.ArgumentParser(
        description="Validate agent name consistency across config files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script validates that agent names are consistent across:

1. foundry/config.yaml - Agent definitions
2. Workflow YAML files - InvokeAzureAgent references
3. copilot_studio/config.yaml - Connected agents

Mismatches can cause runtime errors when agents are invoked.

For more details, see docs/interoperability-design.md.
        """,
    )

    parser.add_argument(
        "--all",
        action="store_true",
        default=True,
        help="Validate all configs (default)",
    )
    parser.add_argument(
        "--foundry-only",
        action="store_true",
        help="Only validate Foundry configs",
    )
    parser.add_argument(
        "--cs-only",
        action="store_true",
        help="Only validate Copilot Studio configs",
    )
    parser.add_argument(
        "--interop-root",
        type=str,
        help="Path to interoperability/ directory",
    )

    args = parser.parse_args()

    # Determine interop root
    if args.interop_root:
        interop_root = Path(args.interop_root)
    else:
        interop_root = Path(__file__).parent

    # Run appropriate validation
    if args.foundry_only:
        results = validate_foundry_only(interop_root)
    elif args.cs_only:
        results = validate_cs_only(interop_root)
    else:
        results = validate_all(interop_root)

    print_results(results)

    # Exit with error if any checks failed
    has_failures = any(r.status == ValidationStatus.FAIL for r in results)
    return 1 if has_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
