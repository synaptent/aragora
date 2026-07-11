"""Tests for scripts/harvest_outcomes.py (#8760). gh/git fully mocked; no live GitHub access."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import scripts.harvest_outcomes as mod


def _pr(**overrides: Any) -> dict[str, Any]:
    pr: dict[str, Any] = {
        "number": 1,
        "title": "feat: add widget",
        "mergedAt": None,
        "closedAt": "2026-06-30T00:00:00Z",
        "additions": 120,
        "deletions": 10,
        "isDraft": False,
        "headRefName": "feat/widget",
        "url": "https://github.com/synaptent/aragora/pull/1",
    }
    pr.update(overrides)
    return pr


def _branch(**overrides: Any) -> dict[str, Any]:
    branch: dict[str, Any] = {
        "name": "feat/orphan-widget",
        "sha": "abc1234",
        "merged": False,
        "orphaned": False,
        "ahead_count": 3,
        "committed_at": "2026-06-01T00:00:00+00:00",
    }
    branch.update(overrides)
    return branch


def _item(kind: str = "pr", identifier: str = "#42", **kw: Any) -> mod.HarvestItem:
    return mod.HarvestItem(
        kind, identifier, kw.pop("title", "feat: add widget"), mod.CLASS_SALVAGE, "reason", **kw
    )


class TestClassifyPR:
    def test_merged_pr_is_learned_pattern(self):
        classification, reason = mod.classify_pr(_pr(mergedAt="2026-06-29T12:00:00Z"))
        assert classification == mod.CLASS_LEARNED
        assert "merged" in reason.lower()

    def test_closed_feature_pr_with_additive_diff_is_salvage(self):
        pr = _pr(title="feat(routing): pareto optimizer", additions=200, deletions=20)
        assert mod.classify_pr(pr)[0] == mod.CLASS_SALVAGE

    def test_closed_trivial_pr_is_write_off(self):
        pr = _pr(title="fix: bump lockfile", additions=4, deletions=4)
        assert mod.classify_pr(pr)[0] == mod.CLASS_WRITEOFF

    def test_closed_draft_pr_is_write_off(self):
        assert (
            mod.classify_pr(_pr(title="feat: half-finished", isDraft=True))[0] == mod.CLASS_WRITEOFF
        )

    def test_closed_non_feature_churn_is_write_off(self):
        pr = _pr(title="fix(reconcile): patch proof path again", additions=300)
        assert mod.classify_pr(pr)[0] == mod.CLASS_WRITEOFF


class TestClassifyBranch:
    def test_merged_branch_is_learned_pattern(self):
        classification, reason = mod.classify_branch(_branch(merged=True))
        assert classification == mod.CLASS_LEARNED
        assert "main" in reason.lower()

    def test_orphaned_branch_is_write_off(self):
        classification, reason = mod.classify_branch(_branch(orphaned=True))
        assert classification == mod.CLASS_WRITEOFF
        assert "merge-base" in reason.lower() or "orphan" in reason.lower()

    def test_stale_feature_branch_with_unique_commits_is_salvage(self):
        branch = _branch(name="feat/goals-store", ahead_count=5)
        assert mod.classify_branch(branch)[0] == mod.CLASS_SALVAGE

    def test_stale_non_feature_branch_is_write_off(self):
        assert mod.classify_branch(_branch(name="codex/settle-retry-17"))[0] == mod.CLASS_WRITEOFF

    def test_branch_with_no_unique_commits_is_write_off(self):
        branch = _branch(name="feat/empty", ahead_count=0)
        assert mod.classify_branch(branch)[0] == mod.CLASS_WRITEOFF


class TestSalvageIssueFormat:
    def test_body_uses_boss_loop_sections(self):
        issue = mod.build_salvage_issue(
            _item(url="https://github.com/synaptent/aragora/pull/42", head_sha="abc1234")
        )
        assert issue["title"]
        for section in ("## Files", "## Acceptance", "## Constraints"):
            assert section in issue["body"]

    def test_body_carries_provenance_marker(self):
        item = _item(kind="branch", identifier="feat/goals-store", head_sha="deadbee")
        issue = mod.build_salvage_issue(item)
        assert "harvest-source: branch:feat/goals-store" in issue["body"]
        assert "deadbee" in issue["body"]


class TestWipCap:
    def test_cap_splits_without_dropping(self):
        items = [_item(identifier=f"#{i}") for i in range(7)]
        to_file, deferred = mod.apply_wip_cap(items, max_issues=5)
        assert len(to_file) == 5
        assert len(deferred) == 2
        # Nothing silently dropped, order preserved.
        assert [i.identifier for i in to_file + deferred] == [f"#{i}" for i in range(7)]

    def test_zero_cap_defers_everything(self):
        to_file, deferred = mod.apply_wip_cap([_item()], max_issues=0)
        assert to_file == []
        assert len(deferred) == 1


class TestLedger:
    def test_append_and_reload_filed_sources(self, tmp_path: Path):
        ledger = tmp_path / "harvest_ledger.jsonl"
        mod.append_ledger(
            ledger,
            {
                "timestamp": "2026-07-01T00:00:00+00:00",
                "counts": {mod.CLASS_SALVAGE: 1},
                "issues_filed": [{"source": "pr:#42", "url": "https://x/issues/1"}],
            },
        )
        mod.append_ledger(ledger, {"timestamp": "t2", "counts": {}, "issues_filed": []})
        lines = ledger.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["counts"][mod.CLASS_SALVAGE] == 1
        assert mod.load_filed_sources(ledger) == {"pr:#42"}

    def test_load_filed_sources_missing_file(self, tmp_path: Path):
        assert mod.load_filed_sources(tmp_path / "nope.jsonl") == set()


class TestGhGuard:
    def test_destructive_gh_subcommands_are_refused(self):
        for argv in (
            ["pr", "close", "42"],
            ["pr", "merge", "42"],
            ["issue", "close", "42"],
            ["pr", "comment", "42", "--body", "x"],
            ["api", "-X", "DELETE", "repos/o/r/git/refs/heads/b"],
        ):
            with pytest.raises(RuntimeError):
                mod.run_gh(argv)


class TestReceiptFalsificationFollowups:
    def test_dry_run_reports_expired_falsification_checks_without_mutation(self, harness):
        receipt_due = {
            "receipt_id": "r-due",
            "falsification": {
                "observation": "Trial-to-paid conversion stays below 8%.",
                "owner": "growth",
                "source": "billing dashboard",
                "check_by": "2026-07-01",
            },
        }
        receipt_future = {
            "receipt_id": "r-future",
            "falsification": {
                "observation": "Latency exceeds 600ms.",
                "check_by": "2026-08-01",
            },
        }

        result = mod.run_harvest(
            repo="synaptent/aragora",
            repo_root=Path("."),
            ledger_path=harness["ledger"],
            signal_log=harness["signal_log"],
            apply=False,
            receipt_followups=[receipt_due, receipt_future],
            now=datetime(2026, 7, 2, tzinfo=timezone.utc),
        )

        assert harness["gh_calls"] == []
        assert result["receipt_followups"] == [
            {
                "receipt_id": "r-due",
                "observation": "Trial-to-paid conversion stays below 8%.",
                "owner": "growth",
                "source": "billing dashboard",
                "check_by": "2026-07-01",
                "reason": "falsification check_by is due",
            }
        ]


@pytest.fixture
def harness(monkeypatch, tmp_path: Path):
    """Mock all gh/git discovery and record write attempts."""
    prs = [
        _pr(number=1, title="feat: merged thing", mergedAt="2026-06-29T00:00:00Z"),
        _pr(number=2, title="feat(goals): salvageable", additions=150, deletions=10),
        _pr(number=3, title="chore: churn", additions=2, deletions=2),
    ]
    branches = [
        _branch(name="feat/stranded-value", ahead_count=4),
        _branch(name="codex/orphan-1", orphaned=True),
        _branch(name="codex/landed", merged=True),
    ]
    gh_calls: list[list[str]] = []

    monkeypatch.setattr(mod, "fetch_recent_prs", lambda **kw: prs)
    monkeypatch.setattr(mod, "fetch_stale_branches", lambda **kw: branches)
    monkeypatch.setattr(mod, "fetch_open_pr_head_refs", lambda **kw: set())

    class FakeProc:
        returncode = 0
        stdout = "https://github.com/synaptent/aragora/issues/999\n"
        stderr = ""

    def fake_run_gh(args: list[str], timeout: int = 60) -> Any:
        gh_calls.append(list(args))
        return FakeProc()

    monkeypatch.setattr(mod, "run_gh", fake_run_gh)
    return {
        "gh_calls": gh_calls,
        "ledger": tmp_path / "ledger.jsonl",
        "signal_log": tmp_path / "signals.jsonl",
    }


def _run(harness: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "repo": "synaptent/aragora",
        "repo_root": Path("."),
        "since_days": 7,
        "max_issues": 5,
        "max_branches": 50,
        "branch_stale_days": 14,
        "ledger_path": harness["ledger"],
        "signal_log": harness["signal_log"],
        "apply": False,
    }
    kwargs.update(overrides)
    return mod.run_harvest(**kwargs)


class TestRunHarvestDryRun:
    def test_classifies_all_items(self, harness):
        result = _run(harness)
        assert result["mode"] == "dry-run"
        counts = result["counts"]
        assert counts[mod.CLASS_LEARNED] == 2  # merged PR + merged branch
        assert counts[mod.CLASS_SALVAGE] == 2  # PR #2 + feat/stranded-value
        assert counts[mod.CLASS_WRITEOFF] == 2  # churn PR + orphaned branch
        assert counts["total"] == 6

    def test_dry_run_never_writes(self, harness):
        result = _run(harness)
        assert harness["gh_calls"] == []
        assert not harness["ledger"].exists()
        assert not harness["signal_log"].exists()
        assert result["issues_filed"] == []
        assert len(result["salvage"]["to_file"]) == 2  # still rendered for inspection


def _ledger_records(ledger: Path, event: str | None = None) -> list[dict[str, Any]]:
    records = [json.loads(line) for line in ledger.read_text().strip().splitlines()]
    return [r for r in records if event is None or r.get("event") == event]


class TestRunHarvestApply:
    def test_apply_files_issues_and_appends_ledger(self, harness):
        result = _run(harness, apply=True)
        assert result["mode"] == "apply"
        creates = [c for c in harness["gh_calls"] if c[:2] == ["issue", "create"]]
        assert len(creates) == 2
        assert len(result["issues_filed"]) == 2
        # Each filed issue is ledgered immediately, then signals, then summary.
        assert len(_ledger_records(harness["ledger"], "issue_filed")) == 2
        summaries = _ledger_records(harness["ledger"], "run_summary")
        assert len(summaries) == 1
        assert summaries[0]["counts"]["total"] == 6
        assert len(summaries[0]["issues_filed"]) == 2

    def test_apply_respects_wip_cap_and_records_deferred(self, harness):
        result = _run(harness, apply=True, max_issues=1)
        creates = [c for c in harness["gh_calls"] if c[:2] == ["issue", "create"]]
        assert len(creates) == 1
        assert len(result["salvage"]["deferred"]) == 1
        summary = _ledger_records(harness["ledger"], "run_summary")[0]
        assert len(summary["deferred"]) == 1  # deferred is never silently dropped

    def test_mid_batch_gh_failure_leaves_ledger_true(self, harness, monkeypatch):
        """First create succeeds, second fails: the success is still ledgered
        and the next run dedups it instead of re-filing a duplicate."""
        calls = {"n": 0}

        class Ok:
            returncode = 0
            stdout = "https://github.com/synaptent/aragora/issues/901\n"
            stderr = ""

        class Boom:
            returncode = 1
            stdout = ""
            stderr = "HTTP 502"

        def flaky_run_gh(args: list[str], timeout: int = 60) -> Any:
            harness["gh_calls"].append(list(args))
            calls["n"] += 1
            return Ok() if calls["n"] == 1 else Boom()

        monkeypatch.setattr(mod, "run_gh", flaky_run_gh)
        with pytest.raises(RuntimeError):
            _run(harness, apply=True)
        filed = _ledger_records(harness["ledger"], "issue_filed")
        assert len(filed) == 1  # the success survived the mid-batch failure
        first_source = filed[0]["issues_filed"][0]["source"]

        def healthy_run_gh(args: list[str], timeout: int = 60) -> Any:
            harness["gh_calls"].append(list(args))
            return Ok()

        # Second run with healthy gh: the ledgered issue is NOT re-filed.
        monkeypatch.setattr(mod, "run_gh", healthy_run_gh)
        result = _run(harness, apply=True)
        refiled = [f["source"] for f in result["issues_filed"]]
        assert first_source not in refiled
        assert len(refiled) == 1  # only the remaining candidate

    def test_apply_emits_learned_signals(self, harness):
        result = _run(harness, apply=True)
        assert result["signals_emitted"] == 2
        lines = harness["signal_log"].read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["source_loop"] == "harvest"

    def test_double_apply_emits_no_duplicate_signals(self, harness):
        first = _run(harness, apply=True)
        second = _run(harness, apply=True)
        assert first["signals_emitted"] == 2
        assert second["signals_emitted"] == 0
        # Same window twice: the learner input is never double-counted.
        assert len(harness["signal_log"].read_text().strip().splitlines()) == 2

    def test_empty_stdout_gh_success_is_handled(self, harness, monkeypatch):
        class EmptyOk:
            returncode = 0
            stdout = ""
            stderr = ""

        def empty_run_gh(args: list[str], timeout: int = 60) -> Any:
            harness["gh_calls"].append(list(args))
            return EmptyOk()

        monkeypatch.setattr(mod, "run_gh", empty_run_gh)
        result = _run(harness, apply=True)  # must not raise IndexError
        assert all(f["url"] == "" for f in result["issues_filed"])

    def test_apply_skips_sources_already_filed(self, harness):
        mod.append_ledger(
            harness["ledger"],
            {"timestamp": "t", "counts": {}, "issues_filed": [{"source": "pr:#2"}]},
        )
        result = _run(harness, apply=True)
        creates = [c for c in harness["gh_calls"] if c[:2] == ["issue", "create"]]
        assert len(creates) == 1  # only the branch candidate; pr:#2 deduped
        assert len(result["salvage"]["skipped_already_filed"]) == 1

    def test_apply_only_ever_creates_issues(self, harness):
        _run(harness, apply=True)
        for call in harness["gh_calls"]:
            # The only gh invocation an apply run may make is `gh issue create`;
            # close/delete/comment/merge authority stays with the cleanup plan.
            assert call[:2] == ["issue", "create"]


class TestOriginFreshness:
    @staticmethod
    def _proc(rc: int, out: str) -> Any:
        class P:
            returncode = rc
            stdout = out
            stderr = ""

        return P()

    def test_stale_origin_main_fails_loud(self, monkeypatch):
        def fake_run_git(args: list[str], repo_root: Path, timeout: int = 60) -> Any:
            if args[0] == "rev-parse":
                return self._proc(0, "aaa111\n")
            return self._proc(0, "bbb222\trefs/heads/main\n")

        monkeypatch.setattr(mod, "run_git", fake_run_git)
        with pytest.raises(RuntimeError, match="stale"):
            mod._verify_origin_fresh(Path("."))

    def test_fresh_origin_main_passes(self, monkeypatch):
        def fake_run_git(args: list[str], repo_root: Path, timeout: int = 60) -> Any:
            if args[0] == "rev-parse":
                return self._proc(0, "aaa111\n")
            return self._proc(0, "aaa111\trefs/heads/main\n")

        monkeypatch.setattr(mod, "run_git", fake_run_git)
        mod._verify_origin_fresh(Path("."))  # must not raise


class TestMain:
    def test_script_help_starts_without_repo_package_on_pythonpath(self, tmp_path: Path):
        repo_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env["PYTHONPATH"] = ""

        proc = subprocess.run(
            [sys.executable, str(repo_root / "scripts" / "harvest_outcomes.py"), "--help"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        assert proc.returncode == 0, proc.stderr
        assert "Harvest engine" in proc.stdout

    def test_defaults(self):
        args = mod.build_parser().parse_args([])
        assert args.since_days == 7
        assert args.max_issues == 5
        assert args.apply is False

    def test_help_description_is_first_nonempty_docstring_line(self):
        description = mod.build_parser().description
        assert description and description.strip()
        assert "Harvest engine" in description

    def test_json_output(self, harness, capsys, monkeypatch):
        monkeypatch.setattr(mod, "run_harvest", lambda **kw: {"mode": "dry-run", "counts": {}})
        rc = mod.main(["--json", "--ledger-path", str(harness["ledger"])])
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["mode"] == "dry-run"
