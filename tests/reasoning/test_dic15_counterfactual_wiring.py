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
from collections.abc import Iterator
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

import pytest

from aragora.epistemic.followup import MAX_BODY_STATEMENT_CHARS, propose_followup_for_crux
from aragora.reasoning import cruxset_emission as mod
from aragora.reasoning.crux_detector import CruxAnalysisResult, CruxClaim
from aragora.reasoning.cruxset import (
    MAX_CRUX_COUNTERFACTUAL_CHARS,
    CruxSet,
    build_cruxset_from_analysis,
    clip_counterfactual,
)


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
def _reset_flag(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
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


def test_wired_counterfactual_is_covered_by_the_checksum() -> None:
    """The wired text is part of the content-addressed payload, not free-floating metadata."""
    payload = _analysis(_claim("c1", "S", 0.7)).to_dict()
    cs_plain = build_cruxset_from_analysis(question="Q?", analysis_payload=payload)
    cs_rich = build_cruxset_from_analysis(
        question="Q?",
        analysis_payload=payload,
        counterfactuals_by_claim_id={"c1": "Rich text changes the crux"},
    )
    assert cs_plain.verify_checksum()
    assert cs_rich.verify_checksum()
    assert (
        cs_plain.to_json()["cruxes"][0]["counterfactual"]
        != cs_rich.to_json()["cruxes"][0]["counterfactual"]
    )
    # Comparing two freshly built CruxSets proves nothing: created_at is in the
    # canonical payload, so their checksums differ regardless of this field.
    # Tamper with only the counterfactual instead.
    tampered = cs_rich.to_json()
    tampered["cruxes"][0]["counterfactual"] = "Something else entirely"
    assert not CruxSet.from_json(tampered).verify_checksum()


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


# ---------------------------------------------------------------------------
# 3. Bounded note contract — Crux.counterfactual stays a short note
# ---------------------------------------------------------------------------


def _finder_counterfactuals(*claims: CruxClaim) -> list[dict[str, Any]]:
    """Mirror the entries ``build_crux_finder_result`` produces for each crux."""
    return [
        {
            "claim_id": c.claim_id,
            "condition": f"Resolve '{c.statement}' to high confidence",
            "outcome_change": f"Reduces total network uncertainty by {c.resolution_impact:.3f}",
            "likelihood": round(float(c.uncertainty_score), 4),
            "affected_claims": list(c.affected_claims),
        }
        for c in claims
    ]


def test_normal_length_counterfactual_is_not_clipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """An ordinary statement produces the full condition and outcome text, unclipped."""
    monkeypatch.setenv(mod.CRUXSET_EMISSION_ENV_VAR, "1")
    claim = _claim("c1", "Adoption of X reduces p99 latency", 0.85)
    result = _result(_analysis(claim), counterfactuals=_finder_counterfactuals(claim))
    cs = mod.maybe_emit_cruxset_from_finder_result(result)
    assert cs is not None
    text = cs.cruxes[0].counterfactual
    assert text.startswith("Resolve 'Adoption of X reduces p99 latency' to high confidence")
    assert "Reduces total network uncertainty by" in text
    assert "…" not in text
    assert len(text) <= MAX_CRUX_COUNTERFACTUAL_CHARS


def test_long_statement_counterfactual_is_clipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """The finder embeds the unbounded claim statement, so the wired note must be bounded."""
    monkeypatch.setenv(mod.CRUXSET_EMISSION_ENV_VAR, "1")
    claim = _claim("c1", "A" * 5000, 0.85)
    result = _result(_analysis(claim), counterfactuals=_finder_counterfactuals(claim))
    cs = mod.maybe_emit_cruxset_from_finder_result(result)
    assert cs is not None
    text = cs.cruxes[0].counterfactual
    # The clip rstrips before appending the ellipsis, so the bound is an upper
    # limit rather than an exact width.
    assert len(text) <= MAX_CRUX_COUNTERFACTUAL_CHARS
    assert text.startswith("Resolve 'AAA")


def test_clipping_sacrifices_the_statement_not_the_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The uncertainty delta is the signal; a long statement must not push it out."""
    monkeypatch.setenv(mod.CRUXSET_EMISSION_ENV_VAR, "1")
    claim = _claim("c1", "A" * 5000, 0.85)
    result = _result(_analysis(claim), counterfactuals=_finder_counterfactuals(claim))
    cs = mod.maybe_emit_cruxset_from_finder_result(result)
    assert cs is not None
    text = cs.cruxes[0].counterfactual
    assert len(text) <= MAX_CRUX_COUNTERFACTUAL_CHARS
    assert "…" in text
    assert text.endswith(f"Reduces total network uncertainty by {claim.resolution_impact:.3f}")


def test_builder_clips_overrides_from_direct_callers() -> None:
    """The bound belongs to the builder, so it holds for callers that bypass the bridge.

    It bounds what this builder produces, not what ``Crux.from_json`` accepts.
    """
    payload = _analysis(_claim("c1", "S", 0.7)).to_dict()
    cs = build_cruxset_from_analysis(
        question="Q?",
        analysis_payload=payload,
        counterfactuals_by_claim_id={"c1": "Z" * 5000},
    )
    text = cs.cruxes[0].counterfactual
    assert len(text) <= MAX_CRUX_COUNTERFACTUAL_CHARS
    assert text.endswith("…")


def test_clipped_counterfactual_keeps_cruxset_verifiable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clipping happens before the checksum is computed, so the bundle still verifies."""
    monkeypatch.setenv(mod.CRUXSET_EMISSION_ENV_VAR, "1")
    claim = _claim("c1", "B" * 4000, 0.9)
    result = _result(_analysis(claim), counterfactuals=_finder_counterfactuals(claim))
    cs = mod.maybe_emit_cruxset_from_finder_result(result)
    assert cs is not None
    assert cs.verify_checksum()
    assert CruxSet.from_json(cs.to_json()).verify_checksum()


def test_explicit_cf_map_value_is_coerced_to_text() -> None:
    """A non-string override still yields a string field.

    The annotated contract is ``dict[str, str]``; this pins the runtime
    behaviour for callers that violate it, not a wider accepted type.
    """
    payload = _analysis(_claim("c1", "S", 0.7)).to_dict()
    cs = build_cruxset_from_analysis(
        question="Q?",
        analysis_payload=payload,
        counterfactuals_by_claim_id={"c1": 42},  # type: ignore[dict-item]
    )
    assert cs.cruxes[0].counterfactual == "42"


@pytest.mark.parametrize(("value", "expected"), [(0, "0"), (False, "False")])
def test_present_but_falsy_override_is_coerced_not_dropped(value: object, expected: str) -> None:
    """Only absence and blankness fall back; a falsy value is still a value.

    Like the coercion test above, this pins runtime behaviour for callers that
    violate the annotated ``dict[str, str]`` contract.
    """
    payload = _analysis(_claim("c1", "S", 0.7)).to_dict()
    cs = build_cruxset_from_analysis(
        question="Q?",
        analysis_payload=payload,
        counterfactuals_by_claim_id={"c1": value},  # type: ignore[dict-item]
    )
    assert cs.cruxes[0].counterfactual == expected


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_blank_override_falls_back_instead_of_emptying_the_field(blank: str) -> None:
    """A blank override must not suppress the resolution_impact default."""
    payload = _analysis(_claim("c1", "S", 0.7)).to_dict()
    cs = build_cruxset_from_analysis(
        question="Q?",
        analysis_payload=payload,
        counterfactuals_by_claim_id={"c1": blank},
    )
    assert "Resolution impact" in cs.cruxes[0].counterfactual


class _Unrenderable:
    def __str__(self) -> str:
        raise RuntimeError("cannot render")


def test_hostile_override_degrades_to_the_default_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """maybe_emit_cruxset promises not to break a debate, including on this new param.

    The builder coerces only types whose ``str()`` cannot raise, so a hostile
    object degrades this one field instead of losing the whole CruxSet.
    """
    monkeypatch.setenv(mod.CRUXSET_EMISSION_ENV_VAR, "1")
    payload = _analysis(_claim("c1", "S", 0.7)).to_dict()
    cs = mod.maybe_emit_cruxset(
        question="Q?",
        analysis_payload=payload,
        counterfactuals_by_claim_id={"c1": _Unrenderable()},  # type: ignore[dict-item]
    )
    assert cs is not None
    assert "Resolution impact" in cs.cruxes[0].counterfactual


def test_clip_counterfactual_never_exceeds_a_non_positive_limit() -> None:
    """The exported helper must honour its bound for every limit, not just the default."""
    assert clip_counterfactual("some text", 0) == ""
    assert clip_counterfactual("some text", -5) == ""


def test_compose_drops_the_condition_when_the_outcome_fills_the_budget() -> None:
    """With no room for both, the signal-bearing half wins outright."""
    outcome = "Y" * MAX_CRUX_COUNTERFACTUAL_CHARS
    assert mod._compose_counterfactual("Resolve 'X' to high confidence", outcome) == outcome


def test_hostile_finder_entry_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bridge is soft enrichment: a hostile value must not escape as an exception.

    Unlike a hostile override, which degrades a single field, the raw finder
    entry also lands in ``provenance``, which the checksum must serialise. No
    bundle can be built from it, so the whole emission fails closed.
    """
    monkeypatch.setenv(mod.CRUXSET_EMISSION_ENV_VAR, "1")
    claim = _claim("c1", "S", 0.7)
    result = _result(
        _analysis(claim),
        counterfactuals=[{"claim_id": "c1", "condition": _Unrenderable()}],
    )
    assert mod.maybe_emit_cruxset_from_finder_result(result) is None


def test_whitespace_only_finder_entry_is_not_mapped(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bridge drops entries whose text is blank once stripped."""
    monkeypatch.setenv(mod.CRUXSET_EMISSION_ENV_VAR, "1")
    cfs = [{"claim_id": "c1", "condition": "   ", "outcome_change": "\n"}]
    result = _result(_analysis(_claim("c1", "S", 0.8)), counterfactuals=cfs)
    cs = mod.maybe_emit_cruxset_from_finder_result(result)
    assert cs is not None
    assert "Resolution impact" in cs.cruxes[0].counterfactual


def test_producer_bound_fits_the_consumer_body_budget() -> None:
    """Nothing couples the two constants, so pin the relation the DIC-17 body relies on."""
    assert MAX_CRUX_COUNTERFACTUAL_CHARS <= MAX_BODY_STATEMENT_CHARS


# ---------------------------------------------------------------------------
# 4. DIC-17 consumer contract — the follow-up bridge reads Crux.counterfactual
# ---------------------------------------------------------------------------


def _proposal_for(monkeypatch: pytest.MonkeyPatch, claim: CruxClaim, *, wired: bool) -> Any:
    monkeypatch.setenv(mod.CRUXSET_EMISSION_ENV_VAR, "1")
    result = _result(
        _analysis(claim),
        counterfactuals=_finder_counterfactuals(claim) if wired else [],
    )
    cs = mod.maybe_emit_cruxset_from_finder_result(result)
    assert cs is not None
    proposal = propose_followup_for_crux(
        cs.cruxes[0], cruxset_id=cs.cruxset_id, question=cs.question
    )
    assert proposal is not None
    return proposal


def test_followup_body_carries_the_rich_counterfactual(monkeypatch: pytest.MonkeyPatch) -> None:
    """The consumer renders the condition/outcome text instead of the bare score."""
    claim = _claim("c1", "Adoption of X reduces p99 latency", 0.85)
    proposal = _proposal_for(monkeypatch, claim, wired=True)
    assert "## Counterfactual" in proposal.body
    assert "Resolve 'Adoption of X reduces p99 latency' to high confidence" in proposal.body
    assert "Resolution impact" not in proposal.body


def test_followup_counterfactual_section_respects_body_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pathological statement must not smuggle unbounded text past the body budget.

    ``propose_followup_for_crux`` truncates ``statement`` at
    ``MAX_BODY_STATEMENT_CHARS`` but renders ``counterfactual`` verbatim, so the
    producer has to keep the note bounded.
    """
    claim = _claim("c1", "A" * 5000, 0.85)
    proposal = _proposal_for(monkeypatch, claim, wired=True)
    section = proposal.body.split("## Counterfactual", 1)[1].split("\n##", 1)[0].strip()
    assert len(section) <= MAX_BODY_STATEMENT_CHARS


def test_followup_dedup_key_is_unchanged_by_wiring(monkeypatch: pytest.MonkeyPatch) -> None:
    """Richer counterfactual text must not move the DIC-17 dedup key."""
    claim = _claim("c1", "Adoption of X reduces p99 latency", 0.85)
    plain = _proposal_for(monkeypatch, claim, wired=False)
    wired = _proposal_for(monkeypatch, claim, wired=True)
    assert wired.source_key == plain.source_key
    assert wired.provenance == plain.provenance
    assert wired.body != plain.body
