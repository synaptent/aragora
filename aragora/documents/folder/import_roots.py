"""Per-org folder import roots from ``ARAGORA_ORG_IMPORT_ROOTS``.

The setting is a JSON object mapping an org id to a list of absolute directories
and is read on every request. A root counts only if it resolves to an existing
directory that does not equal, contain or lie inside a protected server path or
another org's root (overlapping roots are rejected for both orgs). Rejected
roots are logged and grant nothing.

An authorized folder is opened and read with ``open_folder`` and
``read_file_in_folder``, which never follow a symlink below the import root, so
swapping a directory or file for a link after the check cannot move the read
outside the folder.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePath
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
            configured = Path(value).expanduser()
            target = _resolve(configured)  # a symlinked key file is protected where it lives
            candidates += [configured.parent] + ([target.parent] if target else [])
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
    # Every resolvable root takes part in the cross-org overlap check, even one rejected
    # for another reason, so an invalid root never leaves an overlapping one usable.
    configured: list[tuple[str, Any, Path, bool]] = []
    for org, entries in mapping.items():
        for entry in entries if isinstance(entries, list) else [entries]:
            root = _resolve(entry) if isinstance(entry, str) and os.path.isabs(entry) else None
            usable = root is not None and isinstance(entries, list) and root.is_dir()
            if not usable:
                _reject(entry, org, "is not an absolute existing directory in a list")
            if root is not None:
                configured.append((str(org), entry, root, usable))

    roots: list[Path] = []
    for org, entry, root, usable in configured:
        if not usable:
            continue
        if any(_overlaps(root, path) for path in protected):
            _reject(entry, org, "overlaps a protected server path")
        elif any(other != org and _overlaps(root, r) for other, _, r, _ in configured):
            _reject(entry, org, "overlaps a root of another org")
        elif org == org_id:
            roots.append(root)
    return roots


def _nofollow_supported() -> bool:
    flags = ("O_NOFOLLOW", "O_DIRECTORY")
    return all(hasattr(os, flag) for flag in flags) and os.open in os.supports_dir_fd


def _open_below(dir_fd: int, rel: PurePath, last_flags: int) -> int:
    """Open ``rel`` below ``dir_fd`` one name at a time, failing on any symlink."""
    if not _nofollow_supported() or rel.is_absolute() or ".." in rel.parts:
        raise PermissionError("cannot open a path confined below a directory")
    fd = os.dup(dir_fd)
    try:
        for index, name in enumerate(rel.parts):
            last = index == len(rel.parts) - 1
            flags = last_flags if last else os.O_RDONLY | os.O_DIRECTORY
            child = os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd


def open_folder(folder: Path, roots: Sequence[Path]) -> int:
    """Directory fd of the authorized, already resolved ``folder``.

    ``folder`` is not resolved again: it is opened from the import root that
    contains it without following any symlink, so a folder swapped for a link
    after the request fails to open instead of becoming the new boundary.
    """
    root = next((r for r in roots if folder.is_relative_to(r)), None)
    if root is None:
        raise PermissionError("folder is outside the import roots")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        return _open_below(root_fd, folder.relative_to(root), os.O_RDONLY | os.O_DIRECTORY)
    finally:
        os.close(root_fd)


def still_folder(folder_fd: int, folder: Path) -> bool:
    """Whether ``folder`` still names the directory held open as ``folder_fd``."""
    try:
        now, held = os.stat(folder), os.fstat(folder_fd)
    except OSError:
        return False
    return (now.st_dev, now.st_ino) == (held.st_dev, held.st_ino)


def file_in_folder(folder: Path, path: Any) -> PurePath | None:
    """Location of ``path`` relative to ``folder`` once resolved; None when it leaves it."""
    resolved = _resolve(path)
    if resolved is None or not resolved.is_relative_to(folder):
        return None
    return resolved.relative_to(folder)


def read_file_in_folder(folder_fd: int, rel: PurePath, limit: int) -> bytes:
    """Read at most ``limit`` bytes of the regular file ``rel`` below ``folder_fd``.

    Every name is opened with O_NOFOLLOW, so an entry swapped for a link after
    ``file_in_folder`` checked it fails to open instead of being read.
    """
    fd = _open_below(folder_fd, rel, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise PermissionError("not a regular file")
        return handle.read(limit)
