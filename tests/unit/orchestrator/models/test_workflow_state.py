"""
Unit tests for WorkflowState model.

Tests cover:
- WorkflowState creation with all fields
- Serialization to Cosmos DB format
- Deserialization from Cosmos DB format
- Default values for optional fields
- Phase enum values
- AgentA2AState helper class
"""

import pytest
from datetime import datetime, timezone

from src.orchestrator.models.workflow_state import (
    AgentA2AState,
    Phase,
    WorkflowState,
)
from src.orchestrator.models.clarifier_conversation import ClarifierConversation
from src.orchestrator.models.conversation import AgentConversation


class TestPhaseEnum:
    """Tests for the Phase enum."""

    def test_phase_values(self):
        """Verify all phase values match design doc."""
        assert Phase.CLARIFICATION.value == "clarification"
        assert Phase.DISCOVERY_IN_PROGRESS.value == "discovery_in_progress"
        assert Phase.DISCOVERY_PLANNING.value == "discovery_planning"
        assert Phase.BOOKING.value == "booking"
        assert Phase.COMPLETED.value == "completed"
        assert Phase.FAILED.value == "failed"
        assert Phase.CANCELLED.value == "cancelled"

    def test_phase_count(self):
        """Verify we have exactly 7 phases."""
        assert len(Phase) == 7

    def test_phase_is_string_enum(self):
        """Phase should inherit from str for easy comparison."""
        assert Phase.CLARIFICATION == "clarification"
        assert isinstance(Phase.CLARIFICATION, str)


class TestAgentA2AState:
    """Tests for the AgentA2AState dataclass."""

    def test_creation_empty(self):
        """Test creation with defaults."""
        state = AgentA2AState()
        assert state.context_id is None
        assert state.task_id is None

    def test_creation_with_values(self):
        """Test creation with explicit values."""
        state = AgentA2AState(context_id="ctx_123", task_id="task_456")
        assert state.context_id == "ctx_123"
        assert state.task_id == "task_456"

    def test_to_dict(self):
        """Test serialization to dictionary."""
        state = AgentA2AState(context_id="ctx_123", task_id="task_456")
        result = state.to_dict()
        assert result == {
            "context_id": "ctx_123",
            "task_id": "task_456",
        }

    def test_to_dict_empty(self):
        """Test serialization with None values."""
        state = AgentA2AState()
        result = state.to_dict()
        assert result == {
            "context_id": None,
            "task_id": None,
        }

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {"context_id": "ctx_abc", "task_id": "task_xyz"}
        state = AgentA2AState.from_dict(data)
        assert state.context_id == "ctx_abc"
        assert state.task_id == "task_xyz"

    def test_from_dict_missing_fields(self):
        """Test deserialization with missing fields."""
        state = AgentA2AState.from_dict({})
        assert state.context_id is None
        assert state.task_id is None


class TestWorkflowStateCreation:
    """Tests for WorkflowState creation."""

    def test_creation_minimal(self):
        """Test creation with only required fields."""
        state = WorkflowState(
            session_id="sess_123",
            consultation_id="cons_456",
        )
        assert state.session_id == "sess_123"
        assert state.consultation_id == "cons_456"
        assert state.workflow_version == 1
        assert state.phase == Phase.CLARIFICATION
        assert state.checkpoint is None
        assert state.current_step == "gathering"

    def test_creation_full(self):
        """Test creation with all fields."""
        now = datetime.now(timezone.utc)
        state = WorkflowState(
            session_id="sess_123",
            consultation_id="cons_456",
            workflow_version=2,
            phase=Phase.BOOKING,
            checkpoint=None,
            current_step="booking_items",
            trip_spec={"destination": "Tokyo"},
            discovery_results={"transport": {}},
            itinerary_draft={"days": []},
            itinerary_id="itn_789",
            current_job_id="job_abc",
            last_synced_job_id="job_xyz",
            agent_context_ids={"clarifier": AgentA2AState(context_id="ctx_001")},
            discovery_requests={"stay": [{"request": "hotels"}]},
            discovery_artifact_id="artifact_123",
            conversation_overflow_count=5,
            created_at=now,
            updated_at=now,
            cancelled_at=None,
            etag="etag_1",
        )
        assert state.session_id == "sess_123"
        assert state.workflow_version == 2
        assert state.phase == Phase.BOOKING
        assert state.itinerary_id == "itn_789"
        assert state.discovery_artifact_id == "artifact_123"
        assert state.conversation_overflow_count == 5
        assert "clarifier" in state.agent_context_ids


class TestWorkflowStateDefaultValues:
    """Tests for WorkflowState default values."""

    def test_default_phase(self):
        """Default phase should be CLARIFICATION."""
        state = WorkflowState(session_id="sess", consultation_id="cons")
        assert state.phase == Phase.CLARIFICATION

    def test_default_workflow_version(self):
        """Default workflow_version should be 1."""
        state = WorkflowState(session_id="sess", consultation_id="cons")
        assert state.workflow_version == 1

    def test_default_current_step(self):
        """Default current_step should be 'gathering'."""
        state = WorkflowState(session_id="sess", consultation_id="cons")
        assert state.current_step == "gathering"

    def test_default_checkpoint(self):
        """Default checkpoint should be None."""
        state = WorkflowState(session_id="sess", consultation_id="cons")
        assert state.checkpoint is None

    def test_default_business_data(self):
        """Business data fields should default to None."""
        state = WorkflowState(session_id="sess", consultation_id="cons")
        assert state.trip_spec is None
        assert state.discovery_results is None
        assert state.itinerary_draft is None
        assert state.itinerary_id is None

    def test_default_job_coordination(self):
        """Job coordination fields should default to None."""
        state = WorkflowState(session_id="sess", consultation_id="cons")
        assert state.current_job_id is None
        assert state.last_synced_job_id is None

    def test_default_agent_coordination(self):
        """Agent coordination should have sensible defaults."""
        state = WorkflowState(session_id="sess", consultation_id="cons")
        assert state.agent_context_ids == {}
        assert state.discovery_requests == {}
        # clarifier_conversation is now ClarifierConversation for overflow support
        assert isinstance(state.clarifier_conversation, ClarifierConversation)
        assert state.clarifier_conversation.agent_name == "clarifier"
        assert len(state.clarifier_conversation.messages) == 0

    def test_default_sharding_fields(self):
        """Sharding fields should default appropriately."""
        state = WorkflowState(session_id="sess", consultation_id="cons")
        assert state.discovery_artifact_id is None
        assert state.conversation_overflow_count == 0

    def test_default_timestamps(self):
        """Timestamps should be auto-generated."""
        state = WorkflowState(session_id="sess", consultation_id="cons")
        assert state.created_at is not None
        assert state.updated_at is not None
        assert state.cancelled_at is None
        assert isinstance(state.created_at, datetime)
        assert isinstance(state.updated_at, datetime)


class TestWorkflowStateSerialization:
    """Tests for WorkflowState.to_dict() serialization."""

    def test_serialization_basic(self):
        """Test basic serialization."""
        state = WorkflowState(
            session_id="sess_123",
            consultation_id="cons_456",
        )
        result = state.to_dict()

        assert result["id"] == "sess_123"  # Cosmos document ID
        assert result["session_id"] == "sess_123"
        assert result["consultation_id"] == "cons_456"
        assert result["workflow_version"] == 1
        assert result["phase"] == "clarification"
        assert result["checkpoint"] is None
        assert result["current_step"] == "gathering"

    def test_serialization_phase_value(self):
        """Phase should be serialized as string value."""
        state = WorkflowState(
            session_id="sess",
            consultation_id="cons",
            phase=Phase.DISCOVERY_IN_PROGRESS,
        )
        result = state.to_dict()
        assert result["phase"] == "discovery_in_progress"

    def test_serialization_agent_context_ids(self):
        """Agent context IDs should be serialized properly."""
        state = WorkflowState(
            session_id="sess",
            consultation_id="cons",
            agent_context_ids={
                "clarifier": AgentA2AState(context_id="ctx_001", task_id="task_002"),
                "stay": AgentA2AState(context_id="ctx_003"),
            },
        )
        result = state.to_dict()
        assert result["agent_context_ids"] == {
            "clarifier": {"context_id": "ctx_001", "task_id": "task_002"},
            "stay": {"context_id": "ctx_003", "task_id": None},
        }

    def test_serialization_clarifier_conversation(self):
        """Clarifier conversation should be serialized."""
        # Now uses ClarifierConversation which has to_dict() method
        conv = ClarifierConversation(agent_name="clarifier", messages=[])
        conv.append_turn("Hello", "Hi there!")

        state = WorkflowState(
            session_id="sess",
            consultation_id="cons",
            clarifier_conversation=conv,
        )
        result = state.to_dict()

        assert result["clarifier_conversation"]["agent_name"] == "clarifier"
        assert result["clarifier_conversation"]["current_seq"] == 2
        assert len(result["clarifier_conversation"]["messages"]) == 2

    def test_serialization_timestamps(self):
        """Timestamps should be ISO format strings."""
        now = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        state = WorkflowState(
            session_id="sess",
            consultation_id="cons",
            created_at=now,
            updated_at=now,
        )
        result = state.to_dict()
        assert result["created_at"] == "2024-01-15T10:30:00+00:00"
        assert result["updated_at"] == "2024-01-15T10:30:00+00:00"
        assert result["cancelled_at"] is None

    def test_serialization_includes_ttl(self):
        """Serialization should include TTL for Cosmos DB."""
        state = WorkflowState(session_id="sess", consultation_id="cons")
        result = state.to_dict()
        assert result["ttl"] == 7 * 24 * 60 * 60  # 7 days in seconds


class TestWorkflowStateDeserialization:
    """Tests for WorkflowState.from_dict() deserialization."""

    def test_deserialization_basic(self):
        """Test basic deserialization."""
        data = {
            "session_id": "sess_123",
            "consultation_id": "cons_456",
            "workflow_version": 2,
            "phase": "booking",
            "checkpoint": None,
            "current_step": "booking_items",
        }
        state = WorkflowState.from_dict(data)

        assert state.session_id == "sess_123"
        assert state.consultation_id == "cons_456"
        assert state.workflow_version == 2
        assert state.phase == Phase.BOOKING
        assert state.checkpoint is None
        assert state.current_step == "booking_items"

    def test_deserialization_from_cosmos_id(self):
        """Should handle Cosmos document ID field."""
        data = {
            "id": "sess_123",  # Cosmos uses 'id' as document ID
            "consultation_id": "cons_456",
        }
        state = WorkflowState.from_dict(data)
        assert state.session_id == "sess_123"

    def test_deserialization_phase_string(self):
        """Phase should be deserialized from string."""
        for phase in Phase:
            data = {
                "session_id": "sess",
                "consultation_id": "cons",
                "phase": phase.value,
            }
            state = WorkflowState.from_dict(data)
            assert state.phase == phase

    def test_deserialization_invalid_phase(self):
        """Invalid phase should fall back to CLARIFICATION."""
        data = {
            "session_id": "sess",
            "consultation_id": "cons",
            "phase": "invalid_phase",
        }
        state = WorkflowState.from_dict(data)
        assert state.phase == Phase.CLARIFICATION

    def test_deserialization_agent_context_ids(self):
        """Agent context IDs should be deserialized."""
        data = {
            "session_id": "sess",
            "consultation_id": "cons",
            "agent_context_ids": {
                "clarifier": {"context_id": "ctx_001", "task_id": "task_002"},
                "stay": {"context_id": "ctx_003", "task_id": None},
            },
        }
        state = WorkflowState.from_dict(data)

        assert "clarifier" in state.agent_context_ids
        assert state.agent_context_ids["clarifier"].context_id == "ctx_001"
        assert state.agent_context_ids["clarifier"].task_id == "task_002"
        assert state.agent_context_ids["stay"].context_id == "ctx_003"
        assert state.agent_context_ids["stay"].task_id is None

    def test_deserialization_clarifier_conversation(self):
        """Clarifier conversation should be deserialized."""
        data = {
            "session_id": "sess",
            "consultation_id": "cons",
            "clarifier_conversation": {
                "agent_name": "clarifier",
                "messages": [
                    {
                        "messageId": "msg_001",
                        "role": "user",
                        "content": "Hello",
                        "timestamp": "2024-01-15T10:30:00+00:00",
                        "metadata": {"seq": 1},
                    },
                ],
                "current_seq": 1,
            },
        }
        state = WorkflowState.from_dict(data)

        assert state.clarifier_conversation.agent_name == "clarifier"
        assert state.clarifier_conversation.current_seq == 1
        assert len(state.clarifier_conversation.messages) == 1
        assert state.clarifier_conversation.messages[0].content == "Hello"

    def test_deserialization_timestamps(self):
        """Timestamps should be parsed from ISO strings."""
        data = {
            "session_id": "sess",
            "consultation_id": "cons",
            "created_at": "2024-01-15T10:30:00+00:00",
            "updated_at": "2024-01-15T11:00:00+00:00",
            "cancelled_at": "2024-01-15T12:00:00+00:00",
        }
        state = WorkflowState.from_dict(data)

        assert state.created_at == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert state.updated_at == datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc)
        assert state.cancelled_at == datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    def test_deserialization_missing_timestamps(self):
        """Missing timestamps should get defaults."""
        data = {
            "session_id": "sess",
            "consultation_id": "cons",
        }
        state = WorkflowState.from_dict(data)
        assert state.created_at is not None
        assert state.updated_at is not None
        assert state.cancelled_at is None

    def test_deserialization_etag(self):
        """Etag should be read from _etag field."""
        data = {
            "session_id": "sess",
            "consultation_id": "cons",
            "_etag": "etag_12345",
        }
        state = WorkflowState.from_dict(data)
        assert state.etag == "etag_12345"

    def test_deserialization_missing_fields(self):
        """Missing fields should get sensible defaults."""
        data = {
            "session_id": "sess",
            "consultation_id": "cons",
        }
        state = WorkflowState.from_dict(data)

        assert state.workflow_version == 1
        assert state.phase == Phase.CLARIFICATION
        assert state.current_step == "gathering"
        assert state.trip_spec is None
        assert state.agent_context_ids == {}
        assert state.discovery_requests == {}


class TestWorkflowStateRoundtrip:
    """Tests for serialization/deserialization roundtrip."""

    def test_roundtrip_basic(self):
        """Data should survive serialization roundtrip."""
        original = WorkflowState(
            session_id="sess_123",
            consultation_id="cons_456",
            workflow_version=3,
            phase=Phase.DISCOVERY_PLANNING,
            checkpoint="itinerary_approval",
            current_step="approval",
        )

        data = original.to_dict()
        restored = WorkflowState.from_dict(data)

        assert restored.session_id == original.session_id
        assert restored.consultation_id == original.consultation_id
        assert restored.workflow_version == original.workflow_version
        assert restored.phase == original.phase
        assert restored.checkpoint == original.checkpoint
        assert restored.current_step == original.current_step

    def test_roundtrip_with_agent_context(self):
        """Agent context should survive roundtrip."""
        original = WorkflowState(
            session_id="sess",
            consultation_id="cons",
            agent_context_ids={
                "clarifier": AgentA2AState(context_id="ctx_1", task_id="task_1"),
                "stay": AgentA2AState(context_id="ctx_2"),
            },
        )

        data = original.to_dict()
        restored = WorkflowState.from_dict(data)

        assert len(restored.agent_context_ids) == 2
        assert restored.agent_context_ids["clarifier"].context_id == "ctx_1"
        assert restored.agent_context_ids["clarifier"].task_id == "task_1"
        assert restored.agent_context_ids["stay"].context_id == "ctx_2"
        assert restored.agent_context_ids["stay"].task_id is None


class TestWorkflowStateHelperMethods:
    """Tests for WorkflowState helper methods."""

    def test_is_terminal_true(self):
        """Terminal states should return True."""
        for phase in [Phase.COMPLETED, Phase.FAILED, Phase.CANCELLED]:
            state = WorkflowState(
                session_id="sess",
                consultation_id="cons",
                phase=phase,
            )
            assert state.is_terminal() is True

    def test_is_terminal_false(self):
        """Non-terminal states should return False."""
        for phase in [Phase.CLARIFICATION, Phase.DISCOVERY_IN_PROGRESS,
                      Phase.DISCOVERY_PLANNING, Phase.BOOKING]:
            state = WorkflowState(
                session_id="sess",
                consultation_id="cons",
                phase=phase,
            )
            assert state.is_terminal() is False

    def test_is_at_checkpoint_true(self):
        """Should return True when checkpoint is set."""
        state = WorkflowState(
            session_id="sess",
            consultation_id="cons",
            checkpoint="trip_spec_approval",
        )
        assert state.is_at_checkpoint() is True

    def test_is_at_checkpoint_false(self):
        """Should return False when checkpoint is None."""
        state = WorkflowState(
            session_id="sess",
            consultation_id="cons",
            checkpoint=None,
        )
        assert state.is_at_checkpoint() is False

    def test_get_agent_a2a_state_existing(self):
        """Should return existing state."""
        state = WorkflowState(
            session_id="sess",
            consultation_id="cons",
            agent_context_ids={
                "clarifier": AgentA2AState(context_id="ctx_123"),
            },
        )
        result = state.get_agent_a2a_state("clarifier")
        assert result.context_id == "ctx_123"

    def test_get_agent_a2a_state_new(self):
        """Should create new state if not exists."""
        state = WorkflowState(session_id="sess", consultation_id="cons")
        result = state.get_agent_a2a_state("new_agent")

        assert result.context_id is None
        assert result.task_id is None
        assert "new_agent" in state.agent_context_ids

    def test_update_agent_a2a_state(self):
        """Should update agent state and timestamp."""
        state = WorkflowState(session_id="sess", consultation_id="cons")
        original_updated = state.updated_at

        state.update_agent_a2a_state(
            "clarifier",
            context_id="ctx_new",
            task_id="task_new",
        )

        assert state.agent_context_ids["clarifier"].context_id == "ctx_new"
        assert state.agent_context_ids["clarifier"].task_id == "task_new"
        # updated_at should be updated
        assert state.updated_at >= original_updated
