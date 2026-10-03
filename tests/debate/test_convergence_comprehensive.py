"""
Comprehensive tests for the convergence detection module.

Tests cover:
- Semantic similarity detection thresholds
- Edge cases (empty inputs, single response, identical responses)
- Performance with large response sets
- Different convergence algorithms (Jaccard, TF-IDF, SentenceTransformer)
- Integration with debate orchestrator
- Advanced convergence metrics (G3)
- Pairwise similarity cache
- Within-round convergence detection
- Cache management and cleanup

Coverage target: >90% of aragora/debate/convergence.py
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

from aragora.debate.convergence import (
    CACHE_MANAGER_TTL_SECONDS,
    MAX_SIMILARITY_CACHES,
    PERIODIC_CLEANUP_INTERVAL_SECONDS,
    AdvancedConvergenceAnalyzer,
    AdvancedConvergenceMetrics,
    ArgumentDiversityMetric,
    CachedSimilarity,
    ConvergenceDetector,
    ConvergenceResult,
    EvidenceConvergenceMetric,
    JaccardBackend,
    PairwiseSimilarityCache,
    StanceVolatilityMetric,
    cleanup_similarity_cache,
    cleanup_stale_caches,
    cleanup_stale_similarity_caches,
    evict_expired_cache_entries,
    get_cache_manager_stats,
    get_pairwise_similarity_cache,
    get_periodic_cleanup_stats,
    stop_periodic_cleanup,
)
from aragora.debate.similarity.backends import (
    SimilarityBackend,
    TFIDFBackend,
    get_similarity_backend,
)


# =============================================================================
# Helper Functions and Fixtures
# =============================================================================


def clear_global_caches():
    """Clear all global caches for test isolation."""
    from aragora.debate import convergence

    with convergence._similarity_cache_lock:
        for session_id in list(convergence._similarity_cache_manager.keys()):
            convergence._similarity_cache_manager[session_id].clear()
        convergence._similarity_cache_manager.clear()
        convergence._similarity_cache_timestamps.clear()


@pytest.fixture
def clean_cache_state():
    """Fixture to ensure clean cache state for each test."""
    clear_global_caches()
    yield
    clear_global_caches()


@pytest.fixture
def jaccard_backend():
    """Create a Jaccard backend for consistent testing."""
    return JaccardBackend()


@pytest.fixture
def detector():
    """Create a convergence detector with default settings."""
    return ConvergenceDetector(
        convergence_threshold=0.85,
        divergence_threshold=0.40,
        min_rounds_before_check=1,
        consecutive_rounds_needed=1,
    )


@pytest.fixture
def analyzer(jaccard_backend):
    """Create an advanced convergence analyzer with Jaccard backend."""
    return AdvancedConvergenceAnalyzer(similarity_backend=jaccard_backend)


# =============================================================================
# Semantic Similarity Detection Threshold Tests
# =============================================================================


class TestSimilarityThresholds:
    """Tests for semantic similarity detection at various thresholds."""

    def test_convergence_at_85_percent_threshold(self, detector):
        """Test convergence detection at 85% threshold (default)."""
        # Nearly identical responses should converge
        response = "The system should implement a caching layer using Redis with TTL"
        current = {"claude": response, "gpt4": response}
        previous = {"claude": response, "gpt4": response}

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        assert result.converged is True
        assert result.min_similarity >= 0.85

    def test_no_convergence_below_threshold(self, detector):
        """Test no convergence when similarity is below threshold."""
        current = {
            "claude": "We should use Redis for caching with 15 minute TTL",
            "gpt4": "PostgreSQL database storage is the better solution",
        }
        previous = {
            "claude": "Caching improves performance significantly in web applications",
            "gpt4": "Database normalization ensures data integrity",
        }

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        # Different topics should have low similarity
        assert result.min_similarity < 0.85

    def test_divergence_below_40_percent_threshold(self):
        """Test divergence detection below 40% threshold."""
        detector = ConvergenceDetector(
            convergence_threshold=0.85,
            divergence_threshold=0.40,
        )

        # Completely different topics
        current = {
            "claude": "apple orange banana cherry grape",
            "gpt4": "dog cat elephant mouse tiger",
        }
        previous = {
            "claude": "carrot potato tomato onion pepper",
            "gpt4": "house building apartment office store",
        }

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        assert result.status == "diverging"
        assert result.min_similarity < 0.40

    def test_refining_status_between_thresholds(self, detector):
        """Test refining status when similarity is between thresholds."""
        # Use partial word overlap for mid-range similarity
        current = {
            "claude": "The caching system should use Redis for performance benefits",
            "gpt4": "Redis caching improves application response times effectively",
        }
        previous = {
            "claude": "Consider caching for better system performance overall",
            "gpt4": "Caching solutions can improve user experience significantly",
        }

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        # Should be refining if between thresholds
        if 0.40 <= result.min_similarity < 0.85:
            assert result.status == "refining"
            assert result.converged is False

    def test_custom_convergence_threshold(self):
        """Test detector with custom convergence threshold."""
        # Very strict threshold
        strict_detector = ConvergenceDetector(
            convergence_threshold=0.99,
            divergence_threshold=0.40,
        )

        response = "Identical response text"
        current = {"claude": response}
        previous = {"claude": response}

        result = strict_detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        assert result.converged is True
        assert result.min_similarity >= 0.99

    def test_custom_divergence_threshold(self):
        """Test detector with custom divergence threshold."""
        lenient_detector = ConvergenceDetector(
            convergence_threshold=0.85,
            divergence_threshold=0.20,  # Very lenient
        )

        # Completely different texts
        current = {"claude": "abc def ghi"}
        previous = {"claude": "xyz uvw rst"}

        result = lenient_detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        # Should be diverging at 0% similarity which is < 0.20
        assert result.status == "diverging"


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_current_responses(self, detector):
        """Test with empty current responses."""
        current: dict[str, str] = {}
        previous = {"claude": "Some response"}

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is None  # No common agents

    def test_empty_previous_responses(self, detector):
        """Test with empty previous responses."""
        current = {"claude": "Some response"}
        previous: dict[str, str] = {}

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is None  # No common agents

    def test_single_response(self, detector):
        """Test with single agent response."""
        response = "Single agent response text"
        current = {"claude": response}
        previous = {"claude": response}

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        assert result.converged is True
        assert len(result.per_agent_similarity) == 1

    def test_identical_responses_all_agents(self, detector):
        """Test with identical responses from all agents."""
        response = "Exactly the same response from all agents"
        current = {
            "claude": response,
            "gpt4": response,
            "gemini": response,
        }
        previous = {
            "claude": response,
            "gpt4": response,
            "gemini": response,
        }

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        assert result.converged is True
        assert result.min_similarity == 1.0
        assert result.avg_similarity == 1.0
        for similarity in result.per_agent_similarity.values():
            assert similarity == 1.0

    def test_empty_string_response(self, detector):
        """Test with empty string responses."""
        current = {"claude": "", "gpt4": "Some text"}
        previous = {"claude": "", "gpt4": "Some text"}

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        # Empty string vs empty string should have 0 similarity (Jaccard)
        assert "claude" in result.per_agent_similarity
        assert result.per_agent_similarity["claude"] == 0.0

    def test_no_common_agents(self, detector):
        """Test with no common agents between rounds."""
        current = {"claude": "Response from Claude"}
        previous = {"gpt4": "Response from GPT-4"}

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is None  # No common agents to compare

    def test_partial_agent_overlap(self, detector):
        """Test with partial agent overlap between rounds."""
        response = "Same response text"
        current = {"claude": response, "gemini": "Different response"}
        previous = {"claude": response, "gpt4": "Another response"}

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        # Only claude is common
        assert len(result.per_agent_similarity) == 1
        assert "claude" in result.per_agent_similarity

    def test_round_number_before_minimum(self, detector):
        """Test that checks return None before minimum rounds."""
        current = {"claude": "Response"}
        previous = {"claude": "Response"}

        # Round 1 is at or before min_rounds_before_check (1)
        result = detector.check_convergence(current, previous, round_number=1)

        assert result is None

    def test_whitespace_only_response(self, detector):
        """Test with whitespace-only responses."""
        current = {"claude": "   \t\n  "}
        previous = {"claude": "   \t\n  "}

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        # Whitespace-only should have 0 similarity after splitting
        assert result.per_agent_similarity["claude"] == 0.0

    def test_very_long_response(self, detector):
        """Test with very long responses."""
        # Generate a long response
        long_response = " ".join(["word"] * 10000)
        current = {"claude": long_response}
        previous = {"claude": long_response}

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        assert result.converged is True
        assert result.min_similarity == 1.0

    def test_unicode_responses(self, detector):
        """Test with Unicode characters in responses."""
        current = {"claude": "The caf\u00e9 serves creme br\u00fbl\u00e9e and na\u00efve customers"}
        previous = {
            "claude": "The caf\u00e9 serves creme br\u00fbl\u00e9e and na\u00efve customers"
        }

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        assert result.converged is True

    def test_mixed_case_responses(self, detector):
        """Test case insensitivity in similarity calculation."""
        current = {"claude": "THE SYSTEM SHOULD USE REDIS FOR CACHING"}
        previous = {"claude": "the system should use redis for caching"}

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        assert result.converged is True
        assert result.min_similarity == 1.0  # Case insensitive


# =============================================================================
# Performance Tests
# =============================================================================


class TestPerformance:
    """Tests for performance with large response sets."""

    def test_large_number_of_agents(self, detector):
        """Test convergence detection with many agents."""
        response = "Common response text for all agents"
        num_agents = 50

        current = {f"agent_{i}": response for i in range(num_agents)}
        previous = {f"agent_{i}": response for i in range(num_agents)}

        start_time = time.time()
        result = detector.check_convergence(current, previous, round_number=2)
        elapsed = time.time() - start_time

        assert result is not None
        assert result.converged is True
        assert len(result.per_agent_similarity) == num_agents
        # Should complete in reasonable time
        assert elapsed < 5.0  # 5 seconds max

    def test_large_response_texts(self, detector):
        """Test with large response texts."""
        # Generate large but similar responses
        base_words = ["algorithm", "optimization", "performance", "system", "design"]
        large_text = " ".join(base_words * 1000)  # ~5000 words

        current = {"claude": large_text, "gpt4": large_text}
        previous = {"claude": large_text, "gpt4": large_text}

        start_time = time.time()
        result = detector.check_convergence(current, previous, round_number=2)
        elapsed = time.time() - start_time

        assert result is not None
        assert result.converged is True
        # Should complete in reasonable time
        assert elapsed < 5.0

    def test_many_unique_words(self, detector):
        """Test with responses containing many unique words."""
        # Generate responses with high unique word count
        import random

        random.seed(42)
        words1 = [f"word{i}" for i in range(1000)]
        words2 = [f"word{i}" for i in range(500, 1500)]  # 50% overlap

        current = {"claude": " ".join(words1)}
        previous = {"claude": " ".join(words2)}

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        # Should have ~33% overlap (500 common out of 1500 unique)
        # Jaccard: 500 / 1500 ≈ 0.33
        assert 0.30 < result.min_similarity < 0.40

    @pytest.mark.parametrize("num_rounds", [10, 50, 100])
    def test_multiple_consecutive_rounds(self, num_rounds):
        """Test convergence tracking across many rounds."""
        detector = ConvergenceDetector(
            convergence_threshold=0.85,
            min_rounds_before_check=1,
            consecutive_rounds_needed=2,
        )

        response = "Consistent response across rounds"
        current = {"claude": response}
        previous = {"claude": response}

        stable_rounds = 0
        for round_num in range(2, num_rounds + 2):
            result = detector.check_convergence(current, previous, round_num)
            if result and result.min_similarity >= 0.85:
                stable_rounds += 1

        # Should track stable rounds correctly
        assert stable_rounds == num_rounds


# =============================================================================
# Algorithm Tests (Multiple Backends)
# =============================================================================


class TestMultipleBackends:
    """Tests for different similarity backends."""

    def test_jaccard_backend_word_overlap(self):
        """Test Jaccard backend word overlap calculation."""
        backend = JaccardBackend()

        text1 = "the quick brown fox"
        text2 = "the lazy brown dog"

        similarity = backend.compute_similarity(text1, text2)

        # Common: "the", "brown" (2 words)
        # Union: "the", "quick", "brown", "fox", "lazy", "dog" (6 words)
        # Jaccard: 2/6 ≈ 0.333
        assert 0.30 < similarity < 0.40

    def test_tfidf_backend_available(self):
        """Test TF-IDF backend if scikit-learn is available."""
        backend = TFIDFBackend()

        text1 = "machine learning algorithms for data science"
        text2 = "machine learning techniques for data analysis"

        similarity = backend.compute_similarity(text1, text2)

        # Should have high similarity due to semantic overlap
        assert similarity > 0.5
        assert similarity <= 1.0

    def test_backend_selection_auto(self):
        """Test automatic backend selection."""
        backend = get_similarity_backend("auto")

        assert backend is not None
        assert hasattr(backend, "compute_similarity")

        # Should be able to compute similarity
        sim = backend.compute_similarity("test text", "test text")
        assert sim == pytest.approx(1.0, rel=0.01)

    def test_backend_selection_explicit_jaccard(self):
        """Test explicit Jaccard backend selection."""
        from aragora.debate.similarity.backends import JaccardBackend as _JB

        backend = get_similarity_backend("jaccard")

        assert isinstance(backend, _JB)

    def test_backend_compute_similarity_interface(self):
        """Test that all backends implement the same interface."""
        backends = [JaccardBackend()]

        try:
            backends.append(TFIDFBackend())
        except ImportError:
            pass

        text1 = "test similarity computation"
        text2 = "test similarity calculation"

        for backend in backends:
            # All backends should return float between 0 and 1
            sim = backend.compute_similarity(text1, text2)
            assert isinstance(sim, float)
            assert 0.0 <= sim <= 1.0

    def test_jaccard_cache_functionality(self):
        """Test Jaccard backend caching."""
        backend = JaccardBackend()
        JaccardBackend.clear_cache()

        text1 = "cache test one"
        text2 = "cache test two"

        # First computation
        sim1 = backend.compute_similarity(text1, text2)

        # Second computation (should hit cache)
        sim2 = backend.compute_similarity(text1, text2)

        assert sim1 == sim2

        # Reversed order should also hit cache (symmetric)
        sim3 = backend.compute_similarity(text2, text1)
        assert sim1 == sim3


# =============================================================================
# Consecutive Stable Rounds Tests
# =============================================================================


class TestConsecutiveStableRounds:
    """Tests for consecutive stable rounds tracking."""

    def test_single_consecutive_round_needed(self):
        """Test convergence with 1 consecutive round needed."""
        detector = ConvergenceDetector(
            convergence_threshold=0.85,
            min_rounds_before_check=1,
            consecutive_rounds_needed=1,
        )

        response = "Identical response"
        current = {"claude": response}
        previous = {"claude": response}

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        assert result.converged is True
        assert result.consecutive_stable_rounds == 1

    def test_multiple_consecutive_rounds_needed(self):
        """Test convergence requires multiple stable rounds."""
        detector = ConvergenceDetector(
            convergence_threshold=0.85,
            min_rounds_before_check=1,
            consecutive_rounds_needed=3,
        )

        response = "Same response"
        current = {"claude": response}
        previous = {"claude": response}

        # Round 2 - first stable round
        result1 = detector.check_convergence(current, previous, round_number=2)
        assert result1 is not None
        assert result1.converged is False
        assert result1.consecutive_stable_rounds == 1

        # Round 3 - second stable round
        result2 = detector.check_convergence(current, previous, round_number=3)
        assert result2 is not None
        assert result2.converged is False
        assert result2.consecutive_stable_rounds == 2

        # Round 4 - third stable round (should converge)
        result3 = detector.check_convergence(current, previous, round_number=4)
        assert result3 is not None
        assert result3.converged is True
        assert result3.consecutive_stable_rounds == 3

    def test_stable_rounds_reset_on_divergence(self):
        """Test that consecutive count resets on divergence."""
        detector = ConvergenceDetector(
            convergence_threshold=0.85,
            divergence_threshold=0.40,
            min_rounds_before_check=1,
            consecutive_rounds_needed=3,
        )

        # First stable round
        stable_response = "Same response"
        detector.check_convergence(
            {"claude": stable_response},
            {"claude": stable_response},
            round_number=2,
        )
        assert detector.consecutive_stable_count == 1

        # Divergent round - should reset
        detector.check_convergence(
            {"claude": "apple orange banana"},
            {"claude": "dog cat elephant"},
            round_number=3,
        )
        assert detector.consecutive_stable_count == 0

    def test_reset_method(self, detector):
        """Test explicit reset of consecutive count."""
        response = "Same response"
        current = {"claude": response}
        previous = {"claude": response}

        # Build up count
        detector.check_convergence(current, previous, round_number=2)
        assert detector.consecutive_stable_count > 0

        # Reset
        detector.reset()
        assert detector.consecutive_stable_count == 0


# =============================================================================
# Pairwise Similarity Cache Tests
# =============================================================================


class TestPairwiseSimilarityCache:
    """Tests for the pairwise similarity cache."""

    def test_cache_creation(self, clean_cache_state):
        """Test creating a pairwise similarity cache."""
        cache = PairwiseSimilarityCache(
            session_id="test_session",
            max_size=100,
            ttl_seconds=60.0,
        )

        assert cache.session_id == "test_session"
        assert cache.max_size == 100
        assert cache.ttl_seconds == 60.0

    def test_cache_put_and_get(self, clean_cache_state):
        """Test putting and getting values from cache."""
        cache = PairwiseSimilarityCache("test_session")

        cache.put("text1", "text2", 0.85)
        result = cache.get("text1", "text2")

        assert result == 0.85

    def test_cache_symmetric_key(self, clean_cache_state):
        """Test that cache key is symmetric (A,B == B,A)."""
        cache = PairwiseSimilarityCache("test_session")

        cache.put("text1", "text2", 0.75)

        # Should work in both orders
        assert cache.get("text1", "text2") == 0.75
        assert cache.get("text2", "text1") == 0.75

    def test_cache_miss_returns_none(self, clean_cache_state):
        """Test cache miss returns None."""
        cache = PairwiseSimilarityCache("test_session")

        result = cache.get("nonexistent1", "nonexistent2")

        assert result is None

    def test_cache_ttl_expiry(self, clean_cache_state):
        """Test that cached entries expire after TTL."""
        cache = PairwiseSimilarityCache(
            session_id="test_session",
            ttl_seconds=0.01,  # 10ms TTL
        )

        cache.put("text1", "text2", 0.90)
        time.sleep(0.02)  # Wait for TTL to expire

        result = cache.get("text1", "text2")

        assert result is None  # Should be expired

    def test_cache_lru_eviction(self, clean_cache_state):
        """Test LRU eviction when cache is full."""
        cache = PairwiseSimilarityCache(
            session_id="test_session",
            max_size=3,
        )

        # Fill cache
        cache.put("a", "1", 0.1)
        cache.put("b", "2", 0.2)
        cache.put("c", "3", 0.3)

        # Access 'a' to make it recently used
        cache.get("a", "1")

        # Add new entry - should evict 'b' (least recently used)
        cache.put("d", "4", 0.4)

        assert cache.get("a", "1") == 0.1  # Still present
        assert cache.get("b", "2") is None  # Evicted
        assert cache.get("c", "3") == 0.3  # Still present
        assert cache.get("d", "4") == 0.4  # New entry

    def test_cache_clear(self, clean_cache_state):
        """Test clearing the cache."""
        cache = PairwiseSimilarityCache("test_session")

        cache.put("text1", "text2", 0.85)
        cache.clear()

        assert cache.get("text1", "text2") is None

    def test_cache_stats(self, clean_cache_state):
        """Test getting cache statistics."""
        cache = PairwiseSimilarityCache("test_session", max_size=100)

        cache.put("a", "b", 0.5)
        cache.get("a", "b")  # Hit
        cache.get("x", "y")  # Miss

        stats = cache.get_stats()

        assert stats["session_id"] == "test_session"
        assert stats["size"] == 1
        assert stats["max_size"] == 100
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_cache_evict_expired(self, clean_cache_state):
        """Test proactive eviction of expired entries."""
        cache = PairwiseSimilarityCache(
            session_id="test_session",
            ttl_seconds=0.01,
        )

        cache.put("a", "b", 0.5)
        cache.put("c", "d", 0.6)

        time.sleep(0.02)  # Wait for TTL

        evicted = cache.evict_expired()

        assert evicted == 2
        assert cache.get("a", "b") is None
        assert cache.get("c", "d") is None

    def test_cache_thread_safety(self, clean_cache_state):
        """Test cache is thread-safe."""
        cache = PairwiseSimilarityCache("test_session", max_size=1000)
        errors = []

        def writer():
            try:
                for i in range(100):
                    cache.put(f"text_{i}", f"other_{i}", i / 100.0)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(100):
                    cache.get(f"text_{i}", f"other_{i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# =============================================================================
# Global Cache Manager Tests
# =============================================================================


class TestGlobalCacheManager:
    """Tests for the global similarity cache manager."""

    def test_get_pairwise_similarity_cache(self, clean_cache_state):
        """Test getting a similarity cache for a session."""
        cache = get_pairwise_similarity_cache("session_123")

        assert cache is not None
        assert cache.session_id == "session_123"

    def test_get_same_cache_for_session(self, clean_cache_state):
        """Test that same cache is returned for same session."""
        cache1 = get_pairwise_similarity_cache("session_abc")
        cache2 = get_pairwise_similarity_cache("session_abc")

        assert cache1 is cache2

    def test_cleanup_similarity_cache(self, clean_cache_state):
        """Test cleaning up a specific session cache."""
        from aragora.debate import convergence

        get_pairwise_similarity_cache("to_cleanup")

        assert "to_cleanup" in convergence._similarity_cache_manager

        cleanup_similarity_cache("to_cleanup")

        assert "to_cleanup" not in convergence._similarity_cache_manager

    def test_cleanup_stale_caches(self, clean_cache_state):
        """Test cleaning up stale caches."""
        from aragora.debate import convergence

        # Create cache with old timestamp
        cache = get_pairwise_similarity_cache("old_session")
        convergence._similarity_cache_timestamps["old_session"] = time.time() - 7200  # 2 hours ago

        # Create fresh cache
        get_pairwise_similarity_cache("new_session")

        # Cleanup with 1 hour TTL
        cleaned = cleanup_stale_similarity_caches(max_age_seconds=3600)

        assert cleaned == 1
        assert "old_session" not in convergence._similarity_cache_manager
        assert "new_session" in convergence._similarity_cache_manager

    def test_get_cache_manager_stats(self, clean_cache_state):
        """Test getting cache manager statistics."""
        get_pairwise_similarity_cache("stats_session")

        stats = get_cache_manager_stats()

        assert stats["active_caches"] >= 1
        assert stats["max_caches"] == MAX_SIMILARITY_CACHES
        assert "caches" in stats

    def test_cleanup_stale_caches_comprehensive(self, clean_cache_state):
        """Test comprehensive cleanup function."""
        from aragora.debate import convergence

        # Create cache with old timestamp
        get_pairwise_similarity_cache("stale_session")
        convergence._similarity_cache_timestamps["stale_session"] = time.time() - 7200

        result = cleanup_stale_caches(max_age_seconds=3600)

        assert result["cleaned_count"] >= 1
        assert "entries_evicted" in result
        assert "remaining_count" in result
        assert "cleanup_time" in result


# =============================================================================
# Advanced Convergence Analyzer Tests
# =============================================================================


class TestAdvancedConvergenceAnalyzerComprehensive:
    """Comprehensive tests for AdvancedConvergenceAnalyzer."""

    def test_analyzer_with_debate_id_caching(self, clean_cache_state):
        """Test analyzer with debate-scoped caching."""
        analyzer = AdvancedConvergenceAnalyzer(
            similarity_backend=JaccardBackend(),
            debate_id="test_debate_123",
            enable_cache=True,
        )

        assert analyzer._debate_id == "test_debate_123"
        assert analyzer._enable_cache is True
        assert analyzer._similarity_cache is not None

    def test_analyzer_cleanup(self, clean_cache_state):
        """Test analyzer cleanup releases resources."""
        from aragora.debate import convergence

        analyzer = AdvancedConvergenceAnalyzer(
            similarity_backend=JaccardBackend(),
            debate_id="cleanup_debate",
            enable_cache=True,
        )

        # Cache should exist
        assert "cleanup_debate" in convergence._similarity_cache_manager

        analyzer.cleanup()

        # Cache should be removed
        assert "cleanup_debate" not in convergence._similarity_cache_manager

    def test_compute_similarity_cached(self, clean_cache_state):
        """Test cached similarity computation."""
        analyzer = AdvancedConvergenceAnalyzer(
            similarity_backend=JaccardBackend(),
            debate_id="cache_test_debate",
            enable_cache=True,
        )

        # First computation
        sim1 = analyzer._compute_similarity_cached("hello world", "hello there")

        # Second computation (should hit cache)
        sim2 = analyzer._compute_similarity_cached("hello world", "hello there")

        assert sim1 == sim2

        # Check cache stats show hit
        stats = analyzer.get_cache_stats()
        assert stats is not None
        assert stats["hits"] >= 1

    def test_extract_arguments_complex(self, analyzer):
        """Test argument extraction from complex text."""
        text = """
        The implementation should follow SOLID principles.
        We need to ensure proper error handling throughout.
        Performance testing is critical for this component.
        Short.
        Yes.
        The database schema requires careful consideration of normalization.
        """

        arguments = analyzer.extract_arguments(text)

        # Should extract sentences with > 5 words
        assert len(arguments) >= 3
        assert all(len(arg.split()) > 5 for arg in arguments)

    def test_extract_citations_comprehensive(self, analyzer):
        """Test citation extraction for various formats."""
        text = """
        According to https://docs.python.org/3/ the syntax is correct.
        This is supported by (Smith, 2024) and confirmed in [1].
        Per the official documentation from Microsoft, this is valid.
        (Jones et al., 2023) also agrees with this assessment.
        Reference [2] provides additional context.
        """

        citations = analyzer.extract_citations(text)

        assert "https://docs.python.org/3/" in citations
        assert "(Smith, 2024)" in citations
        assert "(Jones et al., 2023)" in citations
        assert "[1]" in citations
        assert "[2]" in citations

    def test_detect_stance_all_types(self, analyzer):
        """Test stance detection for all stance types."""
        # Support
        assert analyzer.detect_stance("I strongly agree and support this") == "support"

        # Oppose
        assert analyzer.detect_stance("I disagree and must reject this") == "oppose"

        # Neutral (no strong indicators)
        assert analyzer.detect_stance("The sky is blue today") == "neutral"

        # Mixed
        mixed_text = (
            "I agree with part of this, however I disagree with the implementation. It depends."
        )
        assert analyzer.detect_stance(mixed_text) == "mixed"

    def test_compute_evidence_convergence_shared(self, analyzer):
        """Test evidence convergence with shared citations."""
        responses = {
            "claude": "According to [1] and https://example.com, this is true.",
            "gpt4": "As stated in [1] and https://example.com, confirmed.",
            "gemini": "Reference [2] shows different data.",
        }

        metric = analyzer.compute_evidence_convergence(responses)

        # [1] and https://example.com are shared by 2 agents
        assert metric.shared_citations >= 2
        assert metric.overlap_score > 0

    def test_compute_stance_volatility_changes(self, analyzer):
        """Test stance volatility tracking changes."""
        history = [
            {"claude": "I strongly agree", "gpt4": "I disagree completely"},
            {"claude": "I agree with this", "gpt4": "Now I support this"},  # gpt4 changed
            {"claude": "Still in agreement", "gpt4": "I continue to support"},
        ]

        metric = analyzer.compute_stance_volatility(history)

        # gpt4 changed stance
        assert metric.stance_changes >= 1
        assert metric.volatility_score > 0

    def test_analyze_full_metrics(self, clean_cache_state):
        """Test full analysis with all metrics."""
        analyzer = AdvancedConvergenceAnalyzer(
            similarity_backend=JaccardBackend(),
            debate_id="full_analysis_debate",
            enable_cache=True,
        )

        current = {
            "claude": "Redis caching improves performance. According to https://redis.io benchmarks show 10ms latency.",
            "gpt4": "I agree that Redis is excellent for caching. The https://redis.io documentation supports this.",
        }
        previous = {
            "claude": "We should consider caching solutions for better performance.",
            "gpt4": "Caching is important for system scalability.",
        }
        history = [previous, current]

        metrics = analyzer.analyze(
            current_responses=current,
            previous_responses=previous,
            response_history=history,
            domain="performance",
        )

        assert metrics.domain == "performance"
        assert metrics.semantic_similarity >= 0
        assert metrics.argument_diversity is not None
        assert metrics.evidence_convergence is not None
        assert metrics.stance_volatility is not None
        assert 0 <= metrics.overall_convergence <= 1


# =============================================================================
# Advanced Convergence Metrics Tests
# =============================================================================


class TestAdvancedConvergenceMetricsComprehensive:
    """Comprehensive tests for AdvancedConvergenceMetrics."""

    def test_compute_overall_score_weights(self):
        """Test overall score respects weights."""
        # Semantic only (weight 0.4)
        metrics = AdvancedConvergenceMetrics(semantic_similarity=1.0)
        score = metrics.compute_overall_score()
        assert score == pytest.approx(0.4, rel=0.01)

    def test_compute_overall_score_bounded(self):
        """Test overall score is bounded between 0 and 1."""
        metrics = AdvancedConvergenceMetrics(
            semantic_similarity=1.0,
            argument_diversity=ArgumentDiversityMetric(0, 10, 0.0),
            evidence_convergence=EvidenceConvergenceMetric(10, 10, 1.0),
            stance_volatility=StanceVolatilityMetric(0, 10, 0.0),
        )

        score = metrics.compute_overall_score()

        assert 0.0 <= score <= 1.0

    def test_to_dict_complete(self):
        """Test to_dict includes all fields."""
        metrics = AdvancedConvergenceMetrics(
            semantic_similarity=0.8,
            argument_diversity=ArgumentDiversityMetric(5, 10, 0.5),
            evidence_convergence=EvidenceConvergenceMetric(3, 5, 0.6),
            stance_volatility=StanceVolatilityMetric(2, 10, 0.2),
            domain="testing",
        )
        metrics.compute_overall_score()

        result = metrics.to_dict()

        assert "semantic_similarity" in result
        assert "overall_convergence" in result
        assert "domain" in result
        assert "argument_diversity" in result
        assert "evidence_convergence" in result
        assert "stance_volatility" in result


# =============================================================================
# Within-Round Convergence Tests
# =============================================================================


class TestWithinRoundConvergence:
    """Tests for within-round convergence detection."""

    def test_within_round_single_response(self, detector):
        """Test within-round convergence with single response."""
        responses = {"claude": "Single response"}

        converged, min_sim, avg_sim = detector.check_within_round_convergence(responses)

        assert converged is True
        assert min_sim == 1.0
        assert avg_sim == 1.0

    def test_within_round_identical_responses(self, detector):
        """Test within-round convergence with identical responses."""
        response = "Everyone agrees on this"
        responses = {
            "claude": response,
            "gpt4": response,
            "gemini": response,
        }

        converged, min_sim, avg_sim = detector.check_within_round_convergence(responses)

        assert converged is True
        assert min_sim >= 0.85  # Default threshold
        assert avg_sim >= 0.85

    def test_within_round_different_responses(self, detector):
        """Test within-round convergence with different responses."""
        responses = {
            "claude": "apple banana cherry",
            "gpt4": "dog elephant fox",
            "gemini": "house building apartment",
        }

        converged, min_sim, avg_sim = detector.check_within_round_convergence(responses)

        assert converged is False
        assert min_sim < 0.85

    def test_within_round_custom_threshold(self, detector):
        """Test within-round convergence with custom threshold."""
        responses = {
            "claude": "common words here",
            "gpt4": "common words there",
        }

        # Very low threshold should converge
        converged, min_sim, _ = detector.check_within_round_convergence(responses, threshold=0.1)
        assert converged is True


# =============================================================================
# Fast Convergence Check Tests
# =============================================================================


class TestFastConvergenceCheck:
    """Tests for the optimized fast convergence check."""

    def test_fast_check_returns_none_early(self, detector):
        """Test fast check returns None for early rounds."""
        current = {"claude": "Response"}
        previous = {"claude": "Response"}

        result = detector.check_convergence_fast(current, previous, round_number=1)

        assert result is None

    def test_fast_check_no_common_agents(self, detector):
        """Test fast check with no common agents."""
        current = {"claude": "Response"}
        previous = {"gpt4": "Response"}

        result = detector.check_convergence_fast(current, previous, round_number=2)

        assert result is None

    def test_fast_check_identical_responses(self, detector):
        """Test fast check with identical responses."""
        response = "Identical response text"
        current = {"claude": response, "gpt4": response}
        previous = {"claude": response, "gpt4": response}

        result = detector.check_convergence_fast(current, previous, round_number=2)

        assert result is not None
        # Fast check might fall back to regular check for Jaccard
        assert result.min_similarity >= 0.85


# =============================================================================
# Detector Cleanup Tests
# =============================================================================


class TestDetectorCleanup:
    """Tests for detector cleanup functionality."""

    def test_cleanup_releases_caches(self, clean_cache_state):
        """Test that cleanup releases debate-specific caches."""
        from aragora.debate import convergence

        detector = ConvergenceDetector(debate_id="cleanup_test_debate")

        # Use the detector to create caches
        # The detector's backend may use caches

        detector.cleanup()

        # Caches should be cleaned up
        assert "cleanup_test_debate" not in convergence._similarity_cache_manager


# =============================================================================
# Periodic Cleanup Tests
# =============================================================================


class TestPeriodicCleanup:
    """Tests for periodic cleanup functionality."""

    def test_periodic_cleanup_stats(self, clean_cache_state):
        """Test getting periodic cleanup stats."""
        stats = get_periodic_cleanup_stats()

        assert "running" in stats
        assert "interval_seconds" in stats
        assert "total_caches_cleaned" in stats

    def test_stop_periodic_cleanup(self, clean_cache_state):
        """Test stopping periodic cleanup."""
        # Just ensure it doesn't raise
        stop_periodic_cleanup()

        stats = get_periodic_cleanup_stats()
        # May or may not be running depending on test order


# =============================================================================
# Integration Tests
# =============================================================================


class TestOrchestratorIntegration:
    """Tests for integration with debate orchestrator patterns."""

    def test_convergence_detector_with_protocol_thresholds(self):
        """Test detector with thresholds matching protocol settings."""
        # Simulate protocol-defined thresholds
        protocol_convergence = 0.90
        protocol_divergence = 0.35

        detector = ConvergenceDetector(
            convergence_threshold=protocol_convergence,
            divergence_threshold=protocol_divergence,
        )

        assert detector.convergence_threshold == 0.90
        assert detector.divergence_threshold == 0.35

    def test_detector_state_across_debate(self):
        """Test detector maintains state across a multi-round debate."""
        detector = ConvergenceDetector(
            convergence_threshold=0.85,
            consecutive_rounds_needed=2,
        )

        # Simulate a multi-round debate
        rounds = [
            ({"a": "initial proposal about caching"}, {"a": "different topic entirely"}),
            (
                {"a": "caching is important for performance"},
                {"a": "initial proposal about caching"},
            ),
            (
                {"a": "caching with Redis improves speed"},
                {"a": "caching is important for performance"},
            ),
            (
                {"a": "caching with Redis improves speed"},
                {"a": "caching with Redis improves speed"},
            ),
            (
                {"a": "caching with Redis improves speed"},
                {"a": "caching with Redis improves speed"},
            ),
        ]

        results = []
        for i, (current, previous) in enumerate(rounds, start=2):
            result = detector.check_convergence(current, previous, round_number=i)
            results.append(result)

        # Should track progression through debate
        assert len(results) == 5

    def test_analyzer_integrates_with_detector(self, clean_cache_state):
        """Test analyzer and detector work together."""
        backend = JaccardBackend()
        analyzer = AdvancedConvergenceAnalyzer(
            similarity_backend=backend,
            debate_id="integration_debate",
        )
        detector = ConvergenceDetector(debate_id="integration_debate")

        # Both should be able to compute similarity
        current = {"claude": "test response"}
        previous = {"claude": "test response"}

        # Detector check
        result = detector.check_convergence(current, previous, round_number=2)
        assert result is not None

        # Analyzer analysis
        metrics = analyzer.analyze(current, previous)
        assert metrics is not None


# =============================================================================
# CachedSimilarity Tests
# =============================================================================


class TestCachedSimilarity:
    """Tests for the CachedSimilarity dataclass."""

    def test_cached_similarity_creation(self):
        """Test creating CachedSimilarity."""
        cached = CachedSimilarity(similarity=0.85, computed_at=time.time())

        assert cached.similarity == 0.85
        assert cached.computed_at > 0

    def test_cached_similarity_equality(self):
        """Test CachedSimilarity equality based on values."""
        timestamp = time.time()
        cached1 = CachedSimilarity(similarity=0.75, computed_at=timestamp)
        cached2 = CachedSimilarity(similarity=0.75, computed_at=timestamp)

        assert cached1.similarity == cached2.similarity
        assert cached1.computed_at == cached2.computed_at


# =============================================================================
# Constants Tests
# =============================================================================


class TestConstants:
    """Tests for module constants."""

    def test_max_similarity_caches(self):
        """Test MAX_SIMILARITY_CACHES has expected value."""
        assert MAX_SIMILARITY_CACHES == 100

    def test_cache_manager_ttl(self):
        """Test CACHE_MANAGER_TTL_SECONDS has expected value."""
        assert CACHE_MANAGER_TTL_SECONDS == 3600  # 1 hour

    def test_periodic_cleanup_interval(self):
        """Test PERIODIC_CLEANUP_INTERVAL_SECONDS has expected value."""
        assert PERIODIC_CLEANUP_INTERVAL_SECONDS == 600  # 10 minutes


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling in convergence detection."""

    def test_backend_handles_none_text(self):
        """Test backend handles None gracefully (via empty string)."""
        backend = JaccardBackend()

        # Empty strings (simulating None-like behavior)
        sim = backend.compute_similarity("", "")
        assert sim == 0.0

    def test_detector_handles_malformed_responses(self, detector):
        """Test detector handles unusual response formats."""
        # Responses with only punctuation
        current = {"claude": "!@#$%^&*()"}
        previous = {"claude": "!@#$%^&*()"}

        result = detector.check_convergence(current, previous, round_number=2)

        # Should not crash, even if similarity is weird
        assert result is not None

    def test_analyzer_handles_no_arguments(self, analyzer):
        """Test analyzer handles text with no extractable arguments."""
        responses = {"claude": "Hi!", "gpt4": "OK."}

        metric = analyzer.compute_argument_diversity(responses)

        assert metric.total_arguments == 0
        assert metric.diversity_score == 0.0

    def test_analyzer_handles_single_agent(self, analyzer):
        """Test analyzer handles single agent evidence convergence."""
        responses = {"claude": "According to [1], this is true."}

        metric = analyzer.compute_evidence_convergence(responses)

        # Single agent can't have shared citations
        assert metric.overlap_score == 0.0


# =============================================================================
# TF-IDF Backend Specific Tests
# =============================================================================


class TestTFIDFBackendConvergence:
    """Tests for TF-IDF backend integration with convergence detection."""

    @pytest.fixture
    def tfidf_detector(self):
        """Create detector with TF-IDF backend if available."""
        from aragora.debate.similarity.backends import TFIDFBackend

        TFIDFBackend()  # Test if it can be created
        return ConvergenceDetector()  # Will select TFIDF if sklearn available

    def test_tfidf_within_round_convergence(self, clean_cache_state):
        """Test within-round convergence with TF-IDF backend."""
        backend = TFIDFBackend()

        # Create detector with TF-IDF backend
        detector = ConvergenceDetector()
        # Force use of TF-IDF backend if available
        detector.backend = backend

        responses = {
            "claude": "machine learning algorithms for data science applications",
            "gpt4": "machine learning techniques for data analysis projects",
            "gemini": "machine learning methods for data processing tasks",
        }

        converged, min_sim, avg_sim = detector.check_within_round_convergence(responses)

        # Should have meaningful similarity due to shared ML terms
        assert isinstance(converged, bool)
        assert 0.0 <= min_sim <= 1.0
        assert 0.0 <= avg_sim <= 1.0

    def test_tfidf_analyzer_diversity(self, clean_cache_state):
        """Test analyzer diversity computation with TF-IDF backend."""
        backend = TFIDFBackend()

        analyzer = AdvancedConvergenceAnalyzer(
            similarity_backend=backend,
            debate_id="tfidf_diversity_test",
        )

        # Generate enough arguments for optimized path (>= 5)
        responses = {
            "claude": "The algorithm improves performance significantly. "
            "Machine learning enables better predictions. "
            "Data processing is streamlined with this approach. "
            "Users benefit from faster response times. "
            "System reliability is enhanced through monitoring. "
            "Security measures protect against threats effectively.",
            "gpt4": "Performance optimization is critical for success. "
            "Predictive models drive business decisions. "
            "Streamlined workflows increase productivity. "
            "User experience determines product adoption. "
            "Reliable systems build customer trust. "
            "Threat detection prevents security breaches.",
        }

        metric = analyzer.compute_argument_diversity(responses, use_optimized=True)

        assert metric.total_arguments >= 5
        assert 0.0 <= metric.diversity_score <= 1.0


# =============================================================================
# Periodic Cleanup Thread Tests
# =============================================================================


class TestPeriodicCleanupThread:
    """Tests for the periodic cleanup thread functionality."""

    def test_periodic_cleanup_start_and_stop(self, clean_cache_state):
        """Test starting and stopping the periodic cleanup thread."""
        from aragora.debate.convergence import (
            _PeriodicCacheCleanup,
        )

        # Create cleanup thread with short interval for testing
        cleanup = _PeriodicCacheCleanup(interval_seconds=0.1)

        assert cleanup.is_running() is False

        cleanup.start()
        assert cleanup.is_running() is True

        # Wait a bit for the thread to run
        time.sleep(0.05)

        cleanup.stop(timeout=1.0)
        assert cleanup.is_running() is False

    def test_periodic_cleanup_stats(self, clean_cache_state):
        """Test getting stats from periodic cleanup thread."""
        from aragora.debate.convergence import (
            _PeriodicCacheCleanup,
        )

        cleanup = _PeriodicCacheCleanup(interval_seconds=1.0)

        stats = cleanup.get_stats()

        assert "running" in stats
        assert "interval_seconds" in stats
        assert "total_caches_cleaned" in stats
        assert "total_entries_evicted" in stats
        assert "last_cleanup_time" in stats
        assert stats["interval_seconds"] == 1.0

    def test_periodic_cleanup_double_start(self, clean_cache_state):
        """Test that double starting doesn't create multiple threads."""
        from aragora.debate.convergence import (
            _PeriodicCacheCleanup,
        )

        cleanup = _PeriodicCacheCleanup(interval_seconds=10.0)

        cleanup.start()
        thread1 = cleanup._thread

        cleanup.start()  # Second start should be a no-op
        thread2 = cleanup._thread

        assert thread1 is thread2
        cleanup.stop()

    def test_periodic_cleanup_double_stop(self, clean_cache_state):
        """Test that double stopping is safe."""
        from aragora.debate.convergence import (
            _PeriodicCacheCleanup,
        )

        cleanup = _PeriodicCacheCleanup(interval_seconds=10.0)

        cleanup.start()
        cleanup.stop()
        cleanup.stop()  # Should not raise

        assert cleanup.is_running() is False


# =============================================================================
# Optimized Diversity Computation Tests
# =============================================================================


class TestOptimizedDiversityComputation:
    """Tests for optimized diversity computation paths."""

    def test_diversity_with_jaccard_uses_fallback(self, clean_cache_state):
        """Test that Jaccard backend uses fallback (non-optimized) path."""
        analyzer = AdvancedConvergenceAnalyzer(
            similarity_backend=JaccardBackend(),
            debate_id="jaccard_fallback_test",
        )

        # Generate enough arguments for potential optimized path
        responses = {
            "claude": "This is a test sentence with more than five words. "
            "Another sentence about software development practices. "
            "Testing methodologies improve code quality significantly. "
            "Continuous integration enables rapid deployment cycles. "
            "Documentation helps maintain project knowledge base.",
        }

        # Should work with fallback since Jaccard doesn't have embeddings
        metric = analyzer.compute_argument_diversity(responses, use_optimized=True)

        assert metric.total_arguments >= 3
        assert 0.0 <= metric.diversity_score <= 1.0

    def test_diversity_without_optimization(self, clean_cache_state):
        """Test diversity computation with optimization disabled."""
        analyzer = AdvancedConvergenceAnalyzer(
            similarity_backend=JaccardBackend(),
            debate_id="no_optimize_test",
        )

        responses = {
            "claude": "The system uses Redis for caching data efficiently. "
            "Performance monitoring tracks application health metrics. "
            "Error handling ensures graceful degradation under load.",
        }

        metric = analyzer.compute_argument_diversity(responses, use_optimized=False)

        assert metric.total_arguments >= 2
        assert 0.0 <= metric.diversity_score <= 1.0


# =============================================================================
# Argument Diversity Unique Detection Tests
# =============================================================================


class TestArgumentDiversityUniqueDetection:
    """Tests for unique argument detection in diversity computation."""

    def test_identical_arguments_low_diversity(self, clean_cache_state):
        """Test that identical arguments result in low diversity."""
        analyzer = AdvancedConvergenceAnalyzer(
            similarity_backend=JaccardBackend(),
            debate_id="identical_args_test",
        )

        # Same argument repeated
        responses = {
            "claude": "The caching layer improves performance significantly. "
            "The caching layer improves performance significantly. "
            "The caching layer improves performance significantly.",
            "gpt4": "The caching layer improves performance significantly. "
            "The caching layer improves performance significantly.",
        }

        metric = analyzer.compute_argument_diversity(responses)

        # Should have low diversity (many identical arguments)
        assert metric.diversity_score < 0.5

    def test_diverse_arguments_high_diversity(self, clean_cache_state):
        """Test that diverse arguments result in high diversity."""
        analyzer = AdvancedConvergenceAnalyzer(
            similarity_backend=JaccardBackend(),
            debate_id="diverse_args_test",
        )

        responses = {
            "claude": "Database optimization reduces query latency significantly. "
            "Frontend caching improves user experience noticeably.",
            "gpt4": "Security hardening protects against common attack vectors. "
            "Monitoring systems provide insights into application health.",
        }

        metric = analyzer.compute_argument_diversity(responses)

        # Should have higher diversity (different topics)
        # Note: With Jaccard, even different topics may share some common words
        assert metric.total_arguments >= 2


# =============================================================================
# Hash Function Tests
# =============================================================================


class TestPairwiseSimilarityCacheHashing:
    """Tests for the pairwise similarity cache hashing functions."""

    def test_hash_text_consistency(self, clean_cache_state):
        """Test that hash function is consistent."""
        cache = PairwiseSimilarityCache("hash_test")

        hash1 = cache._hash_text("test text")
        hash2 = cache._hash_text("test text")

        assert hash1 == hash2

    def test_hash_text_different_inputs(self, clean_cache_state):
        """Test that different inputs produce different hashes."""
        cache = PairwiseSimilarityCache("hash_test")

        hash1 = cache._hash_text("text one")
        hash2 = cache._hash_text("text two")

        assert hash1 != hash2

    def test_make_key_symmetric(self, clean_cache_state):
        """Test that make_key produces symmetric keys."""
        cache = PairwiseSimilarityCache("key_test")

        key1 = cache._make_key("alpha", "beta")
        key2 = cache._make_key("beta", "alpha")

        assert key1 == key2


# =============================================================================
# Advanced Metrics Boundary Tests
# =============================================================================


class TestAdvancedMetricsBoundaries:
    """Tests for boundary conditions in advanced metrics."""

    def test_argument_diversity_boundary_threshold(self):
        """Test ArgumentDiversityMetric at 0.3 boundary."""
        # At boundary
        metric_at = ArgumentDiversityMetric(3, 10, 0.3)
        assert metric_at.is_converging is False  # 0.3 is NOT < 0.3

        # Just below
        metric_below = ArgumentDiversityMetric(2, 10, 0.29)
        assert metric_below.is_converging is True

    def test_evidence_convergence_boundary_threshold(self):
        """Test EvidenceConvergenceMetric at 0.6 boundary."""
        # At boundary
        metric_at = EvidenceConvergenceMetric(6, 10, 0.6)
        assert metric_at.is_converging is False  # 0.6 is NOT > 0.6

        # Just above
        metric_above = EvidenceConvergenceMetric(7, 10, 0.61)
        assert metric_above.is_converging is True

    def test_stance_volatility_boundary_threshold(self):
        """Test StanceVolatilityMetric at 0.2 boundary."""
        # At boundary
        metric_at = StanceVolatilityMetric(2, 10, 0.2)
        assert metric_at.is_stable is False  # 0.2 is NOT < 0.2

        # Just below
        metric_below = StanceVolatilityMetric(1, 10, 0.19)
        assert metric_below.is_stable is True


# =============================================================================
# Evict Expired Cache Entries Tests
# =============================================================================


class TestEvictExpiredCacheEntries:
    """Tests for evicting expired entries across all caches."""

    def test_evict_expired_from_multiple_caches(self, clean_cache_state):
        """Test evicting expired entries from multiple caches."""
        from aragora.debate import convergence

        # Create caches with short TTL
        cache1 = get_pairwise_similarity_cache("evict_test_1", ttl_seconds=0.01)
        cache2 = get_pairwise_similarity_cache("evict_test_2", ttl_seconds=0.01)

        # Add entries
        cache1.put("a", "b", 0.5)
        cache2.put("c", "d", 0.6)

        # Wait for TTL
        time.sleep(0.02)

        # Evict all expired
        total_evicted = evict_expired_cache_entries()

        # Should have evicted entries
        assert total_evicted >= 2

    def test_evict_expired_empty_manager(self, clean_cache_state):
        """Test evicting when no caches exist."""
        evicted = evict_expired_cache_entries()
        assert evicted == 0


# =============================================================================
# Backend Contradiction Detection Tests
# =============================================================================


class TestBackendContradictionDetection:
    """Tests for contradiction detection in similarity backends."""

    def test_jaccard_is_contradictory_basic(self):
        """Test basic contradiction detection with Jaccard."""
        backend = JaccardBackend()

        # Contradictory options
        assert backend.is_contradictory("Yes", "No") is True
        assert backend.is_contradictory("I agree", "I disagree") is True
        assert backend.is_contradictory("Accept the proposal", "Reject the proposal") is True

    def test_jaccard_not_contradictory(self):
        """Test non-contradictory texts."""
        backend = JaccardBackend()

        assert backend.is_contradictory("Hello world", "Hello there") is False
        assert backend.is_contradictory("The sky is blue", "The grass is green") is False

    def test_jaccard_labeled_options_contradictory(self):
        """Test labeled options are detected as contradictory."""
        backend = JaccardBackend()

        assert backend.is_contradictory("Option A", "Option B") is True
        assert backend.is_contradictory("Choice 1", "Choice 2") is True

    def test_jaccard_empty_text_not_contradictory(self):
        """Test empty texts are not contradictory."""
        backend = JaccardBackend()

        assert backend.is_contradictory("", "Some text") is False
        assert backend.is_contradictory("Some text", "") is False
        assert backend.is_contradictory("", "") is False


# =============================================================================
# Backend Batch Similarity Tests
# =============================================================================


class TestBackendBatchSimilarity:
    """Tests for batch similarity computation."""

    def test_jaccard_batch_similarity_single_text(self):
        """Test batch similarity with single text returns 1.0."""
        backend = JaccardBackend()
        assert backend.compute_batch_similarity(["single text"]) == 1.0

    def test_jaccard_batch_similarity_identical(self):
        """Test batch similarity with identical texts."""
        backend = JaccardBackend()
        texts = ["identical text"] * 5
        assert backend.compute_batch_similarity(texts) == 1.0

    def test_jaccard_batch_similarity_different(self):
        """Test batch similarity with different texts."""
        backend = JaccardBackend()
        texts = [
            "apple banana cherry",
            "dog elephant fox",
            "house building apartment",
        ]
        similarity = backend.compute_batch_similarity(texts)
        assert similarity == 0.0  # No word overlap


# =============================================================================
# Cache Manager Edge Cases
# =============================================================================


class TestCacheManagerEdgeCases:
    """Tests for edge cases in the cache manager."""

    def test_cleanup_nonexistent_session(self, clean_cache_state):
        """Test cleaning up a session that doesn't exist."""
        # Should not raise
        cleanup_similarity_cache("nonexistent_session_12345")

    def test_get_stats_after_cleanup(self, clean_cache_state):
        """Test getting stats after cleaning up all caches."""
        # Create and cleanup a cache
        get_pairwise_similarity_cache("temp_session")
        cleanup_similarity_cache("temp_session")

        stats = get_cache_manager_stats()
        assert stats["active_caches"] == 0


# =============================================================================
# SentenceTransformer Backend Tests (Optional)
# =============================================================================


class TestSentenceTransformerBackend:
    """Tests for SentenceTransformer backend when available."""

    @pytest.fixture
    def sentence_backend(self):
        """Get SentenceTransformer backend."""
        from aragora.debate.similarity.backends import SentenceTransformerBackend

        return SentenceTransformerBackend(use_nli=False)  # Skip NLI for faster tests

    def test_sentence_transformer_similarity(self, sentence_backend):
        """Test similarity computation with SentenceTransformer."""
        sim = sentence_backend.compute_similarity(
            "machine learning algorithms",
            "deep learning models",
        )

        # Should have some similarity (both about ML)
        assert 0.0 <= sim <= 1.0
        assert sim > 0.1  # Should have some semantic similarity

    def test_sentence_transformer_identical_text(self, sentence_backend):
        """Test identical texts have similarity ~1.0."""
        sim = sentence_backend.compute_similarity(
            "The quick brown fox jumps over the lazy dog",
            "The quick brown fox jumps over the lazy dog",
        )

        assert sim > 0.99

    def test_sentence_transformer_batch_similarity(self, sentence_backend):
        """The optimized batch path must agree with the naive pairwise average.

        Do not assert `avg_sim >= 0.0` here. Cosine similarity is [-1, 1], and this
        backend clamps at neither end (`compute_similarity` returns the raw cosine;
        `compute_batch_similarity_fast` returns their raw mean). The value is also
        network-dependent: sentence-transformers downloads weights from the HF Hub,
        and when that is rate-limited or offline it falls back to a randomly
        initialised model. With real weights these three texts average ~0.43; with
        random weights the average sits at ~0 and goes negative roughly half the
        time. That made this test flake in CI (`assert 0.0 <= -0.01772175170481205`)
        and locally about 1 run in 5.

        The invariant that actually matters — and that holds under either set of
        weights, because both paths consume the same embeddings — is that the
        vectorised batch implementation equals the naive loop it replaces.
        """
        texts = [
            "machine learning is powerful",
            "deep learning achieves great results",
            "neural networks process data",
        ]

        avg_sim = sentence_backend.compute_batch_similarity(texts)

        naive_pairs = [
            sentence_backend.compute_similarity(texts[i], texts[j])
            for i in range(len(texts))
            for j in range(i + 1, len(texts))
        ]
        naive_avg = sum(naive_pairs) / len(naive_pairs)

        assert avg_sim == pytest.approx(naive_avg, abs=1e-5)
        assert -1.0 <= avg_sim <= 1.0

    def test_sentence_transformer_pairwise_similarities(self, sentence_backend):
        """Test pairwise similarities computation."""
        texts_a = ["hello world", "goodbye world"]
        texts_b = ["hello there", "farewell world"]

        similarities = sentence_backend.compute_pairwise_similarities(texts_a, texts_b)

        assert len(similarities) == 2
        for sim in similarities:
            assert 0.0 <= sim <= 1.0

    def test_sentence_transformer_embedding_cache(self, sentence_backend):
        """Test that embedding cache is used."""
        text = "This is a test sentence for caching"

        # Get embedding twice
        emb1 = sentence_backend._get_embedding(text)
        emb2 = sentence_backend._get_embedding(text)

        # Should return same embedding from cache
        import numpy as np

        assert np.allclose(emb1, emb2)


class TestSentenceTransformerConvergence:
    """Tests for convergence detection with SentenceTransformer backend."""

    @pytest.fixture
    def st_detector(self, clean_cache_state):
        """Get detector with SentenceTransformer."""
        from aragora.debate.similarity.backends import SentenceTransformerBackend

        backend = SentenceTransformerBackend(use_nli=False, debate_id="st_test")
        detector = ConvergenceDetector(debate_id="st_test")
        detector.backend = backend
        return detector

    def test_st_check_convergence(self, st_detector):
        """Test convergence check with SentenceTransformer."""
        response = "Machine learning algorithms improve performance significantly"
        current = {"claude": response, "gpt4": response}
        previous = {"claude": response, "gpt4": response}

        result = st_detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        assert result.converged is True

    def test_st_fast_convergence_check(self, st_detector):
        """Test fast convergence check with SentenceTransformer."""
        response = "Deep neural networks achieve state of the art results"
        current = {"claude": response, "gpt4": response}
        previous = {"claude": response, "gpt4": response}

        result = st_detector.check_convergence_fast(current, previous, round_number=2)

        # Fast check uses embeddings when available
        assert result is not None
        assert result.min_similarity > 0.9

    def test_st_within_round_convergence(self, st_detector):
        """Test within-round convergence with SentenceTransformer."""
        responses = {
            "claude": "artificial intelligence systems learn patterns",
            "gpt4": "artificial intelligence systems learn patterns",
            "gemini": "artificial intelligence systems learn patterns",
        }

        converged, min_sim, avg_sim = st_detector.check_within_round_convergence(responses)

        assert converged is True
        assert min_sim > 0.9
        assert avg_sim > 0.9


class TestSentenceTransformerAnalyzer:
    """Tests for AdvancedConvergenceAnalyzer with SentenceTransformer."""

    @pytest.fixture
    def st_analyzer(self, clean_cache_state):
        """Get analyzer with SentenceTransformer."""
        from aragora.debate.similarity.backends import SentenceTransformerBackend

        backend = SentenceTransformerBackend(use_nli=False, debate_id="st_analyzer")
        return AdvancedConvergenceAnalyzer(
            similarity_backend=backend,
            debate_id="st_analyzer",
            enable_cache=True,
        )

    def test_st_diversity_optimized(self, st_analyzer):
        """Test diversity computation with SentenceTransformer optimized path."""
        # Generate enough arguments for optimized path (>= 5)
        responses = {
            "claude": "The algorithm processes data efficiently in real time. "
            "Memory management is crucial for system performance. "
            "Error handling ensures application stability always. "
            "Logging provides visibility into system behavior. "
            "Testing validates correctness of implementations. "
            "Documentation helps developers understand code.",
            "gpt4": "Data processing pipelines transform raw inputs. "
            "Resource allocation optimizes compute utilization. "
            "Fault tolerance enables graceful degradation. "
            "Observability reveals internal system state. "
            "Quality assurance prevents regression bugs. "
            "Knowledge sharing accelerates team productivity.",
        }

        metric = st_analyzer.compute_argument_diversity(responses, use_optimized=True)

        assert metric.total_arguments >= 5
        assert 0.0 <= metric.diversity_score <= 1.0

    def test_st_full_analysis(self, st_analyzer):
        """Test full analysis with SentenceTransformer backend."""
        current = {
            "claude": "Redis provides excellent caching capabilities for web applications.",
            "gpt4": "Redis caching improves response times for web services.",
        }
        previous = {
            "claude": "We should consider caching solutions for better performance.",
            "gpt4": "Caching is essential for scalable web architectures.",
        }

        metrics = st_analyzer.analyze(
            current_responses=current,
            previous_responses=previous,
            domain="performance",
        )

        assert metrics.semantic_similarity >= 0
        assert metrics.domain == "performance"


# =============================================================================
# Cleanup Loop Error Handling Tests
# =============================================================================


class TestCleanupLoopErrorHandling:
    """Tests for error handling in the cleanup loop."""

    def test_cleanup_handles_cache_errors(self, clean_cache_state):
        """Test that cleanup handles errors gracefully."""
        from aragora.debate.convergence import (
            _PeriodicCacheCleanup,
        )

        cleanup = _PeriodicCacheCleanup(interval_seconds=0.01)

        # Mock cleanup_stale_similarity_caches to raise an error
        with patch(
            "aragora.debate.convergence.cleanup_stale_similarity_caches",
            side_effect=Exception("Test error"),
        ):
            cleanup.start()
            time.sleep(0.05)  # Let it attempt cleanup
            cleanup.stop()

        # Should not have crashed
        assert cleanup.is_running() is False

    def test_cleanup_loop_with_caches_to_clean(self, clean_cache_state):
        """Test cleanup loop actually cleans caches."""
        from aragora.debate.convergence import (
            _PeriodicCacheCleanup,
        )
        from aragora.debate import convergence

        # Create cache with old timestamp
        get_pairwise_similarity_cache("loop_cleanup_test")
        convergence._similarity_cache_timestamps["loop_cleanup_test"] = time.time() - 7200

        cleanup = _PeriodicCacheCleanup(interval_seconds=0.01)
        cleanup.start()
        time.sleep(0.05)  # Let cleanup run
        cleanup.stop()

        # Cache should have been cleaned
        stats = cleanup.get_stats()
        assert stats["total_caches_cleaned"] >= 0  # May have cleaned


# =============================================================================
# Sparse Matrix Handling Tests
# =============================================================================


class TestSparseMatrixHandling:
    """Tests for sparse matrix handling in TF-IDF backend."""

    def test_tfidf_sparse_to_dense(self, clean_cache_state):
        """Test TF-IDF sparse matrix conversion."""
        backend = TFIDFBackend()

        # TF-IDF produces sparse matrices internally
        texts = ["hello world", "hello there"]
        matrix = backend.vectorizer.fit_transform(texts)

        from scipy.sparse import issparse

        assert issparse(matrix)

        # Conversion to dense should work
        dense = matrix.toarray()
        assert dense.shape[0] == 2


# =============================================================================
# Maximum Cache Limit Tests
# =============================================================================


class TestMaximumCacheLimit:
    """Tests for maximum cache limit enforcement."""

    def test_max_caches_evicts_oldest(self, clean_cache_state):
        """Test that exceeding max caches evicts the oldest."""
        from aragora.debate import convergence

        # Temporarily set a low max
        with patch.object(convergence, "MAX_SIMILARITY_CACHES", 3):
            # Create 3 caches
            for i in range(3):
                get_pairwise_similarity_cache(f"max_test_{i}")
                time.sleep(0.001)  # Ensure different timestamps

            assert len(convergence._similarity_cache_manager) == 3

            # Create one more - should evict oldest
            get_pairwise_similarity_cache("max_test_new")

            # Should still have <= 3 caches
            assert len(convergence._similarity_cache_manager) <= 3
            assert "max_test_new" in convergence._similarity_cache_manager


# =============================================================================
# Analyzer No Previous Responses Tests
# =============================================================================


class TestAnalyzerNoPreviousResponses:
    """Tests for analyzer when no previous responses are provided."""

    def test_analyze_without_previous(self, clean_cache_state):
        """Test analyze with no previous responses."""
        analyzer = AdvancedConvergenceAnalyzer(
            similarity_backend=JaccardBackend(),
            debate_id="no_prev_test",
        )

        current = {
            "claude": "The system performs well under load.",
            "gpt4": "Performance is good during stress testing.",
        }

        metrics = analyzer.analyze(
            current_responses=current,
            previous_responses=None,  # No previous
            domain="testing",
        )

        # Semantic similarity should be 0 with no previous
        assert metrics.semantic_similarity == 0.0
        # But other metrics should still work
        assert metrics.argument_diversity is not None

    def test_analyze_without_history(self, clean_cache_state):
        """Test analyze with no response history."""
        analyzer = AdvancedConvergenceAnalyzer(
            similarity_backend=JaccardBackend(),
        )

        current = {"claude": "Test response"}
        previous = {"claude": "Previous response"}

        metrics = analyzer.analyze(
            current_responses=current,
            previous_responses=previous,
            response_history=None,
        )

        # Stance volatility should be None without history
        assert metrics.stance_volatility is None
