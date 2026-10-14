"""Factory hook through which lower packages build evidence connectors by kind.

``aragora.agents`` and ``aragora.verticals`` sit below ``aragora.connectors``, which holds the
web, GitHub, local docs, research, legal, medical, accounting, tax and SEC connectors, and
must not import it. The first :func:`create_connector` that finds no factory runs, once per
process, the registrations declared under the ``aragora.connector_factories`` entry-point
group; aragora's own ``pyproject.toml`` declares the connectors package there. A later
registration replaces the previous factory.

:func:`create_connector` raises :class:`ConnectorFactoryNotRegisteredError` when no factory
is registered after that.
"""

from __future__ import annotations

from typing import Any, Protocol

from aragora.utils.declared_registrations import DeclaredRegistrations

CONNECTOR_FACTORIES_ENTRY_POINT_GROUP = "aragora.connector_factories"


class ConnectorFactory(Protocol):
    """Builds the connector for ``kind`` (such as ``"github"``) from keyword arguments.

    It may return None for a kind it knows but cannot build in this install, and raises
    ``ImportError`` when the connector's module cannot be imported.
    """

    def __call__(self, kind: str, /, **kwargs: Any) -> Any: ...


class ConnectorFactoryNotRegisteredError(RuntimeError):
    """No connector factory is registered."""


_factory: ConnectorFactory | None = None
_declared = DeclaredRegistrations(CONNECTOR_FACTORIES_ENTRY_POINT_GROUP)


def register_connector_factory(factory: ConnectorFactory) -> None:
    """Make ``factory`` build connectors, replacing any earlier one."""
    global _factory
    _factory = factory


def create_connector(kind: str, /, **kwargs: Any) -> Any:
    """Build the connector for ``kind`` with the registered factory.

    Raises:
        ConnectorFactoryNotRegisteredError: no factory is registered, even after the declared
            registrations ran.
    """
    factory = _factory
    if factory is None:
        _declared.load()
        factory = _factory
    if factory is None:
        raise ConnectorFactoryNotRegisteredError(
            "no connector factory is registered; import aragora.connectors.factory_registration "
            "and call register_evidence_connectors(), or declare a registration under the "
            f"{CONNECTOR_FACTORIES_ENTRY_POINT_GROUP!r} entry-point group"
        )
    return factory(kind, **kwargs)


__all__ = [
    "CONNECTOR_FACTORIES_ENTRY_POINT_GROUP",
    "ConnectorFactory",
    "ConnectorFactoryNotRegisteredError",
    "create_connector",
    "register_connector_factory",
]
