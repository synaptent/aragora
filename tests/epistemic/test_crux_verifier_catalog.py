"""Unit tests for CruxVerifierCatalog (DIC-15 / #6025).

Covers: VerifierEntry validation, CruxVerifierCatalog.lookup, enrich_cruxset
flag-gate, idempotency, checksum validity, and cruxset_id stability.
"""

from __future__ import annotations

import pytest

from aragora.epistemic.crux_verifier_catalog import (
    CruxVerifierCatalog,
    VerifierEntry,
    enrich_cruxset,
)
from aragora.reasoning.cruxset import Crux, CruxPosition, CruxSet

_ENV_VAR = "ARAGORA_CRUXSET_EMISSION_ENABLED"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pos(side: str) -> CruxPosition:
    return CruxPosition(side=side, agents=("agent_a",))


def _crux(
    crux_id: str,
    statement: str,
    score: float = 0.8,
    candidate_verifier: str = "",
) -> Crux:
    return Crux(
        crux_id=crux_id,
        statement=statement,
        positions=(_pos("yes"), _pos("no")),
        load_bearing_score=score,
        candidate_verifier=candidate_verifier,
    )


def _cruxset(*cruxes: Crux, question: str = "Should we expand now?") -> CruxSet:
    return CruxSet.build(question=question, cruxes=cruxes)


# ---------------------------------------------------------------------------
# VerifierEntry validation
# ---------------------------------------------------------------------------


def test_verifier_entry_empty_pattern_raises() -> None:
    with pytest.raises(ValueError, match="pattern"):
        VerifierEntry(pattern="", verifier="docs/status/foo.md")


def test_verifier_entry_empty_verifier_raises() -> None:
    with pytest.raises(ValueError, match="verifier"):
        VerifierEntry(pattern="bc12.green_shift", verifier="")


# ---------------------------------------------------------------------------
# VerifierEntry.matches
# ---------------------------------------------------------------------------


def test_entry_matches_crux_id_prefix() -> None:
    entry = VerifierEntry(pattern="bc12.", verifier="docs/foo.md")
    assert entry.matches(_crux("bc12.green_shift", "Some statement"))


def test_entry_matches_crux_id_exact() -> None:
    entry = VerifierEntry(pattern="queue.boss_ready", verifier="cmd.sh")
    assert entry.matches(_crux("queue.boss_ready", "Queue state"))


def test_entry_matches_statement_when_not_crux_id_prefix() -> None:
    # "green" is not a prefix of "bc12.green_shift" but IS a substring of the statement
    entry = VerifierEntry(pattern="green", verifier="docs/foo.md")
    crux = _crux("bc12.green_shift", "Three consecutive green soak days required.")
    assert entry.matches(crux)


def test_entry_matches_statement_case_insensitive() -> None:
    entry = VerifierEntry(pattern="GREEN SOAK", verifier="docs/soak.md")
    assert entry.matches(_crux("bc12.x", "Three consecutive green soak days required."))


def test_entry_no_match() -> None:
    entry = VerifierEntry(pattern="unrelated.topic", verifier="docs/bar.md")
    assert not entry.matches(_crux("bc12.green_shift", "Soaks are required."))


# ---------------------------------------------------------------------------
# CruxVerifierCatalog.lookup and from_dict
# ---------------------------------------------------------------------------


def test_catalog_from_dict_insertion_order() -> None:
    catalog = CruxVerifierCatalog.from_dict(
        {
            "bc12.": "docs/first.md",
            "bc12.green": "docs/second.md",
        }
    )
    # First entry should win for a crux_id that matches both prefixes
    crux = _crux("bc12.green_shift", "irrelevant")
    assert catalog.lookup(crux) == "docs/first.md"


def test_catalog_first_matching_entry_wins() -> None:
    catalog = CruxVerifierCatalog.from_dict(
        {
            "soaks are": "docs/soak_policy.md",
            "soaks": "docs/broader.md",
        }
    )
    crux = _crux("crux.x", "Soaks are required before widening.")
    assert catalog.lookup(crux) == "docs/soak_policy.md"


def test_catalog_no_match_returns_empty() -> None:
    catalog = CruxVerifierCatalog.from_dict({"bc12.": "docs/first.md"})
    crux = _crux("queue.boss_ready", "Queue must be empty.")
    assert catalog.lookup(crux) == ""


def test_catalog_from_entries() -> None:
    entries = [
        VerifierEntry("bc12.", "docs/a.md"),
        VerifierEntry("queue.", "docs/b.md"),
    ]
    catalog = CruxVerifierCatalog.from_entries(entries)
    assert len(catalog) == 2
    assert catalog.lookup(_crux("queue.boss_ready", "Queue state")) == "docs/b.md"


# ---------------------------------------------------------------------------
# enrich_cruxset — flag gate
# ---------------------------------------------------------------------------


def test_flag_off_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV_VAR, raising=False)
    catalog = CruxVerifierCatalog.from_dict({"bc12.": "docs/foo.md"})
    cs = _cruxset(_crux("bc12.x", "Something"))
    with pytest.raises(RuntimeError, match=_ENV_VAR):
        enrich_cruxset(cs, catalog)


def test_flag_on_allows_enrich(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_VAR, "1")
    catalog = CruxVerifierCatalog.from_dict({"bc12.": "docs/foo.md"})
    cs = _cruxset(_crux("bc12.x", "Something"))
    result = enrich_cruxset(cs, catalog)
    assert result is not None


# ---------------------------------------------------------------------------
# enrich_cruxset — behaviour
# ---------------------------------------------------------------------------


def test_empty_catalog_returns_original(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_VAR, "1")
    catalog = CruxVerifierCatalog()
    cs = _cruxset(_crux("bc12.x", "Something"))
    assert enrich_cruxset(cs, catalog) is cs


def test_no_match_returns_original(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_VAR, "1")
    catalog = CruxVerifierCatalog.from_dict({"queue.": "docs/queue.md"})
    cs = _cruxset(_crux("bc12.x", "Something unrelated"))
    assert enrich_cruxset(cs, catalog) is cs


def test_enriches_by_crux_id_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_VAR, "1")
    catalog = CruxVerifierCatalog.from_dict({"bc12.": "docs/bc12.md"})
    cs = _cruxset(_crux("bc12.green_shift", "Soaks required."))
    enriched = enrich_cruxset(cs, catalog)
    assert enriched.cruxes[0].candidate_verifier == "docs/bc12.md"


def test_enriches_by_statement_substring(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_VAR, "1")
    catalog = CruxVerifierCatalog.from_dict({"soak equivalence": "docs/soak.md"})
    cs = _cruxset(_crux("crux.x", "The soak equivalence question is unresolved."))
    enriched = enrich_cruxset(cs, catalog)
    assert enriched.cruxes[0].candidate_verifier == "docs/soak.md"


def test_existing_candidate_verifier_not_overwritten(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_VAR, "1")
    catalog = CruxVerifierCatalog.from_dict({"bc12.": "docs/catalog.md"})
    cs = _cruxset(
        _crux("bc12.green_shift", "Soaks required.", candidate_verifier="docs/original.md")
    )
    enriched = enrich_cruxset(cs, catalog)
    # The crux already had a verifier; it must not be overwritten
    assert enriched.cruxes[0].candidate_verifier == "docs/original.md"


def test_partial_enrichment_mixed_cruxes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_VAR, "1")
    catalog = CruxVerifierCatalog.from_dict({"bc12.": "docs/bc12.md"})
    matched = _crux("bc12.green_shift", "Matched.", score=0.9)
    unmatched = _crux("queue.boss_ready", "Queue must be idle.", score=0.7)
    cs = _cruxset(matched, unmatched)
    enriched = enrich_cruxset(cs, catalog)
    # cruxes are sorted by load_bearing_score desc: matched first
    verifiers = {c.crux_id: c.candidate_verifier for c in enriched.cruxes}
    assert verifiers["bc12.green_shift"] == "docs/bc12.md"
    assert verifiers["queue.boss_ready"] == ""


# ---------------------------------------------------------------------------
# enrich_cruxset — checksum and cruxset_id stability
# ---------------------------------------------------------------------------


def test_enriched_checksum_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_VAR, "1")
    catalog = CruxVerifierCatalog.from_dict({"bc12.": "docs/bc12.md"})
    cs = _cruxset(_crux("bc12.green_shift", "Soaks required."))
    enriched = enrich_cruxset(cs, catalog)
    assert enriched.verify_checksum()


def test_cruxset_id_unchanged_after_enrichment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_VAR, "1")
    catalog = CruxVerifierCatalog.from_dict({"bc12.": "docs/bc12.md"})
    cs = _cruxset(_crux("bc12.green_shift", "Soaks required."))
    enriched = enrich_cruxset(cs, catalog)
    # cruxset_id is content-addressed from question + crux IDs only
    assert enriched.cruxset_id == cs.cruxset_id


def test_checksum_changes_after_enrichment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_VAR, "1")
    catalog = CruxVerifierCatalog.from_dict({"bc12.": "docs/bc12.md"})
    cs = _cruxset(_crux("bc12.green_shift", "Soaks required."))
    enriched = enrich_cruxset(cs, catalog)
    # candidate_verifier is included in the checksum payload, so it must change
    assert enriched.checksum != cs.checksum


def test_enrich_idempotent_second_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_VAR, "1")
    catalog = CruxVerifierCatalog.from_dict({"bc12.": "docs/bc12.md"})
    cs = _cruxset(_crux("bc12.green_shift", "Soaks required."))
    enriched = enrich_cruxset(cs, catalog)
    # Second call: all cruxes already have candidate_verifier → original returned
    enriched_again = enrich_cruxset(enriched, catalog)
    assert enriched_again is enriched


# ---------------------------------------------------------------------------
# enrich_cruxset — metadata it must NOT touch (openai review, PR #9565)
# ---------------------------------------------------------------------------


def test_enrich_preserves_deserialized_schema_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enrichment must not restamp schema_version.

    ``CruxSet.build`` defaults schema_version to CRUXSET_SCHEMA_VERSION, so
    rebuilding a set deserialized at an older/future version silently rewrote
    metadata unrelated to candidate_verifier — while ``from_json`` deliberately
    preserves what it read.
    """
    monkeypatch.setenv(_ENV_VAR, "1")
    catalog = CruxVerifierCatalog.from_dict({"bc12.": "docs/foo.md"})

    payload = _cruxset(_crux("bc12.x", "Something")).to_json()
    payload["schema_version"] = "0.9-legacy"
    legacy = CruxSet.from_json(payload)
    assert legacy.schema_version == "0.9-legacy"

    result = enrich_cruxset(legacy, catalog)

    assert result is not legacy, "expected enrichment to produce a new set"
    assert result.cruxes[0].candidate_verifier == "docs/foo.md"
    assert result.schema_version == "0.9-legacy"
    assert result.verify_checksum(), "checksum must cover the preserved version"


def test_whitespace_only_verifier_is_treated_as_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blank candidate_verifier is not "already populated"."""
    monkeypatch.setenv(_ENV_VAR, "1")
    catalog = CruxVerifierCatalog.from_dict({"bc12.": "docs/foo.md"})
    cs = _cruxset(_crux("bc12.x", "Something", candidate_verifier="   "))

    result = enrich_cruxset(cs, catalog)

    assert result.cruxes[0].candidate_verifier == "docs/foo.md"
