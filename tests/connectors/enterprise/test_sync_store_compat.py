"""Compatibility coverage for the sync store module move."""

from __future__ import annotations

import sys
import warnings

import pytest


def test_storage_sync_store_is_canonical_without_warning():
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        canonical = __import__("aragora.storage.sync_store", fromlist=["SyncStore"])

    assert not captured
    assert canonical.SyncStore.__module__ == "aragora.storage.sync_store"


def test_legacy_connector_sync_store_warns_and_reexports(monkeypatch):
    canonical = __import__("aragora.storage.sync_store", fromlist=["SyncStore"])
    monkeypatch.delitem(sys.modules, "aragora.connectors.enterprise.sync_store", raising=False)

    with pytest.warns(DeprecationWarning, match="aragora.storage.sync_store"):
        legacy = __import__(
            "aragora.connectors.enterprise.sync_store",
            fromlist=["SyncStore", "get_sync_store"],
        )

    assert legacy.SyncStore is canonical.SyncStore
    assert legacy.get_sync_store is canonical.get_sync_store
