# Proposed New Features & 2026 MCP Spec Roadmap (`nexus-agent-runtime`)

**Scope:** Alignment upgrades for Pluralsight *Model Context Protocol: Security and Safety* and *Model Context Protocol: Advanced Features*.  
**Baseline Reviewed:** [`docs/MCP_SPEC.md`](./MCP_SPEC.md), [`nexus_registry/contracts.py`](../nexus_registry/contracts.py), [`nexus_registry/policy.py`](../nexus_registry/policy.py), [`nexus_registry/mcp_adapter.py`](../nexus_registry/mcp_adapter.py), [`nexus_runtime/core/checkpointer.py`](../nexus_runtime/core/checkpointer.py), [`tests/test_durable_resume_and_mcp_trace.py`](../tests/test_durable_resume_and_mcp_trace.py)

---

## Current Baseline Strengths & Gaps

- **Already strong:** [`SQLiteCheckpointer`](../nexus_runtime/core/checkpointer.py#L72) supports durable pause/resume across restarts ([`test_durable_resume_and_mcp_trace.py`](../tests/test_durable_resume_and_mcp_trace.py#L14-L62)), `nexus_sdk/streaming.py` parses live SSE workflow events, and [`MCPProtocolAdapter`](../nexus_registry/mcp_adapter.py#L24) / [`ExternalMCPClientAdapter`](../nexus_registry/mcp_adapter.py#L73) propagate W3C `traceparent` via `params._meta`.
- **Protocol & security gaps relative to 2026 MCP specs:**
  - [`docs/MCP_SPEC.md`](./MCP_SPEC.md#L11) exposes a custom REST RPC path (`POST /api/v1/tools/mcp/rpc`) with plain `text` responses (`mcp_adapter.py:61-69`), no MCP `Tasks` methods (`tasks/get`, `tasks/update`, `tasks/cancel`), no `input-required` elicitation schema, no `ToolAnnotations`, and no OAuth 2.1 / RFC 9728 enforcement.
  - [`ToolPolicyEngine`](../nexus_registry/policy.py#L31) relies on regex string checks (`; rm -rf`, `drop table`, `shutdown`) and accepts unverified `tenant_id` / `approval_token` parameters rather than cryptographically validated identity claims.

---

## Priority 1 — MCP Tasks & Stateless Handle Upgrades (*Advanced Features*)

### 1. Bridge `SQLiteCheckpointer` Workflows to MCP Tasks (`tasks/get`, `tasks/update`, `tasks/cancel`)
- **Course Mapping:** *Advanced Features* (LO 1, LO 3)
- **Target Files:** `nexus_runtime/api/routes_mcp_tasks.py` (new), [`nexus_registry/mcp_adapter.py`](../nexus_registry/mcp_adapter.py), [`nexus_runtime/core/checkpointer.py`](../nexus_runtime/core/checkpointer.py)
- **Features to Add:**
  - Advertise the MCP **Tasks** extension capability cleanly on negotiation/request metadata.
  - Allow long-running `StateGraph` executions (`nexus_runtime/core/graph.py`) to return an MCP Task handle immediately instead of blocking HTTP connections.
  - Persist task status (`working`, `input_required`, `completed`, `failed`, `cancelled`) inside [`SQLiteCheckpointer`](../nexus_runtime/core/checkpointer.py#L72) so active tasks survive server process restarts.
  - Implement `tasks/get` polling, `tasks/update` resumption, `tasks/cancel` wired to async cancellation tokens (`nexus_runtime/reliability/timeouts.py`), and `notifications/progress` streamed from `StateGraph` node transitions.

### 2. Opaque Client-Side State Handles + Auth Separation
- **Course Mapping:** *Advanced Features* (LO 1), *Security & Safety* (LO 1)
- **Target Files:** `nexus_runtime/core/state_handles.py` (new), `nexus_runtime/api/middleware.py`
- **Features to Add:**
  - Support HMAC-SHA256 signed/encrypted opaque state tokens (`cursor` / `workflow_handle`) for stateless horizontal scaling, explicitly validating signature, expiry, and `tenant_id` / `sub` binding.
  - Add negative tests proving that presenting a guessed or stolen `run_id` / state handle without matching authenticated user identity fails authorization (`403`)—demonstrating that a handle is not authentication.

### 3. Native MCP Elicitation (`input-required` Form & URL Modes)
- **Course Mapping:** *Advanced Features* (LO 2), *Security & Safety* (LO 7)
- **Target Files:** [`nexus_registry/contracts.py`](../nexus_registry/contracts.py), [`nexus_registry/policy.py`](../nexus_registry/policy.py), [`nexus_registry/mcp_adapter.py`](../nexus_registry/mcp_adapter.py)
- **Features to Add:**
  - Map `workflow_paused` and `ToolCallResult.status == "approval_required"` (`contracts.py:68`) to standard MCP `input_required` tool/task payloads containing a strict JSON Schema form (`accept`, `decline`, `cancel`) and retry-on-input flow.
  - Support **URL-mode elicitation** for sensitive operations (API key entry, OAuth re-consent, or payment sign-off) so secrets never pass through chat prompts or form inputs.
  - Detect client elicitation capability in request metadata (`_meta`) and provide a deterministic policy fallback when non-interactive clients connect.

---

## Priority 2 — Rich Content, Completions & Security Hardening

### 4. `ToolAnnotations`, `structuredContent`, Multimodal Results & Completions
- **Course Mapping:** *Security & Safety* (LO 6), *Advanced Features* (LO 4)
- **Target Files:** [`nexus_registry/contracts.py`](../nexus_registry/contracts.py#L24-L52), [`nexus_registry/mcp_adapter.py`](../nexus_registry/mcp_adapter.py#L43-L70)
- **Features to Add:**
  - Extend `ToolDefinition` and `to_mcp_format()` / `from_mcp_format()` (`contracts.py:35-51`) with `annotations` (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) while ensuring `ExternalMCPClientAdapter` treats remote servers' annotations as untrusted hints until verified by local policy.
  - Extend `format_mcp_tool_call_response` (`mcp_adapter.py:43-70`) to emit typed `structuredContent`, `image` / `audio` content blocks, and `resource_link` references alongside plain text.
  - Add `completion/complete` support for prompt/resource arguments (for example suggesting registered cluster names or tool versions) backed by strict runtime schema validation.

### 5. OAuth 2.1 Resource Server Auth & Scope-Filtered `tools/list`
- **Course Mapping:** *Security & Safety* (LO 2, LO 3, LO 4)
- **Target Files:** `nexus_runtime/api/middleware.py`, [`nexus_registry/policy.py`](../nexus_registry/policy.py), [`nexus_registry/mcp_adapter.py`](../nexus_registry/mcp_adapter.py)
- **Features to Add:**
  - Add JWT verification (`sig`, `iss`, `aud`, `exp`) + `/.well-known/oauth-protected-resource` metadata on MCP HTTP routes rather than trusting `X-Tenant-ID` headers alone.
  - Filter `tools/list` in `MCPProtocolAdapter.format_mcp_tools_list_response` (`mcp_adapter.py:30-40`) using verified caller scopes/roles (`allowed_tools` + `readOnly` vs. `admin` scopes), and emit `notifications/tools/list_changed` when session permissions or tool states change.
  - Add an **end-to-end chat client/example** under `examples/` that connects `ExternalMCPClientAdapter` to an LLM, handles `input_required` elicitation prompts, polls `tasks/get`, and renders live progress in SSE streams.

---

## Verification Plan

- Extend [`tests/test_durable_resume_and_mcp_trace.py`](../tests/test_durable_resume_and_mcp_trace.py) and [`tests/test_mcp_registry.py`](../tests/test_mcp_registry.py) to test:
  - Restart-resilient `tasks/get` / `tasks/cancel` and `input_required` resume flows backed by `SQLiteCheckpointer`.
  - Opaque state handle HMAC verification and cross-tenant/cross-user rejection.
  - `ToolAnnotations` round-tripping, `structuredContent` + `resource_link` formatting, and scope-filtered `tools/list`.
