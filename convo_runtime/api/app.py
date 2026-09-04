"""
convo_runtime.api.app
~~~~~~~~~~~~~~~~~~~~~

FastAPI application factory for the Convo Shared Agent Runtime.
Integrates tool registry, checkpointer, persistence, idempotency, and telemetry.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from convo_registry.registry import ToolRegistry
from convo_registry.builtin_tools import register_builtin_tools
from convo_runtime.core.checkpointer import BaseCheckpointer, InMemoryCheckpointer
from convo_runtime.persistence.graph_store import GraphStore
from convo_runtime.persistence.vector_store import VectorMemoryStore
from convo_runtime.reliability.idempotency import IdempotencyManager
from convo_runtime.api.middleware import IdempotencyMiddleware, TenantContextMiddleware

from convo_runtime.api.routes_runs import router as runs_router
from convo_runtime.api.routes_tools import router as tools_router
from convo_runtime.api.routes_replay import router as replay_router
from convo_runtime.api.routes_memory import router as memory_router
from convo_runtime.api.routes_telemetry import router as telemetry_router


def create_app(
    tool_registry: Optional[ToolRegistry] = None,
    checkpointer: Optional[BaseCheckpointer] = None,
    graph_store: Optional[GraphStore] = None,
    vector_store: Optional[VectorMemoryStore] = None,
    idempotency_manager: Optional[IdempotencyManager] = None,
) -> FastAPI:
    """
    Creates and configures the FastAPI application instance.
    """
    # Initialize components if not injected
    if tool_registry is None:
        tool_registry = ToolRegistry()
        register_builtin_tools(tool_registry)

    checkpointer = checkpointer or InMemoryCheckpointer()
    graph_store = graph_store or GraphStore()
    vector_store = vector_store or VectorMemoryStore()
    idempotency_manager = idempotency_manager or IdempotencyManager()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup hook
        yield
        # Shutdown hook

    app = FastAPI(
        title="CONVO Agentic Platform Runtime",
        description="Shared runtime, graph orchestrator, MCP tool registry, and observability API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Attach shared platform state
    app.state.tool_registry = tool_registry
    app.state.checkpointer = checkpointer
    app.state.graph_store = graph_store
    app.state.vector_store = vector_store
    app.state.idempotency_mgr = idempotency_manager

    # Middleware stack
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TenantContextMiddleware)
    app.add_middleware(IdempotencyMiddleware, idempotency_manager=idempotency_manager)

    # Include API Routers
    app.include_router(runs_router)
    app.include_router(tools_router)
    app.include_router(replay_router)
    app.include_router(memory_router)
    app.include_router(telemetry_router)

    @app.get("/healthz", tags=["System"])
    async def health_check():
        return {
            "status": "healthy",
            "service": "convo-agent-runtime",
            "version": "1.0.0",
            "registered_tools_count": len(tool_registry.list_tools()),
        }

    return app
