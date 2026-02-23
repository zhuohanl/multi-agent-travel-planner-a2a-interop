"""Unit tests for authorization helpers.

Tests cover:
1. MVP mode (no auth, allows all)
2. Share token access control
3. Owner-only booking access
4. Itinerary filtering by permission level
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pytest

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
from src.orchestrator.auth.share_tokens import InMemoryShareTokenStore


# =============================================================================
# Test Fixtures and Mocks
# =============================================================================


@dataclass
class MockWorkflowState:
    """Mock WorkflowState for testing authorization."""

    session_id: str = "sess_123"
    consultation_id: str = "cons_456"
    user_id: str | None = None


@dataclass
class MockItinerary:
    """Mock Itinerary for testing authorization."""

    itinerary_id: str = "itn_789"
    user_id: str | None = None
    trip_summary: Any | None = None
    days: list[Any] | None = None
    total_estimated_cost: float | None = None


@dataclass
class MockTripSummary:
    """Mock TripSummary for testing."""

    destination: str = "Tokyo"
    start_date: str = "2024-03-15"
    end_date: str = "2024-03-20"
    travelers: int = 2
    trip_type: str = "leisure"


@dataclass
class MockDay:
    """Mock ItineraryDay for testing."""

    date: str = "2024-03-15"
    activities: list[Any] | None = None


@dataclass
class MockActivity:
    """Mock Activity for testing."""

    name: str = "Visit Temple"
    time: str = "09:00"
    duration: str = "2 hours"
    location: str = "Asakusa"
    price: float = 0.0


@dataclass
class MockBooking:
    """Mock Booking for testing authorization."""

    booking_id: str = "book_abc"
    user_id: str | None = None


# =============================================================================
# AuthorizationResult Tests
# =============================================================================


class TestAuthorizationResult:
    """Tests for AuthorizationResult dataclass."""

    def test_allow_creates_allowed_result(self):
        """Test creating an allowed result."""
        result = AuthorizationResult.allow("owner")
        assert result.allowed is True
        assert result.reason == "owner"
        assert result.permission is None

    def test_allow_with_permission(self):
        """Test creating an allowed result with permission."""
        result = AuthorizationResult.allow("share_token", SharePermission.VIEW_SUMMARY)
        assert result.allowed is True
        assert result.reason == "share_token"
        assert result.permission == SharePermission.VIEW_SUMMARY

    def test_deny_creates_denied_result(self):
        """Test creating a denied result."""
        result = AuthorizationResult.deny("unauthorized")
        assert result.allowed is False
        assert result.reason == "unauthorized"
        assert result.permission is None


# =============================================================================
# ShareToken Tests
# =============================================================================


class TestShareToken:
    """Tests for ShareToken dataclass."""

    def test_create_share_token(self):
        """Test creating a share token with factory method."""
        token = ShareToken.create(
            itinerary_id="itn_123",
            created_by="user_456",
            permission=SharePermission.VIEW_SUMMARY,
            expires_in_days=7,
        )

        assert token.itinerary_id == "itn_123"
        assert token.created_by == "user_456"
        assert token.permission == SharePermission.VIEW_SUMMARY
        assert token.revoked is False
        assert len(token.token) > 20  # URL-safe token
        assert token.expires_at > datetime.utcnow()

    def test_is_valid_returns_true_for_valid_token(self):
        """Test that is_valid returns True for non-expired, non-revoked token."""
        token = ShareToken.create(
            itinerary_id="itn_123",
            created_by="user_456",
        )
        assert token.is_valid() is True

    def test_is_valid_returns_false_for_revoked_token(self):
        """Test that is_valid returns False for revoked token."""
        token = ShareToken.create(
            itinerary_id="itn_123",
            created_by="user_456",
        )
        token.revoked = True
        assert token.is_valid() is False

    def test_is_valid_returns_false_for_expired_token(self):
        """Test that is_valid returns False for expired token."""
        token = ShareToken(
            token="test_token",
            itinerary_id="itn_123",
            created_by="user_456",
            created_at=datetime.utcnow() - timedelta(days=10),
            expires_at=datetime.utcnow() - timedelta(days=3),  # Expired
            permission=SharePermission.VIEW_SUMMARY,
        )
        assert token.is_valid() is False


# =============================================================================
# authorize_workflow_mutation Tests
# =============================================================================


class TestAuthorizeWorkflowMutation:
    """Tests for authorize_workflow_mutation."""

    def test_authorize_workflow_mutation_mvp_allows(self):
        """Test that MVP mode (user=None) allows access."""
        state = MockWorkflowState()
        result = authorize_workflow_mutation(state, user=None)

        assert result.allowed is True
        assert result.reason == "mvp_no_auth"

    def test_authorize_workflow_mutation_denies_when_state_none(self):
        """Test that None state is denied (workflow expired)."""
        result = authorize_workflow_mutation(state=None, user=None)

        assert result.allowed is False
        assert result.reason == "workflow_expired"

    def test_authorize_workflow_mutation_owner_allowed(self):
        """Test that owner is allowed in production mode."""
        state = MockWorkflowState(user_id="user_123")
        user = AuthenticatedUser(id="user_123")
        result = authorize_workflow_mutation(state, user)

        assert result.allowed is True
        assert result.reason == "owner"

    def test_authorize_workflow_mutation_non_owner_denied(self):
        """Test that non-owner is denied in production mode."""
        state = MockWorkflowState(user_id="user_123")
        user = AuthenticatedUser(id="user_different")
        result = authorize_workflow_mutation(state, user)

        assert result.allowed is False
        assert result.reason == "unauthorized"


# =============================================================================
# authorize_itinerary_read Tests
# =============================================================================


class TestAuthorizeItineraryRead:
    """Tests for authorize_itinerary_read."""

    def test_authorize_itinerary_read_with_share_token(self):
        """Test that valid share token grants access."""
        itinerary = MockItinerary(itinerary_id="itn_789")
        token = ShareToken.create(
            itinerary_id="itn_789",
            created_by="user_456",
            permission=SharePermission.VIEW_FULL,
        )

        result = authorize_itinerary_read(itinerary, user=None, share_token=token)

        assert result.allowed is True
        assert result.reason == "share_token"
        assert result.permission == SharePermission.VIEW_FULL

    def test_authorize_itinerary_read_mvp_allows(self):
        """Test that MVP mode (user=None, no token) allows access."""
        itinerary = MockItinerary()
        result = authorize_itinerary_read(itinerary, user=None, share_token=None)

        assert result.allowed is True
        assert result.reason == "mvp_no_auth"
        assert result.permission == SharePermission.VIEW_FULL

    def test_authorize_itinerary_read_owner_allowed(self):
        """Test that owner is allowed."""
        itinerary = MockItinerary(user_id="user_123")
        user = AuthenticatedUser(id="user_123")
        result = authorize_itinerary_read(itinerary, user, share_token=None)

        assert result.allowed is True
        assert result.reason == "owner"

    def test_authorize_itinerary_read_not_found(self):
        """Test that None itinerary is denied."""
        result = authorize_itinerary_read(itinerary=None, user=None, share_token=None)

        assert result.allowed is False
        assert result.reason == "not_found"

    def test_authorize_itinerary_read_expired_token_denied(self):
        """Test that expired share token is denied."""
        itinerary = MockItinerary(itinerary_id="itn_789", user_id="user_123")
        user = AuthenticatedUser(id="user_different")  # Not owner
        token = ShareToken(
            token="test_token",
            itinerary_id="itn_789",
            created_by="user_123",
            created_at=datetime.utcnow() - timedelta(days=10),
            expires_at=datetime.utcnow() - timedelta(days=3),  # Expired
            permission=SharePermission.VIEW_SUMMARY,
        )

        result = authorize_itinerary_read(itinerary, user, share_token=token)

        assert result.allowed is False
        assert result.reason == "share_token_expired_or_revoked"

    def test_authorize_itinerary_read_wrong_itinerary_token_denied(self):
        """Test that share token for wrong itinerary is denied."""
        itinerary = MockItinerary(itinerary_id="itn_789", user_id="user_123")
        user = AuthenticatedUser(id="user_different")  # Not owner
        token = ShareToken.create(
            itinerary_id="itn_DIFFERENT",  # Wrong itinerary
            created_by="user_123",
        )

        result = authorize_itinerary_read(itinerary, user, share_token=token)

        assert result.allowed is False
        assert result.reason == "unauthorized"


# =============================================================================
# authorize_booking_read Tests
# =============================================================================


class TestAuthorizeBookingRead:
    """Tests for authorize_booking_read."""

    def test_authorize_booking_read_owner_only(self):
        """Test that only owner can read booking in production mode."""
        booking = MockBooking(user_id="user_123")
        user = AuthenticatedUser(id="user_123")
        result = authorize_booking_read(booking, user)

        assert result.allowed is True
        assert result.reason == "owner"

    def test_authorize_booking_read_non_owner_denied(self):
        """Test that non-owner is denied."""
        booking = MockBooking(user_id="user_123")
        user = AuthenticatedUser(id="user_different")
        result = authorize_booking_read(booking, user)

        assert result.allowed is False
        assert result.reason == "unauthorized"

    def test_authorize_booking_read_mvp_allows(self):
        """Test that MVP mode (user=None) allows access."""
        booking = MockBooking()
        result = authorize_booking_read(booking, user=None)

        assert result.allowed is True
        assert result.reason == "mvp_no_auth"

    def test_authorize_booking_read_not_found(self):
        """Test that None booking is denied."""
        result = authorize_booking_read(booking=None, user=None)

        assert result.allowed is False
        assert result.reason == "not_found"


# =============================================================================
# filter_itinerary_for_share Tests
# =============================================================================


class TestFilterItineraryForShare:
    """Tests for filter_itinerary_for_share."""

    def test_filter_itinerary_for_share_summary(self):
        """Test filtering for VIEW_SUMMARY permission."""
        activity = MockActivity(name="Temple Visit")
        day = MockDay(activities=[activity])
        trip_summary = MockTripSummary()
        itinerary = MockItinerary(
            trip_summary=trip_summary,
            days=[day],
            total_estimated_cost=5000.0,
        )

        result = filter_itinerary_for_share(itinerary, SharePermission.VIEW_SUMMARY)

        assert result["destination"] == "Tokyo"
        assert "start" in result["dates"]
        assert result["travelers"] == 2
        assert len(result["days"]) == 1
        # Summary should only include activity names
        assert result["days"][0]["activities"] == ["Temple Visit"]
        # Should NOT include prices or detailed info
        assert "total_estimated_cost" not in result

    def test_filter_itinerary_for_share_full(self):
        """Test filtering for VIEW_FULL permission."""
        activity = MockActivity(name="Temple Visit", price=25.0)
        day = MockDay(activities=[activity])
        trip_summary = MockTripSummary()
        itinerary = MockItinerary(
            trip_summary=trip_summary,
            days=[day],
            total_estimated_cost=5000.0,
        )

        result = filter_itinerary_for_share(itinerary, SharePermission.VIEW_FULL)

        assert result["destination"] == "Tokyo"
        assert result["trip_type"] == "leisure"
        # Full should include detailed activity info
        assert result["days"][0]["activities"][0]["name"] == "Temple Visit"
        assert result["days"][0]["activities"][0]["price"] == 25.0
        # Should include total cost
        assert result["total_estimated_cost"] == 5000.0


# =============================================================================
# InMemoryShareTokenStore Tests
# =============================================================================


class TestInMemoryShareTokenStore:
    """Tests for InMemoryShareTokenStore."""

    @pytest.fixture
    def store(self):
        """Create a fresh store for each test."""
        return InMemoryShareTokenStore()

    @pytest.mark.asyncio
    async def test_save_and_get_by_token(self, store):
        """Test saving and retrieving a token."""
        token = ShareToken.create(
            itinerary_id="itn_123",
            created_by="user_456",
        )

        await store.save(token)
        retrieved = await store.get_by_token(token.token)

        assert retrieved is not None
        assert retrieved.itinerary_id == "itn_123"
        assert retrieved.created_by == "user_456"

    @pytest.mark.asyncio
    async def test_get_by_token_not_found(self, store):
        """Test that get_by_token returns None for non-existent token."""
        result = await store.get_by_token("nonexistent_token")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_itinerary(self, store):
        """Test retrieving all tokens for an itinerary."""
        token1 = ShareToken.create(itinerary_id="itn_123", created_by="user_1")
        token2 = ShareToken.create(itinerary_id="itn_123", created_by="user_2")
        token3 = ShareToken.create(itinerary_id="itn_different", created_by="user_1")

        await store.save(token1)
        await store.save(token2)
        await store.save(token3)

        tokens = await store.get_by_itinerary("itn_123")
        assert len(tokens) == 2

    @pytest.mark.asyncio
    async def test_revoke_token(self, store):
        """Test revoking a token."""
        token = ShareToken.create(
            itinerary_id="itn_123",
            created_by="user_456",
        )
        await store.save(token)

        # Revoke the token
        result = await store.revoke(token.token)
        assert result is True

        # Check token is now revoked
        retrieved = await store.get_by_token(token.token)
        assert retrieved is not None
        assert retrieved.revoked is True
        assert retrieved.is_valid() is False

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_token(self, store):
        """Test that revoking non-existent token returns False."""
        result = await store.revoke("nonexistent_token")
        assert result is False

    @pytest.mark.asyncio
    async def test_clear(self, store):
        """Test clearing all tokens."""
        token = ShareToken.create(itinerary_id="itn_123", created_by="user_456")
        await store.save(token)

        assert store.count() == 1
        store.clear()
        assert store.count() == 0

    @pytest.mark.asyncio
    async def test_count(self, store):
        """Test counting tokens."""
        assert store.count() == 0

        token1 = ShareToken.create(itinerary_id="itn_1", created_by="user_1")
        token2 = ShareToken.create(itinerary_id="itn_2", created_by="user_2")

        await store.save(token1)
        assert store.count() == 1

        await store.save(token2)
        assert store.count() == 2
