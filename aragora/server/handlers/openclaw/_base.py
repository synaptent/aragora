"""
Shared base for OpenClaw Gateway mixin classes.

Stability: STABLE

Provides:
- OpenClawMixinBase: Base class with method stubs required by all mixins
- _has_permission: Permission check helper with compatibility shim
"""

from __future__ import annotations

from typing import Any

from aragora.server.handlers.utils.decorators import has_permission


def _has_permission(role: Any, permission: str) -> bool:
    """Resolve permission checks via the compatibility shim when patched.

    Checks if the openclaw_gateway module has overridden has_permission
    (for testing or backwards compatibility), and delegates accordingly.
    """
    try:
        import sys

        gateway_module = sys.modules.get("aragora.server.handlers.openclaw.openclaw_gateway")
        override = getattr(gateway_module, "has_permission", None) if gateway_module else None
        if override is not None and override is not has_permission:
            return override(role, permission)
    except (ImportError, AttributeError, TypeError, KeyError) as e:
        import logging

        logging.getLogger(__name__).debug("Permission shim lookup failed: %s", e)
    return has_permission(role, permission)


class OpenClawMixinBase:
    """Base class declaring methods required by OpenClaw handler mixins.

    All OpenClaw mixins (SessionOrchestrationMixin, CredentialHandlerMixin,
    PolicyHandlerMixin) require these methods from the parent class
    (OpenClawGatewayHandler). Declaring them here once avoids duplication
    and provides clear runtime errors if a mixin is used without the parent.
    """

    def _get_user_id(self, handler: Any) -> str:
        """Get user ID from handler. Must be overridden by parent class."""
        raise NotImplementedError(
            f"{self.__class__.__name__}._get_user_id() must be implemented by "
            f"parent class (e.g., OpenClawGatewayHandler). "
            f"Current MRO: {[c.__name__ for c in self.__class__.__mro__[:5]]}"
        )

    def _get_tenant_id(self, handler: Any) -> str | None:
        """Get tenant ID from handler. Must be overridden by parent class."""
        raise NotImplementedError(
            f"{self.__class__.__name__}._get_tenant_id() must be implemented by "
            f"parent class (e.g., OpenClawGatewayHandler). "
            f"Current MRO: {[c.__name__ for c in self.__class__.__mro__[:5]]}"
        )

    def get_current_user(self, handler: Any) -> Any:
        """Get current user from handler. Must be overridden by parent class."""
        raise NotImplementedError(
            f"{self.__class__.__name__}.get_current_user() must be implemented by "
            f"parent class (e.g., OpenClawGatewayHandler). "
            f"Current MRO: {[c.__name__ for c in self.__class__.__mro__[:5]]}"
        )


__all__ = [
    "OpenClawMixinBase",
    "_has_permission",
]
