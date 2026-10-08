"""The worker contract: what a dispatch receives and what it hands back.

Kept in a leaf that depends only on :mod:`aragora.missions.state` so both the
orchestrator (which consumes handoffs) and the swarm (which produces them from
fenced workers) can share the types without importing each other.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .state import Feature

__all__ = ["Dispatch", "Handoff"]


@dataclass
class Handoff:
    """What a worker returns. The orchestrator must dispose of every field.

    ``success`` advances the feature; ``follow_ups`` are worker-proposed queue
    extensions; ``blocked_reason`` records why it failed. Proposed follow-ups are
    advisory by default. A dispatch must set ``accept_follow_ups=True`` to make them
    executable, so a buggy worker cannot silently widen mission scope. ``terminal``
    distinguishes a block that **cannot self-heal by retrying** (operator-gated,
    Tier-3, a contaminated branch needing re-derive) from a transient one — a
    structured flag instead of sniffing the reason string, so the orchestrator and
    swarm agree. ``awaiting_claim`` is a third disposition (#8758): the feature is
    real work this dispatch cannot drive at all — it needs a *worker* to claim it
    (``Status.AWAITING_CLAIM``, claimable by ``ledger.select_for``) — so triage
    parks it claimable with **no retry accounting** instead of failing it toward
    BLOCKED. ``parked`` is the fourth disposition (#8758 design decision,
    2026-07-02): "not ready yet", never "dead" — triage moves the feature to the
    retryable, reconciler-owned ``Status.PARKED`` (recording
    ``parked_reason``/``parked_at``) instead of blocking it; ``parked_kind``
    says why (``PARK_KIND_MISSING_BRANCH`` waits for a live ``metadata.branch``,
    ``PARK_KIND_DECOMPOSITION`` is retry-bounded by ``retry_count`` → TERMINAL
    after ``max_retries`` attempts).
    """

    success: bool = False
    terminal: bool = False  # True = do not retry; park/block immediately
    awaiting_claim: bool = False  # True = park claimable (AWAITING_CLAIM), no retry burn
    parked: bool = False  # True = park retryably (PARKED); reconciler-owned exit
    parked_kind: str | None = None  # PARK_KIND_* — what the reconciler re-verifies
    blocked_reason: str | None = None
    follow_ups: list[Feature] = field(default_factory=list)
    accept_follow_ups: bool = False
    discovered: list[str] = field(default_factory=list)  # tracked into notes/library
    session_id: str | None = None


# A dispatch takes the feature to work and returns a Handoff. It must be
# idempotent: a feature retried after a crash must converge to the same result.
Dispatch = Callable[[Feature], Handoff]
