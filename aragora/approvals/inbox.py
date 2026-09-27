"""Unified approval inbox aggregation."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_APPROVAL_SOURCES = [
    "workflow",
    "decision_plan",
    "computer_use",
    "gateway",
    "inbox_wedge",
]


def _iso_timestamp(value: datetime | float | int | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


@dataclass
class UnifiedApprovalItem:
    id: str
    kind: str
    status: str
    title: str
    description: str
    requested_at: str | None
    requested_by: str | None
    metadata: dict[str, Any]
    actions: dict[str, Any]
    _sort_ts: float

    def to_dict(self) -> dict[str, Any]:
        data = {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "title": self.title,
            "description": self.description,
            "requested_at": self.requested_at,
            "requested_by": self.requested_by,
            "metadata": self.metadata,
            "actions": self.actions,
        }
        return data


def collect_pending_approvals(
    *,
    limit: int = 200,
    sources: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Collect pending approvals across subsystems."""
    items: list[UnifiedApprovalItem] = []
    sources = effective_approval_sources(sources)

    if "workflow" in sources:
        try:
            from aragora.workflow.nodes.human_checkpoint import get_pending_approvals

            for req in get_pending_approvals():
                created_at = getattr(req, "created_at", None)
                items.append(
                    UnifiedApprovalItem(
                        id=req.id,
                        kind="workflow",
                        status=req.status.value,
                        title=req.title,
                        description=req.description,
                        requested_at=_iso_timestamp(created_at),
                        requested_by=getattr(req, "responder_id", None),
                        metadata={
                            "workflow_id": req.workflow_id,
                            "step_id": req.step_id,
                            "timeout_seconds": req.timeout_seconds,
                        },
                        actions={
                            "approve": {
                                "method": "POST",
                                "path": f"/api/v1/workflow-approvals/{req.id}/resolve",
                                "body": {"status": "approved"},
                            },
                            "reject": {
                                "method": "POST",
                                "path": f"/api/v1/workflow-approvals/{req.id}/resolve",
                                "body": {"status": "rejected"},
                            },
                        },
                        _sort_ts=_to_sort_ts(created_at),
                    )
                )
        except (ImportError, AttributeError, OSError):
            logger.debug("Failed to fetch workflow approvals for inbox", exc_info=True)

    if "decision_plan" in sources:
        try:
            from aragora.pipeline.executor import list_plans
            from aragora.pipeline.decision_plan import PlanStatus

            for plan in list_plans(status=PlanStatus.AWAITING_APPROVAL, limit=limit):
                created_at = getattr(plan, "created_at", None)
                items.append(
                    UnifiedApprovalItem(
                        id=plan.id,
                        kind="decision_plan",
                        status=plan.status.value,
                        title="Decision Plan Approval",
                        description=plan.task,
                        requested_at=_iso_timestamp(created_at),
                        requested_by=plan.metadata.get("requested_by")
                        if isinstance(plan.metadata, dict)
                        else None,
                        metadata={
                            "debate_id": plan.debate_id,
                            "risk_level": plan.highest_risk_level.value,
                        },
                        actions={
                            "approve": {
                                "method": "POST",
                                "path": f"/api/v1/decisions/plans/{plan.id}/approve",
                                "body": {"reason": "Approved via inbox"},
                            },
                            "reject": {
                                "method": "POST",
                                "path": f"/api/v1/decisions/plans/{plan.id}/reject",
                                "body": {"reason": "Rejected via inbox"},
                            },
                        },
                        _sort_ts=_to_sort_ts(created_at),
                    )
                )
        except (ImportError, AttributeError, OSError):
            logger.debug("Failed to fetch decision plan approvals for inbox", exc_info=True)

    if "computer_use" in sources:
        try:
            from aragora.server.extensions import get_extension_state
            from aragora.computer_use.approval import ApprovalStatus as CUStatus

            state = get_extension_state()
            workflow = getattr(state, "computer_approval_workflow", None) if state else None
            if workflow:
                approvals = workflow.list_all(limit=limit, status=CUStatus.PENDING)
                if hasattr(approvals, "__await__"):
                    approvals = _run_async(approvals)
                for req in approvals:
                    created_at = getattr(req, "created_at", None)
                    items.append(
                        UnifiedApprovalItem(
                            id=req.id,
                            kind="computer_use",
                            status=req.status.value,
                            title="Computer-Use Approval",
                            description=req.context.reason,
                            requested_at=_iso_timestamp(created_at),
                            requested_by=req.context.user_id,
                            metadata={
                                "action_type": req.context.action_type,
                                "category": req.context.category.value,
                                "risk_level": req.context.risk_level,
                                "current_url": req.context.current_url,
                            },
                            actions={
                                "approve": {
                                    "method": "POST",
                                    "path": f"/api/v1/computer-use/approvals/{req.id}/approve",
                                    "body": {"reason": "Approved via inbox"},
                                },
                                "reject": {
                                    "method": "POST",
                                    "path": f"/api/v1/computer-use/approvals/{req.id}/deny",
                                    "body": {"reason": "Rejected via inbox"},
                                },
                            },
                            _sort_ts=_to_sort_ts(created_at),
                        )
                    )
        except (ImportError, AttributeError, OSError):
            logger.debug("Failed to fetch computer use approvals for inbox", exc_info=True)

    if "gateway" in sources:
        try:
            from aragora.server.handlers.openclaw.store import _get_store

            gateway_store = _get_store()
            if hasattr(gateway_store, "list_approvals"):
                gateway_approvals, _total = gateway_store.list_approvals(limit=limit, offset=0)
                for gateway_req in gateway_approvals:
                    req_dict = (
                        gateway_req.to_dict() if hasattr(gateway_req, "to_dict") else gateway_req
                    )
                    if not isinstance(req_dict, dict):
                        logger.debug(
                            "Skipping malformed gateway approval of type %s",
                            type(req_dict).__name__,
                        )
                        continue
                    created_at = req_dict.get("created_at")
                    items.append(
                        UnifiedApprovalItem(
                            id=req_dict.get("id", ""),
                            kind="gateway",
                            status=req_dict.get("status", "pending"),
                            title=req_dict.get("title", "Gateway Approval"),
                            description=req_dict.get("description", ""),
                            requested_at=_iso_timestamp(created_at),
                            requested_by=req_dict.get("requested_by"),
                            metadata=req_dict,
                            actions={
                                "approve": {
                                    "method": "POST",
                                    "path": f"/api/gateway/openclaw/approvals/{req_dict.get('id')}/approve",
                                    "body": {"reason": "Approved via inbox"},
                                },
                                "reject": {
                                    "method": "POST",
                                    "path": f"/api/gateway/openclaw/approvals/{req_dict.get('id')}/deny",
                                    "body": {"reason": "Rejected via inbox"},
                                },
                            },
                            _sort_ts=_to_sort_ts(created_at),
                        )
                    )
        except (ImportError, AttributeError, OSError):
            logger.debug("Failed to fetch gateway approvals for inbox", exc_info=True)

    if "inbox_wedge" in sources:
        try:
            from aragora.inbox import ReceiptState, get_inbox_trust_wedge_store

            wedge_store = get_inbox_trust_wedge_store()
            for envelope in wedge_store.list_receipts(state=ReceiptState.CREATED, limit=limit):
                created_at = envelope.receipt.created_at
                label_id = envelope.intent.label_id or envelope.decision.label_id
                action_label = envelope.intent.action.value.upper()
                items.append(
                    UnifiedApprovalItem(
                        id=envelope.receipt.receipt_id,
                        kind="inbox_wedge",
                        status=envelope.receipt.state.value,
                        title=f"Inbox {action_label} Approval",
                        description=(
                            envelope.intent.synthesized_rationale
                            or f"{envelope.intent.action.value} message {envelope.intent.message_id}"
                        ),
                        requested_at=_iso_timestamp(created_at),
                        requested_by=envelope.intent.user_id,
                        metadata={
                            "provider": envelope.intent.provider,
                            "message_id": envelope.intent.message_id,
                            "action": envelope.intent.action.value,
                            "label_id": label_id,
                            "confidence": envelope.decision.confidence,
                            "dissent_summary": envelope.decision.dissent_summary,
                            "provider_route": envelope.provider_route,
                            "debate_id": envelope.debate_id,
                        },
                        actions={
                            "approve": {
                                "method": "POST",
                                "path": f"/api/v1/inbox/wedge/receipts/{envelope.receipt.receipt_id}/review",
                                "body": {"choice": "approve", "execute": True},
                            },
                            "reject": {
                                "method": "POST",
                                "path": f"/api/v1/inbox/wedge/receipts/{envelope.receipt.receipt_id}/review",
                                "body": {"choice": "reject"},
                            },
                        },
                        _sort_ts=_to_sort_ts(created_at),
                    )
                )
        except (ImportError, AttributeError, OSError):
            logger.debug("Failed to fetch inbox trust wedge approvals for inbox", exc_info=True)

    if "settlement" in sources and _settlement_inbox_enabled():
        try:
            from aragora.approvals.settlement_inbox import (
                SettlementInboxError,
                collect_pending_settlement_approvals,
            )
        except ImportError:
            logger.warning("Failed to fetch settlement approvals for inbox", exc_info=True)
        else:
            try:
                for item in collect_pending_settlement_approvals(limit=limit):
                    items.append(
                        UnifiedApprovalItem(
                            id=str(item.get("id", "")),
                            kind=str(item.get("kind", "settlement")),
                            status=str(item.get("status", "pending")),
                            title=str(item.get("title", "Settlement Approval")),
                            description=str(item.get("description", "")),
                            requested_at=item.get("requested_at"),
                            requested_by=item.get("requested_by"),
                            metadata=_dict_or_empty(item.get("metadata")),
                            actions=_dict_or_empty(item.get("actions")),
                            _sort_ts=_to_sort_ts(item.get("requested_at")),
                        )
                    )
            except (
                SettlementInboxError,
                AttributeError,
                ImportError,
                OSError,
                TypeError,
                ValueError,
            ):
                logger.warning("Failed to fetch settlement approvals for inbox", exc_info=True)

    items.sort(key=lambda item: item._sort_ts, reverse=True)
    return [item.to_dict() for item in items[:limit]]


def _settlement_inbox_enabled() -> bool:
    raw = os.environ.get("ARAGORA_ENABLE_SETTLEMENT_APPROVAL_INBOX", "")
    return raw.lower().strip() in {"1", "true", "yes", "on"}


def effective_approval_sources(sources: list[str] | None = None) -> list[str]:
    effective = [s.lower() for s in (sources or DEFAULT_APPROVAL_SOURCES)]
    if sources is None and _settlement_inbox_enabled():
        effective.append("settlement")
    return effective


def _dict_or_empty(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return dict(value)


def _to_sort_ts(value: datetime | float | int | str | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return 0.0
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _run_async(coro):
    from aragora.utils.async_utils import run_async

    return run_async(coro)


__all__ = ["DEFAULT_APPROVAL_SOURCES", "collect_pending_approvals"]
