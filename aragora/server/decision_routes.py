"""Wire the core decision router to the packages that implement its hooks.

``aragora.core.decision_router`` reaches workflow, gauntlet, pipeline, chat
connector and audit behaviour only through ``aragora.core.decision_route_hooks``.
Importing this module loads the packages that register themselves in their own init;
:func:`register_decision_routes` re-applies those registrations, adds the
server-owned unified audit sink and registers the HTTP middleware audit logger with
:mod:`aragora.observability.unified_audit`. When it runs as the declared
``aragora.decision_routes`` registration, it only fills what is missing there too, so a
caller's own middleware audit logger is kept. Processes that route decisions (the unified HTTP
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
    declared_registrations_running,
    register_decision_audit_sink,
    register_decision_integrity_builder,
    register_tts_bridge_factory,
)
from aragora.gauntlet.decision_route import register_decision_route as register_gauntlet_route
from aragora.observability.unified_audit import register_middleware_audit_logger
from aragora.pipeline.decision_integrity_utils import build_decision_integrity_payload
from aragora.server.middleware.audit_logger import get_audit_logger
from aragora.workflow.decision_route import register_decision_route as register_workflow_route


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
    register_workflow_route()
    register_gauntlet_route()
    register_decision_integrity_builder(build_decision_integrity_payload)
    register_tts_bridge_factory(get_tts_bridge)
    register_decision_audit_sink(UnifiedAuditDecisionSink())
    # During declared discovery, keep a factory the caller registered first.
    register_middleware_audit_logger(get_audit_logger, replace=not declared_registrations_running())


__all__ = ["UnifiedAuditDecisionSink", "register_decision_routes"]
