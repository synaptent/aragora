"""Registers the marketplace template registry with :mod:`aragora.debate.template_registry_hooks`.

Reached through the ``aragora.debate_template_registries`` entry point in ``pyproject.toml``
on team selection's first template lookup without an injected registry, so importing
``aragora.marketplace`` never loads the debate engine.
"""

from __future__ import annotations

from typing import Any

from aragora.debate.template_registry_hooks import register_template_registry_factory
from aragora.marketplace import registry as _registry


def build_template_registry() -> Any:
    """Build a template registry with its default database path."""
    # Read at call time so patches of aragora.marketplace.registry.TemplateRegistry apply.
    return _registry.TemplateRegistry()


def register_debate_template_registry() -> None:
    """Register the marketplace template registry factory; safe to call more than once."""
    register_template_registry_factory(build_template_registry)


__all__ = ["build_template_registry", "register_debate_template_registry"]
