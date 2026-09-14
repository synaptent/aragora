"""
Tests for Accounting Connectors.

Tests OAuth flows, API operations, and error handling for:
- QuickBooks Online (QBO)
- Plaid (banking)
- Gusto (payroll)
- Xero (accounting)
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


# =============================================================================
# QBO Connector Tests
# =============================================================================


class TestQuickBooksConnector:
    """Tests for QuickBooks Online connector."""

    @pytest.fixture
    def qbo_connector(self):
        """Create QBO connector instance."""
        from aragora.connectors.accounting import QuickBooksConnector, QBOEnvironment

        return QuickBooksConnector(
            client_id="test_client_id",
            client_secret="test_client_secret",
            redirect_uri="http://localhost:8080/callback/qbo",
            environment=QBOEnvironment.SANDBOX,
        )

    def test_connector_is_configured(self, qbo_connector):
        """Test connector configuration check."""
        assert qbo_connector.is_configured is True

    def test_connector_not_configured_without_credentials(self):
        """Test connector not configured without env vars."""
        from aragora.connectors.accounting import QuickBooksConnector

        with patch.dict("os.environ", {}, clear=True):
            connector = QuickBooksConnector()
            assert connector.is_configured is False

    def test_get_authorization_url(self, qbo_connector):
        """Test OAuth authorization URL generation."""
        url = qbo_connector.get_authorization_url(state="test_state")

        assert "intuit" in url.lower() or "appcenter" in url.lower()
        assert "client_id=test_client_id" in url
        assert "state=test_state" in url
        assert "response_type=code" in url

    def test_authorization_url_without_state(self, qbo_connector):
        """Test authorization URL generation without state."""
        url = qbo_connector.get_authorization_url()

        assert "client_id=test_client_id" in url

    @pytest.mark.asyncio
    async def test_exchange_code_success(self, qbo_connector):
        """Test successful OAuth code exchange."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "access_token": "test_access_token",
                "refresh_token": "test_refresh_token",
                "token_type": "Bearer",
                "expires_in": 3600,
            }
        )

        with patch("aiohttp.ClientSession") as mock_session:
            mock_ctx = MagicMock()
            mock_ctx.post = MagicMock(
                return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
            )
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            credentials = await qbo_connector.exchange_code(
                authorization_code="test_code",
                realm_id="123456789",
            )

            assert credentials.access_token == "test_access_token"
            assert credentials.refresh_token == "test_refresh_token"
            assert credentials.realm_id == "123456789"
            assert credentials.is_expired is False

    @pytest.mark.asyncio
    async def test_exchange_code_failure(self, qbo_connector):
        """Test OAuth code exchange failure."""
        mock_response = MagicMock()
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="Invalid authorization code")

        # Create async context manager for the response
        mock_post_cm = AsyncMock()
        mock_post_cm.__aenter__.return_value = mock_response
        mock_post_cm.__aexit__.return_value = None

        # Create the session mock
        mock_session_instance = MagicMock()
        mock_session_instance.post.return_value = mock_post_cm

        # Create async context manager for the session
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__.return_value = mock_session_instance
        mock_session_cm.__aexit__.return_value = None

        with patch("aiohttp.ClientSession", return_value=mock_session_cm):
            with pytest.raises(Exception, match="Token exchange failed"):
                await qbo_connector.exchange_code(
                    authorization_code="invalid_code",
                    realm_id="123456789",
                )


class TestQBOCredentials:
    """Tests for QBO OAuth credentials."""

    def test_credentials_not_expired(self):
        """Test credentials expiry check when not expired."""
        from aragora.connectors.accounting import QBOCredentials

        creds = QBOCredentials(
            access_token="test_token",
            refresh_token="test_refresh",
            realm_id="123",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert creds.is_expired is False

    def test_credentials_expired(self):
        """Test credentials expiry check when expired."""
        from aragora.connectors.accounting import QBOCredentials

        creds = QBOCredentials(
            access_token="test_token",
            refresh_token="test_refresh",
            realm_id="123",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        assert creds.is_expired is True

    def test_credentials_no_expiry(self):
        """Test credentials with no expiry date."""
        from aragora.connectors.accounting import QBOCredentials

        creds = QBOCredentials(
            access_token="test_token",
            refresh_token="test_refresh",
            realm_id="123",
            expires_at=None,
        )
        assert creds.is_expired is True


class TestQBOTransactionTypes:
    """Tests for QBO transaction types."""

    def test_transaction_types_exist(self):
        """Test transaction type enum values."""
        from aragora.connectors.accounting import TransactionType

        assert TransactionType.INVOICE.value == "Invoice"
        assert TransactionType.PAYMENT.value == "Payment"
        assert TransactionType.EXPENSE.value == "Expense"
        assert TransactionType.BILL.value == "Bill"


class TestQBOMockData:
    """Tests for QBO mock data functions."""

    def test_get_mock_customers(self):
        """Test mock customer generation."""
        from aragora.connectors.accounting import get_mock_customers

        customers = get_mock_customers()
        assert len(customers) > 0
        assert customers[0].display_name is not None

    def test_get_mock_transactions(self):
        """Test mock transaction generation."""
        from aragora.connectors.accounting import get_mock_transactions

        transactions = get_mock_transactions()
        assert len(transactions) > 0


# =============================================================================
# Plaid Connector Tests
# =============================================================================


class TestPlaidConnector:
    """Tests for Plaid banking connector."""

    @pytest.fixture
    def plaid_connector(self):
        """Create Plaid connector instance."""
        from aragora.connectors.accounting import PlaidConnector, PlaidEnvironment

        return PlaidConnector(
            client_id="test_client_id",
            secret="test_secret",
            environment=PlaidEnvironment.SANDBOX,
        )

    def test_connector_is_configured(self, plaid_connector):
        """Test connector configuration check."""
        assert plaid_connector.is_configured is True

    def test_connector_not_configured_without_credentials(self):
        """Test connector not configured without env vars."""
        from aragora.connectors.accounting import PlaidConnector

        with patch.dict("os.environ", {}, clear=True):
            connector = PlaidConnector()
            assert connector.is_configured is False

    def test_sandbox_base_url(self, plaid_connector):
        """Test sandbox environment uses correct URL."""
        assert "sandbox" in plaid_connector.base_url


class TestPlaidMockData:
    """Tests for Plaid mock data functions."""

    def test_get_mock_accounts(self):
        """Test mock account generation."""
        from aragora.connectors.accounting import get_mock_accounts

        accounts = get_mock_accounts()
        assert len(accounts) > 0

    def test_get_mock_bank_transactions(self):
        """Test mock bank transaction generation."""
        from aragora.connectors.accounting import get_mock_bank_transactions

        transactions = get_mock_bank_transactions()
        assert len(transactions) > 0


class TestPlaidCredentials:
    """Tests for Plaid credentials."""

    def test_credentials_structure(self):
        """Test credentials data class."""
        from aragora.connectors.accounting import PlaidCredentials

        creds = PlaidCredentials(
            access_token="test_token",
            item_id="test_item",
            institution_id="ins_123",
            institution_name="Test Bank",
            user_id="user_456",
            tenant_id="tenant_789",
        )
        assert creds.access_token == "test_token"
        assert creds.item_id == "test_item"
        assert creds.institution_id == "ins_123"
        assert creds.institution_name == "Test Bank"
        assert creds.user_id == "user_456"
        assert creds.tenant_id == "tenant_789"


# =============================================================================
# Gusto Connector Tests
# =============================================================================


class TestGustoConnector:
    """Tests for Gusto payroll connector."""

    @pytest.fixture
    def gusto_connector(self):
        """Create Gusto connector instance."""
        from aragora.connectors.accounting import GustoConnector

        return GustoConnector(
            client_id="test_client_id",
            client_secret="test_client_secret",
            redirect_uri="http://localhost:8080/callback/gusto",
        )

    def test_connector_is_configured(self, gusto_connector):
        """Test connector configuration check."""
        assert gusto_connector.is_configured is True

    def test_get_authorization_url(self, gusto_connector):
        """Test OAuth authorization URL generation."""
        url = gusto_connector.get_authorization_url(state="test_state")

        assert "gusto" in url.lower() or "oauth" in url.lower()
        assert "client_id=test_client_id" in url
        assert "state=test_state" in url


class TestGustoPayrollTypes:
    """Tests for Gusto payroll data types."""

    def test_payroll_status_enum(self):
        """Test payroll status enum values."""
        from aragora.connectors.accounting import PayrollStatus

        assert PayrollStatus.UNPROCESSED.value == "unprocessed"
        assert PayrollStatus.PROCESSED.value == "processed"

    def test_employment_type_enum(self):
        """Test employment type enum."""
        from aragora.connectors.accounting import EmploymentType

        assert EmploymentType.FULL_TIME is not None
        assert EmploymentType.PART_TIME is not None


class TestGustoMockData:
    """Tests for Gusto mock data functions."""

    def test_get_mock_employees(self):
        """Test mock employee generation."""
        from aragora.connectors.accounting import get_mock_employees

        employees = get_mock_employees()
        assert len(employees) > 0

    def test_get_mock_payroll_run(self):
        """Test mock payroll run generation."""
        from aragora.connectors.accounting import get_mock_payroll_run

        payroll = get_mock_payroll_run()
        assert payroll is not None


# =============================================================================
# Xero Connector Tests
# =============================================================================


class TestXeroConnector:
    """Tests for Xero accounting connector."""

    @pytest.fixture
    def xero_credentials(self):
        """Create Xero credentials instance."""
        from aragora.connectors.accounting import XeroCredentials

        return XeroCredentials(
            client_id="test_client_id",
            client_secret="test_client_secret",
            access_token="test_access_token",
            refresh_token="test_refresh_token",
            tenant_id="test_tenant_id",
        )

    @pytest.fixture
    def xero_connector(self, xero_credentials):
        """Create Xero connector instance."""
        from aragora.connectors.accounting import XeroConnector

        return XeroConnector(credentials=xero_credentials)

    def test_connector_has_credentials(self, xero_connector, xero_credentials):
        """Test connector has credentials set."""
        assert xero_connector.credentials == xero_credentials
        assert xero_connector.credentials.client_id == "test_client_id"

    def test_connector_credentials_tenant_id(self, xero_connector):
        """Test connector credentials tenant ID."""
        assert xero_connector.credentials.tenant_id == "test_tenant_id"


class TestXeroDataTypes:
    """Tests for Xero data types."""

    def test_invoice_type_enum(self):
        """Test invoice type enum."""
        from aragora.connectors.accounting import InvoiceType

        assert InvoiceType is not None

    def test_invoice_status_enum(self):
        """Test invoice status enum."""
        from aragora.connectors.accounting import InvoiceStatus

        assert InvoiceStatus is not None


class TestXeroMockData:
    """Tests for Xero mock data functions."""

    def test_get_mock_xero_invoice(self):
        """Test mock invoice generation."""
        from aragora.connectors.accounting import get_mock_xero_invoice

        invoice = get_mock_xero_invoice()
        assert invoice is not None

    def test_get_mock_xero_contact(self):
        """Test mock contact generation."""
        from aragora.connectors.accounting import get_mock_xero_contact

        contact = get_mock_xero_contact()
        assert contact is not None


# =============================================================================
# Integration Test Helpers
# =============================================================================


class TestAccountingIntegration:
    """Integration tests for accounting connectors working together."""

    def test_all_connectors_importable(self):
        """Test all accounting connectors can be imported."""
        from aragora.connectors.accounting import (
            QuickBooksConnector,
            PlaidConnector,
            GustoConnector,
            XeroConnector,
        )

        assert QuickBooksConnector is not None
        assert PlaidConnector is not None
        assert GustoConnector is not None
        assert XeroConnector is not None

    def test_all_credentials_importable(self):
        """Test all credential classes can be imported."""
        from aragora.connectors.accounting import (
            QBOCredentials,
            PlaidCredentials,
            GustoCredentials,
            XeroCredentials,
        )

        assert QBOCredentials is not None
        assert PlaidCredentials is not None
        assert GustoCredentials is not None
        assert XeroCredentials is not None

    def test_all_mock_functions_available(self):
        """Test all mock data functions are available."""
        from aragora.connectors.accounting import (
            get_mock_customers,
            get_mock_transactions,
            get_mock_accounts,
            get_mock_bank_transactions,
            get_mock_employees,
            get_mock_payroll_run,
            get_mock_xero_invoice,
            get_mock_xero_contact,
        )

        # Just verify they're callable
        assert callable(get_mock_customers)
        assert callable(get_mock_transactions)
        assert callable(get_mock_accounts)
        assert callable(get_mock_bank_transactions)
        assert callable(get_mock_employees)
        assert callable(get_mock_payroll_run)
        assert callable(get_mock_xero_invoice)
        assert callable(get_mock_xero_contact)
