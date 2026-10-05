#!/usr/bin/env python3
"""Inspect the public proof surface a cold reviewer sees first.

This is intentionally dependency-free. It is a fast drift check for framing,
reviewer entry points, API stability boundaries, and current execution truth.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def count_openapi_operations(relative_path: str) -> tuple[int, int] | None:
    path = ROOT / relative_path
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    paths = data.get("paths", {})
    if not isinstance(paths, dict):
        return None
    operation_count = 0
    for path_item in paths.values():
        if not isinstance(path_item, dict):
            continue
        operation_count += sum(1 for method in path_item if method.lower() in HTTP_METHODS)
    return len(paths), operation_count


def main() -> int:
    failures: list[str] = []
    facts: list[str] = []

    def require_file(relative_path: str) -> None:
        if not (ROOT / relative_path).is_file():
            failures.append(f"missing required file: {relative_path}")

    def require_contains(relative_path: str, needle: str) -> None:
        try:
            content = read_text(relative_path)
        except FileNotFoundError:
            failures.append(f"cannot inspect missing file: {relative_path}")
            return
        if needle not in content:
            failures.append(f"{relative_path} must contain: {needle!r}")

    def require_not_contains(relative_path: str, needle: str) -> None:
        try:
            content = read_text(relative_path)
        except FileNotFoundError:
            failures.append(f"cannot inspect missing file: {relative_path}")
            return
        if needle in content:
            failures.append(f"{relative_path} still contains stale text: {needle!r}")

    required_files = [
        "README.md",
        "docs/README.md",
        "docs/COLD_REVIEWER_GUIDE.md",
        "docs/api/SUPPORTED_SURFACE.md",
        "docs/CANONICAL_GOALS.md",
        "docs/THESIS.md",
        "docs/status/NEXT_STEPS_CANONICAL.md",
        "docs/status/ACTIVE_EXECUTION_ISSUES.md",
        "docs/status/B0_BENCHMARK_TRUTH_STATUS.md",
        "docs/status/TW03_RESCUE_PRODUCTIZATION_STATUS.md",
        "docs-site/docusaurus.config.js",
        "docs-site/src/pages/index.md",
        "docs-site/docs/contributing/cold-reviewer-guide.md",
        "docs-site/docs/api/supported-surface.md",
    ]
    for relative_path in required_files:
        require_file(relative_path)

    require_contains("README.md", "auditable execution control plane")
    require_contains("README.md", "docs/COLD_REVIEWER_GUIDE.md")
    require_not_contains("README.md", "github.com/an0mium/aragora")

    require_contains(
        "docs/README.md",
        "auditable execution control plane for AI-assisted decisions",
    )
    require_contains("docs/README.md", "Cold Reviewer Guide")
    require_contains("docs/README.md", "Supported API Surface")

    require_contains("docs/COLD_REVIEWER_GUIDE.md", "What Aragora Is Good For Today")
    require_contains("docs/COLD_REVIEWER_GUIDE.md", "What Is Still Aspirational")
    require_contains("docs/COLD_REVIEWER_GUIDE.md", "Fast Verification")
    require_contains("docs/api/SUPPORTED_SURFACE.md", "Stability Tiers")
    require_contains("docs/api/SUPPORTED_SURFACE.md", "Promotion Checklist")

    require_contains("docs/status/ACTIVE_EXECUTION_ISSUES.md", "Do now: `CS-01..03`")
    require_contains(
        "docs/status/ACTIVE_EXECUTION_ISSUES.md",
        "Conditional/reopen only on fresh evidence",
    )
    require_not_contains(
        "docs/status/ACTIVE_EXECUTION_ISSUES.md",
        "Do now: `BC-07..09`, `RS-11..12`",
    )

    require_contains(
        "docs-site/docusaurus.config.js",
        "Auditable execution control plane for AI-assisted decisions",
    )
    require_contains("docs-site/docusaurus.config.js", "github.com/synaptent/aragora")
    require_not_contains("docs-site/docusaurus.config.js", "github.com/aragora/aragora")
    require_not_contains("docs-site/docusaurus.config.js", "v2_4_release")
    require_not_contains("docs-site/docusaurus.config.js", "Aragora v2.4")

    require_contains("docs-site/src/pages/index.md", "Cold Reviewer Guide")
    require_contains(
        "docs-site/src/pages/index.md",
        "auditable execution control plane for AI-assisted decisions",
    )
    require_contains("docs-site/src/pages/index.md", "Supported API Surface")
    require_contains("docs-site/src/pages/index.md", "Current Boundary")

    for openapi_path in ("docs/api/openapi.json", "docs/openapi.json"):
        summary = count_openapi_operations(openapi_path)
        if summary is None:
            continue
        path_count, operation_count = summary
        facts.append(f"{openapi_path}: {path_count} paths, {operation_count} operations")
        if path_count < 10 or operation_count < 10:
            failures.append(f"{openapi_path} looks unexpectedly small")

    print("Cold-review surface inspection")
    print("=" * 30)
    for fact in facts:
        print(f"- {fact}")

    if failures:
        print("\nFailures:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nOK: public proof surface is present and internally aligned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
