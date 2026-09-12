"""AGT-05 stale-policy seed (shadow only).

A *stale* claim is one whose resolution would still type-check but whose
information value has decayed past a threshold. The settlement module
already supports time-decay via ``decay_half_life_days``. This module
adds an *explicit, named* policy surface that future settlement,
leaderboard, and audit code can call without each call site rolling its
own age math.

This is shadow-only:

- It defines :class:`StalePolicy` with conservative defaults that match
  the existing 30-day settlement half-life.
- It exposes :func:`is_stale` as the public predicate.
- It returns a :class:`StaleDecision` carrying the reason, the age in
  days, and the policy fingerprint, so audit trails are
  machine-greppable.
- No production code path calls into this module yet.

Three-axis calibration policy (added in AGT-05 / #6066):

The :func:`resolve_stale_calibration` function implements the proposal from
``docs/plans/2026-04-29-agt-05-stale-claim-policy.md``.  It maps evidence age
relative to a settlement half-life to one of three :class:`PolicyDecision`
values:

- ``decay_penalty`` — evidence is fresh relative to its half-life; treat the
  stale verdict as a calibration miss and apply the full penalty.
- ``renewal_required`` — evidence is in the mid-band; abstain from penalty and
  emit a deterministic ``claim_renewal_id`` so the agent can re-evidence.
- ``abstain`` — evidence is so old that staleness is structural; abstain
  without any renewal signal.

This function is **advisory and pure** — no calibration delta or renewal
record is written by this module.

A future PR can wire :func:`resolve_stale_calibration` into ``settle_claim``,
the calibration leaderboard, and the rev-4 staging scorecard.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Final

# Default tuning. These mirror the half-life used in
# ``aragora.reputation.settlement.settle_claim`` so a claim that is
# materially decayed under the existing scoring rule is also flagged
# stale by this predicate.
DEFAULT_FRESH_DAYS: Final[float] = 7.0
DEFAULT_STALE_DAYS: Final[float] = 30.0
DEFAULT_HARD_LIMIT_DAYS: Final[float] = 180.0


@dataclass(frozen=True)
class StalePolicy:
    """Bounds for the stale-claim predicate.

    Attributes:
        fresh_days: Claims younger than this are always fresh.
        stale_days: Claims older than this are always stale.
        hard_limit_days: Claims older than this are *expired* and
            should not even be settled.
    """

    fresh_days: float = DEFAULT_FRESH_DAYS
    stale_days: float = DEFAULT_STALE_DAYS
    hard_limit_days: float = DEFAULT_HARD_LIMIT_DAYS

    def __post_init__(self) -> None:
        if not (0 < self.fresh_days <= self.stale_days <= self.hard_limit_days):
            raise ValueError(
                "StalePolicy bounds must satisfy "
                "0 < fresh_days <= stale_days <= hard_limit_days; got "
                f"fresh={self.fresh_days}, stale={self.stale_days}, "
                f"hard_limit={self.hard_limit_days}"
            )

    def fingerprint(self) -> str:
        """Stable 12-char hash of the policy parameters.

        Useful for tagging audit rows so a future change in defaults can
        be tracked in receipts without a schema migration.
        """
        material = json.dumps(
            {
                "fresh_days": self.fresh_days,
                "stale_days": self.stale_days,
                "hard_limit_days": self.hard_limit_days,
            },
            sort_keys=True,
        )
        return f"sp_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:12]}"


@dataclass(frozen=True)
class StaleDecision:
    """The outcome of a stale-policy evaluation.

    Attributes:
        is_stale: True iff the claim should be treated as stale.
        is_expired: True iff the claim is past the hard-limit and
            should not be settled at all.
        age_days: Age of the claim in days at the evaluation moment.
        bucket: One of ``"fresh"``, ``"stale"``, ``"expired"``.
        policy_fingerprint: Stable hash of the policy parameters.
    """

    is_stale: bool
    is_expired: bool
    age_days: float
    bucket: str
    policy_fingerprint: str


def _age_days(claim_iso: str, now_iso: str) -> float:
    claim_at = datetime.fromisoformat(claim_iso.replace("Z", "+00:00"))
    if claim_at.tzinfo is None:
        claim_at = claim_at.replace(tzinfo=timezone.utc)
    now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta = (now - claim_at).total_seconds() / 86400.0
    if delta < 0:
        # Future-dated claims are treated as fresh; we never lie about age.
        return 0.0
    return delta


def is_stale(
    *,
    claim_iso: str,
    now_iso: str | None = None,
    policy: StalePolicy | None = None,
) -> StaleDecision:
    """Decide whether a claim is fresh, stale, or expired.

    Args:
        claim_iso: ISO-8601 timestamp at which the claim was made.
        now_iso: Optional override for the evaluation moment; defaults
            to ``datetime.now(timezone.utc)``.
        policy: Optional :class:`StalePolicy`; defaults to the
            conservative module-level defaults.

    Returns:
        A :class:`StaleDecision`. The decision is *advisory* — call
        sites are responsible for whatever action it implies (skip
        settlement, mark a leaderboard cell, append to an audit row).
    """
    if not claim_iso:
        raise ValueError("claim_iso must be a non-empty ISO-8601 string")
    if now_iso is None:
        now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    p = policy or StalePolicy()
    age = _age_days(claim_iso, now_iso)
    if age > p.hard_limit_days:
        return StaleDecision(
            is_stale=True,
            is_expired=True,
            age_days=age,
            bucket="expired",
            policy_fingerprint=p.fingerprint(),
        )
    if age >= p.stale_days:
        return StaleDecision(
            is_stale=True,
            is_expired=False,
            age_days=age,
            bucket="stale",
            policy_fingerprint=p.fingerprint(),
        )
    return StaleDecision(
        is_stale=False,
        is_expired=False,
        age_days=age,
        bucket="fresh",
        policy_fingerprint=p.fingerprint(),
    )


# ---------------------------------------------------------------------------
# Three-axis calibration policy (AGT-05 / #6066)
# ---------------------------------------------------------------------------


class PolicyDecision(str, Enum):
    """Calibration action for a stale claim.

    See ``docs/plans/2026-04-29-agt-05-stale-claim-policy.md`` for the full
    rationale.

    - ``DECAY_PENALTY``: evidence is fresh relative to its half-life; apply
      the full calibration penalty.
    - ``RENEWAL_REQUIRED``: evidence is in the mid-band; abstain from penalty
      and emit a renewal token.
    - ``ABSTAIN``: evidence is structurally old; abstain silently.
    """

    DECAY_PENALTY = "decay_penalty"
    RENEWAL_REQUIRED = "renewal_required"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class StaleCalibrationDecision:
    """Output of :func:`resolve_stale_calibration`.

    All fields are advisory.  No calibration delta is written by this module.

    Attributes:
        policy_decision: The three-axis calibration action.
        calibration_delta_modifier: 1.0 for full penalty, 0.0 to abstain.
        evidence_age_days: Age of the evidence at evaluation time.
        half_life_used_days: Settlement half-life that produced this decision.
        claim_renewal_id: Deterministic renewal token when policy_decision is
            ``RENEWAL_REQUIRED``; ``None`` otherwise.  Derived from
            ``claim_id`` and ``evidence_age_days`` so callers can correlate
            audit rows without a round-trip to a database.
        policy_fingerprint: SHA-256–derived 12-char tag over the inputs, for
            audit-trail tagging.  Format: ``"cp_" + 12 hex chars``.
    """

    policy_decision: PolicyDecision
    calibration_delta_modifier: float
    evidence_age_days: float
    half_life_used_days: float
    claim_renewal_id: str | None
    policy_fingerprint: str


def _calibration_fingerprint(evidence_age_days: float, half_life_days: float) -> str:
    material = json.dumps(
        {
            "evidence_age_days": round(evidence_age_days, 6),
            "half_life_days": round(half_life_days, 6),
        },
        sort_keys=True,
    )
    return f"cp_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:12]}"


def _renewal_id(claim_id: str, evidence_age_days: float) -> str:
    material = f"{claim_id}:{evidence_age_days:.6f}"
    return f"renew_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}"


def resolve_stale_calibration(
    *,
    evidence_age_days: float,
    half_life_days: float,
    claim_id: str = "",
) -> StaleCalibrationDecision:
    """Map evidence age to a three-axis calibration decision.

    Implements the policy table from
    ``docs/plans/2026-04-29-agt-05-stale-claim-policy.md``:

    +-----------------------------------------------+--------------------+----------+
    | Condition                                     | Decision           | Modifier |
    +===============================================+====================+==========+
    | evidence_age < 0.5 × half_life                | decay_penalty      | 1.0      |
    +-----------------------------------------------+--------------------+----------+
    | 0.5 × half_life ≤ evidence_age < 1.5 × half  | renewal_required   | 0.0      |
    +-----------------------------------------------+--------------------+----------+
    | evidence_age ≥ 1.5 × half_life                | abstain            | 0.0      |
    +-----------------------------------------------+--------------------+----------+

    This function is **pure and side-effect free**.  Shadow only; no live
    settlement path calls this yet.

    Args:
        evidence_age_days: Age of the underlying evidence in days (>= 0).
        half_life_days: Settlement half-life in days (> 0).
        claim_id: Optional stable identifier for the claim; included in the
            ``claim_renewal_id`` hash so audit rows are correlatable.

    Returns:
        A :class:`StaleCalibrationDecision` with the advisory action.

    Raises:
        ValueError: If either input is NaN or infinite, if
            ``evidence_age_days < 0``, or if ``half_life_days <= 0``.
    """
    # NaN compares False against every bound and infinities collapse the band
    # arithmetic, so both would silently route to a decision; reject them first.
    if not math.isfinite(evidence_age_days):
        raise ValueError(f"evidence_age_days must be finite; got {evidence_age_days!r}")
    if not math.isfinite(half_life_days):
        raise ValueError(f"half_life_days must be finite; got {half_life_days!r}")
    if evidence_age_days < 0:
        raise ValueError(f"evidence_age_days must be >= 0; got {evidence_age_days!r}")
    if half_life_days <= 0:
        raise ValueError(f"half_life_days must be > 0; got {half_life_days!r}")

    fp = _calibration_fingerprint(evidence_age_days, half_life_days)
    lo = 0.5 * half_life_days
    hi = 1.5 * half_life_days

    if evidence_age_days < lo:
        return StaleCalibrationDecision(
            policy_decision=PolicyDecision.DECAY_PENALTY,
            calibration_delta_modifier=1.0,
            evidence_age_days=evidence_age_days,
            half_life_used_days=half_life_days,
            claim_renewal_id=None,
            policy_fingerprint=fp,
        )
    if evidence_age_days < hi:
        return StaleCalibrationDecision(
            policy_decision=PolicyDecision.RENEWAL_REQUIRED,
            calibration_delta_modifier=0.0,
            evidence_age_days=evidence_age_days,
            half_life_used_days=half_life_days,
            claim_renewal_id=_renewal_id(claim_id, evidence_age_days),
            policy_fingerprint=fp,
        )
    return StaleCalibrationDecision(
        policy_decision=PolicyDecision.ABSTAIN,
        calibration_delta_modifier=0.0,
        evidence_age_days=evidence_age_days,
        half_life_used_days=half_life_days,
        claim_renewal_id=None,
        policy_fingerprint=fp,
    )


__all__ = [
    "DEFAULT_FRESH_DAYS",
    "DEFAULT_STALE_DAYS",
    "DEFAULT_HARD_LIMIT_DAYS",
    "StalePolicy",
    "StaleDecision",
    "is_stale",
    "PolicyDecision",
    "StaleCalibrationDecision",
    "resolve_stale_calibration",
]
