"""Compatibility coverage for the P4a storage layering moves."""

from __future__ import annotations

import importlib
import sys
import warnings

import pytest

MOVES = [
    ("aragora.server.redis_cluster", "aragora.storage.redis_cluster"),
    ("aragora.gauntlet.signing", "aragora.storage.receipt_signing"),
    ("aragora.storage.provenance_store", "aragora.reasoning.provenance_store"),
    ("aragora.storage.adapters", "aragora.export.storage_adapter"),
]


@pytest.fixture(autouse=True)
def _restore_moved_modules():
    module_names = {name for move in MOVES for name in move}
    saved = {name: sys.modules.get(name) for name in module_names}
    yield
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


@pytest.mark.parametrize(("old_path", "new_path"), MOVES)
def test_canonical_import_does_not_warn(old_path: str, new_path: str) -> None:
    sys.modules.pop(old_path, None)
    sys.modules.pop(new_path, None)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.import_module(new_path)

    assert not [warning for warning in caught if warning.category is DeprecationWarning]


@pytest.mark.parametrize(("old_path", "new_path"), MOVES)
def test_legacy_import_warns_and_aliases_module(old_path: str, new_path: str) -> None:
    canonical = importlib.import_module(new_path)
    sys.modules.pop(old_path, None)

    with pytest.warns(DeprecationWarning, match=old_path):
        legacy = importlib.import_module(old_path)

    assert legacy is canonical


def test_redis_legacy_path_shares_singleton_state() -> None:
    canonical = importlib.import_module("aragora.storage.redis_cluster")
    sys.modules.pop("aragora.server.redis_cluster", None)
    with pytest.warns(DeprecationWarning, match="aragora.server.redis_cluster"):
        legacy = importlib.import_module("aragora.server.redis_cluster")

    marker = object()
    previous = canonical._cluster_client
    try:
        legacy._cluster_client = marker
        assert canonical._cluster_client is marker
    finally:
        canonical._cluster_client = previous


def test_signing_legacy_path_shares_singleton_state() -> None:
    canonical = importlib.import_module("aragora.storage.receipt_signing")
    sys.modules.pop("aragora.gauntlet.signing", None)
    with pytest.warns(DeprecationWarning, match="aragora.gauntlet.signing"):
        legacy = importlib.import_module("aragora.gauntlet.signing")

    marker = object()
    previous = canonical._default_signer
    try:
        legacy._default_signer = marker
        assert canonical._default_signer is marker
    finally:
        canonical._default_signer = previous
