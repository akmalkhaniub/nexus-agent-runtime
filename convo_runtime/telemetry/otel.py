"""
convo_runtime.telemetry.otel
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

OpenTelemetry distributed tracing instrumented according to GenAI Semantic Conventions.
Provides span contexts, traceparent header propagation, and workflow observability.
"""

from __future__ import annotations

import contextlib
from typing import Any, Dict, Iterator, Optional
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Span, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


class InMemorySpanExporter(SpanExporter):
    """Thread-safe in-memory span exporter for testing and telemetry retrieval."""

    def __init__(self) -> None:
        self._spans = []

    def export(self, spans) -> SpanExportResult:
        self._spans.extend(spans)
        return SpanExportResult.SUCCESS

    def get_finished_spans(self) -> list:
        return list(self._spans)

    def clear(self) -> None:
        self._spans.clear()

    def shutdown(self) -> None:
        self.clear()


# In-memory exporter for testing and direct API trace retrieval
_span_exporter = InMemorySpanExporter()
_tracer_provider = TracerProvider()
_tracer_provider.add_span_processor(SimpleSpanProcessor(_span_exporter))
trace.set_tracer_provider(_tracer_provider)
tracer = trace.get_tracer("convo.agent.runtime", "1.0.0")

_propagator = TraceContextTextMapPropagator()


def get_recorded_spans() -> list:
    """Returns all spans recorded by the in-memory exporter."""
    return _span_exporter.get_finished_spans()


def clear_recorded_spans() -> None:
    """Clears previously captured spans."""
    _span_exporter.clear()


def inject_trace_context(headers: Dict[str, str]) -> Dict[str, str]:
    """Injects current active span traceparent into HTTP/gRPC request headers."""
    _propagator.inject(headers)
    return headers


def extract_trace_context(headers: Dict[str, str]) -> Any:
    """Extracts carrier trace context from incoming headers."""
    return _propagator.extract(headers)


@contextlib.contextmanager
def trace_workflow_span(
    name: str,
    run_id: str,
    tenant_id: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None,
) -> Iterator[Span]:
    """
    Context manager creating a top-level workflow trace span conforming
    to OpenTelemetry GenAI semantic conventions.
    """
    with tracer.start_as_current_span(name) as span:
        span.set_attribute("gen_ai.system", "convo_agent_runtime")
        span.set_attribute("convo.run_id", run_id)
        if tenant_id:
            span.set_attribute("convo.tenant_id", tenant_id)

        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, str(v) if not isinstance(v, (int, float, bool, str)) else v)

        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise


@contextlib.contextmanager
def trace_tool_span(
    tool_name: str,
    call_id: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None,
) -> Iterator[Span]:
    """Context manager creating a tool execution child span."""
    with tracer.start_as_current_span(f"tool:{tool_name}") as span:
        span.set_attribute("tool.name", tool_name)
        if call_id:
            span.set_attribute("tool.call_id", call_id)
        if parameters:
            span.set_attribute("tool.parameters", str(parameters))

        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise
