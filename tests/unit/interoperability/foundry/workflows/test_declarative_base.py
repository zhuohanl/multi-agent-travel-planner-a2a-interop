"""Tests for INTEROP-011C1: Base declarative workflow YAML with intake variable handling.

Validates that the declarative workflow YAML has proper SetVariable nodes
for trip request handling and that all InvokeAzureAgent nodes have autoSend: false.
"""

import os
from pathlib import Path

import yaml
import pytest


WORKFLOW_PATH = Path(__file__).resolve().parents[5] / (
    "interoperability/foundry/workflows/discovery_workflow_declarative/workflow.yaml"
)


@pytest.fixture
def workflow():
    """Load and parse the declarative workflow YAML."""
    assert WORKFLOW_PATH.exists(), f"Workflow YAML not found at {WORKFLOW_PATH}"
    with open(WORKFLOW_PATH) as f:
        return yaml.safe_load(f)


@pytest.fixture
def actions(workflow):
    """Extract the actions list from the workflow trigger."""
    return workflow["trigger"]["actions"]


@pytest.fixture
def setvariable_actions(actions):
    """Extract all SetVariable actions."""
    return [a for a in actions if a.get("kind") == "SetVariable"]


@pytest.fixture
def invoke_agent_actions(actions):
    """Extract all InvokeAzureAgent actions."""
    return [a for a in actions if a.get("kind") == "InvokeAzureAgent"]


# --- INTEROP-011C1 Tests ---


class TestTripRequestJsonSetVariable:
    """Test that Local.TripRequestJson is set from System.LastMessageText."""

    def test_triprequest_json_setvariable(self, setvariable_actions):
        """SetVariable for Local.TripRequestJson captures System.LastMessageText."""
        trip_json_vars = [
            a for a in setvariable_actions
            if a.get("variable") == "Local.TripRequestJson"
        ]
        assert len(trip_json_vars) == 1, (
            "Expected exactly one SetVariable for Local.TripRequestJson"
        )
        action = trip_json_vars[0]
        assert action["value"] == "=System.LastMessageText", (
            f"Local.TripRequestJson should be =System.LastMessageText, got {action['value']}"
        )

    def test_triprequest_json_has_id(self, setvariable_actions):
        """SetVariable for Local.TripRequestJson has an id field."""
        trip_json_vars = [
            a for a in setvariable_actions
            if a.get("variable") == "Local.TripRequestJson"
        ]
        assert len(trip_json_vars) == 1
        assert "id" in trip_json_vars[0], "SetVariable should have an id field"

    def test_triprequest_json_is_first_action(self, actions):
        """Local.TripRequestJson should be set before any agent invocation."""
        for action in actions:
            if action.get("kind") == "InvokeAzureAgent":
                pytest.fail(
                    "InvokeAzureAgent found before Local.TripRequestJson SetVariable"
                )
            if (
                action.get("kind") == "SetVariable"
                and action.get("variable") == "Local.TripRequestJson"
            ):
                break


class TestTripRequestMsgSetVariable:
    """Test that Local.TripRequestMsg wraps with UserMessage()."""

    def test_triprequest_msg_setvariable(self, setvariable_actions):
        """SetVariable for Local.TripRequestMsg wraps with UserMessage()."""
        trip_msg_vars = [
            a for a in setvariable_actions
            if a.get("variable") == "Local.TripRequestMsg"
        ]
        assert len(trip_msg_vars) == 1, (
            "Expected exactly one SetVariable for Local.TripRequestMsg"
        )
        action = trip_msg_vars[0]
        assert "UserMessage" in action["value"], (
            f"Local.TripRequestMsg should use UserMessage(), got {action['value']}"
        )
        assert "Local.TripRequestJson" in action["value"], (
            "Local.TripRequestMsg should reference Local.TripRequestJson"
        )

    def test_triprequest_msg_comes_after_json(self, actions):
        """Local.TripRequestMsg must be set after Local.TripRequestJson."""
        json_idx = None
        msg_idx = None
        for i, action in enumerate(actions):
            if (
                action.get("kind") == "SetVariable"
                and action.get("variable") == "Local.TripRequestJson"
            ):
                json_idx = i
            if (
                action.get("kind") == "SetVariable"
                and action.get("variable") == "Local.TripRequestMsg"
            ):
                msg_idx = i

        assert json_idx is not None, "Local.TripRequestJson SetVariable not found"
        assert msg_idx is not None, "Local.TripRequestMsg SetVariable not found"
        assert msg_idx > json_idx, (
            "Local.TripRequestMsg must come after Local.TripRequestJson"
        )


class TestAllAgentsAutoSendFalse:
    """Test that all discovery InvokeAzureAgent nodes have autoSend: false."""

    DISCOVERY_AGENTS = {"transport", "poi", "events", "stay", "dining", "weather-proxy"}

    def test_all_agents_autosend_false(self, invoke_agent_actions):
        """All InvokeAzureAgent nodes for discovery agents have autoSend: false."""
        for action in invoke_agent_actions:
            agent_name = action.get("agent", {}).get("name", "")
            if agent_name in self.DISCOVERY_AGENTS:
                auto_send = action.get("output", {}).get("autoSend")
                assert auto_send is False, (
                    f"Agent '{agent_name}' has autoSend={auto_send}, expected false"
                )

    def test_all_discovery_agents_present(self, invoke_agent_actions):
        """All 6 discovery agents are present in the workflow."""
        agent_names = {
            a.get("agent", {}).get("name") for a in invoke_agent_actions
        }
        for expected in self.DISCOVERY_AGENTS:
            assert expected in agent_names, (
                f"Discovery agent '{expected}' not found in workflow"
            )

    def test_discovery_agents_use_triprequest_msg(self, invoke_agent_actions):
        """All discovery agents use Local.TripRequestMsg as input."""
        for action in invoke_agent_actions:
            agent_name = action.get("agent", {}).get("name", "")
            if agent_name in self.DISCOVERY_AGENTS:
                messages = action.get("input", {}).get("messages", "")
                assert "Local.TripRequestMsg" in messages, (
                    f"Agent '{agent_name}' should use Local.TripRequestMsg, got {messages}"
                )

    def test_agents_have_conversation_id(self, invoke_agent_actions):
        """All InvokeAzureAgent nodes reference System.ConversationId."""
        for action in invoke_agent_actions:
            conv_id = action.get("conversationId", "")
            assert "System.ConversationId" in conv_id, (
                f"Agent '{action.get('agent', {}).get('name')}' missing conversationId"
            )


# --- INTEROP-011C1B Tests ---


class TestDiscoveryOutputsMappedToLocalResults:
    """Test that all discovery InvokeAzureAgent nodes have output.text mapped to Local.*Result."""

    EXPECTED_MAPPINGS = {
        "transport": "Local.TransportResult",
        "poi": "Local.POIResult",
        "events": "Local.EventsResult",
        "stay": "Local.StayResult",
        "dining": "Local.DiningResult",
        "weather-proxy": "Local.WeatherResult",
    }

    def test_discovery_outputs_mapped_to_local_results(self, invoke_agent_actions):
        """All six discovery InvokeAzureAgent nodes set output.text to Local.*Result."""
        for action in invoke_agent_actions:
            agent_name = action.get("agent", {}).get("name", "")
            if agent_name in self.EXPECTED_MAPPINGS:
                output_text = action.get("output", {}).get("text")
                expected = self.EXPECTED_MAPPINGS[agent_name]
                assert output_text == expected, (
                    f"Agent '{agent_name}' output.text should be '{expected}', "
                    f"got '{output_text}'"
                )

        # Verify all expected agents were found
        found_agents = {
            a.get("agent", {}).get("name")
            for a in invoke_agent_actions
            if a.get("agent", {}).get("name") in self.EXPECTED_MAPPINGS
        }
        assert found_agents == set(self.EXPECTED_MAPPINGS.keys()), (
            f"Missing discovery agents: {set(self.EXPECTED_MAPPINGS.keys()) - found_agents}"
        )

    def test_weather_output_mapped_to_local_result(self, invoke_agent_actions):
        """Weather proxy agent specifically has output.text: Local.WeatherResult."""
        weather_actions = [
            a for a in invoke_agent_actions
            if a.get("agent", {}).get("name") == "weather-proxy"
        ]
        assert len(weather_actions) == 1, "Expected exactly one weather-proxy agent"
        output_text = weather_actions[0].get("output", {}).get("text")
        assert output_text == "Local.WeatherResult", (
            f"Weather proxy output.text should be 'Local.WeatherResult', got '{output_text}'"
        )

    def test_combine_results_references_local_results(self, actions):
        """The combine_results SetVariable references the same Local.*Result variables."""
        combine_action = None
        for action in actions:
            if (
                action.get("kind") == "SetVariable"
                and action.get("variable") == "Local.CombinedResultsJson"
            ):
                combine_action = action
                break

        assert combine_action is not None, "combine_results SetVariable not found"
        value = combine_action.get("value", "")

        expected_vars = [
            "Local.TransportResult",
            "Local.POIResult",
            "Local.EventsResult",
            "Local.StayResult",
            "Local.DiningResult",
            "Local.WeatherResult",
        ]
        for var in expected_vars:
            assert var in value, (
                f"combine_results should reference {var}, not found in value"
            )


# --- INTEROP-011C2 Tests ---


class TestAggregatorPayloadConstruction:
    """Test that the aggregator payload is constructed using Concatenate() with correct structure."""

    def test_combined_results_has_trip_request(self, actions):
        """Local.CombinedResultsJson Concatenate() includes trip_request key."""
        combine_action = None
        for action in actions:
            if (
                action.get("kind") == "SetVariable"
                and action.get("variable") == "Local.CombinedResultsJson"
            ):
                combine_action = action
                break

        assert combine_action is not None, (
            "SetVariable for Local.CombinedResultsJson not found"
        )
        value = combine_action.get("value", "")
        assert "Concatenate(" in value, (
            "Local.CombinedResultsJson should use Concatenate() function"
        )
        assert "trip_request" in value, (
            "Concatenate() payload should include trip_request key"
        )
        assert "Local.TripRequestJson" in value, (
            "Concatenate() should reference Local.TripRequestJson for trip_request"
        )

    def test_combined_results_has_discovery_results(self, actions):
        """Local.CombinedResultsJson Concatenate() includes discovery_results key with all 6 agents."""
        combine_action = None
        for action in actions:
            if (
                action.get("kind") == "SetVariable"
                and action.get("variable") == "Local.CombinedResultsJson"
            ):
                combine_action = action
                break

        assert combine_action is not None, (
            "SetVariable for Local.CombinedResultsJson not found"
        )
        value = combine_action.get("value", "")
        assert "discovery_results" in value, (
            "Concatenate() payload should include discovery_results key"
        )

        # Verify all 6 agent result variables are referenced
        expected_results = [
            "Local.TransportResult",
            "Local.POIResult",
            "Local.EventsResult",
            "Local.StayResult",
            "Local.DiningResult",
            "Local.WeatherResult",
        ]
        for var in expected_results:
            assert var in value, (
                f"Concatenate() should reference {var} in discovery_results"
            )

        # Verify all 6 agent keys are present
        expected_keys = ["transport", "poi", "events", "stay", "dining", "weather"]
        for key in expected_keys:
            assert key in value, (
                f"Concatenate() should include '{key}' key in discovery_results"
            )

    def test_combined_results_uses_concatenate(self, actions):
        """Local.CombinedResultsJson uses Concatenate() function (not object expression)."""
        combine_action = None
        for action in actions:
            if (
                action.get("kind") == "SetVariable"
                and action.get("variable") == "Local.CombinedResultsJson"
            ):
                combine_action = action
                break

        assert combine_action is not None
        value = combine_action.get("value", "")
        assert "Concatenate(" in value, (
            "Should use Concatenate() function, not object expression syntax"
        )
        # Should NOT use object expression syntax
        assert not value.strip().startswith("={"), (
            "Should not use ={ object expression syntax"
        )

    def test_combined_results_msg_wraps_with_usermessage(self, actions):
        """Local.CombinedResultsMsg wraps Local.CombinedResultsJson with UserMessage()."""
        wrap_action = None
        for action in actions:
            if (
                action.get("kind") == "SetVariable"
                and action.get("variable") == "Local.CombinedResultsMsg"
            ):
                wrap_action = action
                break

        assert wrap_action is not None, (
            "SetVariable for Local.CombinedResultsMsg not found"
        )
        value = wrap_action.get("value", "")
        assert "UserMessage" in value, (
            "Local.CombinedResultsMsg should use UserMessage() wrapper"
        )
        assert "Local.CombinedResultsJson" in value, (
            "Local.CombinedResultsMsg should reference Local.CombinedResultsJson"
        )

    def test_aggregator_receives_message(self, invoke_agent_actions):
        """Aggregator InvokeAzureAgent uses Local.CombinedResultsMsg as input."""
        aggregator_actions = [
            a for a in invoke_agent_actions
            if a.get("agent", {}).get("name") == "aggregator"
        ]
        assert len(aggregator_actions) == 1, (
            "Expected exactly one aggregator InvokeAzureAgent"
        )
        action = aggregator_actions[0]
        messages = action.get("input", {}).get("messages", "")
        assert "Local.CombinedResultsMsg" in messages, (
            f"Aggregator should receive Local.CombinedResultsMsg, got {messages}"
        )

    def test_aggregator_autosend_false(self, invoke_agent_actions):
        """Aggregator InvokeAzureAgent has autoSend: false."""
        aggregator_actions = [
            a for a in invoke_agent_actions
            if a.get("agent", {}).get("name") == "aggregator"
        ]
        assert len(aggregator_actions) == 1
        auto_send = aggregator_actions[0].get("output", {}).get("autoSend")
        assert auto_send is False, (
            f"Aggregator should have autoSend: false, got {auto_send}"
        )

    def test_aggregator_output_mapped_to_local_result(self, invoke_agent_actions):
        """Aggregator InvokeAzureAgent maps output.text to Local.AggregatedResult."""
        aggregator_actions = [
            a for a in invoke_agent_actions
            if a.get("agent", {}).get("name") == "aggregator"
        ]
        assert len(aggregator_actions) == 1
        output_text = aggregator_actions[0].get("output", {}).get("text")
        assert output_text == "Local.AggregatedResult", (
            f"Aggregator output.text should be 'Local.AggregatedResult', got '{output_text}'"
        )

    def test_combine_results_comes_after_all_discovery_agents(self, actions):
        """combine_results SetVariable appears after all 6 discovery agent invocations."""
        discovery_agents = {"transport", "poi", "events", "stay", "dining", "weather-proxy"}
        found_agents = set()
        for action in actions:
            if action.get("kind") == "InvokeAzureAgent":
                agent_name = action.get("agent", {}).get("name", "")
                if agent_name in discovery_agents:
                    found_agents.add(agent_name)
            if (
                action.get("kind") == "SetVariable"
                and action.get("variable") == "Local.CombinedResultsJson"
            ):
                assert found_agents == discovery_agents, (
                    f"combine_results found before all discovery agents. "
                    f"Missing: {discovery_agents - found_agents}"
                )
                return

        pytest.fail("combine_results SetVariable not found")

    def test_wrap_combined_results_comes_after_combine(self, actions):
        """wrap_combined_results comes after combine_results."""
        combine_idx = None
        wrap_idx = None
        for i, action in enumerate(actions):
            if (
                action.get("kind") == "SetVariable"
                and action.get("variable") == "Local.CombinedResultsJson"
            ):
                combine_idx = i
            if (
                action.get("kind") == "SetVariable"
                and action.get("variable") == "Local.CombinedResultsMsg"
            ):
                wrap_idx = i

        assert combine_idx is not None, "combine_results SetVariable not found"
        assert wrap_idx is not None, "wrap_combined_results SetVariable not found"
        assert wrap_idx > combine_idx, (
            "wrap_combined_results must come after combine_results"
        )

    def test_aggregator_comes_after_wrap(self, actions):
        """Aggregator invocation comes after wrap_combined_results."""
        wrap_idx = None
        agg_idx = None
        for i, action in enumerate(actions):
            if (
                action.get("kind") == "SetVariable"
                and action.get("variable") == "Local.CombinedResultsMsg"
            ):
                wrap_idx = i
            if (
                action.get("kind") == "InvokeAzureAgent"
                and action.get("agent", {}).get("name") == "aggregator"
            ):
                agg_idx = i

        assert wrap_idx is not None, "wrap_combined_results SetVariable not found"
        assert agg_idx is not None, "Aggregator InvokeAzureAgent not found"
        assert agg_idx > wrap_idx, (
            "Aggregator invocation must come after wrap_combined_results"
        )


class TestWorkflowStructure:
    """Test overall workflow structure."""

    def test_workflow_kind(self, workflow):
        """Workflow has kind: workflow."""
        assert workflow["kind"] == "workflow"

    def test_workflow_has_trigger(self, workflow):
        """Workflow has a trigger section."""
        assert "trigger" in workflow

    def test_trigger_is_conversation_start(self, workflow):
        """Trigger is OnConversationStart."""
        assert workflow["trigger"]["kind"] == "OnConversationStart"

    def test_workflow_has_name(self, workflow):
        """Workflow has a name."""
        assert "name" in workflow
        assert workflow["name"]  # not empty


# --- INTEROP-011C3 Tests ---


class TestRouteAgentWiring:
    """Test that the Route agent receives the aggregated result and has autoSend: true."""

    def test_route_receives_aggregated_result(self, invoke_agent_actions):
        """Route InvokeAzureAgent uses Local.AggregatedResultMsg as input."""
        route_actions = [
            a for a in invoke_agent_actions
            if a.get("agent", {}).get("name") == "route"
        ]
        assert len(route_actions) == 1, (
            "Expected exactly one route InvokeAzureAgent"
        )
        action = route_actions[0]
        messages = action.get("input", {}).get("messages", "")
        assert "Local.AggregatedResultMsg" in messages, (
            f"Route agent should receive Local.AggregatedResultMsg, got {messages}"
        )

    def test_route_autosend_true(self, invoke_agent_actions):
        """Route InvokeAzureAgent has autoSend: true to send final itinerary to user."""
        route_actions = [
            a for a in invoke_agent_actions
            if a.get("agent", {}).get("name") == "route"
        ]
        assert len(route_actions) == 1
        auto_send = route_actions[0].get("output", {}).get("autoSend")
        assert auto_send is True, (
            f"Route agent should have autoSend: true, got {auto_send}"
        )

    def test_aggregated_result_msg_wraps_with_usermessage(self, actions):
        """Local.AggregatedResultMsg wraps Local.AggregatedResult with UserMessage()."""
        wrap_action = None
        for action in actions:
            if (
                action.get("kind") == "SetVariable"
                and action.get("variable") == "Local.AggregatedResultMsg"
            ):
                wrap_action = action
                break

        assert wrap_action is not None, (
            "SetVariable for Local.AggregatedResultMsg not found"
        )
        value = wrap_action.get("value", "")
        assert "UserMessage" in value, (
            "Local.AggregatedResultMsg should use UserMessage() wrapper"
        )
        assert "Local.AggregatedResult" in value, (
            "Local.AggregatedResultMsg should reference Local.AggregatedResult"
        )

    def test_wrap_aggregated_comes_after_aggregator(self, actions):
        """wrap_aggregated_result comes after aggregator invocation."""
        agg_idx = None
        wrap_idx = None
        for i, action in enumerate(actions):
            if (
                action.get("kind") == "InvokeAzureAgent"
                and action.get("agent", {}).get("name") == "aggregator"
            ):
                agg_idx = i
            if (
                action.get("kind") == "SetVariable"
                and action.get("variable") == "Local.AggregatedResultMsg"
            ):
                wrap_idx = i

        assert agg_idx is not None, "Aggregator InvokeAzureAgent not found"
        assert wrap_idx is not None, (
            "SetVariable for Local.AggregatedResultMsg not found"
        )
        assert wrap_idx > agg_idx, (
            "wrap_aggregated_result must come after aggregator invocation"
        )

    def test_route_comes_after_wrap_aggregated(self, actions):
        """Route invocation comes after wrap_aggregated_result."""
        wrap_idx = None
        route_idx = None
        for i, action in enumerate(actions):
            if (
                action.get("kind") == "SetVariable"
                and action.get("variable") == "Local.AggregatedResultMsg"
            ):
                wrap_idx = i
            if (
                action.get("kind") == "InvokeAzureAgent"
                and action.get("agent", {}).get("name") == "route"
            ):
                route_idx = i

        assert wrap_idx is not None, (
            "SetVariable for Local.AggregatedResultMsg not found"
        )
        assert route_idx is not None, "Route InvokeAzureAgent not found"
        assert route_idx > wrap_idx, (
            "Route invocation must come after wrap_aggregated_result"
        )

    def test_route_has_conversation_id(self, invoke_agent_actions):
        """Route InvokeAzureAgent references System.ConversationId."""
        route_actions = [
            a for a in invoke_agent_actions
            if a.get("agent", {}).get("name") == "route"
        ]
        assert len(route_actions) == 1
        conv_id = route_actions[0].get("conversationId", "")
        assert "System.ConversationId" in conv_id, (
            "Route agent should reference System.ConversationId"
        )


class TestConfigIncludesDeclarative:
    """Test that foundry/config.yaml includes the declarative workflow entry."""

    CONFIG_PATH = Path(__file__).resolve().parents[5] / (
        "interoperability/foundry/config.yaml"
    )

    def test_config_includes_declarative(self):
        """foundry/config.yaml includes discovery_declarative workflow."""
        assert self.CONFIG_PATH.exists(), (
            f"Config not found at {self.CONFIG_PATH}"
        )
        with open(self.CONFIG_PATH) as f:
            config = yaml.safe_load(f)

        workflows = config.get("workflows", {})
        assert "discovery_declarative" in workflows, (
            "config.yaml should include discovery_declarative workflow"
        )

    def test_declarative_workflow_type(self):
        """discovery_declarative workflow has type: declarative."""
        with open(self.CONFIG_PATH) as f:
            config = yaml.safe_load(f)

        workflow = config["workflows"]["discovery_declarative"]
        assert workflow.get("type") == "declarative", (
            f"discovery_declarative should have type: declarative, got {workflow.get('type')}"
        )

    def test_declarative_workflow_agents(self):
        """discovery_declarative workflow references required agents."""
        with open(self.CONFIG_PATH) as f:
            config = yaml.safe_load(f)

        workflow = config["workflows"]["discovery_declarative"]
        agents = workflow.get("agents", [])
        required_agents = {"transport", "poi", "events", "stay", "dining", "aggregator", "route"}
        found = set(agents)
        for agent in required_agents:
            assert agent in found, (
                f"discovery_declarative should reference agent '{agent}'"
            )


class TestDeclarativeWorkflowComplete:
    """Integration test: verify the full declarative workflow is complete and well-formed."""

    def test_declarative_workflow_complete(self, actions, invoke_agent_actions):
        """Full workflow has all required components: init, discovery, combine, aggregate, route."""
        # 1. Check init variables exist
        set_vars = {
            a.get("variable") for a in actions
            if a.get("kind") == "SetVariable"
        }
        assert "Local.TripRequestJson" in set_vars, "Missing Local.TripRequestJson init"
        assert "Local.TripRequestMsg" in set_vars, "Missing Local.TripRequestMsg init"

        # 2. Check all 6 discovery agents
        agent_names = {
            a.get("agent", {}).get("name") for a in invoke_agent_actions
        }
        discovery_agents = {"transport", "poi", "events", "stay", "dining", "weather-proxy"}
        for agent in discovery_agents:
            assert agent in agent_names, f"Missing discovery agent '{agent}'"

        # 3. Check combine step
        assert "Local.CombinedResultsJson" in set_vars, "Missing combine step"
        assert "Local.CombinedResultsMsg" in set_vars, "Missing wrap_combined step"

        # 4. Check aggregator
        assert "aggregator" in agent_names, "Missing aggregator agent"

        # 5. Check route wiring
        assert "Local.AggregatedResultMsg" in set_vars, "Missing wrap_aggregated step"
        assert "route" in agent_names, "Missing route agent"

        # 6. Check route has autoSend: true
        route_actions = [
            a for a in invoke_agent_actions
            if a.get("agent", {}).get("name") == "route"
        ]
        assert route_actions[0].get("output", {}).get("autoSend") is True, (
            "Route agent must have autoSend: true"
        )

        # 7. Total agent count: 6 discovery + aggregator + route = 8
        assert len(invoke_agent_actions) == 8, (
            f"Expected 8 InvokeAzureAgent actions, got {len(invoke_agent_actions)}"
        )
