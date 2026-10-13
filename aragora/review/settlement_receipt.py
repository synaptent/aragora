"""Persisted human settlement receipt for one PR/head/packet tuple."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class SettlementReceipt:
    """Persisted human settlement receipt for one PR/head/packet tuple.

    The five ``outcome_*`` fields are optional post-settlement signals that
    correspond exactly to the canonical invalidation labels in
    :data:`aragora.review.invalidation.INVALIDATION_SIGNALS`. They default to
    ``None`` (= "signal not yet observed") to preserve backward compatibility
    with receipts written before #6375 phase 4. When ``observe_outcome`` (in
    :mod:`aragora.review.settlement_outcome`) populates these, downstream
    consumers like :mod:`aragora.review.invalidation_event_source` can finally
    classify the human side of the baseline (closing the
    ``schema_gap_human_numerator`` note that #6898 surfaces).

    Semantics:
      - All five ``None`` → receipt is denominator-only (counted in
        ``total_human_settled`` but not in invalidation numerator).
      - Any one ``True`` → receipt is invalidated, all firing signals
        contribute to the numerator.
      - All five ``False`` → receipt is a clean human-settled non-invalidation
        (still denominator, explicitly not numerator).

    ``outcome_observed_at`` is the ISO 8601 UTC timestamp at which the
    observation was recorded (separate from ``reviewed_at`` which is the
    settlement time). ``None`` iff none of the five outcome fields have been
    observed yet.
    """

    session_id: str
    reviewed_at: str
    actor: str
    action: str
    reason: str
    pr_number: int
    pr_url: str
    head_sha: str
    base_sha: str
    packet_sha: str
    queue_bucket: str
    machine_recommendation: str
    github_event: str
    elapsed_seconds: float | None = None
    receipt_path: str = ""
    # Post-settlement outcome signals (#6375 phase 4). None == not yet observed.
    outcome_revert_within_window: bool | None = None
    outcome_post_merge_incident: bool | None = None
    outcome_human_override_redo: bool | None = None
    outcome_rollback: bool | None = None
    outcome_reopened_pr: bool | None = None
    outcome_observed_at: str | None = None
    post_merge_lane_audit: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload.get("post_merge_lane_audit") is None:
            payload.pop("post_merge_lane_audit", None)
        return payload


__all__ = ["SettlementReceipt"]
