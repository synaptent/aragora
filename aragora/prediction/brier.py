"""Per-agent rolling Brier scorer for resolved synthetic GitHub prediction claims.

Computes per-agent Brier scores from resolved :class:`StakeableClaim` objects.
A rolling window (default 90 days) filters by claim *created_at* so only
recent predictions count toward an agent's calibration measurement.

Brier score formula: B = (1/N) Σ (f_t − o_t)²
  f_t = agent probability forecast (0–1)
  o_t = binary outcome (1 for RESOLVED_YES, 0 for RESOLVED_NO)
  Lower is better; 0 = perfect, 0.25 = no-skill baseline, 1 = worst possible.

Feature flag: ``ARAGORA_PREDICTION_MARKETS_ENABLED`` (default OFF).
Data classes are always importable; only :func:`compute_brier_scores` checks
the flag (controllable via *require_enabled*).

Deliberately does NOT:
- call the GitHub API or any external service
- touch the live dispatch queue or boss loop
- import from ``aragora.blockchain`` (reputation wiring is AGT-05)

Advances: issue #6065 (AGT-04), sub-deliverable 4 — per-agent rolling Brier score.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from aragora.prediction.stakeable_claim import ResolutionStatus, StakeableClaim

_ENV_FLAG = "ARAGORA_PREDICTION_MARKETS_ENABLED"


def _flag_enabled() -> bool:
    return os.environ.get(_ENV_FLAG, "").lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentBrierScore:
    """Per-agent Brier score over resolved claims in the rolling window.

    Attributes:
        agent_id: Agent identifier.
        score: Brier score (lower is better; 0 = perfect, 0.25 = no-skill baseline).
        n_predictions: Number of resolved claims scored.
        window_days: Rolling window width used for filtering.
        computed_at: ISO-8601 UTC timestamp of this computation.
    """

    agent_id: str
    score: float
    n_predictions: int
    window_days: int
    computed_at: str

    @property
    def has_skill(self) -> bool:
        """True when score is strictly better than the 0.25 no-skill baseline."""
        return self.score < 0.25

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "score": self.score,
            "n_predictions": self.n_predictions,
            "window_days": self.window_days,
            "computed_at": self.computed_at,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _binary_outcome(claim: StakeableClaim) -> float | None:
    """Return 1.0 for YES, 0.0 for NO, None for anything else."""
    if claim.resolution_status == ResolutionStatus.RESOLVED_YES:
        return 1.0
    if claim.resolution_status == ResolutionStatus.RESOLVED_NO:
        return 0.0
    return None


def _parse_utc(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_brier_scores(
    claims: list[StakeableClaim],
    *,
    window_days: int = 90,
    cutoff_dt: datetime | None = None,
    require_enabled: bool = True,
) -> dict[str, AgentBrierScore]:
    """Compute per-agent Brier scores over resolved claims in the rolling window.

    Only claims that are RESOLVED_YES or RESOLVED_NO and whose *created_at*
    falls within [cutoff − window_days, cutoff] are included.  Agents with no
    qualifying predictions are omitted from the result.

    Args:
        claims: All claims to consider; unresolved ones are silently skipped.
        window_days: Rolling window width in days (default 90).
        cutoff_dt: Upper bound of the window (default: ``datetime.now(UTC)``).
        require_enabled: When True (default), raises if the feature flag is off.

    Returns:
        ``{agent_id: AgentBrierScore}`` for every agent with ≥1 scored prediction.

    Raises:
        RuntimeError: When *require_enabled* is True and the flag is off.
    """
    if require_enabled and not _flag_enabled():
        raise RuntimeError(f"Prediction markets are disabled. Set {_ENV_FLAG}=1 to enable.")

    cutoff = (cutoff_dt or datetime.now(tz=UTC)).astimezone(UTC)
    window_start = cutoff - timedelta(days=window_days)
    computed_at = cutoff.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    # {agent_id: [squared_errors]}
    squared_errors: dict[str, list[float]] = {}

    for claim in claims:
        outcome = _binary_outcome(claim)
        if outcome is None:
            continue
        try:
            created = _parse_utc(claim.created_at)
        except (ValueError, AttributeError):
            continue
        if not (window_start <= created <= cutoff):
            continue

        for agent_id, prob in claim.positions.items():
            squared_errors.setdefault(agent_id, []).append((prob - outcome) ** 2)

    return {
        agent_id: AgentBrierScore(
            agent_id=agent_id,
            score=sum(errs) / len(errs),
            n_predictions=len(errs),
            window_days=window_days,
            computed_at=computed_at,
        )
        for agent_id, errs in squared_errors.items()
    }
