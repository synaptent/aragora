"""
Connection Leak Detector.

Tracks acquired connections from any pool and flags those held longer
than a configurable threshold.  Helps surface resource leaks that would
otherwise manifest as pool exhaustion under load.

Usage:
    from aragora.server.leak_detector import LeakDetector, get_leak_detector

    detector = get_leak_detector()

    # Wrap connection acquisition
    async with detector.track("postgres", conn_id="pg-42"):
        await conn.execute("SELECT 1")

    # Periodic check (e.g. from health endpoint)
    leaks = detector.get_suspected_leaks()
    for leak in leaks:
        logger.warning("Possible leak: %s held for %.1fs from %s",
                        leak.pool_name, leak.held_seconds, leak.caller)
"""

from __future__ import annotations

import logging
import os
import threading
import time
import traceback
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import Any
from collections.abc import AsyncIterator, Iterator

logger = logging.getLogger(__name__)

# Configurable via environment
DEFAULT_WARN_SECONDS = float(os.environ.get("ARAGORA_LEAK_WARN_SECONDS", "30"))
DEFAULT_CRITICAL_SECONDS = float(os.environ.get("ARAGORA_LEAK_CRITICAL_SECONDS", "120"))
MAX_TRACKED = int(os.environ.get("ARAGORA_LEAK_MAX_TRACKED", "5000"))


@dataclass
class AcquisitionRecord:
    """Record of a single connection acquisition."""

    pool_name: str
    conn_id: str
    acquired_at: float
    caller: str  # Short stack frame
    released: bool = False
    released_at: float | None = None

    @property
    def held_seconds(self) -> float:
        end = self.released_at if self.released_at is not None else time.time()
        return end - self.acquired_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "pool_name": self.pool_name,
            "conn_id": self.conn_id,
            "acquired_at": self.acquired_at,
            "held_seconds": round(self.held_seconds, 2),
            "caller": self.caller,
            "released": self.released,
        }


@dataclass
class LeakAlert:
    """Alert raised when a connection is held too long."""

    pool_name: str
    conn_id: str
    held_seconds: float
    caller: str
    level: str  # "warning" or "critical"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pool_name": self.pool_name,
            "conn_id": self.conn_id,
            "held_seconds": round(self.held_seconds, 2),
            "caller": self.caller,
            "level": self.level,
            "timestamp": self.timestamp,
        }


class LeakDetector:
    """Tracks connection acquisitions and flags suspected leaks.

    Thread-safe.  Can be used with any pool type (PostgreSQL, Redis, HTTP).

    Attributes:
        _active: Currently held (unreleased) connections.
        _alerts: Generated leak alerts.
    """

    def __init__(
        self,
        warn_seconds: float = DEFAULT_WARN_SECONDS,
        critical_seconds: float = DEFAULT_CRITICAL_SECONDS,
        max_tracked: int = MAX_TRACKED,
    ) -> None:
        self._warn_seconds = warn_seconds
        self._critical_seconds = critical_seconds
        self._max_tracked = max_tracked

        self._active: dict[str, AcquisitionRecord] = {}
        self._lock = threading.Lock()
        self._alerts: list[LeakAlert] = []
        self._counter = 0

        # Lifetime stats
        self._total_acquired = 0
        self._total_released = 0
        self._total_warn = 0
        self._total_critical = 0

    # ------------------------------------------------------------------
    # Public tracking API
    # ------------------------------------------------------------------

    def acquire(self, pool_name: str, conn_id: str | None = None) -> str:
        """Record that a connection was acquired.

        Args:
            pool_name: Logical pool name (e.g. "postgres", "redis").
            conn_id: Optional connection identifier.  Auto-generated if
                not provided.

        Returns:
            The connection ID used for tracking.
        """
        caller = _short_caller(skip=2)

        with self._lock:
            self._counter += 1
            cid = conn_id or f"{pool_name}-{self._counter}"
            self._total_acquired += 1

            # Enforce cap
            if len(self._active) >= self._max_tracked:
                self._evict_oldest()

            self._active[cid] = AcquisitionRecord(
                pool_name=pool_name,
                conn_id=cid,
                acquired_at=time.time(),
                caller=caller,
            )
            return cid

    def release(self, conn_id: str) -> None:
        """Record that a connection was released.

        Args:
            conn_id: The connection ID returned by :meth:`acquire`.
        """
        with self._lock:
            rec = self._active.pop(conn_id, None)
            if rec is not None:
                rec.released = True
                rec.released_at = time.time()
                self._total_released += 1

    @contextmanager
    def track(self, pool_name: str, conn_id: str | None = None) -> Iterator[str]:
        """Sync context manager that tracks acquire/release.

        Yields:
            The connection ID.
        """
        cid = self.acquire(pool_name, conn_id)
        try:
            yield cid
        finally:
            self.release(cid)

    @asynccontextmanager
    async def atrack(self, pool_name: str, conn_id: str | None = None) -> AsyncIterator[str]:
        """Async context manager that tracks acquire/release.

        Yields:
            The connection ID.
        """
        cid = self.acquire(pool_name, conn_id)
        try:
            yield cid
        finally:
            self.release(cid)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def check_leaks(self) -> list[LeakAlert]:
        """Scan active connections and generate alerts for suspected leaks.

        Returns:
            Newly generated alerts.
        """
        now = time.time()
        new_alerts: list[LeakAlert] = []

        with self._lock:
            for rec in self._active.values():
                held = now - rec.acquired_at
                if held >= self._critical_seconds:
                    alert = LeakAlert(
                        pool_name=rec.pool_name,
                        conn_id=rec.conn_id,
                        held_seconds=held,
                        caller=rec.caller,
                        level="critical",
                    )
                    new_alerts.append(alert)
                    self._total_critical += 1
                    logger.error(
                        "Connection leak CRITICAL: %s held %.1fs from %s",
                        rec.conn_id,
                        held,
                        rec.caller,
                    )
                elif held >= self._warn_seconds:
                    alert = LeakAlert(
                        pool_name=rec.pool_name,
                        conn_id=rec.conn_id,
                        held_seconds=held,
                        caller=rec.caller,
                        level="warning",
                    )
                    new_alerts.append(alert)
                    self._total_warn += 1
                    logger.warning(
                        "Connection leak WARNING: %s held %.1fs from %s",
                        rec.conn_id,
                        held,
                        rec.caller,
                    )

            self._alerts.extend(new_alerts)
            # Cap stored alerts
            if len(self._alerts) > 500:
                self._alerts = self._alerts[-250:]

        return new_alerts

    def get_suspected_leaks(self, threshold: float | None = None) -> list[AcquisitionRecord]:
        """Return active connections held longer than threshold.

        Args:
            threshold: Seconds threshold (default: warn_seconds).

        Returns:
            List of :class:`AcquisitionRecord` ordered by held time desc.
        """
        threshold = threshold or self._warn_seconds
        now = time.time()

        with self._lock:
            suspects = [
                rec for rec in self._active.values() if (now - rec.acquired_at) >= threshold
            ]
        return sorted(suspects, key=lambda r: r.held_seconds, reverse=True)

    def get_active_connections(self, pool_name: str | None = None) -> list[AcquisitionRecord]:
        """Return all active (unreleased) connections.

        Args:
            pool_name: Optional filter by pool name.
        """
        with self._lock:
            records = list(self._active.values())
        if pool_name:
            records = [r for r in records if r.pool_name == pool_name]
        return records

    def get_stats(self) -> dict[str, Any]:
        """Return detector statistics."""
        with self._lock:
            active_by_pool: dict[str, int] = {}
            for rec in self._active.values():
                active_by_pool[rec.pool_name] = active_by_pool.get(rec.pool_name, 0) + 1

            return {
                "total_acquired": self._total_acquired,
                "total_released": self._total_released,
                "currently_active": len(self._active),
                "active_by_pool": active_by_pool,
                "total_warn_alerts": self._total_warn,
                "total_critical_alerts": self._total_critical,
                "alert_count": len(self._alerts),
                "warn_threshold_seconds": self._warn_seconds,
                "critical_threshold_seconds": self._critical_seconds,
            }

    def get_alerts(self, since: float | None = None) -> list[LeakAlert]:
        """Return stored alerts, optionally filtered by time."""
        with self._lock:
            if since is None:
                return list(self._alerts)
            return [a for a in self._alerts if a.timestamp > since]

    def reset(self) -> None:
        """Reset all tracking state."""
        with self._lock:
            self._active.clear()
            self._alerts.clear()
            self._counter = 0
            self._total_acquired = 0
            self._total_released = 0
            self._total_warn = 0
            self._total_critical = 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _evict_oldest(self) -> None:
        """Remove the oldest active record to stay under the cap."""
        if not self._active:
            return
        oldest_key = min(self._active, key=lambda k: self._active[k].acquired_at)
        del self._active[oldest_key]


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

_detector: LeakDetector | None = None


def get_leak_detector() -> LeakDetector:
    """Get or create the global leak detector."""
    global _detector
    if _detector is None:
        _detector = LeakDetector()
    return _detector


def reset_leak_detector() -> None:
    """Reset the global leak detector (for testing)."""
    global _detector
    _detector = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short_caller(skip: int = 2) -> str:
    """Return a short description of the calling code location.

    Args:
        skip: Number of stack frames to skip (default skips this fn + caller).
    """
    try:
        stack = traceback.extract_stack()
        # Walk back past internal frames
        idx = max(0, len(stack) - skip - 1)
        frame = stack[idx]
        return f"{frame.filename.rsplit('/', 1)[-1]}:{frame.lineno} in {frame.name}"
    except (IndexError, ValueError, AttributeError) as e:
        logger.debug("Failed to extract caller info: %s: %s", type(e).__name__, e)
        return "unknown"


__all__ = [
    "AcquisitionRecord",
    "LeakAlert",
    "LeakDetector",
    "get_leak_detector",
    "reset_leak_detector",
]
