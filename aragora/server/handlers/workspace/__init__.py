"""
Workspace Handler Package - Enterprise Privacy and Data Isolation APIs.

This package provides API endpoints for workspace and privacy management:
- Workspace creation and management
- Data isolation and access control
- Retention policy management
- Sensitivity classification
- Privacy audit logging

The package is structured as follows:
- workspace_utils.py: Circuit breaker and validation utilities
- crud.py: Workspace CRUD operations mixin
- policies.py: Retention policy management mixin
- members.py: Member management and RBAC profiles mixin
- invites.py: Workspace invite management mixin
- settings.py: Classification and audit endpoints mixin

For backwards compatibility, all public exports are available directly from this package.

Stability: STABLE

Example usage:
    from aragora.server.handlers.workspace import WorkspaceHandler
    from aragora.server.handlers.workspace import WorkspaceCircuitBreaker
    from aragora.server.handlers.workspace import get_workspace_circuit_breaker_status
"""

from __future__ import annotations

import importlib
from typing import Any

# Import utilities from workspace_utils submodule
from .workspace_utils import (
    WorkspaceCircuitBreaker,
    _get_workspace_circuit_breaker,
    get_workspace_circuit_breaker_status,
    _validate_workspace_id,
    _validate_policy_id,
    _validate_user_id,
)

__all__ = [
    # Main handler
    "WorkspaceHandler",
    # Mixin classes
    "WorkspaceCrudMixin",
    "WorkspacePoliciesMixin",
    "WorkspaceMembersMixin",
    "WorkspaceInvitesMixin",
    "WorkspaceSettingsMixin",
    "WorkspaceActivityMixin",
    # Feature flags (for test patching compatibility)
    "RBAC_AVAILABLE",
    "PROFILES_AVAILABLE",
    # Re-exported for test patching compatibility
    "extract_user_from_request",
    "PrivacyAuditLog",
    "SensitivityLevel",
    "DataIsolationManager",
    "RetentionPolicyManager",
    "SensitivityClassifier",
    # Circuit breaker
    "WorkspaceCircuitBreaker",
    "get_workspace_circuit_breaker_status",
    "_get_workspace_circuit_breaker",
    # Validation utilities
    "_validate_workspace_id",
    "_validate_policy_id",
    "_validate_user_id",
]


_WORKSPACE_EXPORTS = {
    "WorkspaceHandler",
    "WorkspaceCrudMixin",
    "WorkspacePoliciesMixin",
    "WorkspaceMembersMixin",
    "WorkspaceInvitesMixin",
    "WorkspaceSettingsMixin",
    "WorkspaceActivityMixin",
    "RBAC_AVAILABLE",
    "PROFILES_AVAILABLE",
    "extract_user_from_request",
    "PrivacyAuditLog",
    "SensitivityLevel",
    "DataIsolationManager",
    "RetentionPolicyManager",
    "SensitivityClassifier",
}


def __getattr__(name: str) -> Any:
    if name in _WORKSPACE_EXPORTS:
        module = importlib.import_module("aragora.server.handlers.workspace.workspace_module")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
