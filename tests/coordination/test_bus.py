"""Tests for the file-based coordination event bus."""

from __future__ import annotations

import json
import time

import pytest

from aragora.coordination.bus import CoordinationBus, CoordinationEvent


class TestCoordinationEvent:
    def test_roundtrip(self):
        ev = CoordinationEvent(
            event_id="abc123",
            event_type="session_started",
            payload={"agent": "claude"},
            timestamp=1000.0,
            source_session="claude-1",
        )
        data = ev.to_dict()
        restored = CoordinationEvent.from_dict(data)
        assert restored.event_id == "abc123"
        assert restored.event_type == "session_started"
        assert restored.payload == {"agent": "claude"}
        assert restored.source_session == "claude-1"

    def test_from_dict_defaults(self):
        ev = CoordinationEvent.from_dict({})
        assert ev.event_id == ""
        assert ev.timestamp == 0.0


class TestCoordinationBus:
    def test_publish_creates_file(self, tmp_path):
        bus = CoordinationBus(repo_path=tmp_path)
        ev = bus.publish("test_event", {"key": "value"})

        events_dir = tmp_path / ".aragora_coordination" / "events"
        files = list(events_dir.glob("*.json"))
        assert len(files) == 1

        data = json.loads(files[0].read_text())
        assert data["event_type"] == "test_event"
        assert data["payload"]["key"] == "value"
        assert data["event_id"] == ev.event_id

    def test_poll_returns_events_in_order(self, tmp_path):
        bus = CoordinationBus(repo_path=tmp_path)
        bus.publish("ev1", {"order": 1})
        bus.publish("ev2", {"order": 2})
        bus.publish("ev3", {"order": 3})

        events = bus.poll()
        assert len(events) == 3
        assert events[0].event_type == "ev1"
        assert events[2].event_type == "ev3"

    def test_poll_since_filters(self, tmp_path):
        bus = CoordinationBus(repo_path=tmp_path)
        ev1 = bus.publish("old", {})
        ev2 = bus.publish("new", {})

        events = bus.poll(since=ev1.timestamp)
        assert len(events) == 1
        assert events[0].event_type == "new"

    def test_poll_event_type_filter(self, tmp_path):
        bus = CoordinationBus(repo_path=tmp_path)
        bus.publish("type_a", {})
        bus.publish("type_b", {})
        bus.publish("type_a", {})

        events = bus.poll(event_type="type_a")
        assert len(events) == 2

    def test_poll_limit(self, tmp_path):
        bus = CoordinationBus(repo_path=tmp_path)
        for i in range(10):
            bus.publish("ev", {"i": i})

        events = bus.poll(limit=3)
        assert len(events) == 3

    def test_poll_empty_dir(self, tmp_path):
        bus = CoordinationBus(repo_path=tmp_path)
        assert bus.poll() == []

    def test_cleanup_removes_old_events(self, tmp_path):
        bus = CoordinationBus(repo_path=tmp_path, max_event_age_seconds=60)

        # Write an event with old timestamp
        events_dir = tmp_path / ".aragora_coordination" / "events"
        events_dir.mkdir(parents=True)
        old = {
            "event_id": "old1",
            "event_type": "stale",
            "payload": {},
            "timestamp": time.time() - 120,
            "source_session": "",
        }
        (events_dir / "0000000.000000-old1.json").write_text(json.dumps(old))

        bus.publish("fresh", {})

        removed = bus.cleanup()
        assert removed == 1
        assert len(bus.poll()) == 1  # fresh event remains

    def test_clear_removes_all(self, tmp_path):
        bus = CoordinationBus(repo_path=tmp_path)
        bus.publish("a", {})
        bus.publish("b", {})
        removed = bus.clear()
        assert removed == 2
        assert bus.poll() == []

    def test_source_session_default(self, tmp_path):
        bus = CoordinationBus(repo_path=tmp_path, source_session="claude-1")
        ev = bus.publish("test", {})
        assert ev.source_session == "claude-1"

    def test_source_session_override(self, tmp_path):
        bus = CoordinationBus(repo_path=tmp_path, source_session="claude-1")
        ev = bus.publish("test", {}, source_session="codex-2")
        assert ev.source_session == "codex-2"

    def test_corrupt_file_skipped(self, tmp_path):
        bus = CoordinationBus(repo_path=tmp_path)
        events_dir = tmp_path / ".aragora_coordination" / "events"
        events_dir.mkdir(parents=True)
        (events_dir / "bad.json").write_text("not json{{{")

        bus.publish("good", {})
        events = bus.poll()
        assert len(events) == 1
        assert events[0].event_type == "good"
