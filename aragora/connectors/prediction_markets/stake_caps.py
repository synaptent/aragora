"""Per-market stake-cap graduation for the Manifold write path (AGT-03).

AGT-03 sub-deliverable 5 (issue #6064, plan
``docs/plans/2026-04-17-prediction-market-validation.md``): the per-market cap
starts at 50 mana and rises to 200 mana after 30 days of stable behaviour.
"Stable" means an uninterrupted run with no incident (a cap violation or a
venue write error); an incident restarts the clock at the incident time.

Default OFF: unless ``ARAGORA_MANIFOLD_CAP_GRADUATION_ENABLED`` is truthy the
effective cap is always the initial cap, so existing behaviour is unchanged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

CAP_GRADUATION_FLAG = "ARAGORA_MANIFOLD_CAP_GRADUATION_ENABLED"


def cap_graduation_enabled() -> bool:
    """Return True when ARAGORA_MANIFOLD_CAP_GRADUATION_ENABLED is truthy."""
    raw = str(os.environ.get(CAP_GRADUATION_FLAG) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)  # naive == UTC


def _now(now: datetime | None) -> datetime:
    return _aware(now) if now is not None else datetime.now(tz=UTC)


@dataclass
class StabilityRecord:
    """Successful bets and incidents (failed attempts) on the write path."""

    first_bet_at: datetime | None = None
    last_incident_at: datetime | None = None
    bets: int = 0
    incidents: int = 0

    def record_bet(self, *, now: datetime | None = None) -> None:
        when = _now(now)
        if self.first_bet_at is None:
            self.first_bet_at = when
        self.bets += 1

    def record_incident(self, *, now: datetime | None = None) -> None:
        self.last_incident_at = _now(now)
        self.incidents += 1

    def stable_since(self) -> datetime | None:
        """Start of the current uninterrupted stable run, or None before any bet."""
        if self.first_bet_at is None:
            return None
        first = _aware(self.first_bet_at)
        if self.last_incident_at is None:
            return first
        return max(first, _aware(self.last_incident_at))

    def stable_for(self, *, now: datetime | None = None) -> timedelta | None:
        since = self.stable_since()
        if since is None:
            return None
        return max(_now(now) - since, timedelta(0))


@dataclass(frozen=True)
class StakeCapSchedule:
    """Two-step per-market cap: ``initial`` until stable for ``stability_period_days``."""

    initial_cap_mana: int = 50
    graduated_cap_mana: int = 200
    stability_period_days: int = 30

    def __post_init__(self) -> None:
        if self.initial_cap_mana < 1 or self.stability_period_days < 1:
            raise ValueError("initial_cap_mana and stability_period_days must be >= 1")
        if self.graduated_cap_mana < self.initial_cap_mana:
            raise ValueError("graduated_cap_mana must be >= initial_cap_mana")

    def is_graduated(self, record: StabilityRecord, *, now: datetime | None = None) -> bool:
        stable_for = record.stable_for(now=now)
        if stable_for is None:
            return False
        return stable_for >= timedelta(days=self.stability_period_days)

    def effective_per_market_cap(
        self, record: StabilityRecord, *, now: datetime | None = None
    ) -> int:
        """Cap to enforce right now. Always ``initial_cap_mana`` while the flag is off."""
        if not cap_graduation_enabled():
            return self.initial_cap_mana
        if self.is_graduated(record, now=now):
            return self.graduated_cap_mana
        return self.initial_cap_mana


__all__ = ["CAP_GRADUATION_FLAG", "StabilityRecord", "StakeCapSchedule", "cap_graduation_enabled"]
