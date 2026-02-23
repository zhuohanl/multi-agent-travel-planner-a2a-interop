"""
Discovery module for parallel agent execution.

This module provides functionality for running multiple discovery agents
in parallel and aggregating their results.

Key components:
- ParallelDiscoveryExecutor: Manages parallel agent calls with asyncio.gather
- AgentDiscoveryResult: Result from a single discovery agent
- DiscoveryResults: Aggregated results from all discovery agents
- sync_job_to_state: Transfers job results to WorkflowState with idempotency
- finalize_job: Finalizes a completed job by syncing to state
- resume_session_with_recovery: Resumes session with crash recovery
"""

from __future__ import annotations

from src.orchestrator.discovery.parallel_executor import (
    AGENT_TIMEOUTS,
    DISCOVERY_AGENTS,
    AgentDiscoveryResult,
    DiscoveryResults,
    DiscoveryStatus,
    ParallelDiscoveryExecutor,
    execute_parallel_discovery,
)
from src.orchestrator.discovery.job_runner import (
    run_discovery_job,
    spawn_discovery_job,
)
from src.orchestrator.discovery.state_sync import (
    SyncResult,
    check_sync_needed,
    finalize_job,
    finalize_job_with_planning,
    resume_session_with_recovery,
    run_planning_after_discovery,
    sync_job_to_state,
)

__all__ = [
    # Parallel executor
    "AGENT_TIMEOUTS",
    "DISCOVERY_AGENTS",
    "AgentDiscoveryResult",
    "DiscoveryResults",
    "DiscoveryStatus",
    "ParallelDiscoveryExecutor",
    "execute_parallel_discovery",
    "run_discovery_job",
    "spawn_discovery_job",
    # State sync
    "SyncResult",
    "check_sync_needed",
    "finalize_job",
    "finalize_job_with_planning",
    "resume_session_with_recovery",
    "run_planning_after_discovery",
    "sync_job_to_state",
]
