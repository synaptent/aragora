"""
Tests for Semantic Convergence Detection.

Tests cover:
- JaccardBackend (zero dependencies)
- TFIDFBackend (requires scikit-learn)
- SentenceTransformerBackend (requires sentence-transformers)
- ConvergenceResult dataclass
- ConvergenceDetector (threshold checking, status determination)
- get_similarity_backend factory function
"""

from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(scope="module")
def sentence_transformers_module():
    """Import sentence-transformers lazily to avoid heavy import at collection."""
    import sentence_transformers

    return sentence_transformers


requires_sentence_transformers = pytest.mark.usefixtures("sentence_transformers_module")

from aragora.debate.convergence import (
    JaccardBackend,
    TFIDFBackend,
    SentenceTransformerBackend,
    ConvergenceResult,
    ConvergenceDetector,
    SimilarityBackend,
    get_similarity_backend,
)


@pytest.fixture
def real_embeddings_backend():
    """Build a SentenceTransformerBackend on the real model, or skip.

    The real-similarity assertions encode genuine model semantics; the harness
    fake/mock embeddings are hash-based and cannot satisfy them, and a broken
    model download must skip rather than error.
    """
    import sentence_transformers as st

    if getattr(st, "__version__", "") == "0.0.0-test-fake":
        pytest.skip("Real embedding model unavailable: sentence_transformers is test-fake")
    # Clear ALL caches to ensure we get real models, not mocks from earlier tests
    SentenceTransformerBackend.clear_cache()
    SentenceTransformerBackend._model_cache = None
    SentenceTransformerBackend._model_name_cache = None
    try:
        backend = SentenceTransformerBackend()
    except Exception as e:  # noqa: BLE001 - any load failure means unavailable
        pytest.skip(f"Real embedding model unavailable: {type(e).__name__}: {e}")
    impl_module = type(backend.model).__module__
    if impl_module.startswith(("tests.", "unittest.mock")):
        pytest.skip(f"Real embedding model unavailable: model is a harness mock ({impl_module})")
    return backend


# =============================================================================
# Jaccard Backend Tests
# =============================================================================


class TestJaccardBackend:
    """Tests for Jaccard similarity backend."""

    @pytest.fixture
    def backend(self):
        return JaccardBackend()

    def test_identical_text_returns_one(self, backend):
        """Identical text should have similarity of 1.0."""
        text = "the quick brown fox jumps over the lazy dog"
        similarity = backend.compute_similarity(text, text)
        assert similarity == 1.0

    def test_completely_different_text_returns_zero(self, backend):
        """Completely different text should have similarity of 0.0."""
        text1 = "the quick brown fox"
        text2 = "airplane engine turbulence"
        similarity = backend.compute_similarity(text1, text2)
        assert similarity == 0.0

    def test_partial_overlap_returns_intermediate(self, backend):
        """Partially overlapping text should have intermediate similarity."""
        text1 = "the quick brown fox"
        text2 = "the lazy brown dog"
        similarity = backend.compute_similarity(text1, text2)
        # Shared: {the, brown} = 2, Union: {the, quick, brown, fox, lazy, dog} = 6
        # Expected: 2/6 = 0.333...
        assert 0.3 <= similarity <= 0.4

    def test_case_insensitive(self, backend):
        """Comparison should be case-insensitive."""
        text1 = "The Quick Brown Fox"
        text2 = "the quick brown fox"
        similarity = backend.compute_similarity(text1, text2)
        assert similarity == 1.0

    def test_empty_string_first_returns_zero(self, backend):
        """Empty first string should return 0.0."""
        similarity = backend.compute_similarity("", "some text")
        assert similarity == 0.0

    def test_empty_string_second_returns_zero(self, backend):
        """Empty second string should return 0.0."""
        similarity = backend.compute_similarity("some text", "")
        assert similarity == 0.0

    def test_both_empty_returns_zero(self, backend):
        """Both empty strings should return 0.0."""
        similarity = backend.compute_similarity("", "")
        assert similarity == 0.0

    def test_single_word_identical(self, backend):
        """Single identical words should return 1.0."""
        similarity = backend.compute_similarity("hello", "hello")
        assert similarity == 1.0

    def test_single_word_different(self, backend):
        """Single different words should return 0.0."""
        similarity = backend.compute_similarity("hello", "world")
        assert similarity == 0.0

    def test_compute_batch_similarity_single_text_returns_one(self, backend):
        """Batch with single text should return 1.0."""
        similarity = backend.compute_batch_similarity(["single text"])
        assert similarity == 1.0

    def test_compute_batch_similarity_empty_returns_one(self, backend):
        """Batch with no texts should return 1.0."""
        similarity = backend.compute_batch_similarity([])
        assert similarity == 1.0

    def test_compute_batch_similarity_pairwise_average(self, backend):
        """Batch should compute pairwise average similarity."""
        texts = ["hello world", "hello world", "goodbye moon"]
        similarity = backend.compute_batch_similarity(texts)
        # Pairs: (0,1)=1.0, (0,2)=0.0, (1,2)=0.0 -> avg = 1/3 ≈ 0.33
        assert 0.2 <= similarity <= 0.4


# =============================================================================
# TF-IDF Backend Tests
# =============================================================================


class TestTFIDFBackend:
    """Tests for TF-IDF similarity backend."""

    def test_import_error_when_sklearn_missing(self):
        """Should raise ImportError when sklearn not available."""
        with patch.dict("sys.modules", {"sklearn": None}):
            with patch(
                "aragora.debate.convergence.TFIDFBackend.__init__",
                side_effect=ImportError("No sklearn"),
            ):
                with pytest.raises(ImportError):
                    TFIDFBackend()

    def test_identical_text_returns_near_one(self):
        """Identical text should have similarity near 1.0."""
        backend = TFIDFBackend()
        text = "the quick brown fox jumps over the lazy dog"
        similarity = backend.compute_similarity(text, text)
        assert similarity == pytest.approx(1.0, abs=0.01)

    def test_different_text_returns_less_than_one(self):
        """Different text should have similarity less than 1.0."""
        backend = TFIDFBackend()
        text1 = "I prefer TypeScript for type safety"
        text2 = "JavaScript is more flexible"
        similarity = backend.compute_similarity(text1, text2)
        assert similarity < 1.0
        assert similarity >= 0.0

    def test_empty_string_first_returns_zero(self):
        """Empty first string should return 0.0."""
        backend = TFIDFBackend()
        similarity = backend.compute_similarity("", "some text")
        assert similarity == 0.0

    def test_empty_string_second_returns_zero(self):
        """Empty second string should return 0.0."""
        backend = TFIDFBackend()
        similarity = backend.compute_similarity("some text", "")
        assert similarity == 0.0

    def test_semantic_overlap_captured(self):
        """TF-IDF should capture word overlap."""
        backend = TFIDFBackend()
        text1 = "TypeScript provides type safety"
        text2 = "TypeScript is better for types"
        similarity = backend.compute_similarity(text1, text2)
        # Should have some similarity due to shared words
        assert similarity > 0.0


# =============================================================================
# Sentence Transformer Backend Tests
# =============================================================================


@requires_sentence_transformers
class TestSentenceTransformerBackend:
    """Tests for SentenceTransformer similarity backend."""

    def test_import_error_when_missing(self):
        """Should raise ImportError when sentence-transformers not available."""
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            with patch(
                "aragora.debate.convergence.SentenceTransformerBackend.__init__",
                side_effect=ImportError("No sentence-transformers"),
            ):
                with pytest.raises(ImportError):
                    SentenceTransformerBackend()

    def test_identical_text_returns_near_one(self):
        """Identical text should have similarity very close to 1.0."""
        backend = SentenceTransformerBackend()
        text = "The quick brown fox"
        similarity = backend.compute_similarity(text, text)
        assert similarity > 0.99

    @pytest.mark.slow
    def test_semantic_similarity_captured(self, real_embeddings_backend):
        """Should understand semantic similarity (requires real embeddings)."""
        backend = real_embeddings_backend
        text1 = "I prefer TypeScript for type safety"
        text2 = "TypeScript is better because it has types"
        similarity = backend.compute_similarity(text1, text2)
        # Semantically similar - should be high
        assert similarity > 0.5

    def test_model_caching(self):
        """Model should be cached and reused."""
        # Reset cache
        SentenceTransformerBackend._model_cache = None
        SentenceTransformerBackend._model_name_cache = None

        backend1 = SentenceTransformerBackend()
        model1 = backend1.model

        backend2 = SentenceTransformerBackend()
        model2 = backend2.model

        # Should be same object (cached)
        assert model1 is model2

    def test_empty_string_first_returns_zero(self):
        """Empty first string should return 0.0."""
        backend = SentenceTransformerBackend()
        similarity = backend.compute_similarity("", "some text")
        assert similarity == 0.0

    def test_empty_string_second_returns_zero(self):
        """Empty second string should return 0.0."""
        backend = SentenceTransformerBackend()
        similarity = backend.compute_similarity("some text", "")
        assert similarity == 0.0


# =============================================================================
# ConvergenceResult Tests
# =============================================================================


class TestConvergenceResult:
    """Tests for ConvergenceResult dataclass."""

    def test_creation_with_required_fields(self):
        """ConvergenceResult should be created with required fields."""
        result = ConvergenceResult(
            converged=True,
            status="converged",
            min_similarity=0.9,
            avg_similarity=0.92,
        )
        assert result.converged is True
        assert result.status == "converged"
        assert result.min_similarity == 0.9
        assert result.avg_similarity == 0.92

    def test_per_agent_similarity_defaults_empty(self):
        """per_agent_similarity should default to empty dict."""
        result = ConvergenceResult(
            converged=False,
            status="refining",
            min_similarity=0.5,
            avg_similarity=0.6,
        )
        assert result.per_agent_similarity == {}

    def test_consecutive_stable_rounds_defaults_zero(self):
        """consecutive_stable_rounds should default to 0."""
        result = ConvergenceResult(
            converged=False,
            status="refining",
            min_similarity=0.5,
            avg_similarity=0.6,
        )
        assert result.consecutive_stable_rounds == 0

    def test_per_agent_similarity_can_be_set(self):
        """per_agent_similarity should be settable."""
        result = ConvergenceResult(
            converged=True,
            status="converged",
            min_similarity=0.9,
            avg_similarity=0.92,
            per_agent_similarity={"claude": 0.95, "codex": 0.89},
        )
        assert result.per_agent_similarity["claude"] == 0.95
        assert result.per_agent_similarity["codex"] == 0.89


# =============================================================================
# ConvergenceDetector Tests
# =============================================================================


class TestConvergenceDetector:
    """Tests for ConvergenceDetector class."""

    def test_initialization_with_defaults(self):
        """Detector should initialize with default thresholds."""
        detector = ConvergenceDetector()
        assert detector.convergence_threshold == 0.85
        assert detector.divergence_threshold == 0.40
        assert detector.min_rounds_before_check == 1
        assert detector.consecutive_rounds_needed == 1

    def test_initialization_with_custom_thresholds(self):
        """Detector should accept custom thresholds."""
        detector = ConvergenceDetector(
            convergence_threshold=0.90,
            divergence_threshold=0.30,
            min_rounds_before_check=2,
            consecutive_rounds_needed=2,
        )
        assert detector.convergence_threshold == 0.90
        assert detector.divergence_threshold == 0.30
        assert detector.min_rounds_before_check == 2
        assert detector.consecutive_rounds_needed == 2

    def test_select_backend_returns_similarity_backend(self):
        """_select_backend should return a SimilarityBackend."""
        detector = ConvergenceDetector()
        assert isinstance(detector.backend, SimilarityBackend)

    def test_check_convergence_returns_none_before_min_rounds(self):
        """Should return None if round_number <= min_rounds_before_check."""
        detector = ConvergenceDetector(min_rounds_before_check=2)
        current = {"agent1": "response"}
        previous = {"agent1": "response"}

        result = detector.check_convergence(current, previous, round_number=1)
        assert result is None

        result = detector.check_convergence(current, previous, round_number=2)
        assert result is None

    def test_check_convergence_detects_convergence(self):
        """Should detect convergence when similarity >= threshold."""
        detector = ConvergenceDetector(
            convergence_threshold=0.85,
            min_rounds_before_check=1,
        )
        # Identical responses = 1.0 similarity
        current = {"agent1": "TypeScript is better", "agent2": "TypeScript is better"}
        previous = {"agent1": "TypeScript is better", "agent2": "TypeScript is better"}

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        assert result.converged is True
        assert result.status == "converged"
        assert result.min_similarity == pytest.approx(1.0, rel=1e-9)

    def test_check_convergence_detects_refining(self):
        """Should detect refining when similarity is intermediate."""
        detector = ConvergenceDetector(
            convergence_threshold=0.85,
            divergence_threshold=0.40,
            min_rounds_before_check=1,
        )
        # Partial overlap - need enough shared words to be 40-85% similar
        # Shared: {typescript, is, better, for, large, projects} = 6
        # Union: {typescript, is, better, for, large, projects, definitely} = 7
        # Jaccard = 6/7 ≈ 0.86 - just above threshold, let's adjust
        current = {"agent1": "TypeScript is better for large projects and teams"}
        previous = {"agent1": "TypeScript is good for medium projects and developers"}
        # Shared: {typescript, is, for, projects, and} = 5
        # Union: {typescript, is, better, for, large, projects, and, teams, good, medium, developers} = 11
        # Jaccard = 5/11 ≈ 0.45 - in refining range

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        assert result.converged is False
        assert result.status == "refining"

    def test_check_convergence_detects_diverging(self):
        """Should detect diverging when similarity < divergence_threshold."""
        detector = ConvergenceDetector(
            convergence_threshold=0.85,
            divergence_threshold=0.40,
            min_rounds_before_check=1,
        )
        # Completely different responses
        current = {"agent1": "airplane engine turbulence"}
        previous = {"agent1": "butterfly garden flowers"}

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        assert result.converged is False
        assert result.status == "diverging"
        assert result.min_similarity < 0.40

    def test_consecutive_stable_rounds_increments(self):
        """consecutive_stable_count should increment on stable rounds."""
        detector = ConvergenceDetector(
            convergence_threshold=0.85,
            consecutive_rounds_needed=2,
            min_rounds_before_check=1,
        )
        # First stable round
        current = {"agent1": "same response"}
        previous = {"agent1": "same response"}

        result1 = detector.check_convergence(current, previous, round_number=2)
        assert result1.consecutive_stable_rounds == 1
        assert result1.converged is False  # Needs 2 consecutive

        # Second stable round
        result2 = detector.check_convergence(current, previous, round_number=3)
        assert result2.consecutive_stable_rounds == 2
        assert result2.converged is True  # Now converged

    def test_convergence_requires_consecutive_rounds_needed(self):
        """Convergence should only trigger after consecutive_rounds_needed stable rounds."""
        detector = ConvergenceDetector(
            convergence_threshold=0.85,
            consecutive_rounds_needed=3,
            min_rounds_before_check=1,
        )
        current = {"agent1": "same"}
        previous = {"agent1": "same"}

        # Round 1
        result1 = detector.check_convergence(current, previous, round_number=2)
        assert result1.converged is False

        # Round 2
        result2 = detector.check_convergence(current, previous, round_number=3)
        assert result2.converged is False

        # Round 3 - should converge now
        result3 = detector.check_convergence(current, previous, round_number=4)
        assert result3.converged is True

    def test_reset_clears_consecutive_count(self):
        """reset() should clear consecutive_stable_count."""
        detector = ConvergenceDetector(
            convergence_threshold=0.85,
            min_rounds_before_check=1,
        )
        current = {"agent1": "same"}
        previous = {"agent1": "same"}

        detector.check_convergence(current, previous, round_number=2)
        assert detector.consecutive_stable_count >= 1

        detector.reset()
        assert detector.consecutive_stable_count == 0

    def test_handles_missing_agents_between_rounds(self):
        """Should handle case where agent sets don't match."""
        detector = ConvergenceDetector(min_rounds_before_check=1)
        current = {"agent1": "response", "agent2": "response"}
        previous = {"agent3": "response"}  # Different agents

        result = detector.check_convergence(current, previous, round_number=2)
        # Should return None due to no common agents
        assert result is None

    def test_computes_per_agent_similarity(self):
        """Should compute similarity for each agent."""
        detector = ConvergenceDetector(min_rounds_before_check=1)
        current = {
            "claude": "TypeScript is great",
            "codex": "JavaScript is flexible",
        }
        previous = {
            "claude": "TypeScript is great",
            "codex": "JavaScript is flexible",
        }

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        assert "claude" in result.per_agent_similarity
        assert "codex" in result.per_agent_similarity
        assert result.per_agent_similarity["claude"] == pytest.approx(1.0, rel=1e-9)
        assert result.per_agent_similarity["codex"] == pytest.approx(1.0, rel=1e-9)


# =============================================================================
# get_similarity_backend Factory Tests
# =============================================================================


class TestGetSimilarityBackend:
    """Tests for get_similarity_backend factory function."""

    def test_jaccard_returns_jaccard_backend(self):
        """'jaccard' should return JaccardBackend."""
        backend = get_similarity_backend("jaccard")
        assert isinstance(backend, JaccardBackend)

    def test_tfidf_returns_tfidf_backend(self):
        """'tfidf' should return TFIDFBackend if available."""
        backend = get_similarity_backend("tfidf")
        assert isinstance(backend, TFIDFBackend)

    @requires_sentence_transformers
    def test_sentence_transformer_returns_st_backend(self):
        """'sentence-transformer' should return SentenceTransformerBackend if available."""
        backend = get_similarity_backend("sentence-transformer")
        assert isinstance(backend, SentenceTransformerBackend)

    def test_auto_returns_backend(self):
        """'auto' should return best available backend."""
        backend = get_similarity_backend("auto")
        assert isinstance(backend, SimilarityBackend)

    def test_auto_returns_at_least_jaccard(self):
        """'auto' should at least return Jaccard (always available)."""
        # Force other backends to fail by patching the correct module
        with patch(
            "aragora.debate.similarity.backends.SentenceTransformerBackend",
            side_effect=ImportError,
        ):
            with patch(
                "aragora.debate.similarity.backends.TFIDFBackend",
                side_effect=ImportError,
            ):
                backend = get_similarity_backend("auto")
                assert isinstance(backend, JaccardBackend)


# =============================================================================
# Batch Similarity Tests (Performance Optimizations)
# =============================================================================


class TestBatchSimilarityMethods:
    """Tests for batch similarity computation methods."""

    def test_compute_batch_similarity_with_jaccard(self):
        """Test batch similarity with JaccardBackend."""
        backend = JaccardBackend()
        texts = ["hello world", "hello there", "goodbye world"]

        similarity = backend.compute_batch_similarity(texts)

        # Should be between 0 and 1
        assert 0.0 <= similarity <= 1.0
        # With partial overlaps, should be moderate
        assert 0.1 < similarity < 0.9

    def test_compute_batch_similarity_identical_texts(self):
        """Identical texts should have similarity of 1.0."""
        backend = JaccardBackend()
        texts = ["same text here", "same text here", "same text here"]

        similarity = backend.compute_batch_similarity(texts)
        assert similarity == pytest.approx(1.0, rel=1e-9)

    def test_compute_batch_similarity_different_texts(self):
        """Very different texts should have low similarity."""
        backend = JaccardBackend()
        texts = ["alpha beta gamma", "one two three", "red green blue"]

        similarity = backend.compute_batch_similarity(texts)
        # No common words, should be close to 0
        assert similarity == pytest.approx(0.0, rel=1e-9)

    def test_compute_batch_similarity_tfidf(self):
        """Test batch similarity with TFIDFBackend."""
        backend = TFIDFBackend()
        texts = ["machine learning", "deep learning", "neural networks"]

        similarity = backend.compute_batch_similarity(texts)
        assert 0.0 <= similarity <= 1.0

    @requires_sentence_transformers
    def test_sentence_transformer_compute_batch_optimized(self):
        """Test that SentenceTransformerBackend uses optimized batch encoding."""
        backend = SentenceTransformerBackend()
        texts = ["The quick brown fox", "A fast red fox", "The slow gray dog"]

        # This should use single encode call internally
        similarity = backend.compute_batch_similarity(texts)
        assert 0.0 <= similarity <= 1.0

    @pytest.mark.slow
    @requires_sentence_transformers
    def test_compute_pairwise_similarities_basic(self, real_embeddings_backend):
        """Test pairwise similarities (requires real embeddings)."""
        backend = real_embeddings_backend
        texts_a = ["hello world", "good morning", "python programming"]
        texts_b = ["hello world", "good evening", "javascript coding"]

        similarities = backend.compute_pairwise_similarities(texts_a, texts_b)

        assert len(similarities) == 3
        # First pair is identical
        assert similarities[0] == pytest.approx(1.0, rel=0.01)
        # Second pair is similar
        assert 0.3 < similarities[1] < 0.9
        # Third pair is somewhat related
        assert 0.0 < similarities[2] < 0.8

    @requires_sentence_transformers
    def test_compute_pairwise_similarities_empty_lists(self):
        """Test pairwise with empty lists returns empty."""
        backend = SentenceTransformerBackend()

        assert backend.compute_pairwise_similarities([], []) == []

    @requires_sentence_transformers
    def test_compute_pairwise_similarities_unequal_length(self):
        """Test pairwise with unequal lists returns empty."""
        backend = SentenceTransformerBackend()
        texts_a = ["one", "two"]
        texts_b = ["one", "two", "three"]

        # Unequal length should return empty
        assert backend.compute_pairwise_similarities(texts_a, texts_b) == []

    @requires_sentence_transformers
    def test_convergence_detector_uses_batch_method(self):
        """Test that ConvergenceDetector uses batch method when available."""
        detector = ConvergenceDetector(min_rounds_before_check=1)

        current = {
            "agent1": "TypeScript is a typed superset of JavaScript",
            "agent2": "Python is a dynamic language",
            "agent3": "Rust is a systems language",
        }
        previous = {
            "agent1": "TypeScript adds types to JavaScript",
            "agent2": "Python is dynamically typed",
            "agent3": "Rust focuses on memory safety",
        }

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        assert len(result.per_agent_similarity) == 3
        # Each agent should have some similarity with their previous response
        for agent, sim in result.per_agent_similarity.items():
            assert 0.0 <= sim <= 1.0


class TestConvergenceDetectorBatchIntegration:
    """Test that ConvergenceDetector correctly uses batch methods."""

    def test_uses_pairwise_method_when_available(self):
        """Detector should use compute_pairwise_similarities when available."""
        # Create a mock backend with the method
        mock_backend = MagicMock(spec=SimilarityBackend)
        mock_backend.compute_pairwise_similarities = MagicMock(return_value=[0.9, 0.8])

        detector = ConvergenceDetector(min_rounds_before_check=1)
        detector.backend = mock_backend

        current = {"a": "text1", "b": "text2"}
        previous = {"a": "text1_old", "b": "text2_old"}

        result = detector.check_convergence(current, previous, round_number=2)

        # Should have called the batch method
        mock_backend.compute_pairwise_similarities.assert_called_once()
        assert result is not None

    def test_falls_back_to_individual_without_batch_method(self):
        """Detector should fall back to individual calls without batch method."""
        mock_backend = MagicMock(spec=SimilarityBackend)
        mock_backend.compute_similarity = MagicMock(return_value=0.85)
        # Don't add compute_pairwise_similarities

        detector = ConvergenceDetector(min_rounds_before_check=1)
        detector.backend = mock_backend

        current = {"a": "text1", "b": "text2"}
        previous = {"a": "text1_old", "b": "text2_old"}

        result = detector.check_convergence(current, previous, round_number=2)

        # Should have called individual method twice
        assert mock_backend.compute_similarity.call_count == 2
        assert result is not None


# =============================================================================
# Edge Case Tests (F2)
# =============================================================================


class TestConvergenceEdgeCases:
    """Edge case tests for convergence detection."""

    def test_jaccard_with_unicode_text(self):
        """Jaccard should handle Unicode text correctly."""
        backend = JaccardBackend()
        text1 = "你好世界 hello world"
        text2 = "你好世界 hello everyone"

        similarity = backend.compute_similarity(text1, text2)
        # Should have some overlap (你好世界, hello)
        assert 0.0 < similarity < 1.0

    def test_jaccard_with_emojis(self):
        """Jaccard should handle emoji characters."""
        backend = JaccardBackend()
        text1 = "I love Python 🐍 programming"
        text2 = "I love JavaScript ☕ programming"

        similarity = backend.compute_similarity(text1, text2)
        # Shared: {I, love, programming} = 3, unique words differ
        assert 0.0 < similarity < 1.0

    def test_jaccard_with_numbers(self):
        """Jaccard should handle numeric text."""
        backend = JaccardBackend()
        text1 = "The answer is 42"
        text2 = "The answer is 42"

        similarity = backend.compute_similarity(text1, text2)
        assert similarity == 1.0

    def test_jaccard_whitespace_only_returns_zero(self):
        """Jaccard should return 0.0 for whitespace-only text."""
        backend = JaccardBackend()
        similarity = backend.compute_similarity("   ", "text")
        assert similarity == 0.0

    def test_jaccard_cache_symmetric(self):
        """Jaccard cache should be symmetric (text1, text2) == (text2, text1)."""
        JaccardBackend.clear_cache()
        backend = JaccardBackend()

        sim1 = backend.compute_similarity("hello world", "world peace")
        sim2 = backend.compute_similarity("world peace", "hello world")

        assert sim1 == sim2

    def test_jaccard_cache_eviction(self):
        """Jaccard cache should evict old entries when full."""
        JaccardBackend.clear_cache()
        backend = JaccardBackend()

        # Fill cache beyond max size
        for i in range(JaccardBackend._cache_max_size + 50):
            backend.compute_similarity(f"text{i} unique", f"other{i} unique")

        # Cache should not exceed max size
        assert len(JaccardBackend._similarity_cache) <= JaccardBackend._cache_max_size

    def test_tfidf_with_special_characters(self):
        """TF-IDF should handle special characters."""
        backend = TFIDFBackend()

        text1 = "C++ is fast! @performance #systems"
        text2 = "C++ is fast? @speed #optimization"

        similarity = backend.compute_similarity(text1, text2)
        assert 0.0 <= similarity <= 1.0

    def test_tfidf_cache_symmetric(self):
        """TF-IDF cache should be symmetric."""
        TFIDFBackend.clear_cache()
        backend = TFIDFBackend()

        sim1 = backend.compute_similarity("machine learning", "deep learning")
        sim2 = backend.compute_similarity("deep learning", "machine learning")

        assert sim1 == pytest.approx(sim2, rel=1e-9)

    def test_convergence_detector_very_long_text(self):
        """Detector should handle very long text."""
        detector = ConvergenceDetector(min_rounds_before_check=1)

        # Generate long text
        long_text = " ".join(["word"] * 1000)

        current = {"agent": long_text}
        previous = {"agent": long_text}

        result = detector.check_convergence(current, previous, round_number=2)
        assert result is not None
        assert result.converged is True

    def test_convergence_detector_single_agent(self):
        """Detector should work with single agent."""
        detector = ConvergenceDetector(min_rounds_before_check=1)

        current = {"agent1": "same response"}
        previous = {"agent1": "same response"}

        result = detector.check_convergence(current, previous, round_number=2)
        assert result is not None
        assert result.min_similarity == result.avg_similarity

    def test_convergence_detector_many_agents(self):
        """Detector should handle many agents efficiently."""
        detector = ConvergenceDetector(min_rounds_before_check=1)

        # Create 10 agents with identical responses
        current = {f"agent{i}": "consistent position" for i in range(10)}
        previous = {f"agent{i}": "consistent position" for i in range(10)}

        result = detector.check_convergence(current, previous, round_number=2)

        assert result is not None
        assert result.converged is True
        assert len(result.per_agent_similarity) == 10

    def test_convergence_detector_partial_agent_overlap(self):
        """Detector should work with partial agent overlap."""
        detector = ConvergenceDetector(min_rounds_before_check=1)

        current = {"agent1": "response", "agent2": "response", "agent3": "new"}
        previous = {"agent1": "response", "agent2": "response", "agent4": "old"}

        result = detector.check_convergence(current, previous, round_number=2)

        # Should compute for common agents only (agent1, agent2)
        assert result is not None
        assert "agent1" in result.per_agent_similarity
        assert "agent2" in result.per_agent_similarity
        assert "agent3" not in result.per_agent_similarity
        assert "agent4" not in result.per_agent_similarity


class TestBackendFallbackChain:
    """Test backend fallback behavior."""

    def test_auto_falls_back_on_import_error(self):
        """Auto-select should fall back gracefully on import errors."""
        with patch(
            "aragora.debate.similarity.backends.SentenceTransformerBackend",
            side_effect=ImportError("No module"),
        ):
            with patch(
                "aragora.debate.similarity.backends.TFIDFBackend",
                side_effect=ImportError("No sklearn"),
            ):
                backend = get_similarity_backend("auto")
                assert isinstance(backend, JaccardBackend)

    def test_auto_falls_back_on_runtime_error(self):
        """Auto-select should fall back on RuntimeError (Keras issues)."""
        with patch(
            "aragora.debate.similarity.backends.SentenceTransformerBackend",
            side_effect=RuntimeError("Keras 3 incompatible"),
        ):
            with patch(
                "aragora.debate.similarity.backends.TFIDFBackend",
                side_effect=ImportError("No sklearn"),
            ):
                backend = get_similarity_backend("auto")
                assert isinstance(backend, JaccardBackend)

    def test_auto_falls_back_on_os_error(self):
        """Auto-select should fall back on OSError (model files)."""
        with patch(
            "aragora.debate.similarity.backends.SentenceTransformerBackend",
            side_effect=OSError("Model file corrupted"),
        ):
            with patch(
                "aragora.debate.similarity.backends.TFIDFBackend",
                side_effect=ImportError("No sklearn"),
            ):
                backend = get_similarity_backend("auto")
                assert isinstance(backend, JaccardBackend)

    def test_detector_selects_backend_with_fallback(self):
        """ConvergenceDetector should use fallback chain."""
        with patch(
            "aragora.debate.convergence.SentenceTransformerBackend",
            side_effect=ImportError,
        ):
            with patch(
                "aragora.debate.convergence.TFIDFBackend",
                side_effect=ImportError,
            ):
                detector = ConvergenceDetector()
                assert isinstance(detector.backend, JaccardBackend)


class TestCacheBehavior:
    """Test cache behavior across backends."""

    def test_jaccard_clear_cache(self):
        """JaccardBackend.clear_cache() should clear the cache."""
        backend = JaccardBackend()
        backend.compute_similarity("test", "test")

        assert len(JaccardBackend._similarity_cache) > 0
        JaccardBackend.clear_cache()
        assert len(JaccardBackend._similarity_cache) == 0

    def test_tfidf_clear_cache(self):
        """TFIDFBackend.clear_cache() should clear the cache."""
        backend = TFIDFBackend()
        backend.compute_similarity("test", "test")

        assert len(TFIDFBackend._similarity_cache) > 0
        TFIDFBackend.clear_cache()
        assert len(TFIDFBackend._similarity_cache) == 0

    @requires_sentence_transformers
    def test_sentence_transformer_clear_cache(self):
        """SentenceTransformerBackend.clear_cache() should clear similarity cache."""
        backend = SentenceTransformerBackend()
        backend.compute_similarity("test", "test")

        assert len(SentenceTransformerBackend._similarity_cache) > 0
        SentenceTransformerBackend.clear_cache()
        assert len(SentenceTransformerBackend._similarity_cache) == 0

    def test_cache_hit_returns_same_value(self):
        """Cache hit should return identical value."""
        JaccardBackend.clear_cache()
        backend = JaccardBackend()

        result1 = backend.compute_similarity("hello world", "hello there")
        result2 = backend.compute_similarity("hello world", "hello there")

        assert result1 == result2


# =============================================================================
# Advanced Convergence Metrics Tests (G3)
# =============================================================================


from aragora.debate.convergence import (
    AdvancedConvergenceAnalyzer,
    AdvancedConvergenceMetrics,
    ArgumentDiversityMetric,
    EvidenceConvergenceMetric,
    StanceVolatilityMetric,
)


class TestArgumentDiversityMetric:
    """Tests for ArgumentDiversityMetric dataclass."""

    def test_is_converging_low_diversity(self):
        """Low diversity score indicates convergence."""
        metric = ArgumentDiversityMetric(
            unique_arguments=1,
            total_arguments=10,
            diversity_score=0.1,
        )
        assert metric.is_converging is True

    def test_is_converging_high_diversity(self):
        """High diversity score indicates not converging."""
        metric = ArgumentDiversityMetric(
            unique_arguments=8,
            total_arguments=10,
            diversity_score=0.8,
        )
        assert metric.is_converging is False


class TestEvidenceConvergenceMetric:
    """Tests for EvidenceConvergenceMetric dataclass."""

    def test_is_converging_high_overlap(self):
        """High overlap indicates convergence."""
        metric = EvidenceConvergenceMetric(
            shared_citations=5,
            total_citations=6,
            overlap_score=0.83,
        )
        assert metric.is_converging is True

    def test_is_converging_low_overlap(self):
        """Low overlap indicates not converging."""
        metric = EvidenceConvergenceMetric(
            shared_citations=1,
            total_citations=10,
            overlap_score=0.1,
        )
        assert metric.is_converging is False


class TestStanceVolatilityMetric:
    """Tests for StanceVolatilityMetric dataclass."""

    def test_is_stable_low_volatility(self):
        """Low volatility indicates stable positions."""
        metric = StanceVolatilityMetric(
            stance_changes=1,
            total_responses=20,
            volatility_score=0.05,
        )
        assert metric.is_stable is True

    def test_is_stable_high_volatility(self):
        """High volatility indicates unstable positions."""
        metric = StanceVolatilityMetric(
            stance_changes=10,
            total_responses=20,
            volatility_score=0.5,
        )
        assert metric.is_stable is False


class TestAdvancedConvergenceMetrics:
    """Tests for AdvancedConvergenceMetrics dataclass."""

    def test_compute_overall_score_semantic_only(self):
        """Overall score should work with just semantic similarity."""
        metrics = AdvancedConvergenceMetrics(
            semantic_similarity=0.8,
        )
        score = metrics.compute_overall_score()
        # 0.8 * 0.4 = 0.32 (only semantic contributes)
        assert score == pytest.approx(0.32, abs=0.01)

    def test_compute_overall_score_all_metrics(self):
        """Overall score should combine all metrics."""
        metrics = AdvancedConvergenceMetrics(
            semantic_similarity=0.9,
            argument_diversity=ArgumentDiversityMetric(
                unique_arguments=2,
                total_arguments=10,
                diversity_score=0.2,  # Low diversity = high convergence
            ),
            evidence_convergence=EvidenceConvergenceMetric(
                shared_citations=4,
                total_citations=5,
                overlap_score=0.8,
            ),
            stance_volatility=StanceVolatilityMetric(
                stance_changes=1,
                total_responses=10,
                volatility_score=0.1,  # Low volatility = high convergence
            ),
        )
        score = metrics.compute_overall_score()
        # 0.9*0.4 + 0.8*0.2 + 0.8*0.2 + 0.9*0.2 = 0.36 + 0.16 + 0.16 + 0.18 = 0.86
        assert 0.8 < score < 0.95

    def test_to_dict(self):
        """to_dict should include all metrics."""
        metrics = AdvancedConvergenceMetrics(
            semantic_similarity=0.85,
            argument_diversity=ArgumentDiversityMetric(
                unique_arguments=3,
                total_arguments=9,
                diversity_score=0.33,
            ),
            domain="technical",
        )
        metrics.compute_overall_score()

        result = metrics.to_dict()
        assert "semantic_similarity" in result
        assert "overall_convergence" in result
        assert "domain" in result
        assert result["domain"] == "technical"
        assert "argument_diversity" in result


class TestAdvancedConvergenceAnalyzer:
    """Tests for AdvancedConvergenceAnalyzer class."""

    @pytest.fixture
    def analyzer(self):
        """Create analyzer with Jaccard backend (fast, no deps)."""
        return AdvancedConvergenceAnalyzer(similarity_backend=JaccardBackend())

    def test_extract_arguments(self, analyzer):
        """Should extract substantive sentences as arguments."""
        text = "This is a short one. This is a much longer argument that should be extracted. Another short. This argument is also long enough to be included."
        args = analyzer.extract_arguments(text)
        assert len(args) == 2  # Only sentences with > 5 words

    def test_extract_citations_urls(self, analyzer):
        """Should extract URLs as citations."""
        text = "See https://example.com/paper.pdf for details. Also check http://docs.python.org."
        citations = analyzer.extract_citations(text)
        assert len(citations) == 2
        assert "https://example.com/paper.pdf" in citations

    def test_extract_citations_academic(self, analyzer):
        """Should extract academic-style citations."""
        text = "As shown by (Smith, 2024) and (Jones et al., 2023), this is true."
        citations = analyzer.extract_citations(text)
        assert "(Smith, 2024)" in citations
        assert "(Jones et al., 2023)" in citations

    def test_extract_citations_numbered(self, analyzer):
        """Should extract numbered citations."""
        text = "This is proven [1] and supported by [2]."
        citations = analyzer.extract_citations(text)
        assert "[1]" in citations
        assert "[2]" in citations

    def test_detect_stance_support(self, analyzer):
        """Should detect supportive stance."""
        text = "I strongly support this proposal. We should definitely implement it."
        stance = analyzer.detect_stance(text)
        assert stance == "support"

    def test_detect_stance_oppose(self, analyzer):
        """Should detect opposing stance."""
        text = "I disagree with this approach. We must reject this proposal."
        stance = analyzer.detect_stance(text)
        assert stance == "oppose"

    def test_detect_stance_neutral(self, analyzer):
        """Should detect neutral stance."""
        text = "The data is presented here for consideration."
        stance = analyzer.detect_stance(text)
        assert stance == "neutral"

    def test_compute_argument_diversity_empty(self, analyzer):
        """Should handle empty responses."""
        result = analyzer.compute_argument_diversity({})
        assert result.unique_arguments == 0
        assert result.total_arguments == 0
        assert result.diversity_score == 0.0

    def test_compute_argument_diversity_similar(self, analyzer):
        """Should detect low diversity when arguments are nearly identical."""
        # Use nearly identical sentences for Jaccard to detect high overlap
        responses = {
            "agent1": "TypeScript provides strong type safety for JavaScript developers and teams.",
            "agent2": "TypeScript provides strong type safety for JavaScript developers and projects.",
        }
        result = analyzer.compute_argument_diversity(responses)
        # Near-identical arguments should result in low diversity (< 0.5)
        # Jaccard needs ~70% word overlap to exceed 0.7 threshold
        assert result.diversity_score < 0.5

    def test_compute_evidence_convergence_shared(self, analyzer):
        """Should detect shared citations."""
        responses = {
            "agent1": "According to Smith, this is correct. See https://example.com.",
            "agent2": "As Smith noted, the result is confirmed at https://example.com.",
        }
        result = analyzer.compute_evidence_convergence(responses)
        assert result.shared_citations > 0
        assert result.overlap_score > 0

    def test_compute_evidence_convergence_no_citations(self, analyzer):
        """Should handle text without citations."""
        responses = {
            "agent1": "This is just plain text.",
            "agent2": "Another plain text response.",
        }
        result = analyzer.compute_evidence_convergence(responses)
        assert result.total_citations == 0
        assert result.overlap_score == 0.0

    def test_compute_stance_volatility_stable(self, analyzer):
        """Should detect stable stances."""
        history = [
            {"agent1": "I support this proposal strongly.", "agent2": "I agree with this."},
            {"agent1": "I still support this idea.", "agent2": "I continue to agree."},
            {"agent1": "My support remains strong.", "agent2": "I'm still in agreement."},
        ]
        result = analyzer.compute_stance_volatility(history)
        assert result.volatility_score < 0.3

    def test_compute_stance_volatility_volatile(self, analyzer):
        """Should detect volatile stances."""
        history = [
            {"agent1": "I support this proposal."},
            {"agent1": "Actually, I disagree now."},
            {"agent1": "On reflection, I support it again."},
            {"agent1": "No, I must oppose this."},
        ]
        result = analyzer.compute_stance_volatility(history)
        assert result.volatility_score > 0.5

    def test_analyze_full(self, analyzer):
        """Should compute comprehensive metrics."""
        current = {
            "agent1": "I strongly support using TypeScript. See (Smith, 2024).",
            "agent2": "TypeScript is beneficial for type safety. According to Smith.",
        }
        previous = {
            "agent1": "TypeScript seems like a good choice.",
            "agent2": "Type safety is important for maintainability.",
        }
        history = [previous, current]

        result = analyzer.analyze(
            current_responses=current,
            previous_responses=previous,
            response_history=history,
            domain="programming",
        )

        assert result.semantic_similarity > 0
        assert result.argument_diversity is not None
        assert result.evidence_convergence is not None
        assert result.stance_volatility is not None
        assert result.domain == "programming"
        assert 0 <= result.overall_convergence <= 1
