"""Reconcile the committed dogfood spend ledger's cumulative fields."""

from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path


LEDGER = Path("docs/case-studies/dogfood/spend-ledger.json")
MILESTONE_TOTAL_PREFIX = "cumulative_"
MILESTONE_TOTAL_SUFFIX = "_usd"


def test_spend_ledger_is_internally_consistent() -> None:
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"), parse_float=Decimal)
    entries = ledger["entries"]

    entry_total = sum((entry["estimated_cost_usd"] for entry in entries), Decimal("0"))
    assert ledger["cumulative_usd"] == entry_total

    milestone_totals: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for entry in entries:
        milestone = entry["milestone"].partition("-")[0]
        milestone_totals[milestone] += entry["estimated_cost_usd"]

    declared_milestone_totals = {
        key[len(MILESTONE_TOTAL_PREFIX) : -len(MILESTONE_TOTAL_SUFFIX)].replace("_", "-"): value
        for key, value in ledger.items()
        if key.startswith(MILESTONE_TOTAL_PREFIX)
        and key.endswith(MILESTONE_TOTAL_SUFFIX)
        and key != "cumulative_usd"
    }
    assert set(milestone_totals) <= set(declared_milestone_totals)
    assert declared_milestone_totals == {
        milestone: milestone_totals[milestone] for milestone in declared_milestone_totals
    }
    assert ledger["cumulative_usd"] <= ledger["cap_usd"]

    entry_ids = [entry["id"] for entry in entries]
    assert len(entry_ids) == len(set(entry_ids))
