"""
Escalation Workflow Pattern - Multi-level escalation paths for debates.

Defines escalation steps with configurable delays, notification channels,
and actions (notify, reassign, executive_summary).  Includes a standard
3-tier escalation path (team-lead -> manager -> executive).

Usage:
    from aragora.workflow.patterns.escalation import (
        EscalationWorkflowPattern,
        STANDARD_ESCALATION_PATH,
    )

    pattern = EscalationWorkflowPattern()
    workflow = pattern.create_workflow(debate_id="debate-1")
    result = pattern.trigger_escalation("debate-1", level=1, context={})
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass
class EscalationStep:
    """A single step in an escalation path."""

    level: int
    delay_minutes: int
    notify_channels: list[str]
    action: str  # "notify" | "reassign" | "executive_summary"


@dataclass
class EscalationPathConfig:
    """Configuration for an escalation path."""

    steps: list[EscalationStep] = field(default_factory=list)


#: Standard 3-tier escalation: team-lead (15m), manager (30m), executive (60m).
STANDARD_ESCALATION_PATH = EscalationPathConfig(
    steps=[
        EscalationStep(
            level=1,
            delay_minutes=15,
            notify_channels=["slack", "email"],
            action="notify",
        ),
        EscalationStep(
            level=2,
            delay_minutes=30,
            notify_channels=["slack", "email", "sms"],
            action="reassign",
        ),
        EscalationStep(
            level=3,
            delay_minutes=60,
            notify_channels=["slack", "email", "sms", "pager"],
            action="executive_summary",
        ),
    ]
)


class EscalationWorkflowPattern:
    """
    Creates and triggers escalation workflows for debates.

    Generates a workflow definition from an escalation path and provides
    a ``trigger_escalation`` helper to produce an escalation record.
    """

    def create_workflow(
        self,
        debate_id: str,
        config: EscalationPathConfig | None = None,
    ) -> dict[str, Any]:
        """
        Build a workflow definition dict for a debate escalation.

        Args:
            debate_id: The debate this escalation targets.
            config: Escalation path (defaults to STANDARD_ESCALATION_PATH).

        Returns:
            A dict describing the workflow steps and metadata.
        """
        path = config or STANDARD_ESCALATION_PATH
        workflow_id = f"escalation_{uuid4().hex[:8]}"

        steps: list[dict[str, Any]] = []
        for step in path.steps:
            steps.append(
                {
                    "id": f"escalation_level_{step.level}",
                    "name": f"Escalation Level {step.level}",
                    "level": step.level,
                    "delay_minutes": step.delay_minutes,
                    "notify_channels": step.notify_channels,
                    "action": step.action,
                }
            )

        return {
            "id": workflow_id,
            "name": f"Escalation for {debate_id}",
            "debate_id": debate_id,
            "steps": steps,
            "total_levels": len(steps),
        }

    def trigger_escalation(
        self,
        debate_id: str,
        level: int,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute an escalation at the given level.

        Args:
            debate_id: Target debate identifier.
            level: Escalation level (1-based).
            context: Optional contextual data attached to the escalation.

        Returns:
            Dict describing the triggered escalation event.
        """
        ctx = context or {}
        return {
            "debate_id": debate_id,
            "level": level,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "context": ctx,
            "status": "triggered",
        }


__all__ = [
    "EscalationStep",
    "EscalationPathConfig",
    "EscalationWorkflowPattern",
    "STANDARD_ESCALATION_PATH",
]
