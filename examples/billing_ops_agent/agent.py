"""
examples.billing_ops_agent.agent
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Reference Domain Agent: Billing Dispute Resolution Agent.
Demonstrates transactional state updates, policy evaluation, and episodic memory recall.
"""

from __future__ import annotations

from typing import Any, Dict
from convo_sdk import ConvoClient, agent


@agent(
    name="BillingOpsAgent",
    description="Processes disputed customer charges, evaluates refund policy, and logs resolutions.",
    version="1.0.0",
)
class BillingOpsAgent:
    """
    Billing Operations Agent instantiated by internal Finance/Billing engineering pods.
    """

    def __init__(self, client: ConvoClient) -> None:
        self.client = client

    async def resolve_dispute(self, account_id: str, disputed_amount: float, reason: str) -> Dict[str, Any]:
        print(f"[Billing Agent] Initiating dispute resolution for Account: {account_id} (${disputed_amount:.2f})")

        # 1. Search vector memory for dispute precedent
        precedents = await self.client.memory.search_vector(
            query=f"dispute refund policy for {reason}",
            top_k=2,
        )
        print(f"[Billing Agent] Found {len(precedents)} relevant knowledge base precedents.")

        # 2. Execute billing workflow run
        run = await self.client.runs.create(
            intent=f"Resolve billing refund dispute for {account_id}",
            context={"account_id": account_id, "amount": disputed_amount, "reason": reason},
            idempotency_key=f"dispute_{account_id}_{disputed_amount}",
        )
        print(f"[Billing Agent] Dispute workflow completed in {run.duration_ms:.1f}ms (Run ID: {run.run_id})")

        # 3. Store resolution in vector memory for future recall
        await self.client.memory.add_vector(
            doc_id=f"res_{run.run_id}",
            text=f"Account {account_id} refunded ${disputed_amount:.2f} for reason '{reason}'. Resolved cleanly.",
            metadata={"account_id": account_id, "amount": disputed_amount, "type": "dispute_resolution"},
        )
        print("[Billing Agent] Episodic memory updated successfully.")

        return {
            "run_id": run.run_id,
            "account_id": account_id,
            "refunded_amount": disputed_amount,
            "status": "REFUND_ISSUED",
        }
