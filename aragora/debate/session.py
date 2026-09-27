"""
Debate Session Lifecycle Management.

Patterns inspired by claude-squad (AGPL-3.0 License)
Note: Implemented from scratch based on concepts, not copied code (due to AGPL-3.0)
Original concepts: https://github.com/smtg-ai/claude-squad

Provides high-level session management for debates with support for:
- Session states (pending, running, paused, completed, failed, cancelled)
- Pause/resume functionality with checkpoint integration
- Session timeout handling
- Session persistence and recovery

Aragora-specific additions:
- Integration with existing CheckpointManager
- CancellationToken integration for cooperative cancellation
- SessionManager for concurrent session tracking
- Event emission for session lifecycle changes

Usage:
    # Create and run a session
    session = await DebateSession.create(env, agents, protocol)
    await session.start()

    # Pause and resume later
    checkpoint = await session.pause("Taking a break")
    # ... later ...
    await session.resume(checkpoint)

    # Wait for completion
    result = await session.wait_for_completion()
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.debate.cancellation import (
    CancellationReason,
    CancellationToken,
    DebateCancelled,
)

if TYPE_CHECKING:
    from aragora.core import Agent, DebateResult, Environment
    from aragora.debate.checkpoint import CheckpointManager, DebateCheckpoint
    from aragora.debate.protocol import DebateProtocol

__all__ = [
    "DebateSessionState",
    "DebateSession",
    "SessionManager",
    "SessionEvent",
    "SessionEventType",
]

logger = logging.getLogger(__name__)


class DebateSessionState(Enum):
    """Session lifecycle states."""

    PENDING = "pending"  # Created but not started
    RUNNING = "running"  # Active execution
    PAUSED = "paused"  # Suspended with state preserved
    COMPLETED = "completed"  # Finished successfully
    FAILED = "failed"  # Error state
    CANCELLED = "cancelled"  # User cancelled


class SessionEventType(Enum):
    """Types of session lifecycle events."""

    CREATED = "created"
    STARTED = "started"
    PAUSED = "paused"
    RESUMED = "resumed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STATE_CHANGED = "state_changed"
    CHECKPOINT_CREATED = "checkpoint_created"


@dataclass
class SessionEvent:
    """Event emitted during session lifecycle."""

    type: SessionEventType
    session_id: str
    timestamp: str
    data: dict = field(default_factory=dict)
    previous_state: DebateSessionState | None = None
    new_state: DebateSessionState | None = None


@dataclass
class DebateSession:
    """
    High-level debate session with lifecycle management.

    Wraps Arena execution with pause/resume and cancellation support.
    """

    id: str
    state: DebateSessionState
    env: Environment
    agents: list[Agent]
    protocol: DebateProtocol

    # Timing
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    paused_at: datetime | None = None
    completed_at: datetime | None = None

    # State
    current_round: int = 0
    total_rounds: int = 0
    checkpoint_id: str | None = None
    result: DebateResult | None = None
    error_message: str | None = None

    # Cancellation
    cancellation_token: CancellationToken = field(default_factory=CancellationToken)

    # Internal
    _arena: Any = field(default=None, repr=False)
    _task: asyncio.Task | None = field(default=None, repr=False)
    _event_handlers: list[Callable[[SessionEvent], None]] = field(default_factory=list, repr=False)
    _checkpoint_manager: CheckpointManager | None = field(default=None, repr=False)
    _pause_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _resume_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    @classmethod
    async def create(
        cls,
        env: Environment,
        agents: list[Agent],
        protocol: DebateProtocol,
        checkpoint_manager: CheckpointManager | None = None,
        session_id: str | None = None,
    ) -> DebateSession:
        """
        Create a new debate session.

        Args:
            env: Debate environment with task
            agents: Participating agents
            protocol: Debate protocol configuration
            checkpoint_manager: Optional manager for persistence
            session_id: Optional custom session ID

        Returns:
            New DebateSession in PENDING state
        """
        session = cls(
            id=session_id or f"session-{uuid.uuid4().hex[:12]}",
            state=DebateSessionState.PENDING,
            env=env,
            agents=agents,
            protocol=protocol,
            total_rounds=protocol.rounds,
        )
        session._checkpoint_manager = checkpoint_manager

        # Emit creation event
        session._emit_event(
            SessionEventType.CREATED,
            data={"task": env.task[:200], "agent_count": len(agents)},
        )

        logger.info(
            "session_created id=%s agents=%s rounds=%s", session.id, len(agents), protocol.rounds
        )

        return session

    @classmethod
    async def from_checkpoint(
        cls,
        checkpoint: DebateCheckpoint,
        agents: list[Agent],
        protocol: DebateProtocol,
        checkpoint_manager: CheckpointManager | None = None,
    ) -> DebateSession:
        """
        Restore a session from a checkpoint.

        Args:
            checkpoint: Checkpoint to restore from
            agents: Agents to use (should match checkpoint)
            protocol: Protocol configuration
            checkpoint_manager: Optional manager for persistence

        Returns:
            DebateSession in PAUSED state ready to resume
        """
        from aragora.core import Environment

        env = Environment(task=checkpoint.task)

        session = cls(
            id=f"session-{checkpoint.debate_id[:8]}-resumed",
            state=DebateSessionState.PAUSED,
            env=env,
            agents=agents,
            protocol=protocol,
            current_round=checkpoint.current_round,
            total_rounds=checkpoint.total_rounds,
            checkpoint_id=checkpoint.checkpoint_id,
        )
        session._checkpoint_manager = checkpoint_manager

        logger.info(
            "session_restored id=%s from_checkpoint=%s", session.id, checkpoint.checkpoint_id
        )

        return session

    def _emit_event(
        self,
        event_type: SessionEventType,
        data: dict | None = None,
        previous_state: DebateSessionState | None = None,
        new_state: DebateSessionState | None = None,
    ) -> None:
        """Emit a session event to all handlers."""
        event = SessionEvent(
            type=event_type,
            session_id=self.id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data=data or {},
            previous_state=previous_state,
            new_state=new_state,
        )

        for handler in self._event_handlers:
            try:
                handler(event)
            except (RuntimeError, ValueError, TypeError, OSError) as e:
                logger.warning("Session event handler failed: %s", e)

    def _transition_state(self, new_state: DebateSessionState) -> None:
        """Transition to a new state with validation."""
        valid_transitions = {
            DebateSessionState.PENDING: {
                DebateSessionState.RUNNING,
                DebateSessionState.CANCELLED,
            },
            DebateSessionState.RUNNING: {
                DebateSessionState.PAUSED,
                DebateSessionState.COMPLETED,
                DebateSessionState.FAILED,
                DebateSessionState.CANCELLED,
            },
            DebateSessionState.PAUSED: {
                DebateSessionState.RUNNING,
                DebateSessionState.CANCELLED,
            },
            DebateSessionState.COMPLETED: set(),  # Terminal state
            DebateSessionState.FAILED: set(),  # Terminal state
            DebateSessionState.CANCELLED: set(),  # Terminal state
        }

        if new_state not in valid_transitions.get(self.state, set()):
            logger.warning("Invalid state transition: %s -> %s", self.state.value, new_state.value)
            return

        previous_state = self.state
        self.state = new_state

        self._emit_event(
            SessionEventType.STATE_CHANGED,
            data={"transition": f"{previous_state.value} -> {new_state.value}"},
            previous_state=previous_state,
            new_state=new_state,
        )

        logger.debug(
            "session_state_change id=%s %s -> %s", self.id, previous_state.value, new_state.value
        )

    def on_event(self, handler: Callable[[SessionEvent], None]) -> Callable[[], None]:
        """
        Register an event handler.

        Args:
            handler: Callback for session events

        Returns:
            Unregister function
        """
        self._event_handlers.append(handler)

        def unregister():
            if handler in self._event_handlers:
                self._event_handlers.remove(handler)

        return unregister

    async def start(self) -> None:
        """
        Start the debate session.

        Transitions from PENDING to RUNNING and begins execution.
        """
        if self.state != DebateSessionState.PENDING:
            raise RuntimeError(f"Cannot start session in {self.state.value} state")

        self._transition_state(DebateSessionState.RUNNING)
        self.started_at = datetime.now(timezone.utc)

        # Create Arena with cancellation token in context
        from aragora.debate.orchestrator import Arena

        self._arena = Arena(
            environment=self.env,
            agents=self.agents,
            protocol=self.protocol,
            enable_checkpointing=self._checkpoint_manager is not None,
            checkpoint_manager=self._checkpoint_manager,
        )

        # Start execution in background task
        self._task = asyncio.create_task(self._execute())

        self._emit_event(
            SessionEventType.STARTED,
            data={"task": self.env.task[:200]},
        )

        logger.info("session_started id=%s", self.id)

    async def _execute(self) -> None:
        """Internal execution loop with pause/cancel support."""
        try:
            # Run the debate
            self.result = await self._arena.run()

            # Check if we were paused/cancelled during execution
            if self.cancellation_token.is_cancelled:
                self._transition_state(DebateSessionState.CANCELLED)
                self._emit_event(
                    SessionEventType.CANCELLED,
                    data={"reason": self.cancellation_token.reason},
                )
            else:
                self._transition_state(DebateSessionState.COMPLETED)
                self.completed_at = datetime.now(timezone.utc)
                self._emit_event(
                    SessionEventType.COMPLETED,
                    data={
                        "consensus_reached": getattr(self.result, "consensus_reached", False),
                        "rounds_used": getattr(self.result, "rounds_used", 0),
                    },
                )

            logger.info("session_completed id=%s", self.id)

        except DebateCancelled as e:
            self._transition_state(DebateSessionState.CANCELLED)
            self._emit_event(
                SessionEventType.CANCELLED,
                data={"reason": e.reason},
            )
            logger.info("session_cancelled id=%s reason=%s", self.id, e.reason)

        except Exception as e:  # noqa: BLE001 - session lifecycle must catch all failures to transition to FAILED state
            self._transition_state(DebateSessionState.FAILED)
            self.error_message = f"Session failed: {type(e).__name__}"
            self._emit_event(
                SessionEventType.FAILED,
                data={"error": f"session_failed:{type(e).__name__}"},
            )
            logger.error("session_failed id=%s error=%s", self.id, e)

    async def pause(self, reason: str = "User requested pause") -> str | None:
        """
        Pause the session and create a checkpoint.

        Args:
            reason: Reason for pausing

        Returns:
            Checkpoint ID if checkpoint was created
        """
        if self.state != DebateSessionState.RUNNING:
            raise RuntimeError(f"Cannot pause session in {self.state.value} state")

        # Signal pause
        self._pause_event.set()
        self.paused_at = datetime.now(timezone.utc)

        # Create checkpoint if manager available
        checkpoint_id = None
        if self._checkpoint_manager and self._arena:
            try:
                # Get current state from arena context
                checkpoint = await self._checkpoint_manager.create_checkpoint(
                    debate_id=self.id,
                    task=self.env.task,
                    current_round=self.current_round,
                    total_rounds=self.total_rounds,
                    phase="paused",
                    messages=getattr(self._arena, "_partial_messages", []),
                    critiques=getattr(self._arena, "_partial_critiques", []),
                    votes=[],
                    agents=self.agents,
                )
                checkpoint_id = checkpoint.checkpoint_id
                self.checkpoint_id = checkpoint_id

                self._emit_event(
                    SessionEventType.CHECKPOINT_CREATED,
                    data={"checkpoint_id": checkpoint_id},
                )

            except (OSError, RuntimeError, ValueError, TypeError, ConnectionError) as e:
                logger.warning("Failed to create checkpoint on pause: %s", e)

        self._transition_state(DebateSessionState.PAUSED)
        self._emit_event(
            SessionEventType.PAUSED,
            data={"reason": reason, "checkpoint_id": checkpoint_id},
        )

        logger.info("session_paused id=%s checkpoint=%s", self.id, checkpoint_id)

        return checkpoint_id

    async def resume(self, checkpoint_id: str | None = None) -> None:
        """
        Resume a paused session.

        Args:
            checkpoint_id: Optional checkpoint to resume from
        """
        if self.state != DebateSessionState.PAUSED:
            raise RuntimeError(f"Cannot resume session in {self.state.value} state")

        # Load checkpoint if provided
        if checkpoint_id and self._checkpoint_manager:
            resumed = await self._checkpoint_manager.resume_from_checkpoint(checkpoint_id)
            if resumed:
                self.current_round = resumed.checkpoint.current_round
                logger.info(
                    "session_resumed_from_checkpoint id=%s checkpoint=%s", self.id, checkpoint_id
                )

        self._transition_state(DebateSessionState.RUNNING)
        self._pause_event.clear()
        self._resume_event.set()

        # Restart execution
        self._task = asyncio.create_task(self._execute())

        self._emit_event(
            SessionEventType.RESUMED,
            data={"checkpoint_id": checkpoint_id},
        )

        logger.info("session_resumed id=%s", self.id)

    async def cancel(self, reason: str = "User requested cancellation") -> None:
        """
        Cancel the session.

        Args:
            reason: Reason for cancellation
        """
        if self.state in {
            DebateSessionState.COMPLETED,
            DebateSessionState.FAILED,
            DebateSessionState.CANCELLED,
        }:
            return  # Already in terminal state

        # Signal cancellation
        self.cancellation_token.cancel(reason, CancellationReason.USER_REQUESTED)

        # Cancel the task if running
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.debug("session_task_cancelled id=%s", self.id)

        self._transition_state(DebateSessionState.CANCELLED)
        self._emit_event(
            SessionEventType.CANCELLED,
            data={"reason": reason},
        )

        logger.info("session_cancelled id=%s reason=%s", self.id, reason)

    async def wait_for_completion(self, timeout: float | None = None) -> DebateResult | None:
        """
        Wait for the session to complete.

        Args:
            timeout: Optional timeout in seconds

        Returns:
            DebateResult if completed, None if cancelled/failed
        """
        if self._task is None:
            return self.result

        try:
            if timeout is not None:
                await asyncio.wait_for(self._task, timeout=timeout)
            else:
                await self._task
        except asyncio.TimeoutError:
            logger.warning("session_wait_timeout id=%s timeout=%s", self.id, timeout)
            return None
        except asyncio.CancelledError:
            return None

        return self.result

    @property
    def is_terminal(self) -> bool:
        """Check if session is in a terminal state."""
        return self.state in {
            DebateSessionState.COMPLETED,
            DebateSessionState.FAILED,
            DebateSessionState.CANCELLED,
        }

    @property
    def is_running(self) -> bool:
        """Check if session is currently running."""
        return self.state == DebateSessionState.RUNNING

    @property
    def duration_seconds(self) -> float | None:
        """Get session duration in seconds."""
        if self.started_at is None:
            return None

        end_time = self.completed_at or self.paused_at or datetime.now(timezone.utc)
        return (end_time - self.started_at).total_seconds()

    def to_dict(self) -> dict:
        """Serialize session to dictionary."""
        return {
            "id": self.id,
            "state": self.state.value,
            "task": self.env.task[:200],
            "agent_count": len(self.agents),
            "current_round": self.current_round,
            "total_rounds": self.total_rounds,
            "checkpoint_id": self.checkpoint_id,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "paused_at": self.paused_at.isoformat() if self.paused_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message,
        }


class SessionManager:
    """
    Manages multiple debate sessions.

    Provides session lookup, listing, and cleanup.
    """

    def __init__(
        self,
        checkpoint_manager: CheckpointManager | None = None,
        max_sessions: int = 100,
    ):
        """
        Initialize session manager.

        Args:
            checkpoint_manager: Optional checkpoint manager for persistence
            max_sessions: Maximum concurrent sessions
        """
        self._sessions: dict[str, DebateSession] = {}
        self._checkpoint_manager = checkpoint_manager
        self._max_sessions = max_sessions
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        env: Environment,
        agents: list[Agent],
        protocol: DebateProtocol,
    ) -> DebateSession:
        """
        Create a new session.

        Args:
            env: Debate environment
            agents: Participating agents
            protocol: Debate protocol

        Returns:
            New DebateSession
        """
        async with self._lock:
            # Cleanup old sessions if at limit
            if len(self._sessions) >= self._max_sessions:
                await self._cleanup_terminal_sessions()

            session = await DebateSession.create(
                env=env,
                agents=agents,
                protocol=protocol,
                checkpoint_manager=self._checkpoint_manager,
            )

            self._sessions[session.id] = session
            return session

    async def get_session(self, session_id: str) -> DebateSession | None:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    async def list_sessions(
        self,
        state: DebateSessionState | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        List sessions.

        Args:
            state: Optional filter by state
            limit: Maximum sessions to return

        Returns:
            List of session summaries
        """
        sessions = list(self._sessions.values())

        if state is not None:
            sessions = [s for s in sessions if s.state == state]

        # Sort by created_at descending
        sessions.sort(key=lambda s: s.created_at, reverse=True)

        return [s.to_dict() for s in sessions[:limit]]

    async def cancel_session(self, session_id: str, reason: str) -> bool:
        """Cancel a session by ID."""
        session = self._sessions.get(session_id)
        if session is None:
            return False

        await session.cancel(reason)
        return True

    async def _cleanup_terminal_sessions(self) -> int:
        """Remove terminal sessions to free memory."""
        to_remove = []
        for session_id, session in self._sessions.items():
            if session.is_terminal:
                to_remove.append(session_id)

        for session_id in to_remove:
            del self._sessions[session_id]

        logger.debug("Cleaned up %s terminal sessions", len(to_remove))
        return len(to_remove)

    async def cleanup(self) -> None:
        """Cancel all sessions and cleanup."""
        for session in list(self._sessions.values()):
            if not session.is_terminal:
                await session.cancel("Session manager shutdown")

        self._sessions.clear()
        logger.info("Session manager cleanup complete")
