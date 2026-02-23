"""
Prompts module for Transport Agent.

This module provides access to the Transport agent's system prompt
by using the extract_agent module to load from the canonical source.

The prompt content comes from src/prompts/transport.txt and is
extracted via the foundry extract_agent module to ensure consistency
between the local development agent and the Foundry deployment.

Design doc references:
    - Native Agent Instruction Extraction lines 86-94
    - Tool Mapping lines 77-84
"""

from interoperability.foundry.extract_agent import extract_system_prompt


def get_system_prompt() -> str:
    """Get the Transport agent's system prompt.

    Extracts the prompt from src/prompts/transport.txt via the
    extract_agent module. This ensures the Foundry-deployed agent
    uses the same instructions as the local development agent.

    Returns:
        The system prompt string.
    """
    return extract_system_prompt("src/agents/transport_agent")


# For direct module access when loading via extract_agent
SYSTEM_PROMPT = get_system_prompt()
