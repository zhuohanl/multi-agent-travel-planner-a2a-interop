"""Shared pytest fixtures for all tests."""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_env_vars():
    """Fixture to set required environment variables for testing."""
    env_vars = {
        "SERVER_URL": "localhost",
        "POI_SEARCH_AGENT_PORT": "10008",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_DEPLOYMENT_NAME": "test-deployment",
        "AZURE_OPENAI_API_VERSION": "2024-02-01",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


@pytest.fixture
def mock_httpx_client():
    """Fixture to create a mock httpx AsyncClient."""
    client = AsyncMock()
    client.aclose = AsyncMock()
    return client


@pytest.fixture
def mock_agent_executor():
    """Fixture to create a mock agent executor."""
    executor = MagicMock()
    executor.execute = AsyncMock(return_value="Test response")
    return executor
