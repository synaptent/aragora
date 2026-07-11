"""Tests for the Open Decision Receipt (ODR) exporter (issue #8224).

Covers:
- RFC 8785 (JCS) canonicalization: ECMAScript number serialization vectors,
  UTF-16 key sorting, byte stability across dict insertion orders.
- DecisionReceipt -> ODR mapping: losslessness for present fields, explicit
  absent markers (never fabricated values) for missing ones.
- JSON Schema (draft 2020-12) validation of emitted documents.
- CLI round trip via `aragora receipt export --format odr`.
"""

from __future__ import annotations

import argparse
import json

import pytest

from aragora.gauntlet import InputType, OrchestratorResult, Verdict
from aragora.gauntlet.odr_export import (
    ODR_PROFILE_URI,
    ODR_VERSION,
    absent,
    decision_receipt_to_odr,
    jcs_canonicalize,
    load_odr_schema,
    odr_content_digest,
)
from aragora.gauntlet.receipt_models import (
    AgentResponseRecord,
    ConsensusProof,
    DecisionReceipt,
)

# ---------------------------------------------------------------------------
# JCS canonicalization
# ---------------------------------------------------------------------------


class TestJCSNumbers:
    """ECMAScript number serialization vectors (RFC 8785 section 3.2.2.3)."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0.0, "0"),
            (-0.0, "0"),
            (1.0, "1"),
            (-1.0, "-1"),
            (0.5, "0.5"),
            (100.0, "100"),
            (4.5, "4.5"),
            (0.002, "0.002"),
            (1e21, "1e+21"),
            (1e30, "1e+30"),
            (1e-7, "1e-7"),
            (1e-27, "1e-27"),
            (0.00001, "0.00001"),
            (1e-6, "0.000001"),
            (333333333.3333333, "333333333.3333333"),
            (9.999999999999997e22, "9.999999999999997e+22"),
            (-2.5e-3, "-0.0025"),
            (5e-324, "5e-324"),
            (1.7976931348623157e308, "1.7976931348623157e+308"),
            (0.1 + 0.2, "0.30000000000000004"),
        ],
    )
    def test_es_number_vectors(self, value: float, expected: str) -> None:
        assert jcs_canonicalize(value).decode("utf-8") == expected

    def test_rfc8785_numbers_example(self) -> None:
        """The numbers array from the RFC 8785 canonicalization example."""
        data = {"numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 0.000000000000000000000000001]}
        assert (
            jcs_canonicalize(data).decode("utf-8")
            == '{"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27]}'
        )

    def test_nan_and_infinity_rejected(self) -> None:
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError):
                jcs_canonicalize(bad)

    def test_integers_pass_through(self) -> None:
        assert jcs_canonicalize(42).decode("utf-8") == "42"
        assert jcs_canonicalize(-7).decode("utf-8") == "-7"
        assert jcs_canonicalize(2**53 - 1).decode("utf-8") == str(2**53 - 1)


class TestJCSStructure:
    def test_literals(self) -> None:
        assert jcs_canonicalize({"literals": [None, True, False]}) == (
            b'{"literals":[null,true,false]}'
        )

    def test_no_whitespace_and_sorted_keys(self) -> None:
        assert jcs_canonicalize({"b": 2, "a": 1}) == b'{"a":1,"b":2}'

    def test_byte_stability_across_insertion_order(self) -> None:
        one = {"z": [1, {"y": 2.5, "x": "s"}], "a": None}
        two = {"a": None, "z": [1, {"x": "s", "y": 2.5}]}
        assert jcs_canonicalize(one) == jcs_canonicalize(two)

    def test_repeated_calls_byte_identical(self) -> None:
        doc = {"k": [True, 0.1, "v", {"n": 1e21}]}
        assert jcs_canonicalize(doc) == jcs_canonicalize(doc)

    def test_utf16_key_sorting(self) -> None:
        """Keys sort by UTF-16 code units (RFC 8785 section 3.2.3 example subset)."""
        doc = {
            "€": "Euro Sign",
            "\r": "Carriage Return",
            "1": "One",
            "\U0001f600": "Emoji: Grinning Face",
            "ö": "Latin Small Letter O With Diaeresis",
        }
        canonical = jcs_canonicalize(doc).decode("utf-8")
        # Non-BMP emoji encodes as a surrogate pair (0xD83D...) which sorts
        # AFTER the BMP Euro sign (0x20AC) but BEFORE nothing here; the key
        # order must be: \r, 1, ö, €, emoji.
        expected_order = ["\r", "1", "ö", "€", "\U0001f600"]
        positions = [canonical.index(json.dumps(k, ensure_ascii=False)) for k in expected_order]
        assert positions == sorted(positions)

    def test_string_escaping(self) -> None:
        assert jcs_canonicalize("\x0f") == b'"\\u000f"'
        assert jcs_canonicalize('quote " and backslash \\') == b'"quote \\" and backslash \\\\"'
        assert jcs_canonicalize("\n\t") == b'"\\n\\t"'

    def test_non_string_keys_rejected(self) -> None:
        with pytest.raises(TypeError):
            jcs_canonicalize({1: "a"})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _full_receipt() -> DecisionReceipt:
    return DecisionReceipt(
        receipt_id="r-123",
        gauntlet_id="g-456",
        timestamp="2026-06-11T12:00:00+00:00",
        input_summary="Should we ship feature X?",
        input_hash="a" * 64,
        risk_summary={"critical": 0, "high": 1, "medium": 0, "low": 0, "total": 1},
        attacks_attempted=3,
        attacks_successful=0,
        probes_run=2,
        vulnerabilities_found=1,
        verdict="PASS",
        confidence=0.875,
        robustness_score=0.8,
        verdict_reasoning="Consensus reached with strong agreement",
        dissenting_views=["grok-agent: latency risk understated"],
        consensus_proof=ConsensusProof(
            reached=True,
            confidence=0.875,
            supporting_agents=["claude-agent", "mistral-agent"],
            dissenting_agents=["grok-agent"],
            method="majority",
        ),
        agent_responses=[
            AgentResponseRecord(
                agent="claude-agent",
                response="I support shipping.",
                provider="anthropic",
                model="claude-opus-4",
            ),
            AgentResponseRecord(
                agent="mistral-agent",
                response="Agreed.",
                provider="mistral",
                model="mistral-large-2",
            ),
            AgentResponseRecord(agent="grok-agent", response="Latency risk."),
        ],
        settlement_metadata={"settled": True, "quality": 0.9},
        unverified=["No live load test was run against the enterprise tenant."],
        assumptions=["Support can absorb initial manual reconciliation."],
        falsification={
            "observation": "P95 latency exceeds 600ms for paid tenants.",
            "owner": "platform",
            "source": "latency dashboard",
            "check_by": "2026-07-15",
        },
    )


def _minimal_receipt() -> DecisionReceipt:
    return DecisionReceipt(
        receipt_id="r-min",
        gauntlet_id="",
        timestamp="",
        input_summary="",
        input_hash="",
        risk_summary={},
        attacks_attempted=0,
        attacks_successful=0,
        probes_run=0,
        vulnerabilities_found=0,
        verdict="",
        confidence=0.0,
        robustness_score=0.0,
    )


# ---------------------------------------------------------------------------
# Mapping: lossless where present
# ---------------------------------------------------------------------------


class TestMappingLossless:
    def test_top_level_identity(self) -> None:
        receipt = _full_receipt()
        odr = decision_receipt_to_odr(receipt)
        assert odr["odr_version"] == ODR_VERSION
        assert odr["profile"] == ODR_PROFILE_URI
        assert odr["receipt_id"] == "r-123"
        assert odr["issued_at"] == "2026-06-11T12:00:00+00:00"

    def test_subject_binding(self) -> None:
        odr = decision_receipt_to_odr(_full_receipt())
        assert odr["subject"]["identifier"] == "g-456"
        assert odr["subject"]["digest"] == {
            "status": "present",
            "alg": "sha-256",
            "value": "a" * 64,
        }
        assert odr["subject"]["summary"] == "Should we ship feature X?"

    def test_claim_and_reasoning(self) -> None:
        odr = decision_receipt_to_odr(_full_receipt())
        assert odr["claim"]["verdict"] == "PASS"
        assert odr["claim"]["statement"] == "Should we ship feature X?"
        assert odr["reasoning"] == {
            "status": "present",
            "summary": "Consensus reached with strong agreement",
        }

    def test_epistemic_blocks_export_when_present(self) -> None:
        odr = decision_receipt_to_odr(_full_receipt())
        assert odr["epistemic"] == {
            "status": "present",
            "unverified": ["No live load test was run against the enterprise tenant."],
            "assumptions": ["Support can absorb initial manual reconciliation."],
            "falsification": {
                "observation": "P95 latency exceeds 600ms for paid tenants.",
                "owner": "platform",
                "source": "latency dashboard",
                "check_by": "2026-07-15",
            },
        }

    def test_mode_result_unverified_claims_export_to_epistemic_block(self) -> None:
        result = OrchestratorResult(
            gauntlet_id="g-mode-unverified",
            input_type=InputType.ARCHITECTURE,
            input_summary="Architecture summary",
            verdict=Verdict.APPROVED_WITH_CONDITIONS,
            confidence=0.82,
            risk_score=0.4,
            robustness_score=0.7,
            coverage_score=0.6,
            unverified_claims=["Production load behavior was not verified."],
        )

        receipt = DecisionReceipt.from_mode_result(result)
        odr = decision_receipt_to_odr(receipt)

        assert receipt.unverified == ["Production load behavior was not verified."]
        assert odr["epistemic"] == {
            "status": "present",
            "unverified": ["Production load behavior was not verified."],
        }

    def test_epistemic_blocks_absent_when_empty(self) -> None:
        odr = decision_receipt_to_odr(_minimal_receipt())
        assert "epistemic" not in odr

    def test_partial_falsification_is_not_exported(self) -> None:
        receipt = _minimal_receipt()
        receipt.unverified = ["No live validation run."]
        receipt.falsification = {"observation": "Conversion drops below target."}
        receipt.__post_init__()

        odr = decision_receipt_to_odr(receipt)

        assert odr["epistemic"] == {
            "status": "present",
            "unverified": ["No live validation run."],
        }

    def test_quorum_block(self) -> None:
        odr = decision_receipt_to_odr(_full_receipt())
        quorum = odr["quorum"]
        assert quorum["status"] == "present"
        assert quorum["method"] == "majority"
        assert quorum["reached"] is True
        assert quorum["supporting_agents"] == ["claude-agent", "mistral-agent"]
        families = {p["agent"]: p["model_family"] for p in quorum["participants"]}
        assert families == {
            "claude-agent": "anthropic",
            "mistral-agent": "mistral",
            "grok-agent": "undisclosed",
        }
        assert quorum["independence"]["disclosed"] is True
        assert quorum["independence"]["distinct_model_families"] == 2
        assert quorum["independence"]["model_families"] == ["anthropic", "mistral"]
        assert quorum["dissent"]["present"] is True
        assert quorum["dissent"]["dissenting_agents"] == ["grok-agent"]
        assert quorum["dissent"]["views"] == ["grok-agent: latency risk understated"]

    def test_confidence_with_settlement_provenance(self) -> None:
        odr = decision_receipt_to_odr(_full_receipt())
        confidence = odr["confidence"]
        assert confidence["status"] == "present"
        assert confidence["value"] == 0.875
        assert confidence["scale"] == "unit_interval"
        assert confidence["calibration"]["status"] == "present"
        assert confidence["calibration"]["provenance_ref"]["type"] == (
            "aragora.settlement_metadata"
        )

    def test_source_links_native_receipt(self) -> None:
        receipt = _full_receipt()
        odr = decision_receipt_to_odr(receipt)
        assert odr["source"]["system"] == "aragora"
        assert odr["source"]["schema"] == "aragora.gauntlet.DecisionReceipt"
        assert odr["source"]["receipt_id"] == "r-123"
        assert odr["source"]["artifact_hash"] == receipt.artifact_hash

    def test_explicit_crux_set_and_attestation(self) -> None:
        odr = decision_receipt_to_odr(
            _full_receipt(),
            crux_set=[{"claim": "latency budget holds", "load_bearing": True}],
            attestation={
                "disposition": "human_attested",
                "attestor": {"id": "scarmani", "role": "operator"},
                "attested_at": "2026-06-11T13:00:00+00:00",
            },
        )
        assert odr["cruxes"]["status"] == "present"
        assert odr["cruxes"]["items"] == [{"claim": "latency budget holds", "load_bearing": True}]
        assert odr["attestation"]["disposition"] == "human_attested"
        assert odr["attestation"]["attestor"]["id"] == "scarmani"


# ---------------------------------------------------------------------------
# Mapping: honest absence (never fabricate)
# ---------------------------------------------------------------------------


class TestAbsentMarkerHonesty:
    def test_absent_helper_shape(self) -> None:
        marker = absent("why")
        assert marker == {"status": "absent", "reason": "why"}

    def test_minimal_receipt_marks_missing_fields_absent(self) -> None:
        odr = decision_receipt_to_odr(_minimal_receipt())
        assert odr["issued_at"] is None
        assert odr["subject"]["digest"]["status"] == "absent"
        assert odr["claim"]["statement"]["status"] == "absent"
        assert odr["reasoning"]["status"] == "absent"
        assert odr["quorum"]["status"] == "absent"
        assert odr["cruxes"]["status"] == "absent"
        # Confidence value exists (0.0) but calibration provenance does not.
        assert odr["confidence"]["status"] == "present"
        assert odr["confidence"]["calibration"]["status"] == "absent"

    def test_no_human_attestation_means_autonomous(self) -> None:
        odr = decision_receipt_to_odr(_minimal_receipt())
        assert odr["attestation"] == {"disposition": "autonomous"}

    def test_routing_reserved_and_signatures_empty(self) -> None:
        odr = decision_receipt_to_odr(_full_receipt())
        assert odr["routing"] == {"status": "reserved"}
        assert odr["signatures"] == []

    def test_undisclosed_model_families_not_guessed(self) -> None:
        receipt = _full_receipt()
        receipt.agent_responses = []  # No provider metadata recorded at all.
        odr = decision_receipt_to_odr(receipt)
        independence = odr["quorum"]["independence"]
        assert independence["disclosed"] is False
        assert independence["distinct_model_families"] == 0
        assert independence["model_families"] == []
        assert "note" in independence
        for participant in odr["quorum"]["participants"]:
            assert participant["model_family"] == "undisclosed"


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    @pytest.fixture()
    def validator(self):
        jsonschema = pytest.importorskip("jsonschema")
        schema = load_odr_schema()
        jsonschema.Draft202012Validator.check_schema(schema)
        return jsonschema.Draft202012Validator(schema)

    def test_full_receipt_validates(self, validator) -> None:
        errors = list(validator.iter_errors(decision_receipt_to_odr(_full_receipt())))
        assert errors == [], [e.message for e in errors]

    def test_minimal_receipt_validates(self, validator) -> None:
        errors = list(validator.iter_errors(decision_receipt_to_odr(_minimal_receipt())))
        assert errors == [], [e.message for e in errors]

    def test_crux_and_attestation_variant_validates(self, validator) -> None:
        odr = decision_receipt_to_odr(
            _full_receipt(),
            crux_set=[{"claim": "x"}],
            attestation={"disposition": "human_attested", "attestor": {"id": "op"}},
        )
        errors = list(validator.iter_errors(odr))
        assert errors == [], [e.message for e in errors]

    def test_human_attested_without_attestor_rejected(self, validator) -> None:
        odr = decision_receipt_to_odr(_full_receipt())
        odr["attestation"] = {"disposition": "human_attested"}
        assert not validator.is_valid(odr)

    def test_fabricated_extra_top_level_field_rejected(self, validator) -> None:
        odr = decision_receipt_to_odr(_full_receipt())
        odr["made_up"] = True
        assert not validator.is_valid(odr)


# ---------------------------------------------------------------------------
# Digest and round trip
# ---------------------------------------------------------------------------


class TestDigestAndRoundTrip:
    def test_content_digest_excludes_signatures(self) -> None:
        odr = decision_receipt_to_odr(_full_receipt())
        digest_before = odr_content_digest(odr)
        odr["signatures"] = [
            {"alg": "Ed25519", "key_id": "k1", "signature": "sig", "signed_at": "t"}
        ]
        assert odr_content_digest(odr) == digest_before

    def test_canonical_bytes_round_trip_json(self) -> None:
        odr = decision_receipt_to_odr(_full_receipt())
        payload = jcs_canonicalize(odr)
        reparsed = json.loads(payload.decode("utf-8"))
        assert jcs_canonicalize(reparsed) == payload

    def test_dict_round_trip_through_decision_receipt(self) -> None:
        """ODR output is stable across DecisionReceipt to_dict/from_dict."""
        receipt = _full_receipt()
        rebuilt = DecisionReceipt.from_dict(receipt.to_dict())
        original = decision_receipt_to_odr(receipt)
        again = decision_receipt_to_odr(rebuilt)
        # settlement_metadata survives, so calibration provenance must too.
        assert jcs_canonicalize(original) == jcs_canonicalize(again)


# ---------------------------------------------------------------------------
# CLI: aragora receipt export --format odr
# ---------------------------------------------------------------------------


class TestCLIExport:
    def test_export_odr_from_path(self, tmp_path, capsys) -> None:
        from aragora.cli.commands.receipt import cmd_receipt_export

        receipt_file = tmp_path / "receipt.json"
        receipt_file.write_text(json.dumps(_full_receipt().to_dict()), encoding="utf-8")

        args = argparse.Namespace(receipt=str(receipt_file), format="odr", output=None)
        cmd_receipt_export(args)
        out = capsys.readouterr().out.strip()

        parsed = json.loads(out)
        assert parsed["profile"] == ODR_PROFILE_URI
        # Output must be the JCS-canonical serialization, byte for byte.
        assert out == jcs_canonicalize(parsed).decode("utf-8")

    def test_export_odr_validates_against_schema(self, tmp_path, capsys) -> None:
        jsonschema = pytest.importorskip("jsonschema")
        from aragora.cli.commands.receipt import cmd_receipt_export

        receipt_file = tmp_path / "receipt.json"
        receipt_file.write_text(json.dumps(_full_receipt().to_dict()), encoding="utf-8")
        cmd_receipt_export(argparse.Namespace(receipt=str(receipt_file), format="odr", output=None))
        parsed = json.loads(capsys.readouterr().out.strip())
        jsonschema.Draft202012Validator(load_odr_schema()).validate(parsed)

    def test_export_odr_to_file(self, tmp_path, capsys) -> None:
        from aragora.cli.commands.receipt import cmd_receipt_export

        receipt_file = tmp_path / "receipt.json"
        receipt_file.write_text(json.dumps(_full_receipt().to_dict()), encoding="utf-8")
        out_file = tmp_path / "out.odr.json"
        cmd_receipt_export(
            argparse.Namespace(receipt=str(receipt_file), format="odr", output=str(out_file))
        )
        capsys.readouterr()
        parsed = json.loads(out_file.read_text(encoding="utf-8"))
        assert parsed["receipt_id"] == "r-123"

    def test_missing_receipt_id_errors(self, capsys) -> None:
        from aragora.cli.commands.receipt import cmd_receipt_export

        with pytest.raises(SystemExit):
            cmd_receipt_export(
                argparse.Namespace(receipt="no-such-receipt-id", format="odr", output=None)
            )


# ---------------------------------------------------------------------------
# Calibrated-confidence provenance (issue #8229, ODR-5)
# ---------------------------------------------------------------------------


def _calibration_provenance() -> dict:
    return {
        "type": "aragora.calibration_report",
        "endpoint_template": "/api/v1/agents/{agent}/calibration-report",
        "agents": [
            {
                "agent": "claude-agent",
                "sample_size": 12,
                "accuracy": 0.75,
                "brier_score": 0.18,
                "report_ref": "/api/v1/agents/claude-agent/calibration-report",
            }
        ],
    }


class TestCalibrationProvenance:
    """ODR confidence block points at the calibration-report endpoint."""

    def test_explicit_provenance_attached(self) -> None:
        odr = decision_receipt_to_odr(
            _full_receipt(), calibration_provenance=_calibration_provenance()
        )
        calibration = odr["confidence"]["calibration"]
        assert calibration["status"] == "present"
        ref = calibration["provenance_ref"]
        assert ref["type"] == "aragora.calibration_report"
        assert ref["agents"][0]["sample_size"] == 12
        assert ref["agents"][0]["report_ref"] == ("/api/v1/agents/claude-agent/calibration-report")

    def test_provenance_takes_precedence_over_settlement(self) -> None:
        """Explicit calibration provenance is more specific than settlement_metadata."""
        odr = decision_receipt_to_odr(
            _full_receipt(), calibration_provenance=_calibration_provenance()
        )
        assert (
            odr["confidence"]["calibration"]["provenance_ref"]["type"]
            == "aragora.calibration_report"
        )

    def test_omitted_provenance_keeps_existing_behavior(self) -> None:
        odr = decision_receipt_to_odr(_full_receipt())
        assert (
            odr["confidence"]["calibration"]["provenance_ref"]["type"]
            == "aragora.settlement_metadata"
        )

    def test_no_data_yields_absent_never_fabricated(self) -> None:
        odr = decision_receipt_to_odr(_minimal_receipt())
        assert odr["confidence"]["calibration"]["status"] == "absent"

    def test_provenance_variant_validates_against_schema(self) -> None:
        jsonschema = pytest.importorskip("jsonschema")
        schema = load_odr_schema()
        validator = jsonschema.Draft202012Validator(schema)
        odr = decision_receipt_to_odr(
            _full_receipt(), calibration_provenance=_calibration_provenance()
        )
        errors = list(validator.iter_errors(odr))
        assert errors == [], [e.message for e in errors]

    def test_provenance_survives_canonicalization(self) -> None:
        odr = decision_receipt_to_odr(
            _full_receipt(), calibration_provenance=_calibration_provenance()
        )
        round_tripped = json.loads(jcs_canonicalize(odr).decode("utf-8"))
        assert (
            round_tripped["confidence"]["calibration"]["provenance_ref"]["type"]
            == "aragora.calibration_report"
        )


class TestCalibrationProvenanceForReceipt:
    """Best-effort lookup helper: real data or None, never fabrication."""

    def test_participants_forwarded_to_builder(self, monkeypatch) -> None:
        import aragora.ranking.calibration_report as crmod
        from aragora.gauntlet.odr_export import calibration_provenance_for_receipt

        captured: dict = {}

        def fake_builder(agent_names, **kwargs):
            captured["agents"] = list(agent_names)
            return {"type": "aragora.calibration_report", "agents": []}

        monkeypatch.setattr(crmod, "build_odr_calibration_provenance", fake_builder)
        result = calibration_provenance_for_receipt(_full_receipt())
        assert result is not None
        assert sorted(captured["agents"]) == [
            "claude-agent",
            "grok-agent",
            "mistral-agent",
        ]

    def test_no_participants_returns_none(self) -> None:
        from aragora.gauntlet.odr_export import calibration_provenance_for_receipt

        assert calibration_provenance_for_receipt(_minimal_receipt()) is None

    def test_builder_failure_returns_none(self, monkeypatch) -> None:
        import aragora.ranking.calibration_report as crmod
        from aragora.gauntlet.odr_export import calibration_provenance_for_receipt

        def boom(agent_names, **kwargs):
            raise RuntimeError("calibration store unavailable")

        monkeypatch.setattr(crmod, "build_odr_calibration_provenance", boom)
        assert calibration_provenance_for_receipt(_full_receipt()) is None

    def test_no_calibration_data_returns_none(self, monkeypatch) -> None:
        import aragora.ranking.calibration_report as crmod
        from aragora.gauntlet.odr_export import calibration_provenance_for_receipt

        monkeypatch.setattr(crmod, "build_odr_calibration_provenance", lambda names, **kw: None)
        assert calibration_provenance_for_receipt(_full_receipt()) is None
