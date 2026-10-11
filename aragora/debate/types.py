"""
Shared type definitions for the debate package.

This module provides common type aliases, TypeVars, and Protocol classes
used across the debate package to:
- Reduce TYPE_CHECKING import blocks
- Provide single source of truth for debate-related types
- Enable cleaner imports in phase modules

Usage:
    from aragora.debate.types import AgentType, DebateContextType, PhaseProtocol

    # In function signatures
    def process(ctx: DebateContextType, agent: AgentType) -> None: ...

    # In class definitions
    class MyPhase(PhaseProtocol):
        name = "my_phase"
        async def execute(self, ctx: DebateContextType) -> None: ...
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Protocol,
    TypeVar,
    runtime_checkable,
)
from collections.abc import Callable, Coroutine

# Generic type variables
T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)

# Type alias for phase callables
PhaseCallable = Callable[["DebateContextType"], Coroutine[Any, Any, None]]


@runtime_checkable
class PhaseProtocol(Protocol):
    """Protocol for debate phase implementations.

    All debate phases must implement this protocol to be usable
    with the PhaseExecutor.
    """

    name: str

    async def execute(self, ctx: DebateContextType) -> None:
        """Execute the phase with the given debate context."""
        ...


@runtime_checkable
class AgentProtocol(Protocol):
    """Protocol for agent implementations.

    Defines the minimum interface required for an agent to participate
    in debates.
    """

    name: str

    async def generate(
        self,
        prompt: str,
        context: list[Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Generate a response to the given prompt."""
        ...


# TYPE_CHECKING imports for full type information
# These are only used by type checkers, not at runtime
if TYPE_CHECKING:
    from aragora.core import (
        Agent as AgentType,
        Critique as CritiqueType,
        DebateResult as DebateResultType,
        Message as MessageType,
        Vote as VoteType,
    )
    from aragora.debate.context import DebateContext as DebateContextType
    from aragora.protocols.debate import DebateProtocol as DebateProtocolType
else:
    # Runtime type aliases (strings for forward references)
    AgentType = "Agent"
    CritiqueType = "Critique"
    DebateContextType = "DebateContext"
    DebateProtocolType = "DebateProtocol"
    DebateResultType = "DebateResult"
    MessageType = "Message"
    VoteType = "Vote"


__all__ = [
    # Type variables
    "T",
    "T_co",
    # Callable types
    "PhaseCallable",
    # Protocol classes
    "PhaseProtocol",
    "AgentProtocol",
    # Type aliases (TYPE_CHECKING)
    "AgentType",
    "CritiqueType",
    "DebateContextType",
    "DebateProtocolType",
    "DebateResultType",
    "MessageType",
    "VoteType",
]
