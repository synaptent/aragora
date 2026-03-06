"""
Debate SLA Monitor - SLA Tracking for Debate Channels.

Monitors debate response and resolution SLAs, detects violations,
and supports pluggable violation handlers for escalation.

Usage:
    from aragora.services.debate_sla_monitor import DebateChannelSLAMonitor

    monitor = DebateChannelSLAMonitor()
    violation = monitor.check_debate_sla("debate-1", created_at)
    at_risk = monitor.get_at_risk_debates(debates, threshold_minutes=5)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)


@dataclass
class DebateSLAConfig:
    """SLA configuration for debate channels."""

    response_sla_minutes: int = 15
    resolution_sla_minutes: int = 60
    escalation_rules: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DebateSLAViolation:
    """A detected debate SLA violation."""

    debate_id: str
    violation_type: str  # "RESPONSE" or "RESOLUTION"
    sla_minutes: int
    actual_minutes: float
    breached_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "debate_id": self.debate_id,
            "violation_type": self.violation_type,
            "sla_minutes": self.sla_minutes,
            "actual_minutes": self.actual_minutes,
            "breached_at": self.breached_at,
        }


class DebateChannelSLAMonitor:
    """
    SLA monitoring for debate channels.

    Tracks debate response and resolution SLAs, detects violations,
    and dispatches to registered violation handlers.
    """

    def __init__(self, config: DebateSLAConfig | None = None) -> None:
        self._config = config or DebateSLAConfig()
        self._violation_handlers: list[Callable[[DebateSLAViolation], None]] = []

    @property
    def config(self) -> DebateSLAConfig:
        """Current SLA configuration."""
        return self._config

    def check_debate_sla(
        self,
        debate_id: str,
        created_at: datetime,
        completed_at: datetime | None = None,
    ) -> DebateSLAViolation | None:
        """
        Check whether a debate has violated its SLA.

        Checks resolution SLA first (if completed), then response SLA
        (time from creation to now for open debates).

        Args:
            debate_id: Unique debate identifier.
            created_at: When the debate was created.
            completed_at: When the debate was completed (None if still open).

        Returns:
            A DebateSLAViolation if breached, otherwise None.
        """
        now = datetime.now(timezone.utc)

        # Ensure created_at is timezone-aware
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        # Check resolution SLA (completed debates)
        if completed_at is not None:
            if completed_at.tzinfo is None:
                completed_at = completed_at.replace(tzinfo=timezone.utc)
            elapsed = (completed_at - created_at).total_seconds() / 60.0
            if elapsed > self._config.resolution_sla_minutes:
                breached_at = created_at + timedelta(minutes=self._config.resolution_sla_minutes)
                violation = DebateSLAViolation(
                    debate_id=debate_id,
                    violation_type="RESOLUTION",
                    sla_minutes=self._config.resolution_sla_minutes,
                    actual_minutes=round(elapsed, 2),
                    breached_at=breached_at.isoformat(),
                )
                self._dispatch_violation(violation)
                return violation
            return None

        # Check response SLA (open debates)
        elapsed = (now - created_at).total_seconds() / 60.0
        if elapsed > self._config.response_sla_minutes:
            breached_at = created_at + timedelta(minutes=self._config.response_sla_minutes)
            violation = DebateSLAViolation(
                debate_id=debate_id,
                violation_type="RESPONSE",
                sla_minutes=self._config.response_sla_minutes,
                actual_minutes=round(elapsed, 2),
                breached_at=breached_at.isoformat(),
            )
            self._dispatch_violation(violation)
            return violation

        return None

    def get_at_risk_debates(
        self,
        debates: list[dict[str, Any]],
        threshold_minutes: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Identify debates approaching SLA breach.

        A debate is at risk when it is still open and the elapsed time is
        within ``threshold_minutes`` of the response SLA limit.

        Args:
            debates: List of debate dicts with ``id`` and ``created_at`` keys.
            threshold_minutes: Minutes before breach to consider "at risk".

        Returns:
            Filtered list of at-risk debate dicts with ``minutes_remaining``.
        """
        now = datetime.now(timezone.utc)
        at_risk: list[dict[str, Any]] = []

        for debate in debates:
            created_at = self._parse_datetime(debate.get("created_at"))
            if created_at is None:
                continue

            # Skip completed debates
            if debate.get("completed_at") is not None:
                continue

            deadline = created_at + timedelta(minutes=self._config.response_sla_minutes)
            remaining = (deadline - now).total_seconds() / 60.0

            if 0 < remaining <= threshold_minutes:
                entry = dict(debate)
                entry["minutes_remaining"] = round(remaining, 2)
                at_risk.append(entry)

        # Most urgent first
        at_risk.sort(key=lambda d: d.get("minutes_remaining", 0))
        return at_risk

    def register_violation_handler(self, handler: Callable[[DebateSLAViolation], None]) -> None:
        """Register a callback invoked on every SLA violation."""
        self._violation_handlers.append(handler)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dispatch_violation(self, violation: DebateSLAViolation) -> None:
        """Dispatch violation to all registered handlers."""
        for handler in self._violation_handlers:
            try:
                handler(violation)
            except (RuntimeError, TypeError, ValueError) as exc:
                logger.warning("[DebateSLAMonitor] Violation handler failed: %s", exc)

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        """Parse datetime from string or datetime object."""
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                return None
        return None


__all__ = [
    "DebateChannelSLAMonitor",
    "DebateSLAConfig",
    "DebateSLAViolation",
]
