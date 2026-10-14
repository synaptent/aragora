"""
Freshdesk Support Connector.

Integration with Freshdesk API:
- Tickets (CRUD, conversations, time entries)
- Contacts and companies
- Agents and groups
- Canned responses
- SLA policies

Requires Freshdesk domain and API key.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, cast

import httpx

logger = logging.getLogger(__name__)


class TicketStatus(int, Enum):
    """Freshdesk ticket status."""

    OPEN = 2
    PENDING = 3
    RESOLVED = 4
    CLOSED = 5


class TicketPriority(int, Enum):
    """Freshdesk ticket priority."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    URGENT = 4


class TicketSource(int, Enum):
    """Ticket source channel."""

    EMAIL = 1
    PORTAL = 2
    PHONE = 3
    CHAT = 7
    FEEDBACK_WIDGET = 9
    OUTBOUND_EMAIL = 10


@dataclass
class FreshdeskCredentials:
    """Freshdesk API credentials."""

    domain: str  # e.g., "yourcompany" for yourcompany.freshdesk.com
    api_key: str

    @property
    def base_url(self) -> str:
        return f"https://{self.domain}.freshdesk.com/api/v2"

    @property
    def auth_header(self) -> str:
        credentials = f"{self.api_key}:X"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"


@dataclass
class Contact:
    """Freshdesk contact."""

    id: int
    name: str
    email: str
    phone: str | None = None
    mobile: str | None = None
    company_id: int | None = None
    job_title: str | None = None
    language: str = "en"
    time_zone: str | None = None
    tags: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Contact:
        """Create from API response."""
        return cls(
            id=data.get("id", 0),
            name=data.get("name", ""),
            email=data.get("email", ""),
            phone=data.get("phone"),
            mobile=data.get("mobile"),
            company_id=data.get("company_id"),
            job_title=data.get("job_title"),
            language=data.get("language", "en"),
            time_zone=data.get("time_zone"),
            tags=data.get("tags", []),
            created_at=_parse_datetime(data.get("created_at")),
            updated_at=_parse_datetime(data.get("updated_at")),
        )


@dataclass
class Company:
    """Freshdesk company."""

    id: int
    name: str
    description: str | None = None
    domains: list[str] = field(default_factory=list)
    industry: str | None = None
    health_score: str | None = None
    account_tier: str | None = None
    renewal_date: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Company:
        """Create from API response."""
        return cls(
            id=data.get("id", 0),
            name=data.get("name", ""),
            description=data.get("description"),
            domains=data.get("domains", []),
            industry=data.get("industry"),
            health_score=data.get("health_score"),
            account_tier=data.get("account_tier"),
            renewal_date=_parse_datetime(data.get("renewal_date")),
            created_at=_parse_datetime(data.get("created_at")),
            updated_at=_parse_datetime(data.get("updated_at")),
        )


@dataclass
class Conversation:
    """Ticket conversation (reply/note)."""

    id: int
    body: str
    body_text: str
    user_id: int
    incoming: bool = False
    private: bool = False
    support_email: str | None = None
    created_at: datetime | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Conversation:
        """Create from API response."""
        return cls(
            id=data.get("id", 0),
            body=data.get("body", ""),
            body_text=data.get("body_text", ""),
            user_id=data.get("user_id", 0),
            incoming=data.get("incoming", False),
            private=data.get("private", False),
            support_email=data.get("support_email"),
            created_at=_parse_datetime(data.get("created_at")),
            attachments=data.get("attachments", []),
        )


@dataclass
class FreshdeskTicket:
    """Freshdesk ticket."""

    id: int
    subject: str
    description: str
    description_text: str
    status: TicketStatus
    priority: TicketPriority
    source: TicketSource
    requester_id: int
    responder_id: int | None = None
    group_id: int | None = None
    company_id: int | None = None
    product_id: int | None = None
    email: str | None = None
    type: str | None = None
    tags: list[str] = field(default_factory=list)
    cc_emails: list[str] = field(default_factory=list)
    custom_fields: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    due_by: datetime | None = None
    fr_due_by: datetime | None = None
    is_escalated: bool = False
    spam: bool = False

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> FreshdeskTicket:
        """Create from API response."""
        return cls(
            id=data.get("id", 0),
            subject=data.get("subject", ""),
            description=data.get("description", ""),
            description_text=data.get("description_text", ""),
            status=TicketStatus(data.get("status", 2)),
            priority=TicketPriority(data.get("priority", 1)),
            source=TicketSource(data.get("source", 1)),
            requester_id=data.get("requester_id", 0),
            responder_id=data.get("responder_id"),
            group_id=data.get("group_id"),
            company_id=data.get("company_id"),
            product_id=data.get("product_id"),
            email=data.get("email"),
            type=data.get("type"),
            tags=data.get("tags", []),
            cc_emails=data.get("cc_emails", []),
            custom_fields=data.get("custom_fields", {}),
            created_at=_parse_datetime(data.get("created_at")),
            updated_at=_parse_datetime(data.get("updated_at")),
            due_by=_parse_datetime(data.get("due_by")),
            fr_due_by=_parse_datetime(data.get("fr_due_by")),
            is_escalated=data.get("is_escalated", False),
            spam=data.get("spam", False),
        )


@dataclass
class Agent:
    """Freshdesk agent."""

    id: int
    contact_id: int
    name: str
    email: str
    active: bool = True
    occasional: bool = False
    group_ids: list[int] = field(default_factory=list)
    role_ids: list[int] = field(default_factory=list)
    available: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Agent:
        """Create from API response."""
        contact = data.get("contact", {})
        return cls(
            id=data.get("id", 0),
            contact_id=contact.get("id", 0),
            name=contact.get("name", ""),
            email=contact.get("email", ""),
            active=contact.get("active", True),
            occasional=data.get("occasional", False),
            group_ids=data.get("group_ids", []),
            role_ids=data.get("role_ids", []),
            available=data.get("available", True),
            created_at=_parse_datetime(data.get("created_at")),
            updated_at=_parse_datetime(data.get("updated_at")),
        )


class FreshdeskError(Exception):
    """Freshdesk API error."""

    def __init__(self, message: str, status_code: int | None = None, details: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


class FreshdeskConnector:
    """
    Freshdesk API connector.

    Provides integration with Freshdesk for:
    - Ticket management
    - Contact and company management
    - Agent management
    - Conversations and notes
    """

    def __init__(self, credentials: FreshdeskCredentials):
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

    @staticmethod
    def _require_list_response(
        data: dict[str, Any] | list[Any],
        context: str,
    ) -> list[Any]:
        """Fail closed on malformed list responses."""
        if not isinstance(data, list):
            raise FreshdeskError(
                f"Unexpected Freshdesk response for {context}: expected list, got {type(data).__name__}",
            )
        return data

    @staticmethod
    def _require_dict_response(
        data: dict[str, Any] | list[Any],
        context: str,
    ) -> dict[str, Any]:
        """Fail closed on malformed object responses."""
        if not isinstance(data, dict):
            raise FreshdeskError(
                f"Unexpected Freshdesk response for {context}: expected dict, got {type(data).__name__}",
            )
        return data

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_data: dict | None = None,
    ) -> dict[str, Any] | list[Any]:
        """Make API request with retry and exponential backoff.

        Retries on 429 (rate limit) and 5xx (server error) responses,
        as well as transient network errors, up to ``_MAX_RETRIES`` times.
        """
        last_exc: Exception | None = None

        for attempt in range(self._MAX_RETRIES + 1):
            try:
                client = await self._get_client()
                response = await client.request(
                    method,
                    path,
                    params=params,
                    json=json_data,
                )

                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self._MAX_RETRIES:
                        delay = min(
                            self._BASE_DELAY * (2**attempt),
                            self._MAX_DELAY,
                        )
                        jitter = delay * 0.3 * random.random()
                        retry_after = response.headers.get("Retry-After")
                        if retry_after:
                            try:
                                delay = float(retry_after)
                            except (ValueError, TypeError) as exc:
                                raise FreshdeskError(
                                    f"Invalid Retry-After header for {method} {path}: {retry_after!r}",
                                    status_code=response.status_code,
                                ) from exc
                        logger.warning(
                            "Freshdesk %s %s returned %d, retrying in %.1fs (attempt %d/%d)",
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
                        raise FreshdeskError(
                            message=str(
                                error_data.get("errors", [error_data]),
                            ),
                            status_code=response.status_code,
                            details=error_data,
                        )
                    except ValueError:
                        raise FreshdeskError(
                            f"HTTP {response.status_code}: {response.text}",
                            status_code=response.status_code,
                        )

                if response.status_code == 204:
                    return {}
                return response.json()

            except FreshdeskError:
                raise
            except (
                httpx.TimeoutException,
                httpx.ConnectError,
                OSError,
            ) as e:
                last_exc = e
                if attempt < self._MAX_RETRIES:
                    delay = min(
                        self._BASE_DELAY * (2**attempt),
                        self._MAX_DELAY,
                    )
                    jitter = delay * 0.3 * random.random()
                    logger.warning(
                        "Freshdesk %s %s network error: %s, retrying in %.1fs (attempt %d/%d)",
                        method,
                        path,
                        type(e).__name__,
                        delay + jitter,
                        attempt + 1,
                        self._MAX_RETRIES,
                    )
                    await asyncio.sleep(delay + jitter)
                    continue
                raise FreshdeskError(
                    f"Network error after {self._MAX_RETRIES} retries: {type(e).__name__}",
                ) from e

        raise FreshdeskError(
            f"Request failed after {self._MAX_RETRIES} retries",
        ) from last_exc

    # =========================================================================
    # Tickets
    # =========================================================================

    async def get_tickets(
        self,
        filter: str | None = None,
        requester_id: int | None = None,
        company_id: int | None = None,
        updated_since: datetime | None = None,
        page: int = 1,
        per_page: int = 30,
    ) -> list[FreshdeskTicket]:
        """
        Get tickets with optional filtering.

        filter options: new_and_my_open, watching, spam, deleted
        """
        params: dict[str, Any] = {"page": page, "per_page": min(per_page, 100)}

        if filter:
            params["filter"] = filter
        if requester_id:
            params["requester_id"] = requester_id
        if company_id:
            params["company_id"] = company_id
        if updated_since:
            params["updated_since"] = updated_since.strftime("%Y-%m-%dT%H:%M:%SZ")

        data = self._require_list_response(
            await self._request("GET", "/tickets", params=params), "GET /tickets"
        )
        return [FreshdeskTicket.from_api(t) for t in data]

    async def get_ticket(self, ticket_id: int) -> FreshdeskTicket:
        """Get a single ticket."""
        data = await self._request("GET", f"/tickets/{ticket_id}")
        return FreshdeskTicket.from_api(cast(dict[str, Any], data))

    async def create_ticket(
        self,
        subject: str,
        description: str,
        email: str | None = None,
        requester_id: int | None = None,
        priority: TicketPriority = TicketPriority.MEDIUM,
        status: TicketStatus = TicketStatus.OPEN,
        source: TicketSource = TicketSource.EMAIL,
        type: str | None = None,
        tags: list[str] | None = None,
        group_id: int | None = None,
        responder_id: int | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> FreshdeskTicket:
        """Create a new ticket."""
        ticket_data: dict[str, Any] = {
            "subject": subject,
            "description": description,
            "priority": priority.value,
            "status": status.value,
            "source": source.value,
        }

        if email:
            ticket_data["email"] = email
        if requester_id:
            ticket_data["requester_id"] = requester_id
        if type:
            ticket_data["type"] = type
        if tags:
            ticket_data["tags"] = tags
        if group_id:
            ticket_data["group_id"] = group_id
        if responder_id:
            ticket_data["responder_id"] = responder_id
        if custom_fields:
            ticket_data["custom_fields"] = custom_fields

        data = await self._request("POST", "/tickets", json_data=ticket_data)
        return FreshdeskTicket.from_api(cast(dict[str, Any], data))

    async def update_ticket(
        self,
        ticket_id: int,
        status: TicketStatus | None = None,
        priority: TicketPriority | None = None,
        responder_id: int | None = None,
        group_id: int | None = None,
        tags: list[str] | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> FreshdeskTicket:
        """Update a ticket."""
        ticket_data: dict[str, Any] = {}

        if status is not None:
            ticket_data["status"] = status.value
        if priority is not None:
            ticket_data["priority"] = priority.value
        if responder_id is not None:
            ticket_data["responder_id"] = responder_id
        if group_id is not None:
            ticket_data["group_id"] = group_id
        if tags is not None:
            ticket_data["tags"] = tags
        if custom_fields is not None:
            ticket_data["custom_fields"] = custom_fields

        data = await self._request("PUT", f"/tickets/{ticket_id}", json_data=ticket_data)
        return FreshdeskTicket.from_api(cast(dict[str, Any], data))

    async def delete_ticket(self, ticket_id: int) -> bool:
        """Delete a ticket."""
        await self._request("DELETE", f"/tickets/{ticket_id}")
        return True

    # =========================================================================
    # Conversations
    # =========================================================================

    async def get_conversations(self, ticket_id: int) -> list[Conversation]:
        """Get all conversations for a ticket."""
        data = self._require_list_response(
            await self._request("GET", f"/tickets/{ticket_id}/conversations"),
            f"GET /tickets/{ticket_id}/conversations",
        )
        return [Conversation.from_api(c) for c in data]

    async def reply_to_ticket(
        self,
        ticket_id: int,
        body: str,
        cc_emails: list[str] | None = None,
    ) -> Conversation:
        """Reply to a ticket (public)."""
        reply_data: dict[str, Any] = {"body": body}
        if cc_emails:
            reply_data["cc_emails"] = cc_emails

        data = await self._request("POST", f"/tickets/{ticket_id}/reply", json_data=reply_data)
        return Conversation.from_api(cast(dict[str, Any], data))

    async def add_note(
        self,
        ticket_id: int,
        body: str,
        private: bool = True,
    ) -> Conversation:
        """Add a note to a ticket."""
        note_data: dict[str, Any] = {"body": body, "private": private}
        data = await self._request("POST", f"/tickets/{ticket_id}/notes", json_data=note_data)
        return Conversation.from_api(cast(dict[str, Any], data))

    # =========================================================================
    # Contacts
    # =========================================================================

    async def get_contacts(
        self,
        email: str | None = None,
        company_id: int | None = None,
        page: int = 1,
        per_page: int = 30,
    ) -> list[Contact]:
        """Get contacts with optional filtering."""
        params: dict[str, Any] = {"page": page, "per_page": min(per_page, 100)}
        if email:
            params["email"] = email
        if company_id:
            params["company_id"] = company_id

        data = self._require_list_response(
            await self._request("GET", "/contacts", params=params),
            "GET /contacts",
        )
        return [Contact.from_api(c) for c in data]

    async def get_contact(self, contact_id: int) -> Contact:
        """Get a single contact."""
        data = await self._request("GET", f"/contacts/{contact_id}")
        return Contact.from_api(cast(dict[str, Any], data))

    async def create_contact(
        self,
        name: str,
        email: str,
        phone: str | None = None,
        company_id: int | None = None,
        job_title: str | None = None,
    ) -> Contact:
        """Create a new contact."""
        contact_data: dict[str, Any] = {"name": name, "email": email}
        if phone:
            contact_data["phone"] = phone
        if company_id:
            contact_data["company_id"] = company_id
        if job_title:
            contact_data["job_title"] = job_title

        data = await self._request("POST", "/contacts", json_data=contact_data)
        return Contact.from_api(cast(dict[str, Any], data))

    # =========================================================================
    # Companies
    # =========================================================================

    async def get_companies(self, page: int = 1, per_page: int = 30) -> list[Company]:
        """Get companies."""
        params: dict[str, Any] = {"page": page, "per_page": min(per_page, 100)}
        data = self._require_list_response(
            await self._request("GET", "/companies", params=params),
            "GET /companies",
        )
        return [Company.from_api(c) for c in data]

    async def get_company(self, company_id: int) -> Company:
        """Get a single company."""
        data = await self._request("GET", f"/companies/{company_id}")
        return Company.from_api(cast(dict[str, Any], data))

    async def create_company(
        self,
        name: str,
        domains: list[str] | None = None,
        description: str | None = None,
    ) -> Company:
        """Create a new company."""
        company_data: dict[str, Any] = {"name": name}
        if domains:
            company_data["domains"] = domains
        if description:
            company_data["description"] = description

        data = await self._request("POST", "/companies", json_data=company_data)
        return Company.from_api(cast(dict[str, Any], data))

    # =========================================================================
    # Agents
    # =========================================================================

    async def get_agents(self, page: int = 1, per_page: int = 30) -> list[Agent]:
        """Get agents."""
        params: dict[str, Any] = {"page": page, "per_page": min(per_page, 100)}
        data = self._require_list_response(
            await self._request("GET", "/agents", params=params), "GET /agents"
        )
        return [Agent.from_api(a) for a in data]

    async def get_agent(self, agent_id: int) -> Agent:
        """Get a single agent."""
        data = await self._request("GET", f"/agents/{agent_id}")
        return Agent.from_api(cast(dict[str, Any], data))

    # =========================================================================
    # Search
    # =========================================================================

    async def search_tickets(self, query: str) -> list[FreshdeskTicket]:
        """
        Search tickets using Freshdesk query language.

        Example queries:
        - "status:2 AND priority:4" (open and urgent)
        - "created_at:>'2024-01-01'" (created after date)
        """
        data = self._require_dict_response(
            await self._request("GET", "/search/tickets", params={"query": f'"{query}"'}),
            "GET /search/tickets",
        )
        results = data.get("results", [])
        if not isinstance(results, list):
            raise FreshdeskError(
                f"Unexpected Freshdesk response for GET /search/tickets: expected list results, got {type(results).__name__}",
            )
        return [FreshdeskTicket.from_api(t) for t in results]

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> FreshdeskConnector:
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
        raise FreshdeskError(f"Invalid Freshdesk datetime value: {value!r}") from exc


def get_mock_ticket() -> FreshdeskTicket:
    """Get a mock ticket for testing."""
    return FreshdeskTicket(
        id=12345,
        subject="Product not working as expected",
        description="<p>The product stopped working after the update.</p>",
        description_text="The product stopped working after the update.",
        status=TicketStatus.OPEN,
        priority=TicketPriority.HIGH,
        source=TicketSource.EMAIL,
        requester_id=67890,
        created_at=datetime.now(),
    )


def get_mock_contact() -> Contact:
    """Get a mock contact for testing."""
    return Contact(
        id=67890,
        name="Jane Smith",
        email="jane.smith@example.com",
        phone="+1-555-0123",
    )
