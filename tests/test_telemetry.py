"""
tests.test_telemetry
~~~~~~~~~~~~~~~~~~~~

Tests for OpenTelemetry GenAI semantic spans, traceparent context propagation,
and operational telemetry collectors.
"""

import pytest
from nexus_runtime.telemetry.otel import (
    trace_workflow_span,
    trace_tool_span,
    inject_trace_context,
    extract_trace_context,
    get_recorded_spans,
    clear_recorded_spans,
)
from nexus_runtime.telemetry.metrics import RuntimeMetricsCollector


def test_opentelemetry_genai_spans():
    clear_recorded_spans()

    with trace_workflow_span("test_workflow", run_id="run_otel_99", tenant_id="tenant-sre"):
        with trace_tool_span("get_cluster_metrics", call_id="call_1", parameters={"cluster": "prod"}):
            pass

    spans = get_recorded_spans()
    assert len(spans) >= 2

    tool_span = next(s for s in spans if s.name == "tool:get_cluster_metrics")
    assert tool_span.attributes["tool.name"] == "get_cluster_metrics"
    assert tool_span.attributes["tool.call_id"] == "call_1"

    workflow_span = next(s for s in spans if s.name == "test_workflow")
    assert workflow_span.attributes["gen_ai.system"] == "nexus_agent_runtime"
    assert workflow_span.attributes["nexus.run_id"] == "run_otel_99"
    assert workflow_span.attributes["nexus.tenant_id"] == "tenant-sre"


def test_trace_context_propagation():
    headers = {}
    with trace_workflow_span("propagated_span", run_id="run_p"):
        inject_trace_context(headers)

    assert "traceparent" in headers
    extracted = extract_trace_context(headers)
    assert extracted is not None


def test_runtime_metrics_collector():
    collector = RuntimeMetricsCollector()

    collector.record_run_start("run_1", "tenant-alpha")
    assert collector.runs_total == 1
    assert collector.active_runs == 1

    collector.record_tool_call("restart_service_pod", success=True, duration_ms=45.2)
    collector.record_tool_call("restart_service_pod", success=False, duration_ms=12.0)
    collector.record_token_usage(input_tokens=150, output_tokens=50)
    collector.record_run_finish("run_1", success=True, duration_ms=120.5)

    assert collector.active_runs == 0
    assert collector.runs_succeeded == 1
    assert collector.tool_calls_total == 2
    assert collector.tool_calls_failed == 1

    summary = collector.get_summary()
    assert summary["runs"]["total"] == 1
    assert summary["tools"]["breakdown"]["restart_service_pod"] == 2
    assert summary["tokens"]["grand_total"] == 200
