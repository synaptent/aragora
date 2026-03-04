"""File-based event bus for multi-agent coordination.

Agents publish events as JSON files in ``.aragora_coordination/events/``.
Other agents poll for new events by reading the directory.  No Redis, no
long-running server — just the filesystem.

Usage::

    from aragora.coordination.bus import CoordinationBus

    bus = CoordinationBus(repo_path=Path("."))
    bus.publish("session_started", {"agent": "claude", "worktree": "/tmp/wt1"})
    events = bus.poll(since=last_seen)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

_COORD_DIR = ".aragora_coordination"
_EVENTS_DIR = "events"


@dataclass(frozen=True)
class CoordinationEvent:
    """A single coordination event."""

    event_id: str
    event_type: str
    payload: dict[str, object]
    timestamp: float
    source_session: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> CoordinationEvent:
        return cls(
            event_id=str(data.get("event_id", "")),
            event_type=str(data.get("event_type", "")),
            payload=dict(data.get("payload", {})),  # type: ignore[arg-type]
            timestamp=float(data.get("timestamp", 0)),
            source_session=str(data.get("source_session", "")),
        )


class CoordinationBus:
    """File-backed event bus for agent coordination.

    Events are stored as individual JSON files named ``{timestamp}-{uuid}.json``
    for natural chronological ordering via ``sorted(glob(...))``.
    """

    def __init__(
        self,
        repo_path: Path | None = None,
        *,
        max_event_age_seconds: int = 3600,
        source_session: str = "",
    ):
        self.repo_path = (repo_path or Path.cwd()).resolve()
        self._events_dir = self.repo_path / _COORD_DIR / _EVENTS_DIR
        self._max_age = max_event_age_seconds
        self._source_session = source_session

    def _ensure_dir(self) -> Path:
        self._events_dir.mkdir(parents=True, exist_ok=True)
        return self._events_dir

    def publish(
        self,
        event_type: str,
        payload: dict[str, object] | None = None,
        *,
        source_session: str | None = None,
    ) -> CoordinationEvent:
        """Publish an event to the bus.

        Returns the created event.
        """
        now = time.time()
        event = CoordinationEvent(
            event_id=str(uuid4())[:12],
            event_type=event_type,
            payload=payload or {},
            timestamp=now,
            source_session=source_session or self._source_session,
        )

        d = self._ensure_dir()
        # Filename encodes timestamp for natural sort order
        filename = f"{now:.6f}-{event.event_id}.json"
        path = d / filename

        path.write_text(json.dumps(event.to_dict(), default=str), encoding="utf-8")
        logger.debug("event_published type=%s id=%s", event_type, event.event_id)
        return event

    def poll(
        self,
        *,
        since: float = 0.0,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[CoordinationEvent]:
        """Poll for events newer than *since* (epoch timestamp).

        Args:
            since: Only return events with timestamp > since.
            event_type: Filter to a specific event type.
            limit: Max events to return.

        Returns:
            Events in chronological order.
        """
        if not self._events_dir.exists():
            return []

        events: list[CoordinationEvent] = []
        for path in sorted(self._events_dir.glob("*.json")):
            if len(events) >= limit:
                break
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                ev = CoordinationEvent.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                logger.debug("skipping_corrupt_event path=%s", path)
                continue

            if ev.timestamp <= since:
                continue
            if event_type and ev.event_type != event_type:
                continue
            events.append(ev)

        return events

    def cleanup(self, *, max_age: int | None = None) -> int:
        """Remove events older than *max_age* seconds. Returns count removed."""
        if not self._events_dir.exists():
            return 0

        cutoff = time.time() - (max_age if max_age is not None else self._max_age)
        removed = 0

        for path in self._events_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                ts = float(data.get("timestamp", 0))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                ts = 0.0

            if ts < cutoff:
                path.unlink(missing_ok=True)
                removed += 1

        if removed:
            logger.debug("events_cleaned count=%d", removed)
        return removed

    def clear(self) -> int:
        """Remove all events. Returns count removed."""
        if not self._events_dir.exists():
            return 0
        removed = 0
        for path in self._events_dir.glob("*.json"):
            path.unlink(missing_ok=True)
            removed += 1
        return removed


__all__ = [
    "CoordinationBus",
    "CoordinationEvent",
]
