"""
ClarifierConversation: Overflow-aware conversation model for clarifier dialog.

Per design doc Storage Sizing & Sharding Strategy and Conversation History Management sections:
- clarifier_conversation stores last 50 messages + rolling summary in WorkflowState
- When message count reaches SUMMARY_THRESHOLD (40), summarize oldest messages
- Keep last 20 messages, summarize the rest
- Persist trimmed messages to chat_messages container for audit
- Track overflow_message_count for resumption

This extends AgentConversation with size limits and overflow support.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from src.orchestrator.models.conversation import (
    AgentConversation,
    ConversationMessage,
)

if TYPE_CHECKING:
    from src.orchestrator.storage.chat_messages import ChatMessageStoreProtocol

logger = logging.getLogger(__name__)


# Size limits per design doc Conversation History Management section
MAX_MESSAGES_IN_STATE = 50  # Maximum messages to keep in WorkflowState
SUMMARY_THRESHOLD = 40  # Trigger summarization when reaching this count
KEEP_RECENT_COUNT = 20  # Keep this many recent messages after trimming


@dataclass
class ClarifierConversation:
    """
    Manages conversation with Clarifier agent with size limits and overflow.

    Per design doc Storage Sizing & Sharding Strategy:
    - Target size: < 100KB for conversation data
    - Max messages in WorkflowState: 50
    - Older messages are summarized and persisted to overflow container

    Attributes:
        agent_name: Always "clarifier" for this conversation
        messages: Last N messages (up to MAX_MESSAGES_IN_STATE)
        current_seq: Sequence number for divergence detection
        summary: Rolling summary of older messages (updated on trim)
        overflow_message_count: Count of messages persisted to chat_messages
    """

    agent_name: str = "clarifier"
    messages: list[ConversationMessage] = field(default_factory=list)
    current_seq: int = 0
    summary: str | None = None
    overflow_message_count: int = 0

    # Callback for persisting overflow messages (set during handler setup)
    _overflow_callback: Callable[[list[ConversationMessage]], None] | None = field(
        default=None, repr=False
    )
    # Callback for summarizing messages (LLM call)
    _summarize_callback: Callable[[list[ConversationMessage], str | None], str] | None = field(
        default=None, repr=False
    )

    @property
    def next_seq(self) -> int:
        """Get next sequence number (increments with each message we send)."""
        return self.current_seq + 1

    @property
    def message_count(self) -> int:
        """Get the number of messages in the conversation."""
        return len(self.messages)

    @property
    def total_message_count(self) -> int:
        """Get total messages including overflow."""
        return len(self.messages) + self.overflow_message_count

    def set_overflow_callback(
        self,
        callback: Callable[[list[ConversationMessage]], None],
    ) -> None:
        """Set callback for persisting overflow messages."""
        self._overflow_callback = callback

    def set_summarize_callback(
        self,
        callback: Callable[[list[ConversationMessage], str | None], str],
    ) -> None:
        """Set callback for summarizing messages."""
        self._summarize_callback = callback

    def append_turn(self, user_content: str, assistant_content: str) -> None:
        """
        Append a user/assistant turn to the conversation.

        Triggers summarize_and_trim if threshold reached.

        Args:
            user_content: The user's message content
            assistant_content: The assistant's response content
        """
        now = datetime.now(timezone.utc)

        # Increment for the user message
        self.current_seq += 1
        self.messages.append(
            ConversationMessage(
                message_id=f"msg_{uuid.uuid4().hex[:12]}",
                role="user",
                content=user_content,
                timestamp=now,
                metadata={"seq": self.current_seq},
            )
        )

        # Increment for the assistant message
        self.current_seq += 1
        self.messages.append(
            ConversationMessage(
                message_id=f"msg_{uuid.uuid4().hex[:12]}",
                role="assistant",
                content=assistant_content,
                timestamp=now,
                metadata={"seq": self.current_seq},
            )
        )

        # Check if we need to summarize and trim
        if len(self.messages) >= SUMMARY_THRESHOLD:
            self._summarize_and_trim()

    def append_message(
        self,
        role: str,
        content: str,
        message_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        """
        Append a single message to the conversation.

        For finer control than append_turn(). Triggers summarize_and_trim
        if threshold reached.

        Args:
            role: "user" or "assistant"
            content: Message content
            message_id: Optional message ID (generated if not provided)
            timestamp: Optional timestamp (current time if not provided)
        """
        if message_id is None:
            message_id = f"msg_{uuid.uuid4().hex[:12]}"
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        self.current_seq += 1
        self.messages.append(
            ConversationMessage(
                message_id=message_id,
                role=role,  # type: ignore[arg-type]
                content=content,
                timestamp=timestamp,
                metadata={"seq": self.current_seq},
            )
        )

        # Check if we need to summarize and trim
        if len(self.messages) >= SUMMARY_THRESHOLD:
            self._summarize_and_trim()

    def _summarize_and_trim(self) -> None:
        """
        Summarize oldest messages and move to overflow if needed.

        Per design doc Conversation History Management:
        - Keep last KEEP_RECENT_COUNT messages
        - Summarize the rest
        - Update rolling summary (LLM call if callback set)
        - Persist to overflow container if callback set
        - Increment overflow_message_count
        """
        if len(self.messages) < SUMMARY_THRESHOLD:
            return  # Nothing to trim

        # Messages to summarize (oldest ones)
        to_summarize = self.messages[:-KEEP_RECENT_COUNT]
        # Messages to keep (most recent)
        self.messages = self.messages[-KEEP_RECENT_COUNT:]

        logger.debug(
            f"Summarizing {len(to_summarize)} messages, keeping {len(self.messages)} recent"
        )

        # Update rolling summary via callback or default implementation
        if self._summarize_callback is not None:
            self.summary = self._summarize_callback(to_summarize, self.summary)
        else:
            # Default: basic concatenation summary
            self.summary = self._default_summarize(to_summarize, self.summary)

        # Persist to overflow container via callback
        if self._overflow_callback is not None:
            try:
                self._overflow_callback(to_summarize)
                logger.debug(f"Persisted {len(to_summarize)} messages to overflow")
            except Exception as e:
                logger.error(f"Error persisting overflow messages: {e}")
                # Continue even if persistence fails - summary is updated

        # Track overflow count
        self.overflow_message_count += len(to_summarize)

    def _default_summarize(
        self,
        messages: list[ConversationMessage],
        existing_summary: str | None,
    ) -> str:
        """
        Default summarization: simple concatenation with truncation.

        This is a placeholder; real implementation would use LLM.
        For now, extracts key points and combines with existing summary.
        """
        # Build a simple summary from message contents
        new_content = []
        for msg in messages:
            prefix = "User" if msg.role == "user" else "Assistant"
            # Truncate long messages
            content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
            new_content.append(f"[{prefix}] {content}")

        new_summary = "\n".join(new_content[-10:])  # Keep last 10 entries max

        if existing_summary:
            # Combine with existing summary, keeping it reasonable
            combined = f"Earlier: {existing_summary[:500]}...\n\nRecent: {new_summary}"
            return combined[:1000]  # Cap total summary length
        return new_summary

    def to_history_list(self) -> list[dict[str, Any]]:
        """
        Return list of dicts for A2A metadata history injection.

        Per design doc: when sending to clarifier, include:
        1. Summary (if exists) as first message with role='system'
        2. Recent messages in order

        Returns:
            List of serialized messages with camelCase keys
        """
        result: list[dict[str, Any]] = []

        # Include summary as a system message if present
        if self.summary:
            result.append({
                "messageId": "summary",
                "role": "system",
                "content": f"[Previous conversation summary]\n{self.summary}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": {"type": "summary", "overflowCount": self.overflow_message_count},
            })

        # Add recent messages
        result.extend([msg.to_dict() for msg in self.messages])
        return result

    def get_context_for_agent(self) -> dict[str, Any]:
        """
        Get conversation context for agent calls.

        Returns a dict with summary, recent_messages, and metadata
        suitable for injection into agent requests.
        """
        return {
            "summary": self.summary,
            "recent_messages": self.to_history_list(),
            "total_messages": self.total_message_count,
            "overflow_count": self.overflow_message_count,
            "current_seq": self.current_seq,
        }

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize for storage in WorkflowState.

        Only serializes messages within size limit.
        """
        return {
            "agent_name": self.agent_name,
            "messages": [msg.to_dict() for msg in self.messages],
            "current_seq": self.current_seq,
            "summary": self.summary,
            "overflow_message_count": self.overflow_message_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClarifierConversation:
        """
        Deserialize from WorkflowState storage.

        Args:
            data: Dictionary from to_dict()

        Returns:
            ClarifierConversation instance
        """
        messages: list[ConversationMessage] = []
        for msg_data in data.get("messages", []):
            try:
                messages.append(ConversationMessage.from_dict(msg_data))
            except (KeyError, ValueError) as e:
                logger.warning(f"Skipping malformed message: {e}")

        return cls(
            agent_name=data.get("agent_name", "clarifier"),
            messages=messages,
            current_seq=data.get("current_seq", 0),
            summary=data.get("summary"),
            overflow_message_count=data.get("overflow_message_count", 0),
        )

    @classmethod
    def from_agent_conversation(
        cls,
        agent_conv: AgentConversation,
        summary: str | None = None,
        overflow_message_count: int = 0,
    ) -> ClarifierConversation:
        """
        Create ClarifierConversation from existing AgentConversation.

        Used for migration from legacy format.

        Args:
            agent_conv: Existing AgentConversation to convert
            summary: Optional existing summary
            overflow_message_count: Optional existing overflow count

        Returns:
            ClarifierConversation with same messages
        """
        return cls(
            agent_name=agent_conv.agent_name,
            messages=agent_conv.messages.copy(),
            current_seq=agent_conv.current_seq,
            summary=summary,
            overflow_message_count=overflow_message_count,
        )

    def clear(self) -> None:
        """
        Clear conversation for start_new.

        Per design doc start_new semantics, this clears:
        - messages
        - summary
        - overflow_message_count
        - Resets current_seq to 0
        """
        self.messages = []
        self.summary = None
        self.overflow_message_count = 0
        self.current_seq = 0


async def create_overflow_callback(
    session_id: str,
    chat_message_store: ChatMessageStoreProtocol,
) -> Callable[[list[ConversationMessage]], None]:
    """
    Create a callback function for persisting overflow messages.

    This is called by ClarifierConversation._summarize_and_trim()
    to persist trimmed messages to the chat_messages container.

    Args:
        session_id: The session ID for partitioning
        chat_message_store: The chat message store instance

    Returns:
        Callback function that persists messages to overflow
    """
    async def _persist_overflow(messages: list[ConversationMessage]) -> None:
        """Persist messages to overflow container."""
        for msg in messages:
            await chat_message_store.append_message(
                session_id=session_id,
                message_id=msg.message_id,
                role=msg.role,
                content=msg.content,
            )

    # Return a sync wrapper that runs the async function
    # Note: This is a simplification; in practice, you might want to
    # use asyncio.create_task or a queue for async persistence
    def sync_wrapper(messages: list[ConversationMessage]) -> None:
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_persist_overflow(messages))
        except RuntimeError:
            # No running loop - run synchronously
            asyncio.run(_persist_overflow(messages))

    return sync_wrapper


def summarize_messages(
    messages: list[ConversationMessage],
    existing_summary: str | None = None,
) -> str:
    """
    Summarize a list of messages for the rolling summary.

    This is a placeholder implementation. In production, this would
    call an LLM to generate a concise summary of the conversation.

    Args:
        messages: Messages to summarize
        existing_summary: Existing summary to incorporate

    Returns:
        Updated summary string
    """
    # Build a simple summary from message contents
    # Real implementation would use LLM for intelligent summarization
    summaries = []

    if existing_summary:
        summaries.append(f"Previous: {existing_summary[:300]}")

    for msg in messages[-5:]:  # Summarize last 5 messages
        prefix = "User" if msg.role == "user" else "Assistant"
        content = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
        summaries.append(f"{prefix}: {content}")

    return " | ".join(summaries)[:800]  # Cap at 800 chars
