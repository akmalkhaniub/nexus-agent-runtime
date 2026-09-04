"""
tests.test_persistence
~~~~~~~~~~~~~~~~~~~~~~

Tests for dual-tier persistence engine: GraphStore and VectorMemoryStore.
"""

import pytest
from nexus_runtime.persistence.graph_store import GraphStore
from nexus_runtime.persistence.vector_store import VectorMemoryStore


def test_graph_store_nodes_edges_and_subgraph():
    graph = GraphStore()

    n1 = graph.add_node("svc_payment", label="Service", properties={"language": "python"})
    n2 = graph.add_node("pod_worker_1", label="Pod", properties={"status": "CrashLoopBackOff"})
    n3 = graph.add_node("alert_oom", label="Alert", properties={"severity": "CRITICAL"})

    graph.add_edge("svc_payment", "pod_worker_1", relationship="CONTAINS")
    graph.add_edge("pod_worker_1", "alert_oom", relationship="TRIGGERED")

    out_edges = graph.get_outgoing_edges("svc_payment")
    assert len(out_edges) == 1
    assert out_edges[0].target_id == "pod_worker_1"

    # Connected subgraph traversal
    subgraph = graph.find_connected_subgraph("svc_payment", max_depth=2)
    node_ids = [n["id"] for n in subgraph["nodes"]]
    assert "svc_payment" in node_ids
    assert "pod_worker_1" in node_ids
    assert "alert_oom" in node_ids


def test_vector_store_semantic_search_and_metadata_filter():
    vstore = VectorMemoryStore()

    vstore.add("doc_1", "Kubernetes cluster CPU utilization exceeded safe limits", metadata={"category": "sre"})
    vstore.add("doc_2", "Refund request guidelines for canceled subscription contracts", metadata={"category": "billing"})
    vstore.add("doc_3", "Pod memory leak detected in Java JVM worker process", metadata={"category": "sre"})

    # Search for SRE query
    results_sre = vstore.search("crash loop memory issue", top_k=2, filter_metadata={"category": "sre"})
    assert len(results_sre) <= 2
    assert all(r.document.metadata["category"] == "sre" for r in results_sre)

    # Search for Billing query
    results_billing = vstore.search("subscription refund", top_k=1)
    assert results_billing[0].document.id == "doc_2"
