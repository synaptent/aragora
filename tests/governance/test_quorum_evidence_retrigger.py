"""Governance tests for the quorum evidence re-trigger (B1).

These tests are the Tier 4 pre-approval regression target for the design
in ``docs/specs/QUORUM_EVIDENCE_RETRIGGER.md`` (root cause #1 in
``docs/governance/BOSS_LOOP_MERGE_GATE_RESILIENCE.md``: the enforcing
merge-quorum check always evaluates BEFORE evidence comments exist, so
every settlement pays a guaranteed stale failure plus a manual rerun).

They pin the structural contract of ``aragora-merge-quorum.yml``:

* ``issue_comment: [created]`` re-triggers evaluation when evidence
  comments arrive;
* the re-trigger path is guarded, debounced, and least-privileged;
* the enforcing evaluation job is untouched: no comment event reaches
  it, its permissions stay read-only, and its anti-doom-loop
  ``cancel-in-progress: false`` invariant is preserved;
* BOTH retrigger surfaces run the SAME checked-in selection helper,
  ``scripts/quorum_evidence_retrigger_select.sh``, checked out from the
  default branch: the newest completed non-draft head-bound evaluation,
  ordered by ``((run_started_at // created_at), run_id, run_attempt)``,
  with comment bursts collapsing into a single rerun.

The suite must FAIL against the pre-B1 workflow and PASS with the
change (RED/GREEN proof captured in the implementing PR).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "aragora-merge-quorum.yml"
STANDALONE_WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "aragora-merge-quorum-retrigger.yml"
)
SELECT_SCRIPT_PATH = REPO_ROOT / "scripts" / "quorum_evidence_retrigger_select.sh"
SELECT_SCRIPT_INVOCATION = "bash scripts/quorum_evidence_retrigger_select.sh"


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def standalone_workflow() -> dict[str, Any]:
    return yaml.safe_load(STANDALONE_WORKFLOW_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def select_script() -> str:
    assert SELECT_SCRIPT_PATH.is_file(), (
        "both retrigger surfaces must share scripts/quorum_evidence_retrigger_select.sh"
    )
    return SELECT_SCRIPT_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    # YAML 1.1 parses the bare key ``on`` as boolean True.
    return workflow.get("on") or workflow[True]


@pytest.fixture(scope="module")
def retrigger_job(workflow: dict[str, Any]) -> dict[str, Any]:
    jobs = workflow["jobs"]
    assert "evidence-retrigger" in jobs, (
        "workflow must define the B1 evidence-retrigger job "
        "(docs/specs/QUORUM_EVIDENCE_RETRIGGER.md)"
    )
    return jobs["evidence-retrigger"]


@pytest.fixture(scope="module")
def enforcing_job(workflow: dict[str, Any]) -> dict[str, Any]:
    return workflow["jobs"]["merge-quorum"]


@pytest.fixture(scope="module")
def retrigger_scripts(
    retrigger_job: dict[str, Any], standalone_workflow: dict[str, Any]
) -> dict[str, str]:
    return {
        "evidence-retrigger": _run_blocks(retrigger_job),
        "standalone": _run_blocks(standalone_workflow["jobs"]["retrigger"]),
    }


def _run_blocks(job: dict[str, Any]) -> str:
    return "\n".join(str(step.get("run", "")) for step in job.get("steps", []))


class TestIssueCommentTrigger:
    def test_issue_comment_created_is_a_trigger(self, triggers: dict[str, Any]) -> None:
        """Evidence comments must be able to re-trigger the workflow."""
        assert "issue_comment" in triggers
        assert triggers["issue_comment"]["types"] == ["created"]

    def test_existing_pull_request_trigger_is_preserved(self, triggers: dict[str, Any]) -> None:
        assert triggers["pull_request"]["types"] == [
            "opened",
            "synchronize",
            "reopened",
            "ready_for_review",
        ]


class TestDualEventPrResolution:
    def test_workflow_concurrency_group_resolves_issue_number(
        self, workflow: dict[str, Any]
    ) -> None:
        """Comment events must serialize per-PR, not in one global group."""
        group = workflow["concurrency"]["group"]
        assert "github.event.pull_request.number" in group
        assert "github.event.issue.number" in group

    def test_retrigger_job_resolves_pr_from_issue_number(
        self, retrigger_job: dict[str, Any]
    ) -> None:
        steps_env = "\n".join(str(step.get("env", "")) for step in retrigger_job.get("steps", []))
        assert "github.event.issue.number" in steps_env


class TestRetriggerGuards:
    def test_job_is_gated_to_pr_comments_only(self, retrigger_job: dict[str, Any]) -> None:
        """Declarative guard: issue.pull_request non-null, comment events only."""
        condition = str(retrigger_job.get("if", ""))
        assert "github.event_name == 'issue_comment'" in condition
        assert "github.event.issue.pull_request != null" in condition

    def test_github_actions_bot_comments_are_skipped(self, retrigger_job: dict[str, Any]) -> None:
        """Parser-excluded authors must not burn runs or create bot loops."""
        condition = str(retrigger_job.get("if", ""))
        assert "github.event.comment.user.login != 'github-actions[bot]'" in condition

    def test_guard_matches_known_reviewer_family_headings(
        self, retrigger_job: dict[str, Any]
    ) -> None:
        """The in-step guard mirrors the quorum parsers' family markers."""
        script = _run_blocks(retrigger_job)
        for family in ("claude", "grok", "gemini", "mistral", "openai", "codex", "factory"):
            assert family in script, f"guard regex must include reviewer family {family!r}"

    def test_guard_requires_open_non_draft_pr_and_stale_head_bound_run(
        self, retrigger_job: dict[str, Any], select_script: str
    ) -> None:
        """The gate-deferral + stale-run guards live in the shared helper."""
        assert SELECT_SCRIPT_INVOCATION in _run_blocks(retrigger_job)
        # PR open + non-draft.
        assert ".draft" in select_script
        assert ".state" in select_script
        # Re-run only the newest COMPLETED non-success run for the CURRENT head.
        assert "head_sha" in select_script
        assert "completed" in select_script
        assert "gh run rerun" in select_script

    def test_comment_body_enters_only_via_env(self, retrigger_job: dict[str, Any]) -> None:
        """Injection pin: comment markdown never interpolates into run: text."""
        script = _run_blocks(retrigger_job)
        assert "github.event.comment.body" not in script, (
            "comment body must reach the shell via env:, never inline ${{ }}"
        )
        steps_env: dict[str, Any] = {}
        for step in retrigger_job.get("steps", []):
            steps_env.update(step.get("env", {}) or {})
        assert any("github.event.comment.body" in str(value) for value in steps_env.values()), (
            "comment body must be provided to the guard step through env:"
        )


class TestDebounceConcurrency:
    def test_retrigger_concurrency_is_per_pr_and_cancels_in_progress(
        self, retrigger_job: dict[str, Any]
    ) -> None:
        concurrency = retrigger_job.get("concurrency") or {}
        assert "github.event.issue.number" in str(concurrency.get("group", ""))
        assert concurrency.get("cancel-in-progress") is True

    def test_enforcing_workflow_group_still_never_cancels_in_progress(
        self, workflow: dict[str, Any]
    ) -> None:
        """The anti-doom-loop invariant on the REQUIRED check is preserved."""
        assert workflow["concurrency"]["cancel-in-progress"] is False


class TestEnforcingJobUnchanged:
    def test_enforcing_job_excluded_from_issue_comment_events(
        self, enforcing_job: dict[str, Any]
    ) -> None:
        """A comment event must never produce a default-branch-bound evaluation."""
        assert "github.event_name != 'issue_comment'" in str(enforcing_job.get("if", ""))

    def test_workflow_level_permissions_remain_read_only(self, workflow: dict[str, Any]) -> None:
        assert workflow["permissions"] == {
            "contents": "read",
            "pull-requests": "read",
            "statuses": "read",
        }

    def test_enforcing_job_gains_no_write_permission(self, enforcing_job: dict[str, Any]) -> None:
        permissions = enforcing_job.get("permissions") or {}
        assert "write" not in str(permissions.values())

    def test_retrigger_write_surface_is_exactly_actions(
        self, retrigger_job: dict[str, Any]
    ) -> None:
        """actions:write (re-run our own evaluation) is the ONLY write scope."""
        permissions = retrigger_job.get("permissions") or {}
        writes = sorted(scope for scope, level in permissions.items() if level == "write")
        assert writes == ["actions"]
        # contents:read exists solely to check out the default-branch shared
        # selection helper; the job still cannot write repository contents.
        assert permissions.get("contents") == "read"
        assert permissions.get("statuses") is None


class TestSharedSelectionSurface:
    """The selection logic exists in exactly ONE checked-in helper.

    Duplicated merge-authority logic can drift independently, and a
    drifted copy re-opens the PR #9754 incident class, so both surfaces
    delegate to the same repo script, checked out from the BASE repo's
    default branch (the enforcing evaluation job's existing ref pin) so
    comment events never execute PR-author-controlled code.
    """

    def test_selection_helper_is_strict_bash(self, select_script: str) -> None:
        assert select_script.startswith("#!/usr/bin/env bash")
        assert "set -euo pipefail" in select_script

    def test_selection_helper_is_executable(self) -> None:
        """Mode hygiene pin: committed as 100755, even though both surfaces
        invoke it via ``bash <path>`` and never rely on the bit at runtime."""
        assert os.access(SELECT_SCRIPT_PATH, os.X_OK), (
            "scripts/quorum_evidence_retrigger_select.sh must keep its executable bit"
        )

    def test_both_surfaces_delegate_to_the_shared_helper(
        self, retrigger_scripts: dict[str, str]
    ) -> None:
        for surface, script in retrigger_scripts.items():
            assert script.count(SELECT_SCRIPT_INVOCATION) == 1, (
                f"{surface}: must invoke the shared selection helper exactly once"
            )

    def test_no_inline_selection_remains_on_either_surface(
        self, retrigger_scripts: dict[str, str]
    ) -> None:
        """Re-introducing a private copy of the selection is drift."""
        for surface, script in retrigger_scripts.items():
            for token in (
                "sort_by(",
                "--paginate",
                "total_count",
                "gh run rerun",
                "run_started_at",
            ):
                assert token not in script, (
                    f"{surface}: selection logic must live only in the shared helper "
                    f"(found inline {token!r})"
                )

    def test_surface_checkouts_pin_the_default_branch(
        self, retrigger_job: dict[str, Any], standalone_workflow: dict[str, Any]
    ) -> None:
        surfaces = {
            "evidence-retrigger": retrigger_job,
            "standalone": standalone_workflow["jobs"]["retrigger"],
        }
        for surface, job in surfaces.items():
            checkouts = [
                step
                for step in job.get("steps", [])
                if str(step.get("uses", "")).startswith("actions/checkout@")
            ]
            assert len(checkouts) == 1, f"{surface}: exactly one checkout, for the shared helper"
            ref = (checkouts[0].get("with") or {}).get("ref")
            assert ref == "${{ github.event.repository.default_branch }}", (
                f"{surface}: the helper must come from the default branch, never PR code"
            )

    def test_surface_checkouts_materialize_only_the_shared_helper(
        self, retrigger_job: dict[str, Any], standalone_workflow: dict[str, Any]
    ) -> None:
        """Both retrigger checkouts exist solely to fetch the helper, so a
        non-cone sparse checkout of exactly that file keeps per-comment
        runs from paying a full-tree checkout."""
        surfaces = {
            "evidence-retrigger": retrigger_job,
            "standalone": standalone_workflow["jobs"]["retrigger"],
        }
        for surface, job in surfaces.items():
            checkouts = [
                step
                for step in job.get("steps", [])
                if str(step.get("uses", "")).startswith("actions/checkout@")
            ]
            with_block = checkouts[0].get("with") or {}
            patterns = str(with_block.get("sparse-checkout", "")).split()
            assert patterns == ["scripts/quorum_evidence_retrigger_select.sh"], (
                f"{surface}: checkout must sparse-checkout exactly the shared helper"
            )
            assert with_block.get("sparse-checkout-cone-mode") is False, (
                f"{surface}: cone mode cannot express a single-file pattern"
            )


class TestDeterministicNonDraftSelection:
    """The shared helper selects its rerun target deterministically.

    Regression target for the 2026-08-14 draft-success resurfacing
    incident on PR #9754: an evidence burst reran BOTH evaluations at
    head ``ee63516c`` — the older draft-era run was picked because the
    newest was already re-running, and a rerun re-executes the run's
    ORIGINAL frozen event payload, so the draft short-circuit replayed
    a stale SUCCESS over the truthful ready-state result.

    Pinned contract (shared by both surfaces through the helper):
    enumerate ALL head-bound pull_request evaluations (pagination
    reconciled against ``total_count``); exclude runs created before
    the newest ``ready_for_review`` transition; order by
    ``((run_started_at // created_at), run_id, run_attempt)`` —
    coalesced because ``run_started_at`` is null while a run is still
    queued — and consider ONLY the newest survivor (in-flight or green
    newest: no-op, never a fallback); collapse concurrent retriggers
    into one rerun via a fresh pre-rerun status read plus
    rerun-rejection tolerance.
    """

    def test_selection_enumerates_all_head_bound_runs(self, select_script: str) -> None:
        """Full pagination + total_count reconciliation."""
        assert "--paginate" in select_script, "must enumerate ALL head-bound runs"
        assert "total_count" in select_script, "enumeration must be reconciled against total_count"

    def test_selection_orders_by_coalesced_start_time_run_id_run_attempt(
        self, select_script: str
    ) -> None:
        """The pinned deterministic ordering key, with the null coalesce."""
        assert "sort_by((.run_started_at // .created_at), .id, .run_attempt)" in select_script, (
            "selection must order by ((run_started_at // created_at), run_id, run_attempt)"
        )
        assert "sort_by(.run_started_at, .id, .run_attempt)" not in select_script, (
            "an uncoalesced null run_started_at sorts the queued newest run below older runs"
        )

    def test_selection_excludes_draft_frozen_evaluations(self, select_script: str) -> None:
        """Runs created before the newest ready_for_review transition are frozen drafts."""
        assert "ready_for_review" in select_script, "must partition out draft-created evaluations"
        assert "created_at" in select_script

    def test_nondeterministic_selections_are_gone(
        self, select_script: str, retrigger_scripts: dict[str, str]
    ) -> None:
        """The two incident-era selections must not reappear anywhere."""
        surfaces = {"shared-helper": select_script, **retrigger_scripts}
        for surface, script in surfaces.items():
            assert ".workflow_runs[0]" not in script, (
                f"{surface}: per_page=1 first-item selection is API-ordering-dependent"
            )
            assert "sort_by(.createdAt)" not in script, (
                f"{surface}: createdAt-only ordering ignores reruns and attempt order"
            )
            assert '.status=="completed")' not in script, (
                f"{surface}: filtering to completed runs BEFORE picking the newest "
                "falls back to older (draft-era) evaluations while the newest is "
                "re-running — the PR #9754 resurfacing mechanism"
            )

    def test_only_the_newest_evaluation_may_be_rerun(self, select_script: str) -> None:
        """Completed/success checks happen AFTER selection: an in-flight or
        green newest evaluation no-ops instead of falling back."""
        assert select_script.count("gh run rerun") == 1, (
            "exactly one rerun path, for the selected newest run only"
        )
        assert '"$run_status" != "completed"' in select_script, (
            "in-flight newest evaluation must no-op, not fall back"
        )
        assert '"$run_conclusion" == "success"' in select_script, (
            "a green newest evaluation needs no recount"
        )

    def test_concurrent_retriggers_collapse_into_one_rerun(self, select_script: str) -> None:
        """All surfaces compute the same target; a fresh pre-rerun status
        read plus rerun-rejection tolerance turns burst losers into no-ops."""
        assert "actions/runs/${run_id}" in select_script, (
            "must re-read the selected run's status just before rerun"
        )
        assert "concurrent retrigger won" in select_script
        assert "::warning::rerun request" in select_script, (
            "a rejected rerun (already re-running) must not be red noise"
        )

    def test_issue_events_read_permission_present(
        self, retrigger_job: dict[str, Any], standalone_workflow: dict[str, Any]
    ) -> None:
        """The ready_for_review partition reads issue events on both surfaces."""
        job_permissions = retrigger_job.get("permissions") or {}
        assert job_permissions.get("issues") == "read"
        workflow_permissions = standalone_workflow.get("permissions") or {}
        assert workflow_permissions.get("issues") == "read"
        assert workflow_permissions.get("contents") == "read", (
            "helper workflow checks out the shared selection helper"
        )
        surfaces = {
            "evidence-retrigger job": job_permissions,
            "helper workflow": workflow_permissions,
        }
        for surface, permissions in surfaces.items():
            writes = sorted(scope for scope, level in permissions.items() if level == "write")
            assert writes == ["actions"], f"{surface} write surface stays exactly actions"


_GH_SHIM = """\
#!/usr/bin/env bash
set -euo pipefail
args="$*"
case "$args" in
  *"/pulls/"*) cat "${GH_FIXTURES}/pr.json" ;;
  *".total_count"*) cat "${GH_FIXTURES}/total_count.txt" ;;
  *"/actions/workflows/"*) cat "${GH_FIXTURES}/runs.jsonl" ;;
  *"/issues/"*) cat "${GH_FIXTURES}/ready_events.txt" ;;
  *"/actions/runs/"*) cat "${GH_FIXTURES}/fresh_status.txt" ;;
  "run rerun"*) printf '%s\\n' "$args" >>"${GH_FIXTURES}/rerun.log" ;;
  *) echo "unexpected gh invocation: $args" >&2; exit 64 ;;
esac
"""


def _run(
    run_id: int, status: str, conclusion: str | None, created: str, started: str | None
) -> dict[str, Any]:
    return {
        "id": run_id,
        "run_attempt": 1,
        "status": status,
        "conclusion": conclusion,
        "created_at": created,
        "run_started_at": started,
    }


def _run_select_script(
    tmp_path: Path,
    runs: list[dict[str, Any]],
    ready_events: list[str],
    *,
    pr_state: str = "open",
    pr_draft: bool = False,
    fresh_status: str = "completed",
) -> tuple[subprocess.CompletedProcess[str], Path]:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    pr_json = {"state": pr_state, "draft": pr_draft, "head": {"sha": "f" * 40}}
    (fixtures / "pr.json").write_text(json.dumps(pr_json), encoding="utf-8")
    (fixtures / "total_count.txt").write_text(f"{len(runs)}\n", encoding="utf-8")
    (fixtures / "runs.jsonl").write_text(
        "".join(json.dumps(run) + "\n" for run in runs), encoding="utf-8"
    )
    (fixtures / "ready_events.txt").write_text(
        "".join(ts + "\n" for ts in ready_events), encoding="utf-8"
    )
    (fixtures / "fresh_status.txt").write_text(f"{fresh_status}\n", encoding="utf-8")
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    shim = shim_dir / "gh"
    shim.write_text(_GH_SHIM, encoding="utf-8")
    shim.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"
    env["GH_FIXTURES"] = str(fixtures)
    env["GH_REPO"] = "synaptent/aragora"
    env["PR_NUMBER"] = "1234"
    proc = subprocess.run(
        ["bash", str(SELECT_SCRIPT_PATH)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    return proc, fixtures / "rerun.log"


class TestSelectionBehavior:
    """Run the real helper (bash + jq) against a fixture-backed fake gh."""

    def test_reruns_newest_ready_run_and_partitions_draft_era_runs(self, tmp_path: Path) -> None:
        proc, rerun_log = _run_select_script(
            tmp_path,
            runs=[
                _run(50, "completed", "success", "2026-08-16T09:00Z", "2026-08-16T09:01Z"),
                _run(300, "completed", "failure", "2026-08-16T10:05Z", "2026-08-16T10:06Z"),
            ],
            ready_events=["2026-08-16T10:00Z"],
        )
        assert proc.returncode == 0, proc.stderr
        assert rerun_log.read_text(encoding="utf-8") == "run rerun 300 --repo synaptent/aragora\n"
        assert "Re-running stale evaluation run 300" in proc.stdout

    def test_null_run_started_at_newest_run_cannot_lose_to_older_completed_run(
        self, tmp_path: Path
    ) -> None:
        """The coalesced key keeps a still-queued newest run (null
        run_started_at) newest instead of falling back to an older rerun."""
        proc, rerun_log = _run_select_script(
            tmp_path,
            runs=[
                _run(100, "completed", "failure", "2026-08-16T10:00Z", "2026-08-16T10:01Z"),
                _run(200, "queued", None, "2026-08-16T10:30Z", None),
            ],
            ready_events=[],
        )
        assert proc.returncode == 0, proc.stderr
        assert not rerun_log.exists(), "must not fall back to re-running the older evaluation"
        assert "run 200 is queued" in proc.stdout
        assert "no-op" in proc.stdout

    @pytest.mark.parametrize(
        ("pr_state", "pr_draft"),
        [("open", True), ("closed", False)],
        ids=["draft-pr", "closed-pr"],
    )
    def test_draft_or_closed_pr_defers_the_gate_with_no_rerun(
        self, tmp_path: Path, pr_state: str, pr_draft: bool
    ) -> None:
        """Drafts and closed PRs have no active gate to refresh: the helper
        must exit 0 before any selection, even with a stale failed run."""
        proc, rerun_log = _run_select_script(
            tmp_path,
            runs=[_run(300, "completed", "failure", "2026-08-16T10:05Z", "2026-08-16T10:06Z")],
            ready_events=[],
            pr_state=pr_state,
            pr_draft=pr_draft,
        )
        assert proc.returncode == 0, proc.stderr
        assert not rerun_log.exists(), "a gate-deferred PR must never produce a rerun"
        assert "gate not active; no-op" in proc.stdout
        assert "Re-running" not in proc.stdout

    def test_burst_loser_no_ops_when_fresh_status_is_no_longer_completed(
        self, tmp_path: Path
    ) -> None:
        """Burst dedup: the listing still shows a completed failure, but the
        fresh pre-rerun status read sees the concurrent winner's rerun
        already queued, so this surface must no-op instead of double-firing."""
        proc, rerun_log = _run_select_script(
            tmp_path,
            runs=[_run(300, "completed", "failure", "2026-08-16T10:05Z", "2026-08-16T10:06Z")],
            ready_events=[],
            fresh_status="queued",
        )
        assert proc.returncode == 0, proc.stderr
        assert not rerun_log.exists(), "the burst loser must not issue a second rerun"
        assert "concurrent retrigger won" in proc.stdout
