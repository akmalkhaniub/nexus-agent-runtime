"""
nexus_runtime.core.state
~~~~~~~~~~~~~~~~~~~~~~~~

Core state management for graph-based agent orchestration.
Provides typed, immutable state snapshots, message histories, and state reducers.
"""

from __future__ import annotations

import copy
import time
import uuid
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class Message(BaseModel):
    """Represents a conversation message or tool output within an agent execution."""
    id: str = Field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:12]}")
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class StateSnapshot(BaseModel):
    """An immutable snapshot of workflow state at a specific execution step."""
    snapshot_id: str = Field(default_factory=lambda: f"snap_{uuid.uuid4().hex[:12]}")
    step_index: int
    node_name: str
    values: Dict[str, Any] = Field(default_factory=dict)
    messages: List[Message] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def clone(self) -> StateSnapshot:
        return copy.deepcopy(self)


class AgentState:
    """
    Mutable/working state container used during graph node execution.
    Supports dictionary access, message appending, and snapshot generation.
    """

    def __init__(
        self,
        values: Optional[Dict[str, Any]] = None,
        messages: Optional[List[Message]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self._values: Dict[str, Any] = values.copy() if values else {}
        self._messages: List[Message] = list(messages) if messages else []
        self._metadata: Dict[str, Any] = metadata.copy() if metadata else {}

    @property
    def values(self) -> Dict[str, Any]:
        return self._values

    @property
    def messages(self) -> List[Message]:
        return self._messages

    @property
    def metadata(self) -> Dict[str, Any]:
        return self._metadata

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._values[key] = value

    def update(self, new_values: Dict[str, Any]) -> None:
        self._values.update(new_values)

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._values[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self._values

    def add_message(
        self,
        role: Literal["system", "user", "assistant", "tool"],
        content: str,
        name: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Message:
        msg = Message(
            role=role,
            content=content,
            name=name,
            tool_call_id=tool_call_id,
            tool_calls=tool_calls,
            metadata=metadata or {},
        )
        self._messages.append(msg)
        return msg

    def snapshot(self, step_index: int, node_name: str, metadata: Optional[Dict[str, Any]] = None) -> StateSnapshot:
        return StateSnapshot(
            step_index=step_index,
            node_name=node_name,
            values=copy.deepcopy(self._values),
            messages=copy.deepcopy(self._messages),
            metadata=metadata or {},
        )

    def fork(self) -> AgentState:
        return AgentState(
            values=copy.deepcopy(self._values),
            messages=copy.deepcopy(self._messages),
            metadata=copy.deepcopy(self._metadata),
        )

    @classmethod
    def from_snapshot(cls, snap: StateSnapshot) -> AgentState:
        return cls(
            values=copy.deepcopy(snap.values),
            messages=copy.deepcopy(snap.messages),
            metadata=copy.deepcopy(snap.metadata),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "values": self._values,
            "messages": [m.to_dict() for m in self._messages],
            "metadata": self._metadata,
        }
