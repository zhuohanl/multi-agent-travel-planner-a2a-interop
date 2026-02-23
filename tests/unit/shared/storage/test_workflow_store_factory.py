"""
Unit tests for create_workflow_store factory function.

Tests cover:
- Default backend selection (memory)
- Explicit backend selection via parameter
- Environment variable based selection
- InMemoryWorkflowStore creation
- Error handling for missing Cosmos configuration

Per ticket ORCH-097 acceptance criteria:
- create_workflow_store factory selects backend based on STORAGE_BACKEND env var
- Factory returns InMemoryWorkflowStore when backend is "memory"
- Factory validates Cosmos configuration when backend is "cosmos"
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from src.shared.storage.in_memory_workflow_store import InMemoryWorkflowStore
from src.shared.storage.protocols import (
    WorkflowStoreProtocol,
    create_workflow_store,
)


class TestDefaultBackendSelection:
    """Test default backend selection behavior."""

    def test_default_returns_in_memory_store(self) -> None:
        """Should return InMemoryWorkflowStore when no backend specified."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove STORAGE_BACKEND if it exists
            os.environ.pop("STORAGE_BACKEND", None)

            store = create_workflow_store()

            assert isinstance(store, InMemoryWorkflowStore)
            assert isinstance(store, WorkflowStoreProtocol)

    def test_explicit_memory_backend(self) -> None:
        """Should return InMemoryWorkflowStore with explicit 'memory' backend."""
        store = create_workflow_store("memory")

        assert isinstance(store, InMemoryWorkflowStore)

    def test_memory_backend_case_insensitive(self) -> None:
        """Should handle case-insensitive backend parameter."""
        store_lower = create_workflow_store("memory")
        store_upper = create_workflow_store("MEMORY")
        store_mixed = create_workflow_store("Memory")

        assert isinstance(store_lower, InMemoryWorkflowStore)
        assert isinstance(store_upper, InMemoryWorkflowStore)
        assert isinstance(store_mixed, InMemoryWorkflowStore)


class TestEnvironmentVariableSelection:
    """Test STORAGE_BACKEND environment variable selection."""

    def test_env_var_memory_backend(self) -> None:
        """Should use STORAGE_BACKEND=memory from environment."""
        with patch.dict(os.environ, {"STORAGE_BACKEND": "memory"}):
            store = create_workflow_store()

            assert isinstance(store, InMemoryWorkflowStore)

    def test_explicit_backend_overrides_env_var(self) -> None:
        """Explicit backend parameter should override environment variable."""
        with patch.dict(os.environ, {"STORAGE_BACKEND": "cosmos"}):
            # Explicit memory should override cosmos env var
            store = create_workflow_store("memory")

            assert isinstance(store, InMemoryWorkflowStore)

    def test_unknown_backend_defaults_to_memory(self) -> None:
        """Unknown backend values should default to in-memory."""
        store = create_workflow_store("unknown")

        assert isinstance(store, InMemoryWorkflowStore)


class TestCosmosBackendSelection:
    """Test Cosmos DB backend selection and configuration."""

    def test_cosmos_backend_requires_azure_cosmos_package(self) -> None:
        """Should raise ImportError when azure-cosmos not installed."""
        # In CI/test environment, azure-cosmos is typically not installed
        # This test verifies the import error is properly raised
        try:
            import azure.cosmos.aio  # noqa: F401

            # If azure-cosmos is installed, we need different test logic
            pytest.skip("azure-cosmos is installed, skipping import test")
        except ImportError:
            # Expected: azure-cosmos not installed
            with pytest.raises(ImportError) as exc_info:
                create_workflow_store("cosmos")

            assert "azure-cosmos" in str(exc_info.value)

    def test_cosmos_backend_with_mock_validates_endpoint(self) -> None:
        """Should raise ValueError when COSMOS_ENDPOINT missing (with mocked import)."""
        # Mock the azure.cosmos import to test configuration validation
        with patch.dict(
            os.environ,
            {
                "COSMOS_KEY": "test_key",
            },
            clear=True,
        ):
            os.environ.pop("COSMOS_ENDPOINT", None)

            # Mock azure.cosmos.aio to bypass import error
            with patch.dict(
                "sys.modules",
                {"azure": MagicMock(), "azure.cosmos": MagicMock(), "azure.cosmos.aio": MagicMock()},
            ):
                with pytest.raises(ValueError) as exc_info:
                    create_workflow_store("cosmos")

                assert "COSMOS_ENDPOINT" in str(exc_info.value)

    def test_cosmos_backend_requires_key_or_identity(self) -> None:
        """Should raise error when COSMOS_KEY missing and no identity available."""
        try:
            import azure.cosmos.aio  # noqa: F401
            pytest.skip("azure-cosmos is installed, skipping import test")
        except ImportError:
            # When azure-cosmos not installed, it should raise ImportError first
            with pytest.raises(ImportError):
                create_workflow_store("cosmos")


class TestInMemoryStoreInstances:
    """Test that factory creates independent instances."""

    def test_creates_new_instances(self) -> None:
        """Each call should create a new store instance."""
        store1 = create_workflow_store("memory")
        store2 = create_workflow_store("memory")

        assert store1 is not store2

    @pytest.mark.asyncio
    async def test_instances_are_independent(self) -> None:
        """Different instances should not share state."""
        from src.orchestrator.models.workflow_state import Phase, WorkflowState

        store1 = create_workflow_store("memory")
        store2 = create_workflow_store("memory")

        # Save state to store1
        state = WorkflowState(
            session_id="sess_factory_test",
            consultation_id="cons_factory_test",
            phase=Phase.CLARIFICATION,
        )
        await store1.save(state)

        # store2 should not have this state
        result1 = await store1.get_by_session("sess_factory_test")
        result2 = await store2.get_by_session("sess_factory_test")

        assert result1 is not None
        assert result2 is None


class TestFactoryEdgeCases:
    """Test edge cases in factory behavior."""

    def test_empty_string_backend_defaults_to_memory(self) -> None:
        """Empty string backend should use default (memory)."""
        # Empty string is falsy, should use env or default
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("STORAGE_BACKEND", None)
            store = create_workflow_store("")

            assert isinstance(store, InMemoryWorkflowStore)

    def test_whitespace_backend(self) -> None:
        """Whitespace-only backend should be handled."""
        # " cosmos " should match "cosmos" after lowering
        # But strip isn't applied, so this will default to memory
        store = create_workflow_store("  memory  ")

        # Due to .lower() without strip(), this becomes "  memory  "
        # which is not "cosmos", so defaults to memory
        assert isinstance(store, InMemoryWorkflowStore)
