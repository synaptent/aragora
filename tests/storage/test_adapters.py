"""Focused tests for storage adapters."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, UTC
from unittest.mock import MagicMock

from aragora.export.artifact import DebateArtifact
from aragora.export.storage_adapter import DebateStorageAdapter
from aragora.storage.debate_storage import DebateMetadata


def _metadata(*, slug: str = "debate-slug", debate_id: str = "debate-123") -> DebateMetadata:
    return DebateMetadata(
        slug=slug,
        debate_id=debate_id,
        task="Debate task",
        agents=["agent-a", "agent-b"],
        consensus_reached=True,
        confidence=0.9,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        view_count=3,
        is_public=True,
    )


class TestDebateStorageAdapter:
    def test_save_injects_missing_ids_from_key(self) -> None:
        storage = MagicMock()
        storage.save.return_value = "saved-slug"
        adapter = DebateStorageAdapter(storage)

        result = adapter.save("debate-123", {"task": "Ship the adapter tests"})

        assert result == "saved-slug"
        artifact = storage.save.call_args.args[0]
        assert isinstance(artifact, DebateArtifact)
        assert artifact.artifact_id == "debate-123"
        assert artifact.debate_id == "debate-123"
        assert artifact.task == "Ship the adapter tests"

    def test_save_preserves_existing_ids(self) -> None:
        storage = MagicMock()
        adapter = DebateStorageAdapter(storage)

        adapter.save(
            "fallback-key",
            {
                "artifact_id": "artifact-1",
                "debate_id": "debate-1",
                "task": "Keep explicit IDs",
            },
        )

        artifact = storage.save.call_args.args[0]
        assert artifact.artifact_id == "artifact-1"
        assert artifact.debate_id == "debate-1"

    def test_get_delegates_to_storage(self) -> None:
        storage = MagicMock()
        storage.get.return_value = {"debate_id": "debate-123"}
        adapter = DebateStorageAdapter(storage)

        result = adapter.get("debate-123")

        assert result == {"debate_id": "debate-123"}
        storage.get.assert_called_once_with("debate-123")

    def test_delete_delegates_to_delete_debate(self) -> None:
        storage = MagicMock()
        storage.delete_debate.return_value = True
        adapter = DebateStorageAdapter(storage)

        result = adapter.delete("debate-123")

        assert result is True
        storage.delete_debate.assert_called_once_with("debate-123")

    def test_query_returns_debate_lookup_when_filter_uses_id_alias(self) -> None:
        storage = MagicMock()
        storage.get.return_value = {"debate_id": "debate-123"}
        adapter = DebateStorageAdapter(storage)

        result = adapter.query({"id": "debate-123"})

        assert result == [{"debate_id": "debate-123"}]
        storage.get.assert_called_once_with("debate-123")
        storage.get_by_slug.assert_not_called()
        storage.list_recent.assert_not_called()

    def test_query_returns_slug_lookup(self) -> None:
        storage = MagicMock()
        storage.get_by_slug.return_value = {"slug": "ship-it"}
        adapter = DebateStorageAdapter(storage)

        result = adapter.query({"slug": "ship-it"})

        assert result == [{"slug": "ship-it"}]
        storage.get_by_slug.assert_called_once_with("ship-it")
        storage.list_recent.assert_not_called()

    def test_query_returns_empty_list_when_lookup_misses(self) -> None:
        storage = MagicMock()
        storage.get.return_value = None
        adapter = DebateStorageAdapter(storage)

        assert adapter.query({"debate_id": "missing"}) == []

    def test_query_lists_recent_and_normalizes_results(self) -> None:
        metadata = _metadata()
        storage = MagicMock()
        storage.list_recent.return_value = [
            metadata,
            {"debate_id": "raw"},
            "fallback-value",
        ]
        adapter = DebateStorageAdapter(storage)

        result = adapter.query({"limit": "5", "org_id": "org-7"})

        assert result == [
            asdict(metadata),
            {"debate_id": "raw"},
            {"value": "fallback-value"},
        ]
        storage.list_recent.assert_called_once_with(limit=5, org_id="org-7")
