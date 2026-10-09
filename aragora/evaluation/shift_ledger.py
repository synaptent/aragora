"""Persistent shift ledger for proof-first runtime truth (RS-10).

Accumulates structured entries across shifts so operator status
can be answered from the ledger rather than shell sampling.
Each entry is one JSONL line with a type, timestamp, and payload.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_LEDGER_PATH = ".aragora/proof_first_shift/shift_ledger.jsonl"
GREEN_SHIFT_REQUIRED_HOURS = 12.0
FAILURE_THRESHOLDS = {
    "auth_failure": 2,
    "publication_failure": 2,
    "rate_limit": 2,
    "permission_mismatch": 2,
    "runtime_failure": 1,
    "service_failure": 1,
}
HEALTHY_STOP_PREFIXES = ("completed", "TimeLimit:")


@dataclass
class LedgerEntry:
    """One ledger row."""

    entry_type: str
    timestamp: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LedgerEntry:
        return cls(
            entry_type=str(data.get("entry_type", "unknown")),
            timestamp=str(data.get("timestamp", "")),
            payload=dict(data.get("payload") or {}),
        )


class ShiftLedger:
    """Append-only JSONL ledger for shift runtime truth.

    Entry types:
        shift_start     — new shift began
        shift_stop      — shift ended (with reason)
        cycle_tick      — periodic tick with queue/process/benchmark state
        service_restart — boss loop or merge arbiter restarted
        service_failure — restart attempt failed
        benchmark_run   — benchmark publication run observed
        queue_change    — boss-ready queue restocked or pruned
        pr_merged       — automation PR merged
        auth_failure    — Codex/GitHub auth failure detected
        publication_failure — benchmark PR publication failure
    """

    def __init__(self, path: Path | str | None = None):
        # Coerce strings (and ``None``) to ``Path`` so callers using the
        # default ``DEFAULT_LEDGER_PATH`` string or ad-hoc string paths
        # don't crash on ``self._path.parent.mkdir(...)``. Round 30c-Phase-I
        # discovered this when invoking ``ShiftLedger(path=DEFAULT_LEDGER_PATH)``.
        self._path = Path(path) if path is not None else Path(DEFAULT_LEDGER_PATH)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def _now_iso(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def append(self, entry_type: str, **payload: Any) -> LedgerEntry:
        """Append a typed entry to the ledger."""
        entry = LedgerEntry(
            entry_type=entry_type,
            timestamp=self._now_iso(),
            payload=payload,
        )
        try:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), sort_keys=True) + "\n")
        except OSError as exc:
            logger.warning("shift_ledger_write_failed: %s", exc)
        return entry

    def read_all(self) -> list[LedgerEntry]:
        """Read all entries from the ledger."""
        if not self._path.exists():
            return []
        entries: list[LedgerEntry] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(LedgerEntry.from_dict(json.loads(line)))
            except (json.JSONDecodeError, TypeError) as exc:
                logger.debug("shift_ledger_parse_skip: %s", exc)
        return entries

    def read_recent(self, *, max_age_hours: float = 24.0) -> list[LedgerEntry]:
        """Read entries from the last N hours."""
        cutoff = time.time() - (max_age_hours * 3600)
        entries = self.read_all()
        recent: list[LedgerEntry] = []
        for entry in entries:
            try:
                ts = datetime.fromisoformat(entry.timestamp.replace("Z", "+00:00")).timestamp()
                if ts >= cutoff:
                    recent.append(entry)
            except (ValueError, AttributeError):
                recent.append(entry)  # keep unparseable entries
        return recent

    def read_by_type(self, entry_type: str) -> list[LedgerEntry]:
        """Read all entries of a specific type."""
        return [e for e in self.read_all() if e.entry_type == entry_type]

    # -- Convenience recording methods --

    def record_shift_start(
        self,
        *,
        shift_id: str,
        max_hours: float,
        benchmark_mode: str,
        queue_size: int,
    ) -> LedgerEntry:
        return self.append(
            "shift_start",
            shift_id=shift_id,
            max_hours=max_hours,
            benchmark_mode=benchmark_mode,
            queue_size=queue_size,
        )

    def record_shift_stop(
        self,
        *,
        shift_id: str,
        reason: str,
        cycles: int,
        duration_seconds: float,
    ) -> LedgerEntry:
        return self.append(
            "shift_stop",
            shift_id=shift_id,
            reason=reason,
            cycles=cycles,
            duration_seconds=duration_seconds,
        )

    def record_cycle_tick(
        self,
        *,
        queue_size: int,
        queue_removed: int = 0,
        open_prs: int,
        boss_running: bool,
        merge_running: bool,
        benchmark_fresh: bool,
        actions: list[str] | None = None,
        stop_reason: str = "",
    ) -> LedgerEntry:
        return self.append(
            "cycle_tick",
            queue_size=queue_size,
            queue_removed=queue_removed,
            open_prs=open_prs,
            boss_running=boss_running,
            merge_running=merge_running,
            benchmark_fresh=benchmark_fresh,
            actions=actions or [],
            stop_reason=stop_reason,
        )

    def record_service_restart(
        self, *, service: str, success: bool, detail: str = ""
    ) -> LedgerEntry:
        return self.append(
            "service_restart",
            service=service,
            success=success,
            detail=detail,
        )

    def record_pr_merged(self, *, pr_number: int, title: str = "") -> LedgerEntry:
        return self.append("pr_merged", pr_number=pr_number, title=title)

    def record_benchmark_run(
        self, *, run_id: int, conclusion: str, created_at: str = ""
    ) -> LedgerEntry:
        return self.append(
            "benchmark_run",
            run_id=run_id,
            conclusion=conclusion,
            created_at=created_at,
        )

    def record_failure(self, *, failure_type: str, detail: str = "") -> LedgerEntry:
        return self.append(failure_type, detail=detail)

    # -- Status summary --

    def _parse_timestamp(self, value: str) -> datetime | None:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            return None

    def _latest_shift_entries(self, entries: list[LedgerEntry]) -> list[LedgerEntry]:
        for index in range(len(entries) - 1, -1, -1):
            if entries[index].entry_type == "shift_start":
                return entries[index:]
        return []

    def _build_failure_policy_summary(
        self, entries: list[LedgerEntry]
    ) -> dict[str, dict[str, Any]]:
        counts = {
            "auth_failure": sum(1 for e in entries if e.entry_type == "auth_failure"),
            "publication_failure": sum(1 for e in entries if e.entry_type == "publication_failure"),
            "rate_limit": sum(1 for e in entries if e.entry_type == "rate_limit"),
            "permission_mismatch": sum(1 for e in entries if e.entry_type == "permission_mismatch"),
            "runtime_failure": sum(1 for e in entries if e.entry_type == "runtime_failure"),
            "service_failure": sum(1 for e in entries if e.entry_type == "service_failure"),
        }
        status: dict[str, dict[str, Any]] = {}
        for failure_type, count in counts.items():
            stop_after = FAILURE_THRESHOLDS[failure_type]
            status[failure_type] = {
                "count": count,
                "stop_after": stop_after,
                "remaining_self_heal_attempts": max(0, stop_after - count - 1),
                "will_stop": count >= stop_after,
            }
        return status

    def _build_green_shift_summary(self, entries: list[LedgerEntry]) -> dict[str, Any]:
        if not entries:
            return {
                "required_hours": GREEN_SHIFT_REQUIRED_HOURS,
                "observed_hours": 0.0,
                "window_complete": False,
                "benchmark_fresh": False,
                "queue_disciplined": False,
                "boss_service_healthy": False,
                "merge_service_healthy": False,
                "no_repeated_failures": False,
                "healthy_stop_reason": False,
                "is_green": False,
                "last_stop_reason": "",
            }

        ticks = [e for e in entries if e.entry_type == "cycle_tick"]
        stops = [e for e in entries if e.entry_type == "shift_stop"]
        last_tick = ticks[-1] if ticks else None
        last_stop = stops[-1] if stops else None
        start_time = self._parse_timestamp(entries[0].timestamp)
        end_time = self._parse_timestamp((last_stop or entries[-1]).timestamp)
        observed_hours = 0.0
        if start_time is not None and end_time is not None:
            observed_hours = max(0.0, (end_time - start_time).total_seconds() / 3600.0)

        failure_policy = self._build_failure_policy_summary(entries)
        last_stop_reason = ""
        if last_stop is not None:
            last_stop_reason = str(last_stop.payload.get("reason", ""))
        elif last_tick is not None:
            last_stop_reason = str(last_tick.payload.get("stop_reason", ""))

        current_queue_size = last_tick.payload.get("queue_size") if last_tick else None
        current_open_prs = last_tick.payload.get("open_prs") if last_tick else None
        boss_running = bool(last_tick.payload.get("boss_running")) if last_tick else False
        merge_running = bool(last_tick.payload.get("merge_running")) if last_tick else False
        benchmark_fresh = bool(last_tick.payload.get("benchmark_fresh")) if last_tick else False
        queue_removed = sum(int(e.payload.get("queue_removed", 0) or 0) for e in ticks)
        boss_service_healthy = boss_running or current_queue_size in (0, None)
        merge_service_healthy = merge_running or current_open_prs in (0, None)
        healthy_stop_reason = last_stop_reason == "" or any(
            last_stop_reason.startswith(p) for p in HEALTHY_STOP_PREFIXES
        )
        no_repeated_failures = all(not status["will_stop"] for status in failure_policy.values())
        queue_disciplined = queue_removed == 0
        window_complete = observed_hours >= GREEN_SHIFT_REQUIRED_HOURS

        return {
            "required_hours": GREEN_SHIFT_REQUIRED_HOURS,
            "observed_hours": round(observed_hours, 2),
            "window_complete": window_complete,
            "benchmark_fresh": benchmark_fresh,
            "queue_disciplined": queue_disciplined,
            "queue_removed": queue_removed,
            "boss_service_healthy": boss_service_healthy,
            "merge_service_healthy": merge_service_healthy,
            "no_repeated_failures": no_repeated_failures,
            "healthy_stop_reason": healthy_stop_reason,
            "last_stop_reason": last_stop_reason,
            "is_green": all(
                (
                    window_complete,
                    benchmark_fresh,
                    queue_disciplined,
                    boss_service_healthy,
                    merge_service_healthy,
                    no_repeated_failures,
                    healthy_stop_reason,
                )
            ),
        }

    def get_status_summary(self, *, max_age_hours: float = 24.0) -> dict[str, Any]:
        """Build a status summary from recent ledger entries.

        This is the single truthful view that replaces shell sampling.
        """
        all_entries = self.read_all()
        recent = self.read_recent(max_age_hours=max_age_hours)
        latest_shift_entries = self._latest_shift_entries(all_entries)

        shifts = [e for e in recent if e.entry_type == "shift_start"]
        stops = [e for e in recent if e.entry_type == "shift_stop"]
        ticks = [e for e in recent if e.entry_type == "cycle_tick"]
        merges = [e for e in recent if e.entry_type == "pr_merged"]
        benchmarks = [e for e in recent if e.entry_type == "benchmark_run"]
        restarts = [e for e in recent if e.entry_type == "service_restart"]
        auth_failures = [e for e in recent if e.entry_type == "auth_failure"]
        pub_failures = [e for e in recent if e.entry_type == "publication_failure"]
        rate_limit_failures = [e for e in recent if e.entry_type == "rate_limit"]
        permission_mismatches = [e for e in recent if e.entry_type == "permission_mismatch"]
        runtime_failures = [e for e in recent if e.entry_type == "runtime_failure"]
        service_failures = [e for e in recent if e.entry_type == "service_failure"]

        last_tick = ticks[-1] if ticks else None
        last_stop = stops[-1] if stops else None
        last_benchmark = benchmarks[-1] if benchmarks else None
        failure_policy = self._build_failure_policy_summary(latest_shift_entries)
        green_shift = self._build_green_shift_summary(latest_shift_entries)

        return {
            "period_hours": max_age_hours,
            "total_entries": len(recent),
            "shifts_started": len(shifts),
            "shifts_stopped": len(stops),
            "last_stop_reason": last_stop.payload.get("reason", "") if last_stop else "",
            "cycle_ticks": len(ticks),
            "prs_merged": len(merges),
            "pr_numbers_merged": [e.payload.get("pr_number") for e in merges],
            "service_restarts": len(restarts),
            "restart_successes": sum(1 for e in restarts if e.payload.get("success")),
            "restart_failures": sum(1 for e in restarts if not e.payload.get("success")),
            "auth_failures": len(auth_failures),
            "publication_failures": len(pub_failures),
            "rate_limit_failures": len(rate_limit_failures),
            "permission_mismatches": len(permission_mismatches),
            "runtime_failures": len(runtime_failures),
            "service_failures": len(service_failures),
            "benchmark_runs": len(benchmarks),
            "last_benchmark_conclusion": (
                last_benchmark.payload.get("conclusion", "") if last_benchmark else ""
            ),
            "current_queue_size": (last_tick.payload.get("queue_size", 0) if last_tick else None),
            "current_queue_removed": (
                last_tick.payload.get("queue_removed", 0) if last_tick else None
            ),
            "current_open_prs": (last_tick.payload.get("open_prs", 0) if last_tick else None),
            "current_boss_running": (last_tick.payload.get("boss_running") if last_tick else None),
            "current_merge_running": (
                last_tick.payload.get("merge_running") if last_tick else None
            ),
            "current_benchmark_fresh": (
                last_tick.payload.get("benchmark_fresh") if last_tick else None
            ),
            "failure_policy": failure_policy,
            "green_shift": green_shift,
        }
