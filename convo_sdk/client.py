"""
convo_sdk.client
~~~~~~~~~~~~~~~~

Fully typed, asynchronous ConvoClient for consuming engineering pods.
Supports workflow streaming, tool registry contracts, deterministic replay,
and telemetry inspection.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Union
import httpx

from convo_registry.contracts import ToolDefinition, ToolCallResult
from convo_sdk.models import AgentRun, AgentEvent, CheckpointInfo, ReplayExecution
from convo_sdk.streaming import parse_sse_stream
from convo_sdk.exceptions import ConvoAPIError, ApprovalRequiredSDKError


class RunsNamespace:
    def __init__(self, client: ConvoClient) -> None:
        self._client = client

    async def create(
        self,
        intent: str,
        context: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> AgentRun:
        """Executes an agent run to completion."""
        headers = {}
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key

        payload = {"intent": intent, "context": context or {}, "run_id": run_id}
        res = await self._client._request("POST", "/api/v1/runs", json=payload, headers=headers)
        return AgentRun(**res)

    async def stream(
        self,
        intent: str,
        context: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
    ) -> AsyncIterator[AgentEvent]:
        """Streams real-time events from the agent graph execution."""
        payload = {"intent": intent, "context": context or {}, "run_id": run_id}
        req = self._client._http.build_request("POST", "/api/v1/runs/stream", json=payload, headers=self._client._base_headers)
        res = await self._client._http.send(req, stream=True)
        if res.status_code >= 400:
            await res.aread()
            raise ConvoAPIError(res.status_code, res.text)

        async for event in parse_sse_stream(res):
            yield event

    async def get(self, run_id: str) -> Dict[str, Any]:
        """Retrieves status and snapshot for a run."""
        return await self._client._request("GET", f"/api/v1/runs/{run_id}")

    async def list_checkpoints(self, run_id: str) -> List[CheckpointInfo]:
        """Lists historical snapshots recorded for a run."""
        res = await self._client._request("GET", f"/api/v1/runs/{run_id}/checkpoints")
        return [CheckpointInfo(**s) for s in res]

    async def replay(
        self,
        run_id: str,
        step_index: int,
        state_overrides: Optional[Dict[str, Any]] = None,
        new_run_id: Optional[str] = None,
    ) -> ReplayExecution:
        """Deterministically replays an agent execution from a historical checkpoint step."""
        payload = {
            "step_index": step_index,
            "state_overrides": state_overrides or {},
            "new_run_id": new_run_id,
        }
        res = await self._client._request("POST", f"/api/v1/runs/{run_id}/replay", json=payload)
        return ReplayExecution(**res)


class ToolsNamespace:
    def __init__(self, client: ConvoClient) -> None:
        self._client = client

    async def list(self, tag: Optional[str] = None, mcp_format: bool = False) -> List[Dict[str, Any]]:
        """Lists registered tools in the platform registry."""
        params = {}
        if tag:
            params["tag"] = tag
        if mcp_format:
            params["mcp_format"] = "true"
        return await self._client._request("GET", "/api/v1/tools", params=params)

    async def register(
        self,
        tool_fn_or_def: Union[Callable, ToolDefinition],
        mock_return_value: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Registers a Python function or ToolDefinition into the shared runtime."""
        if hasattr(tool_fn_or_def, "__tool_definition__"):
            tool_def = tool_fn_or_def.__tool_definition__
        elif isinstance(tool_fn_or_def, ToolDefinition):
            tool_def = tool_fn_or_def
        else:
            raise ValueError("Target must be decorated with @tool or be an instance of ToolDefinition.")

        payload = {
            "definition": tool_def.model_dump(),
            "mock_return_value": mock_return_value,
        }
        return await self._client._request("POST", "/api/v1/tools", json=payload)

    async def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        approval_token: Optional[str] = None,
    ) -> ToolCallResult:
        """Executes a registered tool."""
        params = {}
        if approval_token:
            params["approval_token"] = approval_token
        res = await self._client._request(
            "POST",
            f"/api/v1/tools/{tool_name}/execute",
            json=arguments,
            params=params,
        )
        result = ToolCallResult(**res)
        if result.status == "approval_required":
            token = (result.output or {}).get("approval_token", "unknown")
            raise ApprovalRequiredSDKError(tool_name, token)
        return result

    async def approve(self, token: str) -> Dict[str, Any]:
        """Authorizes a human-in-the-loop token."""
        return await self._client._request("POST", "/api/v1/tools/approve", json={"token": token})


class MemoryNamespace:
    def __init__(self, client: ConvoClient) -> None:
        self._client = client

    async def add_vector(self, doc_id: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {"id": doc_id, "text": text, "metadata": metadata or {}}
        return await self._client._request("POST", "/api/v1/memory/vector", json=payload)

    async def search_vector(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        payload = {"query": query, "top_k": top_k}
        return await self._client._request("POST", "/api/v1/memory/vector/search", json=payload)

    async def get_graph_subgraph(self, node_id: str, depth: int = 2) -> Dict[str, Any]:
        return await self._client._request("GET", f"/api/v1/memory/graph/subgraph/{node_id}", params={"depth": depth})


class TelemetryNamespace:
    def __init__(self, client: ConvoClient) -> None:
        self._client = client

    async def get_metrics(self) -> Dict[str, Any]:
        return await self._client._request("GET", "/api/v1/telemetry/metrics")

    async def get_spans(self) -> List[Dict[str, Any]]:
        return await self._client._request("GET", "/api/v1/telemetry/spans")


class ConvoClient:
    """
    Main entry point for consuming pods building on the Convo Agent Platform.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: Optional[str] = None,
        tenant_id: str = "tenant-default",
        transport: Optional[httpx.AsyncBaseTransport] = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.tenant_id = tenant_id
        self._base_headers = {
            "X-Tenant-ID": tenant_id,
            "Content-Type": "application/json",
        }
        if api_key:
            self._base_headers["Authorization"] = f"Bearer {api_key}"

        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._base_headers,
            transport=transport,
            timeout=timeout,
        )

        self.runs = RunsNamespace(self)
        self.tools = ToolsNamespace(self)
        self.memory = MemoryNamespace(self)
        self.telemetry = TelemetryNamespace(self)

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        req_headers = {**self._base_headers, **(headers or {})}
        res = await self._http.request(method, path, json=json, params=params, headers=req_headers)
        if res.status_code >= 400:
            try:
                detail = res.json().get("detail", res.text)
            except Exception:
                detail = res.text
            raise ConvoAPIError(res.status_code, detail)
        return res.json()

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> ConvoClient:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
