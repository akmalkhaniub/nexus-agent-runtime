"""
nexus_runtime.telemetry.metrics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Operational telemetry collector for runtime metrics, token spend,
latencies, and tool failure rates.
"""

from __future__ import annotations

import collections
import time
from typing import Any, Dict, List


class RuntimeMetricsCollector:
    """
    Collects real-time operational telemetry for dashboarding and evaluation.
    """

    def __init__(self) -> None:
        self.runs_total: int = 0
        self.runs_succeeded: int = 0
        self.runs_failed: int = 0
        self.active_runs: int = 0

        self.tool_calls_total: int = 0
        self.tool_calls_failed: int = 0
        self.tool_counts_by_name: collections.Counter[str] = collections.Counter()

        self.input_tokens_total: int = 0
        self.output_tokens_total: int = 0

        self.run_latencies_ms: List[float] = []
        self.recent_events: collections.deque[Dict[str, Any]] = collections.deque(maxlen=100)

    def record_run_start(self, run_id: str, tenant_id: str) -> None:
        self.runs_total += 1
        self.active_runs += 1
        self.recent_events.append({
            "event": "run_started",
            "run_id": run_id,
            "tenant_id": tenant_id,
            "timestamp": time.time(),
        })

    def record_run_finish(self, run_id: str, success: bool, duration_ms: float) -> None:
        self.active_runs = max(0, self.active_runs - 1)
        if success:
            self.runs_succeeded += 1
        else:
            self.runs_failed += 1
        self.run_latencies_ms.append(duration_ms)
        self.recent_events.append({
            "event": "run_finished",
            "run_id": run_id,
            "success": success,
            "duration_ms": duration_ms,
            "timestamp": time.time(),
        })

    def record_tool_call(self, tool_name: str, success: bool, duration_ms: float) -> None:
        self.tool_calls_total += 1
        self.tool_counts_by_name[tool_name] += 1
        if not success:
            self.tool_calls_failed += 1

    def record_token_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens_total += input_tokens
        self.output_tokens_total += output_tokens

    def get_summary(self) -> Dict[str, Any]:
        avg_latency = (
            sum(self.run_latencies_ms) / len(self.run_latencies_ms)
            if self.run_latencies_ms else 0.0
        )
        return {
            "runs": {
                "total": self.runs_total,
                "active": self.active_runs,
                "succeeded": self.runs_succeeded,
                "failed": self.runs_failed,
                "avg_duration_ms": round(avg_latency, 2),
            },
            "tools": {
                "total_calls": self.tool_calls_total,
                "failed_calls": self.tool_calls_failed,
                "breakdown": dict(self.tool_counts_by_name),
            },
            "tokens": {
                "input_total": self.input_tokens_total,
                "output_total": self.output_tokens_total,
                "grand_total": self.input_tokens_total + self.output_tokens_total,
            },
        }


# Global singleton instance
runtime_metrics = RuntimeMetricsCollector()
