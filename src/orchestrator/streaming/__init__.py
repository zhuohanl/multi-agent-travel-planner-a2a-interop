"""
Streaming module for SSE progress updates during long-running operations.

This module provides real-time progress streaming via Server-Sent Events (SSE)
for discovery and planning operations that can take 10-30+ seconds.

Per design doc "Long-Running Operations" section:
- SSE streaming provides smooth UX for long operations
- Progress is tracked in-memory to avoid race conditions
- Clients subscribe to progress channels for real-time updates

Key components:
- ProgressUpdate: Data model for progress events
- ProgressChannel: In-memory pub/sub channel for a single job
- ProgressStreamer: Manages progress channels across all active jobs
- get_progress_streamer(): Get the global streamer instance

Usage:
    from src.orchestrator.streaming import (
        ProgressUpdate,
        ProgressEventType,
        get_progress_streamer,
        get_progress_channel,
    )

    # Create channel and stream progress
    streamer = get_progress_streamer()
    channel = await streamer.create_channel(job_id)
    await channel.publish(ProgressUpdate(type=ProgressEventType.AGENT_STARTED, agent="transport"))

    # Subscribe to progress (from SSE endpoint)
    async for update in channel.subscribe():
        yield f"data: {update.to_json()}\n\n"
"""

from __future__ import annotations

from src.orchestrator.streaming.progress import (
    ProgressChannel,
    ProgressEventType,
    ProgressStreamer,
    ProgressUpdate,
    get_progress_channel,
    get_progress_streamer,
)

__all__ = [
    # Data models
    "ProgressEventType",
    "ProgressUpdate",
    # Channel management
    "ProgressChannel",
    "ProgressStreamer",
    # Convenience functions
    "get_progress_channel",
    "get_progress_streamer",
]
