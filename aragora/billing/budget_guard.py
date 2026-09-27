"""Fail-closed monthly spend cap for metered API calls (predictable-cost guard).

This is the anti-runaway-bill primitive: a hard, calendar-month USD ceiling that
**fails closed** — once the configured cap is reached, further metered calls are
refused (an exception) rather than silently billed. It is the safety net that
makes using metered providers (DeepSeek/Kimi/OpenAI/Anthropic API) predictable
even in autonomous loops.

Design:
- **Default OFF.** With no cap configured (``ARAGORA_MONTHLY_BUDGET_USD`` unset or
  <= 0) every call is allowed and nothing is persisted — zero behavior change.
  Opt in by exporting ``ARAGORA_MONTHLY_BUDGET_USD=200`` (or any limit).
- **Fail closed, even on storage failure.** When a cap is set,
  :func:`assert_within_budget` raises :class:`BudgetExceededError` once
  ``spent + estimated >= cap``. Spend is tracked in a flock-guarded JSON counter
  shared across processes; if the disk store cannot be read/written, a
  **process-local in-memory total** is used so the cap can never silently reset
  to 0 and let spend run away (a write failure logs at WARNING).
- **Cross-process safe.** ``fcntl.flock`` serializes the read-modify-write across
  the agent fan-out (boss_loop / swarm workers), so concurrent processes cannot
  under-count spend by last-writer-wins.

Note on precision: callers currently pass ``estimated_usd=0.0``, so the cap is
enforced on already-recorded spend; a single in-flight call can therefore
overshoot by at most its own cost before the *next* call is refused. Plumbing a
conservative per-call estimate (max_tokens * output_rate) would tighten this —
tracked as a follow-up.

This complements (does not replace) ``BudgetManager``'s richer per-org/overage
accounting — it is a process-local-resilient, always-available hard stop for the
common single-operator case.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl  # POSIX file locking (macOS + Linux CI)
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

__all__ = [
    "BudgetExceededError",
    "monthly_cap_usd",
    "is_enabled",
    "assert_within_budget",
    "record_spend",
    "current_spend_usd",
    "remaining_usd",
    "status",
]

_CAP_ENV = "ARAGORA_MONTHLY_BUDGET_USD"
_STORE_ENV = "ARAGORA_BUDGET_GUARD_STORE"
_lock = threading.Lock()
# Process-local fallback: survives disk-store failures so the cap can never
# silently reset to 0. {month: spent_usd}.
_mem_state: dict[str, float] = {}


class BudgetExceededError(RuntimeError):
    """Raised when a metered call would exceed the configured monthly cap."""


def monthly_cap_usd() -> float:
    """The configured monthly cap in USD, or 0.0 if unset/disabled."""
    raw = os.environ.get(_CAP_ENV, "").strip()
    if not raw:
        return 0.0
    try:
        cap = float(raw)
    except ValueError:
        return 0.0
    return cap if cap > 0 else 0.0


def is_enabled() -> bool:
    """True iff a positive monthly cap is configured (otherwise the guard is a no-op)."""
    return monthly_cap_usd() > 0.0


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _store_path() -> Path:
    override = os.environ.get(_STORE_ENV, "").strip()
    if override:
        return Path(override)
    configured_data_dir = os.environ.get("ARAGORA_DATA_DIR") or os.environ.get("ARAGORA_NOMIC_DIR")
    if configured_data_dir:
        return Path(configured_data_dir) / "budget_guard.json"
    # Preserve the historical machine-global ledger unless an operator
    # explicitly configures a data directory. This mirrors the persistence
    # helper's explicit environment precedence without adopting its linked-
    # worktree or CWD-relative defaults, which would fragment this shared
    # cross-process spend counter.
    return Path.home() / ".aragora" / "budget_guard.json"


def _mem_get() -> float:
    """Process-local spend for the current month (fallback when disk is unusable)."""
    return _mem_state.get(_current_month(), 0.0)


def _mem_add(delta: float) -> float:
    month = _current_month()
    _mem_state.clear()  # drop stale prior-month entries
    _mem_state[month] = _mem_state.get(month, 0.0) + delta
    return _mem_state[month]


def _disk_read() -> float | None:
    """Read this month's persisted spend, or None if the store is unusable.

    Returns 0.0 (not None) when the file is simply absent or from a prior month —
    those are valid "zero so far" states. None means a real I/O error.
    """
    path = _store_path()
    try:
        if not path.exists():
            return 0.0
        with path.open("r", encoding="utf-8") as fh:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
            try:
                data = json.load(fh)
            finally:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        # Corrupt/non-object store (null, list, scalar) — treat as unusable so
        # current_spend_usd() falls back to the in-memory total instead of
        # raising AttributeError on the next metered call (fail-closed, not crash).
        return None
    if data.get("month") != _current_month():
        return 0.0
    try:
        return float(data.get("spent_usd", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _disk_add(delta: float) -> bool:
    """Atomically add ``delta`` to this month's persisted spend (flock-guarded).

    Returns True on success, False if the store could not be updated.
    """
    path = _store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Open r+ (create if missing) and hold an exclusive lock across the whole
        # read-modify-write so concurrent processes cannot clobber each other.
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            raw = os.read(fd, 1_000_000).decode("utf-8") or ""
            spent = 0.0
            if raw.strip():
                try:
                    data = json.loads(raw)
                    if isinstance(data, dict) and data.get("month") == _current_month():
                        spent = float(data.get("spent_usd", 0.0))
                except (ValueError, TypeError, AttributeError):
                    spent = 0.0
            new_total = round(spent + delta, 6)
            payload = json.dumps({"month": _current_month(), "spent_usd": new_total}).encode()
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, payload)
            return True
        finally:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
    except OSError:
        return False


def current_spend_usd() -> float:
    """USD spent so far this calendar month (0.0 if guard disabled).

    Uses the larger of the persisted and process-local totals, so a disk failure
    can never make the guard *under*-report spend (which would fail open).
    """
    if not is_enabled():
        return 0.0
    with _lock:
        disk = _disk_read()
        mem = _mem_get()
        if disk is None:
            return mem
        return max(disk, mem)


def remaining_usd() -> float:
    """USD remaining under the cap this month (``inf`` if guard disabled)."""
    cap = monthly_cap_usd()
    if cap <= 0:
        return float("inf")
    return max(0.0, cap - current_spend_usd())


def assert_within_budget(estimated_usd: float = 0.0, *, label: str | None = None) -> None:
    """Raise :class:`BudgetExceededError` if this spend would reach the monthly cap.

    No-op when the guard is disabled. Uses ``>=`` so the cap stops AT the limit,
    not one call past it. ``estimated_usd`` is an optional pre-call cost estimate.
    """
    cap = monthly_cap_usd()
    if cap <= 0:
        return
    spent = current_spend_usd()
    if spent + max(0.0, estimated_usd) >= cap:
        where = f" ({label})" if label else ""
        raise BudgetExceededError(
            f"Monthly budget cap reached{where}: spent ${spent:.2f} + est "
            f"${max(0.0, estimated_usd):.2f} >= cap ${cap:.2f} ({_CAP_ENV}). "
            f"Refusing the call (fail-closed). Raise the cap or wait for the next "
            f"calendar month."
        )


def record_spend(amount_usd: float) -> None:
    """Add ``amount_usd`` to the current month's running total (no-op if disabled).

    Updates the process-local total first (always), then the shared disk store. A
    disk failure is logged at WARNING but never raises — the in-memory total keeps
    the cap enforced for this process so spend cannot run away unnoticed.
    """
    if not is_enabled() or amount_usd <= 0:
        return
    with _lock:
        _mem_add(float(amount_usd))
        if not _disk_add(float(amount_usd)):
            logger.warning(
                "budget_guard: could not persist spend to %s; using in-memory total "
                "($%.2f this process). Cap stays enforced but cross-process totals "
                "may be incomplete.",
                _store_path(),
                _mem_get(),
            )


def status() -> dict[str, float | bool | str]:
    """Snapshot of the guard for operator/CLI display."""
    cap = monthly_cap_usd()
    spent = current_spend_usd()
    return {
        "enabled": cap > 0,
        "month": _current_month(),
        "cap_usd": cap,
        "spent_usd": spent,
        "remaining_usd": remaining_usd(),
    }
