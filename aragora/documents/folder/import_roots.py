"""Per-org folder import roots from ``ARAGORA_ORG_IMPORT_ROOTS``.

The setting is a JSON object mapping an org id to a list of absolute directories
and is read on every request. A root counts only if it resolves to an existing
directory that does not equal, contain or lie inside a protected server path or
another org's root (overlapping roots are rejected for both orgs). Rejected
roots are logged and grant nothing.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from aragora.persistence.db_config import get_default_data_dir

logger = logging.getLogger(__name__)

ORG_IMPORT_ROOTS_ENV = "ARAGORA_ORG_IMPORT_ROOTS"
LEGACY_UPLOAD_DIRS_ENV = "ARAGORA_ALLOWED_UPLOAD_DIRS"

# Settings naming a key, credential or certificate file the server may read;
# the directory holding each file is protected.
SECRET_FILE_ENV_VARS = tuple(
    """ARAGORA_ODR_SIGNING_KEY_FILE ARAGORA_INBOX_TRUST_WEDGE_KEY_FILE ARAGORA_API_KEY_STORE_PATH
    ARAGORA_X_OAUTH_TOKEN_PATH ARAGORA_TLS_CERT_PATH ARAGORA_TLS_KEY_PATH ARAGORA_SSL_CERT
    ARAGORA_SSL_KEY ARAGORA_GITHUB_APP_PRIVATE_KEY_PATH GITHUB_APP_PRIVATE_KEY_PATH
    GH_APP_PRIVATE_KEY_PATH ERC8004_KEYSTORE_PATH SNOWFLAKE_PRIVATE_KEY_PATH
    GOOGLE_APPLICATION_CREDENTIALS GOOGLE_CHAT_CREDENTIALS GOOGLE_HOME_CREDENTIALS
    AWS_WEB_IDENTITY_TOKEN_FILE""".split()
)
_SECRET_FILE_DEFAULTS = {
    "ARAGORA_API_KEY_STORE_PATH": "~/.aragora/api_keys.json",
    "ARAGORA_X_OAUTH_TOKEN_PATH": ".aragora/x_intake/oauth.json",
}


def _resolve(value: Any) -> Path | None:
    if not isinstance(value, (str, os.PathLike)):
        return None
    try:
        return Path(value).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _overlaps(a: Path, b: Path) -> bool:
    return a.is_relative_to(b) or b.is_relative_to(a)


def _reject(root: Any, org: Any, reason: str) -> None:
    logger.error("%s: root %r of org %s %s; ignored", ORG_IMPORT_ROOTS_ENV, root, org, reason)


def inside_roots(path: Any, roots: Sequence[Path]) -> bool:
    """Whether ``path`` resolves (symlinks and ``..`` included) inside one of ``roots``."""
    resolved = _resolve(path)
    return resolved is not None and any(resolved.is_relative_to(root) for root in roots)


def protected_paths(nomic_dir: Any = None, document_store_dir: Any = None) -> list[Path]:
    """Resolved server paths that no import root may equal, contain or lie inside."""
    data_dir = get_default_data_dir()
    candidates = [data_dir, data_dir / "nomic" / "documents", nomic_dir, document_store_dir]
    for name in SECRET_FILE_ENV_VARS:
        value = os.environ.get(name) or _SECRET_FILE_DEFAULTS.get(name)
        # Credential settings that also accept inline JSON or PEM content name no file.
        if value and "\n" not in value and not value.lstrip().startswith(("{", "-----")):
            candidates.append(Path(value).expanduser().parent)
    return [path for path in map(_resolve, candidates) if path is not None]


def org_import_roots(org_id: str, protected: Iterable[Path]) -> list[Path]:
    """Valid import roots of ``org_id``; empty when the org may not import folders."""
    if os.environ.get(LEGACY_UPLOAD_DIRS_ENV, "").strip():
        logger.warning("%s is ignored; configure %s", LEGACY_UPLOAD_DIRS_ENV, ORG_IMPORT_ROOTS_ENV)
    try:
        mapping = json.loads(os.environ.get(ORG_IMPORT_ROOTS_ENV, "").strip() or "{}")
    except ValueError:
        mapping = None
    if not isinstance(mapping, dict):
        logger.error("%s must be a JSON object of org id to directories", ORG_IMPORT_ROOTS_ENV)
        return []

    protected = list(protected)
    candidates: list[tuple[str, Path]] = []
    for org, entries in mapping.items():
        for entry in entries if isinstance(entries, list) else [entries]:
            root = _resolve(entry) if isinstance(entry, str) and os.path.isabs(entry) else None
            if root is None or not isinstance(entries, list) or not root.is_dir():
                _reject(entry, org, "is not an absolute existing directory in a list")
            elif any(_overlaps(root, path) for path in protected):
                _reject(entry, org, "overlaps a protected server path")
            else:
                candidates.append((str(org), root))

    roots: list[Path] = []
    for org, root in candidates:
        if any(other_org != org and _overlaps(root, other) for other_org, other in candidates):
            _reject(str(root), org, "overlaps a root of another org")
        elif org == org_id:
            roots.append(root)
    return roots
