"""Compatibility re-export of :mod:`aragora.observability.audit_persistence.base`."""

from __future__ import annotations

from aragora.observability.audit_persistence.base import (
    AuditPersistenceBackend,
    PersistenceError,
)

__all__ = ["AuditPersistenceBackend", "PersistenceError"]
