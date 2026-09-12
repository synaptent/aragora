"""Keep DAST scans bounded, reproducible, advisory, and off draft PRs."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/dast.yml"
DRAFT_GUARD = "github.event_name != 'pull_request' || !github.event.pull_request.draft"


@pytest.fixture
def workflow() -> dict:
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)


def step_named(job: dict, name: str) -> dict:
    return next(step for step in job["steps"] if step.get("name") == name)


def test_triggers_draft_guard_and_least_privilege(workflow: dict) -> None:
    assert set(workflow["on"]) == {"pull_request", "schedule"}
    assert {
        "aragora/server/**",
        "docs/api/openapi.json",
        ".github/workflows/dast.yml",
    } <= set(workflow["on"]["pull_request"]["paths"])
    assert "ready_for_review" in workflow["on"]["pull_request"]["types"]
    assert workflow["on"]["schedule"][0]["cron"]
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["dast-pr"]["if"] == DRAFT_GUARD
    for job in workflow["jobs"].values():
        if job["if"] != "github.event_name == 'schedule'":
            assert DRAFT_GUARD in job["if"]
        assert "permissions" not in job
        assert "continue-on-error" not in job
    assert workflow["concurrency"]["cancel-in-progress"] == (
        "${{ github.event_name == 'pull_request' }}"
    )


@pytest.mark.parametrize("job_id", ["dast-pr", "dast-nightly"])
def test_setup_and_cleanup_surround_scans(workflow: dict, job_id: str) -> None:
    job = workflow["jobs"][job_id]
    steps = job["steps"]
    checkout = step_named(job, "Checkout")
    assert re.fullmatch(r"actions/checkout@[0-9a-f]{40}", checkout["uses"])
    assert checkout["with"]["persist-credentials"] == "false"
    assert step_named(job, "Set up Python")["uses"] == "./.github/actions/setup-python-safe"
    install = step_named(job, "Install project")
    assert install["run"].strip() == "bash scripts/ci_install_project.sh --extras dev,test"
    start = step_named(job, "Start demo backend")
    assert "aragora serve --demo --host 0.0.0.0 --api-port 8080 --ws-port 8765" in start["run"]
    assert "nohup " in start["run"] and "&" in start["run"]
    assert 'echo $! > "$RUNNER_TEMP/dast-backend.pid"' in start["run"]
    health = step_named(job, "Wait for demo health")
    first_scan = next(s for s in steps if s.get("uses", "").startswith("zaproxy/"))
    assert steps.index(install) < steps.index(start) < steps.index(health) < steps.index(first_scan)
    rules = step_named(job, "Prepare ZAP rules")
    assert rules["run"] == "cp .zap/rules.tsv rules.tsv"
    assert steps.index(rules) < steps.index(first_scan)
    stop = step_named(job, "Stop demo backend")
    assert stop["if"] == "always()"
    assert 'kill "$(cat "$RUNNER_TEMP/dast-backend.pid")"' in stop["run"]
    logs = step_named(job, "Upload backend log")
    assert re.fullmatch(r"actions/upload-artifact@[0-9a-f]{40}", logs["uses"])
    assert logs["if"] == "always()"
    assert logs["with"]["path"] == "${{ runner.temp }}/dast-backend.log"


def test_pr_scans_are_pinned_safe_and_keep_distinct_reports(workflow: dict) -> None:
    job = workflow["jobs"]["dast-pr"]
    assert int(job["timeout-minutes"]) <= 10
    scans = [step for step in job["steps"] if step.get("uses", "").startswith("zaproxy/")]
    assert [s["uses"] for s in scans] == [
        "zaproxy/action-baseline@v0.15.0",
        "zaproxy/action-api-scan@v0.10.0",
    ]
    assert scans[0]["with"]["target"] == "http://localhost:8080"
    assert scans[0]["with"]["cmd_options"] == "-m 1 -I -c rules.tsv"
    assert scans[0]["with"]["artifact_name"] == "zap-baseline-report"
    assert scans[1]["with"]["target"] == "docs/api/openapi-dast.json"
    assert scans[1]["with"]["format"] == "openapi"
    assert scans[1]["with"]["cmd_options"] == "-S -I -T 3 -c rules.tsv"
    assert scans[1]["with"]["artifact_name"] == "zap-api-report"
    assert json.loads((ROOT / "docs/api/openapi-dast.json").read_text())["servers"] == [
        {"url": "http://localhost:8080"}
    ]


def test_all_scans_share_rules_and_cannot_write_issues(workflow: dict) -> None:
    artifacts = []
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if step.get("uses", "").startswith("zaproxy/"):
                options = step["with"]
                assert options["rules_file_name"] == ".zap/rules.tsv"
                assert "-c rules.tsv" in options["cmd_options"]
                assert "-I" in options["cmd_options"].split()
                assert options["fail_action"] == "false"
                assert options["allow_issue_writing"] == "false"
                artifacts.append(options["artifact_name"])
    assert len(artifacts) == len(set(artifacts)) == 3


def test_nightly_is_active_full_spec_and_capped(workflow: dict) -> None:
    job = workflow["jobs"]["dast-nightly"]
    assert job["if"] == "github.event_name == 'schedule'"
    assert job["timeout-minutes"] == "30"
    scan = next(step for step in job["steps"] if step.get("uses", "").startswith("zaproxy/"))
    assert scan["uses"] == "zaproxy/action-api-scan@v0.10.0"
    assert scan["with"]["target"] == "docs/api/openapi.json"
    assert scan["with"]["format"] == "openapi"
    options = scan["with"]["cmd_options"].split()
    assert "-S" not in options
    # Override all canonical servers, including the production URL.
    assert options[options.index("-O") + 1] == "http://localhost:8080"


def test_drift_step_uses_committed_inputs_and_fails_closed(workflow: dict) -> None:
    job = workflow["jobs"]["dast-pr"]
    step = step_named(job, "Check trimmed spec drift")
    assert step["shell"] == "bash"
    assert step["run"].splitlines() == [
        "set -euo pipefail",
        "python scripts/ci/trim_openapi.py --input docs/api/openapi.json "
        "--paths scripts/ci/zap_api_paths.txt --output docs/api/openapi-dast.json "
        "--server http://localhost:8080",
        "git diff --exit-code -- docs/api/openapi-dast.json",
    ]
    assert "continue-on-error" not in step
    assert job["steps"].index(step) < job["steps"].index(step_named(job, "Start demo backend"))


@pytest.mark.parametrize("job_id", ["dast-pr", "dast-nightly"])
@pytest.mark.parametrize(
    ("statuses", "curl_exit", "exit_code", "calls"),
    [
        ("200", 0, 0, 1),
        ("503", 0, 1, 30),
        ("302", 0, 1, 30),
        ("000", 7, 1, 30),
        ("503 503 200", 0, 0, 3),
    ],
)
def test_health_poll_requires_200_and_times_out(
    workflow: dict,
    job_id: str,
    statuses: str,
    curl_exit: int,
    exit_code: int,
    calls: int,
    tmp_path: Path,
) -> None:
    poll = step_named(workflow["jobs"][job_id], "Wait for demo health")["run"]
    assert "http://localhost:8080/healthz" in poll
    assert "--max-time 2" in poll
    curl = tmp_path / "curl"
    curl.write_text(
        "#!/bin/bash\n"
        'n=0; if [ -f "$CALLS" ]; then n=$(cat "$CALLS"); fi\n'
        'n=$((n+1)); echo "$n" > "$CALLS"\n'
        'read -ra statuses <<< "$STATUSES"\n'
        "i=$((n-1)); if ((i >= ${#statuses[@]})); then i=$((${#statuses[@]}-1)); fi\n"
        'printf "%s" "${statuses[$i]}"\nexit "$CURL_EXIT"\n'
    )
    sleep = tmp_path / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n")
    curl.chmod(0o755)
    sleep.chmod(0o755)
    counter = tmp_path / "calls"
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", poll],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "CALLS": str(counter),
            "STATUSES": statuses,
            "CURL_EXIT": str(curl_exit),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert int(counter.read_text()) == calls
    if exit_code:
        assert "::error::Demo backend did not become healthy" in result.stdout
