"""The committed contract-drift inventory agrees with the live baselines."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import scripts.check_contract_drift_ratchet as ratchet
import scripts.generate_contract_drift_inventory as gen

REPO_ROOT = Path(__file__).resolve().parents[2]
INVENTORY_PATH = REPO_ROOT / gen.DEFAULT_INVENTORY


def _inventory() -> dict[str, Any]:
    return json.loads(INVENTORY_PATH.read_bytes())


def test_open_inventory_rows_match_live_baselines() -> None:
    current_ids = gen.collect_ids(gen.load_working_docs(REPO_ROOT))

    assert gen.find_sync_issues(_inventory(), current_ids) == []


def test_resolved_inventory_rows_record_a_resolution_date() -> None:
    problems: list[str] = []
    for item in _inventory()["items"]:
        item_id, status = item["id"], item.get("status")
        if status not in gen.VALID_STATUSES:
            problems.append(f"{item_id}: unknown status {status!r}")
            continue
        if status != "resolved":
            continue
        try:
            resolved_on = date.fromisoformat(item.get("resolved_on") or "")
        except (TypeError, ValueError):
            problems.append(f"{item_id}: invalid resolved_on {item.get('resolved_on')!r}")
            continue
        if resolved_on < date.fromisoformat(item["discovered_on"]):
            problems.append(f"{item_id}: resolved before it was discovered")

    assert problems == []


def test_accepted_authority_line_stays_canonical_and_valid() -> None:
    # Row edits must leave the one-line authority blob alone: the legacy
    # generator's write mode drops it, and any re-render changes its bytes.
    raw = INVENTORY_PATH.read_bytes()
    authority = json.loads(raw)["accepted_authority"]

    assert raw.split(b"\n")[1] == (
        b'  "accepted_authority":' + ratchet._canonical_json_bytes(authority) + b","
    )
    summary = ratchet.validate_accepted_authority(authority, repo_root=REPO_ROOT)
    assert summary["original_record_total"] == 655
