"""
Tests for Salesforce Enterprise Connector.

Tests the Salesforce CRM integration including:
- OAuth2 authentication flows
- SOQL query building
- Record syncing and pagination
- Search functionality
- Error handling and resilience
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from aragora.connectors.enterprise.crm.salesforce import (
    SalesforceConnector,
    SalesforceRecord,
    SALESFORCE_OBJECTS,
)
from aragora.connectors.enterprise.base import SyncState


class TestSalesforceConnectorInit:
    """Test SalesforceConnector initialization."""

    def test_default_objects(self):
        """Should use default objects when none specified."""
        connector = SalesforceConnector()
        assert "Account" in connector.objects
        assert "Contact" in connector.objects
        assert "Opportunity" in connector.objects

    def test_custom_objects(self):
        """Should accept custom objects."""
        connector = SalesforceConnector(
            objects=["Lead", "Case"],
            custom_objects=["CustomObject__c"],
        )
        assert connector.objects == ["Lead", "Case"]
        assert connector.custom_objects == ["CustomObject__c"]

    def test_connector_properties(self):
        """Should have correct connector properties."""
        connector = SalesforceConnector()
        assert connector.name == "Salesforce"
        assert connector.connector_id == "salesforce"

    def test_sandbox_configuration(self):
        """Should configure sandbox mode."""
        connector = SalesforceConnector(is_sandbox=True)
        assert connector.is_sandbox is True

    def test_bulk_api_configuration(self):
        """Should configure bulk API settings."""
        connector = SalesforceConnector(
            use_bulk_api=True,
            bulk_threshold=5000,
        )
        assert connector.use_bulk_api is True
        assert connector.bulk_threshold == 5000


class TestSalesforceAuthentication:
    """Test authentication flows."""

    @pytest.mark.asyncio
    async def test_oauth_refresh_token_flow(self):
        """Should refresh OAuth token successfully."""
        connector = SalesforceConnector()
        connector.credentials = MagicMock()
        connector.credentials.get_credential = AsyncMock(
            side_effect=lambda key: {
                "SALESFORCE_CLIENT_ID": "test_client_id",
                "SALESFORCE_CLIENT_SECRET": "test_secret",
                "SALESFORCE_REFRESH_TOKEN": "test_refresh_token",
            }.get(key)
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "access_token": "new_access_token",
                "instance_url": "https://test.salesforce.com",
                "expires_in": 7200,
            }
            mock_response.raise_for_status = MagicMock()

            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            token = await connector._get_access_token()

            assert token == "new_access_token"
            assert connector._instance_url_resolved == "https://test.salesforce.com"

    @pytest.mark.asyncio
    async def test_password_auth_flow(self):
        """Should authenticate with username/password."""
        connector = SalesforceConnector()
        connector.credentials = MagicMock()
        connector.credentials.get_credential = AsyncMock(
            side_effect=lambda key: {
                "SALESFORCE_CLIENT_ID": "test_client_id",
                "SALESFORCE_CLIENT_SECRET": "test_secret",
                "SALESFORCE_USERNAME": "user@test.com",
                "SALESFORCE_PASSWORD": "password123",
                "SALESFORCE_SECURITY_TOKEN": "token456",
            }.get(key)
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "access_token": "password_access_token",
                "instance_url": "https://test.salesforce.com",
            }
            mock_response.raise_for_status = MagicMock()

            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            token = await connector._get_access_token()

            assert token == "password_access_token"

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Should raise error when credentials missing."""
        connector = SalesforceConnector()
        connector.credentials = MagicMock()
        connector.credentials.get_credential = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="credentials not configured"):
            await connector._get_access_token()


class TestSOQLQueryBuilding:
    """Test SOQL query construction."""

    def test_basic_query(self):
        """Should build basic SOQL query."""
        connector = SalesforceConnector()
        fields = ["Id", "Name", "Type"]

        soql = connector._build_soql_query("Account", fields)

        assert "SELECT Id, Name, Type FROM Account" in soql
        assert "IsDeleted = false" in soql
        assert "ORDER BY LastModifiedDate ASC" in soql

    def test_query_with_filter(self):
        """Should include custom filter."""
        connector = SalesforceConnector(soql_filter="Type = 'Customer'")
        fields = ["Id", "Name"]

        soql = connector._build_soql_query("Account", fields)

        assert "(Type = 'Customer')" in soql

    def test_incremental_query(self):
        """Should add date filter for incremental sync."""
        connector = SalesforceConnector()
        fields = ["Id", "Name"]
        last_sync = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        soql = connector._build_soql_query("Account", fields, last_sync=last_sync)

        assert "LastModifiedDate > 2024-01-15T12:00:00Z" in soql

    def test_include_archived(self):
        """Should not exclude archived when configured."""
        connector = SalesforceConnector(exclude_archived=False)
        fields = ["Id", "Name"]

        soql = connector._build_soql_query("Account", fields)

        assert "IsDeleted = false" not in soql


class TestRecordParsing:
    """Test record parsing and conversion."""

    def test_parse_datetime(self):
        """Should parse Salesforce datetime format."""
        connector = SalesforceConnector()

        # Standard format
        result = connector._parse_datetime("2024-01-15T10:30:00.000Z")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

        # Without milliseconds
        result = connector._parse_datetime("2024-01-15T10:30:00Z")
        assert result is not None

        # None input
        assert connector._parse_datetime(None) is None

        # Invalid format
        assert connector._parse_datetime("invalid") is None

    def test_record_to_text(self):
        """Should convert record to text representation."""
        connector = SalesforceConnector()
        record = {
            "Id": "001xx000003DGbYAAW",
            "Name": "Test Account",
            "Type": "Customer",
            "Industry": "Technology",
            "attributes": {"type": "Account"},
        }

        text = connector._record_to_text(record, "Account")

        assert "# Account: Test Account" in text
        assert "**Type**: Customer" in text
        assert "**Industry**: Technology" in text
        assert "attributes" not in text  # Should be skipped


class TestSyncItems:
    """Test sync_items functionality."""

    @pytest.mark.asyncio
    async def test_sync_items_success(self):
        """Should yield sync items for records."""
        connector = SalesforceConnector(
            instance_url="https://test.salesforce.com",
            objects=["Account"],
        )
        connector._access_token = "test_token"
        connector._instance_url_resolved = "https://test.salesforce.com"

        mock_records = [
            {
                "Id": "001xx000003DGbY",
                "Name": "Test Account",
                "CreatedDate": "2024-01-15T10:00:00Z",
                "LastModifiedDate": "2024-01-16T10:00:00Z",
                "OwnerId": "005xx000001SvAm",
            }
        ]

        with patch.object(connector, "_query") as mock_query:

            async def query_generator(*args, **kwargs):
                for record in mock_records:
                    yield record

            mock_query.return_value = query_generator()

            state = SyncState(connector_id="salesforce")
            items = []
            async for item in connector.sync_items(state):
                items.append(item)

            assert len(items) == 1
            assert items[0].title == "Account: Test Account"
            assert "salesforce/Account/001xx000003DGbY" in items[0].source_id

    @pytest.mark.asyncio
    async def test_sync_multiple_objects(self):
        """Should sync multiple object types."""
        connector = SalesforceConnector(
            objects=["Account", "Contact"],
        )
        connector._access_token = "test_token"
        connector._instance_url_resolved = "https://test.salesforce.com"

        account_records = [{"Id": "001xx1", "Name": "Account 1"}]
        contact_records = [{"Id": "003xx1", "Name": "Contact 1"}]

        call_count = 0

        async def mock_query_gen(*args, **kwargs):
            nonlocal call_count
            records = account_records if call_count == 0 else contact_records
            call_count += 1
            for r in records:
                yield r

        with patch.object(connector, "_query", side_effect=mock_query_gen):
            state = SyncState(connector_id="salesforce")
            items = []
            async for item in connector.sync_items(state):
                items.append(item)

            # Should have synced both objects
            assert len(items) == 2


class TestSearch:
    """Test search functionality."""

    @pytest.mark.asyncio
    async def test_search_success(self):
        """Should search records using SOSL."""
        connector = SalesforceConnector(
            objects=["Account", "Contact"],
        )
        connector._access_token = "test_token"
        connector._instance_url_resolved = "https://test.salesforce.com"

        mock_response = {
            "searchRecords": [
                {
                    "Id": "001xx000003DGbY",
                    "Name": "Acme Corp",
                    "attributes": {"type": "Account"},
                },
            ]
        }

        with patch.object(connector, "_api_request", return_value=mock_response):
            results = await connector.search("Acme")

            assert len(results) == 1
            assert results[0].title == "Account: Acme Corp"

    @pytest.mark.asyncio
    async def test_search_error_handling(self):
        """Should handle search errors gracefully."""
        connector = SalesforceConnector()
        connector._access_token = "test_token"

        with patch.object(connector, "_api_request", side_effect=RuntimeError("API Error")):
            results = await connector.search("test")

            assert results == []


class TestFetch:
    """Test individual record fetch."""

    @pytest.mark.asyncio
    async def test_fetch_success(self):
        """Should fetch individual record."""
        connector = SalesforceConnector()
        connector._access_token = "test_token"
        connector._instance_url_resolved = "https://test.salesforce.com"

        mock_record = {
            "Id": "001xx000003DGbY",
            "Name": "Test Account",
            "Type": "Customer",
            "OwnerId": "005xx1",
        }

        with patch.object(connector, "_api_request", return_value=mock_record):
            result = await connector.fetch("sf-Account-001xx000003DGbY")

            assert result is not None
            assert result.title == "Account: Test Account"
            assert result.metadata["object_type"] == "Account"

    @pytest.mark.asyncio
    async def test_fetch_invalid_id(self):
        """Should return None for invalid evidence ID."""
        connector = SalesforceConnector()

        result = await connector.fetch("invalid-id-format")

        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_error_handling(self):
        """Should handle fetch errors gracefully."""
        connector = SalesforceConnector()
        connector._access_token = "test_token"

        with patch.object(connector, "_api_request", side_effect=RuntimeError("Not Found")):
            result = await connector.fetch("sf-Account-nonexistent")

            assert result is None


class TestRelatedRecords:
    """Test related record retrieval."""

    @pytest.mark.asyncio
    async def test_get_account_contacts(self):
        """Should get contacts for an account."""
        connector = SalesforceConnector()
        connector._access_token = "test_token"

        mock_contacts = [
            {"Id": "003xx1", "FirstName": "John", "LastName": "Doe"},
            {"Id": "003xx2", "FirstName": "Jane", "LastName": "Smith"},
        ]

        async def mock_query_gen(*args, **kwargs):
            for c in mock_contacts:
                yield c

        with patch.object(connector, "_query", return_value=mock_query_gen()):
            contacts = await connector.get_account_contacts("001xx1")

            assert len(contacts) == 2
            assert contacts[0]["FirstName"] == "John"

    @pytest.mark.asyncio
    async def test_get_account_opportunities(self):
        """Should get opportunities for an account."""
        connector = SalesforceConnector()
        connector._access_token = "test_token"

        mock_opps = [
            {"Id": "006xx1", "Name": "Big Deal", "Amount": 100000, "IsClosed": False},
        ]

        async def mock_query_gen(*args, **kwargs):
            for o in mock_opps:
                yield o

        with patch.object(connector, "_query", return_value=mock_query_gen()):
            opps = await connector.get_account_opportunities("001xx1")

            assert len(opps) == 1
            assert opps[0]["Name"] == "Big Deal"


class TestSalesforceObjects:
    """Test predefined Salesforce objects."""

    def test_account_fields(self):
        """Should have Account object with expected fields."""
        assert "Account" in SALESFORCE_OBJECTS
        account = SALESFORCE_OBJECTS["Account"]
        assert "Id" in account["fields"]
        assert "Name" in account["fields"]
        assert "Industry" in account["fields"]

    def test_contact_fields(self):
        """Should have Contact object with expected fields."""
        assert "Contact" in SALESFORCE_OBJECTS
        contact = SALESFORCE_OBJECTS["Contact"]
        assert "FirstName" in contact["fields"]
        assert "LastName" in contact["fields"]
        assert "Email" in contact["fields"]

    def test_opportunity_fields(self):
        """Should have Opportunity object with expected fields."""
        assert "Opportunity" in SALESFORCE_OBJECTS
        opp = SALESFORCE_OBJECTS["Opportunity"]
        assert "StageName" in opp["fields"]
        assert "Amount" in opp["fields"]
        assert "CloseDate" in opp["fields"]

    def test_lead_fields(self):
        """Should have Lead object with expected fields."""
        assert "Lead" in SALESFORCE_OBJECTS
        lead = SALESFORCE_OBJECTS["Lead"]
        assert "Status" in lead["fields"]
        assert "Company" in lead["fields"]
        assert "IsConverted" in lead["fields"]

    def test_case_fields(self):
        """Should have Case object with expected fields."""
        assert "Case" in SALESFORCE_OBJECTS
        case = SALESFORCE_OBJECTS["Case"]
        assert "CaseNumber" in case["fields"]
        assert "Status" in case["fields"]
        assert "Priority" in case["fields"]
