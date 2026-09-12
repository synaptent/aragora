#!/usr/bin/env python3
"""Run mypy and filter its output through mypy-baseline.

Required full tier
------------------
``--baseline scripts/baselines/root-mypy-full.json`` selects the shared JSON
ratchet (check_tool_baseline), pinned to mypy 2.1.0 running on a CPython 3.11
host. mypy parses with the host interpreter's ``ast`` (``--python-version``
selects the target only), so the baseline's line attribution, and therefore its
keys, are host-parser specific; any other host is refused before mypy runs. It
checks diagnostic counts against mypy's summary before filtering, prints raw and
NEW error occurrences, and supports shrink-only ``--update`` (an unchanged
snapshot is not rewritten).
Exit codes: 0 no new errors; 1 new errors/update growth; 2 baseline/usage error;
3 wrong/missing mypy version, wrong host Python version, tool failure or
incomplete diagnostic output.
Without --baseline the legacy pre-push/.mypy-baseline interface is unchanged.

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
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_tool_baseline import (  # noqa: E402
    PARSERS,
    Baseline,
    BaselineError,
    ToolFailed,
    check_findings,
    count_findings,
    key_findings,
    load_baseline,
    run_tool,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = REPO_ROOT / ".mypy-baseline"
MYPY_VERSION = "2.1.0"
# The host major.minor that generated the JSON baseline. Must equal
# [tool.mypy] python_version, the --python-version flag in scripts/test_tiers.sh
# and the setup-python-safe pin of lint.yml's typecheck-run job.
HOST_PYTHON_VERSION = "3.11"
DEFAULT_MYPY_ARGS: tuple[str, ...] = (
    "aragora/",
    "scripts/",
    "--config-file=pyproject.toml",
    "--ignore-missing-imports",
)


def _host_python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def _json_gate(mypy_args: tuple[str, ...], baseline_path: Path, *, update: bool) -> int:
    """Validate a complete mypy run, then reuse the shared shrink-only ratchet."""
    try:
        installed = version("mypy")
        if installed != MYPY_VERSION:
            raise ToolFailed(f"mypy=={MYPY_VERSION} required; found {installed}")
        host = _host_python_version()
        if host != HOST_PYTHON_VERSION:
            raise ToolFailed(
                f"CPython {HOST_PYTHON_VERSION} host required; found {host} at {sys.executable}. "
                "mypy parses with the host interpreter's ast (--python-version selects the "
                "target only), so the baseline's line attribution and keys are specific to a "
                f"{HOST_PYTHON_VERSION} host. Run the tier under {HOST_PYTHON_VERSION}; "
                "regenerating the baseline under another host is not a fix."
            )
        baseline = (
            Baseline(tool="mypy", findings={}, exists=False)
            if update and not baseline_path.exists()
            else load_baseline(baseline_path, "mypy")
        )
        rc, stdout, stderr = run_tool([sys.executable, "-m", "mypy", *mypy_args], REPO_ROOT)
        findings = PARSERS["mypy"].parse(stdout)
        summary = re.search(r"^Found (\d+) errors? in .+$", stdout, re.MULTILINE)
        clean = re.search(r"^Success: no issues found in .+$", stdout, re.MULTILINE)
        reported = int(summary[1]) if summary else (0 if clean else None)
        if rc not in (0, 1) or reported != len(findings) or (rc == 0) != (reported == 0):
            raise ToolFailed(
                f"mypy exited {rc}; parsed {len(findings)} errors, summary {reported}."
                f"\n{stdout}\n{stderr}"
            )
        print(f"Found {len(findings)} mypy error(s) before baseline filtering.")
        keyed = key_findings(findings, PARSERS["mypy"], REPO_ROOT)
        current = count_findings(keyed)
        new_count = sum(max(0, n - baseline.findings.get(k, 0)) for k, n in current.items())
        print(f"Typecheck: {new_count} NEW errors ({len(findings) - new_count} existing errors).")
        return check_findings(baseline_path, baseline, keyed, update=update)
    except BaselineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except (ToolFailed, PackageNotFoundError) as exc:
        print(f"ERROR: mypy=={MYPY_VERSION}: {exc}", file=sys.stderr)
        return 3


def _run_mypy(mypy_args: tuple[str, ...]) -> subprocess.Popen[bytes]:
    cmd = [sys.executable, "-m", "mypy", *mypy_args]
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(REPO_ROOT),
    )


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
        "note",
    ]
    assert mypy_proc.stdout is not None
    filter_proc = subprocess.Popen(cmd, stdin=mypy_proc.stdout, cwd=str(REPO_ROOT))
    mypy_proc.stdout.close()
    filter_rc = filter_proc.wait()
    mypy_proc.wait()
    return filter_rc


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
        epilog=(
            "With --baseline: exit 0 no new errors; 1 new errors/update growth; "
            "2 baseline/usage error; 3 wrong/missing mypy, wrong host Python "
            f"(CPython {HOST_PYTHON_VERSION} required) or incomplete/failed run."
        ),
        add_help=True,
    )
    parser.add_argument("--baseline", type=Path, help="Use the shared JSON ratchet instead.")
    parser.add_argument("--update", action="store_true", help="Create/shrink the JSON baseline.")
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

    if args.baseline is not None:
        if args.sync:
            parser.error("use --update, not --sync, with a JSON --baseline")
        return _json_gate(mypy_args, REPO_ROOT / args.baseline, update=args.update)
    if args.update:
        parser.error("--update requires --baseline")
    mypy_proc = _run_mypy(mypy_args)
    if args.sync:
        return _sync(mypy_proc)
    return _filter(mypy_proc)


if __name__ == "__main__":
    sys.exit(main())
