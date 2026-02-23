"""Unit tests for Cosmos DB setup."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infrastructure.cosmos_setup import (
    CONTAINER_CONFIGS,
    ContainerConfig,
    SEVEN_DAYS_TTL,
    TWENTY_FOUR_HOURS_TTL,
    get_container_config,
)

# These functions require azure.cosmos to be installed or mocked
# We'll import them with mocked azure.cosmos module
@pytest.fixture(autouse=True)
def mock_azure_cosmos():
    """Mock azure.cosmos module for tests."""
    # Create mock modules
    mock_cosmos = MagicMock()
    mock_cosmos_aio = MagicMock()
    mock_cosmos_exceptions = MagicMock()

    # Create exception class
    class MockCosmosResourceExistsError(Exception):
        pass

    mock_cosmos_exceptions.CosmosResourceExistsError = MockCosmosResourceExistsError
    mock_cosmos.exceptions = mock_cosmos_exceptions
    mock_cosmos.PartitionKey = MagicMock()

    # Inject mock modules
    with patch.dict(sys.modules, {
        'azure': MagicMock(),
        'azure.cosmos': mock_cosmos,
        'azure.cosmos.aio': mock_cosmos_aio,
        'azure.cosmos.exceptions': mock_cosmos_exceptions,
    }):
        yield mock_cosmos, mock_cosmos_aio, mock_cosmos_exceptions


# Import functions that need azure.cosmos after mocking
def _get_cosmos_functions():
    """Get functions that require azure.cosmos."""
    from infrastructure.cosmos_setup import (
        create_container,
        create_containers_if_not_exist,
        get_cosmos_client_from_env,
        verify_containers,
    )
    return create_container, create_containers_if_not_exist, get_cosmos_client_from_env, verify_containers


class TestContainerConfig:
    """Tests for ContainerConfig dataclass."""

    def test_container_config_has_partition_key(self) -> None:
        """All container configs must have partition keys starting with '/'."""
        for config in CONTAINER_CONFIGS:
            assert config.partition_key.startswith("/"), (
                f"Container {config.name} partition key must start with '/'"
            )
            assert len(config.partition_key) > 1, (
                f"Container {config.name} must have a valid partition key path"
            )

    def test_container_config_has_ttl(self) -> None:
        """All containers must have TTL configured (fixed or dynamic)."""
        for config in CONTAINER_CONFIGS:
            assert config.has_ttl, (
                f"Container {config.name} must have TTL configured"
            )
            assert config.ttl_type in ("fixed", "dynamic"), (
                f"Container {config.name} TTL type must be 'fixed' or 'dynamic'"
            )
            # Fixed TTL containers must have ttl_seconds set
            if config.ttl_type == "fixed":
                assert config.ttl_seconds is not None, (
                    f"Container {config.name} with fixed TTL must have ttl_seconds"
                )
                assert config.ttl_seconds > 0, (
                    f"Container {config.name} TTL must be positive"
                )

    def test_required_containers_present(self) -> None:
        """Verify all 9 required containers are configured."""
        container_names = {config.name for config in CONTAINER_CONFIGS}
        required_containers = {
            "workflow_states",
            "consultation_index",
            "consultation_summaries",
            "itineraries",
            "bookings",
            "booking_index",
            "chat_messages",
            "discovery_artifacts",
            "discovery_jobs",
        }
        assert container_names == required_containers, (
            f"Missing containers: {required_containers - container_names}"
        )

    def test_workflow_states_config(self) -> None:
        """Verify workflow_states container configuration."""
        config = get_container_config("workflow_states")
        assert config is not None
        assert config.partition_key == "/session_id"
        assert config.ttl_seconds == SEVEN_DAYS_TTL
        assert config.ttl_type == "fixed"

    def test_consultation_index_config(self) -> None:
        """Verify consultation_index container configuration."""
        config = get_container_config("consultation_index")
        assert config is not None
        assert config.partition_key == "/consultation_id"
        assert config.ttl_seconds == SEVEN_DAYS_TTL
        assert config.ttl_type == "fixed"

    def test_consultation_summaries_config(self) -> None:
        """Verify consultation_summaries has dynamic TTL (trip_end + 30 days)."""
        config = get_container_config("consultation_summaries")
        assert config is not None
        assert config.partition_key == "/consultation_id"
        assert config.ttl_type == "dynamic"
        assert config.ttl_seconds is None  # Dynamic TTL set per-document

    def test_itineraries_config(self) -> None:
        """Verify itineraries has dynamic TTL (trip_end + 30 days)."""
        config = get_container_config("itineraries")
        assert config is not None
        assert config.partition_key == "/itinerary_id"
        assert config.ttl_type == "dynamic"

    def test_bookings_config(self) -> None:
        """Verify bookings has dynamic TTL (trip_end + 30 days)."""
        config = get_container_config("bookings")
        assert config is not None
        assert config.partition_key == "/booking_id"
        assert config.ttl_type == "dynamic"

    def test_booking_index_config(self) -> None:
        """Verify booking_index has dynamic TTL (trip_end + 30 days)."""
        config = get_container_config("booking_index")
        assert config is not None
        assert config.partition_key == "/booking_id"
        assert config.ttl_type == "dynamic"

    def test_chat_messages_config(self) -> None:
        """Verify chat_messages container configuration."""
        config = get_container_config("chat_messages")
        assert config is not None
        assert config.partition_key == "/session_id"
        assert config.ttl_seconds == SEVEN_DAYS_TTL
        assert config.ttl_type == "fixed"

    def test_discovery_artifacts_config(self) -> None:
        """Verify discovery_artifacts container configuration."""
        config = get_container_config("discovery_artifacts")
        assert config is not None
        assert config.partition_key == "/consultation_id"
        assert config.ttl_seconds == SEVEN_DAYS_TTL
        assert config.ttl_type == "fixed"

    def test_discovery_jobs_config(self) -> None:
        """Verify discovery_jobs container configuration (24h TTL)."""
        config = get_container_config("discovery_jobs")
        assert config is not None
        assert config.partition_key == "/consultation_id"
        assert config.ttl_seconds == TWENTY_FOUR_HOURS_TTL
        assert config.ttl_type == "fixed"

    def test_get_container_config_not_found(self) -> None:
        """get_container_config returns None for unknown containers."""
        assert get_container_config("unknown_container") is None


class TestCreateContainer:
    """Tests for container creation."""

    @pytest.mark.asyncio
    async def test_create_container_new(self, mock_azure_cosmos) -> None:
        """Successfully creates a new container."""
        mock_cosmos, mock_cosmos_aio, mock_exceptions = mock_azure_cosmos

        # Import after mock is set up
        from infrastructure.cosmos_setup import create_container

        mock_database = MagicMock()
        mock_database.create_container = AsyncMock()

        config = ContainerConfig(
            name="test_container",
            partition_key="/test_id",
            ttl_seconds=3600,
            ttl_type="fixed",
        )

        result = await create_container(mock_database, config)

        assert result is True
        mock_database.create_container.assert_called_once()
        call_kwargs = mock_database.create_container.call_args.kwargs
        assert call_kwargs["id"] == "test_container"
        assert call_kwargs["default_time_to_live"] == 3600

    @pytest.mark.asyncio
    async def test_create_container_already_exists(self, mock_azure_cosmos) -> None:
        """Returns False when container already exists."""
        mock_cosmos, mock_cosmos_aio, mock_exceptions = mock_azure_cosmos

        from infrastructure.cosmos_setup import create_container

        mock_database = MagicMock()
        mock_database.create_container = AsyncMock(
            side_effect=mock_exceptions.CosmosResourceExistsError("exists")
        )

        config = ContainerConfig(
            name="existing_container",
            partition_key="/id",
            ttl_seconds=3600,
            ttl_type="fixed",
        )

        result = await create_container(mock_database, config)

        assert result is False

    @pytest.mark.asyncio
    async def test_create_container_dynamic_ttl(self, mock_azure_cosmos) -> None:
        """Containers with dynamic TTL get default_time_to_live of -1."""
        from infrastructure.cosmos_setup import create_container

        mock_database = MagicMock()
        mock_database.create_container = AsyncMock()

        config = ContainerConfig(
            name="dynamic_ttl_container",
            partition_key="/id",
            ttl_seconds=None,
            ttl_type="dynamic",
        )

        await create_container(mock_database, config)

        call_kwargs = mock_database.create_container.call_args.kwargs
        assert call_kwargs["default_time_to_live"] == -1


class TestCreateContainersIfNotExist:
    """Tests for create_containers_if_not_exist."""

    @pytest.mark.asyncio
    async def test_create_containers_idempotent(self, mock_azure_cosmos) -> None:
        """Function is idempotent - returns correct results on repeated calls."""
        mock_cosmos, mock_cosmos_aio, mock_exceptions = mock_azure_cosmos

        from infrastructure.cosmos_setup import create_containers_if_not_exist

        # First call creates all, second call finds all existing
        call_count = 0

        async def mock_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= len(CONTAINER_CONFIGS):
                # First pass: all containers created
                return MagicMock()
            else:
                # Second pass: all containers exist
                raise mock_exceptions.CosmosResourceExistsError("exists")

        mock_database = MagicMock()
        mock_database.create_container = AsyncMock(side_effect=mock_create)

        mock_client = MagicMock()
        mock_client.get_database_client.return_value = mock_database

        # First call - all created
        result1 = await create_containers_if_not_exist(mock_client, "test_db")
        assert all(result1.values())  # All True

        # Reset for second call
        results2 = await create_containers_if_not_exist(mock_client, "test_db")
        assert not any(results2.values())  # All False


class TestVerifyContainers:
    """Tests for verify_containers."""

    @pytest.mark.asyncio
    async def test_verify_all_exist(self, mock_azure_cosmos) -> None:
        """Returns True for all containers when they exist."""
        from infrastructure.cosmos_setup import verify_containers

        mock_container = MagicMock()
        mock_container.read = AsyncMock()

        mock_database = MagicMock()
        mock_database.get_container_client.return_value = mock_container

        mock_client = MagicMock()
        mock_client.get_database_client.return_value = mock_database

        result = await verify_containers(mock_client, "test_db")

        assert len(result) == len(CONTAINER_CONFIGS)
        assert all(result.values())

    @pytest.mark.asyncio
    async def test_verify_some_missing(self, mock_azure_cosmos) -> None:
        """Returns False for containers that don't exist."""
        from infrastructure.cosmos_setup import verify_containers

        call_count = 0

        async def mock_read():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Not found")
            return {}

        mock_container = MagicMock()
        mock_container.read = AsyncMock(side_effect=mock_read)

        mock_database = MagicMock()
        mock_database.get_container_client.return_value = mock_container

        mock_client = MagicMock()
        mock_client.get_database_client.return_value = mock_database

        result = await verify_containers(mock_client, "test_db")

        # First container should be missing, rest should exist
        assert not result[CONTAINER_CONFIGS[0].name]


class TestGetCosmosClientFromEnv:
    """Tests for get_cosmos_client_from_env."""

    def test_missing_connection_string_raises(self, mock_azure_cosmos) -> None:
        """Raises ValueError when connection string is not set."""
        from infrastructure.cosmos_setup import get_cosmos_client_from_env

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError) as exc_info:
                get_cosmos_client_from_env()
            assert "COSMOS_DB_CONNECTION_STRING" in str(exc_info.value)

    def test_default_database_name(self, mock_azure_cosmos) -> None:
        """Uses default database name when not specified."""
        mock_cosmos, mock_cosmos_aio, mock_exceptions = mock_azure_cosmos

        # Set up the mock CosmosClient
        mock_client_instance = MagicMock()
        mock_cosmos_aio.CosmosClient = MagicMock()
        mock_cosmos_aio.CosmosClient.from_connection_string = MagicMock(
            return_value=mock_client_instance
        )

        test_conn_string = (
            "AccountEndpoint=https://test.documents.azure.com:443/;"
            "AccountKey=dGVzdA==;"
        )
        with patch.dict(
            "os.environ",
            {"COSMOS_DB_CONNECTION_STRING": test_conn_string},
            clear=True,
        ):
            from infrastructure.cosmos_setup import get_cosmos_client_from_env
            _, db_name = get_cosmos_client_from_env()
            assert db_name == "travel_planner"

    def test_custom_database_name(self, mock_azure_cosmos) -> None:
        """Uses custom database name when specified."""
        mock_cosmos, mock_cosmos_aio, mock_exceptions = mock_azure_cosmos

        # Set up the mock CosmosClient
        mock_client_instance = MagicMock()
        mock_cosmos_aio.CosmosClient = MagicMock()
        mock_cosmos_aio.CosmosClient.from_connection_string = MagicMock(
            return_value=mock_client_instance
        )

        test_conn_string = (
            "AccountEndpoint=https://test.documents.azure.com:443/;"
            "AccountKey=dGVzdA==;"
        )
        with patch.dict(
            "os.environ",
            {
                "COSMOS_DB_CONNECTION_STRING": test_conn_string,
                "COSMOS_DB_DATABASE_NAME": "custom_db",
            },
            clear=True,
        ):
            from infrastructure.cosmos_setup import get_cosmos_client_from_env
            _, db_name = get_cosmos_client_from_env()
            assert db_name == "custom_db"


class TestTTLConstants:
    """Tests for TTL constant values."""

    def test_seven_days_ttl_value(self) -> None:
        """7 days TTL is 604800 seconds."""
        assert SEVEN_DAYS_TTL == 604800

    def test_twenty_four_hours_ttl_value(self) -> None:
        """24 hours TTL is 86400 seconds."""
        assert TWENTY_FOUR_HOURS_TTL == 86400
