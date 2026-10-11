"""Compatibility re-export of :mod:`aragora.runtime.service_registry`.

The service registry moved to the runtime layer so lower layers can use it
without importing ``aragora.services``. Every name below is the identical
object, so registrations and ``ServiceRegistry.reset()`` are shared by both
paths.
"""

from __future__ import annotations

from aragora.runtime.service_registry import (
    RegistryStats,
    ServiceDescriptor,
    ServiceNotFoundError,
    ServiceRegistry,
    ServiceScope,
    get_service,
    has_service,
    register_service,
)

__all__ = [
    "RegistryStats",
    "ServiceDescriptor",
    "ServiceNotFoundError",
    "ServiceRegistry",
    "ServiceScope",
    "get_service",
    "has_service",
    "register_service",
]
