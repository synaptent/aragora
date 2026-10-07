"""Layer-neutral approval mappings shared by security enforcement adapters.

Security owns these tables so that the structural adapters in
``aragora.security.approval_enforcer`` and the concrete adapters registered by
higher layers (``aragora.ops.security_edge_adapters``) resolve action types and
approval categories from one source. Values are plain strings; higher layers
convert them to their own enums, so this module imports nothing above the
security layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType
from typing import Any


class PolicyActionType(str, Enum):
    """Action types that security enforcement submits to policy evaluation."""

    SHELL = "shell"
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    BROWSER = "browser"
    API = "api"
    SCREENSHOT = "screenshot"
    KEYBOARD = "keyboard"
    MOUSE = "mouse"


POLICY_ACTION_TYPES: Mapping[str, PolicyActionType] = MappingProxyType(
    {member.value: member for member in PolicyActionType}
)
"""Policy-controlled action type strings mapped to their canonical member."""

APPROVAL_SOURCE_CATEGORIES: Mapping[str, str] = MappingProxyType(
    {
        "gateway": "system_modification",
        "device": "external_system",
        "computer_use": "destructive_action",
    }
)
"""Enforcement request source mapped to its approval category value."""

APPROVAL_CATEGORY_UNKNOWN = "unknown"
"""Approval category value for sources missing from ``APPROVAL_SOURCE_CATEGORIES``."""


def resolve_policy_action_type(action_type: str) -> PolicyActionType | None:
    """Return the canonical policy action type, or ``None`` when not policy-controlled."""
    return POLICY_ACTION_TYPES.get(action_type)


def convert_policy_action_type(action_type: str, action_types: Any) -> Any | None:
    """Convert ``action_type`` to the same-named member of a higher-layer action enum.

    Returns ``None`` for action types that are not policy-controlled.
    """
    canonical = resolve_policy_action_type(action_type)
    if canonical is None:
        return None
    return getattr(action_types, canonical.name)


def unknown_action_type_reason(action_type: str) -> str:
    """Reason reported when an action type is not policy-controlled."""
    return f"Unknown action type '{action_type}'; not policy-controlled"


def approval_category_for_source(source: str) -> str:
    """Return the approval category value for an enforcement request source."""
    return APPROVAL_SOURCE_CATEGORIES.get(source, APPROVAL_CATEGORY_UNKNOWN)


__all__ = [
    "APPROVAL_CATEGORY_UNKNOWN",
    "APPROVAL_SOURCE_CATEGORIES",
    "POLICY_ACTION_TYPES",
    "PolicyActionType",
    "approval_category_for_source",
    "convert_policy_action_type",
    "resolve_policy_action_type",
    "unknown_action_type_reason",
]
