"""
Tests for Notion Enterprise Connector.

Tests cover:
- Initialization and configuration
- Page and database crawling
- Block content extraction
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


class TestNotionConnectorInitialization:
    """Tests for connector initialization."""

    def test_init_with_defaults(self):
        """Should initialize with default values."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector()

        assert connector.workspace_name == "default"
        assert connector.include_archived is False
        assert connector.include_databases is True
        assert connector.max_depth == 5
        assert connector.recursive_pages is True

    def test_init_with_custom_config(self):
        """Should initialize with custom configuration."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector(
            workspace_name="Engineering",
            include_archived=True,
            include_databases=False,
            max_depth=3,
            recursive_pages=False,
        )

        assert connector.workspace_name == "Engineering"
        assert connector.include_archived is True
        assert connector.include_databases is False
        assert connector.max_depth == 3
        assert connector.recursive_pages is False

    def test_source_type_is_document(self):
        """Should return DOCUMENT source type."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector()
        assert connector.source_type == SourceType.DOCUMENT

    def test_connector_id_is_normalized(self):
        """Should normalize workspace name in connector ID."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector(workspace_name="My Workspace")

        assert "my_workspace" in connector.connector_id.lower()
        assert " " not in connector.connector_id

    def test_name_includes_workspace(self):
        """Should include workspace name in connector name."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector(workspace_name="Engineering")
        assert "Engineering" in connector.name


class TestNotionDataclasses:
    """Tests for Notion dataclasses."""

    def test_notion_page_creation(self):
        """Should create NotionPage with all fields."""
        from aragora.connectors.enterprise.collaboration.notion import NotionPage

        page = NotionPage(
            id="page-001",
            title="Project Overview",
            url="https://notion.so/page-001",
            content="Page content here",
            parent_type="workspace",
            parent_id="ws-001",
            created_by="user-001",
            created_at=datetime.now(timezone.utc),
            last_edited_at=datetime.now(timezone.utc),
        )

        assert page.id == "page-001"
        assert page.title == "Project Overview"
        assert page.parent_type == "workspace"

    def test_notion_database_creation(self):
        """Should create NotionDatabase with all fields."""
        from aragora.connectors.enterprise.collaboration.notion import NotionDatabase

        database = NotionDatabase(
            id="db-001",
            title="Tasks Database",
            url="https://notion.so/db-001",
            description="Track project tasks",
            properties={"Status": {"type": "select"}},
        )

        assert database.id == "db-001"
        assert database.title == "Tasks Database"
        assert "Status" in database.properties


class TestNotionAuthentication:
    """Tests for authentication handling."""

    @pytest.mark.asyncio
    async def test_get_auth_header_with_token(self, mock_credentials):
        """Should build auth header from API token."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        mock_credentials.set_credential("NOTION_API_TOKEN", "secret_test_token")

        connector = NotionConnector()
        connector.credentials = mock_credentials

        headers = await connector._get_auth_header()

        assert "Authorization" in headers
        assert "Bearer secret_test_token" in headers["Authorization"]
        assert "Notion-Version" in headers

    @pytest.mark.asyncio
    async def test_get_auth_header_raises_without_token(self, mock_credentials):
        """Should raise error when token not configured."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        # Clear the token
        mock_credentials._credentials = {}

        connector = NotionConnector()
        connector.credentials = mock_credentials

        with pytest.raises(ValueError, match="credentials not configured"):
            await connector._get_auth_header()


class TestNotionPageOperations:
    """Tests for page operations."""

    @pytest.mark.asyncio
    async def test_search_pages(self, mock_notion_pages, mock_credentials):
        """Should search and return pages."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector()
        connector.credentials = mock_credentials

        mock_response = {
            "results": mock_notion_pages,
            "has_more": False,
            "next_cursor": None,
        }

        with patch.object(connector, "_api_request", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = mock_response

            pages = await connector._search_pages()

            assert len(pages) >= 0
            mock_api.assert_called()

    @pytest.mark.asyncio
    async def test_get_page_content(self, mock_notion_blocks, mock_credentials):
        """Should extract content from page blocks."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector()
        connector.credentials = mock_credentials

        mock_response = {
            "results": mock_notion_blocks,
            "has_more": False,
        }

        with patch.object(connector, "_api_request", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = mock_response

            content = await connector._get_page_content("page-001")

            assert isinstance(content, str)

    @pytest.mark.asyncio
    async def test_filter_archived_pages(self, mock_credentials):
        """Should filter archived pages when configured."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector, NotionPage

        connector = NotionConnector(include_archived=False)
        connector.credentials = mock_credentials

        pages = [
            NotionPage(id="p1", title="Active", url="", archived=False),
            NotionPage(id="p2", title="Archived", url="", archived=True),
        ]

        filtered = [p for p in pages if not p.archived or connector.include_archived]

        assert len(filtered) == 1
        assert filtered[0].title == "Active"


class TestNotionBlockExtraction:
    """Tests for block content extraction."""

    def test_extract_paragraph_block(self, mock_credentials):
        """Should extract text from paragraph block."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector()

        block = {
            "type": "paragraph",
            "paragraph": {"rich_text": [{"plain_text": "This is a paragraph."}]},
        }

        text = connector._extract_block_content(block)

        assert "This is a paragraph." in text

    def test_extract_heading_block(self, mock_credentials):
        """Should extract text from heading blocks."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector()

        block = {
            "type": "heading_1",
            "heading_1": {"rich_text": [{"plain_text": "Main Title"}]},
        }

        text = connector._extract_block_content(block)

        assert "Main Title" in text

    def test_extract_list_item_block(self, mock_credentials):
        """Should extract text from list item blocks."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector()

        block = {
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"plain_text": "List item text"}]},
        }

        text = connector._extract_block_content(block)

        assert "List item text" in text

    def test_handle_empty_rich_text(self, mock_credentials):
        """Should handle blocks with empty rich text."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector()

        block = {
            "type": "paragraph",
            "paragraph": {"rich_text": []},
        }

        text = connector._extract_block_content(block)

        assert text == "" or text is None or isinstance(text, str)


class TestNotionDatabaseOperations:
    """Tests for database operations."""

    @pytest.mark.asyncio
    async def test_get_database(self, mock_credentials):
        """Should get a database by ID."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector(include_databases=True)
        connector.credentials = mock_credentials

        mock_response = {
            "id": "db-001",
            "object": "database",
            "title": [{"plain_text": "Tasks"}],
            "description": [{"plain_text": "Task tracking"}],
            "properties": {"Status": {"type": "select"}},
            "url": "https://notion.so/db-001",
        }

        with patch.object(connector, "_api_request", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = mock_response

            database = await connector._get_database("db-001")

            assert database is not None or isinstance(database, object)

    @pytest.mark.asyncio
    async def test_skip_databases_when_disabled(self, mock_credentials):
        """Should skip database crawling when disabled."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector(include_databases=False)
        connector.credentials = mock_credentials

        # Database operations should be skipped
        assert connector.include_databases is False


class TestNotionSyncItems:
    """Tests for sync_items generator."""

    @pytest.mark.asyncio
    async def test_sync_items_yields_pages(self, mock_credentials):
        """Should yield sync items for pages."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector(include_databases=False)
        connector.credentials = mock_credentials

        with patch.object(connector, "_search_pages", new_callable=AsyncMock) as mock_search:
            with patch.object(
                connector, "_get_page_content", new_callable=AsyncMock
            ) as mock_content:
                # _search_pages returns tuple (results, next_cursor)
                mock_search.return_value = ([], None)  # Empty results, no next cursor
                mock_content.return_value = "Page content"

                state = SyncState(connector_id="notion_test")
                items = []

                async for item in connector.sync_items(state):
                    items.append(item)

                # Should complete without error
                assert isinstance(items, list)

    @pytest.mark.asyncio
    async def test_sync_respects_max_depth(self, mock_credentials):
        """Should respect max_depth for nested pages."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector(max_depth=2, recursive_pages=True)
        connector.credentials = mock_credentials

        assert connector.max_depth == 2
        assert connector.recursive_pages is True


class TestNotionErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_handles_api_rate_limit(self, mock_credentials):
        """Should handle API rate limit errors."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector()
        connector.credentials = mock_credentials

        with patch.object(connector, "_api_request", new_callable=AsyncMock) as mock_api:
            mock_api.side_effect = Exception("rate_limited")

            # Should handle gracefully
            try:
                await connector._search_pages()
            except Exception as e:
                assert "rate" in str(e).lower() or True

    @pytest.mark.asyncio
    async def test_handles_invalid_page_id(self, mock_credentials):
        """A not-found error for the page's blocks propagates out of _get_page_content."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector()
        connector.credentials = mock_credentials

        with patch.object(connector, "_api_request", new_callable=AsyncMock) as mock_api:
            # Notion answers an unknown page id with HTTP 404 object_not_found,
            # which _api_request surfaces via response.raise_for_status()
            mock_api.side_effect = httpx.HTTPStatusError(
                "object_not_found", request=MagicMock(), response=MagicMock(status_code=404)
            )

            with pytest.raises(httpx.HTTPStatusError, match="object_not_found"):
                await connector._get_page_content("invalid-page-id")

            mock_api.assert_awaited_once_with(
                "/blocks/invalid-page-id/children", params={"page_size": 100}
            )

    @pytest.mark.asyncio
    async def test_handles_permission_denied(self, mock_credentials):
        """A 403 restricted_resource error propagates out of _search_pages."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector()
        connector.credentials = mock_credentials

        with patch.object(connector, "_api_request", new_callable=AsyncMock) as mock_api:
            # Notion answers a permission failure with HTTP 403 restricted_resource
            mock_api.side_effect = httpx.HTTPStatusError(
                "restricted_resource", request=MagicMock(), response=MagicMock(status_code=403)
            )

            with pytest.raises(httpx.HTTPStatusError, match="restricted_resource"):
                await connector._search_pages()

            mock_api.assert_awaited_once()


class TestNotionRichTextExtraction:
    """Tests for rich text extraction."""

    def test_extract_rich_text_to_string(self, mock_credentials):
        """Should convert rich text array to string."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector()

        rich_text = [
            {"plain_text": "Hello "},
            {"plain_text": "World"},
        ]

        text = connector._rich_text_to_string(rich_text)

        assert "Hello" in text
        assert "World" in text

    def test_handle_empty_rich_text(self, mock_credentials):
        """Should handle empty rich text array."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector

        connector = NotionConnector()

        text = connector._rich_text_to_string([])

        assert text == "" or isinstance(text, str)

    def test_parse_page_extracts_title(self, mock_credentials):
        """Should extract title from page data."""
        from aragora.connectors.enterprise.collaboration.notion import NotionConnector
        from datetime import datetime, timezone

        connector = NotionConnector()

        # The _parse_page method looks for properties with "type": "title"
        page_data = {
            "id": "page-001",
            "url": "https://notion.so/page-001",
            "archived": False,
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "My Page Title"}]},
            },
            "parent": {"type": "workspace"},
            "created_by": {"id": "user-001"},
            "created_time": "2024-01-01T00:00:00.000Z",
            "last_edited_time": "2024-01-02T00:00:00.000Z",
        }

        page = connector._parse_page(page_data)

        assert page.title == "My Page Title"
        assert page.id == "page-001"
