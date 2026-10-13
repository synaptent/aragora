"""Self-improvement transparency dashboard endpoints.

Endpoints:
- GET /api/self-improve/meta-planner/goals      - MetaPlanner prioritized goals
- GET /api/self-improve/execution/timeline       - Branch execution timeline
- GET /api/self-improve/learning/insights        - Cross-cycle learning data
- GET /api/self-improve/metrics/comparison       - Before/after codebase metrics
- POST /api/self-improve/improvement-queue       - User-submitted improvement goals
- PUT /api/self-improve/improvement-queue/{id}/priority - Reorder queue items
- DELETE /api/self-improve/improvement-queue/{id} - Remove queue items

These endpoints expose the internal state of the Nomic Loop self-improvement
system so the frontend dashboard can visualize what the system is doing,
why it chose specific goals, and how it learns over time.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    HandlerResult,
    error_response,
    json_response,
    handle_errors,
)
from ..secure import SecureHandler
from ..utils.auth_mixins import SecureEndpointMixin
from ..utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)


class SelfImproveDetailsHandler(SecureEndpointMixin, SecureHandler):  # type: ignore[misc]
    """Handler for self-improvement transparency dashboard.

    Exposes MetaPlanner goals, branch execution state, cross-cycle
    learning insights, and before/after metrics comparison.

    RBAC Permissions:
    - self_improve:read - View goals, timeline, insights, metrics
    """

    RESOURCE_TYPE = "self_improve"

    ROUTES = [
        "/api/self-improve/meta-planner/goals",
        "/api/self-improve/execution/timeline",
        "/api/self-improve/learning/insights",
        "/api/self-improve/metrics/comparison",
        "/api/self-improve/trends/cycles",
        "/api/self-improve/improvement-queue",
        "/api/self-improve/improvement-queue/{id}/priority",
        "/api/self-improve/improvement-queue/{id}",
    ]

    _ROUTE_MAP = {
        "GET /api/self-improve/meta-planner/goals": "_get_meta_planner_goals",
        "GET /api/self-improve/execution/timeline": "_get_execution_timeline",
        "GET /api/self-improve/learning/insights": "_get_learning_insights",
        "GET /api/self-improve/metrics/comparison": "_get_metrics_comparison",
        "GET /api/self-improve/trends/cycles": "_get_cycle_trends",
        "POST /api/self-improve/improvement-queue": "handle_post",
        "PUT /api/self-improve/improvement-queue/{id}/priority": "handle_put",
        "DELETE /api/self-improve/improvement-queue/{id}": "handle_delete",
    }

    # Prefix for PUT/DELETE on individual queue items
    _QUEUE_ITEM_PREFIX = "/api/self-improve/improvement-queue/"
    ROUTE_PREFIXES = [_QUEUE_ITEM_PREFIX]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can handle the given path."""
        path = strip_version_prefix(path)
        if path in self.ROUTES:
            return True
        if path.startswith(self._QUEUE_ITEM_PREFIX):
            return True
        return False

    @rate_limit(requests_per_minute=30)
    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route GET requests to the appropriate endpoint."""
        path = strip_version_prefix(path)

        handlers = {
            "/api/self-improve/meta-planner/goals": self._get_meta_planner_goals,
            "/api/self-improve/execution/timeline": self._get_execution_timeline,
            "/api/self-improve/learning/insights": self._get_learning_insights,
            "/api/self-improve/metrics/comparison": self._get_metrics_comparison,
            "/api/self-improve/trends/cycles": self._get_cycle_trends,
        }

        endpoint_handler = handlers.get(path)
        if endpoint_handler:
            return await endpoint_handler()

        return None

    async def _get_meta_planner_goals(self) -> HandlerResult:
        """Get MetaPlanner prioritized goals with reasoning.

        Instantiates MetaPlanner in scan_mode (no LLM calls) to get
        current prioritized goals derived from codebase signals.

        Returns:
            {"data": {"goals": [...], "signals_used": [...], "config": {...}}}
        """
        try:
            from aragora.nomic.meta_planner import (
                MetaPlanner,
                MetaPlannerConfig,
                PrioritizedGoal,
            )

            config = MetaPlannerConfig(
                scan_mode=True,
                quick_mode=False,
                max_goals=10,
                enable_metrics_collection=False,
                enable_cross_cycle_learning=False,
            )
            planner = MetaPlanner(config)

            goals: list[PrioritizedGoal] = await planner.prioritize_work(
                objective=None,
            )

            goals_data = []
            for g in goals:
                goals_data.append(
                    {
                        "id": g.id,
                        "track": g.track.value,
                        "description": g.description,
                        "rationale": g.rationale,
                        "estimated_impact": g.estimated_impact,
                        "priority": g.priority,
                        "focus_areas": g.focus_areas,
                        "file_hints": g.file_hints[:10],
                    }
                )

            # Collect signal types from goal descriptions
            signals_used = set()
            for g in goals:
                desc = g.description.lower()
                for signal in [
                    "recent_change",
                    "untested",
                    "regression",
                    "test_failure",
                    "lint",
                    "todo",
                    "low_nps",
                    "feedback_queue",
                    "strategic",
                    "pipeline_goal",
                    "feedback_goal",
                ]:
                    if signal in desc:
                        signals_used.add(signal)

            # Include ImprovementQueue state for transparency
            queue_data: dict[str, Any] = {"size": 0, "items": []}
            try:
                from aragora.nomic.improvement_queue import get_improvement_queue

                queue = get_improvement_queue()
                queue_data["size"] = len(queue)
                for s in queue.peek(5):
                    queue_data["items"].append(
                        {
                            "task": s.task[:200],
                            "category": s.category,
                            "confidence": s.confidence,
                            "debate_id": s.debate_id,
                        }
                    )
            except (ImportError, RuntimeError):
                pass

            return json_response(
                {
                    "data": {
                        "goals": goals_data,
                        "signals_used": sorted(signals_used),
                        "improvement_queue": queue_data,
                        "config": {
                            "scan_mode": config.scan_mode,
                            "max_goals": config.max_goals,
                        },
                    }
                }
            )

        except ImportError:
            logger.debug("MetaPlanner not available")
            return json_response(
                {
                    "data": {
                        "goals": [],
                        "signals_used": [],
                        "config": {},
                        "error": "MetaPlanner module not available",
                    }
                }
            )
        except (RuntimeError, ValueError, OSError) as exc:
            logger.warning("Failed to get meta-planner goals: %s", exc)
            return json_response(
                {
                    "data": {
                        "goals": [],
                        "signals_used": [],
                        "config": {},
                        "error": "Failed to generate goals",
                    }
                }
            )

    async def _get_execution_timeline(self) -> HandlerResult:
        """Get active branches and execution status.

        Queries BranchCoordinator for worktree state and recent
        merge decisions.

        Returns:
            {"data": {"branches": [...], "merge_decisions": [...], "active_count": N}}
        """
        branches_data: list[dict[str, Any]] = []
        merge_decisions: list[dict[str, Any]] = []

        # Get worktree info from BranchCoordinator
        try:
            from aragora.nomic.branch_coordinator import BranchCoordinator

            coordinator = BranchCoordinator()
            worktrees = coordinator.list_worktrees()

            for wt in worktrees:
                branches_data.append(
                    {
                        "branch_name": wt.branch_name,
                        "worktree_path": str(wt.worktree_path),
                        "track": wt.track,
                        "created_at": wt.created_at.isoformat() if wt.created_at else None,
                        "assignment_id": wt.assignment_id,
                        "status": "active",
                    }
                )

        except ImportError:
            logger.debug("BranchCoordinator not available")
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("Failed to list worktrees: %s", exc)

        # Get recent cycle records for merge decisions
        try:
            from aragora.nomic.cycle_store import get_cycle_store

            store = get_cycle_store()
            recent_cycles = store.get_recent_cycles(n=20)

            for cycle in recent_cycles:
                cycle_data = cycle if isinstance(cycle, dict) else getattr(cycle, "__dict__", {})
                cycle_id = cycle_data.get("cycle_id", "")
                status = cycle_data.get("status", "unknown")
                started_at = cycle_data.get("started_at")
                completed_at = cycle_data.get("completed_at")

                merge_decisions.append(
                    {
                        "cycle_id": cycle_id,
                        "status": status,
                        "started_at": started_at,
                        "completed_at": completed_at,
                        "success": cycle_data.get("success", False),
                    }
                )

        except ImportError:
            logger.debug("CycleStore not available")
        except (RuntimeError, ValueError, OSError, AttributeError) as exc:
            logger.debug("Failed to get cycle records: %s", exc)

        # Get run state from self-improve handler's active tasks
        try:
            from .self_improve import _active_tasks

            for run_id, task in _active_tasks.items():
                if not task.done():
                    branches_data.append(
                        {
                            "branch_name": f"run/{run_id[:12]}",
                            "worktree_path": None,
                            "track": None,
                            "created_at": None,
                            "assignment_id": run_id,
                            "status": "running",
                        }
                    )
        except ImportError:
            pass

        active_count = sum(1 for b in branches_data if b.get("status") in ("active", "running"))

        return json_response(
            {
                "data": {
                    "branches": branches_data,
                    "merge_decisions": merge_decisions,
                    "active_count": active_count,
                }
            }
        )

    async def _get_learning_insights(self) -> HandlerResult:
        """Get cross-cycle learning data.

        Queries the NomicCycleAdapter for high-ROI patterns,
        recurring failures, and historical learnings.

        Returns:
            {"data": {"insights": [...], "high_roi_patterns": [...], "recurring_failures": [...]}}
        """
        insights: list[dict[str, Any]] = []
        high_roi_patterns: list[dict[str, Any]] = []
        recurring_failures: list[dict[str, Any]] = []

        # Query Knowledge Mound for cross-cycle learning
        try:
            from aragora.knowledge.mound.adapters.nomic_cycle_adapter import (
                get_nomic_cycle_adapter,
            )

            adapter = get_nomic_cycle_adapter()

            # High-ROI goal types
            try:
                roi_data = await adapter.find_high_roi_goal_types(limit=10)
                for entry in roi_data:
                    high_roi_patterns.append(
                        {
                            "pattern": entry.get("pattern", ""),
                            "avg_improvement_score": entry.get("avg_improvement_score", 0),
                            "cycle_count": entry.get("cycle_count", 0),
                        }
                    )
            except (RuntimeError, ValueError, OSError, AttributeError) as exc:
                logger.debug("High-ROI query failed: %s", exc)

            # Recurring failures
            try:
                failure_data = await adapter.find_recurring_failures(min_occurrences=2, limit=10)
                for entry in failure_data:
                    recurring_failures.append(
                        {
                            "pattern": entry.get("pattern", ""),
                            "occurrences": entry.get("occurrences", 0),
                            "affected_tracks": entry.get("affected_tracks", []),
                        }
                    )
            except (RuntimeError, ValueError, OSError, AttributeError) as exc:
                logger.debug("Recurring failures query failed: %s", exc)

        except ImportError:
            logger.debug("NomicCycleAdapter not available")
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("Failed to query KM learning data: %s", exc)

        # Query outcome tracker for regression history as insights
        try:
            from aragora.nomic.outcome_tracker import NomicOutcomeTracker

            regressions = NomicOutcomeTracker.get_regression_history(limit=10)
            for reg in regressions:
                insights.append(
                    {
                        "type": "regression",
                        "cycle_id": reg.get("cycle_id", ""),
                        "regressed_metrics": reg.get("regressed_metrics", []),
                        "recommendation": reg.get("recommendation", ""),
                    }
                )
        except ImportError:
            logger.debug("OutcomeTracker not available")
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("Failed to get regression history: %s", exc)

        # Query strategic memory for recurring findings
        try:
            from aragora.nomic.strategic_memory import StrategicMemoryStore

            sm_store = StrategicMemoryStore()
            recurring = sm_store.get_recurring_findings(min_occurrences=2)
            for finding in recurring[:10]:
                insights.append(
                    {
                        "type": "strategic_finding",
                        "category": finding.category,
                        "description": finding.description[:200],
                        "occurrences": getattr(finding, "occurrences", 0),
                    }
                )
        except ImportError:
            pass
        except (RuntimeError, ValueError, OSError, AttributeError) as exc:
            logger.debug("Strategic memory query failed: %s", exc)

        return json_response(
            {
                "data": {
                    "insights": insights,
                    "high_roi_patterns": high_roi_patterns,
                    "recurring_failures": recurring_failures,
                }
            }
        )

    async def _get_metrics_comparison(self) -> HandlerResult:
        """Get before/after codebase metrics from recent cycles.

        Queries OutcomeTracker for the most recent outcome comparisons
        showing which metrics improved or regressed.

        Returns:
            {"data": {"comparisons": [...], "regressions": [...]}}
        """
        comparisons: list[dict[str, Any]] = []
        regressions: list[dict[str, Any]] = []

        # Get outcome comparisons from tracker
        try:
            from aragora.nomic.outcome_tracker import NomicOutcomeTracker

            # Get regression history (includes metric deltas)
            reg_history = NomicOutcomeTracker.get_regression_history(limit=10)
            for reg in reg_history:
                regressions.append(
                    {
                        "cycle_id": reg.get("cycle_id", ""),
                        "regressed_metrics": reg.get("regressed_metrics", []),
                        "recommendation": reg.get("recommendation", ""),
                        "timestamp": reg.get("timestamp"),
                    }
                )
        except ImportError:
            logger.debug("OutcomeTracker not available")
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("Failed to get outcome comparisons: %s", exc)

        # Get recent cycle records with metrics
        try:
            from aragora.nomic.cycle_store import get_cycle_store

            store = get_cycle_store()
            recent = store.get_recent_cycles(n=10)

            for cycle in recent:
                cycle_data = cycle if isinstance(cycle, dict) else getattr(cycle, "__dict__", {})
                scores = cycle_data.get("evidence_quality_scores", {})
                if scores:
                    comparisons.append(
                        {
                            "cycle_id": cycle_data.get("cycle_id", ""),
                            "metrics": scores,
                            "success": cycle_data.get("success", False),
                            "timestamp": cycle_data.get("started_at"),
                        }
                    )
        except ImportError:
            logger.debug("CycleStore not available")
        except (RuntimeError, ValueError, OSError, AttributeError) as exc:
            logger.debug("Failed to get cycle metrics: %s", exc)

        # Get codebase metrics snapshot if available
        try:
            from aragora.nomic.metrics_collector import MetricsCollector, MetricsCollectorConfig

            config = MetricsCollectorConfig(
                test_timeout=30,
                test_args=["--co", "-q"],  # Collect-only for speed
            )
            collector = MetricsCollector(config)
            from aragora.nomic.metrics_collector import MetricSnapshot
            import time as _time

            snapshot = MetricSnapshot(timestamp=_time.time())
            try:
                collector._collect_size_metrics(snapshot, None)
            except (OSError, ValueError):
                pass

            if snapshot.files_count > 0:
                comparisons.insert(
                    0,
                    {
                        "cycle_id": "current",
                        "metrics": {
                            "files_count": snapshot.files_count,
                            "total_lines": snapshot.total_lines,
                            "tests_passed": snapshot.tests_passed,
                            "lint_errors": snapshot.lint_errors,
                        },
                        "success": True,
                        "timestamp": snapshot.timestamp,
                    },
                )
        except ImportError:
            logger.debug("MetricsCollector not available")
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("Failed to collect current metrics: %s", exc)

        return json_response(
            {
                "data": {
                    "comparisons": comparisons,
                    "regressions": regressions,
                }
            }
        )

    # ------------------------------------------------------------------
    # Improvement Queue write endpoints
    # ------------------------------------------------------------------

    def _get_request_body(self, handler: Any) -> dict[str, Any]:
        """Extract JSON body from buffered or standard HTTP request handlers."""
        try:
            return self.read_json_body(handler) or {}
        except AttributeError:
            return {}

    @handle_errors("improvement queue add")
    async def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """POST /api/v1/self-improve/improvement-queue

        Add a user-submitted goal to the improvement queue.

        Body: {"goal": str, "priority": int, "source": "user"}
        """
        path = strip_version_prefix(path)
        if path != "/api/self-improve/improvement-queue":
            return None

        body = self._get_request_body(handler)
        goal = body.get("goal", "")
        if not goal:
            return error_response("Missing required field: goal", 400)

        priority = body.get("priority", 50)
        source = body.get("source", "user")

        try:
            from aragora.nomic.improvement_queue import (
                ImprovementSuggestion,
                get_improvement_queue,
            )

            suggestion = ImprovementSuggestion(
                debate_id=f"user-{uuid.uuid4().hex[:8]}",
                task=goal,
                suggestion=goal,
                category=source,
                confidence=min(max(priority / 100.0, 0.0), 1.0),
                created_at=time.time(),
            )
            queue = get_improvement_queue()
            queue.enqueue(suggestion)

            return json_response(
                {
                    "data": {
                        "id": suggestion.debate_id,
                        "goal": goal,
                        "priority": priority,
                        "source": source,
                        "status": "pending",
                        "createdAt": str(suggestion.created_at),
                    }
                },
                201,
            )
        except (ImportError, RuntimeError) as exc:
            logger.warning("Failed to add to improvement queue: %s", exc)
            return error_response("Improvement queue unavailable", 503)

    @handle_errors("improvement queue reorder")
    async def handle_put(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """PUT /api/v1/self-improve/improvement-queue/{id}/priority

        Update the priority of a queue item.

        Body: {"priority": int}
        """
        path = strip_version_prefix(path)
        if not path.startswith(self._QUEUE_ITEM_PREFIX):
            return None

        # Parse: /api/self-improve/improvement-queue/{id}/priority
        remainder = path[len(self._QUEUE_ITEM_PREFIX) :]
        if not remainder.endswith("/priority"):
            return None
        item_id = remainder[: -len("/priority")]
        if not item_id:
            return error_response("Missing queue item ID", 400)

        body = self._get_request_body(handler)
        new_priority = body.get("priority")
        if new_priority is None:
            return error_response("Missing required field: priority", 400)

        try:
            from aragora.nomic.improvement_queue import get_improvement_queue

            queue = get_improvement_queue()
            # Update confidence (used as priority proxy) on matching item
            found = False
            for s in queue.peek(queue.max_size):
                if s.debate_id == item_id:
                    s.confidence = min(max(new_priority / 100.0, 0.0), 1.0)
                    found = True
                    break

            if not found:
                return error_response(f"Queue item {item_id} not found", 404)

            return json_response(
                {
                    "data": {
                        "id": item_id,
                        "priority": new_priority,
                        "status": "updated",
                    }
                }
            )
        except (ImportError, RuntimeError) as exc:
            logger.warning("Failed to update queue priority: %s", exc)
            return error_response("Improvement queue unavailable", 503)

    @handle_errors("improvement queue remove")
    async def handle_delete(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """DELETE /api/v1/self-improve/improvement-queue/{id}

        Remove an item from the improvement queue.
        """
        path = strip_version_prefix(path)
        if not path.startswith(self._QUEUE_ITEM_PREFIX):
            return None

        item_id = path[len(self._QUEUE_ITEM_PREFIX) :]
        # Reject if there's a further sub-path (e.g. .../priority)
        if "/" in item_id or not item_id:
            return None

        try:
            from aragora.nomic.improvement_queue import get_improvement_queue

            queue = get_improvement_queue()
            # Remove matching item by rebuilding the queue
            with queue._lock:
                original_len = len(queue._queue)
                queue._queue = type(queue._queue)(
                    (s for s in queue._queue if s.debate_id != item_id),
                    maxlen=queue.max_size,
                )
                removed = len(queue._queue) < original_len

            if not removed:
                return error_response(f"Queue item {item_id} not found", 404)

            return json_response(
                {
                    "data": {
                        "id": item_id,
                        "status": "deleted",
                    }
                }
            )
        except (ImportError, RuntimeError) as exc:
            logger.warning("Failed to remove from improvement queue: %s", exc)
            return error_response("Improvement queue unavailable", 503)

    async def _get_cycle_trends(self) -> HandlerResult:
        """Get self-improvement cycle trends over time.

        Aggregates data from CycleLearningStore and SelfImproveRunStore
        to show success rate, duration, code churn, and cost trends.

        Returns:
            {"data": {"cycles": [...], "summary": {...}, "run_costs": [...]}}
        """
        cycles_data: list[dict[str, Any]] = []
        summary: dict[str, Any] = {
            "total_cycles": 0,
            "success_rate": 0.0,
            "avg_duration_seconds": 0.0,
            "total_lines_changed": 0,
            "avg_tests_passed": 0.0,
        }

        # Get cycle records from CycleLearningStore
        try:
            from aragora.nomic.cycle_store import get_cycle_store

            store = get_cycle_store()
            recent = store.get_recent_cycles(50)

            total_duration = 0.0
            total_success = 0
            total_tests = 0
            duration_count = 0

            for cycle in recent:
                cycle_entry: dict[str, Any] = {
                    "cycle_id": cycle.cycle_id,
                    "started_at": cycle.started_at,
                    "completed_at": cycle.completed_at,
                    "duration_seconds": cycle.duration_seconds,
                    "success": cycle.success,
                    "topics": cycle.topics_debated[:5],
                    "lines_added": cycle.lines_added,
                    "lines_removed": cycle.lines_removed,
                    "tests_passed": cycle.tests_passed,
                    "tests_failed": cycle.tests_failed,
                    "files_modified": len(cycle.files_modified),
                    "files_created": len(cycle.files_created),
                    "phases_completed": cycle.phases_completed,
                    "agent_count": len(cycle.agent_contributions),
                    "evidence_quality": cycle.evidence_quality_scores,
                }
                cycles_data.append(cycle_entry)

                if cycle.success:
                    total_success += 1
                if cycle.duration_seconds and cycle.duration_seconds > 0:
                    total_duration += cycle.duration_seconds
                    duration_count += 1
                summary["total_lines_changed"] += cycle.lines_added + cycle.lines_removed
                total_tests += cycle.tests_passed

            n = len(recent)
            summary["total_cycles"] = n
            if n > 0:
                summary["success_rate"] = round(total_success / n, 4)
                summary["avg_tests_passed"] = round(total_tests / n, 1)
            if duration_count > 0:
                summary["avg_duration_seconds"] = round(total_duration / duration_count, 1)

        except ImportError:
            logger.debug("CycleLearningStore not available")
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("Failed to get cycle trends: %s", exc)

        # Get cost data from SelfImproveRunStore
        run_costs: list[dict[str, Any]] = []
        try:
            from aragora.nomic.stores.run_store import SelfImproveRunStore

            run_store = SelfImproveRunStore()
            for run in run_store.list_runs(limit=50):
                if run.cost_usd > 0 or run.status.value in ("completed", "failed"):
                    run_costs.append(
                        {
                            "run_id": run.run_id,
                            "goal": run.goal[:200],
                            "status": run.status.value,
                            "cost_usd": run.cost_usd,
                            "created_at": run.created_at,
                            "completed_at": run.completed_at,
                            "subtasks_completed": run.completed_subtasks,
                            "subtasks_failed": run.failed_subtasks,
                        }
                    )
        except ImportError:
            logger.debug("SelfImproveRunStore not available")
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("Failed to get run costs: %s", exc)

        return json_response(
            {
                "data": {
                    "cycles": cycles_data,
                    "summary": summary,
                    "run_costs": run_costs,
                }
            }
        )
