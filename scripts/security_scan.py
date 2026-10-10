#!/usr/bin/env python3
"""
CI-friendly security scanner wrapper.

Runs Aragora's 70+ pattern security scanner and outputs results
suitable for CI/CD pipelines with proper exit codes.

Usage:
    # Basic scan (fail on critical)
    python scripts/security_scan.py

    # Strict mode (fail on high and critical)
    python scripts/security_scan.py --strict

    # Include all severities in report
    python scripts/security_scan.py --all

    # Output JSON report
    python scripts/security_scan.py --json

    # Scan specific directory
    python scripts/security_scan.py --path aragora/server/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure aragora is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

# Colors for terminal output
RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aragora Security Scanner - CI/CD friendly",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--path",
        default="aragora/",
        help="Directory to scan (default: aragora/)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include all severities in scan (default: exclude low/info)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on HIGH severity findings (default: only fail on CRITICAL)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON report to security-report.json",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress detailed output, only show summary",
    )
    args = parser.parse_args()

    # Import scanner
    try:
        from aragora.audit.security_scanner import SecurityScanner, SecuritySeverity
    except ImportError as e:
        print(f"{RED}Error: Could not import SecurityScanner: {e}{RESET}")
        print("Make sure aragora is installed: pip install -e .")
        return 1

    # Run scan
    print(f"{BOLD}Aragora Security Scanner{RESET}")
    print(f"Scanning: {args.path}")
    print("-" * 50)

    scanner = SecurityScanner(include_low_severity=args.all)
    report = scanner.scan_directory(args.path)

    # Output JSON if requested
    if args.json:
        output_path = Path("security-report.json")
        with open(output_path, "w") as report_file:
            json.dump(report.to_dict(), report_file, indent=2, default=str)
        print(f"\nJSON report written to: {output_path}")

    # Print summary
    print(f"\n{BOLD}Scan Results:{RESET}")
    print(f"  Files scanned: {report.files_scanned}")
    print(f"  Lines scanned: {report.lines_scanned:,}")
    print(f"  Risk score: {report.risk_score:.1f}/100")
    print()

    # Print counts with colors
    if report.critical_count > 0:
        print(f"  {RED}CRITICAL: {report.critical_count}{RESET}")
    else:
        print("  CRITICAL: 0")

    if report.high_count > 0:
        print(f"  {YELLOW}HIGH: {report.high_count}{RESET}")
    else:
        print("  HIGH: 0")

    print(f"  MEDIUM: {report.medium_count}")
    print(f"  LOW: {report.low_count}")
    print(f"  INFO: {report.info_count}")

    # Print critical/high findings if not quiet
    if not args.quiet:
        critical_findings = [
            f
            for f in report.findings
            if f.severity == SecuritySeverity.CRITICAL and not f.is_false_positive
        ]
        high_findings = [
            f
            for f in report.findings
            if f.severity == SecuritySeverity.HIGH and not f.is_false_positive
        ]

        if critical_findings:
            print(f"\n{RED}{BOLD}CRITICAL Findings:{RESET}")
            for f in critical_findings[:10]:  # Limit to 10
                print(f"  {RED}•{RESET} {f.file_path}:{f.line_number}")
                print(f"    {f.title}: {f.description[:80]}...")
                if f.recommendation:
                    print(f"    {CYAN}Fix:{RESET} {f.recommendation[:80]}...")

        if high_findings and args.strict:
            print(f"\n{YELLOW}{BOLD}HIGH Findings:{RESET}")
            for f in high_findings[:10]:  # Limit to 10
                print(f"  {YELLOW}•{RESET} {f.file_path}:{f.line_number}")
                print(f"    {f.title}: {f.description[:80]}...")

    # Determine exit code
    if report.critical_count > 0:
        print(f"\n{RED}{BOLD}FAILED:{RESET} {report.critical_count} critical finding(s)")
        return 1
    elif args.strict and report.high_count > 0:
        print(f"\n{YELLOW}{BOLD}FAILED (strict):{RESET} {report.high_count} high finding(s)")
        return 1
    else:
        print(f"\n{GREEN}{BOLD}PASSED:{RESET} No critical findings")
        return 0


if __name__ == "__main__":
    sys.exit(main())
