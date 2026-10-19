"""Unit tests for scripts/label_unlabeled_issues.py.

The script is a one-shot backlog labeler; every ``gh`` launch is recorded by a
stub so the tests can prove the dry run needs a constant number of launches,
``--apply`` issues exactly one POST per issue, and a failing ``gh`` call aborts
the run immediately.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = REPO_ROOT / "scripts" / "label_unlabeled_issues.py"

_spec = importlib.util.spec_from_file_location("label_unlabeled_issues", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
mod = importlib.util.module_from_spec(_spec)
# Registered before exec: the script's dataclasses resolve their module by name.
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)

MAPPING = {"dockerfile": "deployment", "traceback": "bug", "receipt": "receipts"}

ISSUES = [
    {
        "number": 1,
        "title": "Dockerfile broken",
        "body": "",
        "labels": [],
        "createdAt": "2026-01-01T00:00:00Z",
    },
    {
        "number": 2,
        "title": "nothing",
        "body": "",
        "labels": [],
        "createdAt": "2026-01-02T00:00:00Z",
    },
    {
        "number": 3,
        "title": "labelled",
        "body": "",
        "labels": [{"name": "bug"}],
        "createdAt": "2026-01-03T00:00:00Z",
    },
    {
        "number": 4,
        "title": "Dockerfile protected",
        "body": "",
        "labels": [{"name": "triage:protected"}],
        "createdAt": "2026-01-04T00:00:00Z",
    },
    {
        "number": 5,
        "title": "receipt traceback",
        "body": "",
        "labels": [],
        "createdAt": "2026-01-05T00:00:00Z",
    },
]


class _Gh:
    """Records every gh launch; serves the issue list and label list."""

    def __init__(self, *, fail_on_post: bool = False):
        self.launches: list[list[str]] = []
        self.fail_on_post = fail_on_post

    def __call__(self, args, *, input=None):  # noqa: A002 - mirrors subprocess API
        self.launches.append(list(args))
        if args[1] == "issue" and args[2] == "list":
            return mod.GhResult(0, json.dumps(ISSUES), "")
        if args[1] == "label":
            names = sorted({*MAPPING.values(), "triage:protected", "triage:unverified"})
            return mod.GhResult(0, json.dumps([{"name": n} for n in names]), "")
        if "POST" in args:
            if self.fail_on_post:
                return mod.GhResult(1, "", "HTTP 403: forbidden")
            return mod.GhResult(0, "[]", "")
        raise AssertionError(f"unexpected gh call: {args}")

    @property
    def posts(self) -> list[list[str]]:
        return [a for a in self.launches if "POST" in a]


@pytest.fixture
def map_path(tmp_path: Path) -> Path:
    p = tmp_path / "map.json"
    p.write_text(json.dumps({"version": 1, "keywords": MAPPING}), encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)


# --- planning ---------------------------------------------------------------------


def test_plan_skips_labelled_protected_and_unmatched():
    plan = mod.build_plan(ISSUES, MAPPING, fallback="triage:unverified")
    assert [(p.number, p.labels) for p in plan] == [
        (1, ["deployment"]),
        (2, ["triage:unverified"]),
        (5, ["bug", "receipts"]),
    ]


def test_plan_without_fallback_leaves_unmatched_alone():
    plan = mod.build_plan(ISSUES, MAPPING, fallback=None)
    assert [p.number for p in plan] == [1, 5]


def test_plan_is_empty_when_everything_is_labelled():
    issues = [dict(i, labels=[{"name": "bug"}]) for i in ISSUES]
    assert mod.build_plan(issues, MAPPING, fallback="triage:unverified") == []


# --- dry run ----------------------------------------------------------------------


def test_dry_run_is_default_prints_plan_and_launches_gh_at_most_twice(
    map_path, monkeypatch, capsys
):
    gh = _Gh()
    monkeypatch.setattr(mod, "run_gh", gh)
    rc = mod.main(["--map", str(map_path)])
    assert rc == 0
    assert gh.posts == []
    assert len(gh.launches) <= 3
    out = capsys.readouterr().out
    assert "#1" in out and "deployment" in out
    assert "#4" not in out
    assert "3 issue(s) to label" in out
    assert "dry run" in out.lower()


def test_dry_run_flag_is_accepted_explicitly(map_path, monkeypatch):
    gh = _Gh()
    monkeypatch.setattr(mod, "run_gh", gh)
    assert mod.main(["--map", str(map_path), "--dry-run"]) == 0
    assert gh.posts == []


def test_dry_run_and_apply_are_mutually_exclusive(map_path):
    with pytest.raises(SystemExit) as exc:
        mod.main(["--map", str(map_path), "--dry-run", "--apply"])
    assert exc.value.code == 2


def test_unknown_target_label_exits_2_before_any_mutation(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"version": 1, "keywords": {"dockerfile": "no-such-label"}}), encoding="utf-8"
    )
    gh = _Gh()
    monkeypatch.setattr(mod, "run_gh", gh)
    assert mod.main(["--map", str(bad), "--apply"]) == 2
    assert gh.posts == []


# --- apply ------------------------------------------------------------------------


def test_apply_posts_exactly_once_per_issue(map_path, monkeypatch, capsys):
    gh = _Gh()
    monkeypatch.setattr(mod, "run_gh", gh)
    assert mod.main(["--map", str(map_path), "--apply"]) == 0
    assert len(gh.posts) == 3
    endpoints = [a[a.index("POST") + 1] for a in gh.posts]
    assert endpoints == [
        "repos/synaptent/aragora/issues/1/labels",
        "repos/synaptent/aragora/issues/2/labels",
        "repos/synaptent/aragora/issues/5/labels",
    ]
    assert "applied 3" in capsys.readouterr().out


def test_apply_sleeps_between_writes(map_path, monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(mod.time, "sleep", sleeps.append)
    monkeypatch.setattr(mod, "run_gh", _Gh())
    assert mod.main(["--map", str(map_path), "--apply"]) == 0
    assert sleeps == [0.5, 0.5]


def test_apply_fails_fast_on_first_gh_error(map_path, monkeypatch, capsys):
    gh = _Gh(fail_on_post=True)
    monkeypatch.setattr(mod, "run_gh", gh)
    assert mod.main(["--map", str(map_path), "--apply"]) == 1
    assert len(gh.posts) == 1
    assert "403" in capsys.readouterr().err


def test_list_failure_exits_1(map_path, monkeypatch):
    def broken(args, *, input=None):  # noqa: A002
        return mod.GhResult(1, "", "gh: not logged in")

    monkeypatch.setattr(mod, "run_gh", broken)
    assert mod.main(["--map", str(map_path)]) == 1


def test_help_documents_modes(capsys):
    with pytest.raises(SystemExit) as exc:
        mod.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--dry-run" in out and "--apply" in out and "default" in out
    assert "triage:protected" in out
