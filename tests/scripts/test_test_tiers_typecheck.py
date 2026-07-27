"""Regression tests for the typecheck tier shell helper."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_TIERS = REPO_ROOT / "scripts" / "test_tiers.sh"


def _run_typecheck_with_fake_python(
    tmp_path: Path, fake_python_body: str
) -> subprocess.CompletedProcess[str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        '[[ "$*" == *scripts/ci/mypy_with_baseline.py* ]] || exit 99\n'
        f"{fake_python_body}\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    env = os.environ.copy()
    env.pop("TYPECHECK_PYTHON", None)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    return subprocess.run(
        ["bash", str(TEST_TIERS), "typecheck"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_typecheck_tier_propagates_new_error_status(tmp_path: Path) -> None:
    proc = _run_typecheck_with_fake_python(tmp_path, "exit 1")

    output = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "=== Type check FAILED ===" in output


def test_typecheck_tier_propagates_toolchain_failure_status(tmp_path: Path) -> None:
    proc = _run_typecheck_with_fake_python(tmp_path, "exit 2")

    output = proc.stdout + proc.stderr
    assert proc.returncode == 2
    assert "=== Type check FAILED ===" in output


def test_typecheck_tier_passes_when_baseline_helper_exits_cleanly(tmp_path: Path) -> None:
    proc = _run_typecheck_with_fake_python(tmp_path, "exit 0")

    output = proc.stdout + proc.stderr
    assert proc.returncode == 0
    assert "=== Type check passed (no new errors) ===" in output


def test_typecheck_tier_ignores_inherited_python_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TYPECHECK_PYTHON", "/missing/inherited/python")

    proc = _run_typecheck_with_fake_python(tmp_path, "exit 0")

    assert proc.returncode == 0
