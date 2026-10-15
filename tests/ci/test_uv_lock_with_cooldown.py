"""Tests for ``scripts/ci/uv_lock_with_cooldown.sh``.

The helper runs against a fake ``uv`` (no network): the fake logs every call as a
JSON line and writes a minimal ``uv.lock`` whose packages come from the scenario
in ``FAKE_UV_CONFIG``. ``ARAGORA_TEST_BASH`` selects the bash that runs the
helper (for example macOS ``/bin/bash`` 3.2 or GNU bash 5).
"""

from __future__ import annotations

import inspect
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "ci" / "uv_lock_with_cooldown.sh"
BASH = shutil.which(os.environ.get("ARAGORA_TEST_BASH", "bash")) or "bash"
SYSTEM_PATH = "/usr/bin:/bin"
RFC3339_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
CUTOFF_LINE = re.compile(r"^exclude-newer cutoff: (\S+)$", re.MULTILINE)

ORIGINAL = [("dep", "3.0"), ("pkg", "0.9")]
PLAIN = [("dep", "3.1"), ("pkg", "2.0")]
COOLED = [("dep", "3.1"), ("pkg", "1.0")]
NO_SOLUTION = (
    "  x No solution found when resolving dependencies:\n"
    "  `-> Because only pkg<2.0 was released before the cutoff and fixture depends on\n"
    "      pkg>=2.0, we can conclude that fixture's requirements are unsatisfiable.\n"
)
FETCH_FAILURE = "error: Failed to fetch: `https://pypi.org/simple/pkg/`\n"


def render_lock(packages: Sequence[Sequence[Any]], options: dict[str, Any] | None = None) -> str:
    """Render a minimal uv.lock; the fake ``uv`` embeds this exact function.

    A package is ``(name, version)``, or ``(name, version, markers)`` for one
    marker fork of a forked package (written as uv writes ``resolution-markers``).
    """
    lines = ["version = 1", 'requires-python = ">=3.10"', ""]
    if options:
        lines += ["[options]", f'exclude-newer = "{options["exclude-newer"]}"', ""]
        if options["packages"]:
            lines.append("[options.exclude-newer-package]")
            lines += [f'{name} = "{stamp}"' for name, stamp in options["packages"]]
            lines.append("")
    for name, version, *fork in packages:
        lines += ["[[package]]", f'name = "{name}"', f'version = "{version}"']
        if fork:
            lines += ["resolution-markers = [", *[f'    "{m}",' for m in fork[0]], "]"]
        lines.append("")
    return "\n".join(lines)


def parse_lock(text: str) -> list[tuple[Any, ...]]:
    """Read back the packages of a ``render_lock`` lock; the fake ``uv`` embeds this too."""
    packages: list[tuple[Any, ...]] = []
    for block in text.split("[[package]]\n")[1:]:
        name = re.search(r'^name = "(.+)"$', block, re.MULTILINE)
        version = re.search(r'^version = "(.+)"$', block, re.MULTILINE)
        assert name and version, block
        markers = re.findall(r'^    "(.+)",$', block, re.MULTILINE)
        fork = (markers,) if "resolution-markers" in block else ()
        packages.append((name.group(1), version.group(1), *fork))
    return packages


# Call kinds: "cooled" carries --exclude-newer; "finalize" is a plain call over
# a lock that still has the exclude-newer options (uv keeps its pins as
# preferences); "plain" is any other plain call; "check" is `uv lock --check`.
FAKE_UV = r"""
import json
import os
import re
import sys
from pathlib import Path

__RENDER_LOCK__

config = json.loads(os.environ["FAKE_UV_CONFIG"])
argv = sys.argv[1:]
lock = Path("uv.lock")
existing = lock.read_text(encoding="utf-8") if lock.exists() else ""
if "--check" in argv:
    kind = "check"
elif "--exclude-newer" in argv:
    kind = "cooled"
elif "exclude-newer" in existing:
    kind = "finalize"
else:
    kind = "plain"
entry = {"argv": argv, "kind": kind, "uv_exclude_newer_set": "UV_EXCLUDE_NEWER" in os.environ}
with open(config["log"], "a", encoding="utf-8") as log:
    log.write(json.dumps(entry) + "\n")
print("fake uv: " + kind)
if kind == "check":
    sys.exit(1 if "exclude-newer" in existing else 0)
failure = config.get("fail", {}).get(kind)
if failure:
    lock.write_text("# partial write from a failed uv call\n", encoding="utf-8")
    sys.stderr.write(failure["stderr"])
    sys.exit(failure["rc"])
if kind == "cooled":
    stamps = [
        argv[i + 1].split("=", 1) for i, arg in enumerate(argv) if arg == "--exclude-newer-package"
    ]
    options = {"exclude-newer": argv[argv.index("--exclude-newer") + 1], "packages": stamps}
    lock.write_text(render_lock(config["cooled"], options), encoding="utf-8")
elif kind == "plain":
    lock.write_text(render_lock(config["plain"]), encoding="utf-8")
elif not config.get("keep_options"):
    pinned = parse_lock(existing)
    if config.get("drift"):
        pinned[0] = (pinned[0][0], pinned[0][1] + ".post1", *pinned[0][2:])
    lock.write_text(render_lock(pinned), encoding="utf-8")
"""


def write_fake_bin(bin_dir: Path) -> None:
    """Write the fake ``uv`` and a ``bash`` link to the selected bash into bin_dir."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    embedded = inspect.getsource(render_lock) + "\n\n" + inspect.getsource(parse_lock)
    source = FAKE_UV.replace("__RENDER_LOCK__", embedded)
    script = bin_dir / "fake_uv.py"
    script.write_text("from __future__ import annotations\n" + source, encoding="utf-8")
    uv = bin_dir / "uv"
    uv.write_text(f"#!/bin/sh\nexec '{sys.executable}' '{script}' \"$@\"\n", encoding="utf-8")
    uv.chmod(0o755)
    bash = bin_dir / "bash"
    if not bash.exists():
        bash.symlink_to(BASH)


def fake_uv_config(log: Path, **scenario: object) -> str:
    return json.dumps({"plain": PLAIN, "cooled": COOLED, "log": str(log), **scenario})


def read_calls(log: Path) -> list[dict[str, object]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def clean_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not key.startswith("UV_")}


def make_project(
    tmp_path: Path,
    *,
    lock: bool = True,
    pyproject: bool = True,
    lock_packages: Sequence[Sequence[Any]] = ORIGINAL,
    dependencies: tuple[str, ...] = ("dep", "pkg"),
) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    if pyproject:
        (project / "pyproject.toml").write_text(
            '[project]\nname = "fixture"\nversion = "0"\n'
            f"dependencies = {json.dumps(list(dependencies))}\n",
            encoding="utf-8",
        )
    if lock:
        (project / "uv.lock").write_text(render_lock(lock_packages), encoding="utf-8")
    return project


def run_helper(
    project: Path,
    *args: str,
    scenario: dict[str, object] | None = None,
    env: dict[str, str] | None = None,
    path_prefix: list[Path] | None = None,
    with_uv: bool = True,
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, object]]]:
    bin_dir = project.parent / ("bin" if with_uv else "bin-without-uv")
    if with_uv:
        write_fake_bin(bin_dir)
    else:
        bin_dir.mkdir(exist_ok=True)
    log = project.parent / "uv-calls.jsonl"
    path = [str(p) for p in path_prefix or []] + [str(bin_dir), SYSTEM_PATH]
    run_env = clean_env()
    run_env.update(PATH=":".join(path), FAKE_UV_CONFIG=fake_uv_config(log, **(scenario or {})))
    run_env.update(env or {})
    proc = subprocess.run(
        [BASH, str(HELPER), *args],
        cwd=project,
        env=run_env,
        text=True,
        capture_output=True,
        check=False,
    )
    return proc, read_calls(log)


def lock_text(project: Path) -> str:
    return (project / "uv.lock").read_text(encoding="utf-8")


def assert_original_restored(project: Path, *, had_lock: bool = True) -> None:
    if had_lock:
        assert lock_text(project) == render_lock(ORIGINAL)
    else:
        assert not (project / "uv.lock").exists()


def parse_utc(stamp: str) -> datetime:
    assert RFC3339_UTC.fullmatch(stamp), stamp
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def assert_cutoff_seven_days_ago(stdout: str) -> str:
    match = CUTOFF_LINE.search(stdout)
    assert match, stdout
    cutoff = match.group(1)
    expected = datetime.now(timezone.utc) - timedelta(days=7)
    assert abs(parse_utc(cutoff) - expected) < timedelta(minutes=2), cutoff
    return cutoff


def kinds(calls: list[dict[str, object]]) -> list[object]:
    return [call["kind"] for call in calls]


def test_equal_resolutions_exit_0_with_rfc3339_cutoff(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    proc, calls = run_helper(project, scenario={"plain": COOLED})

    assert proc.returncode == 0, proc.stderr
    cutoff = assert_cutoff_seven_days_ago(proc.stdout)
    assert "cooled-down resolution equals the plain resolution" in proc.stdout
    assert "held back" not in proc.stdout
    assert lock_text(project) == render_lock(COOLED)
    assert "exclude-newer" not in lock_text(project)
    assert calls[0]["argv"] == ["lock", "--exclude-newer", cutoff]


def test_cooled_resolution_runs_first_and_plain_only_for_comparison(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    proc, calls = run_helper(project)

    assert proc.returncode == 2, proc.stderr
    cutoff = assert_cutoff_seven_days_ago(proc.stdout)
    assert [call["argv"] for call in calls] == [
        ["lock", "--exclude-newer", cutoff],
        ["lock"],
        ["lock"],
    ]
    assert kinds(calls) == ["cooled", "plain", "finalize"]


def test_held_back_packages_are_reported_with_exit_2(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    proc, _ = run_helper(project)

    assert proc.returncode == 2, proc.stderr
    held = [line for line in proc.stdout.splitlines() if line.startswith("held back: ")]
    assert held == ["held back: pkg 2.0 -> 1.0"]
    assert "cooldown held back 1 package(s)" in proc.stdout
    assert lock_text(project) == render_lock(COOLED)


@pytest.mark.parametrize("had_lock", [True, False], ids=["with-lock", "without-lock"])
def test_unsatisfiable_cooled_resolution_exits_4_without_fallback(
    tmp_path: Path, had_lock: bool
) -> None:
    project = make_project(tmp_path, lock=had_lock)

    proc, calls = run_helper(
        project, scenario={"fail": {"cooled": {"rc": 1, "stderr": NO_SOLUTION}}}
    )

    assert proc.returncode == 4, (proc.stdout, proc.stderr)
    assert "No solution found when resolving dependencies" in proc.stderr
    assert "error: no resolution satisfies the 7-day cooldown (exclude-newer " in proc.stderr
    assert "original uv.lock restored; no unrestricted fallback" in proc.stderr
    assert "(manual security relock: docs/RATCHETS.md)" in proc.stderr
    assert "held back" not in proc.stdout
    assert_original_restored(project, had_lock=had_lock)
    assert kinds(calls) == ["cooled"]


def test_other_cooled_failure_exits_1_without_plain_resolution(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    proc, calls = run_helper(
        project, scenario={"fail": {"cooled": {"rc": 1, "stderr": FETCH_FAILURE}}}
    )

    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "Failed to fetch" in proc.stderr
    assert "no resolution satisfies" not in proc.stderr
    assert_original_restored(project)
    assert kinds(calls) == ["cooled"]


def test_comparison_resolution_failure_exits_1(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    proc, calls = run_helper(
        project, scenario={"fail": {"plain": {"rc": 1, "stderr": FETCH_FAILURE}}}
    )

    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert_original_restored(project)
    assert kinds(calls) == ["cooled", "plain"]


@pytest.mark.parametrize("stage", ["cooled", "plain", "finalize"])
def test_uv_step_exiting_2_never_reads_as_held_back(tmp_path: Path, stage: str) -> None:
    project = make_project(tmp_path)

    proc, _ = run_helper(project, scenario={"fail": {stage: {"rc": 2, "stderr": "error: boom\n"}}})

    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "step failed (exit 2); original uv.lock restored" in proc.stderr
    assert "held back" not in proc.stdout
    assert_original_restored(project)


def test_final_lock_drift_from_cooled_resolution_exits_1(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    proc, calls = run_helper(project, scenario={"plain": COOLED, "drift": True})

    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "error: final uv.lock drifted from the cooled-down resolution" in proc.stderr
    assert_original_restored(project)
    assert kinds(calls) == ["cooled", "plain", "finalize"]


def test_exclude_newer_left_in_final_lock_exits_1(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    proc, _ = run_helper(project, scenario={"plain": COOLED, "keep_options": True})

    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "final uv.lock" in proc.stderr
    assert_original_restored(project)


def test_missing_uv_exits_3_and_touches_nothing(tmp_path: Path) -> None:
    if shutil.which("uv", path=SYSTEM_PATH):
        pytest.skip(f"a real uv is installed in {SYSTEM_PATH}")
    project = make_project(tmp_path)

    proc, calls = run_helper(project, with_uv=False)

    assert proc.returncode == 3, (proc.stdout, proc.stderr)
    assert "'uv' is not on PATH" in proc.stderr
    assert_original_restored(project)
    assert sorted(path.name for path in project.iterdir()) == ["pyproject.toml", "uv.lock"]
    assert calls == []


def test_caller_uv_exclude_newer_is_unset_for_every_uv_call(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    proc, calls = run_helper(
        project,
        scenario={"plain": COOLED},
        env={"UV_EXCLUDE_NEWER": "2020-01-01T00:00:00Z"},
    )

    assert proc.returncode == 0, proc.stderr
    assert len(calls) == 3
    assert not [call for call in calls if call["uv_exclude_newer_set"]]


@pytest.mark.parametrize("names", [["pkg"], ["pkg", "Dep.Name_2"]], ids=["one", "two"])
def test_allow_package_lifts_the_cooldown_for_named_packages_only(
    tmp_path: Path, names: list[str]
) -> None:
    project = make_project(tmp_path)
    args = [arg for name in names for arg in ("--allow-package", name)]

    proc, calls = run_helper(project, *args, scenario={"plain": COOLED})

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    cutoff = assert_cutoff_seven_days_ago(proc.stdout)
    for name in names:
        lifted = f"cooldown lifted for: {name}"
        assert lifted in proc.stdout.splitlines()
        assert proc.stdout.index(lifted) < proc.stdout.index("fake uv: cooled")
    assert kinds(calls) == ["cooled", "plain", "finalize"]
    cooled_argv = calls[0]["argv"]
    assert isinstance(cooled_argv, list)
    assert cooled_argv[:3] == ["lock", "--exclude-newer", cutoff]
    extra = cooled_argv[3:]
    assert extra[0::2] == ["--exclude-newer-package"] * len(names)
    assert [value.split("=", 1)[0] for value in extra[1::2]] == names
    now = datetime.now(timezone.utc)
    for value in extra[1::2]:
        assert abs(parse_utc(value.split("=", 1)[1]) - now) < timedelta(minutes=2)
    assert calls[1]["argv"] == ["lock"]
    assert calls[2]["argv"] == ["lock"]
    assert lock_text(project) == render_lock(COOLED)
    assert "exclude-newer" not in lock_text(project)


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--bogus"], "error: unknown argument: --bogus"),
        (["--allow-package"], "error: --allow-package requires a package name"),
        (["--allow-package", "a b"], "error: invalid package name for --allow-package: 'a b'"),
        (["--allow-package", "-x"], "error: invalid package name for --allow-package: '-x'"),
        (["--allow-package", "pkg=1"], "error: invalid package name for --allow-package: 'pkg=1'"),
        (
            ["--allow-package", "pkg", "--allow-package", ""],
            "error: invalid package name for --allow-package: ''",
        ),
    ],
    ids=["unknown-option", "missing-name", "space", "dash", "equals", "empty"],
)
def test_bad_usage_exits_1_before_any_uv_call(
    tmp_path: Path, args: list[str], message: str
) -> None:
    project = make_project(tmp_path)

    proc, calls = run_helper(project, *args)

    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert message in proc.stderr
    assert calls == []
    assert_original_restored(project)


def test_help_documents_exit_codes_and_manual_security_relock(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    proc, calls = run_helper(project, "--help")

    assert proc.returncode == 0, proc.stderr
    for code in range(5):
        assert re.search(rf"^\s+{code}\s+\S", proc.stdout, re.MULTILINE), code
    assert "held back" in proc.stdout
    assert "Manual security relock" in proc.stdout
    assert "--allow-package NAME" in proc.stdout
    assert "never in CI" in proc.stdout
    assert calls == []


def test_missing_pyproject_exits_1(tmp_path: Path) -> None:
    project = make_project(tmp_path, pyproject=False)

    proc, calls = run_helper(project)

    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "no pyproject.toml" in proc.stderr
    assert calls == []
    assert_original_restored(project)


def find_gnu_date() -> str | None:
    for candidate in (shutil.which("gdate"), "/opt/homebrew/bin/gdate"):
        if candidate and Path(candidate).is_file():
            return candidate
    date = shutil.which("date")
    if (
        date
        and subprocess.run([date, "--version"], capture_output=True, check=False).returncode == 0
    ):
        return date
    return None


def test_gnu_date_branch_gives_rfc3339_cutoff(tmp_path: Path) -> None:
    gnu_date = find_gnu_date()
    if gnu_date is None:
        pytest.skip("no GNU date (gdate) on this host")
    project = make_project(tmp_path)
    shim_dir = tmp_path / "date-shim"
    shim_dir.mkdir()
    shim_log = tmp_path / "date-calls.log"
    shim = shim_dir / "date"
    shim.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{shim_log}'\nexec '{gnu_date}' \"$@\"\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)

    proc, calls = run_helper(project, scenario={"plain": COOLED}, path_prefix=[shim_dir])

    assert proc.returncode == 0, proc.stderr
    cutoff = assert_cutoff_seven_days_ago(proc.stdout)
    date_calls = shim_log.read_text(encoding="utf-8").splitlines()
    assert "--version" in date_calls
    assert [line for line in date_calls if line.startswith("-u -d 7 days ago ")]
    assert calls[0]["argv"] == ["lock", "--exclude-newer", cutoff]


# `sub` is a lock-only (transitive) package that an earlier manual security
# relock lifted to a release younger than the cutoff. Nothing in pyproject.toml
# requires it, so the cooled resolution succeeds with an older `sub`.
RECENT_SUB = [*ORIGINAL, ("sub", "2.0")]
PLAIN_SUB = [*PLAIN, ("sub", "2.0")]
COOLED_SUB = [*COOLED, ("sub", "1.5")]


def downgraded_lines(stdout: str) -> list[str]:
    return [line for line in stdout.splitlines() if line.startswith("downgraded: ")]


def test_lock_only_package_downgrade_exits_5_and_restores_the_original(tmp_path: Path) -> None:
    project = make_project(tmp_path, lock_packages=RECENT_SUB)

    proc, calls = run_helper(project, scenario={"plain": PLAIN_SUB, "cooled": COOLED_SUB})

    assert proc.returncode == 5, (proc.stdout, proc.stderr)
    assert downgraded_lines(proc.stdout) == ["downgraded: sub 2.0 -> 1.5"]
    assert (
        "error: the cooled-down resolution would downgrade 1 package(s) already in uv.lock "
        "(listed as `downgraded: <name> <original> -> <cooled>`); original uv.lock restored; "
        "nothing to commit (manual security relock: docs/RATCHETS.md)" in proc.stderr
    )
    assert "step failed" not in proc.stderr
    assert "held back" not in proc.stdout
    assert lock_text(project) == render_lock(RECENT_SUB)
    assert sorted(path.name for path in project.iterdir()) == ["pyproject.toml", "uv.lock"]
    assert kinds(calls) == ["cooled", "plain", "finalize"]


def test_manifest_package_newer_than_the_cutoff_still_exits_4(tmp_path: Path) -> None:
    recent = [("dep", "3.0"), ("pkg", "2.0")]
    project = make_project(tmp_path, lock_packages=recent, dependencies=("dep", "pkg>=2.0"))

    proc, calls = run_helper(
        project, scenario={"fail": {"cooled": {"rc": 1, "stderr": NO_SOLUTION}}}
    )

    assert proc.returncode == 4, (proc.stdout, proc.stderr)
    assert "error: no resolution satisfies the 7-day cooldown (exclude-newer " in proc.stderr
    assert downgraded_lines(proc.stdout) == []
    assert lock_text(project) == render_lock(recent)
    assert kinds(calls) == ["cooled"]


def test_allow_package_run_still_refuses_to_downgrade_other_packages(tmp_path: Path) -> None:
    project = make_project(tmp_path, lock_packages=RECENT_SUB)

    proc, calls = run_helper(
        project, "--allow-package", "pkg", scenario={"plain": COOLED_SUB, "cooled": COOLED_SUB}
    )

    assert proc.returncode == 5, (proc.stdout, proc.stderr)
    assert "cooldown lifted for: pkg" in proc.stdout.splitlines()
    assert downgraded_lines(proc.stdout) == ["downgraded: sub 2.0 -> 1.5"]
    assert lock_text(project) == render_lock(RECENT_SUB)
    assert kinds(calls) == ["cooled", "plain", "finalize"]


@pytest.mark.parametrize(
    ("original", "cooled", "downgraded"),
    [
        ("2.0", "2.0rc1", True),
        ("1.10", "1.9", True),
        ("1.0.post1", "1.0", True),
        ("1.0", "1.0.dev1", True),
        ("1!1.0", "2.0", True),
        ("1.0+local.2", "1.0+local.1", True),
        ("1.9", "1.10", False),
        ("2.0rc1", "2.0", False),
        ("1.0", "1.0.post1", False),
        ("2.0", "2.0.0", False),
    ],
    ids=[
        "final-to-rc",
        "numeric-not-lexical",
        "post-to-final",
        "final-to-dev",
        "epoch",
        "local",
        "upgrade-numeric",
        "rc-to-final",
        "final-to-post",
        "equal-trailing-zero",
    ],
)
def test_downgrade_check_uses_pep440_order(
    tmp_path: Path, original: str, cooled: str, downgraded: bool
) -> None:
    before = [("dep", "3.1"), ("sub", original)]
    after = [("dep", "3.1"), ("sub", cooled)]
    project = make_project(tmp_path, lock_packages=before, dependencies=("dep",))

    proc, _ = run_helper(project, scenario={"plain": after, "cooled": after})

    if downgraded:
        assert proc.returncode == 5, (proc.stdout, proc.stderr)
        assert downgraded_lines(proc.stdout) == [f"downgraded: sub {original} -> {cooled}"]
        assert lock_text(project) == render_lock(before)
    else:
        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        assert downgraded_lines(proc.stdout) == []
        assert lock_text(project) == render_lock(after)


def test_forked_package_downgraded_on_one_fork_exits_5(tmp_path: Path) -> None:
    before = [("dep", "3.1"), ("sub", "1.0"), ("sub", "2.0")]
    after = [("dep", "3.1"), ("sub", "1.0"), ("sub", "1.5")]
    project = make_project(tmp_path, lock_packages=before, dependencies=("dep",))

    proc, _ = run_helper(project, scenario={"plain": after, "cooled": after})

    assert proc.returncode == 5, (proc.stdout, proc.stderr)
    assert downgraded_lines(proc.stdout) == ["downgraded: sub 1.0,2.0 -> 1.0,1.5"]
    assert lock_text(project) == render_lock(before)


def test_removed_and_added_packages_are_not_downgrades(tmp_path: Path) -> None:
    before = [("dep", "3.0"), ("gone", "1.0")]
    after = [("dep", "3.1"), ("new", "0.1")]
    project = make_project(tmp_path, lock_packages=before, dependencies=("dep",))

    proc, _ = run_helper(project, scenario={"plain": after, "cooled": after})

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert downgraded_lines(proc.stdout) == []
    assert lock_text(project) == render_lock(after)


def test_without_an_original_lock_there_is_nothing_to_downgrade(tmp_path: Path) -> None:
    project = make_project(tmp_path, lock=False)

    proc, _ = run_helper(project, scenario={"plain": COOLED})

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert downgraded_lines(proc.stdout) == []
    assert lock_text(project) == render_lock(COOLED)


def test_unorderable_version_change_fails_closed_with_exit_1(tmp_path: Path) -> None:
    before = [("dep", "3.1"), ("sub", "not-a-version")]
    after = [("dep", "3.1"), ("sub", "still-not-a-version")]
    project = make_project(tmp_path, lock_packages=before, dependencies=("dep",))

    proc, _ = run_helper(project, scenario={"plain": after, "cooled": after})

    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "cannot order version" in proc.stderr
    assert "original uv.lock restored" in proc.stderr
    assert lock_text(project) == render_lock(before)


def test_help_documents_exit_5_for_downgrades(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    proc, calls = run_helper(project, "--help")

    assert proc.returncode == 0, proc.stderr
    assert re.search(r"^\s+5\s+\S", proc.stdout, re.MULTILINE)
    assert "downgraded: <name> <original> -> <cooled>" in proc.stdout
    assert calls == []


# Marker forks of the lock-only package `sub`, as uv writes them when the
# resolution forks on the Python version.
PY_LT_311 = "python_full_version < '3.11'"
PY_311 = "python_full_version == '3.11.*'"
PY_GE_311 = "python_full_version >= '3.11'"
PY_LT_312 = "python_full_version < '3.12'"
PY_GE_312 = "python_full_version >= '3.12'"
THREE_FORKS = [
    ("dep", "3.1"),
    ("sub", "1.0", [PY_LT_311]),
    ("sub", "2.0.2", [PY_311]),
    ("sub", "3.0", [PY_GE_312]),
]
MIDDLE_FORK_LOWERED = [
    ("dep", "3.1"),
    ("sub", "1.0", [PY_LT_311]),
    ("sub", "2.0.1", [PY_311]),
    ("sub", "3.0", [PY_GE_312]),
]
TWO_FORKS = [("dep", "3.1"), ("sub", "1.0", [PY_LT_311]), ("sub", "2.0", [PY_GE_311])]
REPARTITION_NOTE = (
    "note: sub forks on other markers than in the original uv.lock; "
    "it passes only if every cooled version is >= every original version"
)


def run_fork_case(
    tmp_path: Path,
    before: Sequence[Sequence[Any]],
    after: Sequence[Sequence[Any]],
    *args: str,
    plain: Sequence[Sequence[Any]] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, object]], bytes, Path]:
    project = make_project(tmp_path, lock_packages=before, dependencies=("dep",))
    original = (project / "uv.lock").read_bytes()
    proc, calls = run_helper(
        project, *args, scenario={"plain": after if plain is None else plain, "cooled": after}
    )
    return proc, calls, original, project


def assert_fork_downgrade_refused(
    proc: subprocess.CompletedProcess[str],
    calls: list[dict[str, object]],
    original: bytes,
    project: Path,
    line: str,
) -> None:
    assert proc.returncode == 5, (proc.stdout, proc.stderr)
    assert downgraded_lines(proc.stdout) == [line]
    assert "would downgrade 1 package(s) already in uv.lock" in proc.stderr
    assert "original uv.lock restored" in proc.stderr
    assert "held back" not in proc.stdout
    assert (project / "uv.lock").read_bytes() == original
    assert sorted(path.name for path in project.iterdir()) == ["pyproject.toml", "uv.lock"]
    assert kinds(calls) == ["cooled", "plain", "finalize"]


@pytest.mark.parametrize(
    "plain_keeps_original", [False, True], ids=["plain-equals-cooled", "plain-keeps-original"]
)
def test_interior_fork_downgrade_exits_5_and_restores_the_original(
    tmp_path: Path, plain_keeps_original: bool
) -> None:
    # Only the middle fork goes down; the lowest and highest versions stay equal.
    proc, calls, original, project = run_fork_case(
        tmp_path,
        THREE_FORKS,
        MIDDLE_FORK_LOWERED,
        plain=THREE_FORKS if plain_keeps_original else None,
    )

    assert_fork_downgrade_refused(
        proc, calls, original, project, "downgraded: sub 1.0,2.0.2,3.0 -> 1.0,2.0.1,3.0"
    )


def test_interior_fork_downgrade_exits_5_with_an_unrelated_allow_package(tmp_path: Path) -> None:
    proc, calls, original, project = run_fork_case(
        tmp_path,
        THREE_FORKS,
        MIDDLE_FORK_LOWERED,
        "--allow-package",
        "unrelated",
        plain=THREE_FORKS,
    )

    assert "cooldown lifted for: unrelated" in proc.stdout.splitlines()
    cooled_argv = calls[0]["argv"]
    assert isinstance(cooled_argv, list)
    assert cooled_argv[3] == "--exclude-newer-package"
    assert cooled_argv[4].startswith("unrelated=")
    assert_fork_downgrade_refused(
        proc, calls, original, project, "downgraded: sub 1.0,2.0.2,3.0 -> 1.0,2.0.1,3.0"
    )


def test_versions_swapped_across_forks_exit_5(tmp_path: Path) -> None:
    before = [("dep", "3.1"), ("sub", "1.0", [PY_LT_311]), ("sub", "3.0", [PY_GE_311])]
    after = [("dep", "3.1"), ("sub", "3.0", [PY_LT_311]), ("sub", "1.0", [PY_GE_311])]

    proc, calls, original, project = run_fork_case(tmp_path, before, after)

    # Versions are listed fork by fork, so the swap stays visible.
    assert_fork_downgrade_refused(
        proc, calls, original, project, "downgraded: sub 1.0,3.0 -> 3.0,1.0"
    )


@pytest.mark.parametrize(
    ("after", "line"),
    [
        (
            [("dep", "3.1"), ("sub", "1.0", [PY_LT_312]), ("sub", "2.0", [PY_GE_312])],
            "downgraded: sub 1.0,2.0 -> 1.0,2.0",
        ),
        (
            [("dep", "3.1"), ("sub", "1.0", [PY_LT_312]), ("sub", "2.5", [PY_GE_312])],
            "downgraded: sub 1.0,2.0 -> 1.0,2.5",
        ),
    ],
    ids=["same-versions-on-new-markers", "higher-top-on-new-markers"],
)
def test_repartitioned_forks_with_a_lower_final_version_exit_5(
    tmp_path: Path, after: list[tuple[Any, ...]], line: str
) -> None:
    # Python 3.11 moves from the 2.0 fork into the 1.0 fork.
    proc, calls, original, project = run_fork_case(tmp_path, TWO_FORKS, after)

    assert_fork_downgrade_refused(proc, calls, original, project, line)
    assert REPARTITION_NOTE in proc.stderr.splitlines()


@pytest.mark.parametrize(
    "after",
    [
        [("dep", "3.1"), ("sub", "2.0", [PY_LT_312]), ("sub", "2.5", [PY_GE_312])],
        [("dep", "3.1"), ("sub", "2.0")],
        [
            ("dep", "3.1"),
            ("sub", "2.0", [PY_LT_311]),
            ("sub", "2.1", [PY_311]),
            ("sub", "3.0", [PY_GE_312]),
        ],
    ],
    ids=["new-markers", "forks-merged", "fork-added"],
)
def test_repartitioned_forks_at_or_above_every_original_version_pass(
    tmp_path: Path, after: list[tuple[Any, ...]]
) -> None:
    proc, _, _, project = run_fork_case(tmp_path, TWO_FORKS, after)

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert downgraded_lines(proc.stdout) == []
    assert lock_text(project) == render_lock(after)


@pytest.mark.parametrize(
    ("after", "line"),
    [
        (
            [("dep", "3.1"), ("sub", "1.0", [PY_LT_312]), ("sub", "3.0", [PY_GE_312])],
            "downgraded: sub 1.0,2.0.2,3.0 -> 1.0,3.0",
        ),
        ([("dep", "3.1"), ("sub", "2.0.2")], "downgraded: sub 1.0,2.0.2,3.0 -> 2.0.2"),
    ],
    ids=["two-forks-into-the-lower", "all-forks-into-one"],
)
def test_forks_collapsing_to_a_lower_version_exit_5(
    tmp_path: Path, after: list[tuple[Any, ...]], line: str
) -> None:
    proc, calls, original, project = run_fork_case(tmp_path, THREE_FORKS, after)

    assert_fork_downgrade_refused(proc, calls, original, project, line)
    assert REPARTITION_NOTE in proc.stderr.splitlines()


def test_every_fork_raised_or_kept_passes(tmp_path: Path) -> None:
    after = [
        ("dep", "3.1"),
        ("sub", "1.0", [PY_LT_311]),
        ("sub", "2.0.3", [PY_311]),
        ("sub", "3.1", [PY_GE_312]),
    ]

    proc, _, _, project = run_fork_case(tmp_path, THREE_FORKS, after)

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert downgraded_lines(proc.stdout) == []
    assert lock_text(project) == render_lock(after)


def test_unorderable_version_on_new_markers_fails_closed_with_exit_1(tmp_path: Path) -> None:
    before = [("dep", "3.1"), ("sub", "1.0", [PY_LT_311]), ("sub", "not-a-version", [PY_GE_311])]
    after = [("dep", "3.1"), ("sub", "1.0", [PY_LT_312]), ("sub", "not-a-version", [PY_GE_312])]

    proc, _, original, project = run_fork_case(tmp_path, before, after)

    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "cannot order version" in proc.stderr
    assert "original uv.lock restored" in proc.stderr
    assert (project / "uv.lock").read_bytes() == original
