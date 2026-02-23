"""
Cosmos DB container setup for the orchestrator.

This module creates and configures the nine Cosmos DB containers required by the
orchestrator as defined in the design document. Each container has specific
partition keys and TTL policies.

Usage:
    # From command line:
    uv run python -m infrastructure.cosmos_setup

    # From code:
    from infrastructure.cosmos_setup import create_containers_if_not_exist
    await create_containers_if_not_exist(cosmos_client, database_name)

Environment Variables:
    COSMOS_DB_CONNECTION_STRING: Azure Cosmos DB connection string
    COSMOS_DB_DATABASE_NAME: Database name (default: "travel_planner")

Dependencies:
    Requires azure-cosmos package for actual Cosmos DB operations.
    Install with: uv add azure-cosmos
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Import azure.cosmos only at type-checking time or when needed at runtime
# This allows the module to be imported for testing without the SDK installed
if TYPE_CHECKING:
    from azure.cosmos.aio import CosmosClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContainerConfig:
    """Configuration for a Cosmos DB container."""

    name: str
    partition_key: str
    ttl_seconds: int | None  # None means TTL is dynamic (set per-document)
    ttl_type: Literal["fixed", "dynamic"]

    @property
    def has_ttl(self) -> bool:
        """Check if container has TTL configured."""
        return self.ttl_seconds is not None or self.ttl_type == "dynamic"


# TTL constants in seconds
SEVEN_DAYS_TTL = 7 * 24 * 60 * 60  # 604800 seconds
TWENTY_FOUR_HOURS_TTL = 24 * 60 * 60  # 86400 seconds

# Authoritative Container List from design document
# See: docs/a2a-orchestrator-design.md "Authoritative Container List"
CONTAINER_CONFIGS: list[ContainerConfig] = [
    # Core workflow containers
    ContainerConfig(
        name="workflow_states",
        partition_key="/session_id",
        ttl_seconds=SEVEN_DAYS_TTL,
        ttl_type="fixed",
    ),
    ContainerConfig(
        name="consultation_index",
        partition_key="/consultation_id",
        ttl_seconds=SEVEN_DAYS_TTL,
        ttl_type="fixed",
    ),
    ContainerConfig(
        name="consultation_summaries",
        partition_key="/consultation_id",
        ttl_seconds=None,  # Dynamic: trip_end + 30 days (set per-document)
        ttl_type="dynamic",
    ),
    # Itinerary and booking containers
    ContainerConfig(
        name="itineraries",
        partition_key="/itinerary_id",
        ttl_seconds=None,  # Dynamic: trip_end + 30 days (set per-document)
        ttl_type="dynamic",
    ),
    ContainerConfig(
        name="bookings",
        partition_key="/booking_id",
        ttl_seconds=None,  # Dynamic: trip_end + 30 days (set per-document)
        ttl_type="dynamic",
    ),
    ContainerConfig(
        name="booking_index",
        partition_key="/booking_id",
        ttl_seconds=None,  # Dynamic: trip_end + 30 days (set per-document)
        ttl_type="dynamic",
    ),
    # Sharding containers for large data
    ContainerConfig(
        name="chat_messages",
        partition_key="/session_id",
        ttl_seconds=SEVEN_DAYS_TTL,
        ttl_type="fixed",
    ),
    ContainerConfig(
        name="discovery_artifacts",
        partition_key="/consultation_id",
        ttl_seconds=SEVEN_DAYS_TTL,
        ttl_type="fixed",
    ),
    # Job tracking
    ContainerConfig(
        name="discovery_jobs",
        partition_key="/consultation_id",
        ttl_seconds=TWENTY_FOUR_HOURS_TTL,
        ttl_type="fixed",
    ),
]


def get_container_config(name: str) -> ContainerConfig | None:
    """Get configuration for a container by name."""
    for config in CONTAINER_CONFIGS:
        if config.name == name:
            return config
    return None


def _get_cosmos_imports() -> tuple[Any, Any]:
    """
    Lazily import azure.cosmos dependencies.

    Returns:
        Tuple of (PartitionKey, CosmosResourceExistsError)

    Raises:
        ImportError: If azure-cosmos package is not installed
    """
    try:
        from azure.cosmos import PartitionKey
        from azure.cosmos.exceptions import CosmosResourceExistsError

        return PartitionKey, CosmosResourceExistsError
    except ImportError as e:
        raise ImportError(
            "azure-cosmos package is required for Cosmos DB operations. "
            "Install it with: uv add azure-cosmos"
        ) from e


async def create_container(
    database: Any,
    config: ContainerConfig,
) -> bool:
    """
    Create a single container if it doesn't exist.

    Args:
        database: Cosmos database client
        config: Container configuration

    Returns:
        True if container was created, False if it already existed
    """
    PartitionKey, CosmosResourceExistsError = _get_cosmos_imports()

    # For containers with dynamic TTL, we enable TTL at container level
    # with default of -1 (no default TTL), so documents can set their own TTL
    if config.ttl_type == "dynamic":
        default_ttl = -1  # Enable TTL but no default (document must specify)
    else:
        default_ttl = config.ttl_seconds

    try:
        await database.create_container(
            id=config.name,
            partition_key=PartitionKey(path=config.partition_key),
            default_time_to_live=default_ttl,
        )
        logger.info(f"Created container: {config.name}")
        return True
    except CosmosResourceExistsError:
        logger.info(f"Container already exists: {config.name}")
        return False


async def create_containers_if_not_exist(
    cosmos_client: CosmosClient,
    database_name: str,
) -> dict[str, bool]:
    """
    Create all required containers if they don't exist.

    This function is idempotent - safe to run multiple times.

    Args:
        cosmos_client: Async Cosmos DB client
        database_name: Name of the database

    Returns:
        Dictionary mapping container names to whether they were created (True)
        or already existed (False)
    """
    database = cosmos_client.get_database_client(database_name)
    results = {}

    for config in CONTAINER_CONFIGS:
        created = await create_container(database, config)
        results[config.name] = created

    return results


async def verify_containers(
    cosmos_client: CosmosClient,
    database_name: str,
) -> dict[str, bool]:
    """
    Verify all required containers exist.

    Args:
        cosmos_client: Async Cosmos DB client
        database_name: Name of the database

    Returns:
        Dictionary mapping container names to whether they exist
    """
    database = cosmos_client.get_database_client(database_name)
    results = {}

    for config in CONTAINER_CONFIGS:
        try:
            # Try to read container properties to verify it exists
            container = database.get_container_client(config.name)
            await container.read()
            results[config.name] = True
        except Exception:
            results[config.name] = False

    return results


def get_cosmos_client_from_env() -> tuple[CosmosClient, str]:
    """
    Create a Cosmos DB client from environment variables.

    Environment Variables:
        COSMOS_DB_CONNECTION_STRING: Required. Azure Cosmos DB connection string.
        COSMOS_DB_DATABASE_NAME: Optional. Database name (default: "travel_planner").

    Returns:
        Tuple of (CosmosClient, database_name)

    Raises:
        ValueError: If COSMOS_DB_CONNECTION_STRING is not set
        ImportError: If azure-cosmos package is not installed
    """
    try:
        from azure.cosmos.aio import CosmosClient
    except ImportError as e:
        raise ImportError(
            "azure-cosmos package is required for Cosmos DB operations. "
            "Install it with: uv add azure-cosmos"
        ) from e

    connection_string = os.environ.get("COSMOS_DB_CONNECTION_STRING")
    if not connection_string:
        raise ValueError(
            "COSMOS_DB_CONNECTION_STRING environment variable is required. "
            "Set it to your Azure Cosmos DB connection string."
        )

    database_name = os.environ.get("COSMOS_DB_DATABASE_NAME", "travel_planner")
    client = CosmosClient.from_connection_string(connection_string)

    return client, database_name


async def main() -> None:
    """
    Main entry point for container setup.

    Creates all required Cosmos DB containers with proper partition keys and TTLs.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        client, database_name = get_cosmos_client_from_env()
    except ValueError as e:
        logger.error(str(e))
        logger.info("\nTo set up Cosmos DB:")
        logger.info("1. Create an Azure Cosmos DB account (NoSQL API)")
        logger.info("2. Create a database named 'travel_planner' (or your choice)")
        logger.info("3. Get the connection string from Azure Portal")
        logger.info("4. Set the environment variable:")
        logger.info('   export COSMOS_DB_CONNECTION_STRING="your-connection-string"')
        return

    async with client:
        logger.info(f"Setting up Cosmos DB containers in database: {database_name}")
        logger.info(f"Creating {len(CONTAINER_CONFIGS)} containers...")

        results = await create_containers_if_not_exist(client, database_name)

        created_count = sum(1 for created in results.values() if created)
        existing_count = len(results) - created_count

        logger.info(f"\nSetup complete:")
        logger.info(f"  Created: {created_count} containers")
        logger.info(f"  Already existed: {existing_count} containers")

        # Print summary table
        logger.info("\nContainer Summary:")
        logger.info("-" * 70)
        logger.info(f"{'Container':<25} {'Partition Key':<20} {'TTL':<15} {'Status':<10}")
        logger.info("-" * 70)
        for config in CONTAINER_CONFIGS:
            ttl_str = (
                f"{config.ttl_seconds}s"
                if config.ttl_seconds
                else "dynamic"
            )
            status = "created" if results[config.name] else "exists"
            logger.info(
                f"{config.name:<25} {config.partition_key:<20} {ttl_str:<15} {status:<10}"
            )


if __name__ == "__main__":
    asyncio.run(main())
