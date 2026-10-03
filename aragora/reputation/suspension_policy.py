"""AGT-05 hard-suspension policy — explicit eligibility gate for dispatch.

Sub-deliverable 6 of AGT-05 (#6066):
"Dispatch eligibility integration with debate team_selector and ELO
(soft downweighting by default; hard suspension only on explicit policy)"

This module provides the *hard* side of that contract. The soft side
(pseudo-Brier weighting) lives in :mod:`aragora.reputation.selection_bridge`.

Hard suspension kicks in when an agent's running reputation score falls
below a configurable floor AND the agent has enough samples for the
verdict to be statistically meaningful. When the feature flag is off
(the default), every check returns ``suspended=False``; no call site is
ever silently gated.

Feature flag: ``ARAGORA_REPUTATION_SUSPENSION_ENABLED`` (default OFF).

Out of scope for this slice:
- Wiring into ``TeamSelector`` — follow-on after the AGT-* gate opens.
- On-chain suspension records — lives with the blockchain anchoring layer.
- Domain-filtered time-decay — domain scores currently sum deltas without
  decay; apply_decay only works on the full-domain path via ``get_score``.
- Notification / audit-event emission — follow-on once event dispatcher
  is stable.

Advances: issue #6066 (AGT-05), sub-deliverable 6.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.reputation.store import ReputationStore

__all__ = [
    "DEFAULT_MIN_SAMPLES",
    "DEFAULT_SCORE_FLOOR",
    "DEFAULT_SUSPENSION_DAYS",
    "SuspensionChecker",
    "SuspensionDecision",
    "SuspensionThreshold",
    "enable_suspension",
    "suspension_enabled",
]

_ENV_FLAG = "ARAGORA_REPUTATION_SUSPENSION_ENABLED"

DEFAULT_SCORE_FLOOR: float = -50.0
DEFAULT_MIN_SAMPLES: int = 10
DEFAULT_SUSPENSION_DAYS: float = 7.0


def suspension_enabled() -> bool:
    """Return True when ARAGORA_REPUTATION_SUSPENSION_ENABLED is truthy."""
    raw = str(os.environ.get(_ENV_FLAG) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def enable_suspension() -> None:
    """Enable the AGT-05 hard-suspension policy for the current process."""
    os.environ[_ENV_FLAG] = "1"


@dataclass(frozen=True)
class SuspensionThreshold:
    """Policy parameters controlling when hard suspension is applied.

    Attributes:
        score_floor: Running reputation score below this value triggers
            suspension. Default ``-50.0``. Scores are unbounded; a floor
            of -50.0 means an agent must net-lose 50 stake-units before
            being suspended.
        min_samples: Minimum number of deltas before suspension can fire.
            Prevents excluding agents with insufficient evidence (default
            ``10``).
        suspension_days: Advisory suspension duration stored in
            :class:`SuspensionDecision` for downstream ledgers. This
            module does not enforce a timeout (default ``7.0``).
        domains: When non-``None``, only deltas whose ``domain`` is in
            this set contribute to the score check. When ``None`` all
            domains are included and the store's decay-weighted score is
            used; domain-filtered paths sum raw deltas without decay.
    """

    score_floor: float = DEFAULT_SCORE_FLOOR
    min_samples: int = DEFAULT_MIN_SAMPLES
    suspension_days: float = DEFAULT_SUSPENSION_DAYS
    domains: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if self.min_samples < 1:
            raise ValueError(f"min_samples must be >= 1; got {self.min_samples}")
        if self.suspension_days <= 0:
            raise ValueError(f"suspension_days must be > 0; got {self.suspension_days}")

    def fingerprint(self) -> str:
        """Return a 64-char SHA-256 hex digest of this policy for audit trails."""
        payload: dict[str, Any] = {
            "score_floor": self.score_floor,
            "min_samples": self.min_samples,
            "suspension_days": self.suspension_days,
            "domains": sorted(self.domains) if self.domains is not None else None,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SuspensionDecision:
    """Outcome of a :class:`SuspensionChecker` evaluation.

    Attributes:
        agent_id: The agent evaluated.
        suspended: ``True`` when the agent should be excluded from dispatch.
        reason: Machine-readable verdict code — one of:
            ``"flag_disabled"``, ``"no_data"``, ``"insufficient_samples"``,
            ``"score_above_floor"``, ``"score_below_floor"``.
        score: Running reputation score used for the decision. ``None``
            when there is no data or the flag is disabled.
        sample_count: Number of deltas evaluated (after domain filter).
        threshold_fingerprint: SHA-256 fingerprint of the
            :class:`SuspensionThreshold` that produced this decision.
        decided_at: ISO-8601 UTC timestamp of the decision.
        suspension_days: Advisory duration from the threshold in effect.
    """

    agent_id: str
    suspended: bool
    reason: str
    score: float | None
    sample_count: int
    threshold_fingerprint: str
    decided_at: str
    suspension_days: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "suspended": self.suspended,
            "reason": self.reason,
            "score": self.score,
            "sample_count": self.sample_count,
            "threshold_fingerprint": self.threshold_fingerprint,
            "decided_at": self.decided_at,
            "suspension_days": self.suspension_days,
        }


class SuspensionChecker:
    """Apply a :class:`SuspensionThreshold` to an agent using a ReputationStore.

    The checker is always safe to construct. When the feature flag
    ``ARAGORA_REPUTATION_SUSPENSION_ENABLED`` is off, every call returns
    ``suspended=False`` with ``reason="flag_disabled"``; no agent is ever
    silently excluded.

    Usage::

        checker = SuspensionChecker()  # default threshold
        decision = checker.check("agent-id", store)
        if decision.suspended:
            ...  # exclude from dispatch

    Wiring into :class:`~aragora.debate.team_selector.TeamSelector` is
    deferred to a follow-on slice.
    """

    def __init__(self, *, threshold: SuspensionThreshold | None = None) -> None:
        self._threshold = threshold or SuspensionThreshold()

    def check(self, agent_id: str, store: "ReputationStore") -> SuspensionDecision:
        """Evaluate whether *agent_id* should be hard-suspended.

        Parameters
        ----------
        agent_id:
            Identifier for the agent to evaluate.
        store:
            The shared :class:`~aragora.reputation.store.ReputationStore`.
            Only public methods are used; no private attributes are accessed.
        """
        fp = self._threshold.fingerprint()
        now_iso = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
        susp_days = self._threshold.suspension_days

        def _make(
            *,
            suspended: bool,
            reason: str,
            score: float | None,
            sample_count: int,
        ) -> SuspensionDecision:
            return SuspensionDecision(
                agent_id=agent_id,
                suspended=suspended,
                reason=reason,
                score=score,
                sample_count=sample_count,
                threshold_fingerprint=fp,
                decided_at=now_iso,
                suspension_days=susp_days,
            )

        if not suspension_enabled():
            return _make(suspended=False, reason="flag_disabled", score=None, sample_count=0)

        all_deltas = store.deltas_for(agent_id)
        if not all_deltas:
            return _make(suspended=False, reason="no_data", score=None, sample_count=0)

        if self._threshold.domains is not None:
            relevant = [d for d in all_deltas if d.domain in self._threshold.domains]
        else:
            relevant = all_deltas

        sample_count = len(relevant)
        if sample_count == 0:
            return _make(suspended=False, reason="no_data", score=None, sample_count=0)

        if sample_count < self._threshold.min_samples:
            # Provide the raw score even though suspension cannot fire.
            raw_score = sum(d.delta for d in relevant)
            return _make(
                suspended=False,
                reason="insufficient_samples",
                score=raw_score,
                sample_count=sample_count,
            )

        # For all-domain path use the store's decay-weighted score.
        # For domain-filtered path sum raw deltas (decay not supported here).
        if self._threshold.domains is None:
            score = store.get_score(agent_id, apply_decay=True)
        else:
            score = sum(d.delta for d in relevant)

        if score >= self._threshold.score_floor:
            return _make(
                suspended=False,
                reason="score_above_floor",
                score=score,
                sample_count=sample_count,
            )

        return _make(
            suspended=True,
            reason="score_below_floor",
            score=score,
            sample_count=sample_count,
        )
