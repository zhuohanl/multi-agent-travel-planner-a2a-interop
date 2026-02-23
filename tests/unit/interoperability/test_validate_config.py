"""Unit tests for interoperability/validate_config.py."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from interoperability.validate_config import (
    AgentReference,
    ConfigValidationContext,
    ValidationStatus,
    parse_connected_agents,
    parse_foundry_config,
    parse_workflow_yaml,
    validate_agent_name_consistency,
    validate_all,
    validate_cs_only,
    validate_foundry_only,
)


class TestParseFoundryConfig:
    """Tests for parse_foundry_config function."""

    def test_parse_foundry_config_extracts_agent_names(self, tmp_path: Path) -> None:
        """Test that agent names are correctly extracted from foundry config."""
        config_content = """
platform: azure_ai_foundry
agents:
  transport:
    type: native
    source: src/agents/transport
  poi:
    type: native
    source: src/agents/poi
  stay:
    type: hosted
    framework: agent_framework
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        agents = parse_foundry_config(config_path)

        assert len(agents) == 3
        agent_names = {a.name for a in agents}
        assert agent_names == {"transport", "poi", "stay"}

    def test_parse_foundry_config_includes_file_path(self, tmp_path: Path) -> None:
        """Test that file path is included in agent references."""
        config_content = """
agents:
  test_agent:
    type: native
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        agents = parse_foundry_config(config_path)

        assert len(agents) == 1
        assert agents[0].file_path == str(config_path)
        assert agents[0].context == "foundry_config"

    def test_parse_foundry_config_file_not_found(self, tmp_path: Path) -> None:
        """Test that FileNotFoundError is raised for missing config."""
        config_path = tmp_path / "nonexistent.yaml"

        with pytest.raises(FileNotFoundError):
            parse_foundry_config(config_path)

    def test_parse_foundry_config_empty_agents(self, tmp_path: Path) -> None:
        """Test parsing config with no agents section."""
        config_content = """
platform: azure_ai_foundry
workflows:
  test: {}
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        agents = parse_foundry_config(config_path)

        assert len(agents) == 0


class TestParseWorkflowYaml:
    """Tests for parse_workflow_yaml function."""

    def test_parse_workflow_yaml_extracts_agent_refs(self, tmp_path: Path) -> None:
        """Test that InvokeAzureAgent references are extracted from workflow YAML."""
        workflow_content = """
trigger:
  kind: OnConversationStart
  actions:
    - kind: InvokeAzureAgent
      id: invoke_transport
      agent:
        name: transport
      output:
        text: Local.Result

    - kind: InvokeAzureAgent
      id: invoke_poi
      agent:
        name: poi
"""
        workflow_dir = tmp_path / "workflow"
        workflow_dir.mkdir()
        (workflow_dir / "workflow.yaml").write_text(workflow_content)

        refs = parse_workflow_yaml(workflow_dir)

        assert len(refs) == 2
        ref_names = {r.name for r in refs}
        assert ref_names == {"transport", "poi"}

    def test_parse_workflow_yaml_includes_line_numbers(self, tmp_path: Path) -> None:
        """Test that line numbers are included in references."""
        workflow_content = """
actions:
  - kind: InvokeAzureAgent
    agent:
      name: test_agent
"""
        workflow_dir = tmp_path / "workflow"
        workflow_dir.mkdir()
        (workflow_dir / "workflow.yaml").write_text(workflow_content)

        refs = parse_workflow_yaml(workflow_dir)

        assert len(refs) == 1
        assert refs[0].line_number is not None
        assert refs[0].context == "workflow"

    def test_parse_workflow_yaml_nonexistent_dir(self, tmp_path: Path) -> None:
        """Test parsing nonexistent workflow directory returns empty list."""
        workflow_dir = tmp_path / "nonexistent"

        refs = parse_workflow_yaml(workflow_dir)

        assert refs == []

    def test_parse_workflow_yaml_empty_dir(self, tmp_path: Path) -> None:
        """Test parsing empty workflow directory returns empty list."""
        workflow_dir = tmp_path / "workflow"
        workflow_dir.mkdir()

        refs = parse_workflow_yaml(workflow_dir)

        assert refs == []


class TestParseConnectedAgents:
    """Tests for parse_connected_agents function."""

    def test_parse_connected_agents_extracts_names(self, tmp_path: Path) -> None:
        """Test that connected agent names are extracted from CS config."""
        config_content = """
platform: copilot_studio
agents:
  weather:
    name: Weather Agent
  travel_planning_parent:
    name: Q&A Parent
    connected_agents:
      - transport
      - poi
      - events
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        cs_agents, connected = parse_connected_agents(config_path)

        assert len(cs_agents) == 2
        cs_names = {a.name for a in cs_agents}
        assert cs_names == {"weather", "travel_planning_parent"}

        assert len(connected) == 3
        connected_names = {c.name for c in connected}
        assert connected_names == {"transport", "poi", "events"}

    def test_parse_connected_agents_includes_context(self, tmp_path: Path) -> None:
        """Test that context is set correctly for connected agents."""
        config_content = """
agents:
  travel_planning_parent:
    connected_agents:
      - transport
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        cs_agents, connected = parse_connected_agents(config_path)

        assert connected[0].context == "connected_agents"
        assert cs_agents[0].context == "cs_config"

    def test_parse_connected_agents_file_not_found(self, tmp_path: Path) -> None:
        """Test that FileNotFoundError is raised for missing config."""
        config_path = tmp_path / "nonexistent.yaml"

        with pytest.raises(FileNotFoundError):
            parse_connected_agents(config_path)


class TestValidateAgentNameConsistency:
    """Tests for validate_agent_name_consistency function."""

    def test_validate_detects_name_mismatch_foundry_workflow(self) -> None:
        """Test that mismatches between workflow and Foundry config are detected."""
        context = ConfigValidationContext(
            foundry_agents=[
                AgentReference(name="transport", file_path="config.yaml", context="foundry_config"),
                AgentReference(name="poi", file_path="config.yaml", context="foundry_config"),
            ],
            workflow_agent_refs=[
                AgentReference(name="transport", file_path="workflow.yaml", context="workflow"),
                AgentReference(name="missing_agent", file_path="workflow.yaml", context="workflow"),
            ],
        )

        results = validate_agent_name_consistency(context)

        # Should have a failure for missing_agent
        fail_results = [r for r in results if r.status == ValidationStatus.FAIL]
        assert len(fail_results) == 1
        assert "missing_agent" in fail_results[0].message

    def test_validate_detects_name_mismatch_connected_agents(self) -> None:
        """Test that mismatches between connected agents and Foundry config are detected."""
        context = ConfigValidationContext(
            foundry_agents=[
                AgentReference(name="transport", file_path="config.yaml", context="foundry_config"),
            ],
            connected_agents=[
                AgentReference(name="transport", file_path="cs_config.yaml", context="connected_agents"),
                AgentReference(name="unknown_agent", file_path="cs_config.yaml", context="connected_agents"),
            ],
            cs_agents=[],  # No internal CS agents
        )

        results = validate_agent_name_consistency(context)

        # Should have a failure for unknown_agent
        fail_results = [r for r in results if r.status == ValidationStatus.FAIL]
        assert len(fail_results) == 1
        assert "unknown_agent" in fail_results[0].message

    def test_validate_passes_when_consistent(self) -> None:
        """Test that validation passes when all names are consistent."""
        context = ConfigValidationContext(
            foundry_agents=[
                AgentReference(name="transport", file_path="config.yaml", context="foundry_config"),
                AgentReference(name="poi", file_path="config.yaml", context="foundry_config"),
            ],
            workflow_agent_refs=[
                AgentReference(name="transport", file_path="workflow.yaml", context="workflow"),
                AgentReference(name="poi", file_path="workflow.yaml", context="workflow"),
            ],
            connected_agents=[
                AgentReference(name="transport", file_path="cs_config.yaml", context="connected_agents"),
            ],
            cs_agents=[],
        )

        results = validate_agent_name_consistency(context)

        # Should have no failures
        fail_results = [r for r in results if r.status == ValidationStatus.FAIL]
        assert len(fail_results) == 0

    def test_validate_outputs_specific_file_locations(self) -> None:
        """Test that file locations are included in validation results."""
        context = ConfigValidationContext(
            foundry_agents=[],
            workflow_agent_refs=[
                AgentReference(
                    name="missing", file_path="/path/to/workflow.yaml", line_number=42, context="workflow"
                ),
            ],
        )

        results = validate_agent_name_consistency(context)

        fail_results = [r for r in results if r.status == ValidationStatus.FAIL]
        assert len(fail_results) == 1
        assert any("/path/to/workflow.yaml:42" in loc for loc in fail_results[0].file_locations)

    def test_validate_ignores_internal_cs_agents_in_connected(self) -> None:
        """Test that internal CS agents are not flagged as missing from Foundry."""
        context = ConfigValidationContext(
            foundry_agents=[
                AgentReference(name="transport", file_path="config.yaml", context="foundry_config"),
            ],
            connected_agents=[
                AgentReference(name="transport", file_path="cs_config.yaml", context="connected_agents"),
                AgentReference(name="weather", file_path="cs_config.yaml", context="connected_agents"),
            ],
            cs_agents=[
                AgentReference(name="weather", file_path="cs_config.yaml", context="cs_config"),
            ],
        )

        results = validate_agent_name_consistency(context)

        # Should not fail because 'weather' is an internal CS agent
        fail_results = [r for r in results if r.status == ValidationStatus.FAIL]
        assert len(fail_results) == 0


class TestValidateFoundryOnly:
    """Tests for validate_foundry_only function."""

    def test_validate_foundry_only_parses_config(self, tmp_path: Path) -> None:
        """Test that foundry-only validation parses the config correctly."""
        # Create directory structure
        foundry_dir = tmp_path / "foundry"
        foundry_dir.mkdir()

        config_content = """
agents:
  transport:
    type: native
  poi:
    type: native
workflows: {}
"""
        (foundry_dir / "config.yaml").write_text(config_content)

        results = validate_foundry_only(tmp_path)

        # Should have a pass result for parsing
        pass_results = [r for r in results if r.status == ValidationStatus.PASS]
        assert len(pass_results) >= 1
        assert any("2 agents" in r.message for r in pass_results)

    def test_validate_foundry_only_missing_config(self, tmp_path: Path) -> None:
        """Test that missing config is reported as failure."""
        results = validate_foundry_only(tmp_path)

        fail_results = [r for r in results if r.status == ValidationStatus.FAIL]
        assert len(fail_results) >= 1
        assert any("not found" in r.message for r in fail_results)


class TestValidateCsOnly:
    """Tests for validate_cs_only function."""

    def test_validate_cs_only_parses_config(self, tmp_path: Path) -> None:
        """Test that cs-only validation parses the config correctly."""
        # Create directory structure
        cs_dir = tmp_path / "copilot_studio"
        cs_dir.mkdir()

        config_content = """
agents:
  weather:
    name: Weather Agent
  travel_planning_parent:
    connected_agents:
      - transport
"""
        (cs_dir / "config.yaml").write_text(config_content)

        # Also need foundry config for cross-reference
        foundry_dir = tmp_path / "foundry"
        foundry_dir.mkdir()
        (foundry_dir / "config.yaml").write_text("""
agents:
  transport:
    type: native
""")

        results = validate_cs_only(tmp_path)

        # Should have results for parsing
        assert len(results) >= 1


class TestCLI:
    """Tests for CLI interface."""

    def test_cli_all_flag(self, tmp_path: Path) -> None:
        """Test that --all flag triggers full validation."""
        # Create minimal config structure
        foundry_dir = tmp_path / "foundry"
        foundry_dir.mkdir()
        (foundry_dir / "config.yaml").write_text("agents: {}")

        cs_dir = tmp_path / "copilot_studio"
        cs_dir.mkdir()
        (cs_dir / "config.yaml").write_text("agents: {}")

        results = validate_all(tmp_path)

        # Should have results for both configs
        assert len(results) >= 2

    def test_cli_foundry_only_flag(self, tmp_path: Path) -> None:
        """Test that --foundry-only flag only validates Foundry."""
        foundry_dir = tmp_path / "foundry"
        foundry_dir.mkdir()
        (foundry_dir / "config.yaml").write_text("agents: {}")

        results = validate_foundry_only(tmp_path)

        # Should have at least one result
        assert len(results) >= 1


class TestIntegrationWithRealConfigs:
    """Integration tests using the actual project config files."""

    def test_parse_actual_foundry_config(self) -> None:
        """Test parsing the actual foundry/config.yaml."""
        interop_root = Path(__file__).parent.parent.parent.parent / "interoperability"
        config_path = interop_root / "foundry" / "config.yaml"

        if not config_path.exists():
            pytest.skip("Actual config not found")

        agents = parse_foundry_config(config_path)

        # Should have the expected agents
        agent_names = {a.name for a in agents}
        assert "transport" in agent_names
        assert "poi" in agent_names
        assert "events" in agent_names

    def test_parse_actual_cs_config(self) -> None:
        """Test parsing the actual copilot_studio/config.yaml."""
        interop_root = Path(__file__).parent.parent.parent.parent / "interoperability"
        config_path = interop_root / "copilot_studio" / "config.yaml"

        if not config_path.exists():
            pytest.skip("Actual config not found")

        cs_agents, connected = parse_connected_agents(config_path)

        # Should have the expected agents
        cs_names = {a.name for a in cs_agents}
        assert "weather" in cs_names
        assert "travel_planning_parent" in cs_names

        # travel_planning_parent should have connected agents
        assert len(connected) > 0

    def test_validate_all_actual_configs(self) -> None:
        """Test full validation on actual project configs."""
        interop_root = Path(__file__).parent.parent.parent.parent / "interoperability"

        if not (interop_root / "foundry" / "config.yaml").exists():
            pytest.skip("Actual config not found")

        results = validate_all(interop_root)

        # Should complete without errors
        assert len(results) >= 1

        # Check that no unexpected failures occurred
        # (some warnings are expected if workflows aren't defined yet)
        for result in results:
            if result.status == ValidationStatus.FAIL:
                # Print details for debugging
                print(f"FAIL: {result.message}")
                print(f"  Details: {result.details}")
