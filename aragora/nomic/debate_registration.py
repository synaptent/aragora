"""Registers the nomic loop as the debate engine's nomic backend.

Reached through the ``aragora.debate_nomic_backends`` entry point in ``pyproject.toml`` on the
debate engine's first nomic lookup, so the debate engine never imports ``aragora.nomic``.
"""

from __future__ import annotations

from typing import Any

from aragora.debate.nomic_backends import register_nomic_backend


class NomicDebateBackend:
    """Hands the debate engine the nomic loop's classes.

    Each method imports its module when called, as the debate engine's own imports did,
    so a patched module attribute applies and a module that cannot be imported (including
    one set to ``None`` in ``sys.modules``) raises ``ImportError`` to the caller.
    """

    def bead_classes(self) -> tuple[Any, Any, Any, Any]:
        from aragora.nomic.beads import Bead, BeadPriority, BeadStatus, BeadType

        return Bead, BeadPriority, BeadStatus, BeadType

    def hook_queue_registry(self) -> Any:
        from aragora.nomic.hook_queue import HookQueueRegistry

        return HookQueueRegistry

    def outcome_feedback_bridge(self) -> Any:
        from aragora.nomic.outcome_feedback import OutcomeFeedbackBridge

        return OutcomeFeedbackBridge

    def debate_profile(self) -> Any:
        from aragora.nomic.debate_profile import NomicDebateProfile

        return NomicDebateProfile

    def outcome_tracker(self) -> Any:
        from aragora.nomic.outcome_tracker import NomicOutcomeTracker

        return NomicOutcomeTracker


def register_debate_nomic_backend() -> None:
    """Register the nomic loop backend; safe to call more than once."""
    register_nomic_backend(NomicDebateBackend())


__all__ = ["NomicDebateBackend", "register_debate_nomic_backend"]
