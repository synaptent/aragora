"""``aragora.gauntlet.receipt_store`` resolves to ``aragora.storage.receipt_lifecycle_store``."""

from __future__ import annotations

import importlib

import pytest

from aragora.storage import receipt_lifecycle_store as new

PUBLIC_NAMES = (
    "ReceiptState",
    "ReceiptStateError",
    "ReceiptStore",
    "StoredReceipt",
    "get_receipt_store",
    "reset_receipt_store",
)


@pytest.fixture
def old():
    return importlib.import_module("aragora.gauntlet.receipt_store")


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    monkeypatch.setattr(new, "_receipt_store_singleton", None)


def test_the_old_path_is_the_moved_module(old):
    assert old is new
    assert old.__name__ == "aragora.storage.receipt_lifecycle_store"


@pytest.mark.parametrize("name", PUBLIC_NAMES)
def test_each_public_name_is_the_same_object_at_both_paths(old, name):
    from aragora.gauntlet import receipt_store

    assert getattr(old, name) is getattr(new, name)
    assert getattr(receipt_store, name) is getattr(new, name)
    assert name in new.__all__


@pytest.mark.parametrize("module_name", ["old", "new"])
def test_a_receipt_moves_through_its_states_at_either_path(old, module_name):
    module = old if module_name == "old" else new
    store = module.ReceiptStore()
    stored = store.persist("r-1", {"receipt_id": "r-1"})
    assert isinstance(stored, module.StoredReceipt)
    assert store.transition("r-1", module.ReceiptState.normalize("approved")).state is (
        new.ReceiptState.APPROVED
    )
    with pytest.raises(module.ReceiptStateError):
        store.transition("r-1", module.ReceiptState.CREATED)
    assert module.StoredReceipt.from_dict(stored.to_dict()) == stored


def test_both_paths_share_one_store(old, monkeypatch):
    assert old.get_receipt_store() is new.get_receipt_store()
    old.get_receipt_store().persist("r-1", {"receipt_id": "r-1"})
    assert new.get_receipt_store().get("r-1").receipt_id == "r-1"

    replacement = new.ReceiptStore()
    monkeypatch.setattr("aragora.gauntlet.receipt_store._receipt_store_singleton", replacement)
    assert new.get_receipt_store() is replacement
    old.reset_receipt_store()
    assert new._receipt_store_singleton is None


def test_verification_signs_through_storage(old, monkeypatch):
    # The module verification imports, even if another test re-imported the package attribute.
    signing = importlib.import_module("aragora.storage.receipt_signing")
    signer = signing.ReceiptSigner(signing.HMACSigner(secret_key=b"k" * 32, key_id="k1"))
    monkeypatch.setattr(signing, "get_default_signer", lambda: signer)
    data = {"receipt_id": "r-1", "verdict": "PASS"}
    signed = signer.sign(data)
    store = old.get_receipt_store()
    store.persist(
        "r-1",
        data,
        signature=signed.signature,
        signature_key_id=signed.signature_metadata.key_id,
        signed_at=signed.signature_metadata.timestamp,
        signature_algorithm=signed.signature_metadata.algorithm,
    )
    assert new.get_receipt_store().verify_receipt("r-1")
    store.persist("r-2", data, signature="0" * 64)
    assert not store.verify_receipt("r-2")
