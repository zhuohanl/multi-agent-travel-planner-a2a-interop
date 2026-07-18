from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when the new-format Foundry configuration is invalid."""


@dataclass(frozen=True)
class PromptAgentSpec:
    name: str
    description: str
    prompt_path: Path
    tools: tuple[str, ...]

    def load_instructions(self) -> str:
        instructions = self.prompt_path.read_text(encoding="utf-8").strip()
        if not instructions:
            raise ConfigError(f"Prompt is empty: {self.prompt_path}")
        return instructions


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Cannot load YAML {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"YAML root must be an object: {path}")
    return value


def _resolve_inside(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    if not resolved_candidate.is_relative_to(resolved_root):
        raise ConfigError(f"Path must stay inside {resolved_root}: {resolved_candidate}")
    return resolved_candidate


def load_prompt_agent_specs(config_path: Path) -> list[PromptAgentSpec]:
    config = _read_yaml(config_path)
    root = config_path.parent
    raw_agents = config.get("prompt_agents")
    if not isinstance(raw_agents, dict) or not raw_agents:
        raise ConfigError("prompt_agents must be a non-empty object")

    specs: list[PromptAgentSpec] = []
    for key, reference in raw_agents.items():
        if not isinstance(reference, dict) or not isinstance(
            reference.get("definition"), str
        ):
            raise ConfigError(f"Prompt agent {key} must reference a definition")
        definition_path = _resolve_inside(root, root / reference["definition"])
        definition = _read_yaml(definition_path)
        name = definition.get("name")
        description = definition.get("description")
        prompt_file = definition.get("prompt_file")
        tools = definition.get("tools", [])
        if not isinstance(name, str) or not name.startswith("travel-planner-"):
            raise ConfigError(f"Invalid new-format agent name in {definition_path}")
        if not isinstance(description, str) or not description.strip():
            raise ConfigError(f"Missing description in {definition_path}")
        if not isinstance(prompt_file, str):
            raise ConfigError(f"Missing prompt_file in {definition_path}")
        if not isinstance(tools, list) or any(
            tool != "bing_grounding" for tool in tools
        ):
            raise ConfigError(f"Unsupported tools in {definition_path}: {tools}")
        prompt_path = _resolve_inside(root, definition_path.parent / prompt_file)
        if not prompt_path.is_file():
            raise ConfigError(f"Prompt file not found: {prompt_path}")
        specs.append(
            PromptAgentSpec(
                name=name,
                description=description.strip(),
                prompt_path=prompt_path,
                tools=tuple(tools),
            )
        )
    return specs
