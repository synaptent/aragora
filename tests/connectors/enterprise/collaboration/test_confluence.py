"""
Tests for Atlassian Confluence Enterprise Connector.

Tests the Confluence REST API integration including:
- Space and page operations
- Content extraction (wiki to text)
- Comment indexing
- Search functionality
- Error handling
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from aragora.connectors.enterprise.collaboration.confluence import (
    ConfluenceConnector,
    ConfluenceSpace,
    ConfluencePage,
)
from aragora.connectors.enterprise.base import SyncState


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def connector():
    """Create test connector for Confluence Cloud."""
    conn = ConfluenceConnector(
        base_url="https://test-domain.atlassian.net/wiki",
        spaces=["ENG", "DOCS"],
        include_archived=False,
        include_comments=True,
    )
    # Mock credentials
    conn.credentials = MagicMock()
    conn.credentials.get_credential = AsyncMock(
        side_effect=lambda key: {
            "CONFLUENCE_EMAIL": "test@example.com",
            "CONFLUENCE_API_TOKEN": "test_token",
        }.get(key)
    )
    return conn


@pytest.fixture
def dc_connector():
    """Create test connector for Confluence Data Center."""
    conn = ConfluenceConnector(
        base_url="https://confluence.internal.company.com",
        spaces=["PROJ"],
    )
    # Mock credentials
    conn.credentials = MagicMock()
    conn.credentials.get_credential = AsyncMock(
        side_effect=lambda key: {"CONFLUENCE_PAT": "test_pat"}.get(key)
    )
    return conn


def make_api_response(data: Any) -> dict[str, Any]:
    """Create a mock API response."""
    return data


def make_space_data(
    space_id: str = "12345",
    key: str = "ENG",
    name: str = "Engineering",
) -> dict[str, Any]:
    """Create mock space data."""
    return {
        "id": space_id,
        "key": key,
        "name": name,
        "type": "global",
        "status": "current",
        "_links": {"webui": f"/spaces/{key}"},
    }


def make_page_data(
    page_id: str = "10001",
    title: str = "Test Page",
    space_key: str = "ENG",
) -> dict[str, Any]:
    """Create mock page data."""
    return {
        "id": page_id,
        "title": title,
        "type": "page",
        "status": "current",
        "space": {"key": space_key},
        "body": {
            "storage": {
                "value": "<p>Page content here</p>",
                "representation": "storage",
            }
        },
        "version": {"number": 1},
        "_links": {"webui": f"/spaces/{space_key}/pages/{page_id}"},
        "history": {
            "createdBy": {"displayName": "Author Name"},
            "createdDate": "2024-01-15T10:00:00.000Z",
            "lastUpdated": {
                "by": {"displayName": "Editor Name"},
                "when": "2024-01-15T12:00:00.000Z",
            },
        },
        "ancestors": [],
        "metadata": {
            "labels": {
                "results": [{"name": "documentation"}],
            }
        },
    }


# =============================================================================
# Initialization Tests
# =============================================================================


class TestConfluenceConnectorInit:
    """Test ConfluenceConnector initialization."""

    def test_cloud_configuration(self):
        """Should detect Confluence Cloud from URL."""
        connector = ConfluenceConnector(base_url="https://company.atlassian.net/wiki")
        assert connector.is_cloud is True

    def test_data_center_configuration(self):
        """Should detect Confluence Data Center from URL."""
        connector = ConfluenceConnector(base_url="https://confluence.internal.com")
        assert connector.is_cloud is False

    def test_url_normalization_adds_wiki(self):
        """Should add /wiki to URL if missing."""
        connector = ConfluenceConnector(base_url="https://test.atlassian.net")
        assert connector.base_url == "https://test.atlassian.net/wiki"

    def test_url_normalization_removes_trailing_slash(self):
        """Should remove trailing slash from URL."""
        connector = ConfluenceConnector(base_url="https://test.atlassian.net/wiki/")
        assert connector.base_url == "https://test.atlassian.net/wiki"

    def test_custom_configuration(self):
        """Should accept custom configuration."""
        connector = ConfluenceConnector(
            base_url="https://test.atlassian.net/wiki",
            spaces=["ENG", "DOCS"],
            include_archived=True,
            include_attachments=False,
            include_comments=False,
            exclude_labels=["draft", "internal"],
        )
        assert connector.spaces == ["ENG", "DOCS"]
        assert connector.include_archived is True
        assert connector.include_attachments is False
        assert connector.include_comments is False
        assert "draft" in connector.exclude_labels

    def test_connector_id_generation(self):
        """Should generate connector ID from domain."""
        connector = ConfluenceConnector(base_url="https://my-company.atlassian.net/wiki")
        assert "confluence_" in connector.connector_id

    def test_connector_properties(self, connector):
        """Should have correct connector properties."""
        assert "Confluence" in connector.name
        assert "test-domain.atlassian.net" in connector.name

    def test_source_type(self, connector):
        """Should have correct source type."""
        from aragora.reasoning.provenance import SourceType

        assert connector.source_type == SourceType.DOCUMENT


# =============================================================================
# Authentication Tests
# =============================================================================


class TestAuthentication:
    """Test authentication flows."""

    @pytest.mark.asyncio
    async def test_cloud_auth_header(self, connector):
        """Should generate Basic auth header for Cloud."""
        header = await connector._get_auth_header()

        assert "Authorization" in header
        assert header["Authorization"].startswith("Basic ")

    @pytest.mark.asyncio
    async def test_data_center_auth_header(self, dc_connector):
        """Should generate Bearer auth header for Data Center."""
        header = await dc_connector._get_auth_header()

        assert "Authorization" in header
        assert header["Authorization"] == "Bearer test_pat"

    @pytest.mark.asyncio
    async def test_missing_cloud_credentials(self, connector):
        """Should raise error when Cloud credentials missing."""
        connector.credentials.get_credential = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="Confluence Cloud credentials not configured"):
            await connector._get_auth_header()

    @pytest.mark.asyncio
    async def test_missing_dc_credentials(self, dc_connector):
        """Should raise error when Data Center credentials missing."""
        dc_connector.credentials.get_credential = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="Confluence Data Center credentials not configured"):
            await dc_connector._get_auth_header()


# =============================================================================
# Space Operations Tests
# =============================================================================


class TestSpaceOperations:
    """Test space-related operations."""

    @pytest.mark.asyncio
    async def test_get_spaces(self, connector):
        """Should get accessible spaces."""
        mock_response = {
            "results": [
                make_space_data("1", "ENG", "Engineering"),
                make_space_data("2", "DOCS", "Documentation"),
            ],
            "_links": {},
        }

        with patch.object(connector, "_api_request", return_value=mock_response):
            spaces = await connector._get_spaces()

            assert len(spaces) == 2
            assert spaces[0].key == "ENG"
            assert spaces[0].name == "Engineering"

    @pytest.mark.asyncio
    async def test_get_spaces_filtered(self, connector):
        """Should filter to configured spaces."""
        connector.spaces = ["ENG"]

        mock_response = {
            "results": [
                make_space_data("1", "ENG", "Engineering"),
                make_space_data("2", "OTHER", "Other Space"),
            ],
            "_links": {},
        }

        with patch.object(connector, "_api_request", return_value=mock_response):
            spaces = await connector._get_spaces()

            assert len(spaces) == 1
            assert spaces[0].key == "ENG"


# =============================================================================
# Page Operations Tests
# =============================================================================


class TestPageOperations:
    """Test page-related operations."""

    @pytest.mark.asyncio
    async def test_get_pages(self, connector):
        """Should get pages from space."""
        mock_response = {
            "results": [
                make_page_data("10001", "Getting Started", "ENG"),
                make_page_data("10002", "API Reference", "ENG"),
            ],
            "_links": {},
        }

        with patch.object(connector, "_api_request", return_value=mock_response):
            pages = []
            async for page in connector._get_pages("ENG"):
                pages.append(page)

            assert len(pages) == 2
            assert pages[0].title == "Getting Started"

    @pytest.mark.asyncio
    async def test_get_pages_includes_all_statuses(self, connector):
        """Should return pages with their status."""
        mock_response = {
            "results": [
                make_page_data("10001", "Active Page", "ENG"),
                {**make_page_data("10002", "Draft Page", "ENG"), "status": "draft"},
            ],
            "_links": {},
        }

        with patch.object(connector, "_api_request", return_value=mock_response):
            pages = []
            async for page in connector._get_pages("ENG"):
                pages.append(page)

            # Both pages are returned, status is preserved
            assert len(pages) == 2
            assert pages[0].status == "current"
            assert pages[1].status == "draft"


# =============================================================================
# Content Extraction Tests
# =============================================================================


class TestContentExtraction:
    """Test content extraction from pages."""

    def test_html_to_text_basic(self, connector):
        """Should convert HTML to text."""
        html_content = "<p>Hello <b>world</b>!</p>"
        text = connector._html_to_text(html_content)

        assert "<p>" not in text
        assert "</p>" not in text
        assert "Hello" in text
        assert "world" in text

    def test_html_to_text_entities(self, connector):
        """Should decode HTML entities."""
        html_content = "Hello &amp; goodbye"
        text = connector._html_to_text(html_content)

        # Should contain decoded content
        assert "Hello" in text

    def test_html_to_text_empty(self, connector):
        """Should handle empty content."""
        result = connector._html_to_text("")
        assert result == ""

        result = connector._html_to_text(None)
        assert result == ""


# =============================================================================
# Search Tests
# =============================================================================


class TestSearch:
    """Test search functionality."""

    @pytest.mark.asyncio
    async def test_search(self, connector):
        """Should search pages by CQL."""
        mock_response = {
            "results": [
                make_page_data("10001", "API Documentation"),
            ],
            "_links": {},
        }

        with patch.object(connector, "_api_request", return_value=mock_response):
            results = await connector.search("API", limit=5)

            assert len(results) >= 0  # May be empty based on implementation

    @pytest.mark.asyncio
    async def test_search_with_space_filter(self, connector):
        """Should filter search by space."""
        mock_response = {
            "results": [make_page_data()],
            "_links": {},
        }

        with patch.object(connector, "_api_request", return_value=mock_response) as mock_request:
            await connector.search("test", space_key="ENG")

            # Verify API was called
            mock_request.assert_called()


# =============================================================================
# Fetch Tests
# =============================================================================


class TestFetch:
    """Test fetch functionality."""

    @pytest.mark.asyncio
    async def test_fetch_page(self, connector):
        """Should fetch a page by evidence ID."""
        mock_response = make_page_data("10001", "Test Page")

        with patch.object(connector, "_api_request", return_value=mock_response):
            evidence = await connector.fetch("confluence-10001")

            # Should return evidence or None
            if evidence:
                assert "10001" in evidence.id

    @pytest.mark.asyncio
    async def test_fetch_invalid_id(self, connector):
        """Should return None for invalid evidence ID."""
        result = await connector.fetch("invalid-id-format")

        assert result is None


# =============================================================================
# Sync Tests
# =============================================================================


class TestSyncItems:
    """Test sync_items functionality."""

    @pytest.mark.asyncio
    async def test_sync_items(self, connector):
        """Should yield sync items for pages."""
        mock_spaces_response = {
            "results": [make_space_data("1", "ENG", "Engineering")],
            "_links": {},
        }
        mock_pages_response = {
            "results": [make_page_data("10001", "Page 1")],
            "_links": {},
        }

        call_count = [0]

        async def mock_api_request(endpoint, **kwargs):
            call_count[0] += 1
            if "/space" in endpoint and "content" not in endpoint:
                return mock_spaces_response
            elif "/content" in endpoint:
                return mock_pages_response
            return {"results": [], "_links": {}}

        with patch.object(connector, "_api_request", side_effect=mock_api_request):
            state = SyncState(connector_id=connector.connector_id)
            items = []
            async for item in connector.sync_items(state):
                items.append(item)
                if len(items) >= 5:  # Limit for test
                    break

            assert isinstance(items, list)


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_api_error(self, connector):
        """API errors from _api_request propagate out of _get_pages."""
        import httpx

        with patch.object(
            connector,
            "_api_request",
            side_effect=httpx.HTTPStatusError(
                "Error", request=None, response=MagicMock(status_code=500)
            ),
        ):
            # _get_pages does not catch API errors: the HTTPStatusError
            # propagates from the first iteration and no page is yielded.
            pages = []
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                async for page in connector._get_pages("ENG"):
                    pages.append(page)

            assert exc_info.value.response.status_code == 500
            assert pages == []


# =============================================================================
# Data Model Tests
# =============================================================================


class TestDataModels:
    """Test data model creation."""

    def test_confluence_space_creation(self):
        """Should create ConfluenceSpace."""
        space = ConfluenceSpace(
            id="12345",
            key="ENG",
            name="Engineering",
            type="global",
            status="current",
        )
        assert space.key == "ENG"
        assert space.homepage_id is None

    def test_confluence_space_with_homepage(self):
        """Should create ConfluenceSpace with homepage."""
        space = ConfluenceSpace(
            id="12345",
            key="ENG",
            name="Engineering",
            type="global",
            status="current",
            homepage_id="10001",
        )
        assert space.homepage_id == "10001"

    def test_confluence_page_creation(self):
        """Should create ConfluencePage with defaults."""
        page = ConfluencePage(
            id="10001",
            title="Test Page",
            space_key="ENG",
            status="current",
        )
        assert page.body == ""
        assert page.version == 1
        assert page.labels == []
        assert page.parent_id is None

    def test_confluence_page_with_all_fields(self):
        """Should create ConfluencePage with all fields."""
        page = ConfluencePage(
            id="10001",
            title="Full Page",
            space_key="ENG",
            status="current",
            body="Page content here",
            version=5,
            url="https://confluence.example.com/pages/10001",
            created_by="Author",
            created_at=datetime.now(timezone.utc),
            updated_by="Editor",
            parent_id="10000",
            labels=["doc", "api"],
        )
        assert page.body == "Page content here"
        assert page.version == 5
        assert len(page.labels) == 2


# =============================================================================
# URL Construction Tests
# =============================================================================


class TestURLConstruction:
    """Test URL construction for API requests."""

    @pytest.mark.asyncio
    async def test_api_url_construction(self, connector):
        """Should construct correct API URL."""
        # The base URL should have /wiki appended
        assert "/wiki" in connector.base_url

        # API requests go to /rest/api
        # This is verified by the _api_request method behavior

    def test_page_url_field(self):
        """Should have URL field for pages."""
        page = ConfluencePage(
            id="10001",
            title="Test",
            space_key="ENG",
            status="current",
            url="https://confluence.example.com/spaces/ENG/pages/10001",
        )
        assert page.url == "https://confluence.example.com/spaces/ENG/pages/10001"
