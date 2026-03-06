"""
Data Retention Policy Manager.

Automates data retention and deletion according to configured policies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any
from collections.abc import Callable
from uuid import uuid4

logger = logging.getLogger(__name__)


class RetentionAction(str, Enum):
    """Actions to take when retention period expires."""

    DELETE = "delete"
    ARCHIVE = "archive"
    ANONYMIZE = "anonymize"
    NOTIFY = "notify"


class RetentionViolation(Exception):
    """Raised when a retention policy is violated."""

    def __init__(
        self,
        message: str,
        policy_id: str,
        resource_id: str,
    ):
        super().__init__(message)
        self.policy_id = policy_id
        self.resource_id = resource_id


@dataclass
class RetentionPolicy:
    """A data retention policy."""

    id: str
    name: str
    description: str = ""

    # Retention settings
    retention_days: int = 90
    action: RetentionAction = RetentionAction.DELETE

    # Scope
    applies_to: list[str] = field(default_factory=lambda: ["documents", "findings", "sessions"])
    workspace_ids: list[str] | None = None  # None = all workspaces

    # Grace period before action
    grace_period_days: int = 7

    # Notification
    notify_before_days: int = 14
    notification_recipients: list[str] = field(default_factory=list)

    # Exceptions
    exclude_sensitivity_levels: list[str] = field(default_factory=list)
    exclude_tags: list[str] = field(default_factory=list)

    # Status
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_run: datetime | None = None

    def is_expired(self, created_at: datetime) -> bool:
        """Check if a resource has expired under this policy."""
        expiry_date = created_at + timedelta(days=self.retention_days)
        return datetime.now(timezone.utc) >= expiry_date

    def days_until_expiry(self, created_at: datetime) -> int:
        """Calculate days until expiry."""
        expiry_date = created_at + timedelta(days=self.retention_days)
        delta = expiry_date - datetime.now(timezone.utc)
        return max(0, delta.days)


@dataclass
class DeletionRecord:
    """Record of a deletion operation."""

    resource_type: str
    resource_id: str
    workspace_id: str
    policy_id: str
    deleted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeletionReport:
    """Report from a retention policy execution."""

    policy_id: str
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_seconds: float = 0.0

    # Counts
    items_evaluated: int = 0
    items_deleted: int = 0
    items_archived: int = 0
    items_anonymized: int = 0
    items_skipped: int = 0
    items_failed: int = 0

    # Details
    deletions: list[DeletionRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notifications_sent: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "policy_id": self.policy_id,
            "executed_at": self.executed_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "items_evaluated": self.items_evaluated,
            "items_deleted": self.items_deleted,
            "items_archived": self.items_archived,
            "items_anonymized": self.items_anonymized,
            "items_skipped": self.items_skipped,
            "items_failed": self.items_failed,
            "notifications_sent": self.notifications_sent,
            "error_count": len(self.errors),
        }


class RetentionPolicyManager:
    """
    Manages data retention policies.

    Features:
    - Define retention policies per workspace or globally
    - Automatic expiration tracking
    - Deletion, archival, or anonymization actions
    - Notification before deletion
    - Compliance reporting
    """

    def __init__(self):
        self._policies: dict[str, RetentionPolicy] = {}
        self._deletion_records: list[DeletionRecord] = []
        self._delete_handlers: dict[str, Callable] = {}

        # Register default policies
        self._register_default_policies()

    def _register_default_policies(self) -> None:
        """Register default retention policies."""
        # Standard 90-day policy
        self._policies["default_90_days"] = RetentionPolicy(
            id="default_90_days",
            name="Standard 90-Day Retention",
            description="Delete documents and findings after 90 days",
            retention_days=90,
        )

        # Long-term audit policy
        self._policies["audit_7_years"] = RetentionPolicy(
            id="audit_7_years",
            name="Audit Retention (7 Years)",
            description="Keep audit logs for regulatory compliance",
            retention_days=365 * 7,
            applies_to=["audit_logs"],
            action=RetentionAction.ARCHIVE,
        )

        # Classification-derived retention policies
        self._policies["classification_public_365d"] = RetentionPolicy(
            id="classification_public_365d",
            name="Public Data Retention (365 Days)",
            description="Delete public-classified data after 365 days",
            retention_days=365,
            action=RetentionAction.DELETE,
        )
        self._policies["classification_confidential_180d"] = RetentionPolicy(
            id="classification_confidential_180d",
            name="Confidential Data Retention (180 Days)",
            description="Archive confidential-classified data after 180 days",
            retention_days=180,
            action=RetentionAction.ARCHIVE,
        )
        self._policies["classification_restricted_90d"] = RetentionPolicy(
            id="classification_restricted_90d",
            name="Restricted Data Retention (90 Days)",
            description="Delete restricted-classified data after 90 days",
            retention_days=90,
            action=RetentionAction.DELETE,
        )

    def create_policy(
        self,
        name: str,
        retention_days: int,
        action: RetentionAction = RetentionAction.DELETE,
        workspace_ids: list[str] | None = None,
        **kwargs,
    ) -> RetentionPolicy:
        """
        Create a new retention policy.

        Args:
            name: Policy name
            retention_days: Days to retain data
            action: Action on expiration
            workspace_ids: Specific workspaces (None = all)
            **kwargs: Additional policy settings

        Returns:
            Created policy
        """
        policy_id = f"policy_{uuid4().hex[:8]}"

        policy = RetentionPolicy(
            id=policy_id,
            name=name,
            retention_days=retention_days,
            action=action,
            workspace_ids=workspace_ids,
            **kwargs,
        )

        self._policies[policy_id] = policy
        logger.info("Created retention policy: %s (%s days)", name, retention_days)

        return policy

    def get_policy(self, policy_id: str) -> RetentionPolicy | None:
        """Get a policy by ID."""
        return self._policies.get(policy_id)

    def list_policies(
        self,
        workspace_id: str | None = None,
    ) -> list[RetentionPolicy]:
        """List retention policies."""
        policies = list(self._policies.values())

        if workspace_id:
            policies = [
                p for p in policies if p.workspace_ids is None or workspace_id in p.workspace_ids
            ]

        return policies

    def update_policy(
        self,
        policy_id: str,
        **updates,
    ) -> RetentionPolicy:
        """Update a retention policy."""
        policy = self._policies.get(policy_id)
        if not policy:
            raise ValueError(f"Policy not found: {policy_id}")

        for key, value in updates.items():
            if hasattr(policy, key):
                setattr(policy, key, value)

        return policy

    def delete_policy(self, policy_id: str) -> None:
        """Delete a retention policy."""
        if policy_id in self._policies:
            del self._policies[policy_id]
            logger.info("Deleted retention policy: %s", policy_id)

    def register_delete_handler(
        self,
        resource_type: str,
        handler: Callable[[str, str], bool],
    ) -> None:
        """
        Register a deletion handler for a resource type.

        Args:
            resource_type: Type of resource (e.g., "documents")
            handler: Function(resource_id, workspace_id) -> success
        """
        self._delete_handlers[resource_type] = handler

    async def execute_policy(
        self,
        policy_id: str,
        dry_run: bool = False,
    ) -> DeletionReport:
        """
        Execute a retention policy.

        Args:
            policy_id: Policy to execute
            dry_run: If True, don't actually delete

        Returns:
            Report of actions taken
        """
        policy = self._policies.get(policy_id)
        if not policy:
            raise ValueError(f"Policy not found: {policy_id}")

        if not policy.enabled:
            return DeletionReport(
                policy_id=policy_id,
                errors=["Policy is disabled"],
            )

        started_at = datetime.now(timezone.utc)
        report = DeletionReport(policy_id=policy_id)

        try:
            # Get items to evaluate
            items = await self._get_items_for_policy(policy)
            report.items_evaluated = len(items)

            for item in items:
                try:
                    result = await self._process_item(item, policy, dry_run)

                    if result == "deleted":
                        report.items_deleted += 1
                    elif result == "archived":
                        report.items_archived += 1
                    elif result == "anonymized":
                        report.items_anonymized += 1
                    elif result == "skipped":
                        report.items_skipped += 1
                    else:
                        report.items_failed += 1

                except (KeyError, ValueError, TypeError, RuntimeError) as e:
                    report.items_failed += 1
                    report.errors.append(f"Error processing {item['id']}: {e}")

            # Send notifications
            if policy.notification_recipients:
                report.notifications_sent = await self._send_notifications(policy, report, dry_run)

            # Update policy
            policy.last_run = datetime.now(timezone.utc)

        except (KeyError, ValueError, TypeError, RuntimeError) as e:
            report.errors.append(f"Policy execution error: {e}")
            logger.exception("Error executing policy %s", policy_id)

        report.duration_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()
        return report

    async def execute_all_policies(
        self,
        dry_run: bool = False,
    ) -> list[DeletionReport]:
        """Execute all enabled retention policies."""
        reports = []

        for policy_id, policy in self._policies.items():
            if policy.enabled:
                report = await self.execute_policy(policy_id, dry_run)
                reports.append(report)

        return reports

    async def check_expiring_soon(
        self,
        workspace_id: str | None = None,
        days: int = 14,
    ) -> list[dict[str, Any]]:
        """
        Check for items expiring soon.

        Args:
            workspace_id: Filter by workspace
            days: Days to look ahead

        Returns:
            List of items expiring within the window
        """
        expiring = []

        for policy in self._policies.values():
            if not policy.enabled:
                continue

            if workspace_id and policy.workspace_ids:
                if workspace_id not in policy.workspace_ids:
                    continue

            items = await self._get_items_for_policy(policy)

            for item in items:
                days_left = policy.days_until_expiry(item["created_at"])
                if 0 < days_left <= days:
                    expiring.append(
                        {
                            "resource_type": item["type"],
                            "resource_id": item["id"],
                            "workspace_id": item.get("workspace_id"),
                            "days_until_expiry": days_left,
                            "policy_id": policy.id,
                            "action": policy.action.value,
                        }
                    )

        return sorted(expiring, key=lambda x: x["days_until_expiry"])

    async def get_compliance_report(
        self,
        workspace_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Generate a compliance report for retention.

        Args:
            workspace_id: Filter by workspace
            start_date: Report start date
            end_date: Report end date

        Returns:
            Compliance report data
        """
        start_date = start_date or (datetime.now(timezone.utc) - timedelta(days=30))
        end_date = end_date or datetime.now(timezone.utc)

        # Filter deletion records
        records = [
            r
            for r in self._deletion_records
            if start_date <= r.deleted_at <= end_date
            and (not workspace_id or r.workspace_id == workspace_id)
        ]

        # Group by policy
        by_policy: dict[str, int] = {}
        by_type: dict[str, int] = {}

        for record in records:
            by_policy[record.policy_id] = by_policy.get(record.policy_id, 0) + 1
            by_type[record.resource_type] = by_type.get(record.resource_type, 0) + 1

        return {
            "report_period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "total_deletions": len(records),
            "deletions_by_policy": by_policy,
            "deletions_by_type": by_type,
            "active_policies": len([p for p in self._policies.values() if p.enabled]),
        }

    async def _get_items_for_policy(
        self,
        policy: RetentionPolicy,
    ) -> list[dict[str, Any]]:
        """Get items that a policy applies to."""
        # This would integrate with document store, audit sessions, etc.
        # For now, return empty list (implementations would override)
        return []

    async def _process_item(
        self,
        item: dict[str, Any],
        policy: RetentionPolicy,
        dry_run: bool,
    ) -> str:
        """Process a single item according to policy."""
        # Check if expired
        if not policy.is_expired(item["created_at"]):
            return "skipped"

        # Check exclusions
        if item.get("sensitivity_level") in policy.exclude_sensitivity_levels:
            return "skipped"

        if any(tag in policy.exclude_tags for tag in item.get("tags", [])):
            return "skipped"

        if dry_run:
            logger.debug("[DRY RUN] Would %s: %s", policy.action.value, item["id"])
            return policy.action.value

        # Execute action
        if policy.action == RetentionAction.DELETE:
            return await self._delete_item(item, policy)
        elif policy.action == RetentionAction.ARCHIVE:
            return await self._archive_item(item, policy)
        elif policy.action == RetentionAction.ANONYMIZE:
            return await self._anonymize_item(item, policy)
        else:
            return "skipped"

    async def _delete_item(
        self,
        item: dict[str, Any],
        policy: RetentionPolicy,
    ) -> str:
        """Delete an item."""
        resource_type = item["type"]
        handler = self._delete_handlers.get(resource_type)

        if handler:
            success = handler(item["id"], item.get("workspace_id", ""))
            if success:
                self._deletion_records.append(
                    DeletionRecord(
                        resource_type=resource_type,
                        resource_id=item["id"],
                        workspace_id=item.get("workspace_id", ""),
                        policy_id=policy.id,
                    )
                )
                return "deleted"
            return "failed"

        logger.warning("No delete handler for type: %s", resource_type)
        return "skipped"

    async def _archive_item(
        self,
        item: dict[str, Any],
        policy: RetentionPolicy,
    ) -> str:
        """Archive an item."""
        # Implementation would move to cold storage
        logger.info("Archiving item %s", item["id"])
        return "archived"

    async def _anonymize_item(
        self,
        item: dict[str, Any],
        policy: RetentionPolicy,
    ) -> str:
        """Anonymize an item."""
        # Implementation would remove PII while keeping structure
        logger.info("Anonymizing item %s", item["id"])
        return "anonymized"

    async def _send_notifications(
        self,
        policy: RetentionPolicy,
        report: DeletionReport,
        dry_run: bool,
    ) -> int:
        """Send notifications about retention execution."""
        if dry_run:
            return 0

        # Would integrate with notification service
        logger.info("Would notify %s recipients", len(policy.notification_recipients))
        return len(policy.notification_recipients)


class RetentionEnforcementScheduler:
    """Automatic retention policy enforcement scheduler.

    Runs periodically to execute all enabled retention policies,
    supporting per-tenant overrides and audit trail logging.

    Integrates with the control plane for tenant-specific scheduling.
    """

    def __init__(
        self,
        manager: RetentionPolicyManager | None = None,
        interval_hours: float = 24.0,
        workspace_ids: list[str] | None = None,
    ) -> None:
        """Initialize the enforcement scheduler.

        Args:
            manager: RetentionPolicyManager to execute policies through.
            interval_hours: How often to run enforcement (default 24h).
            workspace_ids: Limit enforcement to specific workspaces (None = all).
        """
        self._manager = manager or RetentionPolicyManager()
        self._interval_seconds = int(interval_hours * 3600)
        self._workspace_ids = workspace_ids
        self._running = False
        self._task: Any = None
        self._enforcement_log: list[dict[str, Any]] = []

    @property
    def enforcement_log(self) -> list[dict[str, Any]]:
        """Get the enforcement audit trail."""
        return list(self._enforcement_log)

    async def start(self) -> None:
        """Start the enforcement scheduler background task."""
        if self._running:
            return
        self._running = True

        import asyncio

        self._task = asyncio.create_task(self._run_loop())
        self._task.add_done_callback(
            lambda t: logger.critical(
                "Retention enforcement scheduler crashed: %s — compliance processing stopped",
                t.exception(),
            )
            if not t.cancelled() and t.exception()
            else None
        )
        logger.info(
            "Started retention enforcement scheduler (interval=%ds, workspaces=%s)",
            self._interval_seconds,
            self._workspace_ids or "all",
        )

    async def stop(self) -> None:
        """Stop the enforcement scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            import asyncio

            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Stopped retention enforcement scheduler")

    async def run_once(self, dry_run: bool = False) -> list[DeletionReport]:
        """Execute a single enforcement run.

        Args:
            dry_run: If True, don't actually delete/archive.

        Returns:
            List of DeletionReport from each policy execution.
        """
        started_at = datetime.now(timezone.utc)
        reports: list[DeletionReport] = []

        # Get applicable policies
        policies = self._manager.list_policies()
        if self._workspace_ids:
            policies = [
                p
                for p in policies
                if p.workspace_ids is None
                or any(ws in p.workspace_ids for ws in self._workspace_ids)
            ]

        for policy in policies:
            if not policy.enabled:
                continue
            try:
                report = await self._manager.execute_policy(policy.id, dry_run=dry_run)
                reports.append(report)
            except (ValueError, RuntimeError, TypeError, KeyError) as e:
                logger.error("Enforcement error for policy %s: %s", policy.id, e)

        # Record audit entry
        duration = (datetime.now(timezone.utc) - started_at).total_seconds()
        log_entry = {
            "run_at": started_at.isoformat(),
            "duration_seconds": duration,
            "policies_executed": len(reports),
            "total_deleted": sum(r.items_deleted for r in reports),
            "total_archived": sum(r.items_archived for r in reports),
            "total_anonymized": sum(r.items_anonymized for r in reports),
            "total_failed": sum(r.items_failed for r in reports),
            "dry_run": dry_run,
            "workspace_ids": self._workspace_ids,
        }
        self._enforcement_log.append(log_entry)

        logger.info(
            "Retention enforcement complete: %d policies, %d deleted, %d archived (%.1fs)",
            len(reports),
            log_entry["total_deleted"],
            log_entry["total_archived"],
            duration,
        )

        return reports

    async def _run_loop(self) -> None:
        """Background loop for periodic enforcement."""
        import asyncio

        while self._running:
            try:
                await self.run_once()
            except (RuntimeError, OSError, ValueError, TypeError) as e:
                logger.error("Error in retention enforcement loop: %s", e)
            await asyncio.sleep(self._interval_seconds)


# Global instance
_retention_manager: RetentionPolicyManager | None = None


def get_retention_manager() -> RetentionPolicyManager:
    """Get or create the global retention manager."""
    global _retention_manager
    if _retention_manager is None:
        _retention_manager = RetentionPolicyManager()
    return _retention_manager


_enforcement_scheduler: RetentionEnforcementScheduler | None = None


def get_enforcement_scheduler() -> RetentionEnforcementScheduler:
    """Get or create the global enforcement scheduler."""
    global _enforcement_scheduler
    if _enforcement_scheduler is None:
        _enforcement_scheduler = RetentionEnforcementScheduler(manager=get_retention_manager())
    return _enforcement_scheduler


__all__ = [
    "RetentionPolicyManager",
    "RetentionPolicy",
    "RetentionAction",
    "DeletionReport",
    "DeletionRecord",
    "RetentionViolation",
    "RetentionEnforcementScheduler",
    "get_retention_manager",
    "get_enforcement_scheduler",
]
