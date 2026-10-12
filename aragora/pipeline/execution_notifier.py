"""Execution progress notifier for decision implementation.

Provides callback factories that push task-level progress updates to
originating channels during multi-agent plan execution.  Integrates
with both the PlanExecutor (workflow-based) and HybridExecutor (direct).

Usage:
    notifier = ExecutionNotifier(debate_id="d-123")
    callback = notifier.on_task_complete
    results = await executor.execute_plan(tasks, set(), on_task_complete=callback)
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)


@dataclass
class ExecutionProgress:
    """Snapshot of execution progress for channel delivery."""

    debate_id: str
    plan_id: str | None = None
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    current_task_id: str | None = None
    current_task_description: str | None = None
    elapsed_seconds: float = 0.0
    task_results: list[dict[str, Any]] = field(default_factory=list)

    @property
    def progress_pct(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return (self.completed_tasks + self.failed_tasks) / self.total_tasks * 100

    @property
    def is_complete(self) -> bool:
        return (self.completed_tasks + self.failed_tasks) >= self.total_tasks

    def to_dict(self) -> dict[str, Any]:
        return {
            "debate_id": self.debate_id,
            "plan_id": self.plan_id,
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "current_task_id": self.current_task_id,
            "current_task_description": self.current_task_description,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "progress_pct": round(self.progress_pct, 1),
            "is_complete": self.is_complete,
        }


class ExecutionNotifier:
    """Pushes execution progress to originating channels.

    Create one per execution, then pass ``on_task_complete`` as the
    callback to ``HybridExecutor.execute_plan`` or
    ``PlanExecutor.execute``.
    """

    def __init__(
        self,
        debate_id: str,
        plan_id: str | None = None,
        total_tasks: int = 0,
        notify_channel: bool = True,
        notify_websocket: bool = True,
        channel_targets: list[str] | None = None,
        thread_id: str | None = None,
        thread_id_by_platform: dict[str, str] | None = None,
    ) -> None:
        self.progress = ExecutionProgress(
            debate_id=debate_id,
            plan_id=plan_id,
            total_tasks=total_tasks,
        )
        self._notify_channel = notify_channel
        self._notify_websocket = notify_websocket
        self._channel_targets = channel_targets or []
        self._thread_id = thread_id
        self._thread_id_by_platform = thread_id_by_platform or {}
        self._start_time = time.monotonic()
        self._task_descriptions: dict[str, str] = {}
        self._listeners: list[Callable[[ExecutionProgress], Any]] = []
        self._task_outcomes: dict[str, tuple[bool, str | None]] = {}
        self._completion_sent = False
        self._delivery_errors: list[dict[str, Any]] = []
        self._last_dispatch_key: str | None = None

    def set_task_descriptions(self, tasks: list[Any]) -> None:
        """Pre-populate task descriptions from ImplementTask list."""
        for task in tasks:
            tid = getattr(task, "id", None) or str(task)
            desc = getattr(task, "description", "") or ""
            self._task_descriptions[tid] = desc
        self.progress.total_tasks = len(tasks)

    def add_listener(self, fn: Callable[[ExecutionProgress], Any]) -> None:
        """Register an additional listener for progress events."""
        self._listeners.append(fn)

    @property
    def delivery_errors(self) -> list[dict[str, Any]]:
        """Structured delivery errors collected during notification attempts."""
        return list(self._delivery_errors)

    def on_task_complete(self, task_id: str, result: Any) -> None:
        """Callback for HybridExecutor.execute_plan's on_task_complete.

        Matches the signature ``(task_id: str, result: TaskResult) -> None``.
        """
        self.progress.elapsed_seconds = time.monotonic() - self._start_time
        success = getattr(result, "success", True)
        error = getattr(result, "error", None)
        normalized_error = str(error) if error is not None else None

        previous = self._task_outcomes.get(task_id)
        if previous is not None and previous == (bool(success), normalized_error):
            # Idempotency guard: duplicate callback, no progress delta or resend.
            return

        if previous is not None:
            prev_success, _ = previous
            if prev_success:
                self.progress.completed_tasks = max(0, self.progress.completed_tasks - 1)
            else:
                self.progress.failed_tasks = max(0, self.progress.failed_tasks - 1)

        self._task_outcomes[task_id] = (bool(success), normalized_error)

        if success:
            self.progress.completed_tasks += 1
        else:
            self.progress.failed_tasks += 1

        self.progress.current_task_id = task_id
        self.progress.current_task_description = self._task_descriptions.get(task_id)
        self.progress.task_results.append(
            {
                "task_id": task_id,
                "success": success,
                "model_used": getattr(result, "model_used", None),
                "duration_seconds": getattr(result, "duration_seconds", 0.0),
                "error": error,
            }
        )

        # Fire-and-forget channel notification
        self._dispatch_progress()

    def _dispatch_progress(self) -> None:
        """Send progress update to channels and WebSocket."""
        dispatch_key = (
            f"{self.progress.completed_tasks}:{self.progress.failed_tasks}:"
            f"{self.progress.current_task_id}:{len(self.progress.task_results)}"
        )
        if self._last_dispatch_key == dispatch_key:
            return
        self._last_dispatch_key = dispatch_key

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            loop.create_task(self._async_dispatch())
        else:
            # Fallback: log progress for non-async contexts
            logger.info(
                "Execution progress [%s]: %d/%d tasks (%.0f%%)",
                self.progress.debate_id,
                self.progress.completed_tasks + self.progress.failed_tasks,
                self.progress.total_tasks,
                self.progress.progress_pct,
            )

    async def _async_dispatch(self) -> None:
        """Send progress to channel and WebSocket asynchronously."""
        progress_dict = self.progress.to_dict()
        event_payload = {
            "debate_id": self.progress.debate_id,
            "event": "execution_progress",
            "progress": progress_dict,
        }

        # 1. Route to originating channel (Slack/Teams/Discord/etc.)
        if self._notify_channel:
            try:
                from aragora.server.result_router import route_result

                await route_result(self.progress.debate_id, event_payload)
            except (ImportError, OSError, ConnectionError, RuntimeError, ValueError) as exc:
                self._record_delivery_error("channel_route", exc)
                logger.debug("Channel progress notification failed: %s", exc)

        # 2. Broadcast to WebSocket subscribers
        if self._notify_websocket:
            try:
                from aragora.server.stream.broadcast import broadcast_event

                await broadcast_event(
                    "execution_progress",
                    progress_dict,
                    debate_id=self.progress.debate_id,
                )
            except (ImportError, OSError, ConnectionError, RuntimeError, ValueError) as exc:
                self._record_delivery_error("websocket_broadcast", exc)
                logger.debug("WebSocket progress broadcast failed: %s", exc)

        # 3. Custom listeners
        for listener in self._listeners:
            try:
                result = listener(self.progress)
                if asyncio.iscoroutine(result):
                    await result
            except (TypeError, ValueError, RuntimeError, OSError) as exc:
                self._record_delivery_error("listener", exc)
                logger.debug("Progress listener failed: %s", exc)

        # 4. Explicit channel targets (if provided)
        if self._channel_targets:
            await self._dispatch_to_targets(progress_dict, is_complete=False)

    async def _dispatch_to_targets(self, payload: dict[str, Any], *, is_complete: bool) -> None:
        """Send updates to explicitly configured channel targets."""
        try:
            from aragora.connectors.chat.registry import get_connector
        except ImportError:
            return
        from aragora.events.approval_requests import (
            ApprovalNotifierNotRegisteredError,
            parse_approval_targets,
        )

        try:
            targets = parse_approval_targets(self._channel_targets)
        except ApprovalNotifierNotRegisteredError:
            return
        if not targets:
            return

        text = self._format_progress_text(payload, is_complete=is_complete)

        for platform, channels in targets.items():
            connector = get_connector(platform)
            if connector is None or not connector.is_configured:
                continue

            platform_thread_id = self._thread_id_by_platform.get(platform) or self._thread_id
            for channel_id in channels:
                await self._send_target_message(
                    connector=connector,
                    platform=platform,
                    channel_id=channel_id,
                    text=text,
                    thread_id=platform_thread_id,
                )

    def _format_progress_text(self, payload: dict[str, Any], *, is_complete: bool) -> str:
        """Create a short progress message for chat connectors."""
        completed = payload.get("completed_tasks", 0)
        failed = payload.get("failed_tasks", 0)
        total = payload.get("total_tasks", 0)
        pct = payload.get("progress_pct", 0.0)
        prefix = "Execution complete" if is_complete else "Execution update"
        return f"{prefix} ({pct:.0f}%)\n- Tasks: {completed}/{total} completed" + (
            f", {failed} failed" if failed else ""
        )

    async def send_completion_summary(self) -> None:
        """Send a final summary when execution completes."""
        if self._completion_sent:
            logger.debug(
                "Completion summary already sent for %s",
                self.progress.plan_id or self.progress.debate_id,
            )
            return
        self._completion_sent = True
        self.progress.elapsed_seconds = time.monotonic() - self._start_time
        summary_payload = {
            "debate_id": self.progress.debate_id,
            "event": "execution_complete",
            "summary": {
                **self.progress.to_dict(),
                "task_results": self.progress.task_results,
                "notification_errors": self.delivery_errors,
            },
        }

        if self._notify_channel:
            try:
                from aragora.server.result_router import route_result

                await route_result(self.progress.debate_id, summary_payload)
            except (ImportError, OSError, ConnectionError, RuntimeError, ValueError) as exc:
                self._record_delivery_error("channel_route", exc)
                logger.debug("Channel completion notification failed: %s", exc)

        if self._notify_websocket:
            try:
                from aragora.server.stream.broadcast import broadcast_event

                await broadcast_event(
                    "execution_complete",
                    summary_payload.get("summary", {}),
                    debate_id=self.progress.debate_id,
                )
            except (ImportError, OSError, ConnectionError, RuntimeError, ValueError) as exc:
                self._record_delivery_error("websocket_broadcast", exc)
                logger.debug("WebSocket completion broadcast failed: %s", exc)

        if self._channel_targets:
            summary = summary_payload.get("summary", {})
            await self._dispatch_to_targets(
                summary if isinstance(summary, dict) else {},
                is_complete=True,
            )

    async def _send_target_message(
        self,
        *,
        connector: Any,
        platform: str,
        channel_id: str,
        text: str,
        thread_id: str | None,
        max_attempts: int = 2,
    ) -> None:
        """Send one target message with retry and structured failure tracking."""
        for attempt in range(1, max_attempts + 1):
            try:
                await connector.send_message(
                    channel_id=channel_id,
                    text=text,
                    thread_id=thread_id,
                )
                return
            except (OSError, ConnectionError, RuntimeError, TimeoutError, ValueError) as exc:
                retryable = attempt < max_attempts
                self._record_delivery_error(
                    "target_dispatch",
                    exc,
                    platform=platform,
                    channel_id=channel_id,
                    retryable=retryable,
                    attempt=attempt,
                )
                if not retryable:
                    logger.warning(
                        "Failed to send execution update to %s:%s after %d attempts: %s",
                        platform,
                        channel_id,
                        attempt,
                        exc,
                    )
                    return
                await asyncio.sleep(0.01)

    def _record_delivery_error(
        self,
        stage: str,
        error: Exception,
        *,
        platform: str | None = None,
        channel_id: str | None = None,
        retryable: bool = False,
        attempt: int | None = None,
    ) -> None:
        """Persist structured notification failure context for observability."""
        self._delivery_errors.append(
            {
                "stage": stage,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "platform": platform,
                "channel_id": channel_id,
                "retryable": retryable,
                "attempt": attempt,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
