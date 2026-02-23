"""Tests for the observability module."""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from src.shared.observability import (
    NoOpSpan,
    NoOpTracer,
    StructuredFormatter,
    configure_structured_logging,
    extract_trace_context,
    get_tracer,
    inject_trace_context,
    is_instrumentation_enabled,
    setup_observability,
)


class TestIsInstrumentationEnabled:
    """Tests for is_instrumentation_enabled function."""

    def test_disabled_by_default(self) -> None:
        """Test instrumentation is disabled by default."""
        with patch.dict("os.environ", {}, clear=True):
            assert is_instrumentation_enabled() is False

    def test_disabled_when_false(self) -> None:
        """Test instrumentation disabled when explicitly set to false."""
        with patch.dict("os.environ", {"ENABLE_INSTRUMENTATION": "false"}):
            assert is_instrumentation_enabled() is False

    def test_enabled_when_true(self) -> None:
        """Test instrumentation enabled when set to true."""
        with patch.dict("os.environ", {"ENABLE_INSTRUMENTATION": "true"}):
            assert is_instrumentation_enabled() is True

    def test_enabled_case_insensitive(self) -> None:
        """Test instrumentation enabled check is case insensitive."""
        with patch.dict("os.environ", {"ENABLE_INSTRUMENTATION": "TRUE"}):
            assert is_instrumentation_enabled() is True

    def test_disabled_for_invalid_value(self) -> None:
        """Test instrumentation disabled for invalid values."""
        with patch.dict("os.environ", {"ENABLE_INSTRUMENTATION": "yes"}):
            assert is_instrumentation_enabled() is False


class TestSetupObservabilityDisabled:
    """Tests for setup_observability when disabled."""

    def test_returns_early_when_disabled(self) -> None:
        """Test setup_observability returns early when disabled."""
        with patch.dict("os.environ", {"ENABLE_INSTRUMENTATION": "false"}):
            # Should not raise, just return early
            setup_observability("test-service")

    def test_logs_debug_when_disabled(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test setup_observability logs debug message when disabled."""
        with caplog.at_level(logging.DEBUG):
            with patch.dict("os.environ", {"ENABLE_INSTRUMENTATION": "false"}):
                setup_observability("test-service")
        assert "Instrumentation disabled" in caplog.text


class TestSetupObservabilityEnabled:
    """Tests for setup_observability when enabled."""

    def test_warns_when_opentelemetry_not_installed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test setup_observability warns when OpenTelemetry not installed."""
        with patch.dict("os.environ", {"ENABLE_INSTRUMENTATION": "true"}):
            with patch("src.shared.observability.HAS_OPENTELEMETRY", False):
                with caplog.at_level(logging.WARNING):
                    setup_observability("test-service")
        assert "OpenTelemetry not installed" in caplog.text

    def test_azure_monitor_path_when_connection_string_set(self) -> None:
        """Test Azure Monitor is configured when connection string is set."""
        with patch.dict(
            "os.environ",
            {
                "ENABLE_INSTRUMENTATION": "true",
                "APPLICATIONINSIGHTS_CONNECTION_STRING": "InstrumentationKey=test",
            },
        ):
            with patch("src.shared.observability.HAS_OPENTELEMETRY", True):
                with patch(
                    "src.shared.observability._setup_azure_monitor"
                ) as mock_azure:
                    setup_observability("test-service")
                    mock_azure.assert_called_once_with(
                        "test-service", "InstrumentationKey=test"
                    )

    def test_otlp_path_when_endpoint_set(self) -> None:
        """Test OTLP exporter is configured when endpoint is set."""
        with patch.dict(
            "os.environ",
            {
                "ENABLE_INSTRUMENTATION": "true",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
            },
        ):
            with patch("src.shared.observability.HAS_OPENTELEMETRY", True):
                with patch(
                    "src.shared.observability._setup_otlp_exporter"
                ) as mock_otlp:
                    setup_observability("test-service")
                    mock_otlp.assert_called_once_with(
                        "test-service", "http://localhost:4317"
                    )

    def test_console_fallback_when_no_config(self) -> None:
        """Test console exporter is used as fallback."""
        with patch.dict("os.environ", {"ENABLE_INSTRUMENTATION": "true"}, clear=True):
            with patch("src.shared.observability.HAS_OPENTELEMETRY", True):
                with patch(
                    "src.shared.observability._setup_console_exporter"
                ) as mock_console:
                    setup_observability("test-service")
                    mock_console.assert_called_once_with("test-service")

    def test_azure_monitor_takes_precedence_over_otlp(self) -> None:
        """Test Azure Monitor is preferred over OTLP when both are set."""
        with patch.dict(
            "os.environ",
            {
                "ENABLE_INSTRUMENTATION": "true",
                "APPLICATIONINSIGHTS_CONNECTION_STRING": "InstrumentationKey=test",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
            },
        ):
            with patch("src.shared.observability.HAS_OPENTELEMETRY", True):
                with patch(
                    "src.shared.observability._setup_azure_monitor"
                ) as mock_azure:
                    with patch(
                        "src.shared.observability._setup_otlp_exporter"
                    ) as mock_otlp:
                        setup_observability("test-service")
                        mock_azure.assert_called_once()
                        mock_otlp.assert_not_called()


class TestSetupAzureMonitor:
    """Tests for _setup_azure_monitor function."""

    def test_warns_when_azure_monitor_not_installed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test warns when Azure Monitor package not installed."""
        from src.shared.observability import _setup_azure_monitor

        with patch("src.shared.observability.HAS_AZURE_MONITOR", False):
            with patch("src.shared.observability._setup_console_exporter") as mock_cons:
                with caplog.at_level(logging.WARNING):
                    _setup_azure_monitor("test-service", "connection-string")
                assert "Azure Monitor not installed" in caplog.text
                mock_cons.assert_called_once_with("test-service")

    def test_configure_azure_monitor_called(self) -> None:
        """Test configure_azure_monitor is called with correct params."""
        from src.shared.observability import _setup_azure_monitor

        mock_configure = MagicMock()
        with patch("src.shared.observability.HAS_AZURE_MONITOR", True):
            with patch(
                "src.shared.observability.configure_azure_monitor", mock_configure
            ):
                _setup_azure_monitor("test-service", "InstrumentationKey=test")
                mock_configure.assert_called_once_with(
                    connection_string="InstrumentationKey=test",
                    service_name="test-service",
                )

    def test_falls_back_to_console_on_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test falls back to console exporter on Azure Monitor error."""
        from src.shared.observability import _setup_azure_monitor

        mock_configure = MagicMock(side_effect=Exception("Config error"))
        with patch("src.shared.observability.HAS_AZURE_MONITOR", True):
            with patch(
                "src.shared.observability.configure_azure_monitor", mock_configure
            ):
                with patch(
                    "src.shared.observability._setup_console_exporter"
                ) as mock_cons:
                    with caplog.at_level(logging.ERROR):
                        _setup_azure_monitor("test-service", "connection-string")
                    assert "Failed to configure Azure Monitor" in caplog.text
                    mock_cons.assert_called_once_with("test-service")


class TestSetupOtlpExporter:
    """Tests for _setup_otlp_exporter function."""

    def test_warns_when_otlp_not_installed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test warns when OTLP exporter not installed."""
        from src.shared.observability import _setup_otlp_exporter

        with patch("src.shared.observability.HAS_OTLP", False):
            with patch("src.shared.observability._setup_console_exporter") as mock_cons:
                with caplog.at_level(logging.WARNING):
                    _setup_otlp_exporter("test-service", "http://localhost:4317")
                assert "OTLP exporter not installed" in caplog.text
                mock_cons.assert_called_once_with("test-service")

    def test_configure_otlp_exporter_called(self) -> None:
        """Test OTLP exporter is configured with correct params."""
        from src.shared.observability import _setup_otlp_exporter

        mock_resource = MagicMock()
        mock_provider = MagicMock()
        mock_exporter = MagicMock()
        mock_processor = MagicMock()

        with patch("src.shared.observability.HAS_OTLP", True):
            with patch("src.shared.observability.HAS_OPENTELEMETRY", True):
                with patch(
                    "src.shared.observability.Resource.create", return_value=mock_resource
                ):
                    with patch(
                        "src.shared.observability.TracerProvider",
                        return_value=mock_provider,
                    ):
                        with patch(
                            "src.shared.observability.OTLPSpanExporter",
                            return_value=mock_exporter,
                        ):
                            with patch(
                                "src.shared.observability.BatchSpanProcessor",
                                return_value=mock_processor,
                            ):
                                with patch("src.shared.observability.trace") as mock_trace:
                                    _setup_otlp_exporter(
                                        "test-service", "http://localhost:4317"
                                    )
                                    mock_provider.add_span_processor.assert_called_once()
                                    mock_trace.set_tracer_provider.assert_called_once()

    def test_falls_back_to_console_on_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test falls back to console exporter on OTLP error."""
        from src.shared.observability import _setup_otlp_exporter

        with patch("src.shared.observability.HAS_OTLP", True):
            with patch("src.shared.observability.HAS_OPENTELEMETRY", True):
                with patch(
                    "src.shared.observability.Resource.create",
                    side_effect=Exception("Resource error"),
                ):
                    with patch(
                        "src.shared.observability._setup_console_exporter"
                    ) as mock_cons:
                        with caplog.at_level(logging.ERROR):
                            _setup_otlp_exporter("test-service", "http://localhost:4317")
                        assert "Failed to configure OTLP exporter" in caplog.text
                        mock_cons.assert_called_once_with("test-service")


class TestSetupConsoleExporter:
    """Tests for _setup_console_exporter function."""

    def test_configure_console_exporter(self) -> None:
        """Test console exporter is configured correctly."""
        from src.shared.observability import _setup_console_exporter

        mock_resource = MagicMock()
        mock_provider = MagicMock()
        mock_exporter = MagicMock()
        mock_processor = MagicMock()

        with patch("src.shared.observability.HAS_OPENTELEMETRY", True):
            with patch(
                "src.shared.observability.Resource.create", return_value=mock_resource
            ):
                with patch(
                    "src.shared.observability.TracerProvider",
                    return_value=mock_provider,
                ):
                    with patch(
                        "src.shared.observability.ConsoleSpanExporter",
                        return_value=mock_exporter,
                    ):
                        with patch(
                            "src.shared.observability.BatchSpanProcessor",
                            return_value=mock_processor,
                        ):
                            with patch("src.shared.observability.trace") as mock_trace:
                                _setup_console_exporter("test-service")
                                mock_provider.add_span_processor.assert_called_once()
                                mock_trace.set_tracer_provider.assert_called_once()

    def test_logs_error_on_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test logs error when console exporter setup fails."""
        from src.shared.observability import _setup_console_exporter

        with patch("src.shared.observability.HAS_OPENTELEMETRY", True):
            with patch(
                "src.shared.observability.Resource.create",
                side_effect=Exception("Setup error"),
            ):
                with caplog.at_level(logging.ERROR):
                    _setup_console_exporter("test-service")
                assert "Failed to configure console exporter" in caplog.text


class TestGetTracer:
    """Tests for get_tracer function."""

    def test_returns_noop_tracer_when_otel_not_available(self) -> None:
        """Test returns NoOpTracer when OpenTelemetry not available."""
        with patch("src.shared.observability.HAS_OPENTELEMETRY", False):
            tracer = get_tracer(__name__)
            assert isinstance(tracer, NoOpTracer)

    def test_returns_otel_tracer_when_available(self) -> None:
        """Test returns OpenTelemetry tracer when available."""
        mock_tracer = MagicMock()
        mock_trace = MagicMock()
        mock_trace.get_tracer.return_value = mock_tracer

        with patch("src.shared.observability.HAS_OPENTELEMETRY", True):
            with patch("src.shared.observability.trace", mock_trace):
                tracer = get_tracer(__name__)
                mock_trace.get_tracer.assert_called_once_with(__name__)
                assert tracer == mock_tracer


class TestNoOpSpan:
    """Tests for NoOpSpan class."""

    def test_context_manager(self) -> None:
        """Test NoOpSpan can be used as context manager."""
        span = NoOpSpan()
        with span as s:
            assert s is span

    def test_set_attribute_noop(self) -> None:
        """Test set_attribute does nothing."""
        span = NoOpSpan()
        span.set_attribute("key", "value")  # Should not raise

    def test_add_event_noop(self) -> None:
        """Test add_event does nothing."""
        span = NoOpSpan()
        span.add_event("event_name", {"key": "value"})  # Should not raise

    def test_set_status_noop(self) -> None:
        """Test set_status does nothing."""
        span = NoOpSpan()
        span.set_status(None)  # Should not raise

    def test_record_exception_noop(self) -> None:
        """Test record_exception does nothing."""
        span = NoOpSpan()
        span.record_exception(Exception("test"))  # Should not raise


class TestNoOpTracer:
    """Tests for NoOpTracer class."""

    def test_start_span_returns_noop_span(self) -> None:
        """Test start_span returns NoOpSpan."""
        tracer = NoOpTracer()
        span = tracer.start_span("test-span")
        assert isinstance(span, NoOpSpan)

    def test_start_as_current_span_returns_noop_span(self) -> None:
        """Test start_as_current_span returns NoOpSpan."""
        tracer = NoOpTracer()
        span = tracer.start_as_current_span("test-span")
        assert isinstance(span, NoOpSpan)


class TestStructuredFormatter:
    """Tests for StructuredFormatter class."""

    def test_formats_basic_log_record(self) -> None:
        """Test formats basic log record as JSON."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert data["message"] == "Test message"
        assert "timestamp" in data

    def test_includes_exception_info(self) -> None:
        """Test includes exception info when present."""
        formatter = StructuredFormatter()
        try:
            raise ValueError("Test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()
            record = logging.LogRecord(
                name="test.logger",
                level=logging.ERROR,
                pathname="test.py",
                lineno=10,
                msg="Error occurred",
                args=(),
                exc_info=exc_info,
            )
            output = formatter.format(record)
            data = json.loads(output)

            assert "exception" in data
            assert "ValueError" in data["exception"]

    def test_includes_trace_context_when_available(self) -> None:
        """Test includes trace context when OpenTelemetry available."""
        formatter = StructuredFormatter()

        # Create mock span context
        mock_span_context = MagicMock()
        mock_span_context.is_valid = True
        mock_span_context.trace_id = 0x0AF7651916CD43DD8448EB211C80319C
        mock_span_context.span_id = 0x00F067AA0BA902B7

        mock_span = MagicMock()
        mock_span.get_span_context.return_value = mock_span_context

        mock_trace = MagicMock()
        mock_trace.get_current_span.return_value = mock_span

        with patch("src.shared.observability.HAS_OPENTELEMETRY", True):
            with patch("src.shared.observability.trace", mock_trace):
                record = logging.LogRecord(
                    name="test.logger",
                    level=logging.INFO,
                    pathname="test.py",
                    lineno=10,
                    msg="Test message",
                    args=(),
                    exc_info=None,
                )
                output = formatter.format(record)
                data = json.loads(output)

                assert "trace_id" in data
                assert "span_id" in data

    def test_no_trace_context_when_span_invalid(self) -> None:
        """Test no trace context when span context is invalid."""
        formatter = StructuredFormatter()

        mock_span_context = MagicMock()
        mock_span_context.is_valid = False

        mock_span = MagicMock()
        mock_span.get_span_context.return_value = mock_span_context

        mock_trace = MagicMock()
        mock_trace.get_current_span.return_value = mock_span

        with patch("src.shared.observability.HAS_OPENTELEMETRY", True):
            with patch("src.shared.observability.trace", mock_trace):
                record = logging.LogRecord(
                    name="test.logger",
                    level=logging.INFO,
                    pathname="test.py",
                    lineno=10,
                    msg="Test message",
                    args=(),
                    exc_info=None,
                )
                output = formatter.format(record)
                data = json.loads(output)

                assert "trace_id" not in data
                assert "span_id" not in data


class TestConfigureStructuredLogging:
    """Tests for configure_structured_logging function."""

    def test_configures_named_logger(self) -> None:
        """Test configures a named logger."""
        logger = configure_structured_logging("test.structured")
        assert logger.name == "test.structured"
        assert logger.level == logging.INFO
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0].formatter, StructuredFormatter)

    def test_configures_with_custom_level(self) -> None:
        """Test configures logger with custom level."""
        logger = configure_structured_logging("test.debug", level=logging.DEBUG)
        assert logger.level == logging.DEBUG

    def test_removes_existing_handlers(self) -> None:
        """Test removes existing handlers before adding new one."""
        # First setup with one handler
        logger = configure_structured_logging("test.handlers")
        assert len(logger.handlers) == 1

        # Setup again - should still have one handler
        logger = configure_structured_logging("test.handlers")
        assert len(logger.handlers) == 1


class TestInjectTraceContext:
    """Tests for inject_trace_context function."""

    def test_injects_when_otel_available(self) -> None:
        """Test injects trace context when OpenTelemetry available."""
        headers: dict[str, str] = {}
        mock_inject = MagicMock()

        with patch("src.shared.observability.HAS_OPENTELEMETRY", True):
            with patch("src.shared.observability.inject", mock_inject):
                result = inject_trace_context(headers)
                mock_inject.assert_called_once_with(headers)
                assert result is headers

    def test_returns_headers_when_otel_not_available(self) -> None:
        """Test returns original headers when OpenTelemetry not available."""
        headers = {"existing": "header"}
        with patch("src.shared.observability.HAS_OPENTELEMETRY", False):
            result = inject_trace_context(headers)
            assert result == headers


class TestExtractTraceContext:
    """Tests for extract_trace_context function."""

    def test_extracts_when_otel_available(self) -> None:
        """Test extracts trace context when OpenTelemetry available."""
        headers = {"traceparent": "00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01"}
        mock_context = MagicMock()
        mock_extract = MagicMock(return_value=mock_context)

        with patch("src.shared.observability.HAS_OPENTELEMETRY", True):
            with patch("src.shared.observability.extract", mock_extract):
                result = extract_trace_context(headers)
                mock_extract.assert_called_once_with(headers)
                assert result == mock_context

    def test_returns_none_when_otel_not_available(self) -> None:
        """Test returns None when OpenTelemetry not available."""
        headers = {"traceparent": "00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01"}
        with patch("src.shared.observability.HAS_OPENTELEMETRY", False):
            result = extract_trace_context(headers)
            assert result is None
