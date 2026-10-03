"""
Finding Workflow State Machine.

Manages the lifecycle of audit findings from discovery to resolution.

States:
    OPEN → TRIAGING → INVESTIGATING → REMEDIATING → RESOLVED
                                                  → FALSE_POSITIVE
                                                  → ACCEPTED_RISK

Each transition is recorded with timestamp, user, and optional comment.
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


class WorkflowState(str, Enum):
    """Workflow states for audit findings."""

    # Initial state
    OPEN = "open"

    # Triage phase
    TRIAGING = "triaging"

    # Investigation phase
    INVESTIGATING = "investigating"

    # Remediation phase
    REMEDIATING = "remediating"

    # Terminal states
    RESOLVED = "resolved"
    FALSE_POSITIVE = "false_positive"
    ACCEPTED_RISK = "accepted_risk"
    DUPLICATE = "duplicate"

    # Legacy states (for backward compatibility)
    ACKNOWLEDGED = "acknowledged"  # Maps to TRIAGING
    WONT_FIX = "wont_fix"  # Maps to ACCEPTED_RISK


# Valid state transitions
VALID_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.OPEN: {
        WorkflowState.TRIAGING,
        WorkflowState.INVESTIGATING,
        WorkflowState.FALSE_POSITIVE,
        WorkflowState.DUPLICATE,
    },
    WorkflowState.TRIAGING: {
        WorkflowState.INVESTIGATING,
        WorkflowState.FALSE_POSITIVE,
        WorkflowState.ACCEPTED_RISK,
        WorkflowState.DUPLICATE,
        WorkflowState.OPEN,  # Can reopen
    },
    WorkflowState.INVESTIGATING: {
        WorkflowState.REMEDIATING,
        WorkflowState.FALSE_POSITIVE,
        WorkflowState.ACCEPTED_RISK,
        WorkflowState.TRIAGING,  # Can go back to triage
    },
    WorkflowState.REMEDIATING: {
        WorkflowState.RESOLVED,
        WorkflowState.INVESTIGATING,  # Go back if fix didn't work
        WorkflowState.ACCEPTED_RISK,
    },
    WorkflowState.RESOLVED: {
        WorkflowState.OPEN,  # Can reopen if issue recurs
    },
    WorkflowState.FALSE_POSITIVE: {
        WorkflowState.OPEN,  # Can reopen if wrongly classified
    },
    WorkflowState.ACCEPTED_RISK: {
        WorkflowState.OPEN,  # Risk tolerance may change
        WorkflowState.REMEDIATING,  # Decide to fix after all
    },
    WorkflowState.DUPLICATE: {
        WorkflowState.OPEN,  # Wrongly marked as duplicate
    },
    # Legacy mappings
    WorkflowState.ACKNOWLEDGED: {
        WorkflowState.INVESTIGATING,
        WorkflowState.FALSE_POSITIVE,
    },
    WorkflowState.WONT_FIX: {
        WorkflowState.OPEN,
    },
}


class WorkflowEventType(str, Enum):
    """Types of workflow events."""

    STATE_CHANGE = "state_change"
    ASSIGNMENT = "assignment"
    COMMENT = "comment"
    PRIORITY_CHANGE = "priority_change"
    DUE_DATE_CHANGE = "due_date_change"
    TAG_ADDED = "tag_added"
    TAG_REMOVED = "tag_removed"
    LINKED = "linked"
    UNLINKED = "unlinked"
    SEVERITY_CHANGE = "severity_change"


@dataclass
class WorkflowEvent:
    """An event in the finding's workflow history."""

    id: str = field(default_factory=lambda: str(uuid4()))
    finding_id: str = ""
    event_type: WorkflowEventType = WorkflowEventType.STATE_CHANGE
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Who made this change
    user_id: str = ""
    user_name: str = ""

    # State change details
    from_state: WorkflowState | None = None
    to_state: WorkflowState | None = None

    # Generic change data
    field_name: str = ""
    old_value: Any = None
    new_value: Any = None

    # Comment
    comment: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "finding_id": self.finding_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "user_name": self.user_name,
            "from_state": self.from_state.value if self.from_state else None,
            "to_state": self.to_state.value if self.to_state else None,
            "field_name": self.field_name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "comment": self.comment,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowEvent:
        """Create from dictionary."""
        return cls(
            id=data.get("id", str(uuid4())),
            finding_id=data.get("finding_id", ""),
            event_type=WorkflowEventType(data.get("event_type", "state_change")),
            timestamp=(
                datetime.fromisoformat(data["timestamp"])
                if isinstance(data.get("timestamp"), str)
                else datetime.now(timezone.utc)
            ),
            user_id=data.get("user_id", ""),
            user_name=data.get("user_name", ""),
            from_state=(WorkflowState(data["from_state"]) if data.get("from_state") else None),
            to_state=(WorkflowState(data["to_state"]) if data.get("to_state") else None),
            field_name=data.get("field_name", ""),
            old_value=data.get("old_value"),
            new_value=data.get("new_value"),
            comment=data.get("comment", ""),
        )


@dataclass
class WorkflowTransition:
    """Record of a state transition."""

    from_state: WorkflowState
    to_state: WorkflowState
    timestamp: datetime
    user_id: str
    comment: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class WorkflowError(Exception):
    """Error in workflow operation."""

    pass


class InvalidTransitionError(WorkflowError):
    """Invalid state transition attempted."""

    def __init__(self, from_state: WorkflowState, to_state: WorkflowState):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Cannot transition from {from_state.value} to {to_state.value}")


@dataclass
class FindingWorkflowData:
    """Workflow data for a finding."""

    finding_id: str
    current_state: WorkflowState = WorkflowState.OPEN
    history: list[WorkflowEvent] = field(default_factory=list)

    # Assignment
    assigned_to: str | None = None
    assigned_by: str | None = None
    assigned_at: datetime | None = None

    # Priority and scheduling
    priority: int = 3  # 1=highest, 5=lowest
    due_date: datetime | None = None

    # Linked findings
    linked_findings: list[str] = field(default_factory=list)
    parent_finding_id: str | None = None  # For duplicates

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None

    # Metrics
    time_in_states: dict[str, float] = field(default_factory=dict)
    state_entered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "finding_id": self.finding_id,
            "current_state": self.current_state.value,
            "history": [e.to_dict() for e in self.history],
            "assigned_to": self.assigned_to,
            "assigned_by": self.assigned_by,
            "assigned_at": self.assigned_at.isoformat() if self.assigned_at else None,
            "priority": self.priority,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "linked_findings": self.linked_findings,
            "parent_finding_id": self.parent_finding_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "time_in_states": self.time_in_states,
            "state_entered_at": self.state_entered_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FindingWorkflowData:
        """Create from dictionary."""

        return cls(
            finding_id=data.get("finding_id", ""),
            current_state=WorkflowState(data.get("current_state", "open")),
            history=[WorkflowEvent.from_dict(e) for e in data.get("history", [])],
            assigned_to=data.get("assigned_to"),
            assigned_by=data.get("assigned_by"),
            assigned_at=parse_timestamp(data.get("assigned_at")),
            priority=data.get("priority", 3),
            due_date=parse_timestamp(data.get("due_date")),
            linked_findings=data.get("linked_findings", []),
            parent_finding_id=data.get("parent_finding_id"),
            created_at=cast(datetime, parse_timestamp(data.get("created_at"), default=utc_now())),
            updated_at=cast(datetime, parse_timestamp(data.get("updated_at"), default=utc_now())),
            resolved_at=parse_timestamp(data.get("resolved_at")),
            time_in_states=data.get("time_in_states", {}),
            state_entered_at=cast(
                datetime,
                parse_timestamp(data.get("state_entered_at"), default=utc_now()),
            ),
        )


class FindingWorkflow:
    """
    State machine for finding workflow management.

    Handles state transitions, assignment, comments, and history tracking.

    Usage:
        workflow = FindingWorkflow(data)

        # Transition state
        workflow.transition_to(WorkflowState.INVESTIGATING, user_id="user_123")

        # Assign
        workflow.assign(user_id="user_456", assigned_by="user_123")

        # Add comment
        workflow.add_comment("Initial review complete.", user_id="user_123")
    """

    def __init__(
        self,
        data: FindingWorkflowData | None = None,
        finding_id: str = "",
    ):
        """
        Initialize workflow.

        Args:
            data: Existing workflow data to use
            finding_id: Finding ID (required if data not provided)
        """
        if data:
            self.data = data
        elif finding_id:
            self.data = FindingWorkflowData(finding_id=finding_id)
        else:
            raise ValueError("Either data or finding_id must be provided")

        self._transition_hooks: list[Callable[[WorkflowTransition], None]] = []

    @property
    def state(self) -> WorkflowState:
        """Current workflow state."""
        return self.data.current_state

    @property
    def history(self) -> list[WorkflowEvent]:
        """Workflow history."""
        return self.data.history

    @property
    def is_terminal(self) -> bool:
        """Whether workflow is in a terminal state."""
        return self.state in {
            WorkflowState.RESOLVED,
            WorkflowState.FALSE_POSITIVE,
            WorkflowState.ACCEPTED_RISK,
            WorkflowState.DUPLICATE,
        }

    def can_transition_to(self, to_state: WorkflowState) -> bool:
        """Check if transition to state is valid."""
        valid = VALID_TRANSITIONS.get(self.state, set())
        return to_state in valid

    def get_valid_transitions(self) -> list[WorkflowState]:
        """Get list of valid next states."""
        return list(VALID_TRANSITIONS.get(self.state, set()))

    def transition_to(
        self,
        to_state: WorkflowState,
        *,
        user_id: str,
        user_name: str = "",
        comment: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowEvent:
        """
        Transition to a new state.

        Args:
            to_state: Target state
            user_id: User making the transition
            user_name: Display name of user
            comment: Optional comment explaining transition
            metadata: Optional metadata

        Returns:
            The workflow event created

        Raises:
            InvalidTransitionError: If transition is not valid
        """
        if not self.can_transition_to(to_state):
            raise InvalidTransitionError(self.state, to_state)

        from_state = self.state
        now = datetime.now(timezone.utc)

        # Update time in state metrics
        time_in_current = (now - self.data.state_entered_at).total_seconds()
        state_key = from_state.value
        self.data.time_in_states[state_key] = (
            self.data.time_in_states.get(state_key, 0) + time_in_current
        )

        # Create event
        event = WorkflowEvent(
            finding_id=self.data.finding_id,
            event_type=WorkflowEventType.STATE_CHANGE,
            timestamp=now,
            user_id=user_id,
            user_name=user_name,
            from_state=from_state,
            to_state=to_state,
            comment=comment,
        )

        # Update state
        self.data.current_state = to_state
        self.data.state_entered_at = now
        self.data.updated_at = now
        self.data.history.append(event)

        # Track resolution time
        if to_state == WorkflowState.RESOLVED:
            self.data.resolved_at = now

        # Create transition record for hooks
        transition = WorkflowTransition(
            from_state=from_state,
            to_state=to_state,
            timestamp=now,
            user_id=user_id,
            comment=comment,
            metadata=metadata or {},
        )

        # Call hooks
        for hook in self._transition_hooks:
            try:
                hook(transition)
            except (ValueError, RuntimeError, OSError) as e:
                logger.warning("Transition hook error: %s", e)

        logger.info(
            "Finding %s transitioned: %s → %s by %s",
            self.data.finding_id,
            from_state.value,
            to_state.value,
            user_id,
        )

        return event

    def assign(
        self,
        user_id: str,
        *,
        assigned_by: str,
        assigned_by_name: str = "",
        comment: str = "",
    ) -> WorkflowEvent:
        """
        Assign finding to a user.

        Args:
            user_id: User to assign to
            assigned_by: User making the assignment
            assigned_by_name: Display name of assigning user
            comment: Optional comment

        Returns:
            The workflow event created
        """
        now = datetime.now(timezone.utc)
        old_assignee = self.data.assigned_to

        # Update assignment
        self.data.assigned_to = user_id
        self.data.assigned_by = assigned_by
        self.data.assigned_at = now
        self.data.updated_at = now

        # Create event
        event = WorkflowEvent(
            finding_id=self.data.finding_id,
            event_type=WorkflowEventType.ASSIGNMENT,
            timestamp=now,
            user_id=assigned_by,
            user_name=assigned_by_name,
            field_name="assigned_to",
            old_value=old_assignee,
            new_value=user_id,
            comment=comment,
        )

        self.data.history.append(event)

        logger.info("Finding %s assigned to %s by %s", self.data.finding_id, user_id, assigned_by)

        return event

    def unassign(
        self,
        *,
        user_id: str,
        user_name: str = "",
        comment: str = "",
    ) -> WorkflowEvent:
        """Remove assignment from finding."""
        now = datetime.now(timezone.utc)
        old_assignee = self.data.assigned_to

        self.data.assigned_to = None
        self.data.assigned_by = None
        self.data.assigned_at = None
        self.data.updated_at = now

        event = WorkflowEvent(
            finding_id=self.data.finding_id,
            event_type=WorkflowEventType.ASSIGNMENT,
            timestamp=now,
            user_id=user_id,
            user_name=user_name,
            field_name="assigned_to",
            old_value=old_assignee,
            new_value=None,
            comment=comment,
        )

        self.data.history.append(event)
        return event

    def add_comment(
        self,
        comment: str,
        *,
        user_id: str,
        user_name: str = "",
    ) -> WorkflowEvent:
        """
        Add a comment to the finding.

        Args:
            comment: The comment text
            user_id: User adding the comment
            user_name: Display name of user

        Returns:
            The workflow event created
        """
        now = datetime.now(timezone.utc)

        event = WorkflowEvent(
            finding_id=self.data.finding_id,
            event_type=WorkflowEventType.COMMENT,
            timestamp=now,
            user_id=user_id,
            user_name=user_name,
            comment=comment,
        )

        self.data.history.append(event)
        self.data.updated_at = now

        return event

    def set_priority(
        self,
        priority: int,
        *,
        user_id: str,
        user_name: str = "",
        comment: str = "",
    ) -> WorkflowEvent:
        """Set finding priority (1=highest, 5=lowest)."""
        if not 1 <= priority <= 5:
            raise ValueError("Priority must be between 1 and 5")

        now = datetime.now(timezone.utc)
        old_priority = self.data.priority

        self.data.priority = priority
        self.data.updated_at = now

        event = WorkflowEvent(
            finding_id=self.data.finding_id,
            event_type=WorkflowEventType.PRIORITY_CHANGE,
            timestamp=now,
            user_id=user_id,
            user_name=user_name,
            field_name="priority",
            old_value=old_priority,
            new_value=priority,
            comment=comment,
        )

        self.data.history.append(event)
        return event

    def set_due_date(
        self,
        due_date: datetime | None,
        *,
        user_id: str,
        user_name: str = "",
        comment: str = "",
    ) -> WorkflowEvent:
        """Set or clear due date."""
        now = datetime.now(timezone.utc)
        old_due = self.data.due_date

        self.data.due_date = due_date
        self.data.updated_at = now

        event = WorkflowEvent(
            finding_id=self.data.finding_id,
            event_type=WorkflowEventType.DUE_DATE_CHANGE,
            timestamp=now,
            user_id=user_id,
            user_name=user_name,
            field_name="due_date",
            old_value=old_due.isoformat() if old_due else None,
            new_value=due_date.isoformat() if due_date else None,
            comment=comment,
        )

        self.data.history.append(event)
        return event

    def link_finding(
        self,
        linked_finding_id: str,
        *,
        user_id: str,
        user_name: str = "",
        comment: str = "",
    ) -> WorkflowEvent:
        """Link this finding to another finding."""
        now = datetime.now(timezone.utc)

        if linked_finding_id not in self.data.linked_findings:
            self.data.linked_findings.append(linked_finding_id)
            self.data.updated_at = now

        event = WorkflowEvent(
            finding_id=self.data.finding_id,
            event_type=WorkflowEventType.LINKED,
            timestamp=now,
            user_id=user_id,
            user_name=user_name,
            field_name="linked_findings",
            new_value=linked_finding_id,
            comment=comment,
        )

        self.data.history.append(event)
        return event

    def mark_duplicate(
        self,
        parent_finding_id: str,
        *,
        user_id: str,
        user_name: str = "",
        comment: str = "",
    ) -> WorkflowEvent:
        """Mark this finding as a duplicate of another."""
        self.data.parent_finding_id = parent_finding_id

        # Transition to DUPLICATE state
        transition_event = self.transition_to(
            WorkflowState.DUPLICATE,
            user_id=user_id,
            user_name=user_name,
            comment=comment or f"Duplicate of {parent_finding_id}",
        )

        # Link to parent
        self.link_finding(
            parent_finding_id,
            user_id=user_id,
            user_name=user_name,
            comment="Parent finding",
        )

        return transition_event

    def change_severity(
        self,
        new_severity: str,
        *,
        old_severity: str,
        user_id: str,
        user_name: str = "",
        comment: str = "",
    ) -> WorkflowEvent:
        """Record a severity change (actual change happens in finding model)."""
        now = datetime.now(timezone.utc)

        event = WorkflowEvent(
            finding_id=self.data.finding_id,
            event_type=WorkflowEventType.SEVERITY_CHANGE,
            timestamp=now,
            user_id=user_id,
            user_name=user_name,
            field_name="severity",
            old_value=old_severity,
            new_value=new_severity,
            comment=comment,
        )

        self.data.history.append(event)
        self.data.updated_at = now
        return event

    def add_transition_hook(self, hook: Callable[[WorkflowTransition], None]) -> None:
        """Add a callback for state transitions."""
        self._transition_hooks.append(hook)

    def get_time_to_resolution(self) -> float | None:
        """Get total time from open to resolved in seconds."""
        if not self.data.resolved_at:
            return None
        return (self.data.resolved_at - self.data.created_at).total_seconds()

    def get_comments(self) -> list[WorkflowEvent]:
        """Get all comments on this finding."""
        return [e for e in self.data.history if e.event_type == WorkflowEventType.COMMENT]

    def get_state_changes(self) -> list[WorkflowEvent]:
        """Get all state change events."""
        return [e for e in self.data.history if e.event_type == WorkflowEventType.STATE_CHANGE]


# State machine visualization helpers


def get_workflow_diagram() -> str:
    """Get ASCII representation of workflow states."""
    return """
    Finding Workflow State Machine:

    ┌───────────────────────────────────────────────────────────────┐
    │                                                               │
    │   ┌──────┐    ┌──────────┐    ┌──────────────┐    ┌────────┐ │
    │   │ OPEN │───►│ TRIAGING │───►│ INVESTIGATING│───►│REMEDIAT│ │
    │   └──────┘    └──────────┘    └──────────────┘    │  ING   │ │
    │       │            │                  │           └────────┘ │
    │       │            │                  │                │     │
    │       │            ▼                  ▼                ▼     │
    │       │     ┌─────────────────────────────────────────────┐  │
    │       │     │           Terminal States                   │  │
    │       │     │  ┌──────────┐ ┌───────────────┐ ┌────────┐  │  │
    │       └────►│  │ FALSE    │ │ ACCEPTED_RISK │ │RESOLVED│  │  │
    │             │  │ POSITIVE │ │               │ │        │  │  │
    │             │  └──────────┘ └───────────────┘ └────────┘  │  │
    │             │  ┌───────────┐                              │  │
    │             │  │ DUPLICATE │                              │  │
    │             │  └───────────┘                              │  │
    │             └─────────────────────────────────────────────┘  │
    │                                                               │
    │   Note: Terminal states can transition back to OPEN           │
    └───────────────────────────────────────────────────────────────┘
    """


def map_legacy_status(status: str) -> WorkflowState:
    """Map legacy FindingStatus values to WorkflowState."""
    mapping = {
        "open": WorkflowState.OPEN,
        "acknowledged": WorkflowState.TRIAGING,
        "resolved": WorkflowState.RESOLVED,
        "false_positive": WorkflowState.FALSE_POSITIVE,
        "wont_fix": WorkflowState.ACCEPTED_RISK,
    }
    return mapping.get(status.lower(), WorkflowState.OPEN)
