"""Tests for INTEROP-011C4: Test declarative workflow in Local Agent Playground.

Validates that the declarative workflow YAML:
- Loads correctly in playground-compatible format (valid YAML, correct structure)
- SetVariable nodes initialize correctly with proper types
- Concatenate() expression produces valid JSON when agent results are substituted

These tests simulate what the Local Agent Playground does when loading
and validating a declarative workflow YAML file.
"""

import json
import re
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


# --- Test: YAML loads in playground ---


class TestYamlLoadsInPlayground:
    """Test that the workflow YAML is valid and loadable by the Local Agent Playground."""

    def test_yaml_loads_without_error(self, workflow):
        """Workflow YAML parses without YAML syntax errors."""
        assert workflow is not None, "YAML parsed to None"

    def test_workflow_has_required_top_level_keys(self, workflow):
        """Workflow has all required top-level keys for playground compatibility."""
        assert "kind" in workflow, "Missing 'kind' top-level key"
        assert "trigger" in workflow, "Missing 'trigger' top-level key"
        assert "name" in workflow, "Missing 'name' top-level key"

    def test_workflow_kind_is_workflow(self, workflow):
        """Workflow kind must be 'workflow' for playground to load it."""
        assert workflow["kind"] == "workflow", (
            f"Expected kind 'workflow', got '{workflow['kind']}'"
        )

    def test_trigger_has_kind_and_actions(self, workflow):
        """Trigger must have 'kind' and 'actions' for playground to process it."""
        trigger = workflow["trigger"]
        assert "kind" in trigger, "Trigger missing 'kind'"
        assert "actions" in trigger, "Trigger missing 'actions'"
        assert isinstance(trigger["actions"], list), "Trigger actions must be a list"

    def test_all_actions_have_kind(self, actions):
        """Every action must have a 'kind' field for playground dispatch."""
        for i, action in enumerate(actions):
            assert "kind" in action, (
                f"Action at index {i} missing 'kind' field: {action}"
            )

    def test_all_actions_have_valid_kind(self, actions):
        """Every action has a recognized kind (SetVariable or InvokeAzureAgent)."""
        valid_kinds = {"SetVariable", "InvokeAzureAgent", "SendActivity"}
        for i, action in enumerate(actions):
            assert action["kind"] in valid_kinds, (
                f"Action at index {i} has unrecognized kind '{action['kind']}'. "
                f"Valid kinds: {valid_kinds}"
            )

    def test_all_actions_have_id(self, actions):
        """Every action should have an 'id' field for playground node identification."""
        for i, action in enumerate(actions):
            # id is recommended but not always required by the playground
            # We test that our workflow has them for debuggability
            if action.get("kind") in ("SetVariable", "InvokeAzureAgent"):
                assert "id" in action, (
                    f"Action at index {i} (kind={action['kind']}) missing 'id' field"
                )

    def test_no_duplicate_action_ids(self, actions):
        """All action IDs must be unique to avoid playground conflicts."""
        ids = [a.get("id") for a in actions if "id" in a]
        duplicates = [id_ for id_ in ids if ids.count(id_) > 1]
        assert not duplicates, (
            f"Duplicate action IDs found: {set(duplicates)}"
        )


# --- Test: SetVariable initialization ---


class TestSetVariableInitialization:
    """Test that SetVariable nodes initialize correctly with proper variable names and values."""

    def test_all_setvariables_have_variable_field(self, setvariable_actions):
        """Every SetVariable action has a 'variable' field."""
        for action in setvariable_actions:
            assert "variable" in action, (
                f"SetVariable '{action.get('id', '?')}' missing 'variable' field"
            )

    def test_all_setvariables_have_value_field(self, setvariable_actions):
        """Every SetVariable action has a 'value' field."""
        for action in setvariable_actions:
            assert "value" in action, (
                f"SetVariable '{action.get('id', '?')}' missing 'value' field"
            )

    def test_all_variables_use_local_prefix(self, setvariable_actions):
        """All SetVariable targets use Local.* namespace (playground requirement)."""
        for action in setvariable_actions:
            variable = action.get("variable", "")
            assert variable.startswith("Local."), (
                f"SetVariable '{action.get('id', '?')}' variable '{variable}' "
                f"must use Local.* namespace"
            )

    def test_triprequest_json_initializes_from_system(self, setvariable_actions):
        """Local.TripRequestJson initializes from System.LastMessageText (system input)."""
        trip_vars = [
            a for a in setvariable_actions
            if a.get("variable") == "Local.TripRequestJson"
        ]
        assert len(trip_vars) == 1, "Expected exactly one Local.TripRequestJson SetVariable"
        value = trip_vars[0]["value"]
        assert "System.LastMessageText" in value, (
            f"TripRequestJson should reference System.LastMessageText, got {value}"
        )

    def test_triprequest_msg_wraps_json_with_usermessage(self, setvariable_actions):
        """Local.TripRequestMsg wraps Local.TripRequestJson with UserMessage()."""
        msg_vars = [
            a for a in setvariable_actions
            if a.get("variable") == "Local.TripRequestMsg"
        ]
        assert len(msg_vars) == 1, "Expected exactly one Local.TripRequestMsg SetVariable"
        value = msg_vars[0]["value"]
        assert "UserMessage" in value, (
            f"TripRequestMsg should use UserMessage(), got {value}"
        )
        assert "Local.TripRequestJson" in value, (
            f"TripRequestMsg should reference Local.TripRequestJson, got {value}"
        )

    def test_combined_results_json_uses_concatenate(self, setvariable_actions):
        """Local.CombinedResultsJson uses Concatenate() function."""
        combine_vars = [
            a for a in setvariable_actions
            if a.get("variable") == "Local.CombinedResultsJson"
        ]
        assert len(combine_vars) == 1, (
            "Expected exactly one Local.CombinedResultsJson SetVariable"
        )
        value = combine_vars[0]["value"]
        assert "Concatenate(" in value, (
            f"CombinedResultsJson should use Concatenate(), got value starting with: "
            f"{str(value)[:80]}"
        )

    def test_combined_results_msg_wraps_json(self, setvariable_actions):
        """Local.CombinedResultsMsg wraps Local.CombinedResultsJson with UserMessage()."""
        msg_vars = [
            a for a in setvariable_actions
            if a.get("variable") == "Local.CombinedResultsMsg"
        ]
        assert len(msg_vars) == 1, (
            "Expected exactly one Local.CombinedResultsMsg SetVariable"
        )
        value = msg_vars[0]["value"]
        assert "UserMessage" in value and "Local.CombinedResultsJson" in value

    def test_aggregated_result_msg_wraps_result(self, setvariable_actions):
        """Local.AggregatedResultMsg wraps Local.AggregatedResult with UserMessage()."""
        wrap_vars = [
            a for a in setvariable_actions
            if a.get("variable") == "Local.AggregatedResultMsg"
        ]
        assert len(wrap_vars) == 1, (
            "Expected exactly one Local.AggregatedResultMsg SetVariable"
        )
        value = wrap_vars[0]["value"]
        assert "UserMessage" in value and "Local.AggregatedResult" in value


# --- Test: Concatenate() produces valid JSON ---


class TestConcatenateProducesValidJson:
    """Test that the Concatenate() expression produces valid JSON when variables are substituted.

    The Concatenate() function in Foundry declarative workflows concatenates
    string arguments. We simulate this by substituting sample agent response
    JSON into the template and verifying the result is valid JSON.
    """

    # Sample agent responses for substitution
    SAMPLE_TRIP_REQUEST = json.dumps({
        "destination": "Paris",
        "start_date": "2026-06-01",
        "end_date": "2026-06-05",
        "num_travelers": 2,
        "interests": ["museums", "food"],
    })

    SAMPLE_AGENT_RESULTS = {
        "Local.TransportResult": json.dumps({
            "flights": [{"airline": "Air France", "price": 450}]
        }),
        "Local.POIResult": json.dumps({
            "pois": [{"name": "Eiffel Tower", "type": "landmark"}]
        }),
        "Local.EventsResult": json.dumps({
            "events": [{"name": "Jazz Festival", "date": "2026-06-02"}]
        }),
        "Local.StayResult": json.dumps({
            "hotels": [{"name": "Hotel Le Marais", "price_per_night": 150}]
        }),
        "Local.DiningResult": json.dumps({
            "restaurants": [{"name": "Le Comptoir", "cuisine": "French"}]
        }),
        "Local.WeatherResult": json.dumps({
            "location": "Paris",
            "forecasts": [{"date": "2026-06-01", "condition": "Sunny", "high_temp_c": 24.0}],
            "summary": "Mostly sunny with pleasant temperatures",
        }),
    }

    def _extract_concatenate_template(self, actions):
        """Extract the Concatenate() expression from the combine_results SetVariable."""
        for action in actions:
            if (
                action.get("kind") == "SetVariable"
                and action.get("variable") == "Local.CombinedResultsJson"
            ):
                return action.get("value", "")
        pytest.fail("Local.CombinedResultsJson SetVariable not found")

    def _simulate_concatenate(self, template: str, variables: dict) -> str:
        """Simulate the Foundry Concatenate() function by extracting args and joining.

        The template looks like (after YAML parsing):
          =Concatenate(
            "{""trip_request"":", Local.TripRequestJson,
            ",""discovery_results"":{",
            ...
          )

        In Foundry's expression language, "" inside a string literal represents
        a literal double-quote character. Arguments to Concatenate() are
        separated by commas, where each argument is either a string literal
        (enclosed in "") or a variable reference (Local.* identifier).

        We parse the arguments respecting quoted strings and replace variable
        references with sample values.
        """
        # Strip leading = and outer Concatenate(...)
        inner = template.strip()
        if inner.startswith("="):
            inner = inner[1:]
        inner = inner.strip()

        # Remove outer Concatenate( ... )
        if inner.startswith("Concatenate("):
            inner = inner[len("Concatenate("):]
            # Remove trailing )
            if inner.rstrip().endswith(")"):
                inner = inner.rstrip()[:-1]

        # Parse Concatenate() arguments respecting quoted strings.
        # In Foundry expression language:
        # - String literals are enclosed in " ... " with "" for escaped quotes
        # - Variable references are bare identifiers like Local.TripRequestJson
        # - Arguments separated by commas
        parts = []
        i = 0
        chars = inner.strip()

        while i < len(chars):
            # Skip whitespace and newlines
            if chars[i] in (' ', '\n', '\r', '\t'):
                i += 1
                continue

            # Skip commas (argument separators)
            if chars[i] == ',':
                i += 1
                continue

            # String literal: starts with "
            if chars[i] == '"':
                # Collect until closing " that isn't followed by another "
                j = i + 1
                literal_chars = []
                while j < len(chars):
                    if chars[j] == '"':
                        # Check if this is an escaped "" or closing "
                        if j + 1 < len(chars) and chars[j + 1] == '"':
                            # Escaped "" -> literal "
                            literal_chars.append('"')
                            j += 2
                        else:
                            # Closing "
                            j += 1
                            break
                    else:
                        literal_chars.append(chars[j])
                        j += 1
                parts.append("".join(literal_chars))
                i = j
                continue

            # Variable reference: starts with a letter (e.g., Local.*)
            if chars[i].isalpha():
                j = i
                while j < len(chars) and chars[j] not in (',', ' ', '\n', '\r', '\t', ')'):
                    j += 1
                var_name = chars[i:j].strip()
                if var_name in variables:
                    parts.append(variables[var_name])
                else:
                    parts.append(f"<{var_name}>")
                i = j
                continue

            # Skip any other character
            i += 1

        return "".join(parts)

    def test_concatenate_produces_valid_json(self, actions):
        """Concatenate() expression produces valid JSON when agent results are substituted."""
        template = self._extract_concatenate_template(actions)

        variables = {
            "Local.TripRequestJson": self.SAMPLE_TRIP_REQUEST,
            **self.SAMPLE_AGENT_RESULTS,
        }

        result = self._simulate_concatenate(template, variables)

        # Should be valid JSON
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError as e:
            pytest.fail(
                f"Concatenate() output is not valid JSON: {e}\n"
                f"Output (first 500 chars): {result[:500]}"
            )

        # Should have trip_request and discovery_results keys
        assert "trip_request" in parsed, (
            "JSON output missing 'trip_request' key"
        )
        assert "discovery_results" in parsed, (
            "JSON output missing 'discovery_results' key"
        )

    def test_concatenate_output_has_all_agent_results(self, actions):
        """Concatenate() output includes all 6 discovery agent results."""
        template = self._extract_concatenate_template(actions)

        variables = {
            "Local.TripRequestJson": self.SAMPLE_TRIP_REQUEST,
            **self.SAMPLE_AGENT_RESULTS,
        }

        result = self._simulate_concatenate(template, variables)
        parsed = json.loads(result)

        discovery = parsed["discovery_results"]
        expected_agents = ["transport", "poi", "events", "stay", "dining", "weather"]
        for agent in expected_agents:
            assert agent in discovery, (
                f"discovery_results missing '{agent}' key"
            )

    def test_concatenate_output_trip_request_is_valid(self, actions):
        """Concatenate() output trip_request matches original TripSpec."""
        template = self._extract_concatenate_template(actions)

        variables = {
            "Local.TripRequestJson": self.SAMPLE_TRIP_REQUEST,
            **self.SAMPLE_AGENT_RESULTS,
        }

        result = self._simulate_concatenate(template, variables)
        parsed = json.loads(result)

        trip = parsed["trip_request"]
        assert trip["destination"] == "Paris"
        assert trip["num_travelers"] == 2

    def test_concatenate_output_agent_data_preserved(self, actions):
        """Concatenate() output preserves agent response data."""
        template = self._extract_concatenate_template(actions)

        variables = {
            "Local.TripRequestJson": self.SAMPLE_TRIP_REQUEST,
            **self.SAMPLE_AGENT_RESULTS,
        }

        result = self._simulate_concatenate(template, variables)
        parsed = json.loads(result)

        # Check transport data preserved
        transport = parsed["discovery_results"]["transport"]
        assert "flights" in transport
        assert transport["flights"][0]["airline"] == "Air France"

        # Check weather data preserved
        weather = parsed["discovery_results"]["weather"]
        assert weather["location"] == "Paris"
        assert "forecasts" in weather

    def test_concatenate_template_references_triprequestjson(self, actions):
        """Concatenate() template references Local.TripRequestJson (not TripRequestMsg)."""
        template = self._extract_concatenate_template(actions)
        assert "Local.TripRequestJson" in template, (
            "Concatenate() should reference Local.TripRequestJson (raw JSON), "
            "not Local.TripRequestMsg (message-wrapped)"
        )
        assert "Local.TripRequestMsg" not in template, (
            "Concatenate() should NOT reference Local.TripRequestMsg "
            "(it's message-wrapped, not raw JSON)"
        )
