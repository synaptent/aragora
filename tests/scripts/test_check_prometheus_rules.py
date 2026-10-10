from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.check_prometheus_rules import (
    DEFAULT_DOCKER_TIMEOUT_S,
    CheckResult,
    _build_docker_promtool_cmd,
    resolve_rule_files,
    run_rule_check,
)

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/check_prometheus_rules.py"


def _docker_only(name: str) -> str | None:
    return "/usr/bin/docker" if name == "docker" else None


def test_resolve_rule_files_splits_existing_and_missing(tmp_path: Path) -> None:
    existing_rel = "deploy/alerting/prometheus-rules.yml"
    missing_rel = "deploy/monitoring/alerts.yaml"
    existing_path = tmp_path / existing_rel
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text("groups: []\n", encoding="utf-8")

    existing, missing = resolve_rule_files(tmp_path, [existing_rel, missing_rel])

    assert existing == [existing_path.resolve()]
    assert missing == [(tmp_path / missing_rel).resolve()]


def test_build_docker_promtool_cmd_uses_relative_workspace_paths(tmp_path: Path) -> None:
    rule_file = tmp_path / "deploy/observability/alerts.rules"
    rule_file.parent.mkdir(parents=True, exist_ok=True)
    rule_file.write_text("groups: []\n", encoding="utf-8")

    cmd = _build_docker_promtool_cmd(tmp_path, [rule_file], image="prom/prometheus:test")

    assert cmd[:8] == [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{tmp_path.resolve()}:/workspace",
        "-w",
        "/workspace",
        "prom/prometheus:test",
    ]
    assert cmd[-4:] == ["promtool", "check", "rules", "deploy/observability/alerts.rules"]


def test_run_rule_check_prefers_native_promtool(tmp_path: Path) -> None:
    rule_file = tmp_path / "alerts.yml"
    rule_file.write_text("groups: []\n", encoding="utf-8")
    called: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        if name == "promtool":
            return "/usr/local/bin/promtool"
        return None

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        called.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    result = run_rule_check(tmp_path, [rule_file], which=fake_which, run=fake_run)

    assert result.returncode == 0
    assert called == [["promtool", "check", "rules", str(rule_file)]]


def test_run_rule_check_falls_back_to_docker(tmp_path: Path) -> None:
    rule_file = tmp_path / "deploy/observability/alerts.rules"
    rule_file.parent.mkdir(parents=True, exist_ok=True)
    rule_file.write_text("groups: []\n", encoding="utf-8")
    called: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        if name == "docker":
            return "/usr/bin/docker"
        return None

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        called.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    result = run_rule_check(
        tmp_path,
        [rule_file],
        which=fake_which,
        run=fake_run,
        docker_image="prom/prometheus:test",
    )

    assert result.returncode == 0
    assert called
    assert called[0][:8] == [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{tmp_path.resolve()}:/workspace",
        "-w",
        "/workspace",
        "prom/prometheus:test",
    ]


def test_run_rule_check_errors_when_no_tool_available(tmp_path: Path) -> None:
    rule_file = tmp_path / "alerts.yml"
    rule_file.write_text("groups: []\n", encoding="utf-8")

    result = run_rule_check(tmp_path, [rule_file], which=lambda _: None)

    assert isinstance(result, CheckResult)
    assert result.returncode == 0
    assert "Fallback YAML validation passed" in result.output


def test_run_rule_check_docker_failure_uses_yaml_fallback(tmp_path: Path) -> None:
    rule_file = tmp_path / "alerts.yml"
    rule_file.write_text("groups: []\n", encoding="utf-8")

    def fake_which(name: str) -> str | None:
        if name == "docker":
            return "/usr/bin/docker"
        return None

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, "", "Cannot connect to docker daemon")

    result = run_rule_check(tmp_path, [rule_file], which=fake_which, run=fake_run)

    assert result.returncode == 0
    assert result.command == ["python", "yaml-safe-load"]
    assert "Using YAML fallback check" in result.error


def test_docker_fallback_run_is_bounded_by_default_timeout(tmp_path: Path) -> None:
    rule_file = tmp_path / "alerts.yml"
    rule_file.write_text("groups: []\n", encoding="utf-8")
    seen: list[dict[str, object]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    assert run_rule_check(tmp_path, [rule_file], which=_docker_only, run=fake_run).returncode == 0
    assert DEFAULT_DOCKER_TIMEOUT_S > 0
    assert seen == [{"capture_output": True, "text": True, "timeout": DEFAULT_DOCKER_TIMEOUT_S}]


def test_docker_timeout_takes_yaml_fallback_within_the_bound(tmp_path: Path) -> None:
    rule_file = tmp_path / "alerts.yml"
    rule_file.write_text("groups: []\n", encoding="utf-8")
    bounds: list[float] = []

    def wedged_docker(
        cmd: list[str], *, timeout: float, **_: object
    ) -> subprocess.CompletedProcess[str]:
        bounds.append(timeout)
        raise subprocess.TimeoutExpired(cmd, timeout)

    started = time.monotonic()
    result = run_rule_check(
        tmp_path, [rule_file], which=_docker_only, run=wedged_docker, docker_timeout_s=0.5
    )

    assert time.monotonic() - started < 5
    assert bounds == [0.5]
    assert result.returncode == 0
    assert result.command == ["python", "yaml-safe-load"]
    assert "Fallback YAML validation passed" in result.output
    assert "timed out after 0.5" in result.error


def test_docker_timeout_with_failing_fallback_reports_the_timeout(tmp_path: Path) -> None:
    rule_file = tmp_path / "alerts.yml"
    rule_file.write_text("not_groups: true\n", encoding="utf-8")

    def wedged_docker(
        cmd: list[str], *, timeout: float, **_: object
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd, timeout)

    result = run_rule_check(tmp_path, [rule_file], which=_docker_only, run=wedged_docker)

    assert result.returncode != 0
    assert f"timed out after {DEFAULT_DOCKER_TIMEOUT_S:g}" in result.error
    assert "expected top-level `groups` list" in result.error


def test_help_documents_the_docker_timeout_and_its_default() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0
    help_text = " ".join(result.stdout.split())
    assert "--docker-timeout" in help_text
    assert f"default: {DEFAULT_DOCKER_TIMEOUT_S:g} seconds" in help_text


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "soon"])
def test_invalid_docker_timeout_is_a_usage_error(value: str) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--docker-timeout", value],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert "--docker-timeout" in result.stderr
    assert "Traceback" not in result.stderr
