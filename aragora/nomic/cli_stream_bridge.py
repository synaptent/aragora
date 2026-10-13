"""
Bridge between CLI execution events and WebSocket stream servers.

Connects self_develop.py progress callbacks to NomicLoopStreamServer and
PipelineStreamEmitter so frontend hooks (usePipelineWebSocket.ts,
useNomicLoopWebSocket.ts) receive real-time events during CLI execution.

Usage:
    from aragora.nomic.cli_stream_bridge import CLIStreamBridge

    bridge = CLIStreamBridge(nomic_port=8767, pipeline_id="my-run")
    await bridge.start()

    # Use as a drop-in replacement for _print_progress in self_develop.py
    callback = bridge.as_progress_callback()
    callback("cycle_started", {"cycle_id": "abc"})

    await bridge.stop()
"""

# ruff: noqa: T201

from __future__ import annotations

import asyncio
import logging
import sys
import time
import uuid
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Phase name mapping from self_develop.py progress events to NomicLoopStreamServer phases
_NOMIC_PHASE_MAP: dict[str, str] = {
    "cycle_started": "context",
    "planning_complete": "debate",
    "decomposition_complete": "design",
    "risk_assessment_complete": "design",
    "risk_blocked": "design",
    "risk_review_needed": "design",
    "execution_complete": "implement",
    "cycle_complete": "verify",
}

# Pipeline stage mapping from progress events to PipelineStreamEmitter stages
_PIPELINE_STAGE_MAP: dict[str, str] = {
    "cycle_started": "ideas",
    "planning_complete": "goals",
    "decomposition_complete": "goals",
    "risk_assessment_complete": "workflows",
    "risk_blocked": "workflows",
    "risk_review_needed": "workflows",
    "execution_complete": "orchestration",
    "cycle_complete": "orchestration",
}


class CLIStreamBridge:
    """Bridge CLI progress events to WebSocket stream servers.

    Wraps NomicLoopStreamServer and PipelineStreamEmitter to provide
    a unified callback interface compatible with self_develop.py's
    ``_print_progress()`` signature.

    Follows fire-and-forget semantics: if stream servers are unavailable
    or event emission fails, errors are logged but never raised to the
    caller.
    """

    def __init__(
        self,
        nomic_port: int = 8767,
        nomic_host: str = "0.0.0.0",  # WS server binds all interfaces by default
        pipeline_id: str | None = None,
        enable_nomic_server: bool = True,
        enable_pipeline_emitter: bool = True,
        print_to_stdout: bool = True,
    ) -> None:
        """Initialize the bridge.

        Args:
            nomic_port: Port for the NomicLoopStreamServer WebSocket.
            nomic_host: Host to bind the Nomic stream server.
            pipeline_id: Pipeline ID for PipelineStreamEmitter events.
                Auto-generated if not provided.
            enable_nomic_server: Whether to start a NomicLoopStreamServer.
            enable_pipeline_emitter: Whether to emit PipelineStreamEmitter events.
            print_to_stdout: Whether to also print events to stdout
                (preserves the original _print_progress behavior).
        """
        self._nomic_port = nomic_port
        self._nomic_host = nomic_host
        self._pipeline_id = pipeline_id or f"cli-{uuid.uuid4().hex[:8]}"
        self._enable_nomic = enable_nomic_server
        self._enable_pipeline = enable_pipeline_emitter
        self._print_to_stdout = print_to_stdout

        self._nomic_server: Any | None = None
        self._pipeline_emitter: Any | None = None
        self._started = False
        self._cycle_number = 0
        self._start_time = 0.0

    @property
    def pipeline_id(self) -> str:
        """Return the pipeline ID used for pipeline events."""
        return self._pipeline_id

    @property
    def started(self) -> bool:
        """Return whether the bridge has been started."""
        return self._started

    async def start(self) -> None:
        """Start the underlying stream servers.

        Gracefully handles import failures and server startup errors.
        """
        if self._started:
            return

        self._start_time = time.time()

        # Initialize NomicLoopStreamServer
        if self._enable_nomic:
            try:
                from aragora.server.stream.nomic_loop_stream import NomicLoopStreamServer

                self._nomic_server = NomicLoopStreamServer(
                    port=self._nomic_port,
                    host=self._nomic_host,
                )
                await self._nomic_server.start()
                logger.info(
                    "CLI stream bridge: Nomic server started on port %d",
                    self._nomic_port,
                )
            except ImportError:
                logger.debug("websockets not available; Nomic stream server disabled")
                self._nomic_server = None
            except (OSError, RuntimeError) as exc:
                logger.warning("Failed to start Nomic stream server: %s", exc)
                self._nomic_server = None

        # Initialize PipelineStreamEmitter (no server to start -- it's an
        # in-process emitter that clients connect to via the web server)
        if self._enable_pipeline:
            try:
                from aragora.server.stream.pipeline_stream import get_pipeline_emitter

                self._pipeline_emitter = get_pipeline_emitter()
                logger.info(
                    "CLI stream bridge: Pipeline emitter active for pipeline %s",
                    self._pipeline_id,
                )
            except ImportError:
                logger.debug("Pipeline stream emitter not available")
                self._pipeline_emitter = None

        self._started = True

    async def stop(self) -> None:
        """Stop the underlying stream servers."""
        if not self._started:
            return

        if self._nomic_server is not None:
            try:
                await self._nomic_server.stop()
            except (OSError, RuntimeError) as exc:
                logger.debug("Error stopping Nomic stream server: %s", exc)
            self._nomic_server = None

        self._pipeline_emitter = None
        self._started = False

    async def emit_nomic_event(
        self,
        phase: str,
        status: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Emit an event to the NomicLoopStreamServer.

        Args:
            phase: Nomic phase name (context, debate, design, implement, verify).
            status: Event status (started, completed, failed).
            data: Additional event data.
        """
        if self._nomic_server is None:
            return

        try:
            if status == "started":
                await self._nomic_server.emit_phase_started(
                    phase=phase,
                    cycle=self._cycle_number,
                )
            elif status == "completed":
                duration = time.time() - self._start_time
                await self._nomic_server.emit_phase_completed(
                    phase=phase,
                    cycle=self._cycle_number,
                    duration_sec=duration,
                    result_summary=(data or {}).get("summary"),
                )
            elif status == "failed":
                await self._nomic_server.emit_phase_failed(
                    phase=phase,
                    cycle=self._cycle_number,
                    error=(data or {}).get("error", "unknown error"),
                )
            else:
                # Generic log message for unrecognized statuses
                await self._nomic_server.emit_log_message(
                    level="info",
                    message=f"{phase}: {status}",
                    source="cli_bridge",
                )
        except (ConnectionError, OSError, RuntimeError) as exc:
            logger.debug("Failed to emit Nomic event: %s", exc)

    async def emit_pipeline_event(
        self,
        stage: str,
        status: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Emit an event to the PipelineStreamEmitter.

        Args:
            stage: Pipeline stage name (ideas, goals, workflows, orchestration).
            status: Event status (started, completed, failed, progress).
            data: Additional event data.
        """
        if self._pipeline_emitter is None:
            return

        try:
            if status == "started":
                await self._pipeline_emitter.emit_stage_started(
                    pipeline_id=self._pipeline_id,
                    stage_name=stage,
                    config=data,
                )
            elif status == "completed":
                await self._pipeline_emitter.emit_stage_completed(
                    pipeline_id=self._pipeline_id,
                    stage_name=stage,
                    summary=data,
                )
            elif status == "failed":
                await self._pipeline_emitter.emit_failed(
                    pipeline_id=self._pipeline_id,
                    error=(data or {}).get("error", "unknown error"),
                )
            elif status == "progress":
                step_name = (data or {}).get("step", stage)
                progress = (data or {}).get("progress", 0.0)
                await self._pipeline_emitter.emit_step_progress(
                    pipeline_id=self._pipeline_id,
                    step_name=step_name,
                    progress=progress,
                )
        except (ConnectionError, OSError, RuntimeError) as exc:
            logger.debug("Failed to emit pipeline event: %s", exc)

    def _stdout_print(self, event: str, data: dict[str, Any]) -> None:
        """Print event to stdout, matching _print_progress format."""
        if event == "cycle_started":
            self._write_stdout(f"  [start] Cycle {data.get('cycle_id', '?')}")
        elif event == "planning_complete":
            self._write_stdout(f"  [plan] {data.get('goals', 0)} goals identified")
        elif event == "decomposition_complete":
            self._write_stdout(f"  [decompose] {data.get('subtasks', 0)} subtasks created")
        elif event == "risk_assessment_complete":
            self._write_stdout(
                f"  [risk] {data.get('total', 0)} scored: "
                f"{data.get('auto_approved', 0)} auto, "
                f"{data.get('needs_review', 0)} review, "
                f"{data.get('blocked', 0)} blocked"
            )
        elif event == "risk_blocked":
            self._write_stdout(
                f"  [risk:BLOCKED] {str(data.get('subtask', ''))[:60]} (score={data.get('score', 0):.2f})"
            )
        elif event == "risk_review_needed":
            self._write_stdout(
                f"  [risk:REVIEW] {str(data.get('subtask', ''))[:60]} (score={data.get('score', 0):.2f})"
            )
        elif event == "execution_complete":
            self._write_stdout(
                f"  [exec] {data.get('completed', 0)} completed, {data.get('failed', 0)} failed"
            )
        elif event == "cycle_complete":
            self._write_stdout(
                f"  [done] {data.get('completed', 0)} completed, "
                f"{data.get('failed', 0)} failed, "
                f"{data.get('duration', 0):.1f}s"
            )

    @staticmethod
    def _write_stdout(message: str) -> None:
        """Write one line to stdout without using print()."""
        sys.stdout.write(f"{message}\n")

    def _emit_fire_and_forget(self, event: str, data: dict[str, Any]) -> None:
        """Schedule async event emission without blocking the caller.

        Uses fire-and-forget: if no event loop is running or emission fails,
        the error is silently logged.
        """
        nomic_phase = _NOMIC_PHASE_MAP.get(event)
        pipeline_stage = _PIPELINE_STAGE_MAP.get(event)

        # Determine status from event name
        if event == "cycle_started":
            self._cycle_number += 1
            nomic_status = "started"
            pipeline_status = "started"
        elif event in ("cycle_complete",):
            nomic_status = "completed"
            pipeline_status = "completed"
        elif event in ("risk_blocked",):
            nomic_status = "failed"
            pipeline_status = "progress"
        else:
            nomic_status = "completed"
            pipeline_status = "progress"

        try:
            loop = asyncio.get_running_loop()

            if nomic_phase:
                loop.create_task(self.emit_nomic_event(nomic_phase, nomic_status, data))
            if pipeline_stage:
                loop.create_task(self.emit_pipeline_event(pipeline_stage, pipeline_status, data))
        except RuntimeError:
            # No running event loop -- skip async emission
            logger.debug("No event loop available for CLI stream bridge emission")

    def as_progress_callback(self) -> Callable[[str, dict[str, Any]], None]:
        """Return a callback compatible with self_develop.py's _print_progress.

        The returned function:
        1. Prints to stdout (if print_to_stdout is True)
        2. Emits events to NomicLoopStreamServer and PipelineStreamEmitter
           via fire-and-forget async tasks

        Returns:
            A ``(event: str, data: dict) -> None`` callback.
        """

        def callback(event: str, data: dict[str, Any]) -> None:
            # Always print to stdout if enabled
            if self._print_to_stdout:
                self._stdout_print(event, data)

            # Fire-and-forget to stream servers
            self._emit_fire_and_forget(event, data)

        return callback
