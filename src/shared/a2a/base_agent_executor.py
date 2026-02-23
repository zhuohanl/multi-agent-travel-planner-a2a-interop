import inspect
import logging
from collections.abc import AsyncIterable
from typing import Any, NotRequired, Protocol, TypedDict

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import (
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.utils import new_agent_text_message, new_task, new_text_artifact

logger = logging.getLogger(__name__)


class AgentStreamChunk(TypedDict):
    require_user_input: bool
    is_task_complete: bool
    content: str
    data: NotRequired[dict[str, Any]]


class StreamableAgent(Protocol):
    async def stream(
        self,
        user_input: str,
        session_id: str,
        history: list[dict] | None = None,
        history_seq: int | None = None,
    ) -> AsyncIterable[AgentStreamChunk]:
        ...


class BaseA2AAgentExecutor(AgentExecutor):
    """Base executor that adapts a streamable agent to the A2A protocol."""

    def __init__(self, agent: StreamableAgent | None = None):
        self.agent = agent or self.build_agent()
        self._stream_accepts_event = self._detect_event_support()

    def build_agent(self) -> StreamableAgent:
        raise NotImplementedError("Subclasses must provide an agent instance.")

    def get_completion_artifact_name(self) -> str:
        return "current_result"

    def get_completion_artifact_description(self) -> str:
        return "Result of request to agent."

    def build_input_required_message(self, content: str, task) -> object:
        return new_agent_text_message(content, task.context_id, task.id)

    def build_working_message(self, content: str, task) -> object:
        return new_agent_text_message(content, task.context_id, task.id)

    def build_completion_artifact(self, content: str) -> object:
        return new_text_artifact(
            name=self.get_completion_artifact_name(),
            description=self.get_completion_artifact_description(),
            text=content,
        )

    def _extract_history_from_metadata(
        self, context: RequestContext
    ) -> tuple[list[dict] | None, int | None, dict[str, Any] | None]:
        """Extract history and historySeq from request metadata.

        Per design doc (Agent Communication section):
        - History is sent via message.metadata.history for reliability
        - historySeq is a sequence number for divergence detection
        - If historySeq != agent's last_seen_seq, divergence is detected
        - event carries structured workflow actions from UI clicks

        Returns:
            Tuple of (history, history_seq, event). All may be None if not present.
        """
        history: list[dict] | None = None
        history_seq: int | None = None
        event: dict[str, Any] | None = None

        # Check if message has metadata attribute
        message = context.message
        if hasattr(message, "metadata") and message.metadata is not None:
            metadata = message.metadata
            if isinstance(metadata, dict):
                # Extract history list
                raw_history = metadata.get("history")
                if isinstance(raw_history, list):
                    history = raw_history
                    logger.info(
                        "Extracted history from metadata: %d messages",
                        len(history),
                    )

                # Extract historySeq (camelCase per A2A spec)
                raw_seq = metadata.get("historySeq")
                if isinstance(raw_seq, int):
                    history_seq = raw_seq
                    logger.info("Extracted historySeq from metadata: %d", history_seq)
                raw_event = metadata.get("event")
                if isinstance(raw_event, dict):
                    event = raw_event
                    logger.info(
                        "Extracted event from metadata with keys: %s",
                        list(event.keys()),
                    )

        return history, history_seq, event

    def _detect_event_support(self) -> bool:
        """Check if the agent stream method accepts an event keyword."""
        try:
            signature = inspect.signature(self.agent.stream)
        except (TypeError, ValueError):
            return False
        return "event" in signature.parameters

    def _attach_metadata(self, target: object, metadata: dict[str, Any] | None) -> None:
        """Attach metadata to message/artifact objects when supported."""
        if metadata is None:
            return
        if hasattr(target, "metadata"):
            setattr(target, "metadata", metadata)

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Execute agent request with A2A protocol support."""
        query = context.get_user_input()
        task = context.current_task

        logger.info(
            "Incoming message context_id: %s",
            context.message.context_id if hasattr(context.message, "context_id") else "None",
        )
        logger.info("Current task: %s", task)

        # Extract history from request metadata (per design doc Agent Communication)
        history, history_seq, event = self._extract_history_from_metadata(context)

        if not task:
            task = new_task(context.message)
            logger.info("Created new task with context_id: %s", task.context_id)
            await event_queue.enqueue_event(task)
        else:
            logger.info("Using existing task with context_id: %s", task.context_id)

        stream_kwargs: dict[str, Any] = {
            "history": history,
            "history_seq": history_seq,
        }
        if event is not None and self._stream_accepts_event:
            # Only pass event if the agent stream signature supports it.
            stream_kwargs["event"] = event

        async for partial in self.agent.stream(
            query, task.context_id, **stream_kwargs
        ):
            require_input = partial["require_user_input"]
            is_done = partial["is_task_complete"]
            text_content = partial["content"]
            metadata = None
            if isinstance(partial, dict):
                payload = partial.get("data")
                if isinstance(payload, dict):
                    # Surface structured payloads (like UI actions) via A2A metadata.
                    metadata = payload

            if require_input:
                message = self.build_input_required_message(text_content, task)
                self._attach_metadata(message, metadata)
                await event_queue.enqueue_event(
                    TaskStatusUpdateEvent(
                        status=TaskStatus(
                            state=TaskState.input_required,
                            message=message,
                        ),
                        final=True,
                        contextId=task.context_id,
                        taskId=task.id,
                    )
                )
            elif is_done:
                artifact = self.build_completion_artifact(text_content)
                self._attach_metadata(artifact, metadata)
                await event_queue.enqueue_event(
                    TaskArtifactUpdateEvent(
                        append=False,
                        contextId=task.context_id,
                        taskId=task.id,
                        lastChunk=True,
                        artifact=artifact,
                    )
                )
                await event_queue.enqueue_event(
                    TaskStatusUpdateEvent(
                        status=TaskStatus(state=TaskState.completed),
                        final=True,
                        contextId=task.context_id,
                        taskId=task.id,
                    )
                )
            else:
                message = self.build_working_message(text_content, task)
                self._attach_metadata(message, metadata)
                await event_queue.enqueue_event(
                    TaskStatusUpdateEvent(
                        status=TaskStatus(
                            state=TaskState.working,
                            message=message,
                        ),
                        final=False,
                        contextId=task.context_id,
                        taskId=task.id,
                    )
                )

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """Cancel the current task execution."""
        logger.warning("Task cancellation requested but not implemented")
        raise Exception("cancel not supported")
