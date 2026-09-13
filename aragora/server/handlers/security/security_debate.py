"""
Security Debate API endpoint handlers.

Provides API endpoints for triggering multi-agent security debates on
vulnerability findings, SAST results, and security incidents.

Endpoints:
- POST /api/v1/audit/security/debate - Trigger a security debate on findings
- GET /api/v1/audit/security/debate/:id - Get status of a security debate
"""

from __future__ import annotations

__all__ = ["SecurityDebateHandler"]

import logging
import uuid
from collections.abc import Coroutine
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from aragora.core_types import DebateStatus, DebateStatusSource
from aragora.server.http_utils import run_async
from aragora.server.middleware.rate_limit import rate_limit

from ..base import (
    HandlerResult,
    error_response,
    json_response,
    require_permission,
    handle_errors,
)
from ..secure import SecureHandler

logger = logging.getLogger(__name__)


class SecurityDebateHandler(SecureHandler):
    """Handler for security debate endpoints.

    Provides API access to trigger multi-agent debates on security findings.
    Debates use Aragora's Arena with security-focused agents to analyze
    vulnerabilities and recommend remediation strategies.
    """

    ROUTES = [
        "/api/v1/audit/security/debate",
        "/api/v1/audit/security/debate/:id",
    ]

    _PREFIX = "/api/v1/audit/security/debate"

    def can_handle(self, path: str) -> bool:
        return path.startswith(self._PREFIX)

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Handle GET requests for security debate status."""
        parts = path.rstrip("/").split("/")
        # GET /api/v1/audit/security/debate/<id>
        if len(parts) == 7 and parts[-1]:
            return self.get_api_v1_audit_security_debate_id(parts[-1])
        return None

    @handle_errors("security debate creation")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests to trigger security debates."""
        if path.rstrip("/") == self._PREFIX:
            return self.post_api_v1_audit_security_debate()
        return None

    @rate_limit(requests_per_minute=10, key_type="user")
    @require_permission("audit:write")
    def post_api_v1_audit_security_debate(self) -> HandlerResult:
        """
        Trigger a multi-agent security debate on findings.

        Request body:
            {
                "findings": [
                    {
                        "severity": "critical|high|medium|low",
                        "title": "Finding title",
                        "description": "Description of the finding",
                        "file_path": "path/to/file.py",
                        "line_number": 42,
                        "recommendation": "Optional fix suggestion"
                    }
                ],
                "repository": "repo-name",  # optional
                "confidence_threshold": 0.7,  # optional
                "timeout_seconds": 300  # optional
            }

        Returns:
            {
                "debate_id": "uuid",
                "status": "completed|failed",
                "consensus_reached": true|false,
                "confidence": 0.85,
                "final_answer": "Remediation recommendations...",
                "rounds_used": 3,
                "duration_ms": 12500
            }
        """
        # Parse request body
        data = self.get_json_body()
        if data is None:
            return error_response("Invalid JSON body", 400)

        findings_data = data.get("findings", [])
        if not findings_data:
            return error_response("No findings provided", 400)

        if not isinstance(findings_data, list):
            return error_response("findings must be an array", 400)

        repository = data.get("repository", "unknown")
        try:
            confidence_threshold = min(max(float(data.get("confidence_threshold", 0.7)), 0.1), 1.0)
        except (ValueError, TypeError):
            confidence_threshold = 0.7
        try:
            timeout_seconds = min(max(int(data.get("timeout_seconds", 300)), 30), 600)
        except (ValueError, TypeError):
            timeout_seconds = 300

        # Import security event types
        try:
            from aragora.debate.security_debate import run_security_debate
            from aragora.events.security_events import (
                SecurityEvent,
                SecurityEventType,
                SecurityFinding,
                SecuritySeverity,
            )
        except ImportError as e:
            logger.error("Security debate module not available: %s", e)
            return error_response("Security debate module not available", 500)

        # Convert findings to SecurityFinding objects
        findings: list[SecurityFinding] = []
        for i, f in enumerate(findings_data):
            try:
                severity_str = f.get("severity", "medium").lower()
                severity = SecuritySeverity(severity_str)
            except ValueError:
                severity = SecuritySeverity.MEDIUM

            finding = SecurityFinding(
                id=f.get("id", str(uuid.uuid4())),
                finding_type=f.get("finding_type", "vulnerability"),
                severity=severity,
                title=f.get("title", f"Finding {i + 1}"),
                description=f.get("description", ""),
                file_path=f.get("file_path"),
                line_number=f.get("line_number"),
                cve_id=f.get("cve_id"),
                package_name=f.get("package_name"),
                package_version=f.get("package_version"),
                recommendation=f.get("recommendation"),
                metadata=f.get("metadata", {}),
            )
            findings.append(finding)

        # Determine event type based on findings severity
        has_critical = any(f.severity == SecuritySeverity.CRITICAL for f in findings)
        event_type = (
            SecurityEventType.SAST_CRITICAL
            if has_critical
            else SecurityEventType.VULNERABILITY_DETECTED
        )

        # Create security event
        event = SecurityEvent(
            event_type=event_type,
            severity=SecuritySeverity.CRITICAL if has_critical else SecuritySeverity.HIGH,
            source="api",
            repository=repository,
            findings=findings,
        )

        # Run the debate
        start_time = datetime.now(timezone.utc)

        async def _run_debate():
            return await run_security_debate(
                event,
                confidence_threshold=confidence_threshold,
                timeout_seconds=timeout_seconds,
            )

        debate_coro: Coroutine[Any, Any, Any] | None = _run_debate()

        try:
            result = run_async(debate_coro)
        except (RuntimeError, OSError, ConnectionError, TimeoutError, ValueError, TypeError):
            if debate_coro is not None:
                debate_coro.close()
            logger.exception("Security debate failed")
            return error_response("Debate operation failed", 500)
        else:
            if debate_coro is not None:
                debate_coro.close()

        end_time = datetime.now(timezone.utc)
        duration_ms = (end_time - start_time).total_seconds() * 1000

        response_debate_id = result.debate_id if hasattr(result, "debate_id") else event.id

        try:
            from aragora.events.security_events import _store_security_debate_result
        except ImportError:
            logger.debug("Security debate result store unavailable")
        else:
            store_coro: Coroutine[Any, Any, Any] | None = _store_security_debate_result(
                response_debate_id,
                event,
                result,
            )
            try:
                run_async(store_coro)
            except (RuntimeError, OSError, ConnectionError, TimeoutError, ValueError, TypeError):
                logger.exception(
                    "Failed to persist security debate result for %s", response_debate_id
                )
            finally:
                if store_coro is not None:
                    store_coro.close()

        # Build response
        response = {
            "debate_id": response_debate_id,
            "status": "completed",
            "debate_status": DebateStatus.COMPLETED.value,
            "debate_status_source": DebateStatusSource.LIVE.value,
            "consensus_reached": result.consensus_reached,
            "confidence": result.confidence,
            "final_answer": result.final_answer,
            "rounds_used": result.rounds_used,
            "duration_ms": round(duration_ms),
            "findings_analyzed": len(findings),
        }

        # Include votes if available
        if hasattr(result, "votes") and result.votes:
            response["votes"] = {
                v.agent_name: v.vote
                for v in result.votes
                if hasattr(v, "agent_name") and hasattr(v, "vote")
            }

        logger.info(
            f"Security debate {response['debate_id']} completed: "
            f"consensus={result.consensus_reached}, confidence={result.confidence:.2f}"
        )

        return json_response(response)

    @require_permission("audit:read")
    def get_api_v1_audit_security_debate_id(self, debate_id: str) -> HandlerResult:
        """
        Get the status of a security debate.

        This endpoint allows checking on the status of a previously triggered
        security debate. Debates are still synchronous, but completed results
        are cached in-process so callers can re-fetch the latest status payload.

        Returns:
            {
                "debate_id": "uuid",
                "status": "completed|not_found",
                "debate_status": "completed|pending",
                "debate_status_source": "live|receipt|cached",
                "message": "Status message"
            }
        """
        cached_result: dict[str, Any] | None = None
        try:
            from aragora.events.security_events import get_security_debate_result
        except ImportError:
            logger.debug("Security debate result store unavailable")
        else:
            fetch_coro: Coroutine[Any, Any, Any] | None = get_security_debate_result(debate_id)
            try:
                cached = run_async(fetch_coro)
            except (RuntimeError, OSError, ConnectionError, TimeoutError, ValueError, TypeError):
                logger.exception("Failed to load cached security debate result for %s", debate_id)
            else:
                if isinstance(cached, dict):
                    cached_result = dict(cached)
            finally:
                if fetch_coro is not None:
                    fetch_coro.close()

        if cached_result is not None:
            cached_result.setdefault("debate_id", debate_id)
            cached_result.setdefault("status", DebateStatus.COMPLETED.value)
            cached_result.setdefault("debate_status", DebateStatus.COMPLETED.value)
            cached_result.setdefault("debate_status_source", DebateStatusSource.LIVE.value)
            cached_result.setdefault("message", "Cached security debate result available.")
            return json_response(cached_result)

        return json_response(
            {
                "debate_id": debate_id,
                "status": "not_found",
                "debate_status": DebateStatus.PENDING.value,
                "debate_status_source": DebateStatusSource.LIVE.value,
                "message": "No cached security debate result found. Use POST to trigger a new debate.",
            }
        )
