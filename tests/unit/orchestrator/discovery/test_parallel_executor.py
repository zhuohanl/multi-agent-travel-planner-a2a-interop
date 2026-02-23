"""
Unit tests for parallel discovery executor.

Tests parallel agent execution, partial failure handling, result aggregation,
and timeout behavior.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.orchestrator.discovery.parallel_executor import (
    AGENT_TIMEOUTS,
    DEFAULT_AGENT_TIMEOUT,
    DISCOVERY_AGENTS,
    AgentDiscoveryResult,
    DiscoveryResults,
    DiscoveryStatus,
    ParallelDiscoveryExecutor,
    TripSpec,
    execute_parallel_discovery,
)


class TestAgentDiscoveryResult:
    """Tests for AgentDiscoveryResult dataclass."""

    def test_creation_success(self) -> None:
        """Test creating a successful result."""
        result = AgentDiscoveryResult(
            status=DiscoveryStatus.SUCCESS,
            data={"flights": [{"id": "f1", "price": 500}]},
        )
        assert result.status == DiscoveryStatus.SUCCESS
        assert result.data == {"flights": [{"id": "f1", "price": 500}]}
        assert result.is_successful() is True
        assert result.is_error() is False

    def test_creation_error(self) -> None:
        """Test creating an error result."""
        result = AgentDiscoveryResult(
            status=DiscoveryStatus.ERROR,
            message="Connection failed",
            retry_possible=True,
        )
        assert result.status == DiscoveryStatus.ERROR
        assert result.message == "Connection failed"
        assert result.retry_possible is True
        assert result.is_successful() is False
        assert result.is_error() is True

    def test_creation_timeout(self) -> None:
        """Test creating a timeout result."""
        result = AgentDiscoveryResult(
            status=DiscoveryStatus.TIMEOUT,
            message="Timeout after 30s",
            retry_possible=True,
        )
        assert result.status == DiscoveryStatus.TIMEOUT
        assert result.is_successful() is False
        assert result.is_error() is True

    def test_to_dict(self) -> None:
        """Test serialization to dict."""
        timestamp = datetime(2026, 1, 24, 12, 0, 0, tzinfo=timezone.utc)
        result = AgentDiscoveryResult(
            status=DiscoveryStatus.SUCCESS,
            data={"hotels": []},
            message=None,
            retry_possible=False,
            timestamp=timestamp,
        )
        data = result.to_dict()
        assert data["status"] == "success"
        assert data["data"] == {"hotels": []}
        assert data["message"] is None
        assert data["retry_possible"] is False
        assert "2026-01-24T12:00:00" in data["timestamp"]

    def test_from_dict(self) -> None:
        """Test deserialization from dict."""
        data = {
            "status": "error",
            "data": None,
            "message": "Service unavailable",
            "retry_possible": True,
            "timestamp": "2026-01-24T12:00:00+00:00",
        }
        result = AgentDiscoveryResult.from_dict(data)
        assert result.status == DiscoveryStatus.ERROR
        assert result.data is None
        assert result.message == "Service unavailable"
        assert result.retry_possible is True

    def test_from_dict_invalid_status(self) -> None:
        """Test from_dict with invalid status defaults to ERROR."""
        data = {"status": "invalid_status"}
        result = AgentDiscoveryResult.from_dict(data)
        assert result.status == DiscoveryStatus.ERROR

    def test_round_trip_serialization(self) -> None:
        """Test round-trip serialization."""
        original = AgentDiscoveryResult(
            status=DiscoveryStatus.SUCCESS,
            data={"poi": [{"name": "Tokyo Tower"}]},
            message="Found 5 attractions",
            retry_possible=False,
        )
        data = original.to_dict()
        restored = AgentDiscoveryResult.from_dict(data)

        assert restored.status == original.status
        assert restored.data == original.data
        assert restored.message == original.message
        assert restored.retry_possible == original.retry_possible


class TestDiscoveryResults:
    """Tests for DiscoveryResults dataclass."""

    def test_empty_results(self) -> None:
        """Test empty results."""
        results = DiscoveryResults()
        assert results.successful_agents == []
        assert results.failed_agents == []
        assert results.has_any_results is False
        assert results.is_complete is False
        assert results.is_partial is False

    def test_all_successful(self) -> None:
        """Test all agents successful."""
        results = DiscoveryResults(
            transport=AgentDiscoveryResult(status=DiscoveryStatus.SUCCESS, data={}),
            stay=AgentDiscoveryResult(status=DiscoveryStatus.SUCCESS, data={}),
            poi=AgentDiscoveryResult(status=DiscoveryStatus.SUCCESS, data={}),
            events=AgentDiscoveryResult(status=DiscoveryStatus.SUCCESS, data={}),
            dining=AgentDiscoveryResult(status=DiscoveryStatus.SUCCESS, data={}),
        )
        assert len(results.successful_agents) == 5
        assert results.failed_agents == []
        assert results.has_any_results is True
        assert results.is_complete is True
        assert results.is_partial is False

    def test_partial_success(self) -> None:
        """Test partial success (some agents failed)."""
        results = DiscoveryResults(
            transport=AgentDiscoveryResult(status=DiscoveryStatus.ERROR, message="failed"),
            stay=AgentDiscoveryResult(status=DiscoveryStatus.SUCCESS, data={}),
            poi=AgentDiscoveryResult(status=DiscoveryStatus.SUCCESS, data={}),
            events=AgentDiscoveryResult(status=DiscoveryStatus.TIMEOUT, message="timeout"),
            dining=AgentDiscoveryResult(status=DiscoveryStatus.SUCCESS, data={}),
        )
        assert set(results.successful_agents) == {"stay", "poi", "dining"}
        assert set(results.failed_agents) == {"transport", "events"}
        assert results.has_any_results is True
        assert results.is_complete is False
        assert results.is_partial is True

    def test_all_failed(self) -> None:
        """Test all agents failed."""
        results = DiscoveryResults(
            transport=AgentDiscoveryResult(status=DiscoveryStatus.ERROR),
            stay=AgentDiscoveryResult(status=DiscoveryStatus.ERROR),
            poi=AgentDiscoveryResult(status=DiscoveryStatus.ERROR),
            events=AgentDiscoveryResult(status=DiscoveryStatus.ERROR),
            dining=AgentDiscoveryResult(status=DiscoveryStatus.ERROR),
        )
        assert results.successful_agents == []
        assert len(results.failed_agents) == 5
        assert results.has_any_results is False
        assert results.is_complete is False
        assert results.is_partial is False

    def test_get_result(self) -> None:
        """Test getting result for specific agent."""
        transport_result = AgentDiscoveryResult(
            status=DiscoveryStatus.SUCCESS,
            data={"flights": []},
        )
        results = DiscoveryResults(transport=transport_result)

        assert results.get_result("transport") == transport_result
        assert results.get_result("stay") is None
        assert results.get_result("unknown") is None

    def test_set_result(self) -> None:
        """Test setting result for specific agent."""
        results = DiscoveryResults()
        result = AgentDiscoveryResult(status=DiscoveryStatus.SUCCESS, data={})

        results.set_result("transport", result)
        assert results.transport == result

        # Setting invalid agent should be ignored
        results.set_result("invalid", result)

    def test_to_dict(self) -> None:
        """Test serialization to dict."""
        results = DiscoveryResults(
            transport=AgentDiscoveryResult(status=DiscoveryStatus.SUCCESS, data={}),
            stay=None,
        )
        data = results.to_dict()
        assert data["transport"] is not None
        assert data["transport"]["status"] == "success"
        assert data["stay"] is None

    def test_from_dict(self) -> None:
        """Test deserialization from dict."""
        data = {
            "transport": {"status": "success", "data": {"flights": []}},
            "stay": {"status": "error", "message": "failed"},
            "poi": None,
            "events": None,
            "dining": None,
        }
        results = DiscoveryResults.from_dict(data)

        assert results.transport is not None
        assert results.transport.status == DiscoveryStatus.SUCCESS
        assert results.stay is not None
        assert results.stay.status == DiscoveryStatus.ERROR
        assert results.poi is None


class TestTripSpec:
    """Tests for TripSpec dataclass."""

    def test_creation(self) -> None:
        """Test basic creation."""
        spec = TripSpec(
            destination="Tokyo",
            start_date="2026-03-15",
            end_date="2026-03-21",
            travelers=2,
            budget="$3000",
        )
        assert spec.destination == "Tokyo"
        assert spec.travelers == 2

    def test_to_query_message(self) -> None:
        """Test generating query message."""
        spec = TripSpec(
            destination="Tokyo",
            start_date="2026-03-15",
            end_date="2026-03-21",
            travelers=2,
            budget="$3000",
        )
        message = spec.to_query_message()
        assert "Tokyo" in message
        assert "2026-03-15" in message
        assert "2 travelers" in message
        assert "$3000" in message

    def test_to_query_message_single_traveler(self) -> None:
        """Test query message with single traveler."""
        spec = TripSpec(
            destination="Paris",
            start_date="2026-05-01",
            end_date="2026-05-07",
            travelers=1,
        )
        message = spec.to_query_message()
        assert "1 traveler" in message
        assert "travelers" not in message


class TestParallelDiscoveryExecutor:
    """Tests for ParallelDiscoveryExecutor class."""

    def test_get_timeout_known_agent(self) -> None:
        """Test getting timeout for known agent."""
        executor = ParallelDiscoveryExecutor()
        assert executor.get_timeout("transport") == 30.0
        assert executor.get_timeout("dining") == 15.0

    def test_get_timeout_unknown_agent(self) -> None:
        """Test getting timeout for unknown agent uses default."""
        executor = ParallelDiscoveryExecutor()
        assert executor.get_timeout("unknown_agent") == DEFAULT_AGENT_TIMEOUT

    def test_custom_timeouts(self) -> None:
        """Test using custom timeouts."""
        custom_timeouts = {"transport": 60.0, "stay": 45.0}
        executor = ParallelDiscoveryExecutor(agent_timeouts=custom_timeouts)
        assert executor.get_timeout("transport") == 60.0
        assert executor.get_timeout("stay") == 45.0
        # Agent not in custom timeouts uses default
        assert executor.get_timeout("poi") == DEFAULT_AGENT_TIMEOUT

    @pytest.mark.asyncio
    async def test_execute_single_agent_success_stub_mode(self) -> None:
        """Test executing single agent in stub mode (no A2A client)."""
        executor = ParallelDiscoveryExecutor()
        trip_spec = TripSpec(
            destination="Tokyo",
            start_date="2026-03-15",
            end_date="2026-03-21",
        )

        result = await executor.execute_single_agent("transport", trip_spec)

        assert result.status == DiscoveryStatus.SUCCESS
        assert result.data is not None
        assert result.data["agent"] == "transport"
        assert result.data["stub"] is True

    @pytest.mark.asyncio
    async def test_execute_single_agent_timeout(self) -> None:
        """Test executing single agent with timeout."""
        executor = ParallelDiscoveryExecutor(agent_timeouts={"transport": 0.01})

        # Mock _call_agent to be slow
        async def slow_call(*args: Any, **kwargs: Any) -> dict[str, Any]:
            await asyncio.sleep(1.0)  # Longer than timeout
            return {}

        executor._call_agent = slow_call  # type: ignore

        trip_spec = TripSpec(
            destination="Tokyo",
            start_date="2026-03-15",
            end_date="2026-03-21",
        )

        result = await executor.execute_single_agent("transport", trip_spec)

        assert result.status == DiscoveryStatus.TIMEOUT
        assert "timeout" in result.message.lower()
        assert result.retry_possible is True

    @pytest.mark.asyncio
    async def test_execute_single_agent_error(self) -> None:
        """Test executing single agent with error."""
        executor = ParallelDiscoveryExecutor()

        # Mock _call_agent to raise error
        async def error_call(*args: Any, **kwargs: Any) -> dict[str, Any]:
            raise ValueError("Connection refused")

        executor._call_agent = error_call  # type: ignore

        trip_spec = TripSpec(
            destination="Tokyo",
            start_date="2026-03-15",
            end_date="2026-03-21",
        )

        result = await executor.execute_single_agent("transport", trip_spec)

        assert result.status == DiscoveryStatus.ERROR
        assert "Connection refused" in result.message
        assert result.retry_possible is True


class TestParallelExecutionAllSucceed:
    """Test parallel execution where all agents succeed."""

    @pytest.mark.asyncio
    async def test_parallel_execution_all_succeed(self) -> None:
        """Test all agents execute and succeed in parallel."""
        executor = ParallelDiscoveryExecutor()
        trip_spec = TripSpec(
            destination="Tokyo",
            start_date="2026-03-15",
            end_date="2026-03-21",
        )

        results = await executor.execute_parallel(trip_spec)

        assert results.is_complete is True
        assert len(results.successful_agents) == 5
        assert len(results.failed_agents) == 0

        # Verify each agent has results
        for agent in DISCOVERY_AGENTS:
            result = results.get_result(agent)
            assert result is not None
            assert result.status == DiscoveryStatus.SUCCESS
            assert result.data["agent"] == agent


class TestParallelExecutionPartialFailure:
    """Test parallel execution with partial failures."""

    @pytest.mark.asyncio
    async def test_parallel_execution_partial_failure(self) -> None:
        """Test partial failure doesn't crash entire operation."""
        executor = ParallelDiscoveryExecutor()

        # Track which agents were called
        called_agents: list[str] = []

        async def mixed_call(agent: str, trip_spec: TripSpec) -> dict[str, Any]:
            called_agents.append(agent)
            if agent in ["transport", "events"]:
                raise ValueError(f"{agent} failed")
            return {"agent": agent, "stub": True}

        executor._call_agent = mixed_call  # type: ignore

        trip_spec = TripSpec(
            destination="Tokyo",
            start_date="2026-03-15",
            end_date="2026-03-21",
        )

        results = await executor.execute_parallel(trip_spec)

        # All agents should have been called
        assert set(called_agents) == set(DISCOVERY_AGENTS)

        # Check results
        assert results.is_partial is True
        assert set(results.successful_agents) == {"stay", "poi", "dining"}
        assert set(results.failed_agents) == {"transport", "events"}


class TestParallelExecutionAggregatesResults:
    """Test that parallel execution aggregates results correctly."""

    @pytest.mark.asyncio
    async def test_parallel_execution_aggregates_results(self) -> None:
        """Test results are properly aggregated from all agents."""
        executor = ParallelDiscoveryExecutor()

        # Create distinct data for each agent
        async def distinct_call(agent: str, trip_spec: TripSpec) -> dict[str, Any]:
            return {
                "agent": agent,
                "destination": trip_spec.destination,
                "items": [f"{agent}_item_1", f"{agent}_item_2"],
            }

        executor._call_agent = distinct_call  # type: ignore

        trip_spec = TripSpec(
            destination="Paris",
            start_date="2026-05-01",
            end_date="2026-05-07",
        )

        results = await executor.execute_parallel(trip_spec)

        # Verify each agent's data is preserved
        for agent in DISCOVERY_AGENTS:
            result = results.get_result(agent)
            assert result is not None
            assert result.data["agent"] == agent
            assert result.data["destination"] == "Paris"
            assert f"{agent}_item_1" in result.data["items"]


class TestParallelExecutionLogsFailures:
    """Test that parallel execution logs failures correctly."""

    @pytest.mark.asyncio
    async def test_parallel_execution_logs_failures(self) -> None:
        """Test that failures are logged appropriately."""
        executor = ParallelDiscoveryExecutor()

        async def failing_call(agent: str, trip_spec: TripSpec) -> dict[str, Any]:
            if agent == "transport":
                raise ConnectionError("Network error")
            return {"agent": agent}

        executor._call_agent = failing_call  # type: ignore

        trip_spec = TripSpec(
            destination="Tokyo",
            start_date="2026-03-15",
            end_date="2026-03-21",
        )

        with patch(
            "src.orchestrator.discovery.parallel_executor.logger"
        ) as mock_logger:
            results = await executor.execute_parallel(trip_spec)

            # Verify error was logged
            error_calls = [
                call
                for call in mock_logger.error.call_args_list
                if "transport" in str(call)
            ]
            assert len(error_calls) > 0

        # Result should still be populated
        transport_result = results.get_result("transport")
        assert transport_result is not None
        assert transport_result.status == DiscoveryStatus.ERROR
        assert "Network error" in transport_result.message


class TestParallelExecutionSubsetAgents:
    """Test parallel execution with subset of agents."""

    @pytest.mark.asyncio
    async def test_execute_subset_of_agents(self) -> None:
        """Test executing only a subset of agents."""
        executor = ParallelDiscoveryExecutor()
        trip_spec = TripSpec(
            destination="Tokyo",
            start_date="2026-03-15",
            end_date="2026-03-21",
        )

        # Only run transport and stay
        results = await executor.execute_parallel(trip_spec, agents=["transport", "stay"])

        # Only requested agents should have results
        assert results.transport is not None
        assert results.stay is not None
        assert results.poi is None
        assert results.events is None
        assert results.dining is None


class TestExecuteParallelDiscoveryFunction:
    """Tests for the convenience function execute_parallel_discovery."""

    @pytest.mark.asyncio
    async def test_execute_parallel_discovery_default(self) -> None:
        """Test convenience function with defaults."""
        trip_spec = TripSpec(
            destination="London",
            start_date="2026-06-01",
            end_date="2026-06-07",
        )

        results = await execute_parallel_discovery(trip_spec)

        assert results.is_complete is True
        assert len(results.successful_agents) == 5

    @pytest.mark.asyncio
    async def test_execute_parallel_discovery_with_subset(self) -> None:
        """Test convenience function with agent subset."""
        trip_spec = TripSpec(
            destination="Rome",
            start_date="2026-07-01",
            end_date="2026-07-10",
        )

        results = await execute_parallel_discovery(
            trip_spec,
            agents=["transport", "stay"],
        )

        assert results.transport is not None
        assert results.stay is not None
        assert results.poi is None

    @pytest.mark.asyncio
    async def test_execute_parallel_discovery_with_custom_timeouts(self) -> None:
        """Test convenience function with custom timeouts."""
        trip_spec = TripSpec(
            destination="Sydney",
            start_date="2026-08-01",
            end_date="2026-08-14",
        )

        custom_timeouts = {"transport": 60.0}
        results = await execute_parallel_discovery(
            trip_spec,
            agent_timeouts=custom_timeouts,
        )

        assert results.is_complete is True


class TestConcurrency:
    """Tests verifying actual concurrent execution."""

    @pytest.mark.asyncio
    async def test_agents_run_concurrently(self) -> None:
        """Test that agents actually run concurrently, not sequentially."""
        executor = ParallelDiscoveryExecutor()
        start_times: dict[str, float] = {}
        end_times: dict[str, float] = {}

        async def timed_call(agent: str, trip_spec: TripSpec) -> dict[str, Any]:
            import time

            start_times[agent] = time.time()
            await asyncio.sleep(0.1)  # 100ms delay
            end_times[agent] = time.time()
            return {"agent": agent}

        executor._call_agent = timed_call  # type: ignore

        trip_spec = TripSpec(
            destination="Tokyo",
            start_date="2026-03-15",
            end_date="2026-03-21",
        )

        import time

        overall_start = time.time()
        await executor.execute_parallel(trip_spec)
        overall_duration = time.time() - overall_start

        # If running sequentially, it would take 5 * 0.1 = 0.5 seconds
        # If running concurrently, it should take ~0.1 seconds
        assert overall_duration < 0.3, "Agents should run concurrently, not sequentially"

        # Verify all agents were called
        assert set(start_times.keys()) == set(DISCOVERY_AGENTS)


class TestAgentTimeouts:
    """Tests for AGENT_TIMEOUTS configuration."""

    def test_all_discovery_agents_have_timeouts(self) -> None:
        """Test all discovery agents have configured timeouts."""
        for agent in DISCOVERY_AGENTS:
            assert agent in AGENT_TIMEOUTS, f"Missing timeout for {agent}"

    def test_timeouts_are_reasonable(self) -> None:
        """Test timeout values are within reasonable bounds."""
        for agent, timeout in AGENT_TIMEOUTS.items():
            assert 5.0 <= timeout <= 60.0, f"Timeout for {agent} is outside reasonable bounds"


class TestAgentTimeoutHandling:
    """
    Tests for per-agent timeout handling.

    Per ORCH-048: Implement per-agent timeout handling with asyncio.timeout(),
    graceful degradation, and proper status tracking.
    """

    @pytest.mark.asyncio
    async def test_agent_timeout_handling(self) -> None:
        """
        Test that agent timeouts are handled correctly.

        Verifies:
        - asyncio.timeout wraps the agent call
        - Timeout raises TimeoutError which is caught
        - Result status is set to TIMEOUT
        - Message includes timeout duration
        """
        # Use very short timeout
        executor = ParallelDiscoveryExecutor(agent_timeouts={"transport": 0.01})

        # Make _call_agent take longer than the timeout
        async def slow_agent(agent: str, trip_spec: TripSpec) -> dict[str, Any]:
            await asyncio.sleep(0.5)  # 500ms > 10ms timeout
            return {"result": "should not reach here"}

        executor._call_agent = slow_agent  # type: ignore

        trip_spec = TripSpec(
            destination="Tokyo",
            start_date="2026-03-15",
            end_date="2026-03-21",
        )

        result = await executor.execute_single_agent("transport", trip_spec)

        assert result.status == DiscoveryStatus.TIMEOUT
        assert "0.01" in result.message  # Timeout duration in message
        assert "timeout" in result.message.lower()
        assert result.retry_possible is True
        assert result.data is None

    @pytest.mark.asyncio
    async def test_timeout_marks_agent_failed(self) -> None:
        """
        Test that timed-out agents are properly marked as failed/timeout.

        Verifies:
        - Status is set to TIMEOUT (not SUCCESS or ERROR)
        - is_error() returns True for timeout status
        - is_successful() returns False
        - Agent appears in failed_agents list in DiscoveryResults
        """
        executor = ParallelDiscoveryExecutor(agent_timeouts={"transport": 0.01})

        async def slow_agent(agent: str, trip_spec: TripSpec) -> dict[str, Any]:
            if agent == "transport":
                await asyncio.sleep(0.5)  # Timeout
            return {"agent": agent}

        executor._call_agent = slow_agent  # type: ignore

        trip_spec = TripSpec(
            destination="Paris",
            start_date="2026-05-01",
            end_date="2026-05-07",
        )

        # Execute just the transport agent
        result = await executor.execute_single_agent("transport", trip_spec)

        # Verify the result properties
        assert result.status == DiscoveryStatus.TIMEOUT
        assert result.is_error() is True
        assert result.is_successful() is False

        # Verify it appears in failed_agents when using DiscoveryResults
        results = DiscoveryResults(transport=result)
        assert "transport" in results.failed_agents
        assert "transport" not in results.successful_agents

    @pytest.mark.asyncio
    async def test_timeout_doesnt_block_others(self) -> None:
        """
        Test that one agent timing out doesn't block other agents.

        Verifies:
        - Parallel execution continues for other agents
        - Other agents complete successfully
        - Timed-out agent is marked appropriately
        - Total execution time is bounded by slowest agent, not sum
        """
        import time

        # Transport times out, others succeed quickly
        executor = ParallelDiscoveryExecutor(
            agent_timeouts={
                "transport": 0.05,  # 50ms timeout
                "stay": 30.0,
                "poi": 30.0,
                "events": 30.0,
                "dining": 30.0,
            }
        )

        call_times: dict[str, float] = {}
        completion_times: dict[str, float] = {}

        async def mixed_speed_agents(agent: str, trip_spec: TripSpec) -> dict[str, Any]:
            call_times[agent] = time.time()
            if agent == "transport":
                # This agent will timeout
                await asyncio.sleep(1.0)  # Way longer than 50ms timeout
            else:
                # These agents complete quickly
                await asyncio.sleep(0.02)
            completion_times[agent] = time.time()
            return {"agent": agent}

        executor._call_agent = mixed_speed_agents  # type: ignore

        trip_spec = TripSpec(
            destination="Rome",
            start_date="2026-06-01",
            end_date="2026-06-07",
        )

        start_time = time.time()
        results = await executor.execute_parallel(trip_spec)
        total_time = time.time() - start_time

        # Transport should have timed out
        assert results.transport is not None
        assert results.transport.status == DiscoveryStatus.TIMEOUT

        # Other agents should have succeeded
        for agent in ["stay", "poi", "events", "dining"]:
            result = results.get_result(agent)
            assert result is not None, f"{agent} should have a result"
            assert result.status == DiscoveryStatus.SUCCESS, f"{agent} should succeed"

        # All agents should have been called concurrently (not blocked by timeout)
        assert len(call_times) == 5, "All agents should have been called"

        # Total time should be bounded by the longest operation (transport's timeout ~50ms)
        # plus a bit of overhead, NOT the sum of all agent times
        assert total_time < 0.5, f"Total time {total_time}s suggests agents blocked each other"

        # Verify is_partial status
        assert results.is_partial is True
        assert len(results.successful_agents) == 4
        assert len(results.failed_agents) == 1

    def test_configurable_timeout_per_agent(self) -> None:
        """
        Test that timeouts can be configured per agent type.

        Verifies:
        - Different agents can have different timeouts
        - Custom timeouts override defaults
        - get_timeout() returns correct values
        - Default timeout applies to unknown agents
        """
        # Test default timeouts
        default_executor = ParallelDiscoveryExecutor()
        assert default_executor.get_timeout("transport") == 30.0
        assert default_executor.get_timeout("stay") == 25.0
        assert default_executor.get_timeout("poi") == 20.0
        assert default_executor.get_timeout("events") == 20.0
        assert default_executor.get_timeout("dining") == 15.0

        # Unknown agent gets default
        assert default_executor.get_timeout("unknown") == DEFAULT_AGENT_TIMEOUT

        # Test custom timeouts
        custom_timeouts = {
            "transport": 60.0,  # Increased for slow flight searches
            "stay": 45.0,  # Increased for hotel aggregator
            "poi": 10.0,  # Reduced for fast POI API
            "events": 5.0,  # Very fast event lookup
            # dining not specified - should use default
        }
        custom_executor = ParallelDiscoveryExecutor(agent_timeouts=custom_timeouts)

        assert custom_executor.get_timeout("transport") == 60.0
        assert custom_executor.get_timeout("stay") == 45.0
        assert custom_executor.get_timeout("poi") == 10.0
        assert custom_executor.get_timeout("events") == 5.0
        # dining not in custom, gets default
        assert custom_executor.get_timeout("dining") == DEFAULT_AGENT_TIMEOUT
        # Unknown agent still gets default
        assert custom_executor.get_timeout("unknown") == DEFAULT_AGENT_TIMEOUT

    @pytest.mark.asyncio
    async def test_timeout_logged_with_context(self) -> None:
        """
        Test that timeout events are logged with proper context.

        Verifies:
        - Logger.warning is called for timeout
        - Log message includes agent name
        - Log message includes timeout duration
        """
        executor = ParallelDiscoveryExecutor(agent_timeouts={"transport": 0.01})

        async def slow_agent(agent: str, trip_spec: TripSpec) -> dict[str, Any]:
            await asyncio.sleep(0.5)
            return {}

        executor._call_agent = slow_agent  # type: ignore

        trip_spec = TripSpec(
            destination="Berlin",
            start_date="2026-07-01",
            end_date="2026-07-07",
        )

        with patch(
            "src.orchestrator.discovery.parallel_executor.logger"
        ) as mock_logger:
            await executor.execute_single_agent("transport", trip_spec)

            # Check warning was logged with context
            warning_calls = mock_logger.warning.call_args_list
            assert len(warning_calls) > 0, "Timeout should trigger a warning log"

            # Verify log message content
            log_message = str(warning_calls[0])
            assert "transport" in log_message, "Log should include agent name"
            assert "0.01" in log_message, "Log should include timeout duration"


class TestDiscoveryAgents:
    """Tests for DISCOVERY_AGENTS constant."""

    def test_discovery_agents_tuple(self) -> None:
        """Test DISCOVERY_AGENTS is a tuple with expected agents."""
        assert isinstance(DISCOVERY_AGENTS, tuple)
        assert len(DISCOVERY_AGENTS) == 5
        assert set(DISCOVERY_AGENTS) == {"transport", "stay", "poi", "events", "dining"}
