#!/usr/bin/env python3
"""Shrink-only full-codebase mypy baseline checker (issue #9045).

``make ci-required`` runs raw full-codebase mypy, which carries ~1.9k errors of
frozen historical debt; the actual required CI ``typecheck`` check gates touched
files only. This checker gives instruments (scripts/pristine_main_health.py) a
CI-parity signal for the FULL codebase without either lying green or drowning in
frozen debt: it fails only when the error count EXCEEDS the recorded baseline.

Shrink-only ratchet: when the count drops below the baseline the check passes
and reports the delta; the baseline file is never rewritten automatically.
Tighten it deliberately with ``--update-baseline`` in its own reviewed change.

The baseline count is only comparable when it is measured with a mypy that
satisfies the project's ``mypy`` requirement in ``pyproject.toml``: different
mypy releases report different errors for the same tree, so a count from an
older (or newer major) mypy is neither a regression nor a shrink.

Exit codes:
    0  error count at or below baseline (shrink reported when below)
    1  error count exceeds baseline (regression)
    2  infrastructure failure (mypy missing/crashed, mypy version outside the
       pyproject requirement, unparsable output, missing baseline) —
       inconclusive, message prefixed MYPY_BASELINE_INFRA

Usage:
    python scripts/check_mypy_baseline.py
    python scripts/check_mypy_baseline.py --baseline scripts/baselines/mypy_full_baseline.json
    python scripts/check_mypy_baseline.py --update-baseline   # deliberate tighten
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_BASELINE = _SCRIPT_DIR / "baselines" / "mypy_full_baseline.json"
DEFAULT_PYPROJECT = _SCRIPT_DIR.parent / "pyproject.toml"
DEFAULT_PATHS = ("aragora/",)
MYPY_FLAGS = ("--ignore-missing-imports",)
INFRA_EXIT = 2
INFRA_PREFIX = "MYPY_BASELINE_INFRA:"
EVIDENCE_TAIL_LINES = 20
VERSION_TIMEOUT_SECONDS = 60.0

_MYPY_REQUIREMENT = re.compile(r'(?m)^\s*"mypy(?P<spec>[<>=!~][^";]*)"')
_SPEC_CLAUSE = re.compile(r"^(?P<op>>=|<=|==|!=|<|>)\s*(?P<version>\d+(?:\.\d+)*)$")
_MYPY_VERSION = re.compile(r"\bmypy (?P<version>\d+(?:\.\d+)*)")


class InfraError(RuntimeError):
    """The mypy run itself is broken — inconclusive about the codebase."""


def _version_tuple(text: str) -> tuple[int, ...]:
    parts = [int(part) for part in text.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def required_mypy_spec(pyproject: Path) -> str:
    """Return the ``mypy`` version specifier declared in ``pyproject``."""
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError as exc:
        raise InfraError(f"cannot read the mypy requirement from {pyproject}: {exc}") from exc
    match = _MYPY_REQUIREMENT.search(text)
    if match is None:
        raise InfraError(f"no mypy version requirement found in {pyproject}")
    return match.group("spec").strip()


def version_satisfies(version: str, spec: str) -> bool:
    """Evaluate a comma-separated ``>=``/``<=``/``==``/``!=``/``<``/``>`` specifier."""
    have = _version_tuple(version)
    for clause in (part.strip() for part in spec.split(",")):
        match = _SPEC_CLAUSE.match(clause)
        if match is None:
            raise InfraError(f"unsupported mypy version specifier clause {clause!r} in {spec!r}")
        want = _version_tuple(match.group("version"))
        op = match.group("op")
        ok = {
            ">=": have >= want,
            "<=": have <= want,
            "==": have == want,
            "!=": have != want,
            "<": have < want,
            ">": have > want,
        }[op]
        if not ok:
            return False
    return True


def check_mypy_version(mypy_bin: str, spec: str, *, cwd: Path) -> str:
    """Return the mypy version, or raise InfraError when it is outside ``spec``."""
    cmd = [mypy_bin, "--version"]
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=VERSION_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InfraError(f"mypy --version failed ({type(exc).__name__}: {exc})") from exc
    match = _MYPY_VERSION.search(f"{proc.stdout}\n{proc.stderr}")
    if proc.returncode != 0 or match is None:
        raise InfraError(
            f"could not read the mypy version from {' '.join(cmd)} (exit {proc.returncode})"
        )
    version = match.group("version")
    if not version_satisfies(version, spec):
        raise InfraError(
            f"mypy {version} does not satisfy the project requirement mypy{spec}; "
            "its error count is not comparable to the baseline. Run the check with "
            "a mypy inside that range (--mypy-bin)."
        )
    return version


def _run_mypy(
    mypy_bin: str, paths: list[str], *, cwd: Path, timeout_seconds: float
) -> tuple[int, str]:
    cmd = [mypy_bin, *paths, *MYPY_FLAGS]
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise InfraError(f"mypy timed out after {timeout_seconds:g}s: {' '.join(cmd)}") from exc
    except OSError as exc:
        raise InfraError(
            f"mypy launch failed ({type(exc).__name__}: {exc}): {' '.join(cmd)}"
        ) from exc
    return proc.returncode, f"{proc.stdout}\n{proc.stderr}"


def count_errors(output: str, returncode: int) -> tuple[int, int]:
    """Parse mypy's final summary into (error_count, file_count).

    mypy exits 0 on success and 1 when errors were found; anything else
    (2 = fatal/usage error) is inconclusive infrastructure breakage.
    """
    if returncode not in (0, 1):
        tail = "\n".join(output.strip().splitlines()[-EVIDENCE_TAIL_LINES:])
        raise InfraError(f"mypy exited {returncode} (not a checked-code verdict):\n{tail}")
    if re.search(r"(?m)^Success: no issues found", output):
        return 0, 0
    summary = None
    for summary in re.finditer(
        r"(?m)^Found (?P<errors>\d+) errors? in (?P<files>\d+) files?", output
    ):
        pass  # keep the LAST summary line (mypy may emit per-daemon chatter above)
    if summary is None:
        tail = "\n".join(output.strip().splitlines()[-EVIDENCE_TAIL_LINES:])
        raise InfraError(f"could not parse mypy summary line from output:\n{tail}")
    return int(summary.group("errors")), int(summary.group("files"))


def load_baseline(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InfraError(
            f"baseline file missing: {path} (generate with --update-baseline)"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise InfraError(f"baseline file unreadable: {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("error_count"), int):
        raise InfraError(f"baseline file malformed (no integer error_count): {path}")
    return data


def write_baseline(
    path: Path, *, error_count: int, file_count: int, paths: list[str], mypy_version: str
) -> None:
    payload = {
        "comment": (
            "Shrink-only full-codebase mypy debt baseline (issue #9045). "
            "check_mypy_baseline.py fails only when the live count EXCEEDS "
            "error_count; it never rewrites this file. Tighten deliberately "
            "with --update-baseline in a reviewed change."
        ),
        "command": f"mypy {' '.join(paths)} {' '.join(MYPY_FLAGS)}",
        "error_count": error_count,
        "file_count": file_count,
        "mypy_version": mypy_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--paths", nargs="+", default=list(DEFAULT_PATHS))
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="directory to run mypy in")
    parser.add_argument("--mypy-bin", default=None, help="mypy executable (default: PATH lookup)")
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=DEFAULT_PYPROJECT,
        help="pyproject.toml whose mypy requirement the mypy version must satisfy",
    )
    parser.add_argument("--timeout-seconds", type=float, default=3600)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="rewrite the baseline to the measured count (deliberate tighten only)",
    )
    args = parser.parse_args(argv)

    try:
        mypy_bin = args.mypy_bin or shutil.which("mypy")
        if mypy_bin is None:
            raise InfraError("mypy missing from PATH")
        mypy_version = check_mypy_version(
            mypy_bin, required_mypy_spec(args.pyproject), cwd=args.root
        )
        returncode, output = _run_mypy(
            mypy_bin, args.paths, cwd=args.root, timeout_seconds=args.timeout_seconds
        )
        error_count, file_count = count_errors(output, returncode)
        if args.update_baseline:
            write_baseline(
                args.baseline,
                error_count=error_count,
                file_count=file_count,
                paths=args.paths,
                mypy_version=mypy_version,
            )
            print(
                f"baseline updated: {error_count} errors in {file_count} files -> {args.baseline}"
            )
            return 0
        baseline = load_baseline(args.baseline)
    except InfraError as exc:
        print(f"{INFRA_PREFIX} {exc}", file=sys.stderr)
        return INFRA_EXIT

    allowed = baseline["error_count"]
    if error_count > allowed:
        delta = error_count - allowed
        print(
            f"FAIL: full-codebase mypy errors grew: {error_count} > baseline {allowed} "
            f"(+{delta}). New type errors were introduced; fix them or, if the "
            f"baseline is deliberately being raised, update {args.baseline} in a "
            f"reviewed change.",
            file=sys.stderr,
        )
        tail = "\n".join(output.strip().splitlines()[-EVIDENCE_TAIL_LINES:])
        print(tail, file=sys.stderr)
        return 1
    if error_count < allowed:
        shrink = allowed - error_count
        print(
            f"PASS (shrink): full-codebase mypy errors {error_count} are {shrink} below "
            f"baseline {allowed}. Consider tightening the baseline with "
            f"--update-baseline in its own reviewed change."
        )
        return 0
    print(f"PASS: full-codebase mypy errors at baseline ({error_count}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
