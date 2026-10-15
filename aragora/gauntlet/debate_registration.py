"""Registers :class:`~aragora.gauntlet.runner.GauntletRunner` with the debate engine.

Reached through the ``aragora.debate_gauntlet_runners`` entry point in ``pyproject.toml``
on the post-debate coordinator's first gauntlet lookup, so the debate engine never imports
``aragora.gauntlet``.
"""

from __future__ import annotations

from typing import Any

from aragora.debate.gauntlet_runners import register_gauntlet_runner_factory
from aragora.gauntlet import runner


def build_gauntlet_runner() -> Any:
    """A new :class:`~aragora.gauntlet.runner.GauntletRunner` with the default config."""
    # Looked up on each call so a patched module class applies.
    return runner.GauntletRunner()


def register_debate_gauntlet_runner() -> None:
    """Register the gauntlet runner factory; safe to call more than once."""
    register_gauntlet_runner_factory(build_gauntlet_runner)


__all__ = ["build_gauntlet_runner", "register_debate_gauntlet_runner"]
