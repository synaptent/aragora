"""Tests for Index namespace API."""

from __future__ import annotations

import pytest

from aragora_sdk.client import AragoraAsyncClient, AragoraClient


class TestIndexEmbedding:
    """Tests for embedding operations."""

    def test_embed_single_text(self, client: AragoraClient, mock_request) -> None:
        """Embed a single text."""
        mock_request.return_value = {
            "embeddings": [[0.1, 0.2, 0.3]],
            "dimension": 3,
        }

        result = client.index.embed(text="hello world")

        mock_request.assert_called_once_with(
            "POST",
            "/api/v1/ml/embed",
            params=None,
            json={"text": "hello world"},
            headers=None,
        )
        assert result["dimension"] == 3

    def test_embed_multiple_texts(self, client: AragoraClient, mock_request) -> None:
        """Embed multiple texts."""
        mock_request.return_value = {
            "embeddings": [[0.1, 0.2], [0.3, 0.4]],
            "dimension": 2,
        }

        result = client.index.embed(texts=["hello", "world"])

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["json"]["texts"] == ["hello", "world"]
        assert len(result["embeddings"]) == 2

    def test_embed_with_model(self, client: AragoraClient, mock_request) -> None:
        """Embed with specific model."""
        mock_request.return_value = {"embeddings": [[0.1]], "dimension": 1}

        client.index.embed(text="test", model="text-embedding-3-small")

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["json"]["model"] == "text-embedding-3-small"


class TestIndexSearch:
    """Tests for semantic search operations."""

    def test_search_documents(self, client: AragoraClient, mock_request) -> None:
        """Search documents by query."""
        mock_request.return_value = {
            "results": [
                {"text": "machine learning", "score": 0.95, "index": 0},
                {"text": "deep learning", "score": 0.85, "index": 1},
            ]
        }

        result = client.index.search(
            query="AI",
            documents=["machine learning", "deep learning", "cooking"],
            top_k=2,
        )

        mock_request.assert_called_once_with(
            "POST",
            "/api/v1/ml/search",
            params=None,
            json={
                "query": "AI",
                "documents": ["machine learning", "deep learning", "cooking"],
                "top_k": 2,
                "threshold": 0.0,
            },
            headers=None,
        )
        assert len(result["results"]) == 2

    def test_search_with_threshold(self, client: AragoraClient, mock_request) -> None:
        """Search with minimum threshold."""
        mock_request.return_value = {"results": []}

        client.index.search(
            query="test",
            documents=["a", "b"],
            threshold=0.8,
        )

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["json"]["threshold"] == 0.8

    def test_search_index(self, client: AragoraClient, mock_request) -> None:
        """Search a named index."""
        mock_request.return_value = {"results": [{"id": "doc_1", "score": 0.9}]}

        result = client.index.search_index(
            query="test query",
            index_name="my_index",
            top_k=5,
            filters={"category": "docs"},
        )

        mock_request.assert_called_once_with(
            "POST",
            "/api/v1/index/search",
            params=None,
            json={
                "query": "test query",
                "index_name": "my_index",
                "top_k": 5,
                "filters": {"category": "docs"},
            },
            headers=None,
        )
        assert result["results"][0]["id"] == "doc_1"


class TestIndexManagement:
    """Tests for index management operations."""

    def test_list_indexes(self, client: AragoraClient, mock_request) -> None:
        """List all indexes."""
        mock_request.return_value = {
            "indexes": [
                {"name": "docs", "dimension": 1536, "status": "ready"},
            ]
        }

        result = client.index.list_indexes()

        mock_request.assert_called_once_with(
            "GET", "/api/v1/index", params=None, json=None, headers=None
        )
        assert len(result["indexes"]) == 1

    def test_get_index(self, client: AragoraClient, mock_request) -> None:
        """Get index details."""
        mock_request.return_value = {
            "name": "docs",
            "dimension": 1536,
            "document_count": 1000,
            "status": "ready",
        }

        result = client.index.get_index("docs")

        mock_request.assert_called_once_with(
            "GET", "/api/v1/index/docs", params=None, json=None, headers=None
        )
        assert result["document_count"] == 1000

    def test_create_index(self, client: AragoraClient, mock_request) -> None:
        """Create a new index."""
        mock_request.return_value = {
            "name": "new_index",
            "dimension": 1536,
            "status": "building",
        }

        result = client.index.create_index(
            name="new_index",
            dimension=1536,
            metric="cosine",
            description="Test index",
        )

        mock_request.assert_called_once_with(
            "POST",
            "/api/v1/index",
            params=None,
            json={
                "name": "new_index",
                "metric": "cosine",
                "dimension": 1536,
                "description": "Test index",
            },
            headers=None,
        )
        assert result["status"] == "building"

    def test_delete_index(self, client: AragoraClient, mock_request) -> None:
        """Delete an index."""
        mock_request.return_value = {"deleted": True}

        result = client.index.delete_index("old_index")

        mock_request.assert_called_once_with(
            "DELETE", "/api/v1/index/old_index", params=None, json=None, headers=None
        )
        assert result["deleted"] is True


class TestAsyncIndex:
    """Tests for async index API."""

    @pytest.mark.asyncio
    async def test_async_embed(self, mock_async_request) -> None:
        """Embed asynchronously."""
        mock_async_request.return_value = {"embeddings": [[0.1]], "dimension": 1}

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.index.embed(text="test")

            assert result["dimension"] == 1

    @pytest.mark.asyncio
    async def test_async_search(self, mock_async_request) -> None:
        """Search asynchronously."""
        mock_async_request.return_value = {"results": [{"score": 0.9}]}

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.index.search(query="test", documents=["a"])

            assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_async_create_index(self, mock_async_request) -> None:
        """Create index asynchronously."""
        mock_async_request.return_value = {"name": "async_index", "status": "building"}

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.index.create_index(name="async_index")

            assert result["status"] == "building"
