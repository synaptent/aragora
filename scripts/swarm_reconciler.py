#!/usr/bin/env python3
"""Swarm reconciler daemon.

Thin daemon wrapper around the canonical swarm reconciler so CLI, API, and
background watch mode all use the same supervisor-run advancement logic.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from dataclasses import dataclass
from pathlib import Path

from aragora.swarm import SwarmReconciler as CoreSwarmReconciler

logger = logging.getLogger("aragora.swarm.reconciler")


@dataclass
class ReconcilerConfig:
    """Configuration for the swarm reconciler daemon."""

    repo_root: str = "."
    poll_interval_seconds: int = 30
    collect_timeout_seconds: float = 5.0
    once: bool = False
    limit: int = 20


class SwarmReconciler:
    """Periodically reconcile open supervisor runs."""

    def __init__(self, config: ReconcilerConfig) -> None:
        self._config = config
        self._stop = asyncio.Event()

    async def run(self) -> None:
        """Main daemon loop."""
        repo_root = Path(self._config.repo_root).resolve()
        reconciler = CoreSwarmReconciler(repo_root=repo_root)

        logger.info(
            "Swarm reconciler started (repo=%s, poll=%ds)",
            repo_root,
            self._config.poll_interval_seconds,
        )

        while not self._stop.is_set():
            try:
                await self._reconcile_once(reconciler)
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
                pass

        logger.info("Swarm reconciler stopped")

    async def _reconcile_once(self, reconciler: CoreSwarmReconciler) -> None:
        """Single reconciliation pass."""
        runs = await reconciler.tick_open_runs(limit=self._config.limit)
        if runs:
            logger.info("Reconciled %d open runs", len(runs))
        else:
            logger.debug("No open runs to reconcile")

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
        help="Reserved for compatibility; reconciliation now uses the canonical engine",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum open runs to reconcile per pass (default: 20)",
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
        limit=max(1, args.limit),
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
