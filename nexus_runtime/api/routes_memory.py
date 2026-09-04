"""
nexus_runtime.api.routes_memory
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Endpoints for querying the dual persistence layer (Graph entity store & Vector memory store).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from nexus_runtime.persistence.vector_store import SearchResult, VectorDocument


router = APIRouter(prefix="/api/v1/memory", tags=["Persistence & Memory"])


class VectorAddRequest(BaseModel):
    id: str
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VectorSearchRequest(BaseModel):
    query: str
    top_k: int = 5
    filter_metadata: Optional[Dict[str, Any]] = None


@router.post("/vector", response_model=VectorDocument)
async def add_vector_document(req: VectorAddRequest, request: Request):
    """Indexes a document or episodic memory into the semantic vector store."""
    vector_store = request.app.state.vector_store
    return vector_store.add(doc_id=req.id, text=req.text, metadata=req.metadata)


@router.post("/vector/search", response_model=List[SearchResult])
async def search_vector_memory(req: VectorSearchRequest, request: Request):
    """Performs semantic similarity search over episodic memory and knowledge base."""
    vector_store = request.app.state.vector_store
    return vector_store.search(query=req.query, top_k=req.top_k, filter_metadata=req.filter_metadata)


@router.get("/graph/node/{node_id}")
async def get_graph_node(node_id: str, request: Request):
    """Retrieves an entity or execution node from the graph persistence engine."""
    graph_store = request.app.state.graph_store
    node = graph_store.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found in graph store.")
    return node


@router.get("/graph/subgraph/{node_id}")
async def get_connected_subgraph(
    node_id: str,
    request: Request,
    depth: int = Query(2, ge=1, le=5),
):
    """Traverses connected entities starting from node_id up to specified depth."""
    graph_store = request.app.state.graph_store
    return graph_store.find_connected_subgraph(start_node_id=node_id, max_depth=depth)
