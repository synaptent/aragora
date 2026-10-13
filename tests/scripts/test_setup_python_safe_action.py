from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml


ACTION_PATH = (
    Path(__file__).resolve().parents[2] / ".github" / "actions" / "setup-python-safe" / "action.yml"
)


def _setup_python_safe_steps() -> list[dict[str, object]]:
    action = yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))
    steps = action.get("runs", {}).get("steps", [])
    if not isinstance(steps, list):
        raise AssertionError("setup-python-safe steps not found")
    return steps


def _setup_python_safe_step(name: str) -> dict[str, object]:
    steps = _setup_python_safe_steps()
    for step in steps:
        if str(step.get("name", "")) == name:
            return step
    raise AssertionError(f"{name} step not found")


def _setup_python_safe_step_run(name: str) -> str:
    return str(_setup_python_safe_step(name).get("run", ""))


def _run_step(
    name: str,
    tmp_path: Path,
    env_overrides: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    github_env = tmp_path / "github-env"
    env = os.environ.copy()
    for key in (
        "AGENT_TOOLSDIRECTORY",
        "RUNNER_TEMP",
        "RUNNER_TOOL_CACHE",
        "PYTHON_CALL_LOG",
        "PYTHON_FAIL_STAGE",
    ):
        env.pop(key, None)
    env["GITHUB_ENV"] = str(github_env)
    env.update(env_overrides or {})
    result = subprocess.run(
        ["bash", "-c", _setup_python_safe_step_run(name)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    github_env_lines = (
        github_env.read_text(encoding="utf-8").splitlines() if github_env.exists() else []
    )
    return result, github_env_lines


def _environment_assignments(lines: list[str]) -> dict[str, str]:
    return dict(line.split("=", 1) for line in lines)


def test_preserves_usable_runner_tool_cache(tmp_path: Path) -> None:
    runner_cache = tmp_path / "runner-tool-cache"
    runner_cache.mkdir()
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()

    result, lines = _run_step(
        "Prepare writable tool cache",
        tmp_path,
        {
            "RUNNER_TOOL_CACHE": str(runner_cache),
            "AGENT_TOOLSDIRECTORY": str(tmp_path / "missing-agent-cache"),
            "RUNNER_TEMP": str(runner_temp),
        },
    )

    assert result.returncode == 0, result.stderr
    assert _environment_assignments(lines) == {
        "AGENT_TOOLSDIRECTORY": str(runner_cache),
        "RUNNER_TOOL_CACHE": str(runner_cache),
    }
    assert not (runner_temp / "hostedtoolcache").exists()


def test_preserves_usable_agent_toolsdirectory_when_runner_cache_is_unusable(
    tmp_path: Path,
) -> None:
    unusable_runner_cache = tmp_path / "runner-cache-file"
    unusable_runner_cache.write_text("not a directory", encoding="utf-8")
    agent_cache = tmp_path / "agent-tool-cache"
    agent_cache.mkdir()
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()

    result, lines = _run_step(
        "Prepare writable tool cache",
        tmp_path,
        {
            "RUNNER_TOOL_CACHE": str(unusable_runner_cache),
            "AGENT_TOOLSDIRECTORY": str(agent_cache),
            "RUNNER_TEMP": str(runner_temp),
        },
    )

    assert result.returncode == 0, result.stderr
    assert _environment_assignments(lines) == {
        "AGENT_TOOLSDIRECTORY": str(agent_cache),
        "RUNNER_TOOL_CACHE": str(agent_cache),
    }
    assert not (runner_temp / "hostedtoolcache").exists()


@pytest.mark.parametrize("cache_state", ["absent", "unusable"])
def test_uses_runner_temp_fallback_when_existing_caches_are_not_usable(
    tmp_path: Path,
    cache_state: str,
) -> None:
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    env = {"RUNNER_TEMP": str(runner_temp)}
    if cache_state == "unusable":
        runner_cache = tmp_path / "runner-cache-file"
        runner_cache.write_text("not a directory", encoding="utf-8")
        agent_cache = tmp_path / "agent-cache-file"
        agent_cache.write_text("not a directory", encoding="utf-8")
        env.update(
            {
                "RUNNER_TOOL_CACHE": str(runner_cache),
                "AGENT_TOOLSDIRECTORY": str(agent_cache),
            }
        )

    result, lines = _run_step("Prepare writable tool cache", tmp_path, env)

    fallback = runner_temp / "hostedtoolcache"
    assert result.returncode == 0, result.stderr
    assert fallback.is_dir()
    assert _environment_assignments(lines) == {
        "AGENT_TOOLSDIRECTORY": str(fallback),
        "RUNNER_TOOL_CACHE": str(fallback),
    }


def test_fails_when_fallback_cache_cannot_be_created(tmp_path: Path) -> None:
    runner_temp = tmp_path / "runner-temp-file"
    runner_temp.write_text("not a directory", encoding="utf-8")

    result, lines = _run_step(
        "Prepare writable tool cache",
        tmp_path,
        {"RUNNER_TEMP": str(runner_temp)},
    )

    assert result.returncode != 0
    assert lines == []


def test_preserves_self_hosted_and_setup_failure_fallback_ordering() -> None:
    steps = _setup_python_safe_steps()
    names = [str(step.get("name", "")) for step in steps]
    system_index = names.index("Use matching system Python on self-hosted runners")
    setup_index = names.index("Set up Python ${{ inputs.python-version }}")
    fallback_index = names.index("Fallback to system Python")
    assert system_index < setup_index < fallback_index

    setup_step = steps[setup_index]
    assert setup_step.get("if") == "steps.system-python.outputs.found != 'true'"
    assert setup_step.get("continue-on-error") is True
    assert (
        steps[fallback_index].get("if") == "steps.system-python.outputs.found != 'true' && "
        "steps.setup-python.outcome == 'failure'"
    )


def test_prefers_unpacked_requested_python_before_system_fallback() -> None:
    run = _setup_python_safe_step_run("Fallback to system Python")
    unpacked_index = run.index('DISCOVERED_PY="$(find "${RUNNER_TEMP}"')
    search_index = run.index("for cmd in python${{ inputs.python-version }} python3 python; do")
    assert unpacked_index < search_index
    assert "Found unpacked interpreter in RUNNER_TEMP" in run
    assert "Found $cmd:" in run


def _fake_python(tmp_path: Path) -> tuple[Path, Path]:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    call_log = tmp_path / "python-calls"
    python = fake_bin / "python"
    python.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "${PYTHON_CALL_LOG}"
case "${PYTHON_FAIL_STAGE:-}" in
  startup)
    [[ "${1:-}" == "--version" ]] && exit 31
    ;;
  ssl)
    [[ "${1:-}" == "-c" ]] && exit 32
    ;;
  pip)
    [[ "${1:-}" == "-m" && "${2:-}" == "pip" ]] && exit 33
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    python.chmod(0o755)
    return fake_bin, call_log


def test_runtime_verification_is_non_optional(tmp_path: Path) -> None:
    step = _setup_python_safe_step("Verify Python toolchain")
    run = str(step.get("run", ""))
    assert step.get("continue-on-error", False) is not True
    assert "set -euo pipefail" in run
    assert "|| true" not in run

    fake_bin, call_log = _fake_python(tmp_path)
    result, _ = _run_step(
        "Verify Python toolchain",
        tmp_path,
        {
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "PYTHON_CALL_LOG": str(call_log),
        },
    )

    assert result.returncode == 0, result.stderr
    assert call_log.read_text(encoding="utf-8").splitlines() == [
        "--version",
        "-c import ssl",
        "-m pip --version",
    ]


@pytest.mark.parametrize(
    ("failure_stage", "expected_returncode"),
    [("startup", 31), ("ssl", 32), ("pip", 33)],
)
def test_runtime_verification_fails_closed(
    tmp_path: Path,
    failure_stage: str,
    expected_returncode: int,
) -> None:
    fake_bin, call_log = _fake_python(tmp_path)

    result, _ = _run_step(
        "Verify Python toolchain",
        tmp_path,
        {
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "PYTHON_CALL_LOG": str(call_log),
            "PYTHON_FAIL_STAGE": failure_stage,
        },
    )

    assert result.returncode == expected_returncode
