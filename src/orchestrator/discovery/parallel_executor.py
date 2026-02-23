"""
Parallel discovery executor for running multiple discovery agents concurrently.

This module implements parallel execution of discovery agents using asyncio.gather.
It handles partial failures gracefully, aggregating successful results while
logging and reporting failures.

Key features:
- Parallel execution significantly reduces discovery time
- return_exceptions=True ensures one slow or failing agent doesn't block others
- Local progress tracking avoids race conditions during parallel execution
- Single DB write after all agents complete (no clobber)
- Progress callback support for SSE streaming

Per design doc Long-Running Operations section:
- Uses asyncio.gather for concurrent agent calls
- Handles timeouts, failures, and partial success
- Progress tracking is done in memory to avoid race conditions
- SSE streaming provides real-time feedback during long operations
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.orchestrator.streaming.progress import ProgressChannel, ProgressUpdate
    from src.shared.a2a.client_wrapper import A2AClientWrapper

# Type alias for progress callback
ProgressCallback = Callable[["ProgressUpdate"], Coroutine[Any, Any, None]]
RequestBuilder = Callable[["TripSpec", str], str]

logger = logging.getLogger(__name__)


# Discovery agent names - matches design doc
DISCOVERY_AGENTS: tuple[str, ...] = ("transport", "stay", "poi", "events", "dining")


# Per-agent timeouts (seconds) - different agents have different expected latencies
AGENT_TIMEOUTS: dict[str, float] = {
    "transport": 30.0,  # Flight searches can be slow
    "stay": 25.0,  # Hotel searches moderate
    "poi": 20.0,  # POI searches usually fast
    "events": 20.0,  # Event searches vary
    "dining": 15.0,  # Restaurant searches usually fast
}

# Default timeout for agents not in AGENT_TIMEOUTS
DEFAULT_AGENT_TIMEOUT: float = 30.0


class DiscoveryStatus(str, Enum):
    """Status of an individual agent's discovery result."""

    SUCCESS = "success"  # Agent completed successfully
    ERROR = "error"  # Agent failed with error
    TIMEOUT = "timeout"  # Agent exceeded timeout


@dataclass
class AgentDiscoveryResult:
    """
    Result from a single discovery agent.

    Contains the discovery results for one agent (transport, stay, etc.)
    along with status information for error handling.
    """

    status: DiscoveryStatus
    data: Any | None = None  # The actual discovery results
    message: str | None = None  # Error message or status info
    retry_possible: bool = False  # Whether this agent can be retried
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_successful(self) -> bool:
        """Check if this result represents a successful discovery."""
        return self.status == DiscoveryStatus.SUCCESS

    def is_error(self) -> bool:
        """Check if this result represents an error or timeout."""
        return self.status in (DiscoveryStatus.ERROR, DiscoveryStatus.TIMEOUT)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "status": self.status.value,
            "data": self.data,
            "message": self.message,
            "retry_possible": self.retry_possible,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentDiscoveryResult:
        """Create from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        elif timestamp is None:
            timestamp = datetime.now(timezone.utc)

        status_str = data.get("status", "error")
        try:
            status = DiscoveryStatus(status_str)
        except ValueError:
            status = DiscoveryStatus.ERROR

        return cls(
            status=status,
            data=data.get("data"),
            message=data.get("message"),
            retry_possible=data.get("retry_possible", False),
            timestamp=timestamp,
        )


@dataclass
class DiscoveryResults:
    """
    Aggregated results from all discovery agents.

    Contains results from each agent type, allowing for partial success
    where some agents complete successfully and others fail.
    """

    transport: AgentDiscoveryResult | None = None
    stay: AgentDiscoveryResult | None = None
    poi: AgentDiscoveryResult | None = None
    events: AgentDiscoveryResult | None = None
    dining: AgentDiscoveryResult | None = None

    @property
    def successful_agents(self) -> list[str]:
        """Get list of agent names that completed successfully."""
        agents = []
        for agent in DISCOVERY_AGENTS:
            result = getattr(self, agent, None)
            if result is not None and result.is_successful():
                agents.append(agent)
        return agents

    @property
    def failed_agents(self) -> list[str]:
        """Get list of agent names that failed or timed out."""
        agents = []
        for agent in DISCOVERY_AGENTS:
            result = getattr(self, agent, None)
            if result is not None and result.is_error():
                agents.append(agent)
        return agents

    @property
    def has_any_results(self) -> bool:
        """Check if at least one agent returned results."""
        return len(self.successful_agents) > 0

    @property
    def is_complete(self) -> bool:
        """Check if all agents completed successfully."""
        return len(self.successful_agents) == len(DISCOVERY_AGENTS)

    @property
    def is_partial(self) -> bool:
        """Check if some (but not all) agents succeeded."""
        successes = len(self.successful_agents)
        return 0 < successes < len(DISCOVERY_AGENTS)

    def get_result(self, agent: str) -> AgentDiscoveryResult | None:
        """Get result for a specific agent."""
        return getattr(self, agent, None)

    def set_result(self, agent: str, result: AgentDiscoveryResult) -> None:
        """Set result for a specific agent."""
        if agent in DISCOVERY_AGENTS:
            setattr(self, agent, result)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            agent: getattr(self, agent).to_dict()
            if getattr(self, agent) is not None
            else None
            for agent in DISCOVERY_AGENTS
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiscoveryResults:
        """Create from dictionary."""
        results = cls()
        for agent in DISCOVERY_AGENTS:
            agent_data = data.get(agent)
            if agent_data is not None:
                setattr(results, agent, AgentDiscoveryResult.from_dict(agent_data))
        return results


@runtime_checkable
class AgentRegistryProtocol(Protocol):
    """Protocol for agent registry that provides agent URLs."""

    def get_agent_url(self, agent_name: str) -> str | None:
        """Get URL for an agent by name."""
        ...

    def get(self, agent_name: str) -> Any:
        """Get agent config by name (must include a url attribute)."""
        ...


@dataclass
class TripSpec:
    """
    Trip specification for discovery queries.

    Contains the information needed to query discovery agents.
    This is a simplified version - the actual TripSpec may have more fields.
    """

    destination: str
    start_date: str
    end_date: str
    travelers: int = 1
    budget: str | None = None
    preferences: dict[str, Any] = field(default_factory=dict)

    def to_query_message(self) -> str:
        """Convert to a query message for agents."""
        parts = [
            f"Find options for a trip to {self.destination}",
            f"from {self.start_date} to {self.end_date}",
            f"for {self.travelers} traveler{'s' if self.travelers > 1 else ''}",
        ]
        if self.budget:
            parts.append(f"with budget {self.budget}")
        return " ".join(parts)


class ParallelDiscoveryExecutor:
    """
    Executor for running discovery agents in parallel.

    Uses asyncio.gather with return_exceptions=True to ensure partial
    failures don't crash the entire operation. Progress is tracked
    in memory to avoid race conditions during parallel execution.

    Supports optional progress callbacks for SSE streaming:
    - Set a progress_channel to enable streaming
    - Progress updates are published as agents start/complete/fail
    """

    def __init__(
        self,
        a2a_client: A2AClientWrapper | None = None,
        agent_registry: AgentRegistryProtocol | None = None,
        agent_timeouts: dict[str, float] | None = None,
        progress_channel: ProgressChannel | None = None,
        request_builder: RequestBuilder | None = None,
    ) -> None:
        """
        Initialize the parallel executor.

        Args:
            a2a_client: A2A client for making agent calls
            agent_registry: Registry providing agent URLs
            agent_timeouts: Optional custom timeouts per agent
            progress_channel: Optional channel for streaming progress updates
            request_builder: Optional callable for agent-specific request text
        """
        self._a2a_client = a2a_client
        self._agent_registry = agent_registry
        self._agent_timeouts = agent_timeouts or AGENT_TIMEOUTS.copy()
        self._progress_channel = progress_channel
        self._request_builder = request_builder

    def get_timeout(self, agent: str) -> float:
        """Get timeout for an agent."""
        return self._agent_timeouts.get(agent, DEFAULT_AGENT_TIMEOUT)

    async def _publish_progress(
        self,
        event_type: str,
        agent: str | None = None,
        message: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        """
        Publish a progress update if a channel is configured.

        Args:
            event_type: The type of progress event
            agent: Optional agent name
            message: Optional message
            data: Optional additional data
        """
        if self._progress_channel is None:
            return

        # Import here to avoid circular imports
        from src.orchestrator.streaming.progress import ProgressUpdate

        update = ProgressUpdate(
            type=event_type,
            agent=agent,
            message=message,
            data=data,
        )
        try:
            await self._progress_channel.publish(update)
        except Exception as e:
            logger.warning("Failed to publish progress update: %s", e)

    async def execute_single_agent(
        self,
        agent: str,
        trip_spec: TripSpec,
    ) -> AgentDiscoveryResult:
        """
        Execute a single discovery agent with timeout handling.

        Publishes progress updates if a channel is configured:
        - AGENT_STARTED when the agent begins
        - AGENT_COMPLETED on success
        - AGENT_TIMEOUT on timeout
        - AGENT_FAILED on error

        Args:
            agent: Name of the discovery agent (transport, stay, etc.)
            trip_spec: Trip specification for the query

        Returns:
            AgentDiscoveryResult with success or error status
        """
        timeout = self.get_timeout(agent)

        # Publish agent started
        await self._publish_progress(
            event_type="agent_started",
            agent=agent,
            message=f"Starting {agent} search...",
        )

        try:
            async with asyncio.timeout(timeout):
                result = await self._call_agent(agent, trip_spec)
                logger.info(f"Discovery agent '{agent}' completed successfully")

                # Publish agent completed
                await self._publish_progress(
                    event_type="agent_completed",
                    agent=agent,
                    message=f"{agent.title()} search completed",
                    data={"status": "success"},
                )

                return AgentDiscoveryResult(
                    status=DiscoveryStatus.SUCCESS,
                    data=result,
                    message=None,
                    retry_possible=False,
                )

        except asyncio.TimeoutError:
            logger.warning(f"Discovery agent '{agent}' timed out after {timeout}s")

            # Publish agent timeout
            await self._publish_progress(
                event_type="agent_timeout",
                agent=agent,
                message=f"{agent.title()} search timed out after {timeout}s",
                data={"timeout_seconds": timeout},
            )

            return AgentDiscoveryResult(
                status=DiscoveryStatus.TIMEOUT,
                data=None,
                message=f"Timeout after {timeout}s",
                retry_possible=True,
            )

        except Exception as e:
            logger.error(f"Discovery agent '{agent}' failed: {e}")

            # Publish agent failed
            await self._publish_progress(
                event_type="agent_failed",
                agent=agent,
                message=f"{agent.title()} search failed: {e}",
                data={"error": str(e)},
            )

            return AgentDiscoveryResult(
                status=DiscoveryStatus.ERROR,
                data=None,
                message=str(e),
                retry_possible=True,
            )

    async def _call_agent(
        self,
        agent: str,
        trip_spec: TripSpec,
    ) -> Any:
        """
        Make the actual A2A call to a discovery agent.

        This method is separated to allow for easy mocking in tests.

        Args:
            agent: Name of the discovery agent
            trip_spec: Trip specification for the query

        Returns:
            Agent response data
        """
        if self._a2a_client is None:
            # Stub mode for testing - return mock data
            logger.debug(f"No A2A client configured, returning stub data for '{agent}'")
            return {
                "agent": agent,
                "results": [],
                "stub": True,
                "query": trip_spec.to_query_message(),
            }

        if self._agent_registry is None:
            raise ValueError("Agent registry required when A2A client is configured")

        agent_url: str | None = None
        if hasattr(self._agent_registry, "get_agent_url"):
            agent_url = self._agent_registry.get_agent_url(agent)  # type: ignore[call-arg]
        if agent_url is None and hasattr(self._agent_registry, "get"):
            agent_config = self._agent_registry.get(agent)  # type: ignore[call-arg]
            agent_url = getattr(agent_config, "url", None)
        if agent_url is None:
            raise ValueError(f"No URL found for agent '{agent}'")

        message = (
            self._request_builder(trip_spec, agent)
            if self._request_builder
            else trip_spec.to_query_message()
        )

        response = await self._a2a_client.send_message(
            agent_url=agent_url,
            message=message,
        )

        return {
            "text": response.text,
            "context_id": response.context_id,
            "is_complete": response.is_complete,
        }

    async def execute_parallel(
        self,
        trip_spec: TripSpec,
        agents: tuple[str, ...] | list[str] | None = None,
    ) -> DiscoveryResults:
        """
        Execute multiple discovery agents in parallel.

        Uses asyncio.gather with return_exceptions=True to handle partial
        failures. All agents run concurrently, and results are aggregated.

        Args:
            trip_spec: Trip specification for the queries
            agents: Optional list of agents to run. Defaults to all DISCOVERY_AGENTS.

        Returns:
            DiscoveryResults with results from all agents
        """
        if agents is None:
            agents = DISCOVERY_AGENTS

        logger.info(f"Starting parallel discovery for {len(agents)} agents: {agents}")

        # Create tasks for all agents
        tasks = [
            self.execute_single_agent(agent, trip_spec)
            for agent in agents
        ]

        # Execute all tasks concurrently
        # return_exceptions=True ensures one failure doesn't cancel others
        task_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Aggregate results
        results = DiscoveryResults()
        for agent, task_result in zip(agents, task_results):
            if isinstance(task_result, Exception):
                # Handle unexpected exceptions from gather
                logger.error(f"Unexpected exception for '{agent}': {task_result}")
                results.set_result(
                    agent,
                    AgentDiscoveryResult(
                        status=DiscoveryStatus.ERROR,
                        data=None,
                        message=str(task_result),
                        retry_possible=True,
                    ),
                )
            else:
                results.set_result(agent, task_result)

        # Log summary
        successful = len(results.successful_agents)
        failed = len(results.failed_agents)
        logger.info(
            f"Parallel discovery complete: {successful} succeeded, {failed} failed"
        )

        return results


async def execute_parallel_discovery(
    trip_spec: TripSpec,
    agents: tuple[str, ...] | list[str] | None = None,
    a2a_client: A2AClientWrapper | None = None,
    agent_registry: AgentRegistryProtocol | None = None,
    agent_timeouts: dict[str, float] | None = None,
    progress_channel: ProgressChannel | None = None,
    request_builder: RequestBuilder | None = None,
) -> DiscoveryResults:
    """
    Convenience function to execute parallel discovery.

    Creates a ParallelDiscoveryExecutor and runs the parallel execution.

    Args:
        trip_spec: Trip specification for the queries
        agents: Optional list of agents to run
        a2a_client: Optional A2A client for agent calls
        agent_registry: Optional agent registry for URLs
        agent_timeouts: Optional custom timeouts per agent
        progress_channel: Optional channel for streaming progress updates
        request_builder: Optional callable for agent-specific request text

    Returns:
        DiscoveryResults with results from all agents
    """
    executor = ParallelDiscoveryExecutor(
        a2a_client=a2a_client,
        agent_registry=agent_registry,
        agent_timeouts=agent_timeouts,
        progress_channel=progress_channel,
        request_builder=request_builder,
    )
    return await executor.execute_parallel(trip_spec, agents)
