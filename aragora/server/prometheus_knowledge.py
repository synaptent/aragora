"""
Knowledge Mound metrics for Aragora server.

Extracted from prometheus.py for maintainability.
Provides metrics for visibility, sharing, global knowledge, and federation.
"""

import logging
import time
from contextlib import contextmanager
from collections.abc import Generator

logger = logging.getLogger(__name__)

from aragora.observability.prometheus import (
    PROMETHEUS_AVAILABLE,
    _simple_metrics,
)

# Import metric definitions when prometheus is available
if PROMETHEUS_AVAILABLE:
    from aragora.observability.prometheus import (
        KNOWLEDGE_ACCESS_GRANTS,
        KNOWLEDGE_FEDERATION_LATENCY,
        KNOWLEDGE_FEDERATION_NODES,
        KNOWLEDGE_FEDERATION_REGIONS,
        KNOWLEDGE_FEDERATION_SYNCS,
        KNOWLEDGE_GLOBAL_FACTS,
        KNOWLEDGE_GLOBAL_QUERIES,
        KNOWLEDGE_SHARED_ITEMS,
        KNOWLEDGE_SHARES,
        KNOWLEDGE_VISIBILITY_CHANGES,
    )


def record_knowledge_visibility_change(
    from_level: str,
    to_level: str,
    workspace_id: str,
) -> None:
    """Record a visibility level change on a knowledge item.

    Args:
        from_level: Previous visibility level (private, workspace, org, public, system)
        to_level: New visibility level
        workspace_id: Workspace where the item resides
    """
    if PROMETHEUS_AVAILABLE:
        KNOWLEDGE_VISIBILITY_CHANGES.labels(
            from_level=from_level,
            to_level=to_level,
            workspace_id=workspace_id,
        ).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_knowledge_visibility_changes_total",
            {"from_level": from_level, "to_level": to_level, "workspace_id": workspace_id},
        )


def record_knowledge_access_grant(
    action: str,
    grantee_type: str,
    workspace_id: str,
) -> None:
    """Record an access grant operation.

    Args:
        action: Grant action (grant, revoke)
        grantee_type: Type of grantee (user, role, workspace, organization)
        workspace_id: Workspace where the item resides
    """
    if PROMETHEUS_AVAILABLE:
        KNOWLEDGE_ACCESS_GRANTS.labels(
            action=action,
            grantee_type=grantee_type,
            workspace_id=workspace_id,
        ).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_knowledge_access_grants_total",
            {"action": action, "grantee_type": grantee_type, "workspace_id": workspace_id},
        )


def record_knowledge_share(
    action: str,
    target_type: str,
) -> None:
    """Record a knowledge sharing operation.

    Args:
        action: Sharing action (share, accept, decline, revoke)
        target_type: Type of sharing target (workspace, user)
    """
    if PROMETHEUS_AVAILABLE:
        KNOWLEDGE_SHARES.labels(
            action=action,
            target_type=target_type,
        ).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_knowledge_shares_total",
            {"action": action, "target_type": target_type},
        )


def set_knowledge_shared_items(workspace_id: str, count: int) -> None:
    """Set the number of shared items pending acceptance for a workspace.

    Args:
        workspace_id: Workspace ID
        count: Number of pending shared items
    """
    if PROMETHEUS_AVAILABLE:
        KNOWLEDGE_SHARED_ITEMS.labels(workspace_id=workspace_id).set(count)
    else:
        _simple_metrics.set_gauge(
            "aragora_knowledge_shared_items_count",
            count,
            {"workspace_id": workspace_id},
        )


def record_knowledge_global_fact(action: str) -> None:
    """Record a global knowledge operation.

    Args:
        action: Action performed (stored, promoted, queried)
    """
    if PROMETHEUS_AVAILABLE:
        KNOWLEDGE_GLOBAL_FACTS.labels(action=action).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_knowledge_global_facts_total",
            {"action": action},
        )


def record_knowledge_global_query(has_results: bool) -> None:
    """Record a query against global knowledge.

    Args:
        has_results: Whether the query returned results
    """
    result_str = "true" if has_results else "false"
    if PROMETHEUS_AVAILABLE:
        KNOWLEDGE_GLOBAL_QUERIES.labels(has_results=result_str).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_knowledge_global_queries_total",
            {"has_results": result_str},
        )


def record_knowledge_federation_sync(
    region_id: str,
    direction: str,
    status: str,
    nodes_synced: int = 0,
    duration_seconds: float = 0.0,
) -> None:
    """Record a federation sync operation.

    Args:
        region_id: Federated region ID
        direction: Sync direction (push, pull)
        status: Sync status (success, failed)
        nodes_synced: Number of nodes synced
        duration_seconds: Time taken for sync
    """
    if PROMETHEUS_AVAILABLE:
        KNOWLEDGE_FEDERATION_SYNCS.labels(
            region_id=region_id,
            direction=direction,
            status=status,
        ).inc()

        if nodes_synced > 0:
            KNOWLEDGE_FEDERATION_NODES.labels(
                region_id=region_id,
                direction=direction,
            ).inc(nodes_synced)

        if duration_seconds > 0:
            KNOWLEDGE_FEDERATION_LATENCY.labels(
                region_id=region_id,
                direction=direction,
            ).observe(duration_seconds)
    else:
        _simple_metrics.inc_counter(
            "aragora_knowledge_federation_syncs_total",
            {"region_id": region_id, "direction": direction, "status": status},
        )
        if nodes_synced > 0:
            _simple_metrics.inc_counter(
                "aragora_knowledge_federation_nodes_total",
                {"region_id": region_id, "direction": direction},
                nodes_synced,
            )
        if duration_seconds > 0:
            _simple_metrics.observe_histogram(
                "aragora_knowledge_federation_latency_seconds",
                duration_seconds,
                {"region_id": region_id, "direction": direction},
            )


def set_knowledge_federation_regions(
    enabled: int = 0,
    disabled: int = 0,
    healthy: int = 0,
    unhealthy: int = 0,
) -> None:
    """Set federation region counts by status.

    Args:
        enabled: Number of enabled regions
        disabled: Number of disabled regions
        healthy: Number of healthy regions
        unhealthy: Number of unhealthy regions
    """
    if PROMETHEUS_AVAILABLE:
        KNOWLEDGE_FEDERATION_REGIONS.labels(status="enabled").set(enabled)
        KNOWLEDGE_FEDERATION_REGIONS.labels(status="disabled").set(disabled)
        KNOWLEDGE_FEDERATION_REGIONS.labels(status="healthy").set(healthy)
        KNOWLEDGE_FEDERATION_REGIONS.labels(status="unhealthy").set(unhealthy)
    else:
        _simple_metrics.set_gauge(
            "aragora_knowledge_federation_regions_count",
            enabled,
            {"status": "enabled"},
        )
        _simple_metrics.set_gauge(
            "aragora_knowledge_federation_regions_count",
            disabled,
            {"status": "disabled"},
        )
        _simple_metrics.set_gauge(
            "aragora_knowledge_federation_regions_count",
            healthy,
            {"status": "healthy"},
        )
        _simple_metrics.set_gauge(
            "aragora_knowledge_federation_regions_count",
            unhealthy,
            {"status": "unhealthy"},
        )


@contextmanager
def timed_knowledge_federation_sync(
    region_id: str,
    direction: str,
) -> Generator[dict, None, None]:
    """Context manager to time federation sync operations.

    Usage:
        with timed_knowledge_federation_sync("region-1", "push") as ctx:
            # perform sync
            ctx["nodes_synced"] = 42
            ctx["status"] = "success"

    Args:
        region_id: Federated region ID
        direction: Sync direction (push, pull)

    Yields:
        Dict to populate with sync results (nodes_synced, status)
    """
    start = time.perf_counter()
    ctx: dict = {"status": "success", "nodes_synced": 0}
    try:
        yield ctx
    except (
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
        OSError,
        TimeoutError,
        ConnectionError,
    ) as e:
        logger.warning("Federation sync to %s (%s) failed: %s", region_id, direction, e)
        ctx["status"] = "failed"
        raise
    finally:
        duration = time.perf_counter() - start
        record_knowledge_federation_sync(
            region_id=region_id,
            direction=direction,
            status=str(ctx["status"]),
            nodes_synced=int(ctx.get("nodes_synced", 0)),
            duration_seconds=duration,
        )


__all__ = [
    "record_knowledge_visibility_change",
    "record_knowledge_access_grant",
    "record_knowledge_share",
    "set_knowledge_shared_items",
    "record_knowledge_global_fact",
    "record_knowledge_global_query",
    "record_knowledge_federation_sync",
    "set_knowledge_federation_regions",
    "timed_knowledge_federation_sync",
]
