"""
examples.sre_incident_triage.run
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Runner script demonstrating the SRE Incident Triage reference agent in action.
"""

import asyncio
import os
import sys
import httpx

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from nexus_runtime.api.app import create_app
from nexus_sdk.client import NexusClient
from examples.sre_incident_triage.agent import SREIncidentTriageAgent


async def main():
    print("=" * 60)
    print("  NEXUS SRE INCIDENT TRIAGE DOMAIN AGENT DEMO")
    print("=" * 60)

    # Boot in-memory runtime app
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with NexusClient(base_url="http://testserver", tenant_id="pod-sre-east", transport=transport) as client:
        # Check health and registered tools
        tools = await client.tools.list()
        print(f"Connected to Nexus Runtime. Available tools: {[t.get('name') for t in tools]}")

        # Instantiate reference agent
        sre_agent = SREIncidentTriageAgent(client)

        # Trigger incident triage
        result = await sre_agent.triage_incident(
            alert_description="High CPU & CrashLoopBackOff in payment-api pod",
            cluster="prod-us-east",
            service="payment-api",
        )

        print("\n--- Final Triage Report ---")
        print(result)

        # Check telemetry
        metrics = await client.telemetry.get_metrics()
        print("\n--- Platform Telemetry Metrics ---")
        print(f"Total Runs: {metrics['runs']['total']}, Succeeded: {metrics['runs']['succeeded']}")
        print(f"Total Tool Invocations: {metrics['tools']['total_calls']}")


if __name__ == "__main__":
    asyncio.run(main())
