"""Factory hook for the adversarial gauntlet the post-debate coordinator runs on a decision.

The debate engine sits below ``aragora.gauntlet``, whose ``GauntletRunner`` stress-tests a
decision, and must not import it. The first :func:`create_gauntlet_runner` that finds no
factory runs, once per process, the registrations declared under the
``aragora.debate_gauntlet_runners`` entry-point group; aragora's own ``pyproject.toml``
declares the gauntlet runner there. A later registration replaces the previous factory.

:func:`create_gauntlet_runner` raises :class:`GauntletRunnerNotRegisteredError` when no
factory is registered after that.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aragora.utils.declared_registrations import DeclaredRegistrations

GAUNTLET_RUNNERS_ENTRY_POINT_GROUP = "aragora.debate_gauntlet_runners"

# Returns an object with ``async run(input_content=..., context=...)``.
GauntletRunnerFactory = Callable[[], Any]


class GauntletRunnerNotRegisteredError(RuntimeError):
    """No gauntlet runner factory is registered."""


_factory: GauntletRunnerFactory | None = None
_declared = DeclaredRegistrations(GAUNTLET_RUNNERS_ENTRY_POINT_GROUP)


def register_gauntlet_runner_factory(factory: GauntletRunnerFactory) -> None:
    """Make ``factory`` build gauntlet runners, replacing any earlier one."""
    global _factory
    _factory = factory


def create_gauntlet_runner() -> Any:
    """Build a gauntlet runner with the registered factory.

    Raises:
        GauntletRunnerNotRegisteredError: no factory is registered, even after the
            declared registrations ran.
    """
    factory = _factory
    if factory is None:
        _declared.load()
        factory = _factory
    if factory is None:
        raise GauntletRunnerNotRegisteredError(
            "no gauntlet runner is registered; import aragora.gauntlet.debate_registration "
            "and call register_debate_gauntlet_runner(), or declare a registration under the "
            f"{GAUNTLET_RUNNERS_ENTRY_POINT_GROUP!r} entry-point group"
        )
    return factory()


__all__ = [
    "GAUNTLET_RUNNERS_ENTRY_POINT_GROUP",
    "GauntletRunnerFactory",
    "GauntletRunnerNotRegisteredError",
    "create_gauntlet_runner",
    "register_gauntlet_runner_factory",
]
