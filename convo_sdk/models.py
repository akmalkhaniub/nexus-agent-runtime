"""
convo_sdk.models
~~~~~~~~~~~~~~~~

Pydantic models for runs, events, checkpoints, and tool calls used by consuming pods.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class AgentRun(BaseModel):
    run_id: str
    status: str
    final_state: Dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = 0.0
    total_steps: int = 0


class AgentEvent(BaseModel):
    event_type: str
    run_id: str
    step_index: int
    node_name: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class CheckpointInfo(BaseModel):
    snapshot_id: str
    step_index: int
    node_name: str
    values: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float


class ReplayExecution(BaseModel):
    original_run_id: str
    replay_run_id: str
    from_step_index: int
    restored_node: str
    final_state: Dict[str, Any]
    total_replay_steps: int
