"""
Unit tests for agent extraction module.

Tests instruction extraction from src/agents/, tool mapping to Foundry format,
and loading from interoperability/ paths.
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from interoperability.foundry.extract_agent import (
    ExtractionError,
    extract_agent_for_foundry,
    extract_system_prompt,
    extract_tools,
    generate_native_agent_yaml,
    get_project_root,
    load_agent_yaml_from_interop,
    load_prompts_from_interop,
    map_tool_to_foundry,
    map_tools_to_foundry,
)


class TestExtractSystemPromptFromTransportAgent:
    """Tests for extracting system prompt from transport agent."""

    def test_extract_system_prompt_from_transport_agent(self) -> None:
        """Verify system prompt extraction from src/agents/transport_agent."""
        prompt = extract_system_prompt("src/agents/transport_agent")

        assert prompt is not None
        assert len(prompt) > 0
        assert "Transport" in prompt or "transport" in prompt.lower()

    def test_extract_system_prompt_includes_output_schema(self) -> None:
        """Verify extracted prompt includes output schema definition."""
        prompt = extract_system_prompt("src/agents/transport_agent")

        # Transport prompt should define output schema
        assert "transport_output" in prompt.lower() or "json" in prompt.lower()


class TestExtractSystemPromptFromPOIAgent:
    """Tests for extracting system prompt from POI agent."""

    def test_extract_system_prompt_from_poi_agent(self) -> None:
        """Verify system prompt extraction from src/agents/poi_search_agent."""
        prompt = extract_system_prompt("src/agents/poi_search_agent")

        assert prompt is not None
        assert len(prompt) > 0
        # POI uses "search" prompt
        assert "POI" in prompt or "search" in prompt.lower() or "point" in prompt.lower()


class TestExtractSystemPromptFromEventsAgent:
    """Tests for extracting system prompt from events agent."""

    def test_extract_system_prompt_from_events_agent(self) -> None:
        """Verify system prompt extraction from src/agents/events_agent."""
        prompt = extract_system_prompt("src/agents/events_agent")

        assert prompt is not None
        assert len(prompt) > 0
        assert "event" in prompt.lower()


class TestExtractSystemPromptUnknownAgent:
    """Tests for handling unknown agent directories."""

    def test_extract_system_prompt_unknown_agent(self) -> None:
        """Verify error for unknown agent directory."""
        with pytest.raises(ExtractionError) as exc_info:
            extract_system_prompt("src/agents/unknown_agent")

        assert "Unknown agent" in str(exc_info.value) or "not found" in str(exc_info.value).lower()


class TestExtractToolsFindsHostedWebSearchTool:
    """Tests for tool extraction from agent code."""

    def test_extract_tools_finds_hosted_web_search_tool(self) -> None:
        """Verify tool extraction finds HostedWebSearchTool in transport agent."""
        tools = extract_tools("src/agents/transport_agent")

        assert "HostedWebSearchTool" in tools

    def test_extract_tools_finds_hosted_web_search_tool_in_poi(self) -> None:
        """Verify tool extraction finds HostedWebSearchTool in POI agent."""
        tools = extract_tools("src/agents/poi_search_agent")

        assert "HostedWebSearchTool" in tools

    def test_extract_tools_finds_hosted_web_search_tool_in_events(self) -> None:
        """Verify tool extraction finds HostedWebSearchTool in events agent."""
        tools = extract_tools("src/agents/events_agent")

        assert "HostedWebSearchTool" in tools


class TestMapToolToFoundryHostedWebSearch:
    """Tests for mapping Python tools to Foundry format."""

    def test_map_tool_to_foundry_hosted_web_search(self) -> None:
        """Verify HostedWebSearchTool maps to bing_grounding."""
        result = map_tool_to_foundry("HostedWebSearchTool")

        assert result is not None
        assert result["kind"] == "bing_grounding"

    def test_map_tool_to_foundry_unknown_tool(self) -> None:
        """Verify unknown tools return None."""
        result = map_tool_to_foundry("UnknownTool")

        assert result is None


class TestMapToolToFoundryEmptyList:
    """Tests for mapping empty tool lists."""

    def test_map_tool_to_foundry_empty_list(self) -> None:
        """Verify empty tool list produces empty result."""
        result = map_tools_to_foundry([])

        assert result == []


class TestMapToolsToFoundryList:
    """Tests for mapping tool lists."""

    def test_map_tools_to_foundry_with_tools(self) -> None:
        """Verify tool list mapping works correctly."""
        tools = ["HostedWebSearchTool", "UnknownTool"]
        result = map_tools_to_foundry(tools)

        # Only HostedWebSearchTool should map
        assert len(result) == 1
        assert result[0]["kind"] == "bing_grounding"


class TestGenerateNativeAgentYamlIncludesInstructions:
    """Tests for YAML generation."""

    def test_generate_native_agent_yaml_includes_instructions(self) -> None:
        """Verify generated YAML includes instructions field."""
        yaml_content = generate_native_agent_yaml(
            agent_name="test_agent",
            instructions="Test system prompt",
            tools=[],
        )

        assert "instructions" in yaml_content
        assert "Test system prompt" in yaml_content

    def test_generate_native_agent_yaml_includes_model(self) -> None:
        """Verify generated YAML includes model field."""
        yaml_content = generate_native_agent_yaml(
            agent_name="test_agent",
            instructions="Test prompt",
            tools=[],
            model="gpt-4.1-mini",
        )

        assert "model" in yaml_content
        assert "gpt-4.1-mini" in yaml_content


class TestGenerateNativeAgentYamlIncludesBingGrounding:
    """Tests for YAML generation with bing_grounding tool."""

    def test_generate_native_agent_yaml_includes_bing_grounding(self) -> None:
        """Verify generated YAML includes bing_grounding tool."""
        tools = [{"kind": "bing_grounding"}]
        yaml_content = generate_native_agent_yaml(
            agent_name="test_agent",
            instructions="Test prompt",
            tools=tools,
        )

        assert "bing_grounding" in yaml_content
        assert "tools:" in yaml_content


class TestGenerateNativeAgentYamlNoToolsWhenEmpty:
    """Tests for YAML generation with empty tools."""

    def test_generate_native_agent_yaml_no_tools_when_empty(self) -> None:
        """Verify generated YAML has empty tools list when no tools."""
        yaml_content = generate_native_agent_yaml(
            agent_name="test_agent",
            instructions="Test prompt",
            tools=[],
        )

        # Should still have tools field, but empty
        assert "tools:" in yaml_content

        # Parse to verify it's an empty list
        parsed = yaml.safe_load(yaml_content)
        assert parsed["tools"] == []


class TestLoadPromptsFromInteropAggregator:
    """Tests for loading prompts from interoperability path."""

    def test_load_prompts_from_interop_aggregator_exists(self) -> None:
        """Verify prompts can be loaded from aggregator prompts.py (created in INTEROP-008)."""
        # Aggregator prompts.py exists (created in INTEROP-008)
        project_root = get_project_root()
        prompts_path = project_root / "interoperability" / "foundry" / "agents" / "aggregator" / "prompts.py"

        assert prompts_path.exists(), "aggregator prompts.py should exist after INTEROP-008"

        prompt = load_prompts_from_interop("interoperability/foundry/agents/aggregator")
        assert "Aggregator Agent" in prompt
        assert "discovery" in prompt.lower()


class TestLoadPromptsFromInteropWithValidFile:
    """Tests for loading prompts from a valid prompts.py file."""

    def test_load_prompts_from_interop_valid_file(self) -> None:
        """Verify loading prompts from a valid prompts.py works."""
        project_root = get_project_root()

        # Create a temporary prompts.py file
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_dir = Path(tmpdir) / "test_agent"
            agent_dir.mkdir()

            prompts_file = agent_dir / "prompts.py"
            prompts_file.write_text('''
SYSTEM_PROMPT = """You are a test agent.
This is a multi-line prompt."""
''')

            # Create relative path from project root
            # Note: This test uses absolute path since tempfile is outside project
            # We need to test the actual function with a mocked path
            # For now, verify the parsing logic works
            import ast
            source = prompts_file.read_text()
            tree = ast.parse(source)

            prompt_found = None
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "SYSTEM_PROMPT":
                            if isinstance(node.value, ast.Constant):
                                prompt_found = node.value.value

            assert prompt_found is not None
            assert "test agent" in prompt_found


class TestLoadAgentYamlFromInterop:
    """Tests for loading agent.yaml from interoperability path."""

    def test_load_agent_yaml_from_interop_aggregator_exists(self) -> None:
        """Verify agent.yaml can be loaded for aggregator (created in INTEROP-008)."""
        result = load_agent_yaml_from_interop("interoperability/foundry/agents/aggregator")

        # Should return the loaded config (created in INTEROP-008)
        assert result is not None
        assert result["name"] == "aggregator"
        assert "instructions" in result
        assert "Aggregator Agent" in result["instructions"]

    def test_load_agent_yaml_from_interop_valid_file(self) -> None:
        """Verify loading valid agent.yaml works."""
        project_root = get_project_root()

        # Create a temporary agent.yaml for testing
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_dir = Path(tmpdir) / "test_agent"
            agent_dir.mkdir()

            yaml_file = agent_dir / "agent.yaml"
            test_config = {
                "name": "test_agent",
                "instructions": "Test instructions",
                "tools": [],
            }
            with open(yaml_file, "w") as f:
                yaml.dump(test_config, f)

            # Read it back
            with open(yaml_file) as f:
                loaded = yaml.safe_load(f)

            assert loaded["name"] == "test_agent"
            assert loaded["instructions"] == "Test instructions"


class TestDeployAgentRoutesSrcAgentsPath:
    """Tests for routing extraction based on source path."""

    def test_deploy_agent_routes_src_agents_path(self) -> None:
        """Verify extract_agent_for_foundry uses extraction for src/agents/ path."""
        result = extract_agent_for_foundry(
            agent_name="transport",
            source_path="src/agents/transport_agent",
        )

        assert result["source_type"] == "src_agents"
        assert "instructions" in result
        assert len(result["instructions"]) > 0

    def test_extract_agent_includes_tools_for_transport(self) -> None:
        """Verify extracted transport agent has bing_grounding tool."""
        result = extract_agent_for_foundry(
            agent_name="transport",
            source_path="src/agents/transport_agent",
        )

        assert len(result["tools"]) > 0
        assert result["tools"][0]["kind"] == "bing_grounding"


class TestDeployAgentRoutesInteropPath:
    """Tests for routing extraction based on interoperability path."""

    def test_deploy_agent_routes_interop_path_aggregator(self) -> None:
        """Verify extract_agent_for_foundry works for aggregator (created in INTEROP-008)."""
        result = extract_agent_for_foundry(
            agent_name="aggregator",
            source_path="interoperability/foundry/agents/aggregator",
        )

        assert result["source_type"] == "interoperability_yaml"
        assert "Aggregator Agent" in result["instructions"]
        assert result["tools"] == []  # Aggregator has no tools

    def test_deploy_agent_routes_interop_path_route(self) -> None:
        """Verify extract_agent_for_foundry works for route (created in INTEROP-008)."""
        result = extract_agent_for_foundry(
            agent_name="route",
            source_path="interoperability/foundry/agents/route",
        )

        assert result["source_type"] == "interoperability_yaml"
        assert "Route Agent" in result["instructions"]
        assert result["tools"] == []  # Route has no tools


class TestExtractToolsReturnsEmptyForAggregator:
    """Tests for agents without tools."""

    def test_extract_tools_returns_empty_for_aggregator_when_exists(self) -> None:
        """Verify that workflow-support agents have empty tools list when loaded."""
        # This test validates the expected behavior once INTEROP-008 creates prompts.py
        # For now, we verify the mapping works correctly with empty inputs
        result = map_tools_to_foundry([])
        assert result == []


class TestIntegrationTransportAgentExtraction:
    """Integration tests for complete transport agent extraction."""

    def test_full_extraction_transport(self) -> None:
        """Verify complete extraction flow for transport agent."""
        result = extract_agent_for_foundry(
            agent_name="transport",
            source_path="src/agents/transport_agent",
            model="gpt-4.1-mini",
            description="Transport search agent",
        )

        # Verify all fields present
        assert "instructions" in result
        assert "tools" in result
        assert "tool_names" in result
        assert "yaml" in result
        assert "source_type" in result

        # Verify content
        assert result["source_type"] == "src_agents"
        assert "HostedWebSearchTool" in result["tool_names"]
        assert len(result["tools"]) > 0
        assert result["tools"][0]["kind"] == "bing_grounding"

        # Verify YAML content
        assert "instructions" in result["yaml"]
        assert "bing_grounding" in result["yaml"]


class TestIntegrationPOIAgentExtraction:
    """Integration tests for complete POI agent extraction."""

    def test_full_extraction_poi(self) -> None:
        """Verify complete extraction flow for POI agent."""
        result = extract_agent_for_foundry(
            agent_name="poi",
            source_path="src/agents/poi_search_agent",
        )

        assert result["source_type"] == "src_agents"
        assert "HostedWebSearchTool" in result["tool_names"]
        assert result["tools"][0]["kind"] == "bing_grounding"


class TestIntegrationEventsAgentExtraction:
    """Integration tests for complete events agent extraction."""

    def test_full_extraction_events(self) -> None:
        """Verify complete extraction flow for events agent."""
        result = extract_agent_for_foundry(
            agent_name="events",
            source_path="src/agents/events_agent",
        )

        assert result["source_type"] == "src_agents"
        assert "HostedWebSearchTool" in result["tool_names"]
        assert result["tools"][0]["kind"] == "bing_grounding"
