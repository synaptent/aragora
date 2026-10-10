#!/usr/bin/env python3
"""Ratchet the explicit modules exempted from disallow_untyped_defs.

Uses check_tool_baseline's comparison, JSON format, and shrink-only updates.
Exit codes: 0 current set is a subset of baseline; 1 grew (added names printed);
2 baseline/config shape, I/O, or usage error. Defaults are repository-relative,
including scripts/baselines/root-mypy-overrides.json, regardless of cwd.
--report-json is also written for exit 2, with an ``error`` string.
"""

from __future__ import annotations

import argparse
import configparser
import re
import sys
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_tool_baseline import (  # noqa: E402
    EXIT_BASELINE_ERROR,
    Baseline,
    BaselineError,
    Comparison,
    Finding,
    _write_report,
    check_findings,
    count_findings,
    load_baseline,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = "scripts/baselines/root-mypy-overrides.json"
TOOL = "mypy-overrides"
RULE = "disallow_untyped_defs"
# Script module names may contain hyphens. Wildcard exemptions are not a
# finite module set and would exempt future modules without growing the ratchet.
MODULE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*")
# mypy's config_parser.convert_to_boolean keeps bools and looks every other
# value up as str(value).lower() here, so "on", "yes", "1" and 1 all mean true.
MYPY_BOOLEANS = configparser.RawConfigParser.BOOLEAN_STATES


def _mypy_boolean(path: Path, where: str, key: str, value: object) -> bool:
    if isinstance(value, bool):
        return value
    state = MYPY_BOOLEANS.get(str(value).lower())
    if state is None:
        raise BaselineError(f"{path}: {key} = {value!r} in {where} is not a mypy boolean")
    return state


def _reject_bypasses(path: Path, table: Mapping[str, object], where: str) -> None:
    """Reject the two spellings that switch the untyped-def check off for `where`."""
    if "allow_untyped_defs" in table:
        value = table["allow_untyped_defs"]
        if _mypy_boolean(path, where, "allow_untyped_defs", value):
            raise BaselineError(
                f"{path}: allow_untyped_defs = {value!r} in {where} bypasses the ratchet"
            )
    disabled_codes = table.get("disable_error_code", [])
    if isinstance(disabled_codes, str):
        disabled_codes = disabled_codes.split(",")
    if isinstance(disabled_codes, list) and any(
        isinstance(code, str) and code.strip() == "no-untyped-def" for code in disabled_codes
    ):
        raise BaselineError(
            f"{path}: disable_error_code contains no-untyped-def in {where}, "
            "which bypasses the ratchet"
        )


def overridden_modules(path: Path) -> list[str]:
    with path.open("rb") as source:
        data = tomllib.load(source)
    tool = data.get("tool", {})
    mypy = tool.get("mypy", {}) if isinstance(tool, dict) else None
    if not isinstance(mypy, dict) or mypy.get(RULE) is not True:
        raise BaselineError(f"{path}: [tool.mypy] must set {RULE} = true globally")
    _reject_bypasses(path, mypy, "[tool.mypy]")
    overrides = mypy.get("overrides", [])
    if not isinstance(overrides, list):
        raise BaselineError(f"{path}: mypy overrides must be an array of tables")
    modules: set[str] = set()
    for override in overrides:
        if not isinstance(override, dict):
            raise BaselineError(f"{path}: each mypy override must be a table")
        names = override.get("module")
        if isinstance(names, str):
            names = [names]
        if (
            not isinstance(names, list)
            or not names
            or not all(
                isinstance(name, str)
                and all(part == "*" or MODULE_NAME.fullmatch(part) for part in name.split("."))
                for name in names
            )
        ):
            raise BaselineError(f"{path}: each mypy override requires valid module names")
        _reject_bypasses(path, override, f"the override for modules {names}")
        if RULE not in override:
            continue
        if not isinstance(override[RULE], bool):
            raise BaselineError(f"{path}: {RULE} must be a boolean")
        if override[RULE]:
            continue
        if not all(MODULE_NAME.fullmatch(name) for name in names):
            raise BaselineError(f"{path}: relaxing overrides require explicit module names")
        modules.update(names)
    return sorted(modules)


def validate_baseline(baseline: Baseline) -> None:
    for key, count in baseline.findings.items():
        parts = key.split("::")
        if (
            len(parts) != 3
            or parts[0] != "pyproject.toml"
            or not MODULE_NAME.fullmatch(parts[1])
            or parts[2] != RULE
            or count != 1
        ):
            raise BaselineError("mypy baseline requires one finding per explicit module name")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Shrink-only ratchet of modules exempted from disallow_untyped_defs.",
        epilog=(
            "Exit codes: 0 current set is a subset of baseline; 1 grew (prints added "
            "module names); 2 baseline/config shape, I/O, or usage error. "
            f"Default baseline: {DEFAULT_BASELINE}. Relative paths resolve from "
            "the repository root, not cwd."
        ),
    )
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--baseline", type=Path, default=Path(DEFAULT_BASELINE))
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Write the shared runner's JSON report, also when exiting 2 (with an error field).",
    )
    parser.add_argument("--update", action="store_true", help="Create or shrink the baseline.")
    parser.add_argument(
        "--allow-grow", action="store_true", help="Allow growth with --update and --reason."
    )
    parser.add_argument("--reason", help="Reason for growth, recorded in the baseline growth_log.")
    args = parser.parse_args(argv)
    if args.allow_grow and (not args.update or not args.reason or not args.reason.strip()):
        parser.error("--allow-grow requires --update and a non-empty --reason")
    if args.reason is not None and not args.allow_grow:
        parser.error("--reason requires --allow-grow")
    project = REPO_ROOT / args.pyproject
    path = REPO_ROOT / args.baseline
    report = REPO_ROOT / args.report_json if args.report_json is not None else None
    try:
        modules = overridden_modules(project)
        baseline = (
            Baseline(tool=TOOL, findings={}, exists=False)
            if args.update and not path.exists()
            else load_baseline(path, TOOL)
        )
        validate_baseline(baseline)
        findings = [Finding(path="pyproject.toml", symbol=module, rule=RULE) for module in modules]
        comparison = Comparison(count_findings(findings), baseline.findings)
        if baseline.exists and comparison.new_keys:
            print(
                f"mypy override set grew beyond the recorded ratchet: "
                f"{len(modules)} current / {len(baseline.findings)} baseline modules; "
                f"{len(comparison.new_keys)} added module(s)"
            )
        return check_findings(
            path,
            baseline,
            findings,
            update=args.update,
            allow_grow=args.allow_grow,
            reason=args.reason,
            report_json=report,
        )
    except (BaselineError, OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        error = str(exc) or type(exc).__name__
        print(f"ERROR: {error}", file=sys.stderr)
        try:
            _write_report(
                report, tool=TOOL, baseline=path, exit_code=EXIT_BASELINE_ERROR, error=error
            )
        except OSError as report_exc:
            print(f"ERROR: cannot write --report-json {report}: {report_exc}", file=sys.stderr)
        return EXIT_BASELINE_ERROR


if __name__ == "__main__":
    sys.exit(main())
