"""
nexus_runtime.core.checkpointer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Persistence contracts and implementations for workflow state checkpoints.
Enables deterministic replay, time-travel inspection, and pause/resume workflows.
"""

from __future__ import annotations

import abc
import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from nexus_runtime.core.state import StateSnapshot, Message


@dataclass
class McpTaskRecord:
    """Durable record for an MCP Task backed by the runtime checkpointer."""

    task_id: str
    run_id: str
    tenant_id: str
    sub: str
    status: str  # working | input_required | completed | failed | cancelled
    progress: int = 0
    total: int = 1
    message: str = ""
    elicitation: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    updated_at: float = field(default_factory=time.time)

    def to_mcp_task(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "taskId": self.task_id,
            "runId": self.run_id,
            "status": self.status,
            "progress": self.progress,
            "total": self.total,
            "statusMessage": self.message,
            "updatedAt": self.updated_at,
        }
        if self.elicitation is not None:
            payload["elicitation"] = self.elicitation
        if self.result is not None:
            payload["result"] = self.result
        return payload


class BaseCheckpointer(abc.ABC):
    """Abstract checkpointer contract for persisting and retrieving state snapshots."""

    @abc.abstractmethod
    async def save_checkpoint(self, run_id: str, snapshot: StateSnapshot) -> None:
        """Persist a state snapshot for a given run."""
        pass

    @abc.abstractmethod
    async def get_checkpoint(self, run_id: str, step_index: int) -> Optional[StateSnapshot]:
        """Retrieve a specific snapshot by step index."""
        pass

    @abc.abstractmethod
    async def get_latest_checkpoint(self, run_id: str) -> Optional[StateSnapshot]:
        """Retrieve the most recent snapshot for a run."""
        pass

    @abc.abstractmethod
    async def list_checkpoints(self, run_id: str) -> List[StateSnapshot]:
        """List all historical snapshots recorded for a run in chronological order."""
        pass

    async def save_task(self, task: McpTaskRecord) -> None:
        """Persist or update a durable MCP Task record."""
        raise NotImplementedError

    async def get_task(self, task_id: str) -> Optional[McpTaskRecord]:
        """Retrieve a durable MCP Task record by ID."""
        raise NotImplementedError


class InMemoryCheckpointer(BaseCheckpointer):
    """Thread-safe in-memory checkpointer suitable for testing and ephemeral execution."""

    def __init__(self) -> None:
        self._storage: Dict[str, List[StateSnapshot]] = {}
        self._tasks: Dict[str, McpTaskRecord] = {}

    async def save_checkpoint(self, run_id: str, snapshot: StateSnapshot) -> None:
        if run_id not in self._storage:
            self._storage[run_id] = []
        # Store a deep clone to ensure immutability
        self._storage[run_id].append(snapshot.clone())

    async def get_checkpoint(self, run_id: str, step_index: int) -> Optional[StateSnapshot]:
        history = self._storage.get(run_id, [])
        for snap in history:
            if snap.step_index == step_index:
                return snap.clone()
        return None

    async def get_latest_checkpoint(self, run_id: str) -> Optional[StateSnapshot]:
        history = self._storage.get(run_id, [])
        if not history:
            return None
        return history[-1].clone()

    async def list_checkpoints(self, run_id: str) -> List[StateSnapshot]:
        history = self._storage.get(run_id, [])
        return [snap.clone() for snap in history]

    async def save_task(self, task: McpTaskRecord) -> None:
        self._tasks[task.task_id] = McpTaskRecord(
            task_id=task.task_id,
            run_id=task.run_id,
            tenant_id=task.tenant_id,
            sub=task.sub,
            status=task.status,
            progress=task.progress,
            total=task.total,
            message=task.message,
            elicitation=dict(task.elicitation) if task.elicitation is not None else None,
            result=dict(task.result) if task.result is not None else None,
            updated_at=task.updated_at,
        )

    async def get_task(self, task_id: str) -> Optional[McpTaskRecord]:
        task = self._tasks.get(task_id)
        if not task:
            return None
        return McpTaskRecord(
            task_id=task.task_id,
            run_id=task.run_id,
            tenant_id=task.tenant_id,
            sub=task.sub,
            status=task.status,
            progress=task.progress,
            total=task.total,
            message=task.message,
            elicitation=dict(task.elicitation) if task.elicitation is not None else None,
            result=dict(task.result) if task.result is not None else None,
            updated_at=task.updated_at,
        )


class SQLiteCheckpointer(BaseCheckpointer):
    """Durable SQLite-backed checkpointer for persistent production or local developer runs."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    run_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    node_name TEXT NOT NULL,
                    values_json TEXT NOT NULL,
                    messages_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (run_id, step_index)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mcp_tasks (
                    task_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    sub TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    elicitation_json TEXT,
                    result_json TEXT,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    async def save_checkpoint(self, run_id: str, snapshot: StateSnapshot) -> None:
        messages_data = [m.model_dump() for m in snapshot.messages]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO checkpoints 
                (run_id, step_index, snapshot_id, node_name, values_json, messages_json, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    snapshot.step_index,
                    snapshot.snapshot_id,
                    snapshot.node_name,
                    json.dumps(snapshot.values),
                    json.dumps(messages_data),
                    json.dumps(snapshot.metadata),
                    snapshot.timestamp,
                ),
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mcp_tasks (
                    task_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    sub TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    elicitation_json TEXT,
                    result_json TEXT,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    async def get_checkpoint(self, run_id: str, step_index: int) -> Optional[StateSnapshot]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT snapshot_id, step_index, node_name, values_json, messages_json, metadata_json, created_at
                FROM checkpoints
                WHERE run_id = ? AND step_index = ?
                """,
                (run_id, step_index),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_snapshot(row)

    async def get_latest_checkpoint(self, run_id: str) -> Optional[StateSnapshot]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT snapshot_id, step_index, node_name, values_json, messages_json, metadata_json, created_at
                FROM checkpoints
                WHERE run_id = ?
                ORDER BY step_index DESC
                LIMIT 1
                """,
                (run_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_snapshot(row)

    async def list_checkpoints(self, run_id: str) -> List[StateSnapshot]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT snapshot_id, step_index, node_name, values_json, messages_json, metadata_json, created_at
                FROM checkpoints
                WHERE run_id = ?
                ORDER BY step_index ASC
                """,
                (run_id,),
            )
            rows = cursor.fetchall()
            return [self._row_to_snapshot(r) for r in rows]

    def _row_to_snapshot(self, row: tuple) -> StateSnapshot:
        snap_id, step_idx, node_name, values_json, msgs_json, meta_json, created_at = row
        messages = [Message(**m) for m in json.loads(msgs_json)]
        return StateSnapshot(
            snapshot_id=snap_id,
            step_index=step_idx,
            node_name=node_name,
            values=json.loads(values_json),
            messages=messages,
            metadata=json.loads(meta_json),
            timestamp=created_at,
        )

    async def save_task(self, task: McpTaskRecord) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO mcp_tasks
                (task_id, run_id, tenant_id, sub, status, progress, total, message, elicitation_json, result_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.run_id,
                    task.tenant_id,
                    task.sub,
                    task.status,
                    task.progress,
                    task.total,
                    task.message,
                    json.dumps(task.elicitation) if task.elicitation is not None else None,
                    json.dumps(task.result) if task.result is not None else None,
                    task.updated_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    async def get_task(self, task_id: str) -> Optional[McpTaskRecord]:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT task_id, run_id, tenant_id, sub, status, progress, total, message, elicitation_json, result_json, updated_at
                FROM mcp_tasks
                WHERE task_id = ?
                """,
                (task_id,),
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        if not row:
            return None
        (
            task_id_val,
            run_id,
            tenant_id,
            sub,
            status,
            progress,
            total,
            message,
            elicit_json,
            res_json,
            updated_at,
        ) = row
        return McpTaskRecord(
            task_id=task_id_val,
            run_id=run_id,
            tenant_id=tenant_id,
            sub=sub,
            status=status,
            progress=progress,
            total=total,
            message=message,
            elicitation=json.loads(elicit_json) if elicit_json else None,
            result=json.loads(res_json) if res_json else None,
            updated_at=updated_at,
        )
