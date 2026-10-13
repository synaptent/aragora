"""
Gas Town Dashboard API Handlers.

Provides REST APIs for the Gas Town multi-agent orchestration dashboard:
- Overview stats and metrics
- Convoy progress tracking
- Agent workload distribution
- Bead queue depth
- GUPP recovery events

Endpoints:
- GET /api/v1/dashboard/gastown/overview - Get Gas Town overview
- GET /api/v1/dashboard/gastown/convoys - Get convoy list with progress
- GET /api/v1/dashboard/gastown/agents - Get agent workload distribution
- GET /api/v1/dashboard/gastown/beads - Get bead queue stats
- GET /api/v1/dashboard/gastown/metrics - Get throughput metrics

Note: This module uses Gas Town APIs that are still being developed.
Some APIs may have signature mismatches that require type: ignore comments.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    json_response,
)
from aragora.server.handlers.secure import SecureHandler, ForbiddenError, UnauthorizedError
from aragora.server.versioning.compat import strip_version_prefix
from aragora.server.validation.query_params import safe_query_int

logger = logging.getLogger(__name__)

# In-memory cache for dashboard data
_gt_dashboard_cache: dict[str, dict[str, Any]] = {}
_gt_dashboard_cache_lock = threading.Lock()

# Cache TTL (15 seconds for near-real-time)
CACHE_TTL = 15


def _get_cached_data(key: str) -> dict[str, Any] | None:
    """Get cached dashboard data if not expired."""
    with _gt_dashboard_cache_lock:
        cached = _gt_dashboard_cache.get(key)
        if cached:
            if datetime.now(timezone.utc).timestamp() - cached.get("cached_at", 0) < CACHE_TTL:
                return cached.get("data")
    return None


def _set_cached_data(key: str, data: dict[str, Any]) -> None:
    """Cache dashboard data."""
    with _gt_dashboard_cache_lock:
        _gt_dashboard_cache[key] = {
            "data": data,
            "cached_at": datetime.now(timezone.utc).timestamp(),
        }


def _get_gastown_state() -> Any | None:
    try:
        from aragora.server.extensions import get_extension_state

        return get_extension_state()
    except ImportError:
        # Extensions module not available
        return None
    except (RuntimeError, AttributeError) as e:
        # Extension state not initialized or misconfigured
        logger.debug(
            "Could not get Gas Town extension state: %s",
            e,
        )
        return None


def _resolve_convoy_tracker() -> Any | None:
    state = _get_gastown_state()
    if not state:
        return None
    if state.convoy_tracker:
        return state.convoy_tracker
    if state.coordinator:
        return state.coordinator.convoys
    return None


class GasTownDashboardHandler(SecureHandler):
    """Handler for Gas Town dashboard endpoints."""

    RESOURCE_TYPE = "gastown"

    ROUTES = [
        "/api/v1/dashboard/gastown/overview",
        "/api/v1/dashboard/gastown/convoys",
        "/api/v1/dashboard/gastown/agents",
        "/api/v1/dashboard/gastown/beads",
        "/api/v1/dashboard/gastown/metrics",
    ]

    def _get_canonical_workspace_stores(self):
        stores = getattr(self, "_canonical_workspace_stores", None)
        if stores is None:
            try:
                from aragora.stores import get_canonical_workspace_stores
            except ImportError:
                return None
            stores = get_canonical_workspace_stores()
            setattr(self, "_canonical_workspace_stores", stores)
        return stores

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can handle the given path."""
        normalized = strip_version_prefix(path)
        return (
            path.startswith("/api/v1/dashboard/gastown/")
            or normalized.startswith("/api/dashboard/gastown/")
            or path in self.ROUTES
        )

    async def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route Gas Town dashboard requests."""
        # Require authentication
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Permission denied", 403)

        # Check read permission
        try:
            self.check_permission(auth_context, "gastown:read")
        except ForbiddenError:
            return error_response("Permission denied", 403)

        path = strip_version_prefix(path)

        # Route to appropriate handler (path is normalized, no /v1/)
        if path == "/api/dashboard/gastown/overview":
            return await self._get_overview(query_params)
        elif path == "/api/dashboard/gastown/convoys":
            return await self._get_convoys(query_params)
        elif path == "/api/dashboard/gastown/agents":
            return await self._get_agents(query_params)
        elif path == "/api/dashboard/gastown/beads":
            return await self._get_beads(query_params)
        elif path == "/api/dashboard/gastown/metrics":
            return await self._get_metrics(query_params)

        return None

    async def _get_overview(self, query_params: dict[str, Any]) -> HandlerResult:
        """Get Gas Town overview dashboard data.

        Returns:
            - Total convoys (active, completed, failed)
            - Total beads (by status)
            - Agent counts (by role)
            - Witness patrol status
            - Mayor status
            - Recent activity summary
        """
        force_refresh = query_params.get("refresh", "").lower() == "true"

        if not force_refresh:
            cached = _get_cached_data("overview")
            if cached:
                return json_response(cached)

        now = datetime.now(timezone.utc)
        overview: dict[str, Any] = {
            "generated_at": now.isoformat(),
            "convoys": {"active": 0, "completed": 0, "failed": 0, "total": 0},
            "beads": {"pending": 0, "in_progress": 0, "completed": 0, "failed": 0, "total": 0},
            "agents": {"mayor": 0, "witness": 0, "polecat": 0, "crew": 0, "total": 0},
            "witness_patrol": {"active": False, "last_check": None},
            "mayor": {"active": False, "node_id": None},
        }

        # Get convoy stats
        try:
            convoys = []
            tracker = _resolve_convoy_tracker()
            if tracker:
                from aragora.extensions.gastown.models import ConvoyStatus as GastownStatus

                convoys = await tracker.list_convoys()
                overview["convoys"]["total"] = len(convoys)
                for c in convoys:
                    if c.status in (GastownStatus.IN_PROGRESS, GastownStatus.REVIEW):
                        overview["convoys"]["active"] += 1
                    elif c.status == GastownStatus.COMPLETED:
                        overview["convoys"]["completed"] += 1
                    elif c.status == GastownStatus.BLOCKED:
                        overview["convoys"]["failed"] += 1
            else:
                from aragora.nomic.stores import ConvoyStatus as ConvoyStatus

                stores = self._get_canonical_workspace_stores()
                if stores:
                    manager = await stores.convoy_manager()
                    convoys = await manager.list_convoys()
                    overview["convoys"]["total"] = len(convoys)
                    for c in convoys:
                        if c.status == ConvoyStatus.ACTIVE:
                            overview["convoys"]["active"] += 1
                        elif c.status == ConvoyStatus.COMPLETED:
                            overview["convoys"]["completed"] += 1
                        elif c.status == ConvoyStatus.FAILED:
                            overview["convoys"]["failed"] += 1
        except ImportError:
            logger.debug("Convoy module not available")
        except (AttributeError, TypeError, ValueError) as e:
            logger.debug(
                "Could not get convoy stats due to data error: %s",
                e,
            )
        except (RuntimeError, OSError) as e:
            logger.warning(
                "Could not get convoy stats due to runtime error: %s",
                e,
            )

        # Get bead stats
        try:
            from aragora.nomic.stores import BeadStatus

            stores = self._get_canonical_workspace_stores()
            if stores:
                bead_store = await stores.bead_store()
                for status in BeadStatus:
                    beads = await bead_store.list_beads(status=status, limit=1000)
                    count = len(beads)
                    overview["beads"][status.value] = count
                    overview["beads"]["total"] += count
        except ImportError:
            logger.debug("Bead module not available")
        except (AttributeError, TypeError, ValueError) as e:
            logger.debug(
                "Could not get bead stats due to data error: %s",
                e,
            )
        except (RuntimeError, OSError) as e:
            logger.warning(
                "Could not get bead stats due to runtime error: %s",
                e,
            )

        # Get agent stats
        try:
            from aragora.extensions.gastown.agent_roles import AgentHierarchy, AgentRole

            hierarchy: Any = AgentHierarchy()
            for role in AgentRole:
                agents = await hierarchy.list_agents(role=role)
                count = len(agents)
                overview["agents"][role.value] = count
                overview["agents"]["total"] += count
        except ImportError:
            logger.debug("Agent roles module not available")
        except (AttributeError, TypeError, ValueError) as e:
            logger.debug(
                "Could not get agent stats due to data error: %s",
                e,
            )
        except (RuntimeError, OSError) as e:
            logger.warning(
                "Could not get agent stats due to runtime error: %s",
                e,
            )

        # Get witness patrol status
        try:
            from aragora.server.startup import get_witness_behavior

            witness = get_witness_behavior()
            if witness:
                overview["witness_patrol"]["active"] = witness._running
        except ImportError:
            pass
        except AttributeError as e:
            # Witness behavior object not fully initialized
            logger.debug(
                "Could not get witness status: attribute missing: %s",
                e,
            )
        except (RuntimeError, OSError) as e:
            logger.warning(
                "Could not get witness status due to runtime error: %s",
                e,
            )

        # Get mayor status
        try:
            from aragora.server.startup import get_mayor_coordinator

            coordinator = get_mayor_coordinator()
            if coordinator:
                overview["mayor"]["active"] = coordinator.is_mayor
                overview["mayor"]["node_id"] = coordinator.get_current_mayor_node()
        except ImportError:
            pass
        except AttributeError as e:
            # Mayor coordinator object not fully initialized
            logger.debug(
                "Could not get mayor status: attribute missing: %s",
                e,
            )
        except (RuntimeError, OSError) as e:
            logger.warning(
                "Could not get mayor status due to runtime error: %s",
                e,
            )

        _set_cached_data("overview", overview)
        return json_response(overview)

    async def _get_convoys(self, query_params: dict[str, Any]) -> HandlerResult:
        """Get convoy list with progress.

        Returns list of convoys with:
        - ID, title, status
        - Progress (completed/total beads)
        - Created/updated timestamps
        - Assigned agents
        """
        limit = safe_query_int(query_params, "limit", default=20, max_val=1000)
        status_filter = query_params.get("status")

        try:
            tracker = _resolve_convoy_tracker()
            result = []

            if tracker:
                from aragora.extensions.gastown.models import ConvoyStatus as GastownStatus
                from aragora.workspace.bead import BeadManager, BeadStatus

                filter_status = None
                if status_filter:
                    try:
                        filter_status = GastownStatus(status_filter)
                    except ValueError:
                        return error_response(f"Invalid status: {status_filter}", 400)

                convoys = await tracker.list_convoys(status=filter_status)
                bead_manager = BeadManager()

                for c in convoys[:limit]:
                    beads = await bead_manager.list_beads(convoy_id=c.id)
                    total_beads = len(beads)
                    completed_beads = sum(1 for b in beads if b.status == BeadStatus.DONE)
                    failed_beads = sum(1 for b in beads if b.status == BeadStatus.FAILED)
                    progress_pct = (completed_beads / total_beads) * 100 if total_beads else 0.0

                    result.append(
                        {
                            "id": c.id,
                            "title": c.title,
                            "description": getattr(c, "description", ""),
                            "status": c.status.value,
                            "total_beads": total_beads,
                            "completed_beads": completed_beads,
                            "failed_beads": failed_beads,
                            "progress_percentage": round(progress_pct, 1),
                            "created_at": c.created_at.isoformat() if c.created_at else None,
                            "updated_at": getattr(c, "updated_at", c.created_at).isoformat()
                            if getattr(c, "updated_at", c.created_at)
                            else None,
                        }
                    )
                total = len(convoys)
            else:
                from aragora.nomic.stores import ConvoyStatus as ConvoyStatus

                stores = self._get_canonical_workspace_stores()
                if not stores:
                    return json_response({"convoys": [], "total": 0, "showing": 0})
                bead_store = await stores.bead_store()
                convoy_manager = await stores.convoy_manager()

                filter_status: Any | None = None  # type: ignore[no-redef]
                if status_filter:
                    try:
                        filter_status = ConvoyStatus(status_filter)  # type: ignore[assignment]
                    except ValueError:
                        return error_response(f"Invalid status: {status_filter}", 400)

                convoys = await convoy_manager.list_convoys(status=filter_status)

                for c in convoys[:limit]:
                    total_beads = len(c.bead_ids)
                    completed_beads = 0
                    failed_beads = 0
                    for bead_id in c.bead_ids:
                        bead = await bead_store.get(bead_id)
                        if not bead:
                            continue
                        if bead.status.value == "completed":
                            completed_beads += 1
                        elif bead.status.value == "failed":
                            failed_beads += 1
                    progress_pct = (completed_beads / total_beads) * 100 if total_beads else 0.0

                    result.append(
                        {
                            "id": c.id,
                            "title": c.title,
                            "description": getattr(c, "description", ""),
                            "status": c.status.value,
                            "total_beads": total_beads,
                            "completed_beads": completed_beads,
                            "failed_beads": failed_beads,
                            "progress_percentage": round(progress_pct, 1),
                            "created_at": c.created_at.isoformat() if c.created_at else None,
                            "updated_at": getattr(c, "updated_at", c.created_at).isoformat()
                            if getattr(c, "updated_at", c.created_at)
                            else None,
                        }
                    )
                total = len(convoys)

            return json_response(
                {
                    "convoys": result,
                    "total": total,
                    "showing": len(result),
                }
            )

        except ImportError as e:
            logger.debug("Convoy module not available: %s", e)
            return json_response({"convoys": [], "total": 0, "showing": 0})
        except (AttributeError, TypeError, KeyError) as e:
            # Data structure issues - return empty but log warning
            logger.warning(
                "Error getting convoys due to data error: %s",
                e,
            )
            return json_response({"convoys": [], "total": 0, "showing": 0, "error": "data_error"})
        except (RuntimeError, OSError) as e:
            # Runtime errors - return 500 with context
            logger.error(
                "Error getting convoys due to runtime error: %s",
                e,
            )
            return error_response("Internal server error", 500)

    async def _get_agents(self, query_params: dict[str, Any]) -> HandlerResult:
        """Get agent workload distribution.

        Returns:
        - Agents grouped by role
        - Active bead count per agent
        - Completion rate per agent
        """
        try:
            from aragora.extensions.gastown.agent_roles import AgentHierarchy, AgentRole

            hierarchy: Any = AgentHierarchy()

            agents_by_role: dict[str, list[dict[str, Any]]] = {role.value: [] for role in AgentRole}

            for role in AgentRole:
                agents = await hierarchy.list_agents(role=role)
                for a in agents:
                    agents_by_role[role.value].append(
                        {
                            "agent_id": a.agent_id,
                            "role": a.role.value,
                            "supervised_by": a.supervised_by,
                            "is_ephemeral": a.is_ephemeral,
                            "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
                            "capabilities": [c.value for c in a.capabilities]
                            if a.capabilities
                            else [],
                        }
                    )

            # Calculate totals
            totals = {role: len(agents) for role, agents in agents_by_role.items()}
            totals["total"] = sum(totals.values())

            return json_response(
                {
                    "agents_by_role": agents_by_role,
                    "totals": totals,
                }
            )

        except ImportError as e:
            logger.debug("Agent roles module not available: %s", e)
            return json_response(
                {
                    "agents_by_role": {},
                    "totals": {"total": 0},
                }
            )
        except (AttributeError, TypeError, KeyError) as e:
            # Data structure issues
            logger.warning(
                "Error getting agents due to data error: %s",
                e,
            )
            return json_response(
                {
                    "agents_by_role": {},
                    "totals": {"total": 0},
                    "error": "data_error",
                }
            )
        except (RuntimeError, OSError) as e:
            # Runtime errors
            logger.error(
                "Error getting agents due to runtime error: %s",
                e,
            )
            return error_response("Internal server error", 500)

    async def _get_beads(self, query_params: dict[str, Any]) -> HandlerResult:
        """Get bead queue stats.

        Returns:
        - Bead counts by status
        - Queue depth over time
        - Average completion time
        """
        try:
            from aragora.nomic.stores import BeadPriority, BeadStatus

            stores = self._get_canonical_workspace_stores()
            if not stores:
                return json_response(
                    {
                        "by_status": {},
                        "queue_depth": 0,
                        "processing": 0,
                        "total": 0,
                    }
                )
            bead_store = await stores.bead_store()

            stats: dict[str, Any] = {
                "by_status": {},
                "by_priority": {},
                "queue_depth": 0,
                "processing": 0,
            }

            total = 0
            for status in BeadStatus:
                beads = await bead_store.list_beads(status=status, limit=1000)
                count = len(beads)
                stats["by_status"][status.value] = count
                total += count

            stats["queue_depth"] = stats["by_status"].get("pending", 0)
            stats["processing"] = stats["by_status"].get("running", 0) + stats["by_status"].get(
                "claimed", 0
            )
            stats["total"] = total

            # Get priority distribution
            for priority in BeadPriority:
                beads = await bead_store.list_beads(priority=priority, limit=1000)
                stats["by_priority"][priority.value] = len(beads)

            return json_response(stats)

        except ImportError as e:
            logger.debug("Bead module not available: %s", e)
            return json_response(
                {
                    "by_status": {},
                    "queue_depth": 0,
                    "processing": 0,
                    "total": 0,
                }
            )
        except (AttributeError, TypeError, KeyError) as e:
            # Data structure issues
            logger.warning(
                "Error getting beads due to data error: %s",
                e,
            )
            return json_response(
                {
                    "by_status": {},
                    "queue_depth": 0,
                    "processing": 0,
                    "total": 0,
                    "error": "data_error",
                }
            )
        except (RuntimeError, OSError) as e:
            # Runtime errors
            logger.error(
                "Error getting beads due to runtime error: %s",
                e,
            )
            return error_response("Internal server error", 500)

    async def _get_metrics(self, query_params: dict[str, Any]) -> HandlerResult:
        """Get throughput metrics.

        Returns:
        - Beads completed per hour
        - Average bead duration
        - Convoy completion rate
        - GUPP recovery events (if available)
        """
        hours = safe_query_int(query_params, "hours", default=24, max_val=8760)

        metrics: dict[str, Any] = {
            "period_hours": hours,
            "beads_per_hour": 0.0,
            "avg_bead_duration_minutes": None,
            "convoy_completion_rate": 0.0,
            "gupp_recovery_events": 0,
        }

        # Try to get metrics from Prometheus or internal counters
        try:
            from aragora.extensions.gastown.metrics import (
                get_beads_completed_count,
                get_convoy_completion_rate,
                get_gupp_recovery_count,
            )

            beads_completed = get_beads_completed_count(hours=hours)
            metrics["beads_per_hour"] = round(beads_completed / max(hours, 1), 2)
            metrics["convoy_completion_rate"] = get_convoy_completion_rate()
            metrics["gupp_recovery_events"] = get_gupp_recovery_count(hours=hours)

        except ImportError:
            # Fallback: estimate from current data
            try:
                tracker = _resolve_convoy_tracker()
                if tracker:
                    from aragora.extensions.gastown.models import ConvoyStatus as GastownStatus

                    convoys = await tracker.list_convoys()
                    completed = sum(1 for c in convoys if c.status == GastownStatus.COMPLETED)
                    total = len(convoys)
                    if total > 0:
                        metrics["convoy_completion_rate"] = round((completed / total) * 100, 1)
                else:
                    from aragora.nomic.stores import ConvoyStatus as ConvoyStatus

                    stores = self._get_canonical_workspace_stores()
                    if stores:
                        mgr = await stores.convoy_manager()
                        convoys = await mgr.list_convoys()
                        completed = sum(1 for c in convoys if c.status == ConvoyStatus.COMPLETED)
                        total = len(convoys)
                        if total > 0:
                            metrics["convoy_completion_rate"] = round((completed / total) * 100, 1)
            except (ImportError, AttributeError, TypeError, RuntimeError, OSError) as e:
                logger.debug(
                    "Could not get convoy metrics: %s",
                    e,
                )
        except (AttributeError, TypeError, ValueError) as e:
            logger.debug(
                "Could not get detailed metrics due to data error: %s",
                e,
            )
        except (RuntimeError, OSError) as e:
            logger.warning(
                "Could not get detailed metrics due to runtime error: %s",
                e,
            )

        return json_response(metrics)
