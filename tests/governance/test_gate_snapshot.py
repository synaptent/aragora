"""#9873: a merge may only land the head whose checks authorized it.

The race tests are the point of this file. Everything else guards the shape that
makes the race safe; these prove the behaviour under an actual head change
between classification and merge.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess

import pytest

from aragora.governance.gate_snapshot import (
    GateSnapshot,
    GateSnapshotError,
    MergeRefused,
    capture_gate_snapshot,
    merge_with_snapshot,
    require_snapshot,
)

HEAD_A = "a" * 40
HEAD_B = "b" * 40


def _proc(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _view_payload(head: str, *, green: bool = True, state: str = "OPEN", draft: bool = False):
    conclusion = "SUCCESS" if green else "FAILURE"
    return json.dumps(
        {
            "number": 42,
            "headRefOid": head,
            "state": state,
            "isDraft": draft,
            "mergeStateStatus": "CLEAN",
            "statusCheckRollup": [{"status": "COMPLETED", "conclusion": conclusion}],
        }
    )


class _Recorder:
    """Runner that serves scripted responses and records every argv."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[list[str]] = []

    def __call__(self, args, *, timeout=30.0):
        self.calls.append(list(args))
        return self._responses.pop(0) if self._responses else _proc()


# --------------------------------------------------------------------------
# The invariant: no snapshot, no merge — enforced by construction
# --------------------------------------------------------------------------


def test_a_snapshot_cannot_exist_without_a_full_head() -> None:
    """'Refuse when the head is missing' is structural, not a forgettable check."""
    for bad in ["", None, "abc123", HEAD_A[:12], "z" * 40]:
        with pytest.raises(GateSnapshotError):
            GateSnapshot(42, "o/r", bad, True, True, "OPEN", False, None, "t")  # type: ignore[arg-type]


def test_capture_refuses_when_github_omits_the_head() -> None:
    payload = json.dumps({"number": 42, "state": "OPEN", "statusCheckRollup": []})
    with pytest.raises(GateSnapshotError):
        capture_gate_snapshot(42, "o/r", runner=_Recorder([_proc(stdout=payload)]))


def test_capture_failure_is_not_mistaken_for_a_missing_head() -> None:
    """A failed read must raise, never yield a snapshot-shaped 'no'."""
    with pytest.raises(GateSnapshotError) as exc:
        capture_gate_snapshot(42, "o/r", runner=_Recorder([_proc(returncode=1, stderr="boom")]))
    assert "boom" in str(exc.value)


def test_merge_without_a_snapshot_is_refused() -> None:
    with pytest.raises(MergeRefused):
        merge_with_snapshot(None)
    with pytest.raises(MergeRefused):
        require_snapshot(None, pr_number=42)


def test_snapshot_is_immutable() -> None:
    """Frozen is what stops a caller 'refreshing' the head after classification."""
    snap = GateSnapshot(42, "o/r", HEAD_A, True, True, "OPEN", False, None, "t")
    with pytest.raises(Exception):
        snap.head_sha = HEAD_B  # type: ignore[misc]


def test_head_and_verdict_come_from_one_read() -> None:
    """Two reads would reintroduce the split this type exists to prevent."""
    rec = _Recorder([_proc(stdout=_view_payload(HEAD_A))])
    snap = capture_gate_snapshot(42, "o/r", runner=rec)
    assert len(rec.calls) == 1, f"expected exactly one gh read, got {rec.calls}"
    assert snap.head_sha == HEAD_A and snap.required_checks_green


def test_unknown_checks_are_not_a_pass() -> None:
    """An empty rollup means 'we do not know', which must not authorize a merge."""
    payload = json.dumps(
        {"number": 42, "headRefOid": HEAD_A, "state": "OPEN", "statusCheckRollup": []}
    )
    snap = capture_gate_snapshot(42, "o/r", runner=_Recorder([_proc(stdout=payload)]))
    assert not snap.checks_known and not snap.mergeable_now


# --------------------------------------------------------------------------
# The race: head changes between classification and merge
# --------------------------------------------------------------------------


def test_race_merge_pins_the_captured_head_not_the_live_one() -> None:
    """Capture at A, PR force-pushes to B, merge must still carry A.

    This is the TOCTOU that nine rounds of #9677 failed to close by passing a
    SHA around: any code path that re-reads the head here would send B and merge
    unchecked content.
    """
    rec = _Recorder([_proc(stdout=_view_payload(HEAD_A)), _proc(returncode=0, stdout="merged")])
    snap = capture_gate_snapshot(42, "o/r", runner=rec)

    # ... the world moves on: the PR is force-pushed to HEAD_B ...

    merge_with_snapshot(snap, runner=rec)
    merge_argv = rec.calls[-1]
    assert "--match-head-commit" in merge_argv
    pinned = merge_argv[merge_argv.index("--match-head-commit") + 1]
    assert pinned == HEAD_A, f"merge pinned {pinned}, must pin the captured head {HEAD_A}"
    assert HEAD_B not in merge_argv


def test_race_github_rejection_is_surfaced_as_refusal_not_retried() -> None:
    """When the head moved, GitHub rejects the pin — we must report, not retry."""
    rec = _Recorder(
        [
            _proc(stdout=_view_payload(HEAD_A)),
            _proc(returncode=1, stderr="Head branch was modified. Review and try again."),
        ]
    )
    snap = capture_gate_snapshot(42, "o/r", runner=rec)
    outcome = merge_with_snapshot(snap, runner=rec)

    assert outcome.merged is False
    assert outcome.action == "refused"
    assert "Head branch was modified" in outcome.detail
    assert outcome.head_sha == HEAD_A
    # Exactly one capture and one merge — no re-read, no second attempt.
    assert len(rec.calls) == 2, f"a retry or re-resolve happened: {rec.calls}"


def test_race_a_stale_verdict_cannot_be_paired_with_a_fresh_head() -> None:
    """The reverted #9677 bug, encoded: classification then a *new* head lookup.

    Building a second snapshot is the only way to obtain HEAD_B, and doing so
    re-reads the checks too — so a fresh head always arrives with a fresh
    verdict. There is no API that yields B's head with A's verdict.
    """
    rec = _Recorder([_proc(stdout=_view_payload(HEAD_A, green=True))])
    first = capture_gate_snapshot(42, "o/r", runner=rec)

    rec2 = _Recorder([_proc(stdout=_view_payload(HEAD_B, green=False))])
    second = capture_gate_snapshot(42, "o/r", runner=rec2)

    assert first.head_sha == HEAD_A and first.required_checks_green
    assert second.head_sha == HEAD_B and not second.required_checks_green
    # The failing new head cannot borrow the old head's pass.
    assert not second.mergeable_now
    assert merge_with_snapshot(second, runner=_Recorder([])).action == "blocked"


def test_merge_argv_carries_exactly_one_head_pin() -> None:
    rec = _Recorder([_proc(stdout=_view_payload(HEAD_A)), _proc()])
    snap = capture_gate_snapshot(42, "o/r", runner=rec)
    merge_with_snapshot(snap, admin=True, delete_branch=True, runner=rec)
    argv = rec.calls[-1]
    assert argv.count("--match-head-commit") == 1
    assert argv[-2:] == ["--match-head-commit", HEAD_A]


def test_a_non_open_or_draft_pr_is_not_mergeable() -> None:
    for payload in (
        _view_payload(HEAD_A, state="CLOSED"),
        _view_payload(HEAD_A, draft=True),
        _view_payload(HEAD_A, green=False),
    ):
        snap = capture_gate_snapshot(42, "o/r", runner=_Recorder([_proc(stdout=payload)]))
        assert not snap.mergeable_now
        assert merge_with_snapshot(snap, runner=_Recorder([])).action == "blocked"


# --------------------------------------------------------------------------
# Argument hygiene: what reaches gh must be a well-formed capture
# --------------------------------------------------------------------------


def test_a_snapshot_requires_an_owner_name_repository() -> None:
    for bad in ["", "o", "o/r/x", "x /../evil", "o/r --admin", "../o/r"]:
        with pytest.raises(GateSnapshotError):
            GateSnapshot(42, bad, HEAD_A, True, True, "OPEN", False, None, "t")


def test_capture_rejects_a_malformed_repository_before_reading() -> None:
    rec = _Recorder([])
    with pytest.raises(GateSnapshotError):
        capture_gate_snapshot(42, "x /../evil", runner=rec)
    assert rec.calls == []


def test_a_non_integer_pr_number_from_github_is_a_capture_error() -> None:
    """Callers catch GateSnapshotError; a bare ValueError would escape them."""
    payload = json.dumps(
        {"number": "forty-two", "headRefOid": HEAD_A, "state": "OPEN", "statusCheckRollup": []}
    )
    with pytest.raises(GateSnapshotError):
        capture_gate_snapshot(42, "o/r", runner=_Recorder([_proc(stdout=payload)]))


# --------------------------------------------------------------------------
# The main-red merge halt (#9216) applies to the captured head
# --------------------------------------------------------------------------


@pytest.fixture
def armed_halt(tmp_path, monkeypatch):
    """Arm the halt marker the merge reads by default, with no waiver present."""
    import aragora.swarm.merge_halt as merge_halt

    halt = tmp_path / "merge_executor.halt"
    halt.write_text(json.dumps({"reason": "main_red"}) + "\n", encoding="utf-8")
    waiver = tmp_path / "merge_executor.waiver"
    monkeypatch.setattr(merge_halt, "DEFAULT_HALT_FILE", halt)
    monkeypatch.setattr(merge_halt, "DEFAULT_WAIVER_FILE", waiver)
    monkeypatch.setattr(merge_halt, "SHARED_ROOT_ERROR", None)
    return waiver


def _waive(path, *, head: str) -> None:
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    payload = {
        "pr": 42,
        "head_sha": head,
        "actor": "operator",
        "scope": "single-pr",
        "reason": "incident waiver",
        "expires_at": expires.isoformat(),
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_merge_refuses_while_the_main_red_halt_is_armed(armed_halt) -> None:
    rec = _Recorder([_proc(stdout=_view_payload(HEAD_A))])
    snap = capture_gate_snapshot(42, "o/r", runner=rec)
    outcome = merge_with_snapshot(snap, runner=rec)

    assert (outcome.merged, outcome.action) == (False, "blocked")
    assert "halt armed" in outcome.detail
    assert outcome.head_sha == HEAD_A
    assert len(rec.calls) == 1, f"a merge ran while the halt was armed: {rec.calls}"


def test_a_waiver_for_the_captured_head_lets_the_pinned_merge_run(armed_halt) -> None:
    _waive(armed_halt, head=HEAD_A)
    rec = _Recorder([_proc(stdout=_view_payload(HEAD_A)), _proc(stdout="merged")])
    outcome = merge_with_snapshot(capture_gate_snapshot(42, "o/r", runner=rec), runner=rec)

    assert outcome.merged is True
    assert rec.calls[-1][-2:] == ["--match-head-commit", HEAD_A]


def test_a_waiver_for_another_head_does_not_apply(armed_halt) -> None:
    _waive(armed_halt, head=HEAD_B)
    rec = _Recorder([_proc(stdout=_view_payload(HEAD_A))])
    outcome = merge_with_snapshot(capture_gate_snapshot(42, "o/r", runner=rec), runner=rec)

    assert outcome.action == "blocked"
    assert len(rec.calls) == 1, f"a merge ran under another head's waiver: {rec.calls}"
