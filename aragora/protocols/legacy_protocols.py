"""Canonical homes for protocols preserved from :mod:`aragora.types.protocols`.

The agent, memory, and event-emitter contracts here intentionally differ from
the newer protocols exported under the same unprefixed names by
``aragora.protocols``. They remain distinct so compatibility imports preserve
their original structural requirements without weakening either contract.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, Protocol, runtime_checkable

EventData = dict[str, Any]
EventHandlerProtocol = Callable[[Any], Coroutine[Any, Any, None]]
SyncEventHandlerProtocol = Callable[[Any], None]


@runtime_checkable
class EventEmitterProtocol(Protocol):
    """Compatibility contract for subscription-based event emitters."""

    def subscribe(
        self,
        event_type: str,
        handler: EventHandlerProtocol,
    ) -> None:
        """Subscribe an async handler to an event type."""
        ...

    def subscribe_sync(
        self,
        event_type: str,
        handler: SyncEventHandlerProtocol,
    ) -> None:
        """Subscribe a sync handler to an event type."""
        ...

    def unsubscribe(
        self,
        event_type: str,
        handler: EventHandlerProtocol,
    ) -> bool:
        """Unsubscribe a handler from an event type."""
        ...

    async def emit(
        self,
        event_type: str,
        debate_id: str = "",
        correlation_id: str | None = None,
        **data: Any,
    ) -> None:
        """Emit an event asynchronously."""
        ...

    def emit_sync(
        self,
        event_type: str,
        debate_id: str = "",
        correlation_id: str | None = None,
        **data: Any,
    ) -> None:
        """Emit an event synchronously."""
        ...


@runtime_checkable
class StorageProtocol(Protocol):
    """Compatibility contract for asynchronous key-value storage."""

    async def get(self, key: str) -> Any | None:
        """Get a value by key."""
        ...

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set a value with an optional TTL."""
        ...

    async def delete(self, key: str) -> bool:
        """Delete a value by key."""
        ...

    async def exists(self, key: str) -> bool:
        """Check whether a key exists."""
        ...


@runtime_checkable
class CacheProtocol(Protocol):
    """Compatibility contract for synchronous caches."""

    def get(self, key: str) -> Any | None:
        """Get a cached value."""
        ...

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set a cached value with an optional TTL."""
        ...

    def delete(self, key: str) -> None:
        """Delete a cached value."""
        ...

    def clear(self) -> None:
        """Clear all cached values."""
        ...


@runtime_checkable
class AgentProtocol(Protocol):
    """Compatibility contract for agents exposing ``generate``."""

    @property
    def name(self) -> str:
        """Return the agent's display name."""
        ...

    @property
    def model(self) -> str:
        """Return the model identifier."""
        ...

    async def generate(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Generate a response to a prompt."""
        ...


@runtime_checkable
class MemoryProtocol(Protocol):
    """Compatibility contract for asynchronous debate memory."""

    async def store(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store content and return its memory identifier."""
        ...

    async def retrieve(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Retrieve memories relevant to a query."""
        ...

    async def forget(self, memory_id: str) -> bool:
        """Remove a memory by identifier."""
        ...


__all__ = [
    "AgentProtocol",
    "CacheProtocol",
    "EventData",
    "EventEmitterProtocol",
    "EventHandlerProtocol",
    "MemoryProtocol",
    "StorageProtocol",
    "SyncEventHandlerProtocol",
]
