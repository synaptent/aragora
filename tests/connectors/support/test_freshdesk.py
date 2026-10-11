"""
Comprehensive tests for the Freshdesk Support Connector.

Tests cover:
- Enum values (TicketStatus, TicketPriority, TicketSource)
- FreshdeskCredentials dataclass and auth header generation
- Data models: Contact, Company, Conversation, FreshdeskTicket, Agent
- Model serialization (from_api)
- FreshdeskConnector initialization and async context manager
- API request handling (_request with auth, error responses)
- Tickets CRUD operations (get, create, update, delete)
- Conversations (replies, notes)
- Contacts CRUD operations
- Companies CRUD operations
- Agents operations
- Search operations
- Helper functions (_parse_datetime)
- Error handling (HTTP errors, JSON parsing)
- Edge cases (empty responses, missing fields, malformed data)
- Mock data generation helpers
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.connectors.support.freshdesk import (
    Agent,
    Company,
    Contact,
    Conversation,
    FreshdeskConnector,
    FreshdeskCredentials,
    FreshdeskError,
    FreshdeskTicket,
    TicketPriority,
    TicketSource,
    TicketStatus,
    _parse_datetime,
    get_mock_contact,
    get_mock_ticket,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def credentials():
    """Standard test credentials."""
    return FreshdeskCredentials(
        domain="testcompany",
        api_key="test-api-key-xyz",
    )


@pytest.fixture
def mock_httpx_client():
    """Create a mock httpx AsyncClient."""
    client = AsyncMock()
    return client


@pytest.fixture
def freshdesk_connector(credentials, mock_httpx_client):
    """Create a FreshdeskConnector with a mock HTTP client."""
    connector = FreshdeskConnector(credentials)
    connector._client = mock_httpx_client
    return connector


def _make_response(json_data: dict[str, Any] | list[Any], status_code: int = 200) -> MagicMock:
    """Build a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = str(json_data)
    return resp


# =============================================================================
# Enum Tests
# =============================================================================


class TestTicketStatus:
    """Tests for TicketStatus enum."""

    def test_ticket_status_values(self):
        assert TicketStatus.OPEN.value == 2
        assert TicketStatus.PENDING.value == 3
        assert TicketStatus.RESOLVED.value == 4
        assert TicketStatus.CLOSED.value == 5

    def test_ticket_status_is_int(self):
        assert isinstance(TicketStatus.OPEN, int)
        assert TicketStatus.OPEN == 2

    def test_ticket_status_from_int(self):
        assert TicketStatus(3) == TicketStatus.PENDING


class TestTicketPriority:
    """Tests for TicketPriority enum."""

    def test_ticket_priority_values(self):
        assert TicketPriority.LOW.value == 1
        assert TicketPriority.MEDIUM.value == 2
        assert TicketPriority.HIGH.value == 3
        assert TicketPriority.URGENT.value == 4

    def test_ticket_priority_is_int(self):
        assert isinstance(TicketPriority.HIGH, int)
        assert TicketPriority.HIGH == 3


class TestTicketSource:
    """Tests for TicketSource enum."""

    def test_ticket_source_values(self):
        assert TicketSource.EMAIL.value == 1
        assert TicketSource.PORTAL.value == 2
        assert TicketSource.PHONE.value == 3
        assert TicketSource.CHAT.value == 7
        assert TicketSource.FEEDBACK_WIDGET.value == 9
        assert TicketSource.OUTBOUND_EMAIL.value == 10

    def test_ticket_source_is_int(self):
        assert isinstance(TicketSource.EMAIL, int)


# =============================================================================
# Credentials Tests
# =============================================================================


class TestFreshdeskCredentials:
    """Tests for FreshdeskCredentials dataclass."""

    def test_basic_construction(self):
        creds = FreshdeskCredentials(
            domain="mycompany",
            api_key="api-key-123",
        )
        assert creds.domain == "mycompany"
        assert creds.api_key == "api-key-123"

    def test_base_url_property(self):
        creds = FreshdeskCredentials(
            domain="test",
            api_key="token",
        )
        assert creds.base_url == "https://test.freshdesk.com/api/v2"

    def test_auth_header_property(self):
        creds = FreshdeskCredentials(
            domain="test",
            api_key="myapikey",
        )
        expected_credentials = "myapikey:X"
        expected_encoded = base64.b64encode(expected_credentials.encode()).decode()
        assert creds.auth_header == f"Basic {expected_encoded}"

    def test_auth_header_encoding(self):
        creds = FreshdeskCredentials(
            domain="company",
            api_key="secret123",
        )
        # Verify the auth header can be decoded correctly
        auth_header = creds.auth_header
        assert auth_header.startswith("Basic ")
        encoded_part = auth_header[6:]
        decoded = base64.b64decode(encoded_part).decode()
        assert decoded == "secret123:X"


# =============================================================================
# Error Tests
# =============================================================================


class TestFreshdeskError:
    """Tests for FreshdeskError exception."""

    def test_error_basic(self):
        err = FreshdeskError("Something went wrong")
        assert str(err) == "Something went wrong"
        assert err.status_code is None
        assert err.details == {}

    def test_error_with_status(self):
        err = FreshdeskError("Not found", status_code=404, details={"error": "RecordNotFound"})
        assert err.status_code == 404
        assert err.details == {"error": "RecordNotFound"}

    def test_error_with_all_params(self):
        err = FreshdeskError(
            "Rate limit exceeded",
            status_code=429,
            details={"message": "Too many requests", "retry_after": 60},
        )
        assert str(err) == "Rate limit exceeded"
        assert err.status_code == 429
        assert err.details["retry_after"] == 60


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestHelperFunctions:
    """Tests for _parse_datetime helper function."""

    def test_parse_datetime_none(self):
        assert _parse_datetime(None) is None

    def test_parse_datetime_empty(self):
        assert _parse_datetime("") is None

    def test_parse_datetime_iso_with_z(self):
        result = _parse_datetime("2023-06-15T10:30:00Z")
        assert result is not None
        assert result.year == 2023
        assert result.month == 6
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30

    def test_parse_datetime_iso_with_offset(self):
        result = _parse_datetime("2023-06-15T10:30:00+00:00")
        assert result is not None
        assert result.year == 2023

    def test_parse_datetime_invalid(self):
        with pytest.raises(FreshdeskError, match="Invalid Freshdesk datetime value"):
            _parse_datetime("not-a-date")

    def test_parse_datetime_malformed(self):
        with pytest.raises(FreshdeskError, match="Invalid Freshdesk datetime value"):
            _parse_datetime("2023/06/15")


# =============================================================================
# Contact Model Tests
# =============================================================================


class TestContactModel:
    """Tests for Contact dataclass."""

    def test_from_api_full(self):
        data = {
            "id": 12345,
            "name": "John Doe",
            "email": "john@example.com",
            "phone": "+1-555-0100",
            "mobile": "+1-555-0101",
            "company_id": 100,
            "job_title": "Software Engineer",
            "language": "en",
            "time_zone": "America/New_York",
            "tags": ["vip", "enterprise"],
            "created_at": "2023-01-15T10:00:00Z",
            "updated_at": "2023-06-20T14:30:00Z",
        }
        contact = Contact.from_api(data)
        assert contact.id == 12345
        assert contact.name == "John Doe"
        assert contact.email == "john@example.com"
        assert contact.phone == "+1-555-0100"
        assert contact.mobile == "+1-555-0101"
        assert contact.company_id == 100
        assert contact.job_title == "Software Engineer"
        assert contact.language == "en"
        assert contact.time_zone == "America/New_York"
        assert contact.tags == ["vip", "enterprise"]
        assert contact.created_at is not None

    def test_from_api_minimal(self):
        data = {"id": 1, "name": "", "email": ""}
        contact = Contact.from_api(data)
        assert contact.id == 1
        assert contact.name == ""
        assert contact.email == ""
        assert contact.phone is None
        assert contact.company_id is None
        assert contact.tags == []

    def test_from_api_default_language(self):
        data = {"id": 1, "name": "Test", "email": "test@test.com"}
        contact = Contact.from_api(data)
        assert contact.language == "en"


# =============================================================================
# Company Model Tests
# =============================================================================


class TestCompanyModel:
    """Tests for Company dataclass."""

    def test_from_api_full(self):
        data = {
            "id": 100,
            "name": "Acme Corp",
            "description": "Enterprise customer",
            "domains": ["acme.com", "acme.io"],
            "industry": "Technology",
            "health_score": "At risk",
            "account_tier": "Enterprise",
            "renewal_date": "2024-01-01T00:00:00Z",
            "created_at": "2023-01-01T00:00:00Z",
            "updated_at": "2023-06-01T12:00:00Z",
        }
        company = Company.from_api(data)
        assert company.id == 100
        assert company.name == "Acme Corp"
        assert company.description == "Enterprise customer"
        assert company.domains == ["acme.com", "acme.io"]
        assert company.industry == "Technology"
        assert company.health_score == "At risk"
        assert company.account_tier == "Enterprise"
        assert company.renewal_date is not None

    def test_from_api_minimal(self):
        data = {"id": 1}
        company = Company.from_api(data)
        assert company.id == 1
        assert company.name == ""
        assert company.domains == []
        assert company.description is None


# =============================================================================
# Conversation Model Tests
# =============================================================================


class TestConversationModel:
    """Tests for Conversation dataclass."""

    def test_from_api_full(self):
        data = {
            "id": 500,
            "body": "<p>Thank you for contacting us.</p>",
            "body_text": "Thank you for contacting us.",
            "user_id": 12345,
            "incoming": True,
            "private": False,
            "support_email": "support@company.com",
            "created_at": "2023-07-10T09:00:00Z",
            "attachments": [{"name": "screenshot.png", "url": "https://..."}],
        }
        conversation = Conversation.from_api(data)
        assert conversation.id == 500
        assert conversation.body == "<p>Thank you for contacting us.</p>"
        assert conversation.body_text == "Thank you for contacting us."
        assert conversation.user_id == 12345
        assert conversation.incoming is True
        assert conversation.private is False
        assert conversation.support_email == "support@company.com"
        assert len(conversation.attachments) == 1

    def test_from_api_minimal(self):
        data = {"id": 1}
        conversation = Conversation.from_api(data)
        assert conversation.id == 1
        assert conversation.body == ""
        assert conversation.body_text == ""
        assert conversation.user_id == 0
        assert conversation.incoming is False
        assert conversation.private is False
        assert conversation.attachments == []

    def test_from_api_private_note(self):
        data = {"id": 2, "body": "Internal note", "user_id": 1, "private": True}
        conversation = Conversation.from_api(data)
        assert conversation.private is True


# =============================================================================
# FreshdeskTicket Model Tests
# =============================================================================


class TestFreshdeskTicketModel:
    """Tests for FreshdeskTicket dataclass."""

    def test_from_api_full(self):
        data = {
            "id": 1000,
            "subject": "Cannot login to my account",
            "description": "<p>I tried resetting my password.</p>",
            "description_text": "I tried resetting my password.",
            "status": 2,
            "priority": 3,
            "source": 1,
            "requester_id": 12345,
            "responder_id": 67890,
            "group_id": 5,
            "company_id": 100,
            "product_id": 10,
            "email": "customer@example.com",
            "type": "Incident",
            "tags": ["login", "urgent"],
            "cc_emails": ["manager@example.com"],
            "custom_fields": {"cf_department": "IT"},
            "created_at": "2023-07-01T10:00:00Z",
            "updated_at": "2023-07-01T12:00:00Z",
            "due_by": "2023-07-02T10:00:00Z",
            "fr_due_by": "2023-07-01T14:00:00Z",
            "is_escalated": True,
            "spam": False,
        }
        ticket = FreshdeskTicket.from_api(data)
        assert ticket.id == 1000
        assert ticket.subject == "Cannot login to my account"
        assert ticket.status == TicketStatus.OPEN
        assert ticket.priority == TicketPriority.HIGH
        assert ticket.source == TicketSource.EMAIL
        assert ticket.requester_id == 12345
        assert ticket.responder_id == 67890
        assert ticket.group_id == 5
        assert ticket.company_id == 100
        assert ticket.email == "customer@example.com"
        assert ticket.type == "Incident"
        assert ticket.tags == ["login", "urgent"]
        assert ticket.cc_emails == ["manager@example.com"]
        assert ticket.custom_fields == {"cf_department": "IT"}
        assert ticket.is_escalated is True
        assert ticket.spam is False

    def test_from_api_minimal(self):
        data = {"id": 1, "status": 2}
        ticket = FreshdeskTicket.from_api(data)
        assert ticket.id == 1
        assert ticket.status == TicketStatus.OPEN
        assert ticket.subject == ""
        assert ticket.responder_id is None
        assert ticket.tags == []

    def test_from_api_all_statuses(self):
        for status in TicketStatus:
            data = {"id": 1, "status": status.value}
            ticket = FreshdeskTicket.from_api(data)
            assert ticket.status == status

    def test_from_api_all_priorities(self):
        for priority in TicketPriority:
            data = {"id": 1, "status": 2, "priority": priority.value}
            ticket = FreshdeskTicket.from_api(data)
            assert ticket.priority == priority

    def test_from_api_all_sources(self):
        for source in TicketSource:
            data = {"id": 1, "status": 2, "source": source.value}
            ticket = FreshdeskTicket.from_api(data)
            assert ticket.source == source


# =============================================================================
# Agent Model Tests
# =============================================================================


class TestAgentModel:
    """Tests for Agent dataclass."""

    def test_from_api_full(self):
        data = {
            "id": 100,
            "contact": {
                "id": 200,
                "name": "Agent Smith",
                "email": "agent.smith@company.com",
                "active": True,
            },
            "occasional": False,
            "group_ids": [1, 2, 3],
            "role_ids": [10, 20],
            "available": True,
            "created_at": "2023-01-01T00:00:00Z",
            "updated_at": "2023-06-01T12:00:00Z",
        }
        agent = Agent.from_api(data)
        assert agent.id == 100
        assert agent.contact_id == 200
        assert agent.name == "Agent Smith"
        assert agent.email == "agent.smith@company.com"
        assert agent.active is True
        assert agent.occasional is False
        assert agent.group_ids == [1, 2, 3]
        assert agent.role_ids == [10, 20]
        assert agent.available is True

    def test_from_api_minimal(self):
        data = {"id": 1}
        agent = Agent.from_api(data)
        assert agent.id == 1
        assert agent.contact_id == 0
        assert agent.name == ""
        assert agent.email == ""
        assert agent.group_ids == []
        assert agent.role_ids == []

    def test_from_api_occasional_agent(self):
        data = {"id": 2, "occasional": True, "contact": {"id": 3, "name": "Part Timer"}}
        agent = Agent.from_api(data)
        assert agent.occasional is True


# =============================================================================
# Client Initialization Tests
# =============================================================================


class TestFreshdeskConnectorInit:
    """Tests for FreshdeskConnector initialization and context manager."""

    def test_init(self, credentials):
        connector = FreshdeskConnector(credentials)
        assert connector.credentials is credentials
        assert connector._client is None

    @pytest.mark.asyncio
    async def test_context_manager(self, credentials):
        import httpx

        with patch.object(httpx, "AsyncClient") as mock_async_client_class:
            mock_async_client = AsyncMock()
            mock_async_client_class.return_value = mock_async_client

            async with FreshdeskConnector(credentials) as connector:
                # Trigger client creation
                await connector._get_client()
                assert connector._client is mock_async_client

            mock_async_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_exit_clears_client(self, credentials):
        import httpx

        with patch.object(httpx, "AsyncClient") as mock_async_client_class:
            mock_async_client = AsyncMock()
            mock_async_client_class.return_value = mock_async_client

            connector = FreshdeskConnector(credentials)
            await connector.__aenter__()
            await connector._get_client()
            assert connector._client is not None
            await connector.__aexit__(None, None, None)
            assert connector._client is None

    @pytest.mark.asyncio
    async def test_close_when_no_client(self, credentials):
        connector = FreshdeskConnector(credentials)
        assert connector._client is None
        await connector.close()
        assert connector._client is None

    @pytest.mark.asyncio
    async def test_get_client_reuses_existing(self, credentials):
        import httpx

        with patch.object(httpx, "AsyncClient") as mock_async_client_class:
            mock_async_client = AsyncMock()
            mock_async_client_class.return_value = mock_async_client

            connector = FreshdeskConnector(credentials)
            client1 = await connector._get_client()
            client2 = await connector._get_client()

            assert client1 is client2
            assert mock_async_client_class.call_count == 1

            await connector.close()


# =============================================================================
# API Request Tests
# =============================================================================


class TestApiRequest:
    """Tests for _request method."""

    @pytest.mark.asyncio
    async def test_request_success(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response({"id": 1, "subject": "Test"})
        result = await freshdesk_connector._request("GET", "/tickets/1")
        assert result["id"] == 1

    @pytest.mark.asyncio
    async def test_request_success_list(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response([{"id": 1}, {"id": 2}])
        result = await freshdesk_connector._request("GET", "/tickets")
        assert isinstance(result, list)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_request_http_error(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            {"errors": [{"message": "RecordNotFound"}]},
            status_code=404,
        )
        with pytest.raises(FreshdeskError) as exc_info:
            await freshdesk_connector._request("GET", "/tickets/999")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_request_http_error_no_json(self, freshdesk_connector, mock_httpx_client):
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "Internal Server Error"
        resp.json.side_effect = ValueError("No JSON")
        mock_httpx_client.request.return_value = resp
        with pytest.raises(FreshdeskError) as exc_info:
            await freshdesk_connector._request("GET", "/test")
        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_request_204_no_content(self, freshdesk_connector, mock_httpx_client):
        resp = MagicMock()
        resp.status_code = 204
        mock_httpx_client.request.return_value = resp
        result = await freshdesk_connector._request("DELETE", "/tickets/1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_request_rate_limit_429(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            {"errors": [{"message": "Rate limit exceeded"}]},
            status_code=429,
        )
        with pytest.raises(FreshdeskError) as exc_info:
            await freshdesk_connector._request("GET", "/tickets")
        assert exc_info.value.status_code == 429


# =============================================================================
# Ticket Operations Tests
# =============================================================================


class TestTicketOperations:
    """Tests for ticket CRUD operations."""

    @pytest.mark.asyncio
    async def test_get_tickets(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            [
                {"id": 1, "subject": "Issue 1", "status": 2},
                {"id": 2, "subject": "Issue 2", "status": 3},
            ]
        )
        tickets = await freshdesk_connector.get_tickets()
        assert len(tickets) == 2
        assert tickets[0].subject == "Issue 1"
        assert tickets[0].status == TicketStatus.OPEN
        assert tickets[1].status == TicketStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_tickets_with_filter(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response([{"id": 1, "status": 2}])
        await freshdesk_connector.get_tickets(filter="new_and_my_open")
        call_args = mock_httpx_client.request.call_args
        assert call_args.kwargs["params"]["filter"] == "new_and_my_open"

    @pytest.mark.asyncio
    async def test_get_tickets_with_requester_id(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response([])
        await freshdesk_connector.get_tickets(requester_id=123)
        call_args = mock_httpx_client.request.call_args
        assert call_args.kwargs["params"]["requester_id"] == 123

    @pytest.mark.asyncio
    async def test_get_tickets_with_company_id(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response([])
        await freshdesk_connector.get_tickets(company_id=456)
        call_args = mock_httpx_client.request.call_args
        assert call_args.kwargs["params"]["company_id"] == 456

    @pytest.mark.asyncio
    async def test_get_tickets_with_updated_since(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response([])
        since = datetime(2023, 1, 1, 0, 0, 0)
        await freshdesk_connector.get_tickets(updated_since=since)
        call_args = mock_httpx_client.request.call_args
        assert "2023-01-01T00:00:00Z" in call_args.kwargs["params"]["updated_since"]

    @pytest.mark.asyncio
    async def test_get_tickets_pagination(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response([])
        await freshdesk_connector.get_tickets(page=2, per_page=50)
        call_args = mock_httpx_client.request.call_args
        assert call_args.kwargs["params"]["page"] == 2
        assert call_args.kwargs["params"]["per_page"] == 50

    @pytest.mark.asyncio
    async def test_get_tickets_per_page_capped_at_100(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response([])
        await freshdesk_connector.get_tickets(per_page=200)
        call_args = mock_httpx_client.request.call_args
        assert call_args.kwargs["params"]["per_page"] == 100

    @pytest.mark.asyncio
    async def test_get_ticket(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            {"id": 1000, "subject": "Help needed", "status": 2}
        )
        ticket = await freshdesk_connector.get_ticket(1000)
        assert ticket.id == 1000
        assert ticket.subject == "Help needed"

    @pytest.mark.asyncio
    async def test_create_ticket(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            {
                "id": 2000,
                "subject": "New ticket",
                "description": "Description here",
                "status": 2,
                "priority": 2,
                "source": 1,
                "requester_id": 123,
            }
        )
        ticket = await freshdesk_connector.create_ticket(
            subject="New ticket",
            description="Description here",
            email="customer@example.com",
            priority=TicketPriority.MEDIUM,
            status=TicketStatus.OPEN,
            source=TicketSource.EMAIL,
        )
        assert ticket.id == 2000
        assert ticket.subject == "New ticket"

    @pytest.mark.asyncio
    async def test_create_ticket_with_requester_id(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            {"id": 2001, "subject": "Test", "status": 2, "requester_id": 456}
        )
        ticket = await freshdesk_connector.create_ticket(
            subject="Test",
            description="Test description",
            requester_id=456,
        )
        assert ticket.requester_id == 456

    @pytest.mark.asyncio
    async def test_create_ticket_with_all_options(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            {"id": 2002, "subject": "Full ticket", "status": 2, "requester_id": 0}
        )
        await freshdesk_connector.create_ticket(
            subject="Full ticket",
            description="Full description",
            email="test@example.com",
            priority=TicketPriority.URGENT,
            status=TicketStatus.OPEN,
            source=TicketSource.PORTAL,
            type="Incident",
            tags=["urgent", "billing"],
            group_id=5,
            responder_id=10,
            custom_fields={"cf_category": "billing"},
        )
        call_args = mock_httpx_client.request.call_args
        json_data = call_args.kwargs["json"]
        assert json_data["type"] == "Incident"
        assert json_data["tags"] == ["urgent", "billing"]
        assert json_data["group_id"] == 5
        assert json_data["responder_id"] == 10
        assert json_data["custom_fields"] == {"cf_category": "billing"}

    @pytest.mark.asyncio
    async def test_update_ticket(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            {"id": 1000, "subject": "Updated", "status": 3, "requester_id": 1}
        )
        ticket = await freshdesk_connector.update_ticket(
            1000,
            status=TicketStatus.PENDING,
            priority=TicketPriority.HIGH,
        )
        assert ticket.status == TicketStatus.PENDING

    @pytest.mark.asyncio
    async def test_update_ticket_with_all_options(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            {"id": 1000, "status": 4, "requester_id": 1}
        )
        await freshdesk_connector.update_ticket(
            1000,
            status=TicketStatus.RESOLVED,
            priority=TicketPriority.LOW,
            responder_id=20,
            group_id=10,
            tags=["resolved"],
            custom_fields={"cf_resolution": "Fixed"},
        )
        call_args = mock_httpx_client.request.call_args
        json_data = call_args.kwargs["json"]
        assert json_data["status"] == 4
        assert json_data["priority"] == 1
        assert json_data["responder_id"] == 20
        assert json_data["group_id"] == 10
        assert json_data["tags"] == ["resolved"]
        assert json_data["custom_fields"] == {"cf_resolution": "Fixed"}

    @pytest.mark.asyncio
    async def test_delete_ticket(self, freshdesk_connector, mock_httpx_client):
        resp = MagicMock()
        resp.status_code = 204
        mock_httpx_client.request.return_value = resp
        result = await freshdesk_connector.delete_ticket(1000)
        assert result is True


# =============================================================================
# Conversation Operations Tests
# =============================================================================


class TestConversationOperations:
    """Tests for ticket conversation operations."""

    @pytest.mark.asyncio
    async def test_get_conversations(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            [
                {"id": 1, "body": "First message", "user_id": 123, "private": False},
                {"id": 2, "body": "Internal note", "user_id": 456, "private": True},
            ]
        )
        conversations = await freshdesk_connector.get_conversations(1000)
        assert len(conversations) == 2
        assert conversations[0].body == "First message"
        assert conversations[1].private is True

    @pytest.mark.asyncio
    async def test_reply_to_ticket(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            {"id": 100, "body": "Thank you for contacting us.", "user_id": 10}
        )
        reply = await freshdesk_connector.reply_to_ticket(
            1000,
            body="Thank you for contacting us.",
        )
        assert reply.id == 100
        assert reply.body == "Thank you for contacting us."

    @pytest.mark.asyncio
    async def test_reply_to_ticket_with_cc(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            {"id": 101, "body": "CC reply", "user_id": 10}
        )
        await freshdesk_connector.reply_to_ticket(
            1000,
            body="CC reply",
            cc_emails=["manager@example.com", "team@example.com"],
        )
        call_args = mock_httpx_client.request.call_args
        json_data = call_args.kwargs["json"]
        assert json_data["cc_emails"] == ["manager@example.com", "team@example.com"]

    @pytest.mark.asyncio
    async def test_add_note(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            {"id": 200, "body": "Internal note", "user_id": 10, "private": True}
        )
        note = await freshdesk_connector.add_note(
            1000,
            body="Internal note",
            private=True,
        )
        assert note.id == 200
        assert note.body == "Internal note"
        assert note.private is True

    @pytest.mark.asyncio
    async def test_add_public_note(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            {"id": 201, "body": "Public note", "user_id": 10, "private": False}
        )
        await freshdesk_connector.add_note(
            1000,
            body="Public note",
            private=False,
        )
        call_args = mock_httpx_client.request.call_args
        json_data = call_args.kwargs["json"]
        assert json_data["private"] is False


# =============================================================================
# Contact Operations Tests
# =============================================================================


class TestContactOperations:
    """Tests for contact CRUD operations."""

    @pytest.mark.asyncio
    async def test_get_contacts(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            [
                {"id": 1, "name": "John Doe", "email": "john@test.com"},
                {"id": 2, "name": "Jane Smith", "email": "jane@test.com"},
            ]
        )
        contacts = await freshdesk_connector.get_contacts()
        assert len(contacts) == 2
        assert contacts[0].name == "John Doe"
        assert contacts[1].name == "Jane Smith"

    @pytest.mark.asyncio
    async def test_get_contacts_with_email_filter(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response([])
        await freshdesk_connector.get_contacts(email="john@test.com")
        call_args = mock_httpx_client.request.call_args
        assert call_args.kwargs["params"]["email"] == "john@test.com"

    @pytest.mark.asyncio
    async def test_get_contacts_with_company_filter(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response([])
        await freshdesk_connector.get_contacts(company_id=100)
        call_args = mock_httpx_client.request.call_args
        assert call_args.kwargs["params"]["company_id"] == 100

    @pytest.mark.asyncio
    async def test_get_contact(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            {"id": 12345, "name": "John Doe", "email": "john@test.com"}
        )
        contact = await freshdesk_connector.get_contact(12345)
        assert contact.id == 12345
        assert contact.name == "John Doe"

    @pytest.mark.asyncio
    async def test_create_contact(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            {"id": 99999, "name": "New Contact", "email": "new@test.com"}
        )
        contact = await freshdesk_connector.create_contact(
            name="New Contact",
            email="new@test.com",
        )
        assert contact.id == 99999
        assert contact.name == "New Contact"

    @pytest.mark.asyncio
    async def test_create_contact_with_all_options(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            {"id": 88888, "name": "Full Contact", "email": "full@test.com"}
        )
        await freshdesk_connector.create_contact(
            name="Full Contact",
            email="full@test.com",
            phone="+1-555-0100",
            company_id=100,
            job_title="Engineer",
        )
        call_args = mock_httpx_client.request.call_args
        json_data = call_args.kwargs["json"]
        assert json_data["name"] == "Full Contact"
        assert json_data["email"] == "full@test.com"
        assert json_data["phone"] == "+1-555-0100"
        assert json_data["company_id"] == 100
        assert json_data["job_title"] == "Engineer"


# =============================================================================
# Company Operations Tests
# =============================================================================


class TestCompanyOperations:
    """Tests for company CRUD operations."""

    @pytest.mark.asyncio
    async def test_get_companies(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            [
                {"id": 100, "name": "Acme Corp"},
                {"id": 101, "name": "Tech Inc"},
            ]
        )
        companies = await freshdesk_connector.get_companies()
        assert len(companies) == 2
        assert companies[0].name == "Acme Corp"

    @pytest.mark.asyncio
    async def test_get_companies_pagination(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response([])
        await freshdesk_connector.get_companies(page=2, per_page=50)
        call_args = mock_httpx_client.request.call_args
        assert call_args.kwargs["params"]["page"] == 2
        assert call_args.kwargs["params"]["per_page"] == 50

    @pytest.mark.asyncio
    async def test_get_company(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            {"id": 100, "name": "Acme Corp", "domains": ["acme.com"]}
        )
        company = await freshdesk_connector.get_company(100)
        assert company.id == 100
        assert company.domains == ["acme.com"]

    @pytest.mark.asyncio
    async def test_create_company(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            {"id": 200, "name": "New Org", "domains": ["neworg.com"]}
        )
        company = await freshdesk_connector.create_company(
            name="New Org",
            domains=["neworg.com"],
            description="A new organization",
        )
        assert company.id == 200
        assert company.name == "New Org"

    @pytest.mark.asyncio
    async def test_create_company_minimal(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response({"id": 201, "name": "Simple Org"})
        await freshdesk_connector.create_company(name="Simple Org")
        call_args = mock_httpx_client.request.call_args
        json_data = call_args.kwargs["json"]
        assert json_data == {"name": "Simple Org"}


# =============================================================================
# Agent Operations Tests
# =============================================================================


class TestAgentOperations:
    """Tests for agent operations."""

    @pytest.mark.asyncio
    async def test_get_agents(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            [
                {"id": 1, "contact": {"id": 10, "name": "Agent 1", "email": "agent1@test.com"}},
                {"id": 2, "contact": {"id": 20, "name": "Agent 2", "email": "agent2@test.com"}},
            ]
        )
        agents = await freshdesk_connector.get_agents()
        assert len(agents) == 2
        assert agents[0].name == "Agent 1"
        assert agents[1].name == "Agent 2"

    @pytest.mark.asyncio
    async def test_get_agents_pagination(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response([])
        await freshdesk_connector.get_agents(page=2, per_page=50)
        call_args = mock_httpx_client.request.call_args
        assert call_args.kwargs["params"]["page"] == 2
        assert call_args.kwargs["params"]["per_page"] == 50

    @pytest.mark.asyncio
    async def test_get_agent(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            {"id": 100, "contact": {"id": 200, "name": "Agent Smith", "email": "smith@test.com"}}
        )
        agent = await freshdesk_connector.get_agent(100)
        assert agent.id == 100
        assert agent.name == "Agent Smith"


# =============================================================================
# Search Operations Tests
# =============================================================================


class TestSearchOperations:
    """Tests for search operations."""

    @pytest.mark.asyncio
    async def test_search_tickets(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response(
            {
                "results": [
                    {"id": 1, "subject": "Login issue", "status": 2},
                    {"id": 2, "subject": "Cannot login", "status": 2},
                ]
            }
        )
        tickets = await freshdesk_connector.search_tickets("status:2 AND priority:4")
        assert len(tickets) == 2
        assert tickets[0].subject == "Login issue"

    @pytest.mark.asyncio
    async def test_search_tickets_empty_results(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response({"results": []})
        tickets = await freshdesk_connector.search_tickets("nonexistent")
        assert tickets == []

    @pytest.mark.asyncio
    async def test_search_tickets_query_format(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response({"results": []})
        await freshdesk_connector.search_tickets("status:2")
        call_args = mock_httpx_client.request.call_args
        assert call_args.kwargs["params"]["query"] == '"status:2"'


# =============================================================================
# Mock Data Generation Tests
# =============================================================================


class TestMockDataGenerators:
    """Tests for mock data helpers."""

    def test_get_mock_ticket(self):
        ticket = get_mock_ticket()
        assert ticket.id == 12345
        assert ticket.subject == "Product not working as expected"
        assert ticket.status == TicketStatus.OPEN
        assert ticket.priority == TicketPriority.HIGH
        assert ticket.source == TicketSource.EMAIL
        assert ticket.requester_id == 67890
        assert ticket.created_at is not None

    def test_get_mock_contact(self):
        contact = get_mock_contact()
        assert contact.id == 67890
        assert contact.name == "Jane Smith"
        assert contact.email == "jane.smith@example.com"
        assert contact.phone == "+1-555-0123"


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and unusual inputs."""

    def test_ticket_from_api_empty_tags(self):
        data = {"id": 1, "status": 2, "tags": []}
        ticket = FreshdeskTicket.from_api(data)
        assert ticket.tags == []

    def test_contact_from_api_empty_tags(self):
        data = {"id": 1, "name": "Test", "email": "test@test.com", "tags": []}
        contact = Contact.from_api(data)
        assert contact.tags == []

    def test_company_from_api_empty_domains(self):
        data = {"id": 1, "name": "Test", "domains": []}
        company = Company.from_api(data)
        assert company.domains == []

    def test_ticket_defaults(self):
        ticket = FreshdeskTicket(
            id=1,
            subject="Test",
            description="",
            description_text="",
            status=TicketStatus.OPEN,
            priority=TicketPriority.LOW,
            source=TicketSource.EMAIL,
            requester_id=1,
        )
        assert ticket.responder_id is None
        assert ticket.group_id is None
        assert ticket.tags == []
        assert ticket.custom_fields == {}
        assert ticket.is_escalated is False
        assert ticket.spam is False

    def test_contact_defaults(self):
        contact = Contact(
            id=1,
            name="Test",
            email="test@test.com",
        )
        assert contact.phone is None
        assert contact.mobile is None
        assert contact.company_id is None
        assert contact.language == "en"
        assert contact.tags == []

    @pytest.mark.asyncio
    async def test_get_tickets_empty_response(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response([])
        tickets = await freshdesk_connector.get_tickets()
        assert tickets == []

    @pytest.mark.asyncio
    async def test_get_tickets_dict_response(self, freshdesk_connector, mock_httpx_client):
        # In case API returns dict instead of list
        mock_httpx_client.request.return_value = _make_response({"error": "unexpected"})
        with pytest.raises(FreshdeskError, match="GET /tickets: expected list, got dict"):
            await freshdesk_connector.get_tickets()

    @pytest.mark.asyncio
    async def test_get_conversations_empty_response(self, freshdesk_connector, mock_httpx_client):
        mock_httpx_client.request.return_value = _make_response([])
        conversations = await freshdesk_connector.get_conversations(1000)
        assert conversations == []

    @pytest.mark.asyncio
    async def test_get_conversations_dict_response(self, freshdesk_connector, mock_httpx_client):
        # In case API returns dict instead of list
        mock_httpx_client.request.return_value = _make_response({"error": "unexpected"})
        with pytest.raises(
            FreshdeskError, match="GET /tickets/1000/conversations: expected list, got dict"
        ):
            await freshdesk_connector.get_conversations(1000)
