import ast
import io
import json
import os
import re
import shutil
import subprocess
import zipfile
from datetime import datetime as RealDateTime
from pathlib import Path
from typing import Any

import pytest
import yaml

import scripts.verify_contract_drift_workflow_state as workflow_state
from scripts.verify_contract_drift_workflow_state import (
    CANONICAL_WORKFLOW_ID,
    CANONICAL_WORKFLOW_NAME,
    CANONICAL_WORKFLOW_PATH,
    EXPECTED_PROTECTION_STRICT,
    GhApiReader,
    PRE_CUTOVER_REQUIRED_CHECKS,
    VerificationError,
    verify_workflow_state,
)
from tests.scripts._contract_drift_historical_git import (
    HISTORICAL_HEAD_FETCH_ENV,
    PR_9320_HEAD_REF,
    PR_9320_LOCAL_REF,
    ensure_pr_9320_head,
)

ROOT = Path(__file__).resolve().parents[2]
TEXT = (ROOT / ".github/workflows/contract-drift-governance.yml").read_text()
DOC = yaml.load(TEXT, Loader=yaml.BaseLoader)
JOBS = DOC["jobs"]
HISTORICAL_FINALIZER_PATH = (
    ROOT / ".github/workflows/contract-drift-historical-backfill-finalizer.yml"
)

LIVE_CHECK_NAMES = (
    "contract-drift-pr-delta",
    "contract-drift-main-receipt",
    "contract-drift-program-trajectory",
)
LIVE_JOB_IDS = ("pr-delta", "main-receipt", "program-trajectory")
# The finalizer dispatch is the only step needing `actions: write`; it lives in
# its own job so the routine receipt path never carries a write scope.
DISPATCH_JOB_ID = "historical-backfill-dispatch"
DISPATCH_JOB_NAME = "contract-drift-historical-backfill-dispatch"
DISPATCH_JOB_IF = (
    "success() && github.event_name == 'workflow_dispatch' && inputs.historical_backfill"
)
# (trigger event, inputs.historical_backfill, jobs whose `if` holds).
EVENT_JOB_TABLE = (
    ("pull_request", None, ("pr-delta",)),
    ("push", None, ("main-receipt", "program-trajectory")),
    ("schedule", None, ("main-receipt", "program-trajectory")),
    ("workflow_dispatch", False, ("main-receipt", "program-trajectory")),
    ("workflow_dispatch", True, ("main-receipt", DISPATCH_JOB_ID)),
)
SOURCE_SHA_EXPR = "${{ github.event_name == 'push' && github.event.after || github.sha }}"
HISTORICAL_SOURCE_SHA_EXPR = "${{ github.event_name == 'workflow_dispatch' && inputs.historical_backfill && github.sha || github.event_name == 'push' && github.event.after || github.sha }}"
# GitHub Actions app installation id: required-check tuples produced by
# workflow jobs must carry this app identity, never a third-party app.
EXPECTED_PR_DELTA_APP_ID = 15368
GITHUB_RUNNER_ENV_ALLOWLIST = frozenset(
    {
        "CI",
        "COMSPEC",
        "GITHUB_ACTIONS",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOGNAME",
        "PATH",
        "PATHEXT",
        "RUNNER_ARCH",
        "RUNNER_OS",
        "RUNNER_TEMP",
        "RUNNER_TOOL_CACHE",
        "SHELL",
        "SYSTEMROOT",
        "TMPDIR",
        "TZ",
        "USER",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
    }
)


def _analyzer_step(job_id: str) -> dict:
    matches = [
        step
        for step in JOBS[job_id]["steps"]
        if "run" in step and "check_contract_drift_ratchet.py" in step["run"]
    ]
    exact = [
        step for step in matches if "build_contract_drift_historical_backfill.py" not in step["run"]
    ]
    if len(exact) == 1:
        return exact[0]
    raise AssertionError(f"expected one analyzer step in {job_id}, found {len(exact)}")


def _upload_step(job_id: str) -> dict:
    for step in JOBS[job_id]["steps"]:
        if str(step.get("uses", "")).startswith("actions/upload-artifact@"):
            return step
    raise AssertionError(f"no upload step in {job_id}")


def _named_run_step(job_id: str, name: str) -> dict:
    matches = [
        step
        for step in JOBS[job_id]["steps"]
        if step.get("name") == name and isinstance(step.get("run"), str)
    ]
    assert len(matches) == 1, f"expected one {name!r} step in {job_id}, found {len(matches)}"
    return matches[0]


def _historical_finalizer() -> tuple[str, dict[str, Any]]:
    assert HISTORICAL_FINALIZER_PATH.is_file()
    text = HISTORICAL_FINALIZER_PATH.read_text(encoding="utf-8")
    document = yaml.load(text, Loader=yaml.BaseLoader)
    assert isinstance(document, dict)
    return text, document


def _terminal_step() -> dict:
    matches = [
        step
        for step in JOBS["pr-delta"]["steps"]
        if step.get("if") == "always()" and "steps.admission.outcome" in step.get("run", "")
    ]
    assert len(matches) == 1, f"expected one terminal pr-delta step, found {len(matches)}"
    return matches[0]


def _simulate_step(
    run_block: str,
    *,
    env: dict[str, str],
    cwd: Path,
    stubs: dict[str, int] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a workflow run block the way GitHub does (bash -e), with
    optional shell-function stubs standing in for named commands."""
    prelude = "".join(
        f"{name}() {{ echo stub-{name}; return {code}; }}\n" for name, code in (stubs or {}).items()
    )
    runner_env = {
        name: value
        for name in GITHUB_RUNNER_ENV_ALLOWLIST
        if (value := os.environ.get(name)) is not None
    }
    return subprocess.run(
        ["bash", "-e", "-c", prelude + run_block],
        capture_output=True,
        text=True,
        env={**runner_env, **env},
        cwd=str(cwd),
    )


def test_terminal_step_is_selected_by_identity(monkeypatch: pytest.MonkeyPatch):
    terminal = _terminal_step()
    sentinel = {"name": "unrelated trailing cleanup", "run": "exit 99"}
    monkeypatch.setitem(
        JOBS,
        "pr-delta",
        {**JOBS["pr-delta"], "steps": [*JOBS["pr-delta"]["steps"], sentinel]},
    )
    assert _terminal_step() == terminal


def test_simulate_step_scrubs_non_runner_parent_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CDG_UNTRUSTED_PARENT_VALUE", "must-not-leak")
    result = _simulate_step(
        'test -z "${CDG_UNTRUSTED_PARENT_VALUE+x}"',
        env={},
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def _terminal_repo(tmp_path: Path, *, baseline_text: str) -> tuple[Path, str]:
    """Build a fixture git repo whose BASE_SHA-addressed baseline the terminal
    aggregator inspects, and return (workdir, base_sha)."""
    repo = tmp_path / "terminal-repo"
    baseline = repo / "scripts/baselines/contract_drift_inventory.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(baseline_text, encoding="utf-8")
    for argv in (
        ["git", "init", "-q"],
        ["git", "add", "-A"],
        [
            "git",
            "-c",
            "user.email=cdg-test@example.invalid",
            "-c",
            "user.name=cdg-test",
            "commit",
            "-q",
            "-m",
            "baseline",
        ],
    ):
        subprocess.run(argv, cwd=repo, check=True, capture_output=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repo, base_sha


def _run_terminal(
    tmp_path: Path,
    *,
    outcome: str,
    payload: str | None,
    baseline_text: str = '{"accepted_authority": {}}\n',
) -> subprocess.CompletedProcess[str]:
    repo, base_sha = _terminal_repo(tmp_path, baseline_text=baseline_text)
    if payload is not None:
        (repo / "contract-drift-pr-delta.json").write_text(payload, encoding="utf-8")
    script = _terminal_step()["run"].replace("${{ steps.admission.outcome }}", outcome)
    return _simulate_step(script, env={"BASE_SHA": base_sha}, cwd=repo)


def test_workflow_has_exact_live_checks_and_events():
    assert {JOBS[job_id]["name"] for job_id in LIVE_JOB_IDS} == {f"contract-drift-{name}" for name in ("pr-delta", "main-receipt", "program-trajectory")}  # fmt: skip
    assert set(JOBS) == {*LIVE_JOB_IDS, DISPATCH_JOB_ID}
    assert set(DOC["on"]) == {"pull_request", "push", "schedule", "workflow_dispatch"} and not {"paths", "paths-ignore"} & set(DOC["on"]["pull_request"])  # fmt: skip
    assert all({"uses": "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065", "with": {"python-version": "3.11"}} in JOBS[job_id]["steps"] for job_id in LIVE_JOB_IDS)  # fmt: skip


def test_pr_admission_is_event_bound_absolute_and_terminal():
    assert '--base-ref "$BASE_SHA"' in TEXT and '--head-ref "$HEAD_SHA"' in TEXT
    assert TEXT.count('--repo-root "$GITHUB_WORKSPACE"') == 3
    pr = str(JOBS["pr-delta"])
    assert "--mode pr" in pr and "--mode receipt" not in pr and "--mode program" not in pr
    terminal = JOBS["pr-delta"]["steps"][-1]
    assert terminal["if"] == "always()" and "steps.admission.outcome" in terminal["run"]
    receipt, program = JOBS["main-receipt"], JOBS["program-trajectory"]
    assert receipt["env"]["SOURCE_SHA"] == HISTORICAL_SOURCE_SHA_EXPR
    assert program["env"]["SOURCE_SHA"] == SOURCE_SHA_EXPR
    assert "needs" not in receipt and "needs" not in program
    assert "--mode program" in str(program) and "continue-on-error" not in str(program)


def test_program_trajectory_upload_is_sha_qualified_and_never_masks_the_analyzer():
    program = JOBS["program-trajectory"]
    assert "continue-on-error" not in program  # job level: analyzer red stays red
    *_, analyzer, upload = program["steps"]
    # The analyzer stays the unconditioned terminal enforcement step: no `if`
    # and no `continue-on-error`, so its exit code alone decides the job.
    assert "--mode program" in analyzer["run"]
    assert "tee contract-drift-program-trajectory.json" in analyzer["run"]
    assert "if" not in analyzer and "continue-on-error" not in analyzer
    # The durable upload is exactly one SHA-qualified actions/upload-artifact@v4
    # step that runs on success or failure but not cancellation, and carries no
    # extra keys that could soften or reinterpret the analyzer outcome.
    assert upload == {
        "if": "always() && !cancelled()",
        "uses": "actions/upload-artifact@v4",
        "with": {
            "name": "contract-drift-program-trajectory-${{ github.sha }}",
            "path": "contract-drift-program-trajectory.json",
        },
    }


# --- VAL-CDG-015: live workflow topology -----------------------------------


def _job_names(doc: dict) -> list[str]:
    return [
        str(job.get("name", job_id))
        for job_id, job in doc.get("jobs", {}).items()
        if isinstance(job, dict)
    ]


FIXTURE_REPO = "synaptent/aragora"
FIXTURE_MAIN_SHA = "a" * 40
FIXTURE_RUN_ID = 7001


class FixtureApiReader:
    def __init__(
        self,
        json_responses: dict[str, list[Any]],
        bytes_responses: dict[str, bytes],
    ):
        self.json_responses = {key: list(value) for key, value in json_responses.items()}
        self.bytes_responses = bytes_responses
        self.json_calls: list[str] = []

    def get_json(self, endpoint: str) -> dict[str, Any]:
        self.json_calls.append(endpoint)
        responses = self.json_responses.get(endpoint)
        if not responses:
            raise AssertionError(f"unexpected JSON endpoint: {endpoint}")
        payload = responses.pop(0) if len(responses) > 1 else responses[0]
        if not isinstance(payload, dict):
            raise AssertionError(f"unexpected non-object JSON endpoint: {endpoint}")
        return payload

    def get_bytes(self, endpoint: str, *, max_bytes: int | None = None) -> bytes:
        try:
            payload = self.bytes_responses[endpoint]
        except KeyError as exc:
            raise AssertionError(f"unexpected bytes endpoint: {endpoint}") from exc
        if max_bytes is not None and len(payload) > max_bytes:
            raise VerificationError(f"authenticated GitHub response is too large: {endpoint}")
        return payload


class FixedDateTime(RealDateTime):
    @classmethod
    def now(cls, tz=None):
        return RealDateTime(2026, 2, 19, tzinfo=tz)


def _json_page(items: list[dict[str, Any]], key: str, total: int | None = None) -> dict[str, Any]:
    return {"total_count": len(items) if total is None else total, key: items}


def _artifact_zip(filename: str, payload: dict[str, Any]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(filename, json.dumps(payload, sort_keys=True))
    return buffer.getvalue()


def _workflow_record(*, workflow_id: int = CANONICAL_WORKFLOW_ID, state: str = "active") -> dict[str, Any]:  # fmt: skip
    return {"id": workflow_id, "name": CANONICAL_WORKFLOW_NAME, "path": CANONICAL_WORKFLOW_PATH, "state": state}  # fmt: skip


def _run_record(
    *,
    run_id: int = FIXTURE_RUN_ID,
    main_sha: str = FIXTURE_MAIN_SHA,
    run_attempt: int = 1,
    started_at: str = "2026-08-12T01:00:00Z",
    event: str = "push",
    conclusion: str = "failure",
) -> dict[str, Any]:
    return {"id": run_id, "workflow_id": CANONICAL_WORKFLOW_ID, "path": CANONICAL_WORKFLOW_PATH, "head_branch": "main", "head_sha": main_sha, "event": event, "run_attempt": run_attempt, "run_started_at": started_at, "status": "completed", "conclusion": conclusion}  # fmt: skip


FIXTURE_ATTEMPT_JOB_NAMES = (*LIVE_CHECK_NAMES, DISPATCH_JOB_NAME)
FIXTURE_JOB_CONCLUSIONS = dict(
    zip(FIXTURE_ATTEMPT_JOB_NAMES, ("skipped", "success", "failure", "skipped"), strict=True)
)
# Job conclusions of a (workflow_dispatch, historical_backfill=true) execution
# per EVENT_JOB_TABLE: trajectory never runs, the write-scoped dispatch does.
BACKFILL_DISPATCH_CONCLUSIONS = dict(
    zip(FIXTURE_ATTEMPT_JOB_NAMES, ("skipped", "success", "skipped", "success"), strict=True)
)


def _job_record(name: str, *, run_id: int, main_sha: str, attempt: int, job_id: int, conclusion: str | None = None) -> tuple[dict[str, Any], str, dict[str, Any]]:  # fmt: skip
    check_id = job_id + 10_000
    check_url = f"https://api.github.com/repos/{FIXTURE_REPO}/check-runs/{check_id}"
    conclusion = FIXTURE_JOB_CONCLUSIONS[name] if conclusion is None else conclusion
    job = {"id": job_id, "name": name, "run_attempt": attempt, "check_run_url": check_url}
    check = {"id": check_id, "name": name, "head_sha": main_sha, "app": {"id": EXPECTED_PR_DELTA_APP_ID}, "status": "completed", "conclusion": conclusion, "details_url": f"https://github.com/{FIXTURE_REPO}/actions/runs/{run_id}/job/{job_id}"}  # fmt: skip
    return job, check_url, check


def _live_fixture(
    *,
    workflows: list[dict[str, Any]] | None = None,
    workflow_total: int | None = None,
    runs: list[dict[str, Any]] | None = None,
    run_total: int | None = None,
    run_attempt: int = 1,
    second_snapshot_run: dict[str, Any] | None = None,
    protection_checks: list[dict[str, Any]] | None = None,
    protection_strict: bool = EXPECTED_PROTECTION_STRICT,
    receipt_payload_status: str = "pass",
) -> tuple[FixtureApiReader, dict[str, Any]]:
    run_records = list(runs or [_run_record(run_attempt=run_attempt)])
    selected = max(
        (item for item in run_records if item["head_sha"] == FIXTURE_MAIN_SHA),
        key=lambda item: (item["run_started_at"], item["id"], item["run_attempt"]),
    )
    selected_id = selected["id"]
    selected_sha = selected["head_sha"]
    selected_attempt = selected["run_attempt"]
    workflows = [_workflow_record()] if workflows is None else workflows
    if protection_checks is None:
        protection_checks = [{"context": context, "app_id": app_id} for context, app_id in PRE_CUTOVER_REQUIRED_CHECKS]  # fmt: skip

    json_responses: dict[str, list[Any]] = {
        f"repos/{FIXTURE_REPO}/actions/workflows?per_page=100&page=1": [
            _json_page(workflows, "workflows", workflow_total)
        ],
        f"repos/{FIXTURE_REPO}/git/ref/heads/main": [
            {"object": {"sha": FIXTURE_MAIN_SHA}},
            {"object": {"sha": FIXTURE_MAIN_SHA}},
        ],
        f"repos/{FIXTURE_REPO}/actions/workflows/{CANONICAL_WORKFLOW_ID}/runs?per_page=100&page=1": [
            _json_page(run_records, "workflow_runs", run_total),
            _json_page(run_records, "workflow_runs", run_total),
            _json_page([second_snapshot_run or selected], "workflow_runs"),
            _json_page([second_snapshot_run or selected], "workflow_runs"),
        ],  # fmt: skip
        f"repos/{FIXTURE_REPO}/branches/main/protection/required_status_checks": [
            {"strict": protection_strict, "checks": protection_checks}
        ],
    }
    workflow_source = (ROOT / CANONICAL_WORKFLOW_PATH).read_bytes()
    bytes_responses: dict[str, bytes] = {
        f"repos/{FIXTURE_REPO}/contents/{CANONICAL_WORKFLOW_PATH}?ref=main": workflow_source,
        f"repos/{FIXTURE_REPO}/contents/{CANONICAL_WORKFLOW_PATH}?ref={selected_sha}": workflow_source,
    }

    for attempt in range(1, selected_attempt + 1):
        jobs: list[dict[str, Any]] = []
        for offset, name in enumerate(FIXTURE_ATTEMPT_JOB_NAMES, start=1):
            job, check_url, check = _job_record(
                name,
                run_id=selected_id,
                main_sha=selected_sha,
                attempt=attempt,
                job_id=attempt * 100 + offset,
            )
            jobs.append(job)
            json_responses[check_url] = [check]
        endpoint = f"repos/{FIXTURE_REPO}/actions/runs/{selected_id}/attempts/{attempt}/jobs?per_page=100&page=1"
        json_responses[endpoint] = [_json_page(jobs, "jobs")]

    artifacts: list[dict[str, Any]] = []
    artifact_specs = (
        (9001, "contract-drift-main-receipt", "contract-drift-main-receipt.json", {"source_sha": selected_sha, "status": receipt_payload_status}),
        (9002, "contract-drift-program-trajectory", "contract-drift-program-trajectory.json", {"program": {"source_sha": selected_sha}, "status": "fail"}),
    )  # fmt: skip
    for artifact_id, prefix, filename, payload in artifact_specs:
        raw_zip = _artifact_zip(filename, payload)
        artifacts.append({"id": artifact_id, "name": f"{prefix}-{selected_sha}", "expired": False, "size_in_bytes": len(raw_zip), "workflow_run": {"id": selected_id, "head_sha": selected_sha}})  # fmt: skip
        bytes_responses[f"repos/{FIXTURE_REPO}/actions/artifacts/{artifact_id}/zip"] = raw_zip
    json_responses[
        f"repos/{FIXTURE_REPO}/actions/runs/{selected_id}/artifacts?per_page=100&page=1"
    ] = [_json_page(artifacts, "artifacts")]
    expected = {"workflow_id": CANONICAL_WORKFLOW_ID, "main_sha": FIXTURE_MAIN_SHA, "run_id": selected_id, "run_attempt": selected_attempt}  # fmt: skip
    return FixtureApiReader(json_responses, bytes_responses), expected


def test_exactly_one_active_contract_drift_workflow():
    disabled = [
        {
            "id": 100_000 + index,
            "name": f"legacy-{index}",
            "path": f".github/workflows/legacy-{index}.yml",
            "state": "disabled_manually",
        }
        for index in range(100)
    ]
    reader, expected = _live_fixture(workflows=[*disabled, _workflow_record()])
    repo = "synaptent/aragora"
    # Force a real second page while preserving one stable response for every later endpoint.
    reader.json_responses[f"repos/{repo}/actions/workflows?per_page=100&page=1"] = [
        _json_page(disabled, "workflows", 101)
    ]
    reader.json_responses[f"repos/{repo}/actions/workflows?per_page=100&page=2"] = [
        _json_page([_workflow_record()], "workflows", 101)
    ]
    result = verify_workflow_state(reader)
    assert result["workflow"] == _workflow_record(workflow_id=expected["workflow_id"])
    assert result["workflow_pages"] == [
        f"repos/{repo}/actions/workflows?per_page=100&page=1",
        f"repos/{repo}/actions/workflows?per_page=100&page=2",
    ]
    reader, _ = _live_fixture(workflows=[_workflow_record(state="disabled_manually")])
    with pytest.raises(VerificationError, match="must be active"):
        verify_workflow_state(reader)


def test_exact_three_live_cdg_check_names():
    reader, _ = _live_fixture()
    result = verify_workflow_state(reader)
    assert set(result["selection"]["selected_attempt"]["checks"]) == set(LIVE_CHECK_NAMES)


def test_no_duplicate_live_cdg_check_names():
    workflow_paths = sorted((ROOT / ".github/workflows").glob("*.y*ml"))
    for live in LIVE_CHECK_NAMES:
        assert [path.name for path in workflow_paths if live in _job_names(yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader))] == ["contract-drift-governance.yml"], live  # fmt: skip
        assert _job_names(DOC).count(live) == 1
    duplicate = _workflow_record(workflow_id=CANONICAL_WORKFLOW_ID + 1)
    duplicate["path"] = ".github/workflows/contract-drift-copy.yml"
    reader, _ = _live_fixture(workflows=[_workflow_record(), duplicate])
    with pytest.raises(VerificationError, match="exactly one registered workflow"):
        verify_workflow_state(reader)
    reader, _ = _live_fixture(workflows=[_workflow_record(), _workflow_record()])
    with pytest.raises(VerificationError, match="duplicate identities"):
        verify_workflow_state(reader)
    reader, _ = _live_fixture(workflow_total=2)
    with pytest.raises(VerificationError, match="do not reconcile to total_count"):
        verify_workflow_state(reader)


def test_contract_drift_triggers_pr_main_schedule_dispatch():
    reader, _ = _live_fixture()
    result = verify_workflow_state(reader)
    assert result["workflow"]["state"] == "active"
    assert set(DOC["on"]) == {"pull_request", "push", "schedule", "workflow_dispatch"}
    assert DOC["on"]["pull_request"]["branches"] == ["main"]
    assert DOC["on"]["push"]["branches"] == ["main"]
    schedule = DOC["on"]["schedule"]
    assert schedule and all("cron" in entry for entry in schedule)
    assert set(DOC["on"]["workflow_dispatch"]["inputs"]) == {
        "historical_backfill",
        "historical_base_sha",
        "historical_first_parent_sha",
        "historical_head_sha",
        "historical_merge_sha",
    }


def test_contract_drift_pr_has_no_governed_path_filter_gap():
    reader, _ = _live_fixture()
    verify_workflow_state(reader)
    for event in ("pull_request", "push"):
        assert not {"paths", "paths-ignore"} & set(DOC["on"][event])


def test_contract_drift_pr_uses_event_bound_full_shas():
    reader, expected = _live_fixture()
    result = verify_workflow_state(reader)
    assert result["main_sha"] == expected["main_sha"]
    env = JOBS["pr-delta"]["env"]
    assert env["BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
    assert env["HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    admission = _analyzer_step("pr-delta")["run"]
    assert '--base-ref "$BASE_SHA"' in admission and '--head-ref "$HEAD_SHA"' in admission
    assert 'git fetch --no-tags origin "$BASE_SHA" "$HEAD_SHA"' in admission
    # No mutable or synthetic refs stand in for the immutable event SHAs.
    pr_text = str(JOBS["pr-delta"])
    assert "github.ref" not in pr_text and "merge_commit_sha" not in pr_text
    assert "--base-ref HEAD" not in pr_text and "--head-ref HEAD" not in pr_text


def test_contract_drift_non_pr_events_resolve_one_sha_for_receipt_and_program():
    reader, expected = _live_fixture()
    result = verify_workflow_state(reader)
    assert result["selection"]["identity"]["run_id"] == expected["run_id"]
    assert JOBS["main-receipt"]["env"]["SOURCE_SHA"] == HISTORICAL_SOURCE_SHA_EXPR
    assert JOBS["program-trajectory"]["env"]["SOURCE_SHA"] == SOURCE_SHA_EXPR


def _analyzer_step_text(job: dict) -> str:
    matches = [
        step["run"]
        for step in job["steps"]
        if "run" in step
        and "check_contract_drift_ratchet.py" in step["run"]
        and "build_contract_drift_historical_backfill.py" not in step["run"]
    ]
    if len(matches) == 1:
        return matches[0]
    raise AssertionError(f"expected one analyzer step, found {len(matches)}")


def test_workflow_runs_paginate_unfiltered_and_filter_locally():
    same_sha = [_run_record(run_id=6000 + index, started_at="2026-08-11T01:00:00Z") for index in range(100)]  # fmt: skip
    expected_run = _run_record(run_id=7002, run_attempt=2, started_at="2026-08-12T01:00:00Z")
    newer_other_sha = _run_record(
        run_id=8000,
        main_sha="b" * 40,
        started_at="2026-08-12T02:00:00Z",
    )
    tie = _run_record(run_id=7001, run_attempt=5, started_at=expected_run["run_started_at"])
    reader, _ = _live_fixture(runs=[*same_sha, tie, expected_run, newer_other_sha])
    endpoint = f"repos/{FIXTURE_REPO}/actions/workflows/{CANONICAL_WORKFLOW_ID}/runs"
    reader.json_responses[f"{endpoint}?per_page=100&page=1"] = [_json_page(same_sha, "workflow_runs", 103)] * 4  # fmt: skip
    reader.json_responses[f"{endpoint}?per_page=100&page=2"] = [_json_page([tie, expected_run, newer_other_sha], "workflow_runs", 103)] * 2 + [_json_page([expected_run], "workflow_runs")] * 2  # fmt: skip
    result = verify_workflow_state(reader)
    assert result["selection"]["identity"] == {"run_started_at": expected_run["run_started_at"], "run_id": 7002, "run_attempt": 2}  # fmt: skip
    run_calls = [call for call in reader.json_calls if call.startswith(endpoint)]
    assert f"{endpoint}?per_page=100&page=2" in run_calls and all(not any(token in call for token in ("branch=", "status=", "event=", "conclusion=")) for call in run_calls)  # fmt: skip
    duplicate, _ = _live_fixture(runs=[*same_sha, expected_run])
    duplicate.json_responses[f"{endpoint}?per_page=100&page=1"] = [_json_page(same_sha, "workflow_runs", 101)]  # fmt: skip
    duplicate.json_responses[f"{endpoint}?per_page=100&page=2"] = [_json_page([same_sha[0]], "workflow_runs", 101)]  # fmt: skip
    with pytest.raises(VerificationError, match="duplicate identities"):
        verify_workflow_state(duplicate)


def test_filtered_history_requires_disjoint_date_shards_below_1000(monkeypatch: pytest.MonkeyPatch):
    import scripts.verify_contract_drift_workflow_state as verifier

    days = [verifier.HISTORY_START_DATE + verifier.timedelta(days=offset) for offset in range(7)]
    monkeypatch.setattr(verifier, "datetime", FixedDateTime)
    responses: dict[str, list[dict[str, Any]]] = {}
    for day_index, day in enumerate(days):
        base = f"repos/{FIXTURE_REPO}/actions/workflows/{CANONICAL_WORKFLOW_ID}/runs?created={day.isoformat()}T00%3A00%3A00Z..{day.isoformat()}T23%3A59%3A59Z"
        records = [{"id": day_index * 1000 + index + 1} for index in range(400)]
        for page in range(1, 5):
            responses[f"{base}&per_page=100&page={page}"] = [_json_page(records[(page - 1) * 100 : page * 100], "workflow_runs", 400)]  # fmt: skip
        responses[f"{base}&per_page=100&page=5"] = [_json_page([], "workflow_runs", 400)]
    reader = FixtureApiReader(responses, {})
    records, endpoints = verifier._workflow_runs_by_date(
        reader,
        repo=FIXTURE_REPO,
        workflow_id=CANONICAL_WORKFLOW_ID,
        reported_total=2800,
    )
    logical_shards = [endpoint for endpoint in endpoints if endpoint.startswith("created=")]
    assert len(records) == 2800
    assert logical_shards == ["created=2026-02-13..2026-02-14", "created=2026-02-15..2026-02-16", "created=2026-02-17..2026-02-18", "created=2026-02-19..2026-02-19"]  # fmt: skip
    assert all("created=" in call and "per_page=100&page=" in call for call in reader.json_calls)
    hostile = FixtureApiReader(json.loads(json.dumps(responses)), {})
    for key in [key for key in hostile.json_responses if f"created={days[0].isoformat()}" in key]:
        hostile.json_responses[key][0]["total_count"] = 401
    with pytest.raises(VerificationError, match="do not reconcile to total_count"):
        verifier._workflow_runs_by_date(hostile, repo=FIXTURE_REPO, workflow_id=CANONICAL_WORKFLOW_ID, reported_total=2800)  # fmt: skip
    hostile = FixtureApiReader(json.loads(json.dumps(responses)), {})
    first, second = [key for key in hostile.json_responses if key.endswith("page=1")][:2]
    hostile.json_responses[second][0]["workflow_runs"][0]["id"] = hostile.json_responses[first][0]["workflow_runs"][0]["id"]  # fmt: skip
    with pytest.raises(VerificationError, match="date-sharded workflow history returned duplicate identities"):  # fmt: skip
        verifier._workflow_runs_by_date(hostile, repo=FIXTURE_REPO, workflow_id=CANONICAL_WORKFLOW_ID, reported_total=2800)  # fmt: skip


def test_workflow_run_ids_reconcile_to_total_count():
    reader, _ = _live_fixture(run_total=2)
    with pytest.raises(VerificationError, match="do not reconcile to total_count"):
        verify_workflow_state(reader)
    duplicate = _run_record(run_id=7001)
    reader, _ = _live_fixture(runs=[duplicate, dict(duplicate)], run_total=2)
    with pytest.raises(VerificationError, match="duplicate identities"):
        verify_workflow_state(reader)


def test_attempts_are_enumerated_one_through_run_attempt():
    reader, expected = _live_fixture(run_attempt=3)
    result = verify_workflow_state(reader)
    assert [attempt["attempt"] for attempt in result["selection"]["attempts"]] == [1, 2, 3]
    assert result["selection"]["identity"]["run_attempt"] == expected["run_attempt"]


def test_jobs_and_check_urls_are_attempt_specific():
    reader, expected = _live_fixture(run_attempt=2)
    result = verify_workflow_state(reader)
    for attempt in result["selection"]["attempts"]:
        assert f"/attempts/{attempt['attempt']}/jobs" in attempt["jobs_endpoint"]
        for check in attempt["checks"].values():
            assert check["jobs_endpoint"] == attempt["jobs_endpoint"]
            assert check["check_url"].startswith(
                "https://api.github.com/repos/synaptent/aragora/check-runs/"
            )
    hostile, _ = _live_fixture(run_attempt=1)
    endpoint = f"repos/synaptent/aragora/actions/runs/{expected['run_id']}/attempts/1/jobs?per_page=100&page=1"
    hostile.json_responses[endpoint][0]["jobs"][0]["run_attempt"] = 2
    with pytest.raises(VerificationError, match="job record is not attempt-specific"):
        verify_workflow_state(hostile)
    hostile, _ = _live_fixture(run_attempt=1)
    hostile.json_responses[endpoint][0]["jobs"][0]["check_run_url"] = (
        "https://api.github.com/repos/attacker/other/check-runs/10101"
    )
    with pytest.raises(VerificationError, match="bound to another repository"):
        verify_workflow_state(hostile)


def test_run_level_artifacts_require_payload_and_release_binding():
    reader, expected = _live_fixture()
    result = verify_workflow_state(reader)
    assert {item["payload_status"] for item in result["selection"]["artifacts"]} == {"pass", "fail"}
    assert all(
        f"-{expected['main_sha']}" in item["name"] for item in result["selection"]["artifacts"]
    )
    hostile, _ = _live_fixture(receipt_payload_status="fail")
    with pytest.raises(VerificationError, match="payload status contradicts"):
        verify_workflow_state(hostile)
    hostile, _ = _live_fixture()
    endpoint = (
        f"repos/synaptent/aragora/actions/runs/{expected['run_id']}/artifacts?per_page=100&page=1"
    )
    hostile.json_responses[endpoint][0]["artifacts"][0]["workflow_run"]["id"] += 1
    with pytest.raises(VerificationError, match="bound to another run or SHA"):
        verify_workflow_state(hostile)


def test_pr_delta_cutover_preserves_exact_context_app_id_set_and_strict():
    after = [
        {"context": context, "app_id": app_id} for context, app_id in PRE_CUTOVER_REQUIRED_CHECKS
    ] + [{"context": "contract-drift-pr-delta", "app_id": EXPECTED_PR_DELTA_APP_ID}]
    reader, _ = _live_fixture(protection_checks=after)
    result = verify_workflow_state(reader)
    assert result["branch_protection"]["cutover_phase"] == "after"
    strict_hostile, _ = _live_fixture(protection_strict=not EXPECTED_PROTECTION_STRICT)
    with pytest.raises(VerificationError, match="strict moved"):
        verify_workflow_state(strict_hostile)


def test_pr_delta_uses_expected_app_identity():
    hostile_checks = [
        {"context": context, "app_id": app_id} for context, app_id in PRE_CUTOVER_REQUIRED_CHECKS
    ] + [{"context": "contract-drift-pr-delta", "app_id": 99999}]
    reader, _ = _live_fixture(protection_checks=hostile_checks)
    with pytest.raises(VerificationError, match="valid cutover state"):
        verify_workflow_state(reader)
    reader, _ = _live_fixture()
    check_url = "https://api.github.com/repos/synaptent/aragora/check-runs/10101"
    reader.json_responses[check_url][0]["app"]["id"] = 99999
    with pytest.raises(VerificationError, match="not authenticated by the GitHub Actions app"):
        verify_workflow_state(reader)


def test_live_verifier_rejects_main_or_selected_run_movement():
    reader, _ = _live_fixture()
    reader.json_responses["repos/synaptent/aragora/git/ref/heads/main"][-1] = {
        "object": {"sha": "b" * 40}
    }
    with pytest.raises(VerificationError, match="matches current main|moved during verification"):
        verify_workflow_state(reader)
    moved = _run_record(run_id=7002, started_at="2026-08-12T02:00:00Z")
    reader, _ = _live_fixture(second_snapshot_run=moved)
    with pytest.raises(VerificationError, match="moved during verification"):
        verify_workflow_state(reader)


def test_terminal_aggregator_fails_if_pr_delta_is_skipped_cancelled_or_missing(tmp_path):
    assert _terminal_step()["if"] == "always()"
    payload = '{"admitted": true}\n'
    assert _run_terminal(tmp_path / "ok", outcome="success", payload=payload).returncode == 0
    for index, outcome in enumerate(("skipped", "cancelled", "failure")):
        result = _run_terminal(tmp_path / f"bad{index}", outcome=outcome, payload=payload)
        assert result.returncode != 0, outcome
    assert _run_terminal(tmp_path / "missing", outcome="success", payload=None).returncode != 0


def test_main_receipt_job_is_distinct_and_successful_when_trajectory_is_red(tmp_path):
    receipt, program = JOBS["main-receipt"], JOBS["program-trajectory"]
    assert receipt["name"] != program["name"] and "needs" not in receipt
    env = {
        "EVENT_NAME": "push",
        "HISTORICAL_BACKFILL": "false",
        "SOURCE_SHA": "b" * 40,
        "GITHUB_WORKSPACE": str(tmp_path),
    }
    red = _simulate_step(_analyzer_step_text(program), env=env, cwd=tmp_path, stubs={"python3": 17})
    green = _simulate_step(
        _analyzer_step_text(receipt), env=env, cwd=tmp_path, stubs={"python3": 0}
    )
    assert red.returncode == 17 and green.returncode == 0
    # The receipt artifact is gated only on the receipt job's own success.
    assert _upload_step("main-receipt")["if"] == "success()"


def test_main_receipt_requires_complete_first_parent_backfill(tmp_path):
    receipt = _analyzer_step_text(JOBS["main-receipt"])
    assert "--mode receipt" in receipt and "--mode program" not in receipt
    env = {
        "EVENT_NAME": "workflow_dispatch",
        "HISTORICAL_BACKFILL": "true",
        "HISTORICAL_BASE_SHA": "a" * 40,
        "HISTORICAL_FIRST_PARENT_SHA": "d" * 40,
        "HISTORICAL_HEAD_SHA": "b" * 40,
        "HISTORICAL_MERGE_SHA": "c" * 40,
        "SOURCE_SHA": "b" * 40,
        "GITHUB_WORKSPACE": str(tmp_path),
    }
    # An incomplete first-parent backfill is a red receipt analyzer; pipefail
    # preserves that exit through tee, and the success-gated upload withholds
    # the receipt artifact.
    incomplete = _simulate_step(receipt, env=env, cwd=tmp_path, stubs={"python3": 3})
    assert incomplete.returncode == 3
    assert _upload_step("main-receipt")["if"] == "success()"
    assert "continue-on-error" not in str(JOBS["main-receipt"])


def test_historical_backfill_dispatch_is_exact_pair_and_event_disjoint():
    dispatch = DOC["on"]["workflow_dispatch"]["inputs"]
    assert dispatch["historical_backfill"]["type"] == "boolean"
    assert dispatch["historical_backfill"]["default"] == "false"
    receipt = JOBS["main-receipt"]
    run = _analyzer_step_text(receipt)
    env = receipt["env"]
    assert receipt["if"] == "github.event_name != 'pull_request'"
    assert env["EVENT_NAME"] == "${{ github.event_name }}"
    assert "inputs.historical_backfill" in env["HISTORICAL_BACKFILL"]
    assert env["SOURCE_SHA"] == HISTORICAL_SOURCE_SHA_EXPR
    assert receipt["steps"][0]["with"]["ref"] == HISTORICAL_SOURCE_SHA_EXPR
    assert "${EVENT_NAME:-}" in run
    assert "${HISTORICAL_BACKFILL:-false}" in run
    for flag, input_name in (
        ("--historical-base-sha", "historical_base_sha"),
        ("--historical-head-sha", "historical_head_sha"),
        ("--historical-merge-sha", "historical_merge_sha"),
        ("--historical-first-parent-sha", "historical_first_parent_sha"),
    ):
        assert flag in run
        env_name = input_name.upper()
        assert f"inputs.{input_name}" in env[env_name]
        assert f"${env_name}" in run
    assert "FULL_SHA='^[0-9a-f]{40}$'" in run
    assert "inputs.historical_backfill" in _upload_step("main-receipt")["with"]["name"]
    assert "contract-drift-main-receipt-analyzer" in _upload_step("main-receipt")["with"]["name"]
    assert JOBS["program-trajectory"]["if"].endswith("|| !inputs.historical_backfill)")


def test_historical_backfill_fetches_the_exact_pull_request_head_before_receipt():
    fetch = _named_run_step("main-receipt", "Fetch exact historical PR head")
    assert fetch["if"] == ("github.event_name == 'workflow_dispatch' && inputs.historical_backfill")
    run = fetch["run"]
    assert 'HISTORICAL_PR_REF="refs/pull/9320/head"' in run
    assert 'HISTORICAL_LOCAL_REF="refs/cdg-historical-backfill/9320/head"' in run
    assert (
        'git fetch --no-tags --force origin "${HISTORICAL_PR_REF}:${HISTORICAL_LOCAL_REF}"' in run
    )
    assert (
        'test "$(git rev-parse --verify "${HISTORICAL_LOCAL_REF}^{commit}")" = '
        '"$HISTORICAL_HEAD_SHA"'
    ) in run
    assert "github.event.pull_request" not in run
    assert "refs/heads/" not in run and "refs/tags/" not in run


def _scratch_clone_missing_historical_head(tmp_path: Path) -> tuple[Path, str]:
    """Clone a file:// origin whose historical head exists only under refs/pull/9320/head."""
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    (source / "tracked.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=source, check=True)
    commit_env = {
        **os.environ,
        "GIT_AUTHOR_EMAIL": "cdg-test@example.invalid",
        "GIT_AUTHOR_NAME": "cdg-test",
        "GIT_COMMITTER_EMAIL": "cdg-test@example.invalid",
        "GIT_COMMITTER_NAME": "cdg-test",
    }
    subprocess.run(
        ["git", "commit", "-q", "-m", "base"],
        cwd=source,
        env=commit_env,
        check=True,
    )
    base_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    subprocess.run(["git", "checkout", "-q", "-b", "historical"], cwd=source, check=True)
    (source / "tracked.txt").write_text("historical\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "historical"], cwd=source, env=commit_env, check=True)
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    subprocess.run(["git", "checkout", "-q", "-B", "main", base_sha], cwd=source, check=True)

    bare = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(source), str(bare)], check=True)
    subprocess.run(
        ["git", f"--git-dir={bare}", "update-ref", PR_9320_HEAD_REF, head_sha],
        check=True,
    )
    subprocess.run(
        ["git", f"--git-dir={bare}", "update-ref", "-d", "refs/heads/historical"],
        check=True,
    )

    checkout = tmp_path / "checkout"
    subprocess.run(
        [
            "git",
            "clone",
            "-q",
            "--no-local",
            "--single-branch",
            "--branch",
            "main",
            f"file://{bare}",
            str(checkout),
        ],
        check=True,
    )
    assert (
        subprocess.run(
            ["git", "cat-file", "-e", f"{head_sha}^{{commit}}"],
            cwd=checkout,
            capture_output=True,
        ).returncode
        != 0
    )
    return checkout, head_sha


def _local_backfill_ref_present(checkout: Path) -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", PR_9320_LOCAL_REF],
            cwd=checkout,
            capture_output=True,
        ).returncode
        == 0
    )


def _ensure_head_or_fail(checkout: Path, expected_sha: str) -> str:
    # A stray skip inside the helper would report the test as skipped rather
    # than failed, so convert it into a hard failure for fetch-path tests.
    try:
        return ensure_pr_9320_head(checkout, expected_sha=expected_sha)
    except pytest.skip.Exception as exc:
        pytest.fail(f"ensure_pr_9320_head skipped unexpectedly: {exc}")


def _unset_historical_fetch_opt_ins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(HISTORICAL_HEAD_FETCH_ENV, raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


def test_missing_historical_head_skips_without_fetching_when_no_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    checkout, head_sha = _scratch_clone_missing_historical_head(tmp_path)
    _unset_historical_fetch_opt_ins(monkeypatch)

    with pytest.raises(pytest.skip.Exception) as excinfo:
        ensure_pr_9320_head(checkout, expected_sha=head_sha)

    reason = str(excinfo.value)
    assert HISTORICAL_HEAD_FETCH_ENV in reason
    assert head_sha in reason
    assert PR_9320_HEAD_REF in reason
    assert not _local_backfill_ref_present(checkout)
    assert (
        subprocess.run(
            ["git", "cat-file", "-e", f"{head_sha}^{{commit}}"],
            cwd=checkout,
            capture_output=True,
        ).returncode
        != 0
    )


def test_missing_historical_head_fetches_when_opt_in_flag_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    checkout, head_sha = _scratch_clone_missing_historical_head(tmp_path)
    _unset_historical_fetch_opt_ins(monkeypatch)
    monkeypatch.setenv(HISTORICAL_HEAD_FETCH_ENV, "1")

    assert _ensure_head_or_fail(checkout, head_sha) == head_sha
    assert (
        subprocess.check_output(
            ["git", "rev-parse", PR_9320_LOCAL_REF],
            cwd=checkout,
            text=True,
        ).strip()
        == head_sha
    )


def test_missing_historical_head_fetches_under_github_actions_without_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    checkout, head_sha = _scratch_clone_missing_historical_head(tmp_path)
    _unset_historical_fetch_opt_ins(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    assert _ensure_head_or_fail(checkout, head_sha) == head_sha
    assert (
        subprocess.check_output(
            ["git", "rev-parse", PR_9320_LOCAL_REF],
            cwd=checkout,
            text=True,
        ).strip()
        == head_sha
    )


def test_present_historical_head_honors_caller_expected_sha_without_fetching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    checkout, _ = _scratch_clone_missing_historical_head(tmp_path)
    _unset_historical_fetch_opt_ins(monkeypatch)
    present_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout, text=True
    ).strip()

    assert ensure_pr_9320_head(checkout, expected_sha=present_sha) == present_sha
    assert not _local_backfill_ref_present(checkout)


def test_historical_backfill_fetch_succeeds_from_a_clean_runner_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    checkout, head_sha = _scratch_clone_missing_historical_head(tmp_path)
    monkeypatch.setenv(HISTORICAL_HEAD_FETCH_ENV, "1")
    assert ensure_pr_9320_head(checkout, expected_sha=head_sha) == head_sha
    assert (
        subprocess.check_output(
            ["git", "rev-parse", PR_9320_LOCAL_REF],
            cwd=checkout,
            text=True,
        ).strip()
        == head_sha
    )
    subprocess.run(
        ["git", "update-ref", "-d", PR_9320_LOCAL_REF],
        cwd=checkout,
        check=True,
    )

    git_stub_dir = tmp_path / "bin"
    git_stub_dir.mkdir()
    git_bin = shutil.which("git")
    assert git_bin is not None
    (git_stub_dir / "git").write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
if [[ "${{1:-}}" == "fetch" ]]; then
  shift
  args=()
  for arg in "$@"; do
    [[ "$arg" == "--no-tags" || "$arg" == "--force" ]] && continue
    args+=("$arg")
  done
  exec {git_bin!r} fetch "${{args[@]}}"
fi
exec {git_bin!r} "$@"
""",
        encoding="utf-8",
    )
    (git_stub_dir / "git").chmod(0o755)

    fetch = _named_run_step("main-receipt", "Fetch exact historical PR head")
    result = _simulate_step(
        fetch["run"],
        env={
            "HISTORICAL_HEAD_SHA": head_sha,
            "PATH": f"{git_stub_dir}:{os.environ['PATH']}",
        },
        cwd=checkout,
    )
    assert result.returncode == 0, result.stderr
    assert (
        subprocess.check_output(
            ["git", "rev-parse", PR_9320_LOCAL_REF],
            cwd=checkout,
            text=True,
        ).strip()
        == head_sha
    )


def test_historical_backfill_finalizes_only_after_the_receipt_job_completed():
    receipt = JOBS["main-receipt"]
    assert "build_contract_drift_historical_backfill.py" not in str(receipt)
    assert DOC["permissions"] == {"checks": "read", "contents": "read"}
    assert "permissions" not in JOBS["pr-delta"]
    assert receipt["permissions"] == {"checks": "read", "contents": "read"}

    upload = _upload_step("main-receipt")
    assert upload["id"] == "receipt-upload"
    assert (
        "format('contract-drift-main-receipt-analyzer-{0}', github.sha)" in upload["with"]["name"]
    )
    assert "contract-drift-main-receipt-analyzer.json" in upload["with"]["path"]
    # The dispatch job depends on the completed receipt job and consumes the
    # uploaded analyzer artifact through the job output, so it can only run
    # after the producer job (and its upload) reached success.
    assert receipt["outputs"]["analyzer_artifact_id"] == (
        "${{ steps.receipt-upload.outputs.artifact-id }}"
    )
    dispatch_job = JOBS[DISPATCH_JOB_ID]
    assert dispatch_job["needs"] == "main-receipt"
    assert dispatch_job["if"] == DISPATCH_JOB_IF
    assert dispatch_job["env"]["ANALYZER_ARTIFACT_ID"] == (
        "${{ needs.main-receipt.outputs.analyzer_artifact_id }}"
    )
    dispatch = _named_run_step(DISPATCH_JOB_ID, "Finalize completed historical receipt")
    dispatch_run = dispatch["run"]
    assert "/attempts/${GITHUB_RUN_ATTEMPT}/jobs?per_page=100&page=1" in dispatch_run
    assert 'select(.name == "contract-drift-main-receipt") | .id' in dispatch_run
    assert '--argjson artifact_id "$ANALYZER_ARTIFACT_ID"' in dispatch_run
    assert '--arg source_sha "$SOURCE_SHA"' in dispatch_run
    assert "producer_identity" in dispatch_run
    assert "gh api --method POST" in dispatch_run
    assert (
        "actions/workflows/contract-drift-historical-backfill-finalizer.yml/dispatches"
        in dispatch_run
    )
    assert 'SOURCE_REF="${GITHUB_REF#refs/heads/}"' in dispatch_run
    assert 'SOURCE_REF="${GITHUB_REF#refs/tags/}"' in dispatch_run
    assert '-f ref="$SOURCE_REF"' in dispatch_run
    assert '-f ref="$SOURCE_SHA"' not in dispatch_run

    text, finalizer = _historical_finalizer()
    assert finalizer["on"] == {
        "workflow_dispatch": {
            "inputs": {
                "producer_identity": {
                    "description": (
                        "Canonical JSON identity of the completed historical receipt producer"
                    ),
                    "required": "true",
                    "type": "string",
                }
            }
        }
    }
    jobs = finalizer["jobs"]
    assert set(jobs) == {"finalize-historical-receipt"}
    job = jobs["finalize-historical-receipt"]
    assert job["name"] == "contract-drift-historical-backfill-receipt-finalizer"
    assert "if" not in job
    assert job["env"]["PRODUCER_IDENTITY"] == "${{ inputs.producer_identity }}"
    validate = next(
        step for step in job["steps"] if step.get("name") == "Validate completed producer identity"
    )
    assert (
        '["artifact_id","job_id","run_attempt","source_sha","workflow_run_id"]' in validate["run"]
    )
    assert 'test("^[0-9a-f]{40}$")' in validate["run"]
    assert "$GITHUB_OUTPUT" in validate["run"]

    checkout = next(
        step for step in job["steps"] if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout["with"]["ref"] == "${{ steps.producer.outputs.source_sha }}"
    download = next(
        step
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/download-artifact@")
    )
    assert download["with"]["artifact-ids"] == "${{ steps.producer.outputs.artifact_id }}"
    assert download["with"]["github-token"] == "${{ github.token }}"
    assert download["with"]["merge-multiple"] == "true"
    assert download["with"]["repository"] == "${{ github.repository }}"
    assert download["with"]["run-id"] == "${{ steps.producer.outputs.workflow_run_id }}"

    build = next(
        step
        for step in job["steps"]
        if step.get("name") == "Build completed historical receipt envelope"
    )
    assert build["env"]["ANALYZER_ARTIFACT_ID"] == ("${{ steps.producer.outputs.artifact_id }}")
    assert build["env"]["GH_TOKEN"] == "${{ github.token }}"
    run = build["run"]
    assert "for attempt in $(seq 1 30)" in run
    assert "actions/runs/${PRODUCER_RUN_ID}" in run
    assert "steps.producer.outputs.source_sha" in run
    assert ".github/workflows/contract-drift-governance.yml" in run
    assert '"workflow_dispatch"' in run
    assert 'test "${RUN_STATUS:-}" = "completed"' in run
    assert 'test "${RUN_CONCLUSION:-}" = "success"' in run
    assert "scripts/build_contract_drift_historical_backfill.py" in run
    assert "--build-receipt-envelope" in run
    assert "--analyzer-result receipt-input/contract-drift-main-receipt-analyzer.json" in run
    assert "--output-receipt contract-drift-main-receipt.json" in run
    assert '--workflow-run-id "$PRODUCER_RUN_ID"' in run
    assert '--run-attempt "$PRODUCER_RUN_ATTEMPT"' in run
    assert '--job-id "$PRODUCER_JOB_ID"' in run
    assert '--artifact-id "$ANALYZER_ARTIFACT_ID"' in run
    assert '--repository "$GITHUB_REPOSITORY"' in run
    assert "--github-api" in run
    assert "artifact_name=" in run and "$GITHUB_OUTPUT" in run

    final_upload = next(
        step
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    )
    assert final_upload["if"] == "success()"
    assert final_upload["with"]["name"] == "${{ steps.envelope.outputs.artifact_name }}"
    assert final_upload["with"]["path"] == "contract-drift-main-receipt.json"
    assert "contract-drift-main-receipt" not in {value["name"] for value in jobs.values()}
    assert "workflow_run:" not in text

    analyzer = _analyzer_step_text(receipt)
    assert "tee contract-drift-main-receipt-analyzer.json" in analyzer
    assert "tee contract-drift-main-receipt.json" not in analyzer


# --- least-privilege split: finalizer dispatch is its own gated job ----------


def _job_permissions(job: dict) -> dict[str, str]:
    permissions = job.get("permissions")
    if permissions is None:
        return dict(DOC["permissions"])
    assert isinstance(permissions, dict), permissions
    return dict(permissions)


def _job_if_holds(job: dict, *, event: str, historical_backfill: bool | None) -> bool:
    """Evaluate the job-level `if` for one trigger event with a tiny expression subset."""
    expression = job.get("if")
    if expression is None:
        return True
    text = str(expression)
    replacements = {
        "success()": "True",
        "github.event_name": repr(event),
        "!github.event.pull_request.draft": "True",
        "inputs.historical_backfill": repr(bool(historical_backfill)),
    }
    for token, value in replacements.items():
        text = text.replace(token, value)
    text = text.replace("&&", " and ").replace("||", " or ")
    text = re.sub(r"!(?!=)", " not ", text)

    def evaluate(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not evaluate(node.operand)
        if isinstance(node, ast.BoolOp):
            values = [evaluate(value) for value in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left, right = evaluate(node.left), evaluate(node.comparators[0])
            if isinstance(node.ops[0], ast.Eq):
                return left == right
            if isinstance(node.ops[0], ast.NotEq):
                return left != right
        raise AssertionError((ast.dump(node), expression))

    return bool(evaluate(ast.parse(text, mode="eval")))


def test_routine_main_receipt_is_read_only_and_finalizer_dispatch_is_its_own_gated_job():
    # Job-level permissions cannot be conditioned per step, so the only way the
    # routine receipt path can run read-only is for the dispatch to be a job.
    receipt = JOBS["main-receipt"]
    assert "actions" not in _job_permissions(receipt)
    assert all(scope == "read" for scope in _job_permissions(receipt).values())
    assert "actions/workflows/contract-drift-historical-backfill-finalizer.yml" not in str(receipt)
    assert "gh api --method POST" not in str(receipt)
    assert receipt["outputs"] == {
        "analyzer_artifact_id": "${{ steps.receipt-upload.outputs.artifact-id }}"
    }

    assert set(JOBS) == {*LIVE_JOB_IDS, DISPATCH_JOB_ID}
    dispatch_job = JOBS[DISPATCH_JOB_ID]
    assert dispatch_job["name"] == DISPATCH_JOB_NAME
    assert dispatch_job["name"] not in LIVE_CHECK_NAMES
    assert dispatch_job["needs"] == "main-receipt"
    assert dispatch_job["if"] == DISPATCH_JOB_IF
    assert dispatch_job["permissions"] == {"actions": "write"}
    assert dispatch_job["env"]["ANALYZER_ARTIFACT_ID"] == (
        "${{ needs.main-receipt.outputs.analyzer_artifact_id }}"
    )
    assert dispatch_job["env"]["SOURCE_SHA"] == HISTORICAL_SOURCE_SHA_EXPR
    assert "continue-on-error" not in str(dispatch_job)
    assert all("uses" not in step for step in dispatch_job["steps"])
    dispatch = _named_run_step(DISPATCH_JOB_ID, "Finalize completed historical receipt")
    assert "if" not in dispatch
    assert dispatch["env"] == {"GH_TOKEN": "${{ github.token }}"}
    dispatch_run = dispatch["run"]
    assert dispatch_run.startswith("set -euo pipefail\n")
    assert '[[ "$ANALYZER_ARTIFACT_ID" =~ ^[1-9][0-9]*$ ]]' in dispatch_run
    assert "/attempts/${GITHUB_RUN_ATTEMPT}/jobs?per_page=100&page=1" in dispatch_run
    assert 'select(.name == "contract-drift-main-receipt") | .id' in dispatch_run
    assert '--argjson artifact_id "$ANALYZER_ARTIFACT_ID"' in dispatch_run
    assert '--arg source_sha "$SOURCE_SHA"' in dispatch_run
    assert (
        "actions/workflows/contract-drift-historical-backfill-finalizer.yml/dispatches"
        in dispatch_run
    )

    # `actions: write` exists in exactly one job, and every other job is read-only.
    writers = {job_id for job_id, job in JOBS.items() if "write" in _job_permissions(job).values()}
    assert writers == {DISPATCH_JOB_ID}
    assert TEXT.count("actions: write") == 1


def test_event_permission_table_proves_non_historical_paths_never_reach_actions_write():
    for event, historical_backfill, expected_jobs in EVENT_JOB_TABLE:
        running = {
            job_id
            for job_id, job in JOBS.items()
            if _job_if_holds(job, event=event, historical_backfill=historical_backfill)
        }
        assert running == set(expected_jobs), (event, historical_backfill)
        effective = {job_id: _job_permissions(JOBS[job_id]) for job_id in running}
        if event == "workflow_dispatch" and historical_backfill:
            assert effective[DISPATCH_JOB_ID] == {"actions": "write"}
            assert "actions" not in effective["main-receipt"]
        else:
            assert "write" not in {
                scope for permissions in effective.values() for scope in permissions.values()
            }, (event, historical_backfill)
    # The gated job never runs on a routine event, so a skipped-job row is the
    # only trace it leaves on push/schedule/non-backfill dispatch attempts.
    assert JOBS[DISPATCH_JOB_ID]["needs"] == "main-receipt"
    assert "program-trajectory" not in str(JOBS[DISPATCH_JOB_ID].get("needs"))


def test_live_verifier_requires_the_skipped_dispatch_job_on_routine_main_runs():
    assert workflow_state.HISTORICAL_DISPATCH_JOB_NAME == DISPATCH_JOB_NAME
    assert DISPATCH_JOB_NAME not in workflow_state.LIVE_CHECK_NAMES
    reader, expected = _live_fixture()
    result = verify_workflow_state(reader)
    selected = result["selection"]["selected_attempt"]
    assert set(selected["checks"]) == set(LIVE_CHECK_NAMES)
    assert selected["auxiliary_jobs"] == {DISPATCH_JOB_NAME: "skipped"}
    endpoint = f"repos/synaptent/aragora/actions/runs/{expected['run_id']}/attempts/1/jobs?per_page=100&page=1"

    # A missing dispatch job means the workflow source and the attempt disagree.
    missing, _ = _live_fixture()
    remaining = [
        job
        for job in missing.json_responses[endpoint][0]["jobs"]
        if job["name"] != DISPATCH_JOB_NAME
    ]
    missing.json_responses[endpoint] = [_json_page(remaining, "jobs")]
    with pytest.raises(VerificationError, match="exact three live checks"):
        verify_workflow_state(missing)

    # A routine push/schedule run that actually executed the dispatch job is hostile.
    executed, _ = _live_fixture()
    dispatch_job = next(
        job
        for job in executed.json_responses[endpoint][0]["jobs"]
        if job["name"] == DISPATCH_JOB_NAME
    )
    executed.json_responses[dispatch_job["check_run_url"]][0]["conclusion"] = "success"
    with pytest.raises(VerificationError, match="historical-backfill dispatch job did not skip"):
        verify_workflow_state(executed)

    # The dispatch job may never masquerade as a live check.
    renamed, _ = _live_fixture()
    dispatch_job = next(
        job
        for job in renamed.json_responses[endpoint][0]["jobs"]
        if job["name"] == DISPATCH_JOB_NAME
    )
    dispatch_job["name"] = "contract-drift-main-receipt"
    with pytest.raises(VerificationError, match="duplicate names"):
        verify_workflow_state(renamed)


def _register_attempt_jobs(reader: FixtureApiReader, *, run: dict[str, Any], conclusions: dict[str, str]) -> None:  # fmt: skip
    for attempt in range(1, run["run_attempt"] + 1):
        jobs: list[dict[str, Any]] = []
        for offset, name in enumerate(FIXTURE_ATTEMPT_JOB_NAMES, start=1):
            job, check_url, check = _job_record(name, run_id=run["id"], main_sha=run["head_sha"], attempt=attempt, job_id=run["id"] * 1_000 + attempt * 100 + offset, conclusion=conclusions[name])  # fmt: skip
            jobs.append(job)
            reader.json_responses[check_url] = [check]
        endpoint = f"repos/{FIXTURE_REPO}/actions/runs/{run['id']}/attempts/{attempt}/jobs?per_page=100&page=1"
        reader.json_responses[endpoint] = [_json_page(jobs, "jobs")]


def test_live_verifier_selects_the_newest_routine_run_past_historical_backfill_dispatches():
    runs_endpoint = (
        f"repos/{FIXTURE_REPO}/actions/workflows/{CANONICAL_WORKFLOW_ID}/runs?per_page=100&page=1"
    )
    routine = _run_record(run_id=7001, started_at="2026-08-12T01:00:00Z")
    backfill = _run_record(run_id=7002, started_at="2026-08-12T02:00:00Z", event="workflow_dispatch", conclusion="success")  # fmt: skip
    reader, _ = _live_fixture(runs=[routine])
    reader.json_responses[runs_endpoint] = [_json_page([routine, backfill], "workflow_runs")] * 4
    _register_attempt_jobs(reader, run=backfill, conclusions=BACKFILL_DISPATCH_CONCLUSIONS)
    result = verify_workflow_state(reader)
    assert result["selection"]["identity"] == {"run_started_at": routine["run_started_at"], "run_id": 7001, "run_attempt": 1}  # fmt: skip
    assert result["selection"]["selected_attempt"]["auxiliary_jobs"] == {
        DISPATCH_JOB_NAME: "skipped"
    }
    assert result["stable_requery"] is True

    # A historical_backfill=false dispatch is a routine receipt and still wins as newest.
    routine_dispatch = _run_record(run_id=7003, started_at="2026-08-12T03:00:00Z", event="workflow_dispatch")  # fmt: skip
    reader, _ = _live_fixture(runs=[routine, routine_dispatch])
    assert verify_workflow_state(reader)["selection"]["identity"]["run_id"] == 7003

    # With only a backfill dispatch at main's tip there is no routine execution to verify.
    only_backfill, _ = _live_fixture(runs=[backfill])
    _register_attempt_jobs(only_backfill, run=backfill, conclusions=BACKFILL_DISPATCH_CONCLUSIONS)
    with pytest.raises(VerificationError, match="matches current main"):
        verify_workflow_state(only_backfill)

    # A dispatch run whose attempt hides program-trajectory cannot be classified.
    hidden, _ = _live_fixture(runs=[routine])
    hidden.json_responses[runs_endpoint] = [_json_page([routine, backfill], "workflow_runs")] * 4
    _register_attempt_jobs(hidden, run=backfill, conclusions=BACKFILL_DISPATCH_CONCLUSIONS)
    jobs_endpoint = f"repos/{FIXTURE_REPO}/actions/runs/{backfill['id']}/attempts/1/jobs?per_page=100&page=1"  # fmt: skip
    remaining = [
        job
        for job in hidden.json_responses[jobs_endpoint][0]["jobs"]
        if job["name"] != "contract-drift-program-trajectory"
    ]
    hidden.json_responses[jobs_endpoint] = [_json_page(remaining, "jobs")]
    with pytest.raises(VerificationError, match="does not expose the program-trajectory job"):
        verify_workflow_state(hidden)


def test_program_trajectory_preserves_real_red_exit(tmp_path):
    program = JOBS["program-trajectory"]
    assert "continue-on-error" not in str(program)
    analyzer = _analyzer_step(program_id := "program-trajectory")
    assert "if" not in analyzer, program_id
    env = {"SOURCE_SHA": "c" * 40, "GITHUB_WORKSPACE": str(tmp_path)}
    result = _simulate_step(
        _analyzer_step_text(program), env=env, cwd=tmp_path, stubs={"python3": 7}
    )
    assert result.returncode == 7
    assert (tmp_path / "contract-drift-program-trajectory.json").exists()


def test_contract_drift_authoritative_steps_propagate_nonzero_exit(tmp_path):
    env = {
        "BASE_SHA": "a" * 40,
        "EVENT_NAME": "push",
        "HEAD_SHA": "b" * 40,
        "HISTORICAL_BACKFILL": "false",
        "SOURCE_SHA": "c" * 40,
        "GITHUB_WORKSPACE": str(tmp_path),
    }
    for job_id in ("pr-delta", "main-receipt", "program-trajectory"):
        workdir = tmp_path / job_id
        workdir.mkdir()
        result = _simulate_step(
            _analyzer_step(job_id)["run"],
            env=env,
            cwd=workdir,
            stubs={"python3": 5, "git": 0, "date": 0},
        )
        assert result.returncode == 5, (job_id, result.stderr)


def test_every_contract_drift_authoritative_pipeline_enables_pipefail_before_first_pipe(tmp_path):
    pipe = re.compile(r"(?<!\|)\|(?!\|)")
    for job_id in ("pr-delta", "main-receipt", "program-trajectory"):
        run = _analyzer_step(job_id)["run"]
        lines = run.splitlines()
        first_pipe = next(index for index, line in enumerate(lines) if pipe.search(line))
        assert "set -euo pipefail" in lines[:first_pipe][0], job_id
    # Behavioral contrast: the same pipeline without pipefail lets tee's zero
    # exit mask the red analyzer.
    run = _analyzer_step("main-receipt")["run"]
    env = {
        "EVENT_NAME": "push",
        "HISTORICAL_BACKFILL": "false",
        "SOURCE_SHA": "d" * 40,
        "GITHUB_WORKSPACE": str(tmp_path),
    }
    with_pipefail = _simulate_step(run, env=env, cwd=tmp_path, stubs={"python3": 9})
    without = _simulate_step(
        run.replace("set -euo pipefail\n", ""), env=env, cwd=tmp_path, stubs={"python3": 9}
    )
    assert with_pipefail.returncode == 9 and without.returncode == 0


def test_contract_drift_outputs_are_required_before_summary(tmp_path):
    terminal = _terminal_step()["run"]
    lines = terminal.splitlines()
    outcome_line = next(index for index, line in enumerate(lines) if "steps.admission.outcome" in line)  # fmt: skip
    output_line = next(index for index, line in enumerate(lines) if "test -s contract-drift-pr-delta.json" in line)  # fmt: skip
    summary_line = next(index for index, line in enumerate(lines) if "accepted_authority" in line)
    assert outcome_line < output_line < summary_line
    empty = _run_terminal(tmp_path / "empty", outcome="success", payload="")
    assert empty.returncode != 0
    present = _run_terminal(tmp_path / "present", outcome="success", payload='{"admitted": true}\n')
    assert present.returncode == 0


def test_skipped_or_cancelled_cdg_authority_job_cannot_report_success(tmp_path):
    # The terminal aggregator turns a skipped admission into a hard failure
    # instead of an implicit green.
    for index, conclusion in enumerate(("skipped", "cancelled")):
        result = _run_terminal(
            tmp_path / str(index), outcome=conclusion, payload='{"admitted": true}\n'
        )
        assert result.returncode != 0


# --- VAL-CDG-009: separate immutable signals (workflow side) ----------------


def test_pull_request_invokes_only_pr_mode():
    assert JOBS["pr-delta"]["if"] == "github.event_name == 'pull_request' && !github.event.pull_request.draft"  # fmt: skip
    admission = _analyzer_step("pr-delta")["run"]
    assert "--mode pr" in admission
    assert "--mode receipt" not in str(JOBS["pr-delta"])
    assert "--mode program" not in str(JOBS["pr-delta"])
    # The two main-only jobs are event-disjoint from PR admission.
    assert JOBS["main-receipt"]["if"] == "github.event_name != 'pull_request'"
    assert JOBS["program-trajectory"]["if"].startswith("github.event_name != 'pull_request'")


def test_pull_request_uses_immutable_event_base_and_head_shas():
    env = JOBS["pr-delta"]["env"]
    assert env == {
        "BASE_SHA": "${{ github.event.pull_request.base.sha }}",
        "HEAD_SHA": "${{ github.event.pull_request.head.sha }}",
    }
    admission = _analyzer_step("pr-delta")["run"]
    assert admission.index("git fetch") < admission.index("--base-ref")
    assert '"$BASE_SHA" "$HEAD_SHA"' in admission
    # The upload key is bound to the same immutable event head SHA.
    assert _upload_step("pr-delta")["with"]["name"].endswith(
        "${{ github.event.pull_request.head.sha }}"
    )


def test_synthetic_merge_sha_is_rejected_for_pr_delta():
    pr_text = str(JOBS["pr-delta"])
    # The synthetic refs/pull/N/merge commit and its aliases never reach the
    # analyzer: no merge_commit_sha, no github.sha, no mutable ref names.
    assert "merge_commit_sha" not in pr_text
    assert "github.sha" not in pr_text
    assert "refs/pull" not in pr_text and "github.ref" not in pr_text
    admission = _analyzer_step("pr-delta")["run"]
    for flag, value in (("--base-ref", '"$BASE_SHA"'), ("--head-ref", '"$HEAD_SHA"')):
        assert f"{flag} {value}" in admission
    assert "GITHUB_SHA" not in admission and "HEAD^" not in admission


def test_push_main_binds_receipt_and_program_to_event_after_sha():
    assert DOC["on"]["push"]["branches"] == ["main"]
    assert "github.event.after" in SOURCE_SHA_EXPR
    receipt = JOBS["main-receipt"]
    assert receipt["env"]["SOURCE_SHA"] == HISTORICAL_SOURCE_SHA_EXPR
    assert receipt["steps"][0]["with"]["ref"] == HISTORICAL_SOURCE_SHA_EXPR
    program = JOBS["program-trajectory"]
    assert program["env"]["SOURCE_SHA"] == SOURCE_SHA_EXPR
    assert program["steps"][0]["with"]["ref"] == SOURCE_SHA_EXPR
    for job in (receipt, program):
        assert '--ref "$SOURCE_SHA"' in _analyzer_step_text(job)


def test_schedule_and_dispatch_resolve_main_once_for_both_main_jobs():
    assert "schedule" in DOC["on"] and "workflow_dispatch" in DOC["on"]
    # For non-push events the shared expression falls back to the single
    # resolved github.sha, so receipt and trajectory bind one identical SHA.
    assert SOURCE_SHA_EXPR.endswith("|| github.sha }}")
    receipt, program = JOBS["main-receipt"], JOBS["program-trajectory"]
    assert receipt["env"]["SOURCE_SHA"] == HISTORICAL_SOURCE_SHA_EXPR
    assert receipt["steps"][0]["with"]["ref"] == HISTORICAL_SOURCE_SHA_EXPR
    assert program["env"]["SOURCE_SHA"] == SOURCE_SHA_EXPR
    assert program["steps"][0]["with"]["ref"] == SOURCE_SHA_EXPR
    assert TEXT.count(SOURCE_SHA_EXPR) == 2
    # Receipt env + receipt checkout ref + the dispatch job's SOURCE_SHA, which
    # must bind the identical resolved SHA into the finalizer payload.
    assert TEXT.count(HISTORICAL_SOURCE_SHA_EXPR) == 3
    assert JOBS[DISPATCH_JOB_ID]["env"]["SOURCE_SHA"] == HISTORICAL_SOURCE_SHA_EXPR


def test_exact_three_live_check_names_are_separate():
    assert len(set(JOBS)) == 4 and len(set(_job_names(DOC))) == 4
    assert set(_job_names(DOC)) & set(LIVE_CHECK_NAMES) == set(LIVE_CHECK_NAMES)
    assert JOBS[DISPATCH_JOB_ID]["name"] not in LIVE_CHECK_NAMES
    artifact_names = {job_id: _upload_step(job_id)["with"]["name"] for job_id in LIVE_JOB_IDS}
    assert len(set(artifact_names.values())) == 3
    outputs = {job_id: _upload_step(job_id)["with"]["path"] for job_id in LIVE_JOB_IDS}
    assert len(set(outputs.values())) == 3
    for job_id in LIVE_JOB_IDS:
        assert f"contract-drift-{job_id}-" in artifact_names[job_id]
        assert f"contract-drift-{job_id}.json" in outputs[job_id]
    # The dispatch job publishes nothing: no upload step, no live check name.
    with pytest.raises(AssertionError, match="no upload step"):
        _upload_step(DISPATCH_JOB_ID)


def test_terminal_aggregator_fails_when_pr_delta_is_skipped(tmp_path):
    terminal = _terminal_step()
    # `always()` forces the aggregator to run and judge a skipped admission
    # rather than letting the job end green with the step silently absent.
    assert terminal["if"] == "always()"
    assert "steps.admission.outcome" in terminal["run"]
    result = _run_terminal(tmp_path, outcome="skipped", payload='{"admitted": true}\n')
    assert result.returncode == 1
    assert 'test "skipped" = "success"' in terminal["run"].replace(
        "${{ steps.admission.outcome }}", "skipped"
    )


def test_main_receipt_job_is_separate_from_intentionally_red_trajectory():
    receipt, program = JOBS["main-receipt"], JOBS["program-trajectory"]
    assert "needs" not in receipt and "needs" not in program
    assert receipt["name"] == "contract-drift-main-receipt"
    assert program["name"] == "contract-drift-program-trajectory"
    assert "--mode receipt" in _analyzer_step_text(receipt)
    assert "--mode program" in _analyzer_step_text(program)
    assert _upload_step("main-receipt")["with"]["name"] != _upload_step("program-trajectory")["with"]["name"]  # fmt: skip


def test_trajectory_failure_does_not_block_main_receipt(tmp_path):
    # No job anywhere in the workflow declares a dependency on the trajectory
    # job, so its intentionally red exit cannot gate the receipt. The only
    # `needs` edge is the gated dispatch job depending on the receipt itself.
    for job_id, job in JOBS.items():
        needs = job.get("needs", [])
        needs = [needs] if isinstance(needs, str) else list(needs)
        assert "program-trajectory" not in needs
        assert needs == (["main-receipt"] if job_id == DISPATCH_JOB_ID else []), job_id
    env = {
        "EVENT_NAME": "push",
        "HISTORICAL_BACKFILL": "false",
        "SOURCE_SHA": "e" * 40,
        "GITHUB_WORKSPACE": str(tmp_path),
    }
    trajectory = _simulate_step(
        _analyzer_step_text(JOBS["program-trajectory"]),
        env=env,
        cwd=tmp_path,
        stubs={"python3": 21},  # fmt: skip
    )
    receipt = _simulate_step(
        _analyzer_step_text(JOBS["main-receipt"]), env=env, cwd=tmp_path, stubs={"python3": 0}
    )
    assert trajectory.returncode == 21 and receipt.returncode == 0
    assert (tmp_path / "contract-drift-main-receipt.json").exists()


def test_main_receipt_success_does_not_mask_trajectory_failure(tmp_path):
    program = JOBS["program-trajectory"]
    assert "continue-on-error" not in str(program)
    # The trajectory job has no aggregator step that could rewrite its
    # conclusion: the analyzer is the last conditioned enforcement point and
    # the only later step is the always-on artifact upload.
    *_, analyzer, upload = program["steps"]
    assert "check_contract_drift_ratchet.py" in analyzer["run"]
    assert upload["uses"].startswith("actions/upload-artifact@")
    env = {
        "EVENT_NAME": "push",
        "HISTORICAL_BACKFILL": "false",
        "SOURCE_SHA": "f" * 40,
        "GITHUB_WORKSPACE": str(tmp_path),
    }
    receipt = _simulate_step(
        _analyzer_step_text(JOBS["main-receipt"]), env=env, cwd=tmp_path, stubs={"python3": 0}
    )
    trajectory = _simulate_step(
        _analyzer_step_text(program), env=env, cwd=tmp_path, stubs={"python3": 13}
    )
    assert receipt.returncode == 0 and trajectory.returncode == 13


def test_program_red_cannot_mask_or_replace_pr_delta_result():
    # PR admission and program trajectory run on disjoint events, publish
    # differently named artifacts, and satisfy different required contexts.
    assert JOBS["pr-delta"]["if"].startswith("github.event_name == 'pull_request'")
    assert JOBS["program-trajectory"]["if"].startswith("github.event_name != 'pull_request'")
    assert "contract-drift-pr-delta.json" not in str(JOBS["program-trajectory"])
    assert "contract-drift-program-trajectory.json" not in str(JOBS["pr-delta"])


@pytest.mark.skipif(
    os.environ.get("ARAGORA_RUN_LIVE_CDG_WORKFLOW_TEST") != "1",
    reason="set ARAGORA_RUN_LIVE_CDG_WORKFLOW_TEST=1 for authenticated read-only GitHub verification",
)
def test_live_contract_drift_workflow_selection_is_stable_twice():
    first = verify_workflow_state(GhApiReader())
    second = verify_workflow_state(GhApiReader())
    assert first["workflow"] == second["workflow"]
    assert first["main_sha"] == second["main_sha"]
    assert first["selection"]["identity"] == second["selection"]["identity"]
    assert first["stable_requery"] is second["stable_requery"] is True
