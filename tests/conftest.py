"""
tests.conftest
~~~~~~~~~~~~~~

Pytest configuration, async event loop fixtures, and runtime component mocks.
"""

import pytest
import httpx
from nexus_registry.registry import ToolRegistry
from nexus_registry.builtin_tools import register_builtin_tools
from nexus_runtime.core.checkpointer import InMemoryCheckpointer
from nexus_runtime.persistence.graph_store import GraphStore
from nexus_runtime.persistence.vector_store import VectorMemoryStore
from nexus_runtime.reliability.idempotency import IdempotencyManager
from nexus_runtime.api.app import create_app
from nexus_sdk.client import NexusClient


@pytest.fixture
def tool_registry() -> ToolRegistry:
    reg = ToolRegistry()
    register_builtin_tools(reg)
    return reg


@pytest.fixture
def checkpointer() -> InMemoryCheckpointer:
    return InMemoryCheckpointer()


@pytest.fixture
def graph_store() -> GraphStore:
    return GraphStore()


@pytest.fixture
def vector_store() -> VectorMemoryStore:
    return VectorMemoryStore()


@pytest.fixture
def idempotency_mgr() -> IdempotencyManager:
    return IdempotencyManager()


@pytest.fixture
def app(tool_registry, checkpointer, graph_store, vector_store, idempotency_mgr):
    return create_app(
        tool_registry=tool_registry,
        checkpointer=checkpointer,
        graph_store=graph_store,
        vector_store=vector_store,
        idempotency_manager=idempotency_mgr,
    )


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with NexusClient(base_url="http://testserver", tenant_id="test-tenant", transport=transport) as c:
        yield c
