"""Keep standalone package CI and local pre-push gates effective."""

from __future__ import annotations

import os
import re
import shlex
import shutil
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
    # Test plugins come from each package's own dev extra, so CI sees what a
    # fresh install sees (debate declares pytest-asyncio; verify needs none).
    assert "pytest-asyncio" not in install
    assert "./aragora-${{ matrix.app }}[${{ matrix.extras }}]" in install
    # The contract-drift authority checker rejects `${{ }}` in `working-directory`.
    assert workflow["jobs"]["packages"]["env"]["APP"] == "${{ matrix.app }}"
    strict = next(step for step in steps if step["name"] == "Strict mypy")
    assert "working-directory" not in strict
    assert strict["run"].splitlines()[0] == 'cd "aragora-$APP"'
    assert strict["run"].splitlines()[1:] == ["mypy --version", "mypy --strict src"]
    ratchets = next(step["run"] for step in steps if step["name"] == "Ruff and ratchets")
    assert "make readiness-lint-${{ matrix.app }}" in ratchets
    assert "pipefail" in ratchets
    assert "! grep" in ratchets and "SKIP" in ratchets
    tests = next(step for step in steps if step["name"] == "Tests with coverage")
    assert "working-directory" not in tests
    assert tests["run"].splitlines()[0] == strict["run"].splitlines()[0]
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
    artifact = next(
        step
        for step in steps
        if re.fullmatch(r"actions/upload-artifact@[0-9a-f]{40}", step.get("uses", ""))
    )
    assert artifact["if"] == "always()"
    assert artifact["with"]["name"] == "junit-${{ matrix.app }}"
    assert artifact["with"]["path"] == "aragora-${{ matrix.app }}/junit.xml"


def test_workflow_pins_every_remote_action_to_a_commit() -> None:
    text = (ROOT / ".github/workflows/packages-ci.yml").read_text()
    # YAML parsing drops comments, so the version comment is checked on the raw line.
    uses = re.findall(r"(?m)^\s*(?:-\s+)?uses:\s*(.+?)\s*$", text)
    remote = [use for use in uses if not use.startswith("./")]
    assert {use.split("@", 1)[0] for use in remote} == {
        "actions/checkout",
        "actions/upload-artifact",
    }
    for use in remote:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+", use), use
    assert re.search(r"(?m)uses: actions/upload-artifact@[0-9a-f]{40} # v4\.\d+\.\d+$", text)
    assert not re.search(r"upload-artifact@v\d", text)


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
        "entry": "bash scripts/tsc_check_hook.sh",
        "language": "system",
        "pass_filenames": False,
        "files": r"^aragora/live/src/.*\.(ts|tsx)$",
        "stages": ["pre-push"],
    }


TSC_HOOK = ROOT / "scripts/tsc_check_hook.sh"


def test_tsc_hook_guards_npx_before_the_unchanged_check() -> None:
    lines = [line.strip() for line in TSC_HOOK.read_text().splitlines() if line.strip()]
    assert lines[-2:] == ['cd "$live"', "exec npx tsc --noEmit"]
    guard = lines.index("if ! command -v npx >/dev/null 2>&1; then")
    assert lines.index('if [ ! -d "$live/node_modules" ]; then') < guard < len(lines) - 2


def _tsc_sandbox(tmp_path: Path, *, node_modules: bool, npx: bool) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts/tsc_check_hook.sh").write_bytes(TSC_HOOK.read_bytes())
    (repo / "aragora/live").mkdir(parents=True)
    if node_modules:
        (repo / "aragora/live/node_modules").mkdir()
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env, timeout=30)
    # Only git (and the fake npx when wanted) on PATH, whatever the host has installed.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git = shutil.which("git")
    assert git is not None
    (bin_dir / "git").symlink_to(git)
    if npx:
        (bin_dir / "npx").write_text(
            '#!/bin/sh\nprintf "%s|%s\\n" "$PWD" "$*" >> "$HOOK_LOG"\nexit "$HOOK_EXIT"\n'
        )
        (bin_dir / "npx").chmod(0o755)
    env.update(PATH=str(bin_dir), HOOK_LOG=str(tmp_path / "calls"), HOOK_EXIT="0")
    env.pop("ARAGORA_TSC_CHECK_STRICT", None)
    return repo, env


def _run_tsc_hook(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash is not None
    return subprocess.run(
        [bash, "scripts/tsc_check_hook.sh"],
        cwd=repo,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize(
    ("node_modules", "reason"),
    [(False, "aragora/live/node_modules is absent"), (True, "npx is not on PATH")],
    ids=["no-node-modules", "no-npx"],
)
@pytest.mark.parametrize("strict", [False, True], ids=["default", "strict"])
def test_tsc_hook_skips_loudly_or_fails_strict_without_its_tools(
    tmp_path: Path, node_modules: bool, reason: str, strict: bool
) -> None:
    repo, env = _tsc_sandbox(tmp_path, node_modules=node_modules, npx=False)
    if strict:
        env["ARAGORA_TSC_CHECK_STRICT"] = "1"
    result = _run_tsc_hook(repo, env)
    assert "not found" not in result.stderr
    assert reason in result.stdout + result.stderr
    if strict:
        assert result.returncode == 1, result.stdout + result.stderr
        assert "SKIPPED" not in result.stdout
        assert "ARAGORA_TSC_CHECK_STRICT=1, failing" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith("tsc-check: SKIPPED.")
        assert "authoritative" in result.stdout
        if node_modules:
            assert "NOT type-checked" in result.stdout
    assert not (tmp_path / "calls").exists()


@pytest.mark.parametrize("tool_exit", [0, 2])
@pytest.mark.parametrize("strict", [False, True], ids=["default", "strict"])
def test_tsc_hook_runs_tsc_when_npx_is_present(
    tmp_path: Path, tool_exit: int, strict: bool
) -> None:
    repo, env = _tsc_sandbox(tmp_path, node_modules=True, npx=True)
    env["HOOK_EXIT"] = str(tool_exit)
    if strict:
        env["ARAGORA_TSC_CHECK_STRICT"] = "1"
    result = _run_tsc_hook(repo, env)
    assert result.returncode == tool_exit, result.stdout + result.stderr
    assert "SKIP" not in result.stdout
    live = (repo / "aragora/live").resolve()
    assert (tmp_path / "calls").read_text().splitlines() == [f"{live}|tsc --noEmit"]


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
    # Answer the version the real pinned tool prints, so a hook's version check
    # sees this stand-in as that tool.
    version = {"ruff": "ruff 0.14.14", "mypy": "mypy 2.1.0 (compiled: yes)"}[tool]
    binary = tmp_path / tool
    binary.write_text(
        f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo "{version}"; '
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
