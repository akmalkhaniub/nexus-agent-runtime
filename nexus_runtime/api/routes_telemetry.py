"""
nexus_runtime.api.routes_telemetry
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Endpoints for inspecting live OpenTelemetry traces, latency histograms,
and operational reliability metrics.
"""

from __future__ import annotations

from typing import Any, Dict, List
from fastapi import APIRouter
from nexus_runtime.telemetry.metrics import runtime_metrics
from nexus_runtime.telemetry.otel import get_recorded_spans


router = APIRouter(prefix="/api/v1/telemetry", tags=["Observability & Telemetry"])


@router.get("/metrics")
async def get_runtime_metrics() -> Dict[str, Any]:
    """Returns aggregated runtime metrics (runs, tools, token spend, latencies)."""
    return runtime_metrics.get_summary()


@router.get("/spans")
async def get_telemetry_spans() -> List[Dict[str, Any]]:
    """Returns the most recent OpenTelemetry spans captured during agent execution."""
    spans = get_recorded_spans()
    serialized = []
    for s in spans[-50:]:
        serialized.append({
            "name": s.name,
            "trace_id": format(s.context.trace_id, "032x") if s.context else None,
            "span_id": format(s.context.span_id, "016x") if s.context else None,
            "status": s.status.status_code.name,
            "attributes": dict(s.attributes or {}),
            "start_time_ns": s.start_time,
            "end_time_ns": s.end_time,
        })
    return serialized
