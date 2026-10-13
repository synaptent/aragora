"""Registers :class:`~aragora.integrations.decision_bridge.DecisionBridge` with the debate engine.

Reached through the ``aragora.decision_plan_bridges`` entry point in ``pyproject.toml`` on
the post-debate coordinator's first bridge lookup, so the debate engine never imports
``aragora.integrations``.
"""

from __future__ import annotations

from typing import Any

from aragora.debate.decision_plan_bridges import register_decision_plan_bridge_factory
from aragora.integrations import decision_bridge


def build_decision_bridge() -> Any:
    """A new :class:`~aragora.integrations.decision_bridge.DecisionBridge` with default targets."""
    # Looked up on each call so a patched module class applies.
    return decision_bridge.DecisionBridge()


def register_decision_bridge() -> None:
    """Register the decision bridge factory; safe to call more than once."""
    register_decision_plan_bridge_factory(build_decision_bridge)


__all__ = ["build_decision_bridge", "register_decision_bridge"]
