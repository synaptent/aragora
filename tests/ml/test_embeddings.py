"""
Tests for aragora.ml.embeddings module.

Tests cover:
- EmbeddingModel enum values
- EmbeddingResult dataclass and serialization
- SearchResult dataclass
- LocalEmbeddingConfig defaults and custom values
- LocalEmbeddingService initialization
- Embedding generation (single and batch)
- Similarity computation
- Search functionality
- Clustering
- Async methods
- Global instance caching
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from aragora.ml.embeddings import (
    EmbeddingModel,
    EmbeddingResult,
    LocalEmbeddingConfig,
    LocalEmbeddingService,
    SearchResult,
    get_embedding_service,
)


# =============================================================================
# TestEmbeddingModel - Enum Tests
# =============================================================================


class TestEmbeddingModel:
    """Tests for EmbeddingModel enum."""

    def test_all_models_defined(self):
        """Should define all expected models."""
        assert EmbeddingModel.MINILM.value == "all-MiniLM-L6-v2"
        assert EmbeddingModel.MINILM_L12.value == "all-MiniLM-L12-v2"
        assert EmbeddingModel.MPNET.value == "all-mpnet-base-v2"
        assert EmbeddingModel.MULTILINGUAL.value == "paraphrase-multilingual-MiniLM-L12-v2"
        assert (
            EmbeddingModel.CODE.value == "flax-sentence-embeddings/st-codesearch-distilroberta-base"
        )

    def test_models_are_strings(self):
        """Model values should be strings."""
        for model in EmbeddingModel:
            assert isinstance(model.value, str)

    def test_model_count(self):
        """Should have expected number of models."""
        assert len(EmbeddingModel) == 5


# =============================================================================
# TestEmbeddingResult - Dataclass Tests
# =============================================================================


class TestEmbeddingResultInit:
    """Tests for EmbeddingResult initialization."""

    def test_creates_with_all_fields(self):
        """Should create with all fields."""
        result = EmbeddingResult(
            text="Test text",
            embedding=[0.1, 0.2, 0.3],
            model="all-MiniLM-L6-v2",
            dimension=3,
        )

        assert result.text == "Test text"
        assert result.embedding == [0.1, 0.2, 0.3]
        assert result.model == "all-MiniLM-L6-v2"
        assert result.dimension == 3


class TestEmbeddingResultToDict:
    """Tests for EmbeddingResult.to_dict()."""

    def test_returns_dict(self):
        """to_dict should return dictionary."""
        result = EmbeddingResult(
            text="Test text",
            embedding=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            model="test-model",
            dimension=6,
        )

        d = result.to_dict()

        assert d["model"] == "test-model"
        assert d["dimension"] == 6
        assert d["embedding_preview"] == [0.1, 0.2, 0.3, 0.4, 0.5]

    def test_truncates_long_text(self):
        """Should truncate text longer than 100 chars."""
        long_text = "x" * 150
        result = EmbeddingResult(
            text=long_text,
            embedding=[0.1],
            model="test",
            dimension=1,
        )

        d = result.to_dict()
        assert len(d["text"]) == 103  # 100 + "..."
        assert d["text"].endswith("...")

    def test_keeps_short_text(self):
        """Should keep short text unchanged."""
        result = EmbeddingResult(
            text="Short text",
            embedding=[0.1],
            model="test",
            dimension=1,
        )

        d = result.to_dict()
        assert d["text"] == "Short text"


# =============================================================================
# TestSearchResult - Dataclass Tests
# =============================================================================


class TestSearchResult:
    """Tests for SearchResult dataclass."""

    def test_creates_with_required_fields(self):
        """Should create with required fields."""
        result = SearchResult(
            text="Found document",
            score=0.95,
            index=5,
        )

        assert result.text == "Found document"
        assert result.score == 0.95
        assert result.index == 5
        assert result.metadata == {}

    def test_creates_with_metadata(self):
        """Should accept metadata."""
        result = SearchResult(
            text="Document",
            score=0.8,
            index=2,
            metadata={"source": "database", "id": 123},
        )

        assert result.metadata == {"source": "database", "id": 123}


# =============================================================================
# TestLocalEmbeddingConfig - Configuration Tests
# =============================================================================


class TestLocalEmbeddingConfigDefaults:
    """Tests for LocalEmbeddingConfig default values."""

    def test_default_values(self):
        """Should have sensible defaults."""
        config = LocalEmbeddingConfig()

        assert config.model == EmbeddingModel.MINILM
        assert config.device == "cpu"
        assert config.normalize is True
        assert config.batch_size == 32
        assert config.show_progress is False
        assert config.cache_folder is None


class TestLocalEmbeddingConfigCustom:
    """Tests for LocalEmbeddingConfig custom values."""

    def test_accepts_custom_values(self):
        """Should accept custom configuration."""
        config = LocalEmbeddingConfig(
            model=EmbeddingModel.MPNET,
            device="cuda",
            normalize=False,
            batch_size=64,
            show_progress=True,
            cache_folder="/path/to/cache",
        )

        assert config.model == EmbeddingModel.MPNET
        assert config.device == "cuda"
        assert config.normalize is False
        assert config.batch_size == 64
        assert config.show_progress is True
        assert config.cache_folder == "/path/to/cache"


# =============================================================================
# TestLocalEmbeddingServiceInit - Initialization Tests
# =============================================================================


class TestLocalEmbeddingServiceInit:
    """Tests for LocalEmbeddingService initialization."""

    def test_creates_with_default_config(self):
        """Should create with default config."""
        service = LocalEmbeddingService()

        assert service.config is not None
        assert isinstance(service.config, LocalEmbeddingConfig)
        assert service._model is None

    def test_creates_with_custom_config(self):
        """Should accept custom config."""
        config = LocalEmbeddingConfig(model=EmbeddingModel.MPNET)
        service = LocalEmbeddingService(config)

        assert service.config.model == EmbeddingModel.MPNET


class TestLocalEmbeddingServiceProperties:
    """Tests for LocalEmbeddingService properties."""

    def test_model_name_property(self):
        """Should return model name."""
        config = LocalEmbeddingConfig(model=EmbeddingModel.MINILM)
        service = LocalEmbeddingService(config)

        assert service.model_name == "all-MiniLM-L6-v2"

    def test_dimension_property_loads_model(self):
        """Dimension property should trigger model load."""
        service = LocalEmbeddingService()

        # Mock the model
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384

        with patch.object(service, "_ensure_model_loaded") as mock_load:
            mock_load.side_effect = lambda: setattr(service, "_model", mock_model)
            dim = service.dimension

        assert dim == 384


# =============================================================================
# TestLocalEmbeddingServiceEnsureModelLoaded - Model Loading Tests
# =============================================================================


class TestLocalEmbeddingServiceEnsureModelLoaded:
    """Tests for LocalEmbeddingService._ensure_model_loaded()."""

    def test_raises_import_error_when_missing_deps(self):
        """Should raise ImportError when sentence-transformers missing."""
        service = LocalEmbeddingService()

        with patch("aragora.ml.embeddings.SentenceTransformer", None):
            with pytest.raises(ImportError, match="sentence-transformers"):
                service._ensure_model_loaded()

    def test_loads_model_once(self):
        """Should only load model once."""
        service = LocalEmbeddingService()

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384

        with patch("aragora.ml.embeddings.SentenceTransformer", return_value=mock_model):
            service._ensure_model_loaded()
            service._ensure_model_loaded()  # Second call

        # Model should be set
        assert service._model is mock_model


# =============================================================================
# TestLocalEmbeddingServiceEmbed - Embedding Tests
# =============================================================================


class TestLocalEmbeddingServiceEmbed:
    """Tests for LocalEmbeddingService.embed()."""

    @pytest.fixture
    def service_with_mock_model(self):
        """Create service with mocked model."""
        service = LocalEmbeddingService()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
        mock_model.get_sentence_embedding_dimension.return_value = 3
        service._model = mock_model
        return service

    def test_returns_list_of_floats(self, service_with_mock_model):
        """Should return embedding as list of floats."""
        embedding = service_with_mock_model.embed("Test text")

        assert isinstance(embedding, list)
        assert all(isinstance(x, float) for x in embedding)

    def test_passes_normalize_option(self, service_with_mock_model):
        """Should pass normalize option to model."""
        service_with_mock_model.embed("Test")

        service_with_mock_model._model.encode.assert_called_once()
        call_kwargs = service_with_mock_model._model.encode.call_args[1]
        assert "normalize_embeddings" in call_kwargs

    def test_raises_when_model_not_initialized(self):
        """Should raise RuntimeError when model fails to initialize."""
        service = LocalEmbeddingService()
        service._model = None

        with patch.object(service, "_ensure_model_loaded"):
            with pytest.raises(RuntimeError, match="Model not initialized"):
                service.embed("Test")


# =============================================================================
# TestLocalEmbeddingServiceEmbedBatch - Batch Embedding Tests
# =============================================================================


class TestLocalEmbeddingServiceEmbedBatch:
    """Tests for LocalEmbeddingService.embed_batch()."""

    @pytest.fixture
    def service_with_mock_model(self):
        """Create service with mocked model."""
        service = LocalEmbeddingService()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array(
            [
                [0.1, 0.2, 0.3],
                [0.4, 0.5, 0.6],
            ]
        )
        mock_model.get_sentence_embedding_dimension.return_value = 3
        service._model = mock_model
        return service

    def test_returns_empty_list_for_empty_input(self):
        """Should return empty list for empty input."""
        service = LocalEmbeddingService()
        result = service.embed_batch([])
        assert result == []

    def test_returns_list_of_embeddings(self, service_with_mock_model):
        """Should return list of embeddings."""
        embeddings = service_with_mock_model.embed_batch(["Text 1", "Text 2"])

        assert len(embeddings) == 2
        assert all(isinstance(e, list) for e in embeddings)

    def test_uses_batch_size(self, service_with_mock_model):
        """Should use configured batch size."""
        service_with_mock_model.config.batch_size = 16
        service_with_mock_model.embed_batch(["Text 1", "Text 2"])

        call_kwargs = service_with_mock_model._model.encode.call_args[1]
        assert call_kwargs["batch_size"] == 16


class TestLocalEmbeddingServiceExceedsMaxSeqLength:
    """Tests for LocalEmbeddingService.exceeds_max_seq_length()."""

    @staticmethod
    def _service(max_seq_length: int | None, tokenizer: object | None) -> LocalEmbeddingService:
        service = LocalEmbeddingService()
        service._model = MagicMock(max_seq_length=max_seq_length, tokenizer=tokenizer)
        return service

    @staticmethod
    def _word_tokenizer(texts: list[str], **kwargs: object) -> dict[str, list[list[int]]]:
        # One id per word plus the two special tokens the model adds.
        return {"input_ids": [[0] * (len(text.split()) + 2) for text in texts]}

    def test_flags_texts_longer_than_the_model_window(self):
        service = self._service(4, self._word_tokenizer)
        assert service.exceeds_max_seq_length(["one two", "one two three"]) == [False, True]

    def test_counts_the_special_tokens(self):
        tokenizer = MagicMock(side_effect=self._word_tokenizer)
        service = self._service(4, tokenizer)
        service.exceeds_max_seq_length(["one two"])
        assert tokenizer.call_args.kwargs["add_special_tokens"] is True

    def test_never_tokenizes_more_than_one_token_past_the_window(self):
        def bounded_tokenizer(texts: list[str], **kwargs: Any) -> dict[str, list[list[int]]]:
            encoded = self._word_tokenizer(texts)["input_ids"]
            if kwargs.get("truncation"):
                encoded = [ids[: kwargs["max_length"]] for ids in encoded]
            return {"input_ids": encoded}

        tokenizer = MagicMock(side_effect=bounded_tokenizer)
        service = self._service(4, tokenizer)

        flags = service.exceeds_max_seq_length(["one two", "word " * 100_000])

        assert flags == [False, True]
        assert tokenizer.call_args.kwargs["truncation"] is True
        assert tokenizer.call_args.kwargs["max_length"] == 5

    @pytest.mark.parametrize(
        ("max_seq_length", "tokenizer"),
        [(None, _word_tokenizer), (4, None)],
        ids=["no-window", "no-tokenizer"],
    )
    def test_reports_no_truncation_when_the_model_cannot_tell(self, max_seq_length, tokenizer):
        service = self._service(max_seq_length, tokenizer)
        assert service.exceeds_max_seq_length(["one two three four five"]) == [False]


# =============================================================================
# TestLocalEmbeddingServiceSimilarity - Similarity Tests
# =============================================================================


class TestLocalEmbeddingServiceSimilarity:
    """Tests for LocalEmbeddingService.similarity()."""

    @pytest.fixture
    def service(self):
        return LocalEmbeddingService()

    def test_identical_embeddings_similarity_one(self, service):
        """Identical embeddings should have similarity 1.0."""
        embedding = [0.5, 0.5, 0.5, 0.5]
        sim = service.similarity(embedding, embedding)
        assert sim == pytest.approx(1.0)

    def test_orthogonal_embeddings_similarity_zero(self, service):
        """Orthogonal embeddings should have similarity 0.0."""
        embedding1 = [1.0, 0.0, 0.0]
        embedding2 = [0.0, 1.0, 0.0]
        sim = service.similarity(embedding1, embedding2)
        assert sim == pytest.approx(0.0)

    def test_opposite_embeddings_negative_similarity(self, service):
        """Opposite embeddings should have negative similarity."""
        embedding1 = [1.0, 0.0, 0.0]
        embedding2 = [-1.0, 0.0, 0.0]
        sim = service.similarity(embedding1, embedding2)
        assert sim == pytest.approx(-1.0)

    def test_returns_float(self, service):
        """Should return Python float."""
        sim = service.similarity([0.1, 0.2], [0.3, 0.4])
        assert isinstance(sim, float)


# =============================================================================
# TestLocalEmbeddingServiceSearch - Search Tests
# =============================================================================


class TestLocalEmbeddingServiceSearch:
    """Tests for LocalEmbeddingService.search()."""

    @pytest.fixture
    def service_with_mock(self):
        """Create service with mocked embedding methods."""
        service = LocalEmbeddingService()

        # Mock embed methods
        def mock_embed(text):
            # Simple hash-based mock embedding
            return [float(ord(c) % 10) / 10 for c in text[:3].ljust(3)]

        def mock_embed_batch(texts):
            return [mock_embed(t) for t in texts]

        service.embed = mock_embed
        service.embed_batch = mock_embed_batch
        return service

    def test_returns_empty_for_empty_documents(self, service_with_mock):
        """Should return empty list for empty documents."""
        results = service_with_mock.search("query", [])
        assert results == []

    def test_returns_search_results(self, service_with_mock):
        """Should return SearchResult objects."""
        results = service_with_mock.search(
            query="test",
            documents=["doc1", "doc2", "doc3"],
            top_k=2,
        )

        assert len(results) <= 2
        assert all(isinstance(r, SearchResult) for r in results)

    def test_respects_top_k(self, service_with_mock):
        """Should respect top_k parameter."""
        results = service_with_mock.search(
            query="test",
            documents=["a", "b", "c", "d", "e"],
            top_k=3,
        )

        assert len(results) <= 3

    def test_applies_threshold(self):
        """Should filter by threshold."""
        service = LocalEmbeddingService()

        # Mock to return specific similarities
        service.embed = lambda x: [0.5, 0.5]
        service.embed_batch = lambda texts: [
            [0.9, 0.1] if "high" in t else [0.1, 0.1] for t in texts
        ]
        service.config.normalize = True

        results = service.search(
            query="test",
            documents=["high similarity", "low match"],
            threshold=0.5,
        )

        # Only high similarity should pass threshold
        assert len(results) <= 1

    def test_results_sorted_by_score(self, service_with_mock):
        """Results should be sorted by descending score."""
        results = service_with_mock.search(
            query="test",
            documents=["a", "b", "c"],
            top_k=3,
        )

        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert results[i].score >= results[i + 1].score


# =============================================================================
# TestLocalEmbeddingServiceCluster - Clustering Tests
# =============================================================================


class TestLocalEmbeddingServiceCluster:
    """Tests for LocalEmbeddingService.cluster()."""

    @pytest.fixture
    def service_with_mock(self):
        """Create service with mocked embedding."""
        service = LocalEmbeddingService()
        service.embed_batch = lambda texts: [[float(i), float(i) * 2] for i, _ in enumerate(texts)]
        return service

    def test_returns_fewer_clusters_when_fewer_texts(self, service_with_mock):
        """Should return range labels when fewer texts than clusters."""
        labels = service_with_mock.cluster(["a", "b"], n_clusters=5)

        assert labels == [0, 1]

    def test_returns_cluster_labels(self, service_with_mock):
        """Should return cluster labels for each text."""
        with patch("sklearn.cluster.KMeans") as MockKMeans:
            mock_kmeans = MagicMock()
            mock_kmeans.fit_predict.return_value = np.array([0, 0, 1, 1, 2])
            MockKMeans.return_value = mock_kmeans

            labels = service_with_mock.cluster(
                texts=["a", "b", "c", "d", "e"],
                n_clusters=3,
            )

        assert len(labels) == 5
        assert all(isinstance(label, int) for label in labels)

    def test_respects_n_clusters(self, service_with_mock):
        """Should use requested number of clusters."""
        with patch("sklearn.cluster.KMeans") as MockKMeans:
            mock_kmeans = MagicMock()
            mock_kmeans.fit_predict.return_value = np.array([0, 1, 2, 0, 1])
            MockKMeans.return_value = mock_kmeans

            service_with_mock.cluster(
                texts=["a", "b", "c", "d", "e"],
                n_clusters=3,
            )

        MockKMeans.assert_called_once()
        assert MockKMeans.call_args[1]["n_clusters"] == 3


# =============================================================================
# TestLocalEmbeddingServiceAsync - Async Method Tests
# =============================================================================


class TestLocalEmbeddingServiceAsync:
    """Tests for LocalEmbeddingService async methods."""

    @pytest.fixture
    def service_with_mock(self):
        """Create service with mocked sync methods."""
        service = LocalEmbeddingService()
        service.embed = MagicMock(return_value=[0.1, 0.2, 0.3])
        service.embed_batch = MagicMock(return_value=[[0.1, 0.2], [0.3, 0.4]])
        service.search = MagicMock(return_value=[SearchResult("doc", 0.9, 0)])
        return service

    @pytest.mark.asyncio
    async def test_embed_async(self, service_with_mock):
        """embed_async should call sync embed."""
        result = await service_with_mock.embed_async("Test text")

        service_with_mock.embed.assert_called_once_with("Test text")
        assert result == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_embed_batch_async(self, service_with_mock):
        """embed_batch_async should call sync embed_batch."""
        result = await service_with_mock.embed_batch_async(["Text 1", "Text 2"])

        service_with_mock.embed_batch.assert_called_once()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_search_async(self, service_with_mock):
        """search_async should call sync search."""
        result = await service_with_mock.search_async(
            query="test",
            documents=["doc1", "doc2"],
            top_k=5,
            threshold=0.5,
        )

        service_with_mock.search.assert_called_once()
        assert len(result) == 1


# =============================================================================
# TestGetEmbeddingService - Global Instance Tests
# =============================================================================


class TestGetEmbeddingService:
    """Tests for get_embedding_service global function."""

    def test_returns_embedding_service(self):
        """Should return LocalEmbeddingService instance."""
        with patch("aragora.ml.embeddings._embedding_services", {}):
            service = get_embedding_service()
            assert isinstance(service, LocalEmbeddingService)

    def test_caches_by_model_and_device(self):
        """Should cache services by model and device."""
        with patch("aragora.ml.embeddings._embedding_services", {}):
            service1 = get_embedding_service(EmbeddingModel.MINILM, "cpu")
            service2 = get_embedding_service(EmbeddingModel.MINILM, "cpu")

            assert service1 is service2

    def test_creates_new_for_different_config(self):
        """Should create new service for different config."""
        with patch("aragora.ml.embeddings._embedding_services", {}):
            service1 = get_embedding_service(EmbeddingModel.MINILM, "cpu")
            service2 = get_embedding_service(EmbeddingModel.MPNET, "cpu")

            assert service1 is not service2

    def test_uses_correct_model(self):
        """Should use specified model."""
        with patch("aragora.ml.embeddings._embedding_services", {}):
            service = get_embedding_service(EmbeddingModel.MPNET)

            assert service.config.model == EmbeddingModel.MPNET

    def test_uses_correct_device(self):
        """Should use specified device."""
        with patch("aragora.ml.embeddings._embedding_services", {}):
            service = get_embedding_service(device="cuda")

            assert service.config.device == "cuda"


# =============================================================================
# Integration Tests
# =============================================================================


class TestLocalEmbeddingServiceIntegration:
    """Integration tests for embedding service workflow."""

    def test_similarity_symmetric(self):
        """Similarity should be symmetric."""
        service = LocalEmbeddingService()

        embedding1 = [0.1, 0.2, 0.3, 0.4]
        embedding2 = [0.5, 0.6, 0.7, 0.8]

        sim1 = service.similarity(embedding1, embedding2)
        sim2 = service.similarity(embedding2, embedding1)

        assert sim1 == pytest.approx(sim2)

    def test_normalized_embeddings_high_self_similarity(self):
        """Normalized embeddings should have self-similarity of 1."""
        service = LocalEmbeddingService()
        service.config.normalize = True

        # Create unit vector
        embedding = [0.5, 0.5, 0.5, 0.5]
        norm = np.linalg.norm(embedding)
        normalized = [x / norm for x in embedding]

        sim = service.similarity(normalized, normalized)
        assert sim == pytest.approx(1.0, abs=0.001)

    def test_search_finds_similar_documents(self):
        """Search should rank similar documents higher."""
        service = LocalEmbeddingService()

        # Mock to return embeddings based on content similarity
        def mock_embed(text):
            if "python" in text.lower():
                return [0.9, 0.1, 0.0]
            elif "programming" in text.lower():
                return [0.8, 0.2, 0.0]
            else:
                return [0.1, 0.1, 0.8]

        service.embed = mock_embed
        service.embed_batch = lambda texts: [mock_embed(t) for t in texts]

        results = service.search(
            query="Python programming",
            documents=[
                "Python is great",
                "Java programming",
                "Cooking recipes",
            ],
            top_k=3,
        )

        # Python doc should rank highest
        assert results[0].text == "Python is great"

    def test_batch_consistency(self):
        """Batch embedding should produce same results as individual."""
        service = LocalEmbeddingService()

        mock_embeddings = {
            "text1": [0.1, 0.2],
            "text2": [0.3, 0.4],
        }

        service.embed = lambda t: mock_embeddings.get(t, [0.0, 0.0])
        service.embed_batch = lambda texts: [mock_embeddings.get(t, [0.0, 0.0]) for t in texts]

        # Individual
        emb1 = service.embed("text1")
        emb2 = service.embed("text2")

        # Batch
        batch = service.embed_batch(["text1", "text2"])

        assert emb1 == batch[0]
        assert emb2 == batch[1]

    def test_config_immutability(self):
        """Config should not change after initialization."""
        config = LocalEmbeddingConfig(
            model=EmbeddingModel.MINILM,
            device="cpu",
            batch_size=32,
        )

        service = LocalEmbeddingService(config)

        # Verify config values are preserved
        assert service.config.model == EmbeddingModel.MINILM
        assert service.config.device == "cpu"
        assert service.config.batch_size == 32

    @pytest.mark.asyncio
    async def test_async_methods_thread_safe(self):
        """Async methods should be thread-safe with lock."""
        service = LocalEmbeddingService()
        service.embed = MagicMock(return_value=[0.1, 0.2])

        # Run multiple async operations concurrently
        async def embed_task(text):
            return await service.embed_async(text)

        results = await asyncio.gather(
            embed_task("text1"),
            embed_task("text2"),
            embed_task("text3"),
        )

        assert len(results) == 3
        assert all(r == [0.1, 0.2] for r in results)

    def test_search_with_threshold_filters_results(self):
        """Search with threshold should filter low-scoring results."""
        service = LocalEmbeddingService()

        # Create embeddings that give predictable similarities
        query_emb = [1.0, 0.0, 0.0]
        doc_embs = [
            [0.9, 0.1, 0.0],  # High similarity
            [0.5, 0.5, 0.0],  # Medium similarity
            [0.0, 0.0, 1.0],  # Low similarity
        ]

        service.embed = lambda x: query_emb
        service.embed_batch = lambda x: doc_embs

        results = service.search(
            query="test",
            documents=["high", "medium", "low"],
            top_k=10,
            threshold=0.6,
        )

        # Only high and possibly medium should pass
        assert len(results) <= 2
        for r in results:
            assert r.score >= 0.6


# =============================================================================
# TestLocalEmbeddingServiceDimensionErrors - Dimension Property Error Paths
# =============================================================================


class TestLocalEmbeddingServiceDimensionErrors:
    """Tests for dimension property error paths."""

    def test_dimension_raises_when_model_fails_to_load(self):
        """Should raise RuntimeError if model stays None after _ensure_model_loaded."""
        service = LocalEmbeddingService()

        # _ensure_model_loaded does nothing, leaving _model as None
        with patch.object(service, "_ensure_model_loaded"):
            with pytest.raises(RuntimeError, match="Model not initialized"):
                _ = service.dimension

    def test_dimension_raises_when_model_returns_none(self):
        """Should raise RuntimeError if model returns None dimension."""
        service = LocalEmbeddingService()

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = None

        with patch.object(
            service,
            "_ensure_model_loaded",
            side_effect=lambda: setattr(service, "_model", mock_model),
        ):
            with pytest.raises(RuntimeError, match="returned None"):
                _ = service.dimension

    def test_dimension_caches_after_first_call(self):
        """Should cache dimension after first computation."""
        service = LocalEmbeddingService()

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384

        with patch.object(
            service,
            "_ensure_model_loaded",
            side_effect=lambda: setattr(service, "_model", mock_model),
        ):
            dim1 = service.dimension
            dim2 = service.dimension

        assert dim1 == 384
        assert dim2 == 384
        # Should only call get_sentence_embedding_dimension once
        assert mock_model.get_sentence_embedding_dimension.call_count == 1


# =============================================================================
# TestLocalEmbeddingServiceEmbedBatchErrors - Batch Embedding Error Paths
# =============================================================================


class TestLocalEmbeddingServiceEmbedBatchErrors:
    """Tests for embed_batch error paths."""

    def test_raises_when_model_not_initialized(self):
        """Should raise RuntimeError when model fails to initialize."""
        service = LocalEmbeddingService()
        service._model = None

        with patch.object(service, "_ensure_model_loaded"):
            with pytest.raises(RuntimeError, match="Model not initialized"):
                service.embed_batch(["Test"])


# =============================================================================
# TestLocalEmbeddingServiceSearchNormalize - Search Normalization Paths
# =============================================================================


class TestLocalEmbeddingServiceSearchNormalize:
    """Tests for search normalization behavior."""

    def test_search_with_normalize_false(self):
        """Search without normalization should use full cosine formula."""
        service = LocalEmbeddingService()
        service.config.normalize = False

        # Set up predictable embeddings
        query_emb = [1.0, 0.0]
        doc_embs = [[1.0, 0.0], [0.0, 1.0]]

        service.embed = lambda x: query_emb
        service.embed_batch = lambda x: doc_embs

        results = service.search(
            query="test",
            documents=["similar", "different"],
            top_k=2,
        )

        # First doc should have high similarity (1.0)
        assert results[0].score == pytest.approx(1.0)
        # Second doc should have low similarity (0.0)
        assert results[1].score == pytest.approx(0.0)

    def test_search_with_normalize_true(self):
        """Search with normalization should use dot product only."""
        service = LocalEmbeddingService()
        service.config.normalize = True

        query_emb = [1.0, 0.0]
        doc_embs = [[0.8, 0.2], [0.2, 0.8]]

        service.embed = lambda x: query_emb
        service.embed_batch = lambda x: doc_embs

        results = service.search(
            query="test",
            documents=["doc1", "doc2"],
            top_k=2,
        )

        assert len(results) == 2
        assert results[0].score > results[1].score


# =============================================================================
# TestLocalEmbeddingServiceClusterEdgeCases - Cluster Edge Cases
# =============================================================================


class TestLocalEmbeddingServiceClusterEdgeCases:
    """Tests for cluster edge cases."""

    def test_cluster_single_text(self):
        """Should handle single text by returning [0]."""
        service = LocalEmbeddingService()
        service.embed_batch = lambda texts: [[1.0, 0.0]]

        labels = service.cluster(["single"], n_clusters=5)
        assert labels == [0]

    def test_cluster_empty_texts(self):
        """Should handle empty text list."""
        service = LocalEmbeddingService()
        service.embed_batch = lambda texts: []

        labels = service.cluster([], n_clusters=5)
        assert labels == []

    def test_cluster_equal_texts_and_clusters(self):
        """Should handle when texts == clusters (returns range)."""
        service = LocalEmbeddingService()
        service.embed_batch = lambda texts: [[float(i)] for i in range(len(texts))]

        labels = service.cluster(["a", "b", "c"], n_clusters=5)
        assert labels == [0, 1, 2]


# =============================================================================
# TestEmbeddingResultEdgeCases - Edge Cases for EmbeddingResult
# =============================================================================


class TestEmbeddingResultEdgeCases:
    """Edge case tests for EmbeddingResult."""

    def test_exactly_100_char_text(self):
        """Text at exactly 100 chars should not be truncated."""
        text = "x" * 100
        result = EmbeddingResult(
            text=text,
            embedding=[0.1],
            model="test",
            dimension=1,
        )
        d = result.to_dict()
        assert d["text"] == text
        assert not d["text"].endswith("...")

    def test_embedding_preview_fewer_than_5(self):
        """Should handle embedding with fewer than 5 dimensions."""
        result = EmbeddingResult(
            text="Test",
            embedding=[0.1, 0.2],
            model="test",
            dimension=2,
        )
        d = result.to_dict()
        assert d["embedding_preview"] == [0.1, 0.2]

    def test_empty_embedding(self):
        """Should handle empty embedding."""
        result = EmbeddingResult(
            text="Test",
            embedding=[],
            model="test",
            dimension=0,
        )
        d = result.to_dict()
        assert d["embedding_preview"] == []


# =============================================================================
# TestSimilarityEdgeCases - Edge Cases for Similarity
# =============================================================================


class TestSimilarityEdgeCases:
    """Edge case tests for similarity computation."""

    def test_single_dimension_embeddings(self):
        """Should work with single-dimension embeddings."""
        service = LocalEmbeddingService()
        sim = service.similarity([1.0], [1.0])
        assert sim == pytest.approx(1.0)

    def test_large_embeddings(self):
        """Should work with large embeddings."""
        service = LocalEmbeddingService()
        emb1 = list(np.random.randn(768))
        emb2 = list(np.random.randn(768))
        sim = service.similarity(emb1, emb2)
        assert -1.0 <= sim <= 1.0

    def test_near_zero_embeddings(self):
        """Should handle near-zero embeddings."""
        service = LocalEmbeddingService()
        sim = service.similarity([1e-10, 1e-10], [1e-10, 1e-10])
        # Result may be imprecise due to floating point
        assert isinstance(sim, float)


# =============================================================================
# TestGetEmbeddingServiceEdgeCases - Global Function Edge Cases
# =============================================================================


class TestGetEmbeddingServiceEdgeCases:
    """Edge case tests for get_embedding_service."""

    def test_creates_with_different_devices(self):
        """Should create separate services for different devices."""
        with patch("aragora.ml.embeddings._embedding_services", {}):
            service_cpu = get_embedding_service(EmbeddingModel.MINILM, "cpu")
            service_cuda = get_embedding_service(EmbeddingModel.MINILM, "cuda")
            assert service_cpu is not service_cuda

    def test_service_uses_correct_batch_size(self):
        """Service should use config batch_size."""
        with patch("aragora.ml.embeddings._embedding_services", {}):
            service = get_embedding_service(EmbeddingModel.MINILM, "cpu")
            assert service.config.batch_size == 32  # Default

    def test_model_name_enum_values(self):
        """All models should have valid string values."""
        for model in EmbeddingModel:
            with patch("aragora.ml.embeddings._embedding_services", {}):
                service = get_embedding_service(model, "cpu")
                assert service.model_name == model.value
