"""Ledger — the stigmergic shared environment ("pheromone") for a mission swarm.

This is the piece that lets *many simple workers* coordinate **without a foreman**
and without a recursive treadmill. It carries two kinds of trail:

1. **Claims / leases** — a worker atomically claims a unit with a TTL. Others see
   the claim and pick something else (response-threshold division of labor →
   non-overlapping fronts). Stale leases evaporate (pheromone decay), so a dead
   worker never permanently blocks a unit.
2. **Constraints / parks** — when a unit hits the same blocker twice, that fact is
   written to the *environment*, not into any agent's prompt (Reflexion-as-data,
   not prompt-rot). Every worker reads it and avoids the excluded behavior. A
   constraint evaporates on TTL or is invalidated when live state materially
   changes — so the swarm escapes treadmills *and* doesn't ossify.

Correctness hinges on **atomic claims**: two workers must never grab the same unit.
Mutations run under an OS file lock (``fcntl.flock``) with read-modify-write, so
the non-overlap property is real across processes, not aspirational.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import ModuleType

from .state import MissionState, Status, from_known_fields, preconditions_met

# POSIX-only; the package imports fine without it (locking raises a clear error).
fcntl: ModuleType | None
try:
    import fcntl as _fcntl

    fcntl = _fcntl
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None

logger = logging.getLogger(__name__)

DEFAULT_LEASE_TTL = 1800.0  # 30 min — a dead worker's claim evaporates after this


class LedgerCorruptError(RuntimeError):
    """Raised when ledger JSON cannot be decoded safely."""


@dataclass
class Lease:
    """A worker's atomic claim on one unit of work."""

    unit: str
    worker_id: str
    claimed_at: float
    ttl: float = DEFAULT_LEASE_TTL

    def is_expired(self, now: float) -> bool:
        return now - self.claimed_at >= self.ttl


@dataclass
class Constraint:
    """A learned exclusion — the pheromone that steers the swarm off a treadmill."""

    key: str
    reason: str
    recorded_at: float
    ttl: float = 0.0  # 0 = active until explicitly invalidated by live-state change

    def is_active(self, now: float) -> bool:
        return self.ttl <= 0 or now - self.recorded_at < self.ttl


@dataclass
class _LedgerData:
    leases: dict[str, Lease] = field(default_factory=dict)
    constraints: dict[str, Constraint] = field(default_factory=dict)
    attempts: dict[str, int] = field(default_factory=dict)
    done: set[str] = field(default_factory=set)  # units completed by any worker
    # Worker-discovered work, recorded to the *locked* ledger so swarm mode never
    # drops it. These are *advisory notes only* (propose/accept boundary): the swarm
    # records what it found; only the orchestrator+gate turn a note into executable
    # work, so there is no path for ledger JSON to inject a Feature. unit -> notes.
    discoveries: dict[str, list[str]] = field(default_factory=dict)
    # Branches a worker MATERIALIZED at claim time (#8773). unit -> branch name.
    # Recorded only AFTER the ref actually exists (never fabricated), so reconcile
    # can safely fold it into ``metadata.branch``. This does not weaken the
    # propose/accept boundary: a branch name only *points* the merge gate at a
    # ref that must still pass rev-parse, the foreign-commit guard, and quorum.
    branches: dict[str, str] = field(default_factory=dict)


class Ledger:
    """Atomic, file-locked shared state for a worker swarm.

    Mutations acquire an exclusive lock, reload from disk, mutate, persist, and
    release — so concurrent ``claim()`` calls from many processes can never
    double-claim a unit.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    # ---- atomic claim (the load-bearing op) ---------------------------------

    def claim(
        self, unit: str, worker_id: str, ttl: float = DEFAULT_LEASE_TTL, *, now: float | None = None
    ) -> bool:
        """Claim ``unit`` for ``worker_id``. Returns False if actively held by another.

        Atomic across processes. An expired lease is reclaimable; re-claiming your
        own live lease is idempotent True.
        """
        now = time.time() if now is None else now
        with self._locked():
            data = self._load()
            held = data.leases.get(unit)
            if held and not held.is_expired(now) and held.worker_id != worker_id:
                return False
            data.leases[unit] = Lease(unit=unit, worker_id=worker_id, claimed_at=now, ttl=ttl)
            self._save(data)
            return True

    def claim_actionable(
        self,
        unit: str,
        worker_id: str,
        *,
        constraint_key: str,
        ttl: float = DEFAULT_LEASE_TTL,
        now: float | None = None,
    ) -> bool:
        """Atomically claim ``unit`` ONLY if it is still actionable — not done, not
        parked, and not held by another worker — all checked **under the lock** so a
        concurrent ``record_done``/``record_constraint`` can't slip a completed or
        parked unit past the check-then-claim race (the TOCTOU select_for had)."""
        now = time.time() if now is None else now
        with self._locked():
            data = self._load()
            if unit in data.done:
                return False
            c = data.constraints.get(constraint_key)
            if c and c.is_active(now):
                return False
            held = data.leases.get(unit)
            if held and not held.is_expired(now) and held.worker_id != worker_id:
                return False
            data.leases[unit] = Lease(unit=unit, worker_id=worker_id, claimed_at=now, ttl=ttl)
            self._save(data)
            return True

    def release(self, unit: str, worker_id: str) -> bool:
        with self._locked():
            data = self._load()
            held = data.leases.get(unit)
            if held and held.worker_id == worker_id:
                del data.leases[unit]
                self._save(data)
                return True
            return False

    def active_claims(self, *, now: float | None = None) -> dict[str, str]:
        """unit -> worker_id for all non-expired leases (lock-free read)."""
        now = time.time() if now is None else now
        data = self._load()
        return {u: lease.worker_id for u, lease in data.leases.items() if not lease.is_expired(now)}

    # ---- constraints / parks (the pheromone) --------------------------------

    def record_constraint(
        self, key: str, reason: str, ttl: float = 0.0, *, now: float | None = None
    ) -> None:
        now = time.time() if now is None else now
        with self._locked():
            data = self._load()
            data.constraints[key] = Constraint(key=key, reason=reason, recorded_at=now, ttl=ttl)
            self._save(data)
            logger.info("recorded constraint %s: %s", key, reason)

    def is_excluded(self, key: str, *, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        c = self._load().constraints.get(key)
        return bool(c and c.is_active(now))

    def constraint_reason(self, key: str, *, now: float | None = None) -> str | None:
        """The reason of the active constraint at ``key`` (for handoff/debug), or None."""
        now = time.time() if now is None else now
        c = self._load().constraints.get(key)
        return c.reason if c and c.is_active(now) else None

    def invalidate_constraint(self, key: str) -> None:
        """Evaporate a constraint because live state materially changed.

        Also resets the attempt budget for ``key``: "invalidate and retry" only
        makes sense if the unit gets a fresh budget — otherwise it inherits the old
        ``attempts`` count and re-parks on its very first next failure, defeating the
        escape path entirely.
        """
        with self._locked():
            data = self._load()
            constraint_dropped = data.constraints.pop(key, None) is not None
            attempts_reset = data.attempts.pop(key, None) is not None
            if constraint_dropped or attempts_reset:
                self._save(data)

    def bump_attempt(self, key: str) -> int:
        """Increment + return the attempt count for ``key`` (drives park-after-N)."""
        with self._locked():
            data = self._load()
            data.attempts[key] = data.attempts.get(key, 0) + 1
            n = data.attempts[key]
            self._save(data)
            return n

    def rollback_attempt(self, key: str) -> int:
        """Undo one provisional attempt when no durable outcome was recorded."""
        with self._locked():
            data = self._load()
            current = data.attempts.get(key, 0)
            if current <= 1:
                data.attempts.pop(key, None)
                n = 0
            else:
                n = current - 1
                data.attempts[key] = n
            self._save(data)
            return n

    def attempts(self, key: str) -> int:
        return self._load().attempts.get(key, 0)

    # ---- completion (shared, so the swarm needs no locked MissionState) ------

    def record_done(self, unit: str) -> None:
        with self._locked():
            data = self._load()
            data.done.add(unit)
            self._save(data)

    def invalidate_done(self, unit: str) -> bool:
        """Remove a stale completion marker after downstream validation reopens work."""
        with self._locked():
            data = self._load()
            if unit not in data.done:
                return False
            data.done.remove(unit)
            self._save(data)
            return True

    def complete(
        self,
        unit: str,
        worker_id: str,
        *,
        discoveries: list[str] | None = None,
        now: float | None = None,
    ) -> bool:
        """Atomically finish ``unit``: mark done, fold any discovery notes, and drop
        the worker's lease — **all under one lock**.

        This is the load-bearing fix for the double-claim window: if ``record_done``
        and ``release`` are separate calls, there is an instant where the unit is
        released-but-not-done, and a concurrent ``claim_actionable`` (which checks
        done + constraint + lease) re-grabs the just-finished unit. Doing all three
        in a single locked transaction closes that window structurally. The outcome
        is applied only if ``worker_id`` still owns the lease; a worker whose lease
        lapsed and was claimed by another process must not mark stale work done.
        """
        now = time.time() if now is None else now
        with self._locked():
            data = self._load()
            held = data.leases.get(unit)
            if not held or held.worker_id != worker_id or held.is_expired(now):
                return False
            data.done.add(unit)
            if discoveries:
                notes = data.discoveries.setdefault(unit, [])
                for note in discoveries:
                    if note not in notes:
                        notes.append(note)
            del data.leases[unit]
            self._save(data)
            return True

    def fail(
        self,
        unit: str,
        worker_id: str,
        *,
        discoveries: list[str] | None = None,
        constraint_key: str | None = None,
        constraint_reason: str | None = None,
        constraint_ttl: float = 0.0,
        now: float | None = None,
    ) -> bool:
        """Atomically finish a failed attempt owned by ``worker_id``.

        Optional discovery notes, optional park constraint, and lease release happen
        in one locked transaction. This avoids the failure-path window where a worker
        releases a repeatedly-blocking unit before recording the park, allowing one
        extra claimant to slip in. Returns False if the caller no longer owns the
        lease, in which case no stale outcome is recorded.
        """
        now = time.time() if now is None else now
        with self._locked():
            data = self._load()
            held = data.leases.get(unit)
            if not held or held.worker_id != worker_id or held.is_expired(now):
                return False
            if discoveries:
                notes = data.discoveries.setdefault(unit, [])
                for note in discoveries:
                    if note not in notes:
                        notes.append(note)
            if constraint_key and constraint_reason:
                data.constraints[constraint_key] = Constraint(
                    key=constraint_key,
                    reason=constraint_reason,
                    recorded_at=now,
                    ttl=constraint_ttl,
                )
            del data.leases[unit]
            self._save(data)
            return True

    def is_done(self, unit: str) -> bool:
        return unit in self._load().done

    def done_units(self) -> set[str]:
        return set(self._load().done)

    # ---- discovered work (advisory notes; swarm can't touch MissionState) -----

    def record_discovery(self, unit: str, note: str) -> None:
        """Record a discovered note against ``unit`` (deduped). Advisory only."""
        with self._locked():
            data = self._load()
            notes = data.discoveries.setdefault(unit, [])
            if note not in notes:
                notes.append(note)
                self._save(data)

    def discoveries(self) -> dict[str, list[str]]:
        """unit -> discovered notes (reconcile folds these into feature notes)."""
        return {u: list(notes) for u, notes in self._load().discoveries.items()}

    # ---- materialized branches (claim-time transition record, #8773) -----------

    def record_branch(self, unit: str, branch: str) -> None:
        """Durably record the branch a worker materialized for ``unit``.

        Contract: callers record only after the ref actually exists (the #8766
        round-1 lesson — never fabricate a branch nobody created). The record
        makes a crash-retried claim adopt the same branch instead of spawning
        suffix litter, and lets reconcile fold ``metadata.branch`` into state.
        """
        with self._locked():
            data = self._load()
            data.branches[unit] = branch
            self._save(data)

    def materialized_branch(self, unit: str) -> str | None:
        """The branch previously materialized for ``unit``, or None."""
        return self._load().branches.get(unit)

    def materialized_branches(self) -> dict[str, str]:
        """unit -> materialized branch (reconcile folds these into metadata)."""
        return dict(self._load().branches)

    def prune(self, *, now: float | None = None) -> tuple[int, int]:
        """Evaporate expired leases + constraints. Returns (leases, constraints) dropped."""
        now = time.time() if now is None else now
        with self._locked():
            data = self._load()
            dead_l = [u for u, ls in data.leases.items() if ls.is_expired(now)]
            dead_c = [k for k, c in data.constraints.items() if not c.is_active(now)]
            for u in dead_l:
                del data.leases[u]
            for k in dead_c:
                del data.constraints[k]
            if dead_l or dead_c:
                self._save(data)
            return len(dead_l), len(dead_c)

    # ---- persistence (atomic) -----------------------------------------------

    @contextlib.contextmanager
    def _locked(self):
        if fcntl is None:  # pragma: no cover - non-POSIX
            raise RuntimeError(
                "Ledger requires POSIX fcntl file locking (not available on this platform)"
            )
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("w") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    def _load(self) -> _LedgerData:
        if not self.path.exists():
            return _LedgerData()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise LedgerCorruptError(f"corrupt ledger JSON at {self.path}: {exc.msg}") from exc
        return _LedgerData(
            leases={u: from_known_fields(Lease, v) for u, v in raw.get("leases", {}).items()},
            constraints={
                k: from_known_fields(Constraint, v) for k, v in raw.get("constraints", {}).items()
            },
            attempts=dict(raw.get("attempts", {})),
            done=set(raw.get("done", [])),
            discoveries={u: list(notes) for u, notes in raw.get("discoveries", {}).items()},
            branches={u: str(b) for u, b in raw.get("branches", {}).items()},
        )

    def _save(self, data: _LedgerData) -> None:
        payload = {
            "leases": {u: asdict(ls) for u, ls in data.leases.items()},
            "constraints": {k: asdict(c) for k, c in data.constraints.items()},
            "attempts": data.attempts,
            "done": sorted(data.done),
            "discoveries": data.discoveries,
            "branches": data.branches,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=f".{self.path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            raise


def select_for(
    state: MissionState,
    ledger: Ledger,
    worker_id: str,
    *,
    ttl: float = DEFAULT_LEASE_TTL,
    now: float | None = None,
    exclude: set[str] | None = None,
) -> str | None:
    """Stigmergic pickup: atomic-claim the first available feature for ``worker_id``.

    "Available" = pending, awaiting a worker claim (``Status.AWAITING_CLAIM`` —
    e.g. a decomposed intake child with no branch yet, #8758), or orphaned
    in-progress; known preconditions met; not done (in state OR the ledger); not
    parked (active constraint); and not claimed by another worker.
    ``exclude`` skips units this worker already yielded back this run (e.g. an
    AWAITING_CLAIM child it cannot materialize a branch for, #8773) so the loop
    cannot livelock re-claiming its own hand-back.
    Returns the claimed feature id, or None if nothing is available to *this* worker.

    This is how non-overlapping fronts emerge with no central dispatcher: every
    worker scans the same queue and the locked ledger arbitrates who gets what.
    Selection only *selects* — the park/attempt policy lives in the worker loop.

    Note: when the only remaining work is precondition-gated on an in-progress unit
    held by another worker, this returns None and the caller idles — effective
    parallelism degrades on long dependency chains (convergence still holds with
    >=1 live worker).
    """
    now = time.time() if now is None else now
    # Precondition gating reads the static backlog + ledger done (a feature
    # completing mid-scan only opens a gate slightly later — no correctness risk).
    done = {f.id for f in state.features if f.status == Status.COMPLETED} | ledger.done_units()

    for feat in state.features:
        # PENDING is normal swarm work. AWAITING_CLAIM is work whose whole point
        # is to be claimed here (a decomposed child waiting for a worker/branch).
        # IN_PROGRESS is also claimable because run_worker holds the shared side
        # of the owner fence; if an orchestrator were alive its exclusive lock
        # would block the swarm before selection. That lets swarm-only recovery
        # reclaim crash-orphaned checkpointed units.
        claimable = {Status.PENDING, Status.AWAITING_CLAIM, Status.IN_PROGRESS}
        if feat.status not in claimable or feat.id in done:
            continue
        if exclude and feat.id in exclude:
            continue
        if not preconditions_met(feat.preconditions, done):
            continue
        # Atomic claim: not-done / not-parked / not-claimed is re-checked under the
        # lock, so a concurrent done/park can't race past the selection.
        if ledger.claim_actionable(
            feat.id, worker_id, constraint_key=f"feature:{feat.id}", ttl=ttl, now=now
        ):
            return feat.id
    return None
