"""IdeaCloud adapter for Knowledge Mound.

Provides bidirectional sync between the Idea Cloud graph and
KnowledgeMound for unified knowledge management.

Forward sync: IdeaNode → KnowledgeNode
Reverse sync: KM validation results → IdeaNode confidence updates
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.knowledge.mound.adapters._base import KnowledgeMoundAdapter

logger = logging.getLogger(__name__)


class IdeaCloudAdapter(KnowledgeMoundAdapter):
    """Bridges Idea Cloud to Knowledge Mound.

    Forward flow: Sync unsynced IdeaNodes → KM as KnowledgeNodes
    Reverse flow: Apply KM validations back to IdeaNode confidence
    """

    adapter_name = "ideacloud"

    def __init__(self, idea_cloud: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._cloud = idea_cloud

    async def sync_to_km(self, **kwargs: Any) -> dict[str, Any]:
        """Forward sync: IdeaCloud → KnowledgeMound.

        Syncs all nodes where ``km_synced=False`` to KM.
        """
        if not self._cloud:
            return {"records_synced": 0, "error": "No IdeaCloud instance configured"}

        synced = 0
        skipped = 0
        failed = 0

        for node in self._cloud.graph.nodes.values():
            if node.km_synced:
                skipped += 1
                continue

            try:
                async with self._resilient_call("sync_to_km"):
                    # Create KM-compatible record and ingest
                    await self.km.ingest(
                        {
                            "source_type": "ideacloud",
                            "source_id": node.id,
                            "node_type": node.node_type,
                            "content": f"{node.title}\n\n{node.body}",
                            "confidence": node.confidence,
                            "tags": node.tags,
                            "metadata": {
                                "source_url": node.source_url,
                                "source_author": node.source_author,
                                "cluster_id": node.cluster_id,
                                "pipeline_status": node.pipeline_status,
                                "relevance_score": node.relevance_score,
                            },
                        }
                    )

                    self._emit_event(
                        "ideacloud_sync",
                        {
                            "node_id": node.id,
                            "title": node.title,
                            "direction": "forward",
                        },
                    )

                    # Mark as synced
                    node.km_synced = True
                    synced += 1

            except Exception as exc:
                logger.warning("Failed to sync node %s: %s", node.id, exc)
                failed += 1

        # Persist sync status back to vault
        if synced > 0:
            self._cloud.save()

        result = {
            "records_synced": synced,
            "records_skipped": skipped,
            "records_failed": failed,
        }

        self._record_metric(
            "sync_to_km",
            success=failed == 0,
            latency=0.0,
            extra_labels={"synced": str(synced)},
        )

        return result

    async def sync_from_km(
        self,
        km_validations: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Reverse sync: KnowledgeMound → IdeaCloud.

        Applies KM validation results back to IdeaNode confidence scores
        and pipeline status.

        Args:
            km_validations: Optional list of validation dicts with fields:
                - ``source_id``: IdeaNode ID
                - ``confidence``: Updated confidence (0-1)
                - ``validation_status``: "confirmed" | "disputed" | "uncertain"
                - ``notes``: Optional validation notes
                If not provided, queries KM for validation events.

        Returns:
            Dict with counts of analyzed and updated records.
        """
        if not self._cloud:
            return {"records_updated": 0, "error": "No IdeaCloud instance configured"}

        updated = 0
        analyzed = 0

        validations = km_validations or []

        # Index validations by source_id for quick lookup
        validation_map: dict[str, dict[str, Any]] = {}
        for v in validations:
            sid = v.get("source_id", "")
            if sid:
                validation_map[sid] = v

        for node in self._cloud.graph.nodes.values():
            if not node.km_synced:
                continue

            analyzed += 1

            validation = validation_map.get(node.id)
            if not validation:
                continue

            try:
                async with self._resilient_call("sync_from_km"):
                    # Update confidence from KM validation
                    new_confidence = validation.get("confidence")
                    if new_confidence is not None:
                        node.confidence = float(new_confidence)

                    # Update pipeline status based on validation
                    status = validation.get("validation_status", "")
                    if status == "confirmed" and node.pipeline_status == "inbox":
                        node.pipeline_status = "candidate"
                    elif status == "disputed":
                        node.confidence = max(0.0, node.confidence - 0.2)

                    node.updated_at = __import__(
                        "aragora.ideacloud.graph.node",
                        fromlist=["_now_iso"],
                    )._now_iso()

                    self._emit_event(
                        "ideacloud_sync",
                        {
                            "node_id": node.id,
                            "title": node.title,
                            "direction": "reverse",
                            "validation_status": status,
                        },
                    )

                    updated += 1

            except Exception as exc:
                logger.warning(
                    "Failed to apply KM validation to node %s: %s",
                    node.id,
                    exc,
                )

        if updated > 0:
            self._cloud.save()

        result = {
            "records_analyzed": analyzed,
            "records_updated": updated,
        }

        self._record_metric(
            "sync_from_km",
            success=True,
            latency=0.0,
            extra_labels={"updated": str(updated)},
        )

        return result

    def health_check(self) -> dict[str, Any]:
        """Return adapter health status."""
        base = super().health_check()
        if self._cloud:
            stats = self._cloud.stats
            base["ideacloud_nodes"] = stats.get("total_nodes", 0)
            base["ideacloud_clusters"] = stats.get("total_clusters", 0)
        return base
