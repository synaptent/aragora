"""
Knowledge Mound health check implementations.

Provides comprehensive health checks for the Knowledge Mound subsystem.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from ...base import HandlerResult, json_response

if TYPE_CHECKING:
    from aragora.knowledge.mound import KnowledgeMound
    from aragora.knowledge.mound.types import MoundConfig

logger = logging.getLogger(__name__)


class KnowledgeMixin:
    """Mixin providing Knowledge Mound health checks.

    Should be mixed into a handler class that provides json_response access.
    """

    def knowledge_mound_health(self) -> HandlerResult:
        """Comprehensive health check for Knowledge Mound subsystem.

        Returns detailed status of:
        - Core mound: Storage layer, fact storage, workspace config
        - Culture accumulator: Organizational pattern tracking
        - Staleness tracking: Fact age and refresh status
        - Query performance: Retrieval latency stats
        - Storage backends: PostgreSQL/SQLite status
        - RLM integration: Context compression caching

        This endpoint is useful for:
        - Monitoring Knowledge Mound operational health
        - Debugging knowledge retrieval issues
        - Verifying debate-knowledge integration
        - Tracking storage capacity and performance

        Returns:
            JSON response with comprehensive KM health metrics
        """
        components: dict[str, dict[str, Any]] = {}
        all_healthy = True
        warnings: list[str] = []
        start_time = time.time()

        # 1. Check if Knowledge Mound module is available
        try:
            from aragora.knowledge.mound import KnowledgeMound
            from aragora.knowledge.mound.types import MoundConfig  # noqa: F401

            components["module"] = {
                "healthy": True,
                "status": "available",
            }
        except ImportError as e:
            logger.warning("Knowledge Mound module not available: %s", e)
            components["module"] = {
                "healthy": False,
                "status": "not_available",
                "error": "Module not available",
            }
            all_healthy = False
            return json_response(
                {
                    "status": "unavailable",
                    "error": "Knowledge Mound module not installed",
                    "components": components,
                    "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                }
            )

        # 2. Check core mound initialization
        mound: KnowledgeMound | None = None
        try:
            # KnowledgeMound is a concrete class composed of 17 mixins. mypy
            # reports it as abstract because Protocol bases in the mixin chain
            # declare abstract methods satisfied at runtime via cooperative MRO.
            mound = KnowledgeMound(workspace_id="health_check")  # type: ignore[abstract]

            components["core"] = {
                "healthy": True,
                "status": "initialized",
                "workspace_id": mound.workspace_id,
            }

            # Check config
            if hasattr(mound, "config") and mound.config:
                config: MoundConfig = mound.config
                components["core"]["config"] = {
                    "enable_staleness_detection": config.enable_staleness_detection,
                    "enable_culture_accumulator": config.enable_culture_accumulator,
                    "staleness_age_threshold_days": config.staleness_age_threshold.days,
                }

        except (OSError, RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.warning("Knowledge Mound core init failed: %s: %s", type(e).__name__, e)
            components["core"] = {
                "healthy": False,
                "status": "initialization_failed",
                "error": "Initialization failed",
            }
            all_healthy = False

        # 3. Check storage backend
        components["storage"] = self._check_km_storage(mound)

        # 4. Check culture accumulator
        components["culture_accumulator"] = self._check_culture_accumulator(mound)

        # 5. Check staleness tracker
        components["staleness_tracker"] = self._check_staleness_tracker(mound)

        # 6. Check RLM integration
        components["rlm_integration"] = self._check_rlm_integration()

        # 7. Check debate integration via knowledge_mound_ops
        components["debate_integration"] = self._check_debate_integration()

        # 8. Check Redis cache for mound (if configured)
        components["redis_cache"] = self._check_km_redis_cache()

        # 9. Check bidirectional adapters
        components["bidirectional_adapters"] = self._check_km_adapters()

        # 10. Check Control Plane adapter
        components["control_plane_adapter"] = self._check_control_plane_adapter()

        # 11. Check KM metrics availability
        components["km_metrics"] = self._check_km_metrics()

        # 12. Check Confidence Decay Scheduler
        decay_result = self._check_confidence_decay()
        components["confidence_decay"] = decay_result["component"]
        if decay_result.get("warnings"):
            warnings.extend(decay_result["warnings"])

        # Calculate response time
        response_time_ms = round((time.time() - start_time) * 1000, 2)

        # Determine overall status
        healthy_count = sum(1 for c in components.values() if c.get("healthy", False))
        active_count = sum(1 for c in components.values() if c.get("status") == "active")
        total_components = len(components)

        status = "healthy" if all_healthy else "degraded"
        if active_count == 0:
            status = "not_configured"

        return json_response(
            {
                "status": status,
                "summary": {
                    "total_components": total_components,
                    "healthy": healthy_count,
                    "active": active_count,
                },
                "components": components,
                "warnings": warnings if warnings else None,
                "response_time_ms": response_time_ms,
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            }
        )

    def _check_km_storage(self, mound: Any) -> dict[str, Any]:
        """Check Knowledge Mound storage backend."""
        try:
            import os

            database_url = os.environ.get("KNOWLEDGE_MOUND_DATABASE_URL", "")

            if "postgres" in database_url.lower():
                result = {
                    "healthy": True,
                    "backend": "postgresql",
                    "status": "configured",
                }
            else:
                result = {
                    "healthy": True,
                    "backend": "sqlite",
                    "status": "configured",
                    "note": "Using local SQLite storage",
                }

            # Try to get storage stats if mound initialized
            if mound is not None and hasattr(mound, "_store"):
                try:
                    if mound._store is not None:
                        result["store_type"] = type(mound._store).__name__
                except AttributeError:
                    logger.debug("Could not get store type for knowledge mound health check")

            return result

        except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError) as e:
            logger.debug("KM storage check error: %s: %s", type(e).__name__, e)
            return {
                "healthy": True,
                "status": "unknown",
                "warning": "Health check failed",
            }

    def _check_culture_accumulator(self, mound: Any) -> dict[str, Any]:
        """Check culture accumulator status."""
        try:
            if mound is not None:
                if hasattr(mound, "_culture_accumulator") and mound._culture_accumulator:
                    accumulator = mound._culture_accumulator
                    result = {
                        "healthy": True,
                        "status": "active",
                        "type": type(accumulator).__name__,
                    }

                    # Try to get pattern counts
                    try:
                        if hasattr(accumulator, "_patterns"):
                            workspace_count = len(accumulator._patterns)
                            result["workspaces_tracked"] = workspace_count
                    except (AttributeError, TypeError):
                        logger.debug(
                            "Could not get pattern counts for culture accumulator health check"
                        )

                    return result
                else:
                    return {
                        "healthy": True,
                        "status": "not_initialized",
                        "note": "Culture accumulator disabled or not yet created",
                    }
            return {
                "healthy": True,
                "status": "not_initialized",
            }
        except (AttributeError, TypeError, KeyError, RuntimeError) as e:
            logger.debug("Culture accumulator check error: %s: %s", type(e).__name__, e)
            return {
                "healthy": True,
                "status": "error",
                "error": "Health check failed",
            }

    def _check_staleness_tracker(self, mound: Any) -> dict[str, Any]:
        """Check staleness tracker status."""
        try:
            if mound is not None:
                if hasattr(mound, "_staleness_tracker") and mound._staleness_tracker:
                    return {
                        "healthy": True,
                        "status": "active",
                    }
                else:
                    return {
                        "healthy": True,
                        "status": "not_initialized",
                        "note": "Staleness tracking disabled",
                    }
            return {
                "healthy": True,
                "status": "not_initialized",
            }
        except (AttributeError, TypeError, RuntimeError) as e:
            logger.debug("Staleness tracker check error: %s: %s", type(e).__name__, e)
            return {
                "healthy": True,
                "status": "error",
                "error": "Health check failed",
            }

    def _check_rlm_integration(self) -> dict[str, Any]:
        """Check RLM integration status."""
        try:
            from aragora.rlm import HAS_OFFICIAL_RLM

            if HAS_OFFICIAL_RLM:
                return {
                    "healthy": True,
                    "status": "active",
                    "type": "official_rlm",
                }
            else:
                return {
                    "healthy": True,
                    "status": "fallback",
                    "type": "compression_only",
                    "note": "Using compression fallback (official RLM not installed)",
                }
        except ImportError:
            return {
                "healthy": True,
                "status": "not_available",
                "note": "RLM module not installed",
            }
        except (AttributeError, TypeError, RuntimeError, ValueError) as e:
            logger.debug("RLM integration check error: %s: %s", type(e).__name__, e)
            return {
                "healthy": True,
                "status": "error",
                "error": "Health check failed",
            }

    def _check_debate_integration(self) -> dict[str, Any]:
        """Check debate integration via knowledge_mound_ops."""
        try:
            from aragora.debate import knowledge_mound_ops

            get_knowledge_mound_stats = getattr(
                knowledge_mound_ops, "get_knowledge_mound_stats", None
            )
            if get_knowledge_mound_stats is None:
                return {
                    "healthy": True,
                    "status": "not_available",
                    "note": "get_knowledge_mound_stats not found in knowledge_mound_ops",
                }

            km_stats: dict[str, Any] = get_knowledge_mound_stats()
            return {
                "healthy": True,
                "status": "active",
                "facts_count": km_stats.get("facts_count", 0),
                "consensus_stored": km_stats.get("consensus_stored", 0),
                "retrievals_count": km_stats.get("retrievals_count", 0),
            }
        except ImportError:
            return {
                "healthy": True,
                "status": "not_available",
                "note": "knowledge_mound_ops module not available",
            }
        except (AttributeError, TypeError, KeyError, RuntimeError, ValueError) as e:
            logger.debug("Debate integration check error: %s: %s", type(e).__name__, e)
            return {
                "healthy": True,
                "status": "error",
                "error": "Health check failed",
            }

    def _check_km_redis_cache(self) -> dict[str, Any]:
        """Check Redis cache for Knowledge Mound."""
        try:
            import os

            redis_url = os.environ.get("KNOWLEDGE_MOUND_REDIS_URL") or os.environ.get("REDIS_URL")
            if redis_url:
                from aragora.knowledge.mound.redis_cache import RedisCache

                RedisCache(url=redis_url)
                return {
                    "healthy": True,
                    "status": "configured",
                }
            else:
                return {
                    "healthy": True,
                    "status": "not_configured",
                    "note": "Knowledge Mound Redis cache not configured",
                }
        except ImportError:
            return {
                "healthy": True,
                "status": "not_available",
                "note": "Redis cache module not installed",
            }
        except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as e:
            logger.debug("KM Redis cache check error: %s: %s", type(e).__name__, e)
            return {
                "healthy": True,
                "status": "error",
                "error": "Health check failed",
            }

    def _check_km_adapters(self) -> dict[str, Any]:
        """Check bidirectional KM adapters."""
        try:
            from aragora.knowledge.mound.adapters import (
                ContinuumAdapter,
                ConsensusAdapter,
                CritiqueAdapter,
                EvidenceAdapter,
                BeliefAdapter,
                InsightsAdapter,
                EloAdapter,
                PulseAdapter,
                CostAdapter,
                RankingAdapter,
                CultureAdapter,
            )

            adapter_classes = [
                ("continuum", ContinuumAdapter),
                ("consensus", ConsensusAdapter),
                ("critique", CritiqueAdapter),
                ("evidence", EvidenceAdapter),
                ("belief", BeliefAdapter),
                ("insights", InsightsAdapter),
                ("elo", EloAdapter),
                ("pulse", PulseAdapter),
                ("cost", CostAdapter),
                ("ranking", RankingAdapter),
                ("culture", CultureAdapter),
            ]

            return {
                "healthy": True,
                "status": "available",
                "adapters_available": len(adapter_classes),
                "adapter_list": [name for name, _ in adapter_classes],
            }
        except ImportError as e:
            logger.debug("Some KM adapters not available: %s", e)
            return {
                "healthy": True,
                "status": "partial",
                "error": "Some adapters not available",
            }
        except (AttributeError, TypeError, RuntimeError) as e:
            logger.debug("KM adapters check error: %s: %s", type(e).__name__, e)
            return {
                "healthy": True,
                "status": "error",
                "error": "Health check failed",
            }

    def _check_control_plane_adapter(self) -> dict[str, Any]:
        """Check Control Plane adapter."""
        try:
            from aragora.knowledge.mound.adapters.control_plane_adapter import (  # noqa: F401
                ControlPlaneAdapter,
                TaskOutcome,
                AgentCapabilityRecord,
                CrossWorkspaceInsight,
            )

            return {
                "healthy": True,
                "status": "available",
                "features": [
                    "task_outcome_storage",
                    "capability_records",
                    "cross_workspace_insights",
                    "agent_recommendations",
                ],
            }
        except ImportError as e:
            logger.debug("Control plane adapter not available: %s", e)
            return {
                "healthy": True,
                "status": "not_available",
                "error": "Module not available",
            }
        except (AttributeError, TypeError, RuntimeError) as e:
            logger.debug("Control plane adapter check error: %s: %s", type(e).__name__, e)
            return {
                "healthy": True,
                "status": "error",
                "error": "Health check failed",
            }

    def _check_km_metrics(self) -> dict[str, Any]:
        """Check KM metrics availability."""
        try:
            from aragora.observability.metrics.km import (  # noqa: F401
                init_km_metrics,
                record_km_operation,
                record_cp_task_outcome,
            )

            return {
                "healthy": True,
                "status": "available",
                "prometheus_integration": True,
            }
        except ImportError:
            return {
                "healthy": True,
                "status": "not_available",
                "prometheus_integration": False,
            }
        except (AttributeError, TypeError, RuntimeError) as e:
            logger.debug("KM metrics check error: %s: %s", type(e).__name__, e)
            return {
                "healthy": True,
                "status": "error",
                "error": "Health check failed",
            }

    def _check_confidence_decay(self) -> dict[str, Any]:
        """Check Confidence Decay Scheduler status.

        Returns:
            Dict with 'component' (health status) and 'warnings' (list of warnings)
        """
        warnings: list[str] = []
        try:
            from aragora.knowledge.mound.confidence_decay_scheduler import (
                get_decay_scheduler,
            )

            scheduler = get_decay_scheduler()
            if scheduler:
                stats = scheduler.get_stats()
                component = {
                    "healthy": True,
                    "status": "active" if scheduler.is_running else "stopped",
                    "running": scheduler.is_running,
                    "decay_interval_hours": stats.get("decay_interval_hours", 24),
                    "total_cycles": stats.get("total_decay_cycles", 0),
                    "total_items_processed": stats.get("total_items_processed", 0),
                    "last_run": stats.get("last_run", {}),
                    "workspaces_monitored": stats.get("workspaces"),
                }
                # Add alerting info
                if scheduler.is_running:
                    last_runs = stats.get("last_run", {})
                    if last_runs:
                        # Check if any workspace hasn't been processed in >48 hours
                        now = datetime.now()
                        stale_workspaces = []
                        for ws_id, run_time_str in last_runs.items():
                            try:
                                run_time = datetime.fromisoformat(run_time_str)
                                hours_since = (now - run_time).total_seconds() / 3600
                                if hours_since > 48:
                                    stale_workspaces.append(ws_id)
                            except (ValueError, TypeError):
                                logger.debug(
                                    "Invalid run time format for workspace %s: %s",
                                    ws_id,
                                    run_time_str,
                                )
                        if stale_workspaces:
                            component["alert"] = {
                                "level": "warning",
                                "message": f"Decay not run in >48h for: {', '.join(stale_workspaces)}",
                            }
                            warnings.append(
                                f"Confidence decay stale for workspaces: {stale_workspaces}"
                            )
                return {"component": component, "warnings": warnings}
            else:
                return {
                    "component": {
                        "healthy": True,
                        "status": "not_configured",
                        "note": "Confidence decay scheduler not initialized",
                    },
                    "warnings": warnings,
                }
        except ImportError:
            return {
                "component": {
                    "healthy": True,
                    "status": "not_available",
                    "note": "Confidence decay module not installed",
                },
                "warnings": warnings,
            }
        except (AttributeError, TypeError, KeyError, RuntimeError, ValueError) as e:
            logger.debug("Confidence decay check error: %s: %s", type(e).__name__, e)
            return {
                "component": {
                    "healthy": True,
                    "status": "error",
                    "error": "Health check failed",
                },
                "warnings": warnings,
            }


__all__ = ["KnowledgeMixin"]
