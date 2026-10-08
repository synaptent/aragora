"""
DecisionService - Async-first abstraction for debate orchestration.

Decouples debate execution from HTTP request/response lifecycle, enabling:
- Background debate processing
- Event-driven updates via async iterators
- State persistence across restarts
- Horizontal scaling to 10,000+ concurrent debates

Usage:
    from aragora.debate.decision_service import (
        DecisionService,
        get_decision_service,
        DebateRequest,
        DebateState,
        DebateEvent,
    )

    # Start a debate (returns immediately)
    service = get_decision_service()
    debate_id = await service.start_debate(DebateRequest(
        task="Design a rate limiter",
        agents=["claude", "gemini"],
    ))

    # Check status later
    state = await service.get_debate(debate_id)
    print(f"Status: {state.status}, Progress: {state.progress}")

    # Subscribe to real-time events
    async for event in service.subscribe_events(debate_id):
        print(f"{event.type}: {event.data}")

Architecture:
    DecisionService (Protocol) - Abstract interface
        └── AsyncDecisionService - Background execution implementation
            ├── _store: StateStore (Protocol) - Debate state persistence
            ├── _event_bus: EventBus - Pub/sub for debate events
            └── _executor: Background debate runner
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Protocol,
    cast,
    runtime_checkable,
)
from collections.abc import Callable

from aragora.config import DEFAULT_CONSENSUS, DEFAULT_ROUNDS
from aragora.config.settings import get_settings
from aragora.core import DebateResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# =============================================================================
# Data Types
# =============================================================================


class DebateStatus(str, Enum):
    """Debate lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventType(str, Enum):
    """Types of debate events."""

    DEBATE_STARTED = "debate_started"
    ROUND_STARTED = "round_started"
    ROUND_COMPLETED = "round_completed"
    AGENT_MESSAGE = "agent_message"
    CRITIQUE_SUBMITTED = "critique_submitted"
    VOTE_CAST = "vote_cast"
    CONSENSUS_REACHED = "consensus_reached"
    DEBATE_COMPLETED = "debate_completed"
    DEBATE_FAILED = "debate_failed"
    PROGRESS_UPDATE = "progress_update"


@dataclass
class DebateRequest:
    """Request to start a new debate.

    All fields except `task` are optional with sensible defaults.
    """

    task: str
    agents: list[str] | None = None
    rounds: int = DEFAULT_ROUNDS
    consensus: Literal[
        "majority",
        "unanimous",
        "judge",
        "none",
        "weighted",
        "supermajority",
        "any",
        "byzantine",
    ] = cast(
        Literal[
            "majority",
            "unanimous",
            "judge",
            "none",
            "weighted",
            "supermajority",
            "any",
            "byzantine",
        ],
        DEFAULT_CONSENSUS,
    )
    timeout: float = 600.0  # 10 minutes for background debates
    priority: int = 0  # Higher = more urgent
    metadata: dict[str, Any] = field(default_factory=dict)

    # Telemetry
    org_id: str = ""
    user_id: str = ""
    correlation_id: str = ""

    # Feature flags
    enable_streaming: bool = True
    enable_checkpointing: bool = True
    enable_memory: bool = True


@dataclass
class DebateState:
    """Current state of a debate.

    Provides a snapshot of debate progress for polling or UI display.
    """

    id: str
    task: str
    status: DebateStatus
    progress: float = 0.0  # 0.0 to 1.0
    current_round: int = 0
    total_rounds: int = DEFAULT_ROUNDS
    agents: list[str] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    result: DebateResult | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize state to dictionary."""
        return {
            "id": self.id,
            "task": self.task,
            "status": self.status.value,
            "progress": self.progress,
            "current_round": self.current_round,
            "total_rounds": self.total_rounds,
            "agents": self.agents,
            "messages": self.messages,
            "result": self.result.to_dict() if self.result else None,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "metadata": self.metadata,
        }


@dataclass
class DebateEvent:
    """Real-time debate event for streaming updates."""

    debate_id: str
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Serialize event to dictionary."""
        return {
            "debate_id": self.debate_id,
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }


# =============================================================================
# Protocols (Abstract Interfaces)
# =============================================================================


@runtime_checkable
class StateStore(Protocol):
    """Protocol for debate state persistence.

    Implementations may use Redis, PostgreSQL, in-memory, etc.
    """

    async def save(self, state: DebateState) -> None:
        """Persist debate state."""
        ...

    async def get(self, debate_id: str) -> DebateState | None:
        """Retrieve debate state by ID."""
        ...

    async def list_active(self, limit: int = 100, org_id: str | None = None) -> list[DebateState]:
        """List active (running/pending) debates, only ``org_id``'s when given."""
        ...

    async def delete(self, debate_id: str) -> bool:
        """Delete debate state."""
        ...


@runtime_checkable
class DecisionService(Protocol):
    """Protocol for debate orchestration service.

    Defines the core interface for starting, monitoring, and subscribing
    to debates. Implementations can use different execution strategies
    (in-process, distributed, serverless, etc.).
    """

    async def start_debate(self, request: DebateRequest) -> str:
        """Start a new debate.

        Returns immediately with debate ID. Debate runs in background.

        Args:
            request: Debate configuration

        Returns:
            Debate ID for tracking
        """
        ...

    async def get_debate(self, debate_id: str) -> DebateState | None:
        """Get current debate state.

        Args:
            debate_id: Debate to query

        Returns:
            Current state or None if not found
        """
        ...

    async def cancel_debate(self, debate_id: str) -> bool:
        """Cancel a running debate.

        Args:
            debate_id: Debate to cancel

        Returns:
            True if cancelled, False if not found or already complete
        """
        ...

    async def subscribe_events(self, debate_id: str) -> AsyncIterator[DebateEvent]:
        """Subscribe to real-time debate events.

        Args:
            debate_id: Debate to subscribe to

        Yields:
            DebateEvent objects as they occur
        """
        ...


# =============================================================================
# In-Memory State Store (Default Implementation)
# =============================================================================


class InMemoryStateStore:
    """Simple in-memory state store for development/testing.

    For production, use RedisStateStore or PostgresStateStore.
    """

    def __init__(self) -> None:
        self._states: dict[str, DebateState] = {}

    async def save(self, state: DebateState) -> None:
        """Save state to memory."""
        state.updated_at = datetime.now(timezone.utc)
        self._states[state.id] = state

    async def get(self, debate_id: str) -> DebateState | None:
        """Get state from memory."""
        return self._states.get(debate_id)

    async def list_active(self, limit: int = 100, org_id: str | None = None) -> list[DebateState]:
        """List active debates, only ``org_id``'s when given."""
        active = [
            s
            for s in self._states.values()
            if s.status in (DebateStatus.PENDING, DebateStatus.RUNNING)
            and (org_id is None or (bool(org_id) and s.metadata.get("org_id") == org_id))
        ]
        return sorted(active, key=lambda s: s.created_at)[:limit]

    async def delete(self, debate_id: str) -> bool:
        """Delete state."""
        if debate_id in self._states:
            del self._states[debate_id]
            return True
        return False


# =============================================================================
# Event Bus (Pub/Sub for Debate Events)
# =============================================================================


class EventBus:
    """Simple async event bus for debate events.

    Enables multiple subscribers to receive real-time debate updates.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[DebateEvent]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, event: DebateEvent) -> None:
        """Publish event to all subscribers."""
        async with self._lock:
            queues = self._subscribers.get(event.debate_id, [])
            for queue in queues:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning("Event queue full for debate %s", event.debate_id)

    async def subscribe(self, debate_id: str) -> asyncio.Queue[DebateEvent]:
        """Create a new subscription for debate events."""
        async with self._lock:
            if debate_id not in self._subscribers:
                self._subscribers[debate_id] = []
            queue: asyncio.Queue[DebateEvent] = asyncio.Queue(maxsize=1000)
            self._subscribers[debate_id].append(queue)
            return queue

    async def unsubscribe(self, debate_id: str, queue: asyncio.Queue[DebateEvent]) -> None:
        """Remove a subscription."""
        async with self._lock:
            if debate_id in self._subscribers:
                try:
                    self._subscribers[debate_id].remove(queue)
                    if not self._subscribers[debate_id]:
                        del self._subscribers[debate_id]
                except ValueError as e:
                    logger.debug("Failed to remove subscription for debate %s: %s", debate_id, e)
                    # Queue was not in subscriber list, likely already removed


# =============================================================================
# Async Decision Service Implementation
# =============================================================================


class AsyncDecisionService:
    """Async-first decision service implementation.

    Runs debates in background tasks, persists state, and publishes events.
    Designed for horizontal scaling with external state stores.

    Example:
        service = AsyncDecisionService()

        # Start debate
        debate_id = await service.start_debate(DebateRequest(
            task="Design caching strategy",
            agents=["claude", "gemini", "grok"],
        ))

        # Poll for completion
        while True:
            state = await service.get_debate(debate_id)
            if state.status == DebateStatus.COMPLETED:
                print(f"Result: {state.result.synthesis}")
                break
            await asyncio.sleep(1)

        # Or subscribe to events
        async for event in service.subscribe_events(debate_id):
            if event.type == EventType.DEBATE_COMPLETED:
                break
    """

    def __init__(
        self,
        store: StateStore | None = None,
        event_bus: EventBus | None = None,
        max_concurrent: int = 100,
        default_agents: list[str] | None = None,
    ) -> None:
        """Initialize the decision service.

        Args:
            store: State persistence backend (default: InMemoryStateStore)
            event_bus: Event pub/sub system (default: EventBus)
            max_concurrent: Maximum concurrent debates
            default_agents: Default agents when none specified
        """
        self._store = store or InMemoryStateStore()
        self._event_bus = event_bus or EventBus()
        self._max_concurrent = max_concurrent
        self._default_agents = default_agents or get_settings().agent.default_agent_list
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running_tasks: dict[str, asyncio.Task[None]] = {}

    async def start_debate(self, request: DebateRequest) -> str:
        """Start a new debate in the background.

        Returns immediately with debate ID.
        """
        debate_id = str(uuid.uuid4())

        # Create initial state
        state = DebateState(
            id=debate_id,
            task=request.task,
            status=DebateStatus.PENDING,
            total_rounds=request.rounds,
            agents=request.agents or self._default_agents,
            metadata={
                "correlation_id": request.correlation_id,
                "priority": request.priority,
                **request.metadata,
                # After the caller's metadata: the owner fields decide who may
                # see the decision, so caller-supplied keys must not replace them.
                "org_id": request.org_id,
                "user_id": request.user_id,
            },
        )

        # Persist initial state
        await self._store.save(state)

        # Publish start event
        await self._event_bus.publish(
            DebateEvent(
                debate_id=debate_id,
                type=EventType.DEBATE_STARTED,
                data={"task": request.task, "agents": state.agents},
            )
        )

        # Start background execution
        task = asyncio.create_task(self._run_debate(debate_id, request))
        task.add_done_callback(
            lambda t: logger.error(
                "[decision_service] Debate %s failed: %s", debate_id, t.exception()
            )
            if not t.cancelled() and t.exception()
            else None
        )
        self._running_tasks[debate_id] = task

        return debate_id

    async def get_debate(self, debate_id: str) -> DebateState | None:
        """Get current debate state."""
        return await self._store.get(debate_id)

    async def cancel_debate(self, debate_id: str) -> bool:
        """Cancel a running debate."""
        state = await self._store.get(debate_id)
        if not state:
            return False

        if state.status not in (DebateStatus.PENDING, DebateStatus.RUNNING):
            return False

        # Cancel the task
        task = self._running_tasks.get(debate_id)
        if task and not task.done():
            task.cancel()

        # Update state
        state.status = DebateStatus.CANCELLED
        state.completed_at = datetime.now(timezone.utc)
        await self._store.save(state)

        # Publish cancellation event
        await self._event_bus.publish(
            DebateEvent(
                debate_id=debate_id,
                type=EventType.DEBATE_FAILED,
                data={"reason": "cancelled"},
            )
        )

        return True

    async def subscribe_events(self, debate_id: str) -> AsyncIterator[DebateEvent]:
        """Subscribe to debate events."""
        queue = await self._event_bus.subscribe(debate_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=60.0)
                    yield event

                    # Stop on terminal events
                    if event.type in (
                        EventType.DEBATE_COMPLETED,
                        EventType.DEBATE_FAILED,
                    ):
                        break
                except asyncio.TimeoutError:
                    # Send keepalive/heartbeat
                    yield DebateEvent(
                        debate_id=debate_id,
                        type=EventType.PROGRESS_UPDATE,
                        data={"heartbeat": True},
                    )
        finally:
            await self._event_bus.unsubscribe(debate_id, queue)

    async def list_debates(
        self,
        status: DebateStatus | None = None,
        limit: int = 100,
        org_id: str | None = None,
    ) -> list[DebateState]:
        """List debates, optionally filtered by status and by owning org."""
        if org_id is not None:
            return await self._store.list_active(limit, org_id=org_id)
        if status in (DebateStatus.PENDING, DebateStatus.RUNNING):
            return await self._store.list_active(limit)
        # For other statuses, implementation depends on store capabilities
        return await self._store.list_active(limit)

    async def _run_debate(self, debate_id: str, request: DebateRequest) -> None:
        """Execute debate in background with state updates and events."""
        async with self._semaphore:
            state = await self._store.get(debate_id)
            if not state:
                return

            try:
                # Update status to running
                state.status = DebateStatus.RUNNING
                await self._store.save(state)

                # Import here to avoid circular imports
                from aragora.debate.service import DebateOptions, DebateService

                # Create debate service with event hooks
                service = DebateService(default_agents=self._default_agents)

                # Build options from request
                options = DebateOptions(
                    rounds=request.rounds,
                    consensus=request.consensus,
                    timeout=request.timeout,
                    enable_streaming=request.enable_streaming,
                    enable_checkpointing=request.enable_checkpointing,
                    enable_memory=request.enable_memory,
                    org_id=request.org_id,
                    user_id=request.user_id,
                    correlation_id=request.correlation_id,
                    on_round_start=self._make_round_callback(debate_id, state),
                    on_agent_message=self._make_message_callback(debate_id),
                    on_consensus=self._make_consensus_callback(debate_id),
                )

                # Run the debate
                result = await service.run(
                    task=request.task,
                    agents=request.agents,
                    options=options,
                )

                # Update state with result
                state.status = DebateStatus.COMPLETED
                state.result = result
                state.progress = 1.0
                state.completed_at = datetime.now(timezone.utc)
                await self._store.save(state)

                # Publish completion event
                await self._event_bus.publish(
                    DebateEvent(
                        debate_id=debate_id,
                        type=EventType.DEBATE_COMPLETED,
                        data={
                            "synthesis": result.synthesis if result else None,
                            "consensus_reached": result.consensus_reached if result else False,
                        },
                    )
                )

            except asyncio.CancelledError:
                state.status = DebateStatus.CANCELLED
                state.completed_at = datetime.now(timezone.utc)
                await self._store.save(state)
                raise

            except Exception as e:  # noqa: BLE001 - background debate execution must catch all failures to update state
                logger.exception("Debate %s failed: %s", debate_id, e)
                state.status = DebateStatus.FAILED
                state.error = f"Debate failed: {type(e).__name__}"
                state.completed_at = datetime.now(timezone.utc)
                await self._store.save(state)

                await self._event_bus.publish(
                    DebateEvent(
                        debate_id=debate_id,
                        type=EventType.DEBATE_FAILED,
                        data={"error": f"debate_failed:{type(e).__name__}"},
                    )
                )

            finally:
                # Cleanup
                self._running_tasks.pop(debate_id, None)

    def _make_round_callback(self, debate_id: str, state: DebateState) -> Callable[[int], None]:
        """Create callback for round start events."""

        def _log_task_error(t: asyncio.Task) -> None:
            if not t.cancelled() and t.exception():
                logger.warning("[decision_service] Background task failed: %s", t.exception())

        def on_round_start(round_num: int) -> None:
            state.current_round = round_num
            state.progress = round_num / state.total_rounds
            # Schedule async save and publish
            asyncio.create_task(self._store.save(state)).add_done_callback(_log_task_error)
            asyncio.create_task(
                self._event_bus.publish(
                    DebateEvent(
                        debate_id=debate_id,
                        type=EventType.ROUND_STARTED,
                        data={"round": round_num},
                    )
                )
            ).add_done_callback(_log_task_error)

        return on_round_start

    def _make_message_callback(self, debate_id: str) -> Callable[[str, str], None]:
        """Create callback for agent message events."""

        def on_agent_message(agent: str, message: str) -> None:
            asyncio.create_task(
                self._event_bus.publish(
                    DebateEvent(
                        debate_id=debate_id,
                        type=EventType.AGENT_MESSAGE,
                        data={"agent": agent, "message": message[:500]},  # Truncate
                    )
                )
            ).add_done_callback(
                lambda t: logger.warning(
                    "[decision_service] Event publish failed: %s", t.exception()
                )
                if not t.cancelled() and t.exception()
                else None
            )

        return on_agent_message

    def _make_consensus_callback(self, debate_id: str) -> Callable[[str, float], None]:
        """Create callback for consensus events."""

        def on_consensus(decision: str, confidence: float) -> None:
            asyncio.create_task(
                self._event_bus.publish(
                    DebateEvent(
                        debate_id=debate_id,
                        type=EventType.CONSENSUS_REACHED,
                        data={"decision": decision, "confidence": confidence},
                    )
                )
            ).add_done_callback(
                lambda t: logger.warning(
                    "[decision_service] Consensus publish failed: %s", t.exception()
                )
                if not t.cancelled() and t.exception()
                else None
            )

        return on_consensus


# =============================================================================
# Global Service Instance
# =============================================================================

_decision_service: AsyncDecisionService | None = None


def get_decision_service(
    store: StateStore | None = None,
    max_concurrent: int = 100,
    default_agents: list[str] | None = None,
    **kwargs: Any,
) -> AsyncDecisionService:
    """Get the global decision service instance.

    Creates a new instance on first call or when store is provided.

    Args:
        store: State persistence backend
        max_concurrent: Maximum concurrent debates
        default_agents: Default agents
        **kwargs: Additional AsyncDecisionService arguments

    Returns:
        AsyncDecisionService instance
    """
    global _decision_service

    if _decision_service is None or store is not None:
        _decision_service = AsyncDecisionService(
            store=store,
            max_concurrent=max_concurrent,
            default_agents=default_agents,
            **kwargs,
        )

    return _decision_service


def reset_decision_service() -> None:
    """Reset the global decision service instance."""
    global _decision_service
    _decision_service = None


__all__ = [
    # Protocols
    "DecisionService",
    "StateStore",
    # Data types
    "DebateRequest",
    "DebateState",
    "DebateEvent",
    "DebateStatus",
    "EventType",
    # Implementation
    "AsyncDecisionService",
    "InMemoryStateStore",
    "EventBus",
    # Factory functions
    "get_decision_service",
    "reset_decision_service",
]
