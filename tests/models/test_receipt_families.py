"""Receipt families in aragora.models.receipts, their facades and the operation hooks."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import aragora.receipts as receipts_facade
from aragora.gauntlet import receipt as gauntlet_receipt
from aragora.models.receipts import gauntlet, legacy, operations

GAUNTLET_NAMES = (
    "AgentResponseRecord ConsensusProof CruxReceipt DecisionReceipt ProvenanceRecord Verdict "
    "RECEIPT_SCHEMA_VERSION RECEIPT_SCHEMA_VERSION_CRUXES RECEIPT_SCHEMA_VERSION_EVIDENCE "
    "_canonical_decision_value _clamp_receipt_confidence _compute_risk_summary_from_critiques "
    "_normalize_receipt_boolean build_crux_receipt build_crux_receipt_from_proof "
    "canonicalize_execution_outcome_linkage compute_decision_payload_hash "
    "compute_receipt_artifact_hash crux_cards_from_metadata normalize_evidence_references "
    "normalize_live_explainability receipt_schema_version"
).split()
LEGACY_NAMES = (
    "DecisionReceipt DecisionReceiptGenerator ReceiptDissent ReceiptFinding ReceiptVerification "
    "SignedDecisionReceipt _load_weasyprint generate_decision_receipt link_receipt_to_trail"
).split()
SIGNING_KEY = "00" * 32


def _gauntlet_receipt() -> gauntlet.DecisionReceipt:
    return gauntlet.DecisionReceipt(
        receipt_id="r-1",
        gauntlet_id="g-1",
        timestamp="2026-10-09T12:00:00+00:00",
        input_summary="Should we ship?",
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


def _legacy_receipt() -> legacy.DecisionReceipt:
    return legacy.DecisionReceipt(
        receipt_id="lr-1",
        gauntlet_id="g-1",
        timestamp="2026-10-09T12:00:00",
        verdict="APPROVED",
        confidence=0.7,
        findings=[legacy.ReceiptFinding("f-1", "LOW", "test", "title", "description")],
    )


@pytest.mark.parametrize(
    ("old_name", "new_module", "names"),
    [
        ("aragora.gauntlet.receipt_models", gauntlet, GAUNTLET_NAMES),
        ("aragora.export.decision_receipt", legacy, LEGACY_NAMES),
    ],
)
def test_old_paths_are_the_foundation_modules(old_name, new_module, names) -> None:
    old_module = importlib.import_module(old_name)
    assert old_module is new_module
    for name in names:
        assert getattr(old_module, name) is getattr(new_module, name), name


def test_identity_matrix_across_facades() -> None:
    from aragora.export import decision_receipt
    from aragora.gauntlet import receipt_models

    assert (
        receipts_facade.DecisionReceipt
        is receipt_models.DecisionReceipt
        is gauntlet_receipt.DecisionReceipt
        is gauntlet.DecisionReceipt
    )
    assert (
        receipts_facade.LegacyDecisionReceipt
        is decision_receipt.DecisionReceipt
        is legacy.DecisionReceipt
    )
    assert receipts_facade.DecisionReceipt is not receipts_facade.LegacyDecisionReceipt
    for name in ("ProvenanceRecord", "ConsensusProof", "CruxReceipt", "AgentResponseRecord"):
        assert getattr(gauntlet, name).__module__ == "aragora.models.receipts.gauntlet"
    for name in ("DecisionReceipt", "SignedDecisionReceipt", "ReceiptFinding"):
        assert getattr(legacy, name).__module__ == "aragora.models.receipts.legacy"


def test_both_families_round_trip_through_json() -> None:
    receipt = _gauntlet_receipt()
    restored = gauntlet.DecisionReceipt.from_dict(json.loads(receipt.to_json()))
    assert restored.to_dict() == receipt.to_dict()
    assert restored.verify_integrity()

    old = _legacy_receipt()
    assert legacy.DecisionReceipt.from_dict(json.loads(old.to_json())).to_dict() == old.to_dict()


def test_facades_register_every_operation() -> None:
    assert operations.registered_operations() == {
        "signing",
        "exporters",
        "compliance",
        "provider_detection",
        "failure_classification",
    }


def test_reimporting_a_facade_replaces_its_adapter_instead_of_adding_one() -> None:
    before = operations.registered_operations()
    sys.modules.pop("aragora.export.decision_receipt")
    assert importlib.import_module("aragora.export.decision_receipt") is legacy
    assert operations.registered_operations() == before
    assert operations.signing_backend() is importlib.import_module(
        "aragora.storage.receipt_signing"
    )


def test_gauntlet_signing_round_trip_through_the_registered_signer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARAGORA_RECEIPT_SIGNING_KEY", SIGNING_KEY)
    monkeypatch.setattr("aragora.storage.receipt_signing._default_signer", None)
    receipt = _gauntlet_receipt().sign()
    assert receipt.signature and receipt.verify_signature()
    receipt.confidence = 0.1
    assert not receipt.verify_signature()


def test_legacy_signing_round_trip_through_the_export_facade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aragora.export.decision_receipt import SignedDecisionReceipt

    monkeypatch.setenv("ARAGORA_RECEIPT_SIGNING_KEY", SIGNING_KEY)
    signed = _legacy_receipt().sign()
    assert isinstance(signed, SignedDecisionReceipt)
    assert SignedDecisionReceipt.from_json(signed.to_json()).verify()


def test_exporters_and_compliance_go_through_registered_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _gauntlet_receipt()
    monkeypatch.setattr(
        "aragora.gauntlet.receipt_exporters.receipt_to_markdown",
        lambda r, **kw: f"md:{r.receipt_id}",
    )
    assert receipt.to_markdown() == "md:r-1"
    calls = []

    class FakeGenerator:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def generate(self, data, frameworks=None):
            return (data["receipt_id"], frameworks)

    monkeypatch.setattr(
        "aragora.compliance.artifact_generator.ReceiptComplianceGenerator", FakeGenerator
    )
    assert receipt.generate_compliance_artifacts(frameworks=["soc2"], org="o") == ("r-1", ["soc2"])
    assert calls == [{"org": "o"}]


def test_patch_through_the_export_path_reaches_the_pdf_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()
    monkeypatch.setattr("aragora.export.decision_receipt._load_weasyprint", lambda: sentinel)
    assert legacy._load_weasyprint() is sentinel


def test_primitive_only_import_constructs_and_unregistered_hook_raises() -> None:
    code = """
import json, sys, warnings
warnings.simplefilter("ignore")
import aragora.models.receipts.gauntlet as G, aragora.models.receipts.legacy as L
import aragora.models.receipts.operations as OP
facades = ("aragora.receipts", "aragora.gauntlet", "aragora.export")
assert not [m for m in sys.modules if m.startswith(facades)]
g = G.DecisionReceipt(receipt_id="r", gauntlet_id="g", timestamp="t", input_summary="s",
    input_hash="h", risk_summary={}, attacks_attempted=0, attacks_successful=0, probes_run=0,
    vulnerabilities_found=0, verdict="PASS", confidence=0.5, robustness_score=0.5)
assert G.DecisionReceipt.from_dict(json.loads(g.to_json())).to_dict() == g.to_dict()
l = L.DecisionReceipt(receipt_id="lr", gauntlet_id="g")
assert L.DecisionReceipt.from_dict(json.loads(l.to_json())).to_dict() == l.to_dict()
for call in (lambda: OP.sign_receipt(l), g.sign, g.to_markdown, g.generate_compliance_artifacts,
             lambda: G.DecisionReceipt._detect_provider("gpt-4")):
    try:
        call()
    except OP.ReceiptOperationNotRegisteredError as exc:
        assert "no adapter registered" in str(exc)
    else:
        raise SystemExit("hook succeeded without an adapter")
import aragora.receipts
assert OP.sign_receipt(l).signature
print("ok")
"""
    env = {**os.environ, "ARAGORA_RECEIPT_SIGNING_KEY": SIGNING_KEY}
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=env,
        cwd=Path(operations.__file__).resolve().parents[3],
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("ok")
