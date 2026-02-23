"""Session storage abstraction and implementations."""
from abc import ABC, abstractmethod
from typing import Any


class SessionStore(ABC):
    """Abstract base class for session storage."""

    @abstractmethod
    async def save(self, session_id: str, data: dict[str, Any]) -> None:
        """Save session data by session_id.

        Args:
            session_id: Unique identifier for the session.
            data: Session data to store.
        """
        pass

    @abstractmethod
    async def load(self, session_id: str) -> dict[str, Any] | None:
        """Load session data by session_id.

        Args:
            session_id: Unique identifier for the session.

        Returns:
            Session data if found, None otherwise.
        """
        pass

    @abstractmethod
    async def delete(self, session_id: str) -> bool:
        """Delete session data by session_id.

        Args:
            session_id: Unique identifier for the session.

        Returns:
            True if session was deleted, False if not found.
        """
        pass


class InMemorySessionStore(SessionStore):
    """In-memory implementation of SessionStore for development/testing."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}

    async def save(self, session_id: str, data: dict[str, Any]) -> None:
        """Save session data by session_id."""
        self._sessions[session_id] = data

    async def load(self, session_id: str) -> dict[str, Any] | None:
        """Load session data by session_id."""
        return self._sessions.get(session_id)

    async def delete(self, session_id: str) -> bool:
        """Delete session data by session_id."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False
