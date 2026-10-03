"""
Fork Bridge Handler: Bridge between fork requests and debate execution.
Provides handlers for starting debates from forked histories.
"""

import asyncio
import json
import logging
import threading
from typing import Any
from collections.abc import Callable

from aragora.config import DEFAULT_CONSENSUS, DEFAULT_ROUNDS

logger = logging.getLogger(__name__)

# Lazy imports to avoid circular dependencies
Arena: Callable[..., Any] | None = None
DebateProtocol: Callable[..., Any] | None = None
Environment: Callable[..., Any] | None = None
create_agent: Callable[..., Any] | None = None


def _ensure_imports():
    """Lazy load debate components."""
    global Arena, DebateProtocol, Environment, create_agent
    if Arena is None:
        try:
            from aragora.agents.base import create_agent as _ca
            from aragora.core import Environment as _Env
            from aragora.debate.orchestrator import Arena as _Arena
            from aragora.debate.orchestrator import DebateProtocol as _DP

            Arena = _Arena
            DebateProtocol = _DP
            Environment = _Env
            create_agent = _ca
        except ImportError as e:
            logger.error("Failed to import debate components: %s", e)
            raise


class ForkBridgeHandler:
    """
    Handles fork-based debate initialization.
    Bridges fork requests to live debates with proper validation.
    """

    def __init__(
        self,
        active_loops: dict[str, Any],
        active_loops_lock: threading.Lock,
        fork_store: dict[str, Any] | None = None,
    ):
        """
        Initialize the fork bridge handler.

        Args:
            active_loops: Shared dict of active loop instances
            active_loops_lock: Lock for thread-safe access to active_loops
            fork_store: Optional store for fork/branch data (branch_id -> Branch)
        """
        self.active_loops = active_loops
        self.active_loops_lock = active_loops_lock
        self.fork_store = fork_store or {}
        self._fork_store_lock = threading.Lock()

    def register_fork(self, fork_id: str, fork_data: dict[str, Any]) -> None:
        """Register a fork for later execution."""
        with self._fork_store_lock:
            self.fork_store[fork_id] = fork_data
            logger.info("Fork registered: %s", fork_id)

    def get_fork(self, fork_id: str) -> dict[str, Any] | None:
        """Get fork data by ID."""
        with self._fork_store_lock:
            return self.fork_store.get(fork_id)

    async def handle_start_fork(self, ws: Any, data: dict[str, Any]) -> bool:
        """
        Handle a fork start request from WebSocket.

        Args:
            ws: WebSocket connection (aiohttp or websockets)
            data: Fork data containing fork_id

        Returns:
            Success status
        """
        fork_id = data.get("fork_id")

        if not fork_id:
            logger.warning("Missing fork_id in fork request")
            await self._send_error(ws, "Missing fork_id parameter")
            return False

        # Validate fork_id format (prevent injection)
        if not isinstance(fork_id, str) or len(fork_id) > 64:
            await self._send_error(ws, "Invalid fork_id format")
            return False

        # Check if fork exists in store
        fork_data = self.get_fork(fork_id)
        if not fork_data:
            await self._send_error(
                ws, f"Fork '{fork_id}' not found. Register a fork first via the forking API."
            )
            return False

        loop_id = f"fork_{fork_id}"

        # Check if already running
        with self.active_loops_lock:
            if loop_id in self.active_loops:
                await self._send_error(ws, f"Fork '{fork_id}' is already running")
                return False

        try:
            _ensure_imports()
            arena_cls = Arena
            protocol_cls = DebateProtocol
            environment_cls = Environment
            create_agent_fn = create_agent
            if (
                arena_cls is None
                or protocol_cls is None
                or environment_cls is None
                or create_agent_fn is None
            ):
                raise RuntimeError("Debate components were not initialized")

            # Extract fork configuration
            hypothesis = fork_data.get("hypothesis", "Forked debate")
            lead_agent = fork_data.get("lead_agent", "unknown")
            initial_messages = fork_data.get("messages", [])
            # Validate initial_messages type and size
            if not isinstance(initial_messages, list):
                logger.warning("Invalid initial_messages type: %s", type(initial_messages).__name__)
                initial_messages = []
            else:
                # Validate per-message structure and truncate
                validated = []
                for msg in initial_messages[:1000]:
                    if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                        validated.append(msg)
                if len(validated) < min(len(initial_messages), 1000):
                    logger.debug(
                        "Filtered %s invalid messages",
                        min(len(initial_messages), 1000) - len(validated),
                    )
                initial_messages = validated
            original_task = fork_data.get("task", "Continue the debate")
            agents_config = fork_data.get("agents", ["anthropic-api", "openai-api"])

            # Create agents
            agents = []
            for agent_type in agents_config[:5]:  # Max 5 agents
                agent = create_agent_fn(
                    model_type=agent_type,
                    name=f"{agent_type}_fork",
                    role="proposer",
                )
                agents.append(agent)

            if len(agents) < 2:
                await self._send_error(ws, "At least 2 agents required for forked debate")
                return False

            # Create environment with fork context
            task = f"[Branch: {hypothesis}]\n[Lead: {lead_agent}]\n\n{original_task}"
            env = environment_cls(task=task, max_rounds=DEFAULT_ROUNDS)
            protocol = protocol_cls(
                rounds=DEFAULT_ROUNDS,
                consensus=DEFAULT_CONSENSUS,
                convergence_detection=False,
                early_stopping=False,
            )

            # Create arena with initial message context
            arena = arena_cls(
                env,
                agents,
                protocol,
                loop_id=loop_id,
                initial_messages=initial_messages,
            )

            # Run in background task
            task_obj = asyncio.create_task(self._run_fork_debate(arena, loop_id), name=loop_id)

            def _on_task_done(t: asyncio.Task):
                """Cleanup task from active_loops when done - with exception safety."""
                try:
                    # Cleanup MUST happen even if logging fails
                    try:
                        with self.active_loops_lock:
                            self.active_loops.pop(loop_id, None)
                    except (RuntimeError, KeyError) as cleanup_err:
                        logger.error("Failed to cleanup fork '%s': %s", loop_id, cleanup_err)
                        return

                    # Log status
                    if t.cancelled():
                        logger.debug("Fork debate '%s' was cancelled", loop_id)
                    elif t.exception():
                        logger.warning("Fork debate '%s' failed: %s", loop_id, t.exception())
                    else:
                        logger.info("Fork debate '%s' completed successfully", loop_id)
                except (RuntimeError, KeyError, TypeError) as e:
                    logger.error("Exception in callback for '%s': %s", loop_id, e)

            task_obj.add_done_callback(_on_task_done)

            # Register with active loops
            with self.active_loops_lock:
                self.active_loops[loop_id] = task_obj

            # Send success response
            await self._send_json(
                ws,
                {
                    "type": "fork_started",
                    "data": {
                        "loop_id": loop_id,
                        "fork_id": fork_id,
                        "hypothesis": hypothesis,
                        "status": "running",
                    },
                },
            )

            logger.info("Fork debate started: %s -> %s", fork_id, loop_id)
            return True

        except ImportError as e:
            logger.error("Debate components not available: %s", e)
            await self._send_error(ws, "Debate system not available")
            return False
        except (ValueError, TypeError, RuntimeError, KeyError, AttributeError) as e:
            # Cleanup on failure
            with self.active_loops_lock:
                self.active_loops.pop(loop_id, None)
            logger.error("Failed to start fork debate %s: %s", fork_id, e)
            await self._send_error(ws, f"Fork initialization failed: {type(e).__name__}")
            return False

    async def _run_fork_debate(self, arena, loop_id: str) -> Any:
        """Run the forked debate (initial messages are passed to Arena constructor)."""
        try:
            return await arena.run()
        except (RuntimeError, ValueError, TimeoutError, asyncio.CancelledError) as e:
            logger.error("Fork debate %s failed: %s: %s", loop_id, type(e).__name__, e)
            raise  # Re-raise so callback can detect it

    async def _send_json(self, ws: Any, data: dict) -> None:
        """Send JSON message to websocket (handles both aiohttp and websockets)."""
        try:
            # Try aiohttp style first
            if hasattr(ws, "send_json"):
                await ws.send_json(data)
            else:
                # Fall back to websockets style
                await ws.send(json.dumps(data))
        except (ConnectionError, OSError, RuntimeError) as e:
            logger.error("Failed to send JSON message: %s", e)

    async def _send_error(self, ws: Any, message: str) -> None:
        """Send error message to websocket."""
        await self._send_json(ws, {"type": "error", "data": {"message": message}})
