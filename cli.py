"""
convo-agent-platform CLI
~~~~~~~~~~~~~~~~~~~~~~~~

Interactive CLI tool to demonstrate and operate the Convo Shared Agent Runtime.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import httpx

from convo_runtime.api.app import create_app
from convo_sdk.client import ConvoClient


def get_client() -> ConvoClient:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    return ConvoClient(base_url="http://testserver", tenant_id="cli-operator", transport=transport)


async def cmd_tools():
    async with get_client() as client:
        tools = await client.tools.list()
        print("\n=== Registered Convo & MCP Tools ===")
        print(f"{'NAME':<25} {'VERSION':<10} {'APPROVAL?':<12} {'TAGS'}")
        print("-" * 65)
        for t in tools:
            req_appr = "YES (HITL)" if t.get("requires_approval") else "No"
            tags = ", ".join(t.get("tags", []))
            print(f"{t['name']:<25} {t.get('version', '1.0.0'):<10} {req_appr:<12} {tags}")


async def cmd_run(intent: str):
    async with get_client() as client:
        print(f"\n[CLI] Initiating workflow for intent: '{intent}'...")
        run = await client.runs.create(intent=intent)
        print(f"[CLI] Run Finished: ID={run.run_id} | Status={run.status} | Steps={run.total_steps} | Time={run.duration_ms:.1f}ms")
        print("\nFinal State Values:")
        print(json.dumps(run.final_state.get("values", {}), indent=2))


async def cmd_stream(intent: str):
    async with get_client() as client:
        print(f"\n[CLI] Streaming real-time events for intent: '{intent}'...")
        async for event in client.runs.stream(intent=intent):
            node_tag = f"[{event.node_name}]" if event.node_name else ""
            print(f"--> Step {event.step_index} | Event: {event.event_type:<20} {node_tag}")
            if event.event_type == "node_finished":
                delta = event.data.get("state_delta", {})
                if delta:
                    print(f"    Delta: {delta}")
            elif event.event_type == "workflow_paused":
                print(f"    PAUSED: {event.data.get('reason')}")


async def cmd_telemetry():
    async with get_client() as client:
        metrics = await client.telemetry.get_metrics()
        print("\n=== Convo Platform Operational Telemetry ===")
        print(json.dumps(metrics, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Convo Agent Platform CLI")
    subparsers = parser.add_subparsers(dest="command")

    # tools command
    subparsers.add_parser("tools", help="List registered tools")

    # run command
    run_p = subparsers.add_parser("run", help="Execute an agent workflow")
    run_p.add_argument("intent", type=str, help="Intent or natural language goal")

    # stream command
    stream_p = subparsers.add_parser("stream", help="Stream workflow execution events in real time")
    stream_p.add_argument("intent", type=str, help="Intent to stream")

    # telemetry command
    subparsers.add_parser("telemetry", help="Inspect runtime operational metrics")

    args = parser.parse_args()

    if args.command == "tools":
        asyncio.run(cmd_tools())
    elif args.command == "run":
        asyncio.run(cmd_run(args.intent))
    elif args.command == "stream":
        asyncio.run(cmd_stream(args.intent))
    elif args.command == "telemetry":
        asyncio.run(cmd_telemetry())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
