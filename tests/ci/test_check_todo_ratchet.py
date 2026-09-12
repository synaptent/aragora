"""Exercise the root marker wrapper through the shared runner and real grep."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci/check_todo_ratchet.py"
RUNNER = ROOT / "scripts/ci/check_tool_baseline.py"


def run(
    root: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--cwd", str(root), "--baseline", "baseline.json", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def write(root: Path, name: str, content: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_help_documents_scope_paths_and_exit_codes(tmp_path: Path) -> None:
    result = run(tmp_path, "--help")
    assert result.returncode == 0
    for phrase in (
        "aragora/",
        "scripts/",
        "tests/",
        "*.py",
        "docs/",
        "scripts/baselines/",
        "--cwd",
        "--report-json",
        "0 ",
        "1 ",
        "2 ",
        "3 ",
    ):
        assert phrase in result.stdout


@pytest.mark.parametrize("with_source", [False, True])
def test_zero_matches_wrapper_and_shared_runner(tmp_path: Path, with_source: bool) -> None:
    if with_source:
        write(tmp_path, "aragora/clean.py", "x = 1\n")
    assert run(tmp_path, "--update").returncode == 0
    assert json.loads((tmp_path / "baseline.json").read_text())["findings"] == {}
    assert run(tmp_path).returncode == 0
    direct = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--tool",
            "todo",
            "--cwd",
            str(tmp_path),
            "--baseline",
            str(tmp_path / "baseline.json"),
            "--",
            "grep",
            "-rnH",
            "--include=*.py",
            "-E",
            "TODO|FIXME",
            ".",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert direct.returncode == 0, direct.stderr


@pytest.mark.parametrize("directory", ["aragora", "scripts", "tests"])
@pytest.mark.parametrize("marker", ["TODO", "FIXME"])
def test_new_markers_fail_with_path_and_report(tmp_path: Path, directory: str, marker: str) -> None:
    assert run(tmp_path, "--update").returncode == 0
    write(tmp_path, f"{directory}/probe.py", f"# {marker}: validation probe\n")
    before = (tmp_path / "baseline.json").read_bytes()
    for flags in ([], ["--update"]):
        result = run(tmp_path, "--report-json", "reports/todo.json", *flags)
        assert result.returncode == 1, result.stderr
        assert f"{directory}/probe.py" in result.stdout
        assert (tmp_path / "baseline.json").read_bytes() == before
        report = json.loads((tmp_path / "reports/todo.json").read_text())
        assert report["tool"] == "todo"
        assert report["exit_code"] == report["new_count"] == 1


def test_scope_excludes_docs_baselines_and_wrapper(tmp_path: Path) -> None:
    for name in (
        "docs/probe.py",
        "scripts/baselines/probe.py",
        "scripts/ci/check_todo_ratchet.py",
        "aragora/probe.md",
        "other/probe.py",
    ):
        write(tmp_path, name, "# TODO: excluded\n")
    assert run(tmp_path, "--update").returncode == 0
    assert json.loads((tmp_path / "baseline.json").read_text())["findings"] == {}


def test_stable_keys_occurrences_shrink_and_idempotence(tmp_path: Path) -> None:
    source = write(tmp_path, "aragora/probe.py", "# TODO: existing\n" * 2)
    assert run(tmp_path, "--update").returncode == 0
    baseline = tmp_path / "baseline.json"
    before = baseline.read_bytes()
    data = json.loads(before)
    assert data["tool"] == "todo" and data["version"] == 1
    assert list(data["findings"].values()) == [2]
    source.write_text("\n" + source.read_text())
    for _ in range(2):
        assert run(tmp_path, "--update").returncode == 0
        assert baseline.read_bytes() == before
    source.write_text("# TODO: existing\n" * 3)
    assert run(tmp_path).returncode == 1
    source.write_text("# TODO: existing\n")
    assert run(tmp_path, "--update").returncode == 0
    assert list(json.loads(baseline.read_text())["findings"].values()) == [1]


def test_missing_grep_returns_three_without_rewriting(tmp_path: Path) -> None:
    assert run(tmp_path, "--update").returncode == 0
    before = (tmp_path / "baseline.json").read_bytes()
    result = run(
        tmp_path, "--update", "--report-json", "report.json", env={**os.environ, "PATH": ""}
    )
    assert result.returncode == 3
    assert "tool failed to run" in result.stderr
    assert (tmp_path / "baseline.json").read_bytes() == before
    assert json.loads((tmp_path / "report.json").read_text())["exit_code"] == 3


def test_default_paths_are_repository_relative(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 new findings" in result.stdout
