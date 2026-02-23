#!/usr/bin/env python3
"""
Provision Azure AI orchestrator agents.

This script creates the 4 pre-provisioned Azure AI agents required by the orchestrator:
  1. Router: Decides workflow_turn vs answer_question (has 5 tools)
  2. Classifier: Classifies user actions (APPROVE, MODIFY, etc.) (has 1 tool)
  3. Planner: Plans which agents to re-run for modifications (has 1 tool)
  4. QA: Answers general/budget questions (no tools - text generation only)

Run this script ONCE during deployment/setup. The output agent IDs should be
saved to environment variables for the orchestrator runtime.

Usage:
    # Provision agents and get their IDs:
    uv run python scripts/provision_azure_agents.py

    # Dry-run to validate configuration without creating agents:
    uv run python scripts/provision_azure_agents.py --dry-run

    # Override endpoint and deployment name:
    uv run python scripts/provision_azure_agents.py \\
        --endpoint "https://your-resource.services.ai.azure.com/api/projects/your-project" \\
        --deployment-name "gpt-4.1"

Environment Variables (if not using command-line arguments):
    PROJECT_ENDPOINT: Azure AI Agent Service endpoint URL
        Format: https://<resource-name>.services.ai.azure.com/api/projects/<project-name>
    AZURE_OPENAI_DEPLOYMENT_NAME: LLM model deployment name

Output:
    The script prints environment variable export lines that should be added
    to your .env file:

        ORCHESTRATOR_ROUTING_AGENT_ID=asst_abc123
        ORCHESTRATOR_CLASSIFIER_AGENT_ID=asst_def456
        ORCHESTRATOR_PLANNER_AGENT_ID=asst_ghi789
        ORCHESTRATOR_QA_AGENT_ID=asst_jkl012

Dependencies:
    Requires azure-ai-agents and azure-identity packages.
    Install with: uv add azure-ai-agents azure-identity
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

if TYPE_CHECKING:
    from azure.ai.agents import AgentsClient

logger = logging.getLogger(__name__)


# =============================================================================
# AGENT CONFIGURATIONS
# =============================================================================

# The 4 orchestrator agent types and their environment variable names
AGENT_TYPES = {
    "router": "ORCHESTRATOR_ROUTING_AGENT_ID",
    "classifier": "ORCHESTRATOR_CLASSIFIER_AGENT_ID",
    "planner": "ORCHESTRATOR_PLANNER_AGENT_ID",
    "qa": "ORCHESTRATOR_QA_AGENT_ID",
}


# Router system prompt - decides workflow_turn vs answer_question
ROUTER_SYSTEM_PROMPT = """You are a routing agent for a travel planning orchestrator.

Your job is to analyze user messages and decide which tool to call:

1. **workflow_turn**: Use for any trip planning, approval, modification, or booking action.
   - Starting a new trip: "I want to plan a trip to Tokyo"
   - Approving plans: "This looks good, let's book it"
   - Modifying plans: "Change the hotel to something cheaper"
   - Booking requests: "Book the flight"

2. **answer_question**: Use for travel questions that don't modify workflow state.
   - General questions: "What's the best time to visit Japan?"
   - Domain-specific questions: "Does the Park Hyatt have a pool?"
   - Budget questions: "How much should I budget for food in Tokyo?"

3. **currency_convert**: Use for currency conversion requests.
   - "How much is 100 USD in Yen?"
   - "Convert 500 euros to dollars"

4. **weather_lookup**: Use for weather forecast requests.
   - "What's the weather like in Tokyo in March?"
   - "Will it rain during my trip?"

5. **timezone_info**: Use for timezone queries.
   - "What time zone is Tokyo in?"
   - "What's the time difference between NYC and Tokyo?"

Always call exactly one tool based on the user's intent."""


# Classifier system prompt - classifies user actions
CLASSIFIER_SYSTEM_PROMPT = """You are an action classifier for a travel planning orchestrator.

Your job is to classify user messages into workflow actions using the classify_action tool.

Available actions:
- APPROVE_TRIP_SPEC: User approves the trip specification (dates, destination, travelers)
- MODIFY_TRIP_SPEC: User wants to change trip details before discovery
- START_DISCOVERY: User wants to begin searching for options (implicit or explicit)
- APPROVE_ITINERARY: User approves the generated itinerary
- MODIFY_ITINERARY: User wants to change the itinerary (e.g., different hotel, dates)
- START_BOOKING: User wants to book the approved itinerary
- CONFIRM_BOOKING: User confirms a pending booking
- CANCEL_BOOKING: User cancels a booking

Consider the current workflow phase when classifying. Call classify_action with your classification."""


# Planner system prompt - plans which agents to re-run
PLANNER_SYSTEM_PROMPT = """You are a modification planner for a travel planning orchestrator.

When a user requests changes to their itinerary, you decide which discovery agents
need to re-run using the plan_modification tool.

Available agents:
- transport: Flights, trains, buses, car rentals
- stay: Hotels, apartments, hostels
- poi: Points of interest, attractions, landmarks
- events: Concerts, shows, sports events
- dining: Restaurants, cafes, food tours

Modification strategies:
- replace: Replace all existing results with new ones
- add: Add new options to existing results
- remove: Remove specific items from results

Examples:
- "Change the hotel" → agents=["stay"], strategy="replace"
- "Add more restaurant options" → agents=["dining"], strategy="add"
- "I don't want the museum visit" → agents=["poi"], strategy="remove"
- "Move my trip dates" → agents=["transport", "stay", "events"], strategy="replace"

Always provide a reason for your selection."""


# QA system prompt - answers general questions (no tools)
QA_SYSTEM_PROMPT = """You are a helpful travel assistant for a travel planning orchestrator.

Answer user questions about travel, destinations, budgeting, and trip planning.
Be concise, accurate, and helpful.

When you have context about the user's trip (destination, dates, etc.), use it
to provide more relevant and personalized answers.

If you don't know something, say so rather than making up information."""


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================

# Tool 1: workflow_turn (for router)
WORKFLOW_TURN_TOOL = {
    "type": "function",
    "function": {
        "name": "workflow_turn",
        "description": (
            "Stateful trip-planning workflow handler. Creates/resumes a workflow, "
            "advances phases, and coordinates downstream agents. Use for any trip "
            "planning, approval, modification, or booking action."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The user's message to process",
                }
            },
            "required": ["message"],
        },
    },
}

# Tool 2: answer_question (for router)
ANSWER_QUESTION_TOOL = {
    "type": "function",
    "function": {
        "name": "answer_question",
        "description": (
            "Answers travel questions. Use for questions that don't modify "
            "workflow state (general travel info, domain-specific questions, etc.)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The user's question",
                },
                "domain": {
                    "type": "string",
                    "enum": [
                        "general",
                        "poi",
                        "stay",
                        "transport",
                        "events",
                        "dining",
                        "budget",
                    ],
                    "description": "Knowledge domain to ground the answer",
                },
            },
            "required": ["question"],
        },
    },
}

# Tool 3: currency_convert (for router)
CURRENCY_CONVERT_TOOL = {
    "type": "function",
    "function": {
        "name": "currency_convert",
        "description": (
            "Converts an amount from one currency to another using current exchange rates."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "amount": {
                    "type": "number",
                    "description": "Amount to convert",
                },
                "from_currency": {
                    "type": "string",
                    "description": "Source currency code (ISO 4217, e.g., USD)",
                },
                "to_currency": {
                    "type": "string",
                    "description": "Target currency code (ISO 4217, e.g., JPY)",
                },
            },
            "required": ["amount", "from_currency", "to_currency"],
        },
    },
}

# Tool 4: weather_lookup (for router)
WEATHER_LOOKUP_TOOL = {
    "type": "function",
    "function": {
        "name": "weather_lookup",
        "description": "Looks up weather forecast for a location and date range.",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "Location (city, region, or country)",
                },
                "date_range": {
                    "type": "string",
                    "description": (
                        "Date range (e.g., '2026-03-10..2026-03-17' or 'March 10-17')"
                    ),
                },
            },
            "required": ["location", "date_range"],
        },
    },
}

# Tool 5: timezone_info (for router)
TIMEZONE_INFO_TOOL = {
    "type": "function",
    "function": {
        "name": "timezone_info",
        "description": (
            "Gets timezone information for a location. Optionally provide a date "
            "for DST-aware results."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "Location (city, region, or country)",
                },
                "date": {
                    "type": "string",
                    "description": (
                        "Optional date for DST-aware result (e.g., '2026-03-15'). "
                        "If omitted, uses current date."
                    ),
                },
            },
            "required": ["location"],
        },
    },
}

# Tool 6: classify_action (for classifier)
CLASSIFY_ACTION_TOOL = {
    "type": "function",
    "function": {
        "name": "classify_action",
        "description": "Classify the user message as a workflow action.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "APPROVE_TRIP_SPEC",
                        "MODIFY_TRIP_SPEC",
                        "START_DISCOVERY",
                        "APPROVE_ITINERARY",
                        "MODIFY_ITINERARY",
                        "START_BOOKING",
                        "CONFIRM_BOOKING",
                        "CANCEL_BOOKING",
                    ],
                    "description": "The classified action type",
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence score 0-1",
                },
            },
            "required": ["action"],
        },
    },
}

# Tool 7: plan_modification (for planner)
PLAN_MODIFICATION_TOOL = {
    "type": "function",
    "function": {
        "name": "plan_modification",
        "description": (
            "Plan which agents need to re-run for a modification request."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "agents": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["transport", "stay", "poi", "events", "dining"],
                    },
                    "description": "Agents that need to re-run",
                },
                "strategy": {
                    "type": "string",
                    "enum": ["replace", "add", "remove"],
                    "description": "How to handle existing results",
                },
                "reason": {
                    "type": "string",
                    "description": "Why these agents were selected",
                },
            },
            "required": ["agents", "strategy"],
        },
    },
}


# Router tools (5 tools)
ROUTING_TOOLS = [
    WORKFLOW_TURN_TOOL,
    ANSWER_QUESTION_TOOL,
    CURRENCY_CONVERT_TOOL,
    WEATHER_LOOKUP_TOOL,
    TIMEZONE_INFO_TOOL,
]

# Classifier tools (1 tool)
CLASSIFICATION_TOOLS = [CLASSIFY_ACTION_TOOL]

# Planner tools (1 tool)
PLANNING_TOOLS = [PLAN_MODIFICATION_TOOL]

# QA tools (no tools - text generation only)
QA_TOOLS: list[dict[str, Any]] = []


@dataclass
class AgentConfig:
    """Configuration for creating an Azure AI agent."""

    name: str
    instructions: str
    tools: list[dict[str, Any]]
    env_var: str


# All agent configurations
AGENT_CONFIGS = {
    "router": AgentConfig(
        name="orchestrator-router-v1",
        instructions=ROUTER_SYSTEM_PROMPT,
        tools=ROUTING_TOOLS,
        env_var="ORCHESTRATOR_ROUTING_AGENT_ID",
    ),
    "classifier": AgentConfig(
        name="orchestrator-classifier-v1",
        instructions=CLASSIFIER_SYSTEM_PROMPT,
        tools=CLASSIFICATION_TOOLS,
        env_var="ORCHESTRATOR_CLASSIFIER_AGENT_ID",
    ),
    "planner": AgentConfig(
        name="orchestrator-planner-v1",
        instructions=PLANNER_SYSTEM_PROMPT,
        tools=PLANNING_TOOLS,
        env_var="ORCHESTRATOR_PLANNER_AGENT_ID",
    ),
    "qa": AgentConfig(
        name="orchestrator-qa-v1",
        instructions=QA_SYSTEM_PROMPT,
        tools=QA_TOOLS,
        env_var="ORCHESTRATOR_QA_AGENT_ID",
    ),
}


# =============================================================================
# AZURE CLIENT HELPERS
# =============================================================================


def _get_azure_agents_imports() -> tuple[Any, Any, Any, Any]:
    """
    Lazily import Azure AI Agents dependencies.

    Returns:
        Tuple of (AgentsClient, DefaultAzureCredential, FunctionToolDefinition, FunctionDefinition)

    Raises:
        ImportError: If required packages are not installed
    """
    try:
        from azure.ai.agents import AgentsClient
        from azure.ai.agents.models import FunctionDefinition, FunctionToolDefinition
        from azure.identity import DefaultAzureCredential

        return (
            AgentsClient,
            DefaultAzureCredential,
            FunctionToolDefinition,
            FunctionDefinition,
        )
    except ImportError as e:
        raise ImportError(
            "azure-ai-agents and azure-identity packages are required. "
            "Install with: uv add azure-ai-agents azure-identity"
        ) from e


def create_agents_client(endpoint: str) -> "AgentsClient":
    """
    Create an AgentsClient from endpoint URL.

    Args:
        endpoint: Azure AI Agent Service endpoint URL

    Returns:
        Configured AgentsClient instance
    """
    AgentsClient, DefaultAzureCredential, _, _ = _get_azure_agents_imports()

    return AgentsClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    )


def validate_endpoint(endpoint: str) -> dict[str, str]:
    """
    Validate and parse Azure AI Agent Service endpoint URL.

    Args:
        endpoint: Azure AI Agent Service endpoint URL

    Returns:
        Dictionary with parsed components

    Raises:
        ValueError: If endpoint format is invalid
    """
    import re

    pattern = r"https://([^.]+)\.services\.ai\.azure\.com/api/projects/([^/]+)"
    match = re.match(pattern, endpoint)

    if not match:
        raise ValueError(
            "Invalid endpoint format. Expected: "
            "https://<resource-name>.services.ai.azure.com/api/projects/<project-name>"
        )

    return {
        "resource_name": match.group(1),
        "project_name": match.group(2),
    }


# =============================================================================
# AGENT PROVISIONING
# =============================================================================


def _convert_tools_to_function_definitions(tools: list[dict[str, Any]]) -> list[Any]:
    """
    Convert tool definitions from dict format to FunctionToolDefinition objects.

    Args:
        tools: List of tool definitions in OpenAI-style dict format

    Returns:
        List of FunctionToolDefinition objects for the SDK API
    """
    _, _, FunctionToolDefinition, FunctionDefinition = _get_azure_agents_imports()

    function_tools = []
    for tool in tools:
        if tool.get("type") == "function":
            func_def = tool["function"]
            function_tools.append(
                FunctionToolDefinition(
                    function=FunctionDefinition(
                        name=func_def["name"],
                        description=func_def.get("description", ""),
                        parameters=func_def.get("parameters", {}),
                    )
                )
            )
    return function_tools


def provision_agent(
    client: "AgentsClient",
    config: AgentConfig,
    deployment_name: str,
    dry_run: bool = False,
) -> str | None:
    """
    Create a single Azure AI agent.

    Args:
        client: AgentsClient instance
        config: Agent configuration
        deployment_name: LLM model deployment name
        dry_run: If True, validate only without creating

    Returns:
        Agent ID if created, None if dry-run
    """
    if dry_run:
        logger.info(f"  [DRY-RUN] Would create agent: {config.name}")
        logger.info(f"    - Model: {deployment_name}")
        logger.info(f"    - Tools: {len(config.tools)}")
        logger.info(f"    - Instructions: {len(config.instructions)} chars")
        return None

    logger.info(f"  Creating agent: {config.name}")

    # Convert tools to FunctionToolDefinition objects
    tools = _convert_tools_to_function_definitions(config.tools) if config.tools else None

    agent = client.create_agent(
        model=deployment_name,
        name=config.name,
        instructions=config.instructions,
        tools=tools,
    )

    logger.info(f"    Created: {agent.id}")
    return agent.id


def provision_all_agents(
    endpoint: str,
    deployment_name: str,
    dry_run: bool = False,
) -> dict[str, str | None]:
    """
    Provision all orchestrator agents.

    Args:
        endpoint: Azure AI Agent Service endpoint URL
        deployment_name: LLM model deployment name
        dry_run: If True, validate only without creating

    Returns:
        Dictionary mapping agent type to agent ID (or None if dry-run)
    """
    # Validate endpoint
    endpoint_info = validate_endpoint(endpoint)
    logger.info(f"Resource: {endpoint_info['resource_name']}")
    logger.info(f"Project: {endpoint_info['project_name']}")
    logger.info(f"Deployment: {deployment_name}")

    if dry_run:
        logger.info("\n[DRY-RUN MODE] - No agents will be created\n")
    else:
        # Create client only if not dry-run
        client = create_agents_client(endpoint)
        logger.info("\nConnected to Azure AI Agent Service\n")

    results: dict[str, str | None] = {}

    for agent_type, config in AGENT_CONFIGS.items():
        logger.info(f"\nProvisioning {agent_type} agent:")

        if dry_run:
            # Validate configuration without creating
            agent_id = provision_agent(
                client=None,  # type: ignore
                config=config,
                deployment_name=deployment_name,
                dry_run=True,
            )
        else:
            agent_id = provision_agent(
                client=client,
                config=config,
                deployment_name=deployment_name,
                dry_run=False,
            )

        results[agent_type] = agent_id

    return results


def print_env_exports(results: dict[str, str | None]) -> None:
    """
    Print environment variable export lines.

    Args:
        results: Dictionary mapping agent type to agent ID
    """
    print("\n" + "=" * 60)
    print("Add these lines to your .env file:")
    print("=" * 60 + "\n")

    for agent_type, agent_id in results.items():
        env_var = AGENT_CONFIGS[agent_type].env_var
        if agent_id:
            print(f'{env_var}="{agent_id}"')
        else:
            print(f'{env_var}=""  # (dry-run, no agent created)')

    print()


# =============================================================================
# MAIN
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Provision Azure AI orchestrator agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Provision agents using environment variables:
    uv run python scripts/provision_azure_agents.py

    # Dry-run to validate configuration:
    uv run python scripts/provision_azure_agents.py --dry-run

    # Override endpoint:
    uv run python scripts/provision_azure_agents.py \\
        --endpoint "https://your-resource.services.ai.azure.com/api/projects/your-project"
""",
    )

    parser.add_argument(
        "--endpoint",
        help=(
            "Azure AI Agent Service endpoint URL. "
            "If not provided, uses PROJECT_ENDPOINT env var."
        ),
    )

    parser.add_argument(
        "--deployment-name",
        help=(
            "LLM model deployment name. "
            "If not provided, uses AZURE_OPENAI_DEPLOYMENT_NAME env var."
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration without creating agents",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
    )

    # Get endpoint
    endpoint = args.endpoint or os.environ.get("PROJECT_ENDPOINT")
    if not endpoint:
        logger.error(
            "Error: Endpoint required.\n"
            "Provide --endpoint or set PROJECT_ENDPOINT"
        )
        return 1

    # Get deployment name
    deployment_name = args.deployment_name or os.environ.get(
        "AZURE_OPENAI_DEPLOYMENT_NAME"
    )
    if not deployment_name:
        logger.error(
            "Error: Deployment name required.\n"
            "Provide --deployment-name or set AZURE_OPENAI_DEPLOYMENT_NAME"
        )
        return 1

    logger.info("=" * 60)
    logger.info("Azure AI Orchestrator Agent Provisioning")
    logger.info("=" * 60 + "\n")

    try:
        results = provision_all_agents(
            endpoint=endpoint,
            deployment_name=deployment_name,
            dry_run=args.dry_run,
        )

        print_env_exports(results)

        if args.dry_run:
            logger.info("Dry-run complete. No agents were created.")
        else:
            logger.info("Provisioning complete!")
            logger.info("Copy the environment variables above to your .env file.")

        return 0

    except ImportError as e:
        logger.error(f"\nError: {e}")
        return 1
    except ValueError as e:
        logger.error(f"\nConfiguration error: {e}")
        return 1
    except Exception as e:
        logger.error(f"\nProvisioning failed: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
