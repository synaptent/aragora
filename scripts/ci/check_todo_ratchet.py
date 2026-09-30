#!/usr/bin/env python3
"""Check root TODO/FIXME debt with the shared shrink-only baseline runner."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_tool_baseline import main as check_baseline  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = "scripts/baselines/root-todo.json"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Ratchet case-sensitive TODO/FIXME matching lines in *.py under "
            "aragora/, scripts/, tests/ (including untracked files). Scans strings "
            "as well as comments. Excludes docs/, baselines/ directories "
            "(including scripts/baselines/), and check_todo_ratchet.py itself."
        ),
        epilog=(
            "Exit codes: 0 no new findings (grep exit 1 means zero matches); "
            "1 new findings; 2 baseline/usage error; 3 grep failed to run. "
            "Missing scope directories are empty, never replaced by a broader scan. "
            "Relative baseline/report paths resolve under --cwd."
        ),
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=REPO_ROOT,
        help="Scan root (default: repository root, independent of caller cwd).",
    )
    parser.add_argument(
        "--baseline", type=Path, default=Path(DEFAULT_BASELINE), help=DEFAULT_BASELINE
    )
    parser.add_argument("--report-json", type=Path, help="Write the shared runner's JSON report.")
    parser.add_argument("--update", action="store_true", help="Create or shrink the baseline.")
    parser.add_argument("--allow-grow", action="store_true", help="Requires --update and --reason.")
    parser.add_argument("--reason", help="Reason for authorized growth, recorded in the baseline.")
    args = parser.parse_args(argv)
    cwd = args.cwd.resolve()
    runner_args = ["--tool", "todo", "--cwd", str(cwd), "--baseline", str(cwd / args.baseline)]
    if args.report_json is not None:
        runner_args.extend(["--report-json", str(cwd / args.report_json)])
    for flag in ("update", "allow_grow"):
        if getattr(args, flag):
            runner_args.append("--" + flag.replace("_", "-"))
    if args.reason is not None:
        runner_args.extend(["--reason", args.reason])
    roots = [name for name in ("aragora", "scripts", "tests") if (cwd / name).is_dir()]
    return check_baseline(
        runner_args
        + [
            "--",
            "grep",
            "-rnH",
            "--include=*.py",
            "--exclude-dir=baselines",
            "--exclude=check_todo_ratchet.py",
            "-E",
            "TODO|FIXME",
            *(roots or ["/dev/null"]),
        ]
    )


if __name__ == "__main__":
    sys.exit(main())
