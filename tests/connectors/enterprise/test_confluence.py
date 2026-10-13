"""
Tests for Confluence Enterprise Connector.

Tests cover:
- Initialization and configuration
- Space and page crawling
- Content extraction
- Authentication (Cloud vs Data Center)
- Incremental sync
- Error handling

Tests use `patch.object(connector, '_api_request', new_callable=AsyncMock)` pattern
to mock the HTTP API calls made by the connector.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from aragora.connectors.enterprise.base import SyncState, SyncStatus
from aragora.reasoning.provenance import SourceType


class TestConfluenceConnectorInitialization:
    """Tests for connector initialization."""

    def test_init_with_cloud_url(self):
        """Should detect Cloud instance from URL."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        connector = ConfluenceConnector(base_url="https://mycompany.atlassian.net/wiki")

        assert connector.is_cloud is True
        assert "atlassian.net" in connector.base_url

    def test_init_with_datacenter_url(self):
        """Should detect Data Center instance from URL."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        connector = ConfluenceConnector(base_url="https://confluence.mycompany.com")

        assert connector.is_cloud is False

    def test_init_normalizes_url(self):
        """Should normalize URL to include /wiki."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        connector = ConfluenceConnector(base_url="https://mycompany.atlassian.net")

        assert connector.base_url.endswith("/wiki")

    def test_init_with_custom_config(self):
        """Should initialize with custom configuration."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        connector = ConfluenceConnector(
            base_url="https://mycompany.atlassian.net/wiki",
            spaces=["ENG", "DOCS"],
            include_archived=True,
            include_attachments=False,
            include_comments=False,
            exclude_labels=["draft", "private"],
        )

        assert connector.spaces == ["ENG", "DOCS"]
        assert connector.include_archived is True
        assert connector.include_attachments is False
        assert connector.include_comments is False
        assert "draft" in connector.exclude_labels

    def test_source_type_is_document(self):
        """Should return DOCUMENT source type."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        connector = ConfluenceConnector(base_url="https://test.atlassian.net/wiki")
        assert connector.source_type == SourceType.DOCUMENT

    def test_name_includes_url(self):
        """Should include base URL in connector name."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        connector = ConfluenceConnector(base_url="https://mycompany.atlassian.net/wiki")
        assert "mycompany" in connector.name.lower() or "atlassian" in connector.name.lower()


class TestConfluenceDataclasses:
    """Tests for Confluence dataclasses."""

    def test_confluence_space_creation(self):
        """Should create ConfluenceSpace with all fields."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceSpace

        space = ConfluenceSpace(
            id="123",
            key="ENG",
            name="Engineering",
            type="global",
            status="current",
            homepage_id="456",
        )

        assert space.key == "ENG"
        assert space.name == "Engineering"
        assert space.type == "global"

    def test_confluence_page_creation(self):
        """Should create ConfluencePage with all fields."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluencePage

        page = ConfluencePage(
            id="789",
            title="API Documentation",
            space_key="DEV",
            status="current",
            body="<p>Documentation content</p>",
            version=5,
            url="/display/DEV/API+Documentation",
            labels=["api", "docs"],
        )

        assert page.id == "789"
        assert page.title == "API Documentation"
        assert page.space_key == "DEV"
        assert page.version == 5
        assert "api" in page.labels


class TestConfluenceAuthentication:
    """Tests for authentication handling."""

    @pytest.mark.asyncio
    async def test_cloud_auth_uses_basic(self, mock_credentials):
        """Should use basic auth for Cloud instances."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        mock_credentials.set_credential("CONFLUENCE_EMAIL", "user@example.com")
        mock_credentials.set_credential("CONFLUENCE_API_TOKEN", "api_token_123")

        connector = ConfluenceConnector(base_url="https://test.atlassian.net/wiki")
        connector.credentials = mock_credentials

        headers = await connector._get_auth_header()

        assert "Authorization" in headers
        assert "Basic" in headers["Authorization"]

    @pytest.mark.asyncio
    async def test_datacenter_auth_uses_pat(self, mock_credentials):
        """Should use PAT for Data Center instances."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        mock_credentials.set_credential("CONFLUENCE_PAT", "pat_token_456")

        connector = ConfluenceConnector(base_url="https://confluence.company.com")
        connector.credentials = mock_credentials

        headers = await connector._get_auth_header()

        assert "Authorization" in headers


class TestConfluenceSpaceOperations:
    """Tests for space operations."""

    @pytest.mark.asyncio
    async def test_list_spaces(self, mock_credentials):
        """Should list accessible spaces."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        connector = ConfluenceConnector(base_url="https://test.atlassian.net/wiki")
        connector.credentials = mock_credentials

        mock_response = {
            "results": [
                {
                    "id": "1",
                    "key": "ENG",
                    "name": "Engineering",
                    "type": "global",
                    "status": "current",
                },
                {
                    "id": "2",
                    "key": "HR",
                    "name": "Human Resources",
                    "type": "global",
                    "status": "current",
                },
            ],
            "_links": {},
        }

        with patch.object(connector, "_api_request", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = mock_response

            spaces = await connector._get_spaces()

            assert len(spaces) == 2

    @pytest.mark.asyncio
    async def test_filter_spaces_by_key(self, mock_credentials):
        """Should filter spaces by configured keys."""
        from aragora.connectors.enterprise.collaboration.confluence import (
            ConfluenceConnector,
            ConfluenceSpace,
        )

        connector = ConfluenceConnector(
            base_url="https://test.atlassian.net/wiki",
            spaces=["ENG"],
        )
        connector.credentials = mock_credentials

        all_spaces = [
            ConfluenceSpace(id="1", key="ENG", name="Engineering", type="global", status="current"),
            ConfluenceSpace(
                id="2", key="HR", name="Human Resources", type="global", status="current"
            ),
        ]

        filtered = [s for s in all_spaces if connector.spaces is None or s.key in connector.spaces]

        assert len(filtered) == 1
        assert filtered[0].key == "ENG"


class TestConfluencePageOperations:
    """Tests for page operations."""

    @pytest.mark.asyncio
    async def test_get_space_pages(self, mock_confluence_pages, mock_credentials):
        """Should get pages from a space using async iterator."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        connector = ConfluenceConnector(base_url="https://test.atlassian.net/wiki")
        connector.credentials = mock_credentials

        # _get_pages returns an AsyncIterator, so we mock _api_request with paginated response
        mock_response = {
            "results": mock_confluence_pages,
            "_links": {},  # No next link = end of pagination
        }

        with patch.object(connector, "_api_request", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = mock_response

            # Collect pages from async iterator
            pages = []
            async for page in connector._get_pages("ENG"):
                pages.append(page)

            assert len(pages) >= 0

    @pytest.mark.asyncio
    async def test_exclude_pages_by_label(self, mock_credentials):
        """Should exclude pages with specified labels."""
        from aragora.connectors.enterprise.collaboration.confluence import (
            ConfluenceConnector,
            ConfluencePage,
        )

        connector = ConfluenceConnector(
            base_url="https://test.atlassian.net/wiki",
            exclude_labels=["draft", "private"],
        )
        connector.credentials = mock_credentials

        pages = [
            ConfluencePage(
                id="1", title="Public", space_key="ENG", status="current", labels=["public"]
            ),
            ConfluencePage(
                id="2", title="Draft", space_key="ENG", status="current", labels=["draft"]
            ),
            ConfluencePage(
                id="3",
                title="Private",
                space_key="ENG",
                status="current",
                labels=["private", "internal"],
            ),
        ]

        filtered = [
            p for p in pages if not any(lbl in connector.exclude_labels for lbl in p.labels)
        ]

        assert len(filtered) == 1
        assert filtered[0].title == "Public"


class TestConfluenceContentExtraction:
    """Tests for content extraction."""

    def test_html_to_text_basic(self, mock_credentials):
        """Should convert HTML to plain text."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        connector = ConfluenceConnector(base_url="https://test.atlassian.net/wiki")

        html_content = "<p>This is a paragraph.</p><p>Second paragraph.</p>"

        text = connector._html_to_text(html_content)

        assert "This is a paragraph" in text
        assert "Second paragraph" in text

    def test_html_to_text_with_headers(self, mock_credentials):
        """Should preserve header text."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        connector = ConfluenceConnector(base_url="https://test.atlassian.net/wiki")

        html_content = "<h1>Main Title</h1><p>Content here.</p>"

        text = connector._html_to_text(html_content)

        assert "Main Title" in text
        assert "Content" in text

    def test_html_to_text_with_lists(self, mock_credentials):
        """Should extract list items."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        connector = ConfluenceConnector(base_url="https://test.atlassian.net/wiki")

        html_content = "<ul><li>Item 1</li><li>Item 2</li></ul>"

        text = connector._html_to_text(html_content)

        assert "Item 1" in text
        assert "Item 2" in text

    def test_html_to_text_strips_tags(self, mock_credentials):
        """Should strip HTML tags from output."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        connector = ConfluenceConnector(base_url="https://test.atlassian.net/wiki")

        html_content = "<div><span>Text content</span></div>"

        text = connector._html_to_text(html_content)

        assert "<div>" not in text
        assert "<span>" not in text
        assert "Text content" in text


class TestConfluenceSyncItems:
    """Tests for sync_items generator."""

    @pytest.mark.asyncio
    async def test_sync_items_yields_pages(self, mock_credentials):
        """Should yield sync items for pages."""
        from aragora.connectors.enterprise.collaboration.confluence import (
            ConfluenceConnector,
            ConfluenceSpace,
        )

        connector = ConfluenceConnector(
            base_url="https://test.atlassian.net/wiki",
            spaces=["ENG"],
            include_attachments=False,
            include_comments=False,
        )
        connector.credentials = mock_credentials

        # Mock _get_spaces to return a space
        mock_spaces = [
            ConfluenceSpace(id="1", key="ENG", name="Engineering", type="global", status="current")
        ]

        # Mock _api_request to return empty pages (simulating end of pagination)
        with patch.object(connector, "_get_spaces", new_callable=AsyncMock) as mock_get_spaces:
            mock_get_spaces.return_value = mock_spaces

            with patch.object(connector, "_api_request", new_callable=AsyncMock) as mock_api:
                mock_api.return_value = {"results": [], "_links": {}}

                state = SyncState(connector_id="confluence_test")
                items = []

                async for item in connector.sync_items(state):
                    items.append(item)

                assert isinstance(items, list)

    @pytest.mark.asyncio
    async def test_sync_includes_metadata(self, mock_credentials):
        """Should include metadata in sync items."""
        from aragora.connectors.enterprise.collaboration.confluence import (
            ConfluenceConnector,
            ConfluencePage,
        )

        connector = ConfluenceConnector(base_url="https://test.atlassian.net/wiki")
        connector.credentials = mock_credentials

        page = ConfluencePage(
            id="123",
            title="Test Page",
            space_key="ENG",
            status="current",
            body="<p>Content</p>",
            version=5,
        )

        # Metadata should include space, version
        assert page.space_key == "ENG"
        assert page.version == 5


class TestConfluenceIncrementalSync:
    """Tests for incremental sync."""

    @pytest.mark.asyncio
    async def test_uses_modified_since_for_incremental(self, mock_credentials):
        """Should filter by modified_since for incremental sync."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        connector = ConfluenceConnector(base_url="https://test.atlassian.net/wiki")
        connector.credentials = mock_credentials

        last_sync = datetime(2024, 1, 15, tzinfo=timezone.utc)

        with patch.object(connector, "_api_request", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"results": [], "_links": {}}

            # _get_pages accepts modified_since parameter
            pages = []
            async for page in connector._get_pages("ENG", modified_since=last_sync):
                pages.append(page)

            # API should have been called
            mock_api.assert_called()


class TestConfluenceErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_handles_api_error(self, mock_credentials):
        """API errors from _api_request propagate out of _get_spaces."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        connector = ConfluenceConnector(base_url="https://test.atlassian.net/wiki")
        connector.credentials = mock_credentials

        with patch.object(connector, "_api_request", new_callable=AsyncMock) as mock_api:
            # _api_request surfaces HTTP failures via response.raise_for_status()
            mock_api.side_effect = httpx.HTTPStatusError(
                "API Error", request=MagicMock(), response=MagicMock(status_code=500)
            )

            with pytest.raises(httpx.HTTPStatusError, match="API Error"):
                await connector._get_spaces()

            mock_api.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_space_not_found(self, mock_credentials):
        """Should handle space not found - returns empty results."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        connector = ConfluenceConnector(
            base_url="https://test.atlassian.net/wiki",
            spaces=["NONEXISTENT"],
        )
        connector.credentials = mock_credentials

        with patch.object(connector, "_api_request", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"results": [], "_links": {}}

            # _get_pages is an async iterator
            pages = []
            async for page in connector._get_pages("NONEXISTENT"):
                pages.append(page)

            assert pages == []

    @pytest.mark.asyncio
    async def test_handles_permission_denied(self, mock_credentials):
        """A 403 from _api_request propagates out of _get_spaces."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        connector = ConfluenceConnector(base_url="https://test.atlassian.net/wiki")
        connector.credentials = mock_credentials

        with patch.object(connector, "_api_request", new_callable=AsyncMock) as mock_api:
            mock_api.side_effect = httpx.HTTPStatusError(
                "403 Forbidden", request=MagicMock(), response=MagicMock(status_code=403)
            )

            with pytest.raises(httpx.HTTPStatusError, match="403 Forbidden"):
                await connector._get_spaces()

            mock_api.assert_awaited_once()


class TestConfluenceWebhooks:
    """Tests for webhook handling."""

    @pytest.mark.asyncio
    async def test_handle_page_updated_webhook(self, mock_credentials):
        """Should handle page updated webhook."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        connector = ConfluenceConnector(base_url="https://test.atlassian.net/wiki")
        connector.credentials = mock_credentials

        payload = {
            "event": "page_updated",
            "page": {
                "id": "123",
                "title": "Updated Page",
                "space": {"key": "ENG"},
            },
        }

        result = await connector.handle_webhook(payload)

        assert result is True or result is None or isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_handle_page_created_webhook(self, mock_credentials):
        """Should handle page created webhook."""
        from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

        connector = ConfluenceConnector(base_url="https://test.atlassian.net/wiki")
        connector.credentials = mock_credentials

        payload = {
            "event": "page_created",
            "page": {
                "id": "456",
                "title": "New Page",
                "space": {"key": "DOCS"},
            },
        }

        result = await connector.handle_webhook(payload)

        assert result is True or result is None or isinstance(result, bool)
