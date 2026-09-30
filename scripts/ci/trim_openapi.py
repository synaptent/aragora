#!/usr/bin/env python3
"""Produce the reproducible, GET-only OpenAPI input for the passive DAST lane."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def read_paths(path: Path) -> list[str]:
    """Read unique absolute paths, allowing blank lines and inline # comments."""
    paths = sorted(
        {line.split("#", 1)[0].strip() for line in path.read_text(encoding="utf-8").splitlines()}
        - {""}
    )
    if not paths:
        raise ValueError("path list is empty")
    invalid = [p for p in paths if not p.startswith("/") or "{" in p or "}" in p]
    if invalid:
        raise ValueError("paths must be absolute and parameter-free: " + ", ".join(invalid))
    return paths


def trim_spec(spec: dict[str, Any], paths: list[str], server: str) -> dict[str, Any]:
    """Retain metadata, all components and exactly the requested GET operations."""
    if not isinstance(spec, dict) or not isinstance(spec.get("paths"), dict):
        raise ValueError("input must be an OpenAPI object with a paths object")
    missing = sorted(set(paths) - spec["paths"].keys())
    if missing:
        raise ValueError("listed paths missing from spec: " + ", ".join(missing))
    without_get = [
        p
        for p in paths
        if not isinstance(spec["paths"][p], dict)
        or not isinstance(spec["paths"][p].get("get"), dict)
    ]
    if without_get:
        raise ValueError("listed paths have no GET operation: " + ", ".join(without_get))
    trimmed = {key: spec[key] for key in ("openapi", "info", "components")}
    trimmed["servers"] = [{"url": server}]
    trimmed["paths"] = {path: {"get": spec["paths"][path]["get"]} for path in paths}
    return trimmed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Trim OpenAPI to listed parameter-free GET paths, preserving openapi, info "
            "and components. Paths accept blank lines and # comments; duplicates are "
            "deduplicated. JSON keys are sorted, with two-space indentation and a final newline."
        ),
        epilog=(
            "Exit codes: 0 output written (or --help); 1 invalid input, missing path/GET "
            "or file I/O error; 2 invalid command-line usage. Inputs are never overwritten."
        ),
    )
    parser.add_argument("--input", type=Path, required=True, help="Canonical OpenAPI JSON file.")
    parser.add_argument("--paths", type=Path, required=True, help="Curated GET path list.")
    parser.add_argument("--output", type=Path, required=True, help="Trimmed JSON destination.")
    parser.add_argument(
        "--server",
        default="http://localhost:8080",
        help="Replace servers with this URL (default: http://localhost:8080).",
    )
    args = parser.parse_args(argv)
    try:
        if any(
            args.output.resolve() == path.resolve()
            or (args.output.exists() and args.output.samefile(path))
            for path in (args.input, args.paths)
        ):
            raise ValueError("--output must not overwrite --input or --paths")
        paths = read_paths(args.paths)
        spec = json.loads(args.input.read_text(encoding="utf-8"))
        trimmed = trim_spec(spec, paths, args.server)
        args.output.write_text(
            json.dumps(trimmed, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (OSError, ValueError, KeyError) as exc:
        print(f"trim_openapi: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {len(paths)} GET paths to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
