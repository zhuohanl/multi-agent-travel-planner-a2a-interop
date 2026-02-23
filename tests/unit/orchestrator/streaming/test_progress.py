"""
Unit tests for the SSE streaming progress module.

Tests cover:
- ProgressUpdate data model and serialization
- ProgressChannel pub/sub functionality
- ProgressStreamer channel management
- Graceful disconnect handling
- Integration with discovery executor
"""

import asyncio
from datetime import datetime, timezone

import pytest

from src.orchestrator.streaming.progress import (
    ProgressChannel,
    ProgressEventType,
    ProgressStreamer,
    ProgressUpdate,
    get_progress_channel,
    get_progress_streamer,
)


class TestProgressUpdate:
    """Tests for ProgressUpdate data model."""

    def test_create_basic_update(self) -> None:
        """Test creating a basic progress update."""
        update = ProgressUpdate(type=ProgressEventType.JOB_STARTED)

        assert update.type == ProgressEventType.JOB_STARTED
        assert update.agent is None
        assert update.message is None
        assert update.data is None
        assert isinstance(update.timestamp, datetime)

    def test_create_agent_update(self) -> None:
        """Test creating an agent-specific progress update."""
        update = ProgressUpdate(
            type=ProgressEventType.AGENT_STARTED,
            agent="transport",
            message="Starting flight search...",
        )

        assert update.type == ProgressEventType.AGENT_STARTED
        assert update.agent == "transport"
        assert update.message == "Starting flight search..."

    def test_create_update_with_data(self) -> None:
        """Test creating an update with additional data."""
        update = ProgressUpdate(
            type=ProgressEventType.AGENT_COMPLETED,
            agent="stay",
            message="Found 12 hotels",
            data={"count": 12, "destination": "Paris"},
        )

        assert update.data == {"count": 12, "destination": "Paris"}

    def test_to_dict(self) -> None:
        """Test converting update to dictionary."""
        update = ProgressUpdate(
            type=ProgressEventType.AGENT_PROGRESS,
            agent="poi",
            message="Searching attractions...",
        )

        d = update.to_dict()

        assert d["type"] == "agent_progress"
        assert d["agent"] == "poi"
        assert d["message"] == "Searching attractions..."
        assert "timestamp" in d

    def test_to_json(self) -> None:
        """Test converting update to JSON string."""
        update = ProgressUpdate(
            type=ProgressEventType.JOB_COMPLETED,
            message="All agents completed",
        )

        json_str = update.to_json()

        assert '"type": "job_completed"' in json_str
        assert '"message": "All agents completed"' in json_str

    def test_from_dict(self) -> None:
        """Test creating update from dictionary."""
        d = {
            "type": "agent_started",
            "agent": "dining",
            "message": "Searching restaurants...",
            "timestamp": "2024-01-15T10:30:00+00:00",
        }

        update = ProgressUpdate.from_dict(d)

        assert update.type == ProgressEventType.AGENT_STARTED
        assert update.agent == "dining"
        assert update.message == "Searching restaurants..."

    def test_from_dict_unknown_event_type(self) -> None:
        """Test that unknown event types are kept as strings."""
        d = {"type": "custom_event", "message": "Custom"}

        update = ProgressUpdate.from_dict(d)

        assert update.type == "custom_event"
        assert update.message == "Custom"

    def test_pipeline_stage_update(self) -> None:
        """Test creating a pipeline stage update."""
        update = ProgressUpdate(
            type=ProgressEventType.PIPELINE_STAGE_STARTED,
            stage="aggregator",
            message="Aggregating results...",
        )

        assert update.type == ProgressEventType.PIPELINE_STAGE_STARTED
        assert update.stage == "aggregator"

        d = update.to_dict()
        assert d["stage"] == "aggregator"


class TestProgressChannel:
    """Tests for ProgressChannel pub/sub functionality."""

    @pytest.fixture
    def channel(self) -> ProgressChannel:
        """Create a test channel."""
        return ProgressChannel("job_test123")

    @pytest.mark.asyncio
    async def test_channel_properties(self, channel: ProgressChannel) -> None:
        """Test channel properties."""
        assert channel.job_id == "job_test123"
        assert not channel.is_closed
        assert channel.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_publish_and_subscribe(self, channel: ProgressChannel) -> None:
        """Test basic publish/subscribe flow."""
        received: list[ProgressUpdate] = []

        async def subscriber() -> None:
            async for update in channel.subscribe(include_history=False):
                received.append(update)
                if update.type == ProgressEventType.JOB_COMPLETED:
                    break

        # Start subscriber
        task = asyncio.create_task(subscriber())

        # Give subscriber time to register
        await asyncio.sleep(0.01)

        # Publish updates
        await channel.publish(
            ProgressUpdate(type=ProgressEventType.AGENT_STARTED, agent="transport")
        )
        await channel.publish(
            ProgressUpdate(type=ProgressEventType.AGENT_COMPLETED, agent="transport")
        )
        await channel.publish(ProgressUpdate(type=ProgressEventType.JOB_COMPLETED))

        # Wait for subscriber to finish
        await asyncio.wait_for(task, timeout=1.0)

        assert len(received) == 3
        assert received[0].type == ProgressEventType.AGENT_STARTED
        assert received[1].type == ProgressEventType.AGENT_COMPLETED
        assert received[2].type == ProgressEventType.JOB_COMPLETED

    @pytest.mark.asyncio
    async def test_subscriber_receives_history(self, channel: ProgressChannel) -> None:
        """Test that new subscribers receive historical events."""
        # Publish some events before subscribing
        await channel.publish(
            ProgressUpdate(type=ProgressEventType.AGENT_STARTED, agent="transport")
        )
        await channel.publish(
            ProgressUpdate(type=ProgressEventType.AGENT_COMPLETED, agent="transport")
        )

        received: list[ProgressUpdate] = []

        async def subscriber() -> None:
            async for update in channel.subscribe(include_history=True):
                received.append(update)
                if update.type == ProgressEventType.JOB_COMPLETED:
                    break

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)

        # Publish completion
        await channel.publish(ProgressUpdate(type=ProgressEventType.JOB_COMPLETED))

        await asyncio.wait_for(task, timeout=1.0)

        # Should receive historical events + completion
        assert len(received) == 3

    @pytest.mark.asyncio
    async def test_subscriber_skips_history(self, channel: ProgressChannel) -> None:
        """Test that history can be skipped."""
        # Publish some events before subscribing
        await channel.publish(
            ProgressUpdate(type=ProgressEventType.AGENT_STARTED, agent="transport")
        )

        received: list[ProgressUpdate] = []

        async def subscriber() -> None:
            async for update in channel.subscribe(include_history=False):
                received.append(update)
                if update.type == ProgressEventType.JOB_COMPLETED:
                    break

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)

        await channel.publish(ProgressUpdate(type=ProgressEventType.JOB_COMPLETED))

        await asyncio.wait_for(task, timeout=1.0)

        # Should only receive the completion event
        assert len(received) == 1
        assert received[0].type == ProgressEventType.JOB_COMPLETED

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self, channel: ProgressChannel) -> None:
        """Test multiple subscribers receive same updates."""
        received1: list[ProgressUpdate] = []
        received2: list[ProgressUpdate] = []

        async def subscriber1() -> None:
            async for update in channel.subscribe(include_history=False):
                received1.append(update)
                if update.type == ProgressEventType.JOB_COMPLETED:
                    break

        async def subscriber2() -> None:
            async for update in channel.subscribe(include_history=False):
                received2.append(update)
                if update.type == ProgressEventType.JOB_COMPLETED:
                    break

        task1 = asyncio.create_task(subscriber1())
        task2 = asyncio.create_task(subscriber2())
        await asyncio.sleep(0.01)

        assert channel.subscriber_count == 2

        await channel.publish(
            ProgressUpdate(type=ProgressEventType.AGENT_STARTED, agent="stay")
        )
        await channel.publish(ProgressUpdate(type=ProgressEventType.JOB_COMPLETED))

        await asyncio.gather(
            asyncio.wait_for(task1, timeout=1.0),
            asyncio.wait_for(task2, timeout=1.0),
        )

        assert len(received1) == 2
        assert len(received2) == 2

    @pytest.mark.asyncio
    async def test_channel_close(self, channel: ProgressChannel) -> None:
        """Test that closing channel notifies subscribers."""
        subscriber_done = asyncio.Event()

        async def subscriber() -> None:
            async for _ in channel.subscribe(include_history=False):
                pass
            subscriber_done.set()

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)

        await channel.close()

        await asyncio.wait_for(subscriber_done.wait(), timeout=1.0)
        assert channel.is_closed
        assert channel.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_publish_to_closed_channel(self, channel: ProgressChannel) -> None:
        """Test that publishing to closed channel is a no-op."""
        await channel.close()

        # Should not raise, just log a warning
        await channel.publish(ProgressUpdate(type=ProgressEventType.AGENT_STARTED))

    @pytest.mark.asyncio
    async def test_get_history(self, channel: ProgressChannel) -> None:
        """Test getting event history."""
        await channel.publish(
            ProgressUpdate(type=ProgressEventType.AGENT_STARTED, agent="transport")
        )
        await channel.publish(
            ProgressUpdate(type=ProgressEventType.AGENT_COMPLETED, agent="transport")
        )

        history = channel.get_history()

        assert len(history) == 2
        assert history[0].type == ProgressEventType.AGENT_STARTED
        assert history[1].type == ProgressEventType.AGENT_COMPLETED

    @pytest.mark.asyncio
    async def test_history_max_size(self) -> None:
        """Test that history is limited to max size."""
        channel = ProgressChannel("job_test", max_history=5)

        # Publish more than max_history events
        for i in range(10):
            await channel.publish(
                ProgressUpdate(
                    type=ProgressEventType.AGENT_PROGRESS,
                    message=f"Event {i}",
                )
            )

        history = channel.get_history()
        assert len(history) == 5
        assert history[0].message == "Event 5"
        assert history[4].message == "Event 9"


class TestProgressStreamer:
    """Tests for ProgressStreamer channel management."""

    @pytest.fixture
    def streamer(self) -> ProgressStreamer:
        """Create a test streamer."""
        return ProgressStreamer()

    @pytest.mark.asyncio
    async def test_create_channel(self, streamer: ProgressStreamer) -> None:
        """Test creating a new channel."""
        channel = await streamer.create_channel("job_123")

        assert channel.job_id == "job_123"
        assert len(streamer) == 1
        assert "job_123" in streamer.active_channels

    @pytest.mark.asyncio
    async def test_create_duplicate_channel_raises(
        self, streamer: ProgressStreamer
    ) -> None:
        """Test that creating a duplicate channel raises."""
        await streamer.create_channel("job_123")

        with pytest.raises(ValueError, match="Channel already exists"):
            await streamer.create_channel("job_123")

    @pytest.mark.asyncio
    async def test_get_channel(self, streamer: ProgressStreamer) -> None:
        """Test getting an existing channel."""
        await streamer.create_channel("job_123")

        channel = await streamer.get_channel("job_123")

        assert channel is not None
        assert channel.job_id == "job_123"

    @pytest.mark.asyncio
    async def test_get_nonexistent_channel(self, streamer: ProgressStreamer) -> None:
        """Test getting a non-existent channel returns None."""
        channel = await streamer.get_channel("job_nonexistent")

        assert channel is None

    @pytest.mark.asyncio
    async def test_get_or_create_channel(self, streamer: ProgressStreamer) -> None:
        """Test get_or_create creates new channel if needed."""
        channel1 = await streamer.get_or_create_channel("job_123")
        channel2 = await streamer.get_or_create_channel("job_123")

        assert channel1 is channel2
        assert len(streamer) == 1

    @pytest.mark.asyncio
    async def test_close_channel(self, streamer: ProgressStreamer) -> None:
        """Test closing and removing a channel."""
        await streamer.create_channel("job_123")

        await streamer.close_channel("job_123")

        assert len(streamer) == 0
        assert await streamer.get_channel("job_123") is None

    @pytest.mark.asyncio
    async def test_close_nonexistent_channel(
        self, streamer: ProgressStreamer
    ) -> None:
        """Test closing a non-existent channel is a no-op."""
        # Should not raise
        await streamer.close_channel("job_nonexistent")

    @pytest.mark.asyncio
    async def test_close_all(self, streamer: ProgressStreamer) -> None:
        """Test closing all channels."""
        await streamer.create_channel("job_1")
        await streamer.create_channel("job_2")
        await streamer.create_channel("job_3")

        await streamer.close_all()

        assert len(streamer) == 0

    @pytest.mark.asyncio
    async def test_active_channels(self, streamer: ProgressStreamer) -> None:
        """Test getting list of active channels."""
        await streamer.create_channel("job_1")
        await streamer.create_channel("job_2")

        channels = streamer.active_channels

        assert set(channels) == {"job_1", "job_2"}


class TestGlobalStreamer:
    """Tests for global streamer functions."""

    def test_get_progress_streamer_singleton(self) -> None:
        """Test that get_progress_streamer returns a singleton."""
        streamer1 = get_progress_streamer()
        streamer2 = get_progress_streamer()

        assert streamer1 is streamer2

    @pytest.mark.asyncio
    async def test_get_progress_channel(self) -> None:
        """Test the get_progress_channel convenience function."""
        streamer = get_progress_streamer()
        await streamer.create_channel("job_global_test")

        channel = await get_progress_channel("job_global_test")

        assert channel is not None
        assert channel.job_id == "job_global_test"

        # Cleanup
        await streamer.close_channel("job_global_test")


class TestProgressChannelHandlesDisconnect:
    """Tests for graceful disconnect handling."""

    @pytest.mark.asyncio
    async def test_subscriber_disconnect_during_iteration(self) -> None:
        """Test that subscriber can disconnect mid-stream."""
        channel = ProgressChannel("job_disconnect")
        received: list[ProgressUpdate] = []

        async def subscriber() -> None:
            count = 0
            async for update in channel.subscribe(include_history=False):
                received.append(update)
                count += 1
                if count >= 2:
                    # Simulate early disconnect
                    break

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)

        # Publish several updates
        await channel.publish(
            ProgressUpdate(type=ProgressEventType.AGENT_STARTED, agent="transport")
        )
        await channel.publish(
            ProgressUpdate(type=ProgressEventType.AGENT_COMPLETED, agent="transport")
        )
        await channel.publish(
            ProgressUpdate(type=ProgressEventType.AGENT_STARTED, agent="stay")
        )

        await asyncio.wait_for(task, timeout=1.0)

        # Subscriber should have received exactly 2
        assert len(received) == 2

        # Channel should have removed the subscriber
        await asyncio.sleep(0.01)
        assert channel.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_terminal_events_close_subscription(self) -> None:
        """Test that terminal events (JOB_COMPLETED, etc.) close subscription."""
        channel = ProgressChannel("job_terminal")
        received: list[ProgressUpdate] = []

        async def subscriber() -> None:
            async for update in channel.subscribe(include_history=False):
                received.append(update)
            # Should exit after terminal event

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)

        await channel.publish(
            ProgressUpdate(type=ProgressEventType.AGENT_STARTED, agent="transport")
        )
        await channel.publish(ProgressUpdate(type=ProgressEventType.JOB_FAILED))

        await asyncio.wait_for(task, timeout=1.0)

        assert len(received) == 2
        assert received[-1].type == ProgressEventType.JOB_FAILED


class TestProgressStreamerSendsEvents:
    """Test that ProgressStreamer correctly sends events (acceptance criteria)."""

    @pytest.mark.asyncio
    async def test_progress_streamer_sends_events(self) -> None:
        """Test that progress updates are sent to subscribers."""
        streamer = ProgressStreamer()
        channel = await streamer.create_channel("job_send_test")
        received: list[ProgressUpdate] = []

        async def subscriber() -> None:
            async for update in channel.subscribe(include_history=False):
                received.append(update)
                if update.type == ProgressEventType.JOB_COMPLETED:
                    break

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)

        # Send various events
        await channel.publish(ProgressUpdate(type=ProgressEventType.JOB_STARTED))
        await channel.publish(
            ProgressUpdate(type=ProgressEventType.AGENT_STARTED, agent="transport")
        )
        await channel.publish(
            ProgressUpdate(
                type=ProgressEventType.AGENT_PROGRESS,
                agent="transport",
                message="Searching...",
            )
        )
        await channel.publish(
            ProgressUpdate(type=ProgressEventType.AGENT_COMPLETED, agent="transport")
        )
        await channel.publish(ProgressUpdate(type=ProgressEventType.JOB_COMPLETED))

        await asyncio.wait_for(task, timeout=1.0)

        assert len(received) == 5
        await streamer.close_channel("job_send_test")


class TestProgressEventFormat:
    """Test event format (acceptance criteria)."""

    def test_progress_streamer_event_format(self) -> None:
        """Test that events include type and data in correct format."""
        update = ProgressUpdate(
            type=ProgressEventType.AGENT_COMPLETED,
            agent="stay",
            message="Found 8 hotels",
            data={"count": 8, "destination": "Tokyo"},
        )

        d = update.to_dict()

        # Verify required fields
        assert "type" in d
        assert d["type"] == "agent_completed"
        assert "timestamp" in d

        # Verify optional fields when present
        assert d["agent"] == "stay"
        assert d["message"] == "Found 8 hotels"
        assert d["data"]["count"] == 8

        # Verify JSON format
        json_str = update.to_json()
        assert '"type": "agent_completed"' in json_str
        assert '"agent": "stay"' in json_str


class TestProgressChannelHandlesDisconnectGracefully:
    """Test graceful disconnect handling (acceptance criteria)."""

    @pytest.mark.asyncio
    async def test_progress_streamer_handles_disconnect(self) -> None:
        """Test that stream handles disconnections gracefully."""
        channel = ProgressChannel("job_graceful")

        # Start subscriber that will disconnect early
        disconnect_count = 0

        async def disconnecting_subscriber() -> None:
            nonlocal disconnect_count
            async for update in channel.subscribe(include_history=False):
                disconnect_count += 1
                if disconnect_count >= 1:
                    break

        # Start and let subscriber disconnect
        task = asyncio.create_task(disconnecting_subscriber())
        await asyncio.sleep(0.01)

        await channel.publish(
            ProgressUpdate(type=ProgressEventType.AGENT_STARTED, agent="transport")
        )

        await asyncio.wait_for(task, timeout=1.0)

        # Channel should still be operational
        assert not channel.is_closed

        # New subscriber should work
        new_received: list[ProgressUpdate] = []

        async def new_subscriber() -> None:
            async for update in channel.subscribe(include_history=False):
                new_received.append(update)
                if update.type == ProgressEventType.JOB_COMPLETED:
                    break

        task2 = asyncio.create_task(new_subscriber())
        await asyncio.sleep(0.01)

        await channel.publish(ProgressUpdate(type=ProgressEventType.JOB_COMPLETED))

        await asyncio.wait_for(task2, timeout=1.0)

        assert len(new_received) == 1
        await channel.close()
