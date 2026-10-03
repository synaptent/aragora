"""Tests for scripts/pristine_main_health.py (epic #9039, issue #9043)."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import signal
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pristine_main_health.py"
_LOCKED_DEV_RUN = ["uv", "run", "--locked", "--extra", "dev", "--extra", "test"]


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("pristine_main_health_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _install_fake_worktree(mod, monkeypatch, sha="deadbeef" * 5):
    monkeypatch.setattr(mod, "refresh_pristine_worktree", lambda repo, pristine: sha)
    monkeypatch.setattr(mod, "_check_required_toolchain", lambda pristine: None)
    monkeypatch.setattr(
        mod,
        "_run_suite",
        lambda cmd, *, cwd, timeout: mod._run(cmd, cwd=cwd, timeout=timeout),
    )
    return sha


class _Proc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _is_runtime_probe(cmd: list[str]) -> bool:
    return cmd == [*_LOCKED_DEV_RUN, "python", "-c", "import pytest"]


def test_existing_pristine_without_owner_marker_refuses_destructive_refresh(
    mod, monkeypatch, tmp_path
):
    repo = tmp_path / "repo"
    repo.mkdir()
    pristine = tmp_path / "other-checkout"
    pristine.mkdir()
    (pristine / ".git").mkdir()
    commands: list[list[str]] = []

    def fake_run(cmd, *, cwd, timeout):
        commands.append(cmd)
        if cmd[:3] == ["git", "fetch", "origin"]:
            return _Proc(0)
        raise AssertionError(f"unexpected command after missing marker: {cmd}")

    monkeypatch.setattr(mod, "_run", fake_run)

    with pytest.raises(SystemExit) as exc:
        mod.refresh_pristine_worktree(repo, pristine)

    assert "unmarked --pristine-dir" in str(exc.value)
    assert not any(cmd[:3] == ["git", "reset", "--hard"] for cmd in commands)
    assert not any(cmd[:2] == ["git", "clean"] for cmd in commands)


def test_existing_marked_registered_pristine_refreshes(mod, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    pristine = tmp_path / "pristine"
    pristine.mkdir()
    (pristine / ".git").mkdir()
    mod._write_owner_marker(repo, pristine)
    commands: list[list[str]] = []

    def fake_run(cmd, *, cwd, timeout):
        commands.append(cmd)
        if cmd[:3] == ["git", "fetch", "origin"]:
            return _Proc(0)
        if cmd == ["git", "worktree", "list", "--porcelain"]:
            return _Proc(0, f"worktree {pristine}\nHEAD cafebabe\n")
        if cmd[0:3] == ["git", "checkout", "--detach"]:
            return _Proc(0)
        if cmd[:3] == ["git", "reset", "--hard"]:
            return _Proc(0)
        if cmd[:3] == ["git", "clean", "-fdx"]:
            return _Proc(0)
        if cmd == ["git", "rev-parse", "HEAD"]:
            return _Proc(0, "cafebabe\n")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(mod, "_run", fake_run)

    assert mod.refresh_pristine_worktree(repo, pristine) == "cafebabe"
    assert ["git", "reset", "--hard", "origin/main"] in commands
    assert ["git", "clean", "-fdx", "--quiet"] in commands


def test_green_run_writes_ledger_and_no_halt(mod, monkeypatch, tmp_path):
    _install_fake_worktree(mod, monkeypatch)
    monkeypatch.setattr(mod, "_run", lambda cmd, *, cwd, timeout: _Proc(0, "ok"))
    halt = tmp_path / "halt.json"
    rc = mod.main(
        [
            "--repo-root",
            str(tmp_path),
            "--pristine-dir",
            str(tmp_path / "pristine"),
            "--halt-file",
            str(halt),
            "--suite",
            "required",
        ]
    )
    assert rc == 0
    assert not halt.exists()
    from aragora.nomic.throughput import ThroughputLedger

    (record,) = ThroughputLedger(tmp_path).records()
    assert record.kind == "note"
    assert record.data["event"] == "pristine_main_health"
    assert record.data["green"] is True
    assert record.data["status"] == "green"


def test_red_run_writes_merge_executor_compatible_halt_marker(mod, monkeypatch, tmp_path):
    sha = _install_fake_worktree(mod, monkeypatch)

    def fake_run(cmd, *, cwd, timeout):
        if _is_runtime_probe(cmd):
            return _Proc(0)
        return _Proc(
            1,
            "FAILED tests/x.py::t - boom",
            "collection warning from stderr",
        )

    monkeypatch.setattr(mod, "_run", fake_run)
    halt = tmp_path / "halt.json"
    rc = mod.main(
        [
            "--repo-root",
            str(tmp_path),
            "--pristine-dir",
            str(tmp_path / "pristine"),
            "--halt-file",
            str(halt),
            "--suite",
            "required",
        ]
    )
    assert rc == 1
    marker = json.loads(halt.read_text())
    assert marker["reason"] == "main_red"  # the field merge_executor keys on
    assert sha[:12] in marker["details"][0]
    assert "FAILED tests/x.py::t - boom" in marker["details"][1]
    assert "collection warning from stderr" in marker["details"][1]
    assert "human deletes" in marker["re_arm"]
    from aragora.nomic.throughput import ThroughputLedger

    (record,) = ThroughputLedger(tmp_path).records()
    assert record.data["green"] is False
    assert record.data["status"] == "main_red"
    assert record.data["failures"]


def test_no_halt_file_flag_reports_only(mod, monkeypatch, tmp_path):
    _install_fake_worktree(mod, monkeypatch)

    def fake_run(cmd, *, cwd, timeout):
        return _Proc(0) if _is_runtime_probe(cmd) else _Proc(2)

    monkeypatch.setattr(mod, "_run", fake_run)
    halt = tmp_path / "halt.json"
    rc = mod.main(
        [
            "--repo-root",
            str(tmp_path),
            "--pristine-dir",
            str(tmp_path / "pristine"),
            "--halt-file",
            str(halt),
            "--suite",
            "required",
            "--no-halt-file",
        ]
    )
    assert rc == 1
    assert not halt.exists()


def test_missing_pytest_records_infra_error_without_touching_halt(
    mod, monkeypatch, tmp_path, capsys
):
    pristine = tmp_path / "pristine"
    events: list[tuple[str, Path]] = []

    def fake_refresh(repo, target):
        events.append(("refresh", target))
        target.mkdir()
        return "deadbeef" * 5

    monkeypatch.setattr(mod, "refresh_pristine_worktree", fake_refresh)

    def fake_run(cmd, *, cwd, timeout):
        assert _is_runtime_probe(cmd)
        events.append(("runtime", cwd))
        return _Proc(
            1,
            "probe stdout",
            f"{sys.executable}: No module named pytest",
        )

    monkeypatch.setattr(mod, "_run", fake_run)
    halt = tmp_path / "halt.json"
    original_halt = '{"reason": "existing-incident"}\n'
    halt.write_text(original_halt)

    rc = mod.main(
        [
            "--repo-root",
            str(tmp_path),
            "--pristine-dir",
            str(pristine),
            "--halt-file",
            str(halt),
            "--suite",
            "full",
        ]
    )

    assert rc == mod.INFRA_ERROR_EXIT
    assert halt.read_text() == original_halt
    stderr = capsys.readouterr().err
    assert "INFRA_ERROR" in stderr
    assert "probe stdout" in stderr
    assert "No module named pytest" in stderr
    assert "halt marker NOT written" in stderr

    from aragora.nomic.throughput import ThroughputLedger

    (record,) = ThroughputLedger(tmp_path).records()
    assert record.data["green"] is False
    assert record.data["status"] == "infra_error"
    assert record.data["failures"] == []
    assert "probe stdout" in record.data["infra_errors"][0]
    assert "No module named pytest" in record.data["infra_errors"][0]
    assert events == [("refresh", pristine), ("runtime", pristine)]


def test_locked_mypy_failure_is_infra_error_without_touching_halt(
    mod, monkeypatch, tmp_path, capsys
):
    repo = tmp_path / "repo"
    repo.mkdir()
    pristine = tmp_path / "pristine"
    pristine.mkdir()
    monkeypatch.setattr(mod, "_check_test_runtime", lambda repo: None)
    monkeypatch.setattr(mod, "refresh_pristine_worktree", lambda repo, pristine: "deadbeef" * 5)
    monkeypatch.setattr(
        mod,
        "_run",
        lambda cmd, *, cwd, timeout: _Proc(
            2,
            "",
            "The lockfile at uv.lock needs to be updated",
        ),
    )

    halt = tmp_path / "halt.json"
    original_halt = b'{"reason": "existing-main-red"}\n'
    halt.write_bytes(original_halt)

    rc = mod.main(
        [
            "--repo-root",
            str(repo),
            "--pristine-dir",
            str(pristine),
            "--halt-file",
            str(halt),
            "--suite",
            "required",
        ]
    )

    assert rc == mod.INFRA_ERROR_EXIT
    assert halt.read_bytes() == original_halt
    stderr = capsys.readouterr().err
    assert "INFRA_ERROR" in stderr
    assert "uv run --locked --extra dev --extra test mypy --version" in stderr
    assert "lockfile at uv.lock needs to be updated" in stderr

    from aragora.nomic.throughput import ThroughputLedger

    (record,) = ThroughputLedger(repo).records()
    assert record.data["status"] == "infra_error"
    assert "lockfile at uv.lock needs to be updated" in record.data["infra_errors"][0]


def test_infra_failure_signature_classification(mod):
    """Runner-environment breakage is infra; first-party import failure is red."""
    # A tool missing from PATH (make or shell reporting it) is infra.
    assert (
        mod._infra_failure_signature(_Proc(2, "make: mypy: No such file or directory")) is not None
    )
    assert mod._infra_failure_signature(_Proc(127, "zsh: ruff: command not found")) is not None
    assert (
        mod._infra_failure_signature(
            _Proc(
                2,
                "",
                "error: Failed to spawn: `ruff`\n  Caused by: No such file or directory (os error 2)",
            )
        )
        is not None
    )
    # A missing THIRD-PARTY module in the runner interpreter is infra.
    proc = _Proc(1, "")
    proc.stderr = "ModuleNotFoundError: No module named 'jsonschema'"
    assert mod._infra_failure_signature(proc) is not None
    # A missing FIRST-PARTY module IS the red this script exists to catch.
    proc = _Proc(1, "")
    proc.stderr = "ModuleNotFoundError: No module named 'aragora.debate.orchestrator'"
    assert mod._infra_failure_signature(proc) is None
    # Ordinary test failures are red.
    assert mod._infra_failure_signature(_Proc(1, "FAILED tests/x.py::t - boom")) is None


def test_suite_tool_missing_is_infra_error_without_touching_halt(
    mod, monkeypatch, tmp_path, capsys
):
    """`make ci-required` failing because a tool is absent must never halt merges."""
    _install_fake_worktree(mod, monkeypatch)
    monkeypatch.setattr(mod, "_check_test_runtime", lambda repo: None)
    monkeypatch.setattr(mod, "_check_required_toolchain", lambda pristine: None)
    monkeypatch.setattr(
        mod,
        "_run_suite",
        lambda cmd, *, cwd, timeout: _Proc(
            2,
            "",
            "error: Failed to spawn: `ruff`\n  Caused by: No such file or directory (os error 2)",
        ),
    )

    halt = tmp_path / "halt.json"
    rc = mod.main(
        [
            "--repo-root",
            str(tmp_path),
            "--pristine-dir",
            str(tmp_path / "pristine"),
            "--halt-file",
            str(halt),
            "--suite",
            "required",
        ]
    )

    assert rc == mod.INFRA_ERROR_EXIT
    assert not halt.exists()
    assert "Failed to spawn" in capsys.readouterr().err

    from aragora.nomic.throughput import ThroughputLedger

    (record,) = ThroughputLedger(tmp_path).records()
    assert record.data["status"] == "infra_error"
    assert "runner environment failure" in record.data["infra_errors"][0]


def test_locked_mypy_command_ignores_unrelated_path_mypy(mod, monkeypatch, tmp_path):
    pristine = tmp_path / "pristine"
    pristine.mkdir()
    commands: list[list[str]] = []

    def fake_run(cmd, *, cwd, timeout):
        commands.append(cmd)
        return _Proc(0, "mypy 2.1.0 (compiled: yes)")

    monkeypatch.setattr(mod, "_run", fake_run)

    assert mod._check_required_toolchain(pristine) is None
    assert commands == [[*_LOCKED_DEV_RUN, "mypy", "--version"]]


def test_locked_command_replaces_caller_python_with_environment_python(mod):
    command = mod._locked_dev_command([sys.executable, "scripts/check.py", "--flag"])

    assert command == [*_LOCKED_DEV_RUN, "python", "scripts/check.py", "--flag"]


def test_suite_launch_error_is_infra_error_and_never_writes_halt(
    mod, monkeypatch, tmp_path, capsys
):
    _install_fake_worktree(mod, monkeypatch)

    def fake_run(cmd, *, cwd, timeout):
        if _is_runtime_probe(cmd):
            return _Proc(0)
        raise OSError("runner executable disappeared")

    monkeypatch.setattr(mod, "_run", fake_run)
    halt = tmp_path / "halt.json"

    rc = mod.main(
        [
            "--repo-root",
            str(tmp_path),
            "--pristine-dir",
            str(tmp_path / "pristine"),
            "--halt-file",
            str(halt),
            "--suite",
            "required",
        ]
    )

    assert rc == mod.INFRA_ERROR_EXIT
    assert not halt.exists()
    assert "runner executable disappeared" in capsys.readouterr().err

    from aragora.nomic.throughput import ThroughputLedger

    (record,) = ThroughputLedger(tmp_path).records()
    assert record.data["status"] == "infra_error"
    assert "runner executable disappeared" in record.data["infra_errors"][0]


def test_timeout_kills_sigterm_ignoring_group_and_never_writes_halt(
    mod, monkeypatch, tmp_path, capsys
):
    repo = tmp_path / "repo"
    repo.mkdir()
    pristine = tmp_path / "pristine"
    pristine.mkdir()
    monkeypatch.setattr(mod, "_check_test_runtime", lambda repo: None)
    monkeypatch.setattr(mod, "_check_required_toolchain", lambda pristine: None)
    monkeypatch.setattr(mod, "refresh_pristine_worktree", lambda repo, pristine: "deadbeef" * 5)
    monkeypatch.setattr(mod, "SUITE_TERMINATION_GRACE_SECONDS", 0.2)
    child = [
        sys.executable,
        "-c",
        (
            "import os, signal, sys, time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "print(f'child-pid={os.getpid()}', flush=True); "
            "print('partial-stderr', file=sys.stderr, flush=True); "
            "time.sleep(60)"
        ),
    ]
    monkeypatch.setitem(mod.SUITES, "required", [child])
    monkeypatch.setattr(mod, "_locked_dev_command", lambda cmd: cmd)

    halt = tmp_path / "halt.json"
    original_halt = b'{"reason": "existing-main-red"}\n'
    halt.write_bytes(original_halt)

    rc = mod.main(
        [
            "--repo-root",
            str(repo),
            "--pristine-dir",
            str(pristine),
            "--halt-file",
            str(halt),
            "--suite",
            "required",
            "--timeout-minutes",
            "0.01",
        ]
    )

    assert rc == mod.INFRA_ERROR_EXIT
    assert halt.read_bytes() == original_halt
    stderr = capsys.readouterr().err
    assert "TIMEOUT after 0.01m" in stderr
    assert "child-pid=" in stderr
    assert "partial-stderr" in stderr
    assert "sent SIGTERM" in stderr
    assert "sent SIGKILL" in stderr

    child_pids = re.findall(r"^child-pid=(\d+)$", stderr, re.MULTILINE)
    assert len(child_pids) == 1
    child_pid = int(child_pids[0])
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)

    from aragora.nomic.throughput import ThroughputLedger

    (record,) = ThroughputLedger(repo).records()
    assert record.data["status"] == "infra_error"
    assert record.data["failures"] == []
    assert "sent SIGKILL" in record.data["infra_errors"][0]


def test_externally_signaled_suite_is_infra_error_without_touching_halt(
    mod, monkeypatch, tmp_path, capsys
):
    _install_fake_worktree(mod, monkeypatch)

    def fake_run(cmd, *, cwd, timeout):
        if _is_runtime_probe(cmd):
            return _Proc(0)
        return _Proc(-signal.SIGTERM, "partial-stdout", "partial-stderr")

    monkeypatch.setattr(mod, "_run", fake_run)
    halt = tmp_path / "halt.json"
    original_halt = b'{"reason": "existing-main-red"}\n'
    halt.write_bytes(original_halt)

    rc = mod.main(
        [
            "--repo-root",
            str(tmp_path),
            "--pristine-dir",
            str(tmp_path / "pristine"),
            "--halt-file",
            str(halt),
            "--suite",
            "required",
        ]
    )

    assert rc == mod.INFRA_ERROR_EXIT
    assert halt.read_bytes() == original_halt
    stderr = capsys.readouterr().err
    assert "suite terminated by signal" in stderr
    assert "partial-stdout" in stderr
    assert "partial-stderr" in stderr


def test_failure_evidence_tails_stdout_and_stderr(mod):
    stdout = "\n".join(f"stdout-{index}" for index in range(20))
    stderr = "\n".join(f"stderr-{index}" for index in range(20))

    evidence = mod._format_stream_evidence(stdout=stdout, stderr=stderr)

    assert "stdout-4" not in evidence
    assert "stderr-4" not in evidence
    assert "stdout-5" in evidence
    assert "stderr-5" in evidence
    assert "stdout-19" in evidence
    assert "stderr-19" in evidence


def test_failure_evidence_caps_single_long_line(mod):
    tail = mod._bounded_tail("x" * (mod.EVIDENCE_TAIL_CHARS + 100))

    assert tail == "x" * mod.EVIDENCE_TAIL_CHARS


def test_full_suite_ignores_known_broken_collection(mod):
    (full_cmd,) = mod.SUITES["full"]
    assert "--ignore=tests/connectors" in full_cmd


def test_required_suite_mirrors_ci_with_baseline_mypy_not_make(mod):
    """CI parity (issue #9045): the required lane mirrors `make ci-required`'s
    steps but swaps raw full-codebase mypy (frozen ~1.9k-error debt, never
    green) for the shrink-only baseline checker. `make ci-required` itself
    stays the strict developer contract and is NOT invoked."""
    commands = mod.SUITES["required"]
    flattened = [" ".join(cmd) for cmd in commands]

    assert not any(cmd[0] == "make" for cmd in commands)
    # No raw mypy invocation anywhere in the lane.
    assert not any(Path(cmd[0]).name == "mypy" for cmd in commands)

    (mypy_step,) = [line for line in flattened if "check_mypy_baseline.py" in line]
    assert "--baseline" in mypy_step
    assert "mypy_full_baseline.json" in mypy_step

    # The other ci-required steps are preserved as-is.
    assert any(cmd[:2] == ["ruff", "check"] for cmd in commands)
    for step in (
        "check_version_alignment.py",
        "check_sdk_parity.py",
        "check_sdk_namespace_parity.py",
        "check_cross_sdk_parity.py",
        "generate_openapi.py",
        "verify_sdk_contracts.py",
        "validate_openapi_routes.py",
    ):
        assert any(step in line for line in flattened), f"missing ci-required step: {step}"


def test_default_suite_is_required(mod, monkeypatch, tmp_path):
    """The nightly full suite TIMEOUTs every run (issue #9045); the default
    lane must be the one that can actually produce a verdict."""
    _install_fake_worktree(mod, monkeypatch)
    monkeypatch.setattr(mod, "_run", lambda cmd, *, cwd, timeout: _Proc(0, "ok"))
    rc = mod.main(
        [
            "--repo-root",
            str(tmp_path),
            "--pristine-dir",
            str(tmp_path / "pristine"),
            "--halt-file",
            str(tmp_path / "halt.json"),
        ]
    )
    assert rc == 0
    from aragora.nomic.throughput import ThroughputLedger

    (record,) = ThroughputLedger(tmp_path).records()
    assert record.data["suite"] == "required"


def test_mypy_baseline_infra_output_is_infra_not_red(mod):
    """A checker that cannot produce a verdict is inconclusive, never main_red."""
    proc = _Proc(2, "", "MYPY_BASELINE_INFRA: mypy missing from PATH")
    assert mod._infra_failure_signature(proc) is not None
    # But a genuine baseline regression IS main_red.
    proc = _Proc(1, "FAIL: full-codebase mypy errors grew: 1872 > baseline 1869 (+3)", "")
    assert mod._infra_failure_signature(proc) is None


def test_mypy_baseline_infra_in_suite_never_writes_halt(mod, monkeypatch, tmp_path, capsys):
    _install_fake_worktree(mod, monkeypatch)
    monkeypatch.setattr(mod, "_check_test_runtime", lambda repo: None)

    def fake_suite(cmd, *, cwd, timeout):
        if "check_mypy_baseline.py" in " ".join(cmd):
            return _Proc(2, "", "MYPY_BASELINE_INFRA: baseline file missing: x.json")
        return _Proc(0, "ok")

    monkeypatch.setattr(mod, "_run_suite", fake_suite)
    halt = tmp_path / "halt.json"
    rc = mod.main(
        [
            "--repo-root",
            str(tmp_path),
            "--pristine-dir",
            str(tmp_path / "pristine"),
            "--halt-file",
            str(halt),
            "--suite",
            "required",
        ]
    )

    assert rc == mod.INFRA_ERROR_EXIT
    assert not halt.exists()
    assert "MYPY_BASELINE_INFRA" in capsys.readouterr().err

    from aragora.nomic.throughput import ThroughputLedger

    (record,) = ThroughputLedger(tmp_path).records()
    assert record.data["status"] == "infra_error"
