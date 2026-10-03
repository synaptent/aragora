"""
Finding Assignment Management.

Handles assignment of findings to users and teams, including
workload balancing and auto-assignment rules.

Usage:
    from aragora.audit.findings import AssignmentManager

    manager = AssignmentManager()

    # Assign finding to user
    assignment = manager.assign(
        finding_id="finding_123",
        user_id="user_456",
        assigned_by="user_789",
    )

    # Auto-assign based on rules
    manager.auto_assign(finding_id="finding_123")

    # Get user's assigned findings
    findings = manager.get_user_findings("user_456")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, cast
from collections.abc import Callable
from uuid import uuid4

from aragora.utils.datetime_helpers import parse_timestamp, utc_now


logger = logging.getLogger(__name__)


class AssignmentPriority(str, Enum):
    """Priority levels for finding assignments."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    DEFERRED = "deferred"


@dataclass
class FindingAssignment:
    """An assignment of a finding to a user or team."""

    id: str = field(default_factory=lambda: str(uuid4()))
    finding_id: str = ""
    session_id: str = ""  # Audit session this finding belongs to

    # Assignee
    user_id: str | None = None
    team_id: str | None = None
    user_name: str = ""
    team_name: str = ""

    # Assignment metadata
    assigned_by: str = ""
    assigned_by_name: str = ""
    assigned_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Priority and scheduling
    priority: AssignmentPriority = AssignmentPriority.MEDIUM
    due_date: datetime | None = None
    sla_hours: int | None = None  # Hours to resolution by priority

    # Status
    is_active: bool = True
    completed_at: datetime | None = None
    unassigned_at: datetime | None = None
    unassigned_by: str | None = None

    # Auto-assignment tracking
    auto_assigned: bool = False
    auto_assign_rule: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "finding_id": self.finding_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "team_id": self.team_id,
            "user_name": self.user_name,
            "team_name": self.team_name,
            "assigned_by": self.assigned_by,
            "assigned_by_name": self.assigned_by_name,
            "assigned_at": self.assigned_at.isoformat(),
            "priority": self.priority.value,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "sla_hours": self.sla_hours,
            "is_active": self.is_active,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "unassigned_at": self.unassigned_at.isoformat() if self.unassigned_at else None,
            "unassigned_by": self.unassigned_by,
            "auto_assigned": self.auto_assigned,
            "auto_assign_rule": self.auto_assign_rule,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FindingAssignment:
        """Create from dictionary."""

        return cls(
            id=data.get("id", str(uuid4())),
            finding_id=data.get("finding_id", ""),
            session_id=data.get("session_id", ""),
            user_id=data.get("user_id"),
            team_id=data.get("team_id"),
            user_name=data.get("user_name", ""),
            team_name=data.get("team_name", ""),
            assigned_by=data.get("assigned_by", ""),
            assigned_by_name=data.get("assigned_by_name", ""),
            assigned_at=cast(
                datetime,
                parse_timestamp(data.get("assigned_at"), default=utc_now()),
            ),
            priority=AssignmentPriority(data.get("priority", "medium")),
            due_date=parse_timestamp(data.get("due_date")),
            sla_hours=data.get("sla_hours"),
            is_active=data.get("is_active", True),
            completed_at=parse_timestamp(data.get("completed_at")),
            unassigned_at=parse_timestamp(data.get("unassigned_at")),
            unassigned_by=data.get("unassigned_by"),
            auto_assigned=data.get("auto_assigned", False),
            auto_assign_rule=data.get("auto_assign_rule", ""),
        )


@dataclass
class AutoAssignRule:
    """Rule for automatic assignment of findings."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    description: str = ""

    # Conditions (all must match)
    audit_type: str | None = None  # e.g., "security", "compliance"
    severity: str | None = None  # e.g., "critical", "high"
    category: str | None = None  # e.g., "exposed_credentials"
    tag: str | None = None  # Finding must have this tag

    # Assignment target
    user_id: str | None = None
    team_id: str | None = None

    # Priority override
    priority: AssignmentPriority | None = None
    sla_hours: int | None = None

    # Rule metadata
    is_active: bool = True
    priority_order: int = 0  # Lower = evaluated first
    workspace_id: str | None = None  # Scope to workspace

    def matches(
        self,
        finding_audit_type: str,
        finding_severity: str,
        finding_category: str,
        finding_tags: list[str],
    ) -> bool:
        """Check if this rule matches a finding."""
        if self.audit_type and self.audit_type != finding_audit_type:
            return False
        if self.severity and self.severity != finding_severity:
            return False
        if self.category and self.category != finding_category:
            return False
        if self.tag and self.tag not in finding_tags:
            return False
        return True


# Default SLA hours by severity
DEFAULT_SLA_HOURS = {
    AssignmentPriority.CRITICAL: 4,
    AssignmentPriority.HIGH: 24,
    AssignmentPriority.MEDIUM: 72,
    AssignmentPriority.LOW: 168,  # 1 week
    AssignmentPriority.DEFERRED: None,
}


class AssignmentManager:
    """
    Manages finding assignments.

    Provides assignment operations, workload tracking, and auto-assignment.
    This is an in-memory implementation; for persistence, subclass and
    override the storage methods.
    """

    def __init__(self):
        """Initialize assignment manager."""
        self._assignments: dict[str, FindingAssignment] = {}
        self._rules: list[AutoAssignRule] = []
        self._assignment_hooks: list[Callable[[FindingAssignment], None]] = []

    def assign(
        self,
        finding_id: str,
        user_id: str,
        *,
        assigned_by: str,
        session_id: str = "",
        team_id: str | None = None,
        priority: AssignmentPriority = AssignmentPriority.MEDIUM,
        due_date: datetime | None = None,
        sla_hours: int | None = None,
        user_name: str = "",
        team_name: str = "",
        assigned_by_name: str = "",
    ) -> FindingAssignment:
        """
        Assign a finding to a user.

        Args:
            finding_id: Finding to assign
            user_id: User to assign to
            assigned_by: User making the assignment
            session_id: Audit session ID
            team_id: Optional team to assign to
            priority: Assignment priority
            due_date: Explicit due date (overrides SLA calculation)
            sla_hours: Hours to resolution (overrides default)
            user_name: Display name of assignee
            team_name: Display name of team
            assigned_by_name: Display name of assigner

        Returns:
            The created assignment
        """
        # Deactivate any existing active assignment
        existing = self.get_assignment(finding_id)
        if existing and existing.is_active:
            existing.is_active = False
            existing.unassigned_at = datetime.now(timezone.utc)
            existing.unassigned_by = assigned_by

        # Calculate due date from SLA if not provided
        if due_date is None and sla_hours is None:
            sla_hours = DEFAULT_SLA_HOURS.get(priority)

        if due_date is None and sla_hours is not None:
            from datetime import timedelta

            due_date = datetime.now(timezone.utc) + timedelta(hours=sla_hours)

        assignment = FindingAssignment(
            finding_id=finding_id,
            session_id=session_id,
            user_id=user_id,
            team_id=team_id,
            user_name=user_name,
            team_name=team_name,
            assigned_by=assigned_by,
            assigned_by_name=assigned_by_name,
            priority=priority,
            due_date=due_date,
            sla_hours=sla_hours,
        )

        self._assignments[finding_id] = assignment

        # Notify hooks
        for hook in self._assignment_hooks:
            try:
                hook(assignment)
            except (ValueError, RuntimeError, OSError) as e:
                logger.warning("Assignment hook error: %s", e)

        logger.info(
            "Assigned finding %s to user %s (priority: %s)", finding_id, user_id, priority.value
        )

        return assignment

    def unassign(
        self,
        finding_id: str,
        *,
        unassigned_by: str,
    ) -> FindingAssignment | None:
        """
        Remove assignment from a finding.

        Args:
            finding_id: Finding to unassign
            unassigned_by: User removing the assignment

        Returns:
            The deactivated assignment, or None if not found
        """
        assignment = self._assignments.get(finding_id)
        if not assignment or not assignment.is_active:
            return None

        assignment.is_active = False
        assignment.unassigned_at = datetime.now(timezone.utc)
        assignment.unassigned_by = unassigned_by

        logger.info("Unassigned finding %s by %s", finding_id, unassigned_by)

        return assignment

    def complete(
        self,
        finding_id: str,
    ) -> FindingAssignment | None:
        """
        Mark an assignment as completed (finding resolved).

        Args:
            finding_id: Finding that was resolved

        Returns:
            The completed assignment, or None if not found
        """
        assignment = self._assignments.get(finding_id)
        if not assignment or not assignment.is_active:
            return None

        assignment.is_active = False
        assignment.completed_at = datetime.now(timezone.utc)

        logger.info("Completed assignment for finding %s", finding_id)

        return assignment

    def reassign(
        self,
        finding_id: str,
        new_user_id: str,
        *,
        reassigned_by: str,
        new_user_name: str = "",
        reassigned_by_name: str = "",
    ) -> FindingAssignment | None:
        """
        Reassign a finding to a different user.

        Preserves priority and due date from original assignment.
        """
        existing = self.get_assignment(finding_id)
        if not existing:
            return None

        return self.assign(
            finding_id=finding_id,
            user_id=new_user_id,
            assigned_by=reassigned_by,
            session_id=existing.session_id,
            team_id=existing.team_id,
            priority=existing.priority,
            due_date=existing.due_date,
            sla_hours=existing.sla_hours,
            user_name=new_user_name,
            team_name=existing.team_name,
            assigned_by_name=reassigned_by_name,
        )

    def get_assignment(self, finding_id: str) -> FindingAssignment | None:
        """Get the current assignment for a finding."""
        return self._assignments.get(finding_id)

    def get_user_assignments(
        self,
        user_id: str,
        *,
        active_only: bool = True,
    ) -> list[FindingAssignment]:
        """Get all assignments for a user."""
        return [
            a
            for a in self._assignments.values()
            if a.user_id == user_id and (not active_only or a.is_active)
        ]

    def get_team_assignments(
        self,
        team_id: str,
        *,
        active_only: bool = True,
    ) -> list[FindingAssignment]:
        """Get all assignments for a team."""
        return [
            a
            for a in self._assignments.values()
            if a.team_id == team_id and (not active_only or a.is_active)
        ]

    def get_overdue_assignments(self) -> list[FindingAssignment]:
        """Get all overdue active assignments."""
        now = datetime.now(timezone.utc)
        return [
            a for a in self._assignments.values() if a.is_active and a.due_date and a.due_date < now
        ]

    def get_user_workload(self, user_id: str) -> dict[str, int]:
        """
        Get workload summary for a user.

        Returns:
            Dictionary with counts by priority
        """
        assignments = self.get_user_assignments(user_id, active_only=True)
        counts: dict[str, int] = {p.value: 0 for p in AssignmentPriority}

        for a in assignments:
            counts[a.priority.value] += 1

        counts["total"] = len(assignments)
        return counts

    # Auto-assignment

    def add_rule(self, rule: AutoAssignRule) -> None:
        """Add an auto-assignment rule."""
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority_order)
        logger.debug("Added auto-assign rule: %s", rule.name)

    def remove_rule(self, rule_id: str) -> bool:
        """Remove an auto-assignment rule."""
        for i, rule in enumerate(self._rules):
            if rule.id == rule_id:
                self._rules.pop(i)
                return True
        return False

    def get_rules(self, workspace_id: str | None = None) -> list[AutoAssignRule]:
        """Get all auto-assignment rules, optionally filtered by workspace."""
        if workspace_id is None:
            return list(self._rules)
        return [r for r in self._rules if r.workspace_id is None or r.workspace_id == workspace_id]

    def auto_assign(
        self,
        finding_id: str,
        *,
        audit_type: str,
        severity: str,
        category: str,
        tags: list[str],
        session_id: str = "",
        workspace_id: str | None = None,
    ) -> FindingAssignment | None:
        """
        Automatically assign a finding based on rules.

        Evaluates rules in priority order and assigns to the first match.

        Args:
            finding_id: Finding to assign
            audit_type: Type of audit (e.g., "security")
            severity: Finding severity (e.g., "critical")
            category: Finding category (e.g., "exposed_credentials")
            tags: Finding tags
            session_id: Audit session ID
            workspace_id: Workspace to scope rules to

        Returns:
            The created assignment if a rule matched, None otherwise
        """
        for rule in self._rules:
            if not rule.is_active:
                continue

            # Check workspace scope
            if rule.workspace_id and rule.workspace_id != workspace_id:
                continue

            # Check if rule matches
            if not rule.matches(audit_type, severity, category, tags):
                continue

            # Found a matching rule
            if not rule.user_id and not rule.team_id:
                logger.warning("Rule %s has no assignment target", rule.name)
                continue

            priority = rule.priority or self._severity_to_priority(severity)

            assignment = FindingAssignment(
                finding_id=finding_id,
                session_id=session_id,
                user_id=rule.user_id,
                team_id=rule.team_id,
                priority=priority,
                sla_hours=rule.sla_hours or DEFAULT_SLA_HOURS.get(priority),
                auto_assigned=True,
                auto_assign_rule=rule.name,
            )

            # Calculate due date
            if assignment.sla_hours:
                from datetime import timedelta

                assignment.due_date = datetime.now(timezone.utc) + timedelta(
                    hours=assignment.sla_hours
                )

            self._assignments[finding_id] = assignment

            logger.info(
                "Auto-assigned finding %s via rule '%s' to user=%s team=%s",
                finding_id,
                rule.name,
                rule.user_id,
                rule.team_id,
            )

            return assignment

        return None

    def _severity_to_priority(self, severity: str) -> AssignmentPriority:
        """Map finding severity to assignment priority."""
        mapping = {
            "critical": AssignmentPriority.CRITICAL,
            "high": AssignmentPriority.HIGH,
            "medium": AssignmentPriority.MEDIUM,
            "low": AssignmentPriority.LOW,
            "info": AssignmentPriority.DEFERRED,
        }
        return mapping.get(severity.lower(), AssignmentPriority.MEDIUM)

    # Hooks

    def add_assignment_hook(self, hook: Callable[[FindingAssignment], None]) -> None:
        """Add a callback for new assignments."""
        self._assignment_hooks.append(hook)

    # Bulk operations

    def bulk_assign(
        self,
        finding_ids: list[str],
        user_id: str,
        *,
        assigned_by: str,
        priority: AssignmentPriority = AssignmentPriority.MEDIUM,
        **kwargs: Any,
    ) -> list[FindingAssignment]:
        """Assign multiple findings to a user."""
        return [
            self.assign(
                finding_id=fid,
                user_id=user_id,
                assigned_by=assigned_by,
                priority=priority,
                **kwargs,
            )
            for fid in finding_ids
        ]

    def bulk_unassign(
        self,
        finding_ids: list[str],
        *,
        unassigned_by: str,
    ) -> list[FindingAssignment]:
        """Unassign multiple findings."""
        results = []
        for fid in finding_ids:
            result = self.unassign(fid, unassigned_by=unassigned_by)
            if result:
                results.append(result)
        return results


# Singleton instance
_assignment_manager: AssignmentManager | None = None


def get_assignment_manager() -> AssignmentManager:
    """Get the global assignment manager instance."""
    global _assignment_manager
    if _assignment_manager is None:
        _assignment_manager = AssignmentManager()
    return _assignment_manager
