"""
Human Checkpoint Step for workflow approval gates.

Provides human-in-the-loop approval for critical workflow steps with:
- Configurable approval checklists
- Timeout with escalation
- Approval/rejection branching
- Audit logging
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from collections.abc import Callable

from aragora.workflow.safe_eval import SafeEvalError, safe_eval_bool
from aragora.workflow.step import BaseStep, WorkflowContext

logger = logging.getLogger(__name__)

# Lazy-loaded governance store for persistence
_governance_store = None


def _get_governance_store():
    """Get or create the governance store for approval persistence."""
    global _governance_store
    if _governance_store is None:
        try:
            from aragora.storage.governance_store import get_governance_store

            _governance_store = get_governance_store()
        except (ImportError, RuntimeError, OSError) as e:
            logger.debug("Governance store not available: %s", e)
    return _governance_store


class ApprovalStatus(Enum):
    """Status of a human approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    TIMEOUT = "timeout"


@dataclass
class ChecklistItem:
    """An item in the approval checklist."""

    id: str
    label: str
    required: bool = True
    checked: bool = False
    notes: str = ""


@dataclass
class ApprovalRequest:
    """A human approval request."""

    id: str
    workflow_id: str
    step_id: str
    title: str
    description: str
    checklist: list[ChecklistItem]
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    responded_at: datetime | None = None
    responder_id: str | None = None
    responder_notes: str = ""
    timeout_seconds: float = 3600.0
    escalation_emails: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "title": self.title,
            "description": self.description,
            "checklist": [
                {
                    "id": c.id,
                    "label": c.label,
                    "required": c.required,
                    "checked": c.checked,
                    "notes": c.notes,
                }
                for c in self.checklist
            ],
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "responded_at": self.responded_at.isoformat() if self.responded_at else None,
            "responder_id": self.responder_id,
            "responder_notes": self.responder_notes,
            "timeout_seconds": self.timeout_seconds,
            "escalation_emails": self.escalation_emails,
        }


# In-memory store for approval requests (backed by GovernanceStore for persistence)
_pending_approvals: dict[str, ApprovalRequest] = {}
_approvals_recovered: bool = False


def recover_pending_approvals() -> int:
    """
    Recover pending approvals from GovernanceStore into memory.

    Call this on server startup to ensure workflows can resume
    after a restart. Returns the number of approvals recovered.

    This function is idempotent - calling it multiple times is safe.
    """
    global _pending_approvals, _approvals_recovered
    import json

    if _approvals_recovered:
        logger.debug("Approvals already recovered, skipping")
        return 0

    store = _get_governance_store()
    if not store:
        logger.debug("GovernanceStore not available, cannot recover approvals")
        return 0

    recovered = 0
    try:
        # Query all pending approvals from persistent store
        pending_records = store.list_approvals(status="pending")

        for record in pending_records:
            if record.approval_id in _pending_approvals:
                continue  # Already in memory

            # Reconstruct ApprovalRequest from stored record
            metadata = {}
            if record.metadata_json:
                try:
                    metadata = json.loads(record.metadata_json)
                except (json.JSONDecodeError, TypeError) as e:
                    logger.debug("Failed to parse JSON data: %s", e)

            # Reconstruct checklist from stored metadata
            checklist = []
            for item in metadata.get("checklist", []):
                checklist.append(
                    ChecklistItem(
                        id=item.get("id", ""),
                        label=item.get("label", ""),
                        required=item.get("required", True),
                        checked=item.get("checked", False),
                        notes=item.get("notes", ""),
                    )
                )

            request = ApprovalRequest(
                id=record.approval_id,
                workflow_id=metadata.get("workflow_id", "unknown"),
                step_id=metadata.get("step_id", "unknown"),
                title=record.title,
                description=record.description,
                checklist=checklist,
                status=ApprovalStatus(record.status),
                created_at=record.requested_at,
                timeout_seconds=float(record.timeout_seconds),
                escalation_emails=metadata.get("escalation_emails", []),
                responder_id=record.approved_by,
                responded_at=record.approved_at,
            )
            _pending_approvals[record.approval_id] = request
            recovered += 1

        _approvals_recovered = True
        if recovered > 0:
            logger.info("Recovered %s pending approvals from GovernanceStore", recovered)

    except (RuntimeError, ValueError, TypeError, OSError, AttributeError, KeyError) as e:
        logger.warning("Failed to recover approvals from GovernanceStore: %s", e)

    return recovered


def reset_approval_recovery() -> None:
    """Reset recovery state (for testing)."""
    global _approvals_recovered
    _approvals_recovered = False


def clear_pending_approvals() -> int:
    """Clear all pending approvals from memory (for testing). Returns count cleared."""
    count = len(_pending_approvals)
    _pending_approvals.clear()
    return count


class HumanCheckpointStep(BaseStep):
    """
    Human checkpoint step for workflow approval gates.

    Config options:
        title: str - Title of the approval request
        description: str - Detailed description for the approver
        checklist: list[dict] - Checklist items [{label, required}]
        timeout_seconds: float - Timeout before escalation (default 3600)
        escalation_emails: list[str] - Emails to notify on timeout
        auto_approve_if: str - Python expression for auto-approval
        require_all_checklist: bool - Require all checklist items (default True)

    Usage:
        step = HumanCheckpointStep(
            name="Legal Review",
            config={
                "title": "Legal Review Required",
                "description": "Please review the contract terms",
                "checklist": [
                    {"label": "Verified compliance terms", "required": True},
                    {"label": "Checked indemnification clause", "required": True},
                ],
                "timeout_seconds": 7200,
                "escalation_emails": ["legal-lead@company.com"],
            }
        )
    """

    # Callback for notifying about new approval requests
    on_approval_requested: Callable[[ApprovalRequest], None] | None = None

    def __init__(self, name: str, config: dict[str, Any] | None = None):
        super().__init__(name, config)

    async def execute(self, context: WorkflowContext) -> Any:
        """Execute the human checkpoint step."""
        config = {**self._config, **context.current_step_config}

        # Build checklist from config
        checklist_config = config.get("checklist", [])
        checklist = [
            ChecklistItem(
                id=f"item_{i}",
                label=item.get("label", f"Item {i + 1}"),
                required=item.get("required", True),
            )
            for i, item in enumerate(checklist_config)
        ]

        # Check auto-approval condition
        auto_approve_condition = config.get("auto_approve_if", "")
        if auto_approve_condition:
            if self._evaluate_condition(auto_approve_condition, context):
                logger.info("Auto-approving checkpoint '%s' based on condition", self.name)
                return {
                    "status": "approved",
                    "auto_approved": True,
                    "condition": auto_approve_condition,
                }

        # Create approval request
        request = ApprovalRequest(
            id=f"apr_{uuid.uuid4().hex[:12]}",
            workflow_id=context.workflow_id,
            step_id=context.current_step_id or self.name,
            title=config.get("title", f"Approval Required: {self.name}"),
            description=self._build_description(config, context),
            checklist=checklist,
            timeout_seconds=config.get("timeout_seconds", 3600.0),
            escalation_emails=config.get("escalation_emails", []),
        )

        # Store the request in memory
        _pending_approvals[request.id] = request
        logger.info("Created approval request %s for checkpoint '%s'", request.id, self.name)

        # Persist to GovernanceStore for durability
        store = _get_governance_store()
        if store:
            try:
                store.save_approval(
                    approval_id=request.id,
                    title=request.title,
                    description=request.description,
                    risk_level="medium",  # Could be made configurable
                    status="pending",
                    requested_by=context.inputs.get("user_id", "system"),
                    changes=[{"type": "workflow_checkpoint", "step": request.step_id}],
                    timeout_seconds=int(request.timeout_seconds),
                    metadata={
                        "workflow_id": request.workflow_id,
                        "step_id": request.step_id,
                        "escalation_emails": request.escalation_emails,
                        "checklist": [
                            {"id": c.id, "label": c.label, "required": c.required}
                            for c in request.checklist
                        ],
                    },
                )
            except (RuntimeError, OSError, ValueError, TypeError) as e:
                logger.warning("Failed to persist approval to store: %s", e)

        # Notify listeners
        if self.on_approval_requested:
            try:
                self.on_approval_requested(request)
            except (RuntimeError, ValueError, TypeError, OSError, AttributeError) as e:
                logger.warning("Failed to notify approval listener: %s", e)

        # Send notifications via notification service (Slack/Email)
        await self._send_approval_notification(request, config, context)

        try:
            from aragora.events.types import StreamEventType

            context.emit_event(
                StreamEventType.WORKFLOW_HUMAN_APPROVAL_REQUIRED.value,
                {
                    "workflow_id": context.workflow_id,
                    "definition_id": context.definition_id,
                    "step_id": request.step_id,
                    "step_name": self.name,
                    "request_id": request.id,
                    "title": request.title,
                    "timeout_seconds": request.timeout_seconds,
                    "escalation_emails": request.escalation_emails,
                },
            )
        except (ImportError, AttributeError, TypeError) as exc:
            logger.debug("Failed to emit approval required event: %s", exc)

        # Store request ID in context for external resolution
        context.set_state(f"approval_request_{self.name}", request.id)

        # Wait for approval (with timeout)
        try:
            result = await asyncio.wait_for(
                self._wait_for_approval(request),
                timeout=request.timeout_seconds,
            )
            try:
                from aragora.events.types import StreamEventType

                context.emit_event(
                    StreamEventType.WORKFLOW_HUMAN_APPROVAL_RECEIVED.value,
                    {
                        "workflow_id": context.workflow_id,
                        "definition_id": context.definition_id,
                        "step_id": request.step_id,
                        "step_name": self.name,
                        "request_id": request.id,
                        "status": result.get("status"),
                        "responder_id": result.get("responder_id"),
                        "responded_at": result.get("responded_at"),
                    },
                )
            except (ImportError, AttributeError, TypeError) as exc:
                logger.debug("Failed to emit approval received event: %s", exc)
            return result
        except asyncio.TimeoutError:
            # Handle timeout
            request.status = ApprovalStatus.TIMEOUT
            logger.warning("Approval request %s timed out", request.id)

            # Persist timeout status to GovernanceStore
            store = _get_governance_store()
            if store:
                try:
                    store.update_approval_status(
                        approval_id=request.id,
                        status="timeout",
                        rejection_reason="Approval request timed out",
                    )
                except (RuntimeError, OSError, ValueError, TypeError) as e:
                    logger.warning("Failed to persist timeout status: %s", e)

            # Trigger escalation
            await self._handle_escalation(request)

            try:
                from aragora.events.types import StreamEventType

                context.emit_event(
                    StreamEventType.WORKFLOW_HUMAN_APPROVAL_TIMEOUT.value,
                    {
                        "workflow_id": context.workflow_id,
                        "definition_id": context.definition_id,
                        "step_id": request.step_id,
                        "step_name": self.name,
                        "request_id": request.id,
                        "timeout_seconds": request.timeout_seconds,
                        "escalated_to": request.escalation_emails,
                    },
                )
            except (ImportError, AttributeError, TypeError) as exc:
                logger.debug("Failed to emit approval timeout event: %s", exc)

            return {
                "status": "timeout",
                "request_id": request.id,
                "timeout_seconds": request.timeout_seconds,
                "escalated_to": request.escalation_emails,
            }

    async def _wait_for_approval(self, request: ApprovalRequest) -> dict[str, Any]:
        """Wait for the approval request to be resolved.

        Polls both in-memory cache and GovernanceStore to detect approvals
        that may have been made via other server instances or direct API calls.
        """
        poll_count = 0
        while request.status == ApprovalStatus.PENDING:
            await asyncio.sleep(1.0)
            poll_count += 1

            # Check if request was updated in memory
            if request.id in _pending_approvals:
                updated = _pending_approvals[request.id]
                if updated.status != ApprovalStatus.PENDING:
                    request = updated
                    break

            # Periodically check GovernanceStore (every 5 seconds)
            # This catches approvals made via other instances or direct API
            if poll_count % 5 == 0:
                store = _get_governance_store()
                if store:
                    try:
                        record = store.get_approval(request.id)
                        if record and record.status != "pending":
                            # Status changed in persistent store
                            request.status = ApprovalStatus(record.status)
                            request.responder_id = record.approved_by
                            if record.decided_at:
                                request.responded_at = record.decided_at
                            # Update in-memory cache
                            _pending_approvals[request.id] = request
                            logger.debug(
                                "Detected approval %s status change from governance store: %s",
                                request.id,
                                record.status,
                            )
                            break
                    except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as e:
                        logger.debug("Error polling governance store: %s", e)

        # Validate checklist if approved
        if request.status == ApprovalStatus.APPROVED:
            require_all = self._config.get("require_all_checklist", True)
            if require_all:
                missing = [c for c in request.checklist if c.required and not c.checked]
                if missing:
                    return {
                        "status": "rejected",
                        "reason": "Required checklist items not completed",
                        "missing_items": [c.label for c in missing],
                    }

        return {
            "status": request.status.value,
            "request_id": request.id,
            "responder_id": request.responder_id,
            "responder_notes": request.responder_notes,
            "responded_at": request.responded_at.isoformat() if request.responded_at else None,
            "checklist": [
                {"label": c.label, "checked": c.checked, "notes": c.notes}
                for c in request.checklist
            ],
        }

    async def _handle_escalation(self, request: ApprovalRequest) -> None:
        """Handle escalation when approval times out."""
        if not request.escalation_emails:
            return

        request.status = ApprovalStatus.ESCALATED
        logger.info("Escalating approval request %s to: %s", request.id, request.escalation_emails)

        # Persist escalation status to GovernanceStore
        store = _get_governance_store()
        if store:
            try:
                store.update_approval_status(
                    approval_id=request.id,
                    status="escalated",
                    rejection_reason=f"Escalated to: {', '.join(request.escalation_emails)}",
                )
            except (RuntimeError, OSError, ValueError, TypeError) as e:
                logger.warning("Failed to persist escalation status: %s", e)

        # Send escalation notifications via Slack/Email
        try:
            from aragora.notifications import notify_checkpoint_escalation

            await notify_checkpoint_escalation(
                request_id=request.id,
                workflow_id=request.workflow_id,
                step_id=request.step_id,
                title=request.title,
                escalation_emails=request.escalation_emails,
                original_timeout_seconds=request.timeout_seconds,
                action_url=self._build_action_url(request),
            )
        except ImportError:
            logger.debug("Notification service not available for escalation")
        except (RuntimeError, OSError, ValueError, TypeError, ConnectionError) as e:
            logger.warning("Failed to send escalation notification: %s", e)

    def _build_description(self, config: dict[str, Any], context: WorkflowContext) -> str:
        """Build the approval request description."""
        base_description = config.get("description", "")

        # Add context information
        parts = [base_description] if base_description else []

        # Add workflow context
        parts.append(f"\nWorkflow: {context.workflow_id}")
        parts.append(f"Step: {context.current_step_id}")

        # Add input summary if relevant
        if context.inputs:
            parts.append("\nInputs:")
            for key, value in list(context.inputs.items())[:5]:  # Limit to first 5
                parts.append(f"  - {key}: {str(value)[:100]}")

        return "\n".join(parts)

    def _evaluate_condition(self, condition: str, context: WorkflowContext) -> bool:
        """Safely evaluate a condition expression using AST-based evaluator."""
        try:
            namespace = {
                "inputs": context.inputs,
                "outputs": context.step_outputs,
                "state": context.state,
            }
            return safe_eval_bool(condition, namespace)
        except SafeEvalError:
            return False

    async def _send_approval_notification(
        self,
        request: ApprovalRequest,
        config: dict[str, Any],
        context: WorkflowContext,
    ) -> None:
        """Send notification for new approval request via Slack/Email."""
        try:
            from aragora.notifications import notify_checkpoint_approval_requested

            # Get assignees from config
            assignees = config.get("assignees") or config.get("escalation_emails") or []

            await notify_checkpoint_approval_requested(
                request_id=request.id,
                workflow_id=request.workflow_id,
                step_id=request.step_id,
                title=request.title,
                description=request.description,
                assignees=assignees,
                timeout_seconds=request.timeout_seconds,
                action_url=self._build_action_url(request),
            )
        except ImportError:
            logger.debug("Notification service not available")
        except (RuntimeError, OSError, ValueError, TypeError, ConnectionError) as e:
            logger.warning("Failed to send approval notification: %s", e)

        # Send interactive chat approval request (best-effort)
        try:
            from aragora.approvals.chat import send_chat_approval_request

            metadata = context.metadata if isinstance(context.metadata, dict) else {}
            raw_plan_meta = metadata.get("plan_metadata")
            plan_meta: dict[str, Any] = raw_plan_meta if isinstance(raw_plan_meta, dict) else {}

            targets = (
                config.get("chat_targets")
                or config.get("chat_channels")
                or config.get("assignees")
                or config.get("escalation_emails")
                or metadata.get("chat_targets")
                or metadata.get("approval_targets")
                or metadata.get("channel_targets")
                or plan_meta.get("chat_targets")
                or plan_meta.get("approval_targets")
                or plan_meta.get("channel_targets")
                or []
            )
            if isinstance(targets, str):
                targets = [targets]

            thread_id = (
                config.get("thread_id")
                or metadata.get("thread_id")
                or metadata.get("origin_thread_id")
                or plan_meta.get("thread_id")
                or plan_meta.get("origin_thread_id")
            )
            thread_id_by_platform = (
                config.get("thread_id_by_platform")
                or metadata.get("thread_id_by_platform")
                or plan_meta.get("thread_id_by_platform")
            )

            fields = [
                ("Workflow", request.workflow_id),
                ("Step", request.step_id),
                ("Request ID", request.id),
            ]
            if request.timeout_seconds:
                fields.append(("Timeout", f"{int(request.timeout_seconds)}s"))

            await send_chat_approval_request(
                title=request.title,
                description=request.description,
                fields=fields,
                targets=list(targets),
                kind="workflow",
                target_id=request.id,
                ttl_seconds=int(request.timeout_seconds) if request.timeout_seconds else None,
                thread_id=thread_id,
                thread_id_by_platform=thread_id_by_platform,
            )
        except (ImportError, RuntimeError, OSError, ValueError, TypeError, ConnectionError) as e:
            logger.debug("Chat approval notification skipped: %s", e)

    def _build_action_url(self, request: ApprovalRequest) -> str | None:
        """Build the URL for viewing/responding to an approval request."""
        import os

        base_url = os.environ.get("ARAGORA_BASE_URL", "")
        if base_url:
            return f"{base_url}/workflows/{request.workflow_id}/approvals/{request.id}"
        return None


# Helper functions for external approval resolution


def resolve_approval(
    request_id: str,
    status: ApprovalStatus,
    responder_id: str,
    notes: str = "",
    checklist_updates: dict[str, bool] | None = None,
) -> bool:
    """
    Resolve an approval request from external code.

    Args:
        request_id: ID of the approval request
        status: New status (APPROVED or REJECTED)
        responder_id: ID of the person responding
        notes: Optional notes from the responder
        checklist_updates: Optional dict mapping item IDs to checked status

    Returns:
        True if request was found and updated, False otherwise
    """
    # Try to get request from memory or recover from persistent store
    request = get_approval_request(request_id)
    if request is None:
        logger.warning("Approval request %s not found in memory or store", request_id)
        return False
    request.status = status
    request.responder_id = responder_id
    request.responder_notes = notes
    request.responded_at = datetime.now(timezone.utc)

    if checklist_updates:
        for item in request.checklist:
            if item.id in checklist_updates:
                item.checked = checklist_updates[item.id]

    logger.info("Resolved approval request %s: %s", request_id, status.value)

    # Persist to GovernanceStore
    store = _get_governance_store()
    if store:
        try:
            rejection_reason = notes if status == ApprovalStatus.REJECTED else None
            store.update_approval_status(
                approval_id=request_id,
                status=status.value,
                approved_by=responder_id if status == ApprovalStatus.APPROVED else None,
                rejection_reason=rejection_reason,
            )
        except (RuntimeError, OSError, ValueError, TypeError) as e:
            logger.warning("Failed to update approval in store: %s", e)

    # Send resolution notification (async in background)
    _send_resolution_notification_background(request)

    return True


def _send_resolution_notification_background(request: ApprovalRequest) -> None:
    """Send resolution notification in background (fire-and-forget)."""
    import asyncio

    async def _send():
        try:
            from aragora.notifications import notify_checkpoint_resolved

            await notify_checkpoint_resolved(
                request_id=request.id,
                workflow_id=request.workflow_id,
                step_id=request.step_id,
                title=request.title,
                status=request.status.value,
                responder_id=request.responder_id,
                responder_notes=request.responder_notes,
            )
        except ImportError:
            pass  # Notification service not available
        except (RuntimeError, OSError, ValueError, TypeError, ConnectionError) as e:
            logger.warning("Failed to send resolution notification: %s", e)

    # Try to schedule in existing event loop or create new one
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_send())
    except RuntimeError:
        # No running loop, run synchronously in new loop
        try:
            asyncio.run(_send())
        except (RuntimeError, asyncio.CancelledError) as e:
            logger.debug("Resolution notification send failed (event loop): %s", e)
        except (RuntimeError, OSError, ValueError, TypeError, ConnectionError) as e:
            logger.warning("Unexpected error sending resolution notification: %s", e)


def get_pending_approvals(workflow_id: str | None = None) -> list[ApprovalRequest]:
    """Get all pending approval requests, optionally filtered by workflow.

    Automatically recovers approvals from GovernanceStore on first call
    after server restart to ensure approvals are not lost.
    """
    # Ensure approvals are recovered from persistent store
    if not _approvals_recovered:
        recover_pending_approvals()

    # Get in-memory approvals (now includes recovered ones)
    approvals = [a for a in _pending_approvals.values() if a.status == ApprovalStatus.PENDING]

    if workflow_id:
        approvals = [a for a in approvals if a.workflow_id == workflow_id]
    return approvals


def get_approval_request(request_id: str) -> ApprovalRequest | None:
    """Get an approval request by ID.

    Automatically recovers approvals from GovernanceStore on first call
    after server restart to ensure approvals are not lost.
    """
    # Ensure approvals are recovered from persistent store
    if not _approvals_recovered:
        recover_pending_approvals()

    # Check in-memory cache (now includes recovered approvals)
    if request_id in _pending_approvals:
        return _pending_approvals[request_id]

    # Try to recover this specific approval from persistent store
    # (in case it was created after the last recovery)
    store = _get_governance_store()
    if store:
        try:
            record = store.get_approval(request_id)
            if record:
                import json

                metadata = {}
                if record.metadata_json:
                    metadata = json.loads(record.metadata_json)

                # Reconstruct checklist from stored metadata
                checklist = []
                for item in metadata.get("checklist", []):
                    checklist.append(
                        ChecklistItem(
                            id=item.get("id", ""),
                            label=item.get("label", ""),
                            required=item.get("required", True),
                            checked=item.get("checked", False),
                            notes=item.get("notes", ""),
                        )
                    )

                # Reconstruct ApprovalRequest from stored record
                request = ApprovalRequest(
                    id=record.approval_id,
                    workflow_id=metadata.get("workflow_id", "unknown"),
                    step_id=metadata.get("step_id", "unknown"),
                    title=record.title,
                    description=record.description,
                    checklist=checklist,
                    status=ApprovalStatus(record.status),
                    timeout_seconds=float(record.timeout_seconds),
                    escalation_emails=metadata.get("escalation_emails", []),
                    responder_id=record.approved_by,
                    responded_at=record.decided_at,
                )
                # Cache for future lookups
                _pending_approvals[request_id] = request
                logger.debug("Recovered approval %s from governance store", request_id)
                return request
        except (RuntimeError, OSError, ValueError, TypeError, KeyError, AttributeError) as e:
            logger.debug("Could not recover approval %s: %s", request_id, e)

    return None
