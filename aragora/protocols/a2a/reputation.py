"""A2A agent reputation read endpoint — AGT-02 / #6063 sub-deliverable 5.

Gate: ``ARAGORA_A2A_REPUTATION_ENABLED`` (default off). Dataclasses always
importable; read functions raise :class:`ReputationEndpointError` when off.

Read-only: deltas recorded only by AGT-05 settlement.
Out of scope: HTTP routes, pagination, on-chain ERC-8004 reads.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.reputation.store import ReputationStore

AGENT_REPUTATION_SCHEMA_VERSION = "1.0"
_FLAG = "ARAGORA_A2A_REPUTATION_ENABLED"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

__all__ = [
    "AGENT_REPUTATION_SCHEMA_VERSION",
    "AgentReputationView",
    "DomainReputationSlice",
    "ReputationEndpointError",
    "read_agent_reputation",
    "read_all_agents",
    "reputation_endpoint_enabled",
]


def reputation_endpoint_enabled() -> bool:
    return os.environ.get(_FLAG, "").strip().lower() in _TRUTHY


def _require_enabled() -> None:
    if not reputation_endpoint_enabled():
        raise ReputationEndpointError(
            f"A2A reputation endpoint is disabled; set {_FLAG}=1 to enable."
        )


class ReputationEndpointError(RuntimeError):
    """Raised when the read endpoint is called while the feature gate is off."""


@dataclass(frozen=True)
class DomainReputationSlice:
    """Per-domain reputation summary within an agent's track record."""

    domain: str
    score: float
    delta_count: int
    most_recent_delta_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "score": round(self.score, 6),
            "delta_count": self.delta_count,
            "most_recent_delta_at": self.most_recent_delta_at,
        }


@dataclass(frozen=True)
class AgentReputationView:
    """Agent-readable reputation summary for one agent."""

    agent_id: str
    schema_version: str
    overall_score: float
    delta_count: int
    domains: tuple[DomainReputationSlice, ...]
    queried_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "agent_id": self.agent_id,
            "overall_score": round(self.overall_score, 6),
            "delta_count": self.delta_count,
            "domains": [s.to_dict() for s in self.domains],
            "queried_at": self.queried_at,
        }


def _decay_weight(delta: Any, now: datetime) -> float:
    """Exponential half-life decay for one reputation delta.

    Mirrors the same function in :mod:`aragora.reputation.store` so this
    module does not need to import a private symbol.
    """
    half_life = getattr(delta, "decay_half_life_days", None)
    if half_life is None:
        return 1.0
    try:
        applied = datetime.fromisoformat(delta.applied_at.replace("Z", "+00:00")).astimezone(UTC)
    except (ValueError, TypeError):
        return 1.0
    age_days = max(0.0, (now - applied).total_seconds() / 86_400.0)
    return math.exp(-math.log(2.0) * age_days / half_life)


def _domain_slices(
    agent_id: str,
    store: "ReputationStore",
    *,
    apply_decay: bool,
    now: datetime,
) -> tuple[DomainReputationSlice, ...]:
    raw_deltas = store.deltas_for(agent_id)
    if not raw_deltas:
        return ()
    by_domain: dict[str, list[Any]] = {}
    for d in raw_deltas:
        by_domain.setdefault(d.domain, []).append(d)
    slices: list[DomainReputationSlice] = []
    for domain, deltas in sorted(by_domain.items()):
        score = (
            sum(d.delta * _decay_weight(d, now) for d in deltas)
            if apply_decay
            else sum(d.delta for d in deltas)
        )
        slices.append(
            DomainReputationSlice(
                domain=domain,
                score=score,
                delta_count=len(deltas),
                most_recent_delta_at=max((d.applied_at for d in deltas), default=None),
            )
        )
    return tuple(slices)


def read_agent_reputation(
    agent_id: str,
    store: "ReputationStore",
    *,
    apply_decay: bool = True,
    now: datetime | None = None,
) -> AgentReputationView:
    """Per-domain reputation view for *agent_id*; zero-score for unknown agents."""
    _require_enabled()
    reference = now or datetime.now(tz=UTC)
    return AgentReputationView(
        agent_id=agent_id,
        schema_version=AGENT_REPUTATION_SCHEMA_VERSION,
        overall_score=store.get_score(agent_id, apply_decay=apply_decay),
        delta_count=len(store.deltas_for(agent_id)),
        domains=_domain_slices(agent_id, store, apply_decay=apply_decay, now=reference),
        queried_at=reference.isoformat().replace("+00:00", "Z"),
    )


def read_all_agents(
    store: "ReputationStore",
    *,
    apply_decay: bool = True,
    now: datetime | None = None,
) -> list[AgentReputationView]:
    """Views for every agent in *store*, sorted descending by overall score."""
    _require_enabled()
    reference = now or datetime.now(tz=UTC)
    views = [
        read_agent_reputation(aid, store, apply_decay=apply_decay, now=reference)
        for aid in store.agent_ids()
    ]
    return sorted(views, key=lambda v: (-v.overall_score, v.agent_id))
