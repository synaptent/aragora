#!/usr/bin/env python3
"""
Handler Test Coverage Audit Script.

Scans the handlers directory and matches against test files to generate
a coverage report in markdown format.

Usage:
    python scripts/audit_handler_coverage.py
    python scripts/audit_handler_coverage.py --output docs/HANDLER_COVERAGE_MATRIX.md
"""

from __future__ import annotations

import argparse
import ast
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class HandlerInfo:
    """Information about a handler file."""

    path: str
    name: str
    category: str
    has_test: bool
    test_path: str | None
    test_methods: int
    test_classes: int
    lines: int
    coverage_level: str  # comprehensive, moderate, minimal, stub, none


def get_category(path: str) -> str:
    """Extract category from handler path."""
    parts = path.split("/")
    if "admin" in parts:
        return "Admin & Operations"
    elif "auth" in parts:
        return "Authentication & Security"
    elif "debates" in parts or "deliberations" in path or "decision" in path:
        return "Core Debate"
    elif "features" in parts:
        return "Features"
    elif "knowledge" in parts or "mound" in parts:
        return "Knowledge Management"
    elif "social" in parts or "bots" in parts or "chat" in parts:
        return "Social & Communication"
    else:
        return "Utilities & Infrastructure"


def count_test_methods(filepath: Path) -> tuple[int, int]:
    """Count test methods and classes in a test file."""
    try:
        with open(filepath) as f:
            content = f.read()
        tree = ast.parse(content)

        classes = 0
        methods = 0

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if node.name.startswith("Test"):
                    classes += 1
            elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                if node.name.startswith("test_"):
                    methods += 1

        return classes, methods
    except Exception:
        return 0, 0


def count_lines(filepath: Path) -> int:
    """Count lines in a file."""
    try:
        with open(filepath) as f:
            return len(f.readlines())
    except Exception:
        return 0


def get_coverage_level(test_classes: int, test_methods: int, test_lines: int) -> str:
    """Determine coverage level based on test metrics."""
    if test_methods == 0:
        return "none"
    elif test_methods < 5:
        return "stub"
    elif test_methods < 15 or test_lines < 300:
        return "minimal"
    elif test_methods < 30 or test_lines < 600:
        return "moderate"
    else:
        return "comprehensive"


def find_test_file(handler_path: str, tests_dir: Path) -> Path | None:
    """Find corresponding test file for a handler."""
    # Get handler filename without extension
    handler_name = Path(handler_path).stem

    # Try various test file naming patterns
    patterns = [
        f"test_{handler_name}.py",
        f"test_{handler_name}_handler.py",
        f"test_{handler_name}s.py",
    ]

    # Check in tests/server/handlers and subdirectories
    for pattern in patterns:
        # Direct match
        test_path = tests_dir / pattern
        if test_path.exists():
            return test_path

        # Check in subdirectories matching handler structure
        for subdir in tests_dir.rglob("*"):
            if subdir.is_dir():
                potential = subdir / pattern
                if potential.exists():
                    return potential

    # Try matching based on directory structure
    handler_parts = handler_path.replace("aragora/server/handlers/", "").split("/")
    if len(handler_parts) > 1:
        subdir_path = "/".join(handler_parts[:-1])
        for pattern in patterns:
            test_path = tests_dir / subdir_path / pattern
            if test_path.exists():
                return test_path

    return None


def scan_handlers(handlers_dir: Path, tests_dir: Path) -> list[HandlerInfo]:
    """Scan all handler files and match with tests."""
    handlers = []

    for handler_path in handlers_dir.rglob("*.py"):
        # Skip __init__.py and other non-handler files
        if handler_path.name.startswith("_"):
            continue
        if handler_path.name in ["base.py", "utils.py", "helpers.py", "types.py"]:
            continue

        rel_path = str(handler_path.relative_to(handlers_dir.parent.parent.parent))
        name = handler_path.stem
        category = get_category(rel_path)
        lines = count_lines(handler_path)

        # Find test file
        test_path = find_test_file(rel_path, tests_dir)

        if test_path:
            test_classes, test_methods = count_test_methods(test_path)
            test_lines = count_lines(test_path)
            coverage_level = get_coverage_level(test_classes, test_methods, test_lines)
            handlers.append(
                HandlerInfo(
                    path=rel_path,
                    name=name,
                    category=category,
                    has_test=True,
                    test_path=str(test_path.relative_to(tests_dir.parent.parent)),
                    test_methods=test_methods,
                    test_classes=test_classes,
                    lines=lines,
                    coverage_level=coverage_level,
                )
            )
        else:
            handlers.append(
                HandlerInfo(
                    path=rel_path,
                    name=name,
                    category=category,
                    has_test=False,
                    test_path=None,
                    test_methods=0,
                    test_classes=0,
                    lines=lines,
                    coverage_level="none",
                )
            )

    return handlers


def generate_markdown_report(handlers: list[HandlerInfo]) -> str:
    """Generate markdown report from handler info."""
    # Calculate statistics
    total = len(handlers)
    tested = sum(1 for h in handlers if h.has_test)
    coverage_pct = (tested / total * 100) if total > 0 else 0

    # Count by coverage level
    by_level: defaultdict[str, int] = defaultdict(int)
    for h in handlers:
        by_level[h.coverage_level] += 1

    # Group by category
    by_category = defaultdict(list)
    for h in handlers:
        by_category[h.category].append(h)

    # Build report
    lines = [
        "# Handler Test Coverage Matrix",
        "",
        "Auto-generated report of handler test coverage.",
        "",
        "## Summary Statistics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Handlers | {total} |",
        f"| Handlers with Tests | {tested} ({coverage_pct:.1f}%) |",
        f"| Handlers without Tests | {total - tested} ({100 - coverage_pct:.1f}%) |",
        "",
        "### Coverage Levels",
        "",
        "| Level | Count | Description |",
        "|-------|-------|-------------|",
        f"| Comprehensive | {by_level['comprehensive']} | 30+ test methods, 600+ lines |",
        f"| Moderate | {by_level['moderate']} | 15-29 test methods, 300-599 lines |",
        f"| Minimal | {by_level['minimal']} | 5-14 test methods, 100-299 lines |",
        f"| Stub | {by_level['stub']} | <5 test methods |",
        f"| None | {by_level['none']} | No test file |",
        "",
    ]

    # Category summaries
    lines.extend(
        [
            "## Coverage by Category",
            "",
            "| Category | Total | Tested | Coverage | Priority |",
            "|----------|-------|--------|----------|----------|",
        ]
    )

    priority_order = {
        "Core Debate": "HIGH",
        "Authentication & Security": "HIGH",
        "Features": "CRITICAL",
        "Knowledge Management": "CRITICAL",
        "Social & Communication": "MEDIUM",
        "Admin & Operations": "MEDIUM",
        "Utilities & Infrastructure": "LOW",
    }

    for category in sorted(
        by_category.keys(),
        key=lambda c: list(priority_order.keys()).index(c) if c in priority_order else 99,
    ):
        handlers_in_cat = by_category[category]
        cat_total = len(handlers_in_cat)
        cat_tested = sum(1 for h in handlers_in_cat if h.has_test)
        cat_pct = (cat_tested / cat_total * 100) if cat_total > 0 else 0
        priority = priority_order.get(category, "LOW")
        lines.append(f"| {category} | {cat_total} | {cat_tested} | {cat_pct:.0f}% | {priority} |")

    lines.append("")

    # Detailed tables by category
    for category in sorted(by_category.keys()):
        handlers_in_cat = sorted(
            by_category[category], key=lambda h: (h.coverage_level == "none", h.name)
        )

        lines.extend(
            [
                f"## {category}",
                "",
                "| Handler | Test Status | Coverage | Test Methods | Priority |",
                "|---------|-------------|----------|--------------|----------|",
            ]
        )

        for h in handlers_in_cat:
            status = "✓" if h.has_test else "✗"
            coverage = h.coverage_level.capitalize()
            methods = str(h.test_methods) if h.test_methods > 0 else "-"
            priority = (
                "HIGH"
                if not h.has_test
                else ("LOW" if h.coverage_level in ["comprehensive", "moderate"] else "MEDIUM")
            )
            lines.append(f"| `{h.name}` | {status} | {coverage} | {methods} | {priority} |")

        lines.append("")

    # Critical gaps section
    lines.extend(
        [
            "## Critical Gaps (No Tests)",
            "",
            "Handlers without any test coverage that should be prioritized:",
            "",
        ]
    )

    untested = [h for h in handlers if not h.has_test]
    for category in sorted(set(h.category for h in untested)):
        cat_untested = [h for h in untested if h.category == category]
        if cat_untested:
            lines.append(f"### {category}")
            lines.append("")
            for h in sorted(cat_untested, key=lambda x: x.name):
                lines.append(f"- `{h.path}`")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Audit handler test coverage")
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--handlers-dir",
        type=str,
        default="aragora/server/handlers",
        help="Handlers directory",
    )
    parser.add_argument(
        "--tests-dir",
        type=str,
        default="tests/server/handlers",
        help="Tests directory",
    )
    args = parser.parse_args()

    # Find project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    handlers_dir = project_root / args.handlers_dir
    tests_dir = project_root / args.tests_dir

    if not handlers_dir.exists():
        print(f"Error: Handlers directory not found: {handlers_dir}")
        return 1

    if not tests_dir.exists():
        print(f"Error: Tests directory not found: {tests_dir}")
        return 1

    print(f"Scanning handlers in: {handlers_dir}")
    print(f"Matching tests in: {tests_dir}")

    handlers = scan_handlers(handlers_dir, tests_dir)
    report = generate_markdown_report(handlers)

    if args.output:
        output_path = project_root / args.output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            f.write(report)
        print(f"Report written to: {output_path}")
    else:
        print(report)

    return 0


if __name__ == "__main__":
    exit(main())
