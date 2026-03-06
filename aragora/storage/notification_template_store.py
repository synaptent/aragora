"""
Notification Template Override Store.

Persists per-user notification template overrides to JSON files so that
customizations survive server restarts.

Storage layout::

    <data_dir>/notification_templates/
        <user_id>.json   # per-user override file

Each JSON file is a dict mapping template_id -> override dict.

Usage:
    from aragora.storage.notification_template_store import (
        get_notification_template_store,
        NotificationTemplateStore,
    )

    store = get_notification_template_store()
    await store.save_override("user-1", "debate_completed", {"subject": "Done!"})
    overrides = await store.load_overrides("user-1")
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from aragora.config import resolve_db_path

logger = logging.getLogger(__name__)


class NotificationTemplateStore:
    """JSON-file-backed store for notification template overrides.

    Each user's overrides are stored in a separate JSON file under
    ``<data_dir>/notification_templates/<user_id>.json``.

    Thread-safe via a reentrant lock around all file operations.
    """

    def __init__(self, data_dir: str | None = None) -> None:
        if data_dir is None:
            # Place alongside other data files under ARAGORA_DATA_DIR
            base = resolve_db_path("notification_templates.json")
            # We want a *directory*, not a file.  resolve_db_path gives us a
            # file path; take its parent and append our directory name.
            data_dir = str(Path(base).parent / "notification_templates")

        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        logger.info("NotificationTemplateStore initialized at %s", self._dir)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _user_path(self, user_id: str) -> Path:
        """Return the path to a user's override JSON file."""
        # Sanitize user_id to prevent path traversal
        safe_id = user_id.replace("/", "_").replace("\\", "_").replace("..", "_")
        return self._dir / f"{safe_id}.json"

    def _read_user_file(self, user_id: str) -> dict[str, dict[str, Any]]:
        """Read a user's override file. Returns empty dict if missing."""
        path = self._user_path(user_id)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            logger.warning("Invalid template override file for %s, resetting", user_id)
            return {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read template overrides for %s: %s", user_id, exc)
            return {}

    def _write_user_file(self, user_id: str, data: dict[str, dict[str, Any]]) -> None:
        """Write a user's override file atomically."""
        path = self._user_path(user_id)
        tmp_path = path.with_suffix(".tmp")
        try:
            tmp_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            tmp_path.replace(path)
        except OSError as exc:
            logger.error("Failed to write template overrides for %s: %s", user_id, exc)
            raise

    # ------------------------------------------------------------------
    # Public API (async wrappers for consistency with other stores)
    # ------------------------------------------------------------------

    async def save_override(
        self,
        user_id: str,
        template_id: str,
        overrides: dict[str, Any],
    ) -> None:
        """Save a template override for a user.

        Args:
            user_id: User identifier.
            template_id: Template identifier (e.g. ``"debate_completed"``).
            overrides: Override dict (keys like ``subject``, ``body``, ``channels``).
        """
        with self._lock:
            data = self._read_user_file(user_id)
            data[template_id] = overrides
            self._write_user_file(user_id, data)
        logger.debug("Saved template override: user=%s template=%s", user_id, template_id)

    async def load_overrides(self, user_id: str) -> dict[str, dict[str, Any]]:
        """Load all template overrides for a user.

        Args:
            user_id: User identifier.

        Returns:
            Dict mapping template_id -> override dict.  Empty dict if none.
        """
        with self._lock:
            return self._read_user_file(user_id)

    async def delete_override(self, user_id: str, template_id: str) -> bool:
        """Delete a single template override.

        Args:
            user_id: User identifier.
            template_id: Template to remove.

        Returns:
            True if the override existed and was removed.
        """
        with self._lock:
            data = self._read_user_file(user_id)
            if template_id not in data:
                return False
            del data[template_id]
            if data:
                self._write_user_file(user_id, data)
            else:
                # Remove file entirely when no overrides remain
                path = self._user_path(user_id)
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            return True

    async def list_all_overrides(self) -> dict[str, dict[str, dict[str, Any]]]:
        """List all overrides across all users.

        Returns:
            Dict mapping user_id -> {template_id -> override dict}.
        """
        result: dict[str, dict[str, dict[str, Any]]] = {}
        with self._lock:
            try:
                for path in self._dir.glob("*.json"):
                    user_id = path.stem
                    data = self._read_user_file(user_id)
                    if data:
                        result[user_id] = data
            except OSError as exc:
                logger.warning("Failed to list template overrides: %s", exc)
        return result


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_store: NotificationTemplateStore | None = None
_store_lock = threading.Lock()


def get_notification_template_store(
    data_dir: str | None = None,
) -> NotificationTemplateStore:
    """Get or create the global NotificationTemplateStore.

    Args:
        data_dir: Optional data directory.  Only used on first call.

    Returns:
        The singleton store instance.
    """
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = NotificationTemplateStore(data_dir=data_dir)
    return _store


def reset_notification_template_store() -> None:
    """Reset the global store (for testing)."""
    global _store
    with _store_lock:
        _store = None


__all__ = [
    "NotificationTemplateStore",
    "get_notification_template_store",
    "reset_notification_template_store",
]
