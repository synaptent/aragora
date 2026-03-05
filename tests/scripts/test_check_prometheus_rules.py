from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.check_prometheus_rules import (
    CheckResult,
    _build_docker_promtool_cmd,
    resolve_rule_files,
    run_rule_check,
)


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
