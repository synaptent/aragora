"""Tests for ``scripts/merge_executor.py`` (issue #8759).

The executor is a bounded single-pass composition over the existing
auto-merge-on-green machinery; it never invents a new merge gate. These tests
drive the pass core (``run_pass``) and helpers with injected I/O — no real
``gh``, no network, no live GitHub mutation.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from aragora.swarm.auto_merge_green import REQUIRED_CHECKS


def _load_module() -> Any:
    script = Path(__file__).resolve().parents[2] / "scripts" / "merge_executor.py"
    spec = importlib.util.spec_from_file_location("merge_executor_under_test", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load spec for {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


me = _load_module()

HEAD = "a" * 40


def _rollup_all_green() -> list[dict]:
    rollup = [{"name": name, "conclusion": "SUCCESS"} for name in REQUIRED_CHECKS]
    rollup.append({"name": "aragora-merge-quorum", "conclusion": "SUCCESS"})
    return rollup


def _view(number: int = 100, head: str = HEAD, **overrides) -> dict:
    base = dict(
        number=number,
        headRefOid=head,
        isDraft=False,
        mergeable="MERGEABLE",
        mergeStateStatus="BLOCKED",
        statusCheckRollup=_rollup_all_green(),
    )
    base.update(overrides)
    return base


def _packet(number: int = 100, head: str = HEAD, tier: int = 1, **overrides) -> dict:
    base = dict(
        pr_number=number,
        tier=tier,
        status="satisfied",
        verdict="admin_squash_allowed",
        requires_human_risk_settlement=False,
        unresolved_dissent=False,
        admin_squash_allowed=True,
        head_sha=head,
    )
    base.update(overrides)
    return base


def _main_runs_green() -> list[dict]:
    return [
        {"id": i, "name": name, "status": "completed", "conclusion": "success"}
        for i, name in enumerate(sorted(REQUIRED_CHECKS), start=1)
    ]


def _main_runs_red() -> list[dict]:
    runs = _main_runs_green()
    runs[0] = dict(runs[0], conclusion="failure")
    return runs


class _Harness:
    """Injected I/O for run_pass: fixture-backed, records every merge call."""

    def __init__(self, views: dict[int, dict], packets: dict[int, dict | None]):
        self.views = views
        self.packets = packets
        self.merge_calls: list[tuple[int, str]] = []
        self.merge_result: tuple[bool, str] = (True, "merged")
        self.main_runs: list[dict] | None = _main_runs_green()

    def merge_fn(self, pr: int, head: str) -> tuple[bool, str]:
        self.merge_calls.append((pr, head))
        return self.merge_result


def _kwargs(h: _Harness, tmp_path: Path, **overrides) -> dict:
    base = dict(
        repo="owner/name",
        prs=[100],
        apply=False,
        max_merges=1,
        receipt_dir=tmp_path / "receipts",
        halt_file=tmp_path / "halt.json",
        disarm_file=tmp_path / "disarm",
        fetch_view=h.views.get,
        fetch_packet=h.packets.get,
        promising=lambda view: True,
        merge_fn=h.merge_fn,
        fetch_main_checks=lambda: h.main_runs,
        fetch_main_statuses=lambda: [],
    )
    base.update(overrides)
    return base


def _actions(summary: dict) -> dict[int, str]:
    return {r["pr"]: r["action"] for r in summary["results"]}


def test_main_health_green_when_all_required_success():
    assert me.evaluate_main_health(_main_runs_green(), REQUIRED_CHECKS) == ("green", [])


def test_main_health_red_on_required_failure():
    state, details = me.evaluate_main_health(_main_runs_red(), REQUIRED_CHECKS)
    assert state == "red"
    assert any("failure" in d for d in details)


def test_main_health_indeterminate_on_pending_empty_or_fetch_failure():
    pending = _main_runs_green()
    pending[0] = dict(pending[0], status="in_progress", conclusion="")
    for runs in (pending, [], None):
        assert me.evaluate_main_health(runs, REQUIRED_CHECKS)[0] == "indeterminate"


def test_main_health_green_when_pr_only_checks_absent_on_main_push():
    # Structural reality (verified live): "Generate & Validate" and
    # "TypeScript SDK Type Check" only run on PRs, never on main-push commits.
    # Their absence must read as not-applicable, otherwise the armed executor
    # could never see green. Failing/pending PRESENT checks still block.
    present = {"lint", "typecheck", "sdk-parity"}
    runs = [r for r in _main_runs_green() if r["name"] in present]
    assert me.evaluate_main_health(runs, REQUIRED_CHECKS)[0] == "green"


def test_main_health_red_still_wins_when_other_checks_absent():
    runs = [
        {"id": 1, "name": "lint", "status": "completed", "conclusion": "failure"},
        {"id": 2, "name": "typecheck", "status": "completed", "conclusion": "success"},
    ]
    state, details = me.evaluate_main_health(runs, REQUIRED_CHECKS)
    assert state == "red"
    assert any("lint" in d for d in details)


def test_main_health_uses_latest_run_per_check():
    # An old failing run superseded by a newer success must not read as red.
    name = sorted(REQUIRED_CHECKS)[0]
    runs = _main_runs_green()
    runs.append({"id": 0, "name": name, "status": "completed", "conclusion": "failure"})
    assert me.evaluate_main_health(runs, REQUIRED_CHECKS)[0] == "green"


def test_main_health_red_on_failing_commit_status_even_with_green_check_runs():
    # A required context can report as a commit *status* instead of a check
    # run; a present-and-failing status must always block (review P2).
    statuses = [{"context": "lint", "state": "failure"}]
    state, details = me.evaluate_main_health(_main_runs_green(), REQUIRED_CHECKS, statuses)
    assert state == "red"
    assert any("lint" in d and "status" in d for d in details)


def test_main_health_status_only_required_context_counts_as_present():
    # 'lint' delivered ONLY as a commit status: success -> green;
    # pending -> indeterminate (fail closed, no halt).
    runs = [r for r in _main_runs_green() if r["name"] != "lint"]
    ok = [{"context": "lint", "state": "success"}]
    assert me.evaluate_main_health(runs, REQUIRED_CHECKS, ok)[0] == "green"
    pending = [{"context": "lint", "state": "pending"}]
    assert me.evaluate_main_health(runs, REQUIRED_CHECKS, pending)[0] == "indeterminate"


def test_main_health_indeterminate_on_statuses_fetch_failure():
    state, _ = me.evaluate_main_health(_main_runs_green(), REQUIRED_CHECKS, None)
    assert state == "indeterminate"


def test_dry_run_never_calls_merge_fn(tmp_path):
    h = _Harness({100: _view()}, {100: _packet()})
    summary = me.run_pass(**_kwargs(h, tmp_path))
    assert h.merge_calls == []
    assert summary["mode"] == "dry-run"
    assert _actions(summary)[100] == "would-merge"


def test_dry_run_writes_no_receipts_and_no_halt_even_on_red_main(tmp_path):
    h = _Harness({100: _view()}, {100: _packet()})
    h.main_runs = _main_runs_red()
    summary = me.run_pass(**_kwargs(h, tmp_path))
    assert summary["main_health"] == "red"
    assert not (tmp_path / "receipts").exists()
    assert not (tmp_path / "halt.json").exists()


def test_dry_run_reports_blockers_for_ineligible(tmp_path):
    h = _Harness({100: _view(isDraft=True)}, {100: _packet()})
    record = me.run_pass(**_kwargs(h, tmp_path))["results"][0]
    assert record["action"] == "skip"
    assert any("draft" in b for b in record["blockers"])


@pytest.mark.parametrize(("tier", "in_digest"), [(0, False), (2, False), (3, True), (4, True)])
def test_tier_3_and_4_never_merged_and_listed_in_digest(tmp_path, tier, in_digest):
    h = _Harness({100: _view()}, {100: _packet(tier=tier)})
    summary = me.run_pass(**_kwargs(h, tmp_path, apply=True))
    digest = [(d["pr"], d["tier"]) for d in summary["tier_3_4_digest"]]
    assert digest == ([(100, tier)] if in_digest else [])
    if in_digest:
        assert h.merge_calls == []  # NEVER acted on, even under --apply


def test_unknown_tier_blocks_merge(tmp_path):
    h = _Harness({100: _view()}, {100: None})
    summary = me.run_pass(**_kwargs(h, tmp_path, apply=True))
    assert h.merge_calls == []
    assert _actions(summary)[100] == "skip"


def test_apply_merges_and_writes_receipt(tmp_path):
    h = _Harness({100: _view()}, {100: _packet(tier=2)})
    summary = me.run_pass(**_kwargs(h, tmp_path, apply=True))
    assert h.merge_calls == [(100, HEAD)]
    assert _actions(summary)[100] == "merged"

    receipts = list((tmp_path / "receipts").glob("*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    expected = {"pr": 100, "head_sha": HEAD, "tier": 2, "repo": "owner/name"}
    assert {k: receipt[k] for k in expected} == expected
    assert receipt["merged_at"] and receipt["executor"]["user"] and receipt["executor"]["host"]
    # packet evidence travels with the receipt
    assert receipt["packet_entry"]["status"] == "satisfied"
    assert receipt["packet_entry"]["verdict"] == "admin_squash_allowed"


def test_apply_max_merges_defers_extras(tmp_path):
    views = {1: _view(1, head="1" * 40), 2: _view(2, head="2" * 40)}
    packets = {1: _packet(1, head="1" * 40), 2: _packet(2, head="2" * 40)}
    h = _Harness(views, packets)
    summary = me.run_pass(**_kwargs(h, tmp_path, prs=[1, 2], apply=True, max_merges=1))
    assert len(h.merge_calls) == 1
    assert _actions(summary)[1] == "merged"
    assert "deferred" in _actions(summary)[2]


def test_apply_merge_failure_recorded_and_no_receipt(tmp_path):
    h = _Harness({100: _view()}, {100: _packet()})
    h.merge_result = (False, "gh rejected")
    summary = me.run_pass(**_kwargs(h, tmp_path, apply=True))
    assert _actions(summary)[100] == "merge-failed"
    assert not list((tmp_path / "receipts").glob("*.json"))


def test_head_moved_between_discovery_and_merge_skips(tmp_path):
    h = _Harness({}, {100: _packet()})
    # Discovery sees HEAD; re-verification sees a new head -> must not merge.
    views = iter([_view(), _view(head="b" * 40)])
    moving = lambda pr: next(views, None)  # noqa: E731
    summary = me.run_pass(**_kwargs(h, tmp_path, apply=True, fetch_view=moving))
    assert h.merge_calls == []
    record = summary["results"][0]
    assert record["action"] == "skip"
    assert any("head" in b.lower() for b in record["blockers"])


def test_packet_regression_at_reverify_skips(tmp_path):
    h = _Harness({100: _view()}, {})
    packets = iter([_packet(), _packet(status="pending")])
    summary = me.run_pass(
        **_kwargs(h, tmp_path, apply=True, fetch_packet=lambda pr: next(packets, None))
    )
    assert h.merge_calls == []
    record = summary["results"][0]
    assert record["action"] == "skip"
    assert record["blockers"]


def test_apply_red_main_halts_writes_marker_and_merges_nothing(tmp_path):
    h = _Harness({100: _view()}, {100: _packet()})
    h.main_runs = _main_runs_red()
    summary = me.run_pass(**_kwargs(h, tmp_path, apply=True))
    assert h.merge_calls == []
    assert summary["halted"] is True
    payload = json.loads((tmp_path / "halt.json").read_text())
    assert payload["reason"] == "main_red"
    assert payload["repo"] == "owner/name"


def test_apply_indeterminate_main_blocks_merges_without_marker(tmp_path):
    h = _Harness({100: _view()}, {100: _packet()})
    h.main_runs = None  # fetch failed -> indeterminate
    summary = me.run_pass(**_kwargs(h, tmp_path, apply=True))
    assert h.merge_calls == []
    assert summary["halted"] is False
    assert not (tmp_path / "halt.json").exists()
    assert "blocked" in _actions(summary)[100]


def _two_pr_harness() -> _Harness:
    views = {1: _view(1, head="1" * 40), 2: _view(2, head="2" * 40)}
    packets = {1: _packet(1, head="1" * 40), 2: _packet(2, head="2" * 40)}
    return _Harness(views, packets)


def test_health_flips_red_between_merges_blocks_second_and_halts(tmp_path):
    # Health is re-evaluated before EACH merge (review P1): pass-start green,
    # green before merge 1, red before merge 2 -> merge 2 blocked, marker written.
    h = _two_pr_harness()
    sequence = iter([_main_runs_green(), _main_runs_green(), _main_runs_red()])
    summary = me.run_pass(
        **_kwargs(
            h,
            tmp_path,
            prs=[1, 2],
            apply=True,
            max_merges=2,
            fetch_main_checks=lambda: next(sequence, _main_runs_red()),
        )
    )
    assert [pr for pr, _ in h.merge_calls] == [1]
    assert _actions(summary)[1] == "merged"
    assert "blocked" in _actions(summary)[2]
    assert summary["halted"] is True
    assert json.loads((tmp_path / "halt.json").read_text())["reason"] == "main_red"


def test_health_flips_pending_between_merges_blocks_second_without_marker(tmp_path):
    # Pending main mid-pass (e.g. our own merge 1 landed) blocks the remainder
    # of the pass fail-closed, but is not evidence of breakage: no halt marker,
    # so the NEXT pass re-evaluates fresh instead of requiring human re-arm.
    h = _two_pr_harness()
    pending = _main_runs_green()
    pending[0] = dict(pending[0], status="in_progress", conclusion="")
    sequence = iter([_main_runs_green(), _main_runs_green(), pending])
    summary = me.run_pass(
        **_kwargs(
            h,
            tmp_path,
            prs=[1, 2],
            apply=True,
            max_merges=2,
            fetch_main_checks=lambda: next(sequence, pending),
        )
    )
    assert [pr for pr, _ in h.merge_calls] == [1]
    assert "blocked" in _actions(summary)[2]
    assert summary["halted"] is False
    assert not (tmp_path / "halt.json").exists()


def test_existing_halt_marker_blocks_apply(tmp_path):
    (tmp_path / "halt.json").write_text("{}")
    h = _Harness({100: _view()}, {100: _packet()})
    summary = me.run_pass(**_kwargs(h, tmp_path, apply=True))
    assert h.merge_calls == []
    assert summary["halted"] is True


@pytest.mark.parametrize("apply", [True, False])
def test_disarm_file_blocks_all_merging(tmp_path, apply):
    (tmp_path / "disarm").write_text("")
    h = _Harness({100: _view()}, {100: _packet()})
    summary = me.run_pass(**_kwargs(h, tmp_path, apply=apply))
    assert h.merge_calls == []
    assert summary["disarmed"] is True
    assert "blocked" in _actions(summary)[100]


def test_exit_codes():
    ok = {"halted": False, "disarmed": False, "results": []}
    assert me.exit_code_for(ok, apply=False) == 0
    assert me.exit_code_for(ok, apply=True) == 0
    assert me.exit_code_for(dict(ok, halted=True), apply=True) == 3
    assert me.exit_code_for(dict(ok, disarmed=True), apply=True) == 3
    failed = dict(ok, results=[{"pr": 1, "action": "merge-failed"}])
    assert me.exit_code_for(failed, apply=True) == 1
    # Dry-run is informational: never an error exit.
    assert me.exit_code_for(dict(ok, disarmed=True, halted=True), apply=False) == 0


def test_merge_command_is_delegated_to_auto_merge_quorum_green(monkeypatch):
    # The executor must NEVER construct its own `gh pr merge`; it reuses the
    # existing script's merge path verbatim.
    calls: list[str] = []
    monkeypatch.setattr(
        me._amqg,
        "_make_merge_fn",
        lambda repo: calls.append(repo) or (lambda pr, head: (True, "sentinel")),
    )
    fn = me.make_merge_fn("owner/name")
    assert calls == ["owner/name"]
    assert fn(1, "x") == (True, "sentinel")


def test_discovery_helpers_are_delegated():
    assert me.fetch_view is me._amqg.fetch_view
    assert me.fetch_packet is me._amqg.fetch_packet_entry
    assert me.list_open_prs is me._amqg.list_open_pr_numbers
    assert me.DEFAULT_MAX_MERGES == 1


@pytest.mark.parametrize(
    "quorum_rows",
    [
        [
            {"name": "aragora-merge-quorum", "conclusion": "FAILURE"},
            {"name": "aragora-merge-quorum", "conclusion": "SUCCESS"},
        ],
        [
            {"name": "aragora-merge-quorum", "conclusion": "SUCCESS"},
            {"name": "aragora-merge-quorum", "conclusion": "FAILURE"},
        ],
    ],
)
def test_quorum_prefilter_fetches_packet_when_any_historical_row_succeeded(quorum_rows):
    view = _view(statusCheckRollup=quorum_rows)
    assert me._amqg._cheaply_promising(view) is True


def test_quorum_prefilter_skips_packet_when_no_quorum_row_succeeded():
    view = _view(
        statusCheckRollup=[
            {"name": "aragora-merge-quorum", "conclusion": "FAILURE"},
            {"name": "aragora-merge-quorum", "conclusion": "CANCELLED"},
        ]
    )
    assert me._amqg._cheaply_promising(view) is False


def _cli_args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--repo",
        "owner/name",
        "--json",
        "--receipt-dir",
        str(tmp_path / "receipts"),
        "--halt-file",
        str(tmp_path / "halt.json"),
        "--disarm-file",
        str(tmp_path / "disarm"),
        *extra,
    ]


def test_main_json_output_dry_run(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(me, "list_open_prs", lambda repo, limit: [100])
    monkeypatch.setattr(me, "fetch_view", lambda repo, pr: _view())
    monkeypatch.setattr(me, "fetch_packet", lambda repo, pr: _packet())
    monkeypatch.setattr(me, "fetch_main_checks", lambda repo, branch: _main_runs_green())
    monkeypatch.setattr(me, "fetch_main_statuses", lambda repo, branch: [])

    rc = me.main(_cli_args(tmp_path))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "dry-run"
    assert payload["repo"] == "owner/name"
    assert payload["main_health"] == "green"
    assert _actions(payload)[100] == "would-merge"
    assert not (tmp_path / "receipts").exists()


def test_main_apply_red_main_returns_halt_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(me, "list_open_prs", lambda repo, limit: [100])
    monkeypatch.setattr(me, "fetch_view", lambda repo, pr: _view())
    monkeypatch.setattr(me, "fetch_packet", lambda repo, pr: _packet())
    monkeypatch.setattr(me, "fetch_main_checks", lambda repo, branch: _main_runs_red())
    monkeypatch.setattr(me, "fetch_main_statuses", lambda repo, branch: [])
    merge_calls: list[int] = []
    monkeypatch.setattr(
        me, "make_merge_fn", lambda repo: lambda pr, head: merge_calls.append(pr) or (True, "x")
    )

    rc = me.main(_cli_args(tmp_path, "--apply"))
    assert rc == 3
    assert merge_calls == []
    assert (tmp_path / "halt.json").exists()
