"""Factory hook for the gateway store behind :class:`~aragora.stores.canonical.CanonicalGatewayStores`.

``aragora.stores`` sits below ``aragora.gateway``, which implements the gateway store
backends, and must not import it. The first :meth:`CanonicalGatewayStores.gateway_store`
that finds no factory runs, once per process, the registrations declared under the
``aragora.gateway_stores`` entry-point group; aragora's own ``pyproject.toml`` declares the
gateway's store builder there. A later registration replaces the previous factory.

:func:`get_gateway_store_factory` raises :class:`GatewayStoreFactoryNotRegisteredError`
when no factory is registered after that.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aragora.utils.declared_registrations import DeclaredRegistrations

GATEWAY_STORES_ENTRY_POINT_GROUP = "aragora.gateway_stores"

# Called with the keyword arguments of ``aragora.gateway.persistence.get_gateway_store_from_env``.
GatewayStoreFactory = Callable[..., Any]


class GatewayStoreFactoryNotRegisteredError(RuntimeError):
    """No gateway store factory is registered."""


_factory: GatewayStoreFactory | None = None
_declared = DeclaredRegistrations(GATEWAY_STORES_ENTRY_POINT_GROUP)


def register_gateway_store_factory(factory: GatewayStoreFactory) -> None:
    """Make ``factory`` build the gateway store, replacing any earlier one."""
    global _factory
    _factory = factory


def get_gateway_store_factory() -> GatewayStoreFactory:
    """The registered gateway store factory.

    Raises:
        GatewayStoreFactoryNotRegisteredError: no factory is registered, even after the
            declared registrations ran.
    """
    factory = _factory
    if factory is None:
        _declared.load()
        factory = _factory
    if factory is None:
        raise GatewayStoreFactoryNotRegisteredError(
            "no gateway store factory is registered; import aragora.gateway.store_registration "
            "and call register_canonical_gateway_store(), or declare a registration under the "
            f"{GATEWAY_STORES_ENTRY_POINT_GROUP!r} entry-point group"
        )
    return factory


__all__ = [
    "GATEWAY_STORES_ENTRY_POINT_GROUP",
    "GatewayStoreFactory",
    "GatewayStoreFactoryNotRegisteredError",
    "get_gateway_store_factory",
    "register_gateway_store_factory",
]
