"""Authorization module for the orchestrator.

This module provides authorization helpers for workflow mutations,
itinerary reads, and booking reads. It supports both MVP mode (no auth
required) and production mode (user authentication with share tokens).

Components:
    SharePermission: Enum for share token permission levels
    ShareToken: Data class for share token storage
    AuthorizationResult: Result of an authorization check
    authorize_workflow_mutation: Check authorization for workflow mutations
    authorize_itinerary_read: Check authorization for itinerary reads
    authorize_booking_read: Check authorization for booking reads
    filter_itinerary_for_share: Filter itinerary data by permission level

    InMemoryShareTokenStore: In-memory share token store for testing
    ShareTokenStoreProtocol: Protocol for share token stores
"""

from src.orchestrator.auth.authorization import (
    AuthenticatedUser,
    AuthorizationResult,
    SharePermission,
    ShareToken,
    authorize_booking_read,
    authorize_itinerary_read,
    authorize_workflow_mutation,
    filter_itinerary_for_share,
)
from src.orchestrator.auth.share_tokens import (
    InMemoryShareTokenStore,
    ShareTokenStoreProtocol,
)

__all__ = [
    # Enums and dataclasses
    "SharePermission",
    "ShareToken",
    "AuthorizationResult",
    "AuthenticatedUser",
    # Authorization functions
    "authorize_workflow_mutation",
    "authorize_itinerary_read",
    "authorize_booking_read",
    "filter_itinerary_for_share",
    # Store protocol and implementations
    "ShareTokenStoreProtocol",
    "InMemoryShareTokenStore",
]
