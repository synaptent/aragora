#!/usr/bin/env python3
"""Run mypy and filter its output through mypy-baseline.

Purpose
-------
Aragora has ~4,100 pre-existing mypy errors (see ``.mypy-baseline``). Failing
the pre-push hook on those known errors makes the gate useless -- every push
fails and automations resort to ``--no-verify``. This wrapper preserves the
hook's value by baselining existing debt and surfacing only *new* errors.

Usage
-----
Invoked from ``.pre-commit-config.yaml``. All arguments are forwarded to
mypy. Output of mypy is piped through ``mypy-baseline filter`` which removes
lines present in ``.mypy-baseline`` (the committed debt snapshot) and exits
non-zero when new errors are introduced.

Exit codes
----------
Exit code matches ``mypy-baseline filter``:
  * 0 -- no new errors, no unexpectedly fixed baseline entries
  * >0 -- new errors introduced (hook fails, pushing author must fix)

We pass ``--allow-unsynced`` so that *accidentally* fixing a baselined error
does not fail the push; the baseline is resynced explicitly via
``python scripts/ci/mypy_with_baseline.py --sync``.

Sync mode
---------
``python scripts/ci/mypy_with_baseline.py --sync`` regenerates
``.mypy-baseline`` from a fresh mypy run. Use after landing a PR that
intentionally clears a batch of existing errors.

Relocation tolerance
--------------------
``mypy-baseline filter`` matches each error's clean line (its own identity:
``path:0: severity: message  [code]``) against the baseline, so moving a file
would report every baselined error in it as new. Before filtering, errors of a
moved file are pointed back at their baselined path when the new path exists,
exactly one baselined path with the same basename is absent from the tree and
no other new error claims it. Ambiguity, copies and changed messages stay new;
relocated errors never change the exit code. Resync with ``--sync`` to rekey.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = REPO_ROOT / ".mypy-baseline"
DEFAULT_MYPY_ARGS: tuple[str, ...] = (
    "aragora/",
    "scripts/",
    "--config-file=pyproject.toml",
    "--ignore-missing-imports",
)


def _run_mypy(mypy_args: tuple[str, ...]) -> subprocess.Popen[bytes]:
    cmd = [sys.executable, "-m", "mypy", *mypy_args]
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(REPO_ROOT),
    )


FILTER_IGNORED_CATEGORIES: tuple[str, ...] = ("note",)


def _filter(mypy_proc: subprocess.Popen[bytes]) -> int:
    cmd = [
        sys.executable,
        "-m",
        "mypy_baseline",
        "filter",
        "--baseline-path",
        str(BASELINE_PATH),
        "--no-colors",
        "--allow-unsynced",
        # Notes are flaky: mypy emits overload/assignment hints whose wording
        # is not stable across runs (e.g. "__init__" vs "dict" in dict
        # overloads). We baseline them out here too so they do not register
        # as new violations.
        "--ignore-categories",
        *FILTER_IGNORED_CATEGORIES,
    ]
    assert mypy_proc.stdout is not None
    # surrogateescape keeps untouched lines byte-identical through the rewrite.
    raw_lines = mypy_proc.stdout.read().decode("utf-8", "surrogateescape")
    mypy_proc.stdout.close()
    mypy_proc.wait()
    try:
        baseline_lines = BASELINE_PATH.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        baseline_lines = []
    lines, relocations = _relocate_moved_files(
        raw_lines.splitlines(keepends=True), baseline_lines, REPO_ROOT
    )
    _print_relocations(relocations)
    filter_proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, cwd=str(REPO_ROOT))
    filter_proc.communicate("".join(lines).encode("utf-8", "surrogateescape"))
    return filter_proc.returncode


def _relocate_moved_files(
    mypy_lines: list[str], baseline_lines: list[str], tree_root: Path
) -> tuple[list[str], list[tuple[str, str, int]]]:
    """Point relocated files' errors back at their baselined path for the filter.

    Identity is mypy-baseline's own clean line (``Error.get_clean_line`` of the
    installed package, under the same options ``_filter`` passes) split into
    path and rest, so this is exactly the filter's matching with the path
    swapped. A new ``P + rest`` is relocated iff ``P`` exists under
    ``tree_root``, exactly one baselined ``Q + rest`` has ``Q != P``, the same
    basename and ``Q`` absent from the tree, and no other new line claims that
    ``Q + rest``. Up to the baselined count of such lines is replaced by the
    baseline line itself (which the filter then matches); everything else is
    passed through untouched. Returns the rewritten stream and
    ``(from_clean_line, to_clean_line, occurrences)`` per relocated identity.
    """
    # The package's own identity, not a re-implementation; these modules are
    # stable across the mypy-baseline>=0.7.4,<0.8 pin in pyproject.toml.
    from mypy_baseline._config import Config
    from mypy_baseline._error import Error

    config = Config().read_file(tree_root / "pyproject.toml")
    config.ignore_categories = list(FILTER_IGNORED_CATEGORIES)

    def split(error: Error) -> tuple[str, str] | None:
        if config.is_ignored(error.message) or config.is_ignored_category(error.category):
            return None
        path = str(Path(*error.path.parts[: config.depth])).replace("\\", "/")
        return path, error.get_clean_line(config)[len(path) :]

    # Baseline lines are already clean; one that does not round-trip through the
    # identity could never be matched by the filter either, so it is left alone.
    baselined: dict[str, int] = {}
    absent_by_rest: dict[str, list[str]] = {}
    for line in baseline_lines:
        error = Error.new(line)
        parts = split(error) if error is not None else None
        if parts is None or "".join(parts) != line:
            continue
        baselined[line] = baselined.get(line, 0) + 1
        if not (tree_root / parts[0]).exists():
            absent_by_rest.setdefault(parts[1], []).append(parts[0])

    parsed: list[tuple[str, str] | None] = []
    current: dict[tuple[str, str], int] = {}
    for line in mypy_lines:
        error = Error.new(line)
        parts = split(error) if error is not None else None
        parsed.append(parts)
        if parts is not None:
            current[parts] = current.get(parts, 0) + 1

    claims: dict[str, list[tuple[str, str]]] = {}
    for (path, rest), count in current.items():
        if count <= baselined.get(path + rest, 0) or not (tree_root / path).exists():
            continue
        candidates = {
            old
            for old in absent_by_rest.get(rest, ())
            if old != path and Path(old).name == Path(path).name
        }
        if len(candidates) == 1:
            claims.setdefault(candidates.pop() + rest, []).append((path, rest))

    target: dict[tuple[str, str], str] = {}
    budget: dict[tuple[str, str], int] = {}
    relocations: list[tuple[str, str, int]] = []
    for old, claimants in claims.items():
        if len(claimants) != 1:
            continue
        new = claimants[0]
        moved = min(current[new] - baselined.get("".join(new), 0), baselined[old])
        target[new] = old
        budget[new] = moved
        relocations.append((old, "".join(new), moved))

    rewritten: list[str] = []
    for line, parts in zip(mypy_lines, parsed):
        if parts is not None and budget.get(parts, 0) > 0:
            budget[parts] -= 1
            rewritten.append(target[parts] + "\n")
        else:
            rewritten.append(line)
    return rewritten, sorted(relocations)


def _print_relocations(relocations: list[tuple[str, str, int]]) -> None:
    if not relocations:
        return
    for old, new, _count in relocations:
        print(f"  RELOCATED {old} -> {new}")
    occurrences = sum(count for _old, _new, count in relocations)
    print(
        f"mypy-baseline: {len(relocations)} relocated error(s) ({occurrences} occurrence(s)) "
        "matched by basename after a file move; counted as baselined, not new "
        "(resync with --sync to rekey)",
        flush=True,
    )


def _sync(mypy_proc: subprocess.Popen[bytes]) -> int:
    cmd = [
        sys.executable,
        "-m",
        "mypy_baseline",
        "sync",
        "--baseline-path",
        str(BASELINE_PATH),
        "--no-colors",
        "--sort-baseline",
        "--ignore-categories",
        "note",
    ]
    assert mypy_proc.stdout is not None
    sync_proc = subprocess.Popen(cmd, stdin=mypy_proc.stdout, cwd=str(REPO_ROOT))
    mypy_proc.stdout.close()
    sync_rc = sync_proc.wait()
    mypy_proc.wait()
    return sync_rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run mypy and filter through mypy-baseline.",
        add_help=True,
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Regenerate .mypy-baseline from a fresh mypy run and exit 0.",
    )
    parser.add_argument(
        "mypy_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to mypy. Defaults to 'aragora/ scripts/ "
        "--config-file=pyproject.toml --ignore-missing-imports'.",
    )
    args = parser.parse_args(argv)

    raw_args = tuple(a for a in args.mypy_args if a != "--")
    mypy_args = raw_args or DEFAULT_MYPY_ARGS

    mypy_proc = _run_mypy(mypy_args)
    if args.sync:
        return _sync(mypy_proc)
    return _filter(mypy_proc)


if __name__ == "__main__":
    sys.exit(main())
