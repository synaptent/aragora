"""
Atlassian Confluence Enterprise Connector.

Provides full integration with Confluence Cloud and Data Center:
- Space traversal and page indexing
- Content extraction (wiki markup to text)
- Attachment handling
- Comment indexing
- Incremental sync via CQL and timestamps
- Webhook support for real-time updates

Requires Confluence API credentials.
"""

from __future__ import annotations

import asyncio
import base64
import html
import logging
import re
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
class ConfluenceSpace:
    """A Confluence space."""

    id: str
    key: str
    name: str
    type: str  # global, personal
    status: str
    homepage_id: str | None = None


@dataclass
class ConfluencePage:
    """A Confluence page."""

    id: str
    title: str
    space_key: str
    status: str
    body: str = ""
    version: int = 1
    url: str = ""
    created_by: str = ""
    created_at: datetime | None = None
    updated_by: str = ""
    updated_at: datetime | None = None
    parent_id: str | None = None
    labels: list[str] = field(default_factory=list)


class ConfluenceConnector(EnterpriseConnector):
    """
    Enterprise connector for Atlassian Confluence.

    Features:
    - Space and page crawling
    - Wiki markup to plaintext conversion
    - Attachment indexing
    - Comment extraction
    - Label-based filtering
    - Incremental sync via modified timestamps
    - Webhook support for real-time updates

    Authentication:
    - Cloud: API token (email + token)
    - Data Center: Personal access token

    Usage:
        connector = ConfluenceConnector(
            base_url="https://your-domain.atlassian.net/wiki",
            spaces=["ENG", "DOCS"],  # Optional: specific spaces
        )
        result = await connector.sync()
    """

    def __init__(
        self,
        base_url: str,
        spaces: list[str] | None = None,
        include_archived: bool = False,
        include_attachments: bool = True,
        include_comments: bool = True,
        exclude_labels: list[str] | None = None,
        **kwargs: Any,
    ):
        """
        Initialize Confluence connector.

        Args:
            base_url: Confluence base URL (e.g., https://domain.atlassian.net/wiki)
            spaces: Specific space keys to sync (None = all accessible spaces)
            include_archived: Whether to include archived pages
            include_attachments: Whether to index attachments
            include_comments: Whether to index page comments
            exclude_labels: Labels to exclude from indexing
        """
        # Normalize URL
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/wiki"):
            self.base_url += "/wiki"

        # Extract domain for connector ID
        domain = re.search(r"https?://([^/]+)", self.base_url)
        domain_name = domain.group(1).replace(".", "_") if domain else "confluence"

        connector_id = f"confluence_{domain_name}"
        super().__init__(connector_id=connector_id, **kwargs)

        self.spaces = spaces
        self.include_archived = include_archived
        self.include_attachments = include_attachments
        self.include_comments = include_comments
        self.exclude_labels = set(exclude_labels or [])

        # Determine if Cloud or Data Center
        self.is_cloud = "atlassian.net" in self.base_url

        # Cache
        self._spaces_cache: dict[str, ConfluenceSpace] = {}

    @property
    def source_type(self) -> SourceType:
        return SourceType.DOCUMENT

    @property
    def name(self) -> str:
        return f"Confluence ({self.base_url})"

    async def _get_auth_header(self) -> dict[str, str]:
        """Get authentication header."""
        if self.is_cloud:
            email = await self.credentials.get_credential("CONFLUENCE_EMAIL")
            token = await self.credentials.get_credential("CONFLUENCE_API_TOKEN")

            if not email or not token:
                raise ValueError(
                    "Confluence Cloud credentials not configured. "
                    "Set CONFLUENCE_EMAIL and CONFLUENCE_API_TOKEN"
                )

            auth = base64.b64encode(f"{email}:{token}".encode()).decode()
            return {"Authorization": f"Basic {auth}"}
        else:
            token = await self.credentials.get_credential("CONFLUENCE_PAT")

            if not token:
                raise ValueError(
                    "Confluence Data Center credentials not configured. Set CONFLUENCE_PAT"
                )

            return {"Authorization": f"Bearer {token}"}

    async def _api_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a request to Confluence REST API."""
        from aragora.observability.http_client_pool import get_http_pool

        headers = await self._get_auth_header()
        headers["Accept"] = "application/json"

        url = f"{self.base_url}/rest/api{endpoint}"

        pool = get_http_pool()
        async with pool.get_session("confluence") as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_data,
                timeout=60,
            )
            response.raise_for_status()
            content = getattr(response, "content", None)
            if content is None:
                try:
                    return response.json()
                except (ValueError, TypeError):
                    logger.debug(
                        "Confluence response had no content attribute and JSON decode failed; returning {}",
                        exc_info=True,
                    )
                    return {}
            return response.json() if content else {}

    async def _get_spaces(self) -> list[ConfluenceSpace]:
        """Get all accessible spaces."""
        spaces = []
        start = 0
        limit = 100

        for _page in range(_MAX_PAGES):
            params = {
                "start": start,
                "limit": limit,
                "expand": "homepage",
            }

            if not self.include_archived:
                params["status"] = "current"

            data = await self._api_request("/space", params=params)

            for item in data.get("results", []):
                space_key = item.get("key", "")

                # Filter to specific spaces if configured
                if self.spaces and space_key not in self.spaces:
                    continue

                space = ConfluenceSpace(
                    id=str(item.get("id", "")),
                    key=space_key,
                    name=item.get("name", ""),
                    type=item.get("type", "global"),
                    status=item.get("status", "current"),
                    homepage_id=item.get("homepage", {}).get("id"),
                )
                spaces.append(space)
                self._spaces_cache[space_key] = space

            # Check pagination
            if len(data.get("results", [])) < limit:
                break
            start += limit
        else:
            logger.warning(
                "[%s] Pagination limit reached (%s pages) for spaces", self.name, _MAX_PAGES
            )

        return spaces

    async def _get_pages(
        self,
        space_key: str,
        modified_since: datetime | None = None,
    ) -> AsyncIterator[ConfluencePage]:
        """Get pages from a space."""
        start = 0
        limit = 50

        for _page in range(_MAX_PAGES):
            params = {
                "spaceKey": space_key,
                "start": start,
                "limit": limit,
                "expand": "body.storage,version,history,metadata.labels",
            }

            if not self.include_archived:
                params["status"] = "current"

            data = await self._api_request("/content", params=params)

            for item in data.get("results", []):
                # Parse dates
                created_at = None
                updated_at = None
                history = item.get("history", {})

                if history.get("createdDate"):
                    try:
                        created_at = datetime.fromisoformat(
                            history["createdDate"].replace("Z", "+00:00")
                        )
                    except ValueError as e:
                        logger.debug("Invalid createdDate format: %s", e)

                if history.get("lastUpdated", {}).get("when"):
                    try:
                        updated_at = datetime.fromisoformat(
                            history["lastUpdated"]["when"].replace("Z", "+00:00")
                        )
                    except ValueError as e:
                        logger.debug("Invalid lastUpdated format: %s", e)

                # Skip if not modified since last sync
                if modified_since and updated_at and updated_at < modified_since:
                    continue

                # Get labels
                labels = [
                    label.get("name", "")
                    for label in item.get("metadata", {}).get("labels", {}).get("results", [])
                ]

                # Skip pages with excluded labels
                if self.exclude_labels and set(labels) & self.exclude_labels:
                    continue

                # Extract body content
                body_storage = item.get("body", {}).get("storage", {}).get("value", "")
                body_text = self._html_to_text(body_storage)

                yield ConfluencePage(
                    id=item.get("id", ""),
                    title=item.get("title", ""),
                    space_key=space_key,
                    status=item.get("status", "current"),
                    body=body_text,
                    version=item.get("version", {}).get("number", 1),
                    url=f"{self.base_url}{item.get('_links', {}).get('webui', '')}",
                    created_by=history.get("createdBy", {}).get("displayName", ""),
                    created_at=created_at,
                    updated_by=history.get("lastUpdated", {}).get("by", {}).get("displayName", ""),
                    updated_at=updated_at,
                    parent_id=(
                        item.get("ancestors", [{}])[-1].get("id") if item.get("ancestors") else None
                    ),
                    labels=labels,
                )

            # Check pagination
            if len(data.get("results", [])) < limit:
                break
            start += limit
        else:
            logger.warning(
                "[%s] Pagination limit reached (%s pages) for space %s",
                self.name,
                _MAX_PAGES,
                space_key,
            )

    async def _get_page_comments(self, page_id: str) -> list[dict[str, Any]]:
        """Get comments for a page."""
        if not self.include_comments:
            return []

        comments = []
        start = 0
        limit = 50

        for _page in range(_MAX_PAGES):
            params = {
                "start": start,
                "limit": limit,
                "expand": "body.storage,history",
            }

            try:
                data = await self._api_request(f"/content/{page_id}/child/comment", params=params)

                for item in data.get("results", []):
                    body_storage = item.get("body", {}).get("storage", {}).get("value", "")

                    comments.append(
                        {
                            "id": item.get("id", ""),
                            "body": self._html_to_text(body_storage),
                            "author": item.get("history", {})
                            .get("createdBy", {})
                            .get("displayName", ""),
                            "created_at": item.get("history", {}).get("createdDate"),
                        }
                    )

                if len(data.get("results", [])) < limit:
                    break
                start += limit

            except (RuntimeError, ValueError, KeyError, OSError) as e:
                logger.warning("[%s] Failed to get comments for page %s: %s", self.name, page_id, e)
                break

        return comments

    def _html_to_text(self, html_content: str) -> str:
        """Convert HTML/wiki storage format to plain text."""
        if not html_content:
            return ""

        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", html_content)

        # Decode HTML entities
        text = html.unescape(text)

        # Clean up whitespace
        text = re.sub(r"\s+", " ", text).strip()

        return text

    async def sync_items(
        self,
        state: SyncState,
        batch_size: int = 100,
    ) -> AsyncIterator[SyncItem]:
        """
        Yield Confluence pages for syncing.

        Crawls spaces and extracts page content.
        """
        # Parse last sync timestamp from cursor
        modified_since = None
        if state.cursor:
            try:
                modified_since = datetime.fromisoformat(state.cursor)
            except ValueError as e:
                logger.debug("Invalid cursor timestamp, starting fresh sync: %s", e)

        # Get all spaces
        spaces = await self._get_spaces()
        state.items_total = len(spaces)

        items_yielded = 0

        for space in spaces:
            logger.info("[%s] Syncing space: %s", self.name, space.key)

            async for page in self._get_pages(space.key, modified_since):
                # Get comments
                comments = await self._get_page_comments(page.id)
                comments_text = ""
                if comments:
                    comments_text = "\n\nComments:\n" + "\n".join(
                        f"- {c['author']}: {c['body']}" for c in comments
                    )

                full_content = f"# {page.title}\n\n{page.body}{comments_text}"

                yield SyncItem(
                    id=f"confluence-{page.id}",
                    content=full_content[:50000],
                    source_type="document",
                    source_id=f"confluence/{space.key}/{page.id}",
                    title=page.title,
                    url=page.url,
                    author=page.updated_by or page.created_by,
                    created_at=page.created_at,
                    updated_at=page.updated_at,
                    domain="enterprise/confluence",
                    confidence=0.85,
                    metadata={
                        "space_key": space.key,
                        "space_name": space.name,
                        "page_id": page.id,
                        "version": page.version,
                        "parent_id": page.parent_id,
                        "labels": page.labels,
                        "comment_count": len(comments),
                    },
                )

                items_yielded += 1

                # Update cursor to latest modification time
                if page.updated_at:
                    current_cursor = state.cursor
                    if not current_cursor or page.updated_at.isoformat() > current_cursor:
                        state.cursor = page.updated_at.isoformat()

                if items_yielded >= batch_size:
                    await asyncio.sleep(0)

    async def search(
        self,
        query: str,
        limit: int = 10,
        space_key: str | None = None,
        **kwargs: Any,
    ) -> list:
        """Search Confluence content via CQL."""
        from aragora.connectors.base import Evidence

        cql = f'text ~ "{query}"'
        if space_key:
            cql += f' AND space = "{space_key}"'

        params = {
            "cql": cql,
            "limit": limit,
            "expand": "body.storage",
        }

        try:
            data = await self._api_request("/content/search", params=params)

            results = []
            for item in data.get("results", []):
                body = item.get("body", {}).get("storage", {}).get("value", "")

                results.append(
                    Evidence(
                        id=f"confluence-{item.get('id', '')}",
                        source_type=self.source_type,
                        source_id=item.get("id", ""),
                        content=self._html_to_text(body)[:2000],
                        title=item.get("title", ""),
                        url=f"{self.base_url}{item.get('_links', {}).get('webui', '')}",
                        confidence=0.8,
                        metadata={
                            "space_key": item.get("space", {}).get("key", ""),
                            "type": item.get("type", ""),
                        },
                    )
                )

            return results

        except (RuntimeError, ValueError, KeyError, OSError) as e:
            logger.error("[%s] Search failed: %s", self.name, e)
            return []

    async def fetch(self, evidence_id: str) -> Any | None:
        """Fetch a specific Confluence page."""
        from aragora.connectors.base import Evidence

        # Extract page ID
        if evidence_id.startswith("confluence-"):
            page_id = evidence_id[11:]
        else:
            page_id = evidence_id
        if not page_id.isdigit():
            return None

        try:
            data = await self._api_request(
                f"/content/{page_id}",
                params={"expand": "body.storage,version,history,space"},
            )

            body_storage = data.get("body", {}).get("storage", {}).get("value", "")

            return Evidence(
                id=evidence_id,
                source_type=self.source_type,
                source_id=page_id,
                content=self._html_to_text(body_storage),
                title=data.get("title", ""),
                url=f"{self.base_url}{data.get('_links', {}).get('webui', '')}",
                author=data.get("history", {})
                .get("lastUpdated", {})
                .get("by", {})
                .get("displayName", ""),
                created_at=data.get("history", {}).get("createdDate"),
                confidence=0.85,
                metadata={
                    "space_key": data.get("space", {}).get("key", ""),
                    "version": data.get("version", {}).get("number", 1),
                },
            )

        except (RuntimeError, ValueError, KeyError, OSError) as e:
            logger.error("[%s] Fetch failed: %s", self.name, e)
            return None

    async def handle_webhook(self, payload: dict[str, Any]) -> bool:
        """Handle Confluence webhook notification."""
        event = payload.get("webhookEvent", "")
        page = payload.get("page", {})

        logger.info("[%s] Webhook: %s on page %s", self.name, event, page.get("id", "unknown"))

        if event in ["page_created", "page_updated", "page_removed"]:
            # Trigger incremental sync
            asyncio.create_task(self.sync(max_items=10))
            return True

        return False


__all__ = ["ConfluenceConnector", "ConfluenceSpace", "ConfluencePage"]
