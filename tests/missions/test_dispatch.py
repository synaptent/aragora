"""Tests for BossLoopDispatch — the merge-gate driving contract.

Validates every hard-won rule with a fake gate (no live main touched):
idempotency, the foreign-commit guard, Tier-3 escalation, dissent, head-bound
merge, and head-moved-under-us.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from aragora.missions.dispatch import BossLoopDispatch, GateVerdict
from aragora.missions.live_gate import LiveBossLoopGate
from aragora.missions.state import PARK_KIND_MISSING_BRANCH, Feature


class FakeGate:
    """Configurable in-memory stand-in for the live review_queue gate."""

    def __init__(
        self,
        *,
        merged: bool = False,
        head: str = "abc123",
        foreign: list[str] | None = None,
        verdict: GateVerdict | None = None,
        merge_ok: bool = True,
        tier: int = 0,
    ) -> None:
        self.merged = merged
        self.head = head
        self.foreign = foreign or []
        self.verdict = verdict or GateVerdict(satisfied=True)
        self.merge_ok = merge_ok
        self.tier = tier
        self.branch_calls = 0
        self.merge_calls: list[tuple[str, str]] = []
        self.foreign_args: tuple[str, str, tuple[str, ...]] | None = None
        self.evidence_calls = 0

    def branch_for(self, feature: Feature) -> str:
        self.branch_calls += 1
        return f"mission/{feature.id}"

    def already_merged(self, branch: str) -> bool:
        return self.merged

    def head_of(self, branch: str) -> str:
        return self.head

    def foreign_commits(self, branch, base, allowed_prefixes):
        self.foreign_args = (branch, base, allowed_prefixes)
        return list(self.foreign)

    def tier_of(self, feature: Feature) -> int:
        return self.tier

    def collect_evidence(self, branch, head):
        self.evidence_calls += 1
        return self.verdict

    def merge_head_bound(self, branch, head):
        self.merge_calls.append((branch, head))
        return self.merge_ok


def _feat() -> Feature:
    return Feature(
        id="a5",
        description="rehome x",
        milestone="phase-a-spine",
        metadata={"branch": "mission/a5"},
    )


def test_missing_branch_metadata_parks_before_live_git_lookup():
    gate = FakeGate()
    feature = Feature(id="a5", description="seeded intake", milestone="phase-a-spine")

    handoff = BossLoopDispatch(gate)(feature)

    assert not handoff.success
    # #8758 design decision: a missing branch is "not ready yet", never "dead" —
    # a retryable, reconciler-owned park, NOT a terminal block.
    assert not handoff.terminal
    assert handoff.parked
    assert handoff.parked_kind == PARK_KIND_MISSING_BRANCH
    assert "metadata.branch" in handoff.blocked_reason
    assert gate.branch_calls == 0
    assert gate.evidence_calls == 0
    assert gate.merge_calls == []


def test_nonempty_missing_branch_ref_reparks_before_evidence():
    class MissingRefGate(FakeGate):
        def head_of(self, branch: str) -> str:
            raise RuntimeError(f"fatal: unknown revision or path {branch}")

    gate = MissingRefGate()
    handoff = BossLoopDispatch(gate)(_feat())

    assert not handoff.success
    assert handoff.parked
    assert handoff.parked_kind == PARK_KIND_MISSING_BRANCH
    assert "live git ref" in (handoff.blocked_reason or "")
    assert gate.evidence_calls == 0
    assert gate.merge_calls == []


def test_clean_quorum_merges_head_bound():
    gate = FakeGate(head="deadbeef", verdict=GateVerdict(satisfied=True, tier=0))
    handoff = BossLoopDispatch(gate)(_feat())
    assert handoff.success
    assert gate.foreign_args == ("mission/a5", "origin/main", ("structex/", "mission/"))
    assert gate.merge_calls == [("mission/a5", "deadbeef")]


def test_already_merged_is_idempotent_success():
    gate = FakeGate(merged=True)
    handoff = BossLoopDispatch(gate)(_feat())
    assert handoff.success
    assert gate.evidence_calls == 0  # never re-collected
    assert gate.merge_calls == []  # never double-merged


def test_foreign_commit_guard_blocks_before_evidence():
    gate = FakeGate(foreign=["aa008da5 fix(memory): cache", "6f4a7222 test"])
    handoff = BossLoopDispatch(gate)(_feat())
    assert not handoff.success
    assert "re-derive" in handoff.blocked_reason
    assert gate.evidence_calls == 0  # the #8616 lesson: never collect on contamination
    assert gate.merge_calls == []


def test_missing_path_allowlist_parks_without_terminal_contamination():
    gate = FakeGate(foreign=["abc123 mission: update feature (missing mission path allowlist)"])
    handoff = BossLoopDispatch(gate)(_feat())
    assert not handoff.success
    assert not handoff.terminal
    assert "metadata missing paths" in handoff.blocked_reason
    assert gate.evidence_calls == 0
    assert gate.merge_calls == []


def test_tier3_escalates_before_spending_a_quorum():
    gate = FakeGate(tier=3)
    handoff = BossLoopDispatch(gate)(_feat())
    assert not handoff.success
    assert "operator settlement" in handoff.blocked_reason
    assert gate.evidence_calls == 0  # classified + escalated before collecting evidence
    assert gate.merge_calls == []  # never auto-settles a Tier-3 surface


def test_tier3_escalation_writes_operator_receipt(tmp_path):
    gate = FakeGate(tier=3)
    handoff = BossLoopDispatch(gate, receipt_dir=tmp_path / "receipts")(_feat())

    receipts = list((tmp_path / "receipts").glob("*.json"))

    assert not handoff.success
    assert len(receipts) == 1
    assert "operator receipt:" in handoff.discovered[0]


def test_post_evidence_tier_reclassification_escalates():
    """Defense in depth: pre-classification says Tier-0 but evidence reveals Tier-3
    — must escalate, not auto-merge past the operator boundary."""
    gate = FakeGate(tier=0, verdict=GateVerdict(satisfied=True, tier=3))
    handoff = BossLoopDispatch(gate)(_feat())
    assert not handoff.success
    assert handoff.terminal
    assert "reclassified to tier-3" in handoff.blocked_reason
    assert gate.merge_calls == []  # never merged past Tier-3


def test_dissent_blocks_without_merge():
    gate = FakeGate(verdict=GateVerdict(satisfied=False, tier=1, dissent=["[P1] real bug"]))
    handoff = BossLoopDispatch(gate)(_feat())
    assert not handoff.success
    assert "[P1] real bug" in handoff.blocked_reason
    assert gate.merge_calls == []


def test_head_moved_under_us_does_not_falsely_succeed():
    gate = FakeGate(verdict=GateVerdict(satisfied=True), merge_ok=False)
    handoff = BossLoopDispatch(gate)(_feat())
    assert not handoff.success
    assert "did not land" in handoff.blocked_reason


def test_live_gate_tier_prefers_merge_packet_over_feature_metadata():
    def runner(cmd: list[str], cwd: Path) -> str:
        if cmd[:2] == ["git", "rev-parse"] and cmd[-1] == "mission/a5":
            return "abc123\n"
        if cmd[:5] == [
            sys.executable,
            "-m",
            "aragora.cli.main",
            "review-queue",
            "merge-packet",
        ]:
            return json.dumps({"entries": [{"pr_number": 8655, "head_sha": "abc123", "tier": 3}]})
        raise AssertionError(f"unexpected command: {cmd}")

    gate = LiveBossLoopGate(repo_root=Path("."), runner=runner)
    feature = Feature(
        id="a5",
        description="inspect",
        milestone="m",
        metadata={"pr": 8655, "tier": 1},
    )

    assert gate.tier_of(feature) == 3


def test_live_gate_foreign_guard_rejects_subject_only_allowance():
    def runner(cmd: list[str], cwd: Path) -> str:
        if cmd[:2] == ["git", "log"]:
            return "abc123\tmission: update feature\n"
        if cmd[:3] == ["git", "show", "--format="]:
            return "aragora/missions/state.py\n"
        raise AssertionError(f"unexpected command: {cmd}")

    gate = LiveBossLoopGate(repo_root=Path("."), runner=runner)
    branch = gate.branch_for(
        Feature(id="a5", description="inspect", milestone="m", metadata={"branch": "mission/a5"})
    )

    foreign = gate.foreign_commits(branch, "origin/main", ("mission/",))

    assert foreign == ["abc123 mission: update feature (missing mission path allowlist)"]


def test_live_gate_foreign_guard_rejects_unexpected_paths():
    def runner(cmd: list[str], cwd: Path) -> str:
        if cmd[:2] == ["git", "log"]:
            return "abc123\tmission: update feature\n"
        if cmd[:3] == ["git", "show", "--format="]:
            return "aragora/missions/state.py\nREADME.md\n"
        raise AssertionError(f"unexpected command: {cmd}")

    gate = LiveBossLoopGate(repo_root=Path("."), runner=runner)
    branch = gate.branch_for(
        Feature(
            id="a5",
            description="inspect",
            milestone="m",
            metadata={"branch": "mission/a5", "paths": ["aragora/missions"]},
        )
    )

    foreign = gate.foreign_commits(branch, "origin/main", ("mission/",))

    assert foreign == ["abc123 mission: update feature (unexpected paths: README.md)"]
