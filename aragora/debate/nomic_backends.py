"""Hook through which the debate engine reaches the nomic loop.

The debate engine sits below ``aragora.nomic``, which holds the beads that record debate work,
the GUPP hook queues, the nomic debate profile, the outcome feedback bridge and the outcome
tracker. It must not import it.
The first :func:`nomic_backend` that finds no backend runs, once per process, the registrations
declared under the ``aragora.debate_nomic_backends`` entry-point group; aragora's own
``pyproject.toml`` declares the nomic package there. A later registration replaces the
previous backend.

:func:`nomic_backend` raises :class:`NomicBackendNotRegisteredError` when no backend is
registered after that.
"""

from __future__ import annotations

from typing import Any, Protocol

from aragora.utils.declared_registrations import DeclaredRegistrations

NOMIC_BACKENDS_ENTRY_POINT_GROUP = "aragora.debate_nomic_backends"


class DebateNomicBackend(Protocol):
    """What the debate engine needs from the nomic loop.

    Each method returns the nomic loop's own classes, so callers use them as they would
    imported names. A method raises ``ImportError`` when the nomic module that defines them
    cannot be imported.
    """

    def bead_classes(self) -> tuple[Any, Any, Any, Any]:
        """``(Bead, BeadPriority, BeadStatus, BeadType)``."""
        ...

    def hook_queue_registry(self) -> Any:
        """``HookQueueRegistry``, which holds each agent's GUPP hook queue."""
        ...

    def outcome_feedback_bridge(self) -> Any:
        """``OutcomeFeedbackBridge``, which turns systematic outcome errors into improvement goals."""
        ...

    def debate_profile(self) -> Any:
        """``NomicDebateProfile``, the settings of the ``full``, ``nomic`` and ``structured`` profiles."""
        ...

    def outcome_tracker(self) -> Any:
        """``NomicOutcomeTracker``, which keeps the regression history of nomic cycles."""
        ...


class NomicBackendNotRegisteredError(RuntimeError):
    """No nomic loop backend is registered."""


_backend: DebateNomicBackend | None = None
_declared = DeclaredRegistrations(NOMIC_BACKENDS_ENTRY_POINT_GROUP)


def register_nomic_backend(backend: DebateNomicBackend) -> None:
    """Make ``backend`` the nomic loop the debate engine uses, replacing any earlier one."""
    global _backend
    _backend = backend


def nomic_backend() -> DebateNomicBackend:
    """The registered nomic loop backend.

    Raises:
        NomicBackendNotRegisteredError: no backend is registered, even after the declared
            registrations ran.
    """
    backend = _backend
    if backend is None:
        _declared.load()
        backend = _backend
    if backend is None:
        raise NomicBackendNotRegisteredError(
            "no nomic loop backend is registered; import aragora.nomic.debate_registration and "
            "call register_debate_nomic_backend(), or declare a registration under the "
            f"{NOMIC_BACKENDS_ENTRY_POINT_GROUP!r} entry-point group"
        )
    return backend


__all__ = [
    "NOMIC_BACKENDS_ENTRY_POINT_GROUP",
    "DebateNomicBackend",
    "NomicBackendNotRegisteredError",
    "nomic_backend",
    "register_nomic_backend",
]
