"""
Discovery progress endpoints for streaming and polling discovery job status.

Per design doc "Long-Running Operations" section:
- GET /sessions/{session_id}/discovery/stream - SSE endpoint for real-time progress
- GET /sessions/{session_id}/discovery/status - Polling endpoint for job status
- GET /sessions/{session_id}/discovery/reconnect - Reconnection endpoint for resuming

These endpoints tie background jobs to client-visible progress and resumption.
They bridge DiscoveryJobStore, WorkflowState.current_job_id, and SSE streaming
so users can observe and resume long-running discovery without losing state.

Design notes:
- Uses session_id (not job_id) to align with Cosmos partition key access patterns
- workflow_states partitioned by /session_id
- discovery_jobs partitioned by /consultation_id (retrieved from WorkflowState)
- All lookups use partition keys (no cross-partition queries)

Progress visibility trade-off:
- SSE stream (connected): Real-time per-agent progress
- SSE stream (reconnect mid-job): Coarse "running" status only (no mid-job DB writes)
- Polling endpoint: Coarse "running" status during job; full details after completion
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.orchestrator.storage.discovery_jobs import (
    DiscoveryJob,
    DiscoveryJobStoreProtocol,
    InMemoryDiscoveryJobStore,
    JobStatus,
)
from src.orchestrator.storage.session_state import (
    InMemoryWorkflowStateStore,
    WorkflowStateStoreProtocol,
)
from src.orchestrator.streaming.progress import (
    ProgressChannel,
    ProgressEventType,
    ProgressUpdate,
    get_progress_channel,
    get_progress_streamer,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Response Models
# =============================================================================


class JobStatusResponse(BaseModel):
    """Response model for discovery status polling endpoint.

    Per design doc:
    - Returns coarse status while job is running (no mid-job DB writes)
    - Returns detailed results after job completion
    """

    status: str = Field(..., description="Job status (pending, running, completed, failed, partial, cancelled)")
    job_id: str | None = Field(default=None, description="Job identifier")
    pipeline_stage: str | None = Field(
        default=None,
        description="Current pipeline stage (discovery, aggregator, budget, route, validator)"
    )
    agent_progress: dict[str, dict[str, Any]] | None = Field(
        default=None,
        description="Per-agent progress (only available after job completes)"
    )
    message: str | None = Field(default=None, description="Human-readable status message")
    itinerary_draft: dict[str, Any] | None = Field(
        default=None,
        description="Draft itinerary (only available after successful completion)"
    )
    gaps: list[dict[str, Any]] | None = Field(
        default=None,
        description="Discovery gaps (only available after partial completion)"
    )


class ReconnectionResponse(BaseModel):
    """Response model for discovery reconnection endpoint.

    Per design doc:
    - Returns stream_url for RUNNING jobs
    - Returns itinerary/gaps for COMPLETED/PARTIAL jobs
    """

    status: str = Field(..., description="Job status")
    stream_url: str | None = Field(
        default=None,
        description="SSE stream URL (only for RUNNING jobs)"
    )
    message: str = Field(..., description="Human-readable message")
    itinerary_draft: dict[str, Any] | None = Field(
        default=None,
        description="Draft itinerary (for COMPLETED/PARTIAL jobs)"
    )
    gaps: list[dict[str, Any]] | None = Field(
        default=None,
        description="Discovery gaps (for PARTIAL jobs)"
    )
    checkpoint: str | None = Field(
        default=None,
        description="Checkpoint name if approval is needed"
    )
    current_progress: dict[str, Any] | None = Field(
        default=None,
        description="Coarse progress info for RUNNING jobs"
    )


# =============================================================================
# Discovery Router Factory
# =============================================================================


def create_discovery_router(
    workflow_state_store: WorkflowStateStoreProtocol | None = None,
    discovery_job_store: DiscoveryJobStoreProtocol | None = None,
) -> APIRouter:
    """
    Create a FastAPI router for discovery progress endpoints.

    Args:
        workflow_state_store: Store for workflow state lookup
        discovery_job_store: Store for discovery job lookup

    Returns:
        FastAPI router with discovery endpoints mounted
    """
    router = APIRouter(prefix="/sessions", tags=["discovery"])

    # Use provided stores or create defaults
    _workflow_store = workflow_state_store or InMemoryWorkflowStateStore()
    _job_store = discovery_job_store or InMemoryDiscoveryJobStore()

    @router.get("/{session_id}/discovery/stream")
    async def stream_discovery_progress(session_id: str) -> StreamingResponse:
        """
        Server-Sent Events endpoint for discovery progress streaming.

        Per design doc:
        - Sends current persisted state first (for reconnection - coarse status only)
        - If job already completed/cancelled, sends final state and closes
        - Streams real-time updates from in-memory progress tracker

        Raises:
            HTTPException 404: If no active discovery job for this session
        """
        # Get workflow state using partition key (session_id)
        state = await _workflow_store.get_state(session_id)
        if state is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session not found: {session_id}"
            )

        if not state.current_job_id:
            raise HTTPException(
                status_code=404,
                detail="No active discovery job for this session"
            )

        # Get job using point read (job_id + partition key consultation_id)
        job = await _job_store.get_job(state.current_job_id, state.consultation_id or "")
        if job is None:
            raise HTTPException(
                status_code=404,
                detail=f"Discovery job not found: {state.current_job_id}"
            )

        async def event_generator() -> AsyncGenerator[str, None]:
            """Generate SSE events from discovery job progress."""

            # Send current persisted state first (for reconnection)
            state_update = _build_state_event(job)
            yield f"event: state\ndata: {state_update.to_json()}\n\n"

            # If job already completed/cancelled, send final state and close
            if job.is_terminal():
                result_update = _build_result_event(job)
                yield f"event: job_completed\ndata: {result_update.to_json()}\n\n"
                return

            # Stream real-time updates from in-memory progress tracker
            # In single-process: direct access to progress channel
            # In distributed: would subscribe to Redis pub/sub channel
            progress_channel = await get_progress_channel(job.job_id)

            if progress_channel is None:
                # No active channel - job may have completed between checks
                # Re-fetch job status
                updated_job = await _job_store.get_job(job.job_id, job.consultation_id)
                if updated_job and updated_job.is_terminal():
                    result_update = _build_result_event(updated_job)
                    yield f"event: job_completed\ndata: {result_update.to_json()}\n\n"
                else:
                    # Channel not found and job still running - this shouldn't happen
                    # in single-process deployment, but handle gracefully
                    yield f"event: error\ndata: {json.dumps({'error': 'Progress channel not found'})}\n\n"
                return

            # Subscribe to progress channel and forward events
            async for update in progress_channel.subscribe():
                event_type = (
                    update.type.value
                    if isinstance(update.type, ProgressEventType)
                    else str(update.type)
                )
                yield f"event: {event_type}\ndata: {update.to_json()}\n\n"

                # Check for terminal events
                if isinstance(update.type, ProgressEventType) and update.type in (
                    ProgressEventType.JOB_COMPLETED,
                    ProgressEventType.JOB_FAILED,
                    ProgressEventType.JOB_CANCELLED,
                ):
                    break

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    @router.get("/{session_id}/discovery/status", response_model=JobStatusResponse)
    async def get_discovery_status(session_id: str) -> JobStatusResponse:
        """
        Polling endpoint for discovery status (fallback for clients without SSE).

        Per design doc:
        - Returns COARSE status only when job is running
        - Detailed per-agent progress is only available via SSE or after completion
        - We don't write progress to DB mid-job to avoid race conditions

        Raises:
            HTTPException 404: If session or job not found
        """
        # Get workflow state using partition key (session_id)
        state = await _workflow_store.get_state(session_id)
        if state is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session not found: {session_id}"
            )

        if not state.current_job_id:
            raise HTTPException(
                status_code=404,
                detail="No active discovery job for this session"
            )

        # Get job using point read (job_id + partition key)
        job = await _job_store.get_job(state.current_job_id, state.consultation_id or "")
        if job is None:
            raise HTTPException(
                status_code=404,
                detail=f"Discovery job not found: {state.current_job_id}"
            )

        # If job is still running, return coarse status only
        if job.status == JobStatus.RUNNING:
            return JobStatusResponse(
                status=job.status.value,
                job_id=job.job_id,
                pipeline_stage=job.pipeline_stage,
                agent_progress=None,  # Not available via polling mid-job
                message="Job in progress. Connect to SSE stream for real-time per-agent progress.",
            )

        # Job completed/failed - return full details
        agent_progress = None
        if job.agent_progress:
            agent_progress = {
                agent: progress.to_dict()
                for agent, progress in job.agent_progress.items()
            }

        # Build message based on status
        message = _build_status_message(job)

        # Extract gaps from discovery results if partial
        gaps = None
        if job.status == JobStatus.PARTIAL and job.discovery_results:
            gaps = job.discovery_results.get("gaps", [])

        return JobStatusResponse(
            status=job.status.value,
            job_id=job.job_id,
            pipeline_stage=job.pipeline_stage,
            agent_progress=agent_progress,
            message=message,
            itinerary_draft=job.itinerary_draft,
            gaps=gaps,
        )

    @router.get("/{session_id}/discovery/reconnect", response_model=ReconnectionResponse)
    async def handle_reconnection(session_id: str) -> ReconnectionResponse:
        """
        Handle user returning after disconnect.

        Per design doc:
        - For RUNNING jobs: Return stream_url for reconnection
        - For COMPLETED jobs: Return itinerary immediately
        - For PARTIAL jobs: Return itinerary with gaps
        - For FAILED/CANCELLED: Return error message

        Raises:
            HTTPException 404: If session not found
        """
        # Get workflow state using partition key (session_id)
        state = await _workflow_store.get_state(session_id)
        if state is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session not found: {session_id}"
            )

        # No active job - return current state info
        if not state.current_job_id:
            return ReconnectionResponse(
                status="no_job",
                message="No active discovery job. Start a new trip planning session.",
                current_progress=None,
            )

        # Get job using point read
        job = await _job_store.get_job(state.current_job_id, state.consultation_id or "")
        if job is None:
            return ReconnectionResponse(
                status="job_not_found",
                message="Discovery job not found. It may have expired.",
                current_progress=None,
            )

        # Handle based on job status
        if job.status == JobStatus.RUNNING:
            # Job still running - provide stream URL for reconnection
            return ReconnectionResponse(
                status=job.status.value,
                stream_url=f"/sessions/{session_id}/discovery/stream",
                message="Your trip planning is in progress...",
                current_progress={
                    "status": "running",
                    "pipeline_stage": job.pipeline_stage,
                    "message": "Reconnect to stream for live updates",
                },
            )

        if job.status == JobStatus.COMPLETED:
            # Job completed - show results
            return ReconnectionResponse(
                status=job.status.value,
                message="Your itinerary is ready!",
                itinerary_draft=job.itinerary_draft,
                checkpoint="itinerary_approval",
            )

        if job.status == JobStatus.PARTIAL:
            # Job completed with gaps - show what we have
            gaps = None
            if job.discovery_results:
                gaps = job.discovery_results.get("gaps", [])

            return ReconnectionResponse(
                status=job.status.value,
                message="Trip planning completed with some gaps",
                itinerary_draft=job.itinerary_draft,
                gaps=gaps,
                checkpoint="itinerary_approval",
            )

        if job.status == JobStatus.FAILED:
            # Job failed - provide error info
            return ReconnectionResponse(
                status=job.status.value,
                message=f"Trip planning failed: {job.error or 'Unknown error'}",
                current_progress={
                    "status": "failed",
                    "error": job.error,
                },
            )

        if job.status == JobStatus.CANCELLED:
            # Job cancelled
            return ReconnectionResponse(
                status=job.status.value,
                message="Trip planning was cancelled. You can start a new session.",
            )

        # Pending status (shouldn't normally reach here)
        return ReconnectionResponse(
            status=job.status.value,
            message="Discovery job is pending. Please wait...",
        )

    return router


# =============================================================================
# Helper Functions
# =============================================================================


def _build_state_event(job: DiscoveryJob) -> ProgressUpdate:
    """Build a state event for SSE reconnection.

    Per design doc, this provides coarse status for reconnecting clients.
    """
    data: dict[str, Any] = {
        "job_id": job.job_id,
        "status": job.status.value,
    }

    if job.pipeline_stage:
        data["pipeline_stage"] = job.pipeline_stage

    # Include completion percentage if available
    total_agents = len(job.agent_progress)
    if total_agents > 0:
        completed = sum(
            1 for p in job.agent_progress.values()
            if p.status in ("completed", "failed", "timeout")
        )
        data["completion_percentage"] = int(completed / total_agents * 100)

    return ProgressUpdate(
        type=ProgressEventType.STATE,
        message=f"Job is {job.status.value}",
        data=data,
    )


def _build_result_event(job: DiscoveryJob) -> ProgressUpdate:
    """Build a result event for completed/failed jobs."""
    event_type = (
        ProgressEventType.JOB_COMPLETED
        if job.status == JobStatus.COMPLETED
        else ProgressEventType.JOB_FAILED
        if job.status == JobStatus.FAILED
        else ProgressEventType.JOB_CANCELLED
    )

    data: dict[str, Any] = {
        "job_id": job.job_id,
        "status": job.status.value,
    }

    # Include agent progress summary
    if job.agent_progress:
        data["agent_progress"] = {
            agent: progress.to_dict()
            for agent, progress in job.agent_progress.items()
        }

    # Include itinerary if completed
    if job.itinerary_draft:
        data["itinerary_draft"] = job.itinerary_draft

    # Include error if failed
    if job.error:
        data["error"] = job.error

    return ProgressUpdate(
        type=event_type,
        message=_build_status_message(job),
        data=data,
    )


def _build_status_message(job: DiscoveryJob) -> str:
    """Build a human-readable status message for a job."""
    match job.status:
        case JobStatus.PENDING:
            return "Discovery job is pending..."
        case JobStatus.RUNNING:
            if job.pipeline_stage == "discovery":
                return "Searching for trip options..."
            elif job.pipeline_stage:
                return f"Building itinerary ({job.pipeline_stage})..."
            return "Discovery in progress..."
        case JobStatus.COMPLETED:
            return "Your itinerary is ready!"
        case JobStatus.PARTIAL:
            return "Trip planning completed with some gaps."
        case JobStatus.FAILED:
            return f"Trip planning failed: {job.error or 'Unknown error'}"
        case JobStatus.CANCELLED:
            return "Trip planning was cancelled."
        case _:
            return f"Job status: {job.status}"


# =============================================================================
# Default Router Instance
# =============================================================================

# Create a default router instance for easy import
discovery_router = create_discovery_router()
