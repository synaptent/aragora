from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from aragora.swarm.issue_scanner import BossIssueCandidate
from aragora.swarm.roadmap_priority import RoadmapPriorityPolicy
from scripts import generate_boss_issues as mod

_FETCH_CLOSURE_COUNTS_7D = mod.fetch_closure_counts_7d


@pytest.fixture(autouse=True)
def _healthy_closure_counts(monkeypatch):
    """Keep main() tests off the network: default the closure-floor counts
    boundary to a healthy trailing-7d ratio. Tests that exercise the floor
    override this explicitly."""
    monkeypatch.setattr(mod, "fetch_closure_counts_7d", lambda repo: (1, 1))


def _candidate(name: str, *, file_scope: list[str]) -> BossIssueCandidate:
    return BossIssueCandidate(
        category="test_coverage",
        title=f"Add tests for {name}",
        description=f"Create tests covering {name}.",
        file_scope=file_scope,
        new_files=[f"tests/test_{name}.py"],
        validation_command=f"pytest tests/test_{name}.py -v",
        acceptance_criteria=["All tests pass"],
    )


def _category_candidate(category: str, *, rel: str) -> BossIssueCandidate:
    validation_command = (
        f"pytest tests/test_{Path(rel).stem}.py -v"
        if category == "test_coverage"
        else f"ruff check {rel}"
    )
    new_files = [f"tests/test_{Path(rel).stem}.py"] if category == "test_coverage" else []
    return BossIssueCandidate(
        category=category,
        title=f"Candidate for {category}",
        description=f"Improve `{rel}` in a bounded way.",
        file_scope=[rel],
        new_files=new_files,
        validation_command=validation_command,
        acceptance_criteria=[f"`{validation_command}` passes"],
    )


def test_main_dry_run_fetches_and_filters_like_real_mode(
    monkeypatch,
    capsys,
) -> None:
    duplicate = _candidate("duplicate_module", file_scope=["aragora/duplicate_module.py"])
    pr_conflict = _candidate("pr_conflict_module", file_scope=["aragora/pr_conflict_module.py"])
    eligible = _candidate("eligible_module", file_scope=["aragora/eligible_module.py"])

    scan_calls: list[tuple[object, object, object]] = []
    fetch_existing_calls: list[str] = []
    fetch_pr_calls: list[str] = []
    create_calls: list[tuple[str, str, str, str]] = []

    monkeypatch.setattr(
        mod,
        "scan_all",
        lambda repo_root, categories=None, min_success_rate=0.3: (
            scan_calls.append((repo_root, categories, min_success_rate))
            or [duplicate, pr_conflict, eligible]
        ),
    )
    monkeypatch.setattr(
        mod,
        "fetch_existing_boss_issues",
        lambda repo: (
            fetch_existing_calls.append(repo)
            or [{"title": "Other issue", "body": f"<!-- fingerprint:{duplicate.fingerprint} -->"}]
        ),
    )
    monkeypatch.setattr(
        mod,
        "fetch_open_pr_files",
        lambda repo: (fetch_pr_calls.append(repo) or {"aragora/pr_conflict_module.py"}),
    )
    monkeypatch.setattr(mod, "validate_body", lambda body: (True, ""))
    monkeypatch.setattr(
        mod,
        "create_github_issue",
        lambda repo, title, body, label, **kwargs: (
            create_calls.append((repo, title, body, label, kwargs.get("extra_labels", []))) or True
        ),
    )
    monkeypatch.setattr(mod, "load_roadmap_priority_policy", lambda repo_root: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_boss_issues.py",
            "--repo",
            "org/repo",
            "--dry-run",
            "--max-issues",
            "5",
            "--label",
            "lane:test",
        ],
    )

    mod.main()

    out = capsys.readouterr().out
    assert scan_calls
    assert scan_calls[0][2] == 0.3
    assert fetch_existing_calls == ["org/repo"]
    assert fetch_pr_calls == ["org/repo"]
    assert "DRY RUN — would create 1 issues" in out
    assert eligible.title in out
    assert (
        "Skipped: 1 duplicates, 1 PR conflicts, 0 canonical priority blocks, "
        "0 validation failures" in out
    )
    assert not create_calls


def test_main_create_mode_trims_to_max_and_writes_fingerprint(
    monkeypatch,
    capsys,
) -> None:
    first = _candidate("first_module", file_scope=["aragora/first_module.py"])
    second = _candidate("second_module", file_scope=["aragora/second_module.py"])

    created: list[tuple[str, str, str, str]] = []
    monkeypatch.setattr(
        mod,
        "scan_all",
        lambda repo_root, categories=None, min_success_rate=0.3: [first, second],
    )
    monkeypatch.setattr(mod, "fetch_existing_boss_issues", lambda repo: [])
    monkeypatch.setattr(mod, "fetch_open_pr_files", lambda repo: set())
    monkeypatch.setattr(mod, "validate_body", lambda body: (True, ""))
    monkeypatch.setattr(mod, "load_roadmap_priority_policy", lambda repo_root: None)
    monkeypatch.setattr(
        mod,
        "create_github_issue",
        lambda repo, title, body, label, **kwargs: (
            created.append((repo, title, body, label, kwargs.get("extra_labels", []))) or True
        ),
    )
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_boss_issues.py",
            "--repo",
            "org/repo",
            "--max-issues",
            "1",
            "--label",
            "lane:test",
        ],
    )

    mod.main()

    out = capsys.readouterr().out
    assert "Done: 1 created, 0 failed" in out
    assert len(created) == 1
    repo, title, body, label, extra_labels = created[0]
    assert repo == "org/repo"
    assert title == first.title
    assert label == "lane:test"
    assert extra_labels == ["autonomous"]
    assert f"<!-- fingerprint:{first.fingerprint} -->" in body


def test_main_passes_explicit_min_success_rate(monkeypatch, capsys) -> None:
    eligible = _candidate("eligible_module", file_scope=["aragora/eligible_module.py"])
    scan_calls: list[tuple[object, object, object]] = []

    monkeypatch.setattr(
        mod,
        "scan_all",
        lambda repo_root, categories=None, min_success_rate=0.3: (
            scan_calls.append((repo_root, categories, min_success_rate)) or [eligible]
        ),
    )
    monkeypatch.setattr(mod, "fetch_existing_boss_issues", lambda repo: [])
    monkeypatch.setattr(mod, "fetch_open_pr_files", lambda repo: set())
    monkeypatch.setattr(mod, "validate_body", lambda body: (True, ""))
    monkeypatch.setattr(mod, "load_roadmap_priority_policy", lambda repo_root: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_boss_issues.py",
            "--dry-run",
            "--min-success-rate",
            "0.5",
        ],
    )

    mod.main()

    _ = capsys.readouterr()
    assert scan_calls
    assert scan_calls[0][2] == 0.5


def test_main_boss_ready_requires_explicit_do_now_priority(monkeypatch, capsys) -> None:
    unknown = _candidate("eligible_module", file_scope=["aragora/eligible_module.py"])

    monkeypatch.setattr(
        mod,
        "scan_all",
        lambda repo_root, categories=None, min_success_rate=0.3: [unknown],
    )
    monkeypatch.setattr(mod, "fetch_existing_boss_issues", lambda repo: [])
    monkeypatch.setattr(mod, "fetch_open_pr_files", lambda repo: set())
    monkeypatch.setattr(mod, "validate_body", lambda body: (True, ""))
    monkeypatch.setattr(
        mod,
        "load_roadmap_priority_policy",
        lambda repo_root: RoadmapPriorityPolicy(
            do_now=frozenset({"TW-01"}),
            delay=frozenset({"BC-07"}),
            avoid=frozenset({"CS-04"}),
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_boss_issues.py",
            "--dry-run",
            "--label",
            "boss-ready",
        ],
    )

    mod.main()

    out = capsys.readouterr().out
    assert "DRY RUN — would create 0 issues" in out
    assert "1 canonical priority blocks" in out


def test_main_non_boss_ready_label_allows_unknown_priority(monkeypatch, capsys) -> None:
    unknown = _candidate("eligible_module", file_scope=["aragora/eligible_module.py"])
    created: list[tuple[str, str, str, str]] = []

    monkeypatch.setattr(
        mod,
        "scan_all",
        lambda repo_root, categories=None, min_success_rate=0.3: [unknown],
    )
    monkeypatch.setattr(mod, "fetch_existing_boss_issues", lambda repo: [])
    monkeypatch.setattr(mod, "fetch_open_pr_files", lambda repo: set())
    monkeypatch.setattr(mod, "validate_body", lambda body: (True, ""))
    monkeypatch.setattr(
        mod,
        "load_roadmap_priority_policy",
        lambda repo_root: RoadmapPriorityPolicy(
            do_now=frozenset({"TW-01"}),
            delay=frozenset({"BC-07"}),
            avoid=frozenset({"CS-04"}),
        ),
    )
    monkeypatch.setattr(
        mod,
        "create_github_issue",
        lambda repo, title, body, label, **kwargs: (
            created.append((repo, title, body, label, kwargs.get("extra_labels", []))) or True
        ),
    )
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_boss_issues.py",
            "--repo",
            "org/repo",
            "--max-issues",
            "1",
            "--label",
            "lane:test",
        ],
    )

    mod.main()

    out = capsys.readouterr().out
    assert "Done: 1 created, 0 failed" in out
    assert created[0][3] == "lane:test"


def test_main_boss_ready_allows_tw02_benchmark_follow_up_without_do_now_code(
    monkeypatch,
    capsys,
) -> None:
    candidate = BossIssueCandidate(
        category="test_coverage",
        title="[TW-02] Restock stale issues in tw-01-bounded-execution-v1 rev-1",
        description=(
            "Refresh benchmark corpus freshness by updating docs/benchmarks/corpus.json "
            "after stale closed issues were detected."
        ),
        file_scope=["docs/benchmarks/corpus.json"],
        new_files=[],
        validation_command="python3 scripts/measure_b0_scorecard.py --json",
        acceptance_criteria=[
            "Recurring benchmark truth publication reports fresh corpus membership."
        ],
    )
    created: list[tuple[str, str, str, str]] = []

    monkeypatch.setattr(
        mod,
        "scan_all",
        lambda repo_root, categories=None, min_success_rate=0.3: [candidate],
    )
    monkeypatch.setattr(mod, "fetch_existing_boss_issues", lambda repo: [])
    monkeypatch.setattr(mod, "fetch_open_pr_files", lambda repo: set())
    monkeypatch.setattr(mod, "validate_body", lambda body: (True, ""))
    monkeypatch.setattr(
        mod,
        "load_roadmap_priority_policy",
        lambda repo_root: RoadmapPriorityPolicy(
            do_now=frozenset({"CS-01", "CS-02", "CS-03"}),
            delay=frozenset({"BC-07"}),
            avoid=frozenset({"CS-04"}),
        ),
    )
    monkeypatch.setattr(
        mod,
        "create_github_issue",
        lambda repo, title, body, label, **kwargs: (
            created.append((repo, title, body, label, kwargs.get("extra_labels", []))) or True
        ),
    )
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_boss_issues.py",
            "--repo",
            "org/repo",
            "--max-issues",
            "1",
            "--label",
            "boss-ready",
        ],
    )

    mod.main()

    out = capsys.readouterr().out
    assert "Done: 1 created, 0 failed" in out
    assert created[0][1] == candidate.title


def test_fetch_existing_boss_issues_includes_fingerprinted_open_issues_without_label_filter(
    monkeypatch,
) -> None:
    seen_cmds: list[list[str]] = []

    def fake_run(cmd: list[str], **_: object) -> SimpleNamespace:
        seen_cmds.append(cmd)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "number": 5529,
                        "title": "Duplicate fingerprint issue",
                        "body": "Task body\n\n<!-- fingerprint:abc123 -->",
                    },
                    {
                        "number": 5574,
                        "title": "Open issue without fingerprint",
                        "body": "Task body without dedupe marker",
                    },
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    issues = mod.fetch_existing_boss_issues("org/repo")

    assert issues == [
        {
            "number": 5529,
            "title": "Duplicate fingerprint issue",
            "body": "Task body\n\n<!-- fingerprint:abc123 -->",
        }
    ]
    assert seen_cmds == [
        [
            "gh",
            "api",
            "--method",
            "GET",
            "repos/org/repo/issues?state=open&per_page=100&page=1",
        ]
    ]


def test_fetch_existing_boss_issues_blocks_on_invalid_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda cmd, **_: SimpleNamespace(returncode=0, stdout=json.dumps({"items": []}), stderr=""),
    )

    with pytest.raises(mod._AdmissionError, match="open issues page 1"):
        mod.fetch_existing_boss_issues("org/repo")


@pytest.mark.parametrize(
    "category",
    ["test_coverage", "broad_exception", "silent_exception", "type_annotation"],
)
def test_format_boss_ready_body_uses_upgrader_for_supported_categories(
    monkeypatch,
    category: str,
) -> None:
    candidate = _category_candidate(category, rel="aragora/swarm/example_module.py")
    calls: list[dict[str, object]] = []

    def _upgrade(title, body, **kwargs):  # noqa: ANN001
        calls.append({"title": title, "body": body, **kwargs})
        return SimpleNamespace(upgraded_body="## Task\n\nUpgraded body")

    monkeypatch.setattr(mod, "upgrade_issue_heuristic", _upgrade)

    body = mod.format_boss_ready_body(candidate)

    assert body.startswith("## Task\n\nUpgraded body")
    assert f"<!-- fingerprint:{candidate.fingerprint} -->" in body
    assert calls[0]["category"] == category
    assert calls[0]["validation_command"] == candidate.validation_command
    assert calls[0]["acceptance_criteria"] == candidate.acceptance_criteria
    assert calls[0]["new_files"] == candidate.new_files


def test_format_boss_ready_body_falls_back_when_non_test_upgrade_is_unavailable(
    monkeypatch,
) -> None:
    candidate = _category_candidate("type_annotation", rel="aragora/swarm/example_module.py")
    monkeypatch.setattr(mod, "upgrade_issue_heuristic", lambda *args, **kwargs: None)

    body = mod.format_boss_ready_body(candidate)

    assert candidate.description in body
    assert "### File Scope" in body
    assert "`aragora/swarm/example_module.py`" in body
    assert candidate.validation_command in body
    assert f"<!-- fingerprint:{candidate.fingerprint} -->" in body


def test_maybe_decompose_candidates_noop_when_disabled(monkeypatch) -> None:
    parent = _candidate("parent_module", file_scope=["aragora/parent_module.py"])

    class UnexpectedBridge:
        def __init__(self, repo_root):  # noqa: D401, ANN001
            raise AssertionError("bridge should not be constructed when disabled")

    monkeypatch.setattr(mod, "DecompositionBridge", UnexpectedBridge)

    result = mod.maybe_decompose_candidates(
        [parent],
        enabled=False,
        max_children_per_parent=5,
        repo_root=mod.REPO_ROOT,
    )

    assert result == [parent]


def test_maybe_decompose_candidates_replaces_parent_when_children_emitted(monkeypatch) -> None:
    parent = _candidate("parent_module", file_scope=["aragora/parent_module.py"])
    child_a = BossIssueCandidate(
        category="test_coverage",
        title="Child A",
        description="Write focused tests for module A with bounded scope and validation.",
        file_scope=["aragora/module_a.py"],
        new_files=["tests/test_module_a.py"],
        validation_command="python3 -m pytest -q tests/test_module_a.py",
    )
    child_b = BossIssueCandidate(
        category="test_coverage",
        title="Child B",
        description="Write focused tests for module B with bounded scope and validation.",
        file_scope=["aragora/module_b.py"],
        new_files=["tests/test_module_b.py"],
        validation_command="python3 -m pytest -q tests/test_module_b.py",
    )
    monkeypatch.setattr(
        mod,
        "format_boss_ready_body",
        lambda candidate: (
            "## Task\n\nAdd comprehensive unit tests.\n\n"
            "### Requirements\n"
            "1. Read the module and identify all public functions.\n"
            "2. Create a test file with broad coverage.\n"
        ),
    )

    class FakeBridge:
        def __init__(self, repo_root):  # noqa: D401, ANN001
            self.repo_root = repo_root

        def decompose_issue_sync_with_stats(self, title, body, *, max_children):  # noqa: ANN001
            assert title == parent.title
            assert "## Task" in body
            assert max_children == 3
            return SimpleNamespace(
                children=[child_a, child_b],
                stats=SimpleNamespace(rejected_candidates=1, sanitizer_rejections=1),
            )

    monkeypatch.setattr(mod, "DecompositionBridge", FakeBridge)

    result = mod.maybe_decompose_candidates(
        [parent],
        enabled=True,
        max_children_per_parent=3,
        repo_root=mod.REPO_ROOT,
    )

    assert result == [child_a, child_b]


def test_maybe_decompose_candidates_keeps_parent_when_child_set_is_not_meaningful(
    monkeypatch,
) -> None:
    parent = _candidate("parent_module", file_scope=["aragora/parent_module.py"])
    single_child = BossIssueCandidate(
        category="test_coverage",
        title="Only child",
        description="Only child with bounded scope and validation command.",
        file_scope=["aragora/module_a.py"],
        validation_command="python3 -m ruff check aragora/module_a.py",
    )
    monkeypatch.setattr(
        mod,
        "format_boss_ready_body",
        lambda candidate: (
            "## Task\n\nAdd comprehensive unit tests.\n\n"
            "### Requirements\n"
            "1. Read the module and identify all public functions.\n"
            "2. Create a test file with broad coverage.\n"
        ),
    )

    class FakeBridge:
        def __init__(self, repo_root):  # noqa: D401, ANN001
            self.repo_root = repo_root

        def decompose_issue_sync_with_stats(self, title, body, *, max_children):  # noqa: ANN001
            return SimpleNamespace(
                children=[single_child],
                stats=SimpleNamespace(rejected_candidates=2, sanitizer_rejections=1),
            )

    monkeypatch.setattr(mod, "DecompositionBridge", FakeBridge)

    result = mod.maybe_decompose_candidates(
        [parent],
        enabled=True,
        max_children_per_parent=5,
        repo_root=mod.REPO_ROOT,
    )

    assert result == [parent]


def test_is_low_quality_parent_skips_bounded_module_aware_issue() -> None:
    candidate = _candidate(
        "analytics_core", file_scope=["aragora/server/handlers/analytics/core.py"]
    )
    body = (
        "## Task\n\n"
        "Write focused unit tests for `aragora/server/handlers/analytics/core.py` (53 lines, 0 public functions).\n\n"
        "**Module purpose:** Analytics Core Module.\n\n"
        "### What to test\n"
        "- happy path behavior\n\n"
        "### Validation\n```bash\npytest tests/test_analytics_core.py -v\n```"
    )

    assert mod.is_low_quality_parent(candidate, body) is False


def test_is_low_quality_parent_detects_generic_template() -> None:
    candidate = _candidate("module", file_scope=["aragora/pkg/module.py"])
    body = (
        "## Task\n\n"
        "Add comprehensive unit tests for `aragora/pkg/module.py`.\n\n"
        "### Requirements\n"
        "1. Read the module and identify all public functions.\n"
        "2. Create a test file with broad coverage.\n"
    )

    assert mod.is_low_quality_parent(candidate, body) is True


def test_maybe_decompose_candidates_with_telemetry_tracks_counts(monkeypatch) -> None:
    low_quality = _candidate("generic_module", file_scope=["aragora/generic_module.py"])
    bounded = _candidate("bounded_module", file_scope=["aragora/bounded_module.py"])
    child_a = _candidate("child_a", file_scope=["aragora/child_a.py"])
    child_b = _candidate("child_b", file_scope=["aragora/child_b.py"])

    original_formatter = mod.format_boss_ready_body

    def fake_format(candidate: BossIssueCandidate) -> str:
        if candidate.title == low_quality.title:
            return (
                "## Task\n\n"
                "Add comprehensive unit tests for `aragora/generic_module.py`.\n\n"
                "### Requirements\n"
                "1. Read the module and identify all public functions.\n"
                "2. Create a test file with broad coverage.\n"
            )
        return original_formatter(candidate)

    class FakeBridge:
        def __init__(self, repo_root):  # noqa: D401, ANN001
            self.repo_root = repo_root

        def decompose_issue_sync_with_stats(self, title, body, *, max_children):  # noqa: ANN001
            assert title == low_quality.title
            return SimpleNamespace(
                children=[child_a, child_b],
                stats=SimpleNamespace(rejected_candidates=3, sanitizer_rejections=2),
            )

    monkeypatch.setattr(mod, "format_boss_ready_body", fake_format)
    monkeypatch.setattr(mod, "DecompositionBridge", FakeBridge)

    result, telemetry = mod.maybe_decompose_candidates_with_telemetry(
        [low_quality, bounded],
        enabled=True,
        max_children_per_parent=4,
        repo_root=mod.REPO_ROOT,
    )

    assert result == [child_a, child_b, bounded]
    assert telemetry.parents_seen == 2
    assert telemetry.parents_eligible == 1
    assert telemetry.parents_replaced == 1
    assert telemetry.parents_preserved == 1
    assert telemetry.children_emitted == 2
    assert telemetry.children_rejected == 3
    assert telemetry.sanitizer_rejections == 2


def test_main_passes_decomposition_flags(monkeypatch, capsys) -> None:
    eligible = _candidate("eligible_module", file_scope=["aragora/eligible_module.py"])
    scan_calls: list[tuple[object, object, object]] = []
    decompose_calls: list[tuple[list[BossIssueCandidate], bool, int, object]] = []

    monkeypatch.setattr(
        mod,
        "scan_all",
        lambda repo_root, categories=None, min_success_rate=0.3: (
            scan_calls.append((repo_root, categories, min_success_rate)) or [eligible]
        ),
    )
    monkeypatch.setattr(
        mod,
        "maybe_decompose_candidates_with_telemetry",
        lambda candidates, *, enabled, max_children_per_parent, repo_root: (
            decompose_calls.append((list(candidates), enabled, max_children_per_parent, repo_root))
            or (
                list(candidates),
                mod.DecompositionTelemetry(
                    parents_seen=len(candidates),
                    parents_preserved=len(candidates),
                ),
            )
        ),
    )
    monkeypatch.setattr(mod, "fetch_existing_boss_issues", lambda repo: [])
    monkeypatch.setattr(mod, "fetch_open_pr_files", lambda repo: set())
    monkeypatch.setattr(mod, "validate_body", lambda body: (True, ""))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_boss_issues.py",
            "--dry-run",
            "--decompose-low-quality",
            "--max-children-per-parent",
            "4",
        ],
    )

    mod.main()

    _ = capsys.readouterr()
    assert scan_calls
    assert decompose_calls
    assert decompose_calls[0][1] is True
    assert decompose_calls[0][2] == 4


def test_fetch_open_pr_files_paginates_open_prs_and_pr_files(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(mod, "_OPEN_PR_PAGE_SIZE", 2)
    monkeypatch.setattr(mod, "_OPEN_PR_FILES_PAGE_SIZE", 2)

    def fake_run(cmd: list[str], **_: object) -> SimpleNamespace:
        endpoint = cmd[-1]
        calls.append(endpoint)
        if endpoint.endswith("/pulls?state=open&per_page=2&page=1"):
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps([{"number": 101}, {"number": 102}]),
                stderr="",
            )
        if endpoint.endswith("/pulls/101/files?per_page=2&page=1"):
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    [{"filename": "aragora/first.py"}, {"filename": "aragora/second.py"}]
                ),
                stderr="",
            )
        if endpoint.endswith("/pulls/101/files?per_page=2&page=2"):
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps([{"filename": "aragora/third.py"}]),
                stderr="",
            )
        if endpoint.endswith("/pulls/102/files?per_page=2&page=1"):
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps([{"filename": "aragora/fourth.py"}]),
                stderr="",
            )
        if endpoint.endswith("/pulls?state=open&per_page=2&page=2"):
            return SimpleNamespace(returncode=0, stdout=json.dumps([{"number": 103}]), stderr="")
        if endpoint.endswith("/pulls/103/files?per_page=2&page=1"):
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps([{"filename": "aragora/fifth.py"}]),
                stderr="",
            )
        if endpoint.endswith("/pulls?state=open&per_page=2&page=3"):
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")
        raise AssertionError(f"unexpected gh api call: {endpoint}")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    files = mod.fetch_open_pr_files("org/repo")

    assert files == {
        "aragora/first.py",
        "aragora/second.py",
        "aragora/third.py",
        "aragora/fourth.py",
        "aragora/fifth.py",
    }
    assert "repos/org/repo/pulls?state=open&per_page=2&page=2" in calls
    assert "repos/org/repo/pulls/101/files?per_page=2&page=2" in calls


def test_fetch_open_pr_files_raises_when_open_pr_pagination_cap_exhausted(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_OPEN_PR_PAGE_SIZE", 1)
    monkeypatch.setattr(mod, "_OPEN_PR_MAX_PAGES", 2)

    def fake_run(cmd: list[str], **_: object) -> SimpleNamespace:
        endpoint = cmd[-1]
        if endpoint.endswith("/pulls?state=open&per_page=1&page=1"):
            return SimpleNamespace(returncode=0, stdout=json.dumps([{"number": 101}]), stderr="")
        if endpoint.endswith("/pulls/101/files?per_page=100&page=1"):
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")
        if endpoint.endswith("/pulls?state=open&per_page=1&page=2"):
            return SimpleNamespace(returncode=0, stdout=json.dumps([{"number": 102}]), stderr="")
        if endpoint.endswith("/pulls/102/files?per_page=100&page=1"):
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")
        raise AssertionError(f"unexpected gh api call: {endpoint}")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    with pytest.raises(mod._AdmissionError, match="open PRs: pagination exceeded configured cap"):
        mod.fetch_open_pr_files("org/repo")


def test_fetch_open_pr_files_raises_when_pr_files_pagination_cap_exhausted(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_OPEN_PR_PAGE_SIZE", 1)
    monkeypatch.setattr(mod, "_OPEN_PR_FILES_PAGE_SIZE", 1)
    monkeypatch.setattr(mod, "_OPEN_PR_FILES_MAX_PAGES", 2)

    def fake_run(cmd: list[str], **_: object) -> SimpleNamespace:
        endpoint = cmd[-1]
        if endpoint.endswith("/pulls?state=open&per_page=1&page=1"):
            return SimpleNamespace(returncode=0, stdout=json.dumps([{"number": 101}]), stderr="")
        if endpoint.endswith("/pulls/101/files?per_page=1&page=1"):
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps([{"filename": "aragora/first.py"}]),
                stderr="",
            )
        if endpoint.endswith("/pulls/101/files?per_page=1&page=2"):
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps([{"filename": "aragora/second.py"}]),
                stderr="",
            )
        raise AssertionError(f"unexpected gh api call: {endpoint}")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    with pytest.raises(mod._AdmissionError, match="open PR #101 files: pagination exceeded"):
        mod.fetch_open_pr_files("org/repo")


def test_main_returns_error_when_open_pr_pagination_exhausted(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        mod,
        "scan_all",
        lambda repo_root, categories=None, min_success_rate=0.3: [],
    )
    monkeypatch.setattr(mod, "fetch_existing_boss_issues", lambda repo: [])

    def raise_pagination_error(repo: str) -> set[str]:
        raise mod._AdmissionError("open PRs", "pagination exceeded configured cap (10 pages)")

    monkeypatch.setattr(mod, "fetch_open_pr_files", raise_pagination_error)
    monkeypatch.setattr(sys, "argv", ["generate_boss_issues.py", "--repo", "org/repo"])

    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "BLOCKED: open PRs: pagination exceeded configured cap (10 pages)" in out


def test_create_github_issue_passes_extra_labels_as_repeated_flags(monkeypatch) -> None:
    """create_github_issue must add each extra label as its own --label flag.

    Without this, issues created by generate_boss_issues.py only carry the
    primary label and are skipped by the boss-loop dispatcher, which requires
    both `boss-ready` and `autonomous` (#5997 followup).
    """
    captured: list[list[str]] = []

    class _Result:
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured.append(list(cmd))
        return _Result()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    ok = mod.create_github_issue(
        "org/repo",
        "title",
        "body",
        "boss-ready",
        extra_labels=["autonomous", "boss-ready", "  "],
    )
    assert ok is True
    assert len(captured) == 1
    cmd = captured[0]
    assert cmd[:3] == ["gh", "issue", "create"]
    label_flags = [cmd[i + 1] for i, token in enumerate(cmd) if token == "--label"]
    assert label_flags == ["boss-ready", "autonomous"]


def test_main_omits_extra_labels_when_disabled(monkeypatch, capsys) -> None:
    """Passing --extra-labels='' yields a single primary label only."""

    eligible = _candidate("eligible_module", file_scope=["aragora/eligible_module.py"])
    created: list[tuple] = []
    monkeypatch.setattr(
        mod,
        "scan_all",
        lambda repo_root, categories=None, min_success_rate=0.3: [eligible],
    )
    monkeypatch.setattr(mod, "fetch_existing_boss_issues", lambda repo: [])
    monkeypatch.setattr(mod, "fetch_open_pr_files", lambda repo: set())
    monkeypatch.setattr(mod, "validate_body", lambda body: (True, ""))
    monkeypatch.setattr(mod, "load_roadmap_priority_policy", lambda repo_root: None)
    monkeypatch.setattr(
        mod,
        "create_github_issue",
        lambda repo, title, body, label, **kwargs: (
            created.append((repo, title, body, label, kwargs.get("extra_labels", []))) or True
        ),
    )
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_boss_issues.py",
            "--repo",
            "org/repo",
            "--max-issues",
            "1",
            "--label",
            "lane:test",
            "--extra-labels",
            "",
        ],
    )

    mod.main()

    assert len(created) == 1
    assert created[0][4] == []


def test_main_backpressure_signal_blocks_substrate_refill(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    substrate = _candidate("substrate_module", file_scope=["scripts/substrate_tool.py"])
    product = _candidate("product_module", file_scope=["aragora/server/product_module.py"])
    signal_file = tmp_path / "backpressure.json"
    signal_file.write_text(
        json.dumps(
            {
                "mode": "shepherd",
                "admission": {
                    "withhold_classes": ["maintenance"],
                    "source": "backlog_gate",
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        mod,
        "scan_all",
        lambda repo_root, categories=None, min_success_rate=0.3: [substrate, product],
    )
    monkeypatch.setattr(mod, "fetch_existing_boss_issues", lambda repo: [])
    monkeypatch.setattr(mod, "fetch_open_pr_files", lambda repo: set())
    monkeypatch.setattr(mod, "validate_body", lambda body: (True, ""))
    monkeypatch.setattr(mod, "load_roadmap_priority_policy", lambda repo_root: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_boss_issues.py",
            "--repo",
            "org/repo",
            "--dry-run",
            "--max-issues",
            "5",
            "--label",
            "lane:test",
            "--backpressure-signal-file",
            str(signal_file),
        ],
    )

    mod.main()

    out = capsys.readouterr().out
    assert "Backpressure admission withheld maintenance" in out
    assert "DRY RUN — would create 1 issues" in out
    assert product.title in out
    assert substrate.title not in out


def test_main_legacy_shepherd_signal_does_not_block_refill(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    substrate = _candidate("substrate_module", file_scope=["scripts/substrate_tool.py"])
    signal_file = tmp_path / "backpressure.json"
    signal_file.write_text(json.dumps({"mode": "shepherd"}), encoding="utf-8")

    monkeypatch.setattr(
        mod,
        "scan_all",
        lambda repo_root, categories=None, min_success_rate=0.3: [substrate],
    )
    monkeypatch.setattr(mod, "fetch_existing_boss_issues", lambda repo: [])
    monkeypatch.setattr(mod, "fetch_open_pr_files", lambda repo: set())
    monkeypatch.setattr(mod, "validate_body", lambda body: (True, ""))
    monkeypatch.setattr(mod, "load_roadmap_priority_policy", lambda repo_root: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_boss_issues.py",
            "--repo",
            "org/repo",
            "--dry-run",
            "--max-issues",
            "5",
            "--label",
            "lane:test",
            "--substrate-cap",
            "1",
            "--backpressure-signal-file",
            str(signal_file),
        ],
    )

    mod.main()

    out = capsys.readouterr().out
    assert "Backpressure admission withheld maintenance" not in out
    assert "DRY RUN — would create 1 issues" in out
    assert substrate.title in out


class TestSelectWithSubstrateCap:
    """Substrate cap on issue creation (FOCUS.md Sprint 3 goal 2)."""

    @staticmethod
    def _items(spec: list[str]) -> list[tuple[BossIssueCandidate, str]]:
        items = []
        for i, surface in enumerate(spec):
            scope = ["scripts/tool.py"] if surface == "s" else ["aragora/server/h.py"]
            cand = BossIssueCandidate(
                category="test_coverage",
                title=f"candidate {i} {surface}",
                description="x",
                file_scope=scope,
                new_files=[],
            )
            items.append((cand, f"body-{i}"))
        return items

    def test_cap_limits_substrate_and_product_fills_rest(self) -> None:
        items = self._items(["s"] * 10 + ["p"] * 10)
        selected, skipped = mod.select_with_substrate_cap(items, 10, 0.3)
        surfaces = [c.surface for c, _ in selected]
        assert len(selected) == 10
        assert surfaces.count("substrate") == 3
        assert surfaces.count("product") == 7
        assert skipped == 7

    def test_only_substrate_candidates_respects_budget_and_reports_skips(self) -> None:
        items = self._items(["s"] * 10)
        selected, skipped = mod.select_with_substrate_cap(items, 10, 0.3)
        assert len(selected) == 3
        assert skipped == 7

    def test_cap_of_one_disables(self) -> None:
        items = self._items(["s"] * 5)
        selected, skipped = mod.select_with_substrate_cap(items, 5, 1.0)
        assert len(selected) == 5
        assert skipped == 0

    def test_product_never_skipped_by_cap(self) -> None:
        items = self._items(["p"] * 12)
        selected, skipped = mod.select_with_substrate_cap(items, 10, 0.0)
        assert len(selected) == 10
        assert skipped == 0


class TestNetClosureFloor:
    """Net-closure floor on issue appetite (Sprint 4 goal 3, plan v2 Phase 0.3).

    Audit basis: 215 issues created, 0 closed over two weeks. The floor
    scales the generator's allowance by the trailing closed:created ratio.
    """

    def test_zero_closures_allows_zero_with_clear_reason(self) -> None:
        allowed, reason = mod.apply_net_closure_floor(20, 215, 0, 0.25)
        assert allowed == 0
        assert "215" in reason
        assert "closed" in reason.lower()
        assert "0.25" in reason
        assert "allowed=0" in reason

    def test_ratio_at_floor_gives_full_allowance(self) -> None:
        allowed, reason = mod.apply_net_closure_floor(20, 100, 25, 0.25)
        assert allowed == 20
        assert "allowed=20" in reason

    def test_ratio_at_half_floor_gives_half_allowance(self) -> None:
        # ratio = 1/8 = 0.125, half of the 0.25 floor -> half of max_issues
        allowed, reason = mod.apply_net_closure_floor(20, 8, 1, 0.25)
        assert allowed == 10
        assert "allowed=10" in reason

    def test_floor_zero_disables_with_full_allowance(self) -> None:
        allowed, reason = mod.apply_net_closure_floor(20, 215, 0, 0.0)
        assert allowed == 20
        assert "disabled" in reason.lower()
        assert "allowed=20" in reason

    def test_no_created_issues_gives_full_allowance(self) -> None:
        allowed, reason = mod.apply_net_closure_floor(20, 0, 5, 0.25)
        assert allowed == 20
        assert "allowed=20" in reason

    def test_ratio_above_floor_never_exceeds_max(self) -> None:
        allowed, _ = mod.apply_net_closure_floor(20, 10, 9, 0.25)
        assert allowed == 20

    def test_reason_always_states_the_numbers(self) -> None:
        cases = [
            (20, 215, 0, 0.25),
            (20, 100, 25, 0.25),
            (20, 0, 0, 0.25),
            (20, 8, 1, 0.25),
            (20, 5, 1, 0.0),
        ]
        for max_issues, created, closed, floor in cases:
            allowed, reason = mod.apply_net_closure_floor(max_issues, created, closed, floor)
            assert f"created_7d={created}" in reason, reason
            assert f"closed_7d={closed}" in reason, reason
            assert f"allowed={allowed}" in reason, reason
            assert 0 <= allowed <= max_issues


class TestClosureFloorMainWiring:
    """main() wiring for the net-closure floor (skips reported, never silent)."""

    @staticmethod
    def _eligible(n: int, *, substrate: int = 0) -> list[BossIssueCandidate]:
        cands = []
        for i in range(n):
            scope = [f"scripts/tool_{i}.py"] if i < substrate else [f"aragora/server/mod_{i}.py"]
            cands.append(
                BossIssueCandidate(
                    category="test_coverage",
                    title=f"Closure floor candidate {i}",
                    description="x",
                    file_scope=scope,
                    new_files=[],
                )
            )
        return cands

    def _patch_pipeline(self, monkeypatch, candidates: list[BossIssueCandidate]) -> None:
        monkeypatch.setattr(
            mod,
            "scan_all",
            lambda repo_root, categories=None, min_success_rate=0.3: list(candidates),
        )
        monkeypatch.setattr(mod, "fetch_existing_boss_issues", lambda repo: [])
        monkeypatch.setattr(mod, "fetch_open_pr_files", lambda repo: set())
        monkeypatch.setattr(mod, "validate_body", lambda body: (True, ""))
        monkeypatch.setattr(mod, "load_roadmap_priority_policy", lambda repo_root: None)

    def test_overrides_throttle_to_zero_without_fetching(self, monkeypatch, capsys) -> None:
        self._patch_pipeline(monkeypatch, self._eligible(3))

        def _boom(repo: str):
            raise AssertionError("fetch_closure_counts_7d must not be called with overrides")

        monkeypatch.setattr(mod, "fetch_closure_counts_7d", _boom)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "generate_boss_issues.py",
                "--repo",
                "org/repo",
                "--dry-run",
                "--max-issues",
                "5",
                "--label",
                "lane:test",
                "--closure-floor",
                "0.25",
                "--created-7d",
                "215",
                "--closed-7d",
                "0",
            ],
        )
        mod.main()
        out = capsys.readouterr().out
        assert "would create 0 issues" in out
        assert "created_7d=215" in out
        assert "closed_7d=0" in out
        assert "allowed=0" in out

    def test_fetches_counts_when_overrides_absent(self, monkeypatch, capsys) -> None:
        self._patch_pipeline(monkeypatch, self._eligible(3))
        fetch_calls: list[str] = []
        monkeypatch.setattr(
            mod,
            "fetch_closure_counts_7d",
            lambda repo: (fetch_calls.append(repo) or (10, 10)),
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "generate_boss_issues.py",
                "--repo",
                "org/repo",
                "--dry-run",
                "--max-issues",
                "5",
                "--label",
                "lane:test",
                "--closure-floor",
                "0.25",
            ],
        )
        mod.main()
        out = capsys.readouterr().out
        assert fetch_calls == ["org/repo"]
        assert "would create 3 issues" in out
        assert "created_7d=10" in out and "closed_7d=10" in out

    def test_counts_unavailable_blocks_with_report(self, monkeypatch, capsys) -> None:
        self._patch_pipeline(monkeypatch, self._eligible(3))
        monkeypatch.setattr(mod, "fetch_closure_counts_7d", lambda repo: None)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "generate_boss_issues.py",
                "--repo",
                "org/repo",
                "--dry-run",
                "--max-issues",
                "5",
                "--label",
                "lane:test",
                "--closure-floor",
                "0.25",
            ],
        )
        assert mod.main() == 1
        out = capsys.readouterr().out
        assert "unavailable" in out.lower()
        assert "BLOCKED:" in out
        assert "would create" not in out

    def test_partial_throttle_preserves_substrate_cap_composition(
        self, monkeypatch, capsys
    ) -> None:
        # 10 substrate-first then 10 product candidates; cap 0.3 at max 10
        # selects 3 substrate + 7 product. Floor at half ratio throttles the
        # total to 5; re-selection keeps the cap (1 substrate + 4 product),
        # never product-starved.
        self._patch_pipeline(monkeypatch, self._eligible(20, substrate=10))
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "generate_boss_issues.py",
                "--repo",
                "org/repo",
                "--dry-run",
                "--max-issues",
                "10",
                "--label",
                "lane:test",
                "--substrate-cap",
                "0.3",
                "--closure-floor",
                "0.25",
                "--created-7d",
                "8",
                "--closed-7d",
                "1",
            ],
        )
        mod.main()
        out = capsys.readouterr().out
        assert "would create 5 issues" in out
        assert "allowed=5" in out
        files_lines = [ln for ln in out.splitlines() if ln.startswith("FILES:")]
        substrate_files = [ln for ln in files_lines if "scripts/" in ln]
        product_files = [ln for ln in files_lines if "aragora/server/" in ln]
        assert len(substrate_files) == 1
        assert len(product_files) == 4


class TestSearchIssueTotalFailureReporting:
    """gh search failures are reported with cause, never swallowed silently
    (grok review task 3 on PR #8148)."""

    def test_nonzero_exit_reports_rc_and_stderr(self, monkeypatch) -> None:
        monkeypatch.setattr(
            mod.subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(returncode=4, stdout="", stderr="gh: API rate limit"),
        )
        with pytest.raises(mod._AdmissionError) as caught:
            mod._search_issue_total("org/repo", "created:>=2026-06-03")
        assert caught.value.stage == "closure counts (created:>=2026-06-03)"
        assert "rc=4" in caught.value.reason
        assert "rate limit" in caught.value.reason

    def test_exception_reports_type_and_message(self, monkeypatch) -> None:
        def _raise(*a, **k):
            raise OSError("gh not found")

        monkeypatch.setattr(mod.subprocess, "run", _raise)
        with pytest.raises(mod._AdmissionError, match="OSError: gh not found"):
            mod._search_issue_total("org/repo", "closed:>=2026-06-03")


def _response(payload: object) -> SimpleNamespace:
    return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")


@pytest.fixture
def admission_pipeline(monkeypatch):
    """Exercise real admission lookups with an otherwise eligible candidate."""
    candidate = _candidate("eligible_module", file_scope=["aragora/eligible_module.py"])
    monkeypatch.setattr(mod, "scan_all", lambda *a, **kw: [candidate])
    monkeypatch.setattr(mod, "format_boss_ready_body", lambda c: "valid body")
    monkeypatch.setattr(mod, "validate_body", lambda body: (True, ""))
    monkeypatch.setattr(mod, "load_roadmap_priority_policy", lambda root: None)
    monkeypatch.setattr(mod, "fetch_closure_counts_7d", _FETCH_CLOSURE_COUNTS_7D)
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: None)
    create = Mock(return_value=True)
    monkeypatch.setattr(mod, "create_github_issue", create)
    return create


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("stage", ["issues", "prs", "files", "created", "closed"])
@pytest.mark.parametrize(
    "failure", ["nonzero", "timeout", "oserror", "invalid_json", "empty", "shape", "record"]
)
def test_main_blocks_every_unavailable_input(
    monkeypatch, capsys, admission_pipeline, stage, failure, dry_run
) -> None:
    def fake_run(cmd, **kwargs):
        assert cmd[:4] == ["gh", "api", "--method", "GET"]
        assert kwargs["timeout"] == 30
        endpoint = cmd[4]
        if "/issues?" in endpoint:
            current, healthy = "issues", []
        elif "/pulls?" in endpoint:
            current, healthy = "prs", [{"number": 1}]
        elif "/pulls/1/files?" in endpoint:
            current, healthy = "files", [{"filename": "aragora/unrelated.py"}]
        else:
            assert endpoint == "search/issues"
            current = "created" if "created:" in cmd[6] else "closed"
            healthy = {"total_count": 1, "incomplete_results": False}
        if current != stage:
            return _response(healthy)
        if failure == "nonzero":
            return SimpleNamespace(returncode=1, stdout="[]", stderr="rate limit")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(cmd, 30)
        if failure == "oserror":
            raise OSError("gh unavailable")
        if failure in {"invalid_json", "empty"}:
            return SimpleNamespace(
                returncode=0, stdout="{" if failure == "invalid_json" else "", stderr=""
            )
        if failure == "shape":
            return _response(None)
        malformed = {
            "issues": [{"number": 1, "title": "title", "body": []}],
            "prs": [{"number": True}],
            "files": [{"filename": None}],
            "created": {"total_count": True, "incomplete_results": False},
            "closed": {"total_count": 1, "incomplete_results": True},
        }
        return _response(malformed[stage])

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["generate_boss_issues.py", "--label", "lane:test"] + (["--dry-run"] if dry_run else []),
    )
    assert mod.main() == 1
    admission_pipeline.assert_not_called()
    out = capsys.readouterr().out
    assert "BLOCKED:" in out and "0 issues created" in out
    assert "would create" not in out


@pytest.mark.parametrize("stage", ["issues", "prs", "files"])
@pytest.mark.parametrize("failure", ["later_page", "cap", "non_object"])
def test_partial_inventory_never_admits_work(
    monkeypatch, capsys, admission_pipeline, stage, failure
) -> None:
    monkeypatch.setattr(mod, "_OPEN_ISSUE_PAGE_SIZE", 1)
    monkeypatch.setattr(mod, "_OPEN_PR_PAGE_SIZE", 1)
    monkeypatch.setattr(mod, "_OPEN_PR_FILES_PAGE_SIZE", 1)
    monkeypatch.setattr(mod, "_OPEN_ISSUE_MAX_PAGES", 2)
    monkeypatch.setattr(mod, "_OPEN_PR_MAX_PAGES", 2)
    monkeypatch.setattr(mod, "_OPEN_PR_FILES_MAX_PAGES", 2)
    seen = []

    def fake_run(cmd, **kwargs):
        endpoint = cmd[-1]
        seen.append(endpoint)
        second_page = endpoint.endswith("page=2")
        if "/issues?" in endpoint:
            current = "issues"
            record = {"number": 1, "title": "title", "body": "<!-- fingerprint:other -->"}
        elif "/pulls?" in endpoint:
            current, record = "prs", {"number": 2 if second_page else 1}
        else:
            current, record = "files", {"filename": "aragora/unrelated.py"}
        if current == stage:
            if failure == "later_page" and second_page:
                raise subprocess.TimeoutExpired(cmd, 30)
            if failure == "non_object":
                return _response([None])
            return _response([record])
        return _response([] if second_page else [record])

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["generate_boss_issues.py", "--label", "lane:test"])
    assert mod.main() == 1
    admission_pipeline.assert_not_called()
    assert "BLOCKED:" in capsys.readouterr().out
    if failure != "non_object":
        assert any(endpoint.endswith("page=2") for endpoint in seen)


def test_issue_pagination_counts_prs_but_excludes_them_from_duplicates(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_OPEN_ISSUE_PAGE_SIZE", 2)
    issue = {"number": 1, "title": "title", "body": "<!-- fingerprint:abc -->"}
    pages = [
        [issue, dict(issue, number=2, pull_request={"url": "https://api.github.com/pulls/2"})],
        [dict(issue, number=3, body=None), dict(issue, number=4)],
        [],
    ]
    run = Mock(side_effect=[_response(page) for page in pages])
    monkeypatch.setattr(mod.subprocess, "run", run)
    assert mod.fetch_existing_boss_issues("org/repo") == [issue, dict(issue, number=4)]
    assert run.call_count == 3
    assert run.call_args.args[0][-1].endswith("page=3")


@pytest.mark.parametrize(
    "payload",
    [
        {"total_count": -1, "incomplete_results": False},
        {"total_count": "0", "incomplete_results": False},
        {"total_count": 1.5, "incomplete_results": False},
        {"total_count": 0},
        {"total_count": 0, "incomplete_results": "false"},
        {"total_count": 0, "incomplete_results": 0},
    ],
)
def test_search_rejects_unverified_counts(monkeypatch, payload) -> None:
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **kw: _response(payload))
    with pytest.raises(mod._AdmissionError, match="closure counts"):
        mod._search_issue_total("org/repo", "created:>=2026-09-01")


@pytest.mark.parametrize("count", [0, 1234])
def test_search_accepts_complete_counts(monkeypatch, count) -> None:
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda *a, **kw: _response({"total_count": count, "incomplete_results": False}),
    )
    assert mod._search_issue_total("org/repo", "created:>=2026-09-01") == count


@pytest.mark.parametrize(
    "options", [[], ["--closure-floor", "0"], ["--created-7d", "1", "--closed-7d", "1"]]
)
def test_verified_empty_inventory_allows_same_candidate(
    monkeypatch, admission_pipeline, options
) -> None:
    def fake_run(cmd, **kwargs):
        if cmd[4] == "search/issues":
            assert not options, "disabled floor or explicit overrides must skip search"
            return _response({"total_count": 1, "incomplete_results": False})
        return _response([])

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["generate_boss_issues.py", "--label", "lane:test", *options])
    assert mod.main() == 0
    admission_pipeline.assert_called_once()
    assert admission_pipeline.call_args.args[1] == "Add tests for eligible_module"


def test_executable_propagates_admission_failure() -> None:
    # Run the actual __main__ block in a child; all inventory I/O is mocked there.
    code = """
import runpy
import subprocess
import sys
from unittest.mock import patch

with patch('aragora.swarm.issue_scanner.scan_all', return_value=[]), \\
     patch('subprocess.run', side_effect=subprocess.TimeoutExpired('gh', 30)):
    sys.argv = ['generate_boss_issues.py', '--dry-run']
    runpy.run_path('scripts/generate_boss_issues.py', run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=mod.REPO_ROOT, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 1, result.stderr
    assert "BLOCKED: open issues page 1: TimeoutExpired" in result.stdout
    assert "would create" not in result.stdout
