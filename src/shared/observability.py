"""Observability module for telemetry, tracing, and structured logging.

This module provides unified observability setup for all agents in the system.
It supports:
- OpenTelemetry tracing with Azure Monitor or OTLP export
- Structured JSON logging with trace correlation
- Graceful fallback when telemetry dependencies are not installed

Environment variables:
- ENABLE_INSTRUMENTATION: Set to 'true' to enable telemetry (default: false)
- APPLICATIONINSIGHTS_CONNECTION_STRING: Azure Monitor connection string
- OTEL_EXPORTER_OTLP_ENDPOINT: OTLP exporter endpoint URL
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

# Conditional imports for telemetry dependencies
try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )
    from opentelemetry.propagate import inject, extract

    HAS_OPENTELEMETRY = True
except ImportError:
    HAS_OPENTELEMETRY = False
    trace = None  # type: ignore
    TracerProvider = None  # type: ignore
    Resource = None  # type: ignore
    BatchSpanProcessor = None  # type: ignore
    ConsoleSpanExporter = None  # type: ignore
    inject = None  # type: ignore
    extract = None  # type: ignore

try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter,
    )

    HAS_OTLP = True
except ImportError:
    HAS_OTLP = False
    OTLPSpanExporter = None  # type: ignore

try:
    from azure.monitor.opentelemetry import configure_azure_monitor

    HAS_AZURE_MONITOR = True
except ImportError:
    HAS_AZURE_MONITOR = False
    configure_azure_monitor = None  # type: ignore


def is_instrumentation_enabled() -> bool:
    """Check if instrumentation is enabled via environment variable."""
    return os.getenv("ENABLE_INSTRUMENTATION", "false").lower() == "true"


def setup_observability(service_name: str) -> None:
    """Set up observability for a service (tracing, metrics, logging).

    This function configures OpenTelemetry tracing based on available
    environment variables and dependencies.

    Args:
        service_name: The name of the service for trace identification.

    Configuration priority:
        1. Azure Monitor (if APPLICATIONINSIGHTS_CONNECTION_STRING is set)
        2. OTLP exporter (if OTEL_EXPORTER_OTLP_ENDPOINT is set)
        3. Console exporter (fallback for local development)
    """
    # Early return if instrumentation is not enabled
    if not is_instrumentation_enabled():
        logging.debug(
            f"Instrumentation disabled for {service_name}. "
            "Set ENABLE_INSTRUMENTATION=true to enable."
        )
        return

    # Check if OpenTelemetry is available
    if not HAS_OPENTELEMETRY:
        logging.warning(
            f"OpenTelemetry not installed for {service_name}. "
            "Install with: uv sync --extra telemetry"
        )
        return

    # Try Azure Monitor first
    azure_connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if azure_connection_string:
        _setup_azure_monitor(service_name, azure_connection_string)
        return

    # Try OTLP exporter
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        _setup_otlp_exporter(service_name, otlp_endpoint)
        return

    # Fallback to console exporter for local development
    _setup_console_exporter(service_name)


def _setup_azure_monitor(service_name: str, connection_string: str) -> None:
    """Configure Azure Monitor for telemetry export."""
    if not HAS_AZURE_MONITOR:
        logging.warning(
            f"Azure Monitor not installed for {service_name}. "
            "Install with: uv sync --extra telemetry"
        )
        _setup_console_exporter(service_name)
        return

    try:
        configure_azure_monitor(
            connection_string=connection_string,
            service_name=service_name,
        )
        logging.info(f"Azure Monitor configured for {service_name}")
    except Exception as e:
        logging.error(f"Failed to configure Azure Monitor: {e}")
        _setup_console_exporter(service_name)


def _setup_otlp_exporter(service_name: str, endpoint: str) -> None:
    """Configure OTLP exporter for telemetry export."""
    if not HAS_OTLP:
        logging.warning(
            f"OTLP exporter not installed for {service_name}. "
            "Install with: uv sync --extra telemetry"
        )
        _setup_console_exporter(service_name)
        return

    try:
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        otlp_exporter = OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        trace.set_tracer_provider(provider)
        logging.info(f"OTLP exporter configured for {service_name} -> {endpoint}")
    except Exception as e:
        logging.error(f"Failed to configure OTLP exporter: {e}")
        _setup_console_exporter(service_name)


def _setup_console_exporter(service_name: str) -> None:
    """Configure console exporter for local development."""
    try:
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        console_exporter = ConsoleSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(console_exporter))
        trace.set_tracer_provider(provider)
        logging.info(f"Console span exporter configured for {service_name}")
    except Exception as e:
        logging.error(f"Failed to configure console exporter: {e}")


def get_tracer(name: str) -> Any:
    """Get a tracer for creating spans.

    Args:
        name: The name for the tracer (typically __name__).

    Returns:
        A tracer instance, or a no-op tracer if OpenTelemetry is not available.
    """
    if HAS_OPENTELEMETRY and trace:
        return trace.get_tracer(name)
    return NoOpTracer()


class NoOpSpan:
    """No-op span for when OpenTelemetry is not available."""

    def __enter__(self) -> "NoOpSpan":
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def set_attribute(self, key: str, value: Any) -> None:
        """No-op set_attribute."""
        pass

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """No-op add_event."""
        pass

    def set_status(self, status: Any) -> None:
        """No-op set_status."""
        pass

    def record_exception(self, exception: Exception) -> None:
        """No-op record_exception."""
        pass


class NoOpTracer:
    """No-op tracer for when OpenTelemetry is not available."""

    def start_span(self, name: str, **kwargs: Any) -> NoOpSpan:
        """Return a no-op span."""
        return NoOpSpan()

    def start_as_current_span(self, name: str, **kwargs: Any) -> NoOpSpan:
        """Return a no-op span."""
        return NoOpSpan()


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging with trace correlation.

    Outputs logs as JSON with trace context when available.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON with trace correlation."""
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields from record
        if hasattr(record, "extra"):
            log_data["extra"] = record.extra

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add trace context if OpenTelemetry is available
        if HAS_OPENTELEMETRY and trace:
            span = trace.get_current_span()
            if span:
                span_context = span.get_span_context()
                if span_context.is_valid:
                    log_data["trace_id"] = format(span_context.trace_id, "032x")
                    log_data["span_id"] = format(span_context.span_id, "016x")

        return json.dumps(log_data)


def configure_structured_logging(
    logger_name: str | None = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """Configure a logger with structured JSON output.

    Args:
        logger_name: Name of the logger (None for root logger).
        level: Logging level.

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)

    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Add structured handler
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    logger.addHandler(handler)

    return logger


def inject_trace_context(headers: dict[str, str]) -> dict[str, str]:
    """Inject trace context into HTTP headers for propagation.

    Args:
        headers: Dictionary of HTTP headers to inject into.

    Returns:
        Headers dictionary with trace context added.
    """
    if HAS_OPENTELEMETRY and inject:
        inject(headers)
    return headers


def extract_trace_context(headers: dict[str, str]) -> Any:
    """Extract trace context from HTTP headers.

    Args:
        headers: Dictionary of HTTP headers containing trace context.

    Returns:
        Extracted context, or None if OpenTelemetry is not available.
    """
    if HAS_OPENTELEMETRY and extract:
        return extract(headers)
    return None
