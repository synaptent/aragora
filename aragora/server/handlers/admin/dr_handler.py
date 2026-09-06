"""
Disaster Recovery HTTP Handlers for Aragora.

Provides REST API endpoints for disaster recovery operations:
- DR readiness status
- DR drills (simulated recovery)
- Recovery point objectives (RPO) tracking
- Recovery time objectives (RTO) validation

Endpoints:
    GET  /api/v2/dr/status              - Get DR readiness status
    POST /api/v2/dr/drill               - Run DR drill (simulated recovery)
    GET  /api/v2/dr/objectives          - Get RPO/RTO objectives and current status
    POST /api/v2/dr/validate            - Validate DR configuration

These endpoints support enterprise disaster recovery requirements.
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Any

from aragora.backup.manager import BackupManager
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
)
from aragora.server.handlers.utils.lazy_stores import LazyStoreFactory
from aragora.server.handlers.utils.rate_limit import rate_limit
from aragora.rbac.decorators import require_permission

logger = logging.getLogger(__name__)


class DRHandler(BaseHandler):
    """
    HTTP handler for disaster recovery operations.

    Provides REST API access to DR status, drills, and objective tracking.
    """

    ROUTES = [
        "/api/v2/dr",
        "/api/v2/dr/*",
    ]

    _manager: BackupManager | None

    def __init__(self, server_context: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(server_context)
        self._manager_factory = LazyStoreFactory(
            store_name="backup_manager",
            import_path="aragora.backup.manager",
            factory_name="get_backup_manager",
            logger_context="DR",
        )
        self._manager = None  # Set by tests or lazy init

    def _get_backup_manager(self) -> BackupManager:
        """Get backup manager for DR operations."""
        if self._manager is None:
            self._manager = self._manager_factory.get()
        return self._manager

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the request."""
        if path.startswith("/api/v2/dr"):
            return method in ("GET", "POST")
        return False

    @rate_limit(requests_per_minute=30)
    async def handle(  # type: ignore[override]
        self,
        path_or_method: str | None = None,
        query_params_or_path: dict[str, Any] | str | None = None,
        handler_or_body: Any = None,
        query_params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        *,
        method: str | None = None,
        path: str | None = None,
        body: dict[str, Any] | None = None,
    ) -> HandlerResult:
        """Route request to appropriate handler method.

        Supports three calling conventions:
        1. Base class style: handle(path, query_params, handler)
        2. Extended positional style: handle(method, path, body, query_params, headers)
        3. Extended keyword style: handle(method=method, path=path, body=body)

        The calling convention is detected by checking the arguments.
        """
        resolved_body: dict[str, Any]
        resolved_method: str
        resolved_path: str

        # Check if using keyword argument style (method= and path= kwargs)
        if method is not None and path is not None:
            # Extended keyword style: handle(method=method, path=path, body=body)
            resolved_method = method
            resolved_path = path
            resolved_body = body or {}
        elif path_or_method is None:
            # No arguments provided - return error
            return error_response("Invalid request: no path or method provided", 400)
        elif isinstance(query_params_or_path, dict) or query_params_or_path is None:
            # Base class calling convention: handle(path, query_params, handler)
            resolved_path = path_or_method
            handler = handler_or_body
            # Extract method from handler if available
            resolved_method = getattr(handler, "command", "GET") if handler else "GET"
            # Extract body from handler if available, or use explicit body kwarg
            resolved_body = (
                body if body is not None else (self.read_json_body(handler) if handler else {})
            )
        else:
            # Extended positional style: handle(method, path, body, query_params, headers)
            resolved_method = path_or_method
            resolved_path = str(query_params_or_path)
            # Use explicit body kwarg if provided, otherwise use positional arg
            if body is not None:
                resolved_body = body
            elif isinstance(handler_or_body, dict):
                resolved_body = handler_or_body
            else:
                resolved_body = {}

        resolved_body = resolved_body or {}

        if resolved_method == "GET" and resolved_path in {"/api/v2/dr", "/api/v2/dr/"}:
            resolved_path = "/api/v2/dr/status"

        try:
            # Status endpoint
            if resolved_path == "/api/v2/dr/status" and resolved_method == "GET":
                return await self._get_status()

            # Drill endpoint
            if resolved_path == "/api/v2/dr/drill" and resolved_method == "POST":
                return await self._run_drill(resolved_body)

            # Objectives endpoint
            if resolved_path == "/api/v2/dr/objectives" and resolved_method == "GET":
                return await self._get_objectives()

            # Validate endpoint
            if resolved_path == "/api/v2/dr/validate" and resolved_method == "POST":
                return await self._validate_configuration(resolved_body)

            return error_response("Not found", 404)

        except (
            KeyError,
            ValueError,
            TypeError,
            OSError,
            RuntimeError,
        ) as e:  # broad catch: last-resort handler
            logger.exception("Error handling DR request: %s", e)
            return error_response("Internal server error", 500)

    @require_permission("dr:read")
    async def _get_status(self) -> HandlerResult:
        """
        Get DR readiness status.

        Returns:
            - Overall readiness score (0-100)
            - Backup status
            - Last successful backup
            - RPO/RTO compliance
            - Issues and recommendations
        """
        manager = self._get_backup_manager()
        backups = manager.list_backups()

        from aragora.backup.manager import BackupStatus

        now = datetime.now(timezone.utc)

        # Get latest verified backup
        latest = manager.get_latest_backup()

        # Calculate readiness metrics
        verified_count = sum(1 for b in backups if b.verified)
        failed_count = sum(1 for b in backups if b.status == BackupStatus.FAILED)

        # RPO check (default: 24 hours)
        rpo_hours = 24
        rpo_compliant = False
        hours_since_backup = None
        if latest:
            hours_since_backup = (now - latest.created_at).total_seconds() / 3600
            rpo_compliant = hours_since_backup <= rpo_hours

        # Calculate readiness score
        issues = []
        recommendations = []
        score = 100

        if not backups:
            score -= 50
            issues.append("No backups found")
            recommendations.append("Create at least one backup immediately")

        if not latest:
            score -= 30
            issues.append("No verified backup available")
            recommendations.append("Verify at least one backup")

        if hours_since_backup is not None and not rpo_compliant:
            score -= 20
            issues.append(f"RPO violation: {hours_since_backup:.1f} hours since last backup")
            recommendations.append(f"Create a backup to meet {rpo_hours}h RPO")

        if failed_count > 0:
            score -= min(failed_count * 5, 20)
            issues.append(f"{failed_count} failed backups")
            recommendations.append("Investigate and resolve backup failures")

        if verified_count < len(backups) * 0.8:
            score -= 10
            issues.append("Less than 80% of backups are verified")
            recommendations.append("Run verification on unverified backups")

        # Ensure score stays in valid range
        score = max(0, min(100, score))

        # Determine overall status
        if score >= 90:
            overall_status = "healthy"
        elif score >= 70:
            overall_status = "warning"
        else:
            overall_status = "critical"

        return json_response(
            {
                "status": overall_status,
                "readiness_score": score,
                "backup_status": {
                    "total_backups": len(backups),
                    "verified_backups": verified_count,
                    "failed_backups": failed_count,
                    "latest_backup": latest.to_dict() if latest else None,
                    "hours_since_backup": round(hours_since_backup, 2)
                    if hours_since_backup
                    else None,
                },
                "rpo_status": {
                    "target_hours": rpo_hours,
                    "compliant": rpo_compliant,
                    "current_hours": round(hours_since_backup, 2) if hours_since_backup else None,
                },
                "issues": issues,
                "recommendations": recommendations,
                "checked_at": now.isoformat(),
            }
        )

    @require_permission("dr:drill")
    async def _run_drill(self, body: dict[str, Any]) -> HandlerResult:
        """
        Run a DR drill (simulated recovery).

        Body:
            backup_id: ID of backup to use for drill (optional, uses latest if not specified)
            drill_type: Type of drill (restore_test, full_recovery_sim, failover_test)
            target_path: Optional target path for restore test
        """
        backup_id = body.get("backup_id")
        drill_type = body.get("drill_type", "restore_test")
        target_path = body.get(
            "target_path", os.path.join(tempfile.gettempdir(), "dr_drill_test.db")
        )

        manager = self._get_backup_manager()
        start_time = datetime.now(timezone.utc)

        # Get backup to use
        if backup_id:
            backups = manager.list_backups()
            backup = next((b for b in backups if b.id == backup_id), None)
            if not backup:
                return error_response(f"Backup not found: {backup_id}", 404)
        else:
            backup = manager.get_latest_backup()
            if not backup:
                return error_response("No verified backup available for drill", 400)
            backup_id = backup.id

        drill_results = {
            "drill_id": f"drill_{start_time.strftime('%Y%m%d_%H%M%S')}",
            "drill_type": drill_type,
            "backup_id": backup_id,
            "started_at": start_time.isoformat(),
            "steps": [],
        }

        try:
            if drill_type == "restore_test":
                # Simple restore test (dry-run)
                drill_results["steps"].append({"step": "verify_backup", "status": "running"})

                result = manager.verify_restore_comprehensive(backup_id)
                drill_results["steps"][-1]["status"] = "completed" if result.verified else "failed"
                drill_results["steps"][-1]["details"] = result.to_dict()

                if not result.verified:
                    drill_results["success"] = False
                    drill_results["error"] = "Backup verification failed"
                else:
                    drill_results["steps"].append({"step": "restore_dry_run", "status": "running"})
                    success = manager.restore_backup(backup_id, target_path, dry_run=True)
                    drill_results["steps"][-1]["status"] = "completed" if success else "failed"
                    drill_results["success"] = success

            elif drill_type == "full_recovery_sim":
                # Full recovery simulation
                drill_results["steps"].append({"step": "verify_backup", "status": "running"})
                result = manager.verify_restore_comprehensive(backup_id)
                drill_results["steps"][-1]["status"] = "completed" if result.verified else "failed"

                drill_results["steps"].append({"step": "schema_validation", "status": "running"})
                drill_results["steps"][-1]["status"] = (
                    "completed"
                    if result.schema_validation and result.schema_validation.valid
                    else "failed"
                )

                drill_results["steps"].append({"step": "integrity_check", "status": "running"})
                drill_results["steps"][-1]["status"] = (
                    "completed"
                    if result.integrity_check and result.integrity_check.valid
                    else "failed"
                )

                drill_results["steps"].append({"step": "restore_dry_run", "status": "running"})
                success = manager.restore_backup(backup_id, target_path, dry_run=True)
                drill_results["steps"][-1]["status"] = "completed" if success else "failed"

                drill_results["success"] = result.verified and success

            elif drill_type == "failover_test":
                # Failover test - verify all recent backups
                drill_results["steps"].append(
                    {"step": "verify_recent_backups", "status": "running"}
                )

                recent = manager.list_backups()[:5]  # Last 5 backups
                verified_count = 0

                for b in recent:
                    verify_result = manager.verify_backup(b.id, test_restore=True)
                    if verify_result.verified:
                        verified_count += 1

                drill_results["steps"][-1]["status"] = "completed"
                drill_results["steps"][-1]["details"] = {
                    "checked": len(recent),
                    "verified": verified_count,
                }

                drill_results["success"] = verified_count > 0

            else:
                return error_response(
                    f"Unknown drill type: {drill_type}. "
                    "Valid: restore_test, full_recovery_sim, failover_test",
                    400,
                )

        except (OSError, RuntimeError, ValueError) as e:
            logger.exception("DR drill failed: %s", e)
            drill_results["success"] = False
            drill_results["error"] = "DR drill failed"

        end_time = datetime.now(timezone.utc)
        drill_results["completed_at"] = end_time.isoformat()
        drill_results["duration_seconds"] = (end_time - start_time).total_seconds()

        # Log drill result
        logger.info(
            "DR drill completed: %s, success=%s, duration=%.2fs",
            drill_results["drill_id"],
            drill_results.get("success"),
            drill_results["duration_seconds"],
        )

        return json_response(drill_results)

    @require_permission("dr:read")
    async def _get_objectives(self) -> HandlerResult:
        """
        Get RPO/RTO objectives and current compliance status.

        Returns:
            - RPO (Recovery Point Objective) configuration and status
            - RTO (Recovery Time Objective) estimates
            - Historical compliance data
        """
        manager = self._get_backup_manager()
        backups = manager.list_backups()
        latest = manager.get_latest_backup()

        now = datetime.now(timezone.utc)

        # Default objectives (could be configurable)
        rpo_target_hours = 24
        rto_target_minutes = 30

        # Calculate current RPO
        current_rpo_hours = None
        if latest:
            current_rpo_hours = (now - latest.created_at).total_seconds() / 3600

        # Estimate RTO based on latest backup size and typical restore time
        estimated_rto_minutes = None
        if latest and latest.compressed_size_bytes > 0:
            # Rough estimate: 100MB/minute restore speed
            mb = latest.compressed_size_bytes / (1024 * 1024)
            estimated_rto_minutes = max(1, mb / 100) + 5  # Base 5 min overhead

        # Calculate compliance history (last 7 days)
        week_ago = now - timedelta(days=7)
        recent_backups = [b for b in backups if b.created_at >= week_ago]

        # Check for RPO violations in history
        rpo_violations = 0
        if len(recent_backups) > 1:
            sorted_backups = sorted(recent_backups, key=lambda b: b.created_at)
            for i in range(1, len(sorted_backups)):
                gap = (
                    sorted_backups[i].created_at - sorted_backups[i - 1].created_at
                ).total_seconds() / 3600
                if gap > rpo_target_hours:
                    rpo_violations += 1

        return json_response(
            {
                "rpo": {
                    "target_hours": rpo_target_hours,
                    "current_hours": round(current_rpo_hours, 2) if current_rpo_hours else None,
                    "compliant": current_rpo_hours is not None
                    and current_rpo_hours <= rpo_target_hours,
                    "violations_last_7_days": rpo_violations,
                },
                "rto": {
                    "target_minutes": rto_target_minutes,
                    "estimated_minutes": round(estimated_rto_minutes, 1)
                    if estimated_rto_minutes
                    else None,
                    "compliant": estimated_rto_minutes is not None
                    and estimated_rto_minutes <= rto_target_minutes,
                },
                "backup_coverage": {
                    "total_backups": len(backups),
                    "backups_last_7_days": len(recent_backups),
                    "latest_backup": latest.to_dict() if latest else None,
                },
                "generated_at": now.isoformat(),
            }
        )

    @require_permission("dr:read")
    async def _validate_configuration(self, body: dict[str, Any]) -> HandlerResult:
        """
        Validate DR configuration.

        Body:
            check_storage: Verify backup storage is accessible (default: true)
            check_permissions: Verify required permissions (default: true)
            check_encryption: Verify encryption configuration (default: true)
        """
        check_storage = body.get("check_storage", True)
        check_permissions = body.get("check_permissions", True)
        check_encryption = body.get("check_encryption", True)

        manager = self._get_backup_manager()
        checks: list[dict[str, Any]] = []
        validation_results: dict[str, Any] = {
            "valid": True,
            "checks": checks,
        }

        # Check RBAC permissions for backup operations
        if check_permissions:
            check: dict[str, Any] = {"name": "rbac_permissions", "status": "checking"}
            try:
                required_perms = ["dr:read", "dr:write", "dr:admin"]
                # Verify RBAC module is available and permissions are defined
                try:
                    from aragora.rbac.defaults import SYSTEM_PERMISSIONS

                    missing_perms = [
                        p
                        for p in required_perms
                        if not any(p in str(perm) for perm in SYSTEM_PERMISSIONS)
                    ]
                    if not missing_perms:
                        check["status"] = "passed"
                        check["details"] = f"Required permissions defined: {required_perms}"
                    else:
                        check["status"] = "warning"
                        check["details"] = f"Missing permission definitions: {missing_perms}"
                        check["recommendation"] = "Add missing permissions to RBAC defaults"
                except ImportError:
                    check["status"] = "warning"
                    check["details"] = "RBAC module not available"
                    check["recommendation"] = "Enable RBAC for production deployments"
            except (TypeError, ValueError, KeyError) as e:
                check["status"] = "failed"
                check["details"] = f"Permission check error: {e}"
                validation_results["valid"] = False
            checks.append(check)

        # Check encryption configuration
        if check_encryption:
            check = {"name": "encryption_config", "status": "checking"}
            try:
                # Check if encryption is enabled for backups
                encryption_enabled = getattr(manager, "encryption_enabled", False)
                encryption_key_set = bool(getattr(manager, "encryption_key", None))

                if encryption_enabled and encryption_key_set:
                    check["status"] = "passed"
                    check["details"] = "Backup encryption enabled with key configured"
                elif encryption_enabled and not encryption_key_set:
                    check["status"] = "failed"
                    check["details"] = "Encryption enabled but no key configured"
                    check["recommendation"] = (
                        "Set ARAGORA_BACKUP_ENCRYPTION_KEY environment variable"
                    )
                    validation_results["valid"] = False
                else:
                    check["status"] = "warning"
                    check["details"] = "Backup encryption not enabled"
                    check["recommendation"] = "Enable encryption for production backups"
            except (TypeError, ValueError, AttributeError) as e:
                check["status"] = "failed"
                check["details"] = f"Encryption check error: {e}"
                validation_results["valid"] = False
            checks.append(check)

        # Check storage access
        if check_storage:
            check = {"name": "storage_access", "status": "checking"}
            try:
                backup_dir = manager.backup_dir
                if backup_dir.exists() and backup_dir.is_dir():
                    # Test write permission
                    test_file = backup_dir / ".dr_test"
                    test_file.write_text("test")
                    test_file.unlink()
                    check["status"] = "passed"
                    check["details"] = f"Backup directory accessible: {backup_dir}"
                else:
                    check["status"] = "failed"
                    check["details"] = f"Backup directory not found: {backup_dir}"
                    validation_results["valid"] = False
            except (OSError, PermissionError) as e:
                check["status"] = "failed"
                check["details"] = f"Storage access error: {e}"
                validation_results["valid"] = False
            checks.append(check)

        # Check retention policy
        check = {"name": "retention_policy", "status": "checking"}
        policy = manager.retention_policy
        if policy.min_backups > 0:
            check["status"] = "passed"
            check["details"] = (
                f"Retention: {policy.keep_daily}d/{policy.keep_weekly}w/{policy.keep_monthly}m"
            )
        else:
            check["status"] = "warning"
            check["details"] = "min_backups is 0, could delete all backups"
        checks.append(check)

        # Check compression
        check = {"name": "compression", "status": "passed" if manager.compression else "info"}
        check["details"] = f"Compression enabled: {manager.compression}"
        checks.append(check)

        # Check auto-verify
        check = {
            "name": "auto_verify",
            "status": "passed" if manager.verify_after_backup else "warning",
        }
        check["details"] = f"Auto-verify after backup: {manager.verify_after_backup}"
        if not manager.verify_after_backup:
            check["recommendation"] = "Enable verify_after_backup for reliability"
        checks.append(check)

        # Check if there are any backups
        check = {"name": "backup_exists", "status": "checking"}
        backups = manager.list_backups()
        if backups:
            check["status"] = "passed"
            check["details"] = f"{len(backups)} backup(s) found"
        else:
            check["status"] = "warning"
            check["details"] = "No backups found"
            check["recommendation"] = "Create initial backup"
        checks.append(check)

        return json_response(validation_results)


# Handler factory function for registration
def create_dr_handler(server_context: dict[str, Any]) -> DRHandler:
    """Factory function for handler registration."""
    return DRHandler(server_context)
