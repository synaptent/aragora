"""Tests for DIC-16 ExecutableClaimAdapter (pure schema/logic)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.epistemic.claim_verifier import ClaimResult, ClaimStatus
from aragora.knowledge.mound.adapters.executable_claim_adapter import (
    ClaimIngestionResult,
    ExecutableClaimAdapter,
    _stable_id,
)
from aragora.knowledge.unified.types import ConfidenceLevel, KnowledgeSource


def _r(status: ClaimStatus = ClaimStatus.PASS, cid: str = "b0.claim") -> ClaimResult:
    return ClaimResult(claim_id=cid, status=status, message="ok", severity="info")


def _mound(sid: str = "stored-1") -> MagicMock:
    m = MagicMock()
    m.store = AsyncMock(return_value=sid)
    return m


# ── ClaimIngestionResult ──────────────────────────────────────────────────────


class TestClaimIngestionResult:
    def test_success(self) -> None:
        assert ClaimIngestionResult(1, ["x"]).success is True

    def test_no_ingested_is_failure(self) -> None:
        assert ClaimIngestionResult(0, []).success is False

    def test_errors_mark_failure(self) -> None:
        assert ClaimIngestionResult(1, ["x"], errors=["e"]).success is False

    def test_to_dict(self) -> None:
        d = ClaimIngestionResult(2, ["a", "b"]).to_dict()
        assert d["claims_ingested"] == 2 and d["success"] is True


# ── _stable_id ────────────────────────────────────────────────────────────────


def test_stable_id_hex16_and_deterministic() -> None:
    r = _stable_id("c", "fail")
    assert len(r) == 16 and all(c in "0123456789abcdef" for c in r)
    assert _stable_id("c", "fail") == _stable_id("c", "fail")
    assert _stable_id("a", "pass") != _stable_id("a", "fail")


# ── _build_item ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "status,conf",
    [
        (ClaimStatus.PASS, ConfidenceLevel.HIGH),
        (ClaimStatus.FAIL, ConfidenceLevel.LOW),
        (ClaimStatus.STALE, ConfidenceLevel.MEDIUM),
        (ClaimStatus.ERROR, ConfidenceLevel.LOW),
    ],
)
def test_confidence_mapping(status: ClaimStatus, conf: ConfidenceLevel) -> None:
    item = ExecutableClaimAdapter()._build_item(_r(status), datetime.now(UTC))
    assert item.confidence == conf


def test_item_fields() -> None:
    item = ExecutableClaimAdapter()._build_item(
        _r(ClaimStatus.FAIL, cid="x.claim"), datetime(2026, 7, 30, tzinfo=UTC)
    )
    assert item.source == KnowledgeSource.BELIEF
    assert item.id == "claim_km_" + _stable_id("x.claim", "fail")
    assert item.source_id == "x.claim"
    assert "x.claim" in item.content and "fail" in item.content
    assert item.metadata["dic_issue"] == "DIC-16/#6026"
    assert (
        item.importance
        > ExecutableClaimAdapter()
        ._build_item(_r(ClaimStatus.PASS, cid="x.claim"), datetime(2026, 7, 30, tzinfo=UTC))
        .importance
    )


# ── flag gating ───────────────────────────────────────────────────────────────


class TestFlagGating:
    def test_skips_when_flag_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARAGORA_EPISTEMIC_CLAIMS_ENABLED", raising=False)
        r = asyncio.run(ExecutableClaimAdapter(mound=_mound()).ingest_claim_result(_r()))
        assert r.claims_ingested == 0 and r.skipped == 1

    def test_proceeds_when_flag_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_EPISTEMIC_CLAIMS_ENABLED", "1")
        r = asyncio.run(ExecutableClaimAdapter(mound=_mound("y")).ingest_claim_result(_r()))
        assert r.claims_ingested == 1 and r.knowledge_item_ids == ["y"]

    def test_bypass_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARAGORA_EPISTEMIC_CLAIMS_ENABLED", raising=False)
        r = asyncio.run(
            ExecutableClaimAdapter(mound=_mound()).ingest_claim_result(_r(), require_enabled=False)
        )
        assert r.claims_ingested == 1


# ── batch & error paths ───────────────────────────────────────────────────────


class TestBatch:
    def test_skips_batch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARAGORA_EPISTEMIC_CLAIMS_ENABLED", raising=False)
        r = asyncio.run(
            ExecutableClaimAdapter(mound=_mound()).ingest_claim_results(
                [_r(cid=f"c{i}") for i in range(3)]
            )
        )
        assert r.claims_ingested == 0 and r.skipped == 3

    @pytest.mark.parametrize(
        "error",
        [
            RuntimeError("down"),
            TypeError("bad store contract"),
            ValueError("invalid item"),
            OSError("transport unavailable"),
        ],
    )
    def test_store_error_captured(self, monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
        monkeypatch.setenv("ARAGORA_EPISTEMIC_CLAIMS_ENABLED", "1")
        bad = MagicMock()
        bad.store = AsyncMock(side_effect=error)
        r = asyncio.run(ExecutableClaimAdapter(mound=bad).ingest_claim_results([_r()]))
        assert r.claims_ingested == 0 and str(error) in r.errors[0]

    def test_unexpected_store_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_EPISTEMIC_CLAIMS_ENABLED", "1")
        bad = MagicMock()
        bad.store = AsyncMock(side_effect=AssertionError("programmer defect"))

        with pytest.raises(AssertionError, match="programmer defect"):
            asyncio.run(ExecutableClaimAdapter(mound=bad).ingest_claim_results([_r()]))


def test_no_mound_returns_generated_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARAGORA_EPISTEMIC_CLAIMS_ENABLED", raising=False)
    r = asyncio.run(ExecutableClaimAdapter().ingest_claim_result(_r(), require_enabled=False))
    assert r.claims_ingested == 1 and r.knowledge_item_ids[0].startswith("claim_km_")


# ── real-mound ingestion contract ─────────────────────────────────────────────


class _NoIngestionContractMound:
    """A configured mound exposing neither ``store`` nor ``ingest``."""


class TestIngestionContract:
    def test_mound_without_ingestion_contract_is_not_counted_as_ingested(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ARAGORA_EPISTEMIC_CLAIMS_ENABLED", "1")
        r = asyncio.run(
            ExecutableClaimAdapter(mound=_NoIngestionContractMound()).ingest_claim_results([_r()])
        )
        assert r.claims_ingested == 0
        assert r.knowledge_item_ids == []
        assert r.success is False
        assert "store" in r.errors[0] and "ingest" in r.errors[0]

    def test_attribute_error_from_store_is_captured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_EPISTEMIC_CLAIMS_ENABLED", "1")
        bad = MagicMock()
        bad.store = AsyncMock(
            side_effect=AttributeError("'KnowledgeItem' object has no attribute 'workspace_id'")
        )
        r = asyncio.run(ExecutableClaimAdapter(mound=bad).ingest_claim_results([_r()]))
        assert r.claims_ingested == 0
        assert "workspace_id" in r.errors[0]

    def test_store_failure_does_not_abort_remaining_claims(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ARAGORA_EPISTEMIC_CLAIMS_ENABLED", "1")
        mound = MagicMock()
        mound.store = AsyncMock(side_effect=[AttributeError("workspace_id"), "stored-2"])
        r = asyncio.run(
            ExecutableClaimAdapter(mound=mound).ingest_claim_results([_r(cid="c1"), _r(cid="c2")])
        )
        assert r.claims_ingested == 1
        assert r.knowledge_item_ids == ["stored-2"]
        assert len(r.errors) == 1 and "c1" in r.errors[0]
