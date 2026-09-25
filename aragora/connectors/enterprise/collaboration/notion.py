"""
Notion Enterprise Connector.

Provides full integration with Notion workspaces:
- Page and database crawling
- Block content extraction
- Database property extraction
- Incremental sync via timestamps
- Nested page traversal

Requires Notion Integration API credentials.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from collections.abc import AsyncIterator

_MAX_PAGES = 1000  # Safety cap for pagination loops

from aragora.connectors.enterprise.base import (
    EnterpriseConnector,
    SyncItem,
    SyncState,
)
from aragora.reasoning.provenance import SourceType

logger = logging.getLogger(__name__)


@dataclass
class NotionPage:
    """A Notion page."""

    id: str
    title: str
    url: str
    content: str = ""
    parent_type: str = ""  # workspace, page_id, database_id
    parent_id: str = ""
    created_by: str = ""
    created_at: datetime | None = None
    last_edited_by: str = ""
    last_edited_at: datetime | None = None
    archived: bool = False
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class NotionDatabase:
    """A Notion database."""

    id: str
    title: str
    url: str
    description: str = ""
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    last_edited_at: datetime | None = None


class NotionConnector(EnterpriseConnector):
    """
    Enterprise connector for Notion workspaces.

    Features:
    - Page content extraction (all block types)
    - Database crawling with property extraction
    - Nested page traversal
    - Incremental sync via last_edited_time
    - Rich text to plaintext conversion

    Authentication:
    - Internal Integration token
    - Requires workspace access configuration in Notion

    Usage:
        connector = NotionConnector(
            workspace_name="Engineering",  # For identification
        )
        result = await connector.sync()
    """

    def __init__(
        self,
        workspace_name: str = "default",
        include_archived: bool = False,
        include_databases: bool = True,
        max_depth: int = 5,
        recursive_pages: bool = True,
        inline_child_content: bool = False,
        **kwargs: Any,
    ):
        """
        Initialize Notion connector.

        Args:
            workspace_name: Name for identification (any string)
            include_archived: Whether to include archived pages
            include_databases: Whether to crawl database entries
            max_depth: Maximum depth for nested page traversal
            recursive_pages: Whether to recursively discover and sync child pages
                            that might not be returned by search API
            inline_child_content: Whether to include child page content inline
                                 within parent page content
        """
        connector_id = f"notion_{workspace_name.lower().replace(' ', '_')}"
        super().__init__(connector_id=connector_id, **kwargs)

        self.workspace_name = workspace_name
        self.include_archived = include_archived
        self.include_databases = include_databases
        self.max_depth = max_depth
        self.recursive_pages = recursive_pages
        self.inline_child_content = inline_child_content

        # Cache
        self._pages_cache: dict[str, NotionPage] = {}
        self._databases_cache: dict[str, NotionDatabase] = {}
        self._synced_page_ids: set[str] = set()  # Track synced pages to avoid duplicates

    @property
    def source_type(self) -> SourceType:
        return SourceType.DOCUMENT

    @property
    def name(self) -> str:
        return f"Notion ({self.workspace_name})"

    async def _get_auth_header(self) -> dict[str, str]:
        """Get authentication header."""
        token = await self.credentials.get_credential("NOTION_API_TOKEN")

        if not token:
            raise ValueError("Notion credentials not configured. Set NOTION_API_TOKEN")

        return {
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
        }

    async def _api_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a request to Notion API."""
        from aragora.observability.http_client_pool import get_http_pool

        headers = await self._get_auth_header()
        headers["Content-Type"] = "application/json"

        url = f"https://api.notion.com/v1{endpoint}"

        pool = get_http_pool()
        async with pool.get_session("notion") as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_data,
                timeout=60,
            )
            response.raise_for_status()
            return response.json() if response.content else {}

    async def _search_pages(
        self,
        query: str = "",
        filter_type: str | None = None,
        start_cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Search for pages and databases."""
        body: dict[str, Any] = {
            "page_size": 100,
        }

        if query:
            body["query"] = query

        if filter_type:
            body["filter"] = {"property": "object", "value": filter_type}

        if start_cursor:
            body["start_cursor"] = start_cursor

        data = await self._api_request("/search", method="POST", json_data=body)

        results = data.get("results", [])
        next_cursor = data.get("next_cursor")

        return results, next_cursor

    async def _get_page(self, page_id: str) -> NotionPage | None:
        """Get a page by ID."""
        try:
            data = await self._api_request(f"/pages/{page_id}")
            return self._parse_page(data)
        except (RuntimeError, ValueError, KeyError, Exception) as e:
            logger.warning("[%s] Failed to get page %s: %s", self.name, page_id, e)
            return None

    async def _get_database(self, database_id: str) -> NotionDatabase | None:
        """Get a database by ID."""
        try:
            data = await self._api_request(f"/databases/{database_id}")
            return self._parse_database(data)
        except (RuntimeError, ValueError, KeyError, Exception) as e:
            logger.warning("[%s] Failed to get database %s: %s", self.name, database_id, e)
            return None

    async def _query_database(
        self,
        database_id: str,
        start_cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Query database entries."""
        body: dict[str, Any] = {
            "page_size": 100,
        }

        if start_cursor:
            body["start_cursor"] = start_cursor

        data = await self._api_request(
            f"/databases/{database_id}/query",
            method="POST",
            json_data=body,
        )

        results = data.get("results", [])
        next_cursor = data.get("next_cursor")

        return results, next_cursor

    async def _get_block_children(
        self,
        block_id: str,
        start_cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Get child blocks of a block."""
        params: dict[str, Any] = {"page_size": 100}

        if start_cursor:
            params["start_cursor"] = start_cursor

        data = await self._api_request(f"/blocks/{block_id}/children", params=params)

        results = data.get("results", [])
        next_cursor = data.get("next_cursor")

        return results, next_cursor

    async def _get_page_content(
        self,
        page_id: str,
        depth: int = 0,
        include_child_pages: bool = False,
    ) -> str:
        """
        Get full content of a page by extracting all blocks.

        Args:
            page_id: The page ID to fetch content from
            depth: Current recursion depth (for max_depth limit)
            include_child_pages: If True, recursively include child page content inline

        Returns:
            Extracted text content from all blocks
        """
        if depth >= self.max_depth:
            return ""

        content_parts = []
        cursor = None

        for _page in range(_MAX_PAGES):
            blocks, cursor = await self._get_block_children(page_id, cursor)

            for block in blocks:
                block_type = block.get("type", "")

                # Handle child pages with optional inline expansion
                if block_type == "child_page" and include_child_pages:
                    child_id = block.get("id", "")
                    child_title = block.get("child_page", {}).get("title", "Untitled")
                    content_parts.append(f"\n## [Child Page: {child_title}]\n")
                    child_content = await self._get_page_content(
                        child_id, depth + 1, include_child_pages=True
                    )
                    if child_content:
                        content_parts.append(child_content)
                    content_parts.append(f"\n[End of {child_title}]\n")
                else:
                    block_content = self._extract_block_content(block)
                    if block_content:
                        content_parts.append(block_content)

                # Recursively get nested blocks (not child pages, just nested content)
                if block.get("has_children") and block_type not in ["child_page", "child_database"]:
                    nested_content = await self._get_page_content(
                        block["id"], depth + 1, include_child_pages=include_child_pages
                    )
                    if nested_content:
                        content_parts.append(nested_content)

            if not cursor:
                break

        return "\n".join(content_parts)

    async def _discover_child_pages(
        self,
        page_id: str,
        depth: int = 0,
    ) -> AsyncIterator[tuple[str, str, int]]:
        """
        Recursively discover all child pages within a page.

        Yields:
            Tuples of (child_page_id, child_title, depth_level)
        """
        if depth >= self.max_depth:
            return

        cursor = None

        for _page in range(_MAX_PAGES):
            blocks, cursor = await self._get_block_children(page_id, cursor)

            for block in blocks:
                block_type = block.get("type", "")

                if block_type == "child_page":
                    child_id = block.get("id", "")
                    child_title = block.get("child_page", {}).get("title", "Untitled")
                    yield (child_id, child_title, depth)

                    # Recursively find children of this child page
                    async for nested in self._discover_child_pages(child_id, depth + 1):
                        yield nested

                elif block_type == "child_database":
                    # Child databases are also discoverable
                    db_id = block.get("id", "")
                    db_title = block.get("child_database", {}).get("title", "Untitled Database")
                    # We mark these with a special prefix in the title
                    yield (db_id, f"[DB] {db_title}", depth)

                # Check nested blocks for child pages (e.g., toggles can contain child pages)
                elif block.get("has_children"):
                    async for nested in self._discover_child_pages(block["id"], depth):
                        yield nested

            if not cursor:
                break

    def _parse_page(self, data: dict[str, Any]) -> NotionPage:
        """Parse page data into NotionPage."""
        # Extract title from properties
        # Notion API can return properties with or without "type" field
        title = ""
        properties = data.get("properties", {})
        for prop_name, prop_value in properties.items():
            # Check for explicit type field or infer from structure
            is_title_prop = prop_value.get("type") == "title" or (
                prop_name.lower() == "title" and "title" in prop_value
            )
            if is_title_prop:
                title_parts = prop_value.get("title", [])
                title = self._rich_text_to_string(title_parts)
                break

        # Parse parent
        parent = data.get("parent", {})
        parent_type = parent.get("type", "")
        parent_id = parent.get(parent_type, "") if parent_type else ""

        # Parse timestamps
        created_at = None
        last_edited_at = None

        if data.get("created_time"):
            try:
                created_at = datetime.fromisoformat(data["created_time"].replace("Z", "+00:00"))
            except ValueError as e:
                logger.debug("Invalid created_time format: %s", e)

        if data.get("last_edited_time"):
            try:
                last_edited_at = datetime.fromisoformat(
                    data["last_edited_time"].replace("Z", "+00:00")
                )
            except ValueError as e:
                logger.debug("Invalid last_edited_time format: %s", e)

        return NotionPage(
            id=data.get("id", ""),
            title=title or "Untitled",
            url=data.get("url", ""),
            parent_type=parent_type,
            parent_id=parent_id,
            created_by=data.get("created_by", {}).get("id", ""),
            created_at=created_at,
            last_edited_by=data.get("last_edited_by", {}).get("id", ""),
            last_edited_at=last_edited_at,
            archived=data.get("archived", False),
            properties=properties,
        )

    def _parse_database(self, data: dict[str, Any]) -> NotionDatabase:
        """Parse database data into NotionDatabase."""
        # Extract title
        title_parts = data.get("title", [])
        title = self._rich_text_to_string(title_parts) or "Untitled Database"

        # Extract description
        description_parts = data.get("description", [])
        description = self._rich_text_to_string(description_parts)

        # Parse timestamps
        created_at = None
        last_edited_at = None

        if data.get("created_time"):
            try:
                created_at = datetime.fromisoformat(data["created_time"].replace("Z", "+00:00"))
            except ValueError as e:
                logger.debug("Invalid created_time format: %s", e)

        if data.get("last_edited_time"):
            try:
                last_edited_at = datetime.fromisoformat(
                    data["last_edited_time"].replace("Z", "+00:00")
                )
            except ValueError as e:
                logger.debug("Invalid last_edited_time format: %s", e)

        return NotionDatabase(
            id=data.get("id", ""),
            title=title,
            url=data.get("url", ""),
            description=description,
            properties=data.get("properties", {}),
            created_at=created_at,
            last_edited_at=last_edited_at,
        )

    def _rich_text_to_string(self, rich_text: list[dict[str, Any]]) -> str:
        """Convert Notion rich text array to plain string."""
        parts = []
        for item in rich_text:
            text = item.get("plain_text", "") or item.get("text", {}).get("content", "")
            if text:
                parts.append(text)
        return "".join(parts)

    def _extract_block_content(self, block: dict[str, Any]) -> str:
        """Extract text content from a block."""
        block_type = block.get("type", "")
        block_data = block.get(block_type, {})

        # Text-based blocks
        if block_type in [
            "paragraph",
            "heading_1",
            "heading_2",
            "heading_3",
            "bulleted_list_item",
            "numbered_list_item",
            "quote",
            "callout",
            "toggle",
        ]:
            rich_text = block_data.get("rich_text", [])
            text = self._rich_text_to_string(rich_text)

            # Add formatting
            if block_type == "heading_1":
                return f"# {text}"
            elif block_type == "heading_2":
                return f"## {text}"
            elif block_type == "heading_3":
                return f"### {text}"
            elif block_type == "bulleted_list_item":
                return f"- {text}"
            elif block_type == "numbered_list_item":
                return f"1. {text}"
            elif block_type == "quote":
                return f"> {text}"
            elif block_type == "callout":
                emoji = block_data.get("icon", {}).get("emoji", "")
                return f"{emoji} {text}"

            return text

        # Code blocks
        elif block_type == "code":
            rich_text = block_data.get("rich_text", [])
            code = self._rich_text_to_string(rich_text)
            language = block_data.get("language", "")
            return f"```{language}\n{code}\n```"

        # To-do items
        elif block_type == "to_do":
            rich_text = block_data.get("rich_text", [])
            text = self._rich_text_to_string(rich_text)
            checked = block_data.get("checked", False)
            return f"[{'x' if checked else ' '}] {text}"

        # Table of contents, divider, etc.
        elif block_type == "divider":
            return "---"

        # Embed types
        elif block_type in ["embed", "bookmark", "link_preview"]:
            url = block_data.get("url", "")
            return f"[Link: {url}]"

        # File/Image
        elif block_type in ["file", "image", "video", "pdf"]:
            file_data = block_data.get("file", {}) or block_data.get("external", {})
            url = file_data.get("url", "")
            caption = self._rich_text_to_string(block_data.get("caption", []))
            return f"[{block_type.title()}: {caption or url}]"

        # Child page/database - return placeholder with ID for later recursion
        elif block_type == "child_page":
            title = block_data.get("title", "Untitled")
            return f"[Child Page: {title}]"

        elif block_type == "child_database":
            title = block_data.get("title", "Untitled")
            return f"[Child Database: {title}]"

        # Synced block
        elif block_type == "synced_block":
            # Synced blocks reference content from another block
            synced_from = block_data.get("synced_from")
            if synced_from:
                return f"[Synced from: {synced_from.get('block_id', 'unknown')}]"
            return ""

        # Column and column_list
        elif block_type in ["column", "column_list"]:
            # Content comes from nested blocks, which are handled by has_children
            return ""

        # Table blocks
        elif block_type == "table":
            return "[Table]"

        elif block_type == "table_row":
            cells = block_data.get("cells", [])
            row_parts = []
            for cell in cells:
                cell_text = self._rich_text_to_string(cell)
                row_parts.append(cell_text)
            return " | ".join(row_parts)

        return ""

    def _extract_database_entry_content(
        self,
        entry: dict[str, Any],
        database: NotionDatabase,
    ) -> str:
        """Extract content from a database entry."""
        parts = []

        properties = entry.get("properties", {})

        for prop_name, prop_value in properties.items():
            prop_type = prop_value.get("type", "")
            value = ""

            if prop_type == "title":
                value = self._rich_text_to_string(prop_value.get("title", []))
            elif prop_type == "rich_text":
                value = self._rich_text_to_string(prop_value.get("rich_text", []))
            elif prop_type == "number":
                value = str(prop_value.get("number", ""))
            elif prop_type == "select":
                select = prop_value.get("select")
                value = select.get("name", "") if select else ""
            elif prop_type == "multi_select":
                options = prop_value.get("multi_select", [])
                value = ", ".join(opt.get("name", "") for opt in options)
            elif prop_type == "date":
                date = prop_value.get("date")
                if date:
                    value = date.get("start", "")
                    if date.get("end"):
                        value += f" - {date['end']}"
            elif prop_type == "checkbox":
                value = "Yes" if prop_value.get("checkbox") else "No"
            elif prop_type == "url":
                value = prop_value.get("url", "")
            elif prop_type == "email":
                value = prop_value.get("email", "")
            elif prop_type == "phone_number":
                value = prop_value.get("phone_number", "")
            elif prop_type == "status":
                status = prop_value.get("status")
                value = status.get("name", "") if status else ""

            if value:
                parts.append(f"{prop_name}: {value}")

        return "\n".join(parts)

    async def sync_items(
        self,
        state: SyncState,
        batch_size: int = 100,
    ) -> AsyncIterator[SyncItem]:
        """
        Yield Notion pages and database entries for syncing.

        Features:
        - Searches all pages accessible via the integration
        - Optionally discovers child pages recursively (recursive_pages=True)
        - Optionally inlines child page content (inline_child_content=True)
        - Tracks synced pages to avoid duplicates
        """
        # Reset synced page tracking for this sync
        self._synced_page_ids.clear()

        # Parse last sync timestamp from cursor
        modified_since = None
        if state.cursor:
            try:
                modified_since = datetime.fromisoformat(state.cursor)
            except ValueError as e:
                logger.debug("Invalid cursor timestamp, starting fresh sync: %s", e)

        items_yielded = 0
        cursor = None
        pages_for_recursion: list[str] = []  # Track pages to check for child pages

        # Search for all pages
        for _page in range(_MAX_PAGES):
            results, cursor = await self._search_pages(filter_type="page", start_cursor=cursor)

            for item in results:
                if item.get("object") != "page":
                    continue

                page = self._parse_page(item)

                # Skip archived if not included
                if page.archived and not self.include_archived:
                    continue

                # Skip if already synced (shouldn't happen in search, but safety check)
                if page.id in self._synced_page_ids:
                    continue

                # Skip if not modified since last sync
                if modified_since and page.last_edited_at and page.last_edited_at < modified_since:
                    continue

                # Get full content (with optional inline child pages)
                content = await self._get_page_content(
                    page.id,
                    include_child_pages=self.inline_child_content,
                )
                page.content = content

                full_content = f"# {page.title}\n\n{content}"

                yield SyncItem(
                    id=f"notion-page-{page.id}",
                    content=full_content[:50000],
                    source_type="document",
                    source_id=f"notion/page/{page.id}",
                    title=page.title,
                    url=page.url,
                    author=page.last_edited_by or page.created_by,
                    created_at=page.created_at,
                    updated_at=page.last_edited_at,
                    domain="enterprise/notion",
                    confidence=0.85,
                    metadata={
                        "page_id": page.id,
                        "parent_type": page.parent_type,
                        "parent_id": page.parent_id,
                        "archived": page.archived,
                    },
                )

                self._synced_page_ids.add(page.id)
                items_yielded += 1

                # Track pages for recursive child discovery
                if self.recursive_pages:
                    pages_for_recursion.append(page.id)

                # Update cursor
                if page.last_edited_at:
                    current = state.cursor
                    new_ts = page.last_edited_at.isoformat()
                    if not current or new_ts > current:
                        state.cursor = new_ts

                if items_yielded >= batch_size:
                    await asyncio.sleep(0)

            if not cursor:
                break

        # Recursive child page discovery
        # This finds child pages that might not be returned by search API
        # (e.g., pages created inside other pages that aren't explicitly shared)
        if self.recursive_pages and pages_for_recursion:
            logger.debug(
                "[%s] Discovering child pages from %s parent pages",
                self.name,
                len(pages_for_recursion),
            )

            for parent_id in pages_for_recursion:
                async for child_id, child_title, depth in self._discover_child_pages(parent_id):
                    # Skip already synced pages
                    if child_id in self._synced_page_ids:
                        continue

                    # Skip database children (handled separately)
                    if child_title.startswith("[DB] "):
                        continue

                    # Fetch the child page
                    child_page = await self._get_page(child_id)
                    if not child_page:
                        continue

                    if child_page.archived and not self.include_archived:
                        continue

                    if (
                        modified_since
                        and child_page.last_edited_at
                        and child_page.last_edited_at < modified_since
                    ):
                        continue

                    # Get content
                    content = await self._get_page_content(
                        child_page.id,
                        include_child_pages=self.inline_child_content,
                    )
                    child_page.content = content

                    full_content = f"# {child_page.title}\n\n{content}"

                    yield SyncItem(
                        id=f"notion-page-{child_page.id}",
                        content=full_content[:50000],
                        source_type="document",
                        source_id=f"notion/page/{child_page.id}",
                        title=child_page.title,
                        url=child_page.url,
                        author=child_page.last_edited_by or child_page.created_by,
                        created_at=child_page.created_at,
                        updated_at=child_page.last_edited_at,
                        domain="enterprise/notion",
                        confidence=0.85,
                        metadata={
                            "page_id": child_page.id,
                            "parent_type": child_page.parent_type,
                            "parent_id": child_page.parent_id,
                            "archived": child_page.archived,
                            "discovered_from": parent_id,
                            "nesting_depth": depth,
                        },
                    )

                    self._synced_page_ids.add(child_page.id)
                    items_yielded += 1

                    if child_page.last_edited_at:
                        current = state.cursor
                        new_ts = child_page.last_edited_at.isoformat()
                        if not current or new_ts > current:
                            state.cursor = new_ts

                    if items_yielded >= batch_size:
                        await asyncio.sleep(0)

        # Search for databases and their entries
        if self.include_databases:
            cursor = None

            for _page in range(_MAX_PAGES):
                results, cursor = await self._search_pages(
                    filter_type="database", start_cursor=cursor
                )

                for item in results:
                    if item.get("object") != "database":
                        continue

                    database = self._parse_database(item)
                    self._databases_cache[database.id] = database

                    # Query database entries
                    entry_cursor = None
                    for _entry_page in range(_MAX_PAGES):
                        entries, entry_cursor = await self._query_database(
                            database.id, entry_cursor
                        )

                        for entry in entries:
                            entry_page = self._parse_page(entry)

                            if entry_page.archived and not self.include_archived:
                                continue

                            if (
                                modified_since
                                and entry_page.last_edited_at
                                and entry_page.last_edited_at < modified_since
                            ):
                                continue

                            # Extract properties content
                            props_content = self._extract_database_entry_content(entry, database)

                            # Get page content
                            page_content = await self._get_page_content(entry_page.id)

                            full_content = (
                                f"# {entry_page.title}\n\n{props_content}\n\n{page_content}"
                            )

                            yield SyncItem(
                                id=f"notion-db-{database.id}-{entry_page.id}",
                                content=full_content[:50000],
                                source_type="document",
                                source_id=f"notion/database/{database.id}/entry/{entry_page.id}",
                                title=entry_page.title,
                                url=entry_page.url,
                                author=entry_page.last_edited_by or entry_page.created_by,
                                created_at=entry_page.created_at,
                                updated_at=entry_page.last_edited_at,
                                domain="enterprise/notion",
                                confidence=0.85,
                                metadata={
                                    "page_id": entry_page.id,
                                    "database_id": database.id,
                                    "database_title": database.title,
                                },
                            )

                            items_yielded += 1

                            if entry_page.last_edited_at:
                                current = state.cursor
                                new_ts = entry_page.last_edited_at.isoformat()
                                if not current or new_ts > current:
                                    state.cursor = new_ts

                        if not entry_cursor:
                            break

                if not cursor:
                    break

    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs: Any,
    ) -> list:
        """Search Notion content."""
        from aragora.connectors.base import Evidence

        results = []
        cursor = None
        count = 0

        while count < limit:
            items, cursor = await self._search_pages(query=query, start_cursor=cursor)

            for item in items:
                if count >= limit:
                    break

                if item.get("object") == "page":
                    page = self._parse_page(item)
                    content = await self._get_page_content(page.id)

                    results.append(
                        Evidence(
                            id=f"notion-{page.id}",
                            source_type=self.source_type,
                            source_id=page.id,
                            content=content[:2000],
                            title=page.title,
                            url=page.url,
                            confidence=0.8,
                        )
                    )
                    count += 1

                elif item.get("object") == "database":
                    database = self._parse_database(item)
                    results.append(
                        Evidence(
                            id=f"notion-db-{database.id}",
                            source_type=self.source_type,
                            source_id=database.id,
                            content=database.description or database.title,
                            title=database.title,
                            url=database.url,
                            confidence=0.8,
                            metadata={"type": "database"},
                        )
                    )
                    count += 1

            if not cursor:
                break

        return results

    async def fetch(self, evidence_id: str) -> Any | None:
        """Fetch a specific Notion page."""
        from aragora.connectors.base import Evidence

        # Extract page ID
        if evidence_id.startswith("notion-page-"):
            page_id = evidence_id[12:]
        elif evidence_id.startswith("notion-"):
            page_id = evidence_id[7:]
        else:
            page_id = evidence_id

        page = await self._get_page(page_id)
        if not page:
            return None

        content = await self._get_page_content(page.id)

        return Evidence(
            id=evidence_id,
            source_type=self.source_type,
            source_id=page.id,
            content=content,
            title=page.title,
            url=page.url,
            created_at=page.created_at.isoformat() if page.created_at else None,
            confidence=0.85,
        )

    # ==========================================================================
    # Write Operations - Bidirectional Support
    # ==========================================================================

    async def create_page(
        self,
        parent_id: str,
        title: str,
        content: str | None = None,
        parent_type: str = "page_id",
        properties: dict[str, Any] | None = None,
    ) -> NotionPage | None:
        """
        Create a new Notion page.

        Args:
            parent_id: Parent page or database ID
            title: Page title
            content: Optional initial content (plain text, converted to paragraphs)
            parent_type: "page_id" or "database_id"
            properties: Additional properties for database entries

        Returns:
            Created NotionPage, or None if failed
        """
        try:
            # Build page properties
            page_properties: dict[str, Any] = properties or {}

            # Set title property
            page_properties["title"] = {"title": [{"type": "text", "text": {"content": title}}]}

            # Build request body
            body: dict[str, Any] = {
                "parent": {parent_type: parent_id},
                "properties": page_properties,
            }

            # Add content blocks if provided
            if content:
                body["children"] = self._text_to_blocks(content)

            data = await self._api_request("/pages", method="POST", json_data=body)

            page = self._parse_page(data)
            logger.info("[%s] Created page: %s (%s)", self.name, page.title, page.id)

            return page

        except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
            logger.error("[%s] Failed to create page: %s", self.name, e)
            return None

    async def update_page(
        self,
        page_id: str,
        properties: dict[str, Any] | None = None,
        archived: bool | None = None,
    ) -> NotionPage | None:
        """
        Update a Notion page's properties.

        Args:
            page_id: Page ID to update
            properties: Properties to update
            archived: Set True to archive, False to unarchive

        Returns:
            Updated NotionPage, or None if failed
        """
        try:
            body: dict[str, Any] = {}

            if properties:
                body["properties"] = properties

            if archived is not None:
                body["archived"] = archived

            if not body:
                return await self._get_page(page_id)

            data = await self._api_request(
                f"/pages/{page_id}",
                method="PATCH",
                json_data=body,
            )

            page = self._parse_page(data)
            logger.info("[%s] Updated page: %s (%s)", self.name, page.title, page.id)

            return page

        except (RuntimeError, ValueError, KeyError, OSError) as e:
            logger.error("[%s] Failed to update page %s: %s", self.name, page_id, e)
            return None

    async def append_content(
        self,
        page_id: str,
        content: str,
    ) -> bool:
        """
        Append content to a Notion page.

        Args:
            page_id: Page ID to append to
            content: Text content to append (converted to paragraphs)

        Returns:
            True if successful, False otherwise
        """
        try:
            blocks = self._text_to_blocks(content)

            await self._api_request(
                f"/blocks/{page_id}/children",
                method="PATCH",
                json_data={"children": blocks},
            )

            logger.info("[%s] Appended content to page %s", self.name, page_id)
            return True

        except (RuntimeError, ValueError, OSError) as e:
            logger.error("[%s] Failed to append content: %s", self.name, e)
            return False

    async def delete_block(self, block_id: str) -> bool:
        """
        Delete a block from a Notion page.

        Args:
            block_id: Block ID to delete

        Returns:
            True if successful, False otherwise
        """
        try:
            await self._api_request(
                f"/blocks/{block_id}",
                method="DELETE",
            )

            logger.info("[%s] Deleted block %s", self.name, block_id)
            return True

        except (RuntimeError, ValueError, OSError) as e:
            logger.error("[%s] Failed to delete block %s: %s", self.name, block_id, e)
            return False

    async def archive_page(self, page_id: str) -> bool:
        """
        Archive a Notion page (soft delete).

        Args:
            page_id: Page ID to archive

        Returns:
            True if successful, False otherwise
        """
        result = await self.update_page(page_id, archived=True)
        return result is not None

    async def add_database_entry(
        self,
        database_id: str,
        properties: dict[str, Any],
        content: str | None = None,
    ) -> NotionPage | None:
        """
        Add an entry to a Notion database.

        Args:
            database_id: Database ID
            properties: Entry properties matching database schema
            content: Optional page content

        Returns:
            Created entry as NotionPage, or None if failed
        """
        return await self.create_page(
            parent_id=database_id,
            title=properties.get("Name", {})
            .get("title", [{}])[0]
            .get("text", {})
            .get("content", "Untitled"),
            content=content,
            parent_type="database_id",
            properties=properties,
        )

    async def update_database_entry(
        self,
        entry_id: str,
        properties: dict[str, Any],
    ) -> NotionPage | None:
        """
        Update a database entry.

        Args:
            entry_id: Entry page ID
            properties: Properties to update

        Returns:
            Updated entry as NotionPage, or None if failed
        """
        return await self.update_page(entry_id, properties=properties)

    def _text_to_blocks(self, text: str) -> list[dict[str, Any]]:
        """Convert plain text to Notion blocks."""
        blocks = []

        for paragraph in text.split("\n\n"):
            if not paragraph.strip():
                continue

            # Handle headers
            if paragraph.startswith("# "):
                blocks.append(
                    {
                        "type": "heading_1",
                        "heading_1": {
                            "rich_text": [
                                {"type": "text", "text": {"content": paragraph[2:].strip()}}
                            ]
                        },
                    }
                )
            elif paragraph.startswith("## "):
                blocks.append(
                    {
                        "type": "heading_2",
                        "heading_2": {
                            "rich_text": [
                                {"type": "text", "text": {"content": paragraph[3:].strip()}}
                            ]
                        },
                    }
                )
            elif paragraph.startswith("### "):
                blocks.append(
                    {
                        "type": "heading_3",
                        "heading_3": {
                            "rich_text": [
                                {"type": "text", "text": {"content": paragraph[4:].strip()}}
                            ]
                        },
                    }
                )
            # Handle bullet lists
            elif paragraph.startswith("- ") or paragraph.startswith("* "):
                for line in paragraph.split("\n"):
                    if line.startswith(("- ", "* ")):
                        blocks.append(
                            {
                                "type": "bulleted_list_item",
                                "bulleted_list_item": {
                                    "rich_text": [
                                        {"type": "text", "text": {"content": line[2:].strip()}}
                                    ]
                                },
                            }
                        )
            # Handle code blocks
            elif paragraph.startswith("```"):
                lines = paragraph.split("\n")
                language = lines[0][3:].strip() or "plain_text"
                code = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
                blocks.append(
                    {
                        "type": "code",
                        "code": {
                            "rich_text": [{"type": "text", "text": {"content": code}}],
                            "language": language,
                        },
                    }
                )
            # Handle quotes
            elif paragraph.startswith("> "):
                blocks.append(
                    {
                        "type": "quote",
                        "quote": {
                            "rich_text": [
                                {"type": "text", "text": {"content": paragraph[2:].strip()}}
                            ]
                        },
                    }
                )
            # Regular paragraph
            else:
                # Split into chunks if too long (Notion limit is 2000 chars)
                text_content = paragraph.strip()
                while text_content:
                    chunk = text_content[:1900]
                    text_content = text_content[1900:]
                    blocks.append(
                        {
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [{"type": "text", "text": {"content": chunk}}]
                            },
                        }
                    )

        return blocks

    def _build_property(
        self,
        prop_type: str,
        value: Any,
    ) -> dict[str, Any]:
        """Build a Notion property value for database entries.

        Args:
            prop_type: Property type (title, rich_text, number, select, etc.)
            value: The value to set

        Returns:
            Formatted property dictionary
        """
        if prop_type == "title":
            return {"title": [{"type": "text", "text": {"content": str(value)}}]}

        elif prop_type == "rich_text":
            return {"rich_text": [{"type": "text", "text": {"content": str(value)}}]}

        elif prop_type == "number":
            return {"number": float(value) if value else None}

        elif prop_type == "select":
            return {"select": {"name": str(value)} if value else None}

        elif prop_type == "multi_select":
            if isinstance(value, list):
                return {"multi_select": [{"name": str(v)} for v in value]}
            return {"multi_select": [{"name": str(value)}]}

        elif prop_type == "date":
            if isinstance(value, dict):
                return {"date": value}
            return {"date": {"start": str(value)} if value else None}

        elif prop_type == "checkbox":
            return {"checkbox": bool(value)}

        elif prop_type == "url":
            return {"url": str(value) if value else None}

        elif prop_type == "email":
            return {"email": str(value) if value else None}

        elif prop_type == "phone_number":
            return {"phone_number": str(value) if value else None}

        elif prop_type == "status":
            return {"status": {"name": str(value)} if value else None}

        return {}


__all__ = ["NotionConnector", "NotionPage", "NotionDatabase"]
