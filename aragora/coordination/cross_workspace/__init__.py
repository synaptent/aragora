"""
Cross-workspace coordination (compatibility path).

The coordinator lives in :mod:`aragora.tenancy.cross_workspace`; this module
re-exports the same objects. The shared coordinator returned by
``get_coordinator`` lives only in the new module; patch or reset it there.
"""

from __future__ import annotations

from aragora.tenancy.cross_workspace import (
    CrossWorkspaceCoordinator,
    CrossWorkspaceOperation,
    CrossWorkspaceRequest,
    CrossWorkspaceResult,
    DataSharingConsent,
    FederatedWorkspace,
    FederationMode,
    FederationPolicy,
    OperationType,
    SharingScope,
    get_coordinator,
)

__all__ = [
    "CrossWorkspaceCoordinator",
    "CrossWorkspaceOperation",
    "FederatedWorkspace",
    "FederationPolicy",
    "FederationMode",
    "CrossWorkspaceRequest",
    "CrossWorkspaceResult",
    "DataSharingConsent",
    "SharingScope",
    "OperationType",
    "get_coordinator",
]
