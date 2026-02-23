"""
Agent Extraction Module for Foundry Deployment

Extracts agent instructions and tools from existing src/agents/ code
for deployment as native Microsoft Foundry Agents (MFA).

Design doc references:
    - Tool Mapping lines 77-84: HostedWebSearchTool() → bing_grounding
    - Native Agent Instruction Extraction lines 86-94: SYSTEM_PROMPT extraction, get_tools() translation
    - Directory Structure lines 1128-1174: Dual-source pattern (src/agents/ vs interoperability/)

Key concepts:
    - Discovery agents (Transport, POI, Events): Extract from src/agents/ using prompt files
    - Workflow support agents (Aggregator, Route): Load from interoperability/foundry/agents/
    - Tool mapping: HostedWebSearchTool() → { kind: bing_grounding }
"""

import ast
import importlib.util
import os
import re
from pathlib import Path
from typing import Any

import yaml

# Default model from environment variable
DEFAULT_MODEL = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4.1")


class ExtractionError(Exception):
    """Error during agent extraction."""

    pass


# Mapping of prompt names to their expected prompt file names
# Based on get_prompt_name() returns in agent classes
AGENT_PROMPT_MAPPING: dict[str, str] = {
    "transport_agent": "transport",
    "poi_search_agent": "search",
    "events_agent": "events",
    "stay_agent": "stay",
    "dining_agent": "dining",
}


def get_project_root() -> Path:
    """Get the project root directory.

    Returns:
        Path to project root (parent of interoperability/).
    """
    # This file is at interoperability/foundry/extract_agent.py
    # Project root is two levels up
    return Path(__file__).parent.parent.parent


def extract_system_prompt(agent_path: str) -> str:
    """Extract system prompt/instructions from an agent in src/agents/.

    The agents use get_prompt_name() to identify which prompt file to load
    from src/prompts/<prompt_name>.txt. This function:
    1. Determines the prompt name from the agent directory name
    2. Loads the prompt content from the prompts directory

    Args:
        agent_path: Path to agent directory relative to project root
                    (e.g., "src/agents/transport_agent")

    Returns:
        The system prompt/instructions as a string.

    Raises:
        ExtractionError: If prompt cannot be extracted.
    """
    project_root = get_project_root()
    agent_dir = project_root / agent_path

    if not agent_dir.exists():
        raise ExtractionError(f"Agent directory not found: {agent_dir}")

    # Get agent directory name to determine prompt file
    agent_name = agent_dir.name

    # Map agent directory name to prompt name
    prompt_name = AGENT_PROMPT_MAPPING.get(agent_name)
    if prompt_name is None:
        raise ExtractionError(
            f"Unknown agent '{agent_name}'. Known agents: {list(AGENT_PROMPT_MAPPING.keys())}"
        )

    # Load prompt from src/prompts/<prompt_name>.txt
    prompt_path = project_root / "src" / "prompts" / f"{prompt_name}.txt"
    if not prompt_path.exists():
        raise ExtractionError(f"Prompt file not found: {prompt_path}")

    try:
        return prompt_path.read_text(encoding="utf-8").strip()
    except Exception as e:
        raise ExtractionError(f"Failed to read prompt file: {e}")


def extract_tools(agent_path: str) -> list[str]:
    """Extract tool names from an agent's get_tools() method.

    Parses the agent.py file to find tool instantiations in get_tools().
    This is done via AST parsing to avoid executing the agent code.

    Args:
        agent_path: Path to agent directory relative to project root
                    (e.g., "src/agents/transport_agent")

    Returns:
        List of tool class names (e.g., ["HostedWebSearchTool"]).

    Raises:
        ExtractionError: If tools cannot be extracted.
    """
    project_root = get_project_root()
    agent_file = project_root / agent_path / "agent.py"

    if not agent_file.exists():
        raise ExtractionError(f"Agent file not found: {agent_file}")

    try:
        source = agent_file.read_text(encoding="utf-8")
    except Exception as e:
        raise ExtractionError(f"Failed to read agent file: {e}")

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ExtractionError(f"Failed to parse agent file: {e}")

    tools: list[str] = []

    # Find the get_tools method and extract tool names
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_tools":
            # Look for return statement with a list
            for child in ast.walk(node):
                if isinstance(child, ast.Return) and child.value:
                    # Handle return [ToolClass()] pattern
                    if isinstance(child.value, ast.List):
                        for elt in child.value.elts:
                            tool_name = _extract_tool_name(elt)
                            if tool_name:
                                tools.append(tool_name)
                    # Handle return [ToolClass()] as single Call
                    elif isinstance(child.value, ast.Call):
                        tool_name = _extract_tool_name(child.value)
                        if tool_name:
                            tools.append(tool_name)

    return tools


def _extract_tool_name(node: ast.AST) -> str | None:
    """Extract tool class name from an AST node.

    Handles patterns like:
    - HostedWebSearchTool()
    - SomeModule.HostedWebSearchTool()

    Args:
        node: AST node to extract from.

    Returns:
        Tool class name or None if not a tool call.
    """
    if isinstance(node, ast.Call):
        # Direct call: ToolClass()
        if isinstance(node.func, ast.Name):
            return node.func.id
        # Attribute call: module.ToolClass()
        elif isinstance(node.func, ast.Attribute):
            return node.func.attr
    return None


def map_tool_to_foundry(tool_name: str) -> dict[str, Any] | None:
    """Map a Python tool class to Foundry YAML tool definition.

    Per design doc (lines 77-84):
    - HostedWebSearchTool() → { kind: bing_grounding }

    Args:
        tool_name: Python tool class name.

    Returns:
        Foundry tool definition dict, or None for unknown tools.
    """
    tool_mapping: dict[str, dict[str, Any]] = {
        "HostedWebSearchTool": {"kind": "bing_grounding"},
    }
    return tool_mapping.get(tool_name)


def map_tools_to_foundry(tool_names: list[str]) -> list[dict[str, Any]]:
    """Map a list of Python tool names to Foundry tool definitions.

    Args:
        tool_names: List of Python tool class names.

    Returns:
        List of Foundry tool definitions.
    """
    tools = []
    for name in tool_names:
        mapped = map_tool_to_foundry(name)
        if mapped:
            tools.append(mapped)
    return tools


def load_prompts_from_interop(agent_path: str) -> str:
    """Load prompts from an interoperability agent's prompts.py file.

    For workflow support agents (Aggregator, Route), instructions are defined
    in interoperability/foundry/agents/<agent>/prompts.py rather than extracted
    from src/agents/.

    The prompts.py file should define a SYSTEM_PROMPT constant.

    Args:
        agent_path: Path to agent directory relative to project root
                    (e.g., "interoperability/foundry/agents/aggregator")

    Returns:
        The system prompt/instructions as a string.

    Raises:
        ExtractionError: If prompts cannot be loaded.
    """
    project_root = get_project_root()
    prompts_file = project_root / agent_path / "prompts.py"

    if not prompts_file.exists():
        raise ExtractionError(f"Prompts file not found: {prompts_file}")

    try:
        source = prompts_file.read_text(encoding="utf-8")
    except Exception as e:
        raise ExtractionError(f"Failed to read prompts file: {e}")

    # Extract SYSTEM_PROMPT constant using AST
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ExtractionError(f"Failed to parse prompts file: {e}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SYSTEM_PROMPT":
                    # Handle string constant
                    if isinstance(node.value, ast.Constant) and isinstance(
                        node.value.value, str
                    ):
                        return node.value.value.strip()
                    # Handle triple-quoted strings (also ast.Constant in Python 3.8+)
                    elif isinstance(node.value, ast.Str):  # Python 3.7 compatibility
                        return node.value.s.strip()

    raise ExtractionError(f"SYSTEM_PROMPT not found in {prompts_file}")


def load_agent_yaml_from_interop(agent_path: str) -> dict[str, Any] | None:
    """Load agent.yaml directly from an interoperability agent directory.

    If an agent.yaml file exists in the agent directory, it can be loaded
    directly without extraction. This is useful for agents that have
    pre-defined YAML configurations.

    Args:
        agent_path: Path to agent directory relative to project root
                    (e.g., "interoperability/foundry/agents/aggregator")

    Returns:
        Parsed YAML content as dict, or None if agent.yaml doesn't exist.

    Raises:
        ExtractionError: If YAML exists but cannot be parsed.
    """
    project_root = get_project_root()
    yaml_file = project_root / agent_path / "agent.yaml"

    if not yaml_file.exists():
        return None

    try:
        with open(yaml_file) as f:
            content = yaml.safe_load(f)
        return content
    except yaml.YAMLError as e:
        raise ExtractionError(f"Failed to parse agent.yaml: {e}")


def generate_native_agent_yaml(
    agent_name: str,
    instructions: str,
    tools: list[dict[str, Any]],
    model: str = DEFAULT_MODEL,
    description: str = "",
) -> str:
    """Generate native agent YAML definition for Foundry deployment.

    Produces YAML compatible with Microsoft Foundry Agent definitions.

    Args:
        agent_name: Name of the agent.
        instructions: System prompt/instructions for the agent.
        tools: List of Foundry tool definitions (e.g., [{ kind: bing_grounding }]).
        model: Model deployment name.
        description: Optional agent description.

    Returns:
        YAML string defining the agent.
    """
    agent_def: dict[str, Any] = {
        "name": agent_name,
        "model": model,
        "instructions": instructions,
    }

    if description:
        agent_def["description"] = description

    # Always include tools section (empty list if no tools)
    agent_def["tools"] = tools

    # Use block scalar style for instructions to preserve formatting
    yaml_content = yaml.dump(
        agent_def,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )

    return yaml_content


def extract_agent_for_foundry(
    agent_name: str,
    source_path: str,
    model: str = DEFAULT_MODEL,
    description: str = "",
) -> dict[str, Any]:
    """Extract agent configuration for Foundry deployment.

    This is the main entry point for agent extraction. It handles both:
    - src/agents/ extraction (for discovery agents)
    - interoperability/ loading (for workflow support agents)

    Args:
        agent_name: Name of the agent.
        source_path: Path to agent directory relative to project root.
        model: Model deployment name.
        description: Optional agent description.

    Returns:
        Dictionary with extracted configuration:
        - instructions: System prompt
        - tools: Foundry tool definitions
        - yaml: Generated YAML string
        - source_type: "src_agents" or "interoperability"
    """
    project_root = get_project_root()

    # Determine extraction method based on source path
    if source_path.startswith("interoperability/"):
        # Workflow support agents - load from interoperability/
        return _extract_from_interoperability(
            agent_name, source_path, model, description, project_root
        )
    else:
        # Discovery agents - extract from src/agents/
        return _extract_from_src_agents(
            agent_name, source_path, model, description
        )


def _extract_from_src_agents(
    agent_name: str,
    source_path: str,
    model: str,
    description: str,
) -> dict[str, Any]:
    """Extract agent from src/agents/ directory.

    Args:
        agent_name: Name of the agent.
        source_path: Path to agent directory.
        model: Model deployment name.
        description: Optional agent description.

    Returns:
        Extracted configuration dictionary.
    """
    # Extract instructions from prompt file
    instructions = extract_system_prompt(source_path)

    # Extract and map tools
    tool_names = extract_tools(source_path)
    tools = map_tools_to_foundry(tool_names)

    # Generate YAML
    yaml_content = generate_native_agent_yaml(
        agent_name=agent_name,
        instructions=instructions,
        tools=tools,
        model=model,
        description=description,
    )

    return {
        "instructions": instructions,
        "tools": tools,
        "tool_names": tool_names,
        "yaml": yaml_content,
        "source_type": "src_agents",
    }


def _extract_from_interoperability(
    agent_name: str,
    source_path: str,
    model: str,
    description: str,
    project_root: Path,
) -> dict[str, Any]:
    """Load agent from interoperability/ directory.

    Tries to load from agent.yaml first, then falls back to prompts.py.

    Args:
        agent_name: Name of the agent.
        source_path: Path to agent directory.
        model: Model deployment name.
        description: Optional agent description.
        project_root: Path to project root.

    Returns:
        Extracted configuration dictionary.

    Raises:
        ExtractionError: If neither agent.yaml nor prompts.py is found.
    """
    # Try to load pre-defined agent.yaml first
    yaml_content_dict = load_agent_yaml_from_interop(source_path)
    if yaml_content_dict is not None:
        # Use the pre-defined YAML
        instructions = yaml_content_dict.get("instructions", "")
        tools = yaml_content_dict.get("tools", [])

        yaml_content = yaml.dump(
            yaml_content_dict,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

        return {
            "instructions": instructions,
            "tools": tools,
            "tool_names": [],  # Not extracted from code
            "yaml": yaml_content,
            "source_type": "interoperability_yaml",
        }

    # Fall back to prompts.py
    agent_dir = project_root / source_path
    prompts_file = agent_dir / "prompts.py"

    if prompts_file.exists():
        instructions = load_prompts_from_interop(source_path)
        # Workflow support agents typically have no tools
        tools: list[dict[str, Any]] = []

        yaml_content = generate_native_agent_yaml(
            agent_name=agent_name,
            instructions=instructions,
            tools=tools,
            model=model,
            description=description,
        )

        return {
            "instructions": instructions,
            "tools": tools,
            "tool_names": [],
            "yaml": yaml_content,
            "source_type": "interoperability_prompts",
        }

    raise ExtractionError(
        f"Agent at {source_path} has neither agent.yaml nor prompts.py"
    )
