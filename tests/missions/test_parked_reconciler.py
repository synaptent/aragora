"""Tests for the parked/terminal split + reconciler re-evaluation (#8758).

Pins the operator-delegated design decision (issue #8758, 2026-07-02) that
unparks the round-2 "parked children unclaimable forever" finding:

* ``parked`` (``Status.PARKED``) is retryable and **reconciler-owned**: an
  intake/branchless feature parks NON-terminally with ``parked_reason`` /
  ``parked_at`` / ``retry_count`` recorded on the Feature;
* each reconciler tick re-evaluates parked Features — when TaskDecomposer
  succeeds (or the missing branch appears) the Feature transitions
  parked → ready and its children become claimable by ``select_for``;
* ``terminal`` (``Status.TERMINAL``) is permanent, reserved for decomposition
  that failed after N attempts (default 3) or an explicit cancel; nothing
  auto-transitions out of it;
* fail-closed: nothing dispatches without a branch — dispatch re-verifies the
  precondition at claim time instead of trusting stored state, so a promoted
  feature whose branch is still missing re-parks without touching git.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from aragora.missions import (
    Feature,
    Handoff,
    Ledger,
    MissionOrchestrator,
    MissionState,
    Status,
    select_for,
)
from aragora.missions.dispatch import BossLoopDispatch, GateVerdict
from aragora.missions.intake import IntakeBridgeDispatch
from aragora.missions.state import (
    PARK_KIND_DECOMPOSITION,
    PARK_KIND_MATERIALIZATION,
    PARK_KIND_MISSING_BRANCH,
)
from aragora.missions.swarm import _reconcile_locked
from aragora.nomic.task_decomposer import SubTask

GOAL = "Add a rate limiter to the API server"


class RecordingGate:
    """Fake merge gate that records whether the live surface was ever touched."""

    def __init__(self) -> None:
        self.branch_calls = 0
        self.merge_calls: list[tuple[str, str]] = []

    def branch_for(self, feature: Feature) -> str:
        self.branch_calls += 1
        return str(feature.metadata["branch"])

    def already_merged(self, branch: str) -> bool:
        return False

    def head_of(self, branch: str) -> str:
        return "deadbeef"

    def foreign_commits(self, branch, base, allowed_prefixes) -> list[str]:
        return []

    def tier_of(self, feature: Feature) -> int:
        return 0

    def collect_evidence(self, branch, head) -> GateVerdict:
        return GateVerdict(satisfied=True)

    def merge_head_bound(self, branch, head) -> bool:
        self.merge_calls.append((branch, head))
        return True


def _refusing_inner(feature: Feature) -> Handoff:
    raise AssertionError(f"inner dispatch must never see feature {feature.id}")


def _subtasks(goal: str, paths: list[str]) -> list[SubTask]:
    return [
        SubTask(id="subtask_1", title="Server Changes", description="Wire it in"),
        SubTask(id="subtask_2", title="Tests", description="Cover it"),
    ]


def _seeded_intake_state(tmp_path: Path) -> Path:
    state_path = tmp_path / "state.json"
    MissionState(
        mission_id="mission-test",
        goal=GOAL,
        milestones=["mission"],
        features=[Feature(id="mission-intake", description=GOAL, milestone="mission")],
    ).save(state_path)
    return state_path


def _branchless_state(tmp_path: Path, feature_id: str = "f1") -> Path:
    state_path = tmp_path / "state.json"
    MissionState(
        mission_id="mission-test",
        goal=GOAL,
        milestones=["m"],
        features=[Feature(id=feature_id, description="branch-backed work", milestone="m")],
    ).save(state_path)
    return state_path


# ---- parked, not terminal ------------------------------------------------------


def test_branchless_feature_parks_retryable_with_transition_recorded(tmp_path):
    """The round-2 gap, fixed per the design decision: a feature without
    metadata.branch is parked (retryable, reconciler-owned) — never terminal,
    never BLOCKED — with parked_reason/parked_at/retry_count on the Feature."""
    state_path = _branchless_state(tmp_path)
    gate = RecordingGate()

    MissionOrchestrator(state_path).tick(BossLoopDispatch(gate))

    feat = MissionState.load(state_path).get("f1")
    assert feat.status == Status.PARKED
    assert feat.status not in {Status.BLOCKED, Status.TERMINAL}
    assert "metadata.branch" in feat.metadata["parked_reason"]
    assert isinstance(feat.metadata["parked_at"], float)
    assert feat.metadata["parked_kind"] == PARK_KIND_MISSING_BRANCH
    # Waiting on an external precondition burns no retry budget toward terminal.
    assert feat.retry_count == 0
    assert gate.branch_calls == 0  # fail-closed: live git never touched


def test_missing_branch_park_stays_parked_while_branch_is_absent(tmp_path):
    """The reconciler releases a missing-branch park only when the branch has
    actually appeared — repeated drains leave it PARKED, never BLOCKED."""
    state_path = _branchless_state(tmp_path)
    gate = RecordingGate()
    orch = MissionOrchestrator(state_path)

    orch.run(BossLoopDispatch(gate), max_ticks=10)  # must drain
    orch.run(BossLoopDispatch(gate), max_ticks=10)  # still drains, still parked

    feat = MissionState.load(state_path).get("f1")
    assert feat.status == Status.PARKED
    assert gate.branch_calls == 0


# ---- reconciler re-evaluation: parked -> ready ----------------------------------


def test_reconciler_releases_missing_branch_park_when_branch_appears(tmp_path):
    """parked → ready: once metadata.branch appears (operator/ledger fold), the
    next reconciler tick releases the park and the feature dispatches through
    the merge gate."""
    state_path = _branchless_state(tmp_path)
    gate = RecordingGate()
    orch = MissionOrchestrator(state_path)
    orch.tick(BossLoopDispatch(gate))
    assert MissionState.load(state_path).get("f1").status == Status.PARKED

    # The awaited precondition appears (e.g. a worker materialized the branch).
    state = MissionState.load(state_path)
    state.get("f1").metadata["branch"] = "mission/f1"
    state.save(state_path)

    orch.tick(BossLoopDispatch(gate))

    feat = MissionState.load(state_path).get("f1")
    assert feat.status == Status.COMPLETED
    assert "unparked" in feat.notes
    # Park bookkeeping is cleared on release; the note keeps the history.
    assert "parked_reason" not in feat.metadata
    assert gate.merge_calls == [("mission/f1", "deadbeef")]


def test_dead_recorded_branch_reaches_blocked_instead_of_spinning(tmp_path):
    """#8766 Gemini P1: metadata.branch is set but the ref does not exist in
    git — the reconciler releases the park on every tick (the branch string is
    non-empty) and dispatch immediately re-parks it. Without retry burn that is
    a tight unpark/repark CPU spin; with it, the feature reaches a stable
    BLOCKED end state after max_retries bounded attempts."""

    class DeadRefGate(RecordingGate):
        def head_of(self, branch: str) -> str:
            raise RuntimeError(f"fatal: unknown revision or path {branch}")

    state_path = _branchless_state(tmp_path)
    state = MissionState.load(state_path)
    state.get("f1").metadata["branch"] = "mission/f1"  # recorded, but the ref is dead
    state.save(state_path)
    gate = DeadRefGate()
    inner = BossLoopDispatch(gate)
    calls = {"n": 0}

    def counting(feature: Feature) -> Handoff:
        calls["n"] += 1
        return inner(feature)

    MissionOrchestrator(state_path, decomposition_retry_backoff=0.0).run(
        counting, max_ticks=50
    )  # must drain, not spin (dead-ref releases are paced; zero backoff here)

    feat = MissionState.load(state_path).get("f1")
    assert feat.status == Status.BLOCKED  # stable end state, not PARKED/PENDING
    assert feat.retry_count == 3
    assert "no live git ref" in feat.notes
    assert calls["n"] == 3  # bounded: one dispatch per burned retry, then BLOCKED
    assert gate.merge_calls == []


def test_missing_branch_park_without_branch_still_burns_no_retries(tmp_path):
    """The dead-ref bound must not regress the waiting flavor: a park with NO
    metadata.branch recorded keeps burning zero retry budget while it waits."""
    state_path = _branchless_state(tmp_path)
    gate = RecordingGate()
    orch = MissionOrchestrator(state_path)

    orch.run(BossLoopDispatch(gate), max_ticks=10)
    orch.run(BossLoopDispatch(gate), max_ticks=10)

    feat = MissionState.load(state_path).get("f1")
    assert feat.status == Status.PARKED
    assert feat.retry_count == 0


def test_reconciler_tick_with_working_decomposer_makes_children_claimable(tmp_path):
    """The acceptance path from the design decision: intake parks on a failing
    decomposer; when TaskDecomposer succeeds on a later reconciler tick the
    Feature transitions parked → ready → decomposed, and its children are
    claimable by the existing select_for machinery."""
    calls = {"n": 0}

    def recovering(goal: str, paths: list[str]) -> list[SubTask]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("provider hiccup")
        return _subtasks(goal, paths)

    state_path = _seeded_intake_state(tmp_path)
    bridge = IntakeBridgeDispatch(_refusing_inner, decompose=recovering)
    # Zero backoff: this test pins the release semantics, not the retry pacing.
    orch = MissionOrchestrator(state_path, decomposition_retry_backoff=0.0)

    orch.tick(bridge)  # decomposer raises → PARKED (retryable)
    parked = MissionState.load(state_path).get("mission-intake")
    assert parked.status == Status.PARKED
    assert parked.metadata["parked_kind"] == PARK_KIND_DECOMPOSITION

    orch.tick(bridge)  # reconciler releases the park; decomposer succeeds

    state = MissionState.load(state_path)
    assert state.get("mission-intake").status == Status.COMPLETED
    children = [f for f in state.features if f.id != "mission-intake"]
    assert len(children) == 2
    assert all(f.status == Status.AWAITING_CLAIM for f in children)
    # Children are claimable — the exact property the round-2 finding lacked.
    ledger = Ledger(tmp_path / "ledger.json")
    assert select_for(state, ledger, "worker-1") == children[0].id


def test_select_for_never_claims_parked_or_terminal_features(tmp_path):
    """PARKED is reconciler-owned and TERMINAL is dead: neither is claimable
    by the swarm — the reconciler is the only path out of parked."""
    state = MissionState(
        mission_id="m",
        goal=GOAL,
        milestones=["m"],
        features=[
            Feature(id="p", description="x", milestone="m", status=Status.PARKED),
            Feature(id="t", description="y", milestone="m", status=Status.TERMINAL),
        ],
    )
    ledger = Ledger(tmp_path / "ledger.json")

    assert select_for(state, ledger, "worker-1") is None


# ---- terminal: permanent -------------------------------------------------------


def test_three_failed_decomposition_attempts_are_terminal(tmp_path):
    """N failed decomposition attempts (default 3) → TERMINAL, with the
    attempts recorded in retry_count. Nothing auto-transitions out: further
    runs leave it untouched."""

    def boom(goal: str, paths: list[str]) -> list[SubTask]:
        raise RuntimeError("provider outage")

    state_path = _seeded_intake_state(tmp_path)
    bridge = IntakeBridgeDispatch(_refusing_inner, decompose=boom)
    # Zero backoff: this test pins the retry-exhaustion cap, not the pacing.
    orch = MissionOrchestrator(state_path, decomposition_retry_backoff=0.0)

    orch.run(bridge, max_ticks=50)  # must drain, not spin

    intake = MissionState.load(state_path).get("mission-intake")
    assert intake.status == Status.TERMINAL
    assert intake.retry_count == 3
    assert "decomposition failed after 3 attempts" in intake.notes

    # Permanent: even a now-working decomposer never resurrects a terminal
    # feature — the reconciler skips TERMINAL entirely.
    working = IntakeBridgeDispatch(_refusing_inner, decompose=_subtasks)
    orch.run(working, max_ticks=10)
    final = MissionState.load(state_path)
    assert final.get("mission-intake").status == Status.TERMINAL
    assert len(final.features) == 1  # no children were ever inserted


def test_decomposition_retry_is_paced_not_burned_in_consecutive_ticks(tmp_path):
    """#8766 Gemini P2: a transient decomposer outage must not exhaust the
    whole retry budget in consecutive (millisecond) ticks. With the pacing
    backoff, the first failure parks the intake and an immediate drain leaves
    it PARKED with only one attempt burned — never TERMINAL."""

    def boom(goal: str, paths: list[str]) -> list[SubTask]:
        raise RuntimeError("provider outage")

    state_path = _seeded_intake_state(tmp_path)
    bridge = IntakeBridgeDispatch(_refusing_inner, decompose=boom)
    orch = MissionOrchestrator(state_path, decomposition_retry_backoff=3600.0)

    orch.run(bridge, max_ticks=50)  # drains immediately: the retry is not due yet

    intake = MissionState.load(state_path).get("mission-intake")
    assert intake.status == Status.PARKED  # not TERMINAL
    assert intake.retry_count == 1  # only the first attempt burned


def test_decomposition_retry_releases_after_backoff_elapses(tmp_path):
    """The paced park is still retryable: once the backoff window has elapsed
    (parked_at backdated), the reconciler releases it for the next bounded
    attempt — and a recovered decomposer completes the intake."""
    calls = {"n": 0}

    def recovering(goal: str, paths: list[str]) -> list[SubTask]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("provider hiccup")
        return _subtasks(goal, paths)

    state_path = _seeded_intake_state(tmp_path)
    bridge = IntakeBridgeDispatch(_refusing_inner, decompose=recovering)
    orch = MissionOrchestrator(state_path, decomposition_retry_backoff=3600.0)

    orch.tick(bridge)  # first attempt fails → PARKED, retry not yet due
    orch.tick(bridge)  # backoff not elapsed: stays PARKED, no attempt burned
    parked = MissionState.load(state_path).get("mission-intake")
    assert parked.status == Status.PARKED
    assert calls["n"] == 1

    state = MissionState.load(state_path)
    state.get("mission-intake").metadata["parked_at"] = time.time() - 7200.0
    state.save(state_path)

    orch.tick(bridge)  # backoff elapsed → released for the bounded retry

    assert MissionState.load(state_path).get("mission-intake").status == Status.COMPLETED


def test_explicit_cancel_is_terminal(tmp_path):
    state_path = _branchless_state(tmp_path)
    state = MissionState.load(state_path)

    state.cancel("f1", "operator withdrew the goal")
    state.save(state_path)

    feat = MissionState.load(state_path).get("f1")
    assert feat.status == Status.TERMINAL
    assert "TERMINAL: operator withdrew the goal" in feat.notes
    # And it stays terminal across a drain: nothing auto-transitions out.
    MissionOrchestrator(state_path).run(_refusing_inner, max_ticks=10)
    assert MissionState.load(state_path).get("f1").status == Status.TERMINAL


def test_unpark_refuses_non_parked_features(tmp_path):
    state = MissionState.load(_branchless_state(tmp_path))
    with pytest.raises(ValueError, match="cannot unpark"):
        state.unpark("f1")


# ---- fail-closed: claim-time re-verification ------------------------------------


def test_dispatch_reverifies_branch_at_claim_time_instead_of_trusting_state(tmp_path):
    """A feature promoted to PENDING on stale/lying state (park metadata gone,
    still no branch) must NOT reach the merge gate: dispatch re-verifies the
    precondition at claim time and re-parks it — fail-closed, git untouched."""
    state_path = _branchless_state(tmp_path)
    state = MissionState.load(state_path)
    feat = state.get("f1")
    feat.status = Status.PENDING  # hand-promoted; no metadata.branch exists
    state.save(state_path)
    gate = RecordingGate()

    MissionOrchestrator(state_path).run(BossLoopDispatch(gate), max_ticks=10)

    reloaded = MissionState.load(state_path).get("f1")
    assert reloaded.status == Status.PARKED  # re-parked, not dispatched
    assert gate.branch_calls == 0
    assert gate.merge_calls == []


def test_pending_work_gated_on_parked_feature_is_not_dead_ended(tmp_path):
    """A PENDING feature precondition-gated on a PARKED one can still complete
    (the reconciler may release the park), so drain leaves it PENDING."""
    state_path = tmp_path / "state.json"
    parked = Feature(
        id="child-a",
        description="waiting on a branch",
        milestone="m",
        status=Status.PARKED,
        metadata={"parked_kind": PARK_KIND_MISSING_BRANCH, "parked_reason": "no branch"},
    )
    gated = Feature(
        id="validate-a",
        description="validate the work",
        milestone="m",
        preconditions=["feature:child-a"],
        metadata={"branch": "mission/validate-a"},
    )
    MissionState(mission_id="m", goal=GOAL, milestones=["m"], features=[parked, gated]).save(
        state_path
    )

    MissionOrchestrator(state_path).run(_refusing_inner, max_ticks=10)

    state = MissionState.load(state_path)
    assert state.get("child-a").status == Status.PARKED
    assert state.get("validate-a").status == Status.PENDING  # not BLOCKED


# ---- swarm reconcile releases missing-branch parks -------------------------------


def test_ledger_reconcile_releases_missing_branch_park_when_worker_materializes(tmp_path):
    """The swarm-side reconciler path: a worker-materialized branch recorded in
    the ledger folds into metadata.branch AND releases a missing-branch park,
    so the feature becomes drivable again without operator surgery."""
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "ledger.json"
    parked = Feature(
        id="child-a",
        description="waiting on a branch",
        milestone="m",
        status=Status.PARKED,
        metadata={"parked_kind": PARK_KIND_MISSING_BRANCH, "parked_reason": "no branch"},
    )
    MissionState(mission_id="m", goal=GOAL, milestones=["m"], features=[parked]).save(state_path)
    Ledger(ledger_path).record_branch("child-a", "mission/child-a")

    assert _reconcile_locked(state_path, ledger_path) > 0

    feat = MissionState.load(state_path).get("child-a")
    assert feat.status == Status.PENDING  # parked → ready
    assert feat.metadata["branch"] == "mission/child-a"
    assert "parked_reason" not in feat.metadata
    assert "unparked" in feat.notes


def test_materialization_park_is_paced_and_reaches_blocked_at_cap(tmp_path):
    """#8766 openai P1 (repair 3): a transient git failure during branch
    materialization parks under the dedicated PACED kind — it is retried
    across real time, never constraint-parked into BLOCKED within one worker
    run — and only PERSISTENT failure reaches BLOCKED after max_retries."""
    state_path = _branchless_state(tmp_path)
    state = MissionState.load(state_path)
    state.save(state_path)

    calls = {"n": 0}

    def always_failing_materialization(feature: Feature) -> Handoff:
        calls["n"] += 1
        return Handoff(
            success=False,
            parked=True,
            parked_kind=PARK_KIND_MATERIALIZATION,
            blocked_reason="branch materialization failed: git blip",
        )

    # backoff=0 so the test exercises the retry-bound quickly; pacing itself
    # is pinned by the next test.
    orch = MissionOrchestrator(state_path, decomposition_retry_backoff=0.0)
    orch.run(always_failing_materialization, max_ticks=50)

    feat = MissionState.load(state_path).get("f1")
    assert feat.status == Status.BLOCKED  # operator-recoverable, not TERMINAL
    assert feat.retry_count == 3
    assert "branch materialization failed after 3 attempts" in feat.notes
    assert calls["n"] == 3  # bounded: one attempt per burned retry


def test_materialization_retry_is_paced_not_burned_in_consecutive_ticks(tmp_path):
    """With a real backoff, consecutive ticks must NOT burn the retry budget:
    the park stays parked until the pacing window elapses."""
    state_path = _branchless_state(tmp_path)

    def failing_materialization(feature: Feature) -> Handoff:
        return Handoff(
            success=False,
            parked=True,
            parked_kind=PARK_KIND_MATERIALIZATION,
            blocked_reason="branch materialization failed: git blip",
        )

    orch = MissionOrchestrator(state_path, decomposition_retry_backoff=3600.0)
    orch.run(failing_materialization, max_ticks=10)

    feat = MissionState.load(state_path).get("f1")
    assert feat.status == Status.PARKED  # waiting out the backoff, not BLOCKED
    assert feat.retry_count == 1  # exactly one attempt; no consecutive-tick burn
