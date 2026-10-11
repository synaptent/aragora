#!/usr/bin/env python3
"""Closure-first backpressure gate for the autonomous PR pipeline (READ-ONLY).

Writer lanes keep admitting new work regardless of how much WIP is already in
flight ("admission outruns settlement"): drafts and outbox handoffs pile up
faster than the merge arbiter can settle them. This gate computes a single
closure-first signal that writer-lane wrappers consult before generating:

- ``generate``  -- backlog is under both thresholds; writer lanes may create
  new work.
- ``shepherd``  -- backlog is at/over a threshold (or the gate itself failed);
  writer lanes should rebase/fix/evidence EXISTING PRs instead of creating
  new work.

Inputs (read-only, one ``gh`` call per run):

1. One ``gh pr list`` call (open PRs, ``--limit 300``) counted against the
   automation branch prefixes (default ``codex/``, repeatable
   ``--branch-prefix``).
2. Outbox depth: the number of ``*.json`` files directly in ``--outbox-dir``
   (default ``.aragora/automation-outbox``). A missing directory counts as 0
   with an annotation -- not an error.

Output: one JSON object on stdout (suppressed by ``--quiet``)::

    {mode, reasons[], open_prs, drafts, ready, outbox_depth, thresholds,
     generated_at, annotations[]}

and the same JSON atomically written to ``--signal-file`` (default
``.aragora/backpressure.json``; temp file + ``os.replace`` so readers never
observe a partial signal).

Exit codes (documented so shell wrappers can branch on ``$?``):

- 0 -- mode ``generate``
- 3 -- mode ``shepherd``
- 1 -- gate failure (gh error etc.). Fail closed: the signal file is still
  written with mode ``shepherd`` and reason ``gate_failure:<detail>`` before
  exiting 1, so a broken gate never green-lights more generation.

Safety model (mirrors ``pr_ready_triage.py`` / ``stale_pr_janitor.py``):
read-only against GitHub, no mutations of any kind; the only file this script
writes is its own signal file. Stdlib-only by design so it can run anywhere
``gh`` is authenticated.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from aragora.swarm.pr_value import (  # noqa: E402
    CLASS_MAINTENANCE,
    DEFAULT_MAX_MAINTENANCE_RATIO,
    DEFAULT_STALE_DAYS,
    build_value_report,
)

DEFAULT_REPO = "synaptent/aragora"
DEFAULT_BRANCH_PREFIXES = ("codex/",)
DEFAULT_OUTBOX_DIR = os.path.join(".aragora", "automation-outbox")
DEFAULT_SIGNAL_FILE = os.path.join(".aragora", "backpressure.json")
DEFAULT_MAX_OPEN_PRS = 60
DEFAULT_MAX_OUTBOX = 50
DEFAULT_WITHHELD_CLASSES = (CLASS_MAINTENANCE,)
GH_TIMEOUT_SECONDS = 120
GH_LIST_LIMIT = 300

EXIT_GENERATE = 0
EXIT_FAILURE = 1
EXIT_SHEPHERD = 3

MODE_GENERATE = "generate"
MODE_SHEPHERD = "shepherd"

_GH_LIST_FIELDS = "number,headRefName,title,labels,isDraft,createdAt,updatedAt"


# --- Inputs (read-only) -------------------------------------------------------------


def default_list_open_prs(repo: str) -> list[dict[str, Any]]:
    """One ``gh pr list`` call for open PRs (read-only, capped at 300)."""
    command = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--json",
        _GH_LIST_FIELDS,
        "--limit",
        str(GH_LIST_LIMIT),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh pr list failed (exit {result.returncode}): {result.stderr.strip()}")
    payload = json.loads(result.stdout or "[]")
    if not isinstance(payload, list):
        raise RuntimeError("gh pr list returned unexpected payload (expected a list)")
    return payload


def count_outbox_depth(outbox_dir: str) -> tuple[int, bool]:
    """Count ``*.json`` files directly in the outbox dir.

    A missing directory is (0, True) -- annotated, never an error.
    """
    if not os.path.isdir(outbox_dir):
        return 0, True
    depth = 0
    with os.scandir(outbox_dir) as entries:
        for entry in entries:
            if entry.is_file() and entry.name.endswith(".json"):
                depth += 1
    return depth, False


# --- Signal file ---------------------------------------------------------------------


def atomic_write_json(path: str, payload: dict[str, Any]) -> None:
    """Write temp + ``os.replace`` so readers never observe a partial file."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:  # never mask the primary error with a cleanup failure
            pass


# --- Gate ------------------------------------------------------------------------------


def run_gate(
    *,
    list_prs: Callable[[], list[dict[str, Any]]],
    branch_prefixes: tuple[str, ...] = DEFAULT_BRANCH_PREFIXES,
    outbox_dir: str = DEFAULT_OUTBOX_DIR,
    max_open_prs: int = DEFAULT_MAX_OPEN_PRS,
    max_outbox: int = DEFAULT_MAX_OUTBOX,
    max_maintenance_ratio: float = DEFAULT_MAX_MAINTENANCE_RATIO,
    stale_days: int = DEFAULT_STALE_DAYS,
    signal_file: str = DEFAULT_SIGNAL_FILE,
    quiet: bool = False,
    now: datetime | None = None,
    log: Callable[[str], None] = print,
) -> int:
    """Compute the gate decision, write the signal file, return the exit code.

    Fail closed: any failure (gh error, unreadable outbox) still writes the
    signal file with mode ``shepherd`` and reason ``gate_failure:<detail>``
    before returning 1, so a broken gate never green-lights more generation.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    generated_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    thresholds = {
        "max_open_prs": max_open_prs,
        "max_outbox": max_outbox,
        "max_maintenance_ratio": max_maintenance_ratio,
    }

    def emit(payload: dict[str, Any]) -> None:
        if not quiet:
            log(json.dumps(payload, sort_keys=True))

    try:
        raw_prs = list_prs()
        prs = [
            pr
            for pr in raw_prs
            if isinstance(pr, dict)
            and any(
                str(pr.get("headRefName") or "").startswith(prefix) for prefix in branch_prefixes
            )
        ]
        depth, outbox_missing = count_outbox_depth(outbox_dir)
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        detail = str(exc)[:300]
        payload: dict[str, Any] = {
            "mode": MODE_SHEPHERD,
            "reasons": [f"gate_failure:{detail}"],
            "open_prs": None,
            "drafts": None,
            "ready": None,
            "outbox_depth": None,
            "thresholds": thresholds,
            "value_composition": None,
            "generated_at": generated_at,
            "annotations": [],
        }
        try:
            atomic_write_json(signal_file, payload)
        except OSError as write_exc:
            print(
                json.dumps({"action": "signal_write_failed", "error": str(write_exc)[:300]}),
                file=sys.stderr,
            )
        emit(payload)
        print(json.dumps({"action": "gate_failure", "error": detail}), file=sys.stderr)
        return EXIT_FAILURE

    open_count = len(prs)
    drafts = sum(1 for pr in prs if bool(pr.get("isDraft")))
    ready = open_count - drafts
    value_report = build_value_report(
        prs,
        stale_days=stale_days,
        max_maintenance_ratio=max_maintenance_ratio,
        now=now,
        annotations=[],
    )

    reasons: list[str] = []
    if open_count >= max_open_prs:
        reasons.append(f"open_prs:{open_count}>=max_open_prs:{max_open_prs}")
    if depth >= max_outbox:
        reasons.append(f"outbox_depth:{depth}>=max_outbox:{max_outbox}")
    if value_report["maintenance_ratio"] > max_maintenance_ratio:
        reasons.append(
            "maintenance_ratio:"
            f"{value_report['maintenance_ratio']}>max_maintenance_ratio:{max_maintenance_ratio}"
        )

    annotations: list[str] = []
    if outbox_missing:
        annotations.append(f"outbox_dir_missing:{outbox_dir}")
    # Fail closed on a truncated listing: ``gh pr list`` truncates BEFORE the
    # branch-prefix filter, so when the raw payload hits the list limit the
    # counts above are floors and in-scope PRs may have been silently dropped.
    # A gate that cannot see the whole backlog must never green-light more
    # generation, regardless of how small the visible counts look.
    if len(raw_prs) >= GH_LIST_LIMIT:
        reasons.append(f"list_truncated:>={GH_LIST_LIMIT}")
        annotations.append(f"list_truncated:>={GH_LIST_LIMIT}")
        value_report["annotations"].append(f"list_truncated:>={GH_LIST_LIMIT}")

    mode = MODE_SHEPHERD if reasons else MODE_GENERATE
    payload = {
        "mode": mode,
        "reasons": reasons,
        "open_prs": open_count,
        "drafts": drafts,
        "ready": ready,
        "outbox_depth": depth,
        "thresholds": thresholds,
        "value_composition": value_report,
        "generated_at": generated_at,
        "annotations": annotations,
    }
    if reasons:
        payload["admission"] = {
            "withhold_classes": list(DEFAULT_WITHHELD_CLASSES),
            "source": "backlog_gate",
        }

    try:
        atomic_write_json(signal_file, payload)
    except OSError as exc:
        # The signal file is the gate's contract with writer lanes; failing to
        # write it is a gate failure (non-zero never green-lights generation).
        emit(payload)
        print(
            json.dumps({"action": "signal_write_failed", "error": str(exc)[:300]}),
            file=sys.stderr,
        )
        return EXIT_FAILURE

    emit(payload)
    return EXIT_GENERATE if mode == MODE_GENERATE else EXIT_SHEPHERD


_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def repo_arg(value: str) -> str:
    """Argparse type: validate ``owner/name`` at parse time, before any gh call."""
    if not _REPO_RE.match(value):
        raise argparse.ArgumentTypeError(f"--repo must look like owner/name, got {value!r}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Closure-first backpressure gate: exits 0 (generate) when the "
            "automation PR backlog and outbox are both under threshold, "
            "3 (shepherd) otherwise, 1 on gate failure (fail closed: the "
            "signal file is still written with mode shepherd). Read-only "
            "except its own --signal-file."
        )
    )
    parser.add_argument(
        "--repo", default=DEFAULT_REPO, type=repo_arg, help="GitHub repo (owner/name)"
    )
    parser.add_argument(
        "--branch-prefix",
        action="append",
        default=None,
        help=f"Head-branch prefix to count; repeatable (default: {list(DEFAULT_BRANCH_PREFIXES)})",
    )
    parser.add_argument(
        "--outbox-dir",
        default=DEFAULT_OUTBOX_DIR,
        help=f"Outbox directory whose direct *.json files are counted "
        f"(default {DEFAULT_OUTBOX_DIR}; missing dir counts as 0)",
    )
    parser.add_argument(
        "--max-open-prs",
        type=int,
        default=DEFAULT_MAX_OPEN_PRS,
        help=f"Open automation PR threshold (default {DEFAULT_MAX_OPEN_PRS}); "
        f"at/over this the gate says shepherd",
    )
    parser.add_argument(
        "--max-outbox",
        type=int,
        default=DEFAULT_MAX_OUTBOX,
        help=f"Outbox depth threshold (default {DEFAULT_MAX_OUTBOX}); "
        f"at/over this the gate says shepherd",
    )
    parser.add_argument(
        "--max-maintenance-ratio",
        type=float,
        default=DEFAULT_MAX_MAINTENANCE_RATIO,
        help=f"Maintenance-ratio threshold (default {DEFAULT_MAX_MAINTENANCE_RATIO}); "
        "above this the gate says shepherd",
    )
    parser.add_argument(
        "--stale-days",
        type=int,
        default=DEFAULT_STALE_DAYS,
        help=f"Open PRs older than this many days count as stale (default {DEFAULT_STALE_DAYS})",
    )
    parser.add_argument(
        "--signal-file",
        default=DEFAULT_SIGNAL_FILE,
        help=f"Path for the atomically-written signal JSON (default {DEFAULT_SIGNAL_FILE})",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress stdout JSON (signal file only)",
    )
    args = parser.parse_args(argv)

    prefixes = tuple(args.branch_prefix) if args.branch_prefix else DEFAULT_BRANCH_PREFIXES

    return run_gate(
        list_prs=lambda: default_list_open_prs(args.repo),
        branch_prefixes=prefixes,
        outbox_dir=args.outbox_dir,
        max_open_prs=args.max_open_prs,
        max_outbox=args.max_outbox,
        max_maintenance_ratio=args.max_maintenance_ratio,
        stale_days=args.stale_days,
        signal_file=args.signal_file,
        quiet=args.quiet,
    )


if __name__ == "__main__":
    sys.exit(main())
