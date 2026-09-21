"""Three-axis epistemic tags: knowledge state x provenance authority x disposition.

A single confidence scalar hides the difference between "we checked and it is
false", "we have not checked", "two authorities disagree", and "we are not
allowed to see it". Agent-facing read models (orientation envelopes, work
recommendations, situation frames) tag every derived record on three
orthogonal axes instead.

``ProvenanceClass`` is an *authority class* used for precedence decisions.
It is deliberately distinct from ``aragora.reasoning.provenance.SourceType``,
which records the channel a piece of evidence arrived through (web search,
document, database, ...). A fact can be ``SourceType.EXTERNAL_API`` and
``ProvenanceClass.OBSERVED`` at the same time.

Tagging convention: a deterministic computation that is exactly reproducible
from its anchored inputs (e.g. repo cleanliness computed from ``git status``)
may keep ``OBSERVED``; anything involving model inference, heuristics, or
sampling must be ``DERIVED`` or ``PREDICTED``. Summaries never gain authority:
``reconcile`` always resolves value disputes toward the lower rank.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "AUTHORITY_RANK",
    "EpistemicTag",
    "HypothesisDisposition",
    "KnowledgeState",
    "ProvenanceClass",
    "reconcile",
]


class KnowledgeState(str, Enum):
    """What the system can currently say about a fact."""

    KNOWN = "known"  # positively established from an authoritative source
    ESTIMATED = "estimated"  # best-effort value with quantified uncertainty
    UNKNOWN = "unknown"  # not yet queried
    CONFLICTED = "conflicted"  # authorities disagree; must not be treated as settled
    STALE = "stale"  # was known/estimated, validity window has lapsed
    NOT_OBSERVABLE = "not_observable"  # source unavailable or unhealthy
    REDACTED = "redacted"  # withheld by security/tenancy policy
    INDETERMINATE = "indeterminate"  # queried, but the source could not decide
    NOT_APPLICABLE = "not_applicable"  # the question does not apply here


class ProvenanceClass(str, Enum):
    """Authority class of the producer, ordered by ``AUTHORITY_RANK``."""

    OBSERVED = "observed"  # exact git/API/lease/halt facts
    OPERATOR_ASSERTED = "operator_asserted"  # human settlement or steering
    POLICY = "policy"  # operating contract / configuration
    REMEMBERED = "remembered"  # KM / continuum / supermemory recall
    VENDOR_CLAIMED = "vendor_claimed"  # third-party self-reports
    DERIVED = "derived"  # computed joins, model analysis
    PREDICTED = "predicted"  # forecasts


AUTHORITY_RANK: dict[ProvenanceClass, int] = {
    ProvenanceClass.OBSERVED: 0,
    ProvenanceClass.OPERATOR_ASSERTED: 1,
    ProvenanceClass.POLICY: 1,
    ProvenanceClass.REMEMBERED: 2,
    ProvenanceClass.VENDOR_CLAIMED: 3,
    ProvenanceClass.DERIVED: 4,
    ProvenanceClass.PREDICTED: 5,
}


class HypothesisDisposition(str, Enum):
    """Where a competing interpretation currently stands."""

    LIVE = "live"  # still on the table, undecided
    SUPPORTED = "supported"  # evidence favors it
    DISFAVORED = "disfavored"  # evidence weighs against it, not eliminated
    REFUTED = "refuted"  # positively eliminated by evidence
    SUPERSEDED = "superseded"  # replaced by a sharper hypothesis


_DECAYABLE = frozenset({KnowledgeState.KNOWN, KnowledgeState.ESTIMATED})


@dataclass(slots=True)
class EpistemicTag:
    """Per-record tag carrying all three axes plus freshness and basis."""

    state: KnowledgeState
    provenance: ProvenanceClass
    disposition: HypothesisDisposition | None = None
    observed_at: float | None = None  # epoch seconds
    ttl_seconds: float | None = None
    basis: list[str] = field(default_factory=list)  # evidence refs / fingerprints

    def authority_rank(self) -> int:
        return AUTHORITY_RANK[self.provenance]

    def effective_state(self, now: float) -> KnowledgeState:
        """State after applying freshness decay.

        Only positive states decay to STALE; CONFLICTED, REDACTED and friends
        never silently improve or change through the passage of time.
        """
        if (
            self.state in _DECAYABLE
            and self.observed_at is not None
            and self.ttl_seconds is not None
            and now > self.observed_at + self.ttl_seconds
        ):
            return KnowledgeState.STALE
        return self.state

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "provenance": self.provenance.value,
            "disposition": self.disposition.value if self.disposition else None,
            "observed_at": self.observed_at,
            "ttl_seconds": self.ttl_seconds,
            "basis": list(self.basis),
        }


def reconcile(
    claimed_value: object,
    claimed: EpistemicTag,
    live_value: object,
    live: EpistemicTag,
) -> tuple[object, EpistemicTag]:
    """Resolve a claimed value against a live fact.

    The higher-authority side supplies the value. When the values disagree the
    resulting tag is CONFLICTED (carrying both bases) so no consumer can treat
    the claim as settled: a lower-authority recommendation can never override
    a higher-authority blocker, and the contradiction stays visible. At equal
    authority rank the live side wins the tie and supplies the value. The
    CONFLICTED tag intentionally resets ``observed_at``, ``ttl_seconds``, and
    ``disposition`` to their defaults — the conflict itself is a fresh finding,
    not an aging of either input fact.
    """
    if live.authority_rank() <= claimed.authority_rank():
        winner_value, winner, loser = live_value, live, claimed
    else:
        winner_value, winner, loser = claimed_value, claimed, live

    if claimed_value == live_value:
        return winner_value, winner
    return winner_value, EpistemicTag(
        state=KnowledgeState.CONFLICTED,
        provenance=winner.provenance,
        basis=[*winner.basis, *loser.basis],
    )
