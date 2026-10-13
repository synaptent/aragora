#!/usr/bin/env python3
r"""
Gmail Takeout Analyzer for Aragora Failures

For users with Advanced Protection enabled, use this script with Google Takeout exports.

Usage:
    1. Go to https://takeout.google.com
    2. Select only Gmail, choose MBOX format
    3. Download and extract the archive
    4. Run: python scripts/analyze_gmail_takeout.py --mbox /path/to/All\ mail\ Including\ Spam\ and\ Trash.mbox

This script analyzes MBOX files locally without requiring OAuth.
"""

from __future__ import annotations

import argparse
import email
import json
import mailbox
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional


@dataclass
class FailureEmail:
    """Represents a failure-related email."""

    id: str
    subject: str
    from_address: str
    date: datetime | None
    snippet: str
    failure_type: str
    severity: str
    keywords_found: list[str]


@dataclass
class FailureSummary:
    """Summary of failure emails."""

    total_emails: int
    by_type: dict[str, int]
    by_severity: dict[str, int]
    by_sender: dict[str, int]
    date_range: tuple[str, str]
    top_subjects: list[tuple[str, int]]
    emails: list[FailureEmail]


# Failure detection patterns
FAILURE_PATTERNS = {
    "error": [r"error", r"failed", r"failure", r"exception", r"crash", r"broken"],
    "test_failure": [r"test.*fail", r"pytest.*fail", r"assertion.*error", r"tests?\s+failed"],
    "ci_failure": [
        r"build\s+fail",
        r"ci\s+fail",
        r"pipeline\s+fail",
        r"github\s+actions",
        r"workflow.*fail",
    ],
    "alert": [r"alert", r"warning", r"critical", r"urgent", r"down", r"outage"],
    "exception": [r"traceback", r"stacktrace", r"unhandled\s+exception", r"runtime\s+error"],
}

SEVERITY_PATTERNS = {
    "critical": [r"critical", r"fatal", r"emergency", r"down", r"outage"],
    "high": [r"error", r"failed", r"exception", r"crash"],
    "medium": [r"warning", r"alert", r"issue"],
    "low": [r"notice", r"info", r"minor"],
}

# Strict Aragora patterns - avoid generic terms that appear in newsletters
# Terms like "debate", "consensus", "agent" cause many false positives
ARAGORA_PATTERNS_STRICT = [
    r"aragora",
    r"aragora\.ai",
    r"synaptent",
    r"nomic\s*loop",
    r"knowledge\s*mound",
    r"continuum\s*memory",
    r"elo\s*rating",  # More specific than just "elo"
]

# Python/CI patterns that indicate actual failures (not newsletter mentions)
TECHNICAL_FAILURE_PATTERNS = [
    r"traceback\s*\(",
    r"File\s+\".*\.py\"",  # Python file references
    r"line\s+\d+,\s+in\s+",  # Python traceback format
    r"pytest",
    r"AssertionError",
    r"github\s*actions.*aragora",
    r"workflow.*failed",
    r"ModuleNotFoundError",
    r"ImportError",
    r"AttributeError",
    r"TypeError",
    r"ValueError",
    r"KeyError",
]

# Combined: Must match strict Aragora OR technical failure patterns
ARAGORA_PATTERNS = ARAGORA_PATTERNS_STRICT


def get_email_body(msg: email.message.Message) -> str:
    """Extract text body from email message."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes) and payload:
                        return payload.decode("utf-8", errors="ignore")
                except Exception:
                    pass
        # Fallback to first text part
        for part in msg.walk():
            if part.get_content_maintype() == "text":
                try:
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes) and payload:
                        return payload.decode("utf-8", errors="ignore")
                except Exception:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if isinstance(payload, bytes) and payload:
                return payload.decode("utf-8", errors="ignore")
        except Exception:
            pass
    return ""


def classify_failure(subject: str, body: str) -> tuple[str, str, list[str]]:
    """Classify a failure email by type and severity."""
    text = f"{subject} {body}".lower()

    failure_type = "unknown"
    keywords_found = []

    for ftype, patterns in FAILURE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                failure_type = ftype
                keywords_found.append(pattern)
                break
        if failure_type != "unknown":
            break

    severity = "medium"
    for sev, patterns in SEVERITY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                severity = sev
                break
        if severity != "medium":
            break

    return failure_type, severity, keywords_found


def is_aragora_related(subject: str, body: str) -> bool:
    """Check if email is Aragora-related.

    Uses strict patterns to avoid false positives from newsletters.
    Returns True if:
    - Email contains strict Aragora terms (aragora, synaptent, nomic loop, etc.)
    - OR email contains Python/CI failure patterns (tracebacks, pytest, etc.)
    """
    text = f"{subject} {body}"

    # Check strict Aragora patterns
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in ARAGORA_PATTERNS_STRICT):
        return True

    # Check technical failure patterns (Python tracebacks, CI failures)
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in TECHNICAL_FAILURE_PATTERNS):
        return True

    return False


def is_failure_related(subject: str, body: str) -> bool:
    """Check if email is failure-related."""
    text = f"{subject} {body}".lower()
    for patterns in FAILURE_PATTERNS.values():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
    return False


def parse_date(date_str: str | None) -> datetime | None:
    """Parse email date string."""
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return None


def analyze_mbox(
    mbox_path: str,
    days_back: int = 60,
    max_results: int = 10000,
) -> list[FailureEmail]:
    """Analyze MBOX file for Aragora failure emails."""
    print(f"\nAnalyzing MBOX file: {mbox_path}")

    if not Path(mbox_path).exists():
        print(f"ERROR: File not found: {mbox_path}")
        return []

    cutoff_date = datetime.now().astimezone() - __import__("datetime").timedelta(days=days_back)

    mbox = mailbox.mbox(mbox_path)
    failures: list[FailureEmail] = []
    total_scanned = 0

    print(f"Scanning for Aragora failure emails (last {days_back} days)...")

    for i, msg in enumerate(mbox):
        total_scanned += 1

        if total_scanned % 1000 == 0:
            print(f"  Scanned {total_scanned} emails, found {len(failures)} failures...")

        if len(failures) >= max_results:
            break

        # Get basic info
        subject = msg.get("Subject", "") or ""
        from_addr = msg.get("From", "") or ""
        date_str = msg.get("Date")
        date = parse_date(date_str)

        # Filter by date
        if date and date < cutoff_date:
            continue

        # Get body
        body = get_email_body(msg)

        # Check if Aragora and failure related
        if not is_aragora_related(subject, body):
            continue
        if not is_failure_related(subject, body):
            continue

        # Classify
        failure_type, severity, keywords = classify_failure(subject, body)

        failures.append(
            FailureEmail(
                id=msg.get("Message-ID", f"msg-{i}") or f"msg-{i}",
                subject=subject[:200],
                from_address=from_addr[:100],
                date=date,
                snippet=body[:300] if body else "",
                failure_type=failure_type,
                severity=severity,
                keywords_found=keywords,
            )
        )

    print(f"Scanned {total_scanned} total emails")
    return failures


def summarize_failures(failures: list[FailureEmail]) -> FailureSummary:
    """Create summary of failure emails."""
    if not failures:
        return FailureSummary(
            total_emails=0,
            by_type={},
            by_severity={},
            by_sender={},
            date_range=("", ""),
            top_subjects=[],
            emails=[],
        )

    by_type: dict[str, int] = defaultdict(int)
    by_severity: dict[str, int] = defaultdict(int)
    by_sender: dict[str, int] = defaultdict(int)
    subjects: dict[str, int] = defaultdict(int)
    dates = []

    for f in failures:
        by_type[f.failure_type] += 1
        by_severity[f.severity] += 1
        by_sender[f.from_address] += 1
        subj = re.sub(r"^(re:|fwd:|fw:)\s*", "", f.subject.lower(), flags=re.IGNORECASE)
        subjects[subj] += 1
        if f.date:
            dates.append(f.date)

    date_range = ("", "")
    if dates:
        dates.sort()
        date_range = (dates[0].isoformat(), dates[-1].isoformat())

    top_subjects = sorted(subjects.items(), key=lambda x: x[1], reverse=True)[:10]

    return FailureSummary(
        total_emails=len(failures),
        by_type=dict(by_type),
        by_severity=dict(by_severity),
        by_sender=dict(by_sender),
        date_range=date_range,
        top_subjects=top_subjects,
        emails=failures,
    )


def print_summary(summary: FailureSummary):
    """Print failure summary to console."""
    print(f"\n{'=' * 60}")
    print("ARAGORA FAILURE ANALYSIS")
    print(f"{'=' * 60}")

    if summary.total_emails == 0:
        print("\nNo Aragora-related failure emails found!")
        return

    print(f"\nTotal failure emails: {summary.total_emails}")
    print(f"Date range: {summary.date_range[0]} to {summary.date_range[1]}")

    print("\n--- By Failure Type ---")
    for ftype, count in sorted(summary.by_type.items(), key=lambda x: x[1], reverse=True):
        print(f"  {ftype}: {count}")

    print("\n--- By Severity ---")
    for sev, count in sorted(summary.by_severity.items(), key=lambda x: x[1], reverse=True):
        print(f"  {sev}: {count}")

    print("\n--- Top Senders ---")
    for sender, count in sorted(summary.by_sender.items(), key=lambda x: x[1], reverse=True)[:5]:
        print(f"  {sender[:50]}: {count}")

    print("\n--- Top Failure Subjects ---")
    for subj, count in summary.top_subjects[:5]:
        print(f"  [{count}x] {subj[:60]}...")

    print("\n--- Recent Critical/High Failures ---")
    critical = [f for f in summary.emails if f.severity in ("critical", "high")]
    for f in sorted(critical, key=lambda x: x.date or datetime.min, reverse=True)[:10]:
        date_str = f.date.strftime("%Y-%m-%d") if f.date else "unknown"
        print(f"  [{date_str}] [{f.severity.upper()}] {f.subject[:50]}...")
        print(f"           From: {f.from_address[:50]}")


def export_results(summary: FailureSummary, output_file: str):
    """Export results to JSON file."""
    export_data = {
        "total_emails": summary.total_emails,
        "by_type": summary.by_type,
        "by_severity": summary.by_severity,
        "by_sender": summary.by_sender,
        "date_range": summary.date_range,
        "top_subjects": summary.top_subjects,
        "emails": [
            {
                "id": e.id,
                "subject": e.subject,
                "from": e.from_address,
                "date": e.date.isoformat() if e.date else None,
                "failure_type": e.failure_type,
                "severity": e.severity,
                "keywords": e.keywords_found,
                "snippet": e.snippet,
            }
            for e in summary.emails
        ],
    }

    with open(output_file, "w") as f:
        json.dump(export_data, f, indent=2, default=str)

    print(f"\nResults exported to: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze Gmail Takeout exports for Aragora failure emails"
    )
    parser.add_argument(
        "--mbox",
        required=True,
        help="Path to MBOX file from Google Takeout",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=60,
        help="Days to look back (default: 60)",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=10000,
        help="Maximum failures to find (default: 10000)",
    )
    parser.add_argument(
        "--output",
        default="gmail_failures.json",
        help="Output JSON file (default: gmail_failures.json)",
    )
    parser.add_argument(
        "--loose",
        action="store_true",
        help="Use loose matching (includes generic terms like 'debate', 'consensus')",
    )

    args = parser.parse_args()

    # Update patterns based on mode
    global ARAGORA_PATTERNS
    if args.loose:
        ARAGORA_PATTERNS = ARAGORA_PATTERNS_STRICT + [
            r"debate",
            r"consensus",
            r"agent",
            r"nomic",
            r"elo",
            r"belief",
            r"rlm",
            r"orchestrat",
        ]
        print("Mode: LOOSE (may include newsletter false positives)")
    else:
        print("Mode: STRICT (Aragora-specific terms only)")

    print(f"\n{'=' * 60}")
    print("ARAGORA GMAIL TAKEOUT ANALYZER")
    print(f"{'=' * 60}")
    print(f"\nLooking back: {args.days} days")
    print(f"Max results: {args.max_results}")

    # Analyze MBOX
    failures = analyze_mbox(args.mbox, args.days, args.max_results)

    # Summarize
    summary = summarize_failures(failures)

    # Print and export
    print_summary(summary)
    export_results(summary, args.output)

    print(f"\n{'=' * 60}")
    print(f"TOTAL: Found {summary.total_emails} Aragora failure emails")
    print(f"{'=' * 60}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
