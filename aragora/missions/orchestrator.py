"""MissionOrchestrator — the stateless tick loop.

The single property that makes a mission survive days: **the orchestrator holds
no state across ticks.** Every ``tick()`` reloads ``MissionState`` from disk,
advances exactly one feature, and persists before returning. Kill the process at
any point and a fresh ``run()`` resumes from the last persisted feature with no
lost or double-done work.

Dispatch is pluggable. Phase A ships a stub; the real engine wires
``swarm/boss_loop.py``'s tick + ``quorum_evidence``/``review_queue`` merge-gate in
as the ``dispatch`` callable (see the spec, Phase A2). The ``Handoff`` /
``Dispatch`` contract itself lives in :mod:`aragora.missions.handoff` and is
re-exported here.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .handoff import Dispatch, Handoff
from .ledger import LedgerCorruptError
from .state import (
    PARK_KIND_DECOMPOSITION,
    PARK_KIND_MATERIALIZATION,
    PARK_KIND_MISSING_BRANCH,
    Feature,
    MissionState,
    Status,
    mission_owner_lock,
)

logger = logging.getLogger(__name__)

__all__ = ["Dispatch", "Handoff", "MissionOrchestrator"]


class MissionOrchestrator:
    """Drives a mission to completion, one survivable tick at a time.

    ``max_retries`` bounds the retry loop: a feature that keeps failing — whether
    by *returning* a failure or by *raising* (kill-9 / 402 / poison) — is marked
    BLOCKED after this many attempts instead of being re-picked forever (the same
    park-after-N protection the swarm path has). A ``Handoff(terminal=True)`` is
    blocked immediately — no point retrying a fork only a human can resolve.

    Concurrency contract — orchestrator-mode and swarm-mode are **mutually
    exclusive**, enforced (not just documented) by the shared/exclusive
    :func:`mission_owner_lock`: ``run``/``tick`` take the exclusive side, swarm
    workers take the shared side, so a second orchestrator *or* a live swarm on the
    same ``state_path`` fails fast with :class:`MissionOwnershipError`. If a
    ``ledger_path`` is given (or a sibling ``ledger.json`` already exists), ``run``
    reconciles ledger results into state before ticking, so switching
    swarm→orchestrator never re-dispatches already-done work.
    Per-save persistence stays atomic via ``os.replace`` (no torn reads).
    """

    def __init__(
        self,
        state_path: str | Path,
        *,
        max_retries: int = 3,
        ledger_path: str | Path | None = None,
        decomposition_retry_backoff: float = 60.0,
    ) -> None:
        self.state_path = Path(state_path)
        self.max_retries = max_retries
        self.ledger_path = Path(ledger_path) if ledger_path is not None else None
        # Seconds before a PARK_KIND_DECOMPOSITION park is released for its next
        # bounded retry, doubling per failed attempt (#8766 Gemini P2): without
        # pacing, consecutive ticks would burn the whole retry budget in
        # milliseconds during a transient decomposer outage → premature TERMINAL.
        self.decomposition_retry_backoff = decomposition_retry_backoff

    # ---- single tick ---------------------------------------------------------

    def tick(self, dispatch: Dispatch) -> bool:
        """Advance one feature under the exclusive fence. Returns True if work was
        done, False if drained.

        Public single-tick entry point: it acquires the exclusive
        :func:`mission_owner_lock` for this one tick, including dispatch and
        triage. A hand-rolled ``while orch.tick(...)`` loop is therefore safe for
        each tick, but only :meth:`run` holds the fence continuously across the
        whole session. Inside :meth:`run` the loop calls :meth:`_tick` directly,
        holding the fence once for the whole run.
        """
        with mission_owner_lock(self.state_path, exclusive=True):
            if self._ledger_path_for_reconcile() is not None:
                self._reconcile_ledger()
            return self._tick(dispatch)

    def _tick(self, dispatch: Dispatch) -> bool:
        """One tick, assuming the exclusive fence is already held.

        Reload → reclaim orphans → pick next → mark in_progress (persist) →
        dispatch → triage handoff → persist. The persist *before* dispatch is
        what makes a mid-dispatch crash recoverable.
        """
        state = MissionState.load(self.state_path)

        # Reclaim orphans, honoring the retry cap — a *raising* dispatch (kill-9 /
        # recurring 402 / poison feature) leaves the feature IN_PROGRESS, and
        # without a cap here it would be reset to PENDING and re-picked forever.
        if self._reclaim_with_cap(state):
            state.save(self.state_path)

        # Reconciler re-evaluation (#8758 design decision): PARKED features are
        # re-checked every tick; when the missing precondition appears (or a
        # bounded decomposition retry is due) they transition parked → ready.
        if self._reevaluate_parked(state):
            state.save(self.state_path)

        feature = state.next_pending()
        if feature is None:
            if self._block_unrunnable_pending(
                state,
                "unmet or unsupported preconditions left no runnable mission work",
            ):
                state.save(self.state_path)
            return False

        # Provisionally count a *crash* BEFORE dispatch, so a raise leaves the count
        # on disk for reclaim to cap. _triage resets it the moment dispatch returns.
        # Reclaim allows one final idempotent confirmation when crash_count reaches
        # the cap, so a dispatch that succeeded externally but died before triage is
        # re-dispatched once to observe already-done/success instead of false-BLOCKed.
        feature.crash_count += 1
        state.mark_in_progress(feature.id)
        state.save(self.state_path)
        logger.info(
            "dispatch feature %s (%s), crash_count=%d retry_count=%d",
            feature.id,
            feature.milestone,
            feature.crash_count,
            feature.retry_count,
        )

        try:
            handoff = dispatch(feature)
        except Exception:  # noqa: BLE001 - dispatch is an external callback (402/poison may raise anything)
            # In-process bound: a raising dispatch must NOT abort the whole mission
            # ("set a goal and walk away" needs the loop to outlive one bad feature).
            # crash_count was persisted pre-dispatch; leave the feature IN_PROGRESS so
            # the next tick's reclaim caps it (PENDING under the cap, BLOCKED at it).
            logger.exception(
                "dispatch raised for feature %s (crash_count=%d); next tick reclaims/caps it",
                feature.id,
                feature.crash_count,
            )
            return True

        # Reload before triage: dispatch may have run in another process and the
        # on-disk truth may have advanced. Never trust the in-memory copy.
        state = MissionState.load(self.state_path)
        self._triage(state, feature.id, handoff)
        state.save(self.state_path)
        return True

    def _reclaim_with_cap(self, state: MissionState) -> bool:
        """Reset orphaned IN_PROGRESS features to PENDING, but BLOCK any that have
        crashed ``max_retries`` times in a row (the raising-dispatch bound). A
        non-crash-looping feature is always retried — so a crash *after* a
        successful dispatch is re-dispatched and confirmed, not false-blocked.
        Returns True if anything changed."""
        changed = False
        for feat in state.features:
            if feat.status != Status.IN_PROGRESS:
                continue
            changed = True
            if feat.crash_count > self.max_retries:
                feat.status = Status.BLOCKED
                feat.notes = (feat.notes + "\n" if feat.notes else "") + (
                    f"blocked: crashed {feat.crash_count}x in a row (poison/crash-looping dispatch)"
                )
            else:
                feat.status = Status.PENDING
        return changed

    def _reevaluate_parked(self, state: MissionState) -> bool:
        """Reconciler-owned re-evaluation of PARKED features (#8758 design decision).

        ``parked`` is retryable and this is the ONLY path out of it:

        * ``PARK_KIND_MISSING_BRANCH`` releases when a live ``metadata.branch``
          has actually appeared (folded in by ledger reconcile, or recorded by
          an operator). Release stays fail-closed: dispatch re-verifies the
          branch at claim time (``BossLoopDispatch`` re-checks
          ``metadata.branch`` before touching git), so a stale or lying state
          file re-parks instead of dispatching without a branch.
        * ``PARK_KIND_DECOMPOSITION`` releases for one bounded retry once the
          pacing backoff has elapsed (``decomposition_retry_backoff``, doubling
          per failed attempt — #8766 Gemini P2: consecutive ticks must not burn
          the whole retry budget in milliseconds during a transient outage);
          triage counts each failed attempt in ``retry_count`` and marks the
          feature TERMINAL at ``max_retries`` (default 3), so the park/release
          cycle can never ping-pong forever.
        * Unknown park kinds stay parked — fail-closed, for the operator.

        TERMINAL features are never re-evaluated: nothing auto-transitions out.
        Returns True if anything changed.
        """
        changed = False
        for feat in state.features:
            if feat.status != Status.PARKED:
                continue
            kind = feat.metadata.get("parked_kind")
            if kind == PARK_KIND_MISSING_BRANCH:
                branch = feat.metadata.get("branch")
                if isinstance(branch, str) and branch.strip():
                    # Dead-ref flavor pacing (#8766 claude P2): when a branch
                    # string is RECORDED, dispatch may still fail to resolve
                    # it and re-park — releasing on every tick would burn all
                    # retries in consecutive ticks during one git outage.
                    # Same pacing contract as decomposition. Parks with no
                    # recorded branch still release the moment one appears.
                    if feat.retry_count > 0 and not self._decomposition_retry_due(feat):
                        continue
                    state.unpark(feat.id, f"metadata.branch {branch} appeared")
                    logger.info("reconciler released parked feature %s: branch appeared", feat.id)
                    changed = True
            elif kind == PARK_KIND_DECOMPOSITION:
                if not self._decomposition_retry_due(feat):
                    continue
                state.unpark(feat.id, "retrying decomposition (bounded by the retry cap)")
                logger.info(
                    "reconciler released parked feature %s for a decomposition retry", feat.id
                )
                changed = True
            elif kind == PARK_KIND_MATERIALIZATION:
                # Same pacing contract as decomposition (#8766 openai P1): a
                # transient git failure is retried across real time, never
                # burned through in consecutive ticks.
                if not self._decomposition_retry_due(feat):
                    continue
                state.unpark(feat.id, "retrying branch materialization (bounded by the retry cap)")
                logger.info(
                    "reconciler released parked feature %s for a materialization retry", feat.id
                )
                changed = True
        return changed

    def _decomposition_retry_due(self, feat: Feature) -> bool:
        """Pace decomposition retries (#8766 Gemini P2): a park is released only
        after ``decomposition_retry_backoff`` seconds, doubling per failed
        attempt, so a transient decomposer outage is retried across real time
        instead of exhausting ``max_retries`` in consecutive ticks. A park
        without a numeric ``parked_at`` (pre-pacing state file) is due
        immediately, exactly as before."""
        parked_at = feat.metadata.get("parked_at")
        if not isinstance(parked_at, (int, float)):
            return True
        delay = self.decomposition_retry_backoff * (2 ** max(feat.retry_count - 1, 0))
        return (time.time() - parked_at) >= delay

    # ---- handoff triage ------------------------------------------------------

    def _triage(self, state: MissionState, feature_id: str, handoff: Handoff) -> None:
        feat = state.get(feature_id)
        feat.crash_count = 0  # dispatch returned — it did not crash this round
        if handoff.session_id and handoff.session_id not in feat.worker_session_ids:
            feat.worker_session_ids.append(handoff.session_id)

        for note in handoff.discovered:
            stamp = f"discovered: {note}"
            if stamp not in feat.notes:  # dedupe across retries
                feat.notes = (feat.notes + "\n" if feat.notes else "") + stamp

        for follow in handoff.follow_ups:
            proposal = f"follow-up proposed: {follow.id} — {follow.description}"
            stamp = f"discovered: {proposal}"
            if stamp not in feat.notes:
                feat.notes = (feat.notes + "\n" if feat.notes else "") + stamp
            if handoff.accept_follow_ups and not any(f.id == follow.id for f in state.features):
                if "paths" not in follow.metadata and "paths" in feat.metadata:
                    follow.metadata["paths"] = list(feat.metadata["paths"])
                state.insert_feature(follow)
                logger.info("handoff inserted accepted follow-up feature %s", follow.id)

        if handoff.success:
            state.mark_completed(feature_id)
            return

        if handoff.awaiting_claim and not handoff.terminal:
            # Claimable park (#8758): the work needs a worker, not a retry — move
            # it where select_for can claim it and burn NO retry budget, so an
            # auto-drain run can never age worker-bound work into BLOCKED.
            reason = handoff.blocked_reason or "awaiting worker claim"
            stamp = f"awaiting claim: {reason}"
            if stamp not in feat.notes:
                feat.notes = (feat.notes + "\n" if feat.notes else "") + stamp
            feat.status = Status.AWAITING_CLAIM
            return

        if handoff.parked and not handoff.terminal:
            # Retryable park (#8758 design decision): "not ready yet" is not
            # "dead". The reconciler's per-tick re-evaluation is the only exit.
            reason = handoff.blocked_reason or "parked pending reconciler re-evaluation"
            if handoff.parked_kind == PARK_KIND_DECOMPOSITION:
                # Each failed decomposition attempt burns retry budget; after
                # max_retries (default 3) the failure is permanent → TERMINAL.
                feat.retry_count += 1
                if feat.retry_count >= self.max_retries:
                    state.mark_terminal(
                        feature_id,
                        f"decomposition failed after {feat.retry_count} attempts: {reason}",
                    )
                    return
            elif handoff.parked_kind == PARK_KIND_MATERIALIZATION:
                # Infra-retryable git failure (#8766 openai P1): each failed
                # materialization attempt burns retry budget; at max_retries
                # the feature reaches BLOCKED — operator-recoverable, unlike
                # TERMINAL — instead of a transient blip killing fresh work.
                feat.retry_count += 1
                if feat.retry_count >= self.max_retries:
                    state.mark_blocked(
                        feature_id,
                        f"branch materialization failed after "
                        f"{feat.retry_count} attempts: {reason}",
                    )
                    return
            elif handoff.parked_kind == PARK_KIND_MISSING_BRANCH and _has_recorded_branch(feat):
                # Dead recorded ref (#8766 Gemini P1): metadata.branch is set but
                # dispatch could not resolve a live git ref for it, so the
                # reconciler would release this park on every tick (the branch
                # string is non-empty) and dispatch would immediately re-park it —
                # a tight unpark/repark CPU spin with no retry burn. Burn retry
                # budget on this flavor so a persistently dead ref reaches a
                # stable BLOCKED end state instead of spinning forever. A park
                # with NO branch recorded still burns nothing: it waits for the
                # branch to appear, exactly as before.
                feat.retry_count += 1
                if feat.retry_count >= self.max_retries:
                    state.mark_blocked(
                        feature_id,
                        f"metadata.branch has no live git ref after "
                        f"{feat.retry_count} attempts: {reason}",
                    )
                    return
            state.mark_parked(feature_id, reason, kind=handoff.parked_kind or "")
            return

        # Returned failure: bound by retry_count. Park a terminal block immediately
        # (never loop on operator-gated forks); retry a transient one until the cap.
        feat.retry_count += 1
        reason = handoff.blocked_reason or f"failed {feat.retry_count}x with no reason"
        if handoff.terminal and handoff.parked_kind == PARK_KIND_DECOMPOSITION:
            # Permanent decomposition failure that no retry can fix (e.g. a
            # blank goal) — TERMINAL per the #8758 design decision, not BLOCKED.
            state.mark_terminal(feature_id, reason)
        elif handoff.terminal or feat.retry_count >= self.max_retries:
            state.mark_blocked(feature_id, reason)
        else:
            feat.status = Status.PENDING  # bounded retry

    def _block_unrunnable_pending(self, state: MissionState, reason: str) -> bool:
        """Block PENDING features the mission can never reach — but leave alone any
        whose precondition chain can still complete outside this loop (an
        AWAITING_CLAIM child a worker will finish, or an IN_PROGRESS unit).
        Genuine dead ends — unsupported precondition tokens, references to missing
        or BLOCKED features, cycles — are still blocked, exactly as before."""
        reachable = self._may_yet_complete(state)
        changed = False
        for feat in state.features:
            if feat.status != Status.PENDING or feat.id in reachable:
                continue
            details = (
                ", ".join(feat.preconditions) if feat.preconditions else "no runnable dispatch"
            )
            state.mark_blocked(feat.id, f"{reason}: {details}")
            changed = True
        return changed

    @staticmethod
    def _may_yet_complete(state: MissionState) -> set[str]:
        """Feature ids that can still complete without operator intervention:
        completed/worker-bound/in-flight/parked features (a PARKED feature is
        retryable — the reconciler releases it when its precondition appears),
        plus (to a fixpoint) any PENDING feature gated only on those. A PENDING
        feature outside this set is a dead end — cycles, unsupported tokens, and
        TERMINAL dependencies never enter it."""
        reachable = {
            f.id
            for f in state.features
            if f.status
            in {Status.COMPLETED, Status.AWAITING_CLAIM, Status.IN_PROGRESS, Status.PARKED}
        }
        pending = [f for f in state.features if f.status == Status.PENDING]
        progressed = True
        while progressed:
            progressed = False
            for feat in pending:
                if feat.id in reachable:
                    continue
                if all(p.startswith("feature:") and p[8:] in reachable for p in feat.preconditions):
                    reachable.add(feat.id)
                    progressed = True
        return reachable

    # ---- run loop ------------------------------------------------------------

    def run(self, dispatch: Dispatch, max_ticks: int = 10_000) -> tuple[int, int]:
        """Tick until the queue drains (or a tick cap). Resumable across crashes.

        Holds the exclusive :func:`mission_owner_lock` for the whole run, so a second
        orchestrator *or* a live swarm fails fast with ``MissionOwnershipError``
        instead of racing ``next_pending``. If a ``ledger_path`` was given (or a
        sibling ``ledger.json`` already exists), folds the swarm's ledger results
        into state first (so swarm→orchestrator never re-dispatches done/parked
        work). The final state is reported precisely:
        complete, blocked-remaining, or hit the tick cap.
        """
        hit_cap = True
        with mission_owner_lock(self.state_path, exclusive=True):
            if self._ledger_path_for_reconcile() is not None:
                self._reconcile_ledger()
            for _ in range(max_ticks):
                if not self._tick(dispatch):
                    hit_cap = False
                    break
        state = MissionState.load(self.state_path)
        done, total = state.progress()
        if hit_cap and done < total:
            logger.warning(
                "mission run hit max_ticks=%d with %d/%d done — NOT complete, re-run to continue",
                max_ticks,
                done,
                total,
            )
        elif done < total:
            blocked = sum(1 for f in state.features if f.status == Status.BLOCKED)
            parked = sum(1 for f in state.features if f.status == Status.PARKED)
            terminal = sum(1 for f in state.features if f.status == Status.TERMINAL)
            logger.info(
                "mission run drained: %d/%d done, %d blocked, %d parked (retryable), "
                "%d terminal (queue has no runnable work)",
                done,
                total,
                blocked,
                parked,
                terminal,
            )
        else:
            logger.info("mission run complete: %d/%d features", done, total)
        return done, total

    def _reconcile_ledger(self) -> None:
        """Fold ledger results into state before driving (swarm→orchestrator switch).

        Imported lazily so importing the orchestrator does not load the swarm's
        git/subprocess machinery. Called while the exclusive fence is already held,
        so it does not re-acquire.
        """
        from .swarm import _reconcile_locked

        ledger_path = self._ledger_path_for_reconcile()
        if ledger_path is not None:
            try:
                _reconcile_locked(self.state_path, ledger_path)
            except LedgerCorruptError as exc:
                self._block_all_open_work(f"ledger reconcile failed closed: {exc}")

    def _block_all_open_work(self, reason: str) -> None:
        state = MissionState.load(self.state_path)
        changed = False
        for feat in state.features:
            if feat.status in {
                Status.PENDING,
                Status.IN_PROGRESS,
                Status.AWAITING_CLAIM,
                Status.PARKED,
            }:
                state.mark_blocked(feat.id, reason)
                changed = True
        if changed:
            state.save(self.state_path)

    def _ledger_path_for_reconcile(self) -> Path | None:
        if self.ledger_path is not None:
            return self.ledger_path
        default_path = self.state_path.with_name("ledger.json")
        return default_path if default_path.exists() else None


def _has_recorded_branch(feat: Feature) -> bool:
    """True iff the feature carries a non-empty ``metadata.branch`` value."""
    branch = feat.metadata.get("branch")
    return isinstance(branch, str) and bool(branch.strip())
