"""Registration hooks between the decision router and the packages that serve it.

``aragora.core`` sits in the domain layer, so the decision router cannot import the
workflow, gauntlet, pipeline, connector or server packages that implement some of
its routes and optional steps. Each of those packages registers its implementation
here (the workflow, gauntlet, pipeline and chat connector packages from their own
init, the server-owned audit sink through
``aragora.server.decision_routes.register_decision_routes``), and the router looks
the implementation up at call time.

A caller that only imports ``aragora.core`` loads none of those packages. The first
lookup that finds nothing registered therefore runs, once per process, the
registrations declared under the ``aragora.decision_routes`` entry-point group;
aragora's own ``pyproject.toml`` declares the server registration there. The
dependency stays declared by the upper package in packaging metadata, so this
module names none of the packages it reaches.

Every getter raises :class:`DecisionRouteNotRegisteredError` when nothing is
registered after that. Registration is keyed, so registering again (for example
when a package is reloaded) replaces the previous entry instead of adding a second
one. A hook holds the registered object itself, so patching the provider module's
attribute does not reach the router; tests swap a hook through its register function.
"""

from __future__ import annotations

import importlib.metadata
import logging
import sys
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from .decision_models import DecisionRequest, DecisionResult

logger = logging.getLogger(__name__)

DECISION_ROUTES_ENTRY_POINT_GROUP = "aragora.decision_routes"

ROUTE_WORKFLOW = "workflow"
ROUTE_GAUNTLET = "gauntlet"

HOOK_DECISION_INTEGRITY = "decision_integrity_builder"
HOOK_TTS_BRIDGE = "tts_bridge_factory"
HOOK_AUDIT_SINK = "decision_audit_sink"


class DecisionRouteNotRegisteredError(RuntimeError):
    """A decision-router hook was used before the package that provides it registered it."""


class DecisionRouteTarget(Protocol):
    """Runs one decision type for ``router``; ``span`` is the active trace span or None."""

    def __call__(
        self, router: Any, request: DecisionRequest, span: Any | None
    ) -> Awaitable[DecisionResult]: ...


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


_route_targets: dict[str, DecisionRouteTarget] = {}
_hooks: dict[str, Any] = {}

_HOOK_PROVIDERS = {
    HOOK_DECISION_INTEGRITY: "the aragora.pipeline package",
    HOOK_TTS_BRIDGE: "the aragora.connectors.chat package",
    HOOK_AUDIT_SINK: "aragora.server.decision_routes.register_decision_routes()",
}

_declared_registrations_loaded = False
_declared_registrations_lock = threading.RLock()
_SOURCE_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


_REGISTRATION_ERRORS = (
    ImportError,
    SyntaxError,
    AttributeError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


def _source_checkout_registrations() -> list[importlib.metadata.EntryPoint]:
    # An editable install keeps the entry points it was installed with, so a source
    # checkout run against older metadata reads the declarations from its own pyproject.
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        try:
            import tomli as tomllib
        except ImportError:
            return []

    try:
        project = tomllib.loads(_SOURCE_PYPROJECT.read_text(encoding="utf-8")).get("project", {})
    except (OSError, tomllib.TOMLDecodeError):
        return []
    if project.get("name") != "aragora":
        return []
    declared = project.get("entry-points", {}).get(DECISION_ROUTES_ENTRY_POINT_GROUP, {})
    return [
        importlib.metadata.EntryPoint(name, value, DECISION_ROUTES_ENTRY_POINT_GROUP)
        for name, value in declared.items()
    ]


def _load_declared_registrations() -> None:
    """Run every registration declared under the ``aragora.decision_routes`` group, once."""
    global _declared_registrations_loaded
    with _declared_registrations_lock:
        if _declared_registrations_loaded:
            return
        # Set before loading: a registration that looks a hook up must not start another load.
        _declared_registrations_loaded = True
        declared = (
            list(importlib.metadata.entry_points(group=DECISION_ROUTES_ENTRY_POINT_GROUP))
            or _source_checkout_registrations()
        )
        _run_registrations(declared)


def _run_registrations(entry_points: list[importlib.metadata.EntryPoint]) -> None:
    if not entry_points:
        return
    entry_point, rest = entry_points[0], entry_points[1:]
    try:
        entry_point.load()()
    except _REGISTRATION_ERRORS as exc:
        logger.warning("Decision route registration %s failed: %s", entry_point.value, exc)
    finally:
        # The rest run even when an error of another type escapes, so one broken plugin
        # cannot keep aragora's own registration from running; that error still reaches
        # the caller afterwards.
        _run_registrations(rest)


def register_route_target(kind: str, target: DecisionRouteTarget) -> None:
    """Register ``target`` for the decision type named ``kind``."""
    _route_targets[kind] = target


def get_route_target(kind: str) -> DecisionRouteTarget:
    """Return the target registered for ``kind``."""
    if kind not in _route_targets:
        _load_declared_registrations()
    try:
        return _route_targets[kind]
    except KeyError:
        raise DecisionRouteNotRegisteredError(
            f"No decision route registered for {kind!r}; the aragora.{kind} package registers "
            f"it when it is loaded, and no {DECISION_ROUTES_ENTRY_POINT_GROUP!r} entry point "
            "registered it (servers call "
            "aragora.server.decision_routes.register_decision_routes())"
        ) from None


def get_registered_routes() -> dict[str, DecisionRouteTarget]:
    """Snapshot of the registered route targets keyed by decision type."""
    return dict(_route_targets)


def _get_hook(name: str) -> Any:
    if name not in _hooks:
        _load_declared_registrations()
    try:
        return _hooks[name]
    except KeyError:
        raise DecisionRouteNotRegisteredError(
            f"No {name} registered; it is provided by {_HOOK_PROVIDERS[name]}, and no "
            f"{DECISION_ROUTES_ENTRY_POINT_GROUP!r} entry point registered it"
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
    "DECISION_ROUTES_ENTRY_POINT_GROUP",
    "DecisionAuditSink",
    "DecisionIntegrityBuilder",
    "DecisionRouteNotRegisteredError",
    "DecisionRouteTarget",
    "ROUTE_GAUNTLET",
    "ROUTE_WORKFLOW",
    "TTSBridgeFactory",
    "get_decision_audit_sink",
    "get_decision_integrity_builder",
    "get_registered_routes",
    "get_route_target",
    "get_tts_bridge_factory",
    "register_decision_audit_sink",
    "register_decision_integrity_builder",
    "register_route_target",
    "register_tts_bridge_factory",
]
