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
    "DecisionConfig",
    "DecisionRequest",
    "DecisionResult",
    "DecisionRouter",
    "DecisionType",
    "Critique",
    "DebateProtocol",
    "DebateResult",
    "DisagreementReport",
    "Environment",
    "InputSource",
    "get_decision_router",
    "Message",
    "Priority",
    "RequestContext",
    "ResponseChannel",
    "ResponseFormat",
    "reset_decision_router",
    "TaskComplexity",
    "Vote",
]

_LAZY_EXPORTS = {
    "DebateProtocol": ("aragora.protocols.debate", "DebateProtocol"),
    "DecisionConfig": ("aragora.core.decision", "DecisionConfig"),
    "DecisionRequest": ("aragora.core.decision", "DecisionRequest"),
    "DecisionResult": ("aragora.core.decision", "DecisionResult"),
    "DecisionRouter": ("aragora.core.decision", "DecisionRouter"),
    "DecisionType": ("aragora.core.decision", "DecisionType"),
    "InputSource": ("aragora.core.decision", "InputSource"),
    "Priority": ("aragora.core.decision", "Priority"),
    "RequestContext": ("aragora.core.decision", "RequestContext"),
    "ResponseChannel": ("aragora.core.decision", "ResponseChannel"),
    "ResponseFormat": ("aragora.core.decision", "ResponseFormat"),
    "get_decision_router": ("aragora.core.decision", "get_decision_router"),
    "reset_decision_router": ("aragora.core.decision", "reset_decision_router"),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        module = __import__(module_name, fromlist=[attr_name])
        return getattr(module, attr_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
