"""Tests for worker branch materialization (#8773) — the last link of seed→PR.

PR #8766 left decomposed intake children in the claimable ``AWAITING_CLAIM``
state carrying only ``metadata.branch_hint``: real work, claimable via
``select_for``, but not *executable* — nothing turned the hint into a live
branch, so a claimed child either parked at BossLoopDispatch for missing
``metadata.branch`` or burned retries on the bridge's awaiting_claim handoff.

These tests pin the materialization contract:

* claiming an AWAITING_CLAIM child creates the real branch from origin/main
  using ``branch_hint``, sets ``metadata.branch``, and dispatch proceeds
  (zero manual steps);
* ``metadata.branch`` is never fabricated — it is only set after the ref
  actually exists (the #8766 round-1 lesson), and the ledger records the
  branch only after creation succeeds, so reconcile can never fold a
  nonexistent ref into state;
* a colliding hint (foreign branch with unique commits) gets a deterministic
  content-derived suffix; a colliding hint parked exactly at base (our own
  crash orphan) is adopted, so crash-retries converge instead of spawning
  branch litter;
* a git failure returns the child to AWAITING_CLAIM with a diagnostic note —
  never BLOCKED/terminal on first failure — and repeated failures are bounded
  by the existing park accounting;
* a worker with no git capability (no materializer) yields the unit back with
  ZERO retry burn, preserving #8766's no-burn property;
* reconcile folds the worker-recorded branch into ``metadata.branch`` and
  transitions AWAITING_CLAIM -> PENDING per the existing state machine;
* full chain: seed -> decompose -> claim -> executable feature (composes the
  intake bridge, the real BossLoopDispatch, and the swarm worker loop).
"""

from __future__ import annotations

import subprocess
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
from aragora.missions.swarm import (
    BranchMaterializationError,
    BranchMaterializer,
    reconcile_from_ledger,
    run_worker,
)
from aragora.nomic.task_decomposer import SubTask

GOAL = "Add a rate limiter to the API server"
BASE_HEAD = "aaaa1111"


class FakeGit:
    """Mock git subprocess runner (``live_gate.Runner`` signature).

    Understands exactly the calls the materializer makes: ``rev-parse`` to
    check refs and ``branch <name> <start>`` to create one. ``fail_creates``
    simulates a git error on branch creation.
    """

    def __init__(
        self,
        *,
        branches: dict[str, str] | None = None,
        base_head: str = BASE_HEAD,
        fail_creates: bool = False,
    ) -> None:
        self.branches = dict(branches or {})
        self.base_head = base_head
        self.fail_creates = fail_creates
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], cwd: Path) -> str:
        self.calls.append(list(cmd))
        if cmd[:2] == ["git", "rev-parse"]:
            name = cmd[-1]
            if name == "origin/main":
                return f"{self.base_head}\n"
            if name in self.branches:
                return f"{self.branches[name]}\n"
            raise RuntimeError(f"fatal: unknown revision or path {name}")
        if cmd[:3] == ["git", "check-ref-format", "--branch"]:
            name = cmd[3]
            if name.startswith("-") or ".." in name or name.endswith(".lock"):
                raise RuntimeError(f"fatal: {name!r} is not a valid branch name")
            return f"{name}\n"
        if cmd[:3] == ["git", "branch", "--"]:
            name, start = cmd[3], cmd[4]
            if self.fail_creates:
                raise RuntimeError("fatal: cannot lock ref (simulated git failure)")
            if start != "origin/main":
                raise RuntimeError(f"unexpected start point {start}")
            if name in self.branches:
                raise RuntimeError(f"fatal: branch {name} already exists")
            self.branches[name] = self.base_head
            return ""
        raise RuntimeError(f"unexpected git call: {cmd}")

    def created_branches(self) -> list[str]:
        return [c[3] for c in self.calls if c[:3] == ["git", "branch", "--"]]


def _materializer(git: FakeGit) -> BranchMaterializer:
    return BranchMaterializer("/repo", runner=git)


def _child(feature_id: str = "mission-intake-tests", **metadata) -> Feature:
    meta = {
        "intake_parent": "mission-intake",
        "branch_hint": f"mission/{feature_id}",
        **metadata,
    }
    return Feature(
        id=feature_id,
        description="Cover it",
        milestone="mission",
        status=Status.AWAITING_CLAIM,
        metadata=meta,
    )


def _child_state(tmp_path: Path, *features: Feature) -> tuple[Path, Path]:
    state_path = tmp_path / "state.json"
    MissionState(
        mission_id="mission-test",
        goal=GOAL,
        milestones=["mission"],
        features=list(features) or [_child()],
    ).save(state_path)
    return state_path, tmp_path / "ledger.json"


# ---- BranchMaterializer unit behavior -----------------------------------------


def test_materialize_creates_branch_from_hint_off_base(tmp_path):
    git = FakeGit()
    ledger = Ledger(tmp_path / "ledger.json")
    child = _child()

    branch = _materializer(git)(child, ledger)

    assert branch == "mission/mission-intake-tests"
    assert git.created_branches() == ["mission/mission-intake-tests"]
    assert git.branches[branch] == BASE_HEAD  # created FROM origin/main
    # Recorded durably only after the ref is real.
    assert ledger.materialized_branch(child.id) == branch


def test_materialize_hint_collision_gets_deterministic_suffix(tmp_path):
    # The hint name is taken by a diverged (foreign) branch.
    git = FakeGit(branches={"mission/mission-intake-tests": "ffff9999"})
    ledger = Ledger(tmp_path / "ledger.json")
    child = _child()

    first = _materializer(git)(child, ledger)

    assert first != "mission/mission-intake-tests"
    assert first.startswith("mission/mission-intake-tests-")
    # Deterministic: a fresh materializer over a fresh ledger converges on the
    # same suffixed name (content-derived, never positional/random).
    git2 = FakeGit(branches={"mission/mission-intake-tests": "ffff9999"})
    second = _materializer(git2)(_child(), Ledger(tmp_path / "other-ledger.json"))
    assert second == first


def test_materialize_does_not_adopt_plain_hint_at_base(tmp_path):
    # #8766 claude P3: a plain-hint-named branch at base may be a FOREIGN
    # actor's fresh branch (every new branch starts at base) — adopting it
    # would silently hijack their branch. The materializer moves to its
    # deterministic hash-suffixed namespace instead.
    git = FakeGit(branches={"mission/mission-intake-tests": BASE_HEAD})
    ledger = Ledger(tmp_path / "ledger.json")

    branch = _materializer(git)(_child(), ledger)

    assert branch != "mission/mission-intake-tests"
    assert branch.startswith("mission/mission-intake-tests-")
    assert ledger.materialized_branch("mission-intake-tests") == branch


def test_materialize_adopts_suffixed_crash_orphan_at_base(tmp_path):
    # The suffixed ref exists at base: only a prior attempt of OURS generates
    # that hash-suffixed name (created between _create_branch and
    # record_branch) — adopt it, no branch litter.
    import hashlib

    hint = "mission/mission-intake-tests"
    suffixed = f"{hint}-{hashlib.sha256(hint.encode()).hexdigest()[:8]}"
    git = FakeGit(branches={hint: "f" * 40, suffixed: BASE_HEAD})
    ledger = Ledger(tmp_path / "ledger.json")

    branch = _materializer(git)(_child(), ledger)

    assert branch == suffixed
    assert git.created_branches() == []  # adopted, not re-created


def test_materialize_is_idempotent_via_ledger_record(tmp_path):
    git = FakeGit()
    ledger = Ledger(tmp_path / "ledger.json")
    child = _child()
    materializer = _materializer(git)

    first = materializer(child, ledger)
    second = materializer(_child(), ledger)  # crash-retry: fresh Feature, same ledger

    assert first == second
    assert git.created_branches() == [first]  # created exactly once


def test_materialize_recreates_recorded_branch_if_ref_was_deleted(tmp_path):
    git = FakeGit()
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.record_branch("mission-intake-tests", "mission/mission-intake-tests")

    branch = _materializer(git)(_child(), ledger)

    assert branch == "mission/mission-intake-tests"
    assert git.created_branches() == [branch]


def test_materialize_reuses_preexisting_valid_metadata_branch(tmp_path):
    """Crash-recovery reuse (#8766 Gemini P2): a feature that already carries a
    valid metadata.branch (e.g. the ledger was pruned/cleared after a prior
    materialization) adopts that branch — never shadowed by a fresh branch
    derived from the hint."""
    git = FakeGit(branches={"mission/prior": "bbbb2222"})
    ledger = Ledger(tmp_path / "ledger.json")  # pruned: no branch record
    child = _child(branch="mission/prior")

    branch = _materializer(git)(child, ledger)

    assert branch == "mission/prior"
    assert git.created_branches() == []  # adopted, not re-created
    # Re-recorded so later crash-retries adopt the same branch.
    assert ledger.materialized_branch(child.id) == "mission/prior"


def test_materialize_dead_metadata_branch_falls_through_to_hint(tmp_path):
    """A pre-existing metadata.branch whose ref no longer exists is NOT reused
    blindly: materialization falls through to the hint, exactly as before."""
    git = FakeGit()
    ledger = Ledger(tmp_path / "ledger.json")
    child = _child(branch="mission/vanished")  # ref does not exist

    branch = _materializer(git)(child, ledger)

    assert branch == "mission/mission-intake-tests"
    assert git.created_branches() == ["mission/mission-intake-tests"]
    assert ledger.materialized_branch(child.id) == branch


def test_materialize_ledger_record_wins_over_metadata_branch(tmp_path):
    """The ledger record stays the durable claim-time truth: when both exist,
    the recorded branch is adopted over a hand-attached metadata.branch."""
    git = FakeGit(branches={"mission/recorded": BASE_HEAD, "mission/hand-attached": "cccc3333"})
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.record_branch("mission-intake-tests", "mission/recorded")
    child = _child(branch="mission/hand-attached")

    branch = _materializer(git)(child, ledger)

    assert branch == "mission/recorded"
    assert git.created_branches() == []


def test_materialize_git_failure_raises_and_records_nothing(tmp_path):
    git = FakeGit(fail_creates=True)
    ledger = Ledger(tmp_path / "ledger.json")

    with pytest.raises(BranchMaterializationError):
        _materializer(git)(_child(), ledger)

    # Never fabricate: no ledger record without a real ref.
    assert ledger.materialized_branch("mission-intake-tests") is None


def test_materialize_rejects_invalid_branch_hint_before_create(tmp_path):
    git = FakeGit()
    ledger = Ledger(tmp_path / "ledger.json")

    with pytest.raises(BranchMaterializationError):
        _materializer(git)(_child(branch_hint="-bad"), ledger)

    assert git.created_branches() == []
    assert ledger.materialized_branch("mission-intake-tests") is None


def test_materialize_both_names_taken_with_foreign_commits_fails_closed(tmp_path):
    hint = "mission/mission-intake-tests"
    git = FakeGit(branches={hint: "ffff9999"})
    ledger = Ledger(tmp_path / "ledger.json")
    materializer = _materializer(git)
    suffixed = materializer._suffixed(hint)
    git.branches[suffixed] = "eeee8888"

    with pytest.raises(BranchMaterializationError):
        materializer(_child(), ledger)


# ---- ledger branch record ------------------------------------------------------


def test_ledger_branch_record_roundtrip_persists(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    assert ledger.materialized_branch("u1") is None
    ledger.record_branch("u1", "mission/u1")
    # Fresh instance reads the same file: durable, not in-memory.
    reloaded = Ledger(tmp_path / "ledger.json")
    assert reloaded.materialized_branch("u1") == "mission/u1"
    assert reloaded.materialized_branches() == {"u1": "mission/u1"}


# ---- worker claim path (run_worker) ---------------------------------------------


def test_claimed_child_gets_branch_and_becomes_dispatchable(tmp_path):
    """The headline acceptance: claim -> real branch from hint ->
    metadata.branch set -> dispatch proceeds with zero manual steps."""
    state_path, ledger_path = _child_state(tmp_path)
    git = FakeGit()
    seen: list[Feature] = []

    def dispatch(feature: Feature) -> Handoff:
        seen.append(feature)
        return Handoff(success=True)

    res = run_worker(
        state_path,
        ledger_path,
        "w1",
        dispatch,
        materialize=_materializer(git),
    )

    assert res.done == ["mission-intake-tests"]
    assert len(seen) == 1
    assert seen[0].metadata["branch"] == "mission/mission-intake-tests"
    assert git.created_branches() == ["mission/mission-intake-tests"]


def test_git_failure_returns_child_to_awaiting_claim_with_note(tmp_path):
    state_path, ledger_path = _child_state(tmp_path)
    git = FakeGit(fail_creates=True)

    def refusing(feature: Feature) -> Handoff:
        raise AssertionError("dispatch must not run when materialization failed")

    res = run_worker(
        state_path,
        ledger_path,
        "w1",
        refusing,
        materialize=_materializer(git),
        park_threshold=5,
        max_units=1,
    )

    assert res.done == []
    assert res.blocked == ["mission-intake-tests"]
    # Repair 3 (#8766 openai P1): a git failure parks IMMEDIATELY under the
    # dedicated paced kind — it must never age through the generic
    # park_threshold accounting into a constraint park within one run.
    assert res.parked == ["mission-intake-tests"]
    ledger = Ledger(ledger_path)
    assert "mission-intake-tests" not in ledger.done_units()

    reconcile_from_ledger(state_path, ledger_path)
    child = MissionState.load(state_path).get("mission-intake-tests")
    assert child.status == Status.PARKED  # paced park — never BLOCKED on a git blip
    assert child.metadata["parked_kind"] == "branch-materialization-failed"
    assert "branch materialization" in child.notes


@pytest.mark.parametrize(
    "runner_error",
    [
        OSError("git executable unavailable"),
        subprocess.CalledProcessError(1, ["git", "rev-parse"]),
    ],
    ids=["os-error", "called-process-error"],
)
def test_runner_process_failure_returns_child_to_awaiting_claim(tmp_path, runner_error):
    state_path, ledger_path = _child_state(tmp_path)

    def failing_runner(cmd: list[str], cwd: Path) -> str:
        raise runner_error

    def refusing(feature: Feature) -> Handoff:
        raise AssertionError("dispatch must not run when materialization failed")

    res = run_worker(
        state_path,
        ledger_path,
        "w1",
        refusing,
        materialize=BranchMaterializer(tmp_path, runner=failing_runner),
        park_threshold=5,
        max_units=1,
    )

    assert res.blocked == ["mission-intake-tests"]
    assert res.done == []
    assert res.parked == ["mission-intake-tests"]  # paced park, repair 3

    reconcile_from_ledger(state_path, ledger_path)
    child = MissionState.load(state_path).get("mission-intake-tests")
    assert child.status == Status.PARKED
    assert child.metadata["parked_kind"] == "branch-materialization-failed"
    assert "branch materialization for mission-intake-tests failed" in child.notes


def test_git_failure_parks_once_never_reclaimed_same_run(tmp_path):
    """Repair 3 (#8766 openai P1): with park_threshold=2 the OLD contract let
    the same worker immediately reclaim the unit and constraint-park it in one
    run (reconcile then BLOCKED it). The park now happens on the FIRST failure
    under the paced kind, so the unit is attempted exactly once per run and
    persistence is bounded by the orchestrator's retry_count -> BLOCKED cap."""
    state_path, ledger_path = _child_state(tmp_path)
    git = FakeGit(fail_creates=True)

    def refusing(feature: Feature) -> Handoff:
        raise AssertionError("dispatch must not run when materialization failed")

    res = run_worker(
        state_path,
        ledger_path,
        "w1",
        refusing,
        materialize=_materializer(git),
        park_threshold=2,
    )

    assert res.parked == ["mission-intake-tests"]
    assert res.blocked.count("mission-intake-tests") == 1  # one attempt, one park
    reconcile_from_ledger(state_path, ledger_path)
    child = MissionState.load(state_path).get("mission-intake-tests")
    assert child.status == Status.PARKED
    assert child.metadata["parked_kind"] == "branch-materialization-failed"


def test_retryable_parked_handoff_parks_without_repeated_attempts(tmp_path):
    state_path, ledger_path = _child_state(
        tmp_path, Feature(id="plain", description="x", milestone="m")
    )

    def dispatch(feature: Feature) -> Handoff:
        return Handoff(
            success=False,
            parked=True,
            parked_kind="missing-branch",
            blocked_reason="missing live branch",
            discovered=["waiting for branch"],
        )

    res = run_worker(state_path, ledger_path, "w1", dispatch, park_threshold=5)

    assert res.parked == ["plain"]
    assert res.blocked == ["plain"]
    assert Ledger(ledger_path).attempts("feature:plain") == 1
    reconcile_from_ledger(state_path, ledger_path)
    reloaded = MissionState.load(state_path).get("plain")
    assert reloaded.status == Status.PARKED
    assert reloaded.metadata["parked_kind"] == "missing-branch"
    assert "missing-branch" in reloaded.notes


def test_worker_without_materializer_yields_unit_back_with_zero_retry_burn(tmp_path):
    """#8766's property, preserved at the claim seam: a worker that cannot do
    git work releases the child untouched — no attempts, no park, no BLOCKED —
    and the run still terminates."""
    state_path, ledger_path = _child_state(tmp_path)

    def refusing(feature: Feature) -> Handoff:
        raise AssertionError("dispatch must never see a branch-less child")

    res = run_worker(state_path, ledger_path, "w1", refusing)

    assert res.awaiting_claim == ["mission-intake-tests"]
    assert res.done == [] and res.blocked == [] and res.parked == []
    ledger = Ledger(ledger_path)
    assert ledger.attempts("feature:mission-intake-tests") == 0  # zero retry burn
    assert not ledger.is_excluded("feature:mission-intake-tests")
    assert ledger.active_claims() == {}  # lease released for a capable worker
    reconcile_from_ledger(state_path, ledger_path)
    child = MissionState.load(state_path).get("mission-intake-tests")
    assert child.status == Status.AWAITING_CLAIM


def test_awaiting_claim_handoff_from_dispatch_burns_no_retries(tmp_path):
    """Defense in depth: if an (unmaterialized) child still reaches a bridge
    that answers awaiting_claim, the swarm yields it back instead of counting
    the non-failure toward a park."""
    state_path, ledger_path = _child_state(tmp_path)

    def bridge_like(feature: Feature) -> Handoff:
        return Handoff(success=False, awaiting_claim=True, blocked_reason="awaiting worker claim")

    # A materializer is present but the unit carries no hint/intake marker, so
    # materialization is skipped and the dispatch's awaiting_claim wins.
    plain = Feature(id="plain", description="x", milestone="mission")
    state_path2 = tmp_path / "state2.json"
    MissionState(mission_id="m2", goal=GOAL, milestones=["mission"], features=[plain]).save(
        state_path2
    )

    res = run_worker(state_path2, tmp_path / "ledger2.json", "w1", bridge_like)

    assert res.awaiting_claim == ["plain"]
    assert res.blocked == [] and res.parked == []
    assert Ledger(tmp_path / "ledger2.json").attempts("feature:plain") == 0


def test_unclaimed_children_stay_awaiting_claim_untouched(tmp_path):
    """A dependent sibling nobody claimed stays harmlessly AWAITING_CLAIM."""
    first = _child("mission-intake-server")
    second = _child("mission-intake-tests")
    second.preconditions = ["feature:mission-intake-server"]
    state_path, ledger_path = _child_state(tmp_path, first, second)
    git = FakeGit(fail_creates=True)

    def refusing(feature: Feature) -> Handoff:
        raise AssertionError("unreached")

    run_worker(
        state_path,
        ledger_path,
        "w1",
        refusing,
        materialize=_materializer(git),
        park_threshold=5,
        max_units=1,
    )
    reconcile_from_ledger(state_path, ledger_path)
    state = MissionState.load(state_path)
    assert state.get("mission-intake-tests").status == Status.AWAITING_CLAIM
    assert state.get("mission-intake-tests").retry_count == 0
    assert Ledger(ledger_path).attempts("feature:mission-intake-tests") == 0


# ---- reconcile folds the branch into state --------------------------------------


def test_reconcile_folds_branch_and_promotes_awaiting_claim_to_pending(tmp_path):
    """A materialized-but-unfinished child becomes orchestrator-drivable: the
    recorded branch lands in metadata.branch and AWAITING_CLAIM -> PENDING."""
    state_path, ledger_path = _child_state(tmp_path)
    git = FakeGit()

    def transient(feature: Feature) -> Handoff:
        return Handoff(success=False, blocked_reason="quorum not satisfied: incomplete")

    run_worker(
        state_path,
        ledger_path,
        "w1",
        transient,
        materialize=_materializer(git),
        park_threshold=5,
        max_units=1,
    )
    n = reconcile_from_ledger(state_path, ledger_path)

    assert n >= 2  # branch fold + status transition
    child = MissionState.load(state_path).get("mission-intake-tests")
    assert child.metadata["branch"] == "mission/mission-intake-tests"
    assert child.status == Status.PENDING


def test_reconcile_never_promotes_parked_child_to_pending(tmp_path):
    state_path, ledger_path = _child_state(tmp_path)
    git = FakeGit()

    def always_blocked(feature: Feature) -> Handoff:
        return Handoff(success=False, blocked_reason="persistent blocker")

    run_worker(
        state_path,
        ledger_path,
        "w1",
        always_blocked,
        materialize=_materializer(git),
        park_threshold=2,
    )
    reconcile_from_ledger(state_path, ledger_path)

    child = MissionState.load(state_path).get("mission-intake-tests")
    assert child.status == Status.BLOCKED  # park wins; branch is provenance only
    assert child.metadata["branch"] == "mission/mission-intake-tests"


def test_reconcile_does_not_clobber_existing_live_branch(tmp_path):
    child = _child()
    child.metadata["branch"] = "mission/hand-attached"
    state_path, ledger_path = _child_state(tmp_path, child)
    Ledger(ledger_path).record_branch("mission-intake-tests", "mission/other")

    reconcile_from_ledger(state_path, ledger_path)

    reloaded = MissionState.load(state_path).get("mission-intake-tests")
    assert reloaded.metadata["branch"] == "mission/hand-attached"


# ---- full chain: seed -> decompose -> claim -> executable ------------------------


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


class _RecordingGate:
    """FleetGate stand-in that requires a REAL ref: head_of consults the same
    FakeGit the materializer used, so a fabricated metadata.branch would raise
    exactly like live ``git rev-parse``."""

    def __init__(self, git: FakeGit) -> None:
        self.git = git
        self.dispatched_branches: list[str] = []

    def branch_for(self, feature: Feature) -> str:
        return str(feature.metadata.get("branch") or f"mission/{feature.id}")

    def already_merged(self, branch: str) -> bool:
        return False

    def head_of(self, branch: str) -> str:
        return self.git(
            ["git", "rev-parse", "--verify", "--end-of-options", branch], Path()
        ).strip()

    def foreign_commits(self, branch, base, allowed_prefixes) -> list[str]:
        return []

    def tier_of(self, feature: Feature) -> int:
        return 0

    def collect_evidence(self, branch, head) -> GateVerdict:
        self.dispatched_branches.append(branch)
        return GateVerdict(satisfied=True)

    def merge_head_bound(self, branch, head) -> bool:
        return True


def test_swarm_yields_intake_to_orchestrator_without_losing_followups(tmp_path):
    state_path = tmp_path / "state.json"
    intake = Feature(
        id="mission-intake",
        description=GOAL,
        milestone="mission",
        metadata={"kind": "intake"},
    )
    MissionState(
        mission_id="mission-e2e",
        goal=GOAL,
        milestones=["mission"],
        features=[intake],
    ).save(state_path)
    bridge = IntakeBridgeDispatch(lambda feature: Handoff(success=True), decompose=_two_subtasks)

    result = run_worker(state_path, tmp_path / "ledger.json", "w1", bridge)

    assert result.awaiting_claim == ["mission-intake"]
    assert result.done == []
    assert MissionState.load(state_path).get("mission-intake").status == Status.PENDING


def test_full_chain_seed_decompose_claim_executable(tmp_path):
    """The whole point of #8773: fresh seed -> auto-drain decomposes ->
    worker claims -> branch exists -> metadata.branch set -> the real
    BossLoopDispatch drives the merge gate -> children complete. Zero
    manual steps, zero BLOCKED features, zero fabricated refs."""
    state_path = tmp_path / "state.json"
    MissionState(
        mission_id="mission-e2e",
        goal=GOAL,
        milestones=["mission"],
        features=[
            Feature(
                id="mission-intake",
                description=GOAL,
                milestone="mission",
                metadata={"kind": "intake", "paths": ["aragora/server"]},
            )
        ],
    ).save(state_path)
    ledger_path = tmp_path / "ledger.json"
    git = FakeGit()
    gate = _RecordingGate(git)
    bridge = IntakeBridgeDispatch(BossLoopDispatch(gate), decompose=_two_subtasks)

    # 1) Auto-drain: intake decomposes; children are born AWAITING_CLAIM.
    MissionOrchestrator(state_path).run(bridge, max_ticks=50)
    state = MissionState.load(state_path)
    children = [f for f in state.features if f.id != "mission-intake"]
    assert len(children) == 2
    assert all(f.status == Status.AWAITING_CLAIM for f in children)

    # 2) A worker claims, materializes, and drives the SAME dispatch chain.
    res = run_worker(
        state_path,
        ledger_path,
        "w1",
        bridge,
        materialize=BranchMaterializer("/repo", runner=git),
    )
    assert sorted(res.done) == sorted(f.id for f in children)
    assert res.parked == [] and res.blocked == []
    # Real refs were created from origin/main for each child hint.
    assert sorted(git.created_branches()) == sorted(
        str(f.metadata["branch_hint"]) for f in children
    )
    # The merge gate saw the materialized branches — the child was executable.
    assert sorted(gate.dispatched_branches) == sorted(git.created_branches())

    # 3) Reconcile: everything completes; branches are folded as provenance.
    reconcile_from_ledger(state_path, ledger_path)
    final = MissionState.load(state_path)
    assert final.get("mission-intake").status == Status.COMPLETED
    for feat in final.features:
        assert feat.status == Status.COMPLETED
        if feat.id != "mission-intake":
            assert feat.metadata["branch"] == feat.metadata["branch_hint"]
