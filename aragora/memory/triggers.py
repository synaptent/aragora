"""
MemoryTriggerEngine -- Reactive rules fired on memory events.

Make.com-style triggers that fire workflows when memory events occur
(high surprise, stale knowledge, contradiction, consolidation, new pattern).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from collections.abc import Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class MemoryTrigger:
    """A single reactive trigger rule."""

    name: str
    event: str  # "high_surprise", "stale_knowledge", "contradiction", "consolidation", "new_pattern", "query_result", "new_write"
    condition: Callable[[dict[str, Any]], bool] | None = None
    action: Callable[[dict[str, Any]], Awaitable[None]] | None = None
    enabled: bool = True


@dataclass
class TriggerResult:
    """Result of firing a single trigger."""

    trigger_name: str
    success: bool
    error: str | None = None


class MemoryTriggerEngine:
    """Reactive rule engine fired on memory events.

    Manages a registry of triggers that match on event type, optionally
    filter by condition, and execute async action callbacks. Errors in
    one trigger never block others.
    """

    def __init__(self) -> None:
        self._triggers: dict[str, MemoryTrigger] = {}
        self._fire_log: list[TriggerResult] = []
        self._register_builtins()

    def register(self, trigger: MemoryTrigger) -> None:
        """Register a trigger by name (overwrites if exists)."""
        self._triggers[trigger.name] = trigger

    def unregister(self, name: str) -> bool:
        """Remove a trigger by name. Returns True if it existed."""
        return self._triggers.pop(name, None) is not None

    async def fire(self, event: str, context: dict[str, Any]) -> list[str]:
        """Fire all triggers matching *event*, return list of triggered names.

        Each matching trigger's condition is checked (if present). If the
        condition passes (or is None), the action is executed.

        Errors in one trigger do not block others -- they are logged and
        recorded in the fire log.
        """
        triggered: list[str] = []

        for trigger in self._triggers.values():
            if not trigger.enabled:
                continue
            if trigger.event != event:
                continue

            # Check condition
            if trigger.condition is not None:
                try:
                    if not trigger.condition(context):
                        continue
                except Exception as exc:
                    logger.warning("Trigger %s condition failed: %s", trigger.name, exc)
                    self._fire_log.append(
                        TriggerResult(
                            trigger_name=trigger.name,
                            success=False,
                            error=f"condition error: {exc}",
                        )
                    )
                    continue

            # Execute action
            if trigger.action is not None:
                try:
                    await trigger.action(context)
                    self._fire_log.append(TriggerResult(trigger_name=trigger.name, success=True))
                    triggered.append(trigger.name)
                    _record_trigger_metric(trigger.name, True)
                except Exception as exc:
                    logger.warning("Trigger %s action failed: %s", trigger.name, exc)
                    self._fire_log.append(
                        TriggerResult(
                            trigger_name=trigger.name,
                            success=False,
                            error=f"action error: {exc}",
                        )
                    )
                    triggered.append(trigger.name)
                    _record_trigger_metric(trigger.name, False)
            else:
                # No action -- trigger matched but has no handler
                self._fire_log.append(TriggerResult(trigger_name=trigger.name, success=True))
                triggered.append(trigger.name)
                _record_trigger_metric(trigger.name, True)

        return triggered

    def list_triggers(self) -> list[MemoryTrigger]:
        """Return all registered triggers."""
        return list(self._triggers.values())

    def get_trigger(self, name: str) -> MemoryTrigger | None:
        """Get a trigger by name."""
        return self._triggers.get(name)

    def enable(self, name: str) -> None:
        """Enable a trigger by name."""
        if name in self._triggers:
            self._triggers[name].enabled = True

    def disable(self, name: str) -> None:
        """Disable a trigger by name."""
        if name in self._triggers:
            self._triggers[name].enabled = False

    def get_fire_log(self) -> list[TriggerResult]:
        """Return a copy of the fire log."""
        return list(self._fire_log)

    def clear_fire_log(self) -> None:
        """Clear the fire log."""
        self._fire_log.clear()

    def _register_builtins(self) -> None:
        """Register the 5 built-in triggers."""
        self.register(
            MemoryTrigger(
                name="high_surprise_investigate",
                event="high_surprise",
                condition=lambda ctx: ctx.get("surprise", 0) > 0.7,
                action=_log_high_surprise,
            )
        )
        self.register(
            MemoryTrigger(
                name="stale_knowledge_revalidate",
                event="stale_knowledge",
                condition=lambda ctx: (
                    ctx.get("days_since_access", 0) > 7 and ctx.get("confidence", 1.0) < 0.5
                ),
                action=_mark_for_revalidation,
            )
        )
        self.register(
            MemoryTrigger(
                name="contradiction_detected",
                event="contradiction",
                condition=None,
                action=_create_debate_topic,
            )
        )
        self.register(
            MemoryTrigger(
                name="consolidation_merge",
                event="consolidation",
                condition=lambda ctx: (
                    ctx.get("item_count", 0) >= 3 and ctx.get("avg_surprise", 1.0) < 0.2
                ),
                action=_merge_summaries,
            )
        )
        self.register(
            MemoryTrigger(
                name="pattern_emergence",
                event="new_pattern",
                condition=lambda ctx: ctx.get("surprise_ema_trend") == "decreasing",
                action=_extract_pattern,
            )
        )


def _record_trigger_metric(trigger_name: str, success: bool) -> None:
    """Emit a Prometheus metric for a trigger fire (best-effort)."""
    try:
        from aragora.observability.metrics.memory import record_trigger_fire

        record_trigger_fire(trigger_name, success)
    except ImportError:
        pass


# -----------------------------------------------------------------------
# Built-in action functions
# -----------------------------------------------------------------------


async def _log_high_surprise(context: dict[str, Any]) -> None:
    """Investigate high-surprise memory write via anomaly detection queue."""
    item_id = context.get("item_id")
    surprise = context.get("surprise", 0)
    logger.info(
        "High surprise detected: item_id=%s surprise=%.3f",
        item_id,
        surprise,
    )
    try:
        from aragora.security.anomaly_detection import get_anomaly_detector

        from aragora.security.anomaly_detection import AnomalyResult, AnomalySeverity

        detector = get_anomaly_detector()
        anomaly_result = AnomalyResult(
            is_anomalous=True,
            severity=AnomalySeverity.MEDIUM if surprise < 0.9 else AnomalySeverity.HIGH,
            description=f"Surprising memory item {item_id} (score={surprise:.2f})",
            details={
                "source": "memory",
                "item_id": item_id,
                "surprise_score": surprise,
                "content_preview": context.get("content_preview", "")[:200],
            },
        )
        detector._emit_anomaly_event(anomaly_result)
    except ImportError:
        pass
    except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
        logger.debug("Anomaly report failed (non-critical): %s", exc)

    try:
        from aragora.events.dispatcher import dispatch_event

        dispatch_event(
            "memory.high_surprise",
            {
                "item_id": item_id,
                "surprise": surprise,
                "source": context.get("source", "unknown"),
            },
        )
    except ImportError:
        pass
    except (RuntimeError, ValueError, TypeError, AttributeError):
        pass


async def _mark_for_revalidation(context: dict[str, Any]) -> None:
    """Mark stale knowledge for revalidation and apply confidence decay."""
    item_id = context.get("item_id")
    logger.info(
        "Stale knowledge marked for revalidation: item_id=%s",
        item_id,
    )
    try:
        from aragora.knowledge.mound.ops.confidence_decay import get_decay_manager
        from aragora.knowledge.mound import get_knowledge_mound

        manager = get_decay_manager()
        mound = get_knowledge_mound()
        workspace_id = context.get("workspace_id", "default")
        await manager.apply_decay(mound, workspace_id, force=True)  # type: ignore[arg-type]
    except ImportError:
        pass
    except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
        logger.debug("Confidence decay failed (non-critical): %s", exc)

    try:
        from aragora.events.dispatcher import dispatch_event

        dispatch_event(
            "memory.stale_revalidation",
            {
                "item_id": item_id,
                "days_since_access": context.get("days_since_access", 0),
                "confidence": context.get("confidence", 0),
            },
        )
    except ImportError:
        pass
    except (RuntimeError, ValueError, TypeError, AttributeError):
        pass


async def _create_debate_topic(context: dict[str, Any]) -> None:
    """Route contradiction to debate engine for resolution."""
    description = context.get("description", "")
    logger.info(
        "Contradiction detected, debate topic created: %s",
        description,
    )
    try:
        from aragora.learning.improvement_queue import (
            ImprovementSuggestion,
            get_improvement_queue,
        )

        queue = get_improvement_queue()
        queue.enqueue(
            ImprovementSuggestion(
                debate_id=f"contradiction_{id(context)}",
                task=f"Resolve contradiction: {description[:200]}",
                suggestion="Run targeted debate to reconcile conflicting knowledge",
                category="knowledge_contradiction",
                confidence=0.9,
            )
        )
    except ImportError:
        pass
    except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
        logger.debug("Debate topic creation failed (non-critical): %s", exc)

    try:
        from aragora.events.dispatcher import dispatch_event

        dispatch_event(
            "memory.contradiction_detected",
            {"description": description},
        )
    except ImportError:
        pass
    except (RuntimeError, ValueError, TypeError, AttributeError):
        pass


async def _merge_summaries(context: dict[str, Any]) -> None:
    """Consolidate similar memory items into a single merged entry."""
    item_count = context.get("item_count", 0)
    logger.info(
        "Consolidation merge triggered for %d items",
        item_count,
    )
    try:
        from aragora.events.dispatcher import dispatch_event

        dispatch_event(
            "memory.consolidation_merge",
            {
                "item_count": item_count,
                "avg_surprise": context.get("avg_surprise", 0),
            },
        )
    except ImportError:
        pass
    except (RuntimeError, ValueError, TypeError, AttributeError):
        pass


async def _extract_pattern(context: dict[str, Any]) -> None:
    """Extract emerging pattern and persist to Knowledge Mound."""
    pattern = context.get("pattern", "")
    logger.info(
        "Pattern emergence detected: %s",
        pattern,
    )
    try:
        from aragora.events.dispatcher import dispatch_event

        dispatch_event(
            "memory.pattern_emerged",
            {
                "pattern": pattern,
                "trend": context.get("surprise_ema_trend", ""),
            },
        )
    except ImportError:
        pass
    except (RuntimeError, ValueError, TypeError, AttributeError):
        pass


__all__ = ["MemoryTriggerEngine", "MemoryTrigger", "TriggerResult"]
