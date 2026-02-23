"""
Discovery job runner for background execution.

This module wires TripSpec approval to discovery + planning execution:
- Runs discovery agents in parallel
- Persists job results to DiscoveryJobStore
- Runs planning pipeline and syncs WorkflowState
- Streams progress events via ProgressChannel
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any

from src.orchestrator.discovery.parallel_executor import (
    DISCOVERY_AGENTS,
    DiscoveryResults,
    TripSpec,
    execute_parallel_discovery,
)
from src.orchestrator.discovery.state_sync import finalize_job_with_planning
from src.orchestrator.storage.discovery_jobs import (
    AgentProgress,
    DiscoveryJob,
    DiscoveryJobStoreProtocol,
    JobStatus,
)
from src.orchestrator.streaming.progress import (
    ProgressEventType,
    ProgressUpdate,
    get_progress_streamer,
)

if TYPE_CHECKING:
    from src.shared.a2a.client_wrapper import A2AClientWrapper
    from src.shared.a2a.registry import AgentRegistry
    from src.shared.storage.protocols import WorkflowStoreProtocol

logger = logging.getLogger(__name__)


def _normalize_trip_spec(trip_spec: Any) -> dict[str, Any]:
    if trip_spec is None:
        return {}
    if isinstance(trip_spec, dict):
        return trip_spec
    if hasattr(trip_spec, "to_dict"):
        return trip_spec.to_dict()
    return {}


def _stringify_date(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None:
        return ""
    return str(value)


def build_executor_trip_spec(trip_spec: dict[str, Any]) -> TripSpec:
    destination = (
        trip_spec.get("destination")
        or trip_spec.get("destination_city")
        or "unknown"
    )
    start_date = _stringify_date(trip_spec.get("start_date"))
    end_date = _stringify_date(trip_spec.get("end_date"))
    travelers = (
        trip_spec.get("num_travelers")
        or trip_spec.get("travelers")
        or trip_spec.get("num_people")
        or 1
    )

    budget = trip_spec.get("budget")
    if budget is None and "budget_per_person" in trip_spec:
        currency = trip_spec.get("budget_currency", "")
        budget = f"{currency} {trip_spec.get('budget_per_person')}".strip()

    preferences: dict[str, Any] = {}
    for key in ("interests", "constraints", "preferences"):
        if key in trip_spec:
            preferences[key] = trip_spec.get(key)

    return TripSpec(
        destination=str(destination),
        start_date=start_date,
        end_date=end_date,
        travelers=int(travelers),
        budget=str(budget) if budget else None,
        preferences=preferences,
    )


def build_discovery_request(trip_spec: TripSpec, agent: str) -> str:
    destination = trip_spec.destination or "unknown"
    start_date = trip_spec.start_date or ""
    end_date = trip_spec.end_date or ""
    travelers = trip_spec.travelers or 1

    prompts = {
        "transport": (
            f"Find flight options to {destination} from {start_date} "
            f"to {end_date} for {travelers} travelers."
        ),
        "stay": (
            f"Find hotel options in {destination} from {start_date} "
            f"to {end_date} for {travelers} guests."
        ),
        "poi": f"Find top attractions and points of interest in {destination}.",
        "events": (
            f"Find events happening in {destination} between {start_date} "
            f"and {end_date}."
        ),
        "dining": f"Find restaurant recommendations in {destination}.",
    }

    return prompts.get(agent, f"Search for {agent} options in {destination}.")


def _build_agent_progress(results: DiscoveryResults) -> dict[str, AgentProgress]:
    progress: dict[str, AgentProgress] = {}
    for agent in DISCOVERY_AGENTS:
        result = results.get_result(agent)
        if result is None:
            continue
        status = "failed"
        if result.status.value == "success":
            status = "completed"
        elif result.status.value == "timeout":
            status = "timeout"
        progress[agent] = AgentProgress(
            agent=agent,
            status=status,
            message=result.message,
            completed_at=result.timestamp,
        )
    return progress


def _derive_job_status(results: DiscoveryResults) -> JobStatus:
    if results.is_complete:
        return JobStatus.COMPLETED
    if not results.has_any_results:
        return JobStatus.FAILED
    return JobStatus.PARTIAL


def _stage_label(stage: str) -> str:
    labels = {
        "discovery": "discovery",
        "aggregator": "aggregation",
        "budget": "budget planning",
        "route": "route planning",
        "validator": "validation",
    }
    return labels.get(stage, stage.replace("_", " "))


async def run_discovery_job(
    job: DiscoveryJob,
    *,
    trip_spec: dict[str, Any] | None,
    session_id: str,
    discovery_job_store: DiscoveryJobStoreProtocol,
    workflow_store: "WorkflowStoreProtocol",
    a2a_client: "A2AClientWrapper | None" = None,
    agent_registry: "AgentRegistry | None" = None,
) -> None:
    """
    Run discovery agents in parallel, then planning, and sync to workflow state.

    This function is intended to be launched in the background (create_task).
    """
    progress_channel = await get_progress_streamer().get_or_create_channel(job.job_id)
    await progress_channel.publish(
        ProgressUpdate(
            type=ProgressEventType.JOB_STARTED,
            message="Discovery started",
            data={"job_id": job.job_id},
        )
    )

    trip_spec_dict = _normalize_trip_spec(trip_spec)
    executor_trip_spec = build_executor_trip_spec(trip_spec_dict)

    try:
        results = await execute_parallel_discovery(
            executor_trip_spec,
            a2a_client=a2a_client,
            agent_registry=agent_registry,
            progress_channel=progress_channel,
            request_builder=build_discovery_request,
        )

        job.agent_progress = _build_agent_progress(results)
        job.discovery_results = results.to_dict()
        job.status = _derive_job_status(results)
        job.completed_at = datetime.now(timezone.utc)
        job.pipeline_stage = "discovery"
        await discovery_job_store.save_job(job)

        async def report_stage_progress(
            stage: str,
            event: str,
        ) -> None:
            job.pipeline_stage = stage
            await discovery_job_store.save_job(job)

            event_type = (
                ProgressEventType.PIPELINE_STAGE_STARTED
                if event == "started"
                else ProgressEventType.PIPELINE_STAGE_COMPLETED
            )
            stage_label = _stage_label(stage)
            verb = "started" if event == "started" else "completed"
            await progress_channel.publish(
                ProgressUpdate(
                    type=event_type,
                    stage=stage,
                    message=f"{stage_label.title()} {verb}",
                    data={"job_id": job.job_id, "stage": stage},
                )
            )

        sync_result = None
        for attempt in range(3):
            sync_result = await finalize_job_with_planning(
                job=job,
                workflow_store=workflow_store,
                job_store=discovery_job_store,
                session_id=session_id,
                a2a_client=a2a_client,
                agent_registry=agent_registry,
                stage_progress_callback=report_stage_progress,
            )
            if sync_result.success:
                break
            if sync_result.reason and "expected DISCOVERY_IN_PROGRESS" in sync_result.reason:
                await asyncio.sleep(0.2 * (attempt + 1))
                continue
            if sync_result.reason and "Workflow state not found" in sync_result.reason:
                await asyncio.sleep(0.2 * (attempt + 1))
                continue
            break

        if sync_result and not sync_result.success:
            logger.warning(
                "Discovery job %s finalized with warnings: %s",
                job.job_id,
                sync_result.reason,
            )

        final_event = (
            ProgressEventType.JOB_COMPLETED
            if job.status in (JobStatus.COMPLETED, JobStatus.PARTIAL)
            else ProgressEventType.JOB_FAILED
        )
        await progress_channel.publish(
            ProgressUpdate(
                type=final_event,
                message="Discovery finished",
                data={"job_id": job.job_id, "status": job.status.value},
            )
        )

    except Exception as exc:
        logger.exception("Discovery job %s failed: %s", job.job_id, exc)
        job.status = JobStatus.FAILED
        job.completed_at = datetime.now(timezone.utc)
        job.error = str(exc)
        await discovery_job_store.save_job(job)
        await progress_channel.publish(
            ProgressUpdate(
                type=ProgressEventType.JOB_FAILED,
                message="Discovery failed",
                data={"job_id": job.job_id, "error": str(exc)},
            )
        )
    finally:
        await get_progress_streamer().close_channel(job.job_id)


def spawn_discovery_job(
    job: DiscoveryJob,
    *,
    trip_spec: dict[str, Any] | None,
    session_id: str,
    discovery_job_store: DiscoveryJobStoreProtocol,
    workflow_store: "WorkflowStoreProtocol",
    a2a_client: "A2AClientWrapper | None" = None,
    agent_registry: "AgentRegistry | None" = None,
) -> None:
    """Spawn discovery+planning in the background (best-effort)."""
    async def _run() -> None:
        await run_discovery_job(
            job=job,
            trip_spec=trip_spec,
            session_id=session_id,
            discovery_job_store=discovery_job_store,
            workflow_store=workflow_store,
            a2a_client=a2a_client,
            agent_registry=agent_registry,
        )

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        asyncio.run(_run())
