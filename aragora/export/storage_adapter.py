"""
Export adapter bridging debate artifacts to the unified storage interface.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from aragora.storage.interface import StorageInterface
from aragora.storage.debate_storage import DebateStorage, DebateMetadata
from aragora.export.artifact import DebateArtifact


class DebateStorageAdapter(StorageInterface):
    """Adapter to expose DebateStorage via the unified StorageInterface."""

    def __init__(self, storage: DebateStorage):
        self._storage = storage

    def save(self, key: str, data: dict[str, Any]) -> str:  # type: ignore[override]
        """Save debate data and return a slug.

        Expects data to be a DebateArtifact-compatible dict. The adapter will
        inject artifact_id/debate_id if missing.
        """
        payload = dict(data)
        if key:
            payload.setdefault("artifact_id", key)
            payload.setdefault("debate_id", key)

        artifact = DebateArtifact.from_dict(payload)
        return self._storage.save(artifact)

    def get(self, key: str) -> dict[str, Any] | None:
        return self._storage.get(key)

    def delete(self, key: str) -> bool:
        return self._storage.delete_debate(key)

    def query(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        debate_id = filters.get("debate_id") or filters.get("id")
        if debate_id:
            debate = self._storage.get(debate_id)
            return [debate] if debate else []

        slug = filters.get("slug")
        if slug:
            debate = self._storage.get_by_slug(slug)
            return [debate] if debate else []

        limit = int(filters.get("limit", 20))
        org_id = filters.get("org_id")
        results: list[dict[str, Any]] = []
        for item in self._storage.list_recent(limit=limit, org_id=org_id):
            if isinstance(item, DebateMetadata):
                results.append(asdict(item))
            else:
                results.append(item if isinstance(item, dict) else {"value": item})
        return results


__all__ = ["DebateStorageAdapter"]
