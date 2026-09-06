#!/usr/bin/env python3
"""Shrink-only file-size ratchet for the aragora package.

Purpose
-------
Fails any tracked or untracked (not ignored) ``aragora/**/*.py`` file longer than ``LIMIT`` (2,000) lines
that is not recorded in the frozen adoption baseline at
``scripts/baselines/file_size_baseline.json``. It follows the same shrink-only
model as ``.mypy-baseline`` and ``scripts/ci/check_import_contracts.py``:

  * exits 0 when every oversized file is already baselined (clean origin/main);
  * exits 1 on any NEW oversized file not present in the baseline (fail-on-new),
    naming the offender so a god-file newcomer cannot land unnoticed;
  * the baseline may only shrink -- ``--freeze`` refuses to ADD entries to an
    existing baseline unless ``--adopt`` is given (initial/intentional census).

Line counting matches the way the validation contract measures a file
(``len(file_bytes.splitlines())``), so the checker, the frozen baseline, and the
contract's audit of the baseline all agree on what "over 2,000 lines" means.

Usage
-----
    python3 scripts/ci/check_file_sizes.py                  # check vs baseline
    python3 scripts/ci/check_file_sizes.py --json
    python3 scripts/ci/check_file_sizes.py --freeze --adopt # initial census
    python3 scripts/ci/check_file_sizes.py --freeze         # shrink-only re-freeze
    python3 scripts/ci/check_file_sizes.py --glob 'app/src/**/*.ts' \\
        --glob 'app/src/**/*.tsx' --baseline scripts/baselines/app-file-size.json

Exit codes
----------
    0 -- no new oversized files (clean, or only resolved files).
    1 -- one or more NEW oversized files (fail-on-new).
    2 -- a usage/environment error (missing baseline, or a shrink-only
         violation on --freeze).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# NOTE: the literal "file_size_baseline" below is greppable on purpose
# (VAL-P0-004 verifies the checker actually consults this baseline file).
BASELINE_PATH = REPO_ROOT / "scripts" / "baselines" / "file_size_baseline.json"
PACKAGE_DIR = "aragora"
LIMIT = 2000


class CheckerError(RuntimeError):
    """Raised for usage/environment errors that map to exit code 2."""


# --- Measurement ------------------------------------------------------------


def _expand_glob(pattern: str) -> list[str]:
    """Expand brace alternatives, e.g. ``*.{ts,tsx}``, before Git globbing."""
    match = re.search(r"\{([^{}]+)\}", pattern)
    if not match:
        return [pattern]
    return [
        expanded
        for choice in match[1].split(",")
        for expanded in _expand_glob(pattern[: match.start()] + choice + pattern[match.end() :])
    ]


def list_source_files(globs: list[str] | None = None) -> list[str]:
    """Return sorted tracked and untracked-not-ignored paths, relative to the repo.

    Explicit globs replace the default Python scope. Git's glob pathspec magic
    makes ``**/`` include zero or more directories, including top-level files.
    """
    paths = (
        [f":(glob){expanded}" for pattern in globs for expanded in _expand_glob(pattern)]
        if globs
        else [PACKAGE_DIR]
    )
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *paths],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(
        {path for path in result.stdout.split("\0") if path and (globs or path.endswith(".py"))}
    )


def count_lines(path: Path) -> int:
    """Line count using ``len(bytes.splitlines())`` to match the contract."""
    try:
        return len(path.read_bytes().splitlines())
    except FileNotFoundError:
        return 0


def measure_oversized(files: list[str], limit: int = LIMIT) -> dict[str, int]:
    """Map each selected file over ``limit`` lines to its line count."""
    oversized: dict[str, int] = {}
    for rel in files:
        lines = count_lines(REPO_ROOT / rel)
        if lines > limit:
            oversized[rel] = lines
    return oversized


def find_offenders(oversized: dict[str, int], baseline: set[str]) -> dict[str, int]:
    """Oversized files not present in the baseline (fail-on-new)."""
    return {path: lines for path, lines in oversized.items() if path not in baseline}


# --- Baseline I/O -----------------------------------------------------------


def load_baseline(path: Path) -> dict[str, int]:
    if not path.exists():
        raise CheckerError(
            f"baseline not found: {path}. Create it with "
            "'python3 scripts/ci/check_file_sizes.py --freeze --adopt'."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    files = data.get("files")
    if not isinstance(files, dict):
        raise CheckerError(f"malformed baseline (expected object at '.files'): {path}")
    return {str(key): int(value) for key, value in files.items()}


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def write_baseline(path: Path, oversized: dict[str, int], limit: int = LIMIT) -> None:
    # The comment intentionally avoids any "aragora/<...>.py" substring: the
    # contract extracts baselined paths with the regex /aragora\/[^"]+?\.py/
    # over the whole file, so prose mentioning such a path would be miscounted
    # as an entry. "aragora package" (no slash) is safe.
    payload = {
        "_comment": (
            "Shrink-only baseline of selected tracked and untracked (not ignored) files "
            f"longer than {limit} lines at adoption, frozen by "
            "scripts/ci/check_file_sizes.py --freeze. A NEW oversized file not "
            "listed here fails the checker (fail-on-new); this baseline may only "
            "shrink -- split a god file, re-export from its original path, then "
            "re-freeze."
        ),
        "limit": limit,
        "frozen_from_ref": _git_head(),
        "frozen_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": dict(sorted(oversized.items())),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# --- CLI --------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fail any tracked or untracked (not ignored) aragora/**/*.py file over 2,000 lines that is not "
            "recorded in the shrink-only baseline "
            "scripts/baselines/file_size_baseline.json (fail-on-new)."
        ),
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=BASELINE_PATH,
        help=("Per-app baseline path (default: scripts/baselines/file_size_baseline.json)."),
    )
    parser.add_argument(
        "--glob",
        action="append",
        metavar="PATTERN",
        help=(
            "Repository-relative Git glob (repeatable; replaces the default aragora/**/*.py "
            "scope). Quote patterns; **/ includes zero or more directories, and brace "
            "alternatives such as *.{ts,tsx} are supported. Use --baseline for a per-app census."
        ),
    )
    parser.add_argument(
        "--freeze",
        action="store_true",
        help=(
            "Recompute the oversized census and write it to the baseline. "
            "Refuses to ADD entries to an existing baseline unless --adopt is "
            "given (shrink-only guard)."
        ),
    )
    parser.add_argument(
        "--adopt",
        action="store_true",
        help="With --freeze, permit the baseline to grow (initial adoption only).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON summary to stdout.",
    )
    return parser


def _run_freeze(args: argparse.Namespace) -> int:
    oversized = measure_oversized(list_source_files(args.glob))
    if args.baseline.exists():
        existing = load_baseline(args.baseline)
        if existing == oversized:
            print(
                f"Baseline unchanged ({len(oversized)} oversized file(s) > {LIMIT} lines); "
                f"not rewritten -> {args.baseline}"
            )
            return 0
        added = sorted(set(oversized) - set(existing))
        if added and not args.adopt:
            for path in added:
                print(
                    f"REFUSED (would grow baseline): {path} ({oversized[path]} lines)",
                    file=sys.stderr,
                )
            raise CheckerError(
                "--freeze would ADD entries to the baseline (shrink-only). "
                "Split the file(s), or pass --adopt for an intentional re-adoption."
            )
    write_baseline(args.baseline, oversized)
    print(f"Froze {len(oversized)} oversized file(s) (> {LIMIT} lines) -> {args.baseline}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.freeze:
            return _run_freeze(args)
        oversized = measure_oversized(list_source_files(args.glob))
        baseline = load_baseline(args.baseline)
        offenders = find_offenders(oversized, set(baseline))
    except CheckerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    scope = ", ".join(args.glob) if args.glob else "aragora/**/*.py"
    if args.json:
        print(
            json.dumps(
                {
                    "ok": not offenders,
                    "limit": LIMIT,
                    "offenders": dict(sorted(offenders.items())),
                    "baseline_size": len(baseline),
                },
                indent=2,
            )
        )
    elif offenders:
        print(f"FAIL: {len(offenders)} {scope} file(s) over {LIMIT} lines not in the baseline:")
        for path, lines in sorted(offenders.items()):
            print(f"  NEW {path} ({lines} lines)")
        print(
            "\nSplit the file into cohesive submodules (re-export from the "
            "original path to keep imports stable), or -- only if intentional -- "
            "re-freeze with 'python3 scripts/ci/check_file_sizes.py --freeze'."
        )
    else:
        print(f"OK: no new {scope} files over {LIMIT} lines.")
        print(f"     baseline grandfathers {len(baseline)} oversized file(s).")

    return 1 if offenders else 0


if __name__ == "__main__":
    sys.exit(main())
