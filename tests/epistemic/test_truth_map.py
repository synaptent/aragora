"""Tests for DIC-18 Organizational Truth Map (aragora.epistemic.truth_map).

Includes DIC-24 genealogy drill-down tests (GenealogyRow integration).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aragora.epistemic.claim_verifier import ClaimResult, ClaimStatus
from aragora.epistemic.truth_map import build_truth_map, build_truth_map_from_manifests


def _cr(cid: str, status: ClaimStatus, detail: dict | None = None) -> ClaimResult:
    return ClaimResult(claim_id=cid, status=status, message="", detail=detail or {})


def _mock_cfr(
    debate_id: str, question: str, scores: list[float], barrier: float = 0.5
) -> MagicMock:
    cruxes = []
    for i, s in enumerate(scores):
        c = MagicMock()
        c.crux_score = s
        c.to_dict.return_value = {"claim_id": f"c{i}", "crux_score": s}
        cruxes.append(c)
    analysis = MagicMock()
    analysis.cruxes = cruxes
    cfr = MagicMock()
    cfr.debate_id, cfr.question, cfr.analysis = debate_id, question, analysis
    cfr.top_cruxes.return_value = cruxes
    cfr.convergence_barrier.return_value = barrier
    return cfr


class TestBuildTruthMap:
    def test_empty_inputs_zero_counts(self) -> None:
        r = build_truth_map(claim_results=[])
        assert r.total_claims == 0 and r.open_crux_count == 0

    def test_generated_at_is_utc_iso(self) -> None:
        assert build_truth_map(claim_results=[]).generated_at.endswith("Z")

    def test_mixed_status_counts(self) -> None:
        results = [
            _cr("a", ClaimStatus.PASS),
            _cr("b", ClaimStatus.FAIL),
            _cr("c", ClaimStatus.STALE),
            _cr("d", ClaimStatus.UNSUPPORTED),
            _cr("e", ClaimStatus.ERROR),
        ]
        r = build_truth_map(claim_results=results)
        assert r.total_claims == 5
        assert (r.passing_claims, r.failing_claims, r.stale_claims) == (1, 1, 1)

    def test_claim_row_status_is_string(self) -> None:
        r = build_truth_map(claim_results=[_cr("x", ClaimStatus.FAIL)])
        assert r.claims[0].status == "fail"

    def test_metadata_populates_fields(self) -> None:
        meta = {
            "m": {
                "statement": "OK",
                "owner": "team",
                "verification": {"kind": "command", "command": "pytest"},
            }
        }
        r = build_truth_map(claim_results=[_cr("m", ClaimStatus.PASS)], claim_metadata=meta)
        row = r.claims[0]
        assert row.statement == "OK" and row.owner == "team"
        assert row.verifier_kind == "command" and row.verifier_command == "pytest"

    def test_missing_metadata_falls_back_to_empty(self) -> None:
        r = build_truth_map(claim_results=[_cr("x", ClaimStatus.PASS)])
        assert r.claims[0].statement == "" and r.claims[0].owner == ""

    def test_detail_evidence_age_and_follow_up_link(self) -> None:
        r = build_truth_map(
            claim_results=[
                _cr(
                    "x",
                    ClaimStatus.STALE,
                    {"evidence_age_hours": 36.5, "follow_up_link": "https://gh/1"},
                )
            ]
        )
        assert r.claims[0].evidence_age_hours == pytest.approx(36.5)
        assert r.claims[0].follow_up_link == "https://gh/1"

    def test_crux_summary_open_count_and_barrier(self) -> None:
        cfr = _mock_cfr("d1", "B2?", [0.8, 0.5, 0.1], barrier=0.6)
        r = build_truth_map(claim_results=[], crux_results=[cfr], open_crux_score_threshold=0.3)
        assert r.open_crux_count == 2
        row = r.crux_summaries[0]
        assert row.debate_id == "d1" and row.open_cruxes == 2
        assert row.convergence_barrier == pytest.approx(0.6)

    def test_top_k_limits_cruxes_in_summary(self) -> None:
        cfr = _mock_cfr("d", "Q", [0.9, 0.8, 0.7, 0.6])
        r = build_truth_map(claim_results=[], crux_results=[cfr], top_k_cruxes=2)
        assert len(r.crux_summaries[0].top_cruxes) == 2

    def test_multiple_crux_results_aggregate(self) -> None:
        r = build_truth_map(
            claim_results=[],
            crux_results=[_mock_cfr("d1", "Q1", [0.9, 0.1]), _mock_cfr("d2", "Q2", [0.7, 0.6])],
            open_crux_score_threshold=0.3,
        )
        assert r.open_crux_count == 3

    def test_to_dict_structure(self) -> None:
        results = [_cr("x", ClaimStatus.PASS)]
        d = build_truth_map(claim_results=results).to_dict()
        assert {"generated_at", "claims", "crux_summaries", "summary"} <= d.keys()
        assert d["summary"].keys() == {
            "total_claims",
            "passing",
            "failing",
            "stale",
            "unsupported",
            "error",
            "open_crux_count",
        }


class TestBuildTruthMapFromManifests:
    def test_real_manifest_dry_run(self) -> None:
        manifest = Path("docs/status/claims/proof_first_claims.yaml")
        assert manifest.exists(), "required DIC-13 manifest fixture is missing"
        r = build_truth_map_from_manifests(manifest_paths=[manifest])
        assert r.total_claims > 0
        assert all(row.statement for row in r.claims)
        assert "b0.benchmark_truth.complete_current_corpus" in {row.claim_id for row in r.claims}


# ---------------------------------------------------------------------------
# DIC-24: GenealogyRow integration tests
# ---------------------------------------------------------------------------


class TestGenealogyRows:
    """Verify that build_truth_map populates genealogy drill-downs (DIC-24)."""

    def _store_with_entries(self) -> tuple[object, str]:
        """Return (InMemoryGenealogyStore, code_unit_id) with two sample entries."""
        from aragora.epistemic.genealogy import GenealogyEntry, InMemoryGenealogyStore

        store = InMemoryGenealogyStore()
        uid = "scripts.run_proof_first_shift.evaluate_green_shift"
        store.add(
            uid,
            GenealogyEntry(
                entry_kind="decision_receipt",
                entry_id="dr-001",
                checksum="aabbcc112233",
                timestamp="2026-04-16T10:00:00Z",
            ),
        )
        store.add(
            uid,
            GenealogyEntry(
                entry_kind="decay_signal",
                entry_id="ds-002",
                checksum="ddeeff445566",
                timestamp="2026-05-01T08:30:00Z",
            ),
        )
        return store, uid

    def test_genealogy_row_to_dict_structure(self) -> None:
        from aragora.epistemic.truth_map import GenealogyRow

        row = GenealogyRow(
            code_unit_id="unit.a",
            entry_count=2,
            chain_checksum="deadbeef",
            generated_at="2026-06-03T00:00:00Z",
            entries=[{"entry_kind": "decay_signal", "entry_id": "ds-1"}],
        )
        d = row.to_dict()
        assert d["code_unit_id"] == "unit.a"
        assert d["entry_count"] == 2
        assert d["chain_checksum"] == "deadbeef"
        assert len(d["entries"]) == 1

    def test_genealogy_disabled_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARAGORA_GENEALOGY_ENABLED", raising=False)
        store, uid = self._store_with_entries()
        r = build_truth_map(
            claim_results=[],
            genealogy_inputs=[(uid, store)],  # type: ignore[list-item]
        )
        assert r.genealogies == []

    def test_genealogy_enabled_populates_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_GENEALOGY_ENABLED", "1")
        store, uid = self._store_with_entries()
        r = build_truth_map(
            claim_results=[],
            genealogy_inputs=[(uid, store)],  # type: ignore[list-item]
        )
        assert len(r.genealogies) == 1
        row = r.genealogies[0]
        assert row.code_unit_id == uid
        assert row.entry_count == 2
        assert len(row.chain_checksum) == 64  # SHA-256 hex
        assert len(row.entries) == 2

    def test_genealogy_enabled_surfaces_store_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class BrokenStore:
            def get_entries(self, code_unit_id: str) -> list[object]:
                raise RuntimeError(f"broken lineage for {code_unit_id}")

        monkeypatch.setenv("ARAGORA_GENEALOGY_ENABLED", "1")

        with pytest.raises(RuntimeError, match="broken lineage"):
            build_truth_map(
                claim_results=[],
                genealogy_inputs=[("unit.a", BrokenStore())],  # type: ignore[list-item]
            )

    def test_proof_first_shift_unit_id_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The real DIC-24 target code unit ID round-trips through the report."""
        monkeypatch.setenv("ARAGORA_GENEALOGY_ENABLED", "1")
        store, uid = self._store_with_entries()
        r = build_truth_map(claim_results=[], genealogy_inputs=[(uid, store)])  # type: ignore[list-item]
        assert r.genealogies[0].code_unit_id == uid

    def test_to_dict_includes_genealogies_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_GENEALOGY_ENABLED", "1")
        store, uid = self._store_with_entries()
        d = build_truth_map(
            claim_results=[],
            genealogy_inputs=[(uid, store)],  # type: ignore[list-item]
        ).to_dict()
        assert "genealogies" in d
        assert len(d["genealogies"]) == 1
        assert d["genealogies"][0]["entry_count"] == 2

    def test_genealogy_no_inputs_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_GENEALOGY_ENABLED", "1")
        r = build_truth_map(claim_results=[])
        assert r.genealogies == []
