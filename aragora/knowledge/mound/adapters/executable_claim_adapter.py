"""DIC-16 / #6026: KM adapter for ExecutableClaim verification results.

Ingests ClaimResult objects into the Knowledge Mound as BELIEF items,
preserving verification status.  Completes the executable-claim half of
the DIC-16 criterion "KM ingestion preserves verification status".
Flag-gated by ARAGORA_EPISTEMIC_CLAIMS_ENABLED (default off).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from aragora.epistemic.claim_verifier import ClaimStatus
from aragora.epistemic.executable_claim import _claims_enabled
from aragora.knowledge.mound.adapters._base import KnowledgeMoundAdapter
from aragora.knowledge.mound.types import IngestionRequest
from aragora.knowledge.unified.types import ConfidenceLevel, KnowledgeItem, KnowledgeSource

if TYPE_CHECKING:
    from aragora.epistemic.claim_verifier import ClaimResult

logger = logging.getLogger(__name__)

_CLAIM_SOURCE = KnowledgeSource.BELIEF
_ID_PREFIX = "claim_km_"
_CLAIM_NODE_TYPE = "claim"
# Mirrors MoundConfig.default_workspace_id, for mounds that expose neither the
# effective workspace nor a config object.
_FALLBACK_WORKSPACE_ID = "default"

_STATUS_CONFIDENCE: dict[str, ConfidenceLevel] = {
    ClaimStatus.PASS.value: ConfidenceLevel.HIGH,
    ClaimStatus.STALE.value: ConfidenceLevel.MEDIUM,
    ClaimStatus.FAIL.value: ConfidenceLevel.LOW,
    ClaimStatus.UNSUPPORTED.value: ConfidenceLevel.LOW,
    ClaimStatus.ERROR.value: ConfidenceLevel.LOW,
}
_STATUS_IMPORTANCE: dict[str, float] = {
    ClaimStatus.PASS.value: 0.3,
    ClaimStatus.FAIL.value: 0.9,
    ClaimStatus.STALE.value: 0.7,
    ClaimStatus.UNSUPPORTED.value: 0.4,
    ClaimStatus.ERROR.value: 0.85,
}


@dataclass
class ClaimIngestionResult:
    claims_ingested: int
    knowledge_item_ids: list[str]
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors and self.claims_ingested > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims_ingested": self.claims_ingested,
            "knowledge_item_ids": self.knowledge_item_ids,
            "skipped": self.skipped,
            "errors": self.errors,
            "success": self.success,
        }


class ExecutableClaimAdapter(KnowledgeMoundAdapter):
    """Ingests ClaimResult objects into the Knowledge Mound (DIC-16 / #6026)."""

    adapter_name = "executable_claim"

    def __init__(self, mound: Any = None, workspace_id: str | None = None, **kwargs: Any) -> None:
        """Bind the adapter to a mound.

        Args:
            mound: Knowledge Mound to write claim results into. When omitted the
                adapter runs in schema-only mode and persists nothing.
            workspace_id: Workspace the claim items are written into. When
                omitted the mound's own default is used.
        """
        super().__init__(**kwargs)
        self._mound = mound
        self._workspace_id = workspace_id

    def set_mound(self, mound: Any) -> None:
        self._mound = mound

    async def ingest_claim_results(
        self,
        results: list["ClaimResult"],
        *,
        require_enabled: bool = True,
    ) -> ClaimIngestionResult:
        if require_enabled and not _claims_enabled():
            logger.debug("ExecutableClaimAdapter: flag off; skipping %d claims", len(results))
            return ClaimIngestionResult(0, [], skipped=len(results))

        now = datetime.now(UTC)
        item_ids: list[str] = []
        errors: list[str] = []
        for result in results:
            try:
                item = self._build_item(result, now)
                stored = await self._store(item)
                item_ids.append(stored if stored else item.id)
            # A mound whose store() disagrees with the KnowledgeItem shape surfaces
            # the mismatch as AttributeError from inside the mound, which is an
            # ingestion failure for this claim rather than a reason to drop the rest.
            except (AttributeError, RuntimeError, TypeError, ValueError, OSError) as exc:
                msg = f"claim {result.claim_id}: {exc}"
                logger.warning("ExecutableClaimAdapter – %s", msg)
                errors.append(msg)
        return ClaimIngestionResult(len(item_ids), item_ids, errors=errors)

    async def ingest_claim_result(
        self, result: "ClaimResult", *, require_enabled: bool = True
    ) -> ClaimIngestionResult:
        return await self.ingest_claim_results([result], require_enabled=require_enabled)

    def _build_item(self, result: "ClaimResult", now: datetime) -> KnowledgeItem:
        sv = result.status.value if hasattr(result.status, "value") else str(result.status)
        return KnowledgeItem(
            id=_ID_PREFIX + _stable_id(result.claim_id, sv),
            content=f"[Claim:{sv}] {result.claim_id} — {result.message}",
            source=_CLAIM_SOURCE,
            source_id=result.claim_id,
            confidence=_STATUS_CONFIDENCE.get(sv, ConfidenceLevel.LOW),
            created_at=now,
            updated_at=now,
            importance=_STATUS_IMPORTANCE.get(sv, 0.5),
            metadata={
                "claim_id": result.claim_id,
                "status": sv,
                "severity": result.severity,
                "allowed_action": result.allowed_action,
                "elapsed_ms": result.elapsed_ms,
                "dic_issue": "DIC-16/#6026",
            },
        )

    def _resolve_workspace_id(self) -> str:
        # IngestionRequest requires a workspace and KnowledgeItem carries none,
        # so an unconfigured adapter follows the mound's own workspace rather
        # than inventing a tenant for claim-verification results.
        for candidate in (
            self._workspace_id,
            getattr(self._mound, "workspace_id", None),
            getattr(getattr(self._mound, "config", None), "default_workspace_id", None),
        ):
            if isinstance(candidate, str) and candidate:
                return candidate
        return _FALLBACK_WORKSPACE_ID

    def _build_request(self, item: KnowledgeItem) -> IngestionRequest:
        return IngestionRequest(
            content=item.content,
            workspace_id=self._resolve_workspace_id(),
            source_type=item.source,
            node_type=_CLAIM_NODE_TYPE,
            confidence=item.confidence.to_float(),
            # IngestionRequest has no id or importance field, so the deterministic
            # claim id and the status-derived importance ride in metadata.
            metadata={
                **item.metadata,
                "knowledge_item_id": item.id,
                "importance": item.importance,
            },
        )

    async def _store(self, item: KnowledgeItem) -> str | None:
        # Returning None means schema-only mode, which the caller records as a
        # generated id; a configured mound that cannot ingest must not take that
        # path or the batch would report items it never persisted.
        if not self._mound:
            return None
        if hasattr(self._mound, "store"):
            return _persisted_id(await self._mound.store(self._build_request(item)), self._mound)
        if hasattr(self._mound, "ingest"):
            return _persisted_id(await self._mound.ingest(self._build_request(item)), self._mound)
        raise TypeError(f"mound {type(self._mound).__name__} exposes neither store() nor ingest()")


def _persisted_id(stored: Any, mound: Any) -> str:
    # A mound answering with an IngestionResult reports rejection in-band rather
    # than raising, and a configured mound that answers with no id at all has
    # persisted nothing; neither may be counted as an ingestion.
    node_id = getattr(stored, "node_id", None)
    if node_id is not None:
        if not node_id or not getattr(stored, "success", True):
            reason = getattr(stored, "message", None) or "mound returned no node id"
            raise RuntimeError(f"mound rejected the claim item: {reason}")
        return str(node_id)
    if isinstance(stored, str) and stored:
        return stored
    raise RuntimeError(
        f"mound {type(mound).__name__} returned no usable node id: "
        f"{type(stored).__name__} {stored!r}"
    )


def _stable_id(claim_id: str, status: str) -> str:
    return hashlib.sha256(f"{claim_id}:{status}".encode()).hexdigest()[:16]


__all__ = ["ClaimIngestionResult", "ExecutableClaimAdapter", "_stable_id"]
