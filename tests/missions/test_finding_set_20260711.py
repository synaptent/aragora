"""Regression suite for the 2026-07-11 claude finding set on #8766.

Each test pins one finding from the parked design-session set: the live-gate
false already_merged (P1), the ledger forever-constraint wedge (P1), the
dispatch transient/dead-ref conflation (P2), the foreign-branch adoption
guard (P3), and the CLI awaiting-claim visibility (P3). The forward-compat
status quarantine (P3) is pinned in test_mission_state.py.
"""

from __future__ import annotations

from pathlib import Path

from aragora.missions.dispatch import BossLoopDispatch
from aragora.missions.ledger import Ledger
from aragora.missions.live_gate import LiveBossLoopGate
from aragora.missions.state import (
    PARK_KIND_MATERIALIZATION,
    Feature,
    MissionState,
    Status,
)
from aragora.missions.swarm import (
    RETRYABLE_PARK_CONSTRAINT_TTL,
    BranchMaterializer,
)

BASE_HEAD = "a" * 40
OTHER_HEAD = "b" * 40


def _gate_with_runner(script):
    """LiveBossLoopGate whose git runner is the given callable."""
    return LiveBossLoopGate(repo_root=Path("."), runner=script)


class TestAlreadyMergedFreshBranch:
    """P1: a freshly materialized branch points exactly at base; `git branch
    --merged` lists it, so every decomposed child instantly returned success
    with zero work done."""

    def test_branch_at_base_tip_is_not_already_merged(self) -> None:
        def runner(argv, cwd):
            if argv[:3] == ["git", "rev-parse", "--verify"]:
                return BASE_HEAD  # branch and base resolve identically
            if argv[:3] == ["git", "branch", "--merged"]:
                return "  mission/f1\n"  # reachable-from-base lists it
            raise AssertionError(f"unexpected argv {argv}")

        assert _gate_with_runner(runner).already_merged("mission/f1") is False

    def test_branch_behind_base_with_merged_work_still_detects(self) -> None:
        heads = {"mission/f1": OTHER_HEAD, "origin/main": BASE_HEAD}

        def runner(argv, cwd):
            if argv[:3] == ["git", "rev-parse", "--verify"]:
                return heads[argv[-1]]
            if argv[:3] == ["git", "branch", "--merged"]:
                return "  mission/f1\n"
            raise AssertionError(f"unexpected argv {argv}")

        assert _gate_with_runner(runner).already_merged("mission/f1") is True


class TestRetryableParkConstraintTTL:
    """P1: ledger.fail with the default ttl=0 made the park constraint active
    FOREVER (only a successful record_branch invalidates), so the paced
    unpark could never hand the unit back to a worker."""

    def test_retryable_park_constraint_expires(self, tmp_path) -> None:
        ledger = Ledger(tmp_path / "ledger.json")
        assert ledger.claim("f1", "w1", now=1000.0)
        assert ledger.fail(
            "f1",
            "w1",
            constraint_key="feature:f1",
            constraint_reason=f"parked ({PARK_KIND_MATERIALIZATION}): git blip",
            constraint_ttl=RETRYABLE_PARK_CONSTRAINT_TTL,
            now=1000.0,
        )
        # Inside the TTL window the constraint holds...
        assert ledger.constraint_reason("feature:f1", now=1100.0) is not None
        # ...and after it elapses the unit is claimable again.
        assert ledger.claim_actionable(
            "f1",
            "w2",
            constraint_key="feature:f1",
            now=1000.0 + RETRYABLE_PARK_CONSTRAINT_TTL + 1,
        )


class TestDispatchTransientVsDeadRef:
    """P2: the runner raises RuntimeError for ALL nonzero exits and timeouts;
    only a genuine unknown-revision means the recorded ref is dead."""

    class _Gate:
        def __init__(self, exc_msg: str) -> None:
            self._msg = exc_msg

        def branch_for(self, feature):
            return str(feature.metadata["branch"])

        def already_merged(self, branch):
            return False

        def head_of(self, branch):
            raise RuntimeError(self._msg)

    def _feature(self):
        return Feature(
            id="f1",
            description="",
            milestone="m1",
            status=Status.PENDING,
            metadata={"branch": "mission/f1"},
        )

    def test_timeout_parks_as_paced_materialization(self) -> None:
        handoff = BossLoopDispatch(self._Gate("git command timed out after 120s"))(self._feature())
        assert handoff.parked and handoff.parked_kind == PARK_KIND_MATERIALIZATION

    def test_unknown_revision_parks_as_missing_branch(self) -> None:
        handoff = BossLoopDispatch(
            self._Gate("fatal: unknown revision or path not in the working tree")
        )(self._feature())
        assert handoff.parked and handoff.parked_kind != PARK_KIND_MATERIALIZATION


class TestResolveNameAdoptionGuard:
    """P3: every fresh branch starts at base, so a plain-hint-named branch a
    foreign actor just pushed is indistinguishable from our crash orphan —
    adopting it silently hijacks their branch."""

    def _materializer(self, existing_heads):
        def runner(argv, cwd):
            if argv[:3] == ["git", "rev-parse", "--verify"]:
                ref = argv[-1]
                if ref in existing_heads:
                    return existing_heads[ref]
                raise RuntimeError(f"fatal: unknown revision {ref}")
            if argv[:2] == ["git", "branch"]:
                return ""
            raise AssertionError(f"unexpected argv {argv}")

        return BranchMaterializer(repo_root=Path("."), base="origin/main", runner=runner)

    def test_plain_hint_at_base_is_not_adopted(self, tmp_path) -> None:
        mat = self._materializer({"origin/main": BASE_HEAD, "mission/f1": BASE_HEAD})
        resolved = mat._resolve_name("mission/f1")
        assert resolved != "mission/f1"  # falls to the hash-suffixed namespace

    def test_suffixed_orphan_at_base_is_adopted(self, tmp_path) -> None:
        mat = self._materializer({"origin/main": BASE_HEAD})
        suffixed = mat._suffixed("mission/f1")
        mat2 = self._materializer(
            {"origin/main": BASE_HEAD, "mission/f1": OTHER_HEAD, suffixed: BASE_HEAD}
        )
        assert mat2._resolve_name("mission/f1") == suffixed


def test_status_summary_counts_awaiting_claim(tmp_path, capsys) -> None:
    """P3: the primary state of a freshly decomposed mission was invisible."""
    from aragora.cli.commands.mission import _cmd_status

    state = MissionState(
        mission_id="m1",
        goal="g",
        milestones=["m1"],
        features=[Feature(id="f1", description="", milestone="m1", status=Status.AWAITING_CLAIM)],
    )
    path = tmp_path / "state.json"
    state.save(path)

    class Args:
        state = str(path)

    _cmd_status(Args())
    out = capsys.readouterr().out
    assert "1 awaiting claim" in out


def test_swarm_reconcile_releases_expired_retryable_park(tmp_path) -> None:
    """#8766 openai P2 (post-session round): select_for only claims
    PENDING/AWAITING_CLAIM/IN_PROGRESS and _reevaluate_parked is
    orchestrator-only, so a pure swarm flow must release a PARKED feature
    itself once its retryable constraint TTL expires."""
    from aragora.missions.ledger import Ledger as _Ledger
    from aragora.missions.swarm import _reconcile_locked

    state = MissionState(
        mission_id="m1",
        goal="g",
        milestones=["m1"],
        features=[Feature(id="f1", description="", milestone="m1", status=Status.AWAITING_CLAIM)],
    )
    state_path = tmp_path / "state.json"
    state.save(state_path)
    ledger_path = tmp_path / "ledger.json"
    import time as _time

    ledger = _Ledger(ledger_path)
    now = _time.time()
    assert ledger.claim("f1", "w1", now=now)
    assert ledger.fail(
        "f1",
        "w1",
        constraint_key="feature:f1",
        constraint_reason=f"parked ({PARK_KIND_MATERIALIZATION}): git blip",
        constraint_ttl=RETRYABLE_PARK_CONSTRAINT_TTL,
        now=now,
    )
    # While the constraint is active the park folds in and holds.
    _reconcile_locked(state_path, ledger_path)
    assert MissionState.load(state_path).get("f1").status == Status.PARKED
    # Re-record the same park far enough in the past that its TTL has
    # expired: reconcile must release the park back to a claimable status.
    past = now - RETRYABLE_PARK_CONSTRAINT_TTL - 10
    assert ledger.claim("f1", "w2", now=past)
    assert ledger.fail(
        "f1",
        "w2",
        constraint_key="feature:f1",
        constraint_reason=f"parked ({PARK_KIND_MATERIALIZATION}): git blip",
        constraint_ttl=RETRYABLE_PARK_CONSTRAINT_TTL,
        now=past,
    )
    _reconcile_locked(state_path, ledger_path)
    assert MissionState.load(state_path).get("f1").status == Status.PENDING
