"""
Environment helpers.

Centralizes environment-variable parsing to avoid scattered ad-hoc checks.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_TRUTHY = {"1", "true", "yes", "y", "on"}
_FALSY = {"0", "false", "no", "n", "off"}


def is_truthy_env(name: str, *, default: bool = False) -> bool:
    """Return True/False for common env var boolean encodings."""
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    return default


def is_offline_mode() -> bool:
    """Offline mode disables network-backed features by convention."""
    return is_truthy_env("ARAGORA_OFFLINE", default=False)


@contextmanager
def preserve_environ() -> Iterator[None]:
    """Roll back any os.environ mutation made inside the block.

    Use around imports of third-party packages with import-time environment
    side effects. The official ``rlm`` package calls ``dotenv.load_dotenv()``
    when ``rlm.clients`` is imported; under pytest-xdist (execnet) workers
    python-dotenv searches from the current working directory upward, so the
    import can inject a repository ``.env`` (including flags like
    ARAGORA_SECRETS_STRICT) into the whole process (#8277).
    """
    snapshot = dict(os.environ)
    try:
        yield
    finally:
        for key in set(os.environ) - snapshot.keys():
            del os.environ[key]
        for key, value in snapshot.items():
            if os.environ.get(key) != value:
                os.environ[key] = value


_RLM_IMPORT_LOCK = threading.Lock()


def import_rlm_guarded() -> Any:
    """Import the optional ``rlm`` package exactly once, environ-safely.

    ``preserve_environ`` alone is not thread-safe: two concurrent first-calls
    snapshot/restore the whole environ and their interleaved restores can
    persist the very pollution the guard exists to prevent. This helper
    serializes every call; the import statement itself provides the caching.

    Raises ImportError when the package is not installed.
    """
    # No lock-free fast path on purpose: sys.modules can expose a partially
    # initialized module mid-import. The import statement below is the
    # correct memoized primitive — Python's import machinery returns the
    # cached module when fully initialized and blocks while another thread
    # is importing it. The environ snapshot on the already-imported path is
    # a harmless no-op.
    with _RLM_IMPORT_LOCK:
        with preserve_environ():
            import rlm  # noqa: PLC0415

        return rlm


__all__ = ["is_truthy_env", "is_offline_mode", "preserve_environ", "import_rlm_guarded"]
