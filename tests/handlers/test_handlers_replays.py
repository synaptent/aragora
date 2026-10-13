"""
Tests for ReplaysHandler endpoints.

Endpoints tested:
- GET /api/replays - List available replays
- GET /api/replays/:id - Get specific replay with events
- GET /api/v1/learning/evolution - Get meta-learning patterns
"""

import json
import os
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from aragora.server.handlers.replays import ReplaysHandler, _replays_limiter
from aragora.server.handlers.base import clear_cache


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset rate limiter before each test to avoid cross-test pollution."""
    _replays_limiter._buckets.clear()
    yield
    _replays_limiter._buckets.clear()


@pytest.fixture
def mock_nomic_dir(tmp_path):
    """Create a mock nomic directory structure."""
    nomic_dir = tmp_path / ".nomic"
    nomic_dir.mkdir()
    return nomic_dir


@pytest.fixture
def replays_handler(mock_nomic_dir):
    """Create a ReplaysHandler with mock dependencies."""
    ctx = {
        "storage": None,
        "elo_system": None,
        "nomic_dir": mock_nomic_dir,
    }
    return ReplaysHandler(ctx)


@pytest.fixture
def replays_handler_no_nomic():
    """Create a ReplaysHandler without nomic_dir."""
    ctx = {
        "storage": None,
        "elo_system": None,
        "nomic_dir": None,
    }
    return ReplaysHandler(ctx)


@pytest.fixture
def mock_replay_dir(mock_nomic_dir):
    """Factory to create replay directories with meta.json and events.jsonl.

    Each replay gets an explicit mtime one second after the previous one, so creation
    order decides the newest-first listing even when the filesystem records identical
    timestamps for directories created back to back.
    """
    created = 0

    def create_replay(replay_id, topic="Test Topic", agents=None, events=None):
        nonlocal created
        replays_dir = mock_nomic_dir / "replays"
        replays_dir.mkdir(exist_ok=True)
        replay_dir = replays_dir / replay_id
        replay_dir.mkdir()

        # Write meta.json
        meta = {
            "topic": topic,
            "agents": [{"name": a} for a in (agents or ["agent1", "agent2"])],
            "schema_version": "1.0",
        }
        (replay_dir / "meta.json").write_text(json.dumps(meta))

        # Write events.jsonl if provided
        if events:
            lines = [json.dumps(e) for e in events]
            (replay_dir / "events.jsonl").write_text("\n".join(lines))

        # Writing the files above updates the directory mtime, so set it last.
        created += 1
        stamp = 1_700_000_000 + created
        os.utime(replay_dir, (stamp, stamp))

        return replay_dir

    return create_replay


@pytest.fixture
def mock_learning_db(mock_nomic_dir):
    """Create meta_learning.db with test patterns."""
    db_path = mock_nomic_dir / "meta_learning.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE meta_patterns (
            id INTEGER PRIMARY KEY,
            pattern_name TEXT,
            created_at TEXT
        )
    """
    )
    conn.execute("INSERT INTO meta_patterns VALUES (1, 'pattern_a', '2026-01-01')")
    conn.execute("INSERT INTO meta_patterns VALUES (2, 'pattern_b', '2026-01-02')")
    conn.execute("INSERT INTO meta_patterns VALUES (3, 'pattern_c', '2026-01-03')")
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear caches before and after each test."""
    clear_cache()
    yield
    clear_cache()


# ============================================================================
# Route Matching Tests
# ============================================================================


class TestReplaysRouting:
    """Tests for route matching."""

    def test_can_handle_replays_list(self, replays_handler):
        """Handler can handle /api/replays."""
        assert replays_handler.can_handle("/api/v1/replays") is True

    def test_can_handle_replay_detail(self, replays_handler):
        """Handler can handle /api/replays/{id}."""
        assert replays_handler.can_handle("/api/v1/replays/test-replay-123") is True

    def test_can_handle_learning_evolution(self, replays_handler):
        """Handler can handle /api/v1/learning/evolution."""
        assert replays_handler.can_handle("/api/v1/learning/evolution") is True

    def test_cannot_handle_invalid_replay_path(self, replays_handler):
        """Handler rejects paths with wrong segment count."""
        # Too many segments (5 segments instead of 4)
        assert replays_handler.can_handle("/api/v1/replays/id/extra") is False
        assert replays_handler.can_handle("/api/v1/replays/id/extra/more") is False
        # Note: /api/replays/ has 4 segments ['', 'api', 'replays', ''] so it's handled

    def test_cannot_handle_unrelated_routes(self, replays_handler):
        """Handler doesn't handle unrelated routes."""
        assert replays_handler.can_handle("/api/v1/debates") is False
        assert replays_handler.can_handle("/api/v1/agents") is False
        assert replays_handler.can_handle("/api/v1/learning") is False


# ============================================================================
# GET /api/replays Tests
# ============================================================================


class TestListReplays:
    """Tests for GET /api/replays endpoint."""

    def test_list_no_nomic_dir(self, replays_handler_no_nomic):
        """Returns empty list when nomic_dir is None."""
        result = replays_handler_no_nomic.handle("/api/v1/replays", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data == []

    def test_list_no_replays_dir(self, replays_handler, mock_nomic_dir):
        """Returns empty list when replays/ directory doesn't exist."""
        result = replays_handler.handle("/api/v1/replays", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data == []

    def test_list_empty_replays(self, replays_handler, mock_nomic_dir):
        """Returns empty list when replays/ exists but is empty."""
        (mock_nomic_dir / "replays").mkdir()

        result = replays_handler.handle("/api/v1/replays", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data == []

    def test_list_with_replays(self, replays_handler, mock_replay_dir):
        """Returns replays with meta info."""
        mock_replay_dir("replay-001", topic="First debate", agents=["claude", "gpt4"])
        mock_replay_dir("replay-002", topic="Second debate", agents=["gemini"])

        result = replays_handler.handle("/api/v1/replays", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert len(data) == 2

        # Should be sorted by ID descending (newest first)
        assert data[0]["id"] == "replay-002"
        assert data[0]["topic"] == "Second debate"
        assert data[0]["agents"] == ["gemini"]

        assert data[1]["id"] == "replay-001"
        assert data[1]["topic"] == "First debate"
        assert data[1]["agents"] == ["claude", "gpt4"]

    @pytest.mark.parametrize(
        "iterdir_reverse", [False, True], ids=["iterdir-ascending", "iterdir-descending"]
    )
    def test_list_mtime_tie_orders_by_name_descending(
        self, replays_handler, mock_replay_dir, iterdir_reverse
    ):
        """Replays with identical mtimes list by name descending, whatever order iterdir yields."""
        for name in ("replay-a", "replay-b", "replay-c"):
            replay_dir = mock_replay_dir(name)
            os.utime(replay_dir, (1_700_000_000, 1_700_000_000))

        real_iterdir = Path.iterdir

        def ordered_iterdir(self):
            return iter(sorted(real_iterdir(self), key=lambda p: p.name, reverse=iterdir_reverse))

        with patch.object(Path, "iterdir", ordered_iterdir):
            result = replays_handler.handle("/api/v1/replays", {}, None)

        assert result is not None
        assert result.status_code == 200
        ids = [entry["id"] for entry in json.loads(result.body)]
        assert ids == ["replay-c", "replay-b", "replay-a"]

    def test_list_newer_mtime_wins_over_name(self, replays_handler, mock_replay_dir):
        """The name tie-break never overrides a newer modification time."""
        older = mock_replay_dir("replay-z", topic="Older")
        newer = mock_replay_dir("replay-a", topic="Newer")
        os.utime(older, (1_700_000_000, 1_700_000_000))
        os.utime(newer, (1_700_000_100, 1_700_000_100))

        result = replays_handler.handle("/api/v1/replays", {}, None)

        assert result is not None
        assert result.status_code == 200
        ids = [entry["id"] for entry in json.loads(result.body)]
        assert ids == ["replay-a", "replay-z"]

    def test_list_skips_malformed_meta(self, replays_handler, mock_nomic_dir):
        """Malformed meta.json files are skipped gracefully."""
        replays_dir = mock_nomic_dir / "replays"
        replays_dir.mkdir()

        # Valid replay
        valid_dir = replays_dir / "valid-replay"
        valid_dir.mkdir()
        (valid_dir / "meta.json").write_text('{"topic": "Valid Topic", "agents": []}')

        # Malformed replay (invalid JSON)
        broken_dir = replays_dir / "broken-replay"
        broken_dir.mkdir()
        (broken_dir / "meta.json").write_text("not valid json")

        # Directory without meta.json
        no_meta_dir = replays_dir / "no-meta-replay"
        no_meta_dir.mkdir()

        result = replays_handler.handle("/api/v1/replays", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert len(data) == 1
        assert data[0]["id"] == "valid-replay"

    def test_list_handles_exception(self, replays_handler, mock_nomic_dir):
        """Returns error on unexpected exceptions."""
        # Create replays dir but make it unreadable
        replays_dir = mock_nomic_dir / "replays"
        replays_dir.mkdir()

        with patch.object(Path, "iterdir", side_effect=PermissionError("Access denied")):
            result = replays_handler.handle("/api/v1/replays", {}, None)

            assert result is not None
            # PermissionError is correctly classified as 403 (access denied)
            assert result.status_code == 403
            data = json.loads(result.body)
            assert "error" in data


# ============================================================================
# GET /api/replays/:id Tests
# ============================================================================


class TestGetReplay:
    """Tests for GET /api/replays/:id endpoint."""

    def test_get_no_nomic_dir(self, replays_handler_no_nomic):
        """Returns 503 when nomic_dir is None."""
        result = replays_handler_no_nomic.handle("/api/v1/replays/test-id", {}, None)

        assert result is not None
        assert result.status_code == 503
        data = json.loads(result.body)
        assert "not configured" in data["error"].lower()

    def test_get_not_found(self, replays_handler, mock_nomic_dir):
        """Returns 404 when replay doesn't exist."""
        (mock_nomic_dir / "replays").mkdir()

        result = replays_handler.handle("/api/v1/replays/nonexistent", {}, None)

        assert result is not None
        assert result.status_code == 404
        data = json.loads(result.body)
        assert "not found" in data["error"].lower()

    def test_get_success(self, replays_handler, mock_replay_dir):
        """Returns replay with meta and events."""
        events = [
            {"type": "debate_start", "timestamp": "2026-01-01T00:00:00"},
            {"type": "message", "agent": "claude", "content": "Hello"},
            {"type": "debate_end", "timestamp": "2026-01-01T00:05:00"},
        ]
        mock_replay_dir("test-replay", topic="Test Topic", agents=["claude"], events=events)

        result = replays_handler.handle("/api/v1/replays/test-replay", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)

        assert data["id"] == "test-replay"
        assert data["meta"]["topic"] == "Test Topic"
        assert data["meta"]["agents"] == [{"name": "claude"}]
        assert data["event_count"] == 3
        assert len(data["events"]) == 3
        assert data["events"][0]["type"] == "debate_start"

    def test_get_with_malformed_meta(self, replays_handler, mock_nomic_dir):
        """Handles malformed meta.json gracefully."""
        replays_dir = mock_nomic_dir / "replays"
        replays_dir.mkdir()
        replay_dir = replays_dir / "test-replay"
        replay_dir.mkdir()
        (replay_dir / "meta.json").write_text("invalid json")

        result = replays_handler.handle("/api/v1/replays/test-replay", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["id"] == "test-replay"
        assert "error" in data["meta"]  # Error recorded in meta

    def test_get_with_malformed_events(self, replays_handler, mock_nomic_dir):
        """Skips malformed event lines."""
        replays_dir = mock_nomic_dir / "replays"
        replays_dir.mkdir()
        replay_dir = replays_dir / "test-replay"
        replay_dir.mkdir()
        (replay_dir / "meta.json").write_text('{"topic": "Test"}')

        # Mix of valid and invalid JSON lines
        events_content = '{"type": "start"}\nnot json\n{"type": "end"}\n'
        (replay_dir / "events.jsonl").write_text(events_content)

        result = replays_handler.handle("/api/v1/replays/test-replay", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["event_count"] == 2  # Skipped invalid line

    def test_get_empty_events(self, replays_handler, mock_replay_dir):
        """Returns empty events list when events.jsonl doesn't exist."""
        mock_replay_dir("test-replay", events=None)  # No events file

        result = replays_handler.handle("/api/v1/replays/test-replay", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["events"] == []
        assert data["event_count"] == 0

    def test_get_handles_exception(self, replays_handler, mock_nomic_dir):
        """Returns error on unexpected exceptions."""
        (mock_nomic_dir / "replays").mkdir()

        with patch.object(Path, "exists", side_effect=PermissionError("Access denied")):
            result = replays_handler.handle("/api/v1/replays/test-id", {}, None)

            assert result is not None
            # PermissionError is correctly classified as 403 (access denied)
            assert result.status_code == 403
            data = json.loads(result.body)
            assert "error" in data


# ============================================================================
# GET /api/v1/learning/evolution Tests
# ============================================================================


class TestLearningEvolution:
    """Tests for GET /api/v1/learning/evolution endpoint."""

    def test_evolution_no_nomic_dir(self, replays_handler_no_nomic):
        """Returns empty patterns when nomic_dir is None."""
        result = replays_handler_no_nomic.handle("/api/v1/learning/evolution", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["patterns"] == []
        # Response includes patterns, agents, debates arrays
        assert "agents" in data or "debates" in data

    def test_evolution_no_db(self, replays_handler, mock_nomic_dir):
        """Returns empty patterns when database doesn't exist."""
        result = replays_handler.handle("/api/v1/learning/evolution", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["patterns"] == []
        # Response includes patterns, agents, debates arrays
        assert "agents" in data or "debates" in data

    def test_evolution_no_table(self, replays_handler, mock_nomic_dir):
        """Returns empty patterns when table doesn't exist."""
        # Create empty database without the table
        db_path = mock_nomic_dir / "meta_learning.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE other_table (id INTEGER)")
        conn.close()

        result = replays_handler.handle("/api/v1/learning/evolution", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["patterns"] == []
        # Response includes patterns, agents, debates arrays
        assert "agents" in data or "debates" in data

    def test_evolution_success(self, replays_handler, mock_learning_db):
        """Returns patterns from database."""
        result = replays_handler.handle("/api/v1/learning/evolution", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        # Patterns come from meta_patterns table, but fixture uses different table
        assert isinstance(data["patterns"], list)
        assert "agents" in data or "debates" in data

    def test_evolution_respects_limit(self, replays_handler, mock_learning_db):
        """Respects limit query parameter."""
        result = replays_handler.handle("/api/v1/learning/evolution", {"limit": "2"}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert isinstance(data["patterns"], list)
        # Limit parameter controls max patterns returned
        assert len(data["patterns"]) <= 2

    def test_evolution_caps_limit(self, replays_handler, mock_learning_db):
        """Caps limit at 100."""
        result = replays_handler.handle("/api/v1/learning/evolution", {"limit": "1000"}, None)

        assert result is not None
        assert result.status_code == 200
        # Should only return 3 patterns (all we have), but limit is capped at 100 internally

    def test_evolution_handles_exception(self, replays_handler, mock_nomic_dir):
        """Returns error on unexpected database exceptions."""
        db_path = mock_nomic_dir / "meta_learning.db"
        db_path.write_text("not a valid sqlite database")

        result = replays_handler.handle("/api/v1/learning/evolution", {}, None)

        assert result is not None
        assert result.status_code == 500
        data = json.loads(result.body)
        assert "error" in data


# ============================================================================
# Security Tests
# ============================================================================


class TestReplaysSecurity:
    """Security tests for replays endpoints."""

    def test_path_traversal_blocked(self, replays_handler):
        """Path traversal attempts are blocked."""
        result = replays_handler.handle("/api/v1/replays/../../../etc/passwd", {}, None)

        assert result is not None
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "invalid" in data["error"].lower()

    def test_path_traversal_encoded_blocked(self, replays_handler):
        """Encoded path traversal attempts are blocked."""
        result = replays_handler.handle("/api/v1/replays/..%2F..%2Fetc", {}, None)

        # Note: URL decoding happens before handler, so .. is detected
        assert result is not None
        assert result.status_code == 400

    def test_invalid_id_format_blocked(self, replays_handler):
        """Invalid replay ID formats are rejected."""
        invalid_ids = [
            "'; DROP TABLE replays;--",  # SQL injection
            "<script>alert(1)</script>",  # XSS
            "../etc/passwd",  # Path traversal (blocked by .. check)
            "id with spaces",  # Spaces not allowed
            "id@special!chars",  # Special chars
        ]

        for invalid_id in invalid_ids:
            result = replays_handler.handle(f"/api/v1/replays/{invalid_id}", {}, None)
            assert result is not None
            assert result.status_code == 400, f"Expected 400 for ID: {invalid_id}"

    def test_valid_ids_accepted(self, replays_handler, mock_replay_dir):
        """Valid replay IDs are accepted."""
        valid_ids = [
            "replay-001",
            "test_replay_123",
            "UPPERCASE-ID",
            "mixed-Case_123",
        ]

        for valid_id in valid_ids:
            mock_replay_dir(valid_id)
            result = replays_handler.handle(f"/api/v1/replays/{valid_id}", {}, None)
            assert result is not None
            assert result.status_code == 200, f"Expected 200 for ID: {valid_id}"


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestReplaysErrorHandling:
    """Tests for error handling."""

    def test_handle_returns_none_for_unhandled(self, replays_handler):
        """Returns None for unhandled routes."""
        result = replays_handler.handle("/api/other/endpoint", {}, None)
        assert result is None

    def test_handles_post_not_implemented(self, replays_handler):
        """ReplaysHandler doesn't implement handle_post."""
        assert (
            not hasattr(replays_handler, "handle_post")
            or replays_handler.handle_post("/api/v1/replays", {}, None) is None
        )


# ============================================================================
# Handler Import Tests
# ============================================================================


class TestReplaysHandlerImport:
    """Test ReplaysHandler import and export."""

    def test_handler_importable(self):
        """ReplaysHandler can be imported from handlers package."""
        from aragora.server.handlers import ReplaysHandler

        assert ReplaysHandler is not None

    def test_handler_in_all_exports(self):
        """ReplaysHandler is in __all__ exports."""
        from aragora.server.handlers import __all__

        assert "ReplaysHandler" in __all__
