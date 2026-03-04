# Debate as Coordination Protocol — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable heterogeneous AI agents working in parallel worktrees to coordinate via advisory file claims, peer-to-peer session discovery, and Arena-based conflict resolution — all filesystem-backed, no Redis required.

**Architecture:** New modules in `aragora/coordination/` (registry.py, claims.py, resolver.py, bus.py) provide a file-based coordination layer. State lives in `.aragora_coordination/` (gitignored). The `scripts/coordinate.py` CLI is the single entry point for agents. Arena debates resolve contested claims and merge conflicts. Everything is advisory — agents are never blocked.

**Tech Stack:** Python 3.12+, pathlib, json, dataclasses, asyncio, pytest, existing Arena/SemanticConflictDetector

**Design doc:** `docs/plans/2026-03-04-debate-coordination-protocol-design.md`

---

## Task 1: File-Based Event Bus

The bus is the foundation — other modules publish and subscribe to coordination events via JSON files in `.aragora_coordination/events/`.

**Files:**
- Create: `aragora/coordination/bus.py`
- Create: `tests/coordination/test_bus.py`

**Step 1: Write the failing tests**

```python
# tests/coordination/test_bus.py
"""Tests for file-based coordination event bus."""

import json
import time
from pathlib import Path

import pytest

from aragora.coordination.bus import CoordinationBus, CoordinationEvent


class TestCoordinationEvent:
    def test_create_event(self):
        event = CoordinationEvent(
            event_type="session_registered",
            source="claude-abc123",
            data={"worktree": "/tmp/wt-1"},
        )
        assert event.event_type == "session_registered"
        assert event.source == "claude-abc123"
        assert event.event_id  # auto-generated UUID
        assert event.timestamp  # auto-generated ISO timestamp

    def test_event_roundtrip_json(self):
        event = CoordinationEvent(
            event_type="claim_granted",
            source="codex-def456",
            data={"paths": ["src/foo.py"]},
        )
        json_str = event.to_json()
        restored = CoordinationEvent.from_json(json_str)
        assert restored.event_type == event.event_type
        assert restored.source == event.source
        assert restored.data == event.data


class TestCoordinationBus:
    @pytest.fixture
    def bus(self, tmp_path: Path) -> CoordinationBus:
        return CoordinationBus(state_dir=tmp_path / ".aragora_coordination")

    def test_init_creates_directories(self, bus: CoordinationBus):
        assert bus.events_dir.is_dir()

    def test_publish_creates_event_file(self, bus: CoordinationBus):
        event = bus.publish("session_registered", "claude-1", {"pid": 1234})
        event_file = bus.events_dir / f"{event.event_id}.json"
        assert event_file.exists()
        data = json.loads(event_file.read_text())
        assert data["event_type"] == "session_registered"

    def test_recent_events_returns_latest(self, bus: CoordinationBus):
        bus.publish("ev1", "src1", {})
        time.sleep(0.01)
        bus.publish("ev2", "src2", {})
        events = bus.recent_events(limit=10)
        assert len(events) == 2
        assert events[0].event_type == "ev2"  # most recent first

    def test_recent_events_filters_by_type(self, bus: CoordinationBus):
        bus.publish("claim_granted", "src1", {})
        bus.publish("session_registered", "src2", {})
        events = bus.recent_events(event_type="claim_granted")
        assert len(events) == 1
        assert events[0].event_type == "claim_granted"

    def test_gc_removes_old_events(self, bus: CoordinationBus):
        event = bus.publish("old_event", "src1", {})
        event_file = bus.events_dir / f"{event.event_id}.json"
        # Backdate the file
        import os
        old_time = time.time() - 7200  # 2 hours ago
        os.utime(event_file, (old_time, old_time))
        bus.gc(max_age_seconds=3600)
        assert not event_file.exists()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/coordination/test_bus.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aragora.coordination.bus'`

**Step 3: Write the implementation**

```python
# aragora/coordination/bus.py
"""File-based coordination event bus.

Events are JSON files in `.aragora_coordination/events/`. No Redis, no server,
no single point of failure. Any agent can publish and read events.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CoordinationEvent:
    """A single coordination event."""

    event_type: str
    source: str
    data: dict = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_json(self) -> str:
        return json.dumps(
            {
                "event_id": self.event_id,
                "event_type": self.event_type,
                "source": self.source,
                "data": self.data,
                "timestamp": self.timestamp,
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, raw: str) -> CoordinationEvent:
        d = json.loads(raw)
        return cls(
            event_id=d["event_id"],
            event_type=d["event_type"],
            source=d["source"],
            data=d.get("data", {}),
            timestamp=d["timestamp"],
        )


class CoordinationBus:
    """Filesystem-backed event bus for agent coordination.

    Events are stored as individual JSON files, sorted by mtime for recency.
    No locking needed — each event is an atomic file write.
    """

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.events_dir = state_dir / "events"
        self.events_dir.mkdir(parents=True, exist_ok=True)

    def publish(self, event_type: str, source: str, data: dict) -> CoordinationEvent:
        """Publish an event. Returns the created event."""
        event = CoordinationEvent(event_type=event_type, source=source, data=data)
        event_file = self.events_dir / f"{event.event_id}.json"
        event_file.write_text(event.to_json(), encoding="utf-8")
        logger.debug("Published %s from %s", event_type, source)
        return event

    def recent_events(
        self,
        limit: int = 50,
        event_type: str | None = None,
    ) -> list[CoordinationEvent]:
        """Read recent events, most recent first."""
        files = sorted(
            self.events_dir.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        events: list[CoordinationEvent] = []
        for f in files[:limit * 2]:  # read extra to account for filtering
            try:
                event = CoordinationEvent.from_json(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, KeyError):
                continue
            if event_type and event.event_type != event_type:
                continue
            events.append(event)
            if len(events) >= limit:
                break
        return events

    def gc(self, max_age_seconds: int = 3600) -> int:
        """Remove events older than max_age_seconds. Returns count removed."""
        cutoff = time.time() - max_age_seconds
        removed = 0
        for f in self.events_dir.glob("*.json"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except OSError:
                continue
        if removed:
            logger.debug("GC removed %d stale events", removed)
        return removed
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/coordination/test_bus.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add aragora/coordination/bus.py tests/coordination/test_bus.py
git commit -m "feat(coordination): add file-based event bus"
```

---

## Task 2: Session Registry

Agents register on startup and discover each other by reading JSON files. Built on top of the event bus.

**Files:**
- Create: `aragora/coordination/registry.py`
- Create: `tests/coordination/test_registry.py`

**Step 1: Write the failing tests**

```python
# tests/coordination/test_registry.py
"""Tests for peer-to-peer session registry."""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from aragora.coordination.registry import (
    SessionInfo,
    SessionRegistry,
)


class TestSessionInfo:
    def test_create(self):
        info = SessionInfo(
            session_id="claude-abc123",
            agent="claude",
            worktree="/tmp/wt-1",
            pid=1234,
            intent="Fix auth bug",
        )
        assert info.session_id == "claude-abc123"
        assert info.agent == "claude"

    def test_roundtrip_json(self):
        info = SessionInfo(
            session_id="codex-def456",
            agent="codex",
            worktree="/tmp/wt-2",
            pid=5678,
        )
        d = info.to_dict()
        restored = SessionInfo.from_dict(d)
        assert restored.session_id == info.session_id
        assert restored.pid == info.pid


class TestSessionRegistry:
    @pytest.fixture
    def registry(self, tmp_path: Path) -> SessionRegistry:
        return SessionRegistry(state_dir=tmp_path / ".aragora_coordination")

    def test_register_creates_file(self, registry: SessionRegistry):
        info = registry.register(
            agent="claude",
            worktree="/tmp/wt-1",
            intent="Fix bug",
        )
        session_file = registry.sessions_dir / f"{info.session_id}.json"
        assert session_file.exists()

    def test_active_sessions_returns_live(self, registry: SessionRegistry):
        info = registry.register(agent="claude", worktree="/tmp/wt-1")
        # Current process PID is alive
        sessions = registry.active_sessions()
        assert len(sessions) == 1
        assert sessions[0].session_id == info.session_id

    def test_active_sessions_skips_dead_pid(self, registry: SessionRegistry):
        info = registry.register(agent="claude", worktree="/tmp/wt-1")
        # Overwrite with a dead PID
        session_file = registry.sessions_dir / f"{info.session_id}.json"
        data = json.loads(session_file.read_text())
        data["pid"] = 999999999  # unlikely to be alive
        session_file.write_text(json.dumps(data))
        with patch("os.kill", side_effect=ProcessLookupError):
            sessions = registry.active_sessions()
        assert len(sessions) == 0

    def test_deregister_removes_file(self, registry: SessionRegistry):
        info = registry.register(agent="claude", worktree="/tmp/wt-1")
        registry.deregister(info.session_id)
        session_file = registry.sessions_dir / f"{info.session_id}.json"
        assert not session_file.exists()

    def test_heartbeat_updates_timestamp(self, registry: SessionRegistry):
        info = registry.register(agent="claude", worktree="/tmp/wt-1")
        original_ts = info.last_heartbeat
        time.sleep(0.01)
        registry.heartbeat(info.session_id)
        session_file = registry.sessions_dir / f"{info.session_id}.json"
        data = json.loads(session_file.read_text())
        assert data["last_heartbeat"] > original_ts
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/coordination/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
# aragora/coordination/registry.py
"""Peer-to-peer session registry.

Each agent writes a JSON file on startup. Discovery is reading the directory.
Liveness checked via os.kill(pid, 0). No central process needed.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SessionInfo:
    """Information about an active agent session."""

    session_id: str
    agent: str
    worktree: str
    pid: int
    intent: str = ""
    tracks: list[str] = field(default_factory=list)
    registered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_heartbeat: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "agent": self.agent,
            "worktree": self.worktree,
            "pid": self.pid,
            "intent": self.intent,
            "tracks": self.tracks,
            "registered_at": self.registered_at,
            "last_heartbeat": self.last_heartbeat,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SessionInfo:
        return cls(
            session_id=d["session_id"],
            agent=d["agent"],
            worktree=d["worktree"],
            pid=d["pid"],
            intent=d.get("intent", ""),
            tracks=d.get("tracks", []),
            registered_at=d.get("registered_at", ""),
            last_heartbeat=d.get("last_heartbeat", ""),
        )


def _pid_alive(pid: int) -> bool:
    """Check if a process is alive via signal 0."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned by another user


class SessionRegistry:
    """Filesystem-backed session registry.

    Each session is a JSON file in `.aragora_coordination/sessions/`.
    """

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.sessions_dir = state_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def register(
        self,
        agent: str,
        worktree: str,
        intent: str = "",
        tracks: list[str] | None = None,
    ) -> SessionInfo:
        """Register this session. Returns SessionInfo with generated ID."""
        session_id = f"{agent}-{uuid.uuid4().hex[:8]}"
        info = SessionInfo(
            session_id=session_id,
            agent=agent,
            worktree=worktree,
            pid=os.getpid(),
            intent=intent,
            tracks=tracks or [],
        )
        session_file = self.sessions_dir / f"{session_id}.json"
        session_file.write_text(
            json.dumps(info.to_dict(), indent=2), encoding="utf-8"
        )
        logger.info("Registered session %s (agent=%s)", session_id, agent)
        return info

    def deregister(self, session_id: str) -> None:
        """Remove a session registration."""
        session_file = self.sessions_dir / f"{session_id}.json"
        try:
            session_file.unlink(missing_ok=True)
            logger.info("Deregistered session %s", session_id)
        except OSError:
            pass

    def active_sessions(self) -> list[SessionInfo]:
        """Return all sessions with alive PIDs."""
        sessions: list[SessionInfo] = []
        for f in self.sessions_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                info = SessionInfo.from_dict(data)
            except (OSError, json.JSONDecodeError, KeyError):
                continue
            if _pid_alive(info.pid):
                sessions.append(info)
            else:
                # Auto-reap dead sessions
                logger.debug("Reaping dead session %s (pid=%d)", info.session_id, info.pid)
                f.unlink(missing_ok=True)
        return sessions

    def heartbeat(self, session_id: str) -> None:
        """Update the heartbeat timestamp for a session."""
        session_file = self.sessions_dir / f"{session_id}.json"
        try:
            data = json.loads(session_file.read_text(encoding="utf-8"))
            data["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
            session_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to heartbeat session %s", session_id)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/coordination/test_registry.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add aragora/coordination/registry.py tests/coordination/test_registry.py
git commit -m "feat(coordination): add peer-to-peer session registry"
```

---

## Task 3: File Claim Protocol

Advisory (non-blocking) file claims with TTL-based lease expiry.

**Files:**
- Create: `aragora/coordination/claims.py`
- Create: `tests/coordination/test_claims.py`

**Step 1: Write the failing tests**

```python
# tests/coordination/test_claims.py
"""Tests for advisory file claim protocol."""

import time
from pathlib import Path

import pytest

from aragora.coordination.claims import ClaimResult, ClaimStatus, FileClaims


class TestFileClaims:
    @pytest.fixture
    def claims(self, tmp_path: Path) -> FileClaims:
        return FileClaims(state_dir=tmp_path / ".aragora_coordination")

    def test_claim_uncontested(self, claims: FileClaims):
        result = claims.claim(
            session_id="claude-1",
            paths=["src/foo.py", "src/bar.py"],
            intent="Refactoring",
        )
        assert result.status == ClaimStatus.GRANTED

    def test_claim_overlapping_warns(self, claims: FileClaims):
        claims.claim(session_id="claude-1", paths=["src/foo.py"])
        result = claims.claim(session_id="codex-2", paths=["src/foo.py"])
        assert result.status == ClaimStatus.CONTESTED
        assert "src/foo.py" in result.contested_paths

    def test_claim_non_overlapping_ok(self, claims: FileClaims):
        claims.claim(session_id="claude-1", paths=["src/foo.py"])
        result = claims.claim(session_id="codex-2", paths=["src/bar.py"])
        assert result.status == ClaimStatus.GRANTED

    def test_claim_expired_not_contested(self, claims: FileClaims):
        claims.claim(
            session_id="claude-1",
            paths=["src/foo.py"],
            ttl_minutes=0,  # immediately expired
        )
        result = claims.claim(session_id="codex-2", paths=["src/foo.py"])
        assert result.status == ClaimStatus.GRANTED

    def test_release_removes_claim(self, claims: FileClaims):
        claims.claim(session_id="claude-1", paths=["src/foo.py"])
        claims.release(session_id="claude-1")
        result = claims.claim(session_id="codex-2", paths=["src/foo.py"])
        assert result.status == ClaimStatus.GRANTED

    def test_current_claims_lists_active(self, claims: FileClaims):
        claims.claim(session_id="claude-1", paths=["src/foo.py"])
        claims.claim(session_id="codex-2", paths=["src/bar.py"])
        active = claims.current_claims()
        assert len(active) == 2

    def test_who_owns(self, claims: FileClaims):
        claims.claim(session_id="claude-1", paths=["src/foo.py", "src/bar.py"])
        owner = claims.who_owns("src/foo.py")
        assert owner == "claude-1"
        assert claims.who_owns("src/baz.py") is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/coordination/test_claims.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
# aragora/coordination/claims.py
"""Advisory file claim protocol.

Claims are advisory, not blocking. An agent claiming a file gets a warning
if another agent already holds it, but can always proceed. Claims auto-expire
after TTL.
"""

from __future__ import annotations

import enum
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class ClaimStatus(enum.Enum):
    GRANTED = "granted"
    CONTESTED = "contested"  # granted but with warning about overlap


@dataclass
class ClaimResult:
    """Result of a claim attempt."""

    status: ClaimStatus
    contested_paths: list[str] = field(default_factory=list)
    holders: dict[str, str] = field(default_factory=dict)  # path -> session_id


@dataclass
class Claim:
    """A single file claim."""

    session_id: str
    paths: list[str]
    intent: str = ""
    claimed_at: float = field(default_factory=time.time)
    ttl_minutes: int = 30

    @property
    def expired(self) -> bool:
        return time.time() > self.claimed_at + (self.ttl_minutes * 60)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "paths": self.paths,
            "intent": self.intent,
            "claimed_at": self.claimed_at,
            "ttl_minutes": self.ttl_minutes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Claim:
        return cls(
            session_id=d["session_id"],
            paths=d["paths"],
            intent=d.get("intent", ""),
            claimed_at=d.get("claimed_at", time.time()),
            ttl_minutes=d.get("ttl_minutes", 30),
        )


class FileClaims:
    """Filesystem-backed advisory file claims.

    Each session's claims are stored in a single JSON file.
    Claims are advisory — contested claims are still granted with a warning.
    """

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.claims_dir = state_dir / "claims"
        self.claims_dir.mkdir(parents=True, exist_ok=True)

    def claim(
        self,
        session_id: str,
        paths: list[str],
        intent: str = "",
        ttl_minutes: int = 30,
    ) -> ClaimResult:
        """Claim files. Always succeeds but warns on overlap."""
        # Check for contested paths
        contested: list[str] = []
        holders: dict[str, str] = {}
        for existing in self._load_active_claims():
            if existing.session_id == session_id:
                continue
            overlap = set(paths) & set(existing.paths)
            for p in overlap:
                contested.append(p)
                holders[p] = existing.session_id

        # Write the claim
        new_claim = Claim(
            session_id=session_id,
            paths=paths,
            intent=intent,
            ttl_minutes=ttl_minutes,
        )
        claim_file = self.claims_dir / f"{session_id}.json"
        claim_file.write_text(
            json.dumps(new_claim.to_dict(), indent=2), encoding="utf-8"
        )

        if contested:
            logger.warning(
                "Contested claim by %s on %s (held by: %s)",
                session_id,
                contested,
                holders,
            )
            return ClaimResult(
                status=ClaimStatus.CONTESTED,
                contested_paths=contested,
                holders=holders,
            )

        return ClaimResult(status=ClaimStatus.GRANTED)

    def release(self, session_id: str) -> None:
        """Release all claims for a session."""
        claim_file = self.claims_dir / f"{session_id}.json"
        claim_file.unlink(missing_ok=True)

    def current_claims(self) -> list[Claim]:
        """Return all active (non-expired) claims."""
        return self._load_active_claims()

    def who_owns(self, path: str) -> str | None:
        """Return the session_id that currently claims a path, or None."""
        for c in self._load_active_claims():
            if path in c.paths:
                return c.session_id
        return None

    def _load_active_claims(self) -> list[Claim]:
        """Load all non-expired claims from disk."""
        claims: list[Claim] = []
        for f in self.claims_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                c = Claim.from_dict(data)
            except (OSError, json.JSONDecodeError, KeyError):
                continue
            if c.expired:
                f.unlink(missing_ok=True)
                continue
            claims.append(c)
        return claims
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/coordination/test_claims.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add aragora/coordination/claims.py tests/coordination/test_claims.py
git commit -m "feat(coordination): add advisory file claim protocol"
```

---

## Task 4: Conflict Resolver with Arena Integration

Detects merge conflicts and resolves them via Arena debate. Replaces the `_debate_scan()` stub in SemanticConflictDetector.

**Files:**
- Create: `aragora/coordination/resolver.py`
- Create: `tests/coordination/test_resolver.py`

**Step 1: Write the failing tests**

```python
# tests/coordination/test_resolver.py
"""Tests for Arena-based conflict resolution."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.coordination.resolver import (
    ConflictSeverity,
    ConflictVerdict,
    CoordinationResolver,
)


class TestCoordinationResolver:
    @pytest.fixture
    def resolver(self, tmp_path: Path) -> CoordinationResolver:
        return CoordinationResolver(
            state_dir=tmp_path / ".aragora_coordination",
            repo_path=tmp_path,
        )

    def test_classify_trivial_conflict(self, resolver: CoordinationResolver):
        severity = resolver.classify_conflict(
            files=["requirements.txt"],
            diff_a="added dependency-a",
            diff_b="added dependency-b",
        )
        assert severity == ConflictSeverity.TRIVIAL

    def test_classify_semantic_conflict(self, resolver: CoordinationResolver):
        severity = resolver.classify_conflict(
            files=["aragora/server/handlers/auth.py"],
            diff_a="def login(user, password):",
            diff_b="def login(credentials: LoginRequest):",
        )
        assert severity == ConflictSeverity.SEMANTIC

    @pytest.mark.asyncio
    async def test_resolve_trivial_auto_merges(self, resolver: CoordinationResolver):
        verdict = await resolver.resolve(
            branch_a="feat/auth",
            branch_b="feat/billing",
            files=["requirements.txt"],
            diff_a="added auth-lib",
            diff_b="added billing-lib",
        )
        assert verdict.action == "auto_merge"

    @pytest.mark.asyncio
    async def test_resolve_semantic_triggers_debate(self, resolver: CoordinationResolver):
        mock_result = MagicMock()
        mock_result.consensus_reached = True
        mock_result.final_answer = "Merge branch_a first, then rebase branch_b"
        mock_result.confidence = 0.9
        mock_result.messages = []

        mock_arena = MagicMock()
        mock_arena.run = AsyncMock(return_value=mock_result)

        with patch(
            "aragora.coordination.resolver.CoordinationResolver._create_arena",
            return_value=mock_arena,
        ):
            verdict = await resolver.resolve(
                branch_a="feat/auth",
                branch_b="feat/billing",
                files=["aragora/server/handlers/auth.py"],
                diff_a="def login(user, password):",
                diff_b="def login(credentials: LoginRequest):",
            )
        assert verdict.action in ("merge_a_first", "merge_b_first", "synthesize")
        assert verdict.reasoning

    @pytest.mark.asyncio
    async def test_resolve_debate_failure_flags_human(self, resolver: CoordinationResolver):
        mock_arena = MagicMock()
        mock_arena.run = AsyncMock(side_effect=RuntimeError("Arena failed"))

        with patch(
            "aragora.coordination.resolver.CoordinationResolver._create_arena",
            return_value=mock_arena,
        ):
            verdict = await resolver.resolve(
                branch_a="feat/a",
                branch_b="feat/b",
                files=["aragora/core.py"],
                diff_a="change A",
                diff_b="change B",
            )
        assert verdict.action == "flag_human"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/coordination/test_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
# aragora/coordination/resolver.py
"""Arena-based conflict resolution.

When two branches modify the same files, this module classifies the conflict
severity and either auto-merges (trivial) or runs an Arena debate (semantic).
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Files where parallel edits are almost always safe to auto-merge
_TRIVIAL_PATTERNS = {
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "uv.lock",
    ".gitignore",
}


class ConflictSeverity(enum.Enum):
    TRIVIAL = "trivial"  # auto-merge safe
    SEMANTIC = "semantic"  # needs debate


@dataclass
class ConflictVerdict:
    """Result of conflict resolution."""

    action: str  # "auto_merge", "merge_a_first", "merge_b_first", "synthesize", "flag_human"
    reasoning: str = ""
    confidence: float = 0.0


class CoordinationResolver:
    """Resolves file conflicts between parallel branches.

    Trivial conflicts (requirements, config) are auto-merged.
    Semantic conflicts (same function changed) trigger an Arena debate.
    If debate fails, flags for human review. Never blocks.
    """

    def __init__(self, state_dir: Path, repo_path: Path) -> None:
        self.state_dir = state_dir
        self.repo_path = repo_path

    def classify_conflict(
        self, files: list[str], diff_a: str, diff_b: str
    ) -> ConflictSeverity:
        """Classify whether a conflict is trivial or semantic."""
        # If all files match trivial patterns, it's trivial
        all_trivial = all(
            Path(f).name in _TRIVIAL_PATTERNS for f in files
        )
        if all_trivial:
            return ConflictSeverity.TRIVIAL

        # If diffs touch different functions/classes, could still be trivial,
        # but we err on the side of debate
        return ConflictSeverity.SEMANTIC

    async def resolve(
        self,
        branch_a: str,
        branch_b: str,
        files: list[str],
        diff_a: str,
        diff_b: str,
    ) -> ConflictVerdict:
        """Resolve a conflict. Auto-merges trivial, debates semantic."""
        severity = self.classify_conflict(files, diff_a, diff_b)

        if severity == ConflictSeverity.TRIVIAL:
            return ConflictVerdict(
                action="auto_merge",
                reasoning="All conflicting files are config/dependency files safe for auto-merge",
                confidence=0.95,
            )

        # Semantic conflict — run Arena debate
        return await self._debate_resolution(branch_a, branch_b, files, diff_a, diff_b)

    async def _debate_resolution(
        self,
        branch_a: str,
        branch_b: str,
        files: list[str],
        diff_a: str,
        diff_b: str,
    ) -> ConflictVerdict:
        """Run an Arena debate to resolve a semantic conflict."""
        try:
            arena = self._create_arena(branch_a, branch_b, files, diff_a, diff_b)
            result = await arena.run()
        except Exception:
            logger.warning(
                "Debate failed for conflict between %s and %s, flagging for human",
                branch_a,
                branch_b,
            )
            return ConflictVerdict(
                action="flag_human",
                reasoning="Arena debate failed — keeping both branches for human review",
                confidence=0.0,
            )

        # Parse debate result into a verdict
        answer = (result.final_answer or "").lower()
        if branch_a.split("/")[-1] in answer or "first" in answer:
            action = "merge_a_first"
        elif branch_b.split("/")[-1] in answer:
            action = "merge_b_first"
        else:
            action = "synthesize"

        return ConflictVerdict(
            action=action,
            reasoning=result.final_answer or "Debate reached consensus",
            confidence=getattr(result, "confidence", 0.5),
        )

    def _create_arena(
        self,
        branch_a: str,
        branch_b: str,
        files: list[str],
        diff_a: str,
        diff_b: str,
    ):
        """Create an Arena for conflict resolution debate."""
        from aragora.debate.orchestrator import Arena, Environment, DebateProtocol

        env = Environment(
            task=(
                f"Branches '{branch_a}' and '{branch_b}' conflict on {files}. "
                f"Diff A: {diff_a[:500]}. Diff B: {diff_b[:500]}. "
                f"Which should merge first? How should conflicts resolve?"
            )
        )
        protocol = DebateProtocol(rounds=2, consensus="majority")

        # Use lightweight mock agents for fast resolution
        from aragora.agents.api_agents.anthropic import AnthropicAgent

        agents = [
            AnthropicAgent(name="code-quality-judge", model="claude-haiku-4-5-20251001"),
            AnthropicAgent(name="dependency-judge", model="claude-haiku-4-5-20251001"),
        ]
        return Arena(env, agents, protocol)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/coordination/test_resolver.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add aragora/coordination/resolver.py tests/coordination/test_resolver.py
git commit -m "feat(coordination): add Arena-based conflict resolver"
```

---

## Task 5: CLI Entry Point

The `scripts/coordinate.py` CLI is how agents interact with the coordination system.

**Files:**
- Create: `scripts/coordinate.py`
- Create: `tests/coordination/test_coordinate_cli.py`

**Step 1: Write the failing tests**

```python
# tests/coordination/test_coordinate_cli.py
"""Tests for coordinate.py CLI."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestCoordinateCLI:
    @pytest.fixture
    def state_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / ".aragora_coordination"
        d.mkdir()
        return d

    def test_register_command(self, tmp_path: Path):
        """Test that register creates a session file."""
        result = subprocess.run(
            [
                sys.executable,
                "scripts/coordinate.py",
                "register",
                "--agent", "claude",
                "--worktree", str(tmp_path),
                "--state-dir", str(tmp_path / ".aragora_coordination"),
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )
        assert result.returncode == 0
        assert "Registered" in result.stdout

    def test_status_command(self, tmp_path: Path):
        """Test that status runs without error."""
        state_dir = tmp_path / ".aragora_coordination"
        state_dir.mkdir()
        result = subprocess.run(
            [
                sys.executable,
                "scripts/coordinate.py",
                "status",
                "--state-dir", str(state_dir),
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )
        assert result.returncode == 0

    def test_claim_command(self, tmp_path: Path):
        """Test that claim runs without error."""
        state_dir = tmp_path / ".aragora_coordination"
        state_dir.mkdir()
        result = subprocess.run(
            [
                sys.executable,
                "scripts/coordinate.py",
                "claim",
                "--session-id", "test-123",
                "--paths", "src/foo.py",
                "--state-dir", str(state_dir),
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )
        assert result.returncode == 0
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/coordination/test_coordinate_cli.py -v`
Expected: FAIL (script doesn't exist)

**Step 3: Write the implementation**

```python
#!/usr/bin/env python3
# scripts/coordinate.py — CLI for agent coordination.
#
# Usage:
#   coordinate.py register --agent claude --worktree /path
#   coordinate.py status
#   coordinate.py claim --session-id claude-abc --paths src/foo.py src/bar.py
#   coordinate.py release --session-id claude-abc
#   coordinate.py heartbeat --session-id claude-abc

"""Agent coordination CLI.

Agents call this to register, discover peers, claim files, and release claims.
All state is filesystem-based in .aragora_coordination/.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure the repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aragora.coordination.registry import SessionRegistry
from aragora.coordination.claims import FileClaims, ClaimStatus
from aragora.coordination.bus import CoordinationBus


def _default_state_dir() -> Path:
    """Derive state dir from git repo root."""
    return REPO_ROOT / ".aragora_coordination"


def cmd_register(args: argparse.Namespace) -> None:
    state_dir = Path(args.state_dir) if args.state_dir else _default_state_dir()
    registry = SessionRegistry(state_dir=state_dir)
    bus = CoordinationBus(state_dir=state_dir)

    info = registry.register(
        agent=args.agent,
        worktree=args.worktree or str(Path.cwd()),
        intent=args.intent or "",
    )
    bus.publish("session_registered", info.session_id, info.to_dict())
    print(f"Registered {info.session_id}")


def cmd_status(args: argparse.Namespace) -> None:
    state_dir = Path(args.state_dir) if args.state_dir else _default_state_dir()
    registry = SessionRegistry(state_dir=state_dir)
    claims = FileClaims(state_dir=state_dir)

    sessions = registry.active_sessions()
    if not sessions:
        print("No active sessions.")
        return

    print(f"{'Agent':<12} {'Session':<20} {'Intent':<30} {'Worktree'}")
    print("-" * 90)
    for s in sessions:
        print(f"{s.agent:<12} {s.session_id:<20} {s.intent:<30} {s.worktree}")

    active_claims = claims.current_claims()
    if active_claims:
        print(f"\n{'Session':<20} {'Paths'}")
        print("-" * 60)
        for c in active_claims:
            print(f"{c.session_id:<20} {', '.join(c.paths)}")


def cmd_claim(args: argparse.Namespace) -> None:
    state_dir = Path(args.state_dir) if args.state_dir else _default_state_dir()
    fc = FileClaims(state_dir=state_dir)
    bus = CoordinationBus(state_dir=state_dir)

    result = fc.claim(
        session_id=args.session_id,
        paths=args.paths,
        intent=args.intent or "",
    )
    bus.publish("claim_result", args.session_id, {
        "status": result.status.value,
        "paths": args.paths,
        "contested": result.contested_paths,
    })

    if result.status == ClaimStatus.CONTESTED:
        print(f"WARNING: Contested paths: {result.contested_paths}")
        print(f"  Held by: {result.holders}")
        print("  Proceeding anyway (claims are advisory).")
    else:
        print(f"Claimed: {', '.join(args.paths)}")


def cmd_release(args: argparse.Namespace) -> None:
    state_dir = Path(args.state_dir) if args.state_dir else _default_state_dir()
    fc = FileClaims(state_dir=state_dir)
    fc.release(args.session_id)
    print(f"Released claims for {args.session_id}")


def cmd_heartbeat(args: argparse.Namespace) -> None:
    state_dir = Path(args.state_dir) if args.state_dir else _default_state_dir()
    registry = SessionRegistry(state_dir=state_dir)
    registry.heartbeat(args.session_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent coordination CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # register
    p_reg = sub.add_parser("register", help="Register this session")
    p_reg.add_argument("--agent", required=True)
    p_reg.add_argument("--worktree", default="")
    p_reg.add_argument("--intent", default="")
    p_reg.add_argument("--state-dir", default="")
    p_reg.set_defaults(func=cmd_register)

    # status
    p_status = sub.add_parser("status", help="Show active sessions and claims")
    p_status.add_argument("--state-dir", default="")
    p_status.set_defaults(func=cmd_status)

    # claim
    p_claim = sub.add_parser("claim", help="Claim files")
    p_claim.add_argument("--session-id", required=True)
    p_claim.add_argument("--paths", nargs="+", required=True)
    p_claim.add_argument("--intent", default="")
    p_claim.add_argument("--state-dir", default="")
    p_claim.set_defaults(func=cmd_claim)

    # release
    p_release = sub.add_parser("release", help="Release claims")
    p_release.add_argument("--session-id", required=True)
    p_release.add_argument("--state-dir", default="")
    p_release.set_defaults(func=cmd_release)

    # heartbeat
    p_hb = sub.add_parser("heartbeat", help="Update heartbeat")
    p_hb.add_argument("--session-id", required=True)
    p_hb.add_argument("--state-dir", default="")
    p_hb.set_defaults(func=cmd_heartbeat)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/coordination/test_coordinate_cli.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
chmod +x scripts/coordinate.py
git add scripts/coordinate.py tests/coordination/test_coordinate_cli.py
git commit -m "feat(coordination): add coordinate.py CLI entry point"
```

---

## Task 6: Update Module Exports

Add the new modules to `aragora/coordination/__init__.py` and gitignore the state directory.

**Files:**
- Modify: `aragora/coordination/__init__.py`
- Modify: `.gitignore`

**Step 1: Update __init__.py**

Add after line 50 (after the reconciler imports):

```python
from aragora.coordination.bus import CoordinationBus, CoordinationEvent
from aragora.coordination.registry import SessionRegistry, SessionInfo
from aragora.coordination.claims import FileClaims, ClaimResult, ClaimStatus, Claim
from aragora.coordination.resolver import (
    CoordinationResolver,
    ConflictSeverity,
    ConflictVerdict,
)
```

Add to `__all__` list:

```python
    # Coordination protocol
    "CoordinationBus",
    "CoordinationEvent",
    "SessionRegistry",
    "SessionInfo",
    "FileClaims",
    "ClaimResult",
    "ClaimStatus",
    "Claim",
    "CoordinationResolver",
    "ConflictSeverity",
    "ConflictVerdict",
```

**Step 2: Add .aragora_coordination/ to .gitignore**

Add to `.gitignore`:

```
# Agent coordination state (local, not committed)
.aragora_coordination/
```

**Step 3: Verify imports work**

Run: `python -c "from aragora.coordination import SessionRegistry, FileClaims, CoordinationBus, CoordinationResolver; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add aragora/coordination/__init__.py .gitignore
git commit -m "feat(coordination): export new protocol modules and gitignore state dir"
```

---

## Task 7: Integration Test — Full Workflow

End-to-end test: two simulated sessions register, claim files, detect overlap, and resolve.

**Files:**
- Create: `tests/coordination/test_coordination_e2e.py`

**Step 1: Write the integration test**

```python
# tests/coordination/test_coordination_e2e.py
"""End-to-end test for the coordination protocol."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.coordination.bus import CoordinationBus
from aragora.coordination.claims import ClaimStatus, FileClaims
from aragora.coordination.registry import SessionRegistry
from aragora.coordination.resolver import CoordinationResolver


class TestCoordinationE2E:
    @pytest.fixture
    def state_dir(self, tmp_path: Path) -> Path:
        return tmp_path / ".aragora_coordination"

    def test_two_sessions_non_overlapping(self, state_dir: Path):
        """Two agents working on different files — no conflict."""
        registry = SessionRegistry(state_dir=state_dir)
        claims = FileClaims(state_dir=state_dir)
        bus = CoordinationBus(state_dir=state_dir)

        # Agent 1 registers and claims
        s1 = registry.register(agent="claude", worktree="/tmp/wt-1", intent="Auth fix")
        r1 = claims.claim(session_id=s1.session_id, paths=["src/auth.py"])
        assert r1.status == ClaimStatus.GRANTED

        # Agent 2 registers and claims different files
        s2 = registry.register(agent="codex", worktree="/tmp/wt-2", intent="Billing")
        r2 = claims.claim(session_id=s2.session_id, paths=["src/billing.py"])
        assert r2.status == ClaimStatus.GRANTED

        # Both visible
        sessions = registry.active_sessions()
        assert len(sessions) == 2

        # Events recorded
        events = bus.recent_events()
        # No events yet (register/claim don't auto-publish to bus in unit form)

    def test_two_sessions_overlapping_advisory(self, state_dir: Path):
        """Two agents claim the same file — contested but both proceed."""
        claims = FileClaims(state_dir=state_dir)

        r1 = claims.claim(session_id="claude-1", paths=["src/shared.py"])
        assert r1.status == ClaimStatus.GRANTED

        r2 = claims.claim(session_id="codex-2", paths=["src/shared.py"])
        assert r2.status == ClaimStatus.CONTESTED
        assert "src/shared.py" in r2.contested_paths
        assert r2.holders["src/shared.py"] == "claude-1"

    @pytest.mark.asyncio
    async def test_conflict_resolution_trivial(self, state_dir: Path, tmp_path: Path):
        """Config file conflicts auto-merge."""
        resolver = CoordinationResolver(state_dir=state_dir, repo_path=tmp_path)
        verdict = await resolver.resolve(
            branch_a="feat/a",
            branch_b="feat/b",
            files=["requirements.txt"],
            diff_a="added lib-a",
            diff_b="added lib-b",
        )
        assert verdict.action == "auto_merge"

    @pytest.mark.asyncio
    async def test_conflict_resolution_semantic_with_debate(
        self, state_dir: Path, tmp_path: Path
    ):
        """Semantic conflict triggers debate, falls back to human on failure."""
        resolver = CoordinationResolver(state_dir=state_dir, repo_path=tmp_path)

        mock_arena = MagicMock()
        mock_arena.run = AsyncMock(side_effect=RuntimeError("No API key"))

        with patch.object(resolver, "_create_arena", return_value=mock_arena):
            verdict = await resolver.resolve(
                branch_a="feat/a",
                branch_b="feat/b",
                files=["aragora/core.py"],
                diff_a="def foo(x):",
                diff_b="def foo(x, y):",
            )
        assert verdict.action == "flag_human"

    def test_session_lifecycle(self, state_dir: Path):
        """Register → heartbeat → deregister lifecycle."""
        registry = SessionRegistry(state_dir=state_dir)
        claims = FileClaims(state_dir=state_dir)

        info = registry.register(agent="claude", worktree="/tmp/wt")
        claims.claim(session_id=info.session_id, paths=["src/foo.py"])

        # Heartbeat
        registry.heartbeat(info.session_id)

        # Deregister
        registry.deregister(info.session_id)
        claims.release(info.session_id)

        assert len(registry.active_sessions()) == 0
        assert len(claims.current_claims()) == 0
```

**Step 2: Run the integration test**

Run: `pytest tests/coordination/test_coordination_e2e.py -v`
Expected: All 5 tests PASS

**Step 3: Run the full coordination test suite**

Run: `pytest tests/coordination/ -v`
Expected: All tests across test_bus.py, test_registry.py, test_claims.py, test_resolver.py, test_coordinate_cli.py, test_coordination_e2e.py PASS

**Step 4: Commit**

```bash
git add tests/coordination/test_coordination_e2e.py
git commit -m "test(coordination): add end-to-end coordination protocol tests"
```

---

## Summary

| Task | Component | New Files | Tests |
|------|-----------|-----------|-------|
| 1 | Event Bus | `aragora/coordination/bus.py` | 7 |
| 2 | Session Registry | `aragora/coordination/registry.py` | 6 |
| 3 | File Claims | `aragora/coordination/claims.py` | 7 |
| 4 | Conflict Resolver | `aragora/coordination/resolver.py` | 5 |
| 5 | CLI Entry Point | `scripts/coordinate.py` | 3 |
| 6 | Module Exports | `__init__.py`, `.gitignore` | 1 (import check) |
| 7 | Integration Tests | `test_coordination_e2e.py` | 5 |
| **Total** | | **7 new files** | **~34 tests** |

All tasks are independent (can be parallelized in pairs: 1+2, 3+4, 5+6, then 7 last).
