"""Tests for MCP evidence tools execution logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.mcp.tools_module.evidence import (
    cite_evidence_tool,
    search_evidence_tool,
    verify_citation_tool,
)


class TestSearchEvidenceTool:
    """Tests for search_evidence_tool."""

    @pytest.mark.asyncio
    async def test_search_empty_query(self):
        """Test search with empty query."""
        result = await search_evidence_tool(query="")
        assert "error" in result
        assert "required" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_search_success(self):
        """Test successful evidence search."""
        mock_snippet = MagicMock()
        mock_snippet.id = "ev-123"
        mock_snippet.title = "Test Evidence"
        mock_snippet.source = "arxiv"
        mock_snippet.url = "https://arxiv.org/abs/123"
        mock_snippet.snippet = "This is test evidence content"
        mock_snippet.reliability_score = 0.85
        mock_snippet.fetched_at = None

        mock_evidence_pack = MagicMock()
        mock_evidence_pack.snippets = [mock_snippet]

        mock_collector = AsyncMock()
        mock_collector.collect_evidence.return_value = mock_evidence_pack

        with patch(
            "aragora.evidence.collector.EvidenceCollector",
            return_value=mock_collector,
        ):
            result = await search_evidence_tool(query="test query")

        assert result["query"] == "test query"
        assert result["count"] == 1
        assert len(result["results"]) == 1
        assert result["results"][0]["id"] == "ev-123"
        assert result["results"][0]["title"] == "Test Evidence"
        assert result["results"][0]["score"] == 0.85

    @pytest.mark.asyncio
    async def test_search_with_sources_filter(self):
        """Test search with specific sources."""
        mock_evidence_pack = MagicMock()
        mock_evidence_pack.snippets = []

        mock_collector = AsyncMock()
        mock_collector.collect_evidence.return_value = mock_evidence_pack

        with patch(
            "aragora.evidence.collector.EvidenceCollector",
            return_value=mock_collector,
        ):
            result = await search_evidence_tool(query="test", sources="arxiv,reddit")

        assert result["sources"] == "arxiv,reddit"
        mock_collector.collect_evidence.assert_called_once()
        call_kwargs = mock_collector.collect_evidence.call_args.kwargs
        assert call_kwargs["enabled_connectors"] == ["arxiv", "reddit"]

    @pytest.mark.asyncio
    async def test_search_limit_clamped(self):
        """Test that limit is clamped to valid range."""
        mock_evidence_pack = MagicMock()
        mock_evidence_pack.snippets = []

        mock_collector = AsyncMock()
        mock_collector.collect_evidence.return_value = mock_evidence_pack

        with patch(
            "aragora.evidence.collector.EvidenceCollector",
            return_value=mock_collector,
        ):
            # Test limit below minimum
            result = await search_evidence_tool(query="test", limit=0)
            assert result["count"] == 0

            # Test limit above maximum
            result = await search_evidence_tool(query="test", limit=100)
            assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_search_import_error(self):
        """Test graceful handling when EvidenceCollector not available."""
        with patch(
            "aragora.evidence.collector.EvidenceCollector",
            side_effect=ImportError("Not installed"),
        ):
            result = await search_evidence_tool(query="test query")

        assert result["query"] == "test query"
        assert result["count"] == 0
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_search_exception_handling(self):
        """Test graceful exception handling."""
        mock_collector = AsyncMock()
        mock_collector.collect_evidence.side_effect = RuntimeError("API error")

        with patch(
            "aragora.evidence.collector.EvidenceCollector",
            return_value=mock_collector,
        ):
            result = await search_evidence_tool(query="test query")

        assert result["query"] == "test query"
        assert result["count"] == 0


class TestCiteEvidenceTool:
    """Tests for cite_evidence_tool."""

    @pytest.mark.asyncio
    async def test_cite_missing_debate_id(self):
        """Test citation with missing debate_id."""
        result = await cite_evidence_tool(
            debate_id="",
            evidence_id="ev-123",
            message_index=0,
        )
        assert "error" in result
        assert "required" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_cite_missing_evidence_id(self):
        """Test citation with missing evidence_id."""
        result = await cite_evidence_tool(
            debate_id="debate-123",
            evidence_id="",
            message_index=0,
        )
        assert "error" in result
        assert "required" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_cite_success(self):
        """Test successful citation."""
        mock_debate = {"citations": []}
        mock_db = MagicMock()
        mock_db.get.return_value = mock_debate
        mock_db.update = MagicMock()

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await cite_evidence_tool(
                debate_id="debate-123",
                evidence_id="ev-456",
                message_index=2,
                citation_text="As stated in the paper...",
            )

        assert result["success"] is True
        assert result["debate_id"] == "debate-123"
        assert result["evidence_id"] == "ev-456"
        assert result["citation_count"] == 1
        mock_db.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_cite_storage_not_available(self):
        """Test citation when storage not available."""
        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=None,
        ):
            result = await cite_evidence_tool(
                debate_id="debate-123",
                evidence_id="ev-456",
                message_index=0,
            )

        assert "error" in result
        assert "not available" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_cite_debate_not_found(self):
        """Test citation when debate not found."""
        mock_db = MagicMock()
        mock_db.get.return_value = None

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await cite_evidence_tool(
                debate_id="nonexistent",
                evidence_id="ev-456",
                message_index=0,
            )

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_cite_appends_to_existing_citations(self):
        """Test that citation appends to existing citations."""
        existing_citations = [{"evidence_id": "old", "message_index": 0}]
        mock_debate = {"citations": existing_citations}
        mock_db = MagicMock()
        mock_db.get.return_value = mock_debate
        mock_db.update = MagicMock()

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await cite_evidence_tool(
                debate_id="debate-123",
                evidence_id="ev-new",
                message_index=1,
            )

        assert result["citation_count"] == 2


class TestVerifyCitationTool:
    """Tests for verify_citation_tool."""

    @pytest.mark.asyncio
    async def test_verify_empty_url(self):
        """Test verification with empty URL."""
        result = await verify_citation_tool(url="")
        assert "error" in result
        assert "required" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_verify_url_accessible(self):
        """Test verification of accessible URL."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html"}

        mock_client = AsyncMock()
        mock_client.head.return_value = mock_response

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_pool = MagicMock()
        mock_pool.get_session.return_value = mock_session_ctx

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            result = await verify_citation_tool(url="https://example.com/paper")

        assert result["valid"] is True
        assert result["status_code"] == 200
        assert result["accessible"] is True

    @pytest.mark.asyncio
    async def test_verify_url_not_found(self):
        """Test verification of URL returning 404."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.head.return_value = mock_response

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_pool = MagicMock()
        mock_pool.get_session.return_value = mock_session_ctx

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            result = await verify_citation_tool(url="https://example.com/missing")

        assert result["valid"] is False
        assert result["status_code"] == 404
        assert result["accessible"] is False

    @pytest.mark.asyncio
    async def test_verify_url_timeout(self):
        """Test verification timeout handling."""
        import asyncio

        mock_client = AsyncMock()
        mock_client.head.side_effect = asyncio.TimeoutError()

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_pool = MagicMock()
        mock_pool.get_session.return_value = mock_session_ctx

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            result = await verify_citation_tool(url="https://slow.example.com")

        assert result["valid"] is False
        assert result["error"] == "Timeout"

    @pytest.mark.asyncio
    async def test_verify_url_exception(self):
        """Test verification exception handling."""
        mock_client = AsyncMock()
        mock_client.head.side_effect = ConnectionError("Network error")

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_pool = MagicMock()
        mock_pool.get_session.return_value = mock_session_ctx

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            result = await verify_citation_tool(url="https://broken.example.com")

        assert result["valid"] is False
        assert "error" in result
