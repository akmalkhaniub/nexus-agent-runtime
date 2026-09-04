"""
examples.sre_incident_triage.agent
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Reference Domain Agent: Cloud SRE Incident Triage and Auto-Remediation.
Demonstrates consuming the Nexus SDK, handling Human-in-the-loop approvals,
and executing graph-based incident diagnosis.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict
from nexus_sdk import NexusClient, agent, tool


@agent(
    name="SREIncidentTriageAgent",
    description="Diagnoses container crashes, checks observability metrics, and performs safe restarts.",
    version="1.0.0",
)
class SREIncidentTriageAgent:
    """
    SRE Agent instantiated by internal Reliability Engineering pods.
    """

    def __init__(self, client: NexusClient) -> None:
        self.client = client

    async def triage_incident(self, alert_description: str, cluster: str, service: str) -> Dict[str, Any]:
        """
        Executes end-to-end incident triage through the Nexus shared runtime.
        """
        print(f"[SRE Agent] Starting triage for alert: '{alert_description}' on {cluster}/{service}")

        # 1. Trigger agent run via SDK
        run = await self.client.runs.create(
            intent=f"Triage incident: {alert_description}",
            context={"cluster": cluster, "service": service},
        )
        print(f"[SRE Agent] Run completed with ID: {run.run_id} in {run.duration_ms:.1f}ms")

        # 2. Inspect checkpoints
        checkpoints = await self.client.runs.list_checkpoints(run.run_id)
        print(f"[SRE Agent] Recorded {len(checkpoints)} state checkpoints during triage.")

        # 3. Handle high-risk remediation tool (with HITL approval flow)
        restart_tool_req = {"service": service, "grace_period_sec": 15}
        try:
            print(f"[SRE Agent] Attempting restart_service_pod for {service}...")
            await self.client.tools.execute("restart_service_pod", restart_tool_req)
        except Exception as exc:
            # Caught ApprovalRequiredSDKError!
            print(f"[SRE Agent] Safe Policy Enforced: {exc}")
            token = getattr(exc, "approval_token", "appr_restart_service_pod_manual")
            print(f"[SRE Agent] Human SRE Lead approving token: {token}...")
            await self.client.tools.approve(token)
            print("[SRE Agent] Re-executing remediation tool with authorized token...")
            result = await self.client.tools.execute(
                "restart_service_pod",
                restart_tool_req,
                approval_token=token,
            )
            print(f"[SRE Agent] Remediation Succeeded: {result.output}")

        return {
            "run_id": run.run_id,
            "status": "INCIDENT_RESOLVED",
            "summary": "Root cause identified as OOMKilled; pod gracefully restarted after approval.",
        }
