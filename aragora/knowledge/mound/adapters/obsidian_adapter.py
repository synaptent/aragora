"""
ObsidianAdapter - Bridges Obsidian vaults to the Knowledge Mound.

Ingests notes from an Obsidian vault into the Knowledge Mound with
metadata, tags, and backlinks preserved.

Usage:
    from aragora.connectors.knowledge.obsidian import ObsidianConfig, ObsidianConnector
    from aragora.knowledge.mound.adapters import ObsidianAdapter

    config = ObsidianConfig(vault_path="~/Vault")
    connector = ObsidianConnector(config)
    adapter = ObsidianAdapter(connector=connector, workspace_id="team-1")

    result = await adapter.sync_to_km()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.connectors.knowledge.obsidian import ObsidianConfig, ObsidianConnector
    from aragora.connectors.knowledge.obsidian_watcher import VaultChangeEvent

from aragora.knowledge.mound.adapters._base import (
    KnowledgeMoundAdapter,
    ADAPTER_CIRCUIT_CONFIGS,
    AdapterCircuitBreakerConfig,
)
from aragora.knowledge.mound.adapters._types import SyncResult, ValidationSyncResult
from aragora.knowledge.mound.types import IngestionRequest, KnowledgeSource
from aragora.runtime.connector_factory import create_connector

logger = logging.getLogger(__name__)

# Obsidian is local IO, so use tighter circuit breaker thresholds
ADAPTER_CIRCUIT_CONFIGS["obsidian"] = AdapterCircuitBreakerConfig(
    failure_threshold=3,
    success_threshold=2,
    timeout_seconds=20.0,
    half_open_max_calls=2,
)


@dataclass
class ConflictRecord:
    """Record of a sync conflict between Obsidian vault and Knowledge Mound."""

    note_path: str
    vault_modified: datetime
    km_modified: datetime
    winner: str  # "vault" or "km"
    resolved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __str__(self) -> str:
        return (
            f"Conflict on '{self.note_path}': vault={self.vault_modified.isoformat()}, "
            f"km={self.km_modified.isoformat()}, winner={self.winner}"
        )


@dataclass
class ObsidianSyncConfig:
    """Configuration for Obsidian → Knowledge Mound sync."""

    workspace_id: str = "default"
    watch_tags: list[str] | None = None
    include_untagged: bool = False
    max_notes: int | None = None


class ObsidianAdapter(KnowledgeMoundAdapter):
    """Adapter that ingests Obsidian notes into the Knowledge Mound."""

    adapter_name = "obsidian"
    source_type = "document"

    def __init__(
        self,
        connector: ObsidianConnector | None = None,
        config: ObsidianConfig | None = None,
        vault_path: str | Path | None = None,
        sync_config: ObsidianSyncConfig | None = None,
        workspace_id: str = "default",
        event_callback: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the adapter.

        Args:
            connector: Pre-configured ObsidianConnector
            config: ObsidianConfig (used if connector not provided)
            vault_path: Vault path (used if config not provided)
            sync_config: Sync behavior configuration
            workspace_id: Knowledge Mound workspace ID
            event_callback: Optional event callback
        """
        super().__init__(**kwargs)

        if connector is None:
            if config is not None:
                connector = create_connector("obsidian", config=config)
            elif vault_path is not None:
                connector = create_connector("obsidian", vault_path=str(vault_path))
            else:
                connector = create_connector("obsidian")

        self._connector = connector
        self._config = config or getattr(connector, "_config", None)
        self._sync_config = sync_config or ObsidianSyncConfig(workspace_id=workspace_id)
        self._event_callback = event_callback
        self._conflict_log: list[ConflictRecord] = []

        if self._sync_config.watch_tags is None and self._config is not None:
            self._sync_config.watch_tags = list(self._config.watch_tags)

    @property
    def connector(self) -> ObsidianConnector | None:
        """Return the underlying Obsidian connector."""
        return self._connector

    @property
    def conflict_log(self) -> list[ConflictRecord]:
        """Return the list of recorded sync conflicts."""
        return self._conflict_log

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit event via callback if configured."""
        if self._event_callback:
            try:
                self._event_callback(event_type, data)
            except (RuntimeError, ValueError, TypeError, AttributeError) as e:  # noqa: BLE001 - adapter isolation
                logger.debug("ObsidianAdapter event callback failed: %s", e)

    async def _on_vault_change(self, event: VaultChangeEvent) -> None:
        """Respond to a VaultWatcher change event by triggering incremental sync.

        Args:
            event: The vault change event from the watcher.
        """
        if event.change_type == "deleted":
            logger.info("Vault file deleted: %s (KM staleness handles cleanup)", event.path)
            return

        if event.change_type in ("created", "modified"):
            try:
                await self.sync_to_km()
            except (RuntimeError, ValueError, OSError, AttributeError) as e:  # noqa: BLE001 - adapter isolation
                logger.warning("Incremental sync on vault change failed: %s", e)

    def _get_mound(self) -> Any | None:
        """Get Knowledge Mound instance."""
        try:
            from aragora.knowledge.mound import get_knowledge_mound

            return get_knowledge_mound(workspace_id=self._sync_config.workspace_id)
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.debug("Could not get knowledge mound: %s", e)
            return None

    def resolve_conflict(
        self,
        note_path: str,
        vault_modified: datetime,
        km_modified: datetime,
    ) -> str:
        """Resolve a sync conflict using last-write-wins strategy.

        Compares modification timestamps from both sides and returns the
        winner.  The conflict is logged for manual review.

        Args:
            note_path: Path of the conflicting note.
            vault_modified: Last modification time on the vault side.
            km_modified: Last modification time on the KM side.

        Returns:
            ``"vault"`` if the vault version is newer or equal,
            ``"km"`` if the KM version is newer.
        """
        winner = "vault" if vault_modified >= km_modified else "km"
        record = ConflictRecord(
            note_path=note_path,
            vault_modified=vault_modified,
            km_modified=km_modified,
            winner=winner,
        )
        self._conflict_log.append(record)
        logger.info("Obsidian sync conflict resolved: %s", record)
        return winner

    async def _check_conflict(
        self,
        mound: Any,
        document_id: str,
        vault_modified: datetime,
    ) -> str | None:
        """Check for an existing KM entry and resolve conflict if needed.

        Returns ``None`` when there is no conflict (note does not exist in KM
        yet), ``"vault"`` when the vault version wins, or ``"km"`` when the KM
        version wins.
        """
        try:
            results = await mound.query(
                query=f"document_id:{document_id}",
                limit=1,
            )
            if not results:
                return None
            entry = results[0] if isinstance(results, list) else None
            if entry is None:
                return None

            meta = entry.get("metadata", {}) if isinstance(entry, dict) else {}
            km_ts = meta.get("km_validated_at") or meta.get("ingested_at")
            if km_ts is None:
                return None

            if isinstance(km_ts, str):
                # Handle ISO format strings
                km_modified = datetime.fromisoformat(km_ts.replace("Z", "+00:00"))
            elif isinstance(km_ts, (int, float)):
                km_modified = datetime.fromtimestamp(km_ts, tz=timezone.utc)
            else:
                return None

            # Ensure vault_modified is tz-aware for comparison
            vault_aware = vault_modified
            if vault_aware.tzinfo is None:
                vault_aware = vault_aware.replace(tzinfo=timezone.utc)
            if km_modified.tzinfo is None:
                km_modified = km_modified.replace(tzinfo=timezone.utc)

            return self.resolve_conflict(document_id, vault_aware, km_modified)
        except (RuntimeError, ValueError, AttributeError, KeyError, TypeError) as e:  # noqa: BLE001
            logger.debug("Conflict check failed for %s: %s", document_id, e)
            return None

    async def sync_to_km(
        self,
        knowledge_mound: Any | None = None,
        since: datetime | None = None,
        limit: int | None = None,
        tags: list[str] | None = None,
        include_untagged: bool | None = None,
    ) -> SyncResult:
        """Sync Obsidian notes into the Knowledge Mound.

        Args:
            knowledge_mound: Optional Knowledge Mound instance
            since: Only ingest notes modified after this time
            limit: Maximum notes to ingest
            tags: Optional tag filter (overrides config)
            include_untagged: Whether to ingest notes without matching tags
        """
        start_time = time.time()
        synced = 0
        skipped = 0
        failed = 0
        errors: list[str] = []

        connector = self._connector
        if connector is None or not connector.is_configured:
            return SyncResult(
                records_synced=0,
                records_skipped=0,
                records_failed=1,
                errors=["Obsidian connector not configured or vault unavailable"],
                duration_ms=(time.time() - start_time) * 1000,
            )

        mound = knowledge_mound or self._get_mound()
        if mound is None:
            return SyncResult(
                records_synced=0,
                records_skipped=0,
                records_failed=1,
                errors=["Knowledge Mound not available"],
                duration_ms=(time.time() - start_time) * 1000,
            )

        watch_tags = tags or self._sync_config.watch_tags or []
        include_untagged = (
            include_untagged if include_untagged is not None else self._sync_config.include_untagged
        )
        max_notes = limit if limit is not None else self._sync_config.max_notes

        try:
            async with self._resilient_call("sync_to_km"):
                sync_state = connector.new_sync_state(since)
                async for item in connector.sync_items(sync_state, batch_size=max_notes or 1000):
                    item_tags: list[str] = []
                    if isinstance(item.metadata, dict):
                        item_tags = item.metadata.get("tags", []) or []

                    if watch_tags and not any(t in item_tags for t in watch_tags):
                        if not include_untagged:
                            skipped += 1
                            continue

                    try:
                        # Check for conflict with existing KM entry
                        vault_mod_time = None
                        if isinstance(item.metadata, dict):
                            raw_ts = item.metadata.get("modified_at") or item.metadata.get("mtime")
                            if isinstance(raw_ts, (int, float)):
                                vault_mod_time = datetime.fromtimestamp(raw_ts, tz=timezone.utc)
                            elif isinstance(raw_ts, str):
                                vault_mod_time = datetime.fromisoformat(
                                    raw_ts.replace("Z", "+00:00")
                                )
                            elif isinstance(raw_ts, datetime):
                                vault_mod_time = raw_ts

                        if vault_mod_time is not None:
                            winner = await self._check_conflict(
                                mound, item.source_id, vault_mod_time
                            )
                            if winner == "km":
                                # KM version is newer — skip vault ingestion
                                skipped += 1
                                continue

                        req = IngestionRequest(
                            content=item.content,
                            workspace_id=self._sync_config.workspace_id,
                            source_type=KnowledgeSource.DOCUMENT,
                            document_id=item.source_id,
                            node_type="document",
                            confidence=item.confidence,
                            topics=[t.lstrip("#") for t in item_tags if isinstance(t, str)],
                            metadata={
                                "source": "obsidian",
                                "title": item.title,
                                "url": item.url,
                                "tags": item_tags,
                                "note_type": item.metadata.get("note_type")
                                if item.metadata
                                else None,
                                "path": item.source_id,
                            },
                        )
                        await mound.ingest(req)
                        synced += 1
                    except (RuntimeError, ValueError, AttributeError, KeyError) as e:  # noqa: BLE001 - adapter isolation
                        failed += 1
                        logger.warning("Obsidian note ingestion failed: %s", e)
                        errors.append("Note ingestion failed")

                    if max_notes is not None and (synced + skipped + failed) >= max_notes:
                        break

        except (RuntimeError, ValueError, TypeError, AttributeError) as e:  # noqa: BLE001 - adapter isolation
            logger.warning("Obsidian sync failed: %s", e)
            errors.append("Obsidian sync failed")

        duration_ms = (time.time() - start_time) * 1000
        self._emit_event(
            "obsidian_sync_complete",
            {
                "synced": synced,
                "skipped": skipped,
                "failed": failed,
                "duration_ms": duration_ms,
            },
        )

        return SyncResult(
            records_synced=synced,
            records_skipped=skipped,
            records_failed=failed,
            errors=errors,
            duration_ms=duration_ms,
        )

    async def sync_from_km(
        self,
        knowledge_mound: Any | None = None,
        limit: int | None = None,
        min_confidence: float = 0.0,
    ) -> ValidationSyncResult:
        """Reverse sync: write KM validation results back to Obsidian frontmatter.

        Queries KM for entries sourced from Obsidian and writes back
        validation metadata (confidence, cross-debate utility, validation
        status) into note frontmatter using ``km_`` prefixed fields.

        Args:
            knowledge_mound: Optional Knowledge Mound instance
            limit: Maximum entries to process
            min_confidence: Minimum confidence to include
        """
        start_time = time.time()
        analyzed = 0
        updated = 0
        failed = 0
        errors: list[str] = []

        connector = self._connector
        if connector is None or not connector.is_configured:
            return ValidationSyncResult(
                records_analyzed=0,
                records_updated=0,
                records_failed=1,
                errors=["Obsidian connector not configured"],
                duration_ms=(time.time() - start_time) * 1000,
            )

        mound = knowledge_mound or self._get_mound()
        if mound is None:
            return ValidationSyncResult(
                records_analyzed=0,
                records_updated=0,
                records_failed=1,
                errors=["Knowledge Mound not available"],
                duration_ms=(time.time() - start_time) * 1000,
            )

        try:
            async with self._resilient_call("sync_from_km"):
                entries = await self._query_obsidian_entries(mound, limit)

                for entry in entries:
                    analyzed += 1
                    confidence = entry.get("confidence", 0.0)
                    if confidence < min_confidence:
                        continue

                    note_path = self._extract_note_path(entry)
                    if not note_path:
                        continue

                    try:
                        frontmatter_updates = {
                            "km_confidence": round(confidence, 3),
                            "km_validated_at": datetime.utcnow().isoformat(),
                            "km_validation_result": entry.get("validation_status", "unvalidated"),
                        }
                        utility = entry.get("cross_debate_utility")
                        if utility is not None:
                            frontmatter_updates["km_cross_debate_utility"] = round(
                                float(utility), 3
                            )

                        connector.update_note_frontmatter(note_path, frontmatter_updates)
                        updated += 1
                    except (RuntimeError, ValueError, OSError, AttributeError) as e:  # noqa: BLE001 - adapter isolation
                        failed += 1
                        logger.warning("Obsidian frontmatter update failed: %s", e)
                        errors.append("Frontmatter update failed")

        except (RuntimeError, ValueError, TypeError, AttributeError) as e:  # noqa: BLE001 - adapter isolation
            logger.warning("Obsidian reverse sync failed: %s", e)
            errors.append("Reverse sync failed")

        duration_ms = (time.time() - start_time) * 1000
        self._emit_event(
            "obsidian_reverse_sync_complete",
            {
                "analyzed": analyzed,
                "updated": updated,
                "failed": failed,
                "duration_ms": duration_ms,
            },
        )

        return ValidationSyncResult(
            records_analyzed=analyzed,
            records_updated=updated,
            records_failed=failed,
            errors=errors,
            duration_ms=duration_ms,
        )

    async def _query_obsidian_entries(
        self, mound: Any, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Query KM for entries sourced from Obsidian."""
        try:
            results = await mound.query(
                query="source:obsidian",
                limit=limit or 100,
            )
            if isinstance(results, list):
                return results
            return []
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.debug("KM query for obsidian entries failed: %s", e)
            return []

    @staticmethod
    def _extract_note_path(entry: dict[str, Any]) -> str | None:
        """Extract the Obsidian note path from a KM entry."""
        metadata = entry.get("metadata", {})
        if isinstance(metadata, dict):
            path = metadata.get("path") or metadata.get("source_id")
            if isinstance(path, str):
                return path
        doc_id = entry.get("document_id")
        if isinstance(doc_id, str) and doc_id.endswith(".md"):
            return doc_id
        return None


__all__ = ["ConflictRecord", "ObsidianAdapter", "ObsidianSyncConfig"]
