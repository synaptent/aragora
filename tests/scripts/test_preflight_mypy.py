"""Focused tests for scripts/preflight_mypy.sh.

The gate selects files from COMMITTED state only (a three-dot
``<base>...HEAD`` diff), so python edits outside that diff (staged, unstaged,
or untracked) are never type-checked; files inside the diff are passed to
mypy, which reads their working-tree content. These tests pin the
committed-diff behavior byte-for-byte (stdout, exit codes, and the exact mypy
argv captured via a PATH shim) and prove the advisory stderr disclosure for
uncommitted python changes never alters that behavior.

After the repo-config pass the script always runs the repo's own pre-push
``typecheck-changed`` hook through pre-commit, so a preflight-clean branch
cannot still be blocked at ``git push``. The hermetic tests capture the
pre-commit argv through a second PATH shim; the opt-in integration tests run
the real hook and real mypy on fixtures where the two passes disagree.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "preflight_mypy.sh"

SKIP_STDOUT = "no python changes; repo-config mypy pass skipped\n"
DISCLOSURE_HEADER = (
    "preflight_mypy: WARNING: uncommitted python changes are NOT checked "
    "by this committed-state gate (origin/main...HEAD):\n"
)
DISCLOSURE_FOOTER = (
    "preflight_mypy: commit them and re-run scripts/preflight_mypy.sh to type-check them.\n"
)
HOOK_PARITY_STDOUT = (
    "\n"
    "preflight_mypy: pre-push hook parity: typecheck-changed "
    "(plans origin/main...HEAD, as on git push):\n"
)
HOOK_ARGV = ["run", "typecheck-changed", "--hook-stage", "pre-push", "--all-files", "--verbose"]
HOOK_ARGV_FILE = "pre_commit_argv.txt"

HOOK_INTEGRATION_ENV = "PREFLIGHT_MYPY_HOOK_INTEGRATION"


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


def _shim_env(
    tmp_path: Path, *, exit_code: int = 0, hook_exit_code: int = 0
) -> tuple[dict[str, str], Path]:
    """Build PATH shims for mypy and pre-commit that record argv and never type-check.

    Keeps the tests hermetic (no real mypy or pre-commit run, no install
    requirement) while proving exactly which argv the script would hand to
    each tool. The pre-commit argv lands next to the mypy argv file under
    ``HOOK_ARGV_FILE``.
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
    hook_shim = shim_dir / "pre-commit"
    hook_shim.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "${PRE_COMMIT_ARGV_OUT:?}"\n'
        + f"exit {hook_exit_code}\n",
        encoding="utf-8",
    )
    hook_shim.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"
    env["MYPY_ARGV_OUT"] = str(argv_out)
    env["PRE_COMMIT_ARGV_OUT"] = str(shim_dir / HOOK_ARGV_FILE)
    return env, argv_out


def _hook_argv(argv_out: Path) -> list[str]:
    return (argv_out.parent / HOOK_ARGV_FILE).read_text(encoding="utf-8").splitlines()


def _preflight(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _run(["bash", str(SCRIPT), "--diff-base", "origin/main"], cwd=repo, env=env)


def _commit_python_pair(repo: Path) -> None:
    (repo / "scripts").mkdir()
    (repo / "scripts" / "foo.py").write_text("y = 2\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_foo.py").write_text("z = 3\n", encoding="utf-8")
    _run(["git", "add", "scripts/foo.py", "tests/test_foo.py"], cwd=repo)
    _run(["git", "commit", "-m", "feat: add python pair"], cwd=repo)


PAIR_STDOUT = (
    "preflight_mypy: origin/main...HEAD changed python files:\n"
    "  scripts/foo.py\n"
    "  tests/test_foo.py\n"
    "\n"
)


def test_clean_tree_skips_with_no_disclosure(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    env, argv_out = _shim_env(tmp_path)

    proc = _preflight(repo, env)

    assert proc.returncode == 0
    assert proc.stdout == SKIP_STDOUT + HOOK_PARITY_STDOUT
    assert proc.stderr == ""
    assert not argv_out.exists()
    assert _hook_argv(argv_out) == HOOK_ARGV


def test_committed_python_diff_runs_mypy_on_exactly_changed_files(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _commit_python_pair(repo)
    env, argv_out = _shim_env(tmp_path)

    proc = _preflight(repo, env)

    assert proc.returncode == 0
    assert proc.stdout == PAIR_STDOUT + HOOK_PARITY_STDOUT
    assert proc.stderr == ""
    assert argv_out.read_text(encoding="utf-8").splitlines() == [
        "--pretty",
        "scripts/foo.py",
        "tests/test_foo.py",
    ]
    assert _hook_argv(argv_out) == HOOK_ARGV


def test_committed_diff_mypy_exit_code_passthrough_and_hint(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _commit_python_pair(repo)
    env, argv_out = _shim_env(tmp_path, exit_code=7)

    proc = _preflight(repo, env)

    assert proc.returncode == 7
    assert "preflight_mypy: mypy reported issues (exit 7)." in proc.stderr
    assert "uncommitted python changes" not in proc.stderr
    assert "pre-push typecheck-changed hook reported issues" not in proc.stderr
    assert argv_out.read_text(encoding="utf-8").splitlines() == [
        "--pretty",
        "scripts/foo.py",
        "tests/test_foo.py",
    ]
    # The hook still runs after a repo-config failure so one preflight run
    # reports both verdicts.
    assert _hook_argv(argv_out) == HOOK_ARGV


def test_repo_config_failure_exit_code_wins_over_hook_failure(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _commit_python_pair(repo)
    env, argv_out = _shim_env(tmp_path, exit_code=7, hook_exit_code=1)

    proc = _preflight(repo, env)

    assert proc.returncode == 7
    assert "preflight_mypy: mypy reported issues (exit 7)." in proc.stderr
    assert "preflight_mypy: the pre-push typecheck-changed hook reported issues (exit 1)" in (
        proc.stderr
    )


def test_hook_failure_fails_preflight_when_repo_config_pass_is_clean(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "aragora").mkdir()
    (repo / "aragora" / "child.py").write_text("c = 1\n", encoding="utf-8")
    _run(["git", "add", "aragora/child.py"], cwd=repo)
    _run(["git", "commit", "-m", "feat: aragora change"], cwd=repo)
    env, argv_out = _shim_env(tmp_path, exit_code=0, hook_exit_code=1)

    proc = _preflight(repo, env)

    assert proc.returncode == 1
    assert proc.stdout == (
        "preflight_mypy: origin/main...HEAD changed python files:\n"
        "  aragora/child.py\n"
        "\n" + HOOK_PARITY_STDOUT
    )
    assert "preflight_mypy: mypy reported issues" not in proc.stderr
    assert (
        "preflight_mypy: the pre-push typecheck-changed hook reported issues (exit 1); "
        "git push would be blocked." in proc.stderr
    )
    assert argv_out.read_text(encoding="utf-8").splitlines() == ["--pretty", "aragora/child.py"]
    assert _hook_argv(argv_out) == HOOK_ARGV


def test_hook_runs_and_can_fail_without_python_changes(tmp_path: Path) -> None:
    # pyproject.toml forces the hook's full typecheck tier, so a branch with
    # no python changes can still be blocked at push.
    repo = _init_repo(tmp_path)
    (repo / "pyproject.toml").write_text("[tool.mypy]\n", encoding="utf-8")
    _run(["git", "add", "pyproject.toml"], cwd=repo)
    _run(["git", "commit", "-m", "chore: config change"], cwd=repo)
    env, argv_out = _shim_env(tmp_path, hook_exit_code=1)

    proc = _preflight(repo, env)

    assert proc.returncode == 1
    assert proc.stdout == SKIP_STDOUT + HOOK_PARITY_STDOUT
    assert "git push would be blocked" in proc.stderr
    assert not argv_out.exists()
    assert _hook_argv(argv_out) == HOOK_ARGV


def test_missing_pre_commit_fails_closed(tmp_path: Path) -> None:
    system_path = "/usr/bin:/bin"
    if shutil.which("pre-commit", path=system_path):
        pytest.skip("pre-commit is installed in a system directory; cannot hide it")
    repo = _init_repo(tmp_path)
    _commit_python_pair(repo)
    env, argv_out = _shim_env(tmp_path)
    (argv_out.parent / "pre-commit").unlink()
    env["PATH"] = f"{argv_out.parent}{os.pathsep}{system_path}"

    proc = _preflight(repo, env)

    assert proc.returncode == 2
    assert proc.stdout == PAIR_STDOUT + HOOK_PARITY_STDOUT
    assert (
        "error: pre-commit is not installed in PATH; it is required to reproduce "
        "the pre-push typecheck-changed hook" in proc.stderr
    )
    assert not (argv_out.parent / HOOK_ARGV_FILE).exists()


def test_unstaged_python_edit_discloses_on_stderr(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    env, argv_out = _shim_env(tmp_path)
    (repo / "pkg.py").write_text("x = 1\nx2 = 2\n", encoding="utf-8")

    proc = _preflight(repo, env)

    assert proc.returncode == 0
    assert proc.stdout == SKIP_STDOUT + HOOK_PARITY_STDOUT
    assert proc.stderr == DISCLOSURE_HEADER + "  pkg.py\n" + DISCLOSURE_FOOTER
    assert not argv_out.exists()


def test_staged_python_edit_discloses_on_stderr(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    env, argv_out = _shim_env(tmp_path)
    (repo / "pkg.py").write_text("x = 1\nx3 = 3\n", encoding="utf-8")
    _run(["git", "add", "pkg.py"], cwd=repo)

    proc = _preflight(repo, env)

    assert proc.returncode == 0
    assert proc.stdout == SKIP_STDOUT + HOOK_PARITY_STDOUT
    assert proc.stderr == DISCLOSURE_HEADER + "  pkg.py\n" + DISCLOSURE_FOOTER
    assert not argv_out.exists()


def test_untracked_python_file_discloses_on_stderr(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    env, argv_out = _shim_env(tmp_path)
    (repo / "new_tool.py").write_text("t = 4\n", encoding="utf-8")

    proc = _preflight(repo, env)

    assert proc.returncode == 0
    assert proc.stdout == SKIP_STDOUT + HOOK_PARITY_STDOUT
    assert proc.stderr == DISCLOSURE_HEADER + "  new_tool.py\n" + DISCLOSURE_FOOTER
    assert not argv_out.exists()


def test_non_python_dirty_files_do_not_disclose(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    env, argv_out = _shim_env(tmp_path)
    (repo / "README.md").write_text("base\nedited\n", encoding="utf-8")

    proc = _preflight(repo, env)

    assert proc.returncode == 0
    assert proc.stdout == SKIP_STDOUT + HOOK_PARITY_STDOUT
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
    assert proc.stdout == PAIR_STDOUT + HOOK_PARITY_STDOUT
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


# --- Opt-in integration: the real typecheck-changed hook and real mypy ---------
#
# These run the repo's actual hook definition through pre-commit (which may
# need network access the first time it builds the hook's pinned mypy
# environment), so they only run when PREFLIGHT_MYPY_HOOK_INTEGRATION=1.

_FIXTURE_PYPROJECT = """\
[tool.mypy]
python_version = "3.11"
ignore_missing_imports = true
follow_imports = "silent"
check_untyped_defs = false
"""

_BASE_MODULE = """\
class Base:
    def __init__(self) -> None:
        self._connected = False


def takes_str(value: str) -> str:
    return value
"""

# Reading and assigning an attribute that only the (unchanged) base class
# initializes: the hook's --follow-imports=skip cannot see Base's body.
_HAS_TYPE_MODULE = """\
from aragora.base import Base


class Child(Base):
    async def connect(self) -> bool:
        if self._connected:
            return True
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False
"""

# A wrong argument type for a function defined in an unchanged module: the
# repo config follows the import and reports it; the hook treats it as Any.
_ARG_TYPE_MODULE = """\
from aragora.base import takes_str


def use() -> str:
    return takes_str(123)
"""

_CLEAN_MODULE = """\
def double(value: int) -> int:
    return value * 2
"""


def _typecheck_hook_config() -> str:
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = [
        hook
        for repo in config["repos"]
        if repo["repo"] == "local"
        for hook in repo["hooks"]
        if hook["id"] == "typecheck-changed"
    ]
    assert len(hooks) == 1
    return yaml.safe_dump({"repos": [{"repo": "local", "hooks": hooks}]}, sort_keys=False)


def _init_hook_fixture_repo(tmp_path: Path, *, changed_module: str) -> Path:
    repo = _init_repo(tmp_path)
    (repo / ".pre-commit-config.yaml").write_text(_typecheck_hook_config(), encoding="utf-8")
    (repo / "pyproject.toml").write_text(_FIXTURE_PYPROJECT, encoding="utf-8")
    (repo / "scripts").mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "run_typecheck_gate.py", repo / "scripts")
    (repo / "aragora").mkdir()
    (repo / "aragora" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "aragora" / "base.py").write_text(_BASE_MODULE, encoding="utf-8")
    _run(["git", "add", "-A"], cwd=repo)
    _run(["git", "commit", "-m", "fixture base"], cwd=repo)
    _run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=repo)
    (repo / "aragora" / "child.py").write_text(changed_module, encoding="utf-8")
    _run(["git", "add", "aragora/child.py"], cwd=repo)
    _run(["git", "commit", "-m", "fixture change"], cwd=repo)
    return repo


def _run_real_hook(repo: Path) -> subprocess.CompletedProcess[str]:
    return _run(["pre-commit", *HOOK_ARGV], cwd=repo, env=dict(os.environ))


requires_real_hook = pytest.mark.skipif(
    os.environ.get(HOOK_INTEGRATION_ENV) != "1"
    or shutil.which("pre-commit") is None
    or shutil.which("mypy") is None,
    reason=f"set {HOOK_INTEGRATION_ENV}=1 with pre-commit and mypy on PATH",
)


@requires_real_hook
def test_real_hook_failure_on_base_class_attribute_also_fails_preflight(tmp_path: Path) -> None:
    repo = _init_hook_fixture_repo(tmp_path, changed_module=_HAS_TYPE_MODULE)

    hook = _run_real_hook(repo)
    preflight = _preflight(repo, dict(os.environ))

    assert hook.returncode != 0, hook.stdout + hook.stderr
    assert "[has-type]" in hook.stdout
    assert preflight.returncode != 0, preflight.stdout + preflight.stderr
    assert "[has-type]" in preflight.stdout
    assert "git push would be blocked" in preflight.stderr


@requires_real_hook
def test_real_repo_config_only_error_still_fails_preflight(tmp_path: Path) -> None:
    # The delta in the other direction is deliberate: preflight keeps its
    # repo-config pass, so it stays stricter than the hook here.
    repo = _init_hook_fixture_repo(tmp_path, changed_module=_ARG_TYPE_MODULE)

    hook = _run_real_hook(repo)
    preflight = _preflight(repo, dict(os.environ))

    assert hook.returncode == 0, hook.stdout + hook.stderr
    assert preflight.returncode != 0, preflight.stdout + preflight.stderr
    assert "[arg-type]" in preflight.stdout
    assert "git push would be blocked" not in preflight.stderr


@requires_real_hook
def test_real_hook_and_preflight_both_pass_on_clean_change(tmp_path: Path) -> None:
    repo = _init_hook_fixture_repo(tmp_path, changed_module=_CLEAN_MODULE)

    hook = _run_real_hook(repo)
    preflight = _preflight(repo, dict(os.environ))

    assert hook.returncode == 0, hook.stdout + hook.stderr
    assert preflight.returncode == 0, preflight.stdout + preflight.stderr
