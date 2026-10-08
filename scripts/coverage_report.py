#!/usr/bin/env python3
"""
Module-level coverage reporting for Aragora.

Generates coverage reports broken down by module to identify
gaps in test coverage for critical paths.

Usage:
    python scripts/coverage_report.py
    python scripts/coverage_report.py --json
    python scripts/coverage_report.py --critical-only
    python scripts/coverage_report.py --check-zero    # Fail if any module has 0% coverage
    python scripts/coverage_report.py --min-coverage 50  # Fail if overall coverage < 50%
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


# Critical modules that MUST have high coverage (80%+)
CRITICAL_MODULES = [
    "aragora/debate",
    "aragora/consensus",
    "aragora/auth",
    "aragora/rbac",
    "aragora/verification",
    "aragora/server/handlers",
    "aragora/billing",
]

# Target thresholds by tier
COVERAGE_THRESHOLDS = {
    "tier1_critical": 80,  # debate, consensus, auth, rbac, verification
    "tier2_important": 70,  # server, billing, knowledge
    "tier3_standard": 50,  # other modules
}


def run_coverage() -> dict:
    """Run pytest with coverage and return results."""
    cmd = [
        "python",
        "-m",
        "pytest",
        "tests/",
        "-m",
        "not slow and not load and not e2e",
        "--cov=aragora",
        "--cov-report=json:coverage.json",
        "--cov-report=term-missing",
        "-q",
        "--timeout=120",
    ]

    print("Running coverage analysis...")
    subprocess.run(cmd, capture_output=True, text=True)

    # Load coverage data
    coverage_file = Path("coverage.json")
    if not coverage_file.exists():
        print("Error: coverage.json not found. Run pytest with --cov first.")
        sys.exit(1)

    with open(coverage_file) as f:
        return json.load(f)


def analyze_coverage(coverage_data: dict) -> dict:
    """Analyze coverage by module."""
    files = coverage_data.get("files", {})

    module_coverage: dict[str, dict[str, Any]] = {}
    zero_coverage_files = []

    for filepath, data in files.items():
        if not filepath.startswith("aragora/"):
            continue

        # Extract module name (first two path components)
        parts = filepath.split("/")
        if len(parts) >= 2:
            module = "/".join(parts[:2])
        else:
            module = parts[0]

        if module not in module_coverage:
            module_coverage[module] = {
                "files": 0,
                "covered_lines": 0,
                "total_lines": 0,
                "missing_lines": [],
                "zero_coverage_files": [],
            }

        summary = data.get("summary", {})
        module_coverage[module]["files"] += 1
        module_coverage[module]["covered_lines"] += summary.get("covered_lines", 0)
        module_coverage[module]["total_lines"] += summary.get("num_statements", 0)

        # Track files with low coverage
        pct = summary.get("percent_covered", 0)
        if pct < 50:
            module_coverage[module]["missing_lines"].append(
                {
                    "file": filepath,
                    "coverage": pct,
                    "missing": summary.get("missing_lines", 0),
                }
            )

        # Track zero-coverage files specifically
        if pct == 0 and summary.get("num_statements", 0) > 0:
            zero_coverage_files.append(filepath)
            module_coverage[module]["zero_coverage_files"].append(filepath)

    # Calculate percentages
    for module, data in module_coverage.items():
        if data["total_lines"] > 0:
            data["percent"] = round((data["covered_lines"] / data["total_lines"]) * 100, 1)
        else:
            data["percent"] = 0

        # Determine tier
        if any(module.startswith(cm) for cm in CRITICAL_MODULES[:5]):
            data["tier"] = "tier1_critical"
            data["threshold"] = COVERAGE_THRESHOLDS["tier1_critical"]
        elif any(module.startswith(cm) for cm in CRITICAL_MODULES[5:]):
            data["tier"] = "tier2_important"
            data["threshold"] = COVERAGE_THRESHOLDS["tier2_important"]
        else:
            data["tier"] = "tier3_standard"
            data["threshold"] = COVERAGE_THRESHOLDS["tier3_standard"]

        data["passing"] = data["percent"] >= data["threshold"]

    return module_coverage


def print_report(module_coverage: dict, critical_only: bool = False) -> bool:
    """Print coverage report and return True if all thresholds met."""
    all_passing = True

    # Sort by coverage percentage
    sorted_modules = sorted(module_coverage.items(), key=lambda x: (x[1]["tier"], -x[1]["percent"]))

    print("\n" + "=" * 70)
    print("ARAGORA MODULE COVERAGE REPORT")
    print("=" * 70)

    current_tier = None
    for module, data in sorted_modules:
        if critical_only and data["tier"] == "tier3_standard":
            continue

        if data["tier"] != current_tier:
            current_tier = data["tier"]
            tier_label = {
                "tier1_critical": "TIER 1: CRITICAL (80% required)",
                "tier2_important": "TIER 2: IMPORTANT (70% required)",
                "tier3_standard": "TIER 3: STANDARD (50% required)",
            }[current_tier]
            print(f"\n{tier_label}")
            print("-" * 70)

        status = "PASS" if data["passing"] else "FAIL"
        status_icon = "\u2705" if data["passing"] else "\u274c"

        print(
            f"{status_icon} {module:40} "
            f"{data['percent']:5.1f}% ({data['covered_lines']}/{data['total_lines']}) "
            f"[{status}]"
        )

        if not data["passing"]:
            all_passing = False
            # Show worst files
            for bad_file in sorted(data["missing_lines"], key=lambda x: x["coverage"])[:3]:
                print(f"     \u2514\u2500 {bad_file['file']}: {bad_file['coverage']:.1f}%")

    print("\n" + "=" * 70)

    # Summary
    total_modules = len(module_coverage)
    passing_modules = sum(1 for m in module_coverage.values() if m["passing"])
    critical_failing = [
        m for m, d in module_coverage.items() if d["tier"] == "tier1_critical" and not d["passing"]
    ]

    print(f"SUMMARY: {passing_modules}/{total_modules} modules meeting threshold")
    if critical_failing:
        print(f"CRITICAL FAILURES: {', '.join(critical_failing)}")
        print("\nAction required: Increase test coverage for critical modules.")

    return all_passing


def check_zero_coverage(module_coverage: dict) -> list[str]:
    """Return list of all zero-coverage files."""
    zero_files = []
    for data in module_coverage.values():
        zero_files.extend(data.get("zero_coverage_files", []))
    return sorted(zero_files)


def get_overall_coverage(coverage_data: dict) -> float:
    """Calculate overall coverage percentage."""
    totals = coverage_data.get("totals", {})
    return totals.get("percent_covered", 0)


def main():
    parser = argparse.ArgumentParser(description="Generate module-level coverage report")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--critical-only", action="store_true", help="Only show critical modules")
    parser.add_argument("--no-run", action="store_true", help="Use existing coverage.json")
    parser.add_argument(
        "--check-zero",
        action="store_true",
        help="Fail if any module has zero coverage",
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=0,
        help="Minimum overall coverage percentage required",
    )
    parser.add_argument(
        "--list-zero",
        action="store_true",
        help="List all zero-coverage files",
    )
    args = parser.parse_args()

    if args.no_run:
        coverage_file = Path("coverage.json")
        if not coverage_file.exists():
            print("Error: coverage.json not found. Run without --no-run first.")
            sys.exit(1)
        with open(coverage_file) as f:
            coverage_data = json.load(f)
    else:
        coverage_data = run_coverage()

    module_coverage = analyze_coverage(coverage_data)
    overall_coverage = get_overall_coverage(coverage_data)

    # Handle --list-zero flag
    if args.list_zero:
        zero_files = check_zero_coverage(module_coverage)
        print(f"Zero-coverage files ({len(zero_files)} total):")
        for f in zero_files:
            print(f"  - {f}")
        sys.exit(0)

    if args.json:
        output = {
            "modules": module_coverage,
            "overall_coverage": overall_coverage,
            "zero_coverage_files": check_zero_coverage(module_coverage),
        }
        print(json.dumps(output, indent=2))
        sys.exit(0)

    all_passing = print_report(module_coverage, args.critical_only)

    # Print overall coverage
    print(f"\nOVERALL COVERAGE: {overall_coverage:.1f}%")

    # Check zero coverage
    zero_files = check_zero_coverage(module_coverage)
    if zero_files:
        print(f"\nZERO-COVERAGE FILES ({len(zero_files)} total):")
        for f in zero_files[:10]:  # Show first 10
            print(f"  - {f}")
        if len(zero_files) > 10:
            print(f"  ... and {len(zero_files) - 10} more")

    # Determine exit code
    exit_code = 0

    if not all_passing:
        exit_code = 1

    if args.check_zero and zero_files:
        print(f"\nERROR: {len(zero_files)} files have zero coverage!")
        exit_code = 1

    if args.min_coverage > 0 and overall_coverage < args.min_coverage:
        print(f"\nERROR: Overall coverage {overall_coverage:.1f}% < {args.min_coverage}%!")
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
