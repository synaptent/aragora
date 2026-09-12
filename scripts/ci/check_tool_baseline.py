#!/usr/bin/env python3
"""Shrink-only baseline ratchet for any lint/type/dead-code tool.

Purpose
-------
Runs ``<command>``, parses its stdout with the parser registered for
``--tool`` (see ``scripts/ci/tool_baseline_parsers.py``), keys every finding as
``<path>::<symbol-or-line-hash>::<rule>`` (no line numbers, so unrelated edits
never surface as new findings), and compares the set against a committed JSON
baseline. New findings fail; findings that disappeared never fail. The
baseline may only shrink: ``--update`` rewrites it to the current (smaller)
set and refuses growth unless ``--allow-grow --reason "<why>"`` is given, in
which case the reason is recorded in the file.

Modelled on ``scripts/ci/check_file_sizes.py``; stdlib only so it runs in CI
before project dependencies are installed. See ``docs/RATCHETS.md``.

Usage
-----
    python scripts/ci/check_tool_baseline.py --tool ruff \\
        --baseline scripts/baselines/root-ruff-naming.json \\
        -- ruff check aragora --select N --output-format concise

    ... --update                          # shrink-only refresh
    ... --update --allow-grow --reason "adopting module X"

Baseline file
-------------
    {"tool": "ruff", "version": 1, "generated_at": "<UTC ISO>",
     "findings": {"<path>::<symbol>::<rule>": <count>, ...},
     "growth_log": [{"at": ..., "reason": ..., "added": n}]}   (optional)

Keys are sorted and paths are relative to ``--cwd`` so the file is stable
across machines and diffs.

Exit codes
----------
    0 -- no new findings (resolved/stale baseline entries are fine).
    1 -- new findings (each key is printed with the baseline path and both
         remedies), or ``--update`` refused because the set grew.
    2 -- baseline problem (unreadable file, corrupt JSON, wrong shape, tool
         mismatch, missing file without ``--update``) or a usage error.
    3 -- the tool failed to run, exited outside its clean/finding exit codes
         (even with partial findings), or signalled findings but none parsed.
         The baseline is never rewritten in this case.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tool_baseline_parsers import (  # noqa: E402
    PARSERS,
    Finding,
    ToolSpec,
    line_hash,
    supported_tools,
)

BASELINE_VERSION = 1
BASELINES_DIR = "scripts/baselines"

EXIT_OK = 0
EXIT_NEW_FINDINGS = 1
EXIT_BASELINE_ERROR = 2
EXIT_TOOL_FAILED = 3

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class BaselineError(RuntimeError):
    """Baseline read/shape/tool/JSON problem (exit 2)."""


class ToolFailed(RuntimeError):
    """The tool failed or signalled findings but none parsed (exit 3)."""


# --- Baseline I/O -----------------------------------------------------------


@dataclass
class Baseline:
    tool: str
    findings: dict[str, int]
    generated_at: str = ""
    growth_log: list[dict[str, object]] = field(default_factory=list)
    exists: bool = True

    def to_json(self) -> str:
        payload: dict[str, object] = {
            "tool": self.tool,
            "version": BASELINE_VERSION,
            "generated_at": self.generated_at,
            "findings": dict(sorted(self.findings.items())),
        }
        if self.growth_log:
            payload["growth_log"] = self.growth_log
        return json.dumps(payload, indent=2, sort_keys=False) + "\n"


def load_baseline(path: Path, tool: str) -> Baseline:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise BaselineError(f"baseline not found: {path} (create it with --update)") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise BaselineError(f"cannot read baseline: {path}: {exc}") from None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BaselineError(f"corrupt baseline (invalid JSON): {path}: {exc}") from None
    if not isinstance(data, dict):
        raise BaselineError(f"malformed baseline (top level is not an object): {path}")
    if data.get("version") != BASELINE_VERSION:
        raise BaselineError(
            f"unsupported baseline version {data.get('version')!r} "
            f"(expected {BASELINE_VERSION}): {path}"
        )
    baseline_tool = data.get("tool")
    if not isinstance(baseline_tool, str):
        raise BaselineError(f"malformed baseline (missing string field 'tool'): {path}")
    if baseline_tool != tool:
        raise BaselineError(
            f"baseline tool mismatch: baseline={baseline_tool} requested={tool}: {path}"
        )
    findings = data.get("findings")
    if not isinstance(findings, dict) or not all(
        isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)
        for k, v in findings.items()
    ):
        raise BaselineError(
            f"malformed baseline (expected object of key -> int at '.findings'): {path}"
        )
    growth_log = data.get("growth_log", [])
    if not isinstance(growth_log, list):
        raise BaselineError(f"malformed baseline ('growth_log' is not a list): {path}")
    return Baseline(
        tool=baseline_tool,
        findings=dict(findings),
        generated_at=str(data.get("generated_at", "")),
        growth_log=growth_log,
    )


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_baseline(path: Path, baseline: Baseline) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(baseline.to_json(), encoding="utf-8")


# --- Running and keying -----------------------------------------------------


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def run_tool(command: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    env = dict(os.environ)
    # Colour codes would corrupt every path-based parser; some tools honour
    # FORCE_COLOR even on a pipe, so remove it and ask for plain output.
    for var in ("FORCE_COLOR", "CLICOLOR_FORCE", "PY_COLORS"):
        env.pop(var, None)
    env["NO_COLOR"] = "1"
    try:
        proc = subprocess.run(
            list(command),
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise ToolFailed(f"tool failed to run: {exc}") from None
    return proc.returncode, strip_ansi(proc.stdout), strip_ansi(proc.stderr)


def normalize_path(raw: str, cwd: Path) -> str:
    """Make a tool-reported path POSIX and relative to ``cwd``."""
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve().relative_to(cwd.resolve())
        except ValueError:
            candidate = Path(os.path.relpath(candidate, cwd))
    posix = PurePosixPath(*candidate.parts).as_posix()
    while posix.startswith("./"):
        posix = posix[2:]
    return posix


def _symbol_from_source(cwd: Path, rel_path: str, line: int | None, fallback: str) -> str:
    if line is None or line < 1:
        return line_hash(fallback)
    try:
        with (cwd / rel_path).open(encoding="utf-8", errors="replace") as fh:
            for number, content in enumerate(fh, start=1):
                if number == line:
                    return line_hash(content)
    except OSError:
        pass
    return line_hash(fallback)


def key_findings(findings: Sequence[Finding], spec: ToolSpec, cwd: Path) -> list[Finding]:
    """Normalise paths and fill in content-hash symbols; returns keyed findings."""
    keyed: list[Finding] = []
    for finding in findings:
        rel = normalize_path(finding.path, cwd)
        symbol = finding.symbol
        if not symbol:
            if spec.symbol_from_line:
                symbol = _symbol_from_source(cwd, rel, finding.line, finding.message)
            else:
                symbol = line_hash(finding.message)
        keyed.append(
            Finding(
                path=rel,
                rule=finding.rule,
                symbol=symbol,
                line=finding.line,
                message=finding.message,
            )
        )
    return keyed


def collect_findings(
    spec: ToolSpec, command: Sequence[str], cwd: Path
) -> tuple[list[Finding], int]:
    rc, stdout, stderr = run_tool(command, cwd)
    findings = spec.parse(stdout)
    if rc not in spec.clean_exit_codes | spec.finding_exit_codes or (
        not findings and rc not in spec.clean_exit_codes
    ):
        tail = "\n".join((stderr or stdout).strip().splitlines()[-8:])
        detail = f"\n{tail}" if tail else ""
        parsed = f"{len(findings)}" if findings else "no"
        raise ToolFailed(
            f"tool exited {rc} with {parsed} parseable findings (tool failed to run?){detail}"
        )
    return key_findings(findings, spec, cwd), rc


# --- Comparison -------------------------------------------------------------


@dataclass
class Comparison:
    current: dict[str, int]
    baseline: dict[str, int]

    @property
    def new_keys(self) -> list[str]:
        return sorted(k for k, n in self.current.items() if n > self.baseline.get(k, 0))

    @property
    def resolved_keys(self) -> list[str]:
        return sorted(k for k, n in self.baseline.items() if n > self.current.get(k, 0))

    @property
    def unchanged(self) -> bool:
        return self.current == self.baseline


def count_findings(findings: Sequence[Finding]) -> dict[str, int]:
    return dict(Counter(f.key() for f in findings))


# --- CLI --------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    tools = ", ".join(supported_tools())
    parser = argparse.ArgumentParser(
        prog="check_tool_baseline.py",
        usage=(
            "%(prog)s --tool NAME --baseline PATH [--update] "
            "[--allow-grow --reason TEXT] [--report-json PATH] [--cwd DIR] "
            "-- <command...>"
        ),
        description=(
            "Run a tool, parse its findings, and fail on findings that are not "
            "in the shrink-only baseline. Everything after the `--` separator "
            "is the tool command line, run verbatim inside --cwd. "
            f"Supported --tool parsers: {tools}."
        ),
        epilog=(
            "exit codes: 0 no new findings; 1 new findings (or --update refused "
            "because the set grew); 2 baseline unreadable/corrupt/mismatched/missing "
            "or usage error; 3 tool failed to run, exited outside its clean/finding "
            "exit codes (even with partial findings), or signalled findings but "
            "none parsed (baseline never rewritten). "
            f"Baselines live in {BASELINES_DIR}/<app>-<tool>[-<variant>].json."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Not `choices=`: an unknown tool is reported after the baseline's own
    # `tool` field is compared, so a mismatch is always named as a mismatch.
    parser.add_argument(
        "--tool",
        required=True,
        metavar="NAME",
        help=f"Parser to apply to the command's stdout. One of: {tools}.",
    )
    parser.add_argument(
        "--baseline",
        required=True,
        type=Path,
        metavar="PATH",
        help="Baseline JSON to compare against (created by --update if absent).",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help=(
            "Rewrite the baseline to the current finding set. Shrink-only: refuses "
            "when new findings appear unless --allow-grow is given. Skips the "
            "rewrite when the set is unchanged so the file never churns."
        ),
    )
    parser.add_argument(
        "--allow-grow",
        action="store_true",
        help="With --update, permit the baseline to grow; requires --reason.",
    )
    parser.add_argument(
        "--reason",
        metavar="TEXT",
        help="Why the baseline is allowed to grow; recorded in the file's growth_log.",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        metavar="PATH",
        help="Write a JSON report (tool, baseline, new finding keys, counts, exit code).",
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=Path.cwd(),
        metavar="DIR",
        help="Directory to run the command in; finding paths are made relative to it.",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        metavar="-- <command...>",
        help="The tool command line, after a `--` separator.",
    )
    return parser


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("no tool command given (put it after the `--` separator)")
    args.command = command
    if args.allow_grow and not args.update:
        parser.error("--allow-grow only makes sense together with --update")
    if args.allow_grow and (not args.reason or not args.reason.strip()):
        parser.error("--allow-grow requires --reason TEXT")
    if args.reason is not None and not args.allow_grow:
        parser.error("--reason only makes sense together with --allow-grow")
    if not args.cwd.is_dir():
        parser.error(f"--cwd is not a directory: {args.cwd}")
    return args


def _write_report(
    path: Path | None,
    *,
    tool: str,
    baseline: Path,
    exit_code: int,
    new_keys: Sequence[str] = (),
    baselined: int = 0,
    resolved: int = 0,
    current_keys: int = 0,
    current_occurrences: int = 0,
    error: str | None = None,
) -> None:
    if path is None:
        return
    report: dict[str, object] = {
        "tool": tool,
        "baseline": str(baseline),
        "exit_code": exit_code,
        "new_findings": list(new_keys),
        "new_count": len(new_keys),
        "baselined_count": baselined,
        "resolved_count": resolved,
        "current_keys": current_keys,
        "current_occurrences": current_occurrences,
    }
    if error:
        report["error"] = error
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def _print_new_findings(
    tool: str, baseline_path: Path, cmp: Comparison, findings: Sequence[Finding]
) -> None:
    hints: dict[str, Finding] = {}
    for finding in findings:
        hints.setdefault(finding.key(), finding)
    print(f"{tool}: {len(cmp.new_keys)} new finding(s) not in baseline {baseline_path}:")
    for key in cmp.new_keys:
        hint = hints.get(key)
        where = ""
        if hint is not None:
            location = f"{hint.path}:{hint.line}" if hint.line else hint.path
            where = f"  ({location}: {hint.message})" if hint.message else f"  ({location})"
        delta = ""
        if cmp.baseline.get(key, 0):
            delta = f"  [count {cmp.current[key]} > baselined {cmp.baseline[key]}]"
        print(f"  NEW {key}{where}{delta}")
    print(
        "Fix the finding(s), or refresh the baseline with the same command plus:\n"
        "  --update                                   "
        "(shrink-only: refuses to add findings)\n"
        '  --update --allow-grow --reason "<why>"     '
        "(records the growth in the baseline)"
    )


def _print_summary(tool: str, cmp: Comparison) -> None:
    print(
        f"{tool}: 0 new findings ({len(cmp.baseline)} baselined, {len(cmp.resolved_keys)} resolved)"
    )
    print(
        f"{tool}: current {len(cmp.current)} key(s) / {sum(cmp.current.values())} "
        f"occurrence(s); baseline {len(cmp.baseline)} key(s) / "
        f"{sum(cmp.baseline.values())} occurrence(s)"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    baseline_path: Path = args.baseline
    cwd: Path = args.cwd

    try:
        if baseline_path.exists():
            baseline = load_baseline(baseline_path, args.tool)
        elif args.update:
            baseline = Baseline(tool=args.tool, findings={}, exists=False)
        else:
            raise BaselineError(f"baseline not found: {baseline_path} (create it with --update)")
        spec = PARSERS.get(args.tool)
        if spec is None:
            raise BaselineError(
                f"no parser registered for --tool {args.tool!r} "
                f"(supported: {', '.join(supported_tools())})"
            )
    except BaselineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        _write_report(
            args.report_json,
            tool=args.tool,
            baseline=baseline_path,
            exit_code=EXIT_BASELINE_ERROR,
            error=str(exc),
        )
        return EXIT_BASELINE_ERROR

    try:
        findings, _rc = collect_findings(spec, args.command, cwd)
    except ToolFailed as exc:
        print(f"ERROR: {args.tool}: {exc}", file=sys.stderr)
        print(f"ERROR: {args.tool}: baseline {baseline_path} left untouched", file=sys.stderr)
        _write_report(
            args.report_json,
            tool=args.tool,
            baseline=baseline_path,
            exit_code=EXIT_TOOL_FAILED,
            baselined=len(baseline.findings),
            error=str(exc),
        )
        return EXIT_TOOL_FAILED

    return check_findings(
        baseline_path,
        baseline,
        findings,
        update=args.update,
        allow_grow=args.allow_grow,
        reason=args.reason,
        report_json=args.report_json,
    )


def check_findings(
    baseline_path: Path,
    baseline: Baseline,
    findings: Sequence[Finding],
    *,
    update: bool = False,
    allow_grow: bool = False,
    reason: str | None = None,
    report_json: Path | None = None,
) -> int:
    """Apply the shared ratchet to keyed findings, including config-only checks."""
    if (allow_grow and (not update or not reason or not reason.strip())) or (
        reason is not None and not allow_grow
    ):
        raise BaselineError("growth requires --update --allow-grow --reason TEXT")
    tool = baseline.tool
    current = count_findings(findings)
    cmp = Comparison(current=current, baseline=baseline.findings)
    exit_code = EXIT_OK

    if update:
        # Initial creation (no file yet) is not growth: there is nothing to shrink from.
        grew = bool(cmp.new_keys) and baseline.exists
        if grew and not allow_grow:
            _print_new_findings(tool, baseline_path, cmp, findings)
            print(
                f"REFUSED: --update would grow {baseline_path} by "
                f"{len(cmp.new_keys)} key(s); the baseline is shrink-only. "
                'Fix the findings, or re-run with --allow-grow --reason "<why>".',
                file=sys.stderr,
            )
            exit_code = EXIT_NEW_FINDINGS
        elif cmp.unchanged and baseline.exists:
            print(f"{tool}: baseline {baseline_path} unchanged (not rewritten)")
            _print_summary(tool, cmp)
        else:
            new_baseline = Baseline(
                tool=tool,
                findings=current,
                generated_at=_utc_now(),
                growth_log=list(baseline.growth_log),
            )
            if grew:
                new_baseline.growth_log.append(
                    {
                        "at": new_baseline.generated_at,
                        "reason": reason,
                        "added": len(cmp.new_keys),
                    }
                )
            write_baseline(baseline_path, new_baseline)
            verb = "created" if not baseline.exists else ("grew" if grew else "shrank")
            print(
                f"{tool}: baseline {baseline_path} {verb}: "
                f"{len(current)} key(s) / {sum(current.values())} occurrence(s) "
                f"(was {len(baseline.findings)} key(s); "
                f"{len(cmp.new_keys)} added, {len(cmp.resolved_keys)} resolved)"
            )
    elif cmp.new_keys:
        _print_new_findings(tool, baseline_path, cmp, findings)
        exit_code = EXIT_NEW_FINDINGS
    else:
        _print_summary(tool, cmp)

    _write_report(
        report_json,
        tool=tool,
        baseline=baseline_path,
        exit_code=exit_code,
        new_keys=cmp.new_keys,
        baselined=len(baseline.findings),
        resolved=len(cmp.resolved_keys),
        current_keys=len(current),
        current_occurrences=sum(current.values()),
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
