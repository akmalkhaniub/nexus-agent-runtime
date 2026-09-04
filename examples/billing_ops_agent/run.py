"""
examples.billing_ops_agent.run
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Runner script demonstrating the Billing Operations reference agent.
"""

import asyncio
import os
import sys
import httpx

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from nexus_runtime.api.app import create_app
from nexus_sdk.client import NexusClient
from examples.billing_ops_agent.agent import BillingOpsAgent


async def main():
    print("=" * 60)
    print("  NEXUS BILLING OPERATIONS DOMAIN AGENT DEMO")
    print("=" * 60)

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with NexusClient(base_url="http://testserver", tenant_id="pod-billing-ops", transport=transport) as client:
        # Pre-seed vector knowledge base with refund policies
        await client.memory.add_vector(
            doc_id="policy_standard_refund",
            text="Customers experiencing service downtime are eligible for immediate automated refunds under $100 without manual review.",
            metadata={"category": "policy", "threshold": 100},
        )

        agent = BillingOpsAgent(client)

        result = await agent.resolve_dispute(
            account_id="ACC-ENTERPRISE-4421",
            disputed_amount=49.99,
            reason="Unscheduled downtime during monthly reconciliation",
        )

        print("\n--- Final Billing Result ---")
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
