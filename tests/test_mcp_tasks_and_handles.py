"""Tests for durable SQLite MCP Tasks, URL/form elicitation, HMAC opaque state handles & completions."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from nexus_runtime.api.app import create_app
from nexus_runtime.core.checkpointer import SQLiteCheckpointer
from nexus_runtime.core.state_handles import StateHandleManager


def test_durable_sqlite_mcp_tasks_survive_app_restart(tmp_path: Path) -> None:
    db_file = str(tmp_path / "nexus_tasks.db")
    shared_secret = "shared-cluster-hmac-secret"

    app_1 = create_app(
        checkpointer=SQLiteCheckpointer(db_path=db_file),
        state_handle_manager=StateHandleManager(secret=shared_secret),
    )
    client_1 = TestClient(app_1)

    start_resp = client_1.post(
        "/api/v1/mcp/tasks/rpc",
        headers={"X-Tenant-ID": "tenant-alpha", "X-Agent-Principal": "sre-alice"},
        json={
            "jsonrpc": "2.0",
            "id": "req-1",
            "method": "tasks/start",
            "params": {"intent": "Rollback canary deployment", "requires_approval": True},
        },
    )
    assert start_resp.status_code == 200
    result_1 = start_resp.json()["result"]
    task = result_1["task"]
    handle = result_1["_meta"]["state_handle"]
    assert task["status"] == "input_required"
    assert task["elicitation"]["mode"] == "form"
    task_id = task["taskId"]

    # Simulate process restart / request routed to a second replica sharing SQLite & HMAC key
    app_2 = create_app(
        checkpointer=SQLiteCheckpointer(db_path=db_file),
        state_handle_manager=StateHandleManager(secret=shared_secret),
    )
    client_2 = TestClient(app_2)

    get_resp = client_2.post(
        "/api/v1/mcp/tasks/rpc",
        headers={"X-Tenant-ID": "tenant-alpha", "X-Agent-Principal": "sre-alice"},
        json={
            "jsonrpc": "2.0",
            "id": "req-2",
            "method": "tasks/get",
            "params": {"taskId": task_id, "_meta": {"state_handle": handle}},
        },
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["result"]["task"]["status"] == "input_required"

    update_resp = client_2.post(
        "/api/v1/mcp/tasks/rpc",
        headers={"X-Tenant-ID": "tenant-alpha", "X-Agent-Principal": "sre-alice"},
        json={
            "jsonrpc": "2.0",
            "id": "req-3",
            "method": "tasks/update",
            "params": {
                "taskId": task_id,
                "action": "accept",
                "input": {"approved": True, "reason": "Verified error budget burn"},
                "_meta": {"state_handle": handle},
            },
        },
    )
    assert update_resp.status_code == 200
    updated_task = update_resp.json()["result"]["task"]
    assert updated_task["status"] == "completed"
    assert updated_task["result"]["structuredContent"]["resumed"] is True

    # Cancelling an already completed task returns JSON-RPC error
    cancel_done = client_2.post(
        "/api/v1/mcp/tasks/rpc",
        headers={"X-Tenant-ID": "tenant-alpha", "X-Agent-Principal": "sre-alice"},
        json={"jsonrpc": "2.0", "id": "req-4", "method": "tasks/cancel", "params": {"taskId": task_id}},
    )
    assert cancel_done.status_code == 200
    assert cancel_done.json()["error"]["code"] == -32004


def test_opaque_state_handle_tamper_and_cross_tenant_rejection(tmp_path: Path) -> None:
    db_file = str(tmp_path / "nexus_authz.db")
    app = create_app(
        checkpointer=SQLiteCheckpointer(db_path=db_file),
        state_handle_manager=StateHandleManager(secret="strict-handle-secret"),
    )
    client = TestClient(app)

    started = client.post(
        "/api/v1/mcp/tasks/rpc",
        headers={"X-Tenant-ID": "tenant-alpha", "X-Agent-Principal": "alice"},
        json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tasks/start",
            "params": {"intent": "Rotate API key", "requires_approval": True, "elicitation_mode": "url"},
        },
    )
    assert started.status_code == 200
    task = started.json()["result"]["task"]
    assert task["elicitation"]["mode"] == "url"
    assert "consent?task_id=" in task["elicitation"]["url"]
    handle = started.json()["result"]["_meta"]["state_handle"]
    task_id = task["taskId"]

    # 1. Cross-tenant / cross-user replay of stolen handle + taskId is rejected with 403
    cross_tenant = client.post(
        "/api/v1/mcp/tasks/rpc",
        headers={"X-Tenant-ID": "tenant-beta", "X-Agent-Principal": "eve"},
        json={
            "jsonrpc": "2.0",
            "id": "2",
            "method": "tasks/get",
            "params": {"taskId": task_id, "_meta": {"state_handle": handle}},
        },
    )
    assert cross_tenant.status_code == 403

    # 2. Tampered HMAC handle is rejected with 403
    tampered_handle = handle[:-4] + ("AAAA" if not handle.endswith("AAAA") else "BBBB")
    tampered = client.post(
        "/api/v1/mcp/tasks/rpc",
        headers={"X-Tenant-ID": "tenant-alpha", "X-Agent-Principal": "alice"},
        json={
            "jsonrpc": "2.0",
            "id": "3",
            "method": "tasks/get",
            "params": {"taskId": task_id, "_meta": {"state_handle": tampered_handle}},
        },
    )
    assert tampered.status_code == 403

    # 3. Direct task_id guess without handle from another principal still rejected with 403
    direct_guess = client.post(
        "/api/v1/mcp/tasks/rpc",
        headers={"X-Tenant-ID": "tenant-alpha", "X-Agent-Principal": "mallory"},
        json={"jsonrpc": "2.0", "id": "4", "method": "tasks/cancel", "params": {"taskId": task_id}},
    )
    assert direct_guess.status_code == 403

    # 4. Owner can cancel active task
    owner_cancel = client.post(
        "/api/v1/mcp/tasks/rpc",
        headers={"X-Tenant-ID": "tenant-alpha", "X-Agent-Principal": "alice"},
        json={"jsonrpc": "2.0", "id": "5", "method": "tasks/cancel", "params": {"taskId": task_id}},
    )
    assert owner_cancel.status_code == 200
    assert owner_cancel.json()["result"]["task"]["status"] == "cancelled"


def test_mcp_completion_complete_and_resource_links() -> None:
    app = create_app()
    client = TestClient(app)

    comp = client.post(
        "/api/v1/mcp/tasks/rpc",
        json={
            "jsonrpc": "2.0",
            "id": "c-1",
            "method": "completion/complete",
            "params": {"argument": {"name": "cluster", "value": "prod-"}},
        },
    )
    assert comp.status_code == 200
    values = comp.json()["result"]["completion"]["values"]
    assert values == ["prod-us-east-1", "prod-eu-west-1"]

    immediate = client.post(
        "/api/v1/mcp/tasks/rpc",
        json={
            "jsonrpc": "2.0",
            "id": "c-2",
            "method": "tasks/start",
            "params": {"intent": "Generate daily health digest", "complete_immediately": True},
        },
    )
    assert immediate.status_code == 200
    res_links = immediate.json()["result"]["task"]["result"]["resourceLinks"]
    assert res_links[0]["type"] == "resource_link"
    assert res_links[0]["uri"].startswith("nexus://runs/")
