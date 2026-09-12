"""Dependency-free tests for the ODR verification engine (issue #8765).

Everything in this module must run WITHOUT the optional ``cryptography``
package: schema conformance, quorum cross-checks, chain linkage, and weakening
signals are the verifier paths that must work for an auditor who has no key
material. Signature-dependent tests live in ``test_odr_verify.py`` (which
skips as a module when ``cryptography`` is absent).

The negative corpus below pins every bypass from the #8389 round-2 quorum
review: each mutation must FAIL ``schema_conformance`` with a specific error
string. A jsonschema parity test cross-checks the hand-rolled validator
against the normative ``odr_schema.json`` when jsonschema is installed.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from aragora.gauntlet.odr_export import load_odr_schema, odr_content_digest
from aragora.gauntlet.odr_verify import (
    FAIL,
    PASS,
    SKIP,
    WARN,
    verify_odr_document,
)


def _valid_odr() -> dict[str, Any]:
    return {
        "odr_version": "0.1",
        "profile": "https://aragora.ai/specs/open-decision-receipt/v0.1",
        "receipt_id": "rcpt-0001",
        "issued_at": "2026-06-14T00:00:00Z",
        "subject": {
            "identifier": "5f1b14e4b5e113dc978d60d1f6bd21b5a478c744",
            "digest": {"status": "present", "alg": "sha-256", "value": "deadbeef"},
            "summary": "PR #8360",
        },
        "claim": {"verdict": "PASS", "statement": "merge PR #8360"},
        "reasoning": {"status": "present", "summary": "all checks green; quorum reached"},
        "quorum": {
            "status": "present",
            "method": "majority",
            "reached": True,
            "supporting_agents": ["claude", "grok"],
            "participants": [
                {"agent": "claude", "model_family": "anthropic", "model_id": "claude-opus-4-8"},
                {"agent": "grok", "model_family": "xai", "model_id": "grok-4"},
            ],
            "independence": {
                "disclosed": True,
                "distinct_model_families": 2,
                "model_families": ["anthropic", "xai"],
            },
            "dissent": {"present": False, "dissenting_agents": [], "views": []},
        },
        "confidence": {
            "status": "present",
            "value": 0.9,
            "scale": "unit_interval",
            "calibration": {"status": "absent", "reason": "no calibration record"},
        },
        "cruxes": {"status": "absent", "reason": "no crux set supplied"},
        "attestation": {"disposition": "autonomous"},
        "routing": {"status": "reserved"},
        "signatures": [],
    }


def _check(result: Any, name: str) -> Any:
    check = next((c for c in result.checks if c.name == name), None)
    assert check is not None, f"check {name!r} not found in {[c.name for c in result.checks]}"
    return check


# ---------------------------------------------------------------------------
# Tests moved verbatim from test_odr_verify.py (P3 split, #8765): these are
# crypto-free and must not be guarded by importorskip("cryptography").
# ---------------------------------------------------------------------------


def test_valid_unsigned_receipt_passes_structurally() -> None:
    result = verify_odr_document(_valid_odr())
    assert result.ok is True
    assert _check(result, "schema_conformance").status == PASS
    assert _check(result, "signature").status == WARN


def test_digest_matches_emitter() -> None:
    doc = _valid_odr()
    assert verify_odr_document(doc).odr_digest == odr_content_digest(doc)


def test_missing_member_fails_schema() -> None:
    doc = _valid_odr()
    del doc["claim"]
    result = verify_odr_document(doc)
    assert result.ok is False
    assert _check(result, "schema_conformance").status == FAIL


def test_routing_must_be_reserved() -> None:
    doc = _valid_odr()
    doc["routing"] = {"status": "active"}
    assert verify_odr_document(doc).ok is False


def test_quorum_inconsistency_fails() -> None:
    doc = _valid_odr()
    doc["quorum"]["supporting_agents"].append("ghost")
    result = verify_odr_document(doc)
    assert result.ok is False
    assert _check(result, "quorum_consistency").status == FAIL
    assert "ghost" in _check(result, "quorum_consistency").detail


@pytest.mark.parametrize("field", ["participants", "supporting_agents"])
def test_quorum_present_but_null_list_subfield_fails_not_crash(field: str) -> None:
    # A present-but-null list subfield (e.g. ``participants: null``) is a
    # malformed/tamper signal: ``dict.get(key, [])`` returns None on a present
    # null, so the engine must turn it into a FAIL verdict, not raise TypeError
    # downstream. Regression for the #8389 review finding.
    doc = _valid_odr()
    doc["quorum"][field] = None
    result = verify_odr_document(doc)  # must not raise
    assert result.ok is False


def test_quorum_null_dissenting_agents_fails_not_crash() -> None:
    doc = _valid_odr()
    doc["quorum"]["dissent"] = {"status": "present", "dissenting_agents": None}
    result = verify_odr_document(doc)  # must not raise
    assert result.ok is False


def test_malformed_subfields_produce_verdict_not_crash() -> None:
    # Boundary contract: structurally-valid-but-malformed receipts must produce a
    # verdict, never raise. Each mutation crashed a different check before the
    # pipeline guard (review-finding class: malformed input -> FAIL, not crash).
    mutations = [
        lambda d: d["quorum"].__setitem__("participants", None),
        lambda d: d["quorum"].__setitem__("supporting_agents", None),
        lambda d: d.__setitem__(
            "independence", {"status": "present", "distinct_model_families": object()}
        ),
    ]
    for mutate in mutations:
        doc = _valid_odr()
        mutate(doc)
        result = verify_odr_document(doc)  # must not raise
        assert isinstance(result.ok, bool)


def test_chain_non_dict_entry_does_not_crash() -> None:
    doc = _valid_odr()
    digest = odr_content_digest(doc)
    chain: list[Any] = ["not-a-dict", {"hash": "h1", "odr_digest": digest}]
    result = verify_odr_document(doc, chain=chain)  # must not raise
    assert result.ok is False


def test_chain_anchored_passes_and_broken_fails() -> None:
    doc = _valid_odr()
    digest = odr_content_digest(doc)
    good = [{"hash": "h0"}, {"hash": "h1", "prev_hash": "h0", "odr_digest": digest}]
    assert _check(verify_odr_document(doc, chain=good), "chain_link").status == PASS
    bad = [{"hash": "h0"}, {"hash": "h1", "prev_hash": "WRONG", "odr_digest": digest}]
    assert verify_odr_document(doc, chain=bad).ok is False


def test_chain_unanchored_fails() -> None:
    chain = [{"hash": "h0"}, {"hash": "h1", "prev_hash": "h0"}]
    assert verify_odr_document(_valid_odr(), chain=chain).ok is False


def test_weakening_signals_do_not_fail() -> None:
    result = verify_odr_document(_valid_odr())
    joined = " ".join(result.warnings)
    assert "autonomous" in joined
    assert "uncalibrated" in joined
    assert result.ok is True


def test_non_numeric_model_families_warns_not_fails() -> None:
    # Weakening signals warn, never fail (spec §8): a non-numeric
    # distinct_model_families degrades to a warning instead of a FAIL check.
    doc = _valid_odr()
    doc["quorum"]["independence"]["distinct_model_families"] = "n/a"
    result = verify_odr_document(doc)
    assert result.ok is True
    assert not any(c.name == "weakening_signals" and c.status == FAIL for c in result.checks)
    assert any("not numeric" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# New negative corpus (#8765 P1): every bypass listed in the round-2 review
# must FAIL schema conformance with a specific error string.
# ---------------------------------------------------------------------------

Mutation = Callable[[dict[str, Any]], Any]

_SCHEMA_VIOLATIONS: list[Any] = [
    # [P1 bypass] missing claim.statement
    pytest.param(
        lambda d: d["claim"].pop("statement"),
        "claim.statement: required (non-empty string or absent marker)",
        id="claim_statement_missing",
    ),
    pytest.param(
        lambda d: d["claim"].__setitem__("statement", 42),
        "claim.statement: must be a non-empty string or an absent marker",
        id="claim_statement_wrong_type",
    ),
    pytest.param(
        lambda d: d["claim"].__setitem__("statement", ""),
        "claim.statement: must be a non-empty string or an absent marker",
        id="claim_statement_empty",
    ),
    # [P1 bypass] malformed subject.digest
    pytest.param(
        lambda d: d["subject"]["digest"].pop("value"),
        "subject.digest.value: required non-empty string when present",
        id="subject_digest_missing_value",
    ),
    pytest.param(
        lambda d: d["subject"].__setitem__("digest", "sha-256:deadbeef"),
        "subject.digest: must be a present block or an absent marker",
        id="subject_digest_not_a_block",
    ),
    pytest.param(
        lambda d: d["subject"]["digest"].__setitem__("hex", "deadbeef"),
        "subject.digest.hex: unknown member (additionalProperties: false)",
        id="subject_digest_unknown_member",
    ),
    # [P1 bypass] non-boolean quorum.reached
    pytest.param(
        lambda d: d["quorum"].__setitem__("reached", "yes"),
        "quorum.reached: must be a boolean",
        id="quorum_reached_string",
    ),
    pytest.param(
        lambda d: d["quorum"].__setitem__("reached", 1),
        "quorum.reached: must be a boolean",
        id="quorum_reached_int",
    ),
    # [P1 bypass] missing participants[].model_id
    pytest.param(
        lambda d: d["quorum"]["participants"][0].pop("model_id"),
        "quorum.participants[0].model_id: required string",
        id="participant_missing_model_id",
    ),
    pytest.param(
        lambda d: d["quorum"]["participants"][0].__setitem__("provider", "anthropic"),
        "quorum.participants[0].provider: unknown member (additionalProperties: false)",
        id="participant_unknown_member",
    ),
    pytest.param(
        lambda d: d["quorum"]["participants"][0].__setitem__("agent", ""),
        "quorum.participants[0].agent: required non-empty string",
        id="participant_empty_agent",
    ),
    # [P1 bypass] bad independence shape
    pytest.param(
        lambda d: d["quorum"].__setitem__("independence", "high"),
        "quorum.independence: must be an object",
        id="independence_not_object",
    ),
    pytest.param(
        lambda d: d["quorum"].__setitem__("independence", {}),
        "quorum.independence.disclosed: required",
        id="independence_missing_members",
    ),
    pytest.param(
        lambda d: d["quorum"]["independence"].__setitem__("disclosed", "yes"),
        "quorum.independence.disclosed: must be a boolean",
        id="independence_disclosed_not_bool",
    ),
    pytest.param(
        lambda d: d["quorum"]["independence"].__setitem__("model_families", [1, 2]),
        "quorum.independence.model_families: must be an array of strings",
        id="independence_model_families_not_strings",
    ),
    pytest.param(
        lambda d: d["quorum"]["independence"].__setitem__("vendor", "x"),
        "quorum.independence.vendor: unknown member (additionalProperties: false)",
        id="independence_unknown_member",
    ),
    # [P1 bypass] unknown/extra top-level fields (additionalProperties: false)
    pytest.param(
        lambda d: d.__setitem__("extra", 1),
        "unknown top-level member: extra (additionalProperties: false)",
        id="unknown_top_level_member",
    ),
    # [P1 bypass] non-string signatures[].signed_at
    pytest.param(
        lambda d: d.__setitem__(
            "signatures",
            [{"alg": "Ed25519", "key_id": "k1", "signature": "c2ln", "signed_at": 12345}],
        ),
        "signatures[0].signed_at: must be a string",
        id="signature_signed_at_not_string",
    ),
    pytest.param(
        lambda d: d.__setitem__(
            "signatures", [{"alg": "Ed25519", "key_id": "k1", "signature": "c2ln", "note": "x"}]
        ),
        "signatures[0].note: unknown member (additionalProperties: false)",
        id="signature_unknown_member",
    ),
    pytest.param(
        lambda d: d.__setitem__(
            "signatures", [{"alg": "RSA", "key_id": "k1", "signature": "c2ln"}]
        ),
        "signatures[0].alg: only 'Ed25519' is defined in v0.1",
        id="signature_alg_not_ed25519",
    ),
    # Remaining schema surface: quorum block
    pytest.param(
        lambda d: d["quorum"].__setitem__("method", 1),
        "quorum.method: must be a string",
        id="quorum_method_not_string",
    ),
    pytest.param(
        lambda d: d["quorum"].__setitem__("supporting_agents", ["claude", 7]),
        "quorum.supporting_agents: must be an array of strings",
        id="supporting_agents_non_string_item",
    ),
    pytest.param(
        lambda d: d["quorum"].__setitem__("tally", 3),
        "quorum.tally: unknown member (additionalProperties: false)",
        id="quorum_unknown_member",
    ),
    pytest.param(
        lambda d: d["quorum"]["dissent"].__setitem__("present", "no"),
        "quorum.dissent.present: must be a boolean",
        id="dissent_present_not_bool",
    ),
    pytest.param(
        lambda d: d["quorum"]["dissent"].pop("views"),
        "quorum.dissent.views: required",
        id="dissent_missing_views",
    ),
    # confidence / calibration
    pytest.param(
        lambda d: d["confidence"].pop("calibration"),
        "confidence.calibration: required when present",
        id="confidence_missing_calibration",
    ),
    pytest.param(
        lambda d: d["confidence"].__setitem__("calibration", {"status": "present"}),
        "confidence.calibration.provenance_ref: required object when present",
        id="calibration_present_without_provenance_ref",
    ),
    pytest.param(
        lambda d: d["confidence"].__setitem__("basis", "vibes"),
        "confidence.basis: unknown member (additionalProperties: false)",
        id="confidence_unknown_member",
    ),
    # cruxes / absent markers
    pytest.param(
        lambda d: d.__setitem__("cruxes", {"status": "present", "items": []}),
        "cruxes.items: required non-empty array of objects when present",
        id="cruxes_empty_items",
    ),
    pytest.param(
        lambda d: d.__setitem__("cruxes", {"status": "absent", "reason": "x", "note": "y"}),
        "cruxes: must be a present block or an absent marker",
        id="absent_marker_with_unknown_member",
    ),
    pytest.param(
        lambda d: d.__setitem__("reasoning", {"status": "absent", "reason": ""}),
        "reasoning: must be a present block or an absent marker",
        id="absent_marker_empty_reason",
    ),
    pytest.param(
        lambda d: d["reasoning"].__setitem__("detail", "x"),
        "reasoning.detail: unknown member (additionalProperties: false)",
        id="reasoning_unknown_member",
    ),
    # attestation
    pytest.param(
        lambda d: d["attestation"].__setitem__("witness", "x"),
        "attestation.witness: unknown member (additionalProperties: false)",
        id="attestation_unknown_member",
    ),
    pytest.param(
        lambda d: d["attestation"].__setitem__("disposition", "robot"),
        "attestation.disposition: must be 'human_attested' or 'autonomous'",
        id="attestation_bad_disposition",
    ),
    pytest.param(
        lambda d: d.__setitem__("attestation", {"disposition": "human_attested"}),
        "attestation.attestor: required object when disposition is human_attested",
        id="attestation_human_without_attestor",
    ),
    # routing / source / scalars
    pytest.param(
        lambda d: d["routing"].__setitem__("channel", "slack"),
        "routing.channel: unknown member (additionalProperties: false)",
        id="routing_unknown_member",
    ),
    pytest.param(
        lambda d: d.__setitem__("source", {"system": "aragora"}),
        "source.schema: required",
        id="source_missing_required",
    ),
    pytest.param(
        lambda d: d.__setitem__(
            "source", {"system": "a", "schema": "b", "receipt_id": "c", "extra": 1}
        ),
        "source.extra: unknown member (additionalProperties: false)",
        id="source_unknown_member",
    ),
    pytest.param(
        lambda d: d.__setitem__("issued_at", 123),
        "issued_at: must be a string or null",
        id="issued_at_not_string",
    ),
    pytest.param(
        lambda d: d.__setitem__("odr_version", "0.3"),
        "odr_version: must be '0.1' or '0.2'",
        id="odr_version_wrong_const",
    ),
    pytest.param(
        lambda d: d.__setitem__("receipt_id", ""),
        "receipt_id: required non-empty string",
        id="receipt_id_empty",
    ),
]


@pytest.mark.parametrize(("mutate", "expected"), _SCHEMA_VIOLATIONS)
def test_schema_bypass_rejected(mutate: Mutation, expected: str) -> None:
    doc = _valid_odr()
    mutate(doc)
    result = verify_odr_document(doc)  # must not raise (fail-closed, crash-free)
    assert result.ok is False
    check = _check(result, "schema_conformance")
    assert check.status == FAIL
    assert expected in check.detail


# ---------------------------------------------------------------------------
# Positive variants: strictness must not over-reject schema-valid receipts.
# ---------------------------------------------------------------------------

_VALID_VARIANTS: list[Any] = [
    pytest.param(lambda d: None, id="baseline"),
    pytest.param(
        lambda d: d.__setitem__(
            "source", {"system": "aragora", "schema": "DecisionReceipt", "receipt_id": "gr-1"}
        ),
        id="with_source_block",
    ),
    pytest.param(
        lambda d: d["subject"].__setitem__(
            "digest", {"status": "absent", "reason": "source receipt has no input_hash"}
        ),
        id="digest_absent_marker",
    ),
    pytest.param(
        lambda d: d["claim"].__setitem__(
            "statement", {"status": "absent", "reason": "source receipt has no input_summary"}
        ),
        id="statement_absent_marker",
    ),
    pytest.param(
        lambda d: d.__setitem__(
            "attestation",
            {
                "disposition": "human_attested",
                "attestor": {"id": "armand", "role": "founder", "org": "synaptent"},
                "attested_at": "2026-06-14T00:00:02Z",
            },
        ),
        id="human_attested_with_extended_attestor",
    ),
    pytest.param(
        lambda d: d["confidence"].__setitem__(
            "calibration",
            {
                "status": "present",
                "provenance_ref": {"type": "calibration_report", "agent": "claude"},
            },
        ),
        id="calibration_present_with_provenance",
    ),
    pytest.param(
        lambda d: d.__setitem__("cruxes", {"status": "present", "items": [{"claim": "x"}]}),
        id="cruxes_present_with_items",
    ),
    pytest.param(
        lambda d: d.__setitem__(
            "signatures",
            [
                {
                    "alg": "Ed25519",
                    "key_id": "ed25519-0011223344556677",
                    "signature": "c2lnbmF0dXJl",
                    "signed_at": "2026-06-14T00:00:01Z",
                }
            ],
        ),
        id="signature_entry_with_signed_at",
    ),
    pytest.param(
        lambda d: d["quorum"]["independence"].__setitem__("note", "providers disclosed"),
        id="independence_with_note",
    ),
    pytest.param(lambda d: d.__setitem__("issued_at", None), id="issued_at_null"),
]


@pytest.mark.parametrize("mutate", _VALID_VARIANTS)
def test_schema_valid_variant_passes(mutate: Mutation) -> None:
    doc = _valid_odr()
    mutate(doc)
    result = verify_odr_document(doc)
    assert _check(result, "schema_conformance").status == PASS
    assert result.ok is True


# ---------------------------------------------------------------------------
# Parity with the normative schema: the hand-rolled validator must agree with
# a real JSON Schema validator on the whole corpus above (jsonschema is a
# test-only dependency, so this cross-check skips when it is unavailable).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def jsonschema_validator() -> Any:
    jsonschema = pytest.importorskip("jsonschema")
    return jsonschema.Draft202012Validator(load_odr_schema())


@pytest.mark.parametrize(("mutate", "expected"), _SCHEMA_VIOLATIONS)
def test_negative_corpus_agrees_with_jsonschema(
    jsonschema_validator: Any, mutate: Mutation, expected: str
) -> None:
    doc = _valid_odr()
    mutate(doc)
    assert not jsonschema_validator.is_valid(copy.deepcopy(doc))


@pytest.mark.parametrize("mutate", _VALID_VARIANTS)
def test_valid_variants_agree_with_jsonschema(jsonschema_validator: Any, mutate: Mutation) -> None:
    doc = _valid_odr()
    mutate(doc)
    assert jsonschema_validator.is_valid(copy.deepcopy(doc))


# ---------------------------------------------------------------------------
# New unsigned example-state fixtures (m2-odr-unsigned-state-fixtures):
# approved-clean, blocked/FAIL, and abstained/inconclusive. These exercise the
# committed docs/specs/examples/ files (not synthetic dicts) so the schema-
# validation + verifier-behavior contract is pinned against the actual
# shipped fixtures an external auditor would download.
# ---------------------------------------------------------------------------

_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "docs" / "specs" / "examples"

_NEW_FIXTURES = [
    "example-approved-clean.odr.json",
    "example-blocked.odr.json",
    "example-abstained.odr.json",
]


def _load_example(filename: str) -> dict[str, Any]:
    return json.loads((_EXAMPLES_DIR / filename).read_text(encoding="utf-8"))


def _tamper_odr_version(raw_text: str) -> str:
    """Flip a single byte of the fixed ``odr_version`` literal; stays valid JSON."""
    marker = '"odr_version": "0.1"'
    assert marker in raw_text, "fixture does not carry the expected odr_version literal"
    return raw_text.replace(marker, '"odr_version": "0.2"', 1)


@pytest.mark.parametrize("filename", _NEW_FIXTURES)
def test_new_unsigned_fixture_verifies_ok_with_unsigned_warning(filename: str) -> None:
    doc = _load_example(filename)
    result = verify_odr_document(doc)
    assert result.ok is True, [c for c in result.checks if c.status == FAIL]
    assert _check(result, "schema_conformance").status == PASS
    assert _check(result, "canonical_digest").status == PASS
    signature_check = _check(result, "signature")
    assert signature_check.status == WARN
    assert "unsigned" in signature_check.detail


@pytest.mark.parametrize("filename", _NEW_FIXTURES)
def test_new_unsigned_fixture_single_byte_tamper_fails(filename: str) -> None:
    raw_text = (_EXAMPLES_DIR / filename).read_text(encoding="utf-8")
    tampered = json.loads(_tamper_odr_version(raw_text))
    result = verify_odr_document(tampered)
    assert result.ok is False
    check = _check(result, "schema_conformance")
    assert check.status == FAIL
    assert "odr_version" in check.detail


@pytest.mark.parametrize("filename", _NEW_FIXTURES)
def test_new_fixture_agrees_with_jsonschema(jsonschema_validator: Any, filename: str) -> None:
    doc = _load_example(filename)
    assert jsonschema_validator.is_valid(doc)


def test_approved_clean_fixture_has_no_weakening_signals() -> None:
    # The "clean" state fixture is deliberately human-attested, disclosed,
    # calibrated, and unanimous -- it should carry zero weakening warnings,
    # contrasting with the intentionally weaker blocked/abstained fixtures.
    doc = _load_example("example-approved-clean.odr.json")
    result = verify_odr_document(doc)
    assert result.ok is True
    assert result.warnings == []


def test_blocked_fixture_surfaces_weakening_signals() -> None:
    doc = _load_example("example-blocked.odr.json")
    result = verify_odr_document(doc)
    assert result.ok is True
    joined = " ".join(result.warnings)
    assert "attestation: autonomous" in joined
    assert "undisclosed" in joined
    assert "uncalibrated" in joined


def test_abstained_fixture_surfaces_weakening_signals() -> None:
    doc = _load_example("example-abstained.odr.json")
    result = verify_odr_document(doc)
    assert result.ok is True
    # No present quorum block to cross-check -- SKIP, never FAIL.
    assert _check(result, "quorum_consistency").status == SKIP
    joined = " ".join(result.warnings)
    assert "attestation: autonomous" in joined
    assert "quorum: absent" in joined
    assert "reasoning: absent" in joined


def test_quorum_consistency_tamper_on_blocked_fixture_fails() -> None:
    # Semantically distinct from a digest/schema tamper (spec §8): an agent
    # referenced in dissent but never disclosed as a participant must FAIL
    # quorum_consistency specifically, even though the receipt is unsigned
    # and every other check (schema, digest) still passes on the mutated doc.
    doc = _load_example("example-blocked.odr.json")
    doc["quorum"]["dissent"]["dissenting_agents"] = ["ghost-agent"]
    doc["quorum"]["dissent"]["present"] = True
    result = verify_odr_document(doc)
    assert result.ok is False
    assert _check(result, "schema_conformance").status == PASS
    check = _check(result, "quorum_consistency")
    assert check.status == FAIL
    assert "ghost-agent" in check.detail
