"""Wire the core decision router to the packages that implement its hooks.

``aragora.core.decision_router`` reaches pipeline, chat connector and audit
behaviour only through ``aragora.core.decision_route_hooks``. Importing this
module loads the packages that register themselves in their own init;
:func:`register_decision_routes` re-applies those registrations and adds the
server-owned unified audit sink. Processes that route decisions (the unified HTTP
server, the FastAPI app lifespan, the control-plane deliberation worker) call it
once at startup.
"""

from __future__ import annotations

from aragora.audit.unified import (
    AuditOutcome,
    AuditSeverity,
    UnifiedAuditCategory,
    UnifiedAuditEvent,
    get_unified_audit_logger,
)
from aragora.connectors.chat.tts_bridge import get_tts_bridge
from aragora.core.decision_route_hooks import (
    register_decision_audit_sink,
    register_decision_integrity_builder,
    register_tts_bridge_factory,
)
from aragora.pipeline.decision_integrity_utils import build_decision_integrity_payload


class UnifiedAuditDecisionSink:
    """Writes routed-decision start and completion events to the unified audit logger."""

    def log_decision_started(
        self,
        *,
        request_id: str,
        decision_type: str,
        source: str,
        user_id: str | None = None,
        workspace_id: str | None = None,
        content_preview: str | None = None,
    ) -> None:
        get_unified_audit_logger().log(
            UnifiedAuditEvent(
                category=UnifiedAuditCategory.DEBATE_STARTED,
                action=f"Decision {decision_type} started",
                actor_id=user_id,
                resource_type="decision",
                resource_id=request_id,
                workspace_id=workspace_id,
                details={
                    "decision_type": decision_type,
                    "source": source,
                    "content_preview": (content_preview or "")[:200],
                },
            )
        )

    def log_decision_completed(
        self,
        *,
        request_id: str,
        decision_type: str,
        success: bool,
        consensus_reached: bool,
        confidence: float,
        duration_seconds: float,
        user_id: str | None = None,
        workspace_id: str | None = None,
        error: str | None = None,
    ) -> None:
        get_unified_audit_logger().log(
            UnifiedAuditEvent(
                category=UnifiedAuditCategory.DEBATE_COMPLETED,
                action=f"Decision {decision_type} completed",
                outcome=AuditOutcome.SUCCESS if success else AuditOutcome.FAILURE,
                severity=AuditSeverity.INFO if success else AuditSeverity.WARNING,
                actor_id=user_id,
                resource_type="decision",
                resource_id=request_id,
                workspace_id=workspace_id,
                details={
                    "decision_type": decision_type,
                    "consensus_reached": consensus_reached,
                    "confidence": confidence,
                    "duration_seconds": duration_seconds,
                    "error": error,
                },
            )
        )


def register_decision_routes() -> None:
    """Register every decision-router hook; safe to call more than once."""
    register_decision_integrity_builder(build_decision_integrity_payload)
    register_tts_bridge_factory(get_tts_bridge)
    register_decision_audit_sink(UnifiedAuditDecisionSink())


__all__ = ["UnifiedAuditDecisionSink", "register_decision_routes"]
