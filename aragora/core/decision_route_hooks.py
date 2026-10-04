"""Registration hooks between the decision router and the packages that serve it.

``aragora.core`` sits in the domain layer, so the decision router cannot import the
pipeline, connector or server packages that implement some of its optional steps.
Each of those packages registers its implementation here (the pipeline and chat
connector packages from their own init, the server-owned audit sink through
``aragora.server.decision_routes.register_decision_routes``), and the router looks
the implementation up at call time.

Every getter raises :class:`DecisionRouteNotRegisteredError` when nothing is
registered. Each hook holds one implementation, so registering again replaces it.
A hook holds the registered object itself, so patching the provider module's
attribute does not reach the router; tests swap a hook through its register function.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, cast

HOOK_DECISION_INTEGRITY = "decision_integrity_builder"
HOOK_TTS_BRIDGE = "tts_bridge_factory"
HOOK_AUDIT_SINK = "decision_audit_sink"


class DecisionRouteNotRegisteredError(RuntimeError):
    """A decision-router hook was used before the package that provides it registered it."""


DecisionIntegrityBuilder = Callable[..., Awaitable[dict[str, Any] | None]]
TTSBridgeFactory = Callable[[], Any]


class DecisionAuditSink(Protocol):
    """Receives the audit trail of routed decisions."""

    def log_decision_started(
        self,
        *,
        request_id: str,
        decision_type: str,
        source: str,
        user_id: str | None = None,
        workspace_id: str | None = None,
        content_preview: str | None = None,
    ) -> None: ...

    def log_decision_completed(
        self,
        *,
        request_id: str,
        decision_type: str,
        success: bool,
        consensus_reached: bool,
        confidence: float,
        duration_seconds: float,
        user_id: str | None = None,
        workspace_id: str | None = None,
        error: str | None = None,
    ) -> None: ...


_hooks: dict[str, Any] = {}

_HOOK_PROVIDERS = {
    HOOK_DECISION_INTEGRITY: "the aragora.pipeline package",
    HOOK_TTS_BRIDGE: "the aragora.connectors.chat package",
    HOOK_AUDIT_SINK: "aragora.server.decision_routes.register_decision_routes()",
}


def _get_hook(name: str) -> Any:
    try:
        return _hooks[name]
    except KeyError:
        raise DecisionRouteNotRegisteredError(
            f"No {name} registered; it is provided by {_HOOK_PROVIDERS[name]}"
        ) from None


def register_decision_integrity_builder(builder: DecisionIntegrityBuilder) -> None:
    _hooks[HOOK_DECISION_INTEGRITY] = builder


def get_decision_integrity_builder() -> DecisionIntegrityBuilder:
    return cast(DecisionIntegrityBuilder, _get_hook(HOOK_DECISION_INTEGRITY))


def register_tts_bridge_factory(factory: TTSBridgeFactory) -> None:
    _hooks[HOOK_TTS_BRIDGE] = factory


def get_tts_bridge_factory() -> TTSBridgeFactory:
    return cast(TTSBridgeFactory, _get_hook(HOOK_TTS_BRIDGE))


def register_decision_audit_sink(sink: DecisionAuditSink) -> None:
    _hooks[HOOK_AUDIT_SINK] = sink


def get_decision_audit_sink() -> DecisionAuditSink:
    return cast(DecisionAuditSink, _get_hook(HOOK_AUDIT_SINK))


__all__ = [
    "DecisionAuditSink",
    "DecisionIntegrityBuilder",
    "DecisionRouteNotRegisteredError",
    "TTSBridgeFactory",
    "get_decision_audit_sink",
    "get_decision_integrity_builder",
    "get_tts_bridge_factory",
    "register_decision_audit_sink",
    "register_decision_integrity_builder",
    "register_tts_bridge_factory",
]
