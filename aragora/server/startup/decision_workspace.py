"""Decision workspace startup: settle left-over runs, then register the debate runner.

Runs are executed in-process, so a run still ``running`` when the server
starts was cut off by the previous process. The sweep marks those runs
``interrupted`` and their decisions (and any decision left ``debating``
without a run) ``failed``, so each can be rerun. Only then is the runner
registered, so no run of this process is swept.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _workspace_store() -> Any:
    from aragora.decision_workspace.store import get_workspace_store
    from aragora.pipeline.plan_store import get_plan_store

    return get_workspace_store(get_plan_store().db_path)


def _debate_storage_provider(nomic_dir: Path | None) -> Any:
    lock = threading.Lock()
    cached: dict[str, Any] = {}

    def provider() -> Any | None:
        if nomic_dir is None:
            return None
        with lock:
            if "storage" not in cached:
                from aragora.storage.debate_storage import DebateStorage

                cached["storage"] = DebateStorage(str(Path(nomic_dir) / "debates.db"))
            return cached["storage"]

    return provider


def sweep_interrupted_runs() -> tuple[int, int]:
    """Settle runs and decisions a previous process left; ``(runs, decisions)``."""
    started_before = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    runs, decisions = _workspace_store().sweep_after_restart(started_before=started_before)
    if runs or decisions:
        logger.info(
            "Decision workspace: %d interrupted run(s), %d decision(s) marked failed",
            runs,
            decisions,
        )
    return runs, decisions


def init_decision_workspace(nomic_dir: Path | None = None) -> dict[str, Any]:
    """Sweep left-over runs and register the runner; returns a status summary."""
    status: dict[str, Any] = {"runs_interrupted": 0, "decisions_failed": 0, "runner": False}
    try:
        status["runs_interrupted"], status["decisions_failed"] = sweep_interrupted_runs()
    except Exception as exc:  # noqa: BLE001 - startup continues; intake still marks failures
        logger.warning("Decision workspace restart sweep failed: %s", exc)
        status["sweep_error"] = type(exc).__name__

    try:
        from aragora.decision_workspace.debate_hook import set_decision_debate_starter
        from aragora.decision_workspace.runner import DecisionRunner

        set_decision_debate_starter(
            DecisionRunner(
                store_provider=_workspace_store,
                debate_storage_provider=_debate_storage_provider(nomic_dir),
            )
        )
        status["runner"] = True
    except ImportError as exc:
        logger.warning("Decision workspace runner unavailable: %s", exc)
    return status


__all__ = ["init_decision_workspace", "sweep_interrupted_runs"]
