#!/usr/bin/env python3
"""Swarm Reconciler Daemon — periodically dispatches and collects swarm workers.

Polls active supervisor runs, dispatches queued work orders that have leases,
and collects results from completed workers. Follows the PR Watch Daemon pattern.

Usage::

    python scripts/swarm_reconciler.py --repo-root . --poll-interval 30
    python scripts/swarm_reconciler.py --once  # single pass, then exit
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("aragora.swarm.reconciler")


@dataclass
class ReconcilerConfig:
    """Configuration for the swarm reconciler daemon."""

    repo_root: str = "."
    poll_interval_seconds: int = 30
    collect_timeout_seconds: float = 5.0
    once: bool = False


class SwarmReconciler:
    """Periodically reconcile active supervisor runs."""

    def __init__(self, config: ReconcilerConfig) -> None:
        self._config = config
        self._stop = asyncio.Event()

    async def run(self) -> None:
        """Main daemon loop."""
        from aragora.swarm.supervisor import SwarmSupervisor

        repo_root = Path(self._config.repo_root).resolve()
        supervisor = SwarmSupervisor(repo_root=repo_root)

        logger.info(
            "Swarm reconciler started (repo=%s, poll=%ds)",
            repo_root,
            self._config.poll_interval_seconds,
        )

        while not self._stop.is_set():
            try:
                await self._reconcile_once(supervisor)
            except Exception:
                logger.exception("Reconcile cycle failed")

            if self._config.once:
                break

            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._config.poll_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass  # normal — poll interval elapsed

        logger.info("Swarm reconciler stopped")

    async def _reconcile_once(self, supervisor: object) -> None:
        """Single reconciliation pass."""
        summary = supervisor.status_summary(refresh_scaling=True)
        runs = summary.get("runs", [])
        counts = summary.get("counts", {})

        active_runs = [r for r in runs if r.get("status") == "active"]
        if not active_runs:
            logger.debug(
                "No active runs (total=%d, queued=%d, completed=%d)",
                counts.get("runs", 0),
                counts.get("queued_work_orders", 0),
                counts.get("completed_work_orders", 0),
            )
            return

        for run_data in active_runs:
            run_id = run_data.get("run_id", "")
            work_orders = run_data.get("work_orders", [])

            # Count by status
            leased = sum(1 for w in work_orders if w.get("status") == "leased")
            dispatched = sum(1 for w in work_orders if w.get("status") == "dispatched")

            # Dispatch any leased-but-not-yet-launched orders
            if leased > 0:
                try:
                    launched = await supervisor.dispatch_workers(run_id)
                    if launched:
                        logger.info("Run %s: dispatched %d workers", run_id[:8], len(launched))
                except Exception:
                    logger.exception("Failed to dispatch workers for %s", run_id[:8])

            # Collect results from dispatched workers (non-blocking timeout)
            if dispatched > 0:
                try:
                    completed = await supervisor.collect_results(
                        run_id, timeout=self._config.collect_timeout_seconds
                    )
                    if completed:
                        logger.info("Run %s: collected %d results", run_id[:8], len(completed))
                except Exception:
                    logger.exception("Failed to collect results for %s", run_id[:8])

    def stop(self) -> None:
        self._stop.set()


def _setup_signals(reconciler: SwarmReconciler) -> None:
    """Register signal handlers for graceful shutdown."""
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, reconciler.stop)


def main() -> None:
    parser = argparse.ArgumentParser(description="Swarm reconciler daemon")
    parser.add_argument("--repo-root", default=".", help="Repository root path (default: .)")
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=30,
        help="Poll interval in seconds (default: 30)",
    )
    parser.add_argument(
        "--collect-timeout",
        type=float,
        default=5.0,
        help="Timeout for collecting worker results per run (default: 5.0)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one reconciliation pass then exit",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = ReconcilerConfig(
        repo_root=args.repo_root,
        poll_interval_seconds=args.poll_interval,
        collect_timeout_seconds=args.collect_timeout,
        once=args.once,
    )

    reconciler = SwarmReconciler(config)

    async def _run() -> None:
        _setup_signals(reconciler)
        await reconciler.run()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
