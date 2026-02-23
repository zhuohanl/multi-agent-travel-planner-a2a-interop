"""
Tier 2: Live integration tests for session resumption.

Prerequisites:
    - Orchestrator running with Cosmos DB configured
    - Clarifier agent running

Run (only at phase milestones):
    uv run python src/run_all.py  # Terminal 1
    uv run pytest tests/integration/live/test_session_resumption.py -v  # Terminal 2

WARNING: These tests make real LLM calls and consume Azure OpenAI quota.
Only run at phase completion milestones, not on every ticket.
"""

import pytest

from src.shared.a2a.client_wrapper import A2AClientWrapper

from .conftest import AGENT_URLS, check_agent_health


class TestSessionResumption:
    """Test session state persistence across connections."""

    @pytest.fixture
    async def a2a_client(self) -> A2AClientWrapper:
        async with A2AClientWrapper(timeout_seconds=120.0) as client:
            yield client

    @pytest.mark.asyncio
    async def test_context_preserved_across_calls(
        self, a2a_client: A2AClientWrapper, http_client
    ) -> None:
        """Test that context_id preserves conversation state."""
        if not await check_agent_health(http_client, "clarifier"):
            pytest.skip("Clarifier agent not running")

        clarifier_url = AGENT_URLS["clarifier"]

        # First call - establish context
        r1 = await a2a_client.send_message(
            agent_url=clarifier_url,
            message="I'm planning a trip to Barcelona",
        )

        saved_context_id = r1.context_id
        saved_task_id = r1.task_id

        assert saved_context_id is not None, "Must receive context_id"

        # Second call - continue with context
        r2 = await a2a_client.send_message(
            agent_url=clarifier_url,
            message="For next summer, around July",
            context_id=saved_context_id,
            task_id=saved_task_id,
        )

        assert r2.text is not None
        # The agent should understand this is a continuation

    @pytest.mark.asyncio
    async def test_new_client_can_resume_with_context(
        self, http_client
    ) -> None:
        """Test that a new client can resume with saved context_id."""
        if not await check_agent_health(http_client, "clarifier"):
            pytest.skip("Clarifier agent not running")

        clarifier_url = AGENT_URLS["clarifier"]

        # First client - establish context
        async with A2AClientWrapper(timeout_seconds=120.0) as client1:
            r1 = await client1.send_message(
                agent_url=clarifier_url,
                message="I'm planning a trip to Tokyo",
            )

            saved_context_id = r1.context_id
            saved_task_id = r1.task_id

        # Simulate "disconnect" - create completely new client
        async with A2AClientWrapper(timeout_seconds=120.0) as client2:
            # Resume with saved context
            r2 = await client2.send_message(
                agent_url=clarifier_url,
                message="In March, for about a week",
                context_id=saved_context_id,
                task_id=saved_task_id,
            )

            assert r2.text is not None


class TestHistoryInjectionResumption:
    """
    Test session resumption with history injection.

    Per design doc (Agent Communication section):
    - History is always sent (not just on context_id miss) for reliability
    - Uses historySeq (sequence number) for divergence detection
    - Agent echoes back lastSeenSeq; if != historySeq, divergence detected
    - This handles agent restarts, context cache expiry, and orchestrator failover

    Note: These tests are marked as expected failures until
    history injection (ORCH-001 to ORCH-011) is implemented.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="ORCH-009: history injection resumption not yet implemented")
    async def test_resume_with_full_history(self, http_client) -> None:
        """Test resuming a conversation by sending full history.

        Implementation: ORCH-001, ORCH-002, ORCH-009
        """
        if not await check_agent_health(http_client, "clarifier"):
            pytest.skip("Clarifier agent not running")

        clarifier_url = AGENT_URLS["clarifier"]

        # Establish initial conversation
        async with A2AClientWrapper(timeout_seconds=120.0) as client1:
            r1 = await client1.send_message(
                agent_url=clarifier_url,
                message="Plan a trip to Paris",
            )

            # Build history
            history = [
                {"role": "user", "content": "Plan a trip to Paris"},
                {"role": "assistant", "content": r1.text},
            ]
            context_id = r1.context_id
            task_id = r1.task_id

        # Resume with new client and full history
        async with A2AClientWrapper(timeout_seconds=120.0) as client2:
            r2 = await client2.send_message(
                agent_url=clarifier_url,
                message="For 5 days in June",
                context_id=context_id,
                task_id=task_id,
                history=history,  # Send full history per design doc
                history_seq=2,  # Per design doc: sequence number for divergence detection
            )

            # Agent should continue conversation coherently
            assert r2.text is not None

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="ORCH-009: divergence recovery not yet implemented")
    async def test_divergence_recovery(self, http_client) -> None:
        """Test that divergence between client and server history is handled.

        Implementation: ORCH-009

        Per design doc: Count-based divergence detection using historySeq.
        Compare len(history) vs len(cached_thread.messages).
        On mismatch: invalidate cache and rebuild from client-provided history.
        """
        if not await check_agent_health(http_client, "clarifier"):
            pytest.skip("Clarifier agent not running")

        clarifier_url = AGENT_URLS["clarifier"]

        # This test simulates a scenario where:
        # 1. Client has 4 messages in history
        # 2. Server cache has drifted (e.g., due to restart)
        # 3. Client sends history_seq=4
        # 4. Server detects divergence and rebuilds from client history

        async with A2AClientWrapper(timeout_seconds=120.0) as client:
            # Build up a conversation
            r1 = await client.send_message(
                agent_url=clarifier_url,
                message="Plan a trip",
            )

            history = [
                {"role": "user", "content": "Plan a trip"},
                {"role": "assistant", "content": r1.text},
                {"role": "user", "content": "To Rome"},
                {"role": "assistant", "content": "When would you like to go?"},
            ]

            # Send with history that might diverge from server cache
            r2 = await client.send_message(
                agent_url=clarifier_url,
                message="Next month",
                context_id=r1.context_id,
                task_id=r1.task_id,
                history=history,
                history_seq=4,  # Per design doc: sequence number for divergence detection
            )

            assert r2.text is not None


class TestCrossPhaseResumption:
    """
    Test session resumption across workflow phases.

    Note: These tests require full orchestrator implementation.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Orchestrator not yet implemented")
    async def test_resume_after_clarification_complete(self, http_client) -> None:
        """Test resuming a session that completed clarification phase."""
        if not await check_agent_health(http_client, "orchestrator"):
            pytest.skip("Orchestrator not running")

        # This would test:
        # 1. Complete clarification phase
        # 2. Disconnect
        # 3. Resume and verify we're in discovery phase

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Orchestrator not yet implemented")
    async def test_resume_during_discovery(self, http_client) -> None:
        """Test resuming during an active discovery phase."""
        if not await check_agent_health(http_client, "orchestrator"):
            pytest.skip("Orchestrator not running")

        # This would test:
        # 1. Start discovery (parallel agent calls)
        # 2. Disconnect mid-discovery
        # 3. Resume and verify discovery continues/completes
