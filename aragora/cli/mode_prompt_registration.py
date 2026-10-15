"""Registers the operational-mode registry as the debate engine's mode prompt provider.

Reached through the ``aragora.debate_mode_prompts`` entry point in ``pyproject.toml`` on the
debate engine's first mode prompt lookup, so the debate engine never imports
``aragora.modes``.
"""

from __future__ import annotations

from aragora.debate.mode_prompts import register_mode_prompt_provider
from aragora.modes import base


def registered_mode_prompt(name: str) -> str | None:
    """The system prompt of the mode registered as ``name``, or None when none is.

    The registry is looked up on each call, so modes registered later (custom modes, test
    fixtures) are found.
    """
    mode = base.ModeRegistry.get(name)
    if mode is None:
        return None
    return mode.get_system_prompt()


def register_mode_prompts() -> None:
    """Register the mode registry as the provider; safe to call more than once."""
    register_mode_prompt_provider(registered_mode_prompt)


__all__ = ["register_mode_prompts", "registered_mode_prompt"]
