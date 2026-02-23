"""Storage layer for orchestrator workflow state and related data.

This module provides storage abstractions for:
- WorkflowState persistence in Cosmos DB
- Booking persistence in Cosmos DB
- Booking index for workflow lookup via booking_id
- Itinerary persistence in Cosmos DB
- Index stores for cross-session lookups
- Chat message storage for overflow conversation history
- Discovery job tracking for background operations
- Optimistic locking with etag for concurrency control

Storage Backend Selection:
    The STORAGE_BACKEND environment variable controls which implementation is used:
    - "cosmos" (default): Azure Cosmos DB for production
    - "memory": In-memory storage for testing and local development
"""

from src.orchestrator.storage.booking_index import (
    BookingIndexEntry,
    BookingIndexStore,
    BookingIndexStoreProtocol,
    InMemoryBookingIndexStore,
    calculate_booking_index_ttl,
)
from src.orchestrator.storage.discovery_artifacts import (
    DISCOVERY_ARTIFACTS_TTL,
    DiscoveryArtifact,
    DiscoveryArtifactsStore,
    DiscoveryArtifactsStoreProtocol,
    InMemoryDiscoveryArtifactsStore,
)
from src.orchestrator.storage.chat_messages import (
    CHAT_MESSAGES_TTL,
    ChatMessage,
    ChatMessageStore,
    ChatMessageStoreProtocol,
    InMemoryChatMessageStore,
)
from src.orchestrator.storage.booking_store import (
    BookingConflictError,
    BookingStore,
    BookingStoreProtocol,
    InMemoryBookingStore,
    calculate_booking_ttl,
)
from src.orchestrator.storage.consultation_index import (
    ConsultationIndexEntry,
    ConsultationIndexStore,
    ConsultationIndexStoreProtocol,
    InMemoryConsultationIndexStore,
    CONSULTATION_INDEX_TTL,
)
from src.orchestrator.storage.consultation_summaries import (
    ConsultationSummary,
    ConsultationSummaryStore,
    ConsultationSummaryStoreProtocol,
    InMemoryConsultationSummaryStore,
    calculate_consultation_summary_ttl,
)
from src.orchestrator.storage.discovery_jobs import (
    DISCOVERY_JOBS_TTL,
    AgentProgress,
    DiscoveryJob,
    DiscoveryJobStore,
    DiscoveryJobStoreProtocol,
    InMemoryDiscoveryJobStore,
    JobStatus,
)
from src.orchestrator.storage.itinerary_store import (
    InMemoryItineraryStore,
    ItineraryStore,
    ItineraryStoreProtocol,
    calculate_itinerary_ttl,
)
from src.orchestrator.storage.session_state import (
    ConflictError,
    InMemoryWorkflowStateStore,
    WorkflowStateData,
    WorkflowStateStore,
    WorkflowStateStoreProtocol,
)

__all__ = [
    # Workflow state
    "ConflictError",
    "InMemoryWorkflowStateStore",
    "WorkflowStateData",
    "WorkflowStateStore",
    "WorkflowStateStoreProtocol",
    # Booking store
    "BookingConflictError",
    "BookingStore",
    "BookingStoreProtocol",
    "InMemoryBookingStore",
    "calculate_booking_ttl",
    # Booking index
    "BookingIndexEntry",
    "BookingIndexStore",
    "BookingIndexStoreProtocol",
    "InMemoryBookingIndexStore",
    "calculate_booking_index_ttl",
    # Consultation index
    "ConsultationIndexEntry",
    "ConsultationIndexStore",
    "ConsultationIndexStoreProtocol",
    "InMemoryConsultationIndexStore",
    "CONSULTATION_INDEX_TTL",
    # Consultation summaries
    "ConsultationSummary",
    "ConsultationSummaryStore",
    "ConsultationSummaryStoreProtocol",
    "InMemoryConsultationSummaryStore",
    "calculate_consultation_summary_ttl",
    # Discovery jobs
    "DISCOVERY_JOBS_TTL",
    "AgentProgress",
    "DiscoveryJob",
    "DiscoveryJobStore",
    "DiscoveryJobStoreProtocol",
    "InMemoryDiscoveryJobStore",
    "JobStatus",
    # Itinerary
    "InMemoryItineraryStore",
    "ItineraryStore",
    "ItineraryStoreProtocol",
    "calculate_itinerary_ttl",
    # Chat messages
    "CHAT_MESSAGES_TTL",
    "ChatMessage",
    "ChatMessageStore",
    "ChatMessageStoreProtocol",
    "InMemoryChatMessageStore",
    # Discovery artifacts
    "DISCOVERY_ARTIFACTS_TTL",
    "DiscoveryArtifact",
    "DiscoveryArtifactsStore",
    "DiscoveryArtifactsStoreProtocol",
    "InMemoryDiscoveryArtifactsStore",
]
