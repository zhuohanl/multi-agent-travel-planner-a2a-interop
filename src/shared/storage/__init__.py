"""Storage abstractions and implementations for the travel planner.

This module provides both the legacy storage interfaces (SessionStore,
ConsultationStore, BookingStore) and the new unified WorkflowStoreProtocol.

New code should use:
- WorkflowStoreProtocol: Protocol defining the unified interface
- InMemoryWorkflowStore: In-memory implementation for testing/development
- CosmosWorkflowStore: Production implementation (Cosmos DB)
- create_workflow_store: Factory function for backend selection

Legacy interfaces with Cosmos adapters:
- ConsultationStore + CosmosConsultationStore
- BookingStore + CosmosBookingStore

Factory function usage:
    from src.shared.storage import create_workflow_store

    # Use STORAGE_BACKEND env var (defaults to "memory")
    store = create_workflow_store()

    # Explicit backend
    store = create_workflow_store("cosmos")
"""
from .booking_store import BookingStore, InMemoryBookingStore
from .consultation_store import ConsultationStore, InMemoryConsultationStore
from .cosmos_booking_store import CosmosBookingStore
from .cosmos_consultation_store import CosmosConsultationStore
from .cosmos_workflow_store import CosmosWorkflowStore
from .in_memory_workflow_store import ConflictError, InMemoryWorkflowStore
from .protocols import WorkflowStoreProtocol, create_workflow_store
from .session_store import InMemorySessionStore, SessionStore

__all__ = [
    # New unified protocol and implementations
    "WorkflowStoreProtocol",
    "InMemoryWorkflowStore",
    "CosmosWorkflowStore",
    "create_workflow_store",
    "ConflictError",
    # Cosmos adapters for legacy interfaces
    "CosmosConsultationStore",
    "CosmosBookingStore",
    # Legacy interfaces (for backward compatibility)
    "SessionStore",
    "InMemorySessionStore",
    "ConsultationStore",
    "InMemoryConsultationStore",
    "BookingStore",
    "InMemoryBookingStore",
]
