"""
Unit tests for discovery_artifacts storage module.

Tests cover:
- DiscoveryArtifact dataclass creation and serialization
- InMemoryDiscoveryArtifactsStore operations
- TTL configuration
- Query filtering by job_id and agent_name
"""

import pytest
from datetime import datetime, timezone

from src.orchestrator.storage.discovery_artifacts import (
    DISCOVERY_ARTIFACTS_TTL,
    DiscoveryArtifact,
    DiscoveryArtifactsStoreProtocol,
    InMemoryDiscoveryArtifactsStore,
)


class TestDiscoveryArtifact:
    """Tests for DiscoveryArtifact dataclass."""

    def test_creation_with_required_fields(self):
        """Test creating artifact with required fields only."""
        artifact = DiscoveryArtifact(
            consultation_id="cons_abc123",
            job_id="job_xyz789",
            agent_name="stay",
            full_results=[{"name": "Hotel A"}, {"name": "Hotel B"}],
        )

        assert artifact.consultation_id == "cons_abc123"
        assert artifact.job_id == "job_xyz789"
        assert artifact.agent_name == "stay"
        assert len(artifact.full_results) == 2
        assert artifact.result_count == 2  # Auto-calculated
        assert isinstance(artifact.created_at, datetime)

    def test_result_count_auto_calculated(self):
        """Test that result_count is auto-calculated from full_results."""
        artifact = DiscoveryArtifact(
            consultation_id="cons_abc123",
            job_id="job_xyz789",
            agent_name="transport",
            full_results=[{"flight": "AA123"}, {"flight": "UA456"}, {"flight": "DL789"}],
        )

        assert artifact.result_count == 3

    def test_result_count_explicit(self):
        """Test that explicit result_count is preserved."""
        artifact = DiscoveryArtifact(
            consultation_id="cons_abc123",
            job_id="job_xyz789",
            agent_name="poi",
            full_results=[{"name": "POI1"}],
            result_count=100,  # Explicit value
        )

        # Explicit value is preserved when non-zero
        assert artifact.result_count == 100

    def test_artifact_id_generation(self):
        """Test that artifact_id is generated correctly."""
        artifact = DiscoveryArtifact(
            consultation_id="cons_abc123",
            job_id="job_xyz789",
            agent_name="stay",
            full_results=[],
        )

        assert artifact.artifact_id == "artifact_job_xyz789_stay"

    def test_to_dict_includes_all_fields(self):
        """Test serialization includes all required fields."""
        now = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        artifact = DiscoveryArtifact(
            consultation_id="cons_abc123",
            job_id="job_xyz789",
            agent_name="dining",
            full_results=[{"restaurant": "Sushi Place"}],
            result_count=1,
            created_at=now,
        )

        doc = artifact.to_dict()

        assert doc["id"] == "artifact_job_xyz789_dining"
        assert doc["consultation_id"] == "cons_abc123"
        assert doc["job_id"] == "job_xyz789"
        assert doc["agent_name"] == "dining"
        assert doc["full_results"] == [{"restaurant": "Sushi Place"}]
        assert doc["result_count"] == 1
        assert doc["created_at"] == "2024-01-15T10:30:00+00:00"
        assert doc["ttl"] == DISCOVERY_ARTIFACTS_TTL

    def test_from_dict_creates_artifact(self):
        """Test deserialization creates correct artifact."""
        doc = {
            "id": "artifact_job_xyz789_events",
            "consultation_id": "cons_abc123",
            "job_id": "job_xyz789",
            "agent_name": "events",
            "full_results": [{"event": "Concert"}, {"event": "Festival"}],
            "result_count": 2,
            "created_at": "2024-01-15T10:30:00+00:00",
            "ttl": DISCOVERY_ARTIFACTS_TTL,
        }

        artifact = DiscoveryArtifact.from_dict(doc)

        assert artifact.consultation_id == "cons_abc123"
        assert artifact.job_id == "job_xyz789"
        assert artifact.agent_name == "events"
        assert len(artifact.full_results) == 2
        assert artifact.result_count == 2
        assert artifact.created_at.year == 2024

    def test_from_dict_handles_missing_fields(self):
        """Test deserialization handles missing optional fields."""
        doc = {
            "consultation_id": "cons_abc123",
            "job_id": "job_xyz789",
            "agent_name": "stay",
        }

        artifact = DiscoveryArtifact.from_dict(doc)

        assert artifact.consultation_id == "cons_abc123"
        assert artifact.full_results == []
        assert artifact.result_count == 0
        assert isinstance(artifact.created_at, datetime)

    def test_roundtrip_serialization(self):
        """Test that serialization and deserialization are reversible."""
        original = DiscoveryArtifact(
            consultation_id="cons_abc123",
            job_id="job_xyz789",
            agent_name="transport",
            full_results=[{"flight": "AA123", "price": 450.0}],
        )

        doc = original.to_dict()
        restored = DiscoveryArtifact.from_dict(doc)

        assert restored.consultation_id == original.consultation_id
        assert restored.job_id == original.job_id
        assert restored.agent_name == original.agent_name
        assert restored.full_results == original.full_results
        assert restored.result_count == original.result_count


class TestDiscoveryArtifactsTTL:
    """Tests for TTL configuration."""

    def test_ttl_is_seven_days(self):
        """Test that TTL is set to 7 days in seconds."""
        expected_ttl = 7 * 24 * 60 * 60  # 604800 seconds
        assert DISCOVERY_ARTIFACTS_TTL == expected_ttl

    def test_artifact_includes_ttl_in_dict(self):
        """Test that TTL is included in serialized document."""
        artifact = DiscoveryArtifact(
            consultation_id="cons_abc123",
            job_id="job_xyz789",
            agent_name="stay",
            full_results=[],
        )

        doc = artifact.to_dict()
        assert doc["ttl"] == DISCOVERY_ARTIFACTS_TTL


class TestInMemoryDiscoveryArtifactsStore:
    """Tests for InMemoryDiscoveryArtifactsStore."""

    @pytest.fixture
    def store(self) -> InMemoryDiscoveryArtifactsStore:
        """Create a fresh in-memory store for each test."""
        return InMemoryDiscoveryArtifactsStore()

    @pytest.fixture
    def sample_artifact(self) -> DiscoveryArtifact:
        """Create a sample artifact for testing."""
        return DiscoveryArtifact(
            consultation_id="cons_test123",
            job_id="job_test456",
            agent_name="stay",
            full_results=[
                {"name": "Hotel A", "price": 200},
                {"name": "Hotel B", "price": 250},
            ],
        )

    @pytest.mark.asyncio
    async def test_save_artifact(self, store: InMemoryDiscoveryArtifactsStore, sample_artifact: DiscoveryArtifact):
        """Test saving an artifact."""
        saved = await store.save_artifact(sample_artifact)

        assert saved.consultation_id == sample_artifact.consultation_id
        assert saved.job_id == sample_artifact.job_id
        assert saved.agent_name == sample_artifact.agent_name
        assert store.get_artifact_count("cons_test123") == 1

    @pytest.mark.asyncio
    async def test_save_artifact_upsert(self, store: InMemoryDiscoveryArtifactsStore):
        """Test that saving the same artifact updates it."""
        artifact1 = DiscoveryArtifact(
            consultation_id="cons_test123",
            job_id="job_test456",
            agent_name="stay",
            full_results=[{"name": "Hotel A"}],
        )
        artifact2 = DiscoveryArtifact(
            consultation_id="cons_test123",
            job_id="job_test456",
            agent_name="stay",
            full_results=[{"name": "Hotel A"}, {"name": "Hotel B"}],
        )

        await store.save_artifact(artifact1)
        await store.save_artifact(artifact2)

        assert store.get_artifact_count("cons_test123") == 1

        retrieved = await store.get_artifact("cons_test123", "job_test456", "stay")
        assert retrieved is not None
        assert len(retrieved.full_results) == 2

    @pytest.mark.asyncio
    async def test_get_artifact_found(self, store: InMemoryDiscoveryArtifactsStore, sample_artifact: DiscoveryArtifact):
        """Test retrieving an existing artifact."""
        await store.save_artifact(sample_artifact)

        retrieved = await store.get_artifact("cons_test123", "job_test456", "stay")

        assert retrieved is not None
        assert retrieved.agent_name == "stay"
        assert len(retrieved.full_results) == 2

    @pytest.mark.asyncio
    async def test_get_artifact_not_found(self, store: InMemoryDiscoveryArtifactsStore):
        """Test retrieving a non-existent artifact returns None."""
        retrieved = await store.get_artifact("cons_nonexistent", "job_xyz", "stay")

        assert retrieved is None

    @pytest.mark.asyncio
    async def test_get_artifact_wrong_agent(self, store: InMemoryDiscoveryArtifactsStore, sample_artifact: DiscoveryArtifact):
        """Test retrieving artifact with wrong agent_name returns None."""
        await store.save_artifact(sample_artifact)

        retrieved = await store.get_artifact("cons_test123", "job_test456", "transport")

        assert retrieved is None

    @pytest.mark.asyncio
    async def test_get_artifacts_all(self, store: InMemoryDiscoveryArtifactsStore):
        """Test retrieving all artifacts for a consultation."""
        artifacts = [
            DiscoveryArtifact(
                consultation_id="cons_test123",
                job_id="job_test456",
                agent_name="stay",
                full_results=[{"name": "Hotel A"}],
            ),
            DiscoveryArtifact(
                consultation_id="cons_test123",
                job_id="job_test456",
                agent_name="transport",
                full_results=[{"flight": "AA123"}],
            ),
            DiscoveryArtifact(
                consultation_id="cons_test123",
                job_id="job_test789",
                agent_name="poi",
                full_results=[{"name": "Museum"}],
            ),
        ]

        for artifact in artifacts:
            await store.save_artifact(artifact)

        retrieved = await store.get_artifacts("cons_test123")

        assert len(retrieved) == 3

    @pytest.mark.asyncio
    async def test_get_artifacts_by_job_id(self, store: InMemoryDiscoveryArtifactsStore):
        """Test retrieving artifacts filtered by job_id."""
        artifacts = [
            DiscoveryArtifact(
                consultation_id="cons_test123",
                job_id="job_test456",
                agent_name="stay",
                full_results=[{"name": "Hotel A"}],
            ),
            DiscoveryArtifact(
                consultation_id="cons_test123",
                job_id="job_test456",
                agent_name="transport",
                full_results=[{"flight": "AA123"}],
            ),
            DiscoveryArtifact(
                consultation_id="cons_test123",
                job_id="job_test789",
                agent_name="poi",
                full_results=[{"name": "Museum"}],
            ),
        ]

        for artifact in artifacts:
            await store.save_artifact(artifact)

        retrieved = await store.get_artifacts("cons_test123", job_id="job_test456")

        assert len(retrieved) == 2
        assert all(a.job_id == "job_test456" for a in retrieved)

    @pytest.mark.asyncio
    async def test_get_artifacts_empty(self, store: InMemoryDiscoveryArtifactsStore):
        """Test retrieving artifacts for non-existent consultation returns empty list."""
        retrieved = await store.get_artifacts("cons_nonexistent")

        assert retrieved == []

    @pytest.mark.asyncio
    async def test_delete_artifacts_all(self, store: InMemoryDiscoveryArtifactsStore):
        """Test deleting all artifacts for a consultation."""
        artifacts = [
            DiscoveryArtifact(
                consultation_id="cons_test123",
                job_id="job_test456",
                agent_name="stay",
                full_results=[],
            ),
            DiscoveryArtifact(
                consultation_id="cons_test123",
                job_id="job_test789",
                agent_name="transport",
                full_results=[],
            ),
        ]

        for artifact in artifacts:
            await store.save_artifact(artifact)

        deleted_count = await store.delete_artifacts("cons_test123")

        assert deleted_count == 2
        assert store.get_artifact_count("cons_test123") == 0

    @pytest.mark.asyncio
    async def test_delete_artifacts_by_job_id(self, store: InMemoryDiscoveryArtifactsStore):
        """Test deleting artifacts filtered by job_id."""
        artifacts = [
            DiscoveryArtifact(
                consultation_id="cons_test123",
                job_id="job_test456",
                agent_name="stay",
                full_results=[],
            ),
            DiscoveryArtifact(
                consultation_id="cons_test123",
                job_id="job_test456",
                agent_name="transport",
                full_results=[],
            ),
            DiscoveryArtifact(
                consultation_id="cons_test123",
                job_id="job_test789",
                agent_name="poi",
                full_results=[],
            ),
        ]

        for artifact in artifacts:
            await store.save_artifact(artifact)

        deleted_count = await store.delete_artifacts("cons_test123", job_id="job_test456")

        assert deleted_count == 2
        assert store.get_artifact_count("cons_test123") == 1

        # Verify the remaining artifact
        remaining = await store.get_artifacts("cons_test123")
        assert len(remaining) == 1
        assert remaining[0].job_id == "job_test789"

    @pytest.mark.asyncio
    async def test_delete_artifacts_nonexistent(self, store: InMemoryDiscoveryArtifactsStore):
        """Test deleting artifacts for non-existent consultation returns 0."""
        deleted_count = await store.delete_artifacts("cons_nonexistent")

        assert deleted_count == 0

    @pytest.mark.asyncio
    async def test_clear(self, store: InMemoryDiscoveryArtifactsStore):
        """Test clearing all artifacts."""
        await store.save_artifact(
            DiscoveryArtifact(
                consultation_id="cons_1",
                job_id="job_1",
                agent_name="stay",
                full_results=[],
            )
        )
        await store.save_artifact(
            DiscoveryArtifact(
                consultation_id="cons_2",
                job_id="job_2",
                agent_name="transport",
                full_results=[],
            )
        )

        store.clear()

        assert store.get_artifact_count("cons_1") == 0
        assert store.get_artifact_count("cons_2") == 0
        assert store.get_all_consultation_ids() == []

    @pytest.mark.asyncio
    async def test_get_all_consultation_ids(self, store: InMemoryDiscoveryArtifactsStore):
        """Test getting all consultation IDs with artifacts."""
        await store.save_artifact(
            DiscoveryArtifact(
                consultation_id="cons_1",
                job_id="job_1",
                agent_name="stay",
                full_results=[],
            )
        )
        await store.save_artifact(
            DiscoveryArtifact(
                consultation_id="cons_2",
                job_id="job_2",
                agent_name="transport",
                full_results=[],
            )
        )

        consultation_ids = store.get_all_consultation_ids()

        assert len(consultation_ids) == 2
        assert "cons_1" in consultation_ids
        assert "cons_2" in consultation_ids

    @pytest.mark.asyncio
    async def test_artifacts_ordered_by_created_at(self, store: InMemoryDiscoveryArtifactsStore):
        """Test that retrieved artifacts are ordered by created_at."""
        # Create artifacts with explicit timestamps
        artifact1 = DiscoveryArtifact(
            consultation_id="cons_test123",
            job_id="job_test456",
            agent_name="stay",
            full_results=[],
            created_at=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
        )
        artifact2 = DiscoveryArtifact(
            consultation_id="cons_test123",
            job_id="job_test456",
            agent_name="transport",
            full_results=[],
            created_at=datetime(2024, 1, 15, 9, 0, 0, tzinfo=timezone.utc),  # Earlier
        )
        artifact3 = DiscoveryArtifact(
            consultation_id="cons_test123",
            job_id="job_test456",
            agent_name="poi",
            full_results=[],
            created_at=datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc),  # Latest
        )

        # Save in non-chronological order
        await store.save_artifact(artifact1)
        await store.save_artifact(artifact3)
        await store.save_artifact(artifact2)

        retrieved = await store.get_artifacts("cons_test123")

        # Should be ordered by created_at (earliest first)
        assert len(retrieved) == 3
        assert retrieved[0].agent_name == "transport"  # 9:00
        assert retrieved[1].agent_name == "stay"  # 10:00
        assert retrieved[2].agent_name == "poi"  # 11:00


class TestDiscoveryArtifactsStoreProtocol:
    """Tests for protocol compliance."""

    def test_in_memory_store_is_protocol_compliant(self):
        """Test that InMemoryDiscoveryArtifactsStore implements the protocol."""
        store = InMemoryDiscoveryArtifactsStore()
        assert isinstance(store, DiscoveryArtifactsStoreProtocol)

    @pytest.mark.asyncio
    async def test_protocol_methods_exist(self):
        """Test that protocol methods are callable on the store."""
        store: DiscoveryArtifactsStoreProtocol = InMemoryDiscoveryArtifactsStore()

        artifact = DiscoveryArtifact(
            consultation_id="cons_test",
            job_id="job_test",
            agent_name="stay",
            full_results=[{"test": "data"}],
        )

        # All protocol methods should be callable
        saved = await store.save_artifact(artifact)
        assert saved is not None

        retrieved = await store.get_artifact("cons_test", "job_test", "stay")
        assert retrieved is not None

        all_artifacts = await store.get_artifacts("cons_test")
        assert len(all_artifacts) == 1

        deleted = await store.delete_artifacts("cons_test")
        assert deleted == 1
