"""Conversation data models for agent communication and history tracking.

Per design doc Agent Communication section:
- ConversationMessage represents a single message in agent conversation history
- AgentConversation tracks full conversation with a downstream agent
- Used for multi-turn conversations, context recovery, and divergence detection
- Rich format with message_id, timestamp, metadata for debugging and auditing
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


@dataclass
class ConversationMessage:
    """
    A single message in agent conversation history.

    Used for:
    - Multi-turn conversations with downstream agents (especially Clarifier)
    - Context recovery when agent's cached thread is invalid/expired
    - Divergence detection (via sequence number comparison)

    Attributes:
        message_id: UUID, unique per message (for ordering/deduplication)
        role: Who sent the message - "user" or "assistant"
        content: Message text content
        timestamp: When message was created (ISO 8601)
        metadata: Optional structured data, tool calls, sequence numbers, etc.
    """

    message_id: str
    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for A2A request payload.

        Returns dictionary with camelCase keys per A2A spec:
        - messageId (string)
        - role (string)
        - content (string)
        - timestamp (ISO 8601 string)
        - metadata (dict or null)
        """
        return {
            "messageId": self.message_id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationMessage":
        """Deserialize from A2A request payload.

        Accepts camelCase keys (per A2A spec):
        - messageId (string)
        - role (string)
        - content (string)
        - timestamp (ISO 8601 string)
        - metadata (dict or null, optional)

        Args:
            data: Dictionary with camelCase keys

        Returns:
            ConversationMessage instance
        """
        return cls(
            message_id=data["messageId"],
            role=data["role"],
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            metadata=data.get("metadata"),
        )


@dataclass
class AgentConversation:
    """
    Full conversation history with a downstream agent.

    Stored in WorkflowState for each agent that requires multi-turn support.
    Sent with every A2A request for reliability (client history is authoritative).

    Per design doc Agent Communication section:
    - Tracks ordered conversation history with a specific agent
    - Provides append_turn() helper for adding user/assistant message pairs
    - Provides to_history_list() for A2A metadata injection
    - Manages sequence numbers for divergence detection

    Attributes:
        agent_name: Identifier for the agent (e.g., "clarifier", "booking")
        messages: Ordered list of ConversationMessage objects
        current_seq: Current sequence number for divergence detection
    """

    agent_name: str
    messages: list[ConversationMessage] = field(default_factory=list)
    current_seq: int = 0

    @property
    def next_seq(self) -> int:
        """Get next sequence number (increments with each message we send)."""
        return self.current_seq + 1

    @property
    def message_count(self) -> int:
        """Get the number of messages in the conversation."""
        return len(self.messages)

    def append_turn(self, user_content: str, assistant_content: str) -> None:
        """Append a user/assistant turn to the conversation and increment sequence.

        Per design doc: each turn consists of a user message followed by an
        assistant response. Both messages get embedded sequence numbers in
        their metadata for divergence detection.

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

    def to_history_list(self) -> list[dict[str, Any]]:
        """Return list of dicts for A2A metadata history injection.

        Serializes all messages using to_dict() for inclusion in the
        A2A request metadata. The format is suitable for the 'history'
        key in message.metadata.

        Returns:
            List of serialized messages with camelCase keys
        """
        return [msg.to_dict() for msg in self.messages]
