#!/usr/bin/env python3
"""
Access Review Script for SOC 2 Compliance (CC6-02).

Generates reports of user access for quarterly security reviews:
- Lists all users with admin/elevated permissions
- Flags dormant accounts (configurable inactivity threshold)
- Exports to CSV for compliance documentation
- Integrates with audit log for access history

Usage:
    # Generate full access review report
    python scripts/access_review.py

    # Dry run (preview without file output)
    python scripts/access_review.py --dry-run

    # Custom inactivity threshold (default: 90 days)
    python scripts/access_review.py --inactive-days 60

    # Filter by organization
    python scripts/access_review.py --org-id ORG_ID

    # Output formats
    python scripts/access_review.py --format csv
    python scripts/access_review.py --format json
    python scripts/access_review.py --format console

    # Include detailed audit log
    python scripts/access_review.py --include-audit

SOC 2 Control: CC6-02 - Regular access review
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from aragora.storage.user_store import UserStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Access level definitions for review categorization
ACCESS_LEVELS = {
    "admin": {
        "level": 1,
        "description": "Full administrative access",
        "review_frequency": "Monthly",
    },
    "owner": {
        "level": 2,
        "description": "Organization owner with billing access",
        "review_frequency": "Monthly",
    },
    "manager": {
        "level": 3,
        "description": "Team management capabilities",
        "review_frequency": "Quarterly",
    },
    "member": {
        "level": 4,
        "description": "Standard user access",
        "review_frequency": "Annually",
    },
}

# Roles that require elevated review
ELEVATED_ROLES = {"admin", "owner", "manager"}


def get_user_store() -> UserStore:
    """Initialize UserStore with configured database path."""
    data_dir = os.getenv("ARAGORA_DATA_DIR", ".nomic")
    db_path = Path(data_dir) / "users.db"

    if not db_path.exists():
        logger.warning(f"Database not found at {db_path}, creating new database")

    return UserStore(db_path)


def calculate_inactivity_days(last_login: datetime | str | None) -> int | None:
    """Calculate days since last login."""
    if not last_login:
        return None

    try:
        if isinstance(last_login, datetime):
            last_dt = last_login
        else:
            last_dt = datetime.fromisoformat(last_login.replace("Z", "+00:00"))
        # Make datetime naive for comparison if it has timezone
        if last_dt.tzinfo is not None:
            last_dt = last_dt.replace(tzinfo=None)
        delta = datetime.utcnow() - last_dt
        return delta.days
    except (ValueError, TypeError):
        return None


def get_access_findings(
    user: Any,
    inactive_threshold: int,
) -> list[dict]:
    """Generate security findings for a user."""
    findings = []

    # Check for dormant account
    inactivity_days = calculate_inactivity_days(user.last_login_at)
    if inactivity_days is not None and inactivity_days > inactive_threshold:
        findings.append(
            {
                "type": "DORMANT_ACCOUNT",
                "severity": "MEDIUM" if user.role in ELEVATED_ROLES else "LOW",
                "message": f"Account inactive for {inactivity_days} days (threshold: {inactive_threshold})",
                "recommendation": "Review account necessity, consider deactivation",
            }
        )

    # Check for never logged in
    if user.last_login_at is None:
        findings.append(
            {
                "type": "NEVER_LOGGED_IN",
                "severity": "MEDIUM",
                "message": "User has never logged in since account creation",
                "recommendation": "Verify account is needed, remove if unused",
            }
        )

    # Check for admin without MFA
    if user.role in ELEVATED_ROLES and not getattr(user, "mfa_enabled", False):
        findings.append(
            {
                "type": "ADMIN_NO_MFA",
                "severity": "HIGH",
                "message": "Elevated role without MFA enabled",
                "recommendation": "Require MFA for all admin accounts",
            }
        )

    # Check for API key without expiration tracking
    if user.api_key_hash and not user.api_key_expires_at:
        findings.append(
            {
                "type": "API_KEY_NO_EXPIRY",
                "severity": "LOW",
                "message": "API key has no expiration date",
                "recommendation": "Rotate API key with proper expiration",
            }
        )

    return findings


def generate_access_report(
    store: UserStore,
    inactive_threshold: int = 90,
    org_filter: str | None = None,
    include_audit: bool = False,
    elevated_only: bool = False,
) -> dict:
    """Generate comprehensive access review report."""
    report: dict[str, Any] = {
        "metadata": {
            "generated_at": datetime.utcnow().isoformat(),
            "inactive_threshold_days": inactive_threshold,
            "org_filter": org_filter,
            "soc2_control": "CC6-02",
            "review_type": "Quarterly Access Review",
        },
        "summary": {
            "total_users": 0,
            "elevated_users": 0,
            "dormant_accounts": 0,
            "accounts_without_mfa": 0,
            "findings_by_severity": {"HIGH": 0, "MEDIUM": 0, "LOW": 0},
        },
        "users": [],
        "findings": [],
        "recommendations": [],
    }

    # Get all users
    users, total = store.list_all_users(
        limit=10000,
        offset=0,
        org_id_filter=org_filter,
    )

    report["summary"]["total_users"] = total

    for user in users:
        # Skip non-elevated if filtering
        if elevated_only and user.role not in ELEVATED_ROLES:
            continue

        inactivity_days = calculate_inactivity_days(user.last_login_at)
        is_elevated = user.role in ELEVATED_ROLES
        access_info = ACCESS_LEVELS.get(user.role, ACCESS_LEVELS["member"])

        user_record = {
            "user_id": user.id,
            "email": user.email,
            "name": user.name or "(not set)",
            "role": user.role,
            "access_level": access_info["level"],
            "access_description": access_info["description"],
            "review_frequency": access_info["review_frequency"],
            "org_id": user.org_id,
            "is_active": user.is_active,
            "mfa_enabled": getattr(user, "mfa_enabled", False),
            "created_at": user.created_at,
            "last_login_at": user.last_login_at,
            "inactivity_days": inactivity_days,
            "has_api_key": bool(user.api_key_hash),
            "api_key_expires_at": user.api_key_expires_at,
            "findings": [],
        }

        # Get findings for this user
        findings = get_access_findings(user, inactive_threshold)
        user_record["findings"] = findings

        # Update summary counts
        if is_elevated:
            report["summary"]["elevated_users"] += 1

        if inactivity_days and inactivity_days > inactive_threshold:
            report["summary"]["dormant_accounts"] += 1

        if not getattr(user, "mfa_enabled", False):
            report["summary"]["accounts_without_mfa"] += 1

        for finding in findings:
            report["summary"]["findings_by_severity"][finding["severity"]] += 1
            report["findings"].append(
                {
                    "user_id": user.id,
                    "email": user.email,
                    **finding,
                }
            )

        # Include audit log if requested
        if include_audit and user.id:
            try:
                audit_entries = store.get_audit_log(
                    user_id=user.id,
                    limit=10,
                )
                user_record["recent_activity"] = audit_entries
            except Exception as e:
                logger.warning(f"Could not fetch audit log for {user.id}: {e}")

        report["users"].append(user_record)

    # Generate recommendations
    if report["summary"]["findings_by_severity"]["HIGH"] > 0:
        report["recommendations"].append(
            {
                "priority": "CRITICAL",
                "action": "Address all HIGH severity findings immediately",
                "details": f"{report['summary']['findings_by_severity']['HIGH']} high severity issues found",
            }
        )

    if report["summary"]["dormant_accounts"] > 0:
        report["recommendations"].append(
            {
                "priority": "HIGH",
                "action": "Review and deactivate dormant accounts",
                "details": f"{report['summary']['dormant_accounts']} accounts inactive >{inactive_threshold} days",
            }
        )

    if report["summary"]["accounts_without_mfa"] > 0:
        report["recommendations"].append(
            {
                "priority": "MEDIUM",
                "action": "Enable MFA for accounts without it",
                "details": f"{report['summary']['accounts_without_mfa']} accounts without MFA",
            }
        )

    return report


def format_console_output(report: dict) -> str:
    """Format report for console display."""
    lines = []
    lines.append("=" * 70)
    lines.append("ACCESS REVIEW REPORT")
    lines.append(f"Generated: {report['metadata']['generated_at']}")
    lines.append(f"SOC 2 Control: {report['metadata']['soc2_control']}")
    lines.append("=" * 70)

    # Summary
    lines.append("\nSUMMARY")
    lines.append("-" * 40)
    summary = report["summary"]
    lines.append(f"  Total Users:           {summary['total_users']}")
    lines.append(f"  Elevated Users:        {summary['elevated_users']}")
    lines.append(f"  Dormant Accounts:      {summary['dormant_accounts']}")
    lines.append(f"  Without MFA:           {summary['accounts_without_mfa']}")
    lines.append(f"  HIGH Findings:         {summary['findings_by_severity']['HIGH']}")
    lines.append(f"  MEDIUM Findings:       {summary['findings_by_severity']['MEDIUM']}")
    lines.append(f"  LOW Findings:          {summary['findings_by_severity']['LOW']}")

    # Elevated Users
    elevated = [u for u in report["users"] if u["role"] in ELEVATED_ROLES]
    if elevated:
        lines.append("\nELEVATED ACCESS USERS")
        lines.append("-" * 40)
        for user in elevated:
            mfa = "MFA" if user["mfa_enabled"] else "NO MFA"
            inactive = f"({user['inactivity_days']}d inactive)" if user["inactivity_days"] else ""
            lines.append(f"  {user['role']:8} {user['email']:30} {mfa:8} {inactive}")

    # Findings
    if report["findings"]:
        lines.append("\nFINDINGS")
        lines.append("-" * 40)
        for finding in sorted(report["findings"], key=lambda x: x["severity"]):
            lines.append(f"  [{finding['severity']:6}] {finding['email']}")
            lines.append(f"           {finding['type']}: {finding['message']}")

    # Recommendations
    if report["recommendations"]:
        lines.append("\nRECOMMENDATIONS")
        lines.append("-" * 40)
        for rec in report["recommendations"]:
            lines.append(f"  [{rec['priority']}] {rec['action']}")
            lines.append(f"           {rec['details']}")

    lines.append("\n" + "=" * 70)
    return "\n".join(lines)


def export_csv(report: dict, output_path: Path) -> None:
    """Export report to CSV format."""
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)

        # Header
        writer.writerow(
            [
                "User ID",
                "Email",
                "Name",
                "Role",
                "Access Level",
                "Org ID",
                "Active",
                "MFA Enabled",
                "Created At",
                "Last Login",
                "Inactivity Days",
                "Has API Key",
                "Finding Count",
                "High Findings",
            ]
        )

        # Data
        for user in report["users"]:
            high_findings = sum(1 for f in user["findings"] if f["severity"] == "HIGH")
            writer.writerow(
                [
                    user["user_id"],
                    user["email"],
                    user["name"],
                    user["role"],
                    user["access_level"],
                    user["org_id"] or "",
                    "Yes" if user["is_active"] else "No",
                    "Yes" if user["mfa_enabled"] else "No",
                    user["created_at"],
                    user["last_login_at"] or "Never",
                    user["inactivity_days"] or "N/A",
                    "Yes" if user["has_api_key"] else "No",
                    len(user["findings"]),
                    high_findings,
                ]
            )

    logger.info(f"CSV exported to {output_path}")


def export_json(report: dict, output_path: Path) -> None:
    """Export report to JSON format."""
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    logger.info(f"JSON exported to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate access review report for SOC 2 compliance (CC6-02)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/access_review.py                    # Full report to console
  python scripts/access_review.py --format csv      # Export as CSV
  python scripts/access_review.py --dry-run         # Preview without output
  python scripts/access_review.py --inactive-days 60 --elevated-only
        """,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview report without file output",
    )
    parser.add_argument(
        "--inactive-days",
        type=int,
        default=90,
        help="Days of inactivity to flag as dormant (default: 90)",
    )
    parser.add_argument(
        "--org-id",
        type=str,
        help="Filter by organization ID",
    )
    parser.add_argument(
        "--format",
        choices=["console", "csv", "json"],
        default="console",
        help="Output format (default: console)",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file path (auto-generated if not specified)",
    )
    parser.add_argument(
        "--include-audit",
        action="store_true",
        help="Include recent audit log entries for each user",
    )
    parser.add_argument(
        "--elevated-only",
        action="store_true",
        help="Only include users with elevated roles (admin, owner, manager)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("Starting access review...")

    # Initialize store
    try:
        store = get_user_store()
    except Exception as e:
        logger.error(f"Failed to initialize user store: {e}")
        sys.exit(1)

    # Generate report
    try:
        report = generate_access_report(
            store=store,
            inactive_threshold=args.inactive_days,
            org_filter=args.org_id,
            include_audit=args.include_audit,
            elevated_only=args.elevated_only,
        )
    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
        sys.exit(1)

    # Output
    if args.dry_run:
        print(format_console_output(report))
        logger.info("Dry run complete - no files written")
        return

    if args.format == "console":
        print(format_console_output(report))
    elif args.format == "csv":
        output_path = (
            Path(args.output)
            if args.output
            else Path(f"access_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        )
        export_csv(report, output_path)
    elif args.format == "json":
        output_path = (
            Path(args.output)
            if args.output
            else Path(f"access_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        )
        export_json(report, output_path)

    # Summary
    summary = report["summary"]
    logger.info(
        f"Access review complete: {summary['total_users']} users, "
        f"{summary['elevated_users']} elevated, "
        f"{summary['dormant_accounts']} dormant, "
        f"{summary['findings_by_severity']['HIGH']} high-severity findings"
    )

    # Exit with error code if high findings
    if summary["findings_by_severity"]["HIGH"] > 0:
        logger.warning("HIGH severity findings detected - review required")
        sys.exit(1)


if __name__ == "__main__":
    main()
