"""Tests for the intake→decomposition bridge (#8758).

A seeded mission (``aragora mission seed --goal ...``) starts as a single
"mission-intake" feature with no ``metadata.branch``. Before the bridge, the
live dispatch parked it terminally. These tests pin the bridge contract:

* intake-shaped features are decomposed via TaskDecomposer into 1+ child
  Features born in the claimable AWAITING_CLAIM state, each carrying a
  deterministic ``metadata.branch_hint`` (never a fabricated
  ``metadata.branch`` — the merge gate rev-parses that value);
* the intake feature completes (non-terminal) with provenance notes;
* after auto-drain, the children stay claimable by ``select_for`` with
  ``crash_count == 0`` and zero manual status resets — the orchestrator
  never dispatches an AWAITING_CLAIM child, so there is no retry-counter
  burn, no BLOCKED children, and the merge gate is never invoked on a
  nonexistent ref (the round-2 quorum P1);
* a PENDING branch-less child (e.g. hand-reset state) triages back to
  AWAITING_CLAIM via ``Handoff.awaiting_claim`` — never retried to BLOCKED;
* children with a live worker-recorded ``metadata.branch`` flow through to
  the inner dispatch;
* empty decompositions mirror the goal into one child instead of parking;
* a raising decomposer parks the intake NON-terminally with a diagnostic
  (the round-2 quorum P2): a later tick retries when the decomposer
  recovers, bounded by the orchestrator's existing retry cap — and the
  tick loop never crashes;
* re-ticking after a crash never duplicates children, including when the
  decomposer returns duplicate-titled subtasks in a different order
  (child ids are content-derived, not positional);
* non-intake features pass through to the inner dispatch untouched.
"""

from __future__ import annotations

import argparse
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
from aragora.missions.intake import (
    IntakeBridgeDispatch,
    intake_bridge_enabled,
    is_intake_feature,
)
from aragora.missions.state import PARK_KIND_DECOMPOSITION
from aragora.nomic.task_decomposer import SubTask

GOAL = "Add a rate limiter to the API server"


def _intake_feature(goal: str = GOAL) -> Feature:
    return Feature(
        id="mission-intake",
        description=goal,
        milestone="mission",
        metadata={"paths": ["aragora/server"], "tracks": [], "autonomy": "auto-drain"},
    )


def _seeded_state(tmp_path: Path, goal: str = GOAL) -> Path:
    state_path = tmp_path / "state.json"
    state = MissionState(
        mission_id="mission-test",
        goal=goal,
        milestones=["mission"],
        features=[_intake_feature(goal)],
    )
    state.save(state_path)
    return state_path


def _refusing_inner(feature: Feature) -> Handoff:
    raise AssertionError(f"inner dispatch must never see feature {feature.id}")


def _two_subtasks(goal: str, paths: list[str]) -> list[SubTask]:
    return [
        SubTask(
            id="subtask_1",
            title="Server Changes",
            description="Wire the rate limiter into the server",
            file_scope=["aragora/server"],
        ),
        SubTask(
            id="subtask_2",
            title="Tests",
            description="Cover the rate limiter with tests",
            dependencies=["subtask_1"],
        ),
    ]


def _two_independent_subtasks(goal: str, paths: list[str]) -> list[SubTask]:
    return [
        SubTask(id="subtask_1", title="Server Changes", description="Wire it in"),
        SubTask(id="subtask_2", title="Tests", description="Cover it"),
    ]


class _RaisingHeadGate:
    """Faithful stand-in for LiveBossLoopGate against a nonexistent branch:
    ``head_of`` raises RuntimeError exactly like ``git rev-parse`` failing."""

    def __init__(self) -> None:
        self.head_calls = 0

    def branch_for(self, feature: Feature) -> str:
        return str(feature.metadata.get("branch") or f"mission/{feature.id}")

    def already_merged(self, branch: str) -> bool:
        return False

    def head_of(self, branch: str) -> str:
        self.head_calls += 1
        raise RuntimeError(f"fatal: unknown revision or path {branch}")

    def foreign_commits(self, branch, base, allowed_prefixes) -> list[str]:
        return []

    def tier_of(self, feature: Feature) -> int:
        return 0

    def collect_evidence(self, branch, head) -> GateVerdict:
        return GateVerdict(satisfied=True)

    def merge_head_bound(self, branch, head) -> bool:
        return False


# ---- intake detection ---------------------------------------------------------


def test_branch_backed_feature_is_not_intake():
    feat = Feature(id="a1", description="x", milestone="m", metadata={"branch": "mission/a1"})
    assert not is_intake_feature(feat)


def test_seeded_intake_feature_is_intake():
    assert is_intake_feature(_intake_feature())


def test_kind_marker_makes_any_branchless_feature_intake():
    feat = Feature(id="other-id", description="x", milestone="m", metadata={"kind": "intake"})
    assert is_intake_feature(feat)


# ---- successful decomposition -------------------------------------------------


def test_intake_decomposes_into_claimable_follow_ups():
    bridge = IntakeBridgeDispatch(_refusing_inner, decompose=_two_subtasks)

    handoff = bridge(_intake_feature())

    assert handoff.success
    assert not handoff.terminal
    assert handoff.accept_follow_ups
    assert len(handoff.follow_ups) == 2
    for child in handoff.follow_ups:
        # Born awaiting a worker: claimable by select_for, never dispatched
        # (and never retry-burned) by the orchestrator until a branch exists.
        assert child.status == Status.AWAITING_CLAIM
        assert not is_intake_feature(child)
        # Never a fabricated live branch — the merge gate rev-parses that.
        assert "branch" not in child.metadata
        assert child.metadata["branch_hint"].startswith("mission/")
        assert child.metadata["intake_parent"] == "mission-intake"
        assert child.metadata["decomposer"]
        assert isinstance(child.metadata["decomposed_at"], float)
    first, second = handoff.follow_ups
    assert second.preconditions == [f"feature:{first.id}"]
    # Subtask file scope narrows the child's path allowlist.
    assert first.metadata["paths"] == ["aragora/server"]
    assert any("decomposed" in note for note in handoff.discovered)


def test_intake_surfaces_max_children_truncation():
    many = [
        SubTask(id=f"subtask_{i}", title=f"Step {i}", description=f"Do step {i}") for i in range(5)
    ]
    bridge = IntakeBridgeDispatch(
        _refusing_inner, decompose=lambda goal, paths: many, max_children=2
    )

    handoff = bridge(_intake_feature())

    assert handoff.success
    assert len(handoff.follow_ups) == 2
    assert any("truncated from 5 to 2" in note for note in handoff.discovered)


def test_intake_fails_closed_when_truncation_removes_dependency():
    subtasks = [
        SubTask(
            id="kept",
            title="Kept",
            description="Depends on omitted work",
            dependencies=["omitted"],
        ),
        SubTask(id="omitted", title="Omitted", description="Required first"),
    ]
    bridge = IntakeBridgeDispatch(
        _refusing_inner, decompose=lambda goal, paths: subtasks, max_children=1
    )

    handoff = bridge(_intake_feature())

    assert handoff.success is False
    assert handoff.terminal is True
    assert "omitted" in handoff.blocked_reason
    assert handoff.follow_ups == []


def test_tick_converts_intake_into_children_instead_of_parking(tmp_path):
    state_path = _seeded_state(tmp_path)
    bridge = IntakeBridgeDispatch(_refusing_inner, decompose=_two_subtasks)

    assert MissionOrchestrator(state_path).tick(bridge) is True

    state = MissionState.load(state_path)
    intake = state.get("mission-intake")
    assert intake.status == Status.COMPLETED  # non-terminal: never BLOCKED
    assert "decomposed" in intake.notes
    children = [f for f in state.features if f.id != "mission-intake"]
    assert len(children) == 2
    assert all(f.status == Status.AWAITING_CLAIM for f in children)
    assert all(str(f.metadata["branch_hint"]).startswith("mission/") for f in children)


def test_children_are_claimable_by_existing_lease_machinery(tmp_path):
    state_path = _seeded_state(tmp_path)
    bridge = IntakeBridgeDispatch(_refusing_inner, decompose=_two_subtasks)
    MissionOrchestrator(state_path).tick(bridge)

    state = MissionState.load(state_path)
    ledger = Ledger(tmp_path / "ledger.json")
    claimed = select_for(state, ledger, "worker-1")

    children = [f.id for f in state.features if f.id != "mission-intake"]
    assert claimed == children[0]
    # Second worker skips the claimed unit; the dependent child is gated.
    assert select_for(state, ledger, "worker-2") is None


# ---- post-decomposition ticks (the crash-loop regression) ----------------------


def test_branchless_child_parks_gracefully_without_reaching_inner():
    bridge = IntakeBridgeDispatch(_refusing_inner, decompose=_two_subtasks)
    child = Feature(
        id="mission-intake-tests",
        description="Cover it",
        milestone="mission",
        metadata={
            "intake_parent": "mission-intake",
            "branch_hint": "mission/mission-intake-tests",
        },
    )

    handoff = bridge(child)

    assert not handoff.success
    assert not handoff.terminal  # a worker attaching a branch can self-heal
    # The claimable-wait disposition: triage moves the child to AWAITING_CLAIM
    # instead of burning retry_count toward BLOCKED (the round-2 quorum P1).
    assert handoff.awaiting_claim
    assert "awaiting worker claim/branch creation" in (handoff.blocked_reason or "")
    assert "mission/mission-intake-tests" in (handoff.blocked_reason or "")


def test_follow_up_ticks_never_crash_loop_on_nonexistent_branches(tmp_path):
    """The quorum-review regression: after decomposition, the next ticks must
    NOT rev-parse nonexistent branches into a crash/retry loop mislabeled as a
    poison dispatch. Runs the real BossLoopDispatch chain with a gate whose
    head_of raises exactly like live git."""
    state_path = _seeded_state(tmp_path)
    gate = _RaisingHeadGate()
    bridge = IntakeBridgeDispatch(BossLoopDispatch(gate), decompose=_two_independent_subtasks)

    MissionOrchestrator(state_path).run(bridge, max_ticks=50)  # must drain, never raise

    state = MissionState.load(state_path)
    assert state.get("mission-intake").status == Status.COMPLETED
    children = [f for f in state.features if f.id != "mission-intake"]
    assert len(children) == 2
    for child in children:
        # Round-2 P1: awaiting a worker, NOT retried-to-BLOCKED.
        assert child.status == Status.AWAITING_CLAIM
        assert "poison" not in child.notes
        assert "crash" not in child.notes.lower()
        assert child.crash_count == 0  # never dispatched, never raised
        assert child.retry_count == 0  # no retry-counter burn
    assert gate.head_calls == 0  # live git never touched for branch-less children


def test_auto_drain_leaves_children_claimable_by_select_for(tmp_path):
    """Round-2 quorum P1 acceptance: fresh seed → auto-drain completes →
    the decomposed children are claimable by the select_for/swarm machinery
    with crash_count 0, zero manual status resets, and no BLOCKED children."""
    state_path = _seeded_state(tmp_path)
    gate = _RaisingHeadGate()
    bridge = IntakeBridgeDispatch(BossLoopDispatch(gate), decompose=_two_subtasks)

    MissionOrchestrator(state_path).run(bridge, max_ticks=50)

    state = MissionState.load(state_path)
    assert state.get("mission-intake").status == Status.COMPLETED
    assert not any(f.status == Status.BLOCKED for f in state.features)
    children = [f for f in state.features if f.id != "mission-intake"]
    assert children and all(f.status == Status.AWAITING_CLAIM for f in children)
    assert all(f.crash_count == 0 and f.retry_count == 0 for f in children)

    # Zero manual status resets: the worker self-heal path claims as-is.
    ledger = Ledger(tmp_path / "worker-ledger.json")
    assert select_for(state, ledger, "worker-1") == children[0].id
    # The dependent sibling stays precondition-gated until the first completes.
    assert select_for(state, ledger, "worker-2") is None


def test_child_with_live_branch_flows_through_to_inner_dispatch():
    seen: list[str] = []

    def inner(feature: Feature) -> Handoff:
        seen.append(feature.id)
        return Handoff(success=True)

    bridge = IntakeBridgeDispatch(inner, decompose=_two_subtasks)
    child = Feature(
        id="mission-intake-tests",
        description="Cover it",
        milestone="mission",
        metadata={"intake_parent": "mission-intake", "branch": "mission/mission-intake-tests"},
    )

    assert bridge(child).success
    assert seen == ["mission-intake-tests"]


def test_pending_branchless_child_triages_to_awaiting_claim_without_retry_burn(tmp_path):
    """Defense in depth: a branchless child that is somehow PENDING (hand-reset
    state, pre-fix state file) is moved back to AWAITING_CLAIM by one dispatch —
    no retry_count burn, no BLOCKED (the round-2 quorum P1 failure path)."""
    state_path = tmp_path / "state.json"
    child = Feature(
        id="mission-intake-tests",
        description="Cover it",
        milestone="mission",
        metadata={
            "intake_parent": "mission-intake",
            "branch_hint": "mission/mission-intake-tests",
        },
    )
    MissionState(
        mission_id="mission-test", goal=GOAL, milestones=["mission"], features=[child]
    ).save(state_path)
    bridge = IntakeBridgeDispatch(_refusing_inner, decompose=_two_subtasks)

    MissionOrchestrator(state_path).run(bridge, max_ticks=10)  # must drain

    state = MissionState.load(state_path)
    reloaded = state.get("mission-intake-tests")
    assert reloaded.status == Status.AWAITING_CLAIM
    assert reloaded.retry_count == 0
    assert reloaded.crash_count == 0
    assert "awaiting worker claim/branch creation" in reloaded.notes


def test_drain_leaves_pending_work_gated_on_awaiting_claim_unblocked(tmp_path):
    """A PENDING feature precondition-gated on an AWAITING_CLAIM child is still
    reachable (a worker can complete the child), so drain must leave it PENDING
    instead of blocking it as unrunnable."""
    state_path = tmp_path / "state.json"
    awaiting = Feature(
        id="child-a",
        description="do the work",
        milestone="mission",
        status=Status.AWAITING_CLAIM,
        metadata={"intake_parent": "mission-intake", "branch_hint": "mission/child-a"},
    )
    gated = Feature(
        id="validate-a",
        description="validate the work",
        milestone="mission",
        preconditions=["feature:child-a"],
        metadata={"branch": "mission/validate-a"},
    )
    MissionState(
        mission_id="mission-test", goal=GOAL, milestones=["mission"], features=[awaiting, gated]
    ).save(state_path)

    MissionOrchestrator(state_path).run(_refusing_inner, max_ticks=10)  # drains untouched

    state = MissionState.load(state_path)
    assert state.get("child-a").status == Status.AWAITING_CLAIM
    assert state.get("validate-a").status == Status.PENDING  # not BLOCKED


def test_drain_still_blocks_true_precondition_deadlocks(tmp_path):
    """The awaiting-claim reachability carve-out must not weaken deadlock
    detection: a precondition cycle with no workable entry is still blocked."""
    state_path = tmp_path / "state.json"
    a = Feature(id="a", description="x", milestone="m", preconditions=["feature:b"])
    b = Feature(id="b", description="y", milestone="m", preconditions=["feature:a"])
    MissionState(mission_id="m", goal=GOAL, milestones=["m"], features=[a, b]).save(state_path)

    MissionOrchestrator(state_path).run(_refusing_inner, max_ticks=10)

    state = MissionState.load(state_path)
    assert state.get("a").status == Status.BLOCKED
    assert state.get("b").status == Status.BLOCKED


# ---- empty decomposition ------------------------------------------------------


def test_empty_decomposition_falls_back_to_single_mirrored_child():
    bridge = IntakeBridgeDispatch(_refusing_inner, decompose=lambda goal, paths: [])

    handoff = bridge(_intake_feature("Bump the httpx pin"))

    assert handoff.success
    assert len(handoff.follow_ups) == 1
    child = handoff.follow_ups[0]
    assert "Bump the httpx pin" in child.description
    assert child.metadata["branch_hint"].startswith("mission/")
    assert "branch" not in child.metadata
    assert child.metadata["intake_parent"] == "mission-intake"


# ---- failure paths ------------------------------------------------------------


def test_decomposer_exception_parks_non_terminally_with_diagnostic(tmp_path):
    """Round-2 quorum P2 + the #8758 design decision: a raising decomposer is
    a transient provider failure — a retryable, reconciler-owned PARK with the
    transition recorded on the feature, never terminal on the first exception."""

    def boom(goal: str, paths: list[str]) -> list[SubTask]:
        raise RuntimeError("no decomposition today")

    state_path = _seeded_state(tmp_path)
    bridge = IntakeBridgeDispatch(_refusing_inner, decompose=boom)

    assert MissionOrchestrator(state_path).tick(bridge) is True  # no raise

    state = MissionState.load(state_path)
    intake = state.get("mission-intake")
    assert intake.status == Status.PARKED  # retryable, NOT blocked/terminal
    assert intake.retry_count == 1  # bounded: TERMINAL after max_retries attempts
    # The transition is recorded on the feature (#8758 design decision).
    assert "intake decomposition failed" in intake.metadata["parked_reason"]
    assert isinstance(intake.metadata["parked_at"], float)
    assert intake.metadata["parked_kind"] == PARK_KIND_DECOMPOSITION
    assert "raised" in intake.notes  # diagnostic survives for the operator
    assert len(state.features) == 1  # no half-inserted children


def test_transient_decomposer_failure_recovers_on_next_tick(tmp_path):
    """Round-2 quorum P2 acceptance: decomposer raises on tick 1 and succeeds
    on tick 2 → the intake decomposes on tick 2."""
    calls = {"n": 0}

    def flaky(goal: str, paths: list[str]) -> list[SubTask]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("provider hiccup")
        return _two_subtasks(goal, paths)

    state_path = _seeded_state(tmp_path)
    bridge = IntakeBridgeDispatch(_refusing_inner, decompose=flaky)
    # Zero backoff: this test pins the recovery semantics, not the retry pacing.
    orch = MissionOrchestrator(state_path, decomposition_retry_backoff=0.0)

    orch.tick(bridge)  # tick 1: decomposer raises → PARKED (retryable)
    orch.tick(bridge)  # tick 2: reconciler releases the park → decomposes

    state = MissionState.load(state_path)
    assert state.get("mission-intake").status == Status.COMPLETED
    children = [f for f in state.features if f.id != "mission-intake"]
    assert len(children) == 2
    assert all(f.status == Status.AWAITING_CLAIM for f in children)


def test_persistently_raising_decomposer_is_bounded_not_infinite(tmp_path):
    def boom(goal: str, paths: list[str]) -> list[SubTask]:
        raise RuntimeError("provider outage")

    state_path = _seeded_state(tmp_path)
    bridge = IntakeBridgeDispatch(_refusing_inner, decompose=boom)

    # Zero backoff: this test pins the retry-exhaustion cap, not the pacing.
    orch = MissionOrchestrator(state_path, decomposition_retry_backoff=0.0)
    orch.run(bridge, max_ticks=50)  # must drain

    state = MissionState.load(state_path)
    intake = state.get("mission-intake")
    # #8758 design decision: N failed decomposition attempts (default 3) is a
    # PERMANENT failure → TERMINAL, the state nothing auto-transitions out of.
    assert intake.status == Status.TERMINAL
    assert intake.retry_count == 3
    assert "decomposition failed after 3 attempts" in intake.notes
    assert "provider outage" in intake.notes


def test_blank_goal_parks_terminal():
    bridge = IntakeBridgeDispatch(_refusing_inner, decompose=_two_subtasks)

    handoff = bridge(_intake_feature("   "))

    assert not handoff.success
    assert handoff.terminal
    assert "goal" in (handoff.blocked_reason or "")
    assert handoff.follow_ups == []


# ---- idempotency --------------------------------------------------------------


def test_crash_retick_does_not_duplicate_children(tmp_path):
    state_path = _seeded_state(tmp_path)
    bridge = IntakeBridgeDispatch(_refusing_inner, decompose=_two_subtasks)
    orch = MissionOrchestrator(state_path)
    orch.tick(bridge)

    # Simulate a crash after dispatch but before triage persisted completion:
    # the intake is re-picked and re-decomposed on the next tick.
    state = MissionState.load(state_path)
    state.get("mission-intake").status = Status.PENDING
    state.save(state_path)
    orch.tick(bridge)

    state = MissionState.load(state_path)
    ids = [f.id for f in state.features]
    assert len(ids) == len(set(ids)) == 3  # intake + 2 children, no duplicates
    assert state.get("mission-intake").status == Status.COMPLETED


def test_duplicate_title_child_ids_are_order_independent():
    """Duplicate-slug subtasks get content-derived (not positional) suffixes:
    a retry returning the same subtasks reordered — with freshly assigned
    positional subtask ids — converges on the identical child-id set."""
    first_order = [
        SubTask(id="subtask_1", title="Fix Config", description="fix config in module a"),
        SubTask(id="subtask_2", title="Fix Config", description="fix config in module b"),
    ]
    reordered = [
        SubTask(id="subtask_1", title="Fix Config", description="fix config in module b"),
        SubTask(id="subtask_2", title="Fix Config", description="fix config in module a"),
    ]
    bridge_a = IntakeBridgeDispatch(_refusing_inner, decompose=lambda g, p: first_order)
    bridge_b = IntakeBridgeDispatch(_refusing_inner, decompose=lambda g, p: reordered)

    ids_a = {c.id for c in bridge_a(_intake_feature()).follow_ups}
    ids_b = {c.id for c in bridge_b(_intake_feature()).follow_ups}

    assert len(ids_a) == 2
    assert ids_a == ids_b


def test_reordered_duplicate_titles_do_not_duplicate_children_on_retick(tmp_path):
    calls = {"n": 0}

    def flipping_decompose(goal: str, paths: list[str]) -> list[SubTask]:
        calls["n"] += 1
        subtasks = [
            SubTask(id="subtask_1", title="Fix Config", description="fix config in module a"),
            SubTask(id="subtask_2", title="Fix Config", description="fix config in module b"),
        ]
        return subtasks if calls["n"] == 1 else list(reversed(subtasks))

    state_path = _seeded_state(tmp_path)
    bridge = IntakeBridgeDispatch(_refusing_inner, decompose=flipping_decompose)
    orch = MissionOrchestrator(state_path)
    orch.tick(bridge)

    state = MissionState.load(state_path)
    state.get("mission-intake").status = Status.PENDING
    state.save(state_path)
    orch.tick(bridge)  # crash-retry sees the same subtasks, reordered

    state = MissionState.load(state_path)
    ids = [f.id for f in state.features]
    assert len(ids) == len(set(ids)) == 3  # intake + 2 children, no duplicates


def test_exact_duplicate_subtasks_collapse_to_one_child():
    duplicates = [
        SubTask(id="subtask_1", title="Same Work", description="identical"),
        SubTask(id="subtask_2", title="Same Work", description="identical"),
    ]
    bridge = IntakeBridgeDispatch(_refusing_inner, decompose=lambda g, p: duplicates)

    handoff = bridge(_intake_feature())

    assert handoff.success
    assert len(handoff.follow_ups) == 1


# ---- pass-through -------------------------------------------------------------


def test_non_intake_features_pass_through_to_inner_dispatch():
    seen: list[str] = []

    def inner(feature: Feature) -> Handoff:
        seen.append(feature.id)
        return Handoff(success=True)

    bridge = IntakeBridgeDispatch(inner, decompose=_two_subtasks)
    feat = Feature(id="a1", description="x", milestone="m", metadata={"branch": "mission/a1"})

    assert bridge(feat).success
    assert seen == ["a1"]


# ---- default decomposer (heuristic, no API keys) ------------------------------


def test_default_decomposer_requires_no_api_keys(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "ARAGORA_USE_SECRETS_MANAGER"):
        monkeypatch.delenv(var, raising=False)
    bridge = IntakeBridgeDispatch(_refusing_inner)

    handoff = bridge(
        _intake_feature("Harden the api server and add tests for the storage handlers")
    )

    assert handoff.success
    assert len(handoff.follow_ups) >= 1
    assert all(c.metadata["branch_hint"].startswith("mission/") for c in handoff.follow_ups)
    assert all("branch" not in c.metadata for c in handoff.follow_ups)


# ---- feature flag + CLI wiring -------------------------------------------------


def test_intake_bridge_enabled_env_kill_switch(monkeypatch):
    monkeypatch.delenv("ARAGORA_DISABLE_MISSION_INTAKE_BRIDGE", raising=False)
    assert intake_bridge_enabled()
    monkeypatch.setenv("ARAGORA_DISABLE_MISSION_INTAKE_BRIDGE", "1")
    assert not intake_bridge_enabled()
    monkeypatch.setenv("ARAGORA_DISABLE_MISSION_INTAKE_BRIDGE", "0")
    assert intake_bridge_enabled()


@pytest.mark.parametrize("disabled", [False, True])
def test_auto_drain_dispatch_wires_intake_bridge_by_default(tmp_path, monkeypatch, disabled):
    from aragora.cli.commands.mission import _dispatch_for

    if disabled:
        monkeypatch.setenv("ARAGORA_DISABLE_MISSION_INTAKE_BRIDGE", "1")
    else:
        monkeypatch.delenv("ARAGORA_DISABLE_MISSION_INTAKE_BRIDGE", raising=False)
    args = argparse.Namespace(
        autonomy="auto-drain",
        repo_root=str(tmp_path),
        auto_settle_max_tier=2,
        operator_tier=3,
    )

    dispatch = _dispatch_for(args, state_path=None)

    if disabled:
        assert isinstance(dispatch, BossLoopDispatch)
    else:
        assert isinstance(dispatch, IntakeBridgeDispatch)
