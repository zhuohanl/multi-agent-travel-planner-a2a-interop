"""Unit tests for A2A client wrapper."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import httpx

from src.shared.a2a.client_wrapper import (
    A2AClientWrapper,
    A2AResponse,
    A2AClientError,
    A2AConnectionError,
    A2ATimeoutError,
    DEFAULT_TIMEOUT_SECONDS,
    HAS_TELEMETRY,
)


class TestA2AResponse:
    """Tests for A2AResponse dataclass."""

    def test_default_values(self):
        """Test A2AResponse default values."""
        response = A2AResponse(text="Hello")
        assert response.text == "Hello"
        assert response.context_id is None
        assert response.task_id is None
        assert response.is_complete is False
        assert response.requires_input is False
        assert response.raw_chunks == []

    def test_all_values(self):
        """Test A2AResponse with all values set."""
        chunks = [{"result": {"text": "test"}}]
        response = A2AResponse(
            text="Hello",
            context_id="ctx_123",
            task_id="task_456",
            is_complete=True,
            requires_input=False,
            raw_chunks=chunks,
        )
        assert response.text == "Hello"
        assert response.context_id == "ctx_123"
        assert response.task_id == "task_456"
        assert response.is_complete is True
        assert response.requires_input is False
        assert response.raw_chunks == chunks


class TestA2AClientWrapperExceptions:
    """Tests for A2A exception classes."""

    def test_base_error_inheritance(self):
        """Test A2AClientError is base exception."""
        assert issubclass(A2AConnectionError, A2AClientError)
        assert issubclass(A2ATimeoutError, A2AClientError)

    def test_exception_messages(self):
        """Test exception message preservation."""
        msg = "Connection refused"
        exc = A2AConnectionError(msg)
        assert str(exc) == msg


class TestA2AClientWrapperInit:
    """Tests for A2AClientWrapper initialization."""

    def test_default_timeout(self):
        """Test default timeout value."""
        wrapper = A2AClientWrapper()
        assert wrapper._timeout_seconds == DEFAULT_TIMEOUT_SECONDS
        assert wrapper._timeout_seconds == 30.0

    def test_custom_timeout(self):
        """Test custom timeout value."""
        wrapper = A2AClientWrapper(timeout_seconds=60.0)
        assert wrapper._timeout_seconds == 60.0

    def test_external_client(self):
        """Test initialization with external httpx client."""
        mock_client = MagicMock(spec=httpx.AsyncClient)
        wrapper = A2AClientWrapper(httpx_client=mock_client)
        assert wrapper._external_client is mock_client
        assert wrapper._client is mock_client

    def test_no_client_raises_error(self):
        """Test accessing client without context or external client raises."""
        wrapper = A2AClientWrapper()
        with pytest.raises(RuntimeError, match="must be used as async context manager"):
            _ = wrapper._client


class TestA2AClientWrapperContextManager:
    """Tests for async context manager behavior."""

    @pytest.mark.asyncio
    async def test_creates_internal_client(self):
        """Test context manager creates internal httpx client."""
        wrapper = A2AClientWrapper()
        assert wrapper._internal_client is None

        async with wrapper as w:
            assert w._internal_client is not None
            assert isinstance(w._internal_client, httpx.AsyncClient)

        # Client should be closed after exit
        assert wrapper._internal_client is None

    @pytest.mark.asyncio
    async def test_does_not_create_client_with_external(self):
        """Test context manager doesn't create client when external provided."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        wrapper = A2AClientWrapper(httpx_client=mock_client)

        async with wrapper:
            assert wrapper._internal_client is None

        # External client should not be closed
        mock_client.aclose.assert_not_called()

    @pytest.mark.asyncio
    async def test_clears_caches_on_exit(self):
        """Test caches are cleared on context exit."""
        wrapper = A2AClientWrapper()

        async with wrapper as w:
            # Manually populate caches
            w._agent_card_cache["http://test"] = MagicMock()
            w._a2a_client_cache["http://test"] = MagicMock()

        assert len(wrapper._agent_card_cache) == 0
        assert len(wrapper._a2a_client_cache) == 0


class TestA2AClientWrapperAgentCard:
    """Tests for agent card resolution."""

    @pytest.fixture
    def wrapper_with_client(self):
        """Create wrapper with mock httpx client."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        return A2AClientWrapper(httpx_client=mock_client)

    @pytest.mark.asyncio
    async def test_get_agent_card_caches_result(self, wrapper_with_client):
        """Test agent card is cached after first fetch."""
        mock_card = MagicMock()

        with patch("src.shared.a2a.client_wrapper.A2ACardResolver") as MockResolver:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card.return_value = mock_card
            MockResolver.return_value = mock_resolver

            # First call should fetch
            card1 = await wrapper_with_client._get_agent_card("http://localhost:8000")
            assert card1 is mock_card
            assert MockResolver.call_count == 1

            # Second call should use cache
            card2 = await wrapper_with_client._get_agent_card("http://localhost:8000")
            assert card2 is mock_card
            assert MockResolver.call_count == 1  # Not called again

    @pytest.mark.asyncio
    async def test_get_agent_card_different_urls_not_cached(self, wrapper_with_client):
        """Test different URLs get separate cache entries."""
        mock_card1 = MagicMock()
        mock_card2 = MagicMock()

        with patch("src.shared.a2a.client_wrapper.A2ACardResolver") as MockResolver:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card.side_effect = [mock_card1, mock_card2]
            MockResolver.return_value = mock_resolver

            card1 = await wrapper_with_client._get_agent_card("http://agent1:8000")
            card2 = await wrapper_with_client._get_agent_card("http://agent2:8000")

            assert card1 is mock_card1
            assert card2 is mock_card2
            assert MockResolver.call_count == 2

    @pytest.mark.asyncio
    async def test_get_agent_card_connection_error(self, wrapper_with_client):
        """Test connection error is wrapped in A2AConnectionError."""
        with patch("src.shared.a2a.client_wrapper.A2ACardResolver") as MockResolver:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card.side_effect = httpx.ConnectError("refused")
            MockResolver.return_value = mock_resolver

            with pytest.raises(A2AConnectionError, match="Failed to connect"):
                await wrapper_with_client._get_agent_card("http://localhost:8000")

    @pytest.mark.asyncio
    async def test_get_agent_card_timeout_error(self, wrapper_with_client):
        """Test timeout is wrapped in A2ATimeoutError."""
        with patch("src.shared.a2a.client_wrapper.A2ACardResolver") as MockResolver:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card.side_effect = httpx.TimeoutException("timed out")
            MockResolver.return_value = mock_resolver

            with pytest.raises(A2ATimeoutError, match="Timeout connecting"):
                await wrapper_with_client._get_agent_card("http://localhost:8000")


class TestA2AClientWrapperA2AClient:
    """Tests for A2A client creation."""

    @pytest.fixture
    def wrapper_with_client(self):
        """Create wrapper with mock httpx client."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        return A2AClientWrapper(httpx_client=mock_client)

    @pytest.mark.asyncio
    async def test_get_a2a_client_caches_result(self, wrapper_with_client):
        """Test A2A client is cached after first creation."""
        mock_card = MagicMock()
        mock_a2a_client = MagicMock()

        with patch("src.shared.a2a.client_wrapper.A2ACardResolver") as MockResolver:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card.return_value = mock_card
            MockResolver.return_value = mock_resolver

            with patch("src.shared.a2a.client_wrapper.A2AClient") as MockA2AClient:
                MockA2AClient.return_value = mock_a2a_client

                client1 = await wrapper_with_client._get_a2a_client("http://localhost:8000")
                client2 = await wrapper_with_client._get_a2a_client("http://localhost:8000")

                assert client1 is mock_a2a_client
                assert client2 is mock_a2a_client
                assert MockA2AClient.call_count == 1


class TestA2AClientWrapperSendMessage:
    """Tests for send_message functionality."""

    @pytest.fixture
    def wrapper_with_client(self):
        """Create wrapper with mock httpx client."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        return A2AClientWrapper(httpx_client=mock_client)

    def _create_mock_stream_response(self, chunks):
        """Helper to create mock streaming response."""

        async def mock_stream(request):
            for chunk in chunks:
                yield chunk

        return mock_stream

    @pytest.mark.asyncio
    async def test_send_message_simple_response(self, wrapper_with_client):
        """Test sending message and receiving simple response."""
        mock_card = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.model_dump.return_value = {
            "result": {
                "artifact": {"parts": [{"text": "Hello from agent"}]},
                "status": {"state": "completed"},
            }
        }

        with patch("src.shared.a2a.client_wrapper.A2ACardResolver") as MockResolver:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card.return_value = mock_card
            MockResolver.return_value = mock_resolver

            with patch("src.shared.a2a.client_wrapper.A2AClient") as MockA2AClient:
                mock_a2a = MagicMock()

                async def mock_stream(request):
                    yield mock_chunk

                mock_a2a.send_message_streaming = mock_stream
                MockA2AClient.return_value = mock_a2a

                response = await wrapper_with_client.send_message(
                    agent_url="http://localhost:8000",
                    message="Hello",
                )

                assert response.text == "Hello from agent"
                assert response.is_complete is True

    @pytest.mark.asyncio
    async def test_send_message_with_context_id(self, wrapper_with_client):
        """Test sending message with context ID."""
        mock_card = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.model_dump.return_value = {
            "result": {
                "contextId": "new_ctx",
                "artifact": {"parts": [{"text": "Response"}]},
            }
        }

        with patch("src.shared.a2a.client_wrapper.A2ACardResolver") as MockResolver:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card.return_value = mock_card
            MockResolver.return_value = mock_resolver

            with patch("src.shared.a2a.client_wrapper.A2AClient") as MockA2AClient:
                mock_a2a = MagicMock()

                async def mock_stream(request):
                    yield mock_chunk

                mock_a2a.send_message_streaming = mock_stream
                MockA2AClient.return_value = mock_a2a

                response = await wrapper_with_client.send_message(
                    agent_url="http://localhost:8000",
                    message="Continue",
                    context_id="old_ctx",
                )

                assert response.context_id == "new_ctx"

    @pytest.mark.asyncio
    async def test_send_message_with_task_id(self, wrapper_with_client):
        """Test sending message with task ID."""
        mock_card = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.model_dump.return_value = {
            "result": {
                "id": "new_task",
                "kind": "task",
                "artifact": {"parts": [{"text": "Response"}]},
            }
        }

        with patch("src.shared.a2a.client_wrapper.A2ACardResolver") as MockResolver:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card.return_value = mock_card
            MockResolver.return_value = mock_resolver

            with patch("src.shared.a2a.client_wrapper.A2AClient") as MockA2AClient:
                mock_a2a = MagicMock()

                async def mock_stream(request):
                    yield mock_chunk

                mock_a2a.send_message_streaming = mock_stream
                MockA2AClient.return_value = mock_a2a

                response = await wrapper_with_client.send_message(
                    agent_url="http://localhost:8000",
                    message="Task request",
                    task_id="old_task",
                )

                assert response.task_id == "new_task"

    @pytest.mark.asyncio
    async def test_send_message_input_required(self, wrapper_with_client):
        """Test response with input_required status."""
        mock_card = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.model_dump.return_value = {
            "result": {
                "status": {
                    "state": "input_required",
                    "message": {"parts": [{"text": "What dates?"}]},
                },
            }
        }

        with patch("src.shared.a2a.client_wrapper.A2ACardResolver") as MockResolver:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card.return_value = mock_card
            MockResolver.return_value = mock_resolver

            with patch("src.shared.a2a.client_wrapper.A2AClient") as MockA2AClient:
                mock_a2a = MagicMock()

                async def mock_stream(request):
                    yield mock_chunk

                mock_a2a.send_message_streaming = mock_stream
                MockA2AClient.return_value = mock_a2a

                response = await wrapper_with_client.send_message(
                    agent_url="http://localhost:8000",
                    message="Plan trip",
                )

                assert response.requires_input is True
                assert response.is_complete is False
                assert response.text == "What dates?"

    @pytest.mark.asyncio
    async def test_send_message_multiple_chunks(self, wrapper_with_client):
        """Test handling multiple streaming chunks."""
        mock_card = MagicMock()
        chunk1 = MagicMock()
        chunk1.model_dump.return_value = {
            "result": {"message": {"parts": [{"text": "Hello "}]}}
        }
        chunk2 = MagicMock()
        chunk2.model_dump.return_value = {
            "result": {"artifact": {"parts": [{"text": "World"}]}}
        }

        with patch("src.shared.a2a.client_wrapper.A2ACardResolver") as MockResolver:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card.return_value = mock_card
            MockResolver.return_value = mock_resolver

            with patch("src.shared.a2a.client_wrapper.A2AClient") as MockA2AClient:
                mock_a2a = MagicMock()

                async def mock_stream(request):
                    yield chunk1
                    yield chunk2

                mock_a2a.send_message_streaming = mock_stream
                MockA2AClient.return_value = mock_a2a

                response = await wrapper_with_client.send_message(
                    agent_url="http://localhost:8000",
                    message="Hello",
                )

                assert response.text == "Hello World"

    @pytest.mark.asyncio
    async def test_send_message_collect_raw_chunks(self, wrapper_with_client):
        """Test collecting raw chunks when requested."""
        mock_card = MagicMock()
        chunk1_data = {"result": {"message": {"parts": [{"text": "Test"}]}}}
        chunk1 = MagicMock()
        chunk1.model_dump.return_value = chunk1_data

        with patch("src.shared.a2a.client_wrapper.A2ACardResolver") as MockResolver:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card.return_value = mock_card
            MockResolver.return_value = mock_resolver

            with patch("src.shared.a2a.client_wrapper.A2AClient") as MockA2AClient:
                mock_a2a = MagicMock()

                async def mock_stream(request):
                    yield chunk1

                mock_a2a.send_message_streaming = mock_stream
                MockA2AClient.return_value = mock_a2a

                response = await wrapper_with_client.send_message(
                    agent_url="http://localhost:8000",
                    message="Hello",
                    collect_raw_chunks=True,
                )

                assert len(response.raw_chunks) == 1
                assert response.raw_chunks[0] == chunk1_data

    @pytest.mark.asyncio
    async def test_send_message_connection_error(self, wrapper_with_client):
        """Test connection error during message send."""
        with patch("src.shared.a2a.client_wrapper.A2ACardResolver") as MockResolver:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card.side_effect = httpx.ConnectError("refused")
            MockResolver.return_value = mock_resolver

            with pytest.raises(A2AConnectionError):
                await wrapper_with_client.send_message(
                    agent_url="http://localhost:8000",
                    message="Hello",
                )

    @pytest.mark.asyncio
    async def test_send_message_timeout_error(self, wrapper_with_client):
        """Test timeout error during message send."""
        with patch("src.shared.a2a.client_wrapper.A2ACardResolver") as MockResolver:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card.side_effect = httpx.TimeoutException("timeout")
            MockResolver.return_value = mock_resolver

            with pytest.raises(A2ATimeoutError):
                await wrapper_with_client.send_message(
                    agent_url="http://localhost:8000",
                    message="Hello",
                )

    @pytest.mark.asyncio
    async def test_send_message_generic_error(self, wrapper_with_client):
        """Test generic error during message send."""
        with patch("src.shared.a2a.client_wrapper.A2ACardResolver") as MockResolver:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card.side_effect = ValueError("unexpected")
            MockResolver.return_value = mock_resolver

            with pytest.raises(A2AClientError, match="A2A call failed"):
                await wrapper_with_client.send_message(
                    agent_url="http://localhost:8000",
                    message="Hello",
                )


class TestA2AClientWrapperParseChunk:
    """Tests for _parse_result_chunk method."""

    @pytest.fixture
    def wrapper(self):
        """Create wrapper instance."""
        return A2AClientWrapper()

    def test_parse_empty_result(self, wrapper):
        """Test parsing empty result."""
        text, ctx, task, complete, input_req = wrapper._parse_result_chunk(
            {}, None, None, False, False
        )
        assert text == ""
        assert ctx is None
        assert task is None
        assert complete is False
        assert input_req is False

    def test_parse_context_id(self, wrapper):
        """Test parsing contextId from result."""
        result = {"contextId": "ctx_123"}
        text, ctx, task, complete, input_req = wrapper._parse_result_chunk(
            result, None, None, False, False
        )
        assert ctx == "ctx_123"

    def test_parse_task_id_from_taskId(self, wrapper):
        """Test parsing taskId field."""
        result = {"taskId": "task_456"}
        text, ctx, task, complete, input_req = wrapper._parse_result_chunk(
            result, None, None, False, False
        )
        assert task == "task_456"

    def test_parse_task_id_from_task_kind(self, wrapper):
        """Test parsing task ID from kind=task."""
        result = {"id": "task_789", "kind": "task"}
        text, ctx, task, complete, input_req = wrapper._parse_result_chunk(
            result, None, None, False, False
        )
        assert task == "task_789"

    def test_parse_artifact_text(self, wrapper):
        """Test parsing text from artifact parts."""
        result = {"artifact": {"parts": [{"text": "artifact text"}]}}
        text, ctx, task, complete, input_req = wrapper._parse_result_chunk(
            result, None, None, False, False
        )
        assert text == "artifact text"

    def test_parse_message_text(self, wrapper):
        """Test parsing text from message parts."""
        result = {"message": {"parts": [{"text": "message text"}]}}
        text, ctx, task, complete, input_req = wrapper._parse_result_chunk(
            result, None, None, False, False
        )
        assert text == "message text"

    def test_parse_status_completed(self, wrapper):
        """Test parsing completed status."""
        result = {"status": {"state": "completed"}}
        text, ctx, task, complete, input_req = wrapper._parse_result_chunk(
            result, None, None, False, False
        )
        assert complete is True
        assert input_req is False

    def test_parse_status_input_required(self, wrapper):
        """Test parsing input_required status."""
        result = {"status": {"state": "input_required"}}
        text, ctx, task, complete, input_req = wrapper._parse_result_chunk(
            result, None, None, False, False
        )
        assert complete is False
        assert input_req is True

    def test_parse_status_with_message(self, wrapper):
        """Test parsing status with embedded message."""
        result = {
            "status": {
                "state": "input_required",
                "message": {"parts": [{"text": "Need more info"}]},
            }
        }
        text, ctx, task, complete, input_req = wrapper._parse_result_chunk(
            result, None, None, False, False
        )
        assert text == "Need more info"
        assert input_req is True

    def test_parse_combined_text_sources(self, wrapper):
        """Test text is combined from multiple sources."""
        result = {
            "status": {
                "state": "working",
                "message": {"parts": [{"text": "A "}]},
            },
            "artifact": {"parts": [{"text": "B "}]},
            "message": {"parts": [{"text": "C"}]},
        }
        text, ctx, task, complete, input_req = wrapper._parse_result_chunk(
            result, None, None, False, False
        )
        assert text == "A B C"


class TestA2AClientWrapperClearCache:
    """Tests for clear_cache method."""

    def test_clear_cache(self):
        """Test clearing caches."""
        wrapper = A2AClientWrapper()
        wrapper._agent_card_cache["http://test"] = MagicMock()
        wrapper._a2a_client_cache["http://test"] = MagicMock()

        wrapper.clear_cache()

        assert len(wrapper._agent_card_cache) == 0
        assert len(wrapper._a2a_client_cache) == 0


class TestA2AClientWrapperHealthCheck:
    """Tests for health_check method."""

    @pytest.fixture
    def wrapper_with_client(self):
        """Create wrapper with mock httpx client."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        return A2AClientWrapper(httpx_client=mock_client)

    @pytest.mark.asyncio
    async def test_health_check_success(self, wrapper_with_client):
        """Test health check returns True when agent is reachable."""
        mock_card = MagicMock()

        with patch("src.shared.a2a.client_wrapper.A2ACardResolver") as MockResolver:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card.return_value = mock_card
            MockResolver.return_value = mock_resolver

            result = await wrapper_with_client.health_check("http://localhost:8000")
            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_connection_failure(self, wrapper_with_client):
        """Test health check returns False on connection error."""
        with patch("src.shared.a2a.client_wrapper.A2ACardResolver") as MockResolver:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card.side_effect = httpx.ConnectError("refused")
            MockResolver.return_value = mock_resolver

            result = await wrapper_with_client.health_check("http://localhost:8000")
            assert result is False

    @pytest.mark.asyncio
    async def test_health_check_timeout(self, wrapper_with_client):
        """Test health check returns False on timeout."""
        with patch("src.shared.a2a.client_wrapper.A2ACardResolver") as MockResolver:
            mock_resolver = AsyncMock()
            mock_resolver.get_agent_card.side_effect = httpx.TimeoutException("timeout")
            MockResolver.return_value = mock_resolver

            result = await wrapper_with_client.health_check("http://localhost:8000")
            assert result is False


class TestA2AClientWrapperTraceContext:
    """Tests for trace context injection and propagation."""

    def test_has_telemetry_flag_exists(self):
        """Test HAS_TELEMETRY flag is exported."""
        # This flag indicates whether OpenTelemetry is available
        assert isinstance(HAS_TELEMETRY, bool)

    def test_get_trace_headers_no_telemetry(self):
        """Test _get_trace_headers returns empty dict when telemetry disabled."""
        wrapper = A2AClientWrapper()

        # Patch HAS_TELEMETRY to False
        with patch("src.shared.a2a.client_wrapper.HAS_TELEMETRY", False):
            headers = wrapper._get_trace_headers()
            assert headers == {}

    def test_get_trace_headers_with_telemetry(self):
        """Test _get_trace_headers injects headers when telemetry enabled."""
        wrapper = A2AClientWrapper()

        # Mock inject to add trace headers
        def mock_inject(headers):
            headers["traceparent"] = "00-trace-id-span-id-01"
            headers["tracestate"] = "vendor=value"

        with patch("src.shared.a2a.client_wrapper.HAS_TELEMETRY", True):
            with patch("src.shared.a2a.client_wrapper.inject", mock_inject):
                headers = wrapper._get_trace_headers()
                assert "traceparent" in headers
                assert headers["traceparent"] == "00-trace-id-span-id-01"
                assert "tracestate" in headers

    def test_get_trace_headers_inject_none(self):
        """Test _get_trace_headers handles inject being None."""
        wrapper = A2AClientWrapper()

        with patch("src.shared.a2a.client_wrapper.HAS_TELEMETRY", True):
            with patch("src.shared.a2a.client_wrapper.inject", None):
                headers = wrapper._get_trace_headers()
                assert headers == {}

    def test_inject_trace_context_no_telemetry(self):
        """Test _inject_trace_context_to_client does nothing without telemetry."""
        wrapper = A2AClientWrapper()

        with patch("src.shared.a2a.client_wrapper.HAS_TELEMETRY", False):
            # Should not raise, just return
            wrapper._inject_trace_context_to_client()

    def test_inject_trace_context_inject_none(self):
        """Test _inject_trace_context_to_client handles inject being None."""
        wrapper = A2AClientWrapper()

        with patch("src.shared.a2a.client_wrapper.HAS_TELEMETRY", True):
            with patch("src.shared.a2a.client_wrapper.inject", None):
                # Should not raise, just return
                wrapper._inject_trace_context_to_client()

    def test_inject_trace_context_no_headers(self):
        """Test _inject_trace_context_to_client handles empty inject."""
        wrapper = A2AClientWrapper()
        wrapper._internal_client = MagicMock(spec=httpx.AsyncClient)
        wrapper._internal_client.headers = {}

        def mock_inject_empty(headers):
            # inject doesn't add any headers
            pass

        with patch("src.shared.a2a.client_wrapper.HAS_TELEMETRY", True):
            with patch("src.shared.a2a.client_wrapper.inject", mock_inject_empty):
                wrapper._inject_trace_context_to_client()
                # No headers should be added
                assert wrapper._internal_client.headers == {}

    def test_inject_trace_context_updates_client_headers(self):
        """Test _inject_trace_context_to_client updates internal client headers."""
        wrapper = A2AClientWrapper()
        mock_headers = MagicMock()
        wrapper._internal_client = MagicMock(spec=httpx.AsyncClient)
        wrapper._internal_client.headers = mock_headers

        def mock_inject(headers):
            headers["traceparent"] = "00-test-trace-01"

        with patch("src.shared.a2a.client_wrapper.HAS_TELEMETRY", True):
            with patch("src.shared.a2a.client_wrapper.inject", mock_inject):
                wrapper._inject_trace_context_to_client()
                mock_headers.__setitem__.assert_called_with(
                    "traceparent", "00-test-trace-01"
                )

    def test_inject_trace_context_no_internal_client(self):
        """Test _inject_trace_context_to_client handles no internal client."""
        wrapper = A2AClientWrapper()
        # No internal client set

        def mock_inject(headers):
            headers["traceparent"] = "00-test-trace-01"

        with patch("src.shared.a2a.client_wrapper.HAS_TELEMETRY", True):
            with patch("src.shared.a2a.client_wrapper.inject", mock_inject):
                # Should not raise
                wrapper._inject_trace_context_to_client()

    @pytest.mark.asyncio
    async def test_context_manager_includes_trace_headers(self):
        """Test context manager creates client with trace headers."""

        def mock_inject(headers):
            headers["traceparent"] = "00-context-trace-01"

        with patch("src.shared.a2a.client_wrapper.HAS_TELEMETRY", True):
            with patch("src.shared.a2a.client_wrapper.inject", mock_inject):
                wrapper = A2AClientWrapper()
                async with wrapper as w:
                    assert w._internal_client is not None
                    assert "traceparent" in w._internal_client.headers
                    assert (
                        w._internal_client.headers["traceparent"]
                        == "00-context-trace-01"
                    )

    @pytest.mark.asyncio
    async def test_send_message_injects_trace_context(self):
        """Test send_message injects trace context before request."""
        mock_card = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.model_dump.return_value = {
            "result": {
                "artifact": {"parts": [{"text": "Response"}]},
                "status": {"state": "completed"},
            }
        }

        inject_called = []

        def mock_inject(headers):
            inject_called.append(True)
            headers["traceparent"] = "00-send-trace-01"

        with patch("src.shared.a2a.client_wrapper.HAS_TELEMETRY", True):
            with patch("src.shared.a2a.client_wrapper.inject", mock_inject):
                with patch(
                    "src.shared.a2a.client_wrapper.A2ACardResolver"
                ) as MockResolver:
                    mock_resolver = AsyncMock()
                    mock_resolver.get_agent_card.return_value = mock_card
                    MockResolver.return_value = mock_resolver

                    with patch(
                        "src.shared.a2a.client_wrapper.A2AClient"
                    ) as MockA2AClient:
                        mock_a2a = MagicMock()

                        async def mock_stream(request):
                            yield mock_chunk

                        mock_a2a.send_message_streaming = mock_stream
                        MockA2AClient.return_value = mock_a2a

                        mock_client = MagicMock(spec=httpx.AsyncClient)
                        mock_client.headers = {}
                        wrapper = A2AClientWrapper(httpx_client=mock_client)
                        wrapper._internal_client = mock_client

                        response = await wrapper.send_message(
                            agent_url="http://localhost:8000",
                            message="Hello",
                        )

                        assert response.text == "Response"
                        # inject should have been called during send_message
                        assert len(inject_called) >= 1

    @pytest.mark.asyncio
    async def test_send_message_updates_headers_for_each_call(self):
        """Test each send_message call updates headers with current trace."""
        mock_card = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.model_dump.return_value = {
            "result": {
                "artifact": {"parts": [{"text": "Response"}]},
                "status": {"state": "completed"},
            }
        }

        call_count = [0]

        def mock_inject(headers):
            call_count[0] += 1
            headers["traceparent"] = f"00-trace-{call_count[0]}-01"

        with patch("src.shared.a2a.client_wrapper.HAS_TELEMETRY", True):
            with patch("src.shared.a2a.client_wrapper.inject", mock_inject):
                with patch(
                    "src.shared.a2a.client_wrapper.A2ACardResolver"
                ) as MockResolver:
                    mock_resolver = AsyncMock()
                    mock_resolver.get_agent_card.return_value = mock_card
                    MockResolver.return_value = mock_resolver

                    with patch(
                        "src.shared.a2a.client_wrapper.A2AClient"
                    ) as MockA2AClient:
                        mock_a2a = MagicMock()

                        async def mock_stream(request):
                            yield mock_chunk

                        mock_a2a.send_message_streaming = mock_stream
                        MockA2AClient.return_value = mock_a2a

                        headers_dict = {}
                        mock_client = MagicMock(spec=httpx.AsyncClient)
                        mock_client.headers = headers_dict
                        wrapper = A2AClientWrapper(httpx_client=mock_client)
                        wrapper._internal_client = mock_client

                        # First call
                        await wrapper.send_message(
                            agent_url="http://localhost:8000",
                            message="Hello 1",
                        )
                        first_trace = headers_dict.get("traceparent", "")

                        # Second call
                        await wrapper.send_message(
                            agent_url="http://localhost:8000",
                            message="Hello 2",
                        )
                        second_trace = headers_dict.get("traceparent", "")

                        # Both calls should have injected (call_count shows injection)
                        assert call_count[0] >= 2
                        # Headers should be updated (may be same or different based on span)
                        assert first_trace or second_trace  # At least one should be set
