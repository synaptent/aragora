#!/usr/bin/env python3
"""
Control Plane Deliberation Worker.

Claims control-plane tasks of type "deliberation" and executes them using
the DecisionRouter, persisting results for later retrieval.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
import uuid


def _parse_capabilities(raw: str) -> list[str]:
    return [cap.strip() for cap in raw.split(",") if cap.strip()]


async def run_worker(
    agent_id: str, capabilities: list[str], block_ms: int, idle_sleep: float
) -> None:
    from aragora.control_plane import ControlPlaneCoordinator
    from aragora.core.decision import DecisionRequest, get_decision_router
    from aragora.control_plane.deliberation import run_deliberation, record_deliberation_error

    try:
        from aragora.server.decision_routes import register_decision_routes

        register_decision_routes()
    except ImportError as e:
        logging.warning("Decision router hooks not registered: %s", e)
    coordinator = await ControlPlaneCoordinator.create()

    await coordinator.register_agent(
        agent_id=agent_id,
        capabilities=capabilities,
        model="deliberation-worker",
        provider="aragora",
        metadata={"worker_type": "deliberation"},
    )

    router = get_decision_router()

    logging.info("Deliberation worker started: %s", agent_id)
    logging.info("Capabilities: %s", ", ".join(capabilities))

    while True:
        task = await coordinator.claim_task(
            agent_id=agent_id,
            capabilities=capabilities,
            block_ms=block_ms,
        )

        if not task:
            await asyncio.sleep(idle_sleep)
            continue

        start = time.monotonic()
        request_id = None
        try:
            if task.task_type != "deliberation":
                raise ValueError(f"Unsupported task type: {task.task_type}")

            payload = task.payload or {}
            if isinstance(payload, dict):
                payload = payload.get("decision") or payload.get("request") or payload
            else:
                raise ValueError("Task payload must be a dict")

            request = DecisionRequest.from_dict(payload)
            request_id = request.request_id

            result = await run_deliberation(request, router=router)

            await coordinator.complete_task(
                task.id,
                result=result.to_dict(),
                agent_id=agent_id,
                latency_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
            if request_id:
                record_deliberation_error(request_id, str(e))
            await coordinator.fail_task(
                task.id,
                error=str(e),
                agent_id=agent_id,
                latency_ms=(time.monotonic() - start) * 1000,
                requeue=False,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Control plane deliberation worker")
    parser.add_argument(
        "--agent-id",
        default=os.getenv("ARAGORA_WORKER_ID", f"deliberation-worker-{uuid.uuid4().hex[:8]}"),
        help="Agent ID to register with the control plane",
    )
    parser.add_argument(
        "--capabilities",
        default=os.getenv("ARAGORA_WORKER_CAPABILITIES", "deliberation,debate,gauntlet,workflow"),
        help="Comma-separated capabilities for this worker",
    )
    parser.add_argument(
        "--block-ms",
        type=int,
        default=int(os.getenv("ARAGORA_WORKER_BLOCK_MS", "5000")),
        help="Milliseconds to block while waiting for tasks",
    )
    parser.add_argument(
        "--idle-sleep",
        type=float,
        default=float(os.getenv("ARAGORA_WORKER_IDLE_SLEEP", "0.25")),
        help="Seconds to sleep when no task is available",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("ARAGORA_LOG_LEVEL", "INFO"),
        help="Logging level",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(message)s"
    )

    capabilities = _parse_capabilities(args.capabilities)
    asyncio.run(run_worker(args.agent_id, capabilities, args.block_ms, args.idle_sleep))


if __name__ == "__main__":
    main()
