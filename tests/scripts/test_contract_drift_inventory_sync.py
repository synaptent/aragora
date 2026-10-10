"""The committed contract-drift inventory agrees with the live baselines."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import scripts.check_contract_drift_ratchet as ratchet
import scripts.generate_contract_drift_inventory as gen

REPO_ROOT = Path(__file__).resolve().parents[2]
INVENTORY_PATH = REPO_ROOT / gen.DEFAULT_INVENTORY


def _inventory() -> dict[str, Any]:
    return json.loads(INVENTORY_PATH.read_bytes())


def _iso_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(value or "")
    except (TypeError, ValueError):
        return None


def test_open_inventory_rows_match_live_baselines() -> None:
    current_ids = gen.collect_ids(gen.load_working_docs(REPO_ROOT))

    assert gen.find_sync_issues(_inventory(), current_ids) == []


def test_resolved_inventory_rows_record_a_resolution_date() -> None:
    # Not after today in either the local or the UTC calendar.
    latest = max(date.today(), datetime.now(UTC).date())
    problems: list[str] = []
    for item in _inventory()["items"]:
        item_id, status = item.get("id", "<missing id>"), item.get("status")
        if status not in gen.VALID_STATUSES:
            problems.append(f"{item_id}: unknown status {status!r}")
            continue
        if status != "resolved":
            continue
        resolved_on = _iso_date(item.get("resolved_on"))
        discovered_on = _iso_date(item.get("discovered_on"))
        if resolved_on is None or discovered_on is None:
            problems.append(f"{item_id}: invalid resolved_on or discovered_on")
        elif not discovered_on <= resolved_on <= latest:
            problems.append(f"{item_id}: resolved_on {resolved_on} outside [discovered_on, today]")

    assert problems == []


def test_inventory_rows_agree_with_accepted_authority_dispositions() -> None:
    inventory = _inventory()
    authority = inventory["accepted_authority"]
    rows = {item.get("id"): item for item in inventory["items"]}
    expected_status = {
        item["original_record_id"]: "open" if item["status"] == "active" else "resolved"
        for item in authority["active_inventory"]
    }
    problems: list[str] = []
    for record in authority["canonical_artifacts"]["original_cohort"]["original_records"]:
        literal = gen.normalize_key(record["exact_historical_literal_record"])
        row = rows.get(f"{record['source_json_key']}:{literal}")
        expected = expected_status[record["original_record_id"]]
        if row is not None and row.get("status") != expected:
            problems.append(f"{row['id']}: {row.get('status')!r}, authority says {expected!r}")

    assert problems == []


def test_accepted_authority_line_stays_canonical() -> None:
    # Row edits must leave the one-line authority blob alone: the legacy
    # generator's write mode drops it, and any re-render changes its bytes.
    raw = INVENTORY_PATH.read_bytes()
    authority = json.loads(raw)["accepted_authority"]

    assert raw.split(b"\n")[1] == (
        b'  "accepted_authority":' + ratchet._canonical_json_bytes(authority) + b","
    )
