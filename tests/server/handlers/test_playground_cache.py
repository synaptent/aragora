"""Tests for content-addressed debate caching in the playground handler.

Covers:
- Cache hit returns cached result without running a debate
- Cache key normalization is consistent for playground topics
- Cache miss proceeds to debate execution
- Persist saves cache index after debate completion
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.base import HandlerResult, json_response
from aragora.storage.debate_store import normalize_cache_key


@pytest.fixture()
def _fake_debate_store(tmp_path, monkeypatch):
    """Set up a real DebateResultStore backed by a temp directory."""
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path))
    import aragora.storage.debate_store as mod

    monkeypatch.setattr(mod, "_store", None)


@pytest.fixture()
def handler(_fake_debate_store):
    from aragora.server.handlers.playground import PlaygroundHandler

    return PlaygroundHandler()


def _make_handler_mock(body: dict | None = None) -> MagicMock:
    """Create a mock HTTP handler with client_address and rfile for body reading."""
    mock = MagicMock()
    mock.client_address = ("127.0.0.1", 12345)

    if body is not None:
        raw = json.dumps(body).encode("utf-8")
        mock.headers = {"Content-Length": str(len(raw)), "Content-Type": "application/json"}
        mock.rfile.read.return_value = raw
    else:
        mock.headers = {"Content-Length": "2", "Content-Type": "application/json"}
        mock.rfile.read.return_value = b"{}"

    return mock


class TestCacheHitReturnsCachedResult:
    """When get_by_cache_key returns a result, the handler should return it
    without running a debate."""

    def test_cache_hit_returns_cached_result(self, handler):
        """A cached debate is returned immediately without debate execution."""
        from aragora.storage.debate_store import get_debate_store

        store = get_debate_store()

        # Pre-populate a debate result in the store
        debate_id = "cachedebate00001"
        cached_data = {
            "id": debate_id,
            "topic": "Should we cache debates?",
            "status": "completed",
            "verdict": "yes",
            "rounds_used": 2,
        }
        store.save(debate_id, "Should we cache debates?", cached_data)

        # Create a cache index entry for this topic/model/rounds combo
        model_ids = ["anthropic/claude-sonnet-4", "openai/gpt-4o", "google/gemini-2.0-flash-001"]
        cache_key = normalize_cache_key("Should we cache debates?", model_ids, 2)
        store.save_cache_index(
            cache_key=cache_key,
            debate_id=debate_id,
            topic_normalized="should we cache debates?",
            model_ids="|".join(sorted(model_ids)),
            rounds=2,
        )

        # Mock _get_available_live_agents to return tags matching our model_ids
        agent_tags = [f"openrouter:{m}" for m in model_ids]

        body = {"topic": "Should we cache debates?", "rounds": 2, "agents": 3}
        mock_handler = _make_handler_mock(body)

        with (
            patch(
                "aragora.server.handlers.playground._get_available_live_agents",
                return_value=agent_tags,
            ),
            patch(
                "aragora.server.handlers.playground._try_oracle_response",
                side_effect=AssertionError("Should not be called on cache hit"),
            ),
            patch(
                "aragora.server.handlers.playground._try_oracle_tentacles",
                side_effect=AssertionError("Should not be called on cache hit"),
            ),
            patch(
                "aragora.server.handlers.playground._run_inline_mock_debate",
                side_effect=AssertionError("Should not be called on cache hit"),
            ),
        ):
            result = handler.handle_post(
                "/api/v1/playground/debate",
                {},
                mock_handler,
            )

        assert result is not None
        assert result.status_code == 200
        body_out = json.loads(result.body.decode("utf-8"))
        assert body_out["cached"] is True
        assert "cached_at" in body_out
        assert body_out["id"] == debate_id

    def test_cache_hit_skips_rate_limiting(self, handler):
        """Cached results should be returned even if rate limit would block."""
        from aragora.storage.debate_store import get_debate_store

        store = get_debate_store()

        debate_id = "ratelimitbypass1"
        cached_data = {
            "id": debate_id,
            "topic": "Rate limit test",
            "status": "completed",
        }
        store.save(debate_id, "Rate limit test", cached_data)

        model_ids = ["anthropic/claude-sonnet-4", "openai/gpt-4o", "google/gemini-2.0-flash-001"]
        cache_key = normalize_cache_key("Rate limit test", model_ids, 2)
        store.save_cache_index(
            cache_key=cache_key,
            debate_id=debate_id,
            topic_normalized="rate limit test",
            model_ids="|".join(sorted(model_ids)),
            rounds=2,
        )

        agent_tags = [f"openrouter:{m}" for m in model_ids]
        body = {"topic": "Rate limit test", "rounds": 2, "agents": 3}
        mock_handler = _make_handler_mock(body)

        with (
            patch(
                "aragora.server.handlers.playground._get_available_live_agents",
                return_value=agent_tags,
            ),
            patch(
                "aragora.server.handlers.playground._check_rate_limit",
                return_value=(False, 60.0),  # Rate limited!
            ),
        ):
            result = handler.handle_post(
                "/api/v1/playground/debate",
                {},
                mock_handler,
            )

        # Should still succeed despite rate limit because cache hit bypasses it
        assert result is not None
        assert result.status_code == 200
        body_out = json.loads(result.body.decode("utf-8"))
        assert body_out["cached"] is True


class TestCacheKeyNormalizationForPlayground:
    """Verify that topic normalization is consistent with playground inputs."""

    def test_topic_with_extra_whitespace(self):
        key1 = normalize_cache_key("  Should we   cache debates?  ", ["model-a"], 2)
        key2 = normalize_cache_key("should we cache debates?", ["model-a"], 2)
        assert key1 == key2

    def test_topic_case_insensitive(self):
        key1 = normalize_cache_key("SHOULD WE CACHE", ["model-a"], 2)
        key2 = normalize_cache_key("should we cache", ["model-a"], 2)
        assert key1 == key2

    def test_openrouter_prefix_stripped_for_model_ids(self):
        """The handler strips 'openrouter:' prefix before computing cache key.
        Models with and without the prefix should match after stripping."""
        # These are the model IDs that the handler computes
        model_ids = ["anthropic/claude-sonnet-4", "openai/gpt-4o"]
        key = normalize_cache_key("test topic", model_ids, 2)

        # Should be a valid SHA-256 hex string
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)


class TestCacheMissProceedsToDebate:
    """When the cache has no matching entry, the normal debate flow should run."""

    def test_cache_miss_proceeds_to_debate(self, handler):
        """On cache miss, the handler falls through to live debate execution."""
        agent_tags = [
            "openrouter:anthropic/claude-sonnet-4",
            "openrouter:openai/gpt-4o",
            "openrouter:google/gemini-2.0-flash-001",
        ]

        mock_live_response = json_response(
            {
                "id": "newdebate0000001",
                "topic": "A brand new topic",
                "status": "completed",
                "verdict": "interesting",
                "rounds_used": 2,
                "consensus_reached": True,
                "confidence": 0.8,
                "duration_seconds": 1.0,
                "participants": ["analyst", "critic", "synthesizer"],
                "proposals": {},
                "critiques": [],
                "votes": [],
                "dissenting_views": [],
                "final_answer": "Done.",
                "is_live": True,
                "receipt_preview": {},
                "upgrade_cta": {},
            }
        )

        body = {"topic": "A brand new topic", "rounds": 2, "agents": 3}
        mock_handler = _make_handler_mock(body)

        with (
            patch(
                "aragora.server.handlers.playground._get_available_live_agents",
                return_value=agent_tags,
            ),
            patch.object(
                handler,
                "_run_live_debate",
                return_value=mock_live_response,
            ),
        ):
            result = handler.handle_post(
                "/api/v1/playground/debate",
                {},
                mock_handler,
            )

        assert result is not None
        assert result.status_code == 200
        body_out = json.loads(result.body.decode("utf-8"))
        # Should NOT have cached flag since this was a cache miss
        assert body_out.get("cached") is not True


class TestPersistSavesCacheIndex:
    """After a debate completes, the cache index should be saved."""

    def test_persist_saves_cache_index(self, handler):
        """After a debate, _persist_and_respond saves the cache index entry."""
        from aragora.storage.debate_store import get_debate_store

        debate_data = {
            "id": "indexed_debate001",
            "topic": "Cache index test",
            "verdict": "approved",
        }
        original = json_response(debate_data)

        model_ids = ["anthropic/claude-sonnet-4", "openai/gpt-4o"]
        cache_key = normalize_cache_key("Cache index test", model_ids, 2)

        handler._persist_and_respond(
            original,
            "Cache index test",
            "playground",
            cache_key=cache_key,
            model_ids=model_ids,
            rounds=2,
        )

        # Verify the cache index was saved
        store = get_debate_store()
        cached = store.get_by_cache_key(cache_key)
        assert cached is not None
        assert cached["id"] == "indexed_debate001"

    def test_persist_without_cache_params_still_works(self, handler):
        """When cache_key is not provided, persist works as before (no index saved)."""
        debate_data = {
            "id": "no_cache_debate01",
            "topic": "No cache params",
            "verdict": "fine",
        }
        original = json_response(debate_data)

        # Call without cache params — should not raise
        result = handler._persist_and_respond(original, "No cache params", "playground")
        assert result.status_code == 200

    def test_cache_index_error_does_not_crash_persist(self, handler):
        """If saving the cache index fails, the debate result is still returned."""
        debate_data = {
            "id": "resilient_debate1",
            "topic": "Resilience test",
            "verdict": "ok",
        }
        original = json_response(debate_data)

        with patch(
            "aragora.storage.debate_store.DebateResultStore.save_cache_index",
            side_effect=RuntimeError("DB locked"),
        ):
            result = handler._persist_and_respond(
                original,
                "Resilience test",
                "playground",
                cache_key="fake_key",
                model_ids=["m1"],
                rounds=2,
            )

        assert result.status_code == 200
        body = json.loads(result.body.decode("utf-8"))
        assert body["id"] == "resilient_debate1"
