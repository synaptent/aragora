"""DIC-16 / #6026: Knowledge Mound adapter for CruxReceipt objects.

Ingests :class:`~aragora.epistemic.crux_receipt.CruxReceipt` outputs
into the Knowledge Mound, preserving each crux as a KnowledgeItem
(source=BELIEF) with load-bearing score, receipt linkage, affected
claims, and checksum for later provenance verification.

Flag-gated: ``ARAGORA_CRUX_RECEIPT_ENABLED`` gates downstream actions.
Construction is always safe; :meth:`CruxReceiptAdapter.ingest_crux_receipt`
checks the flag when ``require_enabled=True`` (default).

AGT-01 / #6062: :meth:`CruxReceiptAdapter.ingest_cruxset` also ingests the
signed :class:`~aragora.reasoning.cruxset.CruxSet` the debate path emits,
gated by ``ARAGORA_CRUXSET_EMISSION_ENABLED`` (not the receipt flag). No
live debate or dispatch path calls it; callers opt in explicitly.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from aragora.epistemic.crux_receipt import crux_receipt_enabled
from aragora.knowledge.mound.adapters._base import KnowledgeMoundAdapter
from aragora.knowledge.unified.types import (
    ConfidenceLevel,
    KnowledgeItem,
    KnowledgeSource,
)

if TYPE_CHECKING:
    from aragora.epistemic.crux_receipt import CruxEntry, CruxReceipt
    from aragora.reasoning.cruxset import Crux, CruxSet

logger = logging.getLogger(__name__)

_CRUX_SOURCE = KnowledgeSource.BELIEF
_ID_PREFIX = "crux_km_"
_CRUXSET_ID_PREFIX = "cruxset_km_"


@dataclass
class CruxIngestionResult:
    """Result of ingesting a CruxReceipt into the Knowledge Mound."""

    receipt_id: str
    cruxes_ingested: int
    knowledge_item_ids: list[str]
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors and self.cruxes_ingested > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "cruxes_ingested": self.cruxes_ingested,
            "knowledge_item_ids": self.knowledge_item_ids,
            "skipped": self.skipped,
            "errors": self.errors,
            "success": self.success,
        }


@dataclass
class CruxSetIngestionResult:
    """Result of ingesting an AGT-01 CruxSet into the Knowledge Mound."""

    cruxset_id: str
    cruxes_ingested: int
    knowledge_item_ids: list[str]
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors and self.cruxes_ingested > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cruxset_id": self.cruxset_id,
            "cruxes_ingested": self.cruxes_ingested,
            "knowledge_item_ids": self.knowledge_item_ids,
            "skipped": self.skipped,
            "errors": self.errors,
            "success": self.success,
        }


class CruxReceiptAdapter(KnowledgeMoundAdapter):
    """Ingests CruxReceipts (DIC-16 / #6026) and AGT-01 CruxSets (#6062) into the KM."""

    adapter_name = "crux_receipt"

    def __init__(self, mound: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._mound = mound

    def set_mound(self, mound: Any) -> None:
        self._mound = mound

    async def ingest_crux_receipt(
        self,
        receipt: "CruxReceipt",
        *,
        require_enabled: bool = True,
    ) -> CruxIngestionResult:
        """Ingest a CruxReceipt; checks ARAGORA_CRUX_RECEIPT_ENABLED when require_enabled=True."""
        if require_enabled and not crux_receipt_enabled():
            logger.debug("CruxReceiptAdapter: flag off; skipping")
            return CruxIngestionResult(
                receipt_id=receipt.receipt_id,
                cruxes_ingested=0,
                knowledge_item_ids=[],
                skipped=len(receipt.cruxes),
            )

        now = datetime.now(UTC)
        item_ids: list[str] = []
        errors: list[str] = []

        for crux in receipt.cruxes:
            try:
                item = self._crux_to_knowledge_item(crux, receipt, now)
                stored = await self._store_item(item)
                item_ids.append(stored if stored else item.id)
            except Exception as exc:  # noqa: BLE001
                msg = f"crux {crux.crux_id}: {exc}"
                logger.warning("CruxReceiptAdapter – %s", msg)
                errors.append(msg)

        return CruxIngestionResult(
            receipt_id=receipt.receipt_id,
            cruxes_ingested=len(item_ids),
            knowledge_item_ids=item_ids,
            errors=errors,
        )

    def _crux_to_knowledge_item(
        self,
        crux: "CruxEntry",
        receipt: "CruxReceipt",
        now: datetime,
    ) -> KnowledgeItem:
        item_id = _ID_PREFIX + _stable_id(crux.crux_id, receipt.receipt_id)
        content = (
            f"[Crux] {crux.statement} "
            f"(load_bearing={crux.load_bearing_score:.2f}, receipt={receipt.receipt_id})"
        )
        return KnowledgeItem(
            id=item_id,
            content=content,
            source=_CRUX_SOURCE,
            source_id=crux.crux_id,
            confidence=ConfidenceLevel.from_float(crux.load_bearing_score),
            created_at=now,
            updated_at=now,
            importance=crux.load_bearing_score,
            metadata={
                "crux_id": crux.crux_id,
                "receipt_id": receipt.receipt_id,
                "debate_id": receipt.debate_id,
                "checksum": receipt.checksum,
                "load_bearing_score": crux.load_bearing_score,
                "affected_claims": list(crux.affected_claims),
                "dic_issue": "DIC-16/#6026",
            },
            cross_references=list(crux.affected_claims),
        )

    async def ingest_cruxset(
        self,
        cruxset: "CruxSet",
        *,
        require_enabled: bool = True,
    ) -> CruxSetIngestionResult:
        """Ingest an AGT-01 CruxSet; checks ARAGORA_CRUXSET_EMISSION_ENABLED when require_enabled=True.

        Fail-closed: a CruxSet whose checksum does not verify is refused, and a
        missing mound records an error per crux rather than counting it ingested.
        """
        # Lazy: keeps aragora.reasoning out of the adapter package's import graph.
        from aragora.reasoning.cruxset_emission import cruxset_emission_enabled

        if require_enabled and not cruxset_emission_enabled():
            logger.debug("CruxReceiptAdapter: cruxset emission flag off; skipping")
            return CruxSetIngestionResult(
                cruxset_id=cruxset.cruxset_id,
                cruxes_ingested=0,
                knowledge_item_ids=[],
                skipped=len(cruxset.cruxes),
            )

        if not cruxset.verify_checksum():
            msg = f"cruxset {cruxset.cruxset_id}: checksum mismatch; refusing to ingest"
            logger.warning("CruxReceiptAdapter – %s", msg)
            return CruxSetIngestionResult(
                cruxset_id=cruxset.cruxset_id,
                cruxes_ingested=0,
                knowledge_item_ids=[],
                skipped=len(cruxset.cruxes),
                errors=[msg],
            )

        now = datetime.now(UTC)
        item_ids: list[str] = []
        errors: list[str] = []

        for crux in cruxset.cruxes:
            try:
                item = self._cruxset_crux_to_knowledge_item(crux, cruxset, now)
                stored = await self._store_item(item)
                if stored is None:
                    raise RuntimeError("Knowledge Mound not configured or has no store()/ingest()")
                item_ids.append(stored)
            # A mound store() that rejects the item shape raises AttributeError;
            # that fails this crux only, not the rest of the set.
            except (AttributeError, RuntimeError, TypeError, ValueError, OSError) as exc:
                msg = f"crux {crux.crux_id}: {exc}"
                logger.warning("CruxReceiptAdapter – %s", msg)
                errors.append(msg)

        return CruxSetIngestionResult(
            cruxset_id=cruxset.cruxset_id,
            cruxes_ingested=len(item_ids),
            knowledge_item_ids=item_ids,
            errors=errors,
        )

    def _cruxset_crux_to_knowledge_item(
        self,
        crux: "Crux",
        cruxset: "CruxSet",
        now: datetime,
    ) -> KnowledgeItem:
        # cruxset_id is content-addressed, so re-ingesting the same analysis
        # yields the same item ids and deduplicates in the mound.
        item_id = _CRUXSET_ID_PREFIX + _stable_id(crux.crux_id, cruxset.cruxset_id)
        sides = ", ".join(p.side for p in crux.positions) or "(no positions)"
        content = (
            f"[Crux] {crux.statement} "
            f"(load_bearing={crux.load_bearing_score:.2f}, sides=[{sides}], "
            f"cruxset={cruxset.cruxset_id})"
        )
        cross_references = [cruxset.cruxset_id]
        if cruxset.receipt_id:
            cross_references.append(cruxset.receipt_id)
        return KnowledgeItem(
            id=item_id,
            content=content,
            source=_CRUX_SOURCE,
            source_id=crux.crux_id,
            confidence=ConfidenceLevel.from_float(crux.load_bearing_score),
            created_at=now,
            updated_at=now,
            importance=crux.load_bearing_score,
            metadata={
                "crux_id": crux.crux_id,
                "cruxset_id": cruxset.cruxset_id,
                "cruxset_schema_version": cruxset.schema_version,
                "receipt_id": cruxset.receipt_id,
                "debate_id": str(cruxset.provenance.get("debate_id") or ""),
                "question": cruxset.question,
                "decision": cruxset.decision,
                "checksum": cruxset.checksum,
                "load_bearing_score": crux.load_bearing_score,
                "positions": [p.to_json() for p in crux.positions],
                "evidence_gaps": list(crux.evidence_gaps),
                "counterfactual": crux.counterfactual,
                "candidate_verifier": crux.candidate_verifier,
                "agt_issue": "AGT-01/#6062",
            },
            cross_references=cross_references,
        )

    async def _store_item(self, item: KnowledgeItem) -> str | None:
        """Stores item in mound; propagates exceptions so the caller can record them."""
        if not self._mound:
            return None
        if hasattr(self._mound, "store"):
            result = await self._mound.store(item)
            return str(result) if result else item.id
        if hasattr(self._mound, "ingest"):
            await self._mound.ingest(item)
            return item.id
        return None


def _stable_id(crux_id: str, receipt_id: str) -> str:
    """16-char hex stable ID over the crux + receipt pair."""
    return hashlib.sha256(f"{crux_id}:{receipt_id}".encode()).hexdigest()[:16]


__all__ = ["CruxIngestionResult", "CruxReceiptAdapter", "CruxSetIngestionResult"]
