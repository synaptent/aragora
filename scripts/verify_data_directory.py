#!/usr/bin/env python3
"""
Verification script for data directory consolidation.

Checks for:
1. Stray .db files in project root (should be in ARAGORA_DATA_DIR)
2. Hardcoded database paths that bypass resolve_db_path
3. Modules that need to be updated for data directory consolidation

Usage:
    python scripts/verify_data_directory.py [--check-imports] [--fix-dry-run]
"""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple


class Issue(NamedTuple):
    """Represents a verification issue."""

    severity: str  # error, warning, info
    file_path: str
    line_number: int
    message: str


def find_stray_db_files(project_root: Path) -> list[Issue]:
    """Find .db files in project root that should be in data directory."""
    issues: list[Issue] = []

    # Expected data directories
    expected_dirs = {".nomic", ".data", ".aragora", "data", "tests"}

    for db_file in project_root.glob("*.db"):
        # Skip if it's in an expected directory
        if any(str(db_file).startswith(d) for d in expected_dirs):
            continue

        issues.append(
            Issue(
                severity="warning",
                file_path=str(db_file),
                line_number=0,
                message="Stray database file in project root. Should be in ARAGORA_DATA_DIR (.nomic/)",
            )
        )

    return issues


def check_hardcoded_paths(project_root: Path) -> list[Issue]:
    """Check for hardcoded database paths in Python files."""
    issues: list[Issue] = []

    # Patterns that indicate hardcoded paths (bare filenames as defaults)
    bare_db_pattern = re.compile(
        r"""(?:db_path|database|sqlite_path)\s*[:=]\s*['"]([\w_-]+\.db)['"]""", re.IGNORECASE
    )

    # Files that should be using resolve_db_path
    aragora_dir = project_root / "aragora"

    if not aragora_dir.exists():
        return issues

    for py_file in aragora_dir.rglob("*.py"):
        try:
            content = py_file.read_text()
        except Exception:
            continue

        # Skip config/legacy.py (it defines resolve_db_path)
        if "config/legacy.py" in str(py_file):
            continue

        # Skip test files
        if "/tests/" in str(py_file) or py_file.name.startswith("test_"):
            continue

        # Check if file uses resolve_db_path
        uses_resolve = "resolve_db_path" in content

        for line_num, line in enumerate(content.split("\n"), 1):
            # Skip comments and docstrings
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue

            match = bare_db_pattern.search(line)
            if match:
                db_name = match.group(1)

                # Check if this line is in a default argument or assignment
                if "def " in line or "= " in line:
                    if not uses_resolve:
                        issues.append(
                            Issue(
                                severity="warning",
                                file_path=str(py_file.relative_to(project_root)),
                                line_number=line_num,
                                message=f"Bare database path '{db_name}' - consider using resolve_db_path()",
                            )
                        )

    return issues


def check_resolve_db_path_usage(project_root: Path) -> dict:
    """Check which modules use resolve_db_path."""
    aragora_dir = project_root / "aragora"

    if not aragora_dir.exists():
        return {"using": [], "not_using": []}

    using = []
    not_using = []

    # Modules that have database initialization
    db_init_pattern = re.compile(r"def\s+__init__.*db_path.*\.db")

    for py_file in aragora_dir.rglob("*.py"):
        try:
            content = py_file.read_text()
        except Exception:
            continue

        # Skip tests and config
        if "/tests/" in str(py_file) or "config/" in str(py_file):
            continue

        # Check if file has database initialization
        if db_init_pattern.search(content):
            rel_path = str(py_file.relative_to(project_root))
            # Check for either resolve_db_path or get_db_path (both are valid)
            if "resolve_db_path" in content or "get_db_path" in content:
                using.append(rel_path)
            else:
                not_using.append(rel_path)

    return {"using": using, "not_using": not_using}


def main():
    parser = argparse.ArgumentParser(description="Verify data directory consolidation")
    parser.add_argument(
        "--check-imports", action="store_true", help="Check which modules use resolve_db_path"
    )
    parser.add_argument(
        "--project-root", type=Path, default=Path.cwd(), help="Project root directory"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show all findings including info-level"
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()

    print(f"Verifying data directory consolidation in: {project_root}")
    print("=" * 60)

    all_issues: list[Issue] = []

    # Check for stray .db files
    print("\n1. Checking for stray .db files in project root...")
    stray_issues = find_stray_db_files(project_root)
    all_issues.extend(stray_issues)

    if stray_issues:
        print(f"   Found {len(stray_issues)} stray database file(s):")
        for issue in stray_issues:
            print(f"   - {issue.file_path}")
    else:
        print("   No stray .db files found in project root.")

    # Check for hardcoded paths
    print("\n2. Checking for hardcoded database paths...")
    hardcoded_issues = check_hardcoded_paths(project_root)
    all_issues.extend(hardcoded_issues)

    if hardcoded_issues:
        print(f"   Found {len(hardcoded_issues)} potential issue(s):")
        for issue in hardcoded_issues[:10]:  # Show first 10
            print(f"   - {issue.file_path}:{issue.line_number}: {issue.message}")
        if len(hardcoded_issues) > 10:
            print(f"   ... and {len(hardcoded_issues) - 10} more")
    else:
        print("   No hardcoded database paths found.")

    # Check resolve_db_path usage
    if args.check_imports:
        print("\n3. Checking resolve_db_path usage...")
        usage = check_resolve_db_path_usage(project_root)

        print(f"   Modules using resolve_db_path ({len(usage['using'])}):")
        for mod in usage["using"]:
            print(f"   + {mod}")

        print(f"\n   Modules NOT using resolve_db_path ({len(usage['not_using'])}):")
        for mod in usage["not_using"]:
            print(f"   - {mod}")

    # Summary
    print("\n" + "=" * 60)
    errors = [i for i in all_issues if i.severity == "error"]
    warnings = [i for i in all_issues if i.severity == "warning"]

    if errors:
        print(f"ERRORS: {len(errors)}")
    if warnings:
        print(f"WARNINGS: {len(warnings)}")

    if not errors and not warnings:
        print("All checks passed!")
        return 0
    else:
        print("\nRecommendations:")
        print("- Move stray .db files to .nomic/ directory")
        print("- Update modules to use resolve_db_path() from aragora.config")
        print("- Set ARAGORA_DATA_DIR environment variable for production")
        return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
