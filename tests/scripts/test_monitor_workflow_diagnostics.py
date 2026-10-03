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
WEBSOCKET = ("monitor.yml", "health-check", "Check WebSocket Endpoint")
STAGING = ("monitor.yml", "health-check", "Check Staging API (EC2)")


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
    script = (
        _step(*probe)["run"]
        .replace("/tmp/playground-status.json", str(tmp_path / "playground-status.json"))
        .replace("${{ secrets.EC2_HOST }}", "staging.invalid")
    )
    result = subprocess.run(
        ["bash", "-e", "-c", script],
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
    elif probe == WEBSOCKET:
        assert args[-1] == "https://api.aragora.ai/ws"
        assert "Upgrade: websocket" in args
        assert "Connection: Upgrade" in args
        # HTTP error statuses still prove reachability; curl -f would hide that.
        assert "-s" in args
        assert "-sf" not in args
    elif probe == STAGING:
        assert "http://staging.invalid:8080/api/health" in args
        assert args[args.index("--connect-timeout") + 1] == "10"
        assert "-sf" in args
    else:
        assert args[-1] == "https://api.aragora.ai/api/health"
        assert "-sf" in args
    return result


@pytest.mark.parametrize("probe", PROBES, ids=["health", "playground", "production-api"])
@pytest.mark.parametrize(
    ("http_status", "curl_exit", "expected_status"),
    [
        ("200", 0, "200"),
        ("500", 22, "500"),
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
    ("http_status", "curl_exit", "reachable"),
    [
        ("101", 0, True),
        ("200", 0, True),
        ("301", 0, True),
        ("400", 0, True),
        ("404", 0, True),
        ("500", 0, True),
        ("000", 28, False),
        ("000", 6, False),
        ("", 7, False),
        ("200", 28, False),
        ("000", 0, False),
        ("", 0, False),
        ("000000", 0, False),
    ],
)
def test_websocket_requires_transport_success_not_http_health(
    tmp_path: Path, http_status: str, curl_exit: int, reachable: bool
) -> None:
    result = _run_probe(tmp_path, WEBSOCKET, http_status, curl_exit)
    assert (result.returncode == 0) == reachable, result.stdout
    assert f"http_status={http_status or '000'} curl_exit={curl_exit}" in result.stdout
    assert ("WebSocket endpoint reachable" in result.stdout) == reachable


@pytest.mark.parametrize(
    ("http_status", "curl_exit"), [("200", 0), ("500", 22), ("000", 28), ("200", 28)]
)
def test_staging_failure_is_visible_but_advisory(
    tmp_path: Path, http_status: str, curl_exit: int
) -> None:
    result = _run_probe(tmp_path, STAGING, http_status, curl_exit)
    healthy = http_status == "200" and curl_exit == 0
    assert (result.returncode == 0) == healthy, result.stdout
    assert f"http_status={http_status} curl_exit={curl_exit}" in result.stdout
    assert ("::warning::" in result.stdout) == (not healthy)
    assert _step(*STAGING)["continue-on-error"] == "true"


@pytest.mark.parametrize("service", ["frontend", "production_api", "websocket", "staging_api"])
@pytest.mark.parametrize("outcome", ["success", "failure", "skipped", "cancelled", ""])
def test_summary_uses_individual_step_outcomes(tmp_path: Path, service: str, outcome: str) -> None:
    frontend_step = _step("monitor.yml", "health-check", "Check Frontend Critical Routes")
    production_step = _step(*PROBES[2])
    summary = _step("monitor.yml", "health-check", "Summary")
    assert frontend_step["id"] == "frontend"
    assert production_step["id"] == "production_api"
    assert _step(*WEBSOCKET)["id"] == "websocket"
    assert _step(*STAGING)["id"] == "staging_api"
    assert summary["if"] == "always()"
    assert "job.status" not in json.dumps(summary)
    outcomes = dict.fromkeys(["frontend", "production_api", "websocket", "staging_api"], "success")
    outcomes[service] = outcome
    expressions = {"${{ steps." + key + ".outcome }}": value for key, value in outcomes.items()}
    assert set(summary["env"].values()) == set(expressions)
    env = {key: expressions[value] for key, value in summary["env"].items()}
    report = tmp_path / "summary.md"
    result = subprocess.run(
        ["bash", "-e", "-c", summary["run"]],
        env={"PATH": os.defpath, "GITHUB_STEP_SUMMARY": str(report), **env},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    text = report.read_text()
    for key, label, policy in [
        ("frontend", "Frontend (Vercel/custom domain)", "blocking"),
        ("production_api", "Production API", "blocking"),
        ("websocket", "WebSocket endpoint", "blocking"),
        ("staging_api", "Staging API", "advisory (non-blocking)"),
    ]:
        assert f"| {label} | {outcomes[key] or 'skipped'} | {policy} |" in text


@pytest.mark.parametrize(
    "filename,job", [("production-smoke.yml", "smoke"), ("monitor.yml", "health-check")]
)
def test_monitor_schedule_and_failure_policy_are_unchanged(filename: str, job: str) -> None:
    workflow = _workflow(filename)
    assert workflow["on"]["schedule"] == [{"cron": "*/30 * * * *"}]
    assert "workflow_dispatch" in workflow["on"]
    assert workflow["jobs"][job]["timeout-minutes"] == "5"
    assert "continue-on-error" not in workflow["jobs"][job]
    assert "shell" not in workflow.get("defaults", {}).get("run", {})
    assert "shell" not in workflow["jobs"][job].get("defaults", {}).get("run", {})
    for probe in (*PROBES, WEBSOCKET, STAGING):
        if probe[0] == filename:
            step = _step(*probe)
            assert "shell" not in step  # GitHub's implicit Linux shell is bash -e.
            if probe == STAGING:
                assert step["continue-on-error"] == "true"
            else:
                assert "continue-on-error" not in step
            assert "if" not in step
            assert not re.search(r"\|\|\s*(true|echo)", step["run"])
    if filename == "monitor.yml":
        assert "shell" not in _step(filename, job, "Summary")
        assert workflow["jobs"]["notify-on-failure"]["if"] == "failure()"
