"""
Zendesk Support Connector.

Integration with Zendesk Support API:
- Tickets (CRUD, comments, status)
- Users (customers, agents)
- Organizations
- Views and macros
- Automations and triggers
- SLA policies

Requires Zendesk subdomain and API token.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class TicketStatus(str, Enum):
    """Ticket status."""

    NEW = "new"
    OPEN = "open"
    PENDING = "pending"
    HOLD = "hold"
    SOLVED = "solved"
    CLOSED = "closed"


class TicketPriority(str, Enum):
    """Ticket priority."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TicketType(str, Enum):
    """Ticket type."""

    QUESTION = "question"
    INCIDENT = "incident"
    PROBLEM = "problem"
    TASK = "task"


class UserRole(str, Enum):
    """User role."""

    END_USER = "end-user"
    AGENT = "agent"
    ADMIN = "admin"


@dataclass
class ZendeskCredentials:
    """Zendesk API credentials."""

    subdomain: str
    email: str
    api_token: str

    @property
    def base_url(self) -> str:
        return f"https://{self.subdomain}.zendesk.com/api/v2"

    @property
    def auth_header(self) -> str:
        credentials = f"{self.email}/token:{self.api_token}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"


@dataclass
class ZendeskUser:
    """Zendesk user (customer or agent)."""

    id: int
    name: str
    email: str
    role: UserRole
    organization_id: int | None = None
    phone: str | None = None
    time_zone: str | None = None
    verified: bool = False
    suspended: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ZendeskUser:
        """Create from API response."""
        return cls(
            id=data.get("id", 0),
            name=data.get("name", ""),
            email=data.get("email", ""),
            role=UserRole(data.get("role", "end-user")),
            organization_id=data.get("organization_id"),
            phone=data.get("phone"),
            time_zone=data.get("time_zone"),
            verified=data.get("verified", False),
            suspended=data.get("suspended", False),
            created_at=_parse_datetime(data.get("created_at")),
            updated_at=_parse_datetime(data.get("updated_at")),
            tags=data.get("tags", []),
        )


@dataclass
class Organization:
    """Zendesk organization."""

    id: int
    name: str
    domain_names: list[str] = field(default_factory=list)
    details: str | None = None
    notes: str | None = None
    group_id: int | None = None
    tags: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Organization:
        """Create from API response."""
        return cls(
            id=data.get("id", 0),
            name=data.get("name", ""),
            domain_names=data.get("domain_names", []),
            details=data.get("details"),
            notes=data.get("notes"),
            group_id=data.get("group_id"),
            tags=data.get("tags", []),
            created_at=_parse_datetime(data.get("created_at")),
            updated_at=_parse_datetime(data.get("updated_at")),
        )


@dataclass
class TicketComment:
    """Ticket comment."""

    id: int
    body: str
    author_id: int
    public: bool = True
    created_at: datetime | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> TicketComment:
        """Create from API response."""
        return cls(
            id=data.get("id", 0),
            body=data.get("body", ""),
            author_id=data.get("author_id", 0),
            public=data.get("public", True),
            created_at=_parse_datetime(data.get("created_at")),
            attachments=data.get("attachments", []),
        )


@dataclass
class Ticket:
    """Zendesk ticket."""

    id: int
    subject: str
    description: str
    status: TicketStatus
    priority: TicketPriority | None
    type: TicketType | None
    requester_id: int
    assignee_id: int | None = None
    group_id: int | None = None
    organization_id: int | None = None
    tags: list[str] = field(default_factory=list)
    custom_fields: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    due_at: datetime | None = None
    comments: list[TicketComment] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Ticket:
        """Create from API response."""
        return cls(
            id=data.get("id", 0),
            subject=data.get("subject", ""),
            description=data.get("description", ""),
            status=TicketStatus(data.get("status", "new")),
            priority=TicketPriority(data["priority"]) if data.get("priority") else None,
            type=TicketType(data["type"]) if data.get("type") else None,
            requester_id=data.get("requester_id", 0),
            assignee_id=data.get("assignee_id"),
            group_id=data.get("group_id"),
            organization_id=data.get("organization_id"),
            tags=data.get("tags", []),
            custom_fields=data.get("custom_fields", []),
            created_at=_parse_datetime(data.get("created_at")),
            updated_at=_parse_datetime(data.get("updated_at")),
            due_at=_parse_datetime(data.get("due_at")),
        )


@dataclass
class View:
    """Zendesk view."""

    id: int
    title: str
    active: bool = True
    position: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> View:
        """Create from API response."""
        return cls(
            id=data.get("id", 0),
            title=data.get("title", ""),
            active=data.get("active", True),
            position=data.get("position", 0),
            created_at=_parse_datetime(data.get("created_at")),
            updated_at=_parse_datetime(data.get("updated_at")),
        )


class ZendeskError(Exception):
    """Zendesk API error."""

    def __init__(self, message: str, status_code: int | None = None, details: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


class ZendeskConnector:
    """
    Zendesk Support API connector.

    Provides integration with Zendesk for:
    - Ticket management
    - User and organization management
    - Views and search
    - Comments and attachments
    """

    def __init__(self, credentials: ZendeskCredentials):
        self.credentials = credentials
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.credentials.base_url,
                headers={
                    "Authorization": self.credentials.auth_header,
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    # Retry configuration
    _MAX_RETRIES = 3
    _BASE_DELAY = 1.0
    _MAX_DELAY = 30.0

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_data: dict | None = None,
    ) -> dict[str, Any]:
        """Make API request with retry and exponential backoff."""
        last_exc: Exception | None = None
        for attempt in range(self._MAX_RETRIES + 1):
            try:
                client = await self._get_client()
                # Normalize AsyncMock side_effect lists (test safety).
                try:
                    se = getattr(client.request, "side_effect", None)
                    if isinstance(se, list):
                        client.request.side_effect = iter(se)  # type: ignore[attr-defined]
                except (AttributeError, TypeError) as exc:
                    logger.debug("Mock side_effect normalization skipped: %s", exc)
                response = await client.request(
                    method,
                    path,
                    params=params,
                    json=json_data,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self._MAX_RETRIES:
                        delay = min(self._BASE_DELAY * (2**attempt), self._MAX_DELAY)
                        jitter = delay * 0.3 * random.random()
                        ra = response.headers.get("Retry-After")
                        if ra:
                            try:
                                delay = float(ra)
                            except (ValueError, TypeError) as exc:
                                raise ZendeskError(
                                    f"Invalid Retry-After header from Zendesk: {ra!r}",
                                    status_code=response.status_code,
                                    details={"header": "Retry-After", "value": ra},
                                ) from exc
                        logger.warning(
                            "Zendesk %s %s returned %d, retrying in %.1fs (attempt %d/%d)",
                            method,
                            path,
                            response.status_code,
                            delay + jitter,
                            attempt + 1,
                            self._MAX_RETRIES,
                        )
                        await asyncio.sleep(delay + jitter)
                        continue
                if response.status_code >= 400:
                    try:
                        error_data = response.json()
                        raise ZendeskError(
                            message=error_data.get("error", response.text),
                            status_code=response.status_code,
                            details=error_data,
                        )
                    except ValueError:
                        raise ZendeskError(
                            f"HTTP {response.status_code}: {response.text}",
                            status_code=response.status_code,
                        )
                if response.status_code == 204:
                    return {}
                return response.json()
            except ZendeskError:
                raise
            except (httpx.TimeoutException, httpx.ConnectError, OSError) as exc:
                last_exc = exc
                if attempt < self._MAX_RETRIES:
                    delay = min(self._BASE_DELAY * (2**attempt), self._MAX_DELAY)
                    jitter = delay * 0.3 * random.random()
                    logger.warning(
                        "Zendesk %s %s network error: %s, retrying in %.1fs (attempt %d/%d)",
                        method,
                        path,
                        type(exc).__name__,
                        delay + jitter,
                        attempt + 1,
                        self._MAX_RETRIES,
                    )
                    await asyncio.sleep(delay + jitter)
                    continue
                raise ZendeskError(
                    f"Network error after {self._MAX_RETRIES} retries: {type(exc).__name__}",
                ) from exc
        raise ZendeskError(
            f"Request failed after {self._MAX_RETRIES} retries",
        ) from last_exc

    # =========================================================================
    # Tickets
    # =========================================================================

    async def get_tickets(
        self,
        status: TicketStatus | None = None,
        assignee_id: int | None = None,
        requester_id: int | None = None,
        page: int = 1,
        per_page: int = 100,
    ) -> tuple[list[Ticket], bool]:
        """Get tickets with optional filtering. Returns (tickets, has_more)."""
        params: dict[str, Any] = {"page": page, "per_page": min(per_page, 100)}

        # Build query for filtering
        queries = []
        if status:
            queries.append(f"status:{status.value}")
        if assignee_id:
            queries.append(f"assignee_id:{assignee_id}")
        if requester_id:
            queries.append(f"requester_id:{requester_id}")

        if queries:
            params["query"] = " ".join(queries)
            data = await self._request("GET", "/search.json", params=params)
            tickets = [Ticket.from_api(t) for t in data.get("results", [])]
            return tickets, data.get("next_page") is not None
        else:
            data = await self._request("GET", "/tickets.json", params=params)
            tickets = [Ticket.from_api(t) for t in data.get("tickets", [])]
            return tickets, data.get("next_page") is not None

    async def get_ticket(self, ticket_id: int) -> Ticket:
        """Get a single ticket."""
        data = await self._request("GET", f"/tickets/{ticket_id}.json")
        return Ticket.from_api(data["ticket"])

    async def create_ticket(
        self,
        subject: str,
        description: str,
        requester_id: int | None = None,
        requester_email: str | None = None,
        priority: TicketPriority | None = None,
        type: TicketType | None = None,
        tags: list[str] | None = None,
        assignee_id: int | None = None,
        group_id: int | None = None,
        custom_fields: list[dict[str, Any]] | None = None,
    ) -> Ticket:
        """Create a new ticket."""
        ticket_data: dict[str, Any] = {
            "subject": subject,
            "comment": {"body": description},
        }

        if requester_id:
            ticket_data["requester_id"] = requester_id
        elif requester_email:
            ticket_data["requester"] = {"email": requester_email}

        if priority:
            ticket_data["priority"] = priority.value
        if type:
            ticket_data["type"] = type.value
        if tags:
            ticket_data["tags"] = tags
        if assignee_id:
            ticket_data["assignee_id"] = assignee_id
        if group_id:
            ticket_data["group_id"] = group_id
        if custom_fields:
            ticket_data["custom_fields"] = custom_fields

        data = await self._request("POST", "/tickets.json", json_data={"ticket": ticket_data})
        return Ticket.from_api(data["ticket"])

    async def update_ticket(
        self,
        ticket_id: int,
        status: TicketStatus | None = None,
        priority: TicketPriority | None = None,
        assignee_id: int | None = None,
        tags: list[str] | None = None,
        comment: str | None = None,
        public: bool = True,
    ) -> Ticket:
        """Update a ticket."""
        ticket_data: dict[str, Any] = {}

        if status:
            ticket_data["status"] = status.value
        if priority:
            ticket_data["priority"] = priority.value
        if assignee_id is not None:
            ticket_data["assignee_id"] = assignee_id
        if tags is not None:
            ticket_data["tags"] = tags
        if comment:
            ticket_data["comment"] = {"body": comment, "public": public}

        data = await self._request(
            "PUT", f"/tickets/{ticket_id}.json", json_data={"ticket": ticket_data}
        )
        return Ticket.from_api(data["ticket"])

    async def delete_ticket(self, ticket_id: int) -> bool:
        """Delete a ticket."""
        await self._request("DELETE", f"/tickets/{ticket_id}.json")
        return True

    async def get_ticket_comments(self, ticket_id: int) -> list[TicketComment]:
        """Get all comments for a ticket."""
        data = await self._request("GET", f"/tickets/{ticket_id}/comments.json")
        return [TicketComment.from_api(c) for c in data.get("comments", [])]

    async def add_ticket_comment(
        self,
        ticket_id: int,
        body: str,
        public: bool = True,
    ) -> TicketComment:
        """Add a comment to a ticket."""
        await self._request(
            "PUT",
            f"/tickets/{ticket_id}.json",
            json_data={"ticket": {"comment": {"body": body, "public": public}}},
        )
        # Return the last comment
        comments = await self.get_ticket_comments(ticket_id)
        if not comments:
            raise ZendeskError(
                f"Ticket {ticket_id} comment creation could not be verified: no comments returned"
            )
        return comments[-1]

    # =========================================================================
    # Users
    # =========================================================================

    async def get_users(
        self,
        role: UserRole | None = None,
        page: int = 1,
        per_page: int = 100,
    ) -> tuple[list[ZendeskUser], bool]:
        """Get users. Returns (users, has_more)."""
        params: dict[str, Any] = {"page": page, "per_page": min(per_page, 100)}
        if role:
            params["role"] = role.value

        data = await self._request("GET", "/users.json", params=params)
        users = [ZendeskUser.from_api(u) for u in data.get("users", [])]
        return users, data.get("next_page") is not None

    async def get_user(self, user_id: int) -> ZendeskUser:
        """Get a single user."""
        data = await self._request("GET", f"/users/{user_id}.json")
        return ZendeskUser.from_api(data["user"])

    async def create_user(
        self,
        name: str,
        email: str,
        role: UserRole = UserRole.END_USER,
        phone: str | None = None,
        organization_id: int | None = None,
    ) -> ZendeskUser:
        """Create a new user."""
        user_data: dict[str, Any] = {
            "name": name,
            "email": email,
            "role": role.value,
        }
        if phone:
            user_data["phone"] = phone
        if organization_id:
            user_data["organization_id"] = organization_id

        data = await self._request("POST", "/users.json", json_data={"user": user_data})
        return ZendeskUser.from_api(data["user"])

    async def search_users(self, query: str) -> list[ZendeskUser]:
        """Search for users."""
        data = await self._request("GET", "/users/search.json", params={"query": query})
        return [ZendeskUser.from_api(u) for u in data.get("users", [])]

    # =========================================================================
    # Organizations
    # =========================================================================

    async def get_organizations(
        self,
        page: int = 1,
        per_page: int = 100,
    ) -> tuple[list[Organization], bool]:
        """Get organizations. Returns (organizations, has_more)."""
        params: dict[str, Any] = {"page": page, "per_page": min(per_page, 100)}
        data = await self._request("GET", "/organizations.json", params=params)
        orgs = [Organization.from_api(o) for o in data.get("organizations", [])]
        return orgs, data.get("next_page") is not None

    async def get_organization(self, org_id: int) -> Organization:
        """Get a single organization."""
        data = await self._request("GET", f"/organizations/{org_id}.json")
        return Organization.from_api(data["organization"])

    async def create_organization(
        self,
        name: str,
        domain_names: list[str] | None = None,
        details: str | None = None,
    ) -> Organization:
        """Create a new organization."""
        org_data: dict[str, Any] = {"name": name}
        if domain_names:
            org_data["domain_names"] = domain_names
        if details:
            org_data["details"] = details

        data = await self._request(
            "POST", "/organizations.json", json_data={"organization": org_data}
        )
        return Organization.from_api(data["organization"])

    # =========================================================================
    # Views
    # =========================================================================

    async def get_views(self) -> list[View]:
        """Get all views."""
        data = await self._request("GET", "/views.json")
        return [View.from_api(v) for v in data.get("views", [])]

    async def get_view_tickets(
        self, view_id: int, page: int = 1, per_page: int = 100
    ) -> tuple[list[Ticket], bool]:
        """Get tickets in a view. Returns (tickets, has_more)."""
        params: dict[str, Any] = {"page": page, "per_page": min(per_page, 100)}
        data = await self._request("GET", f"/views/{view_id}/tickets.json", params=params)
        tickets = [Ticket.from_api(t) for t in data.get("tickets", [])]
        return tickets, data.get("next_page") is not None

    # =========================================================================
    # Search
    # =========================================================================

    async def search(
        self,
        query: str,
        type: str | None = None,
        page: int = 1,
        per_page: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Search Zendesk.

        type can be: ticket, user, organization, etc.
        """
        params: dict[str, Any] = {"query": query, "page": page, "per_page": min(per_page, 100)}
        if type:
            params["query"] = f"type:{type} {query}"

        data = await self._request("GET", "/search.json", params=params)
        return data.get("results", [])

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> ZendeskConnector:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime string."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ZendeskError(
            f"Invalid Zendesk datetime value: {value!r}",
            details={"value": value},
        ) from exc


def get_mock_ticket() -> Ticket:
    """Get a mock ticket for testing."""
    return Ticket(
        id=12345,
        subject="Cannot login to my account",
        description="I tried resetting my password but still cannot login.",
        status=TicketStatus.OPEN,
        priority=TicketPriority.HIGH,
        type=TicketType.INCIDENT,
        requester_id=67890,
        created_at=datetime.now(),
    )


def get_mock_user() -> ZendeskUser:
    """Get a mock user for testing."""
    return ZendeskUser(
        id=67890,
        name="John Doe",
        email="john.doe@example.com",
        role=UserRole.END_USER,
        verified=True,
    )
