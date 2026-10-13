"""Factory hook for the bridge that routes a post-debate decision plan to external tools.

The debate engine sits below ``aragora.integrations``, whose ``DecisionBridge`` sends a plan
to Jira, Linear or n8n, and must not import it. The first :func:`create_decision_plan_bridge`
that finds no factory runs, once per process, the registrations declared under the
``aragora.decision_plan_bridges`` entry-point group; aragora's own ``pyproject.toml``
declares the integrations bridge there. A later registration replaces the previous factory.

:func:`create_decision_plan_bridge` raises :class:`DecisionPlanBridgeNotRegisteredError`
when no factory is registered after that.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aragora.utils.declared_registrations import DeclaredRegistrations

DECISION_PLAN_BRIDGES_ENTRY_POINT_GROUP = "aragora.decision_plan_bridges"

# Returns an object with ``async handle_decision_plan(plan)``.
DecisionPlanBridgeFactory = Callable[[], Any]


class DecisionPlanBridgeNotRegisteredError(RuntimeError):
    """No decision plan bridge factory is registered."""


_factory: DecisionPlanBridgeFactory | None = None
_declared = DeclaredRegistrations(DECISION_PLAN_BRIDGES_ENTRY_POINT_GROUP)


def register_decision_plan_bridge_factory(factory: DecisionPlanBridgeFactory) -> None:
    """Make ``factory`` build decision plan bridges, replacing any earlier one."""
    global _factory
    _factory = factory


def create_decision_plan_bridge() -> Any:
    """Build a decision plan bridge with the registered factory.

    Raises:
        DecisionPlanBridgeNotRegisteredError: no factory is registered, even after the
            declared registrations ran.
    """
    factory = _factory
    if factory is None:
        _declared.load()
        factory = _factory
    if factory is None:
        raise DecisionPlanBridgeNotRegisteredError(
            "no decision plan bridge is registered; import "
            "aragora.integrations.decision_bridge_registration and call "
            "register_decision_bridge(), or declare a registration under the "
            f"{DECISION_PLAN_BRIDGES_ENTRY_POINT_GROUP!r} entry-point group"
        )
    return factory()


__all__ = [
    "DECISION_PLAN_BRIDGES_ENTRY_POINT_GROUP",
    "DecisionPlanBridgeFactory",
    "DecisionPlanBridgeNotRegisteredError",
    "create_decision_plan_bridge",
    "register_decision_plan_bridge_factory",
]
