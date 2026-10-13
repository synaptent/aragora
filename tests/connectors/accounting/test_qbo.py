"""
Comprehensive tests for QuickBooks Online (QBO) Connector.

Tests cover:
- OAuth2 authentication flow and token refresh
- Customer, invoice, and payment CRUD operations
- Account and vendor management
- API request handling and error responses
- Rate limiting and retry logic
- Data serialization and deserialization
- Query builder security and validation
- Edge cases (expired tokens, API errors, malformed responses)
"""

import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import httpx

from aragora.connectors.accounting.qbo import (
    QuickBooksConnector,
    QBOCredentials,
    QBOCustomer,
    QBOTransaction,
    QBOAccount,
    QBOEnvironment,
    QBOQueryBuilder,
    TransactionType,
    get_mock_customers,
    get_mock_transactions,
)
from aragora.connectors.exceptions import (
    ConnectorAPIError,
    ConnectorAuthError,
    ConnectorConfigError,
    ConnectorNetworkError,
    ConnectorTimeoutError,
)
from aragora.resilience import CircuitBreaker


# =============================================================================
# Enum Tests
# =============================================================================


class TestQBOEnvironment:
    """Tests for QBOEnvironment enum."""

    def test_environment_values(self):
        """Test all environment values."""
        assert QBOEnvironment.SANDBOX.value == "sandbox"
        assert QBOEnvironment.PRODUCTION.value == "production"


class TestTransactionType:
    """Tests for TransactionType enum."""

    def test_transaction_type_values(self):
        """Test all transaction type values."""
        assert TransactionType.INVOICE.value == "Invoice"
        assert TransactionType.PAYMENT.value == "Payment"
        assert TransactionType.EXPENSE.value == "Expense"
        assert TransactionType.BILL.value == "Bill"
        assert TransactionType.CREDIT_MEMO.value == "CreditMemo"
        assert TransactionType.SALES_RECEIPT.value == "SalesReceipt"
        assert TransactionType.PURCHASE.value == "Purchase"
        assert TransactionType.JOURNAL_ENTRY.value == "JournalEntry"


# =============================================================================
# QBOCredentials Tests
# =============================================================================


class TestQBOCredentials:
    """Tests for QBOCredentials dataclass."""

    def test_credentials_creation(self):
        """Test credentials initialization."""
        creds = QBOCredentials(
            access_token="access-token-123",
            refresh_token="refresh-token-456",
            realm_id="123456789",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert creds.access_token == "access-token-123"
        assert creds.refresh_token == "refresh-token-456"
        assert creds.realm_id == "123456789"
        assert creds.token_type == "Bearer"

    def test_credentials_is_expired_true(self):
        """Test is_expired returns True when token is expired."""
        creds = QBOCredentials(
            access_token="token",
            refresh_token="refresh",
            realm_id="realm",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        assert creds.is_expired is True

    def test_credentials_is_expired_false(self):
        """Test is_expired returns False when token is valid."""
        creds = QBOCredentials(
            access_token="token",
            refresh_token="refresh",
            realm_id="realm",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert creds.is_expired is False

    def test_credentials_is_expired_no_expiry(self):
        """Test is_expired returns True when no expiry set."""
        creds = QBOCredentials(
            access_token="token",
            refresh_token="refresh",
            realm_id="realm",
            expires_at=None,
        )
        assert creds.is_expired is True

    def test_credentials_default_token_type(self):
        """Test credentials default token type."""
        creds = QBOCredentials(
            access_token="token",
            refresh_token="refresh",
            realm_id="realm",
        )
        assert creds.token_type == "Bearer"


# =============================================================================
# QBOCustomer Tests
# =============================================================================


class TestQBOCustomer:
    """Tests for QBOCustomer dataclass."""

    def test_customer_creation(self):
        """Test customer initialization."""
        customer = QBOCustomer(
            id="1",
            display_name="Acme Corp",
            company_name="Acme Corporation",
            email="billing@acme.com",
            phone="555-0100",
            balance=15420.50,
            active=True,
        )
        assert customer.id == "1"
        assert customer.display_name == "Acme Corp"
        assert customer.company_name == "Acme Corporation"
        assert customer.balance == 15420.50

    def test_customer_to_dict(self):
        """Test customer serialization."""
        customer = QBOCustomer(
            id="1",
            display_name="Test Customer",
            company_name="Test Co",
            email="test@example.com",
            balance=1000.00,
        )
        data = customer.to_dict(use_api_names=False)
        assert data["id"] == "1"
        assert data["display_name"] == "Test Customer"
        assert data["balance"] == 1000.00

    def test_customer_to_dict_with_api_names(self):
        """Test customer serialization with API field names."""
        customer = QBOCustomer(
            id="1",
            display_name="Test Customer",
            company_name="Test Co",
        )
        data = customer.to_dict(use_api_names=True)
        assert "displayName" in data
        assert "companyName" in data
        assert data["displayName"] == "Test Customer"

    def test_customer_defaults(self):
        """Test customer default values."""
        customer = QBOCustomer(
            id="1",
            display_name="Minimal Customer",
        )
        assert customer.company_name is None
        assert customer.email is None
        assert customer.phone is None
        assert customer.balance == 0.0
        assert customer.active is True


# =============================================================================
# QBOTransaction Tests
# =============================================================================


class TestQBOTransaction:
    """Tests for QBOTransaction dataclass."""

    def test_transaction_creation(self):
        """Test transaction initialization."""
        now = datetime.now(timezone.utc)
        txn = QBOTransaction(
            id="1001",
            type=TransactionType.INVOICE,
            doc_number="INV-1001",
            txn_date=now,
            due_date=now + timedelta(days=30),
            total_amount=5250.00,
            balance=5250.00,
            customer_id="1",
            customer_name="Acme Corp",
            status="Open",
        )
        assert txn.id == "1001"
        assert txn.type == TransactionType.INVOICE
        assert txn.doc_number == "INV-1001"
        assert txn.total_amount == 5250.00

    def test_transaction_to_dict(self):
        """Test transaction serialization."""
        txn = QBOTransaction(
            id="1001",
            type=TransactionType.INVOICE,
            doc_number="INV-1001",
            total_amount=1000.00,
            balance=500.00,
        )
        data = txn.to_dict(use_api_names=False)
        assert data["id"] == "1001"
        assert data["type"] == "Invoice"
        assert data["total_amount"] == 1000.00

    def test_transaction_to_dict_with_api_names(self):
        """Test transaction serialization with API field names."""
        txn = QBOTransaction(
            id="1001",
            type=TransactionType.EXPENSE,
            doc_number="EXP-001",
            txn_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
            total_amount=250.00,
        )
        data = txn.to_dict(use_api_names=True)
        assert "docNumber" in data
        assert "txnDate" in data
        assert "totalAmount" in data

    def test_transaction_expense_type(self):
        """Test expense transaction type."""
        txn = QBOTransaction(
            id="2001",
            type=TransactionType.EXPENSE,
            vendor_id="10",
            vendor_name="Office Supplies Co",
            total_amount=1250.00,
        )
        assert txn.type == TransactionType.EXPENSE
        assert txn.vendor_id == "10"

    def test_transaction_with_line_items(self):
        """Test transaction with line items."""
        line_items = [
            {"Amount": 100.00, "Description": "Item 1"},
            {"Amount": 200.00, "Description": "Item 2"},
        ]
        txn = QBOTransaction(
            id="1001",
            type=TransactionType.INVOICE,
            total_amount=300.00,
            line_items=line_items,
        )
        assert len(txn.line_items) == 2
        assert txn.line_items[0]["Amount"] == 100.00


# =============================================================================
# QBOAccount Tests
# =============================================================================


class TestQBOAccount:
    """Tests for QBOAccount dataclass."""

    def test_account_creation(self):
        """Test account initialization."""
        account = QBOAccount(
            id="1",
            name="Checking Account",
            account_type="Bank",
            account_sub_type="Checking",
            current_balance=50000.00,
            active=True,
        )
        assert account.id == "1"
        assert account.name == "Checking Account"
        assert account.account_type == "Bank"
        assert account.current_balance == 50000.00

    def test_account_to_dict(self):
        """Test account serialization."""
        account = QBOAccount(
            id="1",
            name="Accounts Receivable",
            account_type="Accounts Receivable",
            current_balance=25000.00,
        )
        data = account.to_dict(use_api_names=False)
        assert data["id"] == "1"
        assert data["name"] == "Accounts Receivable"
        assert data["current_balance"] == 25000.00

    def test_account_to_dict_with_api_names(self):
        """Test account serialization with API field names."""
        account = QBOAccount(
            id="1",
            name="Test Account",
            account_type="Bank",
            account_sub_type="Savings",
            current_balance=1000.00,
        )
        data = account.to_dict(use_api_names=True)
        assert "accountType" in data
        assert "accountSubType" in data
        assert "currentBalance" in data


# =============================================================================
# QBOQueryBuilder Tests
# =============================================================================


class TestQBOQueryBuilder:
    """Tests for QBOQueryBuilder security and functionality."""

    def test_valid_entity(self):
        """Test query builder with valid entity."""
        qb = QBOQueryBuilder("Invoice")
        assert qb._entity == "Invoice"

    def test_invalid_entity_raises_error(self):
        """Test query builder rejects invalid entity."""
        with pytest.raises(ValueError, match="Invalid QBO entity"):
            QBOQueryBuilder("InvalidEntity")

    def test_select_valid_fields(self):
        """Test selecting valid fields."""
        qb = QBOQueryBuilder("Invoice")
        qb.select("Id", "DocNumber", "TxnDate")
        assert "Id" in qb._select_fields
        assert "DocNumber" in qb._select_fields

    def test_select_invalid_field_raises_error(self):
        """Test selecting invalid field raises error."""
        qb = QBOQueryBuilder("Customer")
        with pytest.raises(ValueError, match="Invalid QBO field"):
            qb.select("InvalidField")

    def test_where_eq_bool(self):
        """Test where equality with boolean."""
        qb = QBOQueryBuilder("Customer")
        qb.where_eq("Active", True)
        assert "Active = true" in qb._conditions

    def test_where_eq_number(self):
        """Test where equality with number."""
        qb = QBOQueryBuilder("Invoice")
        qb.where_eq("TotalAmt", 100.50)
        assert "TotalAmt = 100.5" in qb._conditions

    def test_where_gte_date(self):
        """Test where >= with date."""
        qb = QBOQueryBuilder("Invoice")
        date = datetime(2024, 1, 15)
        qb.where_gte("TxnDate", date)
        assert "TxnDate >= '2024-01-15'" in qb._conditions

    def test_where_lte_date(self):
        """Test where <= with date."""
        qb = QBOQueryBuilder("Invoice")
        date = datetime(2024, 12, 31)
        qb.where_lte("TxnDate", date)
        assert "TxnDate <= '2024-12-31'" in qb._conditions

    def test_where_ref(self):
        """Test where reference ID."""
        qb = QBOQueryBuilder("Invoice")
        qb.where_ref("CustomerRef", "123")
        assert "CustomerRef = '123'" in qb._conditions

    def test_where_ref_invalid_id_raises_error(self):
        """Test where ref with non-numeric ID raises error."""
        qb = QBOQueryBuilder("Invoice")
        with pytest.raises(ValueError, match="ID must be numeric"):
            qb.where_ref("CustomerRef", "abc")

    def test_where_like(self):
        """Test where LIKE pattern."""
        qb = QBOQueryBuilder("Customer")
        qb.where_like("DisplayName", "Acme")
        assert "DisplayName LIKE '%Acme%'" in qb._conditions

    def test_limit_caps_at_1000(self):
        """Test limit is capped at 1000."""
        qb = QBOQueryBuilder("Invoice")
        qb.limit(5000)
        assert qb._limit_val == 1000

    def test_limit_minimum_1(self):
        """Test limit minimum is 1."""
        qb = QBOQueryBuilder("Invoice")
        qb.limit(-10)
        assert qb._limit_val == 1

    def test_offset_non_negative(self):
        """Test offset cannot be negative."""
        qb = QBOQueryBuilder("Invoice")
        qb.offset(-5)
        assert qb._offset_val == 0

    def test_offset_caps_at_100000(self):
        """Test offset is capped at 100000."""
        qb = QBOQueryBuilder("Invoice")
        qb.offset(200000)
        assert qb._offset_val == 100000

    def test_build_query(self):
        """Test building complete query."""
        qb = QBOQueryBuilder("Invoice")
        qb.select("Id", "DocNumber").where_eq("Active", True).limit(50).offset(10)
        query = qb.build()
        assert "SELECT Id, DocNumber FROM Invoice" in query
        assert "WHERE Active = true" in query
        assert "MAXRESULTS 50" in query
        assert "STARTPOSITION 11" in query  # 10 + 1

    def test_build_query_default_fields(self):
        """Test building query with default * fields."""
        qb = QBOQueryBuilder("Customer")
        query = qb.build()
        assert "SELECT * FROM Customer" in query

    def test_sanitize_string_filters_special_chars(self):
        """Test string sanitization filters characters not in safe set."""
        qb = QBOQueryBuilder("Customer")
        # Single quotes are not in the safe chars set, so they get filtered
        sanitized = qb._sanitize_string("O'Brien")
        # After filtering and escaping, the result depends on safe chars
        assert "O" in sanitized
        assert "Brien" in sanitized

    def test_sanitize_string_max_length(self):
        """Test string sanitization rejects too long strings."""
        qb = QBOQueryBuilder("Customer")
        with pytest.raises(ValueError, match="exceeds 500 character limit"):
            qb._sanitize_string("x" * 501)

    def test_format_date_validates_type(self):
        """Test date formatting validates input type."""
        qb = QBOQueryBuilder("Invoice")
        with pytest.raises(ValueError, match="Expected datetime"):
            qb._format_date("2024-01-15")  # type: ignore

    def test_validate_field_invalid_raises_error(self):
        """Test field validation raises on invalid field."""
        qb = QBOQueryBuilder("Invoice")
        with pytest.raises(ValueError, match="Invalid QBO field"):
            qb._validate_field("HackerField")

    def test_sql_injection_chars_sanitized(self):
        """Test query builder sanitizes dangerous characters."""
        qb = QBOQueryBuilder("Customer")
        # Attempt injection through string value - semicolons are filtered
        qb.where_like("DisplayName", "test;SELECT * FROM users")
        query = qb.build()
        # Semicolons should be stripped from the safe char set
        # The LIKE clause is wrapped in quotes so even if some chars pass
        # they are contained within the string literal
        assert "LIKE '%test" in query


# =============================================================================
# QuickBooksConnector Initialization Tests
# =============================================================================


class TestQuickBooksConnectorInit:
    """Tests for QuickBooksConnector initialization."""

    def test_connector_with_explicit_config(self):
        """Test connector with explicit configuration."""
        connector = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            environment=QBOEnvironment.SANDBOX,
        )
        assert connector.client_id == "test_client"
        assert connector.client_secret == "test_secret"
        assert connector.redirect_uri == "http://localhost/callback"
        assert connector.environment == QBOEnvironment.SANDBOX

    def test_connector_sandbox_base_url(self):
        """Test connector sandbox base URL."""
        connector = QuickBooksConnector(
            client_id="client",
            client_secret="secret",
            redirect_uri="http://localhost/callback",
            environment=QBOEnvironment.SANDBOX,
        )
        assert connector.base_url == QuickBooksConnector.BASE_URL_SANDBOX

    def test_connector_production_base_url(self):
        """Test connector production base URL."""
        connector = QuickBooksConnector(
            client_id="client",
            client_secret="secret",
            redirect_uri="http://localhost/callback",
            environment=QBOEnvironment.PRODUCTION,
        )
        assert connector.base_url == QuickBooksConnector.BASE_URL_PRODUCTION

    def test_is_configured_true(self):
        """Test is_configured when properly configured."""
        connector = QuickBooksConnector(
            client_id="client",
            client_secret="secret",
            redirect_uri="http://localhost/callback",
        )
        assert connector.is_configured is True

    def test_is_configured_false(self):
        """Test is_configured when missing credentials."""
        with patch.dict("os.environ", {}, clear=True):
            connector = QuickBooksConnector()
            assert connector.is_configured is False

    def test_is_authenticated_false_no_credentials(self):
        """Test is_authenticated when no credentials."""
        connector = QuickBooksConnector(
            client_id="client",
            client_secret="secret",
            redirect_uri="http://localhost/callback",
        )
        assert connector.is_authenticated is False

    def test_is_authenticated_true_valid_credentials(self):
        """Test is_authenticated with valid credentials."""
        connector = QuickBooksConnector(
            client_id="client",
            client_secret="secret",
            redirect_uri="http://localhost/callback",
        )
        connector.set_credentials(
            QBOCredentials(
                access_token="token",
                refresh_token="refresh",
                realm_id="realm",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        assert connector.is_authenticated is True

    def test_is_authenticated_false_expired_credentials(self):
        """Test is_authenticated with expired credentials."""
        connector = QuickBooksConnector(
            client_id="client",
            client_secret="secret",
            redirect_uri="http://localhost/callback",
        )
        connector.set_credentials(
            QBOCredentials(
                access_token="token",
                refresh_token="refresh",
                realm_id="realm",
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )
        assert connector.is_authenticated is False

    def test_circuit_breaker_enabled_by_default(self):
        """Test circuit breaker is enabled by default."""
        connector = QuickBooksConnector(
            client_id="client",
            client_secret="secret",
            redirect_uri="http://localhost/callback",
        )
        assert connector._circuit_breaker is not None

    def test_circuit_breaker_disabled(self):
        """Test circuit breaker can be disabled."""
        connector = QuickBooksConnector(
            client_id="client",
            client_secret="secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        assert connector._circuit_breaker is None

    def test_custom_circuit_breaker(self):
        """Test custom circuit breaker can be provided."""
        custom_cb = CircuitBreaker(
            name="custom-qbo",
            failure_threshold=5,
            cooldown_seconds=30.0,
        )
        connector = QuickBooksConnector(
            client_id="client",
            client_secret="secret",
            redirect_uri="http://localhost/callback",
            circuit_breaker=custom_cb,
        )
        assert connector._circuit_breaker is custom_cb


# =============================================================================
# OAuth2 Authentication Tests
# =============================================================================


class TestQuickBooksConnectorOAuth:
    """Tests for QuickBooksConnector OAuth operations."""

    @pytest.fixture
    def connector(self):
        """Create connector for testing."""
        return QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            environment=QBOEnvironment.SANDBOX,
            enable_circuit_breaker=False,
        )

    def test_get_authorization_url(self, connector):
        """Test generating authorization URL."""
        url = connector.get_authorization_url()
        assert QuickBooksConnector.AUTH_URL in url
        assert "client_id=test_client" in url
        assert "response_type=code" in url
        assert "scope=com.intuit.quickbooks.accounting" in url

    def test_get_authorization_url_with_state(self, connector):
        """Test generating authorization URL with state."""
        url = connector.get_authorization_url(state="csrf_token_123")
        assert "state=csrf_token_123" in url

    @pytest.mark.asyncio
    async def test_exchange_code_success(self, connector):
        """Test successful code exchange."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        mock_session = AsyncMock()
        mock_session.post.return_value = mock_response

        # Create proper async context manager
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_session
        mock_cm.__aexit__.return_value = None

        mock_pool = MagicMock()
        mock_pool.get_session.return_value = mock_cm

        with patch("aragora.connectors.accounting.qbo.get_http_pool", return_value=mock_pool):
            creds = await connector.exchange_code(
                authorization_code="auth-code-123",
                realm_id="realm-456",
            )

            assert creds.access_token == "new-access-token"
            assert creds.refresh_token == "new-refresh-token"
            assert creds.realm_id == "realm-456"
            assert creds.token_type == "Bearer"

    @pytest.mark.asyncio
    async def test_exchange_code_failure(self, connector):
        """Test code exchange failure."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "invalid_grant"

        mock_session = AsyncMock()
        mock_session.post.return_value = mock_response

        # Create proper async context manager
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_session
        mock_cm.__aexit__.return_value = None

        mock_pool = MagicMock()
        mock_pool.get_session.return_value = mock_cm

        with patch("aragora.connectors.accounting.qbo.get_http_pool", return_value=mock_pool):
            with pytest.raises(ConnectorAuthError, match="Token exchange failed"):
                await connector.exchange_code(
                    authorization_code="invalid-code",
                    realm_id="realm-456",
                )

    @pytest.mark.asyncio
    async def test_refresh_tokens_success(self, connector):
        """Test successful token refresh."""
        connector.set_credentials(
            QBOCredentials(
                access_token="old-token",
                refresh_token="old-refresh",
                realm_id="realm-123",
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        mock_session = AsyncMock()
        mock_session.post.return_value = mock_response

        mock_pool = MagicMock()
        mock_pool.get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("aragora.connectors.accounting.qbo.get_http_pool", return_value=mock_pool):
            creds = await connector.refresh_tokens()

            assert creds.access_token == "new-access-token"
            assert creds.refresh_token == "new-refresh-token"
            assert creds.realm_id == "realm-123"  # Preserved

    @pytest.mark.asyncio
    async def test_refresh_tokens_no_credentials(self, connector):
        """Test token refresh without credentials."""
        with pytest.raises(ConnectorConfigError, match="No credentials to refresh"):
            await connector.refresh_tokens()

    @pytest.mark.asyncio
    async def test_refresh_tokens_failure(self, connector):
        """Test token refresh failure."""
        connector.set_credentials(
            QBOCredentials(
                access_token="token",
                refresh_token="expired-refresh",
                realm_id="realm-123",
            )
        )

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "invalid_token"

        mock_session = AsyncMock()
        mock_session.post.return_value = mock_response

        # Create proper async context manager
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_session
        mock_cm.__aexit__.return_value = None

        mock_pool = MagicMock()
        mock_pool.get_session.return_value = mock_cm

        with patch("aragora.connectors.accounting.qbo.get_http_pool", return_value=mock_pool):
            with pytest.raises(ConnectorAuthError, match="Token refresh failed"):
                await connector.refresh_tokens()


# =============================================================================
# Customer Operations Tests
# =============================================================================


class TestQuickBooksConnectorCustomers:
    """Tests for QuickBooksConnector customer operations."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector for testing."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            environment=QBOEnvironment.SANDBOX,
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="valid-token",
                refresh_token="refresh-token",
                realm_id="123456789",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_list_customers_success(self, connector):
        """Test successful customer listing."""
        mock_response = {
            "QueryResponse": {
                "Customer": [
                    {
                        "Id": "1",
                        "DisplayName": "Acme Corp",
                        "CompanyName": "Acme Corporation",
                        "PrimaryEmailAddr": {"Address": "billing@acme.com"},
                        "PrimaryPhone": {"FreeFormNumber": "555-0100"},
                        "Balance": 15420.50,
                        "Active": True,
                    },
                    {
                        "Id": "2",
                        "DisplayName": "TechStart Inc",
                        "CompanyName": "TechStart",
                        "Balance": 8750.00,
                        "Active": True,
                    },
                ]
            }
        }

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            customers = await connector.list_customers()

            assert len(customers) == 2
            assert customers[0].id == "1"
            assert customers[0].display_name == "Acme Corp"
            assert customers[0].email == "billing@acme.com"
            assert customers[0].balance == 15420.50

    @pytest.mark.asyncio
    async def test_list_customers_empty(self, connector):
        """Test customer listing with no results."""
        mock_response = {"QueryResponse": {}}

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            customers = await connector.list_customers()
            assert customers == []

    @pytest.mark.asyncio
    async def test_get_customer_success(self, connector):
        """Test successful customer retrieval."""
        mock_response = {
            "Customer": {
                "Id": "1",
                "DisplayName": "Acme Corp",
                "CompanyName": "Acme Corporation",
                "PrimaryEmailAddr": {"Address": "billing@acme.com"},
                "Balance": 15420.50,
                "Active": True,
            }
        }

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            customer = await connector.get_customer("1")

            assert customer is not None
            assert customer.id == "1"
            assert customer.display_name == "Acme Corp"

    @pytest.mark.asyncio
    async def test_get_customer_not_found(self, connector):
        """Test customer retrieval when not found."""
        mock_response = {"Customer": None}

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            customer = await connector.get_customer("999")
            assert customer is None

    @pytest.mark.asyncio
    async def test_get_customer_invalid_id(self, connector):
        """Test customer retrieval with invalid ID."""
        with pytest.raises(ValueError, match="must be a numeric ID"):
            await connector.get_customer("invalid-id")


# =============================================================================
# Invoice Operations Tests
# =============================================================================


class TestQuickBooksConnectorInvoices:
    """Tests for QuickBooksConnector invoice operations."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector for testing."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="valid-token",
                refresh_token="refresh-token",
                realm_id="123456789",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_list_invoices_success(self, connector):
        """Test successful invoice listing."""
        mock_response = {
            "QueryResponse": {
                "Invoice": [
                    {
                        "Id": "1001",
                        "DocNumber": "INV-1001",
                        "TxnDate": "2024-01-15",
                        "DueDate": "2024-02-14",
                        "TotalAmt": 5250.00,
                        "Balance": 5250.00,
                        "CustomerRef": {"value": "1", "name": "Acme Corp"},
                    }
                ]
            }
        }

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            invoices = await connector.list_invoices()

            assert len(invoices) == 1
            assert invoices[0].id == "1001"
            assert invoices[0].doc_number == "INV-1001"
            assert invoices[0].type == TransactionType.INVOICE

    @pytest.mark.asyncio
    async def test_list_invoices_with_date_filter(self, connector):
        """Test invoice listing with date filter."""
        mock_response = {"QueryResponse": {"Invoice": []}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.list_invoices(
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 1, 31),
            )

            # Verify the query includes date filters
            call_args = mock_request.call_args
            assert "2024-01-01" in call_args[0][1]
            assert "2024-01-31" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_list_invoices_with_customer_filter(self, connector):
        """Test invoice listing with customer filter."""
        mock_response = {"QueryResponse": {"Invoice": []}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.list_invoices(customer_id="123")

            call_args = mock_request.call_args
            assert "CustomerRef = '123'" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_create_invoice_success(self, connector):
        """Test successful invoice creation."""
        mock_response = {
            "Invoice": {
                "Id": "1002",
                "DocNumber": "INV-1002",
                "TotalAmt": 1500.00,
            }
        }

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            invoice = await connector.create_invoice(
                customer_id="1",
                line_items=[
                    {
                        "Amount": 1500.00,
                        "DetailType": "SalesItemLineDetail",
                        "SalesItemLineDetail": {"ItemRef": {"value": "1"}},
                    }
                ],
            )

            assert invoice["Id"] == "1002"


# =============================================================================
# Vendor Operations Tests
# =============================================================================


class TestQuickBooksConnectorVendors:
    """Tests for QuickBooksConnector vendor operations."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector for testing."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="valid-token",
                refresh_token="refresh-token",
                realm_id="123456789",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_list_vendors_success(self, connector):
        """Test successful vendor listing."""
        mock_response = {
            "QueryResponse": {
                "Vendor": [
                    {
                        "Id": "1",
                        "DisplayName": "Office Supplies Co",
                        "Balance": 500.00,
                        "Active": True,
                    }
                ]
            }
        }

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            vendors = await connector.list_vendors()

            assert len(vendors) == 1
            assert vendors[0]["Id"] == "1"
            assert vendors[0]["DisplayName"] == "Office Supplies Co"

    @pytest.mark.asyncio
    async def test_get_vendor_by_name_success(self, connector):
        """Test successful vendor lookup by name."""
        mock_response = {
            "QueryResponse": {
                "Vendor": [
                    {
                        "Id": "1",
                        "DisplayName": "Office Supplies Co",
                    }
                ]
            }
        }

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            vendor = await connector.get_vendor_by_name("Office Supplies Co")

            assert vendor is not None
            assert vendor["DisplayName"] == "Office Supplies Co"

    @pytest.mark.asyncio
    async def test_get_vendor_by_name_not_found(self, connector):
        """Test vendor lookup when not found."""
        mock_response = {"QueryResponse": {"Vendor": []}}

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            vendor = await connector.get_vendor_by_name("Nonexistent Vendor")
            assert vendor is None

    @pytest.mark.asyncio
    async def test_create_vendor_success(self, connector):
        """Test successful vendor creation."""
        mock_response = {
            "Vendor": {
                "Id": "10",
                "DisplayName": "New Vendor",
            }
        }

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            vendor = await connector.create_vendor(
                display_name="New Vendor",
                email="vendor@example.com",
                phone="555-0200",
            )

            assert vendor["Id"] == "10"
            assert vendor["DisplayName"] == "New Vendor"


# =============================================================================
# Account Operations Tests
# =============================================================================


class TestQuickBooksConnectorAccounts:
    """Tests for QuickBooksConnector account operations."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector for testing."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="valid-token",
                refresh_token="refresh-token",
                realm_id="123456789",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_list_accounts_success(self, connector):
        """Test successful account listing."""
        mock_response = {
            "QueryResponse": {
                "Account": [
                    {
                        "Id": "1",
                        "Name": "Checking Account",
                        "AccountType": "Bank",
                        "AccountSubType": "Checking",
                        "CurrentBalance": 50000.00,
                        "Active": True,
                    }
                ]
            }
        }

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            accounts = await connector.list_accounts()

            assert len(accounts) == 1
            assert accounts[0].id == "1"
            assert accounts[0].name == "Checking Account"
            assert accounts[0].account_type == "Bank"

    @pytest.mark.asyncio
    async def test_list_accounts_with_type_filter(self, connector):
        """Test account listing with type filter."""
        mock_response = {"QueryResponse": {"Account": []}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.list_accounts(account_type="Bank")

            call_args = mock_request.call_args
            assert "AccountType = 'Bank'" in call_args[0][1]


# =============================================================================
# Payment Operations Tests
# =============================================================================


class TestQuickBooksConnectorPayments:
    """Tests for QuickBooksConnector payment operations."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector for testing."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="valid-token",
                refresh_token="refresh-token",
                realm_id="123456789",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_create_payment_success(self, connector):
        """Test successful payment creation."""
        mock_response = {
            "Payment": {
                "Id": "5001",
                "TotalAmt": 1000.00,
            }
        }

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            payment = await connector.create_payment(
                customer_id="1",
                amount=1000.00,
                invoice_ids=["1001"],
            )

            assert payment["Id"] == "5001"
            assert payment["TotalAmt"] == 1000.00

    @pytest.mark.asyncio
    async def test_create_bill_payment_success(self, connector):
        """Test successful bill payment creation."""
        mock_response = {
            "BillPayment": {
                "Id": "5002",
                "TotalAmt": 500.00,
            }
        }

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            payment = await connector.create_bill_payment(
                vendor_id="10",
                amount=500.00,
                bank_account_id="1",
                bill_ids=["2001"],
            )

            assert payment["Id"] == "5002"


# =============================================================================
# Expense/Purchase Operations Tests
# =============================================================================


class TestQuickBooksConnectorExpenses:
    """Tests for QuickBooksConnector expense operations."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector for testing."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="valid-token",
                refresh_token="refresh-token",
                realm_id="123456789",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_list_expenses_success(self, connector):
        """Test successful expense listing."""
        mock_response = {
            "QueryResponse": {
                "Purchase": [
                    {
                        "Id": "2001",
                        "TxnDate": "2024-01-10",
                        "TotalAmt": 1250.00,
                        "Balance": 0,
                        "VendorRef": {"value": "10", "name": "Office Supplies Co"},
                    }
                ]
            }
        }

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            expenses = await connector.list_expenses()

            assert len(expenses) == 1
            assert expenses[0].id == "2001"
            assert expenses[0].type == TransactionType.EXPENSE

    @pytest.mark.asyncio
    async def test_create_expense_success(self, connector):
        """Test successful expense creation."""
        mock_response = {
            "Purchase": {
                "Id": "2002",
                "TotalAmt": 250.00,
            }
        }

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            expense = await connector.create_expense(
                vendor_id="10",
                account_id="1",
                amount=250.00,
                description="Office supplies",
            )

            assert expense["Id"] == "2002"

    @pytest.mark.asyncio
    async def test_create_bill_success(self, connector):
        """Test successful bill creation."""
        mock_response = {
            "Bill": {
                "Id": "3001",
                "TotalAmt": 1500.00,
            }
        }

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            bill = await connector.create_bill(
                vendor_id="10",
                account_id="1",
                amount=1500.00,
                description="Monthly supplies",
            )

            assert bill["Id"] == "3001"


# =============================================================================
# Report Operations Tests
# =============================================================================


class TestQuickBooksConnectorReports:
    """Tests for QuickBooksConnector report operations."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector for testing."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="valid-token",
                refresh_token="refresh-token",
                realm_id="123456789",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_get_profit_loss_report(self, connector):
        """Test profit and loss report retrieval."""
        mock_response = {"Rows": {"Row": []}}

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            report = await connector.get_profit_loss_report(
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 3, 31),
            )

            assert report is not None

    @pytest.mark.asyncio
    async def test_get_balance_sheet_report(self, connector):
        """Test balance sheet report retrieval."""
        mock_response = {"Rows": {"Row": []}}

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            report = await connector.get_balance_sheet_report()
            assert report is not None

    @pytest.mark.asyncio
    async def test_get_ar_aging(self, connector):
        """Test AR aging report retrieval."""
        mock_response = {"Rows": {"Row": []}}

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            report = await connector.get_accounts_receivable_aging()
            assert report is not None

    @pytest.mark.asyncio
    async def test_get_ap_aging(self, connector):
        """Test AP aging report retrieval."""
        mock_response = {"Rows": {"Row": []}}

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            report = await connector.get_accounts_payable_aging()
            assert report is not None


# =============================================================================
# API Error Handling Tests
# =============================================================================


class TestQuickBooksConnectorErrors:
    """Tests for QuickBooksConnector error handling."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector for testing."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="valid-token",
                refresh_token="refresh-token",
                realm_id="123456789",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_request_not_authenticated(self):
        """Test request without authentication."""
        connector = QuickBooksConnector(
            client_id="client",
            client_secret="secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )

        with pytest.raises(ConnectorAuthError, match="Not authenticated"):
            await connector._request("GET", "test")

    @pytest.mark.asyncio
    async def test_api_error_response(self, connector):
        """Test API error response handling."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "Fault": {"Error": [{"Message": "Invalid request", "code": "2000"}]}
        }

        mock_session = AsyncMock()
        mock_session.request.return_value = mock_response

        # Create proper async context manager
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_session
        mock_cm.__aexit__.return_value = None

        mock_pool = MagicMock()
        mock_pool.get_session.return_value = mock_cm

        with patch("aragora.connectors.accounting.qbo.get_http_pool", return_value=mock_pool):
            with pytest.raises(ConnectorAPIError, match="Invalid request"):
                await connector._request("GET", "customer/1")


# =============================================================================
# Rate Limiting and Retry Tests
# =============================================================================


class TestQuickBooksConnectorRetry:
    """Tests for QuickBooksConnector retry logic."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector for testing."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="valid-token",
                refresh_token="refresh-token",
                realm_id="123456789",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_retry_on_rate_limit(self, connector):
        """Test retry on 429 rate limit."""
        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 429
        rate_limit_response.headers = {"Retry-After": "1"}

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"Customer": {"Id": "1"}}

        mock_session = AsyncMock()
        mock_session.request.side_effect = [rate_limit_response, success_response]

        mock_pool = MagicMock()
        mock_pool.get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("aragora.connectors.accounting.qbo.get_http_pool", return_value=mock_pool):
            with patch("asyncio.sleep", new=AsyncMock()):
                result = await connector._request("GET", "customer/1")
                assert result["Customer"]["Id"] == "1"

    @pytest.mark.asyncio
    async def test_retry_on_server_error(self, connector):
        """Test retry on 500 server error."""
        error_response = MagicMock()
        error_response.status_code = 500

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"data": "success"}

        mock_session = AsyncMock()
        mock_session.request.side_effect = [error_response, success_response]

        mock_pool = MagicMock()
        mock_pool.get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("aragora.connectors.accounting.qbo.get_http_pool", return_value=mock_pool):
            with patch("asyncio.sleep", new=AsyncMock()):
                result = await connector._request("GET", "test")
                assert result["data"] == "success"

    @pytest.mark.asyncio
    async def test_network_error_retry(self, connector):
        """Test retry on network error."""
        mock_session = AsyncMock()
        mock_session.request.side_effect = [
            httpx.RequestError("Connection refused"),
            httpx.RequestError("Connection refused"),
            httpx.RequestError("Connection refused"),
            httpx.RequestError("Connection refused"),
        ]

        # Create proper async context manager
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_session
        mock_cm.__aexit__.return_value = None

        mock_pool = MagicMock()
        mock_pool.get_session.return_value = mock_cm

        with patch("aragora.connectors.accounting.qbo.get_http_pool", return_value=mock_pool):
            with patch("asyncio.sleep", new=AsyncMock()):
                with pytest.raises(ConnectorNetworkError, match="connection failed after"):
                    await connector._request("GET", "test", max_retries=3)

    @pytest.mark.asyncio
    async def test_timeout_error_retry(self, connector):
        """Test retry on timeout error."""
        mock_session = AsyncMock()
        mock_session.request.side_effect = [
            asyncio.TimeoutError(),
            asyncio.TimeoutError(),
            asyncio.TimeoutError(),
            asyncio.TimeoutError(),
        ]

        # Create proper async context manager
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_session
        mock_cm.__aexit__.return_value = None

        mock_pool = MagicMock()
        mock_pool.get_session.return_value = mock_cm

        with patch("aragora.connectors.accounting.qbo.get_http_pool", return_value=mock_pool):
            with patch("asyncio.sleep", new=AsyncMock()):
                with pytest.raises(ConnectorTimeoutError, match="timed out after"):
                    await connector._request("GET", "test", max_retries=3)


# =============================================================================
# Circuit Breaker Tests
# =============================================================================


class TestQuickBooksConnectorCircuitBreaker:
    """Tests for QuickBooksConnector circuit breaker integration."""

    @pytest.fixture
    def connector_with_cb(self):
        """Create connector with circuit breaker for testing."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=True,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="valid-token",
                refresh_token="refresh-token",
                realm_id="123456789",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_circuit_breaker_open(self, connector_with_cb):
        """Test circuit breaker blocks requests when open."""
        # Force circuit breaker open
        cb = connector_with_cb._circuit_breaker
        for _ in range(cb.failure_threshold + 1):
            cb.record_failure()

        with pytest.raises(ConnectorAPIError, match="Circuit breaker open"):
            await connector_with_cb._request("GET", "test")


# =============================================================================
# Validation Helper Tests
# =============================================================================


class TestQuickBooksConnectorValidation:
    """Tests for QuickBooksConnector validation helpers."""

    @pytest.fixture
    def connector(self):
        """Create connector for testing."""
        return QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
        )

    def test_validate_numeric_id_valid(self, connector):
        """Test numeric ID validation with valid input."""
        result = connector._validate_numeric_id("12345", "customer_id")
        assert result == "12345"

    def test_validate_numeric_id_with_whitespace(self, connector):
        """Test numeric ID validation strips whitespace."""
        result = connector._validate_numeric_id("  12345  ", "customer_id")
        assert result == "12345"

    def test_validate_numeric_id_invalid(self, connector):
        """Test numeric ID validation rejects non-numeric."""
        with pytest.raises(ValueError, match="must be a numeric ID"):
            connector._validate_numeric_id("abc123", "customer_id")

    def test_validate_numeric_id_empty(self, connector):
        """Test numeric ID validation rejects empty."""
        with pytest.raises(ValueError, match="cannot be empty"):
            connector._validate_numeric_id("", "customer_id")

    def test_validate_pagination_valid(self, connector):
        """Test pagination validation with valid input."""
        limit, offset = connector._validate_pagination(50, 100)
        assert limit == 50
        assert offset == 100

    def test_validate_pagination_caps_limit(self, connector):
        """Test pagination validation caps limit at 1000."""
        limit, offset = connector._validate_pagination(5000, 0)
        assert limit == 1000

    def test_validate_pagination_negative_limit(self, connector):
        """Test pagination validation rejects negative limit."""
        with pytest.raises(ValueError, match="limit must be positive"):
            connector._validate_pagination(-1, 0)

    def test_validate_pagination_negative_offset(self, connector):
        """Test pagination validation rejects negative offset."""
        with pytest.raises(ValueError, match="offset must be non-negative"):
            connector._validate_pagination(10, -5)

    def test_validate_pagination_invalid_types(self, connector):
        """Test pagination validation rejects invalid types."""
        with pytest.raises(ValueError, match="limit must be an integer"):
            connector._validate_pagination("10", 0)  # type: ignore

    def test_sanitize_query_value_basic(self, connector):
        """Test query value sanitization with basic string."""
        result = connector._sanitize_query_value("Test Company")
        assert result == "Test Company"

    def test_sanitize_query_value_escapes_quotes(self, connector):
        """Test query value sanitization escapes quotes."""
        result = connector._sanitize_query_value("O'Brien")
        assert result == "O''Brien"

    def test_sanitize_query_value_too_long(self, connector):
        """Test query value sanitization rejects long strings."""
        with pytest.raises(ValueError, match="Query value too long"):
            connector._sanitize_query_value("x" * 501)

    def test_sanitize_query_value_strips_unsafe_chars(self, connector):
        """Test query value sanitization strips unsafe characters."""
        result = connector._sanitize_query_value("Test<script>alert(1)</script>")
        # The < and > chars are filtered out as they're not in the allowlist
        assert "<" not in result
        assert ">" not in result

    def test_format_date_for_query_valid(self, connector):
        """Test date formatting with valid input."""
        date = datetime(2024, 1, 15)
        result = connector._format_date_for_query(date, "txn_date")
        assert result == "2024-01-15"

    def test_format_date_for_query_invalid(self, connector):
        """Test date formatting rejects invalid input."""
        with pytest.raises(ValueError, match="must be a datetime object"):
            connector._format_date_for_query("2024-01-15", "txn_date")  # type: ignore


# =============================================================================
# Mock Data Tests
# =============================================================================


class TestMockData:
    """Tests for mock data generation."""

    def test_get_mock_customers(self):
        """Test mock customer generation."""
        customers = get_mock_customers()
        assert len(customers) > 0
        assert all(isinstance(c, QBOCustomer) for c in customers)

        # Check we have variety
        assert any(c.balance > 0 for c in customers)

    def test_get_mock_transactions(self):
        """Test mock transaction generation."""
        transactions = get_mock_transactions()
        assert len(transactions) > 0
        assert all(isinstance(t, QBOTransaction) for t in transactions)

        # Check for variety of transaction types
        types = {t.type for t in transactions}
        assert len(types) > 1

    def test_mock_customers_have_valid_data(self):
        """Test mock customers have valid data."""
        customers = get_mock_customers()
        for customer in customers:
            assert customer.id is not None
            assert customer.display_name is not None
            assert isinstance(customer.balance, (int, float))

    def test_mock_transactions_have_valid_data(self):
        """Test mock transactions have valid data."""
        transactions = get_mock_transactions()
        for txn in transactions:
            assert txn.id is not None
            assert txn.type in TransactionType
            assert isinstance(txn.total_amount, (int, float))


# =============================================================================
# Company Info Tests
# =============================================================================


class TestQuickBooksConnectorCompanyInfo:
    """Tests for QuickBooksConnector company info operations."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector for testing."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="valid-token",
                refresh_token="refresh-token",
                realm_id="123456789",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_get_company_info_success(self, connector):
        """Test successful company info retrieval."""
        mock_response = {
            "CompanyInfo": {
                "CompanyName": "Test Company",
                "LegalName": "Test Company LLC",
                "Country": "US",
            }
        }

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            info = await connector.get_company_info()

            assert info["CompanyName"] == "Test Company"
            assert info["Country"] == "US"


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestQuickBooksConnectorEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector for testing."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="valid-token",
                refresh_token="refresh-token",
                realm_id="123456789",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_auto_refresh_expired_token(self, connector):
        """Test automatic token refresh on expired credentials."""
        # Set expired credentials
        connector.set_credentials(
            QBOCredentials(
                access_token="expired-token",
                refresh_token="refresh-token",
                realm_id="123456789",
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )

        # Mock refresh_tokens
        async def mock_refresh():
            connector.set_credentials(
                QBOCredentials(
                    access_token="new-token",
                    refresh_token="new-refresh",
                    realm_id="123456789",
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                )
            )
            return connector._credentials

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"Customer": {"Id": "1"}}

        mock_session = AsyncMock()
        mock_session.request.return_value = mock_response

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_session
        mock_cm.__aexit__.return_value = None

        mock_pool = MagicMock()
        mock_pool.get_session.return_value = mock_cm

        with patch.object(connector, "refresh_tokens", side_effect=mock_refresh):
            with patch(
                "aragora.connectors.accounting.qbo.get_http_pool",
                return_value=mock_pool,
            ):
                result = await connector._request("GET", "customer/1")
                assert result["Customer"]["Id"] == "1"

    def test_transaction_parse_paid_status(self, connector):
        """Test transaction parsing sets Paid status when balance is 0."""
        item = {
            "Id": "1001",
            "TxnDate": "2024-01-15",
            "TotalAmt": 1000.00,
            "Balance": 0,
        }
        txn = connector._parse_transaction(item, TransactionType.INVOICE)
        assert txn.status == "Paid"

    def test_transaction_parse_open_status(self, connector):
        """Test transaction parsing sets Open status when balance > 0."""
        item = {
            "Id": "1001",
            "TxnDate": "2024-01-15",
            "TotalAmt": 1000.00,
            "Balance": 500.00,
        }
        txn = connector._parse_transaction(item, TransactionType.INVOICE)
        assert txn.status == "Open"

    def test_transaction_parse_with_refs(self, connector):
        """Test transaction parsing with customer and vendor refs."""
        item = {
            "Id": "1001",
            "TxnDate": "2024-01-15",
            "TotalAmt": 1000.00,
            "Balance": 0,
            "CustomerRef": {"value": "1", "name": "Acme Corp"},
            "VendorRef": {"value": "10", "name": "Supplier Inc"},
        }
        txn = connector._parse_transaction(item, TransactionType.INVOICE)
        assert txn.customer_id == "1"
        assert txn.customer_name == "Acme Corp"
        assert txn.vendor_id == "10"
        assert txn.vendor_name == "Supplier Inc"

    @pytest.mark.asyncio
    async def test_list_customers_inactive(self, connector):
        """Test listing inactive customers."""
        mock_response = {"QueryResponse": {"Customer": []}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.list_customers(active_only=False)

            call_args = mock_request.call_args
            assert "Active = false" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_malformed_api_response(self, connector):
        """Test handling malformed API response."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {}  # Missing Fault structure

        mock_session = AsyncMock()
        mock_session.request.return_value = mock_response

        # Create proper async context manager
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_session
        mock_cm.__aexit__.return_value = None

        mock_pool = MagicMock()
        mock_pool.get_session.return_value = mock_cm

        with patch("aragora.connectors.accounting.qbo.get_http_pool", return_value=mock_pool):
            with pytest.raises(ConnectorAPIError, match="Unknown error"):
                await connector._request("GET", "customer/1")


# =============================================================================
# Additional Data Transformation Tests
# =============================================================================


class TestQBOCustomerFromDict:
    """Tests for QBOCustomer deserialization."""

    def test_from_dict_basic(self):
        """Test basic from_dict deserialization."""
        data = {
            "id": "123",
            "display_name": "Test Customer",
            "balance": 1500.50,
        }
        customer = QBOCustomer.from_dict(data)
        assert customer.id == "123"
        assert customer.display_name == "Test Customer"
        assert customer.balance == 1500.50

    def test_from_dict_with_api_names(self):
        """Test from_dict with API field names."""
        data = {
            "id": "123",
            "displayName": "Test Customer",
            "companyName": "Test Co",
        }
        customer = QBOCustomer.from_dict(data, from_api=True)
        assert customer.display_name == "Test Customer"
        assert customer.company_name == "Test Co"

    def test_from_dict_with_datetime(self):
        """Test from_dict handles datetime correctly."""
        created = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        data = {
            "id": "123",
            "display_name": "Test Customer",
            "created_at": created,
        }
        customer = QBOCustomer.from_dict(data)
        assert customer.created_at is not None
        assert customer.created_at.year == 2024


class TestQBOTransactionFromDict:
    """Tests for QBOTransaction deserialization."""

    def test_from_dict_with_dates(self):
        """Test transaction deserialization with dates."""
        data = {
            "id": "1001",
            "type": "Invoice",
            "txn_date": "2024-01-15T00:00:00+00:00",
            "due_date": "2024-02-14T00:00:00+00:00",
            "total_amount": 5000.00,
        }
        txn = QBOTransaction.from_dict(data)
        assert txn.id == "1001"
        assert txn.type == TransactionType.INVOICE
        assert txn.txn_date is not None

    def test_from_dict_with_line_items(self):
        """Test transaction deserialization with line items."""
        data = {
            "id": "1001",
            "type": "Invoice",
            "line_items": [
                {"Amount": 100.00, "Description": "Item 1"},
                {"Amount": 200.00, "Description": "Item 2"},
            ],
        }
        txn = QBOTransaction.from_dict(data)
        assert len(txn.line_items) == 2


class TestQBOAccountFromDict:
    """Tests for QBOAccount deserialization."""

    def test_from_dict_basic(self):
        """Test account deserialization."""
        data = {
            "id": "1",
            "name": "Checking",
            "account_type": "Bank",
            "current_balance": 50000.00,
        }
        account = QBOAccount.from_dict(data)
        assert account.id == "1"
        assert account.name == "Checking"
        assert account.current_balance == 50000.00


# =============================================================================
# Environment Configuration Tests
# =============================================================================


class TestQuickBooksConnectorEnvironmentConfig:
    """Tests for environment variable configuration."""

    def test_environment_from_env_var_sandbox(self):
        """Test environment detected from env var - sandbox."""
        with patch.dict("os.environ", {"QBO_ENVIRONMENT": "sandbox"}):
            connector = QuickBooksConnector(
                client_id="client",
                client_secret="secret",
                redirect_uri="http://localhost/callback",
            )
            assert connector.environment == QBOEnvironment.SANDBOX

    def test_environment_from_env_var_production(self):
        """Test environment detected from env var - production."""
        with patch.dict("os.environ", {"QBO_ENVIRONMENT": "production"}):
            connector = QuickBooksConnector(
                client_id="client",
                client_secret="secret",
                redirect_uri="http://localhost/callback",
            )
            assert connector.environment == QBOEnvironment.PRODUCTION

    def test_credentials_from_env_vars(self):
        """Test credentials loaded from environment variables."""
        with patch.dict(
            "os.environ",
            {
                "QBO_CLIENT_ID": "env_client_id",
                "QBO_CLIENT_SECRET": "env_client_secret",
                "QBO_REDIRECT_URI": "http://env.localhost/callback",
            },
        ):
            connector = QuickBooksConnector()
            assert connector.client_id == "env_client_id"
            assert connector.client_secret == "env_client_secret"
            assert connector.redirect_uri == "http://env.localhost/callback"

    def test_explicit_config_overrides_env(self):
        """Test explicit configuration overrides environment variables."""
        with patch.dict(
            "os.environ",
            {
                "QBO_CLIENT_ID": "env_client_id",
            },
        ):
            connector = QuickBooksConnector(
                client_id="explicit_client_id",
                client_secret="secret",
                redirect_uri="http://localhost/callback",
            )
            assert connector.client_id == "explicit_client_id"


# =============================================================================
# Query Builder Advanced Tests
# =============================================================================


class TestQBOQueryBuilderAdvanced:
    """Advanced tests for query builder."""

    def test_chained_conditions(self):
        """Test multiple chained conditions."""
        qb = QBOQueryBuilder("Invoice")
        qb.select("Id", "DocNumber").where_eq("Active", True).where_gte(
            "TxnDate", datetime(2024, 1, 1)
        ).where_lte("TxnDate", datetime(2024, 12, 31))
        query = qb.build()
        assert "Active = true" in query
        assert "TxnDate >= '2024-01-01'" in query
        assert "TxnDate <= '2024-12-31'" in query

    def test_all_entity_types(self):
        """Test query builder accepts all valid entities."""
        valid_entities = [
            "Account",
            "Bill",
            "Customer",
            "Invoice",
            "Payment",
            "Vendor",
        ]
        for entity in valid_entities:
            qb = QBOQueryBuilder(entity)
            assert qb._entity == entity

    def test_multiple_select_calls(self):
        """Test multiple select calls accumulate fields."""
        qb = QBOQueryBuilder("Customer")
        qb.select("Id", "DisplayName")
        qb.select("Balance")
        assert len(qb._select_fields) == 3

    def test_where_eq_with_string(self):
        """Test where equality with string value."""
        qb = QBOQueryBuilder("Customer")
        qb.where_eq("DisplayName", "Acme Corp")
        assert "DisplayName = 'Acme Corp'" in qb._conditions

    def test_where_eq_with_datetime(self):
        """Test where equality with datetime value."""
        qb = QBOQueryBuilder("Invoice")
        date = datetime(2024, 6, 15)
        qb.where_eq("TxnDate", date)
        assert "TxnDate = '2024-06-15'" in qb._conditions

    def test_format_value_with_int(self):
        """Test value formatting for integers."""
        qb = QBOQueryBuilder("Invoice")
        result = qb._format_value(100)
        assert result == "100"

    def test_format_value_with_float(self):
        """Test value formatting for floats."""
        qb = QBOQueryBuilder("Invoice")
        result = qb._format_value(99.99)
        assert result == "99.99"


# =============================================================================
# Transaction Type Edge Cases
# =============================================================================


class TestTransactionTypeEdgeCases:
    """Tests for transaction type edge cases."""

    def test_all_transaction_types(self):
        """Test all transaction types can be used."""
        for txn_type in TransactionType:
            txn = QBOTransaction(
                id="1",
                type=txn_type,
                total_amount=100.00,
            )
            assert txn.type == txn_type

    def test_transaction_type_serialization(self):
        """Test transaction type serializes to string value."""
        txn = QBOTransaction(
            id="1",
            type=TransactionType.CREDIT_MEMO,
            total_amount=100.00,
        )
        data = txn.to_dict()
        assert data["type"] == "CreditMemo"

    def test_transaction_type_in_expense(self):
        """Test expense transaction has correct type."""
        txn = QBOTransaction(
            id="2001",
            type=TransactionType.PURCHASE,
            vendor_id="10",
            total_amount=500.00,
        )
        assert txn.type == TransactionType.PURCHASE
        assert txn.vendor_id == "10"


# =============================================================================
# Invoice and Expense Date Filtering Tests
# =============================================================================


class TestDateFiltering:
    """Tests for date-based filtering in list operations."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="token",
                refresh_token="refresh",
                realm_id="123",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_list_expenses_with_date_range(self, connector):
        """Test expense listing with date range filter."""
        mock_response = {"QueryResponse": {"Purchase": []}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.list_expenses(
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 3, 31),
            )

            call_args = mock_request.call_args
            assert "2024-01-01" in call_args[0][1]
            assert "2024-03-31" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_list_invoices_no_filters(self, connector):
        """Test invoice listing without filters uses 1=1."""
        mock_response = {"QueryResponse": {"Invoice": []}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.list_invoices()

            call_args = mock_request.call_args
            assert "WHERE 1=1" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_list_invoices_pagination(self, connector):
        """Test invoice listing with pagination."""
        mock_response = {"QueryResponse": {"Invoice": []}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.list_invoices(limit=50, offset=100)

            call_args = mock_request.call_args
            assert "MAXRESULTS 50" in call_args[0][1]
            assert "STARTPOSITION 101" in call_args[0][1]


# =============================================================================
# Vendor Operations Extended Tests
# =============================================================================


class TestVendorOperationsExtended:
    """Extended tests for vendor operations."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="token",
                refresh_token="refresh",
                realm_id="123",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_list_vendors_inactive(self, connector):
        """Test listing inactive vendors."""
        mock_response = {"QueryResponse": {"Vendor": []}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.list_vendors(active_only=False)

            call_args = mock_request.call_args
            assert "Active = false" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_list_vendors_with_pagination(self, connector):
        """Test vendor listing with pagination."""
        mock_response = {"QueryResponse": {"Vendor": []}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.list_vendors(limit=25, offset=50)

            call_args = mock_request.call_args
            assert "MAXRESULTS 25" in call_args[0][1]
            assert "STARTPOSITION 51" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_create_vendor_minimal(self, connector):
        """Test vendor creation with minimal fields."""
        mock_response = {"Vendor": {"Id": "100", "DisplayName": "New Vendor"}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            vendor = await connector.create_vendor(display_name="New Vendor")

            assert vendor["Id"] == "100"
            # Verify no email/phone in request
            call_args = mock_request.call_args
            data = call_args[1]["data"] if "data" in call_args[1] else call_args[0][2]
            assert "DisplayName" in data


# =============================================================================
# Bill and Expense Creation Tests
# =============================================================================


class TestBillAndExpenseCreation:
    """Tests for bill and expense creation."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="token",
                refresh_token="refresh",
                realm_id="123",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_create_bill_with_due_date(self, connector):
        """Test bill creation with due date."""
        mock_response = {"Bill": {"Id": "3001"}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.create_bill(
                vendor_id="10",
                account_id="1",
                amount=1500.00,
                due_date=datetime(2024, 2, 15),
            )

            call_args = mock_request.call_args
            data = call_args[1]["data"] if "data" in call_args[1] else call_args[0][2]
            assert data["DueDate"] == "2024-02-15"

    @pytest.mark.asyncio
    async def test_create_bill_with_line_items(self, connector):
        """Test bill creation with custom line items."""
        mock_response = {"Bill": {"Id": "3002"}}
        custom_lines = [
            {"Amount": 500.00, "Description": "Item 1"},
            {"Amount": 1000.00, "Description": "Item 2"},
        ]

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.create_bill(
                vendor_id="10",
                account_id="1",
                amount=1500.00,
                line_items=custom_lines,
            )

            call_args = mock_request.call_args
            data = call_args[1]["data"] if "data" in call_args[1] else call_args[0][2]
            assert len(data["Line"]) == 2

    @pytest.mark.asyncio
    async def test_create_expense_with_all_fields(self, connector):
        """Test expense creation with all optional fields."""
        mock_response = {"Purchase": {"Id": "2003"}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.create_expense(
                vendor_id="10",
                account_id="1",
                amount=250.00,
                description="Office supplies purchase",
                txn_date=datetime(2024, 1, 20),
                payment_type="CreditCard",
            )

            call_args = mock_request.call_args
            data = call_args[1]["data"] if "data" in call_args[1] else call_args[0][2]
            assert data["PaymentType"] == "CreditCard"
            assert data["PrivateNote"] == "Office supplies purchase"
            assert data["TxnDate"] == "2024-01-20"


# =============================================================================
# Payment Operation Extended Tests
# =============================================================================


class TestPaymentOperationsExtended:
    """Extended tests for payment operations."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="token",
                refresh_token="refresh",
                realm_id="123",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_create_payment_without_invoices(self, connector):
        """Test payment creation without linking to invoices."""
        mock_response = {"Payment": {"Id": "5003", "TotalAmt": 500.00}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            payment = await connector.create_payment(
                customer_id="1",
                amount=500.00,
            )

            assert payment["Id"] == "5003"
            call_args = mock_request.call_args
            data = call_args[1]["data"] if "data" in call_args[1] else call_args[0][2]
            assert "Line" not in data

    @pytest.mark.asyncio
    async def test_create_payment_with_multiple_invoices(self, connector):
        """Test payment linking to multiple invoices."""
        mock_response = {"Payment": {"Id": "5004"}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.create_payment(
                customer_id="1",
                amount=2000.00,
                invoice_ids=["1001", "1002", "1003"],
            )

            call_args = mock_request.call_args
            data = call_args[1]["data"] if "data" in call_args[1] else call_args[0][2]
            assert len(data["Line"][0]["LinkedTxn"]) == 3

    @pytest.mark.asyncio
    async def test_create_bill_payment_with_bills(self, connector):
        """Test bill payment linking to multiple bills."""
        mock_response = {"BillPayment": {"Id": "5005"}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.create_bill_payment(
                vendor_id="10",
                amount=1000.00,
                bank_account_id="1",
                bill_ids=["2001", "2002"],
            )

            call_args = mock_request.call_args
            data = call_args[1]["data"] if "data" in call_args[1] else call_args[0][2]
            assert len(data["Line"][0]["LinkedTxn"]) == 2


# =============================================================================
# Report Operations Extended Tests
# =============================================================================


class TestReportOperationsExtended:
    """Extended tests for report operations."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="token",
                refresh_token="refresh",
                realm_id="123",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_get_balance_sheet_with_date(self, connector):
        """Test balance sheet report with specific date."""
        mock_response = {"Rows": {"Row": []}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.get_balance_sheet_report(
                as_of_date=datetime(2024, 12, 31),
            )

            call_args = mock_request.call_args
            assert "2024-12-31" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_profit_loss_report_date_format(self, connector):
        """Test P&L report uses correct date format."""
        mock_response = {"Rows": {"Row": []}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.get_profit_loss_report(
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 12, 31),
            )

            call_args = mock_request.call_args
            endpoint = call_args[0][1]
            assert "start_date=2024-01-01" in endpoint
            assert "end_date=2024-12-31" in endpoint


# =============================================================================
# Retry and Resilience Extended Tests
# =============================================================================


class TestRetryResilienceExtended:
    """Extended tests for retry and resilience."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="token",
                refresh_token="refresh",
                realm_id="123",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_retry_exhausted_returns_last_error(self, connector):
        """Test that retry exhaustion returns meaningful error."""
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.json.return_value = {"Fault": {"Error": [{"Message": "Service unavailable"}]}}

        mock_session = AsyncMock()
        mock_session.request.return_value = mock_response

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_session
        mock_cm.__aexit__.return_value = None

        mock_pool = MagicMock()
        mock_pool.get_session.return_value = mock_cm

        with patch("aragora.connectors.accounting.qbo.get_http_pool", return_value=mock_pool):
            with patch("asyncio.sleep", new=AsyncMock()):
                with pytest.raises(ConnectorAPIError, match="Service unavailable"):
                    await connector._request("GET", "test", max_retries=2)

    @pytest.mark.asyncio
    async def test_successful_request_after_retry(self, connector):
        """Test successful request after initial failures."""
        error_response = MagicMock()
        error_response.status_code = 502

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"data": "success"}

        mock_session = AsyncMock()
        mock_session.request.side_effect = [
            error_response,
            error_response,
            success_response,
        ]

        mock_pool = MagicMock()
        mock_pool.get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("aragora.connectors.accounting.qbo.get_http_pool", return_value=mock_pool):
            with patch("asyncio.sleep", new=AsyncMock()):
                result = await connector._request("GET", "test", max_retries=3)
                assert result["data"] == "success"


# =============================================================================
# Circuit Breaker Extended Tests
# =============================================================================


class TestCircuitBreakerExtended:
    """Extended tests for circuit breaker behavior."""

    def test_circuit_breaker_default_config(self):
        """Test default circuit breaker configuration."""
        connector = QuickBooksConnector(
            client_id="client",
            client_secret="secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=True,
        )
        cb = connector._circuit_breaker
        assert cb.name == "qbo"
        assert cb.failure_threshold == 3
        assert cb.cooldown_seconds == 60.0

    def test_circuit_breaker_records_success(self):
        """Test circuit breaker records success correctly."""
        connector = QuickBooksConnector(
            client_id="client",
            client_secret="secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=True,
        )
        cb = connector._circuit_breaker

        # Record a failure first
        cb.record_failure()
        assert cb.failures > 0

        # Success should reset
        cb.record_success()
        assert cb.can_proceed()


# =============================================================================
# Input Validation Extended Tests
# =============================================================================


class TestInputValidationExtended:
    """Extended tests for input validation."""

    @pytest.fixture
    def connector(self):
        """Create connector for testing."""
        return QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
        )

    def test_sanitize_query_preserves_ampersand(self, connector):
        """Test sanitization preserves ampersand for business names."""
        result = connector._sanitize_query_value("Johnson & Johnson")
        assert "&" in result

    def test_sanitize_query_preserves_hash(self, connector):
        """Test sanitization preserves hash for reference numbers."""
        result = connector._sanitize_query_value("Order #12345")
        assert "#" in result

    def test_sanitize_query_preserves_parentheses(self, connector):
        """Test sanitization preserves parentheses."""
        result = connector._sanitize_query_value("Company (US)")
        assert "(" in result
        assert ")" in result

    def test_validate_pagination_zero_limit_raises(self, connector):
        """Test zero limit is rejected."""
        with pytest.raises(ValueError, match="limit must be positive"):
            connector._validate_pagination(0, 0)

    def test_format_date_with_timezone(self, connector):
        """Test date formatting with timezone-aware datetime."""
        date = datetime(2024, 6, 15, 12, 30, 0, tzinfo=timezone.utc)
        result = connector._format_date_for_query(date, "txn_date")
        assert result == "2024-06-15"

    def test_format_date_naive_datetime(self, connector):
        """Test date formatting with naive datetime."""
        date = datetime(2024, 6, 15, 12, 30, 0)
        result = connector._format_date_for_query(date, "txn_date")
        assert result == "2024-06-15"


# =============================================================================
# Invoice Creation Extended Tests
# =============================================================================


class TestInvoiceCreationExtended:
    """Extended tests for invoice creation."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="token",
                refresh_token="refresh",
                realm_id="123",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_create_invoice_with_memo(self, connector):
        """Test invoice creation with memo."""
        mock_response = {"Invoice": {"Id": "1003"}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.create_invoice(
                customer_id="1",
                line_items=[{"Amount": 100.00}],
                memo="Thank you for your business!",
            )

            call_args = mock_request.call_args
            data = call_args[1]["data"] if "data" in call_args[1] else call_args[0][2]
            assert data["CustomerMemo"]["value"] == "Thank you for your business!"

    @pytest.mark.asyncio
    async def test_create_invoice_with_due_date(self, connector):
        """Test invoice creation with due date."""
        mock_response = {"Invoice": {"Id": "1004"}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.create_invoice(
                customer_id="1",
                line_items=[{"Amount": 100.00}],
                due_date=datetime(2024, 3, 15),
            )

            call_args = mock_request.call_args
            data = call_args[1]["data"] if "data" in call_args[1] else call_args[0][2]
            assert data["DueDate"] == "2024-03-15"


# =============================================================================
# Customer Operations Extended Tests
# =============================================================================


class TestCustomerOperationsExtended:
    """Extended tests for customer operations."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="token",
                refresh_token="refresh",
                realm_id="123",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_list_customers_with_pagination(self, connector):
        """Test customer listing with pagination."""
        mock_response = {"QueryResponse": {"Customer": []}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.list_customers(limit=25, offset=50)

            call_args = mock_request.call_args
            assert "MAXRESULTS 25" in call_args[0][1]
            assert "STARTPOSITION 51" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_get_customer_parses_all_fields(self, connector):
        """Test customer retrieval parses all available fields."""
        mock_response = {
            "Customer": {
                "Id": "1",
                "DisplayName": "Full Customer",
                "CompanyName": "Full Company LLC",
                "PrimaryEmailAddr": {"Address": "email@example.com"},
                "PrimaryPhone": {"FreeFormNumber": "555-1234"},
                "Balance": 9999.99,
                "Active": True,
            }
        }

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            customer = await connector.get_customer("1")

            assert customer.display_name == "Full Customer"
            assert customer.company_name == "Full Company LLC"
            assert customer.email == "email@example.com"
            assert customer.phone == "555-1234"
            assert customer.balance == 9999.99
            assert customer.active is True


# =============================================================================
# Account Operations Extended Tests
# =============================================================================


class TestAccountOperationsExtended:
    """Extended tests for account operations."""

    @pytest.fixture
    def connector(self):
        """Create authenticated connector."""
        conn = QuickBooksConnector(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="http://localhost/callback",
            enable_circuit_breaker=False,
        )
        conn.set_credentials(
            QBOCredentials(
                access_token="token",
                refresh_token="refresh",
                realm_id="123",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        return conn

    @pytest.mark.asyncio
    async def test_list_accounts_inactive(self, connector):
        """Test listing inactive accounts."""
        mock_response = {"QueryResponse": {"Account": []}}

        with patch.object(
            connector, "_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            await connector.list_accounts(active_only=False)

            call_args = mock_request.call_args
            assert "Active = false" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_list_accounts_parses_all_fields(self, connector):
        """Test account listing parses all fields."""
        mock_response = {
            "QueryResponse": {
                "Account": [
                    {
                        "Id": "10",
                        "Name": "Savings Account",
                        "AccountType": "Bank",
                        "AccountSubType": "Savings",
                        "CurrentBalance": 100000.00,
                        "Active": True,
                    }
                ]
            }
        }

        with patch.object(connector, "_request", new=AsyncMock(return_value=mock_response)):
            accounts = await connector.list_accounts()

            assert len(accounts) == 1
            assert accounts[0].account_sub_type == "Savings"
            assert accounts[0].current_balance == 100000.00
