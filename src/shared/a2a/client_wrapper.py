"""A2A client wrapper for agent-to-agent communication."""

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, A2AClient
from a2a.types import (
    AgentCard,
    MessageSendParams,
    SendStreamingMessageRequest,
)

# Conditional import for telemetry - graceful fallback when not installed
try:
    from opentelemetry.propagate import inject

    HAS_TELEMETRY = True
except ImportError:
    HAS_TELEMETRY = False
    inject = None  # type: ignore

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass
class A2AResponse:
    """Response from an A2A agent call."""

    text: str
    context_id: str | None = None
    task_id: str | None = None
    is_complete: bool = False
    requires_input: bool = False
    last_seen_seq: int | None = None
    raw_chunks: list[dict[str, Any]] = field(default_factory=list)


class A2AClientError(Exception):
    """Base exception for A2A client errors."""

    pass


class A2AConnectionError(A2AClientError):
    """Raised when connection to agent fails."""

    pass


class A2ATimeoutError(A2AClientError):
    """Raised when agent call times out."""

    pass


class A2AClientWrapper:
    """
    Wrapper for making A2A protocol calls to agent endpoints.

    Handles httpx client lifecycle, streaming response parsing,
    timeout handling, and multi-turn conversation state.

    Example:
        async with A2AClientWrapper() as wrapper:
            response = await wrapper.send_message(
                agent_url="http://localhost:10008",
                message="Plan a trip to Tokyo"
            )
            print(response.text)
    """

    def __init__(
        self,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        httpx_client: httpx.AsyncClient | None = None,
    ):
        """
        Initialize the A2A client wrapper.

        Args:
            timeout_seconds: Timeout for agent calls in seconds. Defaults to 30.
            httpx_client: Optional pre-configured httpx client. If not provided,
                          a new client will be created on context entry.
        """
        self._timeout_seconds = timeout_seconds
        self._external_client = httpx_client
        self._internal_client: httpx.AsyncClient | None = None
        self._agent_card_cache: dict[str, AgentCard] = {}
        self._a2a_client_cache: dict[str, A2AClient] = {}

    @property
    def _client(self) -> httpx.AsyncClient:
        """Get the active httpx client."""
        if self._external_client is not None:
            return self._external_client
        if self._internal_client is not None:
            return self._internal_client
        raise RuntimeError(
            "A2AClientWrapper must be used as async context manager or "
            "initialized with an httpx_client"
        )

    async def __aenter__(self) -> "A2AClientWrapper":
        """Enter async context, creating httpx client if needed."""
        if self._external_client is None:
            timeout = httpx.Timeout(self._timeout_seconds, read=None)
            headers = self._get_trace_headers()
            self._internal_client = httpx.AsyncClient(timeout=timeout, headers=headers)
        return self

    def _get_trace_headers(self) -> dict[str, str]:
        """Get trace context headers for propagation.

        Returns empty dict if telemetry is not enabled or installed.
        When telemetry is enabled, injects traceparent and tracestate headers.
        """
        headers: dict[str, str] = {}
        if HAS_TELEMETRY and inject is not None:
            inject(headers)
            if headers:
                logger.debug("Injected trace headers: %s", list(headers.keys()))
        return headers

    def _inject_trace_context_to_client(self) -> None:
        """Inject current trace context into the httpx client headers.

        This updates the client's headers with the current span's trace context,
        allowing distributed tracing across agent-to-agent calls.
        Does nothing if telemetry is not enabled or installed.
        """
        if not HAS_TELEMETRY or inject is None:
            return

        headers: dict[str, str] = {}
        inject(headers)

        if not headers:
            return

        # Update internal client headers if we have one
        if self._internal_client is not None:
            for key, value in headers.items():
                self._internal_client.headers[key] = value
            logger.debug(
                "Updated internal client trace headers: %s", list(headers.keys())
            )

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context, closing internal httpx client if created."""
        if self._internal_client is not None:
            await self._internal_client.aclose()
            self._internal_client = None
        self._agent_card_cache.clear()
        self._a2a_client_cache.clear()

    async def _get_agent_card(self, agent_url: str) -> AgentCard:
        """Get agent card, using cache if available."""
        if agent_url not in self._agent_card_cache:
            try:
                resolver = A2ACardResolver(
                    httpx_client=self._client,
                    base_url=agent_url,
                )
                self._agent_card_cache[agent_url] = await resolver.get_agent_card()
            except httpx.ConnectError as e:
                raise A2AConnectionError(
                    f"Failed to connect to agent at {agent_url}: {e}"
                ) from e
            except httpx.TimeoutException as e:
                raise A2ATimeoutError(
                    f"Timeout connecting to agent at {agent_url}: {e}"
                ) from e
        return self._agent_card_cache[agent_url]

    async def _get_a2a_client(self, agent_url: str) -> A2AClient:
        """Get A2A client for agent, using cache if available."""
        if agent_url not in self._a2a_client_cache:
            agent_card = await self._get_agent_card(agent_url)
            self._a2a_client_cache[agent_url] = A2AClient(
                httpx_client=self._client,
                agent_card=agent_card,
            )
        return self._a2a_client_cache[agent_url]

    async def send_message(
        self,
        agent_url: str,
        message: str,
        context_id: str | None = None,
        task_id: str | None = None,
        collect_raw_chunks: bool = False,
        history: list[dict] | None = None,
        history_seq: int = 0,
        event: dict[str, Any] | None = None,
    ) -> A2AResponse:
        """
        Send a message to an A2A agent and stream the response.

        Args:
            agent_url: Base URL of the agent (e.g., "http://localhost:10008")
            message: The message text to send
            context_id: Optional context ID for multi-turn conversations
            task_id: Optional task ID to continue an existing task
            collect_raw_chunks: If True, collect raw chunk data in response
            history: Optional conversation history for reliability (always sent,
                     not just on context_id miss). Per design doc Agent Communication.
            history_seq: Sequence number for divergence detection. The agent echoes
                        back lastSeenSeq; mismatch indicates cache divergence.
                        Per design doc Agent Communication.
            event: Optional structured event payload for workflow actions.

        Returns:
            A2AResponse containing the agent's response text and metadata

        Raises:
            A2AConnectionError: If connection to agent fails
            A2ATimeoutError: If the call times out
            A2AClientError: For other A2A protocol errors
        """
        try:
            # Inject current trace context into client headers for this request
            self._inject_trace_context_to_client()

            client = await self._get_a2a_client(agent_url)
            return await self._send_streaming_message(
                client=client,
                message=message,
                context_id=context_id,
                task_id=task_id,
                collect_raw_chunks=collect_raw_chunks,
                history=history,
                history_seq=history_seq,
                event=event,
            )
        except (A2AConnectionError, A2ATimeoutError):
            raise
        except httpx.ConnectError as e:
            raise A2AConnectionError(f"Connection failed: {e}") from e
        except httpx.TimeoutException as e:
            raise A2ATimeoutError(f"Request timed out: {e}") from e
        except Exception as e:
            raise A2AClientError(f"A2A call failed: {e}") from e

    async def _send_streaming_message(
        self,
        client: A2AClient,
        message: str,
        context_id: str | None,
        task_id: str | None,
        collect_raw_chunks: bool,
        history: list[dict] | None = None,
        history_seq: int = 0,
        event: dict[str, Any] | None = None,
    ) -> A2AResponse:
        """Internal method to send streaming message and parse response."""
        send_message_payload: dict[str, Any] = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": message}],
                "messageId": uuid4().hex,
            },
        }

        if context_id:
            send_message_payload["message"]["contextId"] = context_id

        if task_id:
            send_message_payload["message"]["taskId"] = task_id

        metadata: dict[str, Any] = {}

        # History injection via metadata (SDK extension point)
        # Per design doc Agent Communication: always send history for reliability
        # Include historySeq for sequence-based divergence detection
        if history is not None:
            metadata["history"] = history
            metadata["historySeq"] = history_seq

        if event is not None:
            # Event metadata drives structured workflow actions (e.g., approvals).
            metadata["event"] = event

        if metadata:
            send_message_payload["message"]["metadata"] = metadata

        streaming_request = SendStreamingMessageRequest(
            id=str(uuid4()),
            params=MessageSendParams(**send_message_payload),
        )

        response_text = ""
        new_context_id = context_id
        new_task_id = task_id
        is_complete = False
        requires_input = False
        last_seen_seq: int | None = None
        raw_chunks: list[dict[str, Any]] = []

        async for chunk in client.send_message_streaming(streaming_request):
            chunk_data = chunk.model_dump(mode="json", exclude_none=True)
            logger.debug("Received chunk: %s", chunk_data)

            if collect_raw_chunks:
                raw_chunks.append(chunk_data)

            if "result" in chunk_data:
                result = chunk_data["result"]
                text_parts, new_context_id, new_task_id, is_complete, requires_input, chunk_last_seen_seq = (
                    self._parse_result_chunk(
                        result, new_context_id, new_task_id, is_complete, requires_input, last_seen_seq
                    )
                )
                response_text += text_parts
                # Update last_seen_seq if we got one from this chunk
                if chunk_last_seen_seq is not None:
                    last_seen_seq = chunk_last_seen_seq

        return A2AResponse(
            text=response_text,
            context_id=new_context_id,
            task_id=new_task_id,
            is_complete=is_complete,
            requires_input=requires_input,
            last_seen_seq=last_seen_seq,
            raw_chunks=raw_chunks if collect_raw_chunks else [],
        )

    def _parse_result_chunk(
        self,
        result: dict[str, Any],
        current_context_id: str | None,
        current_task_id: str | None,
        current_is_complete: bool,
        current_requires_input: bool,
        current_last_seen_seq: int | None,
    ) -> tuple[str, str | None, str | None, bool, bool, int | None]:
        """Parse a result chunk and extract text and metadata.

        Returns:
            Tuple of (text_parts, context_id, task_id, is_complete, requires_input, last_seen_seq)
        """
        text_parts = ""
        new_context_id = current_context_id
        new_task_id = current_task_id
        is_complete = current_is_complete
        requires_input = current_requires_input
        last_seen_seq = current_last_seen_seq

        # Extract IDs
        if "contextId" in result:
            new_context_id = result["contextId"]
        if "taskId" in result:
            new_task_id = result["taskId"]
        if "id" in result and result.get("kind") == "task":
            new_task_id = result["id"]

        # Extract lastSeenSeq from metadata (per design doc Agent Communication)
        # Agents echo back lastSeenSeq for divergence tracking
        if "metadata" in result and isinstance(result["metadata"], dict):
            seq_value = result["metadata"].get("lastSeenSeq")
            if seq_value is not None and isinstance(seq_value, int):
                last_seen_seq = seq_value

        # Check status for completion state
        if "status" in result:
            status = result["status"]
            if isinstance(status, dict):
                state = status.get("state", "")
                is_complete = state == "completed"
                requires_input = state == "input_required"
                # Extract text from status message
                if "message" in status and "parts" in status["message"]:
                    for part in status["message"]["parts"]:
                        if "text" in part:
                            text_parts += part["text"]

        # Handle artifact with parts
        if "artifact" in result and "parts" in result["artifact"]:
            for part in result["artifact"]["parts"]:
                if "text" in part:
                    text_parts += part["text"]

        # Handle message with parts
        if "message" in result and "parts" in result["message"]:
            for part in result["message"]["parts"]:
                if "text" in part:
                    text_parts += part["text"]

        return text_parts, new_context_id, new_task_id, is_complete, requires_input, last_seen_seq

    def clear_cache(self) -> None:
        """Clear agent card and client caches."""
        self._agent_card_cache.clear()
        self._a2a_client_cache.clear()

    async def health_check(self, agent_url: str) -> bool:
        """
        Check if an agent is reachable by fetching its agent card.

        Args:
            agent_url: Base URL of the agent

        Returns:
            True if agent is reachable, False otherwise
        """
        try:
            await self._get_agent_card(agent_url)
            return True
        except (A2AConnectionError, A2ATimeoutError):
            return False
