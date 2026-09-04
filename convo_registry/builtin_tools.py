"""
convo_registry.builtin_tools
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Standard production-ready tools for SRE operations, data retrieval,
and billing management with varying security classifications.
"""

from __future__ import annotations

from typing import Any, Dict
from convo_registry.contracts import ToolDefinition, ToolInputSchema
from convo_registry.registry import ToolRegistry


# 1. SRE Incident Triage Tools
def get_cluster_metrics_def() -> ToolDefinition:
    return ToolDefinition(
        name="get_cluster_metrics",
        description="Retrieves real-time CPU, memory, and error rates for a Kubernetes cluster.",
        input_schema=ToolInputSchema(
            properties={
                "cluster": {"type": "string", "description": "Target cluster name (e.g. prod-east)"},
                "metric": {"type": "string", "description": "Metric name to inspect"},
            },
            required=["cluster", "metric"],
        ),
        tags=["sre", "observability"],
    )


async def get_cluster_metrics_handler(cluster: str, metric: str) -> Dict[str, Any]:
    return {
        "cluster": cluster,
        "metric": metric,
        "value": 94.8 if metric == "cpu_utilization" else 42.1,
        "unit": "percent",
        "threshold_exceeded": True,
        "status": "CRITICAL",
    }


def get_pod_logs_def() -> ToolDefinition:
    return ToolDefinition(
        name="get_pod_logs",
        description="Extracts the most recent stack traces and logs for a crashed microservice pod.",
        input_schema=ToolInputSchema(
            properties={
                "service": {"type": "string", "description": "Microservice name (e.g. payment-api)"},
                "tail_lines": {"type": "integer", "description": "Number of lines to tail"},
            },
            required=["service"],
        ),
        tags=["sre", "logs"],
    )


async def get_pod_logs_handler(service: str, tail_lines: int = 50) -> Dict[str, Any]:
    return {
        "service": service,
        "tail_lines": tail_lines,
        "logs": [
            "[FATAL] java.lang.OutOfMemoryError: Java heap space",
            "at com.convo.billing.WorkerPool.allocate(WorkerPool.java:142)",
            "Container exiting with code 137 (OOMKilled)",
        ],
        "root_cause_hint": "Memory leak under high concurrency load in WorkerPool allocation",
    }


def restart_service_pod_def() -> ToolDefinition:
    return ToolDefinition(
        name="restart_service_pod",
        description="Restarts a failing container pod. High-risk operation requiring human approval.",
        input_schema=ToolInputSchema(
            properties={
                "service": {"type": "string", "description": "Service name to restart"},
                "grace_period_sec": {"type": "integer", "description": "Grace period in seconds"},
            },
            required=["service"],
        ),
        requires_approval=True,  # HITL Gate
        tags=["sre", "remediation", "high_risk"],
    )


async def restart_service_pod_handler(service: str, grace_period_sec: int = 30) -> Dict[str, Any]:
    return {
        "service": service,
        "status": "RESTARTED",
        "new_pod_id": f"pod_{service}_9x8a7f",
        "message": f"Service {service} gracefully restarted and passed liveness checks.",
    }


# 2. Billing & Customer Ops Tools
def get_account_details_def() -> ToolDefinition:
    return ToolDefinition(
        name="get_account_details",
        description="Retrieves customer billing tier, active subscriptions, and payment history.",
        input_schema=ToolInputSchema(
            properties={
                "account_id": {"type": "string", "description": "Account identifier"},
            },
            required=["account_id"],
        ),
        tags=["billing", "customer_ops"],
    )


async def get_account_details_handler(account_id: str) -> Dict[str, Any]:
    return {
        "account_id": account_id,
        "tier": "Enterprise Gold",
        "monthly_spend": 1250.00,
        "has_active_dispute": True,
        "disputed_charge_id": "ch_9981a2c",
        "disputed_amount": 49.99,
    }


def check_refund_eligibility_def() -> ToolDefinition:
    return ToolDefinition(
        name="check_refund_eligibility",
        description="Validates if a refund request complies with platform terms of service.",
        input_schema=ToolInputSchema(
            properties={
                "amount": {"type": "number", "description": "Requested refund amount in USD"},
            },
            required=["amount"],
        ),
        tags=["billing", "policy"],
    )


async def check_refund_eligibility_handler(amount: float) -> Dict[str, Any]:
    eligible = amount <= 100.00
    return {
        "requested_amount": amount,
        "is_eligible": eligible,
        "policy_reason": "Within automated threshold (<= $100)" if eligible else "Exceeds automated threshold",
    }


def process_refund_def() -> ToolDefinition:
    return ToolDefinition(
        name="process_refund",
        description="Issues financial refund credit back to the customer payment method.",
        input_schema=ToolInputSchema(
            properties={
                "amount": {"type": "number", "description": "Refund amount to process"},
            },
            required=["amount"],
        ),
        requires_approval=False,
        tags=["billing", "transactional"],
    )


async def process_refund_handler(amount: float) -> Dict[str, Any]:
    return {
        "status": "PROCESSED",
        "amount": amount,
        "transaction_id": "tx_ref_8823194a",
        "message": f"Successfully credited ${amount:.2f} to customer payment method.",
    }


def register_builtin_tools(registry: ToolRegistry) -> None:
    """Convenience bootstrap to register standard tools."""
    registry.register(get_cluster_metrics_def(), get_cluster_metrics_handler)
    registry.register(get_pod_logs_def(), get_pod_logs_handler)
    registry.register(restart_service_pod_def(), restart_service_pod_handler)
    registry.register(get_account_details_def(), get_account_details_handler)
    registry.register(check_refund_eligibility_def(), check_refund_eligibility_handler)
    registry.register(process_refund_def(), process_refund_handler)
