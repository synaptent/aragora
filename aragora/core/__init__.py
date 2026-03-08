"""Minimal core exports for the standalone debate wedge."""

from __future__ import annotations

from typing import Any

from aragora.core_types import (
    Agent,
    AgentRole,
    AgentStance,
    Critique,
    DebateResult,
    DisagreementReport,
    Environment,
    Message,
    TaskComplexity,
    Vote,
)

__all__ = [
    "Agent",
    "AgentRole",
    "AgentStance",
    "Critique",
    "DebateProtocol",
    "DebateResult",
    "DisagreementReport",
    "Environment",
    "Message",
    "TaskComplexity",
    "Vote",
]


def __getattr__(name: str) -> Any:
    if name == "DebateProtocol":
        from aragora.debate.protocol import DebateProtocol

        return DebateProtocol
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
