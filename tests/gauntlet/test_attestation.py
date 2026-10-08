"""Human-oversight attestation blocks (ODR-6 / #8230).

Acceptance: ODR receipts for human-settled decisions carry the attestation
block (who/what/when/mechanism); autonomous receipts carry the explicit
``autonomous`` disposition; self-attestation (oversight identity ==
execution identity) is refused fail-closed.
"""

from __future__ import annotations

import pytest

from aragora.gauntlet.attestation import (
    HUMAN_SETTLEMENT_CONTEXT,
    OversightAttestation,
    attestation_from_preapproval_comment,
    attestation_from_settlement_status,
    build_oversight_attestation,
)
from aragora.gauntlet.odr_export import decision_receipt_to_odr
from aragora.gauntlet.receipt_models import DecisionReceipt

RECEIPT_SHA = "a" * 64
HEAD_SHA = "b" * 40


def _receipt() -> DecisionReceipt:
    return DecisionReceipt(
        receipt_id="r-att-1",
        gauntlet_id="g-att-1",
        timestamp="2026-07-17T12:00:00+00:00",
        input_summary="Should we merge PR #9999?",
        input_hash="c" * 64,
        risk_summary={"total": 0},
        attacks_attempted=0,
        attacks_successful=0,
        probes_run=1,
        vulnerabilities_found=0,
        verdict="PASS",
        confidence=0.9,
        robustness_score=0.8,
    )


class TestBuilder:
    def test_full_block_shape(self) -> None:
        att = build_oversight_attestation(
            attestor_id="scarmani",
            attested_at="2026-07-17T12:34:56+00:00",
            mechanism_type="settlement_status",
            mechanism_context=HUMAN_SETTLEMENT_CONTEXT,
            mechanism_ref="https://api.github.com/repos/o/r/statuses/abc",
            head_sha=HEAD_SHA,
            evidence_digest=f"sha256:{RECEIPT_SHA}",
            execution_identity_id="an0mium",
        )
        block = att.to_dict()
        assert block["disposition"] == "human_attested"
        assert block["attestor"] == {"id": "scarmani", "role": "oversight"}
        assert block["execution_identity"] == {"id": "an0mium"}
        assert block["attested_at"] == "2026-07-17T12:34:56+00:00"
        assert block["observed"]["head_sha"] == HEAD_SHA
        assert block["observed"]["evidence_digest"] == f"sha256:{RECEIPT_SHA}"
        assert block["mechanism"]["type"] == "settlement_status"
        assert block["mechanism"]["context"] == HUMAN_SETTLEMENT_CONTEXT

    def test_self_attestation_refused(self) -> None:
        """Oversight identity == execution identity must fail closed (TET H2)."""
        with pytest.raises(ValueError, match="must differ"):
            build_oversight_attestation(
                attestor_id="an0mium",
                attested_at="2026-07-17T12:00:00+00:00",
                mechanism_type="settlement_status",
                execution_identity_id="an0mium",
            )

    def test_self_attestation_refused_case_insensitive(self) -> None:
        with pytest.raises(ValueError, match="must differ"):
            build_oversight_attestation(
                attestor_id="Scarmani",
                attested_at="2026-07-17T12:00:00+00:00",
                mechanism_type="manual",
                execution_identity_id="scarmani",
            )

    def test_missing_attestor_refused(self) -> None:
        with pytest.raises(ValueError, match="attestor_id"):
            OversightAttestation(
                attestor_id="  ",
                attested_at="2026-07-17T12:00:00+00:00",
                mechanism_type="manual",
            )

    def test_missing_timestamp_refused(self) -> None:
        with pytest.raises(ValueError, match="attested_at"):
            OversightAttestation(attestor_id="scarmani", attested_at="", mechanism_type="manual")

    def test_unknown_mechanism_refused(self) -> None:
        with pytest.raises(ValueError, match="mechanism_type"):
            OversightAttestation(
                attestor_id="scarmani",
                attested_at="2026-07-17T12:00:00+00:00",
                mechanism_type="vibes",
            )


class TestFromSettlementStatus:
    def _status(self) -> dict:
        return {
            "creator": {"login": "scarmani"},
            "created_at": "2026-07-17T13:00:00Z",
            "context": HUMAN_SETTLEMENT_CONTEXT,
            "state": "success",
            "description": f"Settlement receipt {RECEIPT_SHA} recorded for PR #9999",
            "url": "https://api.github.com/repos/o/r/statuses/xyz",
        }

    def test_maps_status_fields(self) -> None:
        att = attestation_from_settlement_status(
            self._status(), head_sha=HEAD_SHA, execution_identity_id="an0mium"
        )
        block = att.to_dict()
        assert block["attestor"]["id"] == "scarmani"
        assert block["attested_at"] == "2026-07-17T13:00:00Z"
        assert block["observed"]["head_sha"] == HEAD_SHA
        assert block["observed"]["evidence_digest"] == f"sha256:{RECEIPT_SHA}"
        assert block["mechanism"]["context"] == HUMAN_SETTLEMENT_CONTEXT
        assert block["mechanism"]["ref"].endswith("/statuses/xyz")

    def test_status_by_execution_identity_refused(self) -> None:
        """The #8169 precedent gap: a settlement status created by the
        executing identity is not human oversight."""
        status = self._status()
        status["creator"] = {"login": "an0mium"}
        with pytest.raises(ValueError, match="must differ"):
            attestation_from_settlement_status(
                status, head_sha=HEAD_SHA, execution_identity_id="an0mium"
            )

    def test_non_settlement_context_refused(self) -> None:
        """Public-API hardening (round-7 finding): an arbitrary CI status can
        never be converted into countable oversight evidence."""
        status = self._status()
        status["context"] = "ci/build"
        with pytest.raises(ValueError, match="settlement context"):
            attestation_from_settlement_status(status, head_sha=HEAD_SHA)

    def test_non_success_state_refused(self) -> None:
        status = self._status()
        status["state"] = "failure"
        with pytest.raises(ValueError, match="must be 'success'"):
            attestation_from_settlement_status(status, head_sha=HEAD_SHA)

    def test_description_without_digest(self) -> None:
        status = self._status()
        status["description"] = "settled"
        att = attestation_from_settlement_status(status, head_sha=HEAD_SHA)
        assert "evidence_digest" not in att.to_dict().get("observed", {})


class TestFromPreapprovalComment:
    def test_maps_comment_fields(self) -> None:
        att = attestation_from_preapproval_comment(
            {
                "user": {"login": "scarmani"},
                "created_at": "2026-07-17T14:00:00Z",
                "html_url": "https://github.com/o/r/pull/1#issuecomment-5",
            },
            head_sha=HEAD_SHA,
            evidence_digest=f"sha256:{RECEIPT_SHA}",
            execution_identity_id="an0mium",
        )
        block = att.to_dict()
        assert block["mechanism"]["type"] == "preapproval_comment"
        assert block["mechanism"]["ref"].endswith("#issuecomment-5")
        assert block["attestor"]["id"] == "scarmani"


class TestOdrIntegration:
    def test_human_settled_odr_carries_attestation(self) -> None:
        att = attestation_from_settlement_status(
            {
                "creator": {"login": "scarmani"},
                "created_at": "2026-07-17T13:00:00Z",
                "context": HUMAN_SETTLEMENT_CONTEXT,
                "state": "success",
                "description": f"Settlement receipt {RECEIPT_SHA} recorded for PR #9999",
                "url": "https://api.github.com/repos/o/r/statuses/xyz",
            },
            head_sha=HEAD_SHA,
            execution_identity_id="an0mium",
        )
        odr = decision_receipt_to_odr(_receipt(), attestation=att.to_dict())
        assert odr["attestation"]["disposition"] == "human_attested"
        assert odr["attestation"]["attestor"]["id"] == "scarmani"
        assert odr["attestation"]["observed"]["head_sha"] == HEAD_SHA

    def test_autonomous_disposition_is_explicit(self) -> None:
        odr = decision_receipt_to_odr(_receipt())
        assert odr["attestation"] == {"disposition": "autonomous"}

    def test_hand_rolled_verifier_accepts_attested_receipt(self) -> None:
        """The dependency-free verifier must accept the oversight members
        (openai review round 1 on #9417: schema was extended but the
        odr_verify allowlist was not)."""
        from aragora.gauntlet.odr_verify import verify_odr_document

        att = build_oversight_attestation(
            attestor_id="scarmani",
            attested_at="2026-07-17T12:34:56+00:00",
            mechanism_type="settlement_status",
            mechanism_context=HUMAN_SETTLEMENT_CONTEXT,
            head_sha=HEAD_SHA,
            evidence_digest=f"sha256:{RECEIPT_SHA}",
            execution_identity_id="an0mium",
        )
        odr = decision_receipt_to_odr(_receipt(), attestation=att.to_dict())
        result = verify_odr_document(odr)
        assert result.ok, [c for c in result.checks if c.status == "fail"]

    def test_hand_rolled_verifier_rejects_malformed_mechanism(self) -> None:
        from aragora.gauntlet.odr_verify import verify_odr_document

        odr = decision_receipt_to_odr(_receipt())
        odr["attestation"] = {
            "disposition": "human_attested",
            "attestor": {"id": "scarmani"},
            "mechanism": {"context": "missing-type"},
        }
        result = verify_odr_document(odr)
        assert not result.ok
        assert any("mechanism.type" in str(c.detail) for c in result.checks)

    def test_verifier_rejects_self_attested_odr(self) -> None:
        """Round-10 finding: a hand-crafted ODR with attestor == execution
        identity must fail verification, not just builder construction."""
        from aragora.gauntlet.odr_verify import verify_odr_document

        odr = decision_receipt_to_odr(_receipt())
        odr["attestation"] = {
            "disposition": "human_attested",
            "attestor": {"id": "an0mium"},
            "execution_identity": {"id": "An0mium"},
            "attested_at": "2026-07-17T12:00:00+00:00",
            "mechanism": {"type": "settlement_status"},
        }
        result = verify_odr_document(odr)
        assert not result.ok
        assert any("must differ" in str(c.detail) for c in result.checks)

    def test_odr_schema_validates_attested_receipt(self) -> None:
        import json
        from pathlib import Path

        import jsonschema

        schema = json.loads(Path("aragora/gauntlet/odr_schema.json").read_text(encoding="utf-8"))
        att = build_oversight_attestation(
            attestor_id="scarmani",
            attested_at="2026-07-17T12:34:56+00:00",
            mechanism_type="settlement_status",
            mechanism_context=HUMAN_SETTLEMENT_CONTEXT,
            head_sha=HEAD_SHA,
            evidence_digest=f"sha256:{RECEIPT_SHA}",
            execution_identity_id="an0mium",
        )
        odr = decision_receipt_to_odr(_receipt(), attestation=att.to_dict())
        jsonschema.validate(odr, schema)
