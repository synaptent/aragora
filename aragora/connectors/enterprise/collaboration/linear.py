"""
Linear Connector.

Integration with Linear API (GraphQL):
- Issues (create, update, search, transitions)
- Projects and cycles
- Teams and users
- Labels and states
- Comments and attachments
- Roadmaps and initiatives

Requires Linear API key.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from collections.abc import AsyncIterator

import httpx

from aragora.connectors.base import Evidence
from aragora.connectors.enterprise.base import EnterpriseConnector, SyncItem, SyncResult, SyncState
from aragora.reasoning.provenance import SourceType

logger = logging.getLogger(__name__)

_MAX_PAGES = 1000  # Safety cap for pagination loops


class IssuePriority(int, Enum):
    """Issue priority levels."""

    NO_PRIORITY = 0
    URGENT = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4


class IssueStateType(str, Enum):
    """Issue state type categories."""

    BACKLOG = "backlog"
    UNSTARTED = "unstarted"
    STARTED = "started"
    COMPLETED = "completed"
    CANCELED = "canceled"


@dataclass
class LinearCredentials:
    """Linear API credentials."""

    api_key: str
    base_url: str = "https://api.linear.app/graphql"


@dataclass
class LinearTeam:
    """Linear team."""

    id: str
    name: str
    key: str
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    private: bool = False
    timezone: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> LinearTeam:
        """Create from API response."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            key=data.get("key", ""),
            description=data.get("description"),
            icon=data.get("icon"),
            color=data.get("color"),
            private=data.get("private", False),
            timezone=data.get("timezone"),
        )


@dataclass
class LinearUser:
    """Linear user."""

    id: str
    name: str
    display_name: str
    email: str
    active: bool = True
    admin: bool = False
    avatar_url: str | None = None
    guest: bool = False
    created_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> LinearUser:
        """Create from API response."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            display_name=data.get("displayName", data.get("name", "")),
            email=data.get("email", ""),
            active=data.get("active", True),
            admin=data.get("admin", False),
            avatar_url=data.get("avatarUrl"),
            guest=data.get("guest", False),
            created_at=_parse_datetime(data.get("createdAt")),
        )


@dataclass
class IssueState:
    """Issue workflow state."""

    id: str
    name: str
    type: IssueStateType
    color: str
    position: float = 0
    description: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> IssueState:
        """Create from API response."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            type=IssueStateType(data.get("type", "backlog")),
            color=data.get("color", "#000000"),
            position=data.get("position", 0),
            description=data.get("description"),
        )


@dataclass
class Label:
    """Issue label."""

    id: str
    name: str
    color: str
    description: str | None = None
    parent_id: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Label:
        """Create from API response."""
        parent = data.get("parent", {})
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            color=data.get("color", "#000000"),
            description=data.get("description"),
            parent_id=parent.get("id") if parent else None,
        )


@dataclass
class Project:
    """Linear project."""

    id: str
    name: str
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    state: str = "planned"
    progress: float = 0
    target_date: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    lead_id: str | None = None
    team_ids: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Project:
        """Create from API response."""
        lead = data.get("lead", {})
        teams = data.get("teams", {}).get("nodes", [])
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description"),
            icon=data.get("icon"),
            color=data.get("color"),
            state=data.get("state", "planned"),
            progress=data.get("progress", 0),
            target_date=_parse_datetime(data.get("targetDate")),
            started_at=_parse_datetime(data.get("startedAt")),
            completed_at=_parse_datetime(data.get("completedAt")),
            lead_id=lead.get("id") if lead else None,
            team_ids=[t.get("id", "") for t in teams],
            created_at=_parse_datetime(data.get("createdAt")),
            updated_at=_parse_datetime(data.get("updatedAt")),
        )


@dataclass
class Cycle:
    """Linear cycle (sprint)."""

    id: str
    number: int
    name: str | None = None
    description: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    completed_at: datetime | None = None
    progress: float = 0
    scope_target: int | None = None
    team_id: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Cycle:
        """Create from API response."""
        team = data.get("team", {})
        return cls(
            id=data.get("id", ""),
            number=data.get("number", 0),
            name=data.get("name"),
            description=data.get("description"),
            starts_at=_parse_datetime(data.get("startsAt")),
            ends_at=_parse_datetime(data.get("endsAt")),
            completed_at=_parse_datetime(data.get("completedAt")),
            progress=data.get("progress", 0),
            scope_target=data.get("scopeTarget"),
            team_id=team.get("id") if team else None,
        )


@dataclass
class Comment:
    """Issue comment."""

    id: str
    body: str
    user_id: str | None = None
    user_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Comment:
        """Create from API response."""
        user = data.get("user", {})
        return cls(
            id=data.get("id", ""),
            body=data.get("body", ""),
            user_id=user.get("id") if user else None,
            user_name=user.get("name") if user else None,
            created_at=_parse_datetime(data.get("createdAt")),
            updated_at=_parse_datetime(data.get("updatedAt")),
        )


@dataclass
class LinearIssue:
    """Linear issue."""

    id: str
    identifier: str  # e.g., "ENG-123"
    title: str
    description: str | None = None
    priority: IssuePriority = IssuePriority.NO_PRIORITY
    estimate: int | None = None
    state_id: str | None = None
    state_name: str | None = None
    state_type: IssueStateType | None = None
    team_id: str | None = None
    team_key: str | None = None
    assignee_id: str | None = None
    assignee_name: str | None = None
    creator_id: str | None = None
    project_id: str | None = None
    cycle_id: str | None = None
    parent_id: str | None = None
    due_date: datetime | None = None
    label_ids: list[str] = field(default_factory=list)
    subscriber_ids: list[str] = field(default_factory=list)
    url: str | None = None
    branch_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    canceled_at: datetime | None = None
    archived_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> LinearIssue:
        """Create from API response."""
        state = data.get("state", {})
        team = data.get("team", {})
        assignee = data.get("assignee", {})
        creator = data.get("creator", {})
        project = data.get("project", {})
        cycle = data.get("cycle", {})
        parent = data.get("parent", {})
        labels = data.get("labels", {}).get("nodes", [])
        subscribers = data.get("subscribers", {}).get("nodes", [])

        return cls(
            id=data.get("id", ""),
            identifier=data.get("identifier", ""),
            title=data.get("title", ""),
            description=data.get("description"),
            priority=IssuePriority(data.get("priority", 0)),
            estimate=data.get("estimate"),
            state_id=state.get("id") if state else None,
            state_name=state.get("name") if state else None,
            state_type=IssueStateType(state["type"]) if state and state.get("type") else None,
            team_id=team.get("id") if team else None,
            team_key=team.get("key") if team else None,
            assignee_id=assignee.get("id") if assignee else None,
            assignee_name=assignee.get("name") if assignee else None,
            creator_id=creator.get("id") if creator else None,
            project_id=project.get("id") if project else None,
            cycle_id=cycle.get("id") if cycle else None,
            parent_id=parent.get("id") if parent else None,
            due_date=_parse_datetime(data.get("dueDate")),
            label_ids=[lb.get("id", "") for lb in labels],
            subscriber_ids=[s.get("id", "") for s in subscribers],
            url=data.get("url"),
            branch_name=data.get("branchName"),
            created_at=_parse_datetime(data.get("createdAt")),
            updated_at=_parse_datetime(data.get("updatedAt")),
            completed_at=_parse_datetime(data.get("completedAt")),
            canceled_at=_parse_datetime(data.get("canceledAt")),
            archived_at=_parse_datetime(data.get("archivedAt")),
        )


class LinearError(Exception):
    """Linear API error."""

    def __init__(self, message: str, errors: list | None = None):
        super().__init__(message)
        self.errors = errors or []


class LinearConnector(EnterpriseConnector):
    """
    Linear API connector.

    Extends EnterpriseConnector to provide integration with Linear for:
    - Issue management (create, update, search)
    - Project and cycle tracking
    - Team and user management
    - Labels and workflow states
    """

    _linear_credentials: LinearCredentials
    _client: httpx.AsyncClient | None

    def __init__(self, credentials: LinearCredentials, tenant_id: str = "default"):
        super().__init__(connector_id="linear", tenant_id=tenant_id)
        self._linear_credentials = credentials
        self._client = None

    @property
    def name(self) -> str:
        """Human-readable name for this connector."""
        return "Linear"

    @property
    def source_type(self) -> SourceType:
        """The source type for this connector."""
        return SourceType.EXTERNAL_API

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": self._linear_credentials.api_key,
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def _graphql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute GraphQL query."""
        client = await self._get_client()
        response = await client.post(
            self._linear_credentials.base_url,
            json={"query": query, "variables": variables or {}},
        )

        if response.status_code >= 400:
            raise LinearError(f"HTTP {response.status_code}: {response.text}")

        data = response.json()

        if "errors" in data:
            errors = data["errors"]
            message = errors[0].get("message", "Unknown error") if errors else "Unknown error"
            raise LinearError(message, errors)

        return data.get("data", {})

    # =========================================================================
    # Issues
    # =========================================================================

    async def get_issues(
        self,
        team_id: str | None = None,
        project_id: str | None = None,
        assignee_id: str | None = None,
        state_type: IssueStateType | None = None,
        first: int = 50,
        after: str | None = None,
    ) -> tuple[list[LinearIssue], str | None]:
        """Get issues with optional filtering. Returns (issues, end_cursor)."""
        filters = []
        if team_id:
            filters.append(f'team: {{ id: {{ eq: "{team_id}" }} }}')
        if project_id:
            filters.append(f'project: {{ id: {{ eq: "{project_id}" }} }}')
        if assignee_id:
            filters.append(f'assignee: {{ id: {{ eq: "{assignee_id}" }} }}')
        if state_type:
            filters.append(f'state: {{ type: {{ eq: "{state_type.value}" }} }}')

        filter_str = ", ".join(filters) if filters else ""

        query = f"""
        query GetIssues($first: Int!, $after: String) {{
            issues(
                first: $first
                after: $after
                {f"filter: {{ {filter_str} }}" if filter_str else ""}
                orderBy: updatedAt
            ) {{
                nodes {{
                    id
                    identifier
                    title
                    description
                    priority
                    estimate
                    url
                    branchName
                    dueDate
                    createdAt
                    updatedAt
                    completedAt
                    canceledAt
                    archivedAt
                    state {{ id name type }}
                    team {{ id key }}
                    assignee {{ id name }}
                    creator {{ id }}
                    project {{ id }}
                    cycle {{ id }}
                    parent {{ id }}
                    labels {{ nodes {{ id }} }}
                    subscribers {{ nodes {{ id }} }}
                }}
                pageInfo {{
                    hasNextPage
                    endCursor
                }}
            }}
        }}
        """

        data = await self._graphql(query, {"first": first, "after": after})
        issues_data = data.get("issues", {})
        issues = [LinearIssue.from_api(i) for i in issues_data.get("nodes", [])]
        page_info = issues_data.get("pageInfo", {})
        end_cursor = page_info.get("endCursor") if page_info.get("hasNextPage") else None

        return issues, end_cursor

    async def get_issue(self, issue_id: str) -> LinearIssue:
        """Get a single issue by ID or identifier."""
        query = """
        query GetIssue($id: String!) {
            issue(id: $id) {
                id
                identifier
                title
                description
                priority
                estimate
                url
                branchName
                dueDate
                createdAt
                updatedAt
                completedAt
                canceledAt
                archivedAt
                state { id name type }
                team { id key }
                assignee { id name }
                creator { id }
                project { id }
                cycle { id }
                parent { id }
                labels { nodes { id } }
                subscribers { nodes { id } }
            }
        }
        """

        data = await self._graphql(query, {"id": issue_id})
        return LinearIssue.from_api(data.get("issue", {}))

    async def create_issue(
        self,
        team_id: str,
        title: str,
        description: str | None = None,
        priority: IssuePriority | None = None,
        state_id: str | None = None,
        assignee_id: str | None = None,
        project_id: str | None = None,
        cycle_id: str | None = None,
        parent_id: str | None = None,
        label_ids: list[str] | None = None,
        estimate: int | None = None,
        due_date: datetime | None = None,
    ) -> LinearIssue:
        """Create a new issue."""
        mutation = """
        mutation CreateIssue($input: IssueCreateInput!) {
            issueCreate(input: $input) {
                success
                issue {
                    id
                    identifier
                    title
                    description
                    priority
                    estimate
                    url
                    branchName
                    dueDate
                    createdAt
                    updatedAt
                    state { id name type }
                    team { id key }
                    assignee { id name }
                    creator { id }
                    project { id }
                    cycle { id }
                    parent { id }
                    labels { nodes { id } }
                }
            }
        }
        """

        input_data: dict[str, Any] = {
            "teamId": team_id,
            "title": title,
        }

        if description:
            input_data["description"] = description
        if priority is not None:
            input_data["priority"] = priority.value
        if state_id:
            input_data["stateId"] = state_id
        if assignee_id:
            input_data["assigneeId"] = assignee_id
        if project_id:
            input_data["projectId"] = project_id
        if cycle_id:
            input_data["cycleId"] = cycle_id
        if parent_id:
            input_data["parentId"] = parent_id
        if label_ids:
            input_data["labelIds"] = label_ids
        if estimate is not None:
            input_data["estimate"] = estimate
        if due_date:
            input_data["dueDate"] = due_date.strftime("%Y-%m-%d")

        data = await self._graphql(mutation, {"input": input_data})
        return LinearIssue.from_api(data.get("issueCreate", {}).get("issue", {}))

    async def update_issue(
        self,
        issue_id: str,
        title: str | None = None,
        description: str | None = None,
        priority: IssuePriority | None = None,
        state_id: str | None = None,
        assignee_id: str | None = None,
        project_id: str | None = None,
        cycle_id: str | None = None,
        label_ids: list[str] | None = None,
        estimate: int | None = None,
        due_date: datetime | None = None,
    ) -> LinearIssue:
        """Update an issue."""
        mutation = """
        mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
            issueUpdate(id: $id, input: $input) {
                success
                issue {
                    id
                    identifier
                    title
                    description
                    priority
                    estimate
                    url
                    branchName
                    dueDate
                    createdAt
                    updatedAt
                    completedAt
                    state { id name type }
                    team { id key }
                    assignee { id name }
                    creator { id }
                    project { id }
                    cycle { id }
                    parent { id }
                    labels { nodes { id } }
                }
            }
        }
        """

        input_data: dict[str, Any] = {}

        if title is not None:
            input_data["title"] = title
        if description is not None:
            input_data["description"] = description
        if priority is not None:
            input_data["priority"] = priority.value
        if state_id is not None:
            input_data["stateId"] = state_id
        if assignee_id is not None:
            input_data["assigneeId"] = assignee_id
        if project_id is not None:
            input_data["projectId"] = project_id
        if cycle_id is not None:
            input_data["cycleId"] = cycle_id
        if label_ids is not None:
            input_data["labelIds"] = label_ids
        if estimate is not None:
            input_data["estimate"] = estimate
        if due_date is not None:
            input_data["dueDate"] = due_date.strftime("%Y-%m-%d")

        data = await self._graphql(mutation, {"id": issue_id, "input": input_data})
        return LinearIssue.from_api(data.get("issueUpdate", {}).get("issue", {}))

    async def archive_issue(self, issue_id: str) -> bool:
        """Archive an issue."""
        mutation = """
        mutation ArchiveIssue($id: String!) {
            issueArchive(id: $id) {
                success
            }
        }
        """

        data = await self._graphql(mutation, {"id": issue_id})
        return data.get("issueArchive", {}).get("success", False)

    async def search_issues(self, query: str, first: int = 50) -> list[LinearIssue]:
        """Search issues by text."""
        gql = """
        query SearchIssues($query: String!, $first: Int!) {
            issueSearch(query: $query, first: $first) {
                nodes {
                    id
                    identifier
                    title
                    description
                    priority
                    estimate
                    url
                    branchName
                    dueDate
                    createdAt
                    updatedAt
                    completedAt
                    state { id name type }
                    team { id key }
                    assignee { id name }
                    creator { id }
                    project { id }
                    cycle { id }
                    labels { nodes { id } }
                }
            }
        }
        """

        data = await self._graphql(gql, {"query": query, "first": first})
        return [LinearIssue.from_api(i) for i in data.get("issueSearch", {}).get("nodes", [])]

    # =========================================================================
    # Comments
    # =========================================================================

    async def get_issue_comments(self, issue_id: str) -> list[Comment]:
        """Get comments for an issue."""
        query = """
        query GetComments($issueId: String!) {
            issue(id: $issueId) {
                comments {
                    nodes {
                        id
                        body
                        createdAt
                        updatedAt
                        user { id name }
                    }
                }
            }
        }
        """

        data = await self._graphql(query, {"issueId": issue_id})
        comments_data = data.get("issue", {}).get("comments", {}).get("nodes", [])
        return [Comment.from_api(c) for c in comments_data]

    async def add_comment(self, issue_id: str, body: str) -> Comment:
        """Add a comment to an issue."""
        mutation = """
        mutation AddComment($input: CommentCreateInput!) {
            commentCreate(input: $input) {
                success
                comment {
                    id
                    body
                    createdAt
                    updatedAt
                    user { id name }
                }
            }
        }
        """

        data = await self._graphql(mutation, {"input": {"issueId": issue_id, "body": body}})
        return Comment.from_api(data.get("commentCreate", {}).get("comment", {}))

    # =========================================================================
    # Teams
    # =========================================================================

    async def get_teams(self) -> list[LinearTeam]:
        """Get all teams."""
        query = """
        query GetTeams {
            teams {
                nodes {
                    id
                    name
                    key
                    description
                    icon
                    color
                    private
                    timezone
                }
            }
        }
        """

        data = await self._graphql(query)
        return [LinearTeam.from_api(t) for t in data.get("teams", {}).get("nodes", [])]

    async def get_team(self, team_id: str) -> LinearTeam:
        """Get a single team."""
        query = """
        query GetTeam($id: String!) {
            team(id: $id) {
                id
                name
                key
                description
                icon
                color
                private
                timezone
            }
        }
        """

        data = await self._graphql(query, {"id": team_id})
        return LinearTeam.from_api(data.get("team", {}))

    async def get_team_states(self, team_id: str) -> list[IssueState]:
        """Get workflow states for a team."""
        query = """
        query GetTeamStates($teamId: String!) {
            team(id: $teamId) {
                states {
                    nodes {
                        id
                        name
                        type
                        color
                        position
                        description
                    }
                }
            }
        }
        """

        data = await self._graphql(query, {"teamId": team_id})
        return [
            IssueState.from_api(s) for s in data.get("team", {}).get("states", {}).get("nodes", [])
        ]

    # =========================================================================
    # Projects
    # =========================================================================

    async def get_projects(
        self,
        team_id: str | None = None,
        first: int = 50,
    ) -> list[Project]:
        """Get projects."""
        filter_str = (
            f'filter: {{ accessibleTeams: {{ id: {{ eq: "{team_id}" }} }} }}' if team_id else ""
        )

        query = f"""
        query GetProjects($first: Int!) {{
            projects(first: $first {filter_str}) {{
                nodes {{
                    id
                    name
                    description
                    icon
                    color
                    state
                    progress
                    targetDate
                    startedAt
                    completedAt
                    createdAt
                    updatedAt
                    lead {{ id }}
                    teams {{ nodes {{ id }} }}
                }}
            }}
        }}
        """

        data = await self._graphql(query, {"first": first})
        return [Project.from_api(p) for p in data.get("projects", {}).get("nodes", [])]

    async def get_project(self, project_id: str) -> Project:
        """Get a single project."""
        query = """
        query GetProject($id: String!) {
            project(id: $id) {
                id
                name
                description
                icon
                color
                state
                progress
                targetDate
                startedAt
                completedAt
                createdAt
                updatedAt
                lead { id }
                teams { nodes { id } }
            }
        }
        """

        data = await self._graphql(query, {"id": project_id})
        return Project.from_api(data.get("project", {}))

    # =========================================================================
    # Cycles
    # =========================================================================

    async def get_cycles(self, team_id: str, first: int = 20) -> list[Cycle]:
        """Get cycles for a team."""
        query = """
        query GetCycles($teamId: String!, $first: Int!) {
            team(id: $teamId) {
                cycles(first: $first) {
                    nodes {
                        id
                        number
                        name
                        description
                        startsAt
                        endsAt
                        completedAt
                        progress
                        scopeTarget
                        team { id }
                    }
                }
            }
        }
        """

        data = await self._graphql(query, {"teamId": team_id, "first": first})
        return [Cycle.from_api(c) for c in data.get("team", {}).get("cycles", {}).get("nodes", [])]

    async def get_active_cycle(self, team_id: str) -> Cycle | None:
        """Get the active cycle for a team."""
        query = """
        query GetActiveCycle($teamId: String!) {
            team(id: $teamId) {
                activeCycle {
                    id
                    number
                    name
                    description
                    startsAt
                    endsAt
                    progress
                    scopeTarget
                    team { id }
                }
            }
        }
        """

        data = await self._graphql(query, {"teamId": team_id})
        cycle_data = data.get("team", {}).get("activeCycle")
        return Cycle.from_api(cycle_data) if cycle_data else None

    # =========================================================================
    # Labels
    # =========================================================================

    async def get_labels(self, team_id: str | None = None) -> list[Label]:
        """Get labels, optionally filtered by team."""
        filter_str = f'filter: {{ team: {{ id: {{ eq: "{team_id}" }} }} }}' if team_id else ""

        query = f"""
        query GetLabels {{
            issueLabels({filter_str}) {{
                nodes {{
                    id
                    name
                    color
                    description
                    parent {{ id }}
                }}
            }}
        }}
        """

        data = await self._graphql(query)
        return [Label.from_api(lb) for lb in data.get("issueLabels", {}).get("nodes", [])]

    # =========================================================================
    # Users
    # =========================================================================

    async def get_users(self) -> list[LinearUser]:
        """Get all users in the organization."""
        query = """
        query GetUsers {
            users {
                nodes {
                    id
                    name
                    displayName
                    email
                    active
                    admin
                    avatarUrl
                    guest
                    createdAt
                }
            }
        }
        """

        data = await self._graphql(query)
        return [LinearUser.from_api(u) for u in data.get("users", {}).get("nodes", [])]

    async def get_current_user(self) -> LinearUser:
        """Get the authenticated user."""
        query = """
        query GetViewer {
            viewer {
                id
                name
                displayName
                email
                active
                admin
                avatarUrl
                guest
                createdAt
            }
        }
        """

        data = await self._graphql(query)
        return LinearUser.from_api(data.get("viewer", {}))

    # =========================================================================
    # EnterpriseConnector Implementation
    # =========================================================================

    async def connect(self) -> bool:
        """Establish connection to Linear API."""
        try:
            await self._get_client()
            # Test connection by fetching current user
            await self.get_current_user()
            logger.info("Connected to Linear API")
            return True
        except (LinearError, ValueError, OSError) as e:
            logger.error("Failed to connect to Linear: %s", e)
            return False

    async def disconnect(self) -> None:
        """Close Linear connection."""
        await self.close()

    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs: Any,
    ) -> list[Evidence]:
        """Search Linear for issues matching query.

        Args:
            query: Search query string
            limit: Maximum results
            **kwargs: Additional options (team_id: str)

        Returns:
            List of Evidence objects
        """
        results: list[Evidence] = []

        try:
            issues = await self.search_issues(query, first=limit)

            for issue in issues:
                results.append(
                    Evidence(
                        id=f"linear-issue-{issue.id}",
                        source_type=self.source_type,
                        source_id=issue.identifier,
                        content=f"{issue.title}\n\n{issue.description or ''}",
                        title=f"[{issue.identifier}] {issue.title}",
                        url=issue.url,
                        metadata={
                            "type": "issue",
                            "priority": issue.priority.name,
                            "state": issue.state_name,
                            "team": issue.team_key,
                        },
                    )
                )

        except (LinearError, ValueError, KeyError) as e:
            logger.error("Search failed: %s", e)

        return results[:limit]

    async def fetch(self, evidence_id: str) -> Evidence | None:
        """Fetch a specific piece of evidence by ID.

        Args:
            evidence_id: Evidence ID (format: linear-{type}-{id})

        Returns:
            Evidence object, or None if not found. LinearError, ValueError and
            KeyError are logged and also return None instead of raising.
        """
        try:
            parts = evidence_id.split("-")
            if len(parts) < 3 or parts[0] != "linear":
                return None

            entity_type = parts[1]
            entity_id = "-".join(parts[2:])  # Handle IDs with dashes

            if entity_type == "issue":
                issue = await self.get_issue(entity_id)
                if issue:
                    return Evidence(
                        id=evidence_id,
                        source_type=self.source_type,
                        source_id=issue.identifier,
                        content=f"{issue.title}\n\n{issue.description or ''}",
                        title=f"[{issue.identifier}] {issue.title}",
                        url=issue.url,
                        metadata={
                            "type": "issue",
                            "priority": issue.priority.name,
                            "state": issue.state_name,
                            "team": issue.team_key,
                        },
                    )

            elif entity_type == "project":
                project = await self.get_project(entity_id)
                if project:
                    return Evidence(
                        id=evidence_id,
                        source_type=self.source_type,
                        source_id=project.id,
                        content=f"{project.name}\n\n{project.description or ''}",
                        title=project.name,
                        url=None,
                        metadata={"type": "project", "state": project.state},
                    )

        except (LinearError, ValueError, KeyError) as e:
            logger.error("Failed to fetch %s: %s", evidence_id, e)

        return None

    async def sync_items(
        self,
        state: SyncState,
        batch_size: int = 100,
    ) -> AsyncIterator[SyncItem]:
        """Sync items from Linear for Knowledge Mound.

        Args:
            state: Sync state with cursor/timestamp
            batch_size: Number of items per batch

        Yields:
            SyncItem objects for issues and projects
        """
        since = state.last_sync_at

        # Sync issues
        async for issue in self._paginate_issues(since=since, limit=batch_size):
            yield SyncItem(
                id=f"linear-issue-{issue.id}",
                content=f"[{issue.identifier}] {issue.title}\n\n{issue.description or ''}",
                source_type="linear_issue",
                source_id=issue.id,
                title=issue.title,
                url=issue.url or "",
                updated_at=issue.updated_at,
                created_at=issue.created_at,
                metadata={
                    "type": "issue",
                    "identifier": issue.identifier,
                    "priority": issue.priority.value,
                    "state": issue.state_name,
                    "team": issue.team_key,
                },
            )

        # Sync projects
        async for project in self._paginate_projects(limit=batch_size):
            yield SyncItem(
                id=f"linear-project-{project.id}",
                content=f"{project.name}\n\n{project.description or ''}",
                source_type="linear_project",
                source_id=project.id,
                title=project.name,
                updated_at=project.updated_at,
                created_at=project.created_at,
                metadata={
                    "type": "project",
                    "state": project.state,
                },
            )

    async def _paginate_issues(
        self,
        since: datetime | None = None,
        limit: int = 100,
    ) -> AsyncIterator[LinearIssue]:
        """Paginate through issues.

        Args:
            since: Only issues updated after this time
            limit: Items per page

        Yields:
            LinearIssue objects
        """
        cursor: str | None = None
        for _page in range(_MAX_PAGES):
            issues, end_cursor = await self.get_issues(
                first=limit,
                after=cursor,
            )

            for issue in issues:
                yield issue

            if not end_cursor:
                break
            cursor = end_cursor
        else:
            logger.warning("Pagination safety cap reached for Linear issues")

    async def _paginate_projects(
        self,
        limit: int = 100,
    ) -> AsyncIterator[Project]:
        """Paginate through projects.

        Note: get_projects doesn't support pagination cursor,
        so this yields all projects in one batch.

        Args:
            limit: Items per page

        Yields:
            Project objects
        """
        projects = await self.get_projects(first=limit)

        for project in projects:
            yield project

    async def incremental_sync(
        self,
        state: SyncState | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Perform incremental sync of Linear data.

        Args:
            state: Previous sync state

        Yields:
            Data items as dictionaries
        """
        sync_state = state or SyncState(connector_id=self.name)

        async for item in self.sync_items(sync_state, batch_size=100):
            yield {
                "type": item.metadata.get("type", "unknown"),
                "id": item.id,
                "data": item.metadata,
                "content": item.content,
            }

    async def full_sync(self) -> SyncResult:
        """Perform full sync of Linear data."""
        start_time = datetime.now(timezone.utc)
        items_synced = 0
        errors: list[str] = []

        try:
            sync_state = SyncState(connector_id=self.name)
            async for _ in self.incremental_sync(sync_state):
                items_synced += 1
        except (LinearError, ValueError, OSError) as e:
            logger.warning("Linear sync failed: %s", e)
            errors.append("Linear sync operation failed")

        duration = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

        return SyncResult(
            connector_id=self.name,
            success=len(errors) == 0,
            items_synced=items_synced,
            items_updated=0,
            items_skipped=0,
            items_failed=len(errors),
            duration_ms=duration,
            errors=errors,
        )

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> LinearConnector:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime string."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def get_mock_issue() -> LinearIssue:
    """Get a mock issue for testing."""
    return LinearIssue(
        id="issue-123",
        identifier="ENG-42",
        title="Implement user authentication",
        description="Add OAuth2 support for user login",
        priority=IssuePriority.HIGH,
        state_name="In Progress",
        state_type=IssueStateType.STARTED,
        team_key="ENG",
        created_at=datetime.now(),
    )


def get_mock_team() -> LinearTeam:
    """Get a mock team for testing."""
    return LinearTeam(
        id="team-123",
        name="Engineering",
        key="ENG",
        description="Core engineering team",
    )
