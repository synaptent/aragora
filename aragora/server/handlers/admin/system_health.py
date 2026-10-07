"""
System Health Dashboard handler.

Provides a unified view of infrastructure health across all backend subsystems:
circuit breakers, SLOs, KM adapters, agent pool, and budget utilization.

Endpoints:
    GET /api/admin/system-health              - Aggregated health overview
    GET /api/admin/system-health/circuit-breakers - Circuit breaker states
    GET /api/admin/system-health/slos          - SLO compliance status
    GET /api/admin/system-health/adapters      - KM adapter health
    GET /api/admin/system-health/agents        - Agent pool health
    GET /api/admin/system-health/budget        - Budget utilization
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from aragora.server.versioning.compat import strip_version_prefix

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
)
from aragora.server.handlers.utils.rate_limit import rate_limit

try:
    from aragora.rbac.decorators import require_permission
except ImportError:  # pragma: no cover

    def require_permission(*_a, **_kw):  # type: ignore[misc]
        def _noop(fn):  # type: ignore[no-untyped-def]
            return fn

        return _noop


logger = logging.getLogger(__name__)


class SystemHealthDashboardHandler(BaseHandler):
    """Unified system health dashboard handler.

    Aggregates health data from circuit breakers, SLOs, KM adapters,
    agent pool, and budget subsystems with graceful fallbacks.
    """

    ROUTES = [
        "/api/admin/system-health",
        "/api/admin/system-health/circuit-breakers",
        "/api/admin/system-health/slos",
        "/api/admin/system-health/adapters",
        "/api/admin/system-health/agents",
        "/api/admin/system-health/budget",
    ]

    def __init__(self, server_context: dict[str, Any]) -> None:
        super().__init__(server_context)

    def can_handle(self, path: str, method: str = "GET") -> bool:
        normalized = strip_version_prefix(path)
        return method == "GET" and normalized in self.ROUTES

    @require_permission("system:read")
    @rate_limit(requests_per_minute=30)
    async def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        path = strip_version_prefix(path)
        if path == "/api/admin/system-health":
            return self._get_overview()
        if path == "/api/admin/system-health/circuit-breakers":
            return self._get_circuit_breakers()
        if path == "/api/admin/system-health/slos":
            return self._get_slos()
        if path == "/api/admin/system-health/adapters":
            return self._get_adapters()
        if path == "/api/admin/system-health/agents":
            return self._get_agents()
        if path == "/api/admin/system-health/budget":
            return self._get_budget()
        return error_response("Not found", 404)

    # ------------------------------------------------------------------
    # Aggregated overview
    # ------------------------------------------------------------------

    def _get_overview(self) -> HandlerResult:
        t0 = time.monotonic()

        cb_data = self._collect_circuit_breakers()
        slo_data = self._collect_slos()
        adapter_data = self._collect_adapters()
        agent_data = self._collect_agents()
        budget_data = self._collect_budget()

        # Derive overall status
        subsystems: dict[str, str] = {}
        statuses: list[str] = []

        # Circuit breakers
        cb_status = "healthy"
        if cb_data.get("available"):
            open_count = sum(1 for b in cb_data.get("breakers", []) if b.get("state") == "open")
            half_open = sum(1 for b in cb_data.get("breakers", []) if b.get("state") == "half-open")
            if open_count > 0:
                cb_status = "critical"
            elif half_open > 0:
                cb_status = "degraded"
        else:
            cb_status = "unknown"
        subsystems["circuit_breakers"] = cb_status
        statuses.append(cb_status)

        # SLOs
        slo_status = "healthy"
        if slo_data.get("available"):
            if not slo_data.get("overall_healthy", True):
                non_compliant = sum(
                    1 for s in slo_data.get("slos", []) if not s.get("compliant", True)
                )
                slo_status = "critical" if non_compliant > 1 else "degraded"
        else:
            slo_status = "unknown"
        subsystems["slos"] = slo_status
        statuses.append(slo_status)

        # Adapters
        adapter_status = "healthy"
        if adapter_data.get("available"):
            total = adapter_data.get("total", 0)
            active = adapter_data.get("active", 0)
            if total > 0 and active < total * 0.5:
                adapter_status = "degraded"
        else:
            adapter_status = "unknown"
        subsystems["adapters"] = adapter_status
        statuses.append(adapter_status)

        # Agents
        agent_status = "healthy"
        if agent_data.get("available"):
            failed = sum(1 for a in agent_data.get("agents", []) if a.get("status") == "failed")
            total_agents = agent_data.get("total", 0)
            if total_agents > 0 and failed > total_agents * 0.3:
                agent_status = "critical"
            elif failed > 0:
                agent_status = "degraded"
        else:
            agent_status = "unknown"
        subsystems["agents"] = agent_status
        statuses.append(agent_status)

        # Budget
        budget_status = "healthy"
        if budget_data.get("available"):
            utilization = budget_data.get("utilization", 0)
            if utilization > 0.95:
                budget_status = "critical"
            elif utilization > 0.8:
                budget_status = "degraded"
        else:
            budget_status = "unknown"
        subsystems["budget"] = budget_status
        statuses.append(budget_status)

        # Overall
        if "critical" in statuses:
            overall = "critical"
        elif "degraded" in statuses:
            overall = "degraded"
        else:
            overall = "healthy"

        elapsed_ms = round((time.monotonic() - t0) * 1000, 1)

        return json_response(
            {
                "data": {
                    "overall_status": overall,
                    "subsystems": subsystems,
                    "circuit_breakers": cb_data,
                    "slos": slo_data,
                    "adapters": adapter_data,
                    "agents": agent_data,
                    "budget": budget_data,
                    "last_check": datetime.now(timezone.utc).isoformat(),
                    "collection_time_ms": elapsed_ms,
                }
            }
        )

    # ------------------------------------------------------------------
    # Circuit breakers
    # ------------------------------------------------------------------

    def _collect_circuit_breakers(self) -> dict[str, Any]:
        fallback: dict[str, Any] = {"breakers": [], "available": False}
        try:
            from aragora.resilience.registry import get_circuit_breakers

            all_breakers = get_circuit_breakers()
            breakers = []
            for name, cb in all_breakers.items():
                status = cb.get_status() if hasattr(cb, "get_status") else "unknown"
                failures = getattr(cb, "_single_failures", 0)
                threshold = getattr(cb, "failure_threshold", 3)
                success_rate = 1.0
                if threshold > 0 and failures > 0:
                    success_rate = max(0.0, 1.0 - (failures / threshold))
                breakers.append(
                    {
                        "name": name,
                        "state": status,
                        "failure_count": failures,
                        "failure_threshold": threshold,
                        "cooldown_seconds": getattr(cb, "cooldown_seconds", 60),
                        "success_rate": round(success_rate, 3),
                        "last_failure": None,
                    }
                )
            return {"breakers": breakers, "total": len(breakers), "available": True}
        except (ImportError, AttributeError, RuntimeError) as e:
            logger.debug("Circuit breaker collection failed: %s", e)
            return fallback

    def _get_circuit_breakers(self) -> HandlerResult:
        return json_response({"data": self._collect_circuit_breakers()})

    # ------------------------------------------------------------------
    # SLOs
    # ------------------------------------------------------------------

    def _collect_slos(self) -> dict[str, Any]:
        fallback: dict[str, Any] = {"slos": [], "overall_healthy": True, "available": False}
        try:
            from aragora.observability.slo import get_slo_status

            status = get_slo_status()
            slos = []
            for label, result in [
                ("availability", status.availability),
                ("latency_p99", status.latency_p99),
                ("debate_success", status.debate_success),
            ]:
                slos.append(
                    {
                        "name": result.name,
                        "key": label,
                        "target": result.target,
                        "current": round(result.current, 6),
                        "compliant": result.compliant,
                        "compliance_percentage": round(result.compliance_percentage, 2),
                        "error_budget_remaining": round(result.error_budget_remaining, 2),
                        "burn_rate": round(result.burn_rate, 3),
                    }
                )
            return {
                "slos": slos,
                "overall_healthy": status.overall_healthy,
                "timestamp": status.timestamp.isoformat(),
                "available": True,
            }
        except (ImportError, AttributeError, RuntimeError) as e:
            logger.debug("SLO collection failed: %s", e)
            return fallback

    def _get_slos(self) -> HandlerResult:
        return json_response({"data": self._collect_slos()})

    # ------------------------------------------------------------------
    # KM Adapters
    # ------------------------------------------------------------------

    def _collect_adapters(self) -> dict[str, Any]:
        fallback: dict[str, Any] = {"adapters": [], "active": 0, "total": 0, "available": False}
        try:
            from aragora.knowledge.mound.adapters.factory import ADAPTER_SPECS

            adapters = []
            for name, spec in ADAPTER_SPECS.items():
                adapters.append(
                    {
                        "name": name,
                        "enabled_by_default": spec.enabled_by_default,
                        "priority": spec.priority,
                        "has_reverse_sync": spec.reverse_method is not None,
                    }
                )

            active = sum(1 for a in adapters if a["enabled_by_default"])
            return {
                "adapters": sorted(adapters, key=lambda a: -a["priority"]),
                "active": active,
                "total": len(adapters),
                "available": True,
            }
        except (ImportError, AttributeError, RuntimeError) as e:
            logger.debug("Adapter collection failed: %s", e)
            return fallback

    def _get_adapters(self) -> HandlerResult:
        return json_response({"data": self._collect_adapters()})

    # ------------------------------------------------------------------
    # Agent pool
    # ------------------------------------------------------------------

    def _collect_agents(self) -> dict[str, Any]:
        fallback: dict[str, Any] = {"agents": [], "total": 0, "active": 0, "available": False}
        try:
            from aragora.control_plane.registry import get_default_registry

            registry = get_default_registry()
            if registry is None:
                return fallback

            agents_raw = registry.list_agents() if hasattr(registry, "list_agents") else []
            agents = []
            active_count = 0
            for a in agents_raw:
                if isinstance(a, dict):
                    agent_id = a.get("agent_id", a.get("id", "unknown"))
                    agent_type = a.get("type", a.get("agent_type", "unknown"))
                    status = a.get("status", "unknown")
                    heartbeat = a.get("last_heartbeat", "")
                else:
                    agent_id = getattr(a, "agent_id", getattr(a, "id", "unknown"))
                    agent_type = getattr(a, "type", getattr(a, "agent_type", "unknown"))
                    status = getattr(a, "status", "unknown")
                    heartbeat = str(getattr(a, "last_heartbeat", ""))

                if status in ("active", "idle"):
                    active_count += 1
                agents.append(
                    {
                        "agent_id": str(agent_id),
                        "type": str(agent_type),
                        "status": str(status),
                        "last_heartbeat": str(heartbeat),
                    }
                )

            return {
                "agents": agents,
                "total": len(agents),
                "active": active_count,
                "available": True,
            }
        except (ImportError, AttributeError, RuntimeError) as e:
            logger.debug("Agent pool collection failed: %s", e)
            return fallback

    def _get_agents(self) -> HandlerResult:
        return json_response({"data": self._collect_agents()})

    # ------------------------------------------------------------------
    # Budget
    # ------------------------------------------------------------------

    def _collect_budget(self) -> dict[str, Any]:
        fallback: dict[str, Any] = {
            "total_budget": 0,
            "spent": 0,
            "utilization": 0,
            "forecast": None,
            "available": False,
        }
        try:
            from aragora.billing.cost_tracker import get_cost_tracker

            tracker = get_cost_tracker()
            if tracker is None:
                return fallback

            summary = tracker.get_summary() if hasattr(tracker, "get_summary") else {}
            total: Any
            spent: Any
            if isinstance(summary, dict):
                total = summary.get("budget_usd", summary.get("total_budget", 100))
                spent = summary.get("total_cost_usd", summary.get("spent", 0))
            else:
                total = getattr(summary, "budget_usd", getattr(summary, "total_budget", 100))
                spent = getattr(summary, "total_cost_usd", getattr(summary, "spent", 0))

            utilization = spent / total if total > 0 else 0

            forecast = None
            try:
                from aragora.billing.forecaster import get_cost_forecaster

                forecaster = get_cost_forecaster()
                if forecaster and hasattr(forecaster, "forecast_eom"):
                    eom = forecaster.forecast_eom()
                    if eom is not None:
                        trend = "stable"
                        eom_val: Any
                        if isinstance(eom, dict):
                            eom_val = eom.get("projected", spent)
                            trend = eom.get("trend", "stable")
                        else:
                            eom_val = float(eom)
                            if eom_val > spent * 1.2:
                                trend = "increasing"
                            elif eom_val < spent * 0.8:
                                trend = "decreasing"
                        forecast = {"eom": round(eom_val, 2), "trend": trend}
            except (ImportError, AttributeError, RuntimeError):
                pass

            return {
                "total_budget": round(total, 2),
                "spent": round(spent, 2),
                "utilization": round(utilization, 4),
                "forecast": forecast,
                "available": True,
            }
        except (ImportError, AttributeError, RuntimeError) as e:
            logger.debug("Budget collection failed: %s", e)
            return fallback

    def _get_budget(self) -> HandlerResult:
        return json_response({"data": self._collect_budget()})
