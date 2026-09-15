"""Keep standalone package CI and local pre-push gates effective."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
HOOK_APPS = {
    "packages-ruff": ("debate", "verify"),
    "debate-strict-mypy": ("debate",),
    "verify-strict-mypy": ("verify",),
}


def _hooks() -> dict:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    return {hook["id"]: hook for repo in config["repos"] for hook in repo["hooks"]}


def test_workflow_paths_and_least_privilege() -> None:
    workflow = yaml.load(
        (ROOT / ".github/workflows/packages-ci.yml").read_text(), Loader=yaml.BaseLoader
    )
    for event in ("pull_request", "push"):
        assert {
            "aragora-debate/**",
            "aragora-verify/**",
            ".github/workflows/packages-ci.yml",
            "Makefile",
            "pyproject.toml",
        } <= set(workflow["on"][event]["paths"])
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["packages"]
    assert job["strategy"]["fail-fast"] == "false"
    assert {row["app"] for row in job["strategy"]["matrix"]["include"]} == {"debate", "verify"}
    assert int(job["timeout-minutes"]) <= 10
    assert "continue-on-error" not in job


def test_workflow_runs_strict_types_ratchets_and_timed_coverage() -> None:
    workflow = yaml.load(
        (ROOT / ".github/workflows/packages-ci.yml").read_text(), Loader=yaml.BaseLoader
    )
    steps = workflow["jobs"]["packages"]["steps"]
    install = next(step["run"] for step in steps if step["name"] == "Install package and tools")
    assert "python -m pip install" in install
    for requirement in ("mypy==2.1.0", "ruff==0.14.14", "vulture==2.16", "deptry==0.25.1"):
        assert requirement in install
    assert "./aragora-${{ matrix.app }}[${{ matrix.extras }}]" in install
    strict = next(step for step in steps if step["name"] == "Strict mypy")
    assert strict["working-directory"] == "aragora-${{ matrix.app }}"
    assert strict["run"].splitlines() == ["mypy --version", "mypy --strict src"]
    ratchets = next(step["run"] for step in steps if step["name"] == "Ruff and ratchets")
    assert "make readiness-lint-${{ matrix.app }}" in ratchets
    assert "pipefail" in ratchets
    assert "! grep" in ratchets and "SKIP" in ratchets
    tests = next(step for step in steps if step["name"] == "Tests with coverage")
    assert tests["working-directory"] == strict["working-directory"]
    for flag in (
        "--cov=aragora_${{ matrix.app }}",
        "--cov-config=pyproject.toml",
        "--cov-fail-under=",
        "--durations=10",
        "--junitxml=junit.xml",
        "-p randomly",
        "-n 4",
        "--timeout=120",
    ):
        assert flag in tests["run"]
    assert '["fail_under"]' in tests["run"]
    artifact = next(step for step in steps if step.get("uses") == "actions/upload-artifact@v4")
    assert artifact["if"] == "always()"
    assert artifact["with"]["name"] == "junit-${{ matrix.app }}"
    assert artifact["with"]["path"] == "aragora-${{ matrix.app }}/junit.xml"


def test_security_gate_tracks_all_workspace_manifests() -> None:
    workflow = yaml.load(
        (ROOT / ".github/workflows/security-gate.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert {
        "aragora-debate/pyproject.toml",
        "aragora-verify/pyproject.toml",
        "sdk/python/pyproject.toml",
    } <= set(workflow["on"]["pull_request"]["paths"])
    steps = workflow["jobs"]["python-security"]["steps"]
    assert any("uv lock --check" in step.get("run", "") for step in steps)


def test_existing_frontend_hook_is_unchanged() -> None:
    assert _hooks()["tsc-check"] == {
        "id": "tsc-check",
        "name": "TypeScript type check (frontend)",
        "entry": "bash -c 'cd aragora/live && npx tsc --noEmit'",
        "language": "system",
        "pass_filenames": False,
        "files": r"^aragora/live/src/.*\.(ts|tsx)$",
        "stages": ["pre-push"],
    }


@pytest.mark.parametrize("hook_id", HOOK_APPS)
def test_hooks_are_push_only_and_package_scoped(hook_id: str) -> None:
    hook = _hooks()[hook_id]
    assert hook["stages"] == ["pre-push"]
    assert hook["language"] == "system"
    assert hook["pass_filenames"] is False
    assert hook["verbose"] is True  # Pre-commit must display successful SKIP output.
    for app in HOOK_APPS[hook_id]:
        assert re.search(hook["files"], f"aragora-{app}/src/example.py")
    assert not re.search(hook["files"], "aragora/server/example.py")


@pytest.mark.parametrize("hook_id", HOOK_APPS)
def test_hooks_skip_without_tools_or_stdin(hook_id: str) -> None:
    result = subprocess.run(
        shlex.split(_hooks()[hook_id]["entry"]),
        cwd=ROOT,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    for app in HOOK_APPS[hook_id]:
        assert f"SKIP {app}:" in result.stdout


@pytest.mark.parametrize("hook_id", HOOK_APPS)
@pytest.mark.parametrize("tool_exit", [0, 1])
def test_hooks_run_tools_and_propagate_failures(
    hook_id: str, tool_exit: int, tmp_path: Path
) -> None:
    tool = "ruff" if hook_id == "packages-ruff" else "mypy"
    binary = tmp_path / tool
    binary.write_text(
        '#!/bin/sh\nif [ "$1" = "--version" ]; then echo "mypy 2.1.0 (compiled: yes)"; '
        'exit 0; fi\nprintf "%s|%s\\n" "$PWD" "$*" >> "$HOOK_LOG"\nexit "$HOOK_EXIT"\n'
    )
    binary.chmod(0o755)
    log = tmp_path / "calls"
    result = subprocess.run(
        shlex.split(_hooks()[hook_id]["entry"]),
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "HOOK_LOG": str(log),
            "HOOK_EXIT": str(tool_exit),
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == tool_exit, result.stderr
    assert "SKIP" not in result.stdout
    calls = log.read_text().splitlines()
    if tool == "ruff":
        assert calls[0] == f"{ROOT}|check aragora-debate aragora-verify"
        if tool_exit == 0:
            assert calls[1] == f"{ROOT}|format --check aragora-debate aragora-verify"
    else:
        assert calls == [f"{ROOT}/aragora-{HOOK_APPS[hook_id][0]}|--strict src"]


@pytest.mark.parametrize("app", ["debate", "verify"])
def test_mypy_hooks_reject_wrong_version(app: str, tmp_path: Path) -> None:
    binary = tmp_path / "mypy"
    binary.write_text('#!/bin/sh\necho "mypy 2.3.1 (compiled: yes)"\n')
    binary.chmod(0o755)
    result = subprocess.run(
        shlex.split(_hooks()[f"{app}-strict-mypy"]["entry"]),
        cwd=ROOT,
        env={**os.environ, "PATH": f"{tmp_path}:/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert f"{app}: mypy 2.1.0 required" in result.stdout
    assert "SKIP" not in result.stdout
