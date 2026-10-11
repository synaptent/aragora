"""Registers the canonical workspace stores with :mod:`aragora.debate.workspace_stores`.

Reached through the ``aragora.workspace_stores`` entry point in ``pyproject.toml`` on the
debate engine's first workspace stores lookup, so importing ``aragora.stores`` never
loads the debate engine.
"""

from __future__ import annotations

from aragora.debate.workspace_stores import register_workspace_stores_factory
from aragora.stores.canonical import get_canonical_workspace_stores


def register_debate_workspace_stores() -> None:
    """Register the canonical workspace stores factory; safe to call more than once."""
    register_workspace_stores_factory(get_canonical_workspace_stores)


__all__ = ["register_debate_workspace_stores"]
