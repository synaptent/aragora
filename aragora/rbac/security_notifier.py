"""Security-team notifications for RBAC events, supplied by the control plane.

Break-glass access must alert the security team, but the RBAC layer cannot import
the control plane that owns notification delivery. ``aragora.control_plane``
registers a sender here when it is imported, and a process that never imports it
reaches that registration through the ``aragora.security_notifiers`` entry point.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from aragora.utils.declared_registrations import DeclaredRegistrations

logger = logging.getLogger(__name__)

SECURITY_NOTIFIERS_ENTRY_POINT_GROUP = "aragora.security_notifiers"


class SecurityNotifier(Protocol):
    """Sends one notification to the security team; returns whether it was delivered."""

    async def __call__(
        self,
        *,
        title: str,
        message: str,
        severity: str = "medium",
        metadata: dict[str, Any] | None = None,
    ) -> bool: ...


_notifier: SecurityNotifier | None = None
_declared_registrations = DeclaredRegistrations(SECURITY_NOTIFIERS_ENTRY_POINT_GROUP)


def register_security_notifier(notifier: SecurityNotifier) -> bool:
    """Register the sender used for security-team notifications.

    Registering the same sender again is a no-op; a different sender replaces the
    current one.

    Returns:
        True when the sender was installed, False when it was already registered.
    """
    global _notifier
    if _notifier is notifier:
        return False
    if _notifier is not None:
        logger.debug("Replacing security notifier %r with %r", _notifier, notifier)
    _notifier = notifier
    return True


def registered_count() -> int:
    """Return how many security notifiers are registered (0 or 1)."""
    return 0 if _notifier is None else 1


def get_security_notifier() -> SecurityNotifier | None:
    """Return the registered sender, running the declared registrations if none is set.

    Returns:
        The sender, or None when nothing registered one.
    """
    if _notifier is None:
        _declared_registrations.load()
    return _notifier


__all__ = [
    "SECURITY_NOTIFIERS_ENTRY_POINT_GROUP",
    "SecurityNotifier",
    "get_security_notifier",
    "register_security_notifier",
    "registered_count",
]
