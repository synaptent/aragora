"""Periodic reconciler for supervisor-backed swarm runs.

Keeps a supervised Codex/Claude swarm moving by topping up leases,
dispatching ready workers, collecting finished results, and syncing
pending coordination artifacts into the global work queue.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from aragora.swarm.supervisor import SupervisorRun, SwarmSupervisor


@dataclass(slots=True)
class SwarmReconcilerConfig:
    """Configuration for periodic swarm reconciliation."""

    interval_seconds: float = 5.0
    max_ticks: int | None = None
    sync_pending_queue: bool = True


class SwarmReconciler:
    """Periodic reconciler for supervised swarm runs."""

    def __init__(
        self,
        repo_root: Path | None = None,
        *,
        supervisor: SwarmSupervisor | None = None,
        config: SwarmReconcilerConfig | None = None,
    ) -> None:
        self.repo_root = (repo_root or Path.cwd()).resolve()
        self.supervisor = supervisor or SwarmSupervisor(repo_root=self.repo_root)
        self.config = config or SwarmReconcilerConfig()

    async def tick_run(self, run_id: str) -> SupervisorRun:
        """Advance one run by one reconciliation tick."""
        self.supervisor.refresh_run(run_id)
        await self.supervisor.dispatch_workers(run_id)
        completed = await self.supervisor.collect_finished_results(run_id)
        if completed:
            self.supervisor.refresh_run(run_id)
            await self.supervisor.dispatch_workers(run_id)

        if self.config.sync_pending_queue:
            await self.supervisor.store.sync_pending_work_queue()

        record = self.supervisor.store.get_supervisor_run(run_id)
        if record is None:
            raise KeyError(f"Unknown supervisor run: {run_id}")
        return SupervisorRun.from_record(record)

    async def tick_open_runs(self, *, limit: int = 20) -> list[SupervisorRun]:
        """Advance all open runs by one tick."""
        runs = self.supervisor.status_summary(limit=limit, refresh_scaling=False).get("runs", [])
        refreshed: list[SupervisorRun] = []
        for item in runs:
            if not isinstance(item, dict):
                continue
            run_id = str(item.get("run_id", "")).strip()
            if not run_id:
                continue
            refreshed.append(await self.tick_run(run_id))
        return refreshed

    async def watch_run(
        self,
        run_id: str,
        *,
        interval_seconds: float | None = None,
        max_ticks: int | None = None,
    ) -> SupervisorRun:
        """Reconcile a run until it reaches a stable stop condition."""
        interval = (
            self.config.interval_seconds if interval_seconds is None else max(0.1, interval_seconds)
        )
        tick_limit = self.config.max_ticks if max_ticks is None else max_ticks
        ticks = 0
        run = await self.tick_run(run_id)
        while not self._should_stop(run):
            ticks += 1
            if tick_limit is not None and ticks >= tick_limit:
                break
            await asyncio.sleep(interval)
            run = await self.tick_run(run_id)
        return run

    @staticmethod
    def _should_stop(run: SupervisorRun) -> bool:
        statuses = {str(item.get("status", "")).strip() for item in run.work_orders}
        if run.status == "completed":
            return True
        if run.status == "needs_human":
            return True
        active_statuses = {"queued", "waiting_conflict", "leased", "dispatched"}
        return not (statuses & active_statuses)
