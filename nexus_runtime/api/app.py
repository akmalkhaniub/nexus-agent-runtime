"""
nexus_runtime.api.app
~~~~~~~~~~~~~~~~~~~~~

FastAPI application factory for the Nexus Shared Agent Runtime.
Integrates tool registry, checkpointer, persistence, idempotency, and telemetry.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nexus_registry.registry import ToolRegistry
from nexus_registry.builtin_tools import register_builtin_tools
from nexus_runtime.core.checkpointer import BaseCheckpointer, InMemoryCheckpointer
from nexus_runtime.core.state_handles import StateHandleManager
from nexus_runtime.persistence.graph_store import GraphStore
from nexus_runtime.persistence.vector_store import VectorMemoryStore
from nexus_runtime.reliability.idempotency import IdempotencyManager
from nexus_runtime.api.middleware import IdempotencyMiddleware, TenantContextMiddleware

from nexus_runtime.api.routes_runs import router as runs_router
from nexus_runtime.api.routes_tools import router as tools_router
from nexus_runtime.api.routes_replay import router as replay_router
from nexus_runtime.api.routes_memory import router as memory_router
from nexus_runtime.api.routes_telemetry import router as telemetry_router
from nexus_runtime.api.routes_mcp_tasks import router as mcp_tasks_router


def create_app(
    tool_registry: Optional[ToolRegistry] = None,
    checkpointer: Optional[BaseCheckpointer] = None,
    graph_store: Optional[GraphStore] = None,
    vector_store: Optional[VectorMemoryStore] = None,
    idempotency_manager: Optional[IdempotencyManager] = None,
    state_handle_manager: Optional[StateHandleManager] = None,
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
    state_handle_manager = state_handle_manager or StateHandleManager()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup hook
        yield
        # Shutdown hook

    app = FastAPI(
        title="NEXUS Agentic Platform Runtime",
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
    app.state.state_handle_manager = state_handle_manager

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
    app.include_router(mcp_tasks_router)

    @app.get("/healthz", tags=["System"])
    async def health_check():
        return {
            "status": "healthy",
            "service": "nexus-agent-runtime",
            "version": "1.0.0",
            "registered_tools_count": len(tool_registry.list_tools()),
        }

    return app
