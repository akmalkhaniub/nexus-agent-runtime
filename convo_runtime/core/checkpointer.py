"""
convo_runtime.core.checkpointer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Persistence contracts and implementations for workflow state checkpoints.
Enables deterministic replay, time-travel inspection, and pause/resume workflows.
"""

from __future__ import annotations

import abc
import json
import sqlite3
from typing import Dict, List, Optional
from convo_runtime.core.state import StateSnapshot, Message


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


class InMemoryCheckpointer(BaseCheckpointer):
    """Thread-safe in-memory checkpointer suitable for testing and ephemeral execution."""

    def __init__(self) -> None:
        self._storage: Dict[str, List[StateSnapshot]] = {}

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
