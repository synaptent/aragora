"""The debate engine builds receipts from the foundation models, not the gauntlet facades.

``aragora.debate`` imports ``aragora.models.receipts.gauntlet``, signs through
``aragora.storage.receipt_signing`` and tracks receipt state in
``aragora.storage.receipt_lifecycle_store``. ``aragora.debate.receipt_operations``
registers the receipt operations it needs, so it works with no facade imported.
"""

from __future__ import annotations

import importlib

import pytest

from aragora.core_types import DebateResult
from aragora.debate import execution_safety
from aragora.debate.receipt_operations import register_debate_receipt_operations
from aragora.models.receipts import gauntlet as receipts
from aragora.models.receipts import operations
from aragora.storage import receipt_lifecycle_store

SIGNING_KEY = "a" * 64


@pytest.fixture
def no_adapters(monkeypatch):
    """No receipt operation adapter is registered, as before any facade import."""
    monkeypatch.setattr(operations, "_adapters", {})


def _result() -> DebateResult:
    return DebateResult(
        debate_id="d-1",
        task="t",
        final_answer="a",
        confidence=0.9,
        consensus_reached=True,
        rounds_used=1,
        participants=["a1"],
        metadata={},
    )


def test_execution_safety_reads_the_foundation_receipt_type():
    assert execution_safety.DecisionReceipt is receipts.DecisionReceipt


def test_registration_fills_the_operations_debate_receipts_use(no_adapters):
    register_debate_receipt_operations()
    register_debate_receipt_operations()
    assert operations.registered_operations() == {
        "signing",
        "provider_detection",
        "failure_classification",
    }
    signing = importlib.import_module("aragora.storage.receipt_signing")
    assert operations.signing_backend().SignedReceipt is signing.SignedReceipt


def test_a_signing_adapter_registered_first_is_kept(no_adapters):
    adapter = object()
    operations.register_signing(adapter)
    register_debate_receipt_operations()
    assert operations.signing_backend() is adapter


def test_without_facade_adapters_execution_safety_signs_and_verifies(no_adapters, monkeypatch):
    monkeypatch.setenv("ARAGORA_RECEIPT_SIGNING_KEY", SIGNING_KEY)
    signing = importlib.import_module("aragora.storage.receipt_signing")
    monkeypatch.setattr(signing, "_default_signer", None)
    receipt, signed, integrity_valid, signature_valid = execution_safety._build_signed_receipt(
        _result()
    )
    assert receipt is not None and receipt.signature
    assert (signed, integrity_valid, signature_valid) == (True, True, True)


def test_a_persisted_receipt_is_read_back_from_the_lifecycle_store(monkeypatch):
    monkeypatch.setattr(receipt_lifecycle_store, "_receipt_store_singleton", None)
    store = receipt_lifecycle_store.get_receipt_store()
    store.persist("r-1", {"receipt_id": "r-1", "verdict": "PASS", "confidence": 0.9})
    receipt, signed, _, signature_valid = execution_safety._retrieve_persisted_receipt("r-1")
    assert isinstance(receipt, receipts.DecisionReceipt)
    assert (receipt.receipt_id, receipt.verdict, signed, signature_valid) == (
        "r-1",
        "PASS",
        False,
        False,
    )
