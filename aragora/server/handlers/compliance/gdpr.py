"""
GDPR Compliance Handler.

Provides GDPR data operations including:
- Data export
- Right-to-be-forgotten (Article 17)
- Deletion management
- Consent revocation
- Backup exclusions
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    json_response,
)
from aragora.events.handler_events import emit_handler_event, COMPLETED
from aragora.rbac.decorators import require_permission
from aragora.observability.metrics import track_handler

logger = logging.getLogger(__name__)


def _get_compliance_module():
    """Resolve compliance helpers via the shim so tests can patch them."""
    from aragora.server.handlers.compliance import handler as compliance_module

    return compliance_module


def get_receipt_store():
    """Compatibility wrapper for tests patching gdpr.get_receipt_store."""
    return _get_compliance_module().get_receipt_store()


def get_audit_store():
    """Compatibility wrapper for tests patching gdpr.get_audit_store."""
    return _get_compliance_module().get_audit_store()


def get_deletion_scheduler():
    """Compatibility wrapper for tests patching gdpr.get_deletion_scheduler."""
    return _get_compliance_module().get_deletion_scheduler()


def get_legal_hold_manager():
    """Compatibility wrapper for tests patching gdpr.get_legal_hold_manager."""
    return _get_compliance_module().get_legal_hold_manager()


def get_deletion_coordinator():
    """Compatibility wrapper for tests patching gdpr.get_deletion_coordinator."""
    return _get_compliance_module().get_deletion_coordinator()


class GDPRMixin:
    """Mixin providing GDPR-related handler methods."""

    @track_handler("compliance/gdpr-export", method="GET")
    @require_permission("compliance:gdpr")
    async def _gdpr_export(self, query_params: dict[str, str]) -> HandlerResult:
        """
        Export user data for GDPR compliance.

        Query params:
            user_id: User ID to export data for (required)
            format: Export format (json, csv) - default: json
            include: Comma-separated data types (all, decisions, preferences, activity)
        """
        user_id = query_params.get("user_id")
        if not user_id:
            return error_response("user_id is required", 400)

        output_format = query_params.get("format", "json")
        include = query_params.get("include", "all").split(",")

        now = datetime.now(timezone.utc)

        # Collect user data from various sources
        export_data: dict[str, Any] = {
            "export_id": f"gdpr-{user_id}-{now.strftime('%Y%m%d%H%M%S')}",
            "user_id": user_id,
            "requested_at": now.isoformat(),
            "data_categories": [],
        }

        if "all" in include or "decisions" in include:
            decisions = await self._get_user_decisions(user_id)
            export_data["decisions"] = decisions
            export_data["data_categories"].append("decisions")

        if "all" in include or "preferences" in include:
            preferences = await self._get_user_preferences(user_id)
            export_data["preferences"] = preferences
            export_data["data_categories"].append("preferences")

        if "all" in include or "activity" in include:
            activity = await self._get_user_activity(user_id)
            export_data["activity"] = activity
            export_data["data_categories"].append("activity")

        # Calculate checksum for integrity
        data_str = json.dumps(export_data, sort_keys=True, default=str)
        export_data["checksum"] = hashlib.sha256(data_str.encode()).hexdigest()

        if output_format == "csv":
            csv_content = self._render_gdpr_csv(export_data)
            return HandlerResult(
                status_code=200,
                content_type="text/csv",
                body=csv_content.encode("utf-8"),
                headers={
                    "Content-Disposition": f"attachment; filename=gdpr-export-{user_id}.csv",
                },
            )

        emit_handler_event("compliance", COMPLETED, {"action": "gdpr_export"}, user_id=user_id)
        return json_response(export_data)

    @track_handler("compliance/gdpr-rtbf", method="POST")
    @require_permission("compliance:gdpr")
    async def _right_to_be_forgotten(self, body: dict[str, Any]) -> HandlerResult:
        """
        Execute GDPR Right-to-be-Forgotten workflow (Article 17).

        Coordinates three operations:
        1. Revoke all user consents
        2. Generate final data export (for user to keep)
        3. Schedule data deletion after grace period

        Body:
            user_id: User ID requesting erasure (required)
            grace_period_days: Days before deletion (default: 30)
            include_export: Generate export before deletion (default: true)
            reason: Optional reason for the request

        Returns:
            Confirmation with export URL and deletion schedule
        """
        user_id = body.get("user_id")
        if not user_id:
            return error_response("user_id is required", 400)

        grace_period_days = int(body.get("grace_period_days", 30))
        include_export = body.get("include_export", True)
        reason = body.get("reason", "User request")

        now = datetime.now(timezone.utc)
        deletion_scheduled = now + timedelta(days=grace_period_days)
        request_id = f"rtbf-{user_id}-{now.strftime('%Y%m%d%H%M%S')}"

        result: dict[str, Any] = {
            "request_id": request_id,
            "user_id": user_id,
            "status": "scheduled",
            "requested_at": now.isoformat(),
            "reason": reason,
            "operations": [],
        }

        try:
            # Step 1: Revoke all consents
            consents_revoked = await self._revoke_all_consents(user_id)
            result["operations"].append(
                {
                    "operation": "revoke_consents",
                    "status": "completed",
                    "consents_revoked": consents_revoked,
                }
            )

            # Step 2: Generate data export (if requested)
            export_url = None
            if include_export:
                export_data = await self._generate_final_export(user_id)
                export_url = f"/api/v2/compliance/exports/{request_id}"
                result["operations"].append(
                    {
                        "operation": "generate_export",
                        "status": "completed",
                        "export_id": export_data.get("export_id"),
                        "data_categories": export_data.get("data_categories", []),
                    }
                )
                result["export_url"] = export_url

            # Step 3: Schedule deletion
            await self._schedule_deletion(
                user_id=user_id,
                request_id=request_id,
                scheduled_for=deletion_scheduled,
                reason=reason,
            )
            result["operations"].append(
                {
                    "operation": "schedule_deletion",
                    "status": "scheduled",
                    "scheduled_for": deletion_scheduled.isoformat(),
                }
            )

            # Record audit event
            await self._log_rtbf_request(
                request_id=request_id,
                user_id=user_id,
                reason=reason,
                deletion_scheduled=deletion_scheduled,
            )

            result["deletion_scheduled"] = deletion_scheduled.isoformat()
            result["grace_period_days"] = grace_period_days
            result["message"] = (
                f"Right-to-be-forgotten request processed. "
                f"Data will be permanently deleted on {deletion_scheduled.strftime('%Y-%m-%d')}. "
                f"{'Export available at: ' + export_url if export_url else 'No export requested.'}"
            )

            logger.info(
                "GDPR RTBF request processed: user=%s, request_id=%s, deletion=%s",
                user_id,
                request_id,
                deletion_scheduled.isoformat(),
            )

            return json_response(result)

        except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            logger.exception("RTBF request failed for user %s: %s", user_id, e)
            result["status"] = "failed"
            result["error"] = "RTBF request processing failed"
            return json_response(result, status=500)

    async def _revoke_all_consents(self, user_id: str) -> int:
        """Revoke all consents for a user."""
        try:
            from aragora.privacy.consent import get_consent_manager

            manager = get_consent_manager()
            revoked_count = manager.bulk_revoke_for_user(user_id)
            logger.info("Revoked %s consents for user %s", revoked_count, user_id)
            return revoked_count
        except (ImportError, AttributeError, RuntimeError) as e:
            logger.warning("Failed to revoke consents for %s: %s", user_id, e)
            return 0

    async def _generate_final_export(self, user_id: str) -> dict[str, Any]:
        """Generate final data export before deletion."""
        # Use the existing GDPR export logic
        data_categories: list[str] = []
        export_data: dict[str, Any] = {
            "export_id": f"final-{user_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "user_id": user_id,
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "data_categories": data_categories,
        }

        # Collect all data categories
        decisions = await self._get_user_decisions(user_id)
        export_data["decisions"] = decisions
        data_categories.append("decisions")

        preferences = await self._get_user_preferences(user_id)
        export_data["preferences"] = preferences
        data_categories.append("preferences")

        activity = await self._get_user_activity(user_id)
        export_data["activity"] = activity
        data_categories.append("activity")

        # Add consent records
        try:
            from aragora.privacy.consent import get_consent_manager

            manager = get_consent_manager()
            consent_export = manager.export_consent_data(user_id)
            export_data["consent_records"] = consent_export.to_dict()
            data_categories.append("consent_records")
        except (ImportError, AttributeError, RuntimeError) as e:
            logger.warning("Failed to export consent data: %s", e)

        # Calculate checksum
        data_str = json.dumps(export_data, sort_keys=True, default=str)
        export_data["checksum"] = hashlib.sha256(data_str.encode()).hexdigest()

        return export_data

    async def _schedule_deletion(
        self,
        user_id: str,
        request_id: str,
        scheduled_for: datetime,
        reason: str,
    ) -> dict[str, Any]:
        """
        Schedule data deletion for user using GDPRDeletionScheduler.

        Uses the actual deletion infrastructure that will execute
        the deletion after the grace period expires.
        """
        # Calculate grace period from scheduled_for
        now = datetime.now(timezone.utc)
        grace_period_days = max(0, (scheduled_for - now).days)

        try:
            scheduler = get_deletion_scheduler()

            # Check for legal holds first
            hold_manager = get_legal_hold_manager()
            if hold_manager.is_user_on_hold(user_id):
                active_holds = scheduler.store.get_active_holds_for_user(user_id)
                hold = active_holds[0] if active_holds else None
                raise ValueError(
                    f"Cannot schedule deletion: User is under legal hold "
                    f"(hold_id={hold.hold_id if hold else 'unknown'}, "
                    f"reason={hold.reason if hold else 'unknown'})"
                )

            # Schedule the deletion
            deletion_request = scheduler.schedule_deletion(
                user_id=user_id,
                grace_period_days=grace_period_days,
                reason=reason,
                metadata={
                    "rtbf_request_id": request_id,
                    "source": "compliance_handler",
                },
            )

            deletion_record = {
                "request_id": deletion_request.request_id,
                "rtbf_request_id": request_id,
                "user_id": user_id,
                "scheduled_for": deletion_request.scheduled_for.isoformat(),
                "reason": reason,
                "status": deletion_request.status.value,
                "created_at": deletion_request.created_at.isoformat(),
            }

            # Log for audit trail
            try:
                store = get_audit_store()
                store.log_event(
                    action="gdpr_deletion_scheduled",
                    resource_type="user",
                    resource_id=user_id,
                    metadata=deletion_record,
                )
            except (RuntimeError, OSError, ValueError) as e:
                logger.warning("Failed to log deletion schedule: %s", e)

            return deletion_record

        except ValueError:
            # Re-raise legal hold errors
            raise
        except (RuntimeError, OSError, KeyError, TypeError, AttributeError) as e:
            logger.error("Failed to schedule deletion: %s", e)
            # Fall back to basic audit logging if scheduler fails
            deletion_record = {
                "request_id": request_id,
                "user_id": user_id,
                "scheduled_for": scheduled_for.isoformat(),
                "reason": reason,
                "status": "scheduled_fallback",
                "error": "Scheduler unavailable, using fallback",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            try:
                store = get_audit_store()
                store.log_event(
                    action="gdpr_deletion_scheduled_fallback",
                    resource_type="user",
                    resource_id=user_id,
                    metadata=deletion_record,
                )
            except (RuntimeError, OSError, ValueError) as log_err:
                logger.warning("Failed to log deletion schedule: %s", log_err)

            return deletion_record

    async def _log_rtbf_request(
        self,
        request_id: str,
        user_id: str,
        reason: str,
        deletion_scheduled: datetime,
    ) -> None:
        """Log the right-to-be-forgotten request for compliance."""
        try:
            store = get_audit_store()
            store.log_event(
                action="gdpr_rtbf_request",
                resource_type="user",
                resource_id=user_id,
                metadata={
                    "request_id": request_id,
                    "reason": reason,
                    "deletion_scheduled": deletion_scheduled.isoformat(),
                    "operations": [
                        "revoke_consents",
                        "generate_export",
                        "schedule_deletion",
                    ],
                },
            )
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning("Failed to log RTBF request: %s", e)

    # =========================================================================
    # Deletion Management Endpoints
    # =========================================================================

    @require_permission("compliance:gdpr")
    async def _list_deletions(self, query_params: dict[str, str]) -> HandlerResult:
        """
        List scheduled deletion requests.

        Query params:
            status: Filter by status (pending, completed, failed, cancelled, held)
            limit: Max results (default 50, max 200)
        """
        status_filter = query_params.get("status")
        limit = min(int(query_params.get("limit", "50")), 200)

        try:
            from aragora.privacy.deletion import DeletionStatus

            scheduler = get_deletion_scheduler()
            status = DeletionStatus(status_filter) if status_filter else None
            requests = scheduler.store.get_all_requests(status=status, limit=limit)

            return json_response(
                {
                    "deletions": [r.to_dict() for r in requests],
                    "count": len(requests),
                    "filters": {"status": status_filter, "limit": limit},
                }
            )

        except (ImportError, ValueError, KeyError, RuntimeError) as e:
            logger.exception("Error listing deletions: %s", e)
            return error_response("Failed to list deletions", 500)

    @require_permission("compliance:gdpr")
    async def _get_deletion(self, request_id: str) -> HandlerResult:
        """
        Get a specific deletion request.

        Path params:
            request_id: The deletion request ID
        """
        try:
            scheduler = get_deletion_scheduler()
            request = scheduler.store.get_request(request_id)

            if not request:
                return error_response("Deletion request not found", 404)

            return json_response({"deletion": request.to_dict()})

        except (KeyError, RuntimeError, ValueError) as e:
            logger.exception("Error getting deletion: %s", e)
            return error_response("Failed to retrieve deletion", 500)

    @require_permission("compliance:gdpr")
    async def _cancel_deletion(
        self,
        request_id: str,
        body: dict[str, Any],
    ) -> HandlerResult:
        """
        Cancel a pending deletion request.

        Path params:
            request_id: The deletion request ID to cancel

        Body:
            reason: Reason for cancellation (optional)
        """
        reason = body.get("reason", "Administrator cancelled")

        try:
            scheduler = get_deletion_scheduler()
            cancelled = scheduler.cancel_deletion(request_id, reason)

            if not cancelled:
                return error_response("Deletion request not found", 404)

            # Log the cancellation
            try:
                store = get_audit_store()
                store.log_event(
                    action="gdpr_deletion_cancelled",
                    resource_type="deletion_request",
                    resource_id=request_id,
                    metadata={
                        "user_id": cancelled.user_id,
                        "reason": reason,
                        "cancelled_at": cancelled.cancelled_at.isoformat()
                        if cancelled.cancelled_at
                        else None,
                    },
                )
            except (RuntimeError, OSError, ValueError) as log_err:
                logger.warning("Failed to log deletion cancellation: %s", log_err)

            return json_response(
                {
                    "message": "Deletion cancelled successfully",
                    "deletion": cancelled.to_dict(),
                }
            )

        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request", 400)
        except (RuntimeError, OSError, KeyError, TypeError) as e:
            logger.exception("Error cancelling deletion: %s", e)
            return error_response("Deletion cancellation failed", 500)

    # =========================================================================
    # Coordinated Deletion Endpoints (Backup-Aware GDPR Compliance)
    # =========================================================================

    @track_handler("compliance/coordinated-deletion", method="POST")
    @require_permission("compliance:gdpr")
    async def _coordinated_deletion(self, body: dict[str, Any]) -> HandlerResult:
        """
        Execute coordinated deletion across all systems including backups.

        This is the GDPR-compliant deletion that ensures user data is removed
        from both primary storage AND backup systems.

        Body:
            user_id: User ID to delete (required)
            reason: Reason for deletion (required)
            delete_from_backups: Whether to purge from backups (default: true)
            dry_run: If true, simulate without actual deletion (default: false)

        Returns:
            Deletion report showing what was deleted from each system
        """
        user_id = body.get("user_id")
        if not user_id:
            return error_response("user_id is required", 400)

        reason = body.get("reason")
        if not reason:
            return error_response("reason is required", 400)

        delete_from_backups = body.get("delete_from_backups", True)
        dry_run = body.get("dry_run", False)

        try:
            coordinator = get_deletion_coordinator()

            # Check for legal holds first
            hold_manager = get_legal_hold_manager()
            if hold_manager.is_user_on_hold(user_id):
                active_holds = hold_manager.get_active_holds()
                user_holds = [h for h in active_holds if user_id in h.user_ids]
                return error_response(
                    f"Cannot delete: User is under legal hold "
                    f"(hold_id={user_holds[0].hold_id if user_holds else 'unknown'})",
                    409,
                )

            # Execute coordinated deletion
            report = await coordinator.execute_coordinated_deletion(
                user_id=user_id,
                reason=reason,
                delete_from_backups=delete_from_backups,
                dry_run=dry_run,
            )

            # Log the coordinated deletion
            try:
                store = get_audit_store()
                store.log_event(
                    action="gdpr_coordinated_deletion",
                    resource_type="user",
                    resource_id=user_id,
                    metadata={
                        "reason": reason,
                        "dry_run": dry_run,
                        "delete_from_backups": delete_from_backups,
                        "success": report.success,
                        "systems_deleted": [s.value for s in report.deleted_from],
                        "backup_purge_results": report.backup_purge_results,
                    },
                )
            except (RuntimeError, OSError, ValueError) as log_err:
                logger.warning("Failed to log coordinated deletion: %s", log_err)

            return json_response(
                {
                    "message": "Coordinated deletion completed"
                    if not dry_run
                    else "Dry run completed",
                    "report": report.to_dict(),
                }
            )

        except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            logger.exception("Error executing coordinated deletion: %s", e)
            return error_response("Deletion execution failed", 500)

    @require_permission("compliance:gdpr")
    async def _execute_pending_deletions(self, body: dict[str, Any]) -> HandlerResult:
        """
        Execute all pending deletions that have passed their grace period.

        This endpoint is designed to be called by a background job or cron
        to process scheduled deletions.

        Body:
            include_backups: Whether to also purge from backups (default: true)
            limit: Maximum number of deletions to process (default: 100)

        Returns:
            Summary of processed deletions
        """
        include_backups = body.get("include_backups", True)
        limit = min(int(body.get("limit", 100)), 500)

        try:
            coordinator = get_deletion_coordinator()
            results = await coordinator.process_pending_deletions(
                include_backups=include_backups,
                limit=limit,
            )

            successful = [r for r in results if r.success]
            failed = [r for r in results if not r.success]

            # Log batch processing
            try:
                store = get_audit_store()
                store.log_event(
                    action="gdpr_batch_deletion_processed",
                    resource_type="system",
                    resource_id="deletion_coordinator",
                    metadata={
                        "total_processed": len(results),
                        "successful": len(successful),
                        "failed": len(failed),
                        "include_backups": include_backups,
                    },
                )
            except (RuntimeError, OSError, ValueError) as log_err:
                logger.warning("Failed to log batch deletion: %s", log_err)

            return json_response(
                {
                    "message": f"Processed {len(results)} pending deletions",
                    "summary": {
                        "total_processed": len(results),
                        "successful": len(successful),
                        "failed": len(failed),
                    },
                    "results": [r.to_dict() for r in results],
                }
            )

        except (RuntimeError, ValueError, OSError) as e:
            logger.exception("Error processing pending deletions: %s", e)
            return error_response("Deletion processing failed", 500)

    @require_permission("compliance:gdpr")
    async def _list_backup_exclusions(self, query_params: dict[str, str]) -> HandlerResult:
        """
        List users excluded from backup retention.

        These are users whose data has been deleted and should not be
        restored from backups.

        Query params:
            limit: Maximum results (default: 100)
        """
        limit = min(int(query_params.get("limit", "100")), 500)

        try:
            coordinator = get_deletion_coordinator()
            exclusions = coordinator.get_backup_exclusion_list(limit=limit)

            return json_response(
                {
                    "exclusions": exclusions,
                    "count": len(exclusions),
                }
            )

        except (RuntimeError, ValueError, KeyError) as e:
            logger.exception("Error listing backup exclusions: %s", e)
            return error_response("Failed to list exclusions", 500)

    @require_permission("compliance:gdpr")
    async def _add_backup_exclusion(self, body: dict[str, Any]) -> HandlerResult:
        """
        Add a user to the backup exclusion list.

        This prevents the user's data from being restored in future
        backup restoration operations.

        Body:
            user_id: User ID to exclude (required)
            reason: Reason for exclusion (required)
        """
        user_id = body.get("user_id")
        if not user_id:
            return error_response("user_id is required", 400)

        reason = body.get("reason")
        if not reason:
            return error_response("reason is required", 400)

        try:
            coordinator = get_deletion_coordinator()
            coordinator.add_to_backup_exclusion_list(user_id, reason)

            # Log the exclusion
            try:
                store = get_audit_store()
                store.log_event(
                    action="gdpr_backup_exclusion_added",
                    resource_type="user",
                    resource_id=user_id,
                    metadata={"reason": reason},
                )
            except (RuntimeError, OSError, ValueError) as log_err:
                logger.warning("Failed to log backup exclusion: %s", log_err)

            return json_response(
                {
                    "message": "User added to backup exclusion list",
                    "user_id": user_id,
                    "reason": reason,
                },
                status=201,
            )

        except (RuntimeError, ValueError, KeyError) as e:
            logger.exception("Error adding backup exclusion: %s", e)
            return error_response("Exclusion addition failed", 500)

    # =========================================================================
    # Helper methods for user data retrieval
    # =========================================================================

    async def _get_user_decisions(self, user_id: str) -> list[dict[str, Any]]:
        """Get decisions associated with user from receipt store."""
        try:
            store = get_receipt_store()
            receipts = store.list(limit=100, sort_by="created_at", order="desc")
            # Filter receipts that may be associated with this user
            # Note: Full user association would require tenant/user metadata
            return [
                {
                    "receipt_id": r.receipt_id,
                    "gauntlet_id": r.gauntlet_id,
                    "verdict": r.verdict,
                    "confidence": r.confidence,
                    "created_at": r.created_at,
                    "risk_level": r.risk_level,
                }
                for r in receipts[:50]  # Limit for GDPR export
            ]
        except (RuntimeError, AttributeError, KeyError) as e:
            logger.warning("Failed to fetch user decisions: %s", e)
            return []

    async def _get_user_preferences(self, user_id: str) -> dict[str, Any]:
        """Get user preferences."""
        return {"notification_settings": {}, "privacy_settings": {}}

    async def _get_user_activity(self, user_id: str) -> list[dict[str, Any]]:
        """Get user activity logs from audit store."""
        try:
            store = get_audit_store()
            # Get recent activity for the user
            activity = store.get_recent_activity(user_id=user_id, hours=720, limit=100)
            return activity
        except (RuntimeError, AttributeError, KeyError) as e:
            logger.warning("Failed to fetch user activity: %s", e)
            return []

    def _render_gdpr_csv(self, export_data: dict[str, Any]) -> str:
        """Render GDPR export as CSV."""
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(["GDPR Data Export"])
        writer.writerow(["User ID", export_data["user_id"]])
        writer.writerow(["Export ID", export_data["export_id"]])
        writer.writerow(["Requested At", export_data["requested_at"]])
        writer.writerow([])

        for category in export_data.get("data_categories", []):
            writer.writerow([f"=== {category.upper()} ==="])
            data = export_data.get(category, [])
            if isinstance(data, list):
                for item in data:
                    writer.writerow([str(item)])
            elif isinstance(data, dict):
                for key, value in data.items():
                    writer.writerow([key, str(value)])
            writer.writerow([])

        writer.writerow(["Checksum", export_data.get("checksum", "")])

        return output.getvalue()
