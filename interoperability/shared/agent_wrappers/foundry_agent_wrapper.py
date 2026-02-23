"""
Foundry Agent Wrapper for native Microsoft Foundry Agents (MFA).

This wrapper handles deployment of native agents to Azure AI Foundry.
Native agents are prompt-based agents that use PromptAgentDefinition
and are invoked via the Foundry conversations/responses API.

Used for: Transport, POI, Events, Aggregator, Route agents
"""

import ast
import re
from pathlib import Path
from typing import Any

from .base_wrapper import AgentConfig, BaseAgentWrapper


class FoundryAgentWrapper(BaseAgentWrapper):
    """Wrapper for deploying agents as native Microsoft Foundry Agents.

    Native agents extract their configuration from existing Agent Framework
    code in src/agents/ and deploy as prompt-based agents on Foundry.

    The wrapper extracts:
    - Instructions from SYSTEM_PROMPT or load_prompt() calls
    - Tools from get_tools() return value
    - Maps HostedWebSearchTool() to bing_grounding tool kind
    """

    # Mapping from Agent Framework tools to Foundry tool kinds
    TOOL_MAPPING = {
        "HostedWebSearchTool": {"kind": "bing_grounding"},
    }

    def wrap(self) -> None:
        """Extract agent configuration from source code.

        Reads the agent.py file from the source path and extracts:
        - SYSTEM_PROMPT or instructions via load_prompt()
        - Tools from get_tools() method

        Raises:
            FileNotFoundError: If agent.py is not found.
            ValueError: If required elements are missing.
        """
        agent_file = self._find_agent_file()
        if not agent_file:
            raise FileNotFoundError(
                f"Could not find agent.py in {self.source_path}"
            )

        source_code = agent_file.read_text()

        # Extract instructions
        self._instructions = self._extract_instructions(source_code, agent_file)

        # Extract and map tools
        raw_tools = self._extract_tools(source_code)
        self._tools = self._map_tools_to_foundry(raw_tools)

        self._wrapped = True

    def _find_agent_file(self) -> Path | None:
        """Find the agent.py file in the source path.

        Returns:
            Path to agent.py if found, None otherwise.
        """
        # Check if source_path is absolute or relative
        if self.source_path.is_absolute():
            base_path = self.source_path
        else:
            # Assume relative to project root
            base_path = Path.cwd() / self.source_path

        # Try direct agent.py
        agent_file = base_path / "agent.py"
        if agent_file.exists():
            return agent_file

        # Try src/agents/<name>/agent.py pattern
        if not base_path.exists():
            # Try with src/ prefix
            src_path = Path.cwd() / "src" / "agents" / self.source_path.name / "agent.py"
            if src_path.exists():
                return src_path

        return None

    def _extract_instructions(self, source_code: str, agent_file: Path) -> str:
        """Extract instructions from the agent source code.

        Tries multiple methods:
        1. Direct SYSTEM_PROMPT variable
        2. load_prompt() call in get_instructions()
        3. Instructions from the agent's prompt file

        Args:
            source_code: The source code content.
            agent_file: Path to the agent.py file.

        Returns:
            The extracted instructions string.

        Raises:
            ValueError: If no instructions could be found.
        """
        # Try to find SYSTEM_PROMPT constant
        match = re.search(
            r'SYSTEM_PROMPT\s*=\s*["\']+(.*?)["\']+',
            source_code,
            re.DOTALL,
        )
        if match:
            return match.group(1)

        # Try to find get_prompt_name() and load from prompts directory
        prompt_name_match = re.search(
            r'def\s+get_prompt_name\s*\([^)]*\)\s*->\s*str\s*:\s*return\s*["\'](\w+)["\']',
            source_code,
        )
        if prompt_name_match:
            prompt_name = prompt_name_match.group(1)
            return self._load_prompt_file(prompt_name, agent_file)

        # Try to parse AST for more complex cases
        try:
            tree = ast.parse(source_code)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "get_prompt_name":
                    for stmt in node.body:
                        if isinstance(stmt, ast.Return) and isinstance(
                            stmt.value, ast.Constant
                        ):
                            prompt_name = stmt.value.value
                            return self._load_prompt_file(prompt_name, agent_file)
        except SyntaxError:
            pass

        raise ValueError(
            f"Could not extract instructions from {agent_file}. "
            "Expected SYSTEM_PROMPT constant or get_prompt_name() method."
        )

    def _load_prompt_file(self, prompt_name: str, agent_file: Path) -> str:
        """Load prompt from the prompts directory.

        Args:
            prompt_name: Name of the prompt file (without extension).
            agent_file: Path to the agent.py file (used to find prompts dir).

        Returns:
            The prompt content.

        Raises:
            ValueError: If prompt file is not found.
        """
        # Try common prompt locations
        prompts_dirs = [
            agent_file.parent.parent.parent / "prompts",  # src/prompts/
            agent_file.parent / "prompts",  # agent dir prompts/
            Path.cwd() / "src" / "prompts",  # project src/prompts/
        ]

        for prompts_dir in prompts_dirs:
            prompt_file = prompts_dir / f"{prompt_name}.txt"
            if prompt_file.exists():
                return prompt_file.read_text().strip()

            # Also try .md extension
            prompt_file_md = prompts_dir / f"{prompt_name}.md"
            if prompt_file_md.exists():
                return prompt_file_md.read_text().strip()

        raise ValueError(
            f"Could not find prompt file '{prompt_name}' in any prompts directory"
        )

    def _extract_tools(self, source_code: str) -> list[str]:
        """Extract tool names from get_tools() method.

        Args:
            source_code: The source code content.

        Returns:
            List of tool class names used by the agent.
        """
        tools = []

        # Try to find get_tools() method and extract tool instantiations
        match = re.search(
            r'def\s+get_tools\s*\([^)]*\).*?return\s*\[(.*?)\]',
            source_code,
            re.DOTALL,
        )
        if match:
            tools_content = match.group(1)
            # Find tool instantiations like HostedWebSearchTool()
            tool_matches = re.findall(r'(\w+Tool)\s*\(\)', tools_content)
            tools.extend(tool_matches)

        return tools

    def _map_tools_to_foundry(self, raw_tools: list[str]) -> list[dict[str, Any]]:
        """Map Agent Framework tools to Foundry tool definitions.

        Args:
            raw_tools: List of tool class names.

        Returns:
            List of Foundry tool definitions.
        """
        foundry_tools = []
        for tool in raw_tools:
            if tool in self.TOOL_MAPPING:
                foundry_tools.append(self.TOOL_MAPPING[tool])
            else:
                # Unknown tool - log warning but continue
                print(f"Warning: Unknown tool '{tool}' - skipping")

        return foundry_tools

    def get_config(self) -> dict[str, Any]:
        """Get the Foundry agent YAML configuration.

        Returns:
            Dictionary suitable for writing to agent.yaml.

        Raises:
            RuntimeError: If wrap() has not been called.
        """
        self._ensure_wrapped()

        config: dict[str, Any] = {
            "name": self.name,
            "type": "native",
            "instructions": self._instructions,
            "model": self._config.model,
        }

        # Only include tools if there are any
        if self._tools:
            config["tools"] = self._tools
        else:
            config["tools"] = []

        return config

    def deploy(self, dry_run: bool = False) -> dict[str, Any]:
        """Deploy the agent to Azure AI Foundry.

        Args:
            dry_run: If True, only print what would be deployed.

        Returns:
            Deployment result dictionary.

        Raises:
            RuntimeError: If wrap() has not been called.
        """
        self._ensure_wrapped()

        config = self.get_config()

        if dry_run:
            return {
                "success": True,
                "agent_id": None,
                "message": f"[DRY RUN] Would deploy native agent '{self.name}' with config: {config}",
                "config": config,
            }

        # Actual deployment would use AIProjectClient
        # This is a placeholder - actual implementation depends on Azure SDK
        return {
            "success": False,
            "agent_id": None,
            "message": "Actual deployment not yet implemented. Use --dry-run to preview.",
            "config": config,
        }
