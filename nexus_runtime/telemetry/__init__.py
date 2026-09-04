"""
nexus_runtime.telemetry
~~~~~~~~~~~~~~~~~~~~~~~

Telemetry and observability: OpenTelemetry spans conforming to GenAI conventions,
and operational metrics for latency, error rates, and token consumption.
"""

from nexus_runtime.telemetry.otel import (
    tracer,
    trace_workflow_span,
    trace_tool_span,
    inject_trace_context,
    extract_trace_context,
    get_recorded_spans,
    clear_recorded_spans,
)
from nexus_runtime.telemetry.metrics import runtime_metrics, RuntimeMetricsCollector

__all__ = [
    "tracer",
    "trace_workflow_span",
    "trace_tool_span",
    "inject_trace_context",
    "extract_trace_context",
    "get_recorded_spans",
    "clear_recorded_spans",
    "runtime_metrics",
    "RuntimeMetricsCollector",
]
