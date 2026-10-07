"""Agent-registry access for event handlers, supplied by the control plane.

Genesis events keep the control plane's agent registry in sync, but the events
layer cannot import the control plane. ``aragora.control_plane`` registers an
agent-registry factory here when it is imported.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol


class EventAgentRegistry(Protocol):
    """The part of the control plane's agent registry that event handlers use."""

    async def register(
        self,
        agent_id: str,
        capabilities: Sequence[str],
        *,
        model: str = "unknown",
        metadata: dict[str, Any] | None = None,
    ) -> Any: ...

    async def unregister(self, agent_id: str) -> Any: ...


AgentRegistryFactory = Callable[[], EventAgentRegistry]


class AgentRegistryNotRegisteredError(RuntimeError):
    """No agent-registry factory has been registered."""


_factory: AgentRegistryFactory | None = None


def register_agent_registry_factory(factory: AgentRegistryFactory) -> bool:
    """Register the factory that creates the agent registry for event handlers.

    Registering the same factory again is a no-op; a different factory replaces
    the current one.

    Returns:
        True when the factory was installed, False when it was already registered.
    """
    global _factory
    if _factory is factory:
        return False
    _factory = factory
    return True


def registered_count() -> int:
    """Return how many agent-registry factories are registered (0 or 1)."""
    return 0 if _factory is None else 1


def create_agent_registry() -> EventAgentRegistry:
    """Create an agent registry through the registered factory.

    Raises:
        AgentRegistryNotRegisteredError: no factory is registered (the control
            plane has not been imported).
    """
    if _factory is None:
        raise AgentRegistryNotRegisteredError(
            "no agent registry factory is registered; import aragora.control_plane"
        )
    return _factory()


__all__ = [
    "AgentRegistryFactory",
    "AgentRegistryNotRegisteredError",
    "EventAgentRegistry",
    "create_agent_registry",
    "register_agent_registry_factory",
    "registered_count",
]
