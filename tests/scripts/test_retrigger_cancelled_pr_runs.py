"""Selection logic for scripts/retrigger_cancelled_pr_runs.py (M1 guardian).

Pins the five guard conditions from PR_RUN_CANCELLATION_DIAGNOSIS.md M1: exact
current head, no newer run, non-draft open PR, TTL, and the run_attempt==1
once-per-run marker that bounds rerun loops.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "retrigger_cancelled_pr_runs.py"


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("retrigger_cancelled_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)


def _protected(mod) -> dict:
    paths = mod.load_protected_manifest()
    assert paths  # the committed manifest must never be empty
    return {"protected_paths": paths}


def _run(
    run_id: int = 1,
    *,
    workflow_id: int = 77,
    name: str = "Tests",
    path: str = ".github/workflows/test.yml",
    branch: str = "feat/x",
    sha: str = "a" * 40,
    conclusion: str = "cancelled",
    event: str = "pull_request",
    attempt: int = 1,
    age_hours: float = 1.0,
    cancelled_age_hours: float | None = None,
) -> dict:
    return {
        "id": run_id,
        "workflow_id": workflow_id,
        "name": name,
        "path": path,
        "head_branch": branch,
        "head_sha": sha,
        "conclusion": conclusion,
        "event": event,
        "run_attempt": attempt,
        "created_at": (NOW - timedelta(hours=age_hours)).isoformat().replace("+00:00", "Z"),
        "updated_at": (
            NOW - timedelta(hours=age_hours if cancelled_age_hours is None else cancelled_age_hours)
        )
        .isoformat()
        .replace("+00:00", "Z"),
    }


def _heads(branch: str = "feat/x", sha: str = "a" * 40) -> set[tuple[str, str]]:
    return {(branch, sha)}


def test_cancelled_current_head_run_is_selected(mod) -> None:
    reruns = mod.compute_reruns(
        [_run()], active_head_pairs=_heads(), now=NOW, ttl_hours=6.0, **_protected(mod)
    )
    assert [r["run_id"] for r in reruns] == [1]
    assert reruns[0]["workflow"] == "Tests"


def test_superseded_head_is_skipped(mod) -> None:
    reruns = mod.compute_reruns(
        [_run(sha="b" * 40)],
        active_head_pairs=_heads(sha="a" * 40),
        now=NOW,
        ttl_hours=6.0,
        **_protected(mod),
    )
    assert reruns == []


def test_draft_or_closed_pr_branch_is_skipped(mod) -> None:
    # compute_active_head_pairs excludes drafts, so an absent pair == draft/closed.
    reruns = mod.compute_reruns(
        [_run(branch="gone")], active_head_pairs=_heads(), now=NOW, ttl_hours=6.0, **_protected(mod)
    )
    assert reruns == []


def test_newer_run_of_same_workflow_supersedes(mod) -> None:
    cancelled = _run(run_id=1, age_hours=2.0)
    newer = _run(run_id=2, conclusion="success", age_hours=0.5)
    reruns = mod.compute_reruns(
        [cancelled, newer], active_head_pairs=_heads(), now=NOW, ttl_hours=6.0, **_protected(mod)
    )
    assert reruns == []


def test_second_attempt_is_never_rerun_again(mod) -> None:
    # run_attempt > 1 means a rerun already happened: the stateless once-marker.
    reruns = mod.compute_reruns(
        [_run(attempt=2)], active_head_pairs=_heads(), now=NOW, ttl_hours=6.0, **_protected(mod)
    )
    assert reruns == []


def test_old_cancellation_outside_ttl_is_skipped(mod) -> None:
    reruns = mod.compute_reruns(
        [_run(age_hours=7.0)], active_head_pairs=_heads(), now=NOW, ttl_hours=6.0, **_protected(mod)
    )
    assert reruns == []


def test_non_pr_events_and_non_cancelled_conclusions_are_skipped(mod) -> None:
    runs = [
        _run(run_id=1, event="push"),
        _run(run_id=2, conclusion="failure"),
        _run(run_id=3, conclusion="success"),
    ]
    assert (
        mod.compute_reruns(
            runs, active_head_pairs=_heads(), now=NOW, ttl_hours=6.0, **_protected(mod)
        )
        == []
    )


def test_active_head_pairs_excludes_drafts_and_keeps_name_collisions(mod) -> None:
    pulls = [
        {"draft": False, "head": {"ref": "feat/x", "sha": "a" * 40}},
        {"draft": True, "head": {"ref": "feat/draft", "sha": "b" * 40}},
        # fork PR sharing the branch name with a different head (#9133 P2):
        {"draft": False, "head": {"ref": "feat/x", "sha": "c" * 40}},
    ]
    pairs = mod.compute_active_head_pairs(pulls)
    assert pairs == {("feat/x", "a" * 40), ("feat/x", "c" * 40)}


def test_advisory_cancellation_is_intentional_and_never_rerun(mod) -> None:
    """Portability Lint is NOT in the protected manifest: without a jobs
    probe (fetch_jobs=None) the advisory class is disabled entirely and its
    PR-open cancellation stays intentional_advisory_priority — fail closed."""
    advisory = _run(name="Portability Lint", path=".github/workflows/portability.yml")
    reruns = mod.compute_reruns(
        [advisory], active_head_pairs=_heads(), now=NOW, ttl_hours=6.0, **_protected(mod)
    )
    assert reruns == []


def test_empty_manifest_fails_closed(mod, tmp_path) -> None:
    paths = mod.load_protected_manifest(tmp_path / "missing.json")
    assert paths == set()
    reruns = mod.compute_reruns(
        [_run()],
        active_head_pairs=_heads(),
        now=NOW,
        ttl_hours=6.0,
        protected_paths=paths,
    )
    assert reruns == []  # with no manifest, nothing is rerun-eligible


def test_manifest_matches_priority_keep_list(mod) -> None:
    """Drift guard: every keep-list entry in required-check-priority.yml must
    be present in the manifest, so the guardian's protected class can never
    silently diverge from what the priority canceller preserves."""
    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "workflows"
        / "required-check-priority.yml"
    ).read_text(encoding="utf-8")
    paths = mod.load_protected_manifest()
    import re as _re

    # Scope the scan to the alwaysKeepWorkflowPaths block only (#9133 P3 r7):
    # matching any quoted workflow path anywhere in the file would silently
    # track unrelated strings if the workflow gains other path literals.
    block_match = _re.search(
        r"alwaysKeepWorkflowPaths\s*=\s*new Set\(\[(.*?)\]\)", workflow, _re.DOTALL
    )
    assert block_match, "drift guard is vacuous: keep-list block not found"
    matches = _re.findall(r"'(\.github/workflows/[^']+\.yml)'", block_match.group(1))
    assert len(matches) >= 1, "drift guard is vacuous: keep-list regex matched nothing"
    for path in matches:
        assert path in paths, f"keep-list path missing from manifest: {path}"


def test_newer_non_pr_run_does_not_suppress_pr_rerun(mod) -> None:
    """A newer push/dispatch run on the same branch does not re-evaluate the
    PR's required contexts, so it must not count as supersession (#9133 P2)."""
    cancelled_pr_run = _run(run_id=1, age_hours=2.0)
    newer_push_run = _run(run_id=2, conclusion="success", event="push", age_hours=0.5)
    reruns = mod.compute_reruns(
        [cancelled_pr_run, newer_push_run],
        active_head_pairs=_heads(),
        now=NOW,
        ttl_hours=6.0,
        **_protected(mod),
    )
    assert [r["run_id"] for r in reruns] == [1]


def test_newer_run_at_stale_sha_does_not_suppress_current_head_rerun(mod) -> None:
    """A newer PR run at a DIFFERENT (stale) SHA does not cover the current
    head, so it must not suppress the rerun (#9133 claude P2 round 3)."""
    cancelled_current = _run(run_id=1, age_hours=2.0)
    newer_stale_sha = _run(run_id=2, conclusion="success", sha="b" * 40, age_hours=0.5)
    reruns = mod.compute_reruns(
        [cancelled_current, newer_stale_sha],
        active_head_pairs=_heads(),
        now=NOW,
        ttl_hours=6.0,
        **_protected(mod),
    )
    assert [r["run_id"] for r in reruns] == [1]


def test_same_second_tie_broken_by_run_id(mod) -> None:
    """Second-granular timestamps tie in a synchronize+labeled burst; the
    higher run id is newest, so only it survives (#9133 claude P3)."""
    older = _run(run_id=10, age_hours=1.0)
    newer = _run(run_id=11, age_hours=1.0)  # same created_at, higher id
    reruns = mod.compute_reruns(
        [older, newer], active_head_pairs=_heads(), now=NOW, ttl_hours=6.0, **_protected(mod)
    )
    assert [r["run_id"] for r in reruns] == [11]


def test_name_spoofing_alone_never_qualifies(mod) -> None:
    """Protection matching is path-ONLY: a PR-branch workflow merely NAMED
    'Tests' at an advisory path stays intentionally cancelled (#9133 P3)."""
    spoofed = _run(name="Tests", path=".github/workflows/my-advisory.yml")
    reruns = mod.compute_reruns(
        [spoofed], active_head_pairs=_heads(), now=NOW, ttl_hours=6.0, **_protected(mod)
    )
    assert reruns == []


def test_run_scan_filters_pull_request_events_server_side(mod, monkeypatch) -> None:
    """The runs window is bounded; without a server-side event filter,
    push/schedule runs consume it and eligible cancelled PR runs fall
    outside (#9133 openai P2 round 5)."""
    seen = {}

    class _Client(mod.GitHubClient):
        def paginate(self, path, *, query=None, max_pages=10):
            seen.update(query or {})
            return []

    _Client("o/r", "tok").list_recent_workflow_runs(300)
    assert seen.get("event") == "pull_request"


def test_ttl_anchors_to_cancellation_time_not_run_creation(mod) -> None:
    """A shard that STARTED 8h ago but was cancelled 1h ago is eligible: the
    motivating incidents were long-running shards killed mid-run (#9133 P3)."""
    long_runner = _run(age_hours=8.0, cancelled_age_hours=1.0)
    reruns = mod.compute_reruns(
        [long_runner], active_head_pairs=_heads(), now=NOW, ttl_hours=6.0, **_protected(mod)
    )
    assert [r["run_id"] for r in reruns] == [1]


def test_keep_list_names_block_also_matches_manifest(mod) -> None:
    """Both canceller keep-lists are drift-guarded: names too, read straight
    from the manifest JSON since the script consumes only paths (#9133 r8)."""
    import json as _json
    import re as _re

    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "workflows"
        / "required-check-priority.yml"
    ).read_text(encoding="utf-8")
    manifest = _json.loads(mod.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    manifest_names = set(manifest.get("workflow_names", []))
    block = _re.search(r"alwaysKeepWorkflowNames\s*=\s*new Set\(\[(.*?)\]\)", workflow, _re.DOTALL)
    assert block, "names drift guard is vacuous: keep-list names block not found"
    names = _re.findall(r"'([^']+)'", block.group(1))
    assert len(names) >= 1
    for name in names:
        assert name in manifest_names, f"keep-list name missing from manifest: {name}"


def test_run_pr_association_must_intersect_open_prs_when_named(mod) -> None:
    """When the API names the run's pull_requests, at least one must be an
    open scanned PR; an empty list stays eligible (fork runs omit it)."""
    # Distinct workflows so the same-head supersession tie-break stays out
    # of this test's way.
    named_foreign = _run(run_id=1, workflow_id=71)
    named_foreign["pull_requests"] = [{"number": 424242}]
    named_ok = _run(run_id=2, workflow_id=72)
    named_ok["pull_requests"] = [{"number": 9133}]
    unnamed = _run(run_id=3, workflow_id=73)
    reruns = mod.compute_reruns(
        [named_foreign, named_ok, unnamed],
        active_head_pairs=_heads(),
        now=NOW,
        ttl_hours=6.0,
        open_pr_numbers={9133},
        **_protected(mod),
    )
    assert sorted(r["run_id"] for r in reruns) == [2, 3]


# --- queued-phase advisory displacement (#9351 round 2) -----------------------

_ADVISORY_PATH = ".github/workflows/module-tier-drift.yml"


def _advisory_run(run_id: int = 1, **kwargs) -> dict:
    kwargs.setdefault("name", "Module Tier Drift")
    kwargs.setdefault("path", _ADVISORY_PATH)
    return _run(run_id, **kwargs)


def _queued_jobs() -> list[dict]:
    """Jobs of a run cancelled while still queued: nothing ever started."""
    return [
        {"started_at": None, "steps": []},
        {"started_at": None, "steps": [{"name": "Set up job", "started_at": None}]},
    ]


def _checkout_jobs() -> list[dict]:
    """Jobs of a run cancelled at the Checkout step: execution began."""
    return [
        {
            "started_at": "2026-07-10T11:00:00Z",
            "steps": [
                {"name": "Set up job", "started_at": "2026-07-10T11:00:01Z"},
                {"name": "Checkout", "started_at": "2026-07-10T11:00:05Z"},
            ],
        }
    ]


class _CountingFetcher:
    def __init__(self, jobs) -> None:
        self.jobs = jobs
        self.calls: list[int] = []

    def __call__(self, run_id: int):
        self.calls.append(run_id)
        return self.jobs


def test_queued_phase_advisory_displacement_is_selected_once(mod) -> None:
    """An advisory run displaced while QUEUED (no job/step ever started) is
    the residual settlement tax: the guardian now reruns it exactly once,
    classified distinctly so reports separate it from the protected class."""
    fetcher = _CountingFetcher(_queued_jobs())
    reruns = mod.compute_reruns(
        [_advisory_run()],
        active_head_pairs=_heads(),
        now=NOW,
        ttl_hours=6.0,
        fetch_jobs=fetcher,
        **_protected(mod),
    )
    assert [r["run_id"] for r in reruns] == [1]
    assert reruns[0]["classification"] == "queued_phase_advisory_displacement"
    assert fetcher.calls == [1]


def test_checkout_phase_advisory_run_stays_cancelled(mod) -> None:
    """An advisory run that STARTED (cancelled at Checkout) has a started
    step: it is not a queued-phase displacement and stays cancelled — that
    class is eliminated upstream by RCP's queued-only rule."""
    fetcher = _CountingFetcher(_checkout_jobs())
    reruns = mod.compute_reruns(
        [_advisory_run()],
        active_head_pairs=_heads(),
        now=NOW,
        ttl_hours=6.0,
        fetch_jobs=fetcher,
        **_protected(mod),
    )
    assert reruns == []
    assert fetcher.calls == [1]  # probe ran (all other guards passed), said no


def test_protected_selection_unchanged_and_never_probed(mod) -> None:
    """Protected-manifest behavior is byte-identical: selected under the same
    guards, classified unexpected_required_cancellation, and the jobs probe
    is never spent on it."""
    fetcher = _CountingFetcher(_queued_jobs())
    reruns = mod.compute_reruns(
        [_run()],
        active_head_pairs=_heads(),
        now=NOW,
        ttl_hours=6.0,
        fetch_jobs=fetcher,
        **_protected(mod),
    )
    assert [r["run_id"] for r in reruns] == [1]
    assert reruns[0]["classification"] == "unexpected_required_cancellation"
    assert fetcher.calls == []


def test_attempt_2_advisory_is_never_rerun_again(mod) -> None:
    """run_attempt > 1 bounds the advisory class exactly like the protected
    one: once per run, even if the probe would say never-executed."""
    fetcher = _CountingFetcher(_queued_jobs())
    reruns = mod.compute_reruns(
        [_advisory_run(attempt=2)],
        active_head_pairs=_heads(),
        now=NOW,
        ttl_hours=6.0,
        fetch_jobs=fetcher,
        **_protected(mod),
    )
    assert reruns == []
    assert fetcher.calls == []  # cheap guard rejected it before any API spend


def test_jobs_probe_is_lazy_only_surviving_candidates_pay(mod) -> None:
    """Advisory runs failing ANY earlier guard (stale head, attempt 2, TTL,
    supersession) never trigger a jobs fetch; only the single surviving
    candidate costs one probe call (API budget vs --max-runs 300)."""
    fetcher = _CountingFetcher(_queued_jobs())
    runs = [
        _advisory_run(1, sha="b" * 40),  # stale head pair
        _advisory_run(2, attempt=2),  # already rerun once
        _advisory_run(3, age_hours=9.0),  # outside TTL
        _advisory_run(4, age_hours=2.0),  # superseded by run 5 below
        _advisory_run(5, conclusion="success", age_hours=0.5),  # not cancelled
        _advisory_run(6, workflow_id=99, path=".github/workflows/other-advisory.yml"),
    ]
    reruns = mod.compute_reruns(
        runs,
        active_head_pairs=_heads(),
        now=NOW,
        ttl_hours=6.0,
        fetch_jobs=fetcher,
        **_protected(mod),
    )
    assert [r["run_id"] for r in reruns] == [6]
    assert fetcher.calls == [6]


def test_failed_jobs_probe_fails_closed(mod) -> None:
    """A probe returning None (API error upstream) cannot PROVE the run never
    executed, so the run stays cancelled."""
    fetcher = _CountingFetcher(None)
    reruns = mod.compute_reruns(
        [_advisory_run()],
        active_head_pairs=_heads(),
        now=NOW,
        ttl_hours=6.0,
        fetch_jobs=fetcher,
        **_protected(mod),
    )
    assert reruns == []
    assert fetcher.calls == [1]


def test_run_never_executed_signal_matrix(mod) -> None:
    """Either never-executed signal suffices: all job started_at null, OR no
    step started_at anywhere (GitHub stamps job started_at on some
    queued-cancelled jobs without ever running a step). A started step is
    always disqualifying; zero jobs means nothing ever executed."""
    assert mod.run_never_executed([]) is True
    assert mod.run_never_executed(_queued_jobs()) is True
    # Job-level stamp but no step ever started: still queued-phase.
    assert mod.run_never_executed([{"started_at": "2026-07-10T11:00:00Z", "steps": []}]) is True
    assert mod.run_never_executed(_checkout_jobs()) is False
