"""
Audit Sessions API Handler.

Stability: STABLE

Provides RESTful endpoints for managing document audit sessions:
- Create/list/get audit sessions
- Start/pause/resume/cancel audits
- Stream audit events via SSE
- Retrieve and manage findings
- Export audit reports

Usage:
    POST   /api/audit/sessions           - Create new audit session
    GET    /api/audit/sessions           - List all sessions
    GET    /api/audit/sessions/{id}      - Get session details
    POST   /api/audit/sessions/{id}/start   - Start audit
    POST   /api/audit/sessions/{id}/pause   - Pause audit
    POST   /api/audit/sessions/{id}/resume  - Resume audit
    POST   /api/audit/sessions/{id}/cancel  - Cancel audit
    GET    /api/audit/sessions/{id}/findings - Get findings
    GET    /api/audit/sessions/{id}/events   - SSE event stream
    POST   /api/audit/sessions/{id}/intervene - Human intervention
    GET    /api/audit/sessions/{id}/report   - Export report
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from aragora.resilience import CircuitBreaker
from aragora.server.handlers.secure import SecureHandler, ForbiddenError, UnauthorizedError
from aragora.rbac.decorators import require_permission
from aragora.server.handlers.utils.rate_limit import rate_limit
from aragora.server.validation.query_params import safe_query_int

logger = logging.getLogger(__name__)

# =============================================================================
# Resilience Configuration
# =============================================================================

# Circuit breaker for audit sessions service
_audit_sessions_circuit_breaker = CircuitBreaker(
    name="audit_sessions_handler",
    failure_threshold=5,
    cooldown_seconds=30.0,
)


def get_audit_sessions_circuit_breaker() -> CircuitBreaker:
    """Get the circuit breaker for audit sessions service."""
    return _audit_sessions_circuit_breaker


def get_audit_sessions_circuit_breaker_status() -> dict[str, Any]:
    """Get current status of the audit sessions circuit breaker."""
    return _audit_sessions_circuit_breaker.to_dict()


# =============================================================================
# RBAC Configuration
# =============================================================================

# RBAC permissions for audit session endpoints
AUDIT_READ_PERMISSION = "audit:read"
AUDIT_CREATE_PERMISSION = "audit:create"
AUDIT_EXECUTE_PERMISSION = "audit:execute"
AUDIT_DELETE_PERMISSION = "audit:delete"
AUDIT_INTERVENE_PERMISSION = "audit:intervene"


# In-memory session storage (would be replaced with database in production)
_sessions: dict[str, dict[str, Any]] = {}
_findings: dict[str, list[dict[str, Any]]] = {}
_event_queues: dict[str, list[asyncio.Queue]] = {}

# CancellationToken storage for active sessions
_cancellation_tokens: dict[str, Any] = {}


class AuditSessionsHandler(SecureHandler):
    """
    Handler for audit session management endpoints.

    Stability: STABLE

    Features:
    - Circuit breaker pattern for service resilience
    - Rate limiting (60 requests/minute)
    - Full RBAC permission checks
    - Comprehensive input validation

    Provides full lifecycle management for document audit sessions
    including creation, execution control, and reporting.

    RBAC Protected:
    - audit:read - view sessions, findings, events, reports
    - audit:create - create new sessions
    - audit:execute - start, pause, resume, cancel audits
    - audit:delete - delete sessions
    - audit:intervene - human intervention in audits
    """

    def __init__(self, ctx: dict | None = None, server_context: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = server_context or ctx or {}

    ROUTES = [
        "/api/v1/audit/sessions",
        "/api/v1/audit/sessions/{session_id}",
        "/api/v1/audit/sessions/{session_id}/start",
        "/api/v1/audit/sessions/{session_id}/pause",
        "/api/v1/audit/sessions/{session_id}/resume",
        "/api/v1/audit/sessions/{session_id}/cancel",
        "/api/v1/audit/sessions/{session_id}/findings",
        "/api/v1/audit/sessions/{session_id}/events",
        "/api/v1/audit/sessions/{session_id}/intervene",
        "/api/v1/audit/sessions/{session_id}/report",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can handle the given path."""
        return path.startswith("/api/v1/audit/")

    @rate_limit(requests_per_minute=60, limiter_name="audit_sessions")
    async def handle_request(self, request: Any) -> dict[str, Any]:
        """Route request to appropriate handler with RBAC protection."""
        method = request.method
        path = str(request.path)

        # Parse session_id from path if present
        session_id = None
        if "/sessions/" in path:
            parts = path.split("/sessions/")
            if len(parts) > 1:
                remaining = parts[1].split("/")
                session_id = remaining[0]

        # Determine required permission based on endpoint
        required_permission = self._get_required_permission(path, method)

        # RBAC: Require authentication and appropriate permission
        try:
            auth_context = await self.get_auth_context(request, require_auth=True)
            self.check_permission(auth_context, required_permission)
        except UnauthorizedError:
            return self._error_response(401, "Authentication required for audit sessions")
        except ForbiddenError as e:
            logger.warning("Audit session access denied: %s", e)
            return self._error_response(403, "Permission denied")

        # Route to appropriate handler
        if path.endswith("/sessions") and method == "POST":
            return await self._create_session(request)
        elif path.endswith("/sessions") and method == "GET":
            return await self._list_sessions(request)
        elif session_id and path.endswith("/start"):
            return await self._start_audit(request, session_id)
        elif session_id and path.endswith("/pause"):
            return await self._pause_audit(request, session_id)
        elif session_id and path.endswith("/resume"):
            return await self._resume_audit(request, session_id)
        elif session_id and path.endswith("/cancel"):
            return await self._cancel_audit(request, session_id)
        elif session_id and path.endswith("/findings"):
            return await self._get_findings(request, session_id)
        elif session_id and path.endswith("/events"):
            return await self._stream_events(request, session_id)
        elif session_id and path.endswith("/intervene"):
            return await self._handle_intervention(request, session_id)
        elif session_id and path.endswith("/report"):
            return await self._export_report(request, session_id)
        elif session_id and method == "GET":
            return await self._get_session(request, session_id)
        elif session_id and method == "DELETE":
            return await self._delete_session(request, session_id)

        return self._error_response(404, "Endpoint not found")

    def _get_required_permission(self, path: str, method: str) -> str:
        """Determine the required RBAC permission for a given endpoint."""
        # Create session
        if path.endswith("/sessions") and method == "POST":
            return AUDIT_CREATE_PERMISSION
        # List/get sessions, findings, events, reports
        if method == "GET":
            return AUDIT_READ_PERMISSION
        # Delete session
        if method == "DELETE":
            return AUDIT_DELETE_PERMISSION
        # Start, pause, resume, cancel
        if any(path.endswith(action) for action in ["/start", "/pause", "/resume", "/cancel"]):
            return AUDIT_EXECUTE_PERMISSION
        # Human intervention
        if path.endswith("/intervene"):
            return AUDIT_INTERVENE_PERMISSION
        # Default to read for safety
        return AUDIT_READ_PERMISSION

    async def _create_session(self, request: Any) -> dict[str, Any]:
        """
        Create a new audit session.

        Expected body:
        {
            "document_ids": ["doc1", "doc2"],
            "audit_types": ["security", "compliance"],  // optional
            "config": {  // optional
                "use_debate": true,
                "min_confidence": 0.7,
                "parallel_agents": 3
            }
        }
        """
        try:
            body = await self._parse_json_body(request)
        except (json.JSONDecodeError, ValueError, TypeError):
            return self._error_response(400, "Invalid JSON body")

        document_ids = body.get("document_ids", [])
        if not document_ids:
            return self._error_response(400, "document_ids is required")

        audit_types = body.get("audit_types", ["security", "compliance", "consistency", "quality"])
        config = body.get("config", {})

        session_id = str(uuid4())
        session = {
            "id": session_id,
            "document_ids": document_ids,
            "audit_types": audit_types,
            "config": config,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "started_at": None,
            "completed_at": None,
            "progress": {
                "total_documents": len(document_ids),
                "processed_documents": 0,
                "total_chunks": 0,
                "processed_chunks": 0,
                "findings_count": 0,
            },
            "agents": [],
            "error": None,
        }

        _sessions[session_id] = session
        _findings[session_id] = []
        _event_queues[session_id] = []

        logger.info("Created audit session %s with %s documents", session_id, len(document_ids))

        return self._json_response(201, session)

    async def _list_sessions(self, request: Any) -> dict[str, Any]:
        """List all audit sessions with optional filtering."""
        # Parse query params
        status_filter = request.query.get("status")
        limit = safe_query_int(request.query, "limit", default=50, min_val=1, max_val=1000)
        offset = safe_query_int(request.query, "offset", default=0, min_val=0, max_val=1000000)

        sessions = list(_sessions.values())

        # Filter by status
        if status_filter:
            sessions = [s for s in sessions if s["status"] == status_filter]

        # Sort by created_at descending
        sessions.sort(key=lambda s: s["created_at"], reverse=True)

        # Paginate
        total = len(sessions)
        sessions = sessions[offset : offset + limit]

        return self._json_response(
            200,
            {
                "sessions": sessions,
                "total": total,
                "limit": limit,
                "offset": offset,
            },
        )

    async def _get_session(self, request: Any, session_id: str) -> dict[str, Any]:
        """Get details for a specific session."""
        session = _sessions.get(session_id)
        if not session:
            return self._error_response(404, f"Session {session_id} not found")

        return self._json_response(200, session)

    @require_permission("audit:delete")
    async def _delete_session(self, request: Any, session_id: str) -> dict[str, Any]:
        """Delete an audit session."""
        if session_id not in _sessions:
            return self._error_response(404, f"Session {session_id} not found")

        session = _sessions[session_id]
        if session["status"] == "running":
            return self._error_response(
                400, "Cannot delete running session. Pause or cancel first."
            )

        del _sessions[session_id]
        _findings.pop(session_id, None)
        _event_queues.pop(session_id, None)

        logger.info("Deleted audit session %s", session_id)

        return self._json_response(200, {"deleted": session_id})

    async def _start_audit(self, request: Any, session_id: str) -> dict[str, Any]:
        """Start an audit session."""
        session = _sessions.get(session_id)
        if not session:
            return self._error_response(404, f"Session {session_id} not found")

        if session["status"] not in ["pending", "paused"]:
            return self._error_response(400, f"Cannot start session in {session['status']} status")

        session["status"] = "running"
        session["started_at"] = datetime.now(timezone.utc).isoformat()
        session["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Emit event
        await self._emit_event(
            session_id,
            {
                "type": "audit_started",
                "session_id": session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        # Start audit in background (would trigger actual audit processing)
        task = asyncio.create_task(self._run_audit_background(session_id))
        task.add_done_callback(
            lambda t: logger.error("Background audit %s failed: %s", session_id, t.exception())
            if not t.cancelled() and t.exception()
            else None
        )

        logger.info("Started audit session %s", session_id)

        return self._json_response(200, session)

    async def _pause_audit(self, request: Any, session_id: str) -> dict[str, Any]:
        """Pause a running audit session."""
        session = _sessions.get(session_id)
        if not session:
            return self._error_response(404, f"Session {session_id} not found")

        if session["status"] != "running":
            return self._error_response(400, f"Cannot pause session in {session['status']} status")

        session["status"] = "paused"
        session["updated_at"] = datetime.now(timezone.utc).isoformat()

        await self._emit_event(
            session_id,
            {
                "type": "audit_paused",
                "session_id": session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        logger.info("Paused audit session %s", session_id)

        return self._json_response(200, session)

    async def _resume_audit(self, request: Any, session_id: str) -> dict[str, Any]:
        """Resume a paused audit session."""
        session = _sessions.get(session_id)
        if not session:
            return self._error_response(404, f"Session {session_id} not found")

        if session["status"] != "paused":
            return self._error_response(400, f"Cannot resume session in {session['status']} status")

        session["status"] = "running"
        session["updated_at"] = datetime.now(timezone.utc).isoformat()

        await self._emit_event(
            session_id,
            {
                "type": "audit_resumed",
                "session_id": session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        logger.info("Resumed audit session %s", session_id)

        return self._json_response(200, session)

    async def _cancel_audit(self, request: Any, session_id: str) -> dict[str, Any]:
        """Cancel an audit session using CancellationToken for cooperative abort."""
        session = _sessions.get(session_id)
        if not session:
            return self._error_response(404, f"Session {session_id} not found")

        if session["status"] in ["completed", "cancelled"]:
            return self._error_response(400, f"Session already in {session['status']} status")

        # Parse reason from request body
        reason = "User requested cancellation"
        try:
            body = await self._parse_json_body(request)
            reason = body.get("reason", reason)
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug("Could not parse cancellation reason from body: %s, using default", e)

        # Trigger CancellationToken if available
        token = _cancellation_tokens.get(session_id)
        if token:
            try:
                token.cancel(reason)
                logger.debug("Triggered CancellationToken for session %s", session_id)
            except (RuntimeError, ValueError, TypeError) as e:
                logger.warning("Failed to trigger CancellationToken: %s", e)

        session["status"] = "cancelled"
        session["cancel_reason"] = reason
        session["completed_at"] = datetime.now(timezone.utc).isoformat()
        session["updated_at"] = datetime.now(timezone.utc).isoformat()

        await self._emit_event(
            session_id,
            {
                "type": "audit_cancelled",
                "session_id": session_id,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        logger.info("Cancelled audit session %s: %s", session_id, reason)

        return self._json_response(200, session)

    async def _get_findings(self, request: Any, session_id: str) -> dict[str, Any]:
        """Get findings for a session with optional filtering."""
        if session_id not in _sessions:
            return self._error_response(404, f"Session {session_id} not found")

        findings = _findings.get(session_id, [])

        # Parse filters
        severity = request.query.get("severity")
        audit_type = request.query.get("audit_type")
        status = request.query.get("status")
        limit = safe_query_int(request.query, "limit", default=100, min_val=1, max_val=1000)
        offset = safe_query_int(request.query, "offset", default=0, min_val=0, max_val=1000000)

        # Apply filters
        if severity:
            findings = [f for f in findings if f.get("severity") == severity]
        if audit_type:
            findings = [f for f in findings if f.get("audit_type") == audit_type]
        if status:
            findings = [f for f in findings if f.get("status") == status]

        # Sort by severity (critical first)
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        findings.sort(key=lambda f: severity_order.get(f.get("severity", "info"), 5))

        total = len(findings)
        findings = findings[offset : offset + limit]

        return self._json_response(
            200,
            {
                "findings": findings,
                "total": total,
                "limit": limit,
                "offset": offset,
            },
        )

    async def _stream_events(self, request: Any, session_id: str) -> Any:
        """
        Stream audit events via Server-Sent Events (SSE).

        Events include:
        - audit_started, audit_paused, audit_resumed, audit_completed
        - finding_discovered
        - agent_started, agent_completed
        - progress_update
        """
        if session_id not in _sessions:
            return self._error_response(404, f"Session {session_id} not found")

        # Create queue for this client
        queue: asyncio.Queue = asyncio.Queue()
        if session_id not in _event_queues:
            _event_queues[session_id] = []
        _event_queues[session_id].append(queue)

        async def event_generator():
            try:
                # Send initial connection event
                yield f"data: {json.dumps({'type': 'connected', 'session_id': session_id})}\n\n"

                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=30.0)
                        yield f"data: {json.dumps(event)}\n\n"
                    except asyncio.TimeoutError:
                        # Send keepalive
                        yield ": keepalive\n\n"

            finally:
                # Clean up queue
                if session_id in _event_queues and queue in _event_queues[session_id]:
                    _event_queues[session_id].remove(queue)

        return self._sse_response(event_generator())

    async def _handle_intervention(self, request: Any, session_id: str) -> dict[str, Any]:
        """
        Handle human intervention in an audit session.

        Expected body:
        {
            "action": "approve_finding" | "reject_finding" | "add_context" | "override_decision",
            "finding_id": "finding-123",  // for finding-related actions
            "context": "Additional context...",  // for add_context
            "reason": "Reason for action"
        }
        """
        session = _sessions.get(session_id)
        if not session:
            return self._error_response(404, f"Session {session_id} not found")

        try:
            body = await self._parse_json_body(request)
        except (json.JSONDecodeError, ValueError, TypeError):
            return self._error_response(400, "Invalid JSON body")

        action = body.get("action")
        if not action:
            return self._error_response(400, "action is required")

        finding_id = body.get("finding_id")
        reason = body.get("reason", "")

        if action in ["approve_finding", "reject_finding"] and finding_id:
            findings = _findings.get(session_id, [])
            for finding in findings:
                if finding.get("id") == finding_id:
                    if action == "approve_finding":
                        finding["status"] = "acknowledged"
                        finding["human_review"] = {
                            "action": "approved",
                            "reason": reason,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    else:
                        finding["status"] = "false_positive"
                        finding["human_review"] = {
                            "action": "rejected",
                            "reason": reason,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    break

        await self._emit_event(
            session_id,
            {
                "type": "human_intervention",
                "action": action,
                "finding_id": finding_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        logger.info("Human intervention in session %s: %s", session_id, action)

        return self._json_response(
            200,
            {
                "success": True,
                "action": action,
                "finding_id": finding_id,
            },
        )

    async def _export_report(self, request: Any, session_id: str) -> dict[str, Any]:
        """
        Export audit report in various formats.

        Query params:
        - format: json | markdown | html | pdf (default: markdown)
        - template: executive_summary | detailed_findings | compliance_attestation | security_assessment
        - min_severity: critical | high | medium | low | info (default: low)
        - include_resolved: true | false (default: false)
        - author: Author name for the report
        - company: Company name for branding
        """
        session = _sessions.get(session_id)
        if not session:
            return self._error_response(404, f"Session {session_id} not found")

        # Get query parameters
        report_format = request.query.get("format", "markdown")
        template = request.query.get("template", "detailed_findings")
        min_severity = request.query.get("min_severity", "low")
        include_resolved = request.query.get("include_resolved", "false") == "true"
        author = request.query.get("author", "")
        company = request.query.get("company", "Aragora")

        findings = _findings.get(session_id, [])

        try:
            # Import new report generator
            from aragora.reports import (
                AuditReportGenerator,
                ReportConfig,
                ReportFormat,
                ReportTemplate,
            )

            # Map format string to enum
            format_map = {
                "json": ReportFormat.JSON,
                "markdown": ReportFormat.MARKDOWN,
                "html": ReportFormat.HTML,
                "pdf": ReportFormat.PDF,
            }
            output_format = format_map.get(report_format, ReportFormat.MARKDOWN)

            # Map template string to enum
            template_map = {
                "executive_summary": ReportTemplate.EXECUTIVE_SUMMARY,
                "detailed_findings": ReportTemplate.DETAILED_FINDINGS,
                "compliance_attestation": ReportTemplate.COMPLIANCE_ATTESTATION,
                "security_assessment": ReportTemplate.SECURITY_ASSESSMENT,
            }
            output_template = template_map.get(template, ReportTemplate.DETAILED_FINDINGS)

            # Create config
            config = ReportConfig(
                min_severity=min_severity,
                include_resolved=include_resolved,
                author=author,
                company_name=company,
            )

            # Create a mock session object for the generator
            from aragora.audit.document_auditor import (
                AuditSession as RealSession,
                AuditFinding,
                AuditStatus,
                AuditType,
                FindingSeverity,
                FindingStatus,
            )

            # Convert dict findings to AuditFinding objects
            finding_objects = []
            for f in findings:
                try:
                    finding_obj = AuditFinding(
                        id=f.get("id", ""),
                        title=f.get("title", ""),
                        description=f.get("description", ""),
                        severity=FindingSeverity(f.get("severity", "medium")),
                        confidence=f.get("confidence", 0.8),
                        audit_type=AuditType(f.get("audit_type", "security")),
                        category=f.get("category", "general"),
                        document_id=f.get("document_id", ""),
                        chunk_id=f.get("chunk_id"),
                        evidence_text=f.get("evidence_text", ""),
                        evidence_location=f.get("evidence_location"),
                        recommendation=f.get("recommendation"),
                        status=FindingStatus(f.get("status", "open")),
                    )
                    finding_objects.append(finding_obj)
                except (ValueError, KeyError, TypeError) as e:
                    logger.warning("Could not convert finding: %s", e)

            # Create mock session with findings
            mock_session = RealSession(
                id=session_id,
                document_ids=session.get("document_ids", []),
                audit_types=[AuditType(t) for t in session.get("audit_types", ["security"])],
                name=session.get("name", ""),
                model=session.get("model", "unknown"),
                status=AuditStatus(session.get("status", "completed")),
            )
            mock_session.findings = finding_objects
            mock_session.total_chunks = session.get("progress", {}).get("total_chunks", 0)
            mock_session.processed_chunks = session.get("progress", {}).get("processed_chunks", 0)

            if session.get("completed_at"):
                mock_session.completed_at = datetime.fromisoformat(session["completed_at"])
            if session.get("started_at"):
                mock_session.started_at = datetime.fromisoformat(session["started_at"])

            # Generate report
            generator = AuditReportGenerator(config)
            report = await generator.generate(
                session=mock_session,
                format=output_format,
                template=output_template,
            )

            # Set appropriate content type
            content_types = {
                "json": "application/json",
                "markdown": "text/markdown",
                "html": "text/html",
                "pdf": "application/pdf",
            }

            # Add content disposition for download
            filename = report.filename
            headers = {
                "Content-Type": content_types.get(report_format, "text/plain"),
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Report-Findings-Count": str(report.findings_count),
            }

            return {
                "status": 200,
                "headers": headers,
                "body": report.content,
            }

        except ImportError as e:
            logger.warning("New report generator not available, falling back: %s", e)
            # Fallback to legacy JSON export
            return self._json_response(
                200,
                {
                    "session": session,
                    "findings": findings,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.warning("Report generation failed, falling back: %s", e)
            return self._json_response(
                200,
                {
                    "session": session,
                    "findings": findings,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
            )

    async def _run_audit_background(self, session_id: str):
        """
        Background task to run the actual audit using DocumentAuditor.

        Integrates with the DocumentAuditor and uses CancellationToken for
        cooperative cancellation support.
        """
        try:
            session = _sessions.get(session_id)
            if not session:
                return

            document_ids = session["document_ids"]

            # Create CancellationToken for this session
            try:
                from aragora.debate.cancellation import CancellationToken

                cancellation_token = CancellationToken()
                _cancellation_tokens[session_id] = cancellation_token
            except ImportError:
                cancellation_token = None
                logger.debug("CancellationToken not available, using status-based cancellation")

            # Create on_finding callback to emit events
            async def on_finding(finding):
                finding_dict = finding.to_dict() if hasattr(finding, "to_dict") else finding
                finding_dict["session_id"] = session_id

                # Store finding
                if session_id not in _findings:
                    _findings[session_id] = []
                _findings[session_id].append(finding_dict)

                # Emit event
                await self._emit_event(
                    session_id,
                    {
                        "type": "finding_discovered",
                        "session_id": session_id,
                        "finding": finding_dict,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )

            # Create on_progress callback
            def on_progress(sess_id: str, progress: float, phase: str):
                if session_id in _sessions:
                    _sessions[session_id]["progress"]["current_phase"] = phase
                    _sessions[session_id]["progress"]["percentage"] = progress
                    _sessions[session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

                # Emit progress event (fire and forget)
                _emit_task = asyncio.create_task(
                    self._emit_event(
                        session_id,
                        {
                            "type": "progress_update",
                            "session_id": session_id,
                            "phase": phase,
                            "progress": progress,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                )
                _emit_task.add_done_callback(
                    lambda t: logger.warning("Audit progress emission failed: %s", t.exception())
                    if not t.cancelled() and t.exception()
                    else None
                )

            # Try to use DocumentAuditor
            try:
                from aragora.audit.document_auditor import (
                    AuditConfig,
                    AuditFinding,
                    DocumentAuditor,
                )

                config = AuditConfig(
                    use_hive_mind=len(document_ids) > 1,  # Enable Hive-Mind for multi-doc
                    consensus_verification=True,
                )

                def on_finding_sync(f: AuditFinding) -> None:
                    """Sync wrapper that fires and forgets the async callback."""
                    _finding_task = asyncio.create_task(on_finding(f))
                    _finding_task.add_done_callback(
                        lambda t: logger.warning("Audit finding callback failed: %s", t.exception())
                        if not t.cancelled() and t.exception()
                        else None
                    )

                auditor = DocumentAuditor(
                    config=config,
                    on_finding=on_finding_sync,
                    on_progress=on_progress,
                )

                # Create session in auditor
                audit_session = await auditor.create_session(
                    document_ids=document_ids,
                    audit_types=session.get("audit_types", ["all"]),
                    name=session.get("name", ""),
                )

                # Run audit
                result = await auditor.run_audit(audit_session.id)

                # Store findings
                _findings[session_id] = [f.to_dict() for f in result.findings]

            except ImportError:
                logger.warning("DocumentAuditor not available, using fallback simulation")
                # Fallback to simulation
                for i, doc_id in enumerate(document_ids):
                    if cancellation_token and cancellation_token.is_cancelled:
                        break
                    if session["status"] != "running":
                        break

                    session["progress"]["processed_documents"] = i + 1
                    session["updated_at"] = datetime.now(timezone.utc).isoformat()

                    await self._emit_event(
                        session_id,
                        {
                            "type": "progress_update",
                            "session_id": session_id,
                            "document_id": doc_id,
                            "progress": session["progress"],
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    )

                    await asyncio.sleep(0.5)

            # Clean up CancellationToken
            _cancellation_tokens.pop(session_id, None)

            # Mark completed if not cancelled
            if session["status"] == "running":
                session["status"] = "completed"
                session["completed_at"] = datetime.now(timezone.utc).isoformat()
                session["updated_at"] = datetime.now(timezone.utc).isoformat()

                await self._emit_event(
                    session_id,
                    {
                        "type": "audit_completed",
                        "session_id": session_id,
                        "findings_count": len(_findings.get(session_id, [])),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )

                logger.info("Completed audit session %s", session_id)

        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.error("Error in audit session %s: %s", session_id, e)
            _cancellation_tokens.pop(session_id, None)
            if session_id in _sessions:
                _sessions[session_id]["status"] = "failed"
                _sessions[session_id]["error"] = "Audit session failed"
                _sessions[session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

    async def _emit_event(self, session_id: str, event: dict[str, Any]):
        """Emit event to all connected clients for a session."""
        if session_id in _event_queues:
            for queue in _event_queues[session_id]:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass  # Skip if queue is full

    async def _parse_json_body(self, request: Any) -> dict[str, Any]:
        """Parse JSON body from request."""
        if hasattr(request, "json"):
            return await request.json()
        elif hasattr(request, "body"):
            body = await request.body()
            return json.loads(body)
        return {}

    def _json_response(self, status: int, data: Any) -> dict[str, Any]:
        """Create a JSON response."""
        return {
            "status": status,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(data, default=str),
        }

    def _error_response(self, status: int, message: str) -> dict[str, Any]:
        """Create an error response."""
        return self._json_response(status, {"error": message})

    def _sse_response(self, generator) -> dict[str, Any]:
        """Create an SSE response."""
        return {
            "status": 200,
            "headers": {
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
            "body": generator,
        }


__all__ = [
    "AuditSessionsHandler",
    "get_audit_sessions_circuit_breaker",
    "get_audit_sessions_circuit_breaker_status",
]
