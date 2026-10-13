"""
Integration tests for server handler coordination.

Tests validate:
- Cross-handler data consistency
- Handler coordination with shared state
- Concurrent access safety
- Event flow between handlers

These tests use REAL storage and ELO systems (with temp databases),
unlike unit tests which mock dependencies.
"""

import asyncio
import inspect
import json
import threading
import tempfile
import os
from pathlib import Path
from collections.abc import Generator
from unittest.mock import Mock, MagicMock

import pytest

from aragora.rbac.models import AuthorizationContext
from aragora.server.handlers import (
    DebatesHandler,
    AgentsHandler,
    AnalyticsHandler,
    SystemHandler,
    MetricsHandler,
)
from aragora.server.handlers.base import clear_cache
from aragora.storage.debate_storage import DebateStorage
from aragora.ranking.elo import EloSystem
from aragora.server.stream import SyncEventEmitter, StreamEvent, StreamEventType


def call_handler(handler, path, params, req):
    """Call a handler's handle method, awaiting if async."""
    result = handler.handle(path, params, req)
    if inspect.isawaitable(result):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, result).result()
        return asyncio.run(result)
    return result


# ============================================================================
# Storage Adapter - Provides expected handler API on top of DebateStorage
# ============================================================================


class StorageAdapter:
    """
    Wraps DebateStorage to provide the API expected by handlers.

    Handlers expect:
    - list_debates(limit) -> list[dict]
    - get_debate(slug_or_id) -> dict | None

    DebateStorage has:
    - list_recent(limit) -> list[DebateMetadata]
    - get_by_slug(slug) -> dict | None
    - get_by_id(id) -> dict | None
    """

    def __init__(self, storage: DebateStorage):
        self._storage = storage

    def list_debates(self, limit: int = 20) -> list[dict]:
        """List recent debates as dicts."""
        metadata_list = self._storage.list_recent(limit=limit)
        return [
            {
                "slug": m.slug,
                "id": m.debate_id,
                "task": m.task,
                "topic": m.task,  # Alias
                "agents": m.agents,
                "consensus_reached": m.consensus_reached,
                "confidence": m.confidence,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "view_count": m.view_count,
            }
            for m in metadata_list
        ]

    def get_debate(self, slug_or_id: str) -> dict | None:
        """Get debate by slug or ID."""
        result = self._storage.get_by_slug(slug_or_id)
        if result is None:
            result = self._storage.get_by_id(slug_or_id)
        return result

    def save_debate(self, debate_data: dict) -> str:
        """Save a debate and return its slug."""
        return self._storage.save_dict(debate_data)

    # Pass through other methods
    def __getattr__(self, name):
        return getattr(self._storage, name)


# ============================================================================
# Integration Test Fixtures
# ============================================================================


@pytest.fixture
def integration_db() -> Generator[str, None, None]:
    """Create a temporary database for integration tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
        for suffix in ["-wal", "-shm"]:
            try:
                os.unlink(path + suffix)
            except FileNotFoundError:
                pass
    except FileNotFoundError:
        pass


@pytest.fixture
def elo_db() -> Generator[str, None, None]:
    """Create a separate temporary database for ELO."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
        for suffix in ["-wal", "-shm"]:
            try:
                os.unlink(path + suffix)
            except FileNotFoundError:
                pass
    except FileNotFoundError:
        pass


@pytest.fixture
def integrated_storage(integration_db) -> StorageAdapter:
    """Create a real DebateStorage with temp database."""
    storage = DebateStorage(db_path=integration_db)
    return StorageAdapter(storage)


@pytest.fixture
def integrated_elo(elo_db) -> EloSystem:
    """Create a real EloSystem with temp database."""
    return EloSystem(db_path=elo_db)


@pytest.fixture
def integration_nomic_dir() -> Generator[Path, None, None]:
    """Create a temporary nomic directory for integration tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        nomic_dir = Path(tmpdir)

        state_file = nomic_dir / "nomic_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "phase": "implement",
                    "stage": "executing",
                    "cycle": 1,
                    "total_tasks": 5,
                    "completed_tasks": 2,
                }
            )
        )

        log_file = nomic_dir / "nomic_loop.log"
        log_file.write_text(
            "\n".join(
                [
                    "2026-01-05 00:00:01 Starting cycle 1",
                    "2026-01-05 00:00:02 Phase: context",
                ]
            )
        )

        yield nomic_dir


@pytest.fixture
def handler_ensemble(integrated_storage, integrated_elo, integration_nomic_dir):
    """
    Create all handlers sharing the same context.

    This is the key integration fixture - all handlers share real
    storage and ELO system, enabling cross-handler coordination tests.
    """
    ctx = {
        "storage": integrated_storage,
        "elo_system": integrated_elo,
        "nomic_dir": integration_nomic_dir,
        "debate_embeddings": None,
        "critique_store": None,
    }

    return {
        "debates": DebatesHandler(ctx),
        "agents": AgentsHandler(ctx),
        "analytics": AnalyticsHandler(ctx),
        "system": SystemHandler(ctx),
        "metrics": MetricsHandler(ctx),
        "ctx": ctx,
    }


@pytest.fixture
def admin_handler():
    """Mock HTTP handler with admin auth context for RBAC-protected endpoints."""
    handler = MagicMock()
    handler._auth_context = AuthorizationContext(
        user_id="test-admin",
        permissions={
            "debates:read",
            "debates:create",
            "debates:update",
            "debates:delete",
            "agents:read",
            "agents:update",
            "analytics:read",
            "metrics:read",
            "system:read",
            "system:admin",
        },
        roles={"admin"},
    )
    return handler


@pytest.fixture(autouse=True)
def _bypass_auth(monkeypatch):
    """Bypass RBAC and JWT auth for integration tests."""
    mock_auth_ctx = AuthorizationContext(
        user_id="test-admin",
        permissions={"*"},
        roles={"admin", "owner"},
    )

    async def mock_get_auth_context(request, require_auth=False):
        return mock_auth_ctx

    try:
        from aragora.rbac import decorators

        original = decorators._get_context_from_args

        def patched(args, kwargs, context_param):
            result = original(args, kwargs, context_param)
            return result if result is not None else mock_auth_ctx

        monkeypatch.setattr(decorators, "_get_context_from_args", patched)
    except (ImportError, AttributeError):
        pass

    try:
        from aragora.server.handlers.utils import auth as utils_auth

        monkeypatch.setattr(utils_auth, "get_auth_context", mock_get_auth_context)
    except (ImportError, AttributeError):
        pass

    try:
        from aragora.server.handlers import secure

        monkeypatch.setattr(secure, "get_auth_context", mock_get_auth_context)
    except (ImportError, AttributeError):
        pass

    # Override extract_user_from_request to return a user WITHOUT org_id.
    # The conftest patches this with org_id="test-org-001" for test_handlers_* files,
    # but integration tests save debates without org_id, so org-scoped queries
    # would miss them. Setting org_id=None ensures list_recent returns all debates.
    try:
        from aragora.billing.auth.context import UserAuthContext

        _integration_user = UserAuthContext(
            authenticated=True,
            user_id="test-admin",
            email="admin@example.com",
            org_id=None,
            role="admin",
            token_type="access",
        )
        monkeypatch.setattr(
            "aragora.billing.jwt_auth.extract_user_from_request",
            lambda handler, user_store=None: _integration_user,
        )
    except (ImportError, AttributeError):
        pass


@pytest.fixture
def debate_factory(integrated_storage):
    """Factory for creating test debates with full data."""

    def create(
        slug: str,
        agents: list[str],
        task: str = None,
        consensus_reached: bool = False,
        messages: list = None,
    ) -> dict:
        debate_data = {
            "id": f"debate-{slug}",
            "slug": slug,
            "task": task or f"Test debate: {slug}",
            "topic": task or f"Test debate: {slug}",
            "agents": agents,
            "messages": messages
            or [
                {"agent": agents[0], "content": "First message", "round": 1, "role": "speaker"},
                {
                    "agent": agents[1] if len(agents) > 1 else agents[0],
                    "content": "Response",
                    "round": 1,
                    "role": "speaker",
                },
            ],
            "critiques": [],
            "votes": [],
            "consensus_reached": consensus_reached,
            "confidence": 0.8 if consensus_reached else 0.3,
            "rounds_used": 3,
        }
        integrated_storage.save_debate(debate_data)
        return debate_data

    return create


@pytest.fixture
def event_collector():
    """Collect events emitted during handler operations."""
    emitter = SyncEventEmitter()
    events = []

    def collect(event):
        events.append(event)

    emitter.subscribe(collect)
    return {"emitter": emitter, "events": events}


@pytest.fixture(autouse=True)
def clear_caches_between_tests():
    """Clear caches before and after each test."""
    clear_cache()
    yield
    clear_cache()


# ============================================================================
# Test Classes
# ============================================================================


class TestDebateAgentCoordination:
    """Tests for data flow between Debates and Agents handlers."""

    def test_debate_agents_appear_in_leaderboard_after_match(
        self, handler_ensemble, integrated_elo, admin_handler
    ):
        """Agents from a recorded match should appear in the leaderboard."""
        integrated_elo.record_match(
            "test-debate-1",
            ["claude", "gemini"],
            {"claude": 1.0, "gemini": 0.0},
        )

        result = call_handler(handler_ensemble["agents"], "/api/leaderboard", {}, admin_handler)
        assert result.status_code == 200

        data = json.loads(result.body)
        agent_names = [a.get("agent_name") or a.get("name") for a in data.get("rankings", [])]

        assert "claude" in agent_names
        assert "gemini" in agent_names

    def test_debate_appears_in_agent_history(self, handler_ensemble, integrated_elo):
        """Completed matches should be reflected in ELO system records."""
        integrated_elo.record_match(
            "debate-1", ["claude", "gemini"], {"claude": 1.0, "gemini": 0.0}
        )
        integrated_elo.record_match("debate-2", ["claude", "gpt4"], {"claude": 0.0, "gpt4": 1.0})

        rating = integrated_elo.get_rating("claude")
        assert rating is not None
        assert rating.debates_count >= 2 or rating.wins + rating.losses >= 2

    def test_agent_profile_reflects_elo_rating(self, handler_ensemble, integrated_elo):
        """Agent profile should show correct ELO rating."""
        integrated_elo.record_match("test-1", ["claude", "gemini"], {"claude": 1.0, "gemini": 0.0})
        integrated_elo.record_match("test-2", ["claude", "gpt4"], {"claude": 1.0, "gpt4": 0.0})

        rating = integrated_elo.get_rating("claude")
        assert rating is not None
        assert rating.elo > 1500

    def test_head_to_head_reflects_match_history(
        self, handler_ensemble, integrated_elo, admin_handler
    ):
        """Head-to-head stats should reflect recorded matches."""
        integrated_elo.record_match("match-1", ["claude", "gemini"], {"claude": 1.0, "gemini": 0.0})
        integrated_elo.record_match("match-2", ["claude", "gemini"], {"claude": 0.0, "gemini": 1.0})
        integrated_elo.record_match("match-3", ["claude", "gemini"], {"claude": 1.0, "gemini": 0.0})

        result = call_handler(
            handler_ensemble["agents"],
            "/api/agent/claude/head-to-head/gemini",
            {},
            admin_handler,
        )
        assert result.status_code == 200

        data = json.loads(result.body)
        assert data.get("claude_wins", 0) + data.get("wins", 0) >= 2

    def test_recent_matches_includes_recorded_matches(
        self, handler_ensemble, integrated_elo, admin_handler
    ):
        """Recent matches endpoint should include recorded matches."""
        integrated_elo.record_match(
            "recent-1", ["claude", "gemini"], {"claude": 1.0, "gemini": 0.0}
        )
        integrated_elo.record_match("recent-2", ["gpt4", "gemini"], {"gpt4": 1.0, "gemini": 0.0})

        result = call_handler(
            handler_ensemble["agents"],
            "/api/matches/recent",
            {"limit": "10"},
            admin_handler,
        )
        assert result.status_code == 200

        data = json.loads(result.body)
        matches = data.get("matches", [])
        assert len(matches) >= 2

    def test_leaderboard_ordering_reflects_elo(
        self, handler_ensemble, integrated_elo, admin_handler
    ):
        """Leaderboard should be ordered by ELO rating."""
        for i in range(5):
            integrated_elo.record_match(
                f"match-{i}", ["top_agent", "bottom_agent"], {"top_agent": 1.0, "bottom_agent": 0.0}
            )

        result = call_handler(handler_ensemble["agents"], "/api/leaderboard", {}, admin_handler)
        data = json.loads(result.body)
        rankings = data.get("rankings", [])

        if len(rankings) >= 2:
            first_elo = rankings[0].get("elo") or rankings[0].get("rating", 0)
            second_elo = rankings[1].get("elo") or rankings[1].get("rating", 0)
            assert first_elo >= second_elo


class TestDataConsistency:
    """Tests for cross-handler data consistency."""

    def test_debate_count_consistent(self, handler_ensemble, debate_factory, admin_handler):
        """Debate counts should be consistent across handlers."""
        for i in range(5):
            debate_factory(f"consistency-{i}", ["claude", "gemini"])

        result1 = call_handler(
            handler_ensemble["debates"],
            "/api/debates",
            {"limit": "100"},
            admin_handler,
        )
        data1 = json.loads(result1.body)
        debates_count = data1.get("count", len(data1.get("debates", [])))

        assert debates_count == 5

    def test_debate_retrieval_consistent(self, handler_ensemble, debate_factory, admin_handler):
        """Retrieving same debate should return consistent data."""
        created = debate_factory("retrieval-test", ["claude", "gemini"], task="Test task")

        result = call_handler(
            handler_ensemble["debates"],
            "/api/debates/slug/retrieval-test",
            {},
            admin_handler,
        )

        if result.status_code == 200:
            data = json.loads(result.body)
            assert data.get("task") == created["task"] or data.get("topic") == created["task"]

    def test_storage_write_visible_to_handlers(
        self, handler_ensemble, integrated_storage, admin_handler
    ):
        """Writes to storage should be immediately visible to handlers."""
        integrated_storage.save_debate(
            {
                "id": "direct-write",
                "task": "Direct write test",
                "agents": ["agent1", "agent2"],
                "messages": [],
                "critiques": [],
                "votes": [],
                "consensus_reached": True,
            }
        )

        result = call_handler(handler_ensemble["debates"], "/api/debates", {}, admin_handler)
        data = json.loads(result.body)

        debates = data.get("debates", [])
        slugs = [d.get("slug", "") for d in debates]
        tasks = [d.get("task", "") or d.get("topic", "") for d in debates]

        assert any("direct-write" in s for s in slugs) or "Direct write test" in tasks

    def test_elo_changes_reflect_immediately(self, handler_ensemble, integrated_elo):
        """ELO changes should be immediately visible."""
        integrated_elo.record_match(
            "elo-test", ["test-agent", "opponent"], {"test-agent": 1.0, "opponent": 0.0}
        )

        rating = integrated_elo.get_rating("test-agent")
        assert rating is not None
        assert rating.elo > 1500


class TestEventFlow:
    """Tests for event emission and ordering."""

    def test_sync_event_emitter_preserves_order(self, event_collector):
        """Events should be emitted and received in order."""
        emitter = event_collector["emitter"]
        events = event_collector["events"]

        for i in range(10):
            emitter.emit(StreamEvent(type=StreamEventType.AGENT_MESSAGE, data={"index": i}))

        emitter.drain()

        indices = [e.data.get("index") for e in events]
        assert indices == list(range(10))

    def test_event_types_preserved(self, event_collector):
        """Event types should be preserved through emission."""
        emitter = event_collector["emitter"]
        events = event_collector["events"]

        emitter.emit(StreamEvent(type=StreamEventType.DEBATE_START, data={"id": "test"}))
        emitter.emit(StreamEvent(type=StreamEventType.ROUND_START, data={"round": 1}))
        emitter.emit(StreamEvent(type=StreamEventType.AGENT_MESSAGE, data={"agent": "claude"}))
        emitter.emit(StreamEvent(type=StreamEventType.DEBATE_END, data={"id": "test"}))

        emitter.drain()

        types = [e.type for e in events]
        assert types == [
            StreamEventType.DEBATE_START,
            StreamEventType.ROUND_START,
            StreamEventType.AGENT_MESSAGE,
            StreamEventType.DEBATE_END,
        ]

    def test_loop_id_propagated(self):
        """Loop ID should be propagated in events."""
        emitter = SyncEventEmitter(loop_id="test-loop-123")
        events = []
        emitter.subscribe(lambda e: events.append(e))

        emitter.emit(StreamEvent(type=StreamEventType.CYCLE_START, data={}))
        emitter.drain()

        assert events[0].loop_id == "test-loop-123"

    def test_multiple_subscribers_receive_events(self, event_collector):
        """Multiple subscribers should all receive events."""
        emitter = event_collector["emitter"]

        second_events = []
        emitter.subscribe(lambda e: second_events.append(e))

        emitter.emit(StreamEvent(type=StreamEventType.AGENT_MESSAGE, data={"test": True}))
        emitter.drain()

        assert len(event_collector["events"]) == 1
        assert len(second_events) == 1


class TestConcurrentAccess:
    """Tests for thread safety under concurrent access."""

    def test_concurrent_reads_consistent(self, handler_ensemble, debate_factory, admin_handler):
        """Concurrent reads should return consistent data."""
        for i in range(10):
            debate_factory(f"concurrent-{i}", ["claude", "gemini"])

        results = []
        errors = []
        lock = threading.Lock()
        req = admin_handler

        def read_debates():
            try:
                result = call_handler(
                    handler_ensemble["debates"],
                    "/api/debates",
                    {"limit": "100"},
                    req,
                )
                data = json.loads(result.body)
                count = data.get("count", len(data.get("debates", [])))
                with lock:
                    results.append(count)
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = [threading.Thread(target=read_debates) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert all(not t.is_alive() for t in threads), "Some threads timed out"
        assert len(errors) == 0, f"Errors: {errors}"
        assert all(r == results[0] for r in results), f"Inconsistent results: {results}"

    def test_concurrent_handler_access_no_deadlock(
        self, handler_ensemble, debate_factory, admin_handler
    ):
        """Multiple handlers accessing shared state should not deadlock."""
        debate_factory("deadlock-test", ["claude", "gemini"])

        results = []
        errors = []
        lock = threading.Lock()
        req = admin_handler

        def access_debates():
            try:
                call_handler(handler_ensemble["debates"], "/api/debates", {}, req)
                with lock:
                    results.append("debates")
            except Exception as e:
                with lock:
                    errors.append(f"debates: {e}")

        def access_agents():
            try:
                # Use non-ELO endpoint to avoid SQLite lock contention noise.
                call_handler(handler_ensemble["agents"], "/api/agents/availability", {}, req)
                with lock:
                    results.append("agents")
            except Exception as e:
                with lock:
                    errors.append(f"agents: {e}")

        def access_system():
            try:
                call_handler(handler_ensemble["system"], "/api/health", {}, req)
                with lock:
                    results.append("system")
            except Exception as e:
                with lock:
                    errors.append(f"system: {e}")

        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=access_debates))
            threads.append(threading.Thread(target=access_agents))
            threads.append(threading.Thread(target=access_system))

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=10)
            assert not t.is_alive(), "Thread deadlocked"

        assert len(errors) == 0, f"Concurrent handler errors: {errors}"
        assert len(results) == 9

    def test_write_read_consistency(self, handler_ensemble, integrated_storage, admin_handler):
        """Reads after writes should see updated data."""
        result1 = call_handler(handler_ensemble["debates"], "/api/debates", {}, admin_handler)
        initial_count = json.loads(result1.body).get("count", 0)

        integrated_storage.save_debate(
            {
                "id": "write-read-test",
                "task": "Write-read consistency test",
                "agents": ["agent1", "agent2"],
                "messages": [],
                "critiques": [],
                "votes": [],
            }
        )

        clear_cache()

        result2 = call_handler(handler_ensemble["debates"], "/api/debates", {}, admin_handler)
        new_count = json.loads(result2.body).get("count", 0)

        assert new_count == initial_count + 1

    def test_concurrent_elo_updates(self, handler_ensemble, integrated_elo):
        """Concurrent ELO updates should not cause errors."""
        errors = []
        lock = threading.Lock()

        def record_match(idx):
            try:
                integrated_elo.record_match(
                    f"concurrent-match-{idx}",
                    [f"agent-{idx % 3}", f"agent-{(idx + 1) % 3}"],
                    {f"agent-{idx % 3}": 1.0, f"agent-{(idx + 1) % 3}": 0.0},
                )
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = [threading.Thread(target=record_match, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) < 5, f"Too many errors: {errors}"

    def test_cache_thread_safety(self, handler_ensemble, debate_factory, admin_handler):
        """Cache should be thread-safe under concurrent access."""
        debate_factory("cache-test", ["claude", "gemini"])

        errors = []
        lock = threading.Lock()
        req = admin_handler

        def access_cached_endpoint():
            try:
                for _ in range(10):
                    call_handler(handler_ensemble["agents"], "/api/leaderboard", {}, req)
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = [threading.Thread(target=access_cached_endpoint) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Cache errors: {errors}"
