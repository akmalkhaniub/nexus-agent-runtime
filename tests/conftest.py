"""
tests.conftest
~~~~~~~~~~~~~~

Pytest configuration, async event loop fixtures, and runtime component mocks.
"""

import pytest
import httpx
from convo_registry.registry import ToolRegistry
from convo_registry.builtin_tools import register_builtin_tools
from convo_runtime.core.checkpointer import InMemoryCheckpointer
from convo_runtime.persistence.graph_store import GraphStore
from convo_runtime.persistence.vector_store import VectorMemoryStore
from convo_runtime.reliability.idempotency import IdempotencyManager
from convo_runtime.api.app import create_app
from convo_sdk.client import ConvoClient


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
    async with ConvoClient(base_url="http://testserver", tenant_id="test-tenant", transport=transport) as c:
        yield c
