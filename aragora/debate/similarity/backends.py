"""Similarity computation backends for semantic comparison.

Provides a 3-tier fallback for similarity computation:
1. SentenceTransformer (best accuracy, requires sentence-transformers)
2. TF-IDF (good accuracy, requires scikit-learn)
3. Jaccard (always available, zero dependencies)
"""

from __future__ import annotations

import logging
import os
import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Any

try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore[assignment]  # Necessary: np typed as module but None when unavailable; guarded by HAS_NUMPY
    HAS_NUMPY = False

from aragora.debate.cache.embeddings_lru import (
    EmbeddingCache,
    get_embedding_cache,
    get_scoped_embedding_cache,
)

logger = logging.getLogger(__name__)

# Environment variables for backend selection
_ENV_SIMILARITY_BACKEND = "ARAGORA_SIMILARITY_BACKEND"
_ENV_CONVERGENCE_BACKEND = "ARAGORA_CONVERGENCE_BACKEND"

_BACKEND_ALIASES = {
    "sentence-transformers": "sentence-transformer",
    "sentence_transformers": "sentence-transformer",
    "sentence": "sentence-transformer",
    "tf-idf": "tfidf",
    "tf_idf": "tfidf",
}
_VALID_BACKENDS = {"auto", "sentence-transformer", "tfidf", "jaccard"}


def _normalize_backend_name(value: str) -> str | None:
    """Normalize backend name from environment variable."""
    if not value:
        return None
    key = value.strip().lower()
    key = key.replace("_", "-")
    key = _BACKEND_ALIASES.get(key, key)
    return key if key in _VALID_BACKENDS else None


class SimilarityBackend(ABC):
    """Abstract base class for similarity computation backends."""

    # Common contradiction word pairs (lowercase)
    _CONTRADICTION_PAIRS: list[tuple[str, str]] = [
        ("accept", "reject"),
        ("agree", "disagree"),
        ("approve", "disapprove"),
        ("yes", "no"),
        ("true", "false"),
        ("increase", "decrease"),
        ("raise", "lower"),
        ("support", "oppose"),
        ("allow", "deny"),
        ("enable", "disable"),
        ("include", "exclude"),
        ("add", "remove"),
        ("create", "delete"),
        ("start", "stop"),
        ("begin", "end"),
        ("open", "close"),
        ("for", "against"),
        ("pro", "con"),
        ("positive", "negative"),
        ("good", "bad"),
        ("better", "worse"),
        ("more", "less"),
        ("high", "low"),
        ("up", "down"),
        ("pass", "fail"),
        ("win", "lose"),
        ("keep", "discard"),
    ]

    @abstractmethod
    def compute_similarity(self, text1: str, text2: str) -> float:
        """
        Compute similarity between two texts.

        Args:
            text1: First text
            text2: Second text

        Returns:
            Similarity score between 0.0 (completely different) and 1.0 (identical)
        """
        raise NotImplementedError("Subclasses must implement compute_similarity")

    def is_contradictory(self, text1: str, text2: str) -> bool:
        """
        Check if two texts are semantically contradictory.

        This prevents grouping choices that are textually similar but
        semantically opposite (e.g., "Accept the proposal" vs "Reject the proposal").

        Args:
            text1: First text
            text2: Second text

        Returns:
            True if the texts appear to be contradictory choices
        """
        if not text1 or not text2:
            return False

        t1_lower = text1.lower()
        t2_lower = text2.lower()
        t1_words = set(t1_lower.split())
        t2_words = set(t2_lower.split())

        # Check for labeled options (Option A vs Option B, Choice 1 vs Choice 2)
        import re

        option_pattern = r"^(option|choice|alternative|answer)\s*[a-z0-9]+$"
        if re.match(option_pattern, t1_lower.strip()) and re.match(
            option_pattern, t2_lower.strip()
        ):
            # Both are labeled options - they're different choices
            return t1_lower.strip() != t2_lower.strip()

        # Check for contradiction word pairs
        for word1, word2 in self._CONTRADICTION_PAIRS:
            # Check if one text has word1 and the other has word2
            has_w1_in_t1 = word1 in t1_words or word1 in t1_lower
            has_w2_in_t2 = word2 in t2_words or word2 in t2_lower
            has_w1_in_t2 = word1 in t2_words or word1 in t2_lower
            has_w2_in_t1 = word2 in t2_words or word2 in t1_lower

            if (has_w1_in_t1 and has_w2_in_t2) or (has_w1_in_t2 and has_w2_in_t1):
                # Found a contradiction pair - but verify the texts share context
                # (e.g., both mention "proposal" or "funding")
                shared_words = t1_words & t2_words
                # Remove common stopwords
                stopwords = {
                    "the",
                    "a",
                    "an",
                    "is",
                    "are",
                    "was",
                    "were",
                    "to",
                    "of",
                    "and",
                    "or",
                    "it",
                    "this",
                    "that",
                }
                meaningful_shared = shared_words - stopwords
                if meaningful_shared or len(t1_words) <= 3 or len(t2_words) <= 3:
                    return True

        return False

    def compute_batch_similarity(self, texts: list[str]) -> float:
        """
        Compute average pairwise similarity across multiple texts.

        Args:
            texts: List of texts to compare

        Returns:
            Average similarity score
        """
        if len(texts) < 2:
            return 1.0

        total = 0.0
        count = 0
        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                total += self.compute_similarity(texts[i], texts[j])
                count += 1

        return total / count if count > 0 else 0.0


class JaccardBackend(SimilarityBackend):
    """
    Jaccard similarity using word overlap.

    Formula: |A ∩ B| / |A ∪ B|

    Pros:
        - Zero dependencies
        - Fast computation
        - Easy to understand

    Cons:
        - Doesn't understand semantics
        - Order-independent

    Performance optimization:
        - LRU cache for similarity computations (256 pairs, O(1) eviction)
    """

    _similarity_cache: OrderedDict[tuple[str, str], float] = OrderedDict()
    _cache_max_size = 256
    _cache_lock = threading.RLock()

    def compute_similarity(self, text1: str, text2: str) -> float:
        """Compute Jaccard similarity between two texts (thread-safe)."""
        if not text1 or not text2:
            return 0.0

        # Normalize key order for symmetric cache hits
        cache_key = (text1, text2) if text1 <= text2 else (text2, text1)

        # Check cache first (with lock)
        with JaccardBackend._cache_lock:
            if cache_key in JaccardBackend._similarity_cache:
                # Move to end for LRU (O(1))
                JaccardBackend._similarity_cache.move_to_end(cache_key)
                return JaccardBackend._similarity_cache[cache_key]

        # Normalize: lowercase and split into words (outside lock)
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        if not union:
            return 0.0

        result = len(intersection) / len(union)

        # Cache result with LRU eviction (O(1))
        with JaccardBackend._cache_lock:
            # Evict oldest if at capacity
            while len(JaccardBackend._similarity_cache) >= JaccardBackend._cache_max_size:
                JaccardBackend._similarity_cache.popitem(last=False)
            JaccardBackend._similarity_cache[cache_key] = result

        return result

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the similarity cache (thread-safe)."""
        with cls._cache_lock:
            cls._similarity_cache.clear()


class TFIDFBackend(SimilarityBackend):
    """
    TF-IDF similarity backend.

    Requires: scikit-learn

    Better than Jaccard because:
        - Weighs rare words higher (more discriminative)
        - Reduces impact of common words

    Performance optimization:
        - LRU cache for similarity computations (256 pairs, O(1) eviction)
    """

    _similarity_cache: OrderedDict[tuple[str, str], float] = OrderedDict()
    _cache_max_size = 256
    _cache_lock = threading.RLock()

    def __init__(self):
        """Initialize TF-IDF backend."""
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity

            self.vectorizer = TfidfVectorizer()
            self.cosine_similarity = cosine_similarity
        except ImportError as e:
            raise ImportError(
                "TFIDFBackend requires scikit-learn. Install with: pip install scikit-learn"
            ) from e

    def compute_similarity(self, text1: str, text2: str) -> float:
        """Compute TF-IDF cosine similarity between two texts (thread-safe)."""
        if not text1 or not text2:
            return 0.0

        # Normalize key order for symmetric cache hits
        cache_key = (text1, text2) if text1 <= text2 else (text2, text1)

        # Check cache first (with lock)
        with TFIDFBackend._cache_lock:
            if cache_key in TFIDFBackend._similarity_cache:
                # Move to end for LRU (O(1))
                TFIDFBackend._similarity_cache.move_to_end(cache_key)
                return TFIDFBackend._similarity_cache[cache_key]

        # Compute outside lock
        tfidf_matrix = self.vectorizer.fit_transform([text1, text2])
        similarity = self.cosine_similarity(tfidf_matrix[0], tfidf_matrix[1])[0][0]
        result = float(similarity)

        # Cache result with LRU eviction (O(1))
        with TFIDFBackend._cache_lock:
            # Evict oldest if at capacity
            while len(TFIDFBackend._similarity_cache) >= TFIDFBackend._cache_max_size:
                TFIDFBackend._similarity_cache.popitem(last=False)
            TFIDFBackend._similarity_cache[cache_key] = result

        return result

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the similarity cache (thread-safe)."""
        with cls._cache_lock:
            cls._similarity_cache.clear()


class SentenceTransformerBackend(SimilarityBackend):
    """
    Sentence transformer backend using neural embeddings.

    Requires: sentence-transformers (~500MB model download)

    Best accuracy because:
        - Understands semantics and context
        - Captures paraphrasing and synonyms

    Performance optimization:
        - Model is cached at class level (avoids reloading)
        - Embeddings are cached at text level (EmbeddingCache)
        - LRU cache for similarity/contradiction at pair level (256 pairs, O(1) eviction)
        - Expected speedup: 10-100x for repeated text comparisons

    Optional NLI (Natural Language Inference) support:
        - Uses cross-encoder model for accurate contradiction detection
        - Classifies pairs as entailment/neutral/contradiction
        - ~5-10ms per pair, deterministic, local (no API calls)
    """

    _model_cache: Any | None = None
    _model_name_cache: str | None = None
    _nli_model_cache: Any | None = None
    _nli_model_name_cache: str | None = None
    _similarity_cache: OrderedDict[tuple[str, str], float] = OrderedDict()
    _contradiction_cache: OrderedDict[tuple[str, str], bool] = OrderedDict()
    _cache_max_size: int = 256
    _cache_lock = threading.RLock()

    # NLI label indices (model-specific, but standard for most NLI models)
    _NLI_CONTRADICTION_LABEL = 0  # "contradiction"
    _NLI_ENTAILMENT_LABEL = 1  # "entailment"
    _NLI_NEUTRAL_LABEL = 2  # "neutral"

    model: Any
    cosine_similarity: Any
    embedding_cache: EmbeddingCache | None
    nli_model: Any | None
    use_nli: bool

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        use_embedding_cache: bool = True,
        persist_embeddings: bool = False,
        debate_id: str | None = None,
        use_nli: bool = True,
        nli_model_name: str = "cross-encoder/nli-deberta-v3-small",
    ):
        """
        Initialize sentence transformer backend.

        Args:
            model_name: Sentence transformer model name for embeddings
            use_embedding_cache: Enable embedding-level caching (default True)
            persist_embeddings: Persist embeddings to database (default False)
            debate_id: Debate ID for scoped cache (prevents cross-debate contamination)
            use_nli: Enable NLI model for contradiction detection (default True)
            nli_model_name: NLI cross-encoder model name (default: nli-deberta-v3-small)
        """
        try:
            from sentence_transformers import SentenceTransformer
            from sklearn.metrics.pairwise import cosine_similarity

            if (
                SentenceTransformerBackend._model_cache is not None
                and SentenceTransformerBackend._model_name_cache == model_name
            ):
                logger.debug("Reusing cached sentence transformer: %s", model_name)
                self.model = SentenceTransformerBackend._model_cache
            else:
                logger.info("Loading sentence transformer: %s", model_name)
                self.model = SentenceTransformer(model_name)
                SentenceTransformerBackend._model_cache = self.model
                SentenceTransformerBackend._model_name_cache = model_name

            self.cosine_similarity = cosine_similarity
            self.debate_id = debate_id
            self.use_nli = use_nli
            self.nli_model = None

            # Initialize NLI model for contradiction detection
            if use_nli:
                self._init_nli_model(nli_model_name)

            # Initialize embedding cache
            if use_embedding_cache:
                if debate_id:
                    # Use debate-scoped cache to prevent cross-debate contamination
                    self.embedding_cache = get_scoped_embedding_cache(debate_id)
                else:
                    # Fall back to global cache (deprecated but backwards compatible)
                    self.embedding_cache = get_embedding_cache(
                        max_size=1024,
                        persist=persist_embeddings,
                    )
            else:
                self.embedding_cache = None

        except (ImportError, RuntimeError) as e:
            # RuntimeError can occur from transformers/Keras compatibility issues
            raise ImportError(
                "SentenceTransformerBackend requires sentence-transformers. "
                f"Install with: pip install sentence-transformers. Error: {e}"
            ) from e

    def _init_nli_model(self, nli_model_name: str) -> None:
        """Initialize the NLI cross-encoder model for contradiction detection."""
        try:
            from sentence_transformers import CrossEncoder

            if (
                SentenceTransformerBackend._nli_model_cache is not None
                and SentenceTransformerBackend._nli_model_name_cache == nli_model_name
            ):
                logger.debug("Reusing cached NLI model: %s", nli_model_name)
                self.nli_model = SentenceTransformerBackend._nli_model_cache
            else:
                logger.info("Loading NLI model for contradiction detection: %s", nli_model_name)
                self.nli_model = CrossEncoder(nli_model_name)
                SentenceTransformerBackend._nli_model_cache = self.nli_model
                SentenceTransformerBackend._nli_model_name_cache = nli_model_name

        except (RuntimeError, ValueError, TypeError, OSError, ImportError) as e:
            logger.warning(
                "Failed to load NLI model '%s': %s. Falling back to pattern-based contradiction detection.",
                nli_model_name,
                e,
            )
            self.nli_model = None
            self.use_nli = False

    def _get_embedding(self, text: str) -> np.ndarray:
        """Get embedding for text, using cache if available."""
        if self.embedding_cache:
            cached = self.embedding_cache.get(text)
            if cached is not None:
                return cached

        # Compute embedding
        embedding = self.model.encode([text])[0]

        # Cache it
        if self.embedding_cache:
            self.embedding_cache.put(text, embedding)

        return embedding

    def compute_similarity(self, text1: str, text2: str) -> float:
        """Compute semantic similarity using sentence embeddings (thread-safe).

        Uses multi-level caching:
        1. LRU similarity cache (pair level, O(1) eviction) - fastest
        2. Embedding cache (text level) - avoids re-encoding same text
        3. Model encode (slowest) - only for cache misses
        """
        if not text1 or not text2:
            return 0.0

        # Normalize key order for symmetric cache hits
        cache_key = (text1, text2) if text1 <= text2 else (text2, text1)

        # Check similarity cache first (with lock)
        with SentenceTransformerBackend._cache_lock:
            if cache_key in SentenceTransformerBackend._similarity_cache:
                # Move to end for LRU (O(1))
                SentenceTransformerBackend._similarity_cache.move_to_end(cache_key)
                return SentenceTransformerBackend._similarity_cache[cache_key]

        # Get embeddings (checks embedding cache internally)
        emb1 = self._get_embedding(text1)
        emb2 = self._get_embedding(text2)

        # Compute cosine similarity
        similarity = self.cosine_similarity(emb1.reshape(1, -1), emb2.reshape(1, -1))[0][0]
        result = float(similarity)

        # Cache similarity result with LRU eviction (O(1))
        with SentenceTransformerBackend._cache_lock:
            # Evict oldest if at capacity
            while (
                len(SentenceTransformerBackend._similarity_cache)
                >= SentenceTransformerBackend._cache_max_size
            ):
                SentenceTransformerBackend._similarity_cache.popitem(last=False)
            SentenceTransformerBackend._similarity_cache[cache_key] = result

        return result

    def is_contradictory(self, text1: str, text2: str) -> bool:
        """
        Check if two texts are semantically contradictory using NLI model.

        Uses a cross-encoder NLI model to classify the relationship as
        entailment/neutral/contradiction. Falls back to pattern-based
        detection if NLI model is not available.

        Args:
            text1: First text
            text2: Second text

        Returns:
            True if the texts are contradictory
        """
        if not text1 or not text2:
            return False

        # Normalize key order for symmetric cache hits
        cache_key = (text1, text2) if text1 <= text2 else (text2, text1)

        # Check contradiction cache first
        with SentenceTransformerBackend._cache_lock:
            if cache_key in SentenceTransformerBackend._contradiction_cache:
                # Move to end for LRU (O(1))
                SentenceTransformerBackend._contradiction_cache.move_to_end(cache_key)
                return SentenceTransformerBackend._contradiction_cache[cache_key]

        # Use NLI model if available
        if self.nli_model is not None:
            result = self._nli_is_contradictory(text1, text2)
        else:
            # Fall back to pattern-based detection
            result = super().is_contradictory(text1, text2)

        # Cache result with LRU eviction (O(1))
        with SentenceTransformerBackend._cache_lock:
            # Evict oldest if at capacity
            while (
                len(SentenceTransformerBackend._contradiction_cache)
                >= SentenceTransformerBackend._cache_max_size
            ):
                SentenceTransformerBackend._contradiction_cache.popitem(last=False)
            SentenceTransformerBackend._contradiction_cache[cache_key] = result

        return result

    def _nli_is_contradictory(self, text1: str, text2: str) -> bool:
        """
        Use NLI model to detect contradiction.

        The model outputs scores for [contradiction, entailment, neutral].
        We check if contradiction has the highest score.
        """
        if self.nli_model is None:
            return super().is_contradictory(text1, text2)
        try:
            # CrossEncoder expects list of (text1, text2) pairs
            scores = self.nli_model.predict([(text1, text2)])

            # scores is array of shape (1, 3) for [contradiction, entailment, neutral]
            if hasattr(scores, "__len__") and len(scores) > 0:
                if hasattr(scores[0], "__len__"):
                    # Shape (1, 3) - get the contradiction score
                    contradiction_score = scores[0][self._NLI_CONTRADICTION_LABEL]
                    # Consider it a contradiction if that's the highest-scoring label
                    is_contradiction = contradiction_score == max(scores[0])
                    if is_contradiction:
                        logger.debug(
                            "NLI detected contradiction: '%s...' vs '%s...' "
                            "(scores: contra=%.3f, entail=%.3f, neutral=%.3f)",
                            text1[:50],
                            text2[:50],
                            scores[0][0],
                            scores[0][1],
                            scores[0][2],
                        )
                    return is_contradiction
            return False
        except (RuntimeError, ValueError, TypeError, OSError, AttributeError) as e:
            logger.warning("NLI prediction failed: %s. Using pattern fallback.", e)
            return super().is_contradictory(text1, text2)

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the similarity and contradiction caches (thread-safe)."""
        with cls._cache_lock:
            cls._similarity_cache.clear()
            cls._contradiction_cache.clear()

    def compute_batch_similarity(self, texts: list[str]) -> float:
        """
        Optimized batch similarity using single encode call and vectorized operations.

        Computes all embeddings at once, then uses matrix multiplication for
        pairwise cosine similarities. Much faster than looping:
        - For 10 texts: ~10x faster
        - For 50 texts: ~100x faster
        """
        if len(texts) < 2:
            return 1.0

        # Single batch encode (O(n) instead of O(n²) encode calls)
        embeddings = self.model.encode(texts)

        # Use vectorized matrix operations for pairwise similarity
        from aragora.debate.similarity.ann import compute_batch_similarity_fast

        return compute_batch_similarity_fast(embeddings)

    def compute_pairwise_similarities(self, texts_a: list[str], texts_b: list[str]) -> list[float]:
        """
        Compute similarities for paired texts efficiently.

        Args:
            texts_a: First list of texts
            texts_b: Second list of texts (must be same length)

        Returns:
            List of similarities for each pair (a[i], b[i])
        """
        if not texts_a or not texts_b or len(texts_a) != len(texts_b):
            return []

        # Batch encode both lists in one call
        all_texts = texts_a + texts_b
        embeddings = self.model.encode(all_texts)

        # Split embeddings
        n = len(texts_a)
        emb_a = embeddings[:n]
        emb_b = embeddings[n:]

        # Compute pairwise similarities
        similarities = []
        for i in range(n):
            sim = self.cosine_similarity(emb_a[i].reshape(1, -1), emb_b[i].reshape(1, -1))[0][0]
            similarities.append(float(sim))

        return similarities


def get_similarity_backend(
    preferred: str = "auto",
    debate_id: str | None = None,
) -> SimilarityBackend:
    """
    Get a similarity backend by name.

    Args:
        preferred: Backend preference: "auto", "sentence-transformer", "tfidf", "jaccard"
        debate_id: Debate ID for scoped caching (prevents cross-debate contamination)

    Returns:
        Requested backend instance
    """
    if preferred == "auto":
        env_override = _normalize_backend_name(os.getenv(_ENV_SIMILARITY_BACKEND, ""))
        if env_override:
            preferred = env_override
        elif os.getenv(_ENV_SIMILARITY_BACKEND):
            logger.warning("%s value is invalid; using auto selection.", _ENV_SIMILARITY_BACKEND)

    if preferred == "jaccard":
        return JaccardBackend()

    if preferred == "tfidf":
        return TFIDFBackend()

    if preferred == "sentence-transformer":
        return SentenceTransformerBackend(debate_id=debate_id)

    # Auto-select best available
    try:
        return SentenceTransformerBackend(debate_id=debate_id)
    except ImportError:
        logger.debug("sentence-transformers not available for auto-select")
    except RuntimeError as e:
        logger.debug("sentence-transformers failed: %s", e)
    except OSError as e:
        logger.debug("sentence-transformers model error: %s", e)
    except (ValueError, TypeError, AttributeError, ConnectionError) as e:
        # Catch-all for model loading failures (network, auth, etc.)
        logger.debug("sentence-transformers initialization error: %s", e)

    try:
        return TFIDFBackend()
    except ImportError:
        logger.debug("scikit-learn not available for auto-select")

    return JaccardBackend()


__all__ = [
    "SimilarityBackend",
    "JaccardBackend",
    "TFIDFBackend",
    "SentenceTransformerBackend",
    "get_similarity_backend",
]
