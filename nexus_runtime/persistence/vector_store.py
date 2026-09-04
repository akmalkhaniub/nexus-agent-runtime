"""
nexus_runtime.persistence.vector_store
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Vector memory store for episodic agent memory and semantic retrieval (RAG).
Provides vector indexing, cosine similarity scoring, metadata filtering,
and pluggable embedding providers.
"""

from __future__ import annotations

import hashlib
import math
import time
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field


class VectorDocument(BaseModel):
    id: str
    text: str
    vector: List[float]
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)


class SearchResult(BaseModel):
    document: VectorDocument
    score: float


def default_deterministic_embedder(text: str, dim: int = 64) -> List[float]:
    """
    Fast, deterministic hash-based embedding generator.
    Produces repeatable normalized vectors across runs without external API dependencies.
    """
    tokens = text.lower().strip().split()
    vec = [0.0] * dim
    for token in tokens:
        h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        for i in range(dim):
            bit = (h >> (i % 32)) & 1
            vec[i] += 1.0 if bit else -1.0

    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        return [x / norm for x in vec]
    return [1.0 / math.sqrt(dim)] * dim


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Computes cosine similarity between two unit vectors."""
    if len(v1) != len(v2):
        raise ValueError(f"Vector dimensions do not match: {len(v1)} vs {len(v2)}")
    return float(sum(a * b for a, b in zip(v1, v2)))


class VectorMemoryStore:
    """
    In-memory vector database supporting semantic search, episodic memory recall,
    and metadata filtering.
    """

    def __init__(
        self,
        embedder: Optional[Callable[[str], List[float]]] = None,
        dimension: int = 64,
    ) -> None:
        self.dimension = dimension
        self.embedder = embedder or (lambda t: default_deterministic_embedder(t, dim=self.dimension))
        self._documents: Dict[str, VectorDocument] = {}

    def add(
        self,
        doc_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        vector: Optional[List[float]] = None,
    ) -> VectorDocument:
        if vector is None:
            vector = self.embedder(text)
        doc = VectorDocument(
            id=doc_id,
            text=text,
            vector=vector,
            metadata=metadata or {},
        )
        self._documents[doc_id] = doc
        return doc

    def get(self, doc_id: str) -> Optional[VectorDocument]:
        return self._documents.get(doc_id)

    def search(
        self,
        query: str,
        top_k: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        query_vector = self.embedder(query)
        candidates = list(self._documents.values())

        if filter_metadata:
            candidates = [
                d for d in candidates
                if all(d.metadata.get(k) == v for k, v in filter_metadata.items())
            ]

        scored: List[tuple[VectorDocument, float]] = []
        for doc in candidates:
            sim = cosine_similarity(query_vector, doc.vector)
            scored.append((doc, sim))

        scored.sort(key=lambda item: item[1], reverse=True)
        return [
            SearchResult(document=doc, score=score)
            for doc, score in scored[:top_k]
        ]

    def record_episodic_memory(
        self,
        run_id: str,
        workflow_name: str,
        summary: str,
        resolution_outcome: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> VectorDocument:
        """Saves a past workflow run summary into episodic memory for future agent recall."""
        mem_id = f"mem_{run_id}"
        meta = {
            "run_id": run_id,
            "workflow_name": workflow_name,
            "resolution_outcome": resolution_outcome,
            **(metadata or {}),
        }
        text = f"Workflow: {workflow_name}. Outcome: {resolution_outcome}. Summary: {summary}"
        return self.add(doc_id=mem_id, text=text, metadata=meta)
