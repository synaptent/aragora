"""Tests for scripts/route_burndown_batches.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import route_burndown_batches as batches


def _write_inventory(path: Path, items: list[dict[str, str]]) -> None:
    path.write_text(json.dumps({"items": items}))


def _item(
    item_id: str, *, status: str = "open", source: str = "python_sdk_drift"
) -> dict[str, str]:
    return {
        "id": item_id,
        "source": source,
        "status": status,
        "class": "start_cohort",
        "discovered_on": "2026-04-17",
    }


def test_load_open_items_sorts_and_excludes_resolved(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.json"
    _write_inventory(
        inventory,
        [
            _item("python_sdk_drift:Z"),
            _item("python_sdk_drift:B", status="resolved"),
            _item("python_sdk_drift:A"),
        ],
    )

    result = batches.load_open_items(inventory)

    assert [item["id"] for item in result] == [
        "python_sdk_drift:A",
        "python_sdk_drift:Z",
    ]


def test_load_open_items_rejects_duplicate_ids(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.json"
    _write_inventory(inventory, [_item("python_sdk_drift:A"), _item("python_sdk_drift:A")])

    with pytest.raises(batches.InventoryError, match="duplicate inventory id"):
        batches.load_open_items(inventory)


def test_load_open_items_rejects_unknown_status(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.json"
    _write_inventory(inventory, [_item("python_sdk_drift:A", status="pending")])

    with pytest.raises(batches.InventoryError, match="unknown status"):
        batches.load_open_items(inventory)


def test_load_open_items_requires_items_list(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.json"
    inventory.write_text("{}")

    with pytest.raises(batches.InventoryError, match="must contain an 'items' list"):
        batches.load_open_items(inventory)


def test_partition_and_render_are_stable() -> None:
    items = [_item(f"python_sdk_drift:{value}") for value in ("E", "A", "D", "B", "C")]

    first = batches.build_outputs(
        items,
        batch_size=2,
        inventory_label="inventory.json",
        playbook_label="playbook.md",
    )
    second = batches.build_outputs(
        list(reversed(items)),
        batch_size=2,
        inventory_label="inventory.json",
        playbook_label="playbook.md",
    )

    assert first == second
    assert sorted(first) == ["batch-001.md", "batch-002.md", "batch-003.md", "index.md"]
    assert "`python_sdk_drift:A`" in first["batch-001.md"]
    assert "`python_sdk_drift:C`" in first["batch-002.md"]
    assert "Open entries: `5`" in first["index.md"]


def test_empty_inventory_produces_index_only_snapshot() -> None:
    outputs = batches.build_outputs(
        [],
        batch_size=25,
        inventory_label="inventory.json",
        playbook_label="playbook.md",
    )

    assert list(outputs) == ["index.md"]
    assert "Open entries: `0`" in outputs["index.md"]
    assert "Batch count: `0`" in outputs["index.md"]
    assert batches.summarize_batches([], 25) == []


def test_packet_digest_changes_with_membership() -> None:
    one = [_item("python_sdk_drift:A")]
    two = [*one, _item("python_sdk_drift:B")]

    assert batches.batch_digest(one) != batches.batch_digest(two)
    assert batches.batch_digest([_item("A\nB")]) != batches.batch_digest([_item("A"), _item("B")])


def test_batch_summary_exposes_machine_readable_identity() -> None:
    items = [_item("python_sdk_drift:B"), _item("python_sdk_drift:A")]

    summaries = batches.summarize_batches(items, batch_size=1)

    assert summaries == [
        {
            "id": "route-batch-001",
            "entries": 1,
            "digest": batches.batch_digest([_item("python_sdk_drift:A")]),
            "first_id": "python_sdk_drift:A",
            "last_id": "python_sdk_drift:A",
        },
        {
            "id": "route-batch-002",
            "entries": 1,
            "digest": batches.batch_digest([_item("python_sdk_drift:B")]),
            "first_id": "python_sdk_drift:B",
            "last_id": "python_sdk_drift:B",
        },
    ]


def test_write_outputs_refuses_stale_packet(tmp_path: Path) -> None:
    (tmp_path / "batch-999.md").write_text("obsolete")

    with pytest.raises(batches.InventoryError, match="stale generated packets"):
        batches.write_outputs(tmp_path, {"index.md": "index\n"})


def test_write_outputs_requires_index(tmp_path: Path) -> None:
    with pytest.raises(batches.InventoryError, match="must include index.md"):
        batches.write_outputs(tmp_path, {"batch-001.md": "packet\n"})


def test_write_outputs_round_trip(tmp_path: Path) -> None:
    outputs = {"index.md": "index\n", "batch-001.md": "packet\n"}

    batches.write_outputs(tmp_path, outputs)
    batches.write_outputs(tmp_path, outputs)

    assert {path.name: path.read_text() for path in tmp_path.iterdir()} == outputs


def test_write_outputs_removes_old_index_before_packet_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "index.md").write_text("old index\n")
    original_write = Path.write_text

    def fail_packet_write(path: Path, content: str, *args, **kwargs):
        if path.name == "batch-001.md":
            raise OSError("disk full")
        return original_write(path, content, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_packet_write)

    with pytest.raises(OSError, match="disk full"):
        batches.write_outputs(tmp_path, {"index.md": "new index\n", "batch-001.md": "packet\n"})

    assert not (tmp_path / "index.md").exists()
