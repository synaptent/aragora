"""
Audit Log Persistence Backends.

Provides pluggable storage backends for audit log persistence:
- SQLite (default, embedded)
- PostgreSQL (enterprise, distributed)
- File/JSON (SMB, simple deployments)

Usage:
    from aragora.observability.audit_persistence import get_backend, FileBackend, PostgresBackend

    # Auto-detect from environment
    backend = get_backend()

    # Or explicit backend
    backend = FileBackend("/var/log/aragora/audit")
    backend = PostgresBackend(database_url)
"""

from .base import AuditPersistenceBackend
from .file import FileBackend
from .postgres import PostgresBackend

__all__ = [
    "AuditPersistenceBackend",
    "FileBackend",
    "PostgresBackend",
    "get_backend",
]


def get_backend(
    backend_type: str | None = None,
    **kwargs,
) -> AuditPersistenceBackend:
    """
    Get appropriate persistence backend based on configuration.

    Priority:
    1. Explicit backend_type parameter
    2. ARAGORA_AUDIT_STORE_BACKEND environment variable
    3. ARAGORA_DB_BACKEND environment variable
    4. Default to file backend

    Args:
        backend_type: "postgres", "file", or "sqlite"
        **kwargs: Backend-specific configuration

    Returns:
        Configured persistence backend
    """
    import os
    from pathlib import Path

    if not backend_type:
        backend_type = os.environ.get("ARAGORA_AUDIT_STORE_BACKEND")
    if not backend_type:
        backend_type = os.environ.get("ARAGORA_DB_BACKEND", "file")

    backend_type = backend_type.lower()

    if backend_type in ("postgres", "postgresql"):
        database_url = kwargs.get("database_url") or (
            os.environ.get("ARAGORA_POSTGRES_DSN")
            or os.environ.get("DATABASE_URL")
            or os.environ.get("ARAGORA_DATABASE_URL")
        )
        if not database_url:
            raise ValueError(
                "PostgreSQL backend requires database_url or DATABASE_URL environment variable"
            )
        return PostgresBackend(database_url)

    elif backend_type == "file":
        storage_path = kwargs.get("storage_path")
        if not storage_path:
            from aragora.persistence.db_config import get_nomic_dir

            storage_path = get_nomic_dir() / "audit_logs"
        return FileBackend(Path(storage_path))

    else:
        # SQLite is handled by the main AuditLog class for backwards compatibility
        raise ValueError(f"Unknown backend type: {backend_type}. Use 'postgres' or 'file'.")
