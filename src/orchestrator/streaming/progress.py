"""
SSE streaming for progress updates during long-running operations.

This module implements Server-Sent Events (SSE) streaming for discovery and
planning pipeline progress. It provides real-time feedback during operations
that can take 10-30+ seconds.

Per design doc "Long-Running Operations" section:
- SSE streaming provides smooth UX for long operations
- Progress is tracked in-memory to avoid race conditions during parallel execution
- Clients can subscribe to progress channels for real-time updates

Key components:
- ProgressUpdate: Data model for progress events
- ProgressChannel: In-memory pub/sub channel for a single job
- ProgressStreamer: Manages progress channels across all active jobs

Usage:
    # Start streaming progress
    streamer = ProgressStreamer()
    channel = streamer.create_channel(job_id)

    # Publish updates (from worker)
    await channel.publish(ProgressUpdate(type="agent_started", agent="transport"))

    # Subscribe to updates (from SSE endpoint)
    async for update in channel.subscribe():
        yield {"event": "progress", "data": update.to_json()}
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncGenerator

logger = logging.getLogger(__name__)


class ProgressEventType(str, Enum):
    """Types of progress events that can be streamed."""

    # Job lifecycle events
    JOB_STARTED = "job_started"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"
    JOB_CANCELLED = "job_cancelled"

    # Agent progress events
    AGENT_STARTED = "agent_started"
    AGENT_PROGRESS = "agent_progress"  # Interim progress message
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    AGENT_TIMEOUT = "agent_timeout"

    # Pipeline stage events
    PIPELINE_STAGE_STARTED = "pipeline_stage_started"
    PIPELINE_STAGE_COMPLETED = "pipeline_stage_completed"

    # State events (for reconnection)
    STATE = "state"  # Current persisted state snapshot


@dataclass
class ProgressUpdate:
    """
    A progress update event for SSE streaming.

    Per design doc, progress updates are streamed in real-time during
    discovery and planning operations. They include event type, optional
    agent name, and optional message/data.
    """

    type: ProgressEventType | str
    agent: str | None = None
    stage: str | None = None  # Pipeline stage (aggregator, budget, route, validator)
    message: str | None = None
    data: dict[str, Any] | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "type": self.type.value if isinstance(self.type, ProgressEventType) else self.type,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.agent is not None:
            result["agent"] = self.agent
        if self.stage is not None:
            result["stage"] = self.stage
        if self.message is not None:
            result["message"] = self.message
        if self.data is not None:
            result["data"] = self.data
        return result

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProgressUpdate:
        """Create from dictionary."""
        event_type = data.get("type", "unknown")
        try:
            event_type = ProgressEventType(event_type)
        except ValueError:
            pass  # Keep as string if not a known event type

        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        else:
            timestamp = datetime.now(timezone.utc)

        return cls(
            type=event_type,
            agent=data.get("agent"),
            stage=data.get("stage"),
            message=data.get("message"),
            data=data.get("data"),
            timestamp=timestamp,
        )


class ProgressChannel:
    """
    In-memory pub/sub channel for streaming progress updates.

    This channel allows multiple subscribers (SSE connections) to receive
    real-time progress updates from a single publisher (the job worker).

    Per design doc:
    - Progress is tracked in-memory during parallel execution (no DB writes mid-job)
    - SSE endpoint subscribes to channel to forward events to clients
    - Handles graceful cleanup on subscriber disconnect
    """

    def __init__(self, job_id: str, max_history: int = 100) -> None:
        """
        Initialize a progress channel.

        Args:
            job_id: The job ID this channel is for
            max_history: Maximum number of events to keep in history for late subscribers
        """
        self._job_id = job_id
        self._max_history = max_history
        self._subscribers: list[asyncio.Queue[ProgressUpdate | None]] = []
        self._history: list[ProgressUpdate] = []
        self._closed = False
        self._lock = asyncio.Lock()

    @property
    def job_id(self) -> str:
        """Get the job ID for this channel."""
        return self._job_id

    @property
    def is_closed(self) -> bool:
        """Check if the channel is closed."""
        return self._closed

    @property
    def subscriber_count(self) -> int:
        """Get the number of active subscribers."""
        return len(self._subscribers)

    async def publish(self, update: ProgressUpdate) -> None:
        """
        Publish a progress update to all subscribers.

        Args:
            update: The progress update to publish
        """
        if self._closed:
            logger.warning("Attempted to publish to closed channel: %s", self._job_id)
            return

        async with self._lock:
            # Add to history
            self._history.append(update)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history :]

            # Notify all subscribers
            for queue in self._subscribers:
                try:
                    await queue.put(update)
                except Exception as e:
                    logger.warning("Failed to notify subscriber: %s", e)

        logger.debug(
            "Published progress update: type=%s, agent=%s, job=%s",
            update.type,
            update.agent,
            self._job_id,
        )

    async def subscribe(
        self, include_history: bool = True
    ) -> AsyncGenerator[ProgressUpdate, None]:
        """
        Subscribe to progress updates from this channel.

        This is an async generator that yields progress updates as they
        are published. It handles graceful cleanup on disconnect.

        Args:
            include_history: If True, yields all historical events first

        Yields:
            ProgressUpdate events as they are published
        """
        queue: asyncio.Queue[ProgressUpdate | None] = asyncio.Queue()

        async with self._lock:
            self._subscribers.append(queue)

            # Send history first if requested
            if include_history:
                for update in self._history:
                    await queue.put(update)

        logger.debug(
            "New subscriber for channel %s (total: %d)",
            self._job_id,
            len(self._subscribers),
        )

        try:
            while True:
                update = await queue.get()

                # None signals channel close
                if update is None:
                    break

                yield update

                # Check for terminal events
                if isinstance(update.type, ProgressEventType) and update.type in (
                    ProgressEventType.JOB_COMPLETED,
                    ProgressEventType.JOB_FAILED,
                    ProgressEventType.JOB_CANCELLED,
                ):
                    break

        finally:
            async with self._lock:
                if queue in self._subscribers:
                    self._subscribers.remove(queue)
            logger.debug(
                "Subscriber disconnected from channel %s (remaining: %d)",
                self._job_id,
                len(self._subscribers),
            )

    async def close(self) -> None:
        """
        Close the channel and notify all subscribers.

        This should be called when the job completes or is cancelled.
        """
        if self._closed:
            return

        async with self._lock:
            self._closed = True
            # Signal all subscribers to stop
            for queue in self._subscribers:
                try:
                    await queue.put(None)
                except Exception as e:
                    logger.warning("Failed to close subscriber: %s", e)
            self._subscribers.clear()

        logger.debug("Closed channel: %s", self._job_id)

    def get_history(self) -> list[ProgressUpdate]:
        """Get a copy of the event history."""
        return list(self._history)


class ProgressStreamer:
    """
    Manager for progress channels across all active jobs.

    This class provides a central registry for progress channels, allowing
    SSE endpoints to find channels for specific jobs.

    Per design doc:
    - Single-process deployment: API and worker share memory (direct channel access)
    - Distributed deployment: Use Redis pub/sub instead of in-memory channels

    This implementation covers the single-process case. For distributed
    deployment, channels would be backed by Redis pub/sub.
    """

    def __init__(self) -> None:
        """Initialize the progress streamer."""
        self._channels: dict[str, ProgressChannel] = {}
        self._lock = asyncio.Lock()

    async def create_channel(self, job_id: str) -> ProgressChannel:
        """
        Create a new progress channel for a job.

        Args:
            job_id: The job ID to create a channel for

        Returns:
            The created ProgressChannel

        Raises:
            ValueError: If a channel already exists for this job
        """
        async with self._lock:
            if job_id in self._channels:
                raise ValueError(f"Channel already exists for job: {job_id}")

            channel = ProgressChannel(job_id)
            self._channels[job_id] = channel
            logger.info("Created progress channel for job: %s", job_id)
            return channel

    async def get_channel(self, job_id: str) -> ProgressChannel | None:
        """
        Get an existing progress channel.

        Args:
            job_id: The job ID to get the channel for

        Returns:
            The ProgressChannel if it exists, None otherwise
        """
        return self._channels.get(job_id)

    async def get_or_create_channel(self, job_id: str) -> ProgressChannel:
        """
        Get an existing channel or create a new one.

        Args:
            job_id: The job ID to get/create a channel for

        Returns:
            The ProgressChannel (existing or new)
        """
        async with self._lock:
            if job_id not in self._channels:
                channel = ProgressChannel(job_id)
                self._channels[job_id] = channel
                logger.info("Created progress channel for job: %s", job_id)
                return channel
            return self._channels[job_id]

    async def close_channel(self, job_id: str) -> None:
        """
        Close and remove a progress channel.

        Args:
            job_id: The job ID to close the channel for
        """
        async with self._lock:
            channel = self._channels.pop(job_id, None)
            if channel:
                await channel.close()
                logger.info("Closed and removed progress channel for job: %s", job_id)

    async def close_all(self) -> None:
        """Close all active channels (for shutdown)."""
        async with self._lock:
            for channel in self._channels.values():
                await channel.close()
            self._channels.clear()
            logger.info("Closed all progress channels")

    @property
    def active_channels(self) -> list[str]:
        """Get list of active channel job IDs."""
        return list(self._channels.keys())

    def __len__(self) -> int:
        """Get number of active channels."""
        return len(self._channels)


# Global singleton for shared access across the application
# In production, this would be replaced with Redis pub/sub
_global_streamer: ProgressStreamer | None = None


def get_progress_streamer() -> ProgressStreamer:
    """
    Get the global progress streamer instance.

    This provides a shared ProgressStreamer across the application,
    allowing workers and SSE endpoints to share channels.

    Returns:
        The global ProgressStreamer instance
    """
    global _global_streamer
    if _global_streamer is None:
        _global_streamer = ProgressStreamer()
    return _global_streamer


async def get_progress_channel(job_id: str) -> ProgressChannel | None:
    """
    Convenience function to get a progress channel by job ID.

    Args:
        job_id: The job ID to get the channel for

    Returns:
        The ProgressChannel if it exists, None otherwise
    """
    return await get_progress_streamer().get_channel(job_id)
