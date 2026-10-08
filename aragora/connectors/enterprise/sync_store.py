"""Deprecated compatibility imports for the relocated sync store."""

from __future__ import annotations

import warnings

warnings.warn(
    "aragora.connectors.enterprise.sync_store is deprecated; "
    "import from aragora.storage.sync_store instead.",
    DeprecationWarning,
    stacklevel=2,
)

from aragora.storage.sync_store import (  # noqa: E402, F401
    CREDENTIAL_KEYWORDS,
    CRYPTO_AVAILABLE,
    METRICS_AVAILABLE,
    ConnectorConfig,
    EncryptionError,
    SyncJob,
    SyncStore,
    _decrypt_config,
    _encrypt_config,
    _is_sensitive_key,
    get_encryption_service,
    get_sync_store,
    is_encryption_required,
    record_encryption_error,
    record_encryption_operation,
)

__all__ = [
    "SyncStore",
    "SyncJob",
    "ConnectorConfig",
    "get_sync_store",
]
