"""
Compliance Check Example
========================
Validate a decision against compliance policies using the Aragora CLI.

Usage:
    aragora compliance export --format eu-ai-act --output compliance_report.zip

Or programmatically:
    python examples/02_compliance_check.py
"""

import subprocess
import sys


def main():
    result = subprocess.run(
        ["aragora", "compliance", "export", "--format", "eu-ai-act", "--dry-run"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("Compliance check passed")
        print(result.stdout[:500])
    else:
        print("Compliance check failed:", result.stderr[:200], file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
