"""Compatibility re-export of :mod:`aragora.observability.audit_persistence.postgres`."""

from __future__ import annotations

from aragora.observability.audit_persistence.postgres import (
    POSTGRES_SCHEMA,
    PostgresBackend,
)

__all__ = ["POSTGRES_SCHEMA", "PostgresBackend"]
