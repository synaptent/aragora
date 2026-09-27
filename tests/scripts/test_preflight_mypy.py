"""Focused tests for scripts/preflight_mypy.sh.

The gate selects files from COMMITTED state only (a three-dot
``<base>...HEAD`` diff), so python edits outside that diff (staged, unstaged,
or untracked) are never type-checked; files inside the diff are passed to
mypy, which reads their working-tree content. These tests pin the
committed-diff behavior byte-for-byte (stdout, exit codes, and the exact mypy
argv captured via a PATH shim) and prove the advisory stderr disclosure for
uncommitted python changes never alters that behavior.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "preflight_mypy.sh"

SKIP_STDOUT = "no python changes; mypy preflight skipped\n"
DISCLOSURE_HEADER = (
    "preflight_mypy: WARNING: uncommitted python changes are NOT checked "
    "by this committed-state gate (origin/main...HEAD):\n"
)
DISCLOSURE_FOOTER = (
    "preflight_mypy: commit them and re-run scripts/preflight_mypy.sh to type-check them.\n"
)


def _run(
    args: list[str], *, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False, env=env)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-b", "main"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    (repo / "pkg.py").write_text("x = 1\n", encoding="utf-8")
    _run(["git", "add", "README.md", "pkg.py"], cwd=repo)
    _run(["git", "commit", "-m", "init"], cwd=repo)
    _run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=repo)
    return repo


def _shim_env(tmp_path: Path, *, exit_code: int = 0) -> tuple[dict[str, str], Path]:
    """Build a PATH shim for mypy that records its argv and never type-checks.

    Keeps the tests hermetic (no real mypy run, no mypy install requirement)
    while proving exactly which argv the script would hand to mypy.
    """
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    argv_out = shim_dir / "argv.txt"
    shim = shim_dir / "mypy"
    shim.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "${MYPY_ARGV_OUT:?}"\n' + f"exit {exit_code}\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"
    env["MYPY_ARGV_OUT"] = str(argv_out)
    return env, argv_out


def _preflight(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _run(["bash", str(SCRIPT), "--diff-base", "origin/main"], cwd=repo, env=env)


def _commit_python_pair(repo: Path) -> None:
    (repo / "scripts").mkdir()
    (repo / "scripts" / "foo.py").write_text("y = 2\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_foo.py").write_text("z = 3\n", encoding="utf-8")
    _run(["git", "add", "scripts/foo.py", "tests/test_foo.py"], cwd=repo)
    _run(["git", "commit", "-m", "feat: add python pair"], cwd=repo)


def test_clean_tree_skips_with_no_disclosure(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    env, argv_out = _shim_env(tmp_path)

    proc = _preflight(repo, env)

    assert proc.returncode == 0
    assert proc.stdout == SKIP_STDOUT
    assert proc.stderr == ""
    assert not argv_out.exists()


def test_committed_python_diff_runs_mypy_on_exactly_changed_files(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _commit_python_pair(repo)
    env, argv_out = _shim_env(tmp_path)

    proc = _preflight(repo, env)

    assert proc.returncode == 0
    assert proc.stdout == (
        "preflight_mypy: origin/main...HEAD changed python files:\n"
        "  scripts/foo.py\n"
        "  tests/test_foo.py\n"
        "\n"
    )
    assert proc.stderr == ""
    assert argv_out.read_text(encoding="utf-8").splitlines() == [
        "--pretty",
        "scripts/foo.py",
        "tests/test_foo.py",
    ]


def test_committed_diff_mypy_exit_code_passthrough_and_hint(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _commit_python_pair(repo)
    env, argv_out = _shim_env(tmp_path, exit_code=7)

    proc = _preflight(repo, env)

    assert proc.returncode == 7
    assert "preflight_mypy: mypy reported issues (exit 7)." in proc.stderr
    assert "uncommitted python changes" not in proc.stderr
    assert argv_out.read_text(encoding="utf-8").splitlines() == [
        "--pretty",
        "scripts/foo.py",
        "tests/test_foo.py",
    ]


def test_unstaged_python_edit_discloses_on_stderr(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    env, argv_out = _shim_env(tmp_path)
    (repo / "pkg.py").write_text("x = 1\nx2 = 2\n", encoding="utf-8")

    proc = _preflight(repo, env)

    assert proc.returncode == 0
    assert proc.stdout == SKIP_STDOUT
    assert proc.stderr == DISCLOSURE_HEADER + "  pkg.py\n" + DISCLOSURE_FOOTER
    assert not argv_out.exists()


def test_staged_python_edit_discloses_on_stderr(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    env, argv_out = _shim_env(tmp_path)
    (repo / "pkg.py").write_text("x = 1\nx3 = 3\n", encoding="utf-8")
    _run(["git", "add", "pkg.py"], cwd=repo)

    proc = _preflight(repo, env)

    assert proc.returncode == 0
    assert proc.stdout == SKIP_STDOUT
    assert proc.stderr == DISCLOSURE_HEADER + "  pkg.py\n" + DISCLOSURE_FOOTER
    assert not argv_out.exists()


def test_untracked_python_file_discloses_on_stderr(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    env, argv_out = _shim_env(tmp_path)
    (repo / "new_tool.py").write_text("t = 4\n", encoding="utf-8")

    proc = _preflight(repo, env)

    assert proc.returncode == 0
    assert proc.stdout == SKIP_STDOUT
    assert proc.stderr == DISCLOSURE_HEADER + "  new_tool.py\n" + DISCLOSURE_FOOTER
    assert not argv_out.exists()


def test_non_python_dirty_files_do_not_disclose(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    env, argv_out = _shim_env(tmp_path)
    (repo / "README.md").write_text("base\nedited\n", encoding="utf-8")

    proc = _preflight(repo, env)

    assert proc.returncode == 0
    assert proc.stdout == SKIP_STDOUT
    assert proc.stderr == ""
    assert not argv_out.exists()


def test_dirty_file_inside_committed_diff_is_not_named_in_disclosure(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _commit_python_pair(repo)
    env, argv_out = _shim_env(tmp_path)
    # scripts/foo.py is selected by the committed diff and mypy reads its
    # working-tree content, so it IS checked (dirty edits included) and must
    # not be reported as unchecked; only pkg.py is genuinely outside the gate.
    (repo / "scripts" / "foo.py").write_text("y = 2\ny2 = 5\n", encoding="utf-8")
    (repo / "pkg.py").write_text("x = 1\nx5 = 5\n", encoding="utf-8")

    proc = _preflight(repo, env)

    assert proc.returncode == 0
    assert proc.stdout == (
        "preflight_mypy: origin/main...HEAD changed python files:\n"
        "  scripts/foo.py\n"
        "  tests/test_foo.py\n"
        "\n"
    )
    assert proc.stderr == DISCLOSURE_HEADER + "  pkg.py\n" + DISCLOSURE_FOOTER
    assert argv_out.read_text(encoding="utf-8").splitlines() == [
        "--pretty",
        "scripts/foo.py",
        "tests/test_foo.py",
    ]


def test_committed_diff_with_dirty_tree_keeps_committed_behavior_identical(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _commit_python_pair(repo)
    env, argv_out = _shim_env(tmp_path)

    control = _preflight(repo, env)
    control_argv = argv_out.read_text(encoding="utf-8")
    argv_out.unlink()

    (repo / "pkg.py").write_text("x = 1\nx4 = 4\n", encoding="utf-8")
    dirty = _preflight(repo, env)

    assert dirty.returncode == control.returncode == 0
    assert dirty.stdout == control.stdout
    assert argv_out.read_text(encoding="utf-8") == control_argv
    assert control.stderr == ""
    assert dirty.stderr == DISCLOSURE_HEADER + "  pkg.py\n" + DISCLOSURE_FOOTER
