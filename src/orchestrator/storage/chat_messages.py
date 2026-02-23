"""
Chat messages storage for Cosmos DB.

This module implements the ChatMessageStore which persists overflow
conversation history when WorkflowState exceeds 50 messages.

Key features:
- Partitioned by session_id for efficient lookups
- 7-day TTL matching WorkflowState TTL
- Stores individual messages with role, content, and timestamp
- Supports pagination for large conversation histories

Per design doc:
- Container: chat_messages
- Partition key: /session_id
- TTL: 604800 seconds (7 days)
- Purpose: Overflow chat history when WorkflowState exceeds 50 messages
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

# Import azure.cosmos only at type-checking time or when needed at runtime
if TYPE_CHECKING:
    from azure.cosmos.aio import ContainerProxy

logger = logging.getLogger(__name__)

# TTL for chat messages: 7 days in seconds (matches WorkflowState)
CHAT_MESSAGES_TTL = 7 * 24 * 60 * 60  # 604800 seconds


@dataclass
class ChatMessage:
    """
    A single chat message stored in the chat_messages container.

    This represents a message that has overflowed from WorkflowState
    when the conversation exceeds 50 messages.

    Attributes:
        session_id: The session this message belongs to (partition key)
        message_id: Unique identifier for the message within the session
        role: The role of the message sender ('user' or 'assistant')
        content: The text content of the message
        timestamp: When the message was created (UTC)
    """

    session_id: str
    message_id: str
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for Cosmos DB storage."""
        # Document ID combines message_id and session_id for uniqueness
        doc_id = f"{self.message_id}_{self.session_id}"
        return {
            "id": doc_id,  # Cosmos DB document ID
            "session_id": self.session_id,  # Partition key
            "message_id": self.message_id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "ttl": CHAT_MESSAGES_TTL,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatMessage:
        """Create from dictionary retrieved from Cosmos DB."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        else:
            timestamp = datetime.now(timezone.utc)

        return cls(
            session_id=data.get("session_id", ""),
            message_id=data.get("message_id", ""),
            role=data.get("role", "user"),
            content=data.get("content", ""),
            timestamp=timestamp,
        )


@runtime_checkable
class ChatMessageStoreProtocol(Protocol):
    """
    Protocol defining the interface for chat message storage.

    This protocol allows swapping between Cosmos DB and in-memory
    implementations for production vs testing.
    """

    async def get_messages(
        self, session_id: str, limit: int | None = None, offset: int = 0
    ) -> list[ChatMessage]:
        """
        Retrieve messages for a session.

        Args:
            session_id: The session identifier (partition key)
            limit: Maximum number of messages to return (None for all)
            offset: Number of messages to skip (for pagination)

        Returns:
            List of ChatMessage objects ordered by timestamp
        """
        ...

    async def append_message(
        self, session_id: str, message_id: str, role: str, content: str
    ) -> ChatMessage:
        """
        Add a new message to the session.

        Args:
            session_id: The session identifier (partition key)
            message_id: Unique identifier for the message
            role: The role ('user' or 'assistant')
            content: The message content

        Returns:
            The created ChatMessage
        """
        ...

    async def purge_messages(self, session_id: str) -> int:
        """
        Delete all messages for a session.

        Used for cleanup when a session is deleted or when
        conversation history is no longer needed.

        Args:
            session_id: The session identifier

        Returns:
            Number of messages deleted
        """
        ...


class ChatMessageStore:
    """
    Cosmos DB implementation of chat message storage.

    Uses the chat_messages container partitioned by session_id.
    Provides storage for overflow conversation history.
    """

    def __init__(self, container: ContainerProxy) -> None:
        """
        Initialize the store with a Cosmos container client.

        Args:
            container: Async Cosmos container client for chat_messages
        """
        self._container = container

    async def get_messages(
        self, session_id: str, limit: int | None = None, offset: int = 0
    ) -> list[ChatMessage]:
        """
        Retrieve messages for a session.

        Args:
            session_id: The session identifier (partition key)
            limit: Maximum number of messages to return (None for all)
            offset: Number of messages to skip (for pagination)

        Returns:
            List of ChatMessage objects ordered by timestamp
        """
        # Build query with ordering by timestamp
        query = "SELECT * FROM c WHERE c.session_id = @session_id ORDER BY c.timestamp ASC"
        parameters = [{"name": "@session_id", "value": session_id}]

        # Apply OFFSET and LIMIT if specified
        if offset > 0:
            query += f" OFFSET {offset}"
        if limit is not None:
            if offset == 0:
                query += " OFFSET 0"
            query += f" LIMIT {limit}"

        try:
            items = self._container.query_items(
                query=query,
                parameters=parameters,
                partition_key=session_id,
            )

            messages = []
            async for item in items:
                messages.append(ChatMessage.from_dict(item))

            logger.debug(
                f"Retrieved {len(messages)} messages for session {session_id}"
            )
            return messages

        except Exception as e:
            logger.error(f"Error retrieving messages for session {session_id}: {e}")
            raise

    async def append_message(
        self, session_id: str, message_id: str, role: str, content: str
    ) -> ChatMessage:
        """
        Add a new message to the session.

        Args:
            session_id: The session identifier (partition key)
            message_id: Unique identifier for the message
            role: The role ('user' or 'assistant')
            content: The message content

        Returns:
            The created ChatMessage
        """
        message = ChatMessage(
            session_id=session_id,
            message_id=message_id,
            role=role,
            content=content,
        )
        doc = message.to_dict()

        try:
            response = await self._container.create_item(body=doc)
            logger.debug(
                f"Created message {message_id} for session {session_id} (role={role})"
            )
            return ChatMessage.from_dict(response)
        except Exception as e:
            logger.error(f"Error creating message for session {session_id}: {e}")
            raise

    async def purge_messages(self, session_id: str) -> int:
        """
        Delete all messages for a session.

        Args:
            session_id: The session identifier

        Returns:
            Number of messages deleted
        """
        # First, query all message IDs for this session
        query = "SELECT c.id FROM c WHERE c.session_id = @session_id"
        parameters = [{"name": "@session_id", "value": session_id}]

        try:
            items = self._container.query_items(
                query=query,
                parameters=parameters,
                partition_key=session_id,
            )

            deleted_count = 0
            async for item in items:
                doc_id = item["id"]
                try:
                    await self._container.delete_item(
                        item=doc_id,
                        partition_key=session_id,
                    )
                    deleted_count += 1
                except Exception as e:
                    # Log but continue - best effort deletion
                    error_code = getattr(e, "status_code", None)
                    if error_code != 404:
                        logger.warning(f"Error deleting message {doc_id}: {e}")

            logger.debug(
                f"Purged {deleted_count} messages for session {session_id}"
            )
            return deleted_count

        except Exception as e:
            logger.error(f"Error purging messages for session {session_id}: {e}")
            raise


class InMemoryChatMessageStore:
    """
    In-memory implementation of chat message storage for testing.

    Implements the same interface as ChatMessageStore but stores
    data in memory. Useful for unit tests and local development.
    """

    def __init__(self) -> None:
        """Initialize empty in-memory store."""
        # Store messages per session: {session_id: [ChatMessage dicts]}
        self._messages: dict[str, list[dict[str, Any]]] = {}

    async def get_messages(
        self, session_id: str, limit: int | None = None, offset: int = 0
    ) -> list[ChatMessage]:
        """Retrieve messages for a session."""
        if session_id not in self._messages:
            return []

        # Get messages sorted by timestamp
        session_messages = sorted(
            self._messages[session_id],
            key=lambda x: x.get("timestamp", ""),
        )

        # Apply offset
        session_messages = session_messages[offset:]

        # Apply limit
        if limit is not None:
            session_messages = session_messages[:limit]

        return [ChatMessage.from_dict(m) for m in session_messages]

    async def append_message(
        self, session_id: str, message_id: str, role: str, content: str
    ) -> ChatMessage:
        """Add a new message to the session."""
        message = ChatMessage(
            session_id=session_id,
            message_id=message_id,
            role=role,
            content=content,
        )
        doc = message.to_dict()

        if session_id not in self._messages:
            self._messages[session_id] = []

        self._messages[session_id].append(doc)
        return message

    async def purge_messages(self, session_id: str) -> int:
        """Delete all messages for a session."""
        if session_id not in self._messages:
            return 0

        count = len(self._messages[session_id])
        del self._messages[session_id]
        return count

    def clear(self) -> None:
        """Clear all messages (for test cleanup)."""
        self._messages.clear()

    def get_message_count(self, session_id: str) -> int:
        """Get the number of messages for a session (test helper)."""
        if session_id not in self._messages:
            return 0
        return len(self._messages[session_id])
