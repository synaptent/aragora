"""
Atlassian Jira Enterprise Connector.

Provides full integration with Jira Cloud and Data Center:
- Project traversal and issue indexing
- Issue fields (summary, description, comments, attachments)
- JQL-based filtering and search
- Incremental sync via updated timestamps
- Webhook support for real-time updates

Requires Jira API credentials.
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
class JiraProject:
    """A Jira project."""

    id: str
    key: str
    name: str
    project_type: str  # software, business, service_desk
    lead: str = ""
    description: str = ""


@dataclass
class JiraIssue:
    """A Jira issue."""

    id: str
    key: str
    project_key: str
    summary: str
    description: str = ""
    issue_type: str = ""
    status: str = ""
    priority: str = ""
    assignee: str = ""
    reporter: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    resolved_at: datetime | None = None
    labels: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    fix_versions: list[str] = field(default_factory=list)
    url: str = ""
    parent_key: str | None = None
    story_points: float | None = None


@dataclass
class JiraComment:
    """A Jira issue comment."""

    id: str
    body: str
    author: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class JiraConnector(EnterpriseConnector):
    """
    Enterprise connector for Atlassian Jira.

    Features:
    - Project and issue crawling
    - JQL-based filtering
    - Comment extraction
    - Attachment indexing
    - Label and component filtering
    - Incremental sync via updated timestamps
    - Webhook support for real-time updates

    Authentication:
    - Cloud: API token (email + token)
    - Data Center: Personal access token

    Usage:
        connector = JiraConnector(
            base_url="https://your-domain.atlassian.net",
            projects=["PROJ", "DEV"],  # Optional: specific projects
            jql="status != Done",  # Optional: JQL filter
        )
        result = await connector.sync()
    """

    def __init__(
        self,
        base_url: str,
        projects: list[str] | None = None,
        jql: str | None = None,
        include_subtasks: bool = True,
        include_comments: bool = True,
        include_attachments: bool = False,
        exclude_statuses: list[str] | None = None,
        exclude_types: list[str] | None = None,
        **kwargs: Any,
    ):
        """
        Initialize Jira connector.

        Args:
            base_url: Jira base URL (e.g., https://domain.atlassian.net)
            projects: Specific project keys to sync (None = all accessible projects)
            jql: Additional JQL filter to apply
            include_subtasks: Whether to include subtasks
            include_comments: Whether to index issue comments
            include_attachments: Whether to index attachment metadata
            exclude_statuses: Statuses to exclude from indexing
            exclude_types: Issue types to exclude from indexing
        """
        # Normalize URL
        self.base_url = base_url.rstrip("/")

        # Extract domain for connector ID
        domain = re.search(r"https?://([^/]+)", self.base_url)
        domain_name = domain.group(1).replace(".", "_") if domain else "jira"

        connector_id = f"jira_{domain_name}"
        super().__init__(connector_id=connector_id, **kwargs)

        self.projects = projects
        self.jql = jql
        self.include_subtasks = include_subtasks
        self.include_comments = include_comments
        self.include_attachments = include_attachments
        self.exclude_statuses = set(s.lower() for s in (exclude_statuses or []))
        self.exclude_types = set(t.lower() for t in (exclude_types or []))

        # Determine if Cloud or Data Center
        self.is_cloud = "atlassian.net" in self.base_url

        # Cache
        self._projects_cache: dict[str, JiraProject] = {}

    @property
    def source_type(self) -> SourceType:
        return SourceType.EXTERNAL_API

    @property
    def name(self) -> str:
        return f"Jira ({self.base_url})"

    async def _get_auth_header(self) -> dict[str, str]:
        """Get authentication header."""
        if self.is_cloud:
            email = await self.credentials.get_credential("JIRA_EMAIL")
            token = await self.credentials.get_credential("JIRA_API_TOKEN")

            if not email or not token:
                raise ValueError(
                    "Jira Cloud credentials not configured. Set JIRA_EMAIL and JIRA_API_TOKEN"
                )

            auth = base64.b64encode(f"{email}:{token}".encode()).decode()
            return {"Authorization": f"Basic {auth}"}
        else:
            token = await self.credentials.get_credential("JIRA_PAT")

            if not token:
                raise ValueError("Jira Data Center credentials not configured. Set JIRA_PAT")

            return {"Authorization": f"Bearer {token}"}

    async def _api_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        api_version: str = "3",
    ) -> dict[str, Any]:
        """Make a request to Jira REST API."""
        from aragora.observability.http_client_pool import get_http_pool

        headers = await self._get_auth_header()
        headers["Accept"] = "application/json"
        headers["Content-Type"] = "application/json"

        # Jira Cloud uses /rest/api/3, Data Center uses /rest/api/2
        if not self.is_cloud:
            api_version = "2"

        url = f"{self.base_url}/rest/api/{api_version}{endpoint}"

        pool = get_http_pool()
        async with pool.get_session("jira") as client:
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
                        "Jira response had no content attribute and JSON decode failed; returning {}",
                        exc_info=True,
                    )
                    return {}
            return response.json() if content else {}

    async def _get_projects(self) -> list[JiraProject]:
        """Get all accessible projects."""
        projects = []
        start = 0
        max_results = 50

        for _page in range(_MAX_PAGES):
            params = {
                "startAt": start,
                "maxResults": max_results,
                "expand": "description,lead",
            }

            data = await self._api_request("/project/search", params=params)

            for item in data.get("values", []):
                project_key = item.get("key", "")

                # Filter to specific projects if configured
                if self.projects and project_key not in self.projects:
                    continue

                project = JiraProject(
                    id=str(item.get("id", "")),
                    key=project_key,
                    name=item.get("name", ""),
                    project_type=item.get("projectTypeKey", "software"),
                    lead=item.get("lead", {}).get("displayName", ""),
                    description=item.get("description", "") or "",
                )
                projects.append(project)
                self._projects_cache[project_key] = project

            # Check pagination
            if data.get("isLast", True) or len(data.get("values", [])) < max_results:
                break
            start += max_results
        else:
            logger.warning(
                "[%s] Pagination limit reached (%s pages) for projects", self.name, _MAX_PAGES
            )

        return projects

    async def _search_issues(
        self,
        jql: str,
        start_at: int = 0,
        max_results: int = 50,
    ) -> dict[str, Any]:
        """Search for issues using JQL."""
        params = {
            "jql": jql,
            "startAt": start_at,
            "maxResults": max_results,
            "fields": [
                "summary",
                "description",
                "issuetype",
                "status",
                "priority",
                "assignee",
                "reporter",
                "created",
                "updated",
                "resolutiondate",
                "labels",
                "components",
                "fixVersions",
                "parent",
                "customfield_10016",  # Story points (common field)
            ],
            "expand": "names",
        }

        return await self._api_request("/search", params=params)

    async def _get_issues(
        self,
        project_key: str,
        modified_since: datetime | None = None,
    ) -> AsyncIterator[JiraIssue]:
        """Get issues from a project."""
        # Build JQL
        jql_parts = [f'project = "{project_key}"']

        if modified_since:
            # Format: 2024-01-15 14:30
            ts_str = modified_since.strftime("%Y-%m-%d %H:%M")
            jql_parts.append(f'updated >= "{ts_str}"')

        if not self.include_subtasks:
            jql_parts.append("issuetype not in subtaskIssueTypes()")

        if self.jql:
            jql_parts.append(f"({self.jql})")

        jql = " AND ".join(jql_parts)
        jql += " ORDER BY updated ASC"

        start_at = 0
        max_results = 50

        for _page in range(_MAX_PAGES):
            data = await self._search_issues(jql, start_at, max_results)

            for item in data.get("issues", []):
                fields = item.get("fields", {})

                # Skip excluded statuses
                status = fields.get("status", {}).get("name", "")
                if status.lower() in self.exclude_statuses:
                    continue

                # Skip excluded types
                issue_type = fields.get("issuetype", {}).get("name", "")
                if issue_type.lower() in self.exclude_types:
                    continue

                # Parse dates
                created_at = None
                updated_at = None
                resolved_at = None

                if fields.get("created"):
                    try:
                        created_at = datetime.fromisoformat(
                            fields["created"].replace("Z", "+00:00")
                        )
                    except ValueError as e:
                        logger.debug("Failed to parse datetime value: %s", e)

                if fields.get("updated"):
                    try:
                        updated_at = datetime.fromisoformat(
                            fields["updated"].replace("Z", "+00:00")
                        )
                    except ValueError as e:
                        logger.debug("Failed to parse datetime value: %s", e)

                if fields.get("resolutiondate"):
                    try:
                        resolved_at = datetime.fromisoformat(
                            fields["resolutiondate"].replace("Z", "+00:00")
                        )
                    except ValueError as e:
                        logger.debug("Failed to parse datetime value: %s", e)

                # Extract description (handle ADF format in Cloud)
                description = ""
                desc_field = fields.get("description")
                if desc_field:
                    if isinstance(desc_field, str):
                        description = desc_field
                    elif isinstance(desc_field, dict):
                        # Atlassian Document Format - extract text
                        description = self._adf_to_text(desc_field)

                yield JiraIssue(
                    id=item.get("id", ""),
                    key=item.get("key", ""),
                    project_key=project_key,
                    summary=fields.get("summary", ""),
                    description=description,
                    issue_type=issue_type,
                    status=status,
                    priority=fields.get("priority", {}).get("name", ""),
                    assignee=(
                        fields.get("assignee", {}).get("displayName", "")
                        if fields.get("assignee")
                        else ""
                    ),
                    reporter=(
                        fields.get("reporter", {}).get("displayName", "")
                        if fields.get("reporter")
                        else ""
                    ),
                    created_at=created_at,
                    updated_at=updated_at,
                    resolved_at=resolved_at,
                    labels=fields.get("labels", []),
                    components=[c.get("name", "") for c in fields.get("components", [])],
                    fix_versions=[v.get("name", "") for v in fields.get("fixVersions", [])],
                    url=f"{self.base_url}/browse/{item.get('key', '')}",
                    parent_key=(
                        fields.get("parent", {}).get("key") if fields.get("parent") else None
                    ),
                    story_points=fields.get("customfield_10016"),
                )

            # Check pagination
            total = data.get("total", 0)
            if start_at + max_results >= total:
                break
            start_at += max_results
        else:
            logger.warning(
                "[%s] Pagination limit reached (%s pages) for issues", self.name, _MAX_PAGES
            )

    async def _get_issue_comments(self, issue_key: str) -> list[JiraComment]:
        """Get comments for an issue."""
        if not self.include_comments:
            return []

        comments = []
        start_at = 0
        max_results = 50

        for _page in range(_MAX_PAGES):
            try:
                data = await self._api_request(
                    f"/issue/{issue_key}/comment",
                    params={"startAt": start_at, "maxResults": max_results},
                )

                for item in data.get("comments", []):
                    # Handle ADF format for body
                    body = ""
                    body_field = item.get("body")
                    if body_field:
                        if isinstance(body_field, str):
                            body = body_field
                        elif isinstance(body_field, dict):
                            body = self._adf_to_text(body_field)

                    created_at = None
                    if item.get("created"):
                        try:
                            created_at = datetime.fromisoformat(
                                item["created"].replace("Z", "+00:00")
                            )
                        except ValueError as e:
                            logger.debug("Failed to parse datetime value: %s", e)

                    updated_at = None
                    if item.get("updated"):
                        try:
                            updated_at = datetime.fromisoformat(
                                item["updated"].replace("Z", "+00:00")
                            )
                        except ValueError as e:
                            logger.debug("Failed to parse datetime value: %s", e)

                    comments.append(
                        JiraComment(
                            id=item.get("id", ""),
                            body=body,
                            author=item.get("author", {}).get("displayName", ""),
                            created_at=created_at,
                            updated_at=updated_at,
                        )
                    )

                total = data.get("total", 0)
                if start_at + max_results >= total:
                    break
                start_at += max_results

            except (RuntimeError, ValueError, KeyError, OSError, Exception) as e:
                logger.warning("[%s] Failed to get comments for %s: %s", self.name, issue_key, e)
                break

        return comments

    def _adf_to_text(self, adf: dict[str, Any]) -> str:
        """Convert Atlassian Document Format to plain text."""
        if not adf:
            return ""

        def extract_text(node: Any) -> str:
            if isinstance(node, str):
                return node
            if not isinstance(node, dict):
                return ""

            text_parts = []

            # Direct text content
            if node.get("type") == "text":
                text_parts.append(node.get("text", ""))

            # Recurse into content array
            for child in node.get("content", []):
                text_parts.append(extract_text(child))

            return " ".join(text_parts)

        text = extract_text(adf)
        # Clean up whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _html_to_text(self, html_content: str) -> str:
        """Convert HTML to plain text (for Data Center)."""
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
        Yield Jira issues for syncing.

        Crawls projects and extracts issue content.
        """
        # Parse last sync timestamp from cursor
        modified_since = None
        if state.cursor:
            try:
                modified_since = datetime.fromisoformat(state.cursor)
            except ValueError:
                logger.debug("Invalid cursor timestamp, starting fresh sync")

        # Get all projects
        projects = await self._get_projects()
        state.items_total = len(projects)

        items_yielded = 0

        for project in projects:
            logger.info("[%s] Syncing project: %s", self.name, project.key)

            async for issue in self._get_issues(project.key, modified_since):
                # Get comments
                comments = await self._get_issue_comments(issue.key)
                comments_text = ""
                if comments:
                    comments_text = "\n\nComments:\n" + "\n".join(
                        f"- {c.author}: {c.body}" for c in comments
                    )

                # Build full content
                content_parts = [
                    f"# [{issue.key}] {issue.summary}",
                    f"\nType: {issue.issue_type}",
                    f"Status: {issue.status}",
                    f"Priority: {issue.priority}",
                ]

                if issue.assignee:
                    content_parts.append(f"Assignee: {issue.assignee}")
                if issue.reporter:
                    content_parts.append(f"Reporter: {issue.reporter}")
                if issue.labels:
                    content_parts.append(f"Labels: {', '.join(issue.labels)}")
                if issue.components:
                    content_parts.append(f"Components: {', '.join(issue.components)}")
                if issue.fix_versions:
                    content_parts.append(f"Fix Versions: {', '.join(issue.fix_versions)}")
                if issue.story_points:
                    content_parts.append(f"Story Points: {issue.story_points}")

                content_parts.append(f"\n## Description\n{issue.description}")
                content_parts.append(comments_text)

                full_content = "\n".join(content_parts)

                yield SyncItem(
                    id=f"jira-{issue.key}",
                    content=full_content[:50000],
                    source_type="issue",
                    source_id=f"jira/{project.key}/{issue.key}",
                    title=f"[{issue.key}] {issue.summary}",
                    url=issue.url,
                    author=issue.reporter or issue.assignee,
                    created_at=issue.created_at,
                    updated_at=issue.updated_at,
                    domain="enterprise/jira",
                    confidence=0.85,
                    metadata={
                        "project_key": project.key,
                        "project_name": project.name,
                        "issue_key": issue.key,
                        "issue_type": issue.issue_type,
                        "status": issue.status,
                        "priority": issue.priority,
                        "assignee": issue.assignee,
                        "labels": issue.labels,
                        "components": issue.components,
                        "parent_key": issue.parent_key,
                        "story_points": issue.story_points,
                        "comment_count": len(comments),
                    },
                )

                items_yielded += 1

                # Update cursor to latest modification time
                if issue.updated_at:
                    current_cursor = state.cursor
                    if not current_cursor or issue.updated_at.isoformat() > current_cursor:
                        state.cursor = issue.updated_at.isoformat()

                if items_yielded >= batch_size:
                    await asyncio.sleep(0)

    async def search(
        self,
        query: str,
        limit: int = 10,
        project_key: str | None = None,
        **kwargs: Any,
    ) -> list:
        """Search Jira issues via JQL text search."""
        from aragora.connectors.base import Evidence

        jql_parts = [f'text ~ "{query}"']
        if project_key:
            jql_parts.append(f'project = "{project_key}"')

        jql = " AND ".join(jql_parts)

        try:
            data = await self._search_issues(jql, max_results=limit)

            results = []
            for item in data.get("issues", []):
                fields = item.get("fields", {})

                # Extract description
                description = ""
                desc_field = fields.get("description")
                if desc_field:
                    if isinstance(desc_field, str):
                        description = desc_field
                    elif isinstance(desc_field, dict):
                        description = self._adf_to_text(desc_field)

                results.append(
                    Evidence(
                        id=f"jira-{item.get('key', '')}",
                        source_type=self.source_type,
                        source_id=item.get("key", ""),
                        content=f"{fields.get('summary', '')}\n\n{description[:1500]}",
                        title=f"[{item.get('key', '')}] {fields.get('summary', '')}",
                        url=f"{self.base_url}/browse/{item.get('key', '')}",
                        confidence=0.8,
                        metadata={
                            "issue_type": fields.get("issuetype", {}).get("name", ""),
                            "status": fields.get("status", {}).get("name", ""),
                            "priority": fields.get("priority", {}).get("name", ""),
                        },
                    )
                )

            return results

        except (RuntimeError, ValueError, KeyError, OSError) as e:
            logger.error("[%s] Search failed: %s", self.name, e)
            return []

    async def fetch(self, evidence_id: str) -> Any | None:
        """Fetch a specific Jira issue."""
        from aragora.connectors.base import Evidence

        # Extract issue key
        if evidence_id.startswith("jira-"):
            issue_key = evidence_id[5:]
        else:
            issue_key = evidence_id
        parts = issue_key.split("-", 1)
        if len(parts) != 2 or not parts[0] or not parts[1].isdigit():
            return None

        try:
            data = await self._api_request(
                f"/issue/{issue_key}",
                params={"expand": "renderedFields"},
            )

            fields = data.get("fields", {})

            # Extract description
            description = ""
            desc_field = fields.get("description")
            if desc_field:
                if isinstance(desc_field, str):
                    description = desc_field
                elif isinstance(desc_field, dict):
                    description = self._adf_to_text(desc_field)

            return Evidence(
                id=evidence_id,
                source_type=self.source_type,
                source_id=issue_key,
                content=f"{fields.get('summary', '')}\n\n{description}",
                title=f"[{issue_key}] {fields.get('summary', '')}",
                url=f"{self.base_url}/browse/{issue_key}",
                author=(
                    fields.get("reporter", {}).get("displayName", "")
                    if fields.get("reporter")
                    else ""
                ),
                created_at=fields.get("created"),
                confidence=0.85,
                metadata={
                    "issue_type": fields.get("issuetype", {}).get("name", ""),
                    "status": fields.get("status", {}).get("name", ""),
                    "priority": fields.get("priority", {}).get("name", ""),
                    "assignee": (
                        fields.get("assignee", {}).get("displayName", "")
                        if fields.get("assignee")
                        else ""
                    ),
                },
            )

        except (RuntimeError, ValueError, KeyError, OSError) as e:
            logger.error("[%s] Fetch failed: %s", self.name, e)
            return None

    async def handle_webhook(self, payload: dict[str, Any]) -> bool:
        """Handle Jira webhook notification."""
        event = payload.get("webhookEvent", "")
        issue = payload.get("issue", {})

        logger.info("[%s] Webhook: %s on issue %s", self.name, event, issue.get("key", "unknown"))

        # Handle issue events
        if event.startswith("jira:issue_"):
            # Trigger incremental sync
            asyncio.create_task(self.sync(max_items=10))
            return True

        # Handle comment events
        if event.startswith("comment_"):
            asyncio.create_task(self.sync(max_items=10))
            return True

        return False

    def get_webhook_secret(self) -> str | None:
        """Get webhook secret for signature verification."""
        import os

        return os.environ.get("JIRA_WEBHOOK_SECRET")


__all__ = ["JiraConnector", "JiraProject", "JiraIssue", "JiraComment"]
