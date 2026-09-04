"""
convo_runtime.core.planner
~~~~~~~~~~~~~~~~~~~~~~~~~~

Intent-to-workflow planning engine.
Decomposes high-level natural language goals into structured execution plans,
resolves tool dependencies, and synthesizes dynamic executable StateGraphs.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from convo_runtime.core.graph import StateGraph, END
from convo_runtime.core.state import AgentState


class PlanStep(BaseModel):
    step_id: str = Field(default_factory=lambda: f"step_{uuid.uuid4().hex[:8]}")
    title: str
    tool_name: Optional[str] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)
    dependencies: List[str] = Field(default_factory=list)
    description: str = ""
    status: str = "pending"  # pending, running, completed, failed


class ExecutionPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:10]}")
    intent: str
    steps: List[PlanStep] = Field(default_factory=list)
    created_at: float = Field(default_factory=lambda: __import__("time").time())
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WorkflowPlanner:
    """
    Translates intents and registered tool contracts into an executable multi-step plan
    and automatically compiles it into a StateGraph workflow.
    """

    def __init__(self, tool_registry: Optional[Any] = None) -> None:
        self.tool_registry = tool_registry

    async def create_plan(self, intent: str, context: Optional[Dict[str, Any]] = None) -> ExecutionPlan:
        """
        Synthesizes a structured plan from intent. In production, this can use an LLM
        prompt or rule-based heuristic. Here we provide a robust structured planner.
        """
        plan = ExecutionPlan(intent=intent, metadata=context or {})
        
        # Heuristic intent parser (for testing and reference workflows)
        intent_lower = intent.lower()
        if "incident" in intent_lower or "triage" in intent_lower or "cpu" in intent_lower:
            plan.steps = [
                PlanStep(
                    step_id="step_fetch_metrics",
                    title="Fetch System Metrics & CPU Usage",
                    tool_name="get_cluster_metrics",
                    arguments={"cluster": "prod-east", "metric": "cpu_utilization"},
                    dependencies=[],
                ),
                PlanStep(
                    step_id="step_query_logs",
                    title="Analyze Pod Crash Logs",
                    tool_name="get_pod_logs",
                    arguments={"service": "payment-api", "tail_lines": 100},
                    dependencies=["step_fetch_metrics"],
                ),
                PlanStep(
                    step_id="step_remediate",
                    title="Restart Faulty Container Pod",
                    tool_name="restart_service_pod",
                    arguments={"service": "payment-api", "grace_period_sec": 30},
                    dependencies=["step_query_logs"],
                ),
            ]
        elif "refund" in intent_lower or "billing" in intent_lower:
            plan.steps = [
                PlanStep(
                    step_id="step_check_account",
                    title="Retrieve Customer Account Status",
                    tool_name="get_account_details",
                    arguments={"account_id": (context or {}).get("account_id", "ACC-9812")},
                    dependencies=[],
                ),
                PlanStep(
                    step_id="step_verify_policy",
                    title="Verify Refund Policy Compliance",
                    tool_name="check_refund_eligibility",
                    arguments={"amount": (context or {}).get("amount", 49.99)},
                    dependencies=["step_check_account"],
                ),
                PlanStep(
                    step_id="step_issue_refund",
                    title="Process Safe Transactional Refund",
                    tool_name="process_refund",
                    arguments={"amount": (context or {}).get("amount", 49.99)},
                    dependencies=["step_verify_policy"],
                ),
            ]
        else:
            plan.steps = [
                PlanStep(
                    step_id="step_generic_analyze",
                    title="Analyze User Request Context",
                    tool_name="query_knowledge_base",
                    arguments={"query": intent},
                    dependencies=[],
                ),
                PlanStep(
                    step_id="step_generic_execute",
                    title="Execute Requested Operation",
                    tool_name=None,
                    arguments={},
                    dependencies=["step_generic_analyze"],
                ),
            ]

        return plan

    def compile_plan_to_graph(self, plan: ExecutionPlan, tool_executor: Optional[Any] = None) -> StateGraph:
        """
        Converts an ExecutionPlan into a stateful executable StateGraph.
        """
        graph = StateGraph()
        step_ids = [s.step_id for s in plan.steps]

        for step in plan.steps:
            def make_node_handler(step_ref: PlanStep):
                async def node_handler(state: AgentState) -> Dict[str, Any]:
                    state.add_message(
                        role="assistant",
                        content=f"Executing plan step: {step_ref.title} (Tool: {step_ref.tool_name})",
                    )
                    tool_result = None
                    if step_ref.tool_name and tool_executor:
                        tool_result = await tool_executor(step_ref.tool_name, step_ref.arguments, state)
                    else:
                        tool_result = {"status": "simulated_success", "step": step_ref.step_id}

                    return {
                        f"result_{step_ref.step_id}": tool_result,
                        "last_executed_step": step_ref.step_id,
                    }
                return node_handler

            # Capture step in closure
            graph.add_node(step.step_id, make_node_handler(step))

        # Wire linear dependency chain
        if step_ids:
            graph.set_entry_point(step_ids[0])
            for i in range(len(step_ids) - 1):
                graph.add_edge(step_ids[i], step_ids[i + 1])
            graph.add_edge(step_ids[-1], END)

        return graph
