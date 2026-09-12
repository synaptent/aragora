"""Exercise monitor shell blocks without calling any live service."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
PROBES = (
    ("production-smoke.yml", "smoke", "Check backend health"),
    ("production-smoke.yml", "smoke", "Check playground status endpoint"),
    ("monitor.yml", "health-check", "Check Production API (Lightsail)"),
)


def _workflow(filename: str) -> dict:
    return yaml.load((ROOT / ".github/workflows" / filename).read_text(), Loader=yaml.BaseLoader)


def _step(filename: str, job: str, name: str) -> dict:
    return next(step for step in _workflow(filename)["jobs"][job]["steps"] if step["name"] == name)


def _run_probe(
    tmp_path: Path,
    probe: tuple[str, str, str],
    http_status: str,
    curl_exit: int,
    body: str = '{"status":"ok"}',
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        """#!/bin/bash
printf '%s\\n' "$@" > "$CURL_ARGS_FILE"
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-o" ]; then
    shift
    if [ "$1" != "/dev/null" ]; then
      printf '%s' "$CURL_BODY" > "$1"
    fi
  fi
  shift
done
printf '%s' "$CURL_HTTP_STATUS"
exit "$CURL_EXIT_STATUS"
"""
    )
    curl.chmod(0o700)
    # Redirect only the fixed response file, keeping concurrent tests isolated.
    script = _step(*probe)["run"].replace(
        "/tmp/playground-status.json", str(tmp_path / "playground-status.json")
    )
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "API_URL": "https://monitor.invalid",
            "CURL_HTTP_STATUS": http_status,
            "CURL_EXIT_STATUS": str(curl_exit),
            "CURL_BODY": body,
            "CURL_ARGS_FILE": str(tmp_path / "curl-args"),
        },
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    args = (tmp_path / "curl-args").read_text().splitlines()
    if probe[0] == "production-smoke.yml":
        assert args[args.index("--max-time") + 1] == "10"
        endpoint = "/healthz" if probe == PROBES[0] else "/api/v1/playground/status"
        assert args[-1] == f"https://monitor.invalid{endpoint}"
    else:
        assert args[-1] == "https://api.aragora.ai/api/health"
        assert "-sf" in args
    return result


@pytest.mark.parametrize("probe", PROBES, ids=["health", "playground", "production-api"])
@pytest.mark.parametrize(
    ("http_status", "curl_exit", "expected_status"),
    [
        ("200", 0, "200"),
        ("500", 0, "500"),
        ("522", 22, "522"),
        ("000", 28, "000"),
        ("000", 6, "000"),
        ("", 7, "000"),
        ("", 0, "000"),
        ("200", 28, "200"),
    ],
)
def test_probe_reports_http_and_transport_separately(
    tmp_path: Path,
    probe: tuple[str, str, str],
    http_status: str,
    curl_exit: int,
    expected_status: str,
) -> None:
    result = _run_probe(tmp_path, probe, http_status, curl_exit)
    assert (result.returncode == 0) == (http_status == "200" and curl_exit == 0)
    assert f"http_status={expected_status} curl_exit={curl_exit}" in result.stdout
    assert "000000" not in result.stdout
    assert "522000" not in result.stdout


def test_playground_still_requires_ok_payload(tmp_path: Path) -> None:
    result = _run_probe(tmp_path, PROBES[1], "200", 0, '{"status":"unavailable"}')
    assert result.returncode != 0
    assert "missing expected ok marker" in result.stdout


@pytest.mark.parametrize(
    ("frontend", "production"),
    [
        ("success", "failure"),
        ("failure", "skipped"),
        ("success", "cancelled"),
        ("success", "success"),
    ],
)
def test_summary_uses_individual_step_outcomes(
    tmp_path: Path, frontend: str, production: str
) -> None:
    frontend_step = _step("monitor.yml", "health-check", "Check Frontend Critical Routes")
    production_step = _step(*PROBES[2])
    summary = _step("monitor.yml", "health-check", "Summary")
    assert frontend_step["id"] == "frontend"
    assert production_step["id"] == "production_api"
    assert summary["if"] == "always()"
    assert "job.status" not in json.dumps(summary)
    expressions = {
        "${{ steps.frontend.outcome }}": frontend,
        "${{ steps.production_api.outcome }}": production,
    }
    assert set(summary["env"].values()) == set(expressions)
    env = {key: expressions[value] for key, value in summary["env"].items()}
    report = tmp_path / "summary.md"
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", summary["run"]],
        env={"PATH": os.defpath, "GITHUB_STEP_SUMMARY": str(report), **env},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    text = report.read_text()
    assert f"| Frontend (Vercel/custom domain) | {frontend} |" in text
    assert f"| Production API | {production} |" in text


@pytest.mark.parametrize(
    "filename,job", [("production-smoke.yml", "smoke"), ("monitor.yml", "health-check")]
)
def test_monitor_schedule_and_failure_policy_are_unchanged(filename: str, job: str) -> None:
    workflow = _workflow(filename)
    assert workflow["on"]["schedule"] == [{"cron": "*/30 * * * *"}]
    assert "workflow_dispatch" in workflow["on"]
    assert workflow["jobs"][job]["timeout-minutes"] == "5"
    assert "continue-on-error" not in workflow["jobs"][job]
    for probe in PROBES:
        if probe[0] == filename:
            step = _step(*probe)
            assert "continue-on-error" not in step
            assert "if" not in step
            assert not re.search(r"\|\|\s*(true|echo)", step["run"])
