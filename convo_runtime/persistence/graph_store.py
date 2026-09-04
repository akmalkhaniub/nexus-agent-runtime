"""
convo_runtime.persistence.graph_store
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Graph persistence engine for workflow state machines, execution histories,
and entity-relationship memory.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    id: str
    label: str
    properties: Dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)


class GraphEdge(BaseModel):
    id: str = Field(default_factory=lambda: f"edge_{uuid.uuid4().hex[:8]}")
    source_id: str
    target_id: str
    relationship: str
    properties: Dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)


class GraphStore:
    """
    In-memory and durable graph database abstraction for entity relationships
    and workflow execution dependency graphs.
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, GraphNode] = {}
        self._edges: Dict[str, GraphEdge] = {}
        self._adj_out: Dict[str, Set[str]] = {}
        self._adj_in: Dict[str, Set[str]] = {}

    def add_node(self, node_id: str, label: str, properties: Optional[Dict[str, Any]] = None) -> GraphNode:
        node = GraphNode(id=node_id, label=label, properties=properties or {})
        self._nodes[node_id] = node
        if node_id not in self._adj_out:
            self._adj_out[node_id] = set()
        if node_id not in self._adj_in:
            self._adj_in[node_id] = set()
        return node

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        return self._nodes.get(node_id)

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relationship: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> GraphEdge:
        if source_id not in self._nodes:
            raise ValueError(f"Source node '{source_id}' does not exist in graph store.")
        if target_id not in self._nodes:
            raise ValueError(f"Target node '{target_id}' does not exist in graph store.")

        edge = GraphEdge(
            source_id=source_id,
            target_id=target_id,
            relationship=relationship,
            properties=properties or {},
        )
        self._edges[edge.id] = edge
        self._adj_out[source_id].add(edge.id)
        self._adj_in[target_id].add(edge.id)
        return edge

    def get_outgoing_edges(self, node_id: str, relationship: Optional[str] = None) -> List[GraphEdge]:
        edge_ids = self._adj_out.get(node_id, set())
        edges = [self._edges[eid] for eid in edge_ids]
        if relationship:
            edges = [e for e in edges if e.relationship == relationship]
        return edges

    def get_incoming_edges(self, node_id: str, relationship: Optional[str] = None) -> List[GraphEdge]:
        edge_ids = self._adj_in.get(node_id, set())
        edges = [self._edges[eid] for eid in edge_ids]
        if relationship:
            edges = [e for e in edges if e.relationship == relationship]
        return edges

    def find_nodes_by_label(self, label: str, property_filters: Optional[Dict[str, Any]] = None) -> List[GraphNode]:
        results = [n for n in self._nodes.values() if n.label == label]
        if property_filters:
            filtered = []
            for n in results:
                match = all(n.properties.get(k) == v for k, v in property_filters.items())
                if match:
                    filtered.append(n)
            return filtered
        return results

    def find_connected_subgraph(self, start_node_id: str, max_depth: int = 2) -> Dict[str, Any]:
        """Traverse connected entities starting from a root node up to max_depth."""
        visited_nodes: Set[str] = set()
        visited_edges: Set[str] = set()

        queue = [(start_node_id, 0)]
        while queue:
            curr_id, depth = queue.pop(0)
            if curr_id in visited_nodes:
                continue
            visited_nodes.add(curr_id)

            if depth < max_depth:
                out_edges = self.get_outgoing_edges(curr_id)
                for edge in out_edges:
                    visited_edges.add(edge.id)
                    if edge.target_id not in visited_nodes:
                        queue.append((edge.target_id, depth + 1))

        return {
            "nodes": [self._nodes[nid].model_dump() for nid in visited_nodes if nid in self._nodes],
            "edges": [self._edges[eid].model_dump() for eid in visited_edges if eid in self._edges],
        }

    def record_execution_step(
        self,
        run_id: str,
        step_index: int,
        node_name: str,
        state_values: Dict[str, Any],
    ) -> None:
        """Helper to project agent execution steps directly into the graph store."""
        run_node_id = f"run_{run_id}"
        if run_node_id not in self._nodes:
            self.add_node(run_node_id, label="AgentRun", properties={"run_id": run_id})

        step_node_id = f"run_{run_id}_step_{step_index}"
        self.add_node(
            step_node_id,
            label="ExecutionStep",
            properties={
                "step_index": step_index,
                "node_name": node_name,
                "values": state_values,
            },
        )
        if step_index == 0:
            self.add_edge(run_node_id, step_node_id, relationship="INITIALIZED_WITH")
        else:
            prev_step_node_id = f"run_{run_id}_step_{step_index - 1}"
            if prev_step_node_id in self._nodes:
                self.add_edge(prev_step_node_id, step_node_id, relationship="TRANSITIONED_TO")
