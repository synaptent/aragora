#!/usr/bin/env python3
"""Nightly pristine-origin/main health run — the hidden-red countermeasure (epic #9039, issue #9043).

Path-gated CI shards can leave main red without any signal, and session
worktrees inflate failures ~7x, so this script runs the test suite in a
PRISTINE worktree checked out from origin/main (never a session worktree).
On red it writes the same halt marker ``scripts/merge_executor.py`` re-checks
before EVERY merge (``.aragora/merge_executor.halt``) — a human deletes the
marker after verifying main is green. Results append to the throughput ledger.

Read-only vs GitHub. Intended to run nightly under launchd (installation of
the LaunchAgent is an operator action); safe to run by hand:

    python3 scripts/pristine_main_health.py --suite required   # fast lane (default)
    python3 scripts/pristine_main_health.py --suite full       # full shards (manual)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from aragora.nomic.throughput import LedgerRecord, ThroughputLedger  # noqa: E402

DEFAULT_PRISTINE_DIR = Path.home() / ".aragora" / "pristine-main"
DEFAULT_HALT_FILE = _REPO_ROOT / ".aragora" / "merge_executor.halt"
OWNER_MARKER_PURPOSE = "aragora.pristine_main_health"
EVIDENCE_TAIL_LINES = 15
EVIDENCE_TAIL_CHARS = 4_000
INFRA_ERROR_EXIT = 2
SUITE_TERMINATION_GRACE_SECONDS = 30.0

# Suite commands run INSIDE the pristine worktree. "required" mirrors the
# steps of `make ci-required` — NOT the make target itself — with ONE swap for
# CI parity (issue #9045): the make target's raw full-codebase mypy carries
# ~1.9k errors of frozen debt and can never go green, while the actual required
# CI `typecheck` check gates touched files only. The instrument instead runs
# mypy through the shrink-only baseline checker (fails only when the count
# EXCEEDS scripts/baselines/mypy_full_baseline.json). `make ci-required` stays
# unchanged as the strict local developer contract. The checker and baseline
# are taken from THIS checkout (the instrument's own, versioned tooling) while
# every other step uses the pristine checkout's scripts, mirroring make.
# "full" runs the whole suite including path-gated shards (the ones that go
# silently red) minus the known-broken collection module.
_OPENAPI_SPEC_PATH = "/tmp/openapi_pristine_health.json"
SUITES: dict[str, list[list[str]]] = {
    "required": [
        ["ruff", "check", "aragora/", "tests/", "scripts/"],
        [
            sys.executable,
            str(_REPO_ROOT / "scripts" / "check_mypy_baseline.py"),
            "--baseline",
            str(_REPO_ROOT / "scripts" / "baselines" / "mypy_full_baseline.json"),
        ],
        [sys.executable, "scripts/check_version_alignment.py"],
        [
            sys.executable,
            "scripts/check_sdk_parity.py",
            "--strict",
            "--baseline",
            "scripts/baselines/check_sdk_parity.json",
            "--budget",
            "scripts/baselines/check_sdk_parity_budget.json",
        ],
        [
            sys.executable,
            "scripts/check_sdk_namespace_parity.py",
            "--strict",
            "--baseline",
            "scripts/baselines/check_sdk_namespace_parity.json",
        ],
        [
            sys.executable,
            "scripts/check_cross_sdk_parity.py",
            "--strict",
            "--baseline",
            "scripts/baselines/cross_sdk_parity.json",
        ],
        [
            sys.executable,
            "scripts/generate_openapi.py",
            "--output",
            _OPENAPI_SPEC_PATH,
            "--format",
            "json",
            "--quiet",
        ],
        [sys.executable, "scripts/add_openapi_operation_ids.py", "--spec", _OPENAPI_SPEC_PATH],
        [sys.executable, "scripts/add_openapi_param_descriptions.py", "--spec", _OPENAPI_SPEC_PATH],
        [sys.executable, "scripts/add_openapi_descriptions.py", "--spec", _OPENAPI_SPEC_PATH],
        [
            sys.executable,
            "scripts/verify_sdk_contracts.py",
            "--strict",
            "--baseline",
            "scripts/baselines/verify_sdk_contracts.json",
            "--extra-spec",
            _OPENAPI_SPEC_PATH,
        ],
        [
            sys.executable,
            "scripts/validate_openapi_routes.py",
            "--spec",
            _OPENAPI_SPEC_PATH,
            "--fail-on-missing",
            "--baseline",
            "scripts/baselines/validate_openapi_routes.json",
        ],
    ],
    "full": [
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/",
            "-q",
            "-p",
            "no:cacheprovider",
            "--ignore=tests/connectors",
        ]
    ],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(cmd: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def _run_suite(
    cmd: list[str],
    *,
    cwd: Path,
    timeout: float,
) -> subprocess.CompletedProcess:
    """Run a suite in its own session and reap the whole group on timeout."""
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        termination = f"sent SIGTERM to suite process group {proc.pid}"
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = proc.communicate(timeout=SUITE_TERMINATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            termination += (
                f"; still running after {SUITE_TERMINATION_GRACE_SECONDS:g}s grace; sent SIGKILL"
            )
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
        stderr_text = _stream_text(stderr)
        stderr_with_termination = "\n".join(
            part for part in (stderr_text.rstrip(), termination) if part
        )
        raise subprocess.TimeoutExpired(
            cmd,
            timeout,
            output=_stream_text(stdout),
            stderr=stderr_with_termination,
        )
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def _stream_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


def _bounded_tail(value: str | bytes | None, *, lines: int = EVIDENCE_TAIL_LINES) -> str:
    tail = "\n".join(_stream_text(value).strip().splitlines()[-lines:])
    return tail[-EVIDENCE_TAIL_CHARS:]


def _format_stream_evidence(
    *,
    stdout: str | bytes | None,
    stderr: str | bytes | None,
) -> str:
    sections: list[str] = []
    stdout_tail = _bounded_tail(stdout)
    stderr_tail = _bounded_tail(stderr)
    if stdout_tail:
        sections.append(
            f"stdout (last {EVIDENCE_TAIL_LINES} lines, <= {EVIDENCE_TAIL_CHARS} chars):\n"
            f"{stdout_tail}"
        )
    if stderr_tail:
        sections.append(
            f"stderr (last {EVIDENCE_TAIL_LINES} lines, <= {EVIDENCE_TAIL_CHARS} chars):\n"
            f"{stderr_tail}"
        )
    return "\n".join(sections) or "stdout/stderr: (empty)"


def _format_process_failure(cmd: list[str], proc: subprocess.CompletedProcess) -> str:
    evidence = _format_stream_evidence(stdout=proc.stdout, stderr=proc.stderr)
    return f"exit {proc.returncode}: {' '.join(cmd)}\n{evidence}"


# A failing suite command whose output shows the RUNNER environment is broken
# (a tool missing from PATH, a third-party dependency missing from the
# interpreter) is inconclusive about main, exactly like a timeout. A missing
# first-party module stays main_red: an unimportable ``aragora.*``/``tests``
# module on pristine main IS the red this script exists to catch, so the
# module-name check below fails closed on first-party imports.
_INFRA_OUTPUT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?m)^make(\[\d+\])?: .*(command not found|No such file or directory)"),
    re.compile(r"(?m)command not found"),
    # check_mypy_baseline.py could not produce a verdict (mypy crashed, output
    # unparsable, baseline file missing) — inconclusive, exactly like a timeout.
    re.compile(r"(?m)^MYPY_BASELINE_INFRA: .*"),
)
_MISSING_MODULE_PATTERN = re.compile(
    r"(?m)^(?:ModuleNotFoundError|ImportError): No module named ['\"]?(?P<module>[A-Za-z0-9_.]+)"
)
_FIRST_PARTY_MODULE_PREFIXES = ("aragora", "tests", "scripts")


def _infra_failure_signature(proc: subprocess.CompletedProcess) -> str | None:
    """Return the matched runner-environment signature, or None for real red."""
    output = f"{_stream_text(proc.stdout)}\n{_stream_text(proc.stderr)}"
    for pattern in _INFRA_OUTPUT_PATTERNS:
        match = pattern.search(output)
        if match:
            return match.group(0).strip()
    for match in _MISSING_MODULE_PATTERN.finditer(output):
        module = match.group("module")
        if module.split(".")[0] not in _FIRST_PARTY_MODULE_PREFIXES:
            return match.group(0).strip()
    return None


def _check_test_runtime(repo: Path) -> str | None:
    """Return bounded evidence when this interpreter cannot run pytest."""
    cmd = [sys.executable, "-c", "import pytest"]
    try:
        proc = _run(cmd, cwd=repo, timeout=60)
    except subprocess.TimeoutExpired as exc:
        evidence = _format_stream_evidence(stdout=exc.stdout, stderr=exc.stderr)
        return f"TIMEOUT after 60s: {' '.join(cmd)}\n{evidence}"
    except OSError as exc:
        return f"runtime launch failed: {' '.join(cmd)}\n{type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        return _format_process_failure(cmd, proc)
    return None


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = [int(part) for part in value.split(".")]
    padded = (parts + [0, 0])[:3]
    return padded[0], padded[1], padded[2]


def _required_mypy_requirement(
    pristine: Path,
) -> tuple[str, list[tuple[str, tuple[int, int, int]]]]:
    """Read the declared mypy spec and supported constraints from dev dependencies."""
    pyproject = pristine / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    dev_match = re.search(r"(?ms)^\s*dev\s*=\s*\[(?P<body>.*?)^\s*\]", text)
    if dev_match is None:
        raise ValueError(f"dev dependency group missing from {pyproject}")

    dependency_match = re.search(
        r"(?m)^\s*[\"']mypy(?P<specifier>\s*[<>=!~][^\"']*)[\"']\s*,?\s*(?:#.*)?$",
        dev_match.group("body"),
    )
    if dependency_match is None:
        raise ValueError(f"mypy dependency missing from {pyproject}")

    specifier = dependency_match.group("specifier").strip()
    constraints: list[tuple[str, tuple[int, int, int]]] = []
    for clause in specifier.split(","):
        constraint_match = re.fullmatch(
            r"\s*(?P<operator>==|!=|>=|<=|>|<)\s*"
            r"(?P<version>\d+(?:\.\d+){1,2})\s*",
            clause,
        )
        if constraint_match is None:
            raise ValueError(
                f"mypy dependency has unsupported constraint in {pyproject}: {specifier}"
            )
        constraints.append(
            (
                constraint_match.group("operator"),
                _version_tuple(constraint_match.group("version")),
            )
        )
    if not constraints:
        raise ValueError(f"mypy dependency has no constraints in {pyproject}: {specifier}")
    return specifier, constraints


def _mypy_version_satisfies(
    version: tuple[int, int, int],
    constraints: list[tuple[str, tuple[int, int, int]]],
) -> bool:
    comparisons = {
        "==": lambda left, right: left == right,
        "!=": lambda left, right: left != right,
        ">=": lambda left, right: left >= right,
        "<=": lambda left, right: left <= right,
        ">": lambda left, right: left > right,
        "<": lambda left, right: left < right,
    }
    return all(comparisons[operator](version, expected) for operator, expected in constraints)


def _check_required_toolchain(pristine: Path) -> str | None:
    """Return bounded evidence when PATH mypy cannot satisfy the declared requirement."""
    specifier, constraints = _required_mypy_requirement(pristine)
    mypy_path = shutil.which("mypy")
    if mypy_path is None:
        return f"required-suite mypy missing from PATH; required mypy{specifier}"

    cmd = [mypy_path, "--version"]
    try:
        proc = _run(cmd, cwd=pristine, timeout=60)
    except subprocess.TimeoutExpired as exc:
        evidence = _format_stream_evidence(stdout=exc.stdout, stderr=exc.stderr)
        return f"TIMEOUT after 60s: {' '.join(cmd)}\n{evidence}"
    except OSError as exc:
        return f"toolchain launch failed: {' '.join(cmd)}\n{type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        return _format_process_failure(cmd, proc)

    output = f"{_stream_text(proc.stdout)}\n{_stream_text(proc.stderr)}"
    version_match = re.search(r"\bmypy\s+(?P<version>\d+(?:\.\d+){1,2})\b", output, re.IGNORECASE)
    if version_match is None:
        evidence = _format_stream_evidence(stdout=proc.stdout, stderr=proc.stderr)
        return f"could not parse PATH mypy version at {mypy_path}; required mypy{specifier}\n{evidence}"

    found_text = version_match.group("version")
    if not _mypy_version_satisfies(_version_tuple(found_text), constraints):
        return (
            f"PATH mypy does not satisfy declared requirement: found {found_text} at {mypy_path}; "
            f"required mypy{specifier} from {pristine / 'pyproject.toml'}"
        )
    return None


def _record_health(
    repo: Path,
    *,
    sha: str | None,
    suite: str,
    status: str,
    failures: list[str],
    infra_errors: list[str],
) -> None:
    try:
        ledger = ThroughputLedger(repo)
        ledger.append(
            LedgerRecord(
                kind="note",
                timestamp=_now_iso(),
                data={
                    "event": "pristine_main_health",
                    "sha": sha,
                    "suite": suite,
                    "green": status == "green",
                    "status": status,
                    "failures": [failure.splitlines()[0] for failure in failures],
                    "infra_errors": infra_errors,
                },
            )
        )
    except OSError as exc:
        print(f"warning: ledger append failed: {exc}", file=sys.stderr)


def _canon(path: Path) -> str:
    return str(path.expanduser().resolve(strict=False))


def _owner_marker_path(pristine: Path) -> Path:
    return pristine.with_name(f"{pristine.name}.owner.json")


def _write_owner_marker(repo: Path, pristine: Path) -> None:
    marker = {
        "purpose": OWNER_MARKER_PURPOSE,
        "repo_root": _canon(repo),
        "pristine_dir": _canon(pristine),
        "written_at": _now_iso(),
        "written_by": "scripts/pristine_main_health.py",
    }
    _owner_marker_path(pristine).write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")


def _registered_worktree_paths(repo: Path) -> set[str]:
    listed = _run(["git", "worktree", "list", "--porcelain"], cwd=repo, timeout=60)
    if listed.returncode != 0:
        sys.exit(f"git worktree list failed: {listed.stderr.strip()[:300]}")
    paths: set[str] = set()
    for line in listed.stdout.splitlines():
        if line.startswith("worktree "):
            paths.add(_canon(Path(line.removeprefix("worktree "))))
    return paths


def _verify_script_owned_pristine(repo: Path, pristine: Path) -> None:
    marker_path = _owner_marker_path(pristine)
    if not marker_path.exists():
        sys.exit(
            "refusing to destructively refresh unmarked --pristine-dir "
            f"{pristine}; remove it or recreate it with this script"
        )
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"refusing to refresh {pristine}: invalid owner marker {marker_path}: {exc}")

    if (
        marker.get("purpose") != OWNER_MARKER_PURPOSE
        or marker.get("repo_root") != _canon(repo)
        or marker.get("pristine_dir") != _canon(pristine)
    ):
        sys.exit(f"refusing to refresh {pristine}: owner marker {marker_path} does not match")

    if _canon(pristine) not in _registered_worktree_paths(repo):
        sys.exit(f"refusing to refresh {pristine}: not a registered worktree for {repo}")


def refresh_pristine_worktree(repo: Path, pristine: Path) -> str:
    """Create or hard-refresh a detached pristine worktree at origin/main.

    Returns the checked-out commit SHA. This directory is owned by this
    script; it is never a session worktree and holds no uncommitted work.
    """
    # Explicit refspec: plain "fetch origin main" only guarantees FETCH_HEAD,
    # so the later origin/main checkout could test a stale ref and miss a
    # newly red main (#9058 openai [P1]).
    fetch = _run(
        ["git", "fetch", "origin", "+refs/heads/main:refs/remotes/origin/main"],
        cwd=repo,
        timeout=300,
    )
    if fetch.returncode != 0:
        sys.exit(f"git fetch failed: {fetch.stderr.strip()[:300]}")
    if not (pristine / ".git").exists():
        pristine.parent.mkdir(parents=True, exist_ok=True)
        add = _run(
            ["git", "worktree", "add", "--detach", str(pristine), "origin/main"],
            cwd=repo,
            timeout=300,
        )
        if add.returncode != 0:
            sys.exit(f"git worktree add failed: {add.stderr.strip()[:300]}")
        _write_owner_marker(repo, pristine)
    else:
        _verify_script_owned_pristine(repo, pristine)
        for cmd in (
            ["git", "checkout", "--detach", "origin/main"],
            ["git", "reset", "--hard", "origin/main"],
            ["git", "clean", "-fdx", "--quiet"],
        ):
            proc = _run(cmd, cwd=pristine, timeout=300)
            if proc.returncode != 0:
                sys.exit(f"pristine refresh failed ({' '.join(cmd)}): {proc.stderr.strip()[:300]}")
    sha = _run(["git", "rev-parse", "HEAD"], cwd=pristine, timeout=60)
    return sha.stdout.strip()


def write_halt_marker(halt_file: Path, *, sha: str, failures: list[str]) -> None:
    """Same marker shape merge_executor honors; human deletes after verifying green."""
    halt_file.parent.mkdir(parents=True, exist_ok=True)
    marker = {
        "reason": "main_red",
        "repo": "pristine-main-health",
        "details": [f"pristine origin/main {sha[:12]} red"] + failures[:10],
        "written_at": _now_iso(),
        "written_by": "scripts/pristine_main_health.py",
        "re_arm": "a human deletes this file after verifying main is green",
    }
    halt_file.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=_REPO_ROOT)
    parser.add_argument("--pristine-dir", type=Path, default=DEFAULT_PRISTINE_DIR)
    parser.add_argument("--halt-file", type=Path, default=DEFAULT_HALT_FILE)
    # Default is the CI-parity required lane: the full suite cannot finish
    # inside the nightly timeout budget on the launchd host (every run since
    # Jul 11 ended TIMEOUT/infra_error — issue #9045), so "full" is reserved
    # for manual or sharded use.
    parser.add_argument("--suite", choices=sorted(SUITES), default="required")
    parser.add_argument("--timeout-minutes", type=float, default=180, help="per-command timeout")
    parser.add_argument(
        "--no-halt-file",
        action="store_true",
        help="report only; never write the halt marker (for manual diagnosis)",
    )
    args = parser.parse_args(argv)

    runtime_error = _check_test_runtime(args.repo_root)
    if runtime_error:
        _record_health(
            args.repo_root,
            sha=None,
            suite=args.suite,
            status="infra_error",
            failures=[],
            infra_errors=[runtime_error],
        )
        print("INFRA_ERROR: pristine-main test runtime is unavailable:", file=sys.stderr)
        print(f"  {runtime_error}", file=sys.stderr)
        print("halt marker NOT written (infrastructure failure)", file=sys.stderr)
        return INFRA_ERROR_EXIT

    sha = refresh_pristine_worktree(args.repo_root, args.pristine_dir)
    print(f"pristine origin/main at {sha[:12]} in {args.pristine_dir}")

    failures: list[str] = []
    infra_errors: list[str] = []
    if args.suite == "required":
        try:
            toolchain_error = _check_required_toolchain(args.pristine_dir)
        except (OSError, UnicodeError, ValueError) as exc:
            # A broken toolchain *contract* (unreadable/malformed pyproject) is
            # inconclusive about main, exactly like a missing runtime: it must
            # never masquerade as a main-red test result (#9113).
            infra_errors.append(f"required-suite toolchain contract invalid: {exc}")
        else:
            if toolchain_error:
                infra_errors.append(toolchain_error)

    commands = [] if failures or infra_errors else SUITES[args.suite]
    for cmd in commands:
        print(f"running: {' '.join(cmd)}")
        try:
            proc = _run_suite(cmd, cwd=args.pristine_dir, timeout=args.timeout_minutes * 60)
        except subprocess.TimeoutExpired as exc:
            evidence = _format_stream_evidence(stdout=exc.stdout, stderr=exc.stderr)
            infra_errors.append(
                f"TIMEOUT after {args.timeout_minutes:g}m: {' '.join(cmd)}\n{evidence}"
            )
            break
        except OSError as exc:
            infra_errors.append(
                f"command launch failed: {' '.join(cmd)}\n{type(exc).__name__}: {exc}"
            )
            break
        if proc.returncode < 0:
            infra_errors.append(
                f"suite terminated by signal {-proc.returncode}: {' '.join(cmd)}\n"
                f"{_format_stream_evidence(stdout=proc.stdout, stderr=proc.stderr)}"
            )
        elif proc.returncode != 0:
            signature = _infra_failure_signature(proc)
            if signature:
                infra_errors.append(
                    f"runner environment failure ({signature}): "
                    f"{_format_process_failure(cmd, proc)}"
                )
            else:
                failures.append(_format_process_failure(cmd, proc))

    status = "infra_error" if infra_errors else "main_red" if failures else "green"
    green = status == "green"

    # SAFETY ORDER: on red, write the halt marker BEFORE any bookkeeping so an
    # unwritable ledger can never fail open (#9058 openai [P2] round 2).
    # Infrastructure failures are inconclusive about main and must never create
    # or replace a main-red marker (#9113).
    if status == "main_red" and not args.no_halt_file:
        write_halt_marker(args.halt_file, sha=sha, failures=failures)

    _record_health(
        args.repo_root,
        sha=sha,
        suite=args.suite,
        status=status,
        failures=failures,
        infra_errors=infra_errors,
    )

    if green:
        print(f"GREEN: pristine main {sha[:12]} passed suite '{args.suite}'")
        return 0

    if infra_errors:
        print(f"INFRA_ERROR: pristine main {sha[:12]} was not classified:", file=sys.stderr)
        for error in infra_errors:
            print(f"  {error}", file=sys.stderr)
        print("halt marker NOT written (infrastructure failure)", file=sys.stderr)
        return INFRA_ERROR_EXIT

    print(f"RED: pristine main {sha[:12]} failed suite '{args.suite}':", file=sys.stderr)
    for failure in failures:
        print(f"  {failure}", file=sys.stderr)
    if args.no_halt_file:
        print("halt marker NOT written (--no-halt-file)", file=sys.stderr)
    else:
        print(f"halt marker written: {args.halt_file}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
