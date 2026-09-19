"""Swarm worker loop — the pheromone wired to the gate.

One worker repeatedly: atomic-claims a unit (``select_for``), runs the merge-gate
``dispatch``, and writes the *outcome* back to the shared environment — ``done`` on
success, a **park** constraint after repeated blocks. The merge-quorum gate stays
the only thing that says "yes" (propose = swarm, accept = gate, the
FunSearch/AlphaEvolve split); the ledger remembers failures **as data**, so the
whole swarm escapes a treadmill without any prompt self-editing.

``run_worker`` is process-agnostic: run one per thread or per process against the
same ``state_path``/``ledger_path`` and they self-partition. All cross-worker
mutation goes through the file-locked ledger, so workers never write
``MissionState`` — it stays a static backlog that only ``reconcile_from_ledger``
folds the swarm's results back into, from a single writer.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .intake import is_intake_feature
from .ledger import DEFAULT_LEASE_TTL, Ledger, LedgerCorruptError, select_for
from .handoff import Dispatch, Handoff
from .state import (
    PARK_KIND_MATERIALIZATION,
    PARK_KIND_MISSING_BRANCH,
    Feature,
    MissionState,
    Status,
    mission_owner_lock,
)

logger = logging.getLogger(__name__)

# Retryable park constraints expire after this many seconds so the ledger can
# hand the unit back to a worker for its paced retry (#8766 claude P1); the
# ledger attempt budget still bounds total retries at park_threshold.
RETRYABLE_PARK_CONSTRAINT_TTL = 300.0

# Same seam shape as live_gate.Runner: run argv in cwd, return stdout, raise on error.
GitRunner = Callable[[list[str], Path], str]

# (feature, ledger) -> live branch name. BranchMaterializer is the real one;
# tests inject fakes. Raises BranchMaterializationError on git failure.
Materialize = Callable[[Feature, Ledger], str]


class BranchMaterializationError(RuntimeError):
    """A worker could not turn ``metadata.branch_hint`` into a real branch."""


class BranchMaterializer:
    """Turn a claimed child's ``branch_hint`` into a REAL branch off the base (#8773).

    The last link of seed -> PR: decomposed intake children are born
    ``AWAITING_CLAIM`` carrying only a deterministic ``metadata.branch_hint``
    (#8766 — a fabricated ``metadata.branch`` would make the merge gate
    rev-parse a ref nobody created). When a swarm worker claims such a child,
    this materializer creates the branch from ``origin/main``, records it in
    the locked ledger (*after* the ref exists, never before), and returns the
    name for the worker to set as ``metadata.branch``.

    Idempotent across crash-retries: a ledger-recorded branch is adopted (and
    re-created if the ref was deleted). A plain colliding hint is never adopted;
    only this materializer's deterministic suffixed namespace can identify a
    crash orphan at the base head. Foreign commits fail closed.
    """

    def __init__(
        self,
        repo_root: str | Path,
        *,
        base: str = "origin/main",
        runner: GitRunner | None = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.base = base
        self.runner = runner or _run_git

    def __call__(self, feature: Feature, ledger: Ledger) -> str:
        try:
            return self._materialize(feature, ledger)
        except BranchMaterializationError:
            raise
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            # Normalize runner/process failures so the worker's existing
            # BranchMaterializationError path returns the unit to AWAITING_CLAIM.
            raise BranchMaterializationError(str(exc)) from exc

    def _materialize(self, feature: Feature, ledger: Ledger) -> str:
        recorded = ledger.materialized_branch(feature.id)
        if recorded:
            # A prior claim already materialized this unit: adopt its branch,
            # re-creating the ref only if someone deleted it since.
            if not self._ref_exists(recorded):
                self._create_branch(recorded)
            return recorded

        existing = str(feature.metadata.get("branch") or "").strip()
        if existing and self._ref_exists(existing):
            # Crash-recovery reuse (#8766 Gemini P2): a feature that already
            # carries a valid metadata.branch (e.g. the ledger was pruned or
            # cleared after a prior materialization) adopts that branch instead
            # of shadowing it with a fresh one from the hint. Re-record it so
            # later crash-retries adopt the same branch; a dead value falls
            # through to hint materialization as before.
            ledger.record_branch(feature.id, existing)
            return existing

        hint = str(feature.metadata.get("branch_hint") or "").strip()
        candidate = self._resolve_name(hint or f"mission/{feature.id}")
        if not self._ref_exists(candidate):
            self._create_branch(candidate)
        # Record ONLY after the ref is real — reconcile folds this value into
        # metadata.branch, and a record without a ref would re-open the
        # fabricated-branch crash loop (#8766 round 1).
        ledger.record_branch(feature.id, candidate)
        return candidate

    def _resolve_name(self, hint: str) -> str:
        for candidate in (hint, self._suffixed(hint)):
            if not self._ref_exists(candidate):
                return candidate
            if candidate != hint and self._head_of(candidate) == self._head_of(self.base):
                # Exactly at base AND in our deterministic hash-suffixed
                # namespace: an empty crash orphan of ours (created between
                # _create_branch and record_branch) -- adopt it. The PLAIN hint
                # name at base is NOT adopted (#8766 claude P3): every fresh
                # branch starts at base, so a foreign actor's just-pushed name
                # is indistinguishable from our orphan -- committing onto it
                # would be silent branch hijack. Fail toward the suffixed
                # namespace instead.
                return candidate
        raise BranchMaterializationError(
            f"branch {hint} and its deterministic suffix are both taken by "
            f"foreign commits; refusing to guess a third name"
        )

    @staticmethod
    def _suffixed(hint: str) -> str:
        return f"{hint}-{hashlib.sha256(hint.encode('utf-8')).hexdigest()[:8]}"

    def _ref_exists(self, branch: str) -> bool:
        try:
            self._head_of(branch)
        except RuntimeError:
            return False
        return True

    def _head_of(self, ref: str) -> str:
        return self.runner(
            ["git", "rev-parse", "--verify", "--end-of-options", ref], self.repo_root
        ).strip()

    def _create_branch(self, branch: str) -> None:
        self._validate_branch_name(branch)
        self.runner(["git", "branch", "--", branch, self.base], self.repo_root)
        logger.info("materialized branch %s from %s", branch, self.base)

    def _validate_branch_name(self, branch: str) -> None:
        if not branch or branch != branch.strip() or branch.startswith("-"):
            raise BranchMaterializationError(f"invalid branch name {branch!r}")
        try:
            self.runner(["git", "check-ref-format", "--branch", branch], self.repo_root)
        except RuntimeError as exc:
            raise BranchMaterializationError(f"invalid branch name {branch!r}: {exc}") from exc


def _run_git(cmd: list[str], cwd: Path) -> str:
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{cmd[0]} timed out after {exc.timeout}s") from exc
    if proc.returncode != 0:
        raise RuntimeError(
            (proc.stderr or proc.stdout or f"{cmd[0]} exited {proc.returncode}").strip()
        )
    return proc.stdout


def _needs_branch_materialization(feature: Feature) -> bool:
    """A decomposed child waiting for a worker to create its branch (#8773)."""
    branch = feature.metadata.get("branch")
    if isinstance(branch, str) and branch.strip():
        return False
    return bool(feature.metadata.get("branch_hint") or feature.metadata.get("intake_parent"))


class _LeaseHeartbeat:
    """Keep a *live* worker's lease fresh while a long dispatch runs.

    The lease TTL exists so a *dead* worker's claim evaporates and the unit becomes
    reclaimable. But a live worker running a legitimately long dispatch (e.g.
    collecting heterogeneous-model quorum evidence, minutes) would let its own lease
    expire, and another worker could then claim and double-dispatch the same unit
    (claude's [P2]). A background thread re-claims (refreshes ``claimed_at``) every
    ``ttl/3`` until the dispatch returns, so a live worker's lease never lapses; if
    the worker process dies, the thread dies with it and the TTL fallback still frees
    the unit. The heartbeat itself never raises into the worker, but it records
    lost ownership so the caller can fail closed after dispatch returns instead
    of treating a stale result as support.
    """

    def __init__(self, ledger: Ledger, unit: str, worker_id: str, ttl: float) -> None:
        self._ledger = ledger
        self._unit = unit
        self._worker_id = worker_id
        self._ttl = ttl
        self._interval = ttl / 3 if ttl > 0 else DEFAULT_LEASE_TTL / 3
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lost_reason: str | None = None

    @property
    def lost_reason(self) -> str | None:
        return self._lost_reason

    def __enter__(self) -> _LeaseHeartbeat:
        self._thread = threading.Thread(target=self._beat, daemon=True)
        self._thread.start()
        return self

    def _beat(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                if not self._ledger.claim_actionable(
                    self._unit,
                    self._worker_id,
                    constraint_key=f"feature:{self._unit}",
                    ttl=self._ttl,
                ):
                    self._lost_reason = (
                        f"lease heartbeat for {self._unit} lost ownership or actionability"
                    )
                    logger.warning(self._lost_reason)
                    self._stop.set()
                    return
            except (LedgerCorruptError, OSError, RuntimeError, ValueError):
                logger.warning("lease heartbeat for %s failed; will retry next beat", self._unit)

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)


@dataclass
class SwarmResult:
    """What one worker did this run."""

    worker_id: str
    done: list[str] = field(default_factory=list)
    parked: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)  # blocked attempts (incl. pre-park)
    lost_leases: list[str] = field(default_factory=list)
    # Units yielded back untouched (still AWAITING_CLAIM, zero retry burn): a
    # branch-hinted child this worker cannot materialize, or an awaiting_claim
    # handoff from a bridge (#8773). Another (capable) worker can claim them.
    awaiting_claim: list[str] = field(default_factory=list)


def run_worker(
    state_path: str | Path,
    ledger_path: str | Path,
    worker_id: str,
    dispatch: Dispatch,
    *,
    park_threshold: int = 2,
    max_units: int | None = None,
    materialize: Materialize | None = None,
) -> SwarmResult:
    """Drain available units for ``worker_id`` until the queue is dry to it.

    A unit that blocks but hasn't hit ``park_threshold`` stays available, so a
    later attempt (by this or any worker) retries it; once the *shared* attempt
    count reaches the threshold it is parked and the swarm moves on. Convergence
    is guaranteed: attempts accumulate in the ledger, so a persistent blocker is
    parked after at most ``park_threshold`` total attempts across the swarm.

    ``materialize`` (#8773) makes claimed AWAITING_CLAIM children *executable*:
    a claimed unit carrying only ``metadata.branch_hint`` gets a real branch
    created from the base (via :class:`BranchMaterializer` or a test fake) and
    ``metadata.branch`` set before dispatch — the branch is never fabricated
    without the ref existing. A git failure returns the child to the claimable
    pool with a diagnostic note (non-terminal, bounded by the same park
    accounting). Without a materializer, such a unit is yielded back untouched
    with ZERO retry burn, preserving #8766's no-burn property.

    Holds the *shared* side of :func:`mission_owner_lock` for its whole run: many
    workers coexist (shared), but an orchestrator (exclusive) cannot run against the
    same mission concurrently — so orchestrator-mode and swarm-mode never
    double-dispatch a feature. A long dispatch keeps its lease alive via
    :class:`_LeaseHeartbeat`.
    """
    with mission_owner_lock(state_path, exclusive=False):
        return _run_worker_fenced(
            state_path,
            ledger_path,
            worker_id,
            dispatch,
            park_threshold=park_threshold,
            max_units=max_units,
            materialize=materialize,
        )


def _run_worker_fenced(
    state_path: str | Path,
    ledger_path: str | Path,
    worker_id: str,
    dispatch: Dispatch,
    *,
    park_threshold: int,
    max_units: int | None,
    materialize: Materialize | None = None,
) -> SwarmResult:
    state = MissionState.load(state_path)
    ledger = Ledger(ledger_path)
    res = SwarmResult(worker_id=worker_id)
    yielded: set[str] = set()  # units handed back this run; never re-claim (livelock)

    def abandon_lost_lease(unit: str) -> None:
        ledger.rollback_attempt(f"feature:{unit}")
        res.lost_leases.append(unit)

    def yield_back(unit: str, reason: str) -> None:
        """Hand a claimed unit back untouched — still AWAITING_CLAIM, ZERO retry
        burn (#8766's property): no attempt, no park, lease released for a
        capable worker. Locally excluded so this run cannot livelock on it."""
        ledger.release(unit, worker_id)
        yielded.add(unit)
        res.awaiting_claim.append(unit)
        logger.info("worker %s yielded %s back to the claimable pool: %s", worker_id, unit, reason)

    n = 0
    while max_units is None or n < max_units:
        unit = select_for(state, ledger, worker_id, exclude=yielded)
        if unit is None:
            break
        feature = state.get(unit)

        if is_intake_feature(feature):
            yield_back(unit, "intake decomposition is orchestrator-owned")
            continue

        # A branch-hinted child needs its branch materialized before dispatch
        # (#8773). A worker with no git capability yields it back untouched.
        if materialize is None and _needs_branch_materialization(feature):
            yield_back(unit, "no branch materializer available in this worker")
            continue
        n += 1

        # Count the attempt BEFORE materialize/dispatch so a *raising* step is
        # bounded too.
        attempts = ledger.bump_attempt(f"feature:{unit}")

        handoff: Handoff | None = None
        if materialize is not None and _needs_branch_materialization(feature):
            try:
                branch = materialize(feature, ledger)
            except BranchMaterializationError as exc:
                # Infra-retryable by contract (#8766 openai P1): a git blip
                # parks under the dedicated PACED kind instead of flowing to
                # the generic failure path, where park_threshold=2 plus an
                # immediate same-worker reclaim could constraint-park (and
                # reconcile then BLOCK) fresh work in a single run. The
                # reconciler releases it after the backoff; triage bounds
                # persistent failure via retry_count → BLOCKED at the cap.
                handoff = Handoff(
                    success=False,
                    parked=True,
                    parked_kind=PARK_KIND_MATERIALIZATION,
                    blocked_reason=f"branch materialization failed: {exc}",
                    discovered=[
                        f"branch materialization for {unit} failed; parked for paced retry: {exc}"
                    ],
                )
            else:
                # The ref exists (just created/adopted) — only now is it safe
                # to hand the merge gate a live metadata.branch.
                feature.metadata["branch"] = branch

        heartbeat: _LeaseHeartbeat | None = None
        if handoff is None:
            try:
                # Heartbeat keeps the lease fresh so a long dispatch isn't reclaimed.
                heartbeat = _LeaseHeartbeat(ledger, unit, worker_id, DEFAULT_LEASE_TTL)
                with heartbeat:
                    handoff = dispatch(feature)
            except (
                Exception
            ) as exc:  # dispatch is an external callback — may raise anything  # noqa: BLE001
                handoff = Handoff(success=False, blocked_reason=f"dispatch raised: {exc!r}")

        if heartbeat is not None and heartbeat.lost_reason:
            logger.warning(
                "worker %s abandoned stale result for %s after losing the lease: %s",
                worker_id,
                unit,
                heartbeat.lost_reason,
            )
            abandon_lost_lease(unit)
            continue

        # A bridge answering awaiting_claim is a non-failure (#8758): the unit
        # is worker-bound work this dispatch cannot drive. Yield it back with
        # zero retry burn instead of aging it toward a park.
        if not handoff.success and handoff.awaiting_claim and not handoff.terminal:
            for note in handoff.discovered:
                ledger.record_discovery(unit, note)
            ledger.rollback_attempt(f"feature:{unit}")
            yield_back(unit, handoff.blocked_reason or "dispatch reported awaiting claim")
            continue

        # Discovered work is *advisory* in swarm mode (propose/accept boundary): the
        # swarm records what it found — discovered notes and proposed follow-ups —
        # but only the orchestrator+gate turn a note into executable work, so ledger
        # JSON can never inject a Feature. Recorded on *every* path, success or not.
        notes = list(handoff.discovered)
        notes += [f"follow-up proposed: {f.id} — {f.description}" for f in handoff.follow_ups]

        if handoff.success:
            # Atomic: done + notes + lease-release under ONE lock — no released-but-
            # not-done window for a concurrent claim_actionable to re-grab (the [P1]).
            if ledger.complete(unit, worker_id, discoveries=notes):
                res.done.append(unit)
            else:
                logger.warning(
                    "worker %s discarded success for %s after losing the lease",
                    worker_id,
                    unit,
                )
                abandon_lost_lease(unit)
                continue
            continue

        # Failure: record discoveries, optional park, and lease release as one owned
        # transaction. Terminal blocks (operator-gated / re-derive) park immediately;
        # retryable parked handoffs (e.g. missing live branch) also park immediately
        # without aging through repeated attempts.
        constraint_key = None
        constraint_reason = None
        constraint_ttl = 0.0
        parked = False
        if handoff.parked or handoff.terminal or attempts >= park_threshold:
            # Budget exhaustion WINS over the retryable flavor (#8766 claude
            # P1): a park that keeps recurring must reach the generic
            # "N blocks" kind (folds to operator-recoverable BLOCKED) instead
            # of cycling as retryable forever.
            if attempts >= park_threshold and not handoff.terminal:
                kind = f"{attempts} blocks"
            elif handoff.parked:
                kind = handoff.parked_kind or "retryable"
            else:
                kind = "terminal"
            constraint_key = f"feature:{unit}"
            constraint_reason = f"parked ({kind}): {handoff.blocked_reason}"
            if handoff.parked and not handoff.terminal and attempts < park_threshold:
                # Retryable parks must not wedge at the ledger layer (#8766
                # claude P1: ttl=0 means active FOREVER and only a successful
                # record_branch ever invalidates — the orchestrator's paced
                # unpark could never actually reach a worker). A finite TTL
                # lets claim_actionable hand the unit back to a worker once
                # the pacing window has plausibly elapsed, while the ledger
                # attempt budget (surviving across retries) still bounds the
                # loop at park_threshold -> BLOCKED.
                constraint_ttl = RETRYABLE_PARK_CONSTRAINT_TTL
            parked = True
        if ledger.fail(
            unit,
            worker_id,
            discoveries=notes,
            constraint_key=constraint_key,
            constraint_reason=constraint_reason,
            constraint_ttl=constraint_ttl,
        ):
            res.blocked.append(unit)
            if parked:
                res.parked.append(unit)
                logger.info("worker %s parked %s (%s)", worker_id, unit, kind)
        else:
            logger.warning(
                "worker %s discarded failure for %s after losing the lease",
                worker_id,
                unit,
            )
            abandon_lost_lease(unit)
            continue

    return res


def reconcile_from_ledger(state_path: str | Path, ledger_path: str | Path) -> int:
    """Fold the swarm's ledger-recorded completions back into ``MissionState``.

    In swarm mode the ledger is the source of truth (so no locked MissionState is
    needed across workers); call this once afterward — from a single writer — to
    make ``MissionState`` consistent with what the swarm did: ledger ``done`` →
    COMPLETED, active **parks** → BLOCKED for any not-completed feature (so a
    parked IN_PROGRESS checkpoint is not reclaimed by the orchestrator path,
    preserving the anti-treadmill guarantee), and worker-recorded **discovered
    notes** folded into the matching feature's notes (so swarm mode never silently
    drops what it found). Discovered work stays advisory — reconcile never
    *creates* a feature from ledger data, so there is no path to inject
    gate-bypassing work. Returns the number of features whose status or notes
    changed.

    Holds the exclusive side of :func:`mission_owner_lock`, so it cannot run while
    an orchestrator or live swarm worker is driving the same mission. Workers touch
    the ledger, not ``MissionState``, but they still hold the shared side of the
    owner fence for the duration of ``run_worker``.
    """
    with mission_owner_lock(state_path):
        return _reconcile_locked(state_path, ledger_path)


def _reconcile_locked(state_path: str | Path, ledger_path: str | Path) -> int:
    state = MissionState.load(state_path)
    ledger = Ledger(ledger_path)
    done = ledger.done_units()
    n = 0
    for feat in state.features:
        if feat.id in done and feat.status != Status.COMPLETED:
            if _has_stale_validation_done(feat):
                note = "ledger done ignored because validation reopened this feature"
                if note not in feat.notes:
                    feat.notes = (feat.notes + "\n" if feat.notes else "") + note
                    n += 1
                continue
            feat.status = Status.COMPLETED
            _clear_validation_reopen_metadata(feat)
            n += 1
        elif feat.status != Status.COMPLETED and ledger.is_excluded(f"feature:{feat.id}"):
            # Never downgrade COMPLETED on a stale park, but do fold active parks over
            # PENDING or IN_PROGRESS so the orchestrator cannot reclaim a parked unit.
            # Retryable parks keep their first-class PARKED state; generic
            # park-after-N blockers still become BLOCKED.
            reason = ledger.constraint_reason(f"feature:{feat.id}")
            park_kind = _retryable_park_kind_from_constraint(reason)
            if park_kind:
                if (
                    feat.status != Status.PARKED
                    or feat.metadata.get("parked_kind") != park_kind
                    or feat.metadata.get("parked_reason") != reason
                ):
                    state.mark_parked(feat.id, reason or "", kind=park_kind)
                    n += 1
            elif feat.status != Status.BLOCKED:
                feat.status = Status.BLOCKED
                n += 1
            if reason and not park_kind and reason not in feat.notes:
                # Keep operator context for generic park-after-N blockers.
                feat.notes = (feat.notes + "\n" if feat.notes else "") + f"BLOCKED (park): {reason}"
                n += 1
        elif feat.status == Status.PARKED and _retryable_park_kind_from_constraint(
            str(feat.metadata.get("parked_reason") or "")
        ):
            # Swarm-path release (#8766 openai P2): select_for only claims
            # PENDING/AWAITING_CLAIM/IN_PROGRESS and _reevaluate_parked lives
            # in the orchestrator — a pure reconcile_from_ledger flow would
            # otherwise leave the feature PARKED forever once its retryable
            # constraint TTL expires. The TTL IS the pacing on this path:
            # expiry releases the park back to claimable, the surviving
            # ledger attempt budget still bounds total retries, and budget
            # exhaustion folds to BLOCKED via the generic park above.
            state.unpark(feat.id, "retryable park constraint expired; paced retry due")
            n += 1

    # Fold discovered notes (advisory) into the matching feature. Never insert a
    # feature from ledger data — that stays the orchestrator+gate's job.
    for unit, notes in ledger.discoveries().items():
        try:
            feat = state.get(unit)
        except KeyError:
            continue
        for note in notes:
            stamp = f"discovered: {note}"
            if stamp not in feat.notes:
                feat.notes = (feat.notes + "\n" if feat.notes else "") + stamp
                n += 1

    # Fold worker-materialized branches (#8773): the ledger records a branch
    # only after the ref was actually created, so setting metadata.branch here
    # can never point the merge gate at a fabricated ref. An AWAITING_CLAIM
    # child whose branch is now live is promoted to PENDING — it no longer
    # waits on a worker, the orchestrator can drive it (parks folded above win:
    # a BLOCKED/COMPLETED child only gains the branch as provenance). A PARKED
    # missing-branch feature is likewise released (#8758 design decision): its
    # awaited precondition just appeared — and dispatch still re-verifies the
    # branch at claim time, so this promotion is fail-closed.
    for unit, branch in ledger.materialized_branches().items():
        try:
            feat = state.get(unit)
        except KeyError:
            continue
        existing = feat.metadata.get("branch")
        if not (isinstance(existing, str) and existing.strip()):
            feat.metadata["branch"] = branch
            n += 1
        if feat.status == Status.AWAITING_CLAIM:
            feat.status = Status.PENDING
            n += 1
        elif (
            feat.status == Status.PARKED
            and feat.metadata.get("parked_kind") == PARK_KIND_MISSING_BRANCH
        ):
            state.unpark(unit, f"worker materialized branch {branch}")
            ledger.invalidate_constraint(f"feature:{unit}")
            n += 1
    if n:
        state.save(state_path)
    return n


def _retryable_park_kind_from_constraint(reason: str | None) -> str | None:
    if not reason:
        return None
    if reason.startswith(f"parked ({PARK_KIND_MISSING_BRANCH}):"):
        return PARK_KIND_MISSING_BRANCH
    if reason.startswith(f"parked ({PARK_KIND_MATERIALIZATION}):"):
        # #8766 openai P1: a git-blip park folds back as a PACED retryable
        # park, never as BLOCKED — reconcile escalating it was the exact
        # mechanism that killed fresh mission work in one worker run.
        return PARK_KIND_MATERIALIZATION
    return None


def _has_stale_validation_done(feat) -> bool:
    return bool(
        feat.metadata.get("validation_reopened_by")
        and not feat.metadata.get("validation_reopened_ledger_done_invalidated")
    )


def _clear_validation_reopen_metadata(feat) -> None:
    for key in (
        "validation_reopened_by",
        "validation_reopened_reason",
        "validation_reopened_ledger_done_invalidated",
    ):
        feat.metadata.pop(key, None)
