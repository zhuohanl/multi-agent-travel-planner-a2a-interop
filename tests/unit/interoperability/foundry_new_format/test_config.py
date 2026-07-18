from pathlib import Path

import pytest

from interoperability.foundry_new_format.shared.config import (
    ConfigError,
    load_prompt_agent_specs,
)


ROOT = Path("interoperability/foundry_new_format")


def test_loads_exact_prompt_agent_inventory() -> None:
    specs = load_prompt_agent_specs(ROOT / "config.yaml")

    assert [spec.name for spec in specs] == [
        "travel-planner-transport",
        "travel-planner-poi",
        "travel-planner-events",
        "travel-planner-aggregator",
        "travel-planner-route",
    ]


def test_search_tools_are_limited_to_discovery_agents() -> None:
    specs = {spec.name: spec for spec in load_prompt_agent_specs(ROOT / "config.yaml")}

    assert specs["travel-planner-transport"].tools == ("bing_grounding",)
    assert specs["travel-planner-poi"].tools == ("bing_grounding",)
    assert specs["travel-planner-events"].tools == ("bing_grounding",)
    assert specs["travel-planner-aggregator"].tools == ()
    assert specs["travel-planner-route"].tools == ()


def test_prompt_paths_stay_inside_new_format_folder(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        """
prompt_agents:
  bad:
    definition: prompt_agents/bad.yaml
""".strip(),
        encoding="utf-8",
    )
    definition = tmp_path / "prompt_agents" / "bad.yaml"
    definition.parent.mkdir()
    definition.write_text(
        """
name: travel-planner-bad
description: Invalid definition
prompt_file: ../../foundry/agents/route/prompts.py
tools: []
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="must stay inside"):
        load_prompt_agent_specs(config)
