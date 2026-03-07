"""Integration test: playground debate caching end-to-end."""

from __future__ import annotations

import pytest

from aragora.storage.debate_store import DebateResultStore, normalize_cache_key


@pytest.fixture()
def store(tmp_path):
    return DebateResultStore(str(tmp_path / "e2e_debates.db"))


def test_same_topic_returns_cached_after_first_run(store):
    """First call stores result; second call returns cached."""
    topic = "Should we use Rust?"
    models = ["anthropic/claude-sonnet-4", "openai/gpt-4o", "google/gemini-2.0-flash-001"]
    rounds = 2

    debate_result = {
        "id": "first_run_abc",
        "topic": topic,
        "status": "completed",
        "consensus_reached": True,
        "confidence": 0.85,
        "participants": ["analyst", "critic", "synthesizer"],
        "proposals": {"analyst": "Use Rust for perf-critical paths"},
        "final_answer": "Conditional yes",
    }

    cache_key = normalize_cache_key(topic, models, rounds)

    # Simulate first debate: save result + cache index
    store.save("first_run_abc", topic, debate_result)
    store.save_cache_index(
        cache_key, "first_run_abc", topic.lower(), "|".join(sorted(models)), rounds
    )

    # Second lookup should return cached
    cached = store.get_by_cache_key(cache_key)
    assert cached is not None
    assert cached["id"] == "first_run_abc"
    assert cached["status"] == "completed"
    assert cached["consensus_reached"] is True


def test_different_topic_is_cache_miss(store):
    """Different topics produce different cache keys."""
    topic1 = "Should we use Rust?"
    topic2 = "Should we use Go?"
    models = ["model-a"]

    key1 = normalize_cache_key(topic1, models, 1)
    key2 = normalize_cache_key(topic2, models, 1)

    store.save("debate1", topic1, {"id": "debate1", "topic": topic1})
    store.save_cache_index(key1, "debate1", topic1.lower(), "model-a", 1)

    assert store.get_by_cache_key(key1) is not None
    assert store.get_by_cache_key(key2) is None


def test_different_models_is_cache_miss(store):
    """Same topic with different models is a different cache key."""
    topic = "Should we use Rust?"
    models_a = ["model-a", "model-b"]
    models_b = ["model-a", "model-c"]

    key_a = normalize_cache_key(topic, models_a, 1)
    key_b = normalize_cache_key(topic, models_b, 1)

    store.save("d1", topic, {"id": "d1"})
    store.save_cache_index(key_a, "d1", topic.lower(), "|".join(sorted(models_a)), 1)

    assert store.get_by_cache_key(key_a) is not None
    assert store.get_by_cache_key(key_b) is None


def test_different_rounds_is_cache_miss(store):
    """Same topic and models but different rounds is a different key."""
    topic = "topic"
    models = ["model-a"]

    key1 = normalize_cache_key(topic, models, 1)
    key2 = normalize_cache_key(topic, models, 2)

    store.save("d1", topic, {"id": "d1"})
    store.save_cache_index(key1, "d1", topic.lower(), "model-a", 1)

    assert store.get_by_cache_key(key1) is not None
    assert store.get_by_cache_key(key2) is None


def test_cache_survives_whitespace_and_case_variation(store):
    """Cache hit even with different whitespace/casing on topic."""
    topic_original = "Should We Use Rust?"
    topic_variant = "  should   we   use   rust?  "
    models = ["m-a", "m-b"]
    rounds = 1

    key_original = normalize_cache_key(topic_original, models, rounds)
    key_variant = normalize_cache_key(topic_variant, models, rounds)
    assert key_original == key_variant

    store.save("d1", topic_original, {"id": "d1", "topic": topic_original})
    store.save_cache_index(
        key_original, "d1", "should we use rust?", "|".join(sorted(models)), rounds
    )

    cached = store.get_by_cache_key(key_variant)
    assert cached is not None
    assert cached["id"] == "d1"


def test_expired_debate_is_cache_miss(store):
    """Expired debate results should not be returned from cache."""
    topic = "expired topic"
    models = ["m"]
    key = normalize_cache_key(topic, models, 1)

    store.save("exp1", topic, {"id": "exp1"}, ttl_days=0)  # expires immediately
    store.save_cache_index(key, "exp1", topic, "m", 1)

    # Should be None because the underlying debate expired
    assert store.get_by_cache_key(key) is None


def test_hit_count_increments(store):
    """Multiple cache hits increment the counter."""
    topic = "counting"
    models = ["m"]
    key = normalize_cache_key(topic, models, 1)

    store.save("c1", topic, {"id": "c1"})
    store.save_cache_index(key, "c1", topic, "m", 1)

    for _ in range(5):
        store.get_by_cache_key(key)

    with store.connection() as conn:
        row = conn.execute(
            "SELECT hit_count FROM debate_cache_index WHERE cache_key = ?",
            (key,),
        ).fetchone()
    assert row[0] == 5
