"""Tests for Wikipedia connector."""

from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from aragora.connectors.wikipedia import WikipediaConnector
from aragora.connectors.base import Evidence
from aragora.reasoning.provenance import SourceType


# Sample Wikipedia API responses
SAMPLE_OPENSEARCH_RESPONSE = [
    "machine learning",
    ["Machine learning", "Machine learning in video games", "Machine learning control"],
    ["Machine learning is...", "Machine learning in games...", ""],
    [
        "https://en.wikipedia.org/wiki/Machine_learning",
        "https://en.wikipedia.org/wiki/Machine_learning_in_video_games",
        "https://en.wikipedia.org/wiki/Machine_learning_control",
    ],
]

SAMPLE_SUMMARY_RESPONSE = {
    "title": "Machine learning",
    "pageid": 233488,
    "extract": "Machine learning (ML) is a field of study in artificial intelligence concerned with the development and study of statistical algorithms that can learn from data.",
    "timestamp": "2024-01-15T10:30:00Z",
    "content_urls": {
        "desktop": {"page": "https://en.wikipedia.org/wiki/Machine_learning"},
    },
    "description": "Scientific study of algorithms",
}


class TestWikipediaConnector:
    """Tests for WikipediaConnector."""

    @pytest.fixture
    def connector(self):
        """Create a Wikipedia connector for testing."""
        return WikipediaConnector(rate_limit_delay=0.0)  # Disable rate limiting for tests

    def test_connector_properties(self, connector):
        """Test connector property methods."""
        assert connector.source_type == SourceType.DOCUMENT
        assert connector.name == "Wikipedia"
        assert connector.is_available  # Assumes httpx is installed

    def test_language_configuration(self):
        """Test language configuration."""
        connector = WikipediaConnector(language="fr")
        assert connector.language == "fr"
        assert "fr.wikipedia.org" in connector.api_url
        assert "fr.wikipedia.org" in connector.rest_url

    @pytest.mark.asyncio
    async def test_search_mocked(self, connector):
        """Test search with mocked HTTP response."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = SAMPLE_OPENSEARCH_RESPONSE
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_client_instance

            results = await connector.search("machine learning", limit=5, include_summary=False)

            assert len(results) == 3
            assert all(isinstance(r, Evidence) for r in results)
            assert results[0].title == "Machine learning"
            assert results[0].source_type == SourceType.DOCUMENT
            assert results[0].author == "Wikipedia contributors"

    @pytest.mark.asyncio
    async def test_fetch_mocked(self, connector):
        """Test fetch with mocked HTTP response."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = SAMPLE_SUMMARY_RESPONSE
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_client_instance

            result = await connector.fetch("Machine learning")

            assert result is not None
            assert result.title == "Machine learning"
            assert "artificial intelligence" in result.content
            assert result.metadata["page_id"] == 233488

    @pytest.mark.asyncio
    async def test_fetch_not_found(self, connector):
        """Test fetch returns None for non-existent article."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 404

            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_client_instance

            result = await connector.fetch("NonExistentArticle12345")

            assert result is None

    @pytest.mark.asyncio
    async def test_fetch_cached(self, connector):
        """Test that cached results are returned."""
        cached_evidence = Evidence(
            id="wiki:cached-123",
            source_type=SourceType.DOCUMENT,
            source_id="Cached Article",
            content="Cached article content",
            title="Cached Article",
        )
        connector._cache_put("cached-123", cached_evidence)

        result = await connector.fetch("cached-123")

        assert result is not None
        assert result.title == "Cached Article"

    def test_parse_summary_response(self, connector):
        """Test parsing of summary API response."""
        result = connector._parse_summary_response(SAMPLE_SUMMARY_RESPONSE)

        assert result is not None
        assert result.title == "Machine learning"
        assert "artificial intelligence" in result.content
        assert result.metadata["page_id"] == 233488
        assert result.metadata["description"] == "Scientific study of algorithms"

    def test_parse_summary_response_minimal(self, connector):
        """Test parsing with minimal response data."""
        minimal_response = {
            "title": "Test Article",
            "extract": "Test content",
        }

        result = connector._parse_summary_response(minimal_response)

        assert result is not None
        assert result.title == "Test Article"
        assert result.content == "Test content"

    @pytest.mark.asyncio
    async def test_get_article_sections_mocked(self, connector):
        """Test getting article sections."""
        sections_response = {
            "parse": {
                "sections": [
                    {"index": "1", "level": "2", "line": "History", "anchor": "History"},
                    {"index": "2", "level": "2", "line": "Approaches", "anchor": "Approaches"},
                ]
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = sections_response
            mock_response.raise_for_status = MagicMock()

            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_client_instance

            sections = await connector.get_article_sections("Machine learning")

            assert len(sections) == 2
            assert sections[0]["title"] == "History"
            assert sections[1]["title"] == "Approaches"

    @pytest.mark.asyncio
    async def test_get_related_articles_mocked(self, connector):
        """Test getting related articles."""
        links_response = {
            "query": {
                "pages": {
                    "233488": {
                        "links": [
                            {"title": "Artificial intelligence"},
                            {"title": "Deep learning"},
                            {"title": "Neural network"},
                        ]
                    }
                }
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = links_response
            mock_response.raise_for_status = MagicMock()

            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_client_instance

            related = await connector.get_related_articles("Machine learning")

            assert len(related) == 3
            assert "Artificial intelligence" in related
            assert "Deep learning" in related

    @pytest.mark.asyncio
    async def test_search_timeout_handling(self, connector):
        """Test handling of timeout errors."""
        import httpx

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_client_instance

            results = await connector.search("test query")

            assert results == []

    def test_evidence_authority(self, connector):
        """Test that Wikipedia evidence has appropriate authority score."""
        result = connector._parse_summary_response(SAMPLE_SUMMARY_RESPONSE)

        # Wikipedia is collaborative, so authority should be moderate
        assert result.authority == 0.7

    def test_evidence_freshness(self, connector):
        """Test freshness calculation for Wikipedia articles."""
        # Recent article
        recent_response = {
            "title": "Recent Topic",
            "extract": "Content",
            "timestamp": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
        }
        result = connector._parse_summary_response(recent_response)
        assert result.freshness > 0.5

        # Older article (no timestamp)
        old_response = {
            "title": "Old Topic",
            "extract": "Content",
        }
        result = connector._parse_summary_response(old_response)
        assert result.freshness == 0.8  # Default when no timestamp
