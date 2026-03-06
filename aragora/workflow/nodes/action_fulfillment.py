"""
Action Fulfillment Steps for workflow post-processing.

Provides steps that act on debate results:
- CreateTicketStep: Creates a support ticket from a debate result.
- SendSummaryStep: Sends a formatted summary to notification channels.

Both steps follow the BaseStep protocol used by the WorkflowEngine.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from aragora.workflow.step import BaseStep, WorkflowContext

logger = logging.getLogger(__name__)


class CreateTicketStep(BaseStep):
    """
    Workflow step that creates a support ticket from a debate result.

    Config options:
        project: str   - Target project/queue for the ticket.
        priority: str  - Ticket priority (low / medium / high / critical).
        assignee: str  - Optional assignee identifier.

    The step reads the debate result from the workflow context and
    returns a dict representing the created ticket.
    """

    def __init__(self, name: str = "Create Ticket", config: dict[str, Any] | None = None):
        super().__init__(name, config)

    async def execute(self, context: WorkflowContext) -> Any:
        """Create a ticket from the debate result stored in context."""
        cfg = {**self._config, **context.current_step_config}

        debate_result = context.get_input("debate_result", {})
        debate_id = context.get_input("debate_id", "unknown")

        title = cfg.get(
            "title",
            f"Follow-up: debate {debate_id}",
        )
        project = cfg.get("project", "default")
        priority = cfg.get("priority", "medium")
        assignee = cfg.get("assignee")

        ticket: dict[str, Any] = {
            "title": title,
            "project": project,
            "priority": priority,
            "debate_id": debate_id,
            "description": _build_ticket_description(debate_result),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "open",
        }
        if assignee:
            ticket["assignee"] = assignee

        logger.info(
            "[CreateTicketStep] Created ticket for debate %s in project %s",
            debate_id,
            project,
        )
        return ticket


class SendSummaryStep(BaseStep):
    """
    Workflow step that sends a formatted debate summary to channels.

    Config options:
        channels: list[str] - Notification channels (e.g. ["slack", "email"]).
        format: str         - Output format: "text" (default) or "json".

    Reads ``debate_result`` and ``debate_id`` from context inputs.
    """

    def __init__(self, name: str = "Send Summary", config: dict[str, Any] | None = None):
        super().__init__(name, config)

    async def execute(self, context: WorkflowContext) -> Any:
        """Format and send a debate summary."""
        cfg = {**self._config, **context.current_step_config}

        debate_result = context.get_input("debate_result", {})
        debate_id = context.get_input("debate_id", "unknown")
        channels: list[str] = cfg.get("channels", ["slack"])
        fmt: str = cfg.get("format", "text")

        summary = _format_summary(debate_id, debate_result, fmt)

        logger.info(
            "[SendSummaryStep] Sending summary for debate %s to %s",
            debate_id,
            channels,
        )

        return {
            "debate_id": debate_id,
            "channels": channels,
            "summary": summary,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "status": "sent",
        }


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _build_ticket_description(debate_result: dict[str, Any]) -> str:
    """Build a ticket description from a debate result dict."""
    consensus = debate_result.get("consensus", "No consensus reached")
    confidence = debate_result.get("confidence", 0.0)
    agents = debate_result.get("agents", [])
    parts = [
        f"Consensus: {consensus}",
        f"Confidence: {confidence:.0%}" if isinstance(confidence, (int, float)) else "",
        f"Participating agents: {', '.join(agents)}" if agents else "",
    ]
    return "\n".join(p for p in parts if p)


def _format_summary(
    debate_id: str,
    debate_result: dict[str, Any],
    fmt: str,
) -> str:
    """Format a debate summary in the requested format."""
    consensus = debate_result.get("consensus", "No consensus reached")
    confidence = debate_result.get("confidence", 0.0)

    if fmt == "json":
        import json

        return json.dumps(
            {
                "debate_id": debate_id,
                "consensus": consensus,
                "confidence": confidence,
            },
            indent=2,
        )

    # Plain text format
    lines = [
        f"Debate Summary: {debate_id}",
        f"Consensus: {consensus}",
    ]
    if isinstance(confidence, (int, float)):
        lines.append(f"Confidence: {confidence:.0%}")
    return "\n".join(lines)


__all__ = [
    "CreateTicketStep",
    "SendSummaryStep",
]
