"""
convo_sdk.streaming
~~~~~~~~~~~~~~~~~~~

Asynchronous Server-Sent Events (SSE) parser for agent runtime events.
"""

from __future__ import annotations

import json
from typing import AsyncIterator
import httpx
from convo_sdk.models import AgentEvent


async def parse_sse_stream(response: httpx.Response) -> AsyncIterator[AgentEvent]:
    """
    Parses SSE lines ("event: ...", "data: ...") into typed AgentEvent objects.
    """
    current_event = "message"
    async for line in response.aiter_lines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("event:"):
            current_event = line.replace("event:", "").strip()
        elif line.startswith("data:"):
            raw_data = line.replace("data:", "").strip()
            try:
                data_dict = json.loads(raw_data)
                # If the raw data is already a full GraphEvent dict
                if "event_type" in data_dict and "run_id" in data_dict:
                    yield AgentEvent(**data_dict)
                else:
                    yield AgentEvent(
                        event_type=current_event,
                        run_id=data_dict.get("run_id", "unknown"),
                        step_index=data_dict.get("step_index", 0),
                        node_name=data_dict.get("node_name"),
                        data=data_dict,
                    )
            except Exception:
                yield AgentEvent(
                    event_type=current_event,
                    run_id="unknown",
                    step_index=0,
                    data={"raw": raw_data},
                )
