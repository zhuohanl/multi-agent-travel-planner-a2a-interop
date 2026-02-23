"""Share token store interfaces and implementations.

This module provides the protocol for share token storage and an
in-memory implementation for development and testing.

In production, a Cosmos DB-backed implementation would be used
to persist share tokens with automatic TTL expiration.
"""

from __future__ import annotations

from typing import Protocol

from src.orchestrator.auth.authorization import ShareToken


# =============================================================================
# Store Protocol
# =============================================================================


class ShareTokenStoreProtocol(Protocol):
    """Protocol for share token stores.

    Implementations must provide these methods for storing and retrieving
    share tokens. The in-memory implementation is suitable for testing;
    production would use Cosmos DB with TTL.
    """

    async def save(self, token: ShareToken) -> None:
        """Save a share token.

        Args:
            token: The share token to save.
        """
        ...

    async def get_by_token(self, token: str) -> ShareToken | None:
        """Get a share token by its token string.

        Args:
            token: The token string to look up.

        Returns:
            The ShareToken if found, None otherwise.
        """
        ...

    async def get_by_itinerary(self, itinerary_id: str) -> list[ShareToken]:
        """Get all share tokens for an itinerary.

        Args:
            itinerary_id: The itinerary ID to look up.

        Returns:
            List of ShareTokens for this itinerary.
        """
        ...

    async def revoke(self, token: str) -> bool:
        """Revoke a share token.

        Args:
            token: The token string to revoke.

        Returns:
            True if the token was found and revoked, False if not found.
        """
        ...


# =============================================================================
# In-Memory Implementation
# =============================================================================


class InMemoryShareTokenStore:
    """In-memory share token store for development and testing.

    Stores share tokens in memory with no persistence. Suitable for
    unit tests and local development. Not suitable for production
    as data is lost on process restart.
    """

    def __init__(self) -> None:
        """Initialize an empty in-memory store."""
        self._tokens: dict[str, ShareToken] = {}  # token -> ShareToken
        self._by_itinerary: dict[str, list[str]] = {}  # itinerary_id -> [token, ...]

    async def save(self, token: ShareToken) -> None:
        """Save a share token.

        Args:
            token: The share token to save.
        """
        self._tokens[token.token] = token

        # Update itinerary index
        if token.itinerary_id not in self._by_itinerary:
            self._by_itinerary[token.itinerary_id] = []
        if token.token not in self._by_itinerary[token.itinerary_id]:
            self._by_itinerary[token.itinerary_id].append(token.token)

    async def get_by_token(self, token: str) -> ShareToken | None:
        """Get a share token by its token string.

        Args:
            token: The token string to look up.

        Returns:
            The ShareToken if found, None otherwise.
        """
        return self._tokens.get(token)

    async def get_by_itinerary(self, itinerary_id: str) -> list[ShareToken]:
        """Get all share tokens for an itinerary.

        Args:
            itinerary_id: The itinerary ID to look up.

        Returns:
            List of ShareTokens for this itinerary.
        """
        token_strings = self._by_itinerary.get(itinerary_id, [])
        return [
            self._tokens[t]
            for t in token_strings
            if t in self._tokens
        ]

    async def revoke(self, token: str) -> bool:
        """Revoke a share token.

        Args:
            token: The token string to revoke.

        Returns:
            True if the token was found and revoked, False if not found.
        """
        share_token = self._tokens.get(token)
        if share_token:
            share_token.revoked = True
            return True
        return False

    def clear(self) -> None:
        """Clear all tokens from the store.

        Useful for testing to reset state between tests.
        """
        self._tokens.clear()
        self._by_itinerary.clear()

    def count(self) -> int:
        """Return the number of tokens in the store.

        Returns:
            The count of stored tokens.
        """
        return len(self._tokens)
