"""
nexus_registry.registry
~~~~~~~~~~~~~~~~~~~~~~~

Dynamic tool registry, schema contracts, versioning, and secure execution dispatcher.
Integrates circuit breakers, policy validation, timeouts, and OpenTelemetry instrumentation.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from nexus_registry.contracts import ToolDefinition, ToolCallRequest, ToolCallResult
from nexus_registry.policy import ToolPolicyEngine, ApprovalRequiredError, PolicyViolationError
from nexus_runtime.reliability.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from nexus_runtime.reliability.timeouts import run_with_timeout, OperationTimeoutError
from nexus_runtime.telemetry.otel import trace_tool_span
from nexus_runtime.telemetry.metrics import runtime_metrics


ToolHandler = Callable[..., Any]


class ToolRegistry:
    """
    Enterprise tool registry with schema contract versioning, sandboxed execution,
    and resilience guards.
    """

    def __init__(self, policy_engine: Optional[ToolPolicyEngine] = None) -> None:
        self.policy_engine = policy_engine or ToolPolicyEngine()
        self._tools: Dict[str, Dict[str, Tuple[ToolDefinition, ToolHandler]]] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    def register(
        self,
        tool_def: ToolDefinition,
        handler: ToolHandler,
    ) -> None:
        """Registers a tool under its name and version."""
        name = tool_def.name
        version = tool_def.version

        if name not in self._tools:
            self._tools[name] = {}
        self._tools[name][version] = (tool_def, handler)

        if name not in self._circuit_breakers:
            self._circuit_breakers[name] = CircuitBreaker(name=f"tool_cb_{name}", failure_threshold=3, recovery_timeout=15.0)

    def get_tool(self, name: str, version: Optional[str] = None) -> Optional[Tuple[ToolDefinition, ToolHandler]]:
        """Retrieves tool by name and specific or latest version."""
        if name not in self._tools:
            return None
        versions = self._tools[name]
        if version:
            return versions.get(version)
        # Default to latest version registered
        latest_ver = sorted(versions.keys())[-1]
        return versions[latest_ver]

    def list_tools(self, tag: Optional[str] = None) -> List[ToolDefinition]:
        """Lists latest version of registered tools, optionally filtered by tag."""
        definitions: List[ToolDefinition] = []
        for name, versions in self._tools.items():
            latest_ver = sorted(versions.keys())[-1]
            tool_def, _ = versions[latest_ver]
            if tag is None or tag in tool_def.tags:
                definitions.append(tool_def)
        return definitions

    async def execute(
        self,
        request: ToolCallRequest,
        tenant_id: Optional[str] = None,
    ) -> ToolCallResult:
        """
        Executes a registered tool with full security policy, circuit breaker,
        timeout guards, and telemetry tracking.
        """
        tool_entry = self.get_tool(request.tool_name, request.version)
        if not tool_entry:
            return ToolCallResult(
                call_id=request.call_id,
                tool_name=request.tool_name,
                status="error",
                error=f"Tool '{request.tool_name}' not found in registry.",
            )

        tool_def, handler = tool_entry
        start_time = time.time()

        # 1. Policy & Validation Gate
        try:
            self.policy_engine.validate_request(tool_def, request, tenant_id=tenant_id)
        except ApprovalRequiredError as exc:
            return ToolCallResult(
                call_id=request.call_id,
                tool_name=request.tool_name,
                status="approval_required",
                error=str(exc),
                output={"approval_token": exc.approval_token, "requires_approval": True},
            )
        except PolicyViolationError as exc:
            return ToolCallResult(
                call_id=request.call_id,
                tool_name=request.tool_name,
                status="error",
                error=str(exc),
            )

        cb = self._circuit_breakers[tool_def.name]

        # 2. Execution wrapped in OTel tracing, CircuitBreaker, and Timeout
        with trace_tool_span(tool_def.name, call_id=request.call_id, parameters=request.arguments):
            try:
                async def _invoke():
                    if inspect.iscoroutinefunction(handler):
                        return await handler(**request.arguments)
                    return handler(**request.arguments)

                output = await cb.call(
                    run_with_timeout,
                    _invoke(),
                    timeout_seconds=tool_def.timeout_seconds,
                    operation_name=f"tool_{tool_def.name}",
                )

                duration_ms = (time.time() - start_time) * 1000
                runtime_metrics.record_tool_call(tool_def.name, success=True, duration_ms=duration_ms)

                return ToolCallResult(
                    call_id=request.call_id,
                    tool_name=tool_def.name,
                    status="success",
                    output=output,
                    duration_ms=duration_ms,
                )

            except (CircuitBreakerOpenError, OperationTimeoutError, Exception) as exc:
                duration_ms = (time.time() - start_time) * 1000
                runtime_metrics.record_tool_call(tool_def.name, success=False, duration_ms=duration_ms)
                return ToolCallResult(
                    call_id=request.call_id,
                    tool_name=tool_def.name,
                    status="error",
                    error=f"Execution error in '{tool_def.name}': {str(exc)}",
                    duration_ms=duration_ms,
                )
