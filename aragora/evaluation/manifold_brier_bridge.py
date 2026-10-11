"""AGT-03 sub-deliverable 2: bridge ResolutionEvent → ManifoldBrierScorer.

Converts resolved market outcomes into ManifoldPrediction records for rolling
Brier calibration.  Accepts any :class:`ResolutionEventProtocol`-compatible
object so tests and Metaculus can use the same path without loading the full
connectors package hierarchy.  Inconclusive outcomes are silently skipped.

Flag: ARAGORA_MANIFOLD_BRIER_ENABLED.  Advances issue #6064 (AGT-03).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, Sequence, runtime_checkable

from aragora.evaluation.manifold_brier import (
    ManifoldBrierScorer,
    ManifoldPrediction,
    manifold_brier_enabled,
)

_DISABLED_MSG = (
    "ManifoldBrierScorer bridge is disabled. Set ARAGORA_MANIFOLD_BRIER_ENABLED=1 to enable."
)


@runtime_checkable
class ResolutionEventProtocol(Protocol):
    """Structural protocol satisfied by ManifoldResolution and compatible stubs."""

    market_id: str
    outcome: str  # "yes" | "no" | "inconclusive"
    resolved_at_ms: int | None


@dataclass(frozen=True)
class PendingPrediction:
    """An agent prediction waiting to be settled against a resolution."""

    market_id: str
    agent_id: str
    predicted_probability: float
    predicted_at: datetime
    question_slug: str = ""

    def __post_init__(self) -> None:
        if not self.market_id:
            raise ValueError("market_id must be non-empty")
        if not self.agent_id:
            raise ValueError("agent_id must be non-empty")
        if not (0.0 <= self.predicted_probability <= 1.0):
            raise ValueError(
                f"predicted_probability must be in [0, 1]; got {self.predicted_probability}"
            )


def resolution_to_binary_outcome(resolution: ResolutionEventProtocol) -> int | None:
    """Map a resolution to 1 (YES), 0 (NO), or None (inconclusive). Pure, no flag check."""
    if resolution.outcome == "yes":
        return 1
    if resolution.outcome == "no":
        return 0
    return None


def _resolved_at_from_ms(resolved_at_ms: int | None) -> datetime | None:
    if resolved_at_ms is None:
        return None
    return datetime.fromtimestamp(resolved_at_ms / 1000.0, tz=UTC)


def record_resolution(
    scorer: ManifoldBrierScorer,
    resolution: ResolutionEventProtocol,
    pending: PendingPrediction,
) -> ManifoldPrediction | None:
    """Add a scored ManifoldPrediction to scorer; returns None for inconclusive outcomes."""
    if not manifold_brier_enabled():
        raise RuntimeError(_DISABLED_MSG)
    if resolution.market_id != pending.market_id:
        raise ValueError(
            f"resolution market_id {resolution.market_id!r} does not match "
            f"pending market_id {pending.market_id!r}"
        )
    outcome = resolution_to_binary_outcome(resolution)
    if outcome is None:
        return None
    prediction = ManifoldPrediction(
        question_id=resolution.market_id,
        predicted_probability=pending.predicted_probability,
        outcome=outcome,
        predicted_at=pending.predicted_at,
        resolved_at=_resolved_at_from_ms(resolution.resolved_at_ms),
        question_slug=pending.question_slug,
        agent_id=pending.agent_id,
    )
    scorer.add(prediction)
    return prediction


def batch_record_resolutions(
    scorer: ManifoldBrierScorer,
    resolutions: dict[str, ResolutionEventProtocol],
    pending_predictions: Sequence[PendingPrediction],
) -> tuple[int, int]:
    """Batch-settle predictions; returns (recorded, skipped) counts."""
    if not manifold_brier_enabled():
        raise RuntimeError(_DISABLED_MSG)
    recorded = 0
    skipped = 0
    for pending in pending_predictions:
        resolution = resolutions.get(pending.market_id)
        if resolution is None:
            skipped += 1
            continue
        result = record_resolution(scorer, resolution, pending)
        if result is None:
            skipped += 1
        else:
            recorded += 1
    return recorded, skipped


__all__ = [
    "PendingPrediction",
    "ResolutionEventProtocol",
    "batch_record_resolutions",
    "record_resolution",
    "resolution_to_binary_outcome",
]
