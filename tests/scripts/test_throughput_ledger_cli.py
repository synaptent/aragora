"""Snapshot locking + dedupe for scripts/throughput_ledger.py (#9048 openai [P2])."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "throughput_ledger.py"


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("throughput_ledger_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fake_prs(mod, monkeypatch):
    monkeypatch.setattr(
        mod,
        "_gh_merged_prs",
        lambda limit, *, repo_root=".", lookback_days=90: [
            {
                "number": 42,
                "title": "feat: x",
                "mergedAt": "2026-07-09T00:00:00Z",
                "labels": [],
                "files": [{"path": "aragora/debate/a.py", "additions": 5, "deletions": 1}],
            }
        ],
    )


def test_snapshot_dedupes_across_runs_and_takes_lock(mod, monkeypatch, tmp_path):
    _fake_prs(mod, monkeypatch)
    for _ in range(2):
        rc = mod.main(["--repo-root", str(tmp_path), "snapshot", "--limit", "5"])
        assert rc == 0
    from aragora.nomic.throughput import ThroughputLedger

    ledger = ThroughputLedger(tmp_path)
    merges = [r for r in ledger.records() if r.kind == "merge"]
    assert len(merges) == 1  # second run deduped under the lock
    assert ledger.path.with_suffix(ledger.path.suffix + ".lock").exists()


def test_gh_merged_prs_searches_by_merged_day_and_sorts_by_merged_at(mod, monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[:4] == ["gh", "repo", "view", "--json"]:
            return SimpleNamespace(stdout=json.dumps({"nameWithOwner": "synaptent/aragora"}))
        if cmd[:3] == ["gh", "search", "prs"]:
            return SimpleNamespace(
                stdout=json.dumps(
                    [
                        {"url": "https://github.com/synaptent/aragora/pull/1"},
                        {"url": "https://github.com/synaptent/aragora/pull/2"},
                    ]
                )
            )
        if cmd[:3] == ["gh", "pr", "view"]:
            number = int(cmd[3])
            merged_at = {
                1: "2026-07-08T00:00:00Z",
                2: "2026-07-09T00:00:00Z",
            }[number]
            title = {1: "older", 2: "newer"}[number]
            return SimpleNamespace(
                stdout=json.dumps(
                    {
                        "number": number,
                        "title": title,
                        "mergedAt": merged_at,
                        "labels": [],
                        "files": [],
                    }
                )
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(mod, "_today_utc", lambda: mod.date(2026, 7, 9))
    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    prs = mod._gh_merged_prs(2, repo_root=str(tmp_path), lookback_days=1)

    assert [pr["number"] for pr in prs] == [2, 1]
    search_cmd, search_kwargs = calls[1]
    assert search_cmd[:3] == ["gh", "search", "prs"]
    assert "--merged-at" in search_cmd
    assert "2026-07-09" in search_cmd
    assert "url" in search_cmd
    assert "sort:updated-desc" not in search_cmd
    assert search_kwargs["cwd"] == str(tmp_path)


def test_gh_merged_pr_details_paginates_when_files_truncated(mod, monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["gh", "pr", "view"]:
            return SimpleNamespace(
                stdout=json.dumps(
                    {
                        "number": 7,
                        "title": "big",
                        "mergedAt": "2026-07-09T00:00:00Z",
                        "labels": [],
                        "files": [{"path": "a.py", "additions": 1, "deletions": 0}],
                        "changedFiles": 3,
                    }
                )
            )
        if cmd[:2] == ["gh", "api"]:
            assert "--paginate" in cmd
            return SimpleNamespace(
                stdout=json.dumps(
                    [
                        [
                            {"filename": "a.py", "additions": 1, "deletions": 0},
                            {"filename": "b.py", "additions": 2, "deletions": 1},
                        ],
                        [{"filename": "c.py", "additions": 0, "deletions": 5}],
                    ]
                )
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    pr = mod._gh_merged_pr_details(7, repo="synaptent/aragora", repo_root=str(tmp_path))

    assert [f["path"] for f in pr["files"]] == ["a.py", "b.py", "c.py"]
    assert pr["files"][2]["deletions"] == 5
    assert any(cmd[:2] == ["gh", "api"] for cmd in calls)


def test_gh_merged_pr_details_trusts_complete_file_list(mod, monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["gh", "pr", "view"]:
            return SimpleNamespace(
                stdout=json.dumps(
                    {
                        "number": 8,
                        "title": "small",
                        "mergedAt": "2026-07-09T00:00:00Z",
                        "labels": [],
                        "files": [{"path": "a.py", "additions": 1, "deletions": 0}],
                        "changedFiles": 1,
                    }
                )
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    pr = mod._gh_merged_pr_details(8, repo="synaptent/aragora", repo_root=str(tmp_path))

    assert [f["path"] for f in pr["files"]] == ["a.py"]


def test_gh_merged_prs_does_not_let_updated_order_truncate_newer_merges(mod, monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[:4] == ["gh", "repo", "view", "--json"]:
            return SimpleNamespace(stdout=json.dumps({"nameWithOwner": "synaptent/aragora"}))
        if cmd[:3] == ["gh", "search", "prs"]:
            # Simulate search returning an older PR before a newer one. The
            # implementation must fetch details and sort by mergedAt before
            # applying the caller's limit.
            return SimpleNamespace(
                stdout=json.dumps(
                    [
                        {"url": "https://github.com/synaptent/aragora/pull/10"},
                        {"url": "https://github.com/synaptent/aragora/pull/11"},
                    ]
                )
            )
        if cmd[:3] == ["gh", "pr", "view"]:
            number = int(cmd[3])
            merged_at = {
                10: "2026-07-08T23:00:00Z",
                11: "2026-07-09T01:00:00Z",
            }[number]
            return SimpleNamespace(
                stdout=json.dumps(
                    {
                        "number": number,
                        "title": f"pr {number}",
                        "mergedAt": merged_at,
                        "labels": [],
                        "files": [],
                    }
                )
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(mod, "_today_utc", lambda: mod.date(2026, 7, 9))
    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    prs = mod._gh_merged_prs(1, repo_root=str(tmp_path), lookback_days=1)

    assert [pr["number"] for pr in prs] == [11]
    assert any(call[0][:3] == ["gh", "pr", "view"] for call in calls)


def test_gh_merged_prs_scans_older_merged_days_until_limit_is_met(mod, monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        if cmd[:4] == ["gh", "repo", "view", "--json"]:
            return SimpleNamespace(stdout=json.dumps({"nameWithOwner": "synaptent/aragora"}))
        if cmd[:3] == ["gh", "search", "prs"]:
            day = cmd[cmd.index("--merged-at") + 1]
            if day == "2026-07-09":
                return SimpleNamespace(stdout=json.dumps([]))
            if day == "2026-07-08":
                return SimpleNamespace(
                    stdout=json.dumps([{"url": "https://github.com/synaptent/aragora/pull/8"}])
                )
            return SimpleNamespace(stdout=json.dumps([]))
        if cmd[:3] == ["gh", "pr", "view"]:
            return SimpleNamespace(
                stdout=json.dumps(
                    {
                        "number": 8,
                        "title": "older day",
                        "mergedAt": "2026-07-08T12:00:00Z",
                        "labels": [],
                        "files": [],
                    }
                )
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(mod, "_today_utc", lambda: mod.date(2026, 7, 9))
    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    prs = mod._gh_merged_prs(1, repo_root=str(tmp_path), lookback_days=2)

    assert [pr["number"] for pr in prs] == [8]
