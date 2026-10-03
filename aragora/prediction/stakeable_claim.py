"""StakeableClaim — core data model for AGT-04 synthetic GitHub prediction markets.

A StakeableClaim represents one time-bounded predictive question about a
publicly observable GitHub event (PR merge, issue close, CI pass).  Agents
record probability estimates; the store resolves claims when the event occurs
or expires.

All symbols are importable without the feature flag.  Only
:class:`InMemoryStakeableClaimStore` methods that mutate or query state raise
:exc:`RuntimeError` when the flag is off, so unit tests can import freely.

Feature flag: ``ARAGORA_PREDICTION_MARKETS_ENABLED`` (env var, default OFF).

This module deliberately does NOT:
- call the GitHub API (that belongs in a concrete resolution adapter)
- touch the live dispatch queue or boss loop
- import from ``aragora.blockchain`` (reputation wiring is AGT-05)

Advances: issue #6065 (AGT-04), sub-deliverable 1 — synthetic market schema.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Feature gate
# ---------------------------------------------------------------------------

_ENV_FLAG = "ARAGORA_PREDICTION_MARKETS_ENABLED"


def _flag_enabled() -> bool:
    return os.environ.get(_ENV_FLAG, "").lower() in {"1", "true", "yes", "on"}


def _require_enabled() -> None:
    if not _flag_enabled():
        raise RuntimeError(f"Prediction markets are disabled. Set {_ENV_FLAG}=1 to enable.")


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class QuestionType(str, Enum):
    """Shapes of GitHub events that can be predicted."""

    PR_MERGE = "pr_merge"
    ISSUE_CLOSE = "issue_close"
    CI_PASS = "ci_pass"
    DEPENDENCY_RELEASE = "dependency_release"


class ResolutionStatus(str, Enum):
    """Lifecycle state of a stakeable claim."""

    OPEN = "open"
    RESOLVED_YES = "resolved_yes"
    RESOLVED_NO = "resolved_no"
    EXPIRED = "expired"
    INCONCLUSIVE = "inconclusive"


# ---------------------------------------------------------------------------
# Core data model
# ---------------------------------------------------------------------------


@dataclass
class StakeableClaim:
    """One time-bounded predictive claim about a GitHub event.

    Attributes:
        claim_id: Stable opaque identifier (caller-assigned).
        question: Human-readable prediction question.
        question_type: Event category.
        target_ref: ``owner/repo#number`` or ``owner/repo@branch``.
        expiry: ISO-8601 UTC datetime — claim expires if unresolved by this time.
        resolution_window_days: How many days from creation until resolution expected.
        resolution_status: Lifecycle state (starts OPEN).
        resolution_value: ``True``/``False`` once resolved, ``None`` otherwise.
        resolution_evidence: Free-text rationale for the resolution decision.
        positions: ``{agent_id: probability}`` — agent probability estimates (0–1).
        credit_cap: Max internal credits any single agent may stake (default 100).
        created_at: ISO-8601 UTC creation timestamp.
    """

    claim_id: str
    question: str
    question_type: QuestionType
    target_ref: str
    expiry: str
    resolution_window_days: int = 30
    resolution_status: ResolutionStatus = ResolutionStatus.OPEN
    resolution_value: bool | None = None
    resolution_evidence: str = ""
    positions: dict[str, float] = field(default_factory=dict)
    credit_cap: int = 100
    created_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())

    def is_open(self) -> bool:
        return self.resolution_status == ResolutionStatus.OPEN

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "question": self.question,
            "question_type": self.question_type.value,
            "target_ref": self.target_ref,
            "expiry": self.expiry,
            "resolution_window_days": self.resolution_window_days,
            "resolution_status": self.resolution_status.value,
            "resolution_value": self.resolution_value,
            "resolution_evidence": self.resolution_evidence,
            "positions": dict(self.positions),
            "credit_cap": self.credit_cap,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------


class InMemoryStakeableClaimStore:
    """Thread-unsafe in-memory store for :class:`StakeableClaim` objects.

    Suitable for unit tests and local development.  A durable implementation
    backed by ``aragora/storage/`` is a follow-on slice.

    All mutating methods raise :exc:`RuntimeError` when the feature flag is
    off, so callers cannot silently bypass the gate.
    """

    def __init__(self) -> None:
        self._claims: dict[str, StakeableClaim] = {}

    # -- write --

    def add(self, claim: StakeableClaim) -> None:
        """Add *claim* to the store. Raises if the ID already exists."""
        _require_enabled()
        if claim.claim_id in self._claims:
            raise ValueError(f"Claim {claim.claim_id!r} already exists.")
        self._claims[claim.claim_id] = claim

    def record_position(self, claim_id: str, agent_id: str, probability: float) -> None:
        """Record agent probability estimate for an open claim."""
        _require_enabled()
        if not 0.0 <= probability <= 1.0:
            raise ValueError(f"probability must be in [0, 1], got {probability!r}")
        claim = self._get_open(claim_id)
        claim.positions[agent_id] = probability

    def resolve(
        self,
        claim_id: str,
        value: bool,
        evidence: str = "",
    ) -> StakeableClaim:
        """Mark a claim as resolved YES/NO with optional evidence text.

        Only OPEN claims may transition to a terminal state: the
        ``_get_open`` check followed immediately by the status write below
        is the compare-and-swap guard against double settlement (this
        in-memory store is single-threaded, so check-then-set is atomic
        with respect to other store calls).  If the sweeper already voided
        the claim, this raises ``ValueError`` and the EXPIRED state is
        never resurrected.
        """
        _require_enabled()
        claim = self._get_open(claim_id)
        claim.resolution_status = (
            ResolutionStatus.RESOLVED_YES if value else ResolutionStatus.RESOLVED_NO
        )
        claim.resolution_value = value
        claim.resolution_evidence = evidence
        return claim

    def expire_stale(
        self,
        before_dt: datetime | None = None,
        grace: timedelta | float | int = timedelta(hours=24),
    ) -> list[str]:
        """Mark OPEN claims whose ``expiry + grace`` precedes *before_dt* as EXPIRED.

        Finality is processing-time bounded (adjudicated design, PR #8519):
        a claim is voided only once its expiry *plus* a per-claim grace
        window has passed.  The grace window exists because GitHub webhook
        deliveries can lag or be redelivered hours after the underlying
        event occurred — an in-window event delivered late must still be
        able to resolve the claim before the sweeper voids it.

        Args:
            before_dt: Processing-time cutoff (defaults to now, UTC).
            grace: Grace window applied per claim — a ``timedelta`` or a
                number of seconds.  Defaults to 24 hours.

        Only OPEN claims transition to EXPIRED; already-settled claims are
        skipped, so a resolve-then-sweep race no-ops here.

        Returns the list of expired claim IDs.
        """
        _require_enabled()
        if not isinstance(grace, timedelta):
            grace = timedelta(seconds=float(grace))
        if grace < timedelta(0):
            raise ValueError(f"grace must be non-negative, got {grace!r}")
        cutoff = before_dt or datetime.now(tz=UTC)
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=UTC)
        expired_ids: list[str] = []
        for claim in self._claims.values():
            if claim.resolution_status != ResolutionStatus.OPEN:
                continue
            exp_dt = _parse_datetime(claim.expiry)
            if exp_dt is None:
                # Quarantine, never a silent skip (#8777): a malformed expiry
                # can neither qualify events (resolver fails closed on it) nor
                # ever sweep, so skipping leaves a permanent zombie claim.
                claim.resolution_status = ResolutionStatus.EXPIRED
                expired_ids.append(claim.claim_id)
                logger.warning(
                    "prediction.expire_stale: claim %s has malformed expiry %r; "
                    "quarantined as EXPIRED (#8777)",
                    claim.claim_id,
                    claim.expiry,
                )
                continue
            if exp_dt + grace < cutoff:
                claim.resolution_status = ResolutionStatus.EXPIRED
                expired_ids.append(claim.claim_id)
        return expired_ids

    # -- read --

    def get(self, claim_id: str) -> StakeableClaim:
        _require_enabled()
        try:
            return self._claims[claim_id]
        except KeyError:
            raise KeyError(f"Unknown claim {claim_id!r}") from None

    def list_open(self) -> list[StakeableClaim]:
        _require_enabled()
        return [c for c in self._claims.values() if c.is_open()]

    def list_by_type(self, question_type: QuestionType) -> list[StakeableClaim]:
        _require_enabled()
        return [c for c in self._claims.values() if c.question_type == question_type]

    def all(self) -> list[StakeableClaim]:
        _require_enabled()
        return list(self._claims.values())

    def __len__(self) -> int:
        _require_enabled()
        return len(self._claims)

    # -- internal --

    def _get_open(self, claim_id: str) -> StakeableClaim:
        claim = self._claims.get(claim_id)
        if claim is None:
            raise KeyError(f"Unknown claim {claim_id!r}")
        if not claim.is_open():
            raise ValueError(f"Claim {claim_id!r} is already {claim.resolution_status.value}.")
        return claim


# ---------------------------------------------------------------------------
# Resolution adapter stub
# ---------------------------------------------------------------------------


class GithubResolutionAdapterStub:
    """Stub for the GitHub-event resolution adapter.

    Declares the interface that a concrete adapter will implement (e.g. via
    PyGithub or the GitHub REST API).  This stub exists so AGT-05 can type-
    check against the interface without requiring a live GitHub token.

    A concrete adapter is the next sub-deliverable of AGT-04 (sub-deliverable
    2: automatic GitHub-event resolution).
    """

    SUPPORTED_TYPES: frozenset[QuestionType] = frozenset(
        {QuestionType.PR_MERGE, QuestionType.ISSUE_CLOSE, QuestionType.CI_PASS}
    )

    def can_resolve(self, claim: StakeableClaim) -> bool:
        """Return True if this adapter supports the claim's question type."""
        return claim.question_type in self.SUPPORTED_TYPES

    def resolve(self, claim: StakeableClaim) -> tuple[bool, str]:  # pragma: no cover
        """Resolve *claim* against the live GitHub API.

        Not implemented in this stub — raises :exc:`NotImplementedError`.
        The concrete adapter lives in a follow-on slice.
        """
        raise NotImplementedError(
            "GithubResolutionAdapterStub.resolve is a placeholder. "
            "Implement a concrete adapter in the next AGT-04 sub-deliverable."
        )
