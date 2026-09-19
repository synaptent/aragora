"""
Policy and Compliance endpoint handlers.

Provides CRUD operations for compliance policies and violation tracking.

Endpoints:
- GET  /api/policies                    - List policies
- GET  /api/policies/:id                - Get policy details
- POST /api/policies                    - Create policy
- PATCH /api/policies/:id               - Update policy
- DELETE /api/policies/:id              - Delete policy
- POST /api/policies/:id/toggle         - Toggle policy enabled status
- GET  /api/policies/:id/violations     - Get violations for a policy
- GET  /api/compliance/violations       - List all violations
- GET  /api/compliance/violations/:id   - Get violation details
- PATCH /api/compliance/violations/:id  - Update violation status
- POST /api/compliance/check            - Run compliance check on content
- GET  /api/compliance/stats            - Get compliance statistics
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from aragora.server.validation import validate_path_segment, SAFE_ID_PATTERN
from aragora.audit.unified import audit_security

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    get_bool_param,
    get_int_param,
    get_string_param,
    json_response,
)
from ..utils.decorators import require_permission
from ..utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)


class PolicyHandler(BaseHandler):
    """Handler for policy and compliance endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/v1/policies",
        "/api/v1/policies/*",
        "/api/v1/policies/*/toggle",
        "/api/v1/policies/*/violations",
        "/api/v1/policies/validate",
        "/api/v1/policies/violations",
        "/api/v1/compliance/violations",
        "/api/v1/compliance/violations/*",
        "/api/v1/compliance/check",
        "/api/v1/compliance/stats",
        "/api/v1/compliance/status",
        "/api/v1/compliance/summary",
        "/api/v1/compliance/audit-events",
        "/api/v1/compliance/audit-verify",
        "/api/v1/compliance/soc2-report",
        "/api/v1/compliance/gdpr-export",
        "/api/v1/compliance/gdpr/right-to-be-forgotten",
        "/api/v1/compliance/eu-ai-act/audit",
        "/api/v1/compliance/eu-ai-act/classify",
        "/api/v1/compliance/eu-ai-act/generate-bundle",
        "/api/v1/compliance/hipaa/status",
        "/api/v1/compliance/hipaa/baa",
        "/api/v1/compliance/hipaa/detect-phi",
        "/api/v1/compliance/hipaa/deidentify",
        "/api/v1/compliance/hipaa/phi-access",
        "/api/v1/compliance/hipaa/breach-assessment",
        "/api/v1/compliance/hipaa/security-report",
        "/api/v1/compliance/hipaa/safe-harbor/verify",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can handle the request."""
        if path == "/api/v1/policies":
            return True
        if path.startswith("/api/v1/policies/"):
            return True
        if path.startswith("/api/v1/compliance/"):
            return True
        return False

    @rate_limit(requests_per_minute=120)
    async def handle(
        self,
        path: str,
        query_params: dict[str, Any] | str,
        handler: Any = None,
        method: str | None = None,
    ) -> HandlerResult | None:
        """Route request to appropriate handler method."""
        if method is None and isinstance(query_params, str):
            method = query_params
            query_params = {}
        if method is None:
            method = "GET"
        if handler:
            if hasattr(handler, "command"):
                method = handler.command
            # Also parse query params from the handler path if not already provided
            if not query_params and hasattr(handler, "path") and "?" in handler.path:
                query_str = handler.path.split("?", 1)[1]
                from urllib.parse import parse_qs

                query_params = parse_qs(query_str)

        # === Policy endpoints ===

        # GET /api/policies - List policies
        if path == "/api/v1/policies" and method == "GET":
            return self._list_policies(query_params)

        # POST /api/policies - Create policy
        if path == "/api/v1/policies" and method == "POST":
            return await self._create_policy(handler)

        if path.startswith("/api/v1/policies/") and not path.startswith(
            "/api/v1/policies/compliance"
        ):
            parts = path.split("/")
            # Parts: ["", "api", "v1", "policies", ":id", ...]

            # POST /api/v1/policies/:id/toggle (6 parts)
            if len(parts) == 6 and parts[5] == "toggle" and method == "POST":
                policy_id = parts[4]
                is_valid, err = validate_path_segment(policy_id, "policy_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
                return await self._toggle_policy(policy_id, handler)

            # GET /api/v1/policies/:id/violations (6 parts)
            if len(parts) == 6 and parts[5] == "violations" and method == "GET":
                policy_id = parts[4]
                is_valid, err = validate_path_segment(policy_id, "policy_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
                return self._get_policy_violations(policy_id, query_params)

            # GET /api/v1/policies/:id - Get policy (5 parts)
            if len(parts) == 5 and method == "GET":
                policy_id = parts[4]
                is_valid, err = validate_path_segment(policy_id, "policy_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
                return self._get_policy(policy_id)

            # PATCH /api/v1/policies/:id - Update policy (5 parts)
            if len(parts) == 5 and method == "PATCH":
                policy_id = parts[4]
                is_valid, err = validate_path_segment(policy_id, "policy_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
                return await self._update_policy(policy_id, handler)

            # DELETE /api/v1/policies/:id - Delete policy (5 parts)
            if len(parts) == 5 and method == "DELETE":
                policy_id = parts[4]
                is_valid, err = validate_path_segment(policy_id, "policy_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
                return self._delete_policy(policy_id)

        # === Compliance endpoints ===

        # GET /api/compliance/violations - List violations
        if path == "/api/v1/compliance/violations" and method == "GET":
            return self._list_violations(query_params)

        # POST /api/compliance/check - Run compliance check
        if path == "/api/v1/compliance/check" and method == "POST":
            return await self._check_compliance(handler)

        # GET /api/compliance/stats - Get compliance stats
        if path == "/api/v1/compliance/stats" and method == "GET":
            return self._get_stats(query_params)

        if path.startswith("/api/v1/compliance/violations/"):
            parts = path.split("/")
            # Parts: ["", "api", "v1", "compliance", "violations", ":id"]

            # GET /api/v1/compliance/violations/:id - Get violation (6 parts)
            if len(parts) == 6 and method == "GET":
                violation_id = parts[5]
                is_valid, err = validate_path_segment(violation_id, "violation_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
                return self._get_violation(violation_id)

            # PATCH /api/v1/compliance/violations/:id - Update violation status (6 parts)
            if len(parts) == 6 and method == "PATCH":
                violation_id = parts[5]
                is_valid, err = validate_path_segment(violation_id, "violation_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
                return await self._update_violation(violation_id, handler)

        return None

    def _get_policy_store(self):
        """Get or create the policy store."""
        try:
            from aragora.compliance.policy_store import get_policy_store

            return get_policy_store()
        except ImportError:
            logger.warning("Policy store module not available")
            return None

    def _get_compliance_manager(self):
        """Get the compliance framework manager."""
        try:
            from aragora.compliance.framework import ComplianceFrameworkManager

            return ComplianceFrameworkManager()
        except ImportError:
            logger.warning("Compliance framework module not available")
            return None

    # =========================================================================
    # Policy Handlers
    # =========================================================================

    @require_permission("policies:read")
    def _list_policies(self, query_params: dict[str, Any]) -> HandlerResult:
        """List policies with optional filters."""
        store = self._get_policy_store()
        if store is None:
            return error_response("Policy store not available", 503)

        try:
            workspace_id = get_string_param(query_params, "workspace_id", None)
            vertical_id = get_string_param(query_params, "vertical_id", None)
            framework_id = get_string_param(query_params, "framework_id", None)
            enabled_only = get_bool_param(query_params, "enabled_only", False)
            limit = get_int_param(query_params, "limit", 100)
            offset = get_int_param(query_params, "offset", 0)

            policies = store.list_policies(
                workspace_id=workspace_id,
                vertical_id=vertical_id,
                framework_id=framework_id,
                enabled_only=enabled_only,
                limit=limit,
                offset=offset,
            )

            return json_response(
                {
                    "policies": [p.to_dict() for p in policies],
                    "total": len(policies),
                    "limit": limit,
                    "offset": offset,
                }
            )

        except (KeyError, ValueError, OSError, TypeError, AttributeError, RuntimeError) as e:
            logger.error("Failed to list policies: %s", e)
            return error_response("Failed to list policies", 500)

    @require_permission("policies:read")
    def _get_policy(self, policy_id: str) -> HandlerResult:
        """Get a specific policy."""
        store = self._get_policy_store()
        if store is None:
            return error_response("Policy store not available", 503)

        try:
            policy = store.get_policy(policy_id)
            if policy is None:
                return error_response(f"Policy not found: {policy_id}", 404)

            return json_response({"policy": policy.to_dict()})

        except (KeyError, ValueError, OSError, TypeError, AttributeError, RuntimeError) as e:
            logger.error("Failed to get policy %s: %s", policy_id, e)
            return error_response("Failed to retrieve policy", 500)

    @require_permission("policies:create")
    async def _create_policy(self, handler: Any) -> HandlerResult:
        """Create a new policy."""
        store = self._get_policy_store()
        if store is None:
            return error_response("Policy store not available", 503)

        try:
            # Read request body
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 10 * 1024 * 1024:
                return error_response("Request body too large", 413)
            body = handler.rfile.read(content_length).decode("utf-8")
            data = json.loads(body) if body else {}

            # Validate required fields
            required = ["name", "framework_id", "vertical_id"]
            for field in required:
                if field not in data:
                    return error_response(f"Missing required field: {field}", 400)

            # Create policy
            from aragora.compliance.policy_store import Policy, PolicyRule

            policy_id = f"pol_{uuid.uuid4().hex[:12]}"
            rules = [PolicyRule.from_dict(r) for r in data.get("rules", [])]

            policy = Policy(
                id=policy_id,
                name=data["name"],
                description=data.get("description", ""),
                framework_id=data["framework_id"],
                workspace_id=data.get("workspace_id", "default"),
                vertical_id=data["vertical_id"],
                level=data.get("level", "recommended"),
                enabled=data.get("enabled", True),
                rules=rules,
                metadata=data.get("metadata", {}),
            )

            created = store.create_policy(policy)

            # Get user for audit
            user_id = "system"
            if hasattr(handler, "user_context") and handler.user_context:
                user_id = handler.user_context.user_id

            audit_security(
                event_type="policy_created",
                actor_id=user_id,
                resource_type="policy",
                resource_id=policy_id,
                policy_name=data["name"],
                framework_id=data["framework_id"],
            )

            return json_response(
                {
                    "policy": created.to_dict(),
                    "message": "Policy created successfully",
                },
                status=201,
            )

        except json.JSONDecodeError:
            return error_response("Invalid JSON body", 400)
        except (KeyError, ValueError, OSError, TypeError, AttributeError, RuntimeError) as e:
            logger.error("Failed to create policy: %s", e)
            return error_response("Policy creation failed", 500)

    @require_permission("policies:update")
    async def _update_policy(self, policy_id: str, handler: Any) -> HandlerResult:
        """Update a policy."""
        store = self._get_policy_store()
        if store is None:
            return error_response("Policy store not available", 503)

        try:
            # Read request body
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 10 * 1024 * 1024:
                return error_response("Request body too large", 413)
            body = handler.rfile.read(content_length).decode("utf-8")
            data = json.loads(body) if body else {}

            if not data:
                return error_response("No update data provided", 400)

            # Get user for audit
            user_id = None
            if hasattr(handler, "user_context") and handler.user_context:
                user_id = handler.user_context.user_id

            updated = store.update_policy(policy_id, data, changed_by=user_id)
            if updated is None:
                return error_response(f"Policy not found: {policy_id}", 404)

            audit_security(
                event_type="policy_updated",
                actor_id=user_id or "system",
                resource_type="policy",
                resource_id=policy_id,
                changes=list(data.keys()),
            )

            return json_response(
                {
                    "policy": updated.to_dict(),
                    "message": "Policy updated successfully",
                }
            )

        except json.JSONDecodeError:
            return error_response("Invalid JSON body", 400)
        except (KeyError, ValueError, OSError, TypeError, AttributeError, RuntimeError) as e:
            logger.error("Failed to update policy %s: %s", policy_id, e)
            return error_response("Policy update failed", 500)

    @require_permission("policies:delete")
    def _delete_policy(self, policy_id: str) -> HandlerResult:
        """Delete a policy."""
        store = self._get_policy_store()
        if store is None:
            return error_response("Policy store not available", 503)

        try:
            success = store.delete_policy(policy_id)
            if not success:
                return error_response(f"Policy not found: {policy_id}", 404)

            audit_security(
                event_type="policy_deleted",
                actor_id="system",
                resource_type="policy",
                resource_id=policy_id,
            )

            return json_response(
                {
                    "message": "Policy deleted successfully",
                    "policy_id": policy_id,
                }
            )

        except (KeyError, ValueError, OSError, TypeError, AttributeError, RuntimeError) as e:
            logger.error("Failed to delete policy %s: %s", policy_id, e)
            return error_response("Policy deletion failed", 500)

    @require_permission("policies:update")
    async def _toggle_policy(self, policy_id: str, handler: Any) -> HandlerResult:
        """Toggle a policy's enabled status."""
        store = self._get_policy_store()
        if store is None:
            return error_response("Policy store not available", 503)

        try:
            # Read request body for enabled state
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 10 * 1024 * 1024:
                return error_response("Request body too large", 413)
            body = handler.rfile.read(content_length).decode("utf-8")
            data = json.loads(body) if body else {}

            enabled = data.get("enabled")
            if enabled is None:
                # Toggle current state
                policy = store.get_policy(policy_id)
                if policy is None:
                    return error_response(f"Policy not found: {policy_id}", 404)
                enabled = not policy.enabled

            user_id = None
            if hasattr(handler, "user_context") and handler.user_context:
                user_id = handler.user_context.user_id

            success = store.toggle_policy(policy_id, enabled, changed_by=user_id)
            if not success:
                return error_response(f"Policy not found: {policy_id}", 404)

            audit_security(
                event_type="policy_toggled",
                actor_id=user_id or "system",
                resource_type="policy",
                resource_id=policy_id,
                enabled=enabled,
            )

            return json_response(
                {
                    "message": f"Policy {'enabled' if enabled else 'disabled'} successfully",
                    "policy_id": policy_id,
                    "enabled": enabled,
                }
            )

        except json.JSONDecodeError:
            return error_response("Invalid JSON body", 400)
        except (KeyError, ValueError, OSError, TypeError, AttributeError, RuntimeError) as e:
            logger.error("Failed to toggle policy %s: %s", policy_id, e)
            return error_response("Policy toggle failed", 500)

    @require_permission("policies:read")
    def _get_policy_violations(self, policy_id: str, query_params: dict[str, Any]) -> HandlerResult:
        """Get violations for a specific policy."""
        store = self._get_policy_store()
        if store is None:
            return error_response("Policy store not available", 503)

        try:
            # Verify policy exists
            policy = store.get_policy(policy_id)
            if policy is None:
                return error_response(f"Policy not found: {policy_id}", 404)

            status = get_string_param(query_params, "status", None)
            severity = get_string_param(query_params, "severity", None)
            limit = get_int_param(query_params, "limit", 100)
            offset = get_int_param(query_params, "offset", 0)

            violations = store.list_violations(
                policy_id=policy_id,
                status=status,
                severity=severity,
                limit=limit,
                offset=offset,
            )

            return json_response(
                {
                    "violations": [v.to_dict() for v in violations],
                    "total": len(violations),
                    "policy_id": policy_id,
                }
            )

        except (KeyError, ValueError, OSError, TypeError, AttributeError, RuntimeError) as e:
            logger.error("Failed to get violations for policy %s: %s", policy_id, e)
            return error_response("Failed to retrieve violations", 500)

    # =========================================================================
    # Violation Handlers
    # =========================================================================

    @require_permission("policies:read")
    def _list_violations(self, query_params: dict[str, Any]) -> HandlerResult:
        """List all violations with optional filters."""
        store = self._get_policy_store()
        if store is None:
            return error_response("Policy store not available", 503)

        try:
            workspace_id = get_string_param(query_params, "workspace_id", None)
            vertical_id = get_string_param(query_params, "vertical_id", None)
            framework_id = get_string_param(query_params, "framework_id", None)
            status = get_string_param(query_params, "status", None)
            severity = get_string_param(query_params, "severity", None)
            limit = get_int_param(query_params, "limit", 100)
            offset = get_int_param(query_params, "offset", 0)

            violations = store.list_violations(
                workspace_id=workspace_id,
                vertical_id=vertical_id,
                framework_id=framework_id,
                status=status,
                severity=severity,
                limit=limit,
                offset=offset,
            )

            return json_response(
                {
                    "violations": [v.to_dict() for v in violations],
                    "total": len(violations),
                    "limit": limit,
                    "offset": offset,
                }
            )

        except (KeyError, ValueError, OSError, TypeError, AttributeError, RuntimeError) as e:
            logger.error("Failed to list violations: %s", e)
            return error_response("Failed to list violations", 500)

    @require_permission("policies:read")
    def _get_violation(self, violation_id: str) -> HandlerResult:
        """Get a specific violation."""
        store = self._get_policy_store()
        if store is None:
            return error_response("Policy store not available", 503)

        try:
            violation = store.get_violation(violation_id)
            if violation is None:
                return error_response(f"Violation not found: {violation_id}", 404)

            return json_response({"violation": violation.to_dict()})

        except (KeyError, ValueError, OSError, TypeError, AttributeError, RuntimeError) as e:
            logger.error("Failed to get violation %s: %s", violation_id, e)
            return error_response("Failed to retrieve violation", 500)

    @require_permission("policies:update")
    async def _update_violation(self, violation_id: str, handler: Any) -> HandlerResult:
        """Update a violation's status."""
        store = self._get_policy_store()
        if store is None:
            return error_response("Policy store not available", 503)

        try:
            # Read request body
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 10 * 1024 * 1024:
                return error_response("Request body too large", 413)
            body = handler.rfile.read(content_length).decode("utf-8")
            data = json.loads(body) if body else {}

            status = data.get("status")
            if not status:
                return error_response("Missing required field: status", 400)

            valid_statuses = ["open", "investigating", "resolved", "false_positive"]
            if status not in valid_statuses:
                return error_response(
                    f"Invalid status: {status}. Valid values: {valid_statuses}", 400
                )

            user_id = None
            if hasattr(handler, "user_context") and handler.user_context:
                user_id = handler.user_context.user_id

            updated = store.update_violation_status(
                violation_id=violation_id,
                status=status,
                resolved_by=user_id,
                resolution_notes=data.get("resolution_notes"),
            )

            if updated is None:
                return error_response(f"Violation not found: {violation_id}", 404)

            audit_security(
                event_type="violation_status_updated",
                actor_id=user_id or "system",
                resource_type="violation",
                resource_id=violation_id,
                new_status=status,
            )

            return json_response(
                {
                    "violation": updated.to_dict(),
                    "message": f"Violation status updated to {status}",
                }
            )

        except json.JSONDecodeError:
            return error_response("Invalid JSON body", 400)
        except (KeyError, ValueError, OSError, TypeError, AttributeError, RuntimeError) as e:
            logger.error("Failed to update violation %s: %s", violation_id, e)
            return error_response("Violation update failed", 500)

    # =========================================================================
    # Compliance Check
    # =========================================================================

    @require_permission("policies:create")
    async def _check_compliance(self, handler: Any) -> HandlerResult:
        """Run compliance check on content."""
        manager = self._get_compliance_manager()
        if manager is None:
            return error_response("Compliance manager not available", 503)

        try:
            # Read request body
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 10 * 1024 * 1024:
                return error_response("Request body too large", 413)
            body = handler.rfile.read(content_length).decode("utf-8")
            data = json.loads(body) if body else {}

            content = data.get("content")
            if not content:
                return error_response("Missing required field: content", 400)

            frameworks = data.get("frameworks")  # Optional list of framework IDs
            min_severity = data.get("min_severity", "low")

            # Map string to enum
            from aragora.compliance.framework import ComplianceSeverity

            try:
                severity_enum = ComplianceSeverity(min_severity)
            except ValueError:
                return error_response(
                    f"Invalid min_severity: {min_severity}. "
                    f"Valid values: critical, high, medium, low, info",
                    400,
                )

            result = manager.check(content, frameworks=frameworks, min_severity=severity_enum)

            # Optionally store violations
            store_violations = data.get("store_violations", False)
            if store_violations and result.issues:
                store = self._get_policy_store()
                if store:
                    workspace_id = data.get("workspace_id", "default")
                    source = data.get("source", "manual_check")

                    from aragora.compliance.policy_store import Violation

                    for issue in result.issues:
                        violation = Violation(
                            id=f"viol_{uuid.uuid4().hex[:12]}",
                            policy_id="",
                            rule_id=issue.rule_id,
                            rule_name=issue.description,
                            framework_id=issue.framework,
                            vertical_id="",
                            workspace_id=workspace_id,
                            severity=issue.severity.value,
                            status="open",
                            description=issue.description,
                            source=source,
                            metadata=issue.metadata,
                        )
                        store.create_violation(violation)

            return json_response(
                {
                    "result": result.to_dict(),
                    "compliant": result.compliant,
                    "score": result.score,
                    "issue_count": len(result.issues),
                }
            )

        except json.JSONDecodeError:
            return error_response("Invalid JSON body", 400)
        except (KeyError, ValueError, OSError, TypeError, AttributeError, RuntimeError) as e:
            logger.error("Failed to check compliance: %s", e)
            return error_response("Compliance check failed", 500)

    @require_permission("policies:read")
    def _get_stats(self, query_params: dict[str, Any]) -> HandlerResult:
        """Get compliance statistics."""
        store = self._get_policy_store()
        if store is None:
            return error_response("Policy store not available", 503)

        try:
            workspace_id = get_string_param(query_params, "workspace_id", None)

            # Get violation counts
            open_counts = store.count_violations(workspace_id=workspace_id, status="open")
            all_counts = store.count_violations(workspace_id=workspace_id)

            # Get policy counts
            policies = store.list_policies(workspace_id=workspace_id)
            enabled_policies = [p for p in policies if p.enabled]

            return json_response(
                {
                    "policies": {
                        "total": len(policies),
                        "enabled": len(enabled_policies),
                        "disabled": len(policies) - len(enabled_policies),
                    },
                    "violations": {
                        "total": all_counts["total"],
                        "open": open_counts["total"],
                        "by_severity": {
                            "critical": open_counts["critical"],
                            "high": open_counts["high"],
                            "medium": open_counts["medium"],
                            "low": open_counts["low"],
                        },
                    },
                    "risk_score": min(
                        100,
                        sum(
                            [
                                open_counts["critical"] * 25,
                                open_counts["high"] * 10,
                                open_counts["medium"] * 5,
                                open_counts["low"] * 2,
                            ]
                        ),
                    ),
                }
            )

        except (KeyError, ValueError, OSError, TypeError, AttributeError, RuntimeError) as e:
            logger.error("Failed to get compliance stats: %s", e)
            return error_response("Failed to retrieve statistics", 500)


# Export for registration
__all__ = ["PolicyHandler"]
