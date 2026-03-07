"""Tests for content-addressed debate cache index."""

from __future__ import annotations

import time

import pytest

from aragora.storage.debate_store import DebateResultStore, normalize_cache_key


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Create a fresh DebateResultStore backed by a temp directory."""
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path))
    return DebateResultStore("test_debate_cache.db")


class TestNormalizeCacheKey:
    def test_strips_and_lowercases(self):
        key1 = normalize_cache_key("  Hello World  ", ["model-a"], 3)
        key2 = normalize_cache_key("hello world", ["model-a"], 3)
        assert key1 == key2

    def test_collapses_whitespace(self):
        key1 = normalize_cache_key("hello   world", ["model-a"], 3)
        key2 = normalize_cache_key("hello world", ["model-a"], 3)
        assert key1 == key2

    def test_different_topics_differ(self):
        key1 = normalize_cache_key("topic one", ["model-a"], 3)
        key2 = normalize_cache_key("topic two", ["model-a"], 3)
        assert key1 != key2

    def test_different_models_differ(self):
        key1 = normalize_cache_key("topic", ["model-a"], 3)
        key2 = normalize_cache_key("topic", ["model-b"], 3)
        assert key1 != key2

    def test_different_rounds_differ(self):
        key1 = normalize_cache_key("topic", ["model-a"], 3)
        key2 = normalize_cache_key("topic", ["model-a"], 5)
        assert key1 != key2

    def test_model_order_does_not_matter(self):
        key1 = normalize_cache_key("topic", ["model-b", "model-a"], 3)
        key2 = normalize_cache_key("topic", ["model-a", "model-b"], 3)
        assert key1 == key2

    def test_returns_hex_string(self):
        key = normalize_cache_key("topic", ["model-a"], 3)
        assert isinstance(key, str)
        # SHA-256 hex digest is 64 characters
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)


class TestCacheIndex:
    def test_save_and_get_round_trip(self, store):
        result = {"topic": "Cache test", "rounds": [{"round": 1}], "id": "d1"}
        store.save("d1", "Cache test", result)

        cache_key = normalize_cache_key("Cache test", ["model-a", "model-b"], 3)
        store.save_cache_index(
            cache_key=cache_key,
            debate_id="d1",
            topic_normalized="cache test",
            model_ids="model-a|model-b",
            rounds=3,
        )

        cached = store.get_by_cache_key(cache_key)
        assert cached is not None
        assert cached["topic"] == "Cache test"
        assert cached["id"] == "d1"

    def test_get_by_cache_key_returns_none_on_miss(self, store):
        result = store.get_by_cache_key("nonexistent_key_abc123")
        assert result is None

    def test_expired_debate_returns_cache_miss(self, store):
        result = {"topic": "Expiring", "id": "exp1"}
        store.save("exp1", "Expiring", result, ttl_days=0)

        cache_key = normalize_cache_key("Expiring", ["model-a"], 3)
        store.save_cache_index(
            cache_key=cache_key,
            debate_id="exp1",
            topic_normalized="expiring",
            model_ids="model-a",
            rounds=3,
        )

        time.sleep(0.01)
        cached = store.get_by_cache_key(cache_key)
        assert cached is None

        # Orphaned index row should be cleaned up
        with store.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM debate_cache_index WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        assert row is None

    def test_hit_count_increments(self, store):
        result = {"topic": "Hits", "id": "h1"}
        store.save("h1", "Hits", result)

        cache_key = normalize_cache_key("Hits", ["model-a"], 3)
        store.save_cache_index(
            cache_key=cache_key,
            debate_id="h1",
            topic_normalized="hits",
            model_ids="model-a",
            rounds=3,
        )

        # First access
        store.get_by_cache_key(cache_key)
        # Second access
        store.get_by_cache_key(cache_key)
        # Third access
        store.get_by_cache_key(cache_key)

        with store.connection() as conn:
            row = conn.execute(
                "SELECT hit_count FROM debate_cache_index WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        assert row is not None
        assert row[0] == 3

    def test_save_cache_index_replaces_existing(self, store):
        result1 = {"topic": "V1", "id": "v1"}
        result2 = {"topic": "V2", "id": "v2"}
        store.save("v1", "V1", result1)
        store.save("v2", "V2", result2)

        cache_key = normalize_cache_key("Same topic", ["model-a"], 3)

        store.save_cache_index(
            cache_key=cache_key,
            debate_id="v1",
            topic_normalized="same topic",
            model_ids="model-a",
            rounds=3,
        )
        store.save_cache_index(
            cache_key=cache_key,
            debate_id="v2",
            topic_normalized="same topic",
            model_ids="model-a",
            rounds=3,
        )

        cached = store.get_by_cache_key(cache_key)
        assert cached is not None
        assert cached["id"] == "v2"
