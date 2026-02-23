"""
SessionRef: Multi-key reference for workflow state lookup.

SessionRef enables workflow lookup via any ID in the hierarchy:
- session_id: Browser session tracking (ephemeral)
- consultation_id: Planning conversation (returned to client)
- itinerary_id: Approved travel plan (user-facing, shareable)
- booking_id: Individual bookable item

This supports various resumption scenarios:
- User returns to same browser session
- User resumes planning via consultation_id from any device
- User shares itinerary link
- User references booking confirmation
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionRef:
    """Reference for looking up a workflow state.

    At least one ID should be provided. The lookup chain tries IDs
    in priority order: session_id → consultation_id → itinerary_id → booking_id.

    Attributes:
        session_id: Frontend conversation/session id (best for returning to same chat)
        consultation_id: Business workflow id (non-guessable, for resuming planning)
        itinerary_id: Approved itinerary id (user-facing, shareable)
        booking_id: Individual booking id (for booking status/retry)
    """

    session_id: str | None = None
    consultation_id: str | None = None
    itinerary_id: str | None = None
    booking_id: str | None = None

    def has_any_id(self) -> bool:
        """Check if at least one ID is present."""
        return any(
            [self.session_id, self.consultation_id, self.itinerary_id, self.booking_id]
        )

    def primary_id(self) -> str | None:
        """Return the highest-priority ID present.

        Priority order: session_id > consultation_id > itinerary_id > booking_id
        """
        return (
            self.session_id
            or self.consultation_id
            or self.itinerary_id
            or self.booking_id
        )

    def to_dict(self) -> dict:
        """Convert to dictionary, omitting None values."""
        result = {}
        if self.session_id:
            result["session_id"] = self.session_id
        if self.consultation_id:
            result["consultation_id"] = self.consultation_id
        if self.itinerary_id:
            result["itinerary_id"] = self.itinerary_id
        if self.booking_id:
            result["booking_id"] = self.booking_id
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "SessionRef":
        """Create SessionRef from dictionary."""
        return cls(
            session_id=data.get("session_id"),
            consultation_id=data.get("consultation_id"),
            itinerary_id=data.get("itinerary_id"),
            booking_id=data.get("booking_id"),
        )
