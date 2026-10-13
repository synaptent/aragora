"""Webhook handlers for management APIs and external integrations."""

# Aliased so the deprecation shim adds nothing to the package's public surface.
from typing import Any as _Any

import importlib as importlib  # Compatibility: historically a public package attribute.
import warnings as _warnings

from aragora.server.handlers import webhook_management as _webhooks_module
from aragora.server.handlers.webhooks.github_app import (
    GITHUB_APP_ROUTES,
    handle_github_webhook,
)

# Management names that historically lived here; their one canonical home is
# webhook_management, so resolving them through this package warns the caller.
_DEPRECATED_MANAGEMENT_EXPORTS = frozenset(
    {
        "WebhookHandler",
        "WebhookStore",
        "WebhookConfig",
        "get_webhook_store",
        "generate_signature",
        "verify_signature",
        "WEBHOOK_EVENTS",
        "RBAC_AVAILABLE",
        "check_permission",
        "validate_webhook_url",
    }
)

__all__ = [
    "GITHUB_APP_ROUTES",
    "handle_github_webhook",
    "WebhookHandler",
    "WebhookStore",
    "WebhookConfig",
    "get_webhook_store",
    "generate_signature",
    "verify_signature",
    "WEBHOOK_EVENTS",
    "RBAC_AVAILABLE",
    "check_permission",
    "validate_webhook_url",
]


def __getattr__(name: str) -> _Any:
    if name in _DEPRECATED_MANAGEMENT_EXPORTS:
        # Deliberately not cached in module globals: every retired-path import
        # must see the warning, and the module dict stays access-order-stable.
        _warnings.warn(
            "aragora.server.handlers.webhooks is deprecated as the webhook "
            f"management implementation home; import {name} from "
            "aragora.server.handlers.webhook_management instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(_webhooks_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
