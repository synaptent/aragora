"""
GovernanceStore - Database persistence for decision governance artifacts.

Provides durable storage for:
- Approval requests (human-in-the-loop decisions)
- Verification history (formal verification results)
- Decision records (debate outcomes with provenance)
- Rollback points (safety checkpoints)

Supports SQLite (default) and PostgreSQL backends.

Usage:
    from aragora.storage.governance_store import GovernanceStore

    store = GovernanceStore()

    # Save approval request
    store.save_approval(approval_request)

    # Query pending approvals
    pending = store.list_approvals(status="pending")

    # Save verification result
    store.save_verification(verification_entry)

.. note::
    This module is a backwards-compatible re-export shim.
    The implementation has been split into submodules under
    ``aragora.storage.governance``:

    - ``models`` -- ApprovalRecord, VerificationRecord, DecisionRecord
    - ``store`` -- GovernanceStore (sync SQLite/PostgreSQL)
    - ``postgres_store`` -- PostgresGovernanceStore (async PostgreSQL)
    - ``factory`` -- get_governance_store, reset_governance_store
    - ``metrics`` -- observability metric helpers
"""

from __future__ import annotations

# Re-export everything from the governance subpackage so that all existing
# imports of the form ``from aragora.storage.governance_store import X``
# continue to work without modification.

from aragora.storage.governance.factory import (
    get_governance_store,
    reset_governance_store,
)
from aragora.storage.governance.models import (
    ApprovalRecord,
    DecisionRecord,
    VerificationRecord,
)
from aragora.storage.governance.postgres_store import (
    PostgresGovernanceStore,
)
from aragora.storage.governance.store import GovernanceStore

__all__ = [
    "GovernanceStore",
    "PostgresGovernanceStore",
    "ApprovalRecord",
    "VerificationRecord",
    "DecisionRecord",
    "get_governance_store",
    "reset_governance_store",
]
