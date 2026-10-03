"""Tests for scripts/check_mypy_baseline.py (issue #9045).

Shrink-only ratchet over the frozen full-codebase mypy debt: fail only when
the live error count EXCEEDS the recorded baseline, report shrink when below,
never rewrite the baseline automatically.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_mypy_baseline.py"


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("check_mypy_baseline_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_fake_mypy(bin_dir: Path, *, stdout: str, exit_code: int) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    executable = bin_dir / "mypy"
    executable.write_text(
        f"#!/bin/sh\ncat <<'EOF'\n{stdout}\nEOF\nexit {exit_code}\n", encoding="utf-8"
    )
    executable.chmod(0o755)
    return executable


def _write_baseline(path: Path, error_count: int = 1869) -> None:
    path.write_text(
        json.dumps({"command": "mypy aragora/", "error_count": error_count, "file_count": 505}),
        encoding="utf-8",
    )


def _args(baseline: Path, mypy: Path, tmp_path: Path) -> list[str]:
    return [
        "--baseline",
        str(baseline),
        "--mypy-bin",
        str(mypy),
        "--root",
        str(tmp_path),
    ]


def test_count_at_baseline_passes(mod, tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, 1869)
    mypy = _write_fake_mypy(
        tmp_path / "bin",
        stdout="aragora/x.py:1: error: boom  [assignment]\nFound 1869 errors in 505 files (checked 4287 source files)",
        exit_code=1,
    )

    assert mod.main(_args(baseline, mypy, tmp_path)) == 0
    assert "at baseline (1869)" in capsys.readouterr().out


def test_count_above_baseline_fails_with_delta(mod, tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, 1869)
    mypy = _write_fake_mypy(
        tmp_path / "bin",
        stdout="aragora/x.py:1: error: fresh regression  [assignment]\nFound 1872 errors in 506 files (checked 4287 source files)",
        exit_code=1,
    )

    assert mod.main(_args(baseline, mypy, tmp_path)) == 1
    err = capsys.readouterr().err
    assert "1872 > baseline 1869" in err
    assert "+3" in err
    assert "fresh regression" in err  # bounded evidence tail includes real errors


def test_count_below_baseline_passes_and_reports_shrink(mod, tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, 1869)
    mypy = _write_fake_mypy(
        tmp_path / "bin",
        stdout="Found 1800 errors in 490 files (checked 4287 source files)",
        exit_code=1,
    )

    assert mod.main(_args(baseline, mypy, tmp_path)) == 0
    out = capsys.readouterr().out
    assert "shrink" in out
    assert "69 below" in out
    # Shrink-only: the baseline file itself is never rewritten.
    assert json.loads(baseline.read_text())["error_count"] == 1869


def test_clean_mypy_success_passes(mod, tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, 10)
    mypy = _write_fake_mypy(
        tmp_path / "bin",
        stdout="Success: no issues found in 4287 source files",
        exit_code=0,
    )

    assert mod.main(_args(baseline, mypy, tmp_path)) == 0
    assert "10 below" in capsys.readouterr().out


def test_mypy_fatal_exit_is_infra(mod, tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, 1869)
    mypy = _write_fake_mypy(
        tmp_path / "bin",
        stdout="mypy: error: invalid syntax in config",
        exit_code=2,
    )

    assert mod.main(_args(baseline, mypy, tmp_path)) == mod.INFRA_EXIT
    err = capsys.readouterr().err
    assert err.startswith(mod.INFRA_PREFIX)
    assert "exited 2" in err


def test_unparsable_mypy_output_is_infra(mod, tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, 1869)
    mypy = _write_fake_mypy(tmp_path / "bin", stdout="no summary line here", exit_code=1)

    assert mod.main(_args(baseline, mypy, tmp_path)) == mod.INFRA_EXIT
    err = capsys.readouterr().err
    assert err.startswith(mod.INFRA_PREFIX)
    assert "could not parse" in err


def test_mypy_missing_from_path_is_infra(mod, tmp_path, monkeypatch, capsys):
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, 1869)
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))

    assert mod.main(["--baseline", str(baseline), "--root", str(tmp_path)]) == mod.INFRA_EXIT
    err = capsys.readouterr().err
    assert err.startswith(mod.INFRA_PREFIX)
    assert "missing from PATH" in err


def test_missing_baseline_file_is_infra(mod, tmp_path, capsys):
    mypy = _write_fake_mypy(
        tmp_path / "bin",
        stdout="Found 1 error in 1 file (checked 1 source file)",
        exit_code=1,
    )

    rc = mod.main(_args(tmp_path / "absent.json", mypy, tmp_path))

    assert rc == mod.INFRA_EXIT
    err = capsys.readouterr().err
    assert err.startswith(mod.INFRA_PREFIX)
    assert "baseline file missing" in err


def test_update_baseline_writes_measured_count(mod, tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    mypy = _write_fake_mypy(
        tmp_path / "bin",
        stdout="Found 1500 errors in 400 files (checked 4287 source files)",
        exit_code=1,
    )

    rc = mod.main([*_args(baseline, mypy, tmp_path), "--update-baseline"])

    assert rc == 0
    data = json.loads(baseline.read_text())
    assert data["error_count"] == 1500
    assert data["file_count"] == 400
    assert "baseline updated" in capsys.readouterr().out


def test_repo_baseline_file_matches_checker_contract(mod):
    """The committed baseline must be loadable by the checker."""
    baseline_path = _SCRIPT.parent / "baselines" / "mypy_full_baseline.json"
    data = mod.load_baseline(baseline_path)
    assert data["error_count"] >= 0
