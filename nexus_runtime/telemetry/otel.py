"""
nexus_runtime.telemetry.otel
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
tracer = trace.get_tracer("nexus.agent.runtime", "1.0.0")

_propagator = TraceContextTextMapPropagator()


def get_recorded_spans() -> list:
    """Returns all spans recorded by the in-memory exporter."""
    return _span_exporter.get_finished_spans()


def clear_recorded_spans() -> None:
    """Clears previously captured spans."""
    _span_exporter.clear()


def capture_trace_context() -> Dict[str, str]:
    """Captures active W3C traceparent/tracestate headers for durable checkpoint persistence."""
    carrier: Dict[str, str] = {}
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        _propagator.inject(carrier)
    return carrier


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
    parent_traceparent: Optional[str] = None,
    operation_name: str = "invoke_workflow",
    is_replay: bool = False,
    replay_source_run_id: Optional[str] = None,
    replay_from_step: Optional[int] = None,
    step_index: Optional[int] = None,
) -> Iterator[Span]:
    """
    Context manager creating a top-level workflow trace span conforming
    to OpenTelemetry GenAI semantic conventions and durable execution metadata.
    """
    parent_ctx = extract_trace_context({"traceparent": parent_traceparent}) if parent_traceparent else None
    with tracer.start_as_current_span(name, context=parent_ctx) as span:
        span.set_attribute("gen_ai.system", "nexus_agent_runtime")
        span.set_attribute("gen_ai.operation.name", operation_name)
        span.set_attribute("nexus.run_id", run_id)
        span.set_attribute("durable.workflow.id", run_id)
        span.set_attribute("durable.execution.replayed", is_replay)
        if tenant_id:
            span.set_attribute("nexus.tenant_id", tenant_id)
        if is_replay and replay_source_run_id:
            span.set_attribute("durable.replay.source_run_id", replay_source_run_id)
        if is_replay and replay_from_step is not None:
            span.set_attribute("durable.replay.from_step", replay_from_step)
        if step_index is not None:
            span.set_attribute("durable.step.index", step_index)
            span.set_attribute("durable.step.idempotency_key", f"{run_id}:step:{step_index}")

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
    run_id: Optional[str] = None,
    step_index: Optional[int] = None,
    is_replay: bool = False,
) -> Iterator[Span]:
    """Context manager creating a tool execution child span."""
    with tracer.start_as_current_span(f"tool:{tool_name}") as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", tool_name)
        span.set_attribute("tool.name", tool_name)
        span.set_attribute("durable.execution.replayed", is_replay)
        if call_id:
            span.set_attribute("gen_ai.tool.call.id", call_id)
            span.set_attribute("tool.call_id", call_id)
        if run_id and step_index is not None:
            span.set_attribute("durable.step.idempotency_key", f"{run_id}:step:{step_index}:{tool_name}")
        if parameters:
            span.set_attribute("tool.parameters", str(parameters))

        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise
