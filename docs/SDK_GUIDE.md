# CONVO Agent SDK (`convo-agent-sdk`) Developer Guide

This guide explains how internal engineering pods at CONVO consume the shared runtime and SDK to build and operate domain-specific agents.

---

## 1. Installation

```bash
pip install convo-agent-platform
```

---

## 2. Quickstart: Building a Domain Agent

```python
import asyncio
from convo_sdk import ConvoClient, agent, tool

# 1. Define a domain tool using the @tool decorator
@tool(
    name="get_customer_balance",
    description="Retrieves active balance and overdue invoices for an account.",
    tags=["billing", "finance"]
)
async def get_customer_balance(account_id: str) -> dict:
    return {"account_id": account_id, "balance_usd": 142.50, "overdue": False}


# 2. Build the domain agent
@agent(
    name="SupportOpsAgent",
    description="Assists customer support teams with billing and account status lookups."
)
class SupportOpsAgent:
    def __init__(self, client: ConvoClient):
        self.client = client

    async def handle_inquiry(self, account_id: str):
        # Register the custom domain tool with the shared runtime
        await self.client.tools.register(get_customer_balance)

        # Trigger workflow execution
        run = await self.client.runs.create(
            intent=f"Lookup balance details for account {account_id}",
            context={"account_id": account_id},
            idempotency_key=f"inq_{account_id}",
        )
        return run.final_state
```

---

## 3. Streaming Agent Execution (Server-Sent Events)

Consume live workflow events, node transitions, and state deltas in real-time:

```python
async with ConvoClient(base_url="http://localhost:8000", tenant_id="pod-support") as client:
    async for event in client.runs.stream(intent="Diagnose API latency"):
        print(f"[{event.event_type}] Node: {event.node_name}")
        if event.event_type == "node_finished":
            print("Delta:", event.data.get("state_delta"))
        elif event.event_type == "workflow_paused":
            print("Workflow paused for approval:", event.data.get("reason"))
```

---

## 4. Human-In-The-Loop (HITL) Authorizations

For sensitive operations (e.g. database deletions or container restarts), define tools with `requires_approval=True`:

```python
@tool(
    name="drop_user_sessions",
    description="Terminates all active sessions for a user.",
    requires_approval=True  # Enforces human authorization
)
async def drop_user_sessions(user_id: str) -> dict:
    return {"status": "sessions_terminated", "user_id": user_id}

# When invoked without a valid approval token, the SDK raises ApprovalRequiredSDKError:
try:
    await client.tools.execute("drop_user_sessions", {"user_id": "usr_99"})
except ApprovalRequiredSDKError as exc:
    print(f"Approval Token required: {exc.approval_token}")
    # Authorize after human review:
    await client.tools.approve(exc.approval_token)
    # Re-execute with approval:
    res = await client.tools.execute("drop_user_sessions", {"user_id": "usr_99"}, approval_token=exc.approval_token)
```

---

## 5. Deterministic Time-Travel Replay

Inspect checkpoints and rewind a previous run to test a bug fix:

```python
# 1. Fetch historical checkpoints
checkpoints = await client.runs.list_checkpoints(run_id="run_12345")

# 2. Replay from step 2 with patched state
replayed = await client.runs.replay(
    run_id="run_12345",
    step_index=2,
    state_overrides={"patch_flag": True},
)
print("Replayed final state:", replayed.final_state)
```
