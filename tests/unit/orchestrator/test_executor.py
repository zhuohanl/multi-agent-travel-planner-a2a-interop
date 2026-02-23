"""
Unit tests for OrchestratorExecutor and OrchestratorAgent.

Tests cover:
- OrchestratorExecutor extends BaseA2AAgentExecutor correctly
- OrchestratorExecutor processes requests through execute()
- OrchestratorAgent streams responses correctly
- Azure AI configuration integration (placeholder mode vs configured mode)
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.shared.a2a.base_agent_executor import (
    AgentStreamChunk,
    BaseA2AAgentExecutor,
    StreamableAgent,
)


class TestOrchestratorExecutorExtension:
    """Test that OrchestratorExecutor properly extends BaseA2AAgentExecutor."""

    def test_orchestrator_executor_extends_base(self) -> None:
        """Test that OrchestratorExecutor extends BaseA2AAgentExecutor."""
        from src.orchestrator.executor import OrchestratorExecutor

        assert issubclass(OrchestratorExecutor, BaseA2AAgentExecutor)

    def test_orchestrator_executor_implements_build_agent(self) -> None:
        """Test that OrchestratorExecutor implements build_agent()."""
        from src.orchestrator.executor import OrchestratorExecutor

        # Verify the method exists and is overridden
        assert hasattr(OrchestratorExecutor, "build_agent")
        assert (
            OrchestratorExecutor.build_agent is not BaseA2AAgentExecutor.build_agent
        )

    def test_orchestrator_executor_build_agent_returns_agent(self) -> None:
        """Test that build_agent() returns a StreamableAgent."""
        from src.orchestrator.executor import OrchestratorAgent, OrchestratorExecutor

        executor = OrchestratorExecutor()
        agent = executor.build_agent()

        assert isinstance(agent, OrchestratorAgent)

    def test_orchestrator_executor_has_agent_property(self) -> None:
        """Test that executor has an agent property from parent class."""
        from src.orchestrator.executor import OrchestratorAgent, OrchestratorExecutor

        executor = OrchestratorExecutor()

        assert hasattr(executor, "agent")
        assert isinstance(executor.agent, OrchestratorAgent)


class TestOrchestratorExecutorArtifacts:
    """Test executor artifact configuration."""

    def test_completion_artifact_name(self) -> None:
        """Test that completion artifact name is correctly set."""
        from src.orchestrator.executor import OrchestratorExecutor

        executor = OrchestratorExecutor()
        assert executor.get_completion_artifact_name() == "orchestrator_response"

    def test_completion_artifact_description(self) -> None:
        """Test that completion artifact description is correctly set."""
        from src.orchestrator.executor import OrchestratorExecutor

        executor = OrchestratorExecutor()
        description = executor.get_completion_artifact_description()
        assert description == "Response from the travel planner orchestrator"


class TestOrchestratorAgentProtocol:
    """Test that OrchestratorAgent implements StreamableAgent protocol."""

    def test_orchestrator_agent_has_stream_method(self) -> None:
        """Test that OrchestratorAgent has stream() method."""
        from src.orchestrator.executor import OrchestratorAgent

        agent = OrchestratorAgent()
        assert hasattr(agent, "stream")
        assert callable(agent.stream)

    def test_orchestrator_agent_stream_is_async_generator(self) -> None:
        """Test that stream() returns an async generator."""
        import inspect

        from src.orchestrator.executor import OrchestratorAgent

        agent = OrchestratorAgent()
        # The stream method should be an async generator function
        assert inspect.isasyncgenfunction(agent.stream)

    @pytest.mark.asyncio
    async def test_orchestrator_agent_stream_yields_chunks(self) -> None:
        """Test that stream() yields AgentStreamChunk objects."""
        from src.orchestrator.executor import OrchestratorAgent

        agent = OrchestratorAgent()
        chunks = []

        async for chunk in agent.stream(
            user_input="Hello",
            session_id="test_session",
        ):
            chunks.append(chunk)

        assert len(chunks) >= 1
        assert all(isinstance(chunk, dict) for chunk in chunks)
        assert all("content" in chunk for chunk in chunks)
        assert all("is_task_complete" in chunk for chunk in chunks)
        assert all("require_user_input" in chunk for chunk in chunks)


class TestOrchestratorExecutorProcessesRequest:
    """Test that OrchestratorExecutor correctly processes requests."""

    @pytest.mark.asyncio
    async def test_executor_processes_simple_request(self) -> None:
        """Test that executor processes a simple request through stream."""
        from src.orchestrator.executor import OrchestratorExecutor

        executor = OrchestratorExecutor()

        # Collect chunks from the agent
        chunks = []
        async for chunk in executor.agent.stream(
            user_input="Plan a trip to Tokyo",
            session_id="test_session_001",
        ):
            chunks.append(chunk)

        assert len(chunks) >= 1
        # Last chunk should be complete
        assert chunks[-1]["is_task_complete"] is True

    @pytest.mark.asyncio
    async def test_executor_processes_request_with_history(self) -> None:
        """Test that executor handles requests with history."""
        from src.orchestrator.executor import OrchestratorExecutor

        executor = OrchestratorExecutor()
        history = [
            {"role": "user", "content": "Plan a trip"},
            {"role": "assistant", "content": "Where would you like to go?"},
        ]

        chunks = []
        async for chunk in executor.agent.stream(
            user_input="To Tokyo",
            session_id="test_session_002",
            history=history,
            history_seq=2,
        ):
            chunks.append(chunk)

        assert len(chunks) >= 1
        assert chunks[-1]["is_task_complete"] is True

    @pytest.mark.asyncio
    async def test_executor_streams_response(self) -> None:
        """Test that executor streams response content."""
        from src.orchestrator.executor import OrchestratorExecutor

        executor = OrchestratorExecutor()

        chunks = []
        async for chunk in executor.agent.stream(
            user_input="What's the weather in Tokyo?",
            session_id="test_session_003",
        ):
            chunks.append(chunk)

        # Should have at least one chunk with content
        assert len(chunks) >= 1
        assert any(chunk.get("content") for chunk in chunks)


class TestOrchestratorAgentConfiguration:
    """Test OrchestratorAgent configuration handling."""

    def test_agent_initializes_without_config(self) -> None:
        """Test that agent initializes correctly without Azure config."""
        from src.orchestrator.executor import OrchestratorAgent

        agent = OrchestratorAgent()

        assert agent._azure_config is None
        assert agent.is_azure_configured is False

    def test_agent_initializes_with_mock_config(self) -> None:
        """Test that agent initializes with Azure configuration."""
        from src.orchestrator.executor import OrchestratorAgent

        # Create a mock Azure config
        mock_config = MagicMock()
        mock_config.has_connection_config = True

        agent = OrchestratorAgent(azure_config=mock_config)

        assert agent._azure_config is not None
        assert agent.is_azure_configured is True

    def test_agent_is_azure_configured_with_incomplete_config(self) -> None:
        """Test that agent correctly reports unconfigured state."""
        from src.orchestrator.executor import OrchestratorAgent

        # Mock config with missing connection config
        mock_config = MagicMock()
        mock_config.has_connection_config = False

        agent = OrchestratorAgent(azure_config=mock_config)

        assert agent.is_azure_configured is False


class TestOrchestratorExecutorConfiguration:
    """Test OrchestratorExecutor configuration handling."""

    def test_executor_initializes_without_config(self) -> None:
        """Test that executor initializes without Azure config."""
        from src.orchestrator.executor import OrchestratorExecutor

        executor = OrchestratorExecutor()

        assert executor._azure_config is None
        assert executor.is_azure_configured is False

    def test_executor_passes_config_to_agent(self) -> None:
        """Test that executor passes Azure config to agent."""
        from src.orchestrator.executor import OrchestratorExecutor

        mock_config = MagicMock()
        mock_config.has_connection_config = True

        executor = OrchestratorExecutor(azure_config=mock_config)

        assert executor.is_azure_configured is True
        assert executor.agent.is_azure_configured is True

    def test_executor_accepts_custom_agent(self) -> None:
        """Test that executor accepts a custom agent instance."""
        from src.orchestrator.executor import OrchestratorExecutor

        # Create a mock agent
        mock_agent = MagicMock()

        executor = OrchestratorExecutor(agent=mock_agent)

        assert executor.agent is mock_agent


class TestOrchestratorAgentResponseContent:
    """Test the content of OrchestratorAgent responses."""

    @pytest.mark.asyncio
    async def test_response_routes_through_workflow(self) -> None:
        """Test that requests go through the routing layer.

        With the three-layer routing implemented (ORCH-059), requests now
        route through Layer 1a/1b/1c. Without a session or utility pattern
        match, messages go to workflow_turn via Layer 1c (LLM fallback defaults
        to workflow_turn when no LLM is configured).
        """
        from src.orchestrator.executor import OrchestratorAgent

        agent = OrchestratorAgent()
        message = "Plan a trip to Tokyo"

        chunks = []
        async for chunk in agent.stream(
            user_input=message,
            session_id="test_session",
        ):
            chunks.append(chunk)

        # Response should come from workflow_turn (clarification phase)
        response_text = chunks[0]["content"]
        # With routing implemented, requests go through workflow_turn
        assert "clarification" in response_text.lower() or "message" in response_text.lower()

    @pytest.mark.asyncio
    async def test_utility_pattern_routes_correctly(self) -> None:
        """Test that utility patterns route to utility handlers (Layer 1b)."""
        from src.orchestrator.executor import OrchestratorAgent

        agent = OrchestratorAgent()
        # Currency conversion is a utility pattern (Layer 1b)
        message = "convert 100 USD to EUR"

        chunks = []
        async for chunk in agent.stream(
            user_input=message,
            session_id="test_session",
        ):
            chunks.append(chunk)

        response_text = chunks[0]["content"]
        # Should route to currency utility
        assert "USD" in response_text or "EUR" in response_text

    @pytest.mark.asyncio
    async def test_weather_pattern_routes_correctly(self) -> None:
        """Test that weather patterns route to utility handlers (Layer 1b)."""
        from src.orchestrator.executor import OrchestratorAgent

        agent = OrchestratorAgent()
        message = "weather in Tokyo"

        chunks = []
        async for chunk in agent.stream(
            user_input=message,
            session_id="test_session",
        ):
            chunks.append(chunk)

        response_text = chunks[0]["content"]
        # Should route to weather utility
        assert "Tokyo" in response_text or "weather" in response_text.lower()


class TestOrchestratorAgentSessionThreads:
    """Test session thread management in OrchestratorAgent."""

    def test_agent_initializes_empty_session_threads(self) -> None:
        """Test that agent initializes with empty session threads."""
        from src.orchestrator.executor import OrchestratorAgent

        agent = OrchestratorAgent()

        assert hasattr(agent, "_session_threads")
        assert isinstance(agent._session_threads, dict)
        assert len(agent._session_threads) == 0
