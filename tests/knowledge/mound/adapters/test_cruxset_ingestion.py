"""Tests for AGT-01 CruxSet ingestion via CruxReceiptAdapter.ingest_cruxset (#6062).

Gated by ARAGORA_CRUXSET_EMISSION_ENABLED, independently of the DIC-16
CruxReceipt flag; nothing on the live debate path calls it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.knowledge.mound.adapters.crux_receipt_adapter import (
    CruxReceiptAdapter,
    CruxSetIngestionResult,
)
from aragora.knowledge.unified.types import ConfidenceLevel, KnowledgeItem, KnowledgeSource
from aragora.reasoning.cruxset import Crux, CruxPosition, CruxSet

EMISSION_FLAG = "ARAGORA_CRUXSET_EMISSION_ENABLED"
RECEIPT_FLAG = "ARAGORA_CRUX_RECEIPT_ENABLED"


def _crux(crux_id: str = "crux-1", score: float = 0.8) -> Crux:
    return Crux(
        crux_id=crux_id,
        statement="Caching is on the hot path",
        positions=(CruxPosition(side="yes", agents=("alice",)), CruxPosition(side="no")),
        load_bearing_score=score,
        evidence_gaps=("no p99 trace",),
        candidate_verifier="bench/p99",
    )


def _cruxset(cruxes: tuple[Crux, ...] = (_crux(),)) -> CruxSet:
    return CruxSet.build(
        question="Should we add a cache?",
        cruxes=cruxes,
        decision="yes",
        receipt_id="rcpt-9",
        provenance={"debate_id": "debate-42"},
    )


def _mound() -> MagicMock:
    mound = MagicMock()
    mound.store = AsyncMock(return_value="stored-1")
    return mound


def _ingest(adapter: CruxReceiptAdapter, cruxset: CruxSet, **kw: bool) -> CruxSetIngestionResult:
    return asyncio.run(adapter.ingest_cruxset(cruxset, **kw))


@pytest.fixture(autouse=True)
def _flags_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(EMISSION_FLAG, raising=False)
    monkeypatch.delenv(RECEIPT_FLAG, raising=False)


def test_result_success_and_to_dict() -> None:
    assert CruxSetIngestionResult("cs", 1, ["a"]).success is True
    assert CruxSetIngestionResult("cs", 0, []).success is False
    assert CruxSetIngestionResult("cs", 1, ["a"], errors=["e"]).success is False
    d = CruxSetIngestionResult("cs", 1, ["a"], skipped=2).to_dict()
    assert (d["cruxset_id"], d["skipped"], d["success"]) == ("cs", 2, True)


class TestKnowledgeItemShape:
    def setup_method(self) -> None:
        self.cruxset = _cruxset()

    def _item(self) -> KnowledgeItem:
        return CruxReceiptAdapter()._cruxset_crux_to_knowledge_item(
            self.cruxset.cruxes[0], self.cruxset, datetime.now(UTC)
        )

    def test_id_source_confidence_importance(self) -> None:
        item = self._item()
        assert item.id.startswith("cruxset_km_") and item.id == self._item().id
        assert item.source == KnowledgeSource.BELIEF
        assert item.confidence == ConfidenceLevel.from_float(0.8)
        assert item.importance is not None and abs(item.importance - 0.8) < 1e-9

    def test_metadata_and_cross_references_carry_provenance(self) -> None:
        item = self._item()
        meta = item.metadata
        assert meta["cruxset_id"] == self.cruxset.cruxset_id
        assert meta["checksum"] == self.cruxset.checksum
        assert (meta["debate_id"], meta["receipt_id"], meta["decision"]) == (
            "debate-42",
            "rcpt-9",
            "yes",
        )
        assert meta["candidate_verifier"] == "bench/p99"
        assert [p["side"] for p in meta["positions"]] == ["yes", "no"]
        assert meta["agt_issue"] == "AGT-01/#6062"
        assert item.cross_references == [self.cruxset.cruxset_id, "rcpt-9"]


class TestFlagGating:
    def test_skips_when_emission_flag_off(self) -> None:
        mound = _mound()
        result = _ingest(CruxReceiptAdapter(mound=mound), _cruxset())
        assert (result.cruxes_ingested, result.skipped, result.errors) == (0, 1, [])
        mound.store.assert_not_called()

    def test_receipt_flag_does_not_enable_cruxset_ingestion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(RECEIPT_FLAG, "1")
        assert _ingest(CruxReceiptAdapter(mound=_mound()), _cruxset()).skipped == 1

    def test_proceeds_when_emission_flag_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(EMISSION_FLAG, "1")
        result = _ingest(CruxReceiptAdapter(mound=_mound()), _cruxset())
        assert result.cruxes_ingested == 1 and result.success


class TestIngestion:
    def test_stores_one_item_per_crux(self) -> None:
        mound = _mound()
        cruxset = _cruxset((_crux("c1", 0.9), _crux("c2", 0.4)))
        result = _ingest(CruxReceiptAdapter(mound=mound), cruxset, require_enabled=False)
        assert result.cruxes_ingested == 2 and mound.store.call_count == 2
        stored = [call.args[0] for call in mound.store.call_args_list]
        assert all(isinstance(item, KnowledgeItem) for item in stored)
        assert [item.source_id for item in stored] == ["c1", "c2"]

    def test_tampered_cruxset_is_refused(self) -> None:
        payload = _cruxset().to_json()
        payload["cruxes"][0]["statement"] = "tampered"
        mound = _mound()
        result = _ingest(
            CruxReceiptAdapter(mound=mound), CruxSet.from_json(payload), require_enabled=False
        )
        assert (result.cruxes_ingested, result.skipped) == (0, 1)
        assert any("checksum mismatch" in e for e in result.errors)
        mound.store.assert_not_called()

    def test_no_mound_fails_closed(self) -> None:
        result = _ingest(CruxReceiptAdapter(), _cruxset(), require_enabled=False)
        assert result.cruxes_ingested == 0 and result.success is False
        assert any("not configured" in e for e in result.errors)

    def test_store_error_does_not_abort_remaining_cruxes(self) -> None:
        mound = MagicMock()
        mound.store = AsyncMock(side_effect=[RuntimeError("db down"), "stored-2"])
        cruxset = _cruxset((_crux("c1", 0.9), _crux("c2", 0.4)))
        result = _ingest(CruxReceiptAdapter(mound=mound), cruxset, require_enabled=False)
        assert result.cruxes_ingested == 1 and result.knowledge_item_ids == ["stored-2"]
        assert any("c1" in e and "db down" in e for e in result.errors)

    def test_fallback_to_ingest_method(self) -> None:
        mound = MagicMock(spec=["ingest"])
        mound.ingest = AsyncMock()
        result = _ingest(CruxReceiptAdapter(mound=mound), _cruxset(), require_enabled=False)
        mound.ingest.assert_called_once()
        assert result.knowledge_item_ids == [mound.ingest.call_args.args[0].id]
