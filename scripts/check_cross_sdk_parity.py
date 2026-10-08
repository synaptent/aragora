#!/usr/bin/env python3
"""Cross-language SDK parity check.

Extracts normalized endpoint paths from both the Python and TypeScript SDKs
and reports which paths exist in only one language.

Usage:
    python scripts/check_cross_sdk_parity.py
    python scripts/check_cross_sdk_parity.py --strict --baseline scripts/baselines/cross_sdk_parity.json
    python scripts/check_cross_sdk_parity.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from sdk_path_normalize import normalize_sdk_path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Extraction helpers (mirroring check_sdk_parity.py patterns)
# ---------------------------------------------------------------------------

_PY_PATH_RE = re.compile(r'self\._client\.(?:_request|request)\(\s*"[A-Z]+"\s*,\s*[f"]([^"]+)"')
_PY_FSTR_RE = re.compile(r'self\._client\.(?:_request|request)\(\s*"[A-Z]+"\s*,\s*f"([^"]+)"')
_TS_REQUEST_RE = re.compile(
    r"request(?:<[^(]*>)?\(\s*['\"](?:[A-Z]+)['\"]\s*,"
    r"\s*(?P<path>`[^`]+`|'[^']+'|\"[^\"]+\")"
)
_TS_DIRECT_RE = re.compile(
    r"this\.client\.(?:get|post|put|delete|patch)\("
    r"\s*(?P<path>`[^`]+`|'[^']+'|\"[^\"]+\")"
)


def _extract_python_paths() -> set[str]:
    sdk_dir = PROJECT_ROOT / "sdk" / "python" / "aragora_sdk" / "namespaces"
    if not sdk_dir.exists():
        return set()

    paths: set[str] = set()
    for py_file in sdk_dir.glob("*.py"):
        if py_file.name.startswith("_"):
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in _PY_PATH_RE.finditer(content):
            paths.add(normalize_sdk_path(m.group(1)))
        for m in _PY_FSTR_RE.finditer(content):
            paths.add(normalize_sdk_path(m.group(1)))
    return paths


def _extract_typescript_paths() -> set[str]:
    sdk_dir = PROJECT_ROOT / "sdk" / "typescript" / "src" / "namespaces"
    if not sdk_dir.exists():
        return set()

    paths: set[str] = set()
    for ts_file in sdk_dir.glob("*.ts"):
        if ts_file.name.startswith("_") or ts_file.name == "index.ts":
            continue
        try:
            content = ts_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in _TS_REQUEST_RE.finditer(content):
            raw = m.group("path")[1:-1]  # strip quotes/backticks
            paths.add(normalize_sdk_path(raw))
        for m in _TS_DIRECT_RE.finditer(content):
            raw = m.group("path")[1:-1]
            paths.add(normalize_sdk_path(raw))
    return paths


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_CONFIG_ERROR_EXIT = 2


def _config_error(message: str) -> int:
    print(f"check_cross_sdk_parity: configuration error: {message}", file=sys.stderr)
    return _CONFIG_ERROR_EXIT


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-language SDK parity check")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on regressions beyond baseline (requires --baseline)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Baseline JSON file for regression gating",
    )
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    # Resolve the baseline up front and fail loudly when it cannot be
    # resolved: silently gating against an implicitly empty baseline would
    # re-flag every grandfathered gap as a new regression.
    baseline_py_only: set[str] = set()
    baseline_ts_only: set[str] = set()
    if args.baseline is not None:
        if not args.baseline.exists():
            return _config_error(f"baseline file not found: {args.baseline}")
        try:
            data = json.loads(args.baseline.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return _config_error(f"could not load baseline {args.baseline}: {exc}")
        if not isinstance(data, dict):
            return _config_error(f"baseline {args.baseline} must be a JSON object")
        # A null value would raise an uncaught TypeError below, a string would
        # silently dissolve into a set of characters, and non-string elements
        # either crash set() (unhashable) or silently never match any path;
        # all must fail as configuration errors instead of gating against a
        # corrupted baseline.
        for key in ("python_only", "typescript_only"):
            value = data.get(key, [])
            if not isinstance(value, list):
                return _config_error(
                    f"baseline {args.baseline} key {key!r} must be a JSON array, "
                    f"got {type(value).__name__}"
                )
            if not all(isinstance(item, str) for item in value):
                return _config_error(
                    f"baseline {args.baseline} key {key!r} must be a JSON array of strings"
                )
        baseline_py_only = set(data.get("python_only", []))
        baseline_ts_only = set(data.get("typescript_only", []))
    elif args.strict:
        return _config_error(
            "--strict requires --baseline (canonical: scripts/baselines/cross_sdk_parity.json)"
        )

    py_paths = _extract_python_paths()
    ts_paths = _extract_typescript_paths()

    python_only = sorted(py_paths - ts_paths)
    typescript_only = sorted(ts_paths - py_paths)
    common = sorted(py_paths & ts_paths)

    report = {
        "python_endpoint_count": len(py_paths),
        "typescript_endpoint_count": len(ts_paths),
        "common_count": len(common),
        "python_only": python_only,
        "typescript_only": typescript_only,
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Python SDK paths:     {len(py_paths)}")
        print(f"TypeScript SDK paths: {len(ts_paths)}")
        print(f"Common:               {len(common)}")
        print(f"Python-only:          {len(python_only)}")
        print(f"TypeScript-only:      {len(typescript_only)}")

        if python_only:
            print(f"\nPython-only endpoints ({len(python_only)}):")
            for p in python_only[:20]:
                print(f"  {p}")
            if len(python_only) > 20:
                print(f"  ... and {len(python_only) - 20} more")

        if typescript_only:
            print(f"\nTypeScript-only endpoints ({len(typescript_only)}):")
            for p in typescript_only[:20]:
                print(f"  {p}")
            if len(typescript_only) > 20:
                print(f"  ... and {len(typescript_only) - 20} more")

    # Baseline regression check
    new_py_only = set(python_only) - baseline_py_only
    new_ts_only = set(typescript_only) - baseline_ts_only

    if not args.json:
        if args.baseline:
            print(
                f"\nBaseline regressions: python_only={len(new_py_only)} typescript_only={len(new_ts_only)}"
            )
            for p in sorted(new_py_only)[:10]:
                print(f"  NEW PY-ONLY: {p}")
            for p in sorted(new_ts_only)[:10]:
                print(f"  NEW TS-ONLY: {p}")

    if args.strict:
        if new_py_only or new_ts_only:
            # Under --json stdout must stay pure machine-readable JSON, so the
            # human-facing verdict line moves to stderr there.
            print(
                "\nFAILED: Cross-SDK parity regression (--strict mode)",
                file=sys.stderr if args.json else sys.stdout,
            )
            return 1
        if not args.json:
            print("\nPASS: No new cross-SDK parity regressions")

    return 0


if __name__ == "__main__":
    sys.exit(main())
