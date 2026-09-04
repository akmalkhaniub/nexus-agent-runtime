"""
tests.test_sdk_integration
~~~~~~~~~~~~~~~~~~~~~~~~~~

End-to-end integration tests using ConvoClient against the full FastAPI runtime.
Validates SDK ergonomics, streaming SSE, tool contracts, and reference domain agents.
"""

import pytest
from convo_sdk.client import ConvoClient
from convo_sdk.decorators import tool
from examples.sre_incident_triage.agent import SREIncidentTriageAgent
from examples.billing_ops_agent.agent import BillingOpsAgent


@pytest.mark.asyncio
async def test_sdk_tool_registration_and_execution(client: ConvoClient):
    # Register custom tool via @tool decorator
    @tool(name="fetch_user_profile", description="Fetches profile by user ID", tags=["users"])
    async def fetch_user_profile(user_id: str) -> dict:
        return {"user_id": user_id, "name": "Alice Engineer", "role": "Senior SRE"}

    reg_res = await client.tools.register(fetch_user_profile)
    assert reg_res["status"] == "registered"

    # List tools and confirm presence
    tools = await client.tools.list()
    tool_names = [t["name"] for t in tools]
    assert "fetch_user_profile" in tool_names


@pytest.mark.asyncio
async def test_sdk_run_execution_and_checkpoints(client: ConvoClient):
    run = await client.runs.create(
        intent="Triage CPU spike alert on prod-cluster",
        context={"cluster": "prod-us-east", "service": "payment-api"},
    )
    assert run.status == "COMPLETED"
    assert run.run_id is not None
    assert run.total_steps > 0

    # Retrieve checkpoints
    checkpoints = await client.runs.list_checkpoints(run.run_id)
    assert len(checkpoints) >= 2


@pytest.mark.asyncio
async def test_sdk_streaming_events(client: ConvoClient):
    # 1. Test completed workflow stream
    events = []
    async for event in client.runs.stream(
        intent="Analyze cluster resource trends",
        context={"cluster": "prod-west"},
    ):
        events.append(event)

    event_types = [e.event_type for e in events]
    assert "workflow_started" in event_types
    assert "node_finished" in event_types
    assert "workflow_completed" in event_types

    # 2. Test Human-in-the-loop paused workflow stream
    hitl_events = []
    async for event in client.runs.stream(
        intent="Triage memory leak incident",
        context={"cluster": "prod-west", "service": "auth-service"},
    ):
        hitl_events.append(event)

    hitl_types = [e.event_type for e in hitl_events]
    assert "workflow_started" in hitl_types
    assert "workflow_paused" in hitl_types


@pytest.mark.asyncio
async def test_sdk_deterministic_replay(client: ConvoClient):
    # 1. First run
    run = await client.runs.create(
        intent="Triage cluster incident",
        context={"cluster": "prod-central"},
    )

    # 2. Replay from step 1
    replay_res = await client.runs.replay(
        run_id=run.run_id,
        step_index=1,
        state_overrides={"simulated_override": "active"},
    )

    assert replay_res.original_run_id == run.run_id
    assert replay_res.from_step_index == 1
    assert replay_res.final_state["values"].get("simulated_override") == "active"


@pytest.mark.asyncio
async def test_sre_reference_agent_end_to_end(client: ConvoClient):
    agent = SREIncidentTriageAgent(client)
    res = await agent.triage_incident(
        alert_description="High CPU usage and container restart loop",
        cluster="prod-east",
        service="payment-api",
    )
    assert res["status"] == "INCIDENT_RESOLVED"


@pytest.mark.asyncio
async def test_billing_reference_agent_end_to_end(client: ConvoClient):
    agent = BillingOpsAgent(client)
    res = await agent.resolve_dispute(
        account_id="ACC-TEST-9001",
        disputed_amount=29.99,
        reason="Network downtime during month end",
    )
    assert res["status"] == "REFUND_ISSUED"
    assert res["refunded_amount"] == 29.99
