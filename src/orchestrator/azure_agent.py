"""
Azure AI Agent Service wrapper for the orchestrator.

This module provides the runtime interface for the orchestrator's pre-provisioned
Azure AI agents. The agents are created once during deployment via
scripts/provision_azure_agents.py, and this module loads their IDs from
environment variables at runtime.

The orchestrator uses 4 pre-provisioned Azure AI agents:
  - Router: Decides workflow_turn vs answer_question (has 5 tools)
  - Classifier: Classifies user actions (has 1 tool)
  - Planner: Plans which agents to re-run for modifications (has 1 tool)
  - QA: Answers general/budget questions (no tools - text generation only)

Architecture (per design doc "Are These the Same LLM? Threading Strategy"):
  - 4 pre-provisioned agents (different instructions/tools)
  - Each agent type gets its own thread per session to avoid cross-contamination
  - Business context is injected via WorkflowState, not thread history
  - Threads exist for debugging and observability only

Environment Variables (required for runtime):
    PROJECT_ENDPOINT: Azure AI Agent Service endpoint URL
        Format: https://<resource-name>.services.ai.azure.com/api/projects/<project-name>
    AZURE_OPENAI_DEPLOYMENT_NAME: LLM model deployment name
    ORCHESTRATOR_ROUTING_AGENT_ID: Pre-provisioned routing agent ID
    ORCHESTRATOR_CLASSIFIER_AGENT_ID: Pre-provisioned classifier agent ID
    ORCHESTRATOR_PLANNER_AGENT_ID: Pre-provisioned planner agent ID
    ORCHESTRATOR_QA_AGENT_ID: Pre-provisioned Q&A agent ID

Usage:
    from src.orchestrator.azure_agent import OrchestratorLLM, get_orchestrator_llm

    # Load configuration and create LLM instance
    llm = get_orchestrator_llm()

    # Get agent ID by type
    router_id = llm.get_agent_id("router")

    # Make routing decision
    result = await llm.route_decision(session_id, message)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from azure.ai.agents import AgentsClient

logger = logging.getLogger(__name__)


# =============================================================================
# AGENT TYPES AND CONFIGURATION
# =============================================================================


class AgentType(str, Enum):
    """The 4 orchestrator agent types."""

    ROUTER = "router"
    CLASSIFIER = "classifier"
    PLANNER = "planner"
    QA = "qa"


# Environment variable names for each agent type
AGENT_ENV_VARS: dict[AgentType, str] = {
    AgentType.ROUTER: "ORCHESTRATOR_ROUTING_AGENT_ID",
    AgentType.CLASSIFIER: "ORCHESTRATOR_CLASSIFIER_AGENT_ID",
    AgentType.PLANNER: "ORCHESTRATOR_PLANNER_AGENT_ID",
    AgentType.QA: "ORCHESTRATOR_QA_AGENT_ID",
}

# All required environment variables for runtime
REQUIRED_ENV_VARS = [
    "PROJECT_ENDPOINT",
    "AZURE_OPENAI_DEPLOYMENT_NAME",
    *AGENT_ENV_VARS.values(),
]


# =============================================================================
# TOOL SCHEMA BUNDLES
# =============================================================================
# These match the tool definitions in scripts/provision_azure_agents.py
# They are defined here for validation and documentation purposes.


# Tool 1: workflow_turn (for router)
WORKFLOW_TURN_TOOL: dict[str, Any] = {
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
ANSWER_QUESTION_TOOL: dict[str, Any] = {
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
CURRENCY_CONVERT_TOOL: dict[str, Any] = {
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
WEATHER_LOOKUP_TOOL: dict[str, Any] = {
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
TIMEZONE_INFO_TOOL: dict[str, Any] = {
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

# Tool 6: get_booking (for Layer 1b regex lookup - stateless)
GET_BOOKING_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_booking",
        "description": "Retrieves booking details by booking ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "booking_id": {
                    "type": "string",
                    "description": "Booking identifier (e.g., book_abc123)",
                }
            },
            "required": ["booking_id"],
        },
    },
}

# Tool 7: get_consultation (for Layer 1b regex lookup - stateless)
GET_CONSULTATION_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_consultation",
        "description": "Retrieves consultation/trip plan details by consultation ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "consultation_id": {
                    "type": "string",
                    "description": "Consultation identifier (e.g., cons_xyz789)",
                }
            },
            "required": ["consultation_id"],
        },
    },
}

# Tool 8: classify_action (for classifier - not exposed to routing LLM)
CLASSIFY_ACTION_TOOL: dict[str, Any] = {
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

# Tool 9: plan_modification (for planner - not exposed to routing LLM)
PLAN_MODIFICATION_TOOL: dict[str, Any] = {
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


# Tool bundles per agent type (9 tools total across 4 agents)
# Note: get_booking and get_consultation are primarily used via Layer 1b regex,
# not LLM routing. However, we include them in routing tools as LLM fallback
# for cases where regex doesn't match (e.g., "what's the status of my booking")
ROUTING_TOOLS: list[dict[str, Any]] = [
    WORKFLOW_TURN_TOOL,
    ANSWER_QUESTION_TOOL,
    CURRENCY_CONVERT_TOOL,
    WEATHER_LOOKUP_TOOL,
    TIMEZONE_INFO_TOOL,
    GET_BOOKING_TOOL,
    GET_CONSULTATION_TOOL,
]

CLASSIFICATION_TOOLS: list[dict[str, Any]] = [CLASSIFY_ACTION_TOOL]

PLANNING_TOOLS: list[dict[str, Any]] = [PLAN_MODIFICATION_TOOL]

QA_TOOLS: list[dict[str, Any]] = []  # QA uses pure text generation, no tools


# Tool bundles by agent type
TOOL_BUNDLES: dict[AgentType, list[dict[str, Any]]] = {
    AgentType.ROUTER: ROUTING_TOOLS,
    AgentType.CLASSIFIER: CLASSIFICATION_TOOLS,
    AgentType.PLANNER: PLANNING_TOOLS,
    AgentType.QA: QA_TOOLS,
}


# =============================================================================
# CONFIGURATION
# =============================================================================


@dataclass(frozen=True)
class OrchestratorAgentConfig:
    """Configuration for the orchestrator's Azure AI agents.

    This dataclass holds the agent IDs loaded from environment variables.
    It is immutable (frozen) to prevent accidental modification at runtime.
    """

    endpoint: str
    deployment_name: str
    routing_agent_id: str
    classifier_agent_id: str
    planner_agent_id: str
    qa_agent_id: str

    def get_agent_id(self, agent_type: AgentType | str) -> str:
        """Get the agent ID for a given agent type.

        Args:
            agent_type: The agent type (AgentType enum or string)

        Returns:
            The agent ID for the specified type

        Raises:
            ValueError: If agent_type is not recognized
        """
        if isinstance(agent_type, str):
            agent_type = AgentType(agent_type)

        match agent_type:
            case AgentType.ROUTER:
                return self.routing_agent_id
            case AgentType.CLASSIFIER:
                return self.classifier_agent_id
            case AgentType.PLANNER:
                return self.planner_agent_id
            case AgentType.QA:
                return self.qa_agent_id

    @property
    def agent_ids(self) -> dict[AgentType, str]:
        """Return all agent IDs as a dictionary."""
        return {
            AgentType.ROUTER: self.routing_agent_id,
            AgentType.CLASSIFIER: self.classifier_agent_id,
            AgentType.PLANNER: self.planner_agent_id,
            AgentType.QA: self.qa_agent_id,
        }


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""

    pass


def get_missing_env_vars() -> list[str]:
    """Return list of required environment variables that are not set."""
    return [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]


def load_agent_config() -> OrchestratorAgentConfig:
    """Load orchestrator agent configuration from environment variables.

    Returns:
        OrchestratorAgentConfig with all required values

    Raises:
        ConfigurationError: If required environment variables are missing
    """
    missing = get_missing_env_vars()
    if missing:
        raise ConfigurationError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Ensure all agent IDs are configured. "
            "Run 'uv run python scripts/provision_azure_agents.py' to create agents "
            "and get their IDs."
        )

    return OrchestratorAgentConfig(
        endpoint=os.environ["PROJECT_ENDPOINT"],
        deployment_name=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
        routing_agent_id=os.environ["ORCHESTRATOR_ROUTING_AGENT_ID"],
        classifier_agent_id=os.environ["ORCHESTRATOR_CLASSIFIER_AGENT_ID"],
        planner_agent_id=os.environ["ORCHESTRATOR_PLANNER_AGENT_ID"],
        qa_agent_id=os.environ["ORCHESTRATOR_QA_AGENT_ID"],
    )


# =============================================================================
# AZURE CLIENT HELPERS
# =============================================================================


def _get_azure_agents_imports() -> tuple[Any, Any]:
    """Lazily import Azure AI Agents dependencies.

    Returns:
        Tuple of (AgentsClient, DefaultAzureCredential)

    Raises:
        ImportError: If required packages are not installed
    """
    try:
        from azure.ai.agents import AgentsClient
        from azure.identity import DefaultAzureCredential

        return AgentsClient, DefaultAzureCredential
    except ImportError as e:
        raise ImportError(
            "azure-ai-agents and azure-identity packages are required for Azure AI operations. "
            "Install with: uv add azure-ai-agents azure-identity"
        ) from e


def create_agents_client(config: OrchestratorAgentConfig) -> "AgentsClient":
    """Create an AgentsClient from configuration.

    Args:
        config: Orchestrator agent configuration

    Returns:
        Configured AgentsClient instance

    Raises:
        ImportError: If required packages are not installed
    """
    AgentsClient, DefaultAzureCredential = _get_azure_agents_imports()

    return AgentsClient(
        endpoint=config.endpoint,
        credential=DefaultAzureCredential(),
    )


# =============================================================================
# ORCHESTRATOR LLM CLASS
# =============================================================================


class OrchestratorLLM:
    """Azure AI Agent Service wrapper for orchestrator LLM decisions.

    Uses pre-provisioned agent IDs (set during deployment) and
    per-agent threads to avoid cross-contamination.

    The orchestrator uses 4 LLM decision points:
    - LLM #1 (Router): Decides workflow_turn vs answer_question (5 tools)
    - LLM #2 (Classifier): Classifies user actions (1 tool)
    - LLM #3 (Planner): Plans modification re-runs (1 tool)
    - LLM #4 (QA): Answers questions (no tools, pure text)

    Key principle: Each LLM decision must be correct with zero thread history.
    Business context is injected via WorkflowState summaries in the prompt,
    not retrieved from thread history. Threads exist for debugging only.
    """

    # Agent types for thread management
    AGENT_TYPES = list(AgentType)

    def __init__(self, config: OrchestratorAgentConfig) -> None:
        """Initialize the orchestrator LLM wrapper.

        Args:
            config: Orchestrator agent configuration with all agent IDs

        Note:
            This constructor does NOT create agents in Azure. It only
            loads the pre-provisioned agent IDs from configuration.
            Agents are created once during deployment via
            scripts/provision_azure_agents.py.
        """
        self._config = config
        self._client: AgentsClient | None = None

        # Per-agent threads to avoid cross-contamination
        # Structure: session_id -> {agent_type -> thread_id}
        self._session_threads: dict[str, dict[AgentType, str]] = {}

        logger.info(
            "OrchestratorLLM initialized with pre-provisioned agents: %s",
            ", ".join(f"{t.value}={config.get_agent_id(t)[:20]}..." for t in AgentType),
        )

    @property
    def config(self) -> OrchestratorAgentConfig:
        """Return the agent configuration."""
        return self._config

    def get_agent_id(self, agent_type: AgentType | str) -> str:
        """Get the agent ID for a given agent type.

        Args:
            agent_type: The agent type (AgentType enum or string)

        Returns:
            The agent ID for the specified type
        """
        return self._config.get_agent_id(agent_type)

    def get_tools_for_agent(self, agent_type: AgentType | str) -> list[dict[str, Any]]:
        """Get the tool schema bundle for a given agent type.

        Args:
            agent_type: The agent type (AgentType enum or string)

        Returns:
            List of tool definitions for the specified agent
        """
        if isinstance(agent_type, str):
            agent_type = AgentType(agent_type)
        return TOOL_BUNDLES[agent_type]

    @property
    def client(self) -> "AgentsClient":
        """Lazily initialize and return the Azure AI Agents client.

        Returns:
            AgentsClient instance

        Raises:
            ImportError: If Azure packages are not installed
        """
        if self._client is None:
            self._client = create_agents_client(self._config)
        return self._client

    def _ensure_thread_exists(self, session_id: str, agent_type: AgentType) -> str:
        """Get existing thread_id or create new thread for this session/agent_type.

        Each agent type gets its own thread to avoid cross-contamination:
        - Router thread only sees routing decisions
        - Classifier thread only sees classification decisions
        - Planner thread only sees planning decisions
        - QA thread only sees Q&A pairs

        Args:
            session_id: The session identifier
            agent_type: The agent type

        Returns:
            thread_id for this session/agent_type combination

        Note:
            Handles expired threads (Azure TTL) gracefully by creating new ones.
        """
        if session_id not in self._session_threads:
            self._session_threads[session_id] = {}

        agent_threads = self._session_threads[session_id]

        if agent_type in agent_threads:
            try:
                # Verify thread still exists in Azure
                self.client.threads.get(agent_threads[agent_type])
                return agent_threads[agent_type]
            except Exception as e:
                # Thread expired or error - create new one
                logger.info(
                    "Thread expired or error for %s/%s: %s, creating new",
                    session_id,
                    agent_type.value,
                    str(e),
                )

        # Create thread with metadata for debugging/querying
        thread = self.client.threads.create(
            metadata={
                "session_id": session_id,
                "agent_type": agent_type.value,
            }
        )
        agent_threads[agent_type] = thread.id
        logger.debug(
            "Created thread %s for %s/%s",
            thread.id,
            session_id,
            agent_type.value,
        )
        return thread.id

    def get_thread_id(
        self, session_id: str, agent_type: AgentType | str
    ) -> str | None:
        """Get existing thread ID without creating a new one.

        Args:
            session_id: The session identifier
            agent_type: The agent type

        Returns:
            thread_id if it exists, None otherwise
        """
        if isinstance(agent_type, str):
            agent_type = AgentType(agent_type)

        if session_id not in self._session_threads:
            return None
        return self._session_threads[session_id].get(agent_type)

    def clear_session_threads(self, session_id: str) -> None:
        """Clear all threads for a session.

        Use this when a session is terminated or when threads need to be reset.

        Args:
            session_id: The session identifier to clear
        """
        if session_id in self._session_threads:
            del self._session_threads[session_id]
            logger.debug("Cleared threads for session %s", session_id)


# =============================================================================
# MODULE-LEVEL HELPERS
# =============================================================================

# Singleton instance for convenience
_orchestrator_llm: OrchestratorLLM | None = None


def get_orchestrator_llm() -> OrchestratorLLM:
    """Get or create the singleton OrchestratorLLM instance.

    Returns:
        OrchestratorLLM instance

    Raises:
        ConfigurationError: If required environment variables are missing
    """
    global _orchestrator_llm
    if _orchestrator_llm is None:
        config = load_agent_config()
        _orchestrator_llm = OrchestratorLLM(config)
    return _orchestrator_llm


def reset_orchestrator_llm() -> None:
    """Reset the singleton OrchestratorLLM instance.

    Use this for testing or when configuration changes.
    """
    global _orchestrator_llm
    _orchestrator_llm = None
