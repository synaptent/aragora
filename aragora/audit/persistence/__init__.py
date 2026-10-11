"""Compatibility re-export of :mod:`aragora.observability.audit_persistence`.

The audit log persistence backends moved to the observability layer with the
audit log that uses them. Every name below is the identical object; the
``base``, ``file`` and ``postgres`` submodule paths re-export theirs too.
"""

from __future__ import annotations

from aragora.observability.audit_persistence import (
    AuditPersistenceBackend,
    FileBackend,
    PostgresBackend,
    get_backend,
)

__all__ = [
    "AuditPersistenceBackend",
    "FileBackend",
    "PostgresBackend",
    "get_backend",
]
