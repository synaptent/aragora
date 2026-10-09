"""
Centralized Service Registry for dependency management.

This module provides a thread-safe service registry that replaces scattered
global singletons throughout the codebase. Benefits:
- Single location for all services
- Easy to mock services in tests via reset()
- Type-safe service resolution
- Lazy initialization support via factories

Usage:
    # Direct registration
    registry = ServiceRegistry.get()
    registry.register(TierManager, tier_manager_instance)

    # Factory registration (lazy init)
    registry.register_factory(TierManager, lambda: TierManager())

    # Get service
    tier_manager = registry.resolve(TierManager)

    # Module-level convenience functions
    from aragora.runtime.service_registry import get_service, register_service
    register_service(TierManager, my_instance)
    tier_manager = get_service(TierManager)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar, overload
from collections.abc import Callable

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ServiceScope(Enum):
    """Service lifecycle scope."""

    SINGLETON = "singleton"  # One instance for entire application
    TRANSIENT = "transient"  # New instance on each resolve


@dataclass
class ServiceDescriptor:
    """Metadata about a registered service."""

    service_type: type
    scope: ServiceScope = ServiceScope.SINGLETON
    instance: Any | None = None
    factory: Callable[[], Any] | None = None
    on_shutdown: Callable[[Any], None] | None = None
    registered_at: float = field(default_factory=time.time)
    resolve_count: int = 0
    last_resolved_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for stats/logging."""
        return {
            "type": self.service_type.__name__,
            "scope": self.scope.value,
            "has_instance": self.instance is not None,
            "has_factory": self.factory is not None,
            "has_shutdown_hook": self.on_shutdown is not None,
            "resolve_count": self.resolve_count,
            "registered_at": self.registered_at,
            "last_resolved_at": self.last_resolved_at,
        }


@dataclass
class RegistryStats:
    """Statistics about the service registry."""

    total_services: int
    singleton_count: int
    transient_count: int
    initialized_count: int
    pending_count: int
    total_resolves: int
    services: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_services": self.total_services,
            "singleton_count": self.singleton_count,
            "transient_count": self.transient_count,
            "initialized_count": self.initialized_count,
            "pending_count": self.pending_count,
            "total_resolves": self.total_resolves,
            "services": self.services,
        }


class ServiceNotFoundError(Exception):
    """Raised when a requested service is not registered."""

    def __init__(self, service_type: type) -> None:
        self.service_type = service_type
        super().__init__(f"Service not found: {service_type.__name__}")


class ServiceRegistry:
    """
    Thread-safe singleton registry for application services.

    Provides centralized management of services that would otherwise be
    scattered global singletons. Supports both direct instance registration
    and lazy factory registration.

    Example:
        # Get the singleton registry
        registry = ServiceRegistry.get()

        # Register a service instance
        registry.register(TierManager, tier_manager)

        # Or register a factory for lazy initialization
        registry.register_factory(TierManager, TierManager)

        # Resolve a service
        tier_manager = registry.resolve(TierManager)

        # Check if service exists
        if registry.has(TierManager):
            ...

        # Reset for testing
        registry.reset()
    """

    _instance: ServiceRegistry | None = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the service registry."""
        self._services: dict[type, Any] = {}
        self._factories: dict[type, Callable[[], Any]] = {}
        self._service_lock = threading.RLock()

    @classmethod
    def get(cls) -> ServiceRegistry:
        """
        Get the singleton registry instance.

        Thread-safe lazy initialization.

        Returns:
            The global ServiceRegistry instance.
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    logger.debug("ServiceRegistry initialized")
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """
        Reset the registry, clearing all services.

        Primarily used for testing to ensure clean state between tests.
        Also useful when reconfiguring the application.
        """
        with cls._lock:
            if cls._instance is not None:
                cls._instance._services.clear()
                cls._instance._factories.clear()
                logger.debug("ServiceRegistry reset - all services cleared")
            cls._instance = None

    def register(self, service_type: type[T], instance: T) -> None:
        """
        Register a service instance.

        Args:
            service_type: The type to register the service under.
            instance: The service instance.

        Example:
            registry.register(TierManager, TierManager())
        """
        with self._service_lock:
            if service_type in self._services:
                logger.warning("Overwriting existing service: %s", service_type.__name__)
            self._services[service_type] = instance
            # Remove factory if we're providing direct instance
            self._factories.pop(service_type, None)
            logger.debug("Registered service: %s", service_type.__name__)

    def register_factory(
        self,
        service_type: type[T],
        factory: Callable[[], T],
    ) -> None:
        """
        Register a factory for lazy service initialization.

        The factory will be called on first resolve() and the result cached.

        Args:
            service_type: The type to register the factory under.
            factory: A callable that returns the service instance.

        Example:
            registry.register_factory(TierManager, TierManager)
            # or with configuration:
            registry.register_factory(
                TierManager,
                lambda: TierManager(custom_config)
            )
        """
        with self._service_lock:
            self._factories[service_type] = factory
            # Remove cached instance to trigger factory on next resolve
            self._services.pop(service_type, None)
            logger.debug("Registered factory: %s", service_type.__name__)

    @overload
    def resolve(self, service_type: type[T]) -> T: ...

    @overload
    def resolve(self, service_type: type[T], default: T | None) -> T | None: ...

    def resolve(
        self,
        service_type: type[T],
        default: T | None = None,
    ) -> T | None:
        """
        Resolve a service by type.

        If a factory is registered, it will be called and the result cached.

        Args:
            service_type: The type of service to resolve.
            default: Default value if service not found (None raises exception).

        Returns:
            The service instance.

        Raises:
            ServiceNotFoundError: If no service or factory is registered
                and no default is provided.

        Example:
            tier_manager = registry.resolve(TierManager)
            # With default:
            tier_manager = registry.resolve(TierManager, default=TierManager())
        """
        with self._service_lock:
            # Check for cached instance
            if service_type in self._services:
                result: T = self._services[service_type]
                return result

            # Check for factory
            if service_type in self._factories:
                factory = self._factories[service_type]
                instance: T = factory()
                self._services[service_type] = instance
                logger.debug("Lazily initialized service: %s", service_type.__name__)
                return instance

            # Not found - use default or raise
            if default is not None:
                return default

            raise ServiceNotFoundError(service_type)

    def has(self, service_type: type) -> bool:
        """
        Check if a service is registered.

        Returns True if either an instance or factory is registered.

        Args:
            service_type: The type to check.

        Returns:
            True if service is available.
        """
        with self._service_lock:
            return service_type in self._services or service_type in self._factories

    def unregister(self, service_type: type) -> bool:
        """
        Unregister a service.

        Args:
            service_type: The type to unregister.

        Returns:
            True if service was found and removed.
        """
        with self._service_lock:
            found = False
            if service_type in self._services:
                del self._services[service_type]
                found = True
            if service_type in self._factories:
                del self._factories[service_type]
                found = True
            if found:
                logger.debug("Unregistered service: %s", service_type.__name__)
            return found

    def list_services(self) -> list[str]:
        """
        List all registered service type names.

        Returns:
            List of service type names.
        """
        with self._service_lock:
            types = set(self._services.keys()) | set(self._factories.keys())
            return sorted(t.__name__ for t in types)

    def stats(self) -> RegistryStats:
        """
        Get statistics about registered services.

        Returns:
            RegistryStats with service counts and details.
        """
        with self._service_lock:
            all_types = set(self._services.keys()) | set(self._factories.keys())

            services_info = []
            total_resolves = 0

            for service_type in all_types:
                has_instance = service_type in self._services
                has_factory = service_type in self._factories
                services_info.append(
                    {
                        "type": service_type.__name__,
                        "initialized": has_instance,
                        "has_factory": has_factory,
                    }
                )

            return RegistryStats(
                total_services=len(all_types),
                singleton_count=len(all_types),  # All are singletons in basic impl
                transient_count=0,
                initialized_count=len(self._services),
                pending_count=len(self._factories)
                - len(set(self._factories.keys()) & set(self._services.keys())),
                total_resolves=total_resolves,
                services=services_info,
            )

    def shutdown(self) -> int:
        """
        Gracefully shutdown all services with registered shutdown hooks.

        Calls shutdown hooks in reverse registration order.
        Safe to call multiple times (no-op after first call).

        Returns:
            Number of shutdown hooks called.
        """
        with self._service_lock:
            hooks_called = 0

            # For services with close/shutdown methods, try to call them
            for service_type, instance in list(self._services.items()):
                # Check for common cleanup method names
                for method_name in ("close", "shutdown", "cleanup", "dispose"):
                    if hasattr(instance, method_name):
                        try:
                            method = getattr(instance, method_name)
                            if callable(method):
                                method()
                                hooks_called += 1
                                logger.debug(
                                    "Called %s() on %s", method_name, service_type.__name__
                                )
                                break  # Only call one cleanup method
                        except (RuntimeError, TypeError, ValueError, OSError) as e:
                            logger.warning(
                                "Error calling %s() on %s: %s",
                                method_name,
                                service_type.__name__,
                                e,
                            )

            logger.info("ServiceRegistry shutdown complete (%s hooks called)", hooks_called)
            return hooks_called


# Module-level convenience functions


@overload
def get_service(service_type: type[T]) -> T: ...


@overload
def get_service(service_type: type[T], default: T | None) -> T | None: ...


def get_service(service_type: type[T], default: T | None = None) -> T | None:
    """
    Get a service from the global registry.

    Args:
        service_type: The type of service to get.
        default: Default value if not found.

    Returns:
        The service instance.

    Raises:
        ServiceNotFoundError: If not found and no default provided.
    """
    return ServiceRegistry.get().resolve(service_type, default)


def register_service(service_type: type[T], instance: T) -> None:
    """
    Register a service in the global registry.

    Args:
        service_type: The type to register under.
        instance: The service instance.
    """
    ServiceRegistry.get().register(service_type, instance)


def has_service(service_type: type) -> bool:
    """
    Check if a service is registered.

    Args:
        service_type: The type to check.

    Returns:
        True if service is available.
    """
    return ServiceRegistry.get().has(service_type)
