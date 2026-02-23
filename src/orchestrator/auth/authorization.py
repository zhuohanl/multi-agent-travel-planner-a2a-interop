"""Authorization helpers for workflow, itinerary, and booking access.

This module provides authorization checks that support both MVP mode (no auth
required, IDs as bearer tokens) and production mode (authenticated users with
explicit share tokens).

MVP Mode (default):
    - No authentication required
    - Anyone with the ID (session_id, itinerary_id, booking_id) can access
    - Long UUIDs provide sufficient entropy against guessing

Production Mode (future):
    - Requires authenticated user
    - IDs are bound to user_id
    - Share tokens provide explicit sharing with permission levels
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.orchestrator.models.itinerary import Itinerary
    from src.orchestrator.models.workflow_state import WorkflowState


# =============================================================================
# Enums and Data Classes
# =============================================================================


class SharePermission(Enum):
    """Permission levels for share tokens.

    Defines what data is visible when sharing an itinerary.
    """

    VIEW_SUMMARY = "view_summary"  # Trip dates, destinations, activity names only
    VIEW_FULL = "view_full"  # Complete plan with prices (read-only)
    # BOOK = "book"  # Future: allow booking actions


@dataclass
class AuthenticatedUser:
    """Represents an authenticated user.

    In MVP mode, user will be None. In production mode, this contains
    the authenticated user's identity from OAuth/Azure AD B2C.
    """

    id: str  # User ID from authentication provider
    email: str | None = None
    display_name: str | None = None


@dataclass
class ShareToken:
    """A share token for itinerary access.

    Share tokens allow sharing itineraries with others without giving
    them full access. They are time-limited and can be revoked.
    """

    token: str  # Cryptographically random, URL-safe
    itinerary_id: str  # What's being shared
    created_by: str  # user_id of owner
    created_at: datetime
    expires_at: datetime  # Time-limited (e.g., 7 days)
    permission: SharePermission  # Single permission level
    revoked: bool = False

    @classmethod
    def create(
        cls,
        itinerary_id: str,
        created_by: str,
        permission: SharePermission = SharePermission.VIEW_SUMMARY,
        expires_in_days: int = 7,
    ) -> ShareToken:
        """Create a new share token.

        Args:
            itinerary_id: The itinerary to share.
            created_by: The user_id of the owner.
            permission: What level of access to grant.
            expires_in_days: How long the token is valid.

        Returns:
            A new ShareToken instance.
        """
        now = datetime.utcnow()
        return cls(
            token=secrets.token_urlsafe(32),
            itinerary_id=itinerary_id,
            created_by=created_by,
            created_at=now,
            expires_at=now + timedelta(days=expires_in_days),
            permission=permission,
        )

    def is_valid(self) -> bool:
        """Check if the token is valid (not expired and not revoked)."""
        return not self.revoked and datetime.utcnow() < self.expires_at


@dataclass
class AuthorizationResult:
    """Result of an authorization check.

    Provides both the decision (allowed/denied) and the reason for
    debugging and audit logging.
    """

    allowed: bool
    reason: str  # Why access was allowed/denied
    permission: SharePermission | None = None  # Permission level if via share token

    @classmethod
    def allow(cls, reason: str, permission: SharePermission | None = None) -> AuthorizationResult:
        """Create an allowed result."""
        return cls(allowed=True, reason=reason, permission=permission)

    @classmethod
    def deny(cls, reason: str) -> AuthorizationResult:
        """Create a denied result."""
        return cls(allowed=False, reason=reason)


# =============================================================================
# Authorization Functions
# =============================================================================


def authorize_workflow_mutation(
    state: WorkflowState | None,
    user: AuthenticatedUser | None,
) -> AuthorizationResult:
    """Authorize workflow mutations (approve, modify, book, cancel).

    REQUIRES active WorkflowState - cannot mutate expired workflows.
    In MVP mode, allows access when user is None.

    Args:
        state: The workflow state to check, or None if not found/expired.
        user: The authenticated user, or None in MVP mode.

    Returns:
        AuthorizationResult with allowed/denied and reason.
    """
    if not state:
        return AuthorizationResult.deny("workflow_expired")

    # MVP mode: Allow if no auth required
    if user is None:
        return AuthorizationResult.allow("mvp_no_auth")

    # Production mode: Check owner
    # Note: user_id field would be added to WorkflowState in production
    state_user_id = getattr(state, "user_id", None)
    if state_user_id and state_user_id == user.id:
        return AuthorizationResult.allow("owner")

    # In production mode with auth enabled but user doesn't match owner
    return AuthorizationResult.deny("unauthorized")


def authorize_itinerary_read(
    itinerary: Any | None,  # Use Any to avoid circular import with Itinerary
    user: AuthenticatedUser | None,
    share_token: ShareToken | None,
) -> AuthorizationResult:
    """Authorize itinerary read access.

    Does NOT require WorkflowState - works after expiry via itinerary doc.
    In MVP mode, allows access when user is None and no share_token.

    Args:
        itinerary: The itinerary to check, or None if not found.
        user: The authenticated user, or None in MVP mode.
        share_token: A share token for access, or None.

    Returns:
        AuthorizationResult with allowed/denied, reason, and permission level.
    """
    if not itinerary:
        return AuthorizationResult.deny("not_found")

    # Owner access (authenticated)
    if user:
        itinerary_user_id = getattr(itinerary, "user_id", None)
        if itinerary_user_id and itinerary_user_id == user.id:
            return AuthorizationResult.allow("owner", SharePermission.VIEW_FULL)

    # Share token access
    if share_token:
        # Verify token is for this itinerary
        itinerary_id = getattr(itinerary, "itinerary_id", None)
        if itinerary_id and share_token.itinerary_id == itinerary_id:
            if share_token.is_valid():
                return AuthorizationResult.allow("share_token", share_token.permission)
            else:
                return AuthorizationResult.deny("share_token_expired_or_revoked")

    # MVP mode: Allow if no auth and no share token
    if user is None and share_token is None:
        return AuthorizationResult.allow("mvp_no_auth", SharePermission.VIEW_FULL)

    return AuthorizationResult.deny("unauthorized")


def authorize_booking_read(
    booking: Any | None,  # Use Any to avoid circular import with Booking
    user: AuthenticatedUser | None,
) -> AuthorizationResult:
    """Authorize booking read access.

    Does NOT require WorkflowState - works after expiry via booking doc.
    In MVP mode, allows access when user is None.

    Bookings are not shareable via share tokens - they contain sensitive
    confirmation numbers and payment information. Only the owner can view.

    Args:
        booking: The booking to check, or None if not found.
        user: The authenticated user, or None in MVP mode.

    Returns:
        AuthorizationResult with allowed/denied and reason.
    """
    if not booking:
        return AuthorizationResult.deny("not_found")

    # Owner access (authenticated)
    if user:
        booking_user_id = getattr(booking, "user_id", None)
        if booking_user_id and booking_user_id == user.id:
            return AuthorizationResult.allow("owner")

    # MVP mode: Allow if no auth required
    if user is None:
        return AuthorizationResult.allow("mvp_no_auth")

    return AuthorizationResult.deny("unauthorized")


# =============================================================================
# Response Filtering
# =============================================================================


def filter_itinerary_for_share(
    itinerary: Any,  # Itinerary instance
    permission: SharePermission,
) -> dict[str, Any]:
    """Filter itinerary data based on share permission level.

    VIEW_SUMMARY: Only trip dates, destinations, and activity names.
    VIEW_FULL: Complete plan with prices but no confirmation numbers.

    Args:
        itinerary: The itinerary to filter.
        permission: The permission level determining what to include.

    Returns:
        Filtered dictionary suitable for sharing.
    """
    # Extract basic info that's always safe to share
    trip_summary = getattr(itinerary, "trip_summary", None)
    days = getattr(itinerary, "days", [])

    if permission == SharePermission.VIEW_SUMMARY:
        # High-level itinerary only - no prices or booking details
        return {
            "destination": getattr(trip_summary, "destination", None) if trip_summary else None,
            "dates": {
                "start": str(getattr(trip_summary, "start_date", None)) if trip_summary else None,
                "end": str(getattr(trip_summary, "end_date", None)) if trip_summary else None,
            },
            "travelers": getattr(trip_summary, "travelers", None) if trip_summary else None,
            "days": [
                {
                    "date": str(getattr(day, "date", None)),
                    "activities": [
                        getattr(activity, "name", None)
                        for activity in getattr(day, "activities", [])
                    ],
                }
                for day in days
            ],
            # No prices, no booking details
        }

    elif permission == SharePermission.VIEW_FULL:
        # Complete plan with prices (read-only)
        return {
            "destination": getattr(trip_summary, "destination", None) if trip_summary else None,
            "dates": {
                "start": str(getattr(trip_summary, "start_date", None)) if trip_summary else None,
                "end": str(getattr(trip_summary, "end_date", None)) if trip_summary else None,
            },
            "travelers": getattr(trip_summary, "travelers", None) if trip_summary else None,
            "trip_type": getattr(trip_summary, "trip_type", None) if trip_summary else None,
            "days": [
                {
                    "date": str(getattr(day, "date", None)),
                    "activities": [
                        {
                            "name": getattr(activity, "name", None),
                            "time": getattr(activity, "time", None),
                            "duration": getattr(activity, "duration", None),
                            "location": getattr(activity, "location", None),
                            "price": getattr(activity, "price", None),
                        }
                        for activity in getattr(day, "activities", [])
                    ],
                }
                for day in days
            ],
            "total_estimated_cost": getattr(itinerary, "total_estimated_cost", None),
            # No confirmation numbers, no payment details
        }

    # Default: same as VIEW_SUMMARY
    return filter_itinerary_for_share(itinerary, SharePermission.VIEW_SUMMARY)
