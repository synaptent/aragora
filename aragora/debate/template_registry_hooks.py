"""Factory hook for the template registry that team selection reads agent roles from.

The debate engine sits below ``aragora.marketplace`` and must not import it. Importing
``aragora.marketplace`` stays cheap, so that package does not load the debate engine just
to register here. Instead, the first :func:`create_template_registry` that finds no factory
runs, once per process, the registrations declared under the
``aragora.debate_template_registries`` entry-point group; aragora's own ``pyproject.toml``
declares the marketplace registry there. A later registration replaces the previous factory.

:func:`create_template_registry` raises :class:`TemplateRegistryNotRegisteredError` when no
factory is registered after that.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aragora.utils.declared_registrations import DeclaredRegistrations

TEMPLATE_REGISTRIES_ENTRY_POINT_GROUP = "aragora.debate_template_registries"

TemplateRegistryFactory = Callable[[], Any]


class TemplateRegistryNotRegisteredError(RuntimeError):
    """No template registry factory is registered."""


_factory: TemplateRegistryFactory | None = None
_declared_registrations = DeclaredRegistrations(TEMPLATE_REGISTRIES_ENTRY_POINT_GROUP)


def register_template_registry_factory(factory: TemplateRegistryFactory) -> None:
    """Make ``factory`` the builder of the default template registry, replacing any earlier one."""
    global _factory
    _factory = factory


def create_template_registry() -> Any:
    """Build the default template registry (an object with ``get(template_id)``).

    Raises:
        TemplateRegistryNotRegisteredError: no factory is registered, even after the
            declared registrations ran.
    """
    factory = _factory
    if factory is None:
        _declared_registrations.load()
        factory = _factory
    if factory is None:
        raise TemplateRegistryNotRegisteredError(
            "no template registry factory is registered; import "
            "aragora.marketplace.debate_registration and call "
            "register_debate_template_registry(), or declare a registration under the "
            f"{TEMPLATE_REGISTRIES_ENTRY_POINT_GROUP!r} entry-point group"
        )
    return factory()


__all__ = [
    "TEMPLATE_REGISTRIES_ENTRY_POINT_GROUP",
    "TemplateRegistryFactory",
    "TemplateRegistryNotRegisteredError",
    "create_template_registry",
    "register_template_registry_factory",
]
