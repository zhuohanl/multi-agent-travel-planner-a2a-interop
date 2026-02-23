"""
Job-to-state synchronization with idempotency.

This module provides the sync_job_to_state() function that transfers
discovery job results to WorkflowState. It includes:
- Idempotency via last_synced_job_id to prevent duplicate syncs
- Crash recovery via lazy sync on session resume
- 4 safety guards per design doc to prevent race conditions
- Planning pipeline execution after discovery completes

Per design doc Long-Running Operations section:
- Guard 1: Workflow exists
- Guard 2: Workflow version matches (prevents start_new race)
- Guard 3: Job is still the active job (prevents superseded job race)
- Guard 4: Workflow is in correct phase (prevents state corruption)
- Idempotency: last_synced_job_id prevents double-sync on retries

Per design doc ORCH-088:
- finalize_job runs planning pipeline (Aggregator → Budget → Route → Validator)
- Stores PlanningResult and ItineraryDraft on DiscoveryJob and WorkflowState
- Updates phase/checkpoint to DISCOVERY_PLANNING + itinerary_approval
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal, Protocol, runtime_checkable

from src.orchestrator.models.workflow_state import Phase, WorkflowState
from src.orchestrator.storage.discovery_jobs import DiscoveryJob, JobStatus

if TYPE_CHECKING:
    from src.orchestrator.planning.pipeline import PlanningPipeline, PlanningResult
    from src.orchestrator.storage.discovery_jobs import DiscoveryJobStoreProtocol
    from src.shared.a2a.client_wrapper import A2AClientWrapper
    from src.shared.a2a.registry import AgentRegistry
    from src.shared.storage.protocols import WorkflowStoreProtocol

logger = logging.getLogger(__name__)

PlanningStageProgressCallback = Callable[[str, Literal["started", "completed"]], Awaitable[None]]


@dataclass
class SyncResult:
    """
    Result of a sync_job_to_state operation.

    Attributes:
        success: Whether the sync completed successfully
        synced: Whether data was actually transferred (False if skipped due to idempotency)
        reason: Human-readable explanation of the result
        state: The updated WorkflowState (if success)
    """

    success: bool
    synced: bool
    reason: str
    state: WorkflowState | None = None


@runtime_checkable
class WorkflowStateLoaderProtocol(Protocol):
    """Protocol for loading workflow state by session_id."""

    async def get_by_session(self, session_id: str) -> WorkflowState | None:
        """Load workflow state by session ID."""
        ...

    async def save_state(self, state: WorkflowState) -> WorkflowState:
        """Save workflow state."""
        ...


async def _save_state(
    workflow_store: WorkflowStateLoaderProtocol,
    state: WorkflowState,
) -> WorkflowState:
    """Persist workflow state across storage backends."""
    if hasattr(workflow_store, "save_state"):
        return await workflow_store.save_state(state)  # type: ignore[attr-defined]
    if hasattr(workflow_store, "save"):
        etag = await workflow_store.save(state, etag=state.etag)  # type: ignore[call-arg]
        state.etag = etag
        return state
    raise AttributeError("workflow_store does not support save or save_state")


async def sync_job_to_state(
    job: DiscoveryJob,
    workflow_store: WorkflowStateLoaderProtocol,
    *,
    session_id: str | None = None,
) -> SyncResult:
    """
    Synchronize discovery job results to WorkflowState.

    This is the main entry point for job-to-state sync. It:
    1. Loads the workflow state
    2. Validates 4 safety guards
    3. Checks idempotency (last_synced_job_id)
    4. Transfers discovery_results and itinerary_draft
    5. Updates phase/checkpoint based on job status
    6. Saves the updated state

    Args:
        job: The completed discovery job to sync
        workflow_store: Store for loading/saving workflow state
        session_id: Optional session ID override (uses job.consultation_id lookup otherwise)

    Returns:
        SyncResult indicating success/failure and whether data was synced
    """
    logger.debug(f"sync_job_to_state called for job {job.job_id}")

    # Load workflow state - we need a session_id to load state
    # In practice, we'd use consultation_id to lookup session_id, but for now
    # the caller should provide session_id or we need consultation lookup
    if session_id is None:
        # Attempt to use consultation lookup if store supports it
        if hasattr(workflow_store, "get_by_consultation"):
            state = await workflow_store.get_by_consultation(job.consultation_id)  # type: ignore
        else:
            logger.error(
                f"Cannot sync job {job.job_id}: no session_id provided and "
                "workflow_store doesn't support get_by_consultation"
            )
            return SyncResult(
                success=False,
                synced=False,
                reason="Cannot load workflow state: no session_id provided",
            )
    else:
        state = await workflow_store.get_by_session(session_id)

    # GUARD 1: Check workflow still exists
    if state is None:
        logger.warning(f"Job {job.job_id} has no workflow state, orphaning")
        return SyncResult(
            success=False,
            synced=False,
            reason="Workflow state not found - job is orphaned",
        )

    # GUARD 2: Check workflow version matches (prevents start_new race)
    if state.workflow_version != job.workflow_version:
        logger.warning(
            f"Job {job.job_id} version mismatch: job={job.workflow_version}, "
            f"state={state.workflow_version}. Workflow was reset via start_new."
        )
        return SyncResult(
            success=False,
            synced=False,
            reason=f"Workflow version mismatch (job={job.workflow_version}, state={state.workflow_version}) - job is orphaned",
        )

    # GUARD 3: Check this is still the active job (prevents superseded job race)
    if state.current_job_id != job.job_id:
        logger.warning(
            f"Job {job.job_id} is not the active job (active={state.current_job_id}). "
            f"Job was superseded or workflow was modified."
        )
        return SyncResult(
            success=False,
            synced=False,
            reason=f"Job {job.job_id} is not the active job - job is orphaned",
        )

    # GUARD 4: Check workflow is in correct phase (prevents state corruption)
    if state.phase != Phase.DISCOVERY_IN_PROGRESS:
        logger.warning(
            f"Job {job.job_id} cannot finalize: workflow phase is {state.phase}, "
            f"expected DISCOVERY_IN_PROGRESS"
        )
        return SyncResult(
            success=False,
            synced=False,
            reason=f"Workflow phase is {state.phase}, expected DISCOVERY_IN_PROGRESS - job is orphaned",
        )

    # IDEMPOTENCY CHECK: Prevent double-sync on retries
    if state.last_synced_job_id == job.job_id:
        logger.info(f"Job {job.job_id} already synced, skipping")
        return SyncResult(
            success=True,
            synced=False,
            reason="Job already synced (idempotent)",
            state=state,
        )

    # All guards passed - safe to transfer results
    logger.info(f"Syncing job {job.job_id} results to workflow state")

    # Transfer discovery results to WorkflowState
    state.discovery_results = job.discovery_results

    # Transfer itinerary draft (REQUIRED for approval flow)
    state.itinerary_draft = job.itinerary_draft

    # Update phase/checkpoint based on job status
    if job.status == JobStatus.COMPLETED:
        # Present results for approval (do NOT create itinerary yet)
        state.phase = Phase.DISCOVERY_PLANNING
        state.checkpoint = "itinerary_approval"  # Awaiting user approval
        state.current_step = "approval"
        logger.info(f"Job {job.job_id} completed - transitioning to DISCOVERY_PLANNING")

    elif job.status == JobStatus.PARTIAL:
        # Partial results with gaps - still present for approval
        state.phase = Phase.DISCOVERY_PLANNING
        state.checkpoint = "itinerary_approval"  # Awaiting user approval
        state.current_step = "approval"
        logger.info(f"Job {job.job_id} partially completed - transitioning to DISCOVERY_PLANNING with gaps")

    elif job.status == JobStatus.FAILED:
        # All agents failed - terminal state, user can only start_new
        state.phase = Phase.FAILED
        state.checkpoint = None  # No checkpoint - FAILED is terminal
        state.current_step = "failed"
        logger.warning(f"Job {job.job_id} failed - transitioning to FAILED phase")

    # Track what we synced (for idempotency) and clear active job
    state.last_synced_job_id = job.job_id
    state.current_job_id = None

    # Save the updated state
    updated_state = await _save_state(workflow_store, state)

    return SyncResult(
        success=True,
        synced=True,
        reason=f"Job {job.job_id} synced successfully (status={job.status.value})",
        state=updated_state,
    )


async def finalize_job(
    job: DiscoveryJob,
    workflow_store: WorkflowStateLoaderProtocol,
    *,
    session_id: str | None = None,
) -> SyncResult:
    """
    Finalize a completed discovery job by syncing to WorkflowState.

    This is an alias for sync_job_to_state that emphasizes the finalization
    semantics. It should be called when a discovery job reaches a terminal
    state (COMPLETED, PARTIAL, or FAILED).

    Args:
        job: The completed discovery job to finalize
        workflow_store: Store for loading/saving workflow state
        session_id: Optional session ID override

    Returns:
        SyncResult indicating success/failure and whether data was synced
    """
    if not job.is_terminal():
        logger.warning(f"finalize_job called on non-terminal job {job.job_id} (status={job.status})")
        return SyncResult(
            success=False,
            synced=False,
            reason=f"Job {job.job_id} is not in terminal state (status={job.status.value})",
        )

    return await sync_job_to_state(job, workflow_store, session_id=session_id)


async def resume_session_with_recovery(
    session_id: str,
    workflow_store: WorkflowStateLoaderProtocol,
    job_store: DiscoveryJobStoreProtocol,
) -> WorkflowState | None:
    """
    Resume a session with crash recovery.

    Handles the case where a job completed but finalize_job() failed
    to save state (e.g., server crashed). This function:
    1. Loads the workflow state
    2. Detects unsynchronized completed jobs (current_job_id set but no discovery_results)
    3. Runs lazy sync to recover

    Per design doc Long-Running Operations section:
    | Scenario | current_job_id | discovery_results | Action |
    |----------|----------------|-------------------|--------|
    | Normal (no job) | None | Any | Return state |
    | Job running | Set | None | Return state (job in progress) |
    | Job done, synced | None | Set | Return state |
    | **Crash case** | Set | None + job.status=terminal | **Lazy sync** |

    Args:
        session_id: The session to resume
        workflow_store: Store for loading/saving workflow state
        job_store: Store for loading discovery jobs

    Returns:
        WorkflowState if found (possibly recovered), None if session doesn't exist
    """
    state = await workflow_store.get_by_session(session_id)
    if state is None:
        return None

    # CRASH RECOVERY: Check for unsynchronized completed job
    # A job needs recovery if:
    # 1. current_job_id is set (job was started)
    # 2. discovery_results is None (results not synced yet)
    # 3. Job is in a terminal state (completed/partial/failed/cancelled)
    if state.current_job_id and state.discovery_results is None:
        # Load the job to check its status
        job = await job_store.get_job(state.current_job_id, state.consultation_id)

        if job and job.status in (JobStatus.COMPLETED, JobStatus.PARTIAL, JobStatus.FAILED):
            logger.warning(
                f"Detected unsynchronized job {job.job_id} "
                f"(status={job.status}), running lazy sync"
            )
            result = await sync_job_to_state(job, workflow_store, session_id=session_id)

            if result.success and result.synced:
                # Reload state after sync
                state = await workflow_store.get_by_session(session_id)
                logger.info(f"Crash recovery complete for session {session_id}")
            else:
                logger.error(
                    f"Crash recovery failed for session {session_id}: {result.reason}"
                )

        elif job and job.status == JobStatus.CANCELLED:
            # Job was cancelled - just clear the job reference, don't sync results
            logger.info(f"Clearing cancelled job {job.job_id}")
            state.current_job_id = None
            state = await _save_state(workflow_store, state)

        elif job is None:
            # Job was deleted (expired?) - clear the stale reference
            logger.warning(
                f"Job {state.current_job_id} not found for session {session_id}, "
                "clearing stale job reference"
            )
            state.current_job_id = None
            state = await _save_state(workflow_store, state)

    return state


def check_sync_needed(state: WorkflowState, job: DiscoveryJob) -> tuple[bool, str]:
    """
    Check if a job needs to be synced to state.

    This is a lightweight check that can be used before attempting sync.
    It performs all the guard checks without actually modifying state.

    Args:
        state: The current workflow state
        job: The discovery job to check

    Returns:
        Tuple of (needs_sync: bool, reason: str)
    """
    # Guard 1: State exists (assumed if we have a state object)

    # Guard 2: Version match
    if state.workflow_version != job.workflow_version:
        return False, f"Version mismatch (job={job.workflow_version}, state={state.workflow_version})"

    # Guard 3: Active job match
    if state.current_job_id != job.job_id:
        return False, f"Not the active job (active={state.current_job_id})"

    # Guard 4: Correct phase
    if state.phase != Phase.DISCOVERY_IN_PROGRESS:
        return False, f"Wrong phase ({state.phase})"

    # Idempotency check
    if state.last_synced_job_id == job.job_id:
        return False, "Already synced (idempotent)"

    # Job must be terminal
    if not job.is_terminal():
        return False, f"Job not terminal (status={job.status.value})"

    return True, "Sync needed"


async def run_planning_after_discovery(
    job: DiscoveryJob,
    trip_spec: dict[str, Any],
    a2a_client: "A2AClientWrapper | None" = None,
    agent_registry: "AgentRegistry | None" = None,
    stage_progress_callback: PlanningStageProgressCallback | None = None,
) -> "PlanningResult":
    """
    Run the planning pipeline after discovery completes.

    Per design doc ORCH-088, this function:
    1. Invokes PlanningPipeline.run_planning_pipeline() with discovery results
    2. Returns PlanningResult with itinerary draft

    The planning pipeline runs: Aggregator → Budget → Route → Validator

    Args:
        job: The completed discovery job with results
        trip_spec: Trip specification from clarification
        a2a_client: Optional A2A client for agent communication
        agent_registry: Optional agent registry for URL lookup
        stage_progress_callback: Optional callback for stage progress updates.

    Returns:
        PlanningResult with itinerary or blocker reason
    """
    from src.orchestrator.handlers.discovery import DiscoveryResults
    from src.orchestrator.planning.pipeline import run_planning_pipeline

    logger.info(f"Running planning pipeline for job {job.job_id}")

    # Convert discovery_results dict to DiscoveryResults object
    discovery_results_dict = job.discovery_results or {}
    discovery_results = DiscoveryResults.from_dict(discovery_results_dict)

    # Run the planning pipeline
    planning_result = await run_planning_pipeline(
        discovery_results=discovery_results,
        trip_spec=trip_spec,
        a2a_client=a2a_client,
        agent_registry=agent_registry,
        stage_progress_callback=stage_progress_callback,
    )

    logger.info(
        f"Planning pipeline completed for job {job.job_id}: "
        f"success={planning_result.success}, "
        f"has_itinerary={planning_result.itinerary is not None}"
    )

    return planning_result


async def finalize_job_with_planning(
    job: DiscoveryJob,
    workflow_store: WorkflowStateLoaderProtocol,
    job_store: "DiscoveryJobStoreProtocol",
    *,
    session_id: str | None = None,
    a2a_client: "A2AClientWrapper | None" = None,
    agent_registry: "AgentRegistry | None" = None,
    stage_progress_callback: PlanningStageProgressCallback | None = None,
) -> SyncResult:
    """
    Finalize a completed discovery job by running planning and syncing to WorkflowState.

    Per design doc ORCH-088, this is the main entry point that:
    1. Runs the planning pipeline (Aggregator → Budget → Route → Validator)
    2. Stores PlanningResult and ItineraryDraft on DiscoveryJob and WorkflowState
    3. Updates WorkflowState phase/checkpoint to DISCOVERY_PLANNING + itinerary_approval

    This function orchestrates the complete discovery → planning flow and should be
    called when a discovery job completes (status=COMPLETED or PARTIAL).

    Args:
        job: The completed discovery job to finalize
        workflow_store: Store for loading/saving workflow state
        job_store: Store for saving discovery job updates
        session_id: Optional session ID override
        a2a_client: Optional A2A client for planning agent calls
        agent_registry: Optional agent registry for planning agent URLs
        stage_progress_callback: Optional callback for stage progress updates.

    Returns:
        SyncResult indicating success/failure and whether data was synced
    """
    if not job.is_terminal():
        logger.warning(f"finalize_job_with_planning called on non-terminal job {job.job_id}")
        return SyncResult(
            success=False,
            synced=False,
            reason=f"Job {job.job_id} is not in terminal state (status={job.status.value})",
        )

    # For FAILED jobs, skip planning and just sync the failure state
    if job.status == JobStatus.FAILED:
        logger.info(f"Job {job.job_id} failed - skipping planning pipeline")
        return await sync_job_to_state(job, workflow_store, session_id=session_id)

    # Load workflow state to get trip_spec
    if session_id is None:
        if hasattr(workflow_store, "get_by_consultation"):
            state = await workflow_store.get_by_consultation(job.consultation_id)  # type: ignore
        else:
            return SyncResult(
                success=False,
                synced=False,
                reason="Cannot load workflow state: no session_id provided",
            )
    else:
        state = await workflow_store.get_by_session(session_id)

    if state is None:
        return SyncResult(
            success=False,
            synced=False,
            reason="Workflow state not found",
        )

    # Get trip_spec from state
    trip_spec = state.trip_spec or {}

    # Run planning pipeline
    try:
        planning_result = await run_planning_after_discovery(
            job=job,
            trip_spec=trip_spec,
            a2a_client=a2a_client,
            agent_registry=agent_registry,
            stage_progress_callback=stage_progress_callback,
        )
    except Exception as e:
        logger.error(f"Planning pipeline failed for job {job.job_id}: {e}")
        # Still sync the discovery results, but mark planning as failed
        job.pipeline_stage = "planning_failed"
        job.error = str(e)
        await job_store.save_job(job)
        return await sync_job_to_state(job, workflow_store, session_id=session_id)

    # Store planning result on the job
    if planning_result.success and planning_result.itinerary:
        job.itinerary_draft = planning_result.itinerary
        job.pipeline_stage = "validator"  # Planning complete
        logger.info(f"Stored itinerary draft on job {job.job_id}")
    else:
        job.pipeline_stage = "planning_blocked"
        job.error = planning_result.blocker
        logger.warning(f"Planning blocked for job {job.job_id}: {planning_result.blocker}")

    # Save job with planning results
    await job_store.save_job(job)

    # Sync to workflow state (this transfers discovery_results and itinerary_draft)
    return await sync_job_to_state(job, workflow_store, session_id=session_id)
