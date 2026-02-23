"""
Unit tests for A2AClientWrapper.

Tests the history injection functionality per design doc Agent Communication section.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.shared.a2a.client_wrapper import A2AClientWrapper, A2AResponse


class AsyncIteratorMock:
    """Mock async iterator for testing streaming responses."""

    def __init__(self, items: list):
        self.items = items
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.items):
            raise StopAsyncIteration
        item = self.items[self.index]
        self.index += 1
        return item


class TestSendMessageHistoryInjection:
    """Tests for history parameter in send_message()."""

    @pytest.fixture
    def mock_a2a_client(self) -> MagicMock:
        """Create a mock A2A client."""
        client = MagicMock()
        return client

    @pytest.fixture
    def wrapper(self) -> A2AClientWrapper:
        """Create a wrapper with mocked httpx client."""
        mock_httpx = MagicMock()
        return A2AClientWrapper(httpx_client=mock_httpx)

    @pytest.mark.asyncio
    async def test_send_message_without_history(self, wrapper: A2AClientWrapper) -> None:
        """Test that send_message works without history parameter.

        Verifies backward compatibility: existing callers that don't
        provide history should work as before.
        """
        # Mock the internal methods
        with patch.object(wrapper, "_get_a2a_client") as mock_get_client:
            with patch.object(wrapper, "_send_streaming_message") as mock_send:
                mock_send.return_value = A2AResponse(
                    text="Hello",
                    context_id="ctx_001",
                    is_complete=True,
                )

                response = await wrapper.send_message(
                    agent_url="http://localhost:10007",
                    message="Plan a trip",
                )

                # Verify _send_streaming_message was called without history
                mock_send.assert_called_once()
                call_kwargs = mock_send.call_args.kwargs
                assert call_kwargs.get("history") is None

    @pytest.mark.asyncio
    async def test_send_message_with_history_injects_metadata(
        self, wrapper: A2AClientWrapper
    ) -> None:
        """Test that history is passed through to _send_streaming_message.

        Per design doc Agent Communication: history is always sent for reliability.
        """
        history = [
            {"role": "user", "content": "Plan a trip"},
            {"role": "assistant", "content": "Where would you like to go?"},
        ]

        with patch.object(wrapper, "_get_a2a_client") as mock_get_client:
            with patch.object(wrapper, "_send_streaming_message") as mock_send:
                mock_send.return_value = A2AResponse(
                    text="Great choice!",
                    context_id="ctx_001",
                    is_complete=False,
                    requires_input=True,
                )

                response = await wrapper.send_message(
                    agent_url="http://localhost:10007",
                    message="To Tokyo",
                    context_id="ctx_001",
                    history=history,
                )

                # Verify history was passed to internal method
                mock_send.assert_called_once()
                call_kwargs = mock_send.call_args.kwargs
                assert call_kwargs.get("history") == history

    @pytest.mark.asyncio
    async def test_history_uses_camel_case_keys(self, wrapper: A2AClientWrapper) -> None:
        """Test that history in metadata uses camelCase keys per A2A spec.

        Per design doc Agent Communication: metadata uses camelCase convention.
        The key "history" is already lowercase (same in camelCase), but this test
        verifies the metadata structure is correct.
        """
        mock_client = MagicMock()
        mock_client.send_message_streaming = MagicMock(return_value=AsyncIteratorMock([]))

        history = [
            {"role": "user", "content": "Plan a trip"},
            {"role": "assistant", "content": "Where would you like to go?"},
        ]

        with patch.object(wrapper, "_get_a2a_client", return_value=mock_client):
            try:
                await wrapper.send_message(
                    agent_url="http://localhost:10007",
                    message="To Tokyo",
                    history=history,
                )
            except Exception:
                pass  # We're testing payload construction

        # Verify the request payload structure
        mock_client.send_message_streaming.assert_called_once()
        call_args = mock_client.send_message_streaming.call_args
        request = call_args[0][0]

        params_dict = request.params.model_dump()
        message = params_dict.get("message", {})
        metadata = message.get("metadata", {})

        # Verify "history" key exists in metadata (lowercase, per A2A spec)
        assert "history" in metadata
        assert metadata["history"] == history

    @pytest.mark.asyncio
    async def test_empty_history_list_still_injects_metadata(
        self, wrapper: A2AClientWrapper
    ) -> None:
        """Test that empty history list is still injected (not treated as None)."""
        history: list[dict] = []

        with patch.object(wrapper, "_get_a2a_client") as mock_get_client:
            with patch.object(wrapper, "_send_streaming_message") as mock_send:
                mock_send.return_value = A2AResponse(
                    text="Starting fresh",
                    context_id="ctx_001",
                    is_complete=False,
                )

                response = await wrapper.send_message(
                    agent_url="http://localhost:10007",
                    message="Plan a trip",
                    history=history,
                )

                # Empty list should be passed (not None)
                mock_send.assert_called_once()
                call_kwargs = mock_send.call_args.kwargs
                assert call_kwargs.get("history") == []


class TestHistorySeqParameter:
    """Tests for history_seq parameter in send_message().

    Per design doc Agent Communication: sequence-based divergence detection
    is simpler than ID-based. The client sends history_seq, allowing agents
    to detect cache drift by comparing with their last_seen_seq.
    """

    @pytest.fixture
    def wrapper(self) -> A2AClientWrapper:
        """Create a wrapper with mocked httpx client."""
        mock_httpx = MagicMock()
        return A2AClientWrapper(httpx_client=mock_httpx)

    @pytest.mark.asyncio
    async def test_send_message_with_history_seq(self, wrapper: A2AClientWrapper) -> None:
        """Test that history_seq is passed through to _send_streaming_message.

        Per design doc: history_seq is included in metadata for divergence detection.
        """
        history = [
            {"role": "user", "content": "Plan a trip"},
            {"role": "assistant", "content": "Where would you like to go?"},
        ]

        with patch.object(wrapper, "_get_a2a_client") as mock_get_client:
            with patch.object(wrapper, "_send_streaming_message") as mock_send:
                mock_send.return_value = A2AResponse(
                    text="Great choice!",
                    context_id="ctx_001",
                    is_complete=False,
                    requires_input=True,
                )

                response = await wrapper.send_message(
                    agent_url="http://localhost:10007",
                    message="To Tokyo",
                    context_id="ctx_001",
                    history=history,
                    history_seq=5,
                )

                # Verify history_seq was passed to internal method
                mock_send.assert_called_once()
                call_kwargs = mock_send.call_args.kwargs
                assert call_kwargs.get("history_seq") == 5

    @pytest.mark.asyncio
    async def test_history_seq_default_zero(self, wrapper: A2AClientWrapper) -> None:
        """Test that history_seq defaults to 0 when not provided."""
        with patch.object(wrapper, "_get_a2a_client") as mock_get_client:
            with patch.object(wrapper, "_send_streaming_message") as mock_send:
                mock_send.return_value = A2AResponse(
                    text="Hello",
                    context_id="ctx_001",
                    is_complete=True,
                )

                response = await wrapper.send_message(
                    agent_url="http://localhost:10007",
                    message="Plan a trip",
                )

                # Verify history_seq defaults to 0
                mock_send.assert_called_once()
                call_kwargs = mock_send.call_args.kwargs
                assert call_kwargs.get("history_seq") == 0

    @pytest.mark.asyncio
    async def test_history_seq_camel_case_in_metadata(self) -> None:
        """Test that historySeq uses camelCase in metadata per A2A spec.

        Per design doc: metadata uses camelCase convention (historySeq, not history_seq).
        """
        wrapper = A2AClientWrapper(httpx_client=MagicMock())

        history = [
            {"role": "user", "content": "Plan a trip"},
        ]

        mock_client = MagicMock()
        mock_client.send_message_streaming = MagicMock(return_value=AsyncIteratorMock([]))

        with patch.object(wrapper, "_get_a2a_client", return_value=mock_client):
            try:
                await wrapper.send_message(
                    agent_url="http://localhost:10007",
                    message="To Tokyo",
                    history=history,
                    history_seq=42,
                )
            except Exception:
                pass  # We're testing payload construction

        # Verify the request payload structure
        mock_client.send_message_streaming.assert_called_once()
        call_args = mock_client.send_message_streaming.call_args
        request = call_args[0][0]

        params_dict = request.params.model_dump()
        message = params_dict.get("message", {})
        metadata = message.get("metadata", {})

        # Verify "historySeq" key exists in metadata (camelCase per A2A spec)
        assert "historySeq" in metadata
        assert metadata["historySeq"] == 42

    @pytest.mark.asyncio
    async def test_history_seq_included_with_history(self) -> None:
        """Test that both history and historySeq are in metadata together.

        Per design doc: metadata structure is { history: [...], historySeq: N }
        """
        wrapper = A2AClientWrapper(httpx_client=MagicMock())

        history = [
            {"role": "user", "content": "Plan a trip"},
            {"role": "assistant", "content": "Where to?"},
        ]

        mock_client = MagicMock()
        mock_client.send_message_streaming = MagicMock(return_value=AsyncIteratorMock([]))

        with patch.object(wrapper, "_get_a2a_client", return_value=mock_client):
            try:
                await wrapper.send_message(
                    agent_url="http://localhost:10007",
                    message="To Tokyo",
                    history=history,
                    history_seq=3,
                )
            except Exception:
                pass

        mock_client.send_message_streaming.assert_called_once()
        call_args = mock_client.send_message_streaming.call_args
        request = call_args[0][0]

        params_dict = request.params.model_dump()
        message = params_dict.get("message", {})
        metadata = message.get("metadata", {})

        # Verify both keys are present
        assert "history" in metadata
        assert "historySeq" in metadata
        assert metadata["history"] == history
        assert metadata["historySeq"] == 3


class TestRequiresInputField:
    """Tests for requires_input field in A2AResponse.

    Per design doc Response Formats: the orchestrator needs to know when an agent
    requires more user input vs when it has completed. This field exposes the
    A2A status.state in a convenient boolean.
    """

    @pytest.fixture
    def wrapper(self) -> A2AClientWrapper:
        """Create a wrapper with mocked httpx client."""
        mock_httpx = MagicMock()
        return A2AClientWrapper(httpx_client=mock_httpx)

    @pytest.mark.asyncio
    async def test_requires_input_true_for_input_required_state(
        self, wrapper: A2AClientWrapper
    ) -> None:
        """Test that requires_input is True when status.state == 'input_required'.

        Per design doc: input_required state indicates the agent needs more user input.
        """
        # Create a mock response with input_required state
        mock_chunk = MagicMock()
        mock_chunk.model_dump.return_value = {
            "result": {
                "contextId": "ctx_001",
                "status": {
                    "state": "input_required",
                    "message": {
                        "parts": [{"text": "What dates are you traveling?"}]
                    }
                }
            }
        }

        mock_client = MagicMock()
        mock_client.send_message_streaming = MagicMock(
            return_value=AsyncIteratorMock([mock_chunk])
        )

        with patch.object(wrapper, "_get_a2a_client", return_value=mock_client):
            response = await wrapper.send_message(
                agent_url="http://localhost:10007",
                message="Plan a trip",
            )

        assert response.requires_input is True
        assert response.is_complete is False
        assert response.text == "What dates are you traveling?"

    @pytest.mark.asyncio
    async def test_requires_input_false_for_completed_state(
        self, wrapper: A2AClientWrapper
    ) -> None:
        """Test that requires_input is False when status.state == 'completed'.

        Per design doc: completed state indicates the agent has finished processing.
        """
        mock_chunk = MagicMock()
        mock_chunk.model_dump.return_value = {
            "result": {
                "contextId": "ctx_001",
                "status": {
                    "state": "completed",
                    "message": {
                        "parts": [{"text": "Your trip is planned!"}]
                    }
                }
            }
        }

        mock_client = MagicMock()
        mock_client.send_message_streaming = MagicMock(
            return_value=AsyncIteratorMock([mock_chunk])
        )

        with patch.object(wrapper, "_get_a2a_client", return_value=mock_client):
            response = await wrapper.send_message(
                agent_url="http://localhost:10007",
                message="Plan a trip",
            )

        assert response.requires_input is False
        assert response.is_complete is True
        assert response.text == "Your trip is planned!"

    @pytest.mark.asyncio
    async def test_requires_input_false_for_working_state(
        self, wrapper: A2AClientWrapper
    ) -> None:
        """Test that requires_input is False for non-input_required states."""
        mock_chunk = MagicMock()
        mock_chunk.model_dump.return_value = {
            "result": {
                "contextId": "ctx_001",
                "status": {
                    "state": "working",
                    "message": {
                        "parts": [{"text": "Processing..."}]
                    }
                }
            }
        }

        mock_client = MagicMock()
        mock_client.send_message_streaming = MagicMock(
            return_value=AsyncIteratorMock([mock_chunk])
        )

        with patch.object(wrapper, "_get_a2a_client", return_value=mock_client):
            response = await wrapper.send_message(
                agent_url="http://localhost:10007",
                message="Plan a trip",
            )

        assert response.requires_input is False
        assert response.is_complete is False


class TestLastSeenSeqField:
    """Tests for last_seen_seq field in A2AResponse.

    Per design doc Agent Communication: agents echo back lastSeenSeq in response
    metadata for divergence detection. The orchestrator extracts this to track
    the agent's sequence position.
    """

    @pytest.fixture
    def wrapper(self) -> A2AClientWrapper:
        """Create a wrapper with mocked httpx client."""
        mock_httpx = MagicMock()
        return A2AClientWrapper(httpx_client=mock_httpx)

    @pytest.mark.asyncio
    async def test_last_seen_seq_extracted_from_metadata(
        self, wrapper: A2AClientWrapper
    ) -> None:
        """Test that lastSeenSeq is extracted from response metadata.

        Per design doc: agents echo back lastSeenSeq for client tracking.
        """
        mock_chunk = MagicMock()
        mock_chunk.model_dump.return_value = {
            "result": {
                "contextId": "ctx_001",
                "metadata": {"lastSeenSeq": 5},
                "status": {
                    "state": "completed",
                    "message": {"parts": [{"text": "Done"}]}
                }
            }
        }

        mock_client = MagicMock()
        mock_client.send_message_streaming = MagicMock(
            return_value=AsyncIteratorMock([mock_chunk])
        )

        with patch.object(wrapper, "_get_a2a_client", return_value=mock_client):
            response = await wrapper.send_message(
                agent_url="http://localhost:10007",
                message="Plan a trip",
            )

        assert response.last_seen_seq == 5

    @pytest.mark.asyncio
    async def test_last_seen_seq_none_when_not_in_metadata(
        self, wrapper: A2AClientWrapper
    ) -> None:
        """Test that last_seen_seq is None when metadata doesn't contain lastSeenSeq."""
        mock_chunk = MagicMock()
        mock_chunk.model_dump.return_value = {
            "result": {
                "contextId": "ctx_001",
                "status": {
                    "state": "completed",
                    "message": {"parts": [{"text": "Done"}]}
                }
            }
        }

        mock_client = MagicMock()
        mock_client.send_message_streaming = MagicMock(
            return_value=AsyncIteratorMock([mock_chunk])
        )

        with patch.object(wrapper, "_get_a2a_client", return_value=mock_client):
            response = await wrapper.send_message(
                agent_url="http://localhost:10007",
                message="Plan a trip",
            )

        assert response.last_seen_seq is None

    @pytest.mark.asyncio
    async def test_last_seen_seq_zero_is_valid(
        self, wrapper: A2AClientWrapper
    ) -> None:
        """Test that lastSeenSeq of 0 is correctly extracted (not treated as None)."""
        mock_chunk = MagicMock()
        mock_chunk.model_dump.return_value = {
            "result": {
                "contextId": "ctx_001",
                "metadata": {"lastSeenSeq": 0},
                "status": {
                    "state": "completed",
                    "message": {"parts": [{"text": "First message"}]}
                }
            }
        }

        mock_client = MagicMock()
        mock_client.send_message_streaming = MagicMock(
            return_value=AsyncIteratorMock([mock_chunk])
        )

        with patch.object(wrapper, "_get_a2a_client", return_value=mock_client):
            response = await wrapper.send_message(
                agent_url="http://localhost:10007",
                message="Hello",
            )

        assert response.last_seen_seq == 0

    @pytest.mark.asyncio
    async def test_last_seen_seq_ignores_invalid_type(
        self, wrapper: A2AClientWrapper
    ) -> None:
        """Test that non-integer lastSeenSeq values are ignored."""
        mock_chunk = MagicMock()
        mock_chunk.model_dump.return_value = {
            "result": {
                "contextId": "ctx_001",
                "metadata": {"lastSeenSeq": "not_an_int"},
                "status": {
                    "state": "completed",
                    "message": {"parts": [{"text": "Done"}]}
                }
            }
        }

        mock_client = MagicMock()
        mock_client.send_message_streaming = MagicMock(
            return_value=AsyncIteratorMock([mock_chunk])
        )

        with patch.object(wrapper, "_get_a2a_client", return_value=mock_client):
            response = await wrapper.send_message(
                agent_url="http://localhost:10007",
                message="Plan a trip",
            )

        assert response.last_seen_seq is None


class TestSendStreamingMessageMetadata:
    """Tests for metadata construction in _send_streaming_message."""

    @pytest.fixture
    def wrapper(self) -> A2AClientWrapper:
        """Create a wrapper with mocked httpx client."""
        mock_httpx = MagicMock()
        return A2AClientWrapper(httpx_client=mock_httpx)

    @pytest.mark.asyncio
    async def test_metadata_structure_with_history(self) -> None:
        """Test that metadata contains history when provided.

        Per design doc: message.metadata is the extension point for custom data.
        """
        wrapper = A2AClientWrapper(httpx_client=MagicMock())

        history = [
            {"role": "user", "content": "Plan a trip"},
            {"role": "assistant", "content": "Where would you like to go?"},
        ]

        # Mock the A2A client to capture the request payload
        mock_client = MagicMock()
        mock_client.send_message_streaming = MagicMock(return_value=AsyncIteratorMock([]))

        with patch.object(wrapper, "_get_a2a_client", return_value=mock_client):
            try:
                await wrapper.send_message(
                    agent_url="http://localhost:10007",
                    message="To Tokyo",
                    history=history,
                )
            except Exception:
                pass  # We're testing payload construction, not response handling

        # Verify send_message_streaming was called
        mock_client.send_message_streaming.assert_called_once()

        # Get the actual request that was passed
        call_args = mock_client.send_message_streaming.call_args
        request = call_args[0][0]  # First positional argument

        # The request should have params with message containing metadata
        params_dict = request.params.model_dump()
        message = params_dict.get("message", {})
        metadata = message.get("metadata", {})

        assert "history" in metadata
        assert metadata["history"] == history

    @pytest.mark.asyncio
    async def test_metadata_not_modified_without_history(self) -> None:
        """Test that metadata is not added when history is None.

        Ensures backward compatibility with existing callers.
        """
        wrapper = A2AClientWrapper(httpx_client=MagicMock())

        mock_client = MagicMock()
        mock_client.send_message_streaming = MagicMock(return_value=AsyncIteratorMock([]))

        with patch.object(wrapper, "_get_a2a_client", return_value=mock_client):
            try:
                await wrapper.send_message(
                    agent_url="http://localhost:10007",
                    message="Plan a trip",
                    # No history provided
                )
            except Exception:
                pass

        # Verify the request payload
        mock_client.send_message_streaming.assert_called_once()
        call_args = mock_client.send_message_streaming.call_args
        request = call_args[0][0]

        params_dict = request.params.model_dump()
        message = params_dict.get("message", {})

        # Metadata should not be present (or not contain history key)
        metadata = message.get("metadata")
        if metadata is not None:
            assert "history" not in metadata
