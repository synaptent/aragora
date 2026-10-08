"""
Tests for aragora.skills.builtin.web_search module.

Covers:
- SearchResult dataclass
- WebSearchSkill with various providers
- DuckDuckGo, Tavily, and Google search implementations
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.skills.base import SkillCapability, SkillContext, SkillStatus
from aragora.skills.builtin.web_search import SearchResult, WebSearchSkill


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def skill() -> WebSearchSkill:
    """Create a web search skill for testing."""
    return WebSearchSkill()


@pytest.fixture
def context() -> SkillContext:
    """Create a context for testing."""
    return SkillContext(user_id="user123")


# =============================================================================
# SearchResult Tests
# =============================================================================


class TestSearchResult:
    """Tests for SearchResult dataclass."""

    def test_create_search_result(self):
        """Test creating a search result."""
        result = SearchResult(
            title="Test Result",
            url="https://example.com",
            snippet="This is a test snippet",
        )

        assert result.title == "Test Result"
        assert result.url == "https://example.com"
        assert result.snippet == "This is a test snippet"

    def test_search_result_defaults(self):
        """Test search result default values."""
        result = SearchResult(
            title="Test",
            url="https://test.com",
            snippet="Test snippet",
        )

        assert result.source == "web"
        assert result.relevance_score == 0.0
        assert result.published_date is None

    def test_search_result_with_all_fields(self):
        """Test search result with all fields."""
        result = SearchResult(
            title="Full Result",
            url="https://example.com/full",
            snippet="Full snippet",
            source="custom_source",
            relevance_score=0.95,
            published_date="2024-01-15",
        )

        assert result.source == "custom_source"
        assert result.relevance_score == 0.95
        assert result.published_date == "2024-01-15"

    def test_to_dict(self):
        """Test converting search result to dict."""
        result = SearchResult(
            title="Dict Test",
            url="https://dict.com",
            snippet="Dict snippet",
            source="duckduckgo",
            relevance_score=0.8,
        )

        data = result.to_dict()

        assert data["title"] == "Dict Test"
        assert data["url"] == "https://dict.com"
        assert data["snippet"] == "Dict snippet"
        assert data["source"] == "duckduckgo"
        assert data["relevance_score"] == 0.8


# =============================================================================
# WebSearchSkill Manifest Tests
# =============================================================================


class TestWebSearchSkillManifest:
    """Tests for WebSearchSkill manifest."""

    def test_manifest_name(self, skill: WebSearchSkill):
        """Test manifest name."""
        assert skill.manifest.name == "web_search"

    def test_manifest_version(self, skill: WebSearchSkill):
        """Test manifest version."""
        assert skill.manifest.version == "1.0.0"

    def test_manifest_capabilities(self, skill: WebSearchSkill):
        """Test manifest capabilities."""
        caps = skill.manifest.capabilities
        assert SkillCapability.WEB_SEARCH in caps
        assert SkillCapability.EXTERNAL_API in caps

    def test_manifest_input_schema(self, skill: WebSearchSkill):
        """Test manifest input schema."""
        schema = skill.manifest.input_schema

        assert "query" in schema
        assert schema["query"]["type"] == "string"
        assert schema["query"]["required"] is True

        assert "max_results" in schema
        assert "provider" in schema
        assert "region" in schema
        assert "time_range" in schema

    def test_manifest_debate_compatible(self, skill: WebSearchSkill):
        """Test skill is debate compatible."""
        assert skill.manifest.debate_compatible is True

    def test_manifest_rate_limit(self, skill: WebSearchSkill):
        """Test manifest has rate limit."""
        assert skill.manifest.rate_limit_per_minute == 30

    def test_manifest_timeout(self, skill: WebSearchSkill):
        """Test manifest execution timeout."""
        assert skill.manifest.max_execution_time_seconds == 30.0


# =============================================================================
# WebSearchSkill Initialization Tests
# =============================================================================


class TestWebSearchSkillInit:
    """Tests for WebSearchSkill initialization."""

    def test_default_provider(self):
        """Test default provider is DuckDuckGo."""
        skill = WebSearchSkill()
        assert skill._default_provider == "duckduckgo"

    def test_custom_provider(self):
        """Test custom default provider."""
        skill = WebSearchSkill(default_provider="tavily")
        assert skill._default_provider == "tavily"

    def test_default_max_results(self):
        """Test default max results."""
        skill = WebSearchSkill()
        assert skill._max_results == 10

    def test_custom_max_results(self):
        """Test custom max results."""
        skill = WebSearchSkill(max_results=20)
        assert skill._max_results == 20


# =============================================================================
# WebSearchSkill Execution Tests
# =============================================================================


class TestWebSearchSkillExecution:
    """Tests for WebSearchSkill execution."""

    @pytest.mark.asyncio
    async def test_execute_missing_query(self, skill: WebSearchSkill, context: SkillContext):
        """Test execution fails without query."""
        result = await skill.execute({}, context)

        assert result.success is False
        assert "query" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_execute_empty_query(self, skill: WebSearchSkill, context: SkillContext):
        """Test execution fails with empty query."""
        result = await skill.execute({"query": ""}, context)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_success_structure(self, skill: WebSearchSkill, context: SkillContext):
        """Test successful execution returns correct structure."""
        mock_results = [
            SearchResult(
                title="Test 1",
                url="https://test1.com",
                snippet="Snippet 1",
            )
        ]

        with patch.object(skill, "_search_duckduckgo", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = mock_results

            result = await skill.execute({"query": "test"}, context)

        assert result.success is True
        assert "query" in result.data
        assert "provider" in result.data
        assert "results" in result.data
        assert "total_results" in result.data

    @pytest.mark.asyncio
    async def test_execute_with_max_results(self, skill: WebSearchSkill, context: SkillContext):
        """Test execution respects max_results parameter."""
        with patch.object(skill, "_search_duckduckgo", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []

            await skill.execute({"query": "test", "max_results": 5}, context)

            mock_search.assert_called_once()
            call_args = mock_search.call_args
            assert call_args[0][1] == 5  # max_results argument


# =============================================================================
# DuckDuckGo Provider Tests
# =============================================================================


class TestDuckDuckGoProvider:
    """Tests for DuckDuckGo search provider."""

    @pytest.fixture(autouse=True)
    def check_ddg_available(self):
        """Check if duckduckgo_search is available."""
        try:
            from duckduckgo_search import DDGS

            self._ddg_available = True
        except ImportError:
            self._ddg_available = False

    @pytest.mark.asyncio
    async def test_duckduckgo_returns_list(self, skill: WebSearchSkill):
        """Test DuckDuckGo always returns a list."""
        # Should always return a list (empty if not installed or error)
        results = await skill._search_duckduckgo("test", 10, None, None)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_duckduckgo_success(self, skill: WebSearchSkill):
        """Test successful DuckDuckGo search with mock."""
        pytest.importorskip("duckduckgo_search")

        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text = MagicMock(
            return_value=[
                {"title": "Result 1", "href": "https://r1.com", "body": "Body 1"},
                {"title": "Result 2", "href": "https://r2.com", "body": "Body 2"},
            ]
        )

        with patch(
            "duckduckgo_search.DDGS",
            return_value=mock_ddgs,
        ):
            results = await skill._search_duckduckgo("test query", 10, None, None)

        assert len(results) == 2
        assert results[0].title == "Result 1"
        assert results[0].url == "https://r1.com"
        assert results[0].source == "duckduckgo"

    @pytest.mark.asyncio
    async def test_duckduckgo_with_region(self, skill: WebSearchSkill):
        """Test DuckDuckGo search with region."""
        pytest.importorskip("duckduckgo_search")

        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text = MagicMock(return_value=[])

        with patch(
            "duckduckgo_search.DDGS",
            return_value=mock_ddgs,
        ):
            await skill._search_duckduckgo("test", 10, "us-en", None)

            mock_ddgs.text.assert_called_once()
            call_kwargs = mock_ddgs.text.call_args[1]
            assert call_kwargs.get("region") == "us-en"

    @pytest.mark.asyncio
    async def test_duckduckgo_with_time_range(self, skill: WebSearchSkill):
        """Test DuckDuckGo search with time range."""
        pytest.importorskip("duckduckgo_search")

        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text = MagicMock(return_value=[])

        with patch(
            "duckduckgo_search.DDGS",
            return_value=mock_ddgs,
        ):
            await skill._search_duckduckgo("test", 10, None, "week")

            mock_ddgs.text.assert_called_once()
            call_kwargs = mock_ddgs.text.call_args[1]
            assert call_kwargs.get("timelimit") == "w"

    @pytest.mark.asyncio
    async def test_duckduckgo_exception_handling(self, skill: WebSearchSkill):
        """Test DuckDuckGo exception handling."""
        pytest.importorskip("duckduckgo_search")

        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text = MagicMock(side_effect=RuntimeError("API error"))

        with patch(
            "duckduckgo_search.DDGS",
            return_value=mock_ddgs,
        ):
            results = await skill._search_duckduckgo("test", 10, None, None)

        # Should return empty list on error
        assert results == []


# =============================================================================
# Tavily Provider Tests
# =============================================================================


class TestTavilyProvider:
    """Tests for Tavily search provider."""

    @pytest.mark.asyncio
    async def test_tavily_no_api_key(self, skill: WebSearchSkill):
        """Test Tavily falls back to DuckDuckGo without API key."""
        with patch.dict("os.environ", {}, clear=True):
            with patch.object(skill, "_search_duckduckgo", new_callable=AsyncMock) as mock_ddg:
                mock_ddg.return_value = []

                await skill._search_tavily("test", 10)

                mock_ddg.assert_called_once()

    @pytest.mark.asyncio
    async def test_tavily_success(self, skill: WebSearchSkill):
        """Test successful Tavily search."""
        mock_response = MagicMock()
        mock_response.json = MagicMock(
            return_value={
                "results": [
                    {
                        "title": "Tavily Result",
                        "url": "https://tavily.com/result",
                        "content": "Tavily content",
                        "score": 0.9,
                    }
                ]
            }
        )
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_pool = MagicMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.get_session = MagicMock(return_value=mock_session_cm)

        with patch.dict("os.environ", {"TAVILY_API_KEY": "test_key"}):
            with patch(
                "aragora.observability.http_client_pool.get_http_pool",
                return_value=mock_pool,
            ):
                results = await skill._search_tavily("test", 10)

        assert len(results) == 1
        assert results[0].title == "Tavily Result"
        assert results[0].source == "tavily"
        assert results[0].relevance_score == 0.9

    @pytest.mark.asyncio
    async def test_tavily_api_error_fallback(self, skill: WebSearchSkill):
        """Test Tavily falls back to DuckDuckGo on API error."""
        mock_pool = MagicMock()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=RuntimeError("API error"))
        mock_client.aclose = AsyncMock()
        mock_pool.get_session = MagicMock()
        mock_pool.get_session.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_pool.get_session.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.dict("os.environ", {"TAVILY_API_KEY": "test_key"}):
            with patch(
                "aragora.observability.http_client_pool.get_http_pool",
                return_value=mock_pool,
            ):
                with patch.object(skill, "_search_duckduckgo", new_callable=AsyncMock) as mock_ddg:
                    mock_ddg.return_value = []

                    await skill._search_tavily("test", 10)

                    mock_ddg.assert_called_once()


# =============================================================================
# Google Provider Tests
# =============================================================================


class TestGoogleProvider:
    """Tests for Google Custom Search provider."""

    @pytest.mark.asyncio
    async def test_google_no_api_key(self, skill: WebSearchSkill):
        """Test Google falls back to DuckDuckGo without API key."""
        with patch.dict("os.environ", {}, clear=True):
            with patch.object(skill, "_search_duckduckgo", new_callable=AsyncMock) as mock_ddg:
                mock_ddg.return_value = []

                await skill._search_google("test", 10)

                mock_ddg.assert_called_once()

    @pytest.mark.asyncio
    async def test_google_no_cx(self, skill: WebSearchSkill):
        """Test Google falls back without CX (Custom Search Engine ID)."""
        with patch.dict("os.environ", {"GOOGLE_SEARCH_API_KEY": "key"}, clear=True):
            with patch.object(skill, "_search_duckduckgo", new_callable=AsyncMock) as mock_ddg:
                mock_ddg.return_value = []

                await skill._search_google("test", 10)

                mock_ddg.assert_called_once()

    @pytest.mark.asyncio
    async def test_google_success(self, skill: WebSearchSkill):
        """Test successful Google search."""
        mock_response = MagicMock()
        mock_response.json = MagicMock(
            return_value={
                "items": [
                    {
                        "title": "Google Result",
                        "link": "https://google.com/result",
                        "snippet": "Google snippet",
                    }
                ]
            }
        )
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        mock_pool = MagicMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.get_session = MagicMock(return_value=mock_session_cm)

        with patch.dict(
            "os.environ",
            {
                "GOOGLE_SEARCH_API_KEY": "test_key",
                "GOOGLE_SEARCH_CX": "test_cx",
            },
        ):
            with patch(
                "aragora.observability.http_client_pool.get_http_pool",
                return_value=mock_pool,
            ):
                results = await skill._search_google("test", 10)

        assert len(results) == 1
        assert results[0].title == "Google Result"
        assert results[0].url == "https://google.com/result"
        assert results[0].source == "google"

    @pytest.mark.asyncio
    async def test_google_max_results_limit(self, skill: WebSearchSkill):
        """Test Google limits max_results to 10."""
        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value={"items": []})
        mock_response.raise_for_status = MagicMock()

        mock_get = AsyncMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.get = mock_get

        mock_pool = MagicMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.get_session = MagicMock(return_value=mock_session_cm)

        with patch.dict(
            "os.environ",
            {
                "GOOGLE_SEARCH_API_KEY": "test_key",
                "GOOGLE_SEARCH_CX": "test_cx",
            },
        ):
            with patch(
                "aragora.observability.http_client_pool.get_http_pool",
                return_value=mock_pool,
            ):
                await skill._search_google("test", 20)

                # Check that num param is capped at 10
                call_kwargs = mock_get.call_args[1]
                assert call_kwargs["params"]["num"] == 10

    @pytest.mark.asyncio
    async def test_google_api_error_fallback(self, skill: WebSearchSkill):
        """Test Google falls back to DuckDuckGo on API error."""
        mock_pool = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("API error"))
        mock_client.aclose = AsyncMock()
        mock_pool.get_session = MagicMock()
        mock_pool.get_session.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_pool.get_session.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.dict(
            "os.environ",
            {
                "GOOGLE_SEARCH_API_KEY": "test_key",
                "GOOGLE_SEARCH_CX": "test_cx",
            },
        ):
            with patch(
                "aragora.observability.http_client_pool.get_http_pool",
                return_value=mock_pool,
            ):
                with patch.object(skill, "_search_duckduckgo", new_callable=AsyncMock) as mock_ddg:
                    mock_ddg.return_value = []

                    await skill._search_google("test", 10)

                    mock_ddg.assert_called_once()


# =============================================================================
# Provider Selection Tests
# =============================================================================


class TestProviderSelection:
    """Tests for provider selection logic."""

    @pytest.mark.asyncio
    async def test_default_provider_used(self, skill: WebSearchSkill, context: SkillContext):
        """Test default provider is used when not specified."""
        with patch.object(skill, "_search_duckduckgo", new_callable=AsyncMock) as mock_ddg:
            mock_ddg.return_value = []

            await skill.execute({"query": "test"}, context)

            mock_ddg.assert_called_once()

    @pytest.mark.asyncio
    async def test_tavily_provider_selected(self, skill: WebSearchSkill, context: SkillContext):
        """Test Tavily provider is used when specified."""
        with patch.object(skill, "_search_tavily", new_callable=AsyncMock) as mock_tavily:
            mock_tavily.return_value = []

            await skill.execute({"query": "test", "provider": "tavily"}, context)

            mock_tavily.assert_called_once()

    @pytest.mark.asyncio
    async def test_google_provider_selected(self, skill: WebSearchSkill, context: SkillContext):
        """Test Google provider is used when specified."""
        with patch.object(skill, "_search_google", new_callable=AsyncMock) as mock_google:
            mock_google.return_value = []

            await skill.execute({"query": "test", "provider": "google"}, context)

            mock_google.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_provider_fallback(self, skill: WebSearchSkill, context: SkillContext):
        """Test unknown provider falls back to DuckDuckGo."""
        with patch.object(skill, "_search_duckduckgo", new_callable=AsyncMock) as mock_ddg:
            mock_ddg.return_value = []

            await skill.execute({"query": "test", "provider": "unknown"}, context)

            mock_ddg.assert_called_once()


# =============================================================================
# SKILLS Registration Tests
# =============================================================================


class TestSkillsRegistration:
    """Tests for SKILLS module-level list."""

    def test_skills_list_exists(self):
        """Test SKILLS list exists in module."""
        from aragora.skills.builtin import web_search

        assert hasattr(web_search, "SKILLS")

    def test_skills_list_contains_skill(self):
        """Test SKILLS list contains WebSearchSkill."""
        from aragora.skills.builtin.web_search import SKILLS

        assert len(SKILLS) == 1
        assert isinstance(SKILLS[0], WebSearchSkill)
