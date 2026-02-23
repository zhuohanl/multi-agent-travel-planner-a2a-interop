"""
Unit tests for native Microsoft Foundry Agent (MFA) definitions.

Tests verify that:
- agent.yaml files are valid and contain required fields
- bing_grounding tool is present in all native agent YAMLs
- prompts.py files exist and can be loaded
- extract_agent module correctly extracts instructions and tools
- config.yaml includes all MFA agents with correct settings

Design doc references:
    - Agent Distribution lines 64-97: Transport, POI, Events as native MFA
    - Tool Mapping lines 77-84: HostedWebSearchTool() → bing_grounding
    - Native Agent Instruction Extraction lines 86-94
"""

from pathlib import Path

import pytest
import yaml

from interoperability.foundry.extract_agent import (
    extract_agent_for_foundry,
    extract_system_prompt,
    extract_tools,
    map_tools_to_foundry,
)


# Test fixtures
@pytest.fixture
def project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent.parent.parent


@pytest.fixture
def foundry_agents_dir(project_root: Path) -> Path:
    """Get the Foundry agents directory."""
    return project_root / "interoperability" / "foundry" / "agents"


@pytest.fixture
def config_path(project_root: Path) -> Path:
    """Get the Foundry config.yaml path."""
    return project_root / "interoperability" / "foundry" / "config.yaml"


# Test Transport agent YAML
class TestTransportAgentYaml:
    """Tests for Transport agent configuration."""

    def test_transport_agent_yaml_valid(self, foundry_agents_dir: Path) -> None:
        """Test that transport agent.yaml is valid YAML."""
        agent_yaml_path = foundry_agents_dir / "transport" / "agent.yaml"
        assert agent_yaml_path.exists(), "transport/agent.yaml not found"

        with open(agent_yaml_path) as f:
            content = yaml.safe_load(f)

        # Verify required fields
        assert "name" in content, "agent.yaml missing 'name' field"
        assert content["name"] == "transport", "agent name should be 'transport'"
        assert "model" in content, "agent.yaml missing 'model' field"
        assert "instructions" in content, "agent.yaml missing 'instructions' field"
        assert "tools" in content, "agent.yaml missing 'tools' field"

    def test_transport_agent_yaml_has_bing_grounding(
        self, foundry_agents_dir: Path
    ) -> None:
        """Test that transport agent.yaml includes bing_grounding tool."""
        agent_yaml_path = foundry_agents_dir / "transport" / "agent.yaml"

        with open(agent_yaml_path) as f:
            content = yaml.safe_load(f)

        tools = content.get("tools", [])
        assert len(tools) > 0, "transport agent should have at least one tool"

        # Check for bing_grounding tool
        tool_kinds = [t.get("kind") for t in tools if isinstance(t, dict)]
        assert (
            "bing_grounding" in tool_kinds
        ), "transport agent should have bing_grounding tool"

    def test_transport_agent_instructions_not_empty(
        self, foundry_agents_dir: Path
    ) -> None:
        """Test that transport agent has non-empty instructions."""
        agent_yaml_path = foundry_agents_dir / "transport" / "agent.yaml"

        with open(agent_yaml_path) as f:
            content = yaml.safe_load(f)

        instructions = content.get("instructions", "")
        assert len(instructions) > 100, "transport instructions should be substantial"
        assert "Transport Agent" in instructions, "instructions should mention Transport Agent"


# Test POI agent YAML
class TestPoiAgentYaml:
    """Tests for POI Search agent configuration."""

    def test_poi_agent_yaml_valid(self, foundry_agents_dir: Path) -> None:
        """Test that POI agent.yaml is valid YAML."""
        agent_yaml_path = foundry_agents_dir / "poi" / "agent.yaml"
        assert agent_yaml_path.exists(), "poi/agent.yaml not found"

        with open(agent_yaml_path) as f:
            content = yaml.safe_load(f)

        # Verify required fields
        assert "name" in content, "agent.yaml missing 'name' field"
        assert content["name"] == "poi", "agent name should be 'poi'"
        assert "model" in content, "agent.yaml missing 'model' field"
        assert "instructions" in content, "agent.yaml missing 'instructions' field"
        assert "tools" in content, "agent.yaml missing 'tools' field"

    def test_poi_agent_yaml_has_bing_grounding(self, foundry_agents_dir: Path) -> None:
        """Test that POI agent.yaml includes bing_grounding tool."""
        agent_yaml_path = foundry_agents_dir / "poi" / "agent.yaml"

        with open(agent_yaml_path) as f:
            content = yaml.safe_load(f)

        tools = content.get("tools", [])
        assert len(tools) > 0, "POI agent should have at least one tool"

        # Check for bing_grounding tool
        tool_kinds = [t.get("kind") for t in tools if isinstance(t, dict)]
        assert (
            "bing_grounding" in tool_kinds
        ), "POI agent should have bing_grounding tool"

    def test_poi_agent_instructions_not_empty(self, foundry_agents_dir: Path) -> None:
        """Test that POI agent has non-empty instructions."""
        agent_yaml_path = foundry_agents_dir / "poi" / "agent.yaml"

        with open(agent_yaml_path) as f:
            content = yaml.safe_load(f)

        instructions = content.get("instructions", "")
        assert len(instructions) > 100, "POI instructions should be substantial"
        assert "POI Search Agent" in instructions, "instructions should mention POI Search Agent"


# Test Events agent YAML
class TestEventsAgentYaml:
    """Tests for Events agent configuration."""

    def test_events_agent_yaml_valid(self, foundry_agents_dir: Path) -> None:
        """Test that Events agent.yaml is valid YAML."""
        agent_yaml_path = foundry_agents_dir / "events" / "agent.yaml"
        assert agent_yaml_path.exists(), "events/agent.yaml not found"

        with open(agent_yaml_path) as f:
            content = yaml.safe_load(f)

        # Verify required fields
        assert "name" in content, "agent.yaml missing 'name' field"
        assert content["name"] == "events", "agent name should be 'events'"
        assert "model" in content, "agent.yaml missing 'model' field"
        assert "instructions" in content, "agent.yaml missing 'instructions' field"
        assert "tools" in content, "agent.yaml missing 'tools' field"

    def test_events_agent_yaml_has_bing_grounding(
        self, foundry_agents_dir: Path
    ) -> None:
        """Test that Events agent.yaml includes bing_grounding tool."""
        agent_yaml_path = foundry_agents_dir / "events" / "agent.yaml"

        with open(agent_yaml_path) as f:
            content = yaml.safe_load(f)

        tools = content.get("tools", [])
        assert len(tools) > 0, "Events agent should have at least one tool"

        # Check for bing_grounding tool
        tool_kinds = [t.get("kind") for t in tools if isinstance(t, dict)]
        assert (
            "bing_grounding" in tool_kinds
        ), "Events agent should have bing_grounding tool"

    def test_events_agent_instructions_not_empty(
        self, foundry_agents_dir: Path
    ) -> None:
        """Test that Events agent has non-empty instructions."""
        agent_yaml_path = foundry_agents_dir / "events" / "agent.yaml"

        with open(agent_yaml_path) as f:
            content = yaml.safe_load(f)

        instructions = content.get("instructions", "")
        assert len(instructions) > 100, "Events instructions should be substantial"
        assert "Events Agent" in instructions, "instructions should mention Events Agent"


# Test prompts extraction from source
class TestPromptsExtraction:
    """Tests for prompt extraction from source agents."""

    def test_prompts_extracted_from_source_transport(self) -> None:
        """Test that Transport agent prompts can be extracted from source."""
        prompt = extract_system_prompt("src/agents/transport_agent")
        assert prompt, "Should extract non-empty prompt"
        assert "Transport Agent" in prompt, "Prompt should mention Transport Agent"

    def test_prompts_extracted_from_source_poi(self) -> None:
        """Test that POI agent prompts can be extracted from source."""
        prompt = extract_system_prompt("src/agents/poi_search_agent")
        assert prompt, "Should extract non-empty prompt"
        assert "POI Search Agent" in prompt, "Prompt should mention POI Search Agent"

    def test_prompts_extracted_from_source_events(self) -> None:
        """Test that Events agent prompts can be extracted from source."""
        prompt = extract_system_prompt("src/agents/events_agent")
        assert prompt, "Should extract non-empty prompt"
        assert "Events Agent" in prompt, "Prompt should mention Events Agent"


# Test tool mapping
class TestToolMapping:
    """Tests for tool mapping from source to Foundry format."""

    def test_tool_mapping_produces_bing_grounding(self) -> None:
        """Test that HostedWebSearchTool maps to bing_grounding."""
        tool_names = ["HostedWebSearchTool"]
        mapped = map_tools_to_foundry(tool_names)

        assert len(mapped) == 1, "Should map one tool"
        assert mapped[0] == {"kind": "bing_grounding"}, "Should map to bing_grounding"

    def test_transport_tools_include_bing_grounding(self) -> None:
        """Test that Transport agent tools are extracted and mapped correctly."""
        tool_names = extract_tools("src/agents/transport_agent")
        assert "HostedWebSearchTool" in tool_names, "Transport should use HostedWebSearchTool"

        mapped = map_tools_to_foundry(tool_names)
        tool_kinds = [t.get("kind") for t in mapped]
        assert "bing_grounding" in tool_kinds, "Should include bing_grounding"

    def test_poi_tools_include_bing_grounding(self) -> None:
        """Test that POI agent tools are extracted and mapped correctly."""
        tool_names = extract_tools("src/agents/poi_search_agent")
        assert "HostedWebSearchTool" in tool_names, "POI should use HostedWebSearchTool"

        mapped = map_tools_to_foundry(tool_names)
        tool_kinds = [t.get("kind") for t in mapped]
        assert "bing_grounding" in tool_kinds, "Should include bing_grounding"

    def test_events_tools_include_bing_grounding(self) -> None:
        """Test that Events agent tools are extracted and mapped correctly."""
        tool_names = extract_tools("src/agents/events_agent")
        assert "HostedWebSearchTool" in tool_names, "Events should use HostedWebSearchTool"

        mapped = map_tools_to_foundry(tool_names)
        tool_kinds = [t.get("kind") for t in mapped]
        assert "bing_grounding" in tool_kinds, "Should include bing_grounding"


# Test config.yaml includes all MFA agents
class TestConfigIncludesAllMfaAgents:
    """Tests for config.yaml agent definitions."""

    def test_config_includes_all_mfa_agents(self, config_path: Path) -> None:
        """Test that config.yaml includes transport, poi, events as native agents."""
        with open(config_path) as f:
            config = yaml.safe_load(f)

        agents = config.get("agents", {})

        # Check transport
        assert "transport" in agents, "config should include transport agent"
        assert agents["transport"]["type"] == "native", "transport should be native"
        assert "interoperability/foundry/agents/transport" == agents["transport"]["source"], \
            "transport source should reference interoperability path"

        # Check POI
        assert "poi" in agents, "config should include poi agent"
        assert agents["poi"]["type"] == "native", "poi should be native"
        assert "interoperability/foundry/agents/poi" == agents["poi"]["source"], \
            "poi source should reference interoperability path"

        # Check Events
        assert "events" in agents, "config should include events agent"
        assert agents["events"]["type"] == "native", "events should be native"
        assert "interoperability/foundry/agents/events" == agents["events"]["source"], \
            "events source should reference interoperability path"

    def test_config_mfa_agents_have_model(self, config_path: Path) -> None:
        """Test that all MFA agents have model specified."""
        with open(config_path) as f:
            config = yaml.safe_load(f)

        agents = config.get("agents", {})

        for agent_name in ["transport", "poi", "events"]:
            assert "model" in agents[agent_name], f"{agent_name} should have model specified"

    def test_config_transport_points_to_interop(self, config_path: Path) -> None:
        """Test that transport source points to interoperability/foundry/agents/transport."""
        with open(config_path) as f:
            config = yaml.safe_load(f)

        agents = config.get("agents", {})
        assert agents["transport"]["source"] == "interoperability/foundry/agents/transport", \
            "transport source should be interoperability/foundry/agents/transport"

    def test_config_poi_points_to_interop(self, config_path: Path) -> None:
        """Test that poi source points to interoperability/foundry/agents/poi."""
        with open(config_path) as f:
            config = yaml.safe_load(f)

        agents = config.get("agents", {})
        assert agents["poi"]["source"] == "interoperability/foundry/agents/poi", \
            "poi source should be interoperability/foundry/agents/poi"

    def test_config_events_points_to_interop(self, config_path: Path) -> None:
        """Test that events source points to interoperability/foundry/agents/events."""
        with open(config_path) as f:
            config = yaml.safe_load(f)

        agents = config.get("agents", {})
        assert agents["events"]["source"] == "interoperability/foundry/agents/events", \
            "events source should be interoperability/foundry/agents/events"


# Test full extraction workflow
class TestFullExtractionWorkflow:
    """Tests for the full extract_agent_for_foundry workflow."""

    def test_extract_transport_for_foundry(self) -> None:
        """Test full extraction workflow for Transport agent."""
        result = extract_agent_for_foundry(
            agent_name="transport",
            source_path="src/agents/transport_agent",
            model="gpt-4.1-mini",
        )

        assert "instructions" in result, "Should have instructions"
        assert "tools" in result, "Should have tools"
        assert "yaml" in result, "Should have generated YAML"
        assert result["source_type"] == "src_agents", "Should be src_agents source type"

        # Verify tools include bing_grounding
        tool_kinds = [t.get("kind") for t in result["tools"]]
        assert "bing_grounding" in tool_kinds, "Should include bing_grounding tool"

    def test_extract_poi_for_foundry(self) -> None:
        """Test full extraction workflow for POI agent."""
        result = extract_agent_for_foundry(
            agent_name="poi",
            source_path="src/agents/poi_search_agent",
            model="gpt-4.1-mini",
        )

        assert "instructions" in result, "Should have instructions"
        assert "tools" in result, "Should have tools"
        assert result["source_type"] == "src_agents", "Should be src_agents source type"

        tool_kinds = [t.get("kind") for t in result["tools"]]
        assert "bing_grounding" in tool_kinds, "Should include bing_grounding tool"

    def test_extract_events_for_foundry(self) -> None:
        """Test full extraction workflow for Events agent."""
        result = extract_agent_for_foundry(
            agent_name="events",
            source_path="src/agents/events_agent",
            model="gpt-4.1-mini",
        )

        assert "instructions" in result, "Should have instructions"
        assert "tools" in result, "Should have tools"
        assert result["source_type"] == "src_agents", "Should be src_agents source type"

        tool_kinds = [t.get("kind") for t in result["tools"]]
        assert "bing_grounding" in tool_kinds, "Should include bing_grounding tool"


# Test Aggregator agent YAML
class TestAggregatorAgentYaml:
    """Tests for Aggregator agent configuration."""

    def test_aggregator_agent_yaml_valid(self, foundry_agents_dir: Path) -> None:
        """Test that aggregator agent.yaml is valid YAML with required fields."""
        agent_yaml_path = foundry_agents_dir / "aggregator" / "agent.yaml"
        assert agent_yaml_path.exists(), "aggregator/agent.yaml not found"

        with open(agent_yaml_path) as f:
            content = yaml.safe_load(f)

        # Verify required fields
        assert "name" in content, "agent.yaml missing 'name' field"
        assert content["name"] == "aggregator", "agent name should be 'aggregator'"
        assert "model" in content, "agent.yaml missing 'model' field"
        assert "instructions" in content, "agent.yaml missing 'instructions' field"
        assert "tools" in content, "agent.yaml missing 'tools' field"
        # Aggregator does not need external tools
        assert content["tools"] == [], "aggregator should have empty tools list"

    def test_aggregator_prompt_references_all_agents(
        self, foundry_agents_dir: Path
    ) -> None:
        """Test that aggregator prompt references all discovery agent types."""
        agent_yaml_path = foundry_agents_dir / "aggregator" / "agent.yaml"

        with open(agent_yaml_path) as f:
            content = yaml.safe_load(f)

        instructions = content.get("instructions", "")

        # Check that aggregator mentions all discovery agent categories
        assert "POI" in instructions, "Aggregator should mention POI agent"
        assert "Stay" in instructions, "Aggregator should mention Stay agent"
        assert "Transport" in instructions, "Aggregator should mention Transport agent"
        assert "Events" in instructions, "Aggregator should mention Events agent"
        assert "Dining" in instructions, "Aggregator should mention Dining agent"

    def test_aggregator_output_matches_shared_models(
        self, foundry_agents_dir: Path
    ) -> None:
        """Test that aggregator output schema matches DiscoveryResults from src/shared/models.py."""
        agent_yaml_path = foundry_agents_dir / "aggregator" / "agent.yaml"

        with open(agent_yaml_path) as f:
            content = yaml.safe_load(f)

        instructions = content.get("instructions", "")

        # Check for DiscoveryResults schema fields
        assert "aggregated_results" in instructions, "Should mention aggregated_results"
        assert "pois" in instructions, "Should mention pois field"
        assert "stays" in instructions, "Should mention stays field"
        assert "transport" in instructions, "Should mention transport field"
        assert "events" in instructions, "Should mention events field"
        assert "dining" in instructions, "Should mention dining field"
        # Check for src/shared/models.py reference
        assert "src/shared/models.py" in instructions, "Should reference src/shared/models.py"

    def test_aggregator_instructions_not_empty(self, foundry_agents_dir: Path) -> None:
        """Test that aggregator agent has non-empty instructions."""
        agent_yaml_path = foundry_agents_dir / "aggregator" / "agent.yaml"

        with open(agent_yaml_path) as f:
            content = yaml.safe_load(f)

        instructions = content.get("instructions", "")
        assert len(instructions) > 100, "aggregator instructions should be substantial"
        assert "Aggregator Agent" in instructions, "instructions should mention Aggregator Agent"


# Test Route agent YAML
class TestRouteAgentYaml:
    """Tests for Route agent configuration."""

    def test_route_agent_yaml_valid(self, foundry_agents_dir: Path) -> None:
        """Test that route agent.yaml is valid YAML with required fields."""
        agent_yaml_path = foundry_agents_dir / "route" / "agent.yaml"
        assert agent_yaml_path.exists(), "route/agent.yaml not found"

        with open(agent_yaml_path) as f:
            content = yaml.safe_load(f)

        # Verify required fields
        assert "name" in content, "agent.yaml missing 'name' field"
        assert content["name"] == "route", "agent name should be 'route'"
        assert "model" in content, "agent.yaml missing 'model' field"
        assert "instructions" in content, "agent.yaml missing 'instructions' field"
        assert "tools" in content, "agent.yaml missing 'tools' field"
        # Route does not need external tools
        assert content["tools"] == [], "route should have empty tools list"

    def test_route_prompt_creates_itinerary(self, foundry_agents_dir: Path) -> None:
        """Test that route prompt describes itinerary creation."""
        agent_yaml_path = foundry_agents_dir / "route" / "agent.yaml"

        with open(agent_yaml_path) as f:
            content = yaml.safe_load(f)

        instructions = content.get("instructions", "")

        # Check for itinerary creation instructions
        assert "itinerary" in instructions.lower(), "Should mention itinerary"
        assert "day-by-day" in instructions.lower(), "Should mention day-by-day planning"
        assert "slots" in instructions.lower(), "Should mention time slots"
        assert "TripSpec" in instructions, "Should mention TripSpec"

    def test_route_output_matches_itinerary_schema(
        self, foundry_agents_dir: Path
    ) -> None:
        """Test that route output schema matches Itinerary from src/shared/models.py."""
        agent_yaml_path = foundry_agents_dir / "route" / "agent.yaml"

        with open(agent_yaml_path) as f:
            content = yaml.safe_load(f)

        instructions = content.get("instructions", "")

        # Check for Itinerary schema fields
        assert "days" in instructions, "Should mention days field"
        assert "date" in instructions, "Should mention date field"
        assert "slots" in instructions, "Should mention slots field"
        assert "start_time" in instructions, "Should mention start_time field"
        assert "end_time" in instructions, "Should mention end_time field"
        assert "activity" in instructions, "Should mention activity field"
        assert "category" in instructions, "Should mention category field"
        assert "total_estimated_cost" in instructions, "Should mention total_estimated_cost"
        # Check for src/shared/models.py reference
        assert "src/shared/models.py" in instructions, "Should reference src/shared/models.py"

    def test_route_output_compatible_with_demo_b_approval(
        self, foundry_agents_dir: Path
    ) -> None:
        """Test that route output includes fields needed for Demo B approval workflow."""
        agent_yaml_path = foundry_agents_dir / "route" / "agent.yaml"

        with open(agent_yaml_path) as f:
            content = yaml.safe_load(f)

        instructions = content.get("instructions", "")

        # Demo B approval workflow needs:
        # - Itinerary structure with days, slots
        # - Cost information for approval
        # - Item references for traceability
        assert "item_ref" in instructions, "Should mention item_ref for traceability"
        assert "estimated_cost" in instructions, "Should mention estimated_cost"
        assert "currency" in instructions, "Should mention currency"
        # The itinerary structure supports approval by having day summaries
        assert "day_summary" in instructions, "Should mention day_summary for approval"

    def test_route_instructions_not_empty(self, foundry_agents_dir: Path) -> None:
        """Test that route agent has non-empty instructions."""
        agent_yaml_path = foundry_agents_dir / "route" / "agent.yaml"

        with open(agent_yaml_path) as f:
            content = yaml.safe_load(f)

        instructions = content.get("instructions", "")
        assert len(instructions) > 100, "route instructions should be substantial"
        assert "Route Agent" in instructions, "instructions should mention Route Agent"


# Test config.yaml includes Aggregator and Route agents
class TestConfigIncludesWorkflowAgents:
    """Tests for config.yaml workflow agent definitions."""

    def test_config_includes_aggregator_agent(self, config_path: Path) -> None:
        """Test that config.yaml includes aggregator as native agent."""
        with open(config_path) as f:
            config = yaml.safe_load(f)

        agents = config.get("agents", {})

        # Check aggregator
        assert "aggregator" in agents, "config should include aggregator agent"
        assert agents["aggregator"]["type"] == "native", "aggregator should be native"
        assert "interoperability/foundry/agents/aggregator" in agents["aggregator"]["source"], \
            "aggregator source should reference interoperability path"
        assert "model" in agents["aggregator"], "aggregator should have model specified"

    def test_config_includes_route_agent(self, config_path: Path) -> None:
        """Test that config.yaml includes route as native agent."""
        with open(config_path) as f:
            config = yaml.safe_load(f)

        agents = config.get("agents", {})

        # Check route
        assert "route" in agents, "config should include route agent"
        assert agents["route"]["type"] == "native", "route should be native"
        assert "interoperability/foundry/agents/route" in agents["route"]["source"], \
            "route source should reference interoperability path"
        assert "model" in agents["route"], "route should have model specified"


# Test extraction workflow for interoperability agents
class TestInteropAgentExtraction:
    """Tests for extracting workflow support agents from interoperability/."""

    def test_extract_aggregator_for_foundry(self) -> None:
        """Test extraction workflow for Aggregator agent from interoperability path."""
        result = extract_agent_for_foundry(
            agent_name="aggregator",
            source_path="interoperability/foundry/agents/aggregator",
            model="gpt-4.1-mini",
        )

        assert "instructions" in result, "Should have instructions"
        assert "tools" in result, "Should have tools"
        assert "yaml" in result, "Should have generated YAML"
        assert result["source_type"] == "interoperability_yaml", \
            "Should be interoperability_yaml source type (loads from agent.yaml)"

        # Verify aggregator has no tools
        assert result["tools"] == [], "Aggregator should have empty tools list"

        # Verify instructions mention key concepts
        assert "Aggregator" in result["instructions"], "Should mention Aggregator"
        assert "discovery" in result["instructions"].lower(), "Should mention discovery"

    def test_extract_route_for_foundry(self) -> None:
        """Test extraction workflow for Route agent from interoperability path."""
        result = extract_agent_for_foundry(
            agent_name="route",
            source_path="interoperability/foundry/agents/route",
            model="gpt-4.1-mini",
        )

        assert "instructions" in result, "Should have instructions"
        assert "tools" in result, "Should have tools"
        assert "yaml" in result, "Should have generated YAML"
        assert result["source_type"] == "interoperability_yaml", \
            "Should be interoperability_yaml source type (loads from agent.yaml)"

        # Verify route has no tools
        assert result["tools"] == [], "Route should have empty tools list"

        # Verify instructions mention key concepts
        assert "Route" in result["instructions"], "Should mention Route"
        assert "itinerary" in result["instructions"].lower(), "Should mention itinerary"


# Test extraction from interoperability paths for Transport, POI, Events
class TestMfaAgentExtractionFromInterop:
    """Tests for extracting Transport, POI, Events from interoperability/ paths.

    These tests verify that extract_agent_for_foundry correctly loads agent.yaml
    files from interoperability/foundry/agents/ when config.yaml points to these paths.
    Added in INTEROP-005A.
    """

    def test_extract_transport_from_interop(self) -> None:
        """Test extraction workflow for Transport agent from interoperability path."""
        result = extract_agent_for_foundry(
            agent_name="transport",
            source_path="interoperability/foundry/agents/transport",
            model="gpt-4.1-mini",
        )

        assert "instructions" in result, "Should have instructions"
        assert "tools" in result, "Should have tools"
        assert "yaml" in result, "Should have generated YAML"
        assert result["source_type"] == "interoperability_yaml", \
            "Should be interoperability_yaml source type (loads from agent.yaml)"

        # Verify transport has bing_grounding tool
        tool_kinds = [t.get("kind") for t in result["tools"]]
        assert "bing_grounding" in tool_kinds, "Transport should have bing_grounding tool"

        # Verify instructions mention key concepts
        assert "Transport Agent" in result["instructions"], "Should mention Transport Agent"

    def test_extract_poi_from_interop(self) -> None:
        """Test extraction workflow for POI agent from interoperability path."""
        result = extract_agent_for_foundry(
            agent_name="poi",
            source_path="interoperability/foundry/agents/poi",
            model="gpt-4.1-mini",
        )

        assert "instructions" in result, "Should have instructions"
        assert "tools" in result, "Should have tools"
        assert "yaml" in result, "Should have generated YAML"
        assert result["source_type"] == "interoperability_yaml", \
            "Should be interoperability_yaml source type (loads from agent.yaml)"

        # Verify POI has bing_grounding tool
        tool_kinds = [t.get("kind") for t in result["tools"]]
        assert "bing_grounding" in tool_kinds, "POI should have bing_grounding tool"

        # Verify instructions mention key concepts
        assert "POI Search Agent" in result["instructions"], "Should mention POI Search Agent"

    def test_extract_events_from_interop(self) -> None:
        """Test extraction workflow for Events agent from interoperability path."""
        result = extract_agent_for_foundry(
            agent_name="events",
            source_path="interoperability/foundry/agents/events",
            model="gpt-4.1-mini",
        )

        assert "instructions" in result, "Should have instructions"
        assert "tools" in result, "Should have tools"
        assert "yaml" in result, "Should have generated YAML"
        assert result["source_type"] == "interoperability_yaml", \
            "Should be interoperability_yaml source type (loads from agent.yaml)"

        # Verify Events has bing_grounding tool
        tool_kinds = [t.get("kind") for t in result["tools"]]
        assert "bing_grounding" in tool_kinds, "Events should have bing_grounding tool"

        # Verify instructions mention key concepts
        assert "Events Agent" in result["instructions"], "Should mention Events Agent"

    def test_interop_transport_yaml_loads_correctly(self) -> None:
        """Test that load_agent_yaml_from_interop loads transport agent.yaml correctly."""
        from interoperability.foundry.extract_agent import load_agent_yaml_from_interop

        result = load_agent_yaml_from_interop("interoperability/foundry/agents/transport")

        assert result is not None, "Should load agent.yaml"
        assert "name" in result, "Should have name field"
        assert result["name"] == "transport", "name should be transport"
        assert "instructions" in result, "Should have instructions"
        assert "tools" in result, "Should have tools"

    def test_interop_poi_yaml_loads_correctly(self) -> None:
        """Test that load_agent_yaml_from_interop loads POI agent.yaml correctly."""
        from interoperability.foundry.extract_agent import load_agent_yaml_from_interop

        result = load_agent_yaml_from_interop("interoperability/foundry/agents/poi")

        assert result is not None, "Should load agent.yaml"
        assert "name" in result, "Should have name field"
        assert result["name"] == "poi", "name should be poi"
        assert "instructions" in result, "Should have instructions"
        assert "tools" in result, "Should have tools"

    def test_interop_events_yaml_loads_correctly(self) -> None:
        """Test that load_agent_yaml_from_interop loads events agent.yaml correctly."""
        from interoperability.foundry.extract_agent import load_agent_yaml_from_interop

        result = load_agent_yaml_from_interop("interoperability/foundry/agents/events")

        assert result is not None, "Should load agent.yaml"
        assert "name" in result, "Should have name field"
        assert result["name"] == "events", "name should be events"
        assert "instructions" in result, "Should have instructions"
        assert "tools" in result, "Should have tools"
