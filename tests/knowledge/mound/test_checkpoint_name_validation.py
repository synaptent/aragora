"""Checkpoint names must stay one safe path segment inside the checkpoint directory."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aragora.knowledge.mound import checkpoint as checkpoint_module
from aragora.knowledge.mound.checkpoint import KMCheckpointStore

UNSAFE_NAMES = [
    "",
    ".",
    "..",
    "../outside",
    "a/b",
    "/etc",
    "a\\b",
    "..\\outside",
    "nul\x00byte",
    "%2e%2e",
    "..%2Foutside",
    "a%2Fb",
    "a%5Cb",
    "%00",
    "%252e%252e",
    "x" * 129,
    "trailing\n",
    "space name",
    "caf\u00e9",
]

SAFE_NAMES = ["km_ckpt_20261014_013700_0123abcd", "cp-alpha", "A", "x" * 128]


@pytest.fixture
def store_and_outside(tmp_path: Path) -> tuple[KMCheckpointStore, Path]:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "metadata.json").write_text(
        json.dumps(
            {
                "id": "outside",
                "created_at": "2026-10-14T00:00:00",
                "description": "not a checkpoint",
                "workspace_id": "ws",
            }
        )
    )
    store = KMCheckpointStore(
        mound=MagicMock(workspace_id="ws"),
        checkpoint_dir=str(tmp_path / "checkpoints"),
        max_checkpoints=0,
    )
    return store, outside


@pytest.mark.parametrize("name", SAFE_NAMES)
def test_validator_accepts_single_safe_segments(name: str) -> None:
    assert checkpoint_module.validate_checkpoint_name(name) == name


@pytest.mark.parametrize("name", UNSAFE_NAMES + [None, 5, b"cp"])
def test_validator_rejects_unsafe_names(name: object) -> None:
    with pytest.raises(checkpoint_module.InvalidCheckpointNameError):
        checkpoint_module.validate_checkpoint_name(name)


def test_invalid_name_error_is_a_value_error() -> None:
    assert issubclass(checkpoint_module.InvalidCheckpointNameError, ValueError)


async def test_store_methods_reject_traversal_before_touching_disk(store_and_outside) -> None:
    store, outside = store_and_outside
    error = checkpoint_module.InvalidCheckpointNameError
    with pytest.raises(error):
        await store.get_checkpoint_metadata("../outside")
    with pytest.raises(error):
        await store.restore_checkpoint("../outside")
    with pytest.raises(error):
        await store.compare_checkpoints("../outside", "km_ckpt_missing")
    with pytest.raises(error):
        await store.delete_checkpoint("../outside")
    assert (outside / "metadata.json").exists()


@pytest.mark.parametrize("name", UNSAFE_NAMES)
async def test_create_rejects_unsafe_names_before_writing(store_and_outside, name: str) -> None:
    store, _ = store_and_outside
    with pytest.raises(checkpoint_module.InvalidCheckpointNameError):
        await store.create_checkpoint(name=name)
    assert list(store.checkpoint_dir.iterdir()) == []


async def test_symlink_that_resolves_outside_the_directory_is_rejected(store_and_outside) -> None:
    store, outside = store_and_outside
    os.symlink(outside, store.checkpoint_dir / "km_ckpt_link")
    with pytest.raises(checkpoint_module.InvalidCheckpointNameError):
        await store.get_checkpoint_metadata("km_ckpt_link")
    with pytest.raises(checkpoint_module.InvalidCheckpointNameError):
        await store.delete_checkpoint("km_ckpt_link")
    assert await store.list_checkpoints() == []
    assert (outside / "metadata.json").exists()


async def test_metadata_outside_the_entry_is_neither_read_nor_listed(store_and_outside) -> None:
    store, outside = store_and_outside
    linked, looped = store.checkpoint_dir / "km_ckpt_linked", store.checkpoint_dir / "km_ckpt_loop"
    for entry in (linked, looped):
        entry.mkdir()
    (linked / "metadata.json").symlink_to(outside / "metadata.json")
    (looped / "metadata.json").symlink_to(looped / "metadata.json")
    assert await store.get_checkpoint_metadata("km_ckpt_linked") is None
    assert await store.list_checkpoints() == []
    assert await store.get_checkpoint_metadata("km_ckpt_loop") is None


async def test_safe_missing_names_keep_not_found_results(store_and_outside) -> None:
    store, _ = store_and_outside
    assert await store.get_checkpoint_metadata("km_ckpt_missing") is None
    assert await store.delete_checkpoint("km_ckpt_missing") is False
    result = await store.restore_checkpoint("km_ckpt_missing")
    assert result.success is False


async def test_prune_skips_tampered_metadata_ids(store_and_outside) -> None:
    store, outside = store_and_outside
    tampered = store.checkpoint_dir / "km_ckpt_tampered"
    tampered.mkdir()
    (tampered / "metadata.json").write_text(
        json.dumps(
            {
                "id": "../outside",
                "created_at": "2026-10-14T00:00:00",
                "description": "",
                "workspace_id": "ws",
            }
        )
    )
    assert await store._prune_old_checkpoints() == 0
    assert (outside / "metadata.json").exists()
