"""VAL-CDG-012 OpenAPI workflow contract: route/SDK exit integrity cannot be masked.

Static and behavioral guards for ``.github/workflows/openapi.yml`` — the single
active OpenAPI workflow (live workflow ID 226588000, required check name
``Generate & Validate``) — plus reference implementations of the live
execution-selection rules: unfiltered pagination ordered by
``(run_started_at, run_id, run_attempt)``, attempt-specific jobs/check URLs,
run-level release-bound artifacts, and the post-verification re-query/restart
rule.

Behavioral tests execute the workflow's actual ``run:`` bodies the way GitHub
does for the default shell (``bash -e``, no implicit pipefail) with
shell-function stubs standing in for named commands, mirroring
tests/ci/test_required_aggregator_fail_closed.py. The selection-rule helpers
mirror ``_paginate_runs`` / ``_plan_date_shards`` / ``_reconcile_run_ids`` /
``_attempt_numbers`` / ``_attempt_jobs_endpoint`` / ``_validate_attempt_jobs``
/ ``_validate_run_artifact`` from tests/scripts/test_contract_drift_workflow.py,
specialized to the OpenAPI workflow. The live GitHub census and execution
selection are exercised by the VAL-CDG-012 measurement itself; these tests pin
the rules and the repo-tree census so a drifting workflow fails here first.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"
WORKFLOW_PATH = WORKFLOWS_DIR / "openapi.yml"
TEXT = WORKFLOW_PATH.read_text(encoding="utf-8")
# BaseLoader keeps `on:` a string key and every scalar a string.
DOC = yaml.load(TEXT, Loader=yaml.BaseLoader)
JOBS = DOC["jobs"]

# Live census facts (verified against the GitHub API by the VAL-CDG-012
# measurement; pinned here so the repo-side topology cannot drift silently).
LIVE_CHECK_NAME = "Generate & Validate"
OPENAPI_WORKFLOW_ID = 226588000
RUNS_ENDPOINT_TEMPLATE = (
    f"repos/OWNER/REPO/actions/workflows/{OPENAPI_WORKFLOW_ID}/runs?per_page=100&page={{page}}"
)

# Steps in generate-run whose exit codes carry route-validation,
# SDK-verification, parity, or spec-integrity authority. None of them may mask
# a failure with continue-on-error, `|| true`, or an unconditional-success
# wrapper.
AUTHORITATIVE_STEPS = (
    "Generate OpenAPI spec",
    "Normalize OpenAPI spec metadata",
    "Enforce canonical OpenAPI version",
    "Validate spec structure",
    "Validate YAML output is parseable",
    "AST-only generation smoke test",
    "Generate TypeScript SDK types",
    "Generate Python SDK types",
    "Install OpenAPI validator",
    "Validate OpenAPI spec",
    "Audit documentation coverage",
    "Validate handler route coverage",
    "Check for missing operationIds (warning only)",
    "Verify SDK contracts against spec",
    "Check namespace SDK parity",
    "Run contract matrix tests",
    "Validate release envelope helper (dry run)",
)

# The complete continue-on-error census of the workflow. Every entry is a
# justified non-authoritative seam (see the workflow comments and the rearm PR
# body); anything new appearing here fails this contract until re-adjudicated.
JUSTIFIED_CONTINUE_ON_ERROR = {
    # Runner-resilience seam: the immediately following step re-verifies the
    # toolchain fail-closed under `set -euo pipefail`.
    ("generate-run", "Set up Python 3.11"),
    # PR-lane frontend generated types; the strict twin enforces this
    # generation on every push/schedule/dispatch execution.
    ("generate-run", "Generate Live API types (best-effort on PR)"),
    # Notification only; cannot affect any verdict.
    ("generate-run", "Comment on PR (if spec changed)"),
    # Manual-dispatch publish path, not a validation authority.
    ("sync", "Commit updated spec"),
}

# `|| true` is tolerated only inside non-authoritative recovery/publish steps
# (checkout self-repair, toolchain recovery attempts that are re-verified
# fail-closed, npm cache ownership repair, and the manual-dispatch sync
# publish path). No route validation, SDK verification, or parity step may
# ever appear here.
RECOVERY_STEPS_WITH_OR_TRUE = {
    ("scope", "Verify checkout integrity"),
    ("generate-run", "Verify checkout integrity"),
    ("generate-run", "Ensure python toolchain is available"),
    ("generate-run", "Fix npm cache ownership"),
    ("sync", "Verify checkout integrity"),
    ("sync", "Commit updated spec"),
    ("envelope", "Verify checkout integrity"),
}

_PIPE = re.compile(r"(?<!\|)\|(?!\|)")


def _steps(job_id: str) -> list[dict]:
    return JOBS[job_id]["steps"]


def _step(job_id: str, name: str) -> dict:
    for step in _steps(job_id):
        if step.get("name") == name:
            return step
    raise AssertionError(f"step {name!r} not found in job {job_id!r}")


def _step_index(job_id: str, name: str) -> int:
    for index, step in enumerate(_steps(job_id)):
        if step.get("name") == name:
            return index
    raise AssertionError(f"step {name!r} not found in job {job_id!r}")


def _shell_lines(run: str) -> list[str]:
    """Shell-significant lines of a run block (comment-only lines dropped)."""
    return [line for line in run.splitlines() if not line.strip().startswith("#")]


def _pipeline_lines(run: str) -> list[str]:
    return [line for line in _shell_lines(run) if _PIPE.search(line)]


def _pipefail_armed_before_first_pipe(run: str) -> bool:
    armed = False
    for line in _shell_lines(run):
        if "set -o pipefail" in line or "set -euo pipefail" in line:
            armed = True
        if _PIPE.search(line) and not armed:
            return False
    return True


def _simulate_step(
    run_block: str,
    *,
    env: dict[str, str],
    cwd: Path,
    stub_prelude: str = "",
) -> subprocess.CompletedProcess[str]:
    """Execute a workflow run block the way GitHub's default shell does
    (bash -e, no implicit pipefail), with optional shell-function stubs
    standing in for named commands."""
    return subprocess.run(
        ["bash", "-e", "-c", stub_prelude + run_block],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
    )


def _relocated(run: str, tmp_path: Path) -> str:
    """Relocate the workflow's /tmp scratch paths into the test's tmp dir so
    behavioral simulations stay hermetic. Command structure is unchanged."""
    return run.replace("/tmp/", f"{tmp_path}/")


# ---------------------------------------------------------------------------
# Reference live-selection rules (mirrors of test_contract_drift_workflow.py
# helpers, specialized to the OpenAPI workflow).
# ---------------------------------------------------------------------------


def _paginate_openapi_runs(fetch_page) -> tuple[list[dict], list[str]]:
    """Unfiltered per_page=100 pagination of the OpenAPI workflow's runs,
    terminating on a short page, rejecting duplicate run IDs. The endpoint
    carries no status/conclusion/event/branch filter."""
    records: list[dict] = []
    endpoints: list[str] = []
    page = 1
    while True:
        endpoint = RUNS_ENDPOINT_TEMPLATE.format(page=page)
        for forbidden in ("status=", "conclusion=", "event=", "branch="):
            if forbidden in endpoint:
                raise ValueError("workflow-run selection must be unfiltered")
        endpoints.append(endpoint)
        payload = fetch_page(endpoint)
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise ValueError("paginated workflow-run payload is malformed")
        records.extend(payload)
        if len(payload) < 100:
            break
        page += 1
        if page > 10_000:
            raise ValueError("workflow-run pagination did not terminate")
    ids = [run.get("id") for run in records]
    if len(ids) != len(set(ids)):
        raise ValueError("paginated workflow runs returned duplicate record IDs")
    return records, endpoints


def _attempt_numbers(run: dict) -> list[int]:
    attempt = run.get("run_attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError("run_attempt is malformed")
    return list(range(1, attempt + 1))


def _selection_key(run: dict) -> tuple[str, int, int]:
    started = run.get("run_started_at")
    if not isinstance(started, str) or not started:
        raise ValueError("run_started_at is malformed")
    run_id = run.get("id")
    if isinstance(run_id, bool) or not isinstance(run_id, int):
        raise ValueError("run id is malformed")
    return (started, run_id, _attempt_numbers(run)[-1])


def _select_newest_execution(records: list[dict]) -> dict:
    """Newest execution by (run_started_at, run_id, run_attempt) over the
    complete unfiltered record set."""
    if not records:
        raise ValueError("no workflow executions to select from")
    return max(records, key=_selection_key)


def _reconcile_total_count(records: list[dict], *, total_count: int | None) -> None:
    if total_count is not None and total_count != len(records):
        raise ValueError("workflow runs do not reconcile to the reported total_count")


def _plan_date_shards(
    daily_counts: dict[str, int], *, cap: int = 1000
) -> list[tuple[str, str, int]]:
    """Disjoint created-date ranges, each strictly below the 1000-result API
    window (only for filtered-history queries; primary selection stays
    unfiltered)."""
    shards: list[tuple[str, str, int]] = []
    current: list[str] = []
    total = 0
    for day in sorted(daily_counts):
        count = daily_counts[day]
        if count >= cap:
            raise ValueError(f"single-day run volume {count} defeats the {cap}-result window")
        if current and total + count >= cap:
            shards.append((current[0], current[-1], total))
            current, total = [], 0
        current.append(day)
        total += count
    if current:
        shards.append((current[0], current[-1], total))
    for (_, end_a, _), (start_b, _, _) in zip(shards, shards[1:]):
        if not end_a < start_b:
            raise ValueError("date shards overlap")
    if any(count >= cap for _, _, count in shards):
        raise ValueError(f"date shard reaches the {cap}-result cap")
    return shards


def _reconcile_run_ids(shards: list[dict], *, reported_total: int) -> list[int]:
    ids = [run["id"] for shard in shards for run in shard["workflow_runs"]]
    if len(ids) != len(set(ids)):
        raise ValueError("sharded run capture duplicated run IDs")
    for shard in shards:
        if shard["total_count"] != len(shard["workflow_runs"]):
            raise ValueError("shard total_count does not reconcile with captured runs")
    if reported_total != len(ids):
        raise ValueError("run IDs do not reconcile to the reported total_count")
    return sorted(ids)


def _attempt_jobs_endpoint(run_id: int, attempt: int) -> str:
    if attempt < 1:
        raise ValueError("attempt numbers start at 1")
    return f"repos/OWNER/REPO/actions/runs/{run_id}/attempts/{attempt}/jobs"


def _run_artifacts_endpoint(run_id: int) -> str:
    """Artifacts are run-level: the endpoint carries no attempt segment."""
    endpoint = f"repos/OWNER/REPO/actions/runs/{run_id}/artifacts"
    if "/attempts/" in endpoint:
        raise ValueError("artifact queries must be run-level, not attempt-level")
    return endpoint


def _validate_attempt_jobs(endpoint: str, jobs: list[dict], *, attempt: int) -> None:
    if f"/attempts/{attempt}/jobs" not in endpoint:
        raise ValueError("jobs endpoint is not attempt-specific")
    for job in jobs:
        if job.get("run_attempt") != attempt:
            raise ValueError("job record is not attempt-specific")
        if f"/attempts/{attempt}" not in job.get("check_url", ""):
            raise ValueError("check URL is not pinned to the requested attempt")


def _validate_run_artifact(artifact: dict, *, head_sha: str, release_digests: set[str]) -> str:
    name = artifact.get("name")
    if not isinstance(name, str) or not name.endswith(f"-{head_sha}"):
        raise ValueError("run artifact name is not SHA-bound")
    size = artifact.get("size_in_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ValueError("run artifact lacks a nonempty payload")
    if artifact.get("payload_sha256") not in release_digests:
        raise ValueError("run artifact payload is not bound to the immutable release")
    return name


def _selection_is_stable(before: dict, after: dict) -> bool:
    """Post-verification re-query rule: if main, execution identity, attempt,
    or conclusion moved, the whole selection restarts."""
    for key in ("main_sha", "run_id", "run_attempt", "conclusion"):
        if key not in before or key not in after:
            raise ValueError(f"selection snapshot is missing {key!r}")
        if before[key] != after[key]:
            return False
    return True


# ---------------------------------------------------------------------------
# census and trigger topology
# ---------------------------------------------------------------------------


def test_exactly_one_active_openapi_workflow():
    workflow_files = sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml"))
    assert workflow_files, "no workflow files found"
    named_openapi = [
        path
        for path in workflow_files
        if yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader).get("name")
        == "OpenAPI Spec"
    ]
    assert named_openapi == [WORKFLOW_PATH], (
        "exactly one workflow may declare the OpenAPI Spec pipeline; "
        f"found {[p.name for p in named_openapi]}"
    )
    assert DOC["name"] == "OpenAPI Spec"
    # The pinned live workflow ID is the selection-endpoint constant; the
    # VAL-CDG-012 measurement reconciles it against the GitHub API census
    # (102 workflows, exactly one active OpenAPI workflow).
    assert OPENAPI_WORKFLOW_ID == 226588000
    assert str(OPENAPI_WORKFLOW_ID) in RUNS_ENDPOINT_TEMPLATE


def test_no_duplicate_live_openapi_check_name():
    emitters: list[tuple[str, str]] = []
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml")):
        doc = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        for job_id, job in (doc.get("jobs") or {}).items():
            if isinstance(job, dict) and job.get("name") == LIVE_CHECK_NAME:
                emitters.append((path.name, job_id))
    assert emitters == [("openapi.yml", "generate")], (
        f"the live check name {LIVE_CHECK_NAME!r} must be emitted by exactly one job; "
        f"found {emitters}"
    )


def test_openapi_triggers_pr_main_schedule_dispatch():
    on = DOC["on"]
    assert set(on) == {"pull_request", "push", "schedule", "workflow_dispatch"}
    assert on["pull_request"]["types"] == ["opened", "synchronize", "reopened", "ready_for_review"]
    assert on["pull_request"]["branches"] == ["main"]
    assert on["push"]["branches"] == ["main"]
    assert on["schedule"] == [{"cron": "10 1 * * *"}]
    assert "workflow_dispatch" in on


# ---------------------------------------------------------------------------
# method-aware route and SDK authorities
# ---------------------------------------------------------------------------


def test_openapi_invokes_method_aware_route_and_sdk_authorities():
    route = _step("generate-run", "Validate handler route coverage")["run"]
    # Method-aware plane bound to the resolved exact execution SHA.
    assert 'EXEC_SHA="$(git rev-parse HEAD)"' in route
    assert "scripts/validate_openapi_routes.py" in route
    assert '--ref "${EXEC_SHA}"' in route
    # The workflow verifies the plane echoed the same exact-SHA binding back.
    assert 'plane.get("ref")' in route
    # The baseline-gated coverage check stays the fail-closed drift ratchet.
    assert "--fail-on-missing" in route
    assert "--baseline scripts/baselines/validate_openapi_routes.json" in route
    # The exact-ref refusal and the method-aware plane implementation exist in
    # the invoked authority (superseded heuristic mode is not the binding).
    validator_src = (ROOT / "scripts/validate_openapi_routes.py").read_text(encoding="utf-8")
    assert "_require_exact_ref" in validator_src
    assert "validate_method_aware_plane" in validator_src
    # SDK authorities: strict, baseline-pinned, method-aware by construction
    # (the extraction plane is method-bearing (method, path) operations; see
    # the named-group regexes in the authority source).
    verify = _step("generate-run", "Verify SDK contracts against spec")["run"]
    assert "scripts/verify_sdk_contracts.py" in verify
    assert "--strict" in verify
    assert "--baseline scripts/baselines/verify_sdk_contracts.json" in verify
    parity = _step("generate-run", "Check namespace SDK parity")["run"]
    assert "scripts/check_sdk_namespace_parity.py" in parity
    assert "--strict" in parity
    assert "--baseline scripts/baselines/check_sdk_namespace_parity.json" in parity
    sdk_src = (ROOT / "scripts/verify_sdk_contracts.py").read_text(encoding="utf-8")
    assert "(?P<method>" in sdk_src, "SDK contract authority lost its method-bearing extraction"


# ---------------------------------------------------------------------------
# live execution-selection rules (reference implementations)
# ---------------------------------------------------------------------------


def test_openapi_selects_newest_unfiltered_execution_by_started_run_attempt():
    pages = {
        1: [
            {"id": 100 + i, "run_started_at": f"2026-08-01T00:{i:02d}:00Z", "run_attempt": 1}
            for i in range(100)
        ],
        2: [
            {"id": 300, "run_started_at": "2026-08-02T00:00:00Z", "run_attempt": 2},
            {"id": 299, "run_started_at": "2026-08-02T00:00:00Z", "run_attempt": 1},
            {"id": 200, "run_started_at": "2026-07-31T00:00:00Z", "run_attempt": 5},
        ],
    }

    def fetch_page(endpoint: str) -> list[dict]:
        page = int(endpoint.rsplit("page=", 1)[1])
        return pages.get(page, [])

    records, endpoints = _paginate_openapi_runs(fetch_page)
    assert len(records) == 103
    assert endpoints[0] == RUNS_ENDPOINT_TEMPLATE.format(page=1)
    assert all("status=" not in e and "conclusion=" not in e for e in endpoints)
    _reconcile_total_count(records, total_count=103)
    newest = _select_newest_execution(records)
    # Run 299 shares run_started_at with run 300: the (run_id, run_attempt)
    # tie-breakers select run 300 attempt 2. A later attempt of an older run
    # (id 200, attempt 5) never outranks a newer execution.
    assert (newest["id"], newest["run_attempt"]) == (300, 2)
    with pytest.raises(ValueError, match="reconcile"):
        _reconcile_total_count(records, total_count=104)
    with pytest.raises(ValueError, match="duplicate"):
        _paginate_openapi_runs(
            lambda e: [{"id": 1, "run_started_at": "2026-08-01T00:00:00Z", "run_attempt": 1}] * 2
        )
    # Filtered-history fallback stays sharded strictly below the API window
    # with disjoint date ranges reconciling to the reported totals.
    shards = _plan_date_shards({"2026-08-01": 400, "2026-08-02": 400, "2026-08-03": 400})
    assert all(count < 1000 for _, _, count in shards)
    assert _reconcile_run_ids(
        [{"total_count": 1, "workflow_runs": [{"id": 7}]}], reported_total=1
    ) == [7]
    with pytest.raises(ValueError, match="defeats"):
        _plan_date_shards({"2026-08-01": 1000})


def test_openapi_queries_attempt_specific_jobs_checks_and_run_level_artifacts():
    run = {"id": 300, "run_started_at": "2026-08-02T00:00:00Z", "run_attempt": 3}
    assert _attempt_numbers(run) == [1, 2, 3]
    for attempt in _attempt_numbers(run):
        endpoint = _attempt_jobs_endpoint(300, attempt)
        jobs = [
            {
                "run_attempt": attempt,
                "check_url": f"repos/OWNER/REPO/check-runs/9/attempts/{attempt}",
            }
        ]
        _validate_attempt_jobs(endpoint, jobs, attempt=attempt)
    with pytest.raises(ValueError, match="attempt-specific"):
        _validate_attempt_jobs("repos/OWNER/REPO/actions/runs/300/jobs", [], attempt=2)
    with pytest.raises(ValueError, match="not attempt-specific"):
        _validate_attempt_jobs(
            _attempt_jobs_endpoint(300, 2),
            [{"run_attempt": 1, "check_url": "repos/OWNER/REPO/check-runs/9/attempts/2"}],
            attempt=2,
        )
    with pytest.raises(ValueError, match="malformed"):
        _attempt_numbers({"run_attempt": 0})
    artifacts_endpoint = _run_artifacts_endpoint(300)
    assert artifacts_endpoint.endswith("/actions/runs/300/artifacts")
    head = "a" * 40
    good = {"name": f"openapi-spec-{head}", "size_in_bytes": 10, "payload_sha256": "d" * 64}
    assert _validate_run_artifact(good, head_sha=head, release_digests={"d" * 64})
    with pytest.raises(ValueError, match="SHA-bound"):
        _validate_run_artifact(
            {"name": "openapi-spec", "size_in_bytes": 10, "payload_sha256": "d" * 64},
            head_sha=head,
            release_digests={"d" * 64},
        )
    with pytest.raises(ValueError, match="nonempty"):
        _validate_run_artifact(
            {"name": f"openapi-spec-{head}", "size_in_bytes": 0, "payload_sha256": "d" * 64},
            head_sha=head,
            release_digests={"d" * 64},
        )
    with pytest.raises(ValueError, match="immutable release"):
        _validate_run_artifact(
            {"name": f"openapi-spec-{head}", "size_in_bytes": 10, "payload_sha256": "e" * 64},
            head_sha=head,
            release_digests={"d" * 64},
        )


def test_openapi_restarts_if_main_execution_attempt_or_conclusion_moves():
    before = {"main_sha": "a" * 40, "run_id": 300, "run_attempt": 2, "conclusion": "success"}
    assert _selection_is_stable(before, dict(before))
    for key, moved in (
        ("main_sha", "b" * 40),
        ("run_id", 301),
        ("run_attempt", 3),
        ("conclusion", "failure"),
    ):
        after = dict(before)
        after[key] = moved
        assert not _selection_is_stable(before, after), f"movement in {key} must restart selection"
    with pytest.raises(ValueError, match="missing"):
        _selection_is_stable(before, {"main_sha": "a" * 40})


# ---------------------------------------------------------------------------
# authoritative steps propagate failure; pipefail before every pipeline
# ---------------------------------------------------------------------------


def test_openapi_authoritative_route_and_sdk_steps_propagate_nonzero_exit(tmp_path):
    for name in AUTHORITATIVE_STEPS:
        step = _step("generate-run", name)
        assert "continue-on-error" not in step, f"{name!r} may not continue-on-error"
        assert "always()" not in str(step.get("if", "")), f"{name!r} may not run unconditionally"
        assert "|| true" not in step["run"], f"{name!r} may not mask its exit with || true"
    # continue-on-error census: every occurrence is a justified
    # non-authoritative seam, and nothing else.
    census = {
        (job_id, step.get("name"))
        for job_id, job in JOBS.items()
        for step in job.get("steps", [])
        if "continue-on-error" in step
    }
    assert census == JUSTIFIED_CONTINUE_ON_ERROR
    # `|| true` census: non-authoritative recovery/publish steps only.
    or_true = {
        (job_id, step.get("name"))
        for job_id, job in JOBS.items()
        for step in job.get("steps", [])
        if "|| true" in step.get("run", "")
    }
    assert or_true <= RECOVERY_STEPS_WITH_OR_TRUE
    # The setup-python seam is closed by a fail-closed toolchain verification
    # immediately after it.
    steps = _steps("generate-run")
    setup_index = _step_index("generate-run", "Set up Python 3.11")
    ensure = steps[setup_index + 1]
    assert ensure["name"] == "Ensure python toolchain is available"
    assert "set -euo pipefail" in ensure["run"] and "exit 1" in ensure["run"]
    assert "continue-on-error" not in ensure
    # The PR-lane best-effort Live types step has a strict non-PR twin.
    strict_live = _step("generate-run", "Generate Live API types (strict)")
    assert strict_live["if"] == "github.event_name != 'pull_request'"
    assert "continue-on-error" not in strict_live
    best_effort = _step("generate-run", "Generate Live API types (best-effort on PR)")
    assert best_effort["if"] == "github.event_name == 'pull_request'"
    # Behavioral: a failing route authority fails the block even though a
    # successful consumer (tee) sits after it in the pipeline.
    route = _relocated(_step("generate-run", "Validate handler route coverage")["run"], tmp_path)
    fail_stub = (
        "git() { echo 0123456789abcdef0123456789abcdef01234567; }\n"
        "tee() { cat >/dev/null; return 0; }\n"
        'python() { if [ "${1:-}" = "scripts/validate_openapi_routes.py" ]; then return 1; fi; '
        "cat >/dev/null 2>/dev/null || true; return 0; }\n"
    )
    result = _simulate_step(route, env={}, cwd=tmp_path, stub_prelude=fail_stub)
    assert result.returncode != 0, "route authority failure was masked by the tee consumer"
    ok_stub = (
        "git() { echo 0123456789abcdef0123456789abcdef01234567; }\n"
        "tee() { cat >/dev/null; return 0; }\n"
        "python() { cat >/dev/null 2>/dev/null || true; return 0; }\n"
    )
    result = _simulate_step(route, env={}, cwd=tmp_path, stub_prelude=ok_stub)
    assert result.returncode == 0, result.stderr
    # Behavioral: the contract-matrix pytest exit code decides its step.
    matrix = _relocated(_step("generate-run", "Run contract matrix tests")["run"], tmp_path)
    for pytest_rc, expect_failure in ((1, True), (0, False)):
        stub = f"python() {{ return 0; }}\npytest() {{ return {pytest_rc}; }}\n"
        result = _simulate_step(matrix, env={}, cwd=tmp_path, stub_prelude=stub)
        assert (result.returncode != 0) is expect_failure, (
            f"contract-matrix rc={pytest_rc} must propagate; got {result.returncode}"
        )
    # Behavioral: a failing SDK verification authority fails its block.
    verify = _relocated(_step("generate-run", "Verify SDK contracts against spec")["run"], tmp_path)
    stub = "python() { return 1; }\n"
    result = _simulate_step(verify, env={}, cwd=tmp_path, stub_prelude=stub)
    assert result.returncode != 0, "SDK contract verification failure was masked"


def test_every_openapi_authoritative_pipeline_enables_pipefail_before_first_pipe():
    piped = []
    for name in AUTHORITATIVE_STEPS:
        run = _step("generate-run", name)["run"]
        if not _pipeline_lines(run):
            continue
        piped.append(name)
        assert _pipefail_armed_before_first_pipe(run), (
            f"{name!r} contains a pipeline before pipefail is armed"
        )
    # The census of authoritative piped steps must include the known two; a
    # new pipeline elsewhere is caught by the loop above.
    assert "Validate handler route coverage" in piped
    assert "Check for missing operationIds (warning only)" in piped
    # The gate aggregator arms pipefail unconditionally before any logic.
    gate_run = _steps("generate")[0]["run"]
    assert "set -euo pipefail" in gate_run


# ---------------------------------------------------------------------------
# summaries require parseable current-run output
# ---------------------------------------------------------------------------


def test_openapi_outputs_are_required_before_summary(tmp_path):
    route_index = _step_index("generate-run", "Validate handler route coverage")
    summary_index = _step_index("generate-run", "Generate contract drift summary")
    backlog_index = _step_index("generate-run", "Generate contract drift backlog seeds")
    assert route_index < summary_index < backlog_index
    summary = _step("generate-run", "Generate contract drift summary")["run"]
    backlog = _step("generate-run", "Generate contract drift backlog seeds")["run"]
    # Each summary step demands parseable current-run output BEFORE running
    # its generator (the generator is what presents the verdict).
    assert summary.index("json.load") < summary.index("scripts/contract_drift_report.py")
    assert backlog.index("json.load") < backlog.index("scripts/generate_contract_drift_backlog.py")
    # Behavioral: missing or unparseable current-run output fails the step
    # instead of presenting a verdict from stale inputs. The generator
    # scripts are stubbed; the json.load preconditions run under real python.
    stub = 'python() { case "${1:-}" in scripts/*) return 0;; *) command python3 "$@";; esac; }\n'
    summary_run = _relocated(summary, tmp_path)
    backlog_run = _relocated(backlog, tmp_path)
    result = _simulate_step(summary_run, env={}, cwd=tmp_path, stub_prelude=stub)
    assert result.returncode != 0, "summary presented a verdict without current-run output"
    (tmp_path / "route-coverage.json").write_text("{}", encoding="utf-8")
    api_dir = tmp_path / "docs" / "api"
    api_dir.mkdir(parents=True)
    (api_dir / "openapi_generated.json").write_text("{}", encoding="utf-8")
    result = _simulate_step(summary_run, env={}, cwd=tmp_path, stub_prelude=stub)
    assert result.returncode == 0, result.stderr
    result = _simulate_step(backlog_run, env={}, cwd=tmp_path, stub_prelude=stub)
    assert result.returncode != 0, "backlog seeded a verdict without the current-run summary"
    (tmp_path / "contract-drift-summary.json").write_text("{}", encoding="utf-8")
    result = _simulate_step(backlog_run, env={}, cwd=tmp_path, stub_prelude=stub)
    assert result.returncode == 0, result.stderr
    # Truncated current-run output is unparseable and must also fail.
    (tmp_path / "route-coverage.json").write_text('{"coverage', encoding="utf-8")
    result = _simulate_step(summary_run, env={}, cwd=tmp_path, stub_prelude=stub)
    assert result.returncode != 0


# ---------------------------------------------------------------------------
# the gate and the summary/artifact steps
# ---------------------------------------------------------------------------


def test_openapi_gate_has_no_continue_on_error_or_unconditional_success(tmp_path):
    gate = JOBS["generate"]
    assert gate["name"] == LIVE_CHECK_NAME
    assert gate["if"] == "always()"
    assert set(gate["needs"]) == {"scope", "generate-run"}
    assert "continue-on-error" not in str(gate)
    (step,) = gate["steps"]
    run = step["run"]
    assert "|| true" not in run
    env_map = step["env"]
    assert env_map["CLASSIFIER_RESULT"] == "${{ needs.scope.result }}"
    assert env_map["WORKER_RESULT"] == "${{ needs.generate-run.result }}"
    assert env_map["IN_SCOPE"] == "${{ needs.scope.outputs.run_openapi }}"
    cases = [
        # (classifier, worker, in_scope, expect_failure)
        ("success", "success", "true", False),
        ("success", "failure", "true", True),
        ("success", "cancelled", "true", True),
        ("success", "timed_out", "true", True),
        ("success", "skipped", "true", True),  # required work never ran
        ("success", "skipped", "false", False),  # legitimate out-of-scope skip
        ("success", "success", "false", True),  # out of scope yet ran: distrust
        ("success", "failure", "false", True),
        ("failure", "success", "true", True),  # classifier verdict untrusted
        ("failure", "skipped", "false", True),
        ("cancelled", "skipped", "false", True),
        ("skipped", "skipped", "false", True),
    ]
    for classifier, worker, in_scope, expect_failure in cases:
        result = _simulate_step(
            run,
            env={"CLASSIFIER_RESULT": classifier, "WORKER_RESULT": worker, "IN_SCOPE": in_scope},
            cwd=tmp_path,
        )
        assert (result.returncode != 0) is expect_failure, (
            f"gate(classifier={classifier}, worker={worker}, in_scope={in_scope}) "
            f"returned {result.returncode}"
        )


def test_openapi_summary_and_artifact_steps_cannot_rewrite_gate_conclusion():
    # The gate decides only from its dependencies' results and outputs.
    (gate_step,) = JOBS["generate"]["steps"]
    expressions = re.findall(r"\$\{\{\s*([^}]+?)\s*\}\}", str(gate_step))
    allowed = {
        "needs.scope.result",
        "needs.generate-run.result",
        "needs.scope.outputs.run_openapi",
    }
    assert set(expressions) <= allowed, f"gate reads unsupported expressions: {expressions}"
    # Summary/backlog steps may run after failure but cannot mask their own
    # failure, and never touch job outputs or conclusions.
    for name in ("Generate contract drift summary", "Generate contract drift backlog seeds"):
        step = _step("generate-run", name)
        assert step.get("if") == "always()"
        assert "continue-on-error" not in step
        assert "GITHUB_OUTPUT" not in step["run"] and "gh api" not in step["run"]
    # Artifact uploads carry only name/path/retention and cannot reinterpret
    # any outcome.
    uploads = [
        step
        for step in _steps("generate-run")
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert len(uploads) == 2
    for step in uploads:
        assert step["uses"] == "actions/upload-artifact@v4"
        assert set(step["with"]) <= {"name", "path", "retention-days", "overwrite"}
        assert "continue-on-error" not in step
        assert step.get("if") in (None, "always()")
    # No step anywhere in the workflow writes check runs, check conclusions,
    # or commit statuses.
    assert "checks.create" not in TEXT
    assert "check-runs" not in TEXT
    assert "statuses/" not in TEXT
    # The PR comment step is notification-only.
    comment = _step("generate-run", "Comment on PR (if spec changed)")
    script = comment["with"]["script"]
    assert "createComment" in script
    assert "conclusion" not in script


# ---------------------------------------------------------------------------
# FIX-RT-017: SHA/run-bound artifacts and the immutable release envelope
# ---------------------------------------------------------------------------

# The exact run/SHA binding suffix. `github.sha` is the merge SHA on
# pull_request events, so the pull-request head SHA must win there for the
# artifact name to end with the RUN's head_sha (the `-{head_sha}` rule that
# `_validate_run_artifact` pins). The attempt is deliberately NOT in the
# name: re-running only a failed dependent job (sync/envelope) increments
# the run attempt while the artifact keeps its original name, so an
# attempt-bearing name could never be downloaded again.
RUN_SHA_SUFFIX = "${{ github.run_id }}-${{ github.event.pull_request.head.sha || github.sha }}"
ENVELOPE_HELPER_PATH = ROOT / "scripts" / "openapi_release_envelope.py"
# Same pinned actions/attest release the ratified contract-drift boundary
# signer uses; a different (unreviewed) signer version fails this census.
ENVELOPE_ATTEST_ACTION = "actions/attest@508db95dd578ae2727ebd6217d5ba78e4fbda05d"
ENVELOPE_IF = (
    "github.event_name == 'workflow_dispatch' && inputs.publish_envelope == true"
    " && github.ref == 'refs/heads/main'"
)


def _load_envelope_helper():
    spec = importlib.util.spec_from_file_location("openapi_release_envelope", ENVELOPE_HELPER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _identity_kwargs(module, head: str, run_id: int = 7, run_attempt: int = 1) -> dict:
    return {
        "repository": "synaptent/aragora",
        "head_sha": head,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "artifact_name": f"openapi-spec-{run_id}-{head}",
    }


def _live_api_stub(module, identity: dict, head: str, overrides: list):
    """Fake `_gh_api_json` covering every live surface cmd_preflight/cmd_verify
    re-query (main ref, workflow, run, attempt record, artifacts, settings),
    with ordered per-endpoint `(marker, outcome)` overrides; an Exception
    outcome is raised, anything else returned. Tag probes default to Blocked
    (proven absence) so each test states only what it changes."""
    tag = identity["tag"]

    def fake_api(endpoint: str, **kwargs):
        for marker, outcome in overrides:
            if marker in endpoint:
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        if endpoint.endswith("immutable-releases"):
            return {"enabled": True}
        if "rule-suites" in endpoint:
            return [{"after_sha": head, "id": 9, "result": "pass"}]
        if endpoint.endswith("git/ref/heads/main"):
            return {"object": {"sha": head}}
        if "/actions/workflows/" in endpoint:
            return {
                "id": OPENAPI_WORKFLOW_ID,
                "path": ".github/workflows/openapi.yml",
                "state": "active",
            }
        if endpoint.endswith(f"/attempts/{identity['run_attempt']}"):
            return {
                "run_attempt": identity["run_attempt"],
                "head_sha": head,
                "conclusion": "success",
            }
        if endpoint.endswith("/artifacts?per_page=100"):
            return [
                {"artifacts": [{"name": identity["artifact_name"], "id": 91, "size_in_bytes": 10}]}
            ]
        if f"releases/tags/{tag}" in endpoint or f"git/ref/tags/{tag}" in endpoint:
            raise module.Blocked(f"{endpoint} is not visible: HTTP 404")
        return {
            "id": identity["run_id"],
            "path": ".github/workflows/openapi.yml",
            "head_sha": head,
            "run_attempt": identity["run_attempt"],
            "conclusion": "success",
        }

    return fake_api


def test_openapi_artifact_names_are_run_and_sha_bound():
    env = DOC.get("env") or {}
    assert env.get("OPENAPI_RUN_ARTIFACT") == f"openapi-spec-{RUN_SHA_SUFFIX}"
    assert env.get("DRIFT_RUN_ARTIFACT") == f"contract-drift-artifacts-{RUN_SHA_SUFFIX}"
    spec_upload = _step("generate-run", "Upload generated spec and SDK types")
    assert spec_upload["with"]["name"] == "${{ env.OPENAPI_RUN_ARTIFACT }}"
    drift_upload = _step("generate-run", "Upload contract drift artifacts")
    assert drift_upload["with"]["name"] == "${{ env.DRIFT_RUN_ARTIFACT }}"
    # v4 artifacts are immutable per run and the name carries no attempt, so
    # a re-run of all jobs must overwrite rather than 409 on its own name.
    assert spec_upload["with"]["overwrite"] == "true"
    assert drift_upload["with"]["overwrite"] == "true"
    # Every artifact consumer resolves the same run-bound name.
    sync_download = _step("sync", "Download generated spec")
    assert sync_download["with"]["name"] == "${{ env.OPENAPI_RUN_ARTIFACT }}"
    envelope_download = _step("envelope", "Download run-level spec artifact")
    assert envelope_download["with"]["name"] == "${{ env.OPENAPI_RUN_ARTIFACT }}"
    # No fixed-name expiring artifact remains anywhere in the workflow.
    assert "name: openapi-spec\n" not in TEXT
    assert "name: contract-drift-artifacts\n" not in TEXT


def test_openapi_envelope_job_is_dispatch_gated_and_attests_exact_assets():
    job = JOBS["envelope"]
    assert job["needs"] == ["generate-run", "sync"]
    assert job["if"] == ENVELOPE_IF
    # actions:read is load-bearing: the explicit permissions block zeroes
    # unlisted scopes, and preflight/verify re-query the workflow, run, and
    # run-level artifacts through the actions API.
    assert job["permissions"] == {
        "contents": "write",
        "id-token": "write",
        "attestations": "write",
        "actions": "read",
    }
    for step in job["steps"]:
        assert "continue-on-error" not in step, step.get("name")
        if step.get("name") != "Verify checkout integrity":
            assert "|| true" not in step.get("run", ""), step.get("name")
    # A bare dispatch can never publish: the input defaults off.
    dispatch = DOC["on"]["workflow_dispatch"]
    publish_input = dispatch["inputs"]["publish_envelope"]
    assert publish_input["type"] == "boolean"
    assert publish_input["default"] == "false"
    assert publish_input["required"] == "false"
    # Envelope construction hashes the exact downloaded run-payload bytes and
    # re-authenticates them with sha256sum --check --strict.
    build = _step("envelope", "Build deterministic release envelope")["run"]
    assert "set -euo pipefail" in build
    assert "scripts/openapi_release_envelope.py build" in build
    for flag in ("--repository", "--head-sha", "--run-id", "--run-attempt", "--artifact-name"):
        assert flag in build, flag
    assert "sha256sum --check --strict checksums.txt" in build
    # The release is published (not draft) at the exact-SHA tag.
    publish = _step("envelope", "Publish immutable release")["run"]
    assert "set -euo pipefail" in publish
    assert "gh release create" in publish
    assert "--draft" not in publish
    assert "openapi-envelope-$GITHUB_SHA" in publish
    assert '--target "$GITHUB_SHA"' in publish
    # Exact assets are attested with the pinned signer action.
    attest = _step("envelope", "Attest the envelope assets")
    assert attest["uses"] == ENVELOPE_ATTEST_ACTION
    assert "# v4.2.1" in TEXT
    assert attest["with"]["subject-path"].strip() == "/tmp/openapi-envelope/assets/*"
    # Preflight proves attestations, tag availability, capability, and that
    # main is still at the bound head BEFORE anything irreversible runs.
    preflight = _step("envelope", "Preflight verify before publication")["run"]
    assert "set -euo pipefail" in preflight
    assert "scripts/openapi_release_envelope.py preflight" in preflight
    assert "--assets-dir" in preflight
    assert "--admin-reads report" in preflight
    assert "gh --version" in preflight
    # The irreversible publication is the LAST mutating step: build, attest,
    # and preflight all precede it, so no failure can strand a half-published
    # immutable capsule.
    order = [
        _step_index("envelope", name)
        for name in (
            "Build deterministic release envelope",
            "Attest the envelope assets",
            "Preflight verify before publication",
            "Publish immutable release",
            "Verify release, assets, attestation, and rule suite",
        )
    ]
    assert order == sorted(order), "envelope steps out of publication-safety order"
    # Verification binds release, assets, attestation, and rule suite to this
    # workflow as the signer, with movement-requery semantics in the helper.
    verify = _step("envelope", "Verify release, assets, attestation, and rule suite")["run"]
    assert "set -euo pipefail" in verify
    assert "scripts/openapi_release_envelope.py verify" in verify
    assert "--signer-workflow" in verify
    assert ".github/workflows/openapi.yml" in verify
    # The workflow token lacks Administration read, so in-run verification
    # must degrade admin-gated reads to report mode (never exit 1 for a
    # capability gap after publication).
    assert "--admin-reads report" in verify


def test_openapi_envelope_serializes_sync_before_publication_preflight():
    """A publish_envelope=true dispatch also runs sync, which can push a
    spec-drift commit to main. Needing sync serializes any such push BEFORE
    envelope preflight's main-still-at-bound-head check, so the movement is
    the free pre-publication exit-3 restart instead of a post-publish
    supersession record against an already-immutable capsule."""
    envelope = JOBS["envelope"]
    assert envelope["needs"] == ["generate-run", "sync"]
    # The dependency is satisfiable exactly when envelope runs: sync gates on
    # the same dispatch+main events (envelope only adds the publish input),
    # so needing sync can never wedge a publish dispatch, and gating drift
    # between the two jobs fails here first.
    sync = JOBS["sync"]
    assert sync["needs"] == "generate-run"
    assert (
        sync["if"] == "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'"
    )
    for clause in ("github.event_name == 'workflow_dispatch'", "github.ref == 'refs/heads/main'"):
        assert clause in sync["if"]
        assert clause in ENVELOPE_IF


def test_envelope_operator_immutable_releases_attestation_input_defaults_false():
    """In-run report-mode preflight cannot distinguish the admin-gated 404
    "hidden from this token" from "immutable releases disabled", so a
    disabled setting would otherwise surface only post-publish. The dispatch
    input machine-checks the operator's admin-capable {"enabled":true}
    pre-dispatch read when publishing, but stays optional/default-off so an
    omitted input cannot break bare sync-only dispatches."""
    dispatch = DOC["on"]["workflow_dispatch"]
    attestation = dispatch["inputs"]["operator_confirmed_immutable_releases"]
    assert attestation["type"] == "boolean"
    assert "required" not in attestation
    assert attestation["default"] == "false"
    description = attestation["description"]
    assert "immutable-releases" in description
    assert '{"enabled":true}' in description


def test_envelope_gate_fails_closed_without_operator_attestation(tmp_path):
    """The attestation gate is the FIRST envelope step: unless the input is
    exactly the string true it exits 2 (blocked) before any download,
    attestation, or publication step runs. It machine-checks the operator's
    pre-dispatch admin-capable check WITHOUT weakening in-run degradation:
    preflight/verify keep --admin-reads report so the non-admin workflow
    token can never wedge, and no other job consumes the input."""
    gate = _steps("envelope")[0]
    assert gate.get("name") == "Require operator immutable-releases attestation"
    assert "continue-on-error" not in gate
    assert "if" not in gate
    assert (gate.get("env") or {}).get("OPERATOR_CONFIRMED") == (
        "${{ inputs.operator_confirmed_immutable_releases }}"
    )
    run = gate["run"]
    assert "set -euo pipefail" in run
    # Every non-"true" value (including the empty string an expression-drift
    # would interpolate) must block with exit 2 and publish nothing.
    for value in ("false", "", "1", "True"):
        blocked = _simulate_step(run, env={"OPERATOR_CONFIRMED": value}, cwd=tmp_path)
        assert blocked.returncode == 2, (value, blocked.stdout, blocked.stderr)
        assert "blocked" in blocked.stdout + blocked.stderr, value
    confirmed = _simulate_step(run, env={"OPERATOR_CONFIRMED": "true"}, cwd=tmp_path)
    assert confirmed.returncode == 0, (confirmed.stdout, confirmed.stderr)
    # The gate precedes every payload/publication step in the job.
    gate_index = _step_index("envelope", "Require operator immutable-releases attestation")
    for name in (
        "Download run-level spec artifact",
        "Build deterministic release envelope",
        "Attest the envelope assets",
        "Preflight verify before publication",
        "Publish immutable release",
    ):
        assert gate_index < _step_index("envelope", name), name
    # Degradation semantics unchanged: in-run preflight and post-publish
    # verify still degrade admin-gated reads under report mode.
    assert "--admin-reads report" in _step("envelope", "Preflight verify before publication")["run"]
    assert (
        "--admin-reads report"
        in _step("envelope", "Verify release, assets, attestation, and rule suite")["run"]
    )
    # Only the envelope job consumes the attestation; a plain sync dispatch
    # is never gated by it.
    for job_id, job in JOBS.items():
        if job_id != "envelope":
            assert "operator_confirmed_immutable_releases" not in json.dumps(job), job_id


def test_openapi_envelope_helper_dry_run_is_a_pr_time_authority():
    # The dry-run proof runs on every generate-run execution and is part of
    # the no-masking census (AUTHORITATIVE_STEPS).
    assert "Validate release envelope helper (dry run)" in AUTHORITATIVE_STEPS
    step = _step("generate-run", "Validate release envelope helper (dry run)")
    assert "set -euo pipefail" in step["run"]
    assert "scripts/openapi_release_envelope.py dry-run" in step["run"]
    assert "if" not in step


def test_envelope_build_is_deterministic_and_release_bound():
    module = _load_envelope_helper()
    head = "a" * 40
    identity = module.make_identity(**_identity_kwargs(module, head))
    payloads = {
        "docs/api/openapi_generated.json": b'{"openapi":"3.1.0"}\n',
        "sdk/python/aragora/generated_types.py": b"GENERATED = True\n",
    }
    first = module.build_envelope(payloads, identity)
    second = module.build_envelope(dict(payloads), identity)
    assert first == second, "envelope bytes must be deterministic"
    assert set(first) == {
        "manifest.json",
        "checksums.txt",
        "openapi_generated.json",
        "generated_types.py",
    }
    manifest = json.loads(first["manifest.json"])
    assert manifest["repository"] == "synaptent/aragora"
    assert manifest["head_sha"] == head
    assert manifest["workflow_run_id"] == 7
    assert manifest["run_attempt"] == 1
    assert manifest["artifact_name"] == f"openapi-spec-7-{head}"
    assert manifest["tag"] == f"openapi-envelope-{head}"
    assert manifest["workflow_path"] == ".github/workflows/openapi.yml"
    # Canonical bytes: re-serializing the parsed manifest reproduces the
    # exact on-release bytes.
    assert module.canonical_json_bytes(manifest) == first["manifest.json"]
    # checksums.txt is sha256sum-compatible, sorted, and covers every payload
    # asset plus the manifest (never itself).
    lines = first["checksums.txt"].decode("ascii").splitlines()
    names = [line.split("  ", 1)[1] for line in lines]
    assert names == sorted(names)
    assert set(names) == {"manifest.json", "openapi_generated.json", "generated_types.py"}
    for line in lines:
        assert re.fullmatch(r"[0-9a-f]{64}  [^/\s]+", line)
    # Round-trip verification passes and the digest set release-binds the
    # run-level artifact under the VAL-CDG-012 rule.
    verified = module.verify_envelope_assets(first, identity)
    assert verified["head_sha"] == head
    digests = module.release_digest_set(first)
    artifact = {
        "name": identity["artifact_name"],
        "size_in_bytes": 20,
        "payload_sha256": manifest["payload_assets"][0]["sha256"],
    }
    assert _validate_run_artifact(artifact, head_sha=head, release_digests=digests)
    # A digest the release never published is not bound.
    foreign = dict(artifact, payload_sha256="f" * 64)
    with pytest.raises(ValueError, match="not bound"):
        _validate_run_artifact(foreign, head_sha=head, release_digests=digests)


def test_envelope_rejects_unbound_names_and_tampered_assets():
    module = _load_envelope_helper()
    head = "b" * 40
    base = _identity_kwargs(module, head)
    identity = module.make_identity(**base)
    # Hostile identities: fixed (unbound) name, wrong run, attempt-bearing
    # legacy name, foreign head, non-canonical SHA, non-positive run/attempt.
    for kwargs in (
        dict(base, artifact_name="openapi-spec"),
        dict(base, artifact_name=f"openapi-spec-8-{head}"),
        dict(base, artifact_name=f"openapi-spec-7-1-{head}"),
        dict(base, artifact_name=f"openapi-spec-7-{'c' * 40}"),
        dict(base, head_sha=head.upper(), artifact_name=f"openapi-spec-7-{head.upper()}"),
        dict(base, head_sha="b" * 39, artifact_name=f"openapi-spec-7-{'b' * 39}"),
        dict(base, run_id=0, artifact_name=f"openapi-spec-0-{head}"),
        dict(base, run_attempt=0),
        dict(base, repository="aragora"),
    ):
        with pytest.raises(ValueError):
            module.make_identity(**kwargs)
    assets = module.build_envelope({"a.json": b"{}\n"}, identity)
    # Tampered payload bytes.
    tampered = dict(assets, **{"a.json": b"{ }\n"})
    with pytest.raises(ValueError):
        module.verify_envelope_assets(tampered, identity)
    # Renamed, missing, and extra assets.
    renamed = {("b.json" if key == "a.json" else key): value for key, value in assets.items()}
    with pytest.raises(ValueError):
        module.verify_envelope_assets(renamed, identity)
    missing = {key: value for key, value in assets.items() if key != "a.json"}
    with pytest.raises(ValueError):
        module.verify_envelope_assets(missing, identity)
    extra = dict(assets, **{"rogue.bin": b"x"})
    with pytest.raises(ValueError):
        module.verify_envelope_assets(extra, identity)
    # Tampered checksum line.
    digest = assets["checksums.txt"].decode("ascii").split("  ", 1)[0]
    flipped = ("0" if digest[0] != "0" else "1") + digest[1:]
    with pytest.raises(ValueError):
        module.verify_envelope_assets(
            dict(
                assets,
                **{
                    "checksums.txt": assets["checksums.txt"].replace(
                        digest.encode("ascii"), flipped.encode("ascii")
                    )
                },
            ),
            identity,
        )
    # Verifying under a different execution identity fails.
    other = module.make_identity(**_identity_kwargs(module, head, run_id=8))
    with pytest.raises(ValueError):
        module.verify_envelope_assets(assets, other)
    # Non-canonical manifest bytes fail even with a recomputed checksum line.
    noncanonical = json.dumps(json.loads(assets["manifest.json"]), indent=2).encode("ascii")
    rebuilt = dict(assets, **{"manifest.json": noncanonical})
    manifest_digest = module.sha256_hexdigest(assets["manifest.json"])
    rebuilt["checksums.txt"] = assets["checksums.txt"].replace(
        manifest_digest.encode("ascii"),
        module.sha256_hexdigest(noncanonical).encode("ascii"),
    )
    with pytest.raises(ValueError):
        module.verify_envelope_assets(rebuilt, identity)
    # Empty payloads are never publishable.
    with pytest.raises(ValueError):
        module.build_envelope({}, identity)
    with pytest.raises(ValueError):
        module.build_envelope({"a.json": b""}, identity)


def test_envelope_selection_movement_restarts_verification():
    module = _load_envelope_helper()
    before = {
        "main_sha": "a" * 40,
        "workflow_id": OPENAPI_WORKFLOW_ID,
        "run_id": 300,
        "run_attempt": 2,
        "latest_run_attempt": 2,
        "conclusion": "success",
        "artifact_id": 91,
        "artifact_size": 1024,
    }
    assert module.selection_is_stable(before, dict(before))
    for key, moved in (
        ("main_sha", "b" * 40),
        ("workflow_id", 1),
        ("run_id", 301),
        ("run_attempt", 3),
        # A re-run landing DURING the verification window restarts it even
        # though the bound attempt's own record is immutable.
        ("latest_run_attempt", 3),
        ("conclusion", "failure"),
        ("artifact_id", 92),
        ("artifact_size", 2048),
    ):
        after = dict(before)
        after[key] = moved
        assert not module.selection_is_stable(before, after), (
            f"movement in {key} must restart verification"
        )
        # Execution-provenance movement is always a restart; ONLY a bare
        # main advance classifies as supersession (a published immutable
        # capsule stays byte-valid for its exact SHA and must not strand).
        expected = "superseded" if key == "main_sha" else "restart"
        assert module.movement_disposition(before, after) == expected, key
    assert module.movement_disposition(before, dict(before)) == "stable"
    moved_both = dict(before, main_sha="b" * 40, run_attempt=3)
    assert module.movement_disposition(before, moved_both) == "restart"
    with pytest.raises(ValueError, match="missing"):
        module.selection_is_stable(before, {"main_sha": "a" * 40})
    with pytest.raises(ValueError, match="missing"):
        module.movement_disposition(before, {"main_sha": "a" * 40})


def test_envelope_admin_reads_degrade_only_on_true_capability_gaps(monkeypatch):
    module = _load_envelope_helper()
    head = "d" * 40
    repo = "synaptent/aragora"
    real_api = module._gh_api_json

    def forbidden(endpoint, **kwargs):
        raise module.Forbidden(f"{endpoint} is not readable by this token: HTTP 403")

    # HTTP 403 (the workflow GITHUB_TOKEN lacks Administration:read): report
    # mode records the gap and degrades; required mode blocks.
    monkeypatch.setattr(module, "_gh_api_json", forbidden)
    assert module._immutability_state(repo, admin_reads="report").startswith("unreadable")
    with pytest.raises(module.Forbidden):
        module._immutability_state(repo, admin_reads="required")
    degraded = module._rule_suite_binding(repo, head, admin_reads="report")
    assert degraded["state"] == "unverified"
    with pytest.raises(module.Forbidden):
        module._rule_suite_binding(repo, head, admin_reads="required")
    # A READABLE surface keeps full fail-closed semantics in BOTH modes:
    # degradation never substitutes for an answer the token could see.
    monkeypatch.setattr(module, "_gh_api_json", lambda endpoint, **kwargs: {"enabled": False})
    with pytest.raises(RuntimeError, match="not enabled"):
        module._immutability_state(repo, admin_reads="report")
    monkeypatch.setattr(module, "_gh_api_json", lambda endpoint, **kwargs: [])
    with pytest.raises(module.Blocked, match="no rule-suite record"):
        module._rule_suite_binding(repo, head, admin_reads="report")
    monkeypatch.setattr(
        module,
        "_gh_api_json",
        lambda endpoint, **kwargs: [{"after_sha": head, "id": 5, "result": "fail"}],
    )
    with pytest.raises(RuntimeError, match="concluded"):
        module._rule_suite_binding(repo, head, admin_reads="report")
    # GitHub hides admin-gated settings behind HTTP 404 (not 403) from
    # tokens without Administration:read: that 404 is a capability gap
    # (Forbidden, degradable), while the same 404 on an ordinary endpoint
    # stays Blocked.
    hidden = subprocess.CompletedProcess(
        args=["gh"], returncode=1, stdout=b"", stderr=b"HTTP 404 Not Found"
    )
    monkeypatch.setattr(module, "_run_gh", lambda argv: hidden)
    monkeypatch.setattr(module, "_gh_api_json", real_api)
    with pytest.raises(module.Forbidden):
        module._gh_api_json(f"repos/{repo}/immutable-releases", admin_gated=True)
    with pytest.raises(module.Blocked):
        module._gh_api_json(f"repos/{repo}/releases/tags/x")
    assert module._immutability_state(repo, admin_reads="report").startswith("unreadable")


def test_envelope_preflight_tag_probes_treat_forbidden_as_blocked(monkeypatch, tmp_path, capsys):
    """Tag absence must be PROVEN before publication. Forbidden subclasses
    Blocked, so a rate-limit/permission 403 on either tag probe must surface
    as blocked (exit 2) instead of reading as "tag unused" and letting the
    irreversible `gh release create` proceed over a possibly-existing tag."""
    module = _load_envelope_helper()
    head = "f" * 40
    identity = module.make_identity(**_identity_kwargs(module, head, run_id=55))
    assets = module.build_envelope(
        {"docs/api/openapi_generated.json": b'{"openapi":"3.1.0"}\n'}, identity
    )
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    for name, data in assets.items():
        (assets_dir / name).write_bytes(data)
    fake_run, _state = _preflight_gh_stub(module)
    monkeypatch.setattr(module, "_run_gh", fake_run)
    args = argparse.Namespace(
        repository="synaptent/aragora",
        head_sha=head,
        run_id=55,
        run_attempt=1,
        artifact_name=identity["artifact_name"],
        assets_dir=str(assets_dir),
        signer_workflow="",
        admin_reads="report",
    )
    tag = identity["tag"]
    forbidden = module.Forbidden("HTTP 403 rate limit exceeded")
    # Control: proven absence (404 on both probes) preflights clean.
    monkeypatch.setattr(module, "_gh_api_json", _live_api_stub(module, identity, head, []))
    assert module.cmd_preflight(args) == module.EXIT_PASS
    assert json.loads(capsys.readouterr().out)["status"] == "pass"
    # A readable existing release tag still fails closed, never retries.
    monkeypatch.setattr(
        module,
        "_gh_api_json",
        _live_api_stub(module, identity, head, [(f"releases/tags/{tag}", {"id": 1})]),
    )
    assert module.cmd_preflight(args) == module.EXIT_FAIL
    assert json.loads(capsys.readouterr().out)["status"] == "fail"
    # Forbidden on the release-tag probe: blocked, never absence.
    monkeypatch.setattr(
        module,
        "_gh_api_json",
        _live_api_stub(module, identity, head, [(f"releases/tags/{tag}", forbidden)]),
    )
    assert module.cmd_preflight(args) == module.EXIT_BLOCKED
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"
    # Forbidden on the bare-git-tag probe: same.
    monkeypatch.setattr(
        module,
        "_gh_api_json",
        _live_api_stub(module, identity, head, [(f"git/ref/tags/{tag}", forbidden)]),
    )
    assert module.cmd_preflight(args) == module.EXIT_BLOCKED
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


def test_envelope_post_publish_release_verify_lag_blocks_not_fails(monkeypatch, tmp_path, capsys):
    """`gh release verify`/`verify-asset` read the same Sigstore data plane as
    `gh attestation verify`; immediately after publication that data can lag.
    Lag is a Blocked retry state (exit 2), never a byte contradiction (exit
    1) — while a readable verification contradiction still fails closed."""
    module = _load_envelope_helper()
    head = "e" * 40
    identity = module.make_identity(**_identity_kwargs(module, head, run_id=66))
    assets = module.build_envelope(
        {"docs/api/openapi_generated.json": b'{"openapi":"3.1.0"}\n'}, identity
    )
    tag = identity["tag"]
    release = {
        "id": 4242,
        "draft": False,
        "immutable": True,
        "assets": [{"name": name, "size": len(data)} for name, data in assets.items()],
    }
    monkeypatch.setattr(
        module,
        "_gh_api_json",
        _live_api_stub(
            module,
            identity,
            head,
            [
                (f"releases/tags/{tag}", release),
                (f"git/ref/tags/{tag}", {"object": {"type": "commit", "sha": head}}),
            ],
        ),
    )

    def run_stub(lagging: set, failing: set | frozenset = frozenset()):
        def fake_run(argv):
            module.require_read_only_argv(argv)
            action = tuple(argv[1:3])
            if action == ("release", "download"):
                dest = Path(argv[argv.index("--dir") + 1])
                for name, data in assets.items():
                    (dest / name).write_bytes(data)
                return subprocess.CompletedProcess(argv, 0, b"", b"")
            if action in lagging:
                return subprocess.CompletedProcess(
                    argv, 1, b"", b"no attestations found for the requested subject yet"
                )
            if action in failing:
                return subprocess.CompletedProcess(argv, 1, b"", b"subject digest mismatch")
            return subprocess.CompletedProcess(argv, 0, b"{}", b"")

        return fake_run

    args = argparse.Namespace(
        repository="synaptent/aragora",
        head_sha=head,
        run_id=66,
        run_attempt=1,
        artifact_name=identity["artifact_name"],
        signer_workflow="",
        admin_reads="report",
    )
    monkeypatch.setattr(module, "_run_gh", run_stub({("release", "verify")}))
    assert module.cmd_verify(args) == module.EXIT_BLOCKED
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"
    monkeypatch.setattr(module, "_run_gh", run_stub({("release", "verify-asset")}))
    assert module.cmd_verify(args) == module.EXIT_BLOCKED
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"
    monkeypatch.setattr(module, "_run_gh", run_stub(set(), {("release", "verify")}))
    assert module.cmd_verify(args) == module.EXIT_FAIL
    assert json.loads(capsys.readouterr().out)["status"] == "fail"


def test_envelope_module_docstring_names_attempt_free_artifact_form():
    """The artifact name deliberately carries no attempt (attempt binding
    lives in the manifest and the movement plane); an attempt-bearing name in
    the module docstring misdocuments that design."""
    doc = _load_envelope_helper().__doc__
    assert "``openapi-spec-<run_id>-<head_sha>``" in doc
    assert "<attempt>" not in doc


def test_envelope_module_docstring_names_admin_gated_404_degradation():
    """Report mode degrades on BOTH capability-gap classes: a true HTTP 403
    and the admin-gated HTTP 404 mapping (hidden-from-token is in-run
    indistinguishable from a disabled setting). Claiming degradation happens
    only on 403 misdocuments the second class."""
    doc = _load_envelope_helper().__doc__
    assert "admin-gated HTTP 404" in doc
    assert "only on a true HTTP 403" not in doc


def test_envelope_snapshot_binds_attempt_record_and_survives_settled_reruns(monkeypatch):
    module = _load_envelope_helper()
    head = "e" * 40
    identity = module.make_identity(**_identity_kwargs(module, head, run_id=44))
    latest = {"seen": []}

    def fake_api(endpoint, **kwargs):
        latest["seen"].append(endpoint)
        if endpoint.endswith("git/ref/heads/main"):
            return {"object": {"sha": head}}
        if "/actions/workflows/" in endpoint:
            return {"id": 7001, "path": ".github/workflows/openapi.yml", "state": "active"}
        if endpoint.endswith("/attempts/1"):
            # The bound attempt's immutable record: still head-bound and
            # successful even after a later re-run.
            return {"run_attempt": 1, "head_sha": head, "conclusion": "success"}
        if endpoint.endswith("/artifacts?per_page=100"):
            return [
                {"artifacts": [{"name": identity["artifact_name"], "id": 91, "size_in_bytes": 10}]}
            ]
        # The run-level object reports only the LATEST attempt.
        return {
            "id": 44,
            "path": ".github/workflows/openapi.yml",
            "head_sha": head,
            "run_attempt": 2,
            "conclusion": "failure",
        }

    monkeypatch.setattr(module, "_gh_api_json", fake_api)
    snapshot = module.live_selection_snapshot(identity)
    # A settled newer attempt must NOT wedge the bound capsule: the snapshot
    # binds the attempt record (attempt 1, success) and reports the latest
    # attempt on the movement plane instead of raising.
    assert snapshot["run_attempt"] == 1
    assert snapshot["latest_run_attempt"] == 2
    assert snapshot["conclusion"] == "success"
    assert any(endpoint.endswith("/actions/runs/44/attempts/1") for endpoint in latest["seen"])
    assert module.selection_is_stable(snapshot, module.live_selection_snapshot(identity))
    assert set(snapshot) == set(module.SELECTION_KEYS)


def test_envelope_verification_argv_and_read_only_guard():
    module = _load_envelope_helper()
    head = "c" * 40
    tag = f"openapi-envelope-{head}"
    signer = "synaptent/aragora/.github/workflows/openapi.yml"
    assert module.attestation_verify_argv(
        "/tmp/x/manifest.json",
        repository="synaptent/aragora",
        head_sha=head,
        signer_workflow=signer,
    ) == [
        "gh",
        "attestation",
        "verify",
        "/tmp/x/manifest.json",
        "-R",
        "synaptent/aragora",
        "--signer-workflow",
        signer,
        "--source-digest",
        head,
        "--format",
        "json",
    ]
    assert module.release_verify_argv(tag, repository="synaptent/aragora") == [
        "gh",
        "release",
        "verify",
        tag,
        "-R",
        "synaptent/aragora",
        "--format",
        "json",
    ]
    assert module.release_verify_asset_argv(
        tag, "/tmp/x/manifest.json", repository="synaptent/aragora"
    ) == [
        "gh",
        "release",
        "verify-asset",
        tag,
        "/tmp/x/manifest.json",
        "-R",
        "synaptent/aragora",
        "--format",
        "json",
    ]
    # The helper is read-only: mutating argv is rejected before execution.
    for hostile in (
        ["gh", "release", "create", tag],
        ["gh", "release", "delete", tag],
        ["gh", "release", "edit", tag],
        ["gh", "api", "-X", "DELETE", "repos/synaptent/aragora/releases/1"],
        ["gh", "api", "--method", "POST", "repos/synaptent/aragora/releases"],
        # pflag attached-shorthand forms must not slip past the guard.
        ["gh", "api", "-XPOST", "repos/synaptent/aragora/releases"],
        ["gh", "api", "--method=POST", "repos/synaptent/aragora/releases"],
        ["gh", "api", "-fname=v", "repos/synaptent/aragora/releases"],
        ["gh", "api", "-Fname=v", "repos/synaptent/aragora/releases"],
        ["gh", "api", "-f", "name=v", "repos/synaptent/aragora/releases"],
        ["gh", "api", "--raw-field=name=v", "repos/synaptent/aragora/releases"],
        ["gh", "pr", "merge", "1"],
        ["rm", "-rf", "/tmp/x"],
    ):
        with pytest.raises(ValueError):
            module.require_read_only_argv(hostile)
    module.require_read_only_argv(["gh", "api", "repos/synaptent/aragora/releases/tags/x"])
    module.require_read_only_argv(["gh", "api", "-XGET", "repos/synaptent/aragora/releases"])
    module.require_read_only_argv(["gh", "release", "download", tag])
    module.require_read_only_argv(["gh", "release", "verify", tag])


def test_envelope_run_gh_command_is_static_for_the_authority_closure_scanner():
    """closure-member workflow openapi.yml invokes this helper statically, so
    the fail-closed Tier-4 authority-closure scanner walks every subprocess
    call in this file including function bodies. A parameter-forwarded argv
    has no static program token ("dynamic subprocess command is forbidden")
    and breaks the closure build at every ref containing the file; the helper
    must present a statically resolvable command AND introduce zero closure
    helper edges (gh is external; no literal repo helper paths)."""
    import scripts.generate_contract_drift_inventory as drift_inventory

    edges = drift_inventory._subprocess_helper_edges(
        ROOT, "scripts/openapi_release_envelope.py", include_function_bodies=True
    )
    assert edges == []


def test_envelope_run_gh_preserves_caller_argv_and_rejects_non_bare_program(monkeypatch):
    """Static command reconstruction must not change execution semantics: for
    every production argv shape the executed command stays byte-identical to
    the caller's read-only argv with unchanged subprocess options. Any argv
    whose program token is not exactly "gh" would silently execute different
    bytes than the caller requested once the command is rebuilt around the
    literal program name, so path forms fail closed before execution."""
    module = _load_envelope_helper()
    executed: list[list[str]] = []
    sentinel = subprocess.CompletedProcess(args=["gh"], returncode=0, stdout=b"", stderr=b"")

    def fake_run(argv, **kwargs):
        executed.append(list(argv))
        assert kwargs == {"capture_output": True, "check": False}
        return sentinel

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    head = "a" * 40
    tag = f"openapi-envelope-{head}"
    signer = "synaptent/aragora/.github/workflows/openapi.yml"
    production_shapes = [
        [
            "gh",
            "api",
            "-H",
            module.API_VERSION_HEADER,
            f"repos/synaptent/aragora/releases/tags/{tag}",
        ],
        [
            "gh",
            "api",
            "-H",
            module.API_VERSION_HEADER,
            "repos/synaptent/aragora/actions/artifacts",
            "--paginate",
            "--slurp",
        ],
        ["gh", "release", "download", tag, "--repo", "synaptent/aragora", "--dir", "/tmp/scratch"],
        ["gh", "release", "verify", "--help"],
        module.release_verify_argv(tag, repository="synaptent/aragora"),
        module.release_verify_asset_argv(
            tag, "/tmp/x/manifest.json", repository="synaptent/aragora"
        ),
        module.attestation_verify_argv(
            "/tmp/x/manifest.json",
            repository="synaptent/aragora",
            head_sha=head,
            signer_workflow=signer,
        ),
    ]
    for argv in production_shapes:
        result = module._run_gh(argv)
        assert result is sentinel
        assert executed[-1] == argv
    assert len(executed) == len(production_shapes)
    # Path-form programs pass require_read_only_argv (basename check) but must
    # be rejected here: rebuilding around literal "gh" would otherwise execute
    # a different program than the caller named.
    for hostile_program in ("/usr/bin/gh", "./gh", "bin/gh"):
        with pytest.raises(ValueError):
            module._run_gh([hostile_program, "api", "repos/synaptent/aragora/releases"])
    assert len(executed) == len(production_shapes)


def test_envelope_is_a_tier4_authority_dependency_in_both_classifiers():
    """closure-member workflow openapi.yml invokes this helper statically, so
    the helper is an authority-closure member. The fail-closed closure build
    rejects any member classifying below Tier 4 and enforces per-member parity
    between the canonical classifier and the merge-train mirror, so the exact
    file path must be a dependency-prefix entry in both."""
    from aragora.cli.commands import review_queue
    from scripts import tier4_merge_train

    path = "scripts/openapi_release_envelope.py"
    assert path in review_queue.CONTRACT_DRIFT_AUTHORITY_DEPENDENCY_PREFIXES
    assert path in tier4_merge_train.CONTRACT_DRIFT_AUTHORITY_DEPENDENCY_PREFIXES
    assert tier4_merge_train.matches_serialized_path(path) == path
    tier, name, _reason = review_queue._classify_model_review_tier([path])
    assert tier == 4
    assert name == "tier_4_preapproval_required"


def test_envelope_build_and_dry_run_cli_are_deterministic(tmp_path):
    # dry-run: deterministic fixture bytes, byte-identical across invocations.
    runs = [
        subprocess.run(
            [sys.executable, str(ENVELOPE_HELPER_PATH), "dry-run"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            stdin=subprocess.DEVNULL,
        )
        for _ in range(2)
    ]
    for completed in runs:
        assert completed.returncode == 0, completed.stderr
    assert runs[0].stdout == runs[1].stdout
    report = json.loads(runs[0].stdout)
    assert report["status"] == "pass"
    assert report["deterministic"] is True
    assert re.fullmatch(r"[0-9a-f]{64}", report["manifest_sha256"])
    # build CLI: two builds from the same payload bytes produce identical
    # envelope files that pass strict checksum verification.
    head = "d" * 40
    payload_dir = tmp_path / "payload" / "docs" / "api"
    payload_dir.mkdir(parents=True)
    (payload_dir / "openapi_generated.json").write_bytes(b'{"openapi":"3.1.0"}\n')
    outputs = []
    for name in ("assets-one", "assets-two"):
        out_dir = tmp_path / name
        completed = subprocess.run(
            [
                sys.executable,
                str(ENVELOPE_HELPER_PATH),
                "build",
                "--repository",
                "synaptent/aragora",
                "--head-sha",
                head,
                "--run-id",
                "12",
                "--run-attempt",
                "3",
                "--artifact-name",
                f"openapi-spec-12-{head}",
                "--payload-dir",
                str(tmp_path / "payload"),
                "--output-dir",
                str(out_dir),
            ],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            stdin=subprocess.DEVNULL,
        )
        assert completed.returncode == 0, completed.stderr
        outputs.append({path.name: path.read_bytes() for path in sorted(out_dir.iterdir())})
    assert outputs[0] == outputs[1]
    assert set(outputs[0]) == {"manifest.json", "checksums.txt", "openapi_generated.json"}


def _verify_retry_stub(exit_codes: list[int], tmp_path: Path) -> str:
    queue = tmp_path / "verify-exit-codes"
    calls = tmp_path / "verify-calls"
    sleeps = tmp_path / "verify-sleeps"
    queue.write_text("\n".join(str(code) for code in exit_codes) + "\n", encoding="utf-8")
    return f"""
python3() {{
  printf '%s\\n' "$*" >> {calls}
  code="$(head -n 1 {queue})"
  tail -n +2 {queue} > {queue}.next
  mv {queue}.next {queue}
  return "$code"
}}
sleep() {{
  printf '%s\\n' "$1" >> {sleeps}
}}
"""


def _verify_retry_env() -> dict[str, str]:
    head = "e" * 40
    return {
        "GITHUB_REPOSITORY": "synaptent/aragora",
        "GITHUB_SHA": head,
        "GITHUB_RUN_ID": "4242",
        "GITHUB_RUN_ATTEMPT": "7",
        "OPENAPI_RUN_ARTIFACT": f"openapi-spec-4242-{head}",
    }


def test_post_publish_verify_recovers_blocked_blocked_pass(tmp_path):
    run = _step("envelope", "Verify release, assets, attestation, and rule suite")["run"]
    completed = _simulate_step(
        run,
        env=_verify_retry_env(),
        cwd=tmp_path,
        stub_prelude=_verify_retry_stub([2, 2, 0], tmp_path),
    )
    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "verify-sleeps").read_text(encoding="utf-8").splitlines() == ["5", "10"]
    assert len((tmp_path / "verify-calls").read_text(encoding="utf-8").splitlines()) == 3


def test_post_publish_verify_readable_contradiction_fails_without_retry(tmp_path):
    run = _step("envelope", "Verify release, assets, attestation, and rule suite")["run"]
    completed = _simulate_step(
        run,
        env=_verify_retry_env(),
        cwd=tmp_path,
        stub_prelude=_verify_retry_stub([1, 0], tmp_path),
    )
    assert completed.returncode == 1
    assert len((tmp_path / "verify-calls").read_text(encoding="utf-8").splitlines()) == 1
    assert not (tmp_path / "verify-sleeps").exists()


@pytest.mark.parametrize("exit_code", [3, 17])
def test_post_publish_verify_movement_and_unexpected_errors_do_not_retry(tmp_path, exit_code):
    run = _step("envelope", "Verify release, assets, attestation, and rule suite")["run"]
    completed = _simulate_step(
        run,
        env=_verify_retry_env(),
        cwd=tmp_path,
        stub_prelude=_verify_retry_stub([exit_code, 0], tmp_path),
    )
    assert completed.returncode == exit_code
    assert len((tmp_path / "verify-calls").read_text(encoding="utf-8").splitlines()) == 1
    assert not (tmp_path / "verify-sleeps").exists()


def test_post_publish_verify_blocked_exhaustion_is_bounded(tmp_path):
    run = _step("envelope", "Verify release, assets, attestation, and rule suite")["run"]
    completed = _simulate_step(
        run,
        env=_verify_retry_env(),
        cwd=tmp_path,
        stub_prelude=_verify_retry_stub([2, 2, 2, 2, 0], tmp_path),
    )
    assert completed.returncode == 2
    assert (tmp_path / "verify-sleeps").read_text(encoding="utf-8").splitlines() == [
        "5",
        "10",
        "20",
    ]
    assert len((tmp_path / "verify-calls").read_text(encoding="utf-8").splitlines()) == 4
    assert "original-identity recovery runbook" in completed.stdout


def test_post_publish_verify_retries_same_identity_without_replaying_prior_phases(tmp_path):
    step = _step("envelope", "Verify release, assets, attestation, and rule suite")
    run = step["run"]
    assert " build " not in run
    assert " preflight " not in run
    assert "gh release create" not in run
    assert "actions/attest" not in run

    completed = _simulate_step(
        run,
        env=_verify_retry_env(),
        cwd=tmp_path,
        stub_prelude=_verify_retry_stub([2, 2, 0], tmp_path),
    )
    assert completed.returncode == 0, completed.stderr
    calls = (tmp_path / "verify-calls").read_text(encoding="utf-8").splitlines()
    assert len(calls) == 3
    assert len(set(calls)) == 1
    call = calls[0]
    for expected in (
        "scripts/openapi_release_envelope.py verify",
        "--repository synaptent/aragora",
        f"--head-sha {'e' * 40}",
        "--run-id 4242",
        "--run-attempt 7",
        f"--artifact-name openapi-spec-4242-{'e' * 40}",
        "--signer-workflow synaptent/aragora/.github/workflows/openapi.yml",
        "--admin-reads report",
    ):
        assert expected in call


def test_dispatch_omission_is_default_false_and_cannot_publish_envelope():
    inputs = DOC["on"]["workflow_dispatch"]["inputs"]
    publish = inputs["publish_envelope"]
    operator_attestation = inputs["operator_confirmed_immutable_releases"]
    assert publish["default"] == "false"
    assert operator_attestation["default"] == "false"
    assert operator_attestation.get("required", "false") == "false"

    envelope_if = JOBS["envelope"]["if"]
    assert "github.event_name == 'workflow_dispatch'" in envelope_if
    assert "inputs.publish_envelope == true" in envelope_if
    gate = _step("envelope", "Require operator immutable-releases attestation")["run"]
    assert '[[ "$OPERATOR_CONFIRMED" != "true" ]]' in gate
    assert "exit 2" in gate


# ---------------------------------------------------------------------------
# PR #9781 P3 follow-ups: exact post-publish argv + blocked-marker probes,
# bounded pre-publish attestation lag retry, admin-gated degradation in the
# job summary, and the sync copy layout
# ---------------------------------------------------------------------------

SYNC_COPY_STEPS = ("Check for changes", "Commit updated spec")

_GH_HELP_TEXT = b"-R, --repo | --format | --signer-workflow | --source-digest"


def _upload_payload_paths() -> list[str]:
    raw = _step("generate-run", "Upload generated spec and SDK types")["with"]["path"]
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _sync_cp_lines(step_name: str) -> list[str]:
    return [
        line.strip()
        for line in _step("sync", step_name)["run"].splitlines()
        if line.strip().startswith("cp ")
    ]


def _preflight_gh_stub(
    module,
    *,
    help_text: bytes = _GH_HELP_TEXT,
    broken_help: tuple[str, ...] = (),
    probe_rc: int = 1,
    probe_stderr: bytes = b"HTTP 404: no attestations found for subject",
    asset_lag: int = 0,
    asset_stderr: bytes = b"no attestations found for the requested subject yet",
):
    """Fake `_run_gh` covering cmd_preflight's direct gh surfaces: the
    `--help` capability probes, the scratch blocked-marker probe, and the
    per-asset pre-publish attestation verifies (which lag `asset_lag` reads
    before succeeding). Tag probes and settings go through `_gh_api_json`
    and are stubbed separately."""
    state: dict = {"help": [], "probe_calls": 0, "asset_attempts": {}}

    def fake_run(argv):
        module.require_read_only_argv(argv)
        if argv[-1] == "--help":
            action = " ".join(argv[1:-1])
            state["help"].append(action)
            if action in broken_help:
                return subprocess.CompletedProcess(argv, 1, b"", b"unknown command")
            return subprocess.CompletedProcess(argv, 0, help_text, b"")
        assert tuple(argv[1:3]) == ("attestation", "verify"), argv
        subject = argv[3]
        if subject.endswith(module.BLOCKED_MARKER_PROBE_NAME):
            state["probe_calls"] += 1
            return subprocess.CompletedProcess(argv, probe_rc, b"", probe_stderr)
        attempts = state["asset_attempts"].get(subject, 0) + 1
        state["asset_attempts"][subject] = attempts
        if attempts <= asset_lag:
            return subprocess.CompletedProcess(argv, 1, b"", asset_stderr)
        return subprocess.CompletedProcess(argv, 0, b"{}", b"")

    return fake_run, state


def _preflight_fixture(module, tmp_path, head: str = "a1" * 20, run_id: int = 77):
    identity = module.make_identity(**_identity_kwargs(module, head, run_id=run_id))
    assets = module.build_envelope(
        {"docs/api/openapi_generated.json": b'{"openapi":"3.1.0"}\n'}, identity
    )
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    for name, data in assets.items():
        (assets_dir / name).write_bytes(data)
    args = argparse.Namespace(
        repository="synaptent/aragora",
        head_sha=head,
        run_id=run_id,
        run_attempt=1,
        artifact_name=identity["artifact_name"],
        assets_dir=str(assets_dir),
        signer_workflow="",
        admin_reads="report",
    )
    return identity, args


def test_envelope_preflight_pins_exact_post_publish_verify_argv(monkeypatch, tmp_path, capsys):
    """The capability probe must validate the exact post-publish argv shape
    (every flag the shared builders emit) and the attestation subcommand
    itself, so a runner-gh mismatch surfaces as blocked BEFORE `gh release
    create` instead of as a hard exit 1 after the irreversible publication."""
    module = _load_envelope_helper()
    identity, args = _preflight_fixture(module, tmp_path)
    head = args.head_sha
    monkeypatch.setattr(module, "_sleep", lambda _delay: None)
    monkeypatch.setattr(module, "_gh_api_json", _live_api_stub(module, identity, head, []))
    # Control: a gh advertising every builder flag preflights clean and
    # reports all three probed capabilities.
    fake_run, state = _preflight_gh_stub(module)
    monkeypatch.setattr(module, "_run_gh", fake_run)
    assert module.cmd_preflight(args) == module.EXIT_PASS
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "pass"
    assert report["gh_capabilities"] == [
        "attestation verify",
        "release verify",
        "release verify-asset",
    ]
    assert set(state["help"]) == {"release verify", "release verify-asset", "attestation verify"}
    # Exact-argv drift: help output missing `--format` blocks pre-publication
    # naming the rejected flag, before any per-asset verification runs.
    fake_run, state = _preflight_gh_stub(module, help_text=b"-R, --repo only")
    monkeypatch.setattr(module, "_run_gh", fake_run)
    assert module.cmd_preflight(args) == module.EXIT_BLOCKED
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked"
    assert "--format" in report["reason"]
    assert state["asset_attempts"] == {}
    assert state["probe_calls"] == 0
    # A missing subcommand still blocks (the pre-existing guarantee, now
    # covering `gh attestation verify` too).
    fake_run, state = _preflight_gh_stub(module, broken_help=("attestation verify",))
    monkeypatch.setattr(module, "_run_gh", fake_run)
    assert module.cmd_preflight(args) == module.EXIT_BLOCKED
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked"
    assert "attestation verify" in report["reason"]
    assert state["asset_attempts"] == {}


def test_envelope_preflight_validates_blocked_marker_against_live_gh(monkeypatch, tmp_path, capsys):
    """`_checked_verification` keys blocked-vs-fail on the `no attestations`
    stderr marker. Preflight forces the runner's gh to emit its live
    no-attestation error against a guaranteed-unattested scratch subject, so
    marker drift blocks pre-publication instead of turning post-publish
    propagation lag into a hard failure."""
    module = _load_envelope_helper()
    identity, args = _preflight_fixture(module, tmp_path)
    head = args.head_sha
    monkeypatch.setattr(module, "_sleep", lambda _delay: None)
    monkeypatch.setattr(module, "_gh_api_json", _live_api_stub(module, identity, head, []))
    # Marker drift: the probe fails without the marker -> blocked, naming
    # the observed stderr, before any per-asset verification.
    fake_run, state = _preflight_gh_stub(
        module, probe_stderr=b"attestation lookup failed: HTTP 500"
    )
    monkeypatch.setattr(module, "_run_gh", fake_run)
    assert module.cmd_preflight(args) == module.EXIT_BLOCKED
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked"
    assert "no attestations" in report["reason"]
    assert "HTTP 500" in report["reason"]
    assert state["probe_calls"] == 1
    assert state["asset_attempts"] == {}
    # A probe that unexpectedly verifies an unattested subject is just as
    # disqualifying: the runner's verification verdicts cannot be trusted.
    fake_run, state = _preflight_gh_stub(module, probe_rc=0)
    monkeypatch.setattr(module, "_run_gh", fake_run)
    assert module.cmd_preflight(args) == module.EXIT_BLOCKED
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked"
    assert "unattested" in report["reason"]
    assert state["asset_attempts"] == {}
    # Healthy runner: the probe validates the marker and preflight records it.
    fake_run, state = _preflight_gh_stub(module)
    monkeypatch.setattr(module, "_run_gh", fake_run)
    assert module.cmd_preflight(args) == module.EXIT_PASS
    report = json.loads(capsys.readouterr().out)
    assert report["blocked_marker_probe"] == "validated"
    assert state["probe_calls"] == 1


def test_envelope_preflight_probe_names_transient_classes_before_marker_drift(
    monkeypatch, tmp_path, capsys
):
    """A probe answered by HTTP 403, failed by TLS certificate
    verification, dead at Sigstore verifier initialization, or killed in
    the network transport never observed a verification verdict, so the
    blocked report must name the observed cause instead of claiming marker
    drift: network shapes as the transient infrastructure class, TLS-trust,
    verifier-init, and HTTP 403 shapes without any transience promise (a
    corporate-MITM trust failure, a stale or corrupt local TUF cache, and a
    token-permission 403 persist until the runner/token configuration
    changes). The exit class is message-only cosmetics: every class stays
    blocked pre-publication with the observed stderr embedded and no
    per-asset verification attempted, and an unrecognized shape still
    reads as genuine drift."""
    module = _load_envelope_helper()
    identity, args = _preflight_fixture(module, tmp_path)
    head = args.head_sha
    monkeypatch.setattr(module, "_sleep", lambda _delay: None)
    monkeypatch.setattr(module, "_gh_api_json", _live_api_stub(module, identity, head, []))
    transient_shapes = {
        # Live network shape (gh 2.96.0, observed 2026-08-18): a post-init
        # API dial failure whose stderr carries the attestations path but
        # no HTTP 404. A connectivity retry genuinely clears this class.
        "connection refused": (
            b'Error: Get "https://api.github.com/repos/synaptent/aragora/'
            b'attestations/sha256:ab12?per_page=30": proxyconnect tcp: '
            b"dial tcp 127.0.0.1:9: connect: connection refused"
        ),
    }
    for observed, stderr in transient_shapes.items():
        fake_run, state = _preflight_gh_stub(module, probe_stderr=stderr)
        monkeypatch.setattr(module, "_run_gh", fake_run)
        assert module.cmd_preflight(args) == module.EXIT_BLOCKED, observed
        report = json.loads(capsys.readouterr().out)
        assert report["status"] == "blocked", observed
        assert "transient" in report["reason"], observed
        assert "neither the" not in report["reason"], observed
        assert "observed:" in report["reason"], observed
        assert observed in report["reason"], observed
        assert state["probe_calls"] == 1, observed
        assert state["asset_attempts"] == {}, observed
    # Sigstore verifier-init death, pinned live 2026-08-19 with the
    # byte-exact production argv (gh 2.96.0): dead TUF surfaces, TLS
    # interception toward them, and a stale or corrupt local TUF cache all
    # emit this same bare line, and the corrupt-cache case reproduces it
    # with FULL connectivity (gh never self-heals the cache), so this
    # wording must not promise that a connectivity retry clears it.
    observed = "no valid Sigstore verifiers could be initialized"
    fake_run, state = _preflight_gh_stub(
        module,
        probe_stderr=(
            b"error creating Sigstore verifier: no valid Sigstore verifiers could be initialized"
        ),
    )
    monkeypatch.setattr(module, "_run_gh", fake_run)
    assert module.cmd_preflight(args) == module.EXIT_BLOCKED
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked"
    assert "could not initialize the Sigstore verifier" in report["reason"]
    assert "stale or corrupt local TUF cache" in report["reason"]
    assert "even with full connectivity" in report["reason"]
    assert "transient" not in report["reason"]
    assert "neither the" not in report["reason"]
    assert "observed:" in report["reason"]
    assert observed in report["reason"]
    assert state["probe_calls"] == 1
    assert state["asset_attempts"] == {}
    # TLS-trust failures (corporate-MITM interception, untrusted or expired
    # chains), pinned live 2026-08-18 against the byte-exact production argv
    # (gh 2.96.0): an untrusted interceptor reports unknown authority even
    # when its own certificate is expired, so the expired-chain shape rides
    # on the crypto/tls umbrella prefix. These are persistent runner
    # configuration states, so their wording promises no transience.
    tls_trust_shapes = {
        "x509: certificate signed by unknown authority": (
            b'Error: Get "https://api.github.com/repos/synaptent/aragora/'
            b'attestations/sha256:ab12?per_page=30": tls: failed to verify '
            b"certificate: x509: certificate signed by unknown authority"
        ),
        "tls: failed to verify certificate": (
            b'Error: Get "https://api.github.com/repos/synaptent/aragora/'
            b'attestations/sha256:ab12?per_page=30": tls: failed to verify '
            b"certificate: x509: certificate has expired or is not yet valid: "
            b"current time 2026-08-18T12:00:00Z is after 2026-08-17T18:40:37Z"
        ),
    }
    for observed, stderr in tls_trust_shapes.items():
        fake_run, state = _preflight_gh_stub(module, probe_stderr=stderr)
        monkeypatch.setattr(module, "_run_gh", fake_run)
        assert module.cmd_preflight(args) == module.EXIT_BLOCKED, observed
        report = json.loads(capsys.readouterr().out)
        assert report["status"] == "blocked", observed
        assert "failed TLS certificate verification" in report["reason"], observed
        assert "persists until the runner trusts" in report["reason"], observed
        assert "transient" not in report["reason"], observed
        assert "neither the" not in report["reason"], observed
        assert "observed:" in report["reason"], observed
        assert observed in report["reason"], observed
        assert state["probe_calls"] == 1, observed
        assert state["asset_attempts"] == {}, observed
    # Precedence guard: one stderr carrying BOTH a TLS-trust marker and
    # network markers (an untrusted HTTPS proxy fails exactly this way:
    # proxyconnect plus the crypto/tls umbrella text in one line) must keep
    # classifying as the persistent TLS-trust runner state, never as the
    # transient network class, so a `_probe_transient_class` reorder that
    # checks the network markers first fails here instead of shipping.
    combined = "tls-trust must win over network"
    fake_run, state = _preflight_gh_stub(
        module,
        probe_stderr=(
            b'Error: Get "https://api.github.com/repos/synaptent/aragora/'
            b'attestations/sha256:ab12?per_page=30": proxyconnect tcp: '
            b"tls: failed to verify certificate: x509: certificate signed "
            b"by unknown authority"
        ),
    )
    monkeypatch.setattr(module, "_run_gh", fake_run)
    assert module.cmd_preflight(args) == module.EXIT_BLOCKED, combined
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked", combined
    assert "failed TLS certificate verification" in report["reason"], combined
    assert "persists until the runner trusts" in report["reason"], combined
    assert "transient" not in report["reason"], combined
    assert "observed:" in report["reason"], combined
    assert state["probe_calls"] == 1, combined
    assert state["asset_attempts"] == {}, combined
    # HTTP 403 is named without any transience promise: a rate-limited read
    # clears on retry, but a token-permission 403 persists until the token
    # can read the attestations API, and calling it transient would
    # misdirect the operator toward waiting out a permission gap.
    fake_run, state = _preflight_gh_stub(
        module,
        probe_stderr=(
            b"Error: HTTP 403: API rate limit exceeded (https://api.github.com/"
            b"repos/synaptent/aragora/attestations/sha256:ab12?per_page=30)"
        ),
    )
    monkeypatch.setattr(module, "_run_gh", fake_run)
    assert module.cmd_preflight(args) == module.EXIT_BLOCKED
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked"
    assert "HTTP 403" in report["reason"]
    assert "transient" not in report["reason"]
    assert "rate-limited read clears on retry" in report["reason"]
    assert "persists until" in report["reason"]
    assert "neither the" not in report["reason"]
    assert "observed:" in report["reason"]
    assert state["probe_calls"] == 1
    assert state["asset_attempts"] == {}
    # Boundary: an unrecognized shape (HTTP 500 here) is NOT transient-classed;
    # it keeps the marker-drift wording, byte-unchanged, so genuine drift is
    # never soft-pedaled.
    fake_run, state = _preflight_gh_stub(
        module, probe_stderr=b"attestation lookup failed: HTTP 500"
    )
    monkeypatch.setattr(module, "_run_gh", fake_run)
    assert module.cmd_preflight(args) == module.EXIT_BLOCKED
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked"
    assert "transient" not in report["reason"]
    assert "neither the" in report["reason"]
    assert "runner gh reports a missing attestation with neither the" in report["reason"]
    assert "would hard-fail instead of retrying" in report["reason"]
    assert state["asset_attempts"] == {}


def test_absent_attestation_http_404_shape_is_blocked_lag_not_contradiction(
    monkeypatch, tmp_path, capsys
):
    """Newer gh (2.96.0, observed live 2026-08-18) reports an unattested or
    not-yet-propagated subject as a raw attestations-API HTTP 404 instead of
    the textual `no attestations` marker. Both shapes must class as the
    retryable blocked state, while a 404 from any OTHER endpoint stays a
    readable contradiction that fails on the first read with no retry."""
    module = _load_envelope_helper()
    attestation_404 = (
        b"Error: HTTP 404: Not Found (https://api.github.com/repos/"
        b"synaptent/aragora/attestations/sha256:ab12?per_page=30)"
    )
    identity, args = _preflight_fixture(module, tmp_path)
    head = args.head_sha
    monkeypatch.setattr(module, "_gh_api_json", _live_api_stub(module, identity, head, []))
    # The live probe accepts the 404 shape as a validated blocked marker.
    monkeypatch.setattr(module, "_sleep", lambda _delay: None)
    fake_run, state = _preflight_gh_stub(module, probe_stderr=attestation_404)
    monkeypatch.setattr(module, "_run_gh", fake_run)
    assert module.cmd_preflight(args) == module.EXIT_PASS
    assert json.loads(capsys.readouterr().out)["blocked_marker_probe"] == "validated"
    assert state["probe_calls"] == 1
    # The same shape is retryable propagation lag for the per-asset reads.
    sleeps: list[int] = []
    monkeypatch.setattr(module, "_sleep", sleeps.append)
    fake_run, state = _preflight_gh_stub(module, asset_lag=1, asset_stderr=attestation_404)
    monkeypatch.setattr(module, "_run_gh", fake_run)
    assert module.cmd_preflight(args) == module.EXIT_PASS
    assert json.loads(capsys.readouterr().out)["status"] == "pass"
    assert set(state["asset_attempts"].values()) == {2}
    assert sleeps == [5] * len(state["asset_attempts"])
    # A 404 from any non-attestations endpoint is a contradiction, not lag:
    # the first read fails and the ladder never sleeps.
    release_404 = (
        b"HTTP 404: Not Found (https://api.github.com/repos/"
        b"synaptent/aragora/releases/tags/openapi-envelope-x)"
    )
    sleeps.clear()
    monkeypatch.setattr(
        module,
        "_run_gh",
        lambda argv: subprocess.CompletedProcess(argv, 1, b"", release_404),
    )
    with pytest.raises(RuntimeError, match="release probe"):
        module._verification_with_lag_retry(
            ["gh", "release", "verify", "openapi-envelope-x", "-R", "synaptent/aragora"],
            kind="release probe",
        )
    assert sleeps == []


def test_envelope_preflight_attestation_lag_retry_is_bounded_and_deterministic(
    monkeypatch, tmp_path, capsys
):
    """Pre-publish attestation reads can lag the actions/attest step inside
    the same run. The retry mirrors the post-publish ladder (4 attempts,
    5/10/20s waits), retries ONLY the blocked class, and weakens no
    fail-closed outcome: exhaustion stays blocked (exit 2, nothing
    published) and a readable contradiction still fails on the first read."""
    module = _load_envelope_helper()
    assert module.PREPUBLISH_RETRY_DELAYS == (5, 10, 20)
    identity, args = _preflight_fixture(module, tmp_path)
    head = args.head_sha
    monkeypatch.setattr(module, "_gh_api_json", _live_api_stub(module, identity, head, []))
    sleeps: list[int] = []
    monkeypatch.setattr(module, "_sleep", sleeps.append)
    # Two lagging reads per asset recover without failing the run.
    fake_run, state = _preflight_gh_stub(module, asset_lag=2)
    monkeypatch.setattr(module, "_run_gh", fake_run)
    assert module.cmd_preflight(args) == module.EXIT_PASS
    assert json.loads(capsys.readouterr().out)["status"] == "pass"
    assert set(state["asset_attempts"].values()) == {3}
    assert sleeps == [5, 10] * len(state["asset_attempts"])
    # Persistent lag exhausts the bounded ladder on the first asset and
    # stays blocked; the ladder never grows and never loops.
    sleeps.clear()
    fake_run, state = _preflight_gh_stub(module, asset_lag=10)
    monkeypatch.setattr(module, "_run_gh", fake_run)
    assert module.cmd_preflight(args) == module.EXIT_BLOCKED
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked"
    assert "not attested yet" in report["reason"]
    assert state["asset_attempts"] == {
        min(state["asset_attempts"]): 1 + len(module.PREPUBLISH_RETRY_DELAYS)
    }
    assert sleeps == [5, 10, 20]
    # A readable contradiction never retries and never sleeps.
    sleeps.clear()
    fake_run, state = _preflight_gh_stub(
        module, asset_lag=10, asset_stderr=b"subject digest mismatch"
    )
    monkeypatch.setattr(module, "_run_gh", fake_run)
    assert module.cmd_preflight(args) == module.EXIT_FAIL
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "fail"
    assert "digest mismatch" in report["reason"]
    assert set(state["asset_attempts"].values()) == {1}
    assert len(state["asset_attempts"]) == 1
    assert sleeps == []


def test_envelope_admin_gated_degradation_lands_in_step_summary(monkeypatch, tmp_path, capsys):
    """The in-run token soft-reports admin-gated surfaces by design
    (``--admin-reads report``); the job summary must surface that degraded
    state distinctly WITHOUT hard-failing the non-admin token, stay silent
    when nothing degraded, and never affect the verification outcome when no
    summary surface exists."""
    module = _load_envelope_helper()
    identity, args = _preflight_fixture(module, tmp_path)
    head = args.head_sha
    monkeypatch.setattr(module, "_sleep", lambda _delay: None)
    fake_run, _state = _preflight_gh_stub(module)
    monkeypatch.setattr(module, "_run_gh", fake_run)
    degraded = [
        ("immutable-releases", module.Forbidden("immutable-releases hidden: HTTP 404")),
        ("rule-suites", module.Forbidden("rule-suites not readable: HTTP 403")),
    ]
    summary = tmp_path / "step-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(module, "_gh_api_json", _live_api_stub(module, identity, head, degraded))
    assert module.cmd_preflight(args) == module.EXIT_PASS
    assert json.loads(capsys.readouterr().out)["status"] == "pass"
    text = summary.read_text(encoding="utf-8")
    assert "admin-read-gated" in text
    assert "immutable-releases setting: unreadable" in text
    assert "rule-suite binding: unverified" in text
    assert "--admin-reads required" in text
    # Nothing degraded: nothing written.
    clean_summary = tmp_path / "clean-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(clean_summary))
    monkeypatch.setattr(module, "_gh_api_json", _live_api_stub(module, identity, head, []))
    assert module.cmd_preflight(args) == module.EXIT_PASS
    capsys.readouterr()
    assert not clean_summary.exists()
    # No summary surface at all: degradation still soft-reports cleanly.
    monkeypatch.delenv("GITHUB_STEP_SUMMARY")
    monkeypatch.setattr(module, "_gh_api_json", _live_api_stub(module, identity, head, degraded))
    assert module.cmd_preflight(args) == module.EXIT_PASS
    assert json.loads(capsys.readouterr().out)["status"] == "pass"


def test_envelope_step_summary_dedupes_repeated_degraded_sections(monkeypatch, tmp_path, capsys):
    """The workflow's post-publish step re-invokes verify inside one job step
    on the blocked class, and every invocation appends to the same
    GITHUB_STEP_SUMMARY file; an identical degradation block must land once,
    while a genuinely different block (another phase here) still appends."""
    module = _load_envelope_helper()
    identity, args = _preflight_fixture(module, tmp_path)
    head = args.head_sha
    monkeypatch.setattr(module, "_sleep", lambda _delay: None)
    fake_run, _state = _preflight_gh_stub(module)
    monkeypatch.setattr(module, "_run_gh", fake_run)
    degraded = [
        ("immutable-releases", module.Forbidden("immutable-releases hidden: HTTP 404")),
        ("rule-suites", module.Forbidden("rule-suites not readable: HTTP 403")),
    ]
    summary = tmp_path / "retry-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(module, "_gh_api_json", _live_api_stub(module, identity, head, degraded))
    for _attempt in range(2):
        assert module.cmd_preflight(args) == module.EXIT_PASS
        capsys.readouterr()
    preflight_heading = "### OpenAPI envelope preflight: admin-read-gated reads degraded"
    text = summary.read_text(encoding="utf-8")
    assert text.count(preflight_heading) == 1
    # Dedupe is exact-block only: a different phase's block still appends.
    module._append_step_summary(
        {
            "phase": "verify",
            "immutability_setting": "unreadable (HTTP 403)",
            "rule_suite": {"state": "unverified"},
        }
    )
    text = summary.read_text(encoding="utf-8")
    assert text.count(preflight_heading) == 1
    assert text.count("### OpenAPI envelope verify: admin-read-gated reads degraded") == 1


def test_envelope_step_summary_tolerates_foreign_undecodable_bytes(monkeypatch, tmp_path, capsys):
    """GITHUB_STEP_SUMMARY is shared with every other step in the job, so its
    existing content can be arbitrary non-UTF-8 bytes; the dedupe read must
    never let a decode error escape the finally-block append and flip a
    verification outcome (summary IO stays cosmetic), and dedupe must still
    work across repeat runs against the poisoned file."""
    module = _load_envelope_helper()
    identity, args = _preflight_fixture(module, tmp_path)
    head = args.head_sha
    monkeypatch.setattr(module, "_sleep", lambda _delay: None)
    fake_run, _state = _preflight_gh_stub(module)
    monkeypatch.setattr(module, "_run_gh", fake_run)
    degraded = [
        ("immutable-releases", module.Forbidden("immutable-releases hidden: HTTP 404")),
        ("rule-suites", module.Forbidden("rule-suites not readable: HTTP 403")),
    ]
    summary = tmp_path / "poisoned-summary.md"
    summary.write_bytes(b"\xff\xfe\x80 foreign step bytes\n")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(module, "_gh_api_json", _live_api_stub(module, identity, head, degraded))
    for _attempt in range(2):
        assert module.cmd_preflight(args) == module.EXIT_PASS
        assert json.loads(capsys.readouterr().out)["status"] == "pass"
    raw = summary.read_bytes()
    assert raw.startswith(b"\xff\xfe\x80")
    assert raw.count(b"### OpenAPI envelope preflight: admin-read-gated reads degraded") == 1


def test_sync_copies_use_the_artifact_nested_layout():
    """download-artifact@v4 preserves the upload's repo-root-relative layout
    (the five payload paths share the repository root as their least common
    ancestor), so the artifact sources sit at their full nested paths. A
    flat basename copy matches nothing, and with ``2>/dev/null || true``
    masking it silently reduced the whole sync push to a no-op."""
    payload_paths = _upload_payload_paths()
    assert len(payload_paths) == 5
    expected_sources = {f"/tmp/openapi-spec/{path}" for path in payload_paths}
    for step_name in SYNC_COPY_STEPS:
        cp_lines = _sync_cp_lines(step_name)
        assert len(cp_lines) == len(payload_paths), (step_name, cp_lines)
        sources = {line.split()[1] for line in cp_lines}
        assert sources == expected_sources, (step_name, sorted(sources))
        for line in cp_lines:
            assert "|| true" not in line, (step_name, line)
            assert "2>/dev/null" not in line, (step_name, line)


def test_sync_check_step_applies_copies_and_fails_loudly_on_layout_drift(tmp_path):
    """Behavioral: with the artifact tree laid out the way the upload step
    produces it, every copy lands and drift is reported; a missing source
    (layout drift) fails the step instead of no-opping, which fails the sync
    job and skips the dependent envelope job (fail-closed, nothing
    published)."""
    payload_paths = _upload_payload_paths()
    destinations = {
        "docs/api/openapi_generated.json": "docs/api/openapi.json",
        "docs/api/openapi_generated.yaml": "docs/api/openapi.yaml",
        "sdk/typescript/src/openapi-types.ts": "sdk/typescript/src/openapi-types.ts",
        "sdk/python/aragora/generated_types.py": "sdk/python/aragora/generated_types.py",
        "aragora/live/src/types/api.generated.ts": "aragora/live/src/types/api.generated.ts",
    }
    assert set(destinations) == set(payload_paths)
    artifact_root = tmp_path / "openapi-spec"
    for path in payload_paths:
        source = artifact_root / path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f"generated {path}\n", encoding="utf-8")
        destination = tmp_path / destinations[path]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("stale\n", encoding="utf-8")
    run = _relocated(_step("sync", "Check for changes")["run"], tmp_path)
    output = tmp_path / "github-output"
    env = {"GITHUB_OUTPUT": str(output)}
    drift_stub = "git() { return 1; }\n"
    result = _simulate_step(run, env=env, cwd=tmp_path, stub_prelude=drift_stub)
    assert result.returncode == 0, result.stderr
    for path, destination in destinations.items():
        copied = (tmp_path / destination).read_text(encoding="utf-8")
        assert copied == f"generated {path}\n", destination
    assert "changes=true" in output.read_text(encoding="utf-8")
    # No drift: no changes output is emitted.
    output.write_text("", encoding="utf-8")
    clean_stub = "git() { return 0; }\n"
    result = _simulate_step(run, env=env, cwd=tmp_path, stub_prelude=clean_stub)
    assert result.returncode == 0, result.stderr
    assert "changes=true" not in output.read_text(encoding="utf-8")
    # Layout drift: a missing source must fail the step loudly.
    (artifact_root / payload_paths[0]).unlink()
    result = _simulate_step(run, env=env, cwd=tmp_path, stub_prelude=drift_stub)
    assert result.returncode != 0, "missing artifact source no-opped silently"
