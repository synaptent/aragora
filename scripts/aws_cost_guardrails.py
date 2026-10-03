#!/usr/bin/env python3
"""AWS cost guardrails: S3 lifecycle hygiene + a monthly cost budget.

Root-caused from the Feb-Apr 2026 S3 storage runaway (TimedStorage-ByteHrs on
versioned buckets with no noncurrent-version expiration) that led to the Jul 16
2026 account suspension. This script makes the promised remediation applyable
in one command the moment the account is reinstated:

    # 1. See which buckets are leaking (versioned, no noncurrent expiration)
    #    and how big they are. Read-only.
    python scripts/aws_cost_guardrails.py audit

    # 2. Append a guardrail lifecycle rule to every leaking bucket
    #    (dry-run by default; add --apply to write)
    python scripts/aws_cost_guardrails.py lifecycle --apply
    python scripts/aws_cost_guardrails.py lifecycle --bucket my-bucket --apply

    # 3. Create/update a monthly cost budget with email alerts
    python scripts/aws_cost_guardrails.py budget --email ops@example.com --limit 2500 --apply

The lifecycle command MERGES with existing configuration (it never replaces
rules it did not create) and is idempotent via the rule ID.

Credentials: standard boto3 resolution (env, SSO, assume-role). No standing
keys are expected; run after `aws sso login` / MFA per the credential policy.
See docs/runbooks/RUNBOOK_AWS_REINSTATEMENT.md for the full reinstatement flow.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

GUARDRAIL_RULE_ID = "aragora-cost-guardrail"
DELETE_MARKER_RULE_ID = "aragora-purge-expired-delete-markers"


def _client(service: str, region: str | None = None):
    try:
        import boto3
    except ImportError:
        print("boto3 is required: pip install boto3", file=sys.stderr)
        raise SystemExit(1)
    return boto3.client(service, region_name=region) if region else boto3.client(service)


def guardrail_rules(noncurrent_days: int) -> list[dict[str, Any]]:
    """The two lifecycle rules this script owns, identified by fixed IDs."""
    return [
        {
            "ID": GUARDRAIL_RULE_ID,
            "Status": "Enabled",
            "Filter": {"Prefix": ""},
            "NoncurrentVersionExpiration": {"NoncurrentDays": noncurrent_days},
            "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
        },
        {
            "ID": DELETE_MARKER_RULE_ID,
            "Status": "Enabled",
            "Filter": {"Prefix": ""},
            "Expiration": {"ExpiredObjectDeleteMarker": True},
        },
    ]


def bucket_region(s3, bucket: str) -> str:
    loc = s3.get_bucket_location(Bucket=bucket).get("LocationConstraint")
    return loc or "us-east-1"


def bucket_size_gb(bucket: str, region: str) -> float | None:
    """Latest CloudWatch BucketSizeBytes across all storage types, in GB."""
    cw = _client("cloudwatch", region)
    total = 0.0
    seen = False
    for storage_type in (
        "StandardStorage",
        "StandardIAStorage",
        "GlacierStorage",
        "IntelligentTieringFAStorage",
        "IntelligentTieringIAStorage",
        "DeepArchiveStorage",
    ):
        resp = cw.get_metric_statistics(
            Namespace="AWS/S3",
            MetricName="BucketSizeBytes",
            Dimensions=[
                {"Name": "BucketName", "Value": bucket},
                {"Name": "StorageType", "Value": storage_type},
            ],
            StartTime=datetime.now(timezone.utc) - timedelta(days=3),
            EndTime=datetime.now(timezone.utc),
            Period=86400,
            Statistics=["Average"],
        )
        points = resp.get("Datapoints", [])
        if points:
            seen = True
            total += max(p["Average"] for p in points)
    return total / (1024**3) if seen else None


def get_lifecycle(s3, bucket: str) -> list[dict[str, Any]]:
    try:
        return s3.get_bucket_lifecycle_configuration(Bucket=bucket).get("Rules", [])
    except s3.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchLifecycleConfiguration":
            return []
        raise


def _rule_is_whole_bucket(rule: dict[str, Any]) -> bool:
    """True when a lifecycle rule applies to the entire bucket.

    A rule scoped by prefix, tag, size bounds, or an And combination only
    protects part of the keyspace — the rest of a versioned bucket keeps
    accumulating noncurrent versions, so scoped rules must not count as
    coverage for the leak audit/sweep.
    """
    if rule.get("Prefix"):  # legacy top-level prefix; non-empty = scoped
        return False
    rule_filter = rule.get("Filter")
    if not rule_filter:
        return True
    scoped_keys = ("Prefix", "Tag", "And", "ObjectSizeGreaterThan", "ObjectSizeLessThan")
    return not any(rule_filter.get(key) for key in scoped_keys)


def rule_covers_noncurrent(rule: dict[str, Any]) -> bool:
    return (
        rule.get("Status") == "Enabled"
        and "NoncurrentVersionExpiration" in rule
        and _rule_is_whole_bucket(rule)
    )


def rule_has_noncurrent(rule: dict[str, Any]) -> bool:
    """Any enabled noncurrent-version expiration, whole-bucket or scoped."""
    return rule.get("Status") == "Enabled" and "NoncurrentVersionExpiration" in rule


def noncurrent_coverage(rules: list[dict[str, Any]]) -> str:
    """'full' | 'partial' | 'none' noncurrent-expiration coverage.

    'partial' (scoped rules only) is deliberately excluded from the sweep:
    appending a whole-bucket expiration next to intentional scoped retention
    would shorten retention for those prefixes (S3 applies the earliest
    expiration among overlapping rules). Partial buckets need a human
    decision — audit lists them; apply explicitly with --bucket.
    """
    if any(rule_covers_noncurrent(r) for r in rules):
        return "full"
    if any(rule_has_noncurrent(r) for r in rules):
        return "partial"
    return "none"


def is_versioned(s3, bucket: str) -> bool:
    return s3.get_bucket_versioning(Bucket=bucket).get("Status") == "Enabled"


def cmd_audit(args: argparse.Namespace) -> int:
    s3 = _client("s3")
    buckets = [args.bucket] if args.bucket else [b["Name"] for b in s3.list_buckets()["Buckets"]]
    findings = []
    for bucket in buckets:
        try:
            region = bucket_region(s3, bucket)
            versioned = is_versioned(s3, bucket)
            rules = get_lifecycle(s3, bucket)
            coverage = noncurrent_coverage(rules)
            size = bucket_size_gb(bucket, region)
            leaking = versioned and coverage == "none"
            findings.append(
                {
                    "bucket": bucket,
                    "region": region,
                    "size_gb": round(size, 2) if size is not None else None,
                    "versioned": versioned,
                    "noncurrent_coverage": coverage,
                    "leaking": leaking,
                }
            )
        except Exception as e:  # noqa: BLE001 - per-bucket audit must not abort the sweep
            findings.append({"bucket": bucket, "error": str(e)})
    findings.sort(key=lambda f: f.get("size_gb") or 0, reverse=True)
    print(
        json.dumps(
            {
                "findings": findings,
                "leaking": [f["bucket"] for f in findings if f.get("leaking")],
                "partial_coverage_review_manually": [
                    f["bucket"]
                    for f in findings
                    if f.get("versioned") and f.get("noncurrent_coverage") == "partial"
                ],
            },
            indent=2,
        )
    )
    return 0


def cmd_lifecycle(args: argparse.Namespace) -> int:
    s3 = _client("s3")
    buckets = [args.bucket] if args.bucket else [b["Name"] for b in s3.list_buckets()["Buckets"]]
    changed = []
    for bucket in buckets:
        if not args.bucket and not is_versioned(s3, bucket):
            continue  # sweep mode targets the leak pattern; explicit --bucket always applies
        existing = get_lifecycle(s3, bucket)
        ours = {GUARDRAIL_RULE_ID, DELETE_MARKER_RULE_ID}
        if any(r.get("ID") in ours for r in existing):
            print(f"{bucket}: guardrail rules already present, skipping")
            continue
        if not args.bucket and any(rule_has_noncurrent(r) for r in existing):
            # Sweep mode never overrides deliberate retention: any enabled
            # noncurrent-version expiration — whole-bucket OR prefix/tag
            # scoped — takes the bucket out of the sweep, because appending a
            # whole-bucket rule next to scoped retention would shorten
            # retention for those prefixes (earliest expiration wins among
            # overlapping rules). Scoped-only buckets show up in
            # `audit` as partial coverage; apply explicitly with --bucket
            # after review.
            coverage = noncurrent_coverage(existing)
            print(f"{bucket}: existing noncurrent handling (coverage={coverage}), skipping")
            continue
        merged = existing + guardrail_rules(args.noncurrent_days)
        if args.apply:
            s3.put_bucket_lifecycle_configuration(
                Bucket=bucket, LifecycleConfiguration={"Rules": merged}
            )
            print(f"{bucket}: guardrail rules APPLIED ({len(existing)} existing rules preserved)")
        else:
            print(f"{bucket}: would append guardrail rules to {len(existing)} existing (dry-run)")
        changed.append(bucket)
    if not changed:
        print("No buckets needed changes.")
    elif not args.apply:
        print("\nDry-run. Re-run with --apply to write.")
    return 0


def _reconcile_notifications(
    budgets,
    account_id: str,
    name: str,
    desired: list[dict[str, Any]],
    subscribers: list[dict[str, str]],
) -> int:
    """Ensure every desired notification + subscriber exists on the budget.

    update_budget alone never touches notifications, so a preexisting budget
    with missing or stale alerts would otherwise report "updated" while the
    promised guardrail alerts still do not fire. Returns the number of
    notifications/subscribers created.
    """
    existing = budgets.describe_notifications_for_budget(AccountId=account_id, BudgetName=name).get(
        "Notifications", []
    )

    def key(n: dict[str, Any]) -> tuple:
        return (
            n.get("NotificationType"),
            n.get("ComparisonOperator"),
            float(n.get("Threshold", 0)),
            n.get("ThresholdType", "PERCENTAGE"),
        )

    existing_keys = {key(n) for n in existing}
    created = 0
    for notification in desired:
        if key(notification) not in existing_keys:
            budgets.create_notification(
                AccountId=account_id,
                BudgetName=name,
                Notification=notification,
                Subscribers=subscribers,
            )
            created += 1
            continue
        current = budgets.describe_subscribers_for_notification(
            AccountId=account_id, BudgetName=name, Notification=notification
        ).get("Subscribers", [])
        current_addresses = {s.get("Address") for s in current}
        for subscriber in subscribers:
            if subscriber["Address"] not in current_addresses:
                budgets.create_subscriber(
                    AccountId=account_id,
                    BudgetName=name,
                    Notification=notification,
                    Subscriber=subscriber,
                )
                created += 1
    return created


def cmd_budget(args: argparse.Namespace) -> int:
    sts = _client("sts")
    account_id = sts.get_caller_identity()["Account"]
    budgets = _client("budgets", "us-east-1")  # Budgets API lives in us-east-1
    name = "aragora-monthly-cost-guardrail"
    budget = {
        "BudgetName": name,
        "BudgetLimit": {"Amount": str(args.limit), "Unit": "USD"},
        "BudgetType": "COST",
        "TimeUnit": "MONTHLY",
    }
    subscribers = [{"SubscriptionType": "EMAIL", "Address": e} for e in args.email]
    notifications = [
        {
            "NotificationType": "ACTUAL",
            "ComparisonOperator": "GREATER_THAN",
            "Threshold": t,
            "ThresholdType": "PERCENTAGE",
        }
        for t in (50, 80, 100)
    ] + [
        {
            "NotificationType": "FORECASTED",
            "ComparisonOperator": "GREATER_THAN",
            "Threshold": 100,
            "ThresholdType": "PERCENTAGE",
        }
    ]
    if not args.apply:
        print(
            json.dumps(
                {
                    "account": account_id,
                    "budget": budget,
                    "notifications": notifications,
                    "subscribers": [e for e in args.email],
                },
                indent=2,
            )
        )
        print("\nDry-run. Re-run with --apply to write.")
        return 0
    try:
        budgets.describe_budget(AccountId=account_id, BudgetName=name)
        budgets.update_budget(AccountId=account_id, NewBudget=budget)
        created = _reconcile_notifications(budgets, account_id, name, notifications, subscribers)
        print(
            f"Budget {name} updated (limit ${args.limit}/mo; "
            f"{created} missing notification(s)/subscriber(s) reconciled)"
        )
    except budgets.exceptions.NotFoundException:
        budgets.create_budget(
            AccountId=account_id,
            Budget=budget,
            NotificationsWithSubscribers=[
                {"Notification": n, "Subscribers": subscribers} for n in notifications
            ],
        )
        print(
            f"Budget {name} created (limit ${args.limit}/mo, {len(notifications)} alert thresholds)"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser(
        "audit",
        help="Read-only: find versioned buckets lacking noncurrent-version expiration, with sizes",
    )
    p_audit.add_argument("--bucket", help="Audit a single bucket instead of all")
    p_audit.set_defaults(func=cmd_audit)

    p_lc = sub.add_parser("lifecycle", help="Append guardrail lifecycle rules (merge, idempotent)")
    p_lc.add_argument("--bucket", help="Target a single bucket (default: all versioned buckets)")
    p_lc.add_argument(
        "--noncurrent-days",
        type=int,
        default=30,
        help="Retention for noncurrent versions (default 30)",
    )
    p_lc.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    p_lc.set_defaults(func=cmd_lifecycle)

    p_b = sub.add_parser("budget", help="Create/update the monthly cost budget with email alerts")
    p_b.add_argument("--email", action="append", required=True, help="Alert recipient (repeatable)")
    p_b.add_argument(
        "--limit", type=float, default=2500, help="Monthly limit in USD (default 2500)"
    )
    p_b.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    p_b.set_defaults(func=cmd_budget)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
