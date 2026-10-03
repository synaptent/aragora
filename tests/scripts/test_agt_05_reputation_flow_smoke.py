"""Tests for ``scripts/agt_05_reputation_flow_smoke.py``.

Covers the substrate-continuation slice added on top of the original
demo PR (#7161): the smoke now accepts a ``--persist <path>`` argument
and round-trips computed deltas through
:class:`aragora.reputation.store.ReputationStore`.

These tests do not run the smoke as a subprocess; they import its
helpers directly to keep the test surface narrow and to avoid coupling
to argv parsing for the pure-computation paths. The store/file
round-trip is verified end-to-end against an actual JSONL on disk.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import agt_05_reputation_flow_smoke as smoke  # noqa: E402

from aragora.reputation.store import ReputationStore  # noqa: E402
from aragora.reputation.types import ReputationDelta  # noqa: E402


@pytest.fixture(autouse=True)
def _enable_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARAGORA_REPUTATION_FLOW_ENABLED", "1")


class TestComputeDeltas:
    def test_returns_one_delta_per_agent_per_question(self) -> None:
        deltas, rows = smoke.compute_deltas()
        n_q = len(smoke.SMOKE_QUESTIONS)
        n_a = len(smoke.SMOKE_AGENT_PREDICTIONS)
        assert len(deltas) == n_q * n_a
        assert len(rows) == n_q * n_a

    def test_each_delta_has_brier_proper_reason(self) -> None:
        deltas, _ = smoke.compute_deltas()
        for d in deltas:
            assert d.scoring_rule == "brier_proper"
            assert "brier" in d.reason
            assert "payout_fraction" in d.reason

    def test_well_calibrated_agent_has_positive_total(self) -> None:
        deltas, _ = smoke.compute_deltas()
        total = sum(d.delta for d in deltas if d.agent_id == "claude-opus-5")
        assert total > 0.0
        # Calibrated at p in {0.90, 0.85, 0.10} against outcomes {yes, yes, no}.
        # Each Brier <= 0.04 -> payout >= 0.92 -> delta >= 9.2; sum >= 27.
        assert total > 25.0

    def test_anti_calibrated_agent_has_negative_total(self) -> None:
        deltas, _ = smoke.compute_deltas()
        total = sum(d.delta for d in deltas if d.agent_id == "demo-anti")
        assert total < 0.0

    def test_indifferent_agent_total_is_modest(self) -> None:
        deltas, _ = smoke.compute_deltas()
        total = sum(d.delta for d in deltas if d.agent_id == "gpt-4.1")
        # gpt-4.1 predictions hover near 0.5 -> small-positive aggregate.
        assert 0.0 < abs(total) < 25.0

    def test_rows_align_with_deltas(self) -> None:
        deltas, rows = smoke.compute_deltas()
        for d, r in zip(deltas, rows, strict=True):
            assert r["agent"] == d.agent_id
            assert abs(r["delta"] - round(d.delta, 3)) < 1e-9

    def test_custom_predictions_yield_custom_deltas(self) -> None:
        custom_questions = [("manifold-9001", "Custom Q?", 1.0)]
        custom_predictions = {"agent-X": [0.99]}
        deltas, rows = smoke.compute_deltas(
            questions=custom_questions,
            agent_predictions=custom_predictions,
        )
        assert len(deltas) == 1
        assert deltas[0].agent_id == "agent-X"
        # p=0.99 against outcome yes -> Brier=0.0001 -> payout ~= 0.9998
        assert deltas[0].delta > 9.99


class TestPersistToStore:
    def test_persist_writes_jsonl_file(self, tmp_path: Path) -> None:
        deltas, _ = smoke.compute_deltas()
        ledger = tmp_path / "ledger.jsonl"
        store, scores = smoke.persist_to_store(deltas, ledger)
        assert ledger.exists()
        # one JSON line per delta
        line_count = sum(1 for _ in ledger.read_text(encoding="utf-8").splitlines() if _.strip())
        assert line_count == len(deltas)
        assert len(store) == len(deltas)

    def test_store_scores_match_per_agent_totals(self, tmp_path: Path) -> None:
        deltas, _ = smoke.compute_deltas()
        ledger = tmp_path / "ledger.jsonl"
        _, scores = smoke.persist_to_store(deltas, ledger)
        # Decay over <1s should be effectively 1.0; compare to undecayed sum.
        for agent_id in smoke.SMOKE_AGENT_PREDICTIONS:
            raw_total = sum(d.delta for d in deltas if d.agent_id == agent_id)
            assert agent_id in scores
            assert abs(scores[agent_id] - raw_total) < 0.01

    def test_persist_then_load_roundtrip(self, tmp_path: Path) -> None:
        deltas, _ = smoke.compute_deltas()
        ledger = tmp_path / "ledger.jsonl"
        smoke.persist_to_store(deltas, ledger)
        reloaded = ReputationStore.load_from_file(ledger)
        assert len(reloaded) == len(deltas)
        # Same set of agent ids.
        assert set(reloaded.agent_ids()) == set(smoke.SMOKE_AGENT_PREDICTIONS.keys())
        # Same per-agent score (within decay tolerance).
        for agent_id in smoke.SMOKE_AGENT_PREDICTIONS:
            original_score = sum(d.delta for d in deltas if d.agent_id == agent_id)
            reloaded_score = reloaded.get_score(agent_id, apply_decay=False)
            assert abs(reloaded_score - original_score) < 1e-6

    def test_persist_append_only_when_called_twice(self, tmp_path: Path) -> None:
        deltas, _ = smoke.compute_deltas()
        ledger = tmp_path / "ledger.jsonl"
        smoke.persist_to_store(deltas, ledger)
        line_count_a = sum(1 for _ in ledger.read_text(encoding="utf-8").splitlines() if _.strip())
        # Second invocation should append (not overwrite). The store class
        # appends to file via _append_to_file; recording the same deltas a
        # second time will write them again because they have new applied_at
        # timestamps via the new ReputationDelta instances.
        deltas2, _ = smoke.compute_deltas()
        smoke.persist_to_store(deltas2, ledger)
        line_count_b = sum(1 for _ in ledger.read_text(encoding="utf-8").splitlines() if _.strip())
        assert line_count_b == line_count_a + len(deltas2)


class TestCli:
    def test_parse_args_persist_optional(self) -> None:
        ns = smoke._parse_args([])
        assert ns.persist is None
        assert ns.json is False

    def test_parse_args_persist_path(self, tmp_path: Path) -> None:
        target = tmp_path / "ledger.jsonl"
        ns = smoke._parse_args(["--persist", str(target)])
        assert ns.persist == target

    def test_smoke_returns_2_when_flag_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARAGORA_REPUTATION_FLOW_ENABLED", raising=False)
        rc = smoke._smoke([])
        assert rc == 2

    def test_help_works_when_flag_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARAGORA_REPUTATION_FLOW_ENABLED", raising=False)
        with pytest.raises(SystemExit) as excinfo:
            smoke._smoke(["--help"])
        assert excinfo.value.code == 0

    def test_smoke_returns_0_when_flag_on(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = smoke._smoke([])
        captured = capsys.readouterr()
        assert rc == 0
        assert "AGT-05 Reputation Flow Smoke Test" in captured.out

    def test_smoke_with_persist_writes_ledger(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger = tmp_path / "ledger.jsonl"
        rc = smoke._smoke(["--persist", str(ledger)])
        assert rc == 0
        captured = capsys.readouterr()
        assert ledger.exists()
        assert "Persisted" in captured.out
        assert str(ledger) in captured.out


def test_module_uses_existing_store_no_duplicate_module() -> None:
    """Guard: the smoke must reuse ReputationStore; it must not define its own ledger."""
    src = (SCRIPTS / "agt_05_reputation_flow_smoke.py").read_text(encoding="utf-8")
    assert "from aragora.reputation.store import ReputationStore" in src
    # No private ledger class re-defined in this script.
    assert "class ReputationLedger" not in src
    assert "class ReputationStore" not in src


def test_delta_id_stable_for_smoke_scenario() -> None:
    """Deltas should be deterministic given the smoke inputs (modulo timestamps)."""
    a, _ = smoke.compute_deltas()
    b, _ = smoke.compute_deltas()
    assert len(a) == len(b)
    # delta values are deterministic functions of (p, outcome, stake), so
    # numerical fields must match exactly even though delta_ids differ.
    for d1, d2 in zip(a, b, strict=True):
        assert d1.agent_id == d2.agent_id
        assert d1.domain == d2.domain
        assert d1.delta == pytest.approx(d2.delta)
        assert d1.reason.get("brier") == pytest.approx(d2.reason.get("brier"))


def test_store_scores_match_smoke_table_in_e2e_run(tmp_path: Path) -> None:
    """End-to-end check: smoke produces N deltas, store reads back same N agents."""
    ledger = tmp_path / "ledger.jsonl"
    rc = smoke._smoke(["--persist", str(ledger)])
    assert rc == 0
    reloaded = ReputationStore.load_from_file(ledger)
    # Should have the canonical 3 agents.
    assert set(reloaded.agent_ids()) == {"claude-opus-5", "gpt-4.1", "demo-anti"}
    # claude-opus-5 has been well-calibrated -> positive score even after decay.
    claude_score = reloaded.get_score("claude-opus-5")
    assert claude_score > 0.0
    # demo-anti has been systematically wrong -> negative score.
    anti_score = reloaded.get_score("demo-anti")
    assert anti_score < 0.0
    # Type assertions hold for delta objects.
    for agent_id in reloaded.agent_ids():
        for d in reloaded.deltas_for(agent_id):
            assert isinstance(d, ReputationDelta)
            assert d.scoring_rule == "brier_proper"
