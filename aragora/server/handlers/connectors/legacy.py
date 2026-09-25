"""
HTTP API Handlers for Enterprise Connectors.

Provides REST API for managing enterprise data source connectors,
sync operations, and scheduler configuration.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any

from aragora.audit.unified import audit_admin, audit_data
from aragora.server.handlers.utils.responses import error_dict

from aragora.connectors.enterprise import (
    SyncScheduler,
    SyncSchedule,
    GitHubEnterpriseConnector,
    S3Connector,
    PostgreSQLConnector,
    MongoDBConnector,
    FHIRConnector,
)
from aragora.connectors.enterprise.sync.scheduler import SyncStatus

if TYPE_CHECKING:
    from aragora.rbac import AuthorizationContext as AuthorizationContextType
else:
    AuthorizationContextType = None

logger = logging.getLogger(__name__)

# RBAC imports (optional - graceful degradation if not available)
try:
    from aragora.rbac import (
        check_permission,
        PermissionDeniedError,
    )
    from aragora.server.handlers.utils.decorators import require_permission

    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False
    check_permission = None  # type: ignore[assignment]
    PermissionDeniedError = Exception  # type: ignore[misc,assignment]

from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed


def _record_rbac_check(*args: Any, **kwargs: Any) -> None:
    """No-op fallback for when metrics module is not available."""
    pass


# Metrics imports (optional)
try:
    from aragora.observability.metrics import record_rbac_check
except ImportError:
    record_rbac_check = _record_rbac_check


def _check_permission(
    auth_context: Any | None, permission_key: str, resource_id: str | None = None
) -> dict[str, Any] | None:
    """
    Check if the authorization context has the required permission.

    Args:
        auth_context: Optional AuthorizationContext
        permission_key: Permission like "connectors:read" or "connectors:create"
        resource_id: Optional resource ID for resource-specific permissions

    Returns:
        None if allowed, error dict if denied
    """
    rbac_enabled = RBAC_AVAILABLE
    perm_checker = check_permission
    perm_error_type = PermissionDeniedError

    if not rbac_enabled:
        if rbac_fail_closed():
            return error_dict(
                "Service unavailable: access control module not loaded",
                code="SERVICE_UNAVAILABLE",
                status=503,
            )
        return None

    if auth_context is None:
        return None

    try:
        if perm_checker is None:
            return None
        decision = perm_checker(auth_context, permission_key, resource_id)
        if not decision.allowed:
            logger.warning(
                "Permission denied: %s for user %s: %s",
                permission_key,
                auth_context.user_id,
                decision.reason,
            )
            record_rbac_check(permission_key, granted=False)
            return error_dict("Permission denied", code="FORBIDDEN", status=403)
        record_rbac_check(permission_key, granted=True)
    except perm_error_type as e:  # type: ignore[misc]
        logger.warning(
            "Permission denied: %s for user %s: %s", permission_key, auth_context.user_id, e
        )
        record_rbac_check(permission_key, granted=False)
        return error_dict("Permission denied", code="FORBIDDEN", status=403)

    return None


def _resolve_tenant_id(
    auth_context: Any | None,
    fallback_tenant_id: str = "default",
) -> str:
    """
    Resolve tenant_id from auth context, falling back to provided value.

    SECURITY: When RBAC is available and auth_context has an org_id,
    that org_id takes precedence over any user-supplied tenant_id
    to prevent cross-tenant data access.

    Args:
        auth_context: Optional AuthorizationContext with org_id
        fallback_tenant_id: Value to use if no auth context org_id

    Returns:
        Tenant ID extracted from auth context, or fallback
    """
    # The package imports this module, so it is already in sys.modules here;
    # reading it from there honours package-level RBAC_AVAILABLE patches
    # without importing the package back (a mutual import cycle).
    connectors_module = sys.modules.get("aragora.server.handlers.connectors")

    rbac_enabled = RBAC_AVAILABLE
    if connectors_module is not None:
        rbac_enabled = getattr(connectors_module, "RBAC_AVAILABLE", RBAC_AVAILABLE)

    if rbac_enabled and auth_context is not None:
        if (
            auth_context != "unauthenticated"
            and hasattr(auth_context, "org_id")
            and auth_context.org_id
        ):
            return auth_context.org_id
    return fallback_tenant_id


# Global scheduler instance (initialized on first use)
_scheduler: SyncScheduler | None = None


def get_scheduler() -> SyncScheduler:
    """Get or create the global sync scheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = SyncScheduler(max_concurrent_syncs=5)
    return _scheduler


# =============================================================================
# Connector Management Handlers
# =============================================================================


async def handle_list_connectors(
    tenant_id: str = "default",
    auth_context: Any | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """
    List all registered connectors.

    GET /api/connectors?limit=50&offset=0

    Args:
        tenant_id: Tenant ID for isolation
        auth_context: Authentication context for RBAC
        limit: Max results (default: 50, max: 500)
        offset: Pagination offset (default: 0)
    """
    # Check RBAC permission
    perm_error = _check_permission(auth_context, "connectors:read")
    if perm_error:
        return perm_error

    # SECURITY: Resolve tenant_id from auth context to prevent cross-tenant access
    tenant_id = _resolve_tenant_id(auth_context, tenant_id)

    # Bound pagination params
    limit = max(1, min(500, limit))
    offset = max(0, offset)

    scheduler = get_scheduler()
    jobs = scheduler.list_jobs(tenant_id=tenant_id)

    total = len(jobs)
    paginated = jobs[offset : offset + limit]

    return {
        "connectors": [
            {
                "id": job.connector_id,
                "job_id": job.id,
                "tenant_id": job.tenant_id,
                "schedule": job.schedule.to_dict(),
                "last_run": job.last_run.isoformat() if job.last_run else None,
                "next_run": job.next_run.isoformat() if job.next_run else None,
                "consecutive_failures": job.consecutive_failures,
            }
            for job in paginated
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def handle_get_connector(
    connector_id: str,
    tenant_id: str = "default",
    auth_context: Any | None = None,
) -> dict[str, Any] | None:
    """
    Get connector details.

    GET /api/connectors/:connector_id

    Requires connectors.read permission.
    """
    # Check RBAC permission
    perm_error = _check_permission(auth_context, "connectors:read", connector_id)
    if perm_error:
        return perm_error

    # SECURITY: Resolve tenant_id from auth context to prevent cross-tenant access
    tenant_id = _resolve_tenant_id(auth_context, tenant_id)

    scheduler = get_scheduler()
    job_id = f"{tenant_id}:{connector_id}"
    job = scheduler.get_job(job_id)

    if not job:
        return None

    return {
        "id": job.connector_id,
        "job_id": job.id,
        "tenant_id": job.tenant_id,
        "schedule": job.schedule.to_dict(),
        "last_run": job.last_run.isoformat() if job.last_run else None,
        "next_run": job.next_run.isoformat() if job.next_run else None,
        "consecutive_failures": job.consecutive_failures,
        "is_running": job.current_run_id is not None,
    }


async def handle_create_connector(
    connector_type: str,
    config: dict[str, Any],
    schedule: dict[str, Any] | None = None,
    tenant_id: str = "default",
    auth_context: Any | None = None,
) -> dict[str, Any]:
    """
    Create and register a new connector.

    POST /api/connectors
    {
        "type": "github" | "s3" | "postgres" | "mongodb" | "fhir",
        "config": { ... connector-specific config ... },
        "schedule": { ... optional schedule config ... }
    }
    """
    # Check RBAC permission - creating connectors involves sensitive credentials
    perm_error = _check_permission(auth_context, "connectors:create")
    if perm_error:
        return perm_error

    # SECURITY: Resolve tenant_id from auth context to prevent cross-tenant access
    tenant_id = _resolve_tenant_id(auth_context, tenant_id)

    scheduler = get_scheduler()

    # Create connector based on type
    connector = _create_connector(connector_type, config)

    # Create schedule
    sync_schedule = SyncSchedule.from_dict(schedule) if schedule else SyncSchedule()

    # Register with scheduler
    job = scheduler.register_connector(
        connector,
        schedule=sync_schedule,
        tenant_id=tenant_id,
    )

    logger.info("Created connector: %s (%s)", connector.connector_id, connector_type)
    user_id = auth_context.user_id if auth_context else "system"
    audit_data(
        user_id=user_id,
        resource_type="connector",
        resource_id=connector.connector_id,
        action="create",
        connector_type=connector_type,
        tenant_id=tenant_id,
    )

    return {
        "id": job.connector_id,
        "job_id": job.id,
        "type": connector_type,
        "status": "registered",
    }


async def handle_update_connector(
    connector_id: str,
    updates: dict[str, Any],
    tenant_id: str = "default",
    auth_context: Any | None = None,
) -> dict[str, Any] | None:
    """
    Update connector configuration.

    PATCH /api/connectors/:connector_id
    {
        "schedule": { ... updated schedule ... }
    }
    """
    # Check RBAC permission
    perm_error = _check_permission(auth_context, "connectors:update", connector_id)
    if perm_error:
        return perm_error

    # SECURITY: Resolve tenant_id from auth context to prevent cross-tenant access
    tenant_id = _resolve_tenant_id(auth_context, tenant_id)

    scheduler = get_scheduler()
    job_id = f"{tenant_id}:{connector_id}"
    job = scheduler.get_job(job_id)

    if not job:
        return None

    # Update schedule if provided
    if "schedule" in updates:
        job.schedule = SyncSchedule.from_dict(updates["schedule"])
        job._calculate_next_run()

    user_id = auth_context.user_id if auth_context else "system"
    audit_data(
        user_id=user_id,
        resource_type="connector",
        resource_id=connector_id,
        action="update",
        changes=list(updates.keys()),
        tenant_id=tenant_id,
    )

    return {
        "id": job.connector_id,
        "status": "updated",
        "schedule": job.schedule.to_dict(),
    }


@require_permission("connectors:delete")
async def handle_delete_connector(
    connector_id: str,
    tenant_id: str = "default",
    auth_context: Any | None = None,
) -> Any:
    """
    Delete a connector.

    DELETE /api/connectors/:connector_id
    """
    # Check RBAC permission
    perm_error = _check_permission(auth_context, "connectors:delete", connector_id)
    if perm_error:
        return perm_error

    # SECURITY: Resolve tenant_id from auth context to prevent cross-tenant access
    tenant_id = _resolve_tenant_id(auth_context, tenant_id)

    scheduler = get_scheduler()
    scheduler.unregister_connector(connector_id, tenant_id)

    user_id = auth_context.user_id if auth_context else "system"
    audit_data(
        user_id=user_id,
        resource_type="connector",
        resource_id=connector_id,
        action="delete",
        tenant_id=tenant_id,
    )
    return True


def _create_connector(connector_type: str, config: dict[str, Any]):
    """Create a connector instance based on type."""
    if connector_type == "github":
        # GitHubEnterpriseConnector expects repo in "owner/repo" format
        owner = config.get("owner", "")
        repo = config.get("repo", "")
        # If repo already contains owner (owner/repo format), use as-is
        if "/" in repo:
            full_repo = repo
        elif owner and repo:
            full_repo = f"{owner}/{repo}"
        else:
            full_repo = repo or owner  # Fallback

        return GitHubEnterpriseConnector(
            repo=full_repo,
            token=config.get("token"),
            include_prs=config.get("sync_prs", True),
            include_issues=config.get("sync_issues", True),
        )

    elif connector_type == "s3":
        return S3Connector(
            bucket=config["bucket"],
            prefix=config.get("prefix", ""),
            endpoint_url=config.get("endpoint_url"),
            region=config.get("region", "us-east-1"),
        )

    elif connector_type == "postgres":
        return PostgreSQLConnector(
            host=config.get("host", "localhost"),
            port=config.get("port", 5432),
            database=config["database"],
            schema=config.get("schema", "public"),
            tables=config.get("tables"),
            timestamp_column=config.get("timestamp_column"),
        )

    elif connector_type == "mongodb":
        return MongoDBConnector(
            host=config.get("host", "localhost"),
            port=config.get("port", 27017),
            database=config["database"],
            collections=config.get("collections"),
            connection_string=config.get("connection_string"),
        )

    elif connector_type == "fhir":
        return FHIRConnector(
            base_url=config["base_url"],
            organization_id=config["organization_id"],
            client_id=config.get("client_id"),
            enable_phi_redaction=config.get("enable_phi_redaction", True),
        )

    else:
        raise ValueError(f"Unknown connector type: {connector_type}")


# =============================================================================
# Sync Operation Handlers
# =============================================================================


async def handle_trigger_sync(
    connector_id: str,
    full_sync: bool = False,
    tenant_id: str = "default",
    auth_context: Any | None = None,
) -> dict[str, Any] | None:
    """
    Trigger a sync operation.

    POST /api/connectors/:connector_id/sync
    {
        "full_sync": false
    }
    """
    # Check RBAC permission - triggering sync is an execute operation
    perm_error = _check_permission(auth_context, "connectors:execute", connector_id)
    if perm_error:
        return perm_error

    # SECURITY: Resolve tenant_id from auth context to prevent cross-tenant access
    tenant_id = _resolve_tenant_id(auth_context, tenant_id)

    scheduler = get_scheduler()

    run_id = await scheduler.trigger_sync(
        connector_id,
        tenant_id=tenant_id,
        full_sync=full_sync,
    )

    if not run_id:
        return None

    user_id = auth_context.user_id if auth_context else "system"
    audit_data(
        user_id=user_id,
        resource_type="connector_sync",
        resource_id=run_id,
        action="execute",
        connector_id=connector_id,
        full_sync=full_sync,
        tenant_id=tenant_id,
    )

    return {
        "run_id": run_id,
        "connector_id": connector_id,
        "status": "started",
        "full_sync": full_sync,
    }


async def handle_get_sync_status(
    connector_id: str,
    tenant_id: str = "default",
    auth_context: Any | None = None,
) -> dict[str, Any] | None:
    """
    Get current sync status.

    GET /api/connectors/:connector_id/sync/status

    Requires connectors.read permission.
    """
    # Check RBAC permission
    perm_error = _check_permission(auth_context, "connectors:read", connector_id)
    if perm_error:
        return perm_error

    # SECURITY: Resolve tenant_id from auth context to prevent cross-tenant access
    tenant_id = _resolve_tenant_id(auth_context, tenant_id)

    scheduler = get_scheduler()
    job_id = f"{tenant_id}:{connector_id}"
    job = scheduler.get_job(job_id)

    if not job:
        return None

    return {
        "connector_id": connector_id,
        "is_running": job.current_run_id is not None,
        "current_run_id": job.current_run_id,
        "last_run": job.last_run.isoformat() if job.last_run else None,
        "next_run": job.next_run.isoformat() if job.next_run else None,
        "consecutive_failures": job.consecutive_failures,
    }


async def handle_get_sync_history(
    connector_id: str | None = None,
    tenant_id: str = "default",
    status: str | None = None,
    limit: int = 50,
    auth_context: Any | None = None,
) -> dict[str, Any]:
    """
    Get sync history.

    GET /api/connectors/sync/history
    GET /api/connectors/:connector_id/sync/history

    Requires connectors.read permission.
    """
    # Check RBAC permission
    perm_error = _check_permission(auth_context, "connectors:read", connector_id)
    if perm_error:
        return perm_error

    # SECURITY: Resolve tenant_id from auth context to prevent cross-tenant access
    tenant_id = _resolve_tenant_id(auth_context, tenant_id)

    scheduler = get_scheduler()

    job_id = f"{tenant_id}:{connector_id}" if connector_id else None
    sync_status = SyncStatus(status) if status else None

    history = scheduler.get_history(
        job_id=job_id,
        tenant_id=tenant_id,
        status=sync_status,
        limit=limit,
    )

    return {
        "history": [h.to_dict() for h in history],
        "total": len(history),
    }


# =============================================================================
# Webhook Handlers
# =============================================================================


async def handle_webhook(
    connector_id: str,
    payload: dict[str, Any],
    tenant_id: str = "default",
    auth_context: Any | None = None,
) -> dict[str, Any]:
    """
    Handle incoming webhook for a connector.

    POST /api/connectors/:connector_id/webhook
    """
    # Check RBAC permission
    perm_error = _check_permission(auth_context, "connectors:execute", connector_id)
    if perm_error:
        return perm_error

    # SECURITY: Resolve tenant_id from auth context to prevent cross-tenant access
    tenant_id = _resolve_tenant_id(auth_context, tenant_id)

    scheduler = get_scheduler()

    handled = await scheduler.handle_webhook(
        connector_id,
        payload,
        tenant_id=tenant_id,
    )

    return {
        "handled": handled,
        "connector_id": connector_id,
    }


# =============================================================================
# Scheduler Handlers
# =============================================================================


async def handle_start_scheduler(
    auth_context: Any | None = None,
) -> dict[str, Any]:
    """
    Start the sync scheduler.

    POST /api/connectors/scheduler/start

    Requires connectors.execute permission.
    """
    # Check RBAC permission - starting scheduler is an admin operation
    perm_error = _check_permission(auth_context, "connectors:execute")
    if perm_error:
        return perm_error

    scheduler = get_scheduler()
    await scheduler.start()

    user_id = auth_context.user_id if auth_context else "system"
    audit_admin(
        admin_id=user_id,
        action="start_scheduler",
        target_type="scheduler",
        target_id="sync_scheduler",
    )

    return {
        "status": "started",
    }


async def handle_stop_scheduler(
    auth_context: Any | None = None,
) -> dict[str, Any]:
    """
    Stop the sync scheduler.

    POST /api/connectors/scheduler/stop

    Requires connectors.execute permission.
    """
    # Check RBAC permission - stopping scheduler is an admin operation
    perm_error = _check_permission(auth_context, "connectors:execute")
    if perm_error:
        return perm_error

    scheduler = get_scheduler()
    await scheduler.stop()

    user_id = auth_context.user_id if auth_context else "system"
    audit_admin(
        admin_id=user_id,
        action="stop_scheduler",
        target_type="scheduler",
        target_id="sync_scheduler",
    )

    return {
        "status": "stopped",
    }


async def handle_get_scheduler_stats(
    tenant_id: str | None = None,
    auth_context: Any | None = None,
) -> dict[str, Any]:
    """
    Get scheduler statistics.

    GET /api/connectors/scheduler/stats

    Requires connectors.read permission.
    """
    # Check RBAC permission
    perm_error = _check_permission(auth_context, "connectors:read")
    if perm_error:
        return perm_error

    scheduler = get_scheduler()
    return scheduler.get_stats(tenant_id=tenant_id)


# =============================================================================
# Template Handlers
# =============================================================================


async def handle_list_workflow_templates(
    category: str | None = None,
    auth_context: Any | None = None,
) -> dict[str, Any]:
    """
    List available workflow templates.

    GET /api/workflows/templates
    GET /api/workflows/templates?category=legal
    """
    # Check RBAC permission
    perm_error = _check_permission(auth_context, "workflows:read")
    if perm_error:
        return perm_error

    from aragora.workflow.templates import list_templates

    templates = list_templates(category=category)

    return {
        "templates": templates,
        "total": len(templates),
        "categories": list(set(t["category"] for t in templates)),
    }


async def handle_get_workflow_template(
    template_id: str,
    auth_context: Any | None = None,
) -> dict[str, Any] | None:
    """
    Get a specific workflow template.

    GET /api/workflows/templates/:template_id
    """
    # Check RBAC permission
    perm_error = _check_permission(auth_context, "workflows:read", template_id)
    if perm_error:
        return perm_error

    from aragora.workflow.templates import get_template

    template = get_template(template_id)

    if not template:
        return None

    return {
        "id": template_id,
        "template": template,
    }


# =============================================================================
# MongoDB Aggregation Handlers
# =============================================================================


@require_permission("connectors:read")
async def handle_mongodb_aggregate(
    connector_id: str,
    collection: str,
    pipeline: list[dict[str, Any]],
    tenant_id: str = "default",
    limit: int = 1000,
    explain: bool = False,
    auth_context: Any | None = None,
) -> dict[str, Any]:
    """
    Execute MongoDB aggregation pipeline.

    POST /api/connectors/:connector_id/aggregate

    Requires connectors.execute permission.

    {
        "collection": "users",
        "pipeline": [
            {"$match": {"status": "active"}},
            {"$group": {"_id": "$department", "count": {"$sum": 1}}}
        ],
        "limit": 1000,
        "explain": false
    }

    The pipeline supports all MongoDB aggregation stages:
    - $match, $group, $sort, $limit, $skip
    - $project, $unwind, $lookup, $facet
    - $graphLookup, $bucket, $bucketAuto
    - $addFields, $replaceRoot, $merge
    """
    # Check RBAC permission - executing aggregation is a data access operation
    perm_error = _check_permission(auth_context, "connectors:execute", connector_id)
    if perm_error:
        return perm_error

    # SECURITY: Resolve tenant_id from auth context to prevent cross-tenant access
    tenant_id = _resolve_tenant_id(auth_context, tenant_id)

    from aragora.connectors.enterprise.registry import get_connector

    connector = get_connector(connector_id, tenant_id=tenant_id)
    if not connector:
        raise ValueError(f"Connector not found: {connector_id}")

    if not isinstance(connector, MongoDBConnector):
        raise ValueError(f"Connector {connector_id} is not a MongoDB connector")

    # Validate pipeline structure
    if not isinstance(pipeline, list):
        raise ValueError("Pipeline must be a list of stage documents")

    for i, stage in enumerate(pipeline):
        if not isinstance(stage, dict):
            raise ValueError(f"Pipeline stage {i} must be a document")
        if len(stage) == 0:
            raise ValueError(f"Pipeline stage {i} is empty")

    # Add limit stage if not present to prevent unbounded results
    has_limit = any("$limit" in stage for stage in pipeline)
    if not has_limit and limit > 0:
        pipeline = pipeline + [{"$limit": limit}]

    if explain:
        # Return explain plan instead of results
        await connector._get_client()
        if connector._db is None:
            raise RuntimeError("Database not initialized")

        coll = connector._db[collection]
        explain_result = await coll.aggregate(pipeline).explain()
        return {
            "connector_id": connector_id,
            "collection": collection,
            "explain": explain_result,
        }

    # Execute aggregation
    results = await connector.aggregate(collection, pipeline)

    return {
        "connector_id": connector_id,
        "collection": collection,
        "pipeline_stages": len(pipeline),
        "result_count": len(results),
        "results": results,
    }


async def handle_mongodb_collections(
    connector_id: str,
    tenant_id: str = "default",
    auth_context: Any | None = None,
) -> dict[str, Any]:
    """
    List collections in MongoDB database.

    GET /api/connectors/:connector_id/collections

    Requires connectors.read permission.
    """
    # Check RBAC permission
    perm_error = _check_permission(auth_context, "connectors:read", connector_id)
    if perm_error:
        return perm_error

    # SECURITY: Resolve tenant_id from auth context to prevent cross-tenant access
    tenant_id = _resolve_tenant_id(auth_context, tenant_id)

    from aragora.connectors.enterprise.registry import get_connector

    connector = get_connector(connector_id, tenant_id=tenant_id)
    if not connector:
        raise ValueError(f"Connector not found: {connector_id}")

    if not isinstance(connector, MongoDBConnector):
        raise ValueError(f"Connector {connector_id} is not a MongoDB connector")

    await connector._get_client()
    if connector._db is None:
        raise RuntimeError("Database not initialized")

    collections = await connector._db.list_collection_names()

    return {
        "connector_id": connector_id,
        "database": connector._database,
        "collections": collections,
    }


# =============================================================================
# Health Check
# =============================================================================


async def handle_connector_health(
    auth_context: Any | None = None,
) -> dict[str, Any]:
    """
    Health check for connector subsystem.

    GET /api/connectors/health

    Returns basic health status without auth, detailed stats with auth.
    """
    scheduler = get_scheduler()

    stats = scheduler.get_stats()

    # Basic health check for unauthenticated requests
    if not auth_context:
        return {
            "status": "healthy",
            "scheduler_running": scheduler._scheduler_task is not None,
            "total_connectors": stats["total_jobs"],
        }

    if not RBAC_AVAILABLE:
        if rbac_fail_closed():
            return {
                "status": "error",
                "error": "Service unavailable: access control module not loaded",
            }
        return {
            "status": "healthy",
            "scheduler_running": scheduler._scheduler_task is not None,
            "total_connectors": stats["total_jobs"],
        }

    # Detailed stats for authenticated users
    perm_error = _check_permission(auth_context, "connectors:read")
    if perm_error:
        # Return basic health even without permission
        return {
            "status": "healthy",
            "scheduler_running": scheduler._scheduler_task is not None,
            "total_connectors": stats["total_jobs"],
        }

    return {
        "status": "healthy",
        "scheduler_running": scheduler._scheduler_task is not None,
        "total_connectors": stats["total_jobs"],
        "running_syncs": stats["running_syncs"],
        "success_rate": stats["success_rate"],
    }
