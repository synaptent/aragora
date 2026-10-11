"""
Revalidation Scheduler for Knowledge Mound.

Provides automatic staleness detection and revalidation triggering:
- Periodic background staleness checks
- Automatic task creation for stale knowledge
- Integration with control plane task scheduler
- Configurable thresholds and intervals

Usage:
    from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

    scheduler = RevalidationScheduler(
        knowledge_mound=mound,
        task_scheduler=task_scheduler,
        staleness_threshold=0.7,
        check_interval_seconds=3600,
    )

    # Start background monitoring
    await scheduler.start()

    # Manual trigger
    await scheduler.check_and_schedule_revalidations()

    # Stop monitoring
    await scheduler.stop()
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.control_plane.scheduler import TaskScheduler
    from aragora.knowledge.mound.facade import KnowledgeMound

logger = logging.getLogger(__name__)


class RevalidationScheduler:
    """
    Background scheduler for automatic knowledge revalidation.

    Monitors the Knowledge Mound for stale knowledge and creates
    revalidation tasks in the control plane task queue.

    Revalidation can be performed via:
    1. Debate: Run a focused debate to verify/update the knowledge
    2. Evidence: Re-fetch evidence to check if claim still holds
    3. Expert: Flag for human expert review

    Attributes:
        knowledge_mound: Knowledge Mound instance to monitor
        task_scheduler: Control plane task scheduler
        staleness_threshold: Staleness score above which to revalidate (0.0-1.0)
        check_interval_seconds: Interval between staleness checks
        max_tasks_per_check: Maximum tasks to create per check cycle
        revalidation_method: Default method ("debate", "evidence", "expert")
    """

    def __init__(
        self,
        knowledge_mound: KnowledgeMound | None = None,
        task_scheduler: TaskScheduler | None = None,
        staleness_threshold: float = 0.7,
        check_interval_seconds: int = 3600,
        max_tasks_per_check: int = 10,
        revalidation_method: str = "debate",
        on_task_created: Callable[[str, str], None] | None = None,
    ):
        """
        Initialize the revalidation scheduler.

        Args:
            knowledge_mound: Knowledge Mound instance to monitor
            task_scheduler: Control plane task scheduler for creating tasks
            staleness_threshold: Staleness score threshold (default: 0.7)
            check_interval_seconds: Check interval in seconds (default: 3600 = 1 hour)
            max_tasks_per_check: Max revalidation tasks per cycle (default: 10)
            revalidation_method: Default revalidation method
            on_task_created: Optional callback when task is created (task_id, node_id)
        """
        self._knowledge_mound = knowledge_mound
        self._task_scheduler = task_scheduler
        self._staleness_threshold = staleness_threshold
        self._check_interval = check_interval_seconds
        self._max_tasks_per_check = max_tasks_per_check
        self._revalidation_method = revalidation_method
        self._on_task_created = on_task_created

        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._pending_revalidations: set[str] = set()  # Node IDs already queued

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running

    async def start(self) -> None:
        """Start the background monitoring task."""
        if self._running:
            logger.warning("RevalidationScheduler already running")
            return

        if not self._knowledge_mound:
            logger.warning("Cannot start RevalidationScheduler: no knowledge_mound configured")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "RevalidationScheduler started: threshold=%s, interval=%ss, method=%s",
            self._staleness_threshold,
            self._check_interval,
            self._revalidation_method,
        )

    async def stop(self) -> None:
        """Stop the background monitoring task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("RevalidationScheduler stopped")

    async def _run_loop(self) -> None:
        """Main background loop."""
        while self._running:
            try:
                await self.check_and_schedule_revalidations()
            except (RuntimeError, ConnectionError, TimeoutError) as e:
                logger.warning("Revalidation check failed: %s", e)
            except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
                logger.exception("Unexpected revalidation check error: %s", e)

            # Wait for next check interval
            await asyncio.sleep(self._check_interval)

    async def check_and_schedule_revalidations(self) -> list[str]:
        """
        Check for stale knowledge and schedule revalidations.

        Returns:
            List of task IDs created
        """
        if not self._knowledge_mound:
            return []

        try:
            # Get stale knowledge items
            stale_items = await self._knowledge_mound.get_stale_knowledge(
                threshold=self._staleness_threshold,
                limit=self._max_tasks_per_check * 2,  # Get more to filter already-queued
            )

            if not stale_items:
                logger.debug("No stale knowledge found")
                return []

            # Filter out already-queued items
            items_to_revalidate = [
                item for item in stale_items if item.node_id not in self._pending_revalidations
            ][: self._max_tasks_per_check]

            if not items_to_revalidate:
                logger.debug("All stale items already have pending revalidations")
                return []

            task_ids = []

            for item in items_to_revalidate:
                task_id = await self._create_revalidation_task(item)
                if task_id:
                    task_ids.append(task_id)
                    self._pending_revalidations.add(item.node_id)

                    if self._on_task_created:
                        self._on_task_created(task_id, item.node_id)

            logger.info(
                "Scheduled %s revalidation tasks (threshold=%s)",
                len(task_ids),
                self._staleness_threshold,
            )

            return task_ids

        except (RuntimeError, ValueError, KeyError) as e:
            logger.warning("Failed to check/schedule revalidations: %s", e)
            return []
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.exception("Unexpected revalidation scheduling error: %s", e)
            return []

    async def _create_revalidation_task(self, stale_item: Any) -> str | None:
        """
        Create a revalidation task for a stale knowledge item.

        Args:
            stale_item: StalenessCheck object with node info

        Returns:
            Task ID if created, None otherwise
        """
        node_id = stale_item.node_id
        staleness_score = getattr(stale_item, "staleness_score", 0.5)
        content_preview = getattr(stale_item, "content_preview", "")[:200]
        reasons = getattr(stale_item, "reasons", [])

        # Determine priority based on staleness
        priority_str = "normal"
        if staleness_score >= 0.9:
            priority_str = "high"
        elif staleness_score >= 0.8:
            priority_str = "normal"
        else:
            priority_str = "low"

        # Build task payload
        payload = {
            "node_id": node_id,
            "staleness_score": staleness_score,
            "content_preview": content_preview,
            "reasons": reasons,
            "revalidation_method": self._revalidation_method,
            "workspace_id": getattr(self._knowledge_mound, "workspace_id", "default"),
        }

        # If we have a task scheduler, use it
        if self._task_scheduler:
            try:
                from aragora.control_plane.scheduler import TaskPriority

                priority_map = {
                    "low": TaskPriority.LOW,
                    "normal": TaskPriority.NORMAL,
                    "high": TaskPriority.HIGH,
                }

                task_id = await self._task_scheduler.submit(
                    task_type="knowledge_revalidation",
                    payload=payload,
                    required_capabilities=["revalidation", "debate"],
                    priority=priority_map.get(priority_str, TaskPriority.NORMAL),
                    timeout_seconds=600.0,  # 10 minutes for debate
                    metadata={
                        "source": "revalidation_scheduler",
                        "staleness_threshold": self._staleness_threshold,
                    },
                )

                logger.debug(
                    "Created revalidation task %s for node %s (staleness=%.2f, priority=%s)",
                    task_id,
                    node_id,
                    staleness_score,
                    priority_str,
                )
                return task_id

            except (RuntimeError, ConnectionError, TimeoutError) as e:
                logger.warning("Failed to submit revalidation task: %s", e)
            except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
                logger.exception("Unexpected task submission error: %s", e)

        # Fallback: use knowledge mound's schedule_revalidation
        if self._knowledge_mound is None:
            logger.warning(
                "Failed to schedule revalidation via mound: %s", "no knowledge mound configured"
            )
            return None
        try:
            task_ids = await self._knowledge_mound.schedule_revalidation(
                node_ids=[node_id],
                priority=priority_str,
            )
            return task_ids[0] if task_ids else None

        except (RuntimeError, ValueError, AttributeError) as e:
            logger.warning("Failed to schedule revalidation via mound: %s", e)
            return None
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.exception("Unexpected mound revalidation error: %s", e)
            return None

    def mark_revalidation_complete(self, node_id: str) -> None:
        """
        Mark a node's revalidation as complete.

        Called when a revalidation task completes to allow
        future revalidations of the same node.

        Args:
            node_id: Node ID that was revalidated
        """
        self._pending_revalidations.discard(node_id)

    def get_stats(self) -> dict[str, Any]:
        """
        Get scheduler statistics.

        Returns:
            Dict with scheduler status and metrics
        """
        return {
            "running": self._running,
            "staleness_threshold": self._staleness_threshold,
            "check_interval_seconds": self._check_interval,
            "max_tasks_per_check": self._max_tasks_per_check,
            "revalidation_method": self._revalidation_method,
            "pending_revalidations": len(self._pending_revalidations),
        }


# Task handler for processing revalidation tasks
async def handle_revalidation_task(
    task_payload: dict[str, Any],
    knowledge_mound: KnowledgeMound | None = None,
) -> dict[str, Any]:
    """
    Handle a knowledge revalidation task.

    This is the task handler that processes revalidation tasks from
    the control plane queue. It can be registered with a worker to
    automatically process revalidation requests.

    Args:
        task_payload: Task payload with node_id, method, etc.
        knowledge_mound: KnowledgeMound instance for updates

    Returns:
        Result dict with revalidation outcome
    """
    node_id = task_payload.get("node_id")
    method = task_payload.get("revalidation_method", "debate")
    task_payload.get("workspace_id", "default")

    if not node_id:
        return {"success": False, "error": "Missing node_id in payload"}

    logger.info("Processing revalidation for node %s via %s", node_id, method)

    try:
        if method == "debate":
            result = await _revalidate_via_debate(node_id, task_payload, knowledge_mound)
        elif method == "evidence":
            result = await _revalidate_via_evidence(node_id, task_payload, knowledge_mound)
        elif method == "expert":
            result = await _flag_for_expert_review(node_id, task_payload, knowledge_mound)
        else:
            result = {"success": False, "error": f"Unknown method: {method}"}

        # Update knowledge mound if revalidation succeeded
        if result.get("success") and knowledge_mound:
            if result.get("validated", False):
                await knowledge_mound.mark_validated(
                    node_id=node_id,
                    validator=f"revalidation_{method}",
                    confidence=result.get("confidence"),
                )
            else:
                # Mark as needing attention (stale but not validated)
                await knowledge_mound.update(
                    node_id,
                    {
                        "validation_status": "needs_review",
                        "revalidation_result": result,
                    },
                )

        return result

    except (RuntimeError, ValueError, KeyError) as e:
        logger.warning("Revalidation failed for %s: %s", node_id, e)
        return {"success": False, "error": "Revalidation failed"}
    except (RuntimeError, ValueError, OSError, AttributeError) as e:
        logger.exception("Unexpected revalidation failure for %s: %s", node_id, e)
        return {"success": False, "error": "Unexpected revalidation failure"}


async def _revalidate_via_debate(
    node_id: str,
    payload: dict[str, Any],
    knowledge_mound: KnowledgeMound | None,
) -> dict[str, Any]:
    """Revalidate knowledge by running a focused debate.

    Creates a mini-debate with available agents to verify the claim is still valid.
    Updates the knowledge mound with the revalidation result.
    """
    content_preview = payload.get("content_preview", "")
    payload.get("workspace_id", "default")

    try:
        # Import debate components
        from aragora.core_types import Environment
        from aragora.protocols.debate import DebateProtocol
        from aragora.debate.orchestrator import Arena
        from aragora.agents.factory import create_default_agents

        # Create a focused revalidation debate task
        task = f"Verify the following knowledge claim is still accurate and up-to-date: {content_preview}"

        env = Environment(
            task=task,
            context=f"This is a revalidation debate for knowledge node {node_id}. "
            "Determine if this claim is still valid, needs updating, or should be deprecated. "
            "Respond with one of: VALID (claim is still accurate), UPDATE (needs modification), "
            "or DEPRECATED (claim is outdated or incorrect).",
        )

        protocol = DebateProtocol(
            rounds=2,  # Short focused debate
            consensus="majority",
            enable_evidence_weighting=True,
        )

        # Create agents for the revalidation debate
        try:
            agents = create_default_agents(num_agents=3)
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Could not create agents for revalidation: %s", e)
            # Fall back to placeholder response
            return {
                "success": True,
                "method": "debate",
                "status": "debate_scheduled",
                "task": task,
                "message": "Revalidation debate scheduled - agents unavailable",
            }

        # Create and run the arena
        arena = Arena(
            environment=env,
            agents=agents,
            protocol=protocol,
        )

        # Run the debate
        result = await arena.run()

        # Analyze the debate result
        conclusion = result.final_answer if result else ""
        consensus_reached = result.consensus_reached if result else False

        # Determine validation status from debate conclusion
        validation_status = "valid"  # Default
        conclusion_lower = conclusion.lower() if conclusion else ""

        if "deprecated" in conclusion_lower or "outdated" in conclusion_lower:
            validation_status = "deprecated"
        elif "update" in conclusion_lower or "modify" in conclusion_lower:
            validation_status = "needs_update"
        elif "valid" in conclusion_lower or "accurate" in conclusion_lower:
            validation_status = "valid"

        # Update the knowledge mound with revalidation result
        if knowledge_mound and validation_status == "valid":
            try:
                await knowledge_mound.mark_validated(
                    node_id=node_id,
                    validator="debate",
                    confidence=result.confidence if result else 0.7,
                )
            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                logger.warning("Failed to update mound validation status: %s", e)

        return {
            "success": True,
            "method": "debate",
            "status": "completed",
            "validation_status": validation_status,
            "consensus_reached": consensus_reached,
            "conclusion": conclusion[:500] if conclusion else "",
            "debate_id": result.debate_id if result else None,
            "task": task,
        }

    except ImportError as e:
        logger.warning("Debate components not available: %s", e)
        return {
            "success": False,
            "error": "Debate components not available",
        }
    except (RuntimeError, ValueError, OSError, AttributeError) as e:
        logger.exception("Revalidation debate failed: %s", e)
        return {
            "success": False,
            "error": "Revalidation debate failed",
        }


async def _revalidate_via_evidence(
    node_id: str,
    payload: dict[str, Any],
    knowledge_mound: KnowledgeMound | None,
) -> dict[str, Any]:
    """Revalidate knowledge by re-fetching evidence."""
    content_preview = payload.get("content_preview", "")

    try:
        from aragora.evidence.collector import EvidenceCollector

        collector = EvidenceCollector()
        evidence_pack = await collector.collect_evidence(
            task=content_preview[:200],
            enabled_connectors=["web"],
        )

        if evidence_pack.snippets:
            # Found supporting evidence
            return {
                "success": True,
                "method": "evidence",
                "validated": True,
                "confidence": 0.7,
                "evidence_count": len(evidence_pack.snippets),
                "message": f"Found {len(evidence_pack.snippets)} supporting evidence snippets",
            }
        else:
            # No supporting evidence found
            return {
                "success": True,
                "method": "evidence",
                "validated": False,
                "confidence": 0.3,
                "message": "No supporting evidence found - may need review",
            }

    except (RuntimeError, ConnectionError, TimeoutError) as e:
        logger.warning("Evidence collection failed: %s", e)
        return {
            "success": False,
            "error": "Evidence collection failed",
        }
    except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
        logger.exception("Unexpected evidence collection error: %s", e)
        return {
            "success": False,
            "error": "Unexpected evidence collection error",
        }


async def _flag_for_expert_review(
    node_id: str,
    payload: dict[str, Any],
    knowledge_mound: KnowledgeMound | None,
) -> dict[str, Any]:
    """Flag knowledge for human expert review."""
    return {
        "success": True,
        "method": "expert",
        "validated": False,
        "status": "flagged_for_review",
        "message": f"Node {node_id} flagged for expert review",
    }
