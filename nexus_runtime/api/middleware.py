"""
nexus_runtime.api.middleware
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

FastAPI middleware for Idempotency enforcement, Tenant isolation,
and OpenTelemetry context propagation.
"""

from __future__ import annotations

import contextvars
import json
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from nexus_runtime.reliability.idempotency import IdempotencyManager, IdempotencyConflictError
from nexus_runtime.telemetry.otel import extract_trace_context


tenant_context_var: contextvars.ContextVar[str] = contextvars.ContextVar("tenant_id", default="tenant-default")


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Extracts and sets the active tenant context for multi-tenant isolation."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        tenant_id = request.headers.get("X-Tenant-ID", "tenant-default")
        token = tenant_context_var.set(tenant_id)
        try:
            response = await call_next(request)
            response.headers["X-Tenant-ID"] = tenant_id
            return response
        finally:
            tenant_context_var.reset(token)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Guarantees at-most-once execution for mutating requests (POST) containing
    an `X-Idempotency-Key` header.
    """

    def __init__(self, app, idempotency_manager: IdempotencyManager) -> None:
        super().__init__(app)
        self.idempotency_mgr = idempotency_manager

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        idempotency_key = request.headers.get("X-Idempotency-Key")
        if not idempotency_key or request.method != "POST":
            return await call_next(request)

        tenant_id = request.headers.get("X-Tenant-ID", "tenant-default")

        # Read and cache body
        body_bytes = await request.body()
        payload = {}
        if body_bytes:
            try:
                payload = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                payload = {"raw_body": body_bytes.decode("utf-8", errors="ignore")}

        try:
            is_new, cached_data = await self.idempotency_mgr.acquire_or_get(
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                payload=payload,
            )
        except IdempotencyConflictError as exc:
            return JSONResponse(
                status_code=409,
                content={"error": "IdempotencyConflict", "message": str(exc)},
            )

        if not is_new and cached_data is not None:
            return JSONResponse(
                status_code=200,
                content=cached_data,
                headers={"X-Cache-Lookup": "HIT-IDEMPOTENCY"},
            )

        # Execute downstream request
        response = await call_next(request)

        if 200 <= response.status_code < 300:
            # Capture response body to cache
            res_body = [chunk async for chunk in response.body_iterator]
            full_body = b"".join(res_body)
            try:
                res_json = json.loads(full_body.decode("utf-8"))
                await self.idempotency_mgr.complete(tenant_id, idempotency_key, res_json)
            except Exception:
                pass
            return Response(
                content=full_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        else:
            await self.idempotency_mgr.fail(tenant_id, idempotency_key, f"Status {response.status_code}")
            return response
