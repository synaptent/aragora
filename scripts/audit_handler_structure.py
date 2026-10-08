#!/usr/bin/env python3
"""Handler Structure Audit.

Identifies handlers that are NOT organized into subdirectories,
recommending candidates for consolidation.

The goal is to reduce the flat structure of 461 handler files by
grouping related handlers into domain subdirectories.

Usage:
    python scripts/audit_handler_structure.py
    python scripts/audit_handler_structure.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HANDLERS_DIR = PROJECT_ROOT / "aragora" / "server" / "handlers"


def get_handler_structure() -> dict[str, list[str]]:
    """Analyze handler directory structure.

    Returns:
        Dict mapping location type -> list of handler files
    """
    structure: dict[str, list[str]] = {
        "top_level": [],  # *.py files directly in handlers/
        "subdirectory": [],  # *.py files in handlers/<subdir>/
    }

    # Get all .py files in handlers directory (not recursive for top-level)
    for item in HANDLERS_DIR.iterdir():
        if item.is_file() and item.suffix == ".py":
            if not item.name.startswith("_"):
                structure["top_level"].append(item.name)
        elif item.is_dir() and not item.name.startswith("_"):
            # Count files in subdirectory
            for py_file in item.glob("*.py"):
                if not py_file.name.startswith("_"):
                    rel_path = f"{item.name}/{py_file.name}"
                    structure["subdirectory"].append(rel_path)

    return structure


def suggest_consolidations(top_level_files: list[str]) -> dict[str, list[str]]:
    """Suggest groupings for top-level handlers based on naming patterns.

    Returns:
        Dict mapping suggested group -> list of handler files
    """
    suggestions: dict[str, list[str]] = defaultdict(list)

    # Prefixes that suggest natural groupings
    prefix_mappings = {
        "gateway_": "gateway",
        "openclaw_": "openclaw",
        "cross_pollination": "cross_pollination",
        "gauntlet": "gauntlet",
        "workflow": "workflow",
        "oauth": "oauth",
        "email": "email",
        "audit": "audit",
        "backup": "backup",
        "rlm": "rlm",
        "a2a": "protocols",
        "scim": "enterprise",
        "ar_automation": "accounting",
        "ap_automation": "accounting",
        "expenses": "accounting",
        "invoices": "accounting",
        "code_review": "developer",
        "repository": "developer",
        "laboratory": "experimental",
    }

    for filename in sorted(top_level_files):
        base = filename.replace(".py", "")

        # Check prefix mappings
        matched = False
        for prefix, group in prefix_mappings.items():
            if base.startswith(prefix) or base == prefix:
                suggestions[group].append(filename)
                matched = True
                break

        if not matched:
            # Single-file handlers that don't fit a pattern
            suggestions["ungrouped"].append(filename)

    # Filter out groups with only 1 file (not worth creating a subdir)
    return {
        group: files
        for group, files in suggestions.items()
        if len(files) >= 2 or group == "ungrouped"
    }


def get_existing_subdirs() -> dict[str, int]:
    """Get existing handler subdirectories and their file counts."""
    subdirs: dict[str, int] = {}

    for item in HANDLERS_DIR.iterdir():
        if item.is_dir() and not item.name.startswith("_"):
            py_files = list(item.glob("*.py"))
            # Exclude __init__.py from count
            non_init = [f for f in py_files if f.name != "__init__.py"]
            subdirs[item.name] = len(non_init)

    return subdirs


def build_audit_report() -> dict[str, Any]:
    """Build comprehensive handler structure audit report."""
    structure = get_handler_structure()
    suggestions = suggest_consolidations(structure["top_level"])
    existing_subdirs = get_existing_subdirs()

    # Calculate stats
    total_top_level = len(structure["top_level"])
    total_in_subdirs = len(structure["subdirectory"])
    total_handlers = total_top_level + total_in_subdirs

    consolidation_candidates = sum(
        len(files) for group, files in suggestions.items() if group != "ungrouped"
    )

    return {
        "summary": {
            "total_handler_files": total_handlers,
            "top_level_files": total_top_level,
            "files_in_subdirectories": total_in_subdirs,
            "existing_subdirectories": len(existing_subdirs),
            "consolidation_candidates": consolidation_candidates,
            "organization_ratio": round(total_in_subdirs / total_handlers * 100, 1)
            if total_handlers
            else 0,
        },
        "existing_subdirectories": {
            name: {"file_count": count} for name, count in sorted(existing_subdirs.items())
        },
        "top_level_handlers": sorted(structure["top_level"]),
        "consolidation_suggestions": {
            group: sorted(files)
            for group, files in sorted(suggestions.items())
            if group != "ungrouped"
        },
        "ungrouped_handlers": sorted(suggestions.get("ungrouped", [])),
    }


def print_report(report: dict) -> None:
    """Print human-readable audit report."""
    s = report["summary"]

    print("=" * 70)
    print("Handler Structure Audit")
    print("=" * 70)
    print(f"Total handler files:        {s['total_handler_files']}")
    print(
        f"Files in subdirectories:    {s['files_in_subdirectories']} ({s['organization_ratio']}%)"
    )
    print(f"Top-level files:            {s['top_level_files']}")
    print(f"Existing subdirectories:    {s['existing_subdirectories']}")
    print(f"Consolidation candidates:   {s['consolidation_candidates']}")
    print()

    # Existing subdirectories
    print("-" * 70)
    print("Existing Subdirectories:")
    for name, info in report["existing_subdirectories"].items():
        print(f"  {name}/: {info['file_count']} handlers")
    print()

    # Consolidation suggestions
    if report["consolidation_suggestions"]:
        print("-" * 70)
        print("Suggested Consolidations:")
        for group, files in report["consolidation_suggestions"].items():
            print(f"\n  {group}/ ({len(files)} files):")
            for f in files:
                print(f"    - {f}")
    print()

    # Ungrouped
    ungrouped = report["ungrouped_handlers"]
    if ungrouped:
        print("-" * 70)
        print(f"Ungrouped Top-Level Handlers ({len(ungrouped)}):")
        for f in ungrouped[:30]:
            print(f"  {f}")
        if len(ungrouped) > 30:
            print(f"  ... and {len(ungrouped) - 30} more")
    print()

    print("=" * 70)
    print(f"Recommendation: Move {s['consolidation_candidates']} handlers into subdirectories")
    print("to improve organization (target: >80% in subdirectories)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit handler directory structure")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    args = parser.parse_args()

    report = build_audit_report()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
