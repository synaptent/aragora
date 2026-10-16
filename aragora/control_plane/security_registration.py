"""Registers the control plane's security notifications with :mod:`aragora.rbac.security_notifier`."""

from __future__ import annotations

from typing import Any

from aragora.control_plane import notifications as _notifications
from aragora.rbac.security_notifier import register_security_notifier


async def notify_security_team(
    *,
    title: str,
    message: str,
    severity: str = "medium",
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Send a security-team notification through the default notification dispatcher."""
    # Read at call time so a patched ``notifications.send_security_notification`` applies.
    return await _notifications.send_security_notification(
        title=title, message=message, severity=severity, metadata=metadata
    )


def register_rbac_security_notifier() -> bool:
    """Register :func:`notify_security_team` for RBAC break-glass events.

    Returns:
        True when newly registered, False when it was already registered.
    """
    return register_security_notifier(notify_security_team)


__all__ = ["notify_security_team", "register_rbac_security_notifier"]
