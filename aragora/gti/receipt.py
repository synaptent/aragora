"""Belief provenance + freshness fields for GTI DecisionReceipts.

Extends the existing receipt provenance concept (aragora/gauntlet/receipt_models.py
:ProvenanceRecord, and ReceiptVerification whose verification_status already
includes "stale") with the freshness contract this benchmark requires: every
load-bearing belief must carry a source + as_of timestamp and must not be used
past its TTL without revalidation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class BeliefProvenance:
    belief_id: str
    source: str
    as_of: str  # ISO 8601
    verification_method: str
    freshness_ttl_seconds: float
    was_revalidated_at_decision: bool


def validate_belief_provenance(beliefs: list[BeliefProvenance], now_iso: str) -> list[str]:
    """Return a list of problems; empty list means the receipt is valid."""
    problems: list[str] = []
    try:
        now = datetime.fromisoformat(now_iso)
    except ValueError:
        return ["now_iso: invalid ISO timestamp"]

    now_has_offset = now.utcoffset() is not None
    for b in beliefs:
        missing = [
            field
            for field, value in (
                ("source", b.source),
                ("as_of", b.as_of),
                ("verification_method", b.verification_method),
            )
            if not value
        ]
        if missing:
            problems.append(f"{b.belief_id}: missing {'/'.join(missing)} provenance")
            continue

        ttl = b.freshness_ttl_seconds
        # isfinite only sees floats: ints are always finite, and math.isfinite
        # raises OverflowError on ints too large to convert to float.
        if (
            isinstance(ttl, bool)
            or not isinstance(ttl, (int, float))
            or (isinstance(ttl, float) and not math.isfinite(ttl))
            or ttl <= 0
        ):
            problems.append(f"{b.belief_id}: invalid freshness_ttl_seconds")
            continue

        if not isinstance(b.was_revalidated_at_decision, bool):
            problems.append(f"{b.belief_id}: invalid was_revalidated_at_decision")
            continue

        try:
            as_of = datetime.fromisoformat(b.as_of)
        except ValueError:
            problems.append(f"{b.belief_id}: invalid as_of timestamp")
            continue

        if (as_of.utcoffset() is not None) != now_has_offset:
            problems.append(f"{b.belief_id}: as_of timestamp timezone must match now_iso")
            continue

        age = (now - as_of).total_seconds()
        if age < 0:
            problems.append(f"{b.belief_id}: as_of timestamp is in the future")
            continue

        if age > ttl and not b.was_revalidated_at_decision:
            problems.append(
                f"{b.belief_id}: belief used past TTL "
                f"({age:.0f}s > {ttl:.0f}s) without revalidation"
            )
    return problems
