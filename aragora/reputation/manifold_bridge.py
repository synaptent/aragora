"""Manifold Markets → AGT-05 reputation bridge (AGT-03 + AGT-05 / #6064, #6066).

Bridges a resolved :class:`~aragora.connectors.prediction_markets.manifold.ManifoldMarket`
and its :class:`~aragora.connectors.prediction_markets.manifold.ManifoldResolution` into the
AGT-05 reputation flow, producing a :class:`~aragora.reputation.types.StakeableClaim` +
:class:`~aragora.reputation.types.ResolvedClaim` pair ready for
:func:`~aragora.reputation.settlement.settle_claim`.

Flag: ``ARAGORA_REPUTATION_FLOW_ENABLED`` (default off).

Outcome mapping: ManifoldResolution.outcome is already normalized to the ternary
"yes" / "no" / "inconclusive" shape by the connector; this bridge passes it through
directly, treating any unrecognized value as "inconclusive".

Companion to :mod:`aragora.reputation.metaculus_bridge` (Metaculus path) and
:mod:`aragora.reputation.bridge` (synthetic-GitHub path).

Out of scope for this slice (deferred):
- Real-time polling of Manifold API (lives in the connector layer)
- Per-agent Brier score wiring to the evaluation layer (AGT-03 Phase 3)
- On-chain anchoring via ReputationRegistry (downstream AGT-05 sub-deliverable)
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from aragora.reputation.types import (
    DOMAIN_PREDICTION_MARKET,
    ClaimOutcome,
    ResolvedClaim,
    StakeableClaim,
    StakePolicy,
)

if TYPE_CHECKING:
    from aragora.connectors.prediction_markets.manifold import ManifoldMarket, ManifoldResolution

_RESOLUTION_SOURCE = "manifold"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def reputation_flow_enabled() -> bool:
    """Return True when ``ARAGORA_REPUTATION_FLOW_ENABLED`` is truthy."""
    return os.environ.get("ARAGORA_REPUTATION_FLOW_ENABLED", "").strip().lower() in _TRUTHY


def _ms_to_iso(ts_ms: int | None) -> str | None:
    """Convert a Manifold millisecond timestamp to an ISO-8601 UTC string."""
    if ts_ms is None:
        return None
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC).isoformat().replace("+00:00", "Z")


def _manifold_outcome(resolution: "ManifoldResolution") -> ClaimOutcome:
    """Map ManifoldResolution.outcome (normalized ternary) to ClaimOutcome."""
    raw = str(resolution.outcome or "").strip().lower()
    if raw == "yes":
        return "yes"
    if raw == "no":
        return "no"
    return "inconclusive"


def bridge_from_manifold_market(
    market: "ManifoldMarket",
    resolution: "ManifoldResolution",
    agent_id: str,
    predicted_probability: float,
    *,
    stake_units: int = 1,
    stake_policy: StakePolicy = "forfeit_on_loss",
    resolution_source: str = _RESOLUTION_SOURCE,
    submitted_at: str | None = None,
    require_enabled: bool = True,
) -> tuple[StakeableClaim, ResolvedClaim]:
    """Return *(StakeableClaim, ResolvedClaim)* ready for :func:`~aragora.reputation.settlement.settle_claim`.

    Parameters
    ----------
    market:
        Resolved Manifold market (``market.is_resolved`` must be True).
    resolution:
        Matching :class:`ManifoldResolution` from the connector.
    agent_id:
        Identifier of the predicting agent.
    predicted_probability:
        Agent's forecast in [0.0, 1.0].
    stake_units:
        Internal credit units at stake (>= 1).
    stake_policy:
        How credits settle on resolution.
    resolution_source:
        Override the source tag (default "manifold").
    submitted_at:
        ISO-8601 UTC timestamp of when the prediction was submitted.
        Defaults to now.
    require_enabled:
        When True (default), raise :exc:`RuntimeError` if the feature
        flag is off.
    """
    if require_enabled and not reputation_flow_enabled():
        raise RuntimeError(
            "ARAGORA_REPUTATION_FLOW_ENABLED is not set; "
            "set it to '1' or 'true' to use the Manifold reputation bridge"
        )
    if not market.is_resolved:
        raise ValueError(
            f"ManifoldMarket {market.market_id!r} is not resolved "
            f"(resolution={market.resolution!r})"
        )
    if not (0.0 <= predicted_probability <= 1.0):
        raise ValueError(
            f"predicted_probability must be in [0.0, 1.0]; got {predicted_probability!r}"
        )
    if stake_units < 1:
        raise ValueError(f"stake_units must be >= 1; got {stake_units!r}")

    _now = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    ts = submitted_at or _now
    close_time_iso = _ms_to_iso(market.close_time_ms)
    resolved_at_iso = _ms_to_iso(resolution.resolved_at_ms) or _now

    claim = StakeableClaim.create(
        agent_id=agent_id,
        domain=DOMAIN_PREDICTION_MARKET,
        statement=market.question,
        position="yes" if predicted_probability >= 0.5 else "no",
        predicted_probability=predicted_probability,
        stake_units=stake_units,
        stake_policy=stake_policy,
        resolution_source=resolution_source,
        resolution_id=market.market_id,
        provenance={
            "market_id": market.market_id,
            "slug": market.slug,
            "outcome_type": market.outcome_type,
            "close_time_ms": market.close_time_ms,
            "close_time_iso": close_time_iso,
            "submitted_at": ts,
        },
        created_at=ts,
    )
    resolved = ResolvedClaim(
        claim_id=claim.claim_id,
        outcome=_manifold_outcome(resolution),
        resolved_at=resolved_at_iso,
        resolution_source=resolution_source,
        evidence={
            "market_id": resolution.market_id,
            "outcome": resolution.outcome,
            "resolved_at_ms": resolution.resolved_at_ms,
            "question": market.question,
            "creator_username": market.creator_username,
        },
    )
    return claim, resolved


__all__ = ["bridge_from_manifold_market", "reputation_flow_enabled"]
