"""DIC-15 (#6025): per-crux counterfactual wiring tests.

Verifies that the validation-pass counterfactual text from
``CruxFinderResult.counterfactuals`` is propagated into individual
``Crux.counterfactual`` fields when building a ``CruxSet`` via
``maybe_emit_cruxset_from_finder_result``.

Prior to this slice, counterfactuals were stored only in ``provenance``
(the whole list) and not threaded per-crux. Each ``Crux.counterfactual``
fell back to the bare ``"Resolution impact X.XXXX"`` text. AGT-05 and any
consumer that reads per-crux hooks needs the richer condition/outcome text.

All tests are deterministic; no Arena, no network, no live agents.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

import pytest

from aragora.reasoning import cruxset_emission as mod
from aragora.reasoning.crux_detector import CruxAnalysisResult, CruxClaim
from aragora.reasoning.cruxset import CruxSet, build_cruxset_from_analysis


# ---------------------------------------------------------------------------
# Stub for CruxFinderResult when debate backend not importable
# ---------------------------------------------------------------------------

try:
    from aragora.debate.crux_mode import CruxFinderResult as _ResultClass  # type: ignore[assignment]

    _USE_STUB = False
except BaseException:  # noqa: BLE001
    _USE_STUB = True

    @dataclass  # type: ignore[no-redef]
    class _ResultClass:  # type: ignore[no-redef]
        debate_id: str
        question: str
        analysis: Any
        counterfactuals: list[dict[str, Any]] = field(default_factory=list)
        agents: list[str] = field(default_factory=list)
        rounds: int = 0
        raw_claims: list[dict[str, Any]] = field(default_factory=list)
        metadata: dict[str, Any] = field(default_factory=dict)


@pytest.fixture(autouse=True)
def _inject_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    if not _USE_STUB:
        return
    stub = ModuleType("aragora.debate.crux_mode")
    stub.CruxFinderResult = _ResultClass  # type: ignore[attr-defined]
    if "aragora.debate" not in sys.modules:
        monkeypatch.setitem(sys.modules, "aragora.debate", ModuleType("aragora.debate"))
    monkeypatch.setitem(sys.modules, "aragora.debate.crux_mode", stub)


@pytest.fixture(autouse=True)
def _reset_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(mod.CRUXSET_EMISSION_ENV_VAR, raising=False)
    yield
    monkeypatch.delenv(mod.CRUXSET_EMISSION_ENV_VAR, raising=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _claim(claim_id: str, statement: str, score: float) -> CruxClaim:
    return CruxClaim(
        claim_id=claim_id,
        statement=statement,
        author="agent-alpha",
        crux_score=score,
        influence_score=score * 0.9,
        disagreement_score=score * 0.8,
        uncertainty_score=score * 0.5,
        centrality_score=score * 0.7,
        affected_claims=[],
        contesting_agents=["agent-beta"],
        resolution_impact=score * 0.4,
    )


def _analysis(*claims: CruxClaim) -> CruxAnalysisResult:
    return CruxAnalysisResult(
        cruxes=list(claims),
        total_claims=len(claims) + 2,
        total_disagreements=len(claims),
        average_uncertainty=0.45,
        convergence_barrier=0.5,
        recommended_focus=[c.claim_id for c in claims],
    )


def _result(
    analysis: Any,
    *,
    counterfactuals: list[dict[str, Any]] | None = None,
    debate_id: str = "d-test",
    question: str = "Should we do X?",
) -> Any:
    return _ResultClass(
        debate_id=debate_id,
        question=question,
        analysis=analysis,
        counterfactuals=list(counterfactuals or []),
        agents=["agent-alpha", "agent-beta"],
        rounds=2,
        raw_claims=[],
        metadata={"mode": "crux_finder"},
    )


# ---------------------------------------------------------------------------
# 1. build_cruxset_from_analysis — counterfactuals_by_claim_id param
# ---------------------------------------------------------------------------


def test_build_cruxset_falls_back_to_resolution_impact_when_no_cf_map() -> None:
    """Without a cf map, Crux.counterfactual uses the resolution_impact fallback."""
    payload = _analysis(_claim("c1", "Some claim", 0.8)).to_dict()
    cs = build_cruxset_from_analysis(question="Q?", analysis_payload=payload)
    # The only crux should have the resolution_impact string.
    assert len(cs.cruxes) == 1
    assert "Resolution impact" in cs.cruxes[0].counterfactual


def test_build_cruxset_uses_cf_map_when_provided() -> None:
    """Crux.counterfactual is overridden by counterfactuals_by_claim_id when claim_id matches."""
    payload = _analysis(_claim("c1", "Load-bearing claim", 0.8)).to_dict()
    cs = build_cruxset_from_analysis(
        question="Q?",
        analysis_payload=payload,
        counterfactuals_by_claim_id={"c1": "If c1 resolves true, adoption probability doubles"},
    )
    assert cs.cruxes[0].counterfactual == "If c1 resolves true, adoption probability doubles"


def test_build_cruxset_cf_map_partial_match() -> None:
    """Only matching claim IDs get the override; unmatched fall back to resolution_impact."""
    payload = _analysis(_claim("c1", "Matched", 0.9), _claim("c2", "Unmatched", 0.6)).to_dict()
    cs = build_cruxset_from_analysis(
        question="Q?",
        analysis_payload=payload,
        counterfactuals_by_claim_id={"c1": "Rich override for c1"},
    )
    crux_by_id = {c.crux_id: c for c in cs.cruxes}
    assert crux_by_id["c1"].counterfactual == "Rich override for c1"
    assert "Resolution impact" in crux_by_id["c2"].counterfactual


def test_build_cruxset_empty_cf_map_uses_fallback() -> None:
    """An empty cf map is equivalent to no map."""
    payload = _analysis(_claim("c1", "S", 0.7)).to_dict()
    cs = build_cruxset_from_analysis(
        question="Q?",
        analysis_payload=payload,
        counterfactuals_by_claim_id={},
    )
    assert "Resolution impact" in cs.cruxes[0].counterfactual


def test_build_cruxset_cf_map_does_not_affect_checksum_stability() -> None:
    """Two CruxSets built with different cf text must have different checksums (content-addressed)."""
    payload = _analysis(_claim("c1", "S", 0.7)).to_dict()
    cs_plain = build_cruxset_from_analysis(question="Q?", analysis_payload=payload)
    cs_rich = build_cruxset_from_analysis(
        question="Q?",
        analysis_payload=payload,
        counterfactuals_by_claim_id={"c1": "Rich text changes the crux"},
    )
    assert cs_plain.checksum != cs_rich.checksum
    assert cs_plain.verify_checksum()
    assert cs_rich.verify_checksum()


# ---------------------------------------------------------------------------
# 2. maybe_emit_cruxset_from_finder_result — end-to-end wiring
# ---------------------------------------------------------------------------


def test_crux_counterfactual_uses_rich_text_when_validation_ran(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When CruxFinderResult.counterfactuals is populated, Crux.counterfactual gets the rich text."""
    monkeypatch.setenv(mod.CRUXSET_EMISSION_ENV_VAR, "1")
    rich_cf = [
        {
            "claim_id": "c1",
            "condition": "Resolve 'Load-bearing claim' to high confidence",
            "outcome_change": "Reduces total network uncertainty by 0.720",
            "likelihood": 0.6,
            "affected_claims": ["c2"],
        }
    ]
    result = _result(_analysis(_claim("c1", "Load-bearing claim", 0.85)), counterfactuals=rich_cf)
    cs = mod.maybe_emit_cruxset_from_finder_result(result)
    assert cs is not None
    assert len(cs.cruxes) == 1
    cf_text = cs.cruxes[0].counterfactual
    assert "Resolve 'Load-bearing claim' to high confidence" in cf_text
    assert "Reduces total network uncertainty by 0.720" in cf_text


def test_crux_counterfactual_falls_back_when_validation_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When CruxFinderResult.counterfactuals is empty, Crux.counterfactual falls back to resolution_impact."""
    monkeypatch.setenv(mod.CRUXSET_EMISSION_ENV_VAR, "1")
    result = _result(_analysis(_claim("c1", "S", 0.7)), counterfactuals=[])
    cs = mod.maybe_emit_cruxset_from_finder_result(result)
    assert cs is not None
    assert "Resolution impact" in cs.cruxes[0].counterfactual


def test_multi_crux_wiring_matches_each_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each crux gets its own counterfactual from the list (matched by claim_id)."""
    monkeypatch.setenv(mod.CRUXSET_EMISSION_ENV_VAR, "1")
    cfs = [
        {
            "claim_id": "c1",
            "condition": "c1 condition",
            "outcome_change": "c1 outcome",
        },
        {
            "claim_id": "c2",
            "condition": "c2 condition",
            "outcome_change": "c2 outcome",
        },
    ]
    result = _result(
        _analysis(_claim("c1", "First", 0.9), _claim("c2", "Second", 0.6)),
        counterfactuals=cfs,
    )
    cs = mod.maybe_emit_cruxset_from_finder_result(result)
    assert cs is not None
    crux_by_id = {c.crux_id: c for c in cs.cruxes}
    assert "c1 condition" in crux_by_id["c1"].counterfactual
    assert "c1 outcome" in crux_by_id["c1"].counterfactual
    assert "c2 condition" in crux_by_id["c2"].counterfactual
    assert "c2 outcome" in crux_by_id["c2"].counterfactual


def test_malformed_cf_entries_skipped_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-dict entries and entries without claim_id are skipped; valid ones still wire."""
    monkeypatch.setenv(mod.CRUXSET_EMISSION_ENV_VAR, "1")
    cfs: list[Any] = [
        "not-a-dict",
        {"claim_id": "", "condition": "empty id"},
        {"claim_id": "c1", "condition": "valid condition", "outcome_change": "valid outcome"},
    ]
    result = _result(_analysis(_claim("c1", "S", 0.8)), counterfactuals=cfs)
    cs = mod.maybe_emit_cruxset_from_finder_result(result)
    assert cs is not None
    assert "valid condition" in cs.cruxes[0].counterfactual


def test_wiring_does_not_affect_flag_off_behaviour(monkeypatch: pytest.MonkeyPatch) -> None:
    """When emission is disabled, the function still returns None regardless of cf data."""
    monkeypatch.delenv(mod.CRUXSET_EMISSION_ENV_VAR, raising=False)
    rich_cf = [{"claim_id": "c1", "condition": "c", "outcome_change": "o"}]
    result = _result(_analysis(_claim("c1", "S", 0.8)), counterfactuals=rich_cf)
    assert mod.maybe_emit_cruxset_from_finder_result(result) is None


def test_cruxset_checksum_valid_after_wiring(monkeypatch: pytest.MonkeyPatch) -> None:
    """A CruxSet built with the richer counterfactual text must still verify its checksum."""
    monkeypatch.setenv(mod.CRUXSET_EMISSION_ENV_VAR, "1")
    cfs = [{"claim_id": "c1", "condition": "rich", "outcome_change": "large drop"}]
    result = _result(_analysis(_claim("c1", "S", 0.8)), counterfactuals=cfs)
    cs = mod.maybe_emit_cruxset_from_finder_result(result)
    assert cs is not None
    assert cs.verify_checksum()
